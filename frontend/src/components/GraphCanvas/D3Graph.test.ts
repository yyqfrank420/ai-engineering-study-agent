import { describe, expect, it } from 'vitest';
import type { GraphEdge } from '../../types';
import {
  boundLabelCenter,
  COMPACT_LAYOUT_COLUMNS,
  COMPACT_LAYOUT_ROWS,
  filterRenderableEdges,
  initialFitScale,
  isPublishedLayoutScale,
  MAX_PUBLISHED_GRAPH_NODES,
  MIN_PUBLISHED_TITLE_PX,
  NODE_TITLE_PX,
  overviewEdgeLabelOpacity,
  partitionVerticalLevels,
  planCompactLayout,
  planVerticalLayout,
  selectGraphLayout,
  selectOverviewEdgeIndices,
  VERTICAL_LEVEL_H,
  VERTICAL_PAD,
  wrapNodeLabel,
  wrapNodeTechnology,
} from './graphLayout';


describe('graph layout policy', () => {
  it('selects the first layout that meets the title-size contract', () => {
    expect(selectGraphLayout(0.75, 0.8)).toBe('horizontal');
    expect(selectGraphLayout(0.7, 0.75)).toBe('vertical');
    expect(selectGraphLayout(0.7, 0.7)).toBe('compact');
  });

  it('falls back to the rank-ordered compact grid when a 60-node vertical plan misses the title gate', () => {
    const levelSizes = Array.from({ length: 10 }, () => [1, 5]).flat();
    const verticalPlan = planVerticalLayout(1440, 960, levelSizes);
    const compactPlan = planCompactLayout(1440, 960, levelSizes.reduce((sum, size) => sum + size, 0));

    expect(levelSizes.reduce((sum, size) => sum + size, 0)).toBe(MAX_PUBLISHED_GRAPH_NODES);
    expect(NODE_TITLE_PX * verticalPlan.scale).toBeLessThan(MIN_PUBLISHED_TITLE_PX);
    expect(compactPlan.columns).toBe(COMPACT_LAYOUT_COLUMNS);
    expect(compactPlan.rows).toBe(COMPACT_LAYOUT_ROWS);
    expect(isPublishedLayoutScale(compactPlan.scale)).toBe(true);
    expect(selectGraphLayout(0.7, verticalPlan.scale)).toBe('compact');
  });

  it('proves compact capacity at the published schema boundary', () => {
    const compactPlan = planCompactLayout(1440, 960, MAX_PUBLISHED_GRAPH_NODES);

    expect(COMPACT_LAYOUT_COLUMNS * COMPACT_LAYOUT_ROWS).toBeGreaterThanOrEqual(MAX_PUBLISHED_GRAPH_NODES);
    expect(NODE_TITLE_PX * compactPlan.scale).toBeGreaterThanOrEqual(MIN_PUBLISHED_TITLE_PX);
  });

  it('keeps the maximum supported deep graph readable in the evaluation viewport', () => {
    const tenLevelLayoutHeight = 2 * VERTICAL_PAD + 10 * VERTICAL_LEVEL_H;

    expect(initialFitScale(760, 500, 760, tenLevelLayoutHeight)).toBeGreaterThanOrEqual(0.5);
  });

  it('bounds edge-label centers inside the fitted layout', () => {
    expect(boundLabelCenter(
      { x: 8, y: 152 },
      { width: 113, height: 13 },
      { width: 1440, height: 880 },
    )).toEqual({ x: 60.5, y: 152 });
    expect(boundLabelCenter(
      { x: 1432, y: 878 },
      { width: 113, height: 13 },
      { width: 1440, height: 880 },
    )).toEqual({ x: 1379.5, y: 869.5 });
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

  it('packs deep levels into deterministic alternating tracks', () => {
    const levelSizes = Array.from({ length: 42 }, () => 1);
    const plan = planVerticalLayout(1440, 960, levelSizes);
    const tracks = [...new Set(plan.levels.map(level => level.track))];

    expect(plan.levels).toHaveLength(42);
    expect(plan.scale).toBeGreaterThanOrEqual(0.9);
    expect(tracks.length).toBeGreaterThan(1);
    expect(plan.levels.map(level => level.track)).toEqual(
      [...plan.levels.map(level => level.track)].sort((left, right) => left - right),
    );
    for (const track of tracks) {
      const placements = plan.levels.filter(level => level.track === track);
      expect(new Set(placements.map(level => level.direction))).toEqual(
        new Set([track % 2 === 0 ? 1 : -1]),
      );
      const yValues = placements.map(level => level.y);
      expect(yValues).toEqual(
        [...yValues].sort((left, right) => (track % 2 === 0 ? left - right : right - left)),
      );
    }
    expect(planVerticalLayout(1440, 960, levelSizes)).toEqual(plan);
  });

  it('keeps a mixed 40-node topology above publication text size', () => {
    const levelSizes = [5, 5, 4, 4, 3, ...Array.from({ length: 19 }, () => 1)];
    const plan = planVerticalLayout(1440, 960, levelSizes);

    expect(levelSizes.reduce((total, size) => total + size, 0)).toBe(40);
    expect(plan.levels).toHaveLength(levelSizes.length);
    expect(plan.nodesPerRow).toBeGreaterThanOrEqual(3);
    expect(15.36 * plan.scale).toBeGreaterThanOrEqual(12);
    expect(plan.levels.every(level => (
      level.y >= VERTICAL_PAD
      && level.y + VERTICAL_LEVEL_H <= plan.layoutHeight - VERTICAL_PAD + VERTICAL_LEVEL_H
    ))).toBe(true);
  });

  it.each([
    [[1, 1, 5, 1, 1], 3],
    [[1, 8, 1], 3],
  ])('preserves the parallel shape of %j', (levelSizes, minimumNodesPerRow) => {
    const plan = planVerticalLayout(760, 500, levelSizes as number[]);

    expect(plan.nodesPerRow).toBeGreaterThanOrEqual(minimumNodesPerRow);
  });

  it('finds the minimum-height contiguous partition before minimizing width', () => {
    const rows = [1, 1, 1, 3, 1];
    const ranges = partitionVerticalLevels(rows, rows, 1, 3);
    const loads = ranges.map(([start, end]) => (
      rows.slice(start, end).reduce((total, value) => total + value, 0)
    ));

    expect(ranges).toEqual([[0, 3], [3, 4], [4, 5]]);
    expect(Math.max(...loads)).toBe(3);
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
