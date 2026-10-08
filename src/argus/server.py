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
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Mapping, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from argus import __version__
from argus.cli import write_validated
from argus.collectors.gitutil import GITHUB_URL_RE, parse_source
from argus.config import load_config
from argus.llm.interface import LLMError, create_provider
from argus.models import FinalEvaluation
from argus.pipeline import Evaluation

log = logging.getLogger("argus.server")

STAGES = ["Repository acquisition", "Evidence collection", "AI reasoning", "Policy evaluation", "Report generation"]
_MARKERS = {"[1/4]": 0, "[2/4]": 1, "[3/4]": 2, "[4/4]": 3}
MAX_ACTIVE_JOBS = 1  # one evaluation at a time: a free host cannot run concurrent model inference
DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

PUBLIC_INVALID_URL = "Enter a public GitHub repository URL in the form https://github.com/<owner>/<repository>."
PUBLIC_BUSY = "ARGUS is currently evaluating another repository. Only one evaluation runs at a time; please try again shortly."
PUBLIC_FAILURE = "The evaluation could not be completed because of an internal error. No partial result was produced."

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
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
    return sum(1 for job in _jobs.values() if job["state"] == "running")


# ------------------------------------------------------------------ job execution
def _run(job_id: str, url: str, deterministic_only: bool) -> None:
    job = _jobs[job_id]

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
        cfg = load_config(overrides={"llm_enabled": False if deterministic_only else None})
        evaluation = Evaluation(url, cfg, None, progress)  # the temporary clone is removed in Evaluation.run()'s finally
        with _lock:
            job["model"] = cfg.llm_model if cfg.llm_enabled else "disabled (deterministic only)"
        result = evaluation.run()
        with _lock:
            job["stage_index"] = 4
            job["log"].append("Writing and validating reports")
        write_validated(result, Path(cfg.out_dir))
        with _lock:
            job.update(state="done", stage_index=5, evaluation_id=result.evaluation_id, finished=time.time())
            job["log"].append(f"Evaluation status: {result.completion_status.value}")
    except Exception:
        # Details stay in the server log. The browser gets a fixed message: no traceback, path or command.
        log.exception("evaluation job %s failed", job_id)
        with _lock:
            job.update(state="failed", error=PUBLIC_FAILURE, finished=time.time())


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"], "state": job["state"], "repository": job["repository"], "model": job.get("model"),
        "stages": STAGES, "stage_index": job["stage_index"], "log": job["log"][-40:], "error": job.get("error"),
        "evaluation_id": job.get("evaluation_id"), "elapsed_s": round((job.get("finished") or time.time()) - job["started"], 1),
        "deterministic_only": job["deterministic_only"],
    }


class EvaluateRequest(BaseModel):
    url: str
    deterministic_only: bool = False  # skip the model: fast, but can be at best INCOMPLETE_EVALUATION


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
        return {"status": "busy" if busy else "ready", "accepting_evaluations": not busy, "ai_reasoning_available": ai}

    @application.post("/api/evaluate")
    def start(request: EvaluateRequest) -> Any:
        raw = request.url.strip()
        # Public GitHub repositories only, checked against the strict pattern before anything else looks at
        # the value. Local paths, other hosts, credentials, queries and non-https schemes all get one answer.
        if len(raw) > 200 or not GITHUB_URL_RE.match(raw):
            raise HTTPException(status_code=422, detail=PUBLIC_INVALID_URL)
        try:
            source = parse_source(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=PUBLIC_INVALID_URL) from None
        with _lock:
            if active_jobs() >= MAX_ACTIVE_JOBS:
                return JSONResponse(status_code=429, content={"detail": PUBLIC_BUSY}, headers={"Retry-After": "60"})
            job_id = uuid.uuid4().hex[:12]
            _jobs[job_id] = {
                "job_id": job_id, "state": "running", "repository": source.slug, "stage_index": 0, "log": [], "started": time.time(),
                "deterministic_only": request.deterministic_only,
            }
        threading.Thread(target=_run, args=(job_id, source.url, request.deterministic_only), daemon=True).start()
        return _job_view(_jobs[job_id])

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
