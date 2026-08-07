import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/api', () => ({
  updateThreadGraph: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('./D3Graph', () => ({
  D3Graph: ({ graphData, onNodeClick, onViewStateChange, initialViewState }: {
    graphData: { nodes: Array<{ id: string; label: string }> };
    onNodeClick: (node: { id: string; label: string }) => void;
    onViewStateChange?: (state: {
      layoutVersion: number;
      nodePositions: Record<string, { x: number; y: number }>;
      viewport: { x: number; y: number; k: number };
    }) => void;
    initialViewState?: { viewport: { x: number; y: number; k: number } };
  }) => (
    <div data-testid="d3-graph">
      <span data-testid="initial-view">{initialViewState?.viewport.k ?? 'none'}</span>
      <button onClick={() => onNodeClick(graphData.nodes[0])}>Select rendered node</button>
      <button onClick={() => onViewStateChange?.({
        layoutVersion: 1,
        nodePositions: { service: { x: 10, y: 20 } },
        viewport: { x: 3, y: 4, k: 1.2 },
      })}>Save view</button>
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
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(updateThreadGraph).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
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
    expect(screen.getByText('2 components · 1 zones')).toBeTruthy();
    expect(screen.getByText('Runtime')).toBeTruthy();
    expect(screen.getByText('Control')).toBeTruthy();
    expect(screen.getByText('Feedback')).toBeTruthy();
    expect(screen.getByText('Current Retrieval API')).toBeTruthy();
    expect(screen.queryByText('Stale label')).toBeNull();
    expect(screen.getByText('Revising privately · current approved diagram stays visible')).toBeTruthy();
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

  it('renders plain and active empty-graph states with workflow detail', () => {
    const view = render(<GraphCanvas {...baseProps} graphData={null} authSession={null} />);
    expect(screen.getByText('Graph will appear here')).toBeTruthy();

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
    expect(screen.getByText('Reviewing topology')).toBeTruthy();
    expect(screen.getByText('Checking publication invariants.')).toBeTruthy();
  });
});
