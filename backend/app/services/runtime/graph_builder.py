from collections import defaultdict
import math
from app.services.graph import stable_id
from .mapping import map_class


def build(events: list[dict], static: dict) -> dict:
    classes = {c['id']:c for c in static['classes']}
    nodes, mappings, edges = {}, {}, defaultdict(list)
    indexed = {(e['session_id'],e['trace_id'],e['span_id']):e for e in events}
    def node(event):
        raw = event.get('class_name')
        mapping = map_class(raw,classes)
        # Missing class spans are resources/framework observations, never made-up classes.
        identity = mapping['static_id'] or ('runtime:'+raw if raw else stable_id('resource',str((event['event_type'],event.get('database_system'),event.get('database_server'),event.get('database_namespace'),event.get('database_table'),event.get('service_name') or event['session_id'],event.get('http_route'),event.get('http_method'),event.get('messaging_system'),event.get('messaging_destination')))))
        mappings[raw or identity] = dict(mapping,runtime_node_id=identity)
        cls = classes.get(mapping['static_id'],{})
        nodes[identity] = dict(id=identity,name=raw or event.get('http_route') or event.get('database_table') or event['event_type'],
            static_id=mapping['static_id'],mapping_state=mapping['state'],package_name=cls.get('package_name'),domain_id=cls.get('domain_id'),
            node_type='CLASS' if raw else 'RESOURCE')
        return identity
    for e in events: node(e)
    # Malformed span-parent cycles must not manufacture architecture dependencies.
    invalid=set();visited=set()
    for key in indexed:
        path=[];positions={};current=key
        while current in indexed and current not in visited:
            if current in positions:
                invalid.update(path[positions[current]:]);break
            positions[current]=len(path);path.append(current)
            parent=indexed[current].get('parent_span_id')
            current=(current[0],current[1],parent)
        visited.update(path)
    missing = 0
    for e in events:
        if not e.get('parent_span_id'): continue
        if (e['session_id'],e['trace_id'],e['span_id']) in invalid:continue
        parent = indexed.get((e['session_id'],e['trace_id'],e['parent_span_id']))
        if not parent:
            missing += 1
            continue
        source,target = node(parent),node(e)
        if source != target: edges[(source,target,e['event_type'])].append(e)
    result = []
    for (s,t,kind), group in sorted(edges.items()):
        durations = sorted(e['duration_ms'] for e in group)
        count = len(group)
        result.append(dict(id=stable_id('runtime-edge',str((s,t,kind))),source=s,target=t,dependency_type=kind,
            call_count=count,trace_count=len({(e['session_id'],e['trace_id']) for e in group}),
            total_duration_ms=sum(durations),avg_duration_ms=sum(durations)/count,p95_duration_ms=durations[math.ceil(.95*count)-1],
            first_seen=min(e['timestamp'] for e in group),last_seen=max(e['end_timestamp'] for e in group),
            error_count=sum(bool(e['error']) for e in group),error_rate=sum(bool(e['error']) for e in group)/count,
            evidence=[dict(session_id=e['session_id'],trace_id=e['trace_id'],span_id=e['span_id']) for e in group[:20]],evidence_truncated=count>20))
    return dict(nodes=[nodes[k] for k in sorted(nodes)],edges=result,mappings=[mappings[k] for k in sorted(mappings)],missing_parent_count=missing,invalid_parent_count=len(invalid))


def project(graph: dict, level: str, static: dict) -> dict:
    if level=='classes': return graph
    key = 'package_name' if level=='packages' else 'domain_id'
    names = {d['id']:d['name'] for d in static['domains']}
    translated, nodes = {}, {}
    for node in graph['nodes']:
        identity = node.get(key) or 'unresolved:'+node['id']
        translated[node['id']] = identity
        group=nodes.setdefault(identity,dict(id=identity,name=names.get(identity,identity),unresolved=identity.startswith('unresolved:'),evidence_types=[]))
        if node.get('evidence_type') and node['evidence_type'] not in group['evidence_types']:
            group['evidence_types'].append(node['evidence_type'])
        group['evidence_type']=group['evidence_types'][0] if len(group['evidence_types'])==1 else 'MIXED' if group['evidence_types'] else 'DYNAMIC_ONLY'
    edges = {}
    for edge in graph['edges']:
        source,target = translated[edge['source']],translated[edge['target']]
        if source==target: continue
        pair = (source,target,edge['dependency_type'])
        if pair not in edges:
            edges[pair] = dict(id=stable_id('projected',str(pair)),source=source,target=target,dependency_type=edge['dependency_type'],call_count=0,evidence=[])
        edges[pair]['call_count'] += edge.get('call_count',0)
        edges[pair]['evidence'] = (edges[pair]['evidence']+edge.get('evidence',[]))[:20]
        edges[pair].setdefault('evidence_types',[])
        if edge.get('evidence_type') and edge['evidence_type'] not in edges[pair]['evidence_types']: edges[pair]['evidence_types'].append(edge['evidence_type'])
    return dict(nodes=list(nodes.values()),edges=list(edges.values()),level=level)
