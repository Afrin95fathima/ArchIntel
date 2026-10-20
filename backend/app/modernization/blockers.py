"""What each blocker code means and what resolves it. Shared by the plan text, the report and the decision brief."""

# blocker code -> (meaning, how to resolve, finding kind that carries the specifics for the domain)
BLOCKERS = {
    'PINNED_SOURCE_AND_PASSING_BUILD': ('The exact source revision is not pinned and a clean build is not confirmed.', 'Record the repository commit and run the normal build pipeline.', None),
    'BEHAVIORAL_CONTRACTS': ('No behavioral contract tests protect the domain\'s user-visible behavior.', 'Add representative API and workflow tests before changing boundaries.', 'BEHAVIOR_AND_DATA_UNKNOWN'),
    'DATA_OWNERSHIP_REVIEW': ('Write authority for the domain\'s data is not confirmed.', 'Review entities, repositories, transactions and database permissions with their owners.', 'BEHAVIOR_AND_DATA_UNKNOWN'),
    'HUMAN_CHANGE_APPROVAL': ('No reviewer has approved this proposal for implementation.', 'Obtain explicit architecture and product-owner review.', None),
    'RUNTIME_OBSERVATION_GAP': ('The selected runtime sessions do not cover enough of the domain.', 'Exercise the unobserved entry points and capture a new architecture version.', 'LIMITED_OBSERVATION'),
    'DOMAIN_REVIEW_REQUIRED': ('The candidate domain membership has not been reviewed.', 'Review and save the class membership with an architect.', 'UNREVIEWED_BOUNDARY'),
    'UNRESOLVED_MAPPING': ('Some dependency facts reference classes that have no domain.', 'Assign the named classes to a domain and capture a new version.', 'UNRESOLVED_RUNTIME_BOUNDARY'),
    'RUNTIME_QUALITY_REVIEW': ('Telemetry loss or mapping uncertainty weakens the runtime conclusions.', 'Resolve dropped, conflicting or unverified spans before relying on absence.', 'RUNTIME_QUALITY_LIMITATION'),
    'EVIDENCE_CONFLICT': ('Evidence sources disagree about a dependency.', 'Inspect the cited traces and static references and resolve the conflict.', 'CONFLICTING_EVIDENCE'),
    'CROSS_DOMAIN_CYCLE': ('The domain depends on other domains in a cycle.', 'Plan a joint cycle-remediation step before independent extraction.', 'CROSS_DOMAIN_CYCLE'),
    'SHARED_PERSISTENCE_REVIEW': ('More than one domain calls the same observed database resource.', 'Confirm table and entity ownership and the transaction boundaries.', 'SHARED_PERSISTENCE_CANDIDATE'),
    'COMPATIBILITY_INVENTORY_REQUIRED': ('Upgrade compatibility has not been checked against the technology inventory.', 'Review target versions against the lifecycle rules and the dependency inventory.', None),
}


def explain(code: str, domain_name: str, findings: list[dict]) -> dict:
    """The meaning of a blocker for one domain, with the named subjects and measured values of the finding behind it."""
    meaning, resolve, kind = BLOCKERS.get(code, ('This condition needs review before the plan is relied on.', 'Review the cited evidence and record a resolution.', None))
    own = [f for f in findings if kind and f['kind'] == kind]
    subjects = sorted({s for f in own for s in f.get('subjects', [])})
    return dict(code=code, meaning=meaning, resolve=resolve, subjects=subjects[:10], detail=' '.join(f['text'] for f in own[:2]) or None)
