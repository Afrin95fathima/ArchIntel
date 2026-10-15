"""Pure analysis orchestration, independent of HTTP, scanner and persistence."""
from collections import Counter
from app.services.graph import build_graphs, stable_id
from app.services.cycles import detect_cycles
from app.services.metrics import calculate_metrics
from app.services.domains import discover_domains, enrich_domains
from app.services.issues import detect_issues
from app.services.modernization import assess_and_rank
from app.services.domain_analysis import dependency_matrix, model_overlap, entry_point_inventory

VERSION = '0.2.1'


def analyze(classes: list[dict], edges: list[dict], config, stage=lambda *_: None) -> dict:
    stage('GRAPH_BUILDING', 40)
    built = build_graphs(classes, edges, config.external_prefixes)
    graph, packages, internal = built['graph'], built['packages'], built['classes']
    if not internal:
        raise ValueError('No internal classes remain after filtering. Review external-prefix settings.')
    stage('CYCLE_ANALYSIS', 50)
    args = dict(max_length=config.max_cycle_length, cap=config.max_cycles_per_scc, large=config.large_scc_threshold)
    class_cycles = detect_cycles(graph, 'CLASS', **args)
    package_cycles = detect_cycles(packages, 'PACKAGE', **args)
    cycles = class_cycles['items'] + package_cycles['items']
    stage('METRICS_ANALYSIS', 60)
    class_metrics, package_metrics, thresholds = calculate_metrics(internal, graph)
    stage('DOMAIN_DISCOVERY', 70)
    domains, membership = discover_domains(internal, graph)
    enrich_domains(domains, membership, graph, internal, built['external_edges'])
    stage('ISSUE_ANALYSIS', 78)
    issues = detect_issues(internal, graph, class_metrics, package_metrics, thresholds, cycles, domains, membership, built['edges'])
    stage('MODERNIZATION_ANALYSIS', 86)
    assessments = assess_and_rank(domains, membership, graph, cycles, issues, config.readiness_weights)
    class_by_name = {m['entity_id']:m for m in class_metrics}
    class_nodes = [dict(cls, domain_id=membership[name], metrics=class_by_name[name]) for name, cls in sorted(internal.items())]
    package_nodes = [dict(id=m['entity_id'], name=m['entity_id'], metrics=m,
        domain_ids=sorted({membership[n] for n in internal if internal[n]['package_name']==m['entity_id']})) for m in package_metrics]
    package_edges = [dict(id=stable_id('pedge', s+t), source=s,target=t,weight=data['weight']) for s,t,data in packages.edges(data=True)]
    domain_pairs = Counter((membership[s],membership[t]) for s,t in graph.edges if membership[s]!=membership[t])
    domain_edges = [dict(id=stable_id('dedge',s+t),source=s,target=t,weight=w) for (s,t),w in sorted(domain_pairs.items())]
    boundary_analysis = dependency_matrix(domains, internal, built['edges'], membership)
    ownership_analysis = model_overlap(domains, internal, built['edges'], membership)
    entry_points = entry_point_inventory(domains, internal, membership)
    modernization_metrics = dict(cycle_count=len(cycles), god_class_count=sum(i['issue_type']=='GOD_CLASS' for i in issues),
        cross_domain_edge_count=sum(row['edge_count'] for row in boundary_analysis['rows']),
        shared_entity_count=len(ownership_analysis['duplicated_models']),
        average_cross_domain_coupling=round(sum(d['metrics']['cross_domain_ratio'] for d in domains)/len(domains),4) if domains else None)
    return dict(algorithm_version=VERSION,
        summary=dict(class_count=len(internal), package_count=len(package_nodes), dependency_count=graph.number_of_edges(),
            typed_dependency_count=len(built['edges']), external_dependency_count=len(built['external_edges']),
            domain_count=len(domains), issue_count=len(issues),
            class_scc_count=class_cycles['scc_count'], package_scc_count=package_cycles['scc_count'],
            issue_counts=dict(Counter(i['severity'] for i in issues)),
            average_readiness=round(sum(a['readiness_score'] for a in assessments)/len(assessments),1),
            modernization_baseline=modernization_metrics),
        classes=class_nodes, packages=package_nodes, edges=built['edges'], package_edges=package_edges,
        domain_edges=domain_edges, external_edges=built['external_edges'],
        cycles=cycles, domains=domains, issues=issues, metrics=package_metrics,
        domain_dependency_matrix=boundary_analysis, data_ownership=ownership_analysis, entry_points=entry_points,
        modernization_baseline=modernization_metrics,
        class_metrics=class_metrics, thresholds=thresholds, modernization=assessments,
        limitations=['Static bytecode dependencies do not prove runtime behavior, traffic, SQL or business boundaries.',
            'Candidate domains and readiness are explainable heuristics requiring architect validation.',
            'Reflection, dependency injection wiring and runtime-generated classes may be incomplete.',
            'Cycle samples are bounded; SCC membership is the complete cyclic-cluster finding.'],
        configuration=dict(external_prefixes=config.external_prefixes, max_cycle_length=config.max_cycle_length,
            max_cycles_per_scc=config.max_cycles_per_scc, large_scc_threshold=config.large_scc_threshold,
            readiness_weights=config.readiness_weights, louvain_seed=42))
