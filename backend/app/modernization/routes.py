import re
from types import SimpleNamespace
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response
from sqlalchemy import select
from app.api import session, get
from app.models import AnalysisRun, Application
from app.evidence.routes import owned as version_owned
from app.evidence.models import Projection
from app.evidence.service import LOCK
from app.evidence import projection
from app.runtime.models import RuntimeSession
from app.reports.modernization_pdf import render_modernization_report
from .models import Assessment
from .schemas import PlanInput, ReviewInput, Question
from . import service

router = APIRouter(prefix='/api/v1/architecture-versions/{vid}/modernization', tags=['Modernization intelligence'])


@router.post('/preview')
def preview(vid: str, body: PlanInput, request: Request, db=Depends(session)):
    with LOCK:
        version = version_owned(db, request, vid)
        return service.create(db, version, body, request.state.identity['id'], request.app.state.config, preview=True)


@router.post('', status_code=201)
def create(vid: str, body: PlanInput, request: Request, db=Depends(session)):
    with LOCK:
        version = version_owned(db, request, vid)
        item = service.create(db, version, body, request.state.identity['id'], request.app.state.config)
        return service.view(db, version, item)


@router.get('')
def listing(vid: str, request: Request, db=Depends(session)):
    version_owned(db, request, vid)
    return [dict(id=a.id, created_at=a.created_at, strategy=a.document['target']['strategy'], objective=a.document['target']['objective'])
            for a in db.scalars(select(Assessment).where(Assessment.version_id == vid).order_by(Assessment.created_at.desc()).limit(100))]


@router.get('/{aid}')
def read(vid: str, aid: str, request: Request, db=Depends(session)):
    version = version_owned(db, request, vid)
    return service.view(db, version, service.owned(db, version, aid))


@router.get('/{aid}/export')
def export(vid: str, aid: str, request: Request, db=Depends(session)):
    version = version_owned(db, request, vid)
    return service.owned(db, version, aid).document


@router.get('/{aid}/report.pdf')
def report_pdf(vid: str, aid: str, request: Request, db=Depends(session)):
    version = version_owned(db, request, vid)
    assessment = service.owned(db, version, aid)
    run = get(db, AnalysisRun, version.analysis_id)
    application = get(db, Application, version.application_id)
    session_ids = version.manifest.get('runtime_session_ids', [])
    sessions = list(db.scalars(select(RuntimeSession).where(RuntimeSession.id.in_(session_ids)).order_by(RuntimeSession.created_at))) if session_ids else []
    job = db.scalar(select(Projection).where(Projection.version_id == version.id))
    projection_state = dict(state=job.state, attempts=job.attempts, error_code=job.error_code) if job else dict(state='UNAVAILABLE')
    assessment_report = SimpleNamespace(id=assessment.id, document=assessment.document, reviews=service.reviews(db, assessment.id))
    pdf = render_modernization_report(application, run, version, assessment_report, sessions, projection_state)
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '-', application.name).strip('-')[:60] or 'application'
    return Response(pdf, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="archintel-{safe_name}-{aid[:8]}-report.pdf"'})


@router.post('/{aid}/review')
def review(vid: str, aid: str, body: ReviewInput, request: Request, db=Depends(session)):
    with LOCK:
        version = version_owned(db, request, vid)
        return service.review(db, version, service.owned(db, version, aid), body, request.state.identity['id'])


@router.post('/{aid}/explain')
def explain(vid: str, aid: str, body: Question, request: Request, db=Depends(session)):
    version = version_owned(db, request, vid)
    return service.answer(service.owned(db, version, aid), body, request, db)


@router.get('/{aid}/graph')
def graph(vid: str, aid: str, request: Request, limit: int = Query(150, ge=1, le=500), root: str | None = Query(None, max_length=36), db=Depends(session)):
    version = version_owned(db, request, vid)
    return projection.query(request.app.state.config, service.graph_item(service.owned(db, version, aid)), limit, root)


@router.post('/{aid}/projection/rebuild')
def rebuild(vid: str, aid: str, request: Request, db=Depends(session)):
    with LOCK:
        version = version_owned(db, request, vid)
        return service.rebuild(db, service.owned(db, version, aid), request.app.state.config)
