"""Metrics count distinct internal class neighbours, not method-call frequency."""
import math
import networkx as nx


def percentile(values: list[int], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def calculate_metrics(classes: dict, graph: nx.DiGraph) -> tuple[list[dict], list[dict], dict]:
    class_metrics = []
    for name, cls in sorted(classes.items()):
        class_metrics.append(dict(entity_id=name, entity_type='CLASS',
            method_count=cls.get('method_count', 0), field_count=cls.get('field_count', 0),
            fan_in=graph.in_degree(name), fan_out=graph.out_degree(name)))
    package_metrics = []
    for package in sorted({c['package_name'] for c in classes.values()}):
        members = {n for n, c in classes.items() if c['package_name'] == package}
        incoming = {s for t in members for s in graph.predecessors(t) if s not in members}
        outgoing = {t for s in members for t in graph.successors(s) if t not in members}
        ca, ce = len(incoming), len(outgoing)
        instability = ce / (ca + ce) if ca + ce else 0.0
        abstractness = sum(bool(classes[n].get('is_abstract') or classes[n].get('is_interface')) for n in members) / len(members)
        package_metrics.append(dict(entity_id=package, entity_type='PACKAGE', class_count=len(members),
            Ca=ca, Ce=ce, I=round(instability, 6), A=round(abstractness, 6),
            D=round(abs(abstractness + instability - 1), 6),
            isolated=ca + ce == 0))
    thresholds = {key: percentile([m[key] for m in class_metrics], .95) for key in ('method_count', 'field_count', 'fan_in', 'fan_out')}
    return class_metrics, package_metrics, thresholds
