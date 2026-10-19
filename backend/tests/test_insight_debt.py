"""WP4: debt findings on compiled fixtures with known answers."""
from app.insight.debt import detect
from insight_fixtures import model, PETCLINIC


def by_rule(findings, rule):
    return [f for f in findings if f['rule_id'] == rule]


def test_every_finding_has_entity_measure_threshold_layers_and_action():
    result = detect(model('edgecases'))
    assert result['findings']
    for f in result['findings']:
        assert f['entity_id'] and f['node_ids'] and f['measured'] and f['threshold'] is not None
        assert f['explanation']['technical'] and f['explanation']['plain'] and f['suggested_action']
        assert f['evidence'], f['rule_id']
    assert 'not a time, cost or currency' in result['effort_note']


def test_layer_violation_names_caller_and_callee():
    [v] = by_rule(detect(model('edgecases'))['findings'], 'DEBT-LAYER-VIOLATION')
    assert v['entity_id'] == 'com.fixture.edge.legacy.BillingRecord -> com.fixture.edge.legacy.BillingAction'
    assert v['measured'] == {'from_layer': 'DOMAIN', 'to_layer': 'PRESENTATION'}
    assert 'BillingRecord.touch() calls BillingAction.oldApi()' in [e['text'] for e in v['evidence']]


def test_static_state_and_deprecated_usage_are_specific():
    findings = detect(model('edgecases'))['findings']
    static = {f['entity_id']: f for f in by_rule(findings, 'DEBT-STATIC-STATE')}
    assert set(static) == {'com.fixture.edge.model.ItemService#CACHE', 'com.fixture.edge.model.ItemService#counter'}
    assert 'delete, save' in static['com.fixture.edge.model.ItemService#CACHE']['explanation']['technical']
    assert 'assigned in save()' in static['com.fixture.edge.model.ItemService#counter']['explanation']['technical']
    [dep] = by_rule(findings, 'DEBT-DEPRECATED-API')
    assert dep['entity_id'] == 'com.fixture.edge.legacy.BillingRecord'
    assert dep['evidence'][0]['text'] == 'BillingRecord.touch() calls @Deprecated BillingAction.oldApi()'


def test_entity_in_controller_and_aging_links():
    findings = detect(model('edgecases'))['findings']
    assert sorted(f['entity_id'] for f in by_rule(findings, 'DEBT-ENTITY-IN-CONTROLLER')) == [
        'com.fixture.edge.legacy.BillingAction -> com.fixture.edge.legacy.BillingRecord',      # Struts action -> javax entity
        'com.fixture.edge.web.OrderAdminController -> com.fixture.edge.model.OrderEntity']
    aging = {f['entity_id'] for f in by_rule(findings, 'DEBT-AGING-FRAMEWORK')}
    assert 'com.fixture.edge.legacy.BillingAction uses log4j-1' in aging
    assert 'com.fixture.edge.legacy.BillingRecord uses javax-persistence' in aging
    eol = next(f for f in by_rule(findings, 'DEBT-AGING-FRAMEWORK') if f['entity_id'].endswith('log4j-1'))
    assert eol['severity'] == 'HIGH' and eol['related']['lifecycle_finding_id'] == 'log4j-1'


def test_cycle_members_are_findings_with_the_loop():
    members = {f['entity_id'] for f in by_rule(detect(model('edgecases'))['findings'], 'DEBT-CYCLE-MEMBER')}
    assert {'com.fixture.edge.cycle.a.Order', 'com.fixture.edge.cycle.b.Invoice', 'com.fixture.edge.legacy.BillingAction'} <= members
    assert len(members) == 7


def test_petclinic_controllers_bind_entities_directly():
    findings = detect(model('petclinic'))['findings']
    pairs = {f['entity_id'] for f in by_rule(findings, 'DEBT-ENTITY-IN-CONTROLLER')}
    assert f'{PETCLINIC}.owner.OwnerController -> {PETCLINIC}.owner.Owner' in pairs
    assert f'{PETCLINIC}.owner.VisitController -> {PETCLINIC}.owner.Visit' in pairs
    assert not by_rule(findings, 'DEBT-LAYER-VIOLATION') and not by_rule(findings, 'DEBT-UNOBSERVED')


def test_unobserved_only_with_runtime_and_never_called_unused():
    runtime = dict(runtime_graph=dict(nodes=[dict(id=f'{PETCLINIC}.owner.OwnerController', static_id=f'{PETCLINIC}.owner.OwnerController')], edges=[]))
    findings = by_rule(detect(model('petclinic', runtime))['findings'], 'DEBT-UNOBSERVED')
    assert len(findings) == 23 and all('unused' not in f['title'].lower() for f in findings)
    assert all('does not mean it is unused' in f['explanation']['plain'] for f in findings)


def test_package_summary_shows_formula_and_inputs():
    packages = detect(model('edgecases'))['packages']
    legacy = next(p for p in packages if p['package'] == 'com.fixture.edge.legacy')
    assert legacy['debt_index'] == sum({'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'INFO': 0}[k] * v for k, v in legacy['counts'].items())
    assert 'debt index =' in legacy['formula'] and legacy['inputs']['classes'] == 2
