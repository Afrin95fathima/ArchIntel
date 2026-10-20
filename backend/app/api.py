"""Versioned API. Domain logic lives in services; snapshots remain immutable."""
import io
import json
from pathlib import Path
import shutil
from threading import Lock
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import models as m
from app.schemas import (ProjectInput, ProjectView, ApplicationInput, ApplicationView, ArtifactView,
    AnalysisView, ItemsResponse, GraphResponse, QueryInput, AssistantResponse)
from app.services.ingestion import validate_archive, validate_project_zip, file_hash, ArtifactError, LimitExceeded
from app.services.assistant import answer
from app.config import ROOT
from app.services.engine import VERSION
from app.access.core import request_session

router = APIRouter(prefix='/api/v1')
admission = Lock()


def session(request: Request):
    yield from request_session(request)


def get(db: Session, model, identity: str):
    record = db.get(model, identity)
    if not record or record.tenant_id != db.info['tenant_id']:
        raise HTTPException(404, 'Record not found.')
    return record


def snapshot(db: Session, analysis_id: str) -> dict:
    run = get(db, m.AnalysisRun, analysis_id)
    if run.status != 'COMPLETED' or not run.result:
        raise HTTPException(409, 'Analysis results are not complete yet.')
    return run.result


@router.get('/projects', response_model=list[ProjectView])
def projects(db: Session = Depends(session)):
    return db.scalars(select(m.Project).order_by(m.Project.created_at.desc()).limit(200)).all()


@router.post('/projects', response_model=ProjectView, status_code=201)
def create_project(body: ProjectInput, db: Session = Depends(session)):
    record = m.Project(**body.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get('/applications', response_model=list[ApplicationView])
def applications(project_id: str | None = None, db: Session = Depends(session)):
    statement = select(m.Application).order_by(m.Application.created_at.desc())
    if project_id:
        statement = statement.where(m.Application.project_id == project_id)
    return db.scalars(statement.limit(200)).all()


@router.post('/applications', response_model=ApplicationView, status_code=201)
def create_application(body: ApplicationInput, db: Session = Depends(session)):
    get(db, m.Project, body.project_id)
    record = m.Application(**body.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get('/applications/{application_id}', response_model=ApplicationView)
def application(application_id: str, db: Session = Depends(session)):
    return get(db, m.Application, application_id)


@router.get('/applications/{application_id}/artifacts', response_model=list[ArtifactView])
def artifacts(application_id: str, db: Session = Depends(session)):
    get(db, m.Application, application_id)
    return db.scalars(select(m.Artifact).where(m.Artifact.application_id==application_id).order_by(m.Artifact.created_at.desc()).limit(100)).all()


@router.post('/applications/{application_id}/artifact', response_model=ArtifactView, status_code=201)
async def upload(application_id: str, file: UploadFile, request: Request, db: Session = Depends(session)):
    application = get(db, m.Application, application_id)
    filename = (file.filename or '').replace('\\','/').rsplit('/',1)[-1]
    extension = Path(filename).suffix.lower()
    if extension not in ('.jar','.war','.zip') or len(filename) > 255:
        raise HTTPException(422, 'Choose a Java JAR, WAR, or compiled project ZIP with a filename shorter than 256 characters.')
    config = request.app.state.config
    folder = config.data_dir / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    path, total = folder / (str(uuid4()) + extension), 0
    try:
        with path.open('wb') as target:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > config.max_upload_mb * 1024**2:
                    raise HTTPException(413, dict(code='LIMIT_EXCEEDED',limit='max_upload_size_compressed',configured=config.max_upload_mb*1024**2,observed=total,next_step='Split the artifact by module or ask your administrator to raise max_upload_mb.'))
                target.write(chunk)
        manifest = validate_project_zip(path, config) if extension == '.zip' else validate_archive(path, config)
        record = m.Artifact(application_id=application_id, filename=filename, path=str(path),
            size=total, sha256=file_hash(path), manifest=manifest)
        application.source_type = extension[1:].upper()
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except LimitExceeded as error:
        path.unlink(missing_ok=True)
        raise HTTPException(413, dict(code='LIMIT_EXCEEDED',limit=error.limit,configured=error.configured,observed=error.observed,next_step=error.advice))
    except ArtifactError as error:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(error))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def enqueue(application_id: str, request: Request, db: Session) -> m.AnalysisRun:
    get(db, m.Application, application_id)
    if not request.app.state.worker.scanner.available():
        raise HTTPException(503, 'Scanner runtime is unavailable. Run the setup script.')
    with admission:
        # Capacity belongs to the shared worker, not the requesting workspace.
        # This internal aggregate returns no cross-tenant records to the caller.
        with request.app.state.sessions() as capacity_db:
            active = capacity_db.scalar(select(func.count()).select_from(m.AnalysisRun).where(m.AnalysisRun.status.in_(['QUEUED','RUNNING'])))
        if active >= 4:
            raise HTTPException(429, 'Analysis queue is full. Wait for an existing run to finish.')
        existing = db.scalar(select(m.AnalysisRun).where(m.AnalysisRun.application_id==application_id, m.AnalysisRun.status.in_(['QUEUED','RUNNING'])))
        if existing:
            raise HTTPException(409, 'This application already has an active analysis.')
        artifact = db.scalar(select(m.Artifact).where(m.Artifact.application_id==application_id, m.Artifact.available==True,
            m.Artifact.manifest['transformation_task_id'].as_string().is_(None)).order_by(m.Artifact.created_at.desc()))
        if not artifact or not Path(artifact.path).exists():
            raise HTTPException(409, 'Upload an artifact before starting analysis. Previous artifacts are deleted after processing.')
        run = m.AnalysisRun(application_id=application_id, artifact_id=artifact.id)
        db.add(run)
        db.commit()
        db.refresh(run)
        request.app.state.worker.submit(run.id)
        return run


@router.post('/applications/{application_id}/analysis', response_model=AnalysisView, status_code=202)
def start_analysis(application_id: str, request: Request, db: Session = Depends(session)):
    return enqueue(application_id, request, db)


@router.get('/analyses', response_model=list[AnalysisView])
def analyses(application_id: str | None = None, db: Session = Depends(session)):
    statement = select(m.AnalysisRun).order_by(m.AnalysisRun.created_at.desc())
    if application_id:
        statement = statement.where(m.AnalysisRun.application_id==application_id)
    return db.scalars(statement.limit(200)).all()


@router.get('/analyses/{analysis_id}', response_model=AnalysisView)
@router.get('/analyses/{analysis_id}/status', response_model=AnalysisView)
def analysis(analysis_id: str, db: Session = Depends(session)):
    return get(db, m.AnalysisRun, analysis_id)


@router.get('/analyses/{analysis_id}/summary', response_model=dict)
def summary(analysis_id: str, db: Session = Depends(session)):
    result = snapshot(db, analysis_id)
    return dict(result['summary'], artifact=result['artifact'], scanner=result['scanner'],
        algorithm_version=result['algorithm_version'], limitations=result['limitations'])


@router.get('/analyses/{analysis_id}/graph/{level}', response_model=GraphResponse)
def graph(analysis_id: str, level: str, domain_id: str | None = None, package: str | None = None,
    limit: int = Query(150, ge=1, le=400), db: Session = Depends(session)):
    result = snapshot(db, analysis_id)
    if level not in ('classes','packages','domains'):
        raise HTTPException(422, 'Graph level must be domains, packages or classes.')
    nodes = result[level]
    edge_key = {'classes':'edges','packages':'package_edges','domains':'domain_edges'}[level]
    edges = result[edge_key]
    if domain_id:
        if level=='classes':
            nodes = [n for n in nodes if n['domain_id']==domain_id]
        elif level=='packages':
            nodes = [n for n in nodes if domain_id in n['domain_ids']]
        else:
            nodes = [n for n in nodes if n['id']==domain_id]
    if package and level=='classes':
        nodes = [n for n in nodes if n['package_name']==package]
    total = len(nodes)
    all_ids = {n['id'] for n in nodes}
    all_edges = [e for e in edges if e['source'] in all_ids and e['target'] in all_ids]
    nodes = nodes[:limit]
    ids = {n['id'] for n in nodes}
    visible = [e for e in all_edges if e['source'] in ids and e['target'] in ids]
    return GraphResponse(nodes=nodes, edges=visible[:2000], total_nodes=total, total_edges=len(all_edges),
        truncated=total>limit or len(visible)>2000)


@router.get('/limits', response_model=dict)
def effective_limits(request: Request):
    config=request.app.state.config
    values={
        'max_upload_size_compressed':config.max_upload_mb*1024**2,
        'max_uncompressed_size':config.max_expanded_mb*1024**2,
        'max_archive_entries':config.max_archive_entries,
        'max_compression_ratio':config.max_compression_ratio,
        'allowed_artifact_types':['JAR','WAR','ZIP'],
        'max_classes_per_scan':config.max_classes,
        'max_edges_per_scan':config.max_edges,
        'max_packages_per_scan':config.max_packages_per_scan,
        'max_scan_duration_seconds':config.scan_timeout_seconds,
        'max_temp_disk_per_job_bytes':config.max_job_disk_mb*1024**2,
        'runtime_max_body_bytes':config.runtime_max_body_bytes,
        'runtime_max_batch_spans':config.runtime_max_batch_spans,
        'runtime_max_session_spans':config.runtime_max_session_spans,
        'runtime_max_span_size_bytes':config.runtime_max_span_size_bytes,
        'runtime_max_session_duration_hours':config.runtime_max_session_duration_hours,
        'runtime_raw_trace_retention_hours':config.runtime_raw_trace_retention_hours,
    }
    return dict(limits=values,validation='Limits marked as defaults in config.py are unvalidated placeholders; capacity claims need the ramp tests in scripts/ramp_ingestion_limits.py.')


@router.get('/analyses/{analysis_id}/domains', response_model=ItemsResponse)
def domains(analysis_id: str, db: Session = Depends(session)):
    items = snapshot(db, analysis_id)['domains']
    return ItemsResponse(items=items, total=len(items))


@router.get('/analyses/{analysis_id}/domains/dependency-matrix', response_model=dict)
def domain_dependency_matrix(analysis_id: str, db: Session = Depends(session)):
    result = snapshot(db, analysis_id)
    return result.get('domain_dependency_matrix', dict(domain_ids=[], rows=[], matrix_complete=False,
        reason='This historical analysis predates the domain dependency matrix. Run a new static analysis.'))


@router.get('/analyses/{analysis_id}/domains/{domain_id}', response_model=dict)
def domain(analysis_id: str, domain_id: str, db: Session = Depends(session)):
    result = snapshot(db, analysis_id)
    record = next((d for d in result['domains'] if d['id']==domain_id), None)
    if not record:
        raise HTTPException(404, 'Domain not found in this analysis.')
    matrix=result.get('domain_dependency_matrix',{})
    ownership=result.get('data_ownership',{})
    inventory=result.get('entry_points',{})
    return dict(record, modernization=next(a for a in result['modernization'] if a['domain_id']==domain_id),
        issues=[i for i in result['issues'] if domain_id in i['domain_ids']],
        dependency_matrix=dict(per_domain=matrix.get('per_domain',{}).get(domain_id,{}),
            incoming=[row for row in matrix.get('rows',[]) if row['target_domain_id']==domain_id],
            outgoing=[row for row in matrix.get('rows',[]) if row['source_domain_id']==domain_id],
            top_boundary_classes=matrix.get('top_boundary_classes',[])),
        data_ownership=ownership.get('per_domain',{}).get(domain_id,dict(ownership='UNKNOWN')),
        entry_points=inventory.get('by_domain',{}).get(domain_id,[]))


@router.get('/analyses/{analysis_id}/issues', response_model=ItemsResponse)
def issues(analysis_id: str, severity: str | None=None, issue_type: str | None=None,
    domain_id: str | None=None, package: str | None=None,
    offset: int=Query(0,ge=0), limit: int=Query(100,ge=1,le=500), db: Session=Depends(session)):
    result = snapshot(db, analysis_id)
    items = result['issues']
    if severity: items = [i for i in items if i['severity']==severity]
    if issue_type: items = [i for i in items if i['issue_type']==issue_type]
    if domain_id: items = [i for i in items if domain_id in i['domain_ids']]
    if package:
        items = [i for i in items if i['entity_id']==package or i['entity_id'].startswith(package+'.') or package in i['evidence'].get('impacted_packages',[])]
    return ItemsResponse(items=items[offset:offset+limit], total=len(items))


@router.get('/analyses/{analysis_id}/metrics', response_model=ItemsResponse)
def metrics(analysis_id: str, db: Session=Depends(session)):
    items = snapshot(db,analysis_id)['metrics']
    return ItemsResponse(items=items,total=len(items))


@router.get('/analyses/{analysis_id}/cycles', response_model=ItemsResponse)
def cycles(analysis_id: str, db: Session=Depends(session)):
    items = snapshot(db,analysis_id)['cycles']
    return ItemsResponse(items=items,total=len(items))


@router.get('/analyses/{analysis_id}/modernization', response_model=ItemsResponse)
@router.get('/analyses/{analysis_id}/modernization/sequence', response_model=ItemsResponse)
def modernization(analysis_id: str, db: Session=Depends(session)):
    items = snapshot(db,analysis_id)['modernization']
    return ItemsResponse(items=items,total=len(items))


@router.get('/analyses/{analysis_id}/dependencies/external', response_model=ItemsResponse)
def external_dependencies(analysis_id: str, offset: int=Query(0,ge=0), limit: int=Query(100,ge=1,le=500), db: Session=Depends(session)):
    items = snapshot(db,analysis_id)['external_edges']
    return ItemsResponse(items=items[offset:offset+limit],total=len(items))


@router.post('/analyses/{analysis_id}/assistant/query', response_model=AssistantResponse)
def assistant(analysis_id: str, body: QueryInput, request: Request, db: Session=Depends(session)):
    return answer(snapshot(db,analysis_id), body.question, body.domain_id, request.app.state.config, request, db, analysis_id)


@router.get('/analyses/{analysis_id}/export')
def export_analysis(analysis_id: str, db: Session=Depends(session)):
    result = snapshot(db,analysis_id)
    return Response(json.dumps(dict(analysis_id=analysis_id, **result), indent=2), media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="archintel-{analysis_id}.json"'})


@router.get('/analyses/{analysis_id}/evidence/{evidence_id:path}', response_model=dict)
def evidence(analysis_id: str, evidence_id: str, db: Session=Depends(session)):
    result = snapshot(db, analysis_id)
    if evidence_id == 'summary':
        return result['summary']
    prefix, _, identity = evidence_id.partition(':')
    if prefix in ('assessment','coupling','database'):
        if prefix == 'assessment':
            record = next((a for a in result['modernization'] if a['domain_id']==identity), None)
        else:
            domain = next((d for d in result['domains'] if d['id']==identity), None)
            record = domain['metrics' if prefix=='coupling' else 'database'] if domain else None
    else:
        record = next((item for key in ('domains','issues','cycles') for item in result[key] if item['id']==evidence_id), None)
    if record is None:
        raise HTTPException(404, 'Evidence record not found in this analysis.')
    return record


@router.get('/manual/{kind}')
def manual(kind: str):
    names = {'user':'USER-MANUAL.md','developer':'DEVELOPER-GUIDE.md','runtime-user':'RUNTIME-USER-FLOW.md','runtime-developer':'RUNTIME-DEVELOPER-GUIDE.md','phase3-user':'PHASE-3-USER-FLOW.md','phase3-developer':'PHASE-3-DEVELOPER-GUIDE.md','phase4-user':'PHASE-4-USER-FLOW.md','phase4-developer':'PHASE-4-DEVELOPER-GUIDE.md','phase5-user':'PHASE-5-USER-FLOW.md','phase5-developer':'PHASE-5-DEVELOPER-GUIDE.md','phase6-user':'PHASE-6-USER-FLOW.md','phase6-developer':'PHASE-6-DEVELOPER-GUIDE.md'}
    names.update({'phase7-user':'PHASE-7-USER-FLOW.md','phase7-developer':'PHASE-7-DEVELOPER-GUIDE.md'})
    if kind not in names:
        raise HTTPException(404, 'Manual not found.')
    path = ROOT / 'docs' / names[kind]
    if not path.exists():
        raise HTTPException(503, 'Documentation is being prepared.')
    return FileResponse(path,filename=names[kind],media_type='text/markdown')


@router.get('/demo/artifact')
def demo_artifact():
    return FileResponse(ROOT / 'samples/northstar-commerce.jar', filename='northstar-commerce.jar')


@router.post('/demo', response_model=AnalysisView, status_code=202)
def demo(request: Request, db: Session=Depends(session)):
    # Reuse a completed real scan for immediate investor navigation.
    app = None
    project = db.scalar(select(m.Project).where(m.Project.name=='Northstar Commerce · Demo'))
    if project:
        app = db.scalar(select(m.Application).where(m.Application.project_id==project.id))
        if app:
            run = db.scalar(select(m.AnalysisRun).where(m.AnalysisRun.application_id==app.id,
                m.AnalysisRun.status.in_(['COMPLETED','QUEUED','RUNNING'])).order_by(m.AnalysisRun.created_at.desc()))
            if run and (run.status != 'COMPLETED' or (run.result or {}).get('algorithm_version') == VERSION): return run
    else:
        project = m.Project(name='Northstar Commerce · Demo', description='Synthetic commerce application compiled and scanned with jQAssistant. Not a customer application.')
        db.add(project)
        db.commit()
    if app is None:
        app = m.Application(project_id=project.id, name='Northstar Commerce', version='1.0-demo')
        db.add(app)
        db.commit()
    source = ROOT / 'samples/northstar-commerce.jar'
    if not source.exists(): raise HTTPException(503, 'Build the synthetic samples first.')
    folder = request.app.state.config.data_dir / 'uploads'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder / (str(uuid4())+'.jar')
    shutil.copyfile(source,path)
    artifact = m.Artifact(application_id=app.id,filename=source.name,path=str(path),size=path.stat().st_size,
        sha256=file_hash(path),manifest=validate_archive(path,request.app.state.config))
    db.add(artifact)
    db.commit()
    return enqueue(app.id,request,db)
