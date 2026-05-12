import pytest


@pytest.mark.asyncio
async def test_graph_worker_uses_canonical_artifacts_without_llm(monkeypatch, tmp_path):
    from tests.test_canonical_graph import SCHEMA_DIR, _write_parent_docs
    from graph.artifacts import load_canonical_graph
    from graph.build import build_canonical_graph
    import agent.nodes.graph_worker as graph_worker
    import agent.stream_utils as stream_utils_mod

    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)

    async def fail_stream_response(**_kwargs):
        raise AssertionError("canonical graph worker must not call the LLM")
        yield ("text", "")

    monkeypatch.setattr(stream_utils_mod, "stream_response", fail_stream_response)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: artifacts)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "user_id": "user-1",
        "session_id": "thread-1",
        "user_message": "Explain retrieval augmented generation",
        "graph_data": None,
        "complexity": "auto",
        "research_context": "",
        "rag_chunks": [{"parent_chunk_id": "ai-eng:p42:pc0", "text": ""}],
    }

    result = await graph_worker.graph_worker_node(state, tools=[])

    assert events[0] == {"type": "worker_status", "worker": "graph", "status": "Selecting graph…"}
    assert result["graph_data"]["graph_type"] == "concept"
    assert result["graph_data"]["version"]
    assert all(node.get("canonical_id") for node in result["graph_data"]["nodes"])


@pytest.mark.asyncio
async def test_graph_worker_abstains_without_canonical_support(monkeypatch, tmp_path):
    from tests.test_canonical_graph import SCHEMA_DIR, _write_parent_docs
    from graph.artifacts import load_canonical_graph
    from graph.build import build_canonical_graph
    import agent.nodes.graph_worker as graph_worker

    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: artifacts)

    async def send(_event):
        pass

    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Explain an unsupported concept",
            "graph_data": None,
            "complexity": "auto",
            "research_context": "",
            "rag_chunks": [{"parent_chunk_id": "ai-eng:p999:pc0", "text": ""}],
        },
        tools=[],
    )

    assert result["graph_data"] is None


@pytest.mark.asyncio
async def test_graph_worker_keeps_architecture_topic_for_agent_followup(monkeypatch, tmp_path):
    from tests.test_canonical_graph import SCHEMA_DIR, _write_parent_docs
    from graph.artifacts import load_canonical_graph
    from graph.build import build_canonical_graph
    import agent.nodes.graph_worker as graph_worker

    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: artifacts)

    async def send(_event):
        pass

    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "expand on all the agents",
            "history": [
                {
                    "role": "user",
                    "content": "multi-agent customer support chatbot architecture pls",
                }
            ],
            "graph_data": None,
            "complexity": "auto",
            "research_context": "",
            "rag_chunks": [{"parent_chunk_id": "ai-eng:p473:pc0", "text": ""}],
        },
        tools=[],
    )

    graph = result["graph_data"]
    assert graph is not None
    assert graph["graph_type"] == "architecture"
    assert {node["label"] for node in graph["nodes"]} >= {
        "Billing Agent",
        "Returns Agent",
        "Escalation Agent",
    }


@pytest.mark.asyncio
async def test_node_detail_prompt_prefers_canonical_evidence(monkeypatch):
    import agent.nodes.node_detail_worker as node_detail_worker

    captured = {}

    class FakeTool:
        def invoke(self, payload):
            return (
                '[{"chapter": 7, "page_number": 356, "text": '
                '"LoRA is a parameter-efficient fine-tuning method that updates small adapter matrices instead of all model weights."}]'
            )

    async def fake_stream_response(*, model, system, messages, thinking_budget, temperature=None, top_p=None, top_k=None):
        captured["model"] = model
        captured["system"] = system
        captured["messages"] = messages
        captured["thinking_budget"] = thinking_budget
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        captured["top_k"] = top_k
        yield ("text", "LoRA is a lightweight way to adapt a model. It fits into the training flow by changing only a small set of weights. (Chapter 7, p.356)")

    import agent.stream_utils as stream_utils_mod
    monkeypatch.setattr(stream_utils_mod, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    node = {
        "id": "lora",
        "label": "LoRA",
        "type": "service",
        "technology": "PyTorch",
        "description": "Adds low-rank adapters",
        "tier": None,
        "evidence_chunk_ids": ["ai-eng:p356:pc0"],
    }
    edges = [{"source": "trainer", "target": "lora", "label": "applies adapters"}]

    await node_detail_worker.enrich_node(node, edges, FakeTool(), send, graph_version="graph-v1")

    assert "exactly 2 short paragraphs" in captured["system"]
    assert "no bullet points" in captured["system"]
    assert "no equations, matrix notation" in captured["system"]
    assert "If the book evidence is thin" in captured["system"]
    assert "Never invent citations" in captured["system"]
    assert captured["temperature"] == node_detail_worker.settings.node_detail_temperature
    assert "Canonical evidence chunks: ai-eng:p356:pc0" in captured["messages"][0]["content"]
    assert "Connections:" in captured["messages"][0]["content"]
    assert events[-1]["type"] == "node_detail"
    assert events[-1]["book_refs"] == ["(Chapter 7, p.356)"]
    assert events[-1]["graph_version"] == "graph-v1"
