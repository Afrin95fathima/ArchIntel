"""Technology modernization plan: what to replace, with what, in which order, and whether the combination is feasible.

Everything here is deterministic and comes from the lifecycle findings of the analysis and the curated candidate file
(rules/modernization-candidates.yaml). A model may only add wording (see `verify_ai`); it never changes a choice.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import re

import yaml

from . import lifecycle
from .lifecycle import _versioned_status, in_range, load_rules

CANDIDATES_PATH = Path(__file__).resolve().parent / 'rules' / 'modernization-candidates.yaml'
STATUS_RANK = {'current': 0, 'not-covered': 0.5, 'aging': 1, 'end-of-life': 2}
SELECTION_RULE = ('Among candidates without a blocking conflict, prefer the one whose lifecycle status in the rules file is best (current, then not covered by the rules file, then aging, then end-of-life), '
                  'then the lowest required Java level, then the fewest classes that need a namespace rename, then the order in the candidates file.')
PHASE_RULE = ('Phase 1 holds library replacements that run on the current Java level (renaming imports of a library does not need a new Java). Phase 2 raises Java. '
              'Phase 3 holds framework and Jakarta namespace moves and anything else that needs the new Java level; items that must move together share a phase.')


@lru_cache(maxsize=2)
def load_candidates(path: str = str(CANDIDATES_PATH)) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('items'), dict):
        raise ValueError('Unsupported modernization candidates file.')
    rule_ids = {r['id'] for r in load_rules()['rules']}
    for rule_id, rows in data['items'].items():
        if rule_id not in rule_ids:
            raise ValueError(f'Candidates for unknown lifecycle rule {rule_id}.')
        for row in rows:
            if row['lifecycle'] is not None and row['lifecycle']['rule'] not in rule_ids:
                raise ValueError(f"Candidate {row['id']} references unknown lifecycle rule {row['lifecycle']['rule']}.")
    return data


def _java_of(finding) -> int | None:
    match = re.search(r'(\d+)', str(finding.get('version_found') or ''))
    return int(match.group(1)) if match else None


def _plural(count, one, many=None):
    return f'{count} {one if count == 1 else (many or one + "s")}'


def _status_text(view):
    return 'not covered by the rules file' if view['lifecycle']['status'] == 'not-covered' else view['lifecycle']['status']


def _candidate_status(candidate, rules_by_id):
    ref = candidate['lifecycle']
    if ref is None:
        return dict(status='not-covered', note=None, rule=None, version=None)
    verdict = _versioned_status(rules_by_id[ref['rule']], ref['version'])
    return dict(status=verdict['status'], note=verdict['note'], rule=ref['rule'], version=ref['version'])


def build(model, lifecycle_result: dict, candidates: dict | None = None, rules: dict | None = None) -> dict:
    candidates = candidates or load_candidates()
    rules = rules or load_rules()
    rules_by_id = {r['id']: r for r in rules['rules']}
    findings = lifecycle_result['findings']
    java_findings = [f for f in findings if f['rule_id'] == 'java-class-target']
    current_java = max((j for j in map(_java_of, java_findings) if j), default=None)
    flagged = defaultdict(list)
    for f in findings:
        if f['status'] in ('aging', 'end-of-life') and f['rule_id'] != 'java-class-target':
            flagged[f['rule_id']].append(f)
    java_flagged = [f for f in java_findings if f['status'] in ('aging', 'end-of-life')]
    classes_of = lambda fs: sorted({c['class_name'] for f in fs for c in f['affected_classes']})
    by_rule_all = defaultdict(list)
    for f in findings:
        by_rule_all[f['rule_id']].append(f)
    observed = model.observed_classes

    def namespace_classes(namespace):
        prefix = namespace['from']
        out = set()
        for rule_id, fs in by_rule_all.items():
            replacement = rules_by_id[rule_id].get('replacement')
            if replacement and replacement['from'].startswith(prefix):      # rules whose renamed package is inside the candidate's namespace
                out |= set(classes_of(fs))
        return sorted(out)

    def check_needs(candidate):
        """Technologies found in this application that this candidate cannot run with unless they move too."""
        coupled, blocking = [], []
        for need in candidate.get('needs', []):
            for f in by_rule_all.get(need['rule'], []):
                if f['version_found'] and in_range(f['version_found'], need['versions']):
                    row = dict(rule=need['rule'], technology=f['technology'], version=f['version_found'], reason=need['reason'])
                    (coupled if need['rule'] in flagged else blocking).append(row)
        return coupled, blocking

    def candidate_view(candidate):
        coupled, blocking = check_needs(candidate)
        status = _candidate_status(candidate, rules_by_id)
        namespace = candidate.get('namespace')
        ns = namespace_classes(namespace) if namespace else []
        return dict(id=candidate['id'], name=candidate['name'], target_version=candidate['target_version'], requires_java=candidate['requires_java'], phase=candidate['phase'],
            lifecycle=status, namespace=namespace, namespace_classes=ns, coupled=coupled, blocking=blocking, steps=candidate['steps'], fit=candidate['fit'])

    def rank(view):
        return (len(view['blocking']) > 0, STATUS_RANK[view['lifecycle']['status']], view['requires_java'], len(view['namespace_classes']))

    items = []
    for rule_id in sorted(flagged, key=lambda r: (min(STATUS_RANK[f['status']] for f in flagged[r]) * -1, r)):
        fs = flagged[rule_id]
        views = [candidate_view(c) for c in candidates['items'][rule_id]]
        order = sorted(range(len(views)), key=lambda i: (rank(views[i]), i))
        chosen = views[order[0]]
        rejected = []
        for i in order[1:]:
            v = views[i]
            reasons = []
            if v['blocking']:
                reasons.append('blocked by ' + ', '.join(f"{b['technology']} {b['version']} ({b['reason']})" for b in v['blocking']))
            if STATUS_RANK[v['lifecycle']['status']] > STATUS_RANK[chosen['lifecycle']['status']]:
                reasons.append(f"its lifecycle status is {_status_text(v)} against {_status_text(chosen)} for {chosen['name']}")
            elif v['requires_java'] > chosen['requires_java']:
                reasons.append(f"it needs Java {v['requires_java']} against Java {chosen['requires_java']}")
            elif len(v['namespace_classes']) > len(chosen['namespace_classes']):
                reasons.append(f"it changes the namespace of {len(v['namespace_classes'])} classes against {len(chosen['namespace_classes'])}")
            else:
                reasons.append(f"it ranks after {chosen['name']} in the candidates file at equal status, Java level and namespace impact")
            rejected.append(dict(id=v['id'], name=v['name'], reason='; '.join(reasons)))
        items.append(dict(rule_id=rule_id, technology=fs[0]['technology'], category=fs[0].get('category'), status=min((f['status'] for f in fs), key=lambda s: STATUS_RANK[s] * -1),
            versions_found=sorted({f['version_found'] for f in fs if f['version_found']}), version_known=any(f['version_found'] for f in fs),
            affected_classes=classes_of(fs), call_site_count=sum(f['call_site_count'] for f in fs),
            status_note=next((f['status_note'] for f in fs if f['status_note']), None), source_url=fs[0].get('source_url'),
            recommended=chosen, alternatives=rejected, verification='CURATED'))

    # Java target: the smallest LTS that every chosen candidate runs on and that is not older than the code
    needed = max([i['recommended']['requires_java'] for i in items], default=0)
    lts = sorted(c for c in candidates['java']['lts_candidates'])
    java_views = [candidate_view(c) for c in candidates['items']['java-class-target']]
    eligible = [v for v in java_views if v['requires_java'] >= max(needed, current_java or 0)]
    java_target = min(eligible, key=lambda v: (STATUS_RANK[v['lifecycle']['status']], v['requires_java']), default=None)
    java_item = None
    must_raise = bool(java_target) and (bool(java_flagged) or (current_java is not None and current_java < needed))
    if must_raise and java_target:
        affected = classes_of(java_flagged)
        java_item = dict(rule_id='java-class-target', technology='Java bytecode target level', category='platform',
            status=min((f['status'] for f in java_flagged), key=lambda s: STATUS_RANK[s] * -1) if java_flagged else 'aging',
            versions_found=sorted({f['version_found'] for f in java_flagged}) or [f'Java {current_java}'], version_known=True, affected_classes=affected, call_site_count=0,
            status_note=next((f['status_note'] for f in java_flagged), None), source_url=java_findings[0].get('source_url') if java_findings else None,
            recommended=java_target, alternatives=[dict(id=v['id'], name=v['name'], reason=(f"it needs Java {v['requires_java']} but Java {java_target['requires_java']} already satisfies every chosen candidate" if v['requires_java'] > java_target['requires_java']
                                                                                          else f"its lifecycle status is {v['lifecycle']['status']}")) for v in java_views if v['id'] != java_target['id']],
            verification='CURATED', derived_from=None if java_flagged else [i['rule_id'] for i in items if i['recommended']['requires_java'] > (current_java or 0)])
        items.insert(0, java_item)
    target_java = java_target['requires_java'] if java_target else current_java

    # Feasibility checks per item
    for item in items:
        chosen, checks = item['recommended'], []
        if item['rule_id'] == 'java-class-target':
            checks.append(dict(check='JAVA_LEVEL', status='PASS', detail=f"Java {chosen['requires_java']} is an LTS line the rules mark {chosen['lifecycle']['status']}; every other chosen candidate needs at most Java {needed or 'n/a'}."))
        else:
            reachable = chosen['requires_java'] <= max(lts)          # no curated LTS line runs a candidate that needs more
            ok = reachable and (target_java is None or chosen['requires_java'] <= target_java)
            checks.append(dict(check='JAVA_LEVEL', status='PASS' if ok else 'FAIL',
                detail=(f"{chosen['name']} needs Java {chosen['requires_java']}; the plan targets Java {target_java}" + (f" (the code compiles for Java {current_java})." if current_java else '.')) if target_java else (f"{chosen['name']} needs Java {chosen['requires_java']}, which no curated LTS line ({', '.join(map(str, lts))}) provides." if not reachable else f"{chosen['name']} needs Java {chosen['requires_java']}; the current Java level of the code is not measured.")))
        if chosen['namespace']:
            checks.append(dict(check='NAMESPACE', status='COUPLED' if chosen['namespace_classes'] else 'PASS',
                detail=f"{chosen['namespace']['from']} -> {chosen['namespace']['to']}: {_plural(len(chosen['namespace_classes']), 'class', 'classes')} {'uses' if len(chosen['namespace_classes']) == 1 else 'use'} the old namespace" + (f" ({', '.join(c.rsplit('.', 1)[-1] for c in chosen['namespace_classes'][:5])}{' and more' if len(chosen['namespace_classes']) > 5 else ''})." if chosen['namespace_classes'] else '.')))
        for row in chosen['coupled']:
            checks.append(dict(check='DEPENDENCY_CONFLICT', status='COUPLED', detail=f"{row['technology']} {row['version']} is found in this application and is also flagged; {row['reason']} Upgrade it in the same phase."))
        for row in chosen['blocking']:
            checks.append(dict(check='DEPENDENCY_CONFLICT', status='FAIL', detail=f"{row['technology']} {row['version']}: {row['reason']} It is not flagged for replacement, so this candidate cannot run with it."))
        checks.append(dict(check='CURATED_CANDIDATE', status='PASS', detail=f"{chosen['id']} is listed in the curated candidates file (version {candidates['candidates_version']})."))
        item['feasibility'] = checks
        item['feasible'] = all(c['status'] != 'FAIL' for c in checks)

    # Phases
    item_by_rule = {i['rule_id']: i for i in items}
    coupled_groups = []
    for item in items:
        for row in item['recommended']['coupled']:
            if row['rule'] in item_by_rule:
                coupled_groups.append({item['rule_id'], row['rule']})
    def phase_of(item):
        if item['rule_id'] == 'java-class-target':
            return 2
        runs_now = item['recommended']['requires_java'] <= (current_java if current_java is not None else 8)
        return 1 if runs_now and item['recommended']['phase'] == 'library' else 3
    assigned = {i['rule_id']: phase_of(i) for i in items}
    for group in coupled_groups:
        top = max(assigned[r] for r in group)
        for r in group:
            assigned[r] = top
    titles = {1: 'Replace libraries without changing the Java level', 2: f"Raise Java to {target_java}" if target_java else 'Raise the Java level', 3: 'Move frameworks and namespaces on the new Java level'}
    phases = []
    for number in (1, 2, 3):
        members = [i for i in items if assigned[i['rule_id']] == number]
        if not members:
            continue
        classes = sorted({c for i in members for c in i['affected_classes']})
        phases.append(dict(number=len(phases) + 1, source_number=number, title=titles[number], items=[i['rule_id'] for i in members], class_count=len(classes),
            prerequisites=[f"Phase {p['number']} complete" for p in phases],
            exit_criteria=[f"No application class references {i['technology']} (now {_plural(len(i['affected_classes']), 'class', 'classes')})." for i in members] + ['The existing tests pass.']))
    number_of = {p['source_number']: p['number'] for p in phases}
    for item in items:
        item['phase'] = number_of[assigned[item['rule_id']]]
        chosen = item['recommended']
        item['prerequisites'] = [f"Phase {p['number']} ({p['title'].lower()})" for p in phases if p['number'] < item['phase']]
        item['coupled_with'] = sorted({r for g in coupled_groups if item['rule_id'] in g for r in g if r != item['rule_id']})

        # evidence of use at runtime, confidence, why, risks
        affected = item['affected_classes']
        used = len(set(affected) & observed) if observed is not None else None
        item['runtime_evidence'] = dict(observed=used, total=len(affected), text=f"{used} of {len(affected)} affected classes ran in the selected sessions" if used is not None and affected else None,
                                        not_measured=None if observed is not None else 'no runtime session is attached')
        inputs = [dict(name='Version of the technology is known', present=item['version_known']), dict(name='Code references are listed from bytecode', present=bool(model.facts_available and affected)),
                  dict(name='Runtime evidence is attached', present=observed is not None), dict(name='All feasibility checks pass', present=item['feasible'])]
        present = sum(i['present'] for i in inputs)
        item['confidence'] = dict(inputs=inputs, present=present, total=len(inputs), label='HIGH' if present == 4 else 'MEDIUM' if present == 3 else 'LOW',
                                  rule='HIGH when all 4 inputs are present, MEDIUM when 3, otherwise LOW.')
        item['why'] = [
            f"{item['technology']} is {item['status']}" + (f" ({item['status_note']})" if item['version_known'] and item['status_note'] else ' (the installed version could not be determined from the artifact)') + f"; {_plural(len(affected), 'class', 'classes')} {'references' if len(affected) == 1 else 'reference'} it" + (f" with {_plural(item['call_site_count'], 'code reference')}." if item['call_site_count'] else '.'),
            f"{chosen['name']} is chosen. Lifecycle status: " + (f"{chosen['lifecycle']['status']}" + (f" ({chosen['lifecycle']['note']})" if chosen['lifecycle']['note'] else '') if chosen['lifecycle']['status'] != 'not-covered' else 'not covered by lifecycle-rules.yaml')
            + f". It needs Java {chosen['requires_java']}" + (f"; the plan targets Java {target_java}." if target_java else '.'),
            *( [f"{chosen['namespace']['from']} -> {chosen['namespace']['to']} changes the imports of {_plural(len(chosen['namespace_classes']), 'class', 'classes')}."] if chosen['namespace'] and chosen['namespace_classes'] else []),
            *( [item['runtime_evidence']['text'] + '.'] if item['runtime_evidence']['text'] else [] )]
        item['steps'] = chosen['steps']
        item['risks'] = ([f"{len(affected) - used} of {len(affected)} affected classes were never observed at runtime, so tests must cover them." ] if used is not None and affected and used < len(affected) else []) \
            + [f"{c['detail']}" for c in item['feasibility'] if c['status'] == 'COUPLED'] + ([f"The installed version of {item['technology']} could not be determined from the artifact." ] if not item['version_known'] else [])
        item['citations'] = [f"rule:{item['rule_id']}", f"candidate:{chosen['id']}"] + [f"class:{c}" for c in affected[:10]]

    # Verify citations: drop any item whose cited rule, candidate or class does not exist
    known_classes = set(model.classes) | set(model.facts)
    valid_rules = set(rules_by_id)
    candidate_ids = {c['id'] for rows in candidates['items'].values() for c in rows}
    kept, dropped = [], []
    for item in items:
        bad = [c for c in item['citations'] if (c.startswith('rule:') and c[5:] not in valid_rules) or (c.startswith('candidate:') and c[10:] not in candidate_ids) or (c.startswith('class:') and c[6:] not in known_classes)]
        (dropped if bad else kept).append(dict(rule_id=item['rule_id'], missing=bad) if bad else item)
    items = kept

    counts = defaultdict(int)
    for item in items:
        counts[item['category'] or 'other'] += 1
    language = dict(recommendation='NO_LANGUAGE_CHANGE',
        reason=(f"{_plural(len(items), 'aging or end-of-life item')} ({', '.join(f'{n} {k}' for k, n in sorted(counts.items()))}) are library, framework, namespace or platform versions on the same language. "
                f"No measured finding is caused by the Java language itself, so a language change is not supported by the evidence."))
    runtime = dict(current_java=current_java, target_java=target_java,
        recommendation='JAVA_UPGRADE' if java_item else 'NO_JAVA_UPGRADE',
        reason=(f"Class files target Java {current_java}; {java_target['name']} is the smallest LTS that satisfies every chosen candidate (needs Java {needed}) and the rules mark it {java_target['lifecycle']['status']}." if java_item and current_java
                else f"Java {current_java} is not flagged and every chosen candidate runs on it." if current_java else 'The Java level of the code is not measured because this analysis has no bytecode facts.'))
    return dict(status='PROPOSED', generated_by='RULES', candidates_version=candidates['candidates_version'], rules_version=rules['rules_version'], selection_rule=SELECTION_RULE, phase_rule=PHASE_RULE,
        basis=dict(current_java=current_java, flagged_items=len(items), bytecode_facts=model.facts_available, runtime_attached=observed is not None),
        language=language, runtime=runtime, phases=phases, items=items, dropped=dropped, unverified=[],
        feasible=all(i['feasible'] for i in items), review=dict(required=True, state='PROPOSED', note='A human reviews this proposal before it becomes the active plan.'),
        limitations=['Compatibility baselines come from modernization-candidates.yaml and must be checked against each project\'s release notes before work starts.',
                     'Vulnerability data is out of scope: statuses in lifecycle-rules.yaml describe vendor support only.'])


def verify_ai(output: dict, plan: dict, evidence_ids: dict) -> tuple[list[dict], list[dict]]:
    """Keep model recommendations whose rule is in the plan and whose citations were supplied. A choice outside the curated candidates is kept but labelled."""
    rules = {i['rule_id']: i for i in plan['items']}
    candidate_ids = {i['recommended']['id'] for i in plan['items']} | {a['id'] for i in plan['items'] for a in i['alternatives']}
    kept, dropped = [], []
    for row in output.get('recommendations', []) if isinstance(output, dict) else []:
        if not isinstance(row, dict) or row.get('rule_id') not in rules:
            dropped.append(dict(text=str(row)[:200], reason='RULE_NOT_IN_PLAN')); continue
        cites = row.get('cite') or []
        if not cites or any(c not in evidence_ids for c in cites):
            dropped.append(dict(text=str(row.get('rationale'))[:200], reason='UNCITED_OR_UNKNOWN_CITATION')); continue
        choice = str(row.get('choice') or '')[:120]
        curated = choice in candidate_ids
        kept.append(dict(rule_id=row['rule_id'], choice=choice, rationale=str(row.get('rationale') or '')[:600], citations=[evidence_ids[c] for c in cites],
                         verification='CURATED' if curated else 'UNVERIFIED_CONFIRM_BEFORE_USE'))
    return kept, dropped
