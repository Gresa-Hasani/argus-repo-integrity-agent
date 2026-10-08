"""Focused tests for the fixes that came out of the real data-capstone run, and for the web API."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from argus.collectors import hygiene as hygiene_mod
from argus.models import Category, CompletionStatus, FindingType, Outcome
from argus.pipeline import evaluate
from argus.policy import advisory_conflicts, sanitize_advisory, summary_problems
from argus.report import validate
from conftest import BOB, FakeProvider, RepoBuilder, build_clean, default_reply, source, step_of

DBX_TOKEN = "dapi" + "0123456789abcdef" * 2  # fixture with the Databricks token shape, not a real credential


# --- 1. credential classification ------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "EMPTY"), ('""', "EMPTY"), ("   # set me", "EMPTY"),
        ("your-databricks-token-here", "PLACEHOLDER"), ("<paste token>", "PLACEHOLDER"), ("changeme", "PLACEHOLDER"),
        ("xxxxxxxxxxxx", "PLACEHOLDER"), ("dapi-your-token   # from workspace settings", "PLACEHOLDER"), ("${DATABRICKS_TOKEN}", "PLACEHOLDER"),
        (DBX_TOKEN, "SECRET_LIKE"), (f'"{DBX_TOKEN}"  # prod', "SECRET_LIKE"), ("Zx81kQ0pLm29vBn47RtYw3Hs", "SECRET_LIKE"),
        ("abc123", "UNKNOWN"), ("main", "UNKNOWN"),
    ],
)
def test_credential_value_classification(raw, expected):
    assert hygiene_mod.classify_credential_value(raw) == expected


def test_databricks_env_variables_are_recognised_and_never_stored(tmp_path):
    (tmp_path / ".env").write_text(
        f"DATABRICKS_HOST=https://adb-123.azuredatabricks.net\nDATABRICKS_TOKEN={DBX_TOKEN}\nDATABRICKS_CLIENT_SECRET=<your-secret>\nDATABRICKS_CLIENT_ID=\nGOLD_SCHEMA=gold\n",
        encoding="utf-8",
    )
    found = hygiene_mod.credential_variables(tmp_path, [".env"])
    assert {v["variable"]: v["classification"] for v in found} == {"DATABRICKS_TOKEN": "SECRET_LIKE", "DATABRICKS_CLIENT_SECRET": "PLACEHOLDER", "DATABRICKS_CLIENT_ID": "EMPTY"}
    assert DBX_TOKEN not in json.dumps(found) and all(set(v) == {"file", "line", "variable", "classification", "value_length", "is_template_file"} for v in found)


def env_repo(path, token_value) -> RepoBuilder:
    repo = build_clean(path)
    # The fixture's .gitignore excludes .env, so drop that rule to get the file tracked (as in the real repository).
    repo.commit("Add Databricks settings", {".gitignore": "__pycache__/\n*.pyc\n.venv/\nvenv/\n", ".env": f"DATABRICKS_HOST=https://example.cloud.databricks.com\nDATABRICKS_TOKEN={token_value}\n"})
    return repo


def test_secret_like_env_value_is_flagged_deterministically_and_redacted(tmp_path, cfg):
    def suppress(system, prompt, schema):  # the model insists everything is fine
        reply = json.loads(default_reply(system, prompt, schema))
        reply["summary"] = "The environment file only contains placeholders and is safe."
        return json.dumps(reply)

    ev = evaluate(str(env_repo(tmp_path / "r", DBX_TOKEN).path), cfg, FakeProvider(suppress))
    secret = [f for f in ev.findings if f.category == Category.SECRET_EXPOSURE]
    assert secret and secret[0].material and secret[0].requires_manual_review and secret[0].outcome == Outcome.REVIEW
    assert ev.completion_status == CompletionStatus.FLAGGED  # the model cannot suppress it
    assert DBX_TOKEN not in ev.model_dump_json()
    classes = ev.deterministic_metrics["hygiene"]["environment"]["credential_variable_classes"]
    assert classes == {"SECRET_LIKE": 1}


def test_placeholder_env_value_is_a_hygiene_weakness_not_a_credential_flag(tmp_path, cfg):
    ev = evaluate(str(env_repo(tmp_path / "r", "your-token-here   # personal access token").path), cfg, FakeProvider())
    assert not [f for f in ev.findings if f.category == Category.SECRET_EXPOSURE]
    env = ev.deterministic_metrics["hygiene"]["environment"]
    assert env["credential_variables"][0]["classification"] == "PLACEHOLDER"
    weakness = next(f for f in ev.findings if f.title == "Environment file committed to the repository")
    assert weakness.finding_type == FindingType.ENGINEERING_WEAKNESS and not weakness.material
    assert ev.completion_status == CompletionStatus.DONE_WITH_FINDINGS


# --- 2. isolated whitespace-only commit ------------------------------------------------------------
def whitespace_repo(path, n) -> RepoBuilder:
    repo = build_clean(path)
    body = source(0) + "\n\ndef known(levels, item):\n    return item in levels\n"
    for i in range(n):
        body = body.replace("    return item in levels", "    return item in levels" + " ", 1) if i % 2 == 0 else body.replace("levels ", "levels", 1)
        repo.commit(f"Tidy stock module formatting pass {i}", {"inventory/stock.py": body + ("\n" * (i + 1))})
    return repo


def test_one_isolated_whitespace_commit_is_an_observation_not_an_anomaly(tmp_path, cfg):
    ev = evaluate(str(whitespace_repo(tmp_path / "r", 1).path), cfg, FakeProvider())
    assert ev.deterministic_metrics["commits"]["inflation"]["whitespace_only_commits"] == 1
    assert not [a for a in ev.anomalies if a.category == Category.COMMIT_INFLATION]
    assert not [f for f in ev.findings if f.category == Category.COMMIT_INFLATION]
    assert any("isolated whitespace-only commit" in o.text for o in ev.observations)
    assert ev.completion_status == CompletionStatus.DONE_CLEAN


def test_repeated_whitespace_commits_are_still_an_anomaly_pattern(tmp_path, cfg):
    ev = evaluate(str(whitespace_repo(tmp_path / "r", 4).path), cfg, FakeProvider())
    assert ev.deterministic_metrics["commits"]["inflation"]["whitespace_only_commits"] >= 3
    assert [a for a in ev.anomalies if a.category == Category.COMMIT_INFLATION]


# --- 3. model text cannot contradict authoritative fields ------------------------------------------
NON_MATERIAL = dict(manual_review=False, material=False, severity="LOW", finding_type="ANOMALY", outcome="PASS")


@pytest.mark.parametrize(
    "text,code",
    [
        ("This pattern requires manual review.", "contradicts_manual_review"),
        ("A human review is needed here.", "contradicts_manual_review"),
        ("This is a material integrity concern.", "contradicts_material"),
        ("This is a high-severity issue.", "contradicts_severity"),
        ("It should be classified as MATERIAL_INTEGRITY_CONCERN.", "contradicts_finding_type"),
        ("The outcome should be FAIL.", "contradicts_outcome"),
        ("This suggests cheating by the contributor.", "accusatory_language"),
    ],
)
def test_advisory_conflict_codes(text, code):
    assert code in advisory_conflicts(text, **NON_MATERIAL)


def test_consistent_advisory_text_is_kept():
    text = "This could be pair programming. No manual review is needed. It is a low-severity, non-material ANOMALY with outcome PASS."
    assert advisory_conflicts(text, **NON_MATERIAL) == []
    assert advisory_conflicts("Manual review is required for this material concern.", manual_review=True, material=True, severity="MEDIUM", finding_type="MATERIAL_INTEGRITY_CONCERN", outcome="REVIEW") == []


def test_live_coauthorship_text_is_replaced_by_deterministic_statement(tmp_path, cfg):
    """The exact model sentence from the data-capstone run."""
    live = "Gresa-Hasani is a co-author on 7 commits, with 5 of these commits changing 5 lines or fewer, which may indicate a pattern that requires manual review."
    clean, removed = sanitize_advisory(live + " This could suggest either pair programming or potential attribution padding.", **NON_MATERIAL)
    assert removed == ["contradicts_manual_review"] and "requires manual review" not in clean and "pair programming" in clean

    repo = build_clean(tmp_path / "r")
    for i in range(3):
        repo.commit(f"Add allocation strategy {i}", {f"inventory/strategy_{i}.py": source(i) * 12})
    repo.commit("Fix typo in readme", {"README.md": "# Inventory service\n\nTracks stock levels. Run the unit tests with pytest.\n"}, author=BOB)

    def responder(system, prompt, schema):
        reply = json.loads(default_reply(system, prompt, schema))
        if step_of(prompt) == "contribution_analysis":
            anomaly = schema["$defs"]["AnomalyResolution"]["properties"]["anomaly_id"]["enum"][0]
            reply["findings"] = [{"title": "Critical contribution fraud", "category": "CONTRIBUTION_INTEGRITY", "severity": "HIGH", "finding": "This high-severity pattern requires manual review.",
                                  "reasoning": "One contributor wrote nearly all of the source. It requires manual review.", "evidence_ids": [anomaly], "confidence": 0.9, "requires_manual_review": True}]
        return json.dumps(reply)

    ev = evaluate(str(repo.path), cfg, FakeProvider(responder))
    f = next(x for x in ev.findings if x.category == Category.CONTRIBUTION_INTEGRITY)
    assert f.title == "Meaningful source concentrated in one contributor" and f.text_origin == "deterministic"  # title and statement come from the detector
    assert "requires manual review" not in f.finding and "requires manual review" not in f.llm_reasoning and "fraud" not in f.title
    assert f.llm_reasoning == "One contributor wrote nearly all of the source."
    assert set(f.llm_reasoning_removed) == {"contradicts_manual_review", "contradicts_severity"}
    assert not f.requires_manual_review and validate(ev) == []


def test_validator_rejects_a_finding_whose_model_text_contradicts_it(clean_repo, cfg, tmp_path):
    repo = build_clean(tmp_path / "r")
    repo.commit("Remove ignore rules", {".gitignore": None})
    ev = evaluate(str(repo.path), cfg, FakeProvider())
    ev.findings[0].llm_reasoning = "This requires manual review."
    assert any("contradicts_manual_review" in p for p in validate(ev))


# --- 4. repository name -----------------------------------------------------------------------------
def test_narrative_must_use_the_authoritative_repository_name():
    counts = {"manual_review_requirements": 0, "integrity_flags": 0, "evaluator_errors": 0, "mandatory_coverage_gaps": 0, "unverifiable": 0}
    slug = "gegedobruna/data-capstone"
    bad = summary_problems("The repository gedgedobruna/data-capstone is DONE_WITH_FINDINGS.", "DONE_WITH_FINDINGS", counts, None, slug)
    assert [p.split(":")[0] for p in bad] == ["misnamed_repository"]
    assert summary_problems("The repository gegedobruna/data-capstone is DONE_WITH_FINDINGS, with CI/CD and src/app present.", "DONE_WITH_FINDINGS", counts, None, slug) == []


# --- web API ----------------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import argus.server as server

    monkeypatch.chdir(tmp_path)
    return TestClient(server.app), server


def test_api_rejects_bad_urls_and_unknown_ids(api):
    client, _ = api
    assert client.get("/api/health").json() == {"status": "ok", "service": "argus"}
    for bad in ("git@github.com:o/r.git", "https://evil.example/o/r", "C:/Windows", "--upload-pack=x"):
        assert client.post("/api/evaluate", json={"url": bad}).status_code == 422
    assert client.get("/api/evaluate/nope").status_code == 404
    assert client.get("/api/evaluate/..%2F..%2Fsecrets/report").status_code == 404
    assert client.get("/api/evaluations").json() == []


def test_api_runs_the_real_pipeline_and_serves_validated_reports(api, clean_repo, monkeypatch):
    """URL -> API -> ARGUS pipeline -> result -> report endpoints, with only the network replaced."""
    import argus.pipeline as pipeline
    from argus.collectors import github as github_mod
    from argus.collectors.gitutil import RepoSource
    from argus.collectors.gitutil import clone as real_clone

    client, _ = api
    monkeypatch.setattr(pipeline, "clone", lambda source, dest, timeout=1800: real_clone(RepoSource(str(clean_repo), "local", None, "project", None, clean_repo), dest))
    monkeypatch.setattr(github_mod.collect, "__defaults__", (lambda path, token: [] if "?" in path or path.endswith("/releases") else {"full_name": "owner/project", "visibility": "public", "default_branch": "main"},))

    job = client.post("/api/evaluate", json={"url": "https://github.com/owner/project", "deterministic_only": True}).json()
    assert job["repository"] == "owner/project" and job["stages"][0] == "Repository acquisition"
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['job_id']}").json()
        if job["state"] != "running":
            break
        time.sleep(0.2)
    assert job["state"] == "done", job
    result = client.get(f"/api/evaluate/{job['evaluation_id']}").json()
    assert result["completion_status"] == "INCOMPLETE_EVALUATION"  # deterministic-only is never reported as clean
    assert result["repository"]["normalized_url"] == "https://github.com/owner/project" and result["deterministic_metrics"]["statistics"]["commits"] == 6
    assert "Evaluation Status: INCOMPLETE_EVALUATION" in client.get(f"/api/evaluate/{job['evaluation_id']}/report").text
    served = client.get(f"/api/evaluate/{job['evaluation_id']}/json")
    assert served.json()["evaluation_id"] == job["evaluation_id"]
    # No local filesystem paths leave the API: not the temp checkout, not the reports directory.
    assert "checkout_path" not in served.text and "checkout_path" not in json.dumps(result)
    listed = client.get("/api/evaluations").json()
    assert [row["evaluation_id"] for row in listed] == [job["evaluation_id"]] and listed[0]["status"] == "INCOMPLETE_EVALUATION"
