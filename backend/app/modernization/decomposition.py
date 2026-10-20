"""Evidence-bound microservice candidates; proposals never claim business truth."""
import re


SETUP_REQUIREMENTS = [
    'Standalone build and dependency manifest',
    'Create the service entry point with health and readiness endpoints',
    'Externalized configuration and secret references',
    'Versioned API contract and consumer updates',
    'Service data ownership and migration plan',
    'Local orchestration and deployment manifests',
    'Add unit, contract, integration, security and dependency checks',
    'Logging, metrics, tracing and operational runbook',
]


def _slug(value):
    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return slug or 'candidate-service'


def build(static, document):
    """Project reviewed analysis domains into traceable service proposals.

    This intentionally does not merge package heuristics into asserted business
    capabilities or infer table ownership from repository/entity references.
    """
    domains = {row['domain_id']: row for row in document['target']['components']}
    source_domains = {row['id']: row for row in static.get('domains', [])}
    assessments = {row['domain_id']: row for row in document['assessments']}
    decisions = {row['domain_id']: row for row in document['decisions']}
    findings_by_domain = {}
    for row in document['findings']:
        findings_by_domain.setdefault(row['domain_id'], []).append(row)

    edges = document.get('dependency_edges', [])
    candidates = []
    slugs = set()
    for domain_id in sorted(domains):
        component = domains[domain_id]
        source = source_domains.get(domain_id, {})
        assessment = assessments[domain_id]
        decision = decisions[domain_id]
        deps = sorted({edge['target'] for edge in edges if edge['source'] == domain_id and edge['target'] != domain_id})
        consumers = sorted({edge['source'] for edge in edges if edge['target'] == domain_id and edge['source'] != domain_id})
        slug = _slug(component['name'])
        if slug in slugs:
            slug += '-' + domain_id[:8]
        slugs.add(slug)
        findings = sorted(findings_by_domain.get(domain_id, []), key=lambda row: row['id'])
        db = source.get('database', {})
        shared = bool(db.get('shared_repositories')) or any(row['kind'] == 'SHARED_PERSISTENCE_CANDIDATE' for row in findings)
        data = dict(
            repositories=sorted(set(db.get('repositories', []))),
            entity_classes=sorted(set(db.get('entities', []))),
            shared_repository_candidates=sorted(set(item.get('repository', '') for item in db.get('shared_repositories', []) if item.get('repository'))),
            ownership='UNCONFIRMED_SHARED' if shared else 'UNCONFIRMED',
            evidence_scope='STATIC_STRUCTURAL_SIGNALS',
            note=f"Repository and entity references of {source.get('name') or domain_id} are discovery signals only; table ownership, transactions and invariants need review.",
        )
        candidates.append(dict(
            id=domain_id,
            name=component['name'],
            repository_name=slug,
            proposal_state='CANDIDATE_REQUIRES_REVIEW',
            selection_source=source.get('domain_source', 'UNKNOWN'),
            boundary_confidence=source.get('confidence'),
            confidence_note=source.get('confidence_note', 'Boundary confidence was not supplied by this analysis.'),
            class_ids=sorted(set(component.get('classes', []))),
            packages=sorted(set(source.get('packages', []))),
            dependencies=deps,
            consumers=consumers,
            data=data,
            readiness=assessment['combined_score'],
            evidence_confidence=assessment['confidence_score'],
            decision=decision['kind'],
            blockers=sorted(set(decision['blockers'])),
            risks=[dict(kind=row['kind'], severity=row['severity'], text=row['text'], finding_id=row['id'], evidence_ids=row['evidence_ids']) for row in findings],
            evidence_ids=sorted(set(assessment['evidence_ids'] + [eid for row in findings for eid in row['evidence_ids']])),
            fact_ids=sorted(set(assessment['fact_ids'] + [fid for row in findings for fid in row['fact_ids']])),
            required_setup=list(SETUP_REQUIREMENTS),
        ))

    return dict(
        rule_version='microservice-decomposition-1',
        status='PROPOSAL_ONLY',
        source_version_id=document['version_id'],
        source_version_fingerprint=document['version_fingerprint'],
        strategy='MICROSERVICES',
        strategy_source='ARCHINTEL_CANDIDATE_PROPOSAL',
        service_candidates=candidates,
        rollout_modes=[
            dict(id='WHOLE_SYSTEM', name='Modernize the whole monolith', output=f'Coordinated workspace with all {len(candidates)} candidate services, shared local setup, contracts, data plans and end-to-end checks.'),
            dict(id='ONE_BY_ONE', name='Modernize one microservice at a time', output=f'A separate repository per selected service (one of {len(candidates)} candidates), with its own build, runtime setup, contracts and validation evidence.'),
        ],
        shared_setup=['Local orchestration manifest', 'Environment template without credentials', 'Service health/readiness checks', 'API/contract test harness', 'Observability defaults', 'Run and rollback instructions'],
        execution=dict(allowed=False, state='NOT_GENERATED', requires=['PINNED_SOURCE_REPOSITORY', 'EXPLICIT_MODEL_AND_SOURCE_TRANSFER_POLICY', 'BEHAVIORAL_CONTRACTS', 'CUSTOMER_REVIEWED_BOUNDARIES', 'DATA_OWNERSHIP_REVIEW', 'ISOLATED_BUILD_AND_SECURITY_VALIDATION']),
        limitations=[
            f'Each of the {len(candidates)} candidate services is a heuristic boundary, not a confirmed business microservice.',
            f'Ownership and deployment fit of the {len(candidates)} candidates are not inferred from package names.',
            'Static data signals of this proposal do not establish table ownership or safe data separation.',
            'Runtime evidence describes the selected workload only; missing calls do not prove independence.',
            'No source code, repository, deployment or database was changed or generated by this proposal.',
        ],
    )
