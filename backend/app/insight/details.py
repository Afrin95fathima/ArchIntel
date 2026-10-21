"""WP3: node details for system, package, class and method, plus 'why is this connected'."""
from __future__ import annotations

from collections import Counter

from .callgraph import method_key
from .cycles import analyse as analyse_cycles
from .entrypoints import describe
from .graphview import unresolved
from .lifecycle import evaluate as evaluate_lifecycle
from .roles import LAYER_PLAIN, method_label, short


def key_label(key: str) -> str:
    owner, _, rest = key.partition('#')
    return method_label(owner, rest.split('(')[0])



def _package_plain(model, identity: str, members: set[str]) -> str:
    """Say 'mostly' only when one layer holds more than half of the classes; otherwise state the real split."""
    (layer, count), *rest = Counter(model.roles[m]['layer'] for m in members).most_common()
    total = len(members)
    if count * 2 > total:
        return f"Package {identity} mostly holds {LAYER_PLAIN[layer]} code ({count} of {total} classes)."
    return f"Package {identity} mixes layers: the largest group is {LAYER_PLAIN[layer]} code ({count} of {total} classes), the rest is spread over {len(rest)} other {'layer' if len(rest) == 1 else 'layers'}."

def _neighbours(model, members: set[str], outgoing: bool, group_by_package: bool = False) -> list[dict]:
    counts: dict[str, Counter] = {}
    for (s, t), kinds in model.owner_edges.items():
        a, b = (s, t) if outgoing else (t, s)
        if a in members and b not in members:
            key = model.package(b) if group_by_package else b
            counts.setdefault(key, Counter()).update(kinds)
    rows = [dict(id=k, name=k if group_by_package else short(k), edge_types=dict(v), reference_count=sum(v.values()),
        runtime_calls=sum(c for (s, t), c in model.runtime_calls.items() if (s in members and (model.package(t) if group_by_package else t) == k) or
                         (t in members and (model.package(s) if group_by_package else s) == k)))
        for k, v in counts.items()]
    return sorted(rows, key=lambda r: (-r['reference_count'], r['id']))


def _external(model, members: set[str]) -> list[dict]:
    counts: Counter = Counter()
    for edge in model.external_edges:
        if model.owners.get(edge['source'], edge['source']) in members:
            counts[edge['target']] += 1
    return [dict(id=k, reference_count=v) for k, v in counts.most_common(30)]


def _coverage(model, members: set[str]) -> dict:
    observed = model.observed_classes
    if observed is None:
        return dict(status='NOT_AVAILABLE', reason='No runtime session selected. Choose a session to see which classes and methods were observed.')
    seen = sorted(m for m in members if m in observed or any(n in observed for n in model.nested_by_owner.get(m, [])))
    return dict(status='AVAILABLE', observed_classes=seen, unobserved_classes=sorted(members - set(seen)), observed=len(seen), total=len(members),
        note='Unobserved means not seen in the selected sessions; it does not mean unused.')


def _summary(kind, name, role, size_text, deps, dependents, cycles, entries, debt, aging, coverage):
    parts = [f"{name} is {'a package' if kind == 'PACKAGE' else 'a class'}" + (f" whose role is {role['role'].lower().replace('_', ' ')} ({role['reason']})" if role else '') + f"; {size_text}."]
    if deps or dependents:
        parts.append(f"It depends on {len(deps)} {'package' if kind == 'PACKAGE' else 'class'}{'es' if len(deps) != 1 and kind != 'PACKAGE' else 's' if len(deps) != 1 else ''}"
                     + (f" (most: {deps[0]['name']}, {deps[0]['reference_count']} references)" if deps else '') +
                     f" and {len(dependents)} depend on it" + (f" (most: {dependents[0]['name']})" if dependents else '') + '.')
    else:
        parts.append(f'{name} has no dependencies to or from other application classes.')
    if cycles:
        parts.append(f"It is part of {len(cycles)} cyclic group{'s' if len(cycles) != 1 else ''} (largest: {max(c['size'] for c in cycles)} members).")
    if entries:
        parts.append(f"It declares {len(entries)} entry point{'s' if len(entries) != 1 else ''}, e.g. {entries[0]['description']}.")
    if debt:
        severities = Counter(f['severity'] for f in debt)
        parts.append('Technical debt: ' + ', '.join(f'{v} {k.lower()}' for k, v in severities.most_common()) + ' finding(s).')
    if aging:
        parts.append('Uses ' + ', '.join(f"{a['technology']} ({a['status']})" for a in aging[:3]) + '.')
    if coverage.get('status') == 'AVAILABLE':
        parts.append(f"Runtime: {coverage['observed']} of {coverage['total']} classes observed in the selected sessions.")
    return ' '.join(parts)


def node(model, identity: str, debt: dict) -> dict:
    """identity: '' or 'system' | package name | class fqn | 'Class#method(desc)'."""
    if identity.startswith('layer:'):
        from .diagrams import layer_detail
        return layer_detail(model, identity, debt)
    if identity.startswith('external:'):
        from .diagrams import external_detail
        return external_detail(model, identity)
    cycles = analyse_cycles(model)
    lifecycle = evaluate_lifecycle(model, model.result.get('tech_inventory'))
    entries = model.entry_points['items']
    if identity in ('', 'system'):
        roles = Counter(r['role'] for f, r in model.roles.items() if model.owners.get(f, f) == f)
        return dict(kind='SYSTEM', id='system', name='Application', breadcrumb=[dict(id='system', label='Application')],
            size=dict(packages=len(model.packages), classes=sum(1 for f in model.classes if model.owners.get(f, f) == f), nested_classes=sum(1 for f in model.classes if model.owners.get(f, f) != f)),
            roles=dict(roles), entry_points=len(entries), cycle_groups=len(cycles['groups']), debt_findings=len(debt['findings']),
            external=unresolved(model)['total'],
            summary=f"The application has {len(model.packages)} packages and {sum(roles.values())} top-level classes; roles: " +
                ', '.join(f'{v} {k.lower().replace("_", " ")}' for k, v in roles.most_common()) + f". It declares {len(entries)} entry points.")
    if '#' in identity:
        return _method(model, identity, debt, entries)
    if identity in model.packages and identity not in model.classes:
        members = {model.owners.get(c, c) for c in model.packages[identity]} & set(model.classes)
        deps, dependents = _neighbours(model, members, True, True), _neighbours(model, members, False, True)
        class_deps = _neighbours(model, members, True)
        group_cycles = [g for g in cycles['groups'] if identity in g['members'] or set(g['members']) & members]
        own_entries = [dict(e, description=describe(e)) for e in entries if e['handler_class'] in members]
        own_debt = [f for f in debt['findings'] if f['package'] == identity]
        aging = [dict(technology=f['technology'], status=f['status'], id=f['id'], classes=[c['class_name'] for c in f['affected_classes'] if c['class_name'] in members])
            for f in lifecycle['findings'] if f['rule_id'] != 'java-class-target' and any(c['class_name'] in members for c in f['affected_classes'])]
        roles = Counter(model.roles[m]['role'] for m in members)
        coverage = _coverage(model, members)
        size_text = f"{len(members)} top-level classes ({', '.join(f'{v} {k.lower()}' for k, v in roles.most_common())})"
        return dict(kind='PACKAGE', id=identity, name=identity, breadcrumb=[dict(id='system', label='Application'), dict(id=identity, label=identity)],
            what=dict(roles=dict(roles), plain=_package_plain(model, identity, members)),
            size=dict(classes=len(members), methods=sum(len(model.methods_of(m)) for m in members)),
            classes=[dict(id=m, name=short(m), role=model.roles[m]['role']) for m in sorted(members)],
            depends_on=deps, depended_on_by=dependents, top_class_dependencies=class_deps[:10], external_dependencies=_external(model, members),
            cycles=[dict(id=g['id'], level=g['level'], size=g['size'], members=g['members']) for g in group_cycles],
            entry_points=own_entries, coverage=coverage, debt=own_debt, aging=aging,
            summary=_summary('PACKAGE', identity, None, size_text, deps, dependents, group_cycles, own_entries, own_debt, aging, coverage))
    if identity not in model.classes:
        return dict(kind='UNKNOWN', id=identity, reason=f'{identity} is not a class, package or method of this analysis.', **_external_info(model, identity))
    fqn = model.owners.get(identity, identity)
    members = {fqn}
    role = model.roles[fqn]
    deps, dependents = _neighbours(model, members, True), _neighbours(model, members, False)
    group_cycles = [g for g in cycles['groups'] if fqn in g['members']]
    own_entries = [dict(e, description=describe(e)) for e in entries if model.owners.get(e['handler_class'], e['handler_class']) == fqn]
    own_debt = [f for f in debt['findings'] if fqn in f['node_ids']]
    aging = [dict(technology=f['technology'], status=f['status'], id=f['id'], apis=next(c['apis'] for c in f['affected_classes'] if c['class_name'] == fqn))
        for f in lifecycle['findings'] if f['rule_id'] != 'java-class-target' and any(c['class_name'] == fqn for c in f['affected_classes'])]
    methods = [dict(id=method_key(owner, m['name'], m.get('descriptor', '')), name=m['name'], label=method_label(owner, m['name']), owner=owner,
        signature=m.get('signature'), visibility=m.get('visibility'), static=m.get('static'), bytecode_size=m.get('code_length'),
        complexity=(m['branch_count'] + 1) if 'branch_count' in m else None, annotations=[a['type'] if isinstance(a, dict) else a for a in m.get('annotations', [])],
        entry_point=next((describe(e) for e in entries if e['handler_class'] == owner and e['handler_method'] == m['name'] and e['handler_descriptor'] == m.get('descriptor')), None))
        for owner in [fqn] + model.nested_by_owner.get(fqn, []) for m in model.methods_of(owner)]
    coverage = _coverage(model, members)
    info = model.facts.get(fqn) or {}
    size_text = f"{len([m for m in methods if m['owner'] == fqn])} methods, {len([f for f in info.get('fields', []) if not f['synthetic']]) if info else model.classes[fqn].get('field_count', 0)} fields" + (
        f", {len(model.nested_by_owner.get(fqn, []))} nested classes" if model.nested_by_owner.get(fqn) else '')
    return dict(kind='CLASS', id=fqn, name=short(fqn), full_name=fqn, requested=identity,
        breadcrumb=[dict(id='system', label='Application'), dict(id=model.package(fqn), label=model.package(fqn)), dict(id=fqn, label=short(fqn))],
        what=dict(role=role['role'], layer=role['layer'], evidence=role['evidence'], reason=role['reason'], plain=f"{short(fqn)} {role['plain']}."),
        size=dict(methods=len([m for m in methods if m['owner'] == fqn]), fields=len([f for f in info.get('fields', []) if not f['synthetic']]) if info else model.classes[fqn].get('field_count'),
            bytecode_size=sum(m['bytecode_size'] or 0 for m in methods if m['owner'] == fqn) if info else None, nested_classes=model.nested_by_owner.get(fqn, [])),
        fields=[dict(name=f['name'], type=f['type'], static=f['static'], annotations=[a['type'] for a in f['annotations']]) for f in info.get('fields', []) if not f['synthetic']],
        methods=methods, depends_on=deps, depended_on_by=dependents, external_dependencies=_external(model, members),
        cycles=[dict(id=g['id'], level=g['level'], size=g['size'], members=g['members']) for g in group_cycles],
        entry_points=own_entries, coverage=coverage, debt=own_debt, aging=aging,
        summary=_summary('CLASS', short(fqn), role, size_text, deps, dependents, group_cycles, own_entries, own_debt, aging, coverage))


def _external_info(model, identity):
    for category in unresolved(model)['categories']:
        for item in category['items']:
            if item['name'] == identity:
                return dict(external=item)
    return {}


def _method(model, identity, debt, entries):
    owner = identity.split('#', 1)[0]
    graph = model.callgraph
    method = graph.methods.get(identity)
    if not method:
        return dict(kind='UNKNOWN', id=identity, reason='Method not found in the bytecode facts of this analysis.')
    fqn = model.owners.get(owner, owner)
    calls = [dict(target=c['target'], label=key_label(c['target']), line=c['line'], resolution=c['resolution']) for c in graph.calls.get(identity, [])]
    external = [dict(owner=s['owner'], name=s['name'], line=s.get('line'), label=method_label(s['owner'], s['name'])) for s in method.get('invokes', []) if s['owner'] not in model.classes]
    callers = [dict(source=c['source'], label=key_label(c['source']), line=c['line']) for c in graph.callers(identity)]
    entry = next((dict(e, description=describe(e)) for e in entries if e['handler_class'] == owner and e['handler_method'] == method['name'] and e['handler_descriptor'] == method['descriptor']), None)
    label = method_label(owner, method['name'])
    return dict(kind='METHOD', id=identity, name=label, owner=fqn,
        breadcrumb=[dict(id='system', label='Application'), dict(id=model.package(fqn), label=model.package(fqn)), dict(id=fqn, label=short(fqn)), dict(id=identity, label=label)],
        signature=method['signature'], visibility=method['visibility'], static=method['static'], bytecode_size=method['code_length'],
        complexity=method['branch_count'] + 1, line_range=method.get('line_range'), annotations=[a['type'] for a in method['annotations']],
        entry_point=entry, calls=calls, external_calls=external[:40], called_by=callers,
        debt=[f for f in debt['findings'] if f['entity_id'].startswith(identity)],
        summary=f"{label} ({method['signature']}) has {method['code_length']} bytes of bytecode and about {method['branch_count'] + 1} paths; "
                f"it calls {len(calls)} application methods and {len(external)} library methods and is called from {len(callers)} application methods." +
                (f" It is an entry point: {entry['description']}." if entry else ''))


def connection(model, source: str, target: str) -> dict:
    """The concrete class-to-class references behind a class, package, layer or external-system edge."""
    if source.startswith('layer:') or target.startswith('layer:') or target.startswith('external:'):
        from .diagrams import layer_of, externals
        pairs = []
        if target.startswith('external:'):
            system = externals(model).get(target.split(':', 1)[1], {})
            members = [c for c in system.get('classes', []) if layer_of(model, c) == source.split(':', 1)[1]]
            return dict(level='EXTERNAL', source=source, target=target, pair_count=len(members), pairs=[dict(source=c, target=target, edge_types={}, references=[dict(kind='LIBRARY_REFERENCE', text=f"{short(c)} uses library types of this system", line=None)]) for c in members[:40]],
                explanation=f"{len(members)} classes in the {source.split(':', 1)[1].lower().replace('_', ' ')} layer use {system.get('label', 'this system')}.")
        a, b = source.split(':', 1)[1], target.split(':', 1)[1]
        pairs = sorted((s, t) for (s, t) in model.owner_edges if layer_of(model, s) == a and layer_of(model, t) == b)
        return dict(level='LAYER', source=source, target=target, pair_count=len(pairs), pairs=[dict(source=s, target=t, edge_types=dict(model.owner_edges[(s, t)]),
            references=model.references(s, t, limit=3)) for s, t in pairs[:40]], explanation=f"{len(pairs)} class-to-class dependencies from the {a.lower().replace('_', ' ')} layer to the {b.lower().replace('_', ' ')} layer.")
    if source in model.packages and source not in model.classes:
        pairs = sorted((s, t) for (s, t) in model.owner_edges if model.package(s) == source and model.package(t) == target)
        return dict(level='PACKAGE', source=source, target=target, pair_count=len(pairs), pairs=[dict(source=s, target=t,
            edge_types=dict(model.owner_edges[(s, t)]), references=model.references(s, t, limit=6)) for s, t in pairs[:40]],
            explanation=f"{len(pairs)} class-to-class dependencies from {source} to {target}.")
    s, t = model.owners.get(source, source), model.owners.get(target, target)
    refs = model.references(s, t, limit=60)
    kinds = dict(model.owner_edges.get((s, t), {}))
    return dict(level='CLASS', source=s, target=t, edge_types=kinds, references=refs, runtime_calls=model.runtime_calls.get((s, t), 0),
        explanation=(f"{short(s)} depends on {short(t)} through {sum(kinds.values())} typed references ({', '.join(kinds)})." if kinds else
            f'No static dependency from {short(s)} to {short(t)} was found.'),
        references_available=model.facts_available)
