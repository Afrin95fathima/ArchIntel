from app.services.scanner import ScannerError
from test_runtime import live


def by_id(report):
    return {item['id']: item for item in report['checks']}


def test_local_setup_diagnostics_separate_core_services_from_deferred_containers(live):
    response = live.get('/api/v1/system/diagnostics')
    assert response.status_code == 200, response.text
    report = response.json()
    checks = by_id(report)
    assert report['mode'] == 'LOCAL_POC'
    assert report['core_ready'] is True
    assert report['workflows']['static_analysis'] == 'READY'
    assert checks['database']['state'] == 'READY'
    assert checks['static_scanner']['state'] == 'READY'
    assert checks['container_workflows']['state'] == 'DEFERRED'
    assert checks['container_workflows']['required'] is False
    assert checks['otel_agent']['required'] is False


def test_local_setup_diagnostics_explain_missing_static_scanner(live, monkeypatch):
    def unavailable():
        raise ScannerError('Scanner runtime is incomplete. Run the setup script and build the graph exporter.')
    monkeypatch.setattr(live.app.state.worker.scanner, 'command', unavailable)
    response = live.get('/api/v1/system/diagnostics')
    assert response.status_code == 200, response.text
    report = response.json()
    checks = by_id(report)
    assert report['core_ready'] is False
    assert report['workflows']['static_analysis'] == 'BLOCKED'
    assert checks['static_scanner']['state'] == 'ACTION_REQUIRED'
    assert 'scripts/setup.ps1' in checks['static_scanner']['action']
    assert checks['container_workflows']['state'] == 'DEFERRED'


def test_support_bundle_requires_reviewed_fresh_preview_and_contains_status_only(live):
    preview = live.get('/api/v1/system/support-bundle/preview')
    assert preview.status_code == 200, preview.text
    item = preview.json()
    assert item['manifest']['included'] == ['status-report.json']
    assert item['manifest']['transfer'] == 'LOCAL_DOWNLOAD_ONLY'
    assert item['manifest']['upload_performed'] is False
    serialized = str(item).lower()
    for excluded in ('source files', 'secrets', 'logs', 'database contents', 'runtime payloads', 'architecture and customer data'):
        assert excluded in serialized
    assert 'database_url' not in serialized
    stale = live.post('/api/v1/system/support-bundle/export', json={'fingerprint': '0' * 64})
    assert stale.status_code == 409
    exported = live.post('/api/v1/system/support-bundle/export', json={'fingerprint': item['fingerprint']})
    assert exported.status_code == 200, exported.text
    assert exported.json()['report'] == item['report']
    assert exported.json()['manifest']['upload_performed'] is False
    events = live.get('/api/v1/security/audit').json()
    assert any(event['action'] == 'SUPPORT_BUNDLE_EXPORT' and event['outcome'] == 'ALLOW'
               and event['resource'] == item['fingerprint'] for event in events)
