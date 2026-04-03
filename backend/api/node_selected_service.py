import json
import re

from adapters.llm_adapter import stream_response
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


async def stream_suggested_questions(node_title: str, node_description: str, history: list[dict]):
    system = (
        'You are a study assistant for "AI Engineering" by Chip Huyen.\n'
        "Generate exactly 3 follow-up exploration chips for a graph node.\n\n"
        "Each chip is either:\n"
        "  (a) A SHORT TOPIC PHRASE — 3-5 words, noun-phrase style. No question mark.\n"
        "      Good: \"Authentication in Production\", \"Fine-tuning vs RAG\", \"Latency Tradeoffs\"\n"
        "      Bad:  \"How does authentication work in a production AI system?\"\n\n"
        "  (b) A BRIEF QUESTION starting with 'Can' — max 8 words total.\n"
        "      Good: \"Can RAG replace fine-tuning?\", \"Can Claude self-evaluate?\"\n"
        "      Bad:  \"Can you explain how RAG compares to fine-tuning in terms of performance?\"\n\n"
        "Mix both types. Keep them specific to the node. Avoid repeating the node name.\n"
        "Return ONLY a JSON array of 3 strings — no other text."
    )

    questions_text = ""
    async for event_type, chunk in stream_response(
        model=settings.worker_model,
        system=system,
        messages=build_chip_prompt(node_title, node_description, history),
        thinking_budget=None,
        temperature=settings.suggestion_chip_temperature,
        top_p=settings.suggestion_chip_top_p,
        top_k=settings.suggestion_chip_top_k,
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
