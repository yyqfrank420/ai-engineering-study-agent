import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import type { GraphData, GraphEdge } from '../../types';
import { D3Graph } from './D3Graph';


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
    expect(screen.queryByText('ENTRY')).toBeNull();
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
    expect(edgeLabel?.getAttribute('opacity')).toBe('0');
    fireEvent.mouseOver(edgeHitArea!);
    expect(edgeLabel?.getAttribute('opacity')).toBe('1');
    expect(screen.getByText('submits bounded proposal')).toBeTruthy();
    fireEvent.mouseOut(edgeHitArea!);
    expect(edgeLabel?.getAttribute('opacity')).toBe('0');
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
});
