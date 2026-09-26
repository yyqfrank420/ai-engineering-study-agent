import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/api', () => ({
  updateThreadGraph: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('./D3Graph', () => ({
  D3Graph: ({ graphData, onNodeClick, onNodeEdit, onEditConnection, onViewStateChange, initialViewState, onLayoutReady, inspectionViewport }: {
    graphData: { nodes: Array<{ id: string; label: string }> };
    onNodeClick: (node: { id: string; label: string }) => void;
    onNodeEdit?: (node: { id: string; label: string }) => void;
    onEditConnection?: (edgeIndex: number) => void;
    onViewStateChange?: (state: {
      layoutVersion: number;
      nodePositions: Record<string, { x: number; y: number }>;
      zonePadding?: Record<string, { top: number; right: number; bottom: number; left: number }>;
      viewport: { x: number; y: number; k: number };
    }) => void;
    initialViewState?: { viewport: { x: number; y: number; k: number } };
    onLayoutReady?: (key: string) => void;
    inspectionViewport?: { nodeId: string; width: number; height: number };
  }) => (
    <div data-testid="d3-graph">
      <span data-testid="initial-view">{initialViewState?.viewport.k ?? 'none'}</span>
      <span data-testid="inspection-view">{JSON.stringify(inspectionViewport ?? null)}</span>
      <button onClick={() => onLayoutReady?.('painted-key')}>Layout ready</button>
      <button onClick={() => onNodeClick(graphData.nodes[0])}>Select rendered node</button>
      <button onClick={() => onNodeEdit?.(graphData.nodes[0])}>Edit rendered node</button>
      <button onClick={() => onEditConnection?.(0)}>Edit rendered connection</button>
      <button onClick={() => onViewStateChange?.({
        layoutVersion: 1,
        nodePositions: { service: { x: 10, y: 20 } },
        viewport: { x: 3, y: 4, k: 1.2 },
      })}>Save view</button>
      <button onClick={() => onViewStateChange?.({
        layoutVersion: 1,
        nodePositions: { service: { x: 10, y: 20 } },
        zonePadding: { runtime: { top: 10, right: 20, bottom: 30, left: 40 } },
        viewport: { x: 3, y: 4, k: 1.2 },
      })}>Save zone view</button>
    </div>
  ),
}));

vi.mock('./HiddenGraphEvaluator', () => ({
  HiddenGraphEvaluator: () => <div data-testid="hidden-evaluator" />,
}));

import { updateThreadGraph } from '../../services/api';
import type { AuthSession, GraphData } from '../../types';
import { GraphCanvas } from './index';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};

const graph: GraphData = {
  graph_type: 'architecture',
  design_origin: 'applied',
  version: 'graph-v1',
  title: 'Grounded architecture: reviewed runtime',
  nodes: [
    {
      id: 'service',
      label: 'Current Retrieval API',
      type: 'service',
      technology: 'FastAPI',
      description: 'Retrieves RAG evidence.',
      detail: null,
    },
    {
      id: 'store',
      label: 'Vector Index',
      type: 'datastore',
      technology: 'FAISS',
      description: 'Stores embeddings.',
      detail: null,
    },
  ],
  edges: [{
    source: 'service',
    target: 'store',
    label: 'queries index',
    technology: 'Vector search',
    sync: 'sync',
    flow: 'runtime',
    description: 'Retrieves evidence.',
  }],
  sequence: [
    { step: 1, nodes: ['service'], description: 'Receive request' },
    { step: 2, nodes: ['store'], description: 'Retrieve evidence' },
  ],
  groups: [{ id: 'runtime', label: 'Runtime', nodeIds: ['service', 'store'], kind: 'runtime' }],
  view_state: {
    layoutVersion: 1,
    nodePositions: {},
    viewport: { x: 0, y: 0, k: 0.9 },
  },
};

const baseProps = {
  animateSequence: false,
  authSession: session,
  activeThreadId: 'thread-1',
  onNodeClick: vi.fn(),
  onTellMeMore: vi.fn(),
  onExpandGraph: vi.fn(),
  selectedNode: null,
  onClosePopup: vi.fn(),
  sourceTexts: ['RAG calls a vector index.'],
};


describe('GraphCanvas behavior', () => {
  it('labels only an accepted overview and explains its reduced detail', () => {
    const overview = { ...graph, detail_level: 'overview' as const };
    const view = render(<GraphCanvas {...baseProps} graphData={graph} />);
    expect(screen.queryByText('Overview')).toBeNull();

    view.rerender(<GraphCanvas {...baseProps} graphData={overview} isPreview />);
    expect(screen.queryByText('Overview')).toBeNull();

    view.rerender(<GraphCanvas {...baseProps} graphData={overview} isPreview isAcceptedGraph />);
    expect(screen.getByText('Overview')).toBeTruthy();
    expect(screen.getByText('Core workflow. Supporting detail is simplified.')).toBeTruthy();
  });

  it.each([false, true])('reports visible layout readiness for preview=%s', isPreview => {
    const ready = vi.fn();
    render(<GraphCanvas {...baseProps} graphData={graph} isPreview={isPreview} onGraphReady={ready} />);
    fireEvent.click(screen.getByText('Layout ready'));
    expect(ready).toHaveBeenCalledWith('painted-key');
  });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(updateThreadGraph).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('passes measured unobscured space for side and bottom inspectors, then clears stale selection', async () => {
    let notifyResize: (() => void) | undefined;
    class TestResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as ResizeObserver);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);
    const rect = (left: number, top: number, width: number, height: number): DOMRect => ({
      left, top, width, height, right: left + width, bottom: top + height,
      x: left, y: top, toJSON: () => ({}),
    });
    const selectedNode = { node: graph.nodes[0], suggestions: [] };
    const view = render(<GraphCanvas {...baseProps} graphData={graph} selectedNode={selectedNode} />);
    const canvas = view.container.querySelector<HTMLElement>('.graph-canvas__surface')!;
    const panel = view.container.querySelector<HTMLElement>('.node-inspector')!;
    let canvasBox = rect(100, 40, 628, 500);
    let panelBox = rect(376, 52, 340, 420);
    vi.spyOn(canvas, 'getBoundingClientRect').mockImplementation(() => canvasBox);
    vi.spyOn(panel, 'getBoundingClientRect').mockImplementation(() => panelBox);

    act(() => notifyResize?.());
    expect(JSON.parse(screen.getByTestId('inspection-view').textContent!)).toEqual({
      nodeId: 'service', width: 264, height: 500,
    });

    canvasBox = rect(100, 40, 420, 500);
    panelBox = rect(112, 290, 396, 238);
    act(() => notifyResize?.());
    expect(JSON.parse(screen.getByTestId('inspection-view').textContent!)).toEqual({
      nodeId: 'service', width: 420, height: 238,
    });

    view.rerender(<GraphCanvas {...baseProps} graphData={graph}
      selectedNode={{ node: graph.nodes[1], suggestions: [] }} />);
    expect(JSON.parse(screen.getByTestId('inspection-view').textContent!)).toEqual({
      nodeId: 'store', width: 420, height: 238,
    });

    panelBox = rect(80, 52, 340, 420);
    act(() => notifyResize?.());
    expect(JSON.parse(screen.getByTestId('inspection-view').textContent!)).toEqual({
      nodeId: 'store', width: 0, height: 500,
    });
    panelBox = rect(Number.NaN, 52, 340, 420);
    act(() => notifyResize?.());
    expect(screen.getByTestId('inspection-view').textContent).toBe('null');

    view.rerender(<GraphCanvas {...baseProps} graphData={{ ...graph, nodes: [graph.nodes[1]] }}
      selectedNode={selectedNode} />);
    expect(screen.getByTestId('inspection-view').textContent).toBe('null');

    view.rerender(<GraphCanvas {...baseProps} graphData={graph} selectedNode={null} />);
    expect(screen.getByTestId('inspection-view').textContent).toBe('null');
    await act(async () => vi.advanceTimersByTime(400));
    expect(updateThreadGraph).not.toHaveBeenCalled();
  });

  it('composes the reviewed graph and persists a changed view state', async () => {
    const onNodeClick = vi.fn();
    render(
      <GraphCanvas
        {...baseProps}
        graphData={graph}
        onNodeClick={onNodeClick}
        selectedNode={{
          node: { ...graph.nodes[0], label: 'Stale label' },
          suggestions: [],
        }}
        isBuilding={true}
      />,
    );

    expect(screen.getByText('Grounded architecture')).toBeTruthy();
    expect(screen.getByText('reviewed runtime')).toBeTruthy();
    expect(screen.getByText('2 components · 2 zones')).toBeTruthy();
    expect(screen.queryByText('Runtime')).toBeNull();
    expect(screen.queryByText('Control')).toBeNull();
    expect(screen.queryByText('Feedback')).toBeNull();
    expect(screen.getByText('Current Retrieval API')).toBeTruthy();
    expect(screen.queryByText('Stale label')).toBeNull();
    expect(screen.getByText('Preparing your answer…')).toBeTruthy();
    expect(screen.getByTestId('initial-view').textContent).toBe('0.9');

    fireEvent.click(screen.getByText('Select rendered node'));
    expect(onNodeClick).toHaveBeenCalledWith(graph.nodes[0]);
    fireEvent.click(screen.getByText('Save view'));
    await act(async () => vi.advanceTimersByTime(400));

    expect(updateThreadGraph).toHaveBeenCalledWith(
      session,
      'thread-1',
      expect.objectContaining({
        title: graph.title,
        view_state: {
          layoutVersion: 1,
          nodePositions: { service: { x: 10, y: 20 } },
          viewport: { x: 3, y: 4, k: 1.2 },
        },
      }),
    );
  });

  it('dismisses and restores the sequence without discarding the graph', () => {
    render(<GraphCanvas {...baseProps} graphData={graph} />);

    fireEvent.click(screen.getByLabelText('Exit walkthrough'));
    expect(screen.queryByLabelText('Exit walkthrough')).toBeNull();
    fireEvent.click(screen.getByTitle('Show walkthrough steps'));
    expect(screen.getByLabelText('Exit walkthrough')).toBeTruthy();
  });

  it('contains persistence failures and skips writes without durable identity', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(updateThreadGraph).mockRejectedValueOnce(new Error('offline'));
    const view = render(<GraphCanvas {...baseProps} graphData={graph} />);
    fireEvent.click(screen.getByText('Save view'));
    await act(async () => vi.advanceTimersByTime(400));
    await act(async () => Promise.resolve());
    expect(error).toHaveBeenCalledWith(
      '[graph] Failed to persist graph view state:',
      expect.any(Error),
    );

    vi.mocked(updateThreadGraph).mockClear();
    view.rerender(
      <GraphCanvas
        {...baseProps}
        graphData={graph}
        authSession={null}
        activeThreadId={null}
      />,
    );
    fireEvent.click(screen.getByText('Save view'));
    await act(async () => vi.advanceTimersByTime(400));
    expect(updateThreadGraph).not.toHaveBeenCalled();
  });

  it('does not persist view changes while rendering a preview', async () => {
    render(<GraphCanvas {...baseProps} graphData={graph} isPreview={true} />);

    fireEvent.click(screen.getByText('Save view'));
    await act(async () => vi.advanceTimersByTime(400));

    expect(updateThreadGraph).not.toHaveBeenCalled();
  });

  it('persists a zone resize even when positions and viewport are unchanged', async () => {
    render(<GraphCanvas {...baseProps} graphData={{ ...graph, view_state: {
      layoutVersion: 1,
      nodePositions: { service: { x: 10, y: 20 } },
      viewport: { x: 3, y: 4, k: 1.2 },
    } }} />);
    fireEvent.click(screen.getByText('Save zone view'));
    await act(async () => vi.advanceTimersByTime(400));
    expect(updateThreadGraph).toHaveBeenCalledWith(session, 'thread-1', expect.objectContaining({
      view_state: expect.objectContaining({ zonePadding: {
        runtime: { top: 10, right: 20, bottom: 30, left: 40 },
      } }),
    }));
  });

  it('flushes the latest layout before saving content and preserves that view on rerender', async () => {
    let finishLayout: (() => void) | undefined;
    vi.mocked(updateThreadGraph).mockImplementationOnce(() => new Promise<void>(resolve => { finishLayout = resolve; }));
    const onSaveGraphEdit = vi.fn().mockResolvedValue(undefined);
    const view = render(<GraphCanvas {...baseProps} graphData={graph} onSaveGraphEdit={onSaveGraphEdit} />);
    fireEvent.click(screen.getByText('Save view'));
    fireEvent.click(screen.getByText('Edit rendered node'));
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Name' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Updated Retrieval API' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await act(async () => { await Promise.resolve(); });
    expect(updateThreadGraph).toHaveBeenCalledTimes(1);
    expect(onSaveGraphEdit).not.toHaveBeenCalled();
    expect(view.container.querySelector('[inert]')).not.toBeNull();
    expect(vi.mocked(updateThreadGraph).mock.calls[0][2].view_state?.viewport.k).toBe(1.2);

    await act(async () => { finishLayout?.(); await Promise.resolve(); });
    expect(onSaveGraphEdit).toHaveBeenCalledWith({ nodes: [{ id: 'service', label: 'Updated Retrieval API' }] });
    const savedLayout = vi.mocked(updateThreadGraph).mock.calls[0][2].view_state;
    view.rerender(<GraphCanvas {...baseProps} graphData={{ ...graph, nodes: [
      { ...graph.nodes[0], label: 'Updated Retrieval API' }, graph.nodes[1],
    ], view_state: savedLayout }} onSaveGraphEdit={onSaveGraphEdit} />);
    expect(screen.getByTestId('initial-view').textContent).toBe('1.2');
    expect(view.container.querySelector('[inert]')).toBeNull();
  });

  it('keeps the draft available to retry when the layout flush fails', async () => {
    vi.mocked(updateThreadGraph).mockRejectedValueOnce(new Error('Layout write failed'));
    const onSaveGraphEdit = vi.fn().mockResolvedValue(undefined);
    const view = render(<GraphCanvas {...baseProps} graphData={graph} onSaveGraphEdit={onSaveGraphEdit} />);
    fireEvent.click(screen.getByText('Save view'));
    fireEvent.click(screen.getByText('Edit rendered node'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Retry Retrieval API' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(onSaveGraphEdit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('Layout write failed');
    expect((screen.getByRole('textbox', { name: 'Name' }) as HTMLInputElement).value).toBe('Retry Retrieval API');
    expect(view.container.querySelector('[inert]')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(onSaveGraphEdit).toHaveBeenCalledTimes(1);
  });

  it('opens the exact directed edge for editing', async () => {
    const onSaveGraphEdit = vi.fn().mockResolvedValue(undefined);
    render(<GraphCanvas {...baseProps} graphData={graph} onSaveGraphEdit={onSaveGraphEdit} />);
    fireEvent.click(screen.getByText('Edit rendered connection'));
    const label = screen.getByRole('textbox', { name: 'Label' });
    expect(document.activeElement).toBe(label);
    expect((label as HTMLInputElement).value).toBe('queries index');
    fireEvent.change(label, { target: { value: 'reads embeddings' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(onSaveGraphEdit).toHaveBeenCalledWith({ edges: [{ index: 0, label: 'reads embeddings' }] });
  });

  it('reopens the same node and connection fields after Done', () => {
    render(<GraphCanvas {...baseProps} graphData={graph} onSaveGraphEdit={vi.fn().mockResolvedValue(undefined)} />);
    fireEvent.click(screen.getByText('Edit rendered node'));
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Name' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('textbox', { name: 'Name' })).toBeNull();
    fireEvent.click(screen.getByText('Edit rendered node'));
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Name' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    fireEvent.click(screen.getByText('Edit rendered connection'));
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Label' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    fireEvent.click(screen.getByText('Edit rendered connection'));
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Label' }));
  });

  it('keeps a dirty inspector on its current node when another node is selected', () => {
    const onNodeClick = vi.fn();
    render(<GraphCanvas {...baseProps} graphData={graph} onNodeClick={onNodeClick}
      onSaveGraphEdit={vi.fn().mockResolvedValue(undefined)} />);
    fireEvent.click(screen.getByText('Edit rendered node'));
    const name = screen.getByRole('textbox', { name: 'Name' });
    fireEvent.change(name, { target: { value: 'Unfinished name' } });
    fireEvent.click(screen.getByText('Select rendered node'));
    expect(onNodeClick).not.toHaveBeenCalled();
    expect((screen.getByRole('textbox', { name: 'Name' }) as HTMLInputElement).value).toBe('Unfinished name');
    expect(document.activeElement).toBe(name);
  });

  it('hides Dictionary while the node inspector is open', () => {
    const selectedNode = { node: graph.nodes[0], suggestions: [] };
    const view = render(<GraphCanvas {...baseProps} graphData={graph} selectedNode={selectedNode} />);
    expect(screen.getByText('Dictionary').closest('[hidden]')).not.toBeNull();
    view.rerender(<GraphCanvas {...baseProps} graphData={graph} selectedNode={null} />);
    expect(screen.getByText('Dictionary').closest('[hidden]')).toBeNull();
  });

  it('renders plain and active empty-graph states with workflow detail', () => {
    const view = render(<GraphCanvas {...baseProps} graphData={null} authSession={null} />);
    expect(screen.getByText(/No diagram was generated/)).toBeTruthy();

    view.rerender(
      <GraphCanvas
        {...baseProps}
        graphData={null}
        authSession={null}
        isBuilding={true}
        workflowProgress={[{
          phase: 'review',
          status: 'active',
          title: 'Reviewing topology',
          detail: 'Checking publication invariants.',
        }]}
      />,
    );
    expect(screen.getByText('Building your diagram…')).toBeTruthy();
    expect(screen.queryByText('Checking publication invariants.')).toBeNull();
  });
});
