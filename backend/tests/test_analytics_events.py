import asyncio

from adapters.database_adapter import init_db
from analytics import events
from config import settings
from storage.analytics_event_store import list_recent_analytics_events
from storage.product_analytics_store import list_recent_product_analytics_events


def test_enqueue_analytics_event_falls_back_to_safe_direct_write(temp_data_dir):
    init_db()

    accepted = events.enqueue_analytics_event(
        event_name="request_completed",
        event_category="request",
        request_id="request-1",
        numeric_value=42,
        unit="ms",
        properties={"path": "/health"},
        created_at_epoch=20,
    )

    rows = list_recent_analytics_events(since_epoch=0)
    assert accepted is True
    assert rows[0]["event_name"] == "request_completed"
    assert rows[0]["properties"]["path"] == "/health"


def test_enqueue_analytics_event_drops_when_queue_is_full(monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(None)
    monkeypatch.setattr(events, "_queue", queue)
    monkeypatch.setattr(settings, "analytics_queue_max_size", 1)

    accepted = events.enqueue_analytics_event(
        event_name="stream_first_token",
        event_category="stream",
        numeric_value=10,
        unit="ms",
    )

    assert accepted is False


def test_enqueue_product_analytics_event_falls_back_to_safe_direct_write(temp_data_dir):
    init_db()

    accepted = events.enqueue_product_analytics_event(
        anonymous_id="anon-1",
        event_type="auth_viewed",
        properties={"mode": "email"},
        created_at_epoch=30,
    )

    rows = list_recent_product_analytics_events(since_epoch=0)
    assert accepted is True
    assert rows[0]["event_type"] == "auth_viewed"
    assert rows[0]["properties"]["mode"] == "email"


def test_enqueue_product_analytics_event_drops_when_queue_is_full(monkeypatch):
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(None)
    monkeypatch.setattr(events, "_queue", queue)
    monkeypatch.setattr(settings, "analytics_queue_max_size", 1)

    accepted = events.enqueue_product_analytics_event(
        anonymous_id="anon-1",
        event_type="auth_viewed",
        properties={},
    )

    assert accepted is False


def test_analytics_worker_writes_product_events_with_profile(temp_data_dir):
    init_db()

    async def run_worker_once():
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        events._queue = queue
        try:
            worker = asyncio.create_task(events._analytics_worker())
            accepted = events.enqueue_product_analytics_event(
                anonymous_id="anon-1",
                event_type="chat_sent",
                user_id="00000000-0000-0000-0000-000000000001",
                user_email="admin@example.com",
                properties={"thread_id": "thread-1"},
                created_at_epoch=40,
            )
            await queue.join()
            await queue.put(None)
            await worker
            return accepted
        finally:
            events._queue = None

    accepted = asyncio.run(run_worker_once())

    rows = list_recent_product_analytics_events(since_epoch=0)
    assert accepted is True
    assert rows[0]["user_id"] == "00000000-0000-0000-0000-000000000001"
    assert rows[0]["event_type"] == "chat_sent"


def test_output_shape_from_final_state_is_content_light():
    shape = events.output_shape_from_final_state(
        {
            "response_text": "## Answer\nSee (Chapter 1).",
            "graph_data": {
                "graph_type": "concept",
                "version": "v1",
                "nodes": [{"id": "n1"}],
                "edges": [{"source": "n1", "target": "n2"}],
            },
            "rag_chunks": [{"id": "c1"}],
            "retrieval_relevance": "strong",
            "route": "search",
        }
    )

    assert shape == {
        "output_type": "chat_response",
        "answer_chars": 26,
        "contains_markdown": True,
        "has_citations": True,
        "graph_emitted": True,
        "graph_type": "concept",
        "graph_version": "v1",
        "graph_node_count": 1,
        "graph_edge_count": 1,
        "retrieval_relevance": "strong",
        "retrieval_chunk_count": 1,
        "route": "search",
    }


def test_analytics_queue_lifecycle_is_idempotent_and_drains(monkeypatch):
    monkeypatch.setattr(events, "_queue", None)
    monkeypatch.setattr(events, "_worker_task", None)
    monkeypatch.setattr(events, "_dropped_events", 2)
    monkeypatch.setattr(settings, "analytics_queue_max_size", 3)

    async def exercise_worker():
        assert events.analytics_queue_stats() == {
            "queued": 0,
            "dropped": 2,
            "max_size": 3,
        }

        events.start_analytics_worker()
        first_task = events._worker_task
        events.start_analytics_worker()

        assert events._worker_task is first_task
        assert events.analytics_queue_stats()["queued"] == 0
        await events.stop_analytics_worker()
        await events.stop_analytics_worker()

    asyncio.run(exercise_worker())

    assert events._queue is None
    assert events._worker_task is None


def test_analytics_worker_rejects_missing_queue(monkeypatch):
    monkeypatch.setattr(events, "_queue", None)

    async def run_worker():
        try:
            await events._analytics_worker()
        except RuntimeError as exc:
            return str(exc)
        raise AssertionError("worker accepted an uninitialised queue")

    assert asyncio.run(run_worker()) == (
        "Analytics worker started before its queue was initialised"
    )


def test_stop_analytics_worker_cancels_a_stuck_writer(monkeypatch):
    async def exercise_timeout():
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        worker = asyncio.create_task(asyncio.Event().wait())
        monkeypatch.setattr(events, "_queue", queue)
        monkeypatch.setattr(events, "_worker_task", worker)
        real_wait_for = asyncio.wait_for

        async def bounded_wait(awaitable, *, timeout):
            if timeout == 5:
                raise TimeoutError
            return await real_wait_for(awaitable, timeout=timeout)

        monkeypatch.setattr(events.asyncio, "wait_for", bounded_wait)
        await events.stop_analytics_worker()

        assert worker.cancelled()

    asyncio.run(exercise_timeout())

    assert events._queue is None
    assert events._worker_task is None


def test_invalid_analytics_events_are_counted_without_writes(monkeypatch):
    monkeypatch.setattr(events, "_queue", None)
    monkeypatch.setattr(events, "_dropped_events", 0)

    assert events.enqueue_analytics_event(
        event_name="",
        event_category="request",
        created_at_epoch=-1,
    ) is False
    assert events.enqueue_product_analytics_event(
        anonymous_id="",
        event_type="",
        created_at_epoch=-1,
    ) is False
    assert events.analytics_queue_stats()["dropped"] == 2


def test_analytics_write_failures_are_contained(monkeypatch):
    analytics_event = events.AnalyticsEventWrite.model_validate({
        "event_name": "request_failed",
        "event_category": "request",
        "created_at_epoch": 10,
    })
    product_event = events.ProductAnalyticsEventWrite.model_validate({
        "anonymous_id": "anon-1",
        "event_type": "chat_sent",
        "user_id": "user-1",
        "created_at_epoch": 10,
    })

    def fail_write(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(events, "record_analytics_event", fail_write)
    monkeypatch.setattr(events, "record_product_analytics_event", fail_write)
    monkeypatch.setattr(events, "upsert_profile", fail_write)

    assert events._write_item_safely(analytics_event) is False
    assert events._write_item_safely(
        events.ProductAnalyticsEventJob(
            event=product_event,
            user_email="user@example.com",
        )
    ) is False


def test_event_shapes_cover_stream_variants_and_invalid_collections():
    assert events.event_shape_from_sse({
        "type": "response_delta",
        "content": "hello",
    }) == {
        "output_type": "answer_delta",
        "delta_chars": 5,
    }
    assert events.event_shape_from_sse({
        "type": "graph_data",
        "data": {
            "graph_type": "architecture",
            "version": "graph-v1",
            "nodes": "invalid",
            "edges": None,
        },
    }) == {
        "output_type": "graph",
        "graph_type": "architecture",
        "graph_version": "graph-v1",
        "node_count": 0,
        "edge_count": 0,
    }
    assert events.event_shape_from_sse({
        "type": "suggested_questions",
        "questions": ["One", "Two"],
    }) == {
        "output_type": "suggested_questions",
        "question_count": 2,
    }
    assert events.event_shape_from_sse({}) == {"output_type": "unknown"}

    shape = events.output_shape_from_final_state({
        "response_text": None,
        "graph_data": {"nodes": "invalid", "edges": {}},
        "rag_chunks": "invalid",
    })
    assert shape["answer_chars"] == 0
    assert shape["graph_node_count"] == 0
    assert shape["graph_edge_count"] == 0
    assert shape["retrieval_chunk_count"] == 0
