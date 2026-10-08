"""Contributor discovery, evidence-based identity normalisation, contribution and co-authorship metrics."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from argus.collectors.classify import MEANINGFUL, NON_ORIGINAL, component_of, language_of
from argus.collectors.commits import Commit
from argus.evidence import EvidenceStore
from argus.models import Category, Severity

_NOREPLY = re.compile(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$", re.I)
_AI_EMAILS = {"noreply@anthropic.com", "cursoragent@cursor.com", "noreply@openai.com", "noreply@cursor.com"}
_AI_NAMES = re.compile(r"^(claude|claude code|copilot|github copilot|cursor agent|cursor|devin|codex|aider|gemini|windsurf|openhands)\b", re.I)


def identity_kind(name: str, email: str) -> str:
    e = email.lower()
    if e == "noreply@github.com" and name.lower() == "github":
        return "platform"
    if "[bot]" in name.lower() or "[bot]" in e:
        return "bot"
    if e in _AI_EMAILS or e.endswith("+copilot@users.noreply.github.com") or _AI_NAMES.match(name.strip()):
        return "ai_tool"
    return "human"


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}

    def find(self, x: Any) -> Any:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: Any, b: Any) -> None:
        self.parent[self.find(a)] = self.find(b)


def build_identity_map(commits: list[Commit]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str]]:
    """Group raw (name, email) identities only when repository evidence supports it."""
    roles: dict[tuple[str, str], set[str]] = defaultdict(set)
    uses: Counter = Counter()
    for c in commits:
        for role, name, email in (("author", c.author_name, c.author_email), ("committer", c.committer_name, c.committer_email)):
            key = (name, email.lower())
            roles[key].add(role)
            uses[key] += role == "author"
        for name, email in c.coauthors:
            roles[(name, email.lower())].add("co-author")

    uf = _UnionFind()
    reasons: dict[Any, list[str]] = defaultdict(list)
    keys = list(roles)
    by_email: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        uf.find(key)
        by_email[key[1]].append(key)
    for email, group in by_email.items():
        for other in group[1:]:
            uf.union(group[0], other)
            reasons[frozenset((group[0], other))].append(f"identical email {email}")
    for key in keys:
        m = _NOREPLY.match(key[1])
        if not m:
            continue
        login = m.group(1).lower()
        for other in keys:
            if other == key or uf.find(other) == uf.find(key):
                continue
            if other[0].lower() == login or other[1].split("@")[0] == login or other[0].casefold() == key[0].casefold():
                uf.union(key, other)
                reasons[frozenset((key, other))].append("GitHub noreply address matches name/login of the other identity")

    groups: dict[Any, list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        groups[uf.find(key)].append(key)

    contributors = []
    lookup: dict[tuple[str, str], str] = {}
    ordered = sorted(groups.values(), key=lambda g: -sum(uses[k] for k in g))
    for index, group in enumerate(ordered, 1):
        cid = f"C{index}"
        canonical = max(group, key=lambda k: (uses[k], len(k[0])))
        kinds = {identity_kind(n, e) for n, e in group}
        kind = "human" if "human" in kinds else sorted(kinds)[0]
        why = sorted({r for pair, rs in reasons.items() if pair <= set(group) for r in rs})
        contributors.append(
            {
                "id": cid,
                "canonical_contributor": canonical[0],
                "kind": kind,
                "identities": [f"{n} <{e}>" for n, e in sorted(group)],
                "roles": sorted({r for k in group for r in roles[k]}),
                "merge_basis": why,
                "confidence": "HIGH" if len(group) == 1 or all("identical email" in r for r in why) else "MEDIUM",
            }
        )
        for key in group:
            lookup[key] = cid

    names: dict[str, set[str]] = defaultdict(set)
    for c in contributors:
        if c["kind"] == "human":
            names[c["canonical_contributor"].casefold()].add(c["id"])
    for c in contributors:
        same = names.get(c["canonical_contributor"].casefold(), set()) - {c["id"]}
        # Reported, not merged: a shared display name alone is not identity evidence.
        c["possibly_same_person_as"] = sorted(same)
    return contributors, lookup


def analyze(commits: list[Commit], store: EvidenceStore) -> dict[str, Any]:
    src = "contributors"
    identity_map, lookup = build_identity_map(commits)
    by_id = {c["id"]: c for c in identity_map}

    def cid(name: str, email: str) -> str:
        return lookup[(name, email.lower())]

    stats: dict[str, dict[str, Any]] = {}
    for c in identity_map:
        stats[c["id"]] = {
            "authored_commits": 0, "committed_commits": 0, "coauthored_commits": 0, "merge_commits": 0,
            "raw_additions": 0, "raw_deletions": 0, "meaningful_additions_estimate": 0, "meaningful_deletions_estimate": 0,
            "additions_by_category": Counter(), "files": set(), "days": set(), "languages": Counter(),
            "components": Counter(), "first": None, "last": None, "coauthored_additions": 0,
            "authored_with_coauthor": 0, "class": Counter(),
        }

    def touch(s: dict[str, Any], c: Commit) -> None:
        s["days"].add(c.author_time.date().isoformat())
        s["first"] = min(s["first"], c.author_time) if s["first"] else c.author_time
        s["last"] = max(s["last"], c.author_time) if s["last"] else c.author_time

    author_ne_committer = Counter()
    coauthor_rows = []
    pair_counts: Counter = Counter()
    for c in commits:
        a = cid(c.author_name, c.author_email)
        k = cid(c.committer_name, c.committer_email)
        s = stats[a]
        s["authored_commits"] += 1
        s["class"][c.classification] += 1
        touch(s, c)
        stats[k]["committed_commits"] += 1
        if a != k:
            author_ne_committer[(by_id[a]["canonical_contributor"], by_id[k]["canonical_contributor"], by_id[k]["kind"])] += 1
        if c.is_merge:
            s["merge_commits"] += 1
        else:
            for f in c.files:
                s["raw_additions"] += f.additions
                s["raw_deletions"] += f.deletions
                s["additions_by_category"][f.category] += f.additions
                if f.category in MEANINGFUL:
                    s["meaningful_additions_estimate"] += f.additions
                    s["meaningful_deletions_estimate"] += f.deletions
                    s["languages"][language_of(f.path)] += f.additions
                    s["components"][component_of(f.path)] += f.additions
                s["files"].add(f.path)
        if c.coauthors:
            s["authored_with_coauthor"] += 1
            co_ids = []
            for name, email in c.coauthors:
                co = cid(name, email)
                if co == a or co in co_ids:
                    continue
                co_ids.append(co)
                stats[co]["coauthored_commits"] += 1
                stats[co]["coauthored_additions"] += c.additions
                touch(stats[co], c)
                pair_counts[(a, co)] += 1
            coauthor_rows.append(
                {
                    "sha": c.short, "primary_author": by_id[a]["canonical_contributor"],
                    "committer": by_id[k]["canonical_contributor"],
                    "coauthors": [by_id[x]["canonical_contributor"] for x in co_ids],
                    "coauthor_ids": co_ids, "timestamp": c.author_time.isoformat(), "message": c.subject[:120],
                    "files_changed": len(c.files), "additions": c.additions, "deletions": c.deletions,
                }
            )

    human_ids = [c["id"] for c in identity_map if c["kind"] == "human"]
    total_meaningful = sum(stats[i]["meaningful_additions_estimate"] for i in human_ids)
    total_authored = sum(stats[i]["authored_commits"] for i in human_ids)

    contributors = []
    evidence_ids: dict[str, str] = {}
    for c in identity_map:
        s = stats[c["id"]]
        appearances = s["authored_commits"] + s["coauthored_commits"]
        by_cat = dict(s["additions_by_category"])
        row = {
            "id": c["id"], "name": c["canonical_contributor"], "kind": c["kind"],
            "authored_commits": s["authored_commits"], "committed_commits": s["committed_commits"],
            "coauthored_commits": s["coauthored_commits"], "merge_commits": s["merge_commits"],
            "total_commit_appearances": appearances,
            "coauthor_ratio": round(s["coauthored_commits"] / appearances, 4) if appearances else None,
            "first_activity": s["first"].isoformat() if s["first"] else None,
            "last_activity": s["last"].isoformat() if s["last"] else None,
            "active_days": len(s["days"]), "files_touched": len(s["files"]),
            "raw_additions": s["raw_additions"], "raw_deletions": s["raw_deletions"],
            "net_lines": s["raw_additions"] - s["raw_deletions"],
            "meaningful_additions_estimate": s["meaningful_additions_estimate"],
            "meaningful_deletions_estimate": s["meaningful_deletions_estimate"],
            "generated_or_vendored_additions": sum(v for k, v in by_cat.items() if k in NON_ORIGINAL),
            "test_additions": by_cat.get("tests", 0), "documentation_additions": by_cat.get("docs", 0),
            "configuration_additions": by_cat.get("config", 0) + by_cat.get("ci", 0), "ci_additions": by_cat.get("ci", 0),
            "additions_by_category": by_cat,
            "share_of_meaningful_additions": round(s["meaningful_additions_estimate"] / total_meaningful, 4) if total_meaningful and c["kind"] == "human" else None,
            "share_of_authored_commits": round(s["authored_commits"] / total_authored, 4) if total_authored and c["kind"] == "human" else None,
            "languages_touched": [k for k, _ in s["languages"].most_common(6)],
            "components_touched": [k for k, _ in s["components"].most_common(8)],
            "commit_classes": dict(s["class"]),
            "coauthored_commit_additions_not_attributed": s["coauthored_additions"],
        }
        contributors.append(row)
        if c["kind"] != "platform":
            slim = {k: v for k, v in row.items() if k not in {"additions_by_category", "commit_classes"}}
            evidence_ids[c["id"]] = store.add(
                "contributor", src,
                f"{row['name']} ({c['kind']}): {row['authored_commits']} authored, {row['coauthored_commits']} co-authored, "
                f"+{row['raw_additions']} raw / +{row['meaningful_additions_estimate']} meaningful (est.)", slim,
            )

    identity_ev = store.add(
        "identity_map", src, f"{len(identity_map)} canonical contributors from {sum(len(c['identities']) for c in identity_map)} raw identities",
        {"contributors": [{k: c[k] for k in ("id", "canonical_contributor", "kind", "identities", "merge_basis", "confidence", "possibly_same_person_as")} for c in identity_map]},
    )

    # --- authorship --------------------------------------------------------------------------
    mismatches = [{"author": a, "committer": k, "committer_kind": kind, "commits": n} for (a, k, kind), n in author_ne_committer.most_common(15)]
    unexplained = sum(m["commits"] for m in mismatches if m["committer_kind"] == "human")
    authorship = {
        "author_differs_from_committer": sum(author_ne_committer.values()),
        "via_platform_or_bot_committer": sum(m["commits"] for m in mismatches if m["committer_kind"] != "human"),
        "between_human_identities": unexplained,
        "pairs": mismatches,
    }
    authorship_ev = store.add("authorship", src, f"{authorship['author_differs_from_committer']} commits where author != committer ({unexplained} between human identities)", authorship)

    # --- distribution ------------------------------------------------------------------------
    humans = [r for r in contributors if r["kind"] == "human" and (r["authored_commits"] or r["coauthored_commits"])]
    if len(humans) >= 2 and total_meaningful >= 300:
        top = max(humans, key=lambda r: r["meaningful_additions_estimate"])
        if (top["share_of_meaningful_additions"] or 0) >= 0.9:
            store.add_anomaly(
                Category.CONTRIBUTION_INTEGRITY, "Meaningful source concentrated in one contributor",
                f"{top['name']} accounts for {top['share_of_meaningful_additions']:.0%} of meaningful source additions across {len(humans)} human contributors. This is a distribution observation, not a quality or misconduct judgement.",
                [evidence_ids[r["id"]] for r in humans], Severity.LOW, False,
                ["One person integrating/committing the team's work", "Uneven role split (e.g. design, data, documentation)", "Pair programming on one machine"], src,
            )
    # Raw LOC far above meaningful LOC is fully explained by path classification (lockfiles, generated,
    # vendored, data, config). That is codebase composition: reported as evidence, never as an anomaly.

    # --- co-authorship -----------------------------------------------------------------------
    non_merge_total = sum(1 for c in commits if not c.is_merge)
    matrix = [
        {
            "contributor": r["name"], "id": r["id"], "kind": r["kind"], "own_authored_commits": r["authored_commits"],
            "coauthored_appearances": r["coauthored_commits"], "total_appearances": r["total_commit_appearances"],
            "coauthor_ratio": r["coauthor_ratio"],
        }
        for r in contributors if r["total_commit_appearances"]
    ]
    relationships = [
        {"primary_author": by_id[a]["canonical_contributor"], "coauthor": by_id[b]["canonical_contributor"], "coauthor_kind": by_id[b]["kind"], "commits": n}
        for (a, b), n in pair_counts.most_common(20)
    ]
    coauthor = {
        "total_coauthored_commits": len(coauthor_rows),
        "share_of_non_merge_commits": round(len(coauthor_rows) / max(1, non_merge_total), 4),
        "malformed_trailers": sum(c.malformed_coauthor_trailers for c in commits),
        "matrix": matrix,
        "relationships": relationships,
        "commits": coauthor_rows[:200],
        "suspicious_patterns": [],
    }
    coauthor_ev = store.add(
        "coauthorship", src, f"{len(coauthor_rows)} commits carry Co-authored-by trailers",
        {k: coauthor[k] for k in ("total_coauthored_commits", "share_of_non_merge_commits", "malformed_trailers", "matrix", "relationships")},
    )
    sample_ev = [store.add("commit", src, f"co-authored commit {r['sha']} by {r['primary_author']} with {', '.join(r['coauthors'])}", {k: v for k, v in r.items() if k != "coauthor_ids"}) for r in coauthor_rows[:10]]

    explanations = ["Pair programming", "Shared implementation or joint debugging", "Mob sessions committed from one machine"]
    times = [c.author_time for c in commits]
    span = (max(times) - min(times)).total_seconds() if times else 0
    for r in humans:
        co = r["coauthored_commits"]
        rows = [x for x in coauthor_rows if r["id"] in x["coauthor_ids"]]
        patterns = []
        material = False
        if co >= 5 and (r["coauthor_ratio"] or 0) >= 0.8:
            patterns.append(f"{co} co-authored appearances vs {r['authored_commits']} independently authored commits (ratio {r['coauthor_ratio']:.0%})")
            material = True
        if non_merge_total >= 10 and co / non_merge_total >= 0.9:
            patterns.append(f"listed as co-author on {co} of {non_merge_total} non-merge commits")
            material = True
        if co >= 4:
            trivial = sum(1 for x in rows if x["additions"] + x["deletions"] <= 5)
            if trivial / co >= 0.5:
                patterns.append(f"{trivial} of {co} co-authored commits change 5 lines or fewer")
            if span > 86400:
                start = min(times).timestamp() + 0.8 * span
                late = sum(1 for x in rows if _ts(x["timestamp"]) >= start)
                if late == co:
                    patterns.append("all co-author trailers fall in the final 20% of the project timeline")
            comps = {x["primary_author"] for x in rows}
            if len(comps) >= 3 and r["authored_commits"] == 0:
                patterns.append(f"co-author for {len(comps)} different primary authors with no commits of their own")
        if patterns:
            text = f"{r['name']}: " + "; ".join(patterns) + "."
            coauthor["suspicious_patterns"].append({"contributor": r["name"], "patterns": patterns, "material": material})
            store.add_anomaly(
                Category.COAUTHOR_INTEGRITY, f"Unusual co-authorship pattern for {r['name']}", text + " Co-authorship alone is never proof of misconduct.",
                [coauthor_ev, evidence_ids[r["id"]], *sample_ev[:6]], Severity.MEDIUM if material else Severity.LOW, material, explanations, src,
            )

    return {
        "identity_map": identity_map,
        "contributors": contributors,
        "human_contributors": len(humans),
        "authorship": authorship,
        "coauthorship": coauthor,
        "evidence": {"identity_map": identity_ev, "authorship": authorship_ev, "coauthorship": coauthor_ev, "contributors": evidence_ids, "coauthor_commits": sample_ev},
    }


def _ts(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()
