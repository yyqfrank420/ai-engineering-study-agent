import uuid

from adapters.database_adapter import _adapt_query, _connect, fetchall, fetchone
from config import settings
from storage.errors import ThreadMessageLimitExceeded


def count_messages(user_id: str, thread_id: str) -> int:
    """Return the number of messages in this thread."""
    row = fetchone(
        "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    return row["n"] if row else 0


def append(user_id: str, thread_id: str, role: str, content: str) -> None:
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread_query = "SELECT id FROM chat_threads WHERE id = ? AND user_id = ?"
        if settings.use_postgres:
            thread_query += " FOR UPDATE"
        thread = conn.execute(
            _adapt_query(thread_query), (thread_id, user_id)
        ).fetchone()
        if thread is None:
            raise ValueError("Thread no longer exists")
        count = conn.execute(
            _adapt_query(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?"
            ),
            (thread_id, user_id),
        ).fetchone()["n"]
        if count >= settings.max_messages_per_thread:
            raise ThreadMessageLimitExceeded(
                "Thread message limit reached. Start a new chat to continue."
            )
        conn.execute(
            _adapt_query(
                """
                INSERT INTO chat_messages (id, thread_id, user_id, role, content)
                VALUES (?, ?, ?, ?, ?)
                """
            ),
            (str(uuid.uuid4()), thread_id, user_id, role, content),
        )


def get_history(user_id: str, thread_id: str, limit: int = 20) -> list[dict]:
    rows = fetchall(
        """
        SELECT role, content
        FROM chat_messages
        WHERE thread_id = ? AND user_id = ?
        ORDER BY message_sequence DESC
        LIMIT ?
        """,
        (thread_id, user_id, limit),
    )
    return list(reversed(rows))


def get_messages(user_id: str, thread_id: str, limit: int = 100) -> list[dict]:
    rows = fetchall(
        """
        SELECT id, role, content, created_at
        FROM chat_messages
        WHERE thread_id = ? AND user_id = ?
        ORDER BY message_sequence ASC
        LIMIT ?
        """,
        (thread_id, user_id, limit),
    )
    return rows
