import { render } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import type { GraphData, GraphEdge, GraphNode } from '../../types';
import { D3Graph } from './D3Graph';
import { NODE_H, NODE_W } from './graphLayout';


const LEGACY_VIEWPORT = { width: 760, height: 500 };
const DEEP_VIEWPORT = { width: 656, height: 848 };
const NODE_TITLE_PX = 15.36;
const MIN_PUBLISHED_TITLE_PX = 6;
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

function deepCapacityGraph(): GraphData {
  const levelSizes = [3, 2, 3, 3, 1, 5, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1];
  const levelNodeIds = levelSizes.map((size, level) => (
    Array.from({ length: size }, (_, index) => `level_${level + 1}_node_${index + 1}`)
  ));
  const nodeIds = levelNodeIds.flat();
  const generatedNodes = nodeIds.map((id, index) => node(
    id,
    `Owned Capability ${index + 1}`,
    index % 11 === 0 ? 'decision' : 'service',
    index >= 31 ? 'bottom' : 'main',
  ));
  const generatedEdges = levelNodeIds.slice(1).flatMap((ids, levelIndex) => (
    ids.map((target, index) => edge(
      levelNodeIds[levelIndex][index % levelNodeIds[levelIndex].length],
      target,
      `advances stage ${levelIndex + 2}`,
    ))
  ));
  for (let index = 0; generatedEdges.length < 65; index += 1) {
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
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);

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
    expect(NODE_TITLE_PX * transform.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);
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
});
