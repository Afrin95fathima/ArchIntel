import copy
import gzip
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import Project, Application, Artifact, AnalysisRun
from app.runtime.models import RuntimeEvent, RuntimeSession
from app.services.engine import analyze
from app.services.runtime.normalization import decode,normalize
from app.services.runtime.mapping import map_class
from app.services.runtime.graph_builder import build
from app.services.runtime.coverage import calculate
from app.services.runtime.fusion import fuse
from app.services.runtime.intelligence import derive
from helpers import cls,edge
from security_helpers import sign_in_owner


def baseline():
    nodes=[cls('app.a.A'),cls('app.b.B'),cls('app.c.C'),cls('app.d.D')]
    return analyze(nodes,[edge('app.a.A','app.b.B'),edge('app.a.A','app.c.C'),edge('app.b.B','app.d.D')],Settings(_env_file=None))


def span(identity,clsname,parent=None,trace='1'*32,extras=None):
    attrs={'code.namespace':clsname,'code.function':'work',**(extras or {})}
    return dict(traceId=trace,spanId=f'{identity:016x}',parentSpanId=f'{parent:016x}' if parent else '',
        startTimeUnixNano='1000000000',endTimeUnixNano='1001000000',kind=1,
        attributes=[dict(key=k,value={'stringValue':v}) for k,v in attrs.items()])


def payload(*spans): return {'resourceSpans':[{'scopeSpans':[{'spans':list(spans)}]}]}


def events(*spans): return [dict(e,session_id='s1') for e in normalize(payload(*spans),100)]


@pytest.fixture
def live(tmp_path):
    config=Settings(_env_file=None,database_url='sqlite:///'+(tmp_path/'runtime.db').as_posix(),data_dir=tmp_path,runtime_max_session_spans=10,allowed_hosts=['testserver'])
    with TestClient(create_app(config)) as client:
        sign_in_owner(client)
        with client.app.state.sessions() as db:
            p=Project(name='Runtime test'); db.add(p); db.flush()
            a=Application(project_id=p.id,name='Test'); db.add(a); db.flush()
            f=Artifact(application_id=a.id,filename='test.jar',path='unused',sha256='0'*64,size=1); db.add(f); db.flush()
            run=AnalysisRun(application_id=a.id,artifact_id=f.id,status='COMPLETED',result=baseline()); db.add(run); db.commit()
            client.app_id=a.id; client.run_id=run.id
        yield client


def create(client):
    r=client.post(f'/api/v1/applications/{client.app_id}/runtime-sessions',json={'analysis_id':client.run_id,'name':'Test'})
    assert r.status_code==201,r.text
    return r.json()


@pytest.mark.parametrize('name,state,target',[
    ('app.a.A','EXACT','app.a.A'),('app/a/A','NORMALIZED','app.a.A'),
    ('Lapp/a/A;','NORMALIZED','app.a.A'),('app.a.A$$SpringCGLIB$$0','PROXY_RESOLVED','app.a.A'),
    ('app.a.A$$EnhancerBySpringCGLIB$$abcd','PROXY_RESOLVED','app.a.A'),
    ('jdk.proxy1.$Proxy42','UNRESOLVED',None),('A','UNRESOLVED',None),(None,'UNRESOLVED',None)])
def test_mapping(name,state,target):
    mapped=map_class(name,{'app.a.A':{}})
    assert (mapped['state'],mapped['static_id'])==(state,target)


def test_critical_fusion_and_partial_coverage_preserve_static():
    static=baseline(); before=copy.deepcopy(static)
    runtime=build(events(span(1,'app.a.A'),span(2,'app.b.B',1),span(3,'app.d.D',2),span(4,'app.x.X'),span(5,'app.b.B',4)),static)
    unified=fuse(static,runtime)
    pairs={(e['source'],e['target']):e['evidence_type'] for e in unified['edges']}
    assert pairs=={('app.a.A','app.b.B'):'STATIC_AND_DYNAMIC',('app.a.A','app.c.C'):'STATIC_ONLY',('app.b.B','app.d.D'):'STATIC_AND_DYNAMIC',('runtime:app.x.X','app.b.B'):'DYNAMIC_ONLY'}
    coverage=calculate(static,runtime)
    assert coverage['classes']['percentage']==75
    assert coverage['dependencies']['observed']==2
    assert coverage['methods']['percentage'] is None
    assert static==before
    more=build(events(span(1,'app.a.A'),span(2,'app.b.B',1),span(3,'app.d.D',2),span(6,'app.c.C',1)),static)
    assert calculate(static,more)['classes']['percentage']==100


def test_parent_reconstruction_is_trace_and_session_scoped():
    ev=events(span(1,'app.a.A'),span(2,'app.b.B',1,trace='2'*32))
    graph=build(ev,baseline())
    assert not graph['edges'] and graph['missing_parent_count']==1
    ev[1]['trace_id']=ev[0]['trace_id']; ev[1]['session_id']='s2'
    assert not build(ev,baseline())['edges']


def test_sensitive_payloads_not_retained_and_limits():
    raw=payload(span(1,'app.a.A',extras={'authorization':'Bearer secret','db.statement':'select private','http.request.body':'private'}))
    parsed=normalize(raw,10)
    assert 'secret' not in json.dumps(parsed) and 'private' not in json.dumps(parsed)
    with pytest.raises(ValueError): decode(gzip.compress(b'x'*1000),'application/json','gzip',100)
    with pytest.raises(ValueError): normalize(payload(span(0,'app.a.A')),10)
    with pytest.raises(ValueError): normalize(payload(span(1,'app.a.A'),span(2,'app.b.B')),1)


def test_lifecycle_auth_duplicates_isolation_and_evidence(live):
    created=create(live); sid=created['session']['id']; base='/api/v1/runtime-sessions/'+sid
    headers={'Authorization':'Bearer '+created['token']}
    data=payload(span(1,'app.a.A'),span(2,'app.b.B',1))
    assert live.post(base+'/v1/traces',json=data).status_code==401
    assert live.post(base+'/v1/traces',json=data,headers=headers).status_code==409
    assert live.post(base+'/start').status_code==200
    assert live.get(base).json()['agent_status']=='WAITING'
    for _ in range(2): assert live.post(base+'/v1/traces',json=data,headers=headers).status_code==200
    status=live.get(base).json()
    assert status['span_count']==2 and status['trace_count']==1 and status['agent_status']=='RECEIVING_DATA'
    assert 'token' not in live.get(base).text and 'Bearer' not in live.get(base+'/agent-config').text
    other=create(live)
    assert live.post('/api/v1/runtime-sessions/'+other['session']['id']+'/v1/traces',json=data,headers=headers).status_code==401
    result=live.get(base+'/evidence'); assert result.status_code==200,result.text
    assert result.json()['coverage']['classes']['percentage']==50
    for level in ('classes','packages','domains'): assert live.get(base+'/graph/'+level).status_code==200
    assert live.get('/api/v1/applications/wrong/architecture/unified',params={'runtime_session_ids':sid}).status_code==404
    assert live.post(base+'/stop').json()['status']=='COMPLETED'
    assert live.post(base+'/v1/traces',json=data,headers=headers).status_code==409
    assert live.post(base+'/start').status_code==409
    assert live.get(base+'/evidence').json()==result.json()
    assert live.get(base+'/spans/'+'1'*32+'/'+f'{2:016x}').status_code==200


def test_protobuf_gzip_and_partial_success(live):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest,ExportTraceServiceResponse
    c=create(live); base='/api/v1/runtime-sessions/'+c['session']['id']; live.post(base+'/start')
    msg=ExportTraceServiceRequest(); scope=msg.resource_spans.add().scope_spans.add()
    for i in range(1,13):
        s=scope.spans.add(trace_id=bytes.fromhex('1'*32),span_id=i.to_bytes(8,'big'),start_time_unix_nano=1,end_time_unix_nano=2)
        s.attributes.add(key='code.namespace').value.string_value='app.a.A'
        s.attributes.add(key='code.function').value.string_value='work'
    response=live.post(base+'/v1/traces',content=gzip.compress(msg.SerializeToString()),headers={'Authorization':'Bearer '+c['token'],'Content-Type':'application/x-protobuf','Content-Encoding':'gzip'})
    assert response.status_code==200,response.text
    assert ExportTraceServiceResponse.FromString(response.content).partial_success.rejected_spans==2
    assert live.get(base).json()['span_count']==10


def test_no_telemetry_retains_structural_readiness():
    static=baseline(); runtime=build([],static); coverage=calculate(static,runtime)
    result=derive(static,runtime,coverage,[],.6)
    assert all(a['runtime_score'] is None and a['combined_score']==a['structural_score'] and a['coverage_confidence']==0 for a in result['modernization'])


def test_database_caller_resolution_uses_static_class_index():
    static=baseline()
    observed=[
        dict(session_id='s1',trace_id='t1',span_id='1',parent_span_id=None,timestamp='2026-01-01T00:00:00Z',end_timestamp='2026-01-01T00:00:00Z',duration_ms=1,class_name='app.a.A',method_name='orders',event_type='HTTP_SERVER',error=False,http_route='/orders',http_method='GET'),
        dict(session_id='s1',trace_id='t1',span_id='2',parent_span_id='1',timestamp='2026-01-01T00:00:00Z',end_timestamp='2026-01-01T00:00:00Z',duration_ms=1,class_name=None,method_name=None,event_type='DATABASE_CALL',error=False,database_system='postgresql',database_server='db.local',database_namespace='public',database_table='orders',database_operation='SELECT'),
    ]
    runtime=build(observed,static)
    coverage=calculate(static,runtime,observed)
    result=derive(static,runtime,coverage,observed,.6)
    assert result['database'][0]['caller']=='app.a.A'
    assert result['database'][0]['resource']=='orders'


def test_method_inventory_and_ambiguous_overloads():
    static=baseline()
    for c in static['classes']:
        c['methods']=[dict(name='work',signature='void work()',annotations=['org.springframework.web.bind.annotation.GetMapping'])]
    ev=events(span(1,'app.a.A'))
    coverage=calculate(static,build(ev,static),ev)
    assert coverage['methods']['percentage']==25
    assert coverage['entry_points']['percentage']==25
    static['classes'][1]['methods'].append(dict(name=None,signature='void inherited()',annotations=[]))
    assert calculate(static,build(ev,static),ev)['methods']['total']==4
    static['classes'][0]['methods'].append(dict(name='work',signature='void work(int)',annotations=[]))
    assert calculate(static,build(ev,static),ev)['methods']['observed']==0


def test_rotation_revokes_old_token_and_invalid_baseline(live):
    c=create(live); base='/api/v1/runtime-sessions/'+c['session']['id'];live.post(base+'/start')
    rotated=live.post(base+'/rotate-token').json()
    assert live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+c['token']}).status_code==401
    assert live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+rotated['token']}).status_code==200
    assert live.post(f'/api/v1/applications/{live.app_id}/runtime-sessions',json={'analysis_id':'missing','name':'bad'}).status_code==409


def test_runtime_token_expires_and_audit_records_scan_and_session_lifecycle(live):
    from datetime import timedelta
    from app.models import now
    client=live;created=create(client);sid=created['session']['id'];base='/api/v1/runtime-sessions/'+sid
    assert created['agent']['token_expires_at']
    assert client.post(base+'/start').status_code==200
    with client.app.state.sessions() as db:
        item=db.get(RuntimeSession,sid)
        item.settings=dict(item.settings,token_expires_at=(now()-timedelta(seconds=1)).isoformat())
        db.commit()
    rejected=client.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+created['token']})
    assert rejected.status_code==401
    records=client.get('/api/v1/security/audit').json()
    actions=[row.get('action') for row in records]
    assert actions.count('RUNTIME_WRITE')>=2


def test_retention_preserves_aggregate_and_blocks_expired_merge(live):
    from datetime import timedelta
    from app.models import now
    c=create(live);sid=c['session']['id'];base='/api/v1/runtime-sessions/'+sid;live.post(base+'/start')
    live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+c['token']})
    live.post(base+'/stop');before=live.get(base+'/evidence').json()
    with live.app.state.sessions() as db:
        item=db.get(RuntimeSession,sid);item.ended_at=now()-timedelta(hours=25);db.commit()
    assert live.post('/api/v1/runtime/retention/purge').json()['purged_sessions']>=1
    assert live.get(base+'/evidence').json()==before
    assert live.get(base+'/spans/'+'1'*32+'/'+f'{1:016x}').status_code==404
    second=create(live)['session']['id']
    assert live.get('/api/v1/applications/'+live.app_id+'/architecture/unified',params={'runtime_session_ids':sid+','+second}).status_code==409


def test_multi_session_union_and_graph_modes(live):
    ids=[]
    for spans in [(span(1,'app.a.A'),span(2,'app.b.B',1)),(span(1,'app.a.A'),span(3,'app.c.C',1))]:
        c=create(live);sid=c['session']['id'];ids.append(sid);base='/api/v1/runtime-sessions/'+sid
        live.post(base+'/start')
        live.post(base+'/v1/traces',json=payload(*spans),headers={'Authorization':'Bearer '+c['token']})
    url='/api/v1/applications/'+live.app_id+'/architecture/unified'
    selected={'runtime_session_ids':','.join(ids)}
    result=live.get(url,params=selected).json()
    assert result['coverage']['classes']['observed']==3
    assert result['coverage']['dependencies']['observed']==2
    for level in ('classes','packages','domains'):
        for kind in ('static','runtime','unified'):
            response=live.get(url+'/'+level,params=dict(selected,graph_kind=kind))
            assert response.status_code==200,response.text
            assert response.json()['nodes']
    runtime=live.get(url+'/classes',params=dict(selected,graph_kind='runtime')).json()
    assert len(runtime['edges'])==2
    assert all(e['call_count']==1 for e in runtime['edges'])
    static=live.get(url+'/classes',params=dict(selected,graph_kind='static')).json()
    assert len(static['edges'])==3
    assert all(e['evidence_type']=='STATIC' for e in static['edges'])


def test_body_limits_malformed_payload_and_empty_batches(live):
    c=create(live);base='/api/v1/runtime-sessions/'+c['session']['id'];live.post(base+'/start')
    headers={'Authorization':'Bearer '+c['token'],'Content-Type':'application/json'}
    assert live.post(base+'/v1/traces',content=b'{broken',headers=headers).status_code==400
    assert live.post(base+'/v1/traces',json={},headers=headers).status_code==200
    assert live.get(base).json()['agent_status']=='WAITING'
    live.app.state.config.runtime_max_body_bytes=100
    assert live.post(base+'/v1/traces',content=b'x'*101,headers=headers).status_code==413


def test_limits_endpoint_and_oversized_spans_are_visible_as_dropped(live):
    limits=live.get('/api/v1/limits').json()['limits']
    assert limits['max_classes_per_scan']==live.app.state.config.max_classes
    assert limits['runtime_max_span_size_bytes']==live.app.state.config.runtime_max_span_size_bytes
    c=create(live);base='/api/v1/runtime-sessions/'+c['session']['id'];live.post(base+'/start')
    live.app.state.config.runtime_max_span_size_bytes=100
    response=live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+c['token']})
    assert response.status_code==200 and response.json()['partialSuccess']['rejectedSpans']=='1'
    diag=live.get(base+'/diagnostics').json()
    assert diag['dropped_spans']==1 and diag['ingestion']['oversized_spans']==1


def test_expired_runtime_session_is_rejected_and_closed(live):
    from datetime import timedelta
    from app.models import now
    c=create(live);base='/api/v1/runtime-sessions/'+c['session']['id'];live.post(base+'/start')
    live.app.state.config.runtime_max_session_duration_hours=1
    with live.app.state.sessions() as db:
        item=db.get(RuntimeSession,c['session']['id']);item.started_at=now()-timedelta(hours=2);db.commit()
    response=live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers={'Authorization':'Bearer '+c['token']})
    assert response.status_code==409 and response.json()['detail']['limit']=='max_session_duration'
    assert live.get(base).json()['status']=='FAILED'


def test_agent_plan_uses_explicit_declared_method_names(live):
    with live.app.state.sessions() as db:
        run=db.get(AnalysisRun,live.run_id);static=copy.deepcopy(run.result)
        static['classes'][0]['annotations']=['org.springframework.stereotype.Controller']
        static['classes'][0]['methods']=[{'name':'work','signature':'void work()'},{'name':'<init>','signature':'void <init>()'},{'name':'lambda$work$0','signature':'void lambda$work$0()'}]
        run.result=static;db.commit()
    config=create(live)['agent']
    assert config['environment']['OTEL_INSTRUMENTATION_METHODS_INCLUDE']=='app.a.A[work]'
