# ─────────────────────────────────────────────────────────────────────────────
# File: backend/rag/faiss_loader.py
# Purpose: Load the FAISS vectorstore and parent docs from disk at startup.
#          Called once in FastAPI's lifespan hook — results are stored in
#          app.state so all request handlers share the same loaded index.
# Language: Python
# Connects to: config.py (faiss_dir), rag/sentence_embedder.py,
#              main.py (lifespan hook)
# Inputs:  files in data/faiss/ (index.faiss, index.pkl, parent_docs.pkl)
# Outputs: (FAISS vectorstore, list[Document] parent docs)
# ─────────────────────────────────────────────────────────────────────────────

import pickle
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from config import settings
from rag.sentence_embedder import SentenceEmbedder


def load_faiss() -> tuple[FAISS, list[Document]]:
    """
    Load the FAISS index and parent docs from disk after artifact resolution.
    Raises FileNotFoundError if the index files are missing.

    Returns:
        vectorstore: FAISS instance for child-chunk similarity search
        parent_docs: list of parent Document objects for context expansion
    """
    faiss_dir = settings.faiss_dir

    required = ["index.faiss", "index.pkl", "parent_docs.pkl"]
    for fname in required:
        if not (faiss_dir / fname).exists():
            raise FileNotFoundError(
                f"Missing FAISS file: {faiss_dir / fname}\n"
                "Build the FAISS bundle during content updates and make it available at startup."
            )

    embedder = SentenceEmbedder()
    vectorstore = FAISS.load_local(
        str(faiss_dir),
        embedder,
        allow_dangerous_deserialization=True,  # safe — we wrote these files ourselves
    )

    with open(faiss_dir / "parent_docs.pkl", "rb") as f:
        parent_docs: list[Document] = pickle.load(f)

    return vectorstore, parent_docs
