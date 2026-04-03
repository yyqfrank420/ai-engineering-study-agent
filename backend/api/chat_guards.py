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


def check_prompt_injection(text: str) -> bool:
    """Return False when llm-guard flags the prompt as unsafe."""
    try:
        from llm_guard.input_scanners import PromptInjection

        scanner = PromptInjection(threshold=settings.prompt_injection_threshold)
        _, is_valid, _ = scanner.scan(prompt="", output=text)
        return is_valid
    except Exception:
        return True


def byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def knowledge_base_ready(request: Request) -> bool:
    return getattr(request.app.state, "vectorstore", None) is not None and bool(
        getattr(request.app.state, "parent_docs", None)
    )
