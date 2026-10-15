"""Supported method annotations that declare externally triggerable work."""

METHOD_ENTRY_ANNOTATIONS = frozenset({
    # Spring MVC / WebFlux
    'RequestMapping', 'GetMapping', 'PostMapping', 'PutMapping',
    'DeleteMapping', 'PatchMapping',
    # JAX-RS (including Concord's javax.ws.rs resources)
    'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS',
    # Background and message-driven entry points
    'Scheduled', 'KafkaListener', 'JmsListener', 'RabbitListener',
})


def is_method_entry_point(annotations):
    return any(annotation.rsplit('.', 1)[-1] in METHOD_ENTRY_ANNOTATIONS
               for annotation in annotations)
