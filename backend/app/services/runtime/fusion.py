from collections import defaultdict
from app.services.graph import stable_id


def fuse(static, runtime):
    nodes = {c['id']:dict(c,evidence_type='STATIC_ONLY') for c in static['classes']}
    for node in runtime['nodes']:
        previous = nodes.get(node['id'])
        nodes[node['id']] = dict(previous or {},**node,evidence_type='STATIC_AND_DYNAMIC' if previous else 'DYNAMIC_ONLY')
    # Fusion is class-pair level, retaining all underlying static edge types.
    pairs = {}
    for edge in static['edges']:
        pair = (edge['source'],edge['target'])
        item = pairs.setdefault(pair,dict(id=stable_id('unified',str(pair)),source=pair[0],target=pair[1],
            dependency_type='CLASS_DEPENDENCY',static_types=[],static_edge_ids=[],call_count=0,evidence=[],evidence_type='STATIC_ONLY'))
        item['static_types'].append(edge['dependency_type'])
        item['static_edge_ids'].append(edge['id'])
    for edge in runtime['edges']:
        pair = (edge['source'],edge['target'])
        item = pairs.setdefault(pair,dict(id=stable_id('unified',str(pair)),source=pair[0],target=pair[1],
            dependency_type='CLASS_DEPENDENCY',static_types=[],static_edge_ids=[],call_count=0,evidence=[],evidence_type='DYNAMIC_ONLY'))
        item['evidence_type'] = 'STATIC_AND_DYNAMIC' if item['static_types'] else 'DYNAMIC_ONLY'
        item['call_count'] += edge['call_count']
        item['evidence'] = (item['evidence']+edge['evidence'])[:20]
    return dict(nodes=list(nodes.values()),edges=list(pairs.values()),level='classes')
