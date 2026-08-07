import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import {
  filterRenderableEdges,
  initialFitScale,
  overviewEdgeLabelOpacity,
  planVerticalLayout,
  selectOverviewEdgeIndices,
  selectGraphOrientation,
  VERTICAL_LEVEL_H,
  VERTICAL_PAD,
  wrapNodeLabel,
  wrapNodeTechnology,
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

  it.each([
    ['25-node mixed topology', [2, 2, 3, 2, 1, 3, 1, 1, 2, 1, 1, 2, 1, 1, 1, 1]],
    ['37-node deep topology', [4, 2, 2, 2, 4, 3, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1, 1, 1, 3, 1, 1]],
    ['39-node deep topology', [3, 2, 3, 3, 1, 5, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 2, 1, 1]],
    ['40-node mixed topology', [5, 5, 4, 4, 3, ...Array.from({ length: 19 }, () => 1)]],
  ])('plans a readable virtual canvas for a %s', (_name, levelSizes) => {
    const plan = planVerticalLayout(656, 848, levelSizes as number[]);

    expect((levelSizes as number[]).reduce((total, size) => total + size, 0)).toBeGreaterThanOrEqual(25);
    expect(15.36 * plan.scale).toBeGreaterThanOrEqual(6);
    expect(plan.nodesPerRow).toBeGreaterThan(1);
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

  it('preserves deployable technology detail across two compact lines', () => {
    expect(wrapNodeTechnology('Hybrid vector and metadata retrieval with ACL filtering')).toEqual([
      'Hybrid vector and metadata',
      'retrieval with ACL filtering',
    ]);
  });

  it('shows semantic spine labels without turning feedback into overview noise', () => {
    expect(overviewEdgeLabelOpacity({ flow: 'runtime' }, true)).toBeGreaterThan(0.7);
    expect(overviewEdgeLabelOpacity({ flow: 'control' }, true)).toBeGreaterThan(0.5);
    expect(overviewEdgeLabelOpacity({ flow: 'control' }, false)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'runtime' }, false)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'deployment' }, true)).toBe(0);
    expect(overviewEdgeLabelOpacity({ flow: 'feedback', type: 'loop' }, true)).toBe(0);
  });

  it('bounds dense out-of-sample overview labels using structure rather than domain words', () => {
    const edges = Array.from({ length: 12 }, (_, index) => ({
      source: `stage_${index}`,
      target: `stage_${index + 1}`,
      label: `moves payload ${index}`,
      technology: 'Typed event',
      sync: 'async' as const,
      description: 'Carries a versioned payload.',
      flow: index % 4 === 3 ? 'control' as const : 'runtime' as const,
    }));
    const sequence = Array.from({ length: 13 }, (_, index) => ({
      step: index + 1,
      nodes: [`stage_${index}`],
      description: `Stage ${index + 1}`,
    }));

    const selected = selectOverviewEdgeIndices(edges, sequence);

    expect(selected.size).toBe(8);
    expect([...selected].every(index => index >= 0 && index < edges.length)).toBe(true);
    expect([...selected].some(index => edges[index].flow === 'control')).toBe(true);
    expect([...selected].some(index => edges[index].flow === 'runtime')).toBe(true);
  });
});
