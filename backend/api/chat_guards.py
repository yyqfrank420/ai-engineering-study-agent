import time
from collections import defaultdict

from fastapi import Request

from config import settings

_rate_counts: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str) -> str | None:
    """Return an error string when the user is over limit, otherwise None."""
    now = time.time()
    timestamps = [timestamp for timestamp in _rate_counts[key] if now - timestamp < 3600]
    _rate_counts[key] = timestamps

    per_minute = sum(1 for timestamp in timestamps if now - timestamp < 60)
    per_hour = len(timestamps)

    if per_minute >= settings.rate_limit_per_minute:
        return f"Rate limit exceeded: {settings.rate_limit_per_minute} messages/minute"
    if per_hour >= settings.rate_limit_per_hour:
        return f"Rate limit exceeded: {settings.rate_limit_per_hour} messages/hour"

    timestamps.append(now)
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
