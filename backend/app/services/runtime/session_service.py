"""Bounded single-process session orchestration and deterministic derived evidence."""
from datetime import timedelta
import hashlib
import hmac
import secrets
from threading import RLock
from sqlalchemy import select, delete
from fastapi import HTTPException
from app.models import AnalysisRun, Application, Artifact, now
from app.runtime.models import RuntimeSession, RuntimeEvent
from app.runtime.schemas import SessionView
from .graph_builder import build
from .coverage import calculate
from .fusion import fuse
from .intelligence import derive
from .instrumentation import build_plan

LOCK = RLock()
LIMITATIONS = ['Telemetry observes executed and instrumented paths only; unobserved does not mean unused.',
    'Method/entry-point coverage needs a new static method inventory; overloads and inherited/composed routes may remain unobserved.',
    'Parent-child span relationships are observed nesting, not proof of every Java call.',
    'Static snapshots and structural readiness are preserved; runtime scores are transparent heuristics.',
    'Local prototype with workspace authentication; distributed worker locks and production deployment hardening are not implemented.',
    'Shared persistence candidates require matching system/server/namespace/resource identities and remain subject to review.']


def get_session(db, identity):
    item = db.get(RuntimeSession,identity)
    if not item or item.tenant_id!=db.info.get('tenant_id','local'): raise HTTPException(404,'Runtime session not found.')
    return item


def view(item):
    result = SessionView.model_validate(item)
    last = item.last_received_at
    if last:
        last = last.replace(tzinfo=now().tzinfo) if last.tzinfo is None else last
    result.agent_status = 'DISCONNECTED' if item.status in ('COMPLETED','FAILED') or last and now()-last>timedelta(seconds=60) else 'RECEIVING_DATA' if last else 'WAITING'
    return result


def prepare(db, app_id, body):
    app,run = db.get(Application,app_id),db.get(AnalysisRun,body.analysis_id)
    if not app or app.tenant_id!=db.info.get('tenant_id','local'): raise HTTPException(404,'Application not found.')
    if not run or run.tenant_id!=db.info.get('tenant_id','local') or run.application_id!=app_id or run.status!='COMPLETED':
        raise HTTPException(409,'Choose a completed static analysis from this application.')
    options=body.model_dump(exclude={'analysis_id','name','environment'})
    artifact=db.get(Artifact,run.artifact_id)
    options['artifact_sha256']=artifact.sha256
    options['service_name']=body.service_name or 'archintel-'+app_id
    options['instrumentation_plan']=build_plan(run.result,options)
    return run,options


def create(db, app_id, body):
    run,options=prepare(db,app_id,body)
    token = secrets.token_urlsafe(32)
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    options=dict(options,token_expires_at=(now()+timedelta(hours=24)).isoformat())
    item = RuntimeSession(application_id=app_id,analysis_id=run.id,name=body.name,environment=body.environment,
        token_hash=token_hash,settings=options)
    db.add(item)
    db.commit()
    return item,token


def authenticate(item, authorization):
    token = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
    expiry=item.settings.get('token_expires_at')
    if expiry:
        from datetime import datetime
        try: expired=now()>=datetime.fromisoformat(expiry)
        except ValueError: expired=True
    else:
        # Historical sessions predate token expiry. Bound them to session creation plus 24h.
        created=item.created_at.replace(tzinfo=now().tzinfo) if item.created_at.tzinfo is None else item.created_at
        expired=now()>=created+timedelta(hours=24)
    if expired or not token or not hmac.compare_digest(item.token_hash,hashlib.sha256(token.encode()).hexdigest()):
        raise HTTPException(401,'Valid session bearer token required.')


def ingest(db, item, events, settings):
    if item.status not in ('WAITING_FOR_AGENT','RUNNING'): raise HTTPException(409,'Session is not accepting telemetry.')
    counters=dict(item.settings.get('ingestion',{}))
    strict=item.settings.get('binding_mode')=='STRICT'
    for event in events:
        mismatch=any(event.get(k) and expected and event[k]!=expected for k,expected in
                     [('service_name',item.settings.get('service_name')),('artifact_sha256',item.settings.get('artifact_sha256'))])
        missing=not event.get('service_name') or not event.get('artifact_sha256')
        if mismatch or event.get('invalid_resource_identity') or strict and missing:
            counters['binding_rejected_spans']=counters.get('binding_rejected_spans',0)+len(events)
            item.settings=dict(item.settings,ingestion=counters)
            db.commit()
            raise HTTPException(409,'Telemetry resource identity does not match the session. Use its generated service name and artifact resource attributes.')
    existing={(row.trace_id,row.span_id):row.data for row in db.scalars(select(RuntimeEvent).where(RuntimeEvent.session_id==item.id))}
    accepted,dropped,duplicates,conflicts,matched,unverified = 0,0,0,0,0,0
    for event in events:
        key = (event['trace_id'],event['span_id'])
        stored=dict(event,session_id=item.id)
        if key in existing:
            duplicates+=1
            if existing[key]!=stored:conflicts+=1
            continue
        if len(existing)>=settings.runtime_max_session_spans:
            dropped += 1
            continue
        existing[key]=stored
        db.add(RuntimeEvent(session_id=item.id,trace_id=key[0],span_id=key[1],data=stored))
        accepted += 1
        if event.get('service_name') and event.get('artifact_sha256') and item.settings.get('artifact_sha256'):matched+=1
        else:unverified+=1
    item.span_count=len(existing)
    item.trace_count=len({key[0] for key in existing})
    item.dropped_count += dropped
    for key,value in dict(accepted_spans=accepted,duplicate_spans=duplicates,conflicting_spans=conflicts,declared_match_spans=matched,unverified_spans=unverified).items():
        counters[key]=counters.get(key,0)+value
    item.settings=dict(item.settings,ingestion=counters)
    if events:
        item.last_received_at=now()
        item.status='RUNNING'
    item.updated_at=now()
    db.commit()
    return dropped


def result(db, sessions, settings):
    if not sessions: raise HTTPException(422,'Select at least one runtime session.')
    if len(sessions)>10: raise HTTPException(422,'Select at most ten sessions.')
    analysis_ids = {s.analysis_id for s in sessions}
    if len(analysis_ids)!=1: raise HTTPException(409,'Selected sessions must share the same static analysis baseline.')
    if len(sessions)==1 and sessions[0].status=='COMPLETED' and sessions[0].result:
        return sessions[0].result
    for session in sessions:
        if session.settings.get('events_purged'): raise HTTPException(409,'Raw evidence expired; use individual archived session reports.')
    run = db.get(AnalysisRun,sessions[0].analysis_id)
    ids=sorted({s.id for s in sessions})
    events = list(db.scalars(select(RuntimeEvent.data).where(RuntimeEvent.session_id.in_(ids))))
    runtime=build(events,run.result)
    coverage=calculate(run.result,runtime,events)
    return dict(analysis_id=run.id,session_ids=ids,graph=fuse(run.result,runtime),runtime_graph=runtime,
        mappings=runtime['mappings'],coverage=coverage,quality=quality(sessions,runtime,coverage),derivation_version='runtime-foundation-2',
        **derive(run.result,runtime,coverage,events,settings.runtime_structural_weight,settings.runtime_score_weights),limitations=LIMITATIONS)


def quality(sessions,runtime,coverage):
    counters={key:sum(s.settings.get('ingestion',{}).get(key,0) for s in sessions) for key in
              ('duplicate_spans','conflicting_spans','declared_match_spans','unverified_spans','binding_rejected_spans')}
    counters.update(accepted_spans=sum(s.span_count for s in sessions),dropped_spans=sum(s.dropped_count for s in sessions),
                    missing_parents=runtime['missing_parent_count'],invalid_parent_links=runtime.get('invalid_parent_count',0))
    warnings=[]
    for key in ('conflicting_spans','unverified_spans','binding_rejected_spans','dropped_spans','missing_parents','invalid_parent_links'):
        if counters[key]:warnings.append(f'{key.replace("_"," ")}: {counters[key]}')
    if any('ingestion' not in s.settings and s.span_count for s in sessions):warnings.append('Legacy session ingestion diagnostics are unavailable.')
    return dict(**counters,method_mapping=coverage.get('method_mapping_diagnostics',{}),warnings=warnings,
                scope=[dict(session_id=s.id,binding_mode=s.settings.get('binding_mode','LEGACY'),
                            plan_version=s.settings.get('instrumentation_plan',{}).get('version','LEGACY'),
                            plan_sha256=s.settings.get('instrumentation_plan',{}).get('sha256')) for s in sessions],
                binding_note='Artifact identity is declared by the telemetry sender; it is not cryptographic attestation.')


def recover(db):
    for item in db.scalars(select(RuntimeSession).where(RuntimeSession.status=='PROCESSING')):
        item.status='FAILED';item.ended_at=now();item.updated_at=now()
        item.settings=dict(item.settings,recovery_reason='Report generation was interrupted. Retry Stop while raw evidence remains available.')
    db.commit()


def transition(db,item,action,settings):
    if action=='start':
        if item.status=='CREATED':
            item.status='WAITING_FOR_AGENT'
            item.started_at=now()
        elif item.status not in ('WAITING_FOR_AGENT','RUNNING'): raise HTTPException(409,'Completed sessions cannot be restarted; create a new session.')
    else:
        if item.status=='COMPLETED': return item
        item.status='PROCESSING'
        try:
            item.result=result(db,[item],settings)
            item.status='COMPLETED'
            item.ended_at=now()
        except Exception:
            item.status='FAILED'
            item.ended_at=now()
            db.commit()
            raise
    item.updated_at=now()
    db.commit()
    return item


def purge(db,settings):
    cutoff=now()-timedelta(hours=settings.runtime_raw_trace_retention_hours)
    # Bound active observation lifetime as well as completed-event retention.
    expired=list(db.scalars(select(RuntimeSession).where(RuntimeSession.status.in_(['RUNNING','WAITING_FOR_AGENT']),RuntimeSession.started_at<cutoff)))
    for item in expired:
        try:transition(db,item,'stop',settings)
        except Exception:
            db.rollback()
            item.status='FAILED';item.ended_at=now();item.updated_at=now()
            db.commit()
    sessions=list(db.scalars(select(RuntimeSession).where(RuntimeSession.status.in_(['COMPLETED','FAILED']),
        (RuntimeSession.ended_at<cutoff) | (RuntimeSession.ended_at.is_(None) & (RuntimeSession.updated_at<cutoff)))))
    sessions=[s for s in sessions if not s.settings.get('events_purged')]
    for item in sessions:
        db.execute(delete(RuntimeEvent).where(RuntimeEvent.session_id==item.id))
        item.settings=dict(item.settings,events_purged=True)
    db.commit()
    return len(sessions)


def agent_config(item, static, settings, token=None):
    plan=item.settings.get('instrumentation_plan') or build_plan(static,item.settings)
    mode=plan['mode'];classes=plan['classes']
    endpoint=settings.runtime_public_url.rstrip('/')+'/api/v1/runtime-sessions/'+item.id+'/v1/traces'
    env={'OTEL_SERVICE_NAME':item.settings.get('service_name') or 'archintel-'+item.application_id,'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT':endpoint,
        'OTEL_EXPORTER_OTLP_PROTOCOL':'http/protobuf','OTEL_METRICS_EXPORTER':'none','OTEL_LOGS_EXPORTER':'none',
        'OTEL_TRACES_SAMPLER':'parentbased_always_on','OTEL_INSTRUMENTATION_METHODS_INCLUDE':';'.join(c['class_name']+'['+c['methods']+']' for c in classes if c['methods'])}
    if item.settings.get('artifact_sha256'):env['OTEL_RESOURCE_ATTRIBUTES']='archintel.artifact.sha256='+item.settings['artifact_sha256']
    if token: env['OTEL_EXPORTER_OTLP_TRACES_HEADERS']='Authorization=Bearer '+token
    return dict(environment=env,instrumentation_plan=classes,plan=plan,binding_mode=item.settings.get('binding_mode','LEGACY'),mode=mode,
        command='java -javaagent:/path/opentelemetry-javaagent.jar -jar /path/application.jar',
        token_expires_at=item.settings.get('token_expires_at'),
        note='Set these environment variables in the application process. Start the session before the application. Session credential is reusable for OTLP ingestion, displayed only at creation/rotation, expires after 24 hours, and rotation revokes the prior credential. Explicit method names come from the static inventory; old snapshots without methods use framework auto-instrumentation only. Review the plan and overhead. No custom agent extension is required for selected methods.')
