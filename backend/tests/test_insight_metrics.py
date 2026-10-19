"""WP5: metrics against hand-computed expectations."""
import pytest
from app.config import Settings
from app.services.engine import analyze
from app.insight.model import InsightModel
from app.insight.metrics import compute, layer_violations
from helpers import cls, edge
from insight_fixtures import model


@pytest.fixture(scope='module')
def small():
    classes = [cls('p.a.A1', abstract=True), cls('p.a.A2'), cls('p.b.B1'), cls('p.b.B2', interface=True), cls('p.c.C1')]
    edges = [edge('p.a.A1', 'p.b.B1'), edge('p.a.A2', 'p.b.B1'), edge('p.a.A2', 'p.b.B2'), edge('p.b.B1', 'p.c.C1'), edge('p.c.C1', 'p.a.A1')]
    return compute(InsightModel('small', analyze(classes, edges, Settings(_env_file=None))))


def value(rows, entity, key):
    return next(r for r in rows if r['id'] == entity)['metrics'][key]['value']


def test_package_coupling_instability_abstractness_distance(small):
    p = small['packages']
    #               Ca  Ce   I       A    D
    expected = {'p.a': (1, 2, .6667, .5, .1667), 'p.b': (2, 1, .3333, .5, .1667), 'p.c': (1, 1, .5, 0.0, .5)}
    for package, (ca, ce, i, a, d) in expected.items():
        assert value(p, package, 'package.Ca') == ca
        assert value(p, package, 'package.Ce') == ce
        assert value(p, package, 'package.I') == pytest.approx(i, abs=1e-4)
        assert value(p, package, 'package.A') == pytest.approx(a, abs=1e-4)
        assert value(p, package, 'package.D') == pytest.approx(d, abs=1e-4)
    pa = next(r for r in p if r['id'] == 'p.a')['metrics']
    assert pa['package.Ca']['inputs'] == ['p.c.C1'] and pa['package.Ce']['inputs'] == ['p.b.B1', 'p.b.B2']
    assert pa['package.A']['inputs'] == ['p.a.A1']


def test_class_fan_in_fan_out_and_cycles(small):
    c = small['classes']
    assert {x['id']: (x['metrics']['class.fan_in']['value'], x['metrics']['class.fan_out']['value']) for x in c} == {
        'p.a.A1': (1, 1), 'p.a.A2': (0, 2), 'p.b.B1': (2, 1), 'p.b.B2': (1, 0), 'p.c.C1': (1, 1)}
    assert value(c, 'p.b.B1', 'class.cycle_groups') == 1 and value(c, 'p.a.A2', 'class.cycle_groups') == 0
    assert value(small['packages'], 'p.a', 'package.cycle_groups') == 2          # one package group + one class group
    assert value(small['packages'], 'p.a', 'package.largest_cycle') == 3
    assert small['worst']['class.fan_in'][0] == {'id': 'p.b.B1', 'value': 2, 'state': 'ok'}


def test_every_metric_has_formula_meaning_and_threshold(small):
    for key, definition in small['definitions'].items():
        assert definition['formula'] and definition['plain'], key
    assert small['definitions']['package.D']['threshold'] == {'warn': .5, 'over': .7}
    assert value(small['packages'], 'p.c', 'package.D') == .5
    pc = next(r for r in small['packages'] if r['id'] == 'p.c')['metrics']['package.D']['indicator']
    assert pc['state'] == 'ok'                                              # 0.5 is not above warn 0.5


def test_bytecode_size_and_complexity_from_class_files():
    rows = compute(model('edgecases'))['classes']
    address = next(r for r in rows if r['name'] == 'Address')['metrics']
    # <init>: aload_0, invokespecial, return = 5 bytes; region(): new, dup, invokespecial, areturn = 8 bytes.
    assert address['class.bytecode_size']['value'] == 13
    assert address['class.max_method_size'] == {'value': 8, 'indicator': {'state': 'ok', 'warn': 1000, 'over': 8000}, 'inputs': ['region'], 'input_count': 1}
    assert address['class.complexity']['value'] == 2
    service = next(r for r in rows if r['name'] == 'ItemService')
    assert sorted(service['nested_classes']) == ['com.fixture.edge.model.ItemService$1', 'com.fixture.edge.model.ItemService$NameOrder', 'com.fixture.edge.model.ItemService$Tracker']
    assert 'lambda$delete$0' not in service['metrics']['class.method_count']['inputs']


def test_layer_violations_name_both_classes():
    rows = layer_violations(model('petclinic'))
    assert not [r for r in rows if r['kind'] == 'VIOLATION']
    assert not [r for r in rows if r['kind'] == 'SKIP']       # PetClinic has no service layer, so no skip findings
