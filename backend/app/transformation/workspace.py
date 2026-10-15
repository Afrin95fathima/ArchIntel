"""Private Git working directories; never writes a registered customer checkout."""
import hashlib
import os
from pathlib import Path
import re
import stat
from app.access.gateway import git
from app.access.schemas import safe_path


def sha(data): return hashlib.sha256(data).hexdigest()


def relative(name):
    safe_path(name)
    if name.endswith('/') or any(p.lower() in ('.git', '.gitattributes', '.gitmodules', '.lfsconfig', '.env', 'id_rsa', 'id_ed25519') or p.lower().startswith('.env.') or p.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in name.split('/')):
        raise ValueError('Protected or nonportable task path.')
    return name


def no_links(path):
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                raise ValueError('Task storage cannot contain links or junctions.')


def root(config, task):
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,36}', task.tenant_id) or not re.fullmatch(r'[a-f0-9-]{36}', task.id):
        raise ValueError('Invalid task storage identity.')
    base = (config.data_dir / 'transformations').absolute()
    path = base / task.tenant_id / task.id
    no_links(path)
    if not path.resolve().is_relative_to(base.resolve()): raise ValueError('Task path escaped storage root.')
    return path


def file_path(folder, name):
    target = folder / relative(name)
    no_links(target)
    if not target.resolve().is_relative_to(folder.resolve()): raise ValueError('Task path escaped workspace.')
    return target


def inventory(folder):
    result = {}
    for current, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files: no_links(Path(current) / name)
        if Path(current) == folder: dirs[:] = [d for d in dirs if d != '.git']
        for name in files:
            path = Path(current) / name
            key = path.relative_to(folder).as_posix(); relative(key)
            if path.stat().st_size > 33554432: raise ValueError('Unexpected oversized workspace file.')
            result[key] = sha(path.read_bytes())
    return result


def create(config, task, files):
    path = root(config, task)
    if path.exists(): raise ValueError('Task workspace already exists; inspect prior attempt.')
    work = path / 'worktree'; baseline = path / 'baseline'
    work.mkdir(parents=True); baseline.mkdir()
    for f in files:
        for folder in (work, baseline):
            target = file_path(folder, f['path']); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f['content'].encode('utf-8'))
    git(work, 'init', '--template=')
    git(work, 'config', 'core.autocrlf', 'false')
    git(work, 'config', 'core.longpaths', 'true')
    git(work, 'config', 'core.hooksPath', os.devnull)
    git(work, 'add', '-f', '--', *[f['path'] for f in files])
    git(work, '-c', 'user.name=ArchIntel', '-c', 'user.email=local@archintel.invalid', '-c', 'commit.gpgsign=false', 'commit', '-m', 'Authorized pinned source snapshot')
    branch = 'archintel/' + task.id[:12]
    git(work, 'branch', '-M', branch)
    return dict(base_commit=git(work, 'rev-parse', 'HEAD').decode().strip(),
                branch=branch, git_config_sha256=sha((work / '.git/config').read_bytes()),
                baseline={f['path']: f['sha256'] for f in files}, current=inventory(work))


def checked(config, task, recovery=False):
    path = root(config, task); work = path / 'worktree'; baseline = path / 'baseline'
    manifest = task.document['workspace']
    no_links(work / '.git/config')
    if sha((work / '.git/config').read_bytes()) != manifest['git_config_sha256']: raise ValueError('Private Git configuration changed.')
    if inventory(baseline) != manifest['baseline']: raise ValueError('Immutable baseline changed.')
    actual = inventory(work)
    if actual != manifest['current']:
        allowed = task.document.get('recovery_hashes', {}) if recovery else {}
        for name in set(actual) | set(manifest['current']):
            if actual.get(name) not in allowed.get(name, [manifest['current'].get(name)]):
                raise ValueError('Workspace changed outside the reviewed task.')
        if not allowed: raise ValueError('Workspace changed outside the reviewed task.')
    return work


def apply(config, task, edits):
    work = checked(config, task)
    for edit in edits:
        path = file_path(work, edit['path'])
        if edit['operation'] == 'DELETE': path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(edit['content'].encode('utf-8'))
    return inventory(work)


def rollback(config, task):
    # Only manifest-owned regular files are touched. No recursive deletion or Git reset.
    work = checked(config, task, recovery=True); baseline = root(config, task) / 'baseline'
    for name in inventory(work):
        if name not in task.document['workspace']['baseline']: file_path(work, name).unlink()
    for name in task.document['workspace']['baseline']:
        target = file_path(work, name); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_path(baseline, name).read_bytes())
    return inventory(work)
