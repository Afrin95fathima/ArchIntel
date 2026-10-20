"""Read-only, commit-pinned Git context. Never executes source, hooks or model calls."""
from pathlib import Path
import os
import stat
import subprocess
from fastapi import HTTPException
from sqlalchemy import select
from .models import SourceRepository, SourceGrant, Principal
from .schemas import safe_path
from .core import digest, latest_policy, record


def repository_path(raw, settings):
    path = Path(raw).absolute()
    # Reject junctions/symlinks before resolving; require a normal owned checkout.
    for part in (path, *path.parents):
        if part.exists():
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Repository paths cannot contain links or junctions.')
    resolved = path.resolve(strict=True)
    roots = settings.source_repository_roots or [settings.data_dir / 'source-repositories']
    if not any(resolved.is_relative_to(Path(root).resolve()) and resolved != Path(root).resolve() for root in roots):
        raise ValueError('Repository must be below an operator-configured source repository root.')
    gitdir = resolved / '.git'
    if not gitdir.is_dir() or gitdir.is_symlink() or getattr(gitdir.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError('Register a normal checkout with its own .git directory.')
    return resolved


def git(path, *args):
    # Inherited GIT_* variables could redirect a repository/object store.
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0')
    result = subprocess.run(['git', '--no-pager', '--no-replace-objects', '-C', str(path), *args],
                            capture_output=True, timeout=15, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('Pinned repository object is unavailable or invalid.')
    return result.stdout


def matches(path, prefixes):
    return any(path.startswith(prefix) if prefix.endswith('/') else path == prefix for prefix in prefixes)


def read_context(db, request, body, *, task_scope=False):
    identity = request.state.identity
    tenant, actor = identity['tenant_id'], identity['id']
    details = dict(purpose=body.purpose, requested_files=body.files, permitted_files=[],
                   denied_files=[], destination=body.destination, commit=body.commit)
    outcome, reason, files = 'DENY', 'No matching source authorization.', []
    try:
        principal = db.get(Principal, actor)
        if not principal or not principal.active or 'SOURCE_READ' not in principal.permissions:
            raise ValueError('Source permission was revoked.')
        repository = db.get(SourceRepository, body.repository_id)
        policy = latest_policy(db, tenant)
        document = policy.document if policy else {}
        details['policy_revision'] = policy.revision if policy else 0
        if not repository or repository.tenant_id != tenant:
            raise ValueError('Repository not found or not authorized.')
        if body.operation != 'SOURCE_READ' or body.destination != 'LOCAL_CONTEXT':
            raise ValueError('Phase 1 only permits local read-only context; model/export/write operations are denied.')
        if not document.get('source_read_enabled', False):
            raise ValueError('Source access is disabled by workspace policy.')
        if repository.commit != body.commit:
            raise ValueError('The requested commit differs from the registered revision.')
        grant = db.scalar(select(SourceGrant).where(SourceGrant.principal_id == actor,
                                                    SourceGrant.repository_id == repository.id))
        if not grant:
            raise ValueError('An explicit repository scope grant is required, including for administrators.')
        paths = list(dict.fromkeys(safe_path(p) for p in body.files))
        if task_scope and not document.get('transformation_enabled', False):
            raise ValueError('Source tasks are disabled by workspace policy.')
        max_files = document.get('max_task_files', 100) if task_scope else document['max_files']
        max_bytes = document.get('max_task_bytes', 1048576) if task_scope else document['max_bytes']
        details['scope_type'] = 'BOUNDED_TASK' if task_scope else 'READ_CONTEXT'
        if len(paths) > max_files:
            raise ValueError('Requested context exceeds the file limit.')
        for path in paths:
            # Never release Git internals, dotenv files, or common private key files.
            pieces = path.split('/')
            sensitive = any(p.lower() in ('.git', '.env', 'id_rsa', 'id_ed25519') or p.lower().startswith('.env.') for p in pieces)
            if sensitive or not matches(path, grant.allowed_paths) or matches(path, grant.protected_paths + document['protected_paths']):
                raise ValueError('At least one requested file is outside permitted scope or is protected.')
        path = repository_path(repository.path, request.app.state.config)
        if git(path, 'cat-file', '-t', repository.commit).strip() != b'commit':
            raise ValueError('The registered object is not a commit.')
        total = 0
        for name in paths:
            entry = git(path, 'ls-tree', '-z', repository.commit, '--', ':(literal)'+name).rstrip(b'\0')
            if b'\0' in entry or b'\t' not in entry:
                raise ValueError('Requested file is unavailable.')
            info, actual = entry.split(b'\t', 1)
            mode, kind, blob = info.split(b' ')
            if mode not in (b'100644', b'100755') or kind != b'blob' or actual.decode('utf-8') != name:
                raise ValueError('Only regular committed files are supported; links and submodules are denied.')
            size = int(git(path, 'cat-file', '-s', blob.decode()))
            total += size
            if total > max_bytes:
                raise ValueError('Requested context exceeds the byte limit.')
            content = git(path, 'cat-file', 'blob', blob.decode()).decode('utf-8')
            if '\0' in content:
                raise ValueError('Binary source context is not supported.')
            files.append(dict(path=name, content=content, sha256=digest(content), bytes=size))
        outcome, reason = 'ALLOW', 'SCOPE_AND_POLICY_PERMIT: explicit scope and workspace policy permit this pinned local context.'
        details['permitted_files'] = paths
    except (ValueError, OSError, subprocess.SubprocessError, UnicodeError):
        details['denied_files'] = body.files
        reason = 'REQUEST_DENIED: check repository, pinned commit, scope, policy and context limits.'
    details['reason'] = reason
    details['bytes'] = sum(f['bytes'] for f in files) if outcome == 'ALLOW' else 0
    # Close read transaction before separate durable audit commit (SQLite included).
    db.rollback()
    event_id = record(request.app.state.sessions, tenant, actor, 'SOURCE_READ', outcome,
                      resource=body.repository_id, details=details, request_id=request.state.request_id)
    if outcome != 'ALLOW':
        raise HTTPException(403, reason)
    return dict(request_id=event_id, decision=outcome, reason=reason, commit=body.commit,
                policy_revision=details['policy_revision'], files=files, external_transfer=False,
                limitations=['Local authorized read only. No model dispatch or code execution. Sensitive-content filtering is Phase 2.'])
