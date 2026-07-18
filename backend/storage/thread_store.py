import json
import logging
import uuid

from adapters.database_adapter import _adapt_query, _connect, execute, fetchall, fetchone
from config import settings
from storage.errors import ThreadMessageLimitExceeded

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
    """Atomically delete a thread and its messages on either database."""
    with _connect() as conn:
        conn.execute(
            _adapt_query("DELETE FROM chat_messages WHERE thread_id = ? AND user_id = ?"),
            (thread_id, user_id),
        )
        conn.execute(
            _adapt_query("DELETE FROM chat_threads WHERE id = ? AND user_id = ?"),
            (thread_id, user_id),
        )


def create_thread(user_id: str, title: str = "New chat") -> dict:
    with _connect() as conn:
        if settings.use_postgres:
            # Serialise the count/evict/insert sequence per user. The profile is
            # guaranteed to exist because API callers upsert it first.
            profile = conn.execute(
                _adapt_query("SELECT id FROM profiles WHERE id = ? FOR UPDATE"),
                (user_id,),
            ).fetchone()
            if profile is None:
                raise ValueError("Profile does not exist")
        else:
            conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            _adapt_query("SELECT COUNT(*) AS n FROM chat_threads WHERE user_id = ?"),
            (user_id,),
        ).fetchone()
        thread_count = row["n"] if row else 0

        # Evict oldest thread when the user is at the limit.
        if thread_count >= settings.max_threads_per_user:
            oldest = conn.execute(
                _adapt_query(
                    """
                    SELECT id FROM chat_threads
                    WHERE user_id = ?
                    ORDER BY last_seen_at ASC
                    LIMIT 1
                    """
                ),
                (user_id,),
            ).fetchone()
            if oldest:
                oldest_id = oldest["id"]
                logger.info(
                    "thread_store: evicting oldest thread %s for user %s (limit=%d)",
                    oldest_id, user_id, settings.max_threads_per_user,
                )
                conn.execute(
                    _adapt_query("DELETE FROM chat_messages WHERE thread_id = ? AND user_id = ?"),
                    (oldest_id, user_id),
                )
                conn.execute(
                    _adapt_query("DELETE FROM chat_threads WHERE id = ? AND user_id = ?"),
                    (oldest_id, user_id),
                )

        thread_id = str(uuid.uuid4())
        conn.execute(
            _adapt_query(
                """
                INSERT INTO chat_threads (id, user_id, title)
                VALUES (?, ?, ?)
                """
            ),
            (thread_id, user_id, title),
        )
        row = conn.execute(
            _adapt_query(
                """
                SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
                FROM chat_threads
                WHERE id = ? AND user_id = ?
                """
            ),
            (thread_id, user_id),
        ).fetchone()
        thread = dict(row) if row else None

    if thread and thread.get("graph_data"):
        try:
            thread["graph_data"] = json.loads(thread["graph_data"]) if isinstance(thread["graph_data"], str) else thread["graph_data"]
        except Exception:
            thread["graph_data"] = None
    return thread


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


def persist_turn(
    user_id: str,
    thread_id: str,
    *,
    title: str,
    user_content: str,
    assistant_content: str,
    graph_data: dict | None,
    client_request_id: str | None = None,
) -> bool:
    """Atomically and idempotently persist a completed turn and optional graph.

    Returns False only when the graph exceeds its size limit; the messages and
    thread metadata are still committed together. Reusing a non-null
    ``client_request_id`` returns without duplicating an already completed turn.
    Any database error rolls the complete turn back, avoiding partial history.
    """
    serialized_graph: str | None = None
    graph_saved = True
    if graph_data is not None:
        candidate = json.dumps(graph_data, ensure_ascii=False)
        if len(candidate.encode("utf-8")) > settings.max_graph_data_bytes:
            graph_saved = False
        else:
            serialized_graph = candidate

    with _connect() as conn:
        if not settings.use_postgres:
            # Acquire SQLite's write lock before checking the idempotency key.
            conn.execute("BEGIN IMMEDIATE")
        thread_query = (
            "SELECT id FROM chat_threads WHERE id = ? AND user_id = ? FOR UPDATE"
            if settings.use_postgres
            else "SELECT id FROM chat_threads WHERE id = ? AND user_id = ?"
        )
        thread = conn.execute(
            _adapt_query(thread_query),
            (thread_id, user_id),
        ).fetchone()
        if thread is None:
            raise ValueError("Thread no longer exists")

        if client_request_id is not None:
            prior_rows = conn.execute(
                _adapt_query(
                    """
                    SELECT role FROM chat_messages
                    WHERE thread_id = ? AND user_id = ? AND client_request_id = ?
                    """
                ),
                (thread_id, user_id, client_request_id),
            ).fetchall()
            if prior_rows:
                prior_roles = {row["role"] for row in prior_rows}
                if prior_roles != {"user", "assistant"}:
                    raise RuntimeError("Stored turn is incomplete; refusing an ambiguous retry")
                return True

        row = conn.execute(
            _adapt_query(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?"
            ),
            (thread_id, user_id),
        ).fetchone()
        message_count = row["n"] if row else 0
        if message_count + 2 > settings.max_messages_per_thread:
            raise ThreadMessageLimitExceeded(
                "Thread message limit reached. Start a new chat to continue."
            )

        for role, content in (("user", user_content), ("assistant", assistant_content)):
            conn.execute(
                _adapt_query(
                    """
                    INSERT INTO chat_messages (
                        id, thread_id, user_id, role, content, client_request_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    str(uuid.uuid4()),
                    thread_id,
                    user_id,
                    role,
                    content,
                    client_request_id,
                ),
            )

        if serialized_graph is not None:
            conn.execute(
                _adapt_query(
                    """
                    UPDATE chat_threads
                    SET title = ?, graph_data = ?, updated_at = CURRENT_TIMESTAMP,
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (title, serialized_graph, thread_id, user_id),
            )
        else:
            conn.execute(
                _adapt_query(
                    """
                    UPDATE chat_threads
                    SET title = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (title, thread_id, user_id),
            )

    return graph_saved


def get_completed_turn(
    user_id: str,
    thread_id: str,
    client_request_id: str | None,
) -> dict[str, str] | None:
    """Return the canonical stored response for a completed idempotent turn.

    A partial turn is never replayed because its outcome is ambiguous. The
    completed-turn transaction should prevent that state, but treating it as an
    error keeps corruption visible instead of silently inventing a response.
    """
    if client_request_id is None:
        return None

    rows = fetchall(
        """
        SELECT role, content
        FROM chat_messages
        WHERE user_id = ? AND thread_id = ? AND client_request_id = ?
        """,
        (user_id, thread_id, client_request_id),
    )
    if not rows:
        return None

    content_by_role = {row["role"]: row["content"] for row in rows}
    if set(content_by_role) != {"user", "assistant"}:
        raise RuntimeError("Stored turn is incomplete; refusing an ambiguous retry")
    return {
        "user_content": content_by_role["user"],
        "assistant_content": content_by_role["assistant"],
    }
