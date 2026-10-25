"""Generated-code detection from bytecode evidence, so generator output is not read as application design.

Each rule reads a fact recorded in the class file: a retained generator annotation, a generator base class, or the
fixed support-class layout a generator emits. A class name alone never marks a class as generated; names are only
used together with such a fact (a jOOQ helper next to a generated schema, an OpenAPI model next to its ApiClient).
Nested classes follow their outer class. Excluded classes stay visible as external types, so references to them remain.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil

from .bytecode import ACC_STATIC, ClassFormatError, descriptor_type, parse, parse_method_descriptor

GENERATED_ANNOTATIONS = {
    'org.immutables.value.Generated': 'IMMUTABLES',
    # Source-retention annotations do not reach bytecode in standard builds; listed for compilers that keep them.
    'javax.annotation.Generated': 'ANNOTATED_GENERATED',
    'javax.annotation.processing.Generated': 'ANNOTATED_GENERATED',
    'jakarta.annotation.Generated': 'ANNOTATED_GENERATED',
}
JOOQ_BASES = {'org.jooq.impl.TableImpl', 'org.jooq.impl.AbstractRoutine', 'org.jooq.impl.UpdatableRecordImpl', 'org.jooq.impl.TableRecordImpl',
              'org.jooq.impl.CatalogImpl', 'org.jooq.impl.SchemaImpl', 'org.jooq.impl.UDTImpl', 'org.jooq.impl.UDTRecordImpl',
              'org.jooq.impl.EmbeddableRecordImpl', 'org.jooq.impl.DAOImpl'}
JOOQ_ROOTS = {'org.jooq.impl.CatalogImpl', 'org.jooq.impl.SchemaImpl'}
JOOQ_INTERFACES = {'org.jooq.EnumType'}
JOOQ_HELPERS = {'Keys', 'Indexes', 'Tables', 'Routines', 'Sequences', 'Domains', 'UDTs', 'DefaultCatalog'}
OPENAPI_MARKERS = {'ApiClient', 'ApiException', 'Pair'}
OPENAPI_SUPPORT = OPENAPI_MARKERS | {'Configuration', 'JSON', 'ServerConfiguration', 'ServerVariable', 'StringUtil', 'ApiResponse', 'RFC3339DateFormat',
                                     'JavaTimeFormatter', 'AbstractOpenApiSchema', 'ApiCallback', 'ProgressRequestBody', 'ProgressResponseBody'}
RULES = [
    dict(id='IMMUTABLES', text='Class carries @org.immutables.value.Generated (retained in bytecode by the Immutables processor).'),
    dict(id='ANNOTATED_GENERATED', text='Class carries a @Generated annotation retained in bytecode.'),
    dict(id='JOOQ', text='Class extends a jOOQ generated-code base class (TableImpl, AbstractRoutine, record, catalog or schema implementations), '
                        'is an enum implementing org.jooq.EnumType, '
                        'or is a jOOQ helper (Keys, Indexes, Tables, Routines, ...) in a package that holds a generated catalog or schema.'),
    dict(id='OPENAPI_CLIENT', text='Class belongs to an OpenAPI Generator client: a package holding ApiClient, ApiException and Pair, where the class is '
                                  'a support class, a model declaring JSON_PROPERTY_* constants, an API class constructed from that ApiClient, '
                                  'or an auth class of that client.'),
]


def _package(fqn: str) -> str:
    return fqn.rpartition('.')[0]


def _simple(fqn: str) -> str:
    return fqn.rpartition('.')[2]


def summarize(data: bytes) -> dict:
    """The few class-file facts the rules read."""
    cf = parse(data)
    constructors = [m for m in cf.methods if m['name'] == '<init>']
    return dict(fqn=cf.name, super_name=cf.super_name, interfaces=list(cf.interfaces), annotations=[a['type'] for a in cf.attributes.get('annotations', [])],
                static_fields=[f['name'] for f in cf.fields if f['access'] & ACC_STATIC],
                field_types=sorted({descriptor_type(f['descriptor']) for f in cf.fields}),
                constructor_params=sorted({p for m in constructors for p in parse_method_descriptor(m['descriptor'])[0]}))


def detect(summaries: dict[str, dict]) -> dict[str, dict]:
    """fqn -> {generator, evidence} for every class one rule identifies; pure, so it is testable without class files."""
    found: dict[str, dict] = {}
    for fqn, info in summaries.items():
        annotation = next((a for a in info['annotations'] if a in GENERATED_ANNOTATIONS), None)
        if annotation:
            found[fqn] = dict(generator=GENERATED_ANNOTATIONS[annotation], evidence=f'annotated @{annotation}')
        elif info.get('super_name') in JOOQ_BASES:
            found[fqn] = dict(generator='JOOQ', evidence=f"extends {info['super_name']}")
        elif JOOQ_INTERFACES & set(info.get('interfaces', [])):
            found[fqn] = dict(generator='JOOQ', evidence=f"implements {', '.join(sorted(JOOQ_INTERFACES & set(info['interfaces'])))}")
    jooq_packages = {_package(f) for f, i in summaries.items() if i.get('super_name') in JOOQ_ROOTS}
    for fqn in summaries:
        if fqn not in found and '$' not in fqn and _package(fqn) in jooq_packages and _simple(fqn) in JOOQ_HELPERS:
            found[fqn] = dict(generator='JOOQ', evidence=f'jOOQ helper {_simple(fqn)} next to a generated catalog or schema in {_package(fqn)}')
    clients = {p for p in {_package(f) for f in summaries} if all(f'{p}.{m}' in summaries for m in OPENAPI_MARKERS)}
    for fqn, info in summaries.items():
        if fqn in found or '$' in fqn:
            continue
        root = next((c for c in sorted(clients, key=len, reverse=True) if fqn == f'{c}.{_simple(fqn)}' or fqn.startswith(c + '.')), None)
        if root is None:
            continue
        api_client = root + '.ApiClient'
        if _package(fqn) == root and _simple(fqn) in OPENAPI_SUPPORT:
            evidence = f'OpenAPI client support class in {root}'
        elif any(name.startswith('JSON_PROPERTY_') for name in info['static_fields']):
            evidence = 'OpenAPI model: declares JSON_PROPERTY_* constants'
        elif api_client in info['constructor_params'] or api_client in info['field_types']:
            evidence = f'OpenAPI API class built from {api_client}'
        elif _package(fqn) == root + '.auth':
            evidence = f'OpenAPI client auth class in {root}.auth'
        else:
            continue
        found[fqn] = dict(generator='OPENAPI_CLIENT', evidence=evidence)
    for fqn in summaries:
        if '$' in fqn and fqn not in found:
            outer = fqn.split('$', 1)[0]
            if outer in found:
                found[fqn] = dict(generator=found[outer]['generator'], evidence=f'nested in generated class {_simple(outer)}')
    return found


def exclude(classes_dir: Path, target: Path) -> dict:
    """Move generated class files out of the scanned tree; returns the record stored with the analysis."""
    files: dict[str, Path] = {}
    summaries: dict[str, dict] = {}
    failures = 0
    for path in sorted(classes_dir.rglob('*.class')):
        try:
            info = summarize(path.read_bytes())
        except (ClassFormatError, OSError):
            failures += 1
            continue
        files[info['fqn']] = path
        summaries[info['fqn']] = info
    found = detect(summaries)
    if found and len(found) == len(summaries):
        return record(found, len(summaries), 'ALL_GENERATED_KEPT', failures)
    for fqn in found:
        source = files[fqn]
        destination = target / source.relative_to(classes_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), destination)
    return record(found, len(summaries), 'EXCLUDED' if found else 'NONE_DETECTED', failures)


def record(found: dict[str, dict], total: int, status: str, parse_failures: int = 0) -> dict:
    by_generator = Counter(item['generator'] for item in found.values())
    packages = Counter(_package(fqn) for fqn in found)
    return dict(status=status, class_count=len(found), scanned_class_count=total, parse_failure_count=parse_failures,
                by_generator=dict(by_generator.most_common()), top_packages=[dict(package=p, classes=n) for p, n in packages.most_common(20)],
                examples=[dict(class_name=fqn, **found[fqn]) for fqn in sorted(found)[:100]], rules=RULES,
                note=(f'{len(found)} of {total} classes were left out of the dependency graph, domains, cycles, metrics and debt; references to them '
                      'appear as external types. Set EXCLUDE_GENERATED_CODE=false to analyze them as application code.') if status == 'EXCLUDED' else
                     (f'All {total} classes matched a generator rule, so all {total} were kept for analysis.' if status == 'ALL_GENERATED_KEPT' else
                      'No generated classes were detected.'))
