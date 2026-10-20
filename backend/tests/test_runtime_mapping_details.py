"""Items 1 and 2: exact mapping rules, unmapped reasons, route resolution and database callers, on the Spring PetClinic fixture."""
import json
from difflib import SequenceMatcher
import pytest
from app.services.runtime.normalization import normalize
from app.services.runtime.mapping_report import build as report
from app.services.runtime.db_callers import resolve
from app.services.runtime.sql_tables import parse_statement
from insight_fixtures import snapshot
from test_runtime import live  # noqa: F401  (pytest fixture)

PC = 'org.springframework.samples.petclinic.'
OWNER_CONTROLLER = PC + 'owner.OwnerController'
OWNER_REPOSITORY = PC + 'owner.OwnerRepository'
TRACE = '1' * 32


def span(identity, name, parent=None, trace=TRACE, attrs=None, kind=1, start=1_000_000_000, end=1_001_000_000):
    return dict(traceId=trace, spanId=f'{identity:016x}', parentSpanId=f'{parent:016x}' if parent else '', name=name, kind=kind,
                startTimeUnixNano=str(start), endTimeUnixNano=str(end),
                attributes=[dict(key=k, value={'stringValue': v}) for k, v in (attrs or {}).items()])


def events(*spans, scope='io.opentelemetry.tomcat-10.0', session='s1'):
    data = {'resourceSpans': [{'scopeSpans': [{'scope': {'name': scope, 'version': '2.1.0'}, 'spans': list(spans)}]}]}
    return [dict(e, session_id=session) for e in normalize(data, 1000)]


def code(cls, method='work'):
    return {'code.namespace': cls, 'code.function': method}


@pytest.fixture(scope='module')
def static():
    return snapshot()


@pytest.fixture(scope='module')
def classes(static):
    return {c['id']: c for c in static['classes']}


def row(rows, **match):
    found = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, (match, rows)
    return found[0]


# ---- Item 1: mapping report -------------------------------------------------------------------------------------

def test_resolved_rows_name_the_rule_class_and_event_count(static):
    ev = events(span(1, 'a', attrs=code(OWNER_CONTROLLER, 'showOwner')), span(2, 'b', attrs=code(OWNER_CONTROLLER, 'showOwner')),
                span(3, 'c', attrs=code(PC.replace('.', '/') + 'vet/VetController')),
                span(4, 'd', attrs=code(OWNER_REPOSITORY + '$$SpringCGLIB$$0')))
    out = report(ev, static)
    exact = row(out['resolved'], rule='exact')
    assert (exact['runtime_identifier'], exact['static_class'], exact['event_count']) == (OWNER_CONTROLLER, OWNER_CONTROLLER, 2)
    assert len(exact['sample_span_ids']) == 2 and exact['sample_span_ids'][0]['span_id'] == f'{1:016x}'
    normalized = row(out['resolved'], rule='normalized')
    assert normalized['static_class'] == PC + 'vet.VetController' and normalized['event_count'] == 1
    proxy = row(out['resolved'], rule='proxy_suffix')
    assert proxy['runtime_identifier'] == OWNER_REPOSITORY + '$$SpringCGLIB$$0' and proxy['static_class'] == OWNER_REPOSITORY
    assert out['counts'] == dict(events=4, mapped=4, route_resolved=0, unmapped=0)


def test_route_resolved_span_names_the_controller_method_and_route(static):
    ev = events(span(1, 'GET /owners/{id}', attrs={'http.request.method': 'GET', 'http.route': '/owners/{id}'}, kind=2),
                span(2, 'GET /owners/{ownerId}', attrs={'http.request.method': 'GET', 'http.route': '/owners/{ownerId}'}, kind=2),
                span(3, 'POST /owners/new', attrs={'http.request.method': 'POST', 'http.route': '/owners/new'}, kind=2))
    out = report(ev, static)
    hits = [r for r in out['resolved'] if r['rule'] == 'route_match' and r['static_method'] == 'showOwner']
    assert sorted(r['runtime_identifier'] for r in hits) == ['GET /owners/{id}', 'GET /owners/{ownerId}']
    assert all(r['static_class'] == OWNER_CONTROLLER and r['event_count'] == 1 and r['declared_route'] == '/owners/{ownerId}' for r in hits)
    assert row(out['resolved'], rule='route_match', static_method='processCreationForm')['event_count'] == 1
    assert out['counts'] == dict(events=3, mapped=0, route_resolved=3, unmapped=0)
    assert 'do not add to class coverage' in out['why']


def test_unmapped_span_without_code_attributes_lists_attributes_scope_kind_and_three_samples(static):
    ev = events(*[span(i, 'SELECT petclinic.owners', parent=None, trace=f'{i:032x}', kind=3, attrs={'db.system': 'h2', 'db.operation': 'SELECT'}) for i in range(1, 6)], scope='io.opentelemetry.jdbc')
    out = report(ev, static)
    assert out['counts'] == dict(events=5, mapped=0, route_resolved=0, unmapped=5)
    item = row(out['unmapped'], reason_code='NO_CODE_ATTRIBUTES')
    assert item['event_count'] == 5 and item['missing_attributes'] == ['code.namespace', 'code.function']
    assert item['span_names'] == ['SELECT petclinic.owners'] and item['instrumentation_scope'] == 'io.opentelemetry.jdbc' and item['span_kind'] == 'CLIENT'
    assert len(item['sample_span_ids']) == 3 and item['sample_span_ids'][2]['span_id'] == f'{3:016x}'
    assert item['event_type'] == 'DATABASE_CALL' and 'h2' in item['still_tells_us'] and 'SELECT' in item['still_tells_us']
    assert 'client' in item['reason']


def test_close_name_is_reported_with_candidate_and_similarity_but_not_mapped(static):
    typo = PC + 'owner.OwnerControler'
    out = report(events(span(1, 'x', attrs=code(typo))), static)
    item = row(out['unmapped'], runtime_identifier=typo)
    assert item['reason_code'] == 'NAME_MISMATCH_CLOSE_CANDIDATE' and item['closest_candidate'] == OWNER_CONTROLLER
    assert item['similarity'] == round(SequenceMatcher(None, OWNER_CONTROLLER, typo).ratio(), 3) and item['similarity'] >= .85
    assert item['missing_attributes'] == [] and out['counts']['mapped'] == 0
    assert OWNER_CONTROLLER in item['reason'] and str(item['similarity']) in item['reason']


def test_class_outside_the_artifact_and_generated_classes_get_distinct_reasons(static):
    out = report(events(span(1, 'x', attrs=code('org.hibernate.internal.SessionImpl')), span(2, 'y', attrs=code('com.sun.proxy.$Proxy42'))), static)
    assert row(out['unmapped'], runtime_identifier='org.hibernate.internal.SessionImpl')['reason_code'] == 'CLASS_NOT_IN_SCANNED_ARTIFACT'
    assert row(out['unmapped'], runtime_identifier='com.sun.proxy.$Proxy42')['reason_code'] == 'PROXY_OR_GENERATED_CLASS'


def test_unmatched_route_says_no_controller_maps_it(static):
    out = report(events(span(1, 'GET /nope', attrs={'http.request.method': 'GET', 'http.route': '/nope'}, kind=2)), static)
    item = out['unmapped'][0]
    assert item['reason_code'] == 'ROUTE_NOT_IN_SCANNED_ARTIFACT' and item['route'] == 'GET /nope'
    assert 'no controller in the scan maps this route' in item['still_tells_us'] and 'GET /nope' in item['reason']


def test_why_line_states_the_counts(static):
    ev = events(span(1, 'a', attrs=code(OWNER_CONTROLLER)), span(2, 'b'), span(3, 'c', attrs={'http.request.method': 'GET', 'http.route': '/vets'}, kind=2))
    out = report(ev, static)
    assert out['why'].startswith('This table ties runtime spans to scanned classes.')
    assert '1 of 3 spans mapped' in out['why'] and '1 identify a controller method by route only' in out['why'] and '1 did not map' in out['why']
    assert report([], static)['why'] == 'No spans were received in the selected sessions, so nothing could be mapped.'


# ---- Item 2: database callers -----------------------------------------------------------------------------------

DB = {'db.system': 'h2', 'db.statement': 'select o.id from owners o join pets p on p.owner_id = o.id where o.last_name = \'Davis\''}


def test_statement_is_parsed_into_operation_and_tables_and_never_stored():
    ev = events(span(1, 'SELECT', attrs=DB))[0]
    assert (ev['database_operation'], ev['database_tables']) == ('SELECT', ['owners', 'pets'])
    stored = json.dumps(ev).lower()
    assert 'davis' not in stored and 'last_name' not in stored and 'db.statement' not in stored


@pytest.mark.parametrize('statement,operation,tables', [
    ('INSERT INTO visits (a, b) VALUES (?, ?)', 'INSERT', ['visits']), ('update pets set name = ? where id = ?', 'UPDATE', ['pets']),
    ('DELETE FROM public.visits WHERE id = 1', 'DELETE', ['public.visits']), ('select a from owners, pets where 1 = 1', 'SELECT', ['owners', 'pets']),
    ('with x as (select 1 from t1) select * from x join t2 on 1 = 1', 'SELECT', ['t1', 't2'])])
def test_sql_parser_known_statements(statement, operation, tables):
    assert parse_statement(statement) == (operation, tables)


def test_direct_caller_from_the_database_span_itself(classes):
    ev = events(span(1, 'q', attrs={**DB, **code(OWNER_REPOSITORY, 'findByLastName')}))
    rows, summary = resolve(ev, classes)
    r = rows[0]
    assert (r['caller_class'], r['caller_method'], r['depth'], r['resolution'], r['reason_code']) == (OWNER_REPOSITORY, 'findByLastName', 0, 'OWN_ATTRIBUTES', None)
    assert (r['operation'], r['tables'], r['call_count']) == ('SELECT', ['owners', 'pets'], 1)
    assert summary['text'] == '1 of 1 database observations resolved to a caller.'


def test_caller_three_levels_up_is_found_with_its_depth(classes):
    ev = events(span(1, 'POST /owners', attrs=code(OWNER_CONTROLLER, 'processFindForm')), span(2, 'inner', parent=1), span(3, 'inner2', parent=2), span(4, 'q', parent=3, attrs=DB),
                span(5, 'q', parent=3, attrs=DB))
    rows, summary = resolve(ev, classes)
    r = rows[0]
    assert len(rows) == 1 and (r['caller_class'], r['caller_method'], r['depth'], r['resolution']) == (OWNER_CONTROLLER, 'processFindForm', 3, 'PARENT_CHAIN')
    assert r['call_count'] == 2 and [s['span_id'] for s in r['sample_span_ids']] == [f'{4:016x}', f'{5:016x}']
    assert summary['by_depth'] == {'3': 2}


def test_missing_parent_and_dropped_parent_have_different_codes(classes):
    ev = events(span(4, 'q', parent=3, attrs=DB))
    r = resolve(ev, classes, {'s1': {'dropped': 0}})[0][0]
    assert r['reason_code'] == 'PARENT_MISSING_FROM_SESSION' and r['caller_class'] is None and r['reason_evidence']['parent_span_id'] == f'{3:016x}'
    assert f'{3:016x}' in r['reason'] and 'never received' in r['reason']
    r = resolve(ev, classes, {'s1': {'dropped': 4}})[0][0]
    assert r['reason_code'] == 'PARENT_DROPPED_BY_RETENTION_OR_LIMIT' and r['reason_evidence']['session_dropped_spans'] == 4 and '4 span(s)' in r['reason']


def test_unmapped_ancestor_is_named(classes):
    ev = events(span(1, 'session', attrs=code('org.hibernate.internal.SessionImpl', 'get')), span(2, 'q', parent=1, attrs=DB))
    r = resolve(ev, classes)[0][0]
    assert r['reason_code'] == 'ANCESTOR_CLASS_NOT_IN_ARTIFACT' and r['reason_evidence']['ancestor_class'] == 'org.hibernate.internal.SessionImpl'
    assert r['reason_evidence']['depth'] == 1 and r['reason_evidence']['mapping_reason'] == 'CLASS_NOT_IN_SCANNED_ARTIFACT'
    assert 'org.hibernate.internal.SessionImpl' in r['reason']
    ev = events(span(1, 'GET /owners', kind=2), span(2, 'q', parent=1, attrs=DB))
    r = resolve(ev, classes)[0][0]
    assert r['reason_code'] == 'ANCESTOR_WITHOUT_CODE_ATTRIBUTES' and r['reason_evidence']['ancestor_span_names'] == ['GET /owners']


def test_trace_root_database_span_is_an_async_boundary_without_propagation(classes):
    ev = events(span(1, 'q', attrs={**DB, 'thread.name': 'task-3'}))
    r = resolve(ev, classes)[0][0]
    assert r['reason_code'] == 'ASYNC_BOUNDARY_NO_CONTEXT_PROPAGATION' and r['reason_evidence']['thread_name'] == 'task-3'
    assert r['reason_evidence']['connection_pool_or_async_thread'] is True and '(thread task-3)' in r['reason']


def test_parent_starting_after_child_is_reported_as_out_of_order(classes):
    ev = events(span(1, 'late parent', start=5_000_000_000, end=6_000_000_000), span(2, 'q', parent=1, attrs=DB, start=1_000_000_000, end=1_100_000_000))
    r = resolve(ev, classes)[0][0]
    assert r['reason_code'] == 'SPANS_OUT_OF_ORDER' and r['reason_evidence']['child_start_ns'] == 1_000_000_000 and r['reason_evidence']['parent_start_ns'] == 5_000_000_000


def test_parent_links_are_scoped_to_the_session(classes):
    parent = events(span(1, 'GET', attrs=code(OWNER_CONTROLLER)), session='s1')
    child = events(span(2, 'q', parent=1, attrs=DB), session='s2')
    assert resolve(parent + child, classes)[0][0]['reason_code'] == 'PARENT_MISSING_FROM_SESSION'


def test_summary_counts_resolved_and_each_reason(classes):
    ev = events(span(1, 'c', attrs=code(OWNER_CONTROLLER, 'm')), span(2, 'q', parent=1, attrs=DB), span(3, 'q', attrs=DB),
                span(4, 'q', parent=99, attrs=DB, trace='2' * 32), span(5, 'q', parent=98, attrs=DB, trace='3' * 32), span(6, 'q', attrs={**DB, **code(OWNER_REPOSITORY, 'find')}, trace='4' * 32))
    rows, summary = resolve(ev, classes)
    assert (summary['total'], summary['resolved'], summary['unresolved']) == (5, 2, 3)
    assert summary['by_reason'] == {'ASYNC_BOUNDARY_NO_CONTEXT_PROPAGATION': 1, 'PARENT_MISSING_FROM_SESSION': 2}
    assert summary['text'] == '2 of 5 database observations resolved to a caller. Unresolved: PARENT_MISSING_FROM_SESSION (2), ASYNC_BOUNDARY_NO_CONTEXT_PROPAGATION (1).'
    assert all(r['reason'] for r in rows if r['caller_class'] is None) and not any(r['caller'] == 'Unknown' for r in rows)


def test_thread_boundary_is_recorded_when_the_caller_runs_on_another_thread(classes):
    ev = events(span(1, 'c', attrs={**code(OWNER_CONTROLLER, 'm'), 'thread.name': 'http-nio-8080-exec-1'}), span(2, 'q', parent=1, attrs={**DB, 'thread.name': 'HikariPool-1 housekeeper'.replace(' ', '-')}))
    r = resolve(ev, classes)[0][0]
    assert r['thread_boundary'] == dict(database_thread='HikariPool-1-housekeeper', caller_thread='http-nio-8080-exec-1', crosses_thread=True)


# ---- End to end through the API ---------------------------------------------------------------------------------

def test_evidence_endpoint_returns_mapping_report_and_database_callers_and_never_the_statement(live):
    from test_runtime import create
    from app.runtime.models import RuntimeEvent
    from sqlalchemy import select
    created = create(live)
    base = '/api/v1/runtime-sessions/' + created['session']['id']
    headers = {'Authorization': 'Bearer ' + created['token']}
    live.post(base + '/start')
    data = {'resourceSpans': [{'scopeSpans': [{'scope': {'name': 'io.opentelemetry.jdbc'}, 'spans': [
        span(1, 'work', attrs=code('app.a.A', 'work')),
        span(2, 'SELECT owners', parent=1, kind=3, attrs={'db.system': 'h2', 'db.statement': "select * from owners where last_name = 'SecretName'"}),
        span(3, 'GET /unknown', trace='2' * 32, kind=2, attrs={'http.request.method': 'GET', 'http.route': '/unknown'})]}]}]}
    assert live.post(base + '/v1/traces', json=data, headers=headers).status_code == 200
    body = live.get(base + '/evidence').json()
    assert body['mapping_report']['counts'] == dict(events=3, mapped=1, route_resolved=0, unmapped=2)
    assert body['mapping_report']['resolved'][0]['rule'] == 'exact'
    unmapped = {r['reason_code']: r for r in body['mapping_report']['unmapped']}
    assert unmapped['NO_CODE_ATTRIBUTES']['instrumentation_scope'] == 'io.opentelemetry.jdbc' and unmapped['NO_CODE_ATTRIBUTES']['span_kind'] == 'CLIENT'
    assert unmapped['ROUTE_TABLE_UNAVAILABLE']['route'] == 'GET /unknown'
    assert body['database_summary']['text'] == '1 of 1 database observations resolved to a caller.'
    row_ = body['database'][0]
    assert (row_['caller_class'], row_['depth'], row_['operation'], row_['tables']) == ('app.a.A', 1, 'SELECT', ['owners'])
    assert 'SecretName' not in live.get(base + '/evidence').text
    with live.app.state.sessions() as db:
        assert 'SecretName' not in json.dumps([r.data for r in db.scalars(select(RuntimeEvent))])
