"""Completion-state rules and the Definition-of-Done validator. Pure functions, no I/O."""

from __future__ import annotations

from argus.models import (
    Category,
    CompletionStatus,
    CoverageStatus,
    DefinitionOfDone,
    EvaluatorError,
    Finding,
    FindingStatus,
    FindingType,
    ModuleStatus,
    Severity,
)

MODULES = [
    "repository_access", "repository_identity", "repository_metadata", "scc_analysis", "source_classification",
    "contributors", "identity_normalization", "authorship", "coauthorship", "commit_quality", "commit_granularity",
    "commit_inflation", "loc_analysis", "loc_inflation", "contribution_integrity", "timeline", "branches", "merges",
    "pull_requests", "github_actions", "actions_consistency", "repository_structure", "gitignore",
    "environment_hygiene", "secret_scan", "dependency_hygiene", "readme_crosscheck", "ai_assistance_signals",
    "code_provenance", "similarity_analysis", "cross_agent_handoffs", "report_generation", "report_validation",
]

# Checks whose evidence lives outside the Git repository; unverifiable here degrades but does not void the evaluation.
OPTIONAL_MODULES = {"repository_metadata", "pull_requests", "github_actions"}
SIMILARITY_MODULES = {"code_provenance", "similarity_analysis"}


def is_mandatory(module: str, require_similarity: bool) -> bool:
    if module in SIMILARITY_MODULES:
        return require_similarity
    return module not in OPTIONAL_MODULES


def open_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.status in (FindingStatus.OPEN, FindingStatus.UNVERIFIABLE)]


def decide(
    coverage: list[CoverageStatus], findings: list[Finding], errors: list[EvaluatorError]
) -> tuple[CompletionStatus, DefinitionOfDone]:
    by_module = {c.module: c for c in coverage}
    missing = [m for m in MODULES if m not in by_module]
    active = open_findings(findings)
    material = [f for f in active if f.is_material]
    manual = [f for f in active if f.requires_manual_review]
    non_info = [f for f in active if not f.is_material]  # weaknesses and non-material anomalies; observations are never findings
    mandatory_gaps = [c for c in coverage if c.mandatory and c.status == ModuleStatus.UNVERIFIABLE]
    optional_gaps = [c for c in coverage if not c.mandatory and c.status == ModuleStatus.UNVERIFIABLE]
    failed = [c for c in coverage if c.status == ModuleStatus.FAIL]

    reasons: list[str] = []
    if errors:
        status = CompletionStatus.EVALUATOR_ERROR
        reasons += [f"evaluator error in {e.stage}: {e.kind}" for e in errors]
    elif missing:
        status = CompletionStatus.EVALUATOR_ERROR
        reasons.append(f"modules not accounted for: {', '.join(missing)}")
    elif mandatory_gaps:
        status = CompletionStatus.INCOMPLETE_EVALUATION
    elif material:
        status = CompletionStatus.FLAGGED
    elif non_info or failed or optional_gaps:
        status = CompletionStatus.DONE_WITH_FINDINGS
    else:
        status = CompletionStatus.DONE_CLEAN

    reasons += [f"mandatory check unverifiable: {c.module} ({c.detail})" for c in mandatory_gaps]
    reasons += [f"unresolved material finding: {f.finding_id} [{f.severity.value}] {f.title}" for f in material]
    if status == CompletionStatus.DONE_WITH_FINDINGS:
        reasons += [f"non-material finding: {f.finding_id} [{f.severity.value}] {f.title}" for f in non_info]
        reasons += [f"optional check unverifiable: {c.module} ({c.detail})" for c in optional_gaps]

    counts = {
        "required_checks": sum(1 for c in coverage if c.status != ModuleStatus.NOT_APPLICABLE),
        "completed_checks": sum(1 for c in coverage if c.status in (ModuleStatus.PASS, ModuleStatus.FAIL)),
        "not_applicable": sum(1 for c in coverage if c.status == ModuleStatus.NOT_APPLICABLE),
        "unverifiable": sum(1 for c in coverage if c.status == ModuleStatus.UNVERIFIABLE),
        "failed_checks": len(failed),
        "critical_findings": sum(1 for f in active if f.severity == Severity.CRITICAL),
        "high_findings": sum(1 for f in active if f.severity == Severity.HIGH),
        "integrity_flags": len(material),
        "manual_review_requirements": len(manual),
        "evaluator_errors": len(errors),
        "mandatory_coverage_gaps": len(mandatory_gaps),
        "open_findings": len(active),
        "engineering_weaknesses": sum(1 for f in active if f.finding_type == FindingType.ENGINEERING_WEAKNESS),
        "integrity_findings": sum(1 for f in active if f.finding_type != FindingType.ENGINEERING_WEAKNESS and f.category != Category.SECRET_EXPOSURE),
        "security_findings": sum(1 for f in active if f.category == Category.SECRET_EXPOSURE),
    }
    # DONE_WITH_FINDINGS still satisfies the Definition of Done: the pipeline completed and nothing material is open.
    satisfied = status in (CompletionStatus.DONE_CLEAN, CompletionStatus.DONE_WITH_FINDINGS)
    return status, DefinitionOfDone(satisfied=satisfied, reasons=reasons, counts=counts)
