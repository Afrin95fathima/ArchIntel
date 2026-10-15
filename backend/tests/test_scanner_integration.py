"""Opt-in real Java + jQAssistant + Neo4j tests, independent of mocked API tests."""
import os
import pytest
from app.config import ROOT, Settings
from app.services.scanner import JQAssistantScanner
from app.services.ingestion import validate_archive
from app.services.engine import analyze

pytestmark = pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_SCANNER_TESTS') != '1', reason='Opt-in real scanner test')


@pytest.mark.parametrize('artifact,packaging', [('northstar-commerce.jar','JAR'), ('northstar-commerce.war','WAR'), ('northstar-commerce-boot.jar','SPRING_BOOT')])
def test_real_scanner_formats_and_dependency_semantics(tmp_path, monkeypatch, artifact, packaging):
    # Dead local proxies verify the distribution can scan without downloading plugins.
    monkeypatch.setenv('JAVA_TOOL_OPTIONS', '-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9')
    settings = Settings(_env_file=None)
    classes_dir = tmp_path / 'classes'
    classes_dir.mkdir()
    manifest = validate_archive(ROOT / 'samples' / artifact, settings, classes_dir)
    assert manifest['packaging'] == packaging
    classes, edges = JQAssistantScanner(settings).scan(tmp_path, classes_dir, lambda *_: None)
    assert len(classes) == 40
    assert all(c['fqn'].startswith('com.northstar.') for c in classes)
    signatures = {(e['source'],e['target'],e['dependency_type']) for e in edges}
    assert ('com.northstar.payment.PaymentRepository','com.northstar.payment.PaymentEntity','GENERIC_TYPE') in signatures
    assert ('com.northstar.payment.PaymentRepository','java.io.IOException','EXCEPTION') in signatures
    assert ('com.northstar.payment.PaymentService','com.northstar.orders.OrdersService','METHOD_CALL') in signatures
    assert {'METHOD_CALL','FIELD_TYPE','GENERIC_TYPE','ANNOTATION','INHERITANCE','INTERFACE','EXCEPTION','OTHER'} == {e['dependency_type'] for e in edges}
    result = analyze(classes,edges,settings)
    assert result['summary']['class_count'] == 40
    assert result['summary']['package_count'] == 7
    assert result['summary']['domain_count'] == 7
    assert result['summary']['class_scc_count'] == 2
    assert result['summary']['package_scc_count'] == 1
    assert any(i['issue_type']=='GOD_CLASS' for i in result['issues'])
