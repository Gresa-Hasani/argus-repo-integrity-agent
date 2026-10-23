"""Task profiling, task identity and task-based cross-validation tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import argus.server as server
from argus.config import Config, load_config
from argus.models import RepositoryProfile, RequirementStatus
from argus.pipeline import evaluate
from argus.profiling import RepositoryProfiler
from argus.report import check_written, render_markdown, write_reports
from argus.task_validation import ScoringConfig, absolute_criteria, cross_validate_tasks, evaluate_repository_task
from argus.tasks import TaskCatalog, TaskDefinition, assign_task, group_tasks, task_similarity
from conftest import RepoBuilder, build_clean

GENERATED = "2026-01-01T00:00:00+00:00"


def task_repo(path: Path) -> Path:
    repo = RepoBuilder(path)
    repo.commit(
        "Add inventory service with HTTP endpoint",
        {
            "README.md": "# Inventory service\n\nA FastAPI inventory API with stock reservation and automated tests. Kubernetes deployment is planned.\n",
            "docs/kubernetes.md": "# Deployment\n\nKubernetes deployment is planned for a later release. No manifest is provided yet.\n",
            "requirements.txt": "fastapi>=0.110\npytest>=8\n",
            "app/main.py": (
                "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
                "@app.get('/stock')\ndef list_stock():\n    return {'stock': []}\n\n"
                "def reserve_stock(levels, item, quantity):\n"
                "    levels[item] = levels.get(item, 0) - quantity\n    return levels[item]\n"
            ),
            "app/models.py": "class Reservation:\n    def __init__(self, item, quantity):\n        self.item = item\n        self.quantity = quantity\n",
            "tests/test_stock.py": "from app.main import reserve_stock\n\n\ndef test_reserve_stock():\n    assert reserve_stock({'item': 2}, 'item', 1) == 1\n",
        },
    )
    return repo.path


def section(score: float = 0.5) -> dict:
    return {
        "score": score,
        "confidence": 0.8,
        "components": [{"id": "indicator", "normalized": score, "weight": 1.0}],
        "limitations": [],
    }


def profile(name: str, code: tuple[str, ...] = (), docs: tuple[str, ...] = (), score: float = 0.5) -> RepositoryProfile:
    return RepositoryProfile(
        repository=name,
        generated_at=GENERATED,
        evidence_index={
            "code_terms": list(code),
            "documentation_terms": list(docs),
            "token_files": {term: ["src/example.py"] for term in code},
            "symbols": [],
            "routes": [],
        },
        quality=section(score),
        testing=section(score),
        architecture=section(score),
    )


def test_profile_uses_source_structure_not_only_readme(tmp_path):
    repo = task_repo(tmp_path / "repo")
    result = RepositoryProfiler().build(repo)

    assert result.repository == "repo"
    assert any(row["language"] == "Python" for row in result.languages)
    assert "fastapi" in result.dependencies["runtime"]
    assert result.structure["source_files"] >= 1 and result.structure["test_files"] >= 1
    assert result.documentation["readme_present"] is True
    assert result.testing["test_files"] >= 1 and result.testing["score"] is not None
    assert result.quality["score"] is not None
    assert "HTTP API" in result.architecture["patterns"]
    assert any(feature["kind"] == "http_endpoint" for feature in result.features)
    assert result.evidence_fingerprint
    assert "tracked file inventory" in result.evidence_sources


def test_dependency_scopes_and_monorepo_pattern_are_static_but_accurate(tmp_path):
    repo = RepoBuilder(tmp_path / "mono")
    repo.commit(
        "Add multi-package build files",
        {
            "build.gradle": (
                "dependencies {\n"
                "  implementation 'com.example:core:1.0'\n"
                "  testImplementation 'org.junit:junit:5.0'\n"
                "  implementation 'com.example:web:2.0'\n"
                "}\n"
            ),
            "packages/a/package.json": '{"name":"a"}\n',
            "packages/b/package.json": '{"name":"b"}\n',
            "packages/a/src/index.js": "export function a() { return 1; }\n",
            "packages/b/src/index.js": "export function b() { return 2; }\n",
        },
    )
    result = RepositoryProfiler().build(repo.path)
    assert {"core", "web"} <= set(result.dependencies["runtime"])
    assert "junit" in result.dependencies["development"]
    assert "monorepo with multiple packages" in result.architecture["patterns"]


def test_requirement_coverage_never_accepts_readme_claims(tmp_path):
    repo = task_repo(tmp_path / "repo")
    task = TaskDefinition(
        id="inventory",
        description="Build an inventory API with stock reservation and Kubernetes deployment",
        requirements=["stock reservation", "Kubernetes deployment"],
    )
    assessed = RepositoryProfiler.assess_task(RepositoryProfiler().build(repo), task)
    by_requirement = {item.requirement: item for item in assessed.task_coverage}

    stock = by_requirement["stock reservation"]
    assert stock.status in {RequirementStatus.COVERED, RequirementStatus.PARTIAL}
    assert stock.evidence
    deployment = by_requirement["Kubernetes deployment"]
    assert deployment.status == RequirementStatus.UNVERIFIED
    assert deployment.evidence == []
    assert "Documentation alone is not coverage" in deployment.explanation
    assert any("documentation-only" in item.lower() for item in assessed.limitations)


def test_profile_handles_missing_readme_empty_source_and_inaccessible_path(tmp_path):
    repo = RepoBuilder(tmp_path / "bare")
    repo.commit("Add a plain data file", {"data/notes.txt": "no source code here\n"})
    result = RepositoryProfiler().build(repo.path)
    assert result.documentation["readme_present"] is False
    assert result.structure["source_files"] == 0
    assert result.quality["score"] is None
    assert any("No README" in item for item in result.limitations)
    assert any("No recognised source files" in item for item in result.limitations)

    with pytest.raises(FileNotFoundError):
        RepositoryProfiler().build(tmp_path / "does-not-exist")


def test_profile_is_reproducible_apart_from_timestamp(tmp_path):
    repo = task_repo(tmp_path / "repo")
    first = RepositoryProfiler().build(repo)
    second = RepositoryProfiler().build(repo)
    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})


def test_task_similarity_and_grouping_are_content_based():
    a = TaskDefinition(
        id="a", description="Build an inventory REST API with stock reservation and automated tests",
        requirements=["stock reservation endpoint", "automated tests"],
    )
    b = TaskDefinition(
        id="b", description="Build an inventory REST API with stock reservation and unit tests",
        requirements=["stock reservation API", "automated test suite"],
    )
    c = TaskDefinition(
        id="c", description="Train an image segmentation model on labelled photographs",
        requirements=["image segmentation", "model evaluation"],
    )
    assert task_similarity(a, b)["score"] > 0.70
    assert task_similarity(a, c)["score"] < 0.30
    groups = group_tasks([a, b, c])
    assert [group.task_ids for group in groups] == [["a", "b"], ["c"]]
    assert "No repository name, language or framework" in task_similarity(a, b)["method"]


def test_explicit_assignment_wins_and_short_names_do_not_collide():
    first = TaskDefinition(id="first", description="Build an inventory API with stock reservation")
    second = TaskDefinition(id="second", description="Train an image segmentation model on photographs")
    catalog = TaskCatalog(
        [first, second],
        {"https://github.com/ownerA/app": "first", "ownerB/app": "second"},
    )
    assert catalog.assignment_for("ownerA/app")[0].id == "first"
    assert catalog.assignment_for("ownerB/app")[0].id == "second"
    assert catalog.assignment_for("app") is None

    evaluated = assign_task(profile("ownerB/app", ("image", "segment", "model")), catalog)
    assert evaluated is not None
    assert evaluated.task_id == "second"
    assert evaluated.relation == "EXPLICIT"

    single = TaskCatalog([first])
    applied = assign_task(profile("any/repository", ("stock", "reserv")), single)
    assert applied is not None and applied.task_id == "first"
    assert applied.relation == "EXPLICIT" and "single configured task" in applied.method


def test_relative_scoring_uses_only_task_relevant_peers_and_keeps_absolute_primary():
    inventory = TaskDefinition(
        id="inventory", description="Build an inventory REST API with stock reservation",
        requirements=["stock reservation endpoint"],
    )
    vision = TaskDefinition(
        id="vision", description="Train an image segmentation model on labelled photographs",
        requirements=["image segmentation model"],
    )
    catalog = TaskCatalog(
        [inventory, vision],
        {"a": "inventory", "b": "inventory", "c": "vision", "d": "inventory"},
    )
    profiles = [
        profile("a", ("stock", "reserv", "endpoint"), score=0.8),
        profile("b", ("stock", "reserv"), score=0.6),
        profile("c", ("image", "segment", "model"), score=0.7),
        profile("d", ("stock", "reserv", "endpoint"), score=0.9),
    ]
    scoring = ScoringConfig(peer_context_weight=0.15, minimum_peers=2)
    result = cross_validate_tasks(profiles, catalog, scoring=scoring)
    by_repository = {evaluation.repository: evaluation for evaluation in result.evaluations}

    target = by_repository["a"]
    assert target.status == "COMPARED"
    assert {peer.repository for peer in target.comparable_repositories} == {"b", "d"}
    assert [peer.repository for peer in target.excluded_repositories] == ["c"]
    assert target.absolute_score is not None and target.relative_score is not None and target.final_score is not None
    assert target.final_score == round(target.absolute_score * 0.85 + target.relative_score * 0.15, 2)

    vision_result = by_repository["c"]
    assert vision_result.status == "ABSOLUTE_ONLY"
    assert vision_result.relative_score is None and vision_result.final_score == vision_result.absolute_score
    assert {peer.repository for peer in vision_result.excluded_repositories} == {"a", "b", "d"}


def test_insufficient_peers_and_duplicate_profiles_are_reported():
    task = TaskDefinition(id="inventory", description="Build an inventory API with stock reservation", requirements=["stock reservation"])
    catalog = TaskCatalog([task], {"a": "inventory", "c": "inventory"})
    profiles = [
        profile("a", ("stock", "reserv"), score=0.8),
        profile("a", ("stock", "reserv"), score=0.8),
        profile("c", ("stock", "reserv"), score=0.6),
    ]
    result = cross_validate_tasks(profiles, catalog, scoring=ScoringConfig(minimum_peers=2))
    first = result.evaluations[0]
    third = result.evaluations[2]
    assert first.status == "INSUFFICIENT_PEERS" and first.final_score == first.absolute_score
    assert third.status == "INSUFFICIENT_PEERS"
    duplicate = next(row for row in first.excluded_repositories if row.repository == "a")
    assert duplicate.duplicate is True and duplicate.comparable is False
    assert {row.repository for row in third.comparable_repositories} == {"a"}
    assert any(row.duplicate for row in third.excluded_repositories)


def test_task_evaluation_without_established_identity_does_not_compare():
    task = TaskDefinition(id="inventory", description="Build an inventory API with stock reservation", requirements=["stock reservation"])
    other = TaskDefinition(id="vision", description="Train an image segmentation model on labelled photographs")
    uncertain = assign_task(profile("mystery", ("image", "segment")), TaskCatalog([task, other]), threshold=0.99)
    assert uncertain is not None and uncertain.relation in {"UNCERTAIN", "UNRELATED"}
    result = evaluate_repository_task(profile("mystery"), uncertain)
    assert result.status == "TASK_NOT_ESTABLISHED"
    assert result.absolute_score is None and result.final_score is None
    assert result.comparable_repositories == []


def test_task_and_scoring_configuration_layers(tmp_path):
    config = tmp_path / "argus.toml"
    config.write_text(
        "[task]\n"
        'id = "inventory"\n'
        'description = "Build an inventory API with stock reservation"\n'
        'requirements = ["stock reservation", "audit log"]\n'
        "[task.assignments]\n"
        '"owner/repo" = "inventory"\n'
        "[scoring]\n"
        "peer_context_weight = 0.2\n"
        "peer_minimum = 3\n"
        "[scoring.weights]\n"
        "task_requirement_fulfillment = 0.5\n"
        "testing_quality = 0.1\n",
        encoding="utf-8",
    )
    cfg = load_config(
        str(config),
        env={
            "ARGUS_TASK_REQUIREMENTS": '["stock reservation", "audit log", "health endpoint"]',
            "ARGUS_SCORING_WEIGHTS": '{"architecture_implementation": 0.2}',
            "ARGUS_PEER_MINIMUM": "4",
        },
    )
    assert cfg.task_id == "inventory"
    assert cfg.task_requirements == ["stock reservation", "audit log", "health endpoint"]
    assert cfg.task_assignments == {"owner/repo": "inventory"}
    assert cfg.scoring_weights["task_requirement_fulfillment"] == 0.5
    assert cfg.scoring_weights["architecture_implementation"] == 0.2
    assert cfg.peer_context_weight == 0.2 and cfg.peer_minimum == 4
    public = cfg.public_dict()
    assert public["task"]["requirements"] == cfg.task_requirements
    assert public["scoring"]["peer_minimum"] == 4
    assert "GITHUB_TOKEN" not in json.dumps(public)


def test_scoring_configuration_rejects_invalid_criteria():
    with pytest.raises(ValueError):
        ScoringConfig(weights={"unknown": 1.0})
    with pytest.raises(ValueError):
        ScoringConfig(peer_context_weight=0.9)
    with pytest.raises(ValueError):
        ScoringConfig(weights={"testing_quality": -1})
    with pytest.raises(ValueError):
        ScoringConfig(minimum_peers=-1)


def test_partial_scoring_weights_leave_other_criteria_unweighted():
    criteria = absolute_criteria(profile("a"), ScoringConfig(weights={"testing_quality": 1.0}))
    assert [item.id for item in criteria] == [
        "task_requirement_fulfillment", "functional_completeness", "code_quality_maintainability",
        "testing_quality", "architecture_implementation",
    ]
    assert [item.weight for item in criteria] == [0.0, 0.0, 0.0, 1.0, 0.0]
    assert criteria[3].score is not None


def test_pipeline_adds_profile_and_absolute_task_without_changing_status(clean_repo, tmp_path):
    cfg = Config(
        out_dir=str(tmp_path / "reports"), llm_enabled=False,
        task_description="Build an inventory API with stock reservation",
        task_requirements=["stock reservation", "automated tests"],
    )
    result = evaluate(str(clean_repo), cfg)
    plain = evaluate(str(clean_repo), Config(out_dir=str(tmp_path / "plain"), llm_enabled=False))

    assert result.repository_profile is not None
    assert result.task_evaluation is not None
    assert result.task_evaluation.status == "ABSOLUTE_ONLY"
    assert result.task_evaluation.final_score == result.task_evaluation.absolute_score
    assert result.repository_profile.task_coverage
    assert result.completion_status == plain.completion_status
    assert result.profiling_error is None

    md, js = write_reports(result, Path(cfg.out_dir))
    text = md.read_text(encoding="utf-8")
    assert "## 26. Repository Profile and Task-Based Cross-Validation" in text
    assert "Absolute task-based score" in text
    assert check_written(result, md, js) == []
    loaded = json.loads(js.read_text(encoding="utf-8"))
    assert loaded["repository_profile"]["repository"] == result.repository_profile.repository
    assert loaded["task_evaluation"]["task"]["task_id"] == result.task_evaluation.task.task_id


def test_cli_task_file_parses_json_and_toml_payloads(tmp_path):
    from argus.cli import _task_file_overrides

    payload = {
        "task": {
            "id": "inventory",
            "description": "Build an inventory API with stock reservation",
            "requirements": ["stock reservation"],
            "assignments": {"owner/repo": "inventory"},
            "relevance_threshold": 0.7,
        },
        "scoring": {"weights": {"testing_quality": 0.2}, "peer_minimum": 3},
    }
    json_file = tmp_path / "tasks.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")
    parsed = _task_file_overrides(str(json_file))
    assert parsed["task_id"] == "inventory"
    assert parsed["task_requirements"] == ["stock reservation"]
    assert parsed["task_assignments"] == {"owner/repo": "inventory"}
    assert parsed["task_relevance_threshold"] == 0.7
    assert parsed["scoring_weights"] == {"testing_quality": 0.2}
    assert parsed["peer_minimum"] == 3

    toml_file = tmp_path / "tasks.toml"
    toml_file.write_text(
        "[task]\n"
        'id = "vision"\n'
        'description = "Train an image segmentation model"\n'
        'requirements = ["image segmentation"]\n'
        "[task.assignments]\n"
        '"owner/vision" = "vision"\n'
        "[scoring]\n"
        "peer_context_weight = 0.1\n"
        "[scoring.weights]\n"
        "architecture_implementation = 0.25\n",
        encoding="utf-8",
    )
    parsed = _task_file_overrides(str(toml_file))
    assert parsed["task_id"] == "vision"
    assert parsed["task_assignments"] == {"owner/vision": "vision"}
    assert parsed["peer_context_weight"] == 0.1
    assert parsed["scoring_weights"] == {"architecture_implementation": 0.25}


def test_cli_accepts_task_options_and_writes_section_26(clean_repo, tmp_path, capsys):
    from argus.cli import main

    out = tmp_path / "out"
    code = main([
        "evaluate", str(clean_repo), "--no-llm", "--quiet", "--out", str(out),
        "--task", "Build an inventory API with stock reservation",
        "--task-requirement", "stock reservation",
        "--task-id", "inventory",
    ])
    assert code == 4
    report = next(out.glob("*.md"))
    assert "## 26. Repository Profile and Task-Based Cross-Validation" in report.read_text(encoding="utf-8")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server._jobs.clear()
    server._batches.clear()
    monkeypatch.setattr(server, "llm_ready", lambda *args: False)
    yield TestClient(server.create_app({}))
    server._jobs.clear()
    server._batches.clear()


def test_api_rejects_invalid_task_payload_before_starting_job(api):
    response = api.post("/api/evaluate", json={
        "url": "https://github.com/owner/repo",
        "task": {"description": "Task", "scoring_weights": {"unknown_criterion": 1.0}},
    })
    assert response.status_code == 422
    assert not server._jobs


def test_api_propagates_task_payload_to_job_and_batch(api, monkeypatch):
    captured = []

    def run(job_id, url, deterministic_only):
        job = server._jobs[job_id]
        captured.append(job.get("task_payload"))
        job.update(state="done", finished=time.time(), evaluation_id=f"report-{job_id}")

    monkeypatch.setattr(server, "_run", run)
    task = {
        "description": "Build an inventory API with stock reservation",
        "id": "inventory",
        "requirements": ["stock reservation"],
        "peer_minimum": 3,
    }
    response = api.post("/api/evaluate", json={"url": "https://github.com/owner/repo", "task": task})
    assert response.status_code == 200
    deadline = time.monotonic() + 3
    while not captured and time.monotonic() < deadline:
        time.sleep(0.01)
    assert captured and captured[0]["definitions"][0]["id"] == "inventory"
    assert captured[0]["peer_minimum"] == 3


def test_api_batch_runs_task_cross_validation_over_completed_profiles(api, monkeypatch):
    def run(job_id, url, deterministic_only):
        job = server._jobs[job_id]
        owner = job["repository"].split("/")[-1]
        job["repository_profile"] = profile(owner, ("stock", "reserv"), score=0.6).model_dump(mode="json")
        job.update(state="done", finished=time.time(), evaluation_id=f"report-{job_id}")

    monkeypatch.setattr(server, "_run", run)
    response = api.post("/api/batches", json={
        "urls": ["https://github.com/owner/one", "https://github.com/owner/two"],
        "deterministic_only": True,
        "task": {
            "id": "inventory",
            "description": "Build an inventory API with stock reservation",
            "requirements": ["stock reservation"],
            "peer_minimum": 2,
        },
    })
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]
    deadline = time.monotonic() + 5
    value = response.json()
    while time.monotonic() < deadline:
        value = api.get(f"/api/batches/{batch_id}").json()
        if value["state"] in {"done", "done_with_errors", "cancelled"}:
            break
        time.sleep(0.02)
    assert value["state"] == "done"
    assert value["task_cross_validation"]["evaluations"]
    assert {item["status"] for item in value["task_cross_validation"]["evaluations"]} == {"INSUFFICIENT_PEERS"}
    assert value["task_cross_validation_error"] is None
