"""Failure-path regressions for the first dependability checkpoint."""
import io
import time
import zipfile

import pytest

from app.models import AnalysisRun, Artifact
from app.services.scanner import JQAssistantScanner, ScannerError
from helpers import sample
from test_foundation import client, artifact, new_app


def wait_for(client, identity):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = client.get(f'/api/v1/analyses/{identity}').json()
        if result['status'] in ('COMPLETED', 'FAILED'):
            return result
        time.sleep(.02)
    pytest.fail('Analysis did not reach a terminal state.')


def uploaded(client):
    application = new_app(client)
    response = client.post(f'/api/v1/applications/{application}/artifact',
        files={'file': ('fixture.jar', artifact())})
    assert response.status_code == 201
    return application, response.json()['id']


def test_project_zip_upload_runs_through_project_bytecode_ingestion(client, monkeypatch):
    bundle=io.BytesIO()
    with zipfile.ZipFile(bundle,'w') as archive:
        archive.writestr('concord/server/target/classes/org/example/Server.class',b'\xca\xfe\xba\xbecompiled')
    application=new_app(client)
    response=client.post(f'/api/v1/applications/{application}/artifact',
        files={'file':('concord-classes.zip',bundle.getvalue())})
    assert response.status_code==201, response.text
    assert response.json()['manifest']['packaging']=='JAVA_PROJECT_ZIP'
    monkeypatch.setattr(JQAssistantScanner,'scan',lambda *args: sample())
    run=client.post(f'/api/v1/applications/{application}/analysis')
    assert run.status_code==202, run.text
    assert wait_for(client,run.json()['id'])['status']=='COMPLETED'


def test_failed_artifact_can_be_retried_without_upload(client, monkeypatch):
    application, artifact_id = uploaded(client)
    def fail(*args):
        raise ScannerError('Transient scanner failure')
    monkeypatch.setattr(JQAssistantScanner, 'scan', fail)
    first = client.post(f'/api/v1/applications/{application}/analysis').json()['id']
    assert wait_for(client, first)['status'] == 'FAILED'
    with client.app.state.sessions() as db:
        record = db.get(Artifact, artifact_id)
        assert record.available
        from pathlib import Path
        assert Path(record.path).is_file()
    monkeypatch.setattr(JQAssistantScanner, 'scan', lambda *args: sample())
    retry = client.post(f'/api/v1/applications/{application}/analysis')
    assert retry.status_code == 202
    assert retry.json()['id'] != first
    assert wait_for(client, retry.json()['id'])['status'] == 'COMPLETED'
    assert client.get(f'/api/v1/analyses/{first}').json()['status'] == 'FAILED'


@pytest.mark.parametrize('old_status', ['QUEUED', 'RUNNING'])
def test_restart_recovers_persisted_job(client, old_status):
    application, artifact_id = uploaded(client)
    with client.app.state.sessions.begin() as db:
        run = AnalysisRun(application_id=application, artifact_id=artifact_id, status=old_status)
        db.add(run)
        db.flush()
        identity = run.id
    client.app.state.worker.recover()
    assert wait_for(client, identity)['status'] == 'COMPLETED'


def test_missing_recovery_input_fails_with_actionable_error(client):
    application, artifact_id = uploaded(client)
    with client.app.state.sessions.begin() as db:
        db.get(Artifact, artifact_id).available = False
        run = AnalysisRun(application_id=application, artifact_id=artifact_id, status='RUNNING')
        db.add(run)
        db.flush()
        identity = run.id
    client.app.state.worker.recover()
    state = wait_for(client, identity)
    assert state['status'] == 'FAILED'
    assert state['stage'] == 'RECOVERY_FAILED'
    assert 'Upload' in state['error_message']


def test_duplicate_submission_executes_scanner_once(client, monkeypatch):
    application, artifact_id = uploaded(client)
    calls = []
    def scan(*args):
        calls.append(1)
        return sample()
    monkeypatch.setattr(JQAssistantScanner, 'scan', scan)
    with client.app.state.sessions.begin() as db:
        run = AnalysisRun(application_id=application, artifact_id=artifact_id)
        db.add(run)
        db.flush()
        identity = run.id
    client.app.state.worker.run(identity)
    client.app.state.worker.run(identity)
    assert calls == [1]
    assert wait_for(client, identity)['status'] == 'COMPLETED'


def test_modified_artifact_never_reaches_scanner(client, monkeypatch):
    application, artifact_id = uploaded(client)
    with client.app.state.sessions() as db:
        from pathlib import Path
        Path(db.get(Artifact, artifact_id).path).write_bytes(b'changed')
    def unexpected(*args):
        pytest.fail('Tampered artifact reached scanner')
    monkeypatch.setattr(JQAssistantScanner, 'scan', unexpected)
    run = client.post(f'/api/v1/applications/{application}/analysis').json()['id']
    state = wait_for(client, run)
    assert state['status'] == 'FAILED' and 'checksum' in state['error_message']


def test_browser_origin_and_host_boundary(client):
    path = '/api/v1/projects'
    assert client.get(path, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post(path, json={'name': 'Blocked'}, headers={'Origin': 'null'}).status_code == 403
    assert client.get(path, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get(path, headers={'Host': 'rebind.example'}).status_code == 400
    assert client.get(path, headers={'Origin': 'http://testserver'}).status_code == 200
    assert client.get(path, headers={'Origin': 'http://localhost:5173'}).status_code == 200
    # CLI and OTel requests without browser headers remain supported.
    assert client.get(path).status_code == 200
    assert client.get(path).headers['x-frame-options'] == 'DENY'
