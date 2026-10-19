"""End-to-end API fixture: real pipeline with the built-in bytecode scanner on compiled fixtures."""
import time
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from security_helpers import sign_in_owner
from insight_fixtures import jar


def analyse(client, name='petclinic'):
    project = client.post('/api/v1/projects', json={'name': 'Insight ' + name, 'description': 'fixture'}).json()
    app = client.post('/api/v1/applications', json={'project_id': project['id'], 'name': name, 'version': '1.0'}).json()['id']
    upload = client.post(f'/api/v1/applications/{app}/artifact', files={'file': (name + '.jar', jar(name), 'application/java-archive')})
    assert upload.status_code == 201, upload.text
    run = client.post(f'/api/v1/applications/{app}/analysis').json()
    for _ in range(300):
        state = client.get(f"/api/v1/analyses/{run['id']}").json()
        if state['status'] in ('COMPLETED', 'FAILED'):
            break
        time.sleep(.05)
    assert state['status'] == 'COMPLETED', state
    return run['id'], app


@pytest.fixture
def insight_client(tmp_path):
    settings = Settings(_env_file=None, database_url='sqlite:///' + (tmp_path / 'test.db').as_posix(), data_dir=tmp_path,
        allowed_hosts=['testserver'], scanner_engine='bytecode')
    with TestClient(create_app(settings)) as client:
        sign_in_owner(client)
        yield client


@pytest.fixture
def fake_model(monkeypatch):
    """Local Ollama stand-in. Tests set `replies` to the JSON contents the model should return in order."""
    from app.ai.providers import endpoint_allowed
    calls, replies = [], []
    def exchange(endpoint, path, settings, payload=None):
        endpoint_allowed(endpoint, settings)
        calls.append((path, payload))
        if path == '/api/tags':
            return {'models': [{'name': 'qwen2.5:0.5b', 'digest': 'a' * 64, 'size': 100}]}
        content = replies.pop(0) if replies else '{"sentences":[]}'
        return {'done': True, 'message': {'role': 'assistant', 'content': content}, 'eval_count': 7}
    monkeypatch.setattr('app.ai.providers.exchange', exchange)
    return calls, replies


def enable_model(client):
    provider = client.post('/api/v1/security/ai/providers', json=dict(name='Local test', model='qwen2.5:0.5b'))
    assert provider.status_code == 201, provider.text
    policy = client.get('/api/v1/security/policy').json(); revision = policy.pop('revision')
    response = client.post('/api/v1/security/policy', json=dict(policy, expected_revision=revision, model_enabled=True, model_provider_id=provider.json()['id']))
    assert response.status_code == 200, response.text
