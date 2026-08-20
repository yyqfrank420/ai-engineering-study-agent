import { render, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { GraphData, GraphEdge, GraphNode } from '../../types';
import { D3Graph } from './D3Graph';
import { modelServingPaidCandidate } from './__fixtures__/modelServingPaidCandidate';
import {
  BOTTOM_NODE_GAP,
  MAX_PUBLISHED_GRAPH_NODES,
  MIN_PUBLISHED_TITLE_PX,
  NODE_H,
  NODE_TITLE_PX,
  NODE_W,
} from './graphLayout';


const LEGACY_VIEWPORT = { width: 760, height: 500 };
const DEEP_VIEWPORT = { width: 656, height: 848 };
const PUBLICATION_VIEWPORT = { width: 1440, height: 960 };
const MIN_LEGACY_TITLE_PX = 6;
let viewport = LEGACY_VIEWPORT;

const originalGetBBox = SVGGraphicsElement.prototype.getBBox;
const originalElementGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, 'getBBox');
const originalWidth = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'width');
const originalHeight = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'height');
const originalClientWidth = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'clientWidth');
const originalClientHeight = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'clientHeight');

beforeAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 96, height: 12 }),
  });
  Object.defineProperty(SVGElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 96, height: 12 }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'width', {
    configurable: true,
    get: () => ({ baseVal: { value: viewport.width } }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'height', {
    configurable: true,
    get: () => ({ baseVal: { value: viewport.height } }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => viewport.width,
  });
  Object.defineProperty(SVGSVGElement.prototype, 'clientHeight', {
    configurable: true,
    get: () => viewport.height,
  });
});

beforeEach(() => {
  viewport = LEGACY_VIEWPORT;
});

afterAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true,
    value: originalGetBBox,
  });
  if (originalElementGetBBox) Object.defineProperty(SVGElement.prototype, 'getBBox', originalElementGetBBox);
  else delete (SVGElement.prototype as unknown as { getBBox?: unknown }).getBBox;
  if (originalWidth) Object.defineProperty(SVGSVGElement.prototype, 'width', originalWidth);
  else delete (SVGSVGElement.prototype as unknown as { width?: unknown }).width;
  if (originalHeight) Object.defineProperty(SVGSVGElement.prototype, 'height', originalHeight);
  else delete (SVGSVGElement.prototype as unknown as { height?: unknown }).height;
  if (originalClientWidth) {
    Object.defineProperty(SVGSVGElement.prototype, 'clientWidth', originalClientWidth);
  } else {
    delete (SVGSVGElement.prototype as unknown as { clientWidth?: unknown }).clientWidth;
  }
  if (originalClientHeight) {
    Object.defineProperty(SVGSVGElement.prototype, 'clientHeight', originalClientHeight);
  } else {
    delete (SVGSVGElement.prototype as unknown as { clientHeight?: unknown }).clientHeight;
  }
});

function node(
  id: string,
  label: string,
  type: GraphNode['type'] = 'service',
  lane: GraphNode['lane'] = 'main',
): GraphNode {
  return {
    id,
    label,
    type,
    lane,
    tier: type === 'client' ? 'public' : 'private',
    technology: 'Versioned domain capability',
    description: `${label} owns one bounded high-assurance responsibility.`,
    detail: null,
    design_origin: 'applied',
  };
}

function edge(
  source: string,
  target: string,
  label: string,
  flow: NonNullable<GraphEdge['flow']> = 'runtime',
  type?: GraphEdge['type'],
): GraphEdge {
  return {
    source,
    target,
    label,
    flow,
    type,
    technology: flow === 'control' ? 'Typed policy command' : 'Versioned domain event',
    sync: flow === 'runtime' ? 'sync' : 'async',
    description: `${label} from ${source} to ${target}.`,
  };
}

const capacityGraph: GraphData = {
  graph_type: 'architecture',
  design_origin: 'applied',
  title: 'High-Assurance External Action Control and Release Loop',
  nodes: [
    node('request_intake', 'Request Intake', 'client'),
    node('identity_boundary', 'Identity Boundary', 'gateway'),
    node('evidence_context', 'Evidence Context'),
    node('action_planner', 'Action Planner'),
    node('proposal_validator', 'Proposal Validator', 'decision'),
    node('risk_policy', 'Risk Policy', 'decision'),
    node('approval_console', 'Approval Console', 'control'),
    node('lifecycle_ledger', 'Lifecycle Ledger', 'datastore'),
    node('effect_executor', 'Effect Executor', 'gateway'),
    node('authoritative_target', 'Authoritative Target', 'external'),
    node('outcome_reconciler', 'Outcome Reconciler'),
    node('audit_evidence', 'Audit Evidence', 'datastore', 'bottom'),
    node('release_controller', 'Release Controller', 'control', 'bottom'),
  ],
  edges: [
    edge('request_intake', 'identity_boundary', 'submits signed request'),
    edge('identity_boundary', 'evidence_context', 'passes authorized scope'),
    edge('evidence_context', 'action_planner', 'supplies bounded evidence'),
    edge('action_planner', 'proposal_validator', 'submits typed proposal'),
    edge('proposal_validator', 'risk_policy', 'passes valid proposal', 'control'),
    edge('risk_policy', 'approval_console', 'escalates governed action', 'control'),
    edge('approval_console', 'lifecycle_ledger', 'reserves approved envelope', 'control'),
    edge('lifecycle_ledger', 'effect_executor', 'leases reserved operation', 'control'),
    edge('effect_executor', 'authoritative_target', 'executes idempotent action'),
    edge('authoritative_target', 'outcome_reconciler', 'returns authoritative status'),
    edge('outcome_reconciler', 'lifecycle_ledger', 'records reconciled state', 'feedback'),
    edge('outcome_reconciler', 'request_intake', 'returns measured outcome', 'feedback', 'loop'),
    edge('identity_boundary', 'audit_evidence', 'records denied identity', 'control'),
    edge('evidence_context', 'audit_evidence', 'records evidence provenance', 'control'),
    edge('action_planner', 'audit_evidence', 'records proposal lineage', 'control'),
    edge('proposal_validator', 'action_planner', 'requests bounded repair', 'control'),
    edge('proposal_validator', 'audit_evidence', 'records invalid proposal', 'control'),
    edge('risk_policy', 'lifecycle_ledger', 'reserves automatic envelope', 'control'),
    edge('risk_policy', 'audit_evidence', 'records policy rejection', 'control'),
    edge('approval_console', 'audit_evidence', 'records human rejection', 'control'),
    edge('lifecycle_ledger', 'audit_evidence', 'records durable reservation', 'control'),
    edge('effect_executor', 'audit_evidence', 'records execution attempt', 'control'),
    edge('authoritative_target', 'audit_evidence', 'records target receipt', 'control'),
    edge('outcome_reconciler', 'effect_executor', 'retries same operation key', 'control'),
    edge('outcome_reconciler', 'audit_evidence', 'escalates unknown outcome', 'control'),
    edge('audit_evidence', 'release_controller', 'submits curated evaluation set', 'deployment'),
    edge('release_controller', 'action_planner', 'promotes evaluated release', 'deployment'),
    edge('release_controller', 'action_planner', 'rolls back failed release', 'deployment'),
    edge('release_controller', 'audit_evidence', 'records release outcome', 'deployment'),
  ],
  groups: [
    { id: 'intake', label: 'Identity & Evidence', kind: 'runtime', nodeIds: ['request_intake', 'identity_boundary', 'evidence_context'] },
    { id: 'decision', label: 'Decision & Governance', kind: 'runtime', nodeIds: ['action_planner', 'proposal_validator', 'risk_policy', 'approval_console'] },
    { id: 'effect', label: 'Durable Effect Boundary', kind: 'delivery', nodeIds: ['lifecycle_ledger', 'effect_executor', 'authoritative_target', 'outcome_reconciler'] },
    { id: 'operations', label: 'Audit & Release', kind: 'operations', nodeIds: ['audit_evidence', 'release_controller'] },
  ],
  sequence: [
    { step: 1, nodes: ['request_intake', 'identity_boundary'], description: 'Authorize the request.' },
    { step: 2, nodes: ['evidence_context', 'action_planner'], description: 'Build a bounded proposal.' },
    { step: 3, nodes: ['proposal_validator', 'risk_policy'], description: 'Validate and classify risk.' },
    { step: 4, nodes: ['approval_console', 'lifecycle_ledger'], description: 'Approve and reserve.' },
    { step: 5, nodes: ['effect_executor', 'authoritative_target'], description: 'Execute at the target.' },
    { step: 6, nodes: ['outcome_reconciler'], description: 'Reconcile the outcome.' },
    { step: 7, nodes: ['audit_evidence', 'release_controller'], description: 'Evaluate and release.' },
  ],
};

const DEEP_LEVEL_SIZES = [3, 2, 3, 3, 1, 5, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1];

function deepCapacityGraph(
  levelSizes = DEEP_LEVEL_SIZES,
  edgeCount = 65,
): GraphData {
  const levelNodeIds = levelSizes.map((size, level) => (
    Array.from({ length: size }, (_, index) => `level_${level + 1}_node_${index + 1}`)
  ));
  const nodeIds = levelNodeIds.flat();
  const generatedNodes = nodeIds.map((id, index) => node(
    id,
    `Owned Capability ${index + 1}`,
    index % 11 === 0 ? 'decision' : 'service',
    index >= Math.floor(nodeIds.length * 0.8) ? 'bottom' : 'main',
  ));
  const generatedEdges = levelNodeIds.slice(1).flatMap((ids, levelIndex) => (
    ids.map((target, index) => edge(
      levelNodeIds[levelIndex][index % levelNodeIds[levelIndex].length],
      target,
      `advances stage ${levelIndex + 2}`,
    ))
  ));
  for (let index = 0; generatedEdges.length < edgeCount; index += 1) {
    const source = nodeIds[nodeIds.length - 1 - (index % 12)];
    const target = nodeIds[index % 12];
    generatedEdges.push(edge(source, target, `reports outcome ${index + 1}`, 'feedback', 'loop'));
  }
  const groups = Array.from({ length: 18 }, (_, groupIndex) => ({
    id: `zone_${groupIndex + 1}`,
    label: `Responsibility Zone ${groupIndex + 1}`,
    kind: groupIndex >= 14 ? 'operations' as const : 'runtime' as const,
    nodeIds: nodeIds.filter((_id, nodeIndex) => (
      Math.floor(nodeIndex * 18 / nodeIds.length) === groupIndex
    )),
  }));

  return {
    graph_type: 'architecture',
    design_origin: 'applied',
    title: 'Deep production architecture capacity regression',
    nodes: generatedNodes,
    edges: generatedEdges,
    groups,
    sequence: levelNodeIds.map((ids, index) => ({
      step: index + 1,
      nodes: ids,
      description: `Complete stage ${index + 1}.`,
    })),
  };
}

function parseTransform(value: string | null): { x: number; y: number; scale: number } {
  const match = value?.match(/translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/);
  if (!match) throw new Error(`Unexpected graph transform: ${value}`);
  return { x: Number(match[1]), y: Number(match[2]), scale: Number(match[3]) };
}

function parsePosition(value: string | null): { x: number; y: number } {
  const match = value?.match(/translate\(([-\d.]+),([-\d.]+)\)/);
  if (!match) throw new Error(`Unexpected node transform: ${value}`);
  return { x: Number(match[1]), y: Number(match[2]) };
}

function pathControlPoints(value: string | null): Array<{ x: number; y: number }> {
  if (!value) return [];
  return Array.from(value.matchAll(/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g), match => ({
    x: Number(match[1]),
    y: Number(match[2]),
  }));
}

function segmentIntersectsNode(
  start: { x: number; y: number },
  end: { x: number; y: number },
  center: { x: number; y: number },
): boolean {
  const left = center.x - NODE_W / 2;
  const right = center.x + NODE_W / 2;
  const top = center.y - NODE_H / 2;
  const bottom = center.y + NODE_H / 2;
  if (start.x === end.x) {
    return start.x > left && start.x < right
      && Math.max(start.y, end.y) > top
      && Math.min(start.y, end.y) < bottom;
  }
  if (start.y === end.y) {
    return start.y > top && start.y < bottom
      && Math.max(start.x, end.x) > left
      && Math.min(start.x, end.x) < right;
  }
  return false;
}

describe('dense production graph rendering', () => {
  it('renders a realistic 13-node/29-edge control topology at publication readability', () => {
    expect(capacityGraph.nodes).toHaveLength(13);
    expect(capacityGraph.edges).toHaveLength(29);

    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={capacityGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const svg = container.querySelector('svg');
    const viewportGroup = svg?.querySelector(':scope > g');
    const transform = parseTransform(viewportGroup?.getAttribute('transform') ?? null);
    const nodes = Array.from(container.querySelectorAll<SVGGElement>('g.node'));
    const paths = Array.from(container.querySelectorAll<SVGPathElement>('path.edge-vis'));

    expect(nodes).toHaveLength(13);
    expect(paths).toHaveLength(29);
    expect(paths.every(path => Boolean(path.getAttribute('d')))).toBe(true);
    expect(new Set(paths.map(path => path.getAttribute('d'))).size).toBe(paths.length);
    expect(container.querySelectorAll('text.node-group-label')).toHaveLength(13);
    expect(nodes.every(node => Number(node.getAttribute('opacity')) === 1)).toBe(true);
    expect(paths.every(path => Number(path.getAttribute('opacity')) > 0)).toBe(true);
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_LEGACY_TITLE_PX);

    for (const renderedNode of nodes) {
      const position = parsePosition(renderedNode.getAttribute('transform'));
      const left = transform.x + transform.scale * (position.x - NODE_W / 2);
      const right = transform.x + transform.scale * (position.x + NODE_W / 2);
      const top = transform.y + transform.scale * (position.y - NODE_H / 2);
      const bottom = transform.y + transform.scale * (position.y + NODE_H / 2);
      expect(left).toBeGreaterThanOrEqual(0);
      expect(right).toBeLessThanOrEqual(viewport.width);
      expect(top).toBeGreaterThanOrEqual(0);
      expect(bottom).toBeLessThanOrEqual(viewport.height);
    }

    for (const path of paths) {
      const controlPoints = pathControlPoints(path.getAttribute('d'));
      expect(controlPoints.length).toBeGreaterThanOrEqual(2);
      for (const point of controlPoints) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
    }

    const overviewLabels = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
    );
    expect(overviewLabels.length).toBeGreaterThan(0);
    expect(overviewLabels.length).toBeLessThanOrEqual(8);
    expect(overviewLabels.every(label => Number(label.getAttribute('opacity')) > 0)).toBe(true);

    const nodeMarkers = Array.from(container.querySelectorAll('g.node text'))
      .map(marker => marker.textContent);
    expect(nodeMarkers).toContain('ENTRY');
    expect(nodeMarkers).toContain('OUTCOME');
  });

  it('keeps the paid model-serving candidate readable, non-overlapping, and in frame', () => {
    viewport = PUBLICATION_VIEWPORT;
    expect(modelServingPaidCandidate.nodes).toHaveLength(10);
    expect(modelServingPaidCandidate.edges).toHaveLength(15);

    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={modelServingPaidCandidate}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const transform = parseTransform(
      container.querySelector('svg > g')?.getAttribute('transform') ?? null,
    );
    const renderedNodes = Array.from(container.querySelectorAll<SVGGElement>('g.node'));
    const paths = Array.from(container.querySelectorAll<SVGPathElement>('path.edge-vis'));
    const positions = renderedNodes.map(renderedNode => (
      parsePosition(renderedNode.getAttribute('transform'))
    ));

    expect(renderedNodes).toHaveLength(10);
    expect(paths).toHaveLength(15);
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);

    for (let left = 0; left < positions.length; left += 1) {
      for (let right = left + 1; right < positions.length; right += 1) {
        const horizontalOverlap = Math.abs(positions[left].x - positions[right].x) < NODE_W;
        const verticalOverlap = Math.abs(positions[left].y - positions[right].y) < NODE_H;
        expect(horizontalOverlap && verticalOverlap).toBe(false);
      }
    }

    for (const position of positions) {
      expect(transform.x + transform.scale * (position.x - NODE_W / 2)).toBeGreaterThanOrEqual(0);
      expect(transform.x + transform.scale * (position.x + NODE_W / 2)).toBeLessThanOrEqual(viewport.width);
      expect(transform.y + transform.scale * (position.y - NODE_H / 2)).toBeGreaterThanOrEqual(0);
      expect(transform.y + transform.scale * (position.y + NODE_H / 2)).toBeLessThanOrEqual(viewport.height);
    }

    for (const path of paths) {
      const points = pathControlPoints(path.getAttribute('d'));
      expect(points.length).toBeGreaterThanOrEqual(2);
      for (const point of points) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
    }
  });

  it('routes a horizontal skip edge around unrelated middle-column cards', () => {
    viewport = PUBLICATION_VIEWPORT;
    const graph: GraphData = {
      graph_type: 'architecture',
      design_origin: 'applied',
      title: 'Horizontal skip route',
      nodes: [
        node('a', 'Source', 'client'),
        node('b', 'Upper worker'),
        node('c', 'Middle worker'),
        node('e', 'Lower worker'),
        node('d', 'Outcome', 'external'),
      ],
      edges: [
        edge('a', 'b', 'dispatches upper work'),
        edge('a', 'c', 'dispatches middle work'),
        edge('a', 'e', 'dispatches lower work'),
        edge('b', 'd', 'returns upper result'),
        edge('a', 'd', 'sends direct result'),
      ],
      groups: [{
        id: 'runtime',
        label: 'Runtime',
        kind: 'runtime',
        nodeIds: ['a', 'b', 'c', 'e', 'd'],
      }],
      sequence: [],
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const positions = new Map(
      Array.from(container.querySelectorAll<SVGGElement>('g.node')).map(renderedNode => [
        renderedNode.getAttribute('data-node-id') ?? '',
        parsePosition(renderedNode.getAttribute('transform')),
      ]),
    );
    const skipPath = container.querySelector<SVGPathElement>(
      'path.edge-vis[data-source-id="a"][data-target-id="d"]',
    );
    const points = pathControlPoints(skipPath?.getAttribute('d') ?? null);

    expect(points.length).toBeGreaterThanOrEqual(6);
    for (const [nodeId, position] of positions) {
      if (nodeId === 'a' || nodeId === 'd') continue;
      for (let index = 1; index < points.length; index += 1) {
        expect(segmentIntersectsNode(points[index - 1], points[index], position)).toBe(false);
      }
    }
  });

  it('routes vertical edges around wrapped cards in an adjacent rank', () => {
    viewport = PUBLICATION_VIEWPORT;
    const rankOne = Array.from({ length: 10 }, (_, index) => (
      node(`worker_${index}`, index === 0 ? 'Anchor worker' : `Worker ${index}`)
    ));
    const rankTwo = Array.from({ length: 6 }, (_, index) => (
      node(`outcome_${index}`, `Outcome ${index}`, 'external')
    ));
    const graph: GraphData = {
      graph_type: 'architecture',
      design_origin: 'applied',
      title: 'Wrapped adjacent ranks',
      nodes: [node('root', 'Root', 'client'), ...rankOne, ...rankTwo],
      edges: [
        ...rankOne.map(worker => edge('root', worker.id, `starts ${worker.id}`)),
        ...rankTwo.map(outcome => edge('worker_0', outcome.id, `produces ${outcome.id}`)),
      ],
      groups: [{
        id: 'runtime',
        label: 'Runtime',
        kind: 'runtime',
        nodeIds: ['root', ...rankOne.map(worker => worker.id), ...rankTwo.map(outcome => outcome.id)],
      }],
      sequence: [],
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const positions = new Map(
      Array.from(container.querySelectorAll<SVGGElement>('g.node')).map(renderedNode => [
        renderedNode.getAttribute('data-node-id') ?? '',
        parsePosition(renderedNode.getAttribute('transform')),
      ]),
    );
    const path = container.querySelector<SVGPathElement>(
      'path.edge-vis[data-source-id="worker_0"][data-target-id="outcome_0"]',
    );
    const points = pathControlPoints(path?.getAttribute('d') ?? null);

    expect(points.length).toBeGreaterThanOrEqual(6);
    for (const [nodeId, position] of positions) {
      if (nodeId === 'worker_0' || nodeId === 'outcome_0') continue;
      for (let index = 1; index < points.length; index += 1) {
        expect(segmentIntersectsNode(points[index - 1], points[index], position)).toBe(false);
      }
    }
  });

  it('reserves a full card and gap for bottom nodes in the same column', () => {
    const graph: GraphData = {
      graph_type: 'architecture',
      design_origin: 'applied',
      title: 'Bottom band boundary',
      nodes: [
        node('source', 'Source', 'client'),
        node('main', 'Main capability'),
        node('audit_one', 'Audit one', 'datastore', 'bottom'),
        node('audit_two', 'Audit two', 'datastore', 'bottom'),
      ],
      edges: [
        edge('source', 'main', 'starts work'),
        edge('source', 'audit_one', 'records one'),
        edge('source', 'audit_two', 'records two'),
      ],
      groups: [],
      sequence: [],
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const bottomPositions = ['audit_one', 'audit_two'].map((nodeId) => {
      const renderedNode = container.querySelector<SVGGElement>(`g.node[data-node-id="${nodeId}"]`);
      return parsePosition(renderedNode?.getAttribute('transform') ?? null);
    });

    expect(bottomPositions[0].x).toBe(bottomPositions[1].x);
    expect(Math.abs(bottomPositions[0].y - bottomPositions[1].y))
      .toBeGreaterThanOrEqual(NODE_H + BOTTOM_NODE_GAP);
  });

  it('keeps a 39-node, 65-edge deep architecture readable in the live viewport', () => {
    viewport = DEEP_VIEWPORT;
    const graph = deepCapacityGraph();
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const viewportGroup = container.querySelector('svg > g');
    const transform = parseTransform(viewportGroup?.getAttribute('transform') ?? null);
    const nodes = Array.from(container.querySelectorAll<SVGGElement>('g.node'));
    const paths = Array.from(container.querySelectorAll<SVGPathElement>('path.edge-vis'));
    const positions = nodes.map(renderedNode => parsePosition(renderedNode.getAttribute('transform')));

    expect(nodes).toHaveLength(39);
    expect(paths).toHaveLength(65);
    expect(container.querySelectorAll('text.node-group-label')).toHaveLength(39);
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_LEGACY_TITLE_PX);
    expect(nodes.every(renderedNode => Number(renderedNode.getAttribute('opacity')) === 1)).toBe(true);
    expect(paths.every(path => Boolean(path.getAttribute('d')))).toBe(true);

    for (let left = 0; left < positions.length; left += 1) {
      for (let right = left + 1; right < positions.length; right += 1) {
        const horizontalOverlap = Math.abs(positions[left].x - positions[right].x) < NODE_W;
        const verticalOverlap = Math.abs(positions[left].y - positions[right].y) < NODE_H;
        expect(horizontalOverlap && verticalOverlap).toBe(false);
      }
    }

    for (const position of positions) {
      expect(transform.x + transform.scale * (position.x - NODE_W / 2)).toBeGreaterThanOrEqual(0);
      expect(transform.x + transform.scale * (position.x + NODE_W / 2)).toBeLessThanOrEqual(viewport.width);
      expect(transform.y + transform.scale * (position.y - NODE_H / 2)).toBeGreaterThanOrEqual(0);
      expect(transform.y + transform.scale * (position.y + NODE_H / 2)).toBeLessThanOrEqual(viewport.height);
    }

    for (const path of paths) {
      const controlPoints = pathControlPoints(path.getAttribute('d'));
      expect(controlPoints.length).toBeGreaterThanOrEqual(2);
      for (const point of controlPoints) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
    }

    const requiredLabels = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
    );
    expect(requiredLabels).toHaveLength(8);
    expect(requiredLabels.every(label => Number(label.getAttribute('opacity')) > 0)).toBe(true);
  });

  it('publishes a 42-node architecture with readable routed tracks', () => {
    viewport = PUBLICATION_VIEWPORT;
    const graph = deepCapacityGraph(
      [1, 5, 4, 1, 3, 1, 2, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 2, 3, 3, 1, 2, 2],
      62,
    );
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const transform = parseTransform(
      container.querySelector('svg > g')?.getAttribute('transform') ?? null,
    );
    const nodes = Array.from(container.querySelectorAll<SVGGElement>('g.node'));
    const paths = Array.from(container.querySelectorAll<SVGPathElement>('path.edge-vis'));
    const positions = new Map(nodes.map(renderedNode => [
      renderedNode.getAttribute('data-node-id'),
      parsePosition(renderedNode.getAttribute('transform')),
    ]));

    expect(graph.nodes).toHaveLength(42);
    expect(graph.edges).toHaveLength(62);
    expect(nodes).toHaveLength(42);
    expect(paths).toHaveLength(62);
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(12);
    expect(new Set(Array.from(positions.values(), position => position.x)).size).toBeGreaterThan(5);

    const positionedNodes = [...positions.values()];
    for (let left = 0; left < positionedNodes.length; left += 1) {
      for (let right = left + 1; right < positionedNodes.length; right += 1) {
        const horizontalOverlap = Math.abs(positionedNodes[left].x - positionedNodes[right].x) < NODE_W;
        const verticalOverlap = Math.abs(positionedNodes[left].y - positionedNodes[right].y) < NODE_H;
        expect(horizontalOverlap && verticalOverlap).toBe(false);
      }
    }

    for (const path of paths) {
      const points = pathControlPoints(path.getAttribute('d'));
      for (const point of points) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
      if (points.length < 5 || path.getAttribute('d')?.includes('C')) continue;
      const sourceId = path.getAttribute('data-source-id');
      const targetId = path.getAttribute('data-target-id');
      for (const [nodeId, position] of positions) {
        if (nodeId === sourceId || nodeId === targetId) continue;
        for (let index = 1; index < points.length; index += 1) {
          expect(segmentIntersectsNode(points[index - 1], points[index], position)).toBe(false);
        }
      }
    }

  });

  it('renders the 60-node schema boundary through the compact fallback', () => {
    viewport = PUBLICATION_VIEWPORT;
    const generated = deepCapacityGraph(
      Array.from({ length: 10 }, () => [1, 5]).flat(),
      80,
    );
    const bottomIds = new Set(generated.nodes.slice(-6).map(graphNode => graphNode.id));
    const graph: GraphData = {
      ...generated,
      nodes: generated.nodes.map(graphNode => (
        bottomIds.has(graphNode.id) ? { ...graphNode, lane: 'bottom' as const } : graphNode
      )),
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const transform = parseTransform(
      container.querySelector('svg > g')?.getAttribute('transform') ?? null,
    );
    const renderedNodes = Array.from(container.querySelectorAll<SVGGElement>('g.node'));
    const positions = new Map(renderedNodes.map(renderedNode => [
      renderedNode.getAttribute('data-node-id') ?? '',
      parsePosition(renderedNode.getAttribute('transform')),
    ]));
    const paths = Array.from(container.querySelectorAll<SVGPathElement>('path.edge-vis'));

    expect(renderedNodes).toHaveLength(MAX_PUBLISHED_GRAPH_NODES);
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);
    const positionedNodes = [...positions.values()];
    for (let left = 0; left < positionedNodes.length; left += 1) {
      for (let right = left + 1; right < positionedNodes.length; right += 1) {
        const horizontalOverlap = Math.abs(positionedNodes[left].x - positionedNodes[right].x) < NODE_W;
        const verticalOverlap = Math.abs(positionedNodes[left].y - positionedNodes[right].y) < NODE_H;
        expect(horizontalOverlap && verticalOverlap).toBe(false);
      }
    }

    const mainPositions = graph.nodes
      .filter(graphNode => graphNode.lane !== 'bottom')
      .map(graphNode => positions.get(graphNode.id));
    const bottomPositions = graph.nodes
      .filter(graphNode => graphNode.lane === 'bottom')
      .map(graphNode => positions.get(graphNode.id));
    expect(mainPositions).not.toHaveLength(0);
    expect(bottomPositions).not.toHaveLength(0);
    expect(Math.min(...bottomPositions.map(position => position?.y ?? -Infinity)))
      .toBeGreaterThanOrEqual(
        Math.max(...mainPositions.map(position => position?.y ?? Infinity))
          + NODE_H
          + BOTTOM_NODE_GAP,
      );

    for (const path of paths) {
      const points = pathControlPoints(path.getAttribute('d'));
      for (const point of points) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
      const sourceId = path.getAttribute('data-source-id');
      const targetId = path.getAttribute('data-target-id');
      for (const [nodeId, position] of positions) {
        if (nodeId === sourceId || nodeId === targetId) continue;
        for (let index = 1; index < points.length; index += 1) {
          expect(segmentIntersectsNode(points[index - 1], points[index], position)).toBe(false);
        }
      }
    }

    const sameRowSkipPath = container.querySelector<SVGPathElement>(
      'path.edge-vis[data-source-id="level_1_node_1"][data-target-id="level_2_node_5"]',
    );
    const sameRowSkipPoints = pathControlPoints(sameRowSkipPath?.getAttribute('d') ?? null);
    expect(sameRowSkipPoints).toHaveLength(4);
    expect(sameRowSkipPoints[0].y).not.toBe(sameRowSkipPoints[1].y);
  });

  it('keeps required labels inside the frame for a live-shaped multi-track graph', () => {
    viewport = PUBLICATION_VIEWPORT;
    const generated = deepCapacityGraph(
      [4, 3, 5, 3, 1, 2, 2, 1, 1, 1, 2, 3, 2, 1, 1, 1, 1],
      64,
    );
    const graph = {
      ...generated,
      edges: generated.edges.map((generatedEdge, index) => (
        index === 0
          ? { ...generatedEdge, label: 'HTTPS inference request' }
          : generatedEdge
      )),
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const transform = parseTransform(
      container.querySelector('svg > g')?.getAttribute('transform') ?? null,
    );
    const overviewLabels = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
    );

    expect(graph.nodes).toHaveLength(34);
    expect(graph.edges).toHaveLength(64);
    expect(overviewLabels).toHaveLength(8);
    for (const label of overviewLabels) {
      const position = parsePosition(label.getAttribute('transform'));
      const background = label.querySelector<SVGRectElement>('rect');
      const left = position.x + Number(background?.getAttribute('x'));
      const top = position.y + Number(background?.getAttribute('y'));
      const right = left + Number(background?.getAttribute('width'));
      const bottom = top + Number(background?.getAttribute('height'));

      expect(transform.x + transform.scale * left).toBeGreaterThanOrEqual(0);
      expect(transform.x + transform.scale * right).toBeLessThanOrEqual(viewport.width);
      expect(transform.y + transform.scale * top).toBeGreaterThanOrEqual(0);
      expect(transform.y + transform.scale * bottom).toBeLessThanOrEqual(viewport.height);
    }
  });

  it('bounds parallel feedback lanes and keeps their return semantics', () => {
    viewport = PUBLICATION_VIEWPORT;
    const nodeIds = Array.from({ length: 10 }, (_, index) => `stage_${index + 1}`);
    const graph: GraphData = {
      graph_type: 'architecture',
      design_origin: 'applied',
      title: 'Parallel feedback routing regression',
      nodes: nodeIds.map((id, index) => node(id, `Stage ${index + 1}`)),
      edges: [
        ...nodeIds.slice(1).map((target, index) => (
          edge(nodeIds[index], target, `advances stage ${index + 2}`)
        )),
        ...Array.from({ length: 9 }, (_, index) => (
          edge('stage_2', 'stage_9', `reports bounded signal ${index + 1}`, 'feedback')
        )),
        edge('stage_9', 'stage_2', 'returns approval decision', 'control'),
      ],
      groups: [],
      sequence: nodeIds.map((id, index) => ({
        step: index + 1,
        nodes: [id],
        description: `Run stage ${index + 1}.`,
      })),
    };
    const { container } = render(
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );
    const transform = parseTransform(
      container.querySelector('svg > g')?.getAttribute('transform') ?? null,
    );
    const feedbackPaths = Array.from(
      container.querySelectorAll<SVGPathElement>(
        'path.edge-vis[data-source-id="stage_2"][data-target-id="stage_9"]',
      ),
    );

    expect(feedbackPaths).toHaveLength(9);
    expect(feedbackPaths.every(path => path.getAttribute('marker-end') === 'url(#arrow-ret)'))
      .toBe(true);
    for (const path of feedbackPaths) {
      expect(path.getAttribute('d')).not.toContain('C');
      for (const point of pathControlPoints(path.getAttribute('d'))) {
        expect(transform.x + transform.scale * point.x).toBeGreaterThanOrEqual(0);
        expect(transform.x + transform.scale * point.x).toBeLessThanOrEqual(viewport.width);
        expect(transform.y + transform.scale * point.y).toBeGreaterThanOrEqual(0);
        expect(transform.y + transform.scale * point.y).toBeLessThanOrEqual(viewport.height);
      }
    }

    const returnLabel = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label'),
    ).find(label => label.textContent?.startsWith('returns approval'));
    const returnLabelPosition = parsePosition(
      returnLabel?.getAttribute('transform') ?? null,
    );

    expect(returnLabel?.getAttribute('data-overview-required')).toBe('true');
    expect(Number(returnLabel?.getAttribute('opacity'))).toBeGreaterThan(0);
    expect(
      transform.x + transform.scale * (returnLabelPosition.x - 51),
    ).toBeGreaterThanOrEqual(0);
  });

  it('rebinds DOM identities when content changes under the same version', async () => {
    const graph = (source: string, target: string): GraphData => ({
      graph_type: 'architecture',
      design_origin: 'applied',
      version: 'shared-version',
      title: 'Identity binding regression',
      nodes: [node(source, 'Source'), node(target, 'Target')],
      edges: [edge(source, target, 'sends bounded event')],
      groups: [],
      sequence: [],
    });
    const renderGraph = (data: GraphData) => (
      <div style={{ width: viewport.width, height: viewport.height }}>
        <D3Graph
          graphData={data}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>
    );
    const { container, rerender } = render(renderGraph(graph('old-source', 'old-target')));

    rerender(renderGraph(graph('new-source', 'new-target')));

    await waitFor(() => {
      expect(
        Array.from(container.querySelectorAll('g.node'), element => (
          element.getAttribute('data-node-id')
        )),
      ).toEqual(['new-source', 'new-target']);
      expect(
        container.querySelector('[data-testid="graph-canvas"]')
          ?.getAttribute('data-rendered-graph-version'),
      ).toBe('shared-version');
    });
    const renderedEdge = container.querySelector('path.edge-vis');
    expect(renderedEdge?.getAttribute('data-source-id')).toBe('new-source');
    expect(renderedEdge?.getAttribute('data-target-id')).toBe('new-target');
    expect(renderedEdge?.getAttribute('data-edge-label')).toBe('sends bounded event');
  });
});
