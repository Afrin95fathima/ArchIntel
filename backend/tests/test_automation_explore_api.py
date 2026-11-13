"""API exploration with a launch recipe: the job drives a (fake) runner that starts a distribution, sends real OTLP spans back,
and ends with an ordinary completed session; the routes check the distribution, the recipe and the scenario file."""
import gzip
import hashlib
import json
import httpx
from app.automation import explore_api
from app.automation.models import AutomationJob
from app.runtime.models import RuntimeSession
from test_automation_explore import configured
from test_runtime import live, payload, span

DIST = gzip.compress(b'tar bytes of a distribution')


class FakeRunner:
    def __init__(self, client, fail_start=False):
        self.client, self.calls, self.otel, self.recipe, self.explore = client, [], None, None, None
        self.fail_start = fail_start

    def __call__(self, request: httpx.Request):
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path == '/v1/health':
            return httpx.Response(200, json=dict(status='READY', tools=dict(java=True, otel_agent=True, docker='29.7.2'), apps=[], services=[]))
        if method == 'PUT' and path.startswith('/v1/distributions/'):
            return httpx.Response(201, json=dict(sha256=path.rsplit('/', 1)[1], bytes=len(request.content), reused=False))
        if path == '/v1/recipe-runs':
            body = json.loads(request.content)
            self.otel, self.recipe, self.distributions = body['otel'], body['recipe'], body['distributions']
            if self.fail_start:
                return httpx.Response(409, json=dict(error='APP_EXITED', detail='exit 1\nCould not connect to the database'))
            return httpx.Response(201, json=dict(id='11111111-2222-3333-4444-555555555555', base_url='http://127.0.0.1:18080', port=18080,
                                                 dependencies=[dict(name='db', port=15430)], credential=True, companions=[dict(name='agent', running=True)]))
        if path == '/v1/explore-api':
            self.explore = json.loads(request.content)
            token = self.otel['headers'].split('Bearer ', 1)[1]
            response = self.client.post(httpx.URL(self.otel['endpoint']).path, json=payload(span(1, 'app.a.A'), span(2, 'app.b.B', 1)), headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 200, response.text
            return httpx.Response(200, json=dict(origin='http://127.0.0.1:18080', duration_ms=1200, stopped_by_budget=False,
                summary=dict(requests=3, get_routes=2, get_routes_called=1, statuses={'2xx': 3}, scenario_steps=1, scenario_steps_passed=1),
                requests=[dict(phase='crawl', method='GET', template='/a', path='/a', status=200, duration_ms=5, error=None)],
                scenarios=[dict(name='demo', steps=[dict(id='create', kind='step', method='POST', path='/a', status=200, state='PASSED', error=None)], cleanup=[])],
                unresolved=[dict(template='/a/{id}', missing=['id'])], skipped=[]))
        if method == 'DELETE' and path.startswith('/v1/apps/'):
            return httpx.Response(200, json=dict(stopped=True))
        return httpx.Response(404, json=dict(error='NOT_FOUND'))


AGENT = gzip.compress(b'tar bytes of the agent distribution')


def run_job(client, fake, spec=None):
    spec = spec or explore_api.recipe('concord-server')
    with client.app.state.sessions() as db:
        job = explore_api.create(db, dict(tenant_id='local', id='tester'), client.app_id, client.run_id, DIST, spec, dict(mode=None, max_requests=None), dict(agent=AGENT))
        job_id = job.id
    explore_api.run(client.app.state.sessions, client.app.state.config, job_id, DIST, spec, httpx.MockTransport(fake), dict(agent=AGENT))
    with client.app.state.sessions() as db:
        job = db.get(AutomationJob, job_id)
        session = db.get(RuntimeSession, job.document.get('session_id')) if job.document.get('session_id') else None
        return job.state, dict(job.document), session and dict(status=session.status, spans=session.span_count, settings=dict(session.settings))


def test_built_in_recipes_are_listed_without_their_configuration():
    items = explore_api.recipes()
    concord = next(r for r in items if r['id'] == 'concord-server')
    assert concord['dependencies'] == ['postgres:14.21-alpine', 'osixia/openldap:1.5.0'] and concord['mode'] == 'DEEP' and concord['passes'] == 5
    assert [(d['id'], d.get('primary', False)) for d in concord['distributions']] == [('server', True), ('agent', False)]
    assert concord['scenarios'][0]['steps'] >= 20 and concord['scenarios'][0]['cleanup'] >= 10
    assert 'config_files' not in json.dumps(items) and 'ADMIN_TOKEN' not in json.dumps(items)


def test_an_api_exploration_records_a_completed_session_scoped_by_the_recipe(live):
    fake = FakeRunner(configured(live))
    state, document, session = run_job(live, fake)
    assert state == 'COMPLETED', document.get('error')
    assert [s['state'] for s in document['steps']] == ['DONE'] * len(explore_api.steps_for(5))
    assert session['status'] == 'COMPLETED' and session['spans'] == 2
    assert session['settings']['mode'] == 'DEEP' and session['settings']['exclude_packages'] == ['com.walmartlabs.concord.cli']
    assert fake.recipe['name'] == 'concord-server' and fake.explore['skip_paths'] and fake.explore['scenarios'][0]['name'] == 'Organization lifecycle'
    assert fake.explore['max_requests'] == 800
    assert fake.distributions == dict(agent=hashlib.sha256(AGENT).hexdigest()) and fake.recipe['companions'][0]['name'] == 'agent'
    assert ('PUT', f'/v1/distributions/{hashlib.sha256(AGENT).hexdigest()}') in fake.calls and 'companion processes: agent' in next(s for s in document['steps'] if s['name'] == 'START_APPLICATION')['detail']
    assert document['exploration']['summary']['scenario_steps_passed'] == 1 and document['coverage']['spans'] == 2
    assert document['recipe']['name'] == 'concord-server' and document['method'] == 'API'
    assert ('DELETE', '/v1/apps/11111111-2222-3333-4444-555555555555') in fake.calls


def test_a_failed_start_keeps_the_application_log_and_closes_the_session(live):
    fake = FakeRunner(configured(live), fail_start=True)
    state, document, session = run_job(live, fake)
    assert state == 'FAILED' and document['error']['step'] == 'START_APPLICATION' and document['error']['code'] == 'APP_EXITED'
    assert 'Could not connect to the database' in document['error']['detail']
    assert session['status'] == 'COMPLETED'


def test_the_api_checks_the_recipe_the_distribution_and_the_scenario_file(live):
    configured(live)
    base = f'/api/v1/applications/{live.app_id}/runtime-sessions'
    assert [r['id'] for r in live.get(base + '/recipes').json()['items']] == ['concord-server']
    url, form = base + '/explore-api', dict(analysis_id=live.run_id, recipe_id='concord-server')
    both = dict(file=('d.tar.gz', DIST), file_agent=('agent.tar.gz', AGENT))
    assert live.post(url, data=dict(form, recipe_id='nope'), files=both).status_code == 404
    assert live.post(url, data=form, files=dict(both, file=('d.zip', DIST))).status_code == 422
    assert live.post(url, data=form, files=dict(both, file=('d.tar.gz', b'not gzip'))).status_code == 422
    assert live.post(url, data=dict(form, mode='EVERYTHING'), files=both).status_code == 422
    missing = live.post(url, data=form, files=dict(file=('d.tar.gz', DIST)))
    assert missing.status_code == 422 and 'Concord agent distribution' in missing.json()['detail']
    assert live.post(url, data=form, files=dict(both, file_agent=('agent.tar.gz', b'not gzip'))).status_code == 422
    bad = live.post(url, data=form, files=dict(both, scenario_file=('s.json', b'{"name": "x"}')))
    assert bad.status_code == 422 and 'steps' in bad.json()['detail']
    assert live.post(url, data=form, files=dict(both, scenario_file=('s.json', b'not json'))).status_code == 422


def test_coverage_passes_trace_new_classes_each_time_and_stop_when_none_are_left(live):
    fake = FakeRunner(configured(live))
    spec = explore_api.recipe('concord-server')
    with live.app.state.sessions() as db:
        job = explore_api.create(db, dict(tenant_id='local', id='tester'), live.app_id, live.run_id, DIST, spec, dict(passes=3), dict(agent=AGENT))
        job_id = job.id
    explore_api.run(live.app.state.sessions, live.app.state.config, job_id, DIST, spec, httpx.MockTransport(fake), dict(agent=AGENT))
    with live.app.state.sessions() as db:
        document = dict(db.get(AutomationJob, job_id).document)
        sessions = [db.get(RuntimeSession, p['session_id']) for p in document['passes']]
    assert document['steps'][-1]['name'] == 'COMBINE_PASSES' and all(s['state'] == 'DONE' for s in document['steps']), document.get('error')
    assert len(document['passes']) == 1                                          # the small fixture fits one plan; pass 2 had nothing new to trace
    assert 'no further pass needed' in next(s for s in document['steps'] if s['name'] == 'CREATE_SESSION')['detail']
    assert document['coverage']['combined_sessions'] == [sessions[0].id] and sessions[0].status == 'COMPLETED'
    assert sum(1 for m, p in fake.calls if p == '/v1/recipe-runs') == 1
