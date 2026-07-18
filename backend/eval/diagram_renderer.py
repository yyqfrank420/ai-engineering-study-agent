"""Render a bounded diagram image for the non-browser staging client.

The product UI remains the authoritative renderer: it evaluates the actual D3
canvas before publication.  The staging runner uses this small contract
renderer so live model evaluations can complete the same WebSocket handshake
without adding a privileged quality-gate bypass.
"""

from __future__ import annotations

import base64
from collections import defaultdict, deque
from io import BytesIO
import math
import textwrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont


_WIDTH = 1280
_HEIGHT = 760
_MARGIN_X = 54
_MARGIN_TOP = 86
_MARGIN_BOTTOM = 44
_COLUMN_GAP = 44
_ROW_GAP = 24


def render_staging_diagram(graph: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Return ``(base64, media_type, layout_report)`` for one graph candidate."""
    nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
    edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
    if not nodes:
        raise ValueError("diagram candidate has no nodes")

    image = Image.new("RGB", (_WIDTH, _HEIGHT), "#080d14")
    draw = ImageDraw.Draw(image)
    title_font = _font(24)
    node_font = _font(16)
    edge_font = _font(11)
    draw.text((_MARGIN_X, 24), str(graph.get("title") or "Architecture"), fill="#f3f4f6", font=title_font)

    positions = _node_positions(nodes, edges)
    boxes = _node_boxes(positions)
    node_by_id = {str(node.get("id")): node for node in nodes}
    rendered_edges = 0

    for edge in edges:
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        if source_id not in boxes or target_id not in boxes:
            continue
        _draw_edge(
            draw,
            boxes[source_id],
            boxes[target_id],
            str(edge.get("label") or ""),
            str(edge.get("type") or "") == "loop",
            edge_font,
        )
        rendered_edges += 1

    for node_id, box in boxes.items():
        node = node_by_id[node_id]
        node_type = str(node.get("type") or "component")
        outline = _node_colour(node_type)
        draw.rounded_rectangle(box, radius=10, fill="#111827", outline=outline, width=2)
        label = " ".join(str(node.get("label") or node_id).split())
        lines = textwrap.wrap(label, width=24, break_long_words=True)[:3] or [node_id]
        line_height = 20
        text_height = len(lines) * line_height
        top = box[1] + max(10, ((box[3] - box[1]) - text_height) // 2)
        for index, line in enumerate(lines):
            text_box = draw.textbbox((0, 0), line, font=node_font)
            text_width = text_box[2] - text_box[0]
            draw.text(
                (box[0] + ((box[2] - box[0]) - text_width) / 2, top + index * line_height),
                line,
                fill="#f9fafb",
                font=node_font,
            )

    output = BytesIO()
    image.save(output, format="JPEG", quality=72, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    report = {
        "viewport_width": _WIDTH,
        "viewport_height": _HEIGHT,
        "rendered_nodes": len(nodes),
        "rendered_edges": rendered_edges,
        "overlap_count": _overlap_count(list(boxes.values())),
        "clipped_nodes": _clipped_count(list(boxes.values())),
        "minimum_text_px": 11,
        "renderer": "staging-contract-v1",
    }
    return encoded, "image/jpeg", report


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _node_positions(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Assign stable left-to-right columns, excluding declared feedback loops."""
    node_ids = [str(node.get("id")) for node in nodes]
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if (
            source not in indegree
            or target not in indegree
            or str(edge.get("type") or "") == "loop"
        ):
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    depth = {node_id: 0 for node_id in node_ids}
    queue = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        visited.add(source)
        for target in outgoing[source]:
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    # Malformed undeclared cycles stay visible instead of crashing the eval.
    for node_id in node_ids:
        if node_id not in visited:
            depth[node_id] = 0

    raw_columns: dict[int, list[str]] = defaultdict(list)
    for node_id in node_ids:
        raw_columns[depth[node_id]].append(node_id)
    ordered_depths = sorted(raw_columns)
    return {
        node_id: (column_index, row_index)
        for column_index, column_depth in enumerate(ordered_depths)
        for row_index, node_id in enumerate(raw_columns[column_depth])
    }


def _node_boxes(positions: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int, int, int]]:
    column_count = max(column for column, _ in positions.values()) + 1
    rows_per_column: dict[int, int] = defaultdict(int)
    for column, _ in positions.values():
        rows_per_column[column] += 1
    max_rows = max(rows_per_column.values())

    usable_width = _WIDTH - (2 * _MARGIN_X) - ((column_count - 1) * _COLUMN_GAP)
    usable_height = _HEIGHT - _MARGIN_TOP - _MARGIN_BOTTOM - ((max_rows - 1) * _ROW_GAP)
    box_width = max(128, min(236, usable_width // column_count))
    box_height = max(68, min(102, usable_height // max_rows))
    column_step = 0 if column_count == 1 else (_WIDTH - 2 * _MARGIN_X - box_width) / (column_count - 1)

    boxes: dict[str, tuple[int, int, int, int]] = {}
    for node_id, (column, row) in positions.items():
        row_count = rows_per_column[column]
        column_height = row_count * box_height + (row_count - 1) * _ROW_GAP
        column_top = _MARGIN_TOP + ((_HEIGHT - _MARGIN_TOP - _MARGIN_BOTTOM - column_height) / 2)
        left = int(_MARGIN_X + column * column_step)
        top = int(column_top + row * (box_height + _ROW_GAP))
        boxes[node_id] = (left, top, left + box_width, top + box_height)
    return boxes


def _draw_edge(
    draw: ImageDraw.ImageDraw,
    source: tuple[int, int, int, int],
    target: tuple[int, int, int, int],
    label: str,
    is_loop: bool,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    start = (source[2], (source[1] + source[3]) // 2)
    end = (target[0], (target[1] + target[3]) // 2)
    colour = "#a78bfa" if is_loop or end[0] <= start[0] else "#64748b"
    if is_loop or end[0] <= start[0]:
        y = 70
        points = [start, (start[0] + 14, y), (end[0] - 14, y), end]
    else:
        midpoint = (start[0] + end[0]) // 2
        points = [start, (midpoint, start[1]), (midpoint, end[1]), end]
    draw.line(points, fill=colour, width=2, joint="curve")
    _draw_arrowhead(draw, points[-2], end, colour)
    compact_label = " ".join(label.split())[:30]
    if compact_label:
        anchor = points[len(points) // 2]
        draw.text((anchor[0] + 4, anchor[1] - 15), compact_label, fill="#cbd5e1", font=font)


def _draw_arrowhead(
    draw: ImageDraw.ImageDraw,
    previous: tuple[int, int],
    end: tuple[int, int],
    colour: str,
) -> None:
    angle = math.atan2(end[1] - previous[1], end[0] - previous[0])
    size = 8
    points = [
        end,
        (
            end[0] - size * math.cos(angle - math.pi / 6),
            end[1] - size * math.sin(angle - math.pi / 6),
        ),
        (
            end[0] - size * math.cos(angle + math.pi / 6),
            end[1] - size * math.sin(angle + math.pi / 6),
        ),
    ]
    draw.polygon(points, fill=colour)


def _node_colour(node_type: str) -> str:
    return {
        "input": "#60a5fa",
        "model": "#a78bfa",
        "data": "#34d399",
        "evaluation": "#fbbf24",
        "guardrail": "#fb7185",
        "output": "#2dd4bf",
    }.get(node_type.lower(), "#94a3b8")


def _overlap_count(boxes: list[tuple[int, int, int, int]]) -> int:
    count = 0
    for left_index, left in enumerate(boxes):
        for right in boxes[left_index + 1 :]:
            if min(left[2], right[2]) > max(left[0], right[0]) and min(left[3], right[3]) > max(left[1], right[1]):
                count += 1
    return count


def _clipped_count(boxes: list[tuple[int, int, int, int]]) -> int:
    return sum(
        left < 0 or top < 0 or right > _WIDTH or bottom > _HEIGHT
        for left, top, right, bottom in boxes
    )
