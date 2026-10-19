import networkx as nx
import pytest
from app.config import Settings
from app.services.graph import build_graphs
from app.services.cycles import detect_cycles
from app.services.metrics import calculate_metrics, percentile
from app.services.engine import analyze
from app.services.assistant import answer
from helpers import cls,edge,sample


def config():
    return Settings(_env_file=None,database_url='sqlite:///:memory:')


def test_filters_external_but_preserves_evidence_and_distinct_graphs():
    classes=[cls('app.a.A'),cls('app.b.B'),cls('java.lang.Object')]
    edges=[edge('app.a.A','app.b.B'),edge('app.a.A','app.b.B','FIELD_TYPE'),edge('app.a.A','java.lang.Object')]
    g=build_graphs(classes,edges,['java.'])
    assert g['graph'].number_of_nodes()==2
    assert g['graph'].number_of_edges()==1
    assert len(g['edges'])==2 and len(g['external_edges'])==1
    assert g['packages']['app.a']['app.b']['weight']==1


def test_package_cycle_does_not_imply_class_cycle():
    classes=[cls(n) for n in ['a.A','a.D','b.B','b.C']]
    g=build_graphs(classes,[edge('a.A','b.B'),edge('b.C','a.D')],[])
    assert detect_cycles(g['graph'],'CLASS')['scc_count']==0
    assert detect_cycles(g['packages'],'PACKAGE')['scc_count']==1


def test_scc_complete_and_enumeration_capped():
    graph=nx.complete_graph(8,create_using=nx.DiGraph)
    result=detect_cycles(graph,'CLASS',max_length=4,cap=3)
    assert result['scc_count']==1
    c=result['items'][0]
    assert len(c['sample_cycles'])==3 and c['truncated']
    assert all(len(p)<=4 for p in c['sample_cycles'])
    assert len(c['members'])==8


def test_large_scc_does_not_enumerate(monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError('Enumeration must not run')
    monkeypatch.setattr(nx,'simple_cycles',forbidden)
    graph=nx.DiGraph((str(i),str((i+1)%100)) for i in range(100))
    c=detect_cycles(graph,'CLASS')['items'][0]
    assert c['issue_type']=='LARGE_CYCLIC_CLUSTER' and c['node_count']==100
    assert c['internal_edge_count']==100 and c['sample_cycles']==[]


def test_cycle_longer_than_limit_still_reports_complete_cluster():
    graph=nx.DiGraph((str(i),str((i+1)%10)) for i in range(10))
    result=detect_cycles(graph,'CLASS',max_length=8)
    assert result['scc_count']==1 and result['items'][0]['sample_cycles']==[]


def test_metrics_hand_computed_and_abstract_interface_not_double_counted():
    classes=[cls('a.A',abstract=True,interface=True),cls('a.B'),cls('b.C'),cls('b.D'),cls('z.Alone')]
    edges=[edge('a.A','b.C'),edge('a.B','b.C'),edge('b.D','a.B')]
    g=build_graphs(classes,edges,[])
    _,metrics,_=calculate_metrics(g['classes'],g['graph'])
    a=next(m for m in metrics if m['entity_id']=='a')
    assert (a['Ca'],a['Ce'],a['I'],a['A'],a['D'])==(1,1,.5,.5,0)
    z=next(m for m in metrics if m['entity_id']=='z')
    assert z['isolated'] and z['I']==0 and z['D']==1


def test_percentile_interpolation():
    assert percentile([0,10,20,30,40],.95)==pytest.approx(38)
    assert percentile([],.95)==0


def test_god_class_requires_multiple_relative_signals():
    classes=[cls(f'app.p.C{i}',methods=2,fields=1) for i in range(20)]+[cls('app.p.Hub',methods=100,fields=50)]
    result=analyze(classes,[edge('app.p.Hub',f'app.p.C{i}') for i in range(20)],config())
    gods=[i for i in result['issues'] if i['issue_type']=='GOD_CLASS']
    assert len(gods)==1 and gods[0]['entity_id']=='app.p.Hub'
    assert 'p95' in gods[0]['evidence']['method_count']
    classes[-1]['field_count']=1
    result=analyze(classes,[],config())
    assert not any(i['issue_type']=='GOD_CLASS' for i in result['issues'])


def test_cross_domain_ratio_domains_deterministic_and_cycle_classification():
    nodes,edges=sample()
    first=analyze(nodes,edges,config())
    second=analyze(nodes,edges,config())
    assert first==second
    # The evidence-based algorithm now groups all of com.shop.* into one domain.
    assert first['summary']['domain_count']==1
    domain=first['domains'][0]
    assert domain['name']=='Com'
    assert domain['metrics']['cross_domain_ratio']==0.0
    assert domain['database']['status']=='STRUCTURAL_SIGNALS'
    assert any(c['severity']=='HIGH' for c in first['cycles'])


def test_unknown_database_honest_and_scores_explainable():
    nodes,edges=sample()
    result=analyze(nodes,edges,config())
    assert result['summary']['domain_count']==1
    a=result['modernization'][0]
    assert a['domain_name']=='Com'
    assert a['database_coupling']=='STRUCTURAL_SIGNALS'
    assert 0<=a['readiness_score']<=100
    assert a['readiness_score']==pytest.approx(round(sum(a['component_scores'][k]*w for k,w in a['weights'].items()),1),abs=.1)


def test_sequence_dependency_first_and_cycle_group():
    nodes=[cls('app.orders.Order'),cls('app.payment.Payment'),cls('app.notifications.Notifier')]
    edges=[edge('app.orders.Order','app.payment.Payment'),edge('app.payment.Payment','app.notifications.Notifier')]
    result=analyze(nodes,edges,config())
    assert [a['domain_name'] for a in result['modernization']]==['App']
    # The cycle keeps the coupled classes in a single domain / wave.
    cyclic=analyze(nodes,edges+[edge('app.payment.Payment','app.orders.Order')],config())
    assert [a['domain_name'] for a in cyclic['modernization']]==['App']
    assert all(c['issue_type']=='CIRCULAR_DEPENDENCY' for c in cyclic['cycles'])


def test_shared_repository_and_entity_mapping():
    nodes=[cls('app.shared.Repo',annotations=['org.springframework.stereotype.Repository']),cls('app.shared.Entity',annotations=['jakarta.persistence.Entity']),cls('app.a.Service'),cls('app.b.Service')]
    edges=[edge('app.a.Service','app.shared.Repo'),edge('app.b.Service','app.shared.Repo'),edge('app.shared.Repo','app.shared.Entity')]
    result=analyze(nodes,edges,config())
    # Both services share the repository, so they resolve to a single domain.
    assert result['summary']['domain_count']==1
    domain=result['domains'][0]
    assert domain['database']['repository_entities']==[{'repository':'app.shared.Repo','entities':['app.shared.Entity']}]
    assert domain['database']['entities']==['app.shared.Entity']
    assert domain['database']['repositories']==['app.shared.Repo']


def test_no_edges_and_one_class_are_valid():
    result=analyze([cls('Only')],[],config())
    assert result['summary']['class_count']==1
    assert result['modernization'][0]['component_scores']['cohesion']==50


def test_assistant_abstains_and_cites_only_context():
    nodes,edges=sample()
    result=analyze(nodes,edges,config())
    response=answer(result,'Why is Payment risky?',None,config())
    assert response.facts and {f['id'] for f in response.facts}=={s['id'] for s in response.sources}
    assert not answer(result,'What is tomorrow weather?',None,config()).facts
    assert not answer(result,'Explain architecture','missing',config()).facts


def test_invalid_weights_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None,readiness_weights={'cohesion':1})
