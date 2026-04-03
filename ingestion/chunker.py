# ─────────────────────────────────────────────────────────────────────────────
# File: ingestion/chunker.py
# Purpose: Extract text from a PDF and split it into parent + child chunks
#          with accurate book/chapter/section/page metadata on every chunk.
#
#          Uses pdfplumber font-size metadata (not regex on plain text) because
#          most book PDFs don't use numbered headers — they're only
#          distinguishable by font size and font name.
#
#          Designed to generalise across O'Reilly-style PDFs. Font size
#          thresholds are derived empirically per-book (see _build_font_profile).
#
# Language: Python
# Connects to: config.py (chunk sizes), ingest.py (called from pipeline)
# Inputs:  pdf_path (str | Path), book_key (str), book_author (str)
# Outputs: list of (parent_doc, [child_doc, ...]) tuples
# ─────────────────────────────────────────────────────────────────────────────

import re
from collections import Counter
from pathlib import Path

import pdfplumber
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import (
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    PARENT_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
)

# ── Font size tolerances ───────────────────────────────────────────────────────
_SIZE_TOLERANCE = 1.0   # ± 1pt wiggle room for float variation across pages
_Y_TOLERANCE    = 3.0   # ± 3pt to group words onto the same line


def _is_size(word_size: float, target: float) -> bool:
    return abs(word_size - target) <= _SIZE_TOLERANCE


# ── Line grouping ─────────────────────────────────────────────────────────────

def _group_words_into_lines(words: list[dict], y_tol: float = _Y_TOLERANCE) -> list[list[dict]]:
    """
    Group a flat list of word dicts into lines by vertical proximity.
    Words are sorted by (top, x0) so left-to-right reading order is preserved.
    Two words are on the same line if their `top` values are within y_tol pts.
    """
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_y: float | None = None

    for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
        if current_y is None or abs(w["top"] - current_y) <= y_tol:
            current_line.append(w)
            current_y = w["top"] if current_y is None else current_y
        else:
            lines.append(current_line)
            current_line = [w]
            current_y = w["top"]

    if current_line:
        lines.append(current_line)

    return lines


# ── Font profile auto-detection ───────────────────────────────────────────────

def _build_font_profile(pdf: pdfplumber.PDF, sample_pages: int = 30) -> dict:
    """
    Auto-detect the font sizes used for chapter labels, chapter titles, and
    section headers by sampling the first `sample_pages` pages.

    Strategy:
    - Body text is the most common size → identify by frequency
    - Larger sizes above body are candidates for headers
    - "CHAPTER N" pattern → chapter label size
    - Largest non-body size on chapter pages → chapter title size
    - Mid-range non-body size → section header size

    Returns a dict: {body, chapter_label, chapter_title, section_header}
    All values are floats (pt sizes).
    """
    size_counts: Counter = Counter()
    chapter_page_sizes: list[float] = []   # sizes found on pages with "CHAPTER" text
    all_sizes: set[float] = set()

    pages_to_scan = min(sample_pages, len(pdf.pages))

    for page in pdf.pages[:pages_to_scan]:
        words = page.extract_words(extra_attrs=["fontname", "size"])
        for w in words:
            rounded = round(w["size"], 1)
            size_counts[rounded] += 1
            all_sizes.add(rounded)

        # Detect pages containing "CHAPTER" in any large-ish word
        large_words = [w for w in words if w["size"] > 12]
        text_large = " ".join(w["text"] for w in large_words)
        if re.search(r"CHAPTER\s+\d+", text_large, re.IGNORECASE):
            chapter_page_sizes.extend(round(w["size"], 1) for w in large_words)

    if not size_counts:
        raise ValueError("Could not extract any words from the PDF sample pages.")

    # Body = most common size (typically 10–11pt)
    body_size = size_counts.most_common(1)[0][0]

    # All sizes strictly above body are header candidates
    header_sizes = sorted(s for s in all_sizes if s > body_size + _SIZE_TOLERANCE)

    if not header_sizes:
        raise ValueError(
            f"No font sizes above body size ({body_size}pt) found. "
            "Cannot auto-detect header sizes."
        )

    # Chapter label ("CHAPTER N") — smallest above-body size on chapter pages.
    # Falls back to smallest header size overall.
    chapter_label_candidates = sorted(set(
        s for s in chapter_page_sizes if s > body_size + _SIZE_TOLERANCE
    ))
    chapter_label_size = chapter_label_candidates[0] if chapter_label_candidates else header_sizes[0]

    # Chapter title — the next distinct size above chapter_label on chapter pages.
    # We intentionally avoid the global max because cover/decorative text can be
    # very large (e.g. 68pt) and would be mistaken for the chapter title.
    chapter_title_candidates = sorted(set(
        s for s in chapter_page_sizes
        if s > chapter_label_size + _SIZE_TOLERANCE
    ))
    if chapter_title_candidates:
        chapter_title_size = chapter_title_candidates[0]   # smallest size above the label
    else:
        # Fallback: use the second-largest header size globally
        chapter_title_size = header_sizes[-2] if len(header_sizes) >= 2 else header_sizes[-1]

    # Section header — most frequent above-body size that is neither chapter_label
    # nor chapter_title. Frequency weighting is robust to one-off large text.
    section_candidates = {
        s for s in header_sizes
        if not _is_size(s, chapter_label_size) and not _is_size(s, chapter_title_size)
    }
    if section_candidates:
        section_counter = Counter(
            s for s in size_counts.keys() if any(_is_size(s, c) for c in section_candidates)
        )
        section_size = section_counter.most_common(1)[0][0] if section_counter else min(section_candidates)
    else:
        # Only chapter_label and chapter_title found — sections share chapter_title size
        section_size = chapter_title_size

    return {
        "body": body_size,
        "chapter_label": chapter_label_size,
        "chapter_title": chapter_title_size,
        "section_header": section_size,
    }


# ── Chapter map ───────────────────────────────────────────────────────────────

def _build_chapter_map(pdf: pdfplumber.PDF, font_profile: dict) -> dict[int, dict]:
    """
    Scan all pages and return a mapping of page_number (1-indexed) → chapter info.
    Each entry: {chapter_num, chapter_title, first_page}.
    Pages before the first chapter map to None.

    Raises AssertionError if fewer than 5 chapters are found (sanity gate).
    """
    chapters: list[dict] = []

    for page_num, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(extra_attrs=["fontname", "size"])
        lines = _group_words_into_lines(words)

        # Look for a line that reads "CHAPTER N" at chapter_label size
        chapter_num: int | None = None
        chapter_title_lines: list[str] = []

        for line in lines:
            line_text = " ".join(w["text"] for w in line)

            if all(_is_size(w["size"], font_profile["chapter_label"]) for w in line):
                m = re.search(r"CHAPTER\s+(\d+)", line_text, re.IGNORECASE)
                if m:
                    chapter_num = int(m.group(1))

            if all(_is_size(w["size"], font_profile["chapter_title"]) for w in line):
                chapter_title_lines.append(line_text.strip())

        if chapter_num is not None:
            chapter_title = " ".join(chapter_title_lines).strip()
            assert chapter_title, (
                f"Chapter {chapter_num} on page {page_num} has no title. "
                "Check font_profile['chapter_title'] size."
            )
            chapters.append(
                {
                    "chapter_num": chapter_num,
                    "chapter_title": chapter_title,
                    "first_page": page_num,
                }
            )

    assert len(chapters) >= 5, (
        f"Only {len(chapters)} chapter(s) detected — expected at least 5. "
        "Font profile may be wrong. Run with debug=True to inspect."
    )

    # Build page → chapter mapping
    total_pages = len(pdf.pages)
    page_to_chapter: dict[int, dict] = {}

    for i, ch in enumerate(chapters):
        start = ch["first_page"]
        end = chapters[i + 1]["first_page"] - 1 if i + 1 < len(chapters) else total_pages
        for p in range(start, end + 1):
            page_to_chapter[p] = ch

    return page_to_chapter


# ── Body text cleaning ────────────────────────────────────────────────────────

def _remove_header_lines(text: str, headers: list[str]) -> str:
    """
    Remove lines from extracted page text that are just header/footer noise:
    - Lines that match a known section header verbatim
    - Lines that look like page numbers (pure digits, possibly with whitespace)
    This prevents duplicate header text from appearing in the chunk body.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip pure page-number lines
        if re.fullmatch(r"\d+", stripped):
            continue
        # Skip lines that are just a known section header
        if any(h.lower() in stripped.lower() for h in headers if h):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# ── Section extraction ────────────────────────────────────────────────────────

def _extract_sections(
    pdf: pdfplumber.PDF,
    page_to_chapter: dict[int, dict],
    font_profile: dict,
    debug: bool = False,
) -> list[dict]:
    """
    Walk every page, detect section headers by font size + line grouping, and
    accumulate text into section blocks. Each section block carries:
      {text, chapter_num, chapter_title, section_title, page_number}

    A new section is only opened when the header text changes (prevents
    spurious flushes from noise or repeated headers across pages).
    """
    sections: list[dict] = []
    current: dict = {
        "text": "",
        "chapter_num": None,
        "chapter_title": None,
        "section_title": None,
        "page_number": 1,
    }

    for page_num, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(extra_attrs=["fontname", "size"])
        lines = _group_words_into_lines(words)
        chapter_info = page_to_chapter.get(page_num)
        plain_text = page.extract_text() or ""

        # Collect section-header lines: every word in the line must be at
        # section_header size. Take only distinct lines (dedup within page).
        section_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line and all(_is_size(w["size"], font_profile["section_header"]) for w in line):
                text = " ".join(w["text"] for w in line).strip()
                if text and text not in seen:
                    section_lines.append(text)
                    seen.add(text)

        if debug and page_num <= 50:
            print({
                "page": page_num,
                "chapter": chapter_info["chapter_num"] if chapter_info else None,
                "section_lines": section_lines,
            })

        # Clean body text — strip out header lines and page numbers
        clean_text = _remove_header_lines(plain_text, section_lines)

        # Use only the first valid section header on this page to open a new
        # section. Subsequent headers on the same page get folded into the body.
        new_title = section_lines[0] if section_lines else None

        if new_title and new_title != current.get("section_title"):
            # Flush current section before starting a new one
            if current["text"].strip():
                sections.append(current)
            current = {
                "text": clean_text + "\n",
                "chapter_num": chapter_info["chapter_num"] if chapter_info else None,
                "chapter_title": chapter_info["chapter_title"] if chapter_info else None,
                "section_title": new_title,
                "page_number": page_num,
            }
        else:
            # No new section — append to current, update chapter if we just
            # crossed a chapter boundary
            if chapter_info and current["chapter_num"] is None:
                current["chapter_num"] = chapter_info["chapter_num"]
                current["chapter_title"] = chapter_info["chapter_title"]
            current["text"] += clean_text + "\n"

    if current["text"].strip():
        sections.append(current)

    # ── Post-extraction quality assertions ────────────────────────────────────
    chapters_found = {s["chapter_num"] for s in sections if s["chapter_num"] is not None}
    assert len(chapters_found) >= 5, (
        f"Sections only cover {len(chapters_found)} chapter(s). "
        f"Chapters found: {sorted(chapters_found)}"
    )

    short_sections = [s for s in sections[:10] if len(s["text"]) < 200]
    assert not short_sections, (
        f"{len(short_sections)} of the first 10 sections have < 200 chars. "
        "Something may be wrong with text extraction."
    )

    print(f"[chunker] Chapters in sections: {sorted(chapters_found)}")

    return sections


# ── Public entry point ────────────────────────────────────────────────────────

def chunk_pdf(
    pdf_path: Path,
    book_key: str,
    book_author: str,
    debug: bool = False,
) -> list[tuple[Document, list[Document]]]:
    """
    Main entry point. Returns list of (parent_doc, [child_docs]) tuples.

    - Parent docs: ~2048-char sections returned to LLM agents for context
    - Child docs:  ~512-char sub-chunks embedded into FAISS for retrieval
    Both carry identical metadata so child→parent expansion works by metadata match.

    Set debug=True to print per-page chapter/section detection for the first 50 pages.
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE,
        chunk_overlap=PARENT_CHUNK_OVERLAP,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE,
        chunk_overlap=CHILD_CHUNK_OVERLAP,
    )

    with pdfplumber.open(pdf_path) as pdf:
        print("[chunker] Auto-detecting font profile...")
        font_profile = _build_font_profile(pdf)
        print(f"[chunker] Font profile: {font_profile}")

        page_to_chapter = _build_chapter_map(pdf, font_profile)
        print(f"[chunker] Detected {len({v['chapter_num'] for v in page_to_chapter.values()})} chapters")

        sections = _extract_sections(pdf, page_to_chapter, font_profile, debug=debug)

    results: list[tuple[Document, list[Document]]] = []

    for section in sections:
        parent_texts = parent_splitter.split_text(section["text"])

        for parent_idx, parent_text in enumerate(parent_texts):
            parent_meta = {
                "book": book_key,
                "author": book_author,
                "chapter": section["chapter_num"],
                "chapter_title": section["chapter_title"],
                "section": section["section_title"],
                "page_number": section["page_number"],
                "parent_chunk_index": parent_idx,
            }
            parent_doc = Document(page_content=parent_text, metadata=parent_meta)

            child_texts = child_splitter.split_text(parent_text)
            child_docs = [
                Document(
                    page_content=child_text,
                    metadata={**parent_meta, "child_chunk_index": child_idx},
                )
                for child_idx, child_text in enumerate(child_texts)
            ]

            results.append((parent_doc, child_docs))

    return results
