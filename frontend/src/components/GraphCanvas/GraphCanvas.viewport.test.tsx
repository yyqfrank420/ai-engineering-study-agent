import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { GraphCandidate } from '../../types';
import { GraphCanvas } from './index';


vi.mock('./HiddenGraphEvaluator', () => ({
  HiddenGraphEvaluator: ({ viewport }: { viewport: { width: number; height: number } }) => (
    <div data-testid="evaluation-viewport">{viewport.width}x{viewport.height}</div>
  ),
}));


const candidate: GraphCandidate = {
  evaluationId: 'evaluation-1',
  graphVersion: 'graph-1',
  data: {
    graph_type: 'architecture',
    design_origin: 'applied',
    title: 'Private candidate',
    nodes: [],
    edges: [],
    sequence: [],
  },
};


describe('GraphCanvas candidate viewport', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('waits through zero-width reveal and tracks the narrow settled host viewport', () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    class TestResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', TestResizeObserver);

    render(
      <GraphCanvas
        graphData={null}
        animateSequence={false}
        authSession={null}
        activeThreadId={null}
        onNodeClick={() => undefined}
        onTellMeMore={() => undefined}
        onExpandGraph={() => undefined}
        selectedNode={null}
        onClosePopup={() => undefined}
        sourceTexts={[]}
        graphCandidate={candidate}
      />,
    );

    // JSDOM starts the host at zero size, matching SplitPane's reveal origin.
    expect(screen.queryByTestId('evaluation-viewport')).toBeNull();

    act(() => {
      resizeCallback?.([
        { contentRect: { width: 408.4, height: 462.2 } } as ResizeObserverEntry,
      ], {} as ResizeObserver);
    });

    expect(screen.getByTestId('evaluation-viewport').textContent).toBe('408x462');

    act(() => {
      resizeCallback?.([
        { contentRect: { width: 376.2, height: 462.2 } } as ResizeObserverEntry,
      ], {} as ResizeObserver);
    });

    expect(screen.getByTestId('evaluation-viewport').textContent).toBe('376x462');
    expect(screen.queryByText('760x500')).toBeNull();
  });
});
