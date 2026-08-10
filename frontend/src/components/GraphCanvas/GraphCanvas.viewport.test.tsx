import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { GraphCandidate } from '../../types';
import { GraphCanvas } from './index';


vi.mock('./HiddenGraphEvaluator', () => ({
  HiddenGraphEvaluator: ({ candidate }: { candidate: GraphCandidate | null }) => (
    <div data-testid="evaluation-candidate">{candidate?.evaluationId ?? 'none'}</div>
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


describe('GraphCanvas candidate evaluation', () => {
  it('mounts candidate evaluation without waiting for live pane geometry', () => {
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

    expect(screen.getByTestId('evaluation-candidate').textContent).toBe('evaluation-1');
  });
});
