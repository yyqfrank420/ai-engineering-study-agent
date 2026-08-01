import type { GraphEdge, GraphStep } from '../../types';


export const NODE_W = 186;
export const NODE_H = 68;
export const NODE_RX = 6;
export const H_PAD = 44;
export const V_PAD = 72;
export const MIN_COL_W = NODE_W + 84;
export const VERTICAL_PAD = 32;
export const VERTICAL_LEVEL_H = NODE_H + 12;
export const INITIAL_FIT_PADDING = 32;
export const GRAPH_LAYOUT_VERSION = 7;

export type GraphOrientation = 'horizontal' | 'vertical';

export function selectGraphOrientation(
  viewportWidth: number,
  depthCount: number,
  widestLevel = 1,
): GraphOrientation {
  const horizontalWidth = Math.max(1, depthCount) * MIN_COL_W + 2 * H_PAD;
  const initialScale = (viewportWidth - 64) / horizontalWidth;
  // The prior depth>=7 guard left six-level graphs in a ~0.38-scale horizontal
  // strip on the evaluation viewport. Use the predicted readable scale once a
  // graph is deep enough to have a meaningful vertical flow.
  // A shallow graph can still be unreadable when one stage fans out to many
  // parallel responsibilities. Vertical flow can wrap that stage into bounded
  // rows; horizontal flow would instead expand its height and shrink every card.
  return (depthCount >= 4 && initialScale < 0.55) || widestLevel >= 4
    ? 'vertical'
    : 'horizontal';
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

export function wrapNodeLabel(label: string, maxLineChars = 24): string[] {
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

export function wrapNodeTechnology(technology: string, maxLineChars = 30): string[] {
  if (technology.length <= maxLineChars) return [technology];
  const words = technology.split(/\s+/).filter(Boolean);
  const lines: string[] = [];

  for (const word of words) {
    const current = lines.at(-1);
    if (!current || `${current} ${word}`.length > maxLineChars) {
      if (lines.length === 2) break;
      lines.push(word);
    } else {
      lines[lines.length - 1] = `${current} ${word}`;
    }
  }

  if (lines.length === 0) return [];
  const represented = lines.join(' ').length;
  if (represented < technology.length) {
    const lastIndex = lines.length - 1;
    lines[lastIndex] = `${lines[lastIndex].slice(0, maxLineChars - 1).trimEnd()}…`;
  }
  return lines;
}

export function overviewEdgeLabelOpacity(
  edge: { flow?: GraphEdge['flow']; type?: GraphEdge['type'] | 'normal' },
  isOverviewRequired = true,
): number {
  if (edge.type === 'loop' || edge.flow === 'feedback') return 0;
  if (!isOverviewRequired || edge.flow === 'deployment') return 0;
  if (edge.flow === 'control') return 0.62;
  return 0.78;
}

/**
 * Select the few relationships a reader needs to understand the diagram at a
 * glance. Dense graphs remain fully inspectable on hover, but their overview
 * is deliberately bounded so labels do not become a second graph on top of
 * the first one.
 *
 * The policy uses only graph semantics and sequence structure. It does not
 * depend on domain vocabulary, fixture names, or known prompts.
 */
export function selectOverviewEdgeIndices(
  edges: GraphEdge[],
  sequence: GraphStep[],
  maximumLabels = 8,
): Set<number> {
  if (maximumLabels <= 0) return new Set();

  const eligible = edges
    .map((edge, index) => ({ edge, index }))
    .filter(({ edge }) => (
      edge.type !== 'loop'
      && edge.flow !== 'feedback'
      && edge.flow !== 'deployment'
    ));
  if (eligible.length <= maximumLabels) {
    return new Set(eligible.map(({ index }) => index));
  }

  const firstStepByNode = new Map<string, number>();
  for (const step of sequence) {
    for (const nodeId of step.nodes ?? []) {
      const existing = firstStepByNode.get(nodeId);
      if (existing === undefined || step.step < existing) {
        firstStepByNode.set(nodeId, step.step);
      }
    }
  }

  const controls = eligible
    .filter(({ edge }) => edge.flow === 'control')
    .map(({ index }) => index);
  const runtime = eligible.filter(({ edge }) => (edge.flow ?? 'runtime') === 'runtime');
  const runtimeByTargetStep = new Map<number, number>();
  for (const { edge, index } of runtime) {
    const targetStep = firstStepByNode.get(edge.target);
    const sourceStep = firstStepByNode.get(edge.source);
    if (targetStep === undefined) continue;
    if (sourceStep !== undefined && sourceStep > targetStep) continue;
    if (!runtimeByTargetStep.has(targetStep)) runtimeByTargetStep.set(targetStep, index);
  }
  const runtimeSpine = runtimeByTargetStep.size > 0
    ? [...runtimeByTargetStep.entries()]
        .sort(([left], [right]) => left - right)
        .map(([, index]) => index)
    : runtime.map(({ index }) => index);

  const reservedControlLabels = controls.length > 0
    ? Math.min(controls.length, Math.max(2, Math.floor(maximumLabels * 0.375)))
    : 0;
  const runtimeBudget = Math.min(runtimeSpine.length, maximumLabels - reservedControlLabels);
  const controlBudget = Math.min(controls.length, maximumLabels - runtimeBudget);
  const remainingBudget = maximumLabels - runtimeBudget - controlBudget;

  const selected = new Set([
    ...sampleEvenly(runtimeSpine, runtimeBudget + Math.min(
      remainingBudget,
      Math.max(0, runtimeSpine.length - runtimeBudget),
    )),
    ...sampleEvenly(controls, controlBudget + Math.max(
      0,
      remainingBudget - Math.max(0, runtimeSpine.length - runtimeBudget),
    )),
  ]);
  return selected;
}

function sampleEvenly(values: number[], limit: number): number[] {
  if (limit <= 0) return [];
  if (values.length <= limit) return values;
  if (limit === 1) return [values[0]];

  return Array.from({ length: limit }, (_, index) => (
    values[Math.round(index * (values.length - 1) / (limit - 1))]
  ));
}
