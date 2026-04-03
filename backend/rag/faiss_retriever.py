# ─────────────────────────────────────────────────────────────────────────────
# File: backend/rag/faiss_retriever.py
# Purpose: Hierarchical retrieval — search child chunks in FAISS, then expand
#          to the parent section for each match. This gives retrieval precision
#          (child chunks are small and specific) with context richness (full
#          parent sections go to the LLM).
# Language: Python
# Connects to: rag/faiss_loader.py (vectorstore + parent_docs at startup),
#              agent/tools/rag_worker_tools/rag_search_tool.py
# Inputs:  query string, optional metadata filter dict, k (top-k child results)
# Outputs: list of parent Document objects (deduplicated by parent_chunk_index)
# ─────────────────────────────────────────────────────────────────────────────

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from config import settings


def retrieve(
    vectorstore: FAISS,
    parent_docs: list[Document],
    query: str,
    k: int = settings.rag_top_k,
    filter: dict | None = None,
) -> list[Document]:
    """
    Hierarchical retrieval:
    1. FAISS similarity search on child chunks (small, precise)
    2. Expand each child match to its parent section (full context)
    3. Deduplicate parents (multiple child hits can map to the same parent)

    Args:
        vectorstore:  FAISS instance loaded at startup
        parent_docs:  list of parent Documents loaded at startup
        query:        natural language query string
        k:            number of child chunks to retrieve before expansion
        filter:       optional metadata filter e.g. {"chapter": 6}

    Returns:
        list of unique parent Documents, ordered by relevance of best child match
    """
    # Step 1: retrieve top-k child chunks
    child_results = vectorstore.similarity_search(query, k=k, filter=filter)

    # Step 2: map each child back to its parent using shared metadata keys
    # Parent is identified by (book, chapter, page_number, parent_chunk_index)
    seen: set[tuple] = set()
    parents: list[Document] = []

    for child in child_results:
        m = child.metadata
        parent_key = (
            m.get("book"),
            m.get("chapter"),
            m.get("page_number"),
            m.get("parent_chunk_index"),
        )

        if parent_key in seen:
            continue
        seen.add(parent_key)

        # Find the matching parent doc — linear scan is fine at this scale
        # (parent_docs is ~600 items; FAISS already did the heavy lifting)
        parent = _find_parent(parent_docs, m)
        if parent:
            parents.append(parent)

    return parents


def _find_parent(parent_docs: list[Document], child_meta: dict) -> Document | None:
    """Return the parent doc whose metadata matches the child's parent keys."""
    for doc in parent_docs:
        pm = doc.metadata
        if (
            pm.get("book") == child_meta.get("book")
            and pm.get("chapter") == child_meta.get("chapter")
            and pm.get("page_number") == child_meta.get("page_number")
            and pm.get("parent_chunk_index") == child_meta.get("parent_chunk_index")
        ):
            return doc
    return None
