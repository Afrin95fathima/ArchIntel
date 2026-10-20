"""Pure, conservative extraction-boundary assessment for Phase 7B."""
from app.evidence.builder import digest


RULE_VERSION = 'extraction-boundary-1'
MAX_BOUNDARY_EDGES = 200


def build_plan(analysis, domain_id, source_manifest, *, complete_source_snapshot, contracts, data_ownership_review=None):
    classes = analysis.get('classes', [])
    by_id = {row.get('id'): row for row in classes if row.get('id')}
    target_ids = {name for name, row in by_id.items() if row.get('domain_id') == domain_id}
    domain = next((row for row in analysis.get('domains', []) if row.get('id') == domain_id), None)
    manifest = dict(source_manifest)
    paths = sorted(manifest)
    blockers = []
    if not domain or not target_ids:
        blockers.append('TARGET_DOMAIN_NOT_PRESENT_IN_BASELINE')
    if not complete_source_snapshot:
        blockers.append('COMPLETE_SOURCE_SNAPSHOT_REQUIRED')

    class_paths = {}
    all_class_paths = {}
    unresolved_classes = []
    for class_id in sorted(by_id):
        row = by_id[class_id]
        package = row.get('package_name')
        simple_name = class_id.rsplit('.', 1)[-1].split('$', 1)[0]
        suffix = (package.replace('.', '/') + '/' if package and package != '(default)' else '') + simple_name + '.java'
        matches = [path for path in paths if path == suffix or path.endswith('/' + suffix)]
        if len(matches) == 1:
            all_class_paths[class_id] = matches[0]
            if class_id in target_ids:
                class_paths[class_id] = matches[0]
        elif class_id in target_ids:
            unresolved_classes.append(class_id)
    if unresolved_classes:
        blockers.append('TARGET_SOURCE_FILES_UNRESOLVED_OR_AMBIGUOUS')

    shared_files = []
    by_source_path = {}
    for class_id, path in all_class_paths.items():
        by_source_path.setdefault(path, []).append(class_id)
    for path, members in sorted(by_source_path.items()):
        inside = [name for name in members if name in target_ids]
        outside = [name for name in members if name not in target_ids]
        if inside and outside:
            shared_files.append(dict(path=path, target_classes=sorted(inside), outside_target=sorted(outside)))
    if shared_files:
        blockers.append('SOURCE_FILES_CONTAIN_CLASSES_OUTSIDE_TARGET_DOMAIN')

    boundary_edges = []
    for edge in analysis.get('edges', []):
        source, target = edge.get('source'), edge.get('target')
        if source not in by_id or target not in by_id or ((source in target_ids) == (target in target_ids)):
            continue
        boundary_edges.append(dict(
            source=source,
            target=target,
            dependency_type=edge.get('dependency_type', 'UNKNOWN'),
            direction='OUTGOING' if source in target_ids else 'INCOMING',
        ))
    boundary_edges.sort(key=lambda row: (row['direction'], row['source'], row['target'], row['dependency_type']))

    crossing_cycles = []
    for cycle in analysis.get('cycles', []):
        members = set(cycle.get('members', []))
        if cycle.get('level') == 'CLASS' and members & target_ids and members - target_ids:
            crossing_cycles.append(dict(level='CLASS', members=sorted(members)))
    if crossing_cycles:
        blockers.append('CYCLE_CROSSES_PROPOSED_EXTRACTION_BOUNDARY')

    reviewed_contracts = [row for row in contracts if row.review]
    if not reviewed_contracts or len(reviewed_contracts) != len(contracts):
        blockers.append('ALL_BEHAVIORAL_CONTRACTS_MUST_BE_REVIEWED')
    if not data_ownership_review:
        blockers.append('DATA_OWNERSHIP_REVIEW_REQUIRED')

    result = dict(
        rule_version=RULE_VERSION,
        state='PREVIEW_ONLY',
        execution_eligible=False,
        target=dict(domain_id=domain_id, name=domain.get('name') if domain else None,
                    class_ids=sorted(target_ids), packages=sorted({by_id[name].get('package_name', '(unknown)') for name in target_ids}),
                    source_files=sorted(set(class_paths.values())), unresolved_classes=unresolved_classes,
                    source_mapping='PACKAGE_AND_TYPE_FILENAME_SUFFIX_CANDIDATES'),
        boundary=dict(
            incoming_count=sum(row['direction'] == 'INCOMING' for row in boundary_edges),
            outgoing_count=sum(row['direction'] == 'OUTGOING' for row in boundary_edges),
            edges=boundary_edges[:MAX_BOUNDARY_EDGES],
            edges_truncated=len(boundary_edges) > MAX_BOUNDARY_EDGES,
            crossing_cycles=crossing_cycles,
            shared_source_files=shared_files,
        ),
        prerequisites=dict(
            complete_source_snapshot=bool(complete_source_snapshot),
            reviewed_contract_count=len(reviewed_contracts),
            total_contract_count=len(contracts),
            data_ownership_reviewed=bool(data_ownership_review),
        ),
        blockers=sorted(set(blockers)),
        limitations=[
            'The ExtractionPlan is a static boundary preview; it does not create or move source files.',
            'Runtime, reflection, Spring wiring, transaction and business behavior are not inferred.',
            'Source paths are filename/package-suffix candidates, not AST-verified type declarations; unresolved classes remain explicit.',
            'A human must review ownership, contracts, dependencies and the proposed module boundary (ExtractionPlan).',
        ],
        inputs=dict(analysis_sha256=digest(analysis), source_manifest_sha256=digest(manifest),
                    contracts_sha256=digest([dict(document=getattr(row, 'document', {}), review=row.review) for row in contracts]),
                    data_ownership_review_sha256=digest(data_ownership_review) if data_ownership_review else None,
                    target_domain_id=domain_id),
    )
    result['fingerprint'] = digest(result)
    return result
