"""Live checks against a real local runtime. Run with: pytest -m live"""

from __future__ import annotations

import pytest

from argus.config import load_config
from argus.llm.interface import LLMUnavailableError, create_provider
from argus.models import CompletionStatus
from argus.pipeline import evaluate

pytestmark = pytest.mark.live


def _provider(model: str):
    cfg = load_config(overrides={"llm_model": model, "llm_fallback_model": ""})
    provider = create_provider(cfg)
    try:
        provider.prepare()
    except LLMUnavailableError as exc:
        pytest.skip(f"{model} not available: {exc}")
    return cfg, provider


@pytest.mark.parametrize("model", ["Qwen3-8B", "Qwen3-4B"])
def test_model_completes_an_evaluation_with_valid_grounded_output(model, clean_repo, tmp_path):
    cfg, provider = _provider(model)
    cfg.out_dir = str(tmp_path / "reports")
    ev = evaluate(str(clean_repo), cfg, provider)
    assert ev.model["model"] == model and not ev.model["fallback_used"]
    assert ev.errors == [], ev.errors
    assert ev.completion_status in (CompletionStatus.DONE_CLEAN, CompletionStatus.DONE_WITH_FINDINGS, CompletionStatus.FLAGGED)
    known = {e.id for e in ev.evidence}
    assert all(e.id in known for f in ev.findings for e in f.evidence)
