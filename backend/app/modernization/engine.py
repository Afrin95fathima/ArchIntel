"""Deterministic, bounded planning over a frozen architecture version.

Scores are heuristic indices, never probabilities or authorization to execute.
Existing structural scoring is reused; reviewed memberships are recomputed.
"""
import copy
import re
from collections import defaultdict
import networkx as nx
from app.evidence.builder import identity
from app.services.domains import enrich_domains
from app.services.modernization import assess_and_rank
from app.services.runtime.entry_points import is_method_entry_point
from app.services.domain_analysis import dependency_matrix, model_overlap, entry_point_inventory
from app.insight import lifecycle as lifecycle_module, modernization_plan as technology_plan
from app.insight.model import InsightModel
from . import brief as brief_module, decomposition, describe, nonfunctional

RULE_VERSION = 'modernization-intelligence-4'
CALIBRATION = 'fixture-calibration-1'
STRATEGIES = ['MODULAR_MONOLITH', 'MICROSERVICES', 'HYBRID', 'CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE']
PREREQUISITES = ['PINNED_SOURCE_AND_PASSING_BUILD', 'BEHAVIORAL_CONTRACTS', 'DATA_OWNERSHIP_REVIEW', 'HUMAN_CHANGE_APPROVAL']
# Evidence confidence: share of each measured input, weighted by this policy and renormalized over the inputs that are measured.
CONFIDENCE_WEIGHTS = dict(static_support=.30, runtime_coverage=.30, review_status=.15, unresolved_references=.15, runtime_data_quality=.10)
CONFIDENCE_LABELS = dict(static_support='Static boundary evidence', runtime_coverage='Runtime class coverage', review_status='Domain review recorded',
    unresolved_references='Resolved dependency references', runtime_data_quality='Runtime data quality',
    behavioral_validation='Behavioral validation', data_ownership='Data ownership review')


def structural(version, static):
    """Keep historical scores exact unless the user reviewed domain membership."""
    if not version.manifest.get('domain_review'):
        return copy.deepcopy(static['modernization'])
    domains = copy.deepcopy(version.document['domains'])
    classes = {c['id']: c for c in static['classes']}
    membership = {c: d['id'] for d in domains for c in d['classes']}
    # Only classes that belong to a reviewed domain take part; nested and anonymous classes outside every domain have no membership to look up.
    graph = nx.DiGraph()
    graph.add_nodes_from(membership)
    graph.add_edges_from((e['source'], e['target']) for e in static['edges'] if e['source'] in membership and e['target'] in membership)
    for d in domains:
        d['class_count'] = len(d['classes'])
    enrich_domains(domains, membership, graph, classes, static.get('external_edges', []))
    cycles = copy.deepcopy([c for c in static.get('cycles', []) if c['level'] == 'CLASS'])
    for c in cycles:
        c['impacted_domains'] = sorted({membership[n] for n in c['members']})
    # Reviewed membership changes domains, so only class-level God-class findings are reused; domain-boundary violations are not recomputed here.
    god_classes = [i for i in static.get('issues', []) if i['issue_type'] == 'GOD_CLASS']
    return assess_and_rank(domains, membership, graph, cycles, god_classes, static['configuration']['readiness_weights'], boundary_available=False)


def method_name_pairs(pairs):
    """A version stores observed methods as (class, 'ReturnType name(params)'); the insight model matches (class, name)."""
    names = set()
    for owner, signature in pairs:
        found = re.match(r'[^ (]+\s+([^ (]+)\(', signature)
        names.add((owner, found.group(1) if found else signature.split('(')[0]))
    return sorted(names)


def analysis_context(version, static, domains, has_runtime):
    """One insight model for the plan, with the runtime classes of the captured sessions, and its lifecycle evaluation."""
    runtime = None
    if has_runtime:
        unobserved = {c for d in version.document['coverage']['domain_observations'] for c in d.get('unobserved_classes', [])}
        observed = sorted({c for d in domains for c in d['classes']} - unobserved)
        runtime = dict(runtime_graph=dict(nodes=[dict(id=c, static_id=c) for c in observed], edges=[]),
                       observed_methods=method_name_pairs(version.document.get('observed_methods', [])) if version.manifest.get('method_observations_available') else None)
    model = InsightModel('plan', static, runtime)
    return dict(model=model, lifecycle=lifecycle_module.evaluate(model, static.get('tech_inventory')) if model.facts_available else None)


def wave_reason(number, members, dependencies, names, candidates, coupled):
    """Why these domains form this wave: their named dependencies and the cost indexes of the groups that were ready."""
    text = f"Wave {number}: {', '.join(names[m] for m in members)}. "
    text += ('Depends on ' + ', '.join(names[d] for d in dependencies) + ' (earlier waves). ') if dependencies else 'Depends on no other candidate domain. '
    if coupled:
        text += 'Kept together as one dependency cycle: ' + '; '.join(' + '.join(names[d] for d in group) for group in coupled) + '. '
    ranked = sorted(candidates, key=lambda c: (c[1], c[0]))
    if len(ranked) > 1:
        text += f"Chosen first of {len(ranked)} dependency-ready groups for the lowest heuristic cost index: " + '; '.join(f"{' + '.join(g)} {round(c, 1)}" for g, c in ranked) + '.'
    else:
        text += 'It is the only dependency-ready group.'
    return text


def build(assessment_id, version, static, facts, evidence, options):
    uid = lambda key: identity(assessment_id, key)
    domains = sorted(version.document['domains'], key=lambda d: d['id'])
    names = {d['id']: d['name'] for d in domains}
    membership = {c: d['id'] for d in domains for c in d['classes']}
    domain_ids = {d['id'] for d in domains}
    nfr = nonfunctional.build(static, domains)       # non-functional findings, soft blockers and recommendations per domain
    structural_by = {a['domain_id']: a for a in structural(version, static)}
    all_graph, runtime_graph = nx.DiGraph(), nx.DiGraph()
    all_graph.add_nodes_from(sorted(domain_ids)); runtime_graph.add_nodes_from(sorted(domain_ids))
    by_domain = defaultdict(list)
    by_evidence = {e['id']: e for e in evidence}
    coverage = {d['id']: d for d in version.document['coverage']['domain_observations']}
    matrix = static.get('domain_dependency_matrix') or dependency_matrix(domains, {c['id']:c for c in static['classes']}, static['edges'], membership)
    ownership = static.get('data_ownership') or model_overlap(domains, {c['id']:c for c in static['classes']}, static['edges'], membership)
    entry_points = static.get('entry_points') or entry_point_inventory(domains, {c['id']:c for c in static['classes']}, membership)
    observed_method_pairs = {tuple(x) for x in version.document.get('observed_methods', [])}
    for entry in entry_points.get('items', []):
        pair = (entry['handler_class'], entry.get('handler_signature'))
        entry['observation_state'] = 'OBSERVED' if pair in observed_method_pairs else 'UNOBSERVED' if version.manifest.get('method_observations_available') else 'UNKNOWN'
    static_edges = static.get('edges', [])
    inbound_static = defaultdict(int)
    for edge in static_edges: inbound_static[edge['target']] += 1
    dead_candidates = []
    observed_method_owners = {owner for owner, _ in observed_method_pairs}
    if version.manifest.get('method_observations_available'):
        for cls in static.get('classes', []):
            if cls['id'] not in observed_method_owners and inbound_static[cls['id']] == 0:
                dead_candidates.append(dict(class_name=cls['id'],domain_id=membership.get(cls['id']),state='CANDIDATE_ONLY',
                    reason=f"{cls['id'].rsplit('.', 1)[-1]} has no inbound class-level static edge and no observed method owner in the selected sessions; that is not proof it is unused."))
    for f in facts:
        s, t = membership.get(f['source']), membership.get(f['target'])
        for d in sorted({s, t} - {None}):
            by_domain[d].append(f)
        if s and t and s != t:
            all_graph.add_edge(s, t)
            if f['classification'] != 'STATIC_ONLY': runtime_graph.add_edge(s, t)
    cyclic_groups = sorted([sorted(g) for g in nx.strongly_connected_components(all_graph) if len(g) > 1])
    cyclic = {d for g in cyclic_groups for d in g}
    runtime_cyclic = {d for g in nx.strongly_connected_components(runtime_graph) if len(g) > 1 for d in g}
    resources = defaultdict(set)
    resource_evidence = defaultdict(list)
    for e in evidence:
        o = e['observation']
        if e['kind'] == 'DATABASE' and all(o.get(k) for k in ('system', 'server', 'namespace', 'resource')):
            key = tuple(o[k] for k in ('system', 'server', 'namespace', 'resource'))
            d = membership.get(o.get('caller'))
            if d: resources[key].add(d); resource_evidence[key].append(e['id'])
    shared = defaultdict(list)
    for key, owners in resources.items():
        if len(owners) > 1:
            for d in owners: shared[d].extend(resource_evidence[key])
    findings, assessments, decisions = [], [], []
    has_runtime = bool(version.manifest['runtime_session_ids'])
    for domain in domains:
        did = domain['id']; baseline = structural_by[did]; fs = sorted(by_domain[did], key=lambda f: f['id'])
        fact_ids = [f['id'] for f in fs]
        support = sorted({e for f in fs for e in f['evidence_ids']} | {
            e['id'] for e in evidence if e['kind'] == 'COVERAGE' and e['target'] == did or e['kind'] == 'STATIC' and e['target'] in domain['classes']})
        local_findings = []
        def finding(kind, severity, text, fids=None, eids=None, measured=None, threshold=None, subjects=None, key=None, extra=None):
            # rule_id equals kind. measured/threshold/subjects are what "Explain why" shows: the value, the limit, and the named domains, classes or edges.
            row = dict(id=uid('finding:' + did + ':' + kind + (':' + key if key else '')), domain_id=did, kind=kind, rule_id=kind, severity=severity, text=text,
                       fact_ids=fact_ids if fids is None else fids, evidence_ids=support if eids is None else sorted(set(eids)), rule_version=RULE_VERSION,
                       measured=measured or {}, threshold=threshold or {}, subjects=list(subjects or []))
            row.update(extra or {})
            findings.append(row); local_findings.append(row['id'])
        conflicts = [f for f in fs if f.get('conflict_ids')]
        cross = [f for f in fs if membership.get(f['source']) == did and membership.get(f['target']) in domain_ids and membership[f['target']] != did]
        unresolved = [f for f in fs if f['source'] not in membership or f['target'] not in membership]
        if did in cyclic:
            group = next(g for g in cyclic_groups if did in g)
            finding('CROSS_DOMAIN_CYCLE', 'HIGH', f"{domain['name']} is in a dependency cycle with {len(group) - 1} other domain(s): {', '.join(names[g] for g in group)}.",
                measured={'domains_in_cycle': len(group)}, threshold={'minimum_domains_in_cycle': 2}, subjects=[names[g] for g in group])
        if baseline['external_coupling'] > .5:
            finding('HIGH_STRUCTURAL_COUPLING', 'HIGH', f"{round(100 * baseline['external_coupling'], 1)}% of {domain['name']}'s outgoing dependency pairs cross its boundary (limit 50%).",
                measured={'external_coupling': round(baseline['external_coupling'], 3), 'cross_boundary_class_pairs': len(cross)}, threshold={'maximum_external_coupling': .5},
                subjects=sorted({f['source'] for f in cross})[:10])
        shared_keys = sorted(key for key, owners in resources.items() if did in owners and len(owners) > 1)
        if shared[did]:
            finding('SHARED_PERSISTENCE_CANDIDATE', 'HIGH', f"{domain['name']} calls {len(shared_keys)} database resource(s) that other domains also call: {', '.join(k[3] for k in shared_keys[:5])}.", [], shared[did],
                measured={'shared_resources': len(shared_keys)}, threshold={'minimum_domains_per_resource': 2}, subjects=['/'.join(k) for k in shared_keys[:10]])
        if conflicts:
            finding('CONFLICTING_EVIDENCE', 'HIGH', f"{len(conflicts)} dependency fact(s) of {domain['name']} have conflicting evidence.", [f['id'] for f in conflicts],
                measured={'conflicting_facts': len(conflicts)}, threshold={'allowed_conflicting_facts': 0}, subjects=[f"{f['source']} -> {f['target']}" for f in conflicts[:10]])
        if unresolved:
            finding('UNRESOLVED_RUNTIME_BOUNDARY', 'MEDIUM', f"{len(unresolved)} observed dependency fact(s) of {domain['name']} reference a class with no domain.", [f['id'] for f in unresolved],
                measured={'unassigned_facts': len(unresolved)}, threshold={'allowed_unassigned_facts': 0},
                subjects=sorted({n for f in unresolved for n in (f['source'], f['target']) if n not in membership})[:10])
        observed = coverage[did]
        observation_score = round(100 * observed['observed'] / observed['total'], 2) if has_runtime and observed['total'] else 0
        if observation_score < 80:
            finding('LIMITED_OBSERVATION', 'MEDIUM',
                (f"Selected sessions observed {observed['observed']} of {observed['total']} classes of {domain['name']} ({observation_score}%, minimum 80%)." if has_runtime
                 else f"No runtime session is attached to this version, so none of the {observed['total']} classes of {domain['name']} was observed."), [],
                measured={'observed_classes': observed['observed'] if has_runtime else None, 'total_classes': observed['total'], 'observed_class_percentage': observation_score if has_runtime else None},
                threshold={'minimum_observed_class_percentage': 80}, subjects=[domain['name']])
        if not version.manifest.get('domain_review'):
            finding('UNREVIEWED_BOUNDARY', 'MEDIUM', f"The membership of {domain['name']} ({len(domain['classes'])} classes) has not been reviewed.", [],
                measured={'domain_review_recorded': False}, threshold={'domain_review_recorded': True}, subjects=[domain['name']])
        finding('BEHAVIOR_AND_DATA_UNKNOWN', 'MEDIUM', f"No behavioral contract tests or data-ownership review are recorded for {domain['name']}; extraction cannot be approved.", [],
            measured={'behavioral_contracts_recorded': False, 'data_ownership_reviewed': False}, threshold={'behavioral_contracts_recorded': True, 'data_ownership_reviewed': True}, subjects=[domain['name']])
        nfr_domain = nfr['by_domain'].get(did, dict(findings=[], blockers=[], recommendations=[], concerns=[], kind=None, implications=[]))
        for item in nfr_domain['findings']:
            # Support is the domain's captured static evidence, like every other finding; the specific bytecode evidence is referenced, not copied.
            finding(item['kind'], item['severity'], item['text'], [], None, item['measured'], item['threshold'], item['subjects'], key=item['risk_id'] or item['rule_id'],
                    extra=dict(responsibility_risk_id=item['risk_id'], responsibility_evidence_ids=item['evidence_ids'], detection=item['measured'].get('detection_status')))
        outgoing = [f for f in fs if membership.get(f['source']) == did and f['classification'] != 'STATIC_ONLY' and f['target'] in membership]
        total = sum(f['call_count'] for f in outgoing)
        internal = sum(f['call_count'] for f in outgoing if membership[f['target']] == did)
        # Runtime readiness is an observation-coverage measure. A handful of
        # runtime edges must not make an unexercised domain appear highly ready.
        method_coverage = version.document.get('coverage', {}).get('methods', {})
        methods_available = version.manifest.get('method_observations_available') is True
        observed_methods = {tuple(x) for x in version.document.get('observed_methods', [])}
        domain_classes = set(domain.get('classes', []))
        observed_domain_methods = sum(1 for c, _ in observed_methods if c in domain_classes)
        domain_method_signatures = {(c['id'], m['signature']) for c in static['classes'] if c['id'] in domain_classes
                                    for m in c.get('methods', []) if m.get('signature') and not (m.get('name') or '').startswith('<')}
        observed_domain_classes = min(observed.get('observed', 0), len(domain_classes))
        class_pct = round(100 * observed_domain_classes / len(domain_classes), 2) if has_runtime and domain_classes else None
        method_pct = round(100 * len(observed_methods & domain_method_signatures) / len(domain_method_signatures), 2) if methods_available and domain_method_signatures else None
        domain_entry_methods = [(c['id'], m.get('signature')) for c in static['classes'] if c['id'] in domain_classes
                                for m in c.get('methods', []) if m.get('signature') and is_method_entry_point(m)]
        observed_entry_count = sum(1 for pair in domain_entry_methods if pair in observed_methods)
        entry_pct = round(100 * observed_entry_count / len(domain_entry_methods), 2) if methods_available and domain_entry_methods else None
        runtime_parts = [('classes', class_pct, .4), ('methods', method_pct, .4), ('entry_points', entry_pct, .2)]
        available_parts = [(k, v, w) for k, v, w in runtime_parts if v is not None]
        runtime_components = {k: v for k, v, _ in available_parts}
        runtime_weights = {k: round(w / sum(x[2] for x in available_parts), 4) for k, _, w in available_parts} if available_parts else {}
        runtime_score = round(sum(runtime_components[k] * runtime_weights[k] for k in runtime_components), 1) if available_parts and observed_domain_methods > 0 else None
        combined = round(.6 * baseline['readiness_score'] + .4 * runtime_score, 1) if runtime_score is not None else baseline['readiness_score']
        # Quality is a conservative diagnostic index. It does not alter readiness.
        cov = version.document['coverage']
        diagnostics = version.document.get('quality', {})
        issue_keys = ('dropped_spans', 'conflicting_spans', 'invalid_parent_links', 'binding_rejected_spans')
        quality_issues = cov.get('missing_parent_count', 0) + cov.get('unresolved_node_count', 0) + sum(diagnostics.get(k, 0) for k in issue_keys)
        quality_penalty = min(100, 20 * quality_issues)
        unverified = bool(diagnostics.get('unverified_spans') or diagnostics.get('warnings'))
        if unverified: quality_penalty = max(quality_penalty, 25)
        if has_runtime and quality_penalty:
            finding('RUNTIME_QUALITY_LIMITATION', 'MEDIUM',
                f"Runtime capture has {quality_issues} counted quality issue(s)" + (" and unverified spans or warnings" if unverified else "") + f" ({cov.get('missing_parent_count', 0)} missing parents, {cov.get('unresolved_node_count', 0)} unresolved nodes, {sum(diagnostics.get(k, 0) for k in issue_keys)} dropped, conflicting or rejected spans).", [],
                measured={'quality_issue_count': quality_issues, 'missing_parent_count': cov.get('missing_parent_count', 0), 'unresolved_node_count': cov.get('unresolved_node_count', 0),
                          **{k: diagnostics.get(k, 0) for k in issue_keys}, 'unverified_spans_or_warnings': unverified},
                threshold={'allowed_quality_issues': 0}, subjects=[domain['name']])
        accepted_spans = diagnostics.get('accepted_spans')
        confidence_inputs, confidence_not_measured = {}, []
        def conf(key, value, numerator, denominator, text, raise_by=()):
            confidence_inputs[key] = dict(label=CONFIDENCE_LABELS[key], value=round(value, 1), numerator=numerator, denominator=denominator, text=text,
                                          weight=CONFIDENCE_WEIGHTS[key], how_to_raise=list(raise_by))
        def conf_skip(key, reason, measure_by=None):
            confidence_not_measured.append(dict(input=key, label=CONFIDENCE_LABELS[key], reason=reason, how_to_measure=measure_by))
        unobserved_names = [c.rsplit('.', 1)[-1] for c in observed.get('unobserved_classes', [])]
        unresolved_names = sorted({n.rsplit('.', 1)[-1] for f in unresolved for n in (f['source'], f['target']) if n not in membership})
        if domain.get('confidence') is not None:
            conf('static_support', float(domain['confidence']) * 100, None, None, f"clustering confidence {domain['confidence']} (stability, conductance and size of the candidate boundary)",
                 [f"Review the {len(domain['classes'])} classes of {domain['name']}; the value comes from " + '; '.join(domain.get('evidence', [])[:2]) + '.'])
        else:
            conf_skip('static_support', f"the domain record of {domain['name']} has no clustering confidence")
        if class_pct is not None:
            conf('runtime_coverage', class_pct, observed_domain_classes, len(domain_classes), f"{observed_domain_classes} of {len(domain_classes)} classes of {domain['name']} have a mapped span",
                 [f"Exercise code that reaches {', '.join(unobserved_names[:5])}." + (f" {len(unobserved_names) - 5} more are listed in Dynamic analysis." if len(unobserved_names) > 5 else '')] if unobserved_names else [])
        else:
            conf_skip('runtime_coverage', 'no runtime session is attached to this version' if not has_runtime else 'the domain has no classes',
                      'Attach a runtime session in Dynamic analysis, exercise the application, then capture a new architecture version.' if not has_runtime else None)
        conf('review_status', 100.0 if version.manifest.get('domain_review') else 0.0, None, None,
             'a domain review is recorded for this version' if version.manifest.get('domain_review') else 'no domain review is recorded for this version',
             [] if version.manifest.get('domain_review') else [f"Review the membership of {domain['name']} in Evidence & digital twin and save the review."])
        if fs:
            conf('unresolved_references', 100 * (1 - len(unresolved) / len(fs)), len(fs) - len(unresolved), len(fs), f"{len(fs) - len(unresolved)} of {len(fs)} dependency facts of {domain['name']} connect two classes that have a domain",
                 [f"Assign {', '.join(unresolved_names[:5])} to a domain."] if unresolved_names else [])
        else:
            conf_skip('unresolved_references', f"{domain['name']} has no dependency facts")
        if has_runtime and accepted_spans:
            conf('runtime_data_quality', 100 * (1 - min(1, (quality_issues + (1 if unverified else 0)) / accepted_spans)), accepted_spans - quality_issues, accepted_spans,
                 f"{quality_issues} counted quality issue(s)" + (" plus unverified spans or warnings" if unverified else "") + f" against {accepted_spans} accepted spans",
                 ([f"Resolve the {cov.get('missing_parent_count', 0)} missing parent span(s) and {diagnostics.get('dropped_spans', 0)} dropped span(s) in the runtime capture."] if quality_issues else []) + (['Provide the service name and artifact hash resource attributes so spans are verified.'] if unverified else []))
        else:
            conf_skip('runtime_data_quality', 'no runtime session is attached to this version' if not has_runtime else 'the accepted span count is not recorded in this version',
                      'Attach a runtime session and capture a new architecture version.' if not has_runtime else None)
        conf_skip('behavioral_validation', 'no behavioral contract tests are recorded for this version', 'Add reviewed behavioral contracts to a source task for this domain (Source tasks > Contracts).')
        conf_skip('data_ownership', 'no data-ownership review is recorded for this version', 'Review the shared repositories and entities of this domain with their owners and record the result.')
        confidence_components = {k: v['value'] for k, v in confidence_inputs.items()}
        weight_total = sum(CONFIDENCE_WEIGHTS[k] for k in confidence_components)
        confidence_weights = {k: round(CONFIDENCE_WEIGHTS[k] / weight_total, 6) for k in confidence_components}
        confidence = round(sum(confidence_components[k] * confidence_weights[k] for k in confidence_components), 1)
        blockers = list(PREREQUISITES)
        if observation_score < 80: blockers.append('RUNTIME_OBSERVATION_GAP')
        if not version.manifest.get('domain_review'): blockers.append('DOMAIN_REVIEW_REQUIRED')
        if unresolved: blockers.append('UNRESOLVED_MAPPING')
        if has_runtime and quality_penalty: blockers.append('RUNTIME_QUALITY_REVIEW')
        if conflicts: blockers.append('EVIDENCE_CONFLICT')
        if did in cyclic: blockers.append('CROSS_DOMAIN_CYCLE')
        if shared[did]: blockers.append('SHARED_PERSISTENCE_REVIEW')
        blockers += [b for b in nfr_domain['blockers'] if b not in blockers]   # soft: they ask for a decision, they do not block the label
        specialized = options['strategy'] in ('CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE')
        if specialized: blockers.append('COMPATIBILITY_INVENTORY_REQUIRED')
        if conflicts or specialized: decision = 'MANUAL_REVIEW_REQUIRED'
        elif did in cyclic: decision = 'BREAK_CYCLE_FIRST'
        elif shared[did]: decision = 'ISOLATE_DATA_FIRST'
        elif baseline['external_coupling'] > .5: decision = 'REDUCE_COUPLING_FIRST'
        elif not has_runtime or observation_score < 80 or unresolved or quality_penalty or not version.manifest.get('domain_review'): decision = 'COLLECT_MORE_EVIDENCE'
        elif options['strategy'] == 'MODULAR_MONOLITH': decision = 'RETAIN_MODULAR_MONOLITH'
        else: decision = 'PREPARE_FOR_EXTRACTION'
        readiness_score = round(combined * confidence / 100, 1)
        hard_blockers = sorted(set((['CROSS_DOMAIN_CYCLE'] if did in cyclic else []) + (['SHARED_PERSISTENCE_REVIEW'] if shared[did] else []) + (['EVIDENCE_CONFLICT'] if conflicts else [])))
        readiness_label = 'BLOCKED' if hard_blockers else 'READY_TO_PLAN' if confidence >= 60 and readiness_score >= 70 and not unresolved else 'NEEDS_EVIDENCE'
        runtime_gap_cost = round(max(0,100-observation_score)/25,1) if has_runtime else 0.0
        cost_index = round((baseline.get('heuristic_cost_index') or 0) + runtime_gap_cost,1)
        effort_band = 'S' if cost_index <= 8 else 'M' if cost_index <= 18 else 'L' if cost_index <= 35 else 'XL'
        risk_band = 'HIGH' if hard_blockers or (has_runtime and observation_score < 50) else baseline.get('risk_band','MEDIUM')
        cost_drivers = list(baseline.get('risk_drivers', [])) + ([f'{100-observation_score:.1f}% class observation gap adds {runtime_gap_cost:.1f} heuristic cost points'] if has_runtime else ['Runtime gap is not measured: no runtime session is attached, so it adds no cost points.'])
        seams = [f for f in fs if membership.get(f['source']) == did and membership.get(f['target']) in domain_ids and membership[f['target']] != did]
        seam_targets = sorted({membership[f['target']] for f in seams})
        seam_classes = sorted({name for f in seams for name in (f['source'],f['target'])})
        if seams:
            seam_summary = ', '.join(f"{membership[f['source']]}:{f['source']} -> {membership[f['target']]}:{f['target']}" for f in seams[:4])
            action_text = f"Review {len(seams)} observed cross-domain class pair(s) from {domain['name']}: {seam_summary}. Define a reviewed in-process API at this seam; exact contract is unknown until behavior and data ownership are confirmed."
            recommendation = dict(kind='REVIEW_DOMAIN_SEAM', text=action_text, affected_classes=seam_classes,
                dependency_pairs=[dict(source=f['source'],target=f['target'],classification=f['classification'],call_count=f['call_count']) for f in seams[:10]],
                proposed_interface='Candidate module API; method signatures and DTOs require source and behavior review.', target_domains=seam_targets,
                finding_ids=list(local_findings), missing_evidence=['source-level method signatures','behavioral contract','data ownership and transaction rules'])
        else:
            recommendation = dict(kind='COLLECT_DOMAIN_EVIDENCE', text=f"For {domain['name']}, exercise its annotated entry points and capture mapped method traces; the current evidence does not establish a cross-domain seam to change.",
                affected_classes=sorted(domain_classes), dependency_pairs=[], proposed_interface=None, target_domains=[],
                    finding_ids=list(local_findings), missing_evidence=['observed method coverage','confirmed business boundary'])
        assessments.append(dict(domain_id=did, domain_name=domain['name'], structural_score=baseline['readiness_score'],
            structural_components=baseline['component_scores'], structural_weights=baseline['weights'], structural_details=baseline.get('component_details'),
            structural_not_measured=baseline.get('not_measured', []), structural_formula=baseline.get('formula'), structural_source='RECOMPUTED_REVIEWED_DOMAINS' if version.manifest.get('domain_review') else 'PRESERVED_BASELINE',
            runtime_score=runtime_score, runtime_components=runtime_components, runtime_weights=runtime_weights, combined_score=combined,
            readiness_formula='Combined readiness = 0.6 × structural + 0.4 × runtime when runtime is measured, otherwise the structural score. Confidence-adjusted readiness = combined readiness × evidence confidence / 100.',
            confidence_adjusted_score=readiness_score, readiness_score=readiness_score, readiness_label=readiness_label, hard_blockers=hard_blockers,
            runtime_coverage=dict(classes=dict(observed=observed_domain_classes,total=len(domain_classes),percentage=class_pct),
                                  methods=dict(observed=observed_domain_methods,total=method_coverage.get('total') if methods_available else None,percentage=method_pct),
                                  entry_points=dict(observed=observed_entry_count,total=len(domain_entry_methods) if methods_available else None,percentage=entry_pct)),
            confidence_score=confidence, confidence_components=confidence_components, confidence_weights=confidence_weights,
            confidence_inputs=confidence_inputs, confidence_not_measured=confidence_not_measured,
            confidence_label='LIMITED' if confidence < 50 else 'PARTIAL',
            confidence_note=f"Confidence {confidence}/100 for {domain['name']} = sum(input x weight) over {len(confidence_inputs)} measured input(s): " + '; '.join(f"{v['label'].lower()} {v['value']} ({v['text']})" for v in confidence_inputs.values())
                + ". Not measured, so excluded: " + '; '.join(f"{e['label'].lower()} ({e['reason']})" for e in confidence_not_measured) + '. Confidence = sum(input × weight) as defined in the glossary, not a calibrated probability.',
            observation=observed, evidence_ids=support, fact_ids=fact_ids, blockers=blockers,
            recommendations=[recommendation] + nfr_domain['recommendations'], nonfunctional=dict(capability_kind=nfr_domain['kind'], concerns=nfr_domain['concerns'], implications=nfr_domain['implications']), effort_band=effort_band, risk_band=risk_band,
            cost_index=cost_index, cost_drivers=cost_drivers, cost_inputs=baseline.get('cost_inputs'), cost_formula=baseline.get('cost_formula'),
            difficulty='HIGH' if did in cyclic or shared[did] or combined < 60 else 'MEDIUM',
            order_rationale=f"Review after its {len([1 for s,t in all_graph.edges if s==did])} downstream dependency domain(s) and before its {len([1 for s,t in all_graph.edges if t==did])} dependent consumer(s); prioritize the observed {len(seams)} cross-domain class pair(s) and {len(shared[did])} shared-data signal(s).",
            expected_impact='Proposed reduction in boundary risk; no measured improvement until a validated before/after change.'))
        decisions.append(dict(id=uid('decision:' + did), domain_id=did, kind=decision, finding_ids=local_findings, evidence_ids=support,
            fact_ids=fact_ids, action=decision, blockers=blockers, prerequisites=list(PREREQUISITES), status='PROPOSAL', execution_allowed=False))
    condensation = nx.condensation(all_graph)
    remaining = set(condensation.nodes); waves = []; wave_by_domain = {}; wave_no = 1
    while remaining:
        eligible = [n for n in remaining if not (set(condensation.successors(n)) & remaining)]
        # Emit one dependency-ready SCC per wave, ordered by measured heuristic
        # cost. This makes cost differences visible while keeping cycles joint.
        eligible.sort(key=lambda n:(sum(next(a for a in assessments if a['domain_id']==d).get('cost_index') or 0 for d in condensation.nodes[n]['members']), sorted(condensation.nodes[n]['members'])))
        ready = [eligible[0]] if eligible else []
        members = sorted(d for n in ready for d in condensation.nodes[n]['members'])
        for d in members: wave_by_domain[d] = wave_no
        deps = sorted({t for s, t in all_graph.edges if s in members and t not in members})
        selected = [a for a in assessments if a['domain_id'] in members]
        waves.append(dict(id=uid('wave:' + str(wave_no)), number=wave_no, domains=members, dependencies=deps,
            coupled_groups=[sorted(condensation.nodes[n]['members']) for n in ready if len(condensation.nodes[n]['members']) > 1],
            reason=wave_reason(wave_no, members, deps, names, [(sorted(names[d] for d in condensation.nodes[n]['members']), sum(next(a for a in assessments if a['domain_id']==d).get('cost_index') or 0 for d in condensation.nodes[n]['members'])) for n in eligible],
                               [sorted(condensation.nodes[n]['members']) for n in ready if len(condensation.nodes[n]['members']) > 1]),
            readiness={a['domain_id']: a['combined_score'] for a in selected}, confidence={a['domain_id']: a['confidence_score'] for a in selected},
            difficulty='HIGH' if any(a['difficulty'] == 'HIGH' for a in selected) else 'MEDIUM',
            blockers=sorted({b for a in selected for b in a['blockers']}), prerequisites=list(PREREQUISITES),
            entry_criteria=['Source snapshot pinned','Behavioral contract tests identified','Data ownership reviewed'],
            exit_criteria=['Domain-specific blockers resolved','Boundary tests pass','Before/after metrics captured'],
            domain_order_reasons={a['domain_id']:a['order_rationale'] for a in selected},
            expected_impact='Hypothesis: clearer module boundaries. Measure only after validated changes.', execution_allowed=False))
        remaining.difference_update(ready); wave_no += 1
    target = dict(strategy=options['strategy'], objective=options['objective'], status='PROPOSED',
        components=[dict(domain_id=d['id'], name=d['name'], classes=d['classes'], deployment='IN_PROCESS' if options['strategy'] == 'MODULAR_MONOLITH' else 'UNDECIDED_REVIEW_REQUIRED') for d in domains],
        interfaces=[dict(source=s, target=t, contract='UNSPECIFIED', transport='LOCAL_MODULE' if options['strategy'] == 'MODULAR_MONOLITH' else 'UNDECIDED') for s, t in sorted(all_graph.edges)],
        alternatives=[],
        note=f"This proposal covers {len(domains)} domains; approving it does not authorize code changes or deployment, and it names no business capability or service contract.")
    finding_ids_by_kind = defaultdict(list)
    for row in findings:
        finding_ids_by_kind[row['kind']].append(row['id'])
    risks = []
    for kind in ('CROSS_DOMAIN_CYCLE', 'HIGH_STRUCTURAL_COUPLING', 'SHARED_PERSISTENCE_CANDIDATE', 'LIMITED_OBSERVATION', 'CONFLICTING_EVIDENCE'):
        refs = sorted(finding_ids_by_kind[kind])
        if refs:
            affected = sorted({names[f['domain_id']] for f in findings if f['kind'] == kind})
            risks.append(dict(message=f"{kind} affects {len(affected)} of {len(domains)} domains: {', '.join(affected)}.", finding_ids=refs))
    common_unknowns = [
        f"No behavioral contract tests are recorded for the {len(domains)} domains.",
        f"Data ownership and transactions of the {len(domains)} domains are not reviewed.",
        'No operational constraint, deployment requirement or cost target was supplied for this version.',
    ]
    strategy_rows = []
    boundary_gaps = sorted(set(finding_ids_by_kind['CROSS_DOMAIN_CYCLE'] + finding_ids_by_kind['HIGH_STRUCTURAL_COUPLING'] + finding_ids_by_kind['SHARED_PERSISTENCE_CANDIDATE']))
    for candidate in STRATEGIES:
        if candidate in ('CLOUD_REFACTOR', 'JAVA_UPGRADE', 'FRAMEWORK_UPGRADE'):
            inventory = static.get('tech_inventory') or {}
            has_inventory = inventory.get('status') not in (None, 'UNAVAILABLE')
            status = 'INVENTORY_AVAILABLE_REVIEW_REQUIRED' if has_inventory else 'INSUFFICIENT_EVIDENCE'
            if candidate == 'JAVA_UPGRADE':
                observed_targets = inventory.get('bytecode', {}).get('java_targets', [])
                reason = f"Bytecode inventory found Java target(s) {', '.join(map(str, observed_targets)) or 'unknown'}; upgrade compatibility and target-version choice still need review." if has_inventory else 'Java bytecode inventory is unavailable.'
            elif candidate == 'FRAMEWORK_UPGRADE':
                frameworks = inventory.get('frameworks', [])
                reason = f"Framework inventory found {', '.join(x.get('name')+' '+','.join(x.get('versions',[])) for x in frameworks) or 'partial framework metadata'}; compatibility and target version still need review." if has_inventory else 'Framework inventory is unavailable.'
            else:
                reason = 'The architecture inventory is available, but no target cloud platform, deployment constraint or cost objective was supplied for this version.'
            compat = inventory.get('compatibility', {})
            lifecycle_state = (f"Lifecycle rules: Java {compat.get('java_lifecycle')}, frameworks {compat.get('framework_lifecycle')} (see Technology lifecycle)."
                if compat.get('java_lifecycle') not in (None, 'NOT_CHECKED') else 'Lifecycle status is not available for this analysis; run a new analysis to evaluate lifecycle rules.')
            unknowns = [lifecycle_state, 'Vulnerability advisories are out of scope for lifecycle-rules.yaml.', 'The target Java version, platform and dependency compatibility need an authoritative review.']
            refs = []
        elif candidate == 'MODULAR_MONOLITH':
            status = 'CONDITIONAL' if boundary_gaps else 'EVIDENCE_SUPPORTS_REVIEW'
            reason = f"In-process boundaries keep one deployment unit for the {len(domains)} domains; validate module contracts and the {len(boundary_gaps)} boundary findings first."
            unknowns = common_unknowns[:2]
            refs = boundary_gaps
        else:
            status = 'CONDITIONAL'
            reason = f"Service separation of the {len(domains)} domains needs independently owned data, verified behavior and operational evidence; none is recorded in this capture."
            unknowns = common_unknowns
            refs = sorted(set(boundary_gaps + finding_ids_by_kind['BEHAVIOR_AND_DATA_UNKNOWN'] + finding_ids_by_kind['SHARED_PERSISTENCE_CANDIDATE']))
        strategy_rows.append(dict(strategy=candidate, status=status, rationale=reason, finding_ids=refs, unknowns=unknowns,
                                  selected_by_user=(candidate == options['strategy'])))
    target['alternatives'] = [dict(strategy=row['strategy'], status=row['status'], reason=row['rationale'], finding_ids=row['finding_ids'], unknowns=row['unknowns'])
                              for row in strategy_rows if row['strategy'] != options['strategy']]
    class_count = len(static.get('classes', []))
    planned_class_count = sum(len(component.get('classes', [])) for component in target.get('components', []))
    modernization_progress = dict(
        percentage=round(100 * planned_class_count / class_count, 1) if class_count else 0,
        planned_classes=planned_class_count,
        total_classes=class_count,
        basis=f'{planned_class_count} classes assigned to target components in this proposal, divided by {class_count} analyzed classes.',
        state='PLAN_COVERAGE',
    )
    boundary_edge_count = sum(row['edge_count'] for row in matrix.get('rows', []))
    average_cross_ratio = round(sum(a['external_coupling'] for a in structural_by.values()) / max(1, len(structural_by)), 3)
    baseline_metrics = dict(cycle_count=len(static.get('cycles', [])), god_class_count=sum(i.get('issue_type') == 'GOD_CLASS' for i in static.get('issues', [])),
        cross_domain_edge_count=boundary_edge_count, shared_entity_count=len(ownership.get('duplicated_models', [])),
        average_cross_domain_coupling=average_cross_ratio, class_count=class_count)
    proposed_targets = dict(cross_domain_edge_count=dict(baseline=boundary_edge_count,target=max(0, int(boundary_edge_count * .8)),basis='Proposed 20% reduction; planning target, not forecast.'),
        cycle_count=dict(baseline=baseline_metrics['cycle_count'],target=0,basis=f"Proposed target: no cycle remains (baseline {baseline_metrics['cycle_count']})."),
        god_class_count=dict(baseline=baseline_metrics['god_class_count'],target=0 if baseline_metrics['god_class_count'] else 0,basis='Proposed target; candidate findings require review.'),
        average_cross_domain_coupling=dict(baseline=average_cross_ratio,target=round(average_cross_ratio * .8,3),basis='Proposed 20% reduction; planning target, not forecast.'))
    strategy_fit = dict(recommendation='MODULAR_MONOLITH_FIRST' if class_count <= 250 and (ownership.get('shared_repositories') or ownership.get('duplicated_models') or not version.manifest.get('domain_review')) else 'REVIEW_BOUNDARIES',
        rationale=f"The scanned artifact has {class_count} classes and {boundary_edge_count} cross-domain class edges; data ownership is unconfirmed. Prefer validating in-process module boundaries before adding distributed-service operations.",
        metrics=baseline_metrics, confidence='HEURISTIC_REVIEW_REQUIRED')
    top_risks = [r['message'] for r in risks[:3]]
    result_brief = dict(
        headline=f"Planning proposal for {len(domains)} domains; {options['strategy']} was requested and no strategy was selected automatically.",
        strategy_fit=strategy_fit, top_actions=[a['recommendations'][0]['text'] for a in sorted(assessments,key=lambda x:(x.get('cost_index') or 0,x['domain_id']))[:3]],
        effort_range='Heuristic bands: ' + ', '.join(sorted({a['effort_band'] for a in assessments})),
        overall_confidence='LIMITED' if max((a['confidence_score'] for a in assessments),default=0)<50 else 'PARTIAL',
        top_risks=top_risks, baseline_metrics=baseline_metrics, proposed_targets=proposed_targets,
        selected_strategy=options['strategy'], selection_source='USER_INPUT', objective=options['objective'],
        summary=f"The captured version contains {len(domains)} candidate domains, {len(facts)} architecture facts and {len(evidence)} evidence records. The requested strategy is a proposal for review.",
        evidence_scope=dict(architecture_version_id=version.id, domain_count=len(domains), fact_count=len(facts), evidence_count=len(evidence), runtime_sessions=len(version.manifest['runtime_session_ids'])),
        material_risks=risks, strategy_comparison=strategy_rows,
        unresolved_questions=[],      # filled from the brief's questions and unmeasured inputs by brief.merge
        next_step='Review cited findings, confirm business and data rules, and capture representative runtime workflows before approving any implementation plan.',
        automatic_winner=None)
    result = dict(id=assessment_id, version_id=version.id, version_fingerprint=version.fingerprint, rule_version=RULE_VERSION, calibration_version=CALIBRATION,
        options=options, assessments=assessments, findings=findings, decisions=decisions, target=target, waves=waves, decision_brief=result_brief,
        modernization_progress=modernization_progress,
        dependency_edges=[dict(source=s, target=t) for s, t in sorted(all_graph.edges)],
        domain_dependency_matrix=matrix, data_ownership=ownership, entry_points=entry_points, nonfunctional=nfr['document'],
        dead_code_candidates=dead_candidates,
        data_quality=dict(artifact_state='AVAILABLE' if version.manifest.get('artifact_sha256') else 'UNAVAILABLE',
            artifact_impact=f'Static and modernization conclusions for {class_count} classes may be incomplete.' if not version.manifest.get('artifact_sha256') else f"Artifact hash {version.manifest['artifact_sha256'][:12]} is recorded in the version manifest.",
            artifact_remediation='Re-upload the source or compiled artifact and run static analysis.' if not version.manifest.get('artifact_sha256') else None,
            graph_projection_state=version.manifest.get('projection_state','NOT_CAPTURED'),
            method_mapping_state='AVAILABLE' if version.manifest.get('method_observations_available') else 'UNAVAILABLE',
            method_mapping_impact='Method and entry-point runtime scores are not measured for this version; class-level observation is not method coverage.' if not version.manifest.get('method_observations_available') else None,
            method_mapping_remediation='Retain raw span events and configure method mapping before capturing a new architecture version.' if not version.manifest.get('method_observations_available') else None),
        limitations=[f'Scores follow the formulas of rule version {RULE_VERSION} and calibration {CALIBRATION}; they are not calibrated against migration outcomes.',
            f"Runtime figures cover {len(version.manifest['runtime_session_ids'])} selected session(s) only; an unobserved class is not an unused class.",
            f'Data ownership, behavioral equivalence and extraction approval are not recorded for the {len(domains)} domains.',
            'Cloud, Java and framework strategies are review proposals; the technology plan checks only the Java level, namespace and dependency conflicts of its curated candidates.'])
    describe.apply(result, domains)
    shared = analysis_context(version, static, domains, bool(version.manifest['runtime_session_ids']))
    result['technology_plan'] = technology_plan.build(shared['model'], shared['lifecycle']) if shared['lifecycle'] is not None else dict(status='NOT_AVAILABLE', reason='This analysis has no bytecode facts, so aging technology cannot be assessed; run a new analysis.')
    brief_module.merge(result['decision_brief'], brief_module.build(result, static, domains, options, by_evidence, shared), result)
    result['microservice_decomposition'] = decomposition.build(static, result)
    result['graph'] = planning_graph(assessment_id, result, facts, by_evidence)
    return result


def planning_graph(aid, document, facts, evidence):
    """Separate assessment scope: never mutate the captured evidence graph."""
    nodes = {}; edges = {}
    def node(key, kind, name, **properties):
        nid = identity(aid, 'graph:' + key)
        nodes[nid] = dict(id=nid, kind=kind, name=name, **properties)
        return nid
    def link(s, t, kind):
        eid = identity(aid, 'graph-link:' + s + ':' + kind + ':' + t)
        edges[eid] = dict(id=eid, source=s, target=t, kind=kind)
    root = node('assessment', 'ModernizationAssessment', RULE_VERSION)
    version = node('version', 'ArchitectureVersionReference', document['version_id'], canonical_id=document['version_id'])
    link(root, version, 'ASSESSES')
    target = node('target', 'TargetArchitecture', document['target']['strategy']); link(root, target, 'PROPOSES')
    for a in document['assessments']:
        node('domain:' + a['domain_id'], 'DomainAssessment', a['domain_name'], readiness=a['combined_score'], confidence=a['confidence_score'])
    nf = document.get('nonfunctional') or {}
    capability_nodes = {}
    for c in nf.get('capabilities', []):
        capability = capability_nodes[c['name']] = node('capability:' + c['domain_id'], 'BusinessCapability', c['name'], capability_kind=c['kind'])
        link(capability, identity(aid, 'graph:domain:' + c['domain_id']), 'ASSOCIATED_WITH')
        for concern in c['nonfunctional_concerns']:
            link(capability, node('nfr-concern:' + concern['category'], 'NonFunctionalConcern', concern['category']), 'HAS_CONCERN')
    for item in nf.get('cross_cutting', []):
        shared_node = node('shared:' + item['id'], 'SharedComponent', item['name'], component_kind=item['kind'], deployment_form=item['deployment_form'])
        for name in item['capabilities']:
            if name in capability_nodes:
                link(capability_nodes[name], shared_node, 'DEPENDS_ON')
    for r in nf.get('risks', []):
        risk_node = node('nfr-risk:' + r['id'], 'NonFunctionalRisk', r['rule_id'], category=r['category'], severity=r['severity'], detection_status=r['detection_status'], canonical_id=r['id'])
        link(risk_node, node('nfr-concern:' + r['category'], 'NonFunctionalConcern', r['category']), 'CONCERNS')
        for d in r['domains']:
            link(risk_node, identity(aid, 'graph:domain:' + d['id']), 'AFFECTS')
    for f in facts:
        fid = node('fact:' + f['id'], 'ArchitectureFactReference', f['source'] + ' -> ' + f['target'], canonical_id=f['id'])
        for eid in f['evidence_ids']:
            if eid in evidence: link(node('evidence:' + eid, 'EvidenceReference', evidence[eid]['kind'], canonical_id=eid), fid, 'SUPPORTS')
    for f in document['findings']:
        fid = node('finding:' + f['id'], 'ModernizationFinding', f['kind'], canonical_id=f['id'])
        for eid in f['evidence_ids']:
            if eid in evidence: link(node('evidence:' + eid, 'EvidenceReference', evidence[eid]['kind'], canonical_id=eid), fid, 'SUPPORTS')
        for fact in f['fact_ids']: link(identity(aid, 'graph:fact:' + fact), fid, 'SUPPORTS')
    for d in document['decisions']:
        did = node('decision:' + d['id'], 'ModernizationDecision', d['kind'], canonical_id=d['id'])
        link(root, did, 'CONTAINS'); link(did, identity(aid, 'graph:domain:' + d['domain_id']), 'TARGETS')
        for f in d['finding_ids']: link(identity(aid, 'graph:finding:' + f), did, 'SUPPORTS')
        for p in d['prerequisites']: link(did, node('prerequisite:' + p, 'Prerequisite', p), 'REQUIRES')
        for b in d['blockers']: link(did, node('blocker:' + b, 'Blocker', b), 'BLOCKED_BY')
    previous = None
    for w in document['waves']:
        wid = node('wave:' + w['id'], 'ModernizationWave', 'Wave ' + str(w['number']))
        link(root, wid, 'CONTAINS')
        if previous: link(previous, wid, 'PRECEDES')
        for d in w['domains']: link(wid, identity(aid, 'graph:domain:' + d), 'CONTAINS')
        previous = wid
    return dict(nodes=sorted(nodes.values(), key=lambda n: n['id']), edges=sorted(edges.values(), key=lambda e: e['id']))
