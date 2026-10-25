"""Support for large multi-module codebases: generated-code exclusion, bounded facts that degrade step by step,
Maven version resolution across parent poms and in-archive BOMs, and lifecycle package exclusions."""
import json
import shutil
from types import SimpleNamespace

from app.insight.facts import bounded_for_snapshot, extract
from app.insight.generated import detect, exclude
from app.insight.lifecycle import package_usage
from app.services.tech_stack import _maven_dependencies
from insight_fixtures import CLASSES


def summary(fqn, super_name='java.lang.Object', annotations=(), static_fields=(), field_types=(), constructor_params=(), interfaces=()):
    return dict(fqn=fqn, super_name=super_name, interfaces=list(interfaces), annotations=list(annotations), static_fields=list(static_fields),
                field_types=list(field_types), constructor_params=list(constructor_params))


def test_generators_are_recognised_from_bytecode_facts_not_names():
    client = 'com.acme.client'
    rows = [
        summary('com.acme.ImmutableOrder', annotations=['org.immutables.value.Generated']),
        summary('com.acme.ImmutableOrder$Builder'),
        summary('com.acme.ImmutableLookingButHandWritten'),
        summary('com.acme.db.DefaultCatalog', super_name='org.jooq.impl.CatalogImpl'),
        summary('com.acme.db.Keys'),
        summary('com.acme.db.tables.Orders', super_name='org.jooq.impl.TableImpl'),
        summary('com.acme.db.tables.records.OrdersRecord', super_name='org.jooq.impl.UpdatableRecordImpl'),
        summary('com.acme.db.enums.OrderStatus', super_name='java.lang.Enum', interfaces=['org.jooq.EnumType']),
        summary('com.acme.other.Keys'),
        summary(f'{client}.ApiClient'), summary(f'{client}.ApiException', super_name='java.lang.Exception'), summary(f'{client}.Pair'),
        summary(f'{client}.OrdersApi', constructor_params=[f'{client}.ApiClient']),
        summary(f'{client}.model.Order', static_fields=['JSON_PROPERTY_ID']),
        summary(f'{client}.auth.HttpBearerAuth'),
        summary(f'{client}.OrderPoller'),
    ]
    found = detect({r['fqn']: r for r in rows})
    assert {f: v['generator'] for f, v in found.items()} == {
        'com.acme.ImmutableOrder': 'IMMUTABLES', 'com.acme.ImmutableOrder$Builder': 'IMMUTABLES',
        'com.acme.db.DefaultCatalog': 'JOOQ', 'com.acme.db.Keys': 'JOOQ', 'com.acme.db.tables.Orders': 'JOOQ',
        'com.acme.db.tables.records.OrdersRecord': 'JOOQ', 'com.acme.db.enums.OrderStatus': 'JOOQ',
        f'{client}.ApiClient': 'OPENAPI_CLIENT', f'{client}.ApiException': 'OPENAPI_CLIENT', f'{client}.Pair': 'OPENAPI_CLIENT',
        f'{client}.OrdersApi': 'OPENAPI_CLIENT', f'{client}.model.Order': 'OPENAPI_CLIENT', f'{client}.auth.HttpBearerAuth': 'OPENAPI_CLIENT'}
    assert 'nested in generated class ImmutableOrder' == found['com.acme.ImmutableOrder$Builder']['evidence']


def test_application_without_generated_code_is_left_untouched(tmp_path):
    classes = tmp_path / 'classes'
    shutil.copytree(CLASSES / 'petclinic', classes)
    before = sorted(p.relative_to(classes) for p in classes.rglob('*.class'))
    record = exclude(classes, tmp_path / 'generated')
    assert record['status'] == 'NONE_DETECTED' and record['class_count'] == 0
    assert sorted(p.relative_to(classes) for p in classes.rglob('*.class')) == before


def test_oversized_facts_degrade_step_by_step_instead_of_disappearing():
    extracted = extract(CLASSES / 'petclinic')
    internal = set(extracted['classes'])
    full = len(json.dumps(bounded_for_snapshot(extract(CLASSES / 'petclinic'), internal, 10**9), separators=(',', ':')))
    for limit in (int(full * 0.8), int(full * 0.4)):
        facts = bounded_for_snapshot(extract(CLASSES / 'petclinic'), internal, limit)
        assert facts['classes'], 'facts must never be dropped wholesale'
        assert len(json.dumps(facts['classes'], separators=(',', ':'))) <= limit
        assert any('largest classes' in r for r in facts['reductions'])
    assert facts.get('omitted_class_count', 0) < len(internal)


POM = '<project xmlns="http://maven.apache.org/POM/4.0.0">{}</project>'


def test_maven_versions_resolve_through_parents_properties_and_in_archive_boms():
    parent = POM.format('<groupId>com.acme</groupId><artifactId>parent</artifactId><version>2.0.0</version>'
                        '<properties><jackson.version>2.17.1</jackson.version></properties>'
                        '<dependencyManagement><dependencies>'
                        '<dependency><groupId>com.acme</groupId><artifactId>platform</artifactId><version>${project.version}</version><type>pom</type><scope>import</scope></dependency>'
                        '<dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId><version>${jackson.version}</version></dependency>'
                        '<dependency><groupId>org.external</groupId><artifactId>external-bom</artifactId><version>1</version><type>pom</type><scope>import</scope></dependency>'
                        '</dependencies></dependencyManagement>')
    platform = POM.format('<groupId>com.acme</groupId><artifactId>platform</artifactId><version>2.0.0</version>'
                          '<properties><guice.version>6.0.0</guice.version></properties>'
                          '<dependencyManagement><dependencies><dependency><groupId>com.google.inject</groupId><artifactId>guice</artifactId>'
                          '<version>${guice.version}</version></dependency></dependencies></dependencyManagement>')
    module = POM.format('<parent><groupId>com.acme</groupId><artifactId>parent</artifactId><version>2.0.0</version></parent><artifactId>server</artifactId>'
                        '<dependencies>'
                        '<dependency><groupId>com.google.inject</groupId><artifactId>guice</artifactId></dependency>'
                        '<dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId></dependency>'
                        '<dependency><groupId>org.slf4j</groupId><artifactId>slf4j-api</artifactId><version>2.0.13</version></dependency>'
                        '<dependency><groupId>org.unknown</groupId><artifactId>from-external-bom</artifactId></dependency>'
                        '<dependency><groupId>${project.groupId}</groupId><artifactId>platform</artifactId><version>${project.version}</version></dependency>'
                        '<dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.13</version><scope>test</scope></dependency>'
                        '</dependencies>')
    rows, stats = _maven_dependencies([parent.encode(), platform.encode(), module.encode()])
    found = {f"{r['group_id']}:{r['artifact_id']}": r for r in rows}
    assert found['com.google.inject:guice']['version'] == '6.0.0' and found['com.google.inject:guice']['version_source'] == 'IMPORTED_BOM_IN_ARCHIVE'
    assert found['com.fasterxml.jackson.core:jackson-databind']['version'] == '2.17.1'
    assert found['com.fasterxml.jackson.core:jackson-databind']['version_source'] == 'PARENT_DEPENDENCY_MANAGEMENT'
    assert found['org.slf4j:slf4j-api']['version_source'] == 'DECLARED'
    assert found['org.unknown:from-external-bom']['version'] is None
    assert found['org.unknown:from-external-bom']['version_status'] == 'UNRESOLVED_OR_INHERITED'
    assert 'junit:junit' not in found and 'com.acme:platform' not in found
    assert stats == dict(pom_count=3, internal_module_references=1, test_scoped_skipped=1)


def test_lifecycle_package_rules_can_exclude_a_sub_package():
    model = SimpleNamespace(owners={}, facts={}, package=lambda fqn: fqn.rpartition('.')[0], classes={'a.Repo': {}, 'a.Form': {}},
                            external_edges=[dict(source='a.Repo', target='org.hibernate.Session', dependency_type='FIELD_TYPE'),
                                            dict(source='a.Form', target='org.hibernate.validator.constraints.Length', dependency_type='ANNOTATION')])
    assert package_usage(model, ['org.hibernate.'])['class_count'] == 2
    usage = package_usage(model, ['org.hibernate.'], excluded=['org.hibernate.validator.'])
    assert [row['class_name'] for row in usage['classes']] == ['a.Repo']
