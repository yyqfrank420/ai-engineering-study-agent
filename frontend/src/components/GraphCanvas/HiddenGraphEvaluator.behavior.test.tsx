import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./D3Graph', async () => {
  const React = await import('react');
  return {
    D3Graph: ({ onLayoutReady }: { onLayoutReady?: (key: string) => void }) => {
      React.useEffect(() => onLayoutReady?.('candidate-layout'), [onLayoutReady]);
      return (
        <svg width="320" height="240">
          <text>Candidate graph</text>
        </svg>
      );
    },
  };
});

vi.mock('./diagramMeasurement', () => ({
  measureDiagram: vi.fn(() => ({
    viewport_width: 320,
    viewport_height: 240,
    rendered_nodes: 2,
    rendered_edges: 1,
    overlap_count: 0,
    clipped_nodes: 0,
    minimum_text_px: 12,
  })),
}));

vi.mock('../../services/agentTransport', () => ({
  agentTransport: {
    submitDiagramEvaluation: vi.fn(() => true),
  },
}));

import { agentTransport } from '../../services/agentTransport';
import type { GraphCandidate } from '../../types';
import { measureDiagram } from './diagramMeasurement';
import { HiddenGraphEvaluator } from './HiddenGraphEvaluator';


const candidate: GraphCandidate = {
  evaluationId: 'evaluation-1',
  graphVersion: 'graph-v1',
  data: {
    graph_type: 'architecture',
    title: 'Private candidate',
    nodes: [],
    edges: [{
      source: 'one',
      target: 'two',
      label: 'routes request',
      technology: 'HTTPS',
      sync: 'sync',
      description: 'Carries a request.',
    }],
    sequence: [],
  },
};


describe('HiddenGraphEvaluator browser boundary', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:candidate'),
      revokeObjectURL: vi.fn(),
    });
    class LoadedImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal('Image', LoadedImage);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillStyle: '',
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/jpeg;base64,candidate',
    );
    vi.mocked(agentTransport.submitDiagramEvaluation).mockReturnValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('measures, rasterizes, and submits one private candidate', async () => {
    const view = render(
      <HiddenGraphEvaluator candidate={candidate} viewport={{ width: 320, height: 240 }} />,
    );

    await act(async () => vi.runAllTimersAsync());

    expect(measureDiagram).toHaveBeenCalledWith(expect.any(SVGSVGElement));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:candidate');
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1',
      'graph-v1',
      expect.objectContaining({ overlap_count: 0 }),
      'data:image/jpeg;base64,candidate',
    );

    view.rerender(
      <HiddenGraphEvaluator candidate={candidate} viewport={{ width: 400, height: 300 }} />,
    );
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(1);
  });

  it('retries a temporarily unavailable transport with bounded delays', async () => {
    vi.mocked(agentTransport.submitDiagramEvaluation)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(<HiddenGraphEvaluator candidate={candidate} viewport={{ width: 320, height: 240 }} />);

    await act(async () => vi.runAllTimersAsync());

    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledTimes(3);
  });

  it('submits a failure report with a tiny fallback image when capture fails', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
      'data:image/jpeg;base64,fallback',
    );
    render(<HiddenGraphEvaluator candidate={candidate} viewport={{ width: 320, height: 240 }} />);

    await act(async () => vi.runAllTimersAsync());

    expect(agentTransport.submitDiagramEvaluation).toHaveBeenCalledWith(
      'evaluation-1',
      'graph-v1',
      expect.objectContaining({ capture_error: 'Canvas is unavailable' }),
      'data:image/jpeg;base64,fallback',
    );
  });

  it('cancels pending work on unmount and renders nothing without a candidate', async () => {
    const view = render(
      <HiddenGraphEvaluator candidate={candidate} viewport={{ width: 320, height: 240 }} />,
    );
    view.unmount();
    await act(async () => vi.runAllTimersAsync());
    expect(agentTransport.submitDiagramEvaluation).not.toHaveBeenCalled();

    const empty = render(
      <HiddenGraphEvaluator candidate={null} viewport={{ width: 320, height: 240 }} />,
    );
    expect(empty.container.firstChild).toBeNull();
  });
});
