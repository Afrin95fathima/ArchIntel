"""Entry points with composed routes, read from bytecode annotation values.

Supported: Spring MVC/WebFlux mappings (class + method level, value/path aliases, multiple paths and
methods), JAX-RS @Path + verb, servlets (@WebServlet + doGet/doPost...), servlet filters, @Scheduled,
@EventListener, Kafka/JMS/Rabbit listeners, @PostConstruct and public static main.
"""
from __future__ import annotations

from app.services.graph import stable_id
from .roles import short, supertypes

SPRING_VERBS = {'GetMapping': ['GET'], 'PostMapping': ['POST'], 'PutMapping': ['PUT'], 'DeleteMapping': ['DELETE'], 'PatchMapping': ['PATCH']}
JAXRS_VERBS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}
SERVLET_VERBS = {'doGet': 'GET', 'doPost': 'POST', 'doPut': 'PUT', 'doDelete': 'DELETE', 'doPatch': 'PATCH', 'service': 'ANY'}
LISTENERS = {'KafkaListener': ('MESSAGE_LISTENER', 'topics'), 'JmsListener': ('MESSAGE_LISTENER', 'destination'),
    'RabbitListener': ('MESSAGE_LISTENER', 'queues'), 'SqsListener': ('MESSAGE_LISTENER', 'value'),
    'EventListener': ('EVENT_LISTENER', 'classes')}
BINDINGS = {'PathVariable': 'path', 'RequestParam': 'query', 'RequestBody': 'body', 'RequestHeader': 'header',
    'ModelAttribute': 'form', 'CookieValue': 'cookie', 'PathParam': 'path', 'QueryParam': 'query', 'FormParam': 'form'}
CONSTRAINTS = {'NotNull', 'NotBlank', 'NotEmpty', 'Size', 'Pattern', 'Min', 'Max', 'Email', 'Past', 'Future',
    'PastOrPresent', 'FutureOrPresent', 'Positive', 'PositiveOrZero', 'Negative', 'Digits', 'DecimalMin', 'DecimalMax', 'Valid'}
FRAMEWORK_PARAMS = ('org.springframework.ui.', 'org.springframework.validation.', 'org.springframework.web.servlet.mvc.support.',
    'javax.servlet.', 'jakarta.servlet.', 'java.util.Map', 'java.security.Principal', 'java.util.Locale')


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _paths(values: dict) -> list[str]:
    paths = _as_list(values.get('value')) + _as_list(values.get('path'))
    return [p for p in paths if isinstance(p, str)] or ['']


def join_path(prefix: str, suffix: str) -> str:
    joined = '/' + '/'.join(part.strip('/') for part in (prefix, suffix) if part and part.strip('/'))
    return joined


def _ann(items: list[dict], name: str) -> dict | None:
    return next((a for a in items if short(a['type']) == name), None)


def _validation_text(annotation: dict) -> str:
    name = short(annotation['type'])
    values = {k: v for k, v in annotation.get('values', {}).items() if k not in ('message', 'groups', 'payload')}
    return name + ('(' + ', '.join(f'{k}={v}' for k, v in sorted(values.items())) + ')' if values else '')


def parameters(method: dict, facts: dict) -> list[dict]:
    out = []
    groups = method.get('parameter_annotations') or []
    for index, type_name in enumerate(method.get('parameters', [])):
        annotations = groups[index] if index < len(groups) else []
        binding, name, required, default = None, None, None, None
        for annotation in annotations:
            simple = short(annotation['type'])
            if simple in BINDINGS:
                binding = BINDINGS[simple]
                values = annotation.get('values', {})
                name = values.get('value') or values.get('name') or None
                required = values.get('required', True if simple != 'ModelAttribute' else None)
                default = values.get('defaultValue')
        constraints = [_validation_text(a) for a in annotations if short(a['type']) in CONSTRAINTS]
        framework = type_name.startswith(FRAMEWORK_PARAMS)
        if binding is None and not framework and type_name in facts:
            binding = 'form'           # Spring binds an unannotated application type as a form/model attribute.
        out.append(dict(index=index, type=type_name, binding=binding or ('framework' if framework else 'unbound'),
            name=name, required=required, default=default, constraints=constraints))
    return out


def _entry(kind, cls, method, http_methods, paths, trigger, evidence, facts):
    signature = method['signature']
    return dict(id=stable_id('entry', cls['fqn'] + '#' + method['name'] + method['descriptor']), kind=kind,
        handler_class=cls['fqn'], handler_method=method['name'], handler_descriptor=method['descriptor'],
        handler_signature=signature, http_methods=http_methods, paths=paths, trigger=trigger,
        parameters=parameters(method, facts), evidence=evidence, line=(method.get('line_range') or [None])[0],
        route_metadata_state='BYTECODE_ANNOTATION_VALUES')


def _jvm_main(method: dict) -> bool:
    return method['name'] == 'main' and method['static'] and method['descriptor'] == '([Ljava/lang/String;)V' and method['visibility'] == 'public'


def detect(facts: dict) -> dict:
    """Return entry points and the methods that run implicitly around them (model attributes, binders)."""
    items, implicit, duplicates = [], [], []
    for fqn in sorted(facts):
        cls = facts[fqn]
        if cls.get('synthetic'):
            continue
        class_annotations = cls.get('annotations', [])
        class_mapping = _ann(class_annotations, 'RequestMapping')
        class_paths = _paths(class_mapping['values']) if class_mapping else ['']
        class_verbs = [str(v).split('.')[-1] for v in _as_list((class_mapping or {}).get('values', {}).get('method'))]
        jaxrs_class = _ann(class_annotations, 'Path')
        parents = supertypes(fqn, facts, facts)
        servlet = any(p.endswith('.http.HttpServlet') for p in parents)
        servlet_paths = _paths((_ann(class_annotations, 'WebServlet') or {}).get('values', {})) if servlet else []
        is_filter = any(p in ('javax.servlet.Filter', 'jakarta.servlet.Filter') for p in parents)
        is_action = any(p == 'org.apache.struts.action.Action' for p in parents)
        for method in cls.get('methods', []):
            if method['synthetic'] or method['bridge']:
                continue
            annotations = method.get('annotations', [])
            names = {short(a['type']): a for a in annotations}
            found = False
            for name, verbs in list(SPRING_VERBS.items()) + [('RequestMapping', None)]:
                if name not in names:
                    continue
                values = names[name].get('values', {})
                http = verbs or [str(v).split('.')[-1] for v in _as_list(values.get('method'))] or class_verbs or ['ANY']
                paths = sorted({join_path(c, m) for c in class_paths for m in _paths(values)})
                items.append(_entry('HTTP_ENDPOINT', cls, method, http, paths, None,
                    [f"@{short(names[name]['type'])}{values or ''} on {short(fqn)}.{method['name']}"] +
                    ([f"class-level @RequestMapping{class_mapping['values']}"] if class_mapping else []), facts))
                found = True
                break
            if not found and (JAXRS_VERBS & set(names)):
                verb = sorted(JAXRS_VERBS & set(names))[0]
                base = (jaxrs_class or {}).get('values', {}).get('value', '')
                sub = (names.get('Path') or {}).get('values', {}).get('value', '')
                items.append(_entry('HTTP_ENDPOINT', cls, method, [verb], [join_path(base, sub)], None,
                    [f"JAX-RS @{verb} on {short(fqn)}.{method['name']}"] + ([f"class @Path('{base}')"] if base else []), facts))
                found = True
            if not found:
                for name, (kind, key) in LISTENERS.items():
                    if name in names:
                        values = names[name].get('values', {})
                        trigger = ', '.join(str(v) for v in _as_list(values.get(key))) or (
                            'application event of type ' + (method['parameters'][0] if method['parameters'] else 'unknown'))
                        items.append(_entry(kind, cls, method, [], [], trigger, [f'@{name}{values or ""}'], facts))
                        found = True
                        break
            if not found and 'Scheduled' in names:
                values = names['Scheduled'].get('values', {})
                trigger = ('cron ' + values['cron']) if values.get('cron') else ('every %s ms' % values['fixedRate']) if values.get('fixedRate', -1) != -1 else 'schedule defined by configuration'
                items.append(_entry('SCHEDULED_JOB', cls, method, [], [], trigger, [f'@Scheduled{values or ""}'], facts))
                found = True
            if not found and 'PostConstruct' in names:
                items.append(_entry('LIFECYCLE_CALLBACK', cls, method, [], [], 'runs once after the bean is created', ['@PostConstruct'], facts))
                found = True
            if not found and servlet and method['name'] in SERVLET_VERBS:
                items.append(_entry('SERVLET', cls, method, [SERVLET_VERBS[method['name']]], [join_path('', p) for p in servlet_paths if p] or ['(mapped in web.xml)'],
                    None, [f"{short(fqn)} extends HttpServlet and overrides {method['name']}"], facts))
                found = True
            if not found and is_filter and method['name'] == 'doFilter':
                items.append(_entry('SERVLET_FILTER', cls, method, ['ANY'], ['(every request matching the filter mapping)'], None,
                    [f'{short(fqn)} implements Filter'], facts))
                found = True
            if not found and is_action and method['name'] == 'execute':
                items.append(_entry('STRUTS_ACTION', cls, method, ['ANY'], ['(mapped in struts-config.xml)'], None,
                    [f'{short(fqn)} extends org.apache.struts.action.Action'], facts))
                found = True
            if not found and _jvm_main(method):
                items.append(_entry('MAIN_METHOD', cls, method, [], [], 'started from the command line', ['public static void main(String[])'], facts))
                found = True
            if not found and ({'ModelAttribute', 'InitBinder'} & set(names)) and not method['static']:
                implicit.append(dict(class_name=fqn, method=method['name'], descriptor=method['descriptor'],
                    annotation=sorted({'ModelAttribute', 'InitBinder'} & set(names))[0]))
    seen = {}
    for item in items:
        for verb in item['http_methods'] or ['-']:
            for path in item['paths'] or ['-']:
                if item['kind'] != 'HTTP_ENDPOINT':
                    continue
                key = (verb, path)
                if key in seen and seen[key] != item['id']:
                    duplicates.append(dict(http_method=verb, path=path, handlers=[seen[key], item['id']]))
                seen.setdefault(key, item['id'])
    return dict(items=items, implicit_methods=implicit, duplicate_routes=duplicates)


def describe(entry: dict) -> str:
    if entry['kind'] in ('HTTP_ENDPOINT', 'SERVLET', 'SERVLET_FILTER', 'STRUTS_ACTION'):
        return ', '.join(f'{v} {p}' for v in entry['http_methods'] for p in entry['paths'])
    return f"{entry['kind'].replace('_', ' ').lower()}: {entry['trigger']}"
