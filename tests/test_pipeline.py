"""End-to-end completion-state behaviour with a scripted provider (no model runtime needed)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from argus.cli import main
from argus.models import Category, CompletionStatus, FindingStatus, FindingType, Lifecycle, ModuleStatus, Outcome
from argus.pipeline import evaluate
from argus.report import check_written, render_markdown, validate, write_reports
from conftest import ALICE, BASE, BOB, GITIGNORE, FakeProvider, RepoBuilder, build_clean, default_reply, source, step_of

FAKE_AWS_KEY = "AKIA" + "QWERTYUIOPASDFGH"  # fixture value, not a real credential


def status_of(ev, module):
    return next(c for c in ev.coverage if c.module == module).status


def test_clean_repository_is_done_clean(clean_repo, cfg):
    ev = evaluate(str(clean_repo), cfg, FakeProvider())
    assert ev.errors == []
    assert ev.findings == []
    assert "Single human contributor" in [o.text for o in ev.observations]
    assert ev.completion_status == CompletionStatus.DONE_CLEAN
    assert ev.definition_of_done.satisfied
    assert not any(c.status == ModuleStatus.UNVERIFIABLE for c in ev.coverage)
    assert validate(ev) == []
    stats = ev.deterministic_metrics["statistics"]
    assert stats["commits"] == 6 and stats["contributors"] == 1


def test_done_clean_is_not_granted_just_because_the_model_found_nothing(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    repo.commit("Remove ignore rules", {".gitignore": None})
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS
    assert status_of(ev, "gitignore") == ModuleStatus.FAIL
    assert any(f.origin == "deterministic" and "gitignore" in f.title for f in ev.findings)


def test_committed_secret_is_flagged_and_redacted(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    repo.commit("Add deployment settings", {"inventory/settings.py": f'AWS_ACCESS_KEY_ID = "{FAKE_AWS_KEY}"\n'})
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    assert ev.completion_status == CompletionStatus.FLAGGED
    secret = [f for f in ev.findings if f.category == Category.SECRET_EXPOSURE]
    assert secret and secret[0].requires_manual_review
    md, js = write_reports(ev, Path(cfg.out_dir))
    assert FAKE_AWS_KEY not in js.read_text(encoding="utf-8") and FAKE_AWS_KEY not in md.read_text(encoding="utf-8")
    assert check_written(ev, md, js) == []


def coauthor_heavy(path) -> RepoBuilder:
    repo = build_clean(path)
    for i in range(2, 9):
        repo.commit(f"Add warehouse zone {i} allocation rules", {f"inventory/zone_{i}.py": source(i)}, coauthors=(BOB,))
    return repo


def test_unaddressed_material_anomaly_is_escalated_not_dropped(tmp_path, cfg):
    ev = evaluate(str(coauthor_heavy(tmp_path / "r").path), cfg, FakeProvider())
    anomalies = [a for a in ev.anomalies if a.category == Category.COAUTHOR_INTEGRITY]
    assert anomalies and anomalies[0].material
    escalated = [f for f in ev.findings if f.source_step == "escalation"]
    assert escalated and escalated[0].status == FindingStatus.UNVERIFIABLE and escalated[0].requires_manual_review
    assert ev.completion_status == CompletionStatus.FLAGGED
    # Co-authorship is reported as a pattern needing review, never as a verdict.
    text = render_markdown(ev).lower()
    assert "co-authorship alone is never proof" in text


def test_model_explanation_cannot_remove_a_material_review_requirement(tmp_path, cfg):
    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "authorship_analysis":
            anomaly = schema["$defs"]["AnomalyResolution"]["properties"]["anomaly_id"]["enum"][0]
            reply["resolved_anomalies"] = [{"anomaly_id": anomaly, "explanation": "Both contributors have independent commits elsewhere in the evidence packet and the trailers sit on substantial feature commits."}]
        return json.dumps(reply)

    ev = evaluate(str(coauthor_heavy(tmp_path / "r").path), cfg, FakeProvider(responder))
    anomaly = next(a for a in ev.anomalies if a.category == Category.COAUTHOR_INTEGRITY)
    assert anomaly.lifecycle != Lifecycle.RESOLVED and anomaly.proposed_by == "llm:authorship_analysis"
    finding = next(f for f in ev.findings if anomaly.id in f.evidence_ids)
    assert finding.material and finding.requires_manual_review and "advisory" in finding.llm_reasoning
    assert ev.completion_status == CompletionStatus.FLAGGED


def weak_messages(path) -> RepoBuilder:
    repo = build_clean(path)
    for i, message in enumerate(["update", "fix", "changes", "stuff", "wip", "final"]):
        repo.commit(message, {f"inventory/extra_{i}.py": source(i + 10)})
    return repo


def test_llm_candidate_with_deterministic_basis_becomes_an_engineering_weakness(tmp_path, cfg):
    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "commit_analysis":
            ids = schema["$defs"]["LLMFinding"]["properties"]["evidence_ids"]["items"]["enum"]
            quality = next(i for i in ids if i.startswith("EV-COMMIT_QUALITY"))
            reply["findings"] = [{"title": "Commit messages are hard to trace", "category": "commit_integrity", "severity": "critical", "finding": "Half of the commits use generic messages.",
                                  "reasoning": "Derived from the commit quality metrics.", "evidence_ids": [quality], "confidence": "high", "requires_manual_review": True}]
        return json.dumps(reply)

    ev = evaluate(str(weak_messages(tmp_path / "r").path), cfg, FakeProvider(responder))
    finding = next(f for f in ev.findings if f.origin == "llm")
    # Type, severity and review requirement come from the policy layer, not from the model's proposal.
    assert finding.finding_type == FindingType.ENGINEERING_WEAKNESS and finding.severity.value == "LOW"
    assert not finding.material and not finding.requires_manual_review and finding.outcome == Outcome.FAIL
    assert finding.deterministic_basis and "weak_message_ratio" in finding.deterministic_basis[0]
    assert finding.evidence and all(e.id in {x.id for x in ev.evidence} for e in finding.evidence)
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS


def test_hallucinated_evidence_is_rejected(clean_repo, cfg):
    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "commit_analysis":
            reply["findings"] = [{"title": "Invented finding", "category": "COMMIT_INTEGRITY", "severity": "HIGH", "finding": "A commit that does not exist.",
                                  "reasoning": "None.", "evidence_ids": ["EV-COMMIT-999"], "confidence": 0.9}]
        return json.dumps(reply)

    provider = FakeProvider(responder)
    ev = evaluate(str(clean_repo), cfg, provider)
    assert not any(f.title == "Invented finding" for f in ev.findings)
    assert ev.completion_status == CompletionStatus.EVALUATOR_ERROR
    assert any(e.stage == "commit_analysis" and e.kind == "LLM_STEP_FAILED" for e in ev.errors)
    assert status_of(ev, "commit_quality") == ModuleStatus.UNVERIFIABLE
    assert sum(step_of(p) == "commit_analysis" for p in provider.prompts) == 2  # one controlled retry, then failure


def test_invalid_json_fails_the_step_after_one_repair_attempt(clean_repo, cfg):
    ev = evaluate(str(clean_repo), cfg, FakeProvider(lambda s, p, schema: "I think the repository looks fine."))
    assert ev.completion_status == CompletionStatus.EVALUATOR_ERROR
    assert status_of(ev, "timeline") == ModuleStatus.UNVERIFIABLE
    assert ev.executive_summary["origin"] == "deterministic" and "EVALUATOR_ERROR" in ev.executive_summary["text"]


def test_invalid_json_is_repaired_on_retry(clean_repo, cfg):
    seen = set()

    def responder(system, prompt, schema):
        step = step_of(prompt)
        if step == "timeline_analysis" and step not in seen:
            seen.add(step)
            return '{"summary": "truncated'
        return default_reply(system, prompt, schema)

    ev = evaluate(str(clean_repo), cfg, FakeProvider(responder))
    assert ev.completion_status == CompletionStatus.DONE_CLEAN
    assert ev.llm_analyses["timeline_analysis"]["repaired"] is True


def test_model_failure_is_evaluator_error_not_pass(clean_repo, cfg):
    ev = evaluate(str(clean_repo), cfg, FakeProvider(fail=True))
    assert ev.completion_status == CompletionStatus.EVALUATOR_ERROR
    assert not ev.definition_of_done.satisfied


def test_unavailable_runtime_is_evaluator_error(clean_repo, cfg):
    ev = evaluate(str(clean_repo), cfg, FakeProvider(available=False))
    assert ev.completion_status == CompletionStatus.EVALUATOR_ERROR
    assert ev.errors[0].kind == "LLM_UNAVAILABLE"
    assert ev.deterministic_metrics["statistics"]["commits"] == 6  # deterministic evidence is still reported


def test_missing_history_is_incomplete(tmp_path, cfg):
    (tmp_path / "not-a-repo").mkdir()
    ev = evaluate(str(tmp_path / "not-a-repo"), cfg, FakeProvider())
    assert ev.completion_status == CompletionStatus.INCOMPLETE_EVALUATION
    assert status_of(ev, "repository_access") == ModuleStatus.UNVERIFIABLE
    assert ev.errors == []  # the project is unreachable; ARGUS itself did not fail
    empty = RepoBuilder(tmp_path / "empty")
    assert evaluate(str(empty.path), cfg, FakeProvider()).completion_status == CompletionStatus.INCOMPLETE_EVALUATION


def test_disabled_llm_is_incomplete_never_clean(clean_repo, cfg):
    cfg.llm_enabled = False
    ev = evaluate(str(clean_repo), cfg)
    assert ev.completion_status == CompletionStatus.INCOMPLETE_EVALUATION


def test_similarity_above_threshold_requires_review_not_a_verdict(tmp_path, cfg):
    original = build_clean(tmp_path / "original")
    copy = RepoBuilder(tmp_path / "copy")
    copy.commit("Add inventory implementation", {".gitignore": GITIGNORE, "README.md": "# Stock tool\n", "requirements.txt": "pytest\n",
                                                  "inventory/stock.py": source(0) + "\n\ndef known(levels, item):\n    return item in levels\n", "inventory/suppliers.py": source(1)})
    cfg.compare = [str(original.path)]
    ev = evaluate(str(copy.path), cfg, FakeProvider())
    sim = ev.deterministic_metrics["similarity"]
    assert sim["performed"] and sim["comparisons"][0]["similarity_estimate"] >= 0.7
    finding = next(f for f in ev.findings if f.category == Category.SIMILARITY)
    assert finding.requires_manual_review and finding.title == "SIMILARITY_THRESHOLD_EXCEEDED"
    assert "not a plagiarism verdict" in finding.reasoning
    assert ev.completion_status == CompletionStatus.FLAGGED
    assert any(h["event"] == "QA_REVIEW_REQUESTED" for h in ev.handoffs)


def test_unrelated_reference_stays_below_threshold(tmp_path, cfg, clean_repo):
    other = RepoBuilder(tmp_path / "other")
    other.commit("Add parser", {"parser.py": "import re\n\n\ndef tokens(text):\n    return [t for t in re.split(r'\\W+', text) if t]\n\n\ndef count(text):\n    seen = {}\n    for t in tokens(text):\n        seen[t] = seen.get(t, 0) + 1\n    return seen\n"})
    cfg.compare = [str(other.path)]
    ev = evaluate(str(clean_repo), cfg, FakeProvider())
    assert ev.deterministic_metrics["similarity"]["comparisons"][0]["similarity_estimate"] < 0.3
    assert status_of(ev, "similarity_analysis") == ModuleStatus.PASS


def test_required_similarity_without_reference_is_incomplete(clean_repo, cfg):
    cfg.require_similarity = True
    ev = evaluate(str(clean_repo), cfg, FakeProvider())
    assert ev.completion_status == CompletionStatus.INCOMPLETE_EVALUATION


def test_large_generated_commit_is_not_counted_as_meaningful_work(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    lock = json.dumps({"packages": {f"pkg-{i}": {"version": "1.0.0", "integrity": "x" * 40} for i in range(2500)}}, indent=1)
    repo.commit("Add frontend lockfile", {"web/package.json": '{"name": "web", "scripts": {}}\n', "web/package-lock.json": lock, "web/index.js": "console.log('ready')\n"}, author=BOB)
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    bob = next(c for c in ev.deterministic_metrics["contributors"]["contributors"] if c["name"] == "Bob Example")
    assert bob["raw_additions"] > 5000 and bob["meaningful_additions_estimate"] < 10
    # Composition is evidence, not an anomaly: lockfile-heavy LOC is explained by path classification.
    assert not [a for a in ev.anomalies if a.category == Category.LOC_INFLATION]
    assert not [f for f in ev.findings if f.category in (Category.LOC_INFLATION, Category.TIMELINE_ANOMALY)]
    assert any(o.topic == "composition" and "lockfile" in o.text for o in ev.observations)
    assert ev.completion_status != CompletionStatus.FLAGGED  # a large commit alone is not suspicious


def test_post_deadline_commit_is_surfaced(tmp_path, cfg):
    repo = build_clean(tmp_path / "r")
    cfg.deadline = (BASE + timedelta(hours=20)).isoformat()
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    assert ev.deterministic_metrics["timeline"]["commits_after_deadline"] == 2
    assert ev.completion_status == CompletionStatus.FLAGGED


def test_reports_contain_required_sections_and_agree(clean_repo, cfg):
    ev = evaluate(str(clean_repo), cfg, FakeProvider())
    md, js = write_reports(ev, Path(cfg.out_dir))
    data = json.loads(js.read_text(encoding="utf-8"))
    for key in ("repository", "evaluation_id", "model", "timestamp", "coverage", "deterministic_metrics", "findings", "evidence", "manual_review", "completion_status", "errors"):
        assert key in data
    text = md.read_text(encoding="utf-8")
    for n, heading in enumerate(["Executive Summary", "Repository Snapshot", "SCC / Codebase Composition", "Contributor Analysis"], 1):
        assert f"## {n}. {heading}" in text
    for heading in ["16. Repository Observations", "17. Engineering Weaknesses", "18. Integrity Findings", "19. Security Findings", "20. Manual Review Requirements"]:
        assert f"## {heading}" in text
    assert "## 25. Final Status" in text and "Evaluation Status: DONE_CLEAN" in text
    assert "observations" in data and "candidate_decisions" in data
    assert check_written(ev, md, js) == []


def test_packets_never_contain_the_whole_repository(clean_repo, cfg):
    provider = FakeProvider()
    evaluate(str(clean_repo), cfg, provider)
    assert provider.prompts and all(len(p) < 60_000 for p in provider.prompts)
    assert not any("def restock_0" in p for p in provider.prompts)  # source code is never sent


def test_cli_exit_codes(clean_repo, tmp_path, capsys):
    code = main(["evaluate", str(clean_repo), "--no-llm", "--out", str(tmp_path / "out"), "--quiet"])
    assert code == 4
    assert "Evaluation Status: INCOMPLETE_EVALUATION" in capsys.readouterr().out
    assert main(["evaluate", "git@github.com:owner/repo.git", "--no-llm", "--out", str(tmp_path / "out")]) == 2


def test_model_finding_anchored_in_material_anomaly_is_a_material_concern(tmp_path, cfg):
    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "authorship_analysis":
            anomaly = schema["$defs"]["AnomalyResolution"]["properties"]["anomaly_id"]["enum"][0]
            reply["findings"] = [{"title": "Co-authorship pattern needs review", "category": "COMMIT_INTEGRITY", "severity": "INFO", "finding": "Pattern cannot be explained from the packet.",
                                  "reasoning": "Pair programming and padding are both consistent.", "evidence_ids": [anomaly], "confidence": 0.6, "requires_manual_review": False}]
        return json.dumps(reply)

    ev = evaluate(str(coauthor_heavy(tmp_path / "r").path), cfg, FakeProvider(responder))
    finding = next(f for f in ev.findings if f.origin == "llm")
    # The model under-called it (INFO, no review, wrong category); the detected pattern decides.
    assert finding.finding_type == FindingType.MATERIAL_INTEGRITY_CONCERN and finding.category == Category.COAUTHOR_INTEGRITY
    assert finding.severity.value == "MEDIUM" and finding.material and finding.requires_manual_review and finding.outcome == Outcome.REVIEW
    assert len([f for f in ev.findings if f.category == Category.COAUTHOR_INTEGRITY]) == 1  # not escalated a second time
    assert ev.completion_status == CompletionStatus.FLAGGED


def test_github_workflow_records_acquisition_and_turns_api_failure_into_coverage_gap(clean_repo, cfg, monkeypatch):
    """The GitHub URL path end to end, with the network replaced: clone is redirected to a local
    fixture and the API refuses every call (as when rate-limited)."""
    import urllib.error

    import argus.pipeline as pipeline
    from argus.collectors import github as github_mod
    from argus.collectors.gitutil import RepoSource
    from argus.collectors.gitutil import clone as real_clone

    def fake_clone(source, dest, timeout=1800):
        assert source.url == "https://github.com/owner/project"  # the normalized URL is what gets cloned
        return real_clone(RepoSource(str(clean_repo), "local", None, "project", None, clean_repo), dest)

    def refuse(path, token, timeout=20):
        raise urllib.error.HTTPError(path, 403, "rate limit exceeded", {}, None)

    monkeypatch.setattr(pipeline, "clone", fake_clone)
    monkeypatch.setattr(github_mod, "_get", refuse)
    monkeypatch.setattr(github_mod.collect, "__defaults__", (refuse,))
    ev = evaluate("https://github.com/owner/project.git", cfg, FakeProvider())
    repo = ev.repository
    assert (repo["original_url"], repo["normalized_url"], repo["owner"], repo["name"]) == ("https://github.com/owner/project.git", "https://github.com/owner/project", "owner", "project")
    acq = repo["acquisition"]
    assert acq["success"] and acq["isolated_from_argus_source"] and acq["runtime_s"] >= 0 and not acq["retained_after_run"]
    assert not Path(acq["checkout_path"]).exists()  # temporary checkout is removed after the run
    gh = ev.deterministic_metrics["github"]
    assert gh["coverage"]["metadata"] == "UNVERIFIABLE" and gh["coverage"]["pull_requests"] == "UNVERIFIABLE"
    assert status_of(ev, "repository_metadata") == ModuleStatus.UNVERIFIABLE and status_of(ev, "pull_requests") == ModuleStatus.UNVERIFIABLE
    assert ev.findings == [] and ev.errors == []  # unavailable API data is a coverage gap, never a finding and never invented
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS  # optional checks unverifiable: not clean, not incomplete
    assert all(d.candidate_id.startswith("CAND-") for d in ev.candidate_decisions)
