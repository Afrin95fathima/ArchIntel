"""Independent publication gate for deterministic proposals, not code validation."""
import math
import networkx as nx


def validate(document, facts, evidence):
    errors = []
    def check(condition, code):
        if not condition: errors.append(code)
    fby = {f['id']: f for f in facts}; eby = {e['id']: e for e in evidence}
    findings = {f['id']: f for f in document['findings']}
    domains = {a['domain_id']: a for a in document['assessments']}
    check(len(domains) == len(document['assessments']), 'DUPLICATE_DOMAIN')
    brief = document.get('decision_brief', {})
    check(brief.get('selected_strategy') == document.get('target', {}).get('strategy'), 'BRIEF_STRATEGY_MISMATCH')
    check(brief.get('selection_source') == 'USER_INPUT' and brief.get('automatic_winner') is None, 'AUTOMATIC_STRATEGY_CLAIM')
    for row in brief.get('strategy_comparison', []):
        check(all(fid in findings for fid in row.get('finding_ids', [])), 'STRATEGY_FINDING_MISSING')
        check(row.get('status') in {'EVIDENCE_SUPPORTS_REVIEW', 'CONDITIONAL', 'INSUFFICIENT_EVIDENCE', 'INVENTORY_AVAILABLE_REVIEW_REQUIRED'}, 'UNKNOWN_STRATEGY_STATUS')
    if brief.get('facts') is not None:
        from .brief import unregistered_numbers, _format
        check(all(f.get('text') == _format(f['value']) for f in brief['facts']), 'BRIEF_FACT_TEXT_MISMATCH')
        check(unregistered_numbers(brief) == [], 'BRIEF_NUMBER_NOT_IN_FACT_TABLE')
        check(len({f['id'] for f in brief['facts']}) == len(brief['facts']), 'BRIEF_FACT_DUPLICATED')
        check(brief.get('recommendation', {}).get('option') in {'MODULAR_MONOLITH', 'MICROSERVICES', 'HYBRID', 'CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE'}, 'BRIEF_RECOMMENDATION_UNKNOWN')
    for risk in brief.get('material_risks', []):
        check(all(fid in findings for fid in risk.get('finding_ids', [])), 'BRIEF_FINDING_MISSING')
    decomposition = document.get('microservice_decomposition', {})
    candidate_ids = {row.get('id') for row in decomposition.get('service_candidates', [])}
    check(candidate_ids == {row.get('domain_id') for row in document.get('target', {}).get('components', [])}, 'SERVICE_CANDIDATE_MISMATCH')
    for candidate in decomposition.get('service_candidates', []):
        check(set(candidate.get('dependencies', []) + candidate.get('consumers', [])) <= candidate_ids, 'SERVICE_BOUNDARY_REFERENCE_MISSING')
        check(all(eid in eby for eid in candidate.get('evidence_ids', [])), 'SERVICE_EVIDENCE_MISSING')
        check(all(fid in fby for fid in candidate.get('fact_ids', [])), 'SERVICE_FACT_MISSING')
        check(all(risk.get('finding_id') in findings and all(eid in eby for eid in risk.get('evidence_ids', [])) for risk in candidate.get('risks', [])), 'SERVICE_RISK_PROVENANCE_MISSING')
    check(decomposition.get('execution', {}).get('allowed') is False, 'SERVICE_GENERATION_UNGATED')
    for f in facts:
        check(bool(f['evidence_ids']) and all(e in eby for e in f['evidence_ids']), 'FACT_SUPPORT_MISSING')
        for eid in f['evidence_ids']:
            if eid in eby:
                e = eby[eid]
                check((e['source'], e['target']) == (f['source'], f['target']), 'FACT_SUPPORT_MISMATCH')
        kinds = {eby[e]['kind'] for e in f['evidence_ids'] if e in eby}
        required = {'STATIC_ONLY': {'STATIC'}, 'DYNAMIC_ONLY': {'RUNTIME'}, 'STATIC_AND_DYNAMIC': {'STATIC', 'RUNTIME'}}.get(f['classification'])
        check(required is not None and required <= kinds, 'FACT_CLASSIFICATION_UNSUPPORTED')
    for item in document['findings'] + document['decisions'] + document['assessments']:
        check(bool(item['evidence_ids']) and all(e in eby for e in item['evidence_ids']), 'CONCLUSION_SUPPORT_MISSING')
        check(all(f in fby for f in item['fact_ids']), 'CONCLUSION_FACT_MISSING')
    for a in domains.values():
        for prefix in ('structural', 'runtime', 'confidence'):
            score = a[prefix + '_score']
            if prefix == 'runtime' and score is None: continue
            components, weights = a[prefix + '_components'], a[prefix + '_weights']
            check(abs(sum(weights.values()) - 1) < .000001, 'INVALID_WEIGHTS')
            values = list(components.values()) + [score]
            if not all(isinstance(v, (float, int)) and math.isfinite(v) and 0 <= v <= 100 for v in values):
                errors.append('INVALID_SCORE'); continue
            # Baseline components are rounded to two decimals; preserve its one-decimal score.
            check(abs(sum(components[k] * w for k, w in weights.items()) - score) <= .06, 'SCORE_ARITHMETIC')
        expected = a['structural_score'] if a['runtime_score'] is None else round(.6 * a['structural_score'] + .4 * a['runtime_score'], 1)
        check(a['combined_score'] == expected, 'COMBINED_ARITHMETIC')
        check('behavioral_validation' not in a['confidence_components'] and 'data_ownership' not in a['confidence_components'], 'INVENTED_VALIDATION')
        check({'behavioral_validation', 'data_ownership'} <= {e['input'] for e in a.get('confidence_not_measured', [])}, 'UNMEASURED_INPUT_NOT_DISCLOSED')
        if a.get('readiness_label') == 'READY_TO_PLAN':
            check(a['confidence_score'] >= 50 and not a.get('hard_blockers'), 'UNSUPPORTED_READY_LABEL')
        check(a.get('confidence_adjusted_score') == round(a['combined_score'] * a['confidence_score'] / 100, 1), 'CONFIDENCE_ADJUSTMENT_MISMATCH')
    check({d['domain_id'] for d in document['decisions']} == set(domains) and len(document['decisions']) == len(domains), 'DECISION_DOMAIN_MISMATCH')
    for d in document['decisions']:
        check(d['execution_allowed'] is False and d['kind'] != 'EXTRACT_NOW', 'UNSUPPORTED_EXECUTION')
        check(bool(d['finding_ids']) and all(f in findings and findings[f]['domain_id'] == d['domain_id'] for f in d['finding_ids']), 'FINDING_LINK_MISMATCH')
        check('BEHAVIORAL_CONTRACTS' in d['blockers'] and 'DATA_OWNERSHIP_REVIEW' in d['blockers'], 'MISSING_SAFETY_PREREQUISITE')
        if any(fby[f].get('conflict_ids') for f in d['fact_ids'] if f in fby): check(d['kind'] == 'MANUAL_REVIEW_REQUIRED', 'CONFLICT_NOT_BLOCKED')
        check(d['kind'] in {'BREAK_CYCLE_FIRST', 'ISOLATE_DATA_FIRST', 'REDUCE_COUPLING_FIRST', 'COLLECT_MORE_EVIDENCE', 'RETAIN_MODULAR_MONOLITH', 'PREPARE_FOR_EXTRACTION', 'MANUAL_REVIEW_REQUIRED'}, 'UNKNOWN_DECISION')
        kinds = {findings[f]['kind'] for f in d['finding_ids'] if f in findings}
        if d['kind'] == 'BREAK_CYCLE_FIRST': check('CROSS_DOMAIN_CYCLE' in kinds, 'UNSUPPORTED_CYCLE_CONCLUSION')
        if d['kind'] == 'ISOLATE_DATA_FIRST': check('SHARED_PERSISTENCE_CANDIDATE' in kinds, 'UNSUPPORTED_DATA_CONCLUSION')
        if d['kind'] == 'REDUCE_COUPLING_FIRST': check('HIGH_STRUCTURAL_COUPLING' in kinds, 'UNSUPPORTED_COUPLING_CONCLUSION')
        if 'CROSS_DOMAIN_CYCLE' in kinds: check(d['kind'] in {'BREAK_CYCLE_FIRST', 'MANUAL_REVIEW_REQUIRED'}, 'CYCLE_NOT_BLOCKED')
        if d['kind'] in {'RETAIN_MODULAR_MONOLITH', 'PREPARE_FOR_EXTRACTION'}:
            check(not kinds.intersection({'LIMITED_OBSERVATION', 'UNREVIEWED_BOUNDARY', 'UNRESOLVED_RUNTIME_BOUNDARY', 'RUNTIME_QUALITY_LIMITATION', 'CONFLICTING_EVIDENCE', 'HIGH_STRUCTURAL_COUPLING', 'SHARED_PERSISTENCE_CANDIDATE'}), 'UNRESOLVED_FINDING_NOT_BLOCKED')
    graph = nx.DiGraph(); graph.add_nodes_from(domains)
    graph.add_edges_from((e['source'], e['target']) for e in document['dependency_edges'])
    wave_by = {}; groups = []
    for w in document['waves']:
        check(w['execution_allowed'] is False, 'WAVE_EXECUTION_NOT_ALLOWED')
        for d in w['domains']:
            check(d not in wave_by and d in domains, 'WAVE_DOMAIN_DUPLICATED_OR_UNKNOWN'); wave_by[d] = w['number']
        groups.extend(set(g) for g in w['coupled_groups'])
    check(set(wave_by) == set(domains), 'WAVE_DOMAIN_MISSING')
    for group in nx.strongly_connected_components(graph):
        if len(group) > 1: check(group in groups and len({wave_by.get(d) for d in group}) == 1, 'CYCLE_GROUP_SPLIT')
    for s, t in graph.edges:
        if s in wave_by and t in wave_by:
            check(wave_by[t] < wave_by[s] or any(s in g and t in g for g in groups), 'DEPENDENCY_ORDER_INVALID')
    node_ids = {n['id'] for n in document['graph']['nodes']}
    check(all(e['source'] in node_ids and e['target'] in node_ids for e in document['graph']['edges']), 'GRAPH_DANGLING_REFERENCE')
    return dict(status='VALIDATED' if not errors else 'REJECTED', validator_version='proposal-validator-1', errors=sorted(set(errors)),
                scope='Reference integrity, arithmetic, dependency order and publication safety. Not behavioral equivalence or empirical calibration.')
