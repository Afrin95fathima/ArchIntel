"""What changed between two versions of the same static baseline: domains, facts and open suggestions."""
from sqlalchemy import select

from .models import ArchitectureFact, DiscoveryItem


def _facts(db, version) -> dict:
    return {(f.document['source'], f.document['target']): f.classification for f in db.scalars(select(ArchitectureFact).where(ArchitectureFact.version_id == version.id))}


def _gaps(db, version) -> dict:
    return {g.document['text']: g.state for g in db.scalars(select(DiscoveryItem).where(DiscoveryItem.version_id == version.id))}


def detail(db, a, b) -> dict:
    """`a` is the earlier version and `b` the later one; every list is bounded."""
    members_a = {c: d['id'] for d in a.document['domains'] for c in d['classes']}
    members_b = {c: d['id'] for d in b.document['domains'] for c in d['classes']}
    names_a = {d['id']: d['name'] for d in a.document['domains']}
    names_b = {d['id']: d['name'] for d in b.document['domains']}
    moved = [dict(cls=c, from_domain=names_a[members_a[c]], to_domain=names_b[members_b[c]]) for c in sorted(members_a) if c in members_b and members_a[c] != members_b[c]]
    renamed = [dict(id=i, from_name=names_a[i], to_name=names_b[i]) for i in sorted(names_a) if i in names_b and names_a[i] != names_b[i]]
    obs_a = {d['id']: d for d in a.document['coverage'].get('domain_observations', [])}
    obs_b = {d['id']: d for d in b.document['coverage'].get('domain_observations', [])}
    domains = []
    for did in sorted(obs_b, key=lambda i: names_b.get(i, '')):
        before, after = obs_a.get(did), obs_b[did]
        domains.append(dict(id=did, name=names_b.get(did, after.get('name')), before=None if not before else dict(observed=before['observed'], total=before['total']), after=dict(observed=after['observed'], total=after['total'])))
    facts_a, facts_b = _facts(db, a), _facts(db, b)
    counts = lambda facts: {k: sum(1 for v in facts.values() if v == k) for k in ('STATIC_AND_DYNAMIC', 'STATIC_ONLY', 'DYNAMIC_ONLY')}
    changed = [dict(source=s, target=t, before=facts_a.get((s, t)), after=c) for (s, t), c in sorted(facts_b.items()) if facts_a.get((s, t)) != c]
    gaps_a, gaps_b = _gaps(db, a), _gaps(db, b)
    return dict(
        runtime_sessions=dict(before=len(a.manifest.get('runtime_session_ids', [])), after=len(b.manifest.get('runtime_session_ids', []))),
        domains=domains, moved_classes=moved[:50], moved_total=len(moved), renamed_domains=renamed,
        facts=dict(before=counts(facts_a), after=counts(facts_b), changed=changed[:50], changed_total=len(changed)),
        suggestions=dict(before=len(gaps_a), after=len(gaps_b), closed=sorted(t for t in gaps_a if t not in gaps_b)[:50], closed_total=sum(1 for t in gaps_a if t not in gaps_b),
                         opened=sorted(t for t in gaps_b if t not in gaps_a)[:50], opened_total=sum(1 for t in gaps_b if t not in gaps_a)),
    )
