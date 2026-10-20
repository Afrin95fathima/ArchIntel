"""WP6: circular dependencies with the exact edges that form each loop.

Class level: top-level classes (nested/anonymous classes folded into their owner, so Outer <-> Outer$1
is never a cycle). Package level: packages, with the class pairs behind every package edge.
Self-references (a class or package depending on itself) are not cycles and are counted separately.
"""
from __future__ import annotations

from collections import Counter
from itertools import islice

import networkx as nx

from app.services.graph import stable_id
from .roles import LAYER_ORDER, short

VERB = {'METHOD_CALL': 'calls methods of', 'FIELD_TYPE': 'keeps a field of type', 'INHERITANCE': 'extends',
    'INTERFACE': 'implements', 'PARAMETER_TYPE': 'takes as a parameter', 'RETURN_TYPE': 'returns',
    'ANNOTATION': 'is annotated with', 'GENERIC_TYPE': 'uses as a type argument', 'EXCEPTION': 'throws',
    'TYPE_REFERENCE': 'uses', 'OTHER': 'depends on'}
PLAIN_VERB = {'METHOD_CALL': 'uses', 'FIELD_TYPE': 'holds a', 'INHERITANCE': 'is a kind of', 'INTERFACE': 'follows the contract of',
    'PARAMETER_TYPE': 'needs a', 'RETURN_TYPE': 'hands out a', 'ANNOTATION': 'is marked with', 'GENERIC_TYPE': 'holds a list of',
    'EXCEPTION': 'can fail with', 'TYPE_REFERENCE': 'works with', 'OTHER': 'depends on'}
STRENGTH = ['INHERITANCE', 'INTERFACE', 'FIELD_TYPE', 'METHOD_CALL', 'GENERIC_TYPE', 'PARAMETER_TYPE', 'RETURN_TYPE',
    'EXCEPTION', 'TYPE_REFERENCE', 'ANNOTATION', 'OTHER']


def _dominant(kinds: Counter) -> str:
    return min(kinds, key=lambda k: STRENGTH.index(k) if k in STRENGTH else len(STRENGTH)) if kinds else 'OTHER'


def _ordered(cycle: list[str]) -> list[str]:
    start = cycle.index(min(cycle))
    return cycle[start:] + cycle[:start]


def _layer_index(model, fqn: str) -> int:
    layer = model.roles.get(fqn, {}).get('layer', 'SUPPORT')
    return LAYER_ORDER.index(layer) if layer in LAYER_ORDER else len(LAYER_ORDER)


def class_graph(model) -> tuple[nx.DiGraph, int]:
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted({model.owners.get(c, c) for c in model.classes}))
    self_refs = 0
    for (source, target), kinds in model.owner_edges.items():
        graph.add_edge(source, target, kinds=Counter(kinds), runtime_calls=0, static=True)
    for (source, target), calls in model.runtime_calls.items():
        if source == target:
            self_refs += 1
            continue
        if graph.has_edge(source, target):
            graph[source][target]['runtime_calls'] = calls
        elif source in graph and target in graph:
            graph.add_edge(source, target, kinds=Counter({'METHOD_CALL': 1}), runtime_calls=calls, static=False)
    # Self references never enter owner_edges; count classes that reference themselves for the report.
    self_refs += sum(1 for (s, t) in model.edge_types if model.owners.get(s, s) == model.owners.get(t, t))
    return graph, self_refs


def package_graph(model, classes: nx.DiGraph) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(model.packages)
    for source, target, data in classes.edges(data=True):
        p, q = model.package(source), model.package(target)
        if p == q:
            continue
        if not graph.has_edge(p, q):
            graph.add_edge(p, q, kinds=Counter(), runtime_calls=0, static=False, pairs=[])
        edge = graph[p][q]
        edge['kinds'].update(data['kinds'])
        edge['runtime_calls'] += data['runtime_calls']
        edge['static'] = edge['static'] or data['static']
        edge['pairs'].append((source, target))
    return graph


def _edge_detail(model, graph, source, target, level, with_refs=True):
    data = graph[source][target]
    kinds = data['kinds']
    sources = (['static'] if data['static'] else []) + (['runtime'] if data['runtime_calls'] else [])
    detail = dict(id=stable_id('cycle-edge', level + source + '>' + target), source=source, target=target,
        edge_types=dict(sorted(kinds.items())), dominant_type=_dominant(kinds), reference_count=sum(kinds.values()),
        runtime_calls=data['runtime_calls'], sources=sources or ['static'])
    if level == 'CLASS' and with_refs:
        detail['references'] = model.references(source, target, limit=8)
    if level == 'PACKAGE':
        detail['class_pairs'] = [dict(source=s, target=t, edge_types=dict(sorted(graph_pair_kinds(model, s, t).items())),
            references=model.references(s, t, limit=3)) for s, t in sorted(data['pairs'])[:8]]
        detail['class_pair_count'] = len(data['pairs'])
    return detail


def graph_pair_kinds(model, source, target) -> Counter:
    return Counter(model.owner_edges.get((source, target), {}))


def _explain_class_cycle(model, path, edges):
    names = [short(n) for n in path]
    loop = ' → '.join(names + [names[0]])
    technical = '; '.join(
        (e['references'][0]['text'] if e.get('references') else f"{short(e['source'])} {VERB[e['dominant_type']]} {short(e['target'])}") +
        f" [{', '.join(e['edge_types'])}; {'+'.join(e['sources'])}]" for e in edges)
    if len(path) == 2:
        a, b = names
        ab, ba = edges[0], edges[1]
        plain = (f"{a} cannot be changed without also checking {b}, because each uses the other: "
                 f"{a} {PLAIN_VERB[ab['dominant_type']]} {b}, and {b} {PLAIN_VERB[ba['dominant_type']]} {a}.")
    else:
        plain = (f"These {len(path)} classes depend on each other in a loop ({loop}). A change to any one of them "
                 f"can force changes in all of them, and none can be reused or tested on its own.")
    return dict(technical=f'Cycle {loop}: {technical}.', plain=plain)


def _explain_package_cycle(path, edges):
    loop = ' → '.join(path + [path[0]])
    parts = [f"{e['source']} → {e['target']} via {e['class_pair_count']} class reference{'s' if e['class_pair_count'] != 1 else ''} "
             f"(e.g. {short(e['class_pairs'][0]['source'])} → {short(e['class_pairs'][0]['target'])})" for e in edges]
    plain = (f"The packages {', '.join(path)} depend on each other in a loop, so they cannot be separated into independent "
             f"modules until one of these dependencies is removed.")
    return dict(technical=f'Package cycle {loop}: ' + '; '.join(parts) + '.', plain=plain)


def _cut_candidates(model, graph, members, cycles, level):
    sub = graph.subgraph(members)
    counts = Counter((path[i], path[(i + 1) % len(path)]) for path in cycles for i in range(len(path)))
    rows = []
    for source, target, data in sub.edges(data=True):
        against = level == 'CLASS' and _layer_index(model, source) > _layer_index(model, target)
        remaining = sub.copy()
        remaining.remove_edge(source, target)
        breaks_all = not any(len(c) > 1 for c in nx.strongly_connected_components(remaining))
        weight = sum(data['kinds'].values())
        rows.append(dict(source=source, target=target, edge_types=dict(sorted(data['kinds'].items())), reference_count=weight,
            runtime_calls=data['runtime_calls'], against_layering=against, cycles_broken=counts.get((source, target), 0),
            breaks_whole_group=breaks_all))
    rows.sort(key=lambda r: (-r['breaks_whole_group'], -r['cycles_broken'], -r['against_layering'], r['reference_count'], r['runtime_calls'], r['source'], r['target']))
    for rank, row in enumerate(rows[:5], 1):
        why = [f"appears in {row['cycles_broken']} of the {len(cycles)} listed cycles"]
        if row['breaks_whole_group']:
            why.append(f"removing {row['source'].rsplit('.', 1)[-1]} -> {row['target'].rsplit('.', 1)[-1]} alone breaks every cycle in this group")
        if row['against_layering']:
            why.append(f"it points against the layering ({model.roles.get(row['source'], {}).get('layer', '?').lower()} → "
                       f"{model.roles.get(row['target'], {}).get('layer', '?').lower()})")
        why.append(f"only {row['reference_count']} code reference{'s' if row['reference_count'] != 1 else ''} to rework")
        why.append(f"{row['runtime_calls']} observed runtime calls" if row['runtime_calls'] else 'not measured: no runtime session is selected' if model.runtime is None else '0 runtime calls observed in the selected sessions')
        row.update(rank=rank, why='; '.join(why) + '.', label=f"Suggestion {rank} of {min(5, len(rows))}: requires human review before changing code.")
    return rows[:5]


def analyse(model, max_length: int = 8, cap: int = 20) -> dict:
    classes, self_refs = class_graph(model)
    packages = package_graph(model, classes)
    out = []
    for level, graph in (('CLASS', classes), ('PACKAGE', packages)):
        for members in sorted((sorted(s) for s in nx.strongly_connected_components(graph) if len(s) > 1), key=lambda s: (-len(s), s[0])):
            sub = graph.subgraph(members)
            cycles = [_ordered(c) for c in islice(nx.simple_cycles(sub, length_bound=max_length), cap + 1)] if len(members) <= 60 else []
            cycles = sorted(cycles, key=lambda c: (len(c), c))
            listed = []
            for path in cycles[:cap]:
                edges = [_edge_detail(model, graph, path[i], path[(i + 1) % len(path)], level) for i in range(len(path))]
                explanation = _explain_class_cycle(model, path, edges) if level == 'CLASS' else _explain_package_cycle(path, edges)
                listed.append(dict(id=stable_id('cycle-path', level + '>'.join(path)), members=path, size=len(path), edges=edges,
                    explanation=explanation, sources=sorted({s for e in edges for s in e['sources']})))
            crossing = sorted({model.package(m) for m in members}) if level == 'CLASS' else members
            layers = sorted({model.roles.get(m, {}).get('layer', 'SUPPORT') for m in members}) if level == 'CLASS' else []
            entities = level == 'CLASS' and len(members) == 2 and all(model.roles.get(m, {}).get('role') == 'ENTITY' for m in members) and all(
                set(e['edge_types']) <= {'FIELD_TYPE', 'GENERIC_TYPE', 'METHOD_CALL', 'PARAMETER_TYPE', 'RETURN_TYPE'} for c in listed for e in c['edges'])
            severity = 'LOW' if entities else 'HIGH' if (len(crossing) > 1 if level == 'CLASS' else True) or len(layers) > 1 else 'MEDIUM'
            group = dict(id=stable_id('cycle-group', level + '|'.join(members)), level=level, members=members, size=len(members),
                internal_edge_count=sub.number_of_edges(), cycles=listed, cycle_count_listed=len(listed),
                enumeration_truncated=len(cycles) > cap or len(members) > 60, max_cycle_length=max_length,
                packages=crossing, layers=layers, severity=severity, expected_entity_association=entities,
                overlapping=len(listed) > 1, cut_candidates=_cut_candidates(model, graph, members, [c['members'] for c in listed], level),
                explanation=_group_explanation(level, members, listed, crossing, layers, entities))
            out.append(group)
    return dict(groups=out, class_group_count=sum(g['level'] == 'CLASS' for g in out),
        package_group_count=sum(g['level'] == 'PACKAGE' for g in out), nested_or_self_references_ignored=self_refs,
        method=dict(algorithm='Strongly connected components (Tarjan, networkx) on the directed dependency graph; elementary cycles '
            f'enumerated per component with length <= {max_length}, at most {cap} per component.',
            nested_classes='Nested class = an inner, anonymous or local class; it is folded into its top-level class first.',
            self_references='Self reference = a class or package referring to itself; it is not a cycle and is excluded.'),
        runtime_included=model.runtime is not None)


def _group_explanation(level, members, listed, crossing, layers, entities):
    kind = 'classes' if level == 'CLASS' else 'packages'
    technical = (f"{len(members)} {kind} form one strongly connected component ({len(listed)} elementary cycle"
                 f"{'s' if len(listed) != 1 else ''} listed)" + (f", spanning packages {', '.join(crossing)}" if level == 'CLASS' and len(crossing) > 1 else '') +
                 (f" and layers {', '.join(l.lower() for l in layers)}" if len(layers) > 1 else '') + '.')
    if entities:
        plain = (f"{short(members[0])} and {short(members[1])} are database entities that refer to each other. This is usually an "
                 "intentional two-way relationship (for example a JPA association), but it still ties the two together.")
    elif len(listed) > 1:
        plain = (f"{len(members)} {kind} are tangled in {len(listed)} overlapping loops. Breaking one loop may leave the others; "
                 "the suggested cuts below show which dependency breaks the most loops.")
    else:
        plain = listed[0]['explanation']['plain'] if listed else f'{len(members)} {kind} depend on each other in a loop.'
    return dict(technical=technical, plain=plain)


def membership(analysis: dict) -> dict[str, list[str]]:
    """Map node id -> ids of cycle groups it belongs to."""
    out: dict[str, list[str]] = {}
    for group in analysis['groups']:
        for member in group['members']:
            out.setdefault(member, []).append(group['id'])
    return out
