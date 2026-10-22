import json
from pathlib import Path

from argus.config import Config, load_config
from argus.llm.interface import LLMResponse, create_provider
from argus.llm.providers.ollama import OllamaProvider


class GemmaBackend:
    name = "ollama"

    def default_tag(self, logical):
        return logical

    def list_models(self):
        return ["argus-gemma3:12b"]

    def chat(self, model, system, prompt, schema):
        assert model == "argus-gemma3:12b"
        return LLMResponse(text=json.dumps({"ready": True}), model=model)


def test_gemma_profile_selects_generic_provider_and_exact_tag():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(str(root / "argus.gemma.toml"), env={})
    assert isinstance(create_provider(cfg), OllamaProvider)
    provider = OllamaProvider(cfg, GemmaBackend())
    info = provider.prepare()
    assert info['provider'] == 'ollama'
    assert info['runtime_model_tag'] == 'argus-gemma3:12b'
    assert not info['fallback_used']
    assert json.loads(provider.generate('system', 'prompt').text) == {'ready': True}
