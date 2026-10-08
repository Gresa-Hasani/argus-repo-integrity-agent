"""Deployment-readiness tests: binding, CORS, URL validation, concurrency, public-output hygiene."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import argus.server as server
from argus.collectors.gitutil import RepositoryAccessError, parse_source
from argus.config import Config, load_config
from argus.llm.providers.qwen import OllamaBackend, QwenProvider
from argus.models import CompletionStatus, FinalEvaluation
from argus.pipeline import evaluate
from conftest import FakeProvider, build_clean

ROOT = Path(__file__).resolve().parents[1]
SECRET = "dapi" + "fedcba9876543210" * 2  # Databricks-token-shaped fixture, not a real credential


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # reports and demo data resolve inside the test directory
    monkeypatch.delenv("ARGUS_ALLOWED_ORIGINS", raising=False)
    server._jobs.clear()
    server._llm_state.update(ready=None, checked=0.0)
    yield TestClient(server.create_app({}))
    server._jobs.clear()


def fake_github(monkeypatch, repo_path: Path) -> None:
    """Replace the network: clone a local fixture, and answer the GitHub API from memory."""
    import argus.pipeline as pipeline
    from argus.collectors import github as github_mod
    from argus.collectors.gitutil import RepoSource
    from argus.collectors.gitutil import clone as real_clone

    monkeypatch.setattr(pipeline, "clone", lambda source, dest, timeout=1800: real_clone(RepoSource(str(repo_path), "local", None, "project", None, repo_path), dest))
    monkeypatch.setattr(github_mod.collect, "__defaults__", (lambda path, token: [] if "?" in path else {"full_name": "owner/project", "visibility": "public", "default_branch": "main"},))


def wait_for(client, job_id, timeout=60):
    for _ in range(int(timeout / 0.2)):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


# 1 --- production PORT handling ---------------------------------------------------------------------
def test_bind_address_uses_platform_port_and_keeps_local_default():
    assert server.bind_address({}) == ("127.0.0.1", 8000)  # local development unchanged
    assert server.bind_address({"HOST": "0.0.0.0", "PORT": "7860"}) == ("0.0.0.0", 7860)
    assert server.bind_address({"PORT": "10000"}) == ("127.0.0.1", 10000)
    for bad in ("0", "70000", "abc"):
        with pytest.raises(ValueError):
            server.bind_address({"PORT": bad})


# 2 --- CORS -----------------------------------------------------------------------------------------
def test_cors_origins_are_explicit_and_never_wildcard():
    assert server.allowed_origins({}) == ["http://localhost:3000", "http://127.0.0.1:3000"]
    env = {"ARGUS_ALLOWED_ORIGINS": " https://argus-demo.vercel.app/ , *, https://evil.example/path, null, https://user:pw@x.example, http://*.vercel.app"}
    assert server.allowed_origins(env) == ["http://localhost:3000", "http://127.0.0.1:3000", "https://argus-demo.vercel.app"]


def test_cors_headers_only_for_allowed_origins():
    client = TestClient(server.create_app({"ARGUS_ALLOWED_ORIGINS": "https://argus-demo.vercel.app"}))
    for origin in ("https://argus-demo.vercel.app", "http://localhost:3000"):
        assert client.get("/health", headers={"Origin": origin}).headers.get("access-control-allow-origin") == origin
    for origin in ("https://evil.example", "https://argus-demo.vercel.app.evil.example", "null"):
        response = client.get("/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in response.headers
    preflight = client.options("/api/evaluate", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in preflight.headers


# 3 / 4 --- GitHub URL validation --------------------------------------------------------------------
ACCEPTED = [
    ("https://github.com/gegedobruna/data-capstone", "https://github.com/gegedobruna/data-capstone"),
    ("https://github.com/gegedobruna/data-capstone/", "https://github.com/gegedobruna/data-capstone"),
    ("https://github.com/gegedobruna/data-capstone.git", "https://github.com/gegedobruna/data-capstone"),
    ("https://github.com/DonikaNuredinii/Heart_Disease_Data_Pipeline-", "https://github.com/DonikaNuredinii/Heart_Disease_Data_Pipeline-"),
]
REJECTED = [
    "http://github.com/owner/repo", "https://gitlab.com/owner/repo", "https://github.com.evil.example/owner/repo", "https://evil.example/github.com/owner/repo",
    "https://localhost/owner/repo", "https://127.0.0.1/owner/repo", "http://localhost:11434/api/tags", "https://10.0.0.5/owner/repo", "https://192.168.1.10/owner/repo",
    "https://169.254.169.254/latest/meta-data", "file:///etc/passwd", "file://C:/Windows/win.ini", "git@github.com:owner/repo.git", "ssh://git@github.com/owner/repo",
    "git://github.com/owner/repo", "https://github.enterprise.example/owner/repo", "https://token@github.com/owner/repo", "https://user:pass@github.com/owner/repo",
    "https://github.com/owner/repo?ref=main", "https://github.com/owner/repo#readme", "https://github.com/owner/repo/tree/main", "https://github.com/owner/../repo",
    "https://github.com/owner/..", "https://github.com/owner/.", "https://github.com/../../etc/passwd", "https://github.com/owner", "https://github.com/", "https://github.com//repo",
    "https://github.com/owner/repo%2F..%2F..", "https://github.com/owner/repo\nhttps://evil.example", "https://github.com/owner/repo --upload-pack=x", "--upload-pack=touch /tmp/x",
    "ext::sh -c id", "/etc", "C:\\Windows", ".", "..", "", "https://GITHUB.com@evil.example/owner/repo", "https://github.com:22/owner/repo",
]


@pytest.mark.parametrize("raw,normalized", ACCEPTED)
def test_public_github_urls_are_accepted_and_normalized(raw, normalized):
    source = parse_source(raw)
    assert (source.kind, source.url) == ("github", normalized)


@pytest.mark.parametrize("raw", REJECTED)
def test_api_rejects_everything_that_is_not_a_public_github_repository_url(api, raw, monkeypatch):
    started = []
    monkeypatch.setattr(server, "_run", lambda *a: started.append(a))
    response = api.post("/api/evaluate", json={"url": raw})
    assert response.status_code == 422 and response.json() == {"detail": server.PUBLIC_INVALID_URL}
    assert started == [] and server._jobs == {}  # nothing is fetched, cloned or queued


def test_existing_local_directory_gets_the_same_answer_as_a_missing_one(api, tmp_path):
    (tmp_path / "exists").mkdir()
    a = api.post("/api/evaluate", json={"url": str(tmp_path / "exists")})
    b = api.post("/api/evaluate", json={"url": str(tmp_path / "missing")})
    assert a.status_code == b.status_code == 422 and a.json() == b.json()  # the API is not an oracle for the server's filesystem


# 5 --- concurrency limit ----------------------------------------------------------------------------
def test_only_one_evaluation_runs_at_a_time(api, monkeypatch):
    release, calls = threading.Event(), []

    def slow(job_id, url, deterministic_only):
        calls.append(url)
        release.wait(10)
        server._jobs[job_id].update(state="done", finished=time.time())

    monkeypatch.setattr(server, "_run", slow)
    first = api.post("/api/evaluate", json={"url": "https://github.com/owner/one"})
    assert first.status_code == 200 and first.json()["state"] == "running"
    assert api.get("/ready").json()["accepting_evaluations"] is False
    second = api.post("/api/evaluate", json={"url": "https://github.com/owner/two"})
    assert second.status_code == 429 and second.json() == {"detail": server.PUBLIC_BUSY} and second.headers["retry-after"] == "60"
    assert calls == ["https://github.com/owner/one"]  # the second evaluation never started
    release.set()
    wait_for(api, first.json()["job_id"])
    third = api.post("/api/evaluate", json={"url": "https://github.com/owner/three"})
    assert third.status_code == 200
    release.set()
    wait_for(api, third.json()["job_id"])


# 6 --- safe health / readiness ----------------------------------------------------------------------
def test_health_and_ready_expose_only_minimal_operational_state(api, monkeypatch):
    for path in ("/health", "/api/health"):
        assert api.get(path).json() == {"status": "ok", "service": "argus"}
    monkeypatch.setattr(server, "llm_ready", lambda max_age=30.0: False)
    assert api.get("/ready").json() == {"status": "ready", "accepting_evaluations": True, "ai_reasoning_available": False}
    assert api.get("/docs").status_code == 404 and api.get("/openapi.json").status_code == 404  # no schema browser on a public host


def test_readiness_check_lists_models_and_never_pulls(monkeypatch):
    class Backend:
        name = "stub"
        calls: list[str] = []

        def default_tag(self, logical):
            return logical

        def list_models(self):
            self.calls.append("list")
            return ["qwen3:4b"]

        def chat(self, *a):
            raise AssertionError("readiness must not run inference")

    backend = Backend()
    monkeypatch.setattr(server, "create_provider", lambda cfg: QwenProvider(cfg, backend))
    server._llm_state.update(ready=None, checked=0.0)
    assert server.llm_ready(0) is True and backend.calls == ["list"]
    monkeypatch.setattr(server, "create_provider", lambda cfg: QwenProvider(Config(llm_model="qwen3:8b"), backend))
    assert server.llm_ready(0) is False  # configured model absent: reported, not downloaded


# 7 --- safe error responses -------------------------------------------------------------------------
def test_job_failure_returns_a_fixed_public_message(api, monkeypatch, caplog):
    def explode(self):
        raise RuntimeError(f"git clone failed in C:\\Users\\svc\\AppData\\Temp\\argus-x with GITHUB_TOKEN=ghp_{'a' * 36} via http://localhost:11434")

    monkeypatch.setattr(server.Evaluation, "run", explode)
    job = wait_for(api, api.post("/api/evaluate", json={"url": "https://github.com/owner/project", "deterministic_only": True}).json()["job_id"])
    body = json.dumps(job)
    assert job["state"] == "failed" and job["error"] == server.PUBLIC_FAILURE
    for leak in ("ghp_", "AppData", "RuntimeError", "Traceback", "localhost:11434", "git clone"):
        assert leak not in body
    assert api.get("/ready").json()["accepting_evaluations"] is True  # a failed job does not block the service


def test_unhandled_api_error_is_a_plain_500(monkeypatch):
    monkeypatch.setattr(server, "_saved", lambda: (_ for _ in ()).throw(OSError("E:\\secret\\reports unreadable")))
    client = TestClient(server.create_app({}), raise_server_exceptions=False)
    response = client.get("/api/evaluations")
    assert response.status_code == 500 and response.json() == {"detail": "Internal error."}


# 8 / 9 --- no paths, no secret values, no raw emails in API output -----------------------------------
def test_api_output_contains_no_paths_secrets_or_raw_emails(api, tmp_path, monkeypatch):
    repo = build_clean(tmp_path / "fixture")
    repo.commit("Add settings", {".gitignore": "__pycache__/\n", ".env": f"DATABRICKS_HOST=https://example.cloud.databricks.com\nDATABRICKS_TOKEN={SECRET}\nAPI_URL=http://localhost:9000/v1\n"})
    fake_github(monkeypatch, repo.path)
    job = wait_for(api, api.post("/api/evaluate", json={"url": "https://github.com/owner/project", "deterministic_only": True}).json()["job_id"])
    assert job["state"] == "done", job
    eid = job["evaluation_id"]
    result = api.get(f"/api/evaluate/{eid}").json()
    FinalEvaluation.model_validate(result)  # scrubbing keeps the result schema-valid
    assert any(f["category"] == "SECRET_EXPOSURE" for f in result["findings"])  # the indicator is reported...
    bodies = {
        "result": json.dumps(result), "json": api.get(f"/api/evaluate/{eid}/json").text, "report": api.get(f"/api/evaluate/{eid}/report").text,
        "job": json.dumps(job), "list": api.get("/api/evaluations").text,
    }
    tmp_marker = str(tmp_path).replace("\\", "/").split("/")[-1]
    for name, body in bodies.items():
        assert SECRET not in body, name  # ...but never its value
        assert "alice@example.com" not in body and "checkout_path" not in body, name
        assert tmp_marker not in body and "AppData" not in body and "localhost:11434" not in body and "llm_base_url" not in body, name
        assert not re.search(r"[A-Za-z]:\\\\?Users|/tmp/argus-|/home/\w+", body), name
    assert "a***@example.com" in bodies["result"]
    variables = result["deterministic_metrics"]["hygiene"]["environment"]["credential_variables"]
    assert variables == [{"file": ".env", "line": 2, "variable": "DATABRICKS_TOKEN", "classification": "SECRET_LIKE", "value_length": 36, "is_template_file": False}]


def test_scrub_text_rules():
    s = server.scrub_text
    assert s("clone failed: could not create 'C:\\Users\\Admin\\AppData\\Local\\Temp\\argus-ab12\\target'") == "clone failed: could not create '<path>'"
    assert s("error in /tmp/argus-x1/target/.git and /home/app/src") == "error in <path> and <path>"
    assert s("runtime request failed: http://localhost:11434/api/chat refused") == "runtime request failed: <local service> refused"
    assert s("Gresa <someone.long@gmail.com>") == "Gresa <s***@gmail.com>"
    # Repository-relative paths and public URLs are evidence and stay intact.
    for keep in ("src/app/page.tsx", ".github/workflows/main.yml", "https://github.com/gegedobruna/data-capstone", "CI/CD", "2026-06-06T15:35:13+02:00", "data/train.csv"):
        assert s(keep) == keep


def test_bundled_demo_result_is_valid_and_already_scrubbed():
    files = sorted((ROOT / "demo-data").glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    result = FinalEvaluation.model_validate(json.loads(text))
    assert result.completion_status == CompletionStatus.DONE_WITH_FINDINGS and result.model["model"] == "Qwen3-8B"
    combined = text + files[0].with_suffix(".md").read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z0-9._%+-]{2,}@[A-Za-z0-9.-]+\.[a-z]{2,}", combined)  # no full email addresses
    assert not re.search(r"AppData|checkout_path|localhost:11434|[A-Za-z]:\\\\", combined)


def test_demo_data_is_served_by_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARGUS_DEMO_DIR", str(ROOT / "demo-data"))
    client = TestClient(server.create_app({}))
    rows = client.get("/api/evaluations").json()
    assert [(r["repository"], r["status"]) for r in rows] == [("gegedobruna/data-capstone", "DONE_WITH_FINDINGS")]
    assert "ARGUS Repository Forensics Report" in client.get(f"/api/evaluate/{rows[0]['evaluation_id']}/report").text
    for attempt in ("..%2Fdemo-data%2Fx", "%2Fetc%2Fpasswd", "C:%5CWindows", rows[0]["evaluation_id"] + "%2F..%2F.."):
        assert client.get(f"/api/evaluate/{attempt}/report").status_code == 404


# 10 --- frontend API URL configuration --------------------------------------------------------------
def test_frontend_reads_api_url_from_environment_only():
    page = (ROOT / "ui/app/page.tsx").read_text(encoding="utf-8")
    assert "process.env.NEXT_PUBLIC_API_URL" in page
    assert "localhost:8000" not in page and "127.0.0.1" not in page and "NEXT_PUBLIC_ARGUS_API" not in page
    assert "NEXT_PUBLIC_API_URL=http://localhost:8000" in (ROOT / "ui/.env.development").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_API_URL=" in (ROOT / "ui/.env.example").read_text(encoding="utf-8")


# 11 --- model configuration -------------------------------------------------------------------------
def test_model_is_configured_by_environment_with_a_4b_default():
    assert load_config(env={}).llm_model == "qwen3:4b" and load_config(env={}).llm_fallback_model == ""
    assert load_config(env={"ARGUS_MODEL": "qwen3:8b"}).llm_model == "qwen3:8b"
    assert load_config(env={"ARGUS_LLM_MODEL": "Qwen3-8B", "ARGUS_MODEL": "qwen3:4b"}).llm_model == "qwen3:4b"  # ARGUS_MODEL wins
    assert load_config(env={"ARGUS_MODEL": "qwen3:8b", "ARGUS_FALLBACK_MODEL": "qwen3:4b"}).llm_fallback_model == "qwen3:4b"
    assert load_config(env={"ARGUS_REPORTS_DIR": "/data/argus-reports"}).out_dir == "/data/argus-reports"


@pytest.mark.parametrize("configured,installed,tag", [
    ("qwen3:4b", ["qwen3:4b", "qwen3:8b"], "qwen3:4b"),
    ("qwen3:8b", ["qwen3:4b", "qwen3:8b"], "qwen3:8b"),
    ("qwen3:4b", ["hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M"], "hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M"),
])
def test_configured_model_tag_is_resolved_without_hard_coding(configured, installed, tag):
    class Backend:
        name = "stub"

        def default_tag(self, logical):
            return OllamaBackend(Config()).default_tag(logical)

        def list_models(self):
            return installed

    info = QwenProvider(load_config(env={"ARGUS_MODEL": configured}), Backend()).prepare()
    assert (info["model"], info["runtime_model_tag"], info["fallback_used"]) == (configured, tag, False)


def test_no_model_name_is_hard_coded_in_the_pipeline_or_server():
    for rel in ("src/argus/pipeline.py", "src/argus/server.py", "src/argus/llm/runner.py", "src/argus/policy.py"):
        assert not re.search(r"(?i)qwen3[-:]?(4|8)b", (ROOT / rel).read_text(encoding="utf-8")), rel


# 12 --- temporary clone cleanup ---------------------------------------------------------------------
def test_temporary_clone_is_removed_when_the_pipeline_fails(clean_repo, cfg, monkeypatch):
    import argus.pipeline as pipeline

    monkeypatch.setattr(pipeline.commits_mod, "parse_history", lambda repo, branch: (_ for _ in ()).throw(RuntimeError("collector crashed")))
    ev = evaluate(str(clean_repo), cfg, FakeProvider())
    assert ev.completion_status == CompletionStatus.EVALUATOR_ERROR
    checkout = Path(ev.repository["acquisition"]["checkout_path"])
    assert not checkout.exists() and not checkout.parent.exists()


def test_temporary_directory_is_removed_when_acquisition_or_an_unexpected_error_fails(clean_repo, cfg, monkeypatch):
    import argus.pipeline as pipeline

    seen = []

    def failing_clone(source, dest, timeout=1800):
        seen.append(dest.parent)
        dest.mkdir(parents=True)
        (dest / "partial").write_text("x")
        raise RepositoryAccessError("repository not found")

    monkeypatch.setattr(pipeline, "clone", failing_clone)
    assert evaluate(str(clean_repo), cfg, FakeProvider()).completion_status == CompletionStatus.INCOMPLETE_EVALUATION
    assert seen and not seen[0].exists()

    def crashing_clone(source, dest, timeout=1800):
        seen.append(dest.parent)
        dest.mkdir(parents=True)
        raise KeyboardInterrupt()

    monkeypatch.setattr(pipeline, "clone", crashing_clone)
    with pytest.raises(KeyboardInterrupt):
        evaluate(str(clean_repo), cfg, FakeProvider())
    assert not seen[1].exists()  # the finally block ran even though the error propagated


# --- public demo: static frontend, no backend --------------------------------------------------------
def test_static_demo_data_matches_the_saved_evaluation_and_is_scrubbed():
    demo = ROOT / "ui/public/demo"
    index = json.loads((demo / "index.json").read_text(encoding="utf-8"))
    assert [(r["repository"], r["status"], r["model"], r["findings"]) for r in index] == [("gegedobruna/data-capstone", "DONE_WITH_FINDINGS", "Qwen3-8B", 5)]
    eid = index[0]["evaluation_id"]
    static = (demo / f"{eid}.json").read_text(encoding="utf-8")
    result = FinalEvaluation.model_validate(json.loads(static))  # same schema as a live result
    # Byte-identical to what a local backend serves from demo-data/: the public demo is the real evaluation.
    backend_copy = next((ROOT / "demo-data").glob("*.json")).read_text(encoding="utf-8")
    assert static == backend_copy and result.evaluation_id == eid
    assert len(result.findings) == 5 and len(result.candidate_decisions) == 18 and not result.manual_review["required"]
    combined = static + (demo / f"{eid}.md").read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z0-9._%+-]{2,}@[A-Za-z0-9.-]+\.[a-z]{2,}", combined)
    assert not re.search(r"AppData|checkout_path|localhost:11434|[A-Za-z]:\\\\", combined)


def test_demo_export_is_reproducible(tmp_path, monkeypatch):
    import argus.demo as demo

    monkeypatch.setattr(demo, "BACKEND_DIR", tmp_path / "backend")
    monkeypatch.setattr(demo, "FRONTEND_DIR", tmp_path / "frontend")
    source = next((ROOT / "demo-data").glob("*.json"))
    result = demo.export(source)
    assert (tmp_path / "frontend" / f"{result.evaluation_id}.json").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert json.loads((tmp_path / "frontend" / "index.json").read_text(encoding="utf-8"))[0]["evaluation_id"] == result.evaluation_id


def test_frontend_has_a_separate_demo_mode_that_never_evaluates():
    page = (ROOT / "ui/app/page.tsx").read_text(encoding="utf-8")
    assert "const DEMO_MODE = !API;" in page and 'const DEMO_BASE = "/demo";' in page
    assert "if (DEMO_MODE) return;" in page  # the submit handler refuses to run in the public demo
    assert "Live evaluation is not available here" in page and "disabled={running || liveDisabled}" in page
    # No public-backend deployment artefacts are part of the project.
    for removed in ("Dockerfile", ".dockerignore", "DEPLOYMENT.md", "docker", "deploy"):
        assert not (ROOT / removed).exists(), removed
