"""Normalized dependency graphs. Direction: dependent -> dependency."""
import hashlib
import networkx as nx


def stable_id(prefix: str, value: str) -> str:
    return prefix + '-' + hashlib.sha256(value.encode()).hexdigest()[:16]


APPLICATION_STEREOTYPES = ('SpringBootApplication', 'Controller', 'RestController', 'Service', 'Repository',
    'Component', 'Entity', 'Configuration')


def application_roots(classes: list[dict], prefixes: list[str]) -> list[dict]:
    """Package roots of scanned classes that match an external prefix but are evidently application code.

    Spring PetClinic lives in org.springframework.samples.petclinic; a blanket 'org.springframework.'
    exclusion would otherwise remove the whole application. Anchors are scanned classes annotated with
    an application stereotype; the root is the longest common package of anchors sharing a prefix.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for c in classes:
        prefix = next((p for p in prefixes if c['fqn'].startswith(p)), None)
        hit = next((a for a in c.get('annotations', []) if a.rsplit('.', 1)[-1] in APPLICATION_STEREOTYPES), None)
        if prefix and hit:
            groups.setdefault(prefix, []).append((c['fqn'], hit))
    roots = []
    for prefix, anchors in sorted(groups.items()):
        parts = [fqn.rpartition('.')[0].split('.') for fqn, _ in anchors]
        common = []
        for segment in zip(*parts):
            if len(set(segment)) != 1:
                break
            common.append(segment[0])
        root = '.'.join(common)
        if len(common) > len(prefix.strip('.').split('.')):
            roots.append(dict(root=root + '.', excluded_prefix=prefix, anchors=sorted({fqn for fqn, _ in anchors})[:10],
                reason=f"{len(anchors)} scanned classes under {root} carry application stereotypes (e.g. @{anchors[0][1].rsplit('.', 1)[-1]}), "
                       f"so they are analysed although they match the external prefix '{prefix}'."))
    return roots


def build_graphs(classes: list[dict], edges: list[dict], prefixes: list[str]) -> dict:
    roots = application_roots(classes, prefixes)
    keep = tuple(r['root'] for r in roots)
    internal = {c['fqn']: dict(c) for c in classes if c['fqn'].startswith(keep) or not any(c['fqn'].startswith(p) for p in prefixes)}
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
    return dict(classes=internal, graph=graph, packages=packages, edges=internal_edges, external_edges=external_edges, application_roots=roots)
