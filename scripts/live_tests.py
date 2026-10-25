"""Live tests for the REA + Claude conversion flow, run one at a time inside the backend container.

    docker compose exec -T -w /app/backend backend python /app/scripts/live_tests.py <step> [options]

Steps (in order): preflight, claude-smoke, explore (or explore-api for a distribution with a launch recipe), convert, status. Each prints what it checked and exits non-zero on failure.
Only claude-smoke and convert call the Claude API; both print the token usage and the estimated cost.
"""
import argparse
import sys
import time

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import build_engine


def connect():
    settings = Settings()
    return settings, sessionmaker(build_engine(settings), expire_on_commit=False)


def line(ok, text):
    print(('  PASS ' if ok else '  FAIL ') + text)
    return ok


def application(db, name):
    from app.models import Application, AnalysisRun
    app = db.scalar(select(Application).where(Application.name == name))
    if not app:
        sys.exit(f'No application named {name!r}.')
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.application_id == app.id, AnalysisRun.status == 'COMPLETED').order_by(AnalysisRun.created_at.desc()))
    return app, run


def human(db, username=None):
    from app.access.models import Principal
    rows = [p for p in db.scalars(select(Principal).where(Principal.kind == 'HUMAN', Principal.active.is_(True))) if 'SOURCE_READ' in p.permissions]
    if username:
        rows = [p for p in rows if p.username == username]
    if not rows:
        sys.exit('No active human account with source-read permission' + (f' named {username!r}' if username else '') + '.')
    return rows[0]


def preflight(args):
    from app.automation.runner import Runner, RunnerError
    settings, sessions = connect()
    ok = True
    runner = Runner(settings)
    ok &= line(runner.configured, 'RUNNER_TOKEN is set for ArchIntel')
    try:
        tools = runner.health()['tools']
        for name in ('java', 'chrome', 'otel_agent', 'rea', 'docker'):
            ok &= line(bool(tools.get(name)), f'runner tool {name}: {tools.get(name)}')
    except RunnerError as error:
        ok &= line(False, f'runner reachable ({error.code}); start it with scripts/runner-start.sh')
    key = (settings.gemini_api_key if args.provider == 'GEMINI' else settings.anthropic_api_key).get_secret_value()
    ok &= line(bool(key), f"{'GEMINI' if args.provider == 'GEMINI' else 'ANTHROPIC'}_API_KEY is set (value not shown)")
    if args.provider == 'GEMINI':
        print(f'  INFO model {settings.gemini_model}, daily cap {settings.gemini_max_generations_per_day}')
    print(f'  INFO model {settings.claude_model}, effort {settings.claude_effort}, daily cap {settings.claude_max_generations_per_day}, refusal fallback {settings.claude_refusal_fallback}')
    with sessions() as db:
        app, run = application(db, args.application)
        ok &= line(run is not None, f'{args.application} has a completed analysis')
    sys.exit(0 if ok else 1)


def gemini_smoke(args):
    """The smallest real Gemini call: checks the key, the model and the structured bundle answer."""
    from app.ai import gemini
    settings, _ = connect()
    prompt = ('Return a JSON bundle with exactly one file: path README.md, operation ADD, content "ArchIntel smoke test", '
              'rationale "smoke test"; and an empty unresolved_questions list.')
    try:
        result, usage = gemini.generate(prompt, settings.model_copy(update=dict(gemini_max_output_tokens=2048)))
    except gemini.GeminiFailure as error:
        line(False, f'Gemini call failed: {error.args[0]}')
        sys.exit(1)
    line(bool(result['files']) and result['files'][0]['path'] == 'README.md', f"structured bundle returned ({len(result['files'])} file)")
    print(f"  INFO {usage['model']}: {usage['prompt_tokens']} input, {usage['output_tokens']} output tokens, {usage['duration_ms']} ms")


def claude_smoke(args):
    """The smallest real call: checks the key, the model, structured output and the fallback parameter together."""
    from app.ai import claude
    settings, _ = connect()
    small = settings.model_copy(update=dict(claude_effort='low', claude_max_output_tokens=4000))
    prompt = ('Return a JSON bundle with exactly one file: path README.md, operation ADD, content "ArchIntel smoke test", '
              'rationale "smoke test"; and an empty unresolved_questions list.')
    try:
        result, usage = claude.generate(prompt, small)
    except claude.ClaudeFailure as error:
        line(False, f'Claude call failed: {error.args[0]}')
        if error.args[0] == 'PROVIDER_REJECTED' and settings.claude_refusal_fallback:
            print('  HINT If the API rejected the fallback parameter, set CLAUDE_REFUSAL_FALLBACK=false in .env and restart.')
        sys.exit(1)
    line(result['files'] and result['files'][0]['path'] == 'README.md', f"structured bundle returned ({len(result['files'])} file)")
    print(f"  INFO {usage['model']}: {usage['prompt_tokens']} input, {usage['output_tokens']} output tokens, {usage['duration_ms']} ms, estimated ${usage['estimated_cost_usd']}")


def explore(args):
    from app.automation import explore as exploration
    from app.automation.models import AutomationJob
    settings, sessions = connect()
    jar = open(args.jar, 'rb').read()
    with sessions() as db:
        app, run = application(db, args.application)
        person = human(db, args.username)
        job = exploration.create(db, dict(tenant_id=app.tenant_id, id=person.id), app.id, run.id, jar,
                                 dict(max_pages=args.max_pages, max_forms=args.max_forms, mode='DEEP', artifact_name=args.jar.rsplit('/', 1)[-1]))
        job_id = job.id
    print(f'  INFO exploration {job_id} started')
    exploration.run(sessions, settings, job_id, jar)
    report(sessions, job_id)


def explore_api(args):
    from app.automation import explore_api as exploration
    settings, sessions = connect()
    spec = exploration.recipe(args.recipe)
    if spec is None:
        sys.exit(f'No launch recipe named {args.recipe!r}.')
    distribution = open(args.distribution, 'rb').read()
    with sessions() as db:
        app, run = application(db, args.application)
        person = human(db, args.username)
        job = exploration.create(db, dict(tenant_id=app.tenant_id, id=person.id), app.id, run.id, distribution, spec,
                                 dict(mode=args.mode, max_requests=args.max_requests, passes=args.passes, artifact_name=args.distribution.rsplit('/', 1)[-1], scenario_source='RECIPE'))
        job_id = job.id
    print(f'  INFO API exploration {job_id} started with recipe {args.recipe} on analysis {run.id[:8]}')
    exploration.run(sessions, settings, job_id, distribution, spec)
    with sessions() as db:
        from app.automation.models import AutomationJob
        document = db.get(AutomationJob, job_id).document
    if (document.get('exploration') or {}).get('summary'):
        print(f"  INFO {document['exploration']['summary']}")
    for item in document.get('passes', []):
        print(f"  PASS {item['index']}: {item['plan_classes']} classes planned, {item['spans']:,} spans, classes reached {item['classes'].get('observed')} of {item['classes'].get('total')}")
    if document.get('coverage'):
        c = document['coverage']
        print(f"  COVERAGE classes {c['classes'].get('observed')}/{c['classes'].get('total')}, entry points {(c.get('entry_points') or {}).get('observed')}/{(c.get('entry_points') or {}).get('total')}, methods {(c.get('methods') or {}).get('observed')}/{(c.get('methods') or {}).get('total')}")
    report(sessions, job_id)


def convert(args):
    from app.automation import convert as conversion
    from app.access.models import SourceGrant, SourceRepository
    from app.evidence.models import ArchitectureVersion
    from app.modernization import service as planning
    from app.modernization.models import Assessment
    settings, sessions = connect()
    with sessions() as db:
        app, run = application(db, args.application)
        person = human(db, args.username)
        identity = dict(id=person.id, tenant_id=person.tenant_id, kind='HUMAN')
        version = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == app.id).order_by(ArchitectureVersion.created_at.desc(), ArchitectureVersion.id.desc()))
        plans = [p for p in db.scalars(select(Assessment).where(Assessment.version_id == version.id).order_by(Assessment.created_at.desc()))
                 if (planning.reviews(db, p.id) or [{}])[-1].get('state') == 'APPROVED_PLANNING']
        plan = next((p for p in plans if any(c['name'] == args.candidate for c in (p.document.get('microservice_decomposition') or {}).get('service_candidates', []))), None)
        if not plan:
            sys.exit(f'No approved plan on the latest version {version.id[:8]} lists a candidate named {args.candidate!r}. Save and approve one in Modernization first.')
        candidate = next(c for c in plan.document['microservice_decomposition']['service_candidates'] if c['name'] == args.candidate)
        grants = {g.repository_id for g in db.scalars(select(SourceGrant).where(SourceGrant.principal_id == person.id))}
        repo = next((r for r in db.scalars(select(SourceRepository).where(SourceRepository.application_id == app.id)) if r.id in grants), None)
        rows = conversion.preconditions(db, settings, identity, version, plan, candidate['id'], repo.id if repo else '', args.provider)
        for row in rows:
            line(row['met'], row['text'])
        if not all(r['met'] for r in rows):
            sys.exit(1)
        if not args.yes:
            sys.exit(f"Add --yes to confirm that the selected source of this candidate may be sent to {conversion.PROVIDERS[args.provider]['label']}.")
        job = conversion.create(db, settings, identity, version, plan, candidate['id'], repo.id, conversion.PROVIDERS[args.provider]['ack'], args.provider)
        job_id = job.id
    print(f'  INFO conversion {job_id} started for {args.candidate} with {args.provider}; it also appears on the Modernization page')
    conversion.run(sessions, settings, job_id, identity)
    report(sessions, job_id)


def report(sessions, job_id):
    from app.automation.models import AutomationJob
    with sessions() as db:
        job = db.get(AutomationJob, job_id)
        print(f'  RESULT {job.kind} {job.state}' + (f" verdict {job.document.get('verdict')}" if job.document.get('verdict') else ''))
        for step in job.document.get('steps', []):
            print(f"    {step['state']:8} {step['name']}: {step.get('detail') or ''}")
        if job.document.get('error'):
            print(f"  ERROR {job.document['error']}")
        usage = (job.document.get('generation') or {}).get('usage')
        if usage:
            print(f"  COST {usage.get('prompt_tokens')} in / {usage.get('output_tokens')} out tokens, estimated ${usage.get('estimated_cost_usd')}")
        service = job.document.get('service') or {}
        if service.get('base_url'):
            print(f"  SERVICE {service.get('state')} at {service['base_url']}")
    sys.exit(0 if job.state == 'COMPLETED' else 1)


def status(args):
    from app.automation.models import AutomationJob
    _, sessions = connect()
    with sessions() as db:
        for job in db.scalars(select(AutomationJob).order_by(AutomationJob.created_at.desc()).limit(args.limit)):
            print(f"{job.created_at:%Y-%m-%d %H:%M} {job.kind:8} {job.state:10} {job.document.get('candidate_name') or job.document.get('options', {}).get('artifact_name', '')} {job.document.get('verdict') or ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=['preflight', 'claude-smoke', 'gemini-smoke', 'explore', 'explore-api', 'convert', 'status'])
    parser.add_argument('--provider', default='CLAUDE', choices=['CLAUDE', 'GEMINI'])
    parser.add_argument('--application', default='Spring PetClinic')
    parser.add_argument('--candidate', default='Vet')
    parser.add_argument('--username', default=None)
    parser.add_argument('--jar', default='/tmp/petclinic.jar')
    parser.add_argument('--max-pages', type=int, default=40)
    parser.add_argument('--max-forms', type=int, default=12)
    parser.add_argument('--recipe', default='concord-server')
    parser.add_argument('--distribution', default='/tmp/distribution.tar.gz')
    parser.add_argument('--mode', default=None, choices=['BOUNDARY', 'STANDARD', 'DEEP'])
    parser.add_argument('--max-requests', type=int, default=None)
    parser.add_argument('--passes', type=int, default=None)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    started = time.monotonic()
    dict(preflight=preflight, **{'claude-smoke': claude_smoke, 'gemini-smoke': gemini_smoke}, explore=explore, **{'explore-api': explore_api}, convert=convert, status=status)[args.step](args)
    print(f'  INFO took {time.monotonic() - started:.0f} s')


if __name__ == '__main__':
    main()
