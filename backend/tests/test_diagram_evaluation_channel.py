import asyncio
import base64
from io import BytesIO

from PIL import Image
import pytest

from api.diagram_evaluation_channel import DiagramEvaluationChannel


def _png(width: int = 1440, height: int = 960) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "black").save(output, format="PNG", optimize=True)
    return output.getvalue()


def _jpeg(width: int = 1440, height: int = 960) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "black").save(output, format="JPEG")
    return output.getvalue()


def _report(**overrides):
    return {
        "viewport_width": 1440,
        "viewport_height": 960,
        "rendered_nodes": 0,
        "rendered_edges": 0,
        "overlap_count": 0,
        "clipped_nodes": 0,
        "clipped_edges": 0,
        "minimum_text_px": 11,
        "overview_required_edge_labels": 0,
        "visible_overview_required_edge_labels": 0,
        "grouped_nodes": 0,
        "group_labelled_nodes": 0,
        "visible_group_boundaries": 0,
        "group_boundary_overlap_count": 0,
        **overrides,
    }


@pytest.mark.asyncio
async def test_channel_cleans_up_waiter_when_sending_candidate_fails():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=1024)

    async def send(_event):
        raise RuntimeError("connection closed")

    with pytest.raises(RuntimeError, match="connection closed"):
        await channel.request({"version": "graph-v1"}, send)

    assert channel._waiters == {}
    assert channel._uploads == {}


@pytest.mark.asyncio
async def test_channel_accepts_out_of_order_duplicate_chunks_idempotently():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=100_000)
    sent = []
    candidate_ready = asyncio.Event()

    async def send(event):
        sent.append(event)
        candidate_ready.set()

    graph = {"version": "graph-v1", "nodes": [], "edges": []}
    request = asyncio.create_task(channel.request(graph, send))
    await candidate_ready.wait()
    candidate = sent[0]
    assert candidate["criteria"] == {
        "viewport_width": 1440,
        "viewport_height": 960,
        "minimum_text_px": 11.0,
    }
    encoded = base64.b64encode(_png()).decode()
    chunks = [encoded[offset : offset + 8_000] for offset in range(0, len(encoded), 8_000)]
    start = {
        "type": "diagram_evaluation_start",
        "evaluation_id": candidate["evaluation_id"],
        "graph_version": "graph-v1",
        "media_type": "image/png",
        "total_chunks": len(chunks),
        "report": _report(),
    }
    channel.accept(start)
    for index in reversed(range(len(chunks))):
        channel.accept({"type": "diagram_evaluation_chunk", "evaluation_id": candidate["evaluation_id"], "index": index, "data": chunks[index]})
    channel.accept({"type": "diagram_evaluation_chunk", "evaluation_id": candidate["evaluation_id"], "index": 0, "data": chunks[0]})
    channel.accept({"type": "diagram_evaluation_complete", "evaluation_id": candidate["evaluation_id"]})

    result = await request
    assert result["screenshot_base64"] == encoded
    assert result["report"] == _report()


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


@pytest.mark.asyncio
async def test_channel_rejects_uploads_with_a_non_contract_viewport():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=1024)
    sent = []

    async def send(event):
        sent.append(event)

    request = asyncio.create_task(channel.request({"version": "graph-v1"}, send))
    await asyncio.sleep(0)
    candidate = sent[0]
    channel.accept({
        "type": "diagram_evaluation_start",
        "evaluation_id": candidate["evaluation_id"],
        "graph_version": "graph-v1",
        "media_type": "image/jpeg",
        "total_chunks": 1,
        "report": _report(viewport_width=1280),
    })

    result = await request

    assert result == {
        "capture_error": "diagram evaluation viewport did not match its contract",
        "report": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "report",
    [
        _report(group_labelled_nodes=1),
        _report(minimum_text_px=float("nan")),
        {key: value for key, value in _report().items() if key != "grouped_nodes"},
    ],
)
async def test_channel_rejects_incomplete_or_non_finite_reports(report):
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=1024)
    sent = []

    async def send(event):
        sent.append(event)

    request = asyncio.create_task(channel.request({"version": "graph-v1"}, send))
    await asyncio.sleep(0)
    channel.accept({
        "type": "diagram_evaluation_start",
        "evaluation_id": sent[0]["evaluation_id"],
        "graph_version": "graph-v1",
        "media_type": "image/jpeg",
        "total_chunks": 1,
        "report": report,
    })

    assert await request == {
        "capture_error": "diagram evaluation report fields were invalid",
        "report": {},
    }


@pytest.mark.asyncio
async def test_channel_rejects_an_image_with_the_wrong_dimensions():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=100_000)
    sent = []

    async def send(event):
        sent.append(event)

    request = asyncio.create_task(channel.request({"version": "graph-v1"}, send))
    await asyncio.sleep(0)
    evaluation_id = sent[0]["evaluation_id"]
    encoded = base64.b64encode(_png(width=1280)).decode()
    chunks = [encoded[offset : offset + 8_000] for offset in range(0, len(encoded), 8_000)]
    channel.accept({
        "type": "diagram_evaluation_start",
        "evaluation_id": evaluation_id,
        "graph_version": "graph-v1",
        "media_type": "image/png",
        "total_chunks": len(chunks),
        "report": _report(),
    })
    for index, data in enumerate(chunks):
        channel.accept({
            "type": "diagram_evaluation_chunk",
            "evaluation_id": evaluation_id,
            "index": index,
            "data": data,
        })
    channel.accept({"type": "diagram_evaluation_complete", "evaluation_id": evaluation_id})

    assert await request == {
        "capture_error": "diagram evaluation image did not match its contract",
        "report": {},
    }


@pytest.mark.asyncio
async def test_channel_rejects_a_truncated_image_that_has_valid_headers():
    channel = DiagramEvaluationChannel(timeout_s=1, max_screenshot_bytes=100_000)
    sent = []

    async def send(event):
        sent.append(event)

    request = asyncio.create_task(channel.request({"version": "graph-v1"}, send))
    await asyncio.sleep(0)
    evaluation_id = sent[0]["evaluation_id"]
    encoded = base64.b64encode(_jpeg()[:-1]).decode()
    chunks = [encoded[offset : offset + 8_000] for offset in range(0, len(encoded), 8_000)]
    channel.accept({
        "type": "diagram_evaluation_start",
        "evaluation_id": evaluation_id,
        "graph_version": "graph-v1",
        "media_type": "image/jpeg",
        "total_chunks": len(chunks),
        "report": _report(),
    })
    for index, data in enumerate(chunks):
        channel.accept({
            "type": "diagram_evaluation_chunk",
            "evaluation_id": evaluation_id,
            "index": index,
            "data": data,
        })
    channel.accept({"type": "diagram_evaluation_complete", "evaluation_id": evaluation_id})

    assert await request == {
        "capture_error": "diagram evaluation image did not match its contract",
        "report": {},
    }
