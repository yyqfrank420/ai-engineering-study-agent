# ─────────────────────────────────────────────────────────────────────────────
# File: ingestion/config.py
# Purpose: Centralised configuration for the ingestion pipeline
# Language: Python
# Connects to: chunker.py, sentence_embedder.py, ingest.py
# Inputs: none (constants only)
# Outputs: PARENT_CHUNK_SIZE, CHILD_CHUNK_SIZE, OVERLAP, OUTPUT_DIR, BOOKS
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path

# ── Chunking ──────────────────────────────────────────────────────────────────
# Parent chunks: large context windows returned to LLM agents
# Child chunks: smaller units used for vector similarity search
PARENT_CHUNK_SIZE = 2048
PARENT_CHUNK_OVERLAP = 200
CHILD_CHUNK_SIZE = 512
CHILD_CHUNK_OVERLAP = 50

# ── Embedding ─────────────────────────────────────────────────────────────────
# all-MiniLM-L6-v2: 384-dim, fast CPU inference, good retrieval quality
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ── Output ────────────────────────────────────────────────────────────────────
# Local output dir mirrors the Render Persistent Disk layout (/data/faiss/)
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "faiss"

# ── Book registry ─────────────────────────────────────────────────────────────
# Add new books here. `key` is used as the FAISS metadata `book` filter value.
BOOKS = {
    "AI Engineering": {
        "author": "Chip Huyen",
        "key": "AI Engineering",
    },
}
