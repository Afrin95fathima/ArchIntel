"""Improvement estimate and version comparison: derived only from a version's own coverage, facts and suggestions."""
from types import SimpleNamespace
import pytest
from app.evidence import improvement
from app.modernization.thresholds import MIN_OBSERVED_CLASS_PERCENTAGE
from test_evidence import capture, make
from test_runtime import live, span


def version(observed, unobserved_a, unobserved_b, sessions=('s1',), review=True):
    domain = lambda i, name, classes: dict(id=i, name=name, classes=classes)
    return SimpleNamespace(
        manifest=dict(runtime_session_ids=list(sessions), domain_review={'reason': 'r'} if review else None),
        document=dict(domains=[domain('d1', 'Owners', ['a.Owner', 'a.Pet', 'a.OwnerController']), domain('d2', 'Vets', ['b.Vet', 'b.VetController'])],
                      coverage=dict(domain_observations=[dict(id='d1', name='Owners', observed=observed, total=3, unobserved_classes=unobserved_a), dict(id='d2', name='Vets', observed=1, total=2, unobserved_classes=unobserved_b)])))


FACTS = [dict(source='a.OwnerController', target='a.Owner', classification='STATIC_ONLY'), dict(source='a.OwnerController', target='a.Pet', classification='STATIC_ONLY'),
         dict(source='b.VetController', target='b.Vet', classification='DYNAMIC_ONLY')]
GAPS = [dict(id='g1', kind='ENTRY_POINT', state='OPEN', text='Exercise a.OwnerController.showOwner and capture method identity evidence.'),
        dict(id='g2', kind='ENTRY_POINT', state='EXERCISED', text='Exercise b.VetController.list and capture method identity evidence.'),
        dict(id='g3', kind='DEPENDENCY', state='OPEN', text='Exercise the path a.X -> a.Y.')]


def test_the_target_is_the_one_the_plan_uses():
    assert improvement.TARGET == MIN_OBSERVED_CLASS_PERCENTAGE == 80
    assert improvement.needed_classes(1, 3) == 2 and improvement.needed_classes(4, 5) == 0 and improvement.needed_classes(0, 10) == 8 and improvement.needed_classes(0, 0) == 0


def test_each_domain_reports_how_many_more_classes_reach_the_target():
    out = improvement.build(version(1, ['a.Owner', 'a.Pet'], ['b.Vet']), FACTS, GAPS)
    owners, vets = out['domains']
    assert (owners['name'], owners['observed'], owners['total'], owners['classes_needed'], owners['met']) == ('Owners', 1, 3, 2, False)
    assert (vets['classes_needed'], vets['unobserved_classes']) == (1, ['b.Vet'])
    assert out['ready'] is False and out['target_percentage'] == 80


def test_a_suggestion_counts_only_unobserved_classes_reachable_by_static_edges_and_only_when_open():
    out = improvement.build(version(1, ['a.Owner', 'a.Pet'], ['b.Vet']), FACTS, GAPS)
    assert [s['entry_class'] for s in out['suggestions']] == ['a.OwnerController']          # exercised and non-entry suggestions are left out
    top = out['suggestions'][0]
    assert top['up_to_new_classes'] == 2 and top['reachable_unobserved'] == ['a.Owner', 'a.Pet'] and top['per_domain'] == {'Owners': 2}
    owners, vets = out['domains']
    assert owners['reachable_by_open_suggestions'] == 2 and owners['can_reach_target'] is True
    assert vets['reachable_by_open_suggestions'] == 0 and vets['can_reach_target'] is False      # runtime-only edges are not a code path


def test_it_says_when_the_plan_conditions_are_missing_instead_of_estimating():
    out = improvement.build(version(0, ['a.Owner', 'a.Pet', 'a.OwnerController'], ['b.Vet', 'b.VetController'], sessions=(), review=False), FACTS, GAPS)
    assert [c['met'] for c in out['conditions']] == [False, False]
    assert 'No runtime session' in out['conditions'][0]['text'] and 'were not reviewed' in out['conditions'][1]['text']
    assert all(d['observed'] == 0 and d['classes_needed'] > 0 for d in out['domains'])
    assert out['ready'] is False and len(out['limits']) == 3


def test_ready_only_when_conditions_and_every_domain_meet_the_target():
    v = version(3, [], [])
    v.document['coverage']['domain_observations'][1].update(observed=2, unobserved_classes=[])
    assert improvement.build(v, FACTS, GAPS)['ready'] is True


def test_api_returns_the_estimate_for_a_saved_version(live):
    v = make(live)
    out = live.get(f"/api/v1/architecture-versions/{v['id']}/improvement")
    assert out.status_code == 200
    body = out.json()
    assert body['target_percentage'] == 80 and body['conditions'][0]['met'] is False and body['domains'] and body['ready'] is False


def test_comparison_lists_changes_in_coverage_facts_and_suggestions(live):
    first = make(live)
    second = make(live, [capture(live, span(1, 'app.a.A'), span(2, 'app.b.B', 1))])
    out = live.get(f"/api/v1/architecture-versions/{first['id']}/compare/{second['id']}")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body['runtime_sessions'] == dict(before=0, after=1) and body['same_domain_review'] is True
    assert body['facts']['after']['STATIC_AND_DYNAMIC'] > body['facts']['before']['STATIC_AND_DYNAMIC'] and body['facts']['changed_total'] >= 1
    assert body['moved_total'] == 0 and body['renamed_domains'] == []
    assert body['domains'] and all({'before', 'after'} <= set(d) for d in body['domains'])
    assert body['percentage_point_delta']['classes'] is not None


def test_comparison_across_a_domain_review_lists_moves_and_renames_and_withholds_the_domain_delta(live):
    plain = make(live)
    domains = live.get(f"/api/v1/analyses/{live.run_id}/export").json()['domains']
    edits = [dict(id=d['id'], name=d['name'] + ' reviewed' if i == 0 else d['name'], classes=d['classes']) for i, d in enumerate(domains)]
    if len(domains) > 1 and len(domains[0]['classes']) > 1:
        edits[1]['classes'] = edits[1]['classes'] + [edits[0]['classes'][0]]
        edits[0]['classes'] = edits[0]['classes'][1:]
    reviewed = make(live, domain_edits=edits, review_reason='test')
    body = live.get(f"/api/v1/architecture-versions/{plain['id']}/compare/{reviewed['id']}").json()
    assert body['same_domain_review'] is False and body['percentage_point_delta']['domains'] is None
    assert body['renamed_domains'] and body['renamed_domains'][0]['to_name'].endswith(' reviewed')
    assert body['moved_total'] == len(body['moved_classes']) and (body['moved_total'] >= 1 or len(domains) < 2)


def test_twin_reports_the_plan_threshold_so_the_page_does_not_repeat_it(live):
    v = make(live)
    assert live.get(f"/api/v1/architecture-versions/{v['id']}/twin").json()['required_observed_class_percentage'] == MIN_OBSERVED_CLASS_PERCENTAGE
