"""Bounded, idempotent browser-render upload channel for diagram evaluation."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from io import BytesIO
import math
import uuid
from typing import Any

from PIL import Image, UnidentifiedImageError

from agent.diagram_contract import DiagramEvaluationCriteria
from agent.diagram_contract import DIAGRAM_EVALUATION_CRITERIA


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class DiagramWaiter:
    graph_version: str | None
    future: asyncio.Future[dict[str, Any]]
    criteria: DiagramEvaluationCriteria = DIAGRAM_EVALUATION_CRITERIA


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
    _REPORT_COUNT_FIELDS = (
        "rendered_nodes",
        "rendered_edges",
        "overlap_count",
        "clipped_nodes",
        "clipped_edges",
        "overview_required_edge_labels",
        "visible_overview_required_edge_labels",
        "grouped_nodes",
        "group_labelled_nodes",
        "visible_group_boundaries",
        "group_boundary_overlap_count",
    )

    def __init__(self, *, timeout_s: float, max_screenshot_bytes: int) -> None:
        self._timeout_s = timeout_s
        self._max_screenshot_bytes = max_screenshot_bytes
        self._waiters: dict[str, DiagramWaiter] = {}
        self._uploads: dict[str, DiagramUpload] = {}

    async def request(self, graph: dict[str, Any], send: SendEvent) -> dict[str, Any]:
        evaluation_id = str(uuid.uuid4())
        graph_version = _optional_text(graph.get("version"))
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        waiter = DiagramWaiter(graph_version=graph_version, future=future)
        self._waiters[evaluation_id] = waiter
        try:
            await send(self.graph_candidate_event(
                evaluation_id=evaluation_id,
                graph_version=graph_version,
                graph=graph,
                criteria=waiter.criteria,
            ))
            return await asyncio.wait_for(future, timeout=self._timeout_s)
        finally:
            self._waiters.pop(evaluation_id, None)
            self._uploads.pop(evaluation_id, None)
            if not future.done():
                future.cancel()

    @staticmethod
    def graph_candidate_event(
        *,
        evaluation_id: str,
        graph_version: str | None,
        graph: dict[str, Any],
        criteria: DiagramEvaluationCriteria,
    ) -> dict[str, Any]:
        return {
            "type": "graph_candidate",
            "evaluation_id": evaluation_id,
            "graph_version": graph_version,
            "criteria": criteria.as_event_data(),
            "data": graph,
        }

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
        if graph_version != waiter.graph_version:
            return
        if not isinstance(report, dict):
            self._reject_upload(waiter, "diagram evaluation report was missing")
            return
        if not _report_matches_viewport(report, waiter.criteria):
            self._reject_upload(waiter, "diagram evaluation viewport did not match its contract")
            return
        if not self._report_is_complete(report):
            self._reject_upload(waiter, "diagram evaluation report fields were invalid")
            return
        if not 1 <= total_chunks <= self.MAX_CHUNKS:
            self._reject_upload(waiter, "diagram evaluation chunk count was invalid")
            return
        media_type = command.get("media_type")
        if media_type not in {"image/png", "image/jpeg"}:
            self._reject_upload(waiter, "diagram evaluation media type was invalid")
            return
        self._uploads[evaluation_id] = DiagramUpload(
            graph_version=graph_version,
            total_chunks=total_chunks,
            report=dict(report),
            media_type=media_type,
        )

    @classmethod
    def _report_is_complete(cls, report: dict[str, Any]) -> bool:
        for field_name in cls._REPORT_COUNT_FIELDS:
            value = report.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return False
        minimum_text = report.get("minimum_text_px")
        if (
            isinstance(minimum_text, bool)
            or not isinstance(minimum_text, (int, float))
            or not math.isfinite(float(minimum_text))
            or float(minimum_text) < 0
        ):
            return False
        return (
            report["visible_overview_required_edge_labels"]
            <= report["overview_required_edge_labels"]
            and report["group_labelled_nodes"] <= report["grouped_nodes"]
        )

    @staticmethod
    def _reject_upload(waiter: DiagramWaiter, reason: str) -> None:
        if waiter.future.done():
            return
        waiter.future.set_result({"capture_error": reason, "report": {}})

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
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            self._reject_upload(waiter, "diagram evaluation image encoding was invalid")
            return
        if len(decoded) > self._max_screenshot_bytes:
            self._reject_upload(waiter, "diagram evaluation image exceeded its size limit")
            return
        if _image_dimensions(decoded, upload.media_type) != (
            waiter.criteria.viewport_width,
            waiter.criteria.viewport_height,
        ):
            self._reject_upload(waiter, "diagram evaluation image did not match its contract")
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


def _report_matches_viewport(
    report: dict[str, Any],
    criteria: DiagramEvaluationCriteria,
) -> bool:
    return (
        _is_matching_viewport_dimension(report.get("viewport_width"), criteria.viewport_width)
        and _is_matching_viewport_dimension(report.get("viewport_height"), criteria.viewport_height)
    )


def _is_matching_viewport_dimension(value: Any, expected: int) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == expected


def _image_dimensions(data: bytes, media_type: str) -> tuple[int, int] | None:
    expected_format = {"image/jpeg": "JPEG", "image/png": "PNG"}.get(media_type)
    if expected_format is None:
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != expected_format:
                return None
            dimensions = image.size
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            return dimensions
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError):
        return None
