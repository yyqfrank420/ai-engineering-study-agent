import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import * as d3 from 'd3';

import type { GraphData, GraphEdge, GraphViewState } from '../../types';
import { TYPE_STYLE } from '../../utils/graphColors';
import { D3Graph } from './D3Graph';
import tradingBotSavedGraph from './__fixtures__/tradingBotSavedGraph.json';
import { learnerSupportGraph } from './__fixtures__/learnerSupportGraph';
import { diagramConnections } from './diagramConnections';
import { MIN_PUBLISHED_TITLE_PX, NODE_H, NODE_RX, NODE_TITLE_PX, NODE_W } from './graphLayout';
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

const cameraGraph: GraphData = {
  ...graph,
  nodes: ['a', 'b', 'c'].map(id => ({ ...graph.nodes[0], id, label: id })),
  edges: [
    { source: 'a', target: 'b', label: 'First', technology: 'HTTP', sync: 'sync', description: '' },
    { source: 'b', target: 'c', label: 'Second', technology: 'HTTP', sync: 'sync', description: '' },
  ],
  sequence: [
    { step: 1, nodes: ['a'], description: 'First' },
    { step: 2, nodes: ['b'], description: 'Second' },
    { step: 3, nodes: ['c'], description: 'Third' },
  ],
};

const cameraViewState: GraphViewState = {
  layoutVersion: 17,
  nodePositions: { a: { x: 200, y: 200 }, b: { x: 600, y: 200 }, c: { x: 1000, y: 200 } },
  viewport: { x: 0, y: 0, k: 1 },
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
  it.each(['node', 'zone', 'border'])('cleans up an active %s drag when the canvas unmounts', targetType => {
    const save = vi.fn();
    const props = { graphData: { ...graph, groups: [{ id: 'zone', label: 'Processing', kind: 'runtime' as const, nodeIds: ['sensor_gateway'] }] },
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: vi.fn(), onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} />);
    const zone = view.container.querySelector('.group-box > rect')!;
    fireEvent.doubleClick(zone);
    const target = targetType === 'zone' ? zone : view.container.querySelector(targetType === 'node' ? 'g.node' : '.zone-resize')!;
    const down = createEvent.mouseDown(target, { clientX: 100, clientY: 100, button: 0 });
    Object.defineProperty(down, 'view', { value: document.defaultView });
    fireEvent(target, down);
    view.unmount();
    save.mockClear();
    for (const type of ['mouseMove', 'mouseUp'] as const) {
      const event = createEvent[type](window, { clientX: 120, clientY: 140, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(window, event);
    }
    expect(save).not.toHaveBeenCalled();
  });

  it.each(['move', 'resize'] as const)('snaps zone %s to another frame and moves every member together', async operation => {
    const save = vi.fn();
    const zoneGraph: GraphData = { ...graph,
      nodes: ['a', 'b', 'c'].map(id => ({ ...graph.nodes[0], id, label: id })),
      groups: [{ id: 'first', label: 'First cluster', kind: 'runtime', nodeIds: ['a', 'b'] },
        { id: 'second', label: 'Second cluster', kind: 'runtime', nodeIds: ['c'] }] };
    const { container } = render(<D3Graph graphData={zoneGraph} currentStep={-1} activeNodeIds={new Set<string>()}
      onNodeClick={() => undefined} onViewStateChange={save} navigation initialViewState={{ layoutVersion: 17,
        nodePositions: { a: { x: 200, y: 100 }, b: { x: 400, y: 100 }, c: { x: 700, y: 300 } },
        viewport: { x: 0, y: 0, k: 1 } }} />);
    const frame = container.querySelector('[data-group-id="first"] > rect')!;
    fireEvent.doubleClick(frame);
    const target = operation === 'move' ? frame : container.querySelector('[data-group-id="first"] [data-side="e"]')!;
    const mouse = (element: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', x: number, y: number) => {
      const event = createEvent[type](element, { clientX: x, clientY: y, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(element, event);
    };
    const end = operation === 'move' ? [597, 160] : [397, 100];
    mouse(target, 'mouseDown', 100, 100);
    mouse(window, 'mouseMove', end[0], end[1]);
    expect(container.querySelectorAll('.alignment-guides line')).toHaveLength(1);
    const guide = container.querySelector('.alignment-guides line')!;
    expect(Number(guide.getAttribute('x1'))).toBe(operation === 'move' ? 583 : 817);
    mouse(window, 'mouseUp', end[0], end[1]);
    const positions = save.mock.lastCall![0].nodePositions;
    expect(positions.a).toEqual(operation === 'move' ? { x: 700, y: 160 } : { x: 350, y: 100 });
    expect(positions.b.x - positions.a.x).toBe(200);
    expect(positions.b.y).toBe(positions.a.y);
    expect(positions.c).toEqual({ x: 700, y: 300 });
    expect(container.querySelectorAll('.alignment-guides line')).toHaveLength(0);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  });

  it('restores asymmetric saved padding with centered contents and no frame drift', () => {
    const props = { graphData: { ...graph, nodes: ['a', 'b'].map(id => ({ ...graph.nodes[0], id, label: id })),
      groups: [{ id: 'zone', label: 'Processing', kind: 'runtime' as const, nodeIds: ['a', 'b'] }] },
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined, navigation: true, onViewStateChange: vi.fn() };
    const saved = { layoutVersion: 17, nodePositions: { a: { x: 200, y: 100 }, b: { x: 400, y: 200 } },
      viewport: { x: 0, y: 0, k: 1 }, zonePadding: { zone: { left: 100, right: 0, top: 30, bottom: 10 } } };
    const view = render(<D3Graph {...props} initialViewState={saved} />);
    const bounds = (root: HTMLElement) => ['x', 'y', 'width', 'height'].map(attr => Number(root.querySelector('.group-box > rect')!.getAttribute(attr)));
    expect(bounds(view.container)).toEqual([-17, -6, 534, 270]);
    const normalized = props.onViewStateChange.mock.lastCall![0];
    expect(normalized.nodePositions).toEqual({ a: { x: 150, y: 90 }, b: { x: 350, y: 190 } });
    expect(normalized.zonePadding.zone).toEqual({ left: 50, right: 50, top: 20, bottom: 20 });
    view.unmount();
    const restored = render(<D3Graph {...props} initialViewState={normalized} />);
    expect(bounds(restored.container)).toEqual([-17, -6, 534, 270]);
    expect(props.onViewStateChange.mock.lastCall![0].nodePositions).toEqual(normalized.nodePositions);
  });

  it.each([
    { altKey: false, shiftKey: false, x: 496, y: 240, expected: [500, 240], guides: 1 },
    { altKey: true, shiftKey: false, x: 496, y: 240, expected: [496, 240], guides: 0 },
    { altKey: false, shiftKey: true, x: 300, y: 294, expected: [200, 300], guides: 1 },
  ])('snaps node drags with visible guides and respects modifiers: %j', async scenario => {
    const save = vi.fn();
    const props = { graphData: { ...graph, nodes: ['a', 'b', 'c'].map(id => ({ ...graph.nodes[0], id, label: id })) },
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: vi.fn(), navigation: true, onViewStateChange: save,
      initialViewState: { layoutVersion: 17, nodePositions: { a: { x: 200, y: 100 }, b: { x: 500, y: 100 }, c: { x: 500, y: 300 } },
        viewport: { x: 0, y: 0, k: 1 } } };
    const { container } = render(<D3Graph {...props} />);
    const node = container.querySelector('[data-node-id="a"]')!;
    const mouse = (target: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', clientX: number, clientY: number) => {
      const event = createEvent[type](target, { clientX, clientY, button: 0, altKey: scenario.altKey, shiftKey: scenario.shiftKey });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(target, event);
    };
    mouse(node, 'mouseDown', 200, 100);
    mouse(window, 'mouseMove', scenario.x, scenario.y);
    expect(node.getAttribute('transform')).toBe(`translate(${scenario.expected.join(',')})`);
    expect(container.querySelectorAll('.alignment-guides line')).toHaveLength(scenario.guides);
    mouse(window, 'mouseUp', scenario.x, scenario.y);
    expect(container.querySelectorAll('.alignment-guides line')).toHaveLength(0);
    expect(save.mock.lastCall![0].nodePositions.a).toEqual({ x: scenario.expected[0], y: scenario.expected[1] });
    fireEvent.keyDown(node, { key: 'ArrowRight' });
    fireEvent.keyDown(node, { key: 'ArrowDown', shiftKey: true });
    expect(node.getAttribute('transform')).toBe(`translate(${scenario.expected[0] + 1},${scenario.expected[1] + 10})`);
    expect(props.onNodeClick).not.toHaveBeenCalled();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  });
  it('keeps future steps hidden even when focus and Connections request more detail', () => {
    const sequenceGraph: GraphData = {
      ...graph,
      nodes: ['a', 'b'].map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [edge('a', 'b', 'Request'), edge('b', 'a', 'Response')],
      sequence: [{ step: 1, nodes: ['a'], description: 'Start' }, { step: 2, nodes: ['b'], description: 'Respond' }],
    };
    const props = { graphData: sequenceGraph, currentStep: 0, activeNodeIds: new Set(['a']), onNodeClick: vi.fn(), navigation: true };
    const view = render(<D3Graph {...props} />);
    fireEvent.focus(screen.getByRole('button', { name: 'Explore a' }));
    fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
    expect(view.container.querySelector<SVGPathElement>('.edge-vis')?.style.opacity).toBe('0');
    expect(view.container.querySelector('.edge-hit')?.getAttribute('tabindex')).toBe('-1');
    expect(view.container.querySelector('[data-node-id="b"]')?.getAttribute('aria-hidden')).toBe('true');
    expect(view.container.querySelector('[data-node-id="b"]')?.getAttribute('tabindex')).toBe('-1');
    view.rerender(<D3Graph {...props} currentStep={1} activeNodeIds={new Set(['a', 'b'])} />);
    const connection = screen.getByRole('button', { name: 'Connections between a and b' });
    expect(connection.getAttribute('tabindex')).toBe('0');
    fireEvent.keyDown(connection, { key: 'Enter' });
    expect(screen.getByRole('region', { name: 'Connection details' }).textContent).toContain('Response');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close connection details' }));
  });

  it('keeps visible walkthrough steps still and pans offscreen steps without persisting the camera', () => {
    const save = vi.fn();
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      onNodeClick: () => undefined, onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} currentStep={-1} activeNodeIds={new Set<string>()} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const savedCalls = save.mock.calls.length;
    const step = (number: number, nodeIds: string[]) => view.rerender(
      <D3Graph {...props} currentStep={number} activeNodeIds={new Set(nodeIds)} />,
    );

    step(0, ['a']);
    expect(d3.zoomTransform(svg).x).toBe(0);
    step(1, ['b']);
    expect(d3.zoomTransform(svg).x).toBe(0);
    step(2, ['c']);
    const followed = d3.zoomTransform(svg);
    expect(followed.k).toBe(1);
    expect(followed.x).toBeLessThan(0);
    expect(followed.x + (1000 + 186 / 2) * followed.k).toBeLessThanOrEqual(760 - 32);
    expect(save).toHaveBeenCalledTimes(savedCalls);

    step(-1, []);
    expect(d3.zoomTransform(svg).x).toBe(0);
    expect(d3.zoomTransform(svg).k).toBe(1);
    expect(save).toHaveBeenCalledTimes(savedCalls);
  });

  it('minimally frames an inspected node inside the unobscured area without zooming or saving', () => {
    const save = vi.fn();
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined,
      onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const baseline = d3.zoomTransform(svg);
    const savedCalls = save.mock.calls.length;

    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'a', width: 400, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(baseline.toString());
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 400, height: 300 }} />);
    const framed = d3.zoomTransform(svg);
    expect(framed.k).toBe(baseline.k);
    expect(framed.x + (600 - NODE_W / 2) * framed.k).toBeGreaterThanOrEqual(32);
    expect(framed.x + (600 + NODE_W / 2) * framed.k).toBeCloseTo(400 - 32);
    expect(framed.y + (200 - NODE_H / 2) * framed.k).toBeGreaterThanOrEqual(72);
    expect(framed.y + (200 + NODE_H / 2) * framed.k).toBeLessThanOrEqual(300 - 32);
    expect(save).toHaveBeenCalledTimes(savedCalls);

    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 300, height: 300 }} />);
    const narrowed = d3.zoomTransform(svg);
    expect(narrowed.k).toBe(baseline.k);
    expect(narrowed.x + (600 + NODE_W / 2) * narrowed.k).toBeCloseTo(300 - 32);
    expect(save).toHaveBeenCalledTimes(savedCalls);
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'missing', width: 200, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(narrowed.toString());
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 0, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(narrowed.toString());
  });

  it('stops inspection follow after manual pan and resumes only after close and reopen', async () => {
    const save = vi.fn();
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined,
      onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 400, height: 300 }} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const mouse = (element: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', x: number, y: number) => {
      const event = createEvent[type](element, { clientX: x, clientY: y, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(element, event);
    };
    mouse(svg, 'mouseDown', 400, 250);
    mouse(window, 'mouseMove', 350, 250);
    mouse(window, 'mouseUp', 350, 250);
    const manual = d3.zoomTransform(svg);
    expect(save.mock.lastCall![0].viewport.x).toBe(manual.x);
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 250, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    view.rerender(<D3Graph {...props} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    const savedCalls = save.mock.calls.length;
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 250, height: 300 }} />);
    const reopened = d3.zoomTransform(svg);
    expect(reopened.x + (600 + NODE_W / 2) * reopened.k).toBeCloseTo(250 - 32);
    expect(reopened.k).toBe(manual.k);
    expect(save).toHaveBeenCalledTimes(savedCalls);
    await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 0)); });
  });

  it('keeps a manually panned inspection view after the same node is saved', async () => {
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined,
      navigation: true };
    const view = render(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 400, height: 300 }} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const mouse = (element: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', x: number, y: number) => {
      const event = createEvent[type](element, { clientX: x, clientY: y, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(element, event);
    };
    mouse(svg, 'mouseDown', 400, 250);
    mouse(window, 'mouseMove', 350, 250);
    mouse(window, 'mouseUp', 350, 250);
    const manual = d3.zoomTransform(svg);

    const updatedGraph = { ...cameraGraph, version: '2',
      nodes: cameraGraph.nodes.map(node => node.id === 'b' ? { ...node, label: 'Updated b' } : node) };
    const updatedViewState = { ...cameraViewState,
      viewport: { x: manual.x, y: manual.y, k: manual.k } };
    view.rerender(<D3Graph {...props} graphData={updatedGraph} initialViewState={updatedViewState}
      inspectionViewport={{ nodeId: 'b', width: 250, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    view.rerender(<D3Graph {...props} graphData={updatedGraph} initialViewState={updatedViewState}
      inspectionViewport={{ nodeId: 'b', width: 200, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 0)); });
  });

  it('lets toolbar and node-layout actions cancel inspection follow until a different node is selected', () => {
    const save = vi.fn();
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined,
      onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 400, height: 300 }} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    fireEvent.keyDown(screen.getByRole('button', { name: 'Explore b' }), { key: 'ArrowRight' });
    const nudged = d3.zoomTransform(svg);
    expect(save.mock.lastCall![0].nodePositions.b.x).toBe(601);
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'b', width: 250, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(nudged.toString());

    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'c', width: 250, height: 300 }} />);
    const switched = d3.zoomTransform(svg);
    expect(switched.x + (1000 + NODE_W / 2) * switched.k).toBeCloseTo(250 - 32);
    fireEvent.click(screen.getByRole('button', { name: 'Fit diagram' }));
    const toolbar = d3.zoomTransform(svg);
    expect(toolbar.k).toBeLessThan(switched.k);
    view.rerender(<D3Graph {...props} inspectionViewport={{ nodeId: 'c', width: 200, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(toolbar.toString());
  });

  it('keeps inspection framing ahead of walkthrough follow, including after manual intervention', () => {
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      onNodeClick: () => undefined, navigation: true,
      inspectionViewport: { nodeId: 'b', width: 400, height: 300 } };
    const view = render(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const inspected = d3.zoomTransform(svg);
    expect(inspected.x + (600 + NODE_W / 2) * inspected.k).toBeCloseTo(400 - 32);
    view.rerender(<D3Graph {...props} currentStep={2} activeNodeIds={new Set(['c'])} />);
    expect(d3.zoomTransform(svg).toString()).toBe(inspected.toString());
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    const manual = d3.zoomTransform(svg);
    view.rerender(<D3Graph {...props} currentStep={1} activeNodeIds={new Set(['a'])} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    view.rerender(<D3Graph {...props} currentStep={-1} activeNodeIds={new Set<string>()} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    view.rerender(<D3Graph {...props} currentStep={-1} activeNodeIds={new Set<string>()} inspectionViewport={undefined} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
  });

  it('leaves a manually zoomed inspection view unchanged when playback moves or the inspector closes', async () => {
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      onNodeClick: () => undefined, navigation: true };
    const view = render(<D3Graph {...props} currentStep={2} activeNodeIds={new Set(['c'])}
      inspectionViewport={{ nodeId: 'b', width: 400, height: 300 }} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const inspected = d3.zoomTransform(svg);
    fireEvent.wheel(svg, { deltaY: -100, clientX: 300, clientY: 200 });
    await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 180)); });
    const manual = d3.zoomTransform(svg);
    expect(manual.k).toBeGreaterThan(inspected.k);
    view.rerender(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])}
      inspectionViewport={{ nodeId: 'b', width: 250, height: 300 }} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
    view.rerender(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
    expect(d3.zoomTransform(svg).toString()).toBe(manual.toString());
  });

  it('fits all active bounds when a readable zoom reduction suffices', () => {
    const fittingViewState = { ...cameraViewState,
      nodePositions: { ...cameraViewState.nodePositions, c: { x: 950, y: 200 } } };
    const props = { graphData: cameraGraph, initialViewState: fittingViewState,
      onNodeClick: () => undefined, navigation: true };
    const view = render(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    view.rerender(<D3Graph {...props} currentStep={1} activeNodeIds={new Set(['a', 'c'])} />);
    const followed = d3.zoomTransform(svg);
    expect(followed.k).toBeLessThan(1);
    expect(NODE_TITLE_PX * followed.k).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);
    expect(followed.x + (200 - NODE_W / 2) * followed.k).toBeCloseTo(32);
    expect(followed.x + (950 + NODE_W / 2) * followed.k).toBeCloseTo(760 - 32);
  });

  it('keeps wide active groups readable, anchors their first node, then restores baseline zoom', () => {
    const wideViewState = { ...cameraViewState,
      nodePositions: { ...cameraViewState.nodePositions, c: { x: 2000, y: 200 } } };
    const props = { graphData: cameraGraph, initialViewState: wideViewState,
      onNodeClick: () => undefined, navigation: true };
    const view = render(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    view.rerender(<D3Graph {...props} currentStep={1} activeNodeIds={new Set(['c', 'a'])} />);
    const wide = d3.zoomTransform(svg);
    expect(NODE_TITLE_PX * wide.k).toBeCloseTo(MIN_PUBLISHED_TITLE_PX);
    expect(wide.x + (200 - NODE_W / 2) * wide.k).toBeGreaterThanOrEqual(32);
    expect(wide.x + (200 + NODE_W / 2) * wide.k).toBeLessThanOrEqual(760 - 32);
    expect(wide.x + (2000 - NODE_W / 2) * wide.k).toBeGreaterThan(760);

    view.rerender(<D3Graph {...props} currentStep={2} activeNodeIds={new Set(['c'])} />);
    const narrow = d3.zoomTransform(svg);
    expect(narrow.k).toBe(1);
    expect(narrow.x + (2000 - NODE_W / 2) * narrow.k).toBeGreaterThanOrEqual(32);
    expect(narrow.x + (2000 + NODE_W / 2) * narrow.k).toBeLessThanOrEqual(760 - 32);
  });

  it('adopts the visible camera for an explicit node edit and preserves it through resize and overview', () => {
    let notifyResize: ((entries: Array<{ contentRect: { width: number; height: number } }>) => void) | null = null;
    class TestResizeObserver {
      constructor(callback: typeof notifyResize) { notifyResize = callback; }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    try {
      const save = vi.fn();
      const props = { graphData: cameraGraph, initialViewState: cameraViewState,
        onNodeClick: () => undefined, onViewStateChange: save, navigation: true };
      const view = render(<D3Graph {...props} currentStep={2} activeNodeIds={new Set(['c'])} />);
      const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
      const followed = d3.zoomTransform(svg);
      expect(followed.x).toBeLessThan(0);

      fireEvent.keyDown(screen.getByRole('button', { name: 'Explore c' }), { key: 'ArrowRight' });
      expect(save.mock.lastCall![0].viewport.x).toBe(followed.x);
      expect(save.mock.lastCall![0].nodePositions.c).toEqual({ x: 1001, y: 200 });
      view.rerender(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
      expect(d3.zoomTransform(svg).toString()).toBe(followed.toString());

      Object.defineProperty(svg, 'clientWidth', { configurable: true, value: 520 });
      Object.defineProperty(svg, 'clientHeight', { configurable: true, value: 720 });
      act(() => notifyResize?.([{ contentRect: { width: 520, height: 720 } }]));
      const resized = d3.zoomTransform(svg);
      expect(resized.x).toBeCloseTo(followed.x - 120);
      expect(resized.y).toBeCloseTo(followed.y + 110);
      view.rerender(<D3Graph {...props} currentStep={-1} activeNodeIds={new Set<string>()} />);
      expect(d3.zoomTransform(svg).toString()).toBe(resized.toString());
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('stops camera follow after a manual pan or toolbar zoom and preserves that view at overview', async () => {
    const save = vi.fn();
    const props = { graphData: cameraGraph, initialViewState: cameraViewState,
      onNodeClick: () => undefined, onViewStateChange: save, navigation: true };
    const view = render(<D3Graph {...props} currentStep={0} activeNodeIds={new Set(['a'])} />);
    const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
    const step = (number: number, nodeIds: string[]) => view.rerender(
      <D3Graph {...props} currentStep={number} activeNodeIds={new Set(nodeIds)} />,
    );
    const mouse = (element: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', x: number, y: number) => {
      const event = createEvent[type](element, { clientX: x, clientY: y, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(element, event);
    };

    mouse(svg, 'mouseDown', 400, 300);
    mouse(window, 'mouseMove', 350, 300);
    mouse(window, 'mouseUp', 350, 300);
    const manual = d3.zoomTransform(svg);
    expect(manual.x).toBeLessThan(0);
    expect(save.mock.lastCall![0].viewport.x).toBe(manual.x);
    step(2, ['c']);
    expect(d3.zoomTransform(svg).x).toBe(manual.x);
    step(-1, []);
    expect(d3.zoomTransform(svg).x).toBe(manual.x);

    step(0, ['a']);
    await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 0)); });
    fireEvent.click(screen.getByRole('button', { name: 'Fit diagram' }));
    const toolbar = d3.zoomTransform(svg);
    expect(toolbar.k).toBeLessThan(manual.k);
    step(2, ['c']);
    expect(d3.zoomTransform(svg).toString()).toBe(toolbar.toString());
    step(-1, []);
    expect(d3.zoomTransform(svg).toString()).toBe(toolbar.toString());
  });

  it('refocuses after resize and restores the resized learner viewport at overview', () => {
    let notifyResize: ((entries: Array<{ contentRect: { width: number; height: number } }>) => void) | null = null;
    class TestResizeObserver {
      constructor(callback: typeof notifyResize) { notifyResize = callback; }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    try {
      const save = vi.fn();
      const props = { graphData: cameraGraph, initialViewState: cameraViewState,
        onNodeClick: () => undefined, onViewStateChange: save, navigation: true };
      const view = render(<D3Graph {...props} currentStep={2} activeNodeIds={new Set(['c'])} />);
      const svg = screen.getByTestId('graph-canvas') as unknown as SVGSVGElement;
      expect(d3.zoomTransform(svg).x).toBeLessThan(0);
      Object.defineProperty(svg, 'clientWidth', { configurable: true, value: 520 });
      Object.defineProperty(svg, 'clientHeight', { configurable: true, value: 720 });
      act(() => notifyResize?.([{ contentRect: { width: 520, height: 720 } }]));
      const followed = d3.zoomTransform(svg);
      expect(followed.x + (1000 + 186 / 2) * followed.k).toBeLessThanOrEqual(520 - 32);
      const savedCalls = save.mock.calls.length;
      view.rerender(<D3Graph {...props} currentStep={-1} activeNodeIds={new Set<string>()} />);
      expect(d3.zoomTransform(svg).x).toBe(-120);
      expect(d3.zoomTransform(svg).y).toBe(110);
      expect(d3.zoomTransform(svg).k).toBe(1);
      expect(save).toHaveBeenCalledTimes(savedCalls);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it('exposes resize handles only for the selected zone and exits with Escape', () => {
    const { container } = render(<D3Graph graphData={learnerSupportGraph} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    expect(container.querySelectorAll('.zone-resize[tabindex="0"]')).toHaveLength(0);
    const zone = container.querySelector('[data-group-id="data:datastore"] > rect')!;
    fireEvent.keyDown(zone, { key: 'Enter' });
    expect(container.querySelectorAll('.zone-resize[tabindex="0"]')).toHaveLength(8);
    const border = container.querySelector<SVGElement>('[data-group-id="data:datastore"] .zone-resize')!;
    border.focus();
    fireEvent.keyDown(border, { key: 'Escape' });
    expect(container.querySelectorAll('.zone-resize[tabindex="0"]')).toHaveLength(0);
    expect(document.activeElement).toBe(zone);
    expect(screen.getByRole('button', { name: 'Readable view' }).textContent).toBe('Readable');
    expect(screen.queryByText('Diagram help')).toBeNull();
  });
  it('centers blocks while resizing zone borders, clamps to contents, and restores the saved shape', async () => {
    const save = vi.fn();
    const props = { graphData: learnerSupportGraph, currentStep: -1, activeNodeIds: new Set<string>(),
      onNodeClick: () => undefined, onViewStateChange: save, navigation: true };
    const rendered = render(<D3Graph {...props} />);
    const zone = rendered.container.querySelector('[data-group-id="data:datastore"]')!;
    const rect = zone.querySelector('rect')!;
    const width = Number(rect.getAttribute('width'));
    const x = Number(rect.getAttribute('x'));
    const blocks = Array.from(rendered.container.querySelectorAll('g.node'), node => node.getAttribute('transform'));
    const right = zone.querySelector('[data-side="e"]')!;
    fireEvent.keyDown(right, { key: 'ArrowRight', shiftKey: true });
    expect(Number(rect.getAttribute('width'))).toBe(width + 10);
    fireEvent.keyDown(right, { key: 'ArrowLeft', shiftKey: true });
    fireEvent.keyDown(right, { key: 'ArrowLeft', shiftKey: true });
    expect(Number(rect.getAttribute('width'))).toBe(width);
    const corner = zone.querySelector('[data-side="nw"]')!;
    const mouse = (target: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', clientX: number, clientY: number) => {
      const event = createEvent[type](target, { clientX, clientY, button: 0 });
      Object.defineProperty(event, 'view', { value: document.defaultView });
      fireEvent(target, event);
    };
    mouse(corner, 'mouseDown', 100, 100);
    mouse(window, 'mouseMove', 70, 80);
    mouse(window, 'mouseUp', 70, 80);
    expect(Number(rect.getAttribute('x'))).toBe(x - 30);
    expect(Number(rect.getAttribute('width'))).toBe(width + 30);
    const positions = Array.from(rendered.container.querySelectorAll('g.node'), node => node.getAttribute('transform'));
    expect(positions).not.toEqual(blocks);
    const members = learnerSupportGraph.groups!.find(group => group.id === 'data')!.nodeIds;
    for (const node of rendered.container.querySelectorAll<SVGGElement>('g.node')) {
      const index = learnerSupportGraph.nodes.findIndex(item => item.id === node.dataset.nodeId);
      const previous = blocks[index]!.match(/translate\(([^,]+),([^)]+)\)/)!.slice(1).map(Number);
      if (members.includes(node.dataset.nodeId!)) {
        expect(node.getAttribute('transform')).toBe(`translate(${previous[0] - 15},${previous[1] - 10})`);
      } else expect(node.getAttribute('transform')).toBe(blocks[index]);
    }
    const state = save.mock.lastCall![0];
    expect(state.zonePadding['data:datastore']).toEqual({ top: 10, right: 15, bottom: 10, left: 15 });
    rendered.unmount();
    const restored = render(<D3Graph {...props} initialViewState={state} />);
    const restoredRect = restored.container.querySelector('[data-group-id="data:datastore"] > rect')!;
    expect(Number(restoredRect.getAttribute('x'))).toBe(x - 30);
    expect(Number(restoredRect.getAttribute('width'))).toBe(width + 30);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  });

  it.each([false, true])('places learner-facing tiers left to right (component preview: %s)', preview => {
    const { container } = render(<D3Graph graphData={{ ...learnerSupportGraph, edges: preview ? [] : learnerSupportGraph.edges }}
      currentStep={-1} activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    const position = (id: string) => container.querySelector(`[data-node-id="${id}"]`)!
      .getAttribute('transform')!.match(/translate\(([^,]+),([^)]+)\)/)!.slice(1).map(Number);
    expect(position('client')[0]).toBeLessThan(position('gateway')[0]);
    expect(position('gateway')[0]).toBeLessThan(position('agent')[0]);
    expect(position('agent')[0]).toBeLessThan(position('tickets')[0]);
    expect(position('audit')[1]).toBeGreaterThan(position('agent')[1]);
    expect(position('crm')[1]).toBeLessThan(position('agent')[1]);
    expect(position('executor')[0]).toBeLessThan(position('tickets')[0]);
    const labels = Array.from(container.querySelectorAll('.group-labels-layer text'), node => node.textContent);
    expect(labels).toContain('Data stores');
    expect(labels).toContain('Logs and monitoring');
    expect(labels).not.toContain('Operations');
    expect(labels).not.toContain('Runtime');
  });

  it('moves zone members together after double-click and persists their positions', async () => {
    const onViewStateChange = vi.fn();
    const zoneGraph: GraphData = {
      ...graph,
      nodes: ['a', 'b', 'c'].map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [edge('a', 'b', 'Send'), edge('b', 'c', 'Return')],
      groups: [{ id: 'zone', label: 'Processing', nodeIds: ['a', 'b', 'a', 'missing'], kind: 'runtime' }],
    };
    const { container } = render(<D3Graph graphData={zoneGraph} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined}
      onViewStateChange={onViewStateChange} navigation />);
    const rect = container.querySelector<SVGRectElement>('.group-box > rect')!;
    const svg = screen.getByTestId('graph-canvas');
    const view = document.defaultView!;
    const mouse = (target: Element | Window, type: 'mouseDown' | 'mouseMove' | 'mouseUp', x: number, y: number) => {
      const event = createEvent[type](target, { clientX: x, clientY: y, button: 0, buttons: type === 'mouseUp' ? 0 : 1 });
      // Vitest's window proxy is rejected by jsdom's MouseEvent constructor.
      Object.defineProperty(event, 'view', { value: view });
      fireEvent(target, event);
    };
    const position = (id: string) => {
      const value = container.querySelector(`[data-node-id="${id}"]`)!.getAttribute('transform')!;
      return value.match(/translate\(([^,]+),([^)]+)\)/)!.slice(1).map(Number);
    };
    const before = ['a', 'b', 'c'].map(position);
    const oldPath = container.querySelector('.edge-vis')!.getAttribute('d');
    const oldZoneX = Number(rect.getAttribute('x'));
    fireEvent.doubleClick(rect);
    expect(rect.style.cursor).toBe('grab');
    expect(rect.getAttribute('aria-pressed')).toBe('true');
    onViewStateChange.mockClear();
    mouse(rect, 'mouseDown', 100, 100);
    expect(rect.style.cursor).toBe('grabbing');
    mouse(view, 'mouseMove', 140, 120);
    mouse(view, 'mouseUp', 140, 120);
    expect(position('a')).toEqual([before[0][0] + 40, before[0][1] + 20]);
    expect(position('b')).toEqual([before[1][0] + 40, before[1][1] + 20]);
    expect(position('c')).toEqual(before[2]);
    expect(Number(rect.getAttribute('x'))).toBe(oldZoneX + 40);
    expect(container.querySelector('.edge-vis')!.getAttribute('d')).not.toBe(oldPath);
    expect(onViewStateChange).toHaveBeenCalledTimes(1);
    expect(onViewStateChange.mock.calls[0][0].nodePositions.a).toEqual({ x: position('a')[0], y: position('a')[1] });
    expect(rect.style.cursor).toBe('grab');
    fireEvent.keyDown(rect, { key: 'Escape' });
    expect(rect.getAttribute('aria-pressed')).toBe('false');
    expect(rect.style.cursor).toBe('');
    fireEvent.keyDown(rect, { key: 'Enter' });
    expect(rect.style.cursor).toBe('grab');
    mouse(svg, 'mouseDown', 10, 10);
    mouse(view, 'mouseUp', 10, 10);
    expect(rect.getAttribute('aria-pressed')).toBe('false');
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  });

  it('gives wrapped live titles proper leading and separation from their subtitle', () => {
    const measure = vi.spyOn(SVGElement.prototype as SVGElement & { getBBox(): DOMRect }, 'getBBox').mockImplementation(function(this: SVGElement) {
      return { x: 0, y: 0, width: (this.textContent?.length ?? 0) * 8, height: 16 } as DOMRect;
    });
    try {
      const { container } = render(<D3Graph graphData={{ ...graph, nodes: [{ ...graph.nodes[0],
        label: 'Strategy Model Service', technology: 'Application service' }] }}
        currentStep={-1} activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
      const title = container.querySelector('.node-title')!;
      const lines = Array.from(title.querySelectorAll('tspan'));
      expect(lines).toHaveLength(2);
      expect(title.getAttribute('font-weight')).toBe('500');
      expect(Number(lines[1].getAttribute('y')) - Number(lines[0].getAttribute('y'))).toBe(20);
      const subtitleY = Number(container.querySelector('.node-technology tspan')!.getAttribute('y'));
      expect(subtitleY - Number(lines[1].getAttribute('y'))).toBeGreaterThanOrEqual(18);
    } finally {
      measure.mockRestore();
    }
  });

  it.each([
    { label: 'Pattern router', technology: 'Decision component', titleLines: 1, subtitleLines: 1 },
    { label: 'Production approval policy router', technology: 'Deterministic approval decision component', titleLines: 2, subtitleLines: 2 },
  ])('keeps decision text inside the shared padded card for $label', ({ label, technology, titleLines, subtitleLines }) => {
    const measure = vi.spyOn(SVGElement.prototype as SVGElement & { getBBox(): DOMRect }, 'getBBox')
      .mockImplementation(function(this: SVGElement) {
        const subtitle = this.closest('.node-technology') !== null;
        return { x: 0, y: 0, width: (this.textContent?.length ?? 0) * (subtitle ? 5 : 8), height: subtitle ? 9.6 : 17 } as DOMRect;
      });
    try {
      const onNodeClick = vi.fn();
      const onNodeEdit = vi.fn();
      const decisionGraph = { ...graph, nodes: [{ ...graph.nodes[0], type: 'decision' as const, label, technology }] };
      const { container } = render(<D3Graph graphData={decisionGraph} currentStep={-1}
        activeNodeIds={new Set<string>()} onNodeClick={onNodeClick} onNodeEdit={onNodeEdit} navigation />);
      const node = container.querySelector<SVGGElement>('g.node')!;
      const card = node.querySelector<SVGRectElement>('rect.node-card')!;
      expect(node.querySelector('path.node-card')).toBeNull();
      expect(card.getAttribute('x')).toBe(String(-NODE_W / 2));
      expect(card.getAttribute('y')).toBe(String(-NODE_H / 2));
      expect(card.getAttribute('width')).toBe(String(NODE_W));
      expect(card.getAttribute('height')).toBe(String(NODE_H));
      expect(card.getAttribute('rx')).toBe(String(NODE_RX));
      expect(card.getAttribute('stroke')).toBe(TYPE_STYLE.decision.stroke);
      expect(node.querySelector(`rect[x="${-NODE_W / 2}"][width="3"]`)).not.toBeNull();

      const title = Array.from(node.querySelectorAll<SVGTSpanElement>('.node-title tspan'));
      const subtitle = Array.from(node.querySelectorAll<SVGTSpanElement>('.node-technology tspan'));
      expect(title).toHaveLength(titleLines);
      expect(subtitle).toHaveLength(subtitleLines);
      expect(title.map(line => line.textContent).join(' ')).toBe(label);
      expect(subtitle.map(line => line.textContent).join(' ')).toBe(technology);
      for (const line of [...title, ...subtitle]) {
        const halfWidth = line.getBBox().width / 2;
        const halfHeight = line.getBBox().height / 2;
        expect(halfWidth).toBeLessThanOrEqual(NODE_W / 2 - 12);
        expect(Math.abs(Number(line.getAttribute('y'))) + halfHeight).toBeLessThan(NODE_H / 2 - 1);
      }
      const titleBottom = Math.max(...title.map(line => Number(line.getAttribute('y')) + line.getBBox().height / 2));
      const subtitleTop = Math.min(...subtitle.map(line => Number(line.getAttribute('y')) - line.getBBox().height / 2));
      expect(subtitleTop - titleBottom).toBeGreaterThan(1);

      fireEvent.keyDown(node, { key: 'Enter' });
      fireEvent.keyDown(node, { key: 'F2' });
      expect(onNodeClick).toHaveBeenCalledTimes(1);
      expect(onNodeEdit).toHaveBeenCalledTimes(1);
    } finally {
      measure.mockRestore();
    }
  });

  it('renders the saved trading diagram horizontally without overlapping zone frames or overview labels', () => {
    const { container } = render(<D3Graph graphData={tradingBotSavedGraph as unknown as GraphData}
      currentStep={-1} activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    const positions = Array.from(container.querySelectorAll('g.node')).map(node => {
      const match = node.getAttribute('transform')!.match(/translate\(([^,]+),\s*([^)]+)\)/)!;
      return { x: Number(match[1]), y: Number(match[2]) };
    });
    expect(positions).toHaveLength(12);
    const width = Math.max(...positions.map(p => p.x)) - Math.min(...positions.map(p => p.x));
    const height = Math.max(...positions.map(p => p.y)) - Math.min(...positions.map(p => p.y));
    expect(width).toBeGreaterThan(height);
    const regions = Array.from(container.querySelectorAll<SVGRectElement>('.group-box > rect')).map(rect => ({
      id: rect.parentElement!.getAttribute('data-group-id'),
      x: Number(rect.getAttribute('x')), y: Number(rect.getAttribute('y')),
      width: Number(rect.getAttribute('width')), height: Number(rect.getAttribute('height')),
    }));
    expect(regions).toHaveLength(tradingBotSavedGraph.groups.length);
    for (const region of regions) {
      const members = tradingBotSavedGraph.groups.find(group => group.id === region.id)!.nodeIds;
      for (const node of container.querySelectorAll('g.node')) {
        const match = node.getAttribute('transform')!.match(/translate\(([^,]+),\s*([^)]+)\)/)!;
        const x = Number(match[1]), y = Number(match[2]);
        const inside = x > region.x && x < region.x + region.width
          && y > region.y && y < region.y + region.height;
        expect(inside).toBe(members.includes(node.getAttribute('data-node-id')!));
      }
      for (const other of regions.filter(other => other !== region)) {
        expect(region.y + region.height <= other.y || other.y + other.height <= region.y
          || region.x + region.width <= other.x || other.x + other.width <= region.x).toBe(true);
      }
    }
    expect(Array.from(container.querySelectorAll('.group-labels-layer text')).map(label => label.textContent))
      .toEqual(tradingBotSavedGraph.groups.map(group => group.label));
    expect(Array.from(container.querySelectorAll<SVGGElement>('.edge-label'))
      .every(label => label.style.opacity === '0')).toBe(true);
    const connections = diagramConnections(tradingBotSavedGraph.edges as GraphEdge[]);
    expect(container.querySelectorAll('.edge-vis')).toHaveLength(connections.length);
    expect(connections.length).toBeLessThan(tradingBotSavedGraph.edges.length);
    expect(container.querySelectorAll('.node-group-label')).toHaveLength(0);
    const ledger = container.querySelector('[data-node-id="n8"]')!;
    expect(ledger.querySelector('.node-title')?.textContent).toBe('Portfolio Ledger');
    expect(ledger.querySelector('.node-technology')?.textContent).toBe('Data store');
    expect(ledger.querySelector('title')?.textContent).toContain(tradingBotSavedGraph.nodes.find(node => node.id === 'n8')!.description);
    fireEvent.mouseOver(ledger);
    expect(Array.from(container.querySelectorAll<SVGGElement>('.edge-label'))
      .every(label => label.style.opacity === '0')).toBe(true);
    fireEvent.mouseOut(ledger);
    fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
    expect(Array.from(container.querySelectorAll<SVGGElement>('.edge-label'))
      .every(label => label.style.opacity === '0')).toBe(true);
    const edgeIndex = connections.findIndex(connection => connection.members.some(edge => edge.target === 'n8'));
    fireEvent.mouseOver(container.querySelectorAll('.edge-hit')[edgeIndex]);
    expect(screen.getByRole('tooltip').textContent).toContain('Portfolio Ledger');
    fireEvent.click(container.querySelectorAll('.edge-hit')[edgeIndex]);
    const details = screen.getByRole('region', { name: 'Connection details' });
    for (const member of connections[edgeIndex].members) expect(details.textContent).toContain(member.label);
    fireEvent.keyDown(details, { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Connection details' })).toBeNull();
    fireEvent.mouseOut(container.querySelectorAll('.edge-hit')[edgeIndex]);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('exposes every directed member of bundled and individual edge paths', () => {
    const parallelGraph: GraphData = {
      ...graph,
      nodes: ['a', 'b'].map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [
        edge('a', 'b', 'reads'),
        edge('b', 'a', 'returns'),
        edge('a', 'b', 'reads'),
        edge('a', 'b', 'queries'),
      ],
    };
    const members = (path: Element): Array<{ source: string; target: string; label: string }> =>
      JSON.parse(path.getAttribute('data-connection-members') ?? 'null');
    const navigationView = render(<D3Graph graphData={parallelGraph} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    const bundle = navigationView.container.querySelectorAll('path.edge-vis');
    expect(bundle).toHaveLength(1);
    expect(bundle[0].getAttribute('data-connection-count')).toBe('4');
    expect(members(bundle[0])).toEqual([
      { source: 'a', target: 'b', label: 'queries' },
      { source: 'a', target: 'b', label: 'reads' },
      { source: 'a', target: 'b', label: 'reads' },
      { source: 'b', target: 'a', label: 'returns' },
    ]);
    navigationView.unmount();

    const individualView = render(<D3Graph graphData={parallelGraph} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} />);
    const individualPaths = Array.from(individualView.container.querySelectorAll('path.edge-vis'));
    expect(individualPaths).toHaveLength(4);
    expect(individualPaths.map(path => members(path))).toEqual(parallelGraph.edges.map(edge => [
      { source: edge.source, target: edge.target, label: edge.label },
    ]));
    expect(individualPaths.every(path => path.getAttribute('data-connection-count') === '1')).toBe(true);
  });

  it('orders the accepted marketing request and reply motif by canonical cycle breaks', () => {
    const marketingGraph: GraphData = {
      ...graph,
      nodes: [
        { ...graph.nodes[0], id: 'reviewer', label: 'Marketing reviewer', type: 'client' },
        { ...graph.nodes[0], id: 'metrics', label: 'Metrics ingestion' },
        { ...graph.nodes[0], id: 'snapshot', label: 'Campaign metrics store', type: 'datastore' },
        { ...graph.nodes[0], id: 'proposal', label: 'Proposal generation' },
        { ...graph.nodes[0], id: 'validation', label: 'Proposal validation' },
      ],
      edges: [
        edge('metrics', 'snapshot', 'Store normalized snapshot'),
        edge('snapshot', 'metrics', 'Snapshot stored'),
        edge('proposal', 'snapshot', 'Read scoped snapshot'),
        edge('snapshot', 'proposal', 'Return validated snapshot'),
        edge('proposal', 'validation', 'Submit typed proposal'),
        edge('validation', 'proposal', 'Return validation result'),
        edge('reviewer', 'validation', 'Request proposal review'),
        edge('validation', 'reviewer', 'Present validated proposal'),
        edge('reviewer', 'proposal', 'Request rollback proposal'),
        edge('proposal', 'reviewer', 'Return rollback proposal'),
      ],
      groups: [
        { id: 'review', label: 'Human review', kind: 'operations', nodeIds: ['reviewer'] },
        { id: 'services', label: 'Conversation services', kind: 'runtime', nodeIds: ['metrics', 'proposal', 'validation'] },
        { id: 'data', label: 'Data stores', kind: 'data', nodeIds: ['snapshot'] },
      ],
      sequence: [
        { step: 1, nodes: ['metrics'], description: 'Collect metrics' },
        { step: 2, nodes: ['proposal'], description: 'Generate proposal' },
        { step: 3, nodes: ['validation'], description: 'Validate proposal' },
      ],
      view_state: undefined,
    };
    const view = render(<D3Graph graphData={marketingGraph} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    const { container } = view;
    const x = (id: string) => Number(container.querySelector(`[data-node-id="${id}"]`)!
      .getAttribute('transform')!.match(/translate\(([^,]+),/)![1]);
    expect(x('metrics')).toBeLessThan(x('proposal'));
    expect(x('proposal')).toBeLessThan(x('validation'));
    expect(container.querySelectorAll('g.node')).toHaveLength(marketingGraph.nodes.length);
    const bundles = Array.from(container.querySelectorAll('path.edge-vis'));
    expect(bundles).toHaveLength(5);
    expect(bundles.every(path => path.getAttribute('data-connection-count') === '2')).toBe(true);
    const connectionMembers = (path: Element): Array<{ source: string; target: string; label: string }> =>
      JSON.parse(path.getAttribute('data-connection-members') ?? '[]');
    const members = bundles.flatMap(connectionMembers);
    expect(members.map(({ source, target, label }) => `${source}:${target}:${label}`).sort())
      .toEqual(marketingGraph.edges.map(({ source, target, label }) => `${source}:${target}:${label}`).sort());
    const servicePositions = ['metrics', 'proposal', 'validation'].map(x);
    view.rerender(<D3Graph graphData={{ ...marketingGraph, edges: [...marketingGraph.edges].reverse() }}
      currentStep={-1} activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    expect(['metrics', 'proposal', 'validation'].map(x)).toEqual(servicePositions);
  });

  it('keeps longest-path DAG ranks with duplicate links, a self-link, feedback, and a disconnected node', () => {
    const dagGraph: GraphData = {
      ...graph,
      design_origin: undefined,
      nodes: ['a', 'b', 'c', 'd', 'e', 'f'].map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [
        edge('a', 'b', 'First path'), edge('a', 'c', 'Second path'),
        edge('b', 'd', 'First join'), edge('c', 'd', 'Second join'), edge('d', 'e', 'Finish'),
        edge('a', 'b', 'Repeated first path'), edge('b', 'b', 'Self reference'),
        { ...edge('e', 'a', 'Return signal'), flow: 'feedback' },
      ],
      view_state: undefined,
    };
    const props = { currentStep: -1, activeNodeIds: new Set<string>(),
      onNodeClick: () => undefined, navigation: true };
    const view = render(<D3Graph {...props} graphData={dagGraph} />);
    const positions = () => Object.fromEntries(dagGraph.nodes.map(node => [node.id,
      Number(view.container.querySelector(`[data-node-id="${node.id}"]`)!
        .getAttribute('transform')!.match(/translate\(([^,]+),/)![1])]));
    const initial = positions();
    expect(initial.b).toBe(initial.c);
    expect(initial.f).toBe(initial.a);
    expect(initial.b - initial.a).toBe(initial.d - initial.b);
    expect(initial.e - initial.d).toBe(initial.b - initial.a);
    view.rerender(<D3Graph {...props} graphData={{ ...dagGraph, edges: [...dagGraph.edges].reverse() }} />);
    expect(positions()).toEqual(initial);
  });

  it('keeps deep interactive graphs left to right and discloses return connections on focus', () => {
    const ids = Array.from({ length: 12 }, (_, index) => `stage${index}`);
    const chain: GraphData = {
      ...graph,
      nodes: ids.map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [
        ...ids.slice(1).map((id, index) => edge(ids[index], id, 'Continue')),
        { ...edge(ids[11], ids[0], 'Return outcome'), flow: 'feedback' },
      ],
    };
    const { container } = render(<D3Graph graphData={chain} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} navigation />);
    const positions = ids.map(id => {
      const match = container.querySelector(`[data-node-id="${id}"]`)!
        .getAttribute('transform')!.match(/translate\(([^,]+),\s*([^)]+)\)/)!;
      return { x: Number(match[1]), y: Number(match[2]) };
    });
    expect(new Set(positions.map(position => position.y)).size).toBe(1);
    expect(positions.slice(1).every((position, index) => position.x > positions[index].x)).toBe(true);
    const returnPath = container.querySelector<SVGPathElement>('[data-edge-label="Return outcome"]')!;
    expect(returnPath.style.opacity).toBe('0');
    const firstNode = screen.getByRole('button', { name: 'Explore stage0' });
    fireEvent.focus(firstNode);
    expect(returnPath.style.opacity).toBe('1');
    fireEvent.blur(firstNode);
    expect(returnPath.style.opacity).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
    expect(returnPath.style.opacity).toBe('0.4');
    expect(screen.getByRole('button', { name: 'Connections' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps a three-stage flow aligned across group boundaries with local return routes', () => {
    const chain: GraphData = {
      ...graph,
      nodes: ['client', 'service', 'model'].map(id => ({ ...graph.nodes[0], id, label: id })),
      edges: [edge('client', 'service', 'Upload'), edge('service', 'client', 'Summary'),
        edge('service', 'model', 'Prompt'), edge('model', 'service', 'Result')],
      groups: [
        { id: 'runtime', label: 'Runtime', kind: 'runtime', nodeIds: ['client', 'service'] },
        { id: 'external', label: 'External', kind: 'external', nodeIds: ['model'] },
      ],
    };
    const { container } = render(<D3Graph graphData={chain} currentStep={-1}
      activeNodeIds={new Set<string>()} onNodeClick={() => undefined} />);
    const positions = ['client', 'service', 'model'].map(id => (
      container.querySelector(`[data-node-id="${id}"]`)?.getAttribute('transform')?.match(/translate\(([^,]+),\s*([^)]+)\)/)
    ));
    expect(positions.every(position => position !== null && position !== undefined)).toBe(true);
    expect(new Set(positions.map(position => position?.[2])).size).toBe(1);
  });

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

  it('opens node editing on double-click or F2 without zooming or exploring', async () => {
    const onNodeClick = vi.fn();
    const onNodeEdit = vi.fn();
    const saveView = vi.fn();
    render(<D3Graph graphData={graph} currentStep={-1} activeNodeIds={new Set<string>()}
      navigation onNodeClick={onNodeClick} onNodeEdit={onNodeEdit} onViewStateChange={saveView} />);
    const node = screen.getByRole('button', { name: 'Explore Sensor Gateway' });
    const initialViewport = saveView.mock.lastCall![0].viewport;
    expect(node.getAttribute('aria-description')).toContain('F2');

    fireEvent.click(node, { detail: 1 });
    fireEvent.click(node, { detail: 2 });
    fireEvent.doubleClick(node);
    expect(onNodeEdit).toHaveBeenCalledTimes(1);
    expect(onNodeClick).not.toHaveBeenCalled();
    expect(saveView.mock.lastCall![0].viewport).toEqual(initialViewport);
    await new Promise(resolve => window.setTimeout(resolve, 380));
    expect(onNodeClick).not.toHaveBeenCalled();

    fireEvent.keyDown(node, { key: 'F2' });
    expect(onNodeEdit).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(node, { key: 'Enter' });
    expect(onNodeClick).toHaveBeenCalledTimes(1);
  });

  it('keeps a single-click node exploration available when editing is enabled', async () => {
    const onNodeClick = vi.fn();
    render(<D3Graph graphData={graph} currentStep={-1} activeNodeIds={new Set<string>()}
      navigation onNodeClick={onNodeClick} onNodeEdit={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore Sensor Gateway' }), { detail: 1 });
    await waitFor(() => expect(onNodeClick).toHaveBeenCalledTimes(1));
  });

  it('fits feedback-only node titles without assigning runtime entry badges', () => {
    const measure = vi.spyOn(SVGElement.prototype as SVGGraphicsElement, 'getBBox').mockImplementation(function(this: SVGElement) {
      return { x: 0, y: 0, width: (this.textContent?.length ?? 0) * 9, height: 12 } as DOMRect;
    });
    const feedbackGraph: GraphData = {
      ...graph,
      nodes: [
        graph.nodes[0],
        { ...graph.nodes[0], id: 'service', label: 'Serving API', type: 'service' },
        { ...graph.nodes[0], id: 'monitor', label: 'Prototype Monitor', type: 'service' },
        { ...graph.nodes[0], id: 'queue', label: 'Flagged Run Review Queue', type: 'queue' },
      ],
      edges: [
        { ...edge('sensor_gateway', 'service', 'sends request'), flow: 'runtime' },
        { ...edge('service', 'monitor', 'emits telemetry'), flow: 'feedback' },
        { ...edge('monitor', 'queue', 'flags run'), flow: 'feedback' },
        { ...edge('monitor', 'sensor_gateway', 'reports status'), flow: 'feedback' },
      ],
    };

    try {
      const { container } = render(
        <D3Graph
          graphData={feedbackGraph}
          currentStep={-1}
          activeNodeIds={new Set<string>()}
          onNodeClick={() => undefined}
        />,
      );
      const queue = screen.getByRole('button', { name: 'Explore Flagged Run Review Queue' });
      expect(Array.from(queue.querySelectorAll('.node-title tspan'), line => line.textContent))
        .toEqual(['Flagged Run', 'Review Queue']);
      expect(queue.querySelector('.node-title')?.childNodes).toHaveLength(2);
      expect(queue.querySelector('title')?.textContent).toContain('Flagged Run Review Queue');
      for (const nodeId of ['monitor', 'queue']) {
        const labels = Array.from(
          container.querySelectorAll(`[data-node-id="${nodeId}"] text`),
          text => text.textContent,
        );
        expect(labels).not.toContain('ENTRY');
        expect(labels).not.toContain('OUTCOME');
      }
      expect(screen.getByText('ENTRY').closest('[data-node-id]')?.getAttribute('data-node-id'))
        .toBe('sensor_gateway');
      expect(screen.getByText('OUTCOME').closest('[data-node-id]')?.getAttribute('data-node-id'))
        .toBe('service');
    } finally {
      measure.mockRestore();
    }
  });

  it('keeps an unplaceable label hidden on hover while exposing its edge tooltip', async () => {
    const unplaceableLabel = 'returns detailed feedback';
    const measure = vi.spyOn(SVGElement.prototype as SVGGraphicsElement, 'getBBox')
      .mockImplementation(function(this: SVGElement) {
        const width = this.closest('.edge-label')?.textContent?.includes('returns detailed') ? 10_000 : 48;
        return { x: -width / 2, y: -6, width, height: 12 } as DOMRect;
      });
    const baseGraph: GraphData = {
      ...graph,
      nodes: [graph.nodes[0], { ...graph.nodes[0], id: 'service', label: 'Serving API' }],
      edges: [{ ...edge('sensor_gateway', 'service', 'sends request'), flow: 'runtime' }],
    };
    const props = { currentStep: -1, activeNodeIds: new Set<string>(), onNodeClick: () => undefined };
    try {
      const view = render(<D3Graph {...props} graphData={baseGraph} />);
      const baselinePlacement = view.container.querySelector('g.edge-label')?.getAttribute('transform');
      view.rerender(<D3Graph {...props} graphData={{
        ...baseGraph,
        edges: [
          { ...edge('service', 'sensor_gateway', unplaceableLabel), flow: 'feedback' },
          ...baseGraph.edges,
        ],
      }} />);
      const labels = view.container.querySelectorAll('g.edge-label');
      expect(labels[0].getAttribute('display')).toBe('none');
      expect(labels[1].getAttribute('transform')).toBe(baselinePlacement);
      expect(labels[1].getAttribute('display')).not.toBe('none');

      fireEvent.mouseOver(screen.getByRole('button', { name: 'Explore Serving API' }));
      await waitFor(() => expect(labels[0].getAttribute('opacity')).toBe('1'));
      expect(labels[0].getAttribute('display')).toBe('none');
      fireEvent.mouseOver(view.container.querySelectorAll('path.edge-hit')[0]);
      expect(screen.getByText(unplaceableLabel)).toBeTruthy();
      expect(labels[0].getAttribute('display')).toBe('none');

      view.rerender(<D3Graph {...props} graphData={{
        ...baseGraph,
        edges: [{ ...edge('service', 'sensor_gateway', unplaceableLabel), flow: 'runtime' }],
      }} />);
      const requiredLabel = view.container.querySelector('g.edge-label');
      expect(requiredLabel?.getAttribute('display')).toBe('none');
      expect(requiredLabel?.getAttribute('data-overview-required')).toBe('true');
    } finally {
      measure.mockRestore();
    }
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

  it('preserves the diagram center and node positions when the canvas size changes', async () => {
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
      const save = vi.fn();
      const { container } = render(
        <div style={{ width: 760, height: 500 }}>
          <D3Graph
            graphData={graph}
            currentStep={-1}
            activeNodeIds={new Set<string>()}
            onNodeClick={() => undefined}
            onViewStateChange={save}
            navigation
          />
        </div>,
      );
      const firstNode = container.querySelector('g.node');
      const before = save.mock.lastCall![0];
      const svg = screen.getByTestId('graph-canvas');
      Object.defineProperty(svg, 'clientWidth', { configurable: true, value: 520 });
      Object.defineProperty(svg, 'clientHeight', { configurable: true, value: 720 });

      act(() => notifyResize?.([{ contentRect: { width: 520, height: 720 } }]));

      await waitFor(() => expect(firstNode?.isConnected).toBe(false));
      const after = save.mock.lastCall![0];
      expect(after.viewport.x).toBeCloseTo(before.viewport.x - 120);
      expect(after.viewport.y).toBeCloseTo(before.viewport.y + 110);
      expect(after.viewport.k).toBe(before.viewport.k);
      expect(after.nodePositions).toEqual(before.nodePositions);
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
