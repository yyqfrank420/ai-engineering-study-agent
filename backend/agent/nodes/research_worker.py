# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/research_worker.py
# Purpose: Phase 1a research worker — queries DuckDuckGo for real-world context
#          on the user's topic and returns a formatted bullet list.
#
#          Runs in parallel with rag_worker. Its output (research_context) is
#          injected into the graph_worker and orchestrator_synthesise prompts
#          to ground responses in current real-world practice.
#
#          DuckDuckGo is queried synchronously inside asyncio.to_thread() to
#          avoid blocking the event loop. An unavailable provider degrades to
#          book evidence with an explicit status instead of being presented as
#          successful current research.
# Language: Python
# Connects to: agent/state.py, config.py
# Inputs:  AgentState (user_message, send callback)
# Outputs: AgentState update: research_context (formatted bullet string)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from agent.state import AgentState
from config import settings


logger = logging.getLogger(__name__)

# Max characters for title and body in each bullet to keep prompts lean
_TITLE_MAX = 80
_BODY_MAX = 120
_TOPIC_MAX = 160


async def research_worker_node(state: AgentState) -> AgentState:
    """
    Run three DuckDuckGo searches in a background thread and format results
    as a compact bullet list for downstream workers.

    Returns state with research_context and research_status set. On failure,
    downstream nodes degrade explicitly to book-only evidence.
    """
    send = state["send"]
    await send({"type": "worker_status", "worker": "research", "status": "Searching the web…"})

    topic = _normalise_topic(state["user_message"])
    queries = _build_queries(topic)

    try:
        raw = await asyncio.to_thread(
            _run_ddg_searches,
            queries,
            settings.research_results_per_query,
        )
    except Exception as exc:
        logger.warning("Web research failed: %s", type(exc).__name__)
        await _send_unavailable(send)
        return {**state, "research_context": "", "research_status": "unavailable"}

    context = _format_results(raw, settings.research_noise_domains)
    if not context:
        logger.warning("Web research returned no citable sources")
        await _send_unavailable(send)
        return {**state, "research_context": "", "research_status": "unavailable"}
    await send({
        "type": "worker_status",
        "worker": "research",
        "status": "Web evidence ready — citable sources found.",
        "sources": _source_urls(context),
    })
    if _may_emit_eval_evidence(state):
        await send({
            "type": "research_evidence",
            "query": topic,
            "results": context.splitlines(),
        })
    return {**state, "research_context": context, "research_status": "ready"}


async def _send_unavailable(send) -> None:
    await send({
        "type": "worker_status",
        "worker": "research",
        "status": "Web research unavailable — continuing with book evidence only.",
    })


def _may_emit_eval_evidence(state: AgentState) -> bool:
    """Keep external snippets inside the isolated, allowlisted staging evaluator."""
    email = str(state.get("user_email") or "").strip().lower()
    return settings.db_schema == "staging" and email in settings.internal_test_email_allowlist


def _normalise_topic(message: str) -> str:
    topic = " ".join(message.split())
    if len(topic) <= _TOPIC_MAX:
        return topic
    shortened = topic[:_TOPIC_MAX].rsplit(" ", 1)[0].strip()
    return shortened or topic[:_TOPIC_MAX]


def _source_urls(context: str) -> list[str]:
    """Return the exact links emitted by this worker for audit and evaluation."""
    return [
        segment.split(">", 1)[0]
        for segment in context.split("<")[1:]
        if segment.startswith(("http://", "https://")) and ">" in segment
    ]


def _build_queries(topic: str) -> list[str]:
    current_year = datetime.now(timezone.utc).year
    return [
        f"{topic} architecture",
        f"{topic} best practices",
        f"{topic} implementation {current_year}",
    ]


def _run_ddg_searches(queries: list[str], results_per_query: int) -> list[dict]:
    """
    Synchronous DuckDuckGo search across all queries.
    Called inside asyncio.to_thread — must be thread-safe.
    Returns a flat list of raw result dicts (title, href, body).
    """
    from ddgs import DDGS  # imported lazily — only if research is enabled

    results: list[dict] = []
    with DDGS(timeout=4) as ddg:
        for query in queries:
            try:
                hits = list(ddg.text(query, max_results=results_per_query))
                results.extend(hits)
            except Exception:
                # One failed query shouldn't abort the rest
                logger.debug("DuckDuckGo query failed", exc_info=True)
                continue
    if results or not queries:
        return results

    # Retry the provider once with a fresh session. Retrying the whole query
    # set would multiply traffic during an outage without improving evidence.
    time.sleep(0.2)
    try:
        with DDGS(timeout=4) as ddg:
            results.extend(ddg.text(queries[0], max_results=results_per_query))
    except Exception:
        logger.debug("DuckDuckGo bounded retry failed", exc_info=True)
    return results


def _format_results(raw: list[dict], noise_domains: list[str]) -> str:
    """
    Filter noise, deduplicate URLs, and format up to 6 bullets.
    Each bullet preserves the exact source URL for downstream citation.
    Returns an empty string if nothing useful was found.
    """
    seen_urls: set[str] = set()
    bullets: list[str] = []
    normalised_noise_domains = [noise.lower().removeprefix("www.") for noise in noise_domains]

    for item in raw:
        href = str(item.get("href") or item.get("url", "")).strip()
        title = (item.get("title") or "").strip()
        body = (item.get("body") or "").strip()

        if not href or not body:
            continue

        parsed = urlparse(href)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or len(href) > 500
            or any(character.isspace() or character in "<>" for character in href)
        ):
            continue

        # Deduplicate by URL
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Filter low-quality domains
        domain = (parsed.hostname or "").lower().removeprefix("www.")
        if any(
            domain == noise or domain.endswith(f".{noise}")
            for noise in normalised_noise_domains
        ):
            continue

        # Truncate for prompt economy
        safe_title = " ".join(
            title.replace("[", "(").replace("]", ")").replace("<", "(").replace(">", ")").split()
        ) or domain
        safe_body = " ".join(body.replace("<", "(").replace(">", ")").split())
        title_trunc = safe_title[:_TITLE_MAX] + ("…" if len(safe_title) > _TITLE_MAX else "")
        body_trunc = safe_body[:_BODY_MAX] + ("…" if len(safe_body) > _BODY_MAX else "")

        bullets.append(f"- {title_trunc} — <{href}>: {body_trunc}")

        if len(bullets) >= 6:
            break

    if not bullets:
        return ""

    return "\n".join(bullets)
