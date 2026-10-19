"""Static method call graph over application classes, built from bytecode invoke instructions.

Virtual/interface calls are resolved by class-hierarchy analysis (CHA): the declared target plus any
internal override with the same name and descriptor. This over-approximates what runs; callers label
results as "static reachability", never as observed behaviour.
"""
from __future__ import annotations

from collections import defaultdict, deque


def method_key(owner: str, name: str, descriptor: str) -> str:
    return f'{owner}#{name}{descriptor}'


def split_key(key: str) -> tuple[str, str, str]:
    owner, _, rest = key.partition('#')
    name, _, descriptor = rest.partition('(')
    return owner, name, '(' + descriptor


class CallGraph:
    def __init__(self, facts: dict):
        self.facts = facts
        self.methods: dict[str, dict] = {}
        self.subtypes: dict[str, set[str]] = defaultdict(set)
        for fqn, cls in facts.items():
            for parent in ([cls['super_name']] if cls.get('super_name') else []) + cls.get('interfaces', []):
                self.subtypes[parent].add(fqn)
            for method in cls.get('methods', []):
                self.methods[method_key(fqn, method['name'], method['descriptor'])] = dict(method, owner=fqn)
        self.calls: dict[str, list[dict]] = defaultdict(list)
        for key, method in self.methods.items():
            for site in method.get('invokes', []):
                for target in self.resolve(site['owner'], site['name'], site['descriptor'], site['kind']):
                    self.calls[key].append(dict(target=target, line=site.get('line'), kind=site['kind'],
                        declared_owner=site['owner'], resolution='DIRECT' if target.startswith(site['owner'] + '#') else 'HIERARCHY'))
            for lam in method.get('lambdas', []):
                target = method_key(lam['owner'], lam['name'], lam['descriptor'])
                if target in self.methods:
                    self.calls[key].append(dict(target=target, line=lam.get('line'), kind='lambda', declared_owner=lam['owner'], resolution='LAMBDA_BODY'))

    def _declared_upwards(self, owner: str, name: str, descriptor: str) -> str | None:
        current, guard = owner, 0
        while current in self.facts and guard < 50:
            key = method_key(current, name, descriptor)
            if key in self.methods and not self.methods[key]['abstract']:
                return key
            current, guard = self.facts[current].get('super_name'), guard + 1
        return None

    def _all_subtypes(self, owner: str) -> set[str]:
        out, stack = set(), [owner]
        while stack:
            for child in self.subtypes.get(stack.pop(), ()):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    def resolve(self, owner: str, name: str, descriptor: str, kind: str) -> list[str]:
        targets = []
        declared = self._declared_upwards(owner, name, descriptor)
        if declared:
            targets.append(declared)
        elif method_key(owner, name, descriptor) in self.methods:
            targets.append(method_key(owner, name, descriptor))     # abstract/interface declaration
        if kind in ('virtual', 'interface'):
            for child in sorted(self._all_subtypes(owner)):
                key = method_key(child, name, descriptor)
                if key in self.methods and key not in targets and not self.methods[key]['abstract']:
                    targets.append(key)
        return targets

    def reachable(self, starts: list[str], limit: int = 5000) -> dict:
        """Breadth-first static reachability. Returns methods with depth and the edge that reached them."""
        seen = {s: dict(depth=0, via=None, line=None) for s in starts if s in self.methods}
        queue = deque(seen)
        edges = []
        while queue and len(seen) < limit:
            current = queue.popleft()
            for call in self.calls.get(current, []):
                edges.append(dict(source=current, target=call['target'], line=call['line'], kind=call['kind'], resolution=call['resolution']))
                if call['target'] not in seen:
                    seen[call['target']] = dict(depth=seen[current]['depth'] + 1, via=current, line=call['line'])
                    queue.append(call['target'])
        return dict(methods=seen, edges=edges, truncated=bool(queue))

    def callers(self, target: str) -> list[dict]:
        return [dict(source=source, **call) for source, calls in self.calls.items() for call in calls if call['target'] == target]
