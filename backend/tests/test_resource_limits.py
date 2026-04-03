# ─────────────────────────────────────────────────────────────────────────────
# File: backend/tests/test_resource_limits.py
# Purpose: Tests for all resource-limit behaviours added in the sidebar + limits
#          feature: thread eviction, message cap, graph size cap, and
#          auto-condense history.
# Language: Python / pytest
# Connects to: storage/thread_store.py, storage/message_store.py,
#              agent/context_manager.py, adapters/database_adapter.py
# ─────────────────────────────────────────────────────────────────────────────

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from adapters.database_adapter import init_db
from storage import message_store, thread_store
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


# ── Message cap ───────────────────────────────────────────────────────────────

def test_message_cap_raises_429(temp_data_dir, monkeypatch):
    """
    Appending a message when the thread is already at max_messages_per_thread
    should raise HTTPException 429.
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

    with pytest.raises(HTTPException) as exc_info:
        message_store.append(user_id, thread_id, "user", "one too many")

    assert exc_info.value.status_code == 429


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
    """save_graph should return True and persist when under the byte limit."""
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_graph_data_bytes", 1024 * 1024)  # 1 MB

    user_id = make_user()
    thread = thread_store.create_thread(user_id)

    small_graph = {"title": "tiny", "nodes": [], "edges": []}
    result = thread_store.save_graph(user_id, thread["id"], small_graph)

    assert result is True
    assert thread_store.get_graph(user_id, thread["id"]) == small_graph


def test_save_graph_returns_false_over_limit(temp_data_dir, monkeypatch):
    """save_graph should return False and NOT persist when over the byte limit."""
    init_db()
    from config import settings
    monkeypatch.setattr(settings, "max_graph_data_bytes", 10)  # tiny limit

    user_id = make_user()
    thread = thread_store.create_thread(user_id)

    large_graph = {"title": "huge", "nodes": [{"id": "n1", "data": "x" * 1000}], "edges": []}
    result = thread_store.save_graph(user_id, thread["id"], large_graph)

    assert result is False
    # Existing graph_data should remain None (nothing written)
    assert thread_store.get_graph(user_id, thread["id"]) is None


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
    with patch(
        "agent.context_manager._call_haiku_summary",
        new=AsyncMock(return_value=mock_summary),
    ):
        result = await maybe_condense_history(
            history,
            threshold_chars=100,   # threshold easily exceeded
            keep_recent=2,
        )

    # Should be: [summary_msg, recent_turn_3, recent_turn_4]
    assert len(result) == 3
    assert "Summary of old turns." in result[0]["content"]
    assert result[1] == history[2]
    assert result[2] == history[3]


@pytest.mark.asyncio
async def test_condense_falls_back_on_haiku_failure():
    """
    If the Haiku call raises an exception, the original history should be
    returned unchanged — never blocking the main response.
    """
    from agent.context_manager import maybe_condense_history

    history = [
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "B" * 5000},
        {"role": "user", "content": "recent question"},
    ]

    with patch(
        "agent.context_manager._call_haiku_summary",
        new=AsyncMock(side_effect=Exception("Haiku unavailable")),
    ):
        result = await maybe_condense_history(
            history,
            threshold_chars=100,
            keep_recent=1,
        )

    # Should fall back to original
    assert result == history
