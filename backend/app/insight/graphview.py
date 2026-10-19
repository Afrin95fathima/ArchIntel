"""WP11: explained graph views. Every node and edge carries data-derived explanations; external and
unresolved names are classified and grouped instead of appearing as unexplained nodes."""
from __future__ import annotations

from collections import Counter, defaultdict
import re

from .cycles import analyse as analyse_cycles, membership as cycle_membership
from .roles import LAYER_LABEL, LAYER_ORDER, LAYER_PLAIN, short

JDK_PREFIXES = ('java.', 'jdk.', 'sun.', 'com.sun.', 'org.w3c.dom.', 'org.xml.sax.', 'org.ietf.jgss.', 'javax.annotation.processing.',
    'javax.crypto.', 'javax.imageio.', 'javax.lang.model.', 'javax.management.', 'javax.naming.', 'javax.net.', 'javax.print.',
    'javax.script.', 'javax.security.', 'javax.sound.', 'javax.sql.', 'javax.swing.', 'javax.tools.', 'javax.transaction.xa.',
    'javax.xml.catalog.', 'javax.xml.crypto.', 'javax.xml.datatype.', 'javax.xml.namespace.', 'javax.xml.parsers.', 'javax.xml.stream.',
    'javax.xml.transform.', 'javax.xml.validation.', 'javax.xml.xpath.', 'javax.accessibility.', 'javax.rmi.ssl.')
GENERATED = re.compile(r'(\$\$EnhancerBy|\$\$SpringCGLIB|\$\$FastClassBy|\$HibernateProxy|_\$\$_jvst|\$\$Lambda|^jdk\.proxy\d*\.|\$Proxy\d+|^com\.sun\.proxy\.)')
CATEGORY_TEXT = {
    'JDK_CLASS': 'JDK class: part of the Java platform, not of the uploaded artifact.',
    'EXTERNAL_LIBRARY': 'External library class not in the uploaded artifact (a dependency the application compiles against).',
    'RUNTIME_ONLY': 'Runtime-only class: observed at runtime but not found in the scanned artifact; the scanned build may differ from what runs.',
    'GENERATED_OR_PROXY': 'Generated or proxy class created at runtime (for example a Spring CGLIB proxy or a lambda class).',
    'UNMATCHED_NAME': 'Name could not be matched to any class: the telemetry identity is not a recognisable Java class name.',
}


def classify_external(name: str, bundled: set[str] | None = None) -> str:
    if GENERATED.search(name):
        return 'GENERATED_OR_PROXY'
    if name.startswith(JDK_PREFIXES):
        return 'JDK_CLASS'
    if not re.fullmatch(r'[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)+', name):
        return 'UNMATCHED_NAME'
    return 'EXTERNAL_LIBRARY'


def unresolved(model) -> dict:
    """Every name outside the scanned artifact, with category and first reference."""
    rows: dict[str, dict] = {}
    for edge in sorted(model.external_edges, key=lambda e: (e['source'], e['target'], e['dependency_type'])):
        target = edge['target']
        row = rows.get(target)
        if row is None:
            rows[target] = row = dict(name=target, category=classify_external(target), first_reference=dict(kind='STATIC',
                source=model.owners.get(edge['source'], edge['source']), dependency_type=edge['dependency_type']), reference_count=0, referencing_classes=set())
        row['reference_count'] += 1
        row['referencing_classes'].add(model.owners.get(edge['source'], edge['source']))
    for node in (model.runtime or {}).get('runtime_graph', {}).get('nodes', []):
        if node.get('static_id') or node.get('node_type') != 'CLASS':
            continue
        raw = node.get('name') or node['id']
        category = 'GENERATED_OR_PROXY' if GENERATED.search(raw) else 'UNMATCHED_NAME' if not re.fullmatch(r'[A-Za-z_$][\w$.]*', raw) else 'RUNTIME_ONLY'
        rows.setdefault(raw, dict(name=raw, category=category, first_reference=dict(kind='RUNTIME', runtime_node_id=node['id'],
            mapping_state=node.get('mapping_state')), reference_count=1, referencing_classes=set()))
    by_category = defaultdict(list)
    for row in rows.values():
        row['referencing_classes'] = sorted(row['referencing_classes'])[:20]
        row['explanation'] = CATEGORY_TEXT[row['category']]
        by_category[row['category']].append(row)
    return dict(categories=[dict(category=c, label=CATEGORY_TEXT[c], count=len(by_category[c]),
        items=sorted(by_category[c], key=lambda r: (-r['reference_count'], r['name']))[:200]) for c in CATEGORY_TEXT if by_category[c]],
        total=len(rows))


def _debt_levels(debt: dict | None) -> dict[str, str]:
    order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'INFO': 0}
    out: dict[str, str] = {}
    for finding in (debt or {}).get('findings', []):
        for node in finding['node_ids'][:1]:
            if node not in out or order[finding['severity']] > order[out[node]]:
                out[node] = finding['severity']
    return out


def view(model, level: str = 'package', package: str | None = None, focus: str | None = None, min_weight: int = 1,
         limit: int = 400, debt: dict | None = None) -> dict:
    cycles = analyse_cycles(model)
    in_cycle = cycle_membership(cycles)
    debt_level = _debt_levels(debt)
    observed = model.observed_classes
    owners = sorted({model.owners.get(c, c) for c in model.classes if model.owners.get(c, c) in model.classes})
    hidden = []
    if level == 'package':
        members = defaultdict(list)
        for fqn in owners:
            members[model.package(fqn)].append(fqn)
        weights: Counter = Counter()
        kinds: dict = defaultdict(Counter)
        runtime: Counter = Counter()
        for (s, t), k in model.owner_edges.items():
            p, q = model.package(s), model.package(t)
            if p != q:
                weights[(p, q)] += 1
                kinds[(p, q)].update(k)
        for (s, t), calls in model.runtime_calls.items():
            p, q = model.package(s), model.package(t)
            if p != q:
                runtime[(p, q)] += calls
        nodes = []
        for package_name, names in sorted(members.items()):
            layers = Counter(model.roles[n]['layer'] for n in names)
            layer = layers.most_common(1)[0][0]
            seen = None if observed is None else sum(1 for n in names if n in observed)
            nodes.append(dict(id=package_name, kind='PACKAGE', label=package_name.split('.')[-1], full_name=package_name, layer=layer,
                size=len(names), role=None, in_cycle=package_name in in_cycle, debt=max((debt_level.get(n, '') for n in names), key=lambda x: ['', 'INFO', 'LOW', 'MEDIUM', 'HIGH'].index(x)) or None,
                observed=seen, explanation=dict(
                    what=f"Package {package_name} with {len(names)} top-level classes.",
                    why_here=f"Placed in the {LAYER_PLAIN[layer]} row because {layers[layer]} of its {len(names)} classes have that role" +
                             (f" (others: {', '.join(f'{v} {LAYER_PLAIN[k]}' for k, v in layers.items() if k != layer)})." if len(layers) > 1 else '.'),
                    coverage='No runtime session selected.' if seen is None else f'{seen} of {len(names)} classes observed at runtime.')))
        edges = [dict(id=f'{s}->{t}', source=s, target=t, weight=w, edge_types=dict(kinds[(s, t)]), runtime_calls=runtime.get((s, t), 0),
            sources=['static'] + (['runtime'] if runtime.get((s, t)) else [])) for (s, t), w in sorted(weights.items())]
        for (s, t), calls in sorted(runtime.items()):
            if (s, t) not in weights:
                edges.append(dict(id=f'{s}->{t}', source=s, target=t, weight=0, edge_types={}, runtime_calls=calls, sources=['runtime']))
        total_nodes = len(nodes)
    else:
        scope = [n for n in owners if (not package or model.package(n) == package)]
        if focus and focus in model.classes:
            focus_owner = model.owners.get(focus, focus)
            neighbours = {focus_owner} | {t for (s, t) in model.owner_edges if s == focus_owner} | {s for (s, t) in model.owner_edges if t == focus_owner}
            scope = sorted(set(scope) & neighbours) if package else sorted(neighbours)
        total_nodes = len(scope)
        if len(scope) > limit:
            ranked = sorted(scope, key=lambda n: -sum(1 for (s, t) in model.owner_edges if n in (s, t)))
            hidden.append(f'{len(scope) - limit} classes with the fewest dependencies hidden (limit {limit} nodes). Select a package to see all of its classes.')
            scope = sorted(ranked[:limit])
        ids = set(scope)
        nodes = []
        for fqn in scope:
            role = model.roles[fqn]
            methods = model.methods_of(fqn)
            seen = None if observed is None else (fqn in observed or any(n in observed for n in model.nested_by_owner.get(fqn, [])))
            nodes.append(dict(id=fqn, kind='CLASS', label=short(fqn), full_name=fqn, package=model.package(fqn), layer=role['layer'], role=role['role'],
                size=len(methods), in_cycle=fqn in in_cycle, debt=debt_level.get(fqn), observed=seen, explanation=dict(
                    what=f"{short(fqn)} — {role['role'].lower().replace('_', ' ')}: it {role['plain']}.",
                    why_here=f"Placed in the {LAYER_PLAIN[role['layer']]} row because it is {role['reason']}.",
                    coverage='No runtime session selected.' if seen is None else 'Observed at runtime in the selected sessions.' if seen else 'Not observed in the selected sessions (this does not mean unused).')))
        edges = []
        for (s, t), k in sorted(model.owner_edges.items()):
            if s in ids and t in ids:
                calls = model.runtime_calls.get((s, t), 0)
                edges.append(dict(id=f'{s}->{t}', source=s, target=t, weight=sum(k.values()), edge_types=dict(k), runtime_calls=calls,
                    sources=['static'] + (['runtime'] if calls else [])))
        for (s, t), calls in sorted(model.runtime_calls.items()):
            if s in ids and t in ids and (s, t) not in model.owner_edges and s != t:
                edges.append(dict(id=f'{s}->{t}', source=s, target=t, weight=0, edge_types={}, runtime_calls=calls, sources=['runtime']))
    total_edges = len(edges)
    shown = [e for e in edges if e['weight'] >= min_weight or e['runtime_calls']]
    if len(shown) < total_edges:
        hidden.append(f'{total_edges - len(shown)} static edges with fewer than {min_weight} references hidden by the edge threshold.')
    for edge in shown:
        types = ', '.join(f'{k.lower().replace("_", " ")} ×{v}' for k, v in sorted(edge['edge_types'].items()))
        edge['explanation'] = (f"{edge['source']} depends on {edge['target']}" + (f": {types}" if types else '') +
            (f"; {edge['runtime_calls']} calls observed at runtime" if edge['runtime_calls'] else '; not observed at runtime' if observed is not None else '') +
            ('.' if edge['sources'] != ['runtime'] else ' (runtime only: no static reference found in the artifact).'))
    external = unresolved(model)
    return dict(level=level, package=package, focus=focus, nodes=nodes, edges=shown,
        external=dict(total=external['total'], categories=[dict(category=c['category'], label=c['label'], count=c['count']) for c in external['categories']]),
        layers=[dict(id=l, label=LAYER_LABEL[l]) for l in LAYER_ORDER],
        meta=dict(view=('Packages of the application' if level == 'package' else f'Classes in package {package}' if package else
                f'Classes connected to {short(focus)}' if focus else 'All top-level classes'),
            nodes_shown=len(nodes), nodes_total=total_nodes, edges_shown=len(shown), edges_total=total_edges, hidden=hidden,
            aggregation=('Classes are aggregated into packages; edge weight = number of distinct class-to-class dependencies between the packages.'
                if level == 'package' else 'Nested, anonymous and local classes are folded into their top-level class; edge weight = number of typed references.'),
            runtime=('Runtime evidence included.' if observed is not None else 'No runtime session selected: coverage and runtime calls are not shown.'),
            external=f"{external['total']} external or unresolved names are grouped in the 'External and unresolved' cluster, not drawn as nodes."))
