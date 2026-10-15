from pathlib import Path
import os
import hashlib
import json

from sqlalchemy import text

from app.config import ROOT
from app.services.scanner import ScannerError


def diagnostics(config, engine, scanner):
    checks = []

    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        checks.append(dict(id='database', label='Local database', state='READY', required=True,
                           detail='ArchIntel can connect to its configured local database.'))
    except Exception:
        checks.append(dict(id='database', label='Local database', state='ACTION_REQUIRED', required=True,
                           detail='ArchIntel could not connect to its configured local database.',
                           action='Run Start-ArchIntel.cmd again. If the problem continues, check the database service and the backend log.'))

    try:
        scanner.command()
        checks.append(dict(id='static_scanner', label='Java static-analysis tools', state='READY', required=True,
                           detail='Java, jQAssistant, and ArchIntel’s graph exporter are present.'))
    except ScannerError as error:
        checks.append(dict(id='static_scanner', label='Java static-analysis tools', state='ACTION_REQUIRED', required=True,
                           detail=str(error), action='Run scripts/setup.ps1 to install or repair the local analysis runtime.'))

    data_dir = Path(config.data_dir)
    storage_ready = data_dir.is_dir() and os.access(data_dir, os.R_OK | os.W_OK)
    checks.append(dict(id='local_storage', label='Local data folder',
        state='READY' if storage_ready else 'ACTION_REQUIRED', required=True,
        detail='ArchIntel can access its local data folder.' if storage_ready else 'The configured local data folder is missing or not accessible.',
        **({} if storage_ready else {'action':'Check the data-folder path and Windows permissions, then restart ArchIntel.'})))

    agent_dir = ROOT / '.runtime' / 'otel'
    agent_present = agent_dir.is_dir() and any(agent_dir.glob('opentelemetry-javaagent*.jar'))
    checks.append(dict(id='otel_agent', label='OpenTelemetry Java agent',
        state='AVAILABLE' if agent_present else 'OPTIONAL', required=False,
        detail='A local Java agent is available for runtime capture.' if agent_present else
               'Only needed when capturing new runtime traces; static analysis works without it.',
        **({} if agent_present else {'action':'Use the Phase 3 runtime setup guide if you want to collect traces.'})))

    ai_configured = bool(config.llm_url and config.llm_model)
    checks.append(dict(id='local_ai', label='Optional local AI provider',
        state='CONFIGURED' if ai_configured else 'OPTIONAL', required=False,
        detail='A local provider is configured; this check does not contact it.' if ai_configured else
               'Evidence-based deterministic guidance works without a model provider.',
        **({} if ai_configured else {'action':'Configure a permitted local provider only if you want generated explanations.'})))

    checks.append(dict(id='container_workflows', label='Container build and security workflows',
        state='DEFERRED', required=False,
        detail='Docker is intentionally outside the current local POC work. Static and runtime analysis do not require Docker.',
        action='Candidate builds, Java refactor execution, SAST, and packaged-dependency scans need Docker validation later.'))

    required_ready = all(item['state'] == 'READY' for item in checks if item['required'])
    runtime_state = 'BLOCKED' if not required_ready else 'READY' if agent_present else 'OPTIONAL_SETUP'
    return dict(mode='LOCAL_POC', core_ready=required_ready,
        summary='Local static-analysis setup is ready.' if required_ready else 'Local setup needs attention before static analysis.',
        checks=checks,
        workflows=dict(static_analysis='READY' if required_ready else 'BLOCKED',
            runtime_observation=runtime_state,
            source_build_and_security='DEFERRED'))


def support_bundle_preview(config, engine, scanner):
    """Build a minimal, deterministic support report without reading user data."""
    report = diagnostics(config, engine, scanner)
    safe_report = dict(
        schema_version=1,
        product='ArchIntel',
        product_version='0.2.0',
        operating_profile=report['mode'],
        core_ready=report['core_ready'],
        checks=[dict(id=item['id'], state=item['state'], required=item['required']) for item in report['checks']],
        workflows=report['workflows'],
    )
    manifest = dict(
        schema_version=1,
        included=['status-report.json'],
        excluded=['source files', 'generated code', 'secrets', 'environment values', 'logs',
                  'database contents', 'runtime payloads', 'architecture and customer data'],
        transfer='LOCAL_DOWNLOAD_ONLY',
        upload_performed=False,
    )
    canonical = json.dumps(dict(manifest=manifest, report=safe_report), sort_keys=True, separators=(',', ':'))
    fingerprint = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return dict(fingerprint=fingerprint, manifest=manifest, report=safe_report)
