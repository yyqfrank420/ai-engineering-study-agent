import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { GraphData, GraphEdge } from '../../types';
import { D3Graph } from './D3Graph';
import {
  customerSupportDenseGraph,
  growthMarketingDenseGraph,
} from './__fixtures__/denseArchitectures';


const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Cold-chain advisory loop',
  design_origin: 'applied',
  nodes: [
    {
      id: 'sensor_gateway',
      label: 'Sensor Gateway',
      type: 'gateway',
      technology: 'Signed telemetry',
      description: 'Validates immutable temperature readings.',
      detail: null,
      design_origin: 'applied',
    },
  ],
  edges: [],
  sequence: [],
};

function edge(source: string, target: string, label: string): GraphEdge {
  return {
    source,
    target,
    label,
    technology: 'Typed event',
    sync: 'sync',
    description: `${label} from ${source} to ${target}.`,
  };
}

const originalGetBBox = SVGGraphicsElement.prototype.getBBox;
const originalElementGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, 'getBBox');
const originalWidth = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'width');
const originalHeight = Object.getOwnPropertyDescriptor(SVGSVGElement.prototype, 'height');

beforeAll(() => {
  Object.defineProperty(SVGGraphicsElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 48, height: 12 }),
  });
  Object.defineProperty(SVGElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 48, height: 12 }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'width', {
    configurable: true,
    get: () => ({ baseVal: { value: 760 } }),
  });
  Object.defineProperty(SVGSVGElement.prototype, 'height', {
    configurable: true,
    get: () => ({ baseVal: { value: 500 } }),
  });
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
});

describe('graph node activation', () => {
  it('exposes the node as a button and supports pointer and keyboard activation', () => {
    const onNodeClick = vi.fn();
    render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={graph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={onNodeClick}
        />
      </div>,
    );

    const node = screen.getByRole('button', { name: 'Explore Sensor Gateway' });
    fireEvent.click(node);
    fireEvent.keyDown(node, { key: 'Enter' });
    fireEvent.keyDown(node, { key: ' ' });

    expect(onNodeClick).toHaveBeenCalledTimes(3);
    expect(onNodeClick).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'sensor_gateway' }));
    expect(screen.getByText('Signed telemetry')).toBeTruthy();
    expect(screen.getByText('ENTRY')).toBeTruthy();
    expect(screen.queryByText('EXIT')).toBeNull();
  });

  it('preserves control-flow styling after the sequence effect runs', async () => {
    const controlGraph: GraphData = {
      ...graph,
      nodes: [
        graph.nodes[0],
        {
          ...graph.nodes[0],
          id: 'approval_gate',
          label: 'Approval Gate',
          type: 'control',
        },
      ],
      edges: [{
        source: 'sensor_gateway',
        target: 'approval_gate',
        label: 'submits bounded proposal',
        technology: 'Signed command',
        sync: 'sync',
        description: 'A human reviews the proposed external write.',
        flow: 'control',
      }],
      sequence: [{
        step: 1,
        nodes: ['sensor_gateway', 'approval_gate'],
        description: 'Review the proposal.',
      }],
    };
    const { container } = render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={controlGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const edge = container.querySelector('path.edge-vis');
    await waitFor(() => {
      expect(edge?.getAttribute('stroke')).toBe('rgba(148,163,184,0.52)');
      expect(edge?.getAttribute('stroke-dasharray')).toBe('3,4');
    });

    const edgeLabel = container.querySelector('g.edge-label');
    const edgeHitArea = container.querySelector('path.edge-hit');
    expect(edgeLabel?.getAttribute('data-overview-required')).toBe('true');
    expect(edgeLabel?.getAttribute('opacity')).toBe('0.62');
    fireEvent.mouseOver(edgeHitArea!);
    expect(edgeLabel?.getAttribute('opacity')).toBe('1');
    expect(screen.getAllByText('submits bounded proposal')).toHaveLength(2);
    fireEvent.mouseOut(edgeHitArea!);
    expect(edgeLabel?.getAttribute('opacity')).toBe('0.62');
  });

  it('re-renders and re-fits when its actual canvas size changes', async () => {
    let notifyResize: ((entries: Array<{ contentRect: { width: number; height: number } }>) => void) | null = null;
    class TestResizeObserver {
      constructor(callback: typeof notifyResize) {
        notifyResize = callback;
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    try {
      const { container } = render(
        <div style={{ width: 760, height: 500 }}>
          <D3Graph
            graphData={graph}
            currentStep={-1}
            activeNodeIds={new Set<string>()}
            onNodeClick={() => undefined}
          />
        </div>,
      );
      const firstNode = container.querySelector('g.node');

      act(() => notifyResize?.([{ contentRect: { width: 520, height: 720 } }]));

      await waitFor(() => expect(firstNode?.isConnected).toBe(false));
      expect(container.querySelectorAll('g.node')).toHaveLength(1);
      await waitFor(() => {
        expect(container.querySelector('g.node')?.getAttribute('opacity')).toBe('1');
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('wraps a wide parallel stage instead of shrinking every node to fit one row', () => {
    const nodes = [
      ['request', 'Customer Request'],
      ['classify', 'Intent Classifier'],
      ['knowledge', 'Knowledge Retrieval'],
      ['account', 'Account Context'],
      ['policy', 'Policy Guard'],
      ['sentiment', 'Sentiment Analysis'],
      ['history', 'Conversation Memory'],
      ['compose', 'Response Composer'],
      ['deliver', 'Channel Delivery'],
    ].map(([id, label]) => ({
      ...graph.nodes[0],
      id,
      label,
    }));
    const parallelIds = ['knowledge', 'account', 'policy', 'sentiment', 'history'];
    const fanoutGraph: GraphData = {
      ...graph,
      nodes,
      edges: [
        edge('request', 'classify', 'routes'),
        ...parallelIds.map(id => edge('classify', id, 'enriches')),
        ...parallelIds.map(id => edge(id, 'compose', 'rejoins')),
        edge('compose', 'deliver', 'delivers'),
      ],
    };

    render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={fanoutGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const yPositions = parallelIds.map((id) => {
      const node = screen.getByRole('button', {
        name: `Explore ${nodes.find(candidate => candidate.id === id)?.label}`,
      });
      const match = node.getAttribute('transform')?.match(/translate\([^,]+,([^)]+)\)/);
      return Number(match?.[1]);
    });

    expect(new Set(yPositions).size).toBe(2);
    expect(yPositions.every(Number.isFinite)).toBe(true);
  });

  it('wraps a shallow eight-way fanout that would otherwise shrink below readability', () => {
    const peerIds = Array.from({ length: 8 }, (_, index) => `worker_${index}`);
    const nodes = [
      { ...graph.nodes[0], id: 'request', label: 'Campaign Request' },
      ...peerIds.map((id, index) => ({
        ...graph.nodes[0],
        id,
        label: `Domain Worker ${index + 1}`,
      })),
      { ...graph.nodes[0], id: 'aggregate', label: 'Decision Aggregator' },
    ];
    const fanoutGraph: GraphData = {
      ...graph,
      nodes,
      edges: [
        ...peerIds.map(id => edge('request', id, 'dispatches')),
        ...peerIds.map(id => edge(id, 'aggregate', 'returns')),
      ],
    };

    render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={fanoutGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    const positions = peerIds.map((id) => {
      const node = screen.getByRole('button', {
        name: `Explore ${nodes.find(candidate => candidate.id === id)?.label}`,
      });
      const match = node.getAttribute('transform')?.match(/translate\(([^,]+),([^)]+)\)/);
      return { x: Number(match?.[1]), y: Number(match?.[2]) };
    });

    expect(new Set(positions.map(position => position.y)).size).toBe(3);
    const rows = new Map<number, Array<{ x: number; y: number }>>();
    for (const position of positions) {
      rows.set(position.y, [...(rows.get(position.y) ?? []), position]);
    }
    expect(Math.max(...Array.from(rows.values(), row => row.length))).toBe(3);
    for (const row of rows.values()) {
      const sortedX = row.map(position => position.x).sort((left, right) => left - right);
      for (let index = 1; index < sortedX.length; index += 1) {
        expect(sortedX[index] - sortedX[index - 1]).toBeGreaterThanOrEqual(200);
      }
    }
    expect(positions.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y))).toBe(true);
  });

  it('keeps an out-of-sample marketplace control loop readable in overview', async () => {
    const nodes = [
      { ...graph.nodes[0], id: 'seller_event', label: 'Seller Listing Event', technology: 'Signed marketplace event envelope' },
      { ...graph.nodes[0], id: 'risk_gate', label: 'Listing Risk Gate', technology: 'Deterministic policy and risk scoring', type: 'decision' as const },
      { ...graph.nodes[0], id: 'human_review', label: 'Human Review Queue', technology: 'Audited exception workflow', type: 'control' as const },
      { ...graph.nodes[0], id: 'listing_index', label: 'Trusted Listing Index', technology: 'Versioned searchable marketplace catalogue', type: 'datastore' as const },
      { ...graph.nodes[0], id: 'buyer_match', label: 'Buyer Match Service', technology: 'Eligibility-aware candidate ranking' },
      { ...graph.nodes[0], id: 'outcome_ledger', label: 'Outcome Ledger', technology: 'Append-only conversion and dispute events', type: 'datastore' as const },
    ];
    const marketplaceGraph: GraphData = {
      ...graph,
      title: 'Marketplace Trust Loop — Policy-gated listings and measured buyer outcomes',
      nodes,
      edges: [
        { ...edge('seller_event', 'risk_gate', 'submits signed listing'), flow: 'runtime' },
        { ...edge('risk_gate', 'listing_index', 'publishes approved listing'), flow: 'runtime' },
        { ...edge('risk_gate', 'human_review', 'routes ambiguous listing'), flow: 'control' },
        { ...edge('human_review', 'listing_index', 'approves reviewed listing'), flow: 'control' },
        { ...edge('listing_index', 'buyer_match', 'streams eligible candidates'), flow: 'runtime' },
        { ...edge('buyer_match', 'outcome_ledger', 'records measured outcome'), flow: 'runtime' },
        {
          ...edge('outcome_ledger', 'risk_gate', 'returns dispute feedback'),
          flow: 'feedback',
          type: 'loop',
        },
      ],
      groups: [
        { id: 'intake', label: 'Supply Intake', nodeIds: ['seller_event', 'risk_gate'], kind: 'runtime' },
        { id: 'trust', label: 'Trust Operations', nodeIds: ['human_review', 'outcome_ledger'], kind: 'operations' },
        { id: 'market', label: 'Marketplace Delivery', nodeIds: ['listing_index', 'buyer_match'], kind: 'runtime' },
      ],
      sequence: [
        { step: 1, nodes: ['seller_event', 'risk_gate'], description: 'Validate the listing.' },
        { step: 2, nodes: ['risk_gate', 'listing_index'], description: 'Publish or review.' },
        { step: 3, nodes: ['listing_index', 'buyer_match'], description: 'Match eligible buyers.' },
        { step: 4, nodes: ['buyer_match', 'outcome_ledger'], description: 'Measure outcomes.' },
      ],
    };
    const { container } = render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={marketplaceGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    expect(container.querySelectorAll('g.node[data-grouped="true"]')).toHaveLength(nodes.length);
    expect(container.querySelectorAll('text.node-group-label')).toHaveLength(nodes.length);
    expect(Array.from(container.querySelectorAll('text.node-group-label'))
      .filter(label => label.textContent?.startsWith('Marketplace Deliv'))).toHaveLength(2);
    const listingTechnology = screen.getByRole('button', { name: 'Explore Trusted Listing Index' })
      .querySelector('text.node-technology')?.textContent;
    expect(listingTechnology).toContain('Versioned searchable');
    expect(listingTechnology).toContain('marketplace catalogue');

    const requiredLabels = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
    );
    expect(requiredLabels.length).toBeGreaterThanOrEqual(6);
    expect(requiredLabels.every(label => Number(label.getAttribute('opacity')) > 0)).toBe(true);

    const feedbackLabel = Array.from(container.querySelectorAll<SVGGElement>('g.edge-label'))
      .find(label => label.textContent?.includes('returns dispute'));
    expect(feedbackLabel?.getAttribute('data-overview-required')).toBeNull();
    expect(feedbackLabel?.getAttribute('opacity')).toBe('0');

    fireEvent.mouseOver(screen.getByRole('button', { name: 'Explore Outcome Ledger' }));
    await waitFor(() => expect(feedbackLabel?.getAttribute('opacity')).toBe('1'));
    fireEvent.mouseOut(screen.getByRole('button', { name: 'Explore Outcome Ledger' }));
    await waitFor(() => expect(feedbackLabel?.getAttribute('opacity')).toBe('0'));
  });

  it.each([
    ['growth marketing', growthMarketingDenseGraph],
    ['customer support', customerSupportDenseGraph],
  ])('preserves the dense %s regression architecture', (_name, denseGraph) => {
    const { container } = render(
      <div style={{ width: 760, height: 500 }}>
        <D3Graph
          graphData={denseGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />
      </div>,
    );

    expect(container.querySelectorAll('g.node')).toHaveLength(denseGraph.nodes.length);
    expect(container.querySelectorAll('path.edge-vis')).toHaveLength(denseGraph.edges.length);
    expect(container.querySelectorAll('text.node-group-label')).toHaveLength(denseGraph.nodes.length);
    const requiredLabels = Array.from(
      container.querySelectorAll<SVGGElement>('g.edge-label[data-overview-required="true"]'),
    );
    expect(requiredLabels.length).toBeGreaterThan(0);
    expect(requiredLabels.every(label => Number(label.getAttribute('opacity')) > 0)).toBe(true);
    const feedbackLabels = Array.from(container.querySelectorAll<SVGGElement>('g.edge-label'))
      .filter(label => label.getAttribute('data-overview-required') === null);
    expect(feedbackLabels.length).toBeGreaterThan(0);
    expect(feedbackLabels.every(label => Number(label.getAttribute('opacity')) === 0)).toBe(true);
  });
});
