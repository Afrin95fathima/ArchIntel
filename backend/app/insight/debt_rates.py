"""Technical problems as percentages. Every rate is `numerator / denominator` with both definitions stated;
a rate that cannot be computed is NOT_MEASURED with the reason, never 0%."""
from __future__ import annotations

from collections import defaultdict

SEVERITY_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}

# id, label, finding rules, unit, numerator definition, denominator definition, needs bytecode facts
RATE_DEFS = [
    dict(id='god-class', label='God classes', rules=['DEBT-GOD-CLASS'], unit='classes', population='classes', facts=False,
        numerator='classes that exceed at least the rule\'s minimum number of size or coupling thresholds', denominator='all analysed top-level classes'),
    dict(id='high-coupling', label='Highly coupled classes', rules=['DEBT-HIGH-COUPLING'], unit='classes', population='classes', facts=False,
        numerator='classes whose fan-in plus fan-out exceeds the coupling threshold', denominator='all analysed top-level classes'),
    dict(id='cycle-member', label='Classes in dependency cycles', rules=['DEBT-CYCLE-MEMBER'], unit='classes', population='classes', facts=False,
        numerator='classes that belong to a strongly connected group of two or more classes', denominator='all analysed top-level classes'),
    dict(id='too-many-dependencies', label='Classes with too many dependencies', rules=['DEBT-TOO-MANY-DEPENDENCIES'], unit='classes', population='classes', facts=True,
        numerator='classes that reference more distinct types than the threshold', denominator='all analysed top-level classes'),
    dict(id='deprecated-api', label='Classes calling deprecated APIs', rules=['DEBT-DEPRECATED-API'], unit='classes', population='classes', facts=True,
        numerator='classes with at least one call site to a deprecated member', denominator='all analysed top-level classes'),
    dict(id='aging-framework', label='Classes using aging frameworks', rules=['DEBT-AGING-FRAMEWORK'], unit='classes', population='classes', facts=True,
        numerator='classes that use a technology the lifecycle rules mark aging or end-of-life', denominator='all analysed top-level classes'),
    dict(id='layer-violation', label='Layer-violating dependencies', rules=['DEBT-LAYER-VIOLATION', 'DEBT-LAYER-SKIP'], unit='dependency edges', population='edges', facts=True,
        numerator='class dependency edges that point against the layering or skip the service layer', denominator='all class-to-class dependency edges between application classes'),
    dict(id='entity-in-controller', label='Controller dependencies on entities', rules=['DEBT-ENTITY-IN-CONTROLLER'], unit='dependency edges', population='presentation_edges', facts=True,
        numerator='presentation-layer edges that point directly at an entity class', denominator='all dependency edges whose source is a presentation-layer class'),
    dict(id='large-method', label='Large methods', rules=['DEBT-LARGE-METHOD'], unit='methods', population='methods', facts=True,
        numerator='methods whose bytecode length exceeds the warn threshold', denominator='all methods with a measured bytecode length'),
    dict(id='complex-method', label='Complex methods', rules=['DEBT-COMPLEX-METHOD'], unit='methods', population='methods', facts=True,
        numerator='methods whose branch count plus one exceeds the warn threshold', denominator='all methods with a measured bytecode length'),
    dict(id='static-state', label='Mutable static state', rules=['DEBT-STATIC-STATE'], unit='static fields', population='static_fields', facts=True,
        numerator='static fields that are non-final, or final collections that are mutated', denominator='all static fields except serialVersionUID, enum constants and synthetic fields'),
    dict(id='unobserved', label='Classes never observed at runtime', rules=['DEBT-UNOBSERVED'], unit='classes', population='classes', facts=False, runtime=True,
        numerator='classes with no mapped span in the selected runtime sessions', denominator='all analysed top-level classes'),
]
DERIVED = [
    dict(id='cross-domain-edges', label='Cross-domain dependencies', unit='dependency edges',
        numerator='class dependency edges whose two classes belong to different candidate domains', denominator='all class dependency edges whose two classes both have a candidate domain'),
    dict(id='entry-points-unobserved', label='Entry points never observed', unit='entry points',
        numerator='entry points whose handler method (or, without method evidence, handler class) has no mapped span', denominator='all detected entry points'),
    dict(id='any-class', label='Classes with at least one finding', unit='classes',
        numerator='distinct classes named by a technical-debt finding of severity LOW or higher (INFO findings such as "never observed" describe missing evidence and are not counted)', denominator='all analysed top-level classes'),
]
BY_ID = {d['id']: d for d in RATE_DEFS + DERIVED}


def _pct(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def _rate(definition, numerator, denominator, subjects, classes, severity, status='MEASURED', reason=None):
    percentage = _pct(numerator, denominator) if status == 'MEASURED' else None
    return dict(id=definition['id'], label=definition['label'], rule_ids=definition.get('rules', []), unit=definition['unit'], status=status, reason=reason,
        numerator=numerator if status == 'MEASURED' else None, denominator=denominator if status == 'MEASURED' else None, percentage=percentage,
        text=f"{numerator} of {denominator} {definition['unit']} ({percentage}%)" if status == 'MEASURED' and percentage is not None else f"not measured: {reason}" if status != 'MEASURED' else f"0 {definition['unit']} to measure",
        numerator_definition=definition['numerator'], denominator_definition=definition['denominator'], severity=severity, subjects=sorted(subjects), classes=sorted(classes))


def _class_of(finding):
    return finding['node_ids'][0]


def compute(model, findings, class_ids, populations, runtime_included, facts_available):
    """`class_ids`: analysed top-level classes. `populations`: counts gathered by the debt detector."""
    classes = set(class_ids)
    by_rule = defaultdict(list)
    for finding in findings:
        by_rule[finding['rule_id']].append(finding)
    domain_of = {c: model.classes.get(c, {}).get('domain_id') for c in classes}
    package_of = {c: model.package(c) for c in classes}
    rates = []
    class_rate_members = {}
    for definition in RATE_DEFS:
        rows = [f for rule in definition['rules'] for f in by_rule.get(rule, [])]
        severity = min((f['severity'] for f in rows), key=lambda s: SEVERITY_ORDER.get(s, 9), default=None)
        if definition['facts'] and not facts_available:
            rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', 'this analysis has no bytecode facts; run a new analysis')); continue
        if definition.get('runtime') and not runtime_included:
            rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', 'no runtime session is selected')); continue
        denominator = {'classes': len(classes), 'edges': populations['edges'], 'presentation_edges': populations['presentation_edges'],
                       'methods': populations['methods'], 'static_fields': populations['static_fields']}[definition['population']]
        subjects = {f['entity_id'] for f in rows}
        affected = {_class_of(f) for f in rows}
        if not denominator:
            rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', f"there is no {definition['unit'].rstrip('s')} to measure in this analysis")); continue
        rates.append(_rate(definition, len(subjects), denominator, subjects, affected, severity))
        if definition['population'] == 'classes':
            class_rate_members[definition['id']] = affected & classes
    # derived: cross-domain edges
    known = [(s, t) for (s, t) in model.owner_edges if domain_of.get(s) and model.classes.get(t, {}).get('domain_id')]
    cross = [(s, t) for s, t in known if domain_of[s] != model.classes[t]['domain_id']]
    definition = BY_ID['cross-domain-edges']
    if known:
        rates.append(_rate(definition, len(cross), len(known), [f'{s} -> {t}' for s, t in cross], {s for s, _ in cross} | {t for _, t in cross}, None))
    else:
        rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', 'no dependency edge connects two classes that both have a candidate domain'))
    # derived: entry points never observed
    definition = BY_ID['entry-points-unobserved']
    items = model.entry_points['items']
    if not runtime_included or model.observed_classes is None:
        rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', 'no runtime session is selected'))
    elif not items:
        rates.append(_rate(definition, 0, 0, [], [], None, 'NOT_MEASURED', 'no entry point was detected in this analysis'))
    else:
        methods = model.observed_methods
        unobserved = [e for e in items if ((e['handler_class'], e['handler_method']) not in methods if methods is not None else e['handler_class'] not in model.observed_classes)]
        rates.append(_rate(definition, len(unobserved), len(items), [f"{e['handler_class']}.{e['handler_method']}()" for e in unobserved], {e['handler_class'] for e in unobserved}, None))
        rates[-1]['basis'] = 'method-level spans' if methods is not None else 'class-level spans (no method-level evidence)'
    # derived: any class
    problems = [f for f in findings if f['severity'] != 'INFO']
    any_members = {_class_of(f) for f in problems} & classes
    class_rate_members['any-class'] = any_members
    severity = min((f['severity'] for f in problems), key=lambda s: SEVERITY_ORDER.get(s, 9), default=None)
    rates.append(_rate(BY_ID['any-class'], len(any_members), len(classes), any_members, any_members, severity))

    def breakdown(key_of, names):
        groups = defaultdict(set)
        for cls in classes:
            groups[key_of[cls] or '(none)'].add(cls)
        rows = []
        for key, members in sorted(groups.items()):
            measured = {rid: dict(numerator=len(found & members), denominator=len(members), percentage=_pct(len(found & members), len(members)), classes=sorted(found & members))
                        for rid, found in class_rate_members.items() if found & members}
            rows.append(dict(id=key, name=names.get(key, key), class_count=len(members), rates=measured))
        return sorted(rows, key=lambda r: (-(r['rates'].get('any-class', {}).get('percentage') or 0), r['name']))
    domain_names = {d['id']: d['name'] for d in model.result.get('domains', [])}
    return dict(rates=rates, by_package=breakdown(package_of, {}), by_domain=breakdown(domain_of, domain_names),
        note='Each percentage is numerator / denominator, rounded to one decimal. Per-package and per-domain rows use the classes of that package or domain as the denominator and cover class-based rates only.')
