"""Server-built envelopes, fresh authorization, bounded dispatch and validated citations."""
from datetime import timedelta
import hashlib
import json
from time import monotonic
from uuid import uuid4
from sqlalchemy import select,func
from app.models import now
from app.access.core import LOCK,audit,latest_policy
from app.access.models import Principal,SourceGrant,SourceRepository
from app.access.gateway import matches
from .models import ModelProvider,ModelInvocation
from .filters import sanitize,FilterDenied,VERSION
from .providers import OllamaAdapter,ProviderFailure


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def event(request,identity,invocation,outcome,reason,metadata,provider_id='',resource=''):
    with LOCK,request.app.state.sessions.begin() as db:
        row=db.get(ModelInvocation,invocation)
        if not row:
            row=ModelInvocation(id=invocation,tenant_id=identity['tenant_id'],principal_id=identity['id'],provider_id=provider_id,resource=resource,outcome=outcome,reason=reason,metadata_json=metadata)
            db.add(row)
        else:
            row.outcome,row.reason,row.metadata_json=outcome,reason,metadata
        audit(db,identity['tenant_id'],identity['id'],'MODEL_INVOCATION',outcome,resource=resource,
              details=dict(reason=reason,provider_id=provider_id,**metadata),request_id=invocation)


def authorization(db,identity,permission,source_scope=None):
    principal=db.get(Principal,identity['id'])
    if not principal or principal.tenant_id!=identity['tenant_id'] or not principal.active:
        raise ProviderFailure('IDENTITY_REVOKED')
    if not {permission,'MODEL_USE_LOCAL'}<=set(principal.permissions):
        raise ProviderFailure('MODEL_PERMISSION_REQUIRED')
    policy=latest_policy(db,identity['tenant_id'])
    document=policy.document if policy else {}
    if not document.get('model_enabled',False):raise ProviderFailure('MODEL_DISABLED')
    provider=db.get(ModelProvider,document.get('model_provider_id') or '')
    if not provider or provider.tenant_id!=identity['tenant_id'] or not provider.enabled:
        raise ProviderFailure('PROVIDER_UNAVAILABLE')
    if provider.destination!='LOCAL_MODEL' or provider.adapter!='OLLAMA' or document.get('external_transfer','DENY')!='DENY':
        raise ProviderFailure('DESTINATION_DENIED')
    if source_scope:
        repository=db.get(SourceRepository,source_scope['repository_id'])
        grant=db.scalar(select(SourceGrant).where(SourceGrant.tenant_id==identity['tenant_id'],SourceGrant.principal_id==principal.id,SourceGrant.repository_id==source_scope['repository_id']))
        if not document.get('source_read_enabled') or not repository or repository.tenant_id!=identity['tenant_id'] or repository.commit!=source_scope['commit'] or not grant:
            raise ProviderFailure('SOURCE_SCOPE_REVOKED')
        if any(not matches(p,grant.allowed_paths) or matches(p,grant.protected_paths+document['protected_paths']) for p in source_scope['files']):
            raise ProviderFailure('SOURCE_SCOPE_REVOKED')
    return policy,provider


def select_facts(request,db,facts,question,resource,permission='ANALYSIS_READ',source_scope=None):
    identity=request.state.identity
    invocation=str(uuid4());started=monotonic();provider_id=''
    metadata={'filter_version':VERSION,'external_transfer':False,'dispatched':False,'purpose':'SOURCE_RANGE_REVIEW' if source_scope else 'EVIDENCE_SELECTION','deployment_profile':'LOCAL_PRIVATE'}
    fallback=[] if source_scope else facts
    db.rollback()  # No request read transaction remains open during durable audit.
    try:
        with LOCK,request.app.state.sessions() as state:
            policy,provider=authorization(state,identity,permission,source_scope)
            provider_id=provider.id;revision=policy.revision;document=dict(policy.document)
            endpoint,model,digest=provider.endpoint,provider.model,provider.model_digest
            used=state.scalar(select(func.count()).select_from(ModelInvocation).where(ModelInvocation.tenant_id==identity['tenant_id'],ModelInvocation.created_at>=now()-timedelta(hours=1),ModelInvocation.metadata_json['dispatched'].as_boolean()==True))
            if used>=document.get('model_calls_per_hour',30):raise ProviderFailure('HOURLY_BUDGET')
        mode=document.get('sensitive_data','REDACT')
        safe_question,categories=sanitize(question,mode)
        selected=[];candidates=[]
        for i,fact in enumerate(facts[:12]):
            safe_text,found=sanitize(str(fact['text']),mode);categories+=found
            candidates.append(dict(fact,text=safe_text))
            selected.append({'id':'e'+str(i),'text':safe_text})
        envelope={'question':safe_question,'facts':selected}
        encoded=canonical(envelope)
        if not selected:raise ProviderFailure('NO_EVIDENCE')
        if len(encoded.encode())>document.get('model_context_bytes',16384):raise ProviderFailure('CONTEXT_LIMIT')
        # Scan the exact outgoing user envelope again, including its serialization.
        exact,_=sanitize(encoded,mode)
        if exact!=encoded:raise FilterDenied('ENVELOPE_NOT_SANITIZED')
        metadata.update(policy_revision=revision,context_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                        context_bytes=len(encoded.encode()),selected_count=len(selected),omitted_count=max(0,len(facts)-12),
                        redaction_categories=sorted(set(categories)),classification='RESTRICTED_LOCAL_ONLY',
                        model_digest=digest,destination='LOCAL_MODEL',output_token_limit=document.get('model_output_tokens',128))
        with LOCK,request.app.state.sessions() as state:
            current,approved=authorization(state,identity,permission,source_scope)
            if current.revision!=revision or (approved.endpoint,approved.model,approved.model_digest)!=(endpoint,model,digest):raise ProviderFailure('AUTHORIZATION_CHANGED')
            if monotonic()-started>60:raise ProviderFailure('ENVELOPE_EXPIRED')
            # Recheck budget under the same lock as reservation to avoid overspend.
            used=state.scalar(select(func.count()).select_from(ModelInvocation).where(ModelInvocation.tenant_id==identity['tenant_id'],ModelInvocation.created_at>=now()-timedelta(hours=1),ModelInvocation.metadata_json['dispatched'].as_boolean()==True))
            if used>=document.get('model_calls_per_hour',30):raise ProviderFailure('HOURLY_BUDGET')
            metadata['dispatched']=True
            event(request,identity,invocation,'REQUESTED','AUTHORIZED',metadata,provider_id,resource)
        response=OllamaAdapter().select(provider,json.loads(encoded),request.app.state.config,document.get('model_output_tokens',128))
        message=response.get('message',{})
        if not response.get('done') or message.get('tool_calls') or message.get('images') or message.get('role')!='assistant':
            raise ProviderFailure('INVALID_RESPONSE')
        content=message.get('content','')
        clean,output_categories=sanitize(content,'BLOCK')
        output=json.loads(clean)
        if not isinstance(output,dict) or set(output)!={'ids'} or not isinstance(output['ids'],list) or len(output['ids'])>12:
            raise ProviderFailure('INVALID_RESPONSE')
        allowed={f['id']:i for i,f in enumerate(selected)}
        if any(not isinstance(i,str) or i not in allowed for i in output['ids']) or len(set(output['ids']))!=len(output['ids']):
            raise ProviderFailure('INVALID_CITATIONS')
        if not output['ids']:raise ProviderFailure('MODEL_ABSTAINED')
        with LOCK,request.app.state.sessions() as state:
            current,approved=authorization(state,identity,permission,source_scope)
            if current.revision!=revision or not approved.enabled:raise ProviderFailure('AUTHORIZATION_CHANGED')
            usage={k:response[k] for k in ('prompt_eval_count','eval_count') if type(response.get(k)) is int and 0<=response[k]<=1000000}
            metadata.update(usage=usage,duration_ms=int((monotonic()-started)*1000),accepted_count=len(output['ids']),cost_currency=None,cost_amount=None)
            event(request,identity,invocation,'ALLOW','VALIDATED_CITATIONS',metadata,provider_id,resource)
        return [candidates[allowed[i]] for i in output['ids']],dict(mode='LOCAL_MODEL_ASSISTED',request_id=invocation,reason='VALIDATED_CITATIONS',redaction_categories=metadata['redaction_categories'])
    except Exception as error:
        # Only fixed internal reason codes may be persisted. Provider exception text,
        # prompt, raw model output and matched credentials are never logged/stored.
        reason=str(error) if isinstance(error,(ProviderFailure,FilterDenied)) else 'FILTER_OR_PROVIDER_FAILURE'
        if not reason.replace('_','').isupper() or len(reason)>80:reason='FILTER_OR_PROVIDER_FAILURE'
        metadata['duration_ms']=int((monotonic()-started)*1000)
        event(request,identity,invocation,'DENY' if not metadata['dispatched'] else 'REJECTED',reason,metadata,provider_id,resource)
        return fallback,dict(mode='LOCAL_EVIDENCE',request_id=invocation,reason=reason,redaction_categories=metadata.get('redaction_categories',[]))
