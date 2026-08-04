from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.internal_access import get_internal_dashboard_user
from storage.analytics_event_store import list_recent_analytics_events
from storage.product_analytics_store import list_recent_product_analytics_events
from storage.telemetry_store import list_recent_http_request_logs, list_recent_llm_telemetry

router = APIRouter(prefix="/api/internal/dashboard", tags=["internal-dashboard"])

_FUNNEL_STEPS = [
    "auth_viewed",
    "otp_requested",
    "otp_verified",
    "prepare_clicked",
    "prepare_succeeded",
    "chat_sent",
    "chat_stream_completed",
]
_SAFE_EVAL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _actor_key(row: dict[str, Any]) -> str:
    return row.get("anonymous_id") or row.get("user_id") or "unknown"


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _bucket_label(start_epoch: int, bucket: str) -> str:
    dt = time.gmtime(start_epoch)
    if bucket == "hour":
        return time.strftime("%H:%M", dt)
    return time.strftime("%b %d", dt)


def _bucket_start(ts: float, bucket_size_s: int) -> int:
    return int(ts // bucket_size_s) * bucket_size_s


def _event_count(rows: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for row in rows if row["event_type"] == event_type)


def _percentile(values: list[float], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return int(ordered[index])


def _safe_eval_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if _SAFE_EVAL_IDENTIFIER.fullmatch(text) else None


def _nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


@router.get("/overview")
async def dashboard_overview(_user=Depends(get_internal_dashboard_user)):
    now = time.time()
    events_1d = list_recent_product_analytics_events(since_epoch=now - 86400)
    events_7d = list_recent_product_analytics_events(since_epoch=now - 7 * 86400)
    http_1d = list_recent_http_request_logs(since_epoch=now - 86400)
    llm_1d = list_recent_llm_telemetry(since_epoch=now - 86400)
    analytics_1d = list_recent_analytics_events(since_epoch=now - 86400)
    first_token_latencies = [
        float(row["numeric_value"])
        for row in analytics_1d
        if row["event_category"] == "stream"
        and row["event_name"] == "stream_first_token"
        and row.get("numeric_value") is not None
    ]

    sent = _event_count(events_1d, "chat_sent")
    completed = _event_count(events_1d, "chat_stream_completed")
    failed = _event_count(events_1d, "chat_stream_failed")
    stopped = _event_count(events_1d, "chat_stopped")
    search_requested = _event_count(events_1d, "search_tool_requested")

    return {
        "window_hours": 24,
        "kpis": {
            "dau": len({_actor_key(row) for row in events_1d}),
            "wau": len({_actor_key(row) for row in events_7d}),
            "prepares": _event_count(events_1d, "prepare_succeeded"),
            "chats_sent": sent,
            "chats_completed": completed,
            "chats_failed": failed,
            "stop_rate": _safe_rate(stopped, sent),
            "search_tool_request_rate": _safe_rate(search_requested, sent),
            "avg_chat_latency_ms": int(
                mean([row["latency_ms"] for row in http_1d if row["path"] == "/api/chat"])
            ) if any(row["path"] == "/api/chat" for row in http_1d) else None,
            "avg_first_token_latency_ms": int(mean(first_token_latencies)) if first_token_latencies else None,
            "p95_first_token_latency_ms": _percentile(first_token_latencies, 0.95),
            "quality_scores": len([row for row in analytics_1d if row["event_category"] == "quality_score"]),
        },
        "providers": dict(Counter(row["provider"] for row in llm_1d)),
    }


@router.get("/trends")
async def dashboard_trends(
    bucket: str = Query(default="day", pattern="^(day|hour)$"),
    _user=Depends(get_internal_dashboard_user),
):
    now = time.time()
    bucket_size_s = 3600 if bucket == "hour" else 86400
    bucket_count = 24 if bucket == "hour" else 7
    current_bucket_start = _bucket_start(now, bucket_size_s)
    first_bucket_start = current_bucket_start - bucket_size_s * (bucket_count - 1)
    since_epoch = first_bucket_start

    events = list_recent_product_analytics_events(since_epoch=since_epoch)
    http_logs = list_recent_http_request_logs(since_epoch=since_epoch)
    llm_rows = list_recent_llm_telemetry(since_epoch=since_epoch)

    buckets: dict[int, dict[str, Any]] = {}
    for index in range(bucket_count):
        start_epoch = first_bucket_start + index * bucket_size_s
        buckets[start_epoch] = {
            "start_epoch": start_epoch,
            "label": _bucket_label(start_epoch, bucket),
            "chat_sent": 0,
            "chat_completed": 0,
            "chat_failed": 0,
            "avg_chat_latency_ms": None,
            "provider_usage": {},
        }

    latency_values: dict[int, list[int]] = defaultdict(list)
    provider_counts: dict[int, Counter[str]] = defaultdict(Counter)

    for row in events:
        start_epoch = _bucket_start(row["created_at_epoch"], bucket_size_s)
        if start_epoch not in buckets:
            continue
        if row["event_type"] == "chat_sent":
            buckets[start_epoch]["chat_sent"] += 1
        elif row["event_type"] == "chat_stream_completed":
            buckets[start_epoch]["chat_completed"] += 1
        elif row["event_type"] == "chat_stream_failed":
            buckets[start_epoch]["chat_failed"] += 1

    for row in http_logs:
        if row["path"] != "/api/chat":
            continue
        start_epoch = _bucket_start(row["created_at_epoch"], bucket_size_s)
        if start_epoch in buckets:
            latency_values[start_epoch].append(int(row["latency_ms"]))

    for row in llm_rows:
        start_epoch = _bucket_start(row["created_at_epoch"], bucket_size_s)
        if start_epoch in buckets:
            provider_counts[start_epoch][row["provider"]] += 1

    points = []
    for start_epoch in sorted(buckets):
        point = buckets[start_epoch]
        sent = point["chat_sent"]
        point["completion_rate"] = _safe_rate(point["chat_completed"], sent)
        point["avg_chat_latency_ms"] = (
            int(mean(latency_values[start_epoch])) if latency_values[start_epoch] else None
        )
        point["provider_usage"] = dict(provider_counts[start_epoch])
        points.append(point)

    return {"bucket": bucket, "points": points}


@router.get("/funnel")
async def dashboard_funnel(_user=Depends(get_internal_dashboard_user)):
    now = time.time()
    events = list_recent_product_analytics_events(since_epoch=now - 7 * 86400)
    actors_by_step: dict[str, set[str]] = {step: set() for step in _FUNNEL_STEPS}

    for row in events:
        if row["event_type"] in actors_by_step:
            actors_by_step[row["event_type"]].add(_actor_key(row))

    steps = []
    previous = None
    for step in _FUNNEL_STEPS:
        actors = len(actors_by_step[step])
        steps.append(
            {
                "event_type": step,
                "actors": actors,
                "conversion_from_previous": None if previous is None else _safe_rate(actors, previous),
            }
        )
        previous = actors

    return {"window_days": 7, "steps": steps}


@router.get("/failures")
async def dashboard_failures(_user=Depends(get_internal_dashboard_user)):
    now = time.time()
    events = list_recent_product_analytics_events(since_epoch=now - 7 * 86400)
    http_logs = list_recent_http_request_logs(since_epoch=now - 7 * 86400)
    llm_rows = list_recent_llm_telemetry(since_epoch=now - 7 * 86400)

    failures = sorted(
        [row for row in http_logs if row["status_code"] >= 400],
        key=lambda row: row["created_at_epoch"],
        reverse=True,
    )[:10]
    slow_requests = sorted(http_logs, key=lambda row: row["latency_ms"], reverse=True)[:10]
    mode_counts: Counter[str] = Counter()
    for row in events:
        if row["event_type"] != "chat_sent":
            continue
        props = row.get("properties") or {}
        label = (
            f"{props.get('complexity', 'auto')} / "
            f"{props.get('graph_mode', 'auto')} / "
            f"{'research-on' if props.get('research_enabled') else 'research-off'}"
        )
        mode_counts[label] += 1

    fallback_rows = sorted(
        [row for row in llm_rows if row["used_fallback"]],
        key=lambda row: row["created_at_epoch"],
        reverse=True,
    )[:10]

    return {
        "recent_failed_requests": [
            {
                "path": row["path"],
                "status_code": row["status_code"],
                "latency_ms": row["latency_ms"],
                "created_at_epoch": row["created_at_epoch"],
                "request_id": row["metadata"].get("request_id"),
                "trace_id": row["metadata"].get("trace_id"),
                "client_request_id": row["metadata"].get("client_request_id"),
            }
            for row in failures
        ],
        "slow_requests": [
            {
                "path": row["path"],
                "status_code": row["status_code"],
                "latency_ms": row["latency_ms"],
                "created_at_epoch": row["created_at_epoch"],
                "request_id": row["metadata"].get("request_id"),
                "trace_id": row["metadata"].get("trace_id"),
            }
            for row in slow_requests
        ],
        "provider_fallbacks": [
            {
                "operation": row["operation"],
                "provider": row["provider"],
                "model": row["model"],
                "created_at_epoch": row["created_at_epoch"],
                "request_id": row["metadata"].get("request_id"),
                "trace_id": row["metadata"].get("trace_id"),
            }
            for row in fallback_rows
        ],
        "most_used_modes": [
            {"label": label, "count": count}
            for label, count in mode_counts.most_common(10)
        ],
    }


@router.get("/llm-performance")
async def dashboard_llm_performance(_user=Depends(get_internal_dashboard_user)):
    now = time.time()
    rows = list_recent_llm_telemetry(since_epoch=now - 7 * 86400)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["operation"], row["provider"], row["model"])].append(row)

    operations = []
    for (operation, provider, model), group in grouped.items():
        calls = len(group)
        fallback_calls = sum(1 for row in group if row["used_fallback"])
        error_calls = sum(1 for row in group if row["status"] != "success")
        operations.append(
            {
                "operation": operation,
                "provider": provider,
                "model": model,
                "calls": calls,
                "avg_duration_ms": int(mean(row["duration_ms"] for row in group)),
                "fallback_rate": _safe_rate(fallback_calls, calls),
                "error_rate": _safe_rate(error_calls, calls),
            }
        )

    recent_fallbacks = sorted(
        [row for row in rows if row["used_fallback"]],
        key=lambda row: row["created_at_epoch"],
        reverse=True,
    )[:10]

    return {
        "operations": sorted(operations, key=lambda row: row["calls"], reverse=True),
        "recent_fallbacks": [
            {
                "operation": row["operation"],
                "provider": row["provider"],
                "model": row["model"],
                "duration_ms": row["duration_ms"],
                "created_at_epoch": row["created_at_epoch"],
                "request_id": row["metadata"].get("request_id"),
                "trace_id": row["metadata"].get("trace_id"),
            }
            for row in recent_fallbacks
        ],
    }


@router.get("/eval-telemetry")
async def dashboard_eval_telemetry(
    since_epoch: float = Query(..., ge=0),
    thread_id: list[str] | None = Query(default=None),
    _user=Depends(get_internal_dashboard_user),
):
    """Return bounded, sanitized call accounting for an authenticated eval run."""
    # Full live suites contain twenty cases and retain one infrastructure retry.
    if not thread_id or len(thread_id) > 40:
        return {"calls": []}
    wanted = set(thread_id)
    rows = list_recent_llm_telemetry(since_epoch=since_epoch)
    calls = []
    for row in rows:
        if row.get("thread_id") not in wanted:
            continue
        metadata = row.get("metadata") or {}
        attempts = []
        for attempt in metadata.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            attempts.append(
                {
                    "attempt": max(1, _nonnegative_int(attempt.get("attempt"), default=1)),
                    "provider": str(attempt.get("provider") or "unknown")[:64],
                    "model": str(attempt.get("model") or "unknown")[:128],
                    "status": str(attempt.get("status") or "unknown")[:32],
                    "input_tokens": _nonnegative_int(attempt.get("input_tokens")),
                    "output_tokens": _nonnegative_int(attempt.get("output_tokens")),
                    "queue_wait_ms": _nonnegative_int(attempt.get("queue_wait_ms")),
                    "duration_ms": _nonnegative_int(attempt.get("duration_ms")),
                }
            )
        calls.append(
            {
                "thread_id": row.get("thread_id"),
                "operation": row["operation"],
                "provider": row["provider"],
                "model": row["model"],
                "status": row["status"],
                "latency_ms": row["duration_ms"],
                "fallback": row["used_fallback"],
                "input_tokens": _nonnegative_int(metadata.get("input_tokens")),
                "output_tokens": _nonnegative_int(metadata.get("output_tokens")),
                "provider_attempts": max(
                    1,
                    _nonnegative_int(metadata.get("provider_attempts"), default=1),
                ),
                "queue_wait_ms": _nonnegative_int(metadata.get("queue_wait_ms")),
                "attempts": attempts[:10],
                "request_id": _safe_eval_identifier(metadata.get("request_id")),
                "client_request_id": _safe_eval_identifier(
                    metadata.get("client_request_id")
                ),
                "created_at_epoch": row["created_at_epoch"],
            }
        )
    return {"calls": calls}


@router.get("/self-improvement")
async def dashboard_self_improvement(_user=Depends(get_internal_dashboard_user)):
    now = time.time()
    rows = list_recent_analytics_events(since_epoch=now - 7 * 86400)

    first_token_latencies = [
        row for row in rows
        if row["event_category"] == "stream"
        and row["event_name"] == "stream_first_token"
        and row.get("numeric_value") is not None
    ]
    slow_first_token = sorted(
        first_token_latencies,
        key=lambda row: row["numeric_value"] or 0,
        reverse=True,
    )[:10]

    quality_scores = [
        row for row in rows
        if row["event_category"] == "quality_score"
        and row.get("numeric_value") is not None
    ]
    low_scores = sorted(
        [row for row in quality_scores if float(row["numeric_value"] or 0) < 0.7],
        key=lambda row: row["numeric_value"] or 0,
    )[:10]

    output_shapes = Counter()
    for row in rows:
        if row["event_category"] != "stream" or row["event_name"] != "stream_completed":
            continue
        props = row.get("properties") or {}
        label = (
            f"{props.get('output_type', 'unknown')} / "
            f"graph:{props.get('graph_emitted', False)} / "
            f"retrieval:{props.get('retrieval_relevance', 'unknown')}"
        )
        output_shapes[label] += 1

    error_events = [
        row for row in rows
        if row["event_name"] in {"stream_failed", "stream_timeout", "stream_cancelled", "request_rejected"}
    ]

    return {
        "window_days": 7,
        "queues": {
            "slow_first_token": [
                {
                    "latency_ms": int(row["numeric_value"] or 0),
                    "request_id": row.get("request_id"),
                    "trace_id": row.get("trace_id"),
                    "thread_id": row.get("thread_id"),
                    "created_at_epoch": row["created_at_epoch"],
                }
                for row in slow_first_token
            ],
            "low_quality_scores": [
                {
                    "score_name": row.get("properties", {}).get("score_name"),
                    "score": row["numeric_value"],
                    "request_id": row.get("request_id"),
                    "trace_id": row.get("trace_id"),
                    "thread_id": row.get("thread_id"),
                    "properties": row.get("properties", {}),
                    "created_at_epoch": row["created_at_epoch"],
                }
                for row in low_scores
            ],
            "recent_operational_errors": [
                {
                    "event_name": row["event_name"],
                    "request_id": row.get("request_id"),
                    "trace_id": row.get("trace_id"),
                    "thread_id": row.get("thread_id"),
                    "properties": row.get("properties", {}),
                    "created_at_epoch": row["created_at_epoch"],
                }
                for row in sorted(error_events, key=lambda item: item["created_at_epoch"], reverse=True)[:10]
            ],
        },
        "output_shapes": [
            {"label": label, "count": count}
            for label, count in output_shapes.most_common(10)
        ],
    }
