import json
import logging
import uuid

from adapters.database_adapter import execute, fetchall, fetchone
from config import settings

logger = logging.getLogger(__name__)


def count_threads(user_id: str) -> int:
    """Return how many threads this user currently has."""
    row = fetchone(
        "SELECT COUNT(*) AS n FROM chat_threads WHERE user_id = ?",
        (user_id,),
    )
    return row["n"] if row else 0


def get_oldest_thread_id(user_id: str) -> str | None:
    """Return the id of the user's least-recently-seen thread."""
    row = fetchone(
        """
        SELECT id FROM chat_threads
        WHERE user_id = ?
        ORDER BY last_seen_at ASC
        LIMIT 1
        """,
        (user_id,),
    )
    return row["id"] if row else None


def delete_thread(user_id: str, thread_id: str) -> None:
    """Delete a thread and all its messages.

    SQLite does not enforce ON DELETE CASCADE unless PRAGMA foreign_keys=ON is
    set — and we don't set it.  Explicitly delete messages first so we never
    leave orphaned rows regardless of the DB backend.
    """
    execute(
        "DELETE FROM chat_messages WHERE thread_id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    execute(
        "DELETE FROM chat_threads WHERE id = ? AND user_id = ?",
        (thread_id, user_id),
    )


def create_thread(user_id: str, title: str = "New chat") -> dict:
    # Evict oldest thread when the user is at the limit
    if count_threads(user_id) >= settings.max_threads_per_user:
        oldest = get_oldest_thread_id(user_id)
        if oldest:
            logger.info(
                "thread_store: evicting oldest thread %s for user %s (limit=%d)",
                oldest, user_id, settings.max_threads_per_user,
            )
            delete_thread(user_id, oldest)

    thread_id = str(uuid.uuid4())
    execute(
        """
        INSERT INTO chat_threads (id, user_id, title)
        VALUES (?, ?, ?)
        """,
        (thread_id, user_id, title),
    )
    return get_thread(user_id, thread_id)


def get_thread(user_id: str, thread_id: str) -> dict | None:
    row = fetchone(
        """
        SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    )
    if row and row.get("graph_data"):
        try:
            row["graph_data"] = json.loads(row["graph_data"]) if isinstance(row["graph_data"], str) else row["graph_data"]
        except Exception:
            row["graph_data"] = None
    return row


def list_threads(user_id: str, limit: int = 20) -> list[dict]:
    rows = fetchall(
        """
        SELECT id, title, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE user_id = ?
        ORDER BY last_seen_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return rows


def get_latest_thread(user_id: str) -> dict | None:
    row = fetchone(
        """
        SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE user_id = ?
        ORDER BY last_seen_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    if row and row.get("graph_data"):
        try:
            row["graph_data"] = json.loads(row["graph_data"]) if isinstance(row["graph_data"], str) else row["graph_data"]
        except Exception:
            row["graph_data"] = None
    return row


def touch_thread(user_id: str, thread_id: str, title: str | None = None) -> None:
    if title:
        execute(
            """
            UPDATE chat_threads
            SET title = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (title, thread_id, user_id),
        )
        return
    execute(
        """
        UPDATE chat_threads
        SET updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    )


def get_graph(user_id: str, thread_id: str) -> dict | None:
    row = fetchone(
        "SELECT graph_data FROM chat_threads WHERE id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    if row and row.get("graph_data"):
        try:
            return json.loads(row["graph_data"]) if isinstance(row["graph_data"], str) else row["graph_data"]
        except Exception:
            return None
    return None


def save_graph(user_id: str, thread_id: str, graph_data: dict) -> bool:
    """Persist graph_data for a thread.

    Returns True if saved, False if the serialised size exceeds
    settings.max_graph_data_bytes — caller should notify the user.
    """
    serialized = json.dumps(graph_data, ensure_ascii=False)
    byte_size = len(serialized.encode("utf-8"))
    if byte_size > settings.max_graph_data_bytes:
        logger.warning(
            "thread_store: graph_data too large (%d bytes > %d limit) for thread %s — skipping save",
            byte_size, settings.max_graph_data_bytes, thread_id,
        )
        return False
    execute(
        """
        UPDATE chat_threads
        SET graph_data = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (serialized, thread_id, user_id),
    )
    return True
