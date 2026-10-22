"""Model-independent provider for local Ollama models, including Gemma."""

from argus.llm.interface import LLMUnavailableError, register_provider
from argus.llm.providers.qwen import QwenProvider


class OllamaProvider(QwenProvider):
    name = "ollama"

    def __init__(self, cfg, backend=None):
        if cfg.llm_backend.lower() != "ollama":
            raise LLMUnavailableError("the ollama provider requires the ollama backend")
        super().__init__(cfg, backend)


register_provider("ollama", OllamaProvider)
