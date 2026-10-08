"""Command line interface: `argus evaluate <github-url-or-local-path>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from argus import __version__
from argus.config import load_config
from argus.models import CompletionStatus, CoverageStatus, EvaluatorError, ModuleStatus
from argus.pipeline import Evaluation
from argus.report import check_written, final_block, validate, write_reports
from argus.status import decide, open_findings

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


def evaluate_one(raw: str, cfg, quiet: bool, provider=None) -> CompletionStatus:
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
    return result.completion_status


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
        cfg = load_config(args.config, overrides=overrides)
    except (FileNotFoundError, ValueError) as exc:
        print(f"argus: configuration error: {exc}", file=sys.stderr)
        return 2
    worst = 0
    for raw in args.repositories:
        try:
            status = evaluate_one(raw, cfg, args.quiet)
        except ValueError as exc:  # invalid repository reference or deadline
            print(f"argus: {exc}", file=sys.stderr)
            return 2
        worst = max(worst, EXIT[status])
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
