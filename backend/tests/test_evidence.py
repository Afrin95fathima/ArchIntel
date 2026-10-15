"""Evidence intelligence contracts; runtime fixture reuses the existing pipeline."""
import copy,os
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import AnalysisRun,now
from app.runtime.models import RuntimeSession
from app.evidence.models import ArchitectureVersion,Projection
from app.evidence import projection
from app.evidence.builder import digest
from test_runtime import live,create as runtime_session,payload,span
from test_security import account,login


def capture(live,*spans):
    c=runtime_session(live);base='/api/v1/runtime-sessions/'+c['session']['id']
    live.post(base+'/start')
    if spans:assert live.post(base+'/v1/traces',json=payload(*spans),headers={'Authorization':'Bearer '+c['token']}).status_code==200
    assert live.post(base+'/stop').status_code==200
    return c['session']['id']


def make(live,sessions=None,**kwargs):
    body=dict(analysis_id=live.run_id,name='Evidence version',runtime_session_ids=sessions or [],**kwargs)
    response=live.post(f'/api/v1/applications/{live.app_id}/architecture-versions',json=body)
    assert response.status_code==201,response.text
    return response.json()


def test_idempotent_canonical_fusion_and_provenance(live):
    with live.app.state.sessions() as db:before=digest(db.get(AnalysisRun,live.run_id).result)
    sid=capture(live,span(1,'app.a.A'),span(2,'app.b.B',1),span(3,'app.d.D',2),span(4,'app.x.X'),span(5,'app.b.B',4))
    v=make(live,[sid]);assert make(live,[sid])['id']==v['id']
    base='/api/v1/architecture-versions/'+v['id']
    facts=live.get(base+'/facts').json()['items']
    assert {(f['source'],f['target']):f['classification'] for f in facts}=={('app.a.A','app.b.B'):'STATIC_AND_DYNAMIC',('app.a.A','app.c.C'):'STATIC_ONLY',('app.b.B','app.d.D'):'STATIC_AND_DYNAMIC',('runtime:app.x.X','app.b.B'):'DYNAMIC_ONLY'}
    for f in facts:
        proof=live.get(base+'/facts/'+f['id']+'/provenance');assert proof.status_code==200
        assert {e['id'] for e in proof.json()['evidence']}==set(f['evidence_ids'])
    assert live.get(base+'/facts?limit=201').status_code==422
    export=live.get(base+'/export').json();assert export['evidence'] and export['document']['graph']['edges']
    with live.app.state.sessions() as db:assert digest(db.get(AnalysisRun,live.run_id).result)==before


def test_preview_and_domain_review_never_mutate_static(live):
    with live.app.state.sessions() as db:static=copy.deepcopy(db.get(AnalysisRun,live.run_id).result)
    edits=[dict(id=d['id'],name=d['name']+' reviewed',classes=d['classes']) for d in static['domains']]
    url=f'/api/v1/applications/{live.app_id}/architecture-versions'
    body=dict(analysis_id=live.run_id,name='Reviewed',domain_edits=edits,review_reason='Architect review')
    preview=live.post(url+'/preview',json=body);assert preview.status_code==200,preview.text
    assert live.get(url).json()==[]
    v=live.post(url,json=body).json()
    assert v['fingerprint']==preview.json()['fingerprint']
    assert live.get('/api/v1/architecture-versions/'+v['id']+'/twin').json()['domains']==preview.json()['domains']
    assert any(e['kind']=='USER_CONFIRMED' for e in live.get('/api/v1/architecture-versions/'+v['id']+'/evidence').json()['items'])
    with live.app.state.sessions() as db:assert db.get(AnalysisRun,live.run_id).result==static
    edits[0]['classes']=[]
    assert live.post(url,json=body).status_code==422


def test_discovery_updates_are_audited_optimistic_and_not_coverage(live):
    v=make(live);base='/api/v1/architecture-versions/'+v['id']
    before=live.get(base+'/twin').json()['coverage']
    items=live.get(base+'/discovery').json()['items'];assert items
    item=items[0]
    response=live.post(base+'/discovery/'+item['id'],json=dict(state='EXERCISED',note='Ran a workflow; waiting for evidence',expected_revision=0))
    assert response.status_code==200,response.text
    assert response.json()['revision']==1
    assert live.post(base+'/discovery/'+item['id'],json=dict(state='DISMISSED',note='Stale update',expected_revision=0)).status_code==409
    assert live.get(base+'/twin').json()['coverage']==before


def test_active_cross_baseline_and_foreign_sessions_rejected(live):
    c=runtime_session(live)
    url=f'/api/v1/applications/{live.app_id}/architecture-versions'
    body=dict(analysis_id=live.run_id,name='Invalid',runtime_session_ids=[c['session']['id']])
    assert live.post(url,json=body).status_code==409
    body['runtime_session_ids']=['missing'];assert live.post(url,json=body).status_code==404
    body['analysis_id']='missing';body['runtime_session_ids']=[];assert live.post(url,json=body).status_code==404


def test_runtime_permission_and_tenant_isolation(live):
    sid=capture(live,span(1,'app.a.A'));v=make(live,[sid]);plain=make(live)
    account(live,permissions=['ANALYSIS_READ','ANALYSIS_WRITE']);reader=login(live)
    base='/api/v1/architecture-versions/'+v['id']
    for path in ('','/facts','/evidence','/twin','/graph','/discovery','/export'):assert reader.get(base+path).status_code==403
    assert reader.get('/api/v1/architecture-versions/'+plain['id']).status_code==200
    assert reader.post(f'/api/v1/applications/{live.app_id}/architecture-versions',json=dict(analysis_id=live.run_id,name='Denied',runtime_session_ids=[sid])).status_code==403
    assert live.post('/api/v1/security/workspaces',json=dict(name='Other',admin_username='other-owner',admin_password='other-owner-password')).status_code==201
    other=login(live,'other-owner','other-owner-password')
    for path in ('','/facts','/graph','/export'):assert other.get(base+path).status_code==404


def test_expired_sources_retained_without_fabricated_methods(live):
    sid=capture(live,span(1,'app.a.A'),span(2,'app.b.B',1));v=make(live,[sid]);base='/api/v1/architecture-versions/'+v['id']
    frozen=live.get(base+'/export').json()
    with live.app.state.sessions() as db:
        item=db.get(RuntimeSession,sid);item.ended_at=now()-timedelta(hours=25);db.commit()
    live.post('/api/v1/runtime/retention/purge')
    assert live.get(base+'/export').json()==frozen
    fact=live.get(base+'/facts?classification=STATIC_AND_DYNAMIC').json()['items'][0]
    proof=live.get(base+'/facts/'+fact['id']+'/provenance').json()
    assert any(r['status']=='EXPIRED_OR_UNAVAILABLE' for e in proof['evidence'] for r in e['resolved_references'])
    after=make(live,[sid]);assert after['id']!=v['id']
    assert live.get('/api/v1/architecture-versions/'+after['id']+'/twin').json()['coverage']['methods']['status']=='UNAVAILABLE'


def test_observation_comparison_is_baseline_scoped(live):
    a=make(live,[capture(live,span(1,'app.a.A'))])
    b=make(live,[capture(live,span(1,'app.a.A'),span(2,'app.b.B',1))],parent_id=a['id'])
    response=live.get('/api/v1/architecture-versions/'+a['id']+'/compare/'+b['id'])
    assert response.status_code==200 and response.json()['percentage_point_delta']['classes']==25


def test_projection_failure_preserves_canonical_and_retries(live,monkeypatch):
    v=make(live);base='/api/v1/architecture-versions/'+v['id'];before=live.get(base+'/export').json()
    def fail(*args):raise ConnectionError('private endpoint details')
    monkeypatch.setattr(projection,'apply',fail)
    result=live.post(base+'/projection/rebuild').json();assert result['state']=='FAILED' and result['error_code']=='ConnectionError'
    assert 'private endpoint' not in str(result)
    assert live.get(base+'/export').json()==before
    assert live.get(base+'/graph').status_code==503
    monkeypatch.setattr(projection,'apply',lambda *args:None)
    assert live.post(base+'/projection/rebuild').json()['attempts']==2


@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_GRAPH_TESTS')!='1',reason='Requires isolated persistent Neo4j service')
def test_real_neo4j_replay_scope_staleness_and_recovery(live):
    from app.config import ROOT
    config=live.app.state.config
    config.knowledge_graph_enabled=True;config.knowledge_graph_password_file=ROOT/'.data/knowledge-graph/password.key'
    a=make(live);b=make(live,[capture(live,span(1,'app.a.A'),span(2,'app.b.B',1))])
    ids=[a['id'],b['id']]
    try:
        for vid in ids:
            response=live.post('/api/v1/architecture-versions/'+vid+'/projection/rebuild');assert response.json()['state']=='APPLIED',response.text
        base='/api/v1/architecture-versions/'+a['id']
        before=live.get(base+'/graph?limit=500').json();assert before['projection']=='CURRENT'
        assert live.post(base+'/projection/rebuild').json()['state']=='APPLIED'
        assert live.get(base+'/graph?limit=500').json()==before
        foreign=live.get('/api/v1/architecture-versions/'+b['id']+'/graph?limit=500').json()['nodes'][0]['id']
        assert live.get(base+'/graph',params={'root':foreign}).json()['nodes']==[]
        with projection.connect(config) as driver,driver.session() as neo:
            neo.run('MATCH (p:ArchIntelProjection {scope:$scope}) SET p.content_hash="stale"',scope='local:'+a['id']).consume()
        assert live.get(base+'/graph').status_code==409
        assert live.post(base+'/projection/rebuild').json()['state']=='APPLIED'
        assert live.get(base+'/graph?limit=500').json()==before
    finally:
        with projection.connect(config) as driver,driver.session() as neo:
            for vid in ids:
                neo.run('MATCH (n:ArchIntelEntity {scope:$scope}) DETACH DELETE n',scope='local:'+vid).consume()
                neo.run('MATCH (n:ArchIntelProjection {scope:$scope}) DELETE n',scope='local:'+vid).consume()

@pytest.mark.skipif(os.getenv('ARCHINTEL_RUN_POSTGRES_TESTS')!='1' or os.getenv('ARCHINTEL_RUN_GRAPH_TESTS')!='1',reason='Requires prepared PostgreSQL, Neo4j and real PetClinic capture')
def test_postgres_real_petclinic_evidence_restart_and_graph_outage(tmp_path):
    import json,sqlite3,hashlib,secrets
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.config import Settings,ROOT
    from app.db.session import build_engine
    from app.main import create_app
    from app.models import Project,Application,Artifact
    from app.runtime.models import RuntimeEvent
    from security_helpers import sign_in_owner
    report=json.loads((ROOT/'docs/phase3-runtime-validation.json').read_text())
    source=None
    for path in (ROOT/'.data').glob('phase3-real-java-*/runtime.db'):
        with sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT result,settings FROM runtime_sessions WHERE id=?',(report['session_id'],)).fetchone()
            if row:
                static=json.loads(db.execute('SELECT result FROM analysis_runs WHERE id=?',(report['analysis_id'],)).fetchone()[0])
                captured=json.loads(row[0]);options=json.loads(row[1]);spans=[json.loads(r[0]) for r in db.execute('SELECT data FROM runtime_events WHERE session_id=?',(report['session_id'],))]
                source=path;break
    assert source and len(spans)==report['span_count'],'Run scripts/validate_phase3_runtime.py first.'
    base=Settings();engine=build_engine(base);schema='phase4_validation_'+uuid4().hex;version_ids=[]
    with engine.begin() as db:db.execute(text('CREATE SCHEMA '+schema))
    url=make_url(base.database_url).update_query_dict({'options':'-csearch_path='+schema})
    settings=Settings(_env_file=None,database_url=url.render_as_string(hide_password=False),data_dir=tmp_path,allowed_hosts=['testserver'],knowledge_graph_enabled=True,knowledge_graph_password_file=ROOT/'.data/knowledge-graph/password.key')
    try:
        with TestClient(create_app(settings)) as browser:
            sign_in_owner(browser)
            with browser.app.state.sessions() as db:
                p=Project(name='Isolated Phase 4 real capture');db.add(p);db.flush()
                a=Application(name='Real PetClinic evidence',project_id=p.id);db.add(a);db.flush()
                f=Artifact(application_id=a.id,filename='petclinic.jar',path='retained sample capture',sha256=report['artifact_sha256'],size=1);db.add(f);db.flush()
                r=AnalysisRun(application_id=a.id,artifact_id=f.id,status='COMPLETED',result=static);db.add(r);db.flush()
                session=RuntimeSession(application_id=a.id,analysis_id=r.id,name='Imported real Java capture',environment='VALIDATION',status='COMPLETED',token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),span_count=len(spans),trace_count=report['trace_count'],ended_at=now(),settings=options);db.add(session);db.flush()
                replacements={report['session_id']:session.id,report['analysis_id']:r.id,report['application_id']:a.id}
                def translate(value):
                    if isinstance(value,str):return replacements.get(value,value)
                    if isinstance(value,list):return [translate(x) for x in value]
                    if isinstance(value,dict):return {k:translate(v) for k,v in value.items()}
                    return value
                session.result=translate(captured)
                for event in spans:
                    data=translate(event);db.add(RuntimeEvent(session_id=session.id,trace_id=data['trace_id'],span_id=data['span_id'],data=data))
                db.commit();browser.app_id=a.id;browser.run_id=r.id;sid=session.id
            v=make(browser,[sid]);version_ids.append(v['id']);path='/api/v1/architecture-versions/'+v['id']
            export=browser.get(path+'/export').json()
            assert export['document']['coverage']['classes']['observed']==11
            assert export['document']['coverage']['methods']['observed']==26
            assert {f['classification'] for f in export['facts']}=={'STATIC_ONLY','STATIC_AND_DYNAMIC','DYNAMIC_ONLY'}
            assert browser.post(path+'/projection/rebuild').json()['state']=='APPLIED'
            graph=browser.get(path+'/graph?limit=500').json();assert graph['projection']=='CURRENT'
            settings.knowledge_graph_uri='bolt://127.0.0.1:17999'
            assert browser.get(path+'/graph').status_code==503
            assert browser.get(path+'/export').json()==export
            settings.knowledge_graph_uri='bolt://127.0.0.1:17687'
            assert browser.post(path+'/projection/rebuild').json()['state']=='APPLIED'
            assert browser.get(path+'/graph?limit=500').json()==graph
            with browser.app.state.sessions() as db:assert db.get(AnalysisRun,browser.run_id).result==static
        with TestClient(create_app(settings)) as restarted:
            restarted.headers['X-ArchIntel-Request']='1'
            response=restarted.post('/api/v1/security/login',json={'username':'test-owner','password':'test-owner-password-2026'});assert response.status_code==200
            assert restarted.get(path+'/export').json()==export
            assert restarted.get(path+'/graph?limit=500').json()==graph
        result=dict(verified_at=now().isoformat(),source='Real Phase 3 Java-agent PetClinic capture',isolation='Temporary PostgreSQL schema and test-owned Neo4j version scope',source_spans=len(spans),source_traces=report['trace_count'],static_unchanged=True,restart_export_unchanged=True,graph_outage_canonical_available=True,rebuild_graph_unchanged=True,
                    version_id=v['id'],facts=len(export['facts']),evidence=len(export['evidence']),graph_nodes=graph['total_nodes'],graph_relationships=graph['total_edges'],coverage=export['document']['coverage'])
        (ROOT/'docs/phase4-integration-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    finally:
        with projection.connect(settings) as driver,driver.session() as neo:
            for vid in version_ids:
                neo.run('MATCH (n:ArchIntelEntity {scope:$scope}) DETACH DELETE n',scope='local:'+vid).consume()
                neo.run('MATCH (n:ArchIntelProjection {scope:$scope}) DELETE n',scope='local:'+vid).consume()
        with engine.begin() as db:db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        engine.dispose()

@pytest.mark.parametrize('uri',['bolt://remote.example:7687','neo4j://127.0.0.1:7687','bolt://user:pass@127.0.0.1:7687','bolt://127.0.0.1:7687/?query=1'])
def test_graph_destination_rejects_remote_routing_and_embedded_secrets(uri):
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):Settings(_env_file=None,knowledge_graph_uri=uri)


def test_guided_entry_scheduler_consumer_gaps_follow_actual_method_evidence(live):
    with live.app.state.sessions() as db:
        run=db.get(AnalysisRun,live.run_id);data=copy.deepcopy(run.result)
        for c,annotation in zip(data['classes'],['GetMapping','Scheduled','KafkaListener','']):
            c['methods']=[dict(name='work',signature='void work()',annotations=[annotation] if annotation else [])]
        run.result=data;db.commit()
    first=make(live)
    initial=live.get('/api/v1/architecture-versions/'+first['id']+'/discovery').json()['items']
    assert {'ENTRY_POINT','SCHEDULED_JOB','MESSAGE_CONSUMER'} <= {d['kind'] for d in initial}
    assert [d['priority'] for d in initial]==sorted(d['priority'] for d in initial)
    sid=capture(live,span(1,'app.a.A'));second=make(live,[sid])
    later=live.get('/api/v1/architecture-versions/'+second['id']+'/discovery').json()['items']
    assert 'ENTRY_POINT' not in {d['kind'] for d in later}
    assert {'SCHEDULED_JOB','MESSAGE_CONSUMER'} <= {d['kind'] for d in later}
    with live.app.state.sessions() as db:
        item=db.get(RuntimeSession,sid);item.ended_at=now()-timedelta(hours=25);db.commit()
    live.post('/api/v1/runtime/retention/purge');third=make(live,[sid])
    unknown=live.get('/api/v1/architecture-versions/'+third['id']+'/discovery').json()['items']
    assert all(d['gap_state']=='UNKNOWN' for d in unknown if d['kind'] in ('ENTRY_POINT','SCHEDULED_JOB','MESSAGE_CONSUMER'))


def test_version_body_limit_and_unrecognized_fields(live):
    url=f'/api/v1/applications/{live.app_id}/architecture-versions'
    response=live.post(url,content=b' '*((2*1024*1024)+1),headers={'Content-Type':'application/json'})
    assert response.status_code==413
    assert live.post(url,json=dict(analysis_id=live.run_id,name='Invalid',cypher='MATCH (n) RETURN n')).status_code==422
