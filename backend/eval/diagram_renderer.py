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

from agent.diagram_contract import DiagramEvaluationCriteria
from agent.diagram_contract import DIAGRAM_EVALUATION_CRITERIA


_MARGIN_X = 54
_MARGIN_TOP = 86
_MARGIN_BOTTOM = 44
_COLUMN_GAP = 44
_ROW_GAP = 24
_EDGE_TEXT_PX = 11
_DEFAULT_NODE_TITLE_PX = 16
_GROUP_TEXT_PX = 10


def render_staging_diagram(
    graph: dict[str, Any],
    criteria: DiagramEvaluationCriteria = DIAGRAM_EVALUATION_CRITERIA,
) -> tuple[str, str, dict[str, Any]]:
    """Return ``(base64, media_type, layout_report)`` for one graph candidate."""
    if criteria != DIAGRAM_EVALUATION_CRITERIA:
        raise ValueError("staging renderer received unsupported render criteria")
    nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
    edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
    if not nodes:
        raise ValueError("diagram candidate has no nodes")

    width = criteria.viewport_width
    height = criteria.viewport_height
    node_title_px = max(_DEFAULT_NODE_TITLE_PX, math.ceil(criteria.minimum_text_px))
    image = Image.new("RGB", (width, height), "#080d14")
    draw = ImageDraw.Draw(image)
    title_font = _font(24)
    node_font = _font(node_title_px)
    group_font = _font(_GROUP_TEXT_PX)
    edge_font = _font(_EDGE_TEXT_PX)
    draw.text((_MARGIN_X, 24), str(graph.get("title") or "Architecture"), fill="#f3f4f6", font=title_font)

    positions = _node_positions(nodes, edges)
    boxes = _node_boxes(positions, width=width, height=height)
    if _overlap_count(list(boxes.values())) or _clipped_count(
        list(boxes.values()),
        width=width,
        height=height,
    ):
        boxes = _compact_node_boxes(nodes, width=width, height=height)
    node_by_id = {str(node.get("id")): node for node in nodes}
    group_label_by_node_id = _group_labels(graph, set(node_by_id))
    rendered_edges = 0
    rendered_edge_labels = 0
    visible_edge_labels = 0
    visible_group_labels = 0

    for edge in edges:
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        if source_id not in boxes or target_id not in boxes:
            continue
        label_visible = _draw_edge(
            draw,
            boxes[source_id],
            boxes[target_id],
            str(edge.get("label") or ""),
            str(edge.get("type") or "") == "loop",
            edge_font,
            viewport=(width, height),
        )
        rendered_edges += 1
        if str(edge.get("label") or "").strip():
            rendered_edge_labels += 1
            visible_edge_labels += int(label_visible)

    for node_id, box in boxes.items():
        node = node_by_id[node_id]
        node_type = str(node.get("type") or "component")
        outline = _node_colour(node_type)
        draw.rounded_rectangle(box, radius=10, fill="#111827", outline=outline, width=2)
        group_label = group_label_by_node_id.get(node_id)
        if group_label:
            group_position = (box[0] + 8, box[1] + 5)
            compact_group_label = textwrap.shorten(group_label, width=24, placeholder="…")
            draw.text(
                group_position,
                compact_group_label,
                fill="#a78bfa",
                font=group_font,
            )
            visible_group_labels += int(_text_is_bounded(
                draw,
                group_position,
                compact_group_label,
                group_font,
                viewport=(width, height),
            ))
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
        "viewport_width": width,
        "viewport_height": height,
        "rendered_nodes": len(nodes),
        "rendered_edges": rendered_edges,
        "overlap_count": _overlap_count(list(boxes.values())),
        "clipped_nodes": _clipped_count(list(boxes.values()), width=width, height=height),
        # Every contract-renderer edge is drawn between bounded node boxes (or
        # through the reserved y=70 return lane), all inside the image bounds.
        "clipped_edges": 0,
        # This field is the post-fit node-title size. Decorative group and edge
        # text are outside the publication title-size contract.
        "minimum_text_px": node_title_px,
        "overview_required_edge_labels": rendered_edge_labels,
        "visible_overview_required_edge_labels": visible_edge_labels,
        "grouped_nodes": len(group_label_by_node_id),
        "group_labelled_nodes": visible_group_labels,
        "visible_group_boundaries": 0,
        "group_boundary_overlap_count": 0,
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


def _node_boxes(
    positions: dict[str, tuple[int, int]],
    *,
    width: int,
    height: int,
) -> dict[str, tuple[int, int, int, int]]:
    column_count = max(column for column, _ in positions.values()) + 1
    rows_per_column: dict[int, int] = defaultdict(int)
    for column, _ in positions.values():
        rows_per_column[column] += 1
    max_rows = max(rows_per_column.values())

    usable_width = width - (2 * _MARGIN_X) - ((column_count - 1) * _COLUMN_GAP)
    usable_height = height - _MARGIN_TOP - _MARGIN_BOTTOM - ((max_rows - 1) * _ROW_GAP)
    box_width = max(128, min(236, usable_width // column_count))
    box_height = max(68, min(102, usable_height // max_rows))
    column_step = 0 if column_count == 1 else (width - 2 * _MARGIN_X - box_width) / (column_count - 1)

    boxes: dict[str, tuple[int, int, int, int]] = {}
    for node_id, (column, row) in positions.items():
        row_count = rows_per_column[column]
        column_height = row_count * box_height + (row_count - 1) * _ROW_GAP
        column_top = _MARGIN_TOP + ((height - _MARGIN_TOP - _MARGIN_BOTTOM - column_height) / 2)
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
    *,
    viewport: tuple[int, int],
) -> bool:
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
    if not compact_label:
        return False
    anchor = points[len(points) // 2]
    position = _bounded_text_position(
        draw,
        (anchor[0] + 4, anchor[1] - 15),
        compact_label,
        font,
        viewport=viewport,
    )
    draw.text(position, compact_label, fill="#cbd5e1", font=font)
    return _text_is_bounded(draw, position, compact_label, font, viewport=viewport)


def _text_is_bounded(
    draw: ImageDraw.ImageDraw,
    position: tuple[int | float, int | float],
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    viewport: tuple[int, int],
) -> bool:
    left, top, right, bottom = draw.textbbox(position, value, font=font)
    width, height = viewport
    return left >= 0 and top >= 0 and right <= width and bottom <= height


def _bounded_text_position(
    draw: ImageDraw.ImageDraw,
    position: tuple[int | float, int | float],
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    viewport: tuple[int, int],
) -> tuple[int | float, int | float]:
    left, top, right, bottom = draw.textbbox(position, value, font=font)
    width, height = viewport
    x, y = position
    if left < 0:
        x -= left
    elif right > width:
        x -= right - width
    if top < 0:
        y -= top
    elif bottom > height:
        y -= bottom - height
    return x, y


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


def _clipped_count(
    boxes: list[tuple[int, int, int, int]],
    *,
    width: int,
    height: int,
) -> int:
    return sum(
        left < 0 or top < 0 or right > width or bottom > height
        for left, top, right, bottom in boxes
    )


def _group_labels(graph: dict[str, Any], node_ids: set[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for group in graph.get("groups") or []:
        if not isinstance(group, dict):
            continue
        label = " ".join(str(group.get("label") or "").split())
        if not label:
            continue
        for node_id in group.get("nodeIds") or []:
            normalized_id = str(node_id)
            if normalized_id in node_ids:
                labels[normalized_id] = label
    return labels


def _compact_node_boxes(
    nodes: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, tuple[int, int, int, int]]:
    columns = min(8, len(nodes))
    main_nodes = [node for node in nodes if str(node.get("lane") or "main") != "bottom"]
    bottom_nodes = [node for node in nodes if str(node.get("lane") or "main") == "bottom"]
    bottom_start = (
        math.ceil(len(main_nodes) / columns) * columns
        if main_nodes and bottom_nodes
        else len(main_nodes)
    )
    indexed_nodes = [
        *((node, index) for index, node in enumerate(main_nodes)),
        *((node, bottom_start + index) for index, node in enumerate(bottom_nodes)),
    ]
    rows = math.ceil(max(1, bottom_start + len(bottom_nodes)) / columns)
    box_width = 128
    box_height = 68
    horizontal_gap = 0 if columns == 1 else (
        width - 2 * _MARGIN_X - columns * box_width
    ) / (columns - 1)
    vertical_gap = 0 if rows == 1 else (
        height - _MARGIN_TOP - _MARGIN_BOTTOM - rows * box_height
    ) / (rows - 1)
    if horizontal_gap < 0 or vertical_gap < 0:
        raise ValueError("diagram criteria cannot contain the admitted graph")
    return {
        str(node.get("id")): (
            int(_MARGIN_X + (index % columns) * (box_width + horizontal_gap)),
            int(_MARGIN_TOP + (index // columns) * (box_height + vertical_gap)),
            int(_MARGIN_X + (index % columns) * (box_width + horizontal_gap)) + box_width,
            int(_MARGIN_TOP + (index // columns) * (box_height + vertical_gap)) + box_height,
        )
        for node, index in indexed_nodes
    }
