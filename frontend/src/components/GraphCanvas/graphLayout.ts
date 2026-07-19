import type { GraphEdge } from '../../types';


export const NODE_W = 186;
export const NODE_H = 68;
export const NODE_RX = 6;
export const H_PAD = 44;
export const V_PAD = 72;
export const MIN_COL_W = NODE_W + 84;
export const VERTICAL_PAD = 32;
export const VERTICAL_LEVEL_H = NODE_H + 12;
export const INITIAL_FIT_PADDING = 32;
export const GRAPH_LAYOUT_VERSION = 3;

export type GraphOrientation = 'horizontal' | 'vertical';

export function selectGraphOrientation(viewportWidth: number, depthCount: number): GraphOrientation {
  const horizontalWidth = Math.max(1, depthCount) * MIN_COL_W + 2 * H_PAD;
  const initialScale = (viewportWidth - 64) / horizontalWidth;
  return depthCount >= 4 && initialScale < 0.72 ? 'vertical' : 'horizontal';
}

export function initialFitScale(
  viewportWidth: number,
  viewportHeight: number,
  layoutWidth: number,
  layoutHeight: number,
): number {
  return Math.min(
    1,
    (viewportWidth - 2 * INITIAL_FIT_PADDING) / layoutWidth,
    (viewportHeight - 2 * INITIAL_FIT_PADDING) / layoutHeight,
  );
}

export function filterRenderableEdges(
  edges: GraphEdge[],
  nodeIds: ReadonlySet<string>,
): GraphEdge[] {
  return edges.filter(edge => nodeIds.has(edge.source) && nodeIds.has(edge.target));
}

export function wrapNodeLabel(label: string, maxLineChars = 26): string[] {
  if (label.length <= maxLineChars) return [label];
  const words = label.split(/\s+/).filter(Boolean);
  if (words.length < 2) return [`${label.slice(0, maxLineChars - 1)}…`];

  let best = [words[0], words.slice(1).join(' ')];
  let bestWidth = Math.max(best[0].length, best[1].length);
  for (let split = 2; split < words.length; split += 1) {
    const candidate = [words.slice(0, split).join(' '), words.slice(split).join(' ')];
    const width = Math.max(candidate[0].length, candidate[1].length);
    if (width < bestWidth) {
      best = candidate;
      bestWidth = width;
    }
  }
  return best.map(line => line.length <= maxLineChars
    ? line
    : `${line.slice(0, maxLineChars - 1)}…`);
}
