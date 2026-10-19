"""Supported method annotations that declare externally triggerable work.

Annotation names are matched together with their package, so a project's own `@GET` or `@Scheduled`
is not mistaken for a framework entry point. A bare simple name (legacy snapshots without package
information) is still accepted.
"""

ENTRY_ANNOTATIONS = {
    # Spring MVC / WebFlux
    'RequestMapping': ('org.springframework.web.bind.annotation.',), 'GetMapping': ('org.springframework.web.bind.annotation.',),
    'PostMapping': ('org.springframework.web.bind.annotation.',), 'PutMapping': ('org.springframework.web.bind.annotation.',),
    'DeleteMapping': ('org.springframework.web.bind.annotation.',), 'PatchMapping': ('org.springframework.web.bind.annotation.',),
    # JAX-RS (javax and jakarta)
    **{verb: ('javax.ws.rs.', 'jakarta.ws.rs.') for verb in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS')},
    # Background and message-driven entry points
    'Scheduled': ('org.springframework.scheduling.annotation.', 'jakarta.ejb.', 'javax.ejb.'),
    'KafkaListener': ('org.springframework.kafka.annotation.',), 'JmsListener': ('org.springframework.jms.annotation.',),
    'RabbitListener': ('org.springframework.amqp.rabbit.annotation.',), 'SqsListener': ('io.awspring.cloud.sqs.annotation.', 'org.springframework.cloud.aws.messaging.listener.annotation.'),
    'EventListener': ('org.springframework.context.event.',), 'MessageMapping': ('org.springframework.messaging.handler.annotation.',),
}
METHOD_ENTRY_ANNOTATIONS = frozenset(ENTRY_ANNOTATIONS)


def is_entry_annotation(annotation):
    simple = annotation.rsplit('.', 1)[-1]
    packages = ENTRY_ANNOTATIONS.get(simple)
    if packages is None:
        return False
    return '.' not in annotation or any(annotation.startswith(p) for p in packages)


def is_method_entry_point(annotations):
    return any(is_entry_annotation(annotation) for annotation in annotations)
