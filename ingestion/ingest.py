# ─────────────────────────────────────────────────────────────────────────────
# File: ingestion/ingest.py
# Purpose: Full ingestion pipeline — PDF → chunks → embeddings → FAISS index.
#          Run once per content update. Output files are then packaged into
#          a deployable artifact bundle and loaded by the backend at startup.
# Language: Python
# Connects to: config.py, chunker.py, sentence_embedder.py
# Inputs:  --pdf <path>  --book <book key from config.BOOKS>
# Outputs: data/faiss/index.faiss, data/faiss/index.pkl, data/faiss/parent_docs.pkl
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import pickle
from pathlib import Path

from langchain_community.vectorstores import FAISS

from chunker import chunk_pdf
from config import BOOKS, OUTPUT_DIR
from sentence_embedder import SentenceEmbedder


def run(pdf_path: Path, book_key: str) -> None:
    if book_key not in BOOKS:
        raise ValueError(f"Unknown book key '{book_key}'. Add it to config.BOOKS first.")

    book_meta = BOOKS[book_key]
    print(f"[ingest] Book:  {book_key} ({book_meta['author']})")
    print(f"[ingest] PDF:   {pdf_path}")
    print(f"[ingest] Output: {OUTPUT_DIR}")

    # ── Step 1: chunk ─────────────────────────────────────────────────────────
    print("[ingest] Chunking PDF...")
    pairs = chunk_pdf(pdf_path, book_key=book_key, book_author=book_meta["author"])
    print(f"[ingest] Got {len(pairs)} parent chunks")

    parent_docs = [parent for parent, _ in pairs]
    child_docs = [child for _, children in pairs for child in children]
    print(f"[ingest] Got {len(child_docs)} child chunks")

    # Sanity-check a sample metadata record
    if child_docs:
        print(f"[ingest] Sample child metadata: {child_docs[0].metadata}")

    # ── Step 2: embed + build FAISS ───────────────────────────────────────────
    print("[ingest] Loading embedding model...")
    embedder = SentenceEmbedder()

    print("[ingest] Building FAISS index from child chunks (this may take a few minutes)...")
    child_texts = [doc.page_content for doc in child_docs]
    child_metadatas = [doc.metadata for doc in child_docs]

    vectorstore = FAISS.from_texts(
        texts=child_texts,
        embedding=embedder,
        metadatas=child_metadatas,
    )

    # ── Step 3: save ──────────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # FAISS index + child docstore
    vectorstore.save_local(str(OUTPUT_DIR))
    print(f"[ingest] Saved FAISS index → {OUTPUT_DIR}/index.faiss + index.pkl")

    # Parent docs (full sections) — loaded at query time for context expansion
    parent_docs_path = OUTPUT_DIR / "parent_docs.pkl"
    with open(parent_docs_path, "wb") as f:
        pickle.dump(parent_docs, f)
    print(f"[ingest] Saved parent docs → {parent_docs_path}")

    # ── Step 4: verify ────────────────────────────────────────────────────────
    print("\n[ingest] Verification — running a test query...")
    results = vectorstore.similarity_search("What is retrieval-augmented generation?", k=3)
    for i, doc in enumerate(results, 1):
        preview = doc.page_content[:120].replace("\n", " ")
        print(f"  [{i}] (ch={doc.metadata.get('chapter')}, p={doc.metadata.get('page_number')}) {preview}...")

    print("\n[ingest] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a book PDF into the FAISS index.")
    parser.add_argument("--pdf", required=True, type=Path, help="Path to the PDF file")
    parser.add_argument(
        "--book",
        default="AI Engineering",
        help="Book key from config.BOOKS (default: 'AI Engineering')",
    )
    args = parser.parse_args()
    run(args.pdf, args.book)
