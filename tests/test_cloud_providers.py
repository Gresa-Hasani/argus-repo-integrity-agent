import io
import json
import urllib.error

import pytest

from argus.config import Config, load_config
from argus.llm.interface import LLMError, LLMUnavailableError, create_provider


@pytest.mark.parametrize('provider,key,model,host', [('openai', 'OPENAI_API_KEY', 'gpt-4.1-mini', 'api.openai.com'), ('anthropic', 'ANTHROPIC_API_KEY', 'claude-sonnet-4-6', 'api.anthropic.com'), ('claude', 'ANTHROPIC_API_KEY', 'claude-sonnet-4-6', 'api.anthropic.com')])
def test_cloud_config_overrides_local_profile(tmp_path, monkeypatch, provider, key, model, host):
    profile = tmp_path / 'argus.toml'
    profile.write_text('[llm]\nprovider="ollama"\nmodel="argus-gemma3:12b"\nbase_url="http://localhost:11434"\n')
    monkeypatch.setenv(key, 'test-secret')
    cfg = load_config(str(profile), env={'ARGUS_LLM_PROVIDER': provider})
    assert cfg.llm_model == model and host in cfg.llm_base_url
    assert cfg.llm_api_key == 'test-secret'
    assert 'test-secret' not in json.dumps(cfg.public_dict())
    override = load_config(str(profile), env={'ARGUS_LLM_PROVIDER': provider, 'ARGUS_MODEL': 'chosen-model'})
    assert override.llm_model == 'chosen-model'


def cloud_config(provider):
    return load_config(env={}, overrides={'llm_provider': provider})


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_hosted_request_contract_and_usage(monkeypatch, provider):
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-secret')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'claude-secret')
    requests = []
    def urlopen(request, timeout):
        requests.append(request)
        if request.data is None:
            value = {'id': 'model'}
        elif provider == 'openai':
            value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}], 'usage': {'input_tokens': 10, 'output_tokens': 4}}
        else:
            value = {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'name': 'argus_output', 'input': {'ok': True}}], 'usage': {'input_tokens': 10, 'output_tokens': 4}}
        return io.BytesIO(json.dumps(value).encode())
    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    cfg = cloud_config(provider)
    instance = create_provider(cfg)
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    response = instance.generate('system', 'evidence', schema)
    assert json.loads(response.text) == {'ok': True}
    assert response.prompt_tokens == 10 and response.completion_tokens == 4
    assert requests[0].get_method() == 'GET' and '/models/' in requests[0].full_url
    payload = json.loads(requests[1].data)
    if provider == 'openai':
        assert requests[1].full_url == 'https://api.openai.com/v1/responses'
        assert requests[1].get_header('Authorization') == 'Bearer openai-secret'
        assert payload['store'] is False and payload['text']['format']['type'] == 'json_object'
        assert '/no_think' not in str(payload)
        assert json.dumps(schema) in payload['instructions']
    else:
        assert requests[1].full_url == 'https://api.anthropic.com/v1/messages'
        assert requests[1].get_header('X-api-key') == 'claude-secret'
        assert requests[1].get_header('Anthropic-version') == '2023-06-01'
        assert payload['system'] == 'system'
        assert payload['tools'][0]['input_schema'] == schema
        assert payload['tool_choice']['type'] == 'tool'
    assert instance.info()['calls'] == 1
    assert 'secret' not in str(instance.info())


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_missing_key_and_http_errors_are_safe(monkeypatch, provider):
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ARGUS_LLM_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    instance = create_provider(cloud_config(provider))
    with pytest.raises(LLMUnavailableError, match='key is missing'):
        instance.prepare()
    monkeypatch.setenv('ARGUS_LLM_API_KEY', 'secret')
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError('https://example.test', 401, 'secret', {}, io.BytesIO(b'secret response'))
    monkeypatch.setattr('urllib.request.urlopen', fail)
    with pytest.raises(LLMUnavailableError) as caught:
        instance.prepare()
    assert 'HTTP 401' in str(caught.value) and 'secret' not in str(caught.value)


@pytest.mark.parametrize('provider,envelope', [('openai', {'status': 'incomplete', 'output': []}), ('openai', {'status': 'completed', 'output': []}), ('anthropic', {'stop_reason': 'max_tokens', 'content': []}), ('anthropic', {'stop_reason': 'tool_use', 'content': []})])
def test_incomplete_or_empty_output_is_never_accepted(monkeypatch, provider, envelope):
    monkeypatch.setenv('ARGUS_LLM_API_KEY', 'secret')
    instance = create_provider(cloud_config(provider))
    instance.prepared = True
    monkeypatch.setattr(instance, '_request', lambda *a: envelope)
    with pytest.raises(LLMError):
        instance.generate('system', 'prompt', {'type': 'object'})
