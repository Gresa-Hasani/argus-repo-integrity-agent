"""Configuration. Precedence: defaults < config file < environment < CLI flags."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # LLM
    llm_provider: str = "qwen"
    # Safest default for free hosting: the 4B model fits in ~4 GB of RAM. Override with ARGUS_MODEL=qwen3:8b.
    llm_model: str = "qwen3:4b"
    llm_fallback_model: str = ""  # no implicit fallback; set ARGUS_FALLBACK_MODEL to enable one (it is always reported)
    llm_backend: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1536
    llm_num_ctx: int = 8192
    llm_packet_chars: int = 9000
    llm_timeout: float = 900.0
    llm_think: bool = False
    llm_model_tags: dict[str, str] = field(default_factory=dict)
    llm_enabled: bool = True
    # Evaluation rules
    similarity_threshold: float = 0.70
    require_similarity: bool = False
    compare: list[str] = field(default_factory=list)
    deadline: Optional[str] = None
    late_window_hours: float = 2.0
    large_commit_files: int = 100
    large_commit_additions: int = 3000
    # Tooling / IO
    scc_path: Optional[str] = None
    out_dir: str = "argus-reports"
    work_dir: Optional[str] = None
    keep_clone: bool = False
    github_api: bool = True

    @property
    def github_token(self) -> Optional[str]:
        # Environment only: never read from a file that could be committed.
        return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None

    @property
    def llm_api_key(self) -> Optional[str]:
        return os.environ.get("ARGUS_LLM_API_KEY") or None

    def public_dict(self) -> dict[str, Any]:
        """Config as recorded in reports. Contains no credentials by construction."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_fallback_model": self.llm_fallback_model,
            "llm_backend": self.llm_backend,
            "llm_base_url": self.llm_base_url,
            "llm_temperature": self.llm_temperature,
            "llm_max_tokens": self.llm_max_tokens,
            "llm_num_ctx": self.llm_num_ctx,
            "llm_packet_chars": self.llm_packet_chars,
            "llm_enabled": self.llm_enabled,
            "similarity_threshold": self.similarity_threshold,
            "require_similarity": self.require_similarity,
            "compare": list(self.compare),
            "deadline": self.deadline,
            "late_window_hours": self.late_window_hours,
        }


_ENV = {
    "ARGUS_LLM_PROVIDER": ("llm_provider", str),
    "ARGUS_LLM_MODEL": ("llm_model", str),
    "ARGUS_LLM_FALLBACK_MODEL": ("llm_fallback_model", str),
    "ARGUS_MODEL": ("llm_model", str),  # preferred name; wins over ARGUS_LLM_MODEL
    "ARGUS_FALLBACK_MODEL": ("llm_fallback_model", str),
    "ARGUS_OLLAMA_URL": ("llm_base_url", str),
    "ARGUS_REPORTS_DIR": ("out_dir", str),
    "ARGUS_LLM_BACKEND": ("llm_backend", str),
    "ARGUS_LLM_BASE_URL": ("llm_base_url", str),
    "ARGUS_LLM_TEMPERATURE": ("llm_temperature", float),
    "ARGUS_LLM_MAX_TOKENS": ("llm_max_tokens", int),
    "ARGUS_LLM_NUM_CTX": ("llm_num_ctx", int),
    "ARGUS_LLM_PACKET_CHARS": ("llm_packet_chars", int),
    "ARGUS_LLM_TIMEOUT": ("llm_timeout", float),
    "ARGUS_LLM_THINK": ("llm_think", _bool),
    "ARGUS_SCC_PATH": ("scc_path", str),
    "ARGUS_SIMILARITY_THRESHOLD": ("similarity_threshold", float),
    "ARGUS_DEADLINE": ("deadline", str),
}

_FILE_LLM = {
    "provider": "llm_provider",
    "model": "llm_model",
    "fallback_model": "llm_fallback_model",
    "backend": "llm_backend",
    "base_url": "llm_base_url",
    "temperature": "llm_temperature",
    "max_tokens": "llm_max_tokens",
    "num_ctx": "llm_num_ctx",
    "packet_chars": "llm_packet_chars",
    "timeout": "llm_timeout",
    "think": "llm_think",
}

_FILE_EVAL = {
    "similarity_threshold",
    "require_similarity",
    "compare",
    "deadline",
    "late_window_hours",
    "large_commit_files",
    "large_commit_additions",
}


def load_config(
    config_file: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> Config:
    env = os.environ if env is None else env
    cfg = Config()

    path = Path(config_file) if config_file else Path("argus.toml")
    if config_file and not path.is_file():
        raise FileNotFoundError(f"config file not found: {config_file}")
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        llm = data.get("llm", {})
        for key, attr in _FILE_LLM.items():
            if key in llm:
                setattr(cfg, attr, llm[key])
        cfg.llm_model_tags.update({str(k): str(v) for k, v in llm.get("model_tags", {}).items()})
        for key, value in data.get("evaluation", {}).items():
            if key in _FILE_EVAL:
                setattr(cfg, key, value)

    for name, (attr, cast) in _ENV.items():
        if env.get(name):
            setattr(cfg, attr, cast(env[name]))
    if env.get("ARGUS_LLM_MODEL_TAG"):
        cfg.llm_model_tags[cfg.llm_model] = env["ARGUS_LLM_MODEL_TAG"]
    if env.get("ARGUS_LLM_FALLBACK_MODEL_TAG"):
        cfg.llm_model_tags[cfg.llm_fallback_model] = env["ARGUS_LLM_FALLBACK_MODEL_TAG"]

    for key, value in (overrides or {}).items():
        if value is not None:
            setattr(cfg, key, value)
    return cfg
