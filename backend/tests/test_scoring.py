"""Item 11: readiness and confidence from measured inputs only, with hand-computed expectations."""
import networkx as nx
import pytest
from app.services.modernization import assess_and_rank

WEIGHTS = {'cohesion': .25, 'decoupling': .30, 'cycles': .25, 'database': .20}


def domain(identity, name, classes, internal, outgoing, incoming, repositories=(), shared=()):
    edges = internal + outgoing
    return dict(id=identity, name=name, classes=list(classes), class_count=len(classes),
        metrics=dict(internal_edges=internal, outgoing_edges=outgoing, incoming_edges=incoming,
                     cross_domain_ratio=outgoing / edges if edges else 0.0, internal_cohesion=internal / edges if edges else None),
        database=dict(status='STRUCTURAL_SIGNALS' if repositories else 'UNKNOWN', repositories=list(repositories), shared_repositories=list(shared)))


def fixture():
    graph = nx.DiGraph([('a1', 'a2'), ('a2', 'a3'), ('a3', 'a4'), ('a1', 'b1'), ('a2', 'b1')])
    graph.add_node('b2')
    membership = {'a1': 'D1', 'a2': 'D1', 'a3': 'D1', 'a4': 'D1', 'b1': 'D2', 'b2': 'D2'}
    orders = domain('D1', 'Orders', ['a1', 'a2', 'a3', 'a4'], 3, 2, 0, repositories=['app.r1', 'app.r2'], shared=[dict(repository='app.r1', domains=['D1', 'D2'], entities=[])])
    billing = domain('D2', 'Billing', ['b1', 'b2'], 0, 0, 2)
    issues = [dict(issue_type='GOD_CLASS', entity_id='a1', domain_ids=['D1'])]
    return {a['domain_id']: a for a in assess_and_rank([orders, billing], membership, graph, [], issues, WEIGHTS)}


def test_readiness_is_the_weighted_sum_of_hand_computed_components():
    a = fixture()['D1']
    # cohesion 3/5 = 60; decoupling 100 x (1 - 2/5) = 60; cycles 100; data independence 100 x (1 - 1/2) = 50;
    # boundary size 100 / (1 + 2 / max(1, sqrt(4))) = 50; class concentration 100 - 15 x 1 = 85
    assert a['component_scores'] == {'cohesion': 60.0, 'decoupling': 60.0, 'cycles': 100.0, 'database': 50.0, 'boundary_scale': 50.0, 'class_concentration': 85.0}
    # weights: configured x 0.8 -> .20 .24 .20 .16 plus .12 and .08 (sum 1)
    assert {k: round(v, 4) for k, v in a['weights'].items()} == {'cohesion': .2, 'decoupling': .24, 'cycles': .2, 'database': .16, 'boundary_scale': .12, 'class_concentration': .08}
    # 60x.2 + 60x.24 + 100x.2 + 50x.16 + 50x.12 + 85x.08 = 12 + 14.4 + 20 + 8 + 6 + 6.8
    assert a['readiness_score'] == 67.2 and a['not_measured'] == []


def test_each_component_states_its_numerator_denominator_and_a_named_action():
    d = fixture()['D1']['component_details']
    assert (d['cohesion']['numerator'], d['cohesion']['denominator']) == (3, 5)
    assert d['cohesion']['text'] == "3 of 5 dependency edges leaving the domain's classes stay inside it"
    assert d['cohesion']['how_to_raise'] == ['Pull the 2 outgoing dependencies inside the boundary or remove them, starting with a1 (1), a2 (1).']
    assert (d['database']['numerator'], d['database']['denominator']) == (1, 2)
    assert d['database']['how_to_raise'] == ['Give one domain ownership of r1 with Billing.']
    assert d['class_concentration']['how_to_raise'] == ['Split a1.']
    assert d['cycles']['how_to_raise'] == []


def test_unmeasured_inputs_are_excluded_and_the_remaining_weights_renormalized():
    a = fixture()['D2']
    # no dependency edges leave or stay inside Billing and it has no repository
    assert {e['input'] for e in a['not_measured']} == {'cohesion', 'decoupling', 'database'}
    assert set(a['component_scores']) == {'cycles', 'boundary_scale', 'class_concentration'}
    # remaining weights .20, .12, .08 (sum .40) scale to .5, .3, .2
    assert {k: round(v, 4) for k, v in a['weights'].items()} == {'cycles': .5, 'boundary_scale': .3, 'class_concentration': .2}
    assert a['readiness_score'] == 100.0
    assert 'Not measured:' in a['explanation'] and 'no repository class or data-access reference was found' in a['explanation']
    assert 'database' not in a['component_details']


def test_god_class_input_is_not_measured_when_the_view_has_no_god_class_findings():
    graph = nx.DiGraph([('a', 'b')])
    result = assess_and_rank([domain('D', 'Only', ['a', 'b'], 1, 0, 0)], {'a': 'D', 'b': 'D'}, graph, [], [], WEIGHTS, boundary_available=False, god_class_available=False)[0]
    assert 'class_concentration' not in result['component_scores'] and result['boundary_violations'] is None
    assert any(e['input'] == 'class_concentration' for e in result['not_measured'])


def test_database_signal_without_repositories_is_not_scored_as_65_or_45():
    graph = nx.DiGraph([('a', 'b')])
    d = domain('D', 'Only', ['a', 'b'], 1, 0, 0)
    d['database']['status'] = 'STRUCTURAL_SIGNALS'
    result = assess_and_rank([d], {'a': 'D', 'b': 'D'}, graph, [], [], WEIGHTS)[0]
    assert 'database' not in result['component_scores']
    assert not any(v in (45.0, 65.0) for v in result['component_scores'].values())


def test_runtime_persistence_is_the_share_of_resources_called_by_one_domain_only():
    from app.services.runtime.intelligence import derive
    from test_runtime_mapping_details import events, span, code
    db = {'db.system': 'postgresql', 'server.address': 'db.internal', 'db.namespace': 'app'}
    static = dict(classes=[{'id': 'x.A', 'domain_id': 'D1'}, {'id': 'x.B', 'domain_id': 'D1'}, {'id': 'y.C', 'domain_id': 'D2'}],
                  domains=[{'id': 'D1'}, {'id': 'D2'}],
                  modernization=[dict(domain_id=i, domain_name=n, readiness_score=80, recommended_order=k, wave=k, risks=[]) for k, (i, n) in enumerate([('D1', 'One'), ('D2', 'Two')], 1)])
    coverage = dict(domain_observations=[dict(id='D1', observed=2, total=2), dict(id='D2', observed=1, total=1)])
    runtime = dict(nodes=[{'id': 'n1', 'domain_id': 'D1'}, {'id': 'n2', 'domain_id': 'D1'}, {'id': 'n3', 'domain_id': 'D2'}],
                   edges=[dict(id='e1', source='n1', target='n2', call_count=3, error_count=0), dict(id='e2', source='n1', target='n3', call_count=1, error_count=0)])
    ev = events(span(1, 'q', attrs={**db, **code('x.A'), 'db.collection.name': 'orders'}), span(2, 'q', attrs={**db, **code('y.C'), 'db.collection.name': 'orders'}, trace='2' * 32),
                span(3, 'q', attrs={**db, **code('y.C'), 'db.collection.name': 'payments'}, trace='3' * 32))
    result = derive(static, runtime, coverage, ev, .6, {'cohesion': .6, 'cycles': .25, 'persistence': .15})
    one, two = result['modernization']
    # One: cohesion 3 internal of 4 calls = 75, cycles 100, persistence 0 of 1 resources unshared = 0 -> 75x.6 + 100x.25 + 0x.15
    assert one['component_scores'] == {'cohesion': 75.0, 'cycles': 100, 'persistence': 0.0} and one['runtime_score'] == 70.0
    assert one['combined_score'] == 76.0          # .6 x 80 + .4 x 70
    # Two: no outgoing calls, so cohesion and cycles are not measured; persistence = payments only -> 1 of 2 = 50; no runtime score without calls
    assert two['component_scores'] == {'persistence': 50.0} and two['runtime_score'] is None and two['combined_score'] == 80
    assert [n['input'] for n in two['not_measured']] == ['cohesion', 'cycles']
    assert 25 not in one['component_scores'].values()
