"""Architectural role of a class, always with the evidence that produced it.

Order of evidence strength: annotation > type hierarchy > declared entry methods > naming convention.
A class with no evidence is UNKNOWN, never guessed.
"""
from __future__ import annotations

ROLE_LAYER = {
    'CONTROLLER': 'PRESENTATION', 'FILTER': 'PRESENTATION', 'SERVLET': 'PRESENTATION', 'ACTION': 'PRESENTATION',
    'SERVICE': 'SERVICE', 'COMPONENT': 'SERVICE', 'LISTENER': 'SERVICE', 'SCHEDULED_JOB': 'SERVICE', 'VALIDATOR': 'SERVICE',
    'REPOSITORY': 'DATA_ACCESS',
    'ENTITY': 'DOMAIN', 'MODEL': 'DOMAIN',
    'CONFIGURATION': 'CONFIGURATION', 'APPLICATION': 'CONFIGURATION',
    'EXCEPTION': 'SUPPORT', 'UTILITY': 'SUPPORT', 'UNKNOWN': 'SUPPORT',
}
LAYER_ORDER = ['PRESENTATION', 'SERVICE', 'DATA_ACCESS', 'DOMAIN', 'CONFIGURATION', 'SUPPORT']
LAYER_LABEL = {
    'PRESENTATION': 'Presentation (controllers, servlets, filters)', 'SERVICE': 'Services and application logic',
    'DATA_ACCESS': 'Data access (repositories, DAOs)', 'DOMAIN': 'Domain model (entities, models)',
    'CONFIGURATION': 'Configuration and bootstrap', 'SUPPORT': 'Supporting code (no role evidence)'}
ROLE_PLAIN = {
    'CONTROLLER': 'receives web requests from users or other systems',
    'FILTER': 'inspects every web request before it reaches the application',
    'SERVLET': 'handles web requests directly (older Java web style)',
    'ACTION': 'handles a web request in the Struts framework',
    'SERVICE': 'holds business rules that controllers call',
    'COMPONENT': 'is a helper managed by the application framework',
    'LISTENER': 'reacts to messages or events',
    'SCHEDULED_JOB': 'runs automatically on a timer',
    'VALIDATOR': 'checks that input data is valid',
    'REPOSITORY': 'reads and writes data in the database',
    'ENTITY': 'represents a record stored in the database',
    'MODEL': 'carries data between parts of the application',
    'CONFIGURATION': 'sets up how the application runs',
    'APPLICATION': 'starts the application',
    'EXCEPTION': 'describes an error condition',
    'UTILITY': 'offers shared helper functions',
    'UNKNOWN': 'has no clear role signal in the code',
}

_ANNOTATION_ROLES = [
    ({'RestController', 'Controller', 'ControllerAdvice', 'RestControllerAdvice', 'Path'}, 'CONTROLLER'),
    ({'WebServlet'}, 'SERVLET'), ({'WebFilter'}, 'FILTER'),
    ({'Repository'}, 'REPOSITORY'),
    ({'Entity', 'MappedSuperclass', 'Embeddable', 'Table', 'Document'}, 'ENTITY'),
    ({'Service'}, 'SERVICE'),
    ({'SpringBootApplication'}, 'APPLICATION'),
    ({'Configuration', 'EnableCaching', 'EnableScheduling'}, 'CONFIGURATION'),
    ({'XmlRootElement'}, 'MODEL'),
    ({'Component'}, 'COMPONENT'),
]
_HIERARCHY_ROLES = [
    (('org.springframework.data.repository.', 'org.springframework.data.jpa.repository.'), 'REPOSITORY'),
    (('javax.servlet.http.HttpServlet', 'jakarta.servlet.http.HttpServlet'), 'SERVLET'),
    (('javax.servlet.Filter', 'jakarta.servlet.Filter'), 'FILTER'),
    (('org.apache.struts.action.Action',), 'ACTION'),
    (('org.springframework.validation.Validator',), 'VALIDATOR'),
    (('org.springframework.web.servlet.config.annotation.WebMvcConfigurer',), 'CONFIGURATION'),
    (('java.lang.Exception', 'java.lang.RuntimeException', 'java.lang.Throwable', 'java.lang.Error'), 'EXCEPTION'),
]
_LISTENERS = {'KafkaListener', 'JmsListener', 'RabbitListener', 'EventListener', 'StreamListener', 'SqsListener'}
_NAMING = [
    (('Controller', 'Resource', 'Endpoint'), 'CONTROLLER'), (('Repository', 'Dao', 'DAO'), 'REPOSITORY'),
    (('Service', 'ServiceImpl', 'Manager', 'Facade'), 'SERVICE'), (('Entity',), 'ENTITY'),
    (('Dto', 'DTO', 'Request', 'Response', 'Model'), 'MODEL'), (('Config', 'Configuration'), 'CONFIGURATION'),
    (('Exception', 'Error'), 'EXCEPTION'), (('Utils', 'Util', 'Helper', 'Helpers'), 'UTILITY'),
    (('Listener', 'Consumer', 'Handler'), 'LISTENER'), (('Job', 'Scheduler', 'Task'), 'SCHEDULED_JOB'),
    (('Validator',), 'VALIDATOR'), (('Filter',), 'FILTER'), (('Action',), 'ACTION'),
]


def short(name: str) -> str:
    return name.rsplit('.', 1)[-1]


def supertypes(fqn: str, facts: dict, classes: dict) -> list[str]:
    """All supertypes reachable through internal classes (external supertypes are terminal)."""
    seen, stack, out = set(), [fqn], []
    while stack:
        current = stack.pop()
        info = facts.get(current)
        if info:
            parents = ([info['super_name']] if info.get('super_name') else []) + list(info.get('interfaces', []))
        else:
            parents = []
        for parent in parents:
            if parent and parent not in seen:
                seen.add(parent)
                out.append(parent)
                if parent in facts:
                    stack.append(parent)
    return out


def classify(fqn: str, cls: dict, facts: dict, classes: dict) -> dict:
    info = facts.get(fqn) or {}
    annotations = [a['type'] for a in info.get('annotations', [])] or list(cls.get('annotations', []))
    simple = {short(a): a for a in annotations}
    for names, role in _ANNOTATION_ROLES:
        hit = next((simple[n] for n in sorted(names) if n in simple), None)
        if hit:
            return dict(role=role, layer=ROLE_LAYER[role], evidence='ANNOTATION', reason=f'annotated @{hit}', plain=ROLE_PLAIN[role])
    parents = supertypes(fqn, facts, classes)
    for prefixes, role in _HIERARCHY_ROLES:
        hit = next((p for p in parents if any(p == x or p.startswith(x) for x in prefixes)), None)
        if hit:
            kind = 'implements' if hit in (info.get('interfaces') or []) else 'extends'
            return dict(role=role, layer=ROLE_LAYER[role], evidence='TYPE_HIERARCHY', reason=f'{kind} {hit}', plain=ROLE_PLAIN[role])
    methods = info.get('methods') or cls.get('methods') or []
    method_annotations = {short(a['type'] if isinstance(a, dict) else a) for m in methods for a in m.get('annotations', [])}
    if method_annotations & _LISTENERS:
        hit = sorted(method_annotations & _LISTENERS)[0]
        return dict(role='LISTENER', layer='SERVICE', evidence='METHOD_ANNOTATION', reason=f'declares a method annotated @{hit}', plain=ROLE_PLAIN['LISTENER'])
    if 'Scheduled' in method_annotations:
        return dict(role='SCHEDULED_JOB', layer='SERVICE', evidence='METHOD_ANNOTATION', reason='declares a method annotated @Scheduled', plain=ROLE_PLAIN['SCHEDULED_JOB'])
    if any(m.get('name') == 'main' and m.get('static', True) and (m.get('descriptor') == '([Ljava/lang/String;)V' or 'main(java.lang.String[])' in (m.get('signature') or '')) for m in methods):
        return dict(role='APPLICATION', layer='CONFIGURATION', evidence='STRUCTURE', reason='declares public static void main(String[])', plain=ROLE_PLAIN['APPLICATION'])
    name = short(fqn).split('$')[0]
    for suffixes, role in _NAMING:
        hit = next((s for s in suffixes if name.endswith(s) and name != s), None)
        if hit:
            return dict(role=role, layer=ROLE_LAYER[role], evidence='NAMING', reason=f"class name ends with '{hit}' (naming convention only; weaker evidence)", plain=ROLE_PLAIN[role])
    package_parts = set(cls.get('package_name', fqn.rpartition('.')[0]).split('.'))
    if package_parts & {'model', 'models', 'dto', 'domain', 'entity', 'entities'}:
        part = sorted(package_parts & {'model', 'models', 'dto', 'domain', 'entity', 'entities'})[0]
        return dict(role='MODEL', layer='DOMAIN', evidence='NAMING', reason=f"package segment '{part}' (naming convention only)", plain=ROLE_PLAIN['MODEL'])
    return dict(role='UNKNOWN', layer='SUPPORT', evidence='NONE', reason='no role annotation, framework supertype, entry method or naming convention found', plain=ROLE_PLAIN['UNKNOWN'])
