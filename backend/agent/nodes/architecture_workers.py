"""Parallel applied-design workers: a primary architect and an adversarial challenger."""

from __future__ import annotations

import json
import logging
from typing import Any

from adapters.llm_adapter import build_telemetry
from agent.architecture_playbook import format_evidence_bundle
from agent.complexity import resolve_complexity
from agent.state import AgentState
from agent.stream_utils import stream_llm
from config import settings


logger = logging.getLogger(__name__)


_ARCHITECT_SYSTEM = """<role>
You are the primary AI systems architect. Produce a compact implementation plan for another
agent to turn into a diagram. Think across the complete supplied review frame, but include a
concern only when it materially affects this scenario.
</role>

<rules>
- Preserve the user's domain nouns and constraints.
- Separate observed inputs, decisions, controlled actions, and measured outcomes.
- Treat book passages as design principles, not claims that the book specifies this product.
- Make unknown integrations and data availability explicit assumptions.
- Prefer the smallest coherent design that meets the selected depth.
- Prefer reusable platform boundaries over one-off AI infrastructure, but keep risky customer
  writes in dedicated contextual confirmation flows rather than a free-form model tool loop.
- Treat every model and prompt as a versioned deployable with regression tests and rollback.
- Do not draw the final graph and do not expose private chain-of-thought.
</rules>

<output_contract>
Return one JSON object and nothing else:
{
  "interpretation": "one sentence",
  "assumptions": ["material assumption"],
  "decisions": [{"area": "checklist area", "decision": "specific choice", "why": "short rationale"}],
  "runtime_flow": ["observable step"],
  "status_update": "one useful, non-sensitive finding to show while the user waits"
}
</output_contract>"""


_CHALLENGER_SYSTEM = """<role>
You are an independent architecture challenger. You receive the same request and evidence as
the architect, but not the architect's answer. Find omissions and failure modes before a graph
is produced. Your job is constructive risk discovery, not an alternative full design.
</role>

<rules>
- Check data/evaluation, security/safety, latency/cost, reliability, deployment/hardware,
  and feedback-loop concerns for material omissions.
- Check whether the design confuses short-term context, curated long-term memory, and the
  authoritative system of record, or gives an AI unsafe direct write access.
- Challenge invented vendors, live data, retrieval, or permissions.
- Distinguish a true requirement from an optional hardening measure.
- Prioritise at most six risks. Do not expose private chain-of-thought.
</rules>

<output_contract>
Return one JSON object and nothing else:
{
  "risks": [{"area": "checklist area", "risk": "concrete failure", "mitigation": "specific response"}],
  "missing_requirements": ["question or assumption that changes the design"],
  "tradeoffs": ["important tension"],
  "status_update": "one useful, non-sensitive risk finding to show while the user waits"
}
</output_contract>"""


async def architect_node(state: AgentState) -> dict[str, Any]:
    if not state.get("is_applied_design", False):
        return {"architect_plan": {}}
    profile = resolve_complexity(state.get("complexity", "auto"), state.get("user_message", ""))
    await _progress(
        state,
        phase="architect",
        status="active",
        title="Architect is shaping the primary design",
        detail="Mapping the runtime loop and the smallest useful boundaries.",
    )
    try:
        raw = await stream_llm(
            model=settings.orchestrator_model,
            system=_ARCHITECT_SYSTEM,
            messages=[{"role": "user", "content": _worker_context(state, profile.answer_contract)}],
            effort="high",
            temperature=settings.graph_temperature,
            top_p=settings.graph_top_p,
            top_k=settings.graph_top_k,
            telemetry=_telemetry(state, "architecture_architect", profile.resolved),
            send=state.get("send"),
        )
        plan = _normalise_architect(_parse_object(raw))
    except Exception as exc:
        logger.warning("Architect role unavailable; continuing from shared evidence: %s", type(exc).__name__)
        plan = {"status_update": "Primary role was unavailable; the integrator will use the shared evidence and risk review."}
    await _progress(
        state,
        phase="architect",
        status="complete",
        title="Primary design direction ready",
        detail=plan.get("status_update") or plan.get("interpretation") or "Core runtime boundaries identified.",
    )
    return {"architect_plan": plan}


async def challenger_node(state: AgentState) -> dict[str, Any]:
    if not state.get("is_applied_design", False):
        return {"challenger_review": {}}
    profile = resolve_complexity(state.get("complexity", "auto"), state.get("user_message", ""))
    await _progress(
        state,
        phase="challenger",
        status="active",
        title="Challenger is testing the weak spots",
        detail="Looking for missing evals, unsafe actions, and production assumptions.",
    )
    try:
        raw = await stream_llm(
            model=settings.orchestrator_model,
            system=_CHALLENGER_SYSTEM,
            messages=[{"role": "user", "content": _worker_context(state, profile.answer_contract)}],
            effort="medium",
            temperature=settings.graph_temperature,
            top_p=settings.graph_top_p,
            top_k=settings.graph_top_k,
            telemetry=_telemetry(state, "architecture_challenger", profile.resolved),
            send=state.get("send"),
        )
        review = _normalise_challenger(_parse_object(raw))
    except Exception as exc:
        logger.warning("Challenger role unavailable; downstream quality gate remains active: %s", type(exc).__name__)
        review = {"status_update": "Risk role was unavailable; the rendered-diagram quality gate remains active."}
    await _progress(
        state,
        phase="challenger",
        status="complete",
        title="Risk review ready",
        detail=review.get("status_update") or "The main omissions and control risks are now explicit.",
    )
    return {"challenger_review": review}


def _worker_context(state: AgentState, answer_contract: str) -> str:
    return (
        f"User request:\n{state.get('user_message', '')}\n\n"
        f"Selected depth:\n{answer_contract}\n\n"
        f"Shared evidence bundle:\n{format_evidence_bundle(state.get('evidence_bundle') or {})}"
    )


def _parse_object(raw: str) -> dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("architecture worker did not return a JSON object")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("architecture worker payload must be an object")
    return value


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _text_list(value: Any, *, count: int, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _text(item, limit)
        for item in value[:count]
        if isinstance(item, str) and _text(item, limit)
    ]


def _normalise_architect(value: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    raw_decisions = value.get("decisions")
    decision_values = raw_decisions if isinstance(raw_decisions, list) else []
    for item in decision_values[:10]:
        if not isinstance(item, dict):
            continue
        decision = _text(item.get("decision"), 300)
        if decision:
            decisions.append({
                "area": _text(item.get("area"), 80),
                "decision": decision,
                "why": _text(item.get("why"), 300),
            })
    return {
        "interpretation": _text(value.get("interpretation"), 400),
        "assumptions": _text_list(value.get("assumptions"), count=8, limit=240),
        "decisions": decisions,
        "runtime_flow": _text_list(value.get("runtime_flow"), count=10, limit=300),
        "status_update": _text(value.get("status_update"), 220),
    }


def _normalise_challenger(value: dict[str, Any]) -> dict[str, Any]:
    risks = []
    raw_risks = value.get("risks")
    risk_values = raw_risks if isinstance(raw_risks, list) else []
    for item in risk_values[:6]:
        if not isinstance(item, dict):
            continue
        risk = _text(item.get("risk"), 300)
        if risk:
            risks.append({
                "area": _text(item.get("area"), 80),
                "risk": risk,
                "mitigation": _text(item.get("mitigation"), 300),
            })
    return {
        "risks": risks,
        "missing_requirements": _text_list(value.get("missing_requirements"), count=6, limit=260),
        "tradeoffs": _text_list(value.get("tradeoffs"), count=6, limit=260),
        "status_update": _text(value.get("status_update"), 220),
    }


def _telemetry(state: AgentState, operation: str, resolved: str) -> dict:
    return build_telemetry(
        operation,
        user_id=state.get("user_id"),
        thread_id=state.get("session_id"),
        metadata={
            "complexity_resolved": resolved,
            "request_id": state.get("request_id"),
            "client_request_id": state.get("client_request_id"),
        },
    )


async def _progress(
    state: AgentState,
    *,
    phase: str,
    status: str,
    title: str,
    detail: str,
) -> None:
    await state["send"]({
        "type": "workflow_progress",
        "phase": phase,
        "status": status,
        "title": title,
        "detail": detail,
    })
