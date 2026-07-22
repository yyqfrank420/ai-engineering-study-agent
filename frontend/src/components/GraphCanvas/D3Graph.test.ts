import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import {
  filterRenderableEdges,
  initialFitScale,
  selectGraphOrientation,
  VERTICAL_LEVEL_H,
  VERTICAL_PAD,
  wrapNodeLabel,
} from './graphLayout';


describe('graph layout policy', () => {
  it('uses vertical flow when a deep graph would make labels unreadable', () => {
    expect(selectGraphOrientation(720, 7)).toBe('vertical');
    expect(selectGraphOrientation(720, 6)).toBe('vertical');
    expect(selectGraphOrientation(1200, 3)).toBe('horizontal');
    expect(selectGraphOrientation(1200, 6)).toBe('horizontal');
    expect(selectGraphOrientation(1200, 3, 8)).toBe('vertical');
  });

  it('keeps the maximum supported deep graph readable in the evaluation viewport', () => {
    const tenLevelLayoutHeight = 2 * VERTICAL_PAD + 10 * VERTICAL_LEVEL_H;

    expect(initialFitScale(760, 500, 760, tenLevelLayoutHeight)).toBeGreaterThanOrEqual(0.5);
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
