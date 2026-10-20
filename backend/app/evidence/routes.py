"""Authenticated bounded version, evidence, twin and discovery endpoints."""
from fastapi import APIRouter,Depends,Request,HTTPException,Query
from sqlalchemy import select
from app.api import session,get
from app.models import now
from . import service,projection
from .models import ArchitectureVersion,ArchitectureFact,Evidence,DiscoveryItem,Projection
from .schemas import VersionInput,DiscoveryUpdate

router=APIRouter(prefix='/api/v1',tags=['Evidence intelligence'])

def guard(request,item=None,has_runtime=False):
    if (has_runtime or item and item.manifest['runtime_session_ids']) and 'RUNTIME_READ' not in request.state.identity['permissions']:
        raise HTTPException(403,'Runtime read permission is required for versions containing runtime evidence.')

def owned(db,request,vid):
    item=service.version(db,vid);guard(request,item);return item

@router.post('/applications/{app_id}/architecture-versions/preview')
def preview(app_id:str,body:VersionInput,request:Request,db=Depends(session)):
    guard(request,has_runtime=bool(body.runtime_session_ids))
    if body.parent_id:owned(db,request,body.parent_id)
    with service.LOCK:return service.create(db,app_id,body,request.app.state.config,request.state.identity['id'],preview=True)

@router.post('/applications/{app_id}/architecture-versions',status_code=201)
def create(app_id:str,body:VersionInput,request:Request,db=Depends(session)):
    guard(request,has_runtime=bool(body.runtime_session_ids))
    if body.parent_id:owned(db,request,body.parent_id)
    with service.LOCK:return service.view(service.create(db,app_id,body,request.app.state.config,request.state.identity['id']))

@router.get('/applications/{app_id}/architecture-versions')
def versions(app_id:str,request:Request,db=Depends(session)):
    from app.models import Application
    get(db,Application,app_id)
    rows=db.scalars(select(ArchitectureVersion).where(ArchitectureVersion.application_id==app_id).order_by(ArchitectureVersion.created_at.desc()).limit(200))
    return [service.view(v) for v in rows if not v.manifest['runtime_session_ids'] or 'RUNTIME_READ' in request.state.identity['permissions']]

@router.get('/architecture-versions/{vid}')
def version(vid:str,request:Request,db=Depends(session)):
    return service.view(owned(db,request,vid))

@router.get('/architecture-versions/{vid}/twin')
def twin(vid:str,request:Request,db=Depends(session)):
    item=owned(db,request,vid);job=db.scalar(select(Projection).where(Projection.version_id==vid))
    return dict(**service.view(item),coverage=item.document['coverage'],quality=item.document['quality'],domains=item.document['domains'],unknowns=item.document['unknowns'],
                projection=dict(state=job.state,attempts=job.attempts,error_code=job.error_code,content_hash=job.content_hash),
                note='Canonical version snapshot. Graph availability and currentness are checked on graph queries; APPLIED is the last successful projection state.')

@router.get('/architecture-versions/{vid}/facts')
def facts(vid:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),classification:str|None=None,db=Depends(session)):
    owned(db,request,vid)
    if classification not in (None,'STATIC_ONLY','DYNAMIC_ONLY','STATIC_AND_DYNAMIC'):raise HTTPException(422,'Invalid classification.')
    return service.paged(db,ArchitectureFact,vid,offset,limit,classification=classification)

@router.get('/architecture-versions/{vid}/evidence')
def evidence(vid:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),db=Depends(session)):
    owned(db,request,vid);return service.paged(db,Evidence,vid,offset,limit)

@router.get('/architecture-versions/{vid}/facts/{fid}/provenance')
def provenance(vid:str,fid:str,request:Request,db=Depends(session)):
    owned(db,request,vid);return service.provenance(db,vid,fid)

@router.get('/architecture-versions/{vid}/graph')
def graph(vid:str,request:Request,limit:int=Query(150,ge=1,le=500),root:str|None=Query(None,max_length=36),db=Depends(session)):
    return projection.query(request.app.state.config,owned(db,request,vid),limit,root)

@router.post('/architecture-versions/{vid}/projection/rebuild')
def rebuild(vid:str,request:Request,db=Depends(session)):
    with service.LOCK:return projection.project(db,owned(db,request,vid),request.app.state.config)

@router.get('/architecture-versions/{vid}/discovery')
def discovery(vid:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),db=Depends(session)):
    owned(db,request,vid);return service.paged(db,DiscoveryItem,vid,offset,limit)

@router.post('/architecture-versions/{vid}/discovery/{did}')
def update(vid:str,did:str,body:DiscoveryUpdate,request:Request,db=Depends(session)):
    with service.LOCK:
        owned(db,request,vid);item=get(db,DiscoveryItem,did)
        if item.version_id!=vid:raise HTTPException(404,'Discovery item not found in this version.')
        if len(item.history)!=body.expected_revision:raise HTTPException(409,'Discovery item changed. Refresh before saving.')
        if len(item.history)>=100:raise HTTPException(409,'Discovery history limit reached; capture a successor version.')
        item.state=body.state;item.history=[*item.history,dict(state=body.state,note=body.note,actor=request.state.identity['id'],timestamp=now().isoformat())]
        db.commit();return dict(id=item.id,state=item.state,history=item.history,revision=len(item.history))

@router.get('/architecture-versions/{vid}/compare/{other_id}')
def compare(vid:str,other_id:str,request:Request,db=Depends(session)):
    a=owned(db,request,vid);b=owned(db,request,other_id)
    if a.analysis_id!=b.analysis_id or a.manifest.get('domain_review')!=b.manifest.get('domain_review'):raise HTTPException(409,'Observation comparisons require the same static baseline and domain review.')
    delta={}
    for name in ('classes','methods','entry_points','dependencies','domains'):
        x=a.document['coverage'][name];y=b.document['coverage'][name]
        delta[name]=None if x['percentage'] is None or y['percentage'] is None or x['total']!=y['total'] else round(y['percentage']-x['percentage'],2)
    return dict(from_version=a.id,to_version=b.id,percentage_point_delta=delta,note=f'Percentage-point delta between versions {a.id[:8]} and {b.id[:8]}; it measures observation only and infers no modernization improvement.')

@router.get('/architecture-versions/{vid}/export')
def export(vid:str,request:Request,db=Depends(session)):
    item=owned(db,request,vid)
    return dict(version=service.view(item),document=item.document,
        evidence=[dict(e.document,id=e.id,kind=e.kind) for e in db.scalars(select(Evidence).where(Evidence.version_id==vid).order_by(Evidence.id))],
        facts=[dict(f.document,id=f.id) for f in db.scalars(select(ArchitectureFact).where(ArchitectureFact.version_id==vid).order_by(ArchitectureFact.id))])
