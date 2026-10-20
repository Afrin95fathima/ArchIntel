"""Item 7: the technology modernization plan on PetClinic and on a fixture with deliberately aging dependencies."""
import copy
from types import SimpleNamespace
import pytest
from app.insight import lifecycle, modernization_plan as mp
from insight_fixtures import model, snapshot


def plan_for(name, runtime=None):
    m = model(name, runtime)
    return mp.build(m, lifecycle.evaluate(m, snapshot(name).get('tech_inventory'))), m


def item(plan, rule_id):
    return next(i for i in plan['items'] if i['rule_id'] == rule_id)


def test_petclinic_raises_java_first_then_moves_spring_boot_to_the_current_line():
    plan, _ = plan_for('petclinic')
    assert plan['status'] == 'PROPOSED' and plan['review']['required'] and plan['generated_by'] == 'RULES'
    assert plan['runtime']['current_java'] == 17 and plan['runtime']['target_java'] == 21 and plan['runtime']['recommendation'] == 'JAVA_UPGRADE'
    assert [(p['number'], p['items']) for p in plan['phases']] == [(1, ['java-class-target']), (2, ['spring-boot'])]
    java, boot = item(plan, 'java-class-target'), item(plan, 'spring-boot')
    assert java['recommended']['id'] == 'java-21' and len(java['affected_classes']) == 24
    # Spring Boot 4.x is "current" in the rules file, 3.5.x is "aging": status ranks first
    assert any('Lifecycle status: current (Spring Boot 4.x.)' in line for line in boot['why'])
    assert boot['recommended']['id'] == 'spring-boot-4' and boot['recommended']['lifecycle']['status'] == 'current' and boot['recommended']['requires_java'] == 17
    assert [a['id'] for a in boot['alternatives']] == ['spring-boot-3.5'] and 'lifecycle status is aging against current for Spring Boot 4.x' in boot['alternatives'][0]['reason']
    java = item(plan, 'java-class-target')
    assert java['recommended']['lifecycle']['note'] == 'Java 21 LTS: premier support until September 2028.'
    assert boot['phase'] == 2 and boot['prerequisites'] == ['Phase 1 (raise java to 21)']


def test_language_change_is_not_recommended_and_the_reason_counts_the_findings():
    plan, _ = plan_for('petclinic')
    assert plan['language']['recommendation'] == 'NO_LANGUAGE_CHANGE'
    assert plan['language']['reason'].startswith('2 aging or end-of-life items (1 framework, 1 platform)') and 'language change is not supported by the evidence' in plan['language']['reason']


def test_edgecases_orders_library_replacements_before_java_before_framework_moves():
    plan, _ = plan_for('edgecases')
    by_phase = {p['number']: p['items'] for p in plan['phases']}
    assert sorted(by_phase[1]) == ['commons-lang-2', 'jdk-removed-ee-modules', 'log4j-1']        # run on the current Java 17
    assert by_phase[2] == ['java-class-target']
    assert sorted(by_phase[3]) == ['javax-persistence', 'javax-servlet', 'javax-ws-rs', 'struts-1']
    assert len(plan['items']) == 8 and plan['feasible'] is True
    for i in plan['items']:
        later = [p for p in plan['phases'] if p['number'] < i['phase']]
        assert i['prerequisites'] == [f"Phase {p['number']} ({p['title'].lower()})" for p in later]


def test_namespace_changes_list_the_affected_classes_by_name():
    plan, _ = plan_for('edgecases')
    servlet = item(plan, 'javax-servlet')
    check = next(c for c in servlet['feasibility'] if c['check'] == 'NAMESPACE')
    assert check['status'] == 'COUPLED' and check['detail'] == 'javax.servlet -> jakarta.servlet: 2 classes use the old namespace (AuditFilter, LegacyServlet).'
    assert servlet['affected_classes'] == ['com.fixture.edge.web.AuditFilter', 'com.fixture.edge.web.LegacyServlet']
    struts = next(c for c in item(plan, 'struts-1')['feasibility'] if c['check'] == 'NAMESPACE')
    assert 'BillingRecord, AuditFilter, GreetingResource, LegacyServlet' in struts['detail'] and struts['detail'].startswith('javax. -> jakarta.: 4 classes use the old namespace')


def test_each_recommendation_carries_why_alternatives_steps_risks_confidence_and_citations():
    plan, m = plan_for('edgecases')
    log4j = item(plan, 'log4j-1')
    assert log4j['recommended']['id'] == 'log4j-2' and [a['id'] for a in log4j['alternatives']] == ['slf4j-logback']
    assert log4j['alternatives'][0]['reason'] == 'it needs Java 11 against Java 8'
    assert log4j['steps'][0].startswith('Add log4j-api and log4j-core')
    assert log4j['why'] == ['Apache Log4j 1.x is end-of-life (the installed version could not be determined from the artifact); 1 class references it with 2 code references.',
                            'Log4j 2 is chosen. Lifecycle status: not covered by the lifecycle rules file. It needs Java 8; the plan targets Java 21.']
    assert log4j['confidence']['label'] == 'LOW' and log4j['confidence']['present'] == 2 and log4j['confidence']['total'] == 4
    assert log4j['runtime_evidence']['not_measured'] == 'no runtime session is attached' and log4j['runtime_evidence']['text'] is None
    assert log4j['citations'][:2] == ['rule:log4j-1', 'candidate:log4j-2'] and all(c.split(':', 1)[1] in m.classes for c in log4j['citations'] if c.startswith('class:'))


def test_runtime_evidence_says_how_many_affected_classes_ran():
    m = model('edgecases')
    servlet_classes = ['com.fixture.edge.web.AuditFilter', 'com.fixture.edge.web.LegacyServlet']
    runtime = dict(runtime_graph=dict(nodes=[dict(id=servlet_classes[0], static_id=servlet_classes[0])], edges=[]), observed_methods=None)
    plan, _ = plan_for('edgecases', runtime)
    evidence = item(plan, 'javax-servlet')['runtime_evidence']
    assert (evidence['observed'], evidence['total'], evidence['text']) == (1, 2, '1 of 2 affected classes ran in the selected sessions')
    assert '1 of 2 affected classes were never observed at runtime, so tests must cover them.' in item(plan, 'javax-servlet')['risks']
    assert item(plan, 'javax-servlet')['confidence']['present'] == 3


# ---- synthetic scenarios for the feasibility checks -------------------------------------------------------------------

def stub(classes=('app.A',)):
    return SimpleNamespace(classes={c: {} for c in classes}, facts={c: {} for c in classes}, facts_available=True, observed_classes=None)


def finding(rule_id, technology, status, version=None, classes=('app.A',), category='framework'):
    return dict(rule_id=rule_id, technology=technology, status=status, version_found=version, category=category, status_note=None, source_url='u',
                affected_classes=[dict(class_name=c, apis=[], call_sites=[], call_site_count=1, api_count=1) for c in classes], affected_class_count=len(classes), call_site_count=len(classes))


def candidates(**items):
    return {'candidates_version': 'test', 'java': {'lts_candidates': [21, 25]}, 'items': {**mp.load_candidates()['items'], **items}}


def candidate(identifier, requires_java=8, **extra):
    return {**dict(id=identifier, name=identifier, target_version='1', requires_java=requires_java, phase='library', lifecycle={'rule': 'java-class-target', 'version': '21'}, steps=['do it'], fit='x'), **extra}


def test_a_candidate_needing_an_unreachable_java_level_fails_the_java_check():
    cands = candidates(**{'commons-lang-2': [candidate('needs-java-99', 99)]})
    plan = mp.build(stub(), {'findings': [finding('commons-lang-2', 'Commons Lang', 'aging', '2.6', category='library')]}, cands)
    check = item(plan, 'commons-lang-2')['feasibility'][0]
    assert check['check'] == 'JAVA_LEVEL' and check['status'] == 'FAIL' and 'needs Java 99' in check['detail']
    assert plan['feasible'] is False and item(plan, 'commons-lang-2')['feasible'] is False


def test_an_incompatible_technology_that_is_not_being_replaced_blocks_the_candidate_and_the_other_wins():
    needs = [{'rule': 'log4j-1', 'versions': '>=1.0', 'reason': 'Log4j 1 cannot coexist.'}]
    cands = candidates(**{'commons-lang-2': [candidate('blocked-one', 8, needs=needs), candidate('free-one', 8)]})
    findings = [finding('commons-lang-2', 'Commons Lang', 'aging', '2.6', category='library'), finding('log4j-1', 'Log4j 1.x', 'current', '1.2', category='library')]   # present but not flagged
    plan = mp.build(stub(), {'findings': findings}, cands)
    chosen = item(plan, 'commons-lang-2')
    assert chosen['recommended']['id'] == 'free-one' and chosen['alternatives'][0]['reason'].startswith('blocked by Log4j 1.x 1.2 (Log4j 1 cannot coexist.)')


def test_a_flagged_incompatible_technology_couples_the_two_items_into_one_phase():
    cands = candidates(**{'spring-boot': [candidate('boot-x', 17, needs=[{'rule': 'hibernate-orm', 'versions': '<6.0', 'reason': 'Boot X manages Hibernate 6.'}], phase='framework')]})
    findings = [finding('spring-boot', 'Spring Boot', 'aging', '2.7'), finding('hibernate-orm', 'Hibernate ORM', 'end-of-life', '5.6', category='framework')]
    plan = mp.build(stub(), {'findings': findings}, cands)
    boot, hibernate = item(plan, 'spring-boot'), item(plan, 'hibernate-orm')
    assert boot['coupled_with'] == ['hibernate-orm'] and boot['phase'] == hibernate['phase']
    assert any(c['check'] == 'DEPENDENCY_CONFLICT' and c['status'] == 'COUPLED' and 'Hibernate ORM 5.6' in c['detail'] and 'same phase' in c['detail'] for c in boot['feasibility'])


def test_a_recommendation_citing_a_class_that_does_not_exist_is_dropped():
    plan = mp.build(stub(('app.A',)), {'findings': [finding('commons-lang-2', 'Commons Lang', 'aging', '2.6', classes=('app.A', 'app.Ghost'), category='library')]})
    assert plan['items'] == [] and plan['dropped'] == [dict(rule_id='commons-lang-2', missing=['class:app.Ghost'])]


def test_current_technology_is_not_planned_and_the_plan_is_deterministic():
    plan = mp.build(stub(), {'findings': [finding('spring-boot', 'Spring Boot', 'current', '4.0')]})
    assert plan['items'] == [] and plan['phases'] == [] and plan['runtime']['recommendation'] == 'NO_JAVA_UPGRADE'
    first, _ = plan_for('edgecases')
    second, _ = plan_for('edgecases')
    assert first == second


def test_every_lifecycle_rule_has_curated_candidates_that_reference_real_rules():
    data = mp.load_candidates()
    rules = {r['id'] for r in lifecycle.load_rules()['rules']}
    assert set(data['items']) == rules
    assert all(c['requires_java'] >= 8 and c['steps'] for rows in data['items'].values() for c in rows)


# ---- model wording is optional, cited and labelled ---------------------------------------------------------------------

def test_model_recommendations_outside_the_curated_list_are_labelled_unverified_and_uncited_ones_are_dropped():
    plan, _ = plan_for('edgecases')
    ids = {'e0': 'rule:log4j-1', 'e1': 'rule:javax-servlet'}
    output = {'recommendations': [
        dict(rule_id='log4j-1', choice='log4j-2', rationale='Log4j 2 keeps the API.', cite=['e0']),
        dict(rule_id='log4j-1', choice='Reload4j', rationale='A fork exists.', cite=['e0']),
        dict(rule_id='javax-servlet', choice='jakarta-servlet-6', rationale='No citation.', cite=[]),
        dict(rule_id='not-in-plan', choice='x', rationale='r', cite=['e0']),
        dict(rule_id='log4j-1', choice='slf4j-logback', rationale='Cites a missing id.', cite=['e9'])]}
    kept, dropped = mp.verify_ai(output, plan, ids)
    assert [(k['choice'], k['verification']) for k in kept] == [('log4j-2', 'CURATED'), ('Reload4j', 'UNVERIFIED_CONFIRM_BEFORE_USE')]
    assert sorted(d['reason'] for d in dropped) == ['RULE_NOT_IN_PLAN', 'UNCITED_OR_UNKNOWN_CITATION', 'UNCITED_OR_UNKNOWN_CITATION']


def test_candidates_never_borrow_another_technologys_lifecycle_status():
    expected = {'java-21': 'java-class-target', 'java-25': 'java-class-target', 'spring-boot-3.5': 'spring-boot', 'spring-boot-4': 'spring-boot',
                'spring-framework-6.2': 'spring-framework', 'spring-framework-7': 'spring-framework', 'spring-mvc': 'spring-framework',
                'jakarta-persistence-3.1': 'hibernate-orm', 'hibernate-6.6': 'hibernate-orm', 'hibernate-7': 'hibernate-orm'}
    actual = {c['id']: c['lifecycle']['rule'] for rows in mp.load_candidates()['items'].values() for c in rows if c['lifecycle'] is not None}
    assert actual == expected
    plan, _ = plan_for('edgecases')
    log4j = item(plan, 'log4j-1')['recommended']
    assert log4j['lifecycle'] == dict(status='not-covered', note=None, rule=None, version=None)


def test_the_published_proposal_includes_a_valid_technology_plan_and_the_validator_rejects_tampering():
    from test_modernization import pure
    from app.modernization import validation
    doc, facts, evidence, _, _ = pure(snapshot('edgecases'), observations=.5, reviewed=True)
    plan = doc['technology_plan']
    assert plan['status'] == 'PROPOSED' and len(plan['items']) == 8 and validation.validate(doc, facts, evidence)['status'] == 'VALIDATED'
    for tamper, code in (('status', 'TECH_PLAN_NOT_A_PROPOSAL'), ('candidate', 'TECH_PLAN_UNKNOWN_CANDIDATE'), ('feasible', 'TECH_PLAN_FEASIBILITY_MISMATCH'), ('phase', 'TECH_PLAN_PHASE_MISSING')):
        forged = copy.deepcopy(doc)
        if tamper == 'status': forged['technology_plan']['status'] = 'ACTIVE'
        if tamper == 'candidate': forged['technology_plan']['items'][0]['recommended']['id'] = 'invented-library'
        if tamper == 'feasible': forged['technology_plan']['items'][0]['feasible'] = not forged['technology_plan']['items'][0]['feasible']
        if tamper == 'phase': forged['technology_plan']['phases'][0]['items'].pop()
        assert code in validation.validate(forged, facts, evidence)['errors'], tamper


def test_a_version_without_bytecode_facts_states_that_the_plan_is_not_available():
    from test_modernization import pure
    doc, *_ = pure()
    assert doc['technology_plan'] == dict(status='NOT_AVAILABLE', reason='This analysis has no bytecode facts, so aging technology cannot be assessed; run a new analysis.')


def test_model_wording_is_cited_verified_labelled_and_flags_unverified_choices(monkeypatch):
    from test_modernization import pure
    from app.modernization import service
    import app.ai.grounded as grounded
    doc, *_ = pure(snapshot('edgecases'), observations=.5, reviewed=True)
    item_ = SimpleNamespace(id='a1', document=doc)
    sent = {}

    def fake(request, db, purpose, envelope, schema, system, resource, max_tokens=400, permission='ANALYSIS_READ'):
        sent.update(purpose=purpose, envelope=envelope, schema=schema)
        ids = {e['text'][:12]: e['id'] for e in envelope['evidence']}
        log4j = next(e['id'] for e in envelope['evidence'] if e['text'].startswith('Apache Log4j'))
        return {'recommendations': [
            dict(rule_id='log4j-1', choice='log4j-2', rationale='Log4j 2 keeps the logging API that BillingAction already uses.', cite=[log4j]),
            dict(rule_id='log4j-1', choice='Reload4j', rationale='Reload4j is a maintained fork.', cite=[log4j]),
            dict(rule_id='log4j-1', choice='log4j-2', rationale='Replace the logger in com.invented.Missing with it.', cite=[log4j]),
            dict(rule_id='struts-1', choice='spring-mvc', rationale='No citation given.', cite=[])]}, dict(reason=None, request_id='r1', mode='LOCAL_MODEL')
    monkeypatch.setattr(grounded, 'model_call', fake)
    out = service.technology_ai(item_, SimpleNamespace(), None)
    assert sent['purpose'] == 'TECHNOLOGY_PLAN' and len(sent['envelope']['evidence']) == 8 and 'rule_id' in sent['schema']['properties']['recommendations']['items']['properties']
    assert out['status'] == 'AI_GENERATED' and 'AI-written wording' in out['label'] and 'confirm before use' in out['label']
    assert [(r['rule_id'], r['choice'], r['verification']) for r in out['recommendations']] == [('log4j-1', 'log4j-2', 'CURATED'), ('log4j-1', 'Reload4j', 'UNVERIFIED_CONFIRM_BEFORE_USE')]
    assert out['recommendations'][0]['citations'] == ['rule:log4j-1']
    assert sorted(d['reason'] for d in out['dropped']) == ['UNCITED_OR_UNKNOWN_CITATION', 'UNVERIFIED_IDENTIFIER']


def test_without_a_model_the_plan_is_unchanged_and_the_explanation_says_why(monkeypatch):
    from test_modernization import pure
    from app.modernization import service
    import app.ai.grounded as grounded
    doc, *_ = pure(snapshot('edgecases'), observations=.5, reviewed=True)
    before = copy.deepcopy(doc['technology_plan'])
    monkeypatch.setattr(grounded, 'model_call', lambda *a, **k: (None, dict(reason='INSIGHT_AI_DISABLED', request_id=None)))
    out = service.technology_ai(SimpleNamespace(id='a1', document=doc), SimpleNamespace(), None)
    assert out['status'] == 'NOT_AVAILABLE' and out['reason'] == 'INSIGHT_AI_DISABLED' and out['recommendations'] == []
    assert doc['technology_plan'] == before
