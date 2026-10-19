"""Pure snapshot-to-evidence adapter. No network, source code or model access."""
from collections import defaultdict
import hashlib
import json
from uuid import UUID,uuid5
from app.services.runtime.fusion import fuse
from app.services.runtime.instrumentation import ENTRY_POINTS

RULE_VERSION='evidence-foundation-1'

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def identity(version,key):return str(uuid5(UUID(version),key))


def build(version,static,runtime,manifest,observed_methods):
    nodes={};links={};evidence=[];facts=[];discovery=[]
    def node(key,kind,name,**properties):
        uid=identity(version,key)
        nodes[uid]=dict(id=uid,kind=kind,name=name,key=key,**properties)
        return uid
    def link(source,target,kind):
        uid=identity(version,'link:'+source+':'+kind+':'+target)
        links[uid]=dict(id=uid,source=source,target=target,kind=kind)
    def ev(key,kind,source,target,observation,refs=None,confidence=1.):
        uid=identity(version,'evidence:'+key)
        evidence.append(dict(id=uid,kind=kind,document=dict(source=source,target=target,observation=observation,confidence=confidence,
            collector=RULE_VERSION,timestamp=manifest['captured_at'],analysis_id=manifest['analysis_id'],session_ids=manifest['runtime_session_ids'] if kind in ('RUNTIME','DATABASE','COVERAGE') else [],references=refs or [])))
        nodes[uid]=dict(id=uid,key='evidence:'+key,kind='Evidence',name=kind+' observation',evidence_kind=kind)
        return uid
    root=node('version','ArchitectureVersion',manifest['analysis_id'])
    app=node('application','Application',manifest['application_id']);link(app,root,'HAS_VERSION')
    for sid in manifest['runtime_session_ids']:
        link(root,node('session:'+sid,'RuntimeSession',sid),'OBSERVED_IN')
    runtime_graph=runtime['runtime_graph']
    unified=fuse(static,runtime_graph)
    for d in static['domains']:
        link(root,node('domain:'+d['id'],'Domain',d['name'],domain_id=d['id']),'CONTAINS')
    for c in static['classes']:
        cid=node('entity:'+c['id'],'Repository' if any(a.rsplit('.',1)[-1]=='Repository' for a in c.get('annotations',[])) else 'Class',c['id'],static_id=c['id'])
        package=node('package:'+c['package_name'],'Package',c['package_name'])
        link(root,package,'CONTAINS');link(package,cid,'CONTAINS');link(identity(version,'domain:'+c['domain_id']),cid,'CONTAINS')
        proof=ev('class:'+c['id'],'STATIC',manifest['analysis_id'],c['id'],dict(annotations=c.get('annotations',[]),package=c['package_name']))
        link(proof,cid,'DESCRIBES')
        for m in c.get('methods',[]):
            if not m.get('name') or not m.get('signature') or m['name'].startswith('<'):continue
            annotations={a.rsplit('.',1)[-1] for a in m.get('annotations',[])}
            mid=node('method:'+c['id']+':'+m['signature'],'EntryPoint' if annotations & ENTRY_POINTS else 'Method',c['id']+'.'+m['signature'],annotations=sorted(annotations))
            link(cid,mid,'DECLARES');link(proof,mid,'DESCRIBES')
            if annotations & ENTRY_POINTS and (c['id'],m['signature']) not in observed_methods:
                discovery.append(dict(kind='SCHEDULED_JOB' if 'Scheduled' in annotations else 'MESSAGE_CONSUMER' if annotations & {'KafkaListener','JmsListener','RabbitListener'} else 'ENTRY_POINT',target=mid,priority=1,
                    gap_state='UNKNOWN' if manifest['method_observations_available'] is False else 'UNOBSERVED',
                    text='Exercise '+c['id']+'.'+m['name']+' and capture method identity evidence.',evidence_ids=[proof]))
    for index,external in enumerate(static.get('external_edges',[])):
        target=node('external:'+external['target'],'ExternalType',external['target'])
        eid=ev('external:'+str(index),'STATIC',external['source'],external['target'],external)
        link(eid,target,'DESCRIBES');link(identity(version,'entity:'+external['source']),target,'REFERENCES')
    for n in runtime_graph['nodes']:
        uid=identity(version,'entity:'+n['id'])
        if uid not in nodes:node('entity:'+n['id'],'RuntimeResource' if n.get('node_type')=='RESOURCE' else 'UnresolvedClass',n.get('name') or n['id'],mapping_state=n.get('mapping_state'))
    support=defaultdict(list)
    for e in static['edges']:
        support[(e['source'],e['target'])].append(ev('edge:'+e['id'],'STATIC',e['source'],e['target'],dict(dependency_type=e['dependency_type'],static_edge_id=e['id'])))
    for e in runtime_graph['edges']:
        support[(e['source'],e['target'])].append(ev('runtime:'+e['id'],'RUNTIME',e['source'],e['target'],dict(e),e.get('evidence',[])))
    for edge in unified['edges']:
        uid=identity(version,'fact:'+edge['source']+':'+edge['target'])
        doc=dict(source=edge['source'],target=edge['target'],relation='DEPENDS_ON',classification=edge['evidence_type'],
                 evidence_ids=sorted(support[(edge['source'],edge['target'])]),conflict_ids=[],
                 static_types=sorted(set(edge['static_types'])),call_count=edge['call_count'],
                 confidence='OBSERVED_SUPPORT' if edge['evidence_type']!='STATIC_ONLY' else 'STATIC_SUPPORT',
                 note='Static-only is not proof of unused code. Observed nesting is not a complete call graph.')
        facts.append(dict(id=uid,classification=edge['evidence_type'],document=doc))
        nodes[uid]=dict(id=uid,key='fact:'+uid,kind='ArchitectureFact',name=edge['source']+' -> '+edge['target'],classification=edge['evidence_type'])
        link(identity(version,'entity:'+edge['source']),uid,'SOURCE_OF');link(uid,identity(version,'entity:'+edge['target']),'TARGETS')
        for eid in doc['evidence_ids']:link(eid,uid,'SUPPORTS')
        if edge['evidence_type']=='STATIC_ONLY' and 'METHOD_CALL' in edge['static_types']:
            discovery.append(dict(kind='DEPENDENCY',target=uid,priority=2,gap_state='UNOBSERVED',text='Exercise the path '+edge['source']+' -> '+edge['target']+'.',evidence_ids=doc['evidence_ids']))
    for d in runtime['coverage']['domain_observations']:
        eid=ev('coverage:'+d['id'],'COVERAGE',manifest['analysis_id'],d['id'],d)
        link(eid,identity(version,'domain:'+d['id']),'DESCRIBES')
        if d['state']!='OBSERVED':discovery.append(dict(kind='DOMAIN',target=identity(version,'domain:'+d['id']),priority=2,gap_state=d['state'],text=f"{d['name']}: {d['observed']} of {d['total']} classes observed; not yet observed: {', '.join(c.rsplit('.',1)[-1] for c in d['unobserved_classes'][:5])}{'…' if len(d['unobserved_classes'])>5 else ''}. See Dynamic analysis → Next tests.",evidence_ids=[eid]))
    for index,flow in enumerate(runtime.get('flows',[])):
        fid=node('flow:'+str(index),'RuntimeFlow',flow.get('entry_point','Unknown entry'),observation=flow)
        eid=ev('flow:'+str(index),'RUNTIME',manifest['analysis_id'],fid,flow,flow.get('evidence',[]));link(eid,fid,'DESCRIBES');link(root,fid,'CONTAINS')
    for index,db in enumerate(runtime.get('database',[])):
        resource=node('database:'+str(index),'DataResource',db.get('resource') or 'Unknown database resource',observation=db,ownership='UNKNOWN')
        eid=ev('database:'+str(index),'DATABASE',db.get('caller'),resource,db,db.get('evidence',[]))
        link(eid,resource,'DESCRIBES');link(root,eid,'HAS_EVIDENCE')
        if db.get('caller'):link(identity(version,'entity:'+db['caller']),resource,'OBSERVED_DATABASE_CALL')
    for cycle in static.get('cycles',[]):
        cid=node('cycle:'+cycle['id'],'Cycle',cycle['level']+' cycle',observation=cycle)
        eid=ev('cycle:'+cycle['id'],'DERIVED',manifest['analysis_id'],cid,cycle);link(eid,cid,'SUPPORTS');link(root,cid,'CONTAINS')
    metric=ev('metrics','METRIC',manifest['analysis_id'],manifest['analysis_id'],static.get('metrics',{}));link(root,metric,'HAS_EVIDENCE')
    for issue in static.get('issues',[]):
        iid=node('finding:'+issue['id'],'Finding',issue.get('title') or issue['id'],observation=issue)
        eid=ev('finding:'+issue['id'],'DERIVED',manifest['analysis_id'],iid,issue);link(eid,iid,'SUPPORTS');link(root,iid,'CONTAINS')
        if issue.get('severity') in ('CRITICAL','HIGH'):
            discovery.append(dict(kind='HIGH_RISK_PATH',target=iid,priority=1,gap_state='REVIEW_REQUIRED',text='Review and exercise paths implicated by '+(issue.get('title') or issue['id'])+'.',evidence_ids=[eid]))
    if manifest.get('domain_review'):
        eid=ev('domain-review','USER_CONFIRMED',manifest['domain_review']['actor'],manifest['analysis_id'],manifest['domain_review'])
        link(root,eid,'HAS_EVIDENCE')
    for item in discovery:
        item['id']=identity(version,'discovery:'+item['kind']+':'+item['target'])
        item['note']='Suggested investigation, not a proven business workflow. Marking exercised does not change observation coverage.'
    # Edges from malformed old snapshots cannot manufacture missing entities.
    links={k:v for k,v in links.items() if v['source'] in nodes and v['target'] in nodes}
    graph=dict(nodes=sorted(nodes.values(),key=lambda n:n['id']),edges=sorted(links.values(),key=lambda e:e['id']))
    return dict(graph=graph,collector_configuration=static.get('configuration',{}),coverage=runtime['coverage'],quality=runtime.get('quality',{}),domains=static['domains'],
                modernization_baseline=static.get('modernization_baseline',{}),domain_dependency_matrix=static.get('domain_dependency_matrix',{}),
                data_ownership=static.get('data_ownership',{}),entry_points=static.get('entry_points',{}),tech_inventory=static.get('tech_inventory',{}),
                observed_methods=[list(x) for x in sorted(observed_methods)],
                unknowns=['Data ownership is not established by database calls.','Tests and behavioral contracts are not available.','No modernization execution state is inferred.'],
                facts_count=len(facts),evidence_count=len(evidence)),evidence,facts,sorted(discovery,key=lambda d:(d['priority'],d['kind'],d['target']))
