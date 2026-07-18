# AI Engineering Study Agent — Design Spec
**Date:** 2026-03-31
**Status:** Approved

> Historical design snapshot. Significant parts of this spec are now stale:
> the shipped runtime now uses LangGraph plus steerable WebSocket chat; the
> persistence/auth model is Supabase-backed, not browser `session_id` + SQLite;
> and the current cost-first deploy target is Cloud Run, not Render.

---

## Context

A personal AI-powered study tool for working through Chip Huyen's *AI Engineering* (O'Reilly). The agent does RAG over the book PDF, answers questions, and generates interactive D3.js knowledge graphs (architecture diagrams and concept breakdowns) directly in the UI. Nodes are clickable — each surfaces book citations and detailed explanations. The interface is designed to feel like a learning product (Figma-clean, dark mode, interactive). Future books (e.g., *Designing ML Systems*) will be added when the core is working.

**Migration path:** Designed to port cleanly to AWS (ECS Fargate + Bedrock + DynamoDB). All infrastructure-touching code is behind adapter interfaces.

---

## 1. Architecture

### Stack

| Layer | Technology | Cost |
|---|---|---|
| Frontend | React + D3.js (Vite) | Vercel free |
| Backend | FastAPI + LangGraph | Render Starter — $7/mo |
| Persistent storage | SQLite on Render Persistent Disk | $0.25/mo |
| Vector store | FAISS in-memory (loaded from Persistent Disk) | Included |
| LLM | Anthropic API (`claude-sonnet-4-6`, `claude-haiku-4-5`) | Pay-per-token |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, CPU) | Free |
| **Total fixed** | | **$7.25/mo** |

### Request Flow

```
Browser (Vercel)
  └── POST /chat?session_id={uuid}  (SSE — text/event-stream)
        └── FastAPI SSE handler (Render) — sse_handler.py
              └── LangGraph agent
                    ├── Orchestrator (Sonnet 4.6)
                    ├── RAG Worker (Haiku 4.5) ──┐ parallel
                    ├── Graph Worker (Haiku 4.5) ─┤
                    └── N × Node Detail Workers ──┘ (async, post-graph)

                    ↓ stream events back via SSE (text/event-stream)
              LangGraph state → SQLite (SqliteSaver)
```

Note: Frontend hook is named `useWebSocket.ts` but uses the `sse.ts` fetch-based client internally (custom because `EventSource` only supports GET, not POST).

### Session Identity (no auth)

- Browser generates `session_id = crypto.randomUUID()` on first visit, stored in `localStorage`
- Sent as query param on each request: `POST /chat?session_id=abc123`
- FastAPI extracts `session_id`, uses it as the SQLite partition key
- Sessions persist as long as the same browser/localStorage is used

### AWS Migration Shim

All infra calls (LLM, database) route through `backend/adapters/`. Swapping providers = changing env vars + adapter implementation, not business logic.

| Current | AWS equivalent |
|---|---|
| `anthropic` SDK | Bedrock Converse Stream API |
| SQLite (SqliteSaver) | DynamoDB (LangGraph DynamoDB checkpointer) |
| SSE (StreamingResponse) | API GW WebSocket + Lambda `postToConnection`, or ALB streaming |

---

## 2. Agent Design

### Model Split

| Agent | Model | Role |
|---|---|---|
| Orchestrator | `claude-sonnet-4-6` | Routing, planning, response synthesis |
| RAG Worker | `claude-haiku-4-5` | FAISS retrieval + citation formatting |
| Graph Worker | `claude-haiku-4-5` | Graph skeleton JSON generation |
| Node Detail Worker | `claude-haiku-4-5` | Per-node enrichment (runs N×parallel) |

Thinking: enabled for Orchestrator routing only (`budget_tokens=5000`); **disabled for synthesis** (cost reduction — synthesis uses bullet-point format, thinking adds ~$0.075/query at Sonnet 4.6 rates). All agents have tool calls configured.

### 4-Phase Execution Pipeline

**Phase 0 — Intent Router** (Orchestrator, Sonnet)
Decides: can this message be answered from short-term memory?
- Sources: full session history (SQLite), current graph state, cached RAG results from prior turns
- If yes → skip to synthesis (fast path)
- If no → fan out to Phase 1 workers

**Phase 1 — Parallel Workers** (only if Phase 0 decides search needed)
- RAG Worker: FAISS search + metadata filter → returns chunks with book/chapter/page citations
- Graph Worker: classifies intent (architecture/concept/none) + generates graph skeleton `{nodes[], edges[], sequence[]}`
- Both run concurrently via `asyncio.gather`

**Phase 2 — Synthesis + Graph Delivery**
- Orchestrator receives Phase 1 outputs
- Sends `graph_data` WebSocket event immediately → D3 renders graph skeleton
- Orchestrator streams response text via `response_delta` events
- `done` fires when text response is complete

**Phase 3 — Async Node Enrichment** (non-blocking)
- N × Node Detail Workers (capped at 10), one per graph node, all via `asyncio.gather`
- Each sends `node_detail` event as it completes
- Frontend progressively fills in node cards; incomplete nodes show a spinner
- Does NOT block `done` or user input

### Tools (per-agent, intentionally decoupled)

**RAG Worker tools** (`rag_worker_tools/`):
- `rag_search_tool(query: str, k: int = 5, filter: dict | None) → list[Chunk]`  _(k reduced from 8, config-driven via `settings.rag_top_k`)_
- `get_section_tool(book: str, chapter: int, section: str | None) → list[Chunk]`

**Graph Worker tools** (`graph_worker_tools/`):
- `generate_graph_tool(graph_type: "architecture"|"concept", title: str, nodes: list[Node], edges: list[Edge], sequence: list[Step]) → GraphData`
- `get_section_tool(...)` — duplicate, intentionally decoupled

**Node Detail Worker tools** (`node_detail_worker_tools/`):
- Uses `rag_search_tool` (same tool as RAG Worker, bound at runtime)
- Two searches per node: primary by label (k=4), secondary by label + edge labels (k=2)
- Parses `(Chapter N, p.X)` citations from generated text → `book_refs[]`

> Tools use OpenAPI schemas (JSON Schema) for future MCP layer portability.

### Graph JSON Schema

```json
{
  "graph_type": "architecture | concept",
  "title": "Attention Mechanism",
  "nodes": [
    {
      "id": "query",
      "label": "Query Vector",
      "type": "concept | component | input | output",
      "detail": null  // populated by Node Detail Worker async
    }
  ],
  "edges": [
    {
      "source": "attention", "target": "query", "label": "computes",
      "protocol": "REST|gRPC|WebSocket|event|queue|stream|internal",
      "port": "443",           // optional — omit if not applicable
      "description": "one sentence describing what flows here"
    }
  ],
  "sequence": [
    {"step": 0, "nodes": ["input"], "description": "Input tokens"},
    {"step": 1, "nodes": ["query", "key", "value"], "description": "Linear projections"}
  ]
}
```

### WebSocket Event Protocol

Server → Browser:

| Event type | Payload | When |
|---|---|---|
| `worker_status` | `{worker: "rag", status: "Searching…"}` | Phase 1 start |
| `thinking_delta` | `{content: "…"}` | Orchestrator thinking (selective) |
| `response_delta` | `{content: "token"}` | Main response stream |
| `graph_data` | Full graph JSON | Phase 2, fires immediately |
| `node_detail` | `{node_id, description, book_refs[]}` | Phase 3, per node async |
| `suggested_questions` | `{questions: ["…", "…", "…"]}` | After node_selected event |
| `done` | — | Phase 2 complete |

Browser → Server:

| Event type | Payload |
|---|---|
| `message` | `{content: "user message text"}` |
| `node_selected` | `{node_id, title, description}` |

---

## 3. RAG System

### Ingestion Pipeline (`ingestion/`)

Run once locally per book. Output stored on Render Persistent Disk.

```
PDF
  → pdfplumber (extract text + page numbers)
  → chunker.py
      ├── Parent chunks: RecursiveCharacterTextSplitter(chunk_size=2048, overlap=200)
      └── Child chunks:  RecursiveCharacterTextSplitter(chunk_size=512,  overlap=50)
      Both splitters use section boundaries as primary split points (chapter/section headers)
  → sentence_embedder.py (embeds child chunks only, all-MiniLM-L6-v2, 384 dimensions)
  → LangChain ParentDocumentRetriever
      ├── FAISS vectorstore (child chunk vectors) → index.faiss + index.pkl
      └── InMemoryStore (parent chunk text) → parent_docs.pkl
  → saves all three files to /data/faiss/
```

**Retrieval at query time:** FAISS matches best child chunks → retriever expands to parent section → full section text delivered to worker agents.

**Why hierarchical over flat/semantic:** Complex study questions and graph node detail generation need surrounding context (full section), not just the matching sentence. `ParentDocumentRetriever` provides retrieval precision (child) + context richness (parent) in one call.

### Chunk Metadata Schema

```python
{
    "book": "AI Engineering",
    "author": "Chip Huyen",
    "chapter": 4,
    "chapter_title": "Retrieval-Augmented Generation",
    "section": "4.2",
    "section_title": "Chunking Strategies",
    "page_number": 112,
    "chunk_index": 3
}
```

### Retrieval

- `ParentDocumentRetriever.get_relevant_documents(query, filter={"book": "...", "chapter": N})`
- Under the hood: FAISS child search (k=8) + filter → expand to parent sections
- Multi-book: single combined FAISS index, filter by `book` metadata key

### Disk Layout (Render Persistent Disk, mounted at `/data`)

```
/data/
├── faiss/
│   ├── index.faiss          # child chunk vectors
│   ├── index.pkl            # child docstore (chunk text + metadata)
│   └── parent_docs.pkl      # parent docstore (full sections, pickled InMemoryStore)
└── sessions.db              # SQLite
```

---

## 4. Frontend

### Tech Stack

- **Vite + React + TypeScript**
- **D3.js** — force-directed graph, pan/zoom, sequence animation
- **KaTeX** (`react-katex`) — inline LaTeX rendering for math formulas
- **Shiki** — syntax-highlighted code blocks
- **`react-split-pane`** (or custom) — draggable resize handle

### Layout

```
┌─────────────────────────────────────────┬──────────────────────┐
│ [graph icon] Knowledge Graph  7n · 8e   │ [chat icon] Chat     │
├─────────────────────────────────────────┤                      │
│                                         │  [user msg]          │
│           D3 Force Graph                │  [thinking…]         │
│                                         │  [agent response]    │
│  [node popup when clicked]              │    $softmax(QK^T/√d)$│
│                                         │  [graph card badge]  │
├─────────────────────────────────────────┤                      │
│ ─●──────────────────── Sequence ──▶     │  [context bar: ⊙ V] │
│  Step 2/5: Linear projections           │  [suggestion chips]  │
│                                         │  ┌─────────────────┐ │
│                                         │  │ Ask a question… │↑│
│                                         │  └─────────────────┘ │
└─────────────────────────────────────────┴──────────────────────┘
```

**Graph pane (left):** min-width ~50%, resizable up to ~80%.
**Chat pane (right):** min 1/5 screen, max 1/2 screen. Resize handle between panes.

### Key UI Behaviors

**D3 Graph (AWS architecture diagram style):**
- Force-directed layout with left-to-right type bias (`input` → `component` → `output`)
- Pan + scroll-to-zoom on the canvas
- **Node visual:** outlined card (transparent fill ~12% opacity, solid colored border, left accent stripe)
  - `input` = blue, `component` = violet, `concept` = amber, `output` = emerald
  - Type badge top-left inside card, white label centered
- **Click node** → `NodeDetail` popup (right-anchored):
  - Description with loading spinner (progressive as `node_detail` events arrive)
  - Book references (parsed `(Chapter N, p.X)` citations)
  - Connections list (in/out edges with protocol badge)
  - Sends `node_selected` to server
- **Hover edge** → tooltip overlay shows: protocol, port, label, description
  - Wide invisible hit area (14px) for easier hover targeting
- Sequence scrubber dims non-active nodes to 15% opacity

**Sequence Playback Bar (graph pane footer):**
- Horizontal scrubber (0 → N steps)
- Dragging scrubber dims non-active-step nodes to 20% opacity, highlights active nodes
- Step label below scrubber: "Step 2/5: Linear projections"
- Only visible when `graph.sequence.length > 1`

**Node Selection → Chat Bridge:**
- Click node → context pill appears at top of chat: `⊙ Value Matrix`
- Server receives `node_selected` event → Orchestrator generates 3 predicted questions
- `suggested_questions` event → 3 clickable chips below context pill
- Clicking chip → sends as new message with node context pre-loaded

**LaTeX + Code:**
- Messages scanned for `$...$` (inline) and `$$...$$` (block) → KaTeX render
- Fenced code blocks → Shiki with syntax highlighting
- LLM instructed to use LaTeX for all math in system prompt

### Naming Conventions (frontend)

- Components: PascalCase, folder named by component (e.g., `GraphCanvas/index.tsx`, `GraphCanvas/SequenceBar.tsx`)
- Hooks: camelCase prefixed `use` (e.g., `useWebSocket`, `useGraph`)
- Services: camelCase (e.g., `websocket.ts`)
- Types: PascalCase interfaces in `types/index.ts`

---

## 5. Security

### Rate Limiting (`slowapi`)

- Library: `slowapi` (FastAPI integration, in-memory sliding window — no Redis needed)
- Limits applied per `session_id` (not IP — IP can be shared behind NAT):
  - **WebSocket messages:** 20 requests/minute, 100 requests/hour
  - **Payload size:** reject messages > 2KB before processing
- 429 responses close the WebSocket with an informative reason string

```python
from slowapi import Limiter
limiter = Limiter(key_func=lambda ws: ws.query_params.get("session_id", "anon"))
```

### Prompt Injection Detection (`llm-guard`)

- Library: `llm-guard` — `PromptInjectionScanner` on every incoming user message
- Threshold: 0.85 confidence → reject with `{"type": "error", "content": "Message blocked"}`
- Runs before the message reaches any LLM call (pre-LLM gate in `websocket_handler.py`)

```python
from llm_guard.input_scanners import PromptInjection
scanner = PromptInjection(threshold=0.85)
sanitized, is_valid, risk_score = scanner.scan(prompt="", output=user_message)
```

### System Prompt Hardening

All agent system prompts include:
- Instruction to ignore attempts to reveal system prompts, API keys, or internal tools
- Instruction to stay on-topic (AI engineering study only)
- Instruction to refuse requests to generate harmful, misleading, or off-topic content

### Output Validation

- `llm-guard` `BanSubstrings` output scanner: block responses containing `sk-ant-`, `ANTHROPIC_API_KEY`, or other secret patterns
- Applied in `llm_adapter.py` after every LLM response before sending to frontend

### Environment Variables (Render)

All secrets via Render environment variables, never in code:
- `ANTHROPIC_API_KEY`
- `SESSION_SECRET` (optional signing key for session IDs)
- `DATA_DIR` (mount path for Persistent Disk, default `/data`)

---

## 6. Folder Structure

```
agent/
├── frontend/                              # → Vercel
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── index.tsx             # Chat panel container
│   │   │   │   ├── MessageList.tsx       # Renders messages + LaTeX
│   │   │   │   ├── ChatInput.tsx         # Input bar + send button
│   │   │   │   ├── ContextBar.tsx        # Node selection pill + suggestion chips
│   │   │   │   └── ThinkingIndicator.tsx # Muted streaming thinking display
│   │   │   ├── GraphCanvas/
│   │   │   │   ├── index.tsx             # Graph pane container
│   │   │   │   ├── D3Graph.tsx           # D3 force graph (ref-based)
│   │   │   │   ├── NodeDetailPopup.tsx   # Click popup with citation
│   │   │   │   └── SequenceBar.tsx       # Playback scrubber
│   │   │   └── Layout/
│   │   │       ├── SplitPane.tsx         # Resizable two-pane layout
│   │   │       └── TitleBar.tsx          # App header + book badge
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts           # WS connection + typed event dispatch
│   │   │   └── useGraph.ts               # Graph state + sequence playback state
│   │   ├── services/
│   │   │   └── websocket.ts              # WS client, reconnect, event types
│   │   ├── types/
│   │   │   └── index.ts                  # GraphData, Message, NodeDetail, etc.
│   │   └── App.tsx
│   ├── vite.config.ts
│   ├── package.json
│   └── vercel.json
│
├── backend/                              # → Render Starter
│   ├── agent/
│   │   ├── graph.py                      # LangGraph compiled graph
│   │   ├── state.py                      # AgentState TypedDict
│   │   ├── nodes/
│   │   │   ├── orchestrator_node.py      # Sonnet 4.6: router + synthesis
│   │   │   ├── rag_worker.py             # Haiku 4.5: FAISS retrieval
│   │   │   ├── graph_worker.py           # Haiku 4.5: graph skeleton
│   │   │   └── node_detail_worker.py     # Haiku 4.5: per-node enrichment
│   │   └── tools/
│   │       ├── rag_worker_tools/
│   │       │   ├── rag_search_tool.py
│   │       │   └── get_section_tool.py
│   │       ├── graph_worker_tools/
│   │       │   ├── generate_graph_tool.py
│   │       │   └── get_section_tool.py   # decoupled duplicate
│   │       └── node_detail_worker_tools/
│   │           └── get_section_tool.py   # decoupled duplicate
│   ├── api/
│   │   ├── websocket_handler.py          # WS endpoint + event streaming loop
│   │   └── health_route.py              # GET /health (Render health check)
│   ├── rag/
│   │   ├── faiss_retriever.py           # similarity_search with filter
│   │   ├── sentence_embedder.py         # all-MiniLM-L6-v2 wrapper
│   │   └── faiss_loader.py             # load index.faiss + index.pkl from /data
│   ├── storage/
│   │   ├── session_store.py            # SqliteSaver: session CRUD
│   │   └── history_store.py            # Conversation history per session_id
│   ├── adapters/
│   │   ├── llm_adapter.py             # Anthropic SDK (→ Bedrock ConversStream)
│   │   └── database_adapter.py        # SQLite (→ DynamoDB)
│   ├── config.py                       # pydantic-settings: env vars
│   ├── main.py                         # FastAPI app + lifespan hook (load FAISS)
│   ├── requirements.txt
│   └── Dockerfile
│
├── ingestion/                           # run locally once per book
│   ├── ingest.py                       # PDF → chunks → embed → FAISS → /data
│   ├── chunker.py                      # chunking + section boundary detection
│   ├── config.py                       # chunk_size=500, overlap=50
│   └── requirements.txt
│
└── docs/
    └── superpowers/specs/
        └── 2026-03-31-ai-study-agent-design.md
```

---

## 7. Coding Standards

All files open with a header block:
```python
# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/rag_worker.py
# Purpose: RAG retrieval worker — searches FAISS index, returns book chunks
# Language: Python
# Connects to: faiss_retriever.py (retrieval), sentence_embedder.py (query embed)
# Inputs: AgentState with user message + optional metadata filter
# Outputs: list[Chunk] with text + book/chapter/page metadata
# ─────────────────────────────────────────────────────────────────────────────
```

File naming: `_worker`, `_node`, `_tool`, `_store`, `_adapter`, `_handler`, `_route`, `_retriever`, `_embedder`, `_loader` suffixes always describe role.

---

## 8. Verification

1. **Ingestion**: Run `python ingestion/ingest.py` with the PDF path. Confirm `/data/faiss/index.faiss` and `index.pkl` are written. Check chunk count and a sample metadata record.

2. **Backend**: `uvicorn main:app --reload`. Connect via `wscat -c "ws://localhost:8000/ws?session_id=test"`. Send `{"type": "message", "content": "What is attention?"}`. Verify stream of typed events: `worker_status → thinking_delta → response_delta → graph_data → node_detail (×N) → done`.

3. **Frontend**: `npm run dev`. Open `localhost:5173`. Confirm:
   - WebSocket connects, session_id in localStorage
   - Message sent → thinking indicator → response streams
   - Graph renders on left, nodes fill in progressively
   - Click node → popup with book citation appears
   - Sequence bar scrubs correctly, nodes dim/highlight
   - LaTeX renders: send `$e = mc^2$`, verify KaTeX output

4. **End-to-end**: Ask "Generate an architecture diagram for the transformer encoder". Verify: `graph_data` fires immediately with skeleton → nodes detail in async → sequence bar has steps → clicking a node in graph sends `node_selected` → `suggested_questions` chips appear in chat.
