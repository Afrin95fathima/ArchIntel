import re
import hmac
import logging
from uuid import uuid4
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.models import now
from app.runtime.models import RuntimeSession
from .models import Credential, Principal
from .core import COOKIE, csrf, digest, utc, record

PUBLIC = {('/api/v1/health', 'GET'), ('/api/v1/ready', 'GET'),
          ('/api/v1/security/status', 'GET'), ('/api/v1/security/bootstrap', 'POST'),
          ('/api/v1/security/login', 'POST')}
INGEST = re.compile(r'^/api/v1/runtime-sessions/([a-zA-Z0-9-]+)/v1/traces$')


def permission(path, method):
    if path in ('/api/v1/security/me', '/api/v1/security/logout', '/api/v1/security/password'):
        return None
    if path == '/api/v1/security/ai/source-query':
        return 'SOURCE_READ'
    if path == '/api/v1/security/ai/invocations':
        return 'AUDIT_READ'
    if path.startswith('/api/v1/security/context'):
        return 'SOURCE_READ'
    if path.startswith('/api/v1/security/audit'):
        return 'AUDIT_READ'
    if path.startswith('/api/v1/security/') or path == '/api/v1/runtime/retention/purge':
        return 'SECURITY_ADMIN'
    runtime = '/runtime-sessions' in path or '/architecture/unified' in path
    read = method in ('GET', 'HEAD') or path.endswith('/assistant/query') or ('/modernization/' in path and path.endswith('/explain')) \
        or ('/insight/' in path and (path.endswith('/explain') or path.endswith('/assistant/chat')))
    return ('RUNTIME_' if runtime else 'ANALYSIS_') + ('READ' if read else 'WRITE')


def authenticate(request):
    sessions = request.app.state.sessions
    path, method = request.url.path, request.method
    match = INGEST.fullmatch(path) if method == 'POST' else None
    auth = request.headers.get('authorization', '')
    bearer = auth[7:] if auth.startswith('Bearer ') else ''
    identity = None
    with sessions() as db:
        if match:
            item = db.get(RuntimeSession, match[1])
            if item and bearer and hmac.compare_digest(item.token_hash, digest(bearer)):
                identity = dict(id='runtime:'+item.id, tenant_id=item.tenant_id, permissions=[], kind='INGESTION')
        else:
            token = bearer or request.cookies.get(COOKIE, '')
            credential = db.get(Credential, digest(token)) if token else None
            if credential and utc(credential.expires_at) > now() and credential.kind == ('SERVICE' if bearer else 'HUMAN'):
                principal = db.get(Principal, credential.principal_id)
                if principal and principal.active:
                    identity = dict(id=principal.id, username=principal.username, tenant_id=principal.tenant_id,
                                    permissions=list(principal.permissions), kind=principal.kind,
                                    platform_owner=principal.platform_owner)
                    if not bearer and method not in ('GET', 'HEAD', 'OPTIONS'):
                        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf(token)):
                            record(sessions, principal.tenant_id, principal.id, 'CSRF', 'DENY', resource=path)
                            raise HTTPException(403, 'Refresh the page before submitting this request.')
        if not identity:
            record(sessions, 'local', 'anonymous', 'AUTHENTICATE', 'DENY', resource=path[:250])
            raise HTTPException(401, 'Sign in to access ArchIntel.')
    required = None if match else permission(path, method)
    if required and required not in identity['permissions']:
        record(sessions, identity['tenant_id'], identity['id'], required, 'DENY', resource=path[:250])
        raise HTTPException(403, 'Your identity does not have permission for this operation.')
    request.state.identity = identity
    request.state.request_id = str(uuid4())
    # Persist intent before dispatch. Source gateway additionally commits its
    # exact permitted/denied manifest before releasing any bytes.
    if method not in ('GET', 'HEAD', 'OPTIONS') and not match:
        record(sessions, identity['tenant_id'], identity['id'], required or 'SESSION', 'REQUESTED',
               resource=path[:250], request_id=request.state.request_id)


async def access_boundary(request, call_next):
    path, method = request.url.path, request.method
    protected = path.startswith('/api/') or path in ('/docs', '/redoc', '/openapi.json')
    try:
        if protected and method != 'OPTIONS':
            if (path, method) not in PUBLIC:
                await run_in_threadpool(authenticate, request)
            elif method == 'POST' and request.headers.get('x-archintel-request') != '1':
                raise HTTPException(403, 'Use the ArchIntel sign-in form or API client header.')
            if (path.startswith('/api/v1/security/') or '/architecture-versions' in path or '/transformation/' in path) and method == 'POST':
                maximum=65536 if path.startswith('/api/v1/security/') else 2*1024*1024
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > maximum:
                        raise HTTPException(413, 'Request body exceeds the permitted size.')
                request._body = bytes(body)
        response = await call_next(request)
        if protected:
            response.headers['Cache-Control'] = 'no-store'
        return response
    except HTTPException as error:
        return JSONResponse({'detail': error.detail}, status_code=error.status_code, headers={'Cache-Control':'no-store'})
    except Exception as error:
        # Authentication/audit storage failure must never permit dispatch.
        # Do not log exception text: database parameters may contain credentials.
        logging.getLogger('archintel.access').error('Request failed closed (%s).', type(error).__name__)
        return JSONResponse({'detail': 'Request could not complete. Check its status before retrying.'}, status_code=503,
                            headers={'Cache-Control':'no-store'})
