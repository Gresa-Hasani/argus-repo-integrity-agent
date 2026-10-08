"""Commit history: parsing, classification, message quality, granularity and inflation signals."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from argus.collectors.classify import MEANINGFUL, NON_ORIGINAL, classify_path
from argus.collectors.gitutil import git
from argus.evidence import EvidenceStore
from argus.models import Category, Severity

_FORMAT = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%aI%x1f%cI%x1f%s%x1f%b%x1f"
_COAUTHOR = re.compile(r"^\s*co-authored-by:\s*(.*?)\s*<([^<>]*)>\s*$", re.I | re.M)
_COAUTHOR_ANY = re.compile(r"^\s*co-authored-by:", re.I | re.M)

WEAK_MESSAGES = {
    "update", "updates", "updated", "change", "changes", "changed", "fix", "fixes", "fixed", "final", "stuff",
    "wip", "test", "testing", "asdf", "commit", "new", "edit", "edits", "misc", "minor", "done", "temp", "tmp",
    "save", "work", "progress", "more", "again", "ok", "idk", ".", "..", "...", "-", "x", "a", "init", "first commit",
    "initial commit", "update readme", "update readme.md", "bug fix", "bugfix", "small fix", "small changes",
    "minor changes", "minor fix", "final commit", "last commit", "added files", "add files", "add files via upload",
    "changes made", "some changes", "updated files", "update files", "fix bug", "fix bugs", "code",
}
# Conventional, self-explanatory first messages are not held against a project.
_BOOTSTRAP = {"init", "first commit", "initial commit"}
_SCAFFOLD_MESSAGE = re.compile(
    r"(?i)^(initial commit|first commit|init\b|initial (import|version|project|setup|scaffold)|bootstrap|scaffold|"
    r"project (setup|skeleton|scaffold)|create[- ](next|react|vite|t3|nuxt|expo|svelte)|"
    r"initial commit from create|initiali[sz]e (project|repo|repository)|django-admin startproject|ng new|rails new)"
)


def is_initial_scaffold(c: "Commit") -> bool:
    """A root commit that is recognisably project bootstrap: by its message, or because most of it is not original source."""
    if c.parents:
        return False
    non_original = sum(f.additions for f in c.files if f.category in NON_ORIGINAL)
    return bool(_SCAFFOLD_MESSAGE.search(c.subject.strip())) or (c.additions > 0 and non_original / c.additions >= 0.5)


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int
    binary: bool
    category: str


@dataclass
class Commit:
    sha: str
    parents: list[str]
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    author_time: datetime
    commit_time: datetime
    subject: str
    body: str
    files: list[FileChange] = field(default_factory=list)
    coauthors: list[tuple[str, str]] = field(default_factory=list)
    malformed_coauthor_trailers: int = 0
    classification: str = "UNCLEAR"
    on_default: bool = True

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def meaningful_additions(self) -> int:
        return sum(f.additions for f in self.files if f.category in MEANINGFUL)

    @property
    def short(self) -> str:
        return self.sha[:10]

    def brief(self) -> dict[str, Any]:
        return {
            "sha": self.short,
            "author": self.author_name,
            "author_time": self.author_time.isoformat(),
            "message": self.subject[:160],
            "files_changed": len(self.files),
            "additions": self.additions,
            "deletions": self.deletions,
            "meaningful_additions": self.meaningful_additions,
            "classification": self.classification,
        }


def parse_history(repo: Path, default_branch: str) -> list[Commit]:
    """All commits reachable from any ref, oldest first."""
    out = git(repo, "log", "--all", "--no-renames", "--numstat", "--date-order", f"--format={_FORMAT}")
    default_shas = set(git(repo, "rev-list", f"origin/{default_branch}", check=False).split()) or set(
        git(repo, "rev-list", "HEAD").split()
    )
    commits: list[Commit] = []
    for record in out.split("\x1e")[1:]:
        parts = record.split("\x1f")
        if len(parts) < 11:
            continue
        sha, parents, an, ae, cn, ce, at, ct, subject, body = parts[:10]
        commit = Commit(
            sha=sha.strip(), parents=parents.split(), author_name=an, author_email=ae, committer_name=cn,
            committer_email=ce, author_time=datetime.fromisoformat(at), commit_time=datetime.fromisoformat(ct),
            subject=subject, body=body,
        )
        for line in parts[10].splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            binary = cols[0] == "-"
            commit.files.append(
                FileChange(cols[2], 0 if binary else int(cols[0]), 0 if binary else int(cols[1]), binary, classify_path(cols[2]))
            )
        seen = set()
        for name, email in _COAUTHOR.findall(body):
            key = (name.strip(), email.strip().lower())
            if key not in seen:
                seen.add(key)
                commit.coauthors.append((name.strip(), email.strip()))
        commit.malformed_coauthor_trailers = max(0, len(_COAUTHOR_ANY.findall(body)) - len(_COAUTHOR.findall(body)))
        commit.on_default = commit.sha in default_shas
        commit.classification = classify_commit(commit)
        commits.append(commit)
    commits.reverse()
    return commits


def classify_commit(c: Commit) -> str:
    msg = c.subject.lower()
    if c.is_merge:
        return "MERGE"
    if msg.startswith("revert"):
        return "REVERT"
    cats = Counter(f.category for f in c.files)
    total = sum(cats.values())
    if total:
        top, n = cats.most_common(1)[0]
        if n == total:
            only = {"tests": "TEST", "docs": "DOCUMENTATION", "ci": "CI_CD", "lockfile": "DEPENDENCY", "config": "CONFIGURATION"}
            if top in only:
                return only[top]
            if top in NON_ORIGINAL:
                return "GENERATED_CODE"
    if re.search(r"\b(fix|fixes|fixed|bug|hotfix|patch)\b", msg):
        return "BUG_FIX"
    if re.search(r"\b(refactor|cleanup|clean up|restructure|rename|simplify)\b", msg):
        return "REFACTOR"
    if re.search(r"\b(format|lint|prettier|whitespace|style)\b", msg):
        return "FORMATTING"
    if re.search(r"\b(bump|upgrade|dependenc|deps)\b", msg):
        return "DEPENDENCY"
    if re.search(r"\b(test|tests|spec)\b", msg) and cats.get("tests"):
        return "TEST"
    if re.search(r"\b(doc|docs|readme)\b", msg) and cats.get("docs") and not cats.get("source"):
        return "DOCUMENTATION"
    if cats.get("source"):
        return "FEATURE"
    return "UNCLEAR"


def is_weak_message(subject: str) -> bool:
    s = re.sub(r"^(feat|fix|chore|docs|refactor|test|style|ci|build|perf)(\([^)]*\))?!?:\s*", "", subject.strip().lower())
    s = s.strip(" .!")
    if s in _BOOTSTRAP:
        return False
    return len(s) < 4 or s in WEAK_MESSAGES or bool(re.fullmatch(r"(v?\d+|[a-z]{1,3}\d*)", s))


def _whitespace_only(repo: Path, c: Commit) -> bool:
    """A commit with text changes whose diff vanishes when whitespace is ignored."""
    if not c.files or c.is_merge or any(f.binary for f in c.files):
        return False
    out = git(repo, "show", "--no-renames", "-w", "--ignore-blank-lines", "--numstat", "--format=", c.sha, check=False)
    changed = 0
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) == 3 and cols[0].isdigit():
            changed += int(cols[0]) + int(cols[1])
    return changed == 0 and (c.additions + c.deletions) > 0


def analyze(repo: Path, commits: list[Commit], store: EvidenceStore, cfg) -> dict[str, Any]:
    src = "commits"
    non_merge = [c for c in commits if not c.is_merge]
    classes = Counter(c.classification for c in commits)

    # --- message quality -------------------------------------------------------------------
    weak = [c for c in non_merge if is_weak_message(c.subject)]
    weak_ratio = round(len(weak) / max(1, len(non_merge)), 4)
    subjects = Counter(c.subject.strip().lower() for c in non_merge)
    repeated = [(s, n) for s, n in subjects.most_common(8) if n >= 3]
    quality = {
        "non_merge_commits": len(non_merge),
        "weak_message_commits": len(weak),
        "weak_message_ratio": weak_ratio,
        "median_subject_length": sorted(len(c.subject) for c in non_merge)[len(non_merge) // 2] if non_merge else 0,
        "conventional_commit_ratio": round(
            sum(bool(re.match(r"^[a-z]+(\([^)]*\))?!?: ", c.subject)) for c in non_merge) / max(1, len(non_merge)), 4
        ),
        "repeated_subjects": [{"message": s[:120], "count": n} for s, n in repeated],
    }
    quality_ev = store.add("commit_quality", src, f"{len(weak)}/{len(non_merge)} non-merge commits have low-information messages", quality)
    weak_ev = [store.add("commit", src, f"commit {c.short} message: {c.subject[:80]!r}", c.brief()) for c in weak[:12]]
    if len(non_merge) >= 5 and weak_ratio >= 0.4:
        store.add_anomaly(
            Category.COMMIT_INTEGRITY, "High share of low-information commit messages",
            f"{len(weak)} of {len(non_merge)} non-merge commits ({weak_ratio:.0%}) use generic messages, reducing traceability.",
            [quality_ev, *weak_ev], Severity.LOW, False,
            ["Informal workflow under time pressure", "Solo project where messages were not prioritised"], src,
        )

    # --- granularity -----------------------------------------------------------------------
    total_meaningful = sum(c.meaningful_additions for c in non_merge)
    large = [
        c for c in non_merge
        if len(c.files) >= cfg.large_commit_files or c.additions >= cfg.large_commit_additions
    ]
    large_rows = []
    for c in sorted(large, key=lambda c: -c.additions)[:10]:
        non_original = sum(f.additions for f in c.files if f.category in NON_ORIGINAL)
        row = {
            **c.brief(),
            "non_original_additions": non_original,
            "share_of_all_meaningful_additions": round(c.meaningful_additions / max(1, total_meaningful), 4),
            "is_root_commit": not c.parents,
            "is_initial_scaffold": is_initial_scaffold(c),
        }
        row["evidence_id"] = store.add("commit", src, f"large commit {c.short}: {len(c.files)} files, +{c.additions}", row)
        large_rows.append(row)
    sizes = sorted(c.additions + c.deletions for c in non_merge)
    root = next((c for c in commits if not c.parents), None)
    granularity = {
        "root_commit": {"sha": root.short, "message": root.subject[:100], "is_initial_scaffold": is_initial_scaffold(root), "additions": root.additions, "meaningful_additions": root.meaningful_additions} if root else None,
        "large_commit_thresholds": {"files": cfg.large_commit_files, "additions": cfg.large_commit_additions},
        "large_commits": len(large),
        "largest_commits": large_rows,
        "median_lines_changed": sizes[len(sizes) // 2] if sizes else 0,
        "max_lines_changed": sizes[-1] if sizes else 0,
        "total_meaningful_additions": total_meaningful,
    }
    for row in large_rows:
        # One commit in a one-commit repository, or a recognisable initial scaffold, is an observation, not an anomaly.
        if row["meaningful_additions"] >= 1000 and row["share_of_all_meaningful_additions"] >= 0.7 and len(non_merge) > 1 and not row["is_initial_scaffold"]:
            store.add_anomaly(
                Category.TIMELINE_ANOMALY, "Single commit introduces most of the meaningful source",
                f"Commit {row['sha']} adds {row['meaningful_additions']} of {total_meaningful} meaningful source lines "
                f"({row['share_of_all_meaningful_additions']:.0%}) in one step.",
                [row["evidence_id"]], Severity.MEDIUM, True,
                ["Migration from another repository", "Squashed history", "Offline development", "Framework scaffold", "Copied or generated code"], src,
            )

    # --- inflation signals -----------------------------------------------------------------
    empty = [c for c in non_merge if not c.files]
    tiny = [c for c in non_merge if c.files and (c.additions + c.deletions) <= 2 and not any(f.binary for f in c.files)]
    reverts = [c for c in non_merge if c.classification == "REVERT"]
    candidates = [c for c in non_merge if c.files and (c.additions + c.deletions) <= 40][:300]
    ws_only = [c for c in candidates if _whitespace_only(repo, c)]

    bursts = []
    run: list[Commit] = []

    def close_run() -> None:
        if len(run) >= 6:
            bursts.append(
                {
                    "author": run[0].author_name, "commits": len(run), "file": run[0].files[0].path,
                    "from": run[0].author_time.isoformat(), "to": run[-1].author_time.isoformat(),
                    "total_lines_changed": sum(c.additions + c.deletions for c in run),
                    "shas": [c.short for c in run[:8]],
                }
            )

    for c in non_merge:
        single = len(c.files) == 1 and (c.additions + c.deletions) <= 5
        if (
            single and run and c.author_email.lower() == run[-1].author_email.lower()
            and c.files[0].path == run[-1].files[0].path
            and abs(c.author_time - run[-1].author_time) <= timedelta(minutes=10)
        ):
            run.append(c)
        else:
            close_run()
            run = [c] if single else []
    close_run()

    readme_trivial = [
        c for c in non_merge
        if c.files and all(f.path.lower().startswith("readme") for f in c.files) and (c.additions + c.deletions) <= 3
    ]
    n = max(1, len(non_merge))
    inflation = {
        "empty_commits": len(empty),
        "whitespace_only_commits": len(ws_only),
        "whitespace_check_scope": f"{len(candidates)} smallest-diff commits inspected",
        "tiny_commits_le_2_lines": len(tiny),
        "tiny_commit_ratio": round(len(tiny) / n, 4),
        "revert_commits": len(reverts),
        "trivial_readme_commits": len(readme_trivial),
        "rapid_single_file_bursts": bursts,
    }
    inflation_ev = store.add("commit_inflation", src, "commit-count inflation indicators (counts, not intent)", inflation)
    signals = []
    if empty:
        signals.append((f"{len(empty)} empty commit(s)", [store.add("commit", src, f"empty commit {c.short}", c.brief()) for c in empty[:6]]))
    if len(ws_only) >= 3:  # one or two isolated whitespace commits are ordinary; a repeated pattern is a signal
        signals.append((f"{len(ws_only)} whitespace-only commit(s)", [store.add("commit", src, f"whitespace-only commit {c.short}", c.brief()) for c in ws_only[:6]]))
    if bursts:
        signals.append((f"{len(bursts)} rapid burst(s) of tiny single-file commits", [store.add("commit_burst", src, f"{b['commits']} tiny commits to {b['file']} within minutes", b) for b in bursts[:4]]))
    if len(non_merge) >= 10 and len(tiny) / n >= 0.4:
        signals.append((f"{len(tiny)}/{len(non_merge)} commits change 2 lines or fewer", []))
    if len(readme_trivial) >= 5:
        signals.append((f"{len(readme_trivial)} trivial README-only commits", [store.add("commit", src, f"trivial README commit {c.short}", c.brief()) for c in readme_trivial[:6]]))
    weight = len(empty) + (len(ws_only) if len(ws_only) >= 3 else 0) + sum(b["commits"] for b in bursts) + (len(tiny) if len(tiny) / n >= 0.4 else 0) + (len(readme_trivial) if len(readme_trivial) >= 5 else 0)
    if signals:
        share = weight / n
        store.add_anomaly(
            Category.COMMIT_INFLATION, "Commits with little or no semantic effect",
            "; ".join(s for s, _ in signals) + f". Roughly {min(share, 1):.0%} of non-merge commits are affected.",
            [inflation_ev, *[e for _, ids in signals for e in ids]],
            Severity.MEDIUM if share >= 0.3 else Severity.LOW, share >= 0.3 and weight >= 8,
            ["Editing files through the GitHub web UI", "Triggering CI re-runs", "Incremental save-style workflow"], src,
        )
    inflation["signals"] = [s for s, _ in signals]

    return {
        "total": len(commits),
        "non_merge": len(non_merge),
        "merge": len(commits) - len(non_merge),
        "on_default_branch": sum(c.on_default for c in commits),
        "classification": dict(classes),
        "quality": quality,
        "granularity": granularity,
        "inflation": inflation,
        "evidence": {"quality": quality_ev, "inflation": inflation_ev},
    }
