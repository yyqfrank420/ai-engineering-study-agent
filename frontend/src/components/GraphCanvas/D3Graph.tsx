// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/D3Graph.tsx
// Purpose: Architecture diagram rendered with a STATIC directional layout
//          (no force simulation). Shallow graphs flow left-to-right; deep
//          graphs flow top-to-bottom so their labels remain readable.
// Language: TypeScript / React / D3 v7
// Connects to: types/index.ts, hooks/useGraph.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { GraphData, GraphEdge, GraphGroup, GraphNode, GraphViewState } from '../../types';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { TYPE_STYLE, FALLBACK_STYLE } from '../../utils/graphColors';
import {
  filterRenderableEdges,
  GRAPH_LAYOUT_VERSION,
  H_PAD,
  INITIAL_FIT_PADDING,
  initialFitScale,
  MIN_COL_W,
  NODE_H,
  NODE_RX,
  NODE_W,
  overviewEdgeLabelOpacity,
  selectOverviewEdgeIndices,
  selectGraphOrientation,
  VERTICAL_LEVEL_H,
  VERTICAL_PAD,
  V_PAD,
  wrapNodeLabel,
  wrapNodeTechnology,
} from './graphLayout';

const EDGE_LABEL_MAX_CHARS = 24;

// Color palette imported from ../../utils/graphColors (TYPE_STYLE, FALLBACK_STYLE)

// ── Group box colors ─────────────────────────────────────────────────────────
const GROUP_PALETTE = [
  { fill: 'rgba(139,92,246,0.05)',  stroke: 'rgba(139,92,246,0.28)',  label: '#a78bfa' },
  { fill: 'rgba(16,185,129,0.05)', stroke: 'rgba(16,185,129,0.28)',  label: '#34d399' },
  { fill: 'rgba(217,119,6,0.05)',  stroke: 'rgba(217,119,6,0.28)',   label: '#fbbf24' },
  { fill: 'rgba(59,130,246,0.05)', stroke: 'rgba(59,130,246,0.28)',  label: '#60a5fa' },
  { fill: 'rgba(244,63,94,0.05)',  stroke: 'rgba(244,63,94,0.25)',   label: '#fb7185' },
  { fill: 'rgba(20,184,166,0.05)', stroke: 'rgba(20,184,166,0.25)',  label: '#2dd4bf' },
];

// ── Topological column assignment ────────────────────────────────────────────
// Strips back-edges (cycles) via iterative DFS, then runs longest-path on the
// remaining DAG so every node gets its maximum depth from source nodes.
// Result: a Map<nodeId, columnIndex> where col 0 = leftmost entry node.
function assignColumns(
  nodeIds: string[],
  edges: Array<{ source: string; target: string }>,
): Map<string, number> {
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) adj.set(id, []);
  for (const e of edges) adj.get(e.source)?.push(e.target);

  // DFS: mark back edges (those that close a cycle)
  const color = new Map<string, number>(nodeIds.map(id => [id, 0]));
  const backEdgeSet = new Set<string>();

  for (const start of nodeIds) {
    if (color.get(start) !== 0) continue;
    const stack: Array<[string, number]> = [[start, 0]];
    color.set(start, 1);
    while (stack.length > 0) {
      const frame = stack[stack.length - 1];
      const [id, ci] = frame;
      const children = adj.get(id) ?? [];
      if (ci >= children.length) {
        color.set(id, 2);
        stack.pop();
      } else {
        frame[1]++;
        const next = children[ci];
        if (color.get(next) === 1) {
          backEdgeSet.add(`${id}→${next}`);
        } else if (color.get(next) === 0) {
          color.set(next, 1);
          stack.push([next, 0]);
        }
      }
    }
  }

  // Build DAG without back edges
  const dagAdj   = new Map<string, string[]>();
  const dagInDeg = new Map<string, number>();
  for (const id of nodeIds) { dagAdj.set(id, []); dagInDeg.set(id, 0); }
  for (const e of edges) {
    if (!backEdgeSet.has(`${e.source}→${e.target}`)) {
      dagAdj.get(e.source)!.push(e.target);
      dagInDeg.set(e.target, (dagInDeg.get(e.target) ?? 0) + 1);
    }
  }

  // Longest-path via Kahn's (topological BFS)
  const cols   = new Map<string, number>(nodeIds.map(id => [id, 0]));
  const tmpDeg = new Map(dagInDeg);
  const queue  = nodeIds.filter(id => (tmpDeg.get(id) ?? 0) === 0);
  let qi = 0;
  while (qi < queue.length) {
    const id    = queue[qi++];
    const myCol = cols.get(id)!;
    for (const next of (dagAdj.get(id) ?? [])) {
      cols.set(next, Math.max(cols.get(next)!, myCol + 1));
      tmpDeg.set(next, tmpDeg.get(next)! - 1);
      if (tmpDeg.get(next) === 0) queue.push(next);
    }
  }
  return cols;
}

// ── Edge tooltip data ────────────────────────────────────────────────────────
interface EdgeTooltip {
  x: number; y: number;
  label: string; technology: string; sync: string; description: string;
}

interface D3GraphProps {
  graphData: GraphData;
  currentStep: number;
  activeNodeIds: Set<string>;
  onNodeClick: (node: GraphNode) => void;
  initialViewState?: GraphViewState;
  onViewStateChange?: (state: GraphViewState) => void;
}

type RenderNode = GraphNode & {
  x: number;
  y: number;
};

type RenderLink = {
  source: RenderNode;
  target: RenderNode;
  label: string;
  technology: string;
  sync: GraphEdge['sync'];
  description: string;
  stepNum: number | null;
  edgeType: 'normal' | 'loop';
  flow: NonNullable<GraphEdge['flow']>;
  overviewRequired: boolean;
};

interface GraphRenderState {
  nodeSel: d3.Selection<SVGGElement, RenderNode, SVGGElement, unknown>;
  link: d3.Selection<SVGPathElement, RenderLink, SVGGElement, unknown>;
  linkHit: d3.Selection<SVGPathElement, RenderLink, SVGGElement, unknown>;
  edgeLabelGroup: d3.Selection<SVGGElement, RenderLink, SVGGElement, unknown>;
  stepBadgeGroup: d3.Selection<SVGGElement, RenderLink, SVGGElement, unknown>;
  nodeFirstStep: Map<string, number>;
  sequenceLength: number;
  isForward: (d: RenderLink) => boolean;
}

function compareNullableNumber(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}

function averageOrNull(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

// graphStructureKey imported from ../../utils/graphStructureKey

export function D3Graph({
  graphData,
  currentStep,
  activeNodeIds,
  onNodeClick,
  initialViewState,
  onViewStateChange,
}: D3GraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const renderStateRef = useRef<GraphRenderState | null>(null);
  const onNodeClickRef = useRef(onNodeClick);
  const onViewStateChangeRef = useRef(onViewStateChange);
  const graphDataRef = useRef(graphData);
  const initialViewStateRef = useRef(initialViewState);
  const renderedStructureRef = useRef<string | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const [viewportRevision, setViewportRevision] = useState(0);
  const structureKey = graphStructureKey(graphData);
  const detailKey = graphData
    ? graphData.nodes.map(node => `${node.id}:${node.detail || node.design_origin === 'applied' ? '1' : '0'}`).join('|')
    : 'null';

  useEffect(() => {
    graphDataRef.current = graphData;
  }, [graphData]);

  useEffect(() => {
    initialViewStateRef.current = initialViewState;
  }, [initialViewState]);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    onViewStateChangeRef.current = onViewStateChange;
  }, [onViewStateChange]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || typeof ResizeObserver === 'undefined') return;
    let width = Math.round(svg.getBoundingClientRect().width);
    let height = Math.round(svg.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      const nextWidth = Math.round(box?.width ?? svg.getBoundingClientRect().width);
      const nextHeight = Math.round(box?.height ?? svg.getBoundingClientRect().height);
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      setViewportRevision(value => value + 1);
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);

  // ── Main render effect — fires when graphData changes ───────────────────────
  useEffect(() => {
    if (!svgRef.current) return;
    const renderGraphData = graphDataRef.current;
    const renderInitialViewState = initialViewStateRef.current;
    if (!renderGraphData) return;
    setEdgeTooltip(null);

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width  = svgRef.current.clientWidth  || 760;
    const height = svgRef.current.clientHeight || 500;

    // ── Layout constants ──────────────────────────────────────────────────────
    const RETURN_ARC_OFFSET = 18;

    // ── Arrowhead markers ─────────────────────────────────────────────────────
    const defs = svg.append('defs');

    const gridPattern = defs.append('pattern')
      .attr('id', 'architecture-grid')
      .attr('width', 24)
      .attr('height', 24)
      .attr('patternUnits', 'userSpaceOnUse');
    gridPattern.append('circle')
      .attr('cx', 1)
      .attr('cy', 1)
      .attr('r', 0.8)
      .attr('fill', 'rgba(148,163,184,0.11)');

    const cardShadow = defs.append('filter')
      .attr('id', 'architecture-card-shadow')
      .attr('x', '-20%')
      .attr('y', '-30%')
      .attr('width', '140%')
      .attr('height', '160%');
    cardShadow.append('feDropShadow')
      .attr('dx', 0)
      .attr('dy', 5)
      .attr('stdDeviation', 7)
      .attr('flood-color', '#000814')
      .attr('flood-opacity', 0.34);

    // Standard arrowhead (dark gray) — used for forward edges
    defs.append('marker')
      .attr('id', 'arrow-fwd')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 8).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#374151');

    // Violet arrowhead — used for return/back edges so they're visually distinct
    defs.append('marker')
      .attr('id', 'arrow-ret')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 8).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', 'rgba(167,139,250,0.7)');

    svg.append('rect')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('fill', 'url(#architecture-grid)')
      .style('pointer-events', 'none');

    // ── Pan + zoom container ──────────────────────────────────────────────────
    // Store the zoom behaviour so we can set the initial fit transform later.
    const g = svg.append('g');
    const emitViewState = (nodesToPersist: RenderNode[], transform: d3.ZoomTransform) => {
      onViewStateChangeRef.current?.({
        layoutVersion: GRAPH_LAYOUT_VERSION,
        nodePositions: Object.fromEntries(
          nodesToPersist.map((node) => [
            node.id,
            {
              x: node.x,
              y: node.y,
            },
          ]),
        ),
        viewport: {
          x: transform.x,
          y: transform.y,
          k: transform.k,
        },
      });
    };

    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      })
      .on('end', (event) => {
        emitViewState(nodes, event.transform);
      });
    svg.call(zoomBehavior);

    // ── Deep-copy nodes (D3 may mutate x/y) ──────────────────────────────────
    const nodes: RenderNode[] = renderGraphData.nodes.map(n => ({ ...n, x: 0, y: 0 }));
    const nodeById: Record<string, RenderNode> = {};
    for (const n of nodes) nodeById[n.id] = n;

    // ── Assign topological columns ────────────────────────────────────────────
    const colMap  = assignColumns(nodes.map(n => n.id), renderGraphData.edges);
    const numCols = Math.max(1, ...colMap.values()) + 1;

    // Group nodes by column, then assign fixed (x, y) positions
    const colBuckets = new Map<number, RenderNode[]>();
    for (const n of nodes) {
      const c = colMap.get(n.id) ?? 0;
      if (!colBuckets.has(c)) colBuckets.set(c, []);
      colBuckets.get(c)!.push(n);
    }
    const widestLevel = Math.max(1, ...Array.from(colBuckets.values(), bucket => bucket.length));
    const orientation = selectGraphOrientation(width, numCols, widestLevel);
    const isNewStructure = renderedStructureRef.current !== structureKey;
    const restoreViewState = isNewStructure
      && renderInitialViewState?.layoutVersion === GRAPH_LAYOUT_VERSION
      ? renderInitialViewState
      : undefined;
    renderedStructureRef.current = structureKey;
    const colWidth = Math.max(MIN_COL_W, (width - 2 * H_PAD) / numCols);

    const incomingIds = new Map<string, string[]>();
    const outgoingIds = new Map<string, string[]>();
    for (const node of nodes) {
      incomingIds.set(node.id, []);
      outgoingIds.set(node.id, []);
    }
    for (const edge of renderGraphData.edges) {
      incomingIds.get(edge.target)?.push(edge.source);
      outgoingIds.get(edge.source)?.push(edge.target);
    }

    const sequenceRank = new Map<string, number>();
    for (const step of renderGraphData.sequence ?? []) {
      const stepNumber = typeof step.step === 'number' ? step.step : Number.MAX_SAFE_INTEGER;
      for (const nodeId of step.nodes ?? []) {
        const existingRank = sequenceRank.get(nodeId);
        if (existingRank === undefined || stepNumber < existingRank) {
          sequenceRank.set(nodeId, stepNumber);
        }
      }
    }

    const groupRank = new Map<string, number>();
    (renderGraphData.groups ?? []).forEach((group, index) => {
      group.nodeIds.forEach(nodeId => {
        if (!groupRank.has(nodeId)) groupRank.set(nodeId, index);
      });
    });

    const orderById = new Map<string, number>();
    const sortedColumns = Array.from(colBuckets.keys()).sort((a, b) => a - b);
    for (const columnIndex of sortedColumns) {
      const bucket = colBuckets.get(columnIndex) ?? [];
      bucket.sort((a: RenderNode, b: RenderNode) => {
        const groupCompare = compareNullableNumber(
          groupRank.get(a.id) ?? null,
          groupRank.get(b.id) ?? null,
        );
        if (groupCompare !== 0) return groupCompare;

        const aIncoming = incomingIds.get(a.id) ?? [];
        const bIncoming = incomingIds.get(b.id) ?? [];

        const aBarycenter = averageOrNull(
          aIncoming
            .map((id) => orderById.get(id))
            .filter((value): value is number => value !== undefined),
        );
        const bBarycenter = averageOrNull(
          bIncoming
            .map((id) => orderById.get(id))
            .filter((value): value is number => value !== undefined),
        );

        const barycenterCompare = compareNullableNumber(aBarycenter, bBarycenter);
        if (barycenterCompare !== 0) return barycenterCompare;

        const stepCompare = compareNullableNumber(
          sequenceRank.get(a.id) ?? null,
          sequenceRank.get(b.id) ?? null,
        );
        if (stepCompare !== 0) return stepCompare;

        const outDegreeCompare = (outgoingIds.get(b.id)?.length ?? 0) - (outgoingIds.get(a.id)?.length ?? 0);
        if (outDegreeCompare !== 0) return outDegreeCompare;

        return (a.label ?? '').localeCompare(b.label ?? '');
      });

      bucket.forEach((node: RenderNode, index: number) => {
        orderById.set(node.id, index);
      });
    }
    // ── Vertical band layout ──────────────────────────────────────────────────
    // lane:'bottom' nodes (cross-cutting observability) go in a reserved bottom band.
    // All other nodes share the main band.
    //
    // MIN_ROW_H: guaranteed minimum spacing between node centres in a column.
    // If the densest column needs more height than the canvas, the layout expands
    // beyond the visible area. The auto-fit zoom below brings everything into view.
    const BOTTOM_BAND_H = 108;
    const MIN_ROW_H     = NODE_H + 64;   // slightly looser spacing without blowing out the layout

    const ungroupedRank = (renderGraphData.groups ?? []).length;
    const mainGroupRanks = Array.from(new Set(
      nodes
        .filter(node => node.lane !== 'bottom')
        .map(node => groupRank.get(node.id) ?? ungroupedRank),
    )).sort((a, b) => a - b);
    const maxNodesPerGroupInColumn = new Map<number, number>();
    for (const rank of mainGroupRanks) {
      maxNodesPerGroupInColumn.set(rank, Math.max(
        1,
        ...Array.from(colBuckets.values()).map(bucket => bucket.filter(
          node => node.lane !== 'bottom' && (groupRank.get(node.id) ?? ungroupedRank) === rank,
        ).length),
      ));
    }
    const totalMainSlots = Math.max(
      1,
      mainGroupRanks.reduce((total, rank) => total + (maxNodesPerGroupInColumn.get(rank) ?? 1), 0),
    );
    // effectiveMainH is the actual height used for main-band Y calculation.
    // It's at least the canvas main band, but expands to fit all nodes.
    const canvasMainH    = height - 2 * V_PAD - BOTTOM_BAND_H;
    const effectiveMainH = Math.max(canvasMainH, totalMainSlots * MIN_ROW_H);

    // Keep parallel fan-out readable by wrapping a wide topology level. The
    // previous layout widened the virtual canvas for every peer, then shrank
    // all titles below the publication threshold to fit the viewport.
    const VERTICAL_NODE_GAP = 24;
    const verticalNodesPerRow = Math.max(
      1,
      Math.floor((width - 2 * H_PAD + VERTICAL_NODE_GAP) / (NODE_W + VERTICAL_NODE_GAP)),
    );
    const verticalLayoutW = width;
    const verticalLevelStart = new Map<number, number>();
    let verticalCursor = VERTICAL_PAD;
    for (const columnIndex of sortedColumns) {
      verticalLevelStart.set(columnIndex, verticalCursor);
      const bucketSize = colBuckets.get(columnIndex)?.length ?? 0;
      verticalCursor += Math.max(1, Math.ceil(bucketSize / verticalNodesPerRow)) * VERTICAL_LEVEL_H;
    }

    for (const [c, bucket] of colBuckets) {
      if (orientation === 'vertical') {
        bucket.forEach((node: RenderNode, index: number) => {
          const wrappedRow = Math.floor(index / verticalNodesPerRow);
          const indexInRow = index % verticalNodesPerRow;
          const rowStart = wrappedRow * verticalNodesPerRow;
          const nodesInRow = Math.min(verticalNodesPerRow, bucket.length - rowStart);
          const rowWidth = nodesInRow * NODE_W + (nodesInRow - 1) * VERTICAL_NODE_GAP;
          node.x = (width - rowWidth) / 2 + NODE_W / 2 + indexInRow * (NODE_W + VERTICAL_NODE_GAP);
          node.y = (verticalLevelStart.get(c) ?? VERTICAL_PAD)
            + (wrappedRow + 0.5) * VERTICAL_LEVEL_H;
        });
        continue;
      }

      const x = H_PAD + (c + 0.5) * colWidth;
      const mainNodes = bucket.filter((node: RenderNode) => node.lane !== 'bottom');
      const bottomNodes = bucket.filter((node: RenderNode) => node.lane === 'bottom');

      let groupSlotStart = 0;
      for (const rank of mainGroupRanks) {
        const groupNodes = mainNodes.filter(
          node => (groupRank.get(node.id) ?? ungroupedRank) === rank,
        );
        const groupSlotCount = maxNodesPerGroupInColumn.get(rank) ?? 1;
        groupNodes.forEach((node: RenderNode, index: number) => {
          node.x = x;
          const slot = groupSlotStart + groupSlotCount * ((index + 0.5) / groupNodes.length);
          node.y = V_PAD + (effectiveMainH / totalMainSlots) * slot;
        });
        groupSlotStart += groupSlotCount;
      }

      bottomNodes.forEach((node: RenderNode, index: number) => {
        node.x = x;
        node.y = V_PAD + effectiveMainH + (BOTTOM_BAND_H / Math.max(bottomNodes.length, 1)) * (index + 0.5);
      });
    }

    for (const node of nodes) {
      const persistedPosition = restoreViewState?.nodePositions[node.id];
      if (!persistedPosition) continue;
      node.x = persistedPosition.x;
      node.y = persistedPosition.y;
    }

    // Total layout dimensions (used for auto-fit zoom below)
    const layoutW = orientation === 'vertical'
      ? verticalLayoutW
      : numCols * colWidth + 2 * H_PAD;
    const layoutH = orientation === 'vertical'
      ? verticalCursor + VERTICAL_PAD
      : V_PAD + effectiveMainH + BOTTOM_BAND_H + V_PAD;

    // ── Resolve edges to node object references ───────────────────────────────
    // Also attach the sequence step number for each edge so we can badge it.
    const sequence = renderGraphData.sequence ?? [];
    const nodeFirstStep = new Map<string, number>();
    for (const step of sequence) {
      const stepNumber = typeof step.step === 'number' ? step.step : 0;
      for (const nodeId of step.nodes ?? []) {
        const existingStep = nodeFirstStep.get(nodeId);
        if (existingStep === undefined || stepNumber < existingStep) {
          nodeFirstStep.set(nodeId, stepNumber);
        }
      }
    }
    // Preserve every declared edge with valid endpoints. Backward links are
    // routed around the diagram; silently dropping them makes the picture lie.
    const nodeIds = new Set(nodes.map(node => node.id));
    const renderableEdges = filterRenderableEdges(renderGraphData.edges, nodeIds);
    const overviewEdgeIndices = selectOverviewEdgeIndices(renderableEdges, sequence);
    const links = renderableEdges.map((e, edgeIndex) => {
      let stepNum: number | null = null;
      for (const step of sequence) {
        if ((step.nodes ?? []).includes(e.target)) { stepNum = step.step; break; }
      }
      const src = nodeById[e.source]!;
      const tgt = nodeById[e.target]!;
      return {
        source:      src,
        target:      tgt,
        label:       e.label,
        technology:  e.technology ?? '',
        sync:        e.sync ?? 'sync',
        description: e.description ?? '',
        stepNum,
        edgeType:    (e.type ?? 'normal') as 'normal' | 'loop',
        flow:        e.flow ?? (e.type === 'loop' ? 'feedback' : 'runtime'),
        overviewRequired: overviewEdgeIndices.has(edgeIndex),
      };
    });

    // A node hover is the discoverable way to inspect every relationship at
    // that boundary, including secondary and feedback paths.
    const incidentIndicesByNode = new Map<string, number[]>();
    links.forEach((link, index) => {
      for (const nodeId of new Set([link.source.id, link.target.id])) {
        incidentIndicesByNode.set(nodeId, [...(incidentIndicesByNode.get(nodeId) ?? []), index]);
      }
    });

    // ── Hinge helpers ─────────────────────────────────────────────────────────
    // Forward edge (target is clearly to the right of source):
    //   exits the RIGHT border of source, enters the LEFT border of target.
    // Return/back edge (target is to the left of or at the same column):
    //   exits the TOP border of source, enters the TOP border of target.
    //   The path arcs above the canvas, keeping the forward edges clean.

    const isForward = (d: RenderLink): boolean => orientation === 'vertical'
      ? d.target.y > d.source.y + 4
      : d.target.x > d.source.x + 4;

    // Hinge point X
    const hx1 = (d: RenderLink): number => {
      if (orientation === 'vertical') return isForward(d) ? d.source.x : d.source.x - NODE_W / 2;
      return isForward(d) ? d.source.x + NODE_W / 2 : d.source.x;
    };
    const hy1 = (d: RenderLink): number => {
      if (orientation === 'vertical') return isForward(d) ? d.source.y + NODE_H / 2 : d.source.y;
      return isForward(d) ? d.source.y : d.source.y - NODE_H / 2;
    };
    const hx2 = (d: RenderLink): number => {
      if (orientation === 'vertical') return isForward(d) ? d.target.x : d.target.x - NODE_W / 2;
      return isForward(d) ? d.target.x - NODE_W / 2 : d.target.x;
    };
    const hy2 = (d: RenderLink): number => {
      if (orientation === 'vertical') return isForward(d) ? d.target.y - NODE_H / 2 : d.target.y;
      return isForward(d) ? d.target.y : d.target.y - NODE_H / 2;
    };

    // SVG path string for an edge
    const pathD = (d: RenderLink): string => {
      const x1 = hx1(d), y1 = hy1(d), x2 = hx2(d), y2 = hy2(d);
      if (isForward(d)) {
        return `M${x1},${y1} L${x2},${y2}`;
      }
      if (orientation === 'vertical') {
        return `M${x1},${y1} C${RETURN_ARC_OFFSET},${y1} ${RETURN_ARC_OFFSET},${y2} ${x2},${y2}`;
      }
      return `M${x1},${y1} C${x1},${RETURN_ARC_OFFSET} ${x2},${RETURN_ARC_OFFSET} ${x2},${y2}`;
    };

    // Midpoint of edge path (used to place labels and step badges)
    const midX = (d: RenderLink): number => {
      if (!isForward(d) && orientation === 'vertical') {
        return (hx1(d) + hx2(d) + 6 * RETURN_ARC_OFFSET) / 8;
      }
      return (hx1(d) + hx2(d)) / 2;
    };
    const midY = (d: RenderLink): number => {
      if (isForward(d)) return (hy1(d) + hy2(d)) / 2;
      if (orientation === 'vertical') return (hy1(d) + hy2(d)) / 2;
      return (hy1(d) + hy2(d) + 6 * RETURN_ARC_OFFSET) / 8;
    };

    // ── Entry / exit detection ────────────────────────────────────────────────
    const hasIncoming = new Set(renderGraphData.edges.map(e => e.target));
    const hasOutgoing = new Set(renderGraphData.edges.map(e => e.source));
    const sourceNodeIds = new Set(renderGraphData.nodes.filter(n => !hasIncoming.has(n.id)).map(n => n.id));
    const sinkNodeIds   = new Set(renderGraphData.nodes.filter(n => !hasOutgoing.has(n.id)).map(n => n.id));

    // ── Groups layer (rendered behind edges and nodes) ─────────────────────────
    const groupsLayer = g.append('g').attr('class', 'groups-layer');
    const groupLabelsLayer = g.append('g').attr('class', 'group-labels-layer');
    const groups = (renderGraphData.groups ?? []) as GraphGroup[];
    const groupStyleByNodeId = new Map<string, { label: string; color: string }>();
    groups.forEach((group, index) => {
      const color = GROUP_PALETTE[index % GROUP_PALETTE.length].label;
      group.nodeIds.forEach(nodeId => groupStyleByNodeId.set(nodeId, { label: group.label, color }));
    });
    const groupEls = groups.map((grp, idx) => {
      const gc = GROUP_PALETTE[idx % GROUP_PALETTE.length];
      const grpEl = groupsLayer.append('g').attr('class', 'group-box');
      const rect  = grpEl.append('rect')
        .attr('rx', 14)
        .attr('fill', gc.fill)
        .attr('stroke', gc.stroke)
        .attr('stroke-width', 1.2)
        .attr('stroke-dasharray', '7,5');
      const labelBackground = groupLabelsLayer.append('rect')
        .attr('rx', 5)
        .attr('fill', '#0a101b')
        .attr('stroke', gc.stroke)
        .attr('stroke-width', 0.8);
      const labelText = groupLabelsLayer.append('text')
        .text(grp.label.length > 28 ? `${grp.label.slice(0, 27)}…` : grp.label)
        .attr('font-size', '0.58rem')
        .attr('font-weight', 700)
        .attr('letter-spacing', '0.035em')
        .attr('fill', gc.label)
        .attr('opacity', 0.92)
        .style('pointer-events', 'none');
      return { grp, grpEl, rect, labelBackground, labelText };
    });

    // ── Edge layer ────────────────────────────────────────────────────────────
    const linkGroup = g.append('g');

    // Visible edge path.
    // Feedback paths remain faintly visible in overview; detailed labels appear
    // only on hover so dense diagrams do not become a wall of text.
    const link = linkGroup.selectAll('path.edge-vis')
      .data(links).enter().append('path')
      .attr('class', 'edge-vis')
      .attr('fill', 'none')
      .attr('stroke', (d: RenderLink) => {
        if (d.flow === 'feedback') return 'rgba(167,139,250,0.7)';
        if (d.flow === 'control') return 'rgba(148,163,184,0.52)';
        if (d.flow === 'deployment') return 'rgba(148,163,184,0.5)';
        return isForward(d) ? 'rgba(59,130,246,0.55)' : 'rgba(167,139,250,0.35)';
      })
      .attr('stroke-width', 1.7)
      .attr('stroke-dasharray', (d: RenderLink) => {
        if (d.flow === 'feedback') return '5,4';
        if (d.flow === 'control' || d.flow === 'deployment') return '3,4';
        return d.sync === 'async' ? '6,4' : 'none';
      })
      .attr('marker-end', (d: RenderLink) => (d.edgeType === 'loop' || !isForward(d)) ? 'url(#arrow-ret)' : 'url(#arrow-fwd)')
      .attr('opacity', (d: RenderLink) => d.edgeType === 'loop' ? 0.42 : 0);

    // Wide invisible hit area for easier hover targeting
    const linkHit = linkGroup.selectAll('path.edge-hit')
      .data(links).enter().append('path')
      .attr('class', 'edge-hit')
      .attr('fill', 'none')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 14)
      .attr('opacity', 0)
      .style('cursor', 'crosshair')
      .on('mouseover', function(ev: MouseEvent, d: RenderLink) {
        const idx = links.indexOf(d);
        d3.select((linkGroup.selectAll('path.edge-vis').nodes() as Element[])[idx])
          .attr('stroke', 'rgba(167,139,250,0.7)')
          .attr('stroke-width', 2);
        const labelGrpNode = (linkGroup.selectAll('g.edge-label').nodes() as Element[])[idx];
        d3.select(labelGrpNode).attr('opacity', 1);
        d3.select(labelGrpNode).select('text').attr('fill', '#c9d1d9');
        d3.select(labelGrpNode).select('rect').attr('opacity', 1);
        const svgRect = svgRef.current!.getBoundingClientRect();
        setEdgeTooltip({
          x: ev.clientX - svgRect.left,
          y: ev.clientY - svgRect.top,
          label:       d.label || '',
          technology:  d.technology || '',
          sync:        d.sync || 'sync',
          description: d.description || '',
        });
      })
      .on('mouseout', function(_ev: MouseEvent, d: RenderLink) {
        const idx = links.indexOf(d);
        d3.select((linkGroup.selectAll('path.edge-vis').nodes() as Element[])[idx])
          .attr('stroke', d.flow === 'feedback' || !isForward(d)
            ? 'rgba(167,139,250,0.35)'
            : d.flow === 'control'
              ? 'rgba(148,163,184,0.52)'
              : d.flow === 'deployment'
                ? 'rgba(148,163,184,0.5)'
                : 'rgba(59,130,246,0.55)')
          .attr('stroke-width', 1.7);
        const labelGrpNode = (linkGroup.selectAll('g.edge-label').nodes() as Element[])[idx];
        d3.select(labelGrpNode).attr(
          'opacity',
          overviewEdgeLabelOpacity({ flow: d.flow, type: d.edgeType }, d.overviewRequired),
        );
        d3.select(labelGrpNode).select('text').attr('fill', '#7d8590');
        d3.select(labelGrpNode).select('rect').attr('opacity', 0.9);
        setEdgeTooltip(null);
      });

    // Edge action label (verb phrase) — sits slightly above the edge midpoint
    const edgeLabelGroup = linkGroup.selectAll('g.edge-label')
      .data(links).enter().append('g')
      .attr('class', 'edge-label')
      .attr('data-overview-required', (d: RenderLink) => (
        d.overviewRequired
          ? 'true'
          : null
      ));
    edgeLabelGroup.attr('opacity', (d: RenderLink) => (
      overviewEdgeLabelOpacity({ flow: d.flow, type: d.edgeType }, d.overviewRequired)
    ));

    edgeLabelGroup.append('rect')
      .attr('rx', 5).attr('fill', '#090f19').attr('opacity', 0.96)
      .attr('stroke', 'rgba(148,163,184,0.09)');

    edgeLabelGroup.append('text')
      .text((d: RenderLink) => truncateEdgeLabel(d.label))
      .attr('font-size', '0.59rem')
      .attr('font-weight', 520)
      .attr('fill', '#8f9baa')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .style('pointer-events', 'none');

    // ── Node groups ───────────────────────────────────────────────────────────
    const nodeGroup = g.append('g');

    const nodeSel = nodeGroup.selectAll<SVGGElement, RenderNode>('g.node')
      .data(nodes).enter().append('g')
      .attr('class', 'node')
      .attr('role', 'button')
      .attr('tabindex', 0)
      .attr('aria-label', (d: RenderNode) => `Explore ${d.label}`)
      .attr('data-grouped', (d: RenderNode) => groupStyleByNodeId.has(d.id) ? 'true' : null)
      .attr('opacity', 0)
      .style('cursor', 'pointer')
      .call(
        // Drag: move node, re-render all edges (no simulation needed)
        d3.drag<SVGGElement, RenderNode>()
          .on('start', function() { d3.select(this).raise(); })
          .on('drag', (event, d) => {
            d.x = event.x;
            d.y = event.y;
            renderAll();
          })
          .on('end', () => {
            const currentTransform = d3.zoomTransform(svgRef.current!);
            emitViewState(nodes, currentTransform);
          })
      )
      .on('click', (_event: MouseEvent, d: RenderNode) => onNodeClickRef.current(d))
      .on('keydown', (event: KeyboardEvent, d: RenderNode) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        onNodeClickRef.current(d);
      })
      .on('mouseover', function(_ev: MouseEvent, d: RenderNode) {
        d3.select(this).select('.node-card')
          .attr('stroke-width', 2)
          .style('filter', 'brightness(1.14)');
        const incidentIndices = incidentIndicesByNode.get(d.id) ?? [];
        if (incidentIndices.length > 0) {
          const edgeVisNodes  = linkGroup.selectAll('path.edge-vis').nodes() as Element[];
          const edgeHitNodes  = linkGroup.selectAll('path.edge-hit').nodes() as Element[];
          const edgeLblNodes  = linkGroup.selectAll('g.edge-label').nodes() as Element[];
          incidentIndices.forEach(i => {
            const edgeSelection = d3.select(edgeVisNodes[i]);
            const labelSelection = d3.select(edgeLblNodes[i]);
            edgeSelection.attr('data-hover-restore-opacity', edgeSelection.attr('opacity') || '1');
            labelSelection.attr('data-hover-restore-opacity', labelSelection.attr('opacity') || '0');
            edgeSelection.interrupt().transition().duration(150).attr('opacity', 1);
            d3.select(edgeHitNodes[i]).attr('opacity', 1).style('pointer-events', 'auto');
            labelSelection.interrupt().transition().duration(150).attr('opacity', 1);
          });
        }
      })
      .on('mouseout', function(_ev: MouseEvent, d: RenderNode) {
        d3.select(this).select('.node-card')
          .attr('stroke-width', 1.35)
          .style('filter', null);
        const incidentIndices = incidentIndicesByNode.get(d.id) ?? [];
        if (incidentIndices.length > 0) {
          const edgeVisNodes  = linkGroup.selectAll('path.edge-vis').nodes() as Element[];
          const edgeHitNodes  = linkGroup.selectAll('path.edge-hit').nodes() as Element[];
          const edgeLblNodes  = linkGroup.selectAll('g.edge-label').nodes() as Element[];
          incidentIndices.forEach(i => {
            const edgeSelection = d3.select(edgeVisNodes[i]);
            const labelSelection = d3.select(edgeLblNodes[i]);
            const edgeOpacity = Number(edgeSelection.attr('data-hover-restore-opacity') || 1);
            const labelOpacity = Number(labelSelection.attr('data-hover-restore-opacity') || 0);
            edgeSelection.interrupt().transition().duration(200).attr('opacity', edgeOpacity);
            d3.select(edgeHitNodes[i]).attr('opacity', 1).style('pointer-events', 'auto');
            labelSelection.interrupt().transition().duration(200).attr('opacity', labelOpacity);
          });
        }
      });

    nodeSel.append('title')
      .text((d: RenderNode) => d.technology ? `${d.label} — ${d.technology}` : d.label);

    // Card background
    nodeSel.filter((d: RenderNode) => d.type !== 'decision')
      .append('rect')
      .attr('class', 'node-card')
      .attr('width', NODE_W).attr('height', NODE_H)
      .attr('x', -NODE_W / 2).attr('y', -NODE_H / 2)
      .attr('rx', NODE_RX).attr('ry', NODE_RX)
      .attr('fill',   (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).fill)
      .attr('stroke', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke)
      .attr('stroke-width', 1.35)
      .attr('filter', 'url(#architecture-card-shadow)');

    nodeSel.filter((d: RenderNode) => d.type === 'decision')
      .append('path')
      .attr('class', 'node-card')
      .attr('d', [
        `M 0 ${-NODE_H / 2}`,
        `L ${NODE_W / 2} 0`,
        `L 0 ${NODE_H / 2}`,
        `L ${-NODE_W / 2} 0`,
        'Z',
      ].join(' '))
      .attr('fill',   (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).fill)
      .attr('stroke', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke)
      .attr('stroke-width', 1.35)
      .attr('filter', 'url(#architecture-card-shadow)');

    // Left accent stripe
    nodeSel.filter((d: RenderNode) => d.type !== 'decision')
      .append('rect')
      .attr('x', -NODE_W / 2).attr('y', -NODE_H / 2 + NODE_RX)
      .attr('width', 3).attr('height', NODE_H - NODE_RX * 2)
      .attr('fill', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke);

    // Loading shimmer bar (visible while node detail is not yet enriched)
    nodeSel.append('rect')
      .attr('class', 'node-detail-shimmer')
      .attr('width', NODE_W - 32).attr('height', 2)
      .attr('x', -(NODE_W - 32) / 2).attr('y', NODE_H / 2 - 5)
      .attr('rx', 1)
      .attr('fill', 'rgba(167,139,250,0.3)')
      .attr('opacity', (d: RenderNode) => d.detail || d.design_origin === 'applied' ? 0 : 0.7);

    // Row 1 — type badge (top-left)
    nodeSel.filter(() => renderGraphData.design_origin !== 'applied').append('text')
      .text((d: RenderNode) => d.type.toUpperCase())
      .attr('x', -NODE_W / 2 + 12).attr('y', -NODE_H / 2 + 11)
      .attr('font-size', '0.44rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.07em')
      .attr('fill', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).badge)
      .style('pointer-events', 'none');

    // Row 1 — tier badge (top-right: PUB / PVT)
    nodeSel.filter((d: RenderNode) => Boolean(d.tier) && renderGraphData.design_origin !== 'applied')
      .append('text')
      .text((d: RenderNode) => d.tier === 'public' ? 'PUB' : 'PVT')
      .attr('x', NODE_W / 2 - 8).attr('y', -NODE_H / 2 + 11)
      .attr('text-anchor', 'end')
      .attr('font-size', '0.42rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.06em')
      .attr('fill', (d: RenderNode) => d.tier === 'public' ? '#fbbf24' : '#6e7681')
      .style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => groupStyleByNodeId.has(d.id))
      .append('circle')
      .attr('cx', -NODE_W / 2 + 12)
      .attr('cy', -NODE_H / 2 + 12)
      .attr('r', 2.5)
      .attr('fill', (d: RenderNode) => groupStyleByNodeId.get(d.id)?.color ?? '#94a3b8')
      .attr('opacity', 0.9)
      .style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => groupStyleByNodeId.has(d.id))
      .append('text')
      .attr('class', 'node-group-label')
      .text((d: RenderNode) => truncateGroupLabel(groupStyleByNodeId.get(d.id)?.label ?? ''))
      .attr('x', -NODE_W / 2 + 19)
      .attr('y', -NODE_H / 2 + 14)
      .attr('font-size', '0.43rem')
      .attr('font-weight', 700)
      .attr('letter-spacing', '0.045em')
      .attr('fill', (d: RenderNode) => groupStyleByNodeId.get(d.id)?.color ?? '#94a3b8')
      .style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => (
      renderGraphData.design_origin === 'applied'
      && (sourceNodeIds.has(d.id) || sinkNodeIds.has(d.id))
    ))
      .append('text')
      .text((d: RenderNode) => sourceNodeIds.has(d.id) ? 'ENTRY' : 'OUTCOME')
      .attr('x', NODE_W / 2 - 9)
      .attr('y', -NODE_H / 2 + 14)
      .attr('text-anchor', 'end')
      .attr('font-size', '0.39rem')
      .attr('font-weight', 750)
      .attr('letter-spacing', '0.07em')
      .attr('fill', (d: RenderNode) => sourceNodeIds.has(d.id) ? '#60a5fa' : '#34d399')
      .style('pointer-events', 'none');

    // Row 2 — node label (centered, white, main title). Long domain labels
    // wrap instead of losing their distinguishing words to truncation.
    const nodeTitles = nodeSel.append('text')
      .attr('class', 'node-title')
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
      .attr('font-size', '0.9rem').attr('font-weight', 640)
      .attr('fill', '#e6edf3')
      .style('pointer-events', 'none');

    nodeTitles.each(function(d: RenderNode) {
      const lines = wrapNodeLabel(d.label);
      const startY = lines.length === 1 ? 2 : -5;
      d3.select(this).selectAll('tspan')
        .data(lines)
        .enter()
        .append('tspan')
        .attr('x', 0)
        .attr('y', (_line: string, index: number) => startY + index * 13)
        .text((line: string) => line);
    });

    // Row 3 — deployable capability for applied architectures. Canonical book
    // concept metadata is provenance, not a user-facing system component.
    nodeSel.filter((d: RenderNode) => Boolean(d.technology) && d.design_origin === 'applied')
      .append('text')
      .attr('class', 'node-technology')
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
      .attr('font-size', '0.54rem')
      .attr('fill', '#7d8795')
      .style('pointer-events', 'none')
      .each(function(d: RenderNode) {
        const lines = wrapNodeTechnology(d.technology || '');
        const startY = lines.length === 1 ? 24 : 20;
        d3.select(this).selectAll('tspan')
          .data(lines)
          .enter()
          .append('tspan')
          .attr('x', 0)
          .attr('y', (_line: string, index: number) => startY + index * 10)
          .text((line: string) => line);
      });

    // ── Entry / Exit markers ──────────────────────────────────────────────────
    const MARKER_W = 12, MARKER_H = 8, MARKER_GAP = 6;

    // ENTRY — blue right-pointing triangle on left edge
    nodeSel.filter((d: RenderNode) => sourceNodeIds.has(d.id) && renderGraphData.design_origin !== 'applied')
      .append('polygon')
      .attr('points', [
        `${-NODE_W / 2 - MARKER_GAP - MARKER_W},${-MARKER_H / 2}`,
        `${-NODE_W / 2 - MARKER_GAP},0`,
        `${-NODE_W / 2 - MARKER_GAP - MARKER_W},${MARKER_H / 2}`,
      ].join(' '))
      .attr('fill', '#60a5fa').attr('opacity', 0.85).style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => sourceNodeIds.has(d.id) && renderGraphData.design_origin !== 'applied')
      .append('text').text('ENTRY')
      .attr('x', -NODE_W / 2 - MARKER_GAP - MARKER_W / 2)
      .attr('y', -MARKER_H / 2 - 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '0.38rem').attr('font-weight', 700).attr('letter-spacing', '0.1em')
      .attr('fill', '#60a5fa').attr('opacity', 0.9).style('pointer-events', 'none');

    // EXIT — slate right-pointing triangle on right edge
    nodeSel.filter((d: RenderNode) => sinkNodeIds.has(d.id) && renderGraphData.design_origin !== 'applied')
      .append('polygon')
      .attr('points', [
        `${NODE_W / 2 + MARKER_GAP},${-MARKER_H / 2}`,
        `${NODE_W / 2 + MARKER_GAP + MARKER_W},0`,
        `${NODE_W / 2 + MARKER_GAP},${MARKER_H / 2}`,
      ].join(' '))
      .attr('fill', '#94a3b8').attr('opacity', 0.85).style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => sinkNodeIds.has(d.id) && renderGraphData.design_origin !== 'applied')
      .append('text').text('EXIT')
      .attr('x', NODE_W / 2 + MARKER_GAP + MARKER_W / 2)
      .attr('y', -MARKER_H / 2 - 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '0.38rem').attr('font-weight', 700).attr('letter-spacing', '0.1em')
      .attr('fill', '#94a3b8').attr('opacity', 0.9).style('pointer-events', 'none');

    // ── Step number badges ────────────────────────────────────────────────────
    // Render badges in a dedicated overlay layer above nodes so they remain
    // visible when an edge midpoint passes through a card body.
    const stepBadgeLayer = g.append('g').attr('class', 'step-badge-layer');
    const stepBadgeGroup = stepBadgeLayer.selectAll('g.step-badge')
      .data(links).enter().append('g').attr('class', 'step-badge');
    stepBadgeGroup.attr('opacity', 0);

    stepBadgeGroup.filter((d: RenderLink) => d.stepNum !== null).append('circle')
      .attr('r', 10.5)
      .attr('fill', '#101827')
      .attr('stroke', 'rgba(167,139,250,0.78)')
      .attr('stroke-width', 1.4);

    stepBadgeGroup.filter((d: RenderLink) => d.stepNum !== null).append('text')
      .text((d: RenderLink) => String(d.stepNum))
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('font-size', '0.54rem')
      .attr('font-weight', 700)
      .attr('fill', '#a78bfa')
      .style('pointer-events', 'none');

    // ── renderAll: position everything from current node.x/y ─────────────────
    // Called once on init, and on every drag tick.
    function renderAll() {
      // Update edge paths
      link.attr('d', pathD);
      linkHit.attr('d', pathD);

      // Position nodes
      nodeSel.attr('transform', (d: RenderNode) => `translate(${d.x},${d.y})`);

      // Position step badges at exact edge midpoint
      stepBadgeGroup.attr('transform', (d: RenderLink) => `translate(${midX(d)},${midY(d)})`);

      // Refit group boundaries to their member nodes. Some valid topologies
      // interleave responsibility zones; overlapping rectangles imply false
      // containment, so those diagrams fall back to per-zone eyebrow chips.
      const groupLayouts = groupEls.map((groupEl) => {
        const { grp: groupDef } = groupEl;
        const memberNodes = groupDef.nodeIds
          .map(id => nodeById[id])
          .filter((n): n is RenderNode => n?.x != null && n?.y != null);
        const PX = 16, PT = 8, PB = 4;
        const minX = Math.min(...memberNodes.map((n: RenderNode) => n.x)) - NODE_W / 2 - PX;
        const maxX = Math.max(...memberNodes.map((n: RenderNode) => n.x)) + NODE_W / 2 + PX;
        const minY = Math.min(...memberNodes.map((n: RenderNode) => n.y)) - NODE_H / 2 - PT;
        const maxY = Math.max(...memberNodes.map((n: RenderNode) => n.y)) + NODE_H / 2 + PB;
        return {
          ...groupEl,
          memberNodes,
          bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
        };
      }).filter(layout => layout.memberNodes.length > 0);

      const boundaryLayouts = groupLayouts.filter(layout => (
        layout.memberNodes.length > 1
        && layout.bounds.width <= NODE_W * 3.4
        && layout.bounds.height <= NODE_H * 4.2
      ));
      const overlappingBoundaryIds = new Set<string>();
      boundaryLayouts.forEach((left, leftIndex) => {
        boundaryLayouts.slice(leftIndex + 1).forEach((right) => {
          if (!boxesIntersect(left.bounds, right.bounds)) return;
          overlappingBoundaryIds.add(left.grp.id);
          overlappingBoundaryIds.add(right.grp.id);
        });
      });

      for (const {
        grp: groupDef,
        rect,
        labelBackground,
        labelText,
        memberNodes,
        bounds,
      } of groupLayouts) {
        const useBoundary = boundaryLayouts.some(layout => layout.grp.id === groupDef.id)
          && !overlappingBoundaryIds.has(groupDef.id);

        rect
          .attr('display', useBoundary ? null : 'none')
          .attr('x', bounds.x).attr('y', bounds.y)
          .attr('width', bounds.width).attr('height', bounds.height);
        const labelWidth = Math.min(
          NODE_W - 20,
          Math.max(74, Math.min(groupDef.label.length, 28) * 5.6 + 20),
        );
        const labelX = useBoundary ? bounds.x + 10 : memberNodes[0].x - NODE_W / 2 + 8;
        const labelY = useBoundary ? bounds.y + 3 : memberNodes[0].y - NODE_H / 2 + 4;
        labelBackground
          .attr('x', labelX)
          .attr('y', labelY)
          .attr('width', labelWidth)
          .attr('height', 15);
        labelText.attr('x', labelX + 8).attr('y', labelY + 11);
      }

      groupLabelsLayer.raise();

      const occupiedBoxes = nodes.map((node: RenderNode) => ({
        x: node.x - NODE_W / 2 - 14,
        y: node.y - NODE_H / 2 - 14,
        width: NODE_W + 28,
        height: NODE_H + 28,
      }));
      const placedLabels: Array<{ x: number; y: number; width: number; height: number }> = [];

      edgeLabelGroup.each(function(d: RenderLink) {
        const grp = d3.select(this);
        const textEl = grp.select('text').node() as SVGTextElement | null;
        if (!textEl) return;

        const textBox = textEl.getBBox();
        grp.select('rect')
          .attr('x', textBox.x - 3)
          .attr('y', textBox.y - 1)
          .attr('width', textBox.width + 6)
          .attr('height', textBox.height + 2);

        const labelWidth = textBox.width + 6;
        const labelHeight = textBox.height + 2;
        const verticalForward = orientation === 'vertical' && isForward(d);
        const centerX = midX(d);
        const centerY = midY(d);
        const baseY = verticalForward
          ? centerY
          : centerY - (d.stepNum !== null ? 20 : isForward(d) ? 12 : 20);
        const sideOffset = NODE_W / 2 + labelWidth / 2 + 14;
        const preferredSide = centerX < width / 2 ? -1 : 1;
        const candidates = verticalForward
          ? Array.from({ length: 7 }, (_, distanceIndex) => (
              [preferredSide, -preferredSide].map(side => ({
                x: centerX + side * sideOffset,
                y: baseY + (distanceIndex === 0
                  ? 0
                  : (distanceIndex % 2 === 1 ? -1 : 1) * Math.ceil(distanceIndex / 2) * 14),
              }))
            )).flat()
          : Array.from({ length: 13 }, (_, attempt) => ({
              x: centerX,
              y: baseY + (attempt === 0
                ? 0
                : (attempt % 2 === 1 ? -1 : 1)
                  * (14 + Math.floor((attempt - 1) / 2) * (isForward(d) ? 6 : 7))),
            }));
        let placement = candidates.at(-1) ?? { x: centerX, y: baseY };

        for (const candidatePosition of candidates) {
          const candidate = {
            x: candidatePosition.x - labelWidth / 2,
            y: candidatePosition.y - labelHeight / 2,
            width: labelWidth,
            height: labelHeight,
          };
          const collides = occupiedBoxes.some((box) => boxesIntersect(candidate, box))
            || placedLabels.some((box) => boxesIntersect(candidate, box));
          if (!collides) {
            placedLabels.push(candidate);
            placement = candidatePosition;
            break;
          }
        }

        grp.attr('transform', `translate(${placement.x},${placement.y})`);
      });
    }

    // Initial render — static layout, no animation delay
    renderAll();

    // ── Auto-fit: zoom to show the full diagram on first render ───────────────
    // Scale down to fit (never scale up — max 1.0), centre horizontally,
    // add a small top margin so return arcs (which arc above y=0) are visible.
    const fitScale = initialFitScale(width, height, layoutW, layoutH);
    // Clamp fitTx so the leftmost node is never off-screen.
    // When height is the limiting dimension, (width - layoutW*fitScale)/2 can go
    // negative, sliding the entire graph behind the left edge of the container.
    const fitTx = Math.max(INITIAL_FIT_PADDING, (width  - layoutW * fitScale) / 2);
    const fitTy = Math.max(INITIAL_FIT_PADDING, (height - layoutH * fitScale) / 2);
    const initialTransform = restoreViewState?.viewport
      ? d3.zoomIdentity
          .translate(restoreViewState.viewport.x, restoreViewState.viewport.y)
          .scale(restoreViewState.viewport.k)
      : d3.zoomIdentity.translate(fitTx, fitTy).scale(fitScale);
    svg.call(zoomBehavior.transform, initialTransform);

    renderStateRef.current = {
      nodeSel,
      link,
      linkHit,
      edgeLabelGroup,
      stepBadgeGroup,
      nodeFirstStep,
      sequenceLength: sequence.length,
      isForward,
    };

    return () => {
      renderStateRef.current = null;
    };
  }, [structureKey, viewportRevision]);

  useEffect(() => {
    const renderState = renderStateRef.current;
    if (!renderState || !graphData) return;

    const detailById = new Map(graphData.nodes.map(node => [
      node.id,
      Boolean(node.detail) || node.design_origin === 'applied',
    ]));
    renderState.nodeSel
      .select<SVGRectElement>('rect.node-detail-shimmer')
      .interrupt()
      .transition()
      .duration(180)
      .attr('opacity', (d: RenderNode) => detailById.get(d.id) ? 0 : 0.7);
  }, [detailKey, graphData]);

  useEffect(() => {
    const renderState = renderStateRef.current;
    if (!renderState) return;

    const {
      nodeSel,
      link,
      linkHit,
      edgeLabelGroup,
      stepBadgeGroup,
      nodeFirstStep,
      sequenceLength,
      isForward,
    } = renderState;

    const activeStepNumber = currentStep + 1;
    const showAll = currentStep < 0 || sequenceLength === 0;

    nodeSel
      .interrupt()
      .transition()
      .duration(220)
      .attr('opacity', (d: RenderNode) => {
        if (showAll) return 1;
        const firstStep = nodeFirstStep.get(d.id) ?? 1;
        if (firstStep > activeStepNumber) return 0;
        if (activeNodeIds.has(d.id)) return 1;
        return 0.38;
      });

    // Loop edges are hover-controlled — exclude them from sequence animation entirely.
    link.filter((d: RenderLink) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: RenderLink) => {
        if (showAll) return 1;
        if (d.stepNum === null) return 0.22;
        if (d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0.34;
      })
      .attr('stroke-width', (d: RenderLink) => (
        !showAll && d.stepNum === activeStepNumber ? 2.3 : 1.5
      ))
      .attr('stroke', (d: RenderLink) => {
        if (!showAll && d.stepNum === activeStepNumber) {
          return isForward(d) ? '#8bb5ff' : 'rgba(167,139,250,0.92)';
        }
        if (d.flow === 'control') return 'rgba(148,163,184,0.52)';
        if (d.flow === 'deployment') return 'rgba(148,163,184,0.5)';
        return isForward(d) ? 'rgba(59,130,246,0.55)' : 'rgba(167,139,250,0.35)';
      });

    linkHit.filter((d: RenderLink) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: RenderLink) => {
        if (showAll) return 1;
        if (d.stepNum === null) return 0.22;
        return d.stepNum > activeStepNumber ? 0 : 1;
      });

    edgeLabelGroup.filter((d: RenderLink) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: RenderLink) => {
        if (showAll) {
          return overviewEdgeLabelOpacity(
            { flow: d.flow, type: d.edgeType },
            d.overviewRequired,
          );
        }
        if (d.stepNum === null) return 0.28;
        if (d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0;
      });

    stepBadgeGroup
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: RenderLink) => {
        if (showAll) return 0;
        if (d.stepNum === null || d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0;
      });
  // ResizeObserver rebuilds the SVG selections. Reapply the current reveal
  // state to those new elements even when the sequence itself did not change.
  }, [activeNodeIds, currentStep, structureKey, viewportRevision]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* overflow:visible allows return-edge arcs to arc above the SVG viewport */}
      <svg
        ref={svgRef}
        data-testid="graph-canvas"
        aria-label="Architecture graph"
        style={{ width: '100%', height: '100%', background: '#080d14', overflow: 'visible' }}
      />

      {/* Edge hover tooltip */}
      {edgeTooltip && (
        <div style={{
          position: 'absolute',
          left: edgeTooltip.x + 14,
          top:  edgeTooltip.y - 16,
          background: 'rgba(10,14,26,0.97)',
          border: '1px solid rgba(167,139,250,0.3)',
          borderRadius: 6,
          padding: '0.45rem 0.65rem',
          fontSize: '0.7rem',
          pointerEvents: 'none',
          zIndex: 30,
          maxWidth: 250,
          backdropFilter: 'blur(8px)',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
          lineHeight: 1.5,
        }}>
          <div style={{ marginBottom: 3, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            {edgeTooltip.technology && (
              <span style={{ color: '#a78bfa', fontWeight: 700, fontSize: '0.66rem', letterSpacing: '0.05em' }}>
                {edgeTooltip.technology.toUpperCase()}
              </span>
            )}
            <span style={{
              fontSize: '0.52rem', fontWeight: 600, padding: '0 4px', borderRadius: 2,
              background: edgeTooltip.sync === 'async' ? 'rgba(251,191,36,0.15)' : 'rgba(52,211,153,0.15)',
              color: edgeTooltip.sync === 'async' ? '#fbbf24' : '#34d399',
              letterSpacing: '0.06em',
            }}>
              {edgeTooltip.sync === 'async' ? 'ASYNC' : 'SYNC'}
            </span>
          </div>
          <div style={{ color: '#e6edf3', fontWeight: 500 }}>{edgeTooltip.label}</div>
          {edgeTooltip.description && (
            <div style={{ marginTop: 4, color: '#6e7681', fontSize: '0.66rem' }}>
              {edgeTooltip.description}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function truncateEdgeLabel(label: string): string {
  if (!label) return '';
  return label.length > EDGE_LABEL_MAX_CHARS
    ? `${label.slice(0, EDGE_LABEL_MAX_CHARS - 1)}…`
    : label;
}

function truncateGroupLabel(label: string): string {
  return label.length > 18 ? `${label.slice(0, 17)}…` : label;
}

function boxesIntersect(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean {
  return !(
    a.x + a.width < b.x
    || b.x + b.width < a.x
    || a.y + a.height < b.y
    || b.y + b.height < a.y
  );
}
