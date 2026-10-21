import copy
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
import pytest
from app.transformation import workspace, sandbox, service
from app.transformation.models import TransformationTask, BuildRun
from test_runtime import live
from test_evidence import make
from test_modernization import plan, url
from test_security import account, login


def enable(client, **changes):
    policy=client.get('/api/v1/security/policy').json();revision=policy.pop('revision')
    response=client.post('/api/v1/security/policy',json=dict(policy,expected_revision=revision,**changes))
    assert response.status_code==200,response.text


@pytest.fixture
def prepared(live):
    return prepare(live)


def prepare(live,extra_files=None):
    enable(live,transformation_enabled=True,build_execution_enabled=True)
    root=live.app.state.config.data_dir/'source-repositories'/'task-fixture';root.mkdir(parents=True)
    files={'pom.xml':'<project/>\n','src/App.java':'class App { int value() { return 1; } }\n','src/AppTest.java':'class AppTest { void contract() {} }\n'}
    files.update(extra_files or {})
    for name,content in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
    def git(*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True).stdout.decode().strip()
    git('init');git('add','.');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','baseline')
    commit=git('rev-parse','HEAD');original_status=git('status','--porcelain')
    registered=live.post('/api/v1/security/repositories',json=dict(application_id=live.app_id,name='Task source',path=str(root),commit=commit))
    assert registered.status_code==201,registered.text
    rid=registered.json()['id'];owner=live.get('/api/v1/security/me').json()['id']
    grant=live.post('/api/v1/security/grants',json=dict(principal_id=owner,repository_id=rid,allowed_paths=['pom.xml','src/'],protected_paths=[]));assert grant.status_code==200
    v=make(live);p=plan(live,v)
    reviewed=live.post(url(v)+'/'+p['id']+'/review',json=dict(state='APPROVED_PLANNING',note='Review bounded preparation workflow only',expected_revision=0));assert reviewed.status_code==200
    body=dict(assessment_id=p['id'],decision_id=p['document']['decisions'][0]['id'],repository_id=rid,commit=commit,objective='Review a bounded Java change',expected_change='Preserve the observable return value',files=sorted(files),allowed_files=['src/App.java','src/AppTest.java','src/New.java'],artifact_path='target/application.jar')
    response=live.post('/api/v1/architecture-versions/'+v['id']+'/tasks',json=body)
    assert response.status_code==201,response.text
    return dict(client=live,task=response.json(),version=v,plan=p,body=body,root=root,files=files,git=git,owner=owner,repository=rid,status=original_status)


def base(data):return '/api/v1/transformation/tasks/'+data['task']['id']
def refresh(data):data['task']=data['client'].get(base(data)).json();return data['task']
def revision(data,note='Review the exact bounded operation'):return dict(expected_revision=refresh(data)['revision'],note=note)


def proposed(data,path='src/App.java',content='class App { int value() { return 2; } }\n'):
    t=refresh(data)
    r=data['client'].post(base(data)+'/changesets',json=dict(**revision(data),edits=[dict(path=path,operation='MODIFY',expected_sha256=t['document']['workspace']['current'][path],content=content)]))
    assert r.status_code==201,r.text
    return r.json()


def test_isolation_dirty_original_and_rollback(prepared):
    d=prepared;c=d['client'];original=d['root']/'src/App.java'
    original.write_text('uncommitted customer work',encoding='utf-8')
    change=proposed(d)
    patch=c.get(base(d)+'/changesets/'+change['id']);assert patch.status_code==200 and '+class App' in patch.json()['diff']
    review=c.post(base(d)+'/changesets/'+change['id']+'/review',json=dict(**revision(d),action='APPROVE_STAGING',fingerprint=change['fingerprint']));assert review.status_code==200,review.text
    stage=c.post(base(d)+'/changesets/'+change['id']+'/stage',json=revision(d));assert stage.status_code==200,stage.text
    assert stage.json()['state']=='STAGED' and original.read_text()=='uncommitted customer work'
    assert d['git']('rev-parse','HEAD')==d['body']['commit']
    response=c.post(base(d)+'/actions',json=dict(**revision(d),action='ROLLBACK'));assert response.status_code==200,response.text
    assert response.json()['state']=='ROLLED_BACK'
    assert response.json()['document']['workspace']['current']==response.json()['document']['workspace']['baseline']
    assert original.read_text()=='uncommitted customer work'


def test_scope_secrets_stale_patch_and_no_merge_endpoint(prepared):
    d=prepared;c=d['client'];t=refresh(d)
    edit=dict(path='outside.java',operation='ADD',content='class Outside {}')
    assert c.post(base(d)+'/changesets',json=dict(**revision(d),edits=[edit])).status_code==403
    edit=dict(path='src/App.java',operation='MODIFY',expected_sha256='0'*64,content='class App {}')
    assert c.post(base(d)+'/changesets',json=dict(**revision(d),edits=[edit])).status_code==409
    edit['expected_sha256']=t['document']['workspace']['current']['src/App.java'];edit['content']='String password = "sensitive-test-value";'
    assert c.post(base(d)+'/changesets',json=dict(**revision(d),edits=[edit])).status_code==422
    assert c.post(base(d)+'/merge',json={}).status_code==405 or c.post(base(d)+'/merge',json={}).status_code==404


def test_supervised_progress_board_reports_blockers_and_human_next_action(prepared):
    d=prepared;c=d['client'];version=d['version']['id']
    response=c.get('/api/v1/architecture-versions/'+version+'/tasks')
    assert response.status_code==200,response.text
    item=next(row for row in response.json() if row['id']==d['task']['id'])
    assert item['state']=='PLANNED'
    assert item['blockers']>0
    assert item['validation_state'] is None
    assert 'Resolve' in item['next_action']
    assert c.get('/api/v1/architecture-versions/not-a-version/tasks').status_code==404


def test_extraction_plan_is_version_bound_read_only_preview(prepared):
    d=prepared;c=d['client'];before=refresh(d);body=revision(d,'Review a bounded extraction boundary')
    response=c.post(base(d)+'/extraction-plan',json=body)
    assert response.status_code==200,response.text
    plan=response.json()['document']['extraction_plan']
    assert plan['state']=='PREVIEW_ONLY' and plan['execution_eligible'] is False
    assert plan['freshness']=='CURRENT'
    assert plan['inputs']['version_id']==d['version']['id']
    assert 'DATA_OWNERSHIP_REVIEW_REQUIRED' in plan['blockers']
    assert response.json()['changesets']==[]
    assert response.json()['revision']==before['revision']+1
    added=c.post(base(d)+'/contracts',json=dict(name='Extraction behavior',test_file='src/AppTest.java',test_case='AppTest#contract',scenario='Invoke the selected sample operation',expected_behavior='Preserve the pinned baseline result',critical=True))
    assert added.status_code==201,added.text
    assert c.get(base(d)).json()['document']['extraction_plan']['freshness']=='STALE'
    stale=c.post(base(d)+'/extraction-plan',json=body)
    assert stale.status_code==409


def test_discovery_generated_plan_independent_review_and_synthetic_migration(live):
    schema='''CREATE TABLE customers (\n id BIGINT PRIMARY KEY,\n name VARCHAR(120) NOT NULL\n);\n'''
    d=prepare(live,{'src/main/resources/db/migration/V1__customers.sql':schema})
    c=d['client'];task_url=base(d)
    discovery=c.post(task_url+'/data-discovery',json=revision(d,'Discover schema and access evidence'))
    assert discovery.status_code==200,discovery.text
    report=discovery.json()['report']
    assert report['entities'][0]['name']=='customers'
    assert report['entities'][0]['evidence'][0]['path']=='src/main/resources/db/migration/V1__customers.sql'
    assert report['ownership_map'][0]['state'] in ('INFERRED','UNRESOLVED')
    proposal=c.post(task_url+'/data-migration-proposals',json=dict(**revision(d,'Generate a source grounded schema proposal'),target_engine='SQLITE_TEST'))
    assert proposal.status_code==200,proposal.text
    plan=proposal.json()
    assert plan['plan']['target_schema'] and plan['plan']['bindings']['repository_commit']==d['body']['commit']
    assert plan['plan']['bindings']['mapping_version']==1

    reviewer=account(c,'migration-reviewer',['ANALYSIS_READ','ANALYSIS_WRITE','SOURCE_READ','SECURITY_ADMIN'])
    grant=c.post('/api/v1/security/grants',json=dict(principal_id=reviewer['id'],repository_id=d['repository'],allowed_paths=['pom.xml','src/'],protected_paths=[]))
    assert grant.status_code==200,grant.text
    review_client=login(c,'migration-reviewer')
    ownership=[dict(resource=row['resource'],owner_domain_id='SHARED',rationale='Ownership remains shared pending customer confirmation') for row in report['ownership_map']]
    review=review_client.post(task_url+'/'+ 'data-migration-proposals/'+plan['id']+'/review',json=dict(
        **revision(d,'Approve isolated synthetic migration testing'),plan_id=plan['id'],fingerprint=plan['fingerprint'],
        action='APPROVE_FOR_TEST',ownership_decisions=ownership,acknowledged_risks=[]))
    assert review.status_code==200,review.text
    assert review.json()['state']=='APPROVED_FOR_TEST'
    approved=review.json()
    assert approved['fingerprint']==approved['plan']['fingerprint']
    assert approved['review']['proposal_fingerprint']==plan['fingerprint']
    assert approved['review']['fingerprint']==approved['fingerprint']
    run=review_client.post(task_url+'/data-migration-proposals/'+plan['id']+'/synthetic-test',json=dict(
        expected_revision=approved['task']['revision'],note='Run isolated synthetic fixture validation',plan_id=plan['id'],
        data_classification='SYNTHETIC',rows={'customers':[{'id':1,'name':'synthetic customer'}]}))
    assert run.status_code==200,run.text
    result=run.json()['result']
    assert result['state']=='PASS' and result['raw_fixture_persisted'] is False
    assert result['environment']=='EPHEMERAL_SQLITE_MEMORY'
    assert result['checks'] and all(check['status']=='PASS' for check in result['checks'])
    replacement=c.post(task_url+'/data-migration-proposals',json=dict(**revision(d,'Create a new mapping proposal revision'),target_engine='SQLITE_TEST'))
    assert replacement.status_code==200,replacement.text
    stale_run=review_client.post(task_url+'/data-migration-proposals/'+plan['id']+'/synthetic-test',json=dict(
        expected_revision=refresh(d)['revision'],note='Reject a superseded plan execution attempt',plan_id=plan['id'],
        data_classification='SYNTHETIC',rows={'customers':[{'id':2,'name':'synthetic customer'}]}))
    assert stale_run.status_code==409
def test_data_migration_plan_is_reviewed_version_bound_preview_only(prepared):
    d=prepared;c=d['client'];base_url=base(d)
    payload=dict(**revision(d,'Preview the explicit local migration proposal'),
        source=dict(system='legacy-db',schema_name='public',resource='customer'),
        target=dict(system='target-db',schema_name='modern',resource='customer'),
        mappings=[dict(source_column='customer_id',target_column='id',conversion='IDENTITY',key=True),
                  dict(source_column='full_name',target_column='name',conversion='STRING',key=False)],
        invariants=[dict(name='row-count',description='Preserve all eligible source customer rows',expected='source count equals target count')],
        conflict_policy='ABORT_ON_CONFLICT',
        recovery=dict(backup_id='backup-before-cutover',restore_tested=True,rollback_strategy='Restore the verified snapshot and route reads to the source database.'),
        ownership_statement='The customer domain owns the source customer records and will own the target table.',
        ownership_evidence=['review://architecture/customer-domain-ownership'])
    response=c.post(base_url+'/data-migration-plan',json=payload)
    assert response.status_code==200,response.text
    plan=response.json()['data_migration_plan']
    assert plan['state']=='PREVIEW_ONLY' and plan['execution_eligible'] is False
    assert plan['freshness']=='CURRENT' and plan['version_id']==d['version']['id']
    assert 'REVIEWED_DATA_OWNERSHIP_REQUIRED' in plan['blockers']
    assert 'DATABASE_EVIDENCE_UNAVAILABLE' in plan['blockers']
    assert response.json()['changesets']==[]
    assert response.json()['revision']==payload['expected_revision']+1

    reviewer=account(c,'data-reviewer',['ANALYSIS_READ','ANALYSIS_WRITE','SOURCE_READ','SECURITY_ADMIN'])
    grant=c.post('/api/v1/security/grants',json=dict(principal_id=reviewer['id'],repository_id=d['repository'],allowed_paths=['pom.xml','src/'],protected_paths=[]))
    assert grant.status_code==200,grant.text
    r=login(c,'data-reviewer')
    review=r.post(base_url+'/data-migration-plan/review',json=dict(expected_revision=response.json()['revision'],note='Review domain ownership evidence only',fingerprint=plan['fingerprint'],action='APPROVE_PLAN'))
    assert review.status_code==200,review.text
    reviewed=review.json()['task']['data_migration_plan']
    assert reviewed['ownership_review']['state']=='ACCEPTED'
    assert 'REVIEWED_DATA_OWNERSHIP_REQUIRED' not in reviewed['blockers']
    assert 'DATABASE_EVIDENCE_UNAVAILABLE' in reviewed['blockers']
    assert reviewed['execution_eligible'] is False
    assert reviewed['freshness']=='CURRENT'

    # A new mapping cannot inherit the old review: its plan fingerprint is stale.
    changed={**payload,'expected_revision':review.json()['task']['revision'],'note':'Change the mapping proposal materially'}
    changed['mappings']=[*payload['mappings'],dict(source_column='email',target_column='email',conversion='STRING',key=False)]
    replacement=c.post(base_url+'/data-migration-plan',json=changed)
    assert replacement.status_code==200,replacement.text
    assert replacement.json()['data_migration_plan']['blockers']
    assert replacement.json()['data_migration_plan']['freshness']=='CURRENT'


def test_high_risk_requires_distinct_authorized_human(prepared):
    d=prepared;c=d['client'];change=proposed(d,'src/AppTest.java','class AppTest { void changed() {} }\n')
    assert change['risk']=='HIGH'
    body=dict(**revision(d),action='APPROVE_STAGING',fingerprint=change['fingerprint'])
    assert c.post(base(d)+'/changesets/'+change['id']+'/review',json=body).status_code==403
    reviewer=account(c,'reviewer',['ANALYSIS_READ','ANALYSIS_WRITE','SOURCE_READ','SECURITY_ADMIN'])
    c.post('/api/v1/security/grants',json=dict(principal_id=reviewer['id'],repository_id=d['repository'],allowed_paths=['pom.xml','src/'],protected_paths=[]))
    r=login(c,'reviewer');response=r.post(base(d)+'/changesets/'+change['id']+'/review',json=body)
    assert response.status_code==200,response.text
    assert response.json()['changesets'][0]['state']=='APPROVED_FOR_STAGING'


def test_policy_revision_invalidates_staging_approval(prepared):
    d=prepared;c=d['client'];change=proposed(d)
    assert c.post(base(d)+'/changesets/'+change['id']+'/review',json=dict(**revision(d),action='APPROVE_STAGING',fingerprint=change['fingerprint'])).status_code==200
    policy=c.get('/api/v1/security/policy').json();revision_number=policy.pop('revision')
    assert c.post('/api/v1/security/policy',json=dict(policy,expected_revision=revision_number)).status_code==200
    assert c.post(base(d)+'/changesets/'+change['id']+'/stage',json=revision(d)).status_code==409


def test_contracts_baseline_artifact_binding_and_ready_gate(prepared,monkeypatch):
    d=prepared;c=d['client']
    contract=c.post(base(d)+'/contracts',json=dict(name='Return contract',test_file='src/AppTest.java',test_case='AppTest#contract',scenario='Invoke the selected sample method',expected_behavior='Return the documented baseline value',critical=True))
    assert contract.status_code==201,contract.text
    cid=contract.json()['contracts'][0]['id']
    assert c.post(base(d)+'/contracts/'+cid+'/review',json=revision(d)).status_code==200
    fake=dict(tests=1,skipped=0,failures=0,errors=0,cases=[dict(name='AppTest#contract',passed=True)],artifact_sha256='1'*64)
    monkeypatch.setattr(sandbox,'run',lambda *args:copy.deepcopy(fake))
    r=c.post(base(d)+'/builds/BASELINE',json=revision(d));assert r.status_code==200,r.text
    assert r.json()['builds'][-1]['error_code']=='BASELINE_ARTIFACT_MISMATCH'
    assert r.json()['state']=='PLANNED'
    fake['artifact_sha256']='0'*64
    r=c.post(base(d)+'/builds/BASELINE',json=revision(d));assert r.status_code==200,r.text
    assert r.json()['builds'][-1]['state']=='PASSED'
    assert r.json()['state']=='READY' and r.json()['gaps']==[]
    assert not r.json()['execution']['merge_enabled']


def test_missing_sandbox_fails_closed_without_host_build(prepared,monkeypatch):
    d=prepared;c=d['client']
    monkeypatch.setattr(sandbox,'binary',lambda:None)
    r=c.get('/api/v1/transformation/capabilities');assert r.json()['sandbox']['available'] is False
    r=c.post(base(d)+'/builds/BASELINE',json=revision(d));assert r.status_code==200,r.text
    assert r.json()['builds'][-1]['state']=='FAILED'
    assert r.json()['builds'][-1]['error_code']=='SANDBOX_UNAVAILABLE'
    assert r.json()['state']=='PLANNED'


def test_pause_revisions_and_out_of_band_tamper(prepared):
    d=prepared;c=d['client'];body=dict(**revision(d),action='PAUSE')
    assert c.post(base(d)+'/actions',json=body).json()['state']=='PAUSED'
    assert c.post(base(d)+'/actions',json=body).status_code==409
    assert c.post(base(d)+'/actions',json=dict(**revision(d),action='RESUME')).json()['state']=='PLANNED'
    with c.app.state.sessions() as db:
        t=db.get(TransformationTask,d['task']['id']);p=workspace.root(c.app.state.config,t)/'worktree/src/App.java';p.write_text('unexpected user edit',encoding='utf-8')
    r=c.post(base(d)+'/actions',json=dict(**revision(d),action='ROLLBACK'));assert r.status_code==409
    assert p.read_text()=='unexpected user edit'


def test_cross_tenant_revoked_source_and_current_plan_gates(prepared):
    d=prepared;c=d['client'];account(c,permissions=['ANALYSIS_READ','ANALYSIS_WRITE']);reader=login(c)
    assert reader.get(base(d)).status_code==403
    c.post('/api/v1/security/workspaces',json=dict(name='Other',admin_username='other-owner',admin_password='other-owner-password'))
    other=login(c,'other-owner','other-owner-password');assert other.get(base(d)).status_code==404
    make(c,parent_id=d['version']['id'])
    r=c.post(base(d)+'/actions',json=dict(**revision(d),action='RECHECK'));assert r.status_code==409


def test_interrupted_build_recovery_preserves_workspace(prepared):
    d=prepared;c=d['client']
    with c.app.state.sessions() as db:
        t=db.get(TransformationTask,d['task']['id']);t.state='BUILDING'
        job=BuildRun(tenant_id=t.tenant_id,task_id=t.id,actor_id=t.actor_id,kind='BASELINE',state='RUNNING',document={});db.add(job);db.commit();jid=job.id
    service.recover(c.app.state.sessions)
    assert refresh(d)['state']=='FAILED'
    with c.app.state.sessions() as db:assert db.get(BuildRun,jid).document['error_code']=='INTERRUPTED'


def test_idempotent_task_creation(prepared):
    d=prepared
    response=d['client'].post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=d['body'])
    assert response.status_code==201 and response.json()['id']==d['task']['id']


def test_candidate_service_task_binds_to_reviewed_version_and_decision(prepared):
    d=prepared;decision=d['plan']['document']['decisions'][0]
    candidate=next(c for c in d['plan']['document']['microservice_decomposition']['service_candidates']
                   if c['id']==decision['domain_id'])
    body=dict(d['body'],service_candidate_id=candidate['id'],rollout_mode='ONE_BY_ONE')
    response=d['client'].post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=body)
    assert response.status_code==201,response.text
    binding=response.json()['document']['microservice']
    assert binding['candidate_id']==candidate['id']
    assert binding['proposal_fingerprint']==d['plan']['fingerprint']
    assert binding['source_version_fingerprint']==d['version']['fingerprint']
    assert binding['state']=='SOURCE_TASK_SETUP_REQUIRED'
    invalid=dict(body,service_candidate_id='not-a-candidate')
    assert d['client'].post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=invalid).status_code==422
    whole_system=dict(body,request_key='whole-system-is-not-ready',rollout_mode='WHOLE_SYSTEM')
    assert d['client'].post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=whole_system).status_code==422


def test_gemini_service_generation_fails_closed_until_secret_is_configured(prepared):
    from pydantic import SecretStr
    d=prepared;decision=d['plan']['document']['decisions'][0]
    candidate=next(c for c in d['plan']['document']['microservice_decomposition']['service_candidates']
                   if c['id']==decision['domain_id'])
    body=dict(d['body'],service_candidate_id=candidate['id'],rollout_mode='ONE_BY_ONE',request_key='gemini-no-secret')
    made=d['client'].post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=body)
    assert made.status_code==201,made.text
    policy=d['client'].get('/api/v1/security/policy').json();revision=policy.pop('revision')
    allowed=d['client'].post('/api/v1/security/policy',json=dict(policy,expected_revision=revision,gemini_source_transfer_enabled=True))
    assert allowed.status_code==200,allowed.text
    d['client'].app.state.config.gemini_api_key=SecretStr('')
    task=made.json();base='/api/v1/transformation/tasks/'+task['id']
    response=d['client'].post(base+'/microservice/generate',json=dict(expected_revision=task['revision'],confirm_source_transfer=True,
        acknowledgement='I_APPROVE_SENDING_SELECTED_SOURCE_TO_GOOGLE_GEMINI'))
    assert response.status_code==503,response.text
    assert d['client'].get(base).json()['document'].get('microservice_generation') is None


def test_interrupted_gemini_generation_is_marked_failed(prepared):
    d=prepared
    with d['client'].app.state.sessions() as db:
        task=db.get(TransformationTask,d['task']['id'])
        task.state='GENERATING'
        task.document=dict(task.document,microservice_generation_request=dict(invocation_id='test-invocation',state='REQUESTED'))
        db.commit()
    service.recover(d['client'].app.state.sessions)
    task=refresh(d)
    assert task['state']=='FAILED'
    assert task['document']['microservice_generation_request']['error_code']=='INTERRUPTED'


def test_bounded_ast_recipe_produces_reviewable_changeset(prepared, monkeypatch):
    d=prepared;c=d['client'];task=refresh(d)
    generated=dict(recipe='INTRODUCE_INTERFACE',recipe_version='1.0.0',parser='JavaParser',parser_version='3.28.2',
        image_id='sha256:'+'f'*64,implementation_file='src/App.java',interface_file='src/New.java',methods=['value'],
        contents=['class App implements New { public int value() { return 1; } }\n',
                  'public interface New { public int value(); }\n'])
    monkeypatch.setattr(sandbox,'refactor',lambda *args:copy.deepcopy(generated))
    response=c.post(base(d)+'/recipes',json=dict(**revision(d),recipe='INTRODUCE_INTERFACE',implementation_file='src/App.java',
        interface_file='src/New.java',interface_name='New',methods=['value']))
    assert response.status_code==201,response.text
    change=response.json();assert change['generation']['parser']=='JavaParser'
    patch=c.get(base(d)+'/changesets/'+change['id']).json()['diff']
    assert 'implements New' in patch and 'interface New' in patch
    assert c.post(base(d)+'/recipes',json=dict(**revision(d),recipe='INTRODUCE_INTERFACE',implementation_file='src/App.java',
        interface_file='outside/Boundary.java',interface_name='Boundary',methods=['value'])).status_code==403


def test_ast_recipe_failures_do_not_create_changesets(prepared, monkeypatch):
    d=prepared;c=d['client'];monkeypatch.setattr(sandbox,'refactor',lambda *args:(_ for _ in ()).throw(sandbox.SandboxError('JAVA_PARSE_FAILED')))
    before=len(refresh(d)['changesets'])
    response=c.post(base(d)+'/recipes',json=dict(**revision(d),recipe='INTRODUCE_INTERFACE',implementation_file='src/App.java',
        interface_file='src/New.java',interface_name='New',methods=['value']))
    assert response.status_code==409 and response.json()['detail']=='JAVA_PARSE_FAILED'
    assert len(refresh(d)['changesets'])==before


def test_recipe_rejects_type_filename_mismatch_before_execution(prepared, monkeypatch):
    d=prepared
    def unexpected(*args): raise AssertionError('Invalid recipe must not start Docker')
    monkeypatch.setattr(sandbox,'refactor',unexpected)
    response=d['client'].post(base(d)+'/recipes',json=dict(**revision(d),recipe='INTRODUCE_INTERFACE',
        implementation_file='src/App.java',interface_file='src/New.java',interface_name='Boundary',methods=['value']))
    assert response.status_code==422
    assert not refresh(d)['changesets']


def test_paused_build_cannot_resume_or_rollback_until_finished(prepared):
    d=prepared;c=d['client']
    with c.app.state.sessions() as db:
        task=db.get(TransformationTask,d['task']['id']);task.state='BUILDING'
        db.add(BuildRun(tenant_id=task.tenant_id,task_id=task.id,actor_id=task.actor_id,kind='BASELINE',state='RUNNING',document={}))
        db.commit()
    assert c.post(base(d)+'/actions',json=dict(**revision(d),action='PAUSE')).status_code==200
    for action in ('RESUME','ROLLBACK','RECHECK'):
        assert c.post(base(d)+'/actions',json=dict(**revision(d),action=action)).status_code==409


@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_POSTGRES_TESTS')!='1',reason='Requires local PostgreSQL')
def test_postgres_task_restart_preserves_patch_and_rollback(tmp_path):
    from uuid import uuid4
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from fastapi.testclient import TestClient
    from app.config import Settings,ROOT
    from app.main import create_app
    from app.db.session import build_engine
    from app.models import Project,Application,Artifact,AnalysisRun,now
    from test_runtime import baseline
    from security_helpers import sign_in_owner
    host=Settings();engine=build_engine(host);schema='phase6_validation_'+uuid4().hex
    with engine.begin() as db:db.execute(text('CREATE SCHEMA '+schema))
    url=make_url(host.database_url).update_query_dict({'options':'-csearch_path='+schema})
    config=Settings(_env_file=None,database_url=url.render_as_string(hide_password=False),data_dir=tmp_path,allowed_hosts=['testserver'])
    try:
        with TestClient(create_app(config)) as c:
            sign_in_owner(c)
            with c.app.state.sessions() as db:
                project=Project(name='Isolated source validation');db.add(project);db.flush()
                app=Application(project_id=project.id,name='Controlled fixture');db.add(app);db.flush()
                artifact=Artifact(application_id=app.id,filename='fixture.jar',path='unused fixture',sha256='0'*64,size=1);db.add(artifact);db.flush()
                run=AnalysisRun(application_id=app.id,artifact_id=artifact.id,status='COMPLETED',result=baseline());db.add(run);db.commit();c.app_id=app.id;c.run_id=run.id
            d=prepare(c);original=d['root']/'src/App.java';original.write_text('customer uncommitted change',encoding='utf-8')
            change=proposed(d)
            assert c.post(base(d)+'/changesets/'+change['id']+'/review',json=dict(**revision(d),action='APPROVE_STAGING',fingerprint=change['fingerprint'])).status_code==200
            assert c.post(base(d)+'/changesets/'+change['id']+'/stage',json=revision(d)).status_code==200
            frozen=refresh(d)
        with TestClient(create_app(config)) as c:
            c.headers['X-ArchIntel-Request']='1'
            session=c.post('/api/v1/security/login',json=dict(username='test-owner',password='test-owner-password-2026'))
            assert session.status_code==200
            c.headers['X-CSRF-Token']=session.json()['csrf_token']
            d['client']=c;assert refresh(d)==frozen
            assert c.post(base(d)+'/actions',json=dict(**revision(d),action='ROLLBACK')).status_code==200
            assert refresh(d)['document']['workspace']['current']==frozen['document']['workspace']['baseline']
            assert original.read_text()=='customer uncommitted change'
            assert d['git']('rev-parse','HEAD')==d['body']['commit']
        (ROOT/'docs/phase6-integration-validation.json').write_text(json.dumps(dict(verified_at=now().isoformat(),fixture='Controlled Java source fixture; no real container build',database='Isolated PostgreSQL schema',restart_task_unchanged=True,reviewed_patch_preserved=True,rollback_restored_baseline=True,original_dirty_checkout_unchanged=True,original_commit_unchanged=True),indent=2),encoding='utf-8')
    finally:
        with engine.begin() as db:db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        engine.dispose()


def test_interrupted_staging_recovers_only_reviewed_bytes(prepared,monkeypatch):
    d=prepared;c=d['client'];change=proposed(d)
    assert c.post(base(d)+'/changesets/'+change['id']+'/review',json=dict(**revision(d),action='APPROVE_STAGING',fingerprint=change['fingerprint'])).status_code==200
    def interrupted(config,task,edits):
        path=workspace.root(config,task)/'worktree'/edits[0]['path']
        path.write_bytes(edits[0]['content'].encode())
        raise ValueError('Interrupted after a known write')
    monkeypatch.setattr(workspace,'apply',interrupted)
    assert c.post(base(d)+'/changesets/'+change['id']+'/stage',json=revision(d)).status_code==409
    service.recover(c.app.state.sessions)
    response=c.post(base(d)+'/actions',json=dict(**revision(d),action='ROLLBACK'))
    assert response.status_code==200,response.text
    assert response.json()['document']['workspace']['current']==response.json()['document']['workspace']['baseline']


@pytest.mark.parametrize('path',['../escape','src/CON.java','src/a.java/','.git/config','.gitattributes','src/.env','src/x.'])
def test_unsafe_workspace_paths(path):
    with pytest.raises(ValueError):workspace.relative(path)


def test_sandbox_command_is_local_nonroot_offline_and_bounded(tmp_path):
    args=sandbox.run_args('archintel-build-fixture',tmp_path,'sha256:'+'a'*64)
    for flag in ('--network=none','--read-only','--user=1000:1000','--pull=never','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=256','--memory=1024m','--cpus=2'):assert flag in args
    assert 'readonly' in args[args.index('--mount')+1]
    assert '/var/run/docker.sock' not in ' '.join(args)


def test_sandbox_uses_baked_readonly_maven_cache_without_copying_it(monkeypatch, tmp_path):
    from types import SimpleNamespace as Row
    from app.config import Settings
    calls = []
    monkeypatch.setattr(sandbox, 'capabilities', lambda *_: {'available': True})
    monkeypatch.setattr(sandbox, 'call', lambda args, **kwargs: calls.append(args) or b'')
    monkeypatch.setattr(sandbox, 'reports', lambda _: dict(tests=1, skipped=0, failures=0, errors=0, cases=[]))
    task = Row(document={'artifact_path': 'target/app.jar'})

    sandbox.run(Settings(_env_file=None), task, 'test', tmp_path)

    build_command = calls[1][4]
    assert 'mvn -o -B -Dmaven.repo.local=/opt/m2/repository' in build_command
    assert 'cp -R /opt/m2' not in build_command


def test_structured_test_reports_reject_missing_tests_entities_and_links():
    def archive(content):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as tar:
            row=tarfile.TarInfo('TEST.xml');data=content.encode();row.size=len(data);tar.addfile(row,io.BytesIO(data))
        return out.getvalue()
    result=sandbox.reports(archive('<testsuite><testcase classname="AppTest" name="contract"/></testsuite>'))
    assert result['tests']==1 and result['cases'][0]['passed']
    with pytest.raises(sandbox.SandboxError):sandbox.reports(archive('<testsuite/>'))
    with pytest.raises(sandbox.SandboxError):sandbox.reports(archive('<!DOCTYPE x><testsuite/>'))


def test_claude_service_generation_needs_its_own_policy_flag_key_acknowledgement_and_daily_budget(prepared):
    from datetime import timedelta
    from pydantic import SecretStr
    from app.ai.models import ModelInvocation
    from app.models import now
    d=prepared;decision=d['plan']['document']['decisions'][0];client=d['client']
    candidate=next(c for c in d['plan']['document']['microservice_decomposition']['service_candidates'] if c['id']==decision['domain_id'])
    made=client.post('/api/v1/architecture-versions/'+d['version']['id']+'/tasks',json=dict(d['body'],service_candidate_id=candidate['id'],rollout_mode='ONE_BY_ONE',request_key='claude-gates'))
    assert made.status_code==201,made.text
    task=made.json();url='/api/v1/transformation/tasks/'+task['id']+'/microservice/generate'
    claude_body=dict(expected_revision=task['revision'],confirm_source_transfer=True,provider='CLAUDE',acknowledgement='I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE')
    assert client.post(url,json=dict(claude_body,acknowledgement='I_APPROVE_SENDING_SELECTED_SOURCE_TO_GOOGLE_GEMINI')).status_code==422   # must name the receiver
    policy=client.get('/api/v1/security/policy').json();revision=policy.pop('revision')
    assert client.post('/api/v1/security/policy',json=dict(policy,expected_revision=revision,gemini_source_transfer_enabled=True)).status_code==200
    assert client.post(url,json=claude_body).status_code==403                     # Gemini consent does not cover Claude
    policy=client.get('/api/v1/security/policy').json();revision=policy.pop('revision')
    assert client.post('/api/v1/security/policy',json=dict(policy,expected_revision=revision,claude_source_transfer_enabled=True)).status_code==200
    client.app.state.config.anthropic_api_key=SecretStr('')
    assert client.post(url,json=claude_body).status_code==503
    client.app.state.config.anthropic_api_key=SecretStr('sk-test')
    client.app.state.config.claude_max_generations_per_day=2
    with client.app.state.sessions() as db:
        for _ in range(2):
            db.add(ModelInvocation(tenant_id='local',principal_id='p',resource='microservice:x',outcome='ALLOW',reason='r',metadata_json=dict(destination='CLAUDE_EXTERNAL'),created_at=now()-timedelta(hours=1)))
        db.commit()
    blocked=client.post(url,json=claude_body)
    assert blocked.status_code==429 and 'CLAUDE_MAX_GENERATIONS_PER_DAY' in blocked.text
    assert client.get('/api/v1/transformation/tasks/'+task['id']).json()['document'].get('microservice_generation') is None
