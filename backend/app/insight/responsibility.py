"""Functional and non-functional responsibility analysis of a completed snapshot.

Everything is derived from facts the bytecode analysis recorded: annotations (with values), supertypes, field,
parameter and return types, call sites with line numbers, `new` references, thrown types and branch counts.
A class or package name is never sole evidence: a name alone can only produce a WEAK, INFERRED label, and a
class with no better evidence is UNCERTAIN.

Stages: extract signals -> match rules -> add structural evidence -> classify (method, class) -> aggregate
(package, capability) -> map dependencies -> find cross-cutting components -> derive risks -> validate.
The result is a deterministic view over the immutable snapshot; it never mutates stored analysis results.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import re

import yaml

from app.services.graph import stable_id
from .bytecode import base_type
from .roles import short, supertypes, method_label

ENGINE_VERSION = 'responsibility-1'
RULES_PATH = Path(__file__).resolve().parent / 'rules' / 'responsibility-rules.yaml'
SIGNALS = {'ANNOTATION', 'SUPERTYPE', 'TYPE', 'CALL'}
STATUS_RANK = {'DETECTED': 0, 'INFERRED': 1, 'UNVERIFIED': 2}
STRENGTH_RANK = {'STRONG': 0, 'MEDIUM': 1, 'WEAK': 2}
SEVERITY_RANK = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
ACCESSOR = re.compile(r'^(get|set|is|has)[A-Z0-9_]')
MUTATING_HTTP = {'POST', 'PUT', 'DELETE', 'PATCH'}
# Categories that describe a measured property of the class, not a concern the class implements; they never decide its primary classification.
MEASURED_CATEGORIES = {'MAINTAINABILITY'}
COLLECTION_RETURNS = {'java.util.Collection', 'java.util.List', 'java.util.Set', 'java.lang.Iterable', 'java.util.stream.Stream'}
# Aspects of SECURITY: only access control answers "who may call this"; the others harden or protect data.
ACCESS_CONTROL_RULES = {'SEC-AUTHORIZATION', 'SEC-CONFIGURATION', 'SEC-API', 'SEC-PRINCIPAL'}
INSTRUMENTATION_RULES = {'OBS-LOGGING', 'OBS-METRICS-TRACING'}
PROTECTIVE_RULES = {'REL-RETRY', 'REL-CIRCUIT', 'REL-API', 'REL-TIMEOUT'}
REMOTE_CALL_RULES = {'INT-CLIENT', 'INT-MESSAGING'}
NOT_AVAILABLE_REASON = ('Bytecode facts are not available for this analysis, so responsibilities cannot be derived from code. '
                        'Run a new analysis of the same artifact to enable this view.')


def _compile(patterns):
    return {p for p in patterns if not p.endswith('*')}, tuple(p[:-1] for p in patterns if p.endswith('*'))


def _hit(compiled, value):
    exact, prefixes = compiled
    return value in exact or any(value.startswith(p) for p in prefixes)


@lru_cache(maxsize=2)
def load_rules(path: str = str(RULES_PATH)) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    categories = {'FUNCTIONAL': set(data['taxonomy']['functional']), 'NON_FUNCTIONAL': set(data['taxonomy']['nonfunctional'])}
    seen = set()
    for rule in data['rules']:
        if rule['id'] in seen:
            raise ValueError(f"Duplicate responsibility rule id {rule['id']}.")
        seen.add(rule['id'])
        if rule['side'] not in categories or rule['category'] not in categories[rule['side']]:
            raise ValueError(f"Rule {rule['id']} uses category {rule['category']} that is not registered under {rule['side']}.")
        if rule['signal'] not in SIGNALS:
            raise ValueError(f"Rule {rule['id']} uses unknown signal {rule['signal']}.")
        if rule['status'] not in ('DETECTED', 'INFERRED') or rule['strength'] not in STRENGTH_RANK:
            raise ValueError(f"Rule {rule['id']} has an invalid status or strength.")
        rule['_match'] = _compile(rule['match'])
    for family in data['libraries']:
        family['_match'] = _compile(family['match'])
    return data


# ------------------------------------------------------------------------------------------ signals
def _signal(kind, value, scope, where, member=None, line=None, name=None, values=None, via=None, owner=None, member_lines=None):
    return dict(kind=kind, value=value, scope=scope, where=where, member=member, line=line, name=name, values=values or {}, via=via, owner=owner, member_lines=member_lines)


def _signals(model, fqn):
    """All facts of a top-level class and its nested classes that a rule may match."""
    out = []
    for name in [fqn] + model.nested_by_owner.get(fqn, []):
        info = model.facts.get(name) or {}
        label = short(name)
        for annotation in info.get('annotations', []):
            out.append(_signal('ANNOTATION', annotation['type'], 'class', f'{label} is annotated @{short(annotation["type"])}', values=annotation.get('values'), via='class', owner=name))
        for parent in supertypes(name, model.facts, model.classes):
            verb = 'implements' if parent in (info.get('interfaces') or []) else 'extends' if parent == info.get('super_name') else 'inherits from'
            out.append(_signal('SUPERTYPE', parent, 'class', f'{label} {verb} {short(parent)}', via='class', owner=name))
        for field in info.get('fields', []):
            if field['synthetic']:
                continue
            member = f'field {field["name"]}'
            for annotation in field.get('annotations', []):
                out.append(_signal('ANNOTATION', annotation['type'], 'member', f'field {label}.{field["name"]} is annotated @{short(annotation["type"])}', member=member, values=annotation.get('values'), via='field', owner=name))
            for kind_type, via in [(base_type(field['type']), 'field')] + [(t, 'generic') for t in field.get('generic_types', [])]:
                out.append(_signal('TYPE', kind_type, 'member', f'field {label}.{field["name"]} has type {short(kind_type)}', member=member, via=via, owner=name))
        for method in info.get('methods', []):
            if method.get('bridge') or (method.get('synthetic') and not method.get('lambda_body')):
                continue
            sig, where = method['signature'], method_label(name, method['name'])
            lines = method.get('line_range')
            start = (lines or [None])[0]
            for annotation in method.get('annotations', []):
                out.append(_signal('ANNOTATION', annotation['type'], 'member', f'{where} is annotated @{short(annotation["type"])}', member=sig, member_lines=lines, values=annotation.get('values'), via='method', owner=name))
            for group in method.get('parameter_annotations', []):
                for annotation in group:
                    out.append(_signal('ANNOTATION', annotation['type'], 'member', f'{where} has a parameter annotated @{short(annotation["type"])}', member=sig, member_lines=lines, values=annotation.get('values'), via='parameter', owner=name))
            for parameter in method.get('parameters', []):
                out.append(_signal('TYPE', base_type(parameter), 'member', f'{where} takes a {short(base_type(parameter))} parameter', member=sig, member_lines=lines, via='parameter', owner=name))
            out.append(_signal('TYPE', base_type(method.get('returns') or ''), 'member', f'{where} returns {short(method.get("returns") or "")}', member=sig, member_lines=lines, via='return', owner=name))
            for exception in method.get('exceptions', []):
                out.append(_signal('TYPE', exception, 'member', f'{where} declares throws {short(exception)}', member=sig, member_lines=lines, via='throws', owner=name))
            for site in method.get('invokes', []):
                out.append(_signal('CALL', site['owner'], 'member', f'{where} calls {short(site["owner"])}.{site["name"]}()', member=sig, line=site.get('line'), member_lines=lines, name=site['name'], via='call', owner=name))
            for ref in method.get('type_refs', []):
                if ref['kind'] in ('new', 'checkcast'):
                    out.append(_signal('TYPE', ref['type'], 'member', f'{where} {"creates" if ref["kind"] == "new" else "casts to"} {short(ref["type"])}', member=sig, line=ref.get('line'), member_lines=lines, via='new' if ref['kind'] == 'new' else 'cast', owner=name))
    unique, seen = [], set()
    for item in out:
        key = (item['kind'], item['value'], item['member'], item['name'], item['via'])
        if key not in seen and item['value']:
            seen.add(key)
            unique.append(item)
    return unique


def _matches(rule, signal):
    if rule['signal'] == 'TYPE':
        if signal['kind'] not in ('TYPE', 'CALL'):
            return False
    elif signal['kind'] != rule['signal']:
        return False
    if rule['scope'] != 'any' and signal['scope'] != rule['scope']:
        return False
    if not _hit(rule['_match'], signal['value']):
        return False
    if rule.get('names') and signal['name'] not in rule['names']:
        return False
    if rule.get('values_kind') and signal['via'] != rule['values_kind']:
        return False
    for key, wanted in (rule.get('values') or {}).items():
        have = signal['values'].get(key)
        if not (have == wanted or (isinstance(have, list) and wanted in have)):
            return False
    return True


def _counts_toward_mixed(rule, signal):
    """A class is MIXED only when its own code runs a non-functional concern: it calls the API or holds an instance of it.
    Declaring an annotation (such as a transaction or cache annotation) delegates the concern to the framework."""
    return bool(rule.get('mixing')) and (signal['kind'] == 'CALL' or signal['via'] in ('field', 'new', 'cast'))


# ------------------------------------------------------------------------------------------ evidence
class _Builder:
    def __init__(self, model, rules):
        self.model, self.rules = model, rules
        self.evidence: dict[str, dict] = {}
        self.classes: dict[str, dict] = {}

    def location(self, owner, info, line=None, end=None, member_lines=None):
        index = (self.model.result.get('source_store') or {}).get('index') or {}
        entry = index.get(owner)
        derived = (owner.rpartition('.')[0].replace('.', '/') + '/' + info['source_file']) if info.get('source_file') else None
        return dict(file_path=entry['archive_path'] if entry else derived, source_file=info.get('source_file'), start_line=line, end_line=end,
                    available=bool(entry), basis='ARTIFACT_SOURCE_ENTRY' if entry else 'DERIVED_FROM_PACKAGE_AND_SOURCE_FILE_ATTRIBUTE' if derived else 'UNAVAILABLE',
                    member_line_range=list(member_lines) if member_lines else None,
                    line_basis='BYTECODE_LINE_NUMBER_TABLE' if line else 'METHOD_BODY_RANGE_FROM_LINE_NUMBER_TABLE' if member_lines else 'UNAVAILABLE')

    def add(self, top, kind, text, strength, owner, member=None, line=None, end=None, member_lines=None):
        info = self.model.facts.get(owner) or {}
        ident = stable_id('resp-evidence', f'{owner}|{member}|{kind}|{text}')
        self.evidence.setdefault(ident, dict(id=ident, kind=kind, text=text, strength=strength, class_name=owner, top_class=top, member=member,
                                             location=self.location(owner, info, line, end, member_lines), source='BYTECODE'))
        return ident

    def label(self, fqn, side, category, status, strength, rule_id, text, evidence_id, member=None, mixes=False):
        bucket = self.classes[fqn]['_labels'].setdefault((side, category), dict(side=side, category=category, statuses=[], strengths=[], rules=set(), evidence=[], methods=set(), texts={}, mixes=False))
        bucket['statuses'].append(status)
        bucket['strengths'].append(strength)
        bucket['rules'].add(rule_id)
        if evidence_id not in bucket['evidence']:
            bucket['evidence'].append(evidence_id)
        if member and not member.startswith('field '):
            bucket['methods'].add(member)
        bucket['texts'].setdefault(rule_id, text)
        bucket['mixes'] = bucket['mixes'] or mixes
        if member and not member.startswith('field '):
            self.classes[fqn]['_method_labels'].setdefault(member, {}).setdefault((side, category), dict(status=status, evidence=[], rule=rule_id))
            ml = self.classes[fqn]['_method_labels'][member][(side, category)]
            ml['status'] = min(ml['status'], status, key=STATUS_RANK.get)
            if evidence_id not in ml['evidence']:
                ml['evidence'].append(evidence_id)


def _confidence(statuses, strengths, rules):
    detected_strong = any(s == 'DETECTED' and g == 'STRONG' for s, g in zip(statuses, strengths))
    if detected_strong:
        level, basis = 'HIGH', f'{sum(1 for s, g in zip(statuses, strengths) if s == "DETECTED" and g == "STRONG")} detected strong evidence item(s) from rule(s) {", ".join(sorted(rules))}'
    elif 'DETECTED' in statuses or 'MEDIUM' in strengths:
        level, basis = 'MEDIUM', f'only medium-strength or single detected evidence from rule(s) {", ".join(sorted(rules))}'
    else:
        level, basis = 'LOW', f'only weak evidence from rule(s) {", ".join(sorted(rules))}'
    return dict(level=level, basis=basis, calibrated=False)


# ------------------------------------------------------------------------------------------ analysis
def analyze(model) -> dict:
    rules = load_rules()
    if not model.facts_available:
        return dict(status='NOT_AVAILABLE', reason=NOT_AVAILABLE_REASON)
    limitations = []
    builder = _Builder(model, rules)
    tops = sorted(fqn for fqn in model.classes if not model.is_nested(fqn))
    domain_of = {c: d['id'] for d in model.result.get('domains', []) for c in d['classes']}
    # nested classes belong to the domain of their owner
    for fqn in model.classes:
        domain_of.setdefault(fqn, domain_of.get(model.owners.get(fqn, fqn)))
    internal = set(model.classes)
    for fqn in tops:
        info = model.facts.get(fqn) or {}
        builder.classes[fqn] = dict(fqn=fqn, info=info, _labels={}, _method_labels={}, _methods={}, _signals=[])
        signals = _signals(model, fqn)
        builder.classes[fqn]['_signals'] = signals
        for rule in rules['rules']:
            for signal in signals:
                if not _matches(rule, signal):
                    continue
                evidence_id = builder.add(fqn, signal['kind'], signal['where'], rule['strength'], signal['owner'], signal['member'], signal['line'], member_lines=signal['member_lines'])
                builder.label(fqn, rule['side'], rule['category'], rule['status'], rule['strength'], rule['id'], rule['text'], evidence_id, signal['member'],
                              _counts_toward_mixed(rule, signal))
        _structural(model, builder, fqn, internal)
    _role_labels(model, builder, tops)
    maintainability = _maintainability(model, builder, limitations)
    components = {fqn: _finish_class(model, builder, fqn, rules, domain_of) for fqn in tops}
    capabilities = _capabilities(model, components, rules)
    _associate_capabilities(components, capabilities, model, domain_of)
    dependencies, external = _dependencies(model, components, domain_of, capabilities, rules)
    cross = _cross_cutting(model, components, dependencies, external, domain_of, capabilities, rules)
    risks = _risks(model, builder, components, capabilities, cross, domain_of, rules, limitations)
    for risk in risks:
        for fqn in risk['affected_components']:
            if fqn in components:
                components[fqn]['risk_ids'].append(risk['id'])
    packages = _packages(model, components)
    _capability_implications(capabilities, components, cross, risks)
    result = dict(status='AVAILABLE', analysis_metadata=_metadata(model, rules), taxonomy=_taxonomy(rules), components=components, evidence=builder.evidence,
                  packages=packages, capabilities=capabilities, dependencies=dependencies, external_libraries=external, cross_cutting=cross, risks=risks,
                  limitations=limitations + _standing_limitations(model), maintainability_signals=maintainability)
    result['validation'] = validate(result, model)
    result['summary'] = _summary(result)
    return result


def _is_accessor(method):
    return bool(ACCESSOR.match(method['name'])) and method.get('code_length', 99) <= 12 and not method.get('branch_count')


def _structural(model, builder, fqn, internal):
    """Evidence that comes from the shape of the code rather than from a framework API."""
    info = builder.classes[fqn]['info']
    roles = model.roles
    for name in [fqn] + model.nested_by_owner.get(fqn, []):
        nested = model.facts.get(name) or {}
        label = short(name)
        for field in nested.get('fields', []):
            if field['static'] and not field['final'] and not field['synthetic'] and not field['name'].startswith('$'):
                type_name = base_type(field['type'])
                if not type_name.startswith(('org.slf4j.', 'java.util.logging.', 'org.apache.logging.', 'org.apache.commons.logging.')):
                    text = f'field {label}.{field["name"]} is static and not final'
                    ident = builder.add(fqn, 'FIELD', text, 'STRONG', name, f'field {field["name"]}')
                    builder.label(fqn, 'NON_FUNCTIONAL', 'SCALABILITY', 'DETECTED', 'STRONG', 'STRUCT-STATIC-STATE', 'holds mutable static state', ident, f'field {field["name"]}')
        for method in nested.get('methods', []):
            if method.get('bridge') or method.get('synthetic') or method['name'] in ('<init>', '<clinit>'):
                continue
            sig, where = method['signature'], method_label(name, method['name'])
            lines = method.get('line_range') or [None, None]
            owners = [s['owner'] for s in method.get('invokes', []) if s['owner'] in internal and model.owners.get(s['owner'], s['owner']) != fqn]
            if method.get('branch_count', 0) >= 1 and not _is_accessor(method) and any(s['owner'] in internal for s in method.get('invokes', [])):
                called = sorted({short(s['owner']) + '.' + s['name'] + '()' for s in method.get('invokes', []) if s['owner'] in internal})[:4]
                text = f'{where} has {method["branch_count"]} branch(es) and calls {", ".join(called)}'
                ident = builder.add(fqn, 'STRUCTURE', text, 'MEDIUM', name, sig, member_lines=lines)
                builder.label(fqn, 'FUNCTIONAL', 'BUSINESS_LOGIC', 'INFERRED', 'MEDIUM', 'STRUCT-LOGIC', 'contains branching logic over application classes', ident, sig)
            distinct = {o for o in owners if roles.get(o, {}).get('role') not in ('ENTITY', 'MODEL', 'EXCEPTION', 'UTILITY')}
            if len(distinct) >= 2:
                text = f'{where} calls {len(distinct)} collaborating classes that are not domain model: {", ".join(sorted(short(o) for o in distinct)[:4])}'
                ident = builder.add(fqn, 'STRUCTURE', text, 'MEDIUM', name, sig, member_lines=lines)
                builder.label(fqn, 'FUNCTIONAL', 'APPLICATION_ORCHESTRATION', 'INFERRED', 'MEDIUM', 'STRUCT-ORCHESTRATION', 'coordinates classes with different roles', ident, sig)
        constructors = [m for m in nested.get('methods', []) if m['name'] == '<init>' and m.get('parameters')]
        held = {base_type(f['type']) for f in nested.get('fields', []) if not f['static'] and f['final']}
        for constructor in constructors:
            injected = [p for p in map(base_type, constructor['parameters']) if p in held and p in internal]
            if injected:
                text = f'{label} constructor receives {", ".join(short(p) for p in injected)} and stores it in a final field'
                ident = builder.add(fqn, 'STRUCTURE', text, 'MEDIUM', name, constructor['signature'], member_lines=constructor.get('line_range'))
                builder.label(fqn, 'NON_FUNCTIONAL', 'TESTABILITY', 'INFERRED', 'MEDIUM', 'STRUCT-CONSTRUCTOR-INJECTION', 'receives its application dependencies through its constructor', ident, constructor['signature'])
                break
    if info.get('interface') and not info.get('annotation_type'):
        implementers = sorted(n for n, f in model.facts.items() if fqn in (f.get('interfaces') or []) and n in internal)
        if len(implementers) >= 2:
            text = f'interface {short(fqn)} has {len(implementers)} implementations: {", ".join(short(n) for n in implementers[:4])}'
            ident = builder.add(fqn, 'STRUCTURE', text, 'MEDIUM', fqn)
            builder.label(fqn, 'NON_FUNCTIONAL', 'EXTENSIBILITY', 'INFERRED', 'MEDIUM', 'STRUCT-INTERFACE-IMPLEMENTATIONS', 'has alternative implementations', ident)


_ROLE_FUNCTIONAL = {'CONTROLLER': 'API_AND_APPLICATION_ENTRY', 'SERVLET': 'API_AND_APPLICATION_ENTRY', 'ACTION': 'API_AND_APPLICATION_ENTRY', 'LISTENER': 'API_AND_APPLICATION_ENTRY',
                    'SERVICE': 'BUSINESS_LOGIC', 'REPOSITORY': 'BUSINESS_DATA_ACCESS', 'ENTITY': 'DOMAIN_MODEL', 'MODEL': 'DOMAIN_MODEL', 'VALIDATOR': 'BUSINESS_VALIDATION'}


def _role_labels(model, builder, tops):
    """A role read from a name or a package gives only a WEAK, INFERRED label. A MODEL role (a data carrier with a serialization
    annotation) gives a MEDIUM, INFERRED domain-model label. Stronger roles are already covered by rules."""
    for fqn in tops:
        role = model.roles.get(fqn) or {}
        category = _ROLE_FUNCTIONAL.get(role.get('role'))
        if not category or not (role['evidence'] == 'NAMING' or role['role'] == 'MODEL'):
            continue
        weak = role['evidence'] == 'NAMING'
        ident = builder.add(fqn, 'NAMING' if weak else 'ROLE', f'{short(fqn)}: {role["reason"]}', 'WEAK' if weak else 'MEDIUM', fqn)
        builder.label(fqn, 'FUNCTIONAL', category, 'INFERRED', 'WEAK' if weak else 'MEDIUM', 'ROLE-NAMING' if weak else 'ROLE-MODEL',
                      f'is probably a {role["role"].lower()} (naming convention only)' if weak else 'carries business data between the application and its callers', ident)


def _maintainability(model, builder, limitations):
    """MAINTAINABILITY evidence from findings ArchIntel already produced: the snapshot issues (outliers relative to this
    application's own 95th percentile) and the technical-debt rules (absolute thresholds in debt-rules.yaml)."""
    used = []
    def attach(owner, title, detail, rule_id, severity):
        owner = model.owners.get(owner, owner)
        if owner not in builder.classes:
            return
        ident = builder.add(owner, 'METRIC', f'{title}' + (f' ({detail})' if detail else ''), 'STRONG', owner)
        builder.label(owner, 'NON_FUNCTIONAL', 'MAINTAINABILITY', 'DETECTED', 'STRONG', rule_id, title.lower(), ident)
        used.append(dict(rule_id=rule_id, class_name=owner, severity=severity))
    for issue in model.result.get('issues', []):
        if issue.get('entity_type') == 'CLASS':
            attach(issue['entity_id'], issue['title'], f'{issue["issue_type"]}: {_flat(issue.get("evidence"))}; relative to this application, not an absolute limit', 'ISSUE-' + issue['issue_type'], issue['severity'])
    try:
        from .debt import detect
        findings = detect(model)['findings']
    except Exception as error:                      # an unrelated failure must not discard the rest of the analysis
        limitations.append(f'Maintainability evidence from technical-debt rules is unavailable ({type(error).__name__}).')
        return used
    for finding in findings:
        if finding['rule_id'] in ('DEBT-GOD-CLASS', 'DEBT-HIGH-COUPLING', 'DEBT-TOO-MANY-DEPENDENCIES', 'DEBT-CYCLE-MEMBER', 'DEBT-COMPLEX-METHOD') and finding['entity_type'] == 'CLASS':
            attach(finding['entity_id'], finding['title'], _flat(finding.get('measured')), finding['rule_id'], finding['severity'])
        elif finding['rule_id'] == 'DEBT-ENTITY-IN-CONTROLLER' and finding.get('node_ids'):
            attach(finding['node_ids'][0], finding['title'], f'uses {short(finding["node_ids"][-1])} directly', finding['rule_id'], finding['severity'])
    return used


def _flat(value):
    if isinstance(value, dict):
        return ', '.join(f'{k}={_flat(v)}' for k, v in sorted(value.items()) if not isinstance(v, (list, dict)) or k in ('value', 'p95'))
    return str(value)[:120]


def _finish_class(model, builder, fqn, rules, domain_of):
    data = builder.classes[fqn]
    info = data['info']
    labels = {'FUNCTIONAL': [], 'NON_FUNCTIONAL': []}
    strength_of = {r['id']: r['strength'] for r in rules['rules']}
    for (side, category), bucket in sorted(data['_labels'].items()):
        strongest = min(bucket['rules'], key=lambda r: (STRENGTH_RANK.get(strength_of.get(r, 'MEDIUM'), 1), r))
        status = min(bucket['statuses'], key=STATUS_RANK.get)
        labels[side].append(dict(category=category, side=side, status=status, description=bucket['texts'][strongest],
                                 rule_ids=sorted(bucket['rules']), evidence_ids=bucket['evidence'][:12], evidence_count=len(bucket['evidence']), methods=sorted(bucket['methods'])[:20],
                                 confidence=_confidence(bucket['statuses'], bucket['strengths'], bucket['rules']), mixes=bucket['mixes']))
    functional, nonfunctional = labels['FUNCTIONAL'], labels['NON_FUNCTIONAL']
    functional_detected = [l for l in functional if l['status'] == 'DETECTED' or l['confidence']['level'] != 'LOW']
    nonfunctional_detected = [l for l in nonfunctional if l['status'] == 'DETECTED' and l['category'] not in MEASURED_CATEGORIES]
    support = set(rules['classification']['support_categories'])
    reasons, uncertainties = [], []
    if functional_detected:
        primary = 'FUNCTIONAL_SUPPORT' if {l['category'] for l in functional} <= support else 'FUNCTIONAL'
        if any(l['mixes'] for l in nonfunctional_detected):
            primary = 'MIXED'
            reasons.append('its own code runs non-functional concerns: ' + ', '.join(sorted(l['category'] for l in nonfunctional_detected if l['mixes'])))
    elif nonfunctional_detected:
        primary = 'NON_FUNCTIONAL'
    else:
        primary = 'UNCERTAIN'
        uncertainties.append('No annotation, supertype, API call or structural pattern establishes a responsibility; any label above is from a name only.' if (functional or nonfunctional) else
                             'No responsibility evidence was found in the bytecode of this class.')
    weak = [l['category'] for l in functional + nonfunctional if l['confidence']['level'] == 'LOW']
    if weak and primary != 'UNCERTAIN':
        uncertainties.append('Low-confidence labels: ' + ', '.join(sorted(set(weak))) + ' (weak or single inferred evidence).')
    role = dict(model.roles.get(fqn) or {})
    methods = []
    for method in info.get('methods', []):
        if method.get('bridge') or method.get('synthetic'):
            continue
        found = data['_method_labels'].get(method['signature'], {})
        methods.append(dict(signature=method['signature'], name=method['name'], line_range=method.get('line_range'),
                            labels=[dict(category=c, side=s, status=v['status'], evidence_ids=v['evidence'][:6], rule_id=v['rule']) for (s, c), v in sorted(found.items())]))
    return dict(id=fqn, component_type='CLASS', fqn=fqn, simple_name=short(fqn), package=model.package(fqn),
                source_location=builder.location(fqn, info), primary_classification=primary, classification_reasons=reasons,
                architectural_role=dict(role=role.get('role', 'UNKNOWN'), layer=role.get('layer', 'SUPPORT'), evidence=role.get('evidence', 'NONE'), reason=role.get('reason', '')),
                functional_responsibilities=functional, non_functional_responsibilities=nonfunctional, methods=methods, domain_id=domain_of.get(fqn),
                business_capabilities=[], dependencies=[], dependents=[], risk_ids=[], uncertainties=uncertainties,
                nested_classes=model.nested_by_owner.get(fqn, []))


# ------------------------------------------------------------------------------------------ capabilities
def _capabilities(model, components, rules):
    share = rules['capability_kind']['technical_share']
    out = {}
    for domain in model.result.get('domains', []):
        members = [components[c] for c in domain['classes'] if c in components]
        if not members:
            continue
        counts = Counter(m['primary_classification'] for m in members)
        entities = [m['fqn'] for m in members if any(l['category'] == 'DOMAIN_MODEL' and l['status'] == 'DETECTED' for l in m['functional_responsibilities'])]
        repositories = [m['fqn'] for m in members if any(l['category'] == 'BUSINESS_DATA_ACCESS' and l['status'] == 'DETECTED' for l in m['functional_responsibilities'])]
        logic = [m['fqn'] for m in members if any(l['category'] in ('BUSINESS_LOGIC', 'BUSINESS_VALIDATION') and l['status'] in ('DETECTED', 'INFERRED') and l['confidence']['level'] != 'LOW' for l in m['functional_responsibilities'])]
        entry = [m['fqn'] for m in members if any(l['category'] == 'API_AND_APPLICATION_ENTRY' and l['status'] == 'DETECTED' for l in m['functional_responsibilities'])]
        technical_share = counts['NON_FUNCTIONAL'] / len(members)
        business = bool(entities or repositories or logic)
        if business and technical_share < share:
            kind = 'BUSINESS'
        elif not business and technical_share >= share:
            kind = 'TECHNICAL'
        else:
            kind = 'MIXED'
        notes = []
        technical = [m['simple_name'] for m in members if m['primary_classification'] == 'NON_FUNCTIONAL']
        if technical and kind != 'TECHNICAL':
            notes.append(f'contains {len(technical)} non-functional class(es) ({", ".join(sorted(technical)[:4])}) that are not part of the business capability')
        if any(m['architectural_role']['role'] == 'APPLICATION' for m in members):
            notes.append('contains the application bootstrap class')
        out[domain['id']] = dict(id=domain['id'], name=domain['name'], kind=kind, class_count=len(members), classes=sorted(c['fqn'] for c in members),
                                 primary_counts=dict(sorted(counts.items())), entities=sorted(entities), repositories=sorted(repositories), entry_classes=sorted(entry),
                                 boundary_confidence=dict(value=domain.get('confidence'), note=domain.get('confidence_note') or 'Candidate-domain confidence from the domain discovery heuristic; not a calibrated probability.'),
                                 basis=f'{len(entities)} entity class(es), {len(repositories)} repository class(es), {len(logic)} class(es) with business logic or validation, {counts["NON_FUNCTIONAL"]} of {len(members)} classes non-functional (technical threshold {share:.0%})',
                                 boundary_notes=notes, source='CANDIDATE_DOMAIN_DISCOVERY', nonfunctional_concerns=[], implications=[])
    return out


def _associate_capabilities(components, capabilities, model, domain_of):
    for fqn, comp in components.items():
        did = domain_of.get(fqn)
        if did in capabilities:
            cap = capabilities[did]
            comp['business_capabilities'].append(dict(id=did, name=cap['name'], kind=cap['kind'], relation='MEMBER', confidence=cap['boundary_confidence']))
    for (source, target) in model.owner_edges:
        s, t = domain_of.get(source), domain_of.get(target)
        if s and t and s != t and t in capabilities and source in components:
            if not any(c['id'] == t for c in components[source]['business_capabilities']):
                components[source]['business_capabilities'].append(dict(id=t, name=capabilities[t]['name'], kind=capabilities[t]['kind'], relation='USES', confidence=capabilities[t]['boundary_confidence']))


# ------------------------------------------------------------------------------------------ dependencies
def _concerns(comp):
    return sorted({l['category'] for l in comp['non_functional_responsibilities'] if l['status'] == 'DETECTED'})


def _dependencies(model, components, domain_of, capabilities, rules):
    edges = []
    for (source, target), kinds in sorted(model.owner_edges.items()):
        if source not in components or target not in components:
            continue
        s, t = components[source], components[target]
        same = domain_of.get(source) == domain_of.get(target)
        if t['architectural_role']['role'] == 'REPOSITORY' or any(l['category'] == 'BUSINESS_DATA_ACCESS' and l['status'] == 'DETECTED' for l in t['functional_responsibilities']):
            relation = 'DATA_ACCESS'
        elif t['primary_classification'] == 'NON_FUNCTIONAL':
            relation = 'TECHNICAL'
        elif same:
            relation = 'BUSINESS'
        else:
            relation = 'BUSINESS_CROSS_CAPABILITY'
        refs = [dict(kind=r['kind'], text=r['text'], line=r.get('line')) for r in model.references(source, target, 3)]
        edges.append(dict(id=stable_id('resp-dependency', source + '|' + target), source=source, target=target, relation=relation, direct=True, edge_kinds=dict(sorted(kinds.items())),
                          source_capability=domain_of.get(source), target_capability=domain_of.get(target), crosses_capability=not same,
                          concerns=_concerns(t), evidence=refs, basis='BYTECODE_EDGE'))
        s['dependencies'].append(dict(target=target, relation=relation, crosses_capability=not same))
        t['dependents'].append(dict(source=source, relation=relation, crosses_capability=not same))
    external = _external_libraries(model, components, domain_of, capabilities, rules)
    return edges, external


def _external_libraries(model, components, domain_of, capabilities, rules):
    families = {}
    for edge in model.external_edges:
        target, source = edge['target'], model.owners.get(edge['source'], edge['source'])
        if target.startswith('java.') or source not in components:
            continue
        family = next((f for f in rules['libraries'] if _hit(f['_match'], target)), None)
        key = family['id'] if family else 'other:' + '.'.join(target.split('.')[:3])
        entry = families.setdefault(key, dict(id=key, name=family['name'] if family else '.'.join(target.split('.')[:3]), concerns=family['concerns'] if family else [], known_family=bool(family),
                                              dependents=set(), types=Counter(), dependency_types=Counter()))
        entry['dependents'].add(source)
        entry['types'][target] += 1
        entry['dependency_types'][edge['dependency_type']] += 1
    out = []
    for key, entry in sorted(families.items()):
        dependents = sorted(entry['dependents'])
        caps = sorted({domain_of.get(d) for d in dependents} - {None})
        out.append(dict(id=stable_id('resp-library', key), family=key, name=entry['name'], concerns=entry['concerns'], known_family=entry['known_family'], dependents=dependents,
                        dependent_count=len(dependents), capabilities=[dict(id=c, name=capabilities[c]['name']) for c in caps if c in capabilities], capability_count=len(caps),
                        top_types=[t for t, _ in entry['types'].most_common(5)], dependency_types=dict(sorted(entry['dependency_types'].items()))))
    return out


def _cross_cutting(model, components, dependencies, external, domain_of, capabilities, rules):
    minimum = rules['cross_cutting']['min_capabilities']
    out = []
    by_target = defaultdict(list)
    for edge in dependencies:
        by_target[edge['target']].append(edge)
    for target, incoming in sorted(by_target.items()):
        comp = components[target]
        users = sorted({e['source'] for e in incoming})
        caps = {domain_of.get(u) for u in users} | {domain_of.get(target)}
        caps.discard(None)
        outside = [e for e in incoming if e['crosses_capability']]
        # One other domain calling a class is an ordinary cross-domain dependency (the domain dependency matrix shows it). A component is
        # shared when classes of at least `min_capabilities` OTHER candidate domains use it.
        consumers = {domain_of.get(e['source']) for e in outside} - {None}
        if len(consumers) < minimum:
            continue
        if comp['primary_classification'] == 'NON_FUNCTIONAL':
            kind, form = 'SHARED_INFRASTRUCTURE', 'SHARED_LIBRARY_OR_MODULE'
        elif any(l['category'] == 'DOMAIN_MODEL' and l['status'] == 'DETECTED' for l in comp['functional_responsibilities']):
            kind, form = 'SHARED_DOMAIN_MODEL', 'SHARED_LIBRARY_OR_PUBLISHED_CONTRACT'
        elif any(l['category'] == 'BUSINESS_DATA_ACCESS' and l['status'] == 'DETECTED' for l in comp['functional_responsibilities']):
            kind, form = 'SHARED_DATA_ACCESS', 'DECIDE_DATA_OWNER'
        else:
            kind, form = 'SHARED_FUNCTIONAL_COMPONENT', 'DECIDE_OWNER'
        names = sorted(capabilities[c]['name'] for c in caps if c in capabilities)
        guidance = {
            'SHARED_LIBRARY_OR_MODULE': f'Keep {comp["simple_name"]} as a library or module that each service includes. A separate service would add a network call to each of its {len(users)} dependent class(es) and would not remove the coupling.',
            'SHARED_LIBRARY_OR_PUBLISHED_CONTRACT': f'{comp["simple_name"]} is a persistent model used by {len(users)} class(es) across {", ".join(names)}. Decide which capability owns the data, then share it as a library or replace it with a published contract.',
            'DECIDE_DATA_OWNER': f'{comp["simple_name"]} reads and writes data that {len(users)} class(es) in {", ".join(names)} use. Decide which capability owns that data; the others would then call it through a contract instead of sharing the repository.',
            'DECIDE_OWNER': f'{comp["simple_name"]} carries business behavior and is used across {", ".join(names)}. Assign it to one capability or duplicate it deliberately before separating them.'}[form]
        refs = [dict(source=e['source'], kind=r['kind'], text=r['text'], line=r['line']) for e in outside[:3] for r in e['evidence'][:1]]
        out.append(dict(id=stable_id('resp-cross', 'class|' + target), name=comp['simple_name'], component=target, kind=kind, concerns=_concerns(comp), scope='CROSS_CAPABILITY',
                        dependents=users, dependent_count=len(users), capabilities=[dict(id=c, name=capabilities[c]['name']) for c in sorted(caps) if c in capabilities], capability_count=len(caps),
                        deployment_form=form, guidance=guidance, change_impact=f'A change to {comp["simple_name"]} can affect {len(users)} class(es) in {len(caps)} candidate domain(s): {", ".join(names)}.',
                        evidence=refs, status='DETECTED', basis='BYTECODE_EDGE'))
    for library in external:
        if library['capability_count'] >= minimum and library['known_family'] and library['concerns']:
            names = [c['name'] for c in library['capabilities']]
            out.append(dict(id=stable_id('resp-cross', 'library|' + library['family']), name=library['name'], component=library['family'], kind='EXTERNAL_LIBRARY', concerns=library['concerns'], scope='CROSS_CAPABILITY',
                            dependents=library['dependents'], dependent_count=library['dependent_count'], capabilities=library['capabilities'], capability_count=library['capability_count'],
                            deployment_form='LIBRARY_DEPENDENCY', guidance=f'{library["name"]} is a library that {library["dependent_count"]} class(es) in {", ".join(names)} already include. Each extracted service includes it as a dependency; it is not a service candidate.',
                            change_impact=f'Upgrading {library["name"]} touches {library["dependent_count"]} class(es) in {library["capability_count"]} candidate domain(s).', evidence=[], status='DETECTED', basis='BYTECODE_EDGE'))
    return sorted(out, key=lambda c: (-c['capability_count'], -c['dependent_count'], c['name']))


# ------------------------------------------------------------------------------------------ risks
def _risk(rules, rule_id, builder_ids, description, affected, detection, confidence, method_note=None, priority=0):
    rule = rules['risks'][rule_id]
    return dict(id=stable_id('resp-risk', rule_id + '|' + description), rule_id=rule_id, category=rule['category'], title=rule['title'], description=description, severity=rule['severity'],
                affected_components=sorted(affected)[:40], affected_count=len(affected), evidence_ids=sorted(set(builder_ids))[:20], detection_status=detection, consequence_status='INFERRED',
                consequence=rule['consequence'], potential_impact=rule['impact'], confidence=confidence, investigate=rule['investigate'], runtime_validation_required=rule['runtime_validation'],
                priority_basis=f'{rule["severity"]} by rule {rule_id}; ordered by the number of affected components', priority=priority or len(affected))


def _risks(model, builder, components, capabilities, cross, domain_of, rules, limitations):
    risks = []
    confidence = lambda level, basis: dict(level=level, basis=basis, calibrated=False)
    detected = lambda fqn, rule_ids: any(set(l['rule_ids']) & rule_ids and l['status'] == 'DETECTED' for l in components[fqn]['non_functional_responsibilities'])
    http_entries = [i for i in model.entry_points.get('items', []) if i.get('http_methods')]
    mutating = [i for i in http_entries if set(i['http_methods']) & MUTATING_HTTP]
    entry_label = lambda i: '/'.join(i['http_methods']) + ' ' + ((i.get('paths') or ['?'])[0])
    controlled = {fqn for fqn in components if detected(fqn, ACCESS_CONTROL_RULES)}
    handlers = sorted({i['handler_class'] for i in http_entries if i['handler_class'] in components})
    # security: absence of a detectable access-control reference is an inference, never proof
    controlled = {fqn for fqn in components if detected(fqn, ACCESS_CONTROL_RULES)}
    handlers = sorted({i['handler_class'] for i in http_entries if i['handler_class'] in components})
    if http_entries and not controlled:
        hardening = sorted(f for f in components if detected(f, {'SEC-BINDING', 'SEC-CRYPTO'}))
        ident = builder.add(handlers[0] if handlers else next(iter(components)), 'ABSENCE', f'No reference to an access-control API (Spring Security, jakarta.annotation.security, HttpServletRequest identity calls) was found in {len(components)} analyzed classes', 'MEDIUM', handlers[0] if handlers else next(iter(components)))
        text = (f'{len(http_entries)} HTTP entry point(s), {len(mutating)} of them changing data ({", ".join(sorted({entry_label(i) for i in mutating})[:4])}), '
                f'have no detectable authentication or authorization reference in {len(components)} analyzed classes'
                + (f'; input-binding restrictions exist in {len(hardening)} class(es) ({", ".join(short(h) for h in hardening[:3])}) but they do not control who may call' if hardening else ''))
        risks.append(_risk(rules, 'RISK-SEC-NO-CONTROL', [ident], text, handlers, 'INFERRED', confidence('MEDIUM', 'absence of any access-control reference within the analyzed bytecode; a gateway or platform control would not appear here')))
    elif http_entries and controlled:
        uncontrolled = [h for h in handlers if h not in controlled]
        if uncontrolled:
            ident = builder.add(uncontrolled[0], 'ABSENCE', f'{short(uncontrolled[0])} has no access-control reference while {len(controlled)} other class(es) do', 'MEDIUM', uncontrolled[0])
            risks.append(_risk(rules, 'RISK-SEC-PARTIAL', [ident], f'{len(uncontrolled)} of {len(handlers)} entry-point class(es) have no detectable access control: {", ".join(short(u) for u in uncontrolled[:4])}', uncontrolled, 'INFERRED',
                               confidence('MEDIUM', 'absence of a reference in classes that otherwise have access-control evidence elsewhere')))
    # observability
    if not any(detected(f, INSTRUMENTATION_RULES) for f in components) and components:
        first = sorted(components)[0]
        ident = builder.add(first, 'ABSENCE', f'No reference to a logging, metrics or tracing API was found in {len(components)} analyzed classes', 'MEDIUM', first)
        risks.append(_risk(rules, 'RISK-OBS-NO-INSTRUMENTATION', [ident], f'None of the {len(components)} analyzed classes references a logging, metrics or tracing API', sorted(components)[:40], 'INFERRED',
                           confidence('MEDIUM', 'absence within the analyzed bytecode; output written by the framework itself would not appear here'), priority=len(components)))
    # eager fetching and unbounded queries
    for fqn, comp in sorted(components.items()):
        eager = [builder.evidence[e] for l in comp['non_functional_responsibilities'] if 'PERF-EAGER-FETCH' in l['rule_ids'] for e in l['evidence_ids']]
        if eager:
            fields = sorted({e['member'].replace('field ', '') for e in eager if e['member']})
            risks.append(_risk(rules, 'RISK-PERF-EAGER-FETCH', [e['id'] for e in eager], f'{comp["simple_name"]} loads {len(fields)} relationship(s) eagerly: {", ".join(fields)}', [fqn], 'DETECTED',
                               confidence('MEDIUM', 'the eager fetch setting is read from the annotation; its cost depends on data and queries, which are not measured here')))
        if any(l['category'] == 'BUSINESS_DATA_ACCESS' and any(r.startswith('FUNC-DATA-ACCESS') for r in l['rule_ids']) for l in comp['functional_responsibilities']):
            for method in (model.facts.get(fqn) or {}).get('methods', []):
                if method.get('abstract') and not method.get('synthetic') and base_type(method.get('returns') or '') in COLLECTION_RETURNS and not any(base_type(p).endswith(('Pageable', 'Sort')) for p in method.get('parameters', [])):
                    ident = builder.add(fqn, 'SIGNATURE', f'{method_label(fqn, method["name"])} returns {short(method["returns"])} and takes no Pageable', 'MEDIUM', fqn, method['signature'], member_lines=method.get('line_range'))
                    risks.append(_risk(rules, 'RISK-PERF-UNBOUNDED-QUERY', [ident], f'{method_label(fqn, method["name"])} returns a whole {short(method["returns"])} with no paging', [fqn], 'DETECTED',
                                       confidence('MEDIUM', 'the return type is read from the signature; the table size is unknown')))
    # shared persistent models across candidate domains
    entities = {f for f, c in components.items() if any(l['category'] == 'DOMAIN_MODEL' and l['status'] == 'DETECTED' for l in c['functional_responsibilities'])}
    pairs = defaultdict(lambda: dict(entities=set(), users=set()))
    for edge in model.owner_edges:
        source, target = edge
        if target in entities and domain_of.get(source) and domain_of.get(target) and domain_of[source] != domain_of[target] and source in components:
            pairs[(domain_of[target], domain_of[source])]['entities'].add(target)
            pairs[(domain_of[target], domain_of[source])]['users'].add(source)
    for (owner, user), pair in sorted(pairs.items()):
        if owner not in capabilities or user not in capabilities:
            continue
        shown = sorted(short(e) for e in pair['entities'])
        ident = builder.add(sorted(pair['entities'])[0], 'DEPENDENCY', f'{len(pair["users"])} class(es) of {capabilities[user]["name"]} depend on {", ".join(shown)} of {capabilities[owner]["name"]}', 'STRONG', sorted(pair['entities'])[0])
        risks.append(_risk(rules, 'RISK-DATA-SHARED-MODEL', [ident], f'{len(pair["users"])} class(es) in {capabilities[user]["name"]} depend on {len(pair["entities"])} persistent class(es) assigned to {capabilities[owner]["name"]}: {", ".join(shown)}',
                           sorted(pair['entities'] | pair['users']), 'DETECTED', confidence('HIGH', 'the dependency edges and persistence annotations are detected; ownership of the data is a decision, not a fact')))
    # transactions that touch several candidate domains
    for fqn, comp in sorted(components.items()):
        for method in comp['methods']:
            tx = [l for l in method['labels'] if l['category'] == 'DATA_INTEGRITY' and l['status'] == 'DETECTED']
            if not tx:
                continue
            raw = next((m for m in (model.facts.get(fqn) or {}).get('methods', []) if m['signature'] == method['signature']), None)
            touched = {domain_of.get(s['owner']) for s in (raw or {}).get('invokes', []) if s['owner'] in components} - {None}
            if len(touched) >= 2:
                names = sorted(capabilities[d]['name'] for d in touched if d in capabilities)
                risks.append(_risk(rules, 'RISK-DATA-TX-SPAN', tx[0]['evidence_ids'], f'{method_label(fqn, method["name"])} is transactional and calls classes of {len(touched)} candidate domains: {", ".join(names)}', [fqn], 'DETECTED',
                                   confidence('MEDIUM', 'the transaction annotation and the call targets are detected; the actual data written is not')))
    # mutable static state
    for fqn, comp in sorted(components.items()):
        found = [l for l in comp['non_functional_responsibilities'] if 'STRUCT-STATIC-STATE' in l['rule_ids']]
        if found:
            risks.append(_risk(rules, 'RISK-SCAL-STATIC-STATE', found[0]['evidence_ids'], f'{comp["simple_name"]} declares {found[0]["evidence_count"]} static non-final field(s)', [fqn], 'DETECTED',
                               confidence('HIGH', 'the field modifiers are read directly from the class file')))
    # many responsibilities
    limit = rules['classification']['responsibility_limit']
    for fqn, comp in sorted(components.items()):
        cats = sorted({l['category'] for l in comp['functional_responsibilities'] if l['status'] == 'DETECTED'} | {l['category'] for l in comp['non_functional_responsibilities'] if l['status'] == 'DETECTED' and l['mixes']})
        if len(cats) >= limit:
            risks.append(_risk(rules, 'RISK-MAINT-RESPONSIBILITIES', [e for l in comp['functional_responsibilities'] + comp['non_functional_responsibilities'] if l['status'] == 'DETECTED' and (l['side'] == 'FUNCTIONAL' or l['mixes']) for e in l['evidence_ids'][:1]],
                               f'{comp["simple_name"]} has {len(cats)} distinct detected responsibilities: {", ".join(cats)}', [fqn], 'DETECTED', confidence('MEDIUM', f'threshold of {limit} categories is documented in the rules file; it is a structural indicator')))
    # shared components that are not persistent models
    for item in cross:
        if item['kind'] in ('SHARED_INFRASTRUCTURE', 'SHARED_FUNCTIONAL_COMPONENT', 'SHARED_DATA_ACCESS'):
            risks.append(_risk(rules, 'RISK-MAINT-SHARED-COMPONENT', [], f'{item["name"]} is used by {item["dependent_count"]} class(es) in {item["capability_count"]} candidate domains: {", ".join(c["name"] for c in item["capabilities"])}', [item['component']], 'DETECTED',
                               confidence('HIGH', 'dependency edges are detected from bytecode')))
    # remote calls with no protection
    remote = sorted(f for f in components if detected(f, REMOTE_CALL_RULES))
    if remote and not any(detected(f, PROTECTIVE_RULES) for f in components):
        ident = builder.add(remote[0], 'ABSENCE', f'{len(remote)} class(es) call other systems and none references a timeout, retry or circuit-breaker API', 'MEDIUM', remote[0])
        risks.append(_risk(rules, 'RISK-REL-NO-RESILIENCE', [ident], f'{len(remote)} class(es) call other systems ({", ".join(short(r) for r in remote[:4])}) and none has a detectable timeout, retry or circuit breaker', remote, 'INFERRED',
                           confidence('MEDIUM', 'a timeout set in configuration files would not appear in a compiled artifact')))
    return sorted(risks, key=lambda r: (SEVERITY_RANK[r['severity']], -r['priority'], r['rule_id'], r['id']))


# ------------------------------------------------------------------------------------------ packages and implications
def _packages(model, components):
    out = []
    for package, classes in model.packages.items():
        members = [components[c] for c in classes if c in components]
        if not members:
            continue
        counts = Counter(m['primary_classification'] for m in members)
        caps = sorted({c['name'] for m in members for c in m['business_capabilities'] if c['relation'] == 'MEMBER'})
        categories = Counter(l['category'] for m in members for l in m['functional_responsibilities'] + m['non_functional_responsibilities'] if l['status'] == 'DETECTED')
        technical = counts['NON_FUNCTIONAL'] / len(members)
        kind = 'TECHNICAL' if technical >= .5 else 'BUSINESS' if counts['FUNCTIONAL'] + counts['FUNCTIONAL_SUPPORT'] + counts['MIXED'] >= max(1, len(members) / 2) else 'UNCLEAR'
        out.append(dict(package=package, class_count=len(members), primary_counts=dict(sorted(counts.items())), kind=kind, capabilities=caps, mixed=counts['MIXED'] > 0,
                        unclear_boundary=len(caps) > 1 or counts['UNCERTAIN'] > 0, top_categories=[c for c, _ in categories.most_common(6)],
                        note='Package names are supporting evidence only; this reading comes from the classes inside.'))
    return out


def _capability_implications(capabilities, components, cross, risks):
    by_class = defaultdict(list)
    for risk in risks:
        for fqn in risk['affected_components']:
            by_class[fqn].append(risk)
    for cap in capabilities.values():
        members = set(cap['classes'])
        cap_risks = sorted({r['id']: r for fqn in members for r in by_class.get(fqn, [])}.values(), key=lambda r: (SEVERITY_RANK[r['severity']], r['rule_id']))
        cap['risk_ids'] = [r['id'] for r in cap_risks]
        concerns = Counter(l['category'] for fqn in members for l in components[fqn]['non_functional_responsibilities'] if l['status'] == 'DETECTED')
        cap['nonfunctional_concerns'] = [dict(category=c, class_count=n) for c, n in sorted(concerns.items())]
        shared = [c for c in cross if any(d in members for d in c['dependents']) or c['component'] in members]
        cap['cross_cutting_ids'] = [c['id'] for c in shared]
        implications = []
        if cap['kind'] == 'TECHNICAL':
            implications.append(dict(kind='NOT_AN_EXTRACTION_CANDIDATE', severity='MEDIUM', text=f'{cap["name"]} holds platform concerns ({", ".join(c["category"] for c in cap["nonfunctional_concerns"][:4]) or "none detected"}) rather than a business capability. Keep it as shared configuration or a library, not a service.', evidence=[]))
        for risk in cap_risks:
            if risk['rule_id'] == 'RISK-DATA-SHARED-MODEL':
                implications.append(dict(kind='RESOLVE_SHARED_DATA_MODEL', severity=risk['severity'], text=f'Before separating {cap["name"]}: {risk["description"]}.', evidence=[risk['id']]))
            elif risk['rule_id'] in ('RISK-SEC-NO-CONTROL', 'RISK-SEC-PARTIAL'):
                implications.append(dict(kind='SECURITY_CONTROL_TO_DECIDE', severity=risk['severity'], text=f'An extracted {cap["name"]} service needs its own authentication and authorization decision: {risk["description"]}.', evidence=[risk['id']]))
            elif risk['rule_id'] == 'RISK-DATA-TX-SPAN':
                implications.append(dict(kind='DISTRIBUTED_TRANSACTION', severity=risk['severity'], text=risk['description'] + '; separating the domains makes this a distributed transaction.', evidence=[risk['id']]))
            elif risk['rule_id'] == 'RISK-PERF-EAGER-FETCH':
                implications.append(dict(kind='VALIDATE_PERFORMANCE', severity='MEDIUM', text=f'{risk["description"]}. Compare with measured database calls per request before moving either side of the relationship.', evidence=[risk['id']]))
        for item in shared:
            if item['component'] in members and item['kind'] in ('SHARED_DOMAIN_MODEL', 'SHARED_FUNCTIONAL_COMPONENT', 'SHARED_DATA_ACCESS'):
                implications.append(dict(kind='OWNS_SHARED_COMPONENT', severity='MEDIUM', text=f'{cap["name"]} owns {item["name"]}, which {item["dependent_count"]} class(es) in other candidate domains depend on. {item["guidance"]}', evidence=[item['id']]))
            elif item['kind'] in ('SHARED_INFRASTRUCTURE', 'EXTERNAL_LIBRARY') and item['component'] not in members:
                implications.append(dict(kind='SHARED_INFRASTRUCTURE', severity='LOW', text=f'{cap["name"]} depends on shared {item["name"]}. {item["guidance"]}', evidence=[item['id']]))
        if cap['kind'] != 'TECHNICAL' and not any(i['severity'] == 'HIGH' for i in implications):
            implications.append(dict(kind='NO_BLOCKING_CONSTRAINT_DETECTED', severity='LOW',
                                     text=f'No high-impact non-functional constraint was detected for {cap["name"]} in the analyzed bytecode. Runtime behavior, configuration and data volumes were not examined.', evidence=[]))
        cap['implications'] = sorted(implications, key=lambda i: (SEVERITY_RANK[i['severity']], i['kind'], i['text']))[:12]


# ------------------------------------------------------------------------------------------ validation and output
def validate(result, model) -> dict:
    """Reject anything that does not resolve to the snapshot: classes, methods, lines and evidence ids."""
    evidence, components = result['evidence'], result['components']
    rejected, checked = [], 0
    methods = {c: {m['signature']: m for m in (model.facts.get(c) or {}).get('methods', [])} for c in model.facts}
    for ident, item in list(evidence.items()):
        checked += 1
        cls, member = item['class_name'], item['member']
        problem = None
        if cls not in model.facts and cls not in model.classes:
            problem = 'class not in snapshot'
        elif member and not member.startswith('field ') and member not in methods.get(cls, {}):
            problem = 'method not in class'
        elif item['location'].get('member_line_range') and member and not member.startswith('field ') and item['location']['member_line_range'] != (methods[cls][member].get('line_range') or None):
            problem = 'line outside method'
        elif item['location']['start_line'] is not None and member and not member.startswith('field '):
            lines = methods[cls][member].get('line_range') or [None, None]
            sites = [s.get('line') for s in methods[cls][member].get('invokes', [])] + [r.get('line') for r in methods[cls][member].get('type_refs', [])]
            if item['location']['start_line'] not in (lines[0], *sites) and not (lines[0] and lines[1] and lines[0] <= item['location']['start_line'] <= lines[1]):
                problem = 'line outside method'
        if problem:
            rejected.append(dict(id=ident, reason=problem))
            del evidence[ident]
    for comp in components.values():
        for label in comp['functional_responsibilities'] + comp['non_functional_responsibilities']:
            label['evidence_ids'] = [e for e in label['evidence_ids'] if e in evidence]
            if not label['evidence_ids']:
                label['status'] = 'UNVERIFIED'
                label['confidence'] = dict(level='LOW', basis='its evidence did not resolve to the snapshot', calibrated=False)
        for method in comp['methods']:
            method['labels'] = [l for l in method['labels'] if any(e in evidence for e in l['evidence_ids'])]
    return dict(evidence_checked=checked, evidence_rejected=len(rejected), rejected=rejected[:20])


def _metadata(model, rules):
    artifact = (model.result.get('artifact') or {})
    return dict(engine_version=ENGINE_VERSION, rules_version=rules['rules_version'], rules_reviewed=str(rules['reviewed']), snapshot_algorithm_version=model.result.get('algorithm_version'),
                artifact_sha256=artifact.get('sha256'), source_revision=artifact.get('sha256'), source_revision_kind='ARTIFACT_SHA256 (the analysis reads a compiled artifact; no repository commit is available)',
                analyzed_class_count=len(model.classes), derived_from='ANALYSIS_SNAPSHOT', confidence=rules['confidence'])


def _taxonomy(rules):
    return dict(functional={k: dict(label=v['label'], description=v['description'], limit=v['limit']) for k, v in rules['taxonomy']['functional'].items()},
                nonfunctional={k: dict(label=v['label'], description=v['description'], limit=v['limit']) for k, v in rules['taxonomy']['nonfunctional'].items()},
                primary_classifications=dict(
                    FUNCTIONAL='Implements or enforces business behavior (entry points, logic, validation, orchestration).',
                    FUNCTIONAL_SUPPORT='Supports a capability without implementing its rules (data access, domain model).',
                    NON_FUNCTIONAL='Implements a technical concern with no business behavior detected.',
                    MIXED='Has a detected business responsibility and its own code runs a non-functional concern (it calls or holds the concern API).',
                    UNCERTAIN='No detected evidence establishes a responsibility; any label rests on a name only.'),
                statuses=dict(DETECTED='Established directly by a fact in the bytecode.', INFERRED='A reasoned reading of one or more facts; not established as a fact.', UNVERIFIED='Needs runtime, configuration or test evidence that is not available.'))


def _standing_limitations(model):
    notes = ['Evidence comes from compiled bytecode: source files, configuration files and runtime behavior are not examined.',
             'Method bodies expose call sites, type references and branch counts; catch blocks and loop structure are not recorded, so error handling and repeated work cannot be established.',
             'Absence of a detected mechanism is not proof that the mechanism is absent: gateways, configuration files and platform controls do not appear in bytecode.']
    if (model.result.get('source_store') or {}).get('status') != 'SOURCE_CAPTURED':
        notes.append('The artifact contains no .java files, so file paths are derived from the package and the SourceFile attribute and are marked as derived; line numbers come from the bytecode line table.')
    notes.append('Business capabilities are the candidate domains found by ArchIntel; they are heuristic boundaries that an architect must validate.')
    return notes


def _summary(result):
    comps = result['components'].values()
    functional, nonfunctional = Counter(), Counter()
    for c in comps:
        for l in c['functional_responsibilities']:
            functional[l['category']] += 1
        for l in c['non_functional_responsibilities']:
            nonfunctional[l['category']] += 1
    return dict(classes=len(result['components']), by_primary=dict(sorted(Counter(c['primary_classification'] for c in comps).items())), functional_categories=dict(sorted(functional.items())),
                nonfunctional_categories=dict(sorted(nonfunctional.items())), capabilities=len(result['capabilities']), capability_kinds=dict(sorted(Counter(c['kind'] for c in result['capabilities'].values()).items())),
                cross_cutting=len(result['cross_cutting']), dependencies=len(result['dependencies']), risks=len(result['risks']), risks_by_severity=dict(sorted(Counter(r['severity'] for r in result['risks']).items())),
                evidence_items=len(result['evidence']), evidence_rejected=result['validation']['evidence_rejected'], statuses=dict(sorted(Counter(l['status'] for c in comps for l in c['functional_responsibilities'] + c['non_functional_responsibilities']).items())))


# ------------------------------------------------------------------------------------------ API views
def summary_view(result: dict) -> dict:
    """Counts, capabilities, cross-cutting components, risks and limits; no per-component rows and no evidence bodies."""
    if result['status'] != 'AVAILABLE':
        return result
    return dict(status='AVAILABLE', analysis_metadata=result['analysis_metadata'], taxonomy=result['taxonomy'], summary=result['summary'], validation=result['validation'],
                capabilities=sorted(result['capabilities'].values(), key=lambda c: c['name']), packages=result['packages'], cross_cutting=result['cross_cutting'],
                external_libraries=[{k: v for k, v in lib.items() if k != 'dependents'} for lib in result['external_libraries']], risks=result['risks'], limitations=result['limitations'])


def row(component: dict) -> dict:
    """The compact component row used by lists: categories and statuses, no evidence bodies."""
    brief = lambda labels: [dict(category=l['category'], status=l['status'], confidence=l['confidence']['level']) for l in labels]
    return dict(id=component['id'], fqn=component['fqn'], simple_name=component['simple_name'], package=component['package'], primary_classification=component['primary_classification'],
                architectural_role=component['architectural_role'], capability=next((dict(id=c['id'], name=c['name'], kind=c['kind']) for c in component['business_capabilities'] if c['relation'] == 'MEMBER'), None),
                functional=brief(component['functional_responsibilities']), non_functional=brief(component['non_functional_responsibilities']), risk_count=len(component['risk_ids']),
                dependency_count=len(component['dependencies']), dependent_count=len(component['dependents']), uncertain=bool(component['uncertainties']))


def list_components(result: dict, primary=None, functional=None, concern=None, capability=None, status=None, confidence=None, risk=None, q=None, offset=0, limit=50) -> dict:
    """Filtered, paginated rows in a stable order. `status` and `confidence` apply to the labels selected by `functional` or `concern`, or to any label."""
    if result['status'] != 'AVAILABLE':
        return dict(result, items=[], total=0, offset=offset, limit=limit)
    risk_rules = {r['id']: r['rule_id'] for r in result['risks']}
    rows = []
    for component in result['components'].values():
        if primary and component['primary_classification'] != primary:
            continue
        if capability and not any(c['id'] == capability and c['relation'] == 'MEMBER' for c in component['business_capabilities']):
            continue
        if risk and not any(risk_rules.get(i) == risk for i in component['risk_ids']):
            continue
        if q and q.lower() not in component['fqn'].lower():
            continue
        pool = [l for l in component['functional_responsibilities'] + component['non_functional_responsibilities']
                if (not functional or (l['side'] == 'FUNCTIONAL' and l['category'] == functional)) and (not concern or (l['side'] == 'NON_FUNCTIONAL' and l['category'] == concern))]
        if (functional or concern or status or confidence) and not any((not status or l['status'] == status) and (not confidence or l['confidence']['level'] == confidence) for l in pool):
            continue
        rows.append(row(component))
    rows.sort(key=lambda r: r['fqn'])
    return dict(status='AVAILABLE', items=rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)


def component_detail(model, result: dict, ident: str) -> dict | None:
    """One component with its evidence resolved; None when it is not in the snapshot."""
    if result['status'] != 'AVAILABLE':
        return None
    fqn = model.owners.get(ident, ident)
    component = result['components'].get(fqn)
    if not component:
        return None
    evidence, taxonomy = result['evidence'], result['taxonomy']
    detail = dict(component)
    for key in ('functional_responsibilities', 'non_functional_responsibilities'):
        detail[key] = [dict(label, evidence=[evidence[i] for i in label['evidence_ids'] if i in evidence],
                            limit=taxonomy['functional' if label['side'] == 'FUNCTIONAL' else 'nonfunctional'][label['category']]['limit']) for label in component[key]]
    detail['methods'] = [dict(m, labels=[dict(l, evidence=[evidence[i] for i in l['evidence_ids'] if i in evidence][:3]) for l in m['labels']]) for m in component['methods']]
    ids = set(component['risk_ids'])
    detail['risks'] = [r for r in result['risks'] if r['id'] in ids]
    detail['dependency_details'] = [d for d in result['dependencies'] if d['source'] == fqn]
    detail['dependent_details'] = [d for d in result['dependencies'] if d['target'] == fqn]
    detail['cross_cutting'] = [c for c in result['cross_cutting'] if c['component'] == fqn or fqn in c['dependents']]
    detail['capability_implications'] = [dict(capability=c['name'], implications=c['implications']) for c in result['capabilities'].values() if fqn in c['classes']]
    return detail


def list_risks(result: dict, category=None, detection=None, runtime=None, severity=None) -> dict:
    if result['status'] != 'AVAILABLE':
        return dict(result, items=[], total=0)
    items = [r for r in result['risks'] if (not category or r['category'] == category) and (not detection or r['detection_status'] == detection)
             and (runtime is None or r['runtime_validation_required'] == runtime) and (not severity or r['severity'] == severity)]
    return dict(status='AVAILABLE', items=items, total=len(items))
