from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Grade = Literal["pass", "borderline", "fail"]
GateStatus = Literal["pass", "fail", "manual_review", "infrastructure"]


@dataclass(frozen=True)
class DimensionJudgment:
    dimension: str
    grade: Grade
    critical: bool
    evidence: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class JudgeResult:
    dimensions: tuple[DimensionJudgment, ...]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class GateDecision:
    status: GateStatus
    reason: str


def _single_judgment_status(result: JudgeResult) -> GateStatus:
    if not result.dimensions:
        return "infrastructure"
    if any(item.grade == "borderline" for item in result.dimensions):
        return "manual_review"
    if any(item.critical and item.grade == "fail" for item in result.dimensions):
        return "fail"
    non_critical = [item for item in result.dimensions if not item.critical]
    if non_critical:
        pass_ratio = sum(item.grade == "pass" for item in non_critical) / len(non_critical)
        if pass_ratio < 0.85:
            return "fail"
    return "pass"


def decide_semantic_gate(
    first: JudgeResult,
    second: JudgeResult | None = None,
    *,
    deterministic_failures: tuple[str, ...] = (),
) -> GateDecision:
    if deterministic_failures:
        return GateDecision("fail", "deterministic invariant failed: " + "; ".join(deterministic_failures))

    first_status = _single_judgment_status(first)
    if first_status == "infrastructure":
        return GateDecision("infrastructure", "judge returned no dimensions")
    if first_status == "manual_review":
        return GateDecision("manual_review", "judge returned a borderline dimension")
    if first_status == "pass":
        return GateDecision("pass", "all critical dimensions passed and at least 85% of non-critical dimensions passed")
    if second is None:
        return GateDecision("infrastructure", "a clear semantic failure requires a second independent judgment")

    second_status = _single_judgment_status(second)
    if second_status == "fail":
        return GateDecision("fail", "two independent judgments found a clear semantic failure")
    if second_status == "infrastructure":
        return GateDecision("infrastructure", "the second judge call returned no dimensions")
    return GateDecision("manual_review", "the two judgments disagreed or the second was borderline")


def calibration_passes(
    expected: list[tuple[str, bool]],
    actual: list[tuple[str, bool]],
) -> tuple[bool, float, int]:
    if not expected or len(expected) != len(actual):
        raise ValueError("calibration labels must be non-empty and aligned")
    agreements = sum(expected_item[0] == actual_item[0] for expected_item, actual_item in zip(expected, actual, strict=True))
    critical_false_passes = sum(
        expected_grade == "fail" and actual_grade == "pass" and expected_critical
        for (expected_grade, expected_critical), (actual_grade, _actual_critical) in zip(expected, actual, strict=True)
    )
    agreement = agreements / len(expected)
    return agreement >= 0.85 and critical_false_passes <= 1, agreement, critical_false_passes


class EvaluationBudget:
    def __init__(self, *, application_calls: int = 64, judge_calls: int = 16) -> None:
        if application_calls <= 0 or judge_calls <= 0:
            raise ValueError("evaluation budgets must be positive")
        self.application_limit = application_calls
        self.judge_limit = judge_calls
        self.application_calls = 0
        self.judge_calls = 0

    def record_application_calls(self, count: int) -> None:
        if count < 0:
            raise ValueError("call count cannot be negative")
        self.application_calls += count
        if self.application_calls > self.application_limit:
            raise RuntimeError(f"application model-call budget exceeded ({self.application_calls}/{self.application_limit})")

    def record_judge_call(self) -> None:
        self.judge_calls += 1
        if self.judge_calls > self.judge_limit:
            raise RuntimeError(f"judge model-call budget exceeded ({self.judge_calls}/{self.judge_limit})")
