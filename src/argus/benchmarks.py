"""Compare independently validated outcomes with an instance-specific reference.

This module does not execute repository code, validate solutions, or assign grades.
The caller must supply an independent feasibility check and exact benchmark identity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Direction = Literal["minimize", "maximize"]


@dataclass(frozen=True)
class BenchmarkReference:
    problem: str
    instance_sha256: str
    objective_id: str  # includes constraints, weights and objective definition
    direction: Direction
    value: float
    source_url: str
    retrieved_on: str
    proven_optimal: bool = False

    def __post_init__(self) -> None:
        if self.direction not in ("minimize", "maximize"):
            raise ValueError("direction must be minimize or maximize")
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("reference objective must be finite and nonnegative")
        if not self.problem or not self.objective_id or not self.retrieved_on:
            raise ValueError("problem, objective definition and retrieval date are required")
        if len(self.instance_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.instance_sha256):
            raise ValueError("instance identity must be a lowercase SHA-256 digest")
        if not self.source_url.startswith("https://"):
            raise ValueError("a published HTTPS reference source is required")


@dataclass(frozen=True)
class BenchmarkOutcome:
    problem: str
    instance_sha256: str
    objective_id: str
    value: float | None
    feasibility: Literal["valid", "invalid", "unverified"]
    validation_evidence: str = ""


@dataclass(frozen=True)
class BenchmarkAssessment:
    status: Literal["WITHIN_TOLERANCE", "OUTSIDE_TOLERANCE", "INVALID", "UNVERIFIED", "REFERENCE_CONFLICT"]
    reason: str
    acceptable_boundary: float | None = None
    relative_shortfall: float | None = None
    improved_reference: bool = False


def assess(outcome: BenchmarkOutcome, reference: BenchmarkReference, tolerance: float = 0.10) -> BenchmarkAssessment:
    """10% worse than reference is allowed, without relaxing feasibility.

    Minimize: result <= reference * 1.10. Maximize: result >= reference * 0.90.
    A zero reference requires an exact match or improvement; no additive slack
    is invented. Integer results are compared directly, without rounding limits.
    """
    if not math.isfinite(tolerance) or not 0 <= tolerance < 1:
        raise ValueError("tolerance must be finite and in [0, 1)")
    identity = (outcome.problem, outcome.instance_sha256, outcome.objective_id)
    expected = (reference.problem, reference.instance_sha256, reference.objective_id)
    if identity != expected:
        return BenchmarkAssessment("UNVERIFIED", "Problem, instance or objective does not match the reference.")
    if outcome.feasibility == "invalid":
        return BenchmarkAssessment("INVALID", "The solution violates feasibility constraints; tolerance does not apply.")
    if outcome.feasibility != "valid" or not outcome.validation_evidence:
        return BenchmarkAssessment("UNVERIFIED", "Independent feasibility validation evidence is required.")
    value = outcome.value
    if value is None or not math.isfinite(value) or value < 0:
        return BenchmarkAssessment("UNVERIFIED", "A finite nonnegative validated objective is required.")
    minimizing = reference.direction == "minimize"
    improved = value < reference.value if minimizing else value > reference.value
    boundary = reference.value * (1 + tolerance if minimizing else 1 - tolerance)
    delta = value - reference.value if minimizing else reference.value - value
    shortfall = max(0.0, delta) / reference.value if reference.value else None
    if improved and reference.proven_optimal:
        return BenchmarkAssessment("REFERENCE_CONFLICT", "Result improves a proven optimum; review instance, validation and reference.", boundary, shortfall)
    # Avoid binary-float error at the boundary, without introducing scoring slack.
    within = (value <= boundary if minimizing else value >= boundary) or math.isclose(value, boundary, rel_tol=1e-12, abs_tol=0)
    return BenchmarkAssessment(
        "WITHIN_TOLERANCE" if within else "OUTSIDE_TOLERANCE",
        "Validated objective compared with the matching published reference; runtime is assessed separately.",
        boundary, shortfall, improved,
    )


def social_golfer_upper_bound(groups: int, group_size: int) -> int:
    """Each player meets group_size - 1 new players per week."""
    if isinstance(groups, bool) or isinstance(group_size, bool) or not isinstance(groups, int) or not isinstance(group_size, int) or groups < 1 or group_size < 2:
        raise ValueError("groups must be a positive integer and group_size an integer >= 2")
    return (groups * group_size - 1) // (group_size - 1)
