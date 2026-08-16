import base64
from io import BytesIO

from PIL import Image
import pytest

from agent.diagram_contract import DiagramEvaluationCriteria
from eval.diagram_renderer import render_staging_diagram


def test_staging_renderer_produces_a_bounded_visible_diagram():
    graph = {
        "title": "Marketing control loop",
        "nodes": [
            {"id": "objective", "label": "Constrained objective", "type": "input"},
            {"id": "decision", "label": "Creative decision", "type": "model"},
            {"id": "approval", "label": "Policy approval", "type": "guardrail"},
            {"id": "outcome", "label": "Measured outcome", "type": "evaluation"},
        ],
        "edges": [
            {"source": "objective", "target": "decision", "label": "constraints"},
            {"source": "decision", "target": "approval", "label": "proposal"},
            {"source": "approval", "target": "outcome", "label": "controlled action"},
            {
                "source": "outcome",
                "target": "decision",
                "label": "feedback",
                "type": "loop",
            },
        ],
        "groups": [
            {
                "id": "runtime",
                "label": "Runtime decisions",
                "nodeIds": ["objective", "decision", "approval"],
            },
        ],
    }

    encoded, media_type, report = render_staging_diagram(graph)
    image_bytes = base64.b64decode(encoded, validate=True)
    image = Image.open(BytesIO(image_bytes))

    assert media_type == "image/jpeg"
    assert image_bytes.startswith(b"\xff\xd8")
    assert len(image_bytes) < 400_000
    assert image.size == (1440, 960)
    assert report["viewport_width"] == 1440
    assert report["viewport_height"] == 960
    assert report["rendered_nodes"] == 4
    assert report["rendered_edges"] == 4
    assert report["overlap_count"] == 0
    assert report["clipped_nodes"] == 0
    assert report["clipped_edges"] == 0
    assert report["minimum_text_px"] == 16
    assert report["overview_required_edge_labels"] == 4
    assert report["visible_overview_required_edge_labels"] == 4
    assert report["grouped_nodes"] == 3
    assert report["group_labelled_nodes"] == 3
    assert report["visible_group_boundaries"] == 0
    assert report["group_boundary_overlap_count"] == 0


def test_staging_renderer_reports_only_edges_it_actually_draws():
    graph = {
        "nodes": [
            {"id": "input", "label": "Input", "type": "input"},
            {"id": "output", "label": "Output", "type": "output"},
        ],
        "edges": [
            {"source": "input", "target": "output", "label": "valid"},
            {"source": "missing", "target": "output", "label": "invalid"},
        ],
    }

    _encoded, _media_type, report = render_staging_diagram(graph)

    assert report["rendered_edges"] == 1


def test_staging_renderer_rejects_unsupported_render_criteria():
    criteria = DiagramEvaluationCriteria(
        viewport_width=900,
        viewport_height=600,
        minimum_text_px=18,
    )
    graph = {
        "nodes": [{"id": "input", "label": "Input", "type": "input"}],
        "edges": [],
    }

    with pytest.raises(ValueError, match="unsupported render criteria"):
        render_staging_diagram(graph, criteria)


def test_staging_renderer_has_total_capacity_for_sixty_nodes_and_bottom_lane():
    nodes = [
        {
            "id": f"node-{index}",
            "label": f"Responsibility {index}",
            "type": "service",
            "lane": "bottom" if index >= 57 else "main",
        }
        for index in range(60)
    ]
    graph = {
        "nodes": nodes,
        "edges": [
            {
                "source": f"node-{index}",
                "target": f"node-{index + 1}",
                "label": f"sends record {index}",
            }
            for index in range(59)
        ],
    }

    _encoded, _media_type, report = render_staging_diagram(graph)

    assert report["rendered_nodes"] == 60
    assert report["rendered_edges"] == 59
    assert report["overlap_count"] == 0
    assert report["clipped_nodes"] == 0
    assert report["clipped_edges"] == 0
    assert report["minimum_text_px"] >= 11
    assert report["visible_overview_required_edge_labels"] == 59
