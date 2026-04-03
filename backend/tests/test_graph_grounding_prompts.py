import pytest


@pytest.mark.asyncio
async def test_graph_worker_prompt_includes_rag_evidence_and_concept_bias(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    captured = {}

    async def fake_stream_response(*, model, system, messages, thinking_budget, temperature=None, top_p=None, top_k=None):
        captured["model"] = model
        captured["system"] = system
        captured["messages"] = messages
        captured["thinking_budget"] = thinking_budget
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        captured["top_k"] = top_k
        yield ("text", "NO_GRAPH")

    monkeypatch.setattr(graph_worker, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "user_message": "Explain PEFT and LoRA for beginners",
        "graph_data": None,
        "complexity": "auto",
        "research_context": "",
        "rag_chunks": [
            {
                "chapter": 7,
                "page_number": 356,
                "chapter_title": "Training and adaptation",
                "section": "Parameter-efficient fine-tuning",
                "text": "Parameter-efficient fine-tuning (PEFT) updates a small subset of weights instead of the whole model. LoRA is a popular PEFT method.",
            }
        ],
    }

    result = await graph_worker.graph_worker_node(state, tools=[])

    assert events[0] == {"type": "worker_status", "worker": "graph", "status": "Checking graph…"}
    assert result["graph_data"] is None
    assert "Use the retrieved book evidence as the source of truth." in captured["system"]
    assert 'If in doubt, choose "concept".' in captured["system"]
    assert "If the exact product is out of book but the underlying pattern is in book, graph the pattern." in captured["system"]
    assert "Do NOT drift into random enterprise boxes like VPCs" in captured["system"]
    assert captured["temperature"] == graph_worker.settings.graph_temperature
    assert captured["top_p"] == graph_worker.settings.graph_top_p
    assert captured["top_k"] == graph_worker.settings.graph_top_k
    assert "Retrieved book evidence:" in captured["messages"][0]["content"]
    assert "Parameter-efficient fine-tuning" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_graph_worker_retries_when_no_graph_exists_and_model_returns_no_graph(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    calls = []

    async def fake_stream_response(*, model, system, messages, thinking_budget, temperature=None, top_p=None, top_k=None):
        calls.append(system)
        if len(calls) == 1:
            yield ("text", "NO_GRAPH")
        else:
            yield (
                "text",
                '{"action":"replace","graph_type":"concept","title":"Open Agent Stack","nodes":[{"id":"model_api","label":"Model API","type":"service","technology":"Llama","description":"Core model brain","tier":null}],"edges":[],"sequence":[]}',
            )

    monkeypatch.setattr(graph_worker, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "user_message": "How do we build an open-source alternative to Amazon AgentCore?",
        "graph_data": None,
        "complexity": "auto",
        "research_context": "",
        "rag_chunks": [
            {
                "chapter": 10,
                "page_number": 473,
                "chapter_title": "Agents",
                "section": "Agent architecture",
                "text": "An agent system needs a model, tools, planning logic, and guardrails around execution.",
            }
        ],
    }

    result = await graph_worker.graph_worker_node(state, tools=[])

    assert len(calls) == 2
    assert "Do NOT respond with NO_GRAPH" in calls[1]
    assert result["graph_data"]["title"] == "Open Agent Stack"
    assert result["graph_data"]["version"]


@pytest.mark.asyncio
async def test_graph_worker_ignores_non_object_json_before_valid_object(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    async def fake_stream_response(*, model, system, messages, thinking_budget, temperature=None, top_p=None, top_k=None):
        yield (
            "text",
            '[{"noise": true}] {"action":"replace","graph_type":"concept","title":"RAG Flow","nodes":[{"id":"retriever","label":"Retriever","type":"service","technology":"FAISS","description":"Finds relevant chunks","tier":null}],"edges":[],"sequence":[]}',
        )

    monkeypatch.setattr(graph_worker, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "user_message": "Explain retrieval-augmented generation",
        "graph_data": None,
        "complexity": "auto",
        "research_context": "",
        "rag_chunks": [
            {
                "chapter": 10,
                "page_number": 473,
                "chapter_title": "Agents",
                "section": "RAG",
                "text": "RAG retrieves relevant information and passes it to the model before generation.",
            }
        ],
    }

    result = await graph_worker.graph_worker_node(state, tools=[])

    assert result["graph_data"]["title"] == "RAG Flow"
    assert result["graph_data"]["version"]


@pytest.mark.asyncio
async def test_node_detail_prompt_forbids_bullets_and_equations(monkeypatch):
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

    monkeypatch.setattr(node_detail_worker, "stream_response", fake_stream_response)

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
    }
    edges = [{"source": "trainer", "target": "lora", "label": "applies adapters"}]

    await node_detail_worker.enrich_node(node, edges, FakeTool(), send, graph_version="graph-v1")

    assert "exactly 2 short paragraphs" in captured["system"]
    assert "no bullet points" in captured["system"]
    assert "no equations, matrix notation" in captured["system"]
    assert "If the book evidence is thin" in captured["system"]
    assert "Never invent citations" in captured["system"]
    assert captured["temperature"] == node_detail_worker.settings.node_detail_temperature
    assert "Connections:" in captured["messages"][0]["content"]
    assert events[-1]["type"] == "node_detail"
    assert events[-1]["book_refs"] == ["(Chapter 7, p.356)"]
    assert events[-1]["graph_version"] == "graph-v1"
