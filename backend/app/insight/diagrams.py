"""WP2: high-level (HLD) and low-level (LLD) architecture diagram models, plus sequence flows.

Everything is derived: layers from roles (annotation/type evidence), external systems from library
references and persistence/messaging roles, counts from the typed dependency graph and optional runtime
evidence. The frontend only lays out and draws this model.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .callgraph import method_key
from .entrypoints import describe
from .roles import LAYER_LABEL, LAYER_ORDER, LAYER_PLAIN, method_label, short

EXTERNALS = {
    'DATABASE': dict(label='Database', prefixes=('org.springframework.data.', 'javax.persistence.', 'jakarta.persistence.', 'java.sql.', 'javax.sql.',
        'org.hibernate.', 'org.springframework.jdbc.', 'org.springframework.orm.', 'org.jooq.', 'org.mybatis.', 'com.zaxxer.hikari.'),
        plain='A database the application reads and writes through JPA/JDBC.'),
    'MESSAGE_BROKER': dict(label='Message broker', prefixes=('org.springframework.kafka.', 'org.apache.kafka.', 'javax.jms.', 'jakarta.jms.',
        'org.springframework.jms.', 'com.rabbitmq.', 'org.springframework.amqp.', 'software.amazon.awssdk.services.sqs.', 'io.awspring.'),
        plain='A message broker the application publishes to or consumes from.'),
    'HTTP_CLIENT': dict(label='Other HTTP services', prefixes=('org.springframework.web.client.', 'org.springframework.web.reactive.function.client.',
        'java.net.http.', 'okhttp3.', 'org.apache.http.', 'org.apache.hc.', 'javax.ws.rs.client.', 'jakarta.ws.rs.client.', 'feign.', 'org.springframework.cloud.openfeign.'),
        plain='Other web services this application calls over HTTP.'),
}
MAX_CHIPS = 12


def layer_of(model, fqn: str) -> str:
    return model.roles.get(fqn, {}).get('layer', 'SUPPORT')


def externals(model) -> dict[str, dict]:
    """Detected external systems with the classes and library types that evidence them."""
    found: dict[str, dict] = {}
    refs: dict[str, dict[str, set]] = {k: defaultdict(set) for k in EXTERNALS}
    for edge in model.external_edges:
        for key, spec in EXTERNALS.items():
            if edge['target'].startswith(spec['prefixes']):
                refs[key][model.owners.get(edge['source'], edge['source'])].add(edge['target'])
    for key, spec in EXTERNALS.items():
        classes = refs[key]
        runtime = [d for d in (model.runtime or {}).get('database', [])] if key == 'DATABASE' else []
        roles = [c for c, r in model.roles.items() if model.owners.get(c, c) == c and (
            (key == 'DATABASE' and r['role'] in ('REPOSITORY', 'ENTITY')) or (key == 'MESSAGE_BROKER' and r['role'] == 'LISTENER'))]
        members = sorted(set(classes) | set(roles))
        if not members and not runtime:
            continue
        by_layer = Counter(layer_of(model, c) for c in members)
        found[key] = dict(id='external:' + key, key=key, label=spec['label'], plain=spec['plain'], classes=members, class_count=len(members), by_layer=dict(by_layer),
            types=sorted({t for c in classes.values() for t in c})[:12],
            runtime_calls=sum(d.get('call_count', 0) for d in runtime), runtime_resources=sorted({d['resource'] for d in runtime if d.get('resource')}),
            evidence=[f"{short(c)} references {', '.join(short(t) for t in sorted(classes[c])[:3])}" for c in members[:6] if c in classes] +
                     ([f"{len(roles)} classes with role evidence ({'repository/entity' if key == 'DATABASE' else 'listener'})"] if roles else []))
    return found


def hld(model) -> dict:
    if not model.facts_available and not model.classes:
        return dict(status='NOT_AVAILABLE', reason='No classes in this analysis.')
    layers: dict[str, dict] = {}
    for fqn in sorted(model.classes):
        if model.owners.get(fqn, fqn) != fqn:
            continue
        layer = layer_of(model, fqn)
        item = layers.setdefault(layer, dict(id='layer:' + layer, layer=layer, label=LAYER_LABEL[layer], plain=LAYER_PLAIN[layer], classes=[], roles=Counter(), packages=Counter()))
        item['classes'].append(fqn)
        item['roles'][model.roles[fqn]['role']] += 1
        item['packages'][model.package(fqn)] += 1
    edges: dict[tuple[str, str], dict] = {}
    for (s, t), kinds in model.owner_edges.items():
        a, b = layer_of(model, s), layer_of(model, t)
        if a == b:
            continue
        edge = edges.setdefault((a, b), dict(source='layer:' + a, target='layer:' + b, class_pairs=0, references=0, runtime_calls=0, samples=[]))
        edge['class_pairs'] += 1
        edge['references'] += sum(kinds.values())
        edge['runtime_calls'] += model.runtime_calls.get((s, t), 0)
        if len(edge['samples']) < 3:
            edge['samples'].append(f'{short(s)} → {short(t)}')
    ext = externals(model)
    entry_groups: dict[str, list] = defaultdict(list)
    for entry in model.entry_points['items']:
        if entry['kind'] != 'LIFECYCLE_CALLBACK':
            entry_groups[entry['kind']].append(entry)
    ext_edges = []
    for key, system in ext.items():
        for layer, count in system['by_layer'].items():
            if layer in layers:
                ext_edges.append(dict(source='layer:' + layer, target=system['id'], class_pairs=count, references=count, runtime_calls=system['runtime_calls'] if layer == 'DATA_ACCESS' else 0,
                    samples=[short(c) for c in system['classes'] if layer_of(model, c) == layer][:3]))
    for edge in list(edges.values()) + ext_edges:
        edge['observed'] = edge['runtime_calls'] > 0
        edge['id'] = edge['source'] + '->' + edge['target']
        src, tgt = edge['source'].split(':')[1], edge['target'].split(':')[1]
        edge['against_layering'] = edge['target'].startswith('layer:') and LAYER_ORDER.index(src) > LAYER_ORDER.index(tgt) and src in ('DATA_ACCESS', 'DOMAIN') and tgt in ('PRESENTATION', 'SERVICE')
        edge['label'] = f"{edge['class_pairs']} dependencies" + (f" · {edge['runtime_calls']} runtime calls" if edge['runtime_calls'] else '')
        edge['explanation'] = (f"{edge['class_pairs']} class-to-class dependencies from {LAYER_PLAIN.get(src, src.lower())} to {tgt.lower().replace('_', ' ') if edge['target'].startswith('external') else LAYER_PLAIN.get(tgt, tgt)}"
            f" (e.g. {', '.join(edge['samples'])}); " + (f"{edge['runtime_calls']} calls observed at runtime." if edge['observed'] else 'not observed at runtime (static only).' if model.runtime else 'no runtime session selected.'))
    ordered = [layers[l] for l in LAYER_ORDER if l in layers]
    return dict(status='AVAILABLE', level='HLD',
        entry_points=[dict(id='entries:' + kind, kind=kind, count=len(items), label=kind.replace('_', ' ').lower(), examples=[describe(e) for e in items[:3]]) for kind, items in sorted(entry_groups.items())],
        layers=[dict(id=l['id'], layer=l['layer'], label=l['label'], plain=l['plain'], class_count=len(l['classes']), roles=dict(l['roles']),
            packages=[dict(id=p, count=c) for p, c in l['packages'].most_common()], package_count=len(l['packages'])) for l in ordered],
        externals=[{k: v for k, v in s.items() if k != 'classes'} | dict(class_count=s['class_count']) for s in ext.values()],
        edges=sorted(list(edges.values()) + ext_edges, key=lambda e: e['id']), runtime_included=model.runtime is not None,
        how_to_read=['Each wide box is an architecture layer; its class count and role mix come from annotations and type hierarchy, not from package names alone.',
            'Boxes at the top are where requests, messages and timers enter the application; boxes at the bottom are external systems detected from library use.',
            'An arrow points from the layer that depends to the layer it depends on; the label counts distinct class-to-class dependencies.',
            'Solid green arrows were also observed at runtime (call counts shown); dashed grey arrows exist in the code only. Red arrows point against the layering and deserve review.',
            'Click a box or arrow for its detail; “Expand” shows the packages inside a layer. The diagram never draws individual classes at this level.'],
        limitations=['Layer assignment depends on role evidence; classes without evidence are listed under “Supporting code”.',
            'External systems are inferred from library references, not from configuration or network traffic.'])


def lld(model, package: str) -> dict:
    members = sorted(c for c in model.packages.get(package, []) if model.owners.get(c, c) == c)
    if not members:
        return dict(status='NOT_AVAILABLE', reason=f'{package} is not a package of this analysis.')
    names = set(members)
    entries = [e for e in model.entry_points['items'] if e['handler_class'] in names and e['kind'] != 'LIFECYCLE_CALLBACK']
    classes = []
    for fqn in members:
        role = model.roles[fqn]
        info = model.facts.get(fqn) or {}
        table = next((a['values'].get('name') for a in info.get('annotations', []) if a['type'].endswith('persistence.Table')), None)
        classes.append(dict(id=fqn, name=short(fqn), role=role['role'], layer=role['layer'], reason=role['reason'], methods=len(model.methods_of(fqn)), table=table or None,
            entry_points=[dict(id=e['id'], text=describe(e), method=e['handler_method']) for e in entries if e['handler_class'] == fqn],
            observed=None if model.observed_classes is None else fqn in model.observed_classes))
    edges = []
    for (s, t), kinds in sorted(model.owner_edges.items()):
        if s in names and t in names:
            runtime = model.runtime_calls.get((s, t), 0)
            edges.append(dict(id=f'{s}->{t}', source=s, target=t, edge_types=dict(kinds), references=sum(kinds.values()), runtime_calls=runtime,
                observed=runtime > 0, label=', '.join(f'{k.lower().replace("_", " ")} ×{v}' for k, v in sorted(kinds.items()))))
    tables = [dict(id='table:' + c['table'], table=c['table'], entity=c['id'], source='STATIC @Table annotation') for c in classes if c['table']]
    runtime_db = [dict(id=f"db:{d.get('resource')}:{d.get('operation')}:{d.get('caller')}", table=d.get('resource'), operation=d.get('operation'), caller=d.get('caller'), calls=d.get('call_count', 0), source='RUNTIME')
        for d in (model.runtime or {}).get('database', []) if d.get('caller') in names and d.get('resource')]
    return dict(status='AVAILABLE', level='LLD', package=package, classes=classes, edges=edges, tables=tables, runtime_tables=runtime_db,
        entry_points=[dict(id=e['id'], text=describe(e), handler=method_label(e['handler_class'], e['handler_method'])) for e in entries],
        how_to_read=['Boxes are the top-level classes of this package, placed by architecture layer; nested classes are folded into their owner.',
            'Entries inside a box are the methods that start work (routes, listeners, jobs). Arrows point from dependent to dependency; the label lists typed references.',
            'Solid green arrows were observed at runtime; dashed arrows are static only. Table names come from @Table annotations (static) and from database spans (runtime).'],
        limitations=['Database tables are only known where entities carry @Table(name=…) or runtime database spans exist.'])


def sequence_static(model, entry_id: str, depth: int = 4, limit: int = 40) -> dict:
    """Call flow from an entry point in source order, from the static call graph. Not observed behaviour."""
    entry = next((e for e in model.entry_points['items'] if e['id'] == entry_id), None)
    if not entry:
        return dict(status='NOT_AVAILABLE', reason='Entry point not found.')
    graph = model.callgraph
    start = method_key(entry['handler_class'], entry['handler_method'], entry['handler_descriptor'])
    messages, participants, seen = [], [], set()

    def participant(fqn):
        owner = model.owners.get(fqn, fqn)
        if owner not in participants:
            participants.append(owner)
        return owner

    def walk(key, level):
        if level >= depth or len(messages) >= limit:
            return
        caller = participant(key.split('#')[0])
        method = graph.methods[key]
        sites = [(site.get('line') or 0, site['owner'], site['name'], site['descriptor'], site['kind']) for site in method.get('invokes', []) if site['owner'] in model.facts]
        sites += [(c['line'] or 0, c['target'].split('#')[0], c['target'].split('#')[1].split('(')[0], '(' + c['target'].split('(', 1)[1], 'lambda') for c in graph.calls.get(key, []) if c['kind'] == 'lambda']
        for line, owner, name, descriptor, kind in sorted(sites, key=lambda x: x[0]):
            if (key, owner, name) in seen or len(messages) >= limit:
                continue
            seen.add((key, owner, name))
            callee = participant(owner)
            messages.append(dict(order=len(messages) + 1, source=caller, target=callee, label=('new ' + short(callee)) if name == '<init>' else name + '()', line=line or None, kind=kind, origin='static',
                inherited_from_library=not graph.resolve(owner, name, descriptor, kind) and kind != 'lambda'))
            for target in graph.resolve(owner, name, descriptor, kind)[:3]:
                walk(target, level + 1)

    participant(entry['handler_class'])
    walk(start, 0)
    return dict(status='AVAILABLE', origin='STATIC', entry=describe(entry), participants=[dict(id=p, label=short(p), role=model.roles.get(p, {}).get('role')) for p in participants], messages=messages,
        note='Built from bytecode call sites in source order (depth ≤ %d, ≤ %d messages). It shows what the code can do, not what was observed; library calls are omitted.' % (depth, limit))


def sequence_runtime(events: list[dict], model, http_method: str | None, route: str | None, limit: int = 60) -> dict:
    """First matching trace, ordered by start time along parent/child links."""
    from app.services.runtime.mapping import map_class
    classes = model.classes
    by_trace: dict[tuple, list] = defaultdict(list)
    for event in events:
        by_trace[(event['session_id'], event['trace_id'])].append(event)
    for key, group in sorted(by_trace.items()):
        root = next((e for e in group if e.get('event_type') == 'HTTP_SERVER'), None)
        if route and (not root or root.get('http_route') != route or (http_method and root.get('http_method') != http_method)):
            continue
        spans = {e['span_id']: e for e in group}
        children: dict[str | None, list] = defaultdict(list)
        for e in group:
            children[e.get('parent_span_id') if e.get('parent_span_id') in spans else None].append(e)
        participants, messages = [], []

        def who(e):
            mapped = map_class(e.get('class_name'), classes)['static_id']
            label = mapped or e.get('class_name') or e.get('database_table') or e.get('event_type')
            owner = model.owners.get(mapped, mapped) if mapped else label
            if owner not in participants:
                participants.append(owner)
            return owner

        def walk(parent_participant, e):
            if len(messages) >= limit:
                return
            me = who(e)
            messages.append(dict(order=len(messages) + 1, source=parent_participant, target=me, label=(e.get('method_name') or e.get('database_operation') or e.get('http_route') or e['event_type']) + '()' if e.get('method_name') else (e.get('database_operation') or e.get('http_route') or e['event_type']),
                duration_ms=e.get('duration_ms'), origin='runtime', error=bool(e.get('error')), span_id=e['span_id']))
            for child in sorted(children.get(e['span_id'], []), key=lambda c: c['timestamp']):
                walk(me, child)

        roots = sorted(children.get(None, []), key=lambda e: e['timestamp'])
        if not roots:
            continue
        top = who(roots[0])
        for r in roots[:1]:
            for child in sorted(children.get(r['span_id'], []), key=lambda c: c['timestamp']):
                walk(top, child)
        return dict(status='AVAILABLE', origin='RUNTIME', entry=f"{(root or {}).get('http_method', '')} {(root or {}).get('http_route', '')}".strip() or roots[0].get('event_type'),
            participants=[dict(id=p, label=short(p) if p in classes else p, role=model.roles.get(p, {}).get('role')) for p in participants], messages=messages,
            trace=dict(session_id=key[0], trace_id=key[1]), note='Built from one recorded trace (spans ordered by start time along parent links). One trace is an example, not every possible path.')
    return dict(status='NOT_AVAILABLE', reason='No retained trace matches this entry point in the selected sessions.')


def layer_detail(model, identity: str, debt: dict) -> dict:
    layer = identity.split(':', 1)[1]
    members = sorted(c for c in model.classes if model.owners.get(c, c) == c and layer_of(model, c) == layer)
    if not members:
        return dict(kind='UNKNOWN', id=identity, reason=f'No classes are in the {layer} layer.')
    roles = Counter(model.roles[c]['role'] for c in members)
    outgoing, incoming = Counter(), Counter()
    for (s, t), kinds in model.owner_edges.items():
        a, b = layer_of(model, s), layer_of(model, t)
        if a == layer and b != layer:
            outgoing[b] += 1
        if b == layer and a != layer:
            incoming[a] += 1
    packages = Counter(model.package(c) for c in members)
    own_debt = [f for f in debt['findings'] if set(f['node_ids']) & set(members)]
    return dict(kind='LAYER', id=identity, name=LAYER_LABEL[layer], breadcrumb=[dict(id='system', label='Application'), dict(id=identity, label=LAYER_PLAIN[layer])],
        what=dict(plain=f"{LAYER_PLAIN[layer].capitalize()} code: {len(members)} classes ({', '.join(f'{v} {k.lower()}' for k, v in roles.most_common())}).", reason='; '.join(sorted({model.roles[c]['reason'] for c in members})[:3]), role=layer, evidence='ROLE_AGGREGATE'),
        size=dict(classes=len(members), packages=len(packages)), classes=[dict(id=c, name=short(c), role=model.roles[c]['role']) for c in members[:200]],
        depends_on=[dict(id='layer:' + k, name=LAYER_PLAIN[k], reference_count=v, edge_types={}, runtime_calls=0) for k, v in outgoing.most_common()],
        depended_on_by=[dict(id='layer:' + k, name=LAYER_PLAIN[k], reference_count=v, edge_types={}, runtime_calls=0) for k, v in incoming.most_common()],
        packages=[dict(id=p, count=c) for p, c in packages.most_common()], debt=own_debt[:30],
        summary=f"The {LAYER_PLAIN[layer]} layer has {len(members)} classes in {len(packages)} packages; {sum(outgoing.values())} dependencies leave it and {sum(incoming.values())} arrive from other layers. {len(own_debt)} debt findings touch it.")


def external_detail(model, identity: str) -> dict:
    key = identity.split(':', 1)[1]
    system = externals(model).get(key)
    if not system:
        return dict(kind='UNKNOWN', id=identity, reason='External system not detected.')
    return dict(kind='EXTERNAL', id=identity, name=system['label'], breadcrumb=[dict(id='system', label='Application'), dict(id=identity, label=system['label'])],
        what=dict(plain=system['plain'], reason='; '.join(system['evidence'][:3]), role=key, evidence='LIBRARY_REFERENCE'),
        size=dict(classes=system['class_count']), classes=[dict(id=c, name=short(c), role=model.roles.get(c, {}).get('role', 'UNKNOWN')) for c in system['classes'][:100]],
        external_dependencies=[dict(id=t, reference_count=1) for t in system['types']], coverage=dict(status='AVAILABLE' if system['runtime_calls'] else 'NOT_AVAILABLE',
            reason='No database spans in the selected sessions.', observed=system['runtime_calls'], total=system['runtime_calls'], note=', '.join(system['runtime_resources'][:8])),
        summary=f"{system['label']} is inferred from {system['class_count']} application classes ({'; '.join(system['evidence'][:2])}).")
