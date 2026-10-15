"""Deterministic comparison of recorded build evidence; never executes customer code.

A passing contract comparison is deliberately narrower than behavioral equivalence.
Architecture and security gates cannot be supplied or overridden by a client.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from app.evidence.builder import digest

RULE_VERSION = 'transformation-validation-1'


def evaluate(task, builds, contracts, changeset):
    doc = task.document
    latest = {kind: next((b for b in reversed(builds) if b.kind == kind), None)
              for kind in ('BASELINE', 'CANDIDATE')}
    gates = []

    def gate(name, status, reasons):
        gates.append(dict(name=name, status=status, reasons=sorted(set(reasons))))

    gate('SOURCE_SNAPSHOT', 'PASS' if doc['complete_source_snapshot'] else 'FAIL',
         [] if doc['complete_source_snapshot'] else ['INCOMPLETE_SOURCE_SNAPSHOT'])
    results = {}
    for kind, manifest in [('BASELINE', doc['workspace']['baseline']), ('CANDIDATE', doc['workspace']['current'])]:
        run = latest[kind]
        reasons = []
        if run is None:
            gate(kind + '_BUILD', 'NOT_RUN', ['BUILD_REQUIRED'])
            continue
        result = run.document.get('result') or {}
        results[kind] = result
        if run.state != 'PASSED': reasons.append('LATEST_BUILD_NOT_PASSED')
        if run.document.get('input_sha256') != digest(manifest): reasons.append('SOURCE_HASH_MISMATCH')
        if kind == 'BASELINE' and result.get('artifact_sha256') != doc['expected_artifact_sha256']:
            reasons.append('BASELINE_ARTIFACT_MISMATCH')
        if not result.get('artifact_sha256'): reasons.append('ARTIFACT_HASH_MISSING')
        if kind == 'CANDIDATE' and (not changeset or run.document.get('changeset_fingerprint') != changeset.fingerprint):
            reasons.append('CHANGESET_BINDING_MISSING')
        if result.get('tests', 0) <= result.get('skipped', 0) or result.get('failures', 0) or result.get('errors', 0):
            reasons.append('PASSING_TESTS_REQUIRED')
        gate(kind + '_BUILD', 'FAIL' if reasons else 'PASS', reasons)

    baseline, candidate = results.get('BASELINE', {}), results.get('CANDIDATE', {})
    environment_matches = bool(baseline.get('image_id')) and baseline.get('image_id') == candidate.get('image_id')
    gate('BUILD_ENVIRONMENT', 'PASS' if environment_matches else 'INCONCLUSIVE',
         [] if environment_matches else ['MATCHING_PINNED_BUILD_IMAGES_REQUIRED'])

    comparisons = []
    case_maps = []
    for result in (baseline, candidate):
        cases = defaultdict(list)
        for case in result.get('cases', []): cases[case['name']].append(case)
        case_maps.append(cases)
    for contract in contracts:
        c = contract.document
        reasons = []
        if not contract.review or contract.review.get('hash') != digest(c): reasons.append('CURRENT_HUMAN_REVIEW_REQUIRED')
        expected_hash = c['test_file_sha256']
        if any(doc['workspace'][m].get(c['test_file']) != expected_hash for m in ('baseline', 'current')):
            reasons.append('CONTRACT_TEST_CHANGED_OR_REMOVED')
        for label, cases in zip(('BASELINE', 'CANDIDATE'), case_maps):
            matches = cases.get(c['test_case'], [])
            if len(matches) != 1: reasons.append(label + '_CASE_MISSING_OR_AMBIGUOUS')
            elif matches[0].get('passed') is not True: reasons.append(label + '_CASE_NOT_PASSED')
        comparisons.append(dict(contract_id=contract.id, test_case=c['test_case'], critical=c['critical'],
                                status='FAIL' if reasons else 'PASS', reasons=reasons))
    behavior_reasons = []
    if not comparisons: behavior_reasons.append('REVIEWED_CONTRACTS_REQUIRED')
    if any(c['status'] != 'PASS' for c in comparisons): behavior_reasons.append('CONTRACT_COMPARISON_FAILED')
    # Preserve the entire baseline test inventory, including non-contract cases.
    before = Counter(c['name'] for c in baseline.get('cases', []))
    after = Counter(c['name'] for c in candidate.get('cases', []))
    if before - after: behavior_reasons.append('BASELINE_TEST_CASES_REMOVED')
    if any(c.get('passed') is not True for c in candidate.get('cases', [])):
        behavior_reasons.append('CANDIDATE_CASE_FAILED_OR_SKIPPED')
    if not environment_matches or any(g['status'] != 'PASS' for g in gates):
        behavior_reasons.append('BUILD_COMPARISON_PREREQUISITES_NOT_PASSED')
    gate('REVIEWED_CONTRACT_COMPARISON', 'FAIL' if behavior_reasons else 'PASS', behavior_reasons)
    architecture = doc.get('architecture_reanalysis') or {}
    architecture_reasons = []
    if architecture.get('state') != 'COMPLETED': architecture_reasons.append('CANDIDATE_SCANNER_AND_GRAPH_DIFF_REQUIRED')
    if architecture.get('changeset_fingerprint') != (changeset.fingerprint if changeset else None):
        architecture_reasons.append('ARCHITECTURE_CHANGESET_BINDING_MISMATCH')
    candidate_build = latest['CANDIDATE']
    if architecture.get('build_id') != (candidate_build.id if candidate_build else None):
        architecture_reasons.append('ARCHITECTURE_BUILD_BINDING_MISMATCH')
    if architecture.get('artifact_sha256') != candidate.get('artifact_sha256'):
        architecture_reasons.append('ARCHITECTURE_ARTIFACT_BINDING_MISMATCH')
    if architecture.get('diff', {}).get('eligibility') != 'ELIGIBLE':
        architecture_reasons.append('ARCHITECTURE_COMPARISON_INCONCLUSIVE')
    architecture_status = 'FAIL' if architecture_reasons else 'PASS'
    if not architecture or architecture.get('state') in ('QUEUED', 'RUNNING'):
        architecture_status = 'NOT_RUN'
    elif architecture_reasons == ['ARCHITECTURE_COMPARISON_INCONCLUSIVE']:
        architecture_status = 'INCONCLUSIVE'
    gate('ARCHITECTURE_REANALYSIS', architecture_status, architecture_reasons)
    removed_classes = architecture.get('diff', {}).get('classes', {}).get('removed', [])
    inventory_status = 'NOT_RUN' if architecture.get('state') != 'COMPLETED' else ('FAIL' if removed_classes else 'PASS')
    gate('BASELINE_CLASS_INVENTORY', inventory_status,
         ['BASELINE_CLASSES_REMOVED'] if removed_classes else ([] if inventory_status == 'PASS' else ['CANDIDATE_REANALYSIS_REQUIRED']))
    impact = architecture.get('expected_improvement') or {}
    review = doc.get('expected_impact_review') or {}
    reviewed = review.get('decision') == 'ACCEPT' and review.get('impact_fingerprint') == impact.get('fingerprint')
    impact_status = impact.get('state', 'NOT_RUN')
    if impact_status == 'PASS' and not reviewed: impact_status = 'NOT_RUN'
    gate('EXPECTED_IMPROVEMENT', impact_status,
         [] if impact_status == 'PASS' else (impact.get('reasons') or ['HUMAN_ACCEPTANCE_OF_MEASURED_IMPROVEMENT_REQUIRED']))
    security = doc.get('security_analysis') or {}
    security_reasons = []
    if security.get('state') != 'PASS': security_reasons.append('TRUSTED_SAST_PASS_REQUIRED')
    if security.get('input_sha256') != digest(doc['workspace']['current']): security_reasons.append('SECURITY_SOURCE_MISMATCH')
    if security.get('changeset_fingerprint') != (changeset.fingerprint if changeset else None): security_reasons.append('SECURITY_CHANGESET_MISMATCH')
    if security.get('build_id') != (candidate_build.id if candidate_build else None): security_reasons.append('SECURITY_BUILD_MISMATCH')
    if security.get('artifact_sha256') != candidate.get('artifact_sha256'): security_reasons.append('SECURITY_ARTIFACT_MISMATCH')
    gate('JAVA_SECURITY_ANALYSIS', ('FAIL' if security_reasons else 'PASS') if security else 'NOT_RUN', security_reasons)
    dependency = (security.get('result') or {}).get('dependency_scan') or {}
    dep_status = dependency.get('state', 'NOT_RUN')
    if dep_status not in ('PASS','FAIL','NOT_RUN','INCONCLUSIVE'): dep_status='INCONCLUSIVE'
    # A finding is useful even when SAST failed; a pass requires the same exact
    # artifact and successful current server-owned execution.
    if dep_status=='PASS' and (security_reasons or dependency.get('artifact_sha256') != candidate.get('artifact_sha256')): dep_status='INCONCLUSIVE'
    if dep_status=='PASS' and dependency.get('coverage') != 'PACKAGED_ARCHIVE_COMPLETE': dep_status='INCONCLUSIVE'
    if dep_status=='PASS':
        try:
            timestamps=[datetime.fromisoformat(dependency['databases'][kind]['updated_at']) for kind in ('db','java-db')]
            clock=datetime.now(timezone.utc)
            if any(t.tzinfo is None or not -timedelta(minutes=5) <= clock-t <= timedelta(days=7) for t in timestamps): raise ValueError()
        except (KeyError,TypeError,ValueError): dep_status='INCONCLUSIVE'
    gate('PACKAGED_DEPENDENCY_ANALYSIS',dep_status, [] if dep_status=='PASS' else [dependency.get('reason','DEPENDENCY_SCAN_REQUIRED_OR_COVERAGE_INCOMPLETE')])
    dependency_coverage = dependency.get('coverage') == 'PACKAGED_ARCHIVE_COMPLETE'
    security_complete = not security_reasons and security.get('state') == 'PASS' and dep_status == 'PASS' and dependency_coverage
    generated_security_status = ('PASS' if security_complete else 'FAIL' if security.get('state') == 'FAIL' or dep_status == 'FAIL'
        else 'NOT_RUN' if not security or dep_status == 'NOT_RUN' else 'INCONCLUSIVE')
    gate('GENERATED_CODE_SECURITY', generated_security_status,
         [] if security_complete else ['CURRENT_SAST_AND_COMPLETE_PACKAGED_RUNTIME_DEPENDENCY_COVERAGE_REQUIRED'])
    candidate_version = doc.get('candidate_architecture') or {}
    publication_complete = (candidate_version.get('state') == 'PUBLISHED' and
        bool(candidate_version.get('version_id')) and bool(candidate_version.get('version_fingerprint')) and
        candidate_version.get('parent_version_id') == task.version_id and
        candidate_version.get('analysis_id') == architecture.get('analysis_id') and
        candidate_version.get('artifact_sha256') == architecture.get('artifact_sha256') and
        candidate_version.get('build_id') == candidate_build.id if candidate_build else False)
    gate('CANONICAL_CANDIDATE_VERSION', 'PASS' if publication_complete else 'NOT_RUN',
         [] if publication_complete else ['VALIDATED_CANDIDATE_ARCHITECTURE_VERSION_REQUIRED'])
    eligible = bool(gates) and all(g['status'] == 'PASS' for g in gates)
    return dict(rule_version=RULE_VERSION, state='READY_FOR_FINAL_APPROVAL' if eligible else 'BLOCKED', approval_eligible=eligible,
                changeset_fingerprint=changeset.fingerprint if changeset else None,
                source_sha256=digest(doc['workspace']['current']),
                build_ids={kind: b.id if b else None for kind, b in latest.items()},
                architecture_fingerprint=digest(architecture) if architecture else None,
                security_fingerprint=digest(security) if security else None,
                gates=gates, contracts=comparisons,
                scope='Reviewed test cases only; not a proof of full behavioral equivalence.')
