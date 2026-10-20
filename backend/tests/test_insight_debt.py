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


# ---- Item 12: percentages with numerator and denominator ---------------------------------------------------------

def rate(result, rate_id):
    return next(r for r in result['rates']['rates'] if r['id'] == rate_id)


def test_edgecases_rates_match_hand_counts():
    """19 top-level classes (22 minus 3 nested), 15 owner-level dependency edges, 71 measured methods, 3 static fields."""
    r = detect(model('edgecases'))
    cycles = rate(r, 'cycle-member')
    assert (cycles['numerator'], cycles['denominator'], cycles['percentage']) == (7, 19, 36.8) and cycles['text'] == '7 of 19 classes (36.8%)'
    assert len(cycles['classes']) == 7 and 'com.fixture.edge.cycle.a.Order' in cycles['classes']
    aging = rate(r, 'aging-framework')
    assert (aging['numerator'], aging['denominator'], aging['percentage']) == (8, 19, 42.1)
    layer = rate(r, 'layer-violation')
    assert (layer['numerator'], layer['denominator'], layer['percentage']) == (2, 15, 13.3) and layer['unit'] == 'dependency edges'
    controller = rate(r, 'entity-in-controller')
    assert (controller['numerator'], controller['denominator'], controller['percentage']) == (2, 5, 40.0)
    static = rate(r, 'static-state')
    assert (static['numerator'], static['denominator'], static['percentage']) == (2, 3, 66.7)
    assert (rate(r, 'deprecated-api')['numerator'], rate(r, 'deprecated-api')['denominator']) == (1, 19)
    assert (rate(r, 'large-method')['denominator'], rate(r, 'large-method')['numerator']) == (71, 0)
    assert rate(r, 'cross-domain-edges')['text'] == '0 of 15 dependency edges (0.0%)'
    anyclass = rate(r, 'any-class')
    assert (anyclass['numerator'], anyclass['denominator'], anyclass['percentage']) == (12, 19, 63.2)


def test_petclinic_rates_match_hand_counts():
    """24 classes; 35 distinct class edges of which 7 join different candidate domains; 15 edges leave the 6 presentation classes, 8 of them reach entities."""
    r = detect(model('petclinic'))
    assert rate(r, 'cross-domain-edges')['text'] == '7 of 35 dependency edges (20.0%)'
    controller = rate(r, 'entity-in-controller')
    assert (controller['numerator'], controller['denominator'], controller['percentage']) == (8, 15, 53.3)
    assert rate(r, 'aging-framework')['text'] == '1 of 24 classes (4.2%)'
    assert rate(r, 'any-class')['text'] == '5 of 24 classes (20.8%)'


def test_unmeasurable_rates_say_why_and_never_show_a_percentage():
    r = detect(model('edgecases'))
    for rate_id in ('unobserved', 'entry-points-unobserved'):
        item = rate(r, rate_id)
        assert item['status'] == 'NOT_MEASURED' and item['percentage'] is None and item['numerator'] is None
        assert item['reason'] == 'no runtime session is selected' and item['text'] == 'not measured: no runtime session is selected'


def test_runtime_rates_use_the_selected_sessions():
    base = model('petclinic')
    controllers = [c for c in base.classes if c.endswith('Controller')]
    observed_ids = set(base.classes) - set(controllers[:2])
    runtime = dict(runtime_graph=dict(nodes=[dict(id=c, static_id=c) for c in observed_ids], edges=[]), observed_methods=None)
    from insight_fixtures import model as build
    r = detect(build('petclinic', runtime))
    unobserved = rate(r, 'unobserved')
    assert (unobserved['numerator'], unobserved['denominator']) == (2, 24) and unobserved['percentage'] == 8.3 and set(unobserved['classes']) == set(controllers[:2])
    entry = rate(r, 'entry-points-unobserved')
    total = len(base.entry_points['items'])
    expected = sum(1 for e in base.entry_points['items'] if e['handler_class'] in controllers[:2])
    assert (entry['numerator'], entry['denominator']) == (expected, total) and entry['basis'].startswith('class-level')


def test_package_and_domain_breakdowns_use_their_own_denominators():
    r = detect(model('edgecases'))['rates']
    package = next(p for p in r['by_package'] if p['id'] == 'com.fixture.edge.cycle.a')
    classes_in_package = package['class_count']
    cycle = package['rates']['cycle-member']
    assert cycle['denominator'] == classes_in_package and cycle['numerator'] == len(cycle['classes']) and cycle['percentage'] == round(100 * cycle['numerator'] / classes_in_package, 1)
    assert sum(p['class_count'] for p in r['by_package']) == 19 and sum(d['class_count'] for d in r['by_domain']) == 19
    assert sum(len(p['rates'].get('cycle-member', {}).get('classes', [])) for p in r['by_package']) == 7
