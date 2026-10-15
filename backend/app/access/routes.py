from datetime import timedelta
import hmac
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from sqlalchemy import delete, select, func
from sqlalchemy.exc import IntegrityError
from app.models import Application, now
from .models import (Workspace, SecurityState, Principal, Credential, LoginWindow,
                     PolicyRevision, SourceRepository, SourceGrant, AuditEvent)
from .core import (LOCK, COOKIE, PERMISSIONS, DEFAULT_POLICY, audit, record, digest,
                   password_hash, password_matches, issue_credential, csrf, utc, request_session, latest_policy)
from .schemas import PermissionsInput, Bootstrap, Login, PasswordChange, PrincipalInput, WorkspaceInput, PolicyInput, RepositoryInput, GrantInput, ContextInput
from .gateway import repository_path, git, read_context

router = APIRouter(prefix='/api/v1/security', tags=['Security'])


def db_session(request: Request):
    yield from request_session(request)


def view(principal):
    return dict(id=principal.id, username=principal.username, kind=principal.kind,
                tenant_id=principal.tenant_id, permissions=principal.permissions, active=principal.active)


def user_password(value):
    if len(value) < 12:
        raise HTTPException(422, 'Use a password with at least 12 characters.')


def login_cookie(response, token, config):
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=config.secure_cookies,
                        max_age=config.session_hours*3600, path='/')


def attempt(db, request, username):
    host = request.client.host if request.client else 'unknown'
    for label, maximum in [('host:'+host, 40), ('name:'+username.lower(), 8)]:
        key = digest(label)
        row = db.get(LoginWindow, key)
        if not row:
            row = LoginWindow(key=key, attempts=0, started_at=now())
            db.add(row)
        if utc(row.started_at) < now()-timedelta(minutes=15):
            row.attempts, row.started_at = 0, now()
        if row.attempts >= maximum:
            raise HTTPException(429, 'Too many sign-in attempts. Try again after 15 minutes.')
        row.attempts += 1
    db.commit()


@router.get('/status')
def status(request: Request):
    with request.app.state.sessions() as db:
        return dict(setup_required=not db.get(SecurityState, 1).initialized)


@router.post('/bootstrap')
def bootstrap(body: Bootstrap, request: Request, response: Response):
    user_password(body.password)
    with LOCK, request.app.state.sessions() as db:
        attempt(db, request, body.username)
        state = db.scalar(select(SecurityState).where(SecurityState.id == 1).with_for_update())
        if state.initialized:
            raise HTTPException(409, 'Initial setup is already complete.')
        if not hmac.compare_digest(state.bootstrap_hash, digest(body.bootstrap_key)):
            audit(db, 'local', 'anonymous', 'BOOTSTRAP', 'DENY')
            db.commit()
            raise HTTPException(403, 'Invalid setup key.')
        principal = Principal(tenant_id='local', username=body.username.lower(), kind='HUMAN',
                              password_hash=password_hash(body.password), permissions=sorted(PERMISSIONS),
                              platform_owner=True)
        db.add(principal)
        db.flush()
        db.add(PolicyRevision(tenant_id='local', revision=1, document=DEFAULT_POLICY))
        state.initialized, state.bootstrap_hash = True, ''
        token = issue_credential(db, principal, 'HUMAN', request.app.state.config.session_hours)
        audit(db, 'local', principal.id, 'BOOTSTRAP', 'ALLOW')
        db.commit()
    login_cookie(response, token, request.app.state.config)
    return dict(**view(principal), csrf_token=csrf(token))


@router.post('/login')
def login(body: Login, request: Request, response: Response):
    with LOCK, request.app.state.sessions() as db:
        attempt(db, request, body.username)
        principal = db.scalar(select(Principal).where(Principal.username == body.username.lower(), Principal.kind == 'HUMAN'))
        valid = password_matches(body.password, principal.password_hash if principal else None)
        if not valid or not principal or not principal.active:
            audit(db, principal.tenant_id if principal else 'local', principal.id if principal else 'anonymous', 'LOGIN', 'DENY')
            db.commit()
            raise HTTPException(401, 'Invalid username or password.')
        token = issue_credential(db, principal, 'HUMAN', request.app.state.config.session_hours)
        audit(db, principal.tenant_id, principal.id, 'LOGIN', 'ALLOW')
        db.commit()
    login_cookie(response, token, request.app.state.config)
    return dict(**view(principal), csrf_token=csrf(token))


@router.get('/me')
def me(request: Request):
    identity = request.state.identity
    token = request.cookies.get(COOKIE, '')
    return dict(identity, csrf_token=csrf(token) if token else None)


@router.post('/logout')
def logout(request: Request, response: Response):
    identity = request.state.identity
    token = request.cookies.get(COOKIE, '')
    with LOCK, request.app.state.sessions.begin() as db:
        db.execute(delete(Credential).where(Credential.token_hash == digest(token), Credential.principal_id == identity['id']))
        audit(db, identity['tenant_id'], identity['id'], 'LOGOUT', 'ALLOW')
    response.delete_cookie(COOKIE, path='/')
    return {'status': 'signed_out'}


@router.get('/principals')
def principals(db=Depends(db_session)):
    return [view(p) for p in db.scalars(select(Principal).order_by(Principal.created_at).limit(200))]


@router.post('/password')
def change_password(body: PasswordChange, request: Request, response: Response, db=Depends(db_session)):
    with LOCK:
        item = db.get(Principal, request.state.identity['id'])
        if not item or not item.active or item.kind != 'HUMAN':
            raise HTTPException(403, 'Only active human accounts can change a password.')
        attempt(db, request, item.username)
        if not password_matches(body.current_password, item.password_hash):
            audit(db, item.tenant_id, item.id, 'PASSWORD_CHANGE', 'DENY')
            db.commit()
            raise HTTPException(403, 'Current password is incorrect.')
        item.password_hash = password_hash(body.new_password)
        db.execute(delete(Credential).where(Credential.principal_id == item.id))
        token = issue_credential(db, item, 'HUMAN', request.app.state.config.session_hours)
        audit(db, item.tenant_id, item.id, 'PASSWORD_CHANGE', 'ALLOW')
        db.commit()
    login_cookie(response, token, request.app.state.config)
    return dict(csrf_token=csrf(token), status='password_changed')


@router.post('/principals', status_code=201)
def create_principal(body: PrincipalInput, request: Request, db=Depends(db_session)):
    if body.kind == 'HUMAN':
        user_password(body.password)
    if body.kind == 'SERVICE' and set(body.permissions) & {'SECURITY_ADMIN'}:
        raise HTTPException(422, 'Service identities cannot administer workspace security.')
    with LOCK:
        principal = Principal(username=body.username.lower(), kind=body.kind,
                              permissions=body.permissions, password_hash=password_hash(body.password) if body.kind == 'HUMAN' else None)
        db.add(principal)
        try:
            db.flush()
            token = issue_credential(db, principal, 'SERVICE', 168) if body.kind == 'SERVICE' else None
            audit(db, principal.tenant_id, request.state.identity['id'], 'CREATE_PRINCIPAL', 'ALLOW', resource=principal.id)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'That username is unavailable.')
    return dict(**view(principal), token=token, token_expires_in_hours=168 if token else None)


@router.post('/principals/{identity}/revoke')
def revoke(identity: str, request: Request, db=Depends(db_session)):
    item = db.get(Principal, identity)
    if not item:
        raise HTTPException(404, 'Principal not found.')
    if item.id == request.state.identity['id'] or item.platform_owner:
        raise HTTPException(409, 'Cannot revoke yourself or the installation owner.')
    with LOCK:
        item.active = False
        db.execute(delete(Credential).where(Credential.principal_id == item.id))
        audit(db, item.tenant_id, request.state.identity['id'], 'REVOKE_PRINCIPAL', 'ALLOW', resource=item.id)
        db.commit()
    return view(item)


@router.post('/workspaces', status_code=201)
def create_workspace(body: WorkspaceInput, request: Request):
    if not request.state.identity.get('platform_owner'):
        raise HTTPException(403, 'Only the installation owner can provision a workspace.')
    with LOCK, request.app.state.sessions() as db:
        workspace = Workspace(id=str(uuid4()), name=body.name)
        db.add(workspace)
        db.flush()
        principal = Principal(tenant_id=workspace.id, username=body.admin_username.lower(), kind='HUMAN',
                              password_hash=password_hash(body.admin_password), permissions=sorted(PERMISSIONS))
        db.add(principal)
        db.add(PolicyRevision(tenant_id=workspace.id, revision=1, document=DEFAULT_POLICY))
        try:
            db.flush()
            audit(db, workspace.id, request.state.identity['id'], 'CREATE_WORKSPACE', 'ALLOW', resource=workspace.id)
            audit(db, request.state.identity['tenant_id'], request.state.identity['id'], 'CREATE_WORKSPACE', 'ALLOW', resource=workspace.id)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'That username is unavailable.')
    return dict(id=workspace.id, name=workspace.name, administrator=principal.username)


@router.get('/policy')
def policy(request: Request, db=Depends(db_session)):
    item = latest_policy(db, request.state.identity['tenant_id'])
    return dict(revision=item.revision, **item.document)


@router.post('/policy')
def update_policy(body: PolicyInput, request: Request, db=Depends(db_session)):
    if 'SECURITY_ADMIN' not in request.state.identity['permissions']:
        raise HTTPException(403, 'Workspace security administration is required to change policy.')
    tenant = request.state.identity['tenant_id']
    with LOCK:
        # Workspace lock serializes revisions on PostgreSQL as well as SQLite.
        db.scalar(select(Workspace).where(Workspace.id == tenant).with_for_update())
        current = latest_policy(db, tenant)
        if body.model_enabled:
            from app.ai.models import ModelProvider
            provider = db.get(ModelProvider, body.model_provider_id or '')
            if not provider or not provider.enabled:
                raise HTTPException(422, 'Select an enabled provider in this workspace.')
        if current.revision != body.expected_revision:
            raise HTTPException(409, 'Policy changed; reload before saving.')
        item = PolicyRevision(revision=current.revision+1, document=body.model_dump(exclude={'expected_revision'}))
        db.add(item)
        db.flush()
        audit(db, tenant, request.state.identity['id'], 'POLICY_CHANGED', 'ALLOW', details={'revision':item.revision})
        db.commit()
    return dict(revision=item.revision, **item.document)


@router.get('/repositories')
def repositories(db=Depends(db_session)):
    return [dict(id=r.id, name=r.name, application_id=r.application_id, commit=r.commit) for r in db.scalars(select(SourceRepository).limit(200))]


@router.post('/repositories', status_code=201)
def repository(body: RepositoryInput, request: Request, db=Depends(db_session)):
    if not db.get(Application, body.application_id):
        raise HTTPException(404, 'Application not found.')
    try:
        path = repository_path(body.path, request.app.state.config)
        if git(path, 'cat-file', '-t', body.commit).strip() != b'commit':
            raise ValueError('Choose a full commit SHA.')
    except (ValueError, OSError) as error:
        raise HTTPException(422, str(error))
    with LOCK:
        item = SourceRepository(**body.model_dump(exclude={'path'}), path=str(path))
        db.add(item)
        db.flush()
        audit(db, item.tenant_id, request.state.identity['id'], 'REGISTER_REPOSITORY', 'ALLOW', resource=item.id, details={'commit':item.commit})
        db.commit()
    return dict(id=item.id, name=item.name, commit=item.commit)


@router.post('/grants')
def grant(body: GrantInput, request: Request, db=Depends(db_session)):
    if not db.get(Principal, body.principal_id) or not db.get(SourceRepository, body.repository_id):
        raise HTTPException(404, 'Principal or repository not found.')
    with LOCK:
        item = db.scalar(select(SourceGrant).where(SourceGrant.principal_id == body.principal_id, SourceGrant.repository_id == body.repository_id))
        if item:
            item.allowed_paths, item.protected_paths = body.allowed_paths, body.protected_paths
        else:
            item = SourceGrant(**body.model_dump())
            db.add(item)
        db.flush()
        audit(db, item.tenant_id, request.state.identity['id'], 'SOURCE_GRANT', 'ALLOW', resource=item.repository_id,
              details=body.model_dump())
        db.commit()
    return dict(id=item.id)


@router.post('/context')
def context(body: ContextInput, request: Request, db=Depends(db_session)):
    # Serialize authorization, source reads and durable audit with policy/grant
    # changes in this single-process deployment. Recheck the principal inside.
    with LOCK:
        return read_context(db, request, body)


@router.get('/audit')
def events(after: int = Query(0, ge=0), db=Depends(db_session)):
    return [dict(e.event, event_hash=e.event_hash, previous_hash=e.previous_hash) for e in db.scalars(
        select(AuditEvent).where(AuditEvent.sequence > after).order_by(AuditEvent.sequence).limit(100))]


@router.get('/audit/verify')
def verify(request: Request, db=Depends(db_session)):
    import json
    head, count = '0'*64, 0
    for item in db.scalars(select(AuditEvent).order_by(AuditEvent.sequence)):
        expected = digest(head + json.dumps(item.event, sort_keys=True, separators=(',', ':')))
        count += 1
        if item.sequence != count or item.previous_hash != head or item.event_hash != expected:
            return dict(valid=False, checked=count)
        head = expected
    workspace = db.get(Workspace, request.state.identity['tenant_id'])
    return dict(valid=workspace.audit_head == head and workspace.audit_sequence == count,
                checked=count, head=head, limitation='Database-owner replacement of the entire chain requires an external trusted checkpoint to detect.')


@router.post('/principals/{identity}/permissions')
def update_permissions(identity: str, body: PermissionsInput, request: Request, db=Depends(db_session)):
    with LOCK:
        item=db.get(Principal,identity)
        if not item or not item.active:
            raise HTTPException(404,'Active principal not found.')
        if item.kind=='SERVICE' and 'SECURITY_ADMIN' in body.permissions:
            raise HTTPException(422,'Service identities cannot administer security.')
        if (item.platform_owner or item.id==request.state.identity['id']) and 'SECURITY_ADMIN' not in body.permissions:
            raise HTTPException(409,'Cannot remove your own or the owner security administration permission.')
        item.permissions=body.permissions
        audit(db,item.tenant_id,request.state.identity['id'],'PERMISSIONS_CHANGED','ALLOW',resource=item.id,details={'permissions':body.permissions})
        db.commit()
    return view(item)
