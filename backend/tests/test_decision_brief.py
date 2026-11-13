"""Item 8: the decision brief is built from data; every number in its text is in the fact table and equals the API value."""
import copy
from uuid import uuid4
import pytest
from app.modernization import engine, validation
from app.modernization.brief import unregistered_numbers, _texts, NUMBER, Facts, _list
from app.insight import debt
from test_modernization import pure
from insight_fixtures import snapshot, model

SECTIONS = ['decision', 'recommendation', 'options', 'scope', 'blockers', 'nonfunctional', 'risks', 'confidence', 'unknowns']


@pytest.fixture(scope='module')
def petclinic():
    return pure(snapshot('petclinic'), observations=.5, reviewed=True)


@pytest.fixture(scope='module')
def edgecases():
    return pure(snapshot('edgecases'), observations=.5, reviewed=True)


def facts(brief):
    return {f['id']: f for f in brief['facts']}


@pytest.mark.parametrize('fixture', ['petclinic', 'edgecases'])
def test_every_number_in_the_text_is_in_the_fact_table_and_the_plan_validates(fixture, request):
    doc, plan_facts, evidence, *_ = request.getfixturevalue(fixture)
    brief = doc['decision_brief']
    assert [s['id'] for s in brief['sections']] == SECTIONS
    assert unregistered_numbers(brief) == [] and brief['numbers_check']['unregistered'] == []
    assert len({f['id'] for f in brief['facts']}) == len(brief['facts']) > 10
    for fact in brief['facts']:
        assert isinstance(fact['value'], (int, float)) and fact['source'] and fact['label'] and float(fact['text']) == fact['value']
    assert validation.validate(doc, plan_facts, evidence)['status'] == 'VALIDATED'


def test_fact_values_equal_the_api_values(petclinic):
    doc, *_ = petclinic
    f = facts(doc['decision_brief'])
    static = snapshot('petclinic')
    assert f['classes']['value'] == static['summary']['class_count'] == 24 and f['packages']['value'] == static['summary']['package_count'] == 5
    assert f['domains']['value'] == len(static['domains']) == len(doc['assessments'])
    assert f['cross_domain_edges']['value'] == sum(r['edge_count'] for r in doc['domain_dependency_matrix']['rows']) == 15
    rates = {r['id']: r for r in debt.detect(model('petclinic'))['rates']['rates']}      # what /insight/debt returns without a runtime session
    shown = [rate_id for rate_id in rates if 'rate_' + rate_id + '_n' in f]
    assert {'entity-in-controller', 'cross-domain-edges', 'any-class'} <= set(shown)
    for rate_id in shown:
        if rate_id in ('unobserved', 'entry-points-unobserved'):
            continue                                                  # runtime rates are checked against hand counts below
        rate = rates[rate_id]
        assert f['rate_' + rate_id + '_n']['value'] == rate['numerator'] and f['rate_' + rate_id + '_d']['value'] == rate['denominator'] and f['rate_' + rate_id + '_pct']['value'] == rate['percentage']
    observed = sum(a['runtime_coverage']['classes']['observed'] for a in doc['assessments'])
    assert f['observed_classes']['value'] == observed == 12 and f['observed_total']['value'] == 24
    _, _, _, version, _ = petclinic
    unobserved = {c for d in version.document['coverage']['domain_observations'] for c in d['unobserved_classes']}
    assert len(unobserved) == 12                                                             # 24 classes, half observed
    entries = model('petclinic').entry_points['items']
    assert len(entries) == 18 and f['entry_points']['value'] == 18
    assert f['unobserved_entry_points']['value'] == sum(1 for e in entries if e['handler_class'] in unobserved)      # hand count from the handler classes
    assert f['rate_unobserved_n']['value'] == 12 and f['rate_unobserved_d']['value'] == 24 and f['rate_unobserved_pct']['value'] == 50.0
    assert f['confidence_min']['value'] == min(a['confidence_score'] for a in doc['assessments']) and f['confidence_max']['value'] == max(a['confidence_score'] for a in doc['assessments'])


def test_petclinic_text_names_domains_classes_and_measured_percentages(petclinic):
    doc, *_ = petclinic
    text = {s['id']: ' '.join(s['paragraphs']) for s in doc['decision_brief']['sections']}
    assert 'Type Owner' in text['decision'] and '24 classes' in text['decision'] and '5 candidate domains' in text['decision']
    assert 'Controller dependencies on entities: 8 of 15 dependency edges (53.3%).' in text['risks']
    assert 'Cross-domain dependencies: 7 of 35 dependency edges (20.0%).' in text['risks']
    assert 'Runtime sessions observed 12 of 24 classes (50.0%).' in text['confidence']
    assert 'PetClinicApplication.main()' in text['scope'] and '18 entry points were detected' in text['scope']
    assert 'Spring Boot aging (1 class)' in text['options'] and 'Class files target Java 17 (aging) in 24 classes' in text['options']
    assert 'RUNTIME_OBSERVATION_GAP (blocker) affects 5 of 5 domains' in text['blockers'] and 'PINNED_SOURCE_AND_PASSING_BUILD' in text['blockers']


def test_every_paragraph_names_something_or_gives_a_number(petclinic, edgecases):
    for doc in (petclinic[0], edgecases[0]):
        brief = doc['decision_brief']
        names = set(brief['names']) | {a['domain_name'] for a in doc['assessments']}
        for section in brief['sections']:
            for paragraph in section['paragraphs']:
                assert NUMBER.search(paragraph) or any(n in paragraph for n in names), (section['id'], paragraph)


def test_cycles_and_shared_data_make_modular_monolith_the_recommendation_with_the_named_domains(edgecases):
    doc, *_ = edgecases
    brief = doc['decision_brief']
    blocked = [a for a in doc['assessments'] if a['hard_blockers']]
    rec = brief['recommendation']
    if blocked:
        assert rec['option'] == 'MODULAR_MONOLITH' and all(a['domain_name'] in rec['rationale'] for a in blocked[:4])
        assert f"{len(blocked)} of {len(doc['assessments'])} domains have hard blockers" in rec['rationale']
    assert brief['strategy_fit']['recommendation'] == rec['option'] and brief['strategy_fit']['rule'] == rec['rule']
    assert brief['automatic_winner'] is None and brief['selected_strategy'] == 'MODULAR_MONOLITH'


def test_unblocked_ready_domains_make_hybrid_the_recommendation():
    _, plan_facts, evidence, version, static = pure(snapshot('petclinic'), observations=1, reviewed=True)
    doc = engine.build(str(uuid4()), version, static, plan_facts, evidence, dict(strategy='MICROSERVICES', objective='Extract what is ready'))
    brief = doc['decision_brief']
    ready = [d for d in doc['decisions'] if d['kind'] == 'PREPARE_FOR_EXTRACTION']
    if ready and not any(a['hard_blockers'] for a in doc['assessments']):
        assert brief['recommendation']['option'] == 'HYBRID' and f"{len(ready)} of {len(doc['assessments'])} domains" in brief['recommendation']['rationale']
    assert validation.validate(doc, plan_facts, evidence)['status'] == 'VALIDATED'


def test_tampered_numbers_are_rejected(petclinic):
    doc, plan_facts, evidence, *_ = petclinic
    forged = copy.deepcopy(doc)
    forged['decision_brief']['sections'][3]['paragraphs'][0] += ' 999 classes are affected.'
    assert 'BRIEF_NUMBER_NOT_IN_FACT_TABLE' in validation.validate(forged, plan_facts, evidence)['errors']
    changed = copy.deepcopy(doc)
    facts_ = changed['decision_brief']['facts']
    target = next(f for f in facts_ if f['id'] == 'rate_cross-domain-edges_n')      # 7: the text says '7 of 35 dependency edges'
    for other in facts_:                                    # another fact may equal 7 by coincidence (a blocker count); move it so only the target backs the text
        if other is not target and other['value'] == target['value']:
            other['value'] += 2000; other['text'] = str(other['value'])
    assert [f['id'] for f in facts_ if f['value'] == target['value']] == ['rate_cross-domain-edges_n']
    target['value'] = 1007                       # value changed, text left alone
    assert 'BRIEF_FACT_TEXT_MISMATCH' in validation.validate(changed, plan_facts, evidence)['errors']
    target['text'] = '1007'                      # both changed: the sentence still says 7, which no fact backs
    assert 'BRIEF_NUMBER_NOT_IN_FACT_TABLE' in validation.validate(changed, plan_facts, evidence)['errors']


def test_options_carry_measured_tradeoffs_and_the_legacy_fields_are_data_derived(petclinic):
    doc, *_ = petclinic
    brief = doc['decision_brief']
    options = {o['strategy']: o for o in brief['options']}
    assert set(options) == set(engine.STRATEGIES) and options['MODULAR_MONOLITH']['selected_by_user'] and options['MODULAR_MONOLITH']['recommended']
    assert 'Turns 15 cross-domain dependency edges between 3 domain pairs into remote calls.' in options['MICROSERVICES']['tradeoffs']
    legacy = {r['strategy']: r for r in brief['strategy_comparison']}
    assert legacy['MICROSERVICES']['rationale'] == ' '.join(options['MICROSERVICES']['tradeoffs'])
    assert 'Evidence-backed planning proposal; no strategy has been automatically selected.' not in (brief['headline'], brief['summary'])
    assert brief['headline'] == brief['decision'] and brief['next_step'].startswith('Start with ')
    assert all(e['id'] and e['kind'] for e in brief['evidence']) and len(brief['evidence']) <= 30
    assert 'Which user-visible workflows and business invariants must remain unchanged?' not in brief['unresolved_questions']


def test_a_long_list_named_with_two_limits_registers_two_consistent_facts():
    facts = Facts()
    names = [f'Domain {i}' for i in range(19)]
    assert _list(facts, names, 5).endswith('and 14 more') and _list(facts, names).endswith('and 15 more')
    assert sorted(r['value'] for r in facts.table()) == [14, 15]
    assert _list(facts, names, 5).endswith('and 14 more')                       # repeating a listing reuses its fact
