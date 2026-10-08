"""Deterministic code-similarity measurement against supplied reference repositories.

Method: token 6-gram shingles over meaningful source files only. The estimate is the share of the
target's shingles that also occur in the reference (containment), which is robust to the reference
being larger than the target. It measures textual overlap, not intent or direction of copying.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from argus.collectors.classify import MEANINGFUL, classify_path
from argus.collectors.gitutil import read_text

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\sA-Za-z0-9_]")
SHINGLE = 6
MIN_SHINGLES = 20
METHOD = (
    f"Token {SHINGLE}-gram containment over files classified as source/tests "
    f"(files with fewer than {MIN_SHINGLES} shingles skipped). Excludes vendored, generated, build output, "
    "minified, lockfiles, datasets, binaries, configuration, documentation and CI files."
)


def shingles(text: str) -> set[int]:
    tokens = _TOKEN.findall(text)
    return {hash(tuple(tokens[i: i + SHINGLE])) for i in range(len(tokens) - SHINGLE + 1)}


def fingerprint(repo: Path, tracked: list[str]) -> dict[str, set[int]]:
    result = {}
    for rel in tracked:
        if classify_path(rel) not in MEANINGFUL:
            continue
        text = read_text(repo, rel, limit=1_500_000)
        if not text:
            continue
        s = shingles(text)
        if len(s) >= MIN_SHINGLES:
            result[rel] = s
    return result


def compare(target: dict[str, set[int]], reference: dict[str, set[int]], threshold: float) -> dict[str, Any]:
    index: dict[int, list[str]] = {}
    for path, sh in reference.items():
        for h in sh:
            index.setdefault(h, []).append(path)
    total = matched = 0
    files = []
    for path, sh in target.items():
        hits: Counter = Counter()
        common = 0
        for h in sh:
            refs = index.get(h)
            if refs:
                common += 1
                hits.update(set(refs))
        total += len(sh)
        matched += common
        best = hits.most_common(1)
        files.append(
            {
                "file": path, "shingles": len(sh), "containment": round(common / len(sh), 4),
                "best_match": best[0][0] if best else None,
                "best_match_containment": round(best[0][1] / len(sh), 4) if best else 0.0,
            }
        )
    files.sort(key=lambda f: (-f["containment"], -f["shingles"]))
    estimate = round(matched / total, 4) if total else None
    return {
        "files_compared": len(target),
        "reference_files": len(reference),
        "similarity_estimate": estimate,
        "files_at_or_above_threshold": sum(1 for f in files if f["containment"] >= threshold),
        "top_files": files[:15],
        "threshold_exceeded": estimate is not None and estimate >= threshold,
    }
