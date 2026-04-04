from dataclasses import dataclass, field


@dataclass
class StepExpectation:
    http_status: int = 200
    route: str | None = None
    has_error_event: bool | None = False
    error_contains: str | None = None
    graph_emitted: bool | None = None
    workers_include: list[str] = field(default_factory=list)
    workers_exclude: list[str] = field(default_factory=list)
    response_min_length: int | None = None
    response_contains: list[str] = field(default_factory=list)
    suggested_questions_count: int | None = None
    thread_message_count: int | None = None
    thread_message_roles: list[str] = field(default_factory=list)
    thread_count_delta: int | None = None
    thread_deleted: bool | None = None


@dataclass
class StagingStep:
    kind: str
    description: str
    payload: dict = field(default_factory=dict)
    expect: StepExpectation = field(default_factory=StepExpectation)


@dataclass
class StagingCase:
    id: str
    category: str
    description: str
    steps: list[StagingStep]
    cleanup_thread: bool = True
    __test__ = False


STAGING_CASES: list[StagingCase] = [
    StagingCase(
        id="S1",
        category="happy_path",
        description="Fresh RAG explanation with graph generation in auto mode.",
        steps=[
            StagingStep(
                kind="chat",
                description="Ask for a concise explanation of RAG.",
                payload={
                    "content": "Explain retrieval-augmented generation and why teams use it.",
                    "complexity": "auto",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=True,
                    workers_include=["orchestrator", "rag", "graph"],
                    response_min_length=180,
                    response_contains=["retrieval", "generation"],
                ),
            ),
            StagingStep(
                kind="get_thread",
                description="Confirm the conversation persisted to the thread.",
                expect=StepExpectation(
                    thread_message_count=2,
                    thread_message_roles=["user", "assistant"],
                ),
            ),
        ],
    ),
    StagingCase(
        id="S2",
        category="memory_followup",
        description="Multi-turn conversation should answer a follow-up from memory.",
        steps=[
            StagingStep(
                kind="chat",
                description="Seed the thread with an initial concept explanation.",
                payload={
                    "content": "What is prompt injection in LLM systems?",
                    "complexity": "auto",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    workers_include=["rag"],
                    response_min_length=120,
                ),
            ),
            StagingStep(
                kind="chat",
                description="Ask for a short restatement of the prior answer.",
                payload={
                    "content": "Summarise that in one sentence.",
                    "complexity": "low",
                    "graph_mode": "off",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="memory",
                    graph_emitted=False,
                    workers_include=["orchestrator"],
                    workers_exclude=["rag", "graph", "research"],
                    response_min_length=40,
                ),
            ),
            StagingStep(
                kind="get_thread",
                description="Verify both turns were persisted.",
                expect=StepExpectation(
                    thread_message_count=4,
                    thread_message_roles=["user", "assistant", "user", "assistant"],
                ),
            ),
        ],
    ),
    StagingCase(
        id="S3",
        category="graph_expansion",
        description="Graph expansion requests should trigger a new search pass.",
        steps=[
            StagingStep(
                kind="chat",
                description="Create an initial graph.",
                payload={
                    "content": "Describe the model serving stack for production LLMs.",
                    "complexity": "prototype",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=True,
                    workers_include=["rag", "graph"],
                ),
            ),
            StagingStep(
                kind="chat",
                description="Ask to expand the graph with more detail.",
                payload={
                    "content": "Add more nodes and show more operational detail.",
                    "complexity": "production",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=True,
                    workers_include=["rag", "graph"],
                    response_min_length=120,
                ),
            ),
        ],
    ),
    StagingCase(
        id="S4",
        category="mode_controls",
        description="Graph-off mode should skip graph generation while still answering.",
        steps=[
            StagingStep(
                kind="chat",
                description="Request an answer with graph generation disabled.",
                payload={
                    "content": "Compare RAG and fine-tuning in plain English.",
                    "complexity": "low",
                    "graph_mode": "off",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=False,
                    workers_include=["orchestrator", "rag"],
                    workers_exclude=["graph"],
                    response_min_length=120,
                    response_contains=["RAG", "fine-tuning"],
                ),
            ),
        ],
    ),
    StagingCase(
        id="S5",
        category="research_mode",
        description="Research-enabled mode should invoke the research worker.",
        steps=[
            StagingStep(
                kind="chat",
                description="Ask a current-practice question with research enabled.",
                payload={
                    "content": "What are practical trade-offs between agents and workflows for AI products?",
                    "complexity": "prototype",
                    "graph_mode": "auto",
                    "research_enabled": True,
                },
                expect=StepExpectation(
                    workers_include=["orchestrator", "rag", "graph", "research"],
                    graph_emitted=True,
                    response_min_length=150,
                ),
            ),
        ],
    ),
    StagingCase(
        id="S6",
        category="node_selected",
        description="Suggested-question chips should stream from a real graph node after chat.",
        steps=[
            StagingStep(
                kind="chat",
                description="Create a graph to supply node context.",
                payload={
                    "content": "Explain the architecture of an AI agent with tools and memory.",
                    "complexity": "prototype",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=True,
                    workers_include=["rag", "graph"],
                ),
            ),
            StagingStep(
                kind="node_selected",
                description="Request follow-up chips for the first emitted node.",
                payload={"use_first_graph_node": True},
                expect=StepExpectation(
                    suggested_questions_count=3,
                ),
            ),
        ],
    ),
    StagingCase(
        id="S7",
        category="edge_cases",
        description="Empty-message preflight should fail before model work.",
        steps=[
            StagingStep(
                kind="chat",
                description="Send an empty message.",
                payload={
                    "content": "",
                    "complexity": "auto",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    has_error_event=True,
                    error_contains="Empty message",
                    graph_emitted=False,
                    workers_exclude=["orchestrator", "rag", "graph", "research"],
                ),
            ),
        ],
    ),
    StagingCase(
        id="S8",
        category="edge_cases",
        description="Oversized-message preflight should fail before model work.",
        steps=[
            StagingStep(
                kind="chat",
                description="Send an oversized message payload.",
                payload={
                    "content": "x" * 3000,
                    "complexity": "auto",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    has_error_event=True,
                    error_contains="Message too large",
                    graph_emitted=False,
                    workers_exclude=["orchestrator", "rag", "graph", "research"],
                ),
            ),
        ],
    ),
    StagingCase(
        id="S9",
        category="real_workflow",
        description="A realistic user workflow should create, use, and delete a thread cleanly.",
        steps=[
            StagingStep(
                kind="list_threads",
                description="Capture the current thread count.",
                expect=StepExpectation(),
            ),
            StagingStep(
                kind="chat",
                description="Ask a first question.",
                payload={
                    "content": "What is an embedding model and where does it fit in an LLM system?",
                    "complexity": "auto",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    route="search",
                    graph_emitted=True,
                    response_min_length=120,
                ),
            ),
            StagingStep(
                kind="chat",
                description="Ask a contextual follow-up in the same thread.",
                payload={
                    "content": "Now compare that with reranking in two paragraphs.",
                    "complexity": "prototype",
                    "graph_mode": "auto",
                    "research_enabled": False,
                },
                expect=StepExpectation(
                    response_min_length=150,
                ),
            ),
            StagingStep(
                kind="get_thread",
                description="Confirm that both turns persisted.",
                expect=StepExpectation(thread_message_count=4),
            ),
            StagingStep(
                kind="delete_thread",
                description="Delete the workflow thread.",
                expect=StepExpectation(http_status=204),
            ),
            StagingStep(
                kind="list_threads",
                description="Confirm the thread count returned to baseline.",
                expect=StepExpectation(thread_count_delta=0),
            ),
        ],
        cleanup_thread=False,
    ),
]
