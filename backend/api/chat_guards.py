import re
import time

from starlette.requests import HTTPConnection

from config import settings
from storage.rate_limit_store import RateLimitDimension, reserve_rate_limit


def _is_internal_test_user(user: dict) -> bool:
    claims = user.get("claims")
    app_metadata = claims.get("app_metadata") if isinstance(claims, dict) else None
    return (
        isinstance(app_metadata, dict)
        and app_metadata.get("provider") == "internal_test"
    )


def internal_test_stream_scope(user: dict, thread_id: str) -> str | None:
    """Scope trusted eval-session exclusivity to one conversation thread."""
    return thread_id if _is_internal_test_user(user) else None


def is_production_traffic(user: dict) -> bool:
    return (
        settings.otel_environment.strip().lower() == "production"
        and not _is_internal_test_user(user)
    )


def check_rate_limit(key: str) -> str | None:
    """Return an error string when the user is over limit, otherwise None."""
    now = time.time()
    reservation = reserve_rate_limit(
        (
            RateLimitDimension(
                scope="chat-user-minute",
                identifier=key,
                event_type="chat_request_minute",
                limit=settings.rate_limit_per_minute,
                window_s=60,
            ),
            RateLimitDimension(
                scope="chat-user-hour",
                identifier=key,
                event_type="chat_request_hour",
                limit=settings.rate_limit_per_hour,
                window_s=3600,
            ),
        ),
        created_at_epoch=now,
    )
    if reservation is None:
        return (
            "Rate limit exceeded: "
            f"max {settings.rate_limit_per_minute}/minute or "
            f"{settings.rate_limit_per_hour}/hour"
        )
    return None


_PROMPT_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\b(ignore|disregard|forget|bypass|override)\b.{0,80}\b(previous|prior|above|system|developer)\b", re.I | re.S), 0.55),
    (re.compile(r"\b(reveal|print|show|leak|dump)\b.{0,80}\b(system prompt|developer message|hidden instructions|api key|secret)\b", re.I | re.S), 0.55),
    (re.compile(r"\b(system|developer)\s*:\s*", re.I), 0.25),
    (re.compile(r"\byou are now\b|\bnew instructions\b|\bjailbreak\b|\bDAN\b", re.I), 0.35),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|PRIVATE) KEY)\b"), 0.75),
)

_EXPLICIT_UNTRUSTED_QUOTE = re.compile(
    r"\b(?:treat|analy[sz]e|review|explain)\b"
    r"[^'\"]{0,240}"
    r"\b(?:quoted\s+(?:text|instruction|ticket|message|request)|"
    r"untrusted\s+(?:text|notes|instruction|data|ticket|message|request)|"
    r"prompt[- ]injection\s+example)\b"
    r"[^'\"]{0,240}"
    r"(?P<quote>['\"]).*?(?P=quote)",
    re.I | re.S,
)


def check_prompt_injection(text: str) -> bool:
    """Return False for obvious instruction-override or secret-exfiltration prompts."""
    normalized = " ".join(text.split())
    # Ignore only the explicitly framed quotation. Injection-like text outside
    # it is still scored, and a malicious prompt cannot self-label as safe from
    # inside its own quoted payload.
    text_to_score = _EXPLICIT_UNTRUSTED_QUOTE.sub("", normalized)
    score = sum(weight for pattern, weight in _PROMPT_INJECTION_PATTERNS if pattern.search(text_to_score))
    return score < settings.prompt_injection_threshold


def byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def knowledge_base_ready(request: HTTPConnection) -> bool:
    return getattr(request.app.state, "vectorstore", None) is not None and bool(
        getattr(request.app.state, "parent_docs", None)
    )
