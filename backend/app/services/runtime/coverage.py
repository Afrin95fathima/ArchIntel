"""Observation coverage, never code coverage or proof of unused code."""
from .entry_points import is_method_entry_point


def metric(observed, population, reason=None):
    if population is None:
        return dict(observed=None,total=None,percentage=None,status='UNAVAILABLE',reason=reason)
    return dict(observed=len(observed & population),total=len(population),
        percentage=round(100*len(observed & population)/len(population),2) if population else None,
        status='AVAILABLE' if population else 'NOT_APPLICABLE',reason=reason)


def calculate(static, graph, events=None):
    classes = {c['id'] for c in static['classes']}
    observed = {n['static_id'] for n in graph['nodes'] if n.get('static_id')}
    executable = {(e['source'],e['target']) for e in static['edges'] if e['dependency_type']=='METHOD_CALL'}
    calls = {(e['source'],e['target']) for e in graph['edges'] if e['dependency_type']=='METHOD_CALL'}
    domains = []
    for domain in static['domains']:
        members = set(domain['classes'])
        seen = members & observed
        domains.append(dict(id=domain['id'],name=domain['name'],observed=len(seen),total=len(members),
            state='UNOBSERVED' if not seen else 'OBSERVED' if seen==members else 'PARTIALLY_OBSERVED',
            unobserved_classes=sorted(members-seen)))
    from .mapping import map_method
    from collections import Counter
    method_states=Counter()
    by_class={c['id']:c for c in static['classes']}
    inventory_available=all('methods' in c and all(m.get('signature') for m in c['methods']) for c in static['classes'])
    method_population, entry_population, seen_methods = set(),set(),set()
    if inventory_available:
        for c in static['classes']:
            for m in c['methods']:
                # jQAssistant may attach inherited-reference stubs with a signature but no parsed name.
                if not m.get('name') or m['name'].startswith('<'): continue
                identity=(c['id'],m['signature'])
                method_population.add(identity)
                if is_method_entry_point(m.get('annotations',[])): entry_population.add(identity)
        for e in events or []:
            if not e.get('method_name'):continue
            mapped=map_method(e,by_class);method_states[mapped['state']]+=1
            if mapped['signature']:seen_methods.add((mapped['static_class'],mapped['signature']))
    return dict(classes=metric(observed,classes),dependencies=metric(calls,executable,'Distinct directed METHOD_CALL class pairs only.'),
        methods=metric(seen_methods,method_population if inventory_available else None,'Named declared methods only; inherited reference stubs excluded. Exact JVM descriptor or unique owner + method name; ambiguous overloads remain unobserved.' if inventory_available else 'Static snapshot has no reliable method identity inventory; run a new static analysis.'),
        entry_points=metric(seen_methods,entry_population if inventory_available else None,'Explicit supported method annotations only; inherited/composed routes may be absent.' if inventory_available else 'Static snapshot has no enumerated entry-point method inventory.'),
        domains=metric({d['id'] for d in domains if d['observed']},{d['id'] for d in domains}),domain_observations=domains,
        method_mapping_diagnostics=dict(method_states),
        unresolved_node_count=sum(not n.get('static_id') for n in graph['nodes']),missing_parent_count=graph['missing_parent_count'],
        note='Unobserved means not observed in selected sessions, never unused. Domain observation does not establish complete behavior coverage.')
