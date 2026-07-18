"""Bounded, idempotent browser-render upload channel for diagram evaluation."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import uuid
from typing import Any


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class DiagramWaiter:
    graph_version: str | None
    future: asyncio.Future[dict[str, Any]]


@dataclass
class DiagramUpload:
    graph_version: str | None
    total_chunks: int
    report: dict[str, Any]
    media_type: str
    chunks: dict[int, str] = field(default_factory=dict)


class DiagramEvaluationChannel:
    """Own the one source of truth for candidate render requests and uploads.

    Chunks may arrive out of order or be duplicated. An index-keyed upload makes
    those cases deterministic and idempotent. A graph-version check prevents a
    late browser result from approving a newer candidate.
    """

    MAX_CHUNKS = 80
    MAX_CHUNK_CHARS = 12_000

    def __init__(self, *, timeout_s: float, max_screenshot_bytes: int) -> None:
        self._timeout_s = timeout_s
        self._max_screenshot_bytes = max_screenshot_bytes
        self._waiters: dict[str, DiagramWaiter] = {}
        self._uploads: dict[str, DiagramUpload] = {}

    async def request(self, graph: dict[str, Any], send: SendEvent) -> dict[str, Any]:
        evaluation_id = str(uuid.uuid4())
        graph_version = _optional_text(graph.get("version"))
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiters[evaluation_id] = DiagramWaiter(graph_version=graph_version, future=future)
        await send({
            "type": "graph_candidate",
            "evaluation_id": evaluation_id,
            "graph_version": graph_version,
            "data": graph,
        })
        try:
            return await asyncio.wait_for(future, timeout=self._timeout_s)
        finally:
            self._waiters.pop(evaluation_id, None)
            self._uploads.pop(evaluation_id, None)

    def accept(self, command: dict[str, Any]) -> None:
        command_type = command.get("type")
        evaluation_id = _optional_text(command.get("evaluation_id"))
        waiter = self._waiters.get(evaluation_id or "")
        if not evaluation_id or waiter is None:
            return
        if command_type == "diagram_evaluation_start":
            self._start_upload(evaluation_id, waiter, command)
            return
        upload = self._uploads.get(evaluation_id)
        if upload is None:
            return
        if command_type == "diagram_evaluation_chunk":
            self._accept_chunk(upload, command)
        elif command_type == "diagram_evaluation_complete":
            self._complete_upload(evaluation_id, waiter, upload)

    def _start_upload(
        self,
        evaluation_id: str,
        waiter: DiagramWaiter,
        command: dict[str, Any],
    ) -> None:
        total_chunks = _safe_int(command.get("total_chunks"), fallback=0)
        report = command.get("report")
        graph_version = _optional_text(command.get("graph_version"))
        if (
            not 1 <= total_chunks <= self.MAX_CHUNKS
            or not isinstance(report, dict)
            or graph_version != waiter.graph_version
        ):
            return
        self._uploads[evaluation_id] = DiagramUpload(
            graph_version=graph_version,
            total_chunks=total_chunks,
            report=report,
            media_type="image/png" if command.get("media_type") == "image/png" else "image/jpeg",
        )

    def _accept_chunk(self, upload: DiagramUpload, command: dict[str, Any]) -> None:
        index = _safe_int(command.get("index"), fallback=-1)
        data = str(command.get("data") or "")
        if not 0 <= index < upload.total_chunks or len(data) > self.MAX_CHUNK_CHARS:
            return
        upload.chunks[index] = data

    def _complete_upload(
        self,
        evaluation_id: str,
        waiter: DiagramWaiter,
        upload: DiagramUpload,
    ) -> None:
        if len(upload.chunks) != upload.total_chunks:
            return
        encoded = "".join(upload.chunks[index] for index in range(upload.total_chunks))
        try:
            decoded_size = len(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error):
            return
        if decoded_size > self._max_screenshot_bytes:
            return
        if waiter.future.done():
            return
        waiter.future.set_result({
            "report": upload.report,
            "media_type": upload.media_type,
            "screenshot_base64": encoded,
        })
        self._uploads.pop(evaluation_id, None)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_int(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
