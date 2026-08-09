from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
QUALITY_MANIFEST = ROOT / "ci" / "quality.json"


def _live_budgets() -> dict[str, int]:
    manifest = json.loads(QUALITY_MANIFEST.read_text(encoding="utf-8"))
    raw_budgets = manifest["live"]["budgets"]
    budgets = {
        key: int(value)
        for key, value in raw_budgets.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    retry_count = budgets.get("browser_infrastructure_retry_count")
    positive_budgets = {
        key: value
        for key, value in budgets.items()
        if key != "browser_infrastructure_retry_count"
    }
    if (
        len(budgets) != len(raw_budgets)
        or any(value <= 0 for value in positive_budgets.values())
        or retry_count is None
        or retry_count < 0
    ):
        raise ValueError(
            "live evaluation budgets must be positive integers; retry count may be zero"
        )
    return budgets


def application_turn_timeout_seconds() -> int:
    """Return the client-side deadline, including a margin around the agent deadline."""
    return _live_budgets()["application_turn_timeout_seconds"]


def browser_case_concurrency() -> int:
    """Return the number of isolated browser journeys allowed to run at once."""
    return _live_budgets()["browser_case_concurrency"]


def browser_graph_case_concurrency() -> int:
    """Return the number of graph-producing journeys allowed to run at once."""
    return _live_budgets()["browser_graph_case_concurrency"]


def browser_infrastructure_retry_count() -> int:
    """Return additional attempts allowed for infrastructure-only failures."""
    return _live_budgets()["browser_infrastructure_retry_count"]


def browser_suite_timeout_seconds(cases: Iterable[Any]) -> int:
    """Scale the browser deadline with corpus turns while retaining a hard ceiling."""
    budgets = _live_budgets()
    case_list = list(cases)
    case_turn_counts = [len(case.steps) for case in case_list]
    turn_count = sum(case_turn_counts)
    if turn_count <= 0:
        raise ValueError("a browser suite must contain at least one conversation turn")
    aggregate_budget = (
        budgets["browser_suite_base_timeout_seconds"]
        + turn_count * budgets["browser_suite_per_turn_timeout_seconds"]
    )
    longest_case_budget = (
        budgets["browser_suite_base_timeout_seconds"]
        + max(case_turn_counts) * budgets["application_turn_timeout_seconds"]
    )
    graph_turn_count = sum(
        len(case.steps)
        for case in case_list
        if case.deterministic.graph_emitted is True
    )
    graph_lane_count = budgets["browser_graph_case_concurrency"]
    graph_lane_batches = (graph_turn_count + graph_lane_count - 1) // graph_lane_count
    graph_lane_budget = (
        budgets["browser_suite_base_timeout_seconds"]
        + graph_lane_batches * budgets["application_turn_timeout_seconds"]
    )
    return min(
        max(aggregate_budget, longest_case_budget, graph_lane_budget),
        budgets["browser_suite_max_timeout_seconds"],
    )


def semantic_suite_timeout_seconds(suite: str) -> int:
    budgets = _live_budgets()
    if suite in {"pr", "smoke", "diagnostic"}:
        return budgets["semantic_suite_timeout_seconds"]
    return budgets["semantic_full_suite_timeout_seconds"]
