"""WP4: specific technical-debt findings. Every finding names its class/method/edge, the measured value,
the documented threshold, the evidence and a suggested action. No currency or time estimates."""
from __future__ import annotations

from collections import Counter, defaultdict

from app.services.graph import stable_id
from .cycles import analyse as analyse_cycles
from .lifecycle import evaluate as evaluate_lifecycle, load_rules as load_lifecycle_rules
from .metrics import compute as compute_metrics, layer_violations, load_debt_rules
from .roles import LAYER_PLAIN, method_label, short
from . import debt_rates

SEVERITY_WEIGHT = {'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'INFO': 0}
COLLECTION_TYPES = ('java.util.List', 'java.util.Map', 'java.util.Set', 'java.util.Collection', 'java.util.ArrayList', 'java.util.HashMap',
    'java.util.HashSet', 'java.util.LinkedList', 'java.util.TreeMap', 'java.util.LinkedHashMap', 'java.util.Queue', 'java.util.Deque')
MUTATORS = {'add', 'addAll', 'put', 'putAll', 'remove', 'removeIf', 'removeAll', 'clear', 'set', 'offer', 'push', 'poll', 'computeIfAbsent', 'merge', 'replaceAll'}


def _finding(rule, severity, entity_id, entity_type, package, measured, threshold, technical, plain, evidence, nodes, related=None, action=None):
    return dict(id=stable_id('debt', rule['id'] + '|' + entity_id), rule_id=rule['id'], title=rule['title'], severity=severity,
        entity_id=entity_id, entity_type=entity_type, package=package, measured=measured, threshold=threshold,
        reason=rule['description'], explanation=dict(technical=technical, plain=plain), evidence=evidence,
        suggested_action=action or rule['action'], node_ids=nodes, related=related or {})


def detect(model, rules: dict | None = None, metrics: dict | None = None, cycles: dict | None = None, lifecycle: dict | None = None) -> dict:
    rules = rules or load_debt_rules()
    by_id = {r['id']: r for r in rules['rules']}
    thresholds = rules['metric_thresholds']
    cycles = cycles or analyse_cycles(model)
    metrics = metrics or compute_metrics(model, cycles, rules)
    lifecycle = lifecycle or evaluate_lifecycle(model, model.result.get('tech_inventory'))
    findings = []
    classes = {row['id']: row for row in metrics['classes']}
    populations = dict(methods=0, static_fields=0, edges=len(model.owner_edges),
        presentation_edges=sum(1 for (source, _), _kinds in model.owner_edges.items() if model.roles.get(source, {}).get('layer') == 'PRESENTATION'))

    # God class -----------------------------------------------------------------
    rule = by_id['DEBT-GOD-CLASS']
    for fqn, row in classes.items():
        over = {k: row['metrics'][k]['value'] for k in rule['metrics'] if row['metrics'][k]['indicator']['state'] == 'over'}
        if len(over) >= rule['min_signals']:
            labels = ', '.join(f"{metrics['definitions'][k]['label'].lower()} {v} (> {thresholds[k]['over']})" for k, v in over.items())
            findings.append(_finding(rule, rule['severity'], fqn, 'CLASS', row['package'], over, {k: thresholds[k]['over'] for k in over},
                f'{short(fqn)} exceeds {len(over)} size/coupling thresholds: {labels}.',
                f'{short(fqn)} does too many things at once, so almost any change touches it and it is risky to modify.',
                [dict(kind='METRIC', text=f"{metrics['definitions'][k]['label']}: {v}") for k, v in over.items()], [fqn]))
    # High coupling ---------------------------------------------------------------
    rule = by_id['DEBT-HIGH-COUPLING']
    for fqn, row in classes.items():
        total = row['metrics']['class.fan_in']['value'] + row['metrics']['class.fan_out']['value']
        if total > rule['threshold']:
            findings.append(_finding(rule, rule['severity'], fqn, 'CLASS', row['package'], {'fan_in+fan_out': total}, {'fan_in+fan_out': rule['threshold']},
                f"{short(fqn)}: fan-in {row['metrics']['class.fan_in']['value']} + fan-out {row['metrics']['class.fan_out']['value']} = {total} distinct classes (> {rule['threshold']}).",
                f'{short(fqn)} is connected to {total} other classes, so changes ripple widely.',
                [dict(kind='DEPENDENTS', text=', '.join(short(x) for x in row['metrics']['class.fan_in'].get('inputs', [])[:10])),
                 dict(kind='DEPENDENCIES', text=', '.join(short(x) for x in row['metrics']['class.fan_out'].get('inputs', [])[:10]))], [fqn]))
    # Cycle membership --------------------------------------------------------------
    rule = by_id['DEBT-CYCLE-MEMBER']
    for group in (g for g in cycles['groups'] if g['level'] == 'CLASS'):
        example = group['cycles'][0] if group['cycles'] else None
        loop = ' → '.join(short(m) for m in example['members'] + example['members'][:1]) if example else 'not enumerated'
        for member in group['members']:
            severity = 'LOW' if group['expected_entity_association'] else rule['severity']
            findings.append(_finding(rule, severity, member, 'CLASS', model.package(member), {'cycle_group_size': group['size']}, {'cycle_group_size': 1},
                f"{short(member)} is one of {group['size']} classes in a cyclic group; example loop {loop}.",
                f"{short(member)} cannot be changed or reused on its own because it is part of a loop of {group['size']} classes that depend on each other.",
                [dict(kind='CYCLE', text=e['references'][0]['text'] if e.get('references') else f"{short(e['source'])} → {short(e['target'])}") for e in (example['edges'] if example else [])],
                [member], dict(cycle_group_id=group['id']),
                action='Bidirectional entity association: confirm the owning side; usually acceptable.' if group['expected_entity_association'] else None))
    # Layer violations and skips ------------------------------------------------------
    for row in layer_violations(model, rules):
        rule = by_id['DEBT-LAYER-VIOLATION' if row['kind'] == 'VIOLATION' else 'DEBT-LAYER-SKIP']
        refs = model.references(row['source'], row['target'], limit=5)
        a, b = LAYER_PLAIN[row['source_layer']], LAYER_PLAIN[row['target_layer']]
        findings.append(_finding(rule, rule['severity'], row['source'] + ' -> ' + row['target'], 'DEPENDENCY', model.package(row['source']),
            {'from_layer': row['source_layer'], 'to_layer': row['target_layer']}, {'allowed_from_' + row['source_layer']: rules['layering'].get(row['source_layer'])},
            f"{short(row['source'])} ({model.roles[row['source']]['role'].lower()}, {a} layer) depends on {short(row['target'])} "
            f"({model.roles[row['target']]['role'].lower()}, {b} layer) via {', '.join(row['edge_types'])}.",
            (f"{short(row['source'])} reaches directly into {short(row['target'])}, skipping the service layer the application already has."
             if row['kind'] == 'SKIP' else
             f"{short(row['source'])} belongs to the {a} layer but depends on {short(row['target'])} in the {b} layer, which turns the intended direction of the architecture around."),
            [dict(kind=r['kind'], text=r['text'], line=r.get('line')) for r in refs] or [dict(kind='EDGE', text=', '.join(row['edge_types']))],
            [row['source'], row['target']]))
    # Method-level: size and complexity -------------------------------------------------
    size_rule, complex_rule = by_id['DEBT-LARGE-METHOD'], by_id['DEBT-COMPLEX-METHOD']
    size_limit, complex_limit = thresholds['class.max_method_size'], thresholds['class.max_method_complexity']
    for fqn in classes:
        for owner in [fqn] + model.nested_by_owner.get(fqn, []):
            for method in model.methods_of(owner):
                if 'code_length' not in method:
                    continue
                populations['methods'] += 1
                label = method_label(owner, method['name'])
                ident = owner + '#' + method['name'] + method['descriptor']
                where = f" (lines {method['line_range'][0]}-{method['line_range'][1]})" if method.get('line_range') else ''
                if method['code_length'] > size_limit['warn']:
                    severity = size_rule['severity_over'] if method['code_length'] > size_limit['over'] else size_rule['severity']
                    findings.append(_finding(size_rule, severity, ident, 'METHOD', model.package(fqn), {'bytecode_bytes': method['code_length']}, size_limit,
                        f"{label}{where} has {method['code_length']} bytes of bytecode (near above {size_limit['warn']}, over above {size_limit['over']}).",
                        f'{label} is a very long piece of code, which makes it hard to read, test and change safely.',
                        [dict(kind='BYTECODE', text=f"Code attribute length {method['code_length']} bytes")], [fqn]))
                complexity = method['branch_count'] + 1
                if complexity > complex_limit['warn']:
                    severity = 'HIGH' if complexity > complex_limit['over'] else complex_rule['severity']
                    findings.append(_finding(complex_rule, severity, ident + '#complexity', 'METHOD', model.package(fqn), {'branches+1': complexity}, complex_limit,
                        f"{label}{where} has {method['branch_count']} conditional branch/switch targets (complexity ≈ {complexity}).",
                        f'{label} has about {complexity} different paths through it; each one needs a test to be confident a change is safe.',
                        [dict(kind='BYTECODE', text=f"{method['branch_count']} branch instructions")], [fqn]))
    # Too many dependencies --------------------------------------------------------------
    rule = by_id['DEBT-TOO-MANY-DEPENDENCIES']
    for fqn, row in classes.items():
        metric = row['metrics']['class.dependency_count']
        if metric['indicator']['state'] == 'over':
            findings.append(_finding(rule, rule['severity'], fqn, 'CLASS', row['package'], {'dependency_count': metric['value']}, thresholds['class.dependency_count'],
                f"{short(fqn)} references {metric['value']} distinct types (over {thresholds['class.dependency_count']['over']}).",
                f"{short(fqn)} needs {metric['value']} other types to work, so it breaks whenever any of them changes.",
                [dict(kind='TYPES', text=', '.join(short(x) for x in metric.get('inputs', [])[:15]))], [fqn]))
    # Entity used directly by controller ------------------------------------------------------
    rule = by_id['DEBT-ENTITY-IN-CONTROLLER']
    for (source, target), kinds in sorted(model.owner_edges.items()):
        if model.roles.get(source, {}).get('layer') == 'PRESENTATION' and model.roles.get(target, {}).get('role') == 'ENTITY':
            refs = model.references(source, target, limit=6)
            findings.append(_finding(rule, rule['severity'], source + ' -> ' + target, 'DEPENDENCY', model.package(source), {'edge_types': dict(kinds)}, {'allowed': 'request/response models'},
                f"{short(source)} ({model.roles[source]['role'].lower()}) uses entity {short(target)} directly via {', '.join(sorted(kinds))}.",
                f'The web layer in {short(source)} works with the database record {short(target)} directly, so changing the database model can break the web pages or API.',
                [dict(kind=r['kind'], text=r['text'], line=r.get('line')) for r in refs], [source, target]))
    # Static mutable state -----------------------------------------------------------------
    rule = by_id['DEBT-STATIC-STATE']
    for fqn in classes:
        for owner in [fqn] + model.nested_by_owner.get(fqn, []):
            info = model.facts.get(owner)
            if not info or info['enum']:
                continue
            for field in info['fields']:
                if not field['static'] or field['synthetic'] or field['name'] in ('serialVersionUID', '$VALUES'):
                    continue
                populations['static_fields'] += 1
                mutated_in = sorted({m['name'] for m in info['methods'] if any(a['name'] == field['name'] and a['kind'] == 'putstatic' for a in m['field_access']) and m['name'] != '<clinit>'})
                if not field['final']:
                    why = f"static non-final field {short(owner)}.{field['name']} ({short(field['type'])})" + (f", assigned in {', '.join(mutated_in)}()" if mutated_in else '')
                elif field['type'].startswith(COLLECTION_TYPES):
                    mutated_in = sorted({m['name'] for m in info['methods'] if m['name'] != '<clinit>' and any(a['name'] == field['name'] and a['kind'] == 'getstatic' for a in m['field_access'])
                        and any(s['name'] in MUTATORS and s['owner'].startswith('java.util.') for s in m['invokes'])})
                    if not mutated_in:
                        continue
                    why = f"static final collection {short(owner)}.{field['name']} ({short(field['type'])}) is read and a collection mutator is called in {', '.join(mutated_in)}() (likely modified)"
                else:
                    continue
                findings.append(_finding(rule, rule['severity'], owner + '#' + field['name'], 'FIELD', model.package(fqn), {'static': True, 'final': field['final']}, {'allowed': 'immutable or instance state'},
                    why[0].upper() + why[1:] + '.',
                    f"{short(owner)} keeps shared data in '{field['name']}' that every request and thread sees, which causes hard-to-reproduce bugs and blocks running several instances.",
                    [dict(kind='FIELD', text=why)], [fqn]))
    # Deprecated API usage --------------------------------------------------------------------
    rule = by_id['DEBT-DEPRECATED-API']
    deprecated_internal = {(fqn, m['name'], m['descriptor']) for fqn, info in model.facts.items() for m in info['methods'] if m['deprecated'] or any(a['type'] == 'java.lang.Deprecated' for a in m['annotations'])}
    jdk = load_lifecycle_rules().get('deprecated_members', {}).get('members', [])
    for fqn in classes:
        sites = []
        for owner in [fqn] + model.nested_by_owner.get(fqn, []):
            for method in (model.facts.get(owner) or {}).get('methods', []):
                for site in method['invokes']:
                    if (site['owner'], site['name'], site['descriptor']) in deprecated_internal and model.owners.get(site['owner'], site['owner']) != fqn:
                        sites.append(dict(kind='DEPRECATED_INTERNAL', text=f"{method_label(owner, method['name'])} calls @Deprecated {method_label(site['owner'], site['name'])}", line=site.get('line')))
                    for member in jdk:
                        if site['owner'] == member['owner'] and member['name'] in ('*', site['name']):
                            sites.append(dict(kind='DEPRECATED_JDK', text=f"{method_label(owner, method['name'])} calls {method_label(site['owner'], site['name'])}: {member['note']}", line=site.get('line')))
        if sites:
            findings.append(_finding(rule, rule['severity'], fqn, 'CLASS', model.package(fqn), {'deprecated_call_sites': len(sites)}, {'deprecated_call_sites': 0},
                f'{short(fqn)} has {len(sites)} call site(s) to deprecated members.',
                f'{short(fqn)} relies on features that their authors have marked as outdated and may remove.', sites[:10], [fqn]))
    # Aging framework usage (links to WP1) -----------------------------------------------------------
    rule = by_id['DEBT-AGING-FRAMEWORK']
    for item in lifecycle['findings']:
        if item['status'] == 'current' or item['rule_id'] == 'java-class-target':
            continue
        for affected in item['affected_classes']:
            if affected['class_name'] not in classes:
                continue
            severity = rule['severity_over'] if item['status'] == 'end-of-life' else rule['severity']
            findings.append(_finding(rule, severity, affected['class_name'] + ' uses ' + item['rule_id'], 'CLASS', model.package(affected['class_name']),
                {'technology': item['technology'], 'status': item['status']}, {'status': 'current'},
                f"{short(affected['class_name'])} uses {item['technology']} ({item['status']}): {', '.join(affected['apis'][:4])}.",
                f"{short(affected['class_name'])} depends on {item['technology']}, which is {item['status'].replace('-', ' ')}; it will need rework when the technology is replaced.",
                [dict(kind='CALL_SITE', text=s['text'], line=s.get('line')) for s in affected['call_sites'][:8]], [affected['class_name']],
                dict(lifecycle_finding_id=item['id']), action=f"Move to {item['recommended_alternative']}. {item['migration_notes']}"))
    # Unobserved at runtime ------------------------------------------------------------------------
    rule = by_id['DEBT-UNOBSERVED']
    observed = model.observed_classes
    if observed is not None:
        for fqn in classes:
            if fqn not in observed and not any(n in observed for n in model.nested_by_owner.get(fqn, [])):
                findings.append(_finding(rule, rule['severity'], fqn, 'CLASS', model.package(fqn), {'observed_spans': 0}, {'observed_spans': 1},
                    f'No span in the selected runtime session(s) mapped to {fqn}.',
                    f'{short(fqn)} was not seen running during the recorded test session. That does not mean it is unused; it may simply not have been exercised.',
                    [dict(kind='RUNTIME', text='0 mapped spans in the selected sessions')], [fqn]))
    findings.sort(key=lambda f: (-SEVERITY_WEIGHT[f['severity']], f['rule_id'], f['entity_id']))
    return dict(findings=findings, packages=_package_summary(findings, metrics), rules=[dict(id=r['id'], title=r['title'], severity=r['severity'],
        description=r['description'], action=r['action']) for r in rules['rules']], thresholds=thresholds, rules_version=rules['rules_version'],
        counts=dict(Counter(f['severity'] for f in findings)), by_rule=dict(Counter(f['rule_id'] for f in findings)),
        rates=debt_rates.compute(model, findings, list(classes), populations, observed is not None, model.facts_available),
        runtime_included=observed is not None, facts_available=model.facts_available,
        effort_note='The debt index is a heuristic ordering aid with its inputs shown. It is not a time, cost or currency estimate.')


def _package_summary(findings, metrics):
    rows = defaultdict(lambda: Counter())
    for finding in findings:
        rows[finding['package']][finding['severity']] += 1
    sizes = {p['id']: p['class_count'] for p in metrics['packages']}
    out = []
    for package in sorted(set(rows) | set(sizes)):
        counts = rows[package]
        index = sum(SEVERITY_WEIGHT[s] * n for s, n in counts.items())
        classes = sizes.get(package, 0)
        out.append(dict(package=package, class_count=classes, counts=dict(counts), debt_index=index,
            debt_density=round(index / classes, 2) if classes else None,
            formula='debt index = 3 × HIGH + 2 × MEDIUM + 1 × LOW (+4 × CRITICAL, INFO = 0); density = index / classes',
            inputs=dict(counts) | {'classes': classes}))
    return sorted(out, key=lambda r: (-r['debt_index'], r['package']))
