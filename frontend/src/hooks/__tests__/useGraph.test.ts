import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGraph } from '../useGraph';
import type { GraphData } from '../../types';

const graph = (title: string, nodePrefix: string): GraphData => ({
  graph_type: 'architecture',
  title,
  nodes: [
    {
      id: `${nodePrefix}-a`,
      label: 'Client',
      type: 'client',
      technology: 'Browser',
      description: 'Sends a request.',
      detail: null,
    },
    {
      id: `${nodePrefix}-b`,
      label: 'API',
      type: 'service',
      technology: 'FastAPI',
      description: 'Handles the request.',
      detail: null,
    },
    {
      id: `${nodePrefix}-c`,
      label: 'Store',
      type: 'datastore',
      technology: 'Postgres',
      description: 'Stores data.',
      detail: null,
    },
  ],
  edges: [
    {
      source: `${nodePrefix}-a`,
      target: `${nodePrefix}-b`,
      label: 'calls',
      technology: 'HTTPS',
      sync: 'sync',
      description: 'Client calls the API.',
    },
    {
      source: `${nodePrefix}-b`,
      target: `${nodePrefix}-c`,
      label: 'writes',
      technology: 'SQL',
      sync: 'sync',
      description: 'API writes data.',
    },
  ],
  sequence: [
    { step: 1, nodes: [`${nodePrefix}-a`], description: 'Client starts.' },
    { step: 2, nodes: [`${nodePrefix}-b`], description: 'API handles.' },
    { step: 3, nodes: [`${nodePrefix}-c`], description: 'Store persists.' },
  ],
});

describe('useGraph', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('autoplays each sequence step and then returns to overview', async () => {
    const { result } = renderHook(() => useGraph(graph('Graph A', 'a'), true));

    await act(async () => {});
    expect(result.current.currentStep).toBe(0);
    expect([...result.current.activeNodeIds]).toEqual(['a-a']);
    expect(result.current.stepDescription).toBe('Client starts.');

    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(result.current.currentStep).toBe(1);
    expect([...result.current.activeNodeIds]).toEqual(['a-b']);

    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(result.current.currentStep).toBe(2);
    expect([...result.current.activeNodeIds]).toEqual(['a-c']);

    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(result.current.currentStep).toBe(-1);
    expect([...result.current.activeNodeIds]).toEqual([]);
  });

  it('restarts autoplay when a different graph arrives', async () => {
    const { result, rerender } = renderHook(
      ({ data }) => useGraph(data, true),
      { initialProps: { data: graph('Graph A', 'a') } },
    );

    await act(async () => {});
    expect(result.current.currentStep).toBe(0);

    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(result.current.currentStep).toBe(1);

    await act(async () => {
      rerender({ data: graph('Graph B', 'b') });
    });

    expect(result.current.currentStep).toBe(0);
    expect([...result.current.activeNodeIds]).toEqual(['b-a']);
  });
});
