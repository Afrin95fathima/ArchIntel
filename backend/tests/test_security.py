import hashlib
import json
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.access.models import Principal, Credential, SourceRepository, PolicyRevision
from app.access.core import digest
from test_foundation import client, new_app


def account(client, name='reader', permissions=None, kind='HUMAN'):
    response = client.post('/api/v1/security/principals', json=dict(username=name, kind=kind,
        password='test-reader-password-2026', permissions=permissions or ['ANALYSIS_READ', 'RUNTIME_READ']))
    assert response.status_code == 201, response.text
    return response.json()


def login(client, name='reader', password='test-reader-password-2026'):
    browser = TestClient(client.app, headers={'X-ArchIntel-Request':'1'})
    response = browser.post('/api/v1/security/login', json={'username':name, 'password':password})
    assert response.status_code == 200, response.text
    browser.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return browser


@pytest.fixture
def source(client):
    application = new_app(client)
    root = client.app.state.config.data_dir/'source-repositories'/'fixture'
    (root/'payment').mkdir(parents=True)
    (root/'customer').mkdir()
    (root/'payment'/'Payment.java').write_text('class Payment { int value() { return 1; } }', encoding='utf-8')
    (root/'customer'/'Customer.java').write_text('class Customer {}', encoding='utf-8')
    def git(*args):
        result = subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True)
        return result.stdout.decode().strip()
    git('init');git('add','.')
    git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
    commit = git('rev-parse','HEAD')
    response = client.post('/api/v1/security/repositories',json=dict(application_id=application,name='Source fixture',path=str(root),commit=commit))
    assert response.status_code == 201,response.text
    repository = response.json()['id']
    user=account(client,permissions=['SOURCE_READ'])
    grant=client.post('/api/v1/security/grants',json=dict(principal_id=user['id'],repository_id=repository,allowed_paths=['payment/'],protected_paths=[]))
    assert grant.status_code==200,grant.text
    return dict(browser=login(client),repository=repository,commit=commit,user=user,root=root,
                body=dict(repository_id=repository,commit=commit,files=['payment/Payment.java'],purpose='Review payment boundary'))


def test_anonymous_management_denied_and_health_public(client):
    anonymous=TestClient(client.app)
    for path in ['/api/v1/projects','/api/v1/analyses','/api/v1/demo/artifact','/api/v1/manual/user','/openapi.json']:
        assert anonymous.get(path).status_code==401,path
    assert anonymous.get('/api/v1/health').status_code==200
    assert anonymous.post('/api/v1/security/login',json={'username':'test-owner','password':'test-owner-password-2026'}).status_code==403
    assert client.post('/api/v1/security/bootstrap',json={'username':'another','password':'another-password-2026','bootstrap_key':'a'*32}).status_code==409


def test_cookie_csrf_logout_and_credential_revocation(client):
    account(client)
    browser=login(client)
    token=browser.cookies.get('archintel_session')
    assert token
    response=browser.post('/api/v1/security/login',json={'username':'reader','password':'test-reader-password-2026'})
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    browser.headers['X-CSRF-Token']=response.json()['csrf_token']
    browser.headers.pop('X-CSRF-Token')
    assert browser.post('/api/v1/security/logout').status_code==403
    me=browser.get('/api/v1/security/me').json()
    browser.headers['X-CSRF-Token']=me['csrf_token']
    old=browser.cookies.get('archintel_session')
    assert browser.post('/api/v1/security/logout').status_code==200
    browser.cookies.set('archintel_session',old)
    assert browser.get('/api/v1/projects').status_code==401


def test_viewer_cannot_write_or_administer(client):
    account(client)
    browser=login(client)
    assert browser.get('/api/v1/projects').status_code==200
    assert browser.post('/api/v1/projects',json={'name':'forbidden'}).status_code==403
    assert browser.get('/api/v1/security/principals').status_code==403
    assert browser.post('/api/v1/runtime/retention/purge').status_code==403
    policy=client.get('/api/v1/security/policy').json();revision=policy.pop('revision')
    assert browser.post('/api/v1/security/policy',json=dict(policy,expected_revision=revision,gemini_source_transfer_enabled=True)).status_code==403


def test_workspace_isolation_including_lists_and_indirect_ids(client):
    app_id=new_app(client)
    response=client.post('/api/v1/security/workspaces',json={'name':'Other','admin_username':'other-owner','admin_password':'other-owner-password'})
    assert response.status_code==201,response.text
    other=login(client,'other-owner','other-owner-password')
    for path in ['/api/v1/projects','/api/v1/applications','/api/v1/analyses']:
        assert other.get(path).json()==[]
    assert other.get('/api/v1/applications/'+app_id).status_code==404
    project=client.get('/api/v1/projects').json()[0]['id']
    assert other.post('/api/v1/applications',json={'name':'leak','project_id':project}).status_code==404
    their_app=new_app(other)
    assert client.get('/api/v1/applications/'+their_app).status_code==404
    assert other.post('/api/v1/security/workspaces',json={'name':'Denied','admin_username':'third-owner','admin_password':'third-owner-password'}).status_code==403
    own_me=client.get('/api/v1/security/me').json()
    assert other.post('/api/v1/security/principals/'+own_me['id']+'/revoke').status_code==404
    assert {event['tenant_id'] for event in other.get('/api/v1/security/audit').json()}=={response.json()['id']}


def test_service_identity_is_scoped_revocable_and_has_no_admin(client):
    user=account(client,kind='SERVICE')
    service=TestClient(client.app,headers={'Authorization':'Bearer '+user['token']})
    assert service.get('/api/v1/projects').status_code==200
    assert service.get('/api/v1/security/principals').status_code==403
    assert client.post('/api/v1/security/principals/'+user['id']+'/revoke').status_code==200
    assert service.get('/api/v1/projects').status_code==401
    with client.app.state.sessions() as db:
        assert db.get(Credential,digest(user['token'])) is None


def test_committed_source_scope_and_audit(source,client):
    # Working tree modifications cannot change pinned context.
    (source['root']/'payment'/'Payment.java').write_text('uncommitted secret',encoding='utf-8')
    response=source['browser'].post('/api/v1/security/context',json=source['body'])
    assert response.status_code==200,response.text
    result=response.json()
    assert 'return 1' in result['files'][0]['content']
    assert result['external_transfer'] is False
    events=client.get('/api/v1/security/audit').json()
    event=next(e for e in events if e['request_id']==result['request_id'] and e['outcome']=='ALLOW')
    assert event['details']['permitted_files']==['payment/Payment.java']
    assert 'return 1' not in json.dumps(events)
    assert client.get('/api/v1/security/audit/verify').json()['valid']


@pytest.mark.parametrize('paths', [['customer/Customer.java'],['../customer/Customer.java'],
    ['payment/Payment.java','customer/Customer.java'],['/etc/passwd'],['.git/config'],['payment/../customer/Customer.java']])
def test_gateway_denies_escape_or_ungranted_context(source,client,paths):
    response=source['browser'].post('/api/v1/security/context',json=dict(source['body'],files=paths))
    assert response.status_code==403,response.text
    events=client.get('/api/v1/security/audit').json()
    assert any(e['action']=='SOURCE_READ' and e['outcome']=='DENY' and e['details'].get('denied_files')==paths for e in events)


def test_gateway_default_deny_external_write_missing_purpose_wrong_commit(source,client):
    for change in [dict(destination='EXTERNAL_MODEL'),dict(operation='SOURCE_WRITE'),dict(commit='a'*40)]:
        assert source['browser'].post('/api/v1/security/context',json=dict(source['body'],**change)).status_code==403
    assert source['browser'].post('/api/v1/security/context',json=dict(source['body'],purpose='')).status_code==422
    # Even the owner has no implicit repository scope grant.
    assert client.post('/api/v1/security/context',json=source['body']).status_code==403
    principal=account(client,'no-source')
    assert login(client,'no-source').post('/api/v1/security/context',json=source['body']).status_code==403


def test_live_policy_revision_disable_protected_scope_and_limits(source,client):
    policy=client.get('/api/v1/security/policy').json()
    old=policy.pop('revision')
    response=client.post('/api/v1/security/policy',json=dict(policy,expected_revision=old,protected_paths=['payment/']))
    assert response.status_code==200,response.text
    assert source['browser'].post('/api/v1/security/context',json=source['body']).status_code==403
    assert client.post('/api/v1/security/policy',json=dict(policy,expected_revision=old)).status_code==409
    response=client.post('/api/v1/security/policy',json=dict(policy,expected_revision=old+1,max_bytes=1))
    assert response.status_code==200
    assert source['browser'].post('/api/v1/security/context',json=source['body']).status_code==403
    assert client.post('/api/v1/security/policy',json=dict(policy,expected_revision=old+2,source_read_enabled=False)).status_code==200
    assert source['browser'].post('/api/v1/security/context',json=source['body']).status_code==403


def test_gateway_cross_workspace_repository_and_grant_denied(source,client):
    client.post('/api/v1/security/workspaces',json={'name':'Other','admin_username':'other-owner','admin_password':'other-owner-password'})
    other=login(client,'other-owner','other-owner-password')
    assert other.post('/api/v1/security/context',json=source['body']).status_code==403
    assert other.post('/api/v1/security/grants',json=dict(principal_id=source['user']['id'],repository_id=source['repository'],allowed_paths=['payment/'],protected_paths=[])).status_code==404


def test_audit_failure_releases_no_source(source,monkeypatch):
    def fail(*args,**kwargs):raise RuntimeError('Audit unavailable')
    monkeypatch.setattr('app.access.gateway.record',fail)
    response=source['browser'].post('/api/v1/security/context',json=source['body'])
    assert response.status_code==503
    assert 'return 1' not in response.text


def test_audit_database_rejects_update_and_delete(client):
    for sql in ['UPDATE security_audit_events SET event_hash = \'changed\'','DELETE FROM security_audit_events']:
        with pytest.raises(DBAPIError),client.app.state.engine.begin() as connection:
            connection.execute(text(sql))
    assert client.get('/api/v1/security/audit/verify').json()['valid']


def test_operator_root_enforced(client,tmp_path):
    app=new_app(client)
    response=client.post('/api/v1/security/repositories',json=dict(application_id=app,name='forbidden',path=str(tmp_path),commit='a'*40))
    assert response.status_code==422


def test_login_failures_throttled_and_hashed(client):
    account(client)
    browser=TestClient(client.app,headers={'X-ArchIntel-Request':'1'})
    for _ in range(8):
        assert browser.post('/api/v1/security/login',json=dict(username='reader',password='wrong')).status_code==401
    assert browser.post('/api/v1/security/login',json=dict(username='reader',password='test-reader-password-2026')).status_code==429
    with client.app.state.sessions() as db:
        from sqlalchemy import select
        p=db.scalar(select(Principal).where(Principal.username=='reader'))
        assert p.password_hash.startswith('scrypt:') and 'test-reader-password' not in p.password_hash


def test_password_change_revokes_other_sessions_and_rejects_old_password(client):
    account(client)
    first, second = login(client), login(client)
    assert first.post('/api/v1/security/password', json=dict(current_password='wrong',new_password='new-reader-password-2026')).status_code == 403
    changed = first.post('/api/v1/security/password', json=dict(current_password='test-reader-password-2026',new_password='new-reader-password-2026'))
    assert changed.status_code == 200, changed.text
    first.headers['X-CSRF-Token'] = changed.json()['csrf_token']
    assert first.get('/api/v1/projects').status_code == 200
    assert second.get('/api/v1/projects').status_code == 401
    assert second.post('/api/v1/security/login', json=dict(username='reader',password='test-reader-password-2026')).status_code == 401
    assert login(client, password='new-reader-password-2026').get('/api/v1/projects').status_code == 200
    assert first.post('/api/v1/security/logout').status_code == 200


def test_direct_model_adapter_cannot_bypass_gateway():
    from app.services.assistant import OllamaProvider
    with pytest.raises(RuntimeError, match='AI gateway'):
        OllamaProvider('http://127.0.0.1:1', 'unused').select_facts('question', [])


def test_upgrade_preserves_existing_snapshots(tmp_path):
    from alembic import command
    from alembic.config import Config
    from app.config import ROOT, Settings
    from app.db.session import build_engine
    from app.models import Project, Application, Artifact, AnalysisRun
    from app.runtime.models import RuntimeSession
    from sqlalchemy.orm import Session
    engine = build_engine(Settings(_env_file=None,database_url='sqlite:///'+(tmp_path/'upgrade.db').as_posix(),data_dir=tmp_path))
    migration = Config(str(ROOT/'backend/alembic.ini'))
    migration.attributes['engine'] = engine
    command.upgrade(migration, '0002')
    with Session(engine) as db:
        p=Project(name='Preserved');db.add(p);db.flush()
        a=Application(project_id=p.id,name='Preserved');db.add(a);db.flush()
        f=Artifact(application_id=a.id,filename='existing.jar',path='existing',sha256='a'*64,size=10);db.add(f);db.flush()
        run=AnalysisRun(application_id=a.id,artifact_id=f.id,status='COMPLETED',result={'original':'evidence'});db.add(run);db.flush()
        run_id=run.id
        db.commit()
    with engine.connect() as db:
        before = [tuple(row) for row in db.execute(text('SELECT id, tenant_id, created_at, application_id, artifact_id, status, progress, stage, started_at, completed_at, error_message, stages, result FROM analysis_runs'))]
    command.upgrade(migration, 'head')
    with engine.connect() as db:
        assert [tuple(row) for row in db.execute(text('SELECT id, tenant_id, created_at, application_id, artifact_id, status, progress, stage, started_at, completed_at, error_message, stages, result FROM analysis_runs'))] == before
        assert db.execute(text('SELECT limit_details FROM analysis_runs')).scalar() is None
        assert db.execute(text('SELECT COUNT(*) FROM projects')).scalar() == 1
    engine.dispose()


def test_runtime_workspace_boundary_and_ingestion_identity(client):
    from app.models import Artifact, AnalysisRun
    from test_runtime import baseline, payload, span
    workspace = client.post('/api/v1/security/workspaces',json=dict(name='Runtime tenant',admin_username='runtime-owner',admin_password='runtime-owner-password')).json()
    other = login(client, 'runtime-owner', 'runtime-owner-password')
    application = new_app(other)
    with client.app.state.sessions() as db:
        artifact=Artifact(tenant_id=workspace['id'],application_id=application,filename='test.jar',path='unused',sha256='0'*64,size=1)
        db.add(artifact);db.flush()
        run=AnalysisRun(tenant_id=workspace['id'],application_id=application,artifact_id=artifact.id,status='COMPLETED',result=baseline())
        db.add(run);db.commit();run_id=run.id
    response=other.post(f'/api/v1/applications/{application}/runtime-sessions',json=dict(analysis_id=run_id,name='Scoped runtime'))
    assert response.status_code == 201,response.text
    created=response.json();base='/api/v1/runtime-sessions/'+created['session']['id']
    assert client.get(base).status_code == 404
    assert client.post(base+'/start').status_code == 404
    assert other.post(base+'/start').status_code == 200
    agent=TestClient(client.app,headers={'Authorization':'Bearer '+created['token']})
    assert agent.get(base).status_code == 401
    assert agent.post(base+'/v1/traces',json=payload(span(1,'app.a.A'))).status_code == 200
    assert other.get(base).status_code == 200
    from app.runtime.models import RuntimeSession
    with client.app.state.sessions() as db:
        assert db.get(RuntimeSession,created['session']['id']).tenant_id == workspace['id']
    assert other.post(base+'/stop').status_code == 200
    assert client.get(base+'/graph').status_code == 404


def test_worker_capacity_remains_global_across_workspaces(client):
    from app.models import Artifact, AnalysisRun
    application=new_app(client)
    with client.app.state.sessions() as db:
        artifact=Artifact(application_id=application,filename='existing.jar',path='unused',sha256='0'*64,size=1)
        db.add(artifact);db.flush()
        for _ in range(4):
            db.add(AnalysisRun(application_id=application,artifact_id=artifact.id,status='QUEUED'))
        db.commit()
    assert client.post('/api/v1/security/workspaces',json=dict(name='Capacity tenant',admin_username='capacity-owner',admin_password='capacity-owner-password')).status_code==201
    other=login(client,'capacity-owner','capacity-owner-password')
    theirs=new_app(other)
    assert other.get('/api/v1/analyses').json()==[]
    assert other.post(f'/api/v1/applications/{theirs}/analysis').status_code==429
