"""Phase 3 contracts: scope, exact identities, quality and recovery."""
import copy
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import AnalysisRun,now
from app.runtime.models import RuntimeSession,RuntimeEvent
from app.services.runtime import session_service as service
from app.services.runtime.mapping import method_descriptor
from app.services.runtime.instrumentation import build_plan, MAX_BYTES, MAX_CLASSES
from app.services.runtime.graph_builder import build
from app.services.runtime.coverage import calculate
from test_runtime import live,baseline,span,payload,events,create


def with_resource(data,service_name,sha='0'*64):
    data=copy.deepcopy(data)
    data['resourceSpans'][0]['resource']={'attributes':[{'key':k,'value':{'stringValue':v}} for k,v in
        {'service.name':service_name,'archintel.artifact.sha256':sha,'secret.resource':'must-not-survive'}.items()]}
    return data


@pytest.mark.parametrize('signature,expected',[
    ('void work()','()V'),('int work(java.lang.String[], int)','([Ljava/lang/String;I)I'),
    ('java.lang.String[][] work(long...)','([J)[[Ljava/lang/String;'),
    ('void work(String)',None),('void work(void)',None),('void[] work()',None)])
def test_signature_descriptor(signature,expected):
    assert method_descriptor({'signature':signature})==expected


def test_descriptor_overloads_and_invalid_descriptor_never_guess():
    static=baseline()
    for c in static['classes']:c['methods']=[]
    static['classes'][0]['methods']=[{'name':'work','signature':'void work()'},{'name':'work','signature':'void work(int)','annotations':['GetMapping']}]
    ev=events(span(1,'app.a.A$$SpringCGLIB$$0',extras={'code.method.descriptor':'(I)V'}))
    coverage=calculate(static,build(ev,static),ev)
    assert coverage['methods']['observed']==1 and coverage['entry_points']['observed']==1
    assert coverage['method_mapping_diagnostics']=={'EXACT_DESCRIPTOR':1}
    invalid=events(span(2,'app.a.A',extras={'code.method.descriptor':'invalid private text'}))
    assert calculate(static,build(invalid,static),invalid)['methods']['observed']==0
    ambiguous=events(span(3,'app.a.A'))
    assert calculate(static,build(ambiguous,static),ambiguous)['method_mapping_diagnostics']=={'AMBIGUOUS':1}


def test_plan_scope_boundaries_exclusions_annotations_and_limits():
    static=baseline()
    for c in static['classes']:c['methods']=[{'name':'work','signature':'void work()','annotations':['GetMapping']}]
    settings={'include_packages':['app.a'],'exclude_packages':['app.b'],'mode':'BOUNDARY'}
    plan=build_plan(static,settings)
    assert [c['class_name'] for c in plan['classes']]==['app.a.A']
    assert build_plan(dict(static,classes=list(reversed(static['classes']))),settings)==plan
    assert not build_plan(static,dict(settings,include_packages=['app.ab']))['classes']
    assert not build_plan(static,dict(settings,exclude_packages=['app.a']))['classes']
    many=dict(static,classes=[dict(static['classes'][0],id='app.a.Class'+str(i)) for i in range(MAX_CLASSES+50)])
    bounded=build_plan(many,settings)
    assert len(bounded['classes'])==MAX_CLASSES and bounded['omissions']['PLAN_BUDGET']==50
    assert bounded['encoded_bytes']<=MAX_BYTES


def test_a_later_coverage_pass_skips_classes_an_earlier_pass_traced():
    static=baseline()
    for c in static['classes']:c['methods']=[{'name':'work','signature':'void work()','annotations':[]}]
    first=build_plan(static,{'mode':'DEEP'})
    second=build_plan(static,{'mode':'DEEP','exclude_classes':[first['classes'][0]['class_name']]})
    assert first['classes'][0]['class_name'] not in {c['class_name'] for c in second['classes']}
    assert second['omissions']['TRACED_IN_EARLIER_PASS']==1 and len(second['classes'])==len(first['classes'])-1


def test_plan_budget_goes_to_entry_points_and_components_before_alphabetical_order():
    static=baseline()
    plain=[dict(id=f'app.a.Aaa{i:03}',annotations=[],methods=[{'name':'work','signature':'void work()','annotations':[]}],metrics={'fan_in':0,'fan_out':0}) for i in range(MAX_CLASSES)]
    resource=dict(id='app.z.ZResource',annotations=[],methods=[{'name':'list','signature':'java.util.List list()','annotations':['javax.ws.rs.GET']}],metrics={})
    component=dict(id='app.z.ZDao',annotations=['javax.inject.Named'],methods=[{'name':'find','signature':'void find()','annotations':[]}],metrics={})
    plan=build_plan(dict(static,classes=plain+[resource,component]),{'mode':'DEEP'})
    chosen={c['class_name']:c['reason'] for c in plan['classes']}
    assert chosen['app.z.ZResource']=='Annotated entry point' and chosen['app.z.ZDao']=='Annotated application boundary'
    assert len(plan['classes'])==MAX_CLASSES and plan['omissions']['PLAN_BUDGET']==2


def test_jax_rs_entry_points_are_counted_and_selected_for_instrumentation():
    static=baseline()
    for c in static['classes']: c['methods']=[]
    static['classes'][0]['methods']=[
        {'name':'work','signature':'void work()','annotations':['javax.ws.rs.GET']},
        {'name':'createItem','signature':'void createItem()','annotations':['javax.ws.rs.POST']},
        {'name':'helper','signature':'void helper()','annotations':[]},
    ]
    plan=build_plan(static,{'mode':'BOUNDARY'})
    assert plan['classes'][0]['class_name']=='app.a.A'
    assert plan['classes'][0]['reason']=='Annotated entry point'
    assert {'work','createItem','helper'} <= set(plan['classes'][0]['methods'].split(','))

    observed=events(span(1,'app.a.A',extras={'code.method.descriptor':'()V'}))
    coverage=calculate(static,build(observed,static),observed)
    assert coverage['entry_points']['total']==2
    assert coverage['entry_points']['observed']==1
    assert coverage['entry_points']['percentage']==50


def test_preview_saved_plan_and_strict_binding_are_atomic(live):
    body={'analysis_id':live.run_id,'name':'Bound','binding_mode':'STRICT'}
    url=f'/api/v1/applications/{live.app_id}/runtime-sessions'
    preview=live.post(url+'/plan',json=body);assert preview.status_code==200
    assert live.get(url).json()==[]
    created=live.post(url,json=body).json();base='/api/v1/runtime-sessions/'+created['session']['id']
    assert created['agent']['plan']==preview.json()
    live.post(base+'/start');headers={'Authorization':'Bearer '+created['token']}
    raw=payload(span(1,'app.a.A'))
    assert live.post(base+'/v1/traces',json=raw,headers=headers).status_code==409
    valid=with_resource(raw,created['agent']['environment']['OTEL_SERVICE_NAME'])
    bad=with_resource(raw,'another-service')
    mixed={'resourceSpans':valid['resourceSpans']+bad['resourceSpans']}
    assert live.post(base+'/v1/traces',json=mixed,headers=headers).status_code==409
    assert live.get(base).json()['span_count']==0
    assert live.post(base+'/v1/traces',json=valid,headers=headers).status_code==200
    report=live.get(base+'/evidence').json()
    assert report['quality']['declared_match_spans']==1
    assert report['quality']['binding_rejected_spans']==3
    assert 'must-not-survive' not in live.get(base+'/spans/'+'1'*32+'/0000000000000001').text
    with live.app.state.sessions() as db:
        run=db.get(AnalysisRun,live.run_id);run.result=dict(run.result,cycles=[]);db.commit()
    assert live.get(base+'/agent-config').json()['plan']==preview.json()
    assert 'Bearer' not in live.get(base+'/diagnostics').text
    assert live.post(url,json=dict(body,include_packages=['app;malicious'])).status_code==422


def test_late_parent_duplicates_conflicts_and_frozen_evidence(live):
    c=create(live);base='/api/v1/runtime-sessions/'+c['session']['id'];live.post(base+'/start')
    headers={'Authorization':'Bearer '+c['token']}
    child=payload(span(2,'app.b.B',1))
    assert live.post(base+'/v1/traces',json=child,headers=headers).status_code==200
    assert live.get(base+'/evidence').json()['quality']['missing_parents']==1
    live.post(base+'/v1/traces',json=child,headers=headers)
    live.post(base+'/v1/traces',json=payload(span(2,'app.c.C',1)),headers=headers)
    live.post(base+'/v1/traces',json=payload(span(1,'app.a.A')),headers=headers)
    quality=live.get(base+'/evidence').json()['quality']
    assert quality['missing_parents']==0 and quality['duplicate_spans']==2 and quality['conflicting_spans']==1
    assert live.get(base+'/spans/'+'1'*32+'/0000000000000002').json()['class_name']=='app.b.B'
    live.post(base+'/stop');frozen=live.get(base+'/evidence').json()
    assert live.post(base+'/v1/traces',json=child,headers=headers).status_code==409
    assert live.get(base+'/evidence').json()==frozen


def test_resources_are_server_namespace_and_service_scoped_and_cycles_ignored():
    rows=events(span(1,'app.a.A'),span(2,None,1,extras={'db.system':'postgresql','db.collection.name':'orders','server.address':'db1','db.namespace':'a'}),span(3,None,1,extras={'db.system':'postgresql','db.collection.name':'orders','server.address':'db2','db.namespace':'a'}))
    assert len([n for n in build(rows,baseline())['nodes'] if n['node_type']=='RESOURCE'])==2
    cyclic=events(span(1,'app.a.A',2),span(2,'app.b.B',1))
    graph=build(cyclic,baseline());assert graph['invalid_parent_count']==2 and not graph['edges']
    with pytest.raises(ValueError):events(span(1,'app.a.A',1))


def test_recovery_and_retention_idempotence_with_failed_session(live,monkeypatch):
    bad=create(live)['session']['id'];good=create(live)['session']['id'];active=create(live)['session']['id']
    with live.app.state.sessions() as db:
        db.get(RuntimeSession,bad).status='PROCESSING'
        db.get(RuntimeSession,active).status='RUNNING'
        db.commit();service.recover(db)
        assert db.get(RuntimeSession,bad).status=='FAILED'
        assert db.get(RuntimeSession,active).status=='RUNNING'
        for sid in (bad,good):
            item=db.get(RuntimeSession,sid);item.status='RUNNING';item.started_at=now()-timedelta(hours=25)
        db.commit()
        original=service.result
        def faulty(database,sessions,settings):
            if sessions[0].id==bad:raise ValueError('Report failed')
            return original(database,sessions,settings)
        monkeypatch.setattr(service,'result',faulty)
        service.purge(db,live.app.state.config)
        assert db.get(RuntimeSession,bad).status=='FAILED'
        assert db.get(RuntimeSession,good).status=='COMPLETED'
        for sid in (bad,good):db.get(RuntimeSession,sid).ended_at=now()-timedelta(hours=25)
        db.commit()
        assert service.purge(db,live.app.state.config)==2
        assert service.purge(db,live.app.state.config)==0
        assert db.get(RuntimeSession,good).result
