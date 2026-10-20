"""WP8: specific next-test suggestions for unobserved entry points.

Everything is derived from bytecode: route annotations, parameter types and validation constraints,
and static reachability over the call graph (class-hierarchy analysis, so reachability over-approximates;
the expected gain is therefore labelled an upper bound from the static graph).
"""
from __future__ import annotations

import re

from .bytecode import base_type
from .callgraph import method_key
from .entrypoints import describe
from .roles import method_label, short

SAMPLE = {'int': '1', 'long': '1', 'short': '1', 'byte': '1', 'double': '1.5', 'float': '1.5', 'boolean': 'true', 'char': 'a',
    'java.lang.Integer': '1', 'java.lang.Long': '1', 'java.lang.String': 'example', 'java.lang.Boolean': 'true', 'java.lang.Double': '1.5',
    'java.time.LocalDate': '2024-01-15', 'java.time.LocalDateTime': '2024-01-15T10:30:00', 'java.util.UUID': '123e4567-e89b-12d3-a456-426614174000',
    'java.math.BigDecimal': '10.00'}
CONSTRAINT_TEXT = {'NotBlank': 'must not be blank', 'NotNull': 'must be present', 'NotEmpty': 'must not be empty', 'Email': 'must be an email address',
    'Past': 'must be in the past', 'Future': 'must be in the future', 'Positive': 'must be greater than zero'}


def _sample(type_name: str, pattern: str | None = None, regexp: str | None = None) -> str:
    if pattern and type_name.startswith('java.time'):
        return '2024-01-15' if pattern == 'yyyy-MM-dd' else SAMPLE.get(type_name, 'value')
    if regexp:
        digits = re.fullmatch(r'\\d\{(\d+)\}', regexp)
        if digits:
            return '1' * int(digits.group(1))
    return SAMPLE.get(type_name, 'example')


def _constraint(annotation: dict) -> str:
    name, values = annotation['type'].rsplit('.', 1)[-1], annotation['values']
    if name == 'Pattern':
        return f"must match {values.get('regexp')}"
    if name == 'Size':
        return f"length between {values.get('min', 0)} and {values.get('max', 'unbounded')}"
    if name == 'Digits':
        return f"at most {values.get('integer')} integer digits"
    return CONSTRAINT_TEXT.get(name, name)


def form_fields(facts: dict, type_name: str, seen: set | None = None) -> list[dict]:
    """Settable fields of a form/model type including inherited ones, with validation constraints."""
    seen = seen or set()
    info = facts.get(type_name)
    if not info or type_name in seen:
        return []
    seen.add(type_name)
    fields = form_fields(facts, info['super_name'], seen) if info.get('super_name') else []
    setters = {m['name'] for m in info['methods'] if m['name'].startswith('set')}
    for field in info['fields']:
        if field['static'] or field['synthetic'] or field['final']:
            continue
        if any(a['type'].endswith(('persistence.Id', 'persistence.GeneratedValue')) for a in field['annotations']):
            continue                                  # database-generated key, not user input
        if 'set' + field['name'][:1].upper() + field['name'][1:] not in setters:
            continue
        constraints = [a for a in field['annotations'] if a['type'].startswith(('jakarta.validation.', 'javax.validation.'))]
        fmt = next((a['values'].get('pattern') for a in field['annotations'] if a['type'].endswith('DateTimeFormat')), None)
        regexp = next((a['values'].get('regexp') for a in constraints if a['type'].endswith('Pattern')), None)
        fields.append(dict(name=field['name'], type=field['type'], required=any(c['type'].rsplit('.', 1)[-1] in ('NotBlank', 'NotNull', 'NotEmpty') for c in constraints),
            constraints=[_constraint(c) for c in constraints], format=fmt, example=_sample(field['type'], fmt, regexp)))
    return fields


def _observed_methods(model):
    return getattr(model, 'observed_methods', None)


def _entry_state(model, entry) -> str:
    """OBSERVED / NOT_OBSERVED / UNKNOWN for one entry point under the selected sessions."""
    if model.observed_classes is None:
        return 'UNKNOWN'
    methods = _observed_methods(model)
    if methods is not None:
        return 'OBSERVED' if (entry['handler_class'], entry['handler_method']) in methods else 'NOT_OBSERVED'
    return 'OBSERVED' if entry['handler_class'] in model.observed_classes else 'NOT_OBSERVED'


def _reach(model, entry, implicit):
    graph = model.callgraph
    start = method_key(entry['handler_class'], entry['handler_method'], entry['handler_descriptor'])
    starts = [start] + [method_key(i['class_name'], i['method'], i['descriptor']) for i in implicit if i['class_name'] == entry['handler_class']]
    reached = graph.reachable(starts)
    methods = {k for k in reached['methods'] if not graph.methods[k]['synthetic'] and not graph.methods[k]['bridge']}
    classes = {model.owners.get(k.split('#')[0], k.split('#')[0]) for k in reached['methods']}
    return methods, classes, reached['truncated']


def _steps(entry, params, body, preconditions):
    steps = []
    if entry['kind'] == 'HTTP_ENDPOINT':
        verb, path = entry['http_methods'][0], entry['paths'][0]
        if preconditions:
            steps.append('Make sure: ' + '; '.join(preconditions) + '.')
        if verb == 'GET' and not body and not any(p['binding'] == 'query' for p in params):
            steps.append(f'Open {path} in the browser or send GET {path}.')
        elif verb == 'GET':
            steps.append(f'Send GET {path} with the query parameters listed in the sample request.')
        else:
            steps.append(f'Submit the form or send {verb} {path} with the fields in the sample request.')
        if body:
            required = [f['name'] for f in body if f['required']]
            if required:
                steps.append('Fill in the required fields: ' + ', '.join(required) + '.')
    elif entry['kind'] == 'SCHEDULED_JOB':
        steps.append(f"Wait for the schedule ({entry['trigger']}) or trigger the job through its scheduler in a test environment.")
    elif entry['kind'] == 'MESSAGE_LISTENER':
        steps.append(f"Publish a message to {entry['trigger']} so the listener {entry['handler_method']}() receives it.")
    elif entry['kind'] == 'EVENT_LISTENER':
        steps.append(f"Cause the application to publish a {entry['trigger'].replace('application event of type ', '')} event.")
    elif entry['kind'] in ('SERVLET', 'SERVLET_FILTER', 'STRUTS_ACTION'):
        steps.append(f"Send {entry['http_methods'][0]} to {entry['paths'][0]}.")
    elif entry['kind'] == 'MAIN_METHOD':
        steps.append('Run the program from the command line.')
    return steps


def _edge_cases(entry, params, body, methods_graph, handler_methods):
    cases = []
    for field in body:
        for constraint in field['constraints']:
            if constraint in ('must be present', 'must not be blank', 'must not be empty'):
                cases.append(f"Leave {field['name']} empty: the validation error path should run and the form should be shown again.")
            elif constraint.startswith('must match'):
                cases.append(f"Send {field['name']} that does not satisfy '{constraint}'.")
    for p in params:
        if p['binding'] == 'path':
            cases.append(f"Use a {p['name'] or 'path variable'} value that does not exist to exercise the not-found path.")
    if any(h['name'] == 'hasErrors' for h in handler_methods):
        cases.append('Submit invalid data so BindingResult.hasErrors() is true.')
    return list(dict.fromkeys(cases))[:8]


def build(model, rules_note: bool = True) -> dict:
    if not model.facts_available:
        return dict(status='NOT_AVAILABLE', suggestions=[], reason='Bytecode facts are not available for this analysis (run a new analysis); routes and call paths cannot be derived.')
    entries = model.entry_points['items']
    implicit = model.entry_points['implicit_methods']
    prepared = []
    for entry in entries:
        if entry['kind'] == 'LIFECYCLE_CALLBACK':
            continue
        state = _entry_state(model, entry)
        methods, classes, truncated = _reach(model, entry, implicit)
        prepared.append(dict(entry=entry, state=state, methods=methods, classes=classes, truncated=truncated))
    observed = model.observed_classes
    covered_classes = set(observed or ())
    observed_methods = _observed_methods(model)
    covered_methods = {m for m in model.callgraph.methods if observed_methods and (m.split('#')[0], m.split('#')[1].split('(')[0]) in observed_methods}
    pending = [p for p in prepared if p['state'] != 'OBSERVED']
    ranked = []
    while pending:
        def gain(p):
            return (len(p['classes'] - covered_classes), len(p['methods'] - covered_methods))
        best = max(pending, key=lambda p: (gain(p), p['entry']['id']))
        pending.remove(best)
        ranked.append((best, gain(best)))
        covered_classes |= best['classes']
        covered_methods |= best['methods']
    suggestions = []
    for rank, (p, (new_classes, new_methods)) in enumerate(ranked, 1):
        entry = p['entry']
        standalone_classes = p['classes'] - set(observed or ())
        body = []
        forms = [param for param in entry['parameters'] if param['binding'] == 'form' and param['type'] in model.facts]
        # A @Valid form object is what the user submits; other model attributes are populated from the path or a @ModelAttribute method.
        submitted = [param for param in forms if 'Valid' in param['constraints']] or forms
        for param in submitted:
            body += form_fields(model.facts, param['type'])
        path_params = [dict(name=pr['name'] or f"arg{pr['index']}", type=pr['type'], example=_sample(pr['type'])) for pr in entry['parameters'] if pr['binding'] == 'path']
        if entry['paths']:
            declared = {pv['name'] for pv in path_params}
            for placeholder in re.findall(r'\{([A-Za-z_]\w*)(?::[^}]*)?\}', entry['paths'][0]):
                if placeholder not in declared:
                    path_params.append(dict(name=placeholder, type='path variable bound outside the handler (for example by a @ModelAttribute method)', example='1'))
        query = [dict(name=pr['name'] or f"arg{pr['index']}", type=pr['type'], required=bool(pr['required']), default=pr['default'], example=pr['default'] or _sample(pr['type']),
            constraints=pr['constraints']) for pr in entry['parameters'] if pr['binding'] == 'query']
        preconditions = []
        for pv in path_params:
            stem = pv['name'][:-2] if pv['name'].endswith('Id') and len(pv['name']) > 2 else None
            match = next((c for c in model.classes if stem and short(c).lower() == stem.lower() and model.roles.get(c, {}).get('role') == 'ENTITY'), None)
            preconditions.append(f"{'an' if short(match)[0] in 'AEIOU' else 'a'} {short(match)} with {pv['name']}={pv['example']} exists in the database" if match else f"{pv['name']}={pv['example']} refers to existing data")
        handler = method_key(entry['handler_class'], entry['handler_method'], entry['handler_descriptor'])
        handler_methods = [dict(name=s['name']) for s in model.callgraph.methods[handler]['invokes']] if handler in model.callgraph.methods else []
        sample_path = entry['paths'][0] if entry['paths'] else None
        for pv in path_params:
            if sample_path:
                sample_path = sample_path.replace('{' + pv['name'] + '}', pv['example'])
        suggestion = dict(
            id=entry['id'], rank=rank, status='SUGGESTED' if p['state'] != 'UNKNOWN' else 'NO_RUNTIME_SESSION', entry_point=dict(kind=entry['kind'], description=describe(entry),
                http_methods=entry['http_methods'], paths=entry['paths'], trigger=entry['trigger'], handler_class=entry['handler_class'],
                handler=method_label(entry['handler_class'], entry['handler_method'])),
            action_steps=_steps(entry, entry['parameters'], body, preconditions),
            sample_request=dict(method=(entry['http_methods'] or [None])[0], path=sample_path, path_parameters=path_params, query_parameters=query,
                form_fields=[dict(name=f['name'], example=f['example'], required=f['required'], constraints=f['constraints']) for f in body]) if entry['kind'] in ('HTTP_ENDPOINT', 'SERVLET') else None,
            preconditions=preconditions, edge_cases=_edge_cases(entry, entry['parameters'], body, None, handler_methods),
            exercises=dict(classes=sorted(p['classes']), methods=sorted(method_label(k.split('#')[0], k.split('#')[1].split('(')[0]) for k in p['methods'])[:80], method_count=len(p['methods']), truncated=p['truncated']),
            expected_gain=dict(new_classes=new_classes, new_methods=new_methods, standalone_new_classes=len(standalone_classes),
                class_names=sorted(p['classes'] - set(observed or ()))[:40],
                basis='Upper bound from static reachability (class-hierarchy analysis) minus what the selected sessions already observed' +
                      ('' if observed is not None else '; no session selected, so everything reachable counts as new') + '; counted after higher-ranked suggestions.'),
            evidence=[f"{e}" for e in entry['evidence']] + [f"reachable methods: {len(p['methods'])}, classes: {len(p['classes'])}"])
        suggestions.append(suggestion)
    done = [dict(id=p['entry']['id'], entry_point=describe(p['entry']), handler=method_label(p['entry']['handler_class'], p['entry']['handler_method']),
        status='DONE') for p in prepared if p['state'] == 'OBSERVED']
    return dict(status='AVAILABLE', suggestions=suggestions, done=done, runtime_included=observed is not None,
        method_level=observed_methods is not None,
        limitation=('Observation is matched per handler method.' if observed_methods is not None else
            'Only class-level observation is available, so an entry point counts as done when its controller class was observed.') if observed is not None else
            'Not measured: no runtime session is selected, so all entry points are listed as suggestions.',
        totals=dict(entry_points=len(prepared), done=len(done), open=len(suggestions)))
