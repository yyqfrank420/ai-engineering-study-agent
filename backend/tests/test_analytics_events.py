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
