# ─────────────────────────────────────────────────────────────────────────────
# File: backend/eval/test_cases.py
# Purpose: Labeled test cases for the AI Engineering study agent.
#          Each case specifies conversation turns and expected observable outcomes.
#
#          Categories:
#            A  — routing should be SEARCH (new topics)
#            B  — routing should be MEMORY (follow-up in same thread)
#            C  — routing should be SEARCH even on follow-ups (graph expansion)
#            D  — response format compliance (story + walkthrough teaching)
#            E  — graph schema validity (node/edge fields, types, sync values)
# Language: Python
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field


@dataclass
class TestCase:
    """
    id          — unique identifier, e.g. "A1"
    category    — letter prefix maps to the test category description above
    description — human-readable description of what this test checks
    messages    — ordered list of user turns; turns up to the last are
                  "setup" turns to build conversation context; only the
                  last turn is scored
    expected    — dict of expected metric outcomes used by metrics.py
    """
    id: str
    category: str
    description: str
    messages: list[str] = field(default_factory=list)
    endpoint: str = "/api/chat"
    request_payloads: list[dict] = field(default_factory=list)
    expected: dict = field(default_factory=dict)
    __test__ = False


# ── Category A: Fresh queries → should always route SEARCH ───────────────────

A1 = TestCase(
    id="A1",
    category="routing_search",
    description="New topic: RAG pipelines → expect SEARCH + graph emitted",
    messages=["What is RAG and how does it work?"],
    expected={"route": "search", "graph_emitted": True},
)

A2 = TestCase(
    id="A2",
    category="routing_search",
    description="New topic: fine-tuning → expect SEARCH",
    messages=["Explain fine-tuning LLMs and when to use it"],
    expected={"route": "search", "graph_emitted": True},
)

A3 = TestCase(
    id="A3",
    category="routing_search",
    description="New topic: embedding models → expect SEARCH",
    messages=["What are embedding models and how are they used in AI engineering?"],
    expected={"route": "search"},
)

A4 = TestCase(
    id="A4",
    category="routing_search",
    description="New topic: RLHF → expect SEARCH",
    messages=["How does RLHF (Reinforcement Learning from Human Feedback) work?"],
    expected={"route": "search"},
)

A5 = TestCase(
    id="A5",
    category="routing_search",
    description="New topic: model serving → expect SEARCH + graph emitted",
    messages=["Describe the model serving stack for production LLMs"],
    expected={"route": "search", "graph_emitted": True},
)

A6 = TestCase(
    id="A6",
    category="routing_search",
    description="New topic: LLM evaluation metrics → expect SEARCH",
    messages=["What are the key evaluation metrics for LLMs according to Chip Huyen?"],
    expected={"route": "search"},
)

# ── Category B: Follow-ups after context established → should route MEMORY ────
# These use multi-turn sessions to build history, then check the follow-up routes
# to MEMORY (not triggering new RAG+graph workers).

B1 = TestCase(
    id="B1",
    category="routing_memory",
    description="Follow-up: 'say that again' after RAG context → expect MEMORY, no new graph",
    messages=["What is RAG and how does it work?", "Can you say that again?"],
    expected={"route": "memory", "graph_emitted": False},
)

B2 = TestCase(
    id="B2",
    category="routing_memory",
    description="Follow-up: 'what did you just say' → expect MEMORY",
    messages=["Explain fine-tuning LLMs", "What did you just say?"],
    expected={"route": "memory"},
)

B3 = TestCase(
    id="B3",
    category="routing_memory",
    description="Follow-up: 'summarise in one sentence' → expect MEMORY",
    messages=["What is RAG and how does it work?", "Summarise your answer in one sentence"],
    expected={"route": "memory"},
)

# ── Category C: Graph expansion requests → ALWAYS route SEARCH ────────────────
# These are the key regression tests for the router fix. After building context,
# any request that changes/expands the graph should route SEARCH.

C1 = TestCase(
    id="C1",
    category="routing_graph_expand",
    description="Explicit 3x expansion → expect SEARCH + new graph_data",
    messages=["What is RAG and how does it work?", "expand this graph by 3x"],
    expected={"route": "search", "graph_emitted": True},
)

C2 = TestCase(
    id="C2",
    category="routing_graph_expand",
    description="'add more nodes' → expect SEARCH + new graph_data",
    messages=["Explain fine-tuning LLMs", "add more nodes"],
    expected={"route": "search", "graph_emitted": True},
)

C3 = TestCase(
    id="C3",
    category="routing_graph_expand",
    description="'I want more detail' → expect SEARCH + new graph_data",
    messages=["Describe the model serving stack for production LLMs", "I want more detail"],
    expected={"route": "search", "graph_emitted": True},
)

C4 = TestCase(
    id="C4",
    category="routing_graph_expand",
    description="Single word 'deeper' → expect SEARCH",
    messages=["What is RAG and how does it work?", "deeper"],
    expected={"route": "search"},
)

C5 = TestCase(
    id="C5",
    category="routing_graph_expand",
    description="'zoom in' implicit expansion → expect SEARCH",
    messages=["What is RAG and how does it work?", "zoom in"],
    expected={"route": "search"},
)

C6 = TestCase(
    id="C6",
    category="routing_graph_expand",
    description="'show more components' → expect SEARCH",
    messages=["Explain fine-tuning LLMs", "show more components"],
    expected={"route": "search"},
)

# ── Category D: Response format compliance ────────────────────────────────────

D1 = TestCase(
    id="D1",
    category="format",
    description="Response should teach through story + walkthrough + graph mapping",
    messages=["What is RAG and how does it work?"],
    expected={
        "has_story_heading": True,
        "has_walkthrough_heading": True,
        "has_on_graph_heading": True,
        "has_numbered_steps": True,
        "has_citations": True,
    },
)

D2 = TestCase(
    id="D2",
    category="format",
    description="Concept answer keeps the guided teaching structure",
    messages=["How does RLHF work?"],
    expected={
        "has_story_heading": True,
        "has_walkthrough_heading": True,
        "has_numbered_steps": True,
    },
)

D3 = TestCase(
    id="D3",
    category="format",
    description="Beginner explanation should avoid glossary-dump formatting",
    messages=["What is tokenization in the context of LLMs?"],
    expected={
        "has_story_heading": True,
        "has_walkthrough_heading": True,
        "has_numbered_steps": True,
        "no_bullet_dump": True,
    },
)

# ── Category E: Graph schema validation ───────────────────────────────────────

E1 = TestCase(
    id="E1",
    category="graph_schema",
    description="RAG graph: nodes must have required fields and valid types",
    messages=["What is RAG and how does it work?"],
    expected={"node_types_valid": True, "nodes_have_required_fields": True},
)

E2 = TestCase(
    id="E2",
    category="graph_schema",
    description="Fine-tuning graph: edges must have required fields, valid sync values",
    messages=["Explain fine-tuning LLMs"],
    expected={"edges_have_required_fields": True, "sync_field_valid": True},
)

E3 = TestCase(
    id="E3",
    category="graph_schema",
    description="Model serving graph: no forbidden 'internal' technology value on edges",
    messages=["Describe the model serving stack for production LLMs"],
    expected={"no_internal_technology": True},
)


# ── Category F: Cheap preflight / adversarial robustness checks ───────────────

F1 = TestCase(
    id="F1",
    category="preflight_security",
    description="Chat endpoint rejects empty content before any model work",
    request_payloads=[{"content": ""}],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Empty message",
        "no_response_delta": True,
        "no_graph_data": True,
    },
)

F2 = TestCase(
    id="F2",
    category="preflight_security",
    description="Chat endpoint rejects oversized payload before any model work",
    request_payloads=[{"content": "x" * 3000}],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Message too large",
        "no_response_delta": True,
        "no_graph_data": True,
    },
)

F3 = TestCase(
    id="F3",
    category="preflight_security",
    description="Chat endpoint rejects unknown thread IDs before any model work",
    request_payloads=[{"thread_id": "missing-thread", "content": "hello"}],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Thread not found",
        "no_response_delta": True,
        "no_graph_data": True,
    },
)

F4 = TestCase(
    id="F4",
    category="preflight_security",
    description="Node-selected rejects oversized node metadata before any model work",
    endpoint="/api/node-selected",
    request_payloads=[{
        "node_id": "n1",
        "title": "Transformers",
        "description": "x" * 5000,
    }],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Selected node payload too large",
        "no_suggested_questions": True,
    },
)

F5 = TestCase(
    id="F5",
    category="preflight_security",
    description="Node-selected rejects missing titles before model invocation",
    endpoint="/api/node-selected",
    request_payloads=[{
        "node_id": "n1",
        "title": "",
        "description": "retrieval",
    }],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Missing node title",
        "no_suggested_questions": True,
    },
)

F6 = TestCase(
    id="F6",
    category="preflight_security",
    description="Node-selected rejects unknown thread IDs before any model work",
    endpoint="/api/node-selected",
    request_payloads=[{
        "thread_id": "missing-thread",
        "node_id": "n1",
        "title": "RAG",
        "description": "retrieval",
    }],
    expected={
        "http_status": 200,
        "has_error_event": True,
        "error_contains": "Thread not found",
        "no_suggested_questions": True,
    },
)


# ── Ordered test list ──────────────────────────────────────────────────────────

TEST_CASES: list[TestCase] = [
    F1, F2, F3, F4, F5, F6,
    A1, A2, A3, A4, A5, A6,
    B1, B2, B3,
    C1, C2, C3, C4, C5, C6,
    D1, D2, D3,
    E1, E2, E3,
]

SELF_ASSESSMENT_QUERY = (
    "You are a RAG-based study assistant for the book 'AI Engineering' by Chip Huyen. "
    "Describe exactly what 'correct behaviour' looks like for you: "
    "what makes a good response, a good knowledge graph, and a good routing decision? "
    "Be specific — list concrete criteria a test harness could check."
)
