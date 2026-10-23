"""Thin HTTP API around the ARGUS pipeline for the web UI. No evaluation logic lives here.

Local development:   python -m uvicorn argus.server:app --port 8000
Container / hosting: python -m argus.server          (binds HOST:PORT, default 127.0.0.1:8000)

This is the only public interface of a deployment. The model runtime (Ollama) stays on the
loopback interface and is never proxied.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Mapping, Optional
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from argus import __version__
from argus.cli import write_validated
from argus.report import validate, write_reports
from argus.collectors.gitutil import GITHUB_URL_RE, parse_source
from argus.collectors.github import _get as github_get
from argus.cohort import cross_validate, overlap_flags
from argus.config import CLOUD_DEFAULTS, load_config
from argus.llm.interface import LLMError, create_provider
from argus.models import FinalEvaluation, RepositoryProfile
from argus.pipeline import Evaluation
from argus.statistics import cohort_statistics, report_statistics
from argus.task_validation import ScoringConfig, cross_validate_tasks
from argus.tasks import TaskCatalog
from argus.worker import EvaluationCancelled, run_comparison, run_evaluation

log = logging.getLogger("argus.server")

STAGES = ["Repository acquisition", "Evidence collection", "AI reasoning", "Policy evaluation", "Report generation"]
_MARKERS = {"[1/4]": 0, "[2/4]": 1, "[3/4]": 2, "[4/4]": 3}
MAX_ACTIVE_JOBS = 1  # one evaluation at a time: a free host cannot run concurrent model inference
DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

PUBLIC_INVALID_URL = "Enter a public GitHub repository URL in the form https://github.com/<owner>/<repository>."
PUBLIC_BUSY = "ARGUS is currently evaluating another repository. Only one evaluation runs at a time; please try again shortly."
PUBLIC_FAILURE = "The evaluation could not be completed because of an internal error. No partial result was produced."

_jobs: dict[str, dict[str, Any]] = {}
_batches: dict[str, dict[str, Any]] = {}
_lock = threading.RLock()
_llm_state: dict[str, Any] = {"ready": None, "checked": 0.0}


# ------------------------------------------------------------------ configuration helpers
def allowed_origins(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Origins from ARGUS_ALLOWED_ORIGINS (comma-separated) plus local development. Never a wildcard."""
    env = os.environ if env is None else env
    origins = list(DEFAULT_ORIGINS)
    for raw in (env.get("ARGUS_ALLOWED_ORIGINS") or "").split(","):
        origin = raw.strip().rstrip("/")
        # Exact http(s) origins only: no wildcards, no paths, no credentials.
        if origin and re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?", origin) and origin not in origins:
            origins.append(origin)
    return origins


def bind_address(env: Optional[Mapping[str, str]] = None) -> tuple[str, int]:
    """HOST/PORT for `python -m argus.server`. Hosting platforms inject PORT; local default is 127.0.0.1:8000."""
    env = os.environ if env is None else env
    port = int(env.get("PORT") or 8000)
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return env.get("HOST") or "127.0.0.1", port


# ------------------------------------------------------------------ public-output hygiene
_ABS_PATH = re.compile(
    r"(?<![\w/.:-])(?:[A-Za-z]:[\\/]{1,2}(?:[^\s\"'<>|:*?]+)|\\\\\?\\[^\s\"'<>]+|/(?:tmp|home|root|var|usr|opt|app|srv|mnt|etc|Users|private|workspace|data)/[^\s\"'<>]*)"
)
_LOCAL_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal)(?::\d+)?[^\s\"'<>]*", re.I)
_EMAIL = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def scrub_text(text: str) -> str:
    """Remove what a public response must not carry: absolute paths, local service URLs, full email addresses."""
    text = _LOCAL_URL.sub("<local service>", text)
    text = _ABS_PATH.sub("<path>", text)
    return _EMAIL.sub(r"\1***@\2", text)


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def public_result(result: FinalEvaluation) -> dict[str, Any]:
    """The evaluation as served to browsers."""
    data = result.model_dump(mode="json")
    (data.get("repository", {}).get("acquisition") or {}).pop("checkout_path", None)
    data.get("model", {}).pop("base_url", None)
    (data.get("deterministic_metrics", {}).get("config") or {}).pop("llm_base_url", None)
    # Optional task layer: omit empty values so demo exports of pre-task reports stay byte-identical.
    for key in ("repository_profile", "task_evaluation", "profiling_error"):
        if data.get(key) is None:
            data.pop(key, None)
    return scrub(data)


# ------------------------------------------------------------------ report lookup (by evaluation id only)
def _report_dirs() -> list[Path]:
    dirs = [Path(load_config().out_dir).resolve()]
    demo = Path(os.environ.get("ARGUS_DEMO_DIR") or "demo-data").resolve()
    if demo not in dirs:
        dirs.append(demo)
    return dirs


def _saved() -> dict[str, dict[str, Any]]:
    """Completed evaluations on disk, keyed by evaluation_id. Only files that match the current schema."""
    found: dict[str, dict[str, Any]] = {}
    for directory in _report_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                result = FinalEvaluation.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue  # written by an older schema version, or not an ARGUS report
            found.setdefault(result.evaluation_id, {"result": result, "md_path": path.with_suffix(".md")})
    return found


def _entry(evaluation_id: str) -> dict[str, Any]:
    entry = _saved().get(evaluation_id)  # lookup by id only: no client-supplied path ever reaches the filesystem
    if not entry:
        raise HTTPException(status_code=404, detail="Unknown evaluation.")
    return entry


def evaluation_config(provider: str = "configured"):
    if provider == "configured":
        return load_config()
    overrides = {"llm_provider": provider, **CLOUD_DEFAULTS[provider]}
    prefix = "ARGUS_OPENAI" if provider == "openai" else "ARGUS_ANTHROPIC"
    for suffix, attr in (("MODEL", "llm_model"), ("BASE_URL", "llm_base_url")):
        if os.environ.get(prefix + "_" + suffix):
            overrides[attr] = os.environ[prefix + "_" + suffix]
    return load_config(overrides=overrides)


# ------------------------------------------------------------------ readiness
def llm_ready(max_age: float = 30.0) -> bool:
    """Is the configured model present in the local runtime? Lists models only; never downloads one."""
    now = time.time()
    if _llm_state["ready"] is not None and now - _llm_state["checked"] < max_age:
        return bool(_llm_state["ready"])
    try:
        create_provider(load_config()).prepare()
        ready = True
    except LLMError:
        ready = False
    except Exception:
        log.exception("model readiness check failed")
        ready = False
    _llm_state.update(ready=ready, checked=now)
    return ready


def active_jobs() -> int:
    with _lock:
        return sum(job["state"] in {"running", "queued"} for job in _jobs.values()) + sum(
            batch["state"] in {"running", "comparing", "stopping"} for batch in _batches.values())


# ------------------------------------------------------------------ task payload helpers
def _task_payload_dict(payload: Any) -> Optional[dict[str, Any]]:
    """Normalise the API task object, including a single task or a list of definitions."""
    if payload is None:
        return None
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload)
    definitions = list(data.get("definitions") or data.get("tasks") or [])
    if not definitions and data.get("description"):
        definitions = [{
            "id": data.get("id", ""), "description": data["description"], "title": data.get("title", ""),
            "category": data.get("category", ""), "requirements": data.get("requirements") or [],
            "aliases": data.get("aliases") or [],
        }]
    out: dict[str, Any] = {}
    if definitions:
        out["definitions"] = definitions
    if data.get("assignments"):
        out["assignments"] = dict(data["assignments"])
    for source, destination in (
        ("relevance_threshold", "task_relevance_threshold"),
        ("similarity_threshold", "task_similarity_threshold"),
        ("scoring_weights", "scoring_weights"),
        ("peer_context_weight", "peer_context_weight"),
        ("peer_minimum", "peer_minimum"),
    ):
        if data.get(source) is not None:
            out[destination] = data[source]
    return out or None


def _apply_task_payload(cfg, payload: Any) -> None:
    """Apply validated task/scoring settings to a Config instance."""
    data = _task_payload_dict(payload)
    if not data:
        return
    if "definitions" in data:
        cfg.task_definitions = data["definitions"]
        cfg.task_description = ""
        cfg.task_requirements = []
    if "assignments" in data:
        cfg.task_assignments = {**cfg.task_assignments, **data["assignments"]}
    for key in ("task_relevance_threshold", "task_similarity_threshold", "scoring_weights", "peer_context_weight", "peer_minimum"):
        if key in data:
            setattr(cfg, key, data[key])


def _prepare_task_config(cfg, payload: Any):
    """Validate a request payload before a job starts; returns the configured object."""
    _apply_task_payload(cfg, payload)
    if payload is not None:
        TaskCatalog.from_config(cfg)
        ScoringConfig.from_config(cfg)
    return cfg


def _task_config_for_request(payload: Any, provider: str = "configured"):
    try:
        return _prepare_task_config(evaluation_config(provider), payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Task configuration is invalid: {scrub_text(str(exc))[:300]}") from None


def _task_config_for_batch(batch: dict[str, Any]):
    cfg = evaluation_config(batch.get("provider", "configured"))
    try:
        return _prepare_task_config(cfg, batch.get("task_payload"))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _run_task_cross_validation(batch: dict[str, Any]) -> None:
    """Compare completed batch members only with peers assigned to the same task."""
    cfg = _task_config_for_batch(batch)
    catalog = TaskCatalog.from_config(cfg)
    if not catalog.configured:
        return
    profiles = []
    for job_id in batch["job_ids"]:
        job = _jobs[job_id]
        data = job.get("repository_profile")
        if job.get("state") == "done" and data:
            try:
                profiles.append((job_id, RepositoryProfile.model_validate(data)))
            except Exception:
                continue
    if not profiles:
        batch["task_cross_validation_error"] = "No repository profiles were available for task-based peer comparison."
        return
    scoring = ScoringConfig.from_config(cfg)
    validation = cross_validate_tasks(
        [profile for _, profile in profiles], catalog, scoring=scoring,
        relevance_threshold=cfg.task_relevance_threshold,
        task_similarity_threshold=cfg.task_similarity_threshold,
    )
    batch["task_cross_validation"] = validation.model_dump(mode="json")
    by_repository = {evaluation.repository: evaluation for evaluation in validation.evaluations}
    saved = _saved()
    reports_dir = Path(batch.get("reports_dir") or cfg.out_dir)
    for job_id, profile in profiles:
        evaluation = by_repository.get(profile.repository)
        job = _jobs[job_id]
        if evaluation is None or not job.get("evaluation_id"):
            continue
        entry = saved.get(job["evaluation_id"])
        if not entry:
            continue
        result: FinalEvaluation = entry["result"]
        result.repository_profile = evaluation.profile
        result.task_evaluation = evaluation
        if validate(result):
            continue
        write_reports(result, reports_dir)


# ------------------------------------------------------------------ job execution
def _run(job_id: str, url: str, deterministic_only: bool) -> None:
    job = _jobs[job_id]
    cancel = job.setdefault("cancel", threading.Event())

    def progress(message: str) -> None:
        text = scrub_text(message.strip())
        if not text:
            return
        with _lock:
            for marker, index in _MARKERS.items():
                if text.startswith(marker):
                    job["stage_index"] = index
            job["log"].append(text)

    try:
        cfg = evaluation_config(job.get("provider", "configured"))
        if job.get("task_payload"):
            _prepare_task_config(cfg, job["task_payload"])
        if deterministic_only:
            cfg.llm_enabled = False
        cfg.work_dir = job.get("work_dir") or cfg.work_dir
        with _lock:
            job["model"] = cfg.llm_model if cfg.llm_enabled else "disabled (deterministic only)"
        if cancel.is_set():
            raise EvaluationCancelled()
        # The parent owns temporary storage so it is cleaned even when a worker is killed.
        if cfg.work_dir:
            result = run_evaluation(url, cfg, progress, cancel)
        else:
            with tempfile.TemporaryDirectory(prefix="argus-job-") as root:
                cfg.work_dir = root
                result = run_evaluation(url, cfg, progress, cancel)
        if cancel.is_set():
            raise EvaluationCancelled()
        with _lock:
            job["stage_index"] = 4
            job["log"].append("Writing and validating reports")
        write_validated(result, Path(cfg.out_dir))
        with _lock:
            job.update(state="done", stage_index=5, evaluation_id=result.evaluation_id, finished=time.time(),
                       completion_status=result.completion_status.value,
                       acquired=bool(result.repository.get("acquisition", {}).get("success")))
            if result.repository_profile is not None:
                job["repository_profile"] = result.repository_profile.model_dump(mode="json")
            job["log"].append(f"Evaluation status: {result.completion_status.value}")
    except EvaluationCancelled:
        with _lock:
            job.update(state="cancelled", finished=time.time())
            job["log"].append("Evaluation stopped by user. No partial report was saved.")
    except Exception:
        # Details stay in the server log. The browser gets a fixed message: no traceback, path or command.
        log.exception("evaluation job %s failed", job_id)
        with _lock:
            job.update(state="failed", error=PUBLIC_FAILURE, finished=time.time())


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"], "state": job["state"], "repository": job["repository"], "model": job.get("model"),
        "stages": STAGES, "stage_index": job["stage_index"], "log": job["log"][-40:], "error": job.get("error"),
        "evaluation_id": job.get("evaluation_id"), "elapsed_s": 0 if job["state"] == "queued" else round((job.get("finished") or time.time()) - job["started"], 1),
        "deterministic_only": job["deterministic_only"],
        "completion_status": job.get("completion_status"),
    }


def _public_source(raw: str):
    raw = raw.strip()
    if len(raw) > 200 or not GITHUB_URL_RE.match(raw):
        raise HTTPException(status_code=422, detail=PUBLIC_INVALID_URL)
    try:
        return parse_source(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=PUBLIC_INVALID_URL) from None


def _batch_view(batch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        items = [_job_view(_jobs[j]) for j in batch["job_ids"]]
        flags = overlap_flags(batch.get("cross_validation", []))
        for item in items:
            item["similarity_flagged"] = item["repository"] in flags
        return {
            "batch_id": batch["batch_id"], "state": batch["state"], "model": batch["model"], "provider": batch.get("provider", "configured"),
            "total": len(items), "completed": sum(j["state"] in {"done", "failed", "cancelled"} for j in items),
            "cancelled": sum(j["state"] == "cancelled" for j in items),
            "failed": sum(j["state"] == "failed" for j in items), "items": items,
            "cross_validation": batch.get("cross_validation", []),
            "cross_validation_error": batch.get("cross_validation_error"),
            "task_cross_validation": batch.get("task_cross_validation"),
            "task_cross_validation_error": batch.get("task_cross_validation_error"),
            "persistence_error": batch.get("persistence_error"),
            "elapsed_s": round((batch.get("finished") or time.time()) - batch["started"], 1),
        }


def _run_batch(batch_id: str) -> None:
    batch = _batches[batch_id]
    cancel = batch.setdefault("cancel", threading.Event())
    try:
        # Retain each safe clone only until pairwise comparison has finished.
        with tempfile.TemporaryDirectory(prefix="argus-batch-") as root:
            repositories = []
            for job_id in batch["job_ids"]:
                job = _jobs[job_id]
                with _lock:
                    if cancel.is_set():
                        break
                    job["cancel"] = cancel
                    job.update(state="running", started=time.time(), work_dir=str(Path(root) / job_id))
                try:
                    _run(job_id, job["url"], job["deterministic_only"])
                except Exception:
                    log.exception("batch job %s failed", job_id)
                    with _lock:
                        job.update(state="failed", error=PUBLIC_FAILURE, finished=time.time())
                path = Path(job["work_dir"]) / "target"
                repositories.append({"slug": job["repository"], "local_path": str(path),
                                     "acquisition_status": "available" if job.get("acquired") and path.is_dir() else "unavailable"})
            if cancel.is_set():
                return
            with _lock:
                batch["state"] = "comparing"
            try:
                comparisons = run_comparison(repositories, load_config().similarity_threshold, cancel) if len(repositories) > 1 else []
                with _lock:
                    if not cancel.is_set():
                        batch["cross_validation"] = comparisons
            except EvaluationCancelled:
                pass
            except Exception:
                log.exception("batch pairwise comparison failed")
                with _lock:
                    batch["cross_validation_error"] = "Pairwise checks could not be completed. Individual reports remain available."
            if not cancel.is_set():
                try:
                    with _lock:
                        batch["state"] = "comparing"
                    _run_task_cross_validation(batch)
                except Exception:
                    log.exception("batch task-based cross-validation failed")
                    with _lock:
                        batch["task_cross_validation_error"] = "Task-based peer comparison could not be completed. Individual reports remain available."
    except Exception:
        log.exception("batch execution failed")
        with _lock:
            batch["cross_validation_error"] = "The batch could not finish. Completed reports remain available."
            for job_id in batch["job_ids"]:
                job = _jobs[job_id]
                if job["state"] in {"queued", "running"}:
                    job.update(state="failed", error=PUBLIC_FAILURE, finished=time.time())
    finally:
        with _lock:
            failed = any(_jobs[j]["state"] == "failed" for j in batch["job_ids"])
            finished = time.time()
            final_state = "cancelled" if cancel.is_set() else "done_with_errors" if failed or batch.get("cross_validation_error") or batch.get("task_cross_validation_error") else "done"
            if cancel.is_set():
                for job_id in batch["job_ids"]:
                    if _jobs[job_id]["state"] in {"queued", "running"}:
                        _jobs[job_id].update(state="cancelled", finished=finished)
            for job_id in batch["job_ids"]:
                _jobs[job_id].pop("work_dir", None)
            snapshot = _batch_view(batch)
            snapshot.update(state=final_state, elapsed_s=round(finished - batch["started"], 1))
        try:
            directory = Path(batch["reports_dir"])
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"batch-{batch_id}.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            temporary.replace(path)
        except Exception:
            log.exception("could not persist batch summary %s", batch_id)
            with _lock:
                batch["persistence_error"] = "The batch summary could not be saved. It remains available until the backend restarts."
                final_state = "done_with_errors"
        with _lock:
            batch.update(state=final_state, finished=finished)


class TaskDefinitionInput(BaseModel):
    id: str = Field(default="", max_length=120)
    description: str = Field(min_length=1, max_length=12_000)
    title: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=120)
    requirements: list[str] = Field(default_factory=list, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=100)


class TaskPayload(BaseModel):
    """One task definition, or a set of definitions with optional per-repository assignments."""
    id: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=12_000)
    title: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=120)
    requirements: list[str] = Field(default_factory=list, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    definitions: list[TaskDefinitionInput] = Field(default_factory=list, max_length=100)
    tasks: list[TaskDefinitionInput] = Field(default_factory=list, max_length=100)
    assignments: dict[str, str] = Field(default_factory=dict, max_length=200)
    relevance_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    scoring_weights: Optional[dict[str, float]] = None
    peer_context_weight: Optional[float] = Field(default=None, ge=0.0, le=0.5)
    peer_minimum: Optional[int] = Field(default=None, ge=0, le=100)


class EvaluateRequest(BaseModel):
    url: str
    deterministic_only: bool = False  # skip the model: fast, but can be at best INCOMPLETE_EVALUATION
    task: Optional[TaskPayload] = None


class BatchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    deterministic_only: bool = False
    provider: Literal["configured", "openai", "anthropic"] = "configured"
    task: Optional[TaskPayload] = None


# ------------------------------------------------------------------ application
def create_app(env: Optional[Mapping[str, str]] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Verify once at startup that the configured model exists (in the background: the API must come up
        # even when the model is absent, so deterministic evaluations and saved reports stay available).
        threading.Thread(target=lambda: log.info("configured model ready: %s", llm_ready(0)), daemon=True).start()
        yield

    application = FastAPI(title="ARGUS", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins(env), allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False,
    )

    @application.exception_handler(Exception)
    async def unhandled(request, exc):  # last line of defence: never return a traceback or raw exception text
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal error."})

    @application.get("/health")
    @application.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness only. Deliberately says nothing about the host, paths, model or configuration."""
        return {"status": "ok", "service": "argus"}

    @application.get("/ready")
    @application.get("/api/ready")
    def ready() -> dict[str, Any]:
        """Can ARGUS accept an evaluation right now, and is AI reasoning available?"""
        busy = active_jobs() >= MAX_ACTIVE_JOBS
        ai = llm_ready()
        return {"status": "busy" if busy else "ready", "accepting_evaluations": not busy, "ai_reasoning_available": ai,
                "model": scrub_text(load_config().llm_model)}

    @application.post("/api/evaluate")
    def start(request: EvaluateRequest) -> Any:
        # Public GitHub repositories only, checked against the strict pattern before anything else looks at
        # the value. Local paths, other hosts, credentials, queries and non-https schemes all get one answer.
        source = _public_source(request.url)
        task_payload = _task_payload_dict(request.task)
        if task_payload is not None:
            _task_config_for_request(task_payload)
        with _lock:
            if active_jobs() >= MAX_ACTIVE_JOBS:
                return JSONResponse(status_code=429, content={"detail": PUBLIC_BUSY}, headers={"Retry-After": "60"})
            job_id = uuid.uuid4().hex[:12]
            _jobs[job_id] = {
                "job_id": job_id, "state": "running", "repository": source.slug, "stage_index": 0, "log": [], "started": time.time(),
                "deterministic_only": request.deterministic_only, "task_payload": task_payload,
            }
        threading.Thread(target=_run, args=(job_id, source.url, request.deterministic_only), daemon=True).start()
        return _job_view(_jobs[job_id])

    @application.get("/api/repositories/search")
    def search_repositories(q: str = Query(min_length=2, max_length=120)) -> list[dict[str, Any]]:
        if len(q.strip()) < 2:
            raise HTTPException(status_code=422, detail="Enter at least two search characters.")
        try:
            data = github_get("/search/repositories?" + urlencode({"q": q.strip() + " is:public archived:false", "per_page": 8}), load_config().github_token)
        except Exception:
            raise HTTPException(status_code=503, detail="GitHub search is unavailable or rate-limited. Paste links or use the public test repositories.") from None
        rows = []
        for item in data.get("items", []):
            if item.get("private") is not False or item.get("archived") is True:
                continue
            try:
                source = _public_source(item.get("html_url", ""))
            except HTTPException:
                continue
            rows.append({"repository": source.slug, "url": source.url, "description": scrub_text(item.get("description") or "")[:250],
                         "language": item.get("language"), "stars": item.get("stargazers_count", 0)})
        return rows

    @application.get("/api/batches")
    def list_batches() -> list[dict[str, Any]]:
        rows = {}
        directory = Path(load_config().out_dir)
        for path in sorted(directory.glob("batch-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not re.fullmatch(r"batch-[0-9a-f]{12}\.json", path.name):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("batch_id") != path.stem.removeprefix("batch-") or value.get("state") not in {"done", "done_with_errors", "cancelled"}:
                    continue
                rows[value["batch_id"]] = {k: value.get(k) for k in ("batch_id", "state", "model", "total", "completed")}
            except (OSError, ValueError, AttributeError):
                continue
        with _lock:
            active = [_batch_view(b) for b in _batches.values()]
        for value in reversed(active):
            rows[value["batch_id"]] = {k: value.get(k) for k in ("batch_id", "state", "model", "total", "completed")}
        return list(rows.values())

    @application.post("/api/batches")
    def start_batch(request: BatchRequest) -> Any:
        sources = []
        seen = set()
        for raw in request.urls:
            source = _public_source(raw)
            if source.url.casefold() not in seen:
                seen.add(source.url.casefold())
                sources.append(source)
        with _lock:
            if active_jobs() >= MAX_ACTIVE_JOBS:
                return JSONResponse(status_code=429, content={"detail": PUBLIC_BUSY}, headers={"Retry-After": "60"})
            batch_id = uuid.uuid4().hex[:12]
            cfg = evaluation_config(request.provider)
            task_payload = _task_payload_dict(request.task)
            if task_payload is not None:
                try:
                    _prepare_task_config(cfg, task_payload)
                except Exception as exc:
                    raise HTTPException(status_code=422, detail=f"Task configuration is invalid: {scrub_text(str(exc))[:300]}") from None
            if not request.deterministic_only and request.provider != "configured" and not cfg.llm_api_key:
                raise HTTPException(status_code=422, detail=f"Set the {request.provider} API key in the backend environment first.")
            job_ids = []
            for source in sources:
                job_id = uuid.uuid4().hex[:12]
                job_ids.append(job_id)
                _jobs[job_id] = {"job_id": job_id, "state": "queued", "repository": source.slug, "url": source.url,
                                 "stage_index": 0, "log": [], "started": time.time(), "model": cfg.llm_model if not request.deterministic_only else "disabled (deterministic only)",
                                 "deterministic_only": request.deterministic_only, "provider": request.provider,
                                 "task_payload": task_payload}
            _batches[batch_id] = {"batch_id": batch_id, "state": "running", "job_ids": job_ids, "started": time.time(),
                                  "reports_dir": str(Path(cfg.out_dir).resolve()), "provider": request.provider,
                                  "model": cfg.llm_model if not request.deterministic_only else "disabled (deterministic only)",
                                  "task_payload": task_payload}
        threading.Thread(target=_run_batch, args=(batch_id,), daemon=True).start()
        return _batch_view(_batches[batch_id])

    @application.get("/api/batches/{batch_id}")
    def batch_status(batch_id: str) -> dict[str, Any]:
        batch = _batches.get(batch_id)
        if not batch:
            if re.fullmatch(r"[0-9a-f]{12}", batch_id):
                path = Path(load_config().out_dir) / f"batch-{batch_id}.json"
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    if saved.get("batch_id") == batch_id and saved.get("state") in {"done", "done_with_errors", "cancelled"}:
                        return saved
                except (OSError, ValueError, AttributeError):
                    pass
            raise HTTPException(status_code=404, detail="Unknown batch. Saved reports remain available after a backend restart.")
        return _batch_view(batch)

    @application.post("/api/batches/{batch_id}/stop")
    def stop_batch(batch_id: str) -> dict[str, Any]:
        with _lock:
            batch = _batches.get(batch_id)
            if not batch:
                return batch_status(batch_id)  # completed saved batches are an idempotent no-op
            if batch["state"] in {"running", "comparing", "stopping"}:
                batch.setdefault("cancel", threading.Event()).set()
                batch["state"] = "stopping"
                for job_id in batch["job_ids"]:
                    job = _jobs[job_id]
                    job.setdefault("cancel", batch["cancel"]).set()
                    if job["state"] == "queued":
                        job.update(state="cancelled", finished=time.time())
            return _batch_view(batch)

    @application.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str) -> dict[str, Any]:
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Unknown job.")
            # Stopping a batch member stops its containing queue as well.
            for batch in _batches.values():
                if job_id in batch["job_ids"]:
                    stop_batch(batch["batch_id"])
                    return _job_view(job)
            if job["state"] in {"running", "queued"}:
                job.setdefault("cancel", threading.Event()).set()
            return _job_view(job)

    @application.get("/api/providers")
    def providers() -> list[dict[str, Any]]:
        rows = []
        for choice in ("configured", "openai", "anthropic"):
            cfg = evaluation_config(choice)
            rows.append({"id": choice, "provider": cfg.llm_provider, "model": scrub_text(cfg.llm_model),
                         "configured": bool(cfg.llm_api_key) if cfg.llm_provider in {"openai", "anthropic", "claude"} else True})
        return rows

    @application.get("/api/batches/{batch_id}/statistics")
    def batch_statistics(batch_id: str) -> dict[str, Any]:
        batch = batch_status(batch_id)
        reports = _saved()
        rows = []
        for item in batch["items"]:
            entry = reports.get(item.get("evaluation_id"))
            row = {"repository": item["repository"], "state": item["state"], "available": bool(entry)}
            if entry:
                row.update(report_statistics(entry["result"].model_dump(mode="json")))
                row["similarity_flagged"] = item.get("similarity_flagged", False)
                row["flagged"] = row["flagged"] or row["similarity_flagged"]
            rows.append(row)
        return scrub({"batch_id": batch_id, **cohort_statistics(rows)})

    @application.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job.")
        with _lock:
            return _job_view(job)

    @application.get("/api/evaluations")
    def list_evaluations() -> list[dict[str, Any]]:
        """Completed evaluations this instance still holds, openable without re-running anything."""
        rows = []
        for evaluation_id, entry in _saved().items():
            r: FinalEvaluation = entry["result"]
            name = "/".join(str(x) for x in (r.repository.get("owner"), r.repository.get("name")) if x)
            rows.append({
                "evaluation_id": evaluation_id, "repository": name, "timestamp": r.timestamp, "status": r.completion_status.value,
                "model": r.model.get("model"), "kind": r.repository.get("kind"), "findings": r.definition_of_done.counts.get("open_findings", 0),
            })
        return sorted(rows, key=lambda row: row["timestamp"], reverse=True)

    @application.get("/api/evaluate/{evaluation_id}")
    @application.get("/api/evaluate/{evaluation_id}/json")
    def get_evaluation(evaluation_id: str) -> dict[str, Any]:
        return public_result(_entry(evaluation_id)["result"])

    @application.get("/api/evaluate/{evaluation_id}/report", response_class=PlainTextResponse)
    def get_report(evaluation_id: str) -> PlainTextResponse:
        md_path: Path = _entry(evaluation_id)["md_path"]
        if not md_path.is_file():
            raise HTTPException(status_code=404, detail="Report not available.")
        return PlainTextResponse(scrub_text(md_path.read_text(encoding="utf-8")), media_type="text/markdown; charset=utf-8")

    return application


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host, port = bind_address()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
