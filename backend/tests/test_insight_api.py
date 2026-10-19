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
