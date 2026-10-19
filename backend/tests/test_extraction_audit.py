"""WP9: extraction and mapping audit. Each test failed before its fix (see docs/BUGS-FOUND.md)."""
import pytest
from app.config import Settings
from app.insight.facts import extract, referenced_types
from app.insight.scan import scanner_rows
from app.services.engine import analyze
from app.services.runtime.coverage import calculate
from app.services.runtime.entry_points import is_method_entry_point
from app.services.runtime.mapping import map_class
from app.services.domain_analysis import _edge_group
from insight_fixtures import CLASSES, snapshot

ITEM = 'com.fixture.edge.model.ItemService'


# BUG-01: runtime identities that use the canonical (dotted) name of a nested class never matched `Outer$Inner`.
@pytest.mark.parametrize('name,state,target', [
    ('com.x.Outer.Inner', 'NESTED_RESOLVED', 'com.x.Outer$Inner'),
    ('com.x.Outer.Inner.Deep', 'NESTED_RESOLVED', 'com.x.Outer$Inner$Deep'),
    ('com.x.Outer$Inner', 'EXACT', 'com.x.Outer$Inner'),
    ('com.x.Outer.Missing', 'UNRESOLVED', None)])
def test_dotted_nested_class_names_resolve(name, state, target):
    classes = {'com.x.Outer': {}, 'com.x.Outer$Inner': {}, 'com.x.Outer$Inner$Deep': {}}
    mapped = map_class(name, classes)
    assert (mapped['state'], mapped['static_id']) == (state, target)


# BUG-02: lambda classes and other generated proxies were reported as unresolved instead of resolving to their owner.
@pytest.mark.parametrize('name', ['com.x.Outer$$Lambda$14/0x0000000800c03000', 'com.x.Outer$$Lambda/0x0000000801000a00',
    'com.x.Outer$$FastClassBySpringCGLIB$$9f1a', 'com.x.Outer$$EnhancerByCGLIB$$ab12', 'com.x.Outer$HibernateProxy$Zk3',
    'com.x.Outer_$$_jvst1a_2', 'com.x.Outer$ByteBuddy$a1b2'])
def test_generated_classes_resolve_to_owner_with_lower_confidence(name):
    mapped = map_class(name, {'com.x.Outer': {}})
    assert mapped['static_id'] == 'com.x.Outer' and mapped['state'] in ('PROXY_RESOLVED', 'LAMBDA_RESOLVED') and mapped['confidence'] < 1


def test_unrelated_names_still_unresolved():
    assert map_class('jdk.proxy2.$Proxy7', {'com.x.Outer': {}})['static_id'] is None
    assert map_class('com.y.Outer$$Lambda$1/0x1', {'com.x.Outer': {}})['static_id'] is None


# BUG-03: any annotation with a matching simple name (a project's own @GET, @Scheduled) was an entry point.
@pytest.mark.parametrize('annotations,expected', [
    (['com.acme.GET'], False), (['com.acme.Scheduled'], False), (['org.example.Path'], False),
    (['org.springframework.web.bind.annotation.GetMapping'], True), (['javax.ws.rs.GET'], True), (['jakarta.ws.rs.POST'], True),
    (['org.springframework.scheduling.annotation.Scheduled'], True), (['org.springframework.kafka.annotation.KafkaListener'], True),
    (['org.springframework.context.event.EventListener'], True), (['GetMapping'], True)])
def test_entry_point_annotations_are_matched_by_package(annotations, expected):
    assert is_method_entry_point(annotations) is expected


# BUG-04: synthetic, bridge and lambda methods inflated the method and entry-point populations.
def test_coverage_population_excludes_synthetic_bridge_and_lambda_methods():
    classes = [dict(id='p.A', domain_id='d', methods=[
        dict(name='run', signature='void run()', annotations=[]), dict(name='lambda$run$0', signature='void lambda$run$0()', annotations=[]),
        dict(name='access$000', signature='int access$000(p.A)', annotations=[]), dict(name='compare', signature='int compare(java.lang.Object,java.lang.Object)', annotations=[], bridge=True),
        dict(name='hidden', signature='void hidden()', annotations=[], synthetic=True)])]
    static = dict(classes=classes, edges=[], domains=[dict(id='d', name='D', classes=['p.A'])])
    result = calculate(static, dict(nodes=[], edges=[], missing_parent_count=0), events=[])
    assert result['methods']['total'] == 1


# BUG-05: exception and generic-type dependencies were grouped as 'OTHER' in boundary analysis.
@pytest.mark.parametrize('kind,group', [('EXCEPTION', 'FIELD_OR_TYPE_REFERENCE'), ('GENERIC_TYPE', 'FIELD_OR_TYPE_REFERENCE'),
    ('RETURN_TYPE', 'FIELD_OR_TYPE_REFERENCE'), ('PARAMETER_TYPE', 'FIELD_OR_TYPE_REFERENCE'), ('METHOD_CALL', 'CALL')])
def test_edge_groups(kind, group):
    assert _edge_group(kind) == group


# BUG-06: scanner edges had no parameter, return or method/field-annotation dependencies from jQAssistant (only the
# untyped DEPENDS_ON fallback), so these appeared as OTHER or were missing. Bytecode supplies them.
def test_supplemental_edges_add_missing_dependency_types():
    from app.insight.scan import supplement
    extracted = extract(CLASSES / 'edgecases')
    classes, base = scanner_rows(extracted)
    pair = ('com.fixture.edge.web.ItemController', 'com.fixture.edge.model.Item')
    jqa_like = [dict(source=pair[0], target=pair[1], dependency_type='OTHER'), dict(source=pair[0], target='com.fixture.edge.model.ItemService', dependency_type='FIELD_TYPE')]
    merged = supplement(jqa_like, extracted)
    kinds = {e['dependency_type'] for e in merged if (e['source'], e['target']) == pair}
    assert kinds >= {'PARAMETER_TYPE', 'RETURN_TYPE'} and 'OTHER' not in kinds
    assert sum(1 for e in merged if (e['source'], e['target'], e['dependency_type']) == (pair[0], 'com.fixture.edge.model.ItemService', 'FIELD_TYPE')) == 1


# BUG-07: nested, anonymous and local classes were counted as classes, so class counts disagreed between pages.
def test_summary_reports_top_level_and_nested_counts():
    summary = snapshot('edgecases')['summary']
    assert summary['class_count'] == 22 and summary['top_level_class_count'] == 19 and summary['nested_class_count'] == 3


# ---- Fixture truth: assertions that passed from the start and guard against regressions ----------------------------
def test_fixture_methods_overloads_bridges_lambdas_constructors():
    facts = extract(CLASSES / 'edgecases')['classes']
    service = facts[ITEM]
    calc = sorted(m['signature'] for m in service['methods'] if m['name'] == 'calculate')
    assert calc == ['int calculate(int)', 'int calculate(int,int)', 'int calculate(java.lang.String)']
    assert [m['name'] for m in service['methods'] if m['kind'] != 'method'] == ['<init>', '<clinit>']
    assert next(m for m in service['methods'] if m['name'].startswith('lambda$'))['synthetic'] is True
    comparator = facts[ITEM + '$NameOrder']
    assert sum(m['name'] == 'compare' for m in comparator['methods']) == 2          # real + bridge
    assert sum(m['name'] == 'compare' and m['bridge'] for m in comparator['methods']) == 1
    assert facts[ITEM + '$1']['anonymous'] is True and facts[ITEM + '$1']['outer_class'] == ITEM
    assert facts[ITEM + '$Tracker']['outer_class'] == ITEM and facts[ITEM + '$Tracker']['anonymous'] is False


def test_fixture_dependency_types_cover_all_reference_kinds():
    facts = extract(CLASSES / 'petclinic')['classes']
    refs = referenced_types(facts['org.springframework.samples.petclinic.owner.OwnerRepository'])
    assert 'org.springframework.data.jpa.repository.JpaRepository' in refs['INTERFACE']
    assert {'org.springframework.samples.petclinic.owner.Owner'} <= refs['GENERIC_TYPE']
    assert 'org.springframework.data.domain.Page' in refs['RETURN_TYPE'] and 'org.springframework.data.domain.Pageable' in refs['PARAMETER_TYPE']
    exceptions = referenced_types(facts['org.springframework.samples.petclinic.owner.PetTypeFormatter'])['EXCEPTION']
    assert exceptions == {'java.text.ParseException'}
    assert 'org.springframework.data.jpa.repository.Query' in referenced_types(facts['org.springframework.samples.petclinic.owner.PetTypeRepository'])['ANNOTATION']


def test_edge_direction_is_dependent_to_dependency_and_deduplicated():
    result = snapshot('petclinic')
    pairs = [(e['source'], e['target'], e['dependency_type']) for e in result['edges']]
    assert len(pairs) == len(set(pairs))
    assert ('org.springframework.samples.petclinic.owner.OwnerController', 'org.springframework.samples.petclinic.owner.OwnerRepository', 'FIELD_TYPE') in pairs
    assert not any(s == 'org.springframework.samples.petclinic.owner.OwnerRepository' and t.endswith('OwnerController') for s, t, _ in pairs)


# BUG-08: the snapshot entry-point inventory (annotation names only, 'UNKNOWN' routes) disagreed with the insight pages.
def test_snapshot_inventory_and_insight_pages_agree_on_entry_points():
    from insight_fixtures import model
    result = snapshot('petclinic')
    inventory = result['entry_points']['items']
    insight = [e for e in model('petclinic').entry_points['items'] if e['kind'] != 'LIFECYCLE_CALLBACK']
    assert len(inventory) == len(insight) == 18
    owner = next(i for i in inventory if i['handler_signature'].startswith('java.lang.String processNewVisitForm'))
    assert (owner['http_method'], owner['path']) == ('POST', '/owners/{ownerId}/pets/{petId}/visits/new')
