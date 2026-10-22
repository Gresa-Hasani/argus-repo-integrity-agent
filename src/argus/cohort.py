"""Read-only cohort cross-validation and explicit grade-population filtering."""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from argus.collectors.gitutil import read_text, tracked_files
from argus.collectors.similarity import compare, fingerprint


def readme_profile(repo: Path, tracked: list[str]) -> dict[str, Any]:
    paths = sorted((p for p in tracked if Path(p).name.lower() in {"readme.md", "readme.rst", "readme.txt", "readme"}), key=lambda p: (p.count("/"), p.lower()))
    if not paths:
        return {"available": False, "path": None, "headings": [], "tokens": []}
    for path in paths:
        text = read_text(repo, path)
        if text is not None:
            headings = [re.sub(r"\s+", " ", h.lower()).strip() for h in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", text)]
            return {"available": True, "path": path, "headings": headings, "tokens": re.findall(r"\w+", text.lower())}
    return {"available": False, "path": paths[0], "headings": [], "tokens": []}


def cross_validate(repositories: list[dict[str, Any]], threshold: float = 0.70) -> list[dict[str, Any]]:
    """Every pair; directional code containment and symmetric README metrics.

    A failed acquisition is represented as unavailable, never zero overlap.
    README structure is advisory only and cannot set an integrity flag.
    """
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    if len({r["slug"] for r in repositories}) != len(repositories):
        raise ValueError("duplicate repository slugs")
    profiles = {}
    for r in repositories:
        if r.get("acquisition_status") != "available":
            continue
        repo = Path(r["local_path"])
        files = tracked_files(repo)
        profiles[r["slug"]] = (fingerprint(repo, files), readme_profile(repo, files))
    pairs = []
    for a, b in combinations(repositories, 2):
        row = {"a": a["slug"], "b": b["slug"], "readme_structure_advisory_only": True}
        if a["slug"] not in profiles or b["slug"] not in profiles:
            pairs.append(row | {"status": "unavailable", "code_a_in_b": None, "code_b_in_a": None, "readme_text_similarity": None, "readme_heading_similarity": None})
            continue
        fa, ra = profiles[a["slug"]]
        fb, rb = profiles[b["slug"]]
        # Mean both orientations to avoid SequenceMatcher's order dependence.
        def symmetric(x, y):
            return round((SequenceMatcher(None, x, y, autojunk=False).ratio() + SequenceMatcher(None, y, x, autojunk=False).ratio()) / 2, 4) if x and y else None
        ab, ba = compare(fa, fb, threshold), compare(fb, fa, threshold)
        flagged = bool(ab["threshold_exceeded"] or ba["threshold_exceeded"])
        pairs.append(row | {
            "status": "compared", "code_a_in_b": ab["similarity_estimate"] if fb else None,
            "code_b_in_a": ba["similarity_estimate"] if fa else None,
            "flagged": flagged, "threshold": threshold,
            "flag_reason": "CODE_OVERLAP_REVIEW_REQUIRED" if flagged else None,
            "matched_files_a": ab["top_files"], "matched_files_b": ba["top_files"],
            "readme_text_similarity": symmetric(ra["tokens"], rb["tokens"]) if ra["available"] and rb["available"] else None,
            "readme_heading_similarity": symmetric(ra["headings"], rb["headings"]),
            "readme_paths": [ra["path"], rb["path"]],
        })
    return pairs


def grade_populations(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Unknown grade/flag state is excluded; flagged samples get a second plot."""
    eligible = []
    for r in rows:
        score = r.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            continue
        if r.get("grade_verified") is not True or type(r.get("flagged")) is not bool:
            continue
        eligible.append(r)
    populations = {"without_flagged": [r for r in eligible if not r["flagged"]]}
    if any(r["flagged"] for r in eligible):
        populations["with_flagged"] = eligible
    return populations


def plot_grades(rows: list[dict[str, Any]], out: Path, *, title: str, score_max: float = 100) -> list[Path]:
    """Histogram plus descriptive normal fit; common bins and axes for both views."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if not math.isfinite(score_max) or score_max <= 0:
        raise ValueError("score_max must be finite and positive")
    populations = grade_populations(rows)
    all_scores = [r["score"] for pop in populations.values() for r in pop]
    if any(s < 0 or s > score_max for s in all_scores):
        raise ValueError("score outside configured range")
    bins = np.linspace(0, score_max, 11)
    ymax = max([1] + [int(np.histogram([r["score"] for r in pop], bins=bins)[0].max()) for pop in populations.values()]) * 1.5
    out.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, pop in populations.items():
        fig, ax = plt.subplots(figsize=(9, 5))
        scores = [r["score"] for r in pop]
        ax.hist(scores, bins=bins, color="#3578bb", edgecolor="white", label="Observed scores")
        ax.scatter(scores, [0.12] * len(scores), marker="|", color="#222", zorder=3)
        if len(scores) >= 2:
            mean, std = float(np.mean(scores)), float(np.std(scores, ddof=1))
            if std > 0:
                x = np.linspace(0, score_max, 400)
                y = np.exp(-0.5 * ((x - mean) / std) ** 2) / (std * np.sqrt(2 * np.pi)) * len(scores) * (score_max / 10)
                ax.plot(x, y, color="#c35b25", label="Descriptive normal fit")
                ax.set_title(f"{title}\n{name.replace('_', ' ')}: n={len(scores)}, mean={mean:.1f}, median={np.median(scores):.1f}, SD={std:.1f}")
            else:
                ax.set_title(f"{title}\n{name.replace('_', ' ')}: n={len(scores)}, mean={mean:.1f}, SD=0 (no curve)")
        else:
            ax.set_title(f"{title}\n{name.replace('_', ' ')}: n={len(scores)} (insufficient data for a curve)")
        excluded = len(rows) - len(pop)
        ax.set(xlim=(0, score_max), ylim=(0, ymax), xlabel=f"Score / {score_max:g}", ylabel="Repository count")
        ax.text(0.99, 0.96, f"Flagged included: {sum(r['flagged'] for r in pop)}\nExcluded: {excluded}", transform=ax.transAxes, ha="right", va="top")
        ax.legend(loc="upper left")
        fig.tight_layout()
        for ext in ("png", "svg"):
            path = out / f"grades-{name}.{ext}"
            fig.savefig(path, dpi=160, bbox_inches="tight", pad_inches=0.2)
            outputs.append(path)
        plt.close(fig)
    return outputs


def overlap_flags(pairs: list[dict[str, Any]]) -> set[str]:
    """Flag both participants without inferring authorship or copying direction."""
    return {slug for pair in pairs if pair.get('flagged') is True for slug in (pair['a'], pair['b'])}
