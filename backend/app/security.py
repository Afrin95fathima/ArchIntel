"""Browser request boundary for the local prototype; not account authentication."""
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse


def origin_tuple(value: str):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        return None


async def browser_boundary(request: Request, call_next):
    # Reject untrusted browser reads too: analysis results contain private code
    # metadata. Server-to-server OTLP has no Origin and retains bearer auth.
    if request.url.path.startswith('/api/'):
        origin = request.headers.get('origin')
        same_site = request.headers.get('sec-fetch-site')
        allowed = {origin_tuple(str(request.base_url))}
        allowed.update(origin_tuple(value) for value in request.app.state.config.cors_origins)
        allowed.discard(None)
        if (origin is not None and origin_tuple(origin) not in allowed) or (origin is None and same_site == 'cross-site'):
            return JSONResponse({'detail': 'Browser origin is not allowed.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    return response
