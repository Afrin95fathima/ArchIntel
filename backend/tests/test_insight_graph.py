"""WP3 + WP11: node details, explained graph and unresolved classification."""
from app.insight.debt import detect
from app.insight.details import connection, node
from app.insight.graphview import classify_external, unresolved, view
from insight_fixtures import model, PETCLINIC


def test_unresolved_names_are_classified_with_first_reference():
    m = model('petclinic')
    result = unresolved(m)
    cats = {c['category']: c for c in result['categories']}
    assert set(cats) == {'JDK_CLASS', 'EXTERNAL_LIBRARY'}
    repo = next(i for i in cats['EXTERNAL_LIBRARY']['items'] if i['name'] == 'org.springframework.data.jpa.repository.JpaRepository')
    assert repo['first_reference']['kind'] == 'STATIC' and repo['first_reference']['source'] == f'{PETCLINIC}.owner.OwnerRepository'
    assert 'not in the uploaded artifact' in repo['explanation']
    assert classify_external('java.util.List') == 'JDK_CLASS' and classify_external('javax.sql.DataSource') == 'JDK_CLASS'
    assert classify_external('javax.persistence.Entity') == 'EXTERNAL_LIBRARY'
    assert classify_external('com.acme.Foo$$SpringCGLIB$$0') == 'GENERATED_OR_PROXY'


def test_runtime_only_and_unmatched_identities():
    runtime = dict(runtime_graph=dict(edges=[], nodes=[dict(id='runtime:com.acme.Legacy', name='com.acme.Legacy', static_id=None, node_type='CLASS', mapping_state='UNRESOLVED'),
        dict(id='runtime:GET /x', name='GET /x', static_id=None, node_type='CLASS'), dict(id='runtime:p.Svc$$SpringCGLIB$$0', name='p.Svc$$SpringCGLIB$$0', static_id=None, node_type='CLASS')]))
    cats = {c['category']: c for c in unresolved(model('petclinic', runtime))['categories']}
    assert cats['RUNTIME_ONLY']['items'][0]['name'] == 'com.acme.Legacy'
    assert cats['RUNTIME_ONLY']['items'][0]['first_reference']['kind'] == 'RUNTIME'
    assert cats['UNMATCHED_NAME']['count'] == 1 and cats['GENERATED_OR_PROXY']['count'] == 1


def test_package_view_explains_nodes_edges_and_what_is_shown():
    m = model('petclinic')
    data = view(m, 'package', debt=detect(m))
    owner = next(n for n in data['nodes'] if n['id'] == f'{PETCLINIC}.owner')
    assert owner['size'] == 11 and 'Placed in the' in owner['explanation']['why_here']
    edge = next(e for e in data['edges'] if e['source'] == f'{PETCLINIC}.owner' and e['target'] == f'{PETCLINIC}.model')
    assert edge['sources'] == ['static'] and 'inheritance' in edge['explanation']
    assert data['meta']['nodes_shown'] == data['meta']['nodes_total'] == 5
    assert "'External and unresolved' cluster" in data['meta']['external']
    assert data['external']['categories']


def test_class_view_threshold_and_truncation_are_reported():
    m = model('petclinic')
    data = view(m, 'class', min_weight=3, limit=10, debt=detect(m))
    assert data['meta']['nodes_shown'] == 10 and data['meta']['nodes_total'] == 24
    assert any('hidden (limit 10 nodes)' in h for h in data['meta']['hidden'])
    assert any('fewer than 3 references' in h for h in data['meta']['hidden'])


def test_class_detail_lists_role_dependencies_entry_points_and_summary():
    m = model('petclinic')
    data = node(m, f'{PETCLINIC}.owner.OwnerController', detect(m))
    assert data['what']['role'] == 'CONTROLLER' and data['what']['reason'] == 'annotated @org.springframework.stereotype.Controller'
    assert data['breadcrumb'][1]['label'] == f'{PETCLINIC}.owner'
    assert [d['name'] for d in data['depends_on']][:1] == ['Owner']
    routes = sorted(e['description'] for e in data['entry_points'])
    assert 'GET /owners/{ownerId}' in routes and len(routes) == 7
    assert data['coverage']['status'] == 'NOT_AVAILABLE'
    assert any(f['rule_id'] == 'DEBT-ENTITY-IN-CONTROLLER' for f in data['debt'])
    assert data['summary'].startswith('OwnerController is a class whose role is controller')
    assert 'It declares 7 entry points' in data['summary']


def test_package_and_method_detail_and_connection():
    m = model('petclinic')
    debt = detect(m)
    package = node(m, f'{PETCLINIC}.owner', debt)
    assert package['kind'] == 'PACKAGE' and package['size']['classes'] == 11
    assert package['depends_on'][0]['id'] == f'{PETCLINIC}.model'
    method_id = f'{PETCLINIC}.owner.Owner#addVisit(Ljava/lang/Integer;Lorg/springframework/samples/petclinic/owner/Visit;)V'
    method = node(m, method_id, debt)
    assert method['kind'] == 'METHOD' and {c['label'] for c in method['calls']} >= {'Owner.getPet()', 'Pet.addVisit()'}
    assert [c['label'] for c in method['called_by']] == ['VisitController.processNewVisitForm()']
    why = connection(m, f'{PETCLINIC}.owner', f'{PETCLINIC}.model')
    assert why['pair_count'] >= 4 and why['pairs'][0]['references']
    pair = connection(m, f'{PETCLINIC}.owner.PetController', f'{PETCLINIC}.owner.PetValidator')
    assert any('PetValidator constructor' in r['text'] for r in pair['references'])
    system = node(m, 'system', debt)
    assert system['size']['classes'] == 24 and system['entry_points'] == 18
