"""Thin HTTP adapters; OTLP parsing and evidence logic live in runtime services."""
import hashlib
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from sqlalchemy import select
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from app.api import session as db_session
from app.models import AnalysisRun, now
from app.runtime.models import RuntimeSession, RuntimeEvent
from app.runtime.schemas import SessionInput, SessionView, SessionCreated, EvidenceResponse, Question
from app.services.runtime import session_service as service
from app.services.runtime.normalization import decode, normalize
from app.services.runtime.graph_builder import project
from app.services.runtime.mapping import map_class, map_method
from app.services.runtime.entry_points import is_method_entry_point

router=APIRouter(prefix='/api/v1',tags=['Runtime analysis'])


@router.post('/applications/{application_id}/runtime-sessions/plan',response_model=dict)
def preview(application_id:str,body:SessionInput,db=Depends(db_session)):
    _,options=service.prepare(db,application_id,body)
    return options['instrumentation_plan']


@router.post('/applications/{application_id}/runtime-sessions',response_model=SessionCreated,status_code=201)
def create_session(application_id: str,body:SessionInput,request:Request,db=Depends(db_session)):
    with service.LOCK:
        item,token=service.create(db,application_id,body)
        return dict(session=service.view(item),token=token,agent=service.agent_config(item,db.get(AnalysisRun,item.analysis_id).result,request.app.state.config,token))


@router.get('/applications/{application_id}/runtime-sessions',response_model=list[SessionView])
def list_sessions(application_id:str,db=Depends(db_session)):
    return [service.view(s) for s in db.scalars(select(RuntimeSession).where(RuntimeSession.application_id==application_id).order_by(RuntimeSession.created_at.desc()).limit(200))]


@router.get('/runtime-sessions/{session_id}',response_model=SessionView)
@router.get('/runtime-sessions/{session_id}/status',response_model=SessionView)
def status(session_id:str,db=Depends(db_session)):
    return service.view(service.get_session(db,session_id))


@router.get('/runtime-sessions/{session_id}/diagnostics',response_model=dict)
def diagnostics(session_id:str,db=Depends(db_session)):
    item=service.get_session(db,session_id)
    return dict(status=item.status,events_purged=item.settings.get('events_purged',False),
                recovery_reason=item.settings.get('recovery_reason'),ingestion=item.settings.get('ingestion',{}),
                binding_mode=item.settings.get('binding_mode','LEGACY'),dropped_spans=item.dropped_count,
                plan=item.settings.get('instrumentation_plan'))


@router.post('/runtime-sessions/{session_id}/start',response_model=SessionView)
def start(session_id:str,request:Request,db=Depends(db_session)):
    with service.LOCK: return service.view(service.transition(db,service.get_session(db,session_id),'start',request.app.state.config))


@router.post('/runtime-sessions/{session_id}/stop',response_model=SessionView)
def stop(session_id:str,request:Request,db=Depends(db_session)):
    with service.LOCK: return service.view(service.transition(db,service.get_session(db,session_id),'stop',request.app.state.config))


@router.get('/runtime-sessions/{session_id}/agent-config',response_model=dict)
def agent(session_id:str,request:Request,db=Depends(db_session)):
    item=service.get_session(db,session_id)
    return service.agent_config(item,db.get(AnalysisRun,item.analysis_id).result,request.app.state.config)


@router.post('/runtime-sessions/{session_id}/rotate-token',response_model=dict)
def rotate(session_id:str,request:Request,db=Depends(db_session)):
    with service.LOCK:
        item=service.get_session(db,session_id)
        token=secrets.token_urlsafe(32)
        item.token_hash=hashlib.sha256(token.encode()).hexdigest()
        from datetime import timedelta
        item.settings=dict(item.settings,token_expires_at=(now()+timedelta(hours=24)).isoformat())
        db.commit()
        return dict(token=token,agent=service.agent_config(item,db.get(AnalysisRun,item.analysis_id).result,request.app.state.config,token))


@router.post('/runtime-sessions/{session_id}/v1/traces')
async def ingest(session_id:str,request:Request,db=Depends(db_session)):
    service.authenticate(service.get_session(db,session_id),request.headers.get('authorization',''))
    config=request.app.state.config
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>config.runtime_max_body_bytes: raise HTTPException(413,'Telemetry body limit exceeded.')
    try:
        events=normalize(decode(bytes(body),request.headers.get('content-type',''),request.headers.get('content-encoding',''),config.runtime_max_body_bytes),config.runtime_max_batch_spans)
    except Exception as error:
        raise HTTPException(400,'Invalid or unsupported OTLP payload; check encoding, IDs, timestamps and limits.') from error
    with service.LOCK:
        db.expire_all()
        item=service.get_session(db,session_id)
        service.authenticate(item,request.headers.get('authorization',''))
        dropped=service.ingest(db,item,events,config)
    if request.headers.get('content-type','').split(';')[0]=='application/x-protobuf':
        response=ExportTraceServiceResponse()
        if dropped:
            response.partial_success.rejected_spans=dropped
            response.partial_success.error_message='Session span limit reached.'
        return Response(response.SerializeToString(),media_type='application/x-protobuf')
    return {'partialSuccess':{'rejectedSpans':str(dropped),'errorMessage':'Session span limit reached.'}} if dropped else {}


@router.get('/runtime-sessions/{session_id}/evidence',response_model=EvidenceResponse)
def evidence(session_id:str,request:Request,db=Depends(db_session)):
    with service.LOCK: return service.result(db,[service.get_session(db,session_id)],request.app.state.config)


@router.get('/runtime-sessions/{session_id}/coverage',response_model=dict)
def coverage(session_id:str,request:Request,db=Depends(db_session)):
    return evidence(session_id,request,db)['coverage']


@router.get('/runtime-sessions/{session_id}/graph/{level}',response_model=dict)
def runtime_graph(session_id:str,level:str,request:Request,db=Depends(db_session)):
    if level not in ('classes','packages','domains'): raise HTTPException(404,'Unknown graph level.')
    result=evidence(session_id,request,db)
    return project(result['runtime_graph'],level,db.get(AnalysisRun,result['analysis_id']).result)


@router.get('/applications/{application_id}/architecture/unified',response_model=EvidenceResponse)
def unified(application_id:str,request:Request,runtime_session_ids:str=Query(min_length=1,max_length=400),db=Depends(db_session)):
    with service.LOCK:
        sessions=[service.get_session(db,i) for i in sorted(set(runtime_session_ids.split(',')))]
        if any(s.application_id!=application_id for s in sessions): raise HTTPException(404,'Selected session does not belong to this application.')
        return service.result(db,sessions,request.app.state.config)


@router.get('/applications/{application_id}/architecture/unified/coverage-details',response_model=dict)
def unified_coverage_details(application_id:str,request:Request,
    kind:Literal['classes','entry_points','methods','dependencies','domains'],
    runtime_session_ids:str=Query(min_length=1,max_length=400),
    state:Literal['ALL','OBSERVED','NOT_OBSERVED']='ALL',q:str|None=Query(None,max_length=200),
    offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db=Depends(db_session)):
    """Return paged static/runtime membership details for an observation metric."""
    with service.LOCK:
        sessions=[service.get_session(db,i) for i in sorted(set(runtime_session_ids.split(',')))]
        if any(s.application_id!=application_id for s in sessions): raise HTTPException(404,'Selected session does not belong to this application.')
        result=service.result(db,sessions,request.app.state.config)
        static=db.get(AnalysisRun,result['analysis_id']).result
        runtime_graph=result['runtime_graph']
        classes={c['id']:c for c in static['classes']}
        domains={d['id']:d for d in static['domains']}
        nodes={n['id']:n for n in runtime_graph.get('nodes',[])}
        observed_classes={n.get('static_id') for n in nodes.values() if n.get('static_id') in classes}
        method_inventory_available=all(isinstance(c.get('methods'),list) and all(m.get('signature') for m in c['methods']) for c in static['classes'])
        collect_raw=kind in ('classes','methods','entry_points')
        retention_ok=all(not s.settings.get('events_purged') for s in sessions)
        events=list(db.scalars(select(RuntimeEvent.data).where(RuntimeEvent.session_id.in_([s.id for s in sessions])))) if retention_ok and collect_raw else []
        event_sessions={event.get('session_id') for event in events}
        raw_available=retention_ok and (not collect_raw or all(not s.span_count or s.id in event_sessions for s in sessions))
        event_counts={};class_refs={};method_refs={};method_counts={}
        for event in events:
            static_id=map_class(event.get('class_name'),classes).get('static_id')
            if static_id:
                event_counts[static_id]=event_counts.get(static_id,0)+1
                ref=dict(session_id=event.get('session_id'),trace_id=event.get('trace_id'),span_id=event.get('span_id'))
                if all(ref.values()) and len(class_refs.get(static_id,[]))<20: class_refs.setdefault(static_id,[]).append(ref)
            mapped=map_method(event,classes) if kind in ('methods','entry_points') and method_inventory_available else {}
            if mapped.get('signature'):
                identity=(mapped['static_class'],mapped['signature']);method_counts[identity]=method_counts.get(identity,0)+1
                if len(method_refs.get(identity,[]))<20:
                    method_refs.setdefault(identity,[]).append(dict(session_id=event.get('session_id'),trace_id=event.get('trace_id'),span_id=event.get('span_id')))

        def domain_name(class_id):
            domain=domains.get(classes[class_id].get('domain_id'))
            return domain.get('name') if domain else 'Unassigned'

        items=[]
        status='AVAILABLE'
        if kind=='classes':
            mappings={m.get('static_id'):m for m in runtime_graph.get('mappings',[]) if m.get('static_id')}
            for identity,cls in classes.items():
                seen=identity in observed_classes
                items.append(dict(id=identity,name=identity,state='OBSERVED' if seen else 'NOT_OBSERVED',
                    package_name=cls.get('package_name'),domain_name=domain_name(identity),
                    observed_spans=event_counts.get(identity,0) if raw_available else None,annotations=cls.get('annotations',[]),
                    evidence=(mappings.get(identity) or {}).get('evidence',[]),evidence_refs=class_refs.get(identity,[])[:20],
                    suggestion=None if seen else 'Exercise a representative request or background workflow that should reach this class, then confirm its class identity appears in a trace.'))
        elif kind in ('methods','entry_points'):
            inventory_available=method_inventory_available
            if not inventory_available or not raw_available:
                status='UNAVAILABLE'
            seen_methods=set()
            if raw_available and inventory_available:
                for event in events:
                    mapped=map_method(event,classes)
                    if mapped.get('signature'): seen_methods.add((mapped['static_class'],mapped['signature']))
            if inventory_available:
                for class_id,cls in classes.items():
                    for method in cls.get('methods',[]):
                        if not method.get('name') or method['name'].startswith('<'): continue
                        is_entry=is_method_entry_point(method.get('annotations',[]))
                        if (kind=='entry_points') != is_entry: continue
                        identity=(class_id,method['signature'])
                        seen=identity in seen_methods if raw_available else None
                        items.append(dict(id=class_id+'#'+method['signature'],name=method['name'],signature=method['signature'],
                            class_name=class_id,domain_name=domain_name(class_id),package_name=cls.get('package_name'),
                            annotations=method.get('annotations',[]),state='OBSERVED' if seen is True else 'NOT_OBSERVED' if seen is False else 'UNKNOWN',
                            observed_spans=method_counts.get(identity,0) if raw_available else None,evidence_refs=method_refs.get(identity,[]),
                            suggestion=('Exercise the route, message handler, or scheduled trigger declared by this entry point, then inspect the resulting trace.' if kind=='entry_points' else 'Exercise a representative flow that should call this method, then inspect the trace.') if seen is not True else None))
            else:
                for class_id,cls in classes.items():
                    for method in cls.get('methods',[]):
                        if not method.get('name') or method['name'].startswith('<'): continue
                        is_entry=is_method_entry_point(method.get('annotations',[]))
                        if (kind=='entry_points') != is_entry: continue
                        items.append(dict(id=class_id+'#'+(method.get('signature') or method['name']),name=method['name'],
                            signature=method.get('signature'),class_name=class_id,domain_name=domain_name(class_id),
                            annotations=method.get('annotations',[]),state='UNKNOWN',suggestion=None))
        elif kind=='dependencies':
            observed_pairs=set();observed_calls={};dependency_refs={}
            for edge in runtime_graph.get('edges',[]):
                if edge.get('dependency_type')!='METHOD_CALL': continue
                source=nodes.get(edge.get('source'),{}).get('static_id')
                target=nodes.get(edge.get('target'),{}).get('static_id')
                if source in classes and target in classes:
                    pair=(source,target);observed_pairs.add(pair);observed_calls[pair]=edge.get('call_count',0)
                    dependency_refs[pair]=edge.get('evidence',[])
            static_pairs={(edge['source'],edge['target']) for edge in static.get('edges',[]) if edge.get('dependency_type')=='METHOD_CALL'}
            for pair in sorted(static_pairs):
                seen=pair in observed_pairs
                items.append(dict(id=pair[0]+' -> '+pair[1],source=pair[0],target=pair[1],
                    name=pair[0]+' -> '+pair[1],state='OBSERVED' if seen else 'NOT_OBSERVED',
                    source_domain=domain_name(pair[0]),target_domain=domain_name(pair[1]),
                    observed_calls=observed_calls.get(pair,0),dependency_type='METHOD_CALL',evidence_refs=dependency_refs.get(pair,[]),
                    suggestion=None if seen else 'Exercise a flow that should invoke this statically declared call, then inspect the trace.'))
        else:
            domain_observed={d['id']:{c for c in d['classes'] if c in observed_classes} for d in static['domains']}
            for identity,domain in domains.items():
                seen=domain_observed[identity];members=domain['classes']
                items.append(dict(id=identity,name=domain['name'],state='OBSERVED' if seen else 'NOT_OBSERVED',
                    observation_state='ALL_CLASSES_OBSERVED' if seen==set(members) else 'PARTIALLY_OBSERVED' if seen else 'NOT_OBSERVED',
                    observed=len(seen),total=len(members),observed_classes=sorted(seen),
                    unobserved_classes=sorted(set(members)-seen),
                    suggestion=None if len(seen)==len(members) else 'Exercise representative entry points for this domain; start with the listed unobserved classes.'))

        if state!='ALL': items=[item for item in items if item['state']==state]
        if q:
            needle=q.casefold()
            items=[item for item in items if needle in ' '.join(str(value) for value in item.values()).casefold()]
        items.sort(key=lambda item:(item.get('name','').casefold(),item['id']))
        total=len(items)
        metric=result['coverage'][kind]
        if status=='UNAVAILABLE':
            reason='Exact method and entry-point membership needs retained span-level method evidence and a static method inventory. Available runtime aggregate counts remain shown above.'
        else:
            reason=metric.get('reason') or result['coverage'].get('note')
        return dict(kind=kind,status=status,metric=metric,reason=reason,items=items[offset:offset+limit],total=total,offset=offset,limit=limit)


@router.get('/applications/{application_id}/architecture/unified/{level}',response_model=dict)
def unified_graph(application_id:str,level:str,request:Request,runtime_session_ids:str=Query(min_length=1,max_length=400),graph_kind:Literal['unified','runtime','static']='unified',db=Depends(db_session)):
    if level not in ('classes','packages','domains'): raise HTTPException(404,'Unknown graph level.')
    result=unified(application_id,request,runtime_session_ids,db)
    static=db.get(AnalysisRun,result['analysis_id']).result
    graph=result['runtime_graph'] if graph_kind=='runtime' else result['graph']
    if graph_kind=='static':
        graph=dict(nodes=[dict(c,evidence_type='STATIC') for c in static['classes']],
            edges=[dict(e,evidence_type='STATIC',static_types=[e['dependency_type']],call_count=0,evidence=[]) for e in static['edges']])
    return project(graph,level,static)


@router.get('/runtime-sessions/{session_id}/spans/{trace_id}/{span_id}',response_model=dict)
def span(session_id:str,trace_id:str,span_id:str,db=Depends(db_session)):
    service.get_session(db,session_id)
    event=db.scalar(select(RuntimeEvent).where(RuntimeEvent.session_id==session_id,RuntimeEvent.trace_id==trace_id,RuntimeEvent.span_id==span_id))
    if not event: raise HTTPException(404,'Sanitized span not found or retention expired.')
    return event.data


@router.post('/runtime/retention/purge',response_model=dict)
def purge(request:Request,db=Depends(db_session)):
    with service.LOCK: return dict(purged_sessions=service.purge(db,request.app.state.config))


@router.post('/runtime-sessions/{session_id}/assistant/query',response_model=dict)
def assistant(session_id:str,body:Question,request:Request,db=Depends(db_session)):
    result=evidence(session_id,request,db)
    text=body.question.lower()
    if not any(word in text for word in ('runtime','coverage','domain','risk','modern','observ','depend','trace','flow')):
        return dict(facts=[],recommendations=[],answer='No runtime evidence supports that question.',mode='LOCAL_EVIDENCE')
    facts=[dict(text=f"Observed {result['coverage']['classes']['observed']} of {result['coverage']['classes']['total']} static classes.",source=f'/api/v1/runtime-sessions/{session_id}/coverage')]
    for item in result['modernization']:
        if item['domain_name'].lower() in text:
            facts.append(dict(text=f"{item['domain_name']}: structural {item['structural_score']}, runtime {item['runtime_score']}, combined {item['combined_score']}; observation confidence {item['coverage_confidence']}.",source=f'/api/v1/runtime-sessions/{session_id}/evidence'))
    from app.ai.gateway import select_facts
    prepared=[dict(f,id='runtime-evidence-'+str(i),kind='runtime') for i,f in enumerate(facts)]
    facts, gateway=select_facts(request,db,prepared,body.question,'runtime:'+session_id,'RUNTIME_READ')
    return dict(gateway=gateway,facts=facts,recommendations=result['recommendations'][:5],answer='Observed facts from the selected runtime session; suggested actions require architectural review.',mode=gateway['mode'])
