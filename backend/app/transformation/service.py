"""Task constraints, reviewed staging and recoverable validation attempts."""
import copy
import difflib
import sqlite3
import subprocess
from datetime import timedelta, datetime
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func
from app.api import get
from app.models import now
from app.models import Artifact, AnalysisRun
from app.services.ingestion import validate_archive, file_hash, ArtifactError
from app.access.core import LOCK, latest_policy, record, audit
from app.access.models import SourceRepository, SourceGrant, Principal
from app.access import gateway
from app.ai.filters import sanitize, FilterDenied
from app.evidence.builder import digest
from app.evidence import service as evidence_service
from app.evidence.models import ArchitectureVersion
from app.modernization.models import Assessment as ModernizationAssessment
from app.evidence.schemas import VersionInput
from app.evidence.routes import owned as version_owned
from app.modernization import service as planning
from .models import TransformationTask, ChangeSet, BehavioralContract, BuildRun, DataDiscoveryRun, DataMigrationPlan, DataMigrationRun
from .schemas import ChangeInput
from . import workspace, sandbox, validation, architecture, security, extraction, data_migration, data_discovery, migration_test_runner, microservice_codegen


def owned(db, request, tid):
    task = get(db, TransformationTask, tid)
    version_owned(db, request, task.version_id)
    return task


def policy(db, request):
    principal = db.get(Principal, request.state.identity['id'])
    if not principal or not principal.active or 'SOURCE_READ' not in principal.permissions:
        raise HTTPException(403, 'Current source-read permission is required for source tasks.')
    item = latest_policy(db, request.state.identity['tenant_id'])
    if not item.document.get('transformation_enabled') or not item.document.get('source_read_enabled'):
        raise HTTPException(403, 'Enable bounded source tasks in workspace policy before continuing.')
    return item


def authorize_paths(db, request, repo, names):
    item = policy(db, request)
    grant = db.scalar(select(SourceGrant).where(SourceGrant.repository_id == repo.id, SourceGrant.principal_id == request.state.identity['id']))
    if not grant: raise HTTPException(403, 'An explicit repository grant is required, including for administrators.')
    for name in names:
        try: workspace.relative(name)
        except ValueError: raise HTTPException(422, 'Task contains a protected or nonportable path.')
        if not gateway.matches(name, grant.allowed_paths) or gateway.matches(name, grant.protected_paths + item.document['protected_paths']):
            raise HTTPException(403, 'Task scope includes an ungranted or protected path.')
    return item, digest(dict(allowed=grant.allowed_paths, protected=grant.protected_paths))


def source(db, request, task):
    repo = get(db, SourceRepository, task.repository_id)
    p, grant = authorize_paths(db, request, repo, sorted(set(task.document['files'] + task.document['allowed_files'])))
    body = SimpleNamespace(repository_id=repo.id, commit=task.document['commit'], files=task.document['files'],
        purpose='Validate bounded source task ' + task.id, operation='SOURCE_READ', destination='LOCAL_CONTEXT')
    context = gateway.read_context(db, request, body, task_scope=True)
    if {f['path']: f['sha256'] for f in context['files']} != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Pinned source no longer matches this task.')
    return context, p.revision, grant


def event(db, request, task, action, note, **details):
    if len(task.history) >= 200 and action != 'ROLLBACK': raise HTTPException(409, 'Task history limit reached; create a new task.')
    task.revision += 1
    task.history = [*task.history, dict(revision=task.revision, at=now().isoformat(), actor=request.state.identity['id'], action=action, state=task.state, note=note, **details)]


def expected(task, revision):
    if task.revision != revision: raise HTTPException(409, 'Task changed. Refresh before acting.')


def current(db, request, task):
    version = version_owned(db, request, task.version_id)
    if planning.context(db, version)['state'] != 'CURRENT': raise HTTPException(409, 'Architecture version superseded; create a task against current evidence.')
    proposal = planning.owned(db, version, task.assessment_id)
    history = planning.reviews(db, proposal.id)
    if not history or history[-1]['state'] != 'APPROVED_PLANNING': raise HTTPException(409, 'A currently approved planning proposal is required.')
    return version


def create(db, request, version, body):
    p = policy(db, request)
    proposal = planning.owned(db, version, body.assessment_id)
    decision = next((d for d in proposal.document['decisions'] if d['id'] == body.decision_id), None)
    if not decision: raise HTTPException(422, 'Decision is not part of the selected proposal.')
    service_binding = None
    if body.service_candidate_id is not None:
        decomposition = proposal.document.get('microservice_decomposition') or {}
        candidate = next((c for c in decomposition.get('service_candidates', [])
                          if c.get('id') == body.service_candidate_id), None)
        if not candidate or candidate.get('id') != decision.get('domain_id'):
            raise HTTPException(422, 'Selected service candidate must belong to the approved plan decision.')
        if candidate.get('proposal_state') == 'TECHNICAL_DOMAIN_NOT_A_SERVICE':
            raise HTTPException(422, 'A technical domain is kept as shared configuration or a library; it cannot be started as a service.')
        if body.rollout_mode not in ('ONE_BY_ONE', 'WHOLE_SYSTEM'):
            raise HTTPException(422, 'A service rollout mode is required for candidate modernization.')
        service_binding = dict(candidate_id=candidate['id'], name=candidate['name'],
            repository_name=candidate['repository_name'], rollout_mode=body.rollout_mode,
            class_ids=list(candidate.get('class_ids', [])), packages=list(candidate.get('packages', [])),
            data_signals=copy.deepcopy(candidate.get('data', {})),
            proposal_fingerprint=proposal.fingerprint,
            source_version_id=version.id, source_version_fingerprint=version.fingerprint,
            state='SOURCE_TASK_SETUP_REQUIRED')
    elif body.rollout_mode is not None:
        raise HTTPException(422, 'A rollout mode requires a selected service candidate.')
    repo = get(db, SourceRepository, body.repository_id)
    if repo.application_id != version.application_id or repo.commit != body.commit: raise HTTPException(409, 'Repository/application/commit binding does not match.')
    if len({n.casefold() for n in body.files + body.allowed_files}) != len(set(body.files + body.allowed_files)):
        raise HTTPException(422, 'Case-colliding task paths are not supported.')
    authorize_paths(db, request, repo, sorted(set(body.files + body.allowed_files)))
    body_context = SimpleNamespace(repository_id=repo.id, commit=body.commit, files=body.files, purpose='Prepare isolated source task for approved plan', operation='SOURCE_READ', destination='LOCAL_CONTEXT')
    context = gateway.read_context(db, request, body_context, task_scope=True)
    fingerprint = digest(dict(version=version.id, actor=request.state.identity['id'], options=body.model_dump()))
    existing = db.scalar(select(TransformationTask).where(TransformationTask.fingerprint == fingerprint))
    if existing:
        source(db, request, existing)
        return existing
    task = TransformationTask(id=str(uuid4()), fingerprint=fingerprint, tenant_id=version.tenant_id, version_id=version.id, assessment_id=proposal.id,
        repository_id=repo.id, actor_id=request.state.identity['id'], document=dict(**body.model_dump(), domain_id=decision['domain_id'],
        evidence_ids=decision['evidence_ids'], expected_artifact_sha256=version.manifest['artifact_sha256'], recipe='MAVEN_OFFLINE_PACKAGE',
            expected_improvement_criterion=dict(metric=architecture.IMPACT_METRIC_BY_DECISION.get(decision['kind']),
                decision_kind=decision['kind'], domain_id=decision['domain_id']),
            validation_requirements=['BASELINE_ARTIFACT_MATCH','PASSING_TESTS','REVIEWED_BEHAVIORAL_CONTRACTS','ARCHITECTURE_REANALYSIS','GENERATED_CODE_SECURITY'],
        source_policy_revision=p.revision,
        microservice=service_binding))
    current(db, request, task)
    names = gateway.git(gateway.repository_path(repo.path, request.app.state.config), 'ls-tree', '-r', '--name-only', '-z', repo.commit).decode('utf-8').split('\0')
    task.document['complete_source_snapshot'] = set(filter(None, names)) == set(body.files)
    # Block secret-bearing source before persisting any copy. No raw content is logged.
    try:
        for f in context['files']: sanitize(f['content'], 'BLOCK')
    except FilterDenied: raise HTTPException(422, 'Sensitive content detected; task source snapshot was not created.')
    task.document = dict(task.document, workspace=dict(baseline={f['path']:f['sha256'] for f in context['files']}, current={}, branch=None, git_config_sha256=None))
    task.state = 'PREPARING'; db.add(task); db.flush(); event(db, request, task, 'PREPARE_STARTED', body.objective); db.commit()
    try:
        task.document = dict(task.document, workspace=workspace.create(request.app.state.config, task, context['files']))
        if task.document['workspace']['current'] != task.document['workspace']['baseline']: raise ValueError('Snapshot bytes changed during Git initialization.')
        task.state = 'PLANNED'; event(db, request, task, 'CREATE', body.objective)
    except (ValueError, OSError, subprocess.SubprocessError):
        task.state = 'FAILED'; task.document = dict(task.document, preparation_error='SNAPSHOT_PREPARATION_FAILED')
        event(db, request, task, 'PREPARE_FAILED', 'Inspect task storage before preparing a new task.')
    db.commit()
    return task


def contracts(db, task):
    return list(db.scalars(select(BehavioralContract).where(BehavioralContract.task_id == task.id).order_by(BehavioralContract.created_at)))


def builds(db, task):
    return list(db.scalars(select(BuildRun).where(BuildRun.task_id == task.id).order_by(BuildRun.created_at)))


def gaps(db, task):
    items = []
    if not task.document['complete_source_snapshot']: items.append('INCOMPLETE_SOURCE_SNAPSHOT')
    baseline = [b for b in builds(db, task) if b.kind == 'BASELINE' and b.state == 'PASSED']
    if not baseline: items.append('PASSING_BASELINE_AND_ARTIFACT_MATCH_REQUIRED')
    rows = contracts(db, task)
    if not rows: items.append('BEHAVIORAL_CONTRACTS_REQUIRED')
    cases = {c['name'] for b in baseline[-1:] for c in b.document.get('result', {}).get('cases', []) if c['passed']}
    for c in rows:
        if not c.review: items.append('CONTRACT_REVIEW_REQUIRED:' + c.id)
        if c.document['critical'] and c.document['test_case'] not in cases: items.append('CRITICAL_BEHAVIOR_UNVALIDATED:' + c.id)
    return items


def view(db, task):
    rows = contracts(db, task)
    comparison = task.document.get('validation')
    if comparison:
        staged = change(db, task, task.document['staged_changeset'])
        fresh = digest(validation.evaluate(task, builds(db, task), rows, staged)) == comparison['fingerprint']
        comparison = dict(comparison, freshness='CURRENT' if fresh and task.state in ('VALIDATION_BLOCKED','APPROVED') else 'STALE')
    def build_view(b):
        document = copy.deepcopy(b.document)
        capture = (document.get('result') or {}).get('artifact_capture')
        if capture: document['result']['artifact_capture'] = {k:capture[k] for k in ('size','sha256')}
        return dict(id=b.id, kind=b.kind, state=b.state, **document)
    extraction_plan = copy.deepcopy(task.document.get('extraction_plan'))
    if extraction_plan:
        version = db.get(ArchitectureVersion, task.version_id)
        latest_version = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == version.application_id)
            .order_by(ArchitectureVersion.created_at.desc(), ArchitectureVersion.id.desc()).limit(1))
        contracts_hash = digest([dict(document=row.document, review=row.review) for row in rows])
        fresh = (extraction_plan.get('inputs', {}).get('source_manifest_sha256') ==
                 digest(task.document['workspace']['baseline']) and
                 extraction_plan.get('inputs', {}).get('contracts_sha256') == contracts_hash and
                 extraction_plan.get('inputs', {}).get('data_ownership_review_sha256') ==
                 (digest(task.document['data_ownership_review']) if task.document.get('data_ownership_review') else None) and
                 latest_version is not None and latest_version.id == task.version_id and
                 task.document['workspace']['current'] == task.document['workspace']['baseline'] and
                 task.state in ('PLANNED', 'READY'))
        extraction_plan['freshness'] = 'CURRENT' if fresh else 'STALE'
    migration_plan = copy.deepcopy(task.document.get('data_migration_plan'))
    if migration_plan:
        version = db.get(ArchitectureVersion, task.version_id)
        latest_version = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == version.application_id)
            .order_by(ArchitectureVersion.created_at.desc(), ArchitectureVersion.id.desc()).limit(1))
        review = task.document.get('data_migration_ownership_review')
        bindings=migration_plan.get('bindings',{})
        base_fresh=(latest_version is not None and latest_version.id==task.version_id and
            task.document['workspace']['current']==task.document['workspace']['baseline'] and task.state in ('PLANNED','READY'))
        if bindings:
            fresh=base_fresh and bindings.get('source_manifest_sha256')==digest(task.document['workspace']['baseline']) and \
                bindings.get('repository_commit')==task.document['commit'] and bindings.get('architecture_version_fingerprint')==version.fingerprint
        else:
            fresh=base_fresh and migration_plan.get('inputs',{}).get('source_manifest_sha256')==digest(task.document['workspace']['baseline']) and \
                migration_plan.get('inputs',{}).get('spec_sha256')==digest(task.document.get('data_migration_spec')) and \
                migration_plan.get('inputs',{}).get('ownership_review_sha256')==(digest(review) if review else None)
        migration_plan['freshness'] = 'CURRENT' if fresh else 'STALE'
    discovery_record = db.get(DataDiscoveryRun, task.document.get('data_discovery_id', '')) if task.document.get('data_discovery_id') else None
    migration_run = db.get(DataMigrationRun, task.document.get('data_migration_run_id', '')) if task.document.get('data_migration_run_id') else None
    migration_plan_record = db.get(DataMigrationPlan, task.document.get('data_migration_plan_id', '')) if task.document.get('data_migration_plan_id') else None
    document = copy.deepcopy(task.document)
    if extraction_plan:
        document['extraction_plan'] = extraction_plan
    if migration_plan:
        document['data_migration_plan'] = migration_plan
    if migration_plan_record:
        enriched=copy.deepcopy(migration_plan_record.document)
        enriched.update(id=migration_plan_record.id,revision=migration_plan_record.revision,state=migration_plan_record.state,
            review=migration_plan_record.review,freshness=(migration_plan or {}).get('freshness','STALE'))
        document['data_migration_plan'] = enriched
    if discovery_record:
        document['data_discovery'] = discovery_record.document
    if migration_run:
        document['data_migration_test_run'] = migration_run.document
    return dict(id=task.id, version_id=task.version_id, state=task.state, revision=task.revision, created_at=task.created_at,
        document=document, history=task.history, gaps=gaps(db, task),
        contracts=[dict(id=c.id, **c.document, review=c.review) for c in rows],
        changesets=[dict(id=c.id, state=c.state, fingerprint=c.fingerprint, risk=c.document['risk'], files=[e['path'] for e in c.document['edits']], approval=c.approval) for c in db.scalars(select(ChangeSet).where(ChangeSet.task_id == task.id).order_by(ChangeSet.created_at))],
        builds=[build_view(b) for b in builds(db, task)],
        validation=comparison, extraction_plan=extraction_plan, data_migration_plan=document.get('data_migration_plan'),
        data_discovery=discovery_record.document if discovery_record else None,
        data_migration_test_run=migration_run.document if migration_run else None,
        execution=dict(merge_enabled=False, deployment_enabled=False, note='Reviewed staging and build comparison are available for this task. Final approval requires architecture and security validation of this task.'))


def prepare_extraction_plan(db, request, task, body):
    source(db, request, task); version = current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED', 'READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Extraction planning requires the unchanged pinned source baseline.')
    workspace.checked(request.app.state.config, task)
    analysis_run = get(db, AnalysisRun, version.analysis_id)
    if analysis_run.status != 'COMPLETED' or not analysis_run.result:
        raise HTTPException(409, 'A completed baseline architecture analysis is required.')
    reviews = contracts(db, task)
    baseline = copy.deepcopy(analysis_run.result)
    reviewed_domains = version.document.get('domains') or baseline.get('domains', [])
    if reviewed_domains:
        baseline['domains'] = copy.deepcopy(reviewed_domains)
        assignments = {class_id: domain['id'] for domain in reviewed_domains for class_id in domain.get('classes', [])}
        for row in baseline.get('classes', []):
            if row.get('id') in assignments:
                row['domain_id'] = assignments[row['id']]
    plan = extraction.build_plan(baseline, task.document['domain_id'],
        task.document['workspace']['baseline'], complete_source_snapshot=task.document['complete_source_snapshot'],
        contracts=reviews, data_ownership_review=task.document.get('data_ownership_review'))
    plan['inputs'].update(version_id=version.id, version_fingerprint=version.fingerprint,
                          source_manifest_sha256=digest(task.document['workspace']['baseline']))
    plan['fingerprint'] = digest({key:value for key,value in plan.items() if key != 'fingerprint'})
    task.document = dict(task.document, extraction_plan=plan)
    event(db, request, task, 'PREVIEW_EXTRACTION_BOUNDARY', body.note, plan_fingerprint=plan['fingerprint'])
    db.commit()
    return plan


def _build_data_migration_plan(task, spec, ownership_review, version_fingerprint):
    return data_migration.build_plan(spec, version_id=task.version_id,
        version_fingerprint=version_fingerprint,
        source_manifest_sha256=digest(task.document['workspace']['baseline']),
        data_ownership_review=ownership_review,
        database_evidence=task.document.get('database_evidence', []))


def prepare_data_migration_plan(db, request, task, body):
    source(db, request, task); version = current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED', 'READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Data migration planning requires the unchanged pinned source baseline.')
    workspace.checked(request.app.state.config, task)
    spec = body.model_dump(exclude={'expected_revision', 'note'})
    spec['source'] = spec['source']
    # An author assertion is not a review. A separate human security administrator must attest to it.
    review = task.document.get('data_migration_ownership_review')
    if review and review.get('spec_sha256') != digest(spec):
        review = None
    plan = _build_data_migration_plan(task, spec, review, version.fingerprint)
    plan['inputs'] = dict(task_id=task.id, version_id=version.id,
        version_fingerprint=version.fingerprint, source_manifest_sha256=digest(task.document['workspace']['baseline']),
        spec_sha256=digest(spec), ownership_review_sha256=digest(review) if review else None)
    plan['fingerprint'] = digest({key:value for key,value in plan.items() if key != 'fingerprint'})
    task.document = dict(task.document, data_migration_spec=spec, data_migration_plan=plan,
                         data_migration_ownership_review=review)
    event(db, request, task, 'PREVIEW_DATA_MIGRATION_PLAN', body.note, plan_fingerprint=plan['fingerprint'])
    db.commit()
    return plan


def review_data_migration_plan(db, request, task, body):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    identity = request.state.identity
    plan = task.document.get('data_migration_plan')
    spec = task.document.get('data_migration_spec')
    if not plan or not spec or plan['fingerprint'] != body.fingerprint:
        raise HTTPException(409, 'Migration plan changed; refresh and preview it again.')
    if identity['kind'] != 'HUMAN' or 'SECURITY_ADMIN' not in identity['permissions']:
        raise HTTPException(403, 'A human security administrator must review data ownership and the migration plan.')
    if identity['id'] == task.actor_id:
        raise HTTPException(403, 'The migration plan author cannot approve its ownership or migration review.')
    accepted = body.action == 'APPROVE_PLAN'
    review = dict(reviewed=accepted, state='ACCEPTED' if accepted else 'REJECTED', actor=identity['id'], statement=spec['ownership_statement'],
        evidence=spec['ownership_evidence'], spec_sha256=digest(spec), at=now().isoformat(), fingerprint=plan['fingerprint'], note=body.note)
    version = current(db, request, task)
    updated = _build_data_migration_plan(task, spec, review, version.fingerprint)
    updated['inputs'] = dict(plan['inputs'], ownership_review_sha256=digest(review))
    updated['fingerprint'] = digest({key:value for key,value in updated.items() if key != 'fingerprint'})
    task.document = dict(task.document, data_migration_ownership_review=review, data_migration_plan=updated)
    event(db, request, task, 'REVIEW_DATA_MIGRATION_PLAN', body.note,
          decision=body.action, plan_fingerprint=updated['fingerprint'])
    db.commit()
    return updated


def run_data_discovery(db, request, task, body):
    source(db, request, task); version = current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED', 'READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Discovery requires the unchanged pinned source snapshot.')
    baseline_dir = workspace.root(request.app.state.config, task) / 'baseline'
    workspace.checked(request.app.state.config, task)
    files={}; coverage=[]
    for path,sha in sorted(task.document['workspace']['baseline'].items()):
        target=workspace.file_path(baseline_dir,path)
        try: content=target.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            coverage.append(dict(path=path,state='SKIPPED_NON_TEXT',sha256=sha));continue
        files[path]=dict(content=content,sha256=sha)
    run_analysis=get(db,AnalysisRun,version.analysis_id)
    graph=version.document.get('graph',{}).get('nodes',[])
    runtime_db=[n.get('observation') for n in graph if n.get('kind')=='DataResource' and n.get('observation')]
    result=data_discovery.discover(files,full_source_snapshot=task.document.get('complete_source_snapshot',False),
        analysis=run_analysis.result or {},runtime_database=runtime_db)
    result['parser_coverage'].extend(coverage)
    result['provenance'].update(repository_id=task.repository_id,repository_commit=task.document['commit'],
        architecture_version_id=version.id,architecture_version_fingerprint=version.fingerprint,
        artifact_sha256=version.manifest.get('artifact_sha256'))
    result['fingerprint']=digest({k:v for k,v in result.items() if k!='fingerprint'})
    existing=db.scalar(select(DataDiscoveryRun).where(DataDiscoveryRun.task_id==task.id,DataDiscoveryRun.fingerprint==result['fingerprint']))
    if existing:
        record_run=existing
    else:
        record_run=DataDiscoveryRun(tenant_id=task.tenant_id,task_id=task.id,actor_id=request.state.identity['id'],
            state='COMPLETED',fingerprint=result['fingerprint'],document=result)
        db.add(record_run);db.flush()
    task.document=dict(task.document,data_discovery_id=record_run.id)
    event(db,request,task,'DISCOVER_DATA_ARCHITECTURE',body.note,discovery_id=record_run.id,fingerprint=record_run.fingerprint)
    db.commit()
    return record_run


def propose_data_migration(db, request, task, body):
    source(db,request,task);version=current(db,request,task);expected(task,body.expected_revision)
    if task.state not in ('PLANNED','READY') or task.document['workspace']['current']!=task.document['workspace']['baseline']:
        raise HTTPException(409,'A proposal requires the unchanged pinned source snapshot.')
    discovery_id=task.document.get('data_discovery_id')
    discovered=db.get(DataDiscoveryRun,discovery_id) if discovery_id else None
    if not discovered or discovered.task_id!=task.id: raise HTTPException(409,'Run source data discovery before generating a target proposal.')
    source_entities={entity['name'].casefold():entity for entity in discovered.document.get('entities',[])}
    invariant_names=set()
    for invariant in body.business_invariants:
        key=invariant.name.casefold()
        if key in invariant_names: raise HTTPException(422,'Business invariant names must be unique.')
        invariant_names.add(key)
        entity=source_entities.get(invariant.table.casefold())
        if not entity: raise HTTPException(422,'Business invariants must reference a discovered source table.')
        if invariant.kind in ('UNIQUE','NOT_NULL') and not any(column['name'].casefold()==invariant.column.casefold() for column in entity['columns']):
            raise HTTPException(422,'This business invariant must reference a discovered source column.')
    domains=version.document.get('domains',[])
    proposal=data_discovery.propose_target(discovered.document,domains,body.target_engine)
    proposal['ownership_map']=copy.deepcopy(discovered.document['ownership_map'])
    proposal['business_invariants']=[item.model_dump() for item in body.business_invariants]
    proposal['bindings']=dict(repository_id=task.repository_id,repository_commit=task.document['commit'],
        architecture_version_id=version.id,architecture_version_fingerprint=version.fingerprint,
        artifact_sha256=version.manifest.get('artifact_sha256'),source_schema_fingerprint=discovered.fingerprint,
        target_schema_version=digest(proposal.get('target_schema',[])),mapping_version=1,source_manifest_sha256=digest(task.document['workspace']['baseline']))
    proposal['fingerprint']=digest({k:v for k,v in proposal.items() if k!='fingerprint'})
    previous=db.scalar(select(DataMigrationPlan).where(DataMigrationPlan.task_id==task.id).order_by(DataMigrationPlan.revision.desc()))
    plan=DataMigrationPlan(tenant_id=task.tenant_id,task_id=task.id,discovery_id=discovered.id,
        revision=(previous.revision+1 if previous else 1),state='PROPOSED_REVIEW_REQUIRED',fingerprint=proposal['fingerprint'],document=proposal)
    db.add(plan);db.flush()
    task.document=dict(task.document,data_migration_plan_id=plan.id,data_migration_plan=proposal)
    event(db,request,task,'GENERATE_DATA_MIGRATION_PROPOSAL',body.note,plan_id=plan.id,fingerprint=plan.fingerprint)
    db.commit();return plan


def revise_data_migration(db,request,task,body):
    source(db,request,task);current(db,request,task);expected(task,body.expected_revision)
    prior=db.get(DataMigrationPlan,body.base_plan_id)
    if not prior or prior.task_id!=task.id or task.document.get('data_migration_plan_id')!=prior.id or prior.fingerprint!=task.document.get('data_migration_plan',{}).get('fingerprint'):
        raise HTTPException(409,'Only the current plan can be revised; refresh discovery if its source changed.')
    document=copy.deepcopy(prior.document)
    touched=set()
    for override in body.mapping_overrides:
        key=(override.source_table.casefold(),override.source_column.casefold())
        if key in touched: raise HTTPException(422,'A source column can be overridden only once per plan revision.')
        touched.add(key)
        mapping=next((m for m in document['mappings'] if (m['source_table'].casefold(),m['source_column'].casefold())==key),None)
        if not mapping: raise HTTPException(422,'Mapping override does not match a discovered source column.')
        if mapping.get('key') and override.target_column!=mapping['target_column']:
            raise HTTPException(422,'Primary key column renaming is not supported in this release.')
        target_table=next((t for t in document['target_schema'] if t['source_resource'].casefold()==override.source_table.casefold()),None)
        if not target_table: raise HTTPException(422,'Target table proposal is missing for the source resource.')
        target_column=next((c for c in target_table['columns'] if c['name']==mapping['target_column']),None)
        if not target_column: raise HTTPException(409,'Target column changed outside this plan.')
        target_column['name']=override.target_column
        target_column['data_type']=override.target_type
        mapping.update(target_column=override.target_column,target_type=override.target_type,conversion=override.conversion,
            state='CUSTOMER_CONFIRMED',confidence='CUSTOMER_CONFIRMED',rationale=override.rationale)
        display_table=next((t for t in document['tables'] if t.get('source_resource','').casefold()==override.source_table.casefold()),None)
        if display_table:
            display_col=next((c for c in display_table['columns'] if c['name']==mapping['source_column']),None)
            if display_col: display_col.update(name=override.target_column,type=override.target_type,state='CUSTOMER_CONFIRMED')
        if mapping.get('key'):
            target_table['primary_key']=[override.target_column if c==mapping['source_column'] else c for c in target_table['primary_key']]
            for other in document['target_schema']:
                for fk in other.get('foreign_keys',[]):
                    if fk['target_table']==target_table['name']:
                        fk['target_columns']=[override.target_column if c==mapping['source_column'] else c for c in fk['target_columns']]
    for table in document['target_schema']:
        names=[c['name'].casefold() for c in table['columns']]
        if len(names)!=len(set(names)): raise HTTPException(422,'Target column names must be unique within each table.')
    document['bindings']['mapping_version']=prior.document['bindings'].get('mapping_version',1)+1
    document['bindings']['target_schema_version']=digest(document['target_schema'])
    document['state']='PROPOSED_REVIEW_REQUIRED'
    document['fingerprint']=digest({k:v for k,v in document.items() if k!='fingerprint'})
    plan=DataMigrationPlan(tenant_id=task.tenant_id,task_id=task.id,discovery_id=prior.discovery_id,
        revision=prior.revision+1,state='PROPOSED_REVIEW_REQUIRED',fingerprint=document['fingerprint'],document=document)
    db.add(plan);db.flush()
    task.document=dict(task.document,data_migration_plan_id=plan.id,data_migration_plan=document)
    event(db,request,task,'REVISE_DATA_MIGRATION_PROPOSAL',body.note,plan_id=plan.id,fingerprint=plan.fingerprint,mapping_version=document['bindings']['mapping_version'])
    db.commit();return plan


def review_generated_data_migration(db,request,task,body):
    source(db,request,task);version=current(db,request,task);expected(task,body.expected_revision)
    plan=db.get(DataMigrationPlan,body.plan_id)
    if not plan or plan.task_id!=task.id or task.document.get('data_migration_plan_id')!=plan.id:
        raise HTTPException(404,'Current migration plan was not found for this task.')
    if plan.fingerprint!=body.fingerprint or task.document.get('data_migration_plan',{}).get('fingerprint')!=body.fingerprint:
        raise HTTPException(409,'Migration plan changed; regenerate or refresh before review.')
    identity=request.state.identity
    if identity['kind']!='HUMAN' or 'SECURITY_ADMIN' not in identity['permissions']:
        raise HTTPException(403,'A human security administrator must review the migration plan.')
    if identity['id']==task.actor_id: raise HTTPException(403,'The task author cannot approve the migration plan.')
    if plan.review: raise HTTPException(409,'Plan review is immutable; create a new plan revision.')
    proposal=copy.deepcopy(plan.document)
    decisions={x.resource:x.model_dump() for x in body.ownership_decisions}
    if len(decisions)!=len(body.ownership_decisions): raise HTTPException(422,'Ownership decisions must be unique by resource.')
    valid_domains={x['id'] for x in version.document.get('domains',[])}
    claims={x['resource'] for x in proposal.get('ownership_map',[])}
    if body.action=='APPROVE_FOR_TEST' and set(decisions)!=claims:
        raise HTTPException(422,'Confirm each discovered ownership claim or choose SHARED explicitly before test approval.')
    for resource,decision in decisions.items():
        if resource not in claims or decision['owner_domain_id']!='SHARED' and decision['owner_domain_id'] not in valid_domains:
            raise HTTPException(422,'Ownership decision references an unknown resource or architecture domain.')
        candidate=next(x for x in proposal['ownership_map'] if x['resource']==resource)
        candidate.update(state='CUSTOMER_CONFIRMED',confirmed_owner=decision['owner_domain_id'],
            confirmation_rationale=decision['rationale'],reviewer=identity['id'])
        table=next((x for x in proposal['tables'] if x.get('source_resource','').casefold()==resource.casefold()),None)
        if table: table['service']=decision['owner_domain_id'] if decision['owner_domain_id']=='SHARED' else next(x['name'] for x in version.document.get('domains',[]) if x['id']==decision['owner_domain_id'])
    if body.action=='APPROVE_FOR_TEST':
        if proposal.get('target_engine')!='SQLITE_TEST': raise HTTPException(409,'Select the isolated synthetic SQLite test target before approving test execution.')
        hard={'NO_STRUCTURED_SCHEMA_DISCOVERED','PRIMARY_KEY_NOT_DISCOVERED','COLUMN_TYPE_UNKNOWN','SCHEMA_DEFINITION_CONFLICT','REFERENCED_RESOURCE_NOT_DISCOVERED'}
        hard_items=[x for x in proposal['unresolved'] if x['kind'] in hard]
        if hard_items: raise HTTPException(409,'Plan has unresolved schema/key facts that prevent a synthetic test run.')
        proposal['unresolved']=[x for x in proposal['unresolved'] if x['kind']!='TARGET_SERVICE_OWNERSHIP_UNRESOLVED']
        risk_keys={x['kind']+(':'+str(x.get('resource')) if x.get('resource') else '') for x in proposal['unresolved']}
        if not risk_keys.issubset(set(body.acknowledged_risks)):
            raise HTTPException(422,'Acknowledge each remaining unresolved risk or return the plan for more discovery.')
        proposal['state']='APPROVED_FOR_TEST'
    else: proposal['state']='REJECTED'
    proposal['fingerprint']=digest({k:v for k,v in proposal.items() if k!='fingerprint'})
    review=dict(actor=identity['id'],at=now().isoformat(),action=body.action,note=body.note,
        proposal_fingerprint=plan.fingerprint,fingerprint=proposal['fingerprint'],
        ownership_decisions=list(decisions.values()),acknowledged_risks=body.acknowledged_risks)
    plan.fingerprint=proposal['fingerprint']
    plan.review=review;plan.state=proposal['state'];plan.document=proposal
    task.document=dict(task.document,data_migration_plan=proposal)
    event(db,request,task,'REVIEW_GENERATED_DATA_MIGRATION',body.note,plan_id=plan.id,decision=body.action,fingerprint=plan.fingerprint)
    db.commit();return plan


def execute_synthetic_migration(db,request,task,body):
    source(db,request,task);version=current(db,request,task);expected(task,body.expected_revision)
    plan=db.get(DataMigrationPlan,body.plan_id)
    if not plan or plan.task_id!=task.id or plan.state!='APPROVED_FOR_TEST' or not plan.review:
        raise HTTPException(409,'Only an independently approved test plan can run.')
    current_plan=task.document.get('data_migration_plan',{})
    if task.document.get('data_migration_plan_id')!=plan.id or current_plan.get('fingerprint')!=plan.fingerprint or plan.review.get('fingerprint')!=plan.fingerprint:
        raise HTTPException(409,'Approved plan is stale or is no longer the current reviewed proposal.')
    if plan.document.get('target_engine')!='SQLITE_TEST': raise HTTPException(409,'The local isolated runner accepts only the SQLite synthetic-test target.')
    if plan.document['bindings'].get('architecture_version_fingerprint')!=version.fingerprint or plan.document['bindings'].get('repository_commit')!=task.document['commit']:
        raise HTTPException(409,'Plan no longer matches the pinned source and architecture version.')
    if body.data_classification!='SYNTHETIC': raise HTTPException(422,'Only synthetic fixtures are accepted by this local test runner.')
    # Persist an attempt before execution; fixture rows never enter task history or durable storage.
    run=DataMigrationRun(tenant_id=task.tenant_id,task_id=task.id,plan_id=plan.id,actor_id=request.state.identity['id'],state='RUNNING',document=dict(plan_fingerprint=plan.fingerprint,environment='EPHEMERAL_SQLITE_MEMORY',data_classification='SYNTHETIC'))
    db.add(run);db.flush();db.commit()
    try: result=migration_test_runner.execute(plan.document,body.rows)
    except (ValueError,TypeError,KeyError,sqlite3.Error) as error:
        code=str(error) if str(error).isupper() and len(str(error))<80 else 'SYNTHETIC_TEST_INPUT_INVALID'
        result=dict(state='FAIL',environment='EPHEMERAL_SQLITE_MEMORY',data_classification='SYNTHETIC',raw_fixture_persisted=False,database_url_persisted=False,
            checks=[dict(name='MIGRATION_TEST',status='FAIL',code=code)],recovery=dict(state='EPHEMERAL_DATABASE_DISCARDED',backup_restore_tested=False))
    run.state=result['state'];run.document=dict(run.document,**result)
    task.document=dict(task.document,data_migration_run_id=run.id)
    event(db,request,task,'RUN_SYNTHETIC_DATA_MIGRATION_TEST',body.note,run_id=run.id,plan_fingerprint=plan.fingerprint,result=result['state'])
    db.commit();return run


def contract(db, request, task, body):
    source(db, request, task); current(db, request, task); workspace.checked(request.app.state.config, task)
    if task.state not in ('PLANNED','READY','STAGED','VALIDATION_BLOCKED'): raise HTTPException(409, 'Task does not accept contracts in this state.')
    if len(contracts(db, task)) >= 100: raise HTTPException(409, 'Contract limit reached.')
    if body.test_file not in task.document['files'] or body.test_file not in task.document['workspace']['current']: raise HTTPException(422, 'Contract must reference a captured test file.')
    try: sanitize(body.scenario + '\n' + body.expected_behavior, 'BLOCK')
    except FilterDenied: raise HTTPException(422, 'Contract contains sensitive data.')
    item = BehavioralContract(tenant_id=task.tenant_id, task_id=task.id, actor_id=request.state.identity['id'], document=dict(**body.model_dump(), test_file_sha256=task.document['workspace']['baseline'][body.test_file]))
    db.add(item); event(db, request, task, 'ADD_CONTRACT', body.name); db.commit(); return item


def review_contract(db, request, task, cid, body):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED','READY','STAGED','VALIDATION_BLOCKED'): raise HTTPException(409, 'Task does not accept contract reviews in this state.')
    if request.state.identity['kind'] != 'HUMAN': raise HTTPException(403, 'Human contract review is required.')
    item = get(db, BehavioralContract, cid)
    if item.task_id != task.id: raise HTTPException(404, 'Contract not found in this task.')
    if item.review: raise HTTPException(409, 'Contract review is immutable; create a new contract.')
    item.review = dict(actor=request.state.identity['id'], at=now().isoformat(), note=body.note, hash=digest(item.document))
    event(db, request, task, 'REVIEW_CONTRACT', body.note); db.commit()


def propose(db, request, task, body, provenance=None):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED','READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'This slice accepts an initial patch against the pinned baseline. Replan in a new task after staging.')
    work = workspace.checked(request.app.state.config, task)
    edits = [e.model_dump() for e in body.edits]
    if len({e['path'].casefold() for e in edits}) != len(edits): raise HTTPException(422, 'Duplicate patch path.')
    if len(list(db.scalars(select(ChangeSet.id).where(ChangeSet.task_id == task.id)))) >= 50: raise HTTPException(409, 'Changeset limit reached.')
    total_bytes = 0
    for e in edits:
        if e['path'] not in task.document['allowed_files']: raise HTTPException(403, 'Patch escapes the declared file scope.')
        old_hash = task.document['workspace']['current'].get(e['path'])
        if old_hash != e['expected_sha256'] or (e['operation'] == 'ADD') != (old_hash is None): raise HTTPException(409, 'Patch baseline hash or operation does not match current files.')
        if e['operation'] == 'MODIFY' and workspace.sha(e['content'].encode()) == old_hash: raise HTTPException(422, 'Patch contains an unchanged file.')
        if e['operation'] == 'DELETE' and e['content']: raise HTTPException(422, 'Deleted files cannot include replacement content.')
        try: sanitize(e['content'], 'BLOCK')
        except FilterDenied: raise HTTPException(422, 'Patch contains sensitive content.')
        total_bytes += len(e['content'].encode())
    if total_bytes > 1048576: raise HTTPException(413, 'Changeset exceeds one MiB.')
    risky = any(e['operation'] == 'DELETE' or e['path'].endswith(('.xml','.properties','.yml','.yaml','.sql','.gradle')) or any(k in e['path'].lower() for k in ('security','auth','test','migration','api/')) for e in edits)
    doc = dict(edits=edits, reason=body.note, risk='HIGH' if risky or len(edits) > 20 else 'MEDIUM',
        baseline=digest(task.document['workspace']['current']), commit=task.document['commit'], evidence_ids=task.document['evidence_ids'],
        dependency_changes='REVIEW_REQUIRED' if risky else 'NOT_ASSESSED', api_changes='NOT_ASSESSED', database_changes='NOT_ASSESSED',
        validations=dict(architecture='NOT_RUN', security='NOT_RUN', behavior='NOT_RUN'),
        generation=provenance or dict(kind='MANUAL'))
    fingerprint = digest(doc)
    existing = db.scalar(select(ChangeSet).where(ChangeSet.task_id == task.id, ChangeSet.fingerprint == fingerprint))
    if existing: return existing
    item = ChangeSet(tenant_id=task.tenant_id, task_id=task.id, actor_id=request.state.identity['id'], fingerprint=fingerprint, document=doc)
    db.add(item); event(db, request, task, 'PROPOSE_CHANGE', body.note, fingerprint=fingerprint); db.commit(); return item


def generate(db, request, task, body):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if not policy(db, request).document.get('build_execution_enabled'):
        raise HTTPException(403, 'Enable isolated build execution before running a Java recipe.')
    if task.state not in ('PLANNED', 'READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Generate a recipe only against the pinned task baseline.')
    if body.implementation_file == body.interface_file or body.implementation_file not in task.document['workspace']['current']:
        raise HTTPException(422, 'Choose an existing implementation and a different interface path.')
    if body.interface_file in task.document['workspace']['current']:
        raise HTTPException(409, 'The interface output path already exists.')
    if body.implementation_file not in task.document['allowed_files'] or body.interface_file not in task.document['allowed_files']:
        raise HTTPException(403, 'Recipe files must be inside the declared change scope.')
    if body.interface_file.rsplit('/', 1)[-1] != body.interface_name + '.java':
        raise HTTPException(422, 'The interface file name must match its public Java type.')
    if body.interface_file.rpartition('/')[0] != body.implementation_file.rpartition('/')[0]:
        raise HTTPException(422, 'Generate the interface beside its implementation in the same package.')
    if len(task.history) >= 200 or len(list(db.scalars(select(ChangeSet.id).where(ChangeSet.task_id == task.id)))) >= 50:
        raise HTTPException(409, 'Task limit reached; create a new task.')
    work = workspace.checked(request.app.state.config, task)
    generated = sandbox.refactor(request.app.state.config, task, str(uuid4()), work,
        body.implementation_file, body.interface_file, body.interface_name, body.methods)
    provenance = {k:v for k,v in generated.items() if k != 'contents'}
    provenance['input_sha256'] = task.document['workspace']['current'][body.implementation_file]
    edits = [dict(path=body.implementation_file, operation='MODIFY',
                  expected_sha256=task.document['workspace']['current'][body.implementation_file], content=generated['contents'][0]),
             dict(path=body.interface_file, operation='ADD', expected_sha256=None, content=generated['contents'][1])]
    payload = ChangeInput(expected_revision=body.expected_revision, note=body.note, edits=edits)
    return propose(db, request, task, payload, provenance=provenance)


def generate_microservice(db, request, task, body):
    """Send only a mapped one-service source slice after explicit per-call consent."""
    from app.ai import claude, gemini
    from app.ai.gateway import event as model_event
    from app.ai.models import ModelInvocation
    from app.evidence.builder import digest as fingerprint
    from app.transformation.workspace import file_path
    import os
    import re
    import shutil
    from uuid import uuid4

    context, policy_revision, _ = source(db, request, task)
    version = current(db, request, task)
    expected(task, body.expected_revision)
    identity = request.state.identity
    provider = body.provider
    label = {'GEMINI': 'Gemini', 'CLAUDE': 'Claude'}[provider]
    config = request.app.state.config
    if identity.get('kind') != 'HUMAN':
        raise HTTPException(403, f'A human must approve each {label} source transfer.')
    policy_item = latest_policy(db, identity['tenant_id'])
    if not policy_item or not policy_item.document.get(f'{provider.lower()}_source_transfer_enabled', False):
        raise HTTPException(403, f'Workspace security policy has not enabled {label} source transfer.')
    key = config.gemini_api_key if provider == 'GEMINI' else config.anthropic_api_key
    if not key.get_secret_value():
        raise HTTPException(503, f'{label} API key is not configured locally.')
    if provider == 'CLAUDE':
        from datetime import timedelta
        since = now() - timedelta(hours=24)
        recent = db.scalars(select(ModelInvocation).where(ModelInvocation.tenant_id == identity['tenant_id'], ModelInvocation.created_at >= since))
        used = sum(1 for row in recent if (row.metadata_json or {}).get('destination') == 'CLAUDE_EXTERNAL')
        if used >= config.claude_max_generations_per_day:
            raise HTTPException(429, f'The daily limit of {config.claude_max_generations_per_day} Claude generations is reached (CLAUDE_MAX_GENERATIONS_PER_DAY).')
    workspace_policy_revision = policy_item.revision
    binding = task.document.get('microservice')
    if not binding or binding.get('rollout_mode') != 'ONE_BY_ONE':
        raise HTTPException(409, 'This task is not bound to a one-by-one service candidate.')
    proposal = db.get(ModernizationAssessment, task.assessment_id)
    if (not proposal or binding.get('source_version_fingerprint') != version.fingerprint or
            binding.get('proposal_fingerprint') != proposal.fingerprint):
        raise HTTPException(409, 'Candidate plan or architecture version binding is stale.')
    if task.state not in ('PLANNED', 'READY') or task.document['workspace']['current'] != task.document['workspace']['baseline']:
        raise HTTPException(409, 'Generation requires an unchanged pinned task baseline.')
    if task.document.get('microservice_generation'):
        raise HTTPException(409, 'A service generation already exists; review it or prepare a new pinned task.')
    missing = gaps(db, task)
    if missing:
        raise HTTPException(409, {'message':'Complete the required baseline and reviewed behavioral contracts first.','gaps':missing})
    work = workspace.checked(request.app.state.config, task)
    analysis_run = get(db, AnalysisRun, version.analysis_id)
    if not analysis_run or analysis_run.status != 'COMPLETED' or not analysis_run.result:
        raise HTTPException(409, 'A completed baseline analysis is required.')
    analysis = copy.deepcopy(analysis_run.result)
    domains = version.document.get('domains') or analysis.get('domains', [])
    if domains:
        analysis['domains'] = copy.deepcopy(domains)
        assignment = {class_id: domain['id'] for domain in domains for class_id in domain.get('classes', [])}
        for row in analysis.get('classes', []):
            if row.get('id') in assignment:
                row['domain_id'] = assignment[row['id']]
    contracts_rows = contracts(db, task)
    boundary = extraction.build_plan(analysis, binding['candidate_id'], task.document['workspace']['baseline'],
        complete_source_snapshot=task.document['complete_source_snapshot'], contracts=contracts_rows,
        data_ownership_review=task.document.get('data_migration_ownership_review'))
    required_mapping = {'TARGET_DOMAIN_NOT_PRESENT_IN_BASELINE','COMPLETE_SOURCE_SNAPSHOT_REQUIRED',
                        'TARGET_SOURCE_FILES_UNRESOLVED_OR_AMBIGUOUS','SOURCE_FILES_CONTAIN_CLASSES_OUTSIDE_TARGET_DOMAIN',
                        'CYCLE_CROSSES_PROPOSED_EXTRACTION_BOUNDARY'}
    mapping_blockers = sorted(required_mapping.intersection(boundary['blockers']))
    if mapping_blockers:
        raise HTTPException(409, {'message':'Candidate source mapping is not complete enough for code generation.','blockers':mapping_blockers})
    visible = {item['path']:item['content'] for item in context['files']}
    target_paths = set(boundary['target']['source_files'])
    # Include same-package Java tests only; exclude unrelated services and source.
    package_paths = {package.replace('.', '/') for package in boundary['target']['packages'] if package not in ('(default)','(unknown)')}
    for path in visible:
        if '/src/test/' in '/' + path and path.endswith('.java') and any(part in path for part in package_paths):
            target_paths.add(path)
    selected = []
    for path in sorted(target_paths):
        content = visible.get(path)
        if content is None:
            raise HTTPException(409, 'Mapped candidate source is outside the authorized captured task scope.')
        selected.append(dict(path=path, content=content))
    if not selected:
        raise HTTPException(409, 'No unambiguous source files map to this service candidate.')
    contract_context = [dict(name=row.document['name'], test_case=row.document['test_case'],
                             scenario=row.document['scenario'], expected_behavior=row.document['expected_behavior'])
                       for row in contracts_rows if row.review]
    candidate = dict(candidate_id=binding['candidate_id'], name=binding['name'],
        repository_name=binding['repository_name'], class_ids=binding.get('class_ids', []),
        packages=binding.get('packages', []), dependencies=boundary['boundary']['edges'],
        data_signals=binding.get('data_signals',{}),
        source_mapping=boundary['target']['source_mapping'], data_ownership='UNCONFIRMED',
        data_migration='NOT_AUTHORIZED_OR_EXECUTED')
    prompt = microservice_codegen.prompt_for(candidate, selected, contract_context, version.id, task.document['commit'])
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', binding['repository_name']):
        raise HTTPException(409, 'Candidate repository name is not portable.')

    invocation = str(uuid4())
    source_hash = fingerprint({'files':{path:fingerprint(content) for path,content in sorted((f['path'],f['content']) for f in selected)},
                               'contracts':contract_context})
    meta = dict(destination=f'{provider}_EXTERNAL', external_transfer=True, provider=provider,
        task_id=task.id, repository_id=task.repository_id, commit=task.document['commit'],
        architecture_version_id=version.id, candidate_id=binding['candidate_id'],
        source_file_count=len(selected), source_context_bytes=len(prompt.encode('utf-8')),
        source_context_sha256=fingerprint(prompt), selected_source_sha256=source_hash,
        policy_revision=workspace_policy_revision, model=config.gemini_model if provider == 'GEMINI' else config.claude_model)
    task_id=task.id
    with LOCK:
        db.expire_all()
        task=owned(db,request,task_id)
        expected(task,body.expected_revision)
        if task.state not in ('PLANNED','READY') or task.document.get('microservice_generation'):
            raise HTTPException(409,'Task changed or already contains a generated service repository.')
        if len(task.history) >= 198:
            raise HTTPException(409, 'Task history limit reached; create a new task before requesting generation.')
        if task.document.get('microservice_generation_request'):
            raise HTTPException(409, 'This task already has a generation attempt; prepare a new pinned task.')
        task.document=dict(task.document,microservice_generation_request=dict(invocation_id=invocation,
            state='REQUESTED',request_fingerprint=fingerprint(meta)))
        task.state='GENERATING'
        event(db,request,task,f'{provider}_GENERATION_REQUESTED',
              'Human approved the selected source transfer; generation is in progress.',
              invocation_id=invocation,candidate_id=binding['candidate_id'])
        claimed_revision=task.revision
        db.commit()
    try:
        model_event(request, identity, invocation, 'REQUESTED', 'PER_REQUEST_HUMAN_APPROVAL', meta,
                    resource='microservice:'+binding['candidate_id'])
        generated, usage = (gemini.generate if provider == 'GEMINI' else claude.generate)(prompt, config)
        checked = microservice_codegen.validate_bundle(generated)
        # Reauthorize the same exact inputs after the network call before writing.
        db.expire_all()
        task = owned(db, request, task_id)
        version_after = current(db, request, task)
        context_after, revision_after, _ = source(db, request, task)
        latest_workspace_policy = latest_policy(db, identity['tenant_id'])
        if revision_after != policy_revision or not latest_workspace_policy or latest_workspace_policy.revision != workspace_policy_revision:
            raise microservice_codegen.BundleFailure('AUTHORIZATION_CHANGED')
        if (task.document['workspace']['current'] != task.document['workspace']['baseline'] or
                task.revision != claimed_revision or task.state != 'GENERATING' or
                (task.document.get('microservice_generation_request') or {}).get('invocation_id') != invocation):
            raise microservice_codegen.BundleFailure('TASK_CHANGED')
        if version_after.fingerprint != version.fingerprint:
            raise microservice_codegen.BundleFailure('ARCHITECTURE_VERSION_CHANGED')
        workspace.checked(request.app.state.config, task)
        after_files={item['path']:item['content'] for item in context_after['files']}
        for item in selected:
            if after_files.get(item['path']) != item['content']:
                raise microservice_codegen.BundleFailure('SOURCE_CONTEXT_CHANGED')
        contracts_after = [dict(name=row.document['name'], test_case=row.document['test_case'],
                             scenario=row.document['scenario'], expected_behavior=row.document['expected_behavior'])
                           for row in contracts(db, task) if row.review]
        if fingerprint({'files':{path:fingerprint(content) for path,content in sorted((f['path'],f['content']) for f in selected)},
                        'contracts':contracts_after}) != source_hash:
            raise microservice_codegen.BundleFailure('SOURCE_CONTEXT_CHANGED')
        root = workspace.root(request.app.state.config, task)
        services_root = root / 'generated-services'
        if services_root.exists(): workspace.no_links(services_root)
        services_root.mkdir(parents=True, exist_ok=True)
        final = services_root / binding['repository_name']
        if final.exists(): raise microservice_codegen.BundleFailure('SERVICE_REPOSITORY_EXISTS')
        pending = services_root / ('pending-' + uuid4().hex)
        pending.mkdir()
        file_manifest = []
        try:
            for item in checked['files']:
                target = file_path(pending, item['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(item['content'], encoding='utf-8', newline='\n')
                file_manifest.append(dict(path=item['path'], sha256=workspace.sha(item['content'].encode('utf-8')),
                                          rationale=item['rationale']))
            from app.access.gateway import git
            git(pending, 'init', '--template=')
            git(pending, 'config', 'core.autocrlf', 'false')
            git(pending, 'config', 'core.hooksPath', os.devnull)
            git(pending, 'add', '-f', '--', *[f['path'] for f in checked['files']])
            git(pending, '-c', 'user.name=ArchIntel', '-c', 'user.email=local@archintel.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-m', 'Generated service proposal; validation pending')
            git_commit = git(pending, 'rev-parse', 'HEAD').decode().strip()
            os.replace(pending, final)
        except Exception:
            if pending.exists():
                workspace.no_links(pending)
                if pending.resolve().is_relative_to(services_root.resolve()):
                    shutil.rmtree(pending, ignore_errors=True)
            raise
        generation = dict(state='GENERATED_UNVALIDATED', repository_name=binding['repository_name'],
            local_path=str(final), git_commit=git_commit, candidate_id=binding['candidate_id'],
            source_commit=task.document['commit'], source_manifest_sha256=fingerprint(task.document['workspace']['baseline']),
            architecture_version_id=version.id, architecture_version_fingerprint=version.fingerprint,
            plan_fingerprint=binding['proposal_fingerprint'], selected_source_sha256=source_hash,
            fingerprint=checked['fingerprint'], files=file_manifest,
            unresolved_questions=checked['unresolved_questions'], model=usage['model'], provider=provider,
            usage={key:value for key,value in usage.items() if key in ('prompt_tokens','output_tokens','duration_ms','estimated_cost_usd')},
            validation='NOT_RUN', publication='DISABLED')
        updated_document=dict(task.document)
        updated_document.pop('microservice_generation_request',None)
        updated_document['microservice_generation']=generation
        task.document=updated_document
        task.state='READY'
        event(db, request, task, 'GENERATE_MICROSERVICE_REPOSITORY',
              'Generated local candidate repository (service_candidate); validation remains required.',
              generation_fingerprint=checked['fingerprint'], invocation_id=invocation)
        db.commit()
        model_event(request, identity, invocation, 'ALLOW', 'STRUCTURED_BUNDLE_VALIDATED',
                    dict(meta, generation_fingerprint=checked['fingerprint'], file_count=len(file_manifest), usage=generation['usage']),
                    resource='microservice:'+binding['candidate_id'])
        return generation
    except Exception as error:
        code = error.args[0] if isinstance(error, (microservice_codegen.BundleFailure, gemini.GeminiFailure, claude.ClaudeFailure)) and error.args else 'GENERATION_FAILED'
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9_]{1,80}', code): code='GENERATION_FAILED'
        db.rollback()
        try:
            db.expire_all()
            failed_task=owned(db,request,task_id)
            attempt=failed_task.document.get('microservice_generation_request') or {}
            if attempt.get('invocation_id')==invocation and failed_task.state=='GENERATING':
                failed_task.document=dict(failed_task.document,microservice_generation_request=dict(
                    invocation_id=invocation,state='FAILED',error_code=code,
                    request_fingerprint=attempt.get('request_fingerprint')))
                failed_task.state='FAILED'
                event(db,request,failed_task,f'{provider}_GENERATION_FAILED',
                    f'Generation failed closed ({provider}_GENERATION_FAILED); no output was approved.',invocation_id=invocation,error_code=code)
                db.commit()
        except Exception:
            db.rollback()
        model_event(request, identity, invocation, 'REJECTED', code, meta, resource='microservice:'+binding['candidate_id'])
        if isinstance(error, HTTPException): raise
        raise HTTPException(422, f'{label} output was not accepted ('+code+').') from None


def change(db, task, cid):
    item = get(db, ChangeSet, cid)
    if item.task_id != task.id: raise HTTPException(404, 'Changeset not found in this task.')
    return item


def patch(db, request, task, item):
    source(db, request, task); work = workspace.checked(request.app.state.config, task)
    if digest(task.document['workspace']['current']) != item.document['baseline'] and item.state != 'STAGED': raise HTTPException(409, 'Patch context changed.')
    lines = []
    for e in item.document['edits']:
        # Diff is against the pinned task baseline for this bounded initial slice.
        old = workspace.file_path(workspace.root(request.app.state.config, task) / 'baseline', e['path'])
        before = old.read_bytes().decode('utf-8').splitlines(keepends=True) if old.exists() else []
        after = e['content'].splitlines(keepends=True) if e['operation'] != 'DELETE' else []
        lines.extend(difflib.unified_diff(before, after, fromfile='a/' + e['path'], tofile='b/' + e['path']))
    return dict(id=item.id, fingerprint=item.fingerprint, risk=item.document['risk'], state=item.state, diff=''.join(lines), validation=item.document['validations'], generation=item.document.get('generation', {'kind': 'MANUAL'}))


def review_change(db, request, task, item, body):
    _, revision, grant = source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED','READY'): raise HTTPException(409, 'Task is not available for patch review.')
    workspace.checked(request.app.state.config, task)
    if item.state != 'PROPOSED' or item.fingerprint != body.fingerprint or item.document['baseline'] != digest(task.document['workspace']['current']): raise HTTPException(409, 'Changeset or source context changed.')
    if body.action == 'APPROVE_STAGING' and item.document['risk'] == 'HIGH':
        if 'SECURITY_ADMIN' not in request.state.identity['permissions'] or item.actor_id == request.state.identity['id']:
            raise HTTPException(403, 'High-risk staging requires a different human security administrator with source scope.')
    if request.state.identity['kind'] != 'HUMAN': raise HTTPException(403, 'Human review is required.')
    item.state = 'APPROVED_FOR_STAGING' if body.action == 'APPROVE_STAGING' else 'REJECTED'
    item.approval = dict(actor=request.state.identity['id'], at=now().isoformat(), expires_at=(now()+timedelta(hours=24)).isoformat(), note=body.note,
        fingerprint=item.fingerprint, policy_revision=revision, grant_digest=grant)
    event(db, request, task, body.action, body.note, fingerprint=item.fingerprint); db.commit()


def stage(db, request, task, item, body):
    _, revision, _ = source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if task.state not in ('PLANNED','READY') or item.state != 'APPROVED_FOR_STAGING': raise HTTPException(409, 'Task or changeset is not ready for isolated staging.')
    if len(task.history) > 197: raise HTTPException(409, 'Insufficient task history budget for staging; replan.')
    approval = item.approval
    approver = db.get(Principal, approval['actor'])
    grant = db.scalar(select(SourceGrant).where(SourceGrant.repository_id == task.repository_id, SourceGrant.principal_id == approval['actor']))
    grant_hash = digest(dict(allowed=grant.allowed_paths, protected=grant.protected_paths)) if grant else None
    if not approver or not approver.active or 'SOURCE_READ' not in approver.permissions or (item.document['risk']=='HIGH' and 'SECURITY_ADMIN' not in approver.permissions) or grant_hash != approval['grant_digest'] or revision != approval['policy_revision'] or datetime.fromisoformat(approval['expires_at']) < now():
        raise HTTPException(409, 'Staging approval expired or authorization/policy changed.')
    if digest(task.document['workspace']['current']) != item.document['baseline']: raise HTTPException(409, 'Patch baseline changed.')
    # Commit intent before a filesystem mutation. On crash, recovery marks manual inspection required.
    task.document = dict(task.document, pending_changeset=item.id, recovery_hashes={e['path']:[e['expected_sha256'], None if e['operation']=='DELETE' else workspace.sha(e['content'].encode())] for e in item.document['edits']})
    task.state = 'STAGING'; event(db, request, task, 'STAGING_STARTED', body.note); db.commit()
    manifest = workspace.apply(request.app.state.config, task, item.document['edits'])
    task.document = dict(task.document, workspace=dict(task.document['workspace'], current=manifest), staged_changeset=item.id)
    task.state = 'STAGED'; item.state = 'STAGED'; event(db, request, task, 'STAGED', body.note); db.commit()


def action(db, request, task, body):
    source(db, request, task); expected(task, body.expected_revision)
    if task.state == 'GENERATING': raise HTTPException(409, 'Wait for the active Gemini generation attempt to finish or be recovered.')
    if task.document.get('candidate_architecture') or task.document.get('final_approval'):
        raise HTTPException(409, 'A published candidate version is immutable; create a new task for further changes.')
    if body.action != 'PAUSE' and any(b.state == 'RUNNING' for b in builds(db, task)):
        raise HTTPException(409, 'Wait for the current isolated build attempt to finish before changing task files or resuming.')
    if body.action == 'PAUSE':
        if task.state in ('PAUSED','ROLLED_BACK'): raise HTTPException(409, 'Task cannot be paused in this state.')
        task.document = dict(task.document, resume_state=task.state); task.state = 'PAUSED'
    elif body.action == 'RESUME':
        if task.state != 'PAUSED': raise HTTPException(409, 'Task is not paused.')
        current(db, request, task); workspace.checked(request.app.state.config, task)
        task.state = 'VALIDATION_BLOCKED' if task.document.get('staged_changeset') else 'PLANNED'
    elif body.action == 'ROLLBACK':
        if task.state in ('BUILDING','STAGING','ROLLED_BACK'): raise HTTPException(409, 'Task cannot be rolled back in this state.')
        manifest = workspace.rollback(request.app.state.config, task)
        task.document = dict(task.document, workspace=dict(task.document['workspace'], current=manifest))
        task.state = 'ROLLED_BACK'
        for c in db.scalars(select(ChangeSet).where(ChangeSet.task_id == task.id, ChangeSet.state.in_(['STAGED','APPROVED_FOR_STAGING']))): c.state = 'ROLLED_BACK'
    else:
        current(db, request, task); workspace.checked(request.app.state.config, task)
        if task.state not in ('PLANNED','READY','FAILED'): raise HTTPException(409, 'Task cannot recheck prerequisites in this state.')
        task.state = 'READY' if not gaps(db, task) else 'PLANNED'
    event(db, request, task, body.action, body.note); db.commit()


def build(db, request, task, kind, body):
    with LOCK:
        source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
        p = policy(db, request)
        if not p.document.get('build_execution_enabled'): raise HTTPException(403, 'Build execution is disabled by workspace policy.')
        if kind not in ('BASELINE','CANDIDATE'): raise HTTPException(422, 'Unknown build kind.')
        if task.state not in ('PLANNED','READY','STAGED','VALIDATION_BLOCKED','FAILED'): raise HTTPException(409, 'Task is not available for a build.')
        if kind == 'CANDIDATE' and not task.document.get('staged_changeset'): raise HTTPException(409, 'Stage a reviewed changeset first.')
        if not task.document['complete_source_snapshot']: raise HTTPException(409, 'A baseline build requires a complete authorized source snapshot.')
        workspace.checked(request.app.state.config, task)
        if len(builds(db, task)) >= 50: raise HTTPException(409, 'Build attempt limit reached.')
        if len(task.history) > 197: raise HTTPException(409, 'Insufficient task history budget for a build; replan.')
        path = workspace.root(request.app.state.config, task) / ('baseline' if kind == 'BASELINE' else 'worktree')
        staged = change(db, task, task.document['staged_changeset']) if kind == 'CANDIDATE' else None
        item = BuildRun(tenant_id=task.tenant_id, task_id=task.id, actor_id=request.state.identity['id'], kind=kind, state='RUNNING', document=dict(input_sha256=digest(workspace.inventory(path)), policy_revision=p.revision, changeset_fingerprint=staged.fingerprint if staged else None))
        db.add(item); task.state = 'BUILDING'; event(db, request, task, 'BUILD_STARTED', body.note); db.commit()
    artifact_target = workspace.root(request.app.state.config, task) / 'artifacts' / (item.id + ('.war' if task.document['artifact_path'].endswith('.war') else '.jar')) if kind == 'CANDIDATE' else None
    try: result = sandbox.run(request.app.state.config, task, item.id, path, artifact_target); code = None
    except Exception as error:
        result = None; code = str(error) if isinstance(error, sandbox.SandboxError) else type(error).__name__
    with LOCK:
        db.expire_all(); task = owned(db, request, task.id); item = get(db, BuildRun, item.id)
        item.document = dict(item.document, error_code=code, result=result)
        item.state = 'FAILED'
        # No successful result is trusted if policy, source or task state changed mid-run.
        valid = False
        try:
            _, revision, _ = source(db, request, task)
            current(db, request, task); workspace.checked(request.app.state.config, task)
            valid = policy(db, request).document.get('build_execution_enabled') and revision == item.document['policy_revision'] and task.state == 'BUILDING'
        except (HTTPException, ValueError): valid = False
        # read_context rolls back its read transaction; assign durable results only afterward.
        item.document = dict(item.document, error_code=code, result=result)
        passed = valid and result and result['tests'] > result['skipped'] and result['failures'] == 0 and result['errors'] == 0
        if kind == 'BASELINE' and result and result['artifact_sha256'] != task.document['expected_artifact_sha256']:
            passed = False; item.document = dict(item.document, error_code='BASELINE_ARTIFACT_MISMATCH')
        item.state = 'PASSED' if passed else 'FAILED'
        if task.state != 'PAUSED': task.state = 'PLANNED' if kind == 'BASELINE' and not task.document.get('staged_changeset') else 'VALIDATION_BLOCKED'
        db.flush()
        if kind == 'BASELINE' and task.state == 'PLANNED' and not gaps(db, task): task.state = 'READY'
        event(db, request, task, 'BUILD_FINISHED', 'Structured BUILD result recorded; raw build output is not retained.', build_id=item.id)
        db.commit(); return item


def scan_security(db, request, task, body):
    with LOCK:
        source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
        p = policy(db, request)
        if not p.document.get('build_execution_enabled'): raise HTTPException(403, 'Isolated execution is disabled.')
        workspace.checked(request.app.state.config, task)
        attempts = builds(db, task)
        if task.state != 'VALIDATION_BLOCKED' or any(b.state == 'RUNNING' for b in attempts):
            raise HTTPException(409, 'Finish the candidate build before security analysis.')
        if len(attempts) >= 50 or len(task.history) > 197: raise HTTPException(409, 'Task attempt limit reached.')
        candidate = next((b for b in reversed(attempts) if b.kind == 'CANDIDATE'), None)
        item = change(db, task, task.document['staged_changeset'])
        source_hash = digest(task.document['workspace']['current'])
        if not candidate or candidate.state != 'PASSED' or candidate.document.get('input_sha256') != source_hash or candidate.document.get('changeset_fingerprint') != item.fingerprint:
            raise HTTPException(409, 'A passing build of the current changeset is required.')
        capture = (candidate.document.get('result') or {}).get('artifact_capture') or {}
        path = workspace.root(request.app.state.config, task) / 'artifacts' / (candidate.id + ('.war' if task.document['artifact_path'].endswith('.war') else '.jar'))
        workspace.no_links(path)
        if capture.get('path') != str(path) or not path.is_file() or not 0 < path.stat().st_size <= 33554432 or path.stat().st_size != capture.get('size') or file_hash(path) != capture.get('sha256') or capture.get('sha256') != candidate.document['result'].get('artifact_sha256'):
            raise HTTPException(409, 'Candidate artifact integrity failed; rebuild it.')
        attempt = BuildRun(tenant_id=task.tenant_id, task_id=task.id, actor_id=request.state.identity['id'], kind='SECURITY', state='RUNNING',
            document=dict(input_sha256=source_hash, build_id=candidate.id, changeset_fingerprint=item.fingerprint,
                artifact_sha256=capture['sha256'], policy_revision=p.revision))
        db.add(attempt); task.state='BUILDING'
        task.document=dict(task.document, security_analysis=dict(state='RUNNING'))
        event(db, request, task, 'SECURITY_STARTED', body.note); db.commit()
    try: result=security.scan(request.app.state.config, path); error=None
    except Exception as exc:
        result=None; error=str(exc) if isinstance(exc, sandbox.SandboxError) else 'SECURITY_SCAN_FAILED'
    with LOCK:
        db.expire_all(); task=owned(db, request, task.id); attempt=get(db, BuildRun, attempt.id)
        valid=False
        try:
            _, revision, _=source(db, request, task)
            current(db, request, task); workspace.checked(request.app.state.config, task)
            valid=bool(policy(db, request).document.get('build_execution_enabled')) and revision==attempt.document['policy_revision'] and task.state=='BUILDING' and digest(task.document['workspace']['current'])==attempt.document['input_sha256']
        except (HTTPException, ValueError, OSError): pass
        if not valid: error='SECURITY_CONTEXT_CHANGED'
        if result and result.get('artifact_sha256') != attempt.document['artifact_sha256']:
            valid=False; error='SECURITY_ARTIFACT_CHANGED'
        attempt.document=dict(attempt.document, result=result, error_code=error)
        attempt.state='PASSED' if valid and result and result['state']=='PASS' else 'FAILED'
        task.document=dict(task.document, security_analysis=dict(attempt.document, attempt_id=attempt.id,
            state=result['state'] if valid and result else 'FAILED'))
        if task.state!='PAUSED': task.state='VALIDATION_BLOCKED'
        event(db, request, task, 'SECURITY_FINISHED', 'Bounded SECURITY findings recorded; raw tool output is not retained.', attempt_id=attempt.id)
        db.commit()


def reanalyze(db, request, task, body):
    source(db, request, task); version = current(db, request, task); expected(task, body.expected_revision)
    workspace.checked(request.app.state.config, task)
    if task.state != 'VALIDATION_BLOCKED' or any(b.state == 'RUNNING' for b in builds(db, task)):
        raise HTTPException(409, 'Finish the staged candidate build before architecture re-analysis.')
    item = change(db, task, task.document['staged_changeset'])
    candidate = next((b for b in reversed(builds(db, task)) if b.kind == 'CANDIDATE'), None)
    if not candidate or candidate.state != 'PASSED': raise HTTPException(409, 'The latest candidate build must pass.')
    if candidate.document.get('input_sha256') != digest(task.document['workspace']['current']) or candidate.document.get('changeset_fingerprint') != item.fingerprint:
        raise HTTPException(409, 'Candidate source or changeset binding changed; rebuild it.')
    capture = (candidate.document.get('result') or {}).get('artifact_capture') or {}
    expected_path = workspace.root(request.app.state.config, task) / 'artifacts' / (candidate.id + ('.war' if task.document['artifact_path'].endswith('.war') else '.jar'))
    try:
        workspace.no_links(expected_path)
        path = expected_path.resolve()
        if capture.get('path') != str(expected_path) or not path.is_relative_to((workspace.root(request.app.state.config, task) / 'artifacts').resolve()):
            raise ValueError('Artifact path binding failed.')
        if not path.is_file() or not 0 < path.stat().st_size <= 33554432 or file_hash(path) != capture.get('sha256') or path.stat().st_size != capture.get('size') or capture.get('sha256') != candidate.document['result']['artifact_sha256']:
            raise ValueError('Artifact integrity failed.')
        manifest = validate_archive(path, request.app.state.config)
    except (ValueError, OSError, ArtifactError):
        raise HTTPException(409, 'Captured candidate artifact is unavailable or invalid; rebuild it.')
    record = task.document.get('architecture_reanalysis') or {}
    if record:
        if record.get('build_id') != candidate.id or record.get('changeset_fingerprint') != item.fingerprint:
            raise HTTPException(409, 'Candidate evidence changed; start a new source task for another re-analysis.')
        run = get(db, AnalysisRun, record['analysis_id'])
        if run.application_id != version.application_id or run.artifact_id != record['artifact_id']:
            raise HTTPException(409, 'Analysis lineage does not match the task.')
        if run.status in ('QUEUED', 'RUNNING'): return
        if run.status != 'COMPLETED' or not run.result:
            if record.get('state') == 'FAILED': return
            task.document = dict(task.document, architecture_reanalysis=dict(record, state='FAILED', error_code='STATIC_ANALYSIS_FAILED'))
            event(db, request, task, 'REANALYSIS_FAILED', body.note, analysis_id=run.id); db.commit(); return
        baseline = get(db, AnalysisRun, version.analysis_id)
        if digest(baseline.result) != version.manifest['static_sha256'] or run.result.get('artifact', {}).get('sha256') != capture['sha256']:
            raise HTTPException(409, 'Analysis result hash binding failed.')
        if record.get('state') == 'COMPLETED':
            if record.get('candidate_result_sha256') != digest(run.result):
                raise HTTPException(409, 'Candidate analysis result changed after comparison.')
            return
        diff = architecture.compare(baseline.result, run.result)
        impact = architecture.expected_improvement(baseline.result, run.result,
            task.document['domain_id'], task.document.get('expected_improvement_criterion', {}).get('decision_kind', ''))
        task.document = dict(task.document, architecture_reanalysis=dict(record, state='COMPLETED',
            candidate_result_sha256=digest(run.result), diff=diff, expected_improvement=impact))
        task.document.pop('expected_impact_review', None)
        task.document.pop('candidate_architecture', None)
        task.document.pop('final_approval', None)
        event(db, request, task, 'REANALYSIS_COMPLETED', body.note, analysis_id=run.id,
              diff_fingerprint=diff['fingerprint'], expected_improvement_fingerprint=impact['fingerprint'])
        db.commit(); return
    if not request.app.state.worker.scanner.available():
        raise HTTPException(503, 'Scanner runtime is unavailable.')
    # Share queue admission with ordinary static scans.
    from app.api import admission
    with admission:
        with request.app.state.sessions() as capacity_db:
            active = capacity_db.scalar(select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status.in_(['QUEUED','RUNNING'])))
        if active >= 4: raise HTTPException(429, 'Analysis queue is full.')
        return queue_reanalysis(db, request, task, body, version, item, candidate, path, capture, manifest)


def queue_reanalysis(db, request, task, body, version, item, candidate, path, capture, manifest):
    artifact = Artifact(tenant_id=task.tenant_id, application_id=version.application_id,
        filename='candidate-' + candidate.id + path.suffix, path=str(path), sha256=capture['sha256'],
        size=capture['size'], available=True, manifest=dict(manifest, transformation_task_id=task.id, build_id=candidate.id))
    db.add(artifact); db.flush()
    run = AnalysisRun(tenant_id=task.tenant_id, application_id=version.application_id, artifact_id=artifact.id)
    db.add(run); db.flush()
    task.document = dict(task.document, architecture_reanalysis=dict(state='QUEUED', analysis_id=run.id,
        artifact_id=artifact.id, artifact_sha256=capture['sha256'], build_id=candidate.id,
        changeset_fingerprint=item.fingerprint, baseline_analysis_id=version.analysis_id))
    event(db, request, task, 'REANALYSIS_QUEUED', body.note, analysis_id=run.id); db.commit()
    request.app.state.worker.submit(run.id)


def validate(db, request, task, body):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    workspace.checked(request.app.state.config, task)
    if task.state not in ('STAGED', 'VALIDATION_BLOCKED') or any(b.state == 'RUNNING' for b in builds(db, task)):
        raise HTTPException(409, 'Stage a reviewed patch and finish active builds before comparing evidence.')
    item = change(db, task, task.document['staged_changeset'])
    result = validation.evaluate(task, builds(db, task), contracts(db, task), item)
    result['fingerprint'] = digest(result)
    if task.document.get('validation', {}).get('fingerprint') == result['fingerprint']:
        return
    task.document = dict(task.document, validation=result)
    task.state = 'VALIDATION_BLOCKED'
    event(db, request, task, 'VALIDATE', body.note, validation=result)
    db.commit()


def review_expected_impact(db, request, task, body):
    source(db, request, task); current(db, request, task); expected(task, body.expected_revision)
    if request.state.identity['kind'] != 'HUMAN': raise HTTPException(403, 'Human improvement review is required.')
    record = task.document.get('architecture_reanalysis') or {}
    impact = record.get('expected_improvement') or {}
    if record.get('state') != 'COMPLETED' or impact.get('fingerprint') != body.impact_fingerprint:
        raise HTTPException(409, 'Expected-improvement evidence changed; refresh architecture re-analysis.')
    if body.action == 'ACCEPT' and impact.get('state') != 'PASS':
        raise HTTPException(409, 'The selected measurable improvement was not demonstrated; it cannot be accepted.')
    if task.document.get('expected_impact_review', {}).get('impact_fingerprint') == body.impact_fingerprint:
        raise HTTPException(409, 'This expected-improvement result already has an immutable review.')
    task.document = dict(task.document, expected_impact_review=dict(decision=body.action,
        actor=request.state.identity['id'], at=now().isoformat(), note=body.note,
        impact_fingerprint=body.impact_fingerprint))
    event(db, request, task, 'REVIEW_EXPECTED_IMPROVEMENT', body.note,
          decision=body.action, impact_fingerprint=body.impact_fingerprint)
    db.commit()


def publish_candidate(db, request, task, body):
    source(db, request, task); expected(task, body.expected_revision)
    if request.state.identity['kind'] != 'HUMAN': raise HTTPException(403, 'Candidate version publication requires a human reviewer.')
    if task.document.get('candidate_architecture'):
        raise HTTPException(409, 'A candidate architecture version has already been published for this task.')
    current(db, request, task); workspace.checked(request.app.state.config, task)
    if task.state != 'VALIDATION_BLOCKED' or any(b.state == 'RUNNING' for b in builds(db, task)):
        raise HTTPException(409, 'Finish candidate builds and validation before publication.')
    item = change(db, task, task.document.get('staged_changeset', ''))
    result = validation.evaluate(task, builds(db, task), contracts(db, task), item)
    stored = task.document.get('validation') or {}
    if stored.get('fingerprint') != digest(result):
        raise HTTPException(409, 'Validation evidence is stale; rerun comparison before publication.')
    mandatory = [gate for gate in result['gates'] if gate['name'] != 'CANONICAL_CANDIDATE_VERSION']
    if any(gate['status'] != 'PASS' for gate in mandatory):
        raise HTTPException(409, dict(message='Candidate version publication is blocked by incomplete evidence.', gates=mandatory))
    reanalysis = task.document.get('architecture_reanalysis') or {}
    candidate = next((b for b in reversed(builds(db, task)) if b.kind == 'CANDIDATE'), None)
    if reanalysis.get('state') != 'COMPLETED' or not candidate or not reanalysis.get('analysis_id'):
        raise HTTPException(409, 'A completed candidate re-analysis bound to the latest build is required.')
    base = version_owned(db, request, task.version_id)
    run = get(db, AnalysisRun, reanalysis['analysis_id'])
    if run.application_id != base.application_id or run.result is None or digest(run.result) != reanalysis.get('candidate_result_sha256'):
        raise HTTPException(409, 'Candidate analysis result no longer matches its captured fingerprint.')
    name = ('Candidate ' + base.name + ' / ' + task.id[:8])[:160]
    request_body = VersionInput(analysis_id=run.id, name=name, parent_id=base.id)
    candidate_version = evidence_service.create(db, base.application_id, request_body,
        request.app.state.config, request.state.identity['id'], commit=False)
    capture = (candidate.document.get('result') or {}).get('artifact_capture') or {}
    task.document = dict(task.document, candidate_architecture=dict(state='PUBLISHED', version_id=candidate_version.id,
        version_fingerprint=candidate_version.fingerprint, parent_version_id=base.id, analysis_id=run.id,
        build_id=candidate.id, changeset_fingerprint=item.fingerprint, artifact_sha256=capture.get('sha256'),
        published_at=now().isoformat()))
    refreshed = validation.evaluate(task, builds(db, task), contracts(db, task), item)
    refreshed['fingerprint'] = digest(refreshed)
    task.document = dict(task.document, validation=refreshed)
    event(db, request, task, 'PUBLISH_CANDIDATE_ARCHITECTURE', body.note,
          version_id=candidate_version.id, version_fingerprint=candidate_version.fingerprint,
          validation_fingerprint=refreshed['fingerprint'])
    db.commit()


def final_approve(db, request, task, body):
    source(db, request, task); expected(task, body.expected_revision)
    identity = request.state.identity
    if identity['kind'] != 'HUMAN' or 'SECURITY_ADMIN' not in identity['permissions']:
        raise HTTPException(403, 'Final transformation approval requires a human security administrator with source access.')
    if task.state != 'VALIDATION_BLOCKED' or any(b.state == 'RUNNING' for b in builds(db, task)):
        raise HTTPException(409, 'Task is not ready for final review.')
    approval = task.document.get('final_approval')
    if approval: raise HTTPException(409, 'Final approval is immutable; changed evidence requires a new task.')
    item = change(db, task, task.document.get('staged_changeset', ''))
    record = task.document.get('candidate_architecture') or {}
    reanalysis = task.document.get('architecture_reanalysis') or {}
    candidate_version = db.get(ArchitectureVersion, record.get('version_id', ''))
    if (not candidate_version or candidate_version.parent_id != task.version_id or
            candidate_version.analysis_id != reanalysis.get('analysis_id') or
            record.get('build_id') != (next((b.id for b in reversed(builds(db, task)) if b.kind == 'CANDIDATE'), None)) or
            record.get('changeset_fingerprint') != item.fingerprint or
            record.get('artifact_sha256') != reanalysis.get('artifact_sha256') or
            record.get('version_fingerprint') != candidate_version.fingerprint):
        raise HTTPException(409, 'Published candidate version is missing or no longer matches the task evidence.')
    latest = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == candidate_version.application_id)
        .order_by(ArchitectureVersion.created_at.desc(), ArchitectureVersion.id.desc()).limit(1))
    if not latest or latest.id != candidate_version.id:
        raise HTTPException(409, 'A newer architecture version exists; this approval is stale.')
    workspace.checked(request.app.state.config, task)
    result = validation.evaluate(task, builds(db, task), contracts(db, task), item)
    stored = task.document.get('validation') or {}
    if stored.get('fingerprint') != digest(result) or result.get('state') != 'READY_FOR_FINAL_APPROVAL' or not result.get('approval_eligible'):
        raise HTTPException(409, dict(message='Final approval is blocked by missing, stale or failed validation evidence.', gates=result['gates']))
    reviewers = {task.actor_id, item.actor_id}
    if item.approval: reviewers.add(item.approval.get('actor'))
    impact_review = task.document.get('expected_impact_review') or {}
    if impact_review.get('actor'): reviewers.add(impact_review['actor'])
    if identity['id'] in reviewers:
        raise HTTPException(403, 'Final approval must come from a different human than the task author and prior reviewers.')
    record_data = dict(actor=identity['id'], at=now().isoformat(), note=body.note,
        changeset_fingerprint=item.fingerprint, candidate_version_id=candidate_version.id,
        candidate_version_fingerprint=candidate_version.fingerprint,
        validation_fingerprint=stored['fingerprint'], gate_fingerprints=dict(
            architecture=result['architecture_fingerprint'], security=result['security_fingerprint'],
            expected_improvement=impact_review.get('impact_fingerprint')))
    task.document = dict(task.document, final_approval=record_data)
    task.state = 'APPROVED'
    event(db, request, task, 'FINAL_APPROVAL', body.note, **{k:v for k,v in record_data.items() if k not in ('actor','at','note')})
    audit(db, task.tenant_id, identity['id'], 'TRANSFORMATION_FINAL_APPROVAL', 'ALLOW',
        resource='transformation_task:' + task.id, details={k:v for k,v in record_data.items() if k not in ('actor','at','note')})
    db.commit()


def recover(sessions):
    with sessions() as db:
        for task in db.scalars(select(TransformationTask).where(TransformationTask.state.in_(['PREPARING','BUILDING','STAGING','GENERATING']))):
            task.state = 'FAILED'; task.revision += 1
            if task.document.get('microservice_generation_request'):
                task.document=dict(task.document,microservice_generation_request=dict(
                    task.document['microservice_generation_request'],state='FAILED',error_code='INTERRUPTED'))
            task.history = [*task.history, dict(revision=task.revision, at=now().isoformat(), actor='system', action='RECOVER', state='FAILED', note='Interrupted operation; inspect before retry. No automatic execution.')]
        for run in db.scalars(select(BuildRun).where(BuildRun.state == 'RUNNING')):
            run.state = 'FAILED'; run.document = dict(run.document, error_code='INTERRUPTED')
        db.commit()
