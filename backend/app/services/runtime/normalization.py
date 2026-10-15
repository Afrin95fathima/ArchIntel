"""OTLP wire decoding and strict architectural attribute allowlist. No raw payload storage."""
import gzip
import io
import json
import re
from .mapping import DESCRIPTOR
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

IDENTITY = re.compile(r'^[\w.$/;<>\[\]-]{1,400}$')
ALLOWED = {'code.namespace','code.function','code.function.name','code.function.namespace',
    'code.method.name','code.method.descriptor','http.request.method','http.method','http.route',
    'db.system','db.system.name','db.operation','db.operation.name','db.collection.name','db.namespace','server.address',
    'messaging.system','messaging.operation.type','messaging.operation','messaging.destination.name',
    'exception.type','archintel.event_type'}


def decode(body: bytes, content_type: str, encoding: str, maximum: int) -> dict:
    if encoding == 'gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as zipped:
            body = zipped.read(maximum + 1)
    elif encoding not in ('', 'identity'):
        raise ValueError('Only identity and gzip encodings are supported.')
    if len(body) > maximum:
        raise ValueError('Decoded telemetry exceeds the configured size limit.')
    if content_type.split(';')[0] == 'application/x-protobuf':
        request = ExportTraceServiceRequest.FromString(body)
        data = MessageToDict(request, preserving_proto_field_name=False)
        # Protobuf JSON uses base64; OTLP JSON specifically uses hexadecimal IDs.
        import base64
        for resource in data.get('resourceSpans', []):
            for scope in resource.get('scopeSpans', []):
                for span in scope.get('spans', []):
                    for key in ('traceId','spanId','parentSpanId'):
                        if key in span: span[key] = base64.b64decode(span[key]).hex()
        return data
    if content_type.split(';')[0] != 'application/json':
        raise ValueError('Use OTLP HTTP application/x-protobuf or application/json.')
    data = json.loads(body)
    if not isinstance(data, dict): raise ValueError('Expected an OTLP object.')
    return data


def attributes(items, resource=False):
    result = {}
    for item in items:
        key = item.get('key')
        allowed = {'service.name','service.version','archintel.artifact.sha256'} if resource else ALLOWED
        if key not in allowed: continue
        value = item.get('value', {}).get('stringValue')
        if isinstance(value, str) and len(value) <= 400:
            if key == 'code.method.descriptor':
                if DESCRIPTOR.fullmatch(value):result[key]=value
            elif key == 'archintel.artifact.sha256':
                if re.fullmatch(r'[0-9a-fA-F]{64}',value):result[key]=value.lower()
            elif key == 'http.route':
                if value.startswith('/') and '?' not in value and '\n' not in value:
                    result[key] = value
            elif IDENTITY.fullmatch(value): result[key] = value
    return result


def normalize(data: dict, maximum: int) -> list[dict]:
    events = []
    for resource in data.get('resourceSpans', []):
        resource_attrs=attributes(resource.get('resource',{}).get('attributes',[]),resource=True)
        for scope in resource.get('scopeSpans', []):
            for span in scope.get('spans', []):
                if len(events) >= maximum: raise ValueError('Batch span limit exceeded.')
                trace, identity, parent = [str(span.get(k, '')).lower() for k in ('traceId','spanId','parentSpanId')]
                if not re.fullmatch('[0-9a-f]{32}', trace) or int(trace,16) == 0 or not re.fullmatch('[0-9a-f]{16}', identity) or int(identity,16) == 0:
                    raise ValueError('Invalid trace or span identity.')
                if parent and not re.fullmatch('[0-9a-f]{16}', parent): raise ValueError('Invalid parent span identity.')
                if parent == identity:raise ValueError('A span cannot be its own parent.')
                if parent == '0'*16: parent = ''
                start, end = int(span.get('startTimeUnixNano',0)), int(span.get('endTimeUnixNano',0))
                if start <= 0 or end < start or end > 9223372036854775807: raise ValueError('Invalid span timestamps.')
                attrs = attributes(span.get('attributes', []))
                for event in span.get('events', []):
                    attrs.update({k:v for k,v in attributes(event.get('attributes',[])).items() if k=='exception.type'})
                cls = attrs.get('code.namespace') or attrs.get('code.function.namespace')
                method = attrs.get('code.function') or attrs.get('code.method.name')
                function = attrs.get('code.function.name')
                if not method and function:
                    if cls: method = function.rsplit('.',1)[-1]
                    elif '.' in function: cls, method = function.rsplit('.',1)
                kind = span.get('kind', 0)
                kind = {'SPAN_KIND_SERVER':2,'SPAN_KIND_CLIENT':3,'SPAN_KIND_PRODUCER':4,'SPAN_KIND_CONSUMER':5}.get(kind,kind)
                db = attrs.get('db.system.name') or attrs.get('db.system')
                http = attrs.get('http.request.method') or attrs.get('http.method')
                messaging = attrs.get('messaging.system')
                category = 'DATABASE_CALL' if db else 'HTTP_SERVER' if http and kind==2 else 'HTTP_CLIENT' if http else 'MESSAGE_PUBLISH' if messaging and kind==4 else 'MESSAGE_CONSUME' if messaging else 'METHOD_CALL' if cls and method else 'OTHER'
                if db in ('redis','memcached'): category = 'CACHE_CALL'
                if attrs.get('archintel.event_type') == 'SCHEDULED_JOB': category = 'SCHEDULED_JOB'
                error = span.get('status',{}).get('code') in (2,'STATUS_CODE_ERROR') or 'exception.type' in attrs
                events.append(dict(trace_id=trace,span_id=identity,parent_span_id=parent or None,
                    timestamp=start,end_timestamp=end,duration_ms=(end-start)/1e6,
                    class_name=cls,method_name=method,event_type=category,error=error,
                    method_descriptor=attrs.get('code.method.descriptor'),
                    invalid_method_descriptor=any(a.get('key')=='code.method.descriptor' for a in span.get('attributes',[])) and 'code.method.descriptor' not in attrs,
                    service_name=resource_attrs.get('service.name'),service_version=resource_attrs.get('service.version'),
                    artifact_sha256=resource_attrs.get('archintel.artifact.sha256'),
                    invalid_resource_identity=any(a.get('key') in ('service.name','archintel.artifact.sha256') and a.get('key') not in resource_attrs for a in resource.get('resource',{}).get('attributes',[])),
                    http_route=attrs.get('http.route'),http_method=http,database_system=db,
                    database_operation=attrs.get('db.operation.name') or attrs.get('db.operation'),
                    database_table=attrs.get('db.collection.name'),database_namespace=attrs.get('db.namespace'),database_server=attrs.get('server.address'),messaging_system=messaging,
                    messaging_destination=attrs.get('messaging.destination.name'),exception_type=attrs.get('exception.type'),attributes=attrs))
    return events
