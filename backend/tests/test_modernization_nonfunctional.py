"""Non-functional constraints inside the modernization plan: new findings and soft blockers, unchanged scores, honest limits."""
import json
import pytest
from app.modernization import engine, nonfunctional, validation
from app.modernization.brief import unregistered_numbers, HARD
from insight_fixtures import snapshot
from test_modernization import pure

NEW_KINDS = {'SECURITY_CONTROL_NOT_DETECTED', 'SHARED_DATA_MODEL', 'TRANSACTION_SPANS_DOMAINS', 'PERFORMANCE_INDICATOR', 'NO_INSTRUMENTATION_DETECTED', 'RELIABILITY_PROTECTION_NOT_DETECTED',
             'SHARED_MUTABLE_STATE', 'CLASS_WITH_MANY_RESPONSIBILITIES', 'CROSS_CUTTING_DEPENDENCY', 'TECHNICAL_DOMAIN'}
NEW_BLOCKERS = {'SECURITY_CONTROL_REVIEW', 'SHARED_DATA_MODEL_REVIEW', 'CROSS_CUTTING_REVIEW', 'TRANSACTION_BOUNDARY_REVIEW', 'TECHNICAL_DOMAIN_REVIEW'}


@pytest.fixture(scope='module')
def plan():
    return pure(snapshot('petclinic'), observations=.5, reviewed=True)


@pytest.fixture(scope='module')
def plan_without(plan):
    """The same plan with the non-functional analysis switched off, to prove what it does and does not change."""
    original = engine.nonfunctional.build
    engine.nonfunctional.build = lambda static, domains: dict(by_domain={}, document=dict(status='NOT_AVAILABLE', reason='disabled for comparison', limitation='disabled'))
    try:
        return pure(snapshot('petclinic'), observations=.5, reviewed=True)
    finally:
        engine.nonfunctional.build = original


def test_the_document_carries_capabilities_risks_cross_cutting_components_and_what_was_not_examined(plan):
    doc = plan[0]
    nf = doc['nonfunctional']
    assert nf['status'] == 'AVAILABLE' and nf['rules_version'] and nf['engine_version']
    assert {c['name'] for c in nf['capabilities']} == {a['domain_name'] for a in doc['assessments']}
    assert nf['risks'] and all(r['consequence_status'] == 'INFERRED' and r['detection_status'] in ('DETECTED', 'INFERRED') and r['domains'] for r in nf['risks'])
    assert nf['cross_cutting'] and any('configuration' in x for x in nf['not_examined'])
    domain_ids = {a['domain_id'] for a in doc['assessments']}
    assert all(d['id'] in domain_ids for r in nf['risks'] for d in r['domains'])


def test_new_findings_cite_captured_evidence_name_their_risk_and_the_plan_still_validates(plan):
    doc, facts, evidence, *_ = plan
    new = [f for f in doc['findings'] if f['kind'] in NEW_KINDS]
    assert {f['kind'] for f in new} >= {'SECURITY_CONTROL_NOT_DETECTED', 'SHARED_DATA_MODEL', 'PERFORMANCE_INDICATOR'}
    risk_ids = {r['id'] for r in doc['nonfunctional']['risks']}
    for finding in new:
        assert finding['evidence_ids'] and finding['subjects'] or finding['kind'] == 'TECHNICAL_DOMAIN'
        assert finding['responsibility_risk_id'] in risk_ids or finding['kind'] == 'TECHNICAL_DOMAIN'
    assert len({f['id'] for f in doc['findings']}) == len(doc['findings'])
    assert validation.validate(doc, facts, evidence)['status'] == 'VALIDATED'


def test_scores_decisions_and_waves_are_not_changed_by_the_non_functional_analysis(plan, plan_without):
    on, off = plan[0], plan_without[0]
    keys = ('structural_score', 'runtime_score', 'combined_score', 'confidence_score', 'readiness_score', 'readiness_label', 'hard_blockers', 'cost_index', 'effort_band', 'risk_band')
    assert [{k: a[k] for k in keys} for a in on['assessments']] == [{k: a[k] for k in keys} for a in off['assessments']]
    name = lambda doc: {a['domain_id']: a['domain_name'] for a in doc['assessments']}
    assert [(name(on)[d['domain_id']], d['kind']) for d in on['decisions']] == [(name(off)[d['domain_id']], d['kind']) for d in off['decisions']]
    assert [(w['number'], [name(on)[d] for d in w['domains']]) for w in on['waves']] == [(w['number'], [name(off)[d] for d in w['domains']]) for w in off['waves']]
    # domain ids are derived from a fresh random version id in each pure() call, so compare the id-free substance
    substance = lambda r: (r['kind'], r['affected_classes'], r['proposed_interface'], r['missing_evidence'], len(r['dependency_pairs']), len(r['target_domains']))
    assert [substance(a['recommendations'][0]) for a in on['assessments']] == [substance(a['recommendations'][0]) for a in off['assessments']]     # finding_ids may list more findings
    assert off['nonfunctional']['status'] == 'NOT_AVAILABLE' and not [f for f in off['findings'] if f['kind'] in NEW_KINDS]


def test_new_blockers_are_soft_and_never_decide_the_readiness_label(plan):
    doc = plan[0]
    for assessment in doc['assessments']:
        assert not set(assessment['hard_blockers']) & NEW_BLOCKERS and not set(HARD) & NEW_BLOCKERS
    used = {b for a in doc['assessments'] for b in a['blockers']} & NEW_BLOCKERS
    assert {'SECURITY_CONTROL_REVIEW', 'SHARED_DATA_MODEL_REVIEW'} <= used
    brief_codes = {b['code']: b for b in doc['decision_brief']['sections'] and plan[0]['decision_brief']['blockers']}
    for code in used:
        assert brief_codes[code]['hard'] is False and brief_codes[code]['meaning'] and brief_codes[code]['resolve']


def test_technical_domains_are_not_offered_for_extraction(plan):
    doc = plan[0]
    technical = {c['domain_id'] for c in doc['nonfunctional']['capabilities'] if c['kind'] == 'TECHNICAL'}
    assert technical
    for assessment in doc['assessments']:
        if assessment['domain_id'] in technical:
            assert 'TECHNICAL_DOMAIN_REVIEW' in assessment['blockers'] and not set(assessment['blockers']) & {'SECURITY_CONTROL_REVIEW', 'SHARED_DATA_MODEL_REVIEW'}
            assert any(f['kind'] == 'TECHNICAL_DOMAIN' and 'not a candidate for extraction' in f['text'] for f in doc['findings'] if f['domain_id'] == assessment['domain_id'])


def test_a_domain_with_actionable_constraints_gets_a_second_recommendation_that_names_what_is_missing(plan):
    doc = plan[0]
    extra = [(a, r) for a in doc['assessments'] for r in a['recommendations'] if r['kind'] == 'ADDRESS_NONFUNCTIONAL_CONSTRAINT']
    assert extra
    for assessment, recommendation in extra:
        assert assessment['recommendations'][0]['kind'] != 'ADDRESS_NONFUNCTIONAL_CONSTRAINT' and recommendation['text'] and recommendation['affected_classes']
        assert any('runtime_validation_required' in m for m in recommendation['missing_evidence'])
        assert assessment['nonfunctional']['capability_kind'] and assessment['nonfunctional']['implications']


def test_the_brief_has_a_non_functional_section_that_keeps_every_number_registered_and_states_what_was_not_examined(plan):
    brief = plan[0]['decision_brief']
    section = next(s for s in brief['sections'] if s['id'] == 'nonfunctional')
    text = ' '.join(section['paragraphs'])
    assert unregistered_numbers(brief) == [] and 'structural indicators, not measurements' in text and 'Not examined' in text and 'not proven absent' in text
    technical = [c for c in plan[0]['nonfunctional']['capabilities'] if c['kind'] == 'TECHNICAL']
    assert 'library' in text and 'service candidate' in text
    assert ('holds technical concerns' if len(technical) == 1 else 'hold technical concerns') in text and ('is not a service candidate' if len(technical) == 1 else 'are not service candidates') in text
    facts = {f['id']: f for f in brief['facts']}
    assert facts['nfr_risks']['value'] == len(plan[0]['nonfunctional']['risks']) and facts['nfr_risks']['source'].startswith('responsibility analysis')


def test_the_brief_states_the_limit_when_the_analysis_cannot_run(monkeypatch):
    monkeypatch.setattr(nonfunctional, 'analyse', lambda static, domains: dict(status='NOT_AVAILABLE', reason='Bytecode facts are not available for this analysis.'))
    doc, facts, evidence, *_ = pure(snapshot('petclinic'), observations=.5, reviewed=True)
    assert doc['nonfunctional']['status'] == 'NOT_AVAILABLE'
    section = next(s for s in doc['decision_brief']['sections'] if s['id'] == 'nonfunctional')
    assert 'does not account for security, performance, reliability or data-integrity' in ' '.join(section['paragraphs'])
    assert not [f for f in doc['findings'] if f['kind'] in NEW_KINDS] and validation.validate(doc, facts, evidence)['status'] == 'VALIDATED'


def test_the_planning_graph_links_capabilities_concerns_risks_and_shared_components(plan):
    graph = plan[0]['graph']
    nodes = {n['id']: n for n in graph['nodes']}
    kinds = {n['kind'] for n in graph['nodes']}
    assert {'BusinessCapability', 'NonFunctionalConcern', 'NonFunctionalRisk', 'SharedComponent'} <= kinds
    assert {e['kind'] for e in graph['edges']} >= {'ASSOCIATED_WITH', 'HAS_CONCERN', 'CONCERNS', 'AFFECTS', 'DEPENDS_ON'}
    assert all(e['source'] in nodes and e['target'] in nodes for e in graph['edges'])
    assert len({n['id'] for n in graph['nodes']}) == len(graph['nodes']) and len({e['id'] for e in graph['edges']}) == len(graph['edges'])
    risk_nodes = [n for n in graph['nodes'] if n['kind'] == 'NonFunctionalRisk']
    assert len(risk_nodes) == len(plan[0]['nonfunctional']['risks'])


def test_the_plan_is_reproducible_with_the_same_inputs(plan):
    again = pure(snapshot('petclinic'), observations=.5, reviewed=True)[0]
    strip = lambda doc: json.dumps(doc['nonfunctional'], sort_keys=True)
    assert strip(plan[0]) == strip(again)


def test_every_recommendation_carries_every_field_the_plan_screen_reads_and_cites_real_findings(plan):
    """The screen joins these lists; a recommendation without one blanked the whole page in the running app."""
    doc = plan[0]
    finding_ids = {f['id'] for f in doc['findings']}
    seen = {r['kind'] for a in doc['assessments'] for r in a['recommendations']}
    assert 'ADDRESS_NONFUNCTIONAL_CONSTRAINT' in seen and len(seen) >= 2
    for assessment in doc['assessments']:
        for recommendation in assessment['recommendations']:
            for key in ('affected_classes', 'dependency_pairs', 'target_domains', 'finding_ids', 'missing_evidence'):
                assert isinstance(recommendation[key], list), (assessment['domain_name'], recommendation['kind'], key)
            assert {'kind', 'text', 'proposed_interface'} <= set(recommendation) and set(recommendation['finding_ids']) <= finding_ids
        extra = [r for r in assessment['recommendations'] if r['kind'] == 'ADDRESS_NONFUNCTIONAL_CONSTRAINT']
        for r in extra:
            assert r['finding_ids'] and all(next(f for f in doc['findings'] if f['id'] == i)['kind'] in NEW_KINDS for i in r['finding_ids'])


def test_a_domain_lists_only_its_own_classes_even_for_application_wide_risks(plan):
    doc = plan[0]
    own = {a['domain_id']: {c for d in doc['target']['components'] if d['domain_id'] == a['domain_id'] for c in d['classes']} for a in doc['assessments']}
    short = lambda names: {n.rsplit('.', 1)[-1] for n in names}
    for assessment in doc['assessments']:
        for recommendation in assessment['recommendations']:
            if recommendation['kind'] == 'ADDRESS_NONFUNCTIONAL_CONSTRAINT':
                assert recommendation['affected_classes'] and set(recommendation['affected_classes']) <= own[assessment['domain_id']], assessment['domain_name']
    observability = [f for f in doc['findings'] if f['kind'] == 'NO_INSTRUMENTATION_DETECTED']
    assert len(observability) == len(doc['assessments'])                    # the risk is application-wide, so every domain carries it
    for finding in observability:
        assert finding['subjects'] and set(finding['subjects']) <= short(own[finding['domain_id']]), finding['domain_id']


def test_start_with_prefers_business_domains_over_technical_ones(plan, plan_without):
    doc = plan[0]
    technical = {c['name'] for c in doc['nonfunctional']['capabilities'] if c['kind'] == 'TECHNICAL'}
    business = {c['name'] for c in doc['nonfunctional']['capabilities'] if c['kind'] != 'TECHNICAL'}
    assert technical and business
    first = doc['decision_brief']['top_actions'][0].split(':')[0]
    assert first in business and first not in technical
    assert plan_without[0]['decision_brief']['top_actions']                   # without the analysis the order is the plain cost order, as before


def test_a_technical_domain_is_not_a_startable_service_candidate(plan):
    doc = plan[0]
    kinds = {c['domain_id']: c['kind'] for c in doc['nonfunctional']['capabilities']}
    candidates = doc['microservice_decomposition']['service_candidates']
    technical = [c for c in candidates if kinds[c['id']] == 'TECHNICAL']
    assert technical and all(c['proposal_state'] == 'TECHNICAL_DOMAIN_NOT_A_SERVICE' for c in technical)
    assert all(c['proposal_state'] == 'CANDIDATE_REQUIRES_REVIEW' for c in candidates if kinds[c['id']] != 'TECHNICAL')
    assert any('cannot be started as a service' in text for text in doc['microservice_decomposition']['limitations'])
