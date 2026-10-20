from collections import defaultdict
import networkx as nx
from app.services.graph import stable_id
from .db_callers import resolve as resolve_database_callers


def derive(static, runtime, coverage, events, structural_weight, weights=None, session_info=None):
    weights = weights or {'cohesion': .60, 'cycles': .25, 'persistence': .15}
    nodes = {n['id']:n for n in runtime['nodes']}
    class_domains = {c['id']:c['domain_id'] for c in static['classes']}
    classes_by_id = {c['id']:c for c in static['classes']}
    # Callers come from the span's own code attributes or the nearest received ancestor (see db_callers); missing spans are never invented.
    flows = {}
    grouped = defaultdict(list)
    for e in events:
        grouped[(e['session_id'],e['trace_id'])].append(e)
    database_rows, database_summary = resolve_database_callers(events,classes_by_id,session_info)
    database = {i:item for i,item in enumerate(database_rows)}
    for item in database.values(): item['domain_id'] = class_domains.get(item['caller'])
    for (sid,trace), group in grouped.items():
        ordered = sorted(group,key=lambda e:e['timestamp'])
        entry = next((e for e in ordered if e['event_type']=='HTTP_SERVER'),ordered[0])
        identities = sorted({e['class_name'] for e in ordered if e.get('class_name')})
        key = (entry.get('http_method'),entry.get('http_route'),tuple(identities))
        flow = flows.setdefault(key,dict(id=stable_id('flow',str(key)),entry_point=entry.get('http_route') or entry['event_type'],
            http_method=entry.get('http_method'),classes=identities,trace_count=0,error_count=0,total_duration_ms=0,evidence=[]))
        flow['trace_count'] += 1
        flow['error_count'] += int(any(e['error'] for e in group))
        flow['total_duration_ms'] += entry['duration_ms']
        flow['evidence'] = (flow['evidence']+[dict(session_id=sid,trace_id=trace,span_id=entry['span_id'])])[:20]
    domain_graph = nx.DiGraph()
    domain_graph.add_nodes_from(d['id'] for d in static['domains'])
    metrics = {d['id']:dict(internal_calls=0,outgoing_calls=0,incoming_calls=0,error_count=0,total_calls=0) for d in static['domains']}
    for edge in runtime['edges']:
        source,target = nodes[edge['source']].get('domain_id'),nodes[edge['target']].get('domain_id')
        if not source or not target: continue
        count = edge['call_count']
        metrics[source]['total_calls'] += count
        metrics[source]['error_count'] += edge['error_count']
        if source==target: metrics[source]['internal_calls'] += count
        else:
            metrics[source]['outgoing_calls'] += count
            metrics[target]['incoming_calls'] += count
            domain_graph.add_edge(source,target)
    cyclic = {n for group in nx.strongly_connected_components(domain_graph) if len(group)>1 for n in group}
    resources = defaultdict(set)         # (system, server, namespace, resource) -> domains calling it
    called_by = defaultdict(set)         # domain -> resources it calls
    for item in database.values():
        if item['resource'] and item['namespace'] and item['server'] and item['domain_id']:
            key = (item['system'], item['server'], item['namespace'], item['resource'])
            resources[key].add(item['domain_id']); called_by[item['domain_id']].add(key)
    shared_domains = {d for group in resources.values() if len(group)>1 for d in group}
    assessments = []
    for structural in static['modernization']:
        identity = structural['domain_id']
        metric = metrics[identity]
        observation = next(d for d in coverage['domain_observations'] if d['id']==identity)
        ratio = observation['observed']/observation['total'] if observation['total'] else 0
        # Absence of mapped calls is unknown, not zero readiness.
        total = metric['total_calls']
        # Each runtime input is measured or left out; none is replaced by a default.
        components, not_measured = {}, []
        if total: components['cohesion'] = 100*metric['internal_calls']/total
        else: not_measured.append(dict(input='cohesion',reason='no mapped runtime call leaves or stays inside this domain'))
        if total: components['cycles'] = 0 if identity in cyclic else 100
        else: not_measured.append(dict(input='cycles',reason='no mapped runtime call involves this domain'))
        own = called_by.get(identity,set())
        if own: components['persistence'] = 100*sum(len(resources[k])==1 for k in own)/len(own)
        else: not_measured.append(dict(input='persistence',reason='no database call with a complete system, server, namespace and resource identity was attributed to this domain'))
        used = {k:w for k,w in weights.items() if k in components}
        scale = sum(used.values())
        used = {k:w/scale for k,w in used.items()} if scale else {}
        runtime_score = round(sum(components[k]*used[k] for k in used),1) if used and total else None
        combined = round(structural_weight*structural['readiness_score']+(1-structural_weight)*runtime_score,1) if runtime_score is not None else structural['readiness_score']
        assessments.append(dict(domain_id=identity,domain_name=structural['domain_name'],structural_score=structural['readiness_score'],runtime_score=runtime_score,
            combined_score=combined,coverage_confidence=round(ratio,3),confidence='LIMITED_OBSERVATION' if ratio<.8 else 'OBSERVED_SAMPLE',
            extraction_difficulty='LOW' if combined>=80 else 'MEDIUM' if combined>=60 else 'HIGH' if combined>=40 else 'VERY_HIGH',
            metrics=metric,runtime_cycle=identity in cyclic,shared_persistence_candidate=identity in shared_domains,
            recommended_order=structural['recommended_order'],wave=structural['wave'],
            risks=structural['risks']+([f"Observation coverage is {round(100 * ratio, 1)}% of the domain's classes, under 80%; conclusions have limited confidence."] if ratio<.8 else []),
            formula='runtime = sum(component x weight) over the measured components, weights renormalized to sum to 1; cohesion = observed internal calls / observed calls from the domain x 100; cycles = 0 if the domain is in an observed domain cycle, otherwise 100; persistence = resources called by this domain alone / resources it calls x 100; combined = structural_weight x structural + (1 - structural_weight) x runtime; without runtime the structural score is kept',
            component_scores=components,component_weights=used,not_measured=not_measured,
            structural_weight=structural_weight,evidence={'coverage_domain_id':identity,'runtime_edge_ids':[e['id'] for e in runtime['edges'] if nodes[e['source']].get('domain_id')==identity]},
            sequence_note=f"Static dependency-first order retained (wave {structural['wave']}); runtime evidence adds review blockers, not automatic extraction approval."))
    # Generic "exercise another entry point" text was removed: specific, ranked suggestions come from
    # app.insight.test_suggestions (route, parameters, constraints, reachable classes).
    recommendations = []
    return dict(database=list(database.values()),database_summary=database_summary,flows=list(flows.values()),modernization=assessments,recommendations=recommendations)
