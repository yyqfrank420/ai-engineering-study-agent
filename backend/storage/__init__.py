# ─────────────────────────────────────────────────────────────────────────────
# File: backend/storage/__init__.py
# Purpose: Re-export storage modules used by the current authenticated runtime.
#          Legacy session/history stores still exist on disk for migration and
#          archival tests, but they are not part of the production path.
# ─────────────────────────────────────────────────────────────────────────────

from . import message_store, profile_store, thread_store

__all__ = [
    "message_store",
    "profile_store",
    "thread_store",
]
