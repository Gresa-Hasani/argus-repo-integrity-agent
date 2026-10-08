"""Codebase composition via Boyter scc, with a clearly-labelled built-in counter as fallback.

scc measures code; it says nothing about authorship. Per-contributor LOC comes from Git diffs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from argus.collectors.classify import ALL_CATEGORIES, MEANINGFUL, NON_ORIGINAL, classify_path, component_of, language_of
from argus.collectors.gitutil import read_text

_HASH = {"Python", "Shell", "YAML", "TOML", "Ruby", "Perl", "R", "Dockerfile", "Makefile", "PowerShell", "Elixir", "INI", "Terraform"}
_SLASH = {
    "JavaScript", "JSX", "TypeScript", "TSX", "Java", "Kotlin", "Go", "Rust", "C", "C Header", "C++", "C++ Header",
    "C#", "PHP", "Swift", "Scala", "Dart", "CSS", "Sass", "LESS", "Prisma", "Protocol Buffers", "Objective C",
}


def _find_scc(configured: Optional[str]) -> Optional[str]:
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("scc")


def _run_scc(binary: str, repo: Path, tracked: set[str]) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [binary, "--format", "json", "--by-file", "--no-cocomo", "--no-size", "."],
        cwd=repo, capture_output=True, timeout=600, stdin=subprocess.DEVNULL,
        env={**os.environ, "NO_COLOR": "1"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scc exited with {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    files = []
    for lang in json.loads(proc.stdout.decode("utf-8", "replace")):
        for f in lang.get("Files") or []:
            rel = str(f.get("Location", "")).replace("\\", "/").removeprefix("./")
            if rel not in tracked:
                continue
            files.append(
                {
                    "path": rel, "language": f.get("Language") or lang.get("Name"), "lines": f.get("Lines", 0),
                    "code": f.get("Code", 0), "comment": f.get("Comment", 0), "blank": f.get("Blank", 0),
                    "complexity": f.get("Complexity"),
                }
            )
    return files


def count_text(text: str, language: str) -> tuple[int, int, int, int]:
    """Return (lines, code, comment, blank). Line-prefix comment detection only."""
    lines = text.splitlines()
    code = comment = blank = 0
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            blank += 1
        elif in_block:
            comment += 1
            if "*/" in s:
                in_block = False
        elif language in _SLASH and s.startswith("/*"):
            comment += 1
            in_block = "*/" not in s
        elif (language in _SLASH and s.startswith("//")) or (language in _HASH and s.startswith("#")) or (language == "SQL" and s.startswith("--")):
            comment += 1
        else:
            code += 1
    return len(lines), code, comment, blank


def _run_builtin(repo: Path, tracked: list[str]) -> list[dict[str, Any]]:
    files = []
    for rel in tracked:
        if classify_path(rel) in {"binary", "model_artifact"}:
            continue
        text = read_text(repo, rel, limit=5_000_000)
        if text is None:
            continue
        language = language_of(rel)
        lines, code, comment, blank = count_text(text, language)
        files.append({"path": rel, "language": language, "lines": lines, "code": code, "comment": comment, "blank": blank, "complexity": None})
    return files


def analyze(repo: Path, tracked: list[str], scc_path: Optional[str] = None) -> dict[str, Any]:
    binary = _find_scc(scc_path)
    tool, tool_error = "builtin", None
    files: list[dict[str, Any]] = []
    if binary:
        try:
            files = _run_scc(binary, repo, set(tracked))
            tool = "scc"
        except Exception as exc:  # recoverable: fall back, but say so
            tool_error = f"scc failed, used built-in counter: {exc}"
    if tool == "builtin":
        files = _run_builtin(repo, tracked)

    def blank() -> dict[str, int]:
        return {"files": 0, "lines": 0, "code": 0, "comment": 0, "blank": 0}

    languages: dict[str, dict[str, Any]] = defaultdict(blank)
    categories: dict[str, dict[str, Any]] = {c: blank() for c in ALL_CATEGORIES}
    directories: dict[str, dict[str, Any]] = defaultdict(blank)
    totals = blank()
    complexity_total = 0
    for f in files:
        f["category"] = classify_path(f["path"])
        for bucket in (languages[f["language"]], categories[f["category"]], directories[component_of(f["path"])], totals):
            bucket["files"] += 1
            for key in ("lines", "code", "comment", "blank"):
                bucket[key] += f[key]
        complexity_total += f["complexity"] or 0

    counted = {f["path"] for f in files}
    uncounted: dict[str, int] = defaultdict(int)
    for rel in tracked:
        if rel not in counted:
            uncounted[classify_path(rel)] += 1

    meaningful = sum(categories[c]["code"] for c in MEANINGFUL)
    excluded = {c: categories[c]["code"] for c in ALL_CATEGORIES if c not in MEANINGFUL and categories[c]["code"]}
    return {
        "executed": tool == "scc",
        "tool": tool,
        "tool_note": tool_error or ("Boyter scc" if tool == "scc" else "scc not found on PATH; used ARGUS built-in line counter (no complexity metric)"),
        "totals": {**totals, "complexity": complexity_total if tool == "scc" else None},
        "languages": sorted(({"language": k, **v} for k, v in languages.items()), key=lambda r: -r["code"]),
        "categories": {k: v for k, v in categories.items() if v["files"]},
        "directories": sorted(({"directory": k, **v} for k, v in directories.items()), key=lambda r: -r["code"])[:25],
        "raw_code_loc": totals["code"],
        "meaningful_source_loc_estimate": meaningful,
        "excluded_loc": sum(excluded.values()),
        "excluded_content": [
            {"category": c, "code_loc": n, "reason": "not original engineering work" if c in NON_ORIGINAL else "supporting content (config/docs/CI), not application source"}
            for c, n in sorted(excluded.items(), key=lambda kv: -kv[1])
        ],
        "uncounted_tracked_files": dict(uncounted),
        "comment_ratio": round(totals["comment"] / max(1, totals["comment"] + totals["code"]), 4),
        "files": files,
    }
