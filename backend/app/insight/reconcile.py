"""Make snapshot-level counts and inventories agree with the bytecode facts used by the insight pages."""
from __future__ import annotations

from .entrypoints import detect, describe
from .model import owner_of

KIND = {'HTTP_ENDPOINT': 'REST_ENDPOINT', 'SERVLET': 'SERVLET', 'SERVLET_FILTER': 'SERVLET_FILTER', 'STRUTS_ACTION': 'STRUTS_ACTION',
    'SCHEDULED_JOB': 'SCHEDULED_JOB', 'MESSAGE_LISTENER': 'MESSAGE_LISTENER', 'EVENT_LISTENER': 'EVENT_LISTENER',
    'LIFECYCLE_CALLBACK': 'LIFECYCLE_CALLBACK', 'MAIN_METHOD': 'MAIN_METHOD'}


def reconcile(result: dict) -> None:
    facts = (result.get('bytecode') or {}).get('classes') or {}
    names = [c['id'] for c in result['classes']]
    nested = [n for n in names if owner_of(n, facts) != n]
    result['summary']['top_level_class_count'] = len(names) - len(nested)
    result['summary']['nested_class_count'] = len(nested)
    if not facts:
        return
    domains = {c['id']: c.get('domain_id') for c in result['classes']}
    domain_names = {d['id']: d['name'] for d in result.get('domains', [])}
    items = []
    for entry in detect(facts)['items']:
        if entry['handler_class'] not in domains or entry['kind'] == 'LIFECYCLE_CALLBACK':
            continue
        domain = domains[entry['handler_class']]
        items.append(dict(domain_id=domain, domain=domain_names.get(domain), kind=KIND.get(entry['kind'], entry['kind']),
            http_method=','.join(entry['http_methods']) or 'NOT_HTTP', path=', '.join(entry['paths']) or 'NOT_HTTP',
            handler_class=entry['handler_class'], handler_signature=entry['handler_signature'], annotations=[],
            route_metadata_state='BYTECODE_ANNOTATION_VALUES', observation_state='UNKNOWN', description=describe(entry),
            limitation='Routes are read from annotation values in the class files; routes composed in XML or code are not visible.'))
    by_domain = {d['id']: [] for d in result.get('domains', [])}
    for item in items:
        by_domain.setdefault(item['domain_id'], []).append(item)
    result['entry_points'] = dict(items=items, by_domain=by_domain, source='BYTECODE',
        limitation='Entry points = methods with a routing annotation, a servlet override or a listener, read from class files. HTTP paths combine class-level and method-level @RequestMapping values.')
