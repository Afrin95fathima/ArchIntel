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
                note='Latest captured application version defines current planning context; historical assessments remain immutable.')


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


def answer(item, body):
    decision = next((d for d in item.document['decisions'] if d['id'] == body.decision_id), None)
    if not decision: raise HTTPException(404, 'Decision not found in this assessment.')
    findings = [f for f in item.document['findings'] if f['id'] in decision['finding_ids']]
    texts = [f['text'] for f in findings] if body.question == 'WHY' else decision['blockers'] if body.question == 'BLOCKERS' else [decision['action']]
    return dict(mode='DETERMINISTIC_EVIDENCE_RETRIEVAL', answer=' '.join(texts), decision=decision, findings=findings,
        evidence_ids=decision['evidence_ids'], fact_ids=decision['fact_ids'], version_id=item.version_id,
        limitations=['Answers are limited to this frozen assessment. No model calls, arbitrary questions, Cypher or source execution.'])
