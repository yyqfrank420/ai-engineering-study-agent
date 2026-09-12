"""Authoritative render requirements for unpublished graph candidates."""

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class DiagramEvaluationCriteria:
    """Fixed CSS viewport and minimum post-fit node-title size."""

    viewport_width: int = 1440
    viewport_height: int = 960
    minimum_text_px: float = 11.0

    def as_event_data(self) -> dict[str, int | float]:
        return {
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "minimum_text_px": self.minimum_text_px,
        }

    @classmethod
    def from_event_data(cls, value: Any) -> "DiagramEvaluationCriteria":
        if not isinstance(value, dict):
            raise ValueError("graph candidate did not contain render criteria")
        width = value.get("viewport_width")
        height = value.get("viewport_height")
        minimum_text = value.get("minimum_text_px")
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
            or isinstance(minimum_text, bool)
            or not isinstance(minimum_text, (int, float))
            or not math.isfinite(float(minimum_text))
            or float(minimum_text) <= 0
        ):
            raise ValueError("graph candidate render criteria were invalid")
        parsed = cls(
            viewport_width=width,
            viewport_height=height,
            minimum_text_px=float(minimum_text),
        )
        if parsed != cls():
            raise ValueError("graph candidate requested unsupported render criteria")
        return parsed


DIAGRAM_EVALUATION_CRITERIA = DiagramEvaluationCriteria()
MINIMUM_DIAGRAM_NODE_TITLE_PX = DIAGRAM_EVALUATION_CRITERIA.minimum_text_px
MAXIMUM_DIAGRAM_NODES = 60
