"""Functional and non-functional responsibility analysis: rule semantics on small applications, then PetClinic ground truth."""
import copy
import json

import pytest

from app.insight.model import InsightModel
from app.insight import responsibility as R
from app.insight.responsibility import analyze, load_rules, validate
from insight_fixtures import snapshot

P = 'shop.'


def method(name, params=(), returns='void', annotations=(), invokes=(), branches=0, lines=(10, 12), abstract=False, param_annotations=(), type_refs=(), code=30):
    return dict(name=name, descriptor='()V', signature=f'{returns} {name}({",".join(params)})', parameters=list(params), parameter_names=[], returns=returns, visibility='public',
                static=False, abstract=abstract, synthetic=False, bridge=False, varargs=False, lambda_body=False, kind='constructor' if name == '<init>' else 'method',
                annotations=[dict(type=a, values=v) for a, v in annotations], parameter_annotations=[[dict(type=a, values={}) for a in group] for group in param_annotations],
                exceptions=[], generic_types=[], code_length=code, branch_count=branches, line_range=list(lines),
                invokes=[dict(owner=o, name=n, descriptor='()V', kind='virtual', line=l) for o, n, l in invokes], field_access=[], type_refs=list(type_refs))


def field(name, type_, annotations=(), static=False, final=False):
    return dict(name=name, descriptor='L' + type_.replace('.', '/') + ';', type=type_, visibility='private', static=static, final=final, synthetic=False,
                annotations=[dict(type=a, values=v) for a, v in annotations], generic_types=[], deprecated=False)


def klass(name, annotations=(), methods=(), fields=(), super_name='java.lang.Object', interfaces=(), interface=False, domain='d1'):
    return dict(fqn=P + name, super_name=super_name, interfaces=list(interfaces), annotations=[dict(type=a, values=v) for a, v in annotations], fields=list(fields), methods=list(methods),
                interface=interface, abstract=False, annotation_type=False, outer_class=None, source_file=name + '.java', domain=domain)


def application(*classes, edges=(), domains=None, entry_http=()):
    facts = {c['fqn']: {k: v for k, v in c.items() if k != 'domain'} for c in classes}
    rows = [dict(id=c['fqn'], fqn=c['fqn'], simple_name=c['fqn'].rsplit('.', 1)[-1], package_name=P.rstrip('.'), class_type='INTERFACE' if c['interface'] else 'CLASS',
                 annotations=[a['type'] for a in c['annotations']], methods=[dict(name=m['name'], signature=m['signature'], annotations=m['annotations']) for m in c['methods']],
                 domain_id=c['domain'], method_count=len(c['methods']), field_count=len(c['fields'])) for c in classes]
    ids = sorted({c['domain'] for c in classes})
    result = dict(classes=rows, edges=[dict(source=P + s, target=P + t, dependency_type=k, id=f'e-{s}-{t}') for s, t, k in edges], external_edges=[], bytecode=dict(classes=facts),
                  domains=[dict(id=d, name=(domains or {}).get(d, d.upper()), classes=[c['fqn'] for c in classes if c['domain'] == d], confidence=0.8) for d in ids],
                  artifact=dict(sha256='a' * 64), algorithm_version='test', source_store=dict(status='NO_SOURCE_IN_ARTIFACT', index={}), issues=[])
    return InsightModel('t', result)


def run(model):
    result = analyze(model)
    assert result['status'] == 'AVAILABLE'
    return result


def labels(result, name, side='non_functional_responsibilities'):
    return {l['category']: l for l in result['components'][P + name][side]}


GET = ('org.springframework.web.bind.annotation.GetMapping', {'value': ['/x']})
POST = ('org.springframework.web.bind.annotation.PostMapping', {'value': ['/x']})


# ------------------------------------------------------------------------------------------ rules and taxonomy
def test_rules_register_every_category_and_reject_unknown_ones(tmp_path):
    rules = load_rules()
    assert len(rules['taxonomy']['functional']) == 8 and len(rules['taxonomy']['nonfunctional']) >= 15
    for rule in rules['rules']:
        assert rule['category'] in rules['taxonomy']['functional' if rule['side'] == 'FUNCTIONAL' else 'nonfunctional']
    bad = tmp_path / 'bad.yaml'
    bad.write_text(open(R.RULES_PATH).read().replace('category: SECURITY', 'category: NOT_A_CONCERN', 1))
    with pytest.raises(ValueError, match='not registered'):
        load_rules(str(bad))


def test_every_nonfunctional_category_in_the_brief_is_registered():
    wanted = {'SECURITY', 'PERFORMANCE', 'RELIABILITY', 'OBSERVABILITY', 'SCALABILITY', 'MAINTAINABILITY', 'CONFIGURATION', 'DATA_INTEGRITY', 'RESOURCE_MANAGEMENT', 'INTEROPERABILITY',
              'AUDITABILITY_AND_COMPLIANCE', 'TESTABILITY', 'EXTENSIBILITY', 'AVAILABILITY', 'PRIVACY_AND_DATA_PROTECTION'}
    assert wanted <= set(load_rules()['taxonomy']['nonfunctional'])
    assert {'BUSINESS_LOGIC', 'API_AND_APPLICATION_ENTRY', 'DOMAIN_MODEL', 'BUSINESS_DATA_ACCESS', 'BUSINESS_PROCESSING', 'EXTERNAL_BUSINESS_INTEGRATION', 'BUSINESS_VALIDATION', 'APPLICATION_ORCHESTRATION'} == set(load_rules()['taxonomy']['functional'])


# ------------------------------------------------------------------------------------------ classification
def test_declared_concerns_are_additional_not_mixed_and_a_service_stays_functional():
    service = klass('OrderService', annotations=[('org.springframework.stereotype.Service', {})],
                    methods=[method('place', annotations=[('org.springframework.transaction.annotation.Transactional', {})], branches=2, invokes=[(P + 'OrderRepository', 'save', 21)]),
                             method('retry', annotations=[('org.springframework.retry.annotation.Retryable', {})])])
    repository = klass('OrderRepository', interfaces=['org.springframework.data.jpa.repository.JpaRepository'], interface=True, methods=[method('save', abstract=True)])
    result = run(application(service, repository))
    component = result['components'][P + 'OrderService']
    assert component['primary_classification'] == 'FUNCTIONAL'
    assert labels(result, 'OrderService')['DATA_INTEGRITY']['status'] == 'DETECTED' and labels(result, 'OrderService')['RELIABILITY']['status'] == 'DETECTED'
    assert not any(l['mixes'] for l in component['non_functional_responsibilities'])
    assert labels(result, 'OrderService', 'functional_responsibilities')['BUSINESS_LOGIC']['status'] == 'INFERRED'
    assert result['components'][P + 'OrderRepository']['primary_classification'] == 'FUNCTIONAL_SUPPORT'


def test_a_class_that_runs_a_nonfunctional_concern_in_its_own_code_is_mixed():
    service = klass('PaymentService', annotations=[('org.springframework.stereotype.Service', {})],
                    methods=[method('pay', branches=1, invokes=[('org.slf4j.Logger', 'info', 30), (P + 'Ledger', 'post', 31)])])
    result = run(application(service, klass('Ledger')))
    component = result['components'][P + 'PaymentService']
    assert component['primary_classification'] == 'MIXED' and 'OBSERVABILITY' in component['classification_reasons'][0]
    evidence = result['evidence'][labels(result, 'PaymentService')['OBSERVABILITY']['evidence_ids'][0]]
    assert evidence['location']['start_line'] == 30 and evidence['member'].endswith('pay()')


def test_security_configuration_is_nonfunctional_with_security_and_configuration():
    config = klass('SecurityConfig', annotations=[('org.springframework.context.annotation.Configuration', {}), ('org.springframework.security.config.annotation.web.configuration.EnableWebSecurity', {})])
    result = run(application(config))
    assert result['components'][P + 'SecurityConfig']['primary_classification'] == 'NON_FUNCTIONAL'
    assert {'SECURITY', 'CONFIGURATION'} <= set(labels(result, 'SecurityConfig'))


def test_a_name_alone_never_decides_a_class_and_a_class_without_evidence_is_uncertain():
    named = klass('OrderService')                                # no annotation, no call: only the suffix "Service"
    util = klass('CommonUtils', methods=[method('format', branches=0)])
    result = run(application(named, util))
    for name in ('OrderService', 'CommonUtils'):
        assert result['components'][P + name]['primary_classification'] == 'UNCERTAIN'
        assert result['components'][P + name]['uncertainties']
    weak = labels(result, 'OrderService', 'functional_responsibilities')['BUSINESS_LOGIC']
    assert weak['status'] == 'INFERRED' and weak['confidence']['level'] == 'LOW' and weak['confidence']['calibrated'] is False


def test_primary_classification_ignores_measured_maintainability():
    util = klass('Helper', methods=[method('a')])
    model = application(util)
    model.result['issues'] = [dict(id='i', issue_type='GOD_CLASS', severity='HIGH', entity_id=P + 'Helper', entity_type='CLASS', title='Helper concentrates responsibilities', evidence={'method_count': {'value': 20, 'p95': 13.8}})]
    result = run(model)
    assert 'MAINTAINABILITY' in labels(result, 'Helper') and result['components'][P + 'Helper']['primary_classification'] == 'UNCERTAIN'


def test_a_class_can_carry_several_functional_and_nonfunctional_labels():
    controller = klass('OrderController', annotations=[('org.springframework.stereotype.Controller', {})],
                       methods=[method('submit', annotations=[POST], param_annotations=[['jakarta.validation.Valid']], params=('shop.Order',), invokes=[('org.springframework.validation.BindingResult', 'hasErrors', 40),
                                                                                                                                                     ('org.springframework.web.bind.WebDataBinder', 'setDisallowedFields', 41)])])
    result = run(application(controller, klass('Order')))
    functional = labels(result, 'OrderController', 'functional_responsibilities')
    assert functional['API_AND_APPLICATION_ENTRY']['status'] == 'DETECTED' and functional['BUSINESS_VALIDATION']['status'] == 'DETECTED'
    assert 'SECURITY' in labels(result, 'OrderController') and result['components'][P + 'OrderController']['primary_classification'] == 'MIXED'
    submit = next(m for m in result['components'][P + 'OrderController']['methods'] if m['name'] == 'submit')
    assert {(l['side'], l['category']) for l in submit['labels']} >= {('FUNCTIONAL', 'API_AND_APPLICATION_ENTRY'), ('NON_FUNCTIONAL', 'SECURITY')}


# ------------------------------------------------------------------------------------------ evidence
def test_every_label_cites_evidence_that_resolves_and_locations_are_marked_derived():
    controller = klass('C', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('go', annotations=[GET], lines=(7, 9))])
    result = run(application(controller))
    component = result['components'][P + 'C']
    for label in component['functional_responsibilities'] + component['non_functional_responsibilities']:
        assert label['evidence_ids'] and all(e in result['evidence'] for e in label['evidence_ids'])
    location = component['source_location']
    assert location['file_path'] == 'shop/C.java' and location['available'] is False and location['basis'].startswith('DERIVED')
    assert any('derived' in l for l in result['limitations'])


def test_only_call_sites_get_an_exact_line_and_annotations_get_the_method_body_range():
    controller = klass('C', annotations=[('org.springframework.stereotype.Controller', {})],
                       methods=[method('save', annotations=[POST], lines=(76, 90), params=('shop.Order',), param_annotations=[['jakarta.validation.Valid']], invokes=[('org.springframework.validation.BindingResult', 'hasErrors', 77)])])
    result = run(application(controller, klass('Order')))
    evidence = {e['text']: e['location'] for e in result['evidence'].values()}
    call = evidence['C.save() calls BindingResult.hasErrors()']
    assert call['start_line'] == 77 and call['line_basis'] == 'BYTECODE_LINE_NUMBER_TABLE'
    for text in ('C.save() is annotated @PostMapping', 'C.save() has a parameter annotated @Valid'):
        assert evidence[text]['start_line'] is None and evidence[text]['member_line_range'] == [76, 90] and evidence[text]['line_basis'] == 'METHOD_BODY_RANGE_FROM_LINE_NUMBER_TABLE'
    assert evidence['C is annotated @Controller']['line_basis'] == 'UNAVAILABLE' and evidence['C is annotated @Controller']['member_line_range'] is None


def test_captured_source_gives_the_real_archive_path():
    model = application(klass('C', annotations=[('org.springframework.stereotype.Controller', {})]))
    model.result['source_store'] = dict(status='SOURCE_CAPTURED', index={P + 'C': dict(archive_path='src/main/java/shop/C.java')})
    location = run(model)['components'][P + 'C']['source_location']
    assert (location['file_path'], location['available'], location['basis']) == ('src/main/java/shop/C.java', True, 'ARTIFACT_SOURCE_ENTRY')


def test_validation_rejects_evidence_that_names_a_missing_class_method_or_line():
    result = run(application(klass('C', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('go', annotations=[GET], invokes=[('org.slf4j.Logger', 'info', 11)], lines=(10, 12))])))
    model = application(klass('C', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('go', annotations=[GET], invokes=[('org.slf4j.Logger', 'info', 11)], lines=(10, 12))]))
    tampered = copy.deepcopy(result)
    good = next(e for e in tampered['evidence'].values() if e['member'])
    ghost_class = dict(good, id='x1', class_name='shop.Missing')
    ghost_method = dict(good, id='x2', member='void nope()')
    ghost_line = dict(good, id='x3', location=dict(good['location'], start_line=99))
    tampered['evidence'].update({'x1': ghost_class, 'x2': ghost_method, 'x3': ghost_line})
    report = validate(tampered, model)
    assert report['evidence_rejected'] == 3 and {r['reason'] for r in report['rejected']} == {'class not in snapshot', 'method not in class', 'line outside method'}
    assert all(i in tampered['evidence'] for l in tampered['components'][P + 'C']['non_functional_responsibilities'] for i in l['evidence_ids'])


def test_a_label_whose_evidence_is_rejected_becomes_unverified_not_deleted():
    model = application(klass('C', annotations=[('org.springframework.stereotype.Controller', {})]))
    result = run(model)
    only = result['components'][P + 'C']['functional_responsibilities'][0]
    result['evidence'].pop(only['evidence_ids'][0])
    validate(result, model)
    assert only['status'] == 'UNVERIFIED' and only['confidence']['level'] == 'LOW'


# ------------------------------------------------------------------------------------------ risks
def test_eager_relationships_are_flagged_and_lazy_ones_are_not():
    eager = klass('Owner', annotations=[('jakarta.persistence.Entity', {})], fields=[field('pets', 'java.util.Set', [('jakarta.persistence.OneToMany', {'fetch': 'FetchType.EAGER'})]),
                                                                                  field('visits', 'java.util.Set', [('jakarta.persistence.OneToMany', {'fetch': 'FetchType.LAZY'})]),
                                                                                  field('plain', 'java.util.Set', [('jakarta.persistence.OneToMany', {})])])
    risks = [r for r in run(application(eager))['risks'] if r['rule_id'] == 'RISK-PERF-EAGER-FETCH']
    assert len(risks) == 1 and 'pets' in risks[0]['description'] and 'visits' not in risks[0]['description'] and risks[0]['runtime_validation_required'] is True
    assert risks[0]['consequence_status'] == 'INFERRED' and risks[0]['detection_status'] == 'DETECTED'


def test_unbounded_repository_queries_are_flagged_unless_paged_or_single():
    repo = klass('Repo', interfaces=['org.springframework.data.jpa.repository.JpaRepository'], interface=True, methods=[
        method('all', returns='java.util.List', abstract=True), method('paged', params=('org.springframework.data.domain.Pageable',), returns='java.util.List', abstract=True),
        method('one', returns='shop.Thing', abstract=True)])
    risks = [r for r in run(application(repo, klass('Thing')))['risks'] if r['rule_id'] == 'RISK-PERF-UNBOUNDED-QUERY']
    assert [r['description'].split(' returns')[0] for r in risks] == ['Repo.all()']


def test_missing_access_control_is_an_inference_and_a_security_annotation_removes_it():
    open_controller = klass('A', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('save', annotations=[POST])])
    result = run(application(open_controller))
    [risk] = [r for r in result['risks'] if r['rule_id'] == 'RISK-SEC-NO-CONTROL']
    assert risk['detection_status'] == 'INFERRED' and risk['runtime_validation_required'] and 'POST' in risk['description'] and risk['confidence']['calibrated'] is False
    secured = klass('A', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('save', annotations=[POST, ('org.springframework.security.access.prepost.PreAuthorize', {})])])
    assert not [r for r in run(application(secured))['risks'] if r['rule_id'].startswith('RISK-SEC')]


def test_security_on_some_entry_points_only_is_reported_as_partial():
    secured = klass('A', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('save', annotations=[POST, ('org.springframework.security.access.prepost.PreAuthorize', {})])])
    open_one = klass('B', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('read', annotations=[GET])])
    rules = [r['rule_id'] for r in run(application(secured, open_one))['risks']]
    assert 'RISK-SEC-PARTIAL' in rules and 'RISK-SEC-NO-CONTROL' not in rules


def test_input_binding_restrictions_do_not_count_as_access_control():
    controller = klass('A', annotations=[('org.springframework.stereotype.Controller', {})], methods=[method('save', annotations=[POST], invokes=[('org.springframework.web.bind.WebDataBinder', 'setDisallowedFields', 5)])])
    [risk] = [r for r in run(application(controller))['risks'] if r['rule_id'] == 'RISK-SEC-NO-CONTROL']
    assert 'input-binding restrictions' in risk['description']


def test_logging_absence_is_reported_and_a_logger_reference_clears_it():
    plain = klass('A', methods=[method('x')])
    assert [r for r in run(application(plain))['risks'] if r['rule_id'] == 'RISK-OBS-NO-INSTRUMENTATION']
    logging = klass('A', fields=[field('log', 'org.slf4j.Logger', static=True, final=True)])
    assert not [r for r in run(application(logging))['risks'] if r['rule_id'] == 'RISK-OBS-NO-INSTRUMENTATION']


def test_persistent_classes_shared_across_candidate_domains_are_a_data_risk_only_across_domains():
    entity = klass('Person', annotations=[('jakarta.persistence.MappedSuperclass', {})], domain='d1')
    same = klass('Owner', super_name=P + 'Person', annotations=[('jakarta.persistence.Entity', {})], domain='d1')
    other = klass('Vet', super_name=P + 'Person', annotations=[('jakarta.persistence.Entity', {})], domain='d2')
    risks = [r for r in run(application(entity, same, other, edges=[('Owner', 'Person', 'INHERITANCE'), ('Vet', 'Person', 'INHERITANCE')], domains={'d1': 'Owners', 'd2': 'Vets'}))['risks'] if r['rule_id'] == 'RISK-DATA-SHARED-MODEL']
    assert len(risks) == 1 and 'Vets' in risks[0]['description'] and 'Owners' in risks[0]['description'] and set(risks[0]['affected_components']) == {P + 'Person', P + 'Vet'}


def test_a_transaction_that_calls_two_domains_is_flagged():
    a = klass('A', domain='d1', methods=[method('both', annotations=[('org.springframework.transaction.annotation.Transactional', {})], invokes=[(P + 'B', 'x', 5), (P + 'C', 'y', 6)])])
    risks = [r for r in run(application(a, klass('B', domain='d2'), klass('C', domain='d3'), edges=[('A', 'B', 'METHOD_CALL'), ('A', 'C', 'METHOD_CALL')]))['risks'] if r['rule_id'] == 'RISK-DATA-TX-SPAN']
    assert len(risks) == 1 and risks[0]['runtime_validation_required']


def test_mutable_static_state_is_detected_but_constants_and_loggers_are_not():
    state = klass('S', fields=[field('counter', 'int', static=True), field('LIMIT', 'int', static=True, final=True), field('log', 'org.slf4j.Logger', static=True)])
    result = run(application(state))
    [risk] = [r for r in result['risks'] if r['rule_id'] == 'RISK-SCAL-STATIC-STATE']
    assert '1 static non-final' in risk['description'] and 'SCALABILITY' in labels(result, 'S')


def test_remote_calls_without_protection_are_flagged_and_a_timeout_clears_it():
    client = klass('Client', methods=[method('call', invokes=[('org.springframework.web.client.RestTemplate', 'getForObject', 9)])])
    assert [r for r in run(application(client))['risks'] if r['rule_id'] == 'RISK-REL-NO-RESILIENCE']
    protected = klass('Client', methods=[method('call', invokes=[('org.springframework.web.client.RestTemplate', 'getForObject', 9), ('org.springframework.http.client.SimpleClientHttpRequestFactory', 'setReadTimeout', 8)])])
    assert not [r for r in run(application(protected))['risks'] if r['rule_id'] == 'RISK-REL-NO-RESILIENCE']


def test_an_external_client_is_both_interoperability_and_an_inferred_business_integration():
    client = klass('Client', methods=[method('call', invokes=[('org.springframework.web.client.RestTemplate', 'getForObject', 9)])])
    result = run(application(client))
    assert labels(result, 'Client')['INTEROPERABILITY']['status'] == 'DETECTED'
    assert labels(result, 'Client', 'functional_responsibilities')['EXTERNAL_BUSINESS_INTEGRATION']['status'] == 'INFERRED'


# ------------------------------------------------------------------------------------------ dependencies and cross-cutting
def test_dependencies_are_typed_and_cross_capability_edges_are_marked():
    controller = klass('C', annotations=[('org.springframework.stereotype.Controller', {})], domain='d1', methods=[method('go', annotations=[GET], invokes=[(P + 'R', 'find', 5)])])
    repo = klass('R', interfaces=['org.springframework.data.jpa.repository.JpaRepository'], interface=True, domain='d2')
    config = klass('Cfg', annotations=[('org.springframework.context.annotation.Configuration', {})], domain='d2')
    result = run(application(controller, repo, config, edges=[('C', 'R', 'METHOD_CALL'), ('C', 'Cfg', 'FIELD_TYPE')], domains={'d1': 'Web', 'd2': 'Data'}))
    by_target = {d['target'].rsplit('.', 1)[-1]: d for d in result['dependencies']}
    assert by_target['R']['relation'] == 'DATA_ACCESS' and by_target['R']['crosses_capability'] and by_target['R']['direct'] is True
    assert by_target['Cfg']['relation'] == 'TECHNICAL' and by_target['R']['evidence'][0]['kind'] == 'METHOD_CALL' and by_target['R']['evidence'][0]['line'] == 5
    assert result['components'][P + 'R']['dependents'][0]['source'] == P + 'C'


def test_shared_components_are_guided_toward_libraries_not_services():
    util = klass('Metrics', annotations=[('org.springframework.context.annotation.Configuration', {})], domain='d3')
    a = klass('A', domain='d1', fields=[field('m', P + 'Metrics')])
    b = klass('B', domain='d2', fields=[field('m', P + 'Metrics')])
    result = run(application(util, a, b, edges=[('A', 'Metrics', 'FIELD_TYPE'), ('B', 'Metrics', 'FIELD_TYPE')], domains={'d1': 'One', 'd2': 'Two', 'd3': 'Platform'}))
    [item] = [c for c in result['cross_cutting'] if c['component'] == P + 'Metrics']
    assert item['kind'] == 'SHARED_INFRASTRUCTURE' and item['deployment_form'] == 'SHARED_LIBRARY_OR_MODULE' and item['capability_count'] == 3
    assert 'library or module' in item['guidance'] and 'network call' in item['guidance'] and 'service candidate' not in item['guidance'].replace('not a service candidate', '')


def test_a_class_called_from_one_other_domain_is_a_dependency_not_a_shared_component():
    service = klass('PaymentService', annotations=[('org.springframework.stereotype.Service', {})], domain='pay')
    order = klass('OrderService', annotations=[('org.springframework.stereotype.Service', {})], domain='ord', fields=[field('pay', P + 'PaymentService')])
    result = run(application(service, order, edges=[('OrderService', 'PaymentService', 'FIELD_TYPE')], domains={'pay': 'Payment', 'ord': 'Orders'}))
    assert not [c for c in result['cross_cutting'] if c['component'] == P + 'PaymentService']          # one consumer domain: visible in the domain dependency matrix, not cross-cutting
    assert not [r for r in result['risks'] if r['rule_id'] == 'RISK-MAINT-SHARED-COMPONENT']
    other = klass('ReportService', annotations=[('org.springframework.stereotype.Service', {})], domain='rep', fields=[field('pay', P + 'PaymentService')])
    result = run(application(service, order, other, edges=[('OrderService', 'PaymentService', 'FIELD_TYPE'), ('ReportService', 'PaymentService', 'FIELD_TYPE')],
                             domains={'pay': 'Payment', 'ord': 'Orders', 'rep': 'Reports'}))
    [item] = [c for c in result['cross_cutting'] if c['component'] == P + 'PaymentService']
    assert item['capability_count'] == 3 and {c['name'] for c in item['capabilities']} == {'Payment', 'Orders', 'Reports'}


def test_capability_kind_distinguishes_business_technical_and_mixed_domains():
    business = [klass('Order', annotations=[('jakarta.persistence.Entity', {})], domain='b'), klass('OrderRepo', interfaces=['org.springframework.data.jpa.repository.JpaRepository'], interface=True, domain='b')]
    technical = [klass('Cfg1', annotations=[('org.springframework.context.annotation.Configuration', {})], domain='t'), klass('Cfg2', annotations=[('org.springframework.context.annotation.Configuration', {})], domain='t')]
    caps = run(application(*business, *technical, domains={'b': 'Orders', 't': 'Platform'}))['capabilities']
    assert (caps['b']['kind'], caps['t']['kind']) == ('BUSINESS', 'TECHNICAL')
    assert any(i['kind'] == 'NOT_AN_EXTRACTION_CANDIDATE' for i in caps['t']['implications'])
    assert caps['b']['boundary_confidence']['value'] == 0.8


def test_missing_bytecode_facts_is_reported_not_guessed():
    model = application(klass('C'))
    model.facts, model.facts_available = {}, False
    result = analyze(model)
    assert result['status'] == 'NOT_AVAILABLE' and 'Run a new analysis' in result['reason']


# ------------------------------------------------------------------------------------------ PetClinic ground truth
@pytest.fixture(scope='module')
def petclinic():
    model = InsightModel('petclinic', snapshot('petclinic'))
    return model, analyze(model)


def test_petclinic_every_class_is_classified_and_every_evidence_item_resolves(petclinic):
    model, result = petclinic
    tops = {c for c in model.classes if not model.is_nested(c)}
    assert set(result['components']) == tops
    assert result['validation']['evidence_rejected'] == 0 and result['validation']['evidence_checked'] == len(result['evidence'])
    for component in result['components'].values():
        for label in component['functional_responsibilities'] + component['non_functional_responsibilities']:
            assert label['evidence_ids'], (component['fqn'], label['category'])
    assert sum(result['summary']['by_primary'].values()) == len(tops)


def test_petclinic_controller_security_evidence_points_at_the_real_call_site(petclinic):
    model, result = petclinic
    owner = result['components']['org.springframework.samples.petclinic.owner.OwnerController']
    security = next(l for l in owner['non_functional_responsibilities'] if l['category'] == 'SECURITY')
    evidence = result['evidence'][security['evidence_ids'][0]]
    facts = model.facts[owner['fqn']]
    call = next((m, s) for m in facts['methods'] for s in m['invokes'] if s['owner'] == 'org.springframework.web.bind.WebDataBinder' and s['name'] == 'setDisallowedFields')
    assert evidence['member'] == call[0]['signature'] and evidence['location']['start_line'] == call[1]['line']
    assert owner['primary_classification'] == 'MIXED' and security['status'] == 'DETECTED'
    assert evidence['location']['file_path'].endswith('petclinic/owner/OwnerController.java') and evidence['location']['available'] is False


def test_petclinic_repositories_support_a_capability_and_carry_additional_concerns(petclinic):
    _, result = petclinic
    vet = result['components']['org.springframework.samples.petclinic.vet.VetRepository']
    assert vet['primary_classification'] == 'FUNCTIONAL_SUPPORT'
    assert {l['category'] for l in vet['functional_responsibilities']} == {'BUSINESS_DATA_ACCESS'}
    assert {'PERFORMANCE', 'DATA_INTEGRITY'} <= {l['category'] for l in vet['non_functional_responsibilities'] if l['status'] == 'DETECTED'}


def test_petclinic_cache_configuration_is_nonfunctional_and_controllers_are_functional_entry_points(petclinic):
    model, result = petclinic
    cache = result['components']['org.springframework.samples.petclinic.system.CacheConfiguration']
    assert cache['primary_classification'] == 'NON_FUNCTIONAL' and {'CONFIGURATION', 'PERFORMANCE'} <= {l['category'] for l in cache['non_functional_responsibilities']}
    handlers = {i['handler_class'] for i in model.entry_points['items'] if i.get('http_methods')}
    entry_classes = {f for f, c in result['components'].items() if any(l['category'] == 'API_AND_APPLICATION_ENTRY' for l in c['functional_responsibilities'])}
    assert handlers == entry_classes


def test_petclinic_entities_are_domain_model_and_dependencies_cover_every_internal_edge(petclinic):
    model, result = petclinic
    entities = {f for f, c in result['components'].items() if any(l['category'] == 'DOMAIN_MODEL' and l['status'] == 'DETECTED' for l in c['functional_responsibilities'])}
    assert {c for c in model.classes if any(a.endswith('.Entity') or a.endswith('.MappedSuperclass') for a in model.classes[c]['annotations'])} == entities
    internal = {(s, t) for (s, t) in model.owner_edges if s in result['components'] and t in result['components']}
    assert {(d['source'], d['target']) for d in result['dependencies']} == internal


def test_petclinic_is_deterministic_and_does_not_mutate_the_snapshot():
    snap = snapshot('petclinic')
    before = json.dumps(snap, sort_keys=True)
    a, b = analyze(InsightModel('p', snap)), analyze(InsightModel('p', snap))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str) and json.dumps(snap, sort_keys=True) == before
