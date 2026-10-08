"""Read-only GitHub REST metadata. Every endpoint failure is recorded, never swallowed."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

API = "https://api.github.com"


def _get(path: str, token: Optional[str], timeout: float = 20) -> Any:
    request = urllib.request.Request(
        f"{API}{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "argus-repo-integrity-agent", "X-GitHub-Api-Version": "2022-11-28"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))


def collect(owner: str, name: str, token: Optional[str], fetch=_get) -> dict[str, Any]:
    base = f"/repos/{owner}/{name}"
    # coverage: one explicit status per endpoint, so "nothing there" is never confused with "could not look".
    #   SUCCESS         data returned
    #   EMPTY           endpoint answered, nothing exists (e.g. zero pull requests)
    #   UNVERIFIABLE    endpoint refused (rate limit, permissions, not found): absence of data is NOT evidence
    #   ERROR           transport or parsing failure on the ARGUS side of the call
    #   NOT_APPLICABLE  deliberately not requested
    result: dict[str, Any] = {"authenticated": bool(token), "available": {}, "errors": {}, "coverage": {}}

    def call(key: str, path: str) -> Any:
        try:
            data = fetch(path, token)
            result["available"][key] = True
            count = len(data.get("workflow_runs", data.get("workflows", data))) if isinstance(data, dict) and ("workflow_runs" in data or "workflows" in data) else (len(data) if isinstance(data, list) else 1)
            result["coverage"][key] = "SUCCESS" if count else "EMPTY"
            return data
        except urllib.error.HTTPError as exc:
            result["errors"][key] = f"HTTP {exc.code} {exc.reason}"
            result["coverage"][key] = "UNVERIFIABLE"
        except Exception as exc:  # network, JSON, timeout
            result["errors"][key] = f"{type(exc).__name__}: {exc}"
            result["coverage"][key] = "ERROR"
        result["available"][key] = False
        return None

    repo = call("metadata", base)
    if repo:
        result["metadata"] = {
            "full_name": repo.get("full_name"), "visibility": repo.get("visibility"), "created_at": repo.get("created_at"),
            "updated_at": repo.get("updated_at"), "pushed_at": repo.get("pushed_at"), "default_branch": repo.get("default_branch"),
            "fork": repo.get("fork"), "parent": (repo.get("parent") or {}).get("full_name"),
            "template": (repo.get("template_repository") or {}).get("full_name"),
            "license": (repo.get("license") or {}).get("spdx_id"), "language": repo.get("language"),
            "size_kb": repo.get("size"), "stars": repo.get("stargazers_count"), "forks": repo.get("forks_count"),
            "archived": repo.get("archived"),
        }

    pulls = call("pull_requests", f"{base}/pulls?state=all&per_page=100")
    if pulls is not None:
        rows = []
        for p in pulls:
            row = {
                "number": p.get("number"), "title": (p.get("title") or "")[:120], "author": (p.get("user") or {}).get("login"),
                "state": p.get("state"), "merged": bool(p.get("merged_at")), "created_at": p.get("created_at"),
                "merged_at": p.get("merged_at"), "head": (p.get("head") or {}).get("ref"), "base": (p.get("base") or {}).get("ref"),
                "requested_reviewers": [r.get("login") for r in p.get("requested_reviewers") or []],
            }
            rows.append(row)
        if token:  # review detail costs one call per PR; only with an authenticated rate limit
            for row in rows[:30]:
                reviews = call(f"reviews_pr_{row['number']}", f"{base}/pulls/{row['number']}/reviews?per_page=50")
                if reviews is not None:
                    row["reviews"] = [{"reviewer": (r.get("user") or {}).get("login"), "state": r.get("state")} for r in reviews]
            outcomes = [result["coverage"].pop(f"reviews_pr_{row['number']}", None) for row in rows[:30]]
            for row in rows[:30]:
                result["available"].pop(f"reviews_pr_{row['number']}", None)
            result["coverage"]["pull_request_reviews"] = "SUCCESS" if any(o in ("SUCCESS", "EMPTY") for o in outcomes) else ("UNVERIFIABLE" if outcomes else "EMPTY")
        else:
            result["coverage"]["pull_request_reviews"] = "NOT_APPLICABLE"  # one call per PR: only with an authenticated rate limit
        result["pull_requests"] = {
            "count": len(rows), "truncated_at_100": len(rows) == 100, "merged": sum(r["merged"] for r in rows),
            "authors": sorted({r["author"] for r in rows if r["author"]}),
            "with_reviews": sum(1 for r in rows if r.get("reviews")) if token else None,
            "items": rows[:50],
        }

    runs = call("workflow_runs", f"{base}/actions/runs?per_page=100")
    if runs is not None:
        items = runs.get("workflow_runs") or []
        by_conclusion: dict[str, int] = {}
        for r in items:
            key = r.get("conclusion") or r.get("status") or "unknown"
            by_conclusion[key] = by_conclusion.get(key, 0) + 1
        result["workflow_runs"] = {
            "total_count": runs.get("total_count"), "sampled": len(items), "by_conclusion": by_conclusion,
            "latest": [
                {"workflow": r.get("name"), "event": r.get("event"), "conclusion": r.get("conclusion"), "branch": r.get("head_branch"), "created_at": r.get("created_at")}
                for r in items[:10]
            ],
        }

    workflows = call("workflows", f"{base}/actions/workflows?per_page=100")
    if workflows is not None:
        result["workflows"] = [{"name": w.get("name"), "path": w.get("path"), "state": w.get("state")} for w in workflows.get("workflows") or []]

    branches = call("branches", f"{base}/branches?per_page=100")
    if branches is not None:
        result["branches"] = [{"name": b.get("name"), "protected": b.get("protected")} for b in branches]

    contributors = call("contributors", f"{base}/contributors?per_page=100")
    if contributors is not None:
        result["contributors"] = [{"login": c.get("login"), "contributions": c.get("contributions"), "type": c.get("type")} for c in contributors]

    releases = call("releases", f"{base}/releases?per_page=100")
    if releases is not None:
        result["releases"] = [{"tag": r.get("tag_name"), "published_at": r.get("published_at")} for r in releases]
    # Commit history and issues are not requested from the API: commits come from the full Git clone
    # (authoritative), and ARGUS has no issues collector.
    result["coverage"]["commits"] = "NOT_APPLICABLE"
    result["coverage"]["issues"] = "NOT_APPLICABLE"
    return result
