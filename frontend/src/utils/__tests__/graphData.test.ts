import { describe, expect, it } from 'vitest';

import type { GraphData } from '../../types';
import { normalizeGraphData } from '../graphData';

const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Review',
  nodes: [{
    id: 'approval',
    label: 'Authorization decision',
    type: 'decision',
    technology: '',
    description: 'Authorization determines whether access is allowed.',
    detail: null,
  }],
  edges: [],
  sequence: [],
};

describe('normalizeGraphData', () => {
  it('retains compatibility normalization for an unedited generated node', () => {
    expect(normalizeGraphData(graph)?.nodes[0].type).toBe('control');
  });

  it('preserves a type selected by the user after save and rehydration', () => {
    const savedGraph = {
      ...graph,
      nodes: [{ ...graph.nodes[0], user_edited_fields: ['type'] }],
    };
    const normalized = normalizeGraphData(savedGraph);
    expect(normalized?.nodes[0].type).toBe('decision');
    expect(normalizeGraphData(normalized)?.nodes[0].type).toBe('decision');
  });

  it('preserves an accepted overview during normalization', () => {
    expect(normalizeGraphData({ ...graph, detail_level: 'overview' })?.detail_level).toBe('overview');
  });
});
