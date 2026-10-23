"""Command line interface: `argus evaluate <github-url-or-local-path>`."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Optional

from argus import __version__
from argus.config import load_config
from argus.models import CompletionStatus, CoverageStatus, EvaluatorError, FinalEvaluation, ModuleStatus
from argus.pipeline import Evaluation
from argus.report import check_written, final_block, validate, write_reports
from argus.status import decide, open_findings
from argus.task_validation import ScoringConfig, cross_validate_tasks
from argus.tasks import TaskCatalog

EXIT = {
    CompletionStatus.DONE_CLEAN: 0, CompletionStatus.DONE_WITH_FINDINGS: 0, CompletionStatus.FLAGGED: 3,
    CompletionStatus.INCOMPLETE_EVALUATION: 4, CompletionStatus.EVALUATOR_ERROR: 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argus", description="ARGUS - Repository Forensics & Engineering Integrity Agent")
    parser.add_argument("--version", action="version", version=f"argus {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="evaluate one or more repositories")
    ev.add_argument("repositories", nargs="+", help="https://github.com/<owner>/<repo> or a local git directory")
    ev.add_argument("--model", help="logical model name, e.g. Qwen3-8B or Qwen3-4B")
    ev.add_argument("--fallback-model")
    ev.add_argument("--provider", help="LLM provider (default: qwen)")
    ev.add_argument("--backend", choices=["ollama", "openai"], help="local inference runtime protocol")
    ev.add_argument("--base-url", help="runtime URL, e.g. http://localhost:11434")
    ev.add_argument("--config", help="path to an argus.toml file")
    ev.add_argument("--out", help="report directory (default: argus-reports)")
    ev.add_argument("--compare", action="append", default=None, metavar="REPO", help="reference repository for similarity analysis (repeatable)")
    ev.add_argument("--require-similarity", action="store_true", default=None, help="treat missing similarity analysis as a mandatory coverage gap")
    ev.add_argument("--similarity-threshold", type=float)
    ev.add_argument("--deadline", help="submission deadline, ISO-8601 (e.g. 2026-10-01T18:00:00+02:00)")
    ev.add_argument("--task", metavar="DESCRIPTION", help="task description used for task-based profiling and peer comparison")
    ev.add_argument("--task-file", help="JSON or TOML task payload with definitions, assignments or a single task description")
    ev.add_argument("--task-id", help="stable identifier for the configured task")
    ev.add_argument("--task-title", help="human-readable task title")
    ev.add_argument("--task-category", help="task category (for grouping related task descriptions)")
    ev.add_argument("--task-requirement", action="append", default=None, metavar="REQUIREMENT", help="explicit task requirement (repeatable)")
    ev.add_argument("--task-assignment", action="append", default=None, metavar="REPO=TASK", help="assign a repository to a task id (repeatable)")
    ev.add_argument("--task-relevance-threshold", type=float, help="minimum confidence for inferred task identity (default: 0.62)")
    ev.add_argument("--task-similarity-threshold", type=float, help="threshold for merging equivalent task descriptions (default: 0.70)")
    ev.add_argument("--scoring-weight", action="append", default=None, metavar="CRITERION=WEIGHT", help="override an absolute scoring weight (repeatable)")
    ev.add_argument("--peer-context-weight", type=float, help="share of the final score contributed by peer context, 0-0.5 (default: 0.15)")
    ev.add_argument("--peer-minimum", type=int, help="minimum comparable peers before relative context is used (default: 2)")
    ev.add_argument("--no-llm", action="store_true", help="collect deterministic evidence only (result can be at best INCOMPLETE_EVALUATION)")
    ev.add_argument("--no-github-api", action="store_true", help="do not call the GitHub REST API")
    ev.add_argument("--keep-clone", action="store_true", help="keep the temporary clone for inspection")
    ev.add_argument("--quiet", action="store_true")
    return parser


def _say(text: str = "") -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def write_validated(result, out_dir: Path) -> tuple[Path, Path]:
    """Validate the evaluation object, write Markdown + JSON, validate what was written.

    A report that cannot be trusted is an evaluator failure, stated as such in the report itself.
    """
    problems = validate(result)
    if not problems:
        md_path, json_path = write_reports(result, out_dir)
        problems = check_written(result, md_path, json_path)
        if not problems:
            return md_path, json_path
    for i, c in enumerate(result.coverage):
        if c.module == "report_validation":
            result.coverage[i] = CoverageStatus(module=c.module, status=ModuleStatus.FAIL, mandatory=True, detail="; ".join(problems)[:400])
    result.errors.append(EvaluatorError(stage="report_validation", kind="REPORT_INCONSISTENT", message="; ".join(problems)[:800]))
    result.completion_status, result.definition_of_done = decide(result.coverage, result.findings, result.errors)
    return write_reports(result, out_dir)


def _pairs(values: Optional[list[str]], labels: tuple[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"{labels[0]} values must use {labels[1]}=VALUE: {raw!r}")
        key, value = raw.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise ValueError(f"{labels[0]} values must use {labels[1]}=VALUE: {raw!r}")
        result[key] = value
    return result


def _task_file_overrides(path: str) -> dict[str, Any]:
    """Read a JSON/TOML task payload without requiring a new dependency."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if target.suffix.casefold() == ".toml":
        data = tomllib.loads(text)
    else:
        data = json.loads(text)
    if isinstance(data, list):
        return {"task_definitions": data}
    if not isinstance(data, dict):
        raise ValueError("task file must contain an object or a list of task definitions")
    task = data.get("task") if isinstance(data.get("task"), dict) else data
    if not isinstance(task, dict):
        raise ValueError("task file must contain an object or a list of task definitions")
    out: dict[str, Any] = {}
    if "definitions" in task:
        out["task_definitions"] = task["definitions"]
    elif "tasks" in task:
        out["task_definitions"] = task["tasks"]
    elif task.get("description"):
        for source, destination in (("id", "task_id"), ("title", "task_title"), ("category", "task_category"), ("description", "task_description")):
            if source in task:
                out[destination] = str(task[source])
        if "requirements" in task:
            out["task_requirements"] = task["requirements"]
    assignments = task.get("assignments", data.get("assignments"))
    if assignments is not None:
        out["task_assignments"] = assignments
    for source, destination in (
        ("relevance_threshold", "task_relevance_threshold"),
        ("similarity_threshold", "task_similarity_threshold"),
    ):
        if source in task:
            out[destination] = task[source]
    scoring = data.get("scoring") if isinstance(data.get("scoring"), dict) else {}
    weights = scoring.get("weights", scoring.get("criteria"))
    if weights is not None:
        out["scoring_weights"] = weights
    for source, destination in (
        ("peer_context_weight", "peer_context_weight"),
        ("peer_minimum", "peer_minimum"),
        ("task_relevance_threshold", "task_relevance_threshold"),
        ("task_similarity_threshold", "task_similarity_threshold"),
    ):
        if source in scoring:
            out[destination] = scoring[source]
    return out


def _task_overrides(args) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.task_file:
        overrides.update(_task_file_overrides(args.task_file))
    if args.task is not None:
        overrides["task_definitions"] = []
        overrides["task_description"] = args.task
    if args.task_id is not None:
        overrides["task_id"] = args.task_id
    if args.task_title is not None:
        overrides["task_title"] = args.task_title
    if args.task_category is not None:
        overrides["task_category"] = args.task_category
    if args.task_requirement is not None:
        overrides["task_requirements"] = args.task_requirement
    if args.task_assignment is not None:
        overrides["task_assignments"] = _pairs(args.task_assignment, ("task assignment", "REPO"))
    if args.scoring_weight is not None:
        parsed = _pairs(args.scoring_weight, ("scoring weight", "CRITERION"))
        try:
            overrides["scoring_weights"] = {key: float(value) for key, value in parsed.items()}
        except ValueError as exc:
            raise ValueError("scoring weights must be numbers") from exc
    for source, destination in (
        ("task_relevance_threshold", "task_relevance_threshold"),
        ("task_similarity_threshold", "task_similarity_threshold"),
        ("peer_context_weight", "peer_context_weight"),
        ("peer_minimum", "peer_minimum"),
    ):
        value = getattr(args, source)
        if value is not None:
            overrides[destination] = value
    return overrides


def _cohort_summary(results: list[FinalEvaluation], cfg) -> None:
    """After a multi-repository CLI run, compare only task-relevant peers and enrich the reports."""
    profiles = [result.repository_profile for result in results if result.repository_profile is not None]
    catalog = TaskCatalog.from_config(cfg)
    if len(profiles) < 2 or not catalog.configured:
        return
    validation = cross_validate_tasks(
        profiles, catalog, scoring=ScoringConfig.from_config(cfg),
        relevance_threshold=cfg.task_relevance_threshold, task_similarity_threshold=cfg.task_similarity_threshold,
    )
    by_repository = {evaluation.repository: evaluation for evaluation in validation.evaluations}
    for result in results:
        profile = result.repository_profile
        if profile is None:
            continue
        evaluation = by_repository.get(profile.repository)
        if evaluation is None:
            continue
        result.task_evaluation = evaluation
        result.repository_profile = evaluation.profile
        write_validated(result, Path(cfg.out_dir))
    _say("\nTask-based cohort cross-validation")
    _say(f"  {len(validation.evaluations)} repository evaluation(s), {len(validation.groups)} task group(s), "
         f"minimum peers {validation.minimum_peers}")
    for evaluation in validation.evaluations:
        scores = (f"absolute {evaluation.absolute_score:.1f}" if evaluation.absolute_score is not None else "absolute n/a")
        scores += f", relative {evaluation.relative_score:.1f}" if evaluation.relative_score is not None else ", relative n/a"
        scores += f", final {evaluation.final_score:.1f}" if evaluation.final_score is not None else ", final n/a"
        _say(f"  {evaluation.repository}: task={evaluation.task.task_id} [{evaluation.status}] {scores}; "
             f"confidence {evaluation.confidence:.0%} ({evaluation.confidence_level})")


def evaluate_one(raw: str, cfg, quiet: bool, provider=None) -> tuple[CompletionStatus, FinalEvaluation]:
    say = (lambda text="": None) if quiet else _say
    evaluation = Evaluation(raw, cfg, provider, say)
    say(f"ARGUS {__version__}")
    say(f"Repository: {evaluation.source.slug}")
    say(f"Model: {cfg.llm_model} (fallback {cfg.llm_fallback_model}) via {cfg.llm_backend} @ {cfg.llm_base_url}" if cfg.llm_enabled else "Model: disabled (--no-llm)")
    say()
    result = evaluation.run()

    md_path, json_path = write_validated(result, Path(cfg.out_dir))

    done = [c for c in result.coverage if c.status in (ModuleStatus.PASS, ModuleStatus.FAIL)]
    active = open_findings(result.findings)
    say()
    say(f"Modules completed: {len(done)}/{len(result.coverage)} "
        f"(not applicable {sum(c.status == ModuleStatus.NOT_APPLICABLE for c in result.coverage)}, unverifiable {sum(c.status == ModuleStatus.UNVERIFIABLE for c in result.coverage)})")
    say(f"Findings: {len(active)}")
    for f in sorted(active, key=lambda f: -list(type(f.severity)).index(f.severity)):
        say(f"  [{'REVIEW' if f.requires_manual_review else f.severity.value}] {f.finding_id} {f.title}")
    say(f"Manual review required: {'YES' if result.manual_review['required'] else 'NO'}")
    for e in result.errors:
        say(f"Evaluator error: {e.stage} - {e.kind}: {e.message[:200]}")
    for reason in result.definition_of_done.reasons[:8]:
        say(f"  reason: {reason}")
    say()
    _say(final_block(result))
    _say(f"\nReport: {md_path}\nJSON:   {json_path}")
    return result.completion_status, result


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {
        "llm_model": args.model, "llm_fallback_model": args.fallback_model, "llm_provider": args.provider, "llm_backend": args.backend,
        "llm_base_url": args.base_url, "out_dir": args.out, "compare": args.compare, "require_similarity": args.require_similarity,
        "similarity_threshold": args.similarity_threshold, "deadline": args.deadline,
        "llm_enabled": False if args.no_llm else None, "github_api": False if args.no_github_api else None,
        "keep_clone": True if args.keep_clone else None,
    }
    try:
        overrides.update(_task_overrides(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"argus: task configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        cfg = load_config(args.config, overrides=overrides)
        TaskCatalog.from_config(cfg)
        ScoringConfig.from_config(cfg)
    except (FileNotFoundError, ValueError) as exc:
        print(f"argus: configuration error: {exc}", file=sys.stderr)
        return 2
    worst = 0
    results: list[FinalEvaluation] = []
    for raw in args.repositories:
        try:
            status, result = evaluate_one(raw, cfg, args.quiet)
        except ValueError as exc:  # invalid repository reference or deadline
            print(f"argus: {exc}", file=sys.stderr)
            return 2
        worst = max(worst, EXIT[status])
        results.append(result)
    try:
        _cohort_summary(results, cfg)
    except Exception as exc:  # task analysis is auxiliary; individual reports remain valid
        print(f"argus: task cohort cross-validation unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
