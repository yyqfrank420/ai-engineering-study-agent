import type { GraphEdge, GraphStep } from '../../types';
import { DIAGRAM_EVALUATION_CRITERIA } from '../../diagramEvaluationContract';


export const NODE_W = 186;
export const NODE_H = 68;
export const NODE_RX = 6;
export const H_PAD = 44;
export const V_PAD = 72;
export const MIN_COL_W = NODE_W + 84;
export const VERTICAL_PAD = 32;
export const VERTICAL_LEVEL_H = NODE_H + 12;
export const VERTICAL_NODE_GAP = 24;
export const VERTICAL_TRACK_GAP = 72;
export const INITIAL_FIT_PADDING = 32;
export const NODE_TITLE_PX = 15.36;
export const MIN_PUBLISHED_TITLE_PX: number = DIAGRAM_EVALUATION_CRITERIA.minimum_text_px;
export const MIN_PUBLISHED_LAYOUT_SCALE = MIN_PUBLISHED_TITLE_PX / NODE_TITLE_PX;
export const BOTTOM_NODE_GAP = 24;
export const COMPACT_LAYOUT_COLUMNS = 8;
export const COMPACT_LAYOUT_ROWS = 8;
export const COMPACT_NODE_GAP = 24;
export const COMPACT_NODE_PITCH = NODE_H + BOTTOM_NODE_GAP;
export const MAX_PUBLISHED_GRAPH_NODES = 60;
export const GRAPH_LAYOUT_VERSION = 11;
export const DIAGRAM_EVALUATION_VIEWPORT = {
  width: DIAGRAM_EVALUATION_CRITERIA.viewport_width,
  height: DIAGRAM_EVALUATION_CRITERIA.viewport_height,
} as const;

export type GraphOrientation = 'horizontal' | 'vertical' | 'compact';

export interface CompactLayoutPlan {
  columns: number;
  rows: number;
  bottomStartIndex: number;
  layoutWidth: number;
  layoutHeight: number;
  scale: number;
}

export function isPublishedLayoutScale(
  scale: number,
  minimumTitlePx = MIN_PUBLISHED_TITLE_PX,
): boolean {
  return NODE_TITLE_PX * scale >= minimumTitlePx;
}

/**
 * The compact layout has enough cells for every backend-accepted graph. The
 * 8-column boundary is deliberate: at 1440 by 960 its 60-node case still
 * exceeds the 11px title gate after fitting. A bottom lane may reserve one
 * extra partial row so those nodes never share a row with main-lane nodes.
 */
export function planCompactLayout(
  viewportWidth: number,
  viewportHeight: number,
  nodeCount: number,
  bottomNodeCount = 0,
): CompactLayoutPlan {
  const safeNodeCount = Math.max(1, Math.floor(nodeCount));
  const safeBottomNodeCount = Math.min(
    safeNodeCount,
    Math.max(0, Math.floor(bottomNodeCount)),
  );
  const mainNodeCount = safeNodeCount - safeBottomNodeCount;
  const columns = Math.min(
    COMPACT_LAYOUT_COLUMNS,
    Math.max(1, Math.ceil(safeNodeCount / COMPACT_LAYOUT_ROWS)),
  );
  const bottomStartIndex = safeBottomNodeCount > 0 && mainNodeCount > 0
    ? Math.ceil(mainNodeCount / columns) * columns
    : mainNodeCount;
  const occupiedSlots = bottomStartIndex + safeBottomNodeCount;
  const rows = Math.ceil(Math.max(1, occupiedSlots) / columns);
  const layoutWidth = 2 * H_PAD
    + columns * NODE_W
    + Math.max(0, columns - 1) * COMPACT_NODE_GAP;
  const layoutHeight = 2 * V_PAD
    + NODE_H
    + Math.max(0, rows - 1) * COMPACT_NODE_PITCH;

  return {
    columns,
    rows,
    bottomStartIndex,
    layoutWidth,
    layoutHeight,
    scale: initialFitScale(viewportWidth, viewportHeight, layoutWidth, layoutHeight),
  };
}

export function selectGraphLayout(
  horizontalFitScale: number,
  verticalFitScale: number,
  minimumTitlePx = MIN_PUBLISHED_TITLE_PX,
): GraphOrientation {
  if (isPublishedLayoutScale(horizontalFitScale, minimumTitlePx)) return 'horizontal';
  if (isPublishedLayoutScale(verticalFitScale, minimumTitlePx)) return 'vertical';
  return 'compact';
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

export function boundLabelCenter(
  position: { x: number; y: number },
  size: { width: number; height: number },
  bounds: { width: number; height: number },
  padding = 4,
): { x: number; y: number } {
  const boundedCenter = (value: number, extent: number, labelExtent: number): number => {
    if (extent <= 0) return 0;
    const safePadding = Math.max(0, Math.min(padding, extent / 2));
    const halfLabel = Math.max(0, labelExtent) / 2;
    const minimum = Math.min(extent / 2, safePadding + halfLabel);
    const maximum = Math.max(extent / 2, extent - safePadding - halfLabel);
    return Math.min(maximum, Math.max(minimum, value));
  };

  return {
    x: boundedCenter(position.x, bounds.width, size.width),
    y: boundedCenter(position.y, bounds.height, size.height),
  };
}

export interface VerticalLayoutPlan {
  layoutWidth: number;
  layoutHeight: number;
  nodesPerRow: number;
  scale: number;
  levels: VerticalLevelPlacement[];
}

export interface VerticalLevelPlacement {
  track: number;
  direction: 1 | -1;
  x: number;
  y: number;
  width: number;
}

/**
 * Use the two-dimensional canvas for wide topology levels before shrinking the
 * whole diagram. The virtual canvas may be wider than the visible viewport;
 * auto-fit then chooses the largest readable scale across both dimensions.
 */
export function planVerticalLayout(
  viewportWidth: number,
  viewportHeight: number,
  levelSizes: number[],
): VerticalLayoutPlan {
  const normalizedLevelSizes = (levelSizes.length > 0 ? levelSizes : [1])
    .map(size => Math.max(1, Math.floor(size)));
  const widestLevel = Math.max(1, ...normalizedLevelSizes);
  const minimumNodesPerRow = Math.ceil(Math.sqrt(widestLevel));
  let best: VerticalLayoutPlan | null = null;
  const maximumTracks = Math.min(
    normalizedLevelSizes.length,
    Math.max(
      1,
      Math.floor(
        (viewportWidth - 2 * H_PAD + VERTICAL_TRACK_GAP)
        / (NODE_W + VERTICAL_TRACK_GAP),
      ),
    ),
  );

  for (
    let nodesPerRow = minimumNodesPerRow;
    nodesPerRow <= widestLevel;
    nodesPerRow += 1
  ) {
    const levelRows = normalizedLevelSizes.map(size => Math.ceil(size / nodesPerRow));
    for (let trackCount = 1; trackCount <= maximumTracks; trackCount += 1) {
      const ranges = partitionVerticalLevels(
        levelRows,
        normalizedLevelSizes,
        nodesPerRow,
        trackCount,
      );
      const trackRows = ranges.map(([start, end]) => (
        levelRows.slice(start, end).reduce((total, rows) => total + rows, 0)
      ));
      const trackWidths = ranges.map(([start, end]) => {
        const populatedColumns = Math.max(
          1,
          ...normalizedLevelSizes
            .slice(start, end)
            .map(size => Math.min(size, nodesPerRow)),
        );
        return populatedColumns * NODE_W
          + Math.max(0, populatedColumns - 1) * VERTICAL_NODE_GAP;
      });
      const contentWidth = trackWidths.reduce((total, value) => total + value, 0)
        + Math.max(0, trackCount - 1) * VERTICAL_TRACK_GAP;
      const layoutWidth = Math.max(viewportWidth, contentWidth + 2 * H_PAD);
      const layoutHeight = 2 * VERTICAL_PAD
        + Math.max(1, ...trackRows) * VERTICAL_LEVEL_H;
      const scale = initialFitScale(
        viewportWidth,
        viewportHeight,
        layoutWidth,
        layoutHeight,
      );
      const contentStart = (layoutWidth - contentWidth) / 2;
      const levels: VerticalLevelPlacement[] = [];
      let trackX = contentStart;

      ranges.forEach(([start, end], track) => {
        const direction: 1 | -1 = track % 2 === 0 ? 1 : -1;
        let rowsBefore = 0;
        for (let level = start; level < end; level += 1) {
          const rows = levelRows[level];
          const rowOffset = direction === 1
            ? rowsBefore
            : trackRows[track] - rowsBefore - rows;
          levels[level] = {
            track,
            direction,
            x: trackX,
            y: VERTICAL_PAD + rowOffset * VERTICAL_LEVEL_H,
            width: trackWidths[track],
          };
          rowsBefore += rows;
        }
        trackX += trackWidths[track] + VERTICAL_TRACK_GAP;
      });

      const candidate = {
        layoutWidth,
        layoutHeight,
        nodesPerRow,
        scale,
        levels,
      };
      if (
        best === null
        || scale > best.scale + 0.000_001
        || (
          Math.abs(scale - best.scale) <= 0.000_001
          && layoutWidth * layoutHeight < best.layoutWidth * best.layoutHeight
        )
      ) {
        best = candidate;
      }
    }
  }

  return best ?? {
    layoutWidth: viewportWidth,
    layoutHeight: 2 * VERTICAL_PAD + VERTICAL_LEVEL_H,
    nodesPerRow: 1,
    scale: initialFitScale(
      viewportWidth,
      viewportHeight,
      viewportWidth,
      2 * VERTICAL_PAD + VERTICAL_LEVEL_H,
    ),
    levels: [{
      track: 0,
      direction: 1,
      x: (viewportWidth - NODE_W) / 2,
      y: VERTICAL_PAD,
      width: NODE_W,
    }],
  };
}


export function partitionVerticalLevels(
  levelRows: number[],
  levelSizes: number[],
  nodesPerRow: number,
  trackCount: number,
): Array<[number, number]> {
  interface PartitionState {
    maximumRows: number;
    totalWidth: number;
    ranges: Array<[number, number]>;
  }
  const prefixRows = [0];
  for (const rows of levelRows) prefixRows.push(prefixRows.at(-1)! + rows);
  const table: Array<Array<PartitionState | null>> = Array.from(
    { length: trackCount + 1 },
    () => Array(levelRows.length + 1).fill(null),
  );
  table[0][0] = { maximumRows: 0, totalWidth: 0, ranges: [] };

  for (let tracks = 1; tracks <= trackCount; tracks += 1) {
    for (let end = tracks; end <= levelRows.length; end += 1) {
      for (let start = tracks - 1; start < end; start += 1) {
        const previous = table[tracks - 1][start];
        if (!previous) continue;
        const rows = prefixRows[end] - prefixRows[start];
        const populatedColumns = Math.max(
          1,
          ...levelSizes
            .slice(start, end)
            .map(size => Math.min(size, nodesPerRow)),
        );
        const width = populatedColumns * NODE_W
          + Math.max(0, populatedColumns - 1) * VERTICAL_NODE_GAP;
        const candidate: PartitionState = {
          maximumRows: Math.max(previous.maximumRows, rows),
          totalWidth: previous.totalWidth + width,
          ranges: [...previous.ranges, [start, end]],
        };
        const current = table[tracks][end];
        if (
          current === null
          || candidate.maximumRows < current.maximumRows
          || (
            candidate.maximumRows === current.maximumRows
            && candidate.totalWidth < current.totalWidth
          )
        ) {
          table[tracks][end] = candidate;
        }
      }
    }
  }

  return table[trackCount][levelRows.length]?.ranges ?? [[0, levelRows.length]];
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
