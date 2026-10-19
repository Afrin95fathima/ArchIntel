"""WP2: diagram models with known content."""
from app.insight.debt import detect
from app.insight.details import connection, node
from app.insight.diagrams import hld, lld, sequence_runtime, sequence_static
from insight_fixtures import model, PETCLINIC

OWNER = f'{PETCLINIC}.owner.'


def test_hld_layers_externals_entry_points_and_counts():
    d = hld(model('petclinic'))
    layers = {l['layer']: l for l in d['layers']}
    assert layers['PRESENTATION']['class_count'] == 6 and layers['PRESENTATION']['roles'] == {'CONTROLLER': 6}
    assert layers['DATA_ACCESS']['class_count'] == 3
    assert layers['DOMAIN']['roles'] == {'ENTITY': 9, 'MODEL': 1}            # 6 @Entity + 3 @MappedSuperclass; Vets is @XmlRootElement
    assert [e['key'] for e in d['externals']] == ['DATABASE']
    db = d['externals'][0]
    assert db['class_count'] > 0 and any('references' in e for e in db['evidence'])
    entries = {e['kind']: e['count'] for e in d['entry_points']}
    assert entries == {'HTTP_ENDPOINT': 17, 'MAIN_METHOD': 1}
    edge = next(e for e in d['edges'] if e['id'] == 'layer:PRESENTATION->layer:DATA_ACCESS')
    assert edge['class_pairs'] == 5 and edge['observed'] is False and 'no runtime session selected' in edge['explanation']
    assert any(e['id'] == 'layer:DATA_ACCESS->external:DATABASE' for e in d['edges'])
    assert not any(e['against_layering'] for e in d['edges'])
    assert len(d['how_to_read']) >= 4


def test_hld_marks_observed_edges_and_reverse_layering():
    runtime = dict(runtime_graph=dict(nodes=[dict(id=OWNER + 'OwnerController', static_id=OWNER + 'OwnerController'), dict(id=OWNER + 'OwnerRepository', static_id=OWNER + 'OwnerRepository')],
        edges=[dict(source=OWNER + 'OwnerController', target=OWNER + 'OwnerRepository', call_count=7)]))
    edge = next(e for e in hld(model('petclinic', runtime))['edges'] if e['id'] == 'layer:PRESENTATION->layer:DATA_ACCESS')
    assert edge['observed'] and edge['runtime_calls'] == 7 and '7 calls observed at runtime' in edge['explanation']
    legacy = hld(model('edgecases'))
    reverse = next(e for e in legacy['edges'] if e['id'] == 'layer:DOMAIN->layer:PRESENTATION')
    assert reverse['against_layering'] is True


def test_lld_lists_classes_entry_methods_tables_and_edges():
    d = lld(model('petclinic'), f'{PETCLINIC}.owner')
    names = {c['name']: c for c in d['classes']}
    assert len(names) == 11 and names['Owner']['table'] == 'owners' and names['Visit']['table'] == 'visits'
    assert {t['table'] for t in d['tables']} == {'owners', 'pets', 'types', 'visits'}
    assert {e['text'] for e in names['VisitController']['entry_points']} == {'GET /owners/{ownerId}/pets/{petId}/visits/new', 'POST /owners/{ownerId}/pets/{petId}/visits/new'}
    edge = next(e for e in d['edges'] if e['source'] == OWNER + 'Owner' and e['target'] == OWNER + 'Pet')
    assert edge['references'] >= 2 and not edge['observed']
    assert lld(model('petclinic'), 'no.such')['status'] == 'NOT_AVAILABLE'


def test_static_sequence_follows_source_order_and_is_labelled():
    m = model('petclinic')
    entry = next(e for e in m.entry_points['items'] if e['handler_method'] == 'processNewVisitForm')
    flow = sequence_static(m, entry['id'])
    assert flow['origin'] == 'STATIC' and 'not what was observed' in flow['note']
    assert [p['label'] for p in flow['participants']][:2] == ['VisitController', 'Owner'] and 'OwnerRepository' in [p['label'] for p in flow['participants']]
    labels = [(m_['source'].rsplit('.', 1)[-1], m_['label']) for m_ in flow['messages']]
    assert labels[0] == ('VisitController', 'addVisit()') and ('VisitController', 'save()') in labels
    assert labels.index(('VisitController', 'addVisit()')) < labels.index(('VisitController', 'save()'))
    assert all(m_['origin'] == 'static' for m_ in flow['messages'])


def test_runtime_sequence_orders_spans_by_parent_and_time():
    m = model('petclinic')
    def span(i, parent, cls, method, t, **kw):
        return dict(session_id='s', trace_id='t', span_id=str(i), parent_span_id=parent, class_name=cls, method_name=method, timestamp=t, duration_ms=2, error=False, event_type=kw.get('type', 'METHOD'), **{k: v for k, v in kw.items() if k != 'type'})
    events = [span(1, None, OWNER + 'VisitController', 'processNewVisitForm', 1, type='HTTP_SERVER', http_route='/owners/{ownerId}/pets/{petId}/visits/new', http_method='POST'),
        span(2, '1', OWNER + 'Owner', 'addVisit', 2), span(3, '1', OWNER + 'OwnerRepository', 'save', 3), span(4, '3', None, None, 4, type='DB', database_operation='INSERT', database_table='visits')]
    flow = sequence_runtime(events, m, 'POST', '/owners/{ownerId}/pets/{petId}/visits/new')
    assert flow['origin'] == 'RUNTIME' and flow['entry'] == 'POST /owners/{ownerId}/pets/{petId}/visits/new'
    assert [(x['label']) for x in flow['messages']] == ['addVisit()', 'save()', 'INSERT']
    assert sequence_runtime(events, m, 'GET', '/other')['status'] == 'NOT_AVAILABLE'


def test_layer_and_external_nodes_and_connections_share_the_detail_panel():
    m = model('petclinic')
    debt = detect(m)
    layer = node(m, 'layer:PRESENTATION', debt)
    assert layer['kind'] == 'LAYER' and layer['size']['classes'] == 6 and layer['depends_on'][0]['id'].startswith('layer:')
    assert node(m, 'external:DATABASE', debt)['kind'] == 'EXTERNAL'
    why = connection(m, 'layer:PRESENTATION', 'layer:DATA_ACCESS')
    assert why['level'] == 'LAYER' and why['pair_count'] == 5 and why['pairs'][0]['references']
    assert connection(m, 'layer:DATA_ACCESS', 'external:DATABASE')['pair_count'] > 0
