import re

from fastapi import Request

from config import settings
from storage.runtime_state_store import get_recent_request_events, prune_request_events, record_request_event


def check_rate_limit(key: str) -> str | None:
    """Return an error string when the user is over limit, otherwise None."""
    import time

    now = time.time()
    prune_request_events(older_than_epoch=now - 3600)
    events = get_recent_request_events(key, "chat_request", since_epoch=now - 3600)

    per_minute = sum(1 for event in events if now - float(event["created_at_epoch"]) < 60)
    per_hour = len(events)

    if per_minute >= settings.rate_limit_per_minute:
        return f"Rate limit exceeded: {settings.rate_limit_per_minute} messages/minute"
    if per_hour >= settings.rate_limit_per_hour:
        return f"Rate limit exceeded: {settings.rate_limit_per_hour} messages/hour"

    record_request_event(key, "chat_request", created_at_epoch=now)
    return None


_PROMPT_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\b(ignore|disregard|forget|bypass|override)\b.{0,80}\b(previous|prior|above|system|developer)\b", re.I | re.S), 0.55),
    (re.compile(r"\b(reveal|print|show|leak|dump)\b.{0,80}\b(system prompt|developer message|hidden instructions|api key|secret)\b", re.I | re.S), 0.55),
    (re.compile(r"\b(system|developer)\s*:\s*", re.I), 0.25),
    (re.compile(r"\byou are now\b|\bnew instructions\b|\bjailbreak\b|\bDAN\b", re.I), 0.35),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|PRIVATE) KEY)\b"), 0.75),
)


def check_prompt_injection(text: str) -> bool:
    """Return False for obvious instruction-override or secret-exfiltration prompts."""
    normalized = " ".join(text.split())
    score = sum(weight for pattern, weight in _PROMPT_INJECTION_PATTERNS if pattern.search(normalized))
    return score < settings.prompt_injection_threshold


def byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def knowledge_base_ready(request: Request) -> bool:
    return getattr(request.app.state, "vectorstore", None) is not None and bool(
        getattr(request.app.state, "parent_docs", None)
    )
