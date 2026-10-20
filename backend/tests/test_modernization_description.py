"""Item 3: every modernization item is described with its exact target, measured state, reason, named blockers and order."""
import re
import pytest
from test_modernization import pure
from insight_fixtures import snapshot

BANNED = re.compile(r'leverage|seamless|robust|comprehensive|holistic|streamline|unlock|it is important to note', re.I)


@pytest.fixture(scope='module')
def petclinic():
    doc, facts, evidence, version, static = pure(snapshot('petclinic'), observations=.5, reviewed=True)
    return doc


def test_every_assessment_has_a_description_naming_the_domain_and_its_measured_values(petclinic):
    assert len(petclinic['assessments']) == 5
    for a in petclinic['assessments']:
        d = a['item_description']
        text = d['text']
        assert a['domain_name'] in text and d['title'].startswith(a['domain_name'] + ':')
        assert str(a['structural_score']) in text and str(a['confidence_score']) in text
        assert f"Wave {a['wave']} of {len(petclinic['waves'])}" in text if 'wave' in a else True
        assert f"of {a['runtime_coverage']['classes']['total']}" in text.replace('class', 'class ').replace('  ', ' ') or 'not measured' in text
        assert not BANNED.search(text)


def test_owner_domain_is_described_with_its_classes_packages_dependencies_and_order(petclinic):
    a = next(x for x in petclinic['assessments'] if x['domain_name'] == 'Type Owner')
    d = a['item_description']
    assert d['target']['class_count'] == 3 and d['target']['packages'] == ['org.springframework.samples.petclinic.owner']
    assert 'Type Owner has 3 classes in 1 package: org.springframework.samples.petclinic.owner.' in d['current_state'][0]
    assert 'Runtime: 2 of 3 classes observed (66.67%).' in d['current_state']
    assert 'data independence 0.0 (1 of 1 repositories used by the domain are also used by another domain)' in d['current_state'][1]
    assert d['order'] == ['Wave 4 of 5.', 'Depends on Vet (2 dependency edges, wave 2).', 'Used by Owner Visit (7 dependency edges, wave 5).']
    assert any('PetType -> NamedEntity' in line for line in d['current_state'])


def test_decision_action_names_the_numbers_not_a_generic_instruction(petclinic):
    decision = next(x for x in petclinic['decisions'] if x['kind'] == 'COLLECT_MORE_EVIDENCE')
    domain = next(a for a in petclinic['assessments'] if a['domain_id'] == decision['domain_id'])
    assert domain['domain_name'] in decision['action'] and re.search(r'observed \d+ of \d+ classes', decision['action'])
    assert 'Exercise unobserved entry points and capture a successor architecture version.' not in decision['action']


def test_blockers_are_named_with_their_meaning_and_subjects(petclinic):
    a = next(x for x in petclinic['assessments'] if x['domain_name'] == 'Type Owner')
    blockers = {b['code']: b for b in a['item_description']['blockers']}
    assert blockers['RUNTIME_OBSERVATION_GAP']['detail'] == 'Selected sessions observed 2 of 3 classes of Type Owner (66.67%, minimum 80%).'
    assert blockers['RUNTIME_OBSERVATION_GAP']['subjects'] == ['Type Owner']
    assert blockers['PINNED_SOURCE_AND_PASSING_BUILD']['resolve'].startswith('Record the repository commit')


def test_waves_state_their_members_dependencies_and_the_cost_indexes_that_ordered_them(petclinic):
    first = petclinic['waves'][0]
    assert first['reason'].startswith('Wave 1: ') and 'lowest heuristic cost index' in first['reason']
    names = {a['domain_id']: a['domain_name'] for a in petclinic['assessments']}
    assert all(names[d] in first['reason'] for d in first['domains'])
    costs = {a['domain_name']: a['cost_index'] for a in petclinic['assessments']}
    for name in ('System Configuration', 'Vet', 'Application Clinic'):
        assert f'{name} {round(costs[name], 1)}' in first['reason']


def test_cost_index_formula_shows_the_inputs_and_matches_the_value(petclinic):
    for a in petclinic['assessments']:
        inputs = a['cost_inputs']
        base = inputs['classes'] / 20 + 1.5 * inputs['boundary_pairs'] + 8 * inputs['shared_repositories'] + 6 * inputs['god_classes'] + 12 * inputs['cross_domain_cycles']
        gap = round(max(0, 100 - a['observation']['observed'] * 100 / a['observation']['total']) / 25, 1)
        assert a['cost_index'] == pytest.approx(round(base, 1) + gap, abs=.11)
        assert f"{inputs['boundary_pairs']} crossing pairs" in a['item_description']['formulas'][-1]['formula']


def test_static_sequence_reason_names_dependencies_with_class_pair_counts():
    static = snapshot('petclinic')
    by = {a['domain_name']: a for a in static['modernization']}
    domain_of = {c['id']: c['domain_id'] for c in static['classes']}
    names = {d['id']: d['name'] for d in static['domains']}
    pairs = {(e['source'], e['target']) for e in static['edges'] if e['source'] in domain_of and e['target'] in domain_of and domain_of[e['source']] != domain_of[e['target']]}
    count = lambda a, b: sum(1 for s, t in pairs if names[domain_of[s]] == a and names[domain_of[t]] == b)   # independent hand count
    owner_to_vet, visit_to_owner = count('Type Owner', 'Vet'), count('Owner Visit', 'Type Owner')
    assert (owner_to_vet, visit_to_owner) == (1, 3)
    owner = by['Type Owner']['sequence_reason']
    assert f"Type Owner depends on Vet ({owner_to_vet} class pair, wave {by['Vet']['wave']})" in owner
    assert f"It is used by Owner Visit ({visit_to_owner} class pairs, wave {by['Owner Visit']['wave']})" in owner
    assert 'Dependency-first wave: prerequisites appear earlier' not in owner
    assert 'depends on no other candidate domain' in by['System Configuration']['sequence_reason']
