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
#          avoid blocking the event loop. Any exception (timeout, rate-limit,
#          network error) is silently swallowed — research is additive, not
#          required for the pipeline to succeed.
# Language: Python
# Connects to: agent/state.py, config.py
# Inputs:  AgentState (user_message, send callback)
# Outputs: AgentState update: research_context (formatted bullet string)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

from agent.state import AgentState
from config import settings

# Max characters for title and body in each bullet to keep prompts lean
_TITLE_MAX  = 80
_BODY_MAX   = 120


async def research_worker_node(state: AgentState) -> AgentState:
    """
    Run three DuckDuckGo searches in a background thread and format results
    as a compact bullet list for downstream workers.

    Returns state with research_context set. On any failure, research_context
    is an empty string so downstream nodes degrade gracefully.
    """
    send = state["send"]
    await send({"type": "worker_status", "worker": "research", "status": "Searching the web…"})

    topic = state["user_message"][:60].strip()
    queries = _build_queries(topic)

    try:
        raw = await asyncio.to_thread(
            _run_ddg_searches,
            queries,
            settings.research_results_per_query,
        )
    except Exception as exc:
        # Fail silently — research is additive, never a blocker
        print(f"[research_worker] DDG search failed: {exc}")
        return {**state, "research_context": ""}

    context = _format_results(raw, settings.research_noise_domains)
    return {**state, "research_context": context}


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
    from duckduckgo_search import DDGS  # imported lazily — only if research is enabled

    results: list[dict] = []
    with DDGS(timeout=4) as ddg:
        for query in queries:
            try:
                hits = list(ddg.text(query, max_results=results_per_query))
                results.extend(hits)
            except Exception:
                # One failed query shouldn't abort the rest
                continue
    return results


def _format_results(raw: list[dict], noise_domains: list[str]) -> str:
    """
    Filter noise, deduplicate URLs, and format up to 6 bullets.
    Each bullet: [source domain] title snippet: body snippet.
    Returns an empty string if nothing useful was found.
    """
    seen_urls: set[str] = set()
    bullets: list[str] = []

    for item in raw:
        href  = item.get("href") or item.get("url", "")
        title = (item.get("title") or "").strip()
        body  = (item.get("body") or "").strip()

        if not href or not body:
            continue

        # Deduplicate by URL
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Filter low-quality domains
        domain = urlparse(href).netloc.lstrip("www.")
        if any(noise in domain for noise in noise_domains):
            continue

        # Truncate for prompt economy
        title_trunc = title[:_TITLE_MAX] + ("…" if len(title) > _TITLE_MAX else "")
        body_trunc  = body[:_BODY_MAX]   + ("…" if len(body)  > _BODY_MAX  else "")

        bullets.append(f"- [{domain}] {title_trunc}: {body_trunc}")

        if len(bullets) >= 6:
            break

    if not bullets:
        return ""

    return "\n".join(bullets)
