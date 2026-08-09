from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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

_GRAPH_EDIT_ACTION = re.compile(
    r"\b(?:"
    r"add(?:s|ed|ing)?|adjust(?:s|ed|ing)?|chang(?:e|es|ed|ing)|"
    r"connect(?:s|ed|ing)?|correct(?:s|ed|ing)?|delet(?:e|es|ed|ing)|"
    r"disconnect(?:s|ed|ing)?|edit(?:s|ed|ing)?|expand(?:s|ed|ing)?|"
    r"enhanc(?:e|es|ed|ing)|fix(?:es|ed|ing)?|link(?:s|ed|ing)?|"
    r"moderniz(?:e|es|ed|ing)|modify|modifies|modified|modifying|"
    r"improv(?:e|es|ed|ing)|includ(?:e|es|ed|ing)|"
    r"increas(?:e|es|ed|ing)|mak(?:e|es|ing)|mov(?:e|es|ed|ing)|"
    r"remov(?:e|es|ed|ing)|renam(?:e|es|ed|ing)|"
    r"rebuild(?:s|ing)?|redesign(?:s|ed|ing)?|redraw(?:s|n|ing)?|"
    r"regenerat(?:e|es|ed|ing)|replac(?:e|es|ed|ing)|"
    r"revis(?:e|es|ed|ing)|rework(?:s|ed|ing)?|start\s+over|"
    r"unlink(?:s|ed|ing)?|updat(?:e|es|ed|ing)"
    r")\b"
)
_GRAPH_EDIT_TARGET = re.compile(
    r"\b(?:arrows?|edges?|groups?|lanes?|nodes?|sequences?|"
    r"labels?(?=\s*(?:$|[.!?]))|titles?(?=\s*(?:$|[.!?])))\b"
)
_CURRENT_GRAPH_ARTIFACT = re.compile(
    r"\b(?:the|this|current|existing|original|my|our|whole|entire|complete)\s+"
    r"(?:architectures?|diagrams?|graphs?)"
    r"(?!\s+(?:database|db|index|store)\b)"
)
_GRAPH_ARTIFACT_FIELD = re.compile(
    r"\b(?:diagrams?|graphs?)\s+(?:components?|connections?|labels?|titles?)\b"
)
_NON_MUTATING_QUESTION = re.compile(
    r"^(?:what|when|where|why|how|should|do(?!\s+not\b)|does|is|are|"
    r"can\s+i|could\s+i|would\s+i)\b"
)
_NEW_GRAPH_ACTION = re.compile(
    r"^(?:please\s+)?"
    r"(?:(?:(?:can|could|would)\s+(?:you(?:\s+please)?|we)|"
    r"how\s+would\s+(?:you|we)|let(?:'s|\s+us)|"
    r"i\s+(?:want|need)(?:\s+you)?\s+to|"
    r"i(?:'d|\s+would)\s+like(?:\s+you)?\s+to|help\s+me)\s+)?"
    r"(?:we\s+(?:want|need)\s+to\s+)?"
    r"(?:architect|build|create|design|diagram|draw|implement|map|show|"
    r"visualise|visualize)\b"
    r"(?!\s+(?:patterns?|principles?|theory|tradeoffs?|versus|vs\.?|or\s+buy)\b)"
)
_REPLACEMENT_GRAPH_ACTION = re.compile(r"^(?:please\s+)?(?:rebuild|redesign|replace)\b")
_EMBEDDED_GRAPH_ACTION = re.compile(r"\b(?:diagram|draw|show|visualise|visualize)\w*\b")
_NEGATED_GRAPH_EDIT_CLAUSE = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+not|don't|never|without)\b"
)
_EXPLANATION_REQUEST = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
    r"(?:explain|describe|tell\s+me\s+how)\b"
)
_NON_GRAPH_MUTATION_TARGET = re.compile(
    r"\b(?:answer|citations?|explanation|graph\s+database|react\s+components?|"
    r"subject|topic|training\s+data|tradeoffs?)\b"
)
_TOPIC_SWITCH_REQUEST = re.compile(
    r"^(?:change\s+the\s+(?:subject|topic)|move\s+on|switch\s+to|talk\s+about)\b"
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
        graph_parts.extend(
            [
                str(graph_data.get("title") or ""),
                str(graph_data.get("graph_type") or ""),
            ]
        )
        graph_parts.extend(
            str(node.get("label") or "")
            for node in (graph_data.get("nodes") or [])
            if isinstance(node, dict) and node.get("label")
        )
    parts = [*prior_user_messages[-3:], *graph_parts, message]
    return " ".join(part for part in parts if part).strip() or message


def is_existing_graph_edit_request(query: str, graph_data: dict | None) -> bool:
    """Classify an imperative mutation of the current applied graph."""
    if not isinstance(graph_data, dict) or graph_data.get("design_origin") != "applied":
        return False
    return resolve_graph_operation(query, graph_data) == "edit"


def resolve_graph_operation(
    query: str,
    graph_data: dict | None,
) -> Literal["create", "edit"] | None:
    """Resolve one graph mutation intent before routing or worker selection."""
    text = _routing_intent_text(query)
    if not text:
        return None
    applied_design_requested = is_applied_system_design_request(query)
    clauses = [
        clause.strip()
        for clause in re.split(r"[,;\n]|\b(?:and|but|then)\b", text)
        if clause.strip()
    ]
    authored_terms = tuple(
        term
        for collection in (
            (graph_data or {}).get("nodes") or [],
            (graph_data or {}).get("groups") or [],
        )
        for record in collection
        if isinstance(record, dict)
        for term in (
            str(record.get("label") or "").strip().lower(),
            str(record.get("id") or "").strip().lower().replace("_", " "),
        )
        if len(term) >= 3
    )

    def references_authored_record(clause: str) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", clause)
            for term in authored_terms
        )

    def references_current_design(clause: str) -> bool:
        return bool(
            _CURRENT_GRAPH_ARTIFACT.search(clause)
            or _GRAPH_ARTIFACT_FIELD.search(clause)
            or references_authored_record(clause)
        )

    def requests_graph_design(clause: str) -> bool:
        return bool(
            _NEW_GRAPH_ACTION.search(clause)
            or _REPLACEMENT_GRAPH_ACTION.search(clause)
            or (
                _EMBEDDED_GRAPH_ACTION.search(clause)
                and any(phrase in clause for phrase in _DESIGN_FLOW_PHRASES)
            )
        )

    design_clauses = [clause for clause in clauses if requests_graph_design(clause)]
    new_graph_requested = applied_design_requested and any(
        not references_current_design(clause) for clause in design_clauses
    )
    if (
        _TOPIC_SWITCH_REQUEST.match(text)
        or _NON_MUTATING_QUESTION.match(text)
        or _CONCEPT_QUESTION.match(text)
        or _EXPLANATION_REQUEST.match(text)
    ) and not new_graph_requested:
        return None
    if new_graph_requested:
        return "create"
    if any(references_current_design(clause) for clause in design_clauses):
        return "edit"
    if (
        not isinstance(graph_data, dict)
        and applied_design_requested
        and not any(references_current_design(clause) for clause in clauses)
    ):
        return "create"

    mutation_clauses = [
        clause
        for clause in clauses
        if _GRAPH_EDIT_ACTION.search(clause)
        and not _NEGATED_GRAPH_EDIT_CLAUSE.match(clause)
    ]
    if any(
        references_current_design(clause) or _GRAPH_EDIT_TARGET.search(clause)
        for clause in mutation_clauses
    ):
        return "edit"
    if any(
        not _NON_GRAPH_MUTATION_TARGET.search(clause) for clause in mutation_clauses
    ):
        return "edit"
    return None


def is_new_applied_graph_request(query: str, graph_data: dict | None) -> bool:
    """Require explicit new-artifact intent before replacing an applied graph."""
    return resolve_graph_operation(query, graph_data) == "create"


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
        if term
        not in {
            "the",
            "and",
            "for",
            "with",
            "from",
            "into",
            "artificial",
            "intelligence",
        }
        and term.removesuffix("s") not in product_nouns
        and term not in {"ai", "agentic", "multi-agent"}
    }
    seed_words = re.findall(r"[a-z][a-z0-9-]*", intent_text)
    terse_noun_phrase = len(
        seed_words
    ) <= _DIRECT_PRODUCT_SEED_MAX_WORDS and not re.search(r"[.!?:;]", intent_text)
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
    requested = (
        requested if requested in {"auto", "low", "prototype", "production"} else "auto"
    )
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
