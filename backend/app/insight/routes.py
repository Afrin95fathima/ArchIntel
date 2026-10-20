"""Insight API: evidence-derived views over a completed analysis. All routes are tenant-scoped
through the analysis snapshot lookup; optional runtime evidence comes from the caller's sessions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api import session as db_session, snapshot
from .model import get_model
from . import lifecycle

router = APIRouter(prefix='/api/v1/analyses/{analysis_id}/insight', tags=['Insight'])
glossary_router = APIRouter(prefix='/api/v1/insight', tags=['Insight'])


@glossary_router.get('/glossary', response_model=dict)
def glossary():
    from .glossary import entries
    return dict(entries=entries())


def runtime_evidence(db, request: Request, analysis_id: str, session_ids: str | None) -> tuple[dict | None, str]:
    if not session_ids:
        return None, ''
    from app.services.runtime import session_service as service
    with service.LOCK:
        sessions = [service.get_session(db, identity) for identity in sorted(set(session_ids.split(',')))[:20]]
        if any(s.analysis_id != analysis_id for s in sessions):
            raise HTTPException(404, 'Selected runtime session does not belong to this analysis.')
        result = service.result(db, sessions, request.app.state.config)
        result['observed_methods'] = _observed_methods(db, sessions, request.app.state.config, snapshot(db, analysis_id))
        return result, ','.join(sorted(s.id + ':' + str(s.span_count) for s in sessions))


def _observed_methods(db, sessions, config, static):
    """Handler-level observations from retained spans; None when raw spans were purged or are incomplete."""
    from sqlalchemy import select
    from app.runtime.models import RuntimeEvent
    from app.services.runtime.mapping import map_class
    if any(s.settings.get('events_purged') for s in sessions):
        return None
    events = list(db.scalars(select(RuntimeEvent.data).where(RuntimeEvent.session_id.in_([s.id for s in sessions]))))
    if sessions and not events and any(s.span_count for s in sessions):
        return None
    classes = {c['id']: c for c in static['classes']}
    pairs = set()
    for event in events:
        owner = map_class(event.get('class_name'), classes)['static_id']
        if owner and event.get('method_name'):
            pairs.add((owner, event['method_name']))
    return sorted(pairs)


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


@router.get('/cycles', response_model=dict)
def circular_dependencies(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .cycles import analyse
    model = load(analysis_id, request, db, runtime_session_ids)
    config = request.app.state.config
    return analyse(model, config.max_cycle_length, config.max_cycles_per_scc)


@router.post('/cycles/explain', response_model=dict)
def cycle_explanation(analysis_id: str, body: ExplainInput, request: Request, db=Depends(db_session)):
    """AI may only rephrase one cycle; every sentence must cite loop edges that exist in the analysis."""
    from app.ai.grounded import explain
    from .cycles import analyse
    model = load(analysis_id, request, db)
    cycle = next((c for g in analyse(model)['groups'] for c in g['cycles'] if c['id'] == body.target_id), None)
    if not cycle:
        raise HTTPException(404, 'Cycle not found in this analysis.')
    evidence = [dict(id='edge:' + e['source'] + '->' + e['target'], text=f"{e['source']} -> {e['target']} ({', '.join(e['edge_types'])}). " +
        '; '.join(r['text'] for r in e.get('references', [])[:4]) or ', '.join(p['source'] + ' -> ' + p['target'] for p in e.get('class_pairs', [])[:4])) for e in cycle['edges']]
    ai = explain(request, db, 'CYCLE_EXPLANATION', evidence, 'Explain in plain language why these classes form a loop and what that means for changing them.',
        'analysis:' + analysis_id, set(model.classes) | set(model.packages))
    return dict(cycle_id=cycle['id'], deterministic=cycle['explanation'], ai=ai, evidence_ids=[e['id'] for e in evidence])


@router.get('/metrics', response_model=dict)
def architecture_metrics(analysis_id: str, request: Request, db=Depends(db_session)):
    from .metrics import compute
    return compute(load(analysis_id, request, db))


def _method_names(model, classes) -> set[str]:
    """Names an explanation may mention: methods declared by, or invoked from, the classes it was given."""
    names = set()
    for cls in classes:
        for owner in [cls] + model.nested_by_owner.get(cls, []):
            for method in model.methods_of(owner):
                names.add(method['name'])
                names |= {site['name'] for site in method.get('invokes', [])}
    return names


def _debt(model):
    from .debt import detect
    return detect(model)


@router.get('/debt', response_model=dict)
def technical_debt(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    return _debt(load(analysis_id, request, db, runtime_session_ids))


@router.post('/debt/explain', response_model=dict)
def debt_refactoring(analysis_id: str, body: ExplainInput, request: Request, db=Depends(db_session)):
    """Optional AI refactoring proposal for one finding. Sentences must cite evidence and name only real methods."""
    from app.ai.grounded import explain
    from .source_store import read
    model = load(analysis_id, request, db)
    finding = next((f for f in _debt(model)['findings'] if f['id'] == body.target_id), None)
    if not finding:
        raise HTTPException(404, 'Debt finding not found in this analysis.')
    evidence = [dict(id='finding:' + finding['id'], text=f"{finding['title']}: {finding['explanation']['technical']} Suggested action: {finding['suggested_action']}")]
    evidence += [dict(id=f'evidence:{i}', text=e['text']) for i, e in enumerate(finding['evidence'][:8])]
    methods = set()
    for node in finding['node_ids'][:2]:
        source = read(request.app.state.config, analysis_id, model.result, node, 6000)
        if source['text']:
            evidence.append(dict(id='source:' + node, text=f"[{source['kind']}] {source['text']}"))
        methods |= _method_names(model, [node])
    ai = explain(request, db, 'REFACTORING_PROPOSAL', evidence, 'Propose a refactoring for this finding. Name each method involved as name().',
        'analysis:' + analysis_id, set(model.classes), methods)
    return dict(finding_id=finding['id'], deterministic=dict(explanation=finding['explanation'], suggested_action=finding['suggested_action']), ai=ai,
        evidence_ids=[e['id'] for e in evidence])


@router.get('/graph', response_model=dict)
def explained_graph(analysis_id: str, request: Request, level: str = Query('package', pattern='^(package|class)$'), package: str | None = Query(None, max_length=400),
        focus: str | None = Query(None, max_length=400), min_weight: int = Query(1, ge=1, le=1000), limit: int = Query(400, ge=10, le=400),
        runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .graphview import view
    model = load(analysis_id, request, db, runtime_session_ids)
    return view(model, level, package, focus, min_weight, limit, _debt(model))


@router.get('/unresolved', response_model=dict)
def external_and_unresolved(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .graphview import unresolved
    return unresolved(load(analysis_id, request, db, runtime_session_ids))


@router.get('/node', response_model=dict)
def node_detail(analysis_id: str, request: Request, id: str = Query('system', max_length=800), runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .details import node
    model = load(analysis_id, request, db, runtime_session_ids)
    return node(model, id, _debt(model))


@router.get('/connection', response_model=dict)
def connection_detail(analysis_id: str, request: Request, source: str = Query(max_length=400), target: str = Query(max_length=400), runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .details import connection
    return connection(load(analysis_id, request, db, runtime_session_ids), source, target)


@router.get('/index', response_model=dict)
def search_index(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    """Every top-level class with the facets the explorer filters on."""
    from .cycles import analyse, membership
    from .graphview import _debt_levels
    model = load(analysis_id, request, db, runtime_session_ids)
    cycles = membership(analyse(model))
    levels = _debt_levels(_debt(model))
    observed = model.observed_classes
    rows = [dict(id=fqn, name=fqn.rsplit('.', 1)[-1], package=model.package(fqn), role=model.roles[fqn]['role'], layer=model.roles[fqn]['layer'],
        in_cycle=fqn in cycles, debt=levels.get(fqn), observed=None if observed is None else fqn in observed)
        for fqn in sorted(model.classes) if model.owners.get(fqn, fqn) == fqn]
    return dict(classes=rows, packages=sorted(model.packages), roles=sorted({r['role'] for r in rows}), runtime_included=observed is not None)


@router.get('/tests', response_model=dict)
def next_tests(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .test_suggestions import build
    return build(load(analysis_id, request, db, runtime_session_ids))


@router.post('/tests/explain', response_model=dict)
def next_test_steps(analysis_id: str, body: ExplainInput, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    """Optional AI: write the human steps and edge cases from the handler and service code it reads."""
    from app.ai.grounded import explain
    from .source_store import read
    from .test_suggestions import build
    model = load(analysis_id, request, db, runtime_session_ids)
    suggestion = next((s for s in build(model)['suggestions'] if s['id'] == body.target_id), None)
    if not suggestion:
        raise HTTPException(404, 'Suggestion not found; it may already be observed.')
    entry = suggestion['entry_point']
    evidence = [dict(id='entry:' + suggestion['id'], text=f"{entry['description']} handled by {entry['handler']}. Steps: {' '.join(suggestion['action_steps'])} "
        f"Fields: {', '.join(f['name'] + (' required' if f['required'] else '') + ' ' + '/'.join(f['constraints']) for f in suggestion['sample_request']['form_fields']) if suggestion['sample_request'] else 'n/a'}")]
    methods = set()
    for cls in [entry['handler_class']] + [c for c in suggestion['exercises']['classes'] if c != entry['handler_class'] and model.roles.get(c, {}).get('role') in ('SERVICE', 'REPOSITORY')][:2]:
        source = read(request.app.state.config, analysis_id, model.result, cls, 5000)
        if source['text']:
            evidence.append(dict(id='source:' + cls, text=f"[{source['kind']}] " + source['text']))
        methods |= _method_names(model, [cls])
    ai = explain(request, db, 'TEST_STEPS', evidence, 'Write the exact user steps and 2-4 edge cases (invalid input, error paths) for this test. Name methods as name().',
        'analysis:' + analysis_id, set(model.classes), methods)
    return dict(suggestion_id=suggestion['id'], ai=ai, evidence_ids=[e['id'] for e in evidence])


@router.get('/diagram/hld', response_model=dict)
def diagram_hld(analysis_id: str, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .diagrams import hld
    return hld(load(analysis_id, request, db, runtime_session_ids))


@router.get('/diagram/lld', response_model=dict)
def diagram_lld(analysis_id: str, request: Request, package: str = Query(max_length=400), runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .diagrams import lld
    return lld(load(analysis_id, request, db, runtime_session_ids), package)


@router.get('/diagram/sequence', response_model=dict)
def diagram_sequence(analysis_id: str, request: Request, entry_id: str = Query(max_length=400), runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    """Runtime trace when a matching one is retained; otherwise the static call flow, labelled as such."""
    from sqlalchemy import select
    from app.runtime.models import RuntimeEvent
    from .diagrams import sequence_runtime, sequence_static
    model = load(analysis_id, request, db, runtime_session_ids)
    entry = next((e for e in model.entry_points['items'] if e['id'] == entry_id), None)
    if not entry:
        raise HTTPException(404, 'Entry point not found in this analysis.')
    if runtime_session_ids and entry['kind'] == 'HTTP_ENDPOINT':
        ids = sorted(set(runtime_session_ids.split(',')))[:20]
        events = list(db.scalars(select(RuntimeEvent.data).where(RuntimeEvent.session_id.in_(ids))))
        for verb in entry['http_methods'] or [None]:
            for path in entry['paths']:
                flow = sequence_runtime(events, model, None if verb == 'ANY' else verb, path)
                if flow['status'] == 'AVAILABLE':
                    return flow
    flow = sequence_static(model, entry_id)
    if runtime_session_ids:
        flow['note'] = 'No retained trace matched this entry point in the selected sessions, so this is the static call flow. ' + flow['note']
    return flow


class ChatInput(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


def _application_of(db, analysis_id):
    from app import models as m
    return db.get(m.AnalysisRun, analysis_id).application_id


@router.get('/assistant/tools', response_model=dict)
def assistant_tools(analysis_id: str):
    from .assistant.tools import CATALOG
    return dict(tools=CATALOG, read_only=True, note='No tool changes code or data. Any change must go through a Source task, which requires human approval.')


@router.post('/assistant/ask', response_model=dict)
def assistant_ask(analysis_id: str, body: ChatInput, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    from .assistant.service import ask
    model = load(analysis_id, request, db, runtime_session_ids)
    return ask(request, db, model, analysis_id, _application_of(db, analysis_id), body.question, runtime_session_ids or '')


@router.post('/assistant/chat')
def assistant_chat(analysis_id: str, body: ChatInput, request: Request, runtime_session_ids: str | None = Query(None, max_length=400), db=Depends(db_session)):
    """Newline-delimited JSON events: start, tool_call, tool_result, sentence, done."""
    import json
    from fastapi.responses import StreamingResponse
    from .assistant.service import turn
    model = load(analysis_id, request, db, runtime_session_ids)
    application_id = _application_of(db, analysis_id)
    events = turn(request, db, model, analysis_id, application_id, body.question, runtime_session_ids or '')
    first = next(events)            # raises HTTP errors (rate budget, validation) before the stream starts

    def stream():
        yield json.dumps(first) + '\n'
        for event in events:
            yield json.dumps(event, default=str) + '\n'
    return StreamingResponse(stream(), media_type='application/x-ndjson')


@router.get('/assistant/history', response_model=dict)
def assistant_history(analysis_id: str, request: Request, db=Depends(db_session)):
    from .assistant.service import history
    snapshot(db, analysis_id)
    return dict(messages=history(request, analysis_id))


@router.delete('/assistant/history', response_model=dict)
def assistant_clear(analysis_id: str, request: Request, db=Depends(db_session)):
    from .assistant.service import clear_history
    snapshot(db, analysis_id)
    return dict(deleted=clear_history(request, analysis_id))
