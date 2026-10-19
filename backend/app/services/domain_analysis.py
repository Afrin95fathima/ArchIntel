"""Deterministic domain boundary, model-overlap and data-ownership analysis."""
import re
from collections import Counter, defaultdict
from app.services.runtime.entry_points import is_method_entry_point


TYPE_GROUPS = {
    'CALL': {'METHOD_CALL', 'CALLS'},
    'INHERITANCE': {'EXTENDS', 'IMPLEMENTS', 'INHERITS', 'IMPLEMENTS_INTERFACE'},
    'FIELD_OR_TYPE_REFERENCE': {'FIELD_TYPE', 'TYPE_REFERENCE', 'RETURNS', 'RETURN_TYPE', 'PARAMETER_TYPE', 'ANNOTATION', 'GENERIC_TYPE', 'EXCEPTION'},
}


def _edge_group(kind):
    upper = str(kind or 'UNKNOWN').upper()
    return next((name for name, values in TYPE_GROUPS.items() if upper in values), 'OTHER')


def dependency_matrix(domains, classes, edges, membership):
    """Return a complete directed matrix plus concrete class-boundary rows."""
    grouped = defaultdict(list)
    for edge in edges:
        source, target = edge.get('source'), edge.get('target')
        source_domain, target_domain = membership.get(source), membership.get(target)
        if source_domain and target_domain and source_domain != target_domain:
            grouped[(source_domain, target_domain)].append(edge)
    rows = []
    domain_names={d['id']:d['name'] for d in domains}
    for (source_id,target_id),boundary in sorted(grouped.items()):
        edge_types = Counter(str(e.get('dependency_type', 'UNKNOWN')) for e in boundary)
        sources = sorted({e['source'] for e in boundary})
        targets = sorted({e['target'] for e in boundary})
        rows.append(dict(source_domain_id=source_id, source_domain=domain_names[source_id],
            target_domain_id=target_id, target_domain=domain_names[target_id], edge_count=len(boundary),
            distinct_source_classes=len(sources), distinct_target_classes=len(targets),
            boundary_class_count=len(set(sources) | set(targets)), edge_types=dict(sorted(edge_types.items())),
            edge_groups=dict(sorted(Counter(_edge_group(e.get('dependency_type')) for e in boundary).items())),
            class_pairs=[dict(source=e['source'], target=e['target'], edge_type=e.get('dependency_type', 'UNKNOWN'),
                edge_id=e.get('id')) for e in sorted(boundary, key=lambda x:(x['source'],x['target'],x.get('dependency_type','')))[:10]]))
    totals = defaultdict(lambda: dict(afferent_edges=0,efferent_edges=0,afferent_domains=set(),efferent_domains=set(),boundary_classes=set()))
    class_boundaries = Counter()
    for (source, target), boundary in grouped.items():
        totals[source]['efferent_edges'] += len(boundary)
        totals[source]['efferent_domains'].add(target)
        totals[target]['afferent_edges'] += len(boundary)
        totals[target]['afferent_domains'].add(source)
        totals[source]['boundary_classes'].update(e['source'] for e in boundary)
        totals[target]['boundary_classes'].update(e['target'] for e in boundary)
        class_boundaries.update(e['source'] for e in boundary)
        class_boundaries.update(e['target'] for e in boundary)
    inbound_total=Counter();outbound_total=Counter()
    for edge in edges:
        source_domain,target_domain=membership.get(edge.get('source')),membership.get(edge.get('target'))
        if source_domain and target_domain:
            outbound_total[source_domain]+=1;inbound_total[target_domain]+=1
    per_domain = {d['id']: dict(afferent_cross_domain_edges=totals[d['id']]['afferent_edges'],
        efferent_cross_domain_edges=totals[d['id']]['efferent_edges'],
        afferent_cross_domain_coupling=round(totals[d['id']]['afferent_edges']/max(1,inbound_total[d['id']]),4),
        efferent_cross_domain_coupling=round(totals[d['id']]['efferent_edges']/max(1,outbound_total[d['id']]),4),
        afferent_domains=len(totals[d['id']]['afferent_domains']), efferent_domains=len(totals[d['id']]['efferent_domains']),
        boundary_crossing_classes=len(totals[d['id']]['boundary_classes'])) for d in domains}
    return dict(domain_ids=[dict(id=d['id'],name=d['name']) for d in domains],rows=rows,matrix_complete=True,
        zero_cell_note='An ordered domain pair absent from rows has zero class-level dependency edges.',per_domain=per_domain,
        top_boundary_classes=[dict(class_name=name,boundary_edges=count,domain=membership[name]) for name,count in
            sorted(class_boundaries.items(),key=lambda item:(-item[1],item[0]))[:10]])


def _concept(simple_name):
    value = simple_name.rsplit('$', 1)[0]
    value = re.sub(r'(?i)(dto|model|entity|record|view|data)$', '', value)
    return value.lower()


def model_overlap(domains, classes, edges, membership):
    """Find name-based model overlap; fields are absent in current graph export."""
    domain_by_id = {d['id']: d for d in domains}
    concept_domains = defaultdict(list)
    models = {}
    for name, cls in classes.items():
        did = membership.get(name)
        if not did:
            continue
        segments = {part.casefold() for part in cls.get('package_name', '').split('.')}
        annotations = {a.rsplit('.', 1)[-1].casefold() for a in cls.get('annotations', [])}
        looks_like_model = bool(segments & {'dto','model','models','entity','entities','pojo'} or 'entity' in annotations or 'table' in annotations)
        if not looks_like_model:
            continue
        concept = _concept(cls.get('simple_name') or name.rsplit('.',1)[-1])
        if len(concept) < 3:
            continue
        models[name] = dict(class_name=name, domain_id=did, domain=domain_by_id[did]['name'], concept=concept,
            annotations=sorted(annotations), model_evidence='ANNOTATION' if annotations & {'entity','table'} else 'PACKAGE_CONVENTION')
        concept_domains[concept].append(name)
    duplicated = []
    for concept, names in sorted(concept_domains.items()):
        if len({models[n]['domain_id'] for n in names}) > 1:
            duplicated.append(dict(kind='DUPLICATED_MODEL', concept=concept, classes=sorted(names),
                domains=sorted({models[n]['domain'] for n in names}), confidence='INFERRED_NAME_MATCH',
                limitation='Field names/types are not present in the current bytecode export; name overlap is a candidate, not proof of equivalent models.'))
    leakage = []
    domain_concepts = {re.sub(r'[^a-z0-9]', '', d['name'].casefold()): d for d in domains}
    for name, model in sorted(models.items()):
        for concept, target in domain_concepts.items():
            if concept and target['id'] != model['domain_id'] and model['concept'] == concept:
                leakage.append(dict(kind='DOMAIN_LEAKAGE', class_name=name, current_domain=model['domain'],
                    likely_concept_domain=target['name'], confidence='INFERRED_NAME_MATCH',
                    limitation='Package/class naming is a heuristic; confirm ownership with maintainers.'))
    repositories = defaultdict(set)
    entities = {name for name, cls in classes.items() if any(a.rsplit('.',1)[-1] in {'Entity','Table'} for a in cls.get('annotations',[]))}
    for name, cls in classes.items():
        if membership.get(name) and (name.rsplit('.',1)[-1].endswith('Repository') or any(a.rsplit('.',1)[-1]=='Repository' for a in cls.get('annotations',[]))):
            repositories[name].add(membership[name])
    repo_consumers = defaultdict(set)
    for edge in edges:
        repo = edge.get('target')
        if repo in repositories and membership.get(edge.get('source')):
            repo_consumers[repo].add(membership[edge['source']])
    shared_repositories = [dict(repository=repo, domains=sorted({domain_by_id[d]['name'] for d in owners}),
        state='CONFIRMED_SHARED_REFERENCE', ownership='UNKNOWN') for repo, owners in sorted(repo_consumers.items()) if len(owners)>1]
    relationships = []
    for edge in edges:
        source, target = edge.get('source'), edge.get('target')
        if source in entities and target in entities and edge.get('dependency_type') in {'FIELD_TYPE','TYPE_REFERENCE'}:
            relationships.append(dict(source=source,target=target,source_domain=domain_by_id[membership[source]]['name'],
                target_domain=domain_by_id[membership[target]]['name'],cross_domain=membership[source]!=membership[target],
                state='INFERRED_FIELD_TYPE',evidence_id=edge.get('id')))
    transactions=[]
    for name, cls in classes.items():
        for method in cls.get('methods', []):
            annotations={a.rsplit('.',1)[-1] for a in method.get('annotations',[])}
            if 'Transactional' in annotations and membership.get(name):
                crosses=any(edge.get('source')==name and membership.get(edge.get('target')) not in (None,membership[name]) for edge in edges)
                transactions.append(dict(class_name=name,domain=domain_by_id[membership[name]]['name'],signature=method.get('signature'),
                    annotation='Transactional',cross_domain_dependency_from_class=crosses,
                    state='INFERRED_CROSS_DOMAIN_POTENTIAL' if crosses else 'ANNOTATION_CONFIRMED',
                    limitation='Class-level dependencies cannot prove that the annotated method makes the cross-domain call.'))
    domain_entities=defaultdict(list)
    for name in sorted(entities):
        if membership.get(name): domain_entities[membership[name]].append(name)
    domain_leakage=defaultdict(list); duplicate_models_by_domain=defaultdict(list)
    for item in leakage: domain_leakage[item['current_domain']].append(item)
    for item in duplicated:
        for did in {models[name]['domain_id'] for name in item['classes']}: duplicate_models_by_domain[did].append(item)
    per_domain={d['id']:dict(entities=domain_entities[d['id']],repositories=sorted(repo for repo,owners in repo_consumers.items() if d['id'] in owners),
        leakage_candidates=domain_leakage[d['name']],duplicated_model_candidates=duplicate_models_by_domain[d['id']],
        ownership='UNCONFIRMED',ownership_reason='Bytecode references and persistence annotations identify candidates, not business ownership or database write authority.') for d in domains}
    return dict(models=sorted(models.values(),key=lambda x:x['class_name']),duplicated_models=duplicated,
        leakage=leakage,shared_repositories=shared_repositories,entity_relationships=relationships,
        transactional_methods=transactions,per_domain=per_domain,
        limitations=['JPA annotation names are visible, but annotation arguments such as @Table names and mappedBy are not exported.',
            'Field names and field annotation details are not exported; duplicate-model detection uses naming conventions only.',
            'SQL/JPQL text is not retained, and runtime SQL parameters are discarded.',
            'Database-call observations identify resources/operations where available, not table-level ownership.'])


def entry_point_inventory(domains, classes, membership):
    """Inventory method annotations; route values are unknown in this exporter."""
    names={d['id']:d['name'] for d in domains}
    rows=[]
    for class_name, cls in sorted(classes.items()):
        did=membership.get(class_name)
        if not did:continue
        for method in cls.get('methods',[]):
            if not is_method_entry_point(method.get('annotations',[])):continue
            annotations=sorted({a.rsplit('.',1)[-1] for a in method.get('annotations',[])})
            if set(annotations)&{'Scheduled'}:kind='SCHEDULED_JOB'
            elif set(annotations)&{'KafkaListener','JmsListener','RabbitListener'}:kind='MESSAGE_LISTENER'
            elif set(annotations)&{'GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS'}:kind='JAX_RS_ENDPOINT'
            else:kind='REST_ENDPOINT'
            rows.append(dict(domain_id=did,domain=names[did],kind=kind,http_method='UNKNOWN',path='UNKNOWN',
                handler_class=class_name,handler_signature=method.get('signature'),annotations=annotations,
                route_metadata_state='ANNOTATION_ONLY',observation_state='UNKNOWN',
                limitation='Annotation values and composed/inherited route metadata are not included in the current scanner export.'))
    by_domain={d['id']:[] for d in domains}
    for row in rows:by_domain[row['domain_id']].append(row)
    return dict(items=rows,by_domain=by_domain,
        limitation='Static entry-point annotations are listed. HTTP paths, annotation values, inherited mappings and runtime status require richer scanner or selected-session method evidence.')
