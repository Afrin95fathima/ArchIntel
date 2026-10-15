"""Explainable issue rules with cohort-relative thresholds."""
from app.services.graph import stable_id


def make_issue(kind: str, severity: str, entity: str, entity_type: str, title: str, evidence: dict, why: str, recommendation: str, domains: list[str] | None = None) -> dict:
    issue_id = stable_id('issue', kind + entity_type + entity)
    return dict(id=issue_id, issue_type=kind, severity=severity,
        entity_id=entity, entity_type=entity_type, title=title, description=why, why_it_matters=why,
        evidence=evidence, recommendation=recommendation, recommendation_finding_ids=[issue_id], domain_ids=domains or [])


def detect_issues(classes, graph, class_metrics, package_metrics, thresholds, cycles, domains, membership, typed_edges=None):
    issues = []
    typed_pairs = {(e.get('source'), e.get('target'), e.get('dependency_type')) for e in (typed_edges or [])}
    expected_associations = []
    for cycle in cycles:
        affected_packages = sorted({classes[n]['package_name'] for n in cycle['members']}) if cycle['level'] == 'CLASS' else cycle['members']
        affected_domains = sorted({membership[n] for n in classes if classes[n]['package_name'] in affected_packages})
        if cycle['level'] == 'CLASS':
            affected_domains = sorted({membership[n] for n in cycle['members']})
        severity = 'CRITICAL' if len(affected_domains) > 1 else 'HIGH' if len(affected_packages) > 1 else 'MEDIUM'
        interface_pattern = cycle['level'] == 'CLASS' and len(affected_domains) == 1 and any(classes[n].get('is_interface') for n in cycle['members'])
        if interface_pattern:
            severity = 'MEDIUM' if severity == 'HIGH' else 'LOW'
        cycle.update(impacted_packages=affected_packages, impacted_domains=affected_domains, severity=severity)
        members = cycle['members']
        entity_members = cycle['level'] == 'CLASS' and len(members) == 2 and all(
            any(a.endswith('.Entity') for a in classes[n].get('annotations', [])) for n in members)
        reverse_field_pair = entity_members and (
            (members[0], members[1], 'FIELD_TYPE') in typed_pairs and
            (members[1], members[0], 'FIELD_TYPE') in typed_pairs)
        if reverse_field_pair and len(affected_domains) == 1:
            expected_associations.append((cycle, affected_domains))
            continue
        plural = 'class' if cycle['node_count'] == 1 else 'classes'
        issues.append(make_issue(cycle['issue_type'], severity, cycle['id'], cycle['level'],
            f"{cycle['node_count']} {plural} in a cyclic cluster", cycle,
            'Changes may propagate through this mutually dependent group.',
            'Inspect the sampled dependencies; break the cycle through a stable interface or reassign responsibilities.',
            affected_domains))
    for metric in class_metrics:
        name = metric['entity_id']
        abnormal = {k: {'value': metric[k], 'p95': round(thresholds[k], 2)} for k in ('method_count', 'field_count', 'fan_out') if metric[k] > thresholds[k] and metric[k] > 0}
        if len(classes) >= 5 and len(abnormal) >= 2:
            issues.append(make_issue('GOD_CLASS', 'HIGH', name, 'CLASS', f"{classes[name]['simple_name']} concentrates responsibilities",
                abnormal, 'Multiple structural signals exceed the application 95th percentile.',
                'Review responsibilities and identify cohesive subsets before splitting this class.', [membership[name]]))
        for key, kind in [('fan_in', 'HIGH_FAN_IN'), ('fan_out', 'HIGH_FAN_OUT')]:
            if len(classes) >= 5 and metric[key] > thresholds[key] and metric[key] > 1:
                issues.append(make_issue(kind, 'MEDIUM', name, 'CLASS', f"{classes[name]['simple_name']} has unusually high {key.replace('_', '-')}",
                    {'value': metric[key], 'p95': round(thresholds[key], 2)}, 'This class is a coupling outlier in this application.',
                    'Inspect the dependencies and validate whether the central responsibility is intentional.', [membership[name]]))
    by_package = {m['entity_id']: m for m in package_metrics}
    model_packages = set()
    for name, cls in classes.items():
        role_parts = {part.lower() for part in cls.get('package_name', '').split('.')}
        annotation_names = {a.rsplit('.', 1)[-1].lower() for a in cls.get('annotations', [])}
        if role_parts.intersection({'dto', 'model', 'models', 'entity', 'entities', 'pojo'}) or 'entity' in annotation_names:
            model_packages.add(cls['package_name'])
    main_sequence_models = []
    for metric in package_metrics:
        package = metric['entity_id']
        ds = sorted({membership[n] for n in classes if classes[n]['package_name'] == package})
        if not metric['isolated'] and metric['D'] > .7:
            if package in model_packages:
                main_sequence_models.append((package, metric, ds))
            else:
                issues.append(make_issue('MAIN_SEQUENCE_DEVIATION', 'MEDIUM', package, 'PACKAGE',
                    f"{package} deviates from the main sequence", metric,
                    'Abstractness and instability are imbalanced; context determines whether this creates debt.',
                    'Review concrete stable packages and abstract unused packages in their architectural role.', ds))
        unstable_targets = sorted({classes[t]['package_name'] for s, t in graph.edges
            if classes[s]['package_name'] == package and classes[t]['package_name'] != package
            and by_package[classes[t]['package_name']]['I'] > metric['I'] + .2})
        if unstable_targets:
            issues.append(make_issue('UNSTABLE_PACKAGE', 'MEDIUM', package, 'PACKAGE',
                f"{package} depends on more unstable packages", {'metrics': metric, 'targets': unstable_targets},
                'Dependency direction conflicts with the stable-dependencies heuristic.',
                'Consider depending on stable abstractions; do not treat instability alone as a defect.', ds))
    if main_sequence_models:
        packages = sorted(row[0] for row in main_sequence_models)
        issues.append(make_issue('MAIN_SEQUENCE_MODEL_SUMMARY', 'LOW', 'model-packages', 'PACKAGE_GROUP',
            f"{len(packages)} model or DTO packages have main-sequence deviations", dict(packages=[
                dict(package=package, metrics=metric) for package, metric, _ in main_sequence_models]),
            'DTO, entity and model packages often have intentionally low abstractness; inspect them as one group before treating the metric as debt.',
            'Review the listed model packages together and confirm their role before changing abstractions.',
            sorted({d for _, _, ds in main_sequence_models for d in ds})))
    for cycle, association_domains in expected_associations:
        issues.append(make_issue('EXPECTED_ENTITY_ASSOCIATION', 'LOW', cycle['id'], 'CLASS',
            'Bidirectional entity association', dict(members=cycle['members'], cycle=cycle),
            'Two entity types have reciprocal field-type references within one candidate domain. Field names and JPA mappedBy values are not present in this bytecode export, so this is an inferred association, not confirmation of its mapping.',
            'Confirm the JPA ownership and mappedBy side in source before changing this association.', association_domains))
    for domain in domains:
        metric = domain['metrics']
        if metric['cross_domain_ratio'] > .5 and metric['outgoing_edges'] >= 2:
            issues.append(make_issue('CROSS_DOMAIN_COUPLING', 'HIGH', domain['id'], 'DOMAIN',
                f"{domain['name']} has high cross-domain coupling", metric,
                'More than half of its internal-application outgoing dependencies cross the candidate boundary.',
                'Review domain membership and define a smaller explicit boundary API.', [domain['id']]))
    for s, t in graph.edges:
        if membership[s] != membership[t] and any(a.endswith('.Controller') or a.endswith('.RestController') for a in classes[t].get('annotations', [])):
            issues.append(make_issue('DOMAIN_BOUNDARY_VIOLATION', 'HIGH', s + ' -> ' + t, 'DEPENDENCY',
                'Cross-domain dependency targets a controller', {'source': s, 'target': t},
                'A candidate domain depends directly on another domain entry-point implementation.',
                'Review an application-service interface instead of depending on a controller.', [membership[s], membership[t]]))
    impact = {'CIRCULAR_DEPENDENCY':0,'LARGE_CYCLIC_CLUSTER':0,'GOD_CLASS':1,'DOMAIN_BOUNDARY_VIOLATION':1,
        'CROSS_DOMAIN_COUPLING':2,'SHARED_PERSISTENCE_CANDIDATE':2,'HIGH_FAN_IN':3,'HIGH_FAN_OUT':3,
        'UNSTABLE_PACKAGE':4,'MAIN_SEQUENCE_DEVIATION':5,'MAIN_SEQUENCE_MODEL_SUMMARY':7,'EXPECTED_ENTITY_ASSOCIATION':8}
    return sorted(issues, key=lambda x: ({'CRITICAL':0,'HIGH':1,'MEDIUM':2,'LOW':3,'INFO':4}[x['severity']], impact.get(x['issue_type'], 6), x['id']))
