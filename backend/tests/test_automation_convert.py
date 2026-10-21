"""Local conversion trial: gates, source selection within the grant, generation, build, comparison and audit, with fakes for Claude and the runner."""
import json
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from app.ai.models import ModelInvocation
from app.automation import convert
from app.automation.models import AutomationJob
from test_ai_claude import FakeClient, message
from test_transformation import prepare, live  # noqa: F401  (fixture)

ACK = 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE'


def bundle(name='svc'):
    return {'files': [{'path': 'pom.xml', 'operation': 'ADD', 'content': '<project><artifactId>svc</artifactId></project>', 'rationale': 'build'},
                      {'path': 'README.md', 'operation': 'ADD', 'content': '# Service', 'rationale': 'docs'},
                      {'path': 'src/main/java/svc/App.java', 'operation': 'ADD', 'content': 'class App {}', 'rationale': 'entry'},
                      {'path': 'src/test/java/svc/AppTest.java', 'operation': 'ADD', 'content': 'class AppTest {}', 'rationale': 'test'}],
            'unresolved_questions': ['Who owns table A?']}


class FakeRunner:
    def __init__(self, build_state='RUNNING', equivalent=True):
        self.calls, self.build_state, self.equivalent, self.built = [], build_state, equivalent, None

    def __call__(self, request: httpx.Request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        self.calls.append((method, path))
        if path == '/v1/health':
            return httpx.Response(200, json=dict(status='READY', tools=dict(java=True, chrome=True, otel_agent=True, rea='6.7.0', docker='29.7.2'), apps=[], services=[]))
        if path == '/v1/services' and method == 'POST':
            self.built = body
            return httpx.Response(201, json=dict(name=body['name'], state=self.build_state, base_url='http://127.0.0.1:18100' if self.build_state == 'RUNNING' else None,
                                                 build_log_tail='[ERROR] COMPILATION ERROR' if self.build_state != 'RUNNING' else None))
        if path == '/v1/apps' and method == 'POST':
            return httpx.Response(201, json=dict(id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', base_url='http://127.0.0.1:18080'))
        if path == '/v1/compare':
            n = len(body['scenarios'])
            status = 'EQUIVALENT' if self.equivalent else 'DIFFERENT'
            return httpx.Response(200, json=dict(total=n, counts={status: n}, results=[dict(name=s['name'], status=status, differences=[]) for s in body['scenarios']]))
        if method == 'DELETE':
            return httpx.Response(200, json=dict(stopped=True))
        return httpx.Response(404, json=dict(error='NOT_FOUND'))


@pytest.fixture
def ready(live):
    d = prepare(live)
    c = d['client']
    plan = c.get(f"/api/v1/architecture-versions/{d['version']['id']}/modernization/{d['plan']['id']}").json()['document']
    candidate = next(x for x in plan['microservice_decomposition']['service_candidates'] if x['proposal_state'] == 'CANDIDATE_REQUIRES_REVIEW')
    for class_id in candidate['class_ids']:
        path = d['root'] / 'src/main/java' / (class_id.replace('.', '/') + '.java')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'class {class_id.rsplit(".", 1)[-1]} {{}}\n', encoding='utf-8')
    (d['root'] / 'src/main/resources').mkdir(parents=True, exist_ok=True)
    (d['root'] / 'src/main/resources/application.properties').write_text('spring.application.name=fixture\n')
    d['git']('add', '.'); d['git']('-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-m', 'service sources')
    commit = d['git']('rev-parse', 'HEAD')
    repo = c.post('/api/v1/security/repositories', json=dict(application_id=c.app_id, name='Service source', path=str(d['root']), commit=commit)).json()['id']
    assert c.post('/api/v1/security/grants', json=dict(principal_id=d['owner'], repository_id=repo, allowed_paths=['pom.xml', 'src/main/java/'], protected_paths=[])).status_code == 200
    policy = c.get('/api/v1/security/policy').json(); revision = policy.pop('revision')
    assert c.post('/api/v1/security/policy', json=dict(policy, expected_revision=revision, claude_source_transfer_enabled=True)).status_code == 200
    c.app.state.config.anthropic_api_key = SecretStr('sk-test')
    c.app.state.config.runner_token = SecretStr('r' * 40)
    with c.app.state.sessions() as db:
        db.add(AutomationJob(tenant_id='local', application_id=c.app_id, analysis_id=c.run_id, kind='EXPLORE', state='COMPLETED', actor_id=d['owner'],
                             document=dict(artifact=dict(sha256='a' * 64, bytes=1), exploration=dict(routes=[], pages=[]))))
        db.commit()
    return dict(d, candidate=candidate, repo=repo, commit=commit,
                base=f"/api/v1/architecture-versions/{d['version']['id']}/modernization/{d['plan']['id']}/conversions")


def start(ready, runner, client=None):
    c = ready['client']
    with c.app.state.sessions() as db:
        version = db.get(convert.ArchitectureVersion, ready['version']['id']); plan = db.get(convert.Assessment, ready['plan']['id'])
        identity = dict(id=ready['owner'], tenant_id='local', kind='HUMAN')
        job = convert.create(db, c.app.state.config, identity, version, plan, ready['candidate']['id'], ready['repo'], ACK)
        job_id = job.id
    claude_client = client or FakeClient(message(text=json.dumps(bundle())))
    convert.run(c.app.state.sessions, c.app.state.config, job_id, identity, httpx.MockTransport(runner), claude_client)
    with c.app.state.sessions() as db:
        job = db.get(AutomationJob, job_id)
        return job.state, dict(job.document), claude_client


def test_the_checklist_names_every_missing_gate_and_is_ready_once_they_are_met(ready):
    c = ready['client']
    url = ready['base'] + f"/preconditions?candidate_id={ready['candidate']['id']}&repository_id={ready['repo']}"
    assert c.get(url).json()['ready'] is True
    c.app.state.config.anthropic_api_key = SecretStr('')
    rows = c.get(url).json()['items']
    assert [r['id'] for r in rows if not r['met']] == ['CLAUDE_KEY']
    unknown = c.get(ready['base'] + f"/preconditions?candidate_id={ready['candidate']['id']}").json()['items']
    assert {r['id'] for r in unknown if not r['met']} >= {'REPOSITORY', 'SOURCE_GRANT'}


def test_a_conversion_sends_only_granted_candidate_source_then_builds_runs_and_compares(ready):
    runner = FakeRunner()
    state, doc, claude_client = start(ready, runner)
    assert state == 'COMPLETED', doc.get('error')
    assert [s['state'] for s in doc['steps']] == ['DONE'] * len(convert.STEPS)
    sent = {f['path'] for f in doc['source']['files']}
    assert sent >= {'pom.xml'} and all(p == 'pom.xml' or p.startswith('src/main/java/') for p in sent)
    assert {'path': 'src/main/resources/application.properties', 'reason': 'OUTSIDE_GRANT_OR_PROTECTED'} in doc['source']['excluded']
    prompt = json.loads(claude_client.requests[0]['messages'][0]['content'])
    assert {f['path'] for f in prompt['source_files']} == sent
    assert any('--server.port=8080' in r for r in prompt['requirements'])
    assert [f['path'] for f in runner.built['files']] == [f['path'] for f in bundle()['files']]
    assert doc['service']['state'] == 'RUNNING' and doc['generation']['unresolved_questions'] == ['Who owns table A?']
    assert doc['verdict'] == 'NOT_COMPARED'                                       # the recorded exploration had no page of this candidate
    with ready['client'].app.state.sessions() as db:
        audit = [r for r in db.scalars(select(ModelInvocation)) if (r.metadata_json or {}).get('lane') == 'LOCAL_TRIAL']
    assert [r.outcome for r in audit] == ['ALLOW'] and audit[0].metadata_json['destination'] == 'CLAUDE_EXTERNAL'
    c = ready['client']
    listed = c.get(ready['base']).json()['items']
    assert listed[0]['id'] and listed[0]['state'] == 'COMPLETED'
    file = c.get(ready['base'] + f"/{listed[0]['id']}/files/src/main/java/svc/App.java")
    assert file.status_code == 200 and file.json()['content'] == 'class App {}'
    assert c.get(ready['base'] + f"/{listed[0]['id']}/files/../../secret").status_code == 404
    c.app.state.runner_transport = httpx.MockTransport(runner)                     # tests only; production builds its own client
    stopped = c.delete(ready['base'] + f"/{listed[0]['id']}/service")
    assert stopped.status_code == 200 and stopped.json()['service']['state'] == 'STOPPED'


def test_a_refused_generation_fails_closed_is_audited_and_builds_nothing(ready):
    runner = FakeRunner()
    state, doc, _ = start(ready, runner, FakeClient(message(stop='refusal')))
    assert state == 'FAILED' and doc['error']['step'] == 'GENERATE' and doc['error']['code'] == 'REFUSED'
    assert ('POST', '/v1/services') not in runner.calls
    with ready['client'].app.state.sessions() as db:
        outcomes = [r.outcome for r in db.scalars(select(ModelInvocation)) if (r.metadata_json or {}).get('lane') == 'LOCAL_TRIAL']
    assert outcomes == ['REJECTED']


def test_a_build_failure_is_reported_with_the_build_log(ready):
    state, doc, _ = start(ready, FakeRunner(build_state='BUILD_FAILED'))
    assert state == 'FAILED' and doc['error']['step'] == 'BUILD_SERVICE' and 'COMPILATION ERROR' in doc['error']['detail']


def test_the_api_requires_the_acknowledgement_and_all_gates(ready):
    c = ready['client']
    body = dict(candidate_id=ready['candidate']['id'], repository_id=ready['repo'], acknowledgement='yes')
    assert c.post(ready['base'], json=body).status_code == 422
    c.app.state.config.runner_token = SecretStr('')
    blocked = c.post(ready['base'], json=dict(body, acknowledgement=ACK))
    assert blocked.status_code == 409 and [m['id'] for m in blocked.json()['detail']['missing']] == ['RUNNER']
