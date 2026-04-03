"""Legacy storage compatibility tests.

These cover the old session/history stores that are no longer used by the
authenticated thread-based runtime. Keep them separate from production-path
confidence when reviewing test results.
"""

import time
import uuid

from adapters.database_adapter import init_db
from legacy.storage import history_store
from legacy.storage import session_store


def test_session_get_or_create_updates_last_seen(temp_data_dir):
    init_db()
    session_id = str(uuid.uuid4())

    created = session_store.get_or_create(session_id)
    first_seen = created["last_seen_at"]
    time.sleep(1.1)
    updated = session_store.get_or_create(session_id)

    assert updated["session_id"] == session_id
    assert updated["last_seen_at"] > first_seen


def test_session_graph_round_trip(temp_data_dir):
    init_db()
    session_id = str(uuid.uuid4())
    graph = {"title": "Test", "nodes": [{"id": "n1"}], "edges": []}

    session_store.get_or_create(session_id)
    session_store.save_graph(session_id, graph)

    assert session_store.get_graph(session_id) == graph


def test_session_graph_invalid_json_returns_none(temp_data_dir):
    init_db()
    session_id = str(uuid.uuid4())

    session_store.get_or_create(session_id)
    db_path = temp_data_dir / "sessions.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET graph_data = ? WHERE session_id = ?",
            ("{bad json", session_id),
        )
        conn.commit()

    assert session_store.get_graph(session_id) is None


def test_history_round_trip_returns_oldest_first(temp_data_dir):
    init_db()
    session_id = str(uuid.uuid4())

    session_store.get_or_create(session_id)
    history_store.append(session_id, "user", "first")
    history_store.append(session_id, "assistant", "second")
    history_store.append(session_id, "user", "third")

    history = history_store.get_history(session_id, limit=2)

    assert history == [
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
