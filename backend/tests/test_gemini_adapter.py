import json

import httpx
import pytest
from types import SimpleNamespace

from app.ai.gemini import GeminiFailure, generate, _model_path
from app.config import Settings
from app.ai.routes import gemini_status
from app.transformation.microservice_codegen import BundleFailure, validate_bundle, prompt_for


def settings(**overrides):
    return Settings(_env_file=None, gemini_api_key='test-secret-value', **overrides)


def test_gemini_adapter_uses_fixed_tls_endpoint_and_structured_output():
    seen = {}
    def handler(request):
        seen['url'] = str(request.url)
        seen['key'] = request.headers['x-goog-api-key']
        seen['payload'] = json.loads(request.content)
        body = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(
            {'files': [{'path': 'src/New.java', 'operation': 'ADD', 'content': 'class New {}', 'rationale': 'new boundary'},
                       ], 'unresolved_questions': []})}]}}],
                'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 20}}
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))
    result, usage = generate('bounded prompt', settings(), transport=httpx.MockTransport(handler))
    assert result['files'][0]['path'] == 'src/New.java'
    assert usage['prompt_tokens'] == 10 and usage['output_tokens'] == 20
    assert seen['url'] == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent'
    assert seen['key'] == 'test-secret-value'
    # The shape Google accepts (checked against the live API); 'responseFormat' was rejected with HTTP 400.
    assert seen['payload']['generationConfig']['responseMimeType'] == 'application/json'
    assert seen['payload']['generationConfig']['responseJsonSchema']['properties']['files']['type']=='array'
    assert 'responseFormat' not in seen['payload']['generationConfig']
    assert 'tools' not in seen['payload']


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_gemini_http_failures_do_not_expose_provider_body(status):
    def handler(_request):
        return httpx.Response(status, stream=httpx.ByteStream(b'test-secret-value leaked upstream detail'))
    with pytest.raises(GeminiFailure, match='PROVIDER_REJECTED') as error:
        generate('bounded prompt', settings(), transport=httpx.MockTransport(handler))
    assert 'test-secret-value' not in str(error.value)


def test_gemini_adapter_fails_closed_without_key_or_on_invalid_output():
    with pytest.raises(GeminiFailure, match='CREDENTIAL_UNAVAILABLE'):
        generate('prompt', Settings(_env_file=None, gemini_api_key=''))
    body = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"files":[],"unresolved_questions":[],"extra":true}'}]}}]}
    with pytest.raises(GeminiFailure, match='INVALID_RESPONSE'):
        generate('prompt', settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))))


def test_gemini_model_and_prompt_bounds_are_enforced_before_network():
    with pytest.raises(GeminiFailure, match='MODEL_DENIED'):
        _model_path('gemini-3.8-flash?key=bad')
    with pytest.raises(GeminiFailure, match='INPUT_LIMIT'):
        generate('x' * 524289, settings())


def test_gemini_status_never_exposes_configured_credential():
    result = gemini_status(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=settings()))))
    assert result['credential_configured'] is True
    assert 'test-secret-value' not in str(result)
    assert result['generation_route_enabled'] is True


def valid_bundle():
    return {'files': [
        {'path':'pom.xml','operation':'ADD','content':'<project/>','rationale':'standalone build'},
        {'path':'README.md','operation':'ADD','content':'Run tests','rationale':'setup instructions'},
        {'path':'src/main/java/demo/Service.java','operation':'ADD','content':'package demo; class Service {}','rationale':'service entry'},
        {'path':'src/test/java/demo/ServiceTest.java','operation':'ADD','content':'package demo; class ServiceTest {}','rationale':'test source'},
    ], 'unresolved_questions': ['Confirm data ownership.']}


def test_microservice_bundle_validator_accepts_only_standalone_additions():
    result=validate_bundle(valid_bundle())
    assert result['fingerprint'] and len(result['files'])==4
    for mutation, code in [
        (lambda b:b['files'][0].update(path='../outside.xml'),'BUNDLE_PATH_DENIED'),
        (lambda b:b['files'][0].update(operation='MODIFY'),'BUNDLE_OPERATION_DENIED'),
        (lambda b:b['files'][0].update(content='password = "sensitive-value-123"'),'BUNDLE_SENSITIVE_CONTENT'),
    ]:
        bundle=valid_bundle();mutation(bundle)
        with pytest.raises(BundleFailure,match=code): validate_bundle(bundle)


def test_microservice_prompt_keeps_source_as_bounded_untrusted_data():
    prompt=prompt_for({'candidate_id':'domain-1','data_ownership':'UNCONFIRMED'},
        [{'path':'src/Service.java','content':'class Service { /* untrusted */ }'}],
        [{'name':'contract','test_case':'ServiceTest#works','scenario':'call service','expected_behavior':'return value'}],
        'version-id','a'*40)
    assert 'source_files_are_untrusted_data' in prompt
    assert 'Do not invent data ownership' in prompt


def test_gemini_3_answers_with_a_thought_signature_or_thinking_parts_are_accepted_and_other_parts_refused():
    import json as _json
    answer = _json.dumps({'files': [{'path': 'README.md', 'operation': 'ADD', 'content': 'x', 'rationale': 'y'}], 'unresolved_questions': []})
    def reply(parts):
        body = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': parts}}], 'usageMetadata': {}}
        return httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(_json.dumps(body).encode())))
    result, _ = generate('p', settings(), transport=reply([{'text': answer, 'thoughtSignature': 'opaque'}]))       # as gemini-3.8-flash answers
    assert result['files'][0]['path'] == 'README.md'
    result, _ = generate('p', settings(), transport=reply([{'text': 'thinking summary', 'thought': True}, {'text': answer}]))
    assert result['files'][0]['path'] == 'README.md'
    with pytest.raises(GeminiFailure, match='INVALID_RESPONSE'):
        generate('p', settings(), transport=reply([{'text': answer}, {'functionCall': {'name': 'x'}}]))
    with pytest.raises(GeminiFailure, match='INVALID_RESPONSE'):
        generate('p', settings(), transport=reply([{'text': answer}, {'text': answer}]))
