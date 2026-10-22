"""Hosted OpenAI Responses and Anthropic Messages adapters.

Credentials remain in the backend environment. API errors never echo response bodies.
ARGUS still validates every structured response through its existing schema/retry layer.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlsplit

from argus.llm.interface import LLMError, LLMProvider, LLMResponse, LLMUnavailableError, register_provider


class CloudProvider(LLMProvider):
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.llm_base_url.rstrip('/')
        if not self.base.endswith('/v1'):
            self.base += '/v1'
        if urlsplit(self.base).scheme != 'https':
            raise LLMUnavailableError('Hosted providers require an HTTPS API URL.')
        self.calls = 0
        self.prepared = False

    def _request(self, path: str, payload=None):
        key = self.cfg.llm_api_key
        if not key:
            raise LLMUnavailableError(f'{self.name} API key is missing from the backend environment.')
        headers = {'Content-Type': 'application/json'}
        if self.name == 'anthropic':
            headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        else:
            headers['Authorization'] = f'Bearer {key}'
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.cfg.llm_timeout if payload is not None else 15) as response:
                result = json.loads(response.read())
            if not isinstance(result, dict):
                raise LLMError(f'{self.name} returned an invalid response envelope.')
            return result
        except urllib.error.HTTPError as exc:
            raise LLMError(f'{self.name} API returned HTTP {exc.code}. Check credentials, model access, quota and request settings.') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise LLMError(f'{self.name} API request failed or returned invalid JSON.') from None

    def prepare(self):
        try:
            self._request('/models/' + quote(self.cfg.llm_model, safe=''))
        except LLMError as exc:
            raise LLMUnavailableError(str(exc)) from None
        self.prepared = True
        return self.info()

    def info(self):
        return {'provider': self.name, 'backend': self.name, 'model': self.cfg.llm_model,
                'requested_model': self.cfg.llm_model, 'runtime_model_tag': self.cfg.llm_model,
                'fallback_used': False, 'calls': self.calls, 'max_tokens': self.cfg.llm_max_tokens}

    def generate(self, system, prompt, schema=None):
        if not self.prepared:
            self.prepare()
        self.calls += 1
        started = time.monotonic()
        if self.name == 'openai':
            # JSON mode supports the existing ARGUS schemas without changing their optional fields.
            instructions = system + '\nReturn only a JSON object.'
            if schema:
                instructions += '\nIt must satisfy this JSON Schema:\n' + json.dumps(schema)
            data = self._request('/responses', {'model': self.cfg.llm_model, 'instructions': instructions,
                'input': prompt, 'max_output_tokens': self.cfg.llm_max_tokens, 'store': False,
                'text': {'format': {'type': 'json_object'}}})
            if data.get('status') != 'completed':
                raise LLMError('openai response was incomplete or failed; no partial result accepted.')
            text = ''.join(part.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
                           for part in item.get('content', []) if part.get('type') == 'output_text')
            usage = data.get('usage') or {}
        else:
            payload: dict[str, Any] = {'model': self.cfg.llm_model, 'max_tokens': self.cfg.llm_max_tokens,
                'system': system, 'messages': [{'role': 'user', 'content': prompt}]}
            if schema:
                payload.update(tools=[{'name': 'argus_output', 'description': 'Return the ARGUS evaluation output.', 'input_schema': schema}],
                               tool_choice={'type': 'tool', 'name': 'argus_output', 'disable_parallel_tool_use': True})
            else:
                payload['system'] += '\nReturn only a JSON object.'
            data = self._request('/messages', payload)
            if data.get('stop_reason') not in {'end_turn', 'tool_use'}:
                raise LLMError('anthropic response was incomplete or refused; no partial result accepted.')
            blocks = data.get('content') or []
            if schema:
                outputs = [b['input'] for b in blocks if b.get('type') == 'tool_use' and b.get('name') == 'argus_output' and isinstance(b.get('input'), dict)]
                text = json.dumps(outputs[0]) if len(outputs) == 1 else ''
            else:
                text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            usage = data.get('usage') or {}
        if not text.strip():
            raise LLMError(f'{self.name} returned no usable structured output.')
        return LLMResponse(text=text, model=self.cfg.llm_model, duration_s=round(time.monotonic() - started, 2),
                           prompt_tokens=usage.get('input_tokens'), completion_tokens=usage.get('output_tokens'))


class OpenAIProvider(CloudProvider):
    name = 'openai'


class AnthropicProvider(CloudProvider):
    name = 'anthropic'


register_provider('openai', OpenAIProvider)
register_provider('anthropic', AnthropicProvider)
register_provider('claude', AnthropicProvider)
