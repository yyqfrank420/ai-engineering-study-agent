# ─────────────────────────────────────────────────────────────────────────────
# File: backend/legacy/storage/history_store.py
# Purpose: Legacy session-scoped history storage kept for compatibility tests.
# Language: Python
# Connects to: adapters/database_adapter.py
# Inputs:  session_id, role, content
# Outputs: list of {"role": str, "content": str} dicts
# ─────────────────────────────────────────────────────────────────────────────

from adapters.database_adapter import execute, fetchall


def append(session_id: str, role: str, content: str) -> None:
    """Add a message to the conversation history for this session."""
    execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """
    Return the last `limit` messages for this session, oldest first.
    Format matches LangChain / Anthropic messages: [{"role": ..., "content": ...}]
    """
    rows = fetchall(
        """
        SELECT role, content FROM messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    # fetchall returns newest-first (DESC), reverse to oldest-first for LLM context
    return list(reversed(rows))


def clear(session_id: str) -> None:
    """Delete all messages for a session (used in testing)."""
    execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
