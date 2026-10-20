"""Plain, specific descriptions of every modernization item, built from the finished plan document.

Each sentence carries a name or a measured number from the analysis. Nothing here is a template that would read
the same for another application: values, class names, domain names, wave numbers and blocker subjects all come
from the assessments, findings, waves and dependency matrix.
"""
from __future__ import annotations

from .blockers import explain as explain_blocker

FINDING_BY_BLOCKER = {'CROSS_DOMAIN_CYCLE': 'CROSS_DOMAIN_CYCLE', 'SHARED_PERSISTENCE_REVIEW': 'SHARED_PERSISTENCE_CANDIDATE'}


def _list(items, limit=4):
    items = list(items)
    return ', '.join(items[:limit]) + (f' and {len(items) - limit} more' if len(items) > limit else '')


def _n(count, noun, plural=None):
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


def _short(name):
    return name.rsplit('.', 1)[-1]


def decision_action(kind: str, name: str, assessment: dict, findings: list[dict], matrix_rows: list[dict], wave_names: dict) -> str:
    """The proposed action for one decision, with the numbers and names that justify it."""
    by_kind = {f['kind']: f for f in findings}
    recommendation = (assessment.get('recommendations') or [{}])[0]
    pairs = recommendation.get('dependency_pairs') or []
    example = f"{_short(pairs[0]['source'])} -> {_short(pairs[0]['target'])}" if pairs else None
    if kind == 'BREAK_CYCLE_FIRST':
        f = by_kind.get('CROSS_DOMAIN_CYCLE', {})
        return (f"Break the dependency cycle between {_list(f.get('subjects', [name]))} before separating {name}"
                + (f"; the class pairs that cross its boundary include {example}." if example else '.'))
    if kind == 'ISOLATE_DATA_FIRST':
        f = by_kind.get('SHARED_PERSISTENCE_CANDIDATE', {})
        return f"Decide which domain owns {_list(f.get('subjects', []))} before changing {name}: {f.get('measured', {}).get('shared_resources', 0)} database resource(s) are called by more than one domain."
    if kind == 'REDUCE_COUPLING_FIRST':
        f = by_kind.get('HIGH_STRUCTURAL_COUPLING', {})
        return (f"Narrow the interface of {name}: {round(100 * f.get('measured', {}).get('external_coupling', 0), 1)}% of its outgoing dependency pairs cross the boundary"
                + (f", for example {example}." if example else '.') + (f" Start with {_list(_short(s) for s in f.get('subjects', []))}." if f.get('subjects') else ''))
    if kind == 'COLLECT_MORE_EVIDENCE':
        obs = assessment.get('observation') or {}
        gaps = [f['text'] for f in findings if f['kind'] in ('LIMITED_OBSERVATION', 'UNREVIEWED_BOUNDARY', 'UNRESOLVED_RUNTIME_BOUNDARY', 'RUNTIME_QUALITY_LIMITATION')]
        return f"Collect the missing evidence for {name} before deciding: " + ' '.join(gaps[:3]) if gaps else f"Collect more evidence for {name} ({obs.get('observed')} of {obs.get('total')} classes observed)."
    if kind == 'RETAIN_MODULAR_MONOLITH':
        return f"Keep {name} ({assessment['runtime_coverage']['classes']['total']} classes) in-process and write a module contract for it; no blocking finding was raised."
    if kind == 'PREPARE_FOR_EXTRACTION':
        return f"Prepare {name} for extraction: pin the source, add behavioral contract tests and confirm data ownership; readiness {assessment['structural_score']}/100, confidence {assessment['confidence_score']}/100."
    f = by_kind.get('CONFLICTING_EVIDENCE')
    return f"Resolve the evidence conflict in {name} with an architect" + (f": {_list(f.get('subjects', []))}." if f else ' before relying on the plan.')


def _lowest_inputs(details, count=2):
    ranked = sorted((details or {}).values(), key=lambda d: d['value'])[:count]
    return '; '.join(f"{d['label'].lower()} {d['value']} ({d['text']})" for d in ranked)


def apply(result: dict, domains: list[dict]) -> None:
    """Add `item_description` to every assessment and replace generic decision, wave and order text with specific text."""
    names = {a['domain_id']: a['domain_name'] for a in result['assessments']}
    by_domain = {d['id']: d for d in domains}
    findings_of = {a['domain_id']: [f for f in result['findings'] if f['domain_id'] == a['domain_id']] for a in result['assessments']}
    rows = result['domain_dependency_matrix'].get('rows', [])
    pair_count = {(r['source_domain_id'], r['target_domain_id']): r['edge_count'] for r in rows}
    wave_of = {d: w['number'] for w in result['waves'] for d in w['domains']}
    total_waves = len(result['waves'])
    decisions = {d['domain_id']: d for d in result['decisions']}
    for a in result['assessments']:
        did, name = a['domain_id'], a['domain_name']
        findings = findings_of[did]
        domain = by_domain[did]
        classes = domain['classes']
        packages = domain.get('packages') or sorted({c.rsplit('.', 1)[0] for c in classes})
        recommendation = (a.get('recommendations') or [{}])[0]
        key_classes = recommendation.get('affected_classes') or classes[:5]
        decision = decisions[did]
        decision['action'] = decision_action(decision['kind'], name, a, findings, rows, names)
        coverage = a['runtime_coverage']['classes']
        current = [f"{name} has {_n(len(classes), 'class', 'classes')} in {_n(len(packages), 'package')}: {_list(packages, 3)}.",
            f"Structural readiness is {a['structural_score']}/100. Lowest inputs: {_lowest_inputs(a.get('structural_details'))}." if a.get('structural_details') else f"Structural readiness is {a['structural_score']}/100.",
            f"Confidence is {a['confidence_score']}/100 from {_n(len(a.get('confidence_inputs') or {}), 'measured input')}; not measured: {_list(e['label'].lower() for e in a.get('confidence_not_measured', []))}.",
            (f"Runtime: {coverage['observed']} of {_n(coverage['total'], 'class', 'classes')} observed ({coverage['percentage']}%)." if coverage.get('percentage') is not None
             else 'Runtime: not measured, no runtime session is attached to this version.')]
        if recommendation.get('dependency_pairs'):
            current.append(f"{_n(len(recommendation['dependency_pairs']), 'observed class pair')} cross the boundary, for example {_short(recommendation['dependency_pairs'][0]['source'])} -> {_short(recommendation['dependency_pairs'][0]['target'])}.")
        selected = [f"Decision {decision['kind']} was chosen because: " + ' '.join(f['text'] for f in findings if f['kind'] not in ('BEHAVIOR_AND_DATA_UNKNOWN', 'UNREVIEWED_BOUNDARY'))[:700]
                    if any(f['kind'] not in ('BEHAVIOR_AND_DATA_UNKNOWN', 'UNREVIEWED_BOUNDARY') for f in findings) else
                    f"Decision {decision['kind']} was chosen because no cycle, shared data or coupling finding applies and the evidence is incomplete: " + ' '.join(f['text'] for f in findings)[:700]]
        blockers = [explain_blocker(code, name, findings) for code in a['blockers']]
        uses = sorted(((names[t], n, wave_of.get(t)) for (s, t), n in pair_count.items() if s == did), key=lambda x: (x[2] or 0, x[0]))
        used_by = sorted(((names[s], n, wave_of.get(s)) for (s, t), n in pair_count.items() if t == did), key=lambda x: (x[2] or 0, x[0]))
        wave = wave_of[did]
        order = [f"Wave {wave} of {total_waves}."]
        order.append(('Depends on ' + _list(f'{n} ({_n(c, "dependency edge")}, wave {w})' for n, c, w in uses) + '.') if uses else 'Depends on no other candidate domain.')
        if used_by:
            order.append('Used by ' + _list(f'{n} ({_n(c, "dependency edge")}, wave {w})' for n, c, w in used_by) + '.')
        inputs = a.get('cost_inputs') or {}
        formulas = [dict(name='Structural readiness', formula=a.get('structural_formula'), value=a['structural_score']),
            dict(name='Confidence', formula=a['confidence_note'], value=a['confidence_score']),
            dict(name='Combined and adjusted readiness', formula=a['readiness_formula'], value=a['confidence_adjusted_score'])]
        if inputs:
            formulas.append(dict(name='Heuristic cost index (orders the waves)', value=a.get('cost_index'),
                formula=f"classes {inputs.get('classes')} / 20 + 1.5 x {inputs.get('boundary_pairs')} crossing pairs + 8 x {inputs.get('shared_repositories')} shared repositories + 6 x {inputs.get('god_classes')} God-class candidates + 12 x {inputs.get('cross_domain_cycles')} cross-domain cycles"
                        + (f" + runtime gap {round(a['cost_index'] - sum([inputs.get('classes', 0) / 20, 1.5 * inputs.get('boundary_pairs', 0), 8 * inputs.get('shared_repositories', 0), 6 * inputs.get('god_classes', 0), 12 * inputs.get('cross_domain_cycles', 0)]), 1)}" if a.get('cost_index') is not None else '')))
        a['order_rationale'] = ' '.join(order)
        a['expected_impact'] = (f"Baseline to re-measure after a validated change: {inputs.get('boundary_pairs', 0)} crossing class pairs, {inputs.get('cross_domain_cycles', 0)} cross-domain cycle(s), "
                                f"{inputs.get('god_classes', 0)} God-class candidate(s), {inputs.get('shared_repositories', 0)} shared repositories. No improvement is claimed until it is measured.") if inputs else a.get('expected_impact')
        a['item_description'] = dict(domain_id=did, title=f"{name}: {_n(len(classes), 'class', 'classes')}, {_n(len(packages), 'package')}",
            target=dict(domain=name, class_count=len(classes), packages=packages[:8], key_classes=key_classes[:8]),
            current_state=current, selected_because=selected, blockers=blockers, order=order, formulas=formulas,
            text=' '.join(current + selected + order))
    for w in result['waves']:
        members = [a for a in result['assessments'] if a['domain_id'] in w['domains']]
        w['domain_order_reasons'] = {a['domain_id']: a['order_rationale'] for a in members}
        w['expected_impact'] = ' '.join(f"{a['domain_name']}: {a['expected_impact']}" for a in members)
