"""Provider abstraction. The forensics modules only ever see `LLMProvider`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional


class LLMError(Exception):
    """The model call failed (transport, runtime, empty output)."""


class LLMUnavailableError(LLMError):
    """No usable model/runtime could be reached before any reasoning started."""


@dataclass
class LLMResponse:
    text: str
    model: str
    duration_s: float = 0.0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class LLMProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def prepare(self) -> dict[str, Any]:
        """Resolve the model to use and verify the runtime is reachable.

        Returns model metadata for the report. Raises LLMUnavailableError otherwise.
        """

    @abstractmethod
    def generate(self, system: str, prompt: str, schema: Optional[dict[str, Any]] = None) -> LLMResponse:
        """Return the raw model text for one request. `schema` is a JSON Schema the output should satisfy."""

    def info(self) -> dict[str, Any]:
        return {"provider": self.name}


_REGISTRY: dict[str, Callable[[Any], LLMProvider]] = {}


def register_provider(name: str, factory: Callable[[Any], LLMProvider]) -> None:
    _REGISTRY[name.lower()] = factory


def create_provider(cfg) -> LLMProvider:
    from argus.llm.providers import qwen  # noqa: F401 - registers itself

    try:
        factory = _REGISTRY[cfg.llm_provider.lower()]
    except KeyError:
        raise LLMUnavailableError(f"unknown LLM provider '{cfg.llm_provider}' (available: {', '.join(sorted(_REGISTRY))})") from None
    return factory(cfg)
