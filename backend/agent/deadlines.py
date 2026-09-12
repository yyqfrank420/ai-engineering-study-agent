"""Absolute graph-work deadlines and admission rules."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any, Literal

from config import (
    GRAPH_MAX_CONTRACT_CORRECTIONS,
    GRAPH_MAX_REPAIR_ROUNDS,
    STAGED_COMPONENT_GENERATION_CALLS,
    STAGED_CONNECTION_GENERATION_CALLS,
    settings,
)

MAX_GRAPH_REPAIR_ROUNDS = GRAPH_MAX_REPAIR_ROUNDS


class StageAdmissionDenied(TimeoutError):
    """A stage cannot finish while preserving required downstream reserves."""


class WorkflowDeadlineExceeded(TimeoutError):
    """The workflow cannot safely finish before its terminal target."""


def _remaining_seconds(state: dict[str, Any]) -> float | None:
    deadline = state.get("terminal_deadline_s")
    if not isinstance(deadline, (int, float)):
        return None
    return max(0.0, float(deadline) - time.monotonic())


def _stage_timeout(
    state: dict[str, Any],
    *,
    max_s: float,
    downstream_reserve_s: float,
    stage: str,
    standalone_s: float | None = None,
) -> float:
    remaining = _remaining_seconds(state)
    if remaining is None:
        return max_s if standalone_s is None else standalone_s
    available = (
        remaining - downstream_reserve_s - settings.agent_orchestration_reserve_s
    )
    if available <= 0:
        raise StageAdmissionDenied(
            f"{stage} cannot preserve downstream deadline reserves"
        )
    return min(max_s, available)


def architecture_timeout_seconds(
    state: dict[str, Any],
    *,
    review: bool,
) -> float:
    graph_reserve_s = (
        (0.0 if review else settings.graph_design_timeout_s)
        + settings.graph_critic_timeout_s
        + (MAX_GRAPH_REPAIR_ROUNDS + GRAPH_MAX_CONTRACT_CORRECTIONS)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.architecture_role_timeout_s,
        downstream_reserve_s=graph_reserve_s,
        stage="architecture review" if review else "architecture pass",
    )


def design_timeout_seconds(state: dict[str, Any]) -> float:
    preview_deadline = state.get("graph_preview_deadline_s")
    if (
        isinstance(preview_deadline, (int, float))
        and int(state.get("graph_revision_count", 0)) == 0
    ):
        available = (
            float(preview_deadline)
            - time.monotonic()
            - settings.diagram_evaluation_timeout_s
            - settings.graph_preview_finalization_reserve_s
        )
        if available <= 0:
            raise StageAdmissionDenied(
                "graph design cannot preserve the visible preview deadline"
            )
        return min(settings.graph_preview_design_timeout_s, available)
    downstream_reserve_s = (
        settings.graph_critic_timeout_s
        + (MAX_GRAPH_REPAIR_ROUNDS + GRAPH_MAX_CONTRACT_CORRECTIONS)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.graph_builder_max_timeout_s,
        downstream_reserve_s=downstream_reserve_s,
        stage="graph design",
        standalone_s=settings.graph_design_timeout_s,
    )


def staged_timeout_seconds(
    state: dict[str, Any],
    *,
    phase: Literal["components", "connections"],
    action: Literal["generate", "review"],
    attempt: int,
) -> float:
    if phase not in {"components", "connections"}:
        raise ValueError("phase must be components or connections")
    if action not in {"generate", "review"}:
        raise ValueError("action must be generate or review")
    component_phase = phase == "components"
    generation_calls = (
        STAGED_COMPONENT_GENERATION_CALLS
        if component_phase
        else STAGED_CONNECTION_GENERATION_CALLS
    )
    if (
        not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or not 0 <= attempt < generation_calls
    ):
        raise ValueError("attempt must identify a configured generation call")
    generation_s = (
        settings.staged_component_timeout_s
        if component_phase
        else settings.staged_connection_timeout_s
    )
    remaining_attempts = generation_calls - attempt - 1
    review_reserve_s = (
        settings.diagram_evaluation_timeout_s + settings.staged_gate_timeout_s
    )
    downstream_reserve_s = (
        (review_reserve_s if action == "generate" else 0)
        + remaining_attempts * (generation_s + review_reserve_s)
        + (
            STAGED_CONNECTION_GENERATION_CALLS
            * (settings.staged_connection_timeout_s + review_reserve_s)
            if component_phase
            else 0
        )
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=(
            settings.graph_builder_max_timeout_s
            if action == "generate"
            else settings.graph_critic_max_timeout_s
        ),
        downstream_reserve_s=downstream_reserve_s,
        stage=f"staged {phase} {action}",
        standalone_s=(
            generation_s if action == "generate" else settings.staged_gate_timeout_s
        ),
    )


def critic_timeout_seconds(state: dict[str, Any]) -> float:
    completed_repairs = int(
        state.get("graph_repair_round_count", state.get("graph_revision_count", 0))
    )
    remaining_repairs = max(0, MAX_GRAPH_REPAIR_ROUNDS - completed_repairs)
    correction_pending = bool(state.get("graph_contract_correction_pending"))
    remaining_corrections = (
        max(
            0,
            GRAPH_MAX_CONTRACT_CORRECTIONS
            - int(state.get("graph_contract_correction_count", 0)),
        )
        if remaining_repairs and not correction_pending
        else 0
    )
    downstream_reserve_s = (
        (remaining_repairs + remaining_corrections)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.graph_critic_max_timeout_s,
        downstream_reserve_s=downstream_reserve_s,
        stage="graph critic",
        standalone_s=settings.graph_critic_max_timeout_s,
    )


def patch_timeout_seconds(state: dict[str, Any]) -> float:
    current_repair = int(state.get("graph_revision_count", 1))
    remaining_repairs = max(0, MAX_GRAPH_REPAIR_ROUNDS - current_repair)
    remaining_corrections = max(
        0,
        GRAPH_MAX_CONTRACT_CORRECTIONS
        - int(state.get("graph_contract_correction_count", 0)),
    )
    following_reserve = (
        settings.graph_critic_timeout_s
        + (remaining_repairs + remaining_corrections)
        * (settings.graph_patch_timeout_s + settings.graph_critic_timeout_s)
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.graph_builder_max_timeout_s,
        downstream_reserve_s=following_reserve,
        stage="graph patch",
        standalone_s=settings.graph_patch_timeout_s,
    )


def synthesis_timeout_seconds(state: dict[str, Any]) -> float:
    return _stage_timeout(
        state,
        max_s=settings.graph_synthesis_timeout_s,
        downstream_reserve_s=settings.graph_finalization_reserve_s,
        stage="synthesis",
    )


def optional_gateway_args(
    gateway: Callable[..., Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Pass new gateway controls only when the active callable accepts them."""
    try:
        parameters = inspect.signature(gateway).parameters.values()
    except (TypeError, ValueError):
        return {}
    accepts_kwargs = any(
        item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters
    )
    names = {item.name for item in parameters}
    values = {
        "timeout_seconds": max(0.001, timeout_seconds),
        "max_output_tokens": max_output_tokens,
    }
    return {
        name: value for name, value in values.items() if accepts_kwargs or name in names
    }
