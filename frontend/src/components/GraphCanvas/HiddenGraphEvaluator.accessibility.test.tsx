import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../services/agentTransport', () => ({
  agentTransport: { submitDiagramEvaluation: vi.fn() },
}));

vi.mock('./D3Graph', () => ({
  D3Graph: () => <button type="button">private candidate node</button>,
}));

import { HiddenGraphEvaluator } from './HiddenGraphEvaluator';

describe('HiddenGraphEvaluator accessibility boundary', () => {
  it('makes the offscreen candidate subtree inert as well as aria-hidden', () => {
    const { container } = render(
      <HiddenGraphEvaluator
        candidate={{
          evaluationId: 'eval-1',
          graphVersion: 'candidate-1',
          data: {
            graph_type: 'concept',
            title: 'Private candidate',
            version: 'candidate-1',
            nodes: [],
            edges: [],
            sequence: [],
          },
        }}
      />,
    );

    const hiddenRoot = container.querySelector('[aria-hidden="true"]');
    expect(hiddenRoot?.hasAttribute('inert')).toBe(true);
  });
});
