"""SCC-first cycle analysis, with strictly bounded enumeration."""
from itertools import islice
import networkx as nx
import re
from app.services.graph import stable_id


def detect_cycles(graph: nx.DiGraph, level: str, max_length: int = 8, cap: int = 20, large: int = 50) -> dict:
    findings, scc_count = [], 0
    # Synthetic/anonymous/inner classes belong to their declaring outer type for
    # architecture-level cycle analysis. A reference between Outer and Outer$1
    # must not create a reported architecture cycle by itself.
    outer = lambda name: re.sub(r'\$.*$', '', str(name))
    collapsed = nx.DiGraph()
    collapsed.add_nodes_from(sorted({outer(n) for n in graph.nodes}))
    collapsed.add_edges_from((outer(s), outer(t)) for s, t in graph.edges if outer(s) != outer(t))
    components = sorted((sorted(s) for s in nx.strongly_connected_components(collapsed) if len(s) > 1), key=lambda s: s[0])
    for members in components:
        scc_count += 1
        subgraph = collapsed.subgraph(members)
        oversized = len(members) > large
        # Request at most cap+1 cycles so we can report truncation accurately.
        enumerated = [] if oversized else list(islice(nx.simple_cycles(subgraph, length_bound=max_length), cap + 1))
        finding = dict(id=stable_id('cycle', level + '|'.join(map(str, members))),
            level=level, issue_type='LARGE_CYCLIC_CLUSTER' if oversized else 'CIRCULAR_DEPENDENCY',
            members=members, node_count=len(members), internal_edge_count=subgraph.number_of_edges(),
            sample_cycles=enumerated[:cap], enumeration_skipped=oversized,
            truncated=oversized or len(enumerated) > cap,
            max_cycle_length=max_length)
        findings.append(finding)
    return {'items': findings, 'scc_count': scc_count}
