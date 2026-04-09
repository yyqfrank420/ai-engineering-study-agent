// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/D3Graph.tsx
// Purpose: Architecture diagram rendered with a STATIC left-to-right column
//          layout (no force simulation). Follows AWS architecture diagram
//          conventions: strict left→right data flow, numbered steps on edges,
//          forward edges as straight horizontal lines, return/back edges as
//          cubic-bezier arcs routing above the diagram.
// Language: TypeScript / React / D3 v7
// Connects to: types/index.ts, hooks/useGraph.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { GraphData, GraphGroup, GraphNode, GraphViewState } from '../../types';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { TYPE_STYLE, FALLBACK_STYLE } from '../../utils/graphColors';

// ── Node dimensions ─────────────────────────────────────────────────────────
// NODE_W is wide enough to show labels up to ~24 chars without truncation.
const NODE_W  = 186;
const NODE_H  = 56;
const NODE_RX = 6;
const EDGE_LABEL_MAX_CHARS = 18;

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

interface GraphRenderState {
  nodeSel: d3.Selection<SVGGElement, any, SVGGElement, unknown>;
  link: d3.Selection<SVGPathElement, any, SVGGElement, unknown>;
  linkHit: d3.Selection<SVGPathElement, any, SVGGElement, unknown>;
  edgeLabelGroup: d3.Selection<SVGGElement, any, SVGGElement, unknown>;
  stepBadgeGroup: d3.Selection<SVGGElement, any, SVGGElement, unknown>;
  nodeFirstStep: Map<string, number>;
  sequenceLength: number;
  isForward: (d: any) => boolean;
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
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltip | null>(null);
  const structureKey = graphStructureKey(graphData);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    onViewStateChangeRef.current = onViewStateChange;
  }, [onViewStateChange]);

  // ── Main render effect — fires when graphData changes ───────────────────────
  useEffect(() => {
    if (!svgRef.current || !graphData) return;
    setEdgeTooltip(null);

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width  = svgRef.current.clientWidth  || 760;
    const height = svgRef.current.clientHeight || 500;

    // ── Layout constants ──────────────────────────────────────────────────────
    const H_PAD = 44;   // horizontal margin (left/right of first/last column)
    const V_PAD = 72;   // vertical margin (top/bottom of canvas)
    // Minimum column width: node width + comfortable horizontal gap
    const MIN_COL_W = NODE_W + 84;
    // How far above the canvas return-edge arcs peak (requires SVG overflow:visible)
    const RETURN_ARC_Y = -80;

    // ── Arrowhead markers ─────────────────────────────────────────────────────
    const defs = svg.append('defs');

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

    // ── Pan + zoom container ──────────────────────────────────────────────────
    // Store the zoom behaviour so we can set the initial fit transform later.
    const g = svg.append('g');
    const emitViewState = (nodesToPersist: any[], transform: d3.ZoomTransform) => {
      onViewStateChangeRef.current?.({
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
    const nodes: any[] = graphData.nodes.map(n => ({ ...n }));
    const nodeById: Record<string, any> = {};
    for (const n of nodes) nodeById[n.id] = n;

    // ── Assign topological columns ────────────────────────────────────────────
    const colMap  = assignColumns(nodes.map(n => n.id), graphData.edges);
    const numCols = Math.max(1, ...colMap.values()) + 1;
    const colWidth = Math.max(MIN_COL_W, (width - 2 * H_PAD) / numCols);

    // Group nodes by column, then assign fixed (x, y) positions
    const colBuckets = new Map<number, any[]>();
    for (const n of nodes) {
      const c = colMap.get(n.id) ?? 0;
      if (!colBuckets.has(c)) colBuckets.set(c, []);
      colBuckets.get(c)!.push(n);
    }

    const incomingIds = new Map<string, string[]>();
    const outgoingIds = new Map<string, string[]>();
    for (const node of nodes) {
      incomingIds.set(node.id, []);
      outgoingIds.set(node.id, []);
    }
    for (const edge of graphData.edges) {
      incomingIds.get(edge.target)?.push(edge.source);
      outgoingIds.get(edge.source)?.push(edge.target);
    }

    const sequenceRank = new Map<string, number>();
    for (const step of graphData.sequence ?? []) {
      const stepNumber = typeof step.step === 'number' ? step.step : Number.MAX_SAFE_INTEGER;
      for (const nodeId of step.nodes ?? []) {
        const existingRank = sequenceRank.get(nodeId);
        if (existingRank === undefined || stepNumber < existingRank) {
          sequenceRank.set(nodeId, stepNumber);
        }
      }
    }

    const orderById = new Map<string, number>();
    const sortedColumns = Array.from(colBuckets.keys()).sort((a, b) => a - b);
    for (const columnIndex of sortedColumns) {
      const bucket = colBuckets.get(columnIndex) ?? [];
      bucket.sort((a: any, b: any) => {
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

      bucket.forEach((node: any, index: number) => {
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

    const maxMainInCol = Math.max(
      1,
      ...Array.from(colBuckets.values())
        .map(b => b.filter((n: any) => n.lane !== 'bottom').length)
    );
    // effectiveMainH is the actual height used for main-band Y calculation.
    // It's at least the canvas main band, but expands to fit all nodes.
    const canvasMainH    = height - 2 * V_PAD - BOTTOM_BAND_H;
    const effectiveMainH = Math.max(canvasMainH, maxMainInCol * MIN_ROW_H);

    for (const [c, bucket] of colBuckets) {
      const x = H_PAD + (c + 0.5) * colWidth;
      const mainNodes   = bucket.filter((n: any) => n.lane !== 'bottom');
      const bottomNodes = bucket.filter((n: any) => n.lane === 'bottom');

      mainNodes.forEach((n: any, i: number) => {
        n.x = x;
        n.y = V_PAD + (effectiveMainH / Math.max(mainNodes.length, 1)) * (i + 0.5);
      });

      // Bottom-lane nodes sit in the band below the main flow
      bottomNodes.forEach((n: any, i: number) => {
        n.x = x;
        n.y = V_PAD + effectiveMainH + (BOTTOM_BAND_H / Math.max(bottomNodes.length, 1)) * (i + 0.5);
      });
    }

    for (const node of nodes) {
      const persistedPosition = initialViewState?.nodePositions[node.id];
      if (!persistedPosition) continue;
      node.x = persistedPosition.x;
      node.y = persistedPosition.y;
    }

    // Total layout dimensions (used for auto-fit zoom below)
    const layoutW = numCols * colWidth + 2 * H_PAD;
    const layoutH = V_PAD + effectiveMainH + BOTTOM_BAND_H + V_PAD;

    // ── Resolve edges to node object references ───────────────────────────────
    // Also attach the sequence step number for each edge so we can badge it.
    const sequence = graphData.sequence ?? [];
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
    // Build all links, then drop backward non-loop edges.
    // Backward arcs (target.x ≤ source.x) arc above the diagram and create clutter.
    // Only edges with type:"loop" are allowed to flow right-to-left; they are hidden
    // by default and revealed on node hover. This also silently removes any model-
    // generated return arcs that slip through despite the prompt constraint.
    const links = graphData.edges.map(e => {
      let stepNum: number | null = null;
      for (const step of sequence) {
        if ((step.nodes ?? []).includes(e.target)) { stepNum = step.step; break; }
      }
      const src = nodeById[e.source] ?? { id: e.source, x: 0, y: 0 };
      const tgt = nodeById[e.target] ?? { id: e.target, x: 0, y: 0 };
      return {
        source:      src,
        target:      tgt,
        label:       e.label,
        technology:  e.technology ?? '',
        sync:        e.sync ?? 'sync',
        description: e.description ?? '',
        stepNum,
        edgeType:    (e.type ?? 'normal') as 'normal' | 'loop',
      };
    }).filter(l =>
      l.edgeType === 'loop' || (l.target as any).x > (l.source as any).x + 4
    );

    // Pre-build lookup: source node id → indices of its outgoing loop edges.
    // Used by node hover to reveal/hide the right edges instantly.
    const loopIndicesBySource = new Map<string, number[]>();
    links.forEach((l, i) => {
      if (l.edgeType === 'loop') {
        const srcId = (l.source as any).id as string;
        if (!loopIndicesBySource.has(srcId)) loopIndicesBySource.set(srcId, []);
        loopIndicesBySource.get(srcId)!.push(i);
      }
    });

    // ── Hinge helpers ─────────────────────────────────────────────────────────
    // Forward edge (target is clearly to the right of source):
    //   exits the RIGHT border of source, enters the LEFT border of target.
    // Return/back edge (target is to the left of or at the same column):
    //   exits the TOP border of source, enters the TOP border of target.
    //   The path arcs above the canvas, keeping the forward edges clean.

    const isForward = (d: any): boolean => d.target.x > d.source.x + 4;

    // Hinge point X
    const hx1 = (d: any): number => isForward(d) ? d.source.x + NODE_W / 2 : d.source.x;
    const hy1 = (d: any): number => isForward(d) ? d.source.y              : d.source.y - NODE_H / 2;
    const hx2 = (d: any): number => isForward(d) ? d.target.x - NODE_W / 2 : d.target.x;
    const hy2 = (d: any): number => isForward(d) ? d.target.y              : d.target.y - NODE_H / 2;

    // SVG path string for an edge
    const pathD = (d: any): string => {
      const x1 = hx1(d), y1 = hy1(d), x2 = hx2(d), y2 = hy2(d);
      if (isForward(d)) {
        // Straight horizontal line (classic AWS arrow)
        return `M${x1},${y1} L${x2},${y2}`;
      }
      // Cubic bezier: exit top of source, arc above canvas, enter top of target.
      // Control points sit at the RETURN_ARC_Y level, directly above entry/exit X.
      // This creates a smooth U-arc that clears all nodes and group boxes.
      return `M${x1},${y1} C${x1},${RETURN_ARC_Y} ${x2},${RETURN_ARC_Y} ${x2},${y2}`;
    };

    // Midpoint of edge path (used to place labels and step badges)
    const midX = (d: any): number => (hx1(d) + hx2(d)) / 2;
    const midY = (d: any): number => {
      if (isForward(d)) return (hy1(d) + hy2(d)) / 2;
      // For the cubic bezier arc, t=0.5 midpoint is above the canvas
      // By(0.5) = (y1 + 3*cpY + 3*cpY + y2) / 8  where cpY = RETURN_ARC_Y
      return (hy1(d) + hy2(d) + 6 * RETURN_ARC_Y) / 8;
    };

    // ── Entry / exit detection ────────────────────────────────────────────────
    const hasIncoming = new Set(graphData.edges.map(e => e.target));
    const hasOutgoing = new Set(graphData.edges.map(e => e.source));
    const sourceNodeIds = new Set(graphData.nodes.filter(n => !hasIncoming.has(n.id)).map(n => n.id));
    const sinkNodeIds   = new Set(graphData.nodes.filter(n => !hasOutgoing.has(n.id)).map(n => n.id));

    // ── Groups layer (rendered behind edges and nodes) ─────────────────────────
    const groupsLayer = g.append('g').attr('class', 'groups-layer');
    const groups = (graphData.groups ?? []) as GraphGroup[];
    const groupEls = groups.map((grp, idx) => {
      const gc = GROUP_PALETTE[idx % GROUP_PALETTE.length];
      const grpEl = groupsLayer.append('g').attr('class', 'group-box');
      const rect  = grpEl.append('rect')
        .attr('rx', 10)
        .attr('fill', gc.fill)
        .attr('stroke', gc.stroke)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '5,3');
      grpEl.append('text')
        .text(grp.label.toUpperCase())
        .attr('font-size', '0.5rem')
        .attr('font-weight', 700)
        .attr('letter-spacing', '0.1em')
        .attr('fill', gc.label)
        .attr('opacity', 0.6)
        .style('pointer-events', 'none');
      return { grp, grpEl, rect };
    });

    // ── Edge layer ────────────────────────────────────────────────────────────
    const linkGroup = g.append('g');

    // Visible edge path.
    // Loop edges (feedback arcs) start hidden and are revealed only on node hover.
    const link = linkGroup.selectAll('path.edge-vis')
      .data(links).enter().append('path')
      .attr('class', 'edge-vis')
      .attr('fill', 'none')
      .attr('stroke', (d: any) => {
        if (d.edgeType === 'loop') return 'rgba(167,139,250,0.7)';
        return isForward(d) ? '#1e2a3a' : 'rgba(167,139,250,0.35)';
      })
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', (d: any) => d.edgeType === 'loop' ? '5,4' : d.sync === 'async' ? '6,4' : 'none')
      .attr('marker-end', (d: any) => (d.edgeType === 'loop' || !isForward(d)) ? 'url(#arrow-ret)' : 'url(#arrow-fwd)')
      .attr('opacity', 0);

    // Wide invisible hit area for easier hover targeting
    const linkHit = linkGroup.selectAll('path.edge-hit')
      .data(links).enter().append('path')
      .attr('class', 'edge-hit')
      .attr('fill', 'none')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 14)
      .attr('opacity', 0)
      .style('cursor', 'crosshair')
      .on('mouseover', function(ev, d: any) {
        const idx = links.indexOf(d);
        d3.select((linkGroup.selectAll('path.edge-vis').nodes() as Element[])[idx])
          .attr('stroke', 'rgba(167,139,250,0.7)')
          .attr('stroke-width', 2);
        const labelGrpNode = (linkGroup.selectAll('g.edge-label').nodes() as Element[])[idx];
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
      .on('mouseout', function(_ev, d: any) {
        const idx = links.indexOf(d);
        d3.select((linkGroup.selectAll('path.edge-vis').nodes() as Element[])[idx])
          .attr('stroke', (d: any) => isForward(d) ? '#1e2a3a' : 'rgba(167,139,250,0.35)')
          .attr('stroke-width', 1.5);
        const labelGrpNode = (linkGroup.selectAll('g.edge-label').nodes() as Element[])[idx];
        d3.select(labelGrpNode).select('text').attr('fill', '#7d8590');
        d3.select(labelGrpNode).select('rect').attr('opacity', 0.9);
        setEdgeTooltip(null);
      });

    // Edge action label (verb phrase) — sits slightly above the edge midpoint
    const edgeLabelGroup = linkGroup.selectAll('g.edge-label')
      .data(links).enter().append('g').attr('class', 'edge-label');
    edgeLabelGroup.attr('opacity', 0);

    edgeLabelGroup.append('rect')
      .attr('rx', 3).attr('fill', '#0a0e1a').attr('opacity', 0.9);

    edgeLabelGroup.append('text')
      .text((d: any) => truncateEdgeLabel(d.label))
      .attr('font-size', '0.5rem')
      .attr('fill', '#7d8590')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .style('pointer-events', 'none');

    // ── Node groups ───────────────────────────────────────────────────────────
    const nodeGroup = g.append('g');

    const nodeSel = nodeGroup.selectAll<SVGGElement, any>('g.node')
      .data(nodes).enter().append('g')
      .attr('class', 'node')
      .attr('opacity', 0)
      .style('cursor', 'pointer')
      .call(
        // Drag: move node, re-render all edges (no simulation needed)
        d3.drag<SVGGElement, any>()
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
      .on('click', (_event, d: any) => onNodeClickRef.current(d as GraphNode))
      .on('mouseover', function(_ev, d: any) {
        d3.select(this).select('.node-card')
          .attr('stroke-width', 2)
          .attr('filter', 'brightness(1.3)');
        // Reveal this node's outgoing loop edges (feedback arcs)
        const loopIdxs = loopIndicesBySource.get(d.id) ?? [];
        if (loopIdxs.length > 0) {
          const edgeVisNodes  = linkGroup.selectAll('path.edge-vis').nodes() as Element[];
          const edgeHitNodes  = linkGroup.selectAll('path.edge-hit').nodes() as Element[];
          const edgeLblNodes  = linkGroup.selectAll('g.edge-label').nodes() as Element[];
          loopIdxs.forEach(i => {
            d3.select(edgeVisNodes[i]).interrupt().transition().duration(150).attr('opacity', 1);
            d3.select(edgeHitNodes[i]).attr('opacity', 1).style('pointer-events', 'auto');
            d3.select(edgeLblNodes[i]).interrupt().transition().duration(150).attr('opacity', 1);
          });
        }
      })
      .on('mouseout', function(_ev, d: any) {
        d3.select(this).select('.node-card')
          .attr('stroke-width', 1.5)
          .attr('filter', null);
        // Hide loop edges again
        const loopIdxs = loopIndicesBySource.get(d.id) ?? [];
        if (loopIdxs.length > 0) {
          const edgeVisNodes  = linkGroup.selectAll('path.edge-vis').nodes() as Element[];
          const edgeHitNodes  = linkGroup.selectAll('path.edge-hit').nodes() as Element[];
          const edgeLblNodes  = linkGroup.selectAll('g.edge-label').nodes() as Element[];
          loopIdxs.forEach(i => {
            d3.select(edgeVisNodes[i]).interrupt().transition().duration(200).attr('opacity', 0);
            d3.select(edgeHitNodes[i]).attr('opacity', 0).style('pointer-events', 'none');
            d3.select(edgeLblNodes[i]).interrupt().transition().duration(200).attr('opacity', 0);
          });
        }
      });

    // Card background
    nodeSel.filter((d: any) => d.type !== 'decision')
      .append('rect')
      .attr('class', 'node-card')
      .attr('width', NODE_W).attr('height', NODE_H)
      .attr('x', -NODE_W / 2).attr('y', -NODE_H / 2)
      .attr('rx', NODE_RX).attr('ry', NODE_RX)
      .attr('fill',   (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).fill)
      .attr('stroke', (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke)
      .attr('stroke-width', 1.5);

    nodeSel.filter((d: any) => d.type === 'decision')
      .append('path')
      .attr('class', 'node-card')
      .attr('d', [
        `M 0 ${-NODE_H / 2}`,
        `L ${NODE_W / 2} 0`,
        `L 0 ${NODE_H / 2}`,
        `L ${-NODE_W / 2} 0`,
        'Z',
      ].join(' '))
      .attr('fill',   (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).fill)
      .attr('stroke', (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke)
      .attr('stroke-width', 1.5);

    // Left accent stripe
    nodeSel.filter((d: any) => d.type !== 'decision')
      .append('rect')
      .attr('x', -NODE_W / 2).attr('y', -NODE_H / 2 + NODE_RX)
      .attr('width', 3).attr('height', NODE_H - NODE_RX * 2)
      .attr('fill', (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).stroke);

    // Loading shimmer bar (visible while node detail is not yet enriched)
    nodeSel.append('rect')
      .attr('width', NODE_W - 32).attr('height', 2)
      .attr('x', -(NODE_W - 32) / 2).attr('y', NODE_H / 2 - 5)
      .attr('rx', 1)
      .attr('fill', 'rgba(167,139,250,0.3)')
      .attr('opacity', (d: any) => d.detail ? 0 : 0.7);

    // Row 1 — type badge (top-left)
    nodeSel.append('text')
      .text((d: any) => d.type.toUpperCase())
      .attr('x', -NODE_W / 2 + 12).attr('y', -NODE_H / 2 + 11)
      .attr('font-size', '0.44rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.07em')
      .attr('fill', (d: any) => (TYPE_STYLE[d.type] ?? FALLBACK_STYLE).badge)
      .style('pointer-events', 'none');

    // Row 1 — tier badge (top-right: PUB / PVT)
    nodeSel.filter((d: any) => d.tier)
      .append('text')
      .text((d: any) => d.tier === 'public' ? 'PUB' : 'PVT')
      .attr('x', NODE_W / 2 - 8).attr('y', -NODE_H / 2 + 11)
      .attr('text-anchor', 'end')
      .attr('font-size', '0.42rem').attr('font-weight', 700)
      .attr('letter-spacing', '0.06em')
      .attr('fill', (d: any) => d.tier === 'public' ? '#fbbf24' : '#6e7681')
      .style('pointer-events', 'none');

    // Row 2 — node label (centered, white, main title)
    // Max 24 chars — agent is constrained to ≤20 chars; this is a safety truncation only.
    nodeSel.append('text')
      .text((d: any) => d.label.length > 24 ? d.label.slice(0, 23) + '…' : d.label)
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
      .attr('y', 1)
      .attr('font-size', '0.76rem').attr('font-weight', 500)
      .attr('fill', '#e6edf3')
      .style('pointer-events', 'none');

    // Row 3 — technology subtitle (centered, muted)
    // Max 28 chars — agent is constrained to ≤25 chars; this is a safety truncation only.
    nodeSel.filter((d: any) => d.technology)
      .append('text')
      .text((d: any) => {
        const t = d.technology || '';
        return t.length > 28 ? t.slice(0, 27) + '…' : t;
      })
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
      .attr('y', 15)
      .attr('font-size', '0.52rem')
      .attr('fill', '#6e7681')
      .style('pointer-events', 'none');

    // ── Entry / Exit markers ──────────────────────────────────────────────────
    const MARKER_W = 12, MARKER_H = 8, MARKER_GAP = 6;

    // ENTRY — blue right-pointing triangle on left edge
    nodeSel.filter((d: any) => sourceNodeIds.has(d.id))
      .append('polygon')
      .attr('points', [
        `${-NODE_W / 2 - MARKER_GAP - MARKER_W},${-MARKER_H / 2}`,
        `${-NODE_W / 2 - MARKER_GAP},0`,
        `${-NODE_W / 2 - MARKER_GAP - MARKER_W},${MARKER_H / 2}`,
      ].join(' '))
      .attr('fill', '#60a5fa').attr('opacity', 0.85).style('pointer-events', 'none');

    nodeSel.filter((d: any) => sourceNodeIds.has(d.id))
      .append('text').text('ENTRY')
      .attr('x', -NODE_W / 2 - MARKER_GAP - MARKER_W / 2)
      .attr('y', -MARKER_H / 2 - 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '0.38rem').attr('font-weight', 700).attr('letter-spacing', '0.1em')
      .attr('fill', '#60a5fa').attr('opacity', 0.9).style('pointer-events', 'none');

    // EXIT — slate right-pointing triangle on right edge
    nodeSel.filter((d: any) => sinkNodeIds.has(d.id))
      .append('polygon')
      .attr('points', [
        `${NODE_W / 2 + MARKER_GAP},${-MARKER_H / 2}`,
        `${NODE_W / 2 + MARKER_GAP + MARKER_W},0`,
        `${NODE_W / 2 + MARKER_GAP},${MARKER_H / 2}`,
      ].join(' '))
      .attr('fill', '#94a3b8').attr('opacity', 0.85).style('pointer-events', 'none');

    nodeSel.filter((d: any) => sinkNodeIds.has(d.id))
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

    stepBadgeGroup.filter((d: any) => d.stepNum !== null).append('circle')
      .attr('r', 9)
      .attr('fill', '#0d1117')
      .attr('stroke', 'rgba(167,139,250,0.55)')
      .attr('stroke-width', 1.2);

    stepBadgeGroup.filter((d: any) => d.stepNum !== null).append('text')
      .text((d: any) => String(d.stepNum))
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('font-size', '0.48rem')
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
      nodeSel.attr('transform', (d: any) => `translate(${d.x},${d.y})`);

      // Position step badges at exact edge midpoint
      stepBadgeGroup.attr('transform', (d: any) => `translate(${midX(d)},${midY(d)})`);

      // Refit group bounding boxes to wrap their member nodes
      for (const { grp: groupDef, grpEl, rect } of groupEls) {
        const memberNodes = groupDef.nodeIds
          .map(id => nodeById[id])
          .filter((n): n is any => n?.x != null && n?.y != null);
        if (memberNodes.length === 0) continue;

        const PX = 24, PT = 28, PB = 18;
        const minX = Math.min(...memberNodes.map((n: any) => n.x)) - NODE_W / 2 - PX;
        const maxX = Math.max(...memberNodes.map((n: any) => n.x)) + NODE_W / 2 + PX;
        const minY = Math.min(...memberNodes.map((n: any) => n.y)) - NODE_H / 2 - PT;
        const maxY = Math.max(...memberNodes.map((n: any) => n.y)) + NODE_H / 2 + PB;

        rect.attr('x', minX).attr('y', minY)
            .attr('width', maxX - minX).attr('height', maxY - minY);
        grpEl.select('text').attr('x', minX + 10).attr('y', minY + 14);
      }

      const occupiedBoxes = nodes.map((node: any) => ({
        x: node.x - NODE_W / 2 - 14,
        y: node.y - NODE_H / 2 - 14,
        width: NODE_W + 28,
        height: NODE_H + 28,
      }));
      const placedLabels: Array<{ x: number; y: number; width: number; height: number }> = [];

      edgeLabelGroup.each(function(d: any) {
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
        const baseY = midY(d) - (d.stepNum !== null ? 20 : isForward(d) ? 12 : 20);
        let x = midX(d);
        let y = baseY;
        let attempts = 0;

        while (attempts < 12) {
          const candidate = {
            x: x - labelWidth / 2,
            y: y - labelHeight / 2,
            width: labelWidth,
            height: labelHeight,
          };
          const collides = occupiedBoxes.some((box) => boxesIntersect(candidate, box))
            || placedLabels.some((box) => boxesIntersect(candidate, box));
          if (!collides) {
            placedLabels.push(candidate);
            break;
          }
          const direction = attempts % 2 === 0 ? -1 : 1;
          const distance = isForward(d) ? 14 + Math.floor(attempts / 2) * 6 : 18 + Math.floor(attempts / 2) * 7;
          y = baseY + direction * distance;
          attempts += 1;
        }

        grp.attr('transform', `translate(${x},${y})`);
      });
    }

    // Initial render — static layout, no animation delay
    renderAll();

    // ── Auto-fit: zoom to show the full diagram on first render ───────────────
    // Scale down to fit (never scale up — max 1.0), centre horizontally,
    // add a small top margin so return arcs (which arc above y=0) are visible.
    const FIT_PADDING = 32;
    const fitScale = Math.min(
      1.0,
      (width  - 2 * FIT_PADDING) / layoutW,
      (height - 2 * FIT_PADDING) / layoutH,
    );
    // Clamp fitTx so the leftmost node is never off-screen.
    // When height is the limiting dimension, (width - layoutW*fitScale)/2 can go
    // negative, sliding the entire graph behind the left edge of the container.
    const fitTx = Math.max(FIT_PADDING, (width  - layoutW * fitScale) / 2);
    const fitTy = Math.max(FIT_PADDING, (height - layoutH * fitScale) / 2);
    const initialTransform = initialViewState?.viewport
      ? d3.zoomIdentity
          .translate(initialViewState.viewport.x, initialViewState.viewport.y)
          .scale(initialViewState.viewport.k)
      : d3.zoomIdentity.translate(fitTx, fitTy).scale(fitScale);
    svg.call((zoomBehavior.transform as any), initialTransform);

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
  }, [structureKey]);

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
      .attr('opacity', (d: any) => {
        if (showAll) return 1;
        const firstStep = nodeFirstStep.get(d.id) ?? 1;
        if (firstStep > activeStepNumber) return 0;
        if (activeNodeIds.has(d.id)) return 1;
        return 0.38;
      });

    // Loop edges are hover-controlled — exclude them from sequence animation entirely.
    link.filter((d: any) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: any) => {
        if (showAll) return 1;
        if (d.stepNum === null) return 0.22;
        if (d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0.34;
      })
      .attr('stroke-width', (d: any) => (
        !showAll && d.stepNum === activeStepNumber ? 2.3 : 1.5
      ))
      .attr('stroke', (d: any) => {
        if (!showAll && d.stepNum === activeStepNumber) {
          return isForward(d) ? '#8bb5ff' : 'rgba(167,139,250,0.92)';
        }
        return isForward(d) ? '#1e2a3a' : 'rgba(167,139,250,0.35)';
      });

    linkHit.filter((d: any) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: any) => {
        if (showAll) return 1;
        if (d.stepNum === null) return 0.22;
        return d.stepNum > activeStepNumber ? 0 : 1;
      });

    edgeLabelGroup.filter((d: any) => d.edgeType !== 'loop')
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: any) => {
        if (showAll) return 1;
        if (d.stepNum === null) return 0.28;
        if (d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0.42;
      });

    stepBadgeGroup
      .interrupt()
      .transition()
      .duration(200)
      .attr('opacity', (d: any) => {
        if (showAll) return d.stepNum === null ? 0 : 1;
        if (d.stepNum === null || d.stepNum > activeStepNumber) return 0;
        return d.stepNum === activeStepNumber ? 1 : 0.4;
      });
  }, [activeNodeIds, currentStep]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* overflow:visible allows return-edge arcs to arc above the SVG viewport */}
      <svg
        ref={svgRef}
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
