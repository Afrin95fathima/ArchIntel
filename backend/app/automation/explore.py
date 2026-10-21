"""Automated runtime exploration: start the application with the OpenTelemetry agent, let REA drive it, record a session.

Replaces the manual "exercise the application" step of dynamic analysis. The resulting runtime session is an
ordinary ArchIntel session, so coverage, the twin and the plan use it exactly like a manually recorded one.
"""
import hashlib
import time
from app.models import AnalysisRun, now
from app.runtime.models import RuntimeSession
from app.runtime.schemas import SessionInput
from app.services.runtime import session_service
from .jobs import Steps
from .models import AutomationJob
from .runner import Runner, RunnerError

STEPS = ['CHECK_RUNNER', 'CREATE_SESSION', 'UPLOAD_ARTIFACT', 'START_APPLICATION', 'EXPLORE', 'STOP_APPLICATION', 'COMPLETE_SESSION']
LIMITATIONS = [
    'Exploration fills forms with synthetic values and submits them, so it creates and changes data; run it against a disposable copy of this application.',
    'Only pages reachable by links and forms from the start page and the static GET routes are visited; flows behind logins, JavaScript-only navigation or specific data are not.',
    'Links that look destructive (delete, remove, logout) and forms with password fields are skipped, so this session has no evidence for them.',
    'Unvisited code is not proof of unused code in this application.',
]


def seeds(result: dict) -> list[str]:
    """Static GET routes without path variables, so the crawler also reaches pages that no link points to."""
    items = (result.get('entry_points') or {}).get('items', [])
    return sorted({i['path'] for i in items if i.get('http_method') == 'GET' and isinstance(i.get('path'), str)
                   and i['path'].startswith('/') and '{' not in i['path'] and '*' not in i['path']})[:200]


def create(db, identity: dict, application_id: str, analysis_id: str, jar: bytes, options: dict) -> AutomationJob:
    job = AutomationJob(tenant_id=identity['tenant_id'], application_id=application_id, analysis_id=analysis_id, kind='EXPLORE', state='QUEUED',
                        actor_id=identity['id'], document=dict(options=options, artifact=dict(sha256=hashlib.sha256(jar).hexdigest(), bytes=len(jar)),
                                                              steps=[dict(name=s, state='PENDING', detail=None, at=None) for s in STEPS], limitations=LIMITATIONS))
    db.add(job)
    db.commit()
    return job


def run(sessions, settings, job_id: str, jar: bytes, transport=None):
    steps = Steps(sessions, job_id)
    runner = Runner(settings, transport)
    session_id = run_id = None
    current = 'CHECK_RUNNER'
    try:
        steps.update(state='RUNNING', started_at=now().isoformat())
        with sessions() as db:
            job = db.get(AutomationJob, job_id)
            application_id, analysis_id, options, tenant = job.application_id, job.analysis_id, job.document['options'], job.tenant_id
            analysis = db.get(AnalysisRun, analysis_id)
            static = analysis.result

        steps.step(current, 'RUNNING')
        health = runner.health()
        missing = [name for name in ('java', 'chrome', 'otel_agent', 'rea') if not health['tools'].get(name)]
        if missing:
            raise RunnerError('RUNNER_TOOLS_MISSING', ', '.join(missing))
        steps.step(current, 'DONE', f"REA {health['tools']['rea']}, Docker {health['tools'].get('docker') or 'not available'}")

        current = 'CREATE_SESSION'
        steps.step(current, 'RUNNING')
        with sessions() as db:
            db.info['tenant_id'] = tenant                  # no request context in this thread; scope the session to the job's tenant
            body = SessionInput(analysis_id=analysis_id, name=f"Automated exploration {now().strftime('%Y-%m-%d %H:%M')}", mode=options.get('mode', 'DEEP'))
            item, token = session_service.create(db, application_id, body)
            session_service.transition(db, item, 'start', settings)
            session_id = item.id
            agent = session_service.agent_config(item, static, settings, token)
        env = agent['environment']
        otel = dict(endpoint=env['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT'], headers=env['OTEL_EXPORTER_OTLP_TRACES_HEADERS'], service_name=env['OTEL_SERVICE_NAME'],
                    resource_attributes=env.get('OTEL_RESOURCE_ATTRIBUTES'), methods_include=env.get('OTEL_INSTRUMENTATION_METHODS_INCLUDE'))
        steps.update(session_id=session_id)
        steps.step(current, 'DONE', f'Runtime session {session_id[:8]} is waiting for telemetry.')

        current = 'UPLOAD_ARTIFACT'
        steps.step(current, 'RUNNING')
        sha = hashlib.sha256(jar).hexdigest()
        runner.upload(sha, jar)
        steps.step(current, 'DONE', f'{len(jar):,} bytes, sha256 {sha[:12]}')

        current = 'START_APPLICATION'
        steps.step(current, 'RUNNING')
        started = runner.start_app(sha, otel)
        run_id = started['id']
        steps.step(current, 'DONE', f"Started on {started['base_url']} with the OpenTelemetry agent.")

        current = 'EXPLORE'
        steps.step(current, 'RUNNING', 'REA is visiting pages and submitting forms.')
        result = runner.explore(run_id, seeds(static), int(options.get('max_pages', 40)), int(options.get('max_forms', 12)))
        summary = dict(pages=len(result['pages']), forms=len(result['forms']), forms_completed=sum(1 for f in result['forms'] if f['completed']),
                       routes=len(result['routes']), failures=len(result['failures']), skipped=len(result['skipped']), duration_ms=result['duration_ms'])
        steps.update(exploration=dict(summary=summary, pages=result['pages'][:200], forms=result['forms'][:100], routes=result['routes'][:300],
                                      skipped=result['skipped'][:100], failures=result['failures'][:100], unvisited=result['unvisited'][:50],
                                      evidence_ids=result['evidence_ids'][:500], stopped_by_time=result['stopped_by_time']))
        steps.step(current, 'DONE', f"{summary['pages']} pages, {summary['forms_completed']} of {summary['forms']} forms submitted, {summary['routes']} routes observed.")

        current = 'STOP_APPLICATION'
        steps.step(current, 'RUNNING')
        runner.stop_app(run_id)
        run_id = None
        time.sleep(2)                                      # the agent exports its last batch on shutdown
        steps.step(current, 'DONE')

        current = 'COMPLETE_SESSION'
        steps.step(current, 'RUNNING')
        with sessions() as db:
            db.info['tenant_id'] = tenant
            item = db.get(RuntimeSession, session_id)
            session_service.transition(db, item, 'stop', settings)
            coverage = ((item.result or {}).get('coverage') or {})
            spans = item.span_count
        classes = coverage.get('classes') or {}
        steps.update(coverage=dict(spans=spans, classes=classes, entry_points=coverage.get('entry_points'), methods=coverage.get('methods')))
        steps.step(current, 'DONE', f"{spans:,} spans; classes reached {classes.get('observed')} of {classes.get('total')}.")
        steps.update(state='COMPLETED', finished_at=now().isoformat())
    except RunnerError as error:
        _fail(steps, current, error.code, error.detail)
        _cleanup(sessions, settings, runner, run_id, session_id)
    except Exception as error:                              # unexpected: keep the job readable and release resources
        _fail(steps, current, 'EXPLORATION_FAILED', type(error).__name__)
        _cleanup(sessions, settings, runner, run_id, session_id)


def _fail(steps, current, code, detail):
    steps.step(current, 'FAILED', f'{code}: {detail}' if detail else code)
    steps.update(state='FAILED', error=dict(step=current, code=code, detail=(detail or '')[:2000]), finished_at=now().isoformat())


def _cleanup(sessions, settings, runner, run_id, session_id):
    if run_id:
        try:
            runner.stop_app(run_id)
        except RunnerError:
            pass
    if session_id:
        try:
            with sessions() as db:
                item = db.get(RuntimeSession, session_id)
                if item and item.status in ('WAITING_FOR_AGENT', 'RUNNING'):
                    session_service.transition(db, item, 'stop', settings)
        except Exception:
            pass
