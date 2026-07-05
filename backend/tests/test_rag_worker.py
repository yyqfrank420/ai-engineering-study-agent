import json

import pytest

from agent.nodes.rag_worker import _assess_retrieval_relevance, _meaningful_terms, rag_worker_node
from config import settings


class _Tool:
    name = "rag_search"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return json.dumps(self.payload)


@pytest.mark.asyncio
async def test_rag_worker_invokes_search_tool_and_returns_chunks(monkeypatch):
    monkeypatch.setattr(settings, "rag_top_k", 7)
    events = []
    chunks = [{"text": "Agents plan and use tools for tasks.", "chapter": 6}]
    tool = _Tool(chunks)

    async def send(event):
        events.append(event)

    result = await rag_worker_node(
        {
            "user_message": "How do agents use tools?",
            "send": send,
        },
        [tool],
    )

    assert events == [{"type": "worker_status", "worker": "rag", "status": "Searching book…"}]
    assert tool.calls == [{"query": "How do agents use tools?", "k": 7}]
    assert result["rag_chunks"] == chunks
    assert result["retrieval_relevance"] == "strong"
    assert result["retrieval_notice"] == ""


@pytest.mark.asyncio
async def test_rag_worker_handles_missing_search_tool_as_weak_retrieval():
    events = []

    async def send(event):
        events.append(event)

    result = await rag_worker_node({"user_message": "marketing agents", "send": send}, [])

    assert result["rag_chunks"] == []
    assert result["retrieval_relevance"] == "weak"
    assert "closest book patterns" in result["retrieval_notice"]


def test_retrieval_relevance_flags_indirect_single_hit():
    relevance, notice = _assess_retrieval_relevance(
        "How does this apply to sales operations?",
        [{"text": "Agents plan steps."}],
    )

    assert relevance == "weak"
    assert "nearest book concepts" in notice


def test_retrieval_relevance_flags_low_coverage_even_with_multiple_chunks():
    relevance, notice = _assess_retrieval_relevance(
        "warehouse pricing analytics governance",
        [{"text": "Agents plan steps."}, {"text": "Tools execute actions."}],
    )

    assert relevance == "weak"
    assert "closest book ideas" in notice


def test_retrieval_relevance_treats_stopword_only_query_as_strong_when_chunks_exist():
    assert _assess_retrieval_relevance("how is it and why", [{"text": "anything"}]) == ("strong", "")


def test_meaningful_terms_removes_stop_words_and_short_tokens():
    assert _meaningful_terms("How do AI agents use SQL in ops?") == ["agents", "use", "sql", "ops"]
