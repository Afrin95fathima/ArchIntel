from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import Field
from app.api import session
from app.access.schemas import StrictInput
from app.access.core import LOCK, audit

from .service import diagnostics, support_bundle_preview

router = APIRouter(prefix='/api/v1/system', tags=['Local setup'])


@router.get('/diagnostics', response_model=dict)
def local_diagnostics(request: Request):
    return diagnostics(request.app.state.config, request.app.state.engine,
                       request.app.state.worker.scanner)


class SupportBundleExport(StrictInput):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')


@router.get('/support-bundle/preview', response_model=dict)
def support_preview(request: Request):
    return support_bundle_preview(request.app.state.config, request.app.state.engine,
                                  request.app.state.worker.scanner)


@router.post('/support-bundle/export', response_model=dict)
def support_export(body: SupportBundleExport, request: Request, db=Depends(session)):
    current = support_bundle_preview(request.app.state.config, request.app.state.engine,
                                     request.app.state.worker.scanner)
    if body.fingerprint != current['fingerprint']:
        raise HTTPException(409, 'Support data changed after preview. Review a fresh preview before exporting.')
    with LOCK:
        audit(db, request.state.identity['tenant_id'], request.state.identity['id'],
              'SUPPORT_BUNDLE_EXPORT', 'ALLOW', resource=current['fingerprint'],
              details={'included': current['manifest']['included'], 'upload_performed': False},
              request_id=request.state.request_id)
        db.commit()
    return current
