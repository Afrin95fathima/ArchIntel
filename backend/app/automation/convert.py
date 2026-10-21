"""Local conversion trial: generate one service candidate with Claude, build and run it with the runner, compare it with the original.

This is a trial lane, separate from the source-task lane. It never changes the source repository and never publishes:
the generated repository stays in ArchIntel's data folder, runs only as a local container, and is judged by replaying the
recorded REA scenarios against the original application and the new service. Every gate of the source-task lane that
concerns *sending source* still applies: an approved plan, source-read permission and grant, the Claude transfer policy,
a per-request human acknowledgement and the daily generation cap. The reproducible-baseline-build gate is replaced by the
recorded behaviour of the original application, and the result says so.
"""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.access.core import latest_policy
from app.access.gateway import git, matches
from app.access.models import Principal, SourceGrant, SourceRepository
from app.ai import claude
from app.ai.gateway import event as model_event
from app.ai.models import ModelInvocation
from app.evidence.models import ArchitectureVersion
from app.models import now
from app.modernization import service as planning
from app.modernization.models import Assessment
from app.transformation import microservice_codegen
from .jobs import Steps
from .models import AutomationJob
from .runner import Runner, RunnerError

STEPS = ['PRECHECK', 'SELECT_SOURCE', 'GENERATE', 'BUILD_SERVICE', 'START_ORIGINAL', 'COMPARE', 'STOP_ORIGINAL']
ACKNOWLEDGEMENT = 'I_APPROVE_SENDING_SELECTED_SOURCE_TO_ANTHROPIC_CLAUDE'
MAX_SOURCE_FILES = 60
RUNTIME_REQUIREMENTS = [
    'Build with Maven for Java 21 and Spring Boot 3; spring-boot-maven-plugin must produce exactly one executable jar in target/.',
    'Read the HTTP port from server.port; the runner starts the jar with --server.port=8080 and checks GET / for any non-5xx answer.',
    'Serve the same HTTP routes, view templates and response statuses as the original controllers in source_files for this candidate.',
    'When the original uses an embedded in-memory database, keep it and copy the schema and data scripts so the service starts with the same data.',
    'Do not include a Dockerfile, Maven wrapper, CI configuration or files under .mvn; the runner supplies the build recipe.',
]
LIMITATIONS = [
    'Trial lane: ArchIntel builds and runs the generated service in local Docker only; nothing is merged, published or deployed.',
    'The reproducible baseline build of the source-task lane is replaced by the recorded behaviour of the original application.',
    'Equivalence covers only the recorded scenarios replayed for the selected candidate; untested behaviour is unknown.',
    'Data ownership and migration of this application are not decided by a trial; a shared database stays an open question.',
]


def _slug(value: str) -> str:
    return (re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-') or 'service')[:50]


def generations_today(db, tenant_id: str) -> int:
    from datetime import timedelta
    since = now() - timedelta(hours=24)
    rows = db.scalars(select(ModelInvocation).where(ModelInvocation.tenant_id == tenant_id, ModelInvocation.created_at >= since))
    return sum(1 for row in rows if (row.metadata_json or {}).get('destination') == 'CLAUDE_EXTERNAL')


def latest_exploration(db, application_id: str, analysis_id: str):
    return db.scalar(select(AutomationJob).where(AutomationJob.application_id == application_id, AutomationJob.analysis_id == analysis_id,
                                                 AutomationJob.kind == 'EXPLORE', AutomationJob.state == 'COMPLETED')
                     .order_by(AutomationJob.created_at.desc()).limit(1))


def candidate_of(document: dict, candidate_id: str) -> dict:
    candidates = (document.get('microservice_decomposition') or {}).get('service_candidates', [])
    found = next((c for c in candidates if c['id'] == candidate_id), None)
    if not found:
        raise HTTPException(404, 'Service candidate not found in this plan.')
    return found


def preconditions(db, settings, identity: dict, version, plan, candidate_id: str, repository_id: str) -> list[dict]:
    """Every gate as a row (id, met, text); the job starts only when all are met. Also used to show a checklist."""
    rows = []
    def gate(gid, met, text): rows.append(dict(id=gid, met=bool(met), text=text))
    gate('CURRENT_VERSION', planning.context(db, version)['state'] == 'CURRENT', 'This plan belongs to the latest captured architecture version of this application.')
    history = planning.reviews(db, plan.id)
    gate('PLAN_APPROVED', bool(history) and history[-1]['state'] == 'APPROVED_PLANNING', 'The latest review of this plan is an approval.')
    candidates = (plan.document.get('microservice_decomposition') or {}).get('service_candidates', [])
    candidate = next((c for c in candidates if c['id'] == candidate_id), None)
    gate('BUSINESS_CANDIDATE', candidate and candidate.get('proposal_state') == 'CANDIDATE_REQUIRES_REVIEW',
         'The selected candidate is a business domain (technical domains stay shared libraries).')
    principal = db.get(Principal, identity['id'])
    gate('HUMAN_WITH_SOURCE_READ', principal and principal.active and identity.get('kind') == 'HUMAN' and 'SOURCE_READ' in principal.permissions,
         'A human with source-read permission starts the conversion of this application.')
    policy = latest_policy(db, identity['tenant_id'])
    doc = policy.document if policy else {}
    gate('SOURCE_POLICY', doc.get('source_read_enabled') and doc.get('transformation_enabled'), 'Workspace policy allows bounded source reading and source tasks for this account.')
    gate('CLAUDE_POLICY', doc.get('claude_source_transfer_enabled'), 'Workspace policy allows sending selected source to Claude.')
    gate('CLAUDE_KEY', bool(settings.anthropic_api_key.get_secret_value()), 'An Anthropic API key is configured (ANTHROPIC_API_KEY).')
    gate('DAILY_BUDGET', generations_today(db, identity['tenant_id']) < settings.claude_max_generations_per_day,
         f'Fewer than {settings.claude_max_generations_per_day} Claude generations in the last 24 hours.')
    repo = db.get(SourceRepository, repository_id) if repository_id else None
    gate('REPOSITORY', repo and repo.tenant_id == identity['tenant_id'] and repo.application_id == version.application_id,
         'A source repository of this application is registered at a pinned commit.')
    grant = repo and db.scalar(select(SourceGrant).where(SourceGrant.principal_id == identity['id'], SourceGrant.repository_id == repo.id))
    gate('SOURCE_GRANT', grant, 'You have a file-scope grant on the selected repository.')
    exploration = latest_exploration(db, version.application_id, version.analysis_id)
    gate('BEHAVIOUR_BASELINE', exploration, 'A completed automated exploration of the same analysis recorded the original behaviour.')
    gate('RUNNER', Runner(settings).configured, 'The runner is configured (RUNNER_TOKEN).')
    return rows


def select_source(db, identity, repo, candidate: dict, policy_document: dict) -> tuple[list[dict], list[dict]]:
    """Candidate classes plus the build file and the resources the controllers need, filtered by grant and protected paths."""
    grant = db.scalar(select(SourceGrant).where(SourceGrant.principal_id == identity['id'], SourceGrant.repository_id == repo.id))
    tree = [p for p in git(repo.path, 'ls-tree', '-r', '--name-only', repo.commit).decode().splitlines() if p]
    wanted, reasons = [], {}
    for class_id in candidate.get('class_ids', []):
        suffix = '/' + class_id.split('$')[0].replace('.', '/') + '.java'
        hits = [p for p in tree if p.endswith(suffix) and '/src/test/' not in '/' + p]
        if len(hits) == 1:
            wanted.append(hits[0])
        else:
            reasons[class_id] = 'NOT_FOUND' if not hits else 'AMBIGUOUS'
    segments = {p.rsplit('.', 1)[-1] for p in candidate.get('packages', []) if p}
    for path in tree:
        name = path.rsplit('/', 1)[-1]
        if path == 'pom.xml' or path in ('src/main/resources/application.properties', 'src/main/resources/application.yml', 'src/main/resources/messages/messages.properties'):
            wanted.append(path)
        elif path.startswith('src/main/resources/db/h2/') or path.startswith('src/main/resources/templates/fragments/'):
            wanted.append(path)
        elif path.startswith('src/main/resources/templates/') and any(f'/templates/{s}' in path for s in segments | {s + 's' for s in segments}):
            wanted.append(path)
        elif name == 'welcome.html' or name == 'error.html':
            wanted.append(path)
    files, excluded = [], [dict(path=k, reason=v) for k, v in reasons.items()]
    total = 0
    protected = (grant.protected_paths if grant else []) + policy_document.get('protected_paths', [])
    for path in sorted(dict.fromkeys(wanted)):
        if not grant or not matches(path, grant.allowed_paths) or matches(path, protected):
            excluded.append(dict(path=path, reason='OUTSIDE_GRANT_OR_PROTECTED')); continue
        try:
            content = git(repo.path, 'show', f'{repo.commit}:{path}').decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            excluded.append(dict(path=path, reason='UNREADABLE_OR_BINARY')); continue
        if len(files) >= MAX_SOURCE_FILES or total + len(content) > policy_document.get('max_task_bytes', 1048576):
            excluded.append(dict(path=path, reason='SIZE_OR_COUNT_LIMIT')); continue
        files.append(dict(path=path, content=content)); total += len(content)
    return files, excluded


def observations_for(exploration: dict, candidate: dict, entry_points: list[dict]) -> tuple[list[dict], list[dict]]:
    """Recorded routes of this candidate's entry points, and replayable GET scenarios built from the pages REA visited."""
    def shape(path):
        return re.sub(r'\{[^}]+\}', '{id}', path)
    shapes = {shape(e['path']) for e in entry_points if e.get('path', '').startswith('/') and e.get('handler_class') in set(candidate.get('class_ids', []))}
    routes = [r for r in exploration.get('routes', []) if r['shape'].split('?')[0] in shapes]
    seen, scenarios = set(), []
    for page in exploration.get('pages', []):
        if page.get('status') and page['shape'].split('?')[0] in shapes and page['shape'] not in seen:
            seen.add(page['shape'])
            scenarios.append(dict(name=f"GET {page['shape']}", scenario=dict(start_url=dict(url=page['url']),
                                  actions=[dict(step_id='settle', action='wait_for_timeout', duration_ms=400)])))
    return routes, scenarios[:40]


def create(db, settings, identity, version, plan, candidate_id: str, repository_id: str, acknowledgement: str) -> AutomationJob:
    if acknowledgement != ACKNOWLEDGEMENT:
        raise HTTPException(422, 'Acknowledge that the selected source is sent to Anthropic Claude.')
    rows = preconditions(db, settings, identity, version, plan, candidate_id, repository_id)
    missing = [r for r in rows if not r['met']]
    if missing:
        raise HTTPException(409, dict(message='Conversion preconditions are not met.', missing=missing))
    running = db.scalar(select(AutomationJob).where(AutomationJob.application_id == version.application_id, AutomationJob.kind == 'CONVERT',
                                                    AutomationJob.state.in_(['QUEUED', 'RUNNING'])))
    if running:
        raise HTTPException(409, 'A conversion of this application is already running.')
    candidate = candidate_of(plan.document, candidate_id)
    job = AutomationJob(tenant_id=identity['tenant_id'], application_id=version.application_id, analysis_id=version.analysis_id, kind='CONVERT',
                        state='QUEUED', actor_id=identity['id'],
                        document=dict(version_id=version.id, plan_id=plan.id, plan_fingerprint=plan.fingerprint, candidate_id=candidate_id,
                                      candidate_name=candidate['name'], repository_id=repository_id, service_name=_slug(candidate['name']),
                                      consent=dict(actor_id=identity['id'], acknowledgement=acknowledgement, at=now().isoformat()),
                                      provider='CLAUDE', model=settings.claude_model, lane='LOCAL_TRIAL',
                                      steps=[dict(name=s, state='PENDING', detail=None, at=None) for s in STEPS], limitations=LIMITATIONS))
    db.add(job)
    db.commit()
    return job


def run(sessions, settings, job_id: str, identity: dict, runner_transport=None, claude_client=None):
    steps = Steps(sessions, job_id)
    runner = Runner(settings, runner_transport)
    request_shim = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(sessions=sessions)))
    current, original_run, invocation = 'PRECHECK', None, str(uuid4())
    meta = {}
    try:
        steps.update(state='RUNNING', started_at=now().isoformat())
        steps.step(current, 'RUNNING')
        with sessions() as db:
            db.info['tenant_id'] = identity['tenant_id']
            job = db.get(AutomationJob, job_id)
            d = dict(job.document)
            version = db.get(ArchitectureVersion, d['version_id'])
            plan = db.get(Assessment, d['plan_id'])
            rows = preconditions(db, settings, identity, version, plan, d['candidate_id'], d['repository_id'])
            missing = [r['id'] for r in rows if not r['met']]
            if missing:
                raise RunnerError('PRECONDITION_CHANGED', ', '.join(missing))
            if plan.fingerprint != d['plan_fingerprint']:
                raise RunnerError('PLAN_CHANGED')
            candidate = candidate_of(plan.document, d['candidate_id'])
            repo = db.get(SourceRepository, d['repository_id'])
            repo_view = SimpleNamespace(id=repo.id, path=repo.path, commit=repo.commit)
            policy_document = dict(latest_policy(db, identity['tenant_id']).document)
            exploration_job = latest_exploration(db, version.application_id, version.analysis_id)
            exploration = exploration_job.document.get('exploration') or {}
            artifact_sha = exploration_job.document['artifact']['sha256']
            entry_points = ((version.document.get('entry_points') or {}).get('items')) or []
        health = runner.health()
        if not health['tools'].get('docker'):
            raise RunnerError('DOCKER_UNAVAILABLE', 'The runner needs Docker to build the generated service.')
        steps.step(current, 'DONE', f"{len(rows)} conditions met; candidate {candidate['name']}.")

        current = 'SELECT_SOURCE'
        steps.step(current, 'RUNNING')
        with sessions() as db:
            files, excluded = select_source(db, identity, repo_view, candidate, policy_document)
        if not any(f['path'].endswith('.java') for f in files):
            raise RunnerError('NO_CANDIDATE_SOURCE', 'No Java source of the candidate is inside your grant.')
        routes, scenarios = observations_for(exploration, candidate, entry_points)
        steps.update(source=dict(commit=repo_view.commit, files=[dict(path=f['path'], bytes=len(f['content'])) for f in files], excluded=excluded[:100]),
                     observed_routes=routes, scenarios=[s['name'] for s in scenarios])
        steps.step(current, 'DONE', f"{len(files)} files at {repo_view.commit[:8]} ({sum(len(f['content']) for f in files):,} bytes); {len(excluded)} left out; {len(scenarios)} recorded scenarios.")

        current = 'GENERATE'
        steps.step(current, 'RUNNING', f'Waiting for {settings.claude_model}.')
        brief = dict(candidate_id=candidate['id'], name=candidate['name'], repository_name=d['service_name'], class_ids=candidate.get('class_ids', []),
                     packages=candidate.get('packages', []), dependencies=candidate.get('dependencies', []), data_signals=candidate.get('data', {}),
                     data_ownership='UNCONFIRMED', data_migration='NOT_AUTHORIZED_OR_EXECUTED')
        prompt = microservice_codegen.prompt_for(brief, files, [], d['version_id'], repo_view.commit, observations=routes, runtime_requirements=RUNTIME_REQUIREMENTS)
        meta = dict(destination='CLAUDE_EXTERNAL', external_transfer=True, provider='CLAUDE', lane='LOCAL_TRIAL', job_id=job_id,
                    repository_id=repo_view.id, commit=repo_view.commit, candidate_id=candidate['id'], source_file_count=len(files),
                    source_context_bytes=len(prompt.encode('utf-8')), source_context_sha256=hashlib.sha256(prompt.encode()).hexdigest(), model=settings.claude_model)
        with sessions() as db:
            if generations_today(db, identity['tenant_id']) >= settings.claude_max_generations_per_day:
                raise RunnerError('DAILY_GENERATION_LIMIT')
        model_event(request_shim, identity, invocation, 'REQUESTED', 'PER_REQUEST_HUMAN_APPROVAL', meta, resource='microservice:' + candidate['id'])
        generated, usage = claude.generate(prompt, settings, client=claude_client)
        checked = microservice_codegen.validate_bundle(generated)
        out = Path(settings.data_dir) / 'conversions' / job_id / d['service_name']
        for item in checked['files']:
            target = out / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item['content'], encoding='utf-8', newline='\n')
        manifest = [dict(path=f['path'], sha256=hashlib.sha256(f['content'].encode()).hexdigest(), bytes=len(f['content'].encode()), rationale=f['rationale']) for f in checked['files']]
        model_event(request_shim, identity, invocation, 'ALLOW', 'STRUCTURED_BUNDLE_VALIDATED', dict(meta, generation_fingerprint=checked['fingerprint'], file_count=len(manifest)),
                    resource='microservice:' + candidate['id'])
        steps.update(generation=dict(fingerprint=checked['fingerprint'], files=manifest, unresolved_questions=checked['unresolved_questions'], usage=usage))
        cost = f", about ${usage['estimated_cost_usd']}" if usage.get('estimated_cost_usd') is not None else ''
        steps.step(current, 'DONE', f"{len(manifest)} files from {usage['model']} in {usage['duration_ms'] // 1000} s ({usage.get('prompt_tokens')} in / {usage.get('output_tokens')} out tokens{cost}).")

        current = 'BUILD_SERVICE'
        steps.step(current, 'RUNNING', 'Building with Maven in Docker; the first build downloads dependencies.')
        built = runner.build_service(d['service_name'], [dict(path=f['path'], content=f['content']) for f in checked['files']])
        steps.update(service=built)
        if built['state'] != 'RUNNING':
            raise RunnerError(built['state'], (built.get('build_log_tail') or '')[-2000:])
        steps.step(current, 'DONE', f"Running at {built['base_url']}.")

        current = 'START_ORIGINAL'
        steps.step(current, 'RUNNING')
        original = runner.start_app(artifact_sha, None)
        original_run = original['id']
        steps.step(current, 'DONE', f"Original application at {original['base_url']}.")

        current = 'COMPARE'
        steps.step(current, 'RUNNING', f'Replaying {len(scenarios)} recorded scenarios against both.')
        comparison = runner.compare(original['base_url'], built['base_url'], scenarios) if scenarios else dict(total=0, counts={}, results=[], method='No recorded scenario matched this candidate.')
        steps.update(comparison=comparison)
        counts = comparison.get('counts', {})
        steps.step(current, 'DONE', f"{counts.get('EQUIVALENT', 0)} equivalent, {counts.get('DIFFERENT', 0)} different, {counts.get('ERROR', 0)} errors of {comparison.get('total', 0)}.")

        current = 'STOP_ORIGINAL'
        steps.step(current, 'RUNNING')
        runner.stop_app(original_run)
        original_run = None
        steps.step(current, 'DONE', 'The generated service keeps running in Docker so you can try it; stop it from this page.')
        verdict = 'EQUIVALENT' if comparison.get('total') and counts.get('EQUIVALENT', 0) == comparison['total'] else 'REVIEW_DIFFERENCES' if comparison.get('total') else 'NOT_COMPARED'
        steps.update(state='COMPLETED', verdict=verdict, finished_at=now().isoformat())
    except (RunnerError, claude.ClaudeFailure, microservice_codegen.BundleFailure, HTTPException, ValueError, OSError) as error:
        code = getattr(error, 'code', None) or (error.args[0] if error.args and isinstance(error.args[0], str) else type(error).__name__)
        detail = getattr(error, 'detail', '') if isinstance(error, RunnerError) else ''
        if current == 'GENERATE' and meta:
            model_event(request_shim, identity, invocation, 'REJECTED', str(code)[:80], meta, resource='microservice:' + meta.get('candidate_id', ''))
        steps.step(current, 'FAILED', f'{code}: {detail}' if detail else str(code))
        steps.update(state='FAILED', error=dict(step=current, code=str(code)[:80], detail=str(detail)[:2000]), finished_at=now().isoformat())
        if original_run:
            try:
                runner.stop_app(original_run)
            except RunnerError:
                pass
