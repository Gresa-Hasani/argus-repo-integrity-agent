"""Configuration. Precedence: defaults < config file < environment < CLI flags."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _string_list(value: Any) -> list[str]:
    """Accept a TOML/JSON list, a JSON string, or newline/semicolon separated text."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                value = [part for part in text.replace(";", "\n").splitlines()]
        else:
            value = [part for part in text.replace(";", "\n").splitlines()]
    if isinstance(value, (tuple, set)):
        value = list(value)
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    return [str(item).strip() for item in value if str(item).strip()]


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError("task definitions must be a TOML/JSON list of objects") from exc
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("task definitions must be a list of objects")
    return [dict(item) for item in value]


def _string_dict(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError("expected a TOML/JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("expected an object mapping repository keys to values")
    return {str(key): str(item) for key, item in value.items() if str(item).strip()}


def _float_dict(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError("scoring weights must be a TOML/JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("scoring weights must be an object")
    return {str(key): float(item) for key, item in value.items()}


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
    # Task profiling and task-based cross-validation
    task_id: str = ""
    task_title: str = ""
    task_category: str = ""
    task_description: str = ""
    task_requirements: list[str] = field(default_factory=list)
    task_definitions: list[dict[str, Any]] = field(default_factory=list)
    task_assignments: dict[str, str] = field(default_factory=dict)
    task_relevance_threshold: float = 0.62
    task_similarity_threshold: float = 0.70
    scoring_weights: dict[str, float] = field(default_factory=dict)
    peer_context_weight: float = 0.15
    peer_minimum: int = 2
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
        provider = self.llm_provider.lower()
        specific = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY" if provider in {"anthropic", "claude"} else ""
        return os.environ.get(specific) or os.environ.get("ARGUS_LLM_API_KEY") or None

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
            "task": {
                "id": self.task_id,
                "title": self.task_title,
                "category": self.task_category,
                "description": self.task_description,
                "requirements": list(self.task_requirements),
                "definitions": [dict(item) for item in self.task_definitions],
                "assignments": dict(self.task_assignments),
                "relevance_threshold": self.task_relevance_threshold,
                "similarity_threshold": self.task_similarity_threshold,
            },
            "scoring": {
                "weights": dict(self.scoring_weights),
                "peer_context_weight": self.peer_context_weight,
                "peer_minimum": self.peer_minimum,
            },
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
    "ARGUS_TASK_ID": ("task_id", str),
    "ARGUS_TASK_TITLE": ("task_title", str),
    "ARGUS_TASK_CATEGORY": ("task_category", str),
    "ARGUS_TASK_DESCRIPTION": ("task_description", str),
    "ARGUS_TASK_REQUIREMENTS": ("task_requirements", _string_list),
    "ARGUS_TASK_DEFINITIONS": ("task_definitions", _mapping_list),
    "ARGUS_TASK_ASSIGNMENTS": ("task_assignments", _string_dict),
    "ARGUS_TASK_RELEVANCE_THRESHOLD": ("task_relevance_threshold", float),
    "ARGUS_TASK_SIMILARITY_THRESHOLD": ("task_similarity_threshold", float),
    "ARGUS_SCORING_WEIGHTS": ("scoring_weights", _float_dict),
    "ARGUS_PEER_CONTEXT_WEIGHT": ("peer_context_weight", float),
    "ARGUS_PEER_MINIMUM": ("peer_minimum", int),
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


CLOUD_DEFAULTS = {
    "openai": {"llm_model": "gpt-4.1-mini", "llm_base_url": "https://api.openai.com/v1", "llm_backend": "openai"},
    "anthropic": {"llm_model": "claude-sonnet-4-6", "llm_base_url": "https://api.anthropic.com/v1", "llm_backend": "anthropic"},
}


def _provider_defaults(cfg: Config, provider: str) -> None:
    provider = "anthropic" if provider.lower() == "claude" else provider.lower()
    current = "anthropic" if cfg.llm_provider.lower() == "claude" else cfg.llm_provider.lower()
    if provider != current:
        for key, value in CLOUD_DEFAULTS.get(provider, {}).items():
            setattr(cfg, key, value)
        cfg.llm_provider = provider


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
        _provider_defaults(cfg, llm.get("provider", cfg.llm_provider))
        for key, attr in _FILE_LLM.items():
            if key in llm:
                setattr(cfg, attr, llm[key])
        cfg.llm_model_tags.update({str(k): str(v) for k, v in llm.get("model_tags", {}).items()})
        for key, value in data.get("evaluation", {}).items():
            if key in _FILE_EVAL:
                setattr(cfg, key, value)
        task = data.get("task", {})
        if not isinstance(task, dict):
            raise ValueError("[task] must be a TOML table")
        if "id" in task:
            cfg.task_id = str(task["id"])
        if "title" in task:
            cfg.task_title = str(task["title"])
        if "category" in task:
            cfg.task_category = str(task["category"])
        if "description" in task:
            cfg.task_description = str(task["description"])
        if "requirements" in task:
            cfg.task_requirements = _string_list(task["requirements"])
        if "definitions" in task:
            cfg.task_definitions = _mapping_list(task["definitions"])
        if "assignments" in task:
            cfg.task_assignments = _string_dict(task["assignments"])
        if "relevance_threshold" in task:
            cfg.task_relevance_threshold = float(task["relevance_threshold"])
        if "similarity_threshold" in task:
            cfg.task_similarity_threshold = float(task["similarity_threshold"])
        scoring = data.get("scoring", {})
        if not isinstance(scoring, dict):
            raise ValueError("[scoring] must be a TOML table")
        weights = scoring.get("weights", scoring.get("criteria", {}))
        if weights:
            cfg.scoring_weights = _float_dict(weights)
        if "peer_context_weight" in scoring:
            cfg.peer_context_weight = float(scoring["peer_context_weight"])
        if "peer_minimum" in scoring:
            cfg.peer_minimum = int(scoring["peer_minimum"])
        if "task_relevance_threshold" in scoring:
            cfg.task_relevance_threshold = float(scoring["task_relevance_threshold"])
        if "task_similarity_threshold" in scoring:
            cfg.task_similarity_threshold = float(scoring["task_similarity_threshold"])

    _provider_defaults(cfg, env.get("ARGUS_LLM_PROVIDER", cfg.llm_provider))
    for name, (attr, cast) in _ENV.items():
        if env.get(name):
            value = cast(env[name])
            if attr in {"task_assignments", "scoring_weights"} and isinstance(getattr(cfg, attr, None), dict):
                setattr(cfg, attr, {**getattr(cfg, attr), **value})
            else:
                setattr(cfg, attr, value)
    if env.get("ARGUS_LLM_MODEL_TAG"):
        cfg.llm_model_tags[cfg.llm_model] = env["ARGUS_LLM_MODEL_TAG"]
    if env.get("ARGUS_LLM_FALLBACK_MODEL_TAG"):
        cfg.llm_model_tags[cfg.llm_fallback_model] = env["ARGUS_LLM_FALLBACK_MODEL_TAG"]

    _provider_defaults(cfg, (overrides or {}).get("llm_provider") or cfg.llm_provider)
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key in {"task_assignments", "scoring_weights"} and isinstance(value, dict):
            # CLI/env additions extend file configuration instead of silently replacing it.
            setattr(cfg, key, {**getattr(cfg, key, {}), **value})
        else:
            setattr(cfg, key, value)
    _normalize_task_config(cfg)
    return cfg


def _normalize_task_config(cfg: Config) -> None:
    """Normalise and bounds-check task/scoring configuration after all layers are applied."""
    cfg.task_requirements = _string_list(cfg.task_requirements)
    cfg.task_definitions = _mapping_list(cfg.task_definitions)
    for definition in cfg.task_definitions:
        if "requirements" in definition:
            definition["requirements"] = _string_list(definition["requirements"])
        if "aliases" in definition:
            definition["aliases"] = _string_list(definition["aliases"])
    cfg.task_assignments = _string_dict(cfg.task_assignments)
    cfg.scoring_weights = _float_dict(cfg.scoring_weights)
    if not 0.0 <= float(cfg.task_relevance_threshold) <= 1.0:
        raise ValueError("task relevance threshold must be between 0 and 1")
    if not 0.0 <= float(cfg.task_similarity_threshold) <= 1.0:
        raise ValueError("task similarity threshold must be between 0 and 1")
    if not 0.0 <= float(cfg.peer_context_weight) <= 0.5:
        raise ValueError("peer context weight must be between 0 and 0.5")
    cfg.task_relevance_threshold = float(cfg.task_relevance_threshold)
    cfg.task_similarity_threshold = float(cfg.task_similarity_threshold)
    cfg.peer_context_weight = float(cfg.peer_context_weight)
    if isinstance(cfg.peer_minimum, bool) or int(cfg.peer_minimum) < 0:
        raise ValueError("peer minimum must be a non-negative integer")
    cfg.peer_minimum = int(cfg.peer_minimum)
    for key, value in cfg.scoring_weights.items():
        if value < 0:
            raise ValueError(f"scoring weight {key} must be non-negative")
