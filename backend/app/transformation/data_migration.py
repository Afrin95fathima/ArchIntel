"""Conservative, read-only Phase 7C migration-plan assessment."""
from app.evidence.builder import digest

RULE_VERSION = 'data-migration-plan-1'


def build_plan(spec, *, version_id, version_fingerprint, source_manifest_sha256,
               data_ownership_review, database_evidence=None):
    """Assess an explicitly authored mapping; never connects to or mutates a database."""
    source = spec['source']
    target = spec['target']
    mappings = spec['mappings']
    blockers = []
    if source['resource'].casefold() == target['resource'].casefold() and source['system'].casefold() == target['system'].casefold():
        blockers.append('SOURCE_AND_TARGET_RESOURCE_MUST_DIFFER')
    if not data_ownership_review or not data_ownership_review.get('reviewed'):
        blockers.append('REVIEWED_DATA_OWNERSHIP_REQUIRED')
    source_columns = [row['source_column'].casefold() for row in mappings]
    target_columns = [row['target_column'].casefold() for row in mappings]
    if len(source_columns) != len(set(source_columns)):
        blockers.append('SOURCE_COLUMN_MAPPED_MORE_THAN_ONCE')
    if len(target_columns) != len(set(target_columns)):
        blockers.append('TARGET_COLUMN_MAPPED_MORE_THAN_ONCE')
    if not any(row['key'] for row in mappings):
        blockers.append('STABLE_ROW_KEY_MAPPING_REQUIRED')
    if not spec['invariants']:
        blockers.append('DATA_INVARIANTS_REQUIRED')
    if not spec['recovery']['backup_id'] or not spec['recovery']['restore_tested']:
        blockers.append('VERIFIED_BACKUP_AND_RESTORE_REQUIRED')
    if not spec['conflict_policy']:
        blockers.append('CONFLICT_POLICY_REQUIRED')
    if not database_evidence:
        blockers.append('DATABASE_EVIDENCE_UNAVAILABLE')
    document = dict(
        rule_version=RULE_VERSION, state='PREVIEW_ONLY', execution_eligible=False,
        version_id=version_id, version_fingerprint=version_fingerprint,
        source_manifest_sha256=source_manifest_sha256,
        source=source, target=target, mappings=mappings,
        invariants=spec['invariants'], conflict_policy=spec['conflict_policy'],
        recovery=spec['recovery'], ownership_review=data_ownership_review,
        database_evidence=database_evidence or [],
        required_checks=['SOURCE_AND_TARGET_ROW_COUNTS', 'KEY_UNIQUENESS', 'NULL_AND_CONVERSION_ERRORS',
                         'REFERENTIAL_INTEGRITY', 'BUSINESS_INVARIANTS', 'APPLICATION_BEHAVIOR',
                         'BACKUP_RESTORE_DRILL', 'RECONCILIATION_AFTER_CUTOVER'],
        blockers=sorted(set(blockers)),
        limitations=['This plan is metadata-only and performs no database connection, SQL generation, or writes.',
                     'Runtime database observations (DATABASE evidence) are contextual only; they do not prove table ownership or complete traffic.',
                     'A disposable representative database and reviewed invariants (BUSINESS_INVARIANT) are required before execution.'],
    )
    document['fingerprint'] = digest(document)
    return document
