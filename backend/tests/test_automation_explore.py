"""Automated exploration: the job drives a (fake) runner, which sends real OTLP spans back, and ends with an ordinary completed session."""
import json
import httpx
import pytest
from pydantic import SecretStr
from app.automation import explore
from app.automation.models import AutomationJob
from app.runtime.models import RuntimeSession
from test_runtime import live, payload, span

JAR = b'PK\x03\x04 runnable test jar'


class FakeRunner:
    """Speaks the runner API; on explore it posts spans to the session endpoint it was given, like the real agent would."""

    def __init__(self, client, tools=None, fail_explore=False):
        self.client, self.calls, self.otel = client, [], None
        self.tools = tools or dict(java=True, chrome=True, otel_agent=True, rea='6.7.0', docker='29.7.2')
        self.fail_explore = fail_explore

    def __call__(self, request: httpx.Request):
        path, method = request.url.path, request.method
        self.calls.append((method, path, request.headers.get('authorization')))
        if path == '/v1/health':
            return httpx.Response(200, json=dict(status='READY', tools=self.tools, apps=[], services=[]))
        if method == 'PUT' and path.startswith('/v1/artifacts/'):
            return httpx.Response(201, json=dict(sha256=path.rsplit('/', 1)[1], bytes=len(request.content)))
        if path == '/v1/apps' and method == 'POST':
            self.otel = json.loads(request.content)['otel']
            return httpx.Response(201, json=dict(id='11111111-2222-3333-4444-555555555555', base_url='http://127.0.0.1:18080', port=18080))
        if path == '/v1/explore':
            if self.fail_explore:
                return httpx.Response(409, json=dict(error='REA_FAILED', detail='browser did not start'))
            endpoint = httpx.URL(self.otel['endpoint']).path
            token = self.otel['headers'].split('Bearer ', 1)[1]
            response = self.client.post(endpoint, json=payload(span(1, 'app.a.A'), span(2, 'app.b.B', 1)), headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 200, response.text
            return httpx.Response(200, json=dict(origin='http://127.0.0.1:18080', duration_ms=900, stopped_by_time=False,
                pages=[dict(url='http://127.0.0.1:18080/', shape='/', status=200, step_status='completed', evidence_id='ev1')],
                forms=[dict(page='http://127.0.0.1:18080/', method='POST', action='http://127.0.0.1:18080/a', shape='/a', fields=['n'], completed=True, statuses=[302], final_url=None, evidence_id='ev1', error=None)],
                routes=[dict(method='GET', shape='/', statuses=[200]), dict(method='POST', shape='/a', statuses=[302])],
                unvisited=[], skipped=[], failures=[], evidence_ids=['ev1'], transactions=[]))
        if method == 'DELETE' and path.startswith('/v1/apps/'):
            return httpx.Response(200, json=dict(stopped=True))
        return httpx.Response(404, json=dict(error='NOT_FOUND'))


def configured(client):
    client.app.state.config.runner_token = SecretStr('t' * 40)
    return client


def run_job(client, fake):
    with client.app.state.sessions() as db:
        job = explore.create(db, dict(tenant_id='local', id='tester'), client.app_id, client.run_id, JAR, dict(max_pages=10, max_forms=2, mode='STANDARD'))
        job_id = job.id
    explore.run(client.app.state.sessions, client.app.state.config, job_id, JAR, httpx.MockTransport(fake))
    with client.app.state.sessions() as db:
        job = db.get(AutomationJob, job_id)
        session = db.get(RuntimeSession, job.document.get('session_id')) if job.document.get('session_id') else None
        return job.state, dict(job.document), session and dict(status=session.status, spans=session.span_count)


def test_seeds_are_get_routes_without_path_variables():
    result = dict(entry_points=dict(items=[dict(http_method='GET', path='/vets'), dict(http_method='GET', path='/owners/{id}'), dict(http_method='POST', path='/owners/new'),
                                           dict(http_method='NOT_HTTP', path='NOT_HTTP'), dict(http_method='GET', path='/a/**'), dict(http_method='GET', path='/vets')]))
    assert explore.seeds(result) == ['/vets']


def test_an_exploration_records_a_completed_session_with_the_spans_the_application_sent(live):
    fake = FakeRunner(configured(live))
    state, document, session = run_job(live, fake)
    assert state == 'COMPLETED', document.get('error')
    assert [s['state'] for s in document['steps']] == ['DONE'] * len(explore.STEPS)
    assert session == dict(status='COMPLETED', spans=2)
    assert document['exploration']['summary'] == dict(pages=1, forms=1, forms_completed=1, routes=2, failures=0, skipped=0, duration_ms=900)
    assert document['coverage']['spans'] == 2 and document['coverage']['classes']['observed'] == 2
    assert fake.otel['endpoint'].endswith(f"/api/v1/runtime-sessions/{document['session_id']}/v1/traces")
    assert all(auth == 'Bearer ' + 't' * 40 for _, _, auth in fake.calls)
    assert ('DELETE', '/v1/apps/11111111-2222-3333-4444-555555555555') in [(m, p) for m, p, _ in fake.calls]


def test_missing_tools_stop_the_job_before_a_session_is_created(live):
    fake = FakeRunner(configured(live), tools=dict(java=True, chrome=False, otel_agent=True, rea=None))
    state, document, session = run_job(live, fake)
    assert state == 'FAILED' and session is None
    assert document['error'] == dict(step='CHECK_RUNNER', code='RUNNER_TOOLS_MISSING', detail='chrome, rea')


def test_a_failed_exploration_stops_the_application_and_closes_the_session(live):
    fake = FakeRunner(configured(live), fail_explore=True)
    state, document, session = run_job(live, fake)
    assert state == 'FAILED' and document['error']['step'] == 'EXPLORE' and document['error']['code'] == 'REA_FAILED'
    assert session['status'] == 'COMPLETED'                                     # not left waiting for telemetry
    assert any(m == 'DELETE' for m, _, _ in fake.calls)


def test_the_api_requires_a_runnable_archive_a_configured_runner_and_explicit_consent(live):
    url = f'/api/v1/applications/{live.app_id}/runtime-sessions/explore'
    form = dict(analysis_id=live.run_id, confirm_disposable_data='true')
    live.app.state.config.runner_token = SecretStr('')                          # independent of a RUNNER_TOKEN in the environment
    status = live.get(f'/api/v1/applications/{live.app_id}/runtime-sessions/automation').json()
    assert status['configured'] is False
    assert live.post(url, data=form, files=dict(file=('app.jar', JAR))).status_code == 503
    configured(live)
    assert live.post(url, data=dict(form, confirm_disposable_data='false'), files=dict(file=('app.jar', JAR))).status_code == 422
    assert live.post(url, data=form, files=dict(file=('notes.txt', JAR))).status_code == 422
    assert live.post(url, data=form, files=dict(file=('app.jar', b'not a zip'))).status_code == 422
    assert live.post(url, data=dict(form, max_pages='999'), files=dict(file=('app.jar', JAR))).status_code == 422
    assert live.get(f'/api/v1/applications/{live.app_id}/runtime-sessions/explorations').json() == dict(items=[])
