# ─────────────────────────────────────────────────────────────────────────────
# File: ingestion/sentence_embedder.py
# Purpose: Thin wrapper around sentence-transformers for generating embeddings.
#          Exposes the LangChain Embeddings interface so it plugs into FAISS
#          without any glue code.
# Language: Python
# Connects to: config.py (model name), ingest.py (used to build FAISS index)
# Inputs:  list of strings
# Outputs: list of 384-dim float vectors (all-MiniLM-L6-v2)
# ─────────────────────────────────────────────────────────────────────────────

from typing import Any

from langchain_core.embeddings import Embeddings

from config import EMBEDDING_MODEL


class SentenceEmbedder(Embeddings):
    """
    LangChain-compatible embeddings class backed by sentence-transformers.
    Uses CPU inference — no GPU required.
    Model is loaded once at construction and reused for all calls.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL, *, model: Any | None = None):
        if model is None:
            # Keep the heavyweight optional import out of module collection.
            # Production ingestion still loads and reuses one real model.
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Returns list of 384-dim vectors."""
        vectors = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Returns one 384-dim vector."""
        vector = self._model.encode([text], show_progress_bar=False, convert_to_numpy=True)
        return vector[0].tolist()
