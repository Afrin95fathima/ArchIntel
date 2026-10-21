"""What would raise this version's evidence to the level the modernization plan asks for.

Everything here is derived from the version's own coverage, facts and discovery suggestions and from the plan's
published threshold. The gain of one suggestion is an upper bound: the unobserved classes that the code analysis can
reach from its entry class. It is not a prediction of what a session will actually exercise.
"""
import re
from collections import defaultdict, deque

from app.modernization.thresholds import MIN_OBSERVED_CLASS_PERCENTAGE as TARGET

ENTRY_TEXT = re.compile(r'^Exercise (?P<cls>.+)\.(?P<method>[^.]+) and capture')
LIMITS = [
    'For this version, the gain of a suggestion is an upper bound: the unobserved classes the code analysis can reach from its entry class.',
    'The estimate does not predict what a session will exercise, and it changes no plan score until a new version of this application is captured.',
    'Calls made through frameworks, reflection or messaging are not in the code analysis of this version, so they are not counted.',
]


def needed_classes(observed: int, total: int) -> int:
    """Smallest number of additional classes that brings observed/total to the target share."""
    return max(0, -(-TARGET * total // 100) - observed) if total else 0


def build(version, facts: list[dict], gaps: list[dict]) -> dict:
    document, manifest = version.document, version.manifest
    observations = {d['id']: d for d in document['coverage'].get('domain_observations', [])}
    members = {c: d['id'] for d in document['domains'] for c in d['classes']}
    names = {d['id']: d['name'] for d in document['domains']}
    sizes = {d['id']: len(d['classes']) for d in document['domains']}
    unobserved = {c for d in observations.values() for c in d.get('unobserved_classes', [])}
    adjacency = defaultdict(set)
    for fact in facts:
        if fact['classification'] != 'DYNAMIC_ONLY':
            adjacency[fact['source']].add(fact['target'])

    def reachable(start: str) -> set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            for nxt in adjacency[queue.popleft()]:
                if nxt in members and nxt not in seen:
                    seen.add(nxt); queue.append(nxt)
        return seen & unobserved

    has_runtime = bool(manifest.get('runtime_session_ids'))
    conditions = [
        dict(id='RUNTIME_SESSION', met=has_runtime, text='A completed runtime session is part of this version.' if has_runtime else 'No runtime session is part of this version, so the plan treats every domain as unobserved.'),
        dict(id='DOMAIN_REVIEW', met=bool(manifest.get('domain_review')), text='The domain boundaries were reviewed for this version.' if manifest.get('domain_review') else 'The domain boundaries were not reviewed for this version; the plan keeps every domain at "collect more evidence" until they are.'),
    ]
    ranked = []
    for gap in gaps:
        match = ENTRY_TEXT.match(gap['text']) if gap['kind'] == 'ENTRY_POINT' and gap['state'] == 'OPEN' else None
        if not match or match['cls'] not in members:
            continue
        reach = reachable(match['cls'])
        per_domain = defaultdict(int)
        for cls in reach:
            per_domain[members[cls]] += 1
        ranked.append(dict(discovery_id=gap['id'], text=gap['text'], entry_class=match['cls'], method=match['method'], domain_id=members[match['cls']], domain_name=names[members[match['cls']]],
                           up_to_new_classes=len(reach), reachable_unobserved=sorted(reach), per_domain={names[k]: v for k, v in sorted(per_domain.items())}))
    ranked.sort(key=lambda g: (-g['up_to_new_classes'], g['entry_class'], g['method']))
    reach_all = defaultdict(set)
    for gap in ranked:
        for cls in gap['reachable_unobserved']:
            reach_all[members[cls]].add(cls)
    domains = []
    for did, name in sorted(names.items(), key=lambda kv: kv[1]):
        observation = observations.get(did, {})
        observed, total = observation.get('observed', 0) or 0, observation.get('total', sizes[did]) or 0
        need = needed_classes(observed, total) if has_runtime else needed_classes(0, total)
        domains.append(dict(id=did, name=name, observed=observed if has_runtime else 0, total=total, percentage=round(100 * observed / total, 2) if has_runtime and total else 0.0,
                            target_percentage=TARGET, met=need == 0, classes_needed=need, unobserved_classes=sorted(observation.get('unobserved_classes', [])),
                            reachable_by_open_suggestions=len(reach_all[did]), can_reach_target=(need == 0) or (observed + len(reach_all[did]) >= observed + need)))
    return dict(target_percentage=TARGET, conditions=conditions, domains=domains, suggestions=ranked[:10], limits=LIMITS,
                ready=all(c['met'] for c in conditions) and all(d['met'] for d in domains))
