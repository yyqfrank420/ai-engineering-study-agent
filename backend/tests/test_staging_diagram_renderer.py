import base64

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
            {"source": "outcome", "target": "decision", "label": "feedback", "type": "loop"},
        ],
    }

    encoded, media_type, report = render_staging_diagram(graph)
    image_bytes = base64.b64decode(encoded, validate=True)

    assert media_type == "image/jpeg"
    assert image_bytes.startswith(b"\xff\xd8")
    assert len(image_bytes) < 400_000
    assert report["rendered_nodes"] == 4
    assert report["rendered_edges"] == 4
    assert report["overlap_count"] == 0
    assert report["clipped_nodes"] == 0
    assert report["clipped_edges"] == 0
    assert report["minimum_text_px"] >= 6


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
