"""WP5: architecture metrics with formulas, inputs, plain meaning and threshold indicators.

Counted entities are top-level classes; nested/anonymous classes are folded into their owner.
Coupling counts distinct internal classes (Robert C. Martin's package metrics, class-count variant).
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import yaml

from .cycles import analyse as analyse_cycles
from .roles import short

RULES_PATH = Path(__file__).resolve().parent / 'rules' / 'debt-rules.yaml'
INPUT_LIMIT = 50

DEFINITIONS = {
    'class.fan_in': dict(label='Fan-in', formula='|{internal classes that depend on C}|',
        plain='How many other classes rely on this class. High fan-in means a change here can affect many places.'),
    'class.fan_out': dict(label='Fan-out', formula='|{internal classes C depends on}|',
        plain='How many other classes this class relies on. High fan-out means it breaks when any of them changes.'),
    'class.method_count': dict(label='Methods', formula='declared methods excluding synthetic, bridge and lambda methods',
        plain='How much behaviour the class contains.'),
    'class.field_count': dict(label='Fields', formula='declared fields excluding synthetic fields', plain='How much state the class keeps.'),
    'class.bytecode_size': dict(label='Bytecode size', formula='sum of Code attribute lengths of its methods (bytes)',
        plain='How much compiled code the class has; a rough size measure independent of formatting.'),
    'class.max_method_size': dict(label='Largest method', formula='max Code attribute length over its methods (bytes)',
        plain='The size of its biggest method. Very large methods are hard to read and test.'),
    'class.complexity': dict(label='Bytecode complexity', formula='sum over methods of (conditional branch instructions + switch cases + 1)',
        plain='How many decision points the class has in total; approximates cyclomatic complexity from bytecode.'),
    'class.max_method_complexity': dict(label='Most complex method', formula='max over methods of (conditional branches + switch cases + 1)',
        plain='How many paths its most complicated method has; each path needs its own test.'),
    'class.dependency_count': dict(label='Distinct dependencies', formula='|{referenced types, internal and external, excluding java.lang.*}|',
        plain='How many different types this class needs to compile.'),
    'class.cycle_groups': dict(label='Cycle groups', formula='number of cyclic groups (SCCs) containing C', plain='Whether this class is part of a dependency loop.'),
    'class.layer_violations': dict(label='Layer violations', formula='|{dependencies from C to a layer C may not use}|',
        plain='How many times this class reaches into a layer it should not use.'),
    'package.class_count': dict(label='Classes', formula='top-level classes in P', plain='Size of the package.'),
    'package.Ca': dict(label='Afferent coupling (Ca)', formula='|{classes outside P that depend on a class in P}|',
        plain='How many outside classes rely on this package.'),
    'package.Ce': dict(label='Efferent coupling (Ce)', formula='|{classes outside P that a class in P depends on}|',
        plain='How many outside classes this package relies on.'),
    'package.I': dict(label='Instability (I)', formula='Ce / (Ca + Ce); 0 when Ca + Ce = 0',
        plain='0 means many others rely on it and it relies on little (hard to change); 1 means the opposite (easy to change).'),
    'package.A': dict(label='Abstractness (A)', formula='(abstract classes + interfaces) / classes in P',
        plain='Share of the package that is interfaces or abstract classes.'),
    'package.D': dict(label='Distance from main sequence (D)', formula='|A + I - 1|',
        plain='0 is balanced. Near 1 means either rigid concrete code that many rely on, or unused abstractions.'),
    'package.cycle_groups': dict(label='Cycle groups', formula='package-level cyclic groups containing P + class-level groups with a member in P',
        plain='How many dependency loops touch this package.'),
    'package.largest_cycle': dict(label='Largest cycle group', formula='max size of a class-level cyclic group with a member in P', plain='Size of the biggest loop touching this package.'),
    'package.layer_violations': dict(label='Layer violations', formula='sum of class layer violations in P', plain='How often code in this package reaches into a forbidden layer.'),
    'package.bytecode_size': dict(label='Bytecode size', formula='sum of class bytecode sizes in P', plain='Total compiled code in the package.'),
}


@lru_cache(maxsize=2)
def load_debt_rules(path: str = str(RULES_PATH)) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported debt rules file.')
    return data


def indicator(key: str, value, thresholds: dict) -> dict:
    limits = thresholds.get(key)
    if value is None:
        return dict(state='unknown', warn=limits and limits['warn'], over=limits and limits['over'])
    if not limits:
        return dict(state='info', warn=None, over=None)
    state = 'over' if value > limits['over'] else 'near' if value > limits['warn'] else 'ok'
    return dict(state=state, warn=limits['warn'], over=limits['over'])


def _metric(key, value, inputs, thresholds, note=None):
    out = dict(value=value, indicator=indicator(key, value, thresholds))
    if inputs is not None:
        items = sorted(inputs)
        out.update(inputs=items[:INPUT_LIMIT], input_count=len(items))
    if note:
        out['note'] = note
    return out


def layer_violations(model, rules: dict | None = None) -> list[dict]:
    rules = rules or load_debt_rules()
    allowed = rules['layering']
    has_service = any(r['layer'] == 'SERVICE' and r['role'] == 'SERVICE' for r in model.roles.values())
    out = []
    for (source, target), kinds in sorted(model.owner_edges.items()):
        a, b = model.roles.get(source, {}).get('layer', 'SUPPORT'), model.roles.get(target, {}).get('layer', 'SUPPORT')
        if b == 'SUPPORT' or b in allowed.get(a, []):
            if a == 'PRESENTATION' and b == 'DATA_ACCESS' and has_service:
                out.append(dict(source=source, target=target, source_layer=a, target_layer=b, kind='SKIP', edge_types=dict(kinds)))
            continue
        out.append(dict(source=source, target=target, source_layer=a, target_layer=b, kind='VIOLATION', edge_types=dict(kinds)))
    return out


def compute(model, cycles: dict | None = None, rules: dict | None = None) -> dict:
    rules = rules or load_debt_rules()
    thresholds = rules['metric_thresholds']
    cycles = cycles or analyse_cycles(model)
    owners = sorted({model.owners.get(c, c) for c in model.classes if model.owners.get(c, c) in model.classes})
    incoming, outgoing = defaultdict(set), defaultdict(set)
    for (source, target) in model.owner_edges:
        outgoing[source].add(target)
        incoming[target].add(source)
    external = defaultdict(set)
    for edge in model.external_edges:
        if not edge['target'].startswith('java.lang.'):
            external[model.owners.get(edge['source'], edge['source'])].add(edge['target'])
    class_groups = defaultdict(list)
    package_groups = defaultdict(list)
    for group in cycles['groups']:
        for member in group['members']:
            (class_groups if group['level'] == 'CLASS' else package_groups)[member].append(group)
    violations = defaultdict(list)
    for row in layer_violations(model, rules):
        if row['kind'] == 'VIOLATION':
            violations[row['source']].append(row)
    classes = []
    for fqn in owners:
        info = model.facts.get(fqn)
        methods = model.methods_of(fqn)
        if info:
            sizes = [(m['code_length'], m['name']) for m in methods]
            complexity = [(m['branch_count'] + 1, m['name']) for m in methods if not m['abstract'] and m['code_length']]
            fields = [f for f in info['fields'] if not f['synthetic']]
            byte_size = sum(s for s, _ in sizes)
            biggest = max(sizes, default=(0, None))
            hardest = max(complexity, default=(0, None))
            total_complexity = sum(c for c, _ in complexity)
        else:
            fields, byte_size, biggest, hardest, total_complexity = None, None, (None, None), (None, None), None
        cls = model.classes[fqn]
        deps = (outgoing[fqn] | external[fqn]) - {fqn}
        nested = model.nested_by_owner.get(fqn, [])
        no_facts = 'Not available: this analysis has no bytecode facts (run a new analysis).'
        row = dict(id=fqn, name=short(fqn), package=model.package(fqn), role=model.roles[fqn]['role'], layer=model.roles[fqn]['layer'],
            nested_classes=nested, metrics={
                'class.fan_in': _metric('class.fan_in', len(incoming[fqn]), incoming[fqn], thresholds),
                'class.fan_out': _metric('class.fan_out', len(outgoing[fqn]), outgoing[fqn], thresholds),
                'class.method_count': _metric('class.method_count', len(methods), [m['name'] for m in methods], thresholds),
                'class.field_count': _metric('class.field_count', len(fields) if fields is not None else cls.get('field_count'), [f['name'] for f in fields] if fields is not None else None, thresholds),
                'class.bytecode_size': _metric('class.bytecode_size', byte_size, None, thresholds, None if info else no_facts),
                'class.max_method_size': _metric('class.max_method_size', biggest[0], [biggest[1]] if biggest[1] else None, thresholds, None if info else no_facts),
                'class.complexity': _metric('class.complexity', total_complexity, None, thresholds, None if info else no_facts),
                'class.max_method_complexity': _metric('class.max_method_complexity', hardest[0], [hardest[1]] if hardest[1] else None, thresholds, None if info else no_facts),
                'class.dependency_count': _metric('class.dependency_count', len(deps), deps, thresholds),
                'class.cycle_groups': _metric('class.cycle_groups', len(class_groups[fqn]), [g['id'] for g in class_groups[fqn]], thresholds),
                'class.layer_violations': _metric('class.layer_violations', len(violations[fqn]), [v['target'] for v in violations[fqn]], thresholds),
            })
        classes.append(row)
    by_class = {c['id']: c for c in classes}
    packages = []
    for package in sorted({c['package'] for c in classes}):
        members = {c['id'] for c in classes if c['package'] == package}
        ca = {s for t in members for s in incoming[t] if s not in members}
        ce = {t for s in members for t in outgoing[s] if t not in members}
        abstract = {m for m in members if model.classes[m].get('is_abstract') or model.classes[m].get('is_interface')}
        instability = round(len(ce) / (len(ca) + len(ce)), 4) if ca or ce else 0.0
        abstractness = round(len(abstract) / len(members), 4)
        distance = round(abs(abstractness + instability - 1), 4)
        touching = {g['id']: g for m in members for g in class_groups[m]}
        groups = package_groups[package] + list(touching.values())
        size = [by_class[m]['metrics']['class.bytecode_size']['value'] for m in members]
        packages.append(dict(id=package, name=package, class_count=len(members), isolated=not ca and not ce, metrics={
            'package.class_count': _metric('package.class_count', len(members), members, thresholds),
            'package.Ca': _metric('package.Ca', len(ca), ca, thresholds),
            'package.Ce': _metric('package.Ce', len(ce), ce, thresholds),
            'package.I': _metric('package.I', instability, None, thresholds),
            'package.A': _metric('package.A', abstractness, abstract, thresholds),
            'package.D': _metric('package.D', distance if (ca or ce) else None, None, thresholds,
                None if (ca or ce) else 'Not meaningful: the package has no internal dependencies in either direction.'),
            'package.cycle_groups': _metric('package.cycle_groups', len(groups), [g['id'] for g in groups], thresholds),
            'package.largest_cycle': _metric('package.largest_cycle', max((g['size'] for g in touching.values()), default=0), None, thresholds),
            'package.layer_violations': _metric('package.layer_violations', sum(len(violations[m]) for m in members), None, thresholds),
            'package.bytecode_size': _metric('package.bytecode_size', sum(s for s in size if s is not None) if all(s is not None for s in size) else None, None, thresholds),
        }))
    worst = {}
    for key in DEFINITIONS:
        rows = classes if key.startswith('class.') else packages
        ranked = sorted((r for r in rows if r['metrics'][key]['value'] is not None), key=lambda r: (-r['metrics'][key]['value'], r['id']))
        worst[key] = [dict(id=r['id'], value=r['metrics'][key]['value'], state=r['metrics'][key]['indicator']['state']) for r in ranked[:5] if r['metrics'][key]['value']]
    return dict(definitions={k: dict(v, threshold=thresholds.get(k)) for k, v in DEFINITIONS.items()}, classes=classes, packages=packages,
        worst=worst, rules_version=rules['rules_version'], facts_available=model.facts_available,
        counting=f'{len(owners)} top-level classes; {sum(len(c["nested_classes"]) for c in classes)} nested, anonymous or local classes folded into their owners.')
