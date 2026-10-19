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
