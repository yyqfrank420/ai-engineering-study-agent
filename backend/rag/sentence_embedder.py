# ─────────────────────────────────────────────────────────────────────────────
# File: backend/rag/sentence_embedder.py
# Purpose: LangChain-compatible embeddings wrapper for all-MiniLM-L6-v2.
#          Must match the model used during ingestion — embeddings must be
#          in the same vector space for FAISS similarity search to be valid.
# Language: Python
# Connects to: config.py (embedding_model), rag/faiss_loader.py,
#              rag/faiss_retriever.py
# Inputs:  list of strings (documents) or single string (query)
# Outputs: list of 384-dim float vectors
# ─────────────────────────────────────────────────────────────────────────────

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from config import settings

# Loaded once at module import time — model is cached by sentence-transformers
_model = SentenceTransformer(settings.embedding_model)


class SentenceEmbedder(Embeddings):
    """LangChain Embeddings interface backed by sentence-transformers (CPU)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = _model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = _model.encode([text], show_progress_bar=False, convert_to_numpy=True)
        return vector[0].tolist()
