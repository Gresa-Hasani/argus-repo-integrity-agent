"""Task-based repository cross-validation and explainable scoring.

Two layers are deliberately kept separate:

* absolute scoring asks how well one repository satisfies its assigned task;
* relative context compares that repository with peers that implement the same task.

Peer context is a small, configurable part of the final score. If too few relevant peers exist,
the relative layer is not computed at all and the absolute score stands on its own. This is a
repository-to-repository comparison, not machine-learning cross-validation: no model is trained and
no train/validation split exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from argus.models import (
    CriterionScore,
    PeerComparison,
    PeerRelevance,
    RepositoryProfile,
    RequirementStatus,
    TaskAssignment,
    TaskCrossValidationResult,
    TaskEvaluationResult,
    TaskGroup,
    confidence_level,
)
from argus.profiling import RepositoryProfiler
from argus.tasks import (
    DEFAULT_RELEVANCE_THRESHOLD,
    DEFAULT_TASK_SIMILARITY_THRESHOLD,
    TASK_SIMILARITY_METHOD,
    TaskCatalog,
    TaskDefinition,
    assign_task,
    group_tasks,
    task_group_for,
    task_similarity,
)

CRITERIA = {
    "task_requirement_fulfillment": "Task requirement fulfilment",
    "functional_completeness": "Functional completeness",
    "code_quality_maintainability": "Code quality and maintainability",
    "testing_quality": "Testing quality",
    "architecture_implementation": "Architecture and implementation choices",
}
DEFAULT_WEIGHTS = {
    "task_requirement_fulfillment": 0.35,
    "functional_completeness": 0.20,
    "code_quality_maintainability": 0.15,
    "testing_quality": 0.15,
    "architecture_implementation": 0.15,
}
_WEIGHT_ALIASES = {
    "requirement_fulfillment": "task_requirement_fulfillment",
    "requirements": "task_requirement_fulfillment",
    "functional": "functional_completeness",
    "completeness": "functional_completeness",
    "code_quality": "code_quality_maintainability",
    "quality": "code_quality_maintainability",
    "maintainability": "code_quality_maintainability",
    "testing": "testing_quality",
    "tests": "testing_quality",
    "architecture": "architecture_implementation",
}

METHOD = (
    "Absolute criteria are computed from deterministic profile evidence with configured weights. "
    "The relative layer uses leave-one-out peer percentiles over comparable repositories assigned to "
    "the same task (or a task merged by semantic equivalence). Peer context never replaces absolute "
    "fulfilment, and is disabled when fewer than the configured minimum peers are available."
)
STATUS_VALUES = {
    RequirementStatus.COVERED: 1.0,
    RequirementStatus.PARTIAL: 0.5,
    RequirementStatus.MISSING: 0.0,
}


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    peer_context_weight: float = 0.15
    minimum_peers: int = 2
    reference_peer_count: int = 3

    def __post_init__(self) -> None:
        unknown = sorted(set(self.weights) - set(CRITERIA))
        if unknown:
            raise ValueError(f"unknown scoring criterion/criteria: {', '.join(unknown)}")
        if not self.weights:
            raise ValueError("at least one scoring weight is required")
        for key, value in self.weights.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"scoring weight {key} must be a finite non-negative number")
        if not any(value > 0 for value in self.weights.values()):
            raise ValueError("at least one scoring weight must be positive")
        if not math.isfinite(self.peer_context_weight) or not 0 <= self.peer_context_weight <= 0.5:
            raise ValueError("peer_context_weight must be finite and in [0, 0.5]")
        if isinstance(self.minimum_peers, bool) or self.minimum_peers < 0:
            raise ValueError("minimum_peers must be a non-negative integer")
        if self.reference_peer_count < 1:
            raise ValueError("reference_peer_count must be positive")

    @classmethod
    def from_config(cls, cfg: Any) -> "ScoringConfig":
        raw = dict(getattr(cfg, "scoring_weights", None) or {})
        weights = dict(DEFAULT_WEIGHTS)
        for key, value in raw.items():
            canonical = _WEIGHT_ALIASES.get(str(key), str(key))
            if canonical not in CRITERIA:
                raise ValueError(f"unknown scoring weight: {key}")
            weights[canonical] = float(value)
        return cls(
            weights=weights,
            peer_context_weight=float(getattr(cfg, "peer_context_weight", 0.15)),
            minimum_peers=int(getattr(cfg, "peer_minimum", 2)),
            reference_peer_count=max(3, int(getattr(cfg, "peer_minimum", 2))),
        )


def _criterion(
    criterion_id: str, score: Optional[float], weight: float, confidence: float,
    explanation: str, evidence: Optional[Iterable[str]] = None, limitations: Optional[Iterable[str]] = None,
) -> CriterionScore:
    return CriterionScore(
        id=criterion_id, label=CRITERIA[criterion_id], kind="absolute",
        score=round(max(0.0, min(100.0, score)), 2) if score is not None else None,
        weight=weight, confidence=max(0.0, min(1.0, confidence)),
        explanation=explanation, evidence=list(dict.fromkeys(evidence or []))[:15],
        limitations=list(dict.fromkeys(limitations or []))[:10],
    )


def _requirement_criterion(profile: RepositoryProfile, weight: float) -> CriterionScore:
    coverage = profile.task_coverage or []
    if not coverage:
        return _criterion(
            "task_requirement_fulfillment", None, weight, profile.confidence,
            "No task requirements were supplied or no requirement could be assessed.",
            limitations=["Requirement fulfilment is not measurable without explicit task requirements."],
        )
    assessed = [item for item in coverage if item.status != RequirementStatus.UNVERIFIED]
    if not assessed:
        return _criterion(
            "task_requirement_fulfillment", None, weight, 0.2,
            f"All {len(coverage)} requirement(s) are UNVERIFIED; no implementation evidence was sufficient to score coverage.",
            evidence=[path for item in coverage for path in item.evidence],
            limitations=["Documentation-only mentions are not counted as requirement coverage."],
        )
    score = sum(item.score for item in assessed) / len(assessed) * 100
    counts = {status.value: sum(1 for item in coverage if item.status == status) for status in RequirementStatus}
    confidence = sum(item.confidence for item in assessed) / len(assessed) * (len(assessed) / len(coverage))
    limitations = []
    if len(assessed) < len(coverage):
        limitations.append(f"{len(coverage) - len(assessed)} requirement(s) were UNVERIFIED and excluded from the mean.")
    return _criterion(
        "task_requirement_fulfillment", score, weight, confidence,
        f"Mean weighted implementation-term coverage across {len(assessed)} assessed requirement(s) is {score:.1f}/100. "
        f"Statuses: {', '.join(f'{key}={value}' for key, value in counts.items() if value)}. "
        "UNVERIFIED requirements are excluded; documentation-only matches never count as coverage.",
        evidence=[path for item in coverage for path in item.evidence],
        limitations=limitations,
    )


def _functional_criterion(profile: RepositoryProfile, weight: float) -> CriterionScore:
    coverage = profile.task_coverage or []
    status_values = [(STATUS_VALUES[item.status], item) for item in coverage if item.status in STATUS_VALUES]
    if not status_values:
        return _criterion(
            "functional_completeness", None, weight, profile.confidence,
            "Functional completeness needs explicit task requirements with at least one assessed requirement.",
            limitations=["No assessed requirement allows a task-grounded completeness score."],
        )
    status_mean = sum(value for value, _ in status_values) / len(status_values)
    depths = [min(1.0, len(item.evidence) / 2.0) for value, item in status_values if value > 0]
    depth_mean = sum(depths) / len(depths) if depths else 0.0
    score = 100 * (0.85 * status_mean + 0.15 * depth_mean)
    confidence = sum(item.confidence for _, item in status_values) / len(status_values) * 0.9
    return _criterion(
        "functional_completeness", score, weight, confidence,
        f"Status completeness is {status_mean:.0%} (COVERED=1, PARTIAL=0.5, MISSING=0) and evidence depth is {depth_mean:.0%} "
        f"(two independent evidence files reach full depth). Formula: 85% status + 15% depth.",
        evidence=[path for item in coverage for path in item.evidence],
        limitations=["Completeness is inferred from static evidence and requirement wording; no feature was executed."],
    )


def _section_criterion(
    criterion_id: str, section: dict[str, Any], weight: float, *, explanation: str,
) -> CriterionScore:
    score = section.get("score")
    confidence = float(section.get("confidence") or 0.0)
    components = section.get("components") or []
    component_text = "; ".join(
        f"{item.get('id')}={item.get('normalized')} (weight {item.get('weight')})"
        for item in components if item.get("normalized") is not None
    )
    limitations = list(section.get("limitations") or [])
    if score is None:
        return _criterion(criterion_id, None, weight, confidence, explanation + " No component was measurable.", limitations=limitations)
    return _criterion(
        criterion_id, float(score) * 100, weight, confidence,
        explanation + (f" Components: {component_text}." if component_text else ""),
        evidence=list(section.get("evidence") or []), limitations=limitations,
    )


def absolute_criteria(profile: RepositoryProfile, scoring: ScoringConfig) -> list[CriterionScore]:
    return [
        _requirement_criterion(profile, scoring.weights.get("task_requirement_fulfillment", 0.0)),
        _functional_criterion(profile, scoring.weights.get("functional_completeness", 0.0)),
        _section_criterion(
            "code_quality_maintainability", profile.quality or {}, scoring.weights.get("code_quality_maintainability", 0.0),
            explanation="Weighted static maintainability indicators; missing indicators are omitted and remaining weights renormalised.",
        ),
        _section_criterion(
            "testing_quality", profile.testing or {}, scoring.weights.get("testing_quality", 0.0),
            explanation="Static test inventory, test/source ratios, CI test execution and coverage configuration.",
        ),
        _section_criterion(
            "architecture_implementation", profile.architecture or {}, scoring.weights.get("architecture_implementation", 0.0),
            explanation="Evidence for coherent architecture patterns, entry points, modularity and configuration; no architectural style is preferred.",
        ),
    ]


def _weighted_absolute(criteria: Sequence[CriterionScore]) -> tuple[Optional[float], float, list[CriterionScore]]:
    available = [item for item in criteria if item.score is not None and item.weight > 0]
    total_weight = sum(item.weight for item in available)
    if not available or total_weight <= 0:
        return None, 0.0, available
    score = sum(float(item.score) * item.weight for item in available) / total_weight
    coverage = total_weight / sum(item.weight for item in criteria if item.weight > 0) if any(item.weight > 0 for item in criteria) else 0.0
    return round(score, 2), round(coverage, 4), available


def _percentile(value: float, peers: Sequence[float]) -> Optional[float]:
    if not peers:
        return None
    below = sum(1 for item in peers if item < value - 1e-9)
    equal = sum(1 for item in peers if abs(item - value) <= 1e-9)
    return round((below + 0.5 * equal) / len(peers), 4)


def _peer_context(
    criteria: Sequence[CriterionScore], peers: Sequence[RepositoryProfile], scoring: ScoringConfig,
) -> tuple[Optional[float], dict[str, float], dict[str, list[float]], dict[str, list[CriterionScore]]]:
    peer_criteria = {peer.repository: absolute_criteria(peer, scoring) for peer in peers}
    peer_values: dict[str, list[float]] = {}
    for rows in peer_criteria.values():
        for row in rows:
            if row.score is not None:
                peer_values.setdefault(row.id, []).append(float(row.score))
    if len(peers) < scoring.minimum_peers:
        return None, {}, peer_values, peer_criteria
    percentiles = {
        row.id: _percentile(float(row.score), peer_values.get(row.id, []))
        for row in criteria if row.score is not None and peer_values.get(row.id)
    }
    percentiles = {key: value for key, value in percentiles.items() if value is not None}
    total = sum(scoring.weights.get(key, 0.0) for key in percentiles)
    relative = (
        round(sum(value * 100 * scoring.weights.get(key, 0.0) for key, value in percentiles.items()) / total, 2)
        if total else None
    )
    return relative, percentiles, peer_values, peer_criteria


def _peer_comparisons(
    target: RepositoryProfile, criteria: Sequence[CriterionScore], peers: Sequence[RepositoryProfile],
    peer_relevance: Sequence[PeerRelevance], peer_criteria: dict[str, list[CriterionScore]],
    percentiles: dict[str, float], peer_values: dict[str, list[float]],
) -> list[PeerComparison]:
    target_by_id = {row.id: row for row in criteria if row.score is not None}
    relevance_by_repo = {row.repository: row for row in peer_relevance}
    rows: list[PeerComparison] = []
    for peer in peers:
        peer_rows = {row.id: row for row in peer_criteria.get(peer.repository, []) if row.score is not None}
        shared = sorted(set(target_by_id) & set(peer_rows))
        deltas = {key: round(float(target_by_id[key].score) - float(peer_rows[key].score), 2) for key in shared}
        strengths = []
        weaknesses = []
        shared_strengths = []
        for key in shared:
            label = CRITERIA[key]
            delta = deltas[key]
            if delta >= 10:
                strengths.append(f"{label}: {delta:+.1f} points versus this peer")
            elif delta <= -10:
                weaknesses.append(f"{label}: {delta:+.1f} points versus this peer")
            if float(target_by_id[key].score) >= 80 and float(peer_rows[key].score) >= 80:
                shared_strengths.append(f"{label}: both repositories score at least 80/100")
        missing = [item.requirement for item in (target.task_coverage or []) if item.status in {RequirementStatus.MISSING, RequirementStatus.PARTIAL}]
        explanation = (
            f"Compared on {len(shared)} measurable criteria. Peer task relevance is "
            f"{relevance_by_repo.get(peer.repository).relevance if peer.repository in relevance_by_repo else 1.0:.0%}. "
            f"Peer profile: {len(peer.features)} inferred feature(s), {peer.testing.get('test_files', 0)} test file(s), "
            f"architecture patterns {peer.architecture.get('patterns') or 'not inferred'}. "
            "Architecture style itself is not scored as better or worse."
        )
        if missing:
            explanation += f" Target requirement gaps: {', '.join(missing[:4])}."
        rows.append(PeerComparison(
            peer=peer.repository,
            relevance=relevance_by_repo.get(peer.repository).relevance if peer.repository in relevance_by_repo else 1.0,
            peer_criteria={key: round(float(peer_rows[key].score), 2) for key in sorted(peer_rows)},
            criterion_deltas=deltas,
            relative_percentiles={
                key: percentiles[key] for key in percentiles
                if key in shared or key in {row.id for row in criteria if row.score is not None}
            },
            strengths=strengths[:8], weaknesses=weaknesses[:8], shared_strengths=shared_strengths[:8],
            explanation=explanation,
        ))
    return rows


def evaluate_repository_task(
    profile: RepositoryProfile,
    assignment: TaskAssignment,
    *,
    peers: Sequence[RepositoryProfile] = (),
    peer_relevance: Sequence[PeerRelevance] = (),
    excluded: Sequence[PeerRelevance] = (),
    scoring: Optional[ScoringConfig] = None,
) -> TaskEvaluationResult:
    scoring = scoring or ScoringConfig()
    limitations: list[str] = list(profile.limitations) + list(assignment.limitations)
    if assignment.relation not in {"EXPLICIT", "SEMANTIC"}:
        return TaskEvaluationResult(
            repository=profile.repository, task=assignment, profile=profile,
            comparable_repositories=[], excluded_repositories=list(excluded),
            criteria=[], peer_comparisons=[],
            missing_requirements=[item.requirement for item in profile.task_coverage if item.status == RequirementStatus.MISSING],
            partial_requirements=[item.requirement for item in profile.task_coverage if item.status == RequirementStatus.PARTIAL],
            strengths=[], weaknesses=[],
            absolute_score=None, relative_score=None, final_score=None,
            score_explanation="Comparative scoring was not performed because task relevance was not established with sufficient confidence.",
            confidence=round(min(profile.confidence, assignment.confidence), 4),
            confidence_level=confidence_level(min(profile.confidence, assignment.confidence)),
            status="TASK_NOT_ESTABLISHED",
            limitations=list(dict.fromkeys(limitations + ["Repository is excluded from task-based comparative scoring."])),
        )

    criteria = absolute_criteria(profile, scoring)
    absolute, criteria_coverage, available = _weighted_absolute(criteria)
    relative = None
    percentiles: dict[str, float] = {}
    peer_values: dict[str, list[float]] = {}
    peer_criteria: dict[str, list[CriterionScore]] = {}
    comparisons: list[PeerComparison] = []
    if peers:
        relative, percentiles, peer_values, peer_criteria = _peer_context(criteria, peers, scoring)
        comparisons = _peer_comparisons(profile, criteria, peers, peer_relevance, peer_criteria, percentiles, peer_values)

    if absolute is None:
        final = None
        status = "INSUFFICIENT_DATA"
        explanation = "No absolute criterion could be measured from the available profile evidence."
    elif relative is not None:
        final = round(absolute * (1 - scoring.peer_context_weight) + relative * scoring.peer_context_weight, 2)
        status = "COMPARED"
        explanation = (
            f"Absolute score {absolute:.1f}/100 is the configured weighted mean of {len(available)} measurable criteria "
            f"({', '.join(f'{item.id}={item.weight:g}' for item in available)}), renormalised over {criteria_coverage:.0%} of configured weight. "
            f"Relative context {relative:.1f}/100 is the leave-one-out peer percentile over {len(peers)} comparable repository/repositories. "
            f"Final score = {absolute:.1f} x (1 - {scoring.peer_context_weight:g}) + {relative:.1f} x {scoring.peer_context_weight:g} = {final:.1f}. "
            "Absolute task fulfilment therefore remains the primary term."
        )
    elif not peers:
        final = absolute
        status = "ABSOLUTE_ONLY"
        explanation = (
            f"Absolute score {absolute:.1f}/100 is the configured weighted mean of measurable criteria. "
            "No comparable peer repository was available, so the final score remains absolute."
        )
        limitations.append("No comparable peer repository was available; relative context is not computed.")
    elif len(peers) < scoring.minimum_peers:
        final = absolute
        status = "INSUFFICIENT_PEERS"
        explanation = (
            f"Absolute score {absolute:.1f}/100 is the configured weighted mean of measurable criteria. "
            f"Relative context was not computed because {len(peers)} comparable peer(s) are below the configured minimum of {scoring.minimum_peers}. "
            "The final score therefore remains absolute, not a penalty for the small cohort."
        )
        limitations.append(f"Only {len(peers)} comparable peer(s); relative scoring requires at least {scoring.minimum_peers}.")
    else:
        final = absolute
        status = "INSUFFICIENT_DATA"
        explanation = (
            f"Absolute score {absolute:.1f}/100 is the configured weighted mean of measurable criteria. "
            f"{len(peers)} comparable peer(s) were available, but no shared measurable criterion allowed a relative percentile. "
            "The final score therefore remains absolute."
        )
        limitations.append("Peer context could not be computed because no criterion was measurable across the target and peers.")

    missing = [f"{item.requirement_id}: {item.requirement}" for item in profile.task_coverage if item.status == RequirementStatus.MISSING]
    partial = [f"{item.requirement_id}: {item.requirement}" for item in profile.task_coverage if item.status == RequirementStatus.PARTIAL]
    strengths = []
    weaknesses = []
    for item in criteria:
        if item.score is None:
            limitations.append(f"{item.label} was not measurable.")
            continue
        if item.score >= 85:
            strengths.append(f"{item.label}: {item.score:.1f}/100. {item.explanation[:240]}")
        elif item.score < 60:
            weaknesses.append(f"{item.label}: {item.score:.1f}/100. {item.explanation[:240]}")
    for item in profile.task_coverage:
        if item.status == RequirementStatus.COVERED:
            strengths.append(f"Requirement implemented: {item.requirement} ({item.explanation})")
        elif item.status in {RequirementStatus.MISSING, RequirementStatus.PARTIAL}:
            weaknesses.append(f"Requirement {item.status.value.lower()}: {item.requirement} ({item.explanation})")
    for comparison in comparisons[:3]:
        strengths.extend(comparison.strengths[:2])
        weaknesses.extend(comparison.weaknesses[:2])
    if relative is None:
        limitations.append("Relative peer context is absent; the confidence score reflects that limitation.")
    if len(peers) < scoring.reference_peer_count:
        limitations.append(f"Fewer than {scoring.reference_peer_count} peers; peer percentiles are sensitive to small samples.")
    limitations.append("Static profile evidence only; no repository code was executed and no test result is claimed.")
    criteria_weight = sum(item.weight for item in criteria if item.score is not None)
    configured_weight = sum(item.weight for item in criteria) or 1.0
    criteria_coverage = criteria_weight / configured_weight
    peer_evidence = min(1.0, len(peers) / max(1, scoring.minimum_peers)) if peers else 0.0
    confidence = round(
        0.40 * profile.confidence + 0.25 * assignment.confidence + 0.20 * peer_evidence + 0.15 * criteria_coverage,
        4,
    )
    return TaskEvaluationResult(
        repository=profile.repository, task=assignment, profile=profile,
        comparable_repositories=list(peer_relevance), excluded_repositories=list(excluded),
        criteria=criteria, peer_comparisons=comparisons,
        missing_requirements=missing, partial_requirements=partial,
        strengths=list(dict.fromkeys(strengths))[:15], weaknesses=list(dict.fromkeys(weaknesses))[:15],
        absolute_score=absolute, relative_score=relative, final_score=final,
        score_explanation=explanation, confidence=confidence, confidence_level=confidence_level(confidence),
        status=status, limitations=list(dict.fromkeys(limitations))[:30],
    )


def _duplicate_indices(profiles: Sequence[RepositoryProfile]) -> dict[int, int]:
    duplicate: dict[int, int] = {}
    for index, profile in enumerate(profiles):
        for earlier in range(index):
            other = profiles[earlier]
            same_repository = profile.repository.casefold() == other.repository.casefold()
            same_content = bool(profile.evidence_fingerprint) and profile.evidence_fingerprint == other.evidence_fingerprint
            if same_repository or same_content:
                duplicate[index] = earlier
                break
    return duplicate


def cross_validate_tasks(
    profiles: Sequence[RepositoryProfile],
    catalog: TaskCatalog,
    *,
    scoring: Optional[ScoringConfig] = None,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    task_similarity_threshold: float = DEFAULT_TASK_SIMILARITY_THRESHOLD,
) -> TaskCrossValidationResult:
    """Select task-relevant peers, compare each repository only with them, and score explainably."""
    scoring = scoring or ScoringConfig()
    profiles = list(profiles)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    limitations: list[str] = []
    if not catalog.configured:
        return TaskCrossValidationResult(
            generated_at=generated_at, method=METHOD,
            task_relevance_threshold=relevance_threshold, task_similarity_threshold=task_similarity_threshold,
            minimum_peers=scoring.minimum_peers, peer_context_weight=scoring.peer_context_weight,
            scoring_weights=dict(scoring.weights), limitations=["No task description was configured; task-based comparison was skipped."],
        )
    if not profiles:
        return TaskCrossValidationResult(
            generated_at=generated_at, method=METHOD,
            task_relevance_threshold=relevance_threshold, task_similarity_threshold=task_similarity_threshold,
            minimum_peers=scoring.minimum_peers, peer_context_weight=scoring.peer_context_weight,
            scoring_weights=dict(scoring.weights), limitations=["No repository profiles were available."],
        )

    groups = group_tasks(catalog.tasks, task_similarity_threshold)
    prepared: list[tuple[RepositoryProfile, TaskAssignment]] = []
    assignments: list[TaskAssignment] = []
    for profile in profiles:
        assignment = assign_task(profile, catalog, relevance_threshold)
        if assignment is None:
            continue
        task = catalog.by_id[assignment.task_id]
        assessed_requirements = [item.requirement for item in profile.task_coverage]
        if profile.task_id != task.id or assessed_requirements != list(task.requirements):
            profile = RepositoryProfiler.assess_task(profile, task)
        prepared.append((profile, assignment))
        assignments.append(assignment)

    duplicates = _duplicate_indices([profile for profile, _ in prepared])
    evaluations: list[TaskEvaluationResult] = []
    for index, (profile, assignment) in enumerate(prepared):
        task = catalog.by_id[assignment.task_id]
        cluster = task_group_for(task.id, groups)
        peer_relevance_rows: list[PeerRelevance] = []
        excluded_rows: list[PeerRelevance] = []
        peers: list[RepositoryProfile] = []
        for peer_index, (peer, peer_assignment) in enumerate(prepared):
            if peer_index == index:
                continue
            # Duplicates never contribute to peer statistics. Keep the first occurrence as the
            # representative and exclude every later copy, including when the target itself is a copy.
            duplicate = peer_index in duplicates or (index in duplicates and duplicates[index] == peer_index)
            peer_task = catalog.by_id[peer_assignment.task_id]
            same_group = bool(cluster and peer_task.id in cluster.task_ids)
            if not same_group:
                relation = "UNCERTAIN" if peer_assignment.relation in {"SEMANTIC", "UNCERTAIN"} else "UNRELATED"
                excluded_rows.append(PeerRelevance(
                    repository=peer.repository, task_id=peer_task.id, relation=relation,
                    relevance=round(task_similarity(task, peer_task)["score"], 4), confidence=peer_assignment.confidence,
                    comparable=False, duplicate=duplicate,
                    reason=f"Task '{peer_task.id}' is not equivalent to target task '{task.id}' at the configured threshold.",
                ))
                continue
            if peer_assignment.relation not in {"EXPLICIT", "SEMANTIC"}:
                excluded_rows.append(PeerRelevance(
                    repository=peer.repository, task_id=peer_task.id, relation="UNCERTAIN",
                    relevance=peer_assignment.relevance, confidence=peer_assignment.confidence,
                    comparable=False, duplicate=duplicate,
                    reason="Peer task relevance was not established with sufficient confidence.",
                ))
                continue
            relevance = 1.0 if peer_task.id == task.id else task_similarity(task, peer_task)["score"]
            row = PeerRelevance(
                repository=peer.repository, task_id=peer_task.id,
                relation="SAME_TASK" if peer_task.id == task.id else "SEMANTIC_EQUIVALENT",
                relevance=round(relevance, 4),
                confidence=round(min(assignment.confidence, peer_assignment.confidence), 4),
                comparable=not duplicate, duplicate=duplicate,
                reason=(
                    "Repository is assigned to the same task." if peer_task.id == task.id
                    else "Task descriptions were merged as semantically equivalent at the configured threshold."
                ) if not duplicate else "Profile duplicates another cohort member; excluded from peer statistics to avoid double counting.",
            )
            if duplicate:
                excluded_rows.append(row)
                continue
            peer_relevance_rows.append(row)
            peers.append(peer)

        if assignment.relation not in {"EXPLICIT", "SEMANTIC"}:
            for row in peer_relevance_rows:
                excluded_rows.append(row.model_copy(update={
                    "relation": "UNCERTAIN", "comparable": False,
                    "reason": "Target task identity was not established; no comparison performed.",
                }))
        evaluations.append(evaluate_repository_task(
            profile, assignment, peers=peers, peer_relevance=peer_relevance_rows,
            excluded=excluded_rows, scoring=scoring,
        ))

    for group in groups:
        group.repositories = sorted({
            profile.repository for profile, assignment in prepared
            if assignment.relation in {"EXPLICIT", "SEMANTIC"} and assignment.task_id in group.task_ids
        })
    if duplicates:
        limitations.append(f"{len(duplicates)} duplicate profile(s) were excluded from peer statistics to avoid double counting.")
    if any(len(group.task_ids) > 1 for group in groups):
        limitations.append("Task definitions were merged only when their deterministic similarity reached the configured threshold.")
    limitations.append(
        "This is repository-to-repository cross-validation, not machine-learning cross-validation: "
        "no model is trained and there are no train/validation folds or leakage of labels."
    )
    limitations.append("Peer percentiles are descriptive context for a small cohort; they are not statistical significance tests.")
    return TaskCrossValidationResult(
        generated_at=generated_at, method=f"{METHOD} Task equivalence method: {TASK_SIMILARITY_METHOD}",
        task_relevance_threshold=relevance_threshold, task_similarity_threshold=task_similarity_threshold,
        minimum_peers=scoring.minimum_peers, peer_context_weight=scoring.peer_context_weight,
        scoring_weights=dict(scoring.weights), groups=groups, evaluations=evaluations,
        assignments=assignments, limitations=limitations,
    )
