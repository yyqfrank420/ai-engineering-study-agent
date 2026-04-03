# ─────────────────────────────────────────────────────────────────────────────
# File: backend/legacy/storage/session_store.py
# Purpose: Legacy session-scoped storage preserved only for compatibility tests.
# Language: Python
# Connects to: adapters/database_adapter.py
# Inputs:  session_id (str)
# Outputs: session dict or None
# ─────────────────────────────────────────────────────────────────────────────

import json

from adapters.database_adapter import execute, fetchone


def get_or_create(session_id: str) -> dict:
    """
    Return the session row if it exists, or create it and return the new row.
    Also updates last_seen_at on every call (tracks session activity).
    """
    existing = fetchone(
        "SELECT * FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    if existing:
        execute(
            "UPDATE sessions SET last_seen_at = datetime('now') WHERE session_id = ?",
            (session_id,),
        )
        return fetchone("SELECT * FROM sessions WHERE session_id = ?", (session_id,))

    execute(
        "INSERT INTO sessions (session_id) VALUES (?)",
        (session_id,),
    )
    return fetchone("SELECT * FROM sessions WHERE session_id = ?", (session_id,))


def get_graph(session_id: str) -> dict | None:
    """Return the last persisted graph_data for this session, or None."""
    row = fetchone(
        "SELECT graph_data FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    if row and row.get("graph_data"):
        try:
            return json.loads(row["graph_data"])
        except Exception:
            return None
    return None


def save_graph(session_id: str, graph_data: dict) -> None:
    """Persist the current graph_data for this session."""
    execute(
        "UPDATE sessions SET graph_data = ? WHERE session_id = ?",
        (json.dumps(graph_data, ensure_ascii=False), session_id),
    )
