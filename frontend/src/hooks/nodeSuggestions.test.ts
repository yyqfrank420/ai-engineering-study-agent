import { describe, expect, it } from 'vitest';

import { initialNodeSuggestions } from './nodeSuggestions';

describe('initialNodeSuggestions', () => {
  it('normalizes and bounds the selected node label', () => {
    expect(initialNodeSuggestions('  Write   Confirmation Approval Boundary  ')).toEqual([
      'Explain Write Confirmation Approval Boundary clearly',
      'Expand graph around Write Confirmation Approval Boundary',
      'Compare Write Confirmation Approval Boundary trade-offs',
    ]);
  });

  it('falls back for an empty label', () => {
    expect(initialNodeSuggestions('')[0]).toBe('Explain this component clearly');
  });
});
