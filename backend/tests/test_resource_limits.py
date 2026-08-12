# ─────────────────────────────────────────────────────────────────────────────
# File: backend/tests/test_resource_limits.py
# Purpose: Tests for all resource-limit behaviours added in the sidebar + limits
#          feature: thread eviction, message cap, graph size cap, and
#          auto-condense history.
# Language: Python / pytest
# Connects to: storage/thread_store.py, storage/message_store.py,
#              agent/context_manager.py, adapters/database_adapter.py
# ─────────────────────────────────────────────────────────────────────────────

import json
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from adapters.database_adapter import init_db
from storage import message_store, thread_store
from storage.errors import ThreadMessageLimitExceeded
from storage.profile_store import upsert_profile

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_user(email_prefix: str = "test") -> str:
    """Create a test profile and return its user_id."""
    user_id = str(uuid.uuid4())
    upsert_profile(user_id, f"{email_prefix}-{user_id[:8]}@example.com")
    return user_id


# ── Thread eviction ───────────────────────────────────────────────────────────

def test_thread_eviction_keeps_max_threads(temp_data_dir, monkeypatch):
    """
    Creating more threads than max_threads_per_user should evict the oldest
    thread so the count never exceeds the configured limit.
    """
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_threads_per_user", 5)

    user_id = make_user()

    created_ids = []
    for i in range(6):
        t = thread_store.create_thread(user_id, title=f"chat {i}")
        created_ids.append(t["id"])

    remaining = thread_store.list_threads(user_id, limit=20)
    assert len(remaining) == 5, f"Expected 5 threads, got {len(remaining)}"


def test_thread_eviction_removes_oldest_thread(temp_data_dir, monkeypatch):
    """
    The thread that was created and least-recently-seen should be the one
    that gets evicted.
    """
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_threads_per_user", 3)

    user_id = make_user()

    first = thread_store.create_thread(user_id, title="first")
    thread_store.create_thread(user_id, title="second")
    thread_store.create_thread(user_id, title="third")

    # Creating a 4th should evict "first"
    thread_store.create_thread(user_id, title="fourth")

    remaining_ids = {t["id"] for t in thread_store.list_threads(user_id, limit=20)}
    assert first["id"] not in remaining_ids, "Oldest thread should have been evicted"


def test_thread_eviction_cascades_messages(temp_data_dir, monkeypatch):
    """
    When a thread is evicted its messages must also be deleted — no orphaned rows.
    """
    import sqlite3

    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_threads_per_user", 2)

    user_id = make_user()

    first = thread_store.create_thread(user_id, title="first")
    message_store.append(user_id, first["id"], "user", "hello")
    message_store.append(user_id, first["id"], "assistant", "world")

    thread_store.create_thread(user_id, title="second")
    # Third creation evicts "first"
    thread_store.create_thread(user_id, title="third")

    db_path = temp_data_dir / "sessions.db"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE thread_id = ?",
            (first["id"],),
        ).fetchone()
    assert row[0] == 0, "Evicted thread's messages were not deleted"


def test_thread_store_count_oldest_touch_and_delete_helpers(temp_data_dir, monkeypatch):
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_threads_per_user", 10)

    user_id = make_user()
    first = thread_store.create_thread(user_id, title="first")
    second = thread_store.create_thread(user_id, title="second")
    message_store.append(user_id, first["id"], "user", "hello")

    assert thread_store.count_threads(user_id) == 2
    assert thread_store.get_oldest_thread_id(user_id) in {first["id"], second["id"]}

    thread_store.touch_thread(user_id, first["id"], title="renamed")
    assert thread_store.get_thread(user_id, first["id"])["title"] == "renamed"

    thread_store.touch_thread(user_id, second["id"])
    assert thread_store.get_thread(user_id, second["id"]) is not None

    thread_store.delete_thread(user_id, first["id"])
    assert thread_store.get_thread(user_id, first["id"]) is None
    assert message_store.get_messages(user_id, first["id"]) == []


def test_thread_store_handles_corrupt_graph_json(temp_data_dir):
    from adapters.database_adapter import execute

    init_db()
    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    execute(
        "UPDATE chat_threads SET graph_data = ? WHERE id = ? AND user_id = ?",
        ("{not-json", thread["id"], user_id),
    )

    assert thread_store.get_thread(user_id, thread["id"])["graph_data"] is None
    assert thread_store.get_latest_thread(user_id)["graph_data"] is None
    assert thread_store.get_graph(user_id, thread["id"]) is None


# ── Message cap ───────────────────────────────────────────────────────────────

def test_message_cap_raises_domain_error(temp_data_dir, monkeypatch):
    """
    Appending a message when the thread is already at max_messages_per_thread
    should raise a storage-domain error without depending on the HTTP layer.
    """
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_messages_per_thread", 4)

    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    thread_id = thread["id"]

    for i in range(4):
        role = "user" if i % 2 == 0 else "assistant"
        message_store.append(user_id, thread_id, role, f"message {i}")

    with pytest.raises(ThreadMessageLimitExceeded):
        message_store.append(user_id, thread_id, "user", "one too many")


def test_message_cap_allows_up_to_limit(temp_data_dir, monkeypatch):
    """
    Appending exactly max_messages_per_thread messages should succeed without error.
    """
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_messages_per_thread", 3)

    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    thread_id = thread["id"]

    for i in range(3):
        role = "user" if i % 2 == 0 else "assistant"
        message_store.append(user_id, thread_id, role, f"ok {i}")

    assert message_store.count_messages(user_id, thread_id) == 3


# ── Graph size cap ────────────────────────────────────────────────────────────

def test_save_graph_returns_true_under_limit(temp_data_dir, monkeypatch):
    """save_graph should return True and persist layout when under the byte limit."""
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_graph_data_bytes", 1024 * 1024)  # 1 MB

    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    current_graph = {"version": "server-v2", "nodes": [{"id": "current"}], "edges": []}
    assert thread_store.persist_turn(
        user_id,
        thread["id"],
        title="Current",
        user_content="question",
        assistant_content="answer",
        graph_data=current_graph,
    )

    view_state = {"nodePositions": {"current": {"x": 1, "y": 2}}}
    stale_graph = {
        "version": "client-v1",
        "nodes": [{"id": "stale"}],
        "edges": [{"source": "stale", "target": "removed"}],
        "view_state": view_state,
    }
    result = thread_store.save_graph(user_id, thread["id"], stale_graph)

    assert result is True
    assert thread_store.get_graph(user_id, thread["id"]) == current_graph


def test_save_graph_returns_false_over_limit(temp_data_dir, monkeypatch):
    """save_graph should return False and preserve the graph when layout is too large."""
    init_db()
    from config import settings

    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    current_graph = {"version": "server-v2", "nodes": [{"id": "current"}], "edges": []}
    assert thread_store.persist_turn(
        user_id,
        thread["id"],
        title="Current",
        user_content="question",
        assistant_content="answer",
        graph_data=current_graph,
    )
    monkeypatch.setattr(settings, "max_graph_data_bytes", 10)  # tiny limit

    large_graph = {
        "version": "server-v2",
        "view_state": {"nodePositions": {"current": {"x": "x" * 1000}}},
    }
    result = thread_store.save_graph(user_id, thread["id"], large_graph)

    assert result is False
    assert thread_store.get_graph(user_id, thread["id"]) == current_graph


def test_save_graph_uses_postgres_row_lock_and_preserves_semantic_graph(monkeypatch):
    current_graph = {
        "version": "server-v2",
        "nodes": [{"id": "current"}],
        "edges": [],
    }

    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.queries = []
            self.updated_graph = None

        def execute(self, query, params=()):
            self.queries.append((query, params))
            if query.lstrip().startswith("SELECT graph_data"):
                return Cursor({"graph_data": current_graph})
            if query.lstrip().startswith("UPDATE chat_threads"):
                self.updated_graph = json.loads(params[0])
            return Cursor()

    connection = Connection()

    @contextmanager
    def fake_connect():
        yield connection

    from config import settings

    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://example")
    monkeypatch.setattr(thread_store, "_connect", fake_connect)

    view_state = {"nodePositions": {"current": {"x": 3, "y": 4}}}
    assert thread_store.save_graph(
        "user-1",
        "thread-1",
        {
            "version": "client-v1",
            "nodes": [{"id": "stale"}],
            "edges": [{"source": "stale", "target": "removed"}],
            "view_state": view_state,
        },
    )

    select_query, select_params = connection.queries[0]
    assert "FOR UPDATE" in select_query
    assert "id = %s AND user_id = %s" in select_query
    assert select_params == ("thread-1", "user-1")
    assert connection.updated_graph is None


def test_save_graph_updates_layout_for_matching_version(temp_data_dir):
    init_db()
    user_id = make_user()
    thread = thread_store.create_thread(user_id)
    current_graph = {
        "version": "server-v2",
        "nodes": [{"id": "current"}],
        "edges": [],
    }
    assert thread_store.persist_turn(
        user_id,
        thread["id"],
        title="Current",
        user_content="question",
        assistant_content="answer",
        graph_data=current_graph,
    )
    view_state = {"nodePositions": {"current": {"x": 3, "y": 4}}}

    assert thread_store.save_graph(
        user_id,
        thread["id"],
        {"version": "server-v2", "view_state": view_state},
    )

    assert thread_store.get_graph(user_id, thread["id"]) == {
        **current_graph,
        "view_state": view_state,
    }


# ── Auto-condense ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_condense_returns_unchanged_when_below_threshold():
    """History below the char threshold should pass through untouched."""
    from agent.context_manager import maybe_condense_history

    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    result = await maybe_condense_history(history, threshold_chars=10000, keep_recent=4)
    assert result == history


@pytest.mark.asyncio
async def test_condense_summarises_old_turns_when_over_threshold():
    """
    When history exceeds threshold, old turns should be replaced with a
    single summary message, and the most recent turns kept verbatim.
    """
    from agent.context_manager import maybe_condense_history

    history = [
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "B" * 5000},
        {"role": "user", "content": "C" * 5000},   # recent — kept
        {"role": "assistant", "content": "D"},       # recent — kept
    ]

    mock_summary = "Summary of old turns."
    summary_call = AsyncMock(return_value=mock_summary)
    with patch(
        "agent.context_manager._call_summary",
        new=summary_call,
    ):
        result = await maybe_condense_history(
            history,
            threshold_chars=100,   # threshold easily exceeded
            keep_recent=2,
            telemetry={"operation": "context_condense", "thread_id": "thread-1"},
        )

    # Should be: [summary_msg, recent_turn_3, recent_turn_4]
    assert len(result) == 3
    assert "Summary of old turns." in result[0]["content"]
    assert result[1] == history[2]
    assert result[2] == history[3]
    assert summary_call.await_args.kwargs["telemetry"]["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_condense_falls_back_on_model_failure():
    """
    If the summary call raises an exception, the original history should be
    returned unchanged — never blocking the main response.
    """
    from agent.context_manager import maybe_condense_history

    history = [
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "B" * 5000},
        {"role": "user", "content": "recent question"},
    ]

    with patch(
        "agent.context_manager._call_summary",
        new=AsyncMock(side_effect=Exception("Model unavailable")),
    ):
        result = await maybe_condense_history(
            history,
            threshold_chars=100,
            keep_recent=1,
        )

    # Should fall back to original
    assert result == history
