import asyncio
import base64

import pytest

from api.diagram_evaluation_channel import DiagramEvaluationChannel


@pytest.mark.asyncio
async def test_channel_accepts_out_of_order_duplicate_chunks_idempotently():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=1024)
    sent = []
    candidate_ready = asyncio.Event()

    async def send(event):
        sent.append(event)
        candidate_ready.set()

    graph = {"version": "graph-v1", "nodes": [], "edges": []}
    request = asyncio.create_task(channel.request(graph, send))
    await candidate_ready.wait()
    candidate = sent[0]
    encoded = base64.b64encode(b"rendered-diagram").decode()
    chunks = [encoded[:8], encoded[8:]]
    start = {
        "type": "diagram_evaluation_start",
        "evaluation_id": candidate["evaluation_id"],
        "graph_version": "graph-v1",
        "media_type": "image/jpeg",
        "total_chunks": 2,
        "report": {"rendered_nodes": 0},
    }
    channel.accept(start)
    channel.accept({"type": "diagram_evaluation_chunk", "evaluation_id": candidate["evaluation_id"], "index": 1, "data": chunks[1]})
    channel.accept({"type": "diagram_evaluation_chunk", "evaluation_id": candidate["evaluation_id"], "index": 0, "data": chunks[0]})
    channel.accept({"type": "diagram_evaluation_chunk", "evaluation_id": candidate["evaluation_id"], "index": 0, "data": chunks[0]})
    channel.accept({"type": "diagram_evaluation_complete", "evaluation_id": candidate["evaluation_id"]})

    result = await request
    assert result["screenshot_base64"] == encoded
    assert result["report"] == {"rendered_nodes": 0}


@pytest.mark.asyncio
async def test_channel_refuses_a_stale_graph_version():
    channel = DiagramEvaluationChannel(timeout_s=0.01, max_screenshot_bytes=1024)
    sent = []

    async def send(event):
        sent.append(event)

    request = asyncio.create_task(channel.request({"version": "new"}, send))
    await asyncio.sleep(0)
    channel.accept({
        "type": "diagram_evaluation_start",
        "evaluation_id": sent[0]["evaluation_id"],
        "graph_version": "old",
        "media_type": "image/jpeg",
        "total_chunks": 1,
        "report": {},
    })

    with pytest.raises(asyncio.TimeoutError):
        await request
