"""Typed data contracts shared by the deterministic layer, the LLM layer and the reports."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_RANK = {s: i for i, s in enumerate(Severity)}


class ModuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNVERIFIABLE = "UNVERIFIABLE"


class CompletionStatus(str, Enum):
    DONE_CLEAN = "DONE_CLEAN"
    DONE_WITH_FINDINGS = "DONE_WITH_FINDINGS"
    FLAGGED = "FLAGGED"
    INCOMPLETE_EVALUATION = "INCOMPLETE_EVALUATION"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"


class Lifecycle(str, Enum):
    OBSERVED = "OBSERVED"
    CORROBORATED = "CORROBORATED"
    ASSESSED = "ASSESSED"
    RESOLVED = "RESOLVED"


class Outcome(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    UNVERIFIABLE = "UNVERIFIABLE"
    FAIL = "FAIL"


class FindingType(str, Enum):
    """FACT -> OBSERVATION -> ENGINEERING WEAKNESS -> ANOMALY -> MATERIAL INTEGRITY CONCERN.

    Assigned by the deterministic policy layer, never by the model. NORMAL and OBSERVATION are not
    findings: NORMAL candidates are discarded, OBSERVATIONs are reported as repository observations.
    """

    NORMAL = "NORMAL"
    OBSERVATION = "OBSERVATION"
    ENGINEERING_WEAKNESS = "ENGINEERING_WEAKNESS"
    ANOMALY = "ANOMALY"
    MATERIAL_INTEGRITY_CONCERN = "MATERIAL_INTEGRITY_CONCERN"


FINDING_TYPES = (FindingType.ENGINEERING_WEAKNESS, FindingType.ANOMALY, FindingType.MATERIAL_INTEGRITY_CONCERN)


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNVERIFIABLE = "UNVERIFIABLE"


class Category(str, Enum):
    REPOSITORY_ACCESS = "REPOSITORY_ACCESS"
    COMMIT_INTEGRITY = "COMMIT_INTEGRITY"
    CONTRIBUTION_INTEGRITY = "CONTRIBUTION_INTEGRITY"
    COAUTHOR_INTEGRITY = "COAUTHOR_INTEGRITY"
    LOC_INFLATION = "LOC_INFLATION"
    COMMIT_INFLATION = "COMMIT_INFLATION"
    CODE_PROVENANCE = "CODE_PROVENANCE"
    SIMILARITY = "SIMILARITY"
    AI_ASSISTANCE = "AI_ASSISTANCE"
    BRANCH_WORKFLOW = "BRANCH_WORKFLOW"
    CI_CD = "CI_CD"
    REPOSITORY_HYGIENE = "REPOSITORY_HYGIENE"
    SECRET_EXPOSURE = "SECRET_EXPOSURE"
    README_MISMATCH = "README_MISMATCH"
    TIMELINE_ANOMALY = "TIMELINE_ANOMALY"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"


def _enum_token(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().upper().replace("-", "_").replace(" ", "_")
    return value


_CONFIDENCE_WORDS = {"LOW": 0.3, "MEDIUM": 0.6, "MODERATE": 0.6, "HIGH": 0.9}


def confidence_level(value: float) -> str:
    return "HIGH" if value >= 0.75 else "MEDIUM" if value >= 0.45 else "LOW"


class Evidence(BaseModel):
    """One deterministic, addressable fact (or derived metric). The only thing findings may cite."""

    id: str
    type: str
    source: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class Anomaly(BaseModel):
    """A deterministic pattern that warrants investigation. Never an accusation by itself."""

    id: str
    category: Category
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity_hint: Severity = Severity.LOW
    material: bool = False
    possible_explanations: list[str] = Field(default_factory=list)
    lifecycle: Lifecycle = Lifecycle.OBSERVED
    resolution: Optional[str] = None
    resolved_by: Optional[str] = None
    # A model's explanation for a MATERIAL anomaly is advisory only: it never removes the review requirement.
    proposed_explanation: Optional[str] = None
    proposed_by: Optional[str] = None


class Finding(BaseModel):
    """An engineering weakness, anomaly or material integrity concern. Ordinary facts are not findings."""

    finding_id: str
    finding_type: FindingType
    category: Category
    severity: Severity
    title: str
    finding: str
    material: bool = False
    requires_manual_review: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    deterministic_basis: list[str] = Field(default_factory=list)  # why this finding is allowed to exist
    reasoning: str = ""  # deterministic interpretation
    llm_reasoning: str = ""  # advisory interpretation from the model
    llm_reasoning_removed: list[str] = Field(default_factory=list)  # reason codes for model sentences dropped as contradictory
    text_origin: Optional[str] = None  # "deterministic" since the statement stopped coming from the model; None in older reports
    possible_explanations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_level: str = "MEDIUM"
    origin: str = "deterministic"  # "deterministic" | "llm" (who proposed it; the policy layer always decides)
    source_step: str = ""
    lifecycle: Lifecycle = Lifecycle.ASSESSED
    outcome: Outcome = Outcome.REVIEW
    status: FindingStatus = FindingStatus.OPEN

    @property
    def is_material(self) -> bool:
        return self.material and self.status in (FindingStatus.OPEN, FindingStatus.UNVERIFIABLE)


class Observation(BaseModel):
    """A plain repository fact worth showing to a reviewer. Never counted as a finding."""

    id: str
    topic: str
    text: str
    source: str = "deterministic"  # "deterministic" | "llm"
    evidence_ids: list[str] = Field(default_factory=list)


class CandidateDecision(BaseModel):
    """Audit record: what the model proposed and what the deterministic policy did with it."""

    candidate_id: str
    step: str
    title: str
    claim: str = ""
    model_reasoning: str = ""
    proposed_category: str
    proposed_severity: str
    proposed_manual_review: bool
    evidence_ids: list[str] = Field(default_factory=list)
    decision: str  # ACCEPTED | MERGED | OBSERVATION | DISCARDED
    finding_type: FindingType
    reason: str
    finding_id: Optional[str] = None


# --- What the model is allowed to return -------------------------------------------------------


class LLMFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3)
    category: Category
    severity: Severity
    finding: str = Field(min_length=3)
    reasoning: str = Field(min_length=3)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_manual_review: bool = False
    possible_explanations: list[str] = Field(default_factory=list)

    _norm_category = field_validator("category", "severity", mode="before")(_enum_token)

    @field_validator("confidence", mode="before")
    @classmethod
    def _norm_confidence(cls, value: Any) -> Any:
        if isinstance(value, str):
            word = value.strip().upper()
            if word in _CONFIDENCE_WORDS:
                return _CONFIDENCE_WORDS[word]
        return value


class AnomalyResolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    anomaly_id: str
    explanation: str = Field(min_length=20)


class AnalysisResult(BaseModel):
    """Structured output of one specialised reasoning step."""

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=3)
    findings: list[LLMFinding] = Field(default_factory=list)
    resolved_anomalies: list[AnomalyResolution] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    classification: Optional[str] = None


class NarrativeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = Field(min_length=20)


# --- Evaluation-level records ------------------------------------------------------------------


class CoverageStatus(BaseModel):
    module: str
    status: ModuleStatus
    mandatory: bool = True
    detail: str = ""


class ManualReviewRequirement(BaseModel):
    finding_id: str
    category: Category
    reason: str


class EvaluatorError(BaseModel):
    stage: str
    kind: str
    message: str


class IntegrityAssessment(BaseModel):
    summary: str = ""
    summary_origin: str = "not_produced"  # "llm" | "not_produced"
    open_material_concerns: int = 0
    anomalies_detected: int = 0
    anomalies_resolved: int = 0
    anomalies_escalated: int = 0
    manual_review_required: bool = False


class DefinitionOfDone(BaseModel):
    satisfied: bool
    reasons: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class RequirementStatus(str, Enum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


class RequirementAssessment(BaseModel):
    """A task requirement checked against implementation evidence, never against README prose alone."""

    requirement_id: str
    requirement: str
    status: RequirementStatus
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    explanation: str = ""
    limitations: list[str] = Field(default_factory=list)


class RepositoryProfile(BaseModel):
    """Normalised, deterministic description of what a repository contains and implements."""

    profile_version: str = "1.0"
    repository: str
    task_id: Optional[str] = None
    task_category: Optional[str] = None
    generated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    languages: list[dict[str, Any]] = Field(default_factory=list)
    technologies: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)
    architecture: dict[str, Any] = Field(default_factory=dict)
    features: list[dict[str, Any]] = Field(default_factory=list)
    task_coverage: list[RequirementAssessment] = Field(default_factory=list)
    task_coverage_score: Optional[float] = None
    testing: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    documentation: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_level: str = "LOW"
    evidence_fingerprint: Optional[str] = None
    evidence_index: dict[str, Any] = Field(default_factory=dict)
    evidence_sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaskAssignment(BaseModel):
    """How a repository was associated with a task, and how strongly that association is supported."""

    task_id: str
    title: str = ""
    category: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    relation: str = "EXPLICIT"  # EXPLICIT | SEMANTIC | UNCERTAIN | UNRELATED
    relevance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    method: str = "configured"
    explanation: str = ""
    corroboration: Optional[float] = None
    limitations: list[str] = Field(default_factory=list)


class PeerRelevance(BaseModel):
    repository: str
    task_id: Optional[str] = None
    relation: str = "SAME_TASK"  # SAME_TASK | SEMANTIC_EQUIVALENT | UNCERTAIN | UNRELATED | DUPLICATE
    relevance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    comparable: bool = False
    duplicate: bool = False
    reason: str = ""


class CriterionScore(BaseModel):
    id: str
    label: str
    kind: str = "absolute"  # absolute | relative_context
    score: Optional[float] = None  # 0..100; None means not measurable from available evidence
    weight: float = 0.0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PeerComparison(BaseModel):
    peer: str
    relevance: float = Field(ge=0.0, le=1.0)
    peer_criteria: dict[str, float] = Field(default_factory=dict)
    criterion_deltas: dict[str, float] = Field(default_factory=dict)
    relative_percentiles: dict[str, float] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    shared_strengths: list[str] = Field(default_factory=list)
    explanation: str = ""


class TaskEvaluationResult(BaseModel):
    repository: str
    task: TaskAssignment
    profile: RepositoryProfile
    comparable_repositories: list[PeerRelevance] = Field(default_factory=list)
    excluded_repositories: list[PeerRelevance] = Field(default_factory=list)
    criteria: list[CriterionScore] = Field(default_factory=list)
    peer_comparisons: list[PeerComparison] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    partial_requirements: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    absolute_score: Optional[float] = None
    relative_score: Optional[float] = None
    final_score: Optional[float] = None
    score_explanation: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_level: str = "LOW"
    status: str = "ABSOLUTE_ONLY"
    limitations: list[str] = Field(default_factory=list)


class TaskGroup(BaseModel):
    task_id: str
    task_ids: list[str] = Field(default_factory=list)
    title: str = ""
    category: str = ""
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    pair_similarities: list[dict[str, Any]] = Field(default_factory=list)


class TaskCrossValidationResult(BaseModel):
    generated_at: str
    method: str
    task_relevance_threshold: float
    task_similarity_threshold: float
    minimum_peers: int
    peer_context_weight: float
    scoring_weights: dict[str, float] = Field(default_factory=dict)
    groups: list[TaskGroup] = Field(default_factory=list)
    evaluations: list[TaskEvaluationResult] = Field(default_factory=list)
    assignments: list[TaskAssignment] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FinalEvaluation(BaseModel):
    agent: dict[str, str]
    evaluation_id: str
    timestamp: str
    repository: dict[str, Any]
    model: dict[str, Any]
    coverage: list[CoverageStatus]
    deterministic_metrics: dict[str, Any]
    llm_analyses: dict[str, Any]
    anomalies: list[Anomaly]
    observations: list[Observation]
    findings: list[Finding]
    candidate_decisions: list[CandidateDecision]
    evidence: list[Evidence]
    integrity_assessment: IntegrityAssessment
    handoffs: list[dict[str, Any]]
    manual_review: dict[str, Any]
    unverifiable_items: list[str]
    errors: list[EvaluatorError]
    executive_summary: dict[str, Any]
    completion_status: CompletionStatus
    definition_of_done: DefinitionOfDone
    # Optional layers keep reports written before task profiling loadable.
    repository_profile: Optional[RepositoryProfile] = None
    task_evaluation: Optional[TaskEvaluationResult] = None
    profiling_error: Optional[str] = None
