# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/tools/rag_worker_tools/get_section_tool.py
# Purpose: Direct section lookup by book/chapter/section — used when the
#          orchestrator or worker already knows which section to fetch rather
#          than needing similarity search.
# Language: Python
# Connects to: rag/faiss_retriever.py (via parent_docs), agent/state.py
# Inputs:  book (str), chapter (int), section (str | None)
# Outputs: list of matching parent section texts as JSON string
# ─────────────────────────────────────────────────────────────────────────────

import json
from typing import Any

from langchain_core.tools import tool


def make_get_section_tool(parent_docs: list):
    """Factory that binds parent_docs to the tool at startup."""

    @tool
    def get_section(book: str, chapter: int, section: str | None = None) -> str:
        """
        Retrieve full section text directly by book, chapter, and optional section title.
        Use this when you know exactly which part of the book you need.

        Args:
            book:    Book title e.g. "AI Engineering"
            chapter: Chapter number e.g. 6
            section: Optional section title e.g. "Chunking Strategies"
        """
        results = []
        for doc in parent_docs:
            m = doc.metadata
            if m.get("book") != book:
                continue
            if m.get("chapter") != chapter:
                continue
            if section and section.lower() not in (m.get("section") or "").lower():
                continue
            results.append({
                "text": doc.page_content,
                "book": m.get("book"),
                "chapter": m.get("chapter"),
                "chapter_title": m.get("chapter_title"),
                "section": m.get("section"),
                "page_number": m.get("page_number"),
            })

        return json.dumps(results[:5], ensure_ascii=False)  # cap at 5 sections

    return get_section
