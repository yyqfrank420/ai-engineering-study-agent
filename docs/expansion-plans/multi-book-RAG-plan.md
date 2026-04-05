# Multi-Book RAG Scalability Plan

## Executive Summary

Adding **Designing Data-Intensive Applications** (DDIA) to complement "AI Engineering" is **moderately difficult** — not because of architectural flaws, but because the system was purpose-built for one book. The underlying infrastructure actually supports multi-book, but the implementation is tightly coupled.

**Effort Estimate:** 1–2 weeks for production-ready multi-book support

---

## Coupling Analysis by Component

### Backend

#### 1. System Prompts (HIGH EFFORT — 3–4 days)

**Current State:** Every LLM prompt is hardcoded to "AI Engineering"

```python
# graph_worker.py line 36-39 (appears in 3+ files)
_SYSTEM = """<role>
You are the graph planner for the book "AI Engineering" by Chip Huyen.
```

Affected files:
- `backend/agent/nodes/graph_worker.py` — graph generation
- `backend/agent/nodes/orchestrator_node.py` — routing, synthesis (8+ hardcoded refs)
- `backend/agent/nodes/node_detail_worker.py` — node enrichment
- Hardcoded references: "AI Engineering" (22×), "Chip Huyen" (7×), "O'Reilly" (2×)

**Fix:** Parameterize all system prompts to inject active book dynamically:
```python
_SYSTEM = f"""<role>
You are the graph planner for the book "{book_name}" by {book_author}.
```

**Risk:** Inference quality depends on prompt quality per book — requires testing each book's prompts separately.

---

#### 2. FAISS Index Loading (HIGH EFFORT — 3–5 days)

**Current State:** Loads one index at startup

```python
# main.py
vectorstore = FAISSVectorStore.load("data/faiss/")
```

**Option A: Metadata-Filtered Single Index (RECOMMENDED)**
- Ingest both books into one FAISS index during build
- Each chunk carries metadata: `{"book": "AI Engineering", ...}`
- At query time: `faiss.similarity_search(query, filter={"book": active_book})`
- Metadata infrastructure already exists in chunk schema
- **Pros:** Simpler, one artifact, existing infrastructure
- **Cons:** Index grows with each book (~7MB per book)
- **Effort:** 3 days (ingestion refactor + filter logic)

**Option B: Separate Indices Per Book**
- Load multiple FAISS instances in a dict: `{"AI Engineering": index1, "DDIA": index2}`
- Route queries by book name
- **Pros:** Isolated, independent updates
- **Cons:** More memory, index management overhead
- **Effort:** 4 days (loader refactor, routing logic)

**Files to modify:**
- `backend/rag/faiss_loader.py` — load multiple indices
- `backend/rag/faiss_artifact.py` — artifact management
- `backend/main.py` — initialization

---

#### 3. RAG Filtering (MEDIUM EFFORT — 1–2 days)

**Current State:** Retrieval tool supports metadata filters but never uses them

```python
# rag_search_tool.py
child_results = vectorstore.similarity_search(query, k=k, filter=filter)
# filter=None always
```

**Fix:** Pass book filter from AgentState

```python
filter = {"book": state.book}  # from chat_threads.book_id
child_results = vectorstore.similarity_search(query, k=k, filter=filter)
```

**Files to modify:**
- `backend/agent/tools/rag_worker_tools/rag_search_tool.py`
- `backend/agent/state.py` — add `book: str` field

---

#### 4. Database Schema (LOW EFFORT — 1 day)

**Current State:** No book tracking

```sql
-- chat_threads table (no book field)
create table if not exists public.chat_threads (
  id uuid primary key,
  user_id uuid not null,
  title text not null,
  graph_data jsonb,
  created_at timestamptz,
  updated_at timestamptz,
  last_seen_at timestamptz
);
```

**Fix:** Add `book_id` field

```sql
ALTER TABLE chat_threads ADD COLUMN book_id VARCHAR DEFAULT 'AI Engineering';
ALTER TABLE chat_messages ADD COLUMN book_id VARCHAR;
```

**Files to modify:**
- `docs/supabase/schema.sql`
- `backend/storage/thread_store.py` — add filtering by book
- `backend/storage/message_store.py` — add filtering by book

---

#### 5. API Routes (LOW EFFORT — 1 day)

**Current State:** Thread creation doesn't accept book parameter

**Fix:** Accept book in API

```python
# thread_route.py
POST /api/threads?book=DDIA

thread.book_id = request.query_params.get("book", "AI Engineering")
```

**Files to modify:**
- `backend/api/thread_route.py` — add book parameter validation
- `backend/api/sse_handler.py` — pass book through request

---

#### 6. Ingestion Pipeline (MEDIUM EFFORT — 2–3 days)

**Current State:** Single-book ingestion

```python
# ingestion/config.py
BOOKS = {
    "AI Engineering": {
        "author": "Chip Huyen",
        "key": "AI Engineering",
    },
}
```

**Fix:** Support multiple books

```python
BOOKS = {
    "AI Engineering": {
        "author": "Chip Huyen",
        "key": "AI Engineering",
    },
    "DDIA": {
        "author": "Martin Kleppmann",
        "key": "DDIA",
    },
}
```

Then ingest both:
```bash
python ingestion/ingest.py --pdf "path/to/ai-engineering.pdf" --book "AI Engineering"
python ingestion/ingest.py --pdf "path/to/ddia.pdf" --book "DDIA"
```

**Files to modify:**
- `ingestion/config.py` — add book registry
- `ingestion/ingest.py` — multi-book ingestion
- `scripts/package_faiss_artifact.py` — bundle multiple books

---

### Frontend

#### 1. Book Selector Dropdown (2 days)

**Current State:** No way to choose which book

**Fix:** Add dropdown to ModeBar or TitleBar

```tsx
<select onChange={(e) => setActiveBook(e.target.value)} value={activeBook}>
  <option value="AI Engineering">AI Engineering</option>
  <option value="DDIA">Designing Data-Intensive Applications</option>
</select>
```

When user switches books:
- Fetch threads filtered by book: `GET /api/threads?book=DDIA`
- Update thread list
- Pass `book` to thread creation API

**Files to modify:**
- `frontend/src/App.tsx` — add `activeBook` state
- `frontend/src/components/Layout/ModeBar.tsx` or `TitleBar.tsx` — add dropdown

---

#### 2. Dynamic Title Display (1 day)

**Current State:** Hardcoded "AI Engineering" and "Chip Huyen"

```tsx
// TitleBar.tsx
<span>AI Engineering</span>
<span>Chip Huyen · O'Reilly</span>
```

**Fix:** Parameterize with book registry

```tsx
const books = {
  "AI Engineering": {
    title: "AI Engineering",
    author: "Chip Huyen",
    publisher: "O'Reilly"
  },
  "DDIA": {
    title: "Designing Data-Intensive Applications",
    author: "Martin Kleppmann",
    publisher: "O'Reilly"
  }
};

<span>{books[activeBook].title}</span>
<span>{books[activeBook].author} · {books[activeBook].publisher}</span>
```

Also update:
- `frontend/index.html` — page title
- `frontend/vite.config.ts` — if relevant

**Files to modify:**
- `frontend/src/components/Layout/TitleBar.tsx`
- `frontend/index.html`
- `frontend/src/App.tsx` — book registry config

---

#### 3. Thread Filtering by Book (1–2 days)

**Current State:** All threads assumed to be for same book

**Fix:** Filter thread list by active book

```tsx
// Before:
const threads = await fetch("/api/threads");

// After:
const threads = await fetch(`/api/threads?book=${activeBook}`);
```

When switching books:
- Reload thread list
- If no threads exist for that book, show empty state with CTA to create one

**Files to modify:**
- `frontend/src/App.tsx` — add book parameter to thread fetch
- `frontend/src/components/ThreadList.tsx` — display threads per book

---

#### 4. No Changes Required for SSE Streaming

The SSE endpoint already has access to thread context via `thread_id`:
```tsx
POST /api/chat with thread_id
```

Backend looks up `thread.book_id` from database, so the frontend doesn't need to pass it explicitly.

---

## Frontend User Experience

✅ **Same experience as before**
- Users see familiar interface
- Book selector is a simple dropdown
- Thread isolation by book is automatic
- No new workflows or complexity

---

## Implementation Roadmap

### Phase 1: Foundation (3 days)
1. Add `book_id` to database schema + migration
2. Update thread/message storage to filter by book
3. Parameterize system prompts with book name from AgentState
4. Add `book` field to AgentState

**Deliverable:** Backend can accept and store book context, prompts reference active book

### Phase 2: Ingestion (2 days)
1. Extend ingestion config to support multiple books
2. Ingest DDIA alongside AI Engineering
3. Merge into single FAISS index with book metadata (or use separate indices per Option A/B)

**Deliverable:** Two books ingested, available for querying

### Phase 3: Backend Filtering (3 days)
1. Refactor FAISS loader to support metadata filtering
2. Pass book filter from AgentState to RAG retrieval tool
3. Update API routes to accept `book` parameter in thread creation
4. Add book validation and error handling

**Deliverable:** Backend can route queries by book, metadata filtering works

### Phase 4: Frontend (4 days)
1. Add book selector dropdown (ModeBar or TitleBar)
2. Dynamic title/author display based on active book
3. Thread list filtering by book
4. Update page title and branding
5. QA and testing

**Deliverable:** Users can switch between books, see isolated thread lists, experience consistent branding

**Total Effort:** ~2 weeks

---

## Risk Assessment

| Component | Risk Level | Mitigation |
|-----------|-----------|-----------|
| System prompt quality per book | Medium | Test prompts thoroughly with DDIA; iterate if needed |
| FAISS metadata filtering | Medium | Verify filter semantics in FAISS docs; test with sample queries |
| Ingestion consistency | Medium | Ensure DDIA chunking matches AI Engineering quality; compare embeddings |
| Database migration | Low | Add column with default, reversible |
| Frontend UI changes | Low | Isolated, no backend impact, easy to test |
| Deployment artifact size | Low | ~7MB per book, acceptable overhead |

---

## Hardcoded References Checklist

Search-and-replace to enable multi-book:

- [ ] `"AI Engineering"` (22 occurrences)
  - [ ] `backend/agent/nodes/graph_worker.py`
  - [ ] `backend/agent/nodes/orchestrator_node.py`
  - [ ] `frontend/src/components/Layout/TitleBar.tsx`
  - [ ] `frontend/index.html`

- [ ] `"Chip Huyen"` (7 occurrences)
  - [ ] `backend/agent/nodes/orchestrator_node.py`
  - [ ] `frontend/src/components/Layout/TitleBar.tsx`

- [ ] `"O'Reilly"` (2 occurrences)
  - [ ] `frontend/src/components/Layout/TitleBar.tsx`

All should be parameterized or moved to a book registry config.

---

## Key Design Decision: Single Index vs. Multiple Indices

### Recommended: Metadata-Filtered Single Index

**Architecture:**
```
FAISS Index (merged)
├─ AI Engineering chapters (chunks with book="AI Engineering")
└─ DDIA chapters (chunks with book="DDIA")

At query time:
  results = faiss.similarity_search(query, filter={"book": active_book})
```

**Why:**
1. Simpler retrieval logic (one search)
2. One artifact to bundle and deploy
3. Existing metadata infrastructure in chunks
4. Metadata already supports this (`book` field exists)

**Trade-offs:**
- Index grows linearly with books (~7MB per 400-page book)
- Filter performance depends on FAISS (usually fine for reasonable selectivity)

**Alternative: Separate Indices**
- Use if > 5 books or if book-specific tuning is needed
- More complex routing logic, more memory overhead

---

## Success Criteria

- [ ] Users can select which book to interact with
- [ ] Threads are isolated by book (no cross-book contamination)
- [ ] RAG retrieval filters by book (search results only from active book)
- [ ] System prompts reference active book, not hardcoded "AI Engineering"
- [ ] All staging eval tests pass for both books
- [ ] Frontend displays correct title/author per book
- [ ] Thread list updates when switching books
- [ ] Performance is acceptable (< 200ms SSE latency per query)

---

## Next Steps

1. **Week 1:** Implement Phase 1 (database schema + system prompt parameterization)
2. **Week 1–2:** Implement Phase 2 (ingestion + FAISS merging)
3. **Week 2:** Implement Phase 3 (backend filtering + API updates)
4. **Week 2:** Implement Phase 4 (frontend UI + testing)
5. **Staging:** Run eval suite against both books before production

---

## Appendix: Code References

### Current Hardcoded References

**graph_worker.py (lines 36–39):**
```python
_SYSTEM = """<role>
You are the graph planner for the book "AI Engineering" by Chip Huyen.
```

**orchestrator_node.py (lines 20–139):**
```python
"specialised in the book "AI Engineering" by Chip Huyen"
"study assistant for "AI Engineering" by Chip Huyen (O'Reilly)"
"concise study assistant for "AI Engineering" by Chip Huyen (O'Reilly)"
```

**TitleBar.tsx (lines 67–76):**
```tsx
<span style={{...}}>
  AI Engineering
</span>
<span style={{...}}>
  Chip Huyen · O'Reilly
</span>
```

All instances should be replaced with parameterized versions or moved to a book registry config object.

---

## Document Metadata

- **Date Created:** 2026-04-05
- **Status:** Planning phase
- **Priority:** P2 (nice-to-have, not blocking current feature work)
- **Owner:** TBD
- **Review:** Required before Phase 1 starts
