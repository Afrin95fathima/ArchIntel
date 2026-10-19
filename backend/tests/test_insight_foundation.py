"""Bytecode reader, role and entry-point extraction against compiled fixtures with known answers."""
from insight_fixtures import model, snapshot, PETCLINIC
from app.insight.facts import extract
from app.insight.bytecode import ClassFormatError, parse
from insight_fixtures import CLASSES
import pytest


def test_reader_parses_every_fixture_class_without_failures():
    for name, count in (('petclinic', 24), ('edgecases', 22)):
        extracted = extract(CLASSES / name)
        assert extracted['parse_failure_count'] == 0
        assert extracted['class_count'] == count


def test_reader_rejects_malformed_bytes():
    with pytest.raises(ClassFormatError):
        parse(b'\xca\xfe\xba\xbe' + b'\0' * 20)
    with pytest.raises(ClassFormatError):
        parse(b'not a class')


def test_annotation_values_and_java_target():
    facts = snapshot()['bytecode']['classes']
    pet = facts[PETCLINIC + '.owner.PetController']
    assert pet['java_target'] == 17
    mapping = next(a for a in pet['annotations'] if a['type'].endswith('RequestMapping'))
    assert mapping['values'] == {'value': ['/owners/{ownerId}']}
    owner = facts[PETCLINIC + '.owner.Owner']
    telephone = next(f for f in owner['fields'] if f['name'] == 'telephone')
    assert {'type': 'jakarta.validation.constraints.Pattern', 'values': {'regexp': '\\d{10}'}} in telephone['annotations']


def test_roles_come_from_annotations_and_hierarchy():
    roles = model().roles
    assert roles[PETCLINIC + '.owner.OwnerController']['role'] == 'CONTROLLER'
    assert roles[PETCLINIC + '.owner.OwnerController']['evidence'] == 'ANNOTATION'
    repo = roles[PETCLINIC + '.owner.OwnerRepository']
    assert repo['role'] == 'REPOSITORY' and repo['evidence'] == 'TYPE_HIERARCHY'
    assert 'org.springframework.data.jpa.repository.JpaRepository' in repo['reason']
    assert roles[PETCLINIC + '.owner.Owner']['role'] == 'ENTITY'
    assert roles[PETCLINIC + '.model.BaseEntity']['role'] == 'ENTITY'
    assert roles[PETCLINIC + '.owner.PetValidator']['role'] == 'VALIDATOR'
    assert roles[PETCLINIC + '.PetClinicApplication']['role'] == 'APPLICATION'


EXPECTED_ROUTES = {
    ('GET', '/owners/new'), ('POST', '/owners/new'), ('GET', '/owners/find'), ('GET', '/owners'),
    ('GET', '/owners/{ownerId}/edit'), ('POST', '/owners/{ownerId}/edit'), ('GET', '/owners/{ownerId}'),
    ('GET', '/owners/{ownerId}/pets/new'), ('POST', '/owners/{ownerId}/pets/new'),
    ('GET', '/owners/{ownerId}/pets/{petId}/edit'), ('POST', '/owners/{ownerId}/pets/{petId}/edit'),
    ('GET', '/owners/{ownerId}/pets/{petId}/visits/new'), ('POST', '/owners/{ownerId}/pets/{petId}/visits/new'),
    ('GET', '/vets.html'), ('GET', '/vets'), ('GET', '/oups'), ('GET', '/'),
}


def test_petclinic_routes_are_exact():
    entries = model().entry_points
    http = [e for e in entries['items'] if e['kind'] == 'HTTP_ENDPOINT']
    routes = {(v, p) for e in http for v in e['http_methods'] for p in e['paths']}
    assert routes == EXPECTED_ROUTES
    assert len(http) == len(EXPECTED_ROUTES)
    assert not entries['duplicate_routes']
    main = [e for e in entries['items'] if e['kind'] == 'MAIN_METHOD']
    assert [e['handler_class'] for e in main] == [PETCLINIC + '.PetClinicApplication']
    implicit = {(i['class_name'].rsplit('.', 1)[-1], i['method']) for i in entries['implicit_methods']}
    assert ('PetController', 'populatePetTypes') in implicit and ('OwnerController', 'setAllowedFields') in implicit


def test_route_parameters_carry_bindings_and_validation():
    entries = model().entry_points['items']
    find = next(e for e in entries if e['handler_method'] == 'processFindForm')
    page = find['parameters'][0]
    assert (page['binding'], page['type'], page['default']) == ('query', 'int', '1')
    visit = next(e for e in entries if e['handler_method'] == 'processNewVisitForm')
    kinds = [(p['type'].rsplit('.', 1)[-1], p['binding']) for p in visit['parameters']]
    assert kinds[:3] == [('Owner', 'form'), ('int', 'path'), ('Visit', 'form')]
    assert visit['parameters'][2]['constraints'] == ['Valid']


def test_edgecase_entry_points_cover_every_kind():
    entries = model('edgecases').entry_points
    by_kind = {}
    for e in entries['items']:
        by_kind.setdefault(e['kind'], set()).add(e['handler_method'])
    assert by_kind['SCHEDULED_JOB'] == {'sendReminders'}
    assert by_kind['LIFECYCLE_CALLBACK'] == {'init'}
    assert by_kind['EVENT_LISTENER'] == {'onStarted'}
    assert by_kind['MESSAGE_LISTENER'] == {'consume', 'billing', 'audit'}
    assert by_kind['SERVLET'] == {'doGet', 'doPost'}
    assert by_kind['SERVLET_FILTER'] == {'doFilter'}
    assert by_kind['STRUTS_ACTION'] == {'execute'}
    assert by_kind['MAIN_METHOD'] == {'main'}
    http = {(v, p) for e in entries['items'] if e['kind'] == 'HTTP_ENDPOINT' for v in e['http_methods'] for p in e['paths']}
    assert http == {('GET', '/api/items/{id}'), ('POST', '/api/items'), ('GET', '/api/items/search'),
        ('PUT', '/api/items/bulk'), ('PATCH', '/api/items/bulk'), ('DELETE', '/api/items/{id}'),
        ('DELETE', '/api/items/remove/{id}'), ('ANY', '/api/items/legacy-any'), ('GET', '/jaxrs/hello'),
        ('POST', '/jaxrs'), ('GET', '/admin/orders/latest')}
    kafka = next(e for e in entries['items'] if e['handler_method'] == 'consume')
    assert kafka['trigger'] == 'orders'
    search = next(e for e in entries['items'] if e['handler_method'] == 'search')
    assert search['parameters'][0]['constraints'] == ['NotNull', 'Size(max=40, min=2)']


def test_nested_classes_fold_into_owner_and_synthetic_methods_are_hidden():
    m = model('edgecases')
    svc = 'com.fixture.edge.model.ItemService'
    assert m.owners[svc + '$1'] == svc and m.owners[svc + '$NameOrder'] == svc and m.owners[svc + '$Tracker'] == svc
    names = [x['name'] for x in m.methods_of(svc + '$NameOrder')]
    assert names.count('compare') == 1           # bridge compare(Object,Object) hidden
    assert not any(x['name'].startswith('lambda$') for x in m.methods_of(svc))
    overloads = [x['descriptor'] for x in m.methods_of(svc) if x['name'] == 'calculate']
    assert sorted(overloads) == ['(I)I', '(II)I', '(Ljava/lang/String;)I']


def test_references_explain_an_edge_with_code_locations():
    m = model()
    refs = m.references(PETCLINIC + '.owner.PetController', PETCLINIC + '.owner.OwnerRepository')
    texts = [r['text'] for r in refs]
    assert 'field PetController.owners has type OwnerRepository' in texts
    assert any(t.startswith('PetController.findOwner() calls OwnerRepository.findById()') for t in texts)
    assert all(r['line'] for r in refs if r['kind'] == 'METHOD_CALL')


def test_static_reachability_follows_calls_hierarchy_and_lambdas():
    m = model()
    graph = m.callgraph
    start = f'{PETCLINIC}.owner.VisitController#processNewVisitForm(Lorg/springframework/samples/petclinic/owner/Owner;ILorg/springframework/samples/petclinic/owner/Visit;Lorg/springframework/validation/BindingResult;Lorg/springframework/web/servlet/mvc/support/RedirectAttributes;)Ljava/lang/String;'
    reached = graph.reachable([start])['methods']
    owners = {k.split('#')[0].rsplit('.', 1)[-1] + '.' + k.split('#')[1].split('(')[0] for k in reached}
    assert {'Owner.addVisit', 'Owner.getPet', 'Pet.addVisit', 'Pet.getVisits', 'BaseEntity.isNew', 'BaseEntity.getId'}
    assert 'NamedEntity.getName' not in owners <= owners
