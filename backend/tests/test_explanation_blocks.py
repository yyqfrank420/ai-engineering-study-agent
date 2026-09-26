import asyncio
import json

import pytest

import agent.explanation_blocks as explanation_blocks


_OVERVIEW_SENTENCE = (
    "This is an overview of the core workflow, with supporting detail simplified."
)


@pytest.mark.asyncio
async def test_one_provider_call_emits_complete_explanation_blocks(monkeypatch):
    calls = []

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        yield (
            "text",
            '{"block_id":"overview","title":"In one minute","content":"Start here.",',
        )
        yield ("text", '"related_node_ids":["input"],"evidence_refs":[]}\n')
        yield (
            "text",
            '{"block_id":"controls","title":"Safety","content":"Approve risky writes.",',
        )
        yield (
            "text",
            '"related_node_ids":["approval","invented"],"evidence_refs":["Chapter 4, p.8"]}',
        )
        yield ("done", "")

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="medium",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input", "approval"},
        allowed_evidence_refs={"Chapter 4, p.8"},
    )

    assert len(calls) == 1
    assert calls[0]["effort"] == "medium"
    assert calls[0]["max_output_tokens"] == 4500
    assert "<untrusted_context>" in calls[0]["system"]
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert [block["title"] for block in blocks[:2]] == ["In one minute", "Safety"]
    assert len(blocks) == 2
    assert blocks[1]["related_node_ids"] == ["approval"]
    assert "## Safety" in response


@pytest.mark.asyncio
async def test_accepted_overview_prefixes_first_valid_block_once_in_stream_and_result(
    monkeypatch,
):
    calls = []
    original_content = f"{_OVERVIEW_SENTENCE}\n\n" + "A" * 3970

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        yield (
            "text",
            json.dumps(
                {
                    "block_id": "runtime",
                    "title": "Runtime",
                    "content": original_content,
                    "related_node_ids": ["entry"],
                    "evidence_refs": [],
                }
            ),
        )
        yield (
            "text",
            '{"block_id":"controls","title":"Controls","content":"Check approvals.",'
            '"related_node_ids":[],"evidence_refs":[]}',
        )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"entry"},
        accepted_graph_detail="overview",
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(calls) == 1
    assert len(blocks) == 2
    assert blocks[0]["content"].startswith(_OVERVIEW_SENTENCE + "\n\n")
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == 1
    assert len(blocks[0]["content"]) <= 4000
    assert blocks[1]["content"] == "Check approvals."
    assert response == "\n\n".join(
        f"## {block['title']}\n\n{block['content']}" for block in blocks
    )


@pytest.mark.parametrize("detail_level", ["standard", "overview"])
@pytest.mark.asyncio
async def test_accepted_graph_with_no_valid_blocks_gets_ready_to_inspect_fallback(
    monkeypatch, detail_level
):
    async def fake_stream_response(**_kwargs):
        yield ("text", '{"block_id":"invalid","content":"unsupported"}')

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
        accepted_graph_detail=detail_level,
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert blocks[0]["title"] == "Diagram ready"
    assert "The diagram is ready to inspect." in blocks[0]["content"]
    assert "retry" not in blocks[0]["content"].lower()
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == int(
        detail_level == "overview"
    )
    assert response == f"## Diagram ready\n\n{blocks[0]['content']}"
    assert "unsupported" not in response


@pytest.mark.parametrize("accepted_graph_detail", [None, "overview"])
@pytest.mark.asyncio
async def test_stream_timeout_preserves_parsed_block_and_closes_provider_iterator(
    monkeypatch, accepted_graph_detail
):
    closed = False

    async def stalled_stream_response(**_kwargs):
        nonlocal closed
        try:
            yield (
                "text",
                '{"block_id":"overview","title":"Overview","content":"Ready",'
                '"related_node_ids":["input"],"evidence_refs":[]}',
            )
            await asyncio.Future()
        finally:
            closed = True

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)

    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input"},
        accepted_graph_detail=accepted_graph_detail,
    )

    assert closed is True
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert response == f"## Overview\n\n{blocks[0]['content']}"
    assert blocks[0]["content"].endswith("Ready")
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == int(
        accepted_graph_detail == "overview"
    )
    assert [
        event["status"] for event in events if event["type"] == "workflow_progress"
    ] == ["degraded"]


@pytest.mark.asyncio
async def test_stream_timeout_before_complete_block_emits_bounded_fallback(monkeypatch):
    closed = False

    async def stalled_stream_response(**_kwargs):
        nonlocal closed
        try:
            yield ("text", '{"block_id":"overview","content":"partial')
            await asyncio.Future()
        finally:
            closed = True

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input"},
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    fallback = blocks[0]
    assert closed is True
    assert fallback["title"] == "Explanation unavailable"
    assert (
        fallback["content"] == "The explanation response was unavailable. Please retry."
    )
    assert "partial" not in response
    assert fallback["evidence_refs"] == []
    assert any(
        event["type"] == "workflow_progress" and event["status"] == "degraded"
        for event in events
    )


@pytest.mark.asyncio
async def test_accepted_overview_timeout_before_valid_block_keeps_diagram_ready(
    monkeypatch,
):
    async def stalled_stream_response(**_kwargs):
        yield ("text", '{"block_id":"overview","content":"partial')
        await asyncio.Future()

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
        accepted_graph_detail="overview",
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert blocks[0]["content"].startswith(_OVERVIEW_SENTENCE)
    assert "The diagram is ready to inspect." in blocks[0]["content"]
    assert "Please retry" not in response
    assert response == f"## Diagram ready\n\n{blocks[0]['content']}"
    assert [
        event["status"] for event in events if event["type"] == "workflow_progress"
    ] == ["degraded"]


@pytest.mark.asyncio
async def test_malformed_model_output_emits_server_authored_fallback(monkeypatch):
    async def fake_stream_response(**_kwargs):
        yield ("text", '{"block_id":"overview","content":"unsupported claim"}')

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    fallback = blocks[0]
    assert (
        fallback["content"] == "The explanation response was unavailable. Please retry."
    )
    assert fallback["evidence_refs"] == []
    assert "unsupported claim" not in response
    assert any(
        event["type"] == "workflow_progress" and event["status"] == "degraded"
        for event in events
    )


@pytest.mark.asyncio
async def test_preserved_edit_appends_required_completion_sentence_after_parsing(
    monkeypatch,
):
    async def fake_stream_response(**_kwargs):
        yield (
            "text",
            '{"block_id":"result","title":"Result","content":"The prior graph remains.",'
            '"related_node_ids":[],"evidence_refs":[]}',
        )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[
            {
                "role": "user",
                "content": (
                    "<trusted_turn_result>\n"
                    "Publication state: preserved.\n"
                    "Required completion sentence: The requested diagram edit was not approved, so "
                    "the prior approved diagram remains unchanged.\n"
                    "</trusted_turn_result>"
                ),
            }
        ],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    sentence = "The requested diagram edit was not approved, so the prior approved diagram remains unchanged."
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["content"].endswith(sentence)
    assert response.endswith(sentence)


def test_block_normalisation_rejects_non_array_evidence_refs():
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

    assert block is None


def test_block_normalisation_requires_exact_contract_keys():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "overview",
            "title": "Overview",
            "content": "Useful detail",
            "related_node_ids": [],
            "evidence_refs": [],
            "unexpected": "value",
        },
        set(),
    )

    assert block is None


def test_block_normalisation_rejects_unknown_evidence_references():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "overview",
            "title": "Overview",
            "content": "Useful detail",
            "related_node_ids": [],
            "evidence_refs": ["Chapter 1, p.1"],
        },
        set(),
        {"Chapter 2, p.2"},
    )

    assert block is None


@pytest.mark.asyncio
async def test_stream_limits_blocks_and_rejects_duplicate_ids(monkeypatch):
    async def fake_stream_response(**_kwargs):
        for index in range(8):
            block_id = "block_0" if index == 1 else f"block_{index}"
            yield (
                "text",
                (
                    "{"
                    f'"block_id":"{block_id}",'
                    f'"title":"Block {index}",'
                    f'"content":"Content {index}",'
                    '"related_node_ids":[],"evidence_refs":[]}'
                ),
            )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 6
    assert len({block["block_id"] for block in blocks}) == 6
    assert blocks[1]["block_id"] == "block_2"


def test_fallback_block_is_server_authored_and_has_no_evidence_refs():
    block = explanation_blocks._fallback_block("x" * 5000)

    assert block == {
        "block_id": "architecture_explanation",
        "title": "Explanation unavailable",
        "content": "The explanation response was unavailable. Please retry.",
        "related_node_ids": [],
        "evidence_refs": [],
    }


@pytest.mark.asyncio
async def test_cancellation_preserves_emitted_block_without_supplementing(monkeypatch):
    closed = False
    events = []

    async def provider(**_kwargs):
        nonlocal closed
        try:
            yield (
                "text",
                '{"block_id":"answer","title":"Answer","content":"Bounded answer.",'
                '"related_node_ids":[],"evidence_refs":[]}',
            )
            raise asyncio.CancelledError()
        finally:
            closed = True

    async def send(event):
        events.append(event)

    monkeypatch.setattr(explanation_blocks, "stream_response", provider)
    with pytest.raises(asyncio.CancelledError):
        await explanation_blocks.stream_explanation_blocks(
            model="claude-opus-5",
            system="system",
            messages=[{"role": "user", "content": "One focused answer."}],
            effort="low",
            max_output_tokens=4500,
            timeout_seconds=40,
            telemetry={"operation": "test"},
            send=send,
            graph_version="v1",
            allowed_node_ids=set(),
        )
    assert closed is True
    assert len(events) == 1
    assert events[0]["type"] == "explanation_block"
    assert events[0]["content"] == "Bounded answer."
