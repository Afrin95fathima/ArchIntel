"""WP1: lifecycle rules evaluated against compiled fixtures with known usage."""
from datetime import date
import io
import zipfile
from app.insight.lifecycle import evaluate, freshness, in_range, load_rules, compatibility_summary
from app.services.tech_stack import inspect_artifact
from insight_fixtures import model, snapshot, CLASSES


def test_rules_file_is_valid_versioned_and_dated():
    rules = load_rules()
    assert rules['rules_version'] and rules['reviewed']
    for rule in rules['rules']:
        assert rule['source'].startswith('https://')
        assert rule.get('alternative') and rule.get('migration_notes') and rule.get('effort') in ('low', 'medium', 'high')


def test_version_ranges():
    assert in_range('2.7.18', '>=2.7,<3.0') and not in_range('3.0.0', '>=2.7,<3.0')
    assert in_range('17', '==17') and in_range('8', '==8') and not in_range('11', '==8')
    assert in_range('3.5.4', '>=3.5,<4.0') and in_range('25', '>=25')


def test_freshness_warns_when_stale():
    rules = load_rules()
    fresh = freshness(rules, today=date.fromisoformat(str(rules['reviewed'])))
    assert fresh['stale'] is False and fresh['warning'] is None
    stale = freshness(rules, today=date(2030, 1, 1))
    assert stale['stale'] is True and 'last reviewed' in stale['warning']


def by_rule(findings):
    return {f['rule_id']: f for f in findings}


def test_edgecase_aging_apis_list_classes_and_call_sites():
    result = evaluate(model('edgecases'), {})
    found = by_rule(result['findings'])
    log4j = found['log4j-1']
    assert log4j['status'] == 'end-of-life'
    assert [c['class_name'] for c in log4j['affected_classes']] == ['com.fixture.edge.legacy.BillingAction']
    sites = [s['text'] for s in log4j['affected_classes'][0]['call_sites']]
    assert 'BillingAction.execute() calls Logger.info()' in sites
    assert 'BillingAction static initializer calls Logger.getLogger()' in sites
    assert log4j['recommended_alternative'].startswith('Log4j 2')
    jpa = found['javax-persistence']
    assert jpa['replacement'] == {'from': 'javax.persistence', 'to': 'jakarta.persistence'}
    assert [c['class_name'] for c in jpa['affected_classes']] == ['com.fixture.edge.legacy.BillingRecord']
    assert found['jdk-removed-ee-modules']['status'] == 'end-of-life'
    assert found['commons-lang-2']['affected_classes'][0]['class_name'] == 'com.fixture.edge.legacy.BillingAction'
    assert found['struts-1']['status'] == 'end-of-life'
    servlet = found['javax-servlet']
    assert {c['class_name'].rsplit('.', 1)[-1] for c in servlet['affected_classes']} == {'LegacyServlet', 'AuditFilter'}
    # Version unknown: the reason is stated, never guessed.
    assert jpa['version_found'] is None and 'no dependency version' in jpa['version_reason']
    assert all(f['status'] != 'vulnerable' for f in result['findings'])
    assert 'not a vulnerability' in result['label']


def test_petclinic_has_no_javax_findings_and_java_17_is_reported():
    result = evaluate(model('petclinic'), {})
    found = by_rule(result['findings'])
    assert 'javax-persistence' not in found and 'log4j-1' not in found
    java = next(f for f in result['findings'] if f['rule_id'] == 'java-class-target')
    assert java['version_found'] == 'Java 17' and java['status'] == 'aging' and java['affected_class_count'] == 24


def test_dependency_metadata_versions_drive_status(tmp_path):
    archive = tmp_path / 'app.jar'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nSpring-Boot-Version: 2.7.18\n')
        z.writestr('META-INF/maven/log4j/log4j/pom.properties', 'groupId=log4j\nartifactId=log4j\nversion=1.2.17\n')
        z.writestr('BOOT-INF/lib/hibernate-core-5.4.33.Final.jar', b'')
    inventory = inspect_artifact(archive, CLASSES / 'edgecases', snapshot('edgecases'))
    result = evaluate(model('edgecases'), inventory)
    found = {f['id']: f for f in result['findings']}
    assert found['spring-boot:2.7.18']['status'] == 'end-of-life'
    assert found['log4j-1:1.2.17']['status'] == 'end-of-life'
    assert found['hibernate-orm:5.4.33.Final']['status'] == 'end-of-life'
    summary = compatibility_summary(result)
    assert summary['framework_lifecycle'] == 'END_OF_LIFE' and summary['vulnerability_advisories'] == 'OUT_OF_SCOPE'
    assert 'NOT_CHECKED' not in str(summary)
