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
    runner = Runner(request.app.state.config)
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
