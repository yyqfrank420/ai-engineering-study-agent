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

_DESIGN_FLOW_PHRASES = (
    "control flow",
    "data flow",
    "execution flow",
    "request flow",
    "runtime flow",
    "system flow",
)

_DESIGN_VERBS = (
    "architect",
    "build",
    "create",
    "describe",
    "design",
    "diagram",
    "draw",
    "implement",
    "map",
    "show",
    "visualise",
    "visualize",
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

_DIRECT_PRODUCT_NOUNS = (
    "agent",
    "assistant",
    "automation",
    "bot",
    "chatbot",
    "copilot",
    "engine",
    "pipeline",
    "platform",
    "recommender",
    "service",
    "system",
    "workflow",
)

_CONCEPT_QUESTION = re.compile(
    r"^(?:what\s+(?:is|are)|how\s+(?:do|does|is|are)|why\b|"
    r"explain\b|define\b|compare\b|difference\s+between\b)",
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
    "self-improving",
    "self improving",
    "service level",
    "sla",
)

_DESIGN_FOLLOWUP_PHRASES = (
    "add each",
    "add nodes",
    "all agents",
    "expand",
    "go deeper",
    "more detail",
    "show all",
    "sub-agent",
    "subagent",
)

_OUTER_UNTRUSTED_EXPLANATION = re.compile(
    r"^(?:please\s+)?treat\b"
    r"(?=.{0,160}\b(?:quoted|untrusted)\b)"
    r"(?=.{0,160}\b(?:explain|analy[sz]e|summari[sz]e|interpret)\b)",
)

_DIRECT_PRODUCT_SEED_MAX_WORDS = 12


@dataclass(frozen=True)
class ComplexityProfile:
    requested: str
    resolved: str
    thinking_budget: int | None
    answer_contract: str


def _routing_intent_text(query: str) -> str:
    """Remove quoted data so its vocabulary cannot select an application route."""
    text = " ".join(query.lower().split())
    visible: list[str] = []
    quote = ""
    escaped = False
    for index, character in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue

        starts_single_quote = character == "'" and (
            index == 0 or not text[index - 1].isalnum()
        )
        if character in {'"', "`"} or starts_single_quote:
            quote = character
            visible.append(" ")
            continue
        visible.append(character)
    return " ".join("".join(visible).split())


def resolve_design_query(
    user_message: str,
    history: list[dict] | None = None,
    graph_data: dict | None = None,
) -> str:
    """Restore design context for terse graph follow-ups without inventing requirements."""
    message = " ".join(user_message.split())
    if not any(phrase in message.lower() for phrase in _DESIGN_FOLLOWUP_PHRASES):
        return message

    prior_user_messages = [
        " ".join(str(turn.get("content") or "").split())
        for turn in (history or [])[-8:]
        if turn.get("role") == "user" and turn.get("content")
    ]
    graph_parts: list[str] = []
    if graph_data:
        graph_parts.extend([
            str(graph_data.get("title") or ""),
            str(graph_data.get("graph_type") or ""),
        ])
        graph_parts.extend(
            str(node.get("label") or "")
            for node in (graph_data.get("nodes") or [])
            if isinstance(node, dict) and node.get("label")
        )
    parts = [*prior_user_messages[-3:], *graph_parts, message]
    return " ".join(part for part in parts if part).strip() or message


def is_applied_system_design_request(query: str) -> bool:
    """Distinguish a requested system design from a book-concept explanation."""
    text = " ".join(query.lower().split())
    intent_text = _routing_intent_text(text)
    if not intent_text:
        return False
    design_verb_present = any(
        re.search(rf"\b{verb}\w*\b", intent_text) for verb in _DESIGN_VERBS
    )
    # Explicit concept questions stay explanatory even when they contain a
    # product noun such as "agent" or "pipeline". "How to build ..." and
    # other direct design requests continue into the applied-design path.
    if (
        _CONCEPT_QUESTION.match(intent_text)
        or _OUTER_UNTRUSTED_EXPLANATION.match(intent_text)
    ) and not design_verb_present:
        return False
    # A concept explanation can also contain an explicit request for its
    # implementable process diagram ("Explain RAG and draw the runtime flow").
    # Require both a visual-design verb and a flow target so ordinary questions
    # such as "What is control flow?" remain explanatory.
    if design_verb_present and any(
        phrase in intent_text for phrase in _DESIGN_FLOW_PHRASES
    ):
        return True
    if any(phrase in intent_text for phrase in _DESIGN_PHRASES):
        return True
    if re.search(
        r"\b(?:self[- ]improving|autonomous|automated)\b.{0,50}\b(?:ai|agent|platform|system|workflow)\b",
        intent_text,
    ):
        return True
    if re.search(
        r"\b(?:ai|agentic)\s+(?:platform|system|workflow)\b.{0,30}\b(?:for|that|to)\b",
        intent_text,
    ):
        return True
    if design_verb_present and any(
        re.search(rf"\b{noun}s?\b", text) for noun in _SYSTEM_NOUNS
    ):
        return True
    # Product-name seeds are a primary UI workflow: users often type only a
    # domain plus the thing they want built ("customer support chatbot").
    # Require at least one non-scaffolding term so bare "AI assistant" and
    # "agent" remain ambiguous rather than silently inventing a product.
    product_nouns = {
        noun
        for noun in _DIRECT_PRODUCT_NOUNS
        if re.search(rf"\b{re.escape(noun)}s?\b", intent_text)
    }
    meaningful_terms = {
        term
        for term in re.findall(r"[a-z][a-z0-9-]{2,}", intent_text)
        if term not in {"the", "and", "for", "with", "from", "into", "artificial", "intelligence"}
        and term.removesuffix("s") not in product_nouns
        and term not in {"ai", "agentic", "multi-agent"}
    }
    seed_words = re.findall(r"[a-z][a-z0-9-]*", intent_text)
    terse_noun_phrase = (
        len(seed_words) <= _DIRECT_PRODUCT_SEED_MAX_WORDS
        and not re.search(r"[.!?:;]", intent_text)
    )
    if terse_noun_phrase and product_nouns and meaningful_terms:
        return True
    # A request such as "agent that adjusts bids" describes an applied system;
    # "what is agent planning?" is a concept question. Require an explicit
    # relative/infinitive clause before treating action vocabulary as a design.
    return any(
        re.search(
            rf"\bagents?\b.{{0,40}}\b(?:that|which|to)\b.{{0,30}}\b{re.escape(action)}\w*\b",
            intent_text,
        )
        for action in _AGENT_ACTIONS
    )


def resolve_complexity(requested: str, query: str) -> ComplexityProfile:
    requested = requested if requested in {"auto", "low", "prototype", "production"} else "auto"
    if requested == "auto":
        text = _routing_intent_text(query)
        explanatory_flow = (
            bool(_CONCEPT_QUESTION.match(text))
            and any(phrase in text for phrase in _DESIGN_FLOW_PHRASES)
            and not any(hint in text for hint in _PRODUCTION_HINTS)
        )
        if is_applied_system_design_request(query) and explanatory_flow:
            # A concept walkthrough can need an applied runtime diagram without
            # implicitly requesting every production-hardening guarantee.
            resolved = "prototype"
        elif is_applied_system_design_request(query):
            # The default architecture experience targets an implementation-
            # ready system map. Users can still explicitly choose prototype.
            resolved = "production"
        elif any(hint in text for hint in _PRODUCTION_HINTS):
            resolved = "production"
        else:
            resolved = "low"
    else:
        resolved = requested

    if resolved == "production":
        return ComplexityProfile(
            requested=requested,
            resolved=resolved,
            thinking_budget=settings.production_thinking_budget_tokens,
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
        answer_contract=(
            "Low depth: answer the user's actual question directly and concisely. For an explanation "
            "or safety lesson, stop after the requested concept and necessary evidence; do not add "
            "an unrequested architecture, operations plan, or rollout. For an actual design request, "
            "cover the main design and one important trade-off without a production review."
        ),
    )
