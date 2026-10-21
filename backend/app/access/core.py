"""Identity primitives, append-only audit and centrally scoped ORM sessions."""
from datetime import timedelta, timezone
import hashlib
import hmac
import json
import secrets
from threading import RLock
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria
from app.models import Identity, now
from app.runtime.models import RuntimeEvent, RuntimeSession
from .models import AuditEvent, Workspace, Principal, Credential, SecurityState, PolicyRevision

LOCK = RLock()  # SQLite writer serialization; PostgreSQL also locks the workspace row.
COOKIE = 'archintel_session'
PERMISSIONS = {'ANALYSIS_READ', 'ANALYSIS_WRITE', 'RUNTIME_READ', 'RUNTIME_WRITE',
               'SOURCE_READ', 'SECURITY_ADMIN', 'AUDIT_READ', 'MODEL_USE_LOCAL'}
DEFAULT_POLICY = dict(source_read_enabled=True, max_files=5, max_bytes=65536, protected_paths=[],
                      external_transfer='DENY', telemetry='DISABLED', gemini_source_transfer_enabled=False, claude_source_transfer_enabled=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17,
                           r=8, p=1, maxmem=256*1024*1024).hex()
    return f'scrypt:{salt}:{value}'


def password_matches(password, encoded):
    # Same work for unknown names, without revealing whether an account exists.
    encoded = encoded or 'scrypt:' + '0'*32 + ':' + '0'*128
    return hmac.compare_digest(password_hash(password, encoded.split(':')[1]), encoded)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def csrf(token):
    return digest('archintel-csrf:' + token)


def initialize(sessions, config):
    path = config.data_dir / 'security-bootstrap.key'
    with LOCK, sessions.begin() as db:
        if db.get(SecurityState, 1):
            return
        # Exclusive creation prevents another startup from replacing the operator key.
        if not path.exists():
            import os
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as target:
                target.write(secrets.token_urlsafe(32))
        db.add(SecurityState(id=1, bootstrap_hash=digest(path.read_text().strip())))


def audit(db, tenant, actor, action, outcome, resource='', details=None, request_id=None):
    workspace = db.scalar(select(Workspace).where(Workspace.id == tenant).with_for_update())
    if not workspace:
        raise RuntimeError('Audit workspace unavailable')
    sequence = workspace.audit_sequence + 1
    payload = dict(request_id=request_id or str(uuid4()), timestamp=now().isoformat(),
                   actor=actor, action=action, outcome=outcome, resource=resource,
                   details=details or {}, tenant_id=tenant, sequence=sequence)
    hashed = digest(workspace.audit_head + json.dumps(payload, sort_keys=True, separators=(',', ':')))
    db.add(AuditEvent(tenant_id=tenant, sequence=sequence, previous_hash=workspace.audit_head,
                      event_hash=hashed, event=payload))
    workspace.audit_sequence, workspace.audit_head = sequence, hashed
    db.flush()
    return payload['request_id']


def record(sessions, tenant, actor, action, outcome, **kwargs):
    with LOCK, sessions.begin() as db:
        return audit(db, tenant, actor, action, outcome, **kwargs)


def latest_policy(db, tenant):
    policy = db.scalar(select(PolicyRevision).where(PolicyRevision.tenant_id == tenant)
                       .order_by(PolicyRevision.revision.desc()))
    return policy


def issue_credential(db, principal, kind, hours):
    token = secrets.token_urlsafe(32)
    db.add(Credential(token_hash=digest(token), principal_id=principal.id, kind=kind,
                      expires_at=now()+timedelta(hours=hours)))
    return token


class ScopedSession(Session):
    """Request-owned session; background maintenance explicitly uses ordinary Session."""


@event.listens_for(ScopedSession, 'do_orm_execute')
def scope(execute):
    tenant = execute.session.info['tenant_id']
    execute.statement = execute.statement.options(
        with_loader_criteria(Identity, lambda cls: cls.tenant_id == tenant, include_aliases=True),
        with_loader_criteria(AuditEvent, lambda cls: cls.tenant_id == tenant, include_aliases=True),
        with_loader_criteria(RuntimeEvent, lambda cls: cls.session_id.in_(
            select(RuntimeSession.id).where(RuntimeSession.tenant_id == tenant)), include_aliases=True))


@event.listens_for(ScopedSession, 'before_flush')
def scope_writes(db, *_):
    tenant = db.info['tenant_id']
    for item in db.new | db.dirty | db.deleted:
        if isinstance(item, Identity):
            if item in db.new and item.tenant_id is None:
                item.tenant_id = tenant
            if item.tenant_id != tenant:
                raise HTTPException(404, 'Record not found.')


def request_session(request):
    with ScopedSession(request.app.state.engine, expire_on_commit=False,
                       info={'tenant_id': request.state.identity['tenant_id']}) as db:
        yield db
