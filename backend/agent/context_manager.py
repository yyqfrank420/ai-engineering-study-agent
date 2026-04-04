# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/context_manager.py
# Purpose: Auto-condense long conversation histories before sending to the LLM.
#          When the total character count of a thread's history exceeds
#          settings.context_condense_threshold_chars, older turns are
#          summarised by Haiku and replaced with a single summary message.
#          The most recent `settings.context_condense_keep_recent` turns are
#          always kept verbatim so the LLM has full context for the current
#          exchange.
#
#          This is a safety valve — it should rarely trigger in normal use.
#          If the Haiku call fails or times out, the function falls back to
#          returning the original history unchanged so the main response is
#          never blocked.
#
# Language: Python
# Connects to: adapters/llm_adapter.py (Haiku streaming call), config.py
# Inputs:  history list[dict] with keys "role" and "content"
# Outputs: history list[dict] (same format, possibly condensed)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import logging

from adapters.llm_adapter import stream_response
from config import settings

logger = logging.getLogger(__name__)

# How long to wait for Haiku to produce the summary before giving up
_CONDENSE_TIMEOUT_S = 5.0


async def _call_haiku_summary(old_text: str) -> str:
    """
    Ask Haiku to produce a 2-3 sentence summary of `old_text`.

    Collects the full streamed response into a single string.
    Raises on any error so the caller can fall back gracefully.
    """
    system = (
        "<role>You are a concise summariser for an AI study assistant.</role>"
        "<task>Summarise older chat history so later turns keep the right context.</task>"
        "<rules>"
        "Write 2-3 sentences. Keep only the key concepts discussed, decisions made, "
        "open questions, and any graph or architecture topic the user is currently exploring. "
        "Be factual. Do not invent citations or details. Do not add advice that was not said."
        "</rules>"
    )
    messages = [{"role": "user", "content": f"Summarise this conversation:\n\n{old_text}"}]

    tokens: list[str] = []
    async for event_type, content in stream_response(
        model=settings.worker_model,
        system=system,
        messages=messages,
        temperature=settings.condense_temperature,
        top_p=settings.condense_top_p,
        top_k=settings.condense_top_k,
        telemetry={"operation": "context_condense"},
    ):
        if event_type == "text":
            tokens.append(content)
    return "".join(tokens).strip()


async def maybe_condense_history(
    history: list[dict],
    threshold_chars: int | None = None,
    keep_recent: int | None = None,
) -> list[dict]:
    """
    Conditionally condense a conversation history.

    Decision tree:
        total_chars ≤ threshold  →  return history unchanged
        total_chars > threshold  →  summarise old turns with Haiku (5s timeout)
                                     success: return [summary_msg] + recent turns
                                     failure: log warning, return original history

    Args:
        history:         Full conversation history as [{"role": ..., "content": ...}]
        threshold_chars: Char count above which condensing is triggered.
                         Defaults to settings.context_condense_threshold_chars.
        keep_recent:     Number of most-recent turns to keep verbatim.
                         Defaults to settings.context_condense_keep_recent.

    Returns:
        Condensed (or original) history in the same list-of-dict format.
    """
    if not history:
        return history

    threshold = threshold_chars if threshold_chars is not None else settings.context_condense_threshold_chars
    keep = keep_recent if keep_recent is not None else settings.context_condense_keep_recent

    total_chars = sum(len(m.get("content", "")) for m in history)
    if total_chars <= threshold:
        return history

    # Split: old turns to summarise + recent turns to keep verbatim
    if len(history) <= keep:
        # Not enough turns to split — nothing useful to condense
        return history

    old_turns = history[:-keep]
    recent_turns = history[-keep:]

    old_text = "\n".join(f"{m['role']}: {m['content']}" for m in old_turns)

    logger.info(
        "context_manager: condensing %d old turns (%d chars total) for thread context",
        len(old_turns), total_chars,
    )

    try:
        summary = await asyncio.wait_for(
            _call_haiku_summary(old_text),
            timeout=_CONDENSE_TIMEOUT_S,
        )
        condensed: list[dict] = [
            {"role": "assistant", "content": f"[Context summary of earlier conversation: {summary}]"}
        ]
        return condensed + recent_turns

    except Exception:
        logger.warning(
            "context_manager: condense failed (timeout or Haiku error) — using full history",
            exc_info=True,
        )
        return history
