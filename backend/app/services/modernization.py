"""Transparent scores and dependency-aware extraction waves."""
import networkx as nx


def assess_and_rank(domains, membership, graph, cycles, issues, weights):
    assessments = []
    for domain in domains:
        metric, db = domain['metrics'], domain['database']
        member_count = domain['class_count']
        cyclic_members = {n for c in cycles if c['level'] == 'CLASS' for n in c['members'] if membership.get(n) == domain['id']}
        cross_cycles = [c['id'] for c in cycles if domain['id'] in c['impacted_domains'] and len(c['impacted_domains']) > 1]
        db_score = 25.0 if db['shared_repositories'] else 65.0 if db['status'] == 'STRUCTURAL_SIGNALS' else 45.0
        boundary_pairs = [(s,t) for s,t in graph.edges if membership.get(s)==domain['id'] and membership.get(t) != domain['id']]
        god_classes = sorted({i['entity_id'] for i in issues if i['issue_type']=='GOD_CLASS' and i['entity_id'] in domain['classes']})
        components = {'cohesion': 100 * metric['internal_cohesion'] if metric['internal_cohesion'] is not None else 50.0,
            'decoupling': 100 * (1 - metric['cross_domain_ratio']),
            'cycles': max(0., 100 * (1 - len(cyclic_members) / member_count) - (25 if cross_cycles else 0)),
            'database': db_score,
            'boundary_scale': max(0., 100 / (1 + len(boundary_pairs) / max(1, member_count ** .5))),
            'class_concentration': max(0., 100 - min(100, 15 * len(god_classes)))}
        extended_weights = {key: value * .8 for key,value in weights.items()}
        extended_weights.update(boundary_scale=.12, class_concentration=.08)
        readiness = round(sum(components[k] * extended_weights[k] for k in extended_weights), 1)
        risks = []
        if cross_cycles: risks.append('Participates in a cross-domain cyclic cluster.')
        if metric['cross_domain_ratio'] > .5: risks.append('Most outgoing application dependencies cross this boundary.')
        if db['shared_repositories']: risks.append('Repository consumers span multiple candidate domains.')
        risks.append('Runtime SQL and transaction boundaries require validation.')
        if db['status'] == 'UNKNOWN': risks.append('No database structural evidence found; absence does not prove independence.')
        if metric['internal_cohesion'] is None: risks.append('No outgoing dependency evidence to estimate cohesion.')
        confidence = 'LIMITED' if db['status'] == 'UNKNOWN' else 'STRUCTURAL_ONLY'
        boundary_count = sum(i['issue_type'] == 'DOMAIN_BOUNDARY_VIOLATION' and domain['id'] in i['domain_ids'] for i in issues)
        cost_index = round(member_count / 20 + len(boundary_pairs) * 1.5 + len(db['shared_repositories']) * 8 + len(god_classes) * 6 + len(cross_cycles) * 12, 1)
        effort = 'S' if cost_index <= 8 else 'M' if cost_index <= 18 else 'L' if cost_index <= 35 else 'XL'
        risk = 'HIGH' if cross_cycles or db['shared_repositories'] or len(boundary_pairs) >= 8 else 'MEDIUM' if boundary_pairs or god_classes else 'LOW'
        drivers = [f'{member_count} classes']
        if boundary_pairs: drivers.append(f'{len(boundary_pairs)} outgoing cross-domain class pairs')
        if db['shared_repositories']: drivers.append(f'{len(db["shared_repositories"])} shared repositories')
        if god_classes: drivers.append(f'{len(god_classes)} God-class candidate(s)')
        if cross_cycles: drivers.append(f'{len(cross_cycles)} cross-domain cycle(s)')
        assessments.append(dict(domain_id=domain['id'], domain_name=domain['name'], readiness_score=readiness,
            extraction_difficulty={'S':'LOW','M':'MEDIUM','L':'HIGH','XL':'VERY_HIGH'}[effort], effort_band=effort,
            risk_band=risk, risk_drivers=drivers, heuristic_cost_index=cost_index,
            component_scores={k: round(v, 2) for k,v in components.items()}, weights=extended_weights,
            formula='80% of configured cohesion/decoupling/cycle/data weights plus 12% boundary-edge scale and 8% class-concentration adjustment; heuristic, not calibrated.',
            internal_cohesion=metric['internal_cohesion'], external_coupling=metric['cross_domain_ratio'],
            incoming_pressure=metric['incoming_edges'], outgoing_pressure=metric['outgoing_edges'],
            boundary_violations=boundary_count, cycle_risk=len(cross_cycles), database_coupling=db['status'],
            confidence=confidence, risks=risks, blockers=cross_cycles,
            explanation=f"{domain['name']} scores {readiness}/100 from cohesion, decoupling, cycle participation and database signals.",
            unknown_database_score_range=[round(max(0, readiness - 50 * weights['database']), 1), round(min(100, readiness + 50 * weights['database']), 1)] if db['status'] == 'UNKNOWN' else None))
    domain_graph = nx.DiGraph()
    domain_graph.add_nodes_from(d['id'] for d in domains)
    domain_graph.add_edges_from((membership[s], membership[t]) for s,t in graph.edges if membership[s] != membership[t])
    condensation = nx.condensation(domain_graph)
    assessment_by_id = {a['domain_id']: a for a in assessments}
    remaining = set(condensation.nodes)
    ranked, wave = [], 1
    while remaining:
        ready_groups = [n for n in remaining if not (set(condensation.successors(n)) & remaining)]
        ready_groups.sort(key=lambda n: (-sum(assessment_by_id[d]['readiness_score'] for d in condensation.nodes[n]['members']) / len(condensation.nodes[n]['members']), sorted(condensation.nodes[n]['members'])))
        for group in ready_groups:
            members = sorted(condensation.nodes[group]['members'], key=lambda d: (-assessment_by_id[d]['readiness_score'], assessment_by_id[d]['domain_name']))
            for domain_id in members:
                assessment = assessment_by_id[domain_id]
                assessment.update(recommended_order=len(ranked) + 1, wave=wave, coupled_group=members if len(members)>1 else [],
                    sequence_reason='Dependency-first wave: prerequisites appear earlier. Within a wave, higher readiness comes first.' if len(members)==1 else 'Coupled group: remediate cycles together; row order is not an independent extraction plan.')
                ranked.append(assessment)
        remaining.difference_update(ready_groups)
        wave += 1
    return ranked
