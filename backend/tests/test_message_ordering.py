import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from adapters.database_adapter import _connect, execute, fetchall, init_db
from storage import message_store
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, persist_turn


def _thread():
    init_db()
    upsert_profile("user-1", "order@example.com")
    return create_thread("user-1")["id"]


def _persist(thread_id, turn):
    return persist_turn(
        "user-1",
        thread_id,
        title="Ordered conversation",
        user_content=f"user-{turn}",
        assistant_content=f"assistant-{turn}",
        graph_data=None,
        client_request_id=f"turn-{turn}",
    )


def test_history_orders_tied_turns_before_applying_raw_message_limit(temp_data_dir):
    thread_id = _thread()
    for turn in range(3):
        _persist(thread_id, turn)
    execute("UPDATE chat_messages SET created_at = '2026-09-12 00:00:00'")

    expected = [f"{role}-{turn}" for turn in range(3) for role in ("user", "assistant")]
    assert [
        row["content"] for row in message_store.get_history("user-1", thread_id)
    ] == expected
    assert [
        row["content"]
        for row in message_store.get_history("user-1", thread_id, limit=3)
    ] == expected[-3:]
    assert [
        row["content"]
        for row in message_store.get_messages("user-1", thread_id, limit=3)
    ] == expected[:3]
    assert message_store.get_history("user-1", thread_id, limit=0) == []


def test_concurrent_turns_and_single_message_append_keep_each_turn_adjacent(
    temp_data_dir,
):
    thread_id = _thread()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_persist, thread_id, turn) for turn in range(8)]
        futures.append(
            executor.submit(
                message_store.append, "user-1", thread_id, "user", "standalone"
            )
        )
        for future in futures:
            future.result()
    execute("UPDATE chat_messages SET created_at = '2026-09-12 00:00:00'")
    rows = message_store.get_history("user-1", thread_id, limit=100)
    contents = [row["content"] for row in rows]
    assert len(contents) == 17
    assert contents.count("standalone") == 1
    for turn in range(8):
        index = contents.index(f"user-{turn}")
        assert contents[index + 1] == f"assistant-{turn}"
    assert contents == [
        row["content"] for row in message_store.get_messages("user-1", thread_id)
    ]


def test_concurrent_idempotent_retries_do_not_allocate_duplicate_messages(
    temp_data_dir,
):
    thread_id = _thread()
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert all(executor.map(lambda _: _persist(thread_id, 1), range(4)))
    assert [
        row["content"] for row in message_store.get_history("user-1", thread_id)
    ] == ["user-1", "assistant-1"]


@pytest.mark.parametrize("has_request_id", [False, True])
def test_sqlite_upgrade_preserves_legacy_rowid_order_and_constraints(
    temp_data_dir, has_request_id
):
    thread_id = _thread()
    with _connect() as conn:
        conn.execute("DROP TABLE chat_messages")
        request_column = "client_request_id TEXT," if has_request_id else ""
        conn.execute(
            f"""
            CREATE TABLE chat_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES chat_threads(id),
                user_id TEXT NOT NULL REFERENCES profiles(id),
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                {request_column}
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        for index, (message_id, role) in enumerate(
            [("z", "user"), ("a", "assistant"), ("y", "user"), ("b", "assistant")]
        ):
            conn.execute(
                "INSERT INTO chat_messages(id,thread_id,user_id,role,content,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    message_id,
                    thread_id,
                    "user-1",
                    role,
                    f"message-{index}",
                    "2026-09-12 00:00:00",
                ),
            )
        if has_request_id:
            conn.execute(
                "UPDATE chat_messages SET client_request_id = 'first' WHERE id IN ('z','a')"
            )
            conn.execute(
                "UPDATE chat_messages SET client_request_id = 'second' WHERE id IN ('y','b')"
            )
        legacy_rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM chat_messages ORDER BY rowid")
        ]

    init_db()
    init_db()

    rows = fetchall("SELECT * FROM chat_messages ORDER BY message_sequence")
    assert [row["message_sequence"] for row in rows] == [1, 2, 3, 4]
    assert [{key: row[key] for key in legacy_rows[0]} for row in rows] == legacy_rows
    with _connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(chat_messages)")
        }
        assert {
            "idx_chat_messages_thread_created",
            "idx_chat_messages_thread_sequence",
            "uq_chat_messages_client_turn_role",
        } <= indexes
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            "INSERT INTO chat_messages(id,thread_id,user_id,role,content) VALUES(?,?,?,?,?)",
            ("z", thread_id, "user-1", "user", "duplicate"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            "INSERT INTO chat_messages(id,thread_id,user_id,role,content) VALUES(?,?,?,?,?)",
            ("unknown-thread", "missing", "user-1", "user", "bad reference"),
        )
    # An old writer's unchanged column list receives the next database ordinal.
    message_store.append("user-1", thread_id, "user", "after-upgrade")
    assert (
        message_store.get_history("user-1", thread_id)[-1]["content"] == "after-upgrade"
    )
    execute("DELETE FROM chat_messages WHERE content = 'after-upgrade'")
    message_store.append("user-1", thread_id, "user", "after-delete")
    assert fetchall("SELECT MAX(message_sequence) AS n FROM chat_messages")[0]["n"] == 6


def test_append_requires_thread_ownership(temp_data_dir):
    thread_id = _thread()
    upsert_profile("user-2", "other@example.com")
    with pytest.raises(ValueError, match="Thread no longer exists"):
        message_store.append("user-2", thread_id, "user", "unauthorized")
    assert message_store.get_messages("user-1", thread_id) == []


def test_history_accepts_sequence_gaps_from_other_threads(temp_data_dir):
    thread_id = _thread()
    other_thread = create_thread("user-1")["id"]
    _persist(thread_id, 1)
    _persist(other_thread, 2)
    _persist(thread_id, 3)

    assert [
        row["content"]
        for row in message_store.get_history("user-1", thread_id, limit=3)
    ] == ["assistant-1", "user-3", "assistant-3"]
    assert [
        row["content"] for row in message_store.get_messages("user-1", thread_id)
    ] == ["user-1", "assistant-1", "user-3", "assistant-3"]
