"""How runtime spans were tied to scanned classes, and exactly why the others were not."""
import re
from collections import Counter, defaultdict

from .mapping import map_class, unresolved_reason

PARAMETER = re.compile(r'\{[^}/]*\}')
SAMPLES = 3
MAX_ROWS = 200
RULE_LABELS = {
    'exact': 'Exact fully qualified class name',
    'normalized': 'JVM internal name or descriptor normalized to a dotted name',
    'proxy_suffix': 'Generated proxy suffix removed; the base class exists in the scan',
    'lambda_suffix': 'Lambda class resolved to its declaring class',
    'nested_name': 'Dotted nested-class name matched the binary name',
    'route_match': 'HTTP method and route matched a controller mapping in the scan',
}
REASON_TEXT = {
    'NO_CODE_ATTRIBUTES': 'The span carries no code.namespace / code.function attributes, which this instrumentation does not set on {kind} spans.',
    'CLASS_NOT_IN_SCANNED_ARTIFACT': 'The class {name} is not in the scanned artifact and no scanned class is similar to it.',
    'NAME_MISMATCH_CLOSE_CANDIDATE': 'The class {name} is not in the scanned artifact; the closest scanned class is {candidate} (similarity {similarity}).',
    'PROXY_OR_GENERATED_CLASS': 'The class {name} is a generated proxy or lambda whose base class is not in the scanned artifact.',
    'ROUTE_NOT_IN_SCANNED_ARTIFACT': 'No controller in the scan maps {method} {route}.',
}
KIND = {1: 'INTERNAL', 2: 'SERVER', 3: 'CLIENT', 4: 'PRODUCER', 5: 'CONSUMER'}


def route_key(route):
    return PARAMETER.sub('{}', route or '').rstrip('/') or '/'


def route_table(static):
    """(HTTP method, normalized route) -> (handler class, handler method, declared route). Needs bytecode facts in the scan."""
    classes = (static.get('bytecode') or {}).get('classes')
    if not classes:
        return {}
    from app.insight.entrypoints import detect
    table = {}
    for entry in detect(classes)['items']:
        if entry['kind'] != 'HTTP_ENDPOINT':
            continue
        for verb in entry['http_methods'] or ['ANY']:
            for path in entry['paths'] or ['']:
                table.setdefault((verb.upper(), route_key(path)), (entry['handler_class'], entry['handler_method'], path))
    return table


def _still_tells(event, route_hit):
    kind = event.get('event_type')
    if kind == 'HTTP_SERVER':
        base = f"A {event.get('http_method') or 'HTTP'} request to {event.get('http_route') or 'an unnamed route'} was served"
        return base + (f"; the route maps to {route_hit[0]}.{route_hit[1]}()." if route_hit else '; no controller in the scan maps this route.')
    if kind == 'DATABASE_CALL':
        tables = ', '.join(event.get('database_tables') or []) or 'no table name'
        return f"A {event.get('database_system')} {event.get('database_operation') or 'call'} on {tables}."
    if kind in ('MESSAGE_PUBLISH', 'MESSAGE_CONSUME'):
        return f"A {event.get('messaging_system')} message {'published to' if kind == 'MESSAGE_PUBLISH' else 'consumed from'} {event.get('messaging_destination') or 'an unnamed destination'}."
    if kind == 'HTTP_CLIENT':
        return f"An outgoing {event.get('http_method')} call."
    return f"Span {event.get('span_name')!r} ran." if event.get('span_name') else 'Only the span timing and nesting are known.'


def _ref(event):
    return dict(session_id=event['session_id'], trace_id=event['trace_id'], span_id=event['span_id'])


def build(events, static):
    classes = {c['id']: c for c in static['classes']}
    routes = route_table(static)
    resolved, unmapped = {}, {}
    counts = Counter()
    for e in events:
        counts['events'] += 1
        identity = e.get('class_name')
        mapping = map_class(identity, classes)
        if mapping['static_id']:
            counts['mapped'] += 1
            row = resolved.setdefault((identity, mapping['static_id'], mapping['rule'], None), dict(
                runtime_identifier=identity, static_class=mapping['static_id'], static_method=None, rule=mapping['rule'], rule_label=RULE_LABELS[mapping['rule']],
                confidence=mapping['confidence'], event_count=0, sample_span_ids=[]))
            row['event_count'] += 1
            if len(row['sample_span_ids']) < SAMPLES: row['sample_span_ids'].append(_ref(e))
            continue
        route_hit = None
        if not identity and e.get('event_type') == 'HTTP_SERVER' and e.get('http_route'):
            method = (e.get('http_method') or 'ANY').upper()
            route_hit = routes.get((method, route_key(e['http_route']))) or routes.get(('ANY', route_key(e['http_route'])))
        if route_hit:
            counts['route_resolved'] += 1
            row = resolved.setdefault((f"{e.get('http_method')} {e['http_route']}", route_hit[0], 'route_match', route_hit[1]), dict(
                runtime_identifier=f"{e.get('http_method') or 'ANY'} {e['http_route']}", static_class=route_hit[0], static_method=route_hit[1], rule='route_match',
                rule_label=RULE_LABELS['route_match'], confidence=.8, event_count=0, sample_span_ids=[], declared_route=route_hit[2]))
            row['event_count'] += 1
            if len(row['sample_span_ids']) < SAMPLES: row['sample_span_ids'].append(_ref(e))
            continue
        counts['unmapped'] += 1
        if not identity:
            reason = dict(reason_code='NO_CODE_ATTRIBUTES', closest_candidate=None, similarity=None)
            if e.get('event_type') == 'HTTP_SERVER' and e.get('http_route'):
                reason['route_reason_code'] = 'ROUTE_NOT_IN_SCANNED_ARTIFACT' if routes else 'ROUTE_TABLE_UNAVAILABLE'
        else:
            reason = unresolved_reason(identity, classes)
        kind = KIND.get(e.get('span_kind'))
        key = (identity, e.get('event_type'), e.get('scope_name'), e.get('span_kind'), reason['reason_code'], e.get('http_route') if not identity else None)
        row = unmapped.setdefault(key, dict(
            runtime_identifier=identity, event_type=e.get('event_type'), span_names=[], instrumentation_scope=e.get('scope_name'), scope_version=e.get('scope_version'),
            span_kind=kind, event_count=0, missing_attributes=[a for a, present in (('code.namespace', identity), ('code.function', e.get('method_name'))) if not present],
            reason_code=reason['reason_code'], closest_candidate=reason['closest_candidate'], similarity=reason['similarity'], reason=None,
            still_tells_us=_still_tells(e, None), sample_span_ids=[]))
        row['event_count'] += 1
        if e.get('span_name') and e['span_name'] not in row['span_names'] and len(row['span_names']) < 5: row['span_names'].append(e['span_name'])
        if len(row['sample_span_ids']) < SAMPLES: row['sample_span_ids'].append(_ref(e))
        if reason.get('route_reason_code'):
            row['reason_code'] = reason['route_reason_code']
            row['route'] = f"{e.get('http_method')} {e['http_route']}"
    for row in unmapped.values():
        template = REASON_TEXT.get(row['reason_code'])
        row['reason'] = template.format(kind=(row['span_kind'] or 'unspecified-kind').lower(), name=row['runtime_identifier'], candidate=row['closest_candidate'], similarity=row['similarity'],
            method=(row.get('route') or ' ').split(' ')[0], route=(row.get('route') or ' ').split(' ', 1)[-1]) if template else 'The static route table is unavailable because this scan has no bytecode facts; run a new analysis.'
        if not row['span_names'] and not row['runtime_identifier']:
            row['span_names'] = []
    total = counts['events']
    why = (f"This table ties runtime spans to scanned classes. Mapped classes count as observed in coverage and appear in runtime flows. "
           f"{counts['mapped']} of {total} spans mapped to a class by name; {counts['route_resolved']} identify a controller method by route only and do not add to class coverage; "
           f"{counts['unmapped']} did not map.") if total else 'No spans were received in the selected sessions, so nothing could be mapped.'
    ordered = lambda rows, k: sorted(rows, key=lambda r: (-r['event_count'], str(r.get(k))))
    return dict(why=why, counts=dict(events=total, mapped=counts['mapped'], route_resolved=counts['route_resolved'], unmapped=counts['unmapped']),
        resolved=ordered(resolved.values(), 'runtime_identifier')[:MAX_ROWS], unmapped=ordered(unmapped.values(), 'runtime_identifier')[:MAX_ROWS],
        truncated=len(resolved) > MAX_ROWS or len(unmapped) > MAX_ROWS)
