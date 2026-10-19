"""WP6: cycles on fixtures with known answers (2-class, 3-class, package-level, overlapping, self-loop)."""
from collections import Counter
from app.insight.cycles import analyse
from app.insight.model import InsightModel
from app.services.engine import analyze
from app.config import Settings
from insight_fixtures import model

A, B = 'com.fixture.edge.cycle.a.', 'com.fixture.edge.cycle.b.'


def groups(level, m=None):
    return [g for g in analyse(m or model('edgecases'))['groups'] if g['level'] == level]


def test_overlapping_class_cycles_are_listed_in_order_with_their_edges():
    group = next(g for g in groups('CLASS') if A + 'Order' in g['members'])
    assert group['members'] == sorted([A + 'Address', A + 'Customer', A + 'Order', A + 'Region', B + 'Invoice'])
    paths = [[n.rsplit('.', 1)[-1] for n in c['members']] for c in group['cycles']]
    # Each cycle starts at its alphabetically first fully qualified member.
    assert paths == [['Customer', 'Order'], ['Order', 'Invoice'], ['Address', 'Region', 'Customer']]
    assert group['overlapping'] is True
    two = group['cycles'][0]
    order_to_customer = next(e for e in two['edges'] if e['source'] == A + 'Order')
    assert 'FIELD_TYPE' in order_to_customer['edge_types']
    assert 'field Order.customer has type Customer' in [r['text'] for r in order_to_customer['references']]
    customer_to_order = next(e for e in two['edges'] if e['source'] == A + 'Customer')
    assert 'GENERIC_TYPE' in customer_to_order['edge_types']
    assert two['explanation']['plain'].startswith('Customer cannot be changed without also checking Order, because each uses the other')
    three = group['cycles'][2]
    assert three['explanation']['technical'].startswith('Cycle Address → Region → Customer → Address:')
    assert group['packages'] == ['com.fixture.edge.cycle.a', 'com.fixture.edge.cycle.b']


def test_cut_candidates_are_ranked_with_reasons_and_marked_for_review():
    group = next(g for g in groups('CLASS') if A + 'Order' in g['members'])
    top = group['cut_candidates'][0]
    # Every edge of the three cycles belongs to exactly one of them, so no single cut breaks the group.
    assert not any(c['breaks_whole_group'] for c in group['cut_candidates'])
    assert all(c['label'].startswith('Suggestion only') for c in group['cut_candidates'])
    assert 'appears in' in top['why'] and top['rank'] == 1
    assert Counter(c['cycles_broken'] for c in group['cut_candidates'])[1] == len(group['cut_candidates'])


def test_two_class_cycle_in_one_package_names_both_layers():
    group = next(g for g in groups('CLASS') if 'com.fixture.edge.legacy.BillingAction' in g['members'])
    assert group['size'] == 2 and group['packages'] == ['com.fixture.edge.legacy']
    assert group['layers'] == ['DOMAIN', 'PRESENTATION'] and group['severity'] == 'HIGH'
    edges = {e['source'].rsplit('.', 1)[-1]: e for e in group['cycles'][0]['edges']}
    assert 'TYPE_REFERENCE' in edges['BillingAction']['edge_types']          # BillingRecord.class constant
    assert 'METHOD_CALL' in edges['BillingRecord']['edge_types']             # BillingRecord.touch -> oldApi
    assert group['cut_candidates'][0]['breaks_whole_group'] is True


def test_package_level_cycle_lists_class_pairs():
    [group] = groups('PACKAGE')
    assert group['members'] == ['com.fixture.edge.cycle.a', 'com.fixture.edge.cycle.b']
    edge = next(e for e in group['cycles'][0]['edges'] if e['source'] == 'com.fixture.edge.cycle.b')
    assert [(p['source'], p['target']) for p in edge['class_pairs']] == [(B + 'Invoice', A + 'Order')]


def test_self_loop_and_nested_classes_are_not_cycles():
    members = {m for g in groups('CLASS') for m in g['members']}
    assert 'com.fixture.edge.model.ItemService' not in members            # ItemService <-> ItemService$1 folded
    assert not any(g['size'] == 1 for g in analyse(model('edgecases'))['groups'])
    assert analyse(model('edgecases'))['nested_or_self_references_ignored'] > 0


def test_petclinic_has_no_cycles_and_agrees_with_engine():
    result = analyse(model('petclinic'))
    assert result['groups'] == []
    assert model('petclinic').result['cycles'] == []


def test_runtime_only_edge_closes_a_cycle_and_is_labelled():
    classes = [dict(fqn=f'p.{n}', simple_name=n, package_name='p', annotations=[], method_count=1, field_count=0) for n in ('X', 'Y')]
    result = analyze(classes, [dict(source='p.X', target='p.Y', dependency_type='METHOD_CALL')], Settings(_env_file=None))
    runtime = dict(runtime_graph=dict(nodes=[dict(id='p.X', static_id='p.X'), dict(id='p.Y', static_id='p.Y')],
        edges=[dict(source='p.Y', target='p.X', call_count=4)]))
    [group] = analyse(InsightModel('rt', result, runtime))['groups']
    back = next(e for e in group['cycles'][0]['edges'] if e['source'] == 'p.Y')
    assert back['sources'] == ['runtime'] and back['runtime_calls'] == 4
