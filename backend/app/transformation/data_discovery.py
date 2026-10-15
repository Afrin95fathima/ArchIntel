"""Bounded source-only discovery of relational schemas and data access paths.

All output is evidence-linked. Candidate ownership and schema reconstruction are
proposals and are never promoted to customer-confirmed facts here.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from app.evidence.builder import digest

RULE_VERSION = 'data-discovery-1'
MAX_FILES = 5000
MAX_FILE_BYTES = 2_000_000
SQL_TYPES = re.compile(r'\b(bigint|int8|integer|int4|int2|int\b|smallint|serial|bigserial|varchar(?:\s*\([^)]*\))?|character varying(?:\s*\([^)]*\))?|char(?:acter)?(?:\s*\([^)]*\))?|text|boolean|bool|numeric(?:\s*\([^)]*\))?|decimal(?:\s*\([^)]*\))?|real|double precision|float[48]?|date|timestamp(?:\s+with(?:out)?\s+time\s+zone)?|time(?:\s+with(?:out)?\s+time\s+zone)?|uuid|jsonb?|bytea|blob)\b', re.I)


def _type(value: str | None) -> str:
    if not value:
        return 'UNKNOWN'
    value = value.strip().lower()
    if value in {'bigint', 'int8', 'bigserial'}: return 'INT64'
    if value in {'integer', 'int4', 'int', 'serial', 'float4'}: return 'INT32' if value!='float4' else 'FLOAT'
    if value in {'smallint','int2'}: return 'INT16'
    if value.startswith(('varchar', 'character varying', 'char', 'character', 'text')): return 'STRING'
    if value in {'boolean', 'bool'}: return 'BOOLEAN'
    if value.startswith(('numeric', 'decimal')): return 'DECIMAL'
    if value in {'real', 'float', 'float8', 'double precision'} or value.startswith('float'): return 'FLOAT'
    if value == 'date': return 'DATE'
    if value.startswith('timestamp'): return 'TIMESTAMP'
    if value.startswith('time'): return 'TIME'
    if value == 'uuid': return 'UUID'
    if value in {'json', 'jsonb'}: return 'JSON'
    if value in {'bytea', 'blob'}: return 'BINARY'
    return 'UNKNOWN'


def _sql_tables(sql: str, path: str, sha: str, package: str | None = None):
    entities, access = [], []
    # CREATE TABLE definitions, including multiline column/constraint bodies.
    for match in re.finditer(r'(?is)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([`"\w.$]+)\s*\((.*?)\)\s*;', sql):
        name = match.group(1).replace('"', '').replace('`', '').split('.')[-1]
        body = match.group(2)
        columns, primary, foreign = [], [], []
        for item in re.split(r',\s*(?![^()]*\))', body):
            pk = re.search(r'(?is)primary\s+key\s*\(([^)]+)\)', item)
            if pk:
                primary.extend(x.strip(' `"') for x in pk.group(1).split(',')); continue
            fk = re.search(r'(?is)foreign\s+key\s*\(([^)]+)\)\s+references\s+([`"\w.$]+)\s*\(([^)]+)\)', item)
            if fk:
                foreign.append(dict(columns=[x.strip(' `"') for x in fk.group(1).split(',')],
                    target_table=fk.group(2).replace('"','').replace('`','').split('.')[-1],
                    target_columns=[x.strip(' `"') for x in fk.group(3).split(',')], evidence=None)); continue
            col = re.match(r'\s*[`"]?([A-Za-z_][\w$]*)[`"]?\s+(.+)', item, re.S)
            if not col or col.group(1).lower() in {'constraint', 'unique', 'check', 'primary', 'foreign'}: continue
            rest = col.group(2).strip()
            typ = SQL_TYPES.search(rest)
            inline_pk = bool(re.search(r'(?i)\bprimary\s+key\b', rest))
            if inline_pk: primary.append(col.group(1))
            inline_fk = re.search(r'(?i)\breferences\s+([`"\w.$]+)\s*\(([^)]+)\)', rest)
            if inline_fk:
                foreign.append(dict(columns=[col.group(1)], target_table=inline_fk.group(1).replace('"','').replace('`','').split('.')[-1], target_columns=[x.strip(' `"') for x in inline_fk.group(2).split(',')], evidence=None))
            columns.append(dict(name=col.group(1), data_type=_type(typ.group(0) if typ else None), nullable=not bool(re.search(r'(?i)\bnot\s+null\b', rest)) and not inline_pk, primary_key=inline_pk))
        if columns:
            for fk in foreign: fk['evidence'] = dict(path=path, sha256=sha, line=sql.count('\n', 0, match.start()) + 1, parser=RULE_VERSION)
            entities.append(dict(name=name, columns=columns, primary_key=sorted(set(primary)), foreign_keys=foreign,
                evidence=dict(path=path, sha256=sha, line=sql.count('\n', 0, match.start()) + 1, parser=RULE_VERSION), package=package))
    # Query and DML access paths. This deliberately reports table-level candidates only.
    for line_no, line in enumerate(sql.splitlines(), 1):
        for match in re.finditer(r'(?i)\b(from|join|into|update|delete\s+from)\s+([`"\w.$]+)', line):
            verb, raw = match.groups(); table = raw.replace('"','').replace('`','').split('.')[-1]
            operation = 'WRITE' if verb.lower() in {'into','update','delete from'} else 'READ'
            access.append(dict(table=table, operation=operation, source=dict(path=path, sha256=sha, line=line_no, parser=RULE_VERSION), package=package))
    for match in re.finditer(r'(?is)\balter\s+table\s+([`"\w.$]+)\s+add\s+(?:constraint\s+[`"\w$]+\s+)?foreign\s+key\s*\(([^)]+)\)\s+references\s+([`"\w.$]+)\s*\(([^)]+)\)',sql):
        source=match.group(1).replace('"','').replace('`','').split('.')[-1]
        target=match.group(3).replace('"','').replace('`','').split('.')[-1]
        fk=dict(columns=[x.strip(' `"') for x in match.group(2).split(',')],target_table=target,
            target_columns=[x.strip(' `"') for x in match.group(4).split(',')],
            evidence=dict(path=path,sha256=sha,line=sql.count('\n',0,match.start())+1,parser=RULE_VERSION))
        found=next((e for e in entities if e['name'].casefold()==source.casefold()),None)
        if found: found['foreign_keys'].append(fk)
    return entities, access


def _liquibase(text: str, path: str, sha: str):
    entities, access, errors = [], [], []
    try: root = ET.fromstring(text)
    except ET.ParseError:
        return entities, access, ['LIQUIBASE_XML_PARSE_FAILED']
    for element in root.iter():
        tag = element.tag.rsplit('}', 1)[-1]
        if tag == 'createTable':
            columns=[]
            for child in element:
                if child.tag.rsplit('}',1)[-1] != 'column': continue
                constraints=next((x for x in child if x.tag.rsplit('}',1)[-1]=='constraints'),None)
                columns.append(dict(name=child.attrib.get('name',''), data_type=_type(child.attrib.get('type')),
                    nullable=(constraints.attrib.get('nullable','true').lower()!='false') if constraints is not None else True,
                    primary_key=(constraints.attrib.get('primaryKey','false').lower()=='true') if constraints is not None else False))
            if columns:
                entities.append(dict(name=element.attrib.get('tableName',''), columns=columns,
                    primary_key=sorted(c['name'] for c in columns if c['primary_key']), foreign_keys=[],
                    evidence=dict(path=path,sha256=sha,line=None,parser=RULE_VERSION),package=None))
        elif tag == 'addForeignKeyConstraint':
            source=element.attrib.get('baseTableName'); target=element.attrib.get('referencedTableName')
            fk=dict(columns=[x.strip() for x in element.attrib.get('baseColumnNames','').split(',') if x.strip()],
                target_table=target,target_columns=[x.strip() for x in element.attrib.get('referencedColumnNames','').split(',') if x.strip()],
                evidence=dict(path=path,sha256=sha,line=None,parser=RULE_VERSION))
            owner=next((e for e in entities if e['name']==source),None)
            if owner: owner['foreign_keys'].append(fk)
    return entities, access, errors


def _java_entities(text: str, path: str, sha: str):
    entities, access = [], []
    package_match=re.search(r'(?m)^\s*package\s+([\w.]+)\s*;',text)
    package=package_match.group(1) if package_match else None
    for match in re.finditer(r'(?s)((?:@[\w.]+(?:\([^)]*\))?\s*)+)\s*(?:public\s+)?class\s+(\w+)\b',text):
        annotations,name=match.groups()
        if not re.search(r'@(?:jakarta\.persistence\.)?Entity\b',annotations): continue
        table_match=re.search(r'@(?:jakarta\.persistence\.)?Table\s*\(\s*name\s*=\s*["\']([^"\']+)',annotations)
        table=table_match.group(1) if table_match else re.sub(r'(?<!^)(?=[A-Z])','_',name).lower()
        body_start=match.end(); depth=1; i=body_start
        while i<len(text) and depth:
            depth += (text[i]=='{')-(text[i]=='}'); i+=1
        body=text[body_start:max(body_start,i-1)]
        columns=[];primary=[];foreign=[]
        field_rx=re.compile(r'(?s)((?:@[\w.]+(?:\([^)]*\))?\s*)+)\s*(?:private|protected|public)\s+([\w.$<>?, ]+)\s+(\w+)\s*(?:=[^;]*)?;')
        for fm in field_rx.finditer(body):
            ann,java_type,field=fm.groups()
            if '@Transient' in ann: continue
            cm=re.search(r'@(?:jakarta\.persistence\.)?Column\s*\(\s*name\s*=\s*["\']([^"\']+)',ann)
            col=cm.group(1) if cm else re.sub(r'(?<!^)(?=[A-Z])','_',field).lower()
            normalized={'String':'STRING','Long':'INT64','Integer':'INT32','Short':'INT16','Boolean':'BOOLEAN','boolean':'BOOLEAN','int':'INT32','long':'INT64','BigDecimal':'DECIMAL','LocalDate':'DATE','Date':'DATE','Instant':'TIMESTAMP','LocalDateTime':'TIMESTAMP','UUID':'UUID','byte[]':'BINARY'}.get(java_type.strip().split('<')[0], 'UNKNOWN')
            is_id=bool(re.search(r'@(?:jakarta\.persistence\.)?Id\b',ann))
            nullable=not bool(re.search(r'nullable\s*=\s*false',ann))
            columns.append(dict(name=col,data_type=normalized,nullable=nullable,primary_key=is_id))
            if is_id: primary.append(col)
            jcol=re.search(r'@(?:jakarta\.persistence\.)?JoinColumn\s*\(\s*name\s*=\s*["\']([^"\']+)',ann)
            if jcol:
                target_type=java_type.strip().split('<')[0].rsplit('.',1)[-1]
                target_name=re.sub(r'(?<!^)(?=[A-Z])','_',target_type).lower()
                foreign.append(dict(columns=[jcol.group(1)],target_table=target_name,target_columns=['id'],evidence=dict(path=path,sha256=sha,line=text.count('\n',0,match.start()+fm.start())+1,parser=RULE_VERSION)))
        if columns:
            entities.append(dict(name=table,columns=columns,primary_key=primary,foreign_keys=foreign,
                evidence=dict(path=path,sha256=sha,line=text.count('\n',0,match.start())+1,parser=RULE_VERSION),package=package,entity_class=name))
    for line_no,line in enumerate(text.splitlines(),1):
        for match in re.finditer(r'(?i)\b(from|join|into|update|delete\s+from)\s+["`]?([A-Za-z_][\w$]*)',line):
            verb,table=match.groups();operation='WRITE' if verb.lower() in {'into','update','delete from'} else 'READ'
            access.append(dict(table=table,operation=operation,source=dict(path=path,sha256=sha,line=line_no,parser=RULE_VERSION),package=package))
    # Repository interfaces and explicit query annotations are visible but mapped only where a table appears.
    for match in re.finditer(r'(?is)@Query\s*\(\s*["\'](.*?)["\']',text):
        query=match.group(1)
        qentities,qaccess=_sql_tables(query,path,sha,package)
        for item in qaccess: item['source']['line']=text.count('\n',0,match.start())+1; access.append(item)
    repo_match=re.search(r'(?is)(?:interface|class)\s+\w+\s+extends\s+[\w.]+Repository\s*<\s*([\w.$]+)',text)
    if repo_match:
        entity_class=repo_match.group(1).rsplit('.',1)[-1]
        table=re.sub(r'(?<!^)(?=[A-Z])','_',entity_class).lower()
        for line_no,line in enumerate(text.splitlines(),1):
            method=re.search(r'\b(save|saveAll|delete|deleteAll|deleteBy\w+|find|findAll|findBy\w+|existsBy\w+|countBy\w+)\s*\(',line)
            if method:
                operation='WRITE' if method.group(1).lower().startswith(('save','delete')) else 'READ'
                access.append(dict(table=table,operation=operation,source=dict(path=path,sha256=sha,line=line_no,parser=RULE_VERSION,access='SPRING_DATA_REPOSITORY_METHOD'),package=package))
    return entities,access


def discover(files: dict[str, dict], *, full_source_snapshot: bool, analysis: dict, runtime_database: list | None = None):
    """Inspect a bounded immutable source manifest and return grounded findings plus questions."""
    entities_by_name={}; access=[]; parser_coverage=[]; limitations=[]; seen=0
    for path,record in sorted(files.items()):
        if seen>=MAX_FILES:
            limitations.append('MAX_DISCOVERY_FILE_LIMIT_REACHED');break
        text=record['content']; sha=record['sha256']; seen+=1
        if len(text.encode('utf-8'))>MAX_FILE_BYTES:
            parser_coverage.append(dict(path=path,state='SKIPPED_SIZE_LIMIT',sha256=sha));continue
        lower=path.lower(); package_match=re.search(r'(?m)^\s*package\s+([\w.]+)\s*;',text); package=package_match.group(1) if package_match else None
        found=[]; paths=[]
        if lower.endswith('.sql') or re.search(r'(?i)\bcreate\s+table\b',text):
            found,paths=_sql_tables(text,path,sha,package)
        if lower.endswith('.xml') and ('liquibase' in lower or 'databaseChangeLog' in text):
            found,paths,errors=_liquibase(text,path,sha);limitations.extend(errors)
        elif lower.endswith('.xml') and re.search(r'(?i)\b(select|insert\s+into|update|delete\s+from)\b',text):
            found,paths=_sql_tables(text,path,sha,package)
        if lower.endswith('.java'):
            j_entities,j_access=_java_entities(text,path,sha);found.extend(j_entities);paths.extend(j_access)
        for entity in found:
            key=entity['name'].casefold(); existing=entities_by_name.get(key)
            if existing:
                existing['evidence'].append(entity['evidence'])
                if existing['columns']!=entity['columns']:
                    existing['conflicts'].append(dict(kind='SCHEMA_DEFINITION_CONFLICT',evidence=entity['evidence']))
                existing['foreign_keys'].extend(entity['foreign_keys'])
            else:
                entities_by_name[key]=dict(name=entity['name'],columns=entity['columns'],primary_key=entity['primary_key'],
                    foreign_keys=entity['foreign_keys'],evidence=[entity['evidence']],package=entity.get('package'),
                    entity_class=entity.get('entity_class'),conflicts=[])
        access.extend(paths)
        if found or paths:
            parser_coverage.append(dict(path=path,state='PARSED',sha256=sha,entity_count=len(found),access_path_count=len(paths)))
        elif lower.endswith(('.sql','.java','.xml','.yaml','.yml')):
            parser_coverage.append(dict(path=path,state='NO_SUPPORTED_DATA_PATTERN_FOUND',sha256=sha))
    # Match source packages to existing static architecture domains, conservatively.
    classes=analysis.get('classes',[]); package_domains=defaultdict(set)
    for item in classes:
        package_domains[item.get('package_name','')].add(item.get('domain_id'))
    def owner_candidates(package):
        if not package: return []
        found=set()
        for p,domains in package_domains.items():
            if p and (package==p or package.startswith(p+'.') or p.startswith(package+'.')): found.update(x for x in domains if x)
        return sorted(found)
    access_by_table=defaultdict(list)
    for row in access:
        row['candidate_owners']=owner_candidates(row.get('package'))
        access_by_table[row['table'].casefold()].append(row)
    ownership=[]; unresolved=[]; all_entities=sorted(entities_by_name.values(),key=lambda x:x['name'].casefold())
    for entity in all_entities:
        entity_access=access_by_table.get(entity['name'].casefold(),[])
        owners=sorted({owner for row in entity_access for owner in row.get('candidate_owners',[])})
        if not owners and entity.get('package'): owners=owner_candidates(entity['package'])
        write_owners=sorted({owner for row in entity_access if row['operation']=='WRITE' for owner in row.get('candidate_owners',[])})
        conflict=bool(entity['conflicts'] or len(write_owners)>1)
        shared_access=len(owners)>1
        claim_state='INFERRED' if owners and not conflict and not shared_access else 'UNRESOLVED'
        confidence='MEDIUM' if owners and not conflict and not shared_access and entity_access else 'LOW' if owners else 'UNKNOWN'
        ownership.append(dict(resource=entity['name'],candidate_domain_ids=owners,write_domain_ids=write_owners,
            state=claim_state,confidence=confidence,reason='Matched source packages and static read/write references; not customer-confirmed.' if owners else 'No reliable package/domain ownership match was found.',
            evidence=entity['evidence']+[row['source'] for row in entity_access],shared_access=shared_access,conflicting_writes=conflict))
        if conflict: unresolved.append(dict(kind='CONFLICTING_OR_SHARED_OWNERSHIP',resource=entity['name'],evidence=entity['evidence']+[row['source'] for row in entity_access]))
        elif shared_access: unresolved.append(dict(kind='SHARED_DATA_ACCESS_REVIEW_REQUIRED',resource=entity['name'],evidence=entity['evidence']+[row['source'] for row in entity_access]))
        if not entity['primary_key']: unresolved.append(dict(kind='PRIMARY_KEY_NOT_DISCOVERED',resource=entity['name'],evidence=entity['evidence']))
        for column in entity['columns']:
            if column['data_type']=='UNKNOWN': unresolved.append(dict(kind='COLUMN_TYPE_UNKNOWN',resource=entity['name']+'.'+column['name'],evidence=entity['evidence']))
        if entity['conflicts']: unresolved.extend(dict(kind=c['kind'],resource=entity['name'],evidence=c['evidence']) for c in entity['conflicts'])
    if not all_entities:
        unresolved.append(dict(kind='NO_STRUCTURED_SCHEMA_DISCOVERED',resource=None,evidence=[]))
    if not full_source_snapshot:
        limitations.append('SOURCE_SNAPSHOT_IS_PARTIAL; unseen files may contain schemas or access paths.')
    if not any(x['state']=='PARSED' for x in parser_coverage):
        questions=[dict(question='Which source migration directory or schema-only DDL file should be included in the authorized repository snapshot?',reason='No supported schema declaration was found in the captured files.',minimum_input='A repository path to migration files or a schema-only export; a target schema is not required.')]
    else: questions=[]
    if any(x['kind']=='CONFLICTING_OR_SHARED_OWNERSHIP' for x in unresolved):
        for row in unresolved:
            if row['kind']=='CONFLICTING_OR_SHARED_OWNERSHIP':
                questions.append(dict(question=f"Which domain owns writes to {row['resource']}?",reason='Static access paths show shared or conflicting writers.',minimum_input='Confirm the owner for this resource or provide the specific write policy.'))
    for row in unresolved:
        if row['kind']=='SHARED_DATA_ACCESS_REVIEW_REQUIRED':
            questions.append(dict(question=f"Should {row['resource']} remain shared, or should a domain own it?",reason='Multiple architecture domains access this resource; static evidence does not establish its business owner.',minimum_input='Confirm SHARED or name the owning domain and explain the decision.'))
    # Runtime resource names can corroborate a candidate only; they do not prove table identity.
    runtime_database=runtime_database or []
    class_package={x.get('id'):x.get('package_name') for x in classes}
    for row in runtime_database:
        raw=row.get('resource')
        if not raw: continue
        table=str(raw).split('.')[-1].strip(' `"')
        operation=str(row.get('operation') or '').upper()
        access.append(dict(table=table,operation='WRITE' if any(x in operation for x in ('INSERT','UPDATE','DELETE','WRITE')) else 'READ',
            source=dict(kind='RUNTIME_DATABASE_OBSERVATION',version_analysis_id=row.get('analysis_id'),references=row.get('evidence',[])),
            package=class_package.get(row.get('caller'))))
    document=dict(rule_version=RULE_VERSION,source_state='COMPLETE' if full_source_snapshot else 'PARTIAL',
        entities=all_entities,access_paths=sorted(access,key=lambda x:(x['table'].casefold(),x['source'].get('path',''),x['source'].get('line') or 0)),
        ownership_map=ownership,parser_coverage=parser_coverage,unresolved=unresolved,questions=questions,
        runtime_database_context=[dict(row,role='CONTEXT_ONLY_UNVERIFIED_TABLE_IDENTITY') for row in runtime_database],
        limitations=sorted(set(limitations)),
        provenance=dict(source_manifest_sha256=digest({p:r['sha256'] for p,r in sorted(files.items())}),files_inspected=seen,
            analysis_sha256=digest(analysis),parser_version=RULE_VERSION))
    document['fingerprint']=digest(document)
    return document


def propose_target(discovery: dict, domains: list[dict], target_engine: str='LOGICAL'):
    """Generate a reviewable, non-authoritative target schema and mapping proposal."""
    domain_names={d['id']:d.get('name',d['id']) for d in domains}
    tables=[];mappings=[];unresolved=list(discovery['unresolved'])
    for entity in discovery['entities']:
        claim=next((x for x in discovery['ownership_map'] if x['resource'].casefold()==entity['name'].casefold()),None)
        owners=claim['candidate_domain_ids'] if claim else []
        target_service=domain_names[owners[0]] if len(owners)==1 and not claim['conflicting_writes'] else 'UNASSIGNED_REVIEW_REQUIRED'
        target_name=re.sub(r'[^A-Za-z0-9_]+','_',entity['name']).strip('_').lower() or 'unnamed_resource'
        table=dict(name=target_name,service=target_service,state='PROPOSED',source_resource=entity['name'],
            columns=[dict(name=c['name'],type=c['data_type'],nullable=c['nullable'],primary_key=c['primary_key'],state='PROPOSED') for c in entity['columns']],
            primary_key=entity['primary_key'],foreign_keys=entity['foreign_keys'],evidence=entity['evidence'])
        tables.append(table)
        for col in entity['columns']:
            mappings.append(dict(source_table=entity['name'],source_column=col['name'],target_table=target_name,target_column=col['name'],
                source_type=col['data_type'],target_type=col['data_type'] if col['data_type']!='UNKNOWN' else 'REVIEW_REQUIRED',
                conversion='IDENTITY_PROPOSED' if col['data_type']!='UNKNOWN' else 'UNRESOLVED',key=col['primary_key'],
                state='INFERRED',confidence='MEDIUM' if col['data_type']!='UNKNOWN' else 'UNKNOWN',evidence=entity['evidence']))
        if target_service=='UNASSIGNED_REVIEW_REQUIRED':
            unresolved.append(dict(kind='TARGET_SERVICE_OWNERSHIP_UNRESOLVED',resource=entity['name'],evidence=entity['evidence']))
    if not tables:
        for pathrow in discovery['access_paths']:
            name=pathrow['table']; target_name=re.sub(r'[^A-Za-z0-9_]+','_',name).strip('_').lower() or 'unnamed_resource'
            if not any(t['source_resource'].casefold()==name.casefold() for t in tables):
                tables.append(dict(name=target_name,service='UNASSIGNED_REVIEW_REQUIRED',state='PROPOSED_INCOMPLETE',source_resource=name,columns=[],primary_key=[],foreign_keys=[],evidence=[pathrow['source']]))
        if not tables: tables.append(dict(name='TARGET_SCHEMA_TO_BE_DESIGNED',service='UNASSIGNED_REVIEW_REQUIRED',state='PROPOSED_EMPTY',source_resource=None,columns=[],primary_key=[],foreign_keys=[],evidence=[]))
    target_names={x['source_resource'].casefold():x['name'] for x in tables if x.get('source_resource')}
    target_schema=[]
    for item in tables:
        fks=[]
        for fk in item.get('foreign_keys',[]):
            target_source=target_names.get((fk.get('target_table') or '').casefold())
            if target_source:
                fks.append(dict(columns=fk['columns'],target_table=target_source,target_columns=fk['target_columns']))
            else:
                unresolved.append(dict(kind='REFERENCED_RESOURCE_NOT_DISCOVERED',resource=fk.get('target_table'),evidence=fk.get('evidence') or item['evidence']))
        target_schema.append(dict(name=item['name'],state=item['state'],columns=[dict(name=c['name'],data_type=('REVIEW_REQUIRED' if c['type']=='UNKNOWN' else c['type']),nullable=c['nullable']) for c in item['columns']],
            primary_key=item['primary_key'],foreign_keys=fks,source_resource=item['source_resource']))
    no_target='No pre-existing target schema is required; this target is generated as a reviewable proposal.'
    plan=dict(target_engine=target_engine,target_schema_state='PROPOSED',tables=tables,target_schema=target_schema,
        source_schema=discovery['entities'],mappings=mappings,
        migration_steps=[dict(order=1,action='CREATE_TARGET_SCHEMA',state='PROPOSED',explanation='Create target objects from the reviewed proposal.'),
            dict(order=2,action='BACKFILL_DATA',state='PROPOSED',explanation='Copy data using reviewed mappings and explicit conflict handling.'),
            dict(order=3,action='VALIDATE_RELATIONSHIPS_AND_INVARIANTS',state='REQUIRED',explanation='Reconcile keys, relationships, conversions, and customer-defined invariants.'),
            dict(order=4,action='APPLICATION_BEHAVIOR_CHECKS',state='REQUIRED',explanation='Run approved behavior checks against the isolated candidate database.'),
            dict(order=5,action='CUTOVER_PROPOSAL_ONLY',state='NOT_EXECUTABLE',explanation='Production cutover requires a separate future authorization.')],
        alternatives=[dict(id='PRESERVE_CURRENT_RESOURCE_BOUNDARIES',description='Retain each discovered source resource and propose an additive target schema.',tradeoff='Lower semantic change; preserves current coupling.'),
            dict(id='PARTITION_BY_CANDIDATE_SERVICE',description='Group target resources by inferred service ownership where evidence is unambiguous.',tradeoff='Potentially stronger boundaries; ambiguous/shared writers remain unresolved.')],
        unresolved=sorted({(x['kind'],x.get('resource')):x for x in unresolved}.values(),key=lambda x:(x['kind'],x.get('resource') or '')),
        rationale=no_target,discovery_fingerprint=discovery['fingerprint'],state='PROPOSED_REVIEW_REQUIRED',execution_eligible=False)
    plan['fingerprint']=digest(plan)
    return plan
