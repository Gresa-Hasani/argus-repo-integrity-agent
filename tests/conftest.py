"""Test fixtures: throwaway git repositories and a scriptable in-memory LLM provider."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from argus.config import Config
from argus.llm.interface import LLMError, LLMProvider, LLMResponse, LLMUnavailableError

BASE = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
ALICE = ("Alice Example", "alice@example.com")
BOB = ("Bob Example", "bob@example.com")

GITIGNORE = "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n"
README = "# Inventory service\n\nA small Python library that tracks stock levels for a warehouse.\nRun the unit tests with pytest.\n"


def source(i: int) -> str:
    return (
        f'"""Stock module {i}."""\n\n\n'
        f"def restock_{i}(levels, item, quantity):\n"
        f'    """Add quantity to an item and return the new level."""\n'
        f"    if quantity <= 0:\n        raise ValueError('quantity must be positive')\n"
        f"    levels[item] = levels.get(item, 0) + quantity * {i + 1}\n    return levels[item]\n\n\n"
        f"def reserve_{i}(levels, item, quantity):\n"
        f"    available = levels.get(item, 0)\n    if quantity > available:\n        raise LookupError(item)\n"
        f"    levels[item] = available - quantity\n    return levels[item] + {i}\n"
    )


class RepoBuilder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0
        path.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "-b", "main")

    def _git(self, *args: str, env: Optional[dict[str, str]] = None) -> str:
        full = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", **(env or {})}
        return subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", "-C", str(self.path), *args],
            check=True, capture_output=True, env=full,
        ).stdout.decode()

    def commit(
        self, message: str, files: Optional[dict[str, Optional[str]]] = None, author: tuple[str, str] = ALICE,
        when: Optional[datetime] = None, coauthors: tuple[tuple[str, str], ...] = (), allow_empty: bool = False,
    ) -> str:
        for rel, content in (files or {}).items():
            target = self.path / rel
            if content is None:
                self._git("rm", "-q", "--cached", rel)
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        self._git("add", "-A")
        when = when or BASE + timedelta(hours=6 * self.count)
        self.count += 1
        if coauthors:
            message += "\n\n" + "\n".join(f"Co-authored-by: {n} <{e}>" for n, e in coauthors)
        stamp = when.isoformat()
        env = {
            "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1], "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1], "GIT_COMMITTER_DATE": stamp,
        }
        self._git("commit", "-q", "-m", message, *(["--allow-empty"] if allow_empty else []), env=env)
        return self._git("rev-parse", "HEAD").strip()


def build_clean(path: Path) -> RepoBuilder:
    repo = RepoBuilder(path)
    repo.commit("Add project skeleton with ignore rules and readme", {".gitignore": GITIGNORE, "README.md": README, "requirements.txt": "pytest>=8\n"})
    repo.commit("Implement restock and reserve operations", {"inventory/__init__.py": "", "inventory/stock.py": source(0)})
    repo.commit("Add unit tests for stock operations", {"tests/test_stock.py": "from inventory.stock import restock_0\n\n\ndef test_restock():\n    assert restock_0({}, 'a', 2) == 2\n"})
    repo.commit("Add supplier lead-time calculation", {"inventory/suppliers.py": source(1)})
    repo.commit("Handle unknown items when reserving stock", {"inventory/stock.py": source(0) + "\n\ndef known(levels, item):\n    return item in levels\n"})
    repo.commit("Document the reservation rules in the readme", {"README.md": README + "\nReservations fail when stock is insufficient.\n"})
    return repo


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    return build_clean(tmp_path / "clean").path


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(out_dir=str(tmp_path / "reports"), llm_num_ctx=8192)


def step_of(prompt: str) -> str:
    """The step name is the first heading of the task prompt."""
    return prompt.split("\n", 1)[0].removeprefix("# Step:").split("—")[0].strip().replace(" ", "_").replace("-", "_").lower()


def default_reply(system: str, prompt: str, schema: Optional[dict[str, Any]]) -> str:
    props = (schema or {}).get("properties", {})
    if "executive_summary" in props:
        status = re.search(r'"completion_status":"([A-Z_]+)"', prompt).group(1)
        return json.dumps({"executive_summary": f"The evaluation completed with status {status}, reported exactly as computed by the pipeline."})
    reply: dict[str, Any] = {"summary": "The evidence shows nothing noteworthy for this step.", "findings": [], "resolved_anomalies": [], "unresolved_questions": []}
    if "enum" in props.get("classification", {}):
        reply["classification"] = "INSUFFICIENT_EVIDENCE"
    return json.dumps(reply)


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, responder: Callable[[str, str, Optional[dict[str, Any]]], str] = default_reply, available: bool = True, fail: bool = False) -> None:
        self.responder, self.available, self.fail = responder, available, fail
        self.prompts: list[str] = []
        self.schemas: list[Optional[dict[str, Any]]] = []

    def prepare(self) -> dict[str, Any]:
        if not self.available:
            raise LLMUnavailableError("runtime not reachable (test)")
        return self.info()

    def generate(self, system: str, prompt: str, schema: Optional[dict[str, Any]] = None) -> LLMResponse:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if self.fail:
            raise LLMError("model crashed (test)")
        return LLMResponse(text=self.responder(system, prompt, schema), model="fake-model")

    def info(self) -> dict[str, Any]:
        return {"provider": "fake", "model": "Fake-1B", "runtime_model_tag": "fake-model", "requested_model": "Fake-1B", "fallback_used": False}
