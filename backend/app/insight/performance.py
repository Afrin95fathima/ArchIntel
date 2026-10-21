"""Performance evidence derived from the spans of the selected runtime sessions.

Everything here is measured from span timestamps and error status: nothing is estimated. Percentiles use the
nearest-rank method and are flagged unreliable below MIN_SAMPLES requests, because with few requests the p95 is
simply the slowest request. Observation conditions (test traffic, JVM warm-up, a single machine) are not production
load, so the findings point at where to measure next; they are not a capacity statement.
"""
from __future__ import annotations

import math
from collections import defaultdict

MIN_SAMPLES = 20
# (id, label, what is measured, thresholds as (severity, value) from lowest to highest)
RULES = {
    'PERF-SLOW': dict(label='Slow entry point', metric='p95 latency (ms)', thresholds=[('MEDIUM', 500), ('HIGH', 2000)],
                      action='Profile this route using the DB calls / request column and the Slowest code table before changing its structure.'),
    'PERF-CHATTY-DB': dict(label='Many database calls per request', metric='average database calls per request', thresholds=[('MEDIUM', 10), ('HIGH', 30)],
                           action='Check for repeated queries inside a loop (N+1) and batch or join them.'),
    'PERF-DB-BOUND': dict(label='Database-bound request', metric='share of request time spent in DB spans, in percent', thresholds=[('MEDIUM', 70)],
                          action='Tune the SQL queries and indexes first; splitting code will not make this route faster.'),
    'PERF-ERRORS': dict(label='Failing requests', metric='share of requests with an error (%)', thresholds=[('MEDIUM', 5), ('HIGH', 20)],
                        action='Open the failing traces; an error path that is slow or frequent is a risk for any extraction.'),
}
REQUEST = 'HTTP_SERVER'


def _percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[max(0, math.ceil(fraction * len(sorted_values)) - 1)]


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    count = len(ordered)
    return dict(count=count, min_ms=round(ordered[0], 2), avg_ms=round(sum(ordered) / count, 2), p50_ms=round(_percentile(ordered, .50), 2),
                p95_ms=round(_percentile(ordered, .95), 2), p99_ms=round(_percentile(ordered, .99), 2), max_ms=round(ordered[-1], 2),
                percentiles_reliable=count >= MIN_SAMPLES)


def _severity(rule: str, value: float) -> str | None:
    hit = None
    for severity, limit in RULES[rule]['thresholds']:
        if value >= limit:
            hit = severity
    return hit


def analyze(events: list[dict], classes_by_id: dict, class_domains: dict, domain_names: dict, map_class) -> dict:
    """`map_class(name) -> static class id or None` links a span's class name to a scanned class."""
    traces = defaultdict(list)
    for event in events:
        traces[(event.get('session_id'), event['trace_id'])].append(event)
    entries = defaultdict(list)                       # (method, route) -> per-request facts
    non_request = 0
    for group in traces.values():
        ordered = sorted(group, key=lambda e: e['timestamp'])
        root = next((e for e in ordered if e['event_type'] == REQUEST), None)
        if root is None:
            non_request += 1                          # start-up work, scheduled jobs, orphaned spans: not a user request
            continue
        database = [e for e in group if e['event_type'] == 'DATABASE_CALL']
        entries[(root.get('http_method') or '', root.get('http_route') or root.get('span_name') or '(no route)')].append(dict(
            ms=root['duration_ms'], error=any(e['error'] for e in group), at=root['timestamp'],
            db_calls=len(database), db_ms=min(sum(e['duration_ms'] for e in database), root['duration_ms'])))
    rows, findings = [], []
    for (method, route), requests in sorted(entries.items(), key=lambda item: (-len(item[1]), item[0])):
        latency = _stats([r['ms'] for r in requests])
        total_ms = sum(r['ms'] for r in requests)
        errors = sum(r['error'] for r in requests)
        row = dict(id=f'{method} {route}'.strip(), method=method, route=route, **latency,
                   first_ms=round(min(requests, key=lambda r: r['at'])['ms'], 2),
                   errors=errors, error_rate_pct=round(100 * errors / len(requests), 1),
                   db_calls_per_request=round(sum(r['db_calls'] for r in requests) / len(requests), 1),
                   db_share_pct=round(100 * sum(r['db_ms'] for r in requests) / total_ms, 1) if total_ms else 0.0)
        rows.append(row)
        # With too few requests the p95 is the maximum, so the finding says so instead of claiming a percentile.
        slow_value, slow_basis = (row['p95_ms'], 'p95') if row['percentiles_reliable'] else (row['max_ms'], 'slowest of %d requests' % row['count'])
        checks = [('PERF-SLOW', slow_value, f"{slow_basis} {slow_value} ms"),
                  ('PERF-CHATTY-DB', row['db_calls_per_request'], f"{row['db_calls_per_request']} database calls per request on average"),
                  ('PERF-ERRORS', row['error_rate_pct'], f"{errors} of {row['count']} requests failed ({row['error_rate_pct']}%)")]
        if row['avg_ms'] >= 100:                       # a fast route that is mostly one query is not a finding
            checks.append(('PERF-DB-BOUND', row['db_share_pct'], f"{row['db_share_pct']}% of the time is spent in database calls"))
        for rule, value, evidence in checks:
            severity = _severity(rule, value)
            if severity:
                findings.append(dict(rule_id=rule, label=RULES[rule]['label'], severity=severity, entry_point=row['id'], measured=value,
                                     unit=RULES[rule]['metric'], evidence=evidence, action=RULES[rule]['action'], reliable=row['percentiles_reliable'] or rule != 'PERF-SLOW'))
    methods = defaultdict(list)
    for event in events:
        if event['event_type'] == 'METHOD_CALL' and event.get('class_name') and event.get('method_name'):
            methods[(map_class(event['class_name']) or event['class_name'], event['method_name'])].append(event['duration_ms'])
    hotspots = []
    for (owner, name), values in methods.items():
        hotspots.append(dict(class_id=owner, method=name, in_scan=owner in classes_by_id, domain=domain_names.get(class_domains.get(owner)), **_stats(values), total_ms=round(sum(values), 2)))
    hotspots.sort(key=lambda h: (-h['total_ms'], h['class_id'], h['method']))
    by_domain = defaultdict(lambda: dict(calls=0, total_ms=0.0))
    for hotspot in hotspots:
        if hotspot['domain']:
            by_domain[hotspot['domain']]['calls'] += hotspot['count']
            by_domain[hotspot['domain']]['total_ms'] += hotspot['total_ms']
    domains = [dict(domain=name, calls=v['calls'], total_ms=round(v['total_ms'], 2), avg_ms=round(v['total_ms'] / v['calls'], 2)) for name, v in sorted(by_domain.items(), key=lambda i: -i[1]['total_ms'])]
    findings.sort(key=lambda f: (f['severity'] != 'HIGH', f['entry_point'], f['rule_id']))
    return dict(entry_points=rows, findings=findings, hotspots=hotspots[:15], domains=domains,
                summary=dict(requests=sum(r['count'] for r in rows), entry_points=len(rows), non_request_traces=non_request,
                             findings=len(findings), high=sum(f['severity'] == 'HIGH' for f in findings), medium=sum(f['severity'] == 'MEDIUM' for f in findings),
                             reliable_entry_points=sum(r['percentiles_reliable'] for r in rows)),
                rules=[dict(id=k, label=v['label'], metric=v['metric'], thresholds=[dict(severity=s, at_least=t) for s, t in v['thresholds']], action=v['action']) for k, v in RULES.items()],
                method=dict(min_samples=MIN_SAMPLES, percentile='nearest rank', time='inclusive span duration (endTimeUnixNano minus startTimeUnixNano); DB time is the sum of DB spans in the same trace, capped at the request time',
                            caveat='Measured under the observed traffic only (not production load); the first request after start-up includes JVM warm-up. Use these as pointers for load testing, not as capacity limits.'))
