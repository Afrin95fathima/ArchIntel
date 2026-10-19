"""Scanner-shaped rows (classes + typed edges) derived from bytecode facts.

Used for (a) the optional `scanner_engine=bytecode` mode, which needs no JDK, and (b) the WP9 audit
that compares jQAssistant output with what the class files actually declare.
"""
from __future__ import annotations

from .facts import referenced_types

# jQAssistant DEPENDS_ON has no sub-type; the reader keeps finer kinds so missing types are visible.
EDGE_KINDS = ('INHERITANCE', 'INTERFACE', 'FIELD_TYPE', 'PARAMETER_TYPE', 'RETURN_TYPE', 'ANNOTATION',
    'GENERIC_TYPE', 'EXCEPTION', 'METHOD_CALL', 'TYPE_REFERENCE')


def scanner_rows(extracted: dict) -> tuple[list[dict], list[dict]]:
    facts = extracted['classes']
    classes, edges = [], []
    for fqn in sorted(facts):
        info = facts[fqn]
        methods = [dict(name=m['name'], signature=m['signature'], descriptor=m['descriptor'],
            annotations=[a['type'] for a in m['annotations']], synthetic=m['synthetic'], bridge=m['bridge'])
            for m in info['methods']]
        classes.append(dict(fqn=fqn, simple_name=fqn.rsplit('.', 1)[-1], package_name=fqn.rpartition('.')[0] or '(default)',
            class_type='INTERFACE' if info['interface'] else 'ENUM' if info['enum'] else 'CLASS',
            is_abstract=info['abstract'] and not info['interface'], is_interface=info['interface'],
            method_count=len(info['methods']), field_count=len(info['fields']),
            annotations=[a['type'] for a in info['annotations']], methods=methods))
        refs = referenced_types(info)
        refs['TYPE_REFERENCE'] |= refs.pop('FIELD_ACCESS')
        for kind in EDGE_KINDS:
            for target in sorted(refs.get(kind, ())):
                edges.append(dict(source=fqn, target=target, dependency_type=kind))
    return classes, edges


class BytecodeScanner:
    """Drop-in scanner for `scanner_engine=bytecode`; reads validated class files only."""

    def __init__(self, settings):
        self.settings = settings

    def available(self) -> bool:
        return True

    def scan(self, work, classes_dir, on_stage):
        from .facts import extract
        extracted = extract(classes_dir)
        if not extracted['classes']:
            from app.services.scanner import ScannerError
            raise ScannerError('No readable Java class files were found in the artifact.')
        on_stage('GRAPH_EXTRACTION', 30)
        return scanner_rows(extracted)


SUPPLEMENTED = ('PARAMETER_TYPE', 'RETURN_TYPE', 'ANNOTATION', 'EXCEPTION', 'GENERIC_TYPE', 'FIELD_TYPE', 'INHERITANCE', 'INTERFACE')


def supplement(edges: list[dict], extracted: dict) -> list[dict]:
    """Add dependency types the graph export does not distinguish (parameter, return, member annotations,
    declared exceptions, type arguments) from class-file facts. An untyped OTHER edge is dropped once a
    typed edge exists for the same pair, and no typed edge is ever duplicated."""
    from .facts import referenced_types
    seen = {(e['source'], e['target'], e['dependency_type']) for e in edges}
    merged = list(edges)
    for fqn, info in sorted(extracted['classes'].items()):
        refs = referenced_types(info)
        for kind in SUPPLEMENTED:
            for target in sorted(refs.get(kind, ())):
                if (fqn, target, kind) not in seen:
                    seen.add((fqn, target, kind))
                    merged.append(dict(source=fqn, target=target, dependency_type=kind, supplemented=True))
    typed = {(e['source'], e['target']) for e in merged if e['dependency_type'] != 'OTHER'}
    return [e for e in merged if e['dependency_type'] != 'OTHER' or (e['source'], e['target']) not in typed]
