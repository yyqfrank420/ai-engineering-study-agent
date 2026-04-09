import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearThreadSnapshot,
  readThreadSnapshot,
  shouldPersistThreadSnapshot,
  writeThreadSnapshot,
} from '../threadState';

describe('thread snapshot helpers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('round-trips a thread snapshot through localStorage', () => {
    writeThreadSnapshot('user-1', 'thread-1', {
      title: 'Thread title',
      messages: [
        { id: 'm1', role: 'user', content: 'hello', isStreaming: false },
        { id: 'm2', role: 'assistant', content: 'world', isStreaming: true },
      ],
      graphData: null,
    });

    expect(readThreadSnapshot('user-1', 'thread-1')).toEqual({
      title: 'Thread title',
      messages: [
        { id: 'm1', role: 'user', content: 'hello', isStreaming: false },
        { id: 'm2', role: 'assistant', content: 'world', isStreaming: true },
      ],
      graphData: null,
    });
  });

  it('clears a stored thread snapshot', () => {
    writeThreadSnapshot('user-1', 'thread-1', {
      title: 'Thread title',
      messages: [],
      graphData: null,
    });

    clearThreadSnapshot('user-1', 'thread-1');

    expect(readThreadSnapshot('user-1', 'thread-1')).toBeNull();
  });

  it('normalizes legacy security nodes away from decision badges', () => {
    writeThreadSnapshot('user-1', 'thread-1', {
      title: 'Thread title',
      messages: [],
      graphData: {
        graph_type: 'concept',
        title: 'RAG Security',
        nodes: [
          {
            id: 'access_control',
            label: 'Access Control',
            type: 'decision',
            technology: 'Policy Engine',
            description: 'Authorizes retrieval and filters chunks by permission.',
            detail: null,
          },
        ],
        edges: [],
        sequence: [],
      },
    });

    expect(readThreadSnapshot('user-1', 'thread-1')?.graphData?.nodes[0]?.type).toBe('control');
  });

  it('does not persist a transiently emptier live snapshot over a richer cached thread', () => {
    expect(shouldPersistThreadSnapshot(
      {
        title: 'Thread title',
        messages: [],
        graphData: null,
      },
      {
        title: 'Thread title',
        messages: [
          { id: 'm1', role: 'user', content: 'hello', isStreaming: false },
          { id: 'm2', role: 'assistant', content: 'world', isStreaming: false },
        ],
        graphData: {
          graph_type: 'concept',
          title: 'RAG',
          nodes: [],
          edges: [],
          sequence: [],
        },
      },
    )).toBe(false);
  });

  it('persists a live snapshot once it is as complete as the cached thread', () => {
    expect(shouldPersistThreadSnapshot(
      {
        title: 'Thread title',
        messages: [
          { id: 'm1', role: 'user', content: 'hello', isStreaming: false },
          { id: 'm2', role: 'assistant', content: 'world', isStreaming: false },
          { id: 'm3', role: 'user', content: 'new turn', isStreaming: false },
        ],
        graphData: {
          graph_type: 'concept',
          title: 'RAG',
          nodes: [],
          edges: [],
          sequence: [],
        },
      },
      {
        title: 'Thread title',
        messages: [
          { id: 'm1', role: 'user', content: 'hello', isStreaming: false },
          { id: 'm2', role: 'assistant', content: 'world', isStreaming: false },
        ],
        graphData: null,
      },
    )).toBe(true);
  });
});
