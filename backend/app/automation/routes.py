"""Exploration endpoints. Paths sit under /runtime-sessions so the RUNTIME_READ/RUNTIME_WRITE permissions apply."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from app.api import session, get
from app.models import AnalysisRun, Application
from . import explore, jobs
from .models import AutomationJob
from .runner import Runner, RunnerError

router = APIRouter(prefix='/api/v1', tags=['Automated exploration'])


@router.get('/applications/{app_id}/runtime-sessions/automation')
def runner_status(app_id: str, request: Request, db=Depends(session)):
    get(db, Application, app_id)
    runner = Runner(request.app.state.config, getattr(request.app.state, 'runner_transport', None))
    if not runner.configured:
        return dict(configured=False, reachable=False, reason='RUNNER_TOKEN is not set for ArchIntel; start the runner with scripts/runner-start.sh.')
    try:
        return dict(configured=True, reachable=True, **runner.health())
    except RunnerError as error:
        return dict(configured=True, reachable=False, reason=error.code)


@router.post('/applications/{app_id}/runtime-sessions/explore', status_code=202)
async def start_exploration(app_id: str, request: Request, file: UploadFile = File(...), analysis_id: str = Form(...),
                            max_pages: int = Form(40), max_forms: int = Form(12), mode: str = Form('DEEP'),
                            confirm_disposable_data: bool = Form(False), db=Depends(session)):
    get(db, Application, app_id)
    run = get(db, AnalysisRun, analysis_id)
    if run.application_id != app_id or run.status != 'COMPLETED' or not run.result:
        raise HTTPException(409, 'Choose a completed static analysis of this application.')
    if not confirm_disposable_data:
        raise HTTPException(422, 'Exploration submits forms and changes data. Confirm that the application uses a disposable test database.')
    if mode not in ('BOUNDARY', 'STANDARD', 'DEEP') or not 1 <= max_pages <= 200 or not 0 <= max_forms <= 60:
        raise HTTPException(422, 'Use mode BOUNDARY, STANDARD or DEEP, 1-200 pages and 0-60 forms.')
    if not (file.filename or '').lower().endswith(('.jar', '.war')):
        raise HTTPException(422, 'Upload the runnable application JAR or WAR.')
    limit = request.app.state.config.max_upload_mb * 1024 ** 2
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(413, 'The runnable artifact exceeds the upload limit.')
    if content[:2] != b'PK':
        raise HTTPException(422, 'The file is not a JAR or WAR archive.')
    if not Runner(request.app.state.config).configured:
        raise HTTPException(503, 'The runner is not configured: set RUNNER_TOKEN for ArchIntel and start the runner.')
    running = db.scalar(select(AutomationJob).where(AutomationJob.application_id == app_id, AutomationJob.kind == 'EXPLORE', AutomationJob.state.in_(['QUEUED', 'RUNNING'])))
    if running:
        raise HTTPException(409, 'An exploration of this application is already running.')
    job = explore.create(db, request.state.identity, app_id, analysis_id, bytes(content),
                         dict(max_pages=max_pages, max_forms=max_forms, mode=mode, artifact_name=file.filename[:200]))
    jobs.spawn(job.id, explore.run, request.app.state.sessions, request.app.state.config, job.id, bytes(content))
    return jobs.view(job)


@router.get('/applications/{app_id}/runtime-sessions/explorations')
def explorations(app_id: str, db=Depends(session)):
    get(db, Application, app_id)
    rows = db.scalars(select(AutomationJob).where(AutomationJob.application_id == app_id, AutomationJob.kind == 'EXPLORE')
                      .order_by(AutomationJob.created_at.desc()).limit(20))
    return dict(items=[jobs.view(r) for r in rows])


# ---- Local conversion trial (Modernization page) -------------------------------------------------------------
from pydantic import BaseModel, ConfigDict, Field
from app.access.models import Principal, SourceGrant, SourceRepository
from app.evidence.routes import owned as version_owned
from app.modernization import service as planning
from . import convert


class ConversionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str = Field(min_length=1, max_length=80)
    repository_id: str = Field(min_length=36, max_length=36)
    acknowledgement: str = Field(max_length=120)


def _plan(db, request, vid, aid):
    version = version_owned(db, request, vid)
    return version, planning.owned(db, version, aid)


@router.get('/architecture-versions/{vid}/modernization/{aid}/conversions/repositories')
def conversion_repositories(vid: str, aid: str, request: Request, db=Depends(session)):
    version, _ = _plan(db, request, vid, aid)
    identity = request.state.identity
    grants = {g.repository_id for g in db.scalars(select(SourceGrant).where(SourceGrant.principal_id == identity['id']))}
    rows = db.scalars(select(SourceRepository).where(SourceRepository.application_id == version.application_id, SourceRepository.tenant_id == identity['tenant_id']))
    return dict(items=[dict(id=r.id, name=r.name, commit=r.commit, granted=r.id in grants) for r in rows])


@router.get('/architecture-versions/{vid}/modernization/{aid}/conversions/preconditions')
def conversion_preconditions(vid: str, aid: str, candidate_id: str, request: Request, repository_id: str = '', db=Depends(session)):
    version, plan = _plan(db, request, vid, aid)
    rows = convert.preconditions(db, request.app.state.config, request.state.identity, version, plan, candidate_id, repository_id)
    return dict(ready=all(r['met'] for r in rows), items=rows, model=request.app.state.config.claude_model, limitations=convert.LIMITATIONS)


@router.post('/architecture-versions/{vid}/modernization/{aid}/conversions', status_code=202)
def start_conversion(vid: str, aid: str, body: ConversionInput, request: Request, db=Depends(session)):
    version, plan = _plan(db, request, vid, aid)
    identity = dict(request.state.identity)
    job = convert.create(db, request.app.state.config, identity, version, plan, body.candidate_id, body.repository_id, body.acknowledgement)
    jobs.spawn(job.id, convert.run, request.app.state.sessions, request.app.state.config, job.id, identity)
    return jobs.view(job)


@router.get('/architecture-versions/{vid}/modernization/{aid}/conversions')
def conversions(vid: str, aid: str, request: Request, db=Depends(session)):
    version, plan = _plan(db, request, vid, aid)
    rows = db.scalars(select(AutomationJob).where(AutomationJob.application_id == version.application_id, AutomationJob.kind == 'CONVERT')
                      .order_by(AutomationJob.created_at.desc()).limit(20))
    return dict(items=[jobs.view(r) for r in rows if r.document.get('plan_id') == plan.id])


def _conversion(db, request, vid, aid, job_id):
    _, plan = _plan(db, request, vid, aid)
    job = get(db, AutomationJob, job_id)
    if job.kind != 'CONVERT' or job.document.get('plan_id') != plan.id:
        raise HTTPException(404, 'Conversion not found for this plan.')
    return job


@router.get('/architecture-versions/{vid}/modernization/{aid}/conversions/{job_id}/files/{name:path}')
def conversion_file(vid: str, aid: str, job_id: str, name: str, request: Request, db=Depends(session)):
    job = _conversion(db, request, vid, aid, job_id)
    principal = db.get(Principal, request.state.identity['id'])
    if not principal or 'SOURCE_READ' not in principal.permissions:
        raise HTTPException(403, 'Generated code is derived from source; source-read permission is required to view it.')
    entry = next((f for f in (job.document.get('generation') or {}).get('files', []) if f['path'] == name), None)
    if not entry:
        raise HTTPException(404, 'This file is not part of the generated service.')
    from pathlib import Path
    import hashlib
    root = (Path(request.app.state.config.data_dir) / 'conversions' / job.id / job.document['service_name']).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404, 'This file is not part of the generated service.')
    content = target.read_text(encoding='utf-8')
    if hashlib.sha256(content.encode()).hexdigest() != entry['sha256']:
        raise HTTPException(409, 'The generated file changed after it was recorded.')
    return dict(path=name, sha256=entry['sha256'], content=content, rationale=entry['rationale'])


@router.delete('/architecture-versions/{vid}/modernization/{aid}/conversions/{job_id}/service')
def stop_conversion_service(vid: str, aid: str, job_id: str, request: Request, db=Depends(session)):
    job = _conversion(db, request, vid, aid, job_id)
    try:
        Runner(request.app.state.config, getattr(request.app.state, 'runner_transport', None)).stop_service(job.document['service_name'])
    except RunnerError as error:
        if error.code != 'SERVICE_NOT_FOUND':
            raise HTTPException(502, error.code)
    document = dict(job.document)
    document['service'] = dict(document.get('service') or {}, state='STOPPED')
    job.document = document
    db.commit()
    return jobs.view(job)


# ---- Promotion: a reviewed hand-off, never a deployment ------------------------------------------------------
from fastapi.responses import Response
from . import promotion


class PromotionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: str = Field(max_length=40)
    note: str = Field(max_length=2000)
    differences_reviewed: bool = False


@router.post('/architecture-versions/{vid}/modernization/{aid}/conversions/{job_id}/promotion')
def promote(vid: str, aid: str, job_id: str, body: PromotionInput, request: Request, db=Depends(session)):
    job = _conversion(db, request, vid, aid, job_id)
    document = dict(job.document)
    document['promotion'] = promotion.decide(job, request.state.identity, body.decision, body.note, body.differences_reviewed)
    job.document = document
    db.commit()
    return jobs.view(job)


@router.get('/architecture-versions/{vid}/modernization/{aid}/conversions/{job_id}/package')
def deployment_package(vid: str, aid: str, job_id: str, request: Request, db=Depends(session)):
    job = _conversion(db, request, vid, aid, job_id)
    principal = db.get(Principal, request.state.identity['id'])
    if not principal or 'SOURCE_READ' not in principal.permissions:
        raise HTTPException(403, 'The package contains generated code; source-read permission is required.')
    content = promotion.package(job, request.app.state.config.data_dir)
    name = f"{job.document['service_name']}-handoff.zip"
    return Response(content, media_type='application/zip', headers={'content-disposition': f'attachment; filename="{name}"', 'cache-control': 'no-store'})
