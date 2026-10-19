"""Insight API: evidence-derived views over a completed analysis. All routes are tenant-scoped
through the analysis snapshot lookup; optional runtime evidence comes from the caller's sessions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api import session as db_session, snapshot
from .model import get_model
from . import lifecycle

router = APIRouter(prefix='/api/v1/analyses/{analysis_id}/insight', tags=['Insight'])


def runtime_evidence(db, request: Request, analysis_id: str, session_ids: str | None) -> tuple[dict | None, str]:
    if not session_ids:
        return None, ''
    from app.services.runtime import session_service as service
    with service.LOCK:
        sessions = [service.get_session(db, identity) for identity in sorted(set(session_ids.split(',')))[:20]]
        if any(s.analysis_id != analysis_id for s in sessions):
            raise HTTPException(404, 'Selected runtime session does not belong to this analysis.')
        return service.result(db, sessions, request.app.state.config), ','.join(sorted(s.id + ':' + str(s.span_count) for s in sessions))


def load(analysis_id: str, request: Request, db, runtime_session_ids: str | None = None):
    result = snapshot(db, analysis_id)
    runtime, key = runtime_evidence(db, request, analysis_id, runtime_session_ids)
    return get_model(analysis_id, result, runtime, key)


class ExplainInput(BaseModel):
    target_id: str = Field(min_length=1, max_length=400)


@router.get('/lifecycle', response_model=dict)
def technology_lifecycle(analysis_id: str, request: Request, db=Depends(db_session)):
    model = load(analysis_id, request, db)
    return lifecycle.evaluate(model, model.result.get('tech_inventory'), max_age_days=request.app.state.config.lifecycle_rules_max_age_days)


@router.post('/lifecycle/explain', response_model=dict)
def lifecycle_migration_note(analysis_id: str, body: ExplainInput, request: Request, db=Depends(db_session)):
    """Optional AI migration note for one finding's class group. Deterministic data is returned regardless."""
    from app.ai.grounded import explain
    from .source_store import read
    model = load(analysis_id, request, db)
    evaluation = lifecycle.evaluate(model, model.result.get('tech_inventory'))
    finding = next((f for f in evaluation['findings'] if f['id'] == body.target_id), None)
    if not finding:
        raise HTTPException(404, 'Lifecycle finding not found in this analysis.')
    evidence = [dict(id='rule:' + finding['rule_id'], text=f"{finding['technology']}: {finding['explanation']['technical']} "
        f"Alternative: {finding['recommended_alternative']}. Notes: {finding['migration_notes']}")]
    for row in finding['affected_classes'][:6]:
        sites = '; '.join(s['text'] + (f" (line {s['line']})" if s.get('line') else '') for s in row['call_sites'][:8])
        evidence.append(dict(id='class:' + row['class_name'], text=f"{row['class_name']} uses {', '.join(row['apis'][:6])}. {sites}"))
        source = read(request.app.state.config, analysis_id, model.result, row['class_name'], 3000)
        if source['text']:
            evidence.append(dict(id='source:' + row['class_name'], text=f"[{source['kind']}] " + source['text']))
    known = set(model.classes) | {a for row in finding['affected_classes'] for a in row['apis']}
    note = explain(request, db, 'MIGRATION_NOTE', evidence, 'Write a migration note for these classes: what to change, in what order, and what to test.',
        'analysis:' + analysis_id, known)
    return dict(finding_id=finding['id'], deterministic=dict(alternative=finding['recommended_alternative'], migration_notes=finding['migration_notes'],
        replacement=finding['replacement']), ai=note, evidence_ids=[e['id'] for e in evidence])
