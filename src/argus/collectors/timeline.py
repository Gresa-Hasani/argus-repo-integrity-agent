"""Development timeline, branches and merges."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from argus.collectors.commits import Commit
from argus.collectors.gitutil import git
from argus.evidence import EvidenceStore
from argus.models import Category, Severity


def parse_deadline(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def analyze_timeline(commits: list[Commit], store: EvidenceStore, cfg) -> dict[str, Any]:
    src = "timeline"
    non_merge = [c for c in commits if not c.is_merge]
    times = [c.author_time for c in commits]
    first, last = min(times), max(times)
    span = last - first
    deadline = parse_deadline(cfg.deadline)

    days: dict[str, dict[str, Any]] = defaultdict(lambda: {"commits": 0, "additions": 0, "meaningful_additions": 0, "authors": set()})
    for c in non_merge:
        d = days[c.author_time.astimezone(timezone.utc).date().isoformat()]
        d["commits"] += 1
        d["additions"] += c.additions
        d["meaningful_additions"] += c.meaningful_additions
        d["authors"].add(c.author_name)
    per_day = [{"date": k, **{**v, "authors": sorted(v["authors"])}} for k, v in sorted(days.items())]

    def first_commit(pred) -> Optional[dict[str, Any]]:
        for c in commits:
            if any(pred(f) for f in c.files):
                return {"sha": c.short, "time": c.author_time.isoformat(), "message": c.subject[:100]}
        return None

    milestones = {
        "initial_commit": {"sha": commits[0].short, "time": commits[0].author_time.isoformat(), "message": commits[0].subject[:100]},
        "tests_introduced": first_commit(lambda f: f.category == "tests"),
        "ci_introduced": first_commit(lambda f: f.category == "ci"),
        "readme_introduced": first_commit(lambda f: f.path.lower().startswith("readme")),
        "final_activity": {"sha": commits[-1].short, "time": last.isoformat(), "message": commits[-1].subject[:100]},
    }

    total_meaningful = sum(c.meaningful_additions for c in non_merge)
    if deadline:
        window_end, window = deadline, timedelta(hours=cfg.late_window_hours)
        basis = f"final {cfg.late_window_hours:g}h before the configured deadline"
    else:
        window_end = last
        window = max(span * 0.1, timedelta(hours=1)) if span > timedelta(hours=10) else timedelta(0)
        basis = "final 10% of the observed project duration (no deadline configured)"
    late = [c for c in non_merge if window and window_end - window <= c.author_time <= window_end]
    late_meaningful = sum(c.meaningful_additions for c in late)
    late_drop = {
        "window_basis": basis,
        "window_start": (window_end - window).isoformat() if window else None,
        "window_end": window_end.isoformat(),
        "commits_in_window": len(late),
        "meaningful_additions_in_window": late_meaningful,
        "total_meaningful_additions": total_meaningful,
        "share": round(late_meaningful / total_meaningful, 4) if total_meaningful and window else None,
    }

    after_deadline = [c for c in commits if deadline and c.author_time > deadline]
    backdated = [c for c in commits if (c.commit_time - c.author_time) > timedelta(days=1)]
    future = [c for c in commits if c.author_time - c.commit_time > timedelta(hours=1)]

    metrics = {
        "first_commit": first.isoformat(),
        "last_commit": last.isoformat(),
        "duration_hours": round(span.total_seconds() / 3600, 2),
        "active_days": len(per_day),
        "commits_per_active_day": round(len(non_merge) / max(1, len(per_day)), 2),
        "per_day": per_day[-60:],
        "milestones": milestones,
        "late_window": late_drop,
        "deadline": deadline.isoformat() if deadline else None,
        "commits_after_deadline": len(after_deadline),
        "author_date_much_earlier_than_commit_date": len(backdated),
        "author_date_later_than_commit_date": len(future),
    }
    timeline_ev = store.add(
        "timeline", src, f"{len(commits)} commits over {metrics['duration_hours']}h across {len(per_day)} active day(s)",
        {k: v for k, v in metrics.items() if k != "per_day"} | {"per_day": per_day[-14:]},
    )
    metrics["evidence"] = {"timeline": timeline_ev}

    if late_drop["share"] is not None and late_drop["share"] >= 0.6 and total_meaningful >= 1000 and len(non_merge) > 3:
        store.add_anomaly(
            Category.TIMELINE_ANOMALY, "Most meaningful source arrived in the final window",
            f"{late_meaningful} of {total_meaningful} meaningful source lines ({late_drop['share']:.0%}) were added in the {basis}.",
            [timeline_ev, *[store.add("commit", src, f"late-window commit {c.short}", c.brief()) for c in sorted(late, key=lambda c: -c.meaningful_additions)[:5]]],
            Severity.MEDIUM, True,
            ["Branch merge near the end", "Squashed or migrated history", "Offline development pushed late", "Generated scaffold", "Copied project"], src,
        )
    if after_deadline:
        store.add_anomaly(
            Category.TIMELINE_ANOMALY, "Commits authored after the configured deadline",
            f"{len(after_deadline)} commit(s) carry author timestamps after {deadline.isoformat()}.",
            [timeline_ev, *[store.add("commit", src, f"post-deadline commit {c.short}", c.brief()) for c in after_deadline[:6]]],
            Severity.MEDIUM, True, ["Documentation-only fixes permitted by the rules", "Clock/timezone differences"], src,
        )
    if backdated or future:
        store.add_anomaly(
            Category.COMMIT_INTEGRITY, "Author and committer timestamps diverge",
            f"{len(backdated)} commit(s) were authored more than a day before being committed; {len(future)} have an author date later than the commit date. Timestamps are client-supplied.",
            [timeline_ev, *[store.add("commit", src, f"timestamp divergence in {c.short}", {**c.brief(), "commit_time": c.commit_time.isoformat()}) for c in (backdated + future)[:6]]],
            Severity.LOW, False, ["Rebase, amend or cherry-pick", "Patches applied later", "Incorrect local clock"], src,
        )
    return metrics


def analyze_branches(repo: Path, commits: list[Commit], default_branch: str, store: EvidenceStore) -> dict[str, Any]:
    src = "branches"
    by_sha = {c.sha: c for c in commits}
    last_repo_time = max(c.commit_time for c in commits)
    default_ref = f"origin/{default_branch}"
    out = git(repo, "for-each-ref", "--format=%(refname:short)%1f%(objectname)%1f%(committerdate:iso-strict)%1f%(authorname)", "refs/remotes/origin")
    merged = {b.strip() for b in git(repo, "branch", "-r", "--merged", default_ref, check=False).splitlines()}
    branches = []
    for line in out.splitlines():
        name, sha, date, author = (line.split("\x1f") + ["", "", ""])[:4]
        if name in {"origin/HEAD", "origin"} or not name.startswith("origin/"):
            continue
        short = name[len("origin/"):]
        row: dict[str, Any] = {"name": short, "head": sha[:10], "last_commit": date, "last_author": author, "is_default": short == default_branch}
        if not row["is_default"]:
            counts = git(repo, "rev-list", "--left-right", "--count", f"{default_ref}...{name}", check=False).split()
            row["behind_default"], row["ahead_of_default"] = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (None, None)
            row["merged_into_default"] = name in merged
            try:
                row["stale"] = not row["merged_into_default"] and (last_repo_time - datetime.fromisoformat(date)) > timedelta(days=30)
            except ValueError:
                row["stale"] = None
        branches.append(row)
    tags = [t for t in git(repo, "tag", "--list").splitlines() if t]

    merges = []
    for c in commits:
        if not c.is_merge:
            continue
        pr = re.search(r"Merge pull request #(\d+) from (\S+)", c.subject)
        br = re.search(r"Merge (?:remote-tracking )?branch '([^']+)'(?: of \S+)?(?: into (\S+))?", c.subject)
        stat = git(repo, "diff", "--shortstat", c.parents[0], c.sha, check=False) if len(merges) < 60 else ""
        nums = [int(x) for x in re.findall(r"(\d+) (?:file|insertion|deletion)", stat)]
        ins = re.search(r"(\d+) insertion", stat)
        dele = re.search(r"(\d+) deletion", stat)
        merges.append(
            {
                "sha": c.short, "author": c.author_name, "committer": c.committer_name, "time": c.author_time.isoformat(),
                "message": c.subject[:120], "pull_request": int(pr.group(1)) if pr else None,
                "source": pr.group(2) if pr else (br.group(1) if br else None),
                "destination": (br.group(2) if br and br.group(2) else default_branch) if (pr or br) else None,
                "files_integrated": nums[0] if nums else 0,
                "insertions": int(ins.group(1)) if ins else 0, "deletions": int(dele.group(1)) if dele else 0,
                "second_parent_commits": sum(1 for p in c.parents[1:] if p in by_sha),
            }
        )
    empty_merges = [m for m in merges[:60] if m["files_integrated"] == 0]
    feature = [b for b in branches if not b["is_default"]]
    authors_on_default = {c.author_email.lower() for c in commits if c.on_default and not c.is_merge}
    metrics = {
        "default_branch": default_branch,
        "branch_count": len(branches),
        "branches": branches[:60],
        "unmerged_branches": [b["name"] for b in feature if b.get("merged_into_default") is False],
        "stale_branches": [b["name"] for b in feature if b.get("stale")],
        "tags": tags[:50],
        "merge_commits": len(merges),
        "merges": merges[:40],
        "merges_with_no_integrated_changes": len(empty_merges),
        "workflow": "direct commits to default branch only" if not feature and not merges else "branches and/or merges present",
        "distinct_authors_on_default": len(authors_on_default),
    }
    ev = store.add(
        "branches", src, f"{len(branches)} branch(es), {len(merges)} merge commit(s), {len(tags)} tag(s)",
        {k: v for k, v in metrics.items() if k not in {"branches", "merges"}} | {"branches": branches[:15], "merges": merges[:12]},
    )
    metrics["evidence"] = {"branches": ev}
    if len(empty_merges) >= 5 and len(empty_merges) / max(1, len(merges)) >= 0.5:
        store.add_anomaly(
            Category.BRANCH_WORKFLOW, "Many merge commits integrate no changes",
            f"{len(empty_merges)} of {len(merges)} merge commits show no difference against their first parent.",
            [ev], Severity.LOW, False, ["Frequent `git pull` without rebase", "Keeping branches in sync"], src,
        )
    big = [m for m in merges if m["insertions"] >= 3000]
    if big and commits:
        span = (commits[-1].author_time - commits[0].author_time).total_seconds()
        late = [m for m in big if span > 36000 and (datetime.fromisoformat(m["time"]) - commits[0].author_time).total_seconds() >= 0.9 * span]
        if late:
            store.add_anomaly(
                Category.BRANCH_WORKFLOW, "Large merge late in the timeline",
                f"{len(late)} merge(s) of 3000+ insertions landed in the final 10% of the project duration.",
                [ev], Severity.LOW, False, ["Feature branch integrated at the end", "Release merge"], src,
            )
    return metrics
