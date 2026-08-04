import pytest

import agent.explanation_blocks as explanation_blocks


@pytest.mark.asyncio
async def test_one_provider_call_emits_complete_explanation_blocks(monkeypatch):
    calls = []

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        yield ("text", '{"block_id":"overview","title":"In one minute","content":"Start here.",')
        yield ("text", '"related_node_ids":["input"],"evidence_refs":[]}\n')
        yield ("text", '{"block_id":"controls","title":"Safety","content":"Approve risky writes.",')
        yield ("text", '"related_node_ids":["approval","invented"],"evidence_refs":["Chapter 4, p.8"]}')
        yield ("done", "")

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input", "approval"},
    )

    assert len(calls) == 1
    assert calls[0]["effort"] == "high"
    assert "<untrusted_context>" in calls[0]["system"]
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert [block["title"] for block in blocks] == ["In one minute", "Safety"]
    assert blocks[1]["related_node_ids"] == ["approval"]
    assert "## Safety" in response


def test_block_normalisation_rejects_scalar_lists_and_empty_identifiers():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "   ",
            "title": "   ",
            "content": "Useful detail",
            "related_node_ids": "input",
            "evidence_refs": "Chapter 1",
        },
        {"input"},
    )

    assert block == {
        "block_id": "architecture_note",
        "title": "Architecture note",
        "content": "Useful detail",
        "related_node_ids": [],
        "evidence_refs": [],
    }


def test_fallback_block_bounds_unstructured_model_output():
    block = explanation_blocks._fallback_block("x" * 5000)

    assert len(block["content"]) == 4000
