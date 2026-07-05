from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from config import settings
from storage.analytics_event_store import record_analytics_event
from storage.models import AnalyticsEventWrite, ProductAnalyticsEventWrite
from storage.product_analytics_store import record_product_analytics_event
from storage.profile_store import upsert_profile


@dataclass(frozen=True)
class ProductAnalyticsEventJob:
    event: ProductAnalyticsEventWrite
    user_email: str | None = None


AnalyticsQueueItem = AnalyticsEventWrite | ProductAnalyticsEventJob


_queue: asyncio.Queue[AnalyticsQueueItem | None] | None = None
_worker_task: asyncio.Task | None = None
_dropped_events = 0


def analytics_queue_stats() -> dict[str, int]:
    return {
        "queued": 0 if _queue is None else _queue.qsize(),
        "dropped": _dropped_events,
        "max_size": settings.analytics_queue_max_size,
    }


def start_analytics_worker() -> None:
    global _queue, _worker_task

    if _worker_task is not None and not _worker_task.done():
        return
    max_size = max(1, int(settings.analytics_queue_max_size))
    _queue = asyncio.Queue(maxsize=max_size)
    _worker_task = asyncio.create_task(_analytics_worker(), name="analytics-writer")


async def stop_analytics_worker() -> None:
    global _queue, _worker_task

    if _queue is None or _worker_task is None:
        return
    with suppress(TimeoutError):
        await asyncio.wait_for(_queue.put(None), timeout=1)
    try:
        await asyncio.wait_for(_worker_task, timeout=5)
    except TimeoutError:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task
    finally:
        _queue = None
        _worker_task = None


def enqueue_analytics_event(
    *,
    event_name: str,
    event_category: str,
    user_id: str | None = None,
    anonymous_id: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    client_request_id: str | None = None,
    numeric_value: float | None = None,
    unit: str | None = None,
    properties: dict[str, Any] | None = None,
    created_at_epoch: float | None = None,
) -> bool:
    global _dropped_events

    try:
        event = AnalyticsEventWrite.model_validate(
            {
                "event_name": event_name,
                "event_category": event_category,
                "user_id": user_id,
                "anonymous_id": anonymous_id,
                "session_id": session_id,
                "thread_id": thread_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "client_request_id": client_request_id,
                "schema_version": settings.analytics_event_schema_version,
                "app_version": "0.1.0",
                "environment": settings.otel_environment,
                "numeric_value": numeric_value,
                "unit": unit,
                "properties": properties or {},
                "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
            }
        )
    except Exception as exc:
        _dropped_events += 1
        print(f"[analytics] Invalid event dropped: {type(exc).__name__}: {exc}")
        return False

    return _enqueue_or_write(event, f"{event.event_category}.{event.event_name}")


def enqueue_product_analytics_event(
    *,
    anonymous_id: str,
    event_type: str,
    user_id: str | None = None,
    user_email: str | None = None,
    properties: dict[str, Any] | None = None,
    created_at_epoch: float | None = None,
) -> bool:
    global _dropped_events

    try:
        event = ProductAnalyticsEventWrite.model_validate(
            {
                "anonymous_id": anonymous_id,
                "event_type": event_type,
                "user_id": user_id,
                "properties": properties or {},
                "created_at_epoch": time.time() if created_at_epoch is None else created_at_epoch,
            }
        )
    except Exception as exc:
        _dropped_events += 1
        print(f"[analytics] Invalid product event dropped: {type(exc).__name__}: {exc}")
        return False

    return _enqueue_or_write(
        ProductAnalyticsEventJob(event=event, user_email=user_email),
        f"product.{event.event_type}",
    )


def _enqueue_or_write(item: AnalyticsQueueItem, label: str) -> bool:
    global _dropped_events

    if _queue is None:
        return _write_item_safely(item)
    try:
        _queue.put_nowait(item)
        return True
    except asyncio.QueueFull:
        _dropped_events += 1
        print(f"[analytics] Event queue full; dropping event {label}")
        return False


async def _analytics_worker() -> None:
    assert _queue is not None
    while True:
        item = await _queue.get()
        try:
            if item is None:
                return
            await asyncio.to_thread(_write_item_safely, item)
        finally:
            _queue.task_done()


def _write_item_safely(item: AnalyticsQueueItem) -> bool:
    if isinstance(item, ProductAnalyticsEventJob):
        return _write_product_event_safely(item)
    return _write_event_safely(item)


def _write_event_safely(event: AnalyticsEventWrite) -> bool:
    try:
        record_analytics_event(**event.model_dump())
        return True
    except Exception as exc:
        print(
            "[analytics] Event write failed: "
            f"{event.event_category}.{event.event_name} {type(exc).__name__}: {exc}"
        )
        return False


def _write_product_event_safely(job: ProductAnalyticsEventJob) -> bool:
    try:
        if job.event.user_id and job.user_email:
            upsert_profile(job.event.user_id, job.user_email)
        record_product_analytics_event(**job.event.model_dump())
        return True
    except Exception as exc:
        print(
            "[analytics] Product event write failed: "
            f"product.{job.event.event_type} {type(exc).__name__}: {exc}"
        )
        return False


def event_shape_from_sse(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "unknown")
    if event_type == "response_delta":
        return {"output_type": "answer_delta", "delta_chars": len(str(event.get("content") or ""))}
    if event_type == "graph_data":
        data = event.get("data") or {}
        nodes = data.get("nodes") or []
        edges = data.get("edges") or []
        return {
            "output_type": "graph",
            "graph_type": data.get("graph_type"),
            "graph_version": data.get("version"),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
            "edge_count": len(edges) if isinstance(edges, list) else 0,
        }
    if event_type == "suggested_questions":
        questions = event.get("questions") or []
        return {
            "output_type": "suggested_questions",
            "question_count": len(questions) if isinstance(questions, list) else 0,
        }
    return {"output_type": event_type}


def output_shape_from_final_state(state: dict[str, Any]) -> dict[str, Any]:
    response_text = str(state.get("response_text") or "")
    graph_data = state.get("graph_data") or {}
    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or []
    rag_chunks = state.get("rag_chunks") or []
    return {
        "output_type": "chat_response",
        "answer_chars": len(response_text),
        "contains_markdown": any(marker in response_text for marker in ("#", "-", "```", "**")),
        "has_citations": "(Chapter" in response_text,
        "graph_emitted": bool(graph_data),
        "graph_type": graph_data.get("graph_type"),
        "graph_version": graph_data.get("version"),
        "graph_node_count": len(nodes) if isinstance(nodes, list) else 0,
        "graph_edge_count": len(edges) if isinstance(edges, list) else 0,
        "retrieval_relevance": state.get("retrieval_relevance"),
        "retrieval_chunk_count": len(rag_chunks) if isinstance(rag_chunks, list) else 0,
        "route": state.get("route"),
    }
