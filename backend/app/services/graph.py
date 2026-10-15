"""Normalized dependency graphs. Direction: dependent -> dependency."""
import hashlib
import networkx as nx


def stable_id(prefix: str, value: str) -> str:
    return prefix + '-' + hashlib.sha256(value.encode()).hexdigest()[:16]


def build_graphs(classes: list[dict], edges: list[dict], prefixes: list[str]) -> dict:
    internal = {c['fqn']: dict(c) for c in classes if not any(c['fqn'].startswith(p) for p in prefixes)}
    graph = nx.DiGraph()
    for fqn, cls in sorted(internal.items()):
        cls.setdefault('package_name', fqn.rpartition('.')[0] or '(default)')
        cls.setdefault('simple_name', fqn.rsplit('.', 1)[-1])
        cls.setdefault('annotations', [])
        cls['id'] = fqn
        graph.add_node(fqn, **cls)
    internal_edges, external_edges = [], []
    seen = set()
    for edge in sorted(edges, key=lambda e: (e['source'], e['target'], e['dependency_type'])):
        key = (edge['source'], edge['target'], edge['dependency_type'])
        if key in seen or edge['source'] not in internal:
            continue
        seen.add(key)
        edge = dict(edge, id=stable_id('edge', '|'.join(key)))
        if edge['target'] not in internal:
            external_edges.append(edge)
        elif edge['source'] != edge['target']:
            internal_edges.append(edge)
            if graph.has_edge(edge['source'], edge['target']):
                graph[edge['source']][edge['target']]['weight'] += 1
            else:
                graph.add_edge(edge['source'], edge['target'], weight=1)
    packages = nx.DiGraph()
    for cls in internal.values():
        packages.add_node(cls['package_name'])
    for source, target in graph.edges:
        p, q = internal[source]['package_name'], internal[target]['package_name']
        if p != q:
            if packages.has_edge(p, q):
                packages[p][q]['weight'] += 1
            else:
                packages.add_edge(p, q, weight=1)
    return dict(classes=internal, graph=graph, packages=packages, edges=internal_edges, external_edges=external_edges)
