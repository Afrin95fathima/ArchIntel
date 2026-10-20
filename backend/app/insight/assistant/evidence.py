"""Evidence ids and their verification. An id is only valid if the thing it names exists in this analysis."""
from __future__ import annotations

import re

from app.content.check import check_text, load_rules
from app.insight.cycles import analyse as analyse_cycles
from app.insight.debt import detect
from app.insight.lifecycle import evaluate
from app.insight.metrics import DEFINITIONS

PREFIXES = ('class', 'package', 'edge', 'finding', 'cycle', 'entry', 'aging', 'metric', 'runtime', 'source', 'layer', 'summary')


class Index:
    """Lazily computed sets of valid ids for one model (shared by tools, verifier and evaluation)."""

    def __init__(self, model):
        self.model = model
        self._debt = self._cycles = self._aging = self._entries = None

    @property
    def debt(self):
        if self._debt is None:
            self._debt = detect(self.model)
        return self._debt

    @property
    def cycles(self):
        if self._cycles is None:
            self._cycles = analyse_cycles(self.model)
        return self._cycles

    @property
    def aging(self):
        if self._aging is None:
            self._aging = evaluate(self.model, self.model.result.get('tech_inventory'))
        return self._aging

    def exists(self, evidence_id: str) -> bool:
        kind, _, value = evidence_id.partition(':')
        model = self.model
        if kind == 'class':
            return value in model.classes
        if kind == 'package':
            return value in model.packages
        if kind == 'source':
            return value in model.classes
        if kind == 'layer':
            return any(r['layer'] == value for r in model.roles.values())
        if kind == 'summary':
            return value == 'analysis'
        if kind == 'edge':
            source, _, target = value.partition('->')
            owners = lambda n: model.owners.get(n, n)
            return (owners(source), owners(target)) in model.owner_edges or (source in model.packages and any(
                model.package(s) == source and model.package(t) == target for (s, t) in model.owner_edges))
        if kind == 'finding':
            return any(f['id'] == value for f in self.debt['findings'])
        if kind == 'cycle':
            return any(g['id'] == value or any(c['id'] == value for c in g['cycles']) for g in self.cycles['groups'])
        if kind == 'entry':
            return any(e['id'] == value for e in model.entry_points['items'])
        if kind == 'aging':
            return any(f['id'] == value for f in self.aging['findings'])
        if kind == 'metric':
            entity, _, key = value.rpartition(':')
            return key in DEFINITIONS and (entity in model.classes or entity in model.packages)
        if kind == 'runtime':
            return model.observed_classes is not None and value in model.classes
        return False


FQN = re.compile(r'\b(?:[a-z_][a-z0-9_]*\.){2,}[A-Za-z_$][\w$]*\b')
CAMEL = re.compile(r'\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b')


def known_names(model) -> set[str]:
    names = set(model.classes) | set(model.packages)
    # Library types named in the analysis (supertypes, referenced types) are real names, not inventions.
    external = {e['target'] for e in model.external_edges} | {p for i in model.facts.values() for p in ([i['super_name']] if i.get('super_name') else []) + i['interfaces']}
    names |= external | {n.rsplit('.', 1)[-1] for n in external}
    simple = {n.rsplit('.', 1)[-1] for n in model.classes}
    simple |= {n.split('$')[-1] for n in model.classes}
    return names | simple


def check_answer(index: Index, sentences: list[dict], extra_known: set[str] = frozenset(), content_rules: bool = False) -> tuple[list[dict], list[dict]]:
    """Keep sentences whose citations exist and whose identifiers (class names, packages) exist. With content_rules (model-written text), also drop banned phrases and sentences that name nothing and count nothing."""
    model = index.model
    known = known_names(model) | set(extra_known)
    kept, removed = [], []
    for sentence in sentences:
        cites = sentence.get('cites') or []
        bad = [c for c in cites if not index.exists(c)]
        unknown = sorted({n for n in FQN.findall(sentence['text']) if n not in known and not n.startswith(('java.', 'jakarta.', 'javax.', 'org.', 'com.', 'io.'))}
                         | {n for n in CAMEL.findall(sentence['text']) if n not in known and n not in extra_known})
        content = check_text(sentence['text'], 'model output', 0, load_rules()) if content_rules else []
        if any(v.kind == 'BANNED' for v in content):
            removed.append(dict(text=sentence['text'], reason='BANNED_PHRASE'))
        elif content:
            removed.append(dict(text=sentence['text'], reason='NOT_SPECIFIC'))
        elif sentence.get('requires_citation', True) and not cites:
            removed.append(dict(text=sentence['text'], reason='NO_CITATION'))
        elif bad:
            removed.append(dict(text=sentence['text'], reason='CITATION_NOT_FOUND', ids=bad))
        elif unknown and sentence.get('check_identifiers', True):
            removed.append(dict(text=sentence['text'], reason='UNKNOWN_IDENTIFIER', identifiers=unknown[:5]))
        else:
            kept.append(sentence)
    return kept, removed
