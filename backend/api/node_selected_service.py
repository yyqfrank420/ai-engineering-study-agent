import json
import re

from adapters.llm_adapter import stream_response, stream_response_compat
from config import settings


def format_history_brief(history: list[dict]) -> str:
    if not history:
        return "(no prior conversation)"
    return "; ".join(f"{message['role']}: {message['content'][:100]}" for message in history[-4:])


def build_chip_prompt(node_title: str, node_description: str, history: list[dict]) -> list[dict]:
    return [
        {
            "role": "user",
            "content": (
                f"Node: {node_title}\n"
                f"Description: {node_description}\n"
                f"Recent context: {format_history_brief(history)}\n\n"
                "Generate 3 chips."
            ),
        }
    ]


async def stream_suggested_questions(
    node_title: str,
    node_description: str,
    history: list[dict],
    *,
    telemetry: dict | None = None,
):
    system = (
        'You are a study assistant for "AI Engineering" by Chip Huyen.\n'
        "Generate exactly 3 follow-up exploration chips for a graph node.\n\n"
        "Make the chips feel like useful next actions in the UI.\n"
        "Write the chips in the same language as the recent context when that language is clear.\n"
        "Across the 3 chips, prefer this mix:\n"
        "  1. one chip that asks to explain a part more clearly\n"
        "  2. one chip that asks to expand the graph around this node or nearby area\n"
        "  3. one chip that compares this node with a related concept, step, or trade-off\n\n"
        "Each chip should be either:\n"
        "  (a) A SHORT TOPIC PHRASE — 3-6 words, noun-phrase style. No question mark.\n"
        "  (b) A BRIEF QUESTION — max 9 words total.\n\n"
        "Keep them specific to the node and recent context.\n"
        "It is okay to mention the node name when that makes the action clearer.\n"
        "Return ONLY a JSON array of 3 strings — no other text."
    )

    questions_text = ""
    async for event_type, chunk in stream_response_compat(
        stream_response,
        model=settings.worker_model,
        system=system,
        messages=build_chip_prompt(node_title, node_description, history),
        thinking_budget=None,
        temperature=settings.suggestion_chip_temperature,
        top_p=settings.suggestion_chip_top_p,
        top_k=settings.suggestion_chip_top_k,
        telemetry=telemetry,
    ):
        if event_type == "provider_switch":
            yield {"type": "provider_switch", "provider": chunk}
        elif event_type == "text":
            questions_text += chunk

    try:
        match = re.search(r"\[[\s\S]+?\]", questions_text)
        questions = json.loads(match.group()) if match else []
    except Exception:
        questions = []

    yield {"type": "suggested_questions", "questions": questions[:3]}
    yield {"type": "done"}
