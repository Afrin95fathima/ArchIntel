from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from app.api import session
from app.access.core import LOCK
from app.evidence.routes import owned as version_owned
from .models import TransformationTask
from .schemas import TaskInput, RevisionInput, TaskAction, ChangeInput, ChangeReview, ContractInput, RecipeInput, MicroserviceGenerateInput, ImpactReviewInput, ExtractionPlanInput, DataMigrationPlanInput, DataMigrationReviewInput, DataDiscoveryInput, TargetProposalInput, DataMigrationPlanReviewInput, DataMigrationPlanRevisionInput, SyntheticMigrationRunInput
from . import service, sandbox, workspace

router = APIRouter(prefix='/api/v1', tags=['Safe transformation foundation'])


@router.get('/transformation/capabilities')
def capabilities(request: Request):
    return dict(sandbox=sandbox.capabilities(request.app.state.config), recipe='MAVEN_OFFLINE_PACKAGE',
                source_execution='CONTAINER_ONLY', merge_enabled=False, deployment_enabled=False)


@router.post('/architecture-versions/{vid}/tasks', status_code=201)
def create(vid: str, body: TaskInput, request: Request, db=Depends(session)):
    with LOCK:
        try: return service.view(db, service.create(db, request, version_owned(db, request, vid), body))
        except (ValueError, OSError): raise HTTPException(409, 'Source task could not be prepared. Verify scope, storage integrity and pinned source.')


@router.get('/architecture-versions/{vid}/tasks')
def listing(vid: str, request: Request, db=Depends(session)):
    version_owned(db, request, vid)
    result = []
    for task in db.scalars(select(TransformationTask).where(TransformationTask.version_id == vid).order_by(TransformationTask.created_at.desc()).limit(100)):
        view = service.view(db, task)
        validation = view.get('validation') or {}
        if task.state == 'PAUSED':
            next_action = 'Resume or inspect the paused task.'
        elif task.state == 'FAILED':
            next_action = 'Inspect the failure and prepare a new task if needed.'
        elif task.state == 'APPROVED':
            next_action = 'Review the accepted result and plan the next modernization wave.'
        elif task.state in ('STAGED', 'VALIDATION_BLOCKED'):
            next_action = 'Complete the required build, security, architecture, and behavior checks.'
        elif view['gaps']:
            next_action = 'Resolve the listed source, baseline, or behavioral-contract gaps.'
        else:
            next_action = 'Review the task and choose the next bounded validation step.'
        result.append(dict(id=task.id, state=task.state, objective=task.document['objective'], revision=task.revision,
            blockers=len(view['gaps']), validation_state=validation.get('state'),
            validation_freshness=validation.get('freshness'), next_action=next_action))
    return result


def read_task(db, request, tid):
    task = service.owned(db, request, tid)
    service.source(db, request, task)
    return task


@router.get('/transformation/tasks/{tid}')
def read(tid: str, request: Request, db=Depends(session)):
    with LOCK: return service.view(db, read_task(db, request, tid))


@router.get('/transformation/tasks/{tid}/source/{name:path}')
def source_file(tid: str, name: str, request: Request, db=Depends(session)):
    with LOCK:
        task = read_task(db, request, tid)
        if name not in task.document['workspace']['current']: raise HTTPException(404, 'File not in the task snapshot.')
        try:
            work = workspace.checked(request.app.state.config, task)
            return dict(path=name, sha256=task.document['workspace']['current'][name], content=workspace.file_path(work,name).read_bytes().decode('utf-8'))
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')


@router.post('/transformation/tasks/{tid}/actions')
def action(tid: str, body: TaskAction, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.action(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed. No unreviewed files are overwritten.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/contracts', status_code=201)
def contract(tid: str, body: ContractInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.contract(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/contracts/{cid}/review')
def contract_review(tid: str, cid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid); service.review_contract(db, request, task, cid, body)
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/changesets', status_code=201)
def changeset(tid: str, body: ChangeInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try:
            item = service.propose(db, request, task, body)
            return dict(id=item.id, fingerprint=item.fingerprint, state=item.state, risk=item.document['risk'])
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')


@router.post('/transformation/tasks/{tid}/recipes', status_code=201)
def recipe(tid: str, body: RecipeInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try:
            item = service.generate(db, request, task, body)
            return dict(id=item.id, fingerprint=item.fingerprint, state=item.state, risk=item.document['risk'], generation=item.document['generation'])
        except sandbox.SandboxError as error:
            raise HTTPException(409, str(error))
        except (ValueError, OSError): raise HTTPException(409, 'Recipe generation or workspace integrity check failed.')


@router.post('/transformation/tasks/{tid}/microservice/generate', status_code=201)
def generate_microservice(tid: str, body: MicroserviceGenerateInput, request: Request, db=Depends(session)):
    task=service.owned(db,request,tid)
    try:
        result=service.generate_microservice(db,request,task,body)
        return dict(task=service.view(db,service.owned(db,request,tid)),generation=result)
    except HTTPException:
        raise
    except (ValueError,OSError):
        raise HTTPException(409,'Service generation could not be completed safely.') from None


@router.get('/transformation/tasks/{tid}/microservice/files/{name:path}')
def generated_microservice_file(tid:str,name:str,request:Request,db=Depends(session)):
    task=read_task(db,request,tid)
    generated=task.document.get('microservice_generation') or {}
    if name not in {item['path'] for item in generated.get('files',[])}:
        raise HTTPException(404,'Generated file is not part of this service proposal.')
    try:
        import re
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}',generated['repository_name']):
            raise ValueError('Invalid generated repository identity.')
        root=workspace.root(request.app.state.config,task)/'generated-services'/generated['repository_name']
        target=workspace.file_path(root,name)
        content=target.read_text(encoding='utf-8')
        entry=next(item for item in generated['files'] if item['path']==name)
        if workspace.sha(content.encode('utf-8'))!=entry['sha256']:
            raise ValueError('Generated file changed after proposal creation.')
        return dict(path=name,sha256=entry['sha256'],content=content)
    except (ValueError,OSError,KeyError):
        raise HTTPException(409,'Generated repository integrity check failed.') from None


@router.post('/transformation/tasks/{tid}/extraction-plan')
def extraction_plan(tid: str, body: ExtractionPlanInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try:
            service.prepare_extraction_plan(db, request, task, body)
            return service.view(db, task)
        except (ValueError, OSError): raise HTTPException(409, 'Extraction plan could not be bound to the pinned task snapshot.')


@router.post('/transformation/tasks/{tid}/data-migration-plan')
def data_migration_plan(tid: str, body: DataMigrationPlanInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try:
            service.prepare_data_migration_plan(db, request, task, body)
            return service.view(db, task)
        except (ValueError, OSError): raise HTTPException(409, 'Data migration plan could not be bound to the pinned task snapshot.')


@router.post('/transformation/tasks/{tid}/data-migration-plan/review')
def review_data_migration_plan(tid: str, body: DataMigrationReviewInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        plan = service.review_data_migration_plan(db, request, task, body)
        return dict(plan=plan, task=service.view(db, task))


@router.post('/transformation/tasks/{tid}/data-discovery')
def data_discovery(tid: str, body: DataDiscoveryInput, request: Request, db=Depends(session)):
    with LOCK:
        task=service.owned(db,request,tid)
        run=service.run_data_discovery(db,request,task,body)
        return dict(id=run.id,state=run.state,fingerprint=run.fingerprint,report=run.document,task=service.view(db,task))


@router.post('/transformation/tasks/{tid}/data-migration-proposals/{pid}/revise')
def revise_data_migration(tid: str,pid: str,body: DataMigrationPlanRevisionInput,request: Request,db=Depends(session)):
    with LOCK:
        if body.base_plan_id!=pid: raise HTTPException(422,'Base plan ID does not match the route.')
        task=service.owned(db,request,tid)
        plan=service.revise_data_migration(db,request,task,body)
        return dict(id=plan.id,revision=plan.revision,state=plan.state,fingerprint=plan.fingerprint,plan=plan.document,task=service.view(db,task))


@router.post('/transformation/tasks/{tid}/data-migration-proposals')
def data_migration_proposal(tid: str, body: TargetProposalInput, request: Request, db=Depends(session)):
    with LOCK:
        task=service.owned(db,request,tid)
        plan=service.propose_data_migration(db,request,task,body)
        return dict(id=plan.id,revision=plan.revision,state=plan.state,fingerprint=plan.fingerprint,plan=plan.document,task=service.view(db,task))


@router.post('/transformation/tasks/{tid}/data-migration-proposals/{pid}/review')
def review_generated_data_migration(tid: str,pid: str,body: DataMigrationPlanReviewInput,request: Request,db=Depends(session)):
    with LOCK:
        if body.plan_id!=pid: raise HTTPException(422,'Plan ID in the request does not match the route.')
        task=service.owned(db,request,tid)
        plan=service.review_generated_data_migration(db,request,task,body)
        return dict(id=plan.id,state=plan.state,fingerprint=plan.fingerprint,review=plan.review,plan=plan.document,task=service.view(db,task))


@router.post('/transformation/tasks/{tid}/data-migration-proposals/{pid}/synthetic-test')
def synthetic_migration_test(tid: str,pid: str,body: SyntheticMigrationRunInput,request: Request,db=Depends(session)):
    with LOCK:
        if body.plan_id!=pid: raise HTTPException(422,'Plan ID in the request does not match the route.')
        task=service.owned(db,request,tid)
        run=service.execute_synthetic_migration(db,request,task,body)
        return dict(id=run.id,state=run.state,result=run.document,task=service.view(db,task))


@router.get('/transformation/tasks/{tid}/changesets/{cid}')
def patch(tid: str, cid: str, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: return service.patch(db, request, task, service.change(db, task, cid))
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')


@router.post('/transformation/tasks/{tid}/changesets/{cid}/review')
def review(tid: str, cid: str, body: ChangeReview, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.review_change(db, request, task, service.change(db, task, cid), body)
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/changesets/{cid}/stage')
def stage(tid: str, cid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.stage(db, request, task, service.change(db, task, cid), body)
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed. Inspect the task before retrying.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/builds/{kind}')
def build(tid: str, kind: str, body: RevisionInput, request: Request, db=Depends(session)):
    task = service.owned(db, request, tid)
    service.build(db, request, task, kind, body)
    with LOCK: return service.view(db, read_task(db, request, tid))


@router.post('/transformation/tasks/{tid}/validate')
def validate(tid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.validate(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Workspace integrity check failed.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/expected-impact/review')
def review_expected_impact(tid: str, body: ImpactReviewInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        service.review_expected_impact(db, request, task, body)
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/candidate-version')
def publish_candidate(tid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.publish_candidate(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Candidate publication failed an integrity check.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/final-approval')
def final_approval(tid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.final_approve(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Final approval failed an integrity check.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/reanalyze')
def reanalyze(tid: str, body: RevisionInput, request: Request, db=Depends(session)):
    with LOCK:
        task = service.owned(db, request, tid)
        try: service.reanalyze(db, request, task, body)
        except (ValueError, OSError): raise HTTPException(409, 'Artifact or workspace integrity check failed.')
        return service.view(db, task)


@router.post('/transformation/tasks/{tid}/security-scan')
def security_scan(tid: str, body: RevisionInput, request: Request, db=Depends(session)):
    task = service.owned(db, request, tid)
    try: service.scan_security(db, request, task, body)
    except (ValueError, OSError): raise HTTPException(409, 'Security artifact or workspace integrity check failed.')
    with LOCK: return service.view(db, read_task(db, request, tid))
