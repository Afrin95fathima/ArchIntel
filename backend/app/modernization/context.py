"""Exact, current facts the plan is built on: what was scanned, observed and reviewed, what changed, and what the plan will and will not use.

Every field is a measured value or {'value': None, 'not_measured': reason}; nothing is defaulted."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AnalysisRun, Artifact
from app.evidence.models import ArchitectureVersion
from app.runtime.models import RuntimeSession


def _field(value, source, unit=None):
    return dict(value=value, source=source, **({'unit': unit} if unit else {}))


def _missing(reason):
    return dict(value=None, not_measured=reason)


def _coverage(metric, label):
    if not metric or metric.get('percentage') is None:
        return _missing((metric or {}).get('reason') or f'{label} coverage is not available for this version')
    return dict(value=metric['percentage'], observed=metric['observed'], total=metric['total'], text=f"{metric['percentage']}% ({metric['observed']} of {metric['total']})", source='version coverage')


def changes_since(db, version, run):
    """Differences from the previous architecture version of the same application."""
    previous = db.get(ArchitectureVersion, version.parent_id) if version.parent_id else None
    if previous is None:
        previous = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == version.application_id, ArchitectureVersion.created_at < version.created_at,
            ArchitectureVersion.id != version.id).order_by(ArchitectureVersion.created_at.desc()).limit(1))
    if previous is None:
        return dict(state='NO_EARLIER_VERSION', text='No earlier architecture version exists for this application, so nothing can be compared.')
    before = db.get(AnalysisRun, previous.analysis_id).result or {}
    after = run.result or {}
    classes_before, classes_after = {c['id'] for c in before.get('classes', [])}, {c['id'] for c in after.get('classes', [])}
    edges_before, edges_after = {(e['source'], e['target']) for e in before.get('edges', [])}, {(e['source'], e['target']) for e in after.get('edges', [])}
    sessions_before, sessions_after = set(previous.manifest.get('runtime_session_ids', [])), set(version.manifest.get('runtime_session_ids', []))
    cov_before = (previous.document.get('coverage') or {}).get('classes', {}).get('percentage') if sessions_before else None
    cov_after = (version.document.get('coverage') or {}).get('classes', {}).get('percentage') if sessions_after else None
    added, removed = sorted(classes_after - classes_before), sorted(classes_before - classes_after)
    rows = dict(previous_version=previous.id, previous_name=previous.name, previous_fingerprint=previous.fingerprint,
        classes_added=len(added), classes_removed=len(removed), added_examples=added[:5], removed_examples=removed[:5],
        dependency_pairs_added=len(edges_after - edges_before), dependency_pairs_removed=len(edges_before - edges_after),
        domains_before=len(before.get('domains', [])), domains_after=len(after.get('domains', [])),
        cycles_before=len(before.get('cycles', [])), cycles_after=len(after.get('cycles', [])),
        sessions_added=len(sessions_after - sessions_before), sessions_removed=len(sessions_before - sessions_after),
        class_coverage_before=cov_before, class_coverage_after=cov_after, same_fingerprint=previous.fingerprint == version.fingerprint)
    rows['text'] = (f"Compared with {previous.name}: {len(added)} class(es) added, {len(removed)} removed; {rows['dependency_pairs_added']} dependency pair(s) added, {rows['dependency_pairs_removed']} removed; "
        f"domains {rows['domains_before']} -> {rows['domains_after']}; cycles {rows['cycles_before']} -> {rows['cycles_after']}; "
        + (f"class coverage {cov_before}% -> {cov_after}%." if cov_before is not None and cov_after is not None else 'class coverage was not measured in both versions.'))
    return rows


def build(db, version) -> dict:
    from app.insight.model import get_model
    from app.insight import lifecycle
    run = db.get(AnalysisRun, version.analysis_id)
    static = run.result or {}
    summary = static.get('summary', {})
    manifest, document = version.manifest, version.document
    artifact = db.get(Artifact, run.artifact_id)
    model = get_model(run.id, static)
    session_ids = manifest.get('runtime_session_ids', [])
    sessions = list(db.scalars(select(RuntimeSession).where(RuntimeSession.id.in_(session_ids)).order_by(RuntimeSession.created_at))) if session_ids else []
    coverage = document.get('coverage') or {}
    lifecycle_findings = lifecycle.evaluate(model, static.get('tech_inventory'))['findings'] if model.facts_available else None
    aging = [f for f in lifecycle_findings if f['status'] in ('aging', 'end-of-life')] if lifecycle_findings is not None else None
    entry_items = model.entry_points['items']
    class_cycles = [c for c in static.get('cycles', []) if c['level'] == 'CLASS']
    review = manifest.get('domain_review')
    session_rows = [dict(id=s.id, name=s.name, environment=s.environment, status=s.status, started_at=s.started_at, ended_at=s.ended_at, traces=s.trace_count, spans=s.span_count) for s in sessions]
    # Without a runtime session the stored coverage is 0 of N by construction; that is not a measurement.
    classes = (coverage.get('classes') or {}) if session_ids else {}
    entries = (coverage.get('entry_points') or {}) if session_ids else {}
    methods = coverage.get('methods') if session_ids else None
    entry_text = (f"{entries['percentage']}% of entry points ({entries['observed']} of {entries['total']}) were observed" if entries.get('percentage') is not None else None)
    takes = [
        f"Static structure: {summary.get('class_count')} classes, {summary.get('package_count')} packages, {summary.get('domain_count')} candidate domains, {len(class_cycles)} class-level cycle group(s).",
        (f"Runtime coverage: {classes['percentage']}% of classes ({classes['observed']} of {classes['total']})" + (f"; {entry_text}" if entry_text else '; entry-point coverage is not measured')
         + '. Unobserved classes and entry points lower the runtime coverage input of confidence; they never count as unused.') if classes.get('percentage') is not None
        else 'Runtime coverage is not measured because no runtime session is attached; runtime coverage and runtime data quality are excluded from confidence.',
        (f"Domain review: recorded by {review['actor']}." if review else 'Domain review: not recorded; the review-status input of confidence is 0.'),
        (f"Aging technology: {len(aging)} finding(s) from the lifecycle rules ({', '.join(f['technology'] + ' ' + f['status'] for f in aging[:5])})." if aging else
         'Aging technology: none flagged by the lifecycle rules.' if aging is not None else 'Aging technology: not measured, this analysis has no bytecode facts.'),
    ]
    does_not = [
        'Behavioral contract tests: none are recorded for this version; behavioral validation is listed as not measured and is not scored.',
        'Data ownership: no review is recorded; shared repositories are reported but ownership is not decided.',
        'Vulnerabilities: out of scope; the lifecycle rules only state vendor support status.',
        'Deployment constraints, availability targets and cost targets: not supplied to the planner.',
    ]
    return dict(
        version=dict(id=_field(version.id, 'architecture version'), name=_field(version.name, 'architecture version'), fingerprint=_field(version.fingerprint, 'architecture version'),
                     captured_at=_field(manifest.get('captured_at'), 'version manifest')),
        scan=dict(analysis_id=_field(run.id, 'analysis run'), scan_date=_field(run.completed_at or run.created_at, 'analysis run'),
                  algorithm_version=_field(static.get('algorithm_version'), 'analysis result') if static.get('algorithm_version') else _missing('the analysis result records no algorithm version')),
        artifact=dict(name=_field(artifact.filename if artifact else summary.get('artifact', {}).get('filename'), 'artifact record'),
                      sha256=_field(manifest.get('artifact_sha256') or (artifact.sha256 if artifact else None), 'version manifest') if (manifest.get('artifact_sha256') or artifact) else _missing('the version manifest records no artifact hash')),
        counts=dict(classes=_field(summary.get('class_count'), 'static summary'), packages=_field(summary.get('package_count'), 'static summary'), domains=_field(summary.get('domain_count'), 'static summary'),
                    class_cycle_groups=_field(len(class_cycles), 'static cycles'),
                    aging_technology_findings=_field(len(aging), 'lifecycle rules') if aging is not None else _missing('this analysis has no bytecode facts; run a new analysis'),
                    entry_points=_field(len(entry_items), 'entry-point detection' if model.facts_available else 'annotation scan') if entry_items else _missing('no entry point was detected')),
        runtime=dict(sessions=session_rows, session_count=len(session_rows),
                     traces=_field(sum(s.trace_count for s in sessions), 'runtime sessions', 'traces (one per request or job)') if sessions else _missing('no runtime session is attached to this version'),
                     class_coverage=_coverage(classes, 'class') if session_ids else _missing('no runtime session is attached to this version'),
                     entry_point_coverage=_coverage(entries, 'entry-point') if session_ids else _missing('no runtime session is attached to this version'), method_coverage=_coverage(methods, 'method') if session_ids else _missing('no runtime session is attached to this version')),
        review=dict(domain_review=dict(value=True, actor=review['actor'], reason=review.get('reason')) if review else _missing('no domain review is recorded for this version'),
                    plan_reviews=_missing('plan review state is shown with each saved proposal')),
        changes=changes_since(db, version, run),
        takes_into_account=takes, does_not_take_into_account=does_not)
