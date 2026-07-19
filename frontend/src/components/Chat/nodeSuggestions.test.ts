import { describe, expect, it } from 'vitest';

import { initialNodeSuggestions } from './nodeSuggestions';


describe('initialNodeSuggestions', () => {
  it('returns immediate actions scoped to a concise node label', () => {
    expect(initialNodeSuggestions('  Write   Confirmation Approval Boundary  ')).toEqual([
      'Explain Write Confirmation Approval Boundary clearly',
      'Expand graph around Write Confirmation Approval Boundary',
      'Compare Write Confirmation Approval Boundary trade-offs',
    ]);
  });

  it('uses a safe fallback for an empty label', () => {
    expect(initialNodeSuggestions('')[0]).toBe('Explain this component clearly');
  });
});
