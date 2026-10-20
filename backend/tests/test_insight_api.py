"""Insight endpoints end to end on the compiled fixtures."""
import json
from insight_api import analyse, insight_client, fake_model, enable_model  # noqa: F401


def test_pipeline_records_bytecode_facts_and_lifecycle(insight_client):
    analysis, _ = analyse(insight_client, 'edgecases')
    lifecycle = insight_client.get(f'/api/v1/analyses/{analysis}/insight/lifecycle').json()
    assert lifecycle['rules']['rules_version']
    ids = {f['rule_id'] for f in lifecycle['findings']}
    assert {'log4j-1', 'javax-persistence', 'struts-1', 'java-class-target'} <= ids
    exported = insight_client.get(f'/api/v1/analyses/{analysis}/export').json()
    assert exported['bytecode']['class_count'] == 22
    assert exported['tech_inventory']['compatibility']['framework_lifecycle'] == 'END_OF_LIFE'
    assert 'NOT_CHECKED' not in json.dumps(exported['tech_inventory']['compatibility'])


def test_petclinic_analyses_although_it_matches_the_spring_prefix(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    summary = insight_client.get(f'/api/v1/analyses/{analysis}/summary').json()
    assert summary['class_count'] == 24


def test_ai_migration_note_is_cited_verified_and_labelled(insight_client, fake_model):
    calls, replies = fake_model
    analysis, _ = analyse(insight_client, 'edgecases')
    url = f'/api/v1/analyses/{analysis}/insight/lifecycle/explain'
    off = insight_client.post(url, json={'target_id': 'log4j-1'}).json()
    assert off['ai']['status'] == 'NOT_AVAILABLE' and off['deterministic']['alternative']
    enable_model(insight_client)
    replies.append(json.dumps({'sentences': [
        {'text': 'Replace the Logger field in BillingAction with an SLF4J logger.', 'cite': ['e0', 'e1']},
        {'text': 'Also update InvoicePrinter which uses Log4j.', 'cite': ['e1']},
        {'text': 'This sentence has no citation.', 'cite': []}]}))
    note = insight_client.post(url, json={'target_id': 'log4j-1'}).json()['ai']
    assert note['status'] == 'AI_GENERATED' and 'AI-generated' in note['label']
    assert [s['text'] for s in note['sentences']] == ['Replace the Logger field in BillingAction with an SLF4J logger.']
    assert note['sentences'][0]['citations'] == ['rule:log4j-1', 'class:com.fixture.edge.legacy.BillingAction']
    reasons = sorted(d['reason'] for d in note['dropped'])
    assert reasons == ['UNCITED_OR_UNKNOWN_CITATION', 'UNVERIFIED_IDENTIFIER']
    sent = [p for path, p in calls if path == '/api/chat'][-1]
    assert 'BillingAction' in sent['messages'][1]['content'] and sent['format']['required'] == ['sentences']
    audit = insight_client.get('/api/v1/security/ai/invocations').json()[0]
    assert audit['metadata']['purpose'] == 'MIGRATION_NOTE' and audit['metadata']['external_transfer'] is False
    assert 'BillingAction' not in json.dumps(audit)          # audit stores no prompt content


def test_ai_off_switch_keeps_deterministic_answer(insight_client, fake_model):
    calls, _ = fake_model
    analysis, _ = analyse(insight_client, 'edgecases')
    enable_model(insight_client)
    insight_client.app.state.config.insight_ai_mode = 'OFF'
    calls.clear()
    note = insight_client.post(f'/api/v1/analyses/{analysis}/insight/lifecycle/explain', json={'target_id': 'log4j-1'}).json()
    assert note['ai']['reason'] == 'INSIGHT_AI_DISABLED' and not calls


def test_cycle_ai_rewrite_must_cite_existing_edges(insight_client, fake_model):
    _, replies = fake_model
    analysis, _ = analyse(insight_client, 'edgecases')
    data = insight_client.get(f'/api/v1/analyses/{analysis}/insight/cycles').json()
    cycle = next(c for g in data['groups'] for c in g['cycles'] if len(c['members']) == 2 and 'legacy' in c['members'][0])
    enable_model(insight_client)
    replies.append(json.dumps({'sentences': [{'text': 'BillingAction and BillingRecord need each other.', 'cite': ['e0', 'e1']},
        {'text': 'PaymentGateway is also involved.', 'cite': ['e0']}]}))
    out = insight_client.post(f'/api/v1/analyses/{analysis}/insight/cycles/explain', json={'target_id': cycle['id']}).json()
    assert out['deterministic'] == cycle['explanation']
    assert [s['text'] for s in out['ai']['sentences']] == ['BillingAction and BillingRecord need each other.']
    assert all(c.startswith('edge:') for c in out['ai']['sentences'][0]['citations'])
    assert out['ai']['dropped'][0]['reason'] == 'UNVERIFIED_IDENTIFIER'


def test_debt_ai_proposal_drops_invented_methods(insight_client, fake_model):
    _, replies = fake_model
    analysis, _ = analyse(insight_client, 'edgecases')
    debt = insight_client.get(f'/api/v1/analyses/{analysis}/insight/debt').json()
    finding = next(f for f in debt['findings'] if f['rule_id'] == 'DEBT-STATIC-STATE' and f['entity_id'].endswith('#CACHE'))
    enable_model(insight_client)
    replies.append(json.dumps({'sentences': [
        {'text': 'Move CACHE into an instance field and update save() and delete() to use it.', 'cite': ['e0', 'e1']},
        {'text': 'Then call flushCache() on shutdown.', 'cite': ['e0']}]}))
    out = insight_client.post(f'/api/v1/analyses/{analysis}/insight/debt/explain', json={'target_id': finding['id']}).json()
    assert [s['text'] for s in out['ai']['sentences']] == ['Move CACHE into an instance field and update save() and delete() to use it.']
    assert out['ai']['dropped'][0]['identifiers'] == ['flushCache()']
    assert any(e.startswith('source:') for e in out['evidence_ids'])       # bytecode outline was supplied as evidence


def test_next_test_ai_steps_are_cited_and_method_checked(insight_client, fake_model):
    _, replies = fake_model
    analysis, _ = analyse(insight_client, 'petclinic')
    tests = insight_client.get(f'/api/v1/analyses/{analysis}/insight/tests').json()
    assert tests['totals']['open'] == 18
    visit = next(s for s in tests['suggestions'] if s['entry_point']['description'].startswith('POST /owners/{ownerId}/pets/{petId}/visits/new'))
    enable_model(insight_client)
    replies.append(json.dumps({'sentences': [
        {'text': 'Open an owner, choose a pet, then submit the Add Visit form with an empty description to reach the hasErrors() branch.', 'cite': ['e0']},
        {'text': 'Then call validateVisit() directly.', 'cite': ['e0']}]}))
    out = insight_client.post(f'/api/v1/analyses/{analysis}/insight/tests/explain', json={'target_id': visit['id']}).json()
    assert len(out['ai']['sentences']) == 1 and out['ai']['dropped'][0]['identifiers'] == ['validateVisit()']
    assert 'entry:' + visit['id'] == out['ai']['sentences'][0]['citations'][0]


def ask(client, analysis, question, **params):
    return client.post(f'/api/v1/analyses/{analysis}/insight/assistant/ask', json={'question': question}, params=params)


def test_assistant_works_without_any_model_and_remembers_the_subject(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    first = ask(insight_client, analysis, 'What does OwnerController do?').json()
    assert first['mode'] == 'LOCAL_EVIDENCE' and first['ai_generated'] is False and 'no model was used' in first['label']
    assert all(c.split(':')[0] in ('class', 'entry', 'finding') for s in first['sentences'] for c in s['cites'])
    second = ask(insight_client, analysis, 'What does it depend on?').json()
    assert second['status'] == 'ANSWERED' and 'OwnerRepository' in second['sentences'][0]['text']
    history = insight_client.get(f'/api/v1/analyses/{analysis}/insight/assistant/history').json()['messages']
    assert [m['role'] for m in history] == ['user', 'assistant', 'user', 'assistant'] and history[0]['content'] == 'What does OwnerController do?'
    assert insight_client.delete(f'/api/v1/analyses/{analysis}/insight/assistant/history').json()['deleted'] == 4
    assert insight_client.get(f'/api/v1/analyses/{analysis}/insight/assistant/history').json()['messages'] == []


def test_assistant_streams_events_and_audits_without_content(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    response = insight_client.post(f'/api/v1/analyses/{analysis}/insight/assistant/chat', json={'question': 'Which controller handles POST /owners/new?'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e['type'] for e in events][:3] == ['start', 'tool_call', 'tool_result'] and events[-1]['type'] == 'done'
    assert any(e['type'] == 'sentence' and 'processCreationForm' in e['text'] for e in events)
    assert response.headers['content-type'].startswith('application/x-ndjson')
    audit = insight_client.get('/api/v1/security/audit').json()
    text = json.dumps(audit)
    assert 'ASSISTANT_QUESTION' in text and 'ASSISTANT_TOOL_CALL' in text and 'processCreationForm' not in text


def test_assistant_refuses_code_changes_and_cannot_determine_unknowns(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    assert ask(insight_client, analysis, 'Refactor OwnerController please').json()['status'] == 'REFUSED'
    unknown = ask(insight_client, analysis, 'What does BillingGateway do?').json()
    assert unknown['status'] == 'CANNOT_DETERMINE' and 'not a class or package' in unknown['sentences'][0]['text']
    assert ask(insight_client, analysis, 'x').status_code == 422


def test_assistant_request_budget(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    insight_client.app.state.config.assistant_requests_per_hour = 2
    assert ask(insight_client, analysis, 'How many classes are there?').status_code == 200
    assert ask(insight_client, analysis, 'How many classes are there?').status_code == 200
    blocked = ask(insight_client, analysis, 'How many classes are there?')
    assert blocked.status_code == 429 and 'budget' in blocked.json()['detail']


def test_model_driven_turn_calls_tools_then_answers_with_verified_citations(insight_client, fake_model):
    calls, replies = fake_model
    analysis, _ = analyse(insight_client, 'petclinic')
    enable_model(insight_client)
    replies.append(json.dumps({'action': 'tool', 'tool': 'get_dependents', 'args': {'name': 'OwnerRepository'}}))
    replies.append(json.dumps({'action': 'answer', 'sentences': [
        {'text': 'OwnerController, PetController and VisitController depend on OwnerRepository.', 'cite': ['r0']},
        {'text': 'PaymentGateway also depends on it.', 'cite': ['r0']},
        {'text': 'It is used everywhere.', 'cite': ['r9']}]}))
    answer = ask(insight_client, analysis, 'Who relies on the owner repository?').json()
    assert answer['mode'] == 'LOCAL_MODEL_ASSISTED' and answer['ai_generated'] is True and 'AI-generated' in answer['label']
    assert [s['text'] for s in answer['sentences']] == ['OwnerController, PetController and VisitController depend on OwnerRepository.']
    assert all(insight_client.get(f'/api/v1/analyses/{analysis}/insight/node', params={'id': c.split(':', 1)[1].split('->')[0]}).status_code == 200 for c in answer['sentences'][0]['cites'] if c.startswith(('class:', 'edge:')))
    assert sorted(r['reason'] for r in answer['removed']) == ['UNCITED_OR_UNKNOWN_CITATION', 'UNKNOWN_IDENTIFIER']
    assert [c['tool'] for c in answer['tool_calls']] == ['get_dependents']
    sent = [p for path, p in calls if path == '/api/chat']
    assert len(sent) == 2 and 'tools' in sent[0]['messages'][1]['content'] and sent[1]['format']['required'] == ['action']
    audits = json.dumps(insight_client.get('/api/v1/security/audit').json())
    assert 'ASSISTANT_TOOL_CALL' in audits and 'source": "model' in audits.replace('\\"', '"')


def test_model_failures_and_unverifiable_answers_fall_back_to_deterministic(insight_client, fake_model):
    _, replies = fake_model
    analysis, _ = analyse(insight_client, 'petclinic')
    off = ask(insight_client, analysis, 'How many classes are there?').json()          # model not enabled in policy
    assert off['mode'] == 'LOCAL_EVIDENCE' and off['gateway']['reason'] == 'MODEL_DISABLED'
    enable_model(insight_client)
    replies.append(json.dumps({'action': 'answer', 'sentences': [{'text': 'There are 99 classes.', 'cite': ['r0']}]}))
    fallback = ask(insight_client, analysis, 'How many classes are there?').json()
    assert fallback['mode'] == 'LOCAL_EVIDENCE' and '24 top-level classes' in fallback['sentences'][0]['text'] and fallback['gateway']['reason'] == 'NO_VERIFIED_SENTENCES'
    insight_client.app.state.config.insight_ai_mode = 'OFF'
    assert ask(insight_client, analysis, 'How many classes are there?').json()['gateway']['reason'] == 'INSIGHT_AI_DISABLED'


def test_model_sentences_with_invented_numbers_are_removed(insight_client, fake_model):
    _, replies = fake_model
    analysis, _ = analyse(insight_client, 'petclinic')
    enable_model(insight_client)
    replies.append(json.dumps({'action': 'tool', 'tool': 'get_dependents', 'args': {'name': 'OwnerRepository'}}))
    replies.append(json.dumps({'action': 'answer', 'sentences': [{'text': '3 classes depend on OwnerRepository.', 'cite': ['r0']}, {'text': '99 classes depend on OwnerRepository.', 'cite': ['r0']}]}))
    answer = ask(insight_client, analysis, 'Who relies on the owner repository?').json()
    assert [s['text'] for s in answer['sentences']] == ['3 classes depend on OwnerRepository.']
    assert [r['reason'] for r in answer['removed']] == ['UNSUPPORTED_NUMBER'] and answer['removed'][0]['numbers'] == ['99']


ENDPOINTS = ['lifecycle', 'cycles', 'metrics', 'debt', 'graph?level=package', 'graph?level=class', 'unresolved', 'node?id=system', 'index', 'tests', 'diagram/hld', 'assistant/tools']


def test_every_insight_endpoint_works_on_petclinic_end_to_end(insight_client):
    analysis, _ = analyse(insight_client, 'petclinic')
    for path in ENDPOINTS:
        response = insight_client.get(f'/api/v1/analyses/{analysis}/insight/{path}')
        assert response.status_code == 200, (path, response.text[:200])
    lld = insight_client.get(f'/api/v1/analyses/{analysis}/insight/diagram/lld', params={'package': 'org.springframework.samples.petclinic.owner'}).json()
    assert lld['status'] == 'AVAILABLE' and len(lld['classes']) == 11
    entry = next(e['id'] for e in lld['entry_points'] if e['text'] == 'POST /owners/new')
    seq = insight_client.get(f'/api/v1/analyses/{analysis}/insight/diagram/sequence', params={'entry_id': entry}).json()
    assert seq['origin'] == 'STATIC' and seq['messages']
    # tenant scoping: another analysis id is simply not found
    assert insight_client.get('/api/v1/analyses/missing/insight/debt').status_code == 404


def test_real_compiled_demo_jar_goes_through_all_views():
    from pathlib import Path
    import tempfile
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from security_helpers import sign_in_owner
    demo = Path(__file__).resolve().parents[2] / 'samples' / 'northstar-commerce.jar'
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(_env_file=None, database_url='sqlite:///' + folder + '/t.db', data_dir=Path(folder), allowed_hosts=['testserver'], scanner_engine='bytecode')
        with TestClient(create_app(settings)) as client:
            sign_in_owner(client)
            project = client.post('/api/v1/projects', json={'name': 'Demo', 'description': 'x'}).json()
            app = client.post('/api/v1/applications', json={'project_id': project['id'], 'name': 'Northstar', 'version': '1'}).json()['id']
            assert client.post(f'/api/v1/applications/{app}/artifact', files={'file': ('n.jar', demo.read_bytes(), 'application/java-archive')}).status_code == 201
            run = client.post(f'/api/v1/applications/{app}/analysis').json()
            import time
            for _ in range(400):
                state = client.get(f"/api/v1/analyses/{run['id']}").json()
                if state['status'] in ('COMPLETED', 'FAILED'):
                    break
                time.sleep(.05)
            assert state['status'] == 'COMPLETED', state
            for path in ENDPOINTS:
                assert client.get(f"/api/v1/analyses/{run['id']}/insight/{path}").status_code == 200, path
            assert client.get(f"/api/v1/analyses/{run['id']}/insight/cycles").json()['groups'] is not None
            answer = ask(client, run['id'], 'How many classes are in the application?').json()
            assert answer['status'] == 'ANSWERED' and '40' in answer['sentences'][0]['text']


def test_source_store_captures_java_entries_and_respects_limits_and_deny(tmp_path):
    import io, zipfile
    from app.config import Settings
    from app.insight.source_store import capture, read
    result = {'classes': [{'id': 'p.A'}, {'id': 'p.B'}], 'bytecode': {'classes': {}}}
    archive = tmp_path / 'src.jar'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('src/main/java/p/A.java', 'package p; class A {}')
        z.writestr('src/main/java/p/B.java', 'x' * 100000)                 # over the per-class limit
        z.writestr('src/main/java/q/Unrelated.java', 'class Unrelated {}')
        z.writestr('../evil/p/A.java', 'class Evil {}')
    config = Settings(_env_file=None, data_dir=tmp_path)
    store = capture(config, 'an1', archive, result)
    assert store['status'] == 'SOURCE_CAPTURED' and list(store['index']) == ['p.A'] and store['skipped_over_limit'] == 1
    result['source_store'] = store
    assert read(config, 'an1', result, 'p.A')['text'] == 'package p; class A {}' and read(config, 'an1', result, 'p.A')['kind'] == 'SOURCE'
    assert read(config, 'an1', result, 'p.B')['kind'] == 'NOT_AVAILABLE'
    deny = Settings(_env_file=None, data_dir=tmp_path, source_store_mode='DENY')
    assert capture(deny, 'an2', archive, result)['status'] == 'DISABLED' and read(deny, 'an1', result, 'p.A')['kind'] == 'DISABLED'


def test_debt_endpoint_returns_rates_and_glossary_defines_each_one(insight_client):
    analysis, _ = analyse(insight_client, 'edgecases')
    debt = insight_client.get(f'/api/v1/analyses/{analysis}/insight/debt').json()
    rates = {r['id']: r for r in debt['rates']['rates']}
    assert rates['cycle-member']['text'] == '7 of 19 classes (36.8%)' and rates['unobserved']['status'] == 'NOT_MEASURED'
    entries = {e['id']: e for e in insight_client.get('/api/v1/insight/glossary').json()['entries']}
    for rate_id, rate in rates.items():
        entry = entries['rate:' + rate_id]
        assert entry['numerator'] == rate['numerator_definition'] and entry['denominator'] == rate['denominator_definition'] and entry['formula']
