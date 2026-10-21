"""Assistant tools. Each is read-only, scoped to one analysis (tenant ownership is checked when the analysis is
loaded), size-bounded, and returns the evidence ids it used. There is no tool that changes code or data."""
from __future__ import annotations

from collections import Counter

from app.insight.details import node as node_detail
from app.insight.entrypoints import describe
from app.insight.metrics import compute as compute_metrics
from app.insight.roles import short
from app.insight.source_store import read as read_source
from .evidence import Index

MAX_ITEMS = 25
MAX_SOURCE_BYTES = 6000
# Words a question may use for a concern, mapped to the category of the responsibility analysis.
CONCERN_WORDS = {'security': 'SECURITY', 'secure': 'SECURITY', 'authentication': 'SECURITY', 'authorization': 'SECURITY', 'authorisation': 'SECURITY',
    'cache': 'PERFORMANCE', 'caching': 'PERFORMANCE', 'performance': 'PERFORMANCE', 'logging': 'OBSERVABILITY', 'logs': 'OBSERVABILITY', 'log': 'OBSERVABILITY', 'observability': 'OBSERVABILITY',
    'metrics': 'OBSERVABILITY', 'tracing': 'OBSERVABILITY', 'monitoring': 'OBSERVABILITY', 'transaction': 'DATA_INTEGRITY', 'transactions': 'DATA_INTEGRITY', 'integrity': 'DATA_INTEGRITY',
    'retry': 'RELIABILITY', 'retries': 'RELIABILITY', 'resilience': 'RELIABILITY', 'reliability': 'RELIABILITY', 'timeout': 'RELIABILITY', 'timeouts': 'RELIABILITY', 'configuration': 'CONFIGURATION',
    'scalability': 'SCALABILITY', 'privacy': 'PRIVACY_AND_DATA_PROTECTION', 'audit': 'AUDITABILITY_AND_COMPLIANCE', 'auditing': 'AUDITABILITY_AND_COMPLIANCE', 'testability': 'TESTABILITY',
    'maintainability': 'MAINTAINABILITY', 'interoperability': 'INTEROPERABILITY', 'availability': 'AVAILABILITY'}

CATALOG = {
    'get_package': dict(args={'name': 'package name; empty for the whole application'}, doc='Role mix, size, cycles, entry points and debt of a package.'),
    'get_class': dict(args={'name': 'class name (simple or fully qualified)'}, doc='Role (with evidence), size, dependency counts, entry points, cycles, debt and aging technology of a class.'),
    'get_dependencies': dict(args={'name': 'class or package', 'limit': 'max items'}, doc='What the class or package depends on, with edge types and reference counts.'),
    'get_dependents': dict(args={'name': 'class or package', 'limit': 'max items'}, doc='What depends on the class or package.'),
    'get_cycles': dict(args={'name': 'optional class/package filter'}, doc='Cyclic dependency groups with ordered members.'),
    'get_debt_findings': dict(args={'name': 'optional class/package', 'rule': 'optional rule id', 'severity': 'optional', 'limit': 'max items'}, doc='Technical debt findings with measured value and threshold.'),
    'get_runtime_coverage': dict(args={'name': 'optional class/package'}, doc='Which classes were observed in the selected runtime sessions.'),
    'get_entry_points': dict(args={'name': 'optional class/package', 'text': 'optional route/HTTP method/kind filter'}, doc='HTTP routes, listeners and jobs with their handlers.'),
    'get_aging_findings': dict(args={'name': 'optional class/package'}, doc='End-of-life / aging technologies and the classes that use them.'),
    'get_class_source': dict(args={'name': 'class'}, doc='Source (or a labelled bytecode outline) of one class, size-bounded.'),
    'search_classes': dict(args={'query': 'text in the name', 'role': 'optional role', 'limit': 'max items'}, doc='Find classes by name or role.'),
    'get_responsibilities': dict(args={'name': 'optional class or package', 'concern': 'optional concern such as security, caching or logging, or a category id', 'limit': 'max items'}, doc='Functional responsibilities and non-functional concerns of classes with status, confidence and evidence, plus risk indicators and shared components.'),
    'get_metrics': dict(args={'name': 'class or package', 'top': 'or a metric key such as class.fan_in to rank by', 'limit': 'max items'}, doc='Coupling, instability, size and complexity metrics, or the top offenders for one metric.'),
}

# A narrow word also narrows the rules: "caching" means the cache rules, not every performance label (paging, eager fetching).
CONCERN_RULES = {'cache': ('PERF-CACHE',), 'caching': ('PERF-CACHE',), 'logging': ('OBS-LOGGING',), 'logs': ('OBS-LOGGING',), 'log': ('OBS-LOGGING',), 'metrics': ('OBS-METRICS',), 'tracing': ('OBS-METRICS',),
    'transaction': ('DI-TRANSACTION',), 'transactions': ('DI-TRANSACTION',), 'retry': ('REL-RETRY',), 'retries': ('REL-RETRY',), 'timeout': ('REL-TIMEOUT',), 'timeouts': ('REL-TIMEOUT',),
    'authentication': ('SEC-AUTHORIZATION', 'SEC-API', 'SEC-PRINCIPAL', 'SEC-CONFIGURATION'), 'authorization': ('SEC-AUTHORIZATION', 'SEC-API', 'SEC-PRINCIPAL', 'SEC-CONFIGURATION'),
    'authorisation': ('SEC-AUTHORIZATION', 'SEC-API', 'SEC-PRINCIPAL', 'SEC-CONFIGURATION')}


_GENERIC = {'which', 'what', 'route', 'routes', 'endpoint', 'endpoints', 'entry', 'point', 'points', 'show', 'shows', 'page', 'list', 'the', 'for', 'that', 'this', 'does', 'handle', 'handles', 'serve', 'serves', 'url', 'urls', 'with', 'from', 'are', 'all'}


def _stem(word: str) -> str:
    word = ''.join(c for c in word.lower() if c.isalnum())
    if word in _GENERIC or len(word) < 3:
        return ''
    for suffix in ('ing', 'es', 'ed', 's'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


class Tools:
    def __init__(self, model, config=None, analysis_id: str = ''):
        self.model, self.config, self.analysis_id = model, config, analysis_id
        self.index = Index(model)
        self._metrics = None

    # -- resolution -----------------------------------------------------------------------------
    def resolve(self, name: str | None) -> dict:
        model, text = self.model, (name or '').strip()
        if not text:
            return dict(kind='system')
        owner = model.owners.get(text, text)
        if text in model.classes:
            return dict(kind='class', id=owner)
        if text in model.packages:
            return dict(kind='package', id=text)
        lowered = text.lower()
        exact = sorted({model.owners.get(c, c) for c in model.classes if c.rsplit('.', 1)[-1].lower() == lowered or c.rsplit('.', 1)[-1].split('$')[-1].lower() == lowered})
        if len(exact) == 1:
            return dict(kind='class', id=exact[0])
        if len(exact) > 1:
            return dict(kind='ambiguous', candidates=exact[:10])
        packages = sorted(p for p in model.packages if p.lower() == lowered or p.lower().endswith('.' + lowered))
        if len(packages) == 1:
            return dict(kind='package', id=packages[0])
        if len(packages) > 1:
            return dict(kind='ambiguous', candidates=packages[:10])
        return dict(kind='unknown', query=text)

    def _need(self, name):
        target = self.resolve(name)
        if target['kind'] in ('unknown', 'ambiguous'):
            return None, dict(ok=False, error='NOT_FOUND' if target['kind'] == 'unknown' else 'AMBIGUOUS', detail=target, evidence=[])
        return target, None

    def _scope(self, target) -> set[str] | None:
        if target['kind'] == 'class':
            return {target['id']}
        if target['kind'] == 'package':
            return {self.model.owners.get(c, c) for c in self.model.packages[target['id']]}
        return None

    # -- tools ------------------------------------------------------------------------------------
    def get_package(self, name: str = '') -> dict:
        target = self.resolve(name)
        if target['kind'] in ('unknown', 'ambiguous'):
            return dict(ok=False, error='NOT_FOUND' if target['kind'] == 'unknown' else 'AMBIGUOUS', detail=target, evidence=[])
        if target['kind'] == 'class':
            return self.get_class(name)
        detail = node_detail(self.model, target.get('id', 'system'), self.index.debt)
        if target['kind'] == 'system':
            roles = Counter(r['role'] for f, r in self.model.roles.items() if self.model.owners.get(f, f) == f)
            return dict(ok=True, kind='system', data=dict(packages=len(self.model.packages), classes=detail['size']['classes'], nested_classes=detail['size']['nested_classes'],
                roles=dict(roles), entry_points=detail['entry_points'], cycle_groups=detail['cycle_groups'], debt_findings=detail['debt_findings'],
                package_names=sorted(self.model.packages)), evidence=['summary:analysis'])
        return dict(ok=True, kind='package', data=dict(name=detail['name'], classes=detail['size']['classes'], methods=detail['size']['methods'], roles=detail['what']['roles'],
            depends_on=[x['id'] for x in detail['depends_on'][:10]], depended_on_by=[x['id'] for x in detail['depended_on_by'][:10]],
            cycles=len(detail['cycles']), entry_points=len(detail['entry_points']), debt=len(detail['debt']), summary=detail['summary']),
            evidence=['package:' + target['id']])

    def get_class(self, name: str) -> dict:
        target, error = self._need(name)
        if error or target['kind'] != 'class':
            return error or dict(ok=False, error='NOT_A_CLASS', detail=target, evidence=[])
        d = node_detail(self.model, target['id'], self.index.debt)
        evidence = ['class:' + target['id']] + ['finding:' + f['id'] for f in d['debt'][:5]] + ['entry:' + e['id'] for e in d['entry_points'][:5]]
        return dict(ok=True, kind='class', data=dict(name=target['id'], role=d['what']['role'], layer=d['what']['layer'], role_evidence=d['what']['reason'], package=self.model.package(target['id']),
            methods=d['size']['methods'], fields=d['size']['fields'], dependencies=len(d['depends_on']), dependents=len(d['depended_on_by']),
            entry_points=[e['description'] for e in d['entry_points']], cycles=[c['size'] for c in d['cycles']], debt=[dict(rule=f['rule_id'], severity=f['severity'], text=f['explanation']['plain']) for f in d['debt'][:5]],
            aging=[f"{a['technology']} ({a['status']})" for a in d['aging']], summary=d['summary']), evidence=evidence)

    def _neighbours(self, name, outgoing, limit):
        target, error = self._need(name)
        if error:
            return error
        limit = max(1, min(int(limit or 15), MAX_ITEMS))
        d = node_detail(self.model, target.get('id', 'system'), self.index.debt)
        rows = d['depends_on'] if outgoing else d['depended_on_by']
        if target['kind'] == 'package':
            rows = d['depends_on' if outgoing else 'depended_on_by']
        evidence, out = ['class:' + target['id'] if target['kind'] == 'class' else 'package:' + target['id']], []
        for row in rows[:limit]:
            a, b = (target['id'], row['id']) if outgoing else (row['id'], target['id'])
            evidence.append(f'edge:{a}->{b}')
            out.append(dict(id=row['id'], name=row['name'], references=row['reference_count'], edge_types=sorted(row['edge_types']), runtime_calls=row['runtime_calls']))
        return dict(ok=True, kind=target['kind'], data=dict(subject=target['id'], direction='depends_on' if outgoing else 'depended_on_by', total=len(rows), items=out), evidence=evidence)

    def get_dependencies(self, name: str, limit: int = 15) -> dict:
        return self._neighbours(name, True, limit)

    def get_dependents(self, name: str, limit: int = 15) -> dict:
        return self._neighbours(name, False, limit)

    def get_cycles(self, name: str = '') -> dict:
        target = self.resolve(name)
        groups = self.index.cycles['groups']
        scope = self._scope(target) if target['kind'] in ('class', 'package') else None
        rows = [g for g in groups if scope is None or scope & set(g['members']) or (target['kind'] == 'package' and target['id'] in g['members'])]
        return dict(ok=True, data=dict(total=len(rows), groups=[dict(id=g['id'], level=g['level'], size=g['size'], members=g['members'][:8], plain=g['explanation']['plain'],
            cut_first=(g['cut_candidates'][0]['source'] + ' -> ' + g['cut_candidates'][0]['target']) if g['cut_candidates'] else None) for g in rows[:10]]),
            evidence=['cycle:' + g['id'] for g in rows[:10]] or ['summary:analysis'])

    def get_debt_findings(self, name: str = '', rule: str = '', severity: str = '', limit: int = 10) -> dict:
        target = self.resolve(name)
        scope = self._scope(target) if target['kind'] in ('class', 'package') else None
        rows = [f for f in self.index.debt['findings'] if (scope is None or set(f['node_ids']) & scope) and (not rule or f['rule_id'] == rule) and (not severity or f['severity'] == severity.upper())]
        limit = max(1, min(int(limit or 10), MAX_ITEMS))
        return dict(ok=True, data=dict(total=len(rows), by_rule=dict(Counter(f['rule_id'] for f in rows)), items=[dict(id=f['id'], rule=f['rule_id'], title=f['title'], severity=f['severity'],
            entity=f['entity_id'], measured=f['measured'], threshold=f['threshold'], plain=f['explanation']['plain'], action=f['suggested_action']) for f in rows[:limit]]),
            evidence=['finding:' + f['id'] for f in rows[:limit]] or ['summary:analysis'])

    def get_runtime_coverage(self, name: str = '') -> dict:
        observed = self.model.observed_classes
        if observed is None:
            return dict(ok=True, data=dict(available=False, reason='No runtime session is selected for this conversation.'), evidence=['summary:analysis'])
        target = self.resolve(name)
        scope = self._scope(target) or {self.model.owners.get(c, c) for c in self.model.classes}
        seen = sorted(c for c in scope if c in observed or any(n in observed for n in self.model.nested_by_owner.get(c, [])))
        return dict(ok=True, data=dict(available=True, observed=len(seen), total=len(scope), unobserved=sorted(scope - set(seen))[:20], note='Unobserved does not mean unused.'),
            evidence=['runtime:' + c for c in seen[:10]] or ['summary:analysis'])

    def get_entry_points(self, name: str = '', text: str = '') -> dict:
        target = self.resolve(name)
        scope = self._scope(target) if target['kind'] in ('class', 'package') else None
        needle = (text or '').lower()
        candidates = [e for e in self.model.entry_points['items'] if scope is None or e['handler_class'] in scope]
        exact = [e for e in candidates if needle and needle in {part.strip().lower() for part in describe(e).split(', ')}]
        rows = exact or [e for e in candidates if not needle or needle in describe(e).lower() or needle in e['kind'].lower() or needle in e['handler_method'].lower()]
        if needle and not rows:
            terms = [_stem(w) for w in needle.split() if _stem(w)]
            def score(e):
                text = (describe(e) + ' ' + e['handler_class'] + ' ' + e['handler_method']).lower()
                return sum(t in text for t in terms)
            best = max((score(e) for e in candidates), default=0)
            rows = [e for e in candidates if terms and best >= min(2, len(terms)) and score(e) == best]
        return dict(ok=True, data=dict(total=len(rows), items=[dict(id=e['id'], description=describe(e), handler=f"{short(e['handler_class'])}.{e['handler_method']}()", kind=e['kind'], class_name=e['handler_class']) for e in rows[:MAX_ITEMS]],
            route_source=self.model.entry_points['source']), evidence=['entry:' + e['id'] for e in rows[:MAX_ITEMS]] or ['summary:analysis'])

    def get_aging_findings(self, name: str = '') -> dict:
        target = self.resolve(name)
        scope = self._scope(target) if target['kind'] in ('class', 'package') else None
        rows = []
        for f in self.index.aging['findings']:
            classes = [c['class_name'] for c in f['affected_classes'] if scope is None or c['class_name'] in scope]
            if scope is None or classes:
                rows.append((f, classes))
        return dict(ok=True, data=dict(rules_version=self.index.aging['rules']['rules_version'], stale=self.index.aging['rules']['stale'], items=[dict(id=f['id'], technology=f['technology'], version=f['version_found'],
            status=f['status'], alternative=f['recommended_alternative'], classes=classes[:10], class_count=len(classes)) for f, classes in rows[:MAX_ITEMS]]),
            evidence=['aging:' + f['id'] for f, _ in rows[:MAX_ITEMS]] or ['summary:analysis'])

    def get_responsibilities(self, name: str = '', concern: str = '', limit: int = 8) -> dict:
        result = self.model.responsibility
        if result['status'] != 'AVAILABLE':
            return dict(ok=False, error='NOT_AVAILABLE', detail=result.get('reason'), evidence=[])
        target = self.resolve(name)
        if target['kind'] in ('unknown', 'ambiguous'):
            return dict(ok=False, error='NOT_FOUND' if target['kind'] == 'unknown' else 'AMBIGUOUS', detail=target, evidence=[])
        scope = self._scope(target)
        key = (concern or '').strip()
        category = CONCERN_WORDS.get(key.lower()) or (key.upper() if key.upper() in result['taxonomy']['nonfunctional'] else None)
        prefixes = CONCERN_RULES.get(key.lower(), ())
        matches = lambda l: l['category'] == category and (not prefixes or any(r.startswith(p) for r in l['rule_ids'] for p in prefixes))
        if key and not category:
            return dict(ok=False, error='UNKNOWN_CONCERN', detail=key, evidence=[])
        limit = max(1, min(int(limit or 8), MAX_ITEMS))
        components = [c for f, c in sorted(result['components'].items()) if scope is None or f in scope]
        shown = [c for c in components if not category or any(matches(l) for l in c['non_functional_responsibilities'])]
        evidence, items = [], []
        for c in shown[:limit]:
            def brief(labels, wanted=None):
                rows = []
                for l in labels:
                    if wanted and not matches(l):
                        continue
                    ids = ['resp:' + i for i in l['evidence_ids'][:2]]
                    evidence.extend(ids)
                    rows.append(dict(category=l['category'], status=l['status'], confidence=l['confidence']['level'], description=l['description'], evidence=ids))
                return rows
            items.append(dict(id=c['fqn'], primary=c['primary_classification'], role=c['architectural_role']['role'], uncertainties=c['uncertainties'],
                              functional=brief(c['functional_responsibilities']), non_functional=brief(c['non_functional_responsibilities'], category)))
            evidence.append('class:' + c['fqn'])
        wanted = {c['fqn'] for c in components}
        risks = [r for r in result['risks'] if (scope is None or wanted & set(r['affected_components'])) and (not category or r['category'] == category)]
        for r in risks[:5]:
            evidence.append('risk:' + r['id'])
        shared = [c for c in result['cross_cutting'] if (scope is None or c['component'] in wanted or wanted & set(c['dependents'])) and (not category or category in c['concerns'])]
        return dict(ok=True, data=dict(scope=target, concern=category, concern_word=key.lower() if category else '', total=len(shown), analyzed=len(components), items=items,
                                       risks=[dict(id=r['id'], title=r['title'], severity=r['severity'], detection=r['detection_status'], runtime=r['runtime_validation_required'], description=r['description'], investigate=r['investigate']) for r in risks[:5]],
                                       shared=[dict(name=c['name'], kind=c['kind'], is_class=c['component'] in result['components'], component=c['component'], domains=[x['name'] for x in c['capabilities']], guidance=c['guidance']) for c in shared[:3]],
                                       primary_counts=dict(sorted(Counter(c['primary_classification'] for c in components).items())),
                                       limits=result['limitations'][:2]), evidence=list(dict.fromkeys(evidence)) or ['summary:analysis'])

    def get_class_source(self, name: str) -> dict:
        target, error = self._need(name)
        if error or target['kind'] != 'class':
            return error or dict(ok=False, error='NOT_A_CLASS', detail=target, evidence=[])
        result = read_source(self.config, self.analysis_id, self.model.result, target['id'], MAX_SOURCE_BYTES) if self.config else dict(kind='DISABLED', text='', reason='No configuration.')
        if not result['text']:
            return dict(ok=True, data=dict(available=False, kind=result['kind'], reason=result.get('reason')), evidence=['class:' + target['id']])
        return dict(ok=True, data=dict(available=True, kind=result['kind'], text=result['text'], truncated=result.get('truncated', False), reason=result.get('reason')), evidence=['source:' + target['id']])

    def search_classes(self, query: str = '', role: str = '', limit: int = 15) -> dict:
        needle, want = (query or '').lower(), (role or '').upper().replace(' ', '_')
        rows = sorted(c for c in self.model.classes if self.model.owners.get(c, c) == c and (not needle or needle in c.lower()) and (not want or self.model.roles[c]['role'] == want))
        limit = max(1, min(int(limit or 15), MAX_ITEMS))
        return dict(ok=True, data=dict(total=len(rows), items=[dict(id=c, role=self.model.roles[c]['role'], package=self.model.package(c)) for c in rows[:limit]]),
            evidence=['class:' + c for c in rows[:limit]] or ['summary:analysis'])

    def get_metrics(self, name: str = '', top: str = '', limit: int = 5) -> dict:
        if self._metrics is None:
            self._metrics = compute_metrics(self.model, self.index.cycles)
        m = self._metrics
        if top:
            if top not in m['definitions']:
                return dict(ok=False, error='UNKNOWN_METRIC', detail=dict(valid=sorted(m['definitions'])), evidence=[])
            rows = m['worst'][top][:max(1, min(int(limit or 5), MAX_ITEMS))]
            return dict(ok=True, data=dict(metric=top, label=m['definitions'][top]['label'], formula=m['definitions'][top]['formula'], ranking=rows), evidence=[f"metric:{r['id']}:{top}" for r in rows] or ['summary:analysis'])
        target, error = self._need(name)
        if error or target['kind'] == 'system':
            return error or dict(ok=False, error='NAME_REQUIRED', evidence=[])
        row = next((r for r in (m['classes'] if target['kind'] == 'class' else m['packages']) if r['id'] == target['id']), None)
        values = {k: v['value'] for k, v in row['metrics'].items()}
        return dict(ok=True, data=dict(subject=target['id'], values=values, formulas={k: m['definitions'][k]['formula'] for k in values}, states={k: v['indicator']['state'] for k, v in row['metrics'].items()}),
            evidence=[f"metric:{target['id']}:{k}" for k in values])

    def call(self, tool: str, args: dict) -> dict:
        if tool not in CATALOG:
            return dict(ok=False, error='UNKNOWN_TOOL', evidence=[])
        allowed = set(CATALOG[tool]['args'])
        extra = set(args) - allowed
        if extra:
            return dict(ok=False, error='UNKNOWN_ARGUMENTS', detail=sorted(extra), evidence=[])
        try:
            return getattr(self, tool)(**args)
        except (TypeError, ValueError) as error:
            return dict(ok=False, error='BAD_ARGUMENTS', detail=str(error)[:120], evidence=[])
