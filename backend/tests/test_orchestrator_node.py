# ─────────────────────────────────────────────────────────────────────────────
# File: backend/tests/test_orchestrator_node.py
# Purpose: Tests for the orchestration response style:
#          - graph context formatting for synthesis
#          - prose synthesis emits the right events and prompt context
# ─────────────────────────────────────────────────────────────────────────────

import pytest


def test_router_prompt_enforces_exact_token_output_and_search_bias():
    from agent.nodes.orchestrator_node import _ROUTER_SYSTEM

    assert "Return EXACTLY one token and nothing else" in _ROUTER_SYSTEM
    assert "If the turn could reasonably need new evidence, choose SEARCH." in _ROUTER_SYSTEM
    assert "named products, vendors, frameworks, or services not guaranteed to be in the book" in _ROUTER_SYSTEM
    assert "regardless of the language the user writes in" in _ROUTER_SYSTEM
    assert "If a current graph already exists and the user appears to be asking about a different topic" in _ROUTER_SYSTEM


def test_synthesis_prompts_preserve_user_language():
    from agent.nodes.orchestrator_node import _QUICK_SYNTHESIS_SYSTEM, _SYNTHESIS_SYSTEM

    assert "same language as the user's latest message" in _SYNTHESIS_SYSTEM
    assert "same language as the user's latest message" in _QUICK_SYNTHESIS_SYSTEM


@pytest.mark.asyncio
async def test_orchestrator_route_includes_current_graph_context(monkeypatch):
    import agent.nodes.orchestrator_node as orchestrator

    captured = {}

    async def fake_stream_llm(*, model, system, messages, temperature=None, top_p=None, top_k=None, telemetry=None, send=None):
        captured["messages"] = messages
        return "SIMPLE"

    monkeypatch.setattr(orchestrator, "stream_llm", fake_stream_llm)

    async def send(_event):
        return None

    state = {
        "send": send,
        "history": [],
        "user_message": "What is RLHF?",
        "graph_data": {
            "title": "RAG pipeline",
            "nodes": [
                {"id": "retriever", "label": "Retriever"},
                {"id": "generator", "label": "Generator"},
            ],
        },
    }

    result = await orchestrator.orchestrator_route(state)

    assert result["route"] == "simple"
    assert "Current graph:" in captured["messages"][0]["content"]
    assert "RAG pipeline — nodes: [Retriever, Generator]" in captured["messages"][0]["content"]


def test_format_graph_context_summarises_nodes_edges_and_sequence():
    from agent.nodes.orchestrator_node import _format_graph_context

    graph = {
        "title": "RAG pipeline",
        "nodes": [
            {
                "id": "retriever",
                "label": "Retriever",
                "technology": "FAISS",
                "description": "Finds relevant passages",
            },
            {
                "id": "llm",
                "label": "LLM",
                "technology": "Claude",
                "description": "Writes the answer",
            },
        ],
        "edges": [
            {"source": "Retriever", "target": "LLM", "label": "passes context"},
        ],
        "sequence": [
            {"step": 1, "nodes": ["Retriever"], "description": "Search the book"},
            {"step": 2, "nodes": ["LLM"], "description": "Explain the answer"},
        ],
    }

    summary = _format_graph_context(graph)

    assert "Title: RAG pipeline" in summary
    assert "- Retriever: FAISS | Finds relevant passages" in summary
    assert "- Retriever -> LLM: passes context" in summary
    assert "- step 1: Retriever — Search the book" in summary


@pytest.mark.asyncio
async def test_orchestrator_synthesise_emits_status_and_includes_graph_context(monkeypatch):
    import agent.nodes.orchestrator_node as orchestrator
    import agent.stream_utils as stream_utils_mod

    captured = {}

    async def fake_stream_response(*, model, system, messages, thinking_budget, temperature=None, top_p=None, top_k=None):
        captured["model"] = model
        captured["system"] = system
        captured["messages"] = messages
        captured["thinking_budget"] = thinking_budget
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        captured["top_k"] = top_k
        yield ("text", "Story")
        yield ("text", " answer")

    monkeypatch.setattr(stream_utils_mod, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "history": [],
        "user_message": "How does RAG work?",
        "rag_chunks": [
            {"chapter": 4, "page_number": 88, "text": "RAG retrieves useful passages before generation."}
        ],
        "research_context": "",
        "graph_data": {
            "title": "RAG pipeline",
            "nodes": [
                {
                    "id": "retriever",
                    "label": "Retriever",
                    "technology": "FAISS",
                    "description": "Finds relevant book passages",
                }
            ],
            "edges": [],
            "sequence": [],
        },
    }

    result = await orchestrator.orchestrator_synthesise(state)

    assert events[0] == {
        "type": "worker_status",
        "worker": "orchestrator",
        "status": "Writing the explanation…",
    }
    assert events[1]["type"] == "graph_data"
    assert any(event == {"type": "response_delta", "content": "Story"} for event in events)
    assert events[-1] == {"type": "done"}

    assert "<style>" in captured["system"]
    assert "use 3-5 short chunks" in captured["system"]
    assert "Each chunk should follow this pattern: `Topic: locator`" in captured["system"]
    assert "End with `If you want, I can:`" in captured["system"]
    assert "If graph context is provided, anchor the explanation" in captured["system"]
    assert "Do not invent graph positions or edge directions" in captured["system"]
    assert captured["temperature"] == orchestrator.settings.synthesis_temperature
    assert "Current graph:" in captured["messages"][-1]["content"]
    assert "Title: RAG pipeline" in captured["messages"][-1]["content"]
    assert result["response_text"] == "Story answer"


@pytest.mark.asyncio
async def test_context_condense_prompt_preserves_open_questions_and_avoids_invented_details(monkeypatch):
    import agent.context_manager as context_manager

    captured = {}

    async def fake_stream_response(*, model, system, messages, temperature=None, top_p=None, top_k=None):
        captured["model"] = model
        captured["system"] = system
        captured["messages"] = messages
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        captured["top_k"] = top_k
        yield ("text", "summary")

    monkeypatch.setattr(context_manager, "stream_response", fake_stream_response)

    result = await context_manager._call_haiku_summary("user: tell me more about the graph")

    assert result == "summary"
    assert "open questions" in captured["system"]
    assert "graph or architecture topic" in captured["system"]
    assert "Do not invent citations or details" in captured["system"]
    assert captured["temperature"] == context_manager.settings.condense_temperature
