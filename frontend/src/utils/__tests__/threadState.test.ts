import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearThreadSnapshot,
  readThreadSnapshot,
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
});
