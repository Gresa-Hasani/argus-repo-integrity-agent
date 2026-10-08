"""Qwen3 served by a local inference runtime.

Two transports are supported behind one provider: Ollama's native API and any OpenAI-compatible
server (vLLM, llama.cpp server, LM Studio). Adding another runtime means adding a backend class.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from argus.llm.interface import LLMError, LLMProvider, LLMResponse, LLMUnavailableError, register_provider

_SIZE = re.compile(r"^qwen3[-:_ ]?(\d+(?:\.\d+)?b)$", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _post(url: str, payload: dict[str, Any], timeout: float, api_key: Optional[str] = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured local runtime
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"runtime returned HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"runtime request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMError(f"runtime returned a non-JSON envelope: {exc}") from exc


def _get(url: str, timeout: float, api_key: Optional[str] = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LLMUnavailableError(f"cannot reach LLM runtime at {url}: {exc}") from exc


class OllamaBackend:
    name = "ollama"

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.base = cfg.llm_base_url.rstrip("/")

    def default_tag(self, logical: str) -> str:
        m = _SIZE.match(logical.strip())
        return f"qwen3:{m.group(1).lower()}" if m else logical

    def list_models(self) -> list[str]:
        data = _get(f"{self.base}/api/tags", 10)
        return [m.get("name", "") for m in data.get("models", [])]

    def chat(self, model: str, system: str, prompt: str, schema: Optional[dict[str, Any]]) -> LLMResponse:
        payload = {
            "model": model,
            "stream": False,
            "keep_alive": "30m",
            "think": bool(self.cfg.llm_think),
            "format": schema if schema else "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"temperature": self.cfg.llm_temperature, "num_predict": self.cfg.llm_max_tokens, "num_ctx": self.cfg.llm_num_ctx},
        }
        started = time.monotonic()
        data = _post(f"{self.base}/api/chat", payload, self.cfg.llm_timeout)
        if data.get("error"):
            raise LLMError(f"ollama error: {data['error']}")
        return LLMResponse(
            text=(data.get("message") or {}).get("content", ""), model=model, duration_s=round(time.monotonic() - started, 2),
            prompt_tokens=data.get("prompt_eval_count"), completion_tokens=data.get("eval_count"),
        )


class OpenAICompatBackend:
    name = "openai"

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        base = cfg.llm_base_url.rstrip("/")
        self.base = base if base.endswith("/v1") else base + "/v1"

    def default_tag(self, logical: str) -> str:
        m = _SIZE.match(logical.strip())
        return f"Qwen/Qwen3-{m.group(1).upper()}" if m else logical

    def list_models(self) -> list[str]:
        data = _get(f"{self.base}/models", 10, self.cfg.llm_api_key)
        return [m.get("id", "") for m in data.get("data", [])]

    def chat(self, model: str, system: str, prompt: str, schema: Optional[dict[str, Any]]) -> LLMResponse:
        user = prompt if self.cfg.llm_think else prompt + "\n\n/no_think"
        payload: dict[str, Any] = {
            "model": model,
            "temperature": self.cfg.llm_temperature,
            "max_tokens": self.cfg.llm_max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "argus_output", "schema": schema}}
        else:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        data = _post(f"{self.base}/chat/completions", payload, self.cfg.llm_timeout, self.cfg.llm_api_key)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected completion envelope: {str(data)[:200]}") from exc
        usage = data.get("usage") or {}
        return LLMResponse(text=text, model=model, duration_s=round(time.monotonic() - started, 2), prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))


BACKENDS = {"ollama": OllamaBackend, "openai": OpenAICompatBackend}


class QwenProvider(LLMProvider):
    name = "qwen"

    def __init__(self, cfg, backend=None) -> None:
        self.cfg = cfg
        if backend is None:
            try:
                backend = BACKENDS[cfg.llm_backend.lower()](cfg)
            except KeyError:
                raise LLMUnavailableError(f"unknown LLM backend '{cfg.llm_backend}' (available: {', '.join(BACKENDS)})") from None
        self.backend = backend
        self.requested = cfg.llm_model
        self.active_model: Optional[str] = None
        self.active_logical: Optional[str] = None
        self.fallback_tag: Optional[str] = None
        self.fallback_used = False
        self.fallback_reason: Optional[str] = None
        self.calls = 0

    def _resolve(self, logical: str, installed: list[str]) -> Optional[str]:
        if not logical:
            return None
        candidates = [self.cfg.llm_model_tags.get(logical), self.backend.default_tag(logical), logical]
        for candidate in candidates:
            if candidate and candidate in installed:
                return candidate
        wanted = _norm(logical)
        for tag in installed:  # e.g. "hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M" for "Qwen3-4B"
            if wanted and wanted in _norm(tag):
                return tag
        return None

    def prepare(self) -> dict[str, Any]:
        installed = self.backend.list_models()
        primary = self._resolve(self.cfg.llm_model, installed)
        fallback = self._resolve(self.cfg.llm_fallback_model, installed)
        if primary:
            self.active_model, self.active_logical = primary, self.cfg.llm_model
            self.fallback_tag = fallback if fallback != primary else None
        elif fallback:
            self.active_model, self.active_logical = fallback, self.cfg.llm_fallback_model
            self.fallback_used = True
            self.fallback_reason = f"primary model '{self.cfg.llm_model}' is not available in the runtime"
        else:
            raise LLMUnavailableError(
                f"neither '{self.cfg.llm_model}' nor fallback '{self.cfg.llm_fallback_model}' is available at "
                f"{self.cfg.llm_base_url} ({self.backend.name}); installed: {', '.join(installed) or 'none'}"
            )
        return self.info()

    def generate(self, system: str, prompt: str, schema: Optional[dict[str, Any]] = None) -> LLMResponse:
        if not self.active_model:
            self.prepare()
        self.calls += 1
        try:
            response = self.backend.chat(self.active_model, system, prompt, schema)
        except LLMError as exc:
            if not self.fallback_tag or self.fallback_used:
                raise
            # The primary model failed at runtime (e.g. it does not fit in memory): switch once, visibly.
            self.fallback_used = True
            self.fallback_reason = f"primary model failed at runtime: {exc}"
            self.active_model, self.active_logical = self.fallback_tag, self.cfg.llm_fallback_model
            response = self.backend.chat(self.active_model, system, prompt, schema)
        if not response.text.strip():
            raise LLMError("model returned empty output")
        return response

    def info(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "backend": self.backend.name,
            "base_url": self.cfg.llm_base_url,
            "requested_model": self.requested,
            "model": self.active_logical,
            "runtime_model_tag": self.active_model,
            "fallback_model": self.cfg.llm_fallback_model,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "temperature": self.cfg.llm_temperature,
            "max_tokens": self.cfg.llm_max_tokens,
            "calls": self.calls,
        }


register_provider("qwen", QwenProvider)
