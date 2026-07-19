import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import { filterRenderableEdges, selectGraphOrientation, wrapNodeLabel } from './graphLayout';


describe('graph layout policy', () => {
  it('uses vertical flow when a deep graph would make labels unreadable', () => {
    expect(selectGraphOrientation(720, 7)).toBe('vertical');
    expect(selectGraphOrientation(1200, 3)).toBe('horizontal');
  });

  it('keeps backward edges when both endpoints exist', () => {
    const edges = [
      { source: 'a', target: 'b', label: 'forward' },
      { source: 'b', target: 'a', label: 'return' },
      { source: 'b', target: 'missing', label: 'invalid' },
    ] as GraphEdge[];

    expect(filterRenderableEdges(edges, new Set(['a', 'b']))).toEqual(edges.slice(0, 2));
  });

  it('wraps long domain labels without dropping their distinguishing words', () => {
    expect(wrapNodeLabel('AI Severity & Narrative Assistant')).toEqual([
      'AI Severity &',
      'Narrative Assistant',
    ]);
  });
});
