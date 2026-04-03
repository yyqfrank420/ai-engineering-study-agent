import uuid

from fastapi import HTTPException

from adapters.database_adapter import execute, fetchall, fetchone
from config import settings


def count_messages(user_id: str, thread_id: str) -> int:
    """Return the number of messages in this thread."""
    row = fetchone(
        "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    return row["n"] if row else 0


def append(user_id: str, thread_id: str, role: str, content: str) -> None:
    if count_messages(user_id, thread_id) >= settings.max_messages_per_thread:
        raise HTTPException(
            status_code=429,
            detail="Thread message limit reached. Start a new chat to continue.",
        )
    execute(
        """
        INSERT INTO chat_messages (id, thread_id, user_id, role, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), thread_id, user_id, role, content),
    )


def get_history(user_id: str, thread_id: str, limit: int = 20) -> list[dict]:
    rows = fetchall(
        """
        SELECT role, content
        FROM chat_messages
        WHERE thread_id = ? AND user_id = ?
        ORDER BY created_at DESC
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
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (thread_id, user_id, limit),
    )
    return rows
