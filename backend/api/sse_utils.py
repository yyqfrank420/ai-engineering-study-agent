import json

from fastapi.responses import StreamingResponse


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def streaming_response(stream):
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def sse_error(message: str, *, include_done: bool = False):
    """Return a streaming SSE error response.

    Use include_done=True for endpoints where the client expects an explicit
    'done' event after the error (e.g. node-selected).
    """
    async def _gen():
        yield sse({"type": "error", "content": message})
        if include_done:
            yield sse({"type": "done"})
    return streaming_response(_gen())
