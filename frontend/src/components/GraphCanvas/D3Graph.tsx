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
import type { GraphData, GraphEdge, GraphNode, GraphViewState } from '../../types';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { TYPE_STYLE, FALLBACK_STYLE } from '../../utils/graphColors';
import { architectureRegions, regionRole } from './architectureRegions';
import './D3Graph.css';
import { diagramConnections, overviewConnections, routeConnection, type DiagramConnection } from './diagramConnections';
import { snapBounds, resizeCenteredZone, zoneFrame, type Box, type AlignmentGuide } from './diagramAlignment';
import {
  boundLabelCenter,
  BOTTOM_NODE_GAP,
  COMPACT_NODE_GAP,
  COMPACT_NODE_PITCH,
  DIAGRAM_EVALUATION_VIEWPORT,
  filterRenderableEdges,
  GRAPH_LAYOUT_VERSION,
  H_PAD,
  INITIAL_FIT_PADDING,
  initialFitScale,
  labelAxisCandidates,
  MIN_COL_W,
  MIN_PUBLISHED_TITLE_PX,
  NODE_H,
  NODE_TITLE_PX,
  NODE_RX,
  NODE_W,
  overviewEdgeLabelOpacity,
  planCompactLayout,
  planVerticalLayout,
  selectGraphLayout,
  selectOverviewEdgeIndices,
  VERTICAL_LEVEL_H,
  VERTICAL_NODE_GAP,
  VERTICAL_PAD,
  VERTICAL_TRACK_GAP,
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

const MAX_PARALLEL_LANE_OFFSET = 18;

function parallelLaneOffset(index: number, count: number): number {
  if (count <= 1) return 0;
  return MAX_PARALLEL_LANE_OFFSET * (2 * index / (count - 1) - 1);
}

// ── Topological column assignment ────────────────────────────────────────────
// Use longest-path ranks on directed layout edges. When a cycle has no entry,
// break it at the earliest remaining component in the declared node order.
// Result: a Map<nodeId, columnIndex> where col 0 = leftmost entry node.
function assignColumns(
  nodeIds: string[],
  edges: GraphEdge[],
): Map<string, number> {
  // Declared feedback is a return path, not part of the primary runtime DAG.
  const outgoing = new Map(nodeIds.map(id => [id, new Set<string>()]));
  const inDegree = new Map(nodeIds.map(id => [id, 0]));
  for (const edge of edges) {
    if (edge.flow === 'feedback' || edge.type === 'loop') continue;
    const targets = outgoing.get(edge.source);
    if (!targets || !inDegree.has(edge.target) || targets.has(edge.target)) continue;
    targets.add(edge.target);
    inDegree.set(edge.target, inDegree.get(edge.target)! + 1);
  }

  const cols = new Map(nodeIds.map(id => [id, 0]));
  const remaining = new Set(nodeIds);
  while (remaining.size > 0) {
    const id = nodeIds.find(nodeId => remaining.has(nodeId) && inDegree.get(nodeId) === 0)
      ?? nodeIds.find(nodeId => remaining.has(nodeId))!;
    remaining.delete(id);
    for (const target of outgoing.get(id) ?? []) {
      if (!remaining.has(target)) continue;
      cols.set(target, Math.max(cols.get(target)!, cols.get(id)! + 1));
      inDegree.set(target, inDegree.get(target)! - 1);
    }
  }
  return cols;
}

// ── Edge tooltip data ────────────────────────────────────────────────────────
interface EdgeTooltip {
  x: number; y: number;
  label: string; technology: string; sync: string; description: string;
  count?: number;
}

interface D3GraphProps {
  graphData: GraphData;
  currentStep: number;
  activeNodeIds: Set<string>;
  onNodeClick: (node: GraphNode) => void;
  onNodeEdit?: (node: GraphNode) => void;
  onEditConnection?: (edgeIndex: number) => void;
  initialViewState?: GraphViewState;
  onViewStateChange?: (state: GraphViewState) => void;
  onLayoutReady?: (structureKey: string) => void;
  minimumTitlePx?: number;
  navigation?: boolean;
  inspectionViewport?: { nodeId: string; width: number; height: number };
}

type RenderNode = GraphNode & {
  x: number;
  y: number;
  topologyRank: number;
  track: number;
  trackDirection: 1 | -1;
  trackX: number;
  trackWidth: number;
  compactRow: number;
  compactColumn: number;
};

type RenderLink = {
  connection: DiagramConnection;
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
  parallelIndex: number;
  parallelCount: number;
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
  viewport: () => d3.ZoomTransform;
  setTransientViewport: (transform: d3.ZoomTransform) => void;
  focusWalkthroughNodes: (nodeIds: Set<string>) => void;
  focusInspectionNode: (nodeId: string, safeWidth: number, safeHeight: number) => void;
}

interface WalkthroughCamera {
  key: string;
  active: boolean;
  userIntervened: boolean;
  baseline: d3.ZoomTransform | null;
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
  onNodeEdit,
  onEditConnection,
  initialViewState,
  onViewStateChange,
  onLayoutReady,
  minimumTitlePx = MIN_PUBLISHED_TITLE_PX,
  navigation = false,
  inspectionViewport,
}: D3GraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const navigateRef = useRef<(action: 'in' | 'out' | 'fit' | 'read') => void>(() => undefined);
  const renderStateRef = useRef<GraphRenderState | null>(null);
  const walkthroughCameraRef = useRef<WalkthroughCamera | null>(null);
  const inspectionCameraRef = useRef<{ key: string; nodeId: string; userIntervened: boolean } | null>(null);
  const onNodeClickRef = useRef(onNodeClick);
  const onNodeEditRef = useRef(onNodeEdit);
  const onViewStateChangeRef = useRef(onViewStateChange);
  const onLayoutReadyRef = useRef(onLayoutReady);
  const graphDataRef = useRef(graphData);
  const initialViewStateRef = useRef(initialViewState);
  const latestViewStateRef = useRef<{ key: string; state: GraphViewState } | null>(null);
  const previousViewportRef = useRef<{ key: string; width: number; height: number } | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const [viewportRevision, setViewportRevision] = useState(0);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const connectionCloseRef = useRef<HTMLButtonElement>(null);
  const [showConnections, setShowConnections] = useState(false);
  const structureKey = graphStructureKey(graphData);
  const inspectedNodeId = inspectionViewport?.nodeId ?? null;
  const inspectionWidth = inspectionViewport?.width ?? 0;
  const inspectionHeight = inspectionViewport?.height ?? 0;
  const selectedConnection = selectedConnectionId
    ? diagramConnections(graphData.edges).find(connection => connection.id === selectedConnectionId)
    : undefined;
  const nodeLabel = (id: string) => graphData.nodes.find(node => node.id === id)?.label ?? id;
  const closeConnection = () => {
    const sourceId = selectedConnection?.edge.source;
    setSelectedConnectionId(null);
    renderStateRef.current?.nodeSel.filter(node => node.id === sourceId).node()?.focus();
  };
  const detailKey = graphData
    ? graphData.nodes.map(node => `${node.id}:${node.detail || node.design_origin === 'applied' ? '1' : '0'}`).join('|')
    : 'null';

  useEffect(() => {
    if (selectedConnectionId) connectionCloseRef.current?.focus();
  }, [selectedConnectionId]);

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
    onNodeEditRef.current = onNodeEdit;
    renderStateRef.current?.nodeSel.attr('aria-description', onNodeEdit
      ? 'Double-click or press F2 to edit.'
      : null);
  }, [onNodeEdit, structureKey, viewportRevision]);

  useEffect(() => {
    onViewStateChangeRef.current = onViewStateChange;
  }, [onViewStateChange]);

  useEffect(() => {
    onLayoutReadyRef.current = onLayoutReady;
  }, [onLayoutReady]);

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
    if (walkthroughCameraRef.current?.key !== structureKey) {
      walkthroughCameraRef.current = { key: structureKey, active: false, userIntervened: false, baseline: null };
    }
    setEdgeTooltip(null);

    const svg = d3.select(svgRef.current);
    let dragView: Window | null = null;
    let pendingNodeClick: ReturnType<typeof setTimeout> | null = null;
    const clearPendingNodeClick = () => {
      if (pendingNodeClick !== null) window.clearTimeout(pendingNodeClick);
      pendingNodeClick = null;
    };
    const trackDrag = (event: { sourceEvent: MouseEvent | TouchEvent }) => {
      if ('view' in event.sourceEvent) dragView = event.sourceEvent.view;
    };
    const stopCameraFollow = () => {
      const camera = walkthroughCameraRef.current;
      if (camera && (camera.active || inspectionCameraRef.current)) camera.userIntervened = true;
      if (inspectionCameraRef.current) inspectionCameraRef.current.userIntervened = true;
    };
    svg.attr('data-rendered-graph-version', null);
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

    defs.append('marker').attr('id', 'arrow-both')
      .attr('viewBox', '0 -5 10 10').attr('refX', 8).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto-start-reverse')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#8aa4cd');

    svg.append('rect')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('fill', 'url(#architecture-grid)')
      .style('pointer-events', 'none');

    // ── Pan + zoom container ──────────────────────────────────────────────────
    // Store the zoom behaviour so we can set the initial fit transform later.
    const g = svg.append('g');
    const zonePadding: NonNullable<GraphViewState['zonePadding']> = {};
    const emitViewState = (nodesToPersist: RenderNode[], transform: d3.ZoomTransform) => {
      const state: GraphViewState = {
        layoutVersion: GRAPH_LAYOUT_VERSION,
        zonePadding: structuredClone(zonePadding),
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
      };
      latestViewStateRef.current = { key: structureKey, state };
      onViewStateChangeRef.current?.(state);
    };
    let applyingTransientCamera = false;
    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 3])
      .on('start', (event) => {
        if (event.sourceEvent) stopCameraFollow();
      })
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      })
      .on('end', (event) => {
        if (applyingTransientCamera) return;
        const camera = walkthroughCameraRef.current;
        if (camera?.active) camera.baseline = event.transform;
        emitViewState(nodes, event.transform);
      });
    svg.call(zoomBehavior);

    // ── Deep-copy nodes (D3 may mutate x/y) ──────────────────────────────────
    const nodes: RenderNode[] = renderGraphData.nodes.map(n => ({
      ...n,
      x: 0,
      y: 0,
      topologyRank: 0,
      track: 0,
      trackDirection: 1,
      trackX: 0,
      trackWidth: 0,
      compactRow: 0,
      compactColumn: 0,
    }));
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
    const savedView = latestViewStateRef.current?.key === structureKey
      ? latestViewStateRef.current.state : renderInitialViewState;
    const restoreViewState = savedView?.layoutVersion === GRAPH_LAYOUT_VERSION ? savedView : undefined;
    const colWidth = MIN_COL_W;

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

    const groups = navigation && renderGraphData.design_origin === 'applied'
      ? architectureRegions(nodes, renderGraphData.groups ?? [])
      : renderGraphData.groups ?? [];
    for (const group of groups) {
      const saved = restoreViewState?.zonePadding?.[group.id];
      if (saved && ['top', 'right', 'bottom', 'left'].every(side => {
        const value = saved[side as keyof typeof saved];
        return Number.isFinite(value) && value >= 0 && value <= 10000;
      })) zonePadding[group.id] = { ...saved };
    }
    const groupRank = new Map<string, number>();
    groups.forEach((group, index) => {
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
    const MIN_ROW_H     = NODE_H + 64;   // slightly looser spacing without blowing out the layout

    const totalMainSlots = Math.max(
      1,
      ...Array.from(colBuckets.values(), bucket => bucket.filter(node => node.lane !== 'bottom').length),
    );
    const maximumBottomNodesInColumn = Math.max(
      0,
      ...Array.from(colBuckets.values(), bucket => bucket.filter(node => node.lane === 'bottom').length),
    );
    const bottomBandHeight = maximumBottomNodesInColumn === 0
      ? 0
      : maximumBottomNodesInColumn * NODE_H
        + (maximumBottomNodesInColumn - 1) * BOTTOM_NODE_GAP;
    // Group boundaries decorate topology; they must not reserve empty rows.
    const effectiveMainH = totalMainSlots * MIN_ROW_H;
    const horizontalLayoutW = numCols * colWidth + 2 * H_PAD;
    const horizontalLayoutH = V_PAD + effectiveMainH + bottomBandHeight + V_PAD;
    const horizontalCollisionFree = colWidth >= NODE_W
      && effectiveMainH / totalMainSlots >= NODE_H;

    // Choose wrapping and virtual width together so wide levels can use both
    // viewport dimensions without forcing every level into the same narrow row.
    const verticalPlan = planVerticalLayout(
      width,
      height,
      sortedColumns.map(columnIndex => colBuckets.get(columnIndex)?.length ?? 0),
    );
    const verticalLayoutW = verticalPlan.layoutWidth;
    const verticalPlacementByColumn = new Map(
      sortedColumns.map((columnIndex, index) => [columnIndex, verticalPlan.levels[index]]),
    );
    const compactOrderedNodes = sortedColumns.flatMap(
      columnIndex => colBuckets.get(columnIndex) ?? [],
    );
    const compactBottomNodes = compactOrderedNodes.filter(node => node.lane === 'bottom');
    const compactMainNodes = compactOrderedNodes.filter(node => node.lane !== 'bottom');
    const compactPlan = planCompactLayout(
      width,
      height,
      nodes.length,
      compactBottomNodes.length,
    );
    // Keep ordinary flow direction stable when the conversation narrows the pane.
    // The live camera supports panning; the evaluation canvas still fits the graph.
    const orientation = navigation ? 'horizontal' : selectGraphLayout(
      horizontalCollisionFree
        ? initialFitScale(
          Math.max(width, DIAGRAM_EVALUATION_VIEWPORT.width),
          height,
          horizontalLayoutW, horizontalLayoutH,
        )
        : 0,
      verticalPlan.scale,
      minimumTitlePx,
    );
    const compactIndexByNodeId = new Map(
      [
        ...compactMainNodes.map((node, index) => [node.id, index] as const),
        ...compactBottomNodes.map((node, index) => (
          [node.id, compactPlan.bottomStartIndex + index] as const
        )),
      ],
    );

    for (const [c, bucket] of colBuckets) {
      bucket.forEach((node: RenderNode) => {
        node.topologyRank = c;
      });
      if (orientation === 'compact') {
        bucket.forEach((node: RenderNode) => {
          const compactIndex = compactIndexByNodeId.get(node.id) ?? 0;
          node.x = H_PAD + NODE_W / 2
            + (compactIndex % compactPlan.columns) * (NODE_W + COMPACT_NODE_GAP);
          node.y = V_PAD + NODE_H / 2
            + Math.floor(compactIndex / compactPlan.columns) * COMPACT_NODE_PITCH;
          node.track = 0;
          node.trackDirection = 1;
          node.trackX = H_PAD;
          node.trackWidth = compactPlan.layoutWidth - 2 * H_PAD;
          node.compactRow = Math.floor(compactIndex / compactPlan.columns);
          node.compactColumn = compactIndex % compactPlan.columns;
        });
        continue;
      }
      if (orientation === 'vertical') {
        const placement = verticalPlacementByColumn.get(c);
        if (!placement) continue;
        bucket.forEach((node: RenderNode, index: number) => {
          const wrappedRow = Math.floor(index / verticalPlan.nodesPerRow);
          const indexInRow = index % verticalPlan.nodesPerRow;
          const rowStart = wrappedRow * verticalPlan.nodesPerRow;
          const nodesInRow = Math.min(
            verticalPlan.nodesPerRow,
            bucket.length - rowStart,
          );
          const rowWidth = nodesInRow * NODE_W + (nodesInRow - 1) * VERTICAL_NODE_GAP;
          node.x = placement.x + (placement.width - rowWidth) / 2
            + NODE_W / 2
            + indexInRow * (NODE_W + VERTICAL_NODE_GAP);
          node.y = placement.y
            + (wrappedRow + 0.5) * VERTICAL_LEVEL_H;
          node.track = placement.track;
          node.trackDirection = placement.direction;
          node.trackX = placement.x;
          node.trackWidth = placement.width;
        });
        continue;
      }

      const x = H_PAD + (c + 0.5) * colWidth;
      const mainNodes = bucket.filter((node: RenderNode) => node.lane !== 'bottom');
      const bottomNodes = bucket.filter((node: RenderNode) => node.lane === 'bottom');

      mainNodes.forEach((node: RenderNode, index: number) => {
        node.x = x;
        node.y = V_PAD + effectiveMainH / 2
          + (index - (mainNodes.length - 1) / 2) * MIN_ROW_H;
      });

      bottomNodes.forEach((node: RenderNode, index: number) => {
        node.x = x;
        node.y = V_PAD + effectiveMainH + NODE_H / 2
          + index * (NODE_H + BOTTOM_NODE_GAP);
      });
    }

    let groupedLayoutHeight = horizontalLayoutH;
    let groupedLayoutWidth = horizontalLayoutW;
    if (navigation && groupRank.size > 0) {
      const roles = { client: 0, service: 1, datastore: 2, external: 3, support: 4 };
      const regions = [...new Set(nodes.map(node => groupRank.get(node.id) ?? -1))].map(rank => {
        const members = nodes.filter(node => (groupRank.get(node.id) ?? -1) === rank);
        return { members, role: regionRole(members), rank };
      }).sort((a, b) => roles[a.role] - roles[b.role] || a.rank - b.rank);
      const externalRows = Math.max(0, ...regions.filter(region => region.role === 'external').map(region => region.members.length));
      const mainY = V_PAD + (externalRows ? externalRows * MIN_ROW_H + 64 : 0);
      let mainX = H_PAD;
      let mainBottom = mainY;
      let supportX = H_PAD;
      let externalX = H_PAD;
      const place = (members: RenderNode[], x: number, y: number, stack = false) => {
        const ranks = [...new Set(members.map(node => node.topologyRank))].sort((a, b) => a - b);
        const rows = new Map<number, number>();
        members.forEach((node, index) => {
          // Component previews have no edges yet. Spread them horizontally.
          const column = stack ? 0 : renderGraphData.edges.length === 0 ? index : ranks.indexOf(node.topologyRank);
          const row = rows.get(column) ?? 0;
          node.x = x + NODE_W / 2 + column * colWidth;
          node.y = y + NODE_H / 2 + row * MIN_ROW_H;
          rows.set(column, row + 1);
        });
        return {
          right: Math.max(...members.map(node => node.x)) + NODE_W / 2 + 80,
          bottom: Math.max(...members.map(node => node.y)) + NODE_H / 2 + 84,
        };
      };
      for (const region of regions.filter(region => region.role !== 'external' && region.role !== 'support')) {
        if (region.role === 'service' && supportX === H_PAD) supportX = mainX;
        const bounds = place(region.members, mainX, mainY, region.role === 'client' || region.role === 'datastore');
        mainX = bounds.right;
        mainBottom = Math.max(mainBottom, bounds.bottom);
      }
      externalX = Math.max(H_PAD, mainX - colWidth);
      let bottom = mainBottom;
      for (const region of regions.filter(region => region.role === 'external' || region.role === 'support')) {
        const external = region.role === 'external';
        const bounds = place(region.members, external ? externalX : supportX, external ? V_PAD : mainBottom);
        if (external) externalX = bounds.right;
        else supportX = bounds.right;
        bottom = Math.max(bottom, bounds.bottom);
      }
      groupedLayoutWidth = Math.max(mainX, externalX, supportX) + H_PAD;
      groupedLayoutHeight = bottom + V_PAD;
    }

    for (const node of nodes) {
      const persistedPosition = restoreViewState?.nodePositions[node.id];
      if (!persistedPosition) continue;
      node.x = persistedPosition.x;
      node.y = persistedPosition.y;
    }

    const membersOf = (group: typeof groups[number]) => [...new Set(group.nodeIds)]
      .map(id => nodeById[id]).filter((node): node is RenderNode => Boolean(node));
    const contentBounds = (members: RenderNode[]): Box => {
      const x = Math.min(...members.map(node => node.x)) - NODE_W / 2;
      const y = Math.min(...members.map(node => node.y)) - NODE_H / 2;
      return { x, y, width: Math.max(...members.map(node => node.x)) + NODE_W / 2 - x,
        height: Math.max(...members.map(node => node.y)) + NODE_H / 2 - y };
    };
    const boundsOf = (group: typeof groups[number]): Box => zoneFrame(contentBounds(membersOf(group)),
      zonePadding[group.id] ?? { top: 0, right: 0, bottom: 0, left: 0 });
    const centerMembers = (group: typeof groups[number]) => {
      const members = membersOf(group);
      if (!members.length) return;
      const centered = resizeCenteredZone(boundsOf(group), contentBounds(members), '', 0, 0);
      for (const node of members) { node.x += centered.contentOffset.x; node.y += centered.contentOffset.y; }
      zonePadding[group.id] = centered.padding;
    };
    // Older saved frames can have all their spare space on one side.
    // Keep those frame boundaries while restoring centered contents.
    if (navigation) for (const group of groups) {
      const padding = zonePadding[group.id];
      if (padding && (padding.left !== padding.right || padding.top !== padding.bottom)) centerMembers(group);
    }

    // Total layout dimensions (used for auto-fit zoom below)
    const layoutW = orientation === 'vertical'
      ? verticalLayoutW
      : orientation === 'compact'
        ? compactPlan.layoutWidth
        : groupedLayoutWidth;
    const layoutH = orientation === 'vertical'
      ? verticalPlan.layoutHeight
      : orientation === 'compact'
        ? compactPlan.layoutHeight
        : groupedLayoutHeight;

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
    const connections = navigation ? diagramConnections(renderableEdges) : renderableEdges.map((edge, i) => ({
      id: String(i), edge, members: [edge], bidirectional: false,
    }));
    const overviewIds = navigation ? overviewConnections(connections, nodes) : new Set<string>();
    const parallelCounts = new Map<string, number>();
    for (const edge of renderableEdges) {
      const key = `${edge.source}\u0000${edge.target}`;
      parallelCounts.set(key, (parallelCounts.get(key) ?? 0) + 1);
    }
    const parallelOffsets = new Map<string, number>();
    const links = connections.map((connection, edgeIndex) => {
      const e = connection.edge;
      let stepNum: number | null = null;
      for (const step of sequence) {
        if ((step.nodes ?? []).includes(e.target)) { stepNum = step.step; break; }
      }
      const src = nodeById[e.source]!;
      const tgt = nodeById[e.target]!;
      const parallelKey = `${e.source}\u0000${e.target}`;
      const parallelIndex = parallelOffsets.get(parallelKey) ?? 0;
      parallelOffsets.set(parallelKey, parallelIndex + 1);
      return {
        connection,
        source:      src,
        target:      tgt,
        label:       e.label,
        technology:  e.technology ?? '',
        sync:        e.sync ?? 'sync',
        description: e.description ?? '',
        stepNum,
        edgeType:    (e.type ?? 'normal') as 'normal' | 'loop',
        flow:        e.flow ?? (e.type === 'loop' ? 'feedback' : 'runtime'),
        overviewRequired: navigation ? overviewIds.has(connection.id) : overviewEdgeIndices.has(edgeIndex),
        parallelIndex,
        parallelCount: parallelCounts.get(parallelKey) ?? 1,
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

    // ── Edge routes ───────────────────────────────────────────────────────────
    // Semantic rank decides direction. Wrapped and skip routes use the gaps
    // between node rows and tracks, so they cannot cut through an unrelated card.

    const isForward = (d: RenderLink): boolean => {
      if (d.flow === 'feedback' || d.edgeType === 'loop') return false;
      return orientation === 'vertical' || orientation === 'compact'
        ? d.target.topologyRank > d.source.topologyRank
        : d.target.x > d.source.x + 4;
    };
    interface EdgeRoute {
      path: string;
      anchorX: number;
      anchorY: number;
    }

    const cardBorderPoint = (
      from: RenderNode,
      toward: RenderNode,
    ): { x: number; y: number } => {
      const dx = toward.x - from.x;
      const dy = toward.y - from.y;
      if (dx === 0 && dy === 0) return { x: from.x, y: from.y };
      const distanceToBorder = 1 / Math.max(
        Math.abs(dx) / (NODE_W / 2),
        Math.abs(dy) / (NODE_H / 2),
      );
      return {
        x: from.x + dx * distanceToBorder,
        y: from.y + dy * distanceToBorder,
      };
    };

    const computeRouteLink = (d: RenderLink): EdgeRoute => {
      if (navigation) return routeConnection(d.source, d.target, nodes, NODE_W, NODE_H);
      const laneOffset = parallelLaneOffset(d.parallelIndex, d.parallelCount);
      if (orientation === 'horizontal') {
        const forward = isForward(d);
        const blocked = navigation && nodes.some(node => node !== d.source && node !== d.target
          && node.x > Math.min(d.source.x, d.target.x) && node.x < Math.max(d.source.x, d.target.x)
          && node.y + NODE_H / 2 > Math.min(d.source.y, d.target.y)
          && node.y - NODE_H / 2 < Math.max(d.source.y, d.target.y) + 1);
        const adjacent = Math.abs(d.target.topologyRank - d.source.topologyRank) === 1;
        const hasReverse = links.some(other => other.source.id === d.target.id && other.target.id === d.source.id
          && other.flow !== 'feedback' && other.edgeType !== 'loop');
        if (!blocked && adjacent && hasReverse && d.flow !== 'feedback' && d.edgeType !== 'loop') {
          const direction = forward ? 1 : -1;
          const offset = (forward ? -14 : 14) + laneOffset / 3;
          const y1 = d.source.y + offset;
          const y2 = d.target.y + offset;
          const x1 = d.source.x + direction * NODE_W / 2;
          const x2 = d.target.x - direction * NODE_W / 2;
          return { path: `M${x1},${y1} L${x2},${y2}`, anchorX: (x1 + x2) / 2, anchorY: (y1 + y2) / 2 };
        }
        if (forward) {
          const x1 = d.source.x + NODE_W / 2;
          const y1 = d.source.y;
          const x2 = d.target.x - NODE_W / 2;
          const y2 = d.target.y;
          if (
            d.target.topologyRank === d.source.topologyRank + 1
            && d.parallelCount === 1
            && !blocked
          ) {
            return {
              path: `M${x1},${y1} L${x2},${y2}`,
              anchorX: (x1 + x2) / 2,
              anchorY: (y1 + y2) / 2,
            };
          }
          if (blocked || d.target.topologyRank > d.source.topologyRank + 1) {
            const sourceGutterX = d.source.x + colWidth / 2 + laneOffset;
            const targetGutterX = d.target.x - colWidth / 2 + laneOffset;
            const corridorY = V_PAD / 2 + laneOffset / 2;
            return {
              path: [
                `M${x1},${y1}`,
                `L${sourceGutterX},${y1}`,
                `L${sourceGutterX},${corridorY}`,
                `L${targetGutterX},${corridorY}`,
                `L${targetGutterX},${y2}`,
                `L${x2},${y2}`,
              ].join(' '),
              anchorX: (sourceGutterX + targetGutterX) / 2,
              anchorY: corridorY,
            };
          }
          const centerX = (x1 + x2) / 2;
          return {
            path: `M${x1},${y1} C${centerX},${y1 + laneOffset} ${centerX},${y2 + laneOffset} ${x2},${y2}`,
            anchorX: centerX,
            anchorY: (y1 + y2) / 2 + 0.75 * laneOffset,
          };
        }
        const sameColumn = d.source.topologyRank === d.target.topologyRank;
        const sourceIsRight = d.source.x > d.target.x;
        const sourceDirection = sameColumn || sourceIsRight ? -1 : 1;
        const targetDirection = sameColumn ? -1 : sourceIsRight ? 1 : -1;
        const sourceBorderX = d.source.x + sourceDirection * NODE_W / 2;
        const targetBorderX = d.target.x + targetDirection * NODE_W / 2;
        const sourceGutterX = sameColumn
          ? H_PAD / 2 + laneOffset
          : d.source.x + sourceDirection * colWidth / 2 + laneOffset;
        const targetGutterX = sameColumn
          ? H_PAD / 2 + laneOffset
          : d.target.x + targetDirection * colWidth / 2 + laneOffset;
        const returnY = navigation && (regionRole([d.source]) === 'support' || regionRole([d.target]) === 'support')
          ? layoutH - V_PAD / 2 + laneOffset / 2
          : V_PAD / 2 + laneOffset / 2;
        return {
          path: [
            `M${sourceBorderX},${d.source.y}`,
            `L${sourceGutterX},${d.source.y}`,
            `L${sourceGutterX},${returnY}`,
            `L${targetGutterX},${returnY}`,
            `L${targetGutterX},${d.target.y}`,
            `L${targetBorderX},${d.target.y}`,
          ].join(' '),
          anchorX: (sourceGutterX + targetGutterX) / 2,
          anchorY: returnY,
        };
      }

      if (orientation === 'compact') {
        const sameRow = d.source.compactRow === d.target.compactRow;
        const adjacent = Math.abs(d.source.compactRow - d.target.compactRow)
          + Math.abs(d.source.compactColumn - d.target.compactColumn) === 1;
        const sourceBorder = cardBorderPoint(d.source, d.target);
        const targetBorder = cardBorderPoint(d.target, d.source);
        if (adjacent && d.parallelCount === 1) {
          return {
            path: `M${sourceBorder.x},${sourceBorder.y} L${targetBorder.x},${targetBorder.y}`,
            anchorX: (sourceBorder.x + targetBorder.x) / 2,
            anchorY: (sourceBorder.y + targetBorder.y) / 2,
          };
        }

        const compactLaneOffset = parallelLaneOffset(d.parallelIndex, d.parallelCount) / 6;
        const rowGutterY = (row: number, below: boolean): number => {
          if (below) {
            if (row < compactPlan.rows - 1) {
              return V_PAD + NODE_H + row * COMPACT_NODE_PITCH + COMPACT_NODE_GAP / 4;
            }
            return compactPlan.layoutHeight - V_PAD / 2;
          }
          if (row > 0) {
            return V_PAD + (row - 1) * COMPACT_NODE_PITCH + NODE_H + COMPACT_NODE_GAP / 4;
          }
          return V_PAD / 2;
        };
        const sourceBelow = sameRow
          ? d.source.compactRow < compactPlan.rows - 1
          : d.target.compactRow > d.source.compactRow;
        const targetBelow = sameRow
          ? sourceBelow
          : d.source.compactRow > d.target.compactRow;
        const sourceBorderY = d.source.y + (sourceBelow ? NODE_H / 2 : -NODE_H / 2);
        const targetBorderY = d.target.y + (targetBelow ? NODE_H / 2 : -NODE_H / 2);
        const sourceLaneY = rowGutterY(d.source.compactRow, sourceBelow) + compactLaneOffset;
        const targetLaneY = rowGutterY(d.target.compactRow, targetBelow) + compactLaneOffset;

        if (sameRow) {
          return {
            path: [
              `M${d.source.x},${sourceBorderY}`,
              `L${d.source.x},${sourceLaneY}`,
              `L${d.target.x},${targetLaneY}`,
              `L${d.target.x},${targetBorderY}`,
            ].join(' '),
            anchorX: (d.source.x + d.target.x) / 2,
            anchorY: sourceLaneY,
          };
        }

        const routeRight = d.target.compactColumn >= d.source.compactColumn;
        const outerGutterX = routeRight
          ? compactPlan.layoutWidth - H_PAD / 2
          : H_PAD / 2;
        return {
          path: [
            `M${d.source.x},${sourceBorderY}`,
            `L${d.source.x},${sourceLaneY}`,
            `L${outerGutterX},${sourceLaneY}`,
            `L${outerGutterX},${targetLaneY}`,
            `L${d.target.x},${targetLaneY}`,
            `L${d.target.x},${targetBorderY}`,
          ].join(' '),
          anchorX: outerGutterX,
          anchorY: (sourceLaneY + targetLaneY) / 2,
        };
      }

      if (!isForward(d)) {
        const returnX = RETURN_ARC_OFFSET + laneOffset;
        const sourceLaneY = d.source.y - NODE_H / 2 - 6;
        const targetLaneY = d.target.y - NODE_H / 2 - 6;
        return {
          path: [
            `M${d.source.x},${d.source.y - NODE_H / 2}`,
            `L${d.source.x},${sourceLaneY}`,
            `L${returnX},${sourceLaneY}`,
            `L${returnX},${targetLaneY}`,
            `L${d.target.x},${targetLaneY}`,
            `L${d.target.x},${d.target.y - NODE_H / 2}`,
          ].join(' '),
          anchorX: returnX,
          anchorY: (sourceLaneY + targetLaneY) / 2,
        };
      }

      const sourceDirection = d.source.trackDirection;
      const targetDirection = d.target.trackDirection;
      const sourceBorderY = d.source.y + sourceDirection * NODE_H / 2;
      const targetBorderY = d.target.y - targetDirection * NODE_H / 2;
      const sourceLaneY = sourceBorderY + sourceDirection * 6;
      const targetLaneY = targetBorderY - targetDirection * 6;
      if (d.source.track === d.target.track) {
        // Adjacent unwrapped rows share a clear gutter. Routing to the outer
        // track edge here draws a horizontal spur that retraces itself.
        if (
          d.target.topologyRank === d.source.topologyRank + 1
          && sourceDirection === targetDirection
          && sourceLaneY === targetLaneY
          && d.parallelCount === 1
        ) {
          return {
            path: [
              `M${d.source.x},${sourceBorderY}`,
              `L${d.source.x},${sourceLaneY}`,
              `L${d.target.x},${targetLaneY}`,
              `L${d.target.x},${targetBorderY}`,
            ].join(' '),
            anchorX: (d.source.x + d.target.x) / 2,
            anchorY: sourceLaneY,
          };
        }
        const gutterX = Math.min(
          layoutW - VERTICAL_PAD / 2,
          d.source.trackX + d.source.trackWidth + VERTICAL_TRACK_GAP / 2 + laneOffset,
        );
        return {
          path: [
            `M${d.source.x},${sourceBorderY}`,
            `L${d.source.x},${sourceLaneY}`,
            `L${gutterX},${sourceLaneY}`,
            `L${gutterX},${targetLaneY}`,
            `L${d.target.x},${targetLaneY}`,
            `L${d.target.x},${targetBorderY}`,
          ].join(' '),
          anchorX: gutterX,
          anchorY: (sourceLaneY + targetLaneY) / 2,
        };
      }

      const sourceGutterX = Math.min(
        layoutW - VERTICAL_PAD / 2,
        d.source.trackX + d.source.trackWidth + VERTICAL_TRACK_GAP / 2 + laneOffset,
      );
      const targetGutterX = Math.max(
        VERTICAL_PAD / 2,
        d.target.trackX - VERTICAL_TRACK_GAP / 2 + laneOffset,
      );
      const corridorY = sourceDirection === 1
        ? layoutH - VERTICAL_PAD / 2 + laneOffset / 2
        : VERTICAL_PAD / 2 - laneOffset / 2;
      return {
        path: [
          `M${d.source.x},${sourceBorderY}`,
          `L${d.source.x},${sourceLaneY}`,
          `L${sourceGutterX},${sourceLaneY}`,
          `L${sourceGutterX},${corridorY}`,
          `L${targetGutterX},${corridorY}`,
          `L${targetGutterX},${targetLaneY}`,
          `L${d.target.x},${targetLaneY}`,
          `L${d.target.x},${targetBorderY}`,
        ].join(' '),
        anchorX: (sourceGutterX + targetGutterX) / 2,
        anchorY: corridorY,
      };
    };

    const routeCache = new Map<RenderLink, EdgeRoute>();
    const routeLink = (d: RenderLink): EdgeRoute => {
      if (!routeCache.has(d)) routeCache.set(d, computeRouteLink(d));
      return routeCache.get(d)!;
    };
    const pathD = (d: RenderLink): string => routeLink(d).path;
    const midX = (d: RenderLink): number => routeLink(d).anchorX;
    const midY = (d: RenderLink): number => routeLink(d).anchorY;

    // ── Entry / exit detection ────────────────────────────────────────────────
    // Feedback and deployment routes must not erase the product entry/outcome
    // markers on an otherwise closed operational loop.
    const runtimeEdges = renderGraphData.edges.filter(
      edge => (edge.flow ?? (edge.type === 'loop' ? 'feedback' : 'runtime')) === 'runtime',
    );
    const hasIncoming = new Set(runtimeEdges.map(e => e.target));
    const hasOutgoing = new Set(runtimeEdges.map(e => e.source));
    const isolatedSingleton = renderGraphData.nodes.length === 1 && renderGraphData.edges.length === 0;
    const sourceNodeIds = new Set(renderGraphData.nodes.filter(
      n => !hasIncoming.has(n.id) && (hasOutgoing.has(n.id) || isolatedSingleton),
    ).map(n => n.id));
    const sinkNodeIds = new Set(renderGraphData.nodes.filter(
      n => !hasOutgoing.has(n.id) && hasIncoming.has(n.id),
    ).map(n => n.id));

    // ── Groups layer (rendered behind edges and nodes) ─────────────────────────
    const groupsLayer = g.append('g').attr('class', 'groups-layer');
    const guidesLayer = g.append('g').attr('class', 'alignment-guides').attr('aria-hidden', 'true').style('pointer-events', 'none');
    const showGuides = (guides: AlignmentGuide[]) => {
      guidesLayer.selectAll('line').data(guides).join('line')
        .attr('x1', guide => guide.axis === 'x' ? guide.position : guide.start)
        .attr('x2', guide => guide.axis === 'x' ? guide.position : guide.end)
        .attr('y1', guide => guide.axis === 'y' ? guide.position : guide.start)
        .attr('y2', guide => guide.axis === 'y' ? guide.position : guide.end)
        .attr('stroke', '#c4b5fd').attr('stroke-width', 1)
        .attr('stroke-dasharray', '4 3').attr('vector-effect', 'non-scaling-stroke');
      guidesLayer.raise();
    };
    const snapThreshold = () => 6 / d3.zoomTransform(svgRef.current!).k;
    const groupLabelsLayer = g.append('g').attr('class', 'group-labels-layer');
    const groupStyleByNodeId = new Map<string, { label: string; color: string }>();
    groups.forEach((group, index) => {
      const color = GROUP_PALETTE[index % GROUP_PALETTE.length].label;
      group.nodeIds.forEach(nodeId => groupStyleByNodeId.set(nodeId, { label: group.label, color }));
    });
    const groupEls = groups.map((grp, idx) => {
      const gc = GROUP_PALETTE[idx % GROUP_PALETTE.length];
      const grpEl = groupsLayer.append('g').attr('class', 'group-box').attr('data-group-id', grp.id);
      const rect  = grpEl.append('rect')
        .attr('rx', 14)
        .attr('fill', navigation ? `${gc.label}18` : gc.fill)
        .attr('stroke', gc.stroke)
        .attr('stroke-width', 1.2)
        .attr('stroke-dasharray', navigation ? 'none' : '7,5');
      const labelBackground = groupLabelsLayer.append('rect')
        .attr('rx', 5)
        .attr('fill', '#0a101b')
        .attr('stroke', gc.stroke)
        .attr('stroke-width', 0.8);
      const labelText = groupLabelsLayer.append('text')
        .text(navigation ? grp.label : grp.label.length > 28 ? `${grp.label.slice(0, 27)}…` : grp.label)
        .attr('font-size', navigation ? '0.9rem' : '0.58rem')
        .attr('font-weight', 700)
        .attr('letter-spacing', '0.035em')
        .attr('fill', gc.label)
        .attr('opacity', 0.92)
        .style('pointer-events', 'none');
      const handles = grpEl.append('g').selectAll<SVGRectElement, string>('.zone-resize')
        .data(navigation ? ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] : [])
        .enter().append('rect').attr('class', 'zone-resize')
        .attr('data-side', side => side)
        .attr('fill', 'transparent')
        .attr('stroke', 'transparent').attr('stroke-width', 8).attr('vector-effect', 'non-scaling-stroke')
        .style('cursor', side => `${side}-resize`)
        .attr('tabindex', -1).attr('role', 'button')
        .attr('aria-label', side => `Resize ${grp.label} ${ ({ n: 'top', s: 'bottom', e: 'right', w: 'left', ne: 'top right', nw: 'top left', se: 'bottom right', sw: 'bottom left' } as Record<string, string>)[side]} border`)
        .attr('aria-description', 'Drag or use arrow keys. Hold Shift for larger steps.');
      return { grp, grpEl, rect, labelBackground, labelText, handles };
    });

    if (navigation) {
      let activeZoneId: string | null = null;
      const activateZone = (id: string | null) => {
        activeZoneId = id;
        groupEls.forEach(({ grp, rect, handles }) => {
          const active = grp.id === id;
          handles.attr('tabindex', active ? 0 : -1);
          rect.style('cursor', active ? 'grab' : '')
            .attr('stroke-width', active ? 2 : 1.2)
            .attr('aria-pressed', String(active));
        });
      };
      groupEls.forEach(({ grp, rect, handles }) => {
        const members = membersOf(grp);
        if (!members.length) return;
        const otherFrames = () => groups.filter(group => group.id !== grp.id && membersOf(group).length).map(boundsOf);
        const snapshot = () => ({ frame: boundsOf(grp), content: contentBounds(members),
          positions: members.map(node => ({ node, x: node.x, y: node.y })) });
        const resize = (start: ReturnType<typeof snapshot>, side: string, dx: number, dy: number, snap = false) => {
          let result = resizeCenteredZone(start.frame, start.content, side, dx, dy);
          let guides: AlignmentGuide[] = [];
          if (snap) {
            const match = snapBounds(result.frame, otherFrames(), snapThreshold(), {
              x: side.includes('w') ? [0] : side.includes('e') ? [1] : [],
              y: side.includes('n') ? [0] : side.includes('s') ? [1] : [],
            });
            const adjusted = resizeCenteredZone(start.frame, start.content, side, dx + match.dx, dy + match.dy);
            // A minimum-size clamp may prevent a proposed snap.
            guides = match.guides.filter(guide => guide.axis === 'x'
              ? Math.abs(adjusted.frame.x + (side.includes('e') ? adjusted.frame.width : 0) - guide.position) < 0.01
              : Math.abs(adjusted.frame.y + (side.includes('s') ? adjusted.frame.height : 0) - guide.position) < 0.01);
            result = adjusted;
          }
          for (const position of start.positions) {
            position.node.x = position.x + result.contentOffset.x;
            position.node.y = position.y + result.contentOffset.y;
          }
          zonePadding[grp.id] = result.padding;
          renderAll();
          showGuides(guides);
        };
        let resizeStart: ReturnType<typeof snapshot>;
        let resizePointer = { x: 0, y: 0 };
        handles.on('focus', function() { d3.select(this).attr('fill', 'rgba(167,139,250,0.4)'); })
          .on('blur', function() { d3.select(this).attr('fill', 'transparent'); })
          .on('mouseenter', function() { d3.select(this).attr('fill', 'rgba(167,139,250,0.25)'); })
          .on('mouseleave', function() { if (document.activeElement !== this) d3.select(this).attr('fill', 'transparent'); })
          .on('dblclick', event => { event.preventDefault(); event.stopPropagation(); })
          .on('keydown', (event: KeyboardEvent, side) => {
            if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            event.stopPropagation();
            stopCameraFollow();
            const step = event.shiftKey ? 10 : 1;
            resize(snapshot(), side, event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0,
              event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0);
            emitViewState(nodes, d3.zoomTransform(svgRef.current!));
          })
          .call(d3.drag<SVGRectElement, string>().container(() => g.node()!)
            .on('start', event => { trackDrag(event); activateZone(grp.id); resizeStart = snapshot(); resizePointer = { x: event.x, y: event.y }; })
            .on('drag', (event, side) => {
              stopCameraFollow();
              resize(resizeStart, side, event.x - resizePointer.x, event.y - resizePointer.y, !event.sourceEvent.altKey);
            })
            .on('end', () => { dragView = null; showGuides([]); emitViewState(nodes, d3.zoomTransform(svgRef.current!)); }));
        let moveStart: ReturnType<typeof snapshot>;
        let movePointer = { x: 0, y: 0 };
        rect.attr('tabindex', 0)
          .attr('role', 'button')
          .attr('aria-label', `Move ${grp.label} zone`)
          .attr('aria-description', 'Double-click or press Enter to move this zone. Arrow keys nudge; Shift moves faster. Tab to resize borders. Escape exits.')
          .attr('aria-pressed', 'false')
          .on('dblclick.zone', (event: MouseEvent) => {
            event.preventDefault();
            event.stopPropagation();
            activateZone(grp.id);
          })
          .on('keydown.zone', (event: KeyboardEvent) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              activateZone(grp.id);
            }
            if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
              event.preventDefault();
              event.stopPropagation();
              stopCameraFollow();
              activateZone(grp.id);
              centerMembers(grp);
              const step = event.shiftKey ? 10 : 1;
              const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
              const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
              for (const node of members) { node.x += dx; node.y += dy; }
              renderAll();
              emitViewState(nodes, d3.zoomTransform(svgRef.current!));
            }
          })
          .call(d3.drag<SVGRectElement, unknown>()
            .container(() => g.node()!)
            .filter(event => activeZoneId === grp.id && !event.button && !event.ctrlKey)
            .on('start', event => {
              trackDrag(event);
              centerMembers(grp);
              moveStart = snapshot();
              movePointer = { x: event.x, y: event.y };
              rect.style('cursor', 'grabbing');
            })
            .on('drag', event => {
              stopCameraFollow();
              let dx = event.x - movePointer.x, dy = event.y - movePointer.y;
              const constrain = event.sourceEvent.shiftKey;
              const horizontal = Math.abs(dx) >= Math.abs(dy);
              if (constrain) { if (horizontal) dy = 0; else dx = 0; }
              const match = event.sourceEvent.altKey ? { dx: 0, dy: 0, guides: [] }
                : snapBounds({ ...moveStart.frame, x: moveStart.frame.x + dx, y: moveStart.frame.y + dy }, otherFrames(), snapThreshold(),
                  { x: constrain && !horizontal ? [] : undefined, y: constrain && horizontal ? [] : undefined });
              for (const position of moveStart.positions) {
                position.node.x = position.x + dx + match.dx;
                position.node.y = position.y + dy + match.dy;
              }
              renderAll();
              showGuides(match.guides);
            })
            .on('end', () => {
              dragView = null;
              showGuides([]);
              rect.style('cursor', 'grab');
              emitViewState(nodes, d3.zoomTransform(svgRef.current!));
            }));
      });
      svg.on('mousedown.zone', (event: MouseEvent) => {
        const zone = (event.target as Element).closest('.group-box');
        if (zone?.getAttribute('data-group-id') !== activeZoneId) activateZone(null);
      }, true).on('keydown.zone', (event: KeyboardEvent) => {
          if (event.key === 'Escape') {
            const selected = groupEls.find(({ grp }) => grp.id === activeZoneId);
            if ((event.target as Element).classList.contains('zone-resize')) selected?.rect.node()?.focus();
            activateZone(null);
          }
        });
    }

    // ── Edge layer ────────────────────────────────────────────────────────────
    const linkGroup = g.append('g');

    // Visible edge path.
    // Feedback paths remain faintly visible in overview; detailed labels appear
    // only on hover so dense diagrams do not become a wall of text.
    const link = linkGroup.selectAll('path.edge-vis')
      .data(links).enter().append('path')
      .attr('class', 'edge-vis')
      .attr('data-source-id', (d: RenderLink) => d.source.id)
      .attr('data-target-id', (d: RenderLink) => d.target.id)
      .attr('data-edge-label', (d: RenderLink) => d.label)
      .attr('data-connection-count', (d: RenderLink) => d.connection.members.length)
      .attr('data-connection-members', (d: RenderLink) => JSON.stringify(d.connection.members.map(
        ({ source, target, label }) => ({ source, target, label }),
      )))
      .attr('stroke-linejoin', 'round')
      .attr('vector-effect', navigation ? 'non-scaling-stroke' : null)
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
      .attr('marker-end', (d: RenderLink) => navigation ? 'url(#arrow-both)'
        : (d.edgeType === 'loop' || !isForward(d)) ? 'url(#arrow-ret)' : 'url(#arrow-fwd)')
      .attr('marker-start', (d: RenderLink) => navigation && d.connection.bidirectional ? 'url(#arrow-both)' : null)
      .attr('opacity', (d: RenderLink) => d.edgeType === 'loop' ? 0.42 : 1);

    // Wide invisible hit area for easier hover targeting
    const linkHit = linkGroup.selectAll('path.edge-hit')
      .data(links).enter().append('path')
      .attr('class', 'edge-hit')
      .attr('fill', 'none')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 14)
      .attr('vector-effect', navigation ? 'non-scaling-stroke' : null)
      .attr('role', navigation ? 'button' : null)
      .attr('aria-label', (d: RenderLink) => navigation ? `Connections between ${d.source.label} and ${d.target.label}` : null)
      .on('click', (event: MouseEvent, d: RenderLink) => {
        if (!navigation) return;
        event.stopPropagation();
        setEdgeTooltip(null);
        setSelectedConnectionId(d.connection.id);
      })
      .on('keydown', (event: KeyboardEvent, d: RenderLink) => {
        if (!navigation || !['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        setSelectedConnectionId(d.connection.id);
      })
      .attr('opacity', 0)
      .style('cursor', navigation ? 'pointer' : 'crosshair')
      .on('mouseover', function(ev: MouseEvent, d: RenderLink) {
        if (navigation) {
          const svgRect = svgRef.current!.getBoundingClientRect();
          setEdgeTooltip({ x: Math.max(0, Math.min(ev.clientX - svgRect.left, svgRect.width - 270)),
            y: ev.clientY - svgRect.top, label: `${d.source.label} / ${d.target.label}`,
            technology: '', sync: '', description: '', count: d.connection.members.length });
          return;
        }
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
        if (navigation) { setEdgeTooltip(null); return; }
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
      .data(navigation ? [] : links).enter().append('g')
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
    const nodeDragStarts = new Map<string, { x: number; y: number; targets: Box[] }>();

    const nodeSel = nodeGroup.selectAll<SVGGElement, RenderNode>('g.node')
      .data(nodes).enter().append('g')
      .attr('class', 'node')
      .attr('data-node-id', (d: RenderNode) => d.id)
      .attr('role', 'button')
      .attr('tabindex', 0)
      .attr('aria-label', (d: RenderNode) => `Explore ${d.label}`)
      .attr('aria-description', onNodeEditRef.current ? 'Double-click or press F2 to edit.' : null)
      .attr('data-grouped', (d: RenderNode) => groupStyleByNodeId.has(d.id) ? 'true' : null)
      .attr('opacity', 1)
      .style('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, RenderNode>()
          .on('start', function(event, node) {
            trackDrag(event);
            d3.select(this).raise().style('cursor', 'grabbing');
            const visible = new Set(renderStateRef.current?.nodeSel.filter(function() {
              return this.getAttribute('aria-hidden') !== 'true';
            }).data().map(item => item.id) ?? nodes.map(item => item.id));
            const targets = nodes.filter(other => other.id !== node.id && visible.has(other.id)).map(other => contentBounds([other]));
            const group = groups.find(group => group.nodeIds.includes(node.id));
            if (group) {
              const frame = boundsOf(group);
              targets.push({ x: frame.x + 24, y: frame.y + 42, width: frame.width - 48, height: frame.height - 62 });
            }
            nodeDragStarts.set(node.id, { x: node.x, y: node.y, targets });
          })
          .on('drag', (event, d) => {
            stopCameraFollow();
            const start = nodeDragStarts.get(d.id)!;
            const constrain = navigation && event.sourceEvent.shiftKey;
            const horizontal = Math.abs(event.x - start.x) >= Math.abs(event.y - start.y);
            const x = constrain && !horizontal ? start.x : event.x;
            const y = constrain && horizontal ? start.y : event.y;
            const match = !navigation || event.sourceEvent.altKey ? { dx: 0, dy: 0, guides: [] }
              : snapBounds({ x: x - NODE_W / 2, y: y - NODE_H / 2, width: NODE_W, height: NODE_H }, start.targets, snapThreshold(),
                { x: constrain && !horizontal ? [] : undefined, y: constrain && horizontal ? [] : undefined });
            d.x = x + match.dx;
            d.y = y + match.dy;
            renderAll();
            showGuides(match.guides);
          })
          .on('end', function(_event, node) {
            dragView = null;
            nodeDragStarts.delete(node.id);
            d3.select(this).style('cursor', 'pointer');
            showGuides([]);
            const currentTransform = d3.zoomTransform(svgRef.current!);
            emitViewState(nodes, currentTransform);
          })
      )
      .on('click', (event: MouseEvent, d: RenderNode) => {
        if (onNodeEditRef.current) {
          if (event.detail > 1) return;
          clearPendingNodeClick();
          pendingNodeClick = window.setTimeout(() => {
            pendingNodeClick = null;
            setSelectedConnectionId(null);
            onNodeClickRef.current(d);
          }, 350);
          return;
        }
        setSelectedConnectionId(null);
        onNodeClickRef.current(d);
      })
      .on('dblclick.edit', (event: MouseEvent, d: RenderNode) => {
        if (!onNodeEditRef.current) return;
        event.preventDefault();
        event.stopPropagation();
        clearPendingNodeClick();
        setSelectedConnectionId(null);
        onNodeEditRef.current(d);
      })
      .on('focus', (_event: FocusEvent, d: RenderNode) => setFocusedNodeId(d.id))
      .on('blur', () => setFocusedNodeId(null))
      .on('keydown', (event: KeyboardEvent, d: RenderNode) => {
        if (event.key === 'F2' && onNodeEditRef.current) {
          event.preventDefault();
          event.stopPropagation();
          clearPendingNodeClick();
          setSelectedConnectionId(null);
          onNodeEditRef.current(d);
          return;
        }
        if (navigation && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
          event.preventDefault();
          event.stopPropagation();
          stopCameraFollow();
          const step = event.shiftKey ? 10 : 1;
          d.x += event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
          d.y += event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
          renderAll();
          emitViewState(nodes, d3.zoomTransform(svgRef.current!));
          return;
        }
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        setSelectedConnectionId(null);
        onNodeClickRef.current(d);
      })
      .on('mouseover', function(_ev: MouseEvent, d: RenderNode) {
        setHoveredNodeId(d.id);
        d3.select(this).select('.node-card')
          .attr('stroke-width', 2)
          .style('filter', 'brightness(1.14)');
        const incidentIndices = navigation ? [] : incidentIndicesByNode.get(d.id) ?? [];
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
        setHoveredNodeId(null);
        d3.select(this).select('.node-card')
          .attr('stroke-width', 1.35)
          .style('filter', null);
        const incidentIndices = navigation ? [] : incidentIndicesByNode.get(d.id) ?? [];
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
      .text((d: RenderNode) => navigation
        ? `${d.label}: ${d.description || 'Select to learn about this component.'}`
        : d.technology ? `${d.label} — ${d.technology}` : d.label);

    // Card background
    nodeSel.append('rect')
      .attr('class', 'node-card')
      .attr('width', NODE_W).attr('height', NODE_H)
      .attr('x', -NODE_W / 2).attr('y', -NODE_H / 2)
      .attr('rx', NODE_RX).attr('ry', NODE_RX)
      .attr('fill',   (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).fill)
      .attr('stroke', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke)
      .attr('stroke-width', 1.35)
      .attr('filter', 'url(#architecture-card-shadow)');

    // Left accent stripe
    nodeSel.append('rect')
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
    nodeSel.filter(() => !navigation && renderGraphData.design_origin !== 'applied').append('text')
      .text((d: RenderNode) => d.type.toUpperCase())
      .attr('x', -NODE_W / 2 + 12).attr('y', -NODE_H / 2 + 11)
      .attr('font-size', '0.44rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.07em')
      .attr('fill', (d: RenderNode) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).badge)
      .style('pointer-events', 'none');

    // Row 1 — tier badge (top-right: PUB / PVT)
    nodeSel.filter((d: RenderNode) => !navigation && Boolean(d.tier) && renderGraphData.design_origin !== 'applied')
      .append('text')
      .text((d: RenderNode) => d.tier === 'public' ? 'PUB' : 'PVT')
      .attr('x', NODE_W / 2 - 8).attr('y', -NODE_H / 2 + 11)
      .attr('text-anchor', 'end')
      .attr('font-size', '0.42rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.06em')
      .attr('fill', (d: RenderNode) => d.tier === 'public' ? '#fbbf24' : '#6e7681')
      .style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => !navigation && groupStyleByNodeId.has(d.id))
      .append('circle')
      .attr('cx', -NODE_W / 2 + 12)
      .attr('cy', -NODE_H / 2 + 12)
      .attr('r', 2.5)
      .attr('fill', (d: RenderNode) => groupStyleByNodeId.get(d.id)?.color ?? '#94a3b8')
      .attr('opacity', 0.9)
      .style('pointer-events', 'none');

    nodeSel.filter((d: RenderNode) => !navigation && groupStyleByNodeId.has(d.id))
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
      !navigation && renderGraphData.design_origin === 'applied'
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
      .attr('font-size', `${NODE_TITLE_PX}px`).attr('font-weight', 500)
      .attr('fill', '#e6edf3')
      .style('pointer-events', 'none');

    nodeTitles.each(function(d: RenderNode) {
      const lines = wrapNodeLabel(d.label, text => {
        this.textContent = text;
        try {
          return this.getBBox().width;
        } finally {
          this.textContent = '';
        }
      });
      const hasSubtitle = Boolean(d.technology) && d.design_origin === 'applied';
      const compactSubtitle = navigation && hasSubtitle && wrapNodeTechnology(d.technology || '').length === 2;
      // Two subtitle lines need more room inside the shared 68px card.
      const normalLineHeight = navigation ? 20 : 13;
      const normalTitleCenterY = navigation && hasSubtitle ? -4 : 2;
      const lineHeight = compactSubtitle ? 18 : normalLineHeight;
      const titleCenterY = compactSubtitle ? -10 : normalTitleCenterY;
      const startY = titleCenterY - (lines.length - 1) * lineHeight / 2;
      d3.select(this).selectAll('tspan')
        .data(lines)
        .enter()
        .append('tspan')
        .attr('x', 0)
        .attr('y', (_line: string, index: number) => startY + index * lineHeight)
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
        const multilineStartY = navigation ? 15 : 20;
        const startY = lines.length === 1 ? 24 : multilineStartY;
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
      // Keep the badge clear of the preceding card across the 24px gap.
      .attr('x', -NODE_W / 2 - MARKER_GAP - MARKER_W / 2 + 2)
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
      .data(navigation ? [] : links).enter().append('g').attr('class', 'step-badge');
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
      routeCache.clear();
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
        const PX = navigation ? 24 : 16, PT = navigation ? 42 : 8, PB = navigation ? 20 : 4;
        const padding = zonePadding[groupDef.id];
        const minX = Math.min(...memberNodes.map((n: RenderNode) => n.x)) - NODE_W / 2 - PX - (padding?.left ?? 0);
        const maxX = Math.max(...memberNodes.map((n: RenderNode) => n.x)) + NODE_W / 2 + PX + (padding?.right ?? 0);
        const minY = Math.min(...memberNodes.map((n: RenderNode) => n.y)) - NODE_H / 2 - PT - (padding?.top ?? 0);
        const maxY = Math.max(...memberNodes.map((n: RenderNode) => n.y)) + NODE_H / 2 + PB + (padding?.bottom ?? 0);
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
        handles,
      } of groupLayouts) {
        const useBoundary = navigation || (boundaryLayouts.some(layout => layout.grp.id === groupDef.id)
          && !overlappingBoundaryIds.has(groupDef.id));

        rect
          .attr('display', useBoundary ? null : 'none')
          .attr('x', bounds.x).attr('y', bounds.y)
          .attr('width', bounds.width).attr('height', bounds.height);
        handles.each(function(side) {
          const corner = side.length === 2;
          const horizontal = side === 'n' || side === 's';
          const size = 12;
          const x = side.includes('w') ? bounds.x - size / 2 : side.includes('e') ? bounds.x + bounds.width - size / 2 : bounds.x + size / 2;
          const y = side.includes('n') ? bounds.y - size / 2 : side.includes('s') ? bounds.y + bounds.height - size / 2 : bounds.y + size / 2;
          d3.select(this).attr('x', x).attr('y', y)
            .attr('width', corner || !horizontal ? size : bounds.width - size)
            .attr('height', corner || horizontal ? size : bounds.height - size);
        });
        const labelWidth = navigation ? Math.max(100, groupDef.label.length * 8 + 24) : Math.min(
          NODE_W - 20,
          Math.max(74, Math.min(groupDef.label.length, 28) * 5.6 + 20),
        );
        const labelX = useBoundary ? bounds.x + 10 : memberNodes[0].x - NODE_W / 2 + 8;
        const labelY = useBoundary ? bounds.y + (navigation ? 10 : 3) : memberNodes[0].y - NODE_H / 2 + 4;
        labelBackground
          .attr('x', labelX)
          .attr('y', labelY)
          .attr('width', labelWidth)
          .attr('height', navigation ? 22 : 15)
          .attr('display', navigation ? 'none' : null);
        labelText.attr('x', labelX + 8).attr('y', labelY + (navigation ? 15 : 11));
      }

      groupLabelsLayer.raise();

      if (navigation) return;

      const occupiedBoxes = nodes.map((node: RenderNode) => ({
        x: node.x - NODE_W / 2 - 14,
        y: node.y - NODE_H / 2 - 14,
        width: NODE_W + 28,
        height: NODE_H + 28,
      }));
      const placedLabels: Array<{ x: number; y: number; width: number; height: number }> = [];

      const labelsByPriority = edgeLabelGroup.nodes().map(element => ({
        element,
        link: d3.select<SVGGElement, RenderLink>(element).datum(),
      })).sort((left, right) => Number(right.link.overviewRequired) - Number(left.link.overviewRequired));

      for (const { element, link: d } of labelsByPriority) {
        const grp = d3.select(element).attr('display', null);
        const textEl = grp.select('text').node() as SVGTextElement | null;
        if (!textEl) continue;

        const textBox = textEl.getBBox();
        const labelWidth = textBox.width + 6;
        const labelHeight = textBox.height + 2;
        const localLabelCenter = {
          x: textBox.x + textBox.width / 2,
          y: textBox.y + textBox.height / 2,
        };
        grp.select('rect')
          .attr('x', textBox.x - 3)
          .attr('y', textBox.y - 1)
          .attr('width', labelWidth)
          .attr('height', labelHeight);

        const verticalForward = orientation === 'vertical' && isForward(d);
        const centerX = midX(d);
        const centerY = midY(d);
        const labelCenterX = orientation === 'vertical' && !isForward(d)
          ? Math.min(
              layoutW - labelWidth / 2 - 4,
              centerX + labelWidth / 2 + 8,
            )
          : centerX;
        const baseY = verticalForward
          ? centerY
          : centerY - (d.stepNum !== null ? 20 : isForward(d) ? 12 : 20);
        const sideOffset = NODE_W / 2 + labelWidth / 2 + 14;
        const preferredSide = centerX < layoutW / 2 ? -1 : 1;
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
              x: labelCenterX,
              y: baseY + (attempt === 0
                ? 0
                : (attempt % 2 === 1 ? -1 : 1)
                  * (14 + Math.floor((attempt - 1) / 2) * (isForward(d) ? 6 : 7))),
            }));
        const nearbyCandidates = Array.from({ length: 9 }, (_, column) => (
          Array.from({ length: 9 }, (_, row) => ({
            x: labelCenterX + (column - 4) * Math.max(NODE_W / 4, labelWidth / 2 + 8),
            y: baseY + (row - 4) * (labelHeight + 6),
          }))
        )).flat();
        const boundedCandidates = [...candidates, ...nearbyCandidates].map(candidate => boundLabelCenter(
          candidate,
          { width: labelWidth, height: labelHeight },
          { width: layoutW, height: layoutH },
        )).sort((left, right) => (
          Math.hypot(left.x - centerX, left.y - centerY)
          - Math.hypot(right.x - centerX, right.y - centerY)
        ));
        const canPlace = (candidatePosition: { x: number; y: number }): boolean => {
          const candidate = {
            x: candidatePosition.x - labelWidth / 2,
            y: candidatePosition.y - labelHeight / 2,
            width: labelWidth,
            height: labelHeight,
          };
          const collides = candidate.x < 0 || candidate.y < 0
            || candidate.x + candidate.width > layoutW
            || candidate.y + candidate.height > layoutH
            || occupiedBoxes.some((box) => boxesIntersect(candidate, box))
            || placedLabels.some((box) => boxesIntersect(candidate, box));
          return !collides;
        };
        let placement = boundedCandidates.find(canPlace);
        if (!placement && d.overviewRequired) {
          // A fixed sampling grid can miss free space beside an obstacle.
          // Search its boundaries only after the nearby positions fail.
          const obstacles = [...occupiedBoxes, ...placedLabels];
          const xs = labelAxisCandidates(centerX, layoutW, labelWidth,
            obstacles.map(box => ({ start: box.x, end: box.x + box.width })));
          const ys = labelAxisCandidates(centerY, layoutH, labelHeight,
            obstacles.map(box => ({ start: box.y, end: box.y + box.height })));
          let nearestDistance = Infinity;
          for (const x of xs) {
            for (const y of ys) {
              const distance = (x - centerX) ** 2 + (y - centerY) ** 2;
              if (distance < nearestDistance && canPlace({ x, y })) {
                placement = { x, y };
                nearestDistance = distance;
              }
            }
          }
        }

        // Keep an unplaceable label hidden even when hover changes opacity.
        // Its edge tooltip and node connection list still expose the contract.
        if (!placement) {
          grp.attr('display', 'none');
          continue;
        }
        if (overviewEdgeLabelOpacity({ flow: d.flow, type: d.edgeType }, d.overviewRequired) > 0) {
          placedLabels.push({
            x: placement.x - labelWidth / 2, y: placement.y - labelHeight / 2,
            width: labelWidth, height: labelHeight,
          });
        }
        grp.attr(
          'transform',
          `translate(${placement.x - localLabelCenter.x},${placement.y - localLabelCenter.y})`,
        );
      }
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
    const fitTransform = d3.zoomIdentity.translate(fitTx, fitTy).scale(fitScale);
    const readableScale = Math.max(fitScale, minimumTitlePx / NODE_TITLE_PX);
    const readableTransform = d3.zoomIdentity.translate(
      Math.max(INITIAL_FIT_PADDING, (width - layoutW * readableScale) / 2),
      Math.max(INITIAL_FIT_PADDING, (height - layoutH * readableScale) / 2),
    ).scale(readableScale);
    navigateRef.current = (action) => {
      stopCameraFollow();
      if (action === 'fit' || action === 'read') {
        const boxes = groupEls.map(({ rect }) => ({
          x: Number(rect.attr('x')), y: Number(rect.attr('y')),
          width: Number(rect.attr('width')), height: Number(rect.attr('height')),
        })).filter(box => Object.values(box).every(Number.isFinite));
        const left = Math.min(0, ...boxes.map(box => box.x), ...nodes.map(node => node.x - NODE_W / 2));
        const top = Math.min(0, ...boxes.map(box => box.y), ...nodes.map(node => node.y - NODE_H / 2));
        const right = Math.max(layoutW, ...boxes.map(box => box.x + box.width), ...nodes.map(node => node.x + NODE_W / 2));
        const bottom = Math.max(layoutH, ...boxes.map(box => box.y + box.height), ...nodes.map(node => node.y + NODE_H / 2));
        const scale = Math.max(initialFitScale(width, height, right - left, bottom - top),
          action === 'read' ? minimumTitlePx / NODE_TITLE_PX : 0);
        svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(
          Math.max(INITIAL_FIT_PADDING, (width - (right - left) * scale) / 2) - left * scale,
          Math.max(INITIAL_FIT_PADDING, (height - (bottom - top) * scale) / 2) - top * scale,
        ).scale(scale));
      } else {
        svg.call(zoomBehavior.scaleBy, action === 'in' ? 1.25 : 0.8);
      }
    };
    const previousViewport = previousViewportRef.current;
    const sameDiagram = previousViewport?.key === structureKey;
    const resizeX = sameDiagram ? (width - previousViewport.width) / 2 : 0;
    const resizeY = sameDiagram ? (height - previousViewport.height) / 2 : 0;
    previousViewportRef.current = { key: structureKey, width, height };
    // Preserve the point at the center of the pane when its dimensions change.
    const initialTransform = restoreViewState?.viewport
      ? d3.zoomIdentity
          .translate(restoreViewState.viewport.x + resizeX, restoreViewState.viewport.y + resizeY)
          .scale(restoreViewState.viewport.k)
      : navigation ? readableTransform : fitTransform;
    const camera = walkthroughCameraRef.current;
    if (sameDiagram && camera?.active && !camera.userIntervened) camera.baseline = initialTransform;
    svg.call(zoomBehavior.transform, initialTransform);

    const setTransientViewport = (transform: d3.ZoomTransform) => {
      applyingTransientCamera = true;
      try {
        svg.call(zoomBehavior.transform, transform);
      } finally {
        applyingTransientCamera = false;
      }
    };
    const correction = (start: number, end: number, minimum: number, maximum: number) => {
      if (end - start > maximum - minimum) return (minimum + maximum - start - end) / 2;
      if (start < minimum) return minimum - start;
      if (end > maximum) return maximum - end;
      return 0;
    };
    const focusWalkthroughNodes = (nodeIds: Set<string>) => {
      const activeNodes = nodes
        .filter(node => nodeIds.has(node.id) && Number.isFinite(node.x) && Number.isFinite(node.y))
        .sort((a, b) => a.x - b.x || a.y - b.y || a.id.localeCompare(b.id));
      if (activeNodes.length === 0) return;
      const activeBounds = {
        left: Math.min(...activeNodes.map(node => node.x - NODE_W / 2)),
        right: Math.max(...activeNodes.map(node => node.x + NODE_W / 2)),
        top: Math.min(...activeNodes.map(node => node.y - NODE_H / 2)),
        bottom: Math.max(...activeNodes.map(node => node.y + NODE_H / 2)),
      };
      const toolbarHeight = svg.node()?.parentElement?.querySelector<HTMLElement>('.diagram-toolbar')?.offsetHeight ?? 0;
      const left = Math.min(32, width / 4);
      const right = width - left;
      const top = Math.min(Math.max(72, toolbarHeight + 24), height / 3);
      const bottom = height - Math.min(32, height / 4);
      const current = d3.zoomTransform(svg.node()!);
      const preferredScale = walkthroughCameraRef.current?.baseline?.k ?? current.k;
      const readableFloor = Math.min(preferredScale, minimumTitlePx / NODE_TITLE_PX);
      const fitScale = Math.min(
        preferredScale,
        (right - left) / (activeBounds.right - activeBounds.left),
        (bottom - top) / (activeBounds.bottom - activeBounds.top),
      );
      const scale = Math.max(readableFloor, fitScale);
      const first = activeNodes[0];
      const bounds = fitScale >= readableFloor ? activeBounds : {
        left: first.x - NODE_W / 2,
        right: first.x + NODE_W / 2,
        top: first.y - NODE_H / 2,
        bottom: first.y + NODE_H / 2,
      };
      const dx = correction(bounds.left * scale + current.x, bounds.right * scale + current.x, left, right);
      const dy = correction(bounds.top * scale + current.y, bounds.bottom * scale + current.y, top, bottom);
      if (scale === current.k && dx === 0 && dy === 0) return;
      setTransientViewport(d3.zoomIdentity.translate(current.x + dx, current.y + dy).scale(scale));
    };
    const focusInspectionNode = (nodeId: string, safeWidth: number, safeHeight: number) => {
      const node = nodeById[nodeId];
      if (!node || !Number.isFinite(node.x) || !Number.isFinite(node.y)
        || !Number.isFinite(safeWidth) || safeWidth <= 0
        || !Number.isFinite(safeHeight) || safeHeight <= 0) return;
      const visibleWidth = Math.min(width, safeWidth);
      const visibleHeight = Math.min(height, safeHeight);
      const toolbarHeight = svg.node()?.parentElement?.querySelector<HTMLElement>('.diagram-toolbar')?.offsetHeight ?? 0;
      const left = Math.min(32, visibleWidth / 4);
      const right = visibleWidth - left;
      const top = Math.min(Math.max(72, toolbarHeight + 24), visibleHeight / 3);
      const bottom = visibleHeight - Math.min(32, visibleHeight / 4);
      const current = d3.zoomTransform(svg.node()!);
      const dx = correction(
        (node.x - NODE_W / 2) * current.k + current.x,
        (node.x + NODE_W / 2) * current.k + current.x,
        left, right,
      );
      const dy = correction(
        (node.y - NODE_H / 2) * current.k + current.y,
        (node.y + NODE_H / 2) * current.k + current.y,
        top, bottom,
      );
      if (dx === 0 && dy === 0) return;
      setTransientViewport(d3.zoomIdentity.translate(current.x + dx, current.y + dy).scale(current.k));
    };

    renderStateRef.current = {
      nodeSel,
      link,
      linkHit,
      edgeLabelGroup,
      stepBadgeGroup,
      nodeFirstStep,
      sequenceLength: sequence.length,
      isForward,
      viewport: () => d3.zoomTransform(svg.node()!),
      setTransientViewport,
      focusWalkthroughNodes,
      focusInspectionNode,
    };

    let cancelled = false;
    let firstFrame = 0;
    let secondFrame = 0;
    const signalReady = () => {
      firstFrame = window.requestAnimationFrame(() => {
        secondFrame = window.requestAnimationFrame(() => {
          if (!cancelled) {
            svg.attr('data-rendered-graph-version', renderGraphData.version ?? '');
            onLayoutReadyRef.current?.(structureKey);
          }
        });
      });
    };
    const fonts = document.fonts?.ready;
    if (fonts) void fonts.then(signalReady, signalReady);
    else signalReady();

    return () => {
      cancelled = true;
      clearPendingNodeClick();
      // D3 captures mouse drags on window; a chat switch can remove the canvas before mouseup.
      if (dragView) {
        d3.select(dragView).on('mousemove.drag mouseup.drag', null);
        d3.dragEnable(dragView);
      }
      svg.on('.zone', null);
      window.cancelAnimationFrame(firstFrame);
      window.cancelAnimationFrame(secondFrame);
      renderStateRef.current = null;
    };
  }, [minimumTitlePx, navigation, structureKey, viewportRevision]);

  useEffect(() => {
    const exists = renderStateRef.current?.nodeSel.data().some(node => node.id === inspectedNodeId);
    if (!navigation || !inspectedNodeId || !exists) return;
    const camera = inspectionCameraRef.current;
    if (camera?.nodeId === inspectedNodeId) {
      camera.key = structureKey;
      return;
    }
    inspectionCameraRef.current = { key: structureKey, nodeId: inspectedNodeId, userIntervened: false };
  }, [inspectedNodeId, navigation, structureKey, viewportRevision]);

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
    const state = renderStateRef.current;
    const camera = walkthroughCameraRef.current;
    if (!navigation || !state || !camera) return;
    if (inspectionCameraRef.current) {
      if (currentStep < 0) {
        camera.active = false;
        camera.userIntervened = false;
        camera.baseline = null;
      }
      return;
    }
    if (currentStep < 0) {
      if (camera.active && !camera.userIntervened && camera.baseline) {
        state.setTransientViewport(camera.baseline);
      }
      camera.active = false;
      camera.userIntervened = false;
      camera.baseline = null;
      return;
    }
    if (!camera.active) {
      camera.active = true;
      camera.baseline = state.viewport();
    }
    if (!camera.userIntervened) state.focusWalkthroughNodes(activeNodeIds);
  }, [activeNodeIds, currentStep, inspectedNodeId, navigation, structureKey, viewportRevision]);

  useEffect(() => {
    const camera = inspectionCameraRef.current;
    const state = renderStateRef.current;
    if (!navigation || !inspectedNodeId || !state?.nodeSel.data().some(node => node.id === inspectedNodeId)) {
      inspectionCameraRef.current = null;
      return;
    }
    if (!camera || camera.userIntervened
      || camera.key !== structureKey || camera.nodeId !== inspectedNodeId) return;
    state.focusInspectionNode(camera.nodeId, inspectionWidth, inspectionHeight);
  }, [inspectedNodeId, inspectionWidth, inspectionHeight, navigation, structureKey, viewportRevision]);

  useEffect(() => {
    const renderState = renderStateRef.current;
    if (!renderState || navigation) return;

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
  }, [activeNodeIds, currentStep, navigation, structureKey, viewportRevision]);

  useEffect(() => {
    const state = renderStateRef.current;
    if (!state || !navigation) return;
    const focus = hoveredNodeId ?? focusedNodeId;
    const overview = currentStep < 0 || state.sequenceLength === 0;
    const revealed = (node: RenderNode) => overview || (state.nodeFirstStep.get(node.id) ?? 1) <= currentStep + 1;
    const incident = (edge: RenderLink) => edge.source.id === focus || edge.target.id === focus;
    const selected = (edge: RenderLink) => edge.connection.id === selectedConnectionId;
    const active = (edge: RenderLink) => !overview && activeNodeIds.has(edge.source.id) && activeNodeIds.has(edge.target.id);
    const visible = (edge: RenderLink) => revealed(edge.source) && revealed(edge.target)
      && (edge.overviewRequired || showConnections || incident(edge) || selected(edge) || active(edge));
    // One owner controls live edge visibility, hit targets, and walkthroughs.
    state.nodeSel.interrupt().attr('opacity', node => !revealed(node) ? 0
      : overview || activeNodeIds.has(node.id) ? 1 : 0.45)
      .attr('tabindex', node => revealed(node) ? 0 : -1)
      .attr('aria-hidden', node => String(!revealed(node)))
      .style('pointer-events', node => revealed(node) ? 'auto' : 'none');
    state.link.interrupt().attr('opacity', 1)
      .style('opacity', edge => !visible(edge) ? 0 : incident(edge) || selected(edge) || active(edge) ? 1
        : focus || !overview ? 0.18 : edge.overviewRequired ? 0.8 : 0.4)
      .attr('stroke-width', edge => incident(edge) || selected(edge) || active(edge) ? 2 : 1.4);
    state.linkHit.interrupt().attr('opacity', 1).attr('tabindex', edge => visible(edge) ? 0 : -1)
      .attr('aria-hidden', edge => String(!visible(edge)))
      .style('pointer-events', edge => visible(edge) ? 'stroke' : 'none');
  }, [navigation, focusedNodeId, hoveredNodeId, selectedConnectionId, showConnections, activeNodeIds, currentStep, structureKey, viewportRevision]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {navigation && <div aria-label="Diagram view" role="group" className="diagram-toolbar">
        <button type="button" aria-pressed={showConnections} onClick={() => setShowConnections(value => !value)}
          title={showConnections ? 'Hide supporting connections' : 'Show all connections'}>Connections</button>
        {([['out', 'Zoom out', '−'], ['in', 'Zoom in', '+'], ['fit', 'Fit diagram', 'Fit'], ['read', 'Readable view', 'Readable']] as const).map(([action, label, text]) => (
          <button key={action} type="button" aria-label={label} title={label} onClick={() => navigateRef.current(action)}
            className={action === 'in' || action === 'out' ? 'diagram-toolbar__zoom' : undefined}>
            {action === 'in' || action === 'out' ? <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 8h10" />{action === 'in' && <path d="M8 3v10" />}
            </svg> : text}
          </button>
        ))}
      </div>}
      {/* overflow:visible allows return-edge arcs to arc above the SVG viewport */}
      <svg
        ref={svgRef}
        data-testid="graph-canvas"
        aria-label="Architecture graph"
        style={{ width: '100%', height: '100%', background: '#080d14', overflow: 'visible' }}
      />

      {navigation && selectedConnection && <section className="connection-details" aria-label="Connection details"
        onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); closeConnection(); } }}>
        <header>
          <h3>Connections</h3>
          <button ref={connectionCloseRef} type="button" aria-label="Close connection details" onClick={closeConnection}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="m4 4 8 8M12 4l-8 8" /></svg>
          </button>
        </header>
        <ol>{selectedConnection.members.map((edge, index) => <li key={`${edge.edge_id ?? ''}:${index}`}>
          <p className="connection-details__direction">{nodeLabel(edge.source)} <span aria-label="to">→</span> {nodeLabel(edge.target)}</p>
          <p className="connection-details__label">{edge.label}</p>
          {edge.description && edge.description !== edge.label && <p>{edge.description}</p>}
          {edge.technology && <p className="connection-details__technology">{edge.technology}</p>}
          {onEditConnection && <button type="button" onClick={() => {
            const edgeIndex = graphData.edges.indexOf(edge);
            if (edgeIndex < 0) return;
            setSelectedConnectionId(null);
            onEditConnection(edgeIndex);
          }} aria-label={`Edit connection ${nodeLabel(edge.source)} to ${nodeLabel(edge.target)}`}>Edit connection</button>}
        </li>)}</ol>
      </section>}

      {/* Edge hover tooltip */}
      {edgeTooltip && (
        <div role="tooltip" style={{
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
          {!navigation && <div style={{ marginBottom: 3, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
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
          </div>}
          <div style={{ color: '#e6edf3', fontWeight: 500 }}>{edgeTooltip.label}</div>
          {navigation && <div style={{ color: '#bcc7d8', marginTop: 4 }}>Select to view {edgeTooltip.count} {edgeTooltip.count === 1 ? 'exchange' : 'exchanges'}</div>}
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
