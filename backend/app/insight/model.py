"""One read-only view over a completed snapshot, its bytecode facts and optional runtime evidence.

All insight services take an InsightModel. Snapshots are immutable after completion, so a model is
cached per analysis id.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from functools import cached_property
import re
from threading import Lock

from .bytecode import base_type
from .callgraph import CallGraph, method_key
from .entrypoints import detect
from .roles import classify, method_label, short

NOT_AVAILABLE_FACTS = ('Bytecode facts are not available for this analysis: it was produced before bytecode facts were '
    'recorded. Run a new analysis of the same artifact to enable this view.')


def owner_of(fqn: str, facts: dict) -> str:
    """Top-level declaring class for inner, anonymous and local classes."""
    current, guard = fqn, 0
    while guard < 20:
        outer = (facts.get(current) or {}).get('outer_class')
        if not outer or outer == current:
            break
        current, guard = outer, guard + 1
    return re.sub(r'\$.*$', '', current) if '$' in current else current


class InsightModel:
    def __init__(self, analysis_id: str, result: dict, runtime: dict | None = None):
        self.analysis_id, self.result, self.runtime = analysis_id, result, runtime
        bytecode = result.get('bytecode') or {}
        self.facts: dict = bytecode.get('classes') or {}
        self.facts_available = bool(self.facts)
        self.classes: dict = {c['id']: c for c in result.get('classes', [])}
        self.edges: list = result.get('edges', [])
        self.external_edges: list = result.get('external_edges', [])

    # ---------------------------------------------------------------- identity
    @cached_property
    def owners(self) -> dict[str, str]:
        return {fqn: owner_of(fqn, self.facts) for fqn in self.classes}

    def is_nested(self, fqn: str) -> bool:
        return self.owners.get(fqn, fqn) != fqn

    @cached_property
    def nested_by_owner(self) -> dict[str, list[str]]:
        out = defaultdict(list)
        for fqn, owner in self.owners.items():
            if owner != fqn:
                out[owner].append(fqn)
        return {k: sorted(v) for k, v in out.items()}

    def package(self, fqn: str) -> str:
        cls = self.classes.get(fqn)
        return cls['package_name'] if cls else fqn.rpartition('.')[0]

    @cached_property
    def packages(self) -> dict[str, list[str]]:
        out = defaultdict(list)
        for fqn in self.classes:
            out[self.package(fqn)].append(fqn)
        return {k: sorted(v) for k, v in sorted(out.items())}

    # ---------------------------------------------------------------- roles
    @cached_property
    def roles(self) -> dict[str, dict]:
        out = {}
        for fqn, cls in self.classes.items():
            owner = self.owners[fqn]
            if owner != fqn and owner in self.classes:
                continue
            out[fqn] = classify(fqn, cls, self.facts, self.classes)
        for fqn in self.classes:
            if fqn not in out:
                parent = out.get(self.owners[fqn]) or classify(fqn, self.classes[fqn], self.facts, self.classes)
                out[fqn] = dict(parent, reason=f'nested in {short(self.owners[fqn])}; inherits its role ({parent["reason"]})', nested=True)
        return out

    # ---------------------------------------------------------------- edges
    @cached_property
    def edge_types(self) -> dict[tuple[str, str], Counter]:
        out: dict = defaultdict(Counter)
        for edge in self.edges:
            out[(edge['source'], edge['target'])][edge['dependency_type']] += 1
        return out

    @cached_property
    def owner_edges(self) -> dict[tuple[str, str], Counter]:
        """Class edges folded onto top-level owners; nested-to-owner references disappear."""
        out: dict = defaultdict(Counter)
        for (source, target), kinds in self.edge_types.items():
            s, t = self.owners.get(source, source), self.owners.get(target, target)
            if s != t:
                out[(s, t)].update(kinds)
        return out

    def references(self, source: str, target: str, limit: int = 50) -> list[dict]:
        """Concrete code references from source (and its nested classes) to target, read from bytecode."""
        out = []
        sources = [source] + self.nested_by_owner.get(source, [])
        targets = {target} | set(self.nested_by_owner.get(target, []))
        for name in sources:
            info = self.facts.get(name)
            if not info:
                continue
            where = short(name)
            if info.get('super_name') in targets:
                out.append(dict(kind='INHERITANCE', text=f'{where} extends {short(info["super_name"])}', line=None))
            for item in info.get('interfaces', []):
                if item in targets:
                    out.append(dict(kind='INTERFACE', text=f'{where} implements {short(item)}', line=None))
            for annotation in info.get('annotations', []):
                if annotation['type'] in targets:
                    out.append(dict(kind='ANNOTATION', text=f'{where} is annotated @{short(annotation["type"])}', line=None))
            for field in info.get('fields', []):
                if field['synthetic']:
                    continue
                if base_type(field['type']) in targets:
                    out.append(dict(kind='FIELD_TYPE', text=f'field {where}.{field["name"]} has type {short(field["type"])}', line=None))
                elif targets & set(field['generic_types']):
                    out.append(dict(kind='GENERIC_TYPE', text=f'field {where}.{field["name"]} uses {short(field["type"])}<{", ".join(short(t) for t in sorted(targets & set(field["generic_types"])))}>', line=None))
            for method in info.get('methods', []):
                label = method_label(name, method['name'])
                for site in method.get('invokes', []):
                    if site['owner'] in targets:
                        out.append(dict(kind='METHOD_CALL', text=f'{label} calls {method_label(site["owner"], site["name"])}', line=site.get('line'),
                            method=method['name'], target_method=site['name']))
                if method['synthetic'] or method['bridge']:
                    continue
                for index, param in enumerate(method['parameters']):
                    if base_type(param) in targets:
                        out.append(dict(kind='PARAMETER_TYPE', text=f'{label} takes a {short(param)} parameter', line=None, method=method['name']))
                if base_type(method['returns']) in targets:
                    out.append(dict(kind='RETURN_TYPE', text=f'{label} returns {short(method["returns"])}', line=None, method=method['name']))
                for exception in method.get('exceptions', []):
                    if exception in targets:
                        out.append(dict(kind='EXCEPTION', text=f'{label} declares throws {short(exception)}', line=None, method=method['name']))
                for site in method.get('field_access', []):
                    if site['owner'] in targets:
                        out.append(dict(kind='FIELD_ACCESS', text=f'{label} reads/writes {short(site["owner"])}.{site["name"]}', line=site.get('line'), method=method['name']))
                for site in method.get('type_refs', []):
                    if site['type'] in targets and site['kind'] != 'new':
                        out.append(dict(kind='TYPE_REFERENCE', text=f'{label} uses {short(site["type"])} ({site["kind"]})', line=site.get('line'), method=method['name']))
                if targets & set(method.get('generic_types', [])):
                    out.append(dict(kind='GENERIC_TYPE', text=f'{label} signature uses {", ".join(short(t) for t in sorted(targets & set(method["generic_types"])))} as a type argument', line=None, method=method['name']))
                for annotation in method.get('annotations', []):
                    if annotation['type'] in targets:
                        out.append(dict(kind='ANNOTATION', text=f'{label} is annotated @{short(annotation["type"])}', line=None, method=method['name']))
        unique, seen = [], set()
        for item in out:
            key = (item['kind'], item['text'])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:limit]

    # ---------------------------------------------------------------- behaviour
    @cached_property
    def entry_points(self) -> dict:
        if self.facts_available:
            return dict(detect(self.facts), source='BYTECODE')
        from app.services.runtime.entry_points import is_method_entry_point
        items = []
        for fqn, cls in sorted(self.classes.items()):
            for method in cls.get('methods', []):
                if is_method_entry_point(method.get('annotations', [])):
                    items.append(dict(id=fqn + '#' + method.get('signature', method.get('name', '')), kind='HTTP_ENDPOINT',
                        handler_class=fqn, handler_method=method.get('name'), handler_descriptor=None,
                        handler_signature=method.get('signature'), http_methods=[], paths=[], trigger=None, parameters=[],
                        evidence=[f"annotations {', '.join(short(a) for a in method.get('annotations', []))}"],
                        route_metadata_state='NOT_AVAILABLE', line=None))
        return dict(items=items, implicit_methods=[], duplicate_routes=[], source='SNAPSHOT_ANNOTATIONS',
            limitation='Route paths and HTTP methods are not available: ' + NOT_AVAILABLE_FACTS)

    @cached_property
    def callgraph(self) -> CallGraph:
        return CallGraph(self.facts)

    def methods_of(self, fqn: str, include_synthetic: bool = False) -> list[dict]:
        info = self.facts.get(fqn)
        if info:
            return [m for m in info['methods'] if include_synthetic or not (m['synthetic'] or m['bridge'])]
        return [m for m in self.classes.get(fqn, {}).get('methods', []) if include_synthetic or not str(m.get('name', '')).startswith(('lambda$', 'access$'))]

    def method_id(self, fqn: str, method: dict) -> str:
        return method_key(fqn, method['name'], method.get('descriptor') or method.get('signature', ''))

    # ---------------------------------------------------------------- runtime
    @cached_property
    def observed_classes(self) -> set[str] | None:
        if not self.runtime:
            return None
        return {n['static_id'] for n in self.runtime.get('runtime_graph', {}).get('nodes', []) if n.get('static_id')}

    @cached_property
    def runtime_calls(self) -> dict[tuple[str, str], int]:
        if not self.runtime:
            return {}
        nodes = {n['id']: n for n in self.runtime.get('runtime_graph', {}).get('nodes', [])}
        out: Counter = Counter()
        for edge in self.runtime.get('runtime_graph', {}).get('edges', []):
            s, t = nodes.get(edge['source'], {}).get('static_id'), nodes.get(edge['target'], {}).get('static_id')
            if s and t:
                out[(self.owners.get(s, s), self.owners.get(t, t))] += edge.get('call_count', 0)
        return dict(out)


_CACHE: 'OrderedDict[str, InsightModel]' = OrderedDict()
_LOCK = Lock()


def get_model(analysis_id: str, result: dict, runtime: dict | None = None, runtime_key: str = '') -> InsightModel:
    key = analysis_id + '|' + runtime_key
    with _LOCK:
        model = _CACHE.get(key)
        # Completed snapshots are immutable and analysis ids are UUIDs, so the id identifies the content.
        if model is not None:
            _CACHE.move_to_end(key)
            return model
        model = InsightModel(analysis_id, result, runtime)
        _CACHE[key] = model
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
        return model
