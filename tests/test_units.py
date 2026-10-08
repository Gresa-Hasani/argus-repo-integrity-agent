"""Unit tests for deterministic modules, the provider abstraction and the status rules."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argus.collectors import ci as ci_mod
from argus.collectors import hygiene as hygiene_mod
from argus.collectors import readme as readme_mod
from argus.collectors.classify import classify_path
from argus.collectors.commits import Commit, is_weak_message, parse_history
from argus.collectors.contributors import build_identity_map, identity_kind
from argus.collectors.gitutil import parse_source, tracked_files
from argus.collectors.scc import count_text
from argus.collectors.similarity import compare, shingles
from argus.config import Config, load_config
from argus.evidence import EvidenceStore, build_packet
from argus.llm.interface import LLMError, LLMResponse, LLMUnavailableError, create_provider
from argus.llm.providers.qwen import OllamaBackend, OpenAICompatBackend, QwenProvider
from argus.llm.runner import LLMStepError, constrained_schema, extract_json, run_step
from argus.models import AnalysisResult, Category, CompletionStatus, CoverageStatus, EvaluatorError, Finding, FindingType, LLMFinding, ModuleStatus, Severity
from argus.status import MODULES, decide, is_mandatory
from conftest import ALICE, BOB, FakeProvider, RepoBuilder


# --- classification / counting ------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/app/page.tsx", "source"), ("node_modules/react/index.js", "vendored"), ("package-lock.json", "lockfile"),
        ("dist/bundle.js", "build_output"), ("static/app.min.js", "minified"), ("tests/test_api.py", "tests"),
        ("src/utils.test.ts", "tests"), (".github/workflows/ci.yml", "ci"), ("README.md", "docs"), ("Dockerfile", "config"),
        ("models/classifier.pt", "model_artifact"), ("data/train.csv", "dataset"), ("api/client_pb2.py", "generated"),
        ("prisma/migrations/001/migration.sql", "generated"), ("public/logo.png", "binary"), ("tsconfig.json", "config"),
    ],
)
def test_classify_path(path, expected):
    assert classify_path(path) == expected


def test_count_text_separates_code_comments_blanks():
    assert count_text("# header\n\nx = 1\ny = 2  # trailing\n", "Python") == (4, 2, 1, 1)
    assert count_text("/* a\n b */\nint x;\n// c\n", "C") == (4, 1, 3, 0)


@pytest.mark.parametrize("message,weak", [("update", True), ("fix", True), ("asdf", True), ("Initial commit", False), ("Implement refresh-token rotation", False), ("fix: stuff", True), ("feat: add evaluation endpoint", False)])
def test_weak_message_detection(message, weak):
    assert is_weak_message(message) is weak


# --- repository reference validation --------------------------------------------------------------
def test_parse_source_accepts_only_github_https_or_local(tmp_path):
    s = parse_source("https://github.com/boyter/scc.git")
    assert (s.kind, s.owner, s.name, s.url) == ("github", "boyter", "scc", "https://github.com/boyter/scc")
    assert parse_source(str(tmp_path)).kind == "local"
    for bad in ["git@github.com:o/r.git", "https://evil.example/o/r", "--upload-pack=touch x", "file:///etc", "https://github.com/o/r/tree/main; rm -rf", "ext::sh -c id"]:
        with pytest.raises(ValueError):
            parse_source(bad)


# --- identities and co-authors --------------------------------------------------------------------
def _commit(name, email, coauthors=(), sha="a" * 40):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return Commit(sha, [], name, email, name, email, now, now, "msg", "", coauthors=list(coauthors))


def test_identities_merge_on_evidence_not_on_similar_names():
    commits = [
        _commit("Alice Example", "alice@example.com"), _commit("alice-dev", "Alice@Example.com"),
        _commit("alice-dev", "12345+alice-dev@users.noreply.github.com"), _commit("Alice Example", "alice@other.org"),
        _commit("Bob", "bob@example.com", coauthors=[("Claude", "noreply@anthropic.com")]),
    ]
    people, lookup = build_identity_map(commits)
    assert lookup[("Alice Example", "alice@example.com")] == lookup[("alice-dev", "alice@example.com")] == lookup[("alice-dev", "12345+alice-dev@users.noreply.github.com")]
    other = lookup[("Alice Example", "alice@other.org")]
    assert other != lookup[("Alice Example", "alice@example.com")]  # same display name is only a hint
    assert lookup[("Alice Example", "alice@example.com")] in next(p for p in people if p["id"] == other)["possibly_same_person_as"]
    assert next(p for p in people if p["canonical_contributor"] == "Claude")["kind"] == "ai_tool"
    assert identity_kind("GitHub", "noreply@github.com") == "platform" and identity_kind("dependabot[bot]", "x@users.noreply.github.com") == "bot"


def test_history_parsing_reads_authors_trailers_and_numstat(tmp_path):
    repo = RepoBuilder(tmp_path / "r")
    repo.commit("Add module", {"a.py": "x = 1\ny = 2\n"})
    repo.commit("Extend module", {"a.py": "x = 1\ny = 3\nz = 4\n"}, author=BOB, coauthors=(ALICE,))
    repo.commit("Marker", allow_empty=True)
    clone = tmp_path / "clone"
    from argus.collectors.gitutil import clone as do_clone

    do_clone(parse_source(str(repo.path)), clone)
    commits = parse_history(clone, "main")
    assert [c.subject for c in commits] == ["Add module", "Extend module", "Marker"]
    assert (commits[1].author_name, commits[1].additions, commits[1].deletions) == ("Bob Example", 2, 1)
    assert commits[1].coauthors == [ALICE] and commits[2].files == [] and all(c.on_default for c in commits)
    assert tracked_files(clone) == ["a.py"]


# --- hygiene / CI / README ------------------------------------------------------------------------
def test_secret_scan_redacts_and_ignores_placeholders(tmp_path):
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    (tmp_path / "config.py").write_text(f'KEY = "{key}"\nPASSWORD = "changeme"\nAPI_KEY = os.environ["API_KEY"]\ndb = "postgres://app:s3cr3tPassw0rd@db.internal/app"\n', encoding="utf-8")
    (tmp_path / ".env.example").write_text("API_KEY=your-api-key-here\n", encoding="utf-8")
    hits = hygiene_mod.scan_secrets(tmp_path, ["config.py", ".env.example"])
    assert sorted(h["kind"] for h in hits) == ["aws_access_key_id", "credential_in_url"]
    assert all(key not in json.dumps(h) and "s3cr3tPassw0rd" not in json.dumps(h) for h in hits)
    assert hygiene_mod.redact("sk-proj-abcdefghijklmnop8Fd") == "sk-p**********8Fd"


def test_ci_consistency_detects_mismatched_ecosystem(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm ci && npm run build\n      - run: pytest\n        working-directory: backend\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    result = ci_mod.analyze(tmp_path, [".github/workflows/ci.yml", "requirements.txt", "app.py"], EvidenceStore())
    issues = " | ".join(i["issue"] for i in result["consistency_findings"])
    assert "Node.js commands but no package.json" in issues and "working-directory 'backend'" in issues and "no test files" in issues
    assert result["workflows"][0]["triggers"] == ["push"] and "test" in result["capabilities"]


def test_readme_claims_are_cross_checked(tmp_path):
    (tmp_path / "README.md").write_text("# API\n\nBuilt with FastAPI and PostgreSQL. Caching uses Redis.\nThe model reaches 97% accuracy.\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\npsycopg[binary]\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\nimport psycopg\napp = FastAPI()\n", encoding="utf-8")
    result = readme_mod.analyze(tmp_path, ["README.md", "requirements.txt", "main.py"], EvidenceStore())
    status = {c["technology"]: c["status"] for c in result["claims"]}
    assert status == {"PostgreSQL": "VERIFIED", "Redis": "NOT_VERIFIED", "FastAPI": "VERIFIED"}
    assert result["ml_claims"]


def test_similarity_containment():
    a = {"a.py": shingles("def f(x):\n    return x + 1\n" * 20)}
    assert compare(a, a, 0.7)["similarity_estimate"] == 1.0
    assert compare(a, {"b.py": shingles("class Q:\n    name = 'q'\n" * 20)}, 0.7)["similarity_estimate"] == 0.0


# --- evidence store and packets -------------------------------------------------------------------
def test_anomalies_must_cite_existing_evidence_and_packets_state_omissions():
    store = EvidenceStore()
    ids = [store.add("commit", "commits", f"commit {i}", {"blob": "x" * 500}) for i in range(30)]
    with pytest.raises(KeyError):
        store.add_anomaly(Category.COMMIT_INFLATION, "t", "d", ["EV-NOPE-001"])
    anomaly = store.add_anomaly(Category.COMMIT_INFLATION, "t", "d", ids[:2], Severity.LOW, True)
    packet, allowed = build_packet(store, {}, [*ids, anomaly, "EV-UNKNOWN-1"], 4000)
    assert allowed[0] == anomaly and "EV-UNKNOWN-1" not in allowed
    assert packet["omitted_evidence_count"] == 31 - len(allowed) > 0
    assert len(json.dumps(packet)) <= 4000


# --- LLM runner -----------------------------------------------------------------------------------
def _store():
    store = EvidenceStore()
    return store, store.add("commit", "commits", "commit abc", {})


def test_extract_json_handles_think_blocks_and_fences():
    assert extract_json('<think>hmm {"a": 2}</think>\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": 1} done') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_schema_is_narrowed_to_packet_ids():
    schema = constrained_schema(AnalysisResult, ["EV-COMMIT-001"], [], ["LOW", "HIGH"])
    assert schema["$defs"]["LLMFinding"]["properties"]["evidence_ids"]["items"]["enum"] == ["EV-COMMIT-001"]
    assert schema["properties"]["resolved_anomalies"]["maxItems"] == 0
    assert schema["properties"]["classification"]["enum"] == ["LOW", "HIGH"]
    assert constrained_schema(AnalysisResult, [], [], None)["properties"]["findings"]["maxItems"] == 0


def test_run_step_rejects_evidence_outside_the_packet_even_if_it_exists_in_the_store():
    store, in_packet = _store()
    elsewhere = store.add("commit", "commits", "another commit", {})
    reply = json.dumps({"summary": "ok ok", "findings": [{"title": "Finding", "category": "COMMIT_INTEGRITY", "severity": "LOW", "finding": "text", "reasoning": "why", "evidence_ids": [elsewhere], "confidence": 0.5}]})
    with pytest.raises(LLMStepError) as err:
        run_step(FakeProvider(lambda s, p, schema: reply), "commit_analysis", {"metrics": {}}, [in_packet], store)
    assert "not in the evidence packet" in str(err.value) and err.value.attempts == 2


def test_run_step_requires_evidence_and_valid_enums():
    store, ev = _store()
    for bad in [
        {"summary": "ok ok", "findings": [{"title": "Finding", "category": "COMMIT_INTEGRITY", "severity": "LOW", "finding": "text", "reasoning": "why", "evidence_ids": [], "confidence": 0.5}]},
        {"summary": "ok ok", "findings": [{"title": "Finding", "category": "PLAGIARISM", "severity": "LOW", "finding": "text", "reasoning": "why", "evidence_ids": [ev], "confidence": 0.5}]},
        {"summary": "ok ok", "findings": [{"title": "Finding", "category": "COMMIT_INTEGRITY", "severity": "LOW", "finding": "text", "reasoning": "why", "evidence_ids": [ev], "confidence": 7}]},
        {"findings": []},
    ]:
        with pytest.raises(LLMStepError):
            run_step(FakeProvider(lambda s, p, schema, bad=bad: json.dumps(bad)), "commit_analysis", {}, [ev], store)
    with pytest.raises(LLMStepError):
        run_step(FakeProvider(lambda s, p, schema: json.dumps({"summary": "ok ok", "classification": "DEFINITELY_AI"})), "ai_signal_analysis", {}, [ev], store, classifications=["LOW", "HIGH"])


def test_llm_finding_normalises_model_formatting():
    f = LLMFinding(title="Finding", category="commit quality".replace("quality", "integrity"), severity="medium", finding="text", reasoning="why", evidence_ids=["EV-1"], confidence="medium")
    assert (f.category, f.severity, f.confidence) == (Category.COMMIT_INTEGRITY, Severity.MEDIUM, 0.6)


# --- provider abstraction -------------------------------------------------------------------------
def QCFG(**kw):
    """The 8B-primary / 4B-fallback pairing these provider tests were written for."""
    return Config(llm_model="Qwen3-8B", llm_fallback_model="Qwen3-4B", **kw)


class StubBackend:
    name = "stub"

    def __init__(self, installed, failing=()):
        self.installed, self.failing, self.used = installed, set(failing), []

    def default_tag(self, logical):
        return OllamaBackend(Config()).default_tag(logical)

    def list_models(self):
        if self.installed is None:
            raise LLMUnavailableError("connection refused")
        return self.installed

    def chat(self, model, system, prompt, schema):
        self.used.append(model)
        if model in self.failing:
            raise LLMError("out of memory")
        return LLMResponse(text='{"ok": true}', model=model)


def test_default_tags_per_backend():
    assert OllamaBackend(Config()).default_tag("Qwen3-8B") == "qwen3:8b"
    assert OpenAICompatBackend(Config()).default_tag("Qwen3-4B") == "Qwen/Qwen3-4B"
    assert OllamaBackend(Config()).default_tag("mistral:7b") == "mistral:7b"


def test_qwen_resolves_primary_then_fallback():
    primary = QwenProvider(QCFG(), StubBackend(["qwen3:8b", "hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M"]))
    info = primary.prepare()
    assert (info["model"], info["runtime_model_tag"], info["fallback_used"]) == ("Qwen3-8B", "qwen3:8b", False)
    assert primary.fallback_tag == "hf.co/ggml-org/Qwen3-4B-GGUF:Q4_K_M"  # found by name match, not hard-coded

    only_small = QwenProvider(QCFG(), StubBackend(["qwen3:4b"]))
    info = only_small.prepare()
    assert (info["model"], info["fallback_used"]) == ("Qwen3-4B", True) and "not available" in info["fallback_reason"]

    assert QwenProvider(Config(llm_model="Qwen3-4B"), StubBackend(["qwen3:4b"])).prepare()["model"] == "Qwen3-4B"
    assert QwenProvider(QCFG(llm_model_tags={"Qwen3-8B": "my-qwen"}), StubBackend(["my-qwen"])).prepare()["runtime_model_tag"] == "my-qwen"
    for installed in (["llama3:8b"], None):
        with pytest.raises(LLMUnavailableError):
            QwenProvider(QCFG(), StubBackend(installed)).prepare()


def test_qwen_switches_to_fallback_once_when_primary_fails_at_runtime():
    backend = StubBackend(["qwen3:8b", "qwen3:4b"], failing=["qwen3:8b"])
    provider = QwenProvider(QCFG(), backend)
    provider.prepare()
    assert provider.generate("s", "p").model == "qwen3:4b"
    assert provider.info()["fallback_used"] and backend.used == ["qwen3:8b", "qwen3:4b"]
    backend.failing.add("qwen3:4b")
    with pytest.raises(LLMError):
        provider.generate("s", "p")


def test_provider_registry():
    assert isinstance(create_provider(Config()), QwenProvider)
    with pytest.raises(LLMUnavailableError):
        create_provider(Config(llm_provider="nope"))
    with pytest.raises(LLMUnavailableError):
        create_provider(Config(llm_backend="nope"))


# --- configuration --------------------------------------------------------------------------------
def test_config_precedence_and_no_credentials_in_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_notarealtoken")
    path = tmp_path / "argus.toml"
    path.write_text('[llm]\nmodel = "Qwen3-4B"\ntemperature = 0.3\n[llm.model_tags]\n"Qwen3-4B" = "custom:4b"\n[evaluation]\nsimilarity_threshold = 0.8\n', encoding="utf-8")
    cfg = load_config(str(path), env={"ARGUS_LLM_TEMPERATURE": "0.2", "ARGUS_LLM_BASE_URL": "http://localhost:8000"}, overrides={"llm_model": "Qwen3-8B", "deadline": None})
    assert (cfg.llm_model, cfg.llm_temperature, cfg.llm_base_url, cfg.similarity_threshold) == ("Qwen3-8B", 0.2, "http://localhost:8000", 0.8)
    assert cfg.llm_model_tags == {"Qwen3-4B": "custom:4b"} and cfg.github_token == "ghp_notarealtoken"
    assert "ghp_notarealtoken" not in json.dumps(cfg.public_dict())
    defaults = load_config(env={})
    assert (defaults.llm_model, defaults.llm_fallback_model, defaults.similarity_threshold) == ("qwen3:4b", "", 0.70)


# --- completion-state rules -----------------------------------------------------------------------
def _coverage(**overrides):
    return [CoverageStatus(module=m, status=overrides.get(m, ModuleStatus.PASS), mandatory=is_mandatory(m, False)) for m in MODULES]


def _finding(severity, manual=False):
    material = manual or severity in (Severity.HIGH, Severity.CRITICAL)
    kind = FindingType.MATERIAL_INTEGRITY_CONCERN if material else FindingType.ENGINEERING_WEAKNESS
    return Finding(finding_id="ARGUS-X-001", finding_type=kind, category=Category.COMMIT_INTEGRITY, severity=severity, title="t", finding="f", confidence=0.5, material=material, requires_manual_review=material)


def test_completion_state_rules():
    assert decide(_coverage(), [], [])[0] == CompletionStatus.DONE_CLEAN
    assert decide(_coverage(), [_finding(Severity.LOW)], [])[0] == CompletionStatus.DONE_WITH_FINDINGS
    assert decide(_coverage(), [_finding(Severity.MEDIUM, manual=True)], [])[0] == CompletionStatus.FLAGGED
    assert decide(_coverage(), [_finding(Severity.HIGH)], [])[0] == CompletionStatus.FLAGGED
    assert decide(_coverage(pull_requests=ModuleStatus.UNVERIFIABLE), [], [])[0] == CompletionStatus.DONE_WITH_FINDINGS
    assert decide(_coverage(timeline=ModuleStatus.UNVERIFIABLE), [_finding(Severity.HIGH)], [])[0] == CompletionStatus.INCOMPLETE_EVALUATION
    status, dod = decide(_coverage(timeline=ModuleStatus.UNVERIFIABLE), [], [EvaluatorError(stage="x", kind="K", message="m")])
    assert status == CompletionStatus.EVALUATOR_ERROR and not dod.satisfied
    assert decide(_coverage()[:-1], [], [])[0] == CompletionStatus.EVALUATOR_ERROR  # a module silently missing
    assert decide(_coverage(pull_requests=ModuleStatus.NOT_APPLICABLE), [], [])[1].counts["not_applicable"] == 1


def test_published_schemas_match_the_models():
    from argus.llm.schemas import export

    for name, schema in export.schemas().items():
        on_disk = json.loads((Path(export.__file__).parent / name).read_text(encoding="utf-8"))
        assert on_disk == schema, f"{name} is stale: run `python -m argus.llm.schemas.export`"


# --- GitHub URL workflow --------------------------------------------------------------------------
def test_github_api_coverage_distinguishes_success_empty_unverifiable_error():
    import urllib.error

    from argus.collectors import github as github_mod

    def fetch(path, token):
        if path.endswith("/data-capstone"):
            return {"full_name": "o/data-capstone", "visibility": "public", "default_branch": "main", "fork": False}
        if "/pulls" in path:
            return []
        if "/actions/runs" in path:
            raise urllib.error.HTTPError(path, 403, "rate limit exceeded", {}, None)
        if "/actions/workflows" in path:
            return {"total_count": 1, "workflows": [{"name": "CI", "path": ".github/workflows/ci.yml", "state": "active"}]}
        if "/branches" in path:
            return [{"name": "main", "protected": False}, {"name": "dev", "protected": False}]
        if "/contributors" in path:
            raise TimeoutError("timed out")
        return []

    gh = github_mod.collect("o", "data-capstone", None, fetch)
    assert gh["coverage"] == {
        "metadata": "SUCCESS", "pull_requests": "EMPTY", "pull_request_reviews": "NOT_APPLICABLE", "workflow_runs": "UNVERIFIABLE",
        "workflows": "SUCCESS", "branches": "SUCCESS", "contributors": "ERROR", "releases": "EMPTY", "commits": "NOT_APPLICABLE", "issues": "NOT_APPLICABLE",
    }
    assert gh["pull_requests"]["count"] == 0 and "workflow_runs" not in gh and "contributors" not in gh  # nothing fabricated for failed endpoints
    assert gh["errors"]["workflow_runs"].startswith("HTTP 403") and gh["authenticated"] is False


def test_github_url_is_normalized_and_original_is_preserved():
    for raw in ("https://github.com/gegedobruna/data-capstone", "https://github.com/gegedobruna/data-capstone.git", "https://github.com/gegedobruna/data-capstone/"):
        s = parse_source(raw)
        assert (s.raw, s.url, s.owner, s.name, s.slug) == (raw, "https://github.com/gegedobruna/data-capstone", "gegedobruna", "data-capstone", "gegedobruna/data-capstone")
