import io
import time
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.config import Settings
from app.main import create_app
from app.db.session import build_engine
from app.services.scanner import JQAssistantScanner
from helpers import sample
from security_helpers import sign_in_owner


@pytest.fixture
def client(tmp_path,monkeypatch):
    settings=Settings(_env_file=None,database_url='sqlite:///'+(tmp_path/'test.db').as_posix(),data_dir=tmp_path,allowed_hosts=['testserver'])
    monkeypatch.setattr(JQAssistantScanner,'available',lambda self:True)
    monkeypatch.setattr(JQAssistantScanner,'scan',lambda *args:sample())
    with TestClient(create_app(settings)) as client:
        sign_in_owner(client)
        yield client


def artifact():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('app/Sample.class',b'\xca\xfe\xba\xbe'+b'\0'*20)
    return data.getvalue()


def new_app(client):
    project=client.post('/api/v1/projects',json={'name':'Test workspace','description':'Fixture'}).json()
    response=client.post('/api/v1/applications',json={'project_id':project['id'],'name':'Fixture','version':'1.0'})
    assert response.status_code==201
    return response.json()['id']


def test_health_configuration_and_migration(client):
    assert client.get('/api/v1/health').status_code==200
    assert client.get('/api/v1/ready').json()['dependencies']=={'database':'ok','scanner':'ok'}
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0010'
    assert client.get('/api/v1/analysis/capabilities').json()['status']=='AVAILABLE'


def test_database_validation_and_redaction():
    settings=Settings(_env_file=None,database_url='postgresql+psycopg://u:private@localhost/test')
    engine=build_engine(settings)
    assert 'private' not in repr(engine)
    engine.dispose()
    with pytest.raises(ValueError):
        Settings(_env_file=None,database_url='mysql://host/test')


def test_modernization_explanation_weights_are_explicit():
    from app.services.engine import analyze
    from app.config import Settings
    from helpers import sample
    classes,edges=sample()
    result=analyze(classes,edges,Settings(_env_file=None))
    assert result['modernization']
    for assessment in result['modernization']:
        assert set(assessment['component_scores']) == set(assessment['weights'])
        assert 'heuristic' in assessment['formula']
        assert assessment['explanation']


def test_project_validation_and_ownership(client):
    assert client.post('/api/v1/projects',json={'name':'  '}).status_code==422
    assert client.get('/api/v1/applications/missing').status_code==404
    assert client.post('/api/v1/applications',json={'project_id':'missing','name':'x'}).status_code==404


def test_complete_api_flow_progress_results_and_cleanup(client):
    app=new_app(client)
    upload=client.post(f'/api/v1/applications/{app}/artifact',files={'file':('sample.jar',artifact(),'application/java-archive')})
    assert upload.status_code==201
    assert 'path' not in upload.json()
    start=client.post(f'/api/v1/applications/{app}/analysis')
    assert start.status_code==202
    identity=start.json()['id']
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        state=client.get(f'/api/v1/analyses/{identity}/status').json()
        if state['status'] in ('COMPLETED','FAILED'):break
        time.sleep(.02)
    assert state['status']=='COMPLETED',state
    assert state['progress']==100 and state['stages']
    for path in ['summary','graph/classes','graph/packages','graph/domains','domains','issues','metrics','cycles','modernization','modernization/sequence','export','dependencies/external']:
        assert client.get(f'/api/v1/analyses/{identity}/{path}').status_code==200,path
    limited=client.get(f'/api/v1/analyses/{identity}/graph/classes?limit=1').json()
    assert limited['truncated'] and len(limited['nodes'])==1
    ids={n['id'] for n in limited['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in limited['edges'])
    response=client.post(f'/api/v1/analyses/{identity}/assistant/query',json={'question':'Where should modernization begin?'})
    assert response.status_code==200 and response.json()['facts']
    assert client.get(f'/api/v1/analyses/{identity}/domains/missing').status_code==404
    deadline=time.monotonic()+5
    while list((client.app.state.config.data_dir/'uploads').glob('*')) and time.monotonic()<deadline:time.sleep(.02)
    assert not list((client.app.state.config.data_dir/'uploads').glob('*'))


def test_invalid_archive_rejected_without_residual_file(client):
    app=new_app(client)
    response=client.post(f'/api/v1/applications/{app}/artifact',files={'file':('bad.jar',b'not a zip')})
    assert response.status_code==422
    assert not list((client.app.state.config.data_dir/'uploads').glob('*'))
    assert client.post(f'/api/v1/applications/{app}/analysis').status_code==409


def test_upload_size_limit_is_structured_and_cleans_partial_file(client):
    app=new_app(client)
    client.app.state.config.max_upload_mb=0
    response=client.post(f'/api/v1/applications/{app}/artifact',files={'file':('sample.jar',artifact())})
    assert response.status_code==413
    detail=response.json()['detail']
    assert detail['code']=='LIMIT_EXCEEDED' and detail['limit']=='max_upload_size_compressed'
    assert not list((client.app.state.config.data_dir/'uploads').glob('*'))


def test_limit_rejection_is_distinct_and_job_files_are_cleaned(client,monkeypatch):
    from app.services.ingestion import LimitExceeded
    def rejected(*args):raise LimitExceeded('max_edges_per_scan',1,2,'Split the artifact.')
    monkeypatch.setattr(JQAssistantScanner,'scan',rejected)
    app=new_app(client)
    client.post(f'/api/v1/applications/{app}/artifact',files={'file':('sample.jar',artifact())})
    identity=client.post(f'/api/v1/applications/{app}/analysis').json()['id']
    for _ in range(200):
        state=client.get(f'/api/v1/analyses/{identity}').json()
        if state['status']=='REJECTED_LIMIT_EXCEEDED':break
        time.sleep(.02)
    assert state['status']=='REJECTED_LIMIT_EXCEEDED'
    assert state['limit_details']['limit']=='max_edges_per_scan'
    deadline=time.monotonic()+2
    while list((client.app.state.config.data_dir/'jobs').glob(identity+'-*')) and time.monotonic()<deadline:time.sleep(.02)
    assert not list((client.app.state.config.data_dir/'jobs').glob(identity+'-*'))
    assert client.get(f'/api/v1/analyses/{identity}/summary').status_code==409


def test_failed_scan_never_publishes_results(client,monkeypatch):
    from app.services.scanner import ScannerError
    def failed(*args):raise ScannerError('Unsupported test artifact')
    monkeypatch.setattr(JQAssistantScanner,'scan',failed)
    app=new_app(client)
    client.post(f'/api/v1/applications/{app}/artifact',files={'file':('sample.jar',artifact())})
    identity=client.post(f'/api/v1/applications/{app}/analysis').json()['id']
    for _ in range(200):
        state=client.get(f'/api/v1/analyses/{identity}').json()
        if state['status']=='FAILED':break
        time.sleep(.02)
    assert state['status']=='FAILED'
    assert client.get(f'/api/v1/analyses/{identity}/summary').status_code==409
    assert state['error_message']=='Unsupported test artifact'
