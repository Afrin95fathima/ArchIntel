from fastapi import APIRouter,Depends,HTTPException,Request
from sqlalchemy import select
from app.access.routes import db_session
from app.access.core import LOCK,audit,record,latest_policy
from app.access.schemas import ContextInput
from app.access.gateway import read_context
from .models import ModelProvider,ModelInvocation
from .schemas import ProviderInput,ProviderState,SourceQuery
from .providers import endpoint_allowed,installed_digest,ProviderFailure
from .filters import sanitize
from .gateway import select_facts

router=APIRouter(prefix='/api/v1/security/ai',tags=['AI gateway'])


@router.get('/gemini/status')
def gemini_status(request:Request):
    """Expose readiness only; never return or validate the local API key."""
    config=request.app.state.config
    configured=bool(config.gemini_api_key.get_secret_value())
    return dict(provider='GEMINI',credential_configured=configured,model=config.gemini_model,
                adapter='READY',generation_route_enabled=True,
                external_transfer_requires_per_request_approval=True)


def provider_view(item):
    return {key:getattr(item,key) for key in ('id','name','adapter','destination','endpoint','model','model_digest','enabled')}


@router.get('/providers')
def providers(db=Depends(db_session)):
    return [provider_view(p) for p in db.scalars(select(ModelProvider).limit(100))]


@router.post('/providers',status_code=201)
def register(body:ProviderInput,request:Request,db=Depends(db_session)):
    identity=request.state.identity
    db.rollback()
    record(request.app.state.sessions,identity['tenant_id'],identity['id'],'MODEL_PROVIDER_CHECK','REQUESTED')
    try:
        if body.destination!='LOCAL_MODEL':raise ProviderFailure('DESTINATION_DENIED')
        endpoint_allowed(body.endpoint,request.app.state.config)
        digest=installed_digest(body.endpoint,body.model,request.app.state.config)
    except Exception:
        record(request.app.state.sessions,identity['tenant_id'],identity['id'],'MODEL_PROVIDER_CHECK','DENY',details={'reason':'UNAPPROVED_OR_UNAVAILABLE'})
        raise HTTPException(422,'Only an installed local model at an operator-approved loopback endpoint can be registered.')
    with LOCK:
        item=ModelProvider(name=body.name,endpoint=body.endpoint,model=body.model,model_digest=digest,destination='LOCAL_MODEL',adapter='OLLAMA')
        db.add(item);db.flush()
        audit(db,identity['tenant_id'],identity['id'],'REGISTER_MODEL_PROVIDER','ALLOW',resource=item.id,details={'model_digest':digest,'destination':'LOCAL_MODEL'})
        db.commit()
    return provider_view(item)


@router.post('/providers/{provider_id}/state')
def state(provider_id:str,body:ProviderState,request:Request,db=Depends(db_session)):
    with LOCK:
        item=db.get(ModelProvider,provider_id)
        if not item:raise HTTPException(404,'Provider not found.')
        item.enabled=body.enabled
        audit(db,item.tenant_id,request.state.identity['id'],'MODEL_PROVIDER_STATE','ALLOW',resource=item.id,details={'enabled':item.enabled})
        db.commit()
    return provider_view(item)


@router.post('/providers/{provider_id}/check')
def check(provider_id:str,request:Request,db=Depends(db_session)):
    item=db.get(ModelProvider,provider_id)
    if not item:raise HTTPException(404,'Provider not found.')
    identity=request.state.identity;endpoint,model,digest=item.endpoint,item.model,item.model_digest
    db.rollback()
    record(request.app.state.sessions,identity['tenant_id'],identity['id'],'MODEL_CONNECTION_CHECK','REQUESTED',resource=provider_id)
    try:valid=installed_digest(endpoint,model,request.app.state.config)==digest
    except Exception:valid=False
    record(request.app.state.sessions,identity['tenant_id'],identity['id'],'MODEL_CONNECTION_CHECK','ALLOW' if valid else 'DENY',resource=provider_id)
    return dict(available=valid,reason='Pinned local model available.' if valid else 'Unavailable or revision changed. Re-register changed models.')


@router.get('/invocations')
def invocations(db=Depends(db_session)):
    return [dict(id=i.id,created_at=i.created_at,provider_id=i.provider_id,resource=i.resource,outcome=i.outcome,reason=i.reason,metadata=i.metadata_json) for i in db.scalars(select(ModelInvocation).order_by(ModelInvocation.created_at.desc()).limit(100))]


@router.post('/source-query')
def source_query(body:SourceQuery,request:Request,db=Depends(db_session)):
    if any(r.end<r.start or r.end-r.start>=80 for r in body.ranges) or sum(r.end-r.start+1 for r in body.ranges)>200:
        raise HTTPException(422,'Select at most 80 lines per range and 200 lines total.')
    # Purpose is retained by source audit; block secrets and redact PII first.
    try:purpose,_=sanitize(body.purpose)
    except Exception:raise HTTPException(422,'Purpose must not contain sensitive data or instructions.')
    files=list(dict.fromkeys(r.file for r in body.ranges))
    with LOCK:
        context=read_context(db,request,ContextInput(repository_id=body.repository_id,commit=body.commit,files=files,purpose=purpose))
    facts=[]
    content={f['path']:f['content'].splitlines() for f in context['files']}
    for i,r in enumerate(body.ranges):
        if r.end>len(content[r.file]):raise HTTPException(422,'Requested line range is outside the committed file.')
        facts.append(dict(id=f'{r.file}:{r.start}-{r.end}',kind='source_range',text='\n'.join(content[r.file][r.start-1:r.end])))
    facts,info=select_facts(request,db,facts,body.question,'repository:'+body.repository_id,'SOURCE_READ',
        source_scope=dict(repository_id=body.repository_id,commit=body.commit,files=files))
    return dict(facts=facts,**info,external_transfer=False,limitations=['Model selects authorized source ranges only; no generated code or execution. Detection is heuristic.'])
