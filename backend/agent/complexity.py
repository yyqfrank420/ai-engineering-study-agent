from __future__ import annotations

import re
from dataclasses import dataclass

from config import settings


_DESIGN_PHRASES = (
    "architecture",
    "system design",
    "agent system",
    "multi-agent",
    "service layout",
    "request flow",
)

_DESIGN_VERBS = (
    "architect",
    "build",
    "create",
    "describe",
    "design",
    "diagram",
    "implement",
    "map",
    "show",
)

_SYSTEM_NOUNS = (
    "agent",
    "application",
    "automation",
    "pipeline",
    "platform",
    "service",
    "stack",
    "system",
    "workflow",
)

_AGENT_ACTIONS = (
    "adjust",
    "automate",
    "choose",
    "create",
    "evaluate",
    "generate",
    "manage",
    "maximise",
    "maximize",
    "monitor",
    "optimise",
    "optimize",
    "plan",
    "run",
    "target",
    "write",
)

_PRODUCTION_HINTS = (
    "at scale",
    "compliance",
    "high availability",
    "multi-tenant",
    "production",
    "reliable",
    "security",
    "service level",
    "sla",
)


@dataclass(frozen=True)
class ComplexityProfile:
    requested: str
    resolved: str
    thinking_budget: int | None
    min_graph_nodes: int
    max_graph_nodes: int
    answer_contract: str


def is_applied_system_design_request(query: str) -> bool:
    """Distinguish a requested system design from a book-concept explanation."""
    text = " ".join(query.lower().split())
    if not text:
        return False
    if any(phrase in text for phrase in _DESIGN_PHRASES):
        return True
    if any(re.search(rf"\b{verb}\w*\b", text) for verb in _DESIGN_VERBS) and any(
        re.search(rf"\b{noun}s?\b", text) for noun in _SYSTEM_NOUNS
    ):
        return True
    # A request such as "agent that adjusts bids" describes an applied system;
    # "what is agent planning?" is a concept question. Require an explicit
    # relative/infinitive clause before treating action vocabulary as a design.
    return any(
        re.search(
            rf"\bagents?\b.{{0,40}}\b(?:that|which|to)\b.{{0,30}}\b{re.escape(action)}\w*\b",
            text,
        )
        for action in _AGENT_ACTIONS
    )


def resolve_complexity(requested: str, query: str) -> ComplexityProfile:
    requested = requested if requested in {"auto", "low", "prototype", "production"} else "auto"
    if requested == "auto":
        text = query.lower()
        if any(hint in text for hint in _PRODUCTION_HINTS):
            resolved = "production"
        elif is_applied_system_design_request(query):
            resolved = "prototype"
        else:
            resolved = "low"
    else:
        resolved = requested

    if resolved == "production":
        return ComplexityProfile(
            requested=requested,
            resolved=resolved,
            thinking_budget=settings.production_thinking_budget_tokens,
            # Node count is a bounded readability budget, not a quality score.
            # Production responsibilities may be consolidated differently by
            # domain; the browser render gate decides whether the result fits.
            min_graph_nodes=5,
            max_graph_nodes=8,
            answer_contract=(
                "Production depth: give an implementable design, including component boundaries, "
                "data contracts, the decision/feedback loop, safety controls, approval where "
                "external writes exist, failure "
                "handling, observability, and a staged rollout. Aim for 600-900 useful words when "
                "the request warrants it; density matters more than length."
            ),
        )
    if resolved == "prototype":
        return ComplexityProfile(
            requested=requested,
            resolved=resolved,
            thinking_budget=settings.thinking_budget_tokens,
            min_graph_nodes=5,
            max_graph_nodes=6,
            answer_contract=(
                "Prototype depth: produce a concrete buildable design with responsibilities, key "
                "interfaces, the main data/control loop, important assumptions, and the first "
                "trade-offs to test. Aim for 350-600 useful words when the request warrants it."
            ),
        )
    return ComplexityProfile(
        requested=requested,
        resolved="low",
        thinking_budget=None,
        min_graph_nodes=4,
        max_graph_nodes=5,
        answer_contract=(
            "Low depth: answer directly and concretely. Cover the main design and one important "
            "trade-off without expanding into a production review."
        ),
    )
