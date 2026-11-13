"""Automated API exploration of an application that needs a launch recipe (a distribution plus disposable dependencies).

The runner starts the dependencies and the application with the OpenTelemetry agent, calls the GET routes the static
analysis found and runs the recipe's scenario files, then stops everything. The result is an ordinary runtime session, so
coverage, the twin and the plan use it exactly like a manually recorded one.
"""
import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

from app.models import AnalysisRun, now
from app.runtime.models import RuntimeSession
from app.runtime.schemas import SessionInput
from app.services.runtime import session_service
from .jobs import Steps
from .models import AutomationJob
from .runner import Runner, RunnerError

RECIPES = Path(__file__).resolve().parent / 'recipes'
STEPS = ['CHECK_RUNNER', 'UPLOAD_DISTRIBUTION', 'CREATE_SESSION', 'START_APPLICATION', 'EXPLORE_API', 'STOP_APPLICATION', 'COMPLETE_SESSION']
LIMITATIONS = [
    'Each run starts on a fresh database container (for Concord, PostgreSQL) that is removed afterwards; data created by the scenarios does not persist.',
    'The crawl only sends GET requests. POST, PUT and DELETE come from the scenario files, so a write route that no scenario calls has no evidence.',
    'Path variables such as {orgName} are filled from values seen in earlier responses; routes whose values never appeared are listed as unresolved.',
    'Only the processes the recipe starts are observed; a component it does not start (for Concord, the agent that executes processes) stays unobserved.',
    'Unvisited code is not proof of unused code in this application.',
]


@lru_cache(maxsize=8)
def _load(name: str) -> dict:
    return json.loads((RECIPES / f'{name}.json').read_text(encoding='utf-8'))


def recipes() -> list[dict]:
    """Built-in launch recipes, without their configuration templates."""
    out = []
    for path in sorted(RECIPES.glob('*.json')):
        item = _load(path.stem)
        out.append(dict(id=item['id'], title=item['title'], description=item['description'], distribution_hint=item.get('distribution_hint'),
                        distributions=item.get('distributions') or [dict(id='main', primary=True, title='Application distribution', hint=item.get('distribution_hint'))],
                        mode=(item.get('instrumentation') or {}).get('mode', 'STANDARD'), passes=(item.get('exploration') or {}).get('passes', 1), dependencies=[d['image'] for d in item['recipe'].get('dependencies', [])],
                        scenarios=[dict(name=s['name'], description=s.get('description', ''), steps=len(s.get('steps', [])), cleanup=len(s.get('cleanup', []))) for s in item.get('scenarios', [])]))
    return out


def recipe(recipe_id: str) -> dict | None:
    return next((_load(p.stem) for p in sorted(RECIPES.glob('*.json')) if _load(p.stem)['id'] == recipe_id), None)


def endpoints(result: dict) -> list[dict]:
    """GET routes of the static entry-point inventory, the crawl's starting set."""
    items = (result.get('entry_points') or {}).get('items', [])
    return sorted({(i['http_method'], i['path']) for i in items if i.get('http_method') == 'GET' and isinstance(i.get('path'), str) and i['path'].startswith('/')})


def steps_for(passes: int) -> list[str]:
    return STEPS + (['COMBINE_PASSES'] if passes > 1 else [])


def create(db, identity: dict, application_id: str, analysis_id: str, distribution: bytes, spec: dict, options: dict, extra: dict[str, bytes] | None = None) -> AutomationJob:
    passes = int(options.get('passes') or (spec.get('exploration') or {}).get('passes', 1))
    job = AutomationJob(tenant_id=identity['tenant_id'], application_id=application_id, analysis_id=analysis_id, kind='EXPLORE', state='QUEUED', actor_id=identity['id'],
                        document=dict(method='API', options=dict(options, passes=passes), recipe=dict(id=spec.get('id'), title=spec.get('title'), name=spec['recipe']['name']),
                                      artifact=dict(sha256=hashlib.sha256(distribution).hexdigest(), bytes=len(distribution)),
                                      distributions=[dict(id=key, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)) for key, data in sorted((extra or {}).items())],
                                      steps=[dict(name=s, state='PENDING', detail=None, at=None) for s in steps_for(passes)], limitations=LIMITATIONS, passes=[]))
    db.add(job)
    db.commit()
    return job


def run(sessions, settings, job_id: str, distribution: bytes, spec: dict, transport=None, extra: dict[str, bytes] | None = None):
    """One or more coverage passes. Each pass is a fresh start with its own session; a later pass traces only classes no
    earlier pass traced, so together they spread the instrumentation budget over the whole application."""
    steps = Steps(sessions, job_id)
    runner = Runner(settings, transport)
    session_id = run_id = None
    current = 'CHECK_RUNNER'
    try:
        steps.update(state='RUNNING', started_at=now().isoformat())
        with sessions() as db:
            job = db.get(AutomationJob, job_id)
            application_id, analysis_id, options, tenant = job.application_id, job.analysis_id, job.document['options'], job.tenant_id
            static = db.get(AnalysisRun, analysis_id).result
        total = int(options.get('passes') or 1)

        steps.step(current, 'RUNNING')
        health = runner.health()
        missing = [name for name in ('java', 'otel_agent', 'docker') if not health['tools'].get(name)]
        if missing:
            raise RunnerError('RUNNER_TOOLS_MISSING', ', '.join(missing))
        steps.step(current, 'DONE', f"Java, OpenTelemetry agent and Docker {health['tools']['docker']} available")

        current = 'UPLOAD_DISTRIBUTION'
        steps.step(current, 'RUNNING')
        sha = hashlib.sha256(distribution).hexdigest()
        stored = runner.upload_distribution(sha, distribution)
        sent = [f"{len(distribution):,} bytes, sha256 {sha[:12]}" + (' (already unpacked on the runner)' if stored.get('reused') else '')]
        companions = {}
        for key, data in sorted((extra or {}).items()):
            companions[key] = hashlib.sha256(data).hexdigest()
            reply = runner.upload_distribution(companions[key], data)
            sent.append(f"{key}: {len(data):,} bytes, sha256 {companions[key][:12]}" + (' (already unpacked)' if reply.get('reused') else ''))
        steps.step(current, 'DONE', '; '.join(sent))

        scope = spec.get('instrumentation') or {}
        exploration = spec.get('exploration') or {}
        traced: list[str] = []
        passes: list[dict] = []
        for index in range(1, total + 1):
            label = f' (pass {index} of {total})' if total > 1 else ''
            current = 'CREATE_SESSION'
            steps.step(current, 'RUNNING', label.strip() or None)
            with sessions() as db:
                db.info['tenant_id'] = tenant              # no request context in this thread; scope the session to the job's tenant
                body = SessionInput(analysis_id=analysis_id, name=f"API exploration {spec['recipe']['name']} {now().strftime('%Y-%m-%d %H:%M')}{label}",
                                    mode=options.get('mode') or scope.get('mode', 'STANDARD'), include_packages=scope.get('include_packages', []),
                                    exclude_packages=scope.get('exclude_packages', []), exclude_classes=traced)
                item, token = session_service.create(db, application_id, body)
                plan = item.settings['instrumentation_plan']
                if index > 1 and not plan['classes']:
                    db.delete(item)
                    db.commit()
                    steps.step(current, 'DONE', f'Every plannable class was traced by the first {index - 1} passes; no further pass needed.')
                    break
                session_service.transition(db, item, 'start', settings)
                session_id = item.id
                agent = session_service.agent_config(item, static, settings, token)
            env = agent['environment']
            otel = dict(endpoint=env['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT'], headers=env['OTEL_EXPORTER_OTLP_TRACES_HEADERS'], service_name=env['OTEL_SERVICE_NAME'],
                        resource_attributes=env.get('OTEL_RESOURCE_ATTRIBUTES'), methods_include=env.get('OTEL_INSTRUMENTATION_METHODS_INCLUDE'))
            traced += [c['class_name'] for c in plan['classes']]
            steps.update(session_id=session_id, instrumentation=dict(mode=plan['mode'], classes=len(traced), methods=plan['selected_method_names'], omissions=plan['omissions']))
            steps.step(current, 'DONE', f"Runtime session {session_id[:8]} is waiting for telemetry; {len(plan['classes'])} classes in the {plan['mode']} plan{label}.")

            current = 'START_APPLICATION'
            steps.step(current, 'RUNNING', f'Starting the dependencies, then the application with the OpenTelemetry agent{label}.')
            started = runner.start_recipe(sha, spec['recipe'], otel, companions)
            run_id = started['id']
            deps = ', '.join(f"{d['name']} on port {d['port']}" for d in started.get('dependencies', [])) or 'none'
            others = ', '.join(c['name'] for c in started.get('companions', [])) or 'none'
            steps.step(current, 'DONE', f"Started on {started['base_url']}; dependencies: {deps}; companion processes: {others}; credential {'generated' if started.get('credential') else 'not used'}{label}.")

            current = 'EXPLORE_API'
            steps.step(current, 'RUNNING', f'Calling the GET routes from the static analysis and running the scenario files{label}.')
            result = runner.explore_api(run_id, [dict(method=m, path=p) for m, p in endpoints(static)], spec.get('scenarios', []),
                                        exploration.get('skip_paths', []), int(options.get('max_requests') or exploration.get('max_requests', 600)))
            summary = result['summary']
            if index == 1:
                steps.update(exploration=dict(method='API', summary=summary, scenarios=result['scenarios'], unresolved=result['unresolved'], skipped=result.get('skipped', []),
                                              requests=result['requests'][:400], stopped_by_budget=result['stopped_by_budget'], duration_ms=result['duration_ms']))
            steps.step(current, 'DONE', f"{summary['requests']} requests; {summary['get_routes_called']} of {summary['get_routes']} GET routes called; "
                                        f"{summary['scenario_steps_passed']} of {summary['scenario_steps']} scenario steps passed{label}.")

            current = 'STOP_APPLICATION'
            steps.step(current, 'RUNNING')
            runner.stop_app(run_id)
            run_id = None
            time.sleep(2)                                  # the agent exports its last batch on shutdown
            steps.step(current, 'DONE', f'Application stopped and dependency containers removed{label}.')

            current = 'COMPLETE_SESSION'
            steps.step(current, 'RUNNING')
            with sessions() as db:
                db.info['tenant_id'] = tenant
                item = db.get(RuntimeSession, session_id)
                session_service.transition(db, item, 'stop', settings)
                coverage = ((item.result or {}).get('coverage') or {})
                spans = item.span_count
            finished, session_id = session_id, None
            classes = coverage.get('classes') or {}
            passes.append(dict(index=index, session_id=finished, plan_classes=len(plan['classes']), spans=spans, requests=summary['requests'],
                               scenario_steps_passed=summary['scenario_steps_passed'], classes=classes, entry_points=coverage.get('entry_points'), methods=coverage.get('methods')))
            steps.update(passes=passes, coverage=dict(spans=sum(p['spans'] for p in passes), classes=classes, entry_points=coverage.get('entry_points'), methods=coverage.get('methods')))
            steps.step(current, 'DONE', f"{spans:,} spans; classes reached {classes.get('observed')} of {classes.get('total')}{label}.")

        if total > 1:
            current = 'COMBINE_PASSES'
            steps.step(current, 'RUNNING')
            with sessions() as db:
                db.info['tenant_id'] = tenant
                rows = [db.get(RuntimeSession, p['session_id']) for p in passes]
                combined = session_service.result(db, rows, settings)['coverage']
            classes = combined.get('classes') or {}
            steps.update(coverage=dict(spans=sum(p['spans'] for p in passes), classes=classes, entry_points=combined.get('entry_points'), methods=combined.get('methods'),
                                       combined_sessions=[p['session_id'] for p in passes]))
            steps.step(current, 'DONE', f"{len(passes)} sessions combined: classes reached {classes.get('observed')} of {classes.get('total')}; "
                                        f"select these sessions together in Dynamic analysis, and capture an architecture version from them within "
                                        f"{settings.runtime_raw_trace_retention_hours} hours, before their raw spans expire and they can no longer be combined.")
        steps.update(state='COMPLETED', finished_at=now().isoformat())
    except RunnerError as error:
        _fail(steps, current, error.code, error.detail)
        _cleanup(sessions, settings, runner, run_id, session_id)
    except Exception as error:                              # unexpected: keep the job readable and release resources
        _fail(steps, current, 'EXPLORATION_FAILED', type(error).__name__)
        _cleanup(sessions, settings, runner, run_id, session_id)


def _fail(steps, current, code, detail):
    steps.step(current, 'FAILED', f'{code}: {detail[:500]}' if detail else code)
    steps.update(state='FAILED', error=dict(step=current, code=code, detail=(detail or '')[:4000]), finished_at=now().isoformat())


def _cleanup(sessions, settings, runner, run_id, session_id):
    from .explore import _cleanup as cleanup
    cleanup(sessions, settings, runner, run_id, session_id)
