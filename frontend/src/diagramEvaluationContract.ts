import type { DiagramEvaluationCriteria } from './types';


export const DIAGRAM_EVALUATION_CRITERIA = {
  viewport_width: 1440,
  viewport_height: 960,
  minimum_text_px: 11,
} as const satisfies DiagramEvaluationCriteria;

export function isSupportedDiagramEvaluationCriteria(
  value: unknown,
): value is DiagramEvaluationCriteria {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const criteria = value as Record<string, unknown>;
  return Object.keys(criteria).length === 3
    && criteria.viewport_width === DIAGRAM_EVALUATION_CRITERIA.viewport_width
    && criteria.viewport_height === DIAGRAM_EVALUATION_CRITERIA.viewport_height
    && criteria.minimum_text_px === DIAGRAM_EVALUATION_CRITERIA.minimum_text_px;
}
