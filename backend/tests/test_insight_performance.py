"""Performance evidence: latency percentiles, errors, database time and hotspots measured from span events."""
from app.insight.performance import analyze, MIN_SAMPLES
from test_runtime import live, create, payload
from test_evidence import capture

CLASSES = {'app.a.A': {}, 'app.b.B': {}}
DOMAINS = {'app.a.A': 'd1', 'app.b.B': 'd2'}
NAMES = {'d1': 'Alpha', 'd2': 'Beta'}


def mapper(name):
    return name if name in CLASSES else None


def event(trace, kind, ms, at=0, **extra):
    return dict(session_id='s', trace_id=trace, span_id=f'{trace}-{kind}-{at}-{extra.get("method_name", "")}', event_type=kind, duration_ms=ms, timestamp=at, error=extra.pop('error', False), **extra)


def request(trace, ms, route='/pets', at=0, db=(), error=False, method='GET'):
    events = [event(trace, 'HTTP_SERVER', ms, at, http_route=route, http_method=method, error=error)]
    events += [event(trace, 'DATABASE_CALL', d, at + 1 + i) for i, d in enumerate(db)]
    return events


def run(events):
    return analyze(events, CLASSES, DOMAINS, NAMES, mapper)


def test_percentiles_use_nearest_rank_and_are_reliable_with_enough_requests():
    events = [e for i in range(1, 101) for e in request(f't{i}', float(i), at=i)]          # latencies 1..100 ms
    [row] = run(events)['entry_points']
    assert (row['count'], row['min_ms'], row['p50_ms'], row['p95_ms'], row['p99_ms'], row['max_ms'], row['avg_ms']) == (100, 1.0, 50.0, 95.0, 99.0, 100.0, 50.5)
    assert row['percentiles_reliable'] is True and row['first_ms'] == 1.0


def test_nearest_rank_rounds_up_when_the_rank_is_not_a_whole_number():
    [row] = run([e for i in range(1, 11) for e in request(f't{i}', float(i), at=i)])['entry_points']      # ranks 5.0, 9.5, 9.9 of 10
    assert (row['p50_ms'], row['p95_ms'], row['p99_ms']) == (5.0, 10.0, 10.0)
    [row] = run([e for i in range(1, 4) for e in request(f'u{i}', float(i), at=i)])['entry_points']        # rank 1.5 of 3
    assert row['p50_ms'] == 2.0


def test_few_requests_are_marked_unreliable_and_the_finding_names_the_slowest_request():
    result = run([e for i in range(3) for e in request(f't{i}', 3000.0, at=i)])
    [row] = result['entry_points']
    assert row['count'] == 3 < MIN_SAMPLES and row['percentiles_reliable'] is False
    [finding] = [f for f in result['findings'] if f['rule_id'] == 'PERF-SLOW']
    assert finding['severity'] == 'HIGH' and finding['evidence'] == 'slowest of 3 requests 3000.0 ms' and finding['reliable'] is False


def test_fast_routes_produce_no_findings():
    result = run([e for i in range(30) for e in request(f't{i}', 20.0, at=i, db=[2.0])])
    assert result['findings'] == [] and result['summary']['findings'] == 0 and result['summary']['reliable_entry_points'] == 1


def test_chatty_database_access_and_database_bound_requests_are_flagged():
    events = [e for i in range(25) for e in request(f't{i}', 400.0, at=i * 100, db=[10.0] * 35)]       # 35 calls, 350 of 400 ms
    result = run(events)
    [row] = result['entry_points']
    assert (row['db_calls_per_request'], row['db_share_pct']) == (35.0, 87.5)
    flagged = {f['rule_id']: f['severity'] for f in result['findings']}
    assert flagged == {'PERF-CHATTY-DB': 'HIGH', 'PERF-DB-BOUND': 'MEDIUM'}


def test_database_time_never_exceeds_the_request_time():
    [row] = run(request('t', 100.0, db=[80.0, 80.0]))['entry_points']       # overlapping or parallel spans
    assert row['db_share_pct'] == 100.0


def test_a_fast_route_that_is_mostly_one_query_is_not_called_database_bound():
    result = run([e for i in range(25) for e in request(f't{i}', 30.0, at=i, db=[28.0])])
    assert not [f for f in result['findings'] if f['rule_id'] == 'PERF-DB-BOUND']


def test_error_rate_counts_requests_not_spans():
    events = [e for i in range(20) for e in request(f't{i}', 10.0, at=i, error=i < 6)]
    result = run(events)
    [row] = result['entry_points']
    assert (row['errors'], row['error_rate_pct']) == (6, 30.0)
    assert [(f['rule_id'], f['severity']) for f in result['findings']] == [('PERF-ERRORS', 'HIGH')]


def test_traces_without_a_request_are_counted_separately_and_do_not_pollute_latency():
    startup = [event('boot', 'DATABASE_CALL', 900.0, 1), event('boot', 'DATABASE_CALL', 900.0, 2)]
    result = run(request('t', 12.0) + startup)
    assert result['summary'] == dict(result['summary'], requests=1, entry_points=1, non_request_traces=1)
    assert result['entry_points'][0]['max_ms'] == 12.0


def test_routes_are_separated_by_method_and_route_and_sorted_by_volume():
    events = request('a', 10.0, route='/x') + request('b', 10.0, route='/x') + request('c', 10.0, route='/x', method='POST') + request('d', 10.0, route='/y')
    assert [(r['id'], r['count']) for r in run(events)['entry_points']] == [('GET /x', 2), ('GET /y', 1), ('POST /x', 1)]


def test_hotspots_rank_methods_by_total_time_and_attach_the_domain():
    events = [event('t', 'METHOD_CALL', 5.0, 1, class_name='app.a.A', method_name='slow'), event('t', 'METHOD_CALL', 15.0, 2, class_name='app.a.A', method_name='slow'),
              event('t', 'METHOD_CALL', 4.0, 3, class_name='app.b.B', method_name='quick'), event('t', 'METHOD_CALL', 50.0, 4, class_name='lib.X', method_name='outside')]
    result = run(events)
    assert [(h['class_id'], h['method'], h['count'], h['total_ms'], h['domain'], h['in_scan']) for h in result['hotspots']] == [
        ('lib.X', 'outside', 1, 50.0, None, False), ('app.a.A', 'slow', 2, 20.0, 'Alpha', True), ('app.b.B', 'quick', 1, 4.0, 'Beta', True)]
    assert result['domains'] == [dict(domain='Alpha', calls=2, total_ms=20.0, avg_ms=10.0), dict(domain='Beta', calls=1, total_ms=4.0, avg_ms=4.0)]


def test_no_events_gives_an_empty_but_complete_result():
    result = run([])
    assert result['entry_points'] == [] and result['findings'] == [] and result['summary']['requests'] == 0 and result['rules'] and result['method']['caveat']


def timed(identity, trace, start_ms, duration_ms, attrs, parent=None, kind=1):
    base = 1_000_000_000
    return dict(traceId=trace, spanId=f'{identity:016x}', parentSpanId=f'{parent:016x}' if parent else '', kind=kind,
                startTimeUnixNano=str(base + start_ms * 1_000_000), endTimeUnixNano=str(base + (start_ms + duration_ms) * 1_000_000),
                attributes=[dict(key=k, value={'stringValue': v}) for k, v in attrs.items()])


def test_api_measures_latency_from_real_span_timestamps(live):
    spans = []
    for n, ms in enumerate((100, 200, 300), start=1):          # three requests, each: server span, database span, method span
        trace = f'{n:032x}'
        spans += [timed(n * 10, trace, n * 1000, ms, {'http.request.method': 'GET', 'http.route': '/owners/{id}'}, kind=2),
                  timed(n * 10 + 1, trace, n * 1000 + 10, 40, {'db.system': 'h2', 'db.operation': 'SELECT'}, parent=n * 10, kind=3),
                  timed(n * 10 + 2, trace, n * 1000 + 60, 30, {'code.namespace': 'app.a.A', 'code.function': 'work'}, parent=n * 10)]
    session = capture(live, *spans[:9])
    response = live.get(f'/api/v1/analyses/{live.run_id}/insight/performance', params={'runtime_session_ids': session})
    assert response.status_code == 200, response.text
    body = response.json()
    [row] = body['entry_points']
    assert (row['id'], row['count'], row['min_ms'], row['avg_ms'], row['max_ms'], row['db_calls_per_request'], row['percentiles_reliable']) == ('GET /owners/{id}', 3, 100.0, 200.0, 300.0, 1.0, False)
    assert row['db_share_pct'] == 20.0                          # 3 x 40 ms of 600 ms
    assert [(h['class_id'], h['method'], h['count'], h['total_ms'], h['in_scan']) for h in body['hotspots']] == [('app.a.A', 'work', 3, 90.0, True)]
    assert body['sessions'][0]['id'] == session and body['summary']['non_request_traces'] == 0


def test_api_rejects_a_session_of_another_analysis_and_missing_selection(live):
    assert live.get(f'/api/v1/analyses/{live.run_id}/insight/performance').status_code == 422
    assert live.get(f'/api/v1/analyses/{live.run_id}/insight/performance', params={'runtime_session_ids': 'missing'}).status_code in (403, 404)
