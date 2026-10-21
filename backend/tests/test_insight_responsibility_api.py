"""Responsibility analysis through the API: real pipeline on the compiled PetClinic fixture."""
import json
from insight_api import analyse, insight_client, fake_model, enable_model  # noqa: F401

OWNER = 'org.springframework.samples.petclinic.owner.OwnerController'


def url(analysis, path=''):
    return f'/api/v1/analyses/{analysis}/insight/responsibilities{path}'


def test_summary_describes_the_analysis_and_ties_it_to_the_analyzed_artifact(insight_client):
    analysis, _ = analyse(insight_client)
    body = insight_client.get(url(analysis)).json()
    assert body['status'] == 'AVAILABLE' and 'components' not in body and 'evidence' not in body
    exported = insight_client.get(f'/api/v1/analyses/{analysis}/export').json()
    meta = body['analysis_metadata']
    assert meta['artifact_sha256'] == exported['artifact']['sha256'] and meta['source_revision'] == exported['artifact']['sha256']
    assert meta['analyzed_class_count'] == body['summary']['classes'] == 24 and meta['engine_version'] and meta['rules_version']
    assert body['summary']['evidence_rejected'] == 0 and set(body['taxonomy']['nonfunctional']) >= {'SECURITY', 'PERFORMANCE', 'RELIABILITY', 'OBSERVABILITY'}
    assert {c['name'] for c in body['capabilities']} == {d['name'] for d in exported['domains']}
    assert body['limitations'] and all(r['consequence_status'] == 'INFERRED' for r in body['risks'])


def test_components_can_be_filtered_by_classification_concern_status_capability_and_text(insight_client):
    analysis, _ = analyse(insight_client)
    everything = insight_client.get(url(analysis, '/components'), params={'limit': 500}).json()
    assert everything['total'] == 24 and len(everything['items']) == 24
    mixed = insight_client.get(url(analysis, '/components'), params={'primary': 'MIXED'}).json()
    assert mixed['total'] >= 1 and all(i['primary_classification'] == 'MIXED' for i in mixed['items']) and OWNER in {i['fqn'] for i in mixed['items']}
    security = insight_client.get(url(analysis, '/components'), params={'concern': 'SECURITY', 'status': 'DETECTED'}).json()
    assert OWNER in {i['fqn'] for i in security['items']} and all(any(l['category'] == 'SECURITY' and l['status'] == 'DETECTED' for l in i['non_functional']) for i in security['items'])
    entry = insight_client.get(url(analysis, '/components'), params={'functional': 'API_AND_APPLICATION_ENTRY'}).json()
    assert all(i['fqn'].endswith('Controller') for i in entry['items']) and entry['total'] >= 3
    capability = everything['items'][0]['capability']['id']
    in_capability = insight_client.get(url(analysis, '/components'), params={'capability': capability}).json()
    assert 0 < in_capability['total'] < 24 and all(i['capability']['id'] == capability for i in in_capability['items'])
    assert insight_client.get(url(analysis, '/components'), params={'q': 'vetrepository'}).json()['total'] == 1


def test_components_are_paginated_in_a_stable_order(insight_client):
    analysis, _ = analyse(insight_client)
    first = insight_client.get(url(analysis, '/components'), params={'limit': 10, 'offset': 0}).json()
    second = insight_client.get(url(analysis, '/components'), params={'limit': 10, 'offset': 10}).json()
    assert first['total'] == second['total'] == 24 and len(first['items']) == len(second['items']) == 10
    names = [i['fqn'] for i in first['items'] + second['items']]
    assert names == sorted(names) and len(set(names)) == 20


def test_invalid_filter_values_are_rejected_not_ignored(insight_client):
    analysis, _ = analyse(insight_client)
    assert insight_client.get(url(analysis, '/components'), params={'status': 'MAYBE'}).status_code == 422
    assert insight_client.get(url(analysis, '/components'), params={'limit': 0}).status_code == 422
    assert insight_client.get(url(analysis, '/components'), params={'limit': 5000}).status_code == 422


def test_component_detail_resolves_evidence_dependencies_and_risks(insight_client):
    analysis, _ = analyse(insight_client)
    body = insight_client.get(url(analysis, '/component'), params={'id': OWNER}).json()
    security = next(l for l in body['non_functional_responsibilities'] if l['category'] == 'SECURITY')
    assert security['status'] == 'DETECTED' and security['evidence'][0]['location']['start_line'] and 'WebDataBinder' in security['evidence'][0]['text'] and security['limit']
    assert body['dependency_details'] and all(d['source'] == OWNER for d in body['dependency_details'])
    assert any(m['labels'] for m in body['methods']) and body['source_location']['basis'].startswith('DERIVED')
    assert body['capability_implications'] and all(c['implications'] for c in body['capability_implications'])


def test_unknown_component_and_unknown_analysis_return_plain_errors(insight_client):
    analysis, _ = analyse(insight_client)
    missing = insight_client.get(url(analysis, '/component'), params={'id': 'no.such.Class'})
    assert missing.status_code == 404 and missing.json()['detail'] == 'Component not found in this analysis.'
    assert insight_client.get(url('00000000-0000-0000-0000-000000000000')).status_code == 404


def test_risks_can_be_filtered_and_every_risk_names_affected_components_and_what_to_do(insight_client):
    analysis, _ = analyse(insight_client)
    everything = insight_client.get(url(analysis, '/risks')).json()
    assert everything['total'] >= 3
    for risk in everything['items']:
        assert risk['affected_components'] and risk['investigate'] and risk['potential_impact'] and risk['confidence']['calibrated'] is False and risk['detection_status'] in ('DETECTED', 'INFERRED')
    data = insight_client.get(url(analysis, '/risks'), params={'category': 'DATA_INTEGRITY'}).json()
    assert data['items'] and all(r['category'] == 'DATA_INTEGRITY' for r in data['items'])
    runtime = insight_client.get(url(analysis, '/risks'), params={'runtime': 'true'}).json()
    assert all(r['runtime_validation_required'] for r in runtime['items'])
    assert insight_client.get(url(analysis, '/risks'), params={'severity': 'HIGH'}).json()['items'][0]['severity'] == 'HIGH'


def test_the_ai_explanation_is_optional_cited_and_drops_invented_classes(insight_client, fake_model):
    calls, replies = fake_model
    analysis, _ = analyse(insight_client)
    target = {'target_id': OWNER}
    off = insight_client.post(url(analysis, '/explain'), json=target).json()
    assert off['ai']['status'] == 'NOT_AVAILABLE' and not calls
    plain = insight_client.get(url(analysis, '/component'), params={'id': OWNER}).json()
    assert plain['primary_classification'] == 'MIXED'                       # deterministic result is unaffected by the model
    enable_model(insight_client)
    replies.append(json.dumps({'sentences': [
        {'text': 'OwnerController restricts which request fields can be bound.', 'cite': ['e0', 'e1']},
        {'text': 'GhostService also processes payments for it.', 'cite': ['e1']},
        {'text': 'It is certainly secure.', 'cite': []}]}))
    note = insight_client.post(url(analysis, '/explain'), json=target).json()['ai']
    assert note['status'] == 'AI_GENERATED' and 'AI-generated' in note['label']
    assert [s['text'] for s in note['sentences']] == ['OwnerController restricts which request fields can be bound.']
    assert {d['reason'] for d in note['dropped']} == {'UNCITED_OR_UNKNOWN_CITATION', 'UNVERIFIED_IDENTIFIER'}
    assert insight_client.post(url(analysis, '/explain'), json={'target_id': 'no.such.Class'}).status_code == 404


def test_the_deterministic_result_is_identical_with_and_without_a_model(insight_client, fake_model):
    analysis, _ = analyse(insight_client)
    before = insight_client.get(url(analysis)).json()
    enable_model(insight_client)
    after = insight_client.get(url(analysis)).json()
    assert before == after
