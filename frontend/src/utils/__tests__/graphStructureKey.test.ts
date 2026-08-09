import { describe, expect, it } from 'vitest';

import { graphStructureKey } from '../graphStructureKey';
import type { GraphData } from '../../types';

function graph(overrides: Partial<GraphData> = {}): GraphData {
  return {
    graph_type: 'architecture',
    title: 'RAG Pipeline',
    nodes: [
      {
        id: 'retriever',
        label: 'Retriever',
        type: 'service',
        technology: 'FAISS',
        description: 'Finds chunks.',
        tier: 'private',
        lane: 'bottom',
        detail: null,
      },
    ],
    edges: [
      {
        source: 'retriever',
        target: 'llm',
        label: 'sends context',
        technology: 'HTTPS',
        sync: 'sync',
        description: 'Sends retrieved context.',
      },
    ],
    sequence: [
      { step: 1, nodes: ['retriever'], description: 'Retrieve context.' },
    ],
    groups: [
      { id: 'backend', label: 'Backend', nodeIds: ['retriever'] },
    ],
    ...overrides,
  };
}

describe('graphStructureKey', () => {
  it('returns null key for missing graph', () => {
    expect(graphStructureKey(null)).toBe('null');
  });

  it('includes the version without hiding changed content', () => {
    const original = graph({ version: '12' });
    const changed = graph({
      version: '12',
      nodes: [{ ...original.nodes[0], id: 'replacement' }],
    });

    expect(graphStructureKey(original)).not.toBe(graphStructureKey(changed));
  });

  it('includes structural graph fields and ignores transient node fields', () => {
    const base = graph();
    const withTransientDetail = graph({
      nodes: [
        {
          ...base.nodes[0],
          detail: 'Runtime-only generated detail',
          book_refs: ['Chapter 6, p.299'],
        },
      ],
    });

    expect(graphStructureKey(withTransientDetail)).toBe(graphStructureKey(base));
  });

  it('changes when topology or labels change', () => {
    const base = graph();

    expect(graphStructureKey(graph({ title: 'Different' }))).not.toBe(graphStructureKey(base));
    expect(graphStructureKey(graph({ design_origin: 'applied' }))).not.toBe(graphStructureKey(base));
    expect(graphStructureKey(graph({
      edges: [{ ...base.edges[0], label: 'different edge' }],
    }))).not.toBe(graphStructureKey(base));
  });
});
