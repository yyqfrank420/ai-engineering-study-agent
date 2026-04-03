# ─────────────────────────────────────────────────────────────────────────────
# File: ingestion/test_ingestion.py
# Purpose: Quick smoke tests for the ingestion pipeline components
# Language: Python
# Connects to: chunker.py, sentence_embedder.py, config.py
# Inputs:  none (uses synthetic text, no PDF required)
#          FAISS index tests require ingest.py to have been run first.
# Outputs: pytest pass/fail
# ─────────────────────────────────────────────────────────────────────────────

import pickle
from pathlib import Path

import pytest

from config import OUTPUT_DIR
from sentence_embedder import SentenceEmbedder
from chunker import _build_chapter_map, _build_font_profile, _is_size
from langchain_core.documents import Document

PDF_PATH = Path("/Users/yangyuqing/Desktop/Textbooks pdf/AI Engineering.pdf")


# ── font size helper ──────────────────────────────────────────────────────────

def test_is_size_exact():
    assert _is_size(18.9, 18.9) is True

def test_is_size_within_tolerance():
    assert _is_size(18.5, 18.9) is True   # within 1pt

def test_is_size_outside_tolerance():
    assert _is_size(16.8, 18.9) is False  # more than 1pt away


# ── chapter map ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def font_profile():
    import pdfplumber
    with pdfplumber.open(PDF_PATH) as pdf:
        return _build_font_profile(pdf)

@pytest.fixture(scope="module")
def chapter_map(font_profile):
    import pdfplumber
    with pdfplumber.open(PDF_PATH) as pdf:
        return _build_chapter_map(pdf, font_profile)

def test_chapter_map_finds_all_ten_chapters(chapter_map):
    chapter_nums = {v["chapter_num"] for v in chapter_map.values()}
    assert chapter_nums == set(range(1, 11)), f"Expected chapters 1-10, got {sorted(chapter_nums)}"

def test_chapter_map_chapter_one_starts_correct_page(chapter_map):
    # Chapter 1 starts on page 25 (1-indexed)
    ch1_entries = [v for v in chapter_map.values() if v["chapter_num"] == 1]
    assert ch1_entries, "Chapter 1 not found"
    assert ch1_entries[0]["first_page"] == 25

def test_chapter_map_has_titles(chapter_map):
    for ch_info in chapter_map.values():
        assert ch_info["chapter_title"], f"Chapter {ch_info['chapter_num']} has no title"

def test_chapter_map_chapter_one_title(chapter_map):
    ch1 = next(v for v in chapter_map.values() if v["chapter_num"] == 1)
    assert "Introduction" in ch1["chapter_title"]

def test_chapter_map_covers_body_pages(chapter_map):
    # Page 50 should be inside chapter 1 (pages 25-72)
    assert 50 in chapter_map
    assert chapter_map[50]["chapter_num"] == 1


# ── sentence_embedder ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def embedder():
    return SentenceEmbedder()

def test_embed_query_returns_384_dims(embedder):
    vec = embedder.embed_query("What is attention?")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert isinstance(vec[0], float)

def test_embed_documents_returns_correct_count(embedder):
    texts = ["First sentence.", "Second sentence.", "Third sentence."]
    vecs = embedder.embed_documents(texts)
    assert len(vecs) == 3
    assert all(len(v) == 384 for v in vecs)

def test_embed_query_different_texts_differ(embedder):
    v1 = embedder.embed_query("What is RAG?")
    v2 = embedder.embed_query("How do transformers work?")
    assert v1 != v2


# ── FAISS index output files ──────────────────────────────────────────────────

def test_faiss_index_files_exist():
    assert (OUTPUT_DIR / "index.faiss").exists(), "index.faiss missing — run ingest.py first"
    assert (OUTPUT_DIR / "index.pkl").exists(), "index.pkl missing"
    assert (OUTPUT_DIR / "parent_docs.pkl").exists(), "parent_docs.pkl missing"

def test_parent_docs_have_chapter_metadata():
    with open(OUTPUT_DIR / "parent_docs.pkl", "rb") as f:
        docs = pickle.load(f)
    # At least 80% of docs should have chapter metadata (front matter won't)
    with_chapter = [d for d in docs if d.metadata.get("chapter") is not None]
    ratio = len(with_chapter) / len(docs)
    assert ratio >= 0.8, f"Only {ratio:.0%} of docs have chapter metadata — expected ≥80%"

def test_parent_docs_chapter_titles_populated():
    with open(OUTPUT_DIR / "parent_docs.pkl", "rb") as f:
        docs = pickle.load(f)
    chapter_docs = [d for d in docs if d.metadata.get("chapter") is not None]
    missing_title = [d for d in chapter_docs if not d.metadata.get("chapter_title")]
    assert not missing_title, f"{len(missing_title)} docs have chapter but no chapter_title"

def test_parent_docs_all_ten_chapters_present():
    with open(OUTPUT_DIR / "parent_docs.pkl", "rb") as f:
        docs = pickle.load(f)
    chapters_found = {d.metadata["chapter"] for d in docs if d.metadata.get("chapter")}
    assert chapters_found == set(range(1, 11)), f"Found chapters: {sorted(chapters_found)}"

def test_faiss_index_loads_and_queries():
    from langchain_community.vectorstores import FAISS
    embedder = SentenceEmbedder()
    vs = FAISS.load_local(str(OUTPUT_DIR), embedder, allow_dangerous_deserialization=True)
    results = vs.similarity_search("retrieval augmented generation", k=3)
    assert len(results) == 3
    assert all(r.page_content.strip() != "" for r in results)

def test_faiss_chapter_filter_works():
    from langchain_community.vectorstores import FAISS
    embedder = SentenceEmbedder()
    vs = FAISS.load_local(str(OUTPUT_DIR), embedder, allow_dangerous_deserialization=True)
    # Chapter 6 is "RAG and Agents" — should surface RAG results when filtered
    results = vs.similarity_search(
        "retrieval augmented generation",
        k=5,
        filter={"chapter": 6},
    )
    assert len(results) > 0
    assert all(r.metadata.get("chapter") == 6 for r in results)
