from __future__ import annotations

from typing import Any


BOOK_ID = "ai-eng"


def parent_chunk_id_from_metadata(metadata: dict[str, Any]) -> str:
    """Return the stable parent chunk ID described by the graph build plan."""
    page_number = metadata.get("page_number")
    parent_index = metadata.get("parent_chunk_index")
    if page_number is None or parent_index is None:
        raise ValueError(f"Missing chunk metadata for stable ID: {metadata}")
    return f"{BOOK_ID}:p{int(page_number)}:pc{int(parent_index)}"


def child_chunk_id_from_metadata(metadata: dict[str, Any]) -> str:
    """Return the stable child chunk ID when child metadata is available."""
    child_index = metadata.get("child_chunk_index")
    if child_index is None:
        raise ValueError(f"Missing child_chunk_index for stable child ID: {metadata}")
    return f"{parent_chunk_id_from_metadata(metadata)}:cc{int(child_index)}"


def parent_chunk_id_from_chunk(chunk: dict[str, Any]) -> str | None:
    """Best-effort parent chunk ID lookup for runtime RAG chunk dictionaries."""
    existing = chunk.get("parent_chunk_id")
    if existing:
        return str(existing)
    try:
        return parent_chunk_id_from_metadata(chunk)
    except (TypeError, ValueError):
        return None
