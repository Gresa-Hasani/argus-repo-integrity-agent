"""Report rendering and validation. Markdown and JSON are produced from the same FinalEvaluation object."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from argus.models import FINDING_TYPES, Category, CompletionStatus, FinalEvaluation, Finding, FindingStatus, FindingType, Lifecycle, ModuleStatus, Outcome
from argus.policy import advisory_conflicts, summary_problems
from argus.status import MODULES, decide, open_findings


def _cell(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2%}" if 0 <= value <= 1 else f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value) or "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    rows = [list(r) for r in rows]
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def bullets(items: Iterable[str], empty: str = "_None._") -> str:
    items = [i for i in items if i]
    return "\n".join(f"- {i}" for i in items) + "\n" if items else empty + "\n"


def _finding_block(f: Finding) -> str:
    evidence = "\n".join(f"  - `{e.id}` ({e.type}): {e.summary}" for e in f.evidence[:10])
    more = f"\n  - ... {len(f.evidence) - 10} more" if len(f.evidence) > 10 else ""
    lines = [
        f"### {f.finding_id} — [{f.severity.value}] {f.title}",
        "",
        f"- **Type:** {f.finding_type.value} · category {f.category.value} · material: {'yes' if f.material else 'no'}",
        f"- **Proposed by:** {f.origin}" + (f" (step `{f.source_step}`)" if f.source_step else "") + "; accepted by the deterministic policy layer",
        f"- **Deterministic basis:** " + "; ".join(f.deterministic_basis),
        f"- **Observation:** {f.finding}",
        f"- **Evidence:**\n{evidence}{more}",
    ]
    if f.reasoning:
        lines.append(f"- **Interpretation (deterministic):** {f.reasoning}")
    if f.llm_reasoning:
        lines.append(f"- **Interpretation (model, advisory):** {f.llm_reasoning}")
    if f.llm_reasoning_removed:
        lines.append("- **Model text removed by policy:** " + ", ".join(f.llm_reasoning_removed))
    if f.possible_explanations:
        lines.append("- **Possible explanations:** " + "; ".join(f.possible_explanations))
    lines += [
        f"- **Confidence:** {f.confidence_level} ({f.confidence:.2f})",
        f"- **Manual review required:** {'YES' if f.requires_manual_review else 'no'}",
        f"- **Status:** {f.status.value} · lifecycle {f.lifecycle.value} · outcome {f.outcome.value}",
        "",
    ]
    return "\n".join(lines)


def _blocks(findings: list[Finding], empty: str = "None.") -> str:
    ordered = sorted(findings, key=lambda f: (-list(type(f.severity)).index(f.severity), f.finding_id))
    return "\n".join(_finding_block(f) for f in ordered) if ordered else empty + "\n"


def render_markdown(ev: FinalEvaluation) -> str:
    m = ev.deterministic_metrics
    repo = ev.repository
    counts = ev.definition_of_done.counts
    active = open_findings(ev.findings)
    name = f"{repo.get('owner')}/{repo.get('name')}" if repo.get("owner") else str(repo.get("name"))
    has_core = "commits" in m
    out: list[str] = []
    add = out.append

    add("# ARGUS Repository Forensics Report\n")
    add(f"**Repository:** {name}  \n**Evaluated HEAD:** `{repo.get('evaluated_head') or 'n/a'}`  \n**Model:** {ev.model.get('model') or 'none'}"
        + (f" (`{ev.model.get('runtime_model_tag')}`)" if ev.model.get("runtime_model_tag") else "")
        + (" — fallback model in use" if ev.model.get("fallback_used") else "")
        + f"  \n**Evaluation:** `{ev.evaluation_id}` at {ev.timestamp}  \n**Status:** **{ev.completion_status.value}**  \n"
        f"**Manual review required:** {'YES' if ev.manual_review['required'] else 'NO'}\n")

    add("## 1. Executive Summary\n")
    add(ev.executive_summary.get("text", "") + "\n")
    add(f"_Authoritative summary: deterministic. Model narrative: {ev.executive_summary.get('llm_narrative_status', 'NOT_PRODUCED')}._\n")
    narrative_status = ev.executive_summary.get("llm_narrative_status", "NOT_PRODUCED")
    if narrative_status == "ACCEPTED":
        add("**Model narrative** (advisory; checked for consistency with the computed result):\n\n> " + ev.executive_summary["llm_narrative"] + "\n")
    elif narrative_status == "REJECTED":
        add("_A model-written narrative was produced but rejected because it contradicted the computed result (" + ", ".join(ev.executive_summary.get("narrative_rejection_reasons", [])) + "): "
            + "; ".join(p.split(": ", 1)[-1] for p in ev.executive_summary.get("llm_narrative_rejection", [])) + ". The rejected text is kept in the JSON audit trail only._\n")
    add(f"| Open findings | Engineering weaknesses | Integrity findings | Security findings | Integrity flags (material) | Manual-review requirements | Evaluator errors | Mandatory coverage gaps |\n|---|---|---|---|---|---|---|---|\n"
        f"| {counts.get('open_findings', 0)} | {counts.get('engineering_weaknesses', 0)} | {counts.get('integrity_findings', 0)} | {counts.get('security_findings', 0)} | {counts.get('integrity_flags', 0)} | "
        f"{counts.get('manual_review_requirements', 0)} | {counts.get('evaluator_errors', 0)} | {counts.get('mandatory_coverage_gaps', 0)} |\n")

    add("## 2. Repository Snapshot\n")
    acq = repo.get("acquisition") or {}
    snapshot = [("Repository", name), ("Input", repo.get("original_url")), ("Normalized URL", repo.get("normalized_url")),
                ("Acquisition", f"{acq.get('method')} — {'succeeded' if acq.get('success') else 'FAILED'} in {acq.get('runtime_s')}s" if acq else None), ("Default branch", repo.get("default_branch")), ("Evaluated SHA", repo.get("evaluated_head")),
                ("Visibility", repo.get("visibility")), ("Created", repo.get("created_at")), ("Fork / template of", repo.get("parent") or repo.get("template"))]
    if has_core:
        s = m["statistics"]
        snapshot += [("Tracked files", s["files"]), ("Code LOC (raw)", s["raw_loc"]), ("Meaningful source LOC (estimate)", s["meaningful_loc_estimate"]),
                     ("Commits", s["commits"]), ("Human contributors", s["contributors"]), ("Branches", s["branches"]),
                     ("Languages", [l["language"] for l in m["scc"]["languages"][:6]]),
                     ("CI/CD workflows", len(m.get("ci", {}).get("workflow_files", []))),
                     ("Test files", (m.get("hygiene") or {}).get("structure", {}).get("test_files"))]
    add(table(["Field", "Value"], snapshot))

    if not has_core:
        add("_Deterministic analysis did not run; sections 3-15 have no data._\n")
    else:
        scc, commits, contrib, tl, br = m["scc"], m["commits"], m["contributors"], m["timeline"], m["branches"]
        add("## 3. SCC / Codebase Composition\n")
        add(f"Tool: **{scc['tool']}** — {scc['tool_note']}.\n")
        add(table(["Language", "Files", "Lines", "Code", "Comments", "Blanks"], [(l["language"], l["files"], l["lines"], l["code"], l["comment"], l["blank"]) for l in scc["languages"][:15]]))
        add(table(["Content class", "Files", "Code LOC"], [(k, v["files"], v["code"]) for k, v in scc["categories"].items()]))
        add(f"- raw_code_LOC: **{scc['raw_code_loc']:,}**\n- meaningful_source_LOC_estimate: **{scc['meaningful_source_loc_estimate']:,}** (source + tests; path-based estimate, not exact)\n- excluded_LOC: **{scc['excluded_loc']:,}**\n")
        add(bullets(f"{x['category']}: {x['code_loc']:,} LOC excluded — {x['reason']}" for x in scc["excluded_content"]))

        add("## 4. Contributor Analysis\n")
        add(table(["ID", "Contributor", "Kind", "Identities", "Merge basis", "Confidence"],
                  [(c["id"], c["canonical_contributor"], c["kind"], c["identities"], c["merge_basis"] or "single identity", c["confidence"]) for c in contrib["identity_map"]]))
        for c in contrib["contributors"]:
            if c["kind"] == "platform" or not c["total_commit_appearances"]:
                continue
            add(f"**{c['name']}** ({c['kind']}) — active {c['first_activity']} → {c['last_activity']} on {c['active_days']} day(s); "
                f"components: {', '.join(c['components_touched']) or 'n/a'}; languages: {', '.join(c['languages_touched']) or 'n/a'}; "
                f"tests +{c['test_additions']:,}, docs +{c['documentation_additions']:,}, config/CI +{c['configuration_additions']:,}, "
                f"generated/vendored/lock/data +{c['generated_or_vendored_additions']:,}.\n")
        add("_Commit counts and LOC are forensic signals, not measures of developer quality._\n")

        add("## 5. Commit Quality\n")
        q, g = commits["quality"], commits["granularity"]
        add(table(["Metric", "Value"], [("Commits (all refs)", commits["total"]), ("Non-merge", commits["non_merge"]), ("Merge", commits["merge"]),
                                        ("Low-information messages", f"{q['weak_message_commits']} ({q['weak_message_ratio']:.0%})"),
                                        ("Conventional-commit style", q["conventional_commit_ratio"]), ("Median lines changed", g["median_lines_changed"]),
                                        ("Large commits", g["large_commits"])]))
        add(table(["Class", "Commits"], sorted(commits["classification"].items(), key=lambda kv: -kv[1])))
        if g["largest_commits"]:
            add(table(["SHA", "Author", "Files", "+Raw", "+Meaningful", "+Non-original", "Share of meaningful", "Message"],
                      [(r["sha"], r["author"], r["files_changed"], r["additions"], r["meaningful_additions"], r["non_original_additions"], r["share_of_all_meaningful_additions"], r["message"][:60]) for r in g["largest_commits"]]))

        add("## 6. Authorship & Co-Authorship\n")
        a, co = contrib["authorship"], contrib["coauthorship"]
        add(f"Author ≠ committer on {a['author_differs_from_committer']} commit(s): {a['via_platform_or_bot_committer']} via platform/bot committers, {a['between_human_identities']} between human identities.\n")
        add(f"Co-authored commits: **{co['total_coauthored_commits']}** ({co['share_of_non_merge_commits']:.0%} of non-merge commits); malformed trailers: {co['malformed_trailers']}.\n")
        add(table(["Contributor", "Kind", "Own authored commits", "Co-authored appearances", "Total appearances", "Co-author ratio"],
                  [(r["contributor"], r["kind"], r["own_authored_commits"], r["coauthored_appearances"], r["total_appearances"], r["coauthor_ratio"]) for r in co["matrix"]]))
        add(bullets((f"{p['contributor']}: " + "; ".join(p["patterns"]) for p in co["suspicious_patterns"]), "_No unusual co-authorship pattern detected._"))

        add("## 7. Contribution Integrity\n")
        inf = commits["inflation"]
        add(table(["Indicator", "Value"], [("Empty commits", inf["empty_commits"]), ("Whitespace-only commits", inf["whitespace_only_commits"]),
                                           ("Commits changing ≤2 lines", f"{inf['tiny_commits_le_2_lines']} ({inf['tiny_commit_ratio']:.0%})"), ("Revert commits", inf["revert_commits"]),
                                           ("Trivial README-only commits", inf["trivial_readme_commits"]), ("Rapid single-file bursts", len(inf["rapid_single_file_bursts"]))]))
        ia = ev.integrity_assessment
        add(f"Anomaly patterns detected: {ia.anomalies_detected}; resolved with an evidence-grounded explanation: {ia.anomalies_resolved}; escalated unresolved: {ia.anomalies_escalated}.\n")
        if ia.summary:
            add(f"> {ia.summary}\n>\n> _Integrity synthesis by the reasoning model._\n")
        add(table(["Anomaly", "Category", "Material", "Lifecycle", "Pattern", "Resolution"],
                  [(x.id, x.category.value, "yes" if x.material else "no", x.lifecycle.value, f"{x.title}: {x.description}"[:220], (f"{x.resolution} ({x.resolved_by})" if x.resolution else (f"not resolved; advisory explanation from {x.proposed_by}" if x.proposed_explanation else "-"))) for x in ev.anomalies]))

        add("## 8. Timeline Analysis\n")
        lw = tl["late_window"]
        add(table(["Metric", "Value"], [("First commit", tl["first_commit"]), ("Last commit", tl["last_commit"]), ("Duration (hours)", tl["duration_hours"]), ("Active days", tl["active_days"]),
                                        ("Commits per active day", tl["commits_per_active_day"]), ("Deadline", tl["deadline"]), ("Commits after deadline", tl["commits_after_deadline"]),
                                        ("Late window", lw["window_basis"]), ("Meaningful additions in late window", f"{lw['meaningful_additions_in_window']:,} of {lw['total_meaningful_additions']:,}" + (f" ({lw['share']:.0%})" if lw["share"] is not None else ""))]))
        add(table(["Milestone", "Commit", "Time", "Message"], [(k, v["sha"], v["time"], v["message"]) for k, v in tl["milestones"].items() if v]))
        add(table(["Date (UTC)", "Commits", "+Raw", "+Meaningful", "Authors"], [(d["date"], d["commits"], d["additions"], d["meaningful_additions"], d["authors"]) for d in tl["per_day"][-20:]]))

        add("## 9. Branch & Collaboration Workflow\n")
        add(f"{br['workflow']}. Unmerged: {', '.join(br['unmerged_branches']) or 'none'}. Stale: {', '.join(br['stale_branches']) or 'none'}. Tags: {len(br['tags'])}.\n")
        add(table(["Branch", "Default", "Ahead", "Behind", "Merged", "Last commit", "Last author"],
                  [(b["name"], "yes" if b["is_default"] else "", b.get("ahead_of_default"), b.get("behind_default"), b.get("merged_into_default"), b["last_commit"], b["last_author"]) for b in br["branches"][:25]]))
        if br["merges"]:
            add(table(["Merge", "Author", "Source", "PR", "Files", "+", "-", "Time"], [(x["sha"], x["author"], x["source"], x["pull_request"], x["files_integrated"], x["insertions"], x["deletions"], x["time"]) for x in br["merges"][:20]]))
        gh = m.get("github", {})
        prs = gh.get("pull_requests")
        if prs:
            add(f"Pull requests: {prs['count']} ({prs['merged']} merged), authors: {', '.join(prs['authors']) or 'n/a'}.\n")
            add(table(["#", "Title", "Author", "State", "Merged", "Head → Base"], [(p["number"], p["title"][:60], p["author"], p["state"], p["merged"], f"{p['head']} → {p['base']}") for p in prs["items"][:15]]))
        elif gh.get("applicable"):
            add("Pull-request data: **unavailable** (see Unverifiable Items).\n")
        if gh.get("applicable"):
            add("GitHub API coverage (" + ("authenticated" if gh.get("authenticated") else "unauthenticated") + "): " + ", ".join(f"{k}={v}" for k, v in (gh.get("coverage") or {}).items()) + "\n")
        else:
            add("Pull-request data: not applicable (local repository).\n")

        add("## 10. GitHub Actions / CI-CD\n")
        ci = m.get("ci", {})
        if not ci.get("workflow_files"):
            add("No GitHub Actions workflows in the repository." + (f" Other CI files: {', '.join(ci['other_ci_files'])}." if ci.get("other_ci_files") else "") + "\n")
        else:
            add(table(["Workflow", "Name", "Triggers", "Jobs", "Capabilities", "Secrets referenced"],
                      [(w["file"], w.get("name"), w.get("triggers"), [j["name"] for j in w.get("jobs", [])], w.get("capabilities"), w.get("secrets_referenced")) for w in ci["workflows"]]))
            add(bullets((f"[{i['severity']}] {i['workflow']}: {i['issue']}" for i in ci["consistency_findings"]), "_Workflow commands are consistent with tracked files (static check)._"))
            runs = gh.get("workflow_runs")
            add(f"Run history: {runs['by_conclusion']} over {runs['sampled']} sampled run(s).\n" if runs else "Run history: not available — a workflow file existing is not proof that CI works.\n")

        add("## 11. Repository Hygiene\n")
        hy = m.get("hygiene")
        if hy:
            gi, env, deps = hy["gitignore"], hy["environment"], hy["dependencies"]
            add(f"- `.gitignore`: {'present' if gi['present'] else '**missing**'}; missing expected patterns: {', '.join(x['ecosystem'] for x in gi['missing_expected_patterns']) or 'none'}")
            add("- Tracked files that are normally ignored: " + ("; ".join(f"{k} ({v['count']}, e.g. `{v['examples'][0]}`)" for k, v in gi["tracked_files_that_should_be_ignored"].items()) or "none"))
            add(f"- Environment files tracked: {', '.join(env['env_files_tracked']) or 'none'}; real env files: {len(env['real_env_files_tracked'])}; removed but in history: {len(env['env_files_in_history_but_removed'])}")
            add(f"- Dependency manifests: {', '.join(deps['manifests']) or 'none'}; lockfiles: {', '.join(deps['lockfiles']) or 'none'}")
            add(bullets((i["issue"] for i in deps["issues"]), "- Dependency issues: none"))
            add("- Generated / non-original files tracked: " + (", ".join(f"{k}: {v}" for k, v in hy["generated_files"].items()) or "none") + "\n")
        else:
            add("_Hygiene collector did not complete._\n")

        add("## 12. Project Structure\n")
        if hy:
            st = hy["structure"]
            add(f"Ecosystems: {', '.join(st['ecosystems']) or 'none detected'}. README: {st['has_readme']}; LICENSE: {st['has_license']}; tests: {st['has_tests']}; Dockerfile: {st['has_dockerfile']}.\n")
            add(table(["Component", "Files"], [(c["component"], c["files"]) for c in st["components"][:15]]))
        rec = ev.llm_analyses.get("reconnaissance", {})
        if rec.get("summary"):
            add(f"> {rec['summary']}\n")

        add("## 13. README vs Implementation\n")
        rd = m.get("readme")
        if rd and rd["present"]:
            add(f"`{rd['path']}` ({rd['chars']:,} chars). {rd['method']}\n")
            add(table(["Claim (technology mentioned)", "Status", "Supporting evidence", "Evidence ID"], [(c["technology"], c["status"], c["supporting_evidence"] or "none found", c["evidence_id"]) for c in rd["claims"]]))
            rc = ev.llm_analyses.get("readme_crosscheck", {})
            if rc.get("summary"):
                add(f"> {rc['summary']}\n")
        else:
            add("No README present.\n")

        add("## 14. Code Provenance & Similarity\n")
        sim = m["similarity"]
        add(f"Threshold for manual review: **{sim['threshold']:.0%}**. Method: {sim['method']}\n")
        if sim["comparisons"]:
            add(table(["Reference", "Similarity estimate", "Files compared", "Files ≥ threshold", "Threshold exceeded", "Error"],
                      [(c["comparison_source"], c.get("similarity_estimate"), c.get("files_compared"), c.get("files_at_or_above_threshold"), c.get("threshold_exceeded"), c.get("error", "")) for c in sim["comparisons"]]))
            for c in sim["comparisons"]:
                if c.get("top_files"):
                    add(table(["File", "Containment", "Best match in reference"], [(f["file"], f["containment"], f["best_match"]) for f in c["top_files"][:8]]))
        else:
            add(f"No comparison performed: {sim.get('note', 'n/a')}. Provenance is therefore **not verified** by similarity evidence.\n")
        pv = ev.llm_analyses.get("provenance_analysis", {})
        if pv.get("summary"):
            add(f"> {pv['summary']}\n")

        add("## 15. AI-Assistance Signals\n")
        ai = m.get("ai_signals")
        if ai:
            add(f"Classification: **{ai.get('classification') or 'not classified'}** (observable evidence only; never an estimate of how much code was generated).\n")
            add(table(["Signal", "Value"], [("AI-tool identities in history", [f"{i['name']} ({i['authored_commits']} authored, {i['coauthored_commits']} co-authored)" for i in ai["ai_tool_identities_in_history"]]),
                                            ("Commits with explicit AI attribution", ai["commits_attributed_to_ai_tools"]), ("Commits with AI-tool markers in message", ai["commits_with_ai_tool_markers_in_message"]),
                                            ("AI-assistant config files", ai["ai_assistant_config_files"]), ("Placeholder markers in source", ai["placeholder_markers"]["total"]), ("Comment ratio", ai["comment_ratio"])]))
            add(f"_{ai['note']}_\n")

    weaknesses = [f for f in active if f.finding_type == FindingType.ENGINEERING_WEAKNESS]
    security = [f for f in ev.findings if f.category == Category.SECRET_EXPOSURE]
    integrity = [f for f in active if f.finding_type in (FindingType.ANOMALY, FindingType.MATERIAL_INTEGRITY_CONCERN) and f.category != Category.SECRET_EXPOSURE]

    add("## 16. Repository Observations\n")
    add("_Plain facts about the repository. These are not findings and do not affect the status._\n")
    add(bullets(o.text + (" _(noted by the model)_" if o.source == "llm" else "") + (f" [{', '.join(o.evidence_ids[:3])}]" if o.evidence_ids else "") for o in ev.observations))

    add("## 17. Engineering Weaknesses\n")
    add(_blocks(weaknesses))
    add("## 18. Integrity Findings\n")
    add("_Anomalies and material integrity concerns. Each one is anchored in a deterministically detected pattern; none is a verdict._\n")
    add(_blocks(integrity))
    add("## 19. Security Findings\n")
    add(_blocks(security, "None (static secret-pattern scan of tracked files at HEAD)."))
    add("## 20. Manual Review Requirements\n")
    add(bullets((f"{r['finding_id']} ({r['category']}): {r['reason']}" for r in ev.manual_review["requirements"]), "None."))

    add("## 21. Contributor Evidence Matrix\n")
    if has_core:
        flags: dict[str, list[str]] = {}
        for f in active:
            if not f.is_material:
                continue
            for e in f.evidence:
                if e.type == "contributor":
                    flags.setdefault(e.data.get("id"), []).append(f.finding_id)
        add(table(["Contributor", "Authored commits", "Co-authored appearances", "Meaningful commits", "Raw LOC (+/-)", "Meaningful LOC estimate (+)", "Active days", "Components", "Integrity flags"],
                  [(c["name"], c["authored_commits"], c["coauthored_commits"], sum(n for k, n in c["commit_classes"].items() if k in {"FEATURE", "BUG_FIX", "REFACTOR", "TEST"}),
                    f"+{c['raw_additions']:,} / -{c['raw_deletions']:,}", c["meaningful_additions_estimate"], c["active_days"], c["components_touched"][:5], sorted(set(flags.get(c["id"], []))) or "none")
                   for c in m["contributors"]["contributors"] if c["kind"] != "platform" and c["total_commit_appearances"]]))
        add("_Not ranked. \"Meaningful commits\" counts commits classified FEATURE, BUG_FIX, REFACTOR or TEST._\n")

    add("## 22. Healthy Engineering Signals\n")
    add(bullets(m.get("healthy_signals", [])))

    add("## 23. Unverifiable Items, Errors and Policy Decisions\n")
    add(bullets(ev.unverifiable_items, "No unverifiable items."))
    if ev.errors:
        add("**Evaluator errors (ARGUS failures, not project failures):**\n")
        add(bullets(f"{e.stage} — {e.kind}: {e.message}" for e in ev.errors))
    if ev.handoffs:
        add("**Cross-agent handoffs:**\n")
        add(bullets(f"{h['event']} → {h['to']}" + (f" ({h.get('requirement')}: {h.get('status')})" if h.get("requirement") else "") for h in ev.handoffs))
    if ev.candidate_decisions:
        add("**Model candidates and what the deterministic policy did with them:**\n")
        add(table(["ID", "Step", "Candidate", "Proposed", "Decision", "Type", "Reason"],
                  [(d.candidate_id, d.step, d.title[:60], f"{d.proposed_category} / {d.proposed_severity}" + (" / review" if d.proposed_manual_review else ""), d.decision + (f" → {d.finding_id}" if d.finding_id else ""), d.finding_type.value, d.reason[:200]) for d in ev.candidate_decisions]))

    add("## 24. Definition of Done\n")
    add(table(["Module", "Status", "Mandatory", "Detail"], [(c.module, c.status.value, "yes" if c.mandatory else "no", c.detail) for c in ev.coverage]))
    add(bullets(ev.definition_of_done.reasons, "_No blocking reasons._"))

    add("## 25. Final Status\n")
    add("```text\n" + final_block(ev) + "\n```\n")
    return "\n".join(out)


def final_block(ev: FinalEvaluation) -> str:
    c = ev.definition_of_done.counts
    repo = ev.repository
    name = f"{repo.get('owner')}/{repo.get('name')}" if repo.get("owner") else str(repo.get("name"))
    return "\n".join(
        [
            "ARGUS EVALUATION COMPLETE", "", f"Repository: {name}", f"Evaluated HEAD: {repo.get('evaluated_head') or 'n/a'}",
            f"Model: {ev.model.get('model') or 'none'}", "",
            f"Required checks: {c['required_checks']}", f"Completed checks: {c['completed_checks']}", f"Not applicable: {c['not_applicable']}",
            f"Unverifiable: {c['unverifiable']}", f"Failed checks: {c['failed_checks']}", "",
            f"Engineering weaknesses: {c['engineering_weaknesses']}", f"Integrity findings: {c['integrity_findings']}", f"Security findings: {c['security_findings']}",
            f"Critical findings: {c['critical_findings']}", f"High findings: {c['high_findings']}", f"Integrity flags: {c['integrity_flags']}",
            f"Manual-review requirements: {c['manual_review_requirements']}", f"Evaluator errors: {c['evaluator_errors']}", "",
            f"Evaluation Status: {ev.completion_status.value}",
            f"Definition of Done: {'SATISFIED' if ev.definition_of_done.satisfied else 'NOT_SATISFIED'}",
        ]
    )


def validate(ev: FinalEvaluation) -> list[str]:
    """Internal consistency checks run before a report is trusted. Returns a list of problems."""
    problems = []
    evidence_ids = {e.id for e in ev.evidence}
    modules = {c.module for c in ev.coverage}
    problems += [f"module missing from coverage: {m}" for m in MODULES if m not in modules]
    for f in ev.findings:
        if not f.evidence:
            problems.append(f"{f.finding_id} has no evidence")
        problems += [f"{f.finding_id} cites evidence not present in the report: {e.id}" for e in f.evidence if e.id not in evidence_ids]
        if f.evidence_ids != [e.id for e in f.evidence]:
            problems.append(f"{f.finding_id}: evidence_ids disagree with embedded evidence")
        if f.finding_type not in FINDING_TYPES:
            problems.append(f"{f.finding_id}: {f.finding_type.value} is not a finding type; normal facts and observations must not be in findings")
        if not f.deterministic_basis:
            problems.append(f"{f.finding_id} has no deterministic basis")
        if f.material != (f.finding_type == FindingType.MATERIAL_INTEGRITY_CONCERN):
            problems.append(f"{f.finding_id}: material={f.material} is inconsistent with type {f.finding_type.value}")
        if f.requires_manual_review != f.material:
            problems.append(f"{f.finding_id}: manual review must be required exactly for material findings")
        if not f.material and f.outcome == Outcome.FAIL and f.finding_type != FindingType.ENGINEERING_WEAKNESS:
            problems.append(f"{f.finding_id}: non-material {f.finding_type.value} cannot have outcome FAIL")
        if f.severity.value == "INFO":
            problems.append(f"{f.finding_id}: INFO-level facts are observations, not findings")
        conflicts = advisory_conflicts(
            f.llm_reasoning, manual_review=f.requires_manual_review, material=f.material, severity=f.severity.value,
            finding_type=f.finding_type.value, outcome=f.outcome.value,
        )
        if conflicts:
            problems.append(f"{f.finding_id}: model reasoning contradicts authoritative fields ({', '.join(conflicts)})")
    slug = f"{ev.repository.get('owner')}/{ev.repository.get('name')}" if ev.repository.get("owner") else None
    for text in (ev.executive_summary.get("text", ""), ev.executive_summary.get("llm_narrative", "")):
        if text:
            problems += [f"executive summary {p}" for p in summary_problems(text, ev.completion_status.value, ev.definition_of_done.counts, None, slug)]
    for a in ev.anomalies:
        if a.material and a.lifecycle in (Lifecycle.OBSERVED, Lifecycle.CORROBORATED):
            problems.append(f"material anomaly {a.id} is neither resolved nor assessed")
        if a.lifecycle == Lifecycle.RESOLVED and not a.resolution:
            problems.append(f"anomaly {a.id} resolved without an explanation")
    status, dod = decide(ev.coverage, ev.findings, ev.errors)
    if status != ev.completion_status:
        problems.append(f"completion status {ev.completion_status.value} disagrees with recomputed {status.value}")
    if dod.counts != ev.definition_of_done.counts:
        problems.append("definition-of-done counts disagree with recomputed counts")
    manual = {f.finding_id for f in open_findings(ev.findings) if f.requires_manual_review}
    if manual != {r["finding_id"] for r in ev.manual_review["requirements"]} or ev.manual_review["required"] != bool(manual):
        problems.append("manual-review list disagrees with findings")
    if ev.completion_status == CompletionStatus.DONE_CLEAN:
        if any(c.status == ModuleStatus.UNVERIFIABLE for c in ev.coverage):
            problems.append("DONE_CLEAN with an unverifiable module")
        if ev.errors or manual or any(f.is_material for f in ev.findings if f.status == FindingStatus.OPEN):
            problems.append("DONE_CLEAN with errors, manual review or material findings")
    return problems


def write_reports(ev: FinalEvaluation, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    repo = ev.repository
    stem = "-".join(str(x) for x in (repo.get("owner"), repo.get("name")) if x) or "repository"
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)
    json_path = out_dir / f"{stem}.{ev.evaluation_id}.json"
    md_path = out_dir / f"{stem}.{ev.evaluation_id}.md"
    json_path.write_text(json.dumps(ev.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(ev), encoding="utf-8")
    return md_path, json_path


def check_written(ev: FinalEvaluation, md_path: Path, json_path: Path) -> list[str]:
    """The two outputs must agree with each other and with the in-memory evaluation."""
    problems = []
    loaded = FinalEvaluation.model_validate(json.loads(json_path.read_text(encoding="utf-8")))
    md = md_path.read_text(encoding="utf-8")
    if loaded.completion_status != ev.completion_status:
        problems.append("JSON completion status differs from the evaluation")
    if f"Evaluation Status: {loaded.completion_status.value}" not in md:
        problems.append("Markdown final status differs from JSON")
    problems += [f"finding {f.finding_id} missing from Markdown" for f in loaded.findings if f.finding_id not in md]
    expected = "YES" if loaded.manual_review["required"] else "NO"
    if f"**Manual review required:** {expected}" not in md:
        problems.append("Markdown header disagrees with JSON on manual review")
    # Validate the summary as rendered, not only the object it came from.
    start, end = md.find("## 1. Executive Summary"), md.find("## 2. Repository Snapshot")
    rendered = md[start:end].split("| Open findings |")[0]
    rendered = "\n".join(line for line in rendered.splitlines() if not line.startswith("_A model-written narrative was produced but rejected"))
    problems += [f"rendered executive summary {p}" for p in summary_problems(rendered, loaded.completion_status.value, loaded.definition_of_done.counts)]
    return problems
