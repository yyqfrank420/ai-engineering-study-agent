from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal


PRICE_RELEASE = "2026-08-07"
APPLICATION_PRICES_USD_PER_MILLION = {
    # Keep prior models so saved captures remain account-able after a model change.
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
}
# Anthropic's default ephemeral cache uses a five-minute lifetime.
CACHE_WRITE_5M_INPUT_PRICE_MULTIPLIER = 1.25
CACHE_READ_INPUT_PRICE_MULTIPLIER = 0.10
CostPolicyMode = Literal["blocking", "report-only"]
_MODEL_VERSION_SUFFIX = re.compile(r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class CostPolicy:
    mode: CostPolicyMode = "report-only"
    suite_limit_usd: float | None = None
    case_limit_usd: float | None = None
    baseline_min_runs: int = 5

    def __post_init__(self) -> None:
        if self.mode not in {"blocking", "report-only"}:
            raise ValueError(f"unknown cost policy mode: {self.mode}")
        for value in (self.suite_limit_usd, self.case_limit_usd):
            if value is not None and value < 0:
                raise ValueError("cost limits must be non-negative")
        if self.baseline_min_runs <= 0:
            raise ValueError("baseline_min_runs must be positive")


def _price_for_model(model: str) -> tuple[float, float] | None:
    return next(
        (
            price
            for prefix, price in sorted(
                APPLICATION_PRICES_USD_PER_MILLION.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            )
            if model == prefix
            or (
                model.startswith(prefix)
                and _MODEL_VERSION_SUFFIX.fullmatch(model[len(prefix) :]) is not None
            )
        ),
        None,
    )


def _thread_ids(result: dict[str, Any]) -> set[str]:
    values = [result.get("thread_id")]
    values.extend(result.get("thread_ids") or [])
    values.extend(result.get("attempt_thread_ids") or [])
    for attempt in result.get("attempts") or []:
        if isinstance(attempt, dict):
            values.append(attempt.get("thread_id"))
    return {str(value) for value in values if value}


def _usage_attempts(call: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attempts = call.get("attempts")
    if isinstance(raw_attempts, list) and raw_attempts:
        return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]
    return [
        {
            "attempt": 1,
            "provider": call.get("provider"),
            "model": call.get("model"),
            "status": call.get("status"),
            "input_tokens": call.get("input_tokens"),
            "cache_creation_input_tokens": call.get(
                "cache_creation_input_tokens"
            ),
            "cache_read_input_tokens": call.get("cache_read_input_tokens"),
            "output_tokens": call.get("output_tokens"),
            "queue_wait_ms": call.get("queue_wait_ms"),
        }
    ]


def _empty_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "queue_wait_ms": 0,
        "estimated_usd": 0.0,
    }


def account_application_cost(
    browser_results: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attribute every priced provider attempt to a browser case and operation."""
    case_order = [str(result.get("id") or "unknown") for result in browser_results]
    case_by_thread: dict[str, str] = {}
    errors: list[str] = []
    for result, case_id in zip(browser_results, case_order, strict=True):
        for thread_id in _thread_ids(result):
            previous = case_by_thread.setdefault(thread_id, case_id)
            if previous != case_id:
                errors.append(
                    f"thread {thread_id!r} is attributed to both {previous!r} and {case_id!r}"
                )

    per_case: dict[str, dict[str, Any]] = {
        case_id: {**_empty_usage(), "operations": {}} for case_id in case_order
    }
    attributed_calls = {case_id: 0 for case_id in case_order}
    invalid_cases: set[str] = set()
    invalid_operations: set[tuple[str, str]] = set()
    total = _empty_usage()
    for call_index, call in enumerate(telemetry, start=1):
        thread_id = str(call.get("thread_id") or "")
        case_id = case_by_thread.get(thread_id)
        if case_id is None:
            errors.append(f"application call {call_index} has no browser-case thread attribution")
            continue
        attributed_calls[case_id] += 1
        operation = str(call.get("operation") or "unknown")
        operation_usage = per_case[case_id]["operations"].setdefault(
            operation,
            {**_empty_usage(), "calls": 0, "provider_attempts": 0},
        )
        operation_usage["calls"] += 1

        attempts = _usage_attempts(call)
        if not attempts:
            errors.append(f"application call {call_index} has no usable provider attempts")
            invalid_cases.add(case_id)
            invalid_operations.add((case_id, operation))
            continue
        for attempt_index, attempt in enumerate(attempts, start=1):
            model = str(attempt.get("model") or "")
            price = _price_for_model(model)
            if price is None:
                errors.append(
                    f"application call {call_index} attempt {attempt_index} uses unpriced model {model!r}"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            try:
                input_tokens = int(attempt.get("input_tokens") or 0)
                cache_creation_input_tokens = int(
                    attempt.get("cache_creation_input_tokens") or 0
                )
                cache_read_input_tokens = int(
                    attempt.get("cache_read_input_tokens") or 0
                )
                output_tokens = int(attempt.get("output_tokens") or 0)
                queue_wait_ms = int(attempt.get("queue_wait_ms") or 0)
            except (TypeError, ValueError):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has invalid usage"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if min(
                input_tokens,
                cache_creation_input_tokens,
                cache_read_input_tokens,
                output_tokens,
                queue_wait_ms,
            ) < 0:
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has negative usage"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if (
                cache_creation_input_tokens or cache_read_input_tokens
            ) and not model.startswith("claude-"):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has "
                    f"unsupported prompt-cache pricing for model {model!r}"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            estimated_usd = (
                input_tokens * price[0] / 1_000_000
                + cache_creation_input_tokens
                * price[0]
                * CACHE_WRITE_5M_INPUT_PRICE_MULTIPLIER
                / 1_000_000
                + cache_read_input_tokens
                * price[0]
                * CACHE_READ_INPUT_PRICE_MULTIPLIER
                / 1_000_000
                + output_tokens * price[1] / 1_000_000
            )
            operation_usage["provider_attempts"] += 1
            for target in (operation_usage, per_case[case_id], total):
                target["input_tokens"] += input_tokens
                target["cache_creation_input_tokens"] += cache_creation_input_tokens
                target["cache_read_input_tokens"] += cache_read_input_tokens
                target["output_tokens"] += output_tokens
                target["queue_wait_ms"] += queue_wait_ms
                target["estimated_usd"] += estimated_usd
            status = str(attempt.get("status") or "")
            accepted_with_incomplete_usage = (
                "incomplete_usage" in status
                or (
                    attempt.get("accepted") is True
                    and attempt.get("usage_complete") is False
                )
            )
            if accepted_with_incomplete_usage:
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has "
                    "incomplete usage after provider acceptance"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))

    for result, case_id in zip(browser_results, case_order, strict=True):
        if _thread_ids(result) and attributed_calls[case_id] == 0:
            errors.append(
                f"browser case {case_id!r} has thread attribution but no application telemetry"
            )
            invalid_cases.add(case_id)

    cases = []
    for case_id in case_order:
        usage = per_case[case_id]
        operations = []
        for operation, operation_usage in sorted(usage.pop("operations").items()):
            operation_usage["estimated_usd"] = (
                None
                if (case_id, operation) in invalid_operations
                else round(operation_usage["estimated_usd"], 6)
            )
            operations.append({"operation": operation, **operation_usage})
        usage["estimated_usd"] = (
            None
            if case_id in invalid_cases
            else round(usage["estimated_usd"], 6)
        )
        cases.append({"id": case_id, **usage, "operations": operations})
    total["estimated_usd"] = None if errors else round(total["estimated_usd"], 6)
    return {
        "status": "infrastructure" if errors else "pass",
        "reason": "; ".join(dict.fromkeys(errors)) if errors else None,
        "price_release": PRICE_RELEASE,
        "total": total,
        "cases": cases,
    }


def account_judge_cost(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    cases = []
    total = {"input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0}
    for evaluation in evaluations:
        case_usage = {"input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0}
        for judgment in evaluation.get("judgments") or []:
            case_usage["input_tokens"] += int(judgment.get("input_tokens") or 0)
            case_usage["output_tokens"] += int(judgment.get("output_tokens") or 0)
            case_usage["estimated_usd"] += float(
                judgment.get("estimated_cost_usd") or 0
            )
        case_usage["estimated_usd"] = round(case_usage["estimated_usd"], 6)
        total["input_tokens"] += case_usage["input_tokens"]
        total["output_tokens"] += case_usage["output_tokens"]
        total["estimated_usd"] += case_usage["estimated_usd"]
        cases.append({"id": evaluation["id"], **case_usage})
    total["estimated_usd"] = round(total["estimated_usd"], 6)
    return {"total": total, "cases": cases}


def evaluate_cost_policy(
    application: dict[str, Any],
    policy: CostPolicy = CostPolicy(),
) -> dict[str, Any]:
    """Apply optional rollout limits without hiding accounting failures."""
    if application.get("status") != "pass":
        return {
            "mode": policy.mode,
            "status": "infrastructure",
            "blocking_status": "fail",
            "reason": application.get("reason") or "application cost is unavailable",
            "suite_limit_usd": policy.suite_limit_usd,
            "case_limit_usd": policy.case_limit_usd,
            "baseline_min_runs": policy.baseline_min_runs,
        }

    breaches: list[str] = []
    total_usd = float(application["total"]["estimated_usd"])
    if policy.suite_limit_usd is not None and total_usd > policy.suite_limit_usd:
        breaches.append(
            f"suite cost ${total_usd:.6f} exceeds ${policy.suite_limit_usd:.6f}"
        )
    if policy.case_limit_usd is not None:
        breaches.extend(
            f"case {case['id']} cost ${case['estimated_usd']:.6f} exceeds "
            f"${policy.case_limit_usd:.6f}"
            for case in application["cases"]
            if case["estimated_usd"] > policy.case_limit_usd
        )
    return {
        "mode": policy.mode,
        "status": "over_budget" if breaches else "pass",
        "blocking_status": (
            "fail" if breaches and policy.mode == "blocking" else "pass"
        ),
        "reason": "; ".join(breaches) if breaches else None,
        "suite_limit_usd": policy.suite_limit_usd,
        "case_limit_usd": policy.case_limit_usd,
        "baseline_min_runs": policy.baseline_min_runs,
    }
