"""Regression tests for the live Qwen3-8B runs on a single-commit Create Next App repository.

The model proposed ordinary repository characteristics as findings (single contributor, one large
initial commit, lockfile-heavy LOC, no co-authorship, no further activity, a README "mismatch" for a
VERIFIED claim) and wrote a summary that contradicted the computed result. These tests replay those
exact candidates through the pipeline and pin the deterministic policy that rejects them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.evidence import EvidenceStore
from argus.models import Category, CompletionStatus, FindingType, LLMFinding, Outcome, Severity
from argus.pipeline import evaluate
from argus.policy import assess_candidate, deterministic_summary, numbers_in, outcome_for, reason_codes, summary_problems
from argus.report import check_written, render_markdown, validate, write_reports
from conftest import ALICE, BOB, FakeProvider, RepoBuilder, build_clean, default_reply, source, step_of

NEXT_README = "This is a [Next.js](https://nextjs.org) project bootstrapped with `create-next-app`.\n\n## Getting Started\n\nRun the development server and open the page in your browser.\n"


def scaffold_repo(path: Path) -> RepoBuilder:
    """One root commit, mostly lockfile: the shape of the repository from the live runs."""
    lock = json.dumps({"packages": {f"node_modules/pkg-{i}": {"version": "1.0.0", "resolved": f"https://registry.example/pkg-{i}.tgz", "integrity": "sha512-" + "a" * 40} for i in range(1300)}}, indent=2)
    page = "export default function Home() {\n  return (\n    <main>\n      <h1>Portfolio</h1>\n      <p>Work in progress.</p>\n    </main>\n  );\n}\n"
    repo = RepoBuilder(path)
    repo.commit(
        "Initial commit from Create Next App",
        {
            ".gitignore": "node_modules/\n.next/\n.env*\n", "README.md": NEXT_README, "AGENTS.md": "# Agent notes\n", "CLAUDE.md": "@AGENTS.md\n",
            "package.json": json.dumps({"name": "portfolio", "scripts": {"dev": "next dev", "build": "next build"}, "dependencies": {"next": "16.0.0", "react": "19.0.0"}}, indent=2),
            "package-lock.json": lock, "next.config.ts": "import type { NextConfig } from 'next';\nconst nextConfig: NextConfig = {};\nexport default nextConfig;\n",
            "tsconfig.json": "{}\n", "src/app/page.tsx": page, "src/app/layout.tsx": "import type { Metadata } from 'next';\n" + page.replace("Home", "RootLayout"),
            "src/app/globals.css": "body {\n  margin: 0;\n}\n",
        },
    )
    return repo


def first(ids: list[str], prefix: str) -> str:
    return next(i for i in ids if i.startswith(prefix))


def candidate(title, category, severity, evidence_id, review=False, text="As observed in the evidence."):
    return {"title": title, "category": category, "severity": severity, "finding": text, "reasoning": "Model reasoning.", "evidence_ids": [evidence_id], "confidence": 0.95, "requires_manual_review": review}


def noisy_model(system, prompt, schema):
    """Replays the candidates Qwen3-8B produced in the live runs, step by step."""
    reply = json.loads(default_reply(system, prompt, schema))
    if "$defs" not in (schema or {}) or "LLMFinding" not in schema["$defs"]:
        return json.dumps(reply)
    ids = schema["$defs"]["LLMFinding"]["properties"]["evidence_ids"].get("items", {}).get("enum", [])
    step = step_of(prompt)
    if step == "reconnaissance":
        reply["findings"] = [
            candidate("High proportion of non-source code", "LOC_INFLATION", "MEDIUM", first(ids, "EV-SCC"), review=True),
            candidate("Missing standard files", "REPOSITORY_HYGIENE", "LOW", first(ids, "EV-STRUCTURE"), text="The repository lacks a LICENSE file, tests, and Docker-related files."),
        ]
    elif step == "commit_analysis":
        reply["findings"] = [
            candidate("Single, Large Initial Commit", "COMMIT_INTEGRITY", "LOW", first(ids, "EV-COMMIT-")),
            candidate("No Low-Information Messages", "COMMIT_INTEGRITY", "INFO", first(ids, "EV-COMMIT_QUALITY")),
        ]
    elif step == "contribution_analysis":
        reply["findings"] = [
            candidate("LOC Inflation from Generated Content", "LOC_INFLATION", "LOW", first(ids, "EV-CONTRIBUTOR")),
            candidate("Minimal Meaningful Source Contribution", "CONTRIBUTION_INTEGRITY", "LOW", first(ids, "EV-CONTRIBUTOR")),
        ]
    elif step == "authorship_analysis":
        reply["findings"] = [
            candidate("No Co-Authorship", "COAUTHOR_INTEGRITY", "INFO", first(ids, "EV-COAUTHORSHIP"), text="No co-authorship, which is normal for a single contributor repository."),
            candidate("Single Human Contributor", "CONTRIBUTION_INTEGRITY", "INFO", first(ids, "EV-CONTRIBUTOR")),
            candidate("No Author-Committer Discrepancy", "COMMIT_INTEGRITY", "INFO", first(ids, "EV-AUTHORSHIP")),
        ]
    elif step == "timeline_analysis":
        reply["findings"] = [
            candidate("Single Commit with Large Codebase", "TIMELINE_ANOMALY", "HIGH", first(ids, "EV-COMMIT-"), review=True),
            candidate("No Activity After Initial Commit", "TIMELINE_ANOMALY", "LOW", first(ids, "EV-TIMELINE")),
            candidate("No Branches or Merges", "BRANCH_WORKFLOW", "LOW", first(ids, "EV-BRANCHES")),
            candidate("No Tests or CI Introduced", "CI_CD", "LOW", first(ids, "EV-TIMELINE")),
        ]
    elif step == "ai_assistance_signals":
        reply["findings"] = [candidate("AI-assistant config files present", "AI_ASSISTANCE", "INFO", first(ids, "EV-AI_SIGNALS"))]
    elif step == "readme_versus_implementation":
        reply["findings"] = [candidate("README_MISMATCH", "README_MISMATCH", "LOW", first(ids, "EV-README_CLAIM"), text="The README claims the project uses Next.js.")]
    elif step == "integrity_synthesis":
        reply["findings"] = [
            candidate("Single Contributor with Large Initial Commit", "CONTRIBUTION_INTEGRITY", "HIGH", first(ids, "EV-CONTRIBUTOR"), review=True),
            candidate("No Co-Authorship and No Further Activity", "TIMELINE_ANOMALY", "LOW", first(ids, "EV-TIMELINE")),
        ]
    return json.dumps(reply)


@pytest.fixture
def scaffold_eval(tmp_path, cfg):
    return evaluate(str(scaffold_repo(tmp_path / "portfolio").path), cfg, FakeProvider(noisy_model))


def decisions(ev, title):
    return next(d for d in ev.candidate_decisions if d.title == title)


# 1 ---------------------------------------------------------------------------------------------
def test_single_contributor_is_an_observation_not_a_finding(scaffold_eval):
    assert decisions(scaffold_eval, "Single Human Contributor").decision == "DISCARDED"
    assert not [f for f in scaffold_eval.findings if f.category == Category.CONTRIBUTION_INTEGRITY]
    assert "Single human contributor" in [o.text for o in scaffold_eval.observations]


# 2 ---------------------------------------------------------------------------------------------
def test_single_initial_scaffold_commit_is_not_an_integrity_finding(scaffold_eval):
    ev = scaffold_eval
    assert ev.anomalies == []  # nothing about this repository is a detected anomaly pattern
    for title in ("Single Commit with Large Codebase", "Single, Large Initial Commit", "Single Contributor with Large Initial Commit"):
        d = decisions(ev, title)
        assert d.decision == "DISCARDED" and d.finding_type == FindingType.NORMAL
    assert ev.deterministic_metrics["commits"]["granularity"]["root_commit"]["is_initial_scaffold"] is True
    assert any("project scaffold" in o.text for o in ev.observations)
    assert ev.findings == [] and not ev.manual_review["required"]
    assert ev.completion_status == CompletionStatus.DONE_CLEAN


def test_large_root_commit_in_a_longer_history_is_not_an_anomaly_when_it_is_a_scaffold(tmp_path, cfg):
    repo = RepoBuilder(tmp_path / "r")
    repo.commit("Initial commit", {".gitignore": "__pycache__/\n*.pyc\nvenv/\n.env\n", "README.md": "# Tool\n", "requirements.txt": "pytest\n", **{f"app/mod_{i}.py": source(i) * 8 for i in range(12)}})
    repo.commit("Tune reservation rule", {"app/mod_0.py": source(0) * 8 + "\nLIMIT = 3\n"})
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    largest = ev.deterministic_metrics["commits"]["granularity"]["largest_commits"]
    root = ev.deterministic_metrics["commits"]["granularity"]["root_commit"]
    assert root["meaningful_additions"] >= 1000 and root["is_initial_scaffold"]
    assert not [a for a in ev.anomalies if a.category == Category.TIMELINE_ANOMALY] and (not largest or largest[0]["is_initial_scaffold"])


def test_non_root_code_drop_is_still_detected(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    repo.commit("Add everything", {f"inventory/bulk_{i}.py": source(i) * 10 for i in range(12)}, author=BOB)
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    drop = [a for a in ev.anomalies if a.category == Category.TIMELINE_ANOMALY]
    assert drop and drop[0].material
    assert ev.completion_status == CompletionStatus.FLAGGED  # the policy is not "never flag"


# 3 ---------------------------------------------------------------------------------------------
def test_lockfile_heavy_repository_has_no_loc_integrity_finding(scaffold_eval):
    ev = scaffold_eval
    scc = ev.deterministic_metrics["scc"]
    assert scc["raw_code_loc"] > 20 * scc["meaningful_source_loc_estimate"]  # the composition is still measured and reported
    for title in ("High proportion of non-source code", "LOC Inflation from Generated Content", "Minimal Meaningful Source Contribution"):
        assert decisions(ev, title).decision == "DISCARDED"
    assert not [f for f in ev.findings if f.category == Category.LOC_INFLATION]
    assert not [a for a in ev.anomalies if a.category == Category.LOC_INFLATION]
    composition = next(o for o in ev.observations if o.topic == "composition")
    assert "lockfile" in composition.text and "meaningful source" in composition.text


# 4 ---------------------------------------------------------------------------------------------
def test_no_coauthorship_is_evidence_not_a_finding(scaffold_eval):
    ev = scaffold_eval
    d = decisions(ev, "No Co-Authorship")
    assert d.decision == "DISCARDED" and "requires a deterministically detected anomaly pattern" in d.reason
    assert not [f for f in ev.findings if f.category == Category.COAUTHOR_INTEGRITY]
    assert "Co-authorship: none detected" in [o.text for o in ev.observations]
    assert "No Co-Authorship" not in render_markdown(ev).split("## 23.")[0]  # only listed in the policy audit table


# 5 ---------------------------------------------------------------------------------------------
def test_no_activity_after_initial_commit_is_not_a_timeline_anomaly(scaffold_eval):
    ev = scaffold_eval
    for title in ("No Activity After Initial Commit", "No Co-Authorship and No Further Activity", "No Branches or Merges", "No Tests or CI Introduced"):
        assert decisions(ev, title).decision == "DISCARDED"
    assert not [f for f in ev.findings if f.category in (Category.TIMELINE_ANOMALY, Category.BRANCH_WORKFLOW, Category.CI_CD)]
    texts = " | ".join(o.text for o in ev.observations)
    assert "No deadline or expected milestone configured" in texts and "No CI workflows" in texts and "No test files" in texts and "No LICENSE file" in texts


# 6 ---------------------------------------------------------------------------------------------
def test_verified_readme_claim_rejects_readme_mismatch(scaffold_eval):
    ev = scaffold_eval
    claim = next(c for c in ev.deterministic_metrics["readme"]["claims"] if c["technology"] == "Next.js")
    assert claim["status"] == "VERIFIED"
    d = decisions(ev, "README_MISMATCH")
    assert d.decision == "DISCARDED" and "Next.js=VERIFIED" in d.reason
    assert not [f for f in ev.findings if f.category == Category.README_MISMATCH]
    assert "ARGUS-README" not in render_markdown(ev)


def test_contradicted_readme_claim_is_a_deterministic_engineering_weakness(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    repo.commit("Describe deployment", {"README.md": "# Inventory service\n\nRun the unit tests with pytest.\nThe service ships as a Docker image built in GitHub Actions.\nKubernetes support is planned.\n"})

    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "readme_versus_implementation":
            ids = schema["$defs"]["LLMFinding"]["properties"]["evidence_ids"]["items"]["enum"]
            claims = [i for i in ids if i.startswith("EV-README_CLAIM")]
            reply["findings"] = [candidate("Docker claim unsupported", "README_MISMATCH", "CRITICAL", c, review=True) for c in claims]
        return json.dumps(reply)

    ev = evaluate(str(repo.path), cfg, FakeProvider(responder))
    status = {c["technology"]: c["status"] for c in ev.deterministic_metrics["readme"]["claims"]}
    assert status["Docker"] == "CONTRADICTED" and status["GitHub Actions / CI"] == "CONTRADICTED"
    assert status["Automated tests"] == "VERIFIED" and status["Kubernetes"] == "NOT_VERIFIED"  # hedged ("planned") is not a contradiction
    mismatch = [f for f in ev.findings if f.category == Category.README_MISMATCH]
    assert len(mismatch) == 1 and mismatch[0].origin == "deterministic"  # model candidates merged, not duplicated
    assert mismatch[0].finding_type == FindingType.ENGINEERING_WEAKNESS and not mismatch[0].requires_manual_review and mismatch[0].llm_reasoning
    by_decision = {d.decision for d in ev.candidate_decisions if d.step == "readme_crosscheck"}
    assert by_decision == {"MERGED", "DISCARDED"}
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS


# 7 ---------------------------------------------------------------------------------------------
def test_non_material_findings_never_have_outcome_fail_unless_engineering_weakness(tmp_path, cfg):
    assert outcome_for(FindingType.ANOMALY, False) == Outcome.PASS
    assert outcome_for(FindingType.ENGINEERING_WEAKNESS, False) == Outcome.FAIL
    assert outcome_for(FindingType.MATERIAL_INTEGRITY_CONCERN, True) == Outcome.REVIEW

    # Non-material anomaly (two contributors, one with ~all meaningful source), cited by the model.
    repo = build_clean(tmp_path / "r")
    for i in range(3):
        repo.commit(f"Add allocation strategy {i}", {f"inventory/strategy_{i}.py": source(i) * 12})
    repo.commit("Fix typo in readme", {"README.md": "# Inventory service\n\nTracks stock levels. Run the unit tests with pytest.\n"}, author=BOB)

    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "contribution_analysis":
            anomaly = schema["$defs"]["AnomalyResolution"]["properties"]["anomaly_id"]["enum"][0]
            reply["findings"] = [candidate("Uneven contribution", "CONTRIBUTION_INTEGRITY", "HIGH", anomaly, review=True)]
        return json.dumps(reply)

    ev = evaluate(str(repo.path), cfg, FakeProvider(responder))
    finding = next(f for f in ev.findings if f.category == Category.CONTRIBUTION_INTEGRITY)
    assert finding.finding_type == FindingType.ANOMALY and finding.severity == Severity.LOW  # the detected pattern's severity, not the model's HIGH
    assert not finding.material and not finding.requires_manual_review and finding.outcome == Outcome.PASS
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS
    for f in ev.findings:
        assert f.material or f.outcome != Outcome.FAIL or f.finding_type == FindingType.ENGINEERING_WEAKNESS
    assert validate(ev) == []


# 8 ---------------------------------------------------------------------------------------------
def test_normal_observations_are_excluded_from_findings_and_counts(scaffold_eval, cfg):
    ev = scaffold_eval
    assert len(ev.candidate_decisions) == 17
    assert {d.decision for d in ev.candidate_decisions} <= {"DISCARDED", "OBSERVATION"}
    assert ev.findings == [] and ev.definition_of_done.counts["open_findings"] == 0
    assert all(f.finding_type in (FindingType.ENGINEERING_WEAKNESS, FindingType.ANOMALY, FindingType.MATERIAL_INTEGRITY_CONCERN) for f in ev.findings)
    ai = decisions(ev, "AI-assistant config files present")
    assert ai.decision == "OBSERVATION" and any(o.source == "llm" for o in ev.observations)  # explicit signal: an observation, never a finding
    md, js = write_reports(ev, Path(cfg.out_dir))
    assert validate(ev) == [] and check_written(ev, md, js) == []
    text = md.read_text(encoding="utf-8")
    for section in ("## 17. Engineering Weaknesses\n\nNone.", "## 19. Security Findings\n\nNone", "## 20. Manual Review Requirements\n\nNone."):
        assert section in text
    integrity = text.split("## 18. Integrity Findings")[1].split("## 19.")[0]
    assert "None." in integrity and "ARGUS-" not in integrity
    assert "**Manual review required:** NO" in text and "Evaluation Status: DONE_CLEAN" in text


# 9 ---------------------------------------------------------------------------------------------
def test_executive_summary_cannot_contradict_manual_review_status(tmp_path, cfg):
    live_summary = (
        "The evaluation status is DONE_CLEAN. The repository has a single contributor and a single commit. "
        "The report highlights the need for manual review due to the lack of further activity and potential concerns about the development process."
    )

    def responder(system, prompt, schema):
        if "executive_summary" in (schema or {}).get("properties", {}):
            return json.dumps({"executive_summary": live_summary})
        return noisy_model(system, prompt, schema)

    provider = FakeProvider(responder)
    ev = evaluate(str(scaffold_repo(tmp_path / "portfolio").path), cfg, provider)
    assert ev.executive_summary["llm_narrative_status"] == "REJECTED" and ev.executive_summary["llm_narrative"] == ""
    assert ev.executive_summary["narrative_rejection_reasons"] == ["contradicts_manual_review_status"]
    assert "manual review" in ev.executive_summary["llm_narrative_rejection"][0]
    assert ev.executive_summary["rejected_narrative"] == live_summary and ev.executive_summary["authoritative_summary"] == "deterministic"
    assert ev.llm_analyses["final_report"]["status"] == "REJECTED"
    assert ev.executive_summary["origin"] == "deterministic" and "No manual review is required." in ev.executive_summary["text"]
    assert ev.completion_status == CompletionStatus.DONE_CLEAN and ev.errors == []  # rejected prose does not change the computed result
    assert sum(step_of(p) == "executive_summary" for p in provider.prompts) == 2  # one repair attempt, then rejected
    md, js = write_reports(ev, Path(cfg.out_dir))
    text = md.read_text(encoding="utf-8")
    assert "highlights the need for manual review" not in text and "rejected because it contradicted the computed result (contradicts_manual_review_status)" in text
    assert check_written(ev, md, js) == []


COUNTS_CLEAN = {"manual_review_requirements": 0, "integrity_flags": 0, "evaluator_errors": 0, "mandatory_coverage_gaps": 0, "unverifiable": 0}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Status DONE_CLEAN. No manual review is required.", None),
        ("Status DONE_CLEAN. Manual review is not needed and there are no integrity flags.", None),
        ("Status DONE_CLEAN. A reviewer should manually review the history.", "manual review"),
        ("Status DONE_CLEAN. The repository was FLAGGED for review.", "mentions status FLAGGED"),
        ("Everything looks fine.", "must state the evaluation status"),
        ("Status DONE_CLEAN. Several integrity concerns were identified.", "0 integrity flags"),
        ("Status DONE_CLEAN. The evaluation hit an evaluator error.", "evaluator errors"),
        ("Status DONE_CLEAN. There are coverage gaps in the analysis.", "coverage gaps"),
        ("Status DONE_CLEAN. This looks like plagiarism.", "accusatory"),
    ],
)
def test_summary_consistency_rules(text, expected):
    problems = summary_problems(text, "DONE_CLEAN", COUNTS_CLEAN)
    assert (problems == []) if expected is None else any(expected in p for p in problems), problems


def test_summary_rules_for_flagged_and_invented_numbers():
    flagged = {**COUNTS_CLEAN, "manual_review_requirements": 2, "integrity_flags": 2}
    assert summary_problems("Status FLAGGED. No manual review is needed.", "FLAGGED", flagged)
    assert summary_problems("Status FLAGGED. Manual review is required for 2 material findings.", "FLAGGED", flagged, numbers_in({"n": 2})) == []
    problems = summary_problems("Status FLAGGED and DONE_CLEAN. Manual review is required; 74% of the code is copied.", "FLAGGED", flagged, numbers_in({"n": 2}))
    assert reason_codes(problems) == ["contradicts_authoritative_status", "unsupported_number"]
    generated = deterministic_summary("o/r", "FLAGGED", {**flagged, "engineering_weaknesses": 1, "integrity_findings": 2, "security_findings": 0}, None, ["unresolved material finding: X"])
    assert summary_problems(generated, "FLAGGED", flagged) == []


def test_report_validation_catches_a_contradictory_summary(scaffold_eval, cfg):
    ev = scaffold_eval
    ev.executive_summary["llm_narrative"] = "Status DONE_CLEAN. The report highlights the need for manual review."
    ev.executive_summary["llm_narrative_status"] = "ACCEPTED"
    assert any("manual review" in p for p in validate(ev))
    md, js = write_reports(ev, Path(cfg.out_dir))
    assert any("rendered executive summary" in p for p in check_written(ev, md, js))  # the rendered report is validated too


# 10 --------------------------------------------------------------------------------------------
def _store_with(**data):
    store = EvidenceStore()
    return store, {name: store.add(kind, "test", name, payload) for name, (kind, payload) in data.items()}


def _cand(category, evidence_ids, severity="CRITICAL", review=True):
    return LLMFinding(title="Candidate", category=category, severity=severity, finding="text", reasoning="because", evidence_ids=evidence_ids, confidence=0.99, requires_manual_review=review)


def test_llm_cannot_override_deterministic_evidence():
    store, ids = _store_with(
        verified=("readme_claim", {"technology": "Next.js", "status": "VERIFIED"}),
        unverified=("readme_claim", {"technology": "Redis", "status": "NOT_VERIFIED"}),
        contradicted=("readme_claim", {"technology": "Docker", "status": "CONTRADICTED"}),
        quality_ok=("commit_quality", {"weak_message_ratio": 0.0, "non_merge_commits": 1}),
        quality_bad=("commit_quality", {"weak_message_ratio": 0.7, "non_merge_commits": 10}),
        coauthorship=("coauthorship", {"total_coauthored_commits": 0}),
        contributor=("contributor", {"authored_commits": 1}),
        scc=("scc", {"raw_code_loc": 6971, "meaningful_source_loc_estimate": 115}),
        ai_none=("ai_signals", {"commits_attributed_to_ai_tools": 0, "commits_with_ai_tool_markers_in_message": 0, "ai_assistant_config_files": []}),
        ai_some=("ai_signals", {"commits_attributed_to_ai_tools": 4, "commits_with_ai_tool_markers_in_message": 0, "ai_assistant_config_files": []}),
        structure=("structure", {"has_tests": False}),
    )
    normal = [
        ("README_MISMATCH", "verified"), ("README_MISMATCH", "unverified"), ("COMMIT_INTEGRITY", "quality_ok"), ("COAUTHOR_INTEGRITY", "coauthorship"),
        ("CONTRIBUTION_INTEGRITY", "contributor"), ("LOC_INFLATION", "scc"), ("TIMELINE_ANOMALY", "contributor"), ("BRANCH_WORKFLOW", "structure"),
        ("COMMIT_INFLATION", "quality_ok"), ("AI_ASSISTANCE", "ai_none"), ("REPOSITORY_HYGIENE", "structure"), ("CI_CD", "structure"),
        ("SECRET_EXPOSURE", "structure"), ("SIMILARITY", "scc"), ("CODE_PROVENANCE", "scc"),
    ]
    for category, key in normal:
        d = assess_candidate(_cand(category, [ids[key]]), store, [])
        assert d.finding_type == FindingType.NORMAL and not d.material and not d.requires_manual_review, (category, key)

    weak = assess_candidate(_cand("COMMIT_INTEGRITY", [ids["quality_bad"]]), store, [])
    assert (weak.finding_type, weak.severity, weak.material, weak.outcome) == (FindingType.ENGINEERING_WEAKNESS, Severity.MEDIUM, False, Outcome.FAIL)
    readme = assess_candidate(_cand("README_MISMATCH", [ids["contradicted"], ids["verified"]]), store, [])
    assert (readme.finding_type, readme.severity, readme.requires_manual_review) == (FindingType.ENGINEERING_WEAKNESS, Severity.LOW, False)
    assert assess_candidate(_cand("AI_ASSISTANCE", [ids["ai_some"]]), store, []).finding_type == FindingType.OBSERVATION

    minor = store.add_anomaly(Category.CONTRIBUTION_INTEGRITY, "Concentration", "one contributor", [ids["contributor"]], Severity.LOW, False)
    major = store.add_anomaly(Category.COAUTHOR_INTEGRITY, "Co-author pattern", "pattern", [ids["coauthorship"]], Severity.MEDIUM, True)
    d = assess_candidate(_cand("SECRET_EXPOSURE", [minor]), store, [])  # wrong category, CRITICAL, review requested
    assert (d.finding_type, d.category, d.severity, d.material, d.requires_manual_review, d.outcome) == (FindingType.ANOMALY, Category.CONTRIBUTION_INTEGRITY, Severity.LOW, False, False, Outcome.PASS)
    d = assess_candidate(_cand("AI_ASSISTANCE", [major], severity="INFO", review=False), store, [])  # under-called by the model
    assert (d.finding_type, d.category, d.severity, d.material, d.requires_manual_review, d.outcome) == (FindingType.MATERIAL_INTEGRITY_CONCERN, Category.COAUTHOR_INTEGRITY, Severity.MEDIUM, True, True, Outcome.REVIEW)


def test_full_report_for_scaffold_repository_reads_as_observations(scaffold_eval):
    text = render_markdown(scaffold_eval)
    observations = text.split("## 16. Repository Observations")[1].split("## 17.")[0]
    for line in ("Single human contributor", "Single commit", "Co-authorship: none detected", "No CI workflows", "No test files", "Codebase composition"):
        assert line in observations
    assert "| 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |" in text  # findings are not inflated by ordinary facts
