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
