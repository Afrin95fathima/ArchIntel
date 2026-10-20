"""Which application method issued each database span, and why not when that cannot be told.

A caller is taken from (1) the database span's own code attributes, else (2) the nearest ancestor span in
the same session and trace that maps to a scanned class. Spans are never skipped to invent ownership;
every observation that cannot be resolved carries a reason code with the evidence behind it.
"""
import re
from collections import Counter

from .mapping import map_class, map_method, unresolved_reason

MAX_DEPTH = 64
POOL_THREAD = re.compile(r'hikari|pool|connection|async|executor|task-|scheduling', re.I)
REASONS = {
    'PARENT_MISSING_FROM_SESSION': 'The parent span {parent} (depth {depth}) is not in this session and no spans were dropped, so it was never received.',
    'PARENT_DROPPED_BY_RETENTION_OR_LIMIT': 'The parent span {parent} (depth {depth}) is not in this session and {dropped} span(s) of the session were dropped by ingestion limits, so it may be among them.',
    'SPANS_OUT_OF_ORDER': 'Span {child} starts at {child_start} ns before its parent {parent} at {parent_start} ns; arrival order is not stored, so timestamps show spans out of order or clock skew.',
    'ANCESTOR_CLASS_NOT_IN_ARTIFACT': 'The nearest ancestor with a class is {cls} (depth {depth}); it is not mapped to a scanned class ({code}).',
    'ANCESTOR_WITHOUT_CODE_ATTRIBUTES': 'The {count} ancestor span(s) up to the trace root carry no code attributes: {names}.',
    'ASYNC_BOUNDARY_NO_CONTEXT_PROPAGATION': 'The database span is the root of its trace and has no code attributes; its caller ran on another thread or async task without trace-context propagation{thread}.',
    'INVALID_PARENT_CYCLE': 'The parent links of span {child} form a cycle, so no caller can be derived.',
}


def _ref(event):
    return dict(session_id=event['session_id'], trace_id=event['trace_id'], span_id=event['span_id'])


def resolve(events, classes, session_info=None):
    """Return (observations, summary). `classes` maps class id to its static record; `session_info` maps session id to {'dropped': n}."""
    index = {(e['session_id'], e['trace_id'], e['span_id']): e for e in events}
    session_info = session_info or {}
    cache = {}

    def mapped(name):
        if name not in cache:
            cache[name] = map_class(name, classes)
        return cache[name]

    def caller_of(span):
        m = mapped(span.get('class_name'))
        if not m['static_id']:
            return None
        return dict(caller_class=m['static_id'], caller_method=span.get('method_name'), caller_signature=map_method(span, classes).get('signature'),
                    thread=span.get('thread_name'))

    groups, reasons, depths = {}, Counter(), Counter()
    total = resolved = 0
    for e in events:
        if not e.get('database_system'):
            continue
        total += 1
        found, depth, code, reason, evidence = caller_of(e), 0, None, None, {}
        if found:
            resolution = 'OWN_ATTRIBUTES'
        else:
            resolution, path, seen, current, status = 'UNRESOLVED', [], {e['span_id']}, e, 'ROOT'
            while True:
                parent_id = current.get('parent_span_id')
                if not parent_id:
                    break
                parent = index.get((e['session_id'], e['trace_id'], parent_id))
                if parent is None:
                    status = 'MISSING'; evidence = dict(parent_span_id=parent_id, depth=depth + 1, child_span_id=current['span_id'])
                    break
                depth += 1
                if parent['span_id'] in seen or depth > MAX_DEPTH:
                    status = 'CYCLE'; break
                seen.add(parent['span_id']); path.append(parent)
                found = caller_of(parent)
                if found:
                    resolution, status = 'PARENT_CHAIN', 'RESOLVED'
                    break
                current = parent
            if status != 'RESOLVED':
                depth_at_stop = depth
                inverted = next(((c, p) for c, p in zip([e] + path, path) if p['timestamp'] > c['timestamp']), None)
                dropped = session_info.get(e['session_id'], {}).get('dropped', 0)
                if status == 'MISSING':
                    code = 'PARENT_DROPPED_BY_RETENTION_OR_LIMIT' if dropped else 'PARENT_MISSING_FROM_SESSION'
                    evidence = dict(evidence, session_dropped_spans=dropped)
                    reason = REASONS[code].format(parent=evidence['parent_span_id'], depth=evidence['depth'], dropped=dropped)
                elif status == 'CYCLE':
                    code = 'INVALID_PARENT_CYCLE'; reason = REASONS[code].format(child=e['span_id']); evidence = dict(child_span_id=e['span_id'])
                elif inverted:
                    code = 'SPANS_OUT_OF_ORDER'
                    evidence = dict(child_span_id=inverted[0]['span_id'], parent_span_id=inverted[1]['span_id'], child_start_ns=inverted[0]['timestamp'], parent_start_ns=inverted[1]['timestamp'])
                    reason = REASONS[code].format(child=evidence['child_span_id'], parent=evidence['parent_span_id'], child_start=evidence['child_start_ns'], parent_start=evidence['parent_start_ns'])
                elif not path:
                    code = 'ASYNC_BOUNDARY_NO_CONTEXT_PROPAGATION'
                    thread = e.get('thread_name')
                    evidence = dict(thread_name=thread, connection_pool_or_async_thread=bool(thread and POOL_THREAD.search(thread)), scope_name=e.get('scope_name'))
                    reason = REASONS[code].format(thread=f' (thread {thread})' if thread else '')
                else:
                    named = next((p for p in path if p.get('class_name')), None)
                    if named:
                        why = unresolved_reason(named['class_name'], classes)
                        code = 'ANCESTOR_CLASS_NOT_IN_ARTIFACT'
                        evidence = dict(ancestor_class=named['class_name'], ancestor_span_id=named['span_id'], depth=path.index(named) + 1, mapping_reason=why['reason_code'],
                                        closest_candidate=why['closest_candidate'], similarity=why['similarity'])
                        reason = REASONS[code].format(cls=named['class_name'], depth=evidence['depth'], code=why['reason_code'])
                    else:
                        code = 'ANCESTOR_WITHOUT_CODE_ATTRIBUTES'
                        names = [p.get('span_name') or p.get('event_type', 'OTHER') for p in path]
                        evidence = dict(ancestor_span_ids=[p['span_id'] for p in path[:5]], ancestor_span_names=names[:5])
                        reason = REASONS[code].format(count=len(path), names=', '.join(names[:5]))
                depth = depth_at_stop
        if found:
            resolved += 1
            depths[depth] += 1
        else:
            reasons[code] += 1
        tables = list(e.get('database_tables') or ([e['database_table']] if e.get('database_table') else []))
        caller = found or dict(caller_class=None, caller_method=None, caller_signature=None, thread=None)
        thread_boundary = None
        if found and e.get('thread_name') and caller.get('thread'):
            thread_boundary = dict(database_thread=e['thread_name'], caller_thread=caller['thread'], crosses_thread=e['thread_name'] != caller['thread'])
        key = (caller['caller_class'], caller['caller_method'], depth if found else None, code, e['database_system'], e.get('database_server'), e.get('database_namespace'), tuple(tables), e.get('database_operation'))
        item = groups.setdefault(key, dict(caller=caller['caller_class'], caller_class=caller['caller_class'], caller_method=caller['caller_method'],
            caller_signature=caller['caller_signature'], depth=depth if found else None, resolution=resolution, reason_code=code, reason=reason, reason_evidence=evidence,
            system=e['database_system'], server=e.get('database_server'), namespace=e.get('database_namespace'), resource=tables[0] if tables else None, tables=tables,
            operation=e.get('database_operation'), call_count=0, evidence=[], sample_span_ids=[], thread_boundary=thread_boundary))
        item['call_count'] += 1
        if len(item['evidence']) < 20:
            item['evidence'].append(_ref(e))
        if len(item['sample_span_ids']) < 3:
            item['sample_span_ids'].append(_ref(e))
    summary = dict(total=total, resolved=resolved, unresolved=total - resolved, by_reason=dict(reasons), by_depth={str(k): v for k, v in sorted(depths.items())})
    if not total:
        summary['text'] = 'No database spans were received in the selected sessions.'
    else:
        rest = ', '.join(f'{code} ({n})' for code, n in reasons.most_common())
        summary['text'] = f'{resolved} of {total} database observations resolved to a caller.' + (f' Unresolved: {rest}.' if rest else '')
    return list(groups.values()), summary
