"""Turn parsed class files into bounded, JSON-serialisable bytecode facts for a snapshot."""
from __future__ import annotations

from pathlib import Path
import re

from .bytecode import (ACC_ABSTRACT, ACC_ANNOTATION, ACC_BRIDGE, ACC_ENUM, ACC_FINAL, ACC_INTERFACE, ACC_PRIVATE,
    ACC_PROTECTED, ACC_PUBLIC, ACC_STATIC, ACC_SYNTHETIC, ACC_VARARGS, ClassFormatError, base_type, parse,
    parse_method_descriptor, signature_types, descriptor_type)

SCHEMA = 'bytecode-facts-1'
MAX_CLASSES = 50000
MAX_EXTERNAL_SITES_PER_CLASS = 300
PRIMITIVES = {'boolean', 'byte', 'char', 'short', 'int', 'long', 'float', 'double', 'void'}


def visibility(access: int) -> str:
    return 'public' if access & ACC_PUBLIC else 'private' if access & ACC_PRIVATE else 'protected' if access & ACC_PROTECTED else 'package'


def _annotation_view(items: list[dict] | None) -> list[dict]:
    return [dict(type=a['type'], values=a['values']) for a in items or []]


def java_signature(name: str, descriptor: str) -> str:
    params, result = parse_method_descriptor(descriptor)
    return f"{result} {name}({','.join(params)})"


def class_facts(data: bytes) -> dict:
    cf = parse(data)
    lambdas = cf.lambda_targets()
    attrs = cf.attributes
    inner_row = next((row for row in attrs.get('inner_classes', []) if row['inner'] == cf.name), None)
    enclosing = attrs.get('enclosing_method')
    outer = (enclosing or {}).get('owner') or (inner_row or {}).get('outer') or attrs.get('nest_host')
    anonymous = bool(inner_row and inner_row['simple_name'] is None) or bool(re.search(r'\$\d+$', cf.name))
    methods = []
    for m in cf.methods:
        params, returns = parse_method_descriptor(m['descriptor'])
        lambda_impls = []
        for site in m.get('indy', []):
            target = lambdas.get(site['bootstrap'])
            if target:
                lambda_impls.append(dict(target, line=site['line']))
        methods.append(dict(
            name=m['name'], descriptor=m['descriptor'], signature=java_signature(m['name'], m['descriptor']),
            parameters=params, returns=returns, visibility=visibility(m['access']),
            static=bool(m['access'] & ACC_STATIC), abstract=bool(m['access'] & ACC_ABSTRACT),
            synthetic=bool(m['access'] & ACC_SYNTHETIC), bridge=bool(m['access'] & ACC_BRIDGE),
            varargs=bool(m['access'] & ACC_VARARGS), lambda_body=m['name'].startswith('lambda$'),
            kind='constructor' if m['name'] == '<init>' else 'static_initializer' if m['name'] == '<clinit>' else 'method',
            annotations=_annotation_view(m.get('annotations')),
            parameter_annotations=[_annotation_view(p) for p in m.get('parameter_annotations', [])],
            exceptions=m.get('exceptions', []), generic_signature=m.get('signature'),
            generic_types=signature_types(m.get('signature')), deprecated=bool(m.get('deprecated')),
            code_length=m.get('code_length', 0), branch_count=m.get('branch_count', 0),
            line_range=m.get('line_range'), invokes=m.get('invokes', []), field_access=m.get('field_access', []),
            type_refs=m.get('type_refs', []), lambdas=lambda_impls, sites_truncated=m.get('sites_truncated', False)))
    fields = [dict(name=f['name'], descriptor=f['descriptor'], type=descriptor_type(f['descriptor']),
        visibility=visibility(f['access']), static=bool(f['access'] & ACC_STATIC), final=bool(f['access'] & ACC_FINAL),
        synthetic=bool(f['access'] & ACC_SYNTHETIC), annotations=_annotation_view(f.get('annotations')),
        generic_types=signature_types(f.get('signature')), deprecated=bool(f.get('deprecated'))) for f in cf.fields]
    return dict(fqn=cf.name, major=cf.major, java_target=max(1, cf.major - 44), super_name=cf.super_name,
        interfaces=cf.interfaces, access=cf.access, visibility=visibility(cf.access),
        interface=bool(cf.access & ACC_INTERFACE), abstract=bool(cf.access & ACC_ABSTRACT),
        enum=bool(cf.access & ACC_ENUM), annotation_type=bool(cf.access & ACC_ANNOTATION),
        synthetic=bool(cf.access & ACC_SYNTHETIC), final=bool(cf.access & ACC_FINAL),
        source_file=attrs.get('source_file'), deprecated=bool(attrs.get('deprecated')),
        annotations=_annotation_view(attrs.get('annotations')), generic_signature=attrs.get('signature'),
        generic_types=signature_types(attrs.get('signature')), outer_class=outer if outer != cf.name else None,
        anonymous=anonymous, enclosing_method=enclosing, fields=fields, methods=methods)


def extract(classes_dir: Path, owned: set[str] | None = None) -> dict:
    """Parse every owned .class under classes_dir. Unparseable classes are counted, never guessed."""
    classes, failures = {}, []
    files = sorted(classes_dir.rglob('*.class'))
    for path in files[:MAX_CLASSES]:
        try:
            facts = class_facts(path.read_bytes())
        except (ClassFormatError, OSError) as error:
            failures.append(dict(path=path.relative_to(classes_dir).as_posix(), reason=str(error)))
            continue
        if owned is not None and facts['fqn'] not in owned:
            continue
        classes[facts['fqn']] = facts
    return dict(schema=SCHEMA, classes=classes, parse_failures=failures[:200], parse_failure_count=len(failures),
        truncated=len(files) > MAX_CLASSES, class_count=len(classes))


def referenced_types(facts: dict) -> dict[str, set[str]]:
    """Typed references from one class, keyed by dependency type. Used by the fixture audit (WP9)."""
    out: dict[str, set[str]] = {k: set() for k in ('INHERITANCE', 'INTERFACE', 'FIELD_TYPE', 'PARAMETER_TYPE', 'RETURN_TYPE',
        'ANNOTATION', 'GENERIC_TYPE', 'EXCEPTION', 'METHOD_CALL', 'FIELD_ACCESS', 'TYPE_REFERENCE')}
    if facts.get('super_name'):
        out['INHERITANCE'].add(facts['super_name'])
    out['INTERFACE'].update(facts.get('interfaces', []))
    out['ANNOTATION'].update(a['type'] for a in facts.get('annotations', []))
    out['GENERIC_TYPE'].update(facts.get('generic_types', []))
    for field in facts.get('fields', []):
        if field['synthetic']:
            continue
        out['FIELD_TYPE'].add(base_type(field['type']))
        out['GENERIC_TYPE'].update(field['generic_types'])
        out['ANNOTATION'].update(a['type'] for a in field['annotations'])
    for method in facts.get('methods', []):
        out['PARAMETER_TYPE'].update(base_type(p) for p in method['parameters'])
        out['RETURN_TYPE'].add(base_type(method['returns']))
        out['ANNOTATION'].update(a['type'] for a in method['annotations'])
        out['ANNOTATION'].update(a['type'] for group in method['parameter_annotations'] for a in group)
        out['GENERIC_TYPE'].update(method['generic_types'])
        out['EXCEPTION'].update(method['exceptions'])
        out['METHOD_CALL'].update(site['owner'] for site in method['invokes'])
        out['FIELD_ACCESS'].update(site['owner'] for site in method['field_access'])
        out['TYPE_REFERENCE'].update(site['type'] for site in method['type_refs'])
    for key in out:
        out[key] = {t for t in out[key] if t and t not in PRIMITIVES and t != facts['fqn']}
    return out


def compact_for_snapshot(extracted: dict, internal: set[str]) -> dict:
    """Keep internal call sites and a bounded sample of external call sites per class."""
    classes = {}
    for fqn, facts in extracted['classes'].items():
        external_budget = MAX_EXTERNAL_SITES_PER_CLASS
        methods = []
        for method in facts['methods']:
            keep = []
            for site in method['invokes']:
                if site['owner'] in internal:
                    keep.append(site)
                elif external_budget > 0:
                    keep.append(site)
                    external_budget -= 1
            methods.append(dict(method, invokes=keep))
        classes[fqn] = dict(facts, methods=methods)
    return dict(extracted, classes=classes)


def bounded_for_snapshot(extracted: dict, internal: set[str], max_bytes: int) -> dict:
    """Shrink facts step by step until the JSON fits; every reduction is recorded, never silent."""
    import json
    facts = compact_for_snapshot(extracted, internal)
    reductions = []

    def size(value):
        return len(json.dumps(value, separators=(',', ':')))

    if size(facts) > max_bytes:
        for info in facts['classes'].values():
            for method in info['methods']:
                method['field_access'] = [s for s in method['field_access'] if s['owner'] in internal]
                method['type_refs'] = [s for s in method['type_refs'] if s['type'] in internal]
        reductions.append('external field accesses and type references removed')
    if size(facts) > max_bytes:
        for info in facts['classes'].values():
            for method in info['methods']:
                method['invokes'] = [s for s in method['invokes'] if s['owner'] in internal]
        reductions.append('external call sites removed (aging-API call sites limited to class-level references)')
    if size(facts) > max_bytes:
        return dict(schema=SCHEMA, classes={}, class_count=0, reductions=reductions + ['facts omitted: snapshot size limit'],
            parse_failure_count=extracted.get('parse_failure_count', 0), omitted_reason='Bytecode facts exceeded bytecode_facts_max_bytes.')
    facts['reductions'] = reductions
    return facts
