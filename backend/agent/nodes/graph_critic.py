import json
import logging
import re
from typing import Any

from adapters.llm_adapter import build_telemetry
from agent.complexity import is_applied_system_design_request, resolve_complexity
from agent.state import AgentState
from agent.stream_utils import stream_llm
from config import settings


logger = logging.getLogger(__name__)

_EXTERNAL_MUTATION_TERMS = (
    "adjust",
    "apply",
    "charge",
    "delete",
    "deploy",
    "execute",
    "modify",
    "publish",
    "purchase",
    "send",
    "target",
    "transfer",
    "update",
    "write",
)


_GRAPH_CRITIC_SYSTEM = """<role>
You are the independent architecture reviewer in a multi-agent system. You did not create the
diagram. Your job is to reject plausible-looking, generic, or visually confusing diagrams before
the user sees them. When an image is supplied, judge the rendered image—not an imagined layout.
</role>

<review_contract>
Compare the diagram with the user's exact request. Check all of the following:
1. domain specificity: component names and boundaries are particular to this user's system;
2. objective fidelity: the requested goal and constraints materially shape the design;
3. closed-loop completeness: observations, decisions, actions, and measured outcomes connect;
4. safe action boundary: external mutations have policy, approval, audit, or rollback controls;
5. edge semantics: edges say what data or command moves and in which direction;
6. assumption hygiene: important unknowns are explicit instead of invented as facts;
7. selected depth: production designs include failure, observability, and rollout concerns.
8. novice clarity: a newcomer can identify the entry, main path, controls, and outcome without help;
9. logical flow: spatial direction and arrows agree with the described runtime sequence;
10. succinctness: labels are scannable and the canvas is not overloaded;
11. visual readability: no clipping, overlap, illegible text, or ambiguous edge labels;
12. MECE-ish scope: major responsibilities have clear homes without needless duplicates, while
    cross-cutting evaluation, security, and observability may intentionally span components.

Reject a diagram dominated by labels such as Agent, Tool Use, Planning, Evaluation, Generation,
Foundation Model, Memory, or Application. Reject invented retrieval, live data, or vendor details.
Do not reward node count or polished wording when the architecture is not implementable.
</review_contract>

<output_contract>
Return one JSON object and nothing else:
{
  "approved": true,
  "score": 0.0,
  "strengths": ["specific strength"],
  "missing": ["specific missing or weak design element"],
  "revision_instruction": "one precise instruction for the designer; empty when approved"
}
</output_contract>"""


async def graph_critic_node(state: AgentState) -> AgentState:
    graph = state.get("graph_data")
    query = state.get("user_message", "")
    if (
        not graph
        or not state.get("graph_changed")
        or graph.get("design_origin") != "applied"
        or not is_applied_system_design_request(query)
    ):
        return {**state, "graph_review": {"approved": True, "score": 1.0}}

    profile = resolve_complexity(state.get("complexity", "auto"), query)
    await state["send"]({
        "type": "worker_status",
        "worker": "critic",
        "status": "Checking domain coverage, control boundaries, and failure modes…",
    })
    deterministic_review = _deterministic_review(query, graph, profile.resolved)
    render_result: dict[str, Any] = {}
    await_render = state.get("await_diagram_evaluation")
    if deterministic_review.get("approved") and callable(await_render):
        await state["send"]({
            "type": "workflow_progress",
            "phase": "render",
            "status": "active",
            "title": "Rendering the candidate privately",
            "detail": "The diagram stays hidden while the browser checks its real layout.",
        })
        try:
            render_result = await await_render(graph)
        except Exception as exc:
            logger.warning("Browser diagram render unavailable: %s", type(exc).__name__)
            render_result = {"capture_error": "The browser render did not complete."}
        deterministic_review = _merge_reviews(
            deterministic_review,
            _deterministic_render_review(graph, render_result),
        )
    elif deterministic_review.get("approved"):
        deterministic_review = _merge_reviews(
            deterministic_review,
            {
                "approved": False,
                "score": 0.0,
                "strengths": [],
                "missing": ["The browser render quality gate is unavailable on this transport."],
                "revision_instruction": "Use the WebSocket workflow so the actual diagram can be evaluated.",
            },
        )
        deterministic_review["terminal"] = True
    try:
        review_text = (
            f"User request:\n{query}\n\n"
            f"Resolved depth: {profile.resolved}\n\n"
            f"Browser layout report:\n{json.dumps(render_result.get('report') or {}, ensure_ascii=False)}\n\n"
            "Candidate architecture:\n"
            f"{json.dumps(graph, ensure_ascii=False)[:16000]}"
        )
        screenshot = str(render_result.get("screenshot_base64") or "")
        media_type = str(render_result.get("media_type") or "image/jpeg")
        content: str | list[dict[str, Any]] = review_text
        if screenshot:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": screenshot,
                    },
                },
                {"type": "text", "text": review_text},
            ]
        raw = await stream_llm(
            model=settings.orchestrator_model,
            system=_GRAPH_CRITIC_SYSTEM,
            messages=[{"role": "user", "content": content}],
            thinking_budget=(
                min(profile.thinking_budget, settings.graph_critic_thinking_budget_tokens)
                if profile.thinking_budget is not None
                else None
            ),
            temperature=settings.graph_temperature,
            top_p=settings.graph_top_p,
            top_k=settings.graph_top_k,
            effort="medium",
            telemetry=build_telemetry(
                "graph_critic",
                user_id=state.get("user_id"),
                thread_id=state.get("session_id"),
                metadata={
                    "complexity_resolved": profile.resolved,
                    "revision_count": state.get("graph_revision_count", 0),
                    "request_id": state.get("request_id"),
                    "client_request_id": state.get("client_request_id"),
                },
            ),
            send=state.get("send"),
        )
        review = _merge_reviews(deterministic_review, _normalise_review(_parse_json_object(raw)))
        if deterministic_review.get("terminal"):
            review["terminal"] = True
    except Exception as exc:
        # The quality gate must remain available during a provider incident. The
        # local checks are intentionally conservative and never depend on an LLM.
        logger.warning("Model review unavailable; using local gate: %s", type(exc).__name__)
        review = deterministic_review
    await state["send"]({
        "type": "workflow_progress",
        "phase": "review",
        "status": "complete" if review.get("approved") else "retry",
        "title": "Diagram passed the clarity gate" if review.get("approved") else "Diagram needs one focused revision",
        "detail": (
            "The rendered design is ready to publish."
            if review.get("approved")
            else str(review.get("revision_instruction") or "Improving the weakest part before showing it.")[:260]
        ),
    })
    return {**state, "graph_review": review}


def _deterministic_review(query: str, graph: dict[str, Any], resolved_complexity: str) -> dict[str, Any]:
    labels = [str(node.get("label") or "").strip().lower() for node in graph.get("nodes") or []]
    edges = graph.get("edges") or []
    descriptions = " ".join(
        str(value or "").lower()
        for collection in (graph.get("nodes") or [], edges)
        for item in collection
        for value in (item.get("label"), item.get("description"), item.get("technology"))
    )
    generic = {
        "agent", "application", "evaluation", "foundation model", "generation",
        "memory", "planning", "tokenization", "tool use",
    }
    missing: list[str] = []
    if sum(label in generic for label in labels) >= 3:
        missing.append("Replace generic AI taxonomy labels with domain responsibilities.")
    if not any(edge.get("type") == "loop" for edge in edges):
        missing.append("Add the measured outcome feedback edge that closes the runtime loop.")
    if _has_external_mutation(descriptions) and not any(
        term in descriptions
        for term in ("approval", "policy", "guardrail", "rollback", "audit")
    ):
        missing.append("Show the policy, approval, audit, or rollback boundary around external actions.")
    if resolved_complexity == "production" and not any(
        term in descriptions for term in ("observe", "telemetry", "alert", "failure", "retry", "dead letter")
    ):
        missing.append("Add production observability and failure recovery responsibilities.")

    # Require at least one meaningful request noun to survive into the design.
    request_terms = {
        token.strip(".,:;!?()[]{}")
        for token in query.lower().split()
        if len(token.strip(".,:;!?()[]{}")) >= 6
    }
    design_terms = set(descriptions.split()) | {part for label in labels for part in label.split()}
    if request_terms and not request_terms.intersection(design_terms):
        missing.append("Preserve the user's domain vocabulary in component and boundary names.")

    score = max(0.0, 0.92 - (0.22 * len(missing)))
    return {
        "approved": not missing and score >= 0.78,
        "score": score,
        "strengths": ["The diagram passed deterministic structure and control-boundary checks"] if not missing else [],
        "missing": missing,
        "revision_instruction": (
            " ".join(missing) if missing else ""
        ),
    }


def _merge_reviews(local: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    missing = list(dict.fromkeys([*(local.get("missing") or []), *(model.get("missing") or [])]))[:8]
    score = min(float(local.get("score", 0)), float(model.get("score", 0)))
    approved = bool(local.get("approved")) and bool(model.get("approved")) and not missing
    instructions = [
        str(value).strip()
        for value in (local.get("revision_instruction"), model.get("revision_instruction"))
        if str(value or "").strip()
    ]
    return {
        "approved": approved,
        "score": score,
        "strengths": list(dict.fromkeys([*(local.get("strengths") or []), *(model.get("strengths") or [])]))[:8],
        "missing": missing,
        "revision_instruction": " ".join(instructions)[:800],
    }


def _deterministic_render_review(
    graph: dict[str, Any],
    render_result: dict[str, Any],
) -> dict[str, Any]:
    report = render_result.get("report") or {}
    missing: list[str] = []
    if (
        render_result.get("capture_error")
        or report.get("capture_error")
        or not render_result.get("screenshot_base64")
    ):
        missing.append("Render the actual candidate successfully before publication.")
    expected_nodes = len(graph.get("nodes") or [])
    expected_edges = len(graph.get("edges") or [])
    if int(report.get("rendered_nodes") or 0) != expected_nodes:
        missing.append("Ensure every architecture node is visible in the rendered canvas.")
    if int(report.get("overlap_count") or 0) > 0:
        missing.append("Remove overlapping node cards or labels in the rendered layout.")
    if int(report.get("rendered_edges") or 0) != expected_edges:
        missing.append("Ensure every declared edge is visible in the rendered diagram.")
    if int(report.get("clipped_nodes") or 0) > 0:
        missing.append("Fit every node fully inside the initial viewport.")
    if float(report.get("minimum_text_px") or 0) < 6:
        missing.append("Increase the smallest rendered text to a readable size.")
    score = max(0.0, 0.95 - 0.24 * len(missing))
    return {
        "approved": not missing,
        "score": score,
        "strengths": ["The browser render passed deterministic visibility checks"] if not missing else [],
        "missing": missing,
        "revision_instruction": " ".join(missing),
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("critic did not return a JSON object")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("critic payload must be an object")
    return payload


def _normalise_review(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        score = min(1.0, max(0.0, float(payload.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    missing = _clean_list(payload.get("missing"))
    strengths = _clean_list(payload.get("strengths"))
    approved = payload.get("approved") is True and score >= 0.78 and not missing
    revision_instruction = " ".join(str(payload.get("revision_instruction") or "").split())[:800]
    if not approved and not revision_instruction:
        revision_instruction = "Resolve every missing item and make the runtime data/control loop explicit."
    return {
        "approved": approved,
        "score": score,
        "strengths": strengths,
        "missing": missing,
        "revision_instruction": revision_instruction,
    }


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(str(item).split())[:300]
        for item in value[:8]
        if isinstance(item, str) and item.strip()
    ]


def _has_external_mutation(descriptions: str) -> bool:
    return any(
        re.search(rf"\b{re.escape(term)}\w*\b", descriptions) is not None
        for term in _EXTERNAL_MUTATION_TERMS
    )
