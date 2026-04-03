# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/tools/rag_worker_tools/rag_search_tool.py
# Purpose: FAISS similarity search tool for the RAG Worker agent.
#          Searches child chunks, expands to parent sections, returns
#          formatted results with full book/chapter/page citations.
# Language: Python
# Connects to: rag/faiss_retriever.py, agent/state.py (Chunk type)
# Inputs:  query (str), k (int), filter (dict | None)
# Outputs: list[Chunk] formatted as a JSON string for the LLM
# ─────────────────────────────────────────────────────────────────────────────

import json
from typing import Any

from langchain_core.tools import tool

# vectorstore and parent_docs are injected at runtime via app.state
# (set in main.py lifespan, passed to tools via tool factory functions)


from rag.faiss_retriever import retrieve


def make_rag_search_tool(vectorstore: Any, parent_docs: list):
    """
    Factory that binds the loaded FAISS index to the tool.
    Called once at startup — returns a LangChain tool with the index baked in.
    """
    @tool
    def rag_search(query: str, k: int = 8, filter: dict | None = None) -> str:
        """
        Search the book's knowledge base for content relevant to the query.
        Returns the most relevant sections with book, chapter, and page citations.

        Args:
            query:  Natural language search query
            k:      Number of results to return (default 8)
            filter: Optional metadata filter e.g. {"chapter": 6}
        """
        docs = retrieve(vectorstore, parent_docs, query, k=k, filter=filter)
        chunks = [
            {
                "text": doc.page_content,
                "book": doc.metadata.get("book"),
                "chapter": doc.metadata.get("chapter"),
                "chapter_title": doc.metadata.get("chapter_title"),
                "section": doc.metadata.get("section"),
                "page_number": doc.metadata.get("page_number"),
            }
            for doc in docs
        ]
        return json.dumps(chunks, ensure_ascii=False)

    return rag_search
