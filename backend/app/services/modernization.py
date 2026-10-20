"""Transparent scores and dependency-aware extraction waves."""
import networkx as nx


# Weight policy: the configured weights (cohesion, decoupling, cycles, database) share CONFIGURED_SHARE of the score;
# boundary scale and class concentration take the rest. Inputs that cannot be measured are excluded and the
# remaining weights are renormalized to sum to 1; nothing is replaced by a default value.
CONFIGURED_SHARE = .8
EXTRA_WEIGHTS = {'boundary_scale': .12, 'class_concentration': .08}
LABELS = {'cohesion': 'Cohesion', 'decoupling': 'Decoupling', 'cycles': 'Cycle freedom', 'database': 'Data independence',
          'boundary_scale': 'Boundary size', 'class_concentration': 'Class concentration'}


def _top(counter, limit=3):
    return ', '.join(f'{name} ({count})' for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])


def assess_and_rank(domains, membership, graph, cycles, issues, weights, boundary_available=True, god_class_available=True):
    """`issues` supplies GOD_CLASS and DOMAIN_BOUNDARY_VIOLATION rows. Pass god_class_available=False when it holds neither."""
    names = {d['id']: d['name'] for d in domains}
    assessments = []
    for domain in domains:
        metric, db = domain['metrics'], domain['database']
        member_count = domain['class_count']
        edge_total = metric['internal_edges'] + metric['outgoing_edges']
        cyclic_members = {n for c in cycles if c['level'] == 'CLASS' for n in c['members'] if membership.get(n) == domain['id']}
        cross_cycles = [c['id'] for c in cycles if domain['id'] in c['impacted_domains'] and len(c['impacted_domains']) > 1]
        boundary_pairs = [(s,t) for s,t in graph.edges if membership.get(s)==domain['id'] and membership.get(t) != domain['id']]
        by_source = {}
        for s, t in boundary_pairs:
            by_source[s.rsplit('.', 1)[-1]] = by_source.get(s.rsplit('.', 1)[-1], 0) + 1
        god_classes = sorted({i['entity_id'] for i in issues if i['issue_type']=='GOD_CLASS' and i['entity_id'] in domain['classes']})
        repositories, shared = db['repositories'], db['shared_repositories']
        components, details, not_measured = {}, {}, []

        def measure(key, value, numerator, denominator, text, raise_by):
            components[key] = value
            details[key] = dict(label=LABELS[key], value=round(value, 2), numerator=numerator, denominator=denominator, text=text, how_to_raise=raise_by)

        def skip(key, reason):
            not_measured.append(dict(input=key, label=LABELS[key], reason=reason))

        if edge_total:
            measure('cohesion', 100 * metric['internal_cohesion'], metric['internal_edges'], edge_total,
                f"{metric['internal_edges']} of {edge_total} dependency edges leaving the domain's classes stay inside it",
                [f"Pull the {metric['outgoing_edges']} outgoing dependencies inside the boundary or remove them, starting with {_top(by_source)}."] if metric['outgoing_edges'] else [])
            measure('decoupling', 100 * (1 - metric['cross_domain_ratio']), metric['outgoing_edges'], edge_total,
                f"{metric['outgoing_edges']} of {edge_total} dependency edges leave the domain ({round(100 * metric['cross_domain_ratio'], 1)}%)",
                [f"Introduce an interface for the {metric['outgoing_edges']} outgoing dependencies, starting with {_top(by_source)}."] if metric['outgoing_edges'] else [])
        else:
            skip('cohesion', f"{domain['name']} has no dependency edges, so the internal share has no denominator")
            skip('decoupling', f"{domain['name']} has no dependency edges, so the outgoing share has no denominator")
        cycle_value = max(0., 100 * (1 - len(cyclic_members) / member_count) - (25 if cross_cycles else 0))
        measure('cycles', cycle_value, len(cyclic_members), member_count,
            f"{len(cyclic_members)} of {member_count} classes are in dependency cycles" + (f"; {len(cross_cycles)} cycle(s) span other domains (-25)" if cross_cycles else ''),
            ([f"Break the cycle through {', '.join(sorted(m.rsplit('.', 1)[-1] for m in cyclic_members)[:5])}."] if cyclic_members else []) + ([f"Resolve cross-domain cycle(s) {', '.join(cross_cycles[:3])} together with the other domains."] if cross_cycles else []))
        if repositories:
            sharedn = sorted(r['repository'].rsplit('.', 1)[-1] + ' with ' + ', '.join(names.get(x, x) for x in r['domains'] if x != domain['id']) for r in shared)
            measure('database', 100 * (1 - len(shared) / len(repositories)), len(shared), len(repositories),
                f"{len(shared)} of {len(repositories)} repositories used by the domain are also used by another domain",
                [f"Give one domain ownership of {s}." for s in sharedn[:3]])
        else:
            skip('database', f"no repository class or data-access reference was found in {domain['name']}; absence does not prove independence")
        pairs_scale = 100 / (1 + len(boundary_pairs) / max(1, member_count ** .5))
        measure('boundary_scale', max(0., pairs_scale), len(boundary_pairs), member_count,
            f"{len(boundary_pairs)} class pairs cross the boundary for {member_count} classes (100 / (1 + pairs / max(1, √classes)))",
            [f"Reduce crossing pairs, starting with {_top(by_source)}."] if boundary_pairs else [])
        if god_class_available:
            measure('class_concentration', max(0., 100 - min(100, 15 * len(god_classes))), len(god_classes), member_count,
                f"{len(god_classes)} God-class candidate(s) among {member_count} classes (100 - 15 per candidate)",
                [f"Split {', '.join(g.rsplit('.', 1)[-1] for g in god_classes[:5])}."] if god_classes else [])
        else:
            skip('class_concentration', 'God-class findings are not measured for this view')
        configured = {key: value * CONFIGURED_SHARE for key, value in weights.items()}
        configured.update(EXTRA_WEIGHTS)
        total_weight = sum(configured[k] for k in components)
        effective = {k: configured[k] / total_weight for k in components}
        readiness = round(sum(components[k] * effective[k] for k in components), 1)
        for key, item in details.items():
            item['weight'] = round(effective[key], 4)
        for entry in not_measured:
            entry['configured_weight'] = round(configured[entry['input']], 4)
        risks = []
        if cross_cycles: risks.append(f"Participates in {len(cross_cycles)} cross-domain cycle(s): {', '.join(cross_cycles[:3])}.")
        if metric['cross_domain_ratio'] > .5: risks.append(f"{metric['outgoing_edges']} of {edge_total} dependency edges cross this boundary.")
        if shared: risks.append(f"{len(shared)} repositories are used by other domains too: {', '.join(r['repository'].rsplit('.', 1)[-1] for r in shared[:3])}.")
        if repositories: risks.append(f"Runtime SQL and transactions of {len(repositories)} repositories ({', '.join(r.rsplit('.', 1)[-1] for r in repositories[:3])}) are not validated.")
        if db['status'] == 'UNKNOWN': risks.append(f"No database structural evidence found for {domain['name']}; absence does not prove independence.")
        if metric['internal_cohesion'] is None: risks.append(f"No outgoing dependency evidence of {domain['name']} to estimate cohesion.")
        confidence = 'LIMITED' if db['status'] == 'UNKNOWN' else 'STRUCTURAL_ONLY'
        boundary_count = sum(i['issue_type'] == 'DOMAIN_BOUNDARY_VIOLATION' and domain['id'] in i['domain_ids'] for i in issues) if boundary_available else None
        cost_inputs = dict(classes=member_count, boundary_pairs=len(boundary_pairs), shared_repositories=len(shared), god_classes=len(god_classes), cross_domain_cycles=len(cross_cycles))
        cost_index = round(member_count / 20 + len(boundary_pairs) * 1.5 + len(shared) * 8 + len(god_classes) * 6 + len(cross_cycles) * 12, 1)
        effort = 'S' if cost_index <= 8 else 'M' if cost_index <= 18 else 'L' if cost_index <= 35 else 'XL'
        risk = 'HIGH' if cross_cycles or shared or len(boundary_pairs) >= 8 else 'MEDIUM' if boundary_pairs or god_classes else 'LOW'
        drivers = [f'{member_count} classes']
        if boundary_pairs: drivers.append(f'{len(boundary_pairs)} outgoing cross-domain class pairs')
        if shared: drivers.append(f'{len(shared)} shared repositories')
        if god_classes: drivers.append(f'{len(god_classes)} God-class candidate(s)')
        if cross_cycles: drivers.append(f'{len(cross_cycles)} cross-domain cycle(s)')
        excluded = ', '.join(f"{e['label'].lower()} ({e['reason']})" for e in not_measured)
        parts = '; '.join(f"{d['label'].lower()} {d['value']} = {d['text']}" for d in details.values())
        assessments.append(dict(domain_id=domain['id'], domain_name=domain['name'], readiness_score=readiness,
            extraction_difficulty={'S':'LOW','M':'MEDIUM','L':'HIGH','XL':'VERY_HIGH'}[effort], effort_band=effort,
            risk_band=risk, risk_drivers=drivers, heuristic_cost_index=cost_index, cost_inputs=cost_inputs,
            cost_formula='cost index = classes / 20 + 1.5 x crossing class pairs + 8 x shared repositories + 6 x God-class candidates + 12 x cross-domain cycles (heuristic, not hours or currency)',
            component_scores={k: round(v, 2) for k,v in components.items()}, weights=effective, configured_weights=configured,
            component_details=details, not_measured=not_measured,
            formula='readiness = sum(component x weight) over the measured inputs. Weights: configured cohesion/decoupling/cycles/database weights x 0.8, plus boundary size 0.12 and class concentration 0.08; '
                    'weights of inputs that are not measured are removed and the rest are scaled to sum to 1. Per the glossary term Readiness this is a heuristic ordering aid, not calibrated.'
                    + (f' Not measured here: {excluded}.' if excluded else ''),
            internal_cohesion=metric['internal_cohesion'], external_coupling=metric['cross_domain_ratio'],
            incoming_pressure=metric['incoming_edges'], outgoing_pressure=metric['outgoing_edges'],
            boundary_violations=boundary_count, cycle_risk=len(cross_cycles), database_coupling=db['status'],
            confidence=confidence, risks=risks, blockers=cross_cycles,
            explanation=f"{domain['name']} scores {readiness}/100 from {len(components)} measured inputs: {parts}." + (f' Not measured: {excluded}.' if excluded else '')))
    domain_graph = nx.DiGraph()
    domain_graph.add_nodes_from(d['id'] for d in domains)
    pair_counts = {}
    for s, t in graph.edges:
        if membership[s] != membership[t]:
            pair_counts[(membership[s], membership[t])] = pair_counts.get((membership[s], membership[t]), 0) + 1
    domain_graph.add_edges_from(pair_counts)
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
                assessment.update(recommended_order=len(ranked) + 1, wave=wave, coupled_group=members if len(members) > 1 else [])
                ranked.append(assessment)
        remaining.difference_update(ready_groups)
        wave += 1
    for a in ranked:
        did = a['domain_id']
        uses = sorted(((names[t], n, assessment_by_id[t]['wave']) for (s, t), n in pair_counts.items() if s == did and t != did and t not in a['coupled_group']), key=lambda x: (x[2], x[0]))
        used_by = sorted(((names[s], n, assessment_by_id[s]['wave']) for (s, t), n in pair_counts.items() if t == did and s not in a['coupled_group']), key=lambda x: (x[2], x[0]))
        peers = [names[m] for m in a['coupled_group'] if m != did]
        wave_peers = [x for x in ranked if x['wave'] == a['wave'] and x['domain_id'] != did and x['domain_id'] not in a['coupled_group']]
        parts = []
        if peers:
            loop = sum(n for (s, t), n in pair_counts.items() if s in a['coupled_group'] and t in a['coupled_group'] and s != t)
            parts.append(f"{a['domain_name']} is in a dependency cycle with {', '.join(peers)} ({loop} class pairs between the group); the group is remediated together in wave {a['wave']}.")
        if uses:
            parts.append(f"Wave {a['wave']}: {a['domain_name']} depends on " + ', '.join(f"{n} ({c} class pair{'s' if c != 1 else ''}, wave {w})" for n, c, w in uses) + ', which precede it.')
        elif not peers:
            parts.append(f"Wave {a['wave']}: {a['domain_name']} depends on no other candidate domain.")
        if used_by:
            parts.append('It is used by ' + ', '.join(f"{n} ({c} class pair{'s' if c != 1 else ''}, wave {w})" for n, c, w in used_by) + '.')
        if wave_peers:
            ordered = sorted(wave_peers + [a], key=lambda x: (-x['readiness_score'], x['domain_name']))
            scores = ', '.join(x['domain_name'] + ' ' + str(x['readiness_score']) for x in ordered)
            parts.append(f"Within wave {a['wave']} it ranks {ordered.index(a) + 1} of {len(ordered)} by structural readiness ({scores}).")
        a['sequence_reason'] = ' '.join(parts)
    return ranked
