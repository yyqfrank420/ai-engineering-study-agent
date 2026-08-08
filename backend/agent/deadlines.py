"""Absolute graph-work deadlines and admission rules."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any

from config import settings


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
        remaining
        - downstream_reserve_s
        - settings.agent_orchestration_reserve_s
    )
    if available <= 0:
        raise StageAdmissionDenied(f"{stage} cannot preserve downstream deadline reserves")
    return min(max_s, available)


def architecture_timeout_seconds(
    state: dict[str, Any],
    *,
    review: bool,
) -> float:
    graph_reserve_s = (
        settings.graph_design_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
        + settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.architecture_role_timeout_s,
        downstream_reserve_s=(
            graph_reserve_s
            if review
            else graph_reserve_s + settings.architecture_role_timeout_s
        ),
        stage="architecture review" if review else "architecture pass",
    )


def design_timeout_seconds(state: dict[str, Any]) -> float:
    downstream_reserve_s = (
        settings.graph_critic_timeout_s
        + settings.graph_patch_timeout_s
        + settings.graph_critic_timeout_s
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


def critic_timeout_seconds(state: dict[str, Any]) -> float:
    downstream_reserve_s = (
        settings.graph_synthesis_timeout_s
        + settings.graph_finalization_reserve_s
    )
    return _stage_timeout(
        state,
        max_s=settings.graph_critic_max_timeout_s,
        downstream_reserve_s=downstream_reserve_s,
        stage="graph critic",
        standalone_s=settings.graph_critic_timeout_s,
    )


def patch_timeout_seconds(state: dict[str, Any]) -> float:
    following_reserve = (
        settings.graph_critic_timeout_s
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
    accepts_kwargs = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters)
    names = {item.name for item in parameters}
    values = {
        "timeout_seconds": max(0.001, timeout_seconds),
        "max_output_tokens": max_output_tokens,
    }
    return {
        name: value
        for name, value in values.items()
        if accepts_kwargs or name in names
    }
