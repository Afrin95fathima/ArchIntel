"""Deterministic, conservative comparison of two completed static analyses."""
from app.evidence.builder import digest

RULE_VERSION = 'architecture-diff-1'

IMPACT_METRIC_BY_DECISION = {
    'REDUCE_COUPLING_FIRST': 'CROSS_DOMAIN_DEPENDENCY_COUNT',
    'BREAK_CYCLE_FIRST': 'CLASS_CYCLE_COUNT',
    'PREPARE_FOR_EXTRACTION': 'CROSS_DOMAIN_DEPENDENCY_COUNT',
}


def compare(baseline, candidate):
    compatible = (bool(baseline.get('algorithm_version')) and 'configuration' in baseline and
                  baseline.get('algorithm_version') == candidate.get('algorithm_version') and
                  baseline.get('configuration') == candidate.get('configuration') and
                  {k:baseline.get('scanner', {}).get(k) for k in ('name','version')} ==
                  {k:candidate.get('scanner', {}).get(k) for k in ('name','version')})
    before_classes = {c['id'] for c in baseline.get('classes', [])}
    after_classes = {c['id'] for c in candidate.get('classes', [])}
    edge = lambda row: (row['source'], row['target'], row.get('dependency_type', 'UNKNOWN'))
    before_edges = {edge(e) for e in baseline.get('edges', [])}
    after_edges = {edge(e) for e in candidate.get('edges', [])}
    cycle = lambda row: (row.get('level'), tuple(sorted(row.get('members', []))))
    before_cycles = {cycle(c) for c in baseline.get('cycles', [])}
    after_cycles = {cycle(c) for c in candidate.get('cycles', [])}
    issue = lambda row: (row.get('issue_type', ''), row.get('entity_type', ''), row.get('entity_id', ''), row.get('severity', ''))
    before_issues = {issue(i) for i in baseline.get('issues', [])}
    after_issues = {issue(i) for i in candidate.get('issues', [])}
    domain_before = {c['id']: c.get('domain_id') for c in baseline.get('classes', [])}
    domain_after = {c['id']: c.get('domain_id') for c in candidate.get('classes', [])}
    common = before_classes & after_classes
    document = dict(rule_version=RULE_VERSION,
        eligibility='ELIGIBLE' if compatible else 'INCONCLUSIVE',
        reasons=[] if compatible else ['ALGORITHM_SCANNER_OR_CONFIGURATION_CHANGED_OR_MISSING'],
        inputs=dict(baseline_sha256=digest(baseline), candidate_sha256=digest(candidate),
                    algorithm_version=baseline.get('algorithm_version'),
                    candidate_algorithm_version=candidate.get('algorithm_version')),
        classes=dict(added=sorted(after_classes-before_classes), removed=sorted(before_classes-after_classes),
                     renames=[], rename_note='ArchitectureDiff infers no class rename without a reviewed entity correspondence.'),
        edges=dict(added=[list(x) for x in sorted(after_edges-before_edges)],
                   removed=[list(x) for x in sorted(before_edges-after_edges)]),
        cycles=dict(added=[list(x) for x in sorted(after_cycles-before_cycles)],
                    removed=[list(x) for x in sorted(before_cycles-after_cycles)]),
        issues=dict(added=[list(x) for x in sorted(after_issues-before_issues)],
                    removed=[list(x) for x in sorted(before_issues-after_issues)]),
        domain_membership_changes=[dict(class_id=name, before=domain_before[name], after=domain_after[name])
                                   for name in sorted(common) if domain_before[name] != domain_after[name]],
        summaries=dict(baseline=baseline.get('summary', {}), candidate=candidate.get('summary', {})),
        limitations=['A static delta (ArchitectureDiff) does not prove runtime behavior changed.',
                     'Domain IDs may change when community detection changes; membership deltas require architect review.',
                     'A Readiness-score improvement alone is not an approval condition.'])
    document['fingerprint'] = digest(document)
    return document


def expected_improvement(baseline, candidate, domain_id, decision_kind):
    """Measure the selected plan's structural objective without inferring intent."""
    metric = IMPACT_METRIC_BY_DECISION.get(decision_kind)
    before_classes = {c['id']: c for c in baseline.get('classes', [])}
    after_classes = {c['id']: c for c in candidate.get('classes', [])}
    target = {cid for cid, row in before_classes.items() if row.get('domain_id') == domain_id}
    reasons = []
    if not metric:
        reasons.append('DECISION_HAS_NO_SUPPORTED_STATIC_IMPROVEMENT_METRIC')
    if not target:
        reasons.append('TARGET_DOMAIN_HAS_NO_BASELINE_CLASS_INVENTORY')
    removed = sorted(set(before_classes) - set(after_classes))
    if removed:
        reasons.append('BASELINE_CLASS_INVENTORY_NOT_PRESERVED')

    def cross_boundary_edges(result):
        classes = {c['id'] for c in result.get('classes', [])}
        return len({(e['source'], e['target'], e.get('dependency_type', 'UNKNOWN'))
                    for e in result.get('edges', [])
                    if e.get('source') in classes and e.get('target') in classes and
                    ((e['source'] in target) != (e['target'] in target))})

    def class_cycles(result):
        return len({tuple(sorted(c.get('members', []))) for c in result.get('cycles', [])
                    if c.get('level') == 'CLASS' and set(c.get('members', [])) & target})

    counter = cross_boundary_edges if metric == 'CROSS_DOMAIN_DEPENDENCY_COUNT' else class_cycles
    before, after = (counter(baseline), counter(candidate)) if metric else (None, None)
    if metric and not reasons and after >= before:
        reasons.append('EXPECTED_STRUCTURAL_IMPROVEMENT_NOT_OBSERVED')
    failed = bool(removed) or bool(metric and target and before is not None and after is not None and after >= before)
    result = dict(rule_version='expected-impact-1', state=('PASS' if not reasons else 'FAIL' if failed else 'INCONCLUSIVE'),
        decision_kind=decision_kind, domain_id=domain_id, metric=metric, direction='DECREASE',
        baseline_value=before, candidate_value=after,
        improvement=(before - after) if before is not None and after is not None else None,
        reasons=sorted(set(reasons)), limitations=['A static structural change (ArchitectureDiff) does not prove runtime, business or data behavior improved.'])
    result['fingerprint'] = digest(result)
    return result
