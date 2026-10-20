"""Immutable assessments and revision-checked planning review."""
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from fastapi import HTTPException
from app.api import get
from app.models import AnalysisRun
from app.evidence.models import ArchitectureVersion, ArchitectureFact, Evidence
from app.evidence.builder import digest
from app.evidence import projection
from .models import Assessment, PlanReview
from . import engine, validation


def material(db, version):
    static = get(db, AnalysisRun, version.analysis_id).result
    if digest(static) != version.manifest['static_sha256']:
        raise HTTPException(409, 'The source snapshot changed. Capture a new architecture version.')
    facts = [dict(id=f.id, **f.document) for f in db.scalars(select(ArchitectureFact).where(ArchitectureFact.version_id == version.id).order_by(ArchitectureFact.id))]
    evidence = [dict(id=e.id, kind=e.kind, **e.document) for e in db.scalars(select(Evidence).where(Evidence.version_id == version.id).order_by(Evidence.id))]
    if len(version.document['domains']) > 500 or len(facts) > 30000:
        raise HTTPException(413, 'Planning currently supports up to 500 domains and 30,000 dependency facts per version.')
    return static, facts, evidence


def create(db, version, body, actor, config, preview=False):
    if not body.objective.strip(): raise HTTPException(422, 'Provide a planning objective.')
    static, facts, evidence = material(db, version)
    fingerprint = digest(dict(version=version.fingerprint, input=digest(dict(document=version.document, facts=facts, evidence=evidence)),
                              options=body.model_dump(), rules=engine.RULE_VERSION, calibration=engine.CALIBRATION))
    existing = db.scalar(select(Assessment).where(Assessment.version_id == version.id, Assessment.fingerprint == fingerprint))
    if existing: return existing.document if preview else existing
    aid = str(uuid5(NAMESPACE_URL, 'archintel-modernization:' + version.tenant_id + ':' + fingerprint))
    document = engine.build(aid, version, static, facts, evidence, body.model_dump())
    document['validation'] = validation.validate(document, facts, evidence)
    document['fingerprint'] = fingerprint
    if document['validation']['status'] != 'VALIDATED':
        raise HTTPException(409, dict(message='Proposal failed independent publication validation.', validation=document['validation']))
    if len(document['graph']['nodes']) > 100000 or len(document['graph']['edges']) > 250000:
        raise HTTPException(413, 'Planning graph exceeds the supported projection budget.')
    if preview: return document
    item = Assessment(id=aid, tenant_id=version.tenant_id, version_id=version.id, fingerprint=fingerprint, actor_id=actor, document=document)
    db.add(item); db.commit()
    if config.knowledge_graph_enabled: rebuild(db, item, config)
    return item


def context(db, version):
    latest = db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.application_id == version.application_id).order_by(ArchitectureVersion.created_at.desc(), ArchitectureVersion.id.desc()).limit(1))
    # Do not disclose the ID of a newer runtime version to static-only readers.
    return dict(state='CURRENT' if latest and latest.id == version.id else 'SUPERSEDED',
                note=f"The latest captured version of this application defines the current planning context; version {version.id[:8]} is {'the latest' if latest and latest.id == version.id else 'superseded'}.")


def reviews(db, aid):
    return [dict(id=r.id, revision=r.revision, state=r.state, note=r.note, actor_id=r.actor_id, created_at=r.created_at)
            for r in db.scalars(select(PlanReview).where(PlanReview.assessment_id == aid).order_by(PlanReview.revision))]


def view(db, version, item):
    return dict(id=item.id, version_id=item.version_id, created_at=item.created_at, fingerprint=item.fingerprint, actor_id=item.actor_id,
        document=item.document, context=context(db, version), reviews=reviews(db, item.id),
        projection=dict(state=item.projection_state, attempts=item.projection_attempts, error_code=item.projection_error))


def owned(db, version, aid):
    item = get(db, Assessment, aid)
    if item.version_id != version.id: raise HTTPException(404, 'Assessment not found in this architecture version.')
    return item


def review(db, version, item, body, actor):
    if not body.note.strip(): raise HTTPException(422, 'Provide a review note.')
    if context(db, version)['state'] != 'CURRENT': raise HTTPException(409, 'This version has been superseded. Review a plan for the latest captured version.')
    history = reviews(db, item.id)
    if len(history) != body.expected_revision: raise HTTPException(409, 'Review changed. Refresh before saving.')
    if len(history) >= 100: raise HTTPException(409, 'Review history limit reached; create a new version and proposal.')
    db.add(PlanReview(tenant_id=item.tenant_id, assessment_id=item.id, revision=len(history) + 1, actor_id=actor, state=body.state, note=body.note))
    db.commit()
    return view(db, version, item)


def graph_item(item):
    return SimpleNamespace(id=item.id, tenant_id=item.tenant_id, document=item.document)


def rebuild(db, item, config):
    item.projection_attempts += 1
    try:
        projection.apply(config, graph_item(item)); item.projection_state = 'APPLIED'; item.projection_error = None
    except Exception as error:
        item.projection_state = 'FAILED'; item.projection_error = type(error).__name__
    db.commit()
    return dict(state=item.projection_state, attempts=item.projection_attempts, error_code=item.projection_error)


def _reason(finding):
    """One finding as a rule id, measured value, threshold, named subjects and evidence ids. Older proposals lack the measured fields."""
    recorded = 'measured' in finding
    return dict(rule_id=finding.get('rule_id') or finding['kind'], severity=finding['severity'], text=finding['text'],
        measured=finding.get('measured') or {}, threshold=finding.get('threshold') or {}, subjects=finding.get('subjects') or [],
        evidence_ids=finding['evidence_ids'], fact_count=len(finding['fact_ids']), measured_fields_recorded=recorded)


def answer(item, body, request=None, db=None):
    decision = next((d for d in item.document['decisions'] if d['id'] == body.decision_id), None)
    if not decision: raise HTTPException(404, 'Decision not found in this assessment.')
    findings = [f for f in item.document['findings'] if f['id'] in decision['finding_ids']]
    reasons = [_reason(f) for f in findings]
    texts = [f['text'] for f in findings] if body.question == 'WHY' else decision['blockers'] if body.question == 'BLOCKERS' else [decision['action']]
    result = dict(mode='DETERMINISTIC_EVIDENCE_RETRIEVAL', answer=' '.join(texts), decision=decision, findings=findings, reasons=reasons,
        decision_rule=dict(rule_id=decision['kind'], action=decision['action'], blockers=decision['blockers']),
        evidence_ids=decision['evidence_ids'], fact_ids=decision['fact_ids'], version_id=item.version_id,
        ai=dict(status='NOT_REQUESTED'),
        limitations=[f'Answers are limited to this proposal (assessment {item.id[:8]}). No arbitrary questions, Cypher or source execution.'])
    if body.with_ai and request is not None:
        from app.ai.grounded import explain
        evidence = [dict(id='finding:' + f['id'], text=f"{r['rule_id']}: {r['text']} Measured {r['measured']}; threshold {r['threshold']}; involved {', '.join(r['subjects'])}.")
                    for f, r in zip(findings, reasons)]
        domain = next((a for a in item.document['assessments'] if a['domain_id'] == decision['domain_id']), {})
        known = {s for r in reasons for s in r['subjects']} | {domain.get('domain_name', '')}
        result['ai'] = explain(request, db, 'DECISION_EXPLANATION', evidence, 'Explain in plain language why this decision was made for this domain, using only the supplied findings.',
            'assessment:' + item.id, known)
    return result


def technology_ai(item, request, db):
    """Optional model wording for the technology plan. The plan and every choice in it are deterministic; the model may only add a cited rationale
    or propose an alternative, and a proposal outside the curated candidates is labelled unverified."""
    from app.ai.grounded import model_call, verify_sentences, SYSTEM
    from app.insight import modernization_plan as mp
    plan = item.document.get('technology_plan') or {}
    if not plan.get('items'):
        return dict(status='NOT_AVAILABLE', reason='NO_PLAN_ITEMS', recommendations=[], dropped=[])
    evidence = []
    for i in plan['items'][:24]:
        names = ', '.join(c.rsplit('.', 1)[-1] for c in i['affected_classes'][:6])
        evidence.append(dict(id='rule:' + i['rule_id'], text=f"{i['technology']} is {i['status']}; {len(i['affected_classes'])} classes use it ({names}). Chosen: {i['recommended']['name']} (needs Java {i['recommended']['requires_java']}). "
                             f"Alternatives: {'; '.join(a['name'] + ' - ' + a['reason'] for a in i['alternatives']) or 'none'}. Phase {i['phase']}."))
    local = {f'e{n}': e['id'] for n, e in enumerate(evidence)}
    envelope = dict(instruction='For each rule, explain in one or two sentences why the chosen candidate fits this application, or propose a different candidate from your knowledge and say so. Cite the evidence ids. Choose among the listed candidate ids when you agree with the plan.',
                    evidence=[dict(id=k, text=e['text']) for (k, _), e in zip(local.items(), evidence)])
    schema = {'type': 'object', 'properties': {'recommendations': {'type': 'array', 'maxItems': 24, 'items': {'type': 'object', 'properties': {
        'rule_id': {'type': 'string', 'enum': [i['rule_id'] for i in plan['items']]}, 'choice': {'type': 'string'}, 'rationale': {'type': 'string'},
        'cite': {'type': 'array', 'items': {'type': 'string', 'enum': sorted(local)}}}, 'required': ['rule_id', 'choice', 'rationale', 'cite'], 'additionalProperties': False}}},
        'required': ['recommendations'], 'additionalProperties': False}
    output, info = model_call(request, db, 'TECHNOLOGY_PLAN', envelope, schema, SYSTEM, 'assessment:' + item.id, max_tokens=900)
    if output is None:
        return dict(status='NOT_AVAILABLE', reason=info['reason'], request_id=info['request_id'], recommendations=[], dropped=[])
    kept, dropped = mp.verify_ai(output, plan, local)
    known = {c for i in plan['items'] for c in i['affected_classes']} | {i['technology'] for i in plan['items']} | {i['recommended']['name'] for i in plan['items']} | {a['name'] for i in plan['items'] for a in i['alternatives']}
    final = []
    for row in kept:
        ok, bad = verify_sentences([dict(text=row['rationale'], cite=[k for k, v in local.items() if v in row['citations']])], local, known)
        if ok:
            final.append(row)
        else:
            dropped.append(dict(text=row['rationale'][:200], reason='UNVERIFIED_IDENTIFIER'))
    return dict(status='AI_GENERATED' if final else 'NOT_AVAILABLE', reason=None if final else 'NO_VERIFIED_RECOMMENDATIONS', recommendations=final, dropped=dropped, request_id=info['request_id'],
                label='AI-written wording. Each recommendation cites its rule id (rule:log4j-1 style); a choice outside modernization-candidates.yaml is marked unverified, confirm before use. The technology plan of this proposal is unchanged by this wording.')
