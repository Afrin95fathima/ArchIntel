import networkx as nx
from community import community_louvain

from app.services.domains import _community_graph


def test_lightweight_community_graph_preserves_louvain_topology_and_seeded_result():
    graph = nx.DiGraph()
    graph.add_nodes_from((f'class{i}', {'large_metadata': 'x' * 1000}) for i in range(12))
    graph.add_weighted_edges_from([
        ('class0', 'class1', 3), ('class1', 'class0', 5),
        ('class1', 'class2', 1), ('class2', 'class3', 2),
        ('class3', 'class4', 1), ('class4', 'class2', 4),
        ('class5', 'class6', 2), ('class6', 'class7', 2),
        ('class7', 'class5', 2), ('class8', 'class9', 1),
    ])

    original = graph.to_undirected()
    lightweight = _community_graph(graph)
    assert list(original.nodes) == list(lightweight.nodes)
    assert list(original.edges(data='weight')) == list(lightweight.edges(data='weight'))
    assert community_louvain.best_partition(original, random_state=42, weight='weight') == \
        community_louvain.best_partition(lightweight, random_state=42, weight='weight')
    assert all('large_metadata' not in data for _, data in lightweight.nodes(data=True))
