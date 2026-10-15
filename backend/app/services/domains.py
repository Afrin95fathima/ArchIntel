"""Deterministic, evidence-bearing candidate domains; not business truth."""
from collections import Counter, defaultdict
import re
import networkx as nx
from community import community_louvain
from app.services.graph import stable_id

GENERIC = {'service', 'services', 'controller', 'controllers', 'repository', 'repositories', 'model', 'models', 'entity', 'entities', 'impl', 'api', 'dto', 'util', 'utils', 'internal'}


def discover_domains(classes: dict, graph: nx.DiGraph) -> tuple[list[dict], dict[str, str]]:
    packages = sorted({c['package_name'] for c in classes.values()})
    parts = [p.split('.') for p in packages]
    common = 0
    while parts and all(len(p) > common for p in parts) and len({p[common] for p in parts}) == 1:
        common += 1
    if len(packages) == 1:
        common = max(0, len(parts[0]) - 1)
    undirected = graph.to_undirected()
    communities = community_louvain.best_partition(undirected, random_state=42, weight='weight') if undirected.number_of_edges() else {n: i for i, n in enumerate(sorted(classes))}
    groups = defaultdict(list)
    naming = {}
    for name, cls in sorted(classes.items()):
        suffix = cls['package_name'].split('.')[common:]
        semantic = next((p for p in suffix if p.lower() not in GENERIC), None)
        if semantic:
            key = semantic
        else:
            key = 'community-' + str(communities[name])
        groups[key].append(name)
        naming[key] = semantic
    domains, membership = [], {}
    for key, members in sorted(groups.items()):
        if naming[key]:
            label = re.sub(r'[_-]', ' ', key).title()
        else:
            stems = [re.sub(r'(Service|Controller|Repository|Entity|Impl|Manager|Dto)$', '', classes[n]['simple_name']) for n in members]
            label = Counter(stems).most_common(1)[0][0] or 'Candidate'
        domain_id = stable_id('domain', '|'.join(members))
        counts = Counter(communities[n] for n in members)
        agreement = max(counts.values()) / len(members)
        annotations = sorted({a for n in members for a in classes[n].get('annotations', [])})
        density = nx.density(graph.subgraph(members)) if len(members) > 1 else 0.0
        confidence = min(.95, .40 + (.25 if naming[key] else 0) + .15 * agreement + (.10 if annotations else 0))
        domain = dict(id=domain_id, name=label, domain_source='AUTO', confidence=round(confidence, 2),
            class_count=len(members), package_count=len({classes[n]['package_name'] for n in members}),
            classes=members, packages=sorted({classes[n]['package_name'] for n in members}),
            evidence=[f"Package grouping: {key}", f"Louvain community agreement: {agreement:.0%} (seed 42)", f"Internal dependency density: {density:.3f}"] + ([f"Annotations: {', '.join(annotations[:8])}"] if annotations else []),
            confidence_note='Heuristic confidence, not a calibrated probability; validate business boundaries.')
        domains.append(domain)
        membership.update({n: domain_id for n in members})
    return domains, membership


def enrich_domains(domains: list[dict], membership: dict, graph: nx.DiGraph, classes: dict, external_edges: list[dict]) -> None:
    db_words = ('java.sql.', 'javax.sql.', 'jakarta.persistence.', 'javax.persistence.', 'JdbcTemplate', 'DataSource', 'JpaRepository', 'CrudRepository')
    for domain in domains:
        members = set(domain['classes'])
        internal = [(s, t) for s, t in graph.edges if s in members and t in members]
        outgoing = [(s, t) for s, t in graph.edges if s in members and t not in members]
        incoming = [(s, t) for s, t in graph.edges if s not in members and t in members]
        db_classes = sorted(n for n in members if any(a.endswith('.Repository') for a in classes[n].get('annotations', [])))
        signals = [e for e in external_edges if e['source'] in members and any(w in e['target'] for w in db_words)]
        repositories = sorted(set(db_classes + [e['source'] for e in signals if 'Repository' in e['target']]))
        entities = sorted(n for n in classes if any(a.endswith('.Entity') for a in classes[n].get('annotations', [])))
        shared = []
        for repo in repositories:
            consumers = sorted({membership[s] for s in graph.predecessors(repo)} | {domain['id']})
            targets = sorted(t for t in graph.successors(repo) if t in entities)
            if len(consumers) > 1:
                shared.append(dict(repository=repo, domains=consumers, entities=targets))
        domain['metrics'] = dict(internal_edges=len(internal), outgoing_edges=len(outgoing), incoming_edges=len(incoming),
            cross_domain_ratio=round(len(outgoing) / (len(internal) + len(outgoing)), 6) if internal or outgoing else 0.0,
            internal_cohesion=round(len(internal) / (len(internal) + len(outgoing)), 6) if internal or outgoing else None,
            internal_density=round(nx.density(graph.subgraph(members)), 6) if len(members) > 1 else 0.0)
        domain_entities = [n for n in entities if n in members]
        repository_entities = [{'repository': repo, 'entities': sorted(t for t in graph.successors(repo) if t in entities)} for repo in repositories]
        domain['database'] = dict(status='STRUCTURAL_SIGNALS' if repositories or signals or domain_entities else 'UNKNOWN',
            repositories=repositories, signals=signals[:50], shared_repositories=shared,
            entities=domain_entities, repository_entities=repository_entities,
            note='Static repository/entity references only. Runtime SQL, transactions and table ownership are unknown.')
