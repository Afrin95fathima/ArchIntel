"""Read-only live delivery checks; saves a comparison fingerprint for restart checks."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import httpx
import yaml
from api_auth import management_headers

ROOT = Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=15, headers=management_headers()) as client:
    def get(url):
        response = client.get(url)
        response.raise_for_status()
        return response
    ready = get('/api/v1/ready').json()
    projects = get('/api/v1/projects').json()
    project = next(p for p in projects if p['name'].startswith('Northstar Commerce'))
    applications = get('/api/v1/applications').json()
    app = next(a for a in applications if a['project_id'] == project['id'])
    runs = get('/api/v1/analyses?application_id=' + app['id']).json()
    run = next(r for r in runs if r['status'] == 'COMPLETED')
    base = '/api/v1/analyses/' + run['id']
    result = get(base + '/export').json()
    assert result['algorithm_version'] == '0.2.1'
    assert result['summary']['class_count'] == 40
    payment = next(d for d in result['domains'] if d['name'] == 'Payment')
    assert all(not r.endswith('Entity') for r in payment['database']['repositories'])
    response = client.post(base + '/assistant/query', json={'question': 'Why is Payment high risk?'})
    response.raise_for_status()
    explanation = response.json()
    assert explanation['facts']
    for source in explanation['sources']:
        get(base + '/evidence/' + quote(source['id'], safe=''))
    unknown = client.post(base + '/assistant/query', json={'question': 'What is tomorrow weather?'}).json()
    assert not unknown['facts']
    for kind in ('user', 'developer'):
        assert len(get('/api/v1/manual/' + kind).content) > 5000
    for name in ('USER-MANUAL', 'DEVELOPER-GUIDE'):
        assert (ROOT / 'docs' / f'{name}.pdf').read_bytes().startswith(b'%PDF')
    assert set(yaml.safe_load((ROOT / 'docker-compose.yml').read_text())['services']) == {'postgres', 'backend'}
    fingerprint = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    destination = ROOT / 'docs' / 'verification-data.json'
    previous = json.loads(destination.read_text()) if destination.exists() else {}
    record = dict(checked_at=datetime.now(timezone.utc).isoformat(), analysis_id=run['id'],
        algorithm_version=result['algorithm_version'], status=run['status'], summary=result['summary'],
        snapshot_sha256=fingerprint, same_snapshot_as_previous_check=previous.get('snapshot_sha256') == fingerprint,
        resolved_citations=len(explanation['sources']), assistant_mode=explanation['mode'], readiness=ready)
    destination.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))
