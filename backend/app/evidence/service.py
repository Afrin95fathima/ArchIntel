"""Version creation and canonical provenance APIs, independent of graph availability."""
import copy
from threading import RLock
from uuid import uuid5,NAMESPACE_URL
from fastapi import HTTPException
from sqlalchemy import select,func,insert
from app.api import get
from app.models import AnalysisRun,Application,Artifact,now
from app.runtime.models import RuntimeSession,RuntimeEvent
from app.services.runtime import session_service
from app.services.runtime.graph_builder import build as runtime_graph
from app.services.runtime.coverage import calculate
from app.services.runtime.mapping import map_method
from .models import ArchitectureVersion,Evidence,ArchitectureFact,Projection,DiscoveryItem
from .builder import build,digest,RULE_VERSION

LOCK=RLock()

def version(db,vid):return get(db,ArchitectureVersion,vid)

def prepare(db,app_id,body,config,actor):
    get(db,Application,app_id);run=get(db,AnalysisRun,body.analysis_id)
    if run.application_id!=app_id or run.status!='COMPLETED' or not run.result:raise HTTPException(409,'Choose a completed analysis from this application.')
    if len(run.result['classes'])>50000 or len(run.result['edges'])+len(run.result.get('external_edges',[]))>80000:raise HTTPException(413,'Version projection currently supports up to 50,000 classes and 80,000 static edges.')
    static=copy.deepcopy(run.result)
    sessions=[get(db,RuntimeSession,sid) for sid in sorted(set(body.runtime_session_ids))]
    if any(s.application_id!=app_id or s.analysis_id!=run.id or s.status!='COMPLETED' for s in sessions):raise HTTPException(409,'Select completed runtime sessions from this exact static baseline.')
    if body.parent_id and version(db,body.parent_id).application_id!=app_id:raise HTTPException(409,'Parent version belongs to another application.')
    review=None
    if body.domain_edits is not None:
        domains=[d.model_dump() for d in body.domain_edits]
        members=[c for d in domains for c in d['classes']]
        if not body.review_reason.strip() or len({d['id'] for d in domains})!=len(domains) or {d['id'] for d in domains}!={d['id'] for d in static['domains']} or len(members)!=len(set(members)) or set(members)!={c['id'] for c in static['classes']} or any(not d['classes'] or not d['name'].strip() for d in domains):
            raise HTTPException(422,'Reviewed domains must retain existing domain IDs, assign every class exactly once, remain nonempty and include a review reason.')
        domains=sorted([dict(d,classes=sorted(d['classes'])) for d in domains],key=lambda d:d['id'])
        static['domains']=domains
        assignment={c:d['id'] for d in domains for c in d['classes']}
        for c in static['classes']:c['domain_id']=assignment[c['id']]
        review=dict(actor=actor,reason=body.review_reason,domains=domains)
    with session_service.LOCK:
        runtime=session_service.result(db,sessions,config) if sessions else dict(runtime_graph=runtime_graph([],static),flows=[],database=[],quality={})
        events=list(db.scalars(select(RuntimeEvent.data).where(RuntimeEvent.session_id.in_([s.id for s in sessions])))) if sessions else []
    classes={c['id']:c for c in static['classes']};observed=set()
    for event in events:
        match=map_method(event,classes)
        if match['signature']:observed.add((match['static_class'],match['signature']))
    runtime=copy.deepcopy(runtime)
    # Recalculate domain observation for reviewed memberships without reusing old scores.
    for n in runtime['runtime_graph']['nodes']:
        if n.get('static_id') in classes:n['domain_id']=classes[n['static_id']]['domain_id']
    for resource in runtime.get('database',[]):
        if resource.get('caller') in classes:resource['domain_id']=classes[resource['caller']]['domain_id']
    runtime['coverage']=calculate(static,runtime['runtime_graph'],events)
    methods_available=all(not s.settings.get('events_purged') for s in sessions)
    if not methods_available:
        for key in ('methods','entry_points'):
            runtime['coverage'][key]=dict(observed=None,total=None,percentage=None,status='UNAVAILABLE',reason='Raw method evidence expired; no signature-level observations reconstructed from aggregate counts.')
    artifact=get(db,Artifact,run.artifact_id)
    manifest=dict(application_id=app_id,analysis_id=run.id,artifact_sha256=artifact.sha256,
                  static_sha256=digest(run.result),runtime_session_ids=[s.id for s in sessions],runtime_sha256={s.id:digest(s.result) for s in sessions},
                  domain_review=review,parent_id=body.parent_id,rule_version=RULE_VERSION,raw_method_evidence_available=methods_available,
                  method_observations_available=methods_available and all('methods' in c and all(m.get('signature') for m in c['methods']) for c in static['classes']),
                  observed_methods_sha256=digest(sorted(observed)),
                  artifact_available=bool(artifact.path), modernization_baseline=run.result.get('modernization_baseline',{}),
                  tech_inventory_status=(run.result.get('tech_inventory') or {}).get('status','UNAVAILABLE'), projection_state='PENDING')
    fingerprint=digest(manifest)
    manifest['captured_at']=now().isoformat()
    manifest['derived_assessments']='NOT_RECOMPUTED; static finding references remain baseline-scoped' if review else 'BASELINE_ONLY; no Phase 5 assessments created'
    return static,runtime,manifest,observed,fingerprint


def create(db,app_id,body,config,actor,preview=False,commit=True):
    static,runtime,manifest,observed,fingerprint=prepare(db,app_id,body,config,actor)
    tenant=db.info.get('tenant_id','local')
    existing=db.scalar(select(ArchitectureVersion).where(ArchitectureVersion.fingerprint==fingerprint,ArchitectureVersion.tenant_id==tenant))
    if existing and not preview:return existing
    vid=str(uuid5(NAMESPACE_URL,'archintel:'+tenant+':'+fingerprint))
    document,evidence,facts,discovery=build(vid,static,runtime,manifest,observed)
    if len(document['graph']['nodes'])>500000 or len(document['graph']['edges'])>750000:raise HTTPException(413,'Canonical graph exceeds the 500,000 node / 750,000 relationship projection budget.')
    if preview:return dict(manifest=manifest,fingerprint=fingerprint,counts=dict(nodes=len(document['graph']['nodes']),relationships=len(document['graph']['edges']),evidence=len(evidence),facts=len(facts),discovery=len(discovery)),domains=static['domains'])
    item=ArchitectureVersion(id=vid,tenant_id=tenant,application_id=app_id,analysis_id=body.analysis_id,parent_id=body.parent_id,name=body.name,fingerprint=fingerprint,manifest=manifest,document=document)
    db.add(item);db.flush()
    # ORM add() per row retains every large JSON document in the identity map and
    # makes large captures take many minutes. Use bounded executemany batches so
    # the canonical snapshot and its normalized evidence persist efficiently.
    batch_size=1000
    for rows,model in ((evidence,Evidence),(facts,ArchitectureFact)):
        for start in range(0,len(rows),batch_size):
            batch=[dict(version_id=vid,tenant_id=tenant,**row) for row in rows[start:start+batch_size]]
            db.execute(insert(model),batch)
    for start in range(0,len(discovery),batch_size):
        batch=[dict(id=row['id'],tenant_id=tenant,version_id=vid,document=row,priority=row['priority'],state='OPEN',history=[])
               for row in discovery[start:start+batch_size]]
        db.execute(insert(DiscoveryItem),batch)
    db.add(Projection(tenant_id=tenant,version_id=vid,content_hash=digest(document['graph'])))
    if commit:db.commit()
    return item


def view(item):
    return dict(id=item.id,name=item.name,application_id=item.application_id,analysis_id=item.analysis_id,parent_id=item.parent_id,created_at=item.created_at,fingerprint=item.fingerprint,manifest=item.manifest,
                counts=dict(nodes=len(item.document['graph']['nodes']),relationships=len(item.document['graph']['edges']),facts=item.document['facts_count'],evidence=item.document['evidence_count']))


def paged(db,model,vid,offset,limit,**filters):
    version(db,vid)
    query=select(model).where(model.version_id==vid)
    for k,v in filters.items():
        if v is not None:query=query.where(getattr(model,k)==v)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    query=query.order_by(DiscoveryItem.priority,model.id) if model is DiscoveryItem else query.order_by(model.id)
    rows=list(db.scalars(query.offset(offset).limit(limit)))
    return dict(total=total,offset=offset,limit=limit,items=[dict(r.document,id=r.id,**(dict(state=r.state,history=r.history,revision=len(r.history)) if model is DiscoveryItem else dict(kind=r.kind) if model is Evidence else {})) for r in rows])


def provenance(db,vid,fid):
    item=version(db,vid);fact=get(db,ArchitectureFact,fid)
    if fact.version_id!=vid:raise HTTPException(404,'Fact not found in this version.')
    rows=[]
    for eid in fact.document['evidence_ids']:
        e=get(db,Evidence,eid)
        if e.version_id!=vid:raise HTTPException(409,'Evidence provenance mismatch.')
        refs=[]
        for ref in e.document.get('references',[])[:20]:
            session=get(db,RuntimeSession,ref['session_id'])
            available=not session.settings.get('events_purged') and db.scalar(select(RuntimeEvent.id).where(RuntimeEvent.session_id==session.id,RuntimeEvent.trace_id==ref['trace_id'],RuntimeEvent.span_id==ref['span_id'])) is not None
            refs.append(dict(**ref,status='AVAILABLE' if available else 'EXPIRED_OR_UNAVAILABLE',url=f"/api/v1/runtime-sessions/{session.id}/spans/{ref['trace_id']}/{ref['span_id']}" if available else None))
        rows.append(dict(id=e.id,kind=e.kind,**e.document,resolved_references=refs))
    return dict(version_id=item.id,fact=dict(id=fact.id,**fact.document),evidence=rows)
