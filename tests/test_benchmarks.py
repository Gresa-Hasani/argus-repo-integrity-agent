from dataclasses import replace

import pytest

from argus.benchmarks import BenchmarkOutcome, BenchmarkReference, assess, social_golfer_upper_bound


@pytest.fixture
def ref():
    return BenchmarkReference("social_golfer", "a" * 64, "8x4:max_weeks:no_repeated_pairs", "maximize", 10, "https://www.csplib.org/Problems/prob010/results/", "2026-10-14", True)


def result(ref, value):
    return BenchmarkOutcome(ref.problem, ref.instance_sha256, ref.objective_id, value, "valid", "independent-validator:fixture")


def test_social_golfer_bound_and_allowance(ref):
    assert social_golfer_upper_bound(8, 4) == 10
    assert assess(result(ref, 9), ref).status == "WITHIN_TOLERANCE"
    assert assess(result(ref, 8), ref).status == "OUTSIDE_TOLERANCE"
    assert assess(result(ref, 11), ref).status == "REFERENCE_CONFLICT"


def test_minimization_boundary_without_integer_rounding(ref):
    ref = replace(ref, direction="minimize", value=5)
    assert assess(result(ref, 5), ref).status == "WITHIN_TOLERANCE"
    assert assess(result(ref, 6), ref).status == "OUTSIDE_TOLERANCE"
    ref = replace(ref, value=100)
    assert assess(result(ref, 110), ref).status == "WITHIN_TOLERANCE"
    assert assess(result(ref, 111), ref).status == "OUTSIDE_TOLERANCE"


@pytest.mark.parametrize("field,value", [("problem", "different"), ("instance_sha256", "b" * 64), ("objective_id", "different_weights")])
def test_mismatched_reference_is_unverified(ref, field, value):
    assert assess(replace(result(ref, 10), **{field: value}), ref).status == "UNVERIFIED"


def test_feasibility_not_relaxed(ref):
    assert assess(replace(result(ref, 10), feasibility="invalid"), ref).status == "INVALID"
    assert assess(replace(result(ref, 10), validation_evidence=""), ref).status == "UNVERIFIED"


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1])
def test_invalid_objective_cannot_score(ref, value):
    assert assess(result(ref, value), ref).status == "UNVERIFIED"


def test_zero_reference_has_no_invented_allowance(ref):
    ref = replace(ref, direction="minimize", value=0)
    assert assess(result(ref, 0), ref).status == "WITHIN_TOLERANCE"
    assert assess(result(ref, 1), ref).status == "OUTSIDE_TOLERANCE"


def test_improved_best_known_is_not_claimed_optimal(ref):
    ref = replace(ref, proven_optimal=False)
    a = assess(result(ref, 11), ref)
    assert a.status == "WITHIN_TOLERANCE" and a.improved_reference


@pytest.mark.parametrize("tolerance", [-0.1, 1, float("nan")])
def test_invalid_tolerance(ref, tolerance):
    with pytest.raises(ValueError):
        assess(result(ref, 10), ref, tolerance)
