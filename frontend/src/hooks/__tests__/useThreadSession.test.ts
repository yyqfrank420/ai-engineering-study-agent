import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useThreadSession } from '../useThreadSession';
import type { GraphData } from '../../types';
import { storageKeyForThread } from '../../utils/threadState';

vi.mock('../../services/api', () => ({
  captureAnalyticsEvent: vi.fn().mockResolvedValue(undefined),
  createThread: vi.fn(),
  fetchLatestThread: vi.fn(),
  fetchThread: vi.fn(),
}));

import { createThread, fetchLatestThread, fetchThread } from '../../services/api';

const TEST_SESSION = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: {
    id: 'user-1',
    email: 'friend@example.com',
  },
};

function makeThreadDetail(
  threadId: string,
  title: string,
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string }> = [],
  graphData: GraphData | null = null,
) {
  const now = '2026-04-05T00:00:00Z';
  return {
    thread: {
      id: threadId,
      title,
      graph_data: graphData,
      created_at: now,
      updated_at: now,
      last_seen_at: now,
    },
    messages: messages.map((message) => ({
      ...message,
      created_at: now,
    })),
  };
}

function makeGraph(title: string): GraphData {
  return {
    graph_type: 'concept',
    title,
    nodes: [],
    edges: [],
    sequence: [],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useThreadSession', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(createThread).mockResolvedValue(makeThreadDetail('thread-initial', 'New chat') as never);
    vi.mocked(fetchLatestThread).mockRejectedValue(new Error('not used'));
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it('clears the previous thread immediately when starting a new chat', async () => {
    vi.mocked(fetchThread).mockResolvedValueOnce(
      makeThreadDetail(
        'thread-old',
        'Older chat',
        [
          { id: 'm1', role: 'user', content: 'Old question' },
          { id: 'm2', role: 'assistant', content: 'Old answer' },
        ],
        makeGraph('Old graph'),
      ),
    );

    const clearSelection = vi.fn();
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection,
    }));

    act(() => {
      result.current.handleSelectThread('thread-old');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-old');
      expect(result.current.threadSnapshot.messages).toHaveLength(2);
      expect(result.current.threadSnapshot.graphData).not.toBeNull();
    });

    const createDeferred = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread).mockReturnValueOnce(createDeferred.promise as never);

    act(() => {
      result.current.handleNewChat();
    });

    expect(clearSelection).toHaveBeenCalled();
    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.threadTitle).toBe('New chat');
    expect(result.current.threadSnapshot).toEqual({
      title: 'New chat',
      messages: [],
      graphData: null,
    });
    expect(result.current.loadingThread).toBe(true);

    await act(async () => {
      createDeferred.resolve(makeThreadDetail('thread-new', 'New chat'));
      await createDeferred.promise;
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-new');
      expect(result.current.threadSnapshot.messages).toHaveLength(0);
      expect(result.current.threadSnapshot.graphData).toBeNull();
      expect(result.current.loadingThread).toBe(false);
    });
  });

  it('creates a new thread when the backend becomes ready', async () => {
    vi.mocked(createThread).mockResolvedValueOnce(
      makeThreadDetail('thread-new', 'New chat'),
    );

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    await waitFor(() => {
      expect(createThread).toHaveBeenCalledWith(TEST_SESSION);
      expect(fetchLatestThread).not.toHaveBeenCalled();
      expect(result.current.activeThreadId).toBe('thread-new');
      expect(result.current.threadTitle).toBe('New chat');
      expect(result.current.loadingThread).toBe(false);
    });
  });

  it('starts on a new thread instead of restoring a remembered thread', async () => {
    localStorage.setItem(storageKeyForThread(TEST_SESSION.user.id), 'thread-old');
    vi.mocked(createThread).mockResolvedValueOnce(
      makeThreadDetail('thread-new', 'New chat'),
    );

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    await waitFor(() => {
      expect(fetchThread).not.toHaveBeenCalled();
      expect(fetchLatestThread).not.toHaveBeenCalled();
      expect(result.current.activeThreadId).toBe('thread-new');
      expect(result.current.threadTitle).toBe('New chat');
      expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('thread-new');
    });
  });

  it('replaces the snapshot when switching to a thread with fewer messages', async () => {
    vi.mocked(fetchThread)
      .mockResolvedValueOnce(
        makeThreadDetail(
          'thread-a',
          'Thread A',
          [
            { id: 'a1', role: 'user', content: 'Question A' },
            { id: 'a2', role: 'assistant', content: 'Answer A' },
          ],
          makeGraph('Graph A'),
        ),
      )
      .mockResolvedValueOnce(
        makeThreadDetail('thread-b', 'Thread B', [], null),
      );

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => {
      result.current.handleSelectThread('thread-a');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-a');
      expect(result.current.threadSnapshot.messages).toHaveLength(2);
      expect(result.current.threadSnapshot.graphData).not.toBeNull();
    });

    act(() => {
      result.current.handleSelectThread('thread-b');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-b');
      expect(result.current.threadTitle).toBe('Thread B');
      expect(result.current.threadSnapshot).toEqual({
        title: 'Thread B',
        messages: [],
        graphData: null,
      });
    });
  });

  it('ignores stale thread responses that finish after a newer selection', async () => {
    const deferredA = deferred<ReturnType<typeof makeThreadDetail>>();
    const deferredB = deferred<ReturnType<typeof makeThreadDetail>>();

    vi.mocked(fetchThread).mockImplementation((_, threadId: string) => {
      if (threadId === 'thread-a') {
        return deferredA.promise as never;
      }
      if (threadId === 'thread-b') {
        return deferredB.promise as never;
      }
      throw new Error(`Unexpected thread id: ${threadId}`);
    });

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => {
      result.current.handleSelectThread('thread-a');
      result.current.handleSelectThread('thread-b');
    });

    await act(async () => {
      deferredB.resolve(makeThreadDetail('thread-b', 'Thread B'));
      await deferredB.promise;
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-b');
      expect(result.current.threadTitle).toBe('Thread B');
    });

    await act(async () => {
      deferredA.resolve(
        makeThreadDetail(
          'thread-a',
          'Thread A',
          [{ id: 'a1', role: 'user', content: 'late result' }],
        ),
      );
      await deferredA.promise;
    });

    expect(result.current.activeThreadId).toBe('thread-b');
    expect(result.current.threadTitle).toBe('Thread B');
    expect(result.current.threadSnapshot).toEqual({
      title: 'Thread B',
      messages: [],
      graphData: null,
    });
  });

  it('clears the deleted active thread before loading the fallback thread', async () => {
    vi.mocked(fetchThread).mockResolvedValueOnce(
      makeThreadDetail(
        'thread-a',
        'Thread A',
        [
          { id: 'a1', role: 'user', content: 'Question A' },
          { id: 'a2', role: 'assistant', content: 'Answer A' },
        ],
        makeGraph('Graph A'),
      ),
    );

    const fallbackDeferred = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(fetchLatestThread).mockReturnValueOnce(fallbackDeferred.promise as never);

    const clearSelection = vi.fn();
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection,
    }));

    act(() => {
      result.current.handleSelectThread('thread-a');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-a');
      expect(result.current.threadSnapshot.messages).toHaveLength(2);
      expect(result.current.threadSnapshot.graphData).not.toBeNull();
    });

    act(() => {
      result.current.handleDeleteThread('thread-a');
    });

    expect(clearSelection).toHaveBeenCalled();
    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.threadSnapshot).toEqual({
      title: 'New chat',
      messages: [],
      graphData: null,
    });
    expect(result.current.loadingThread).toBe(true);

    await act(async () => {
      fallbackDeferred.resolve(makeThreadDetail('thread-b', 'Thread B'));
      await fallbackDeferred.promise;
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('thread-b');
      expect(result.current.threadTitle).toBe('Thread B');
      expect(result.current.loadingThread).toBe(false);
    });
  });

  it('does not create or select threads until auth and backend are ready', async () => {
    const clearSelection = vi.fn();
    const { result, rerender } = renderHook(
      ({ authSession, backendReady }) => useThreadSession({
        authSession,
        backendReady,
        clearSelection,
      }),
      { initialProps: { authSession: null as typeof TEST_SESSION | null, backendReady: false } },
    );

    await act(async () => {
      await result.current.handleNewChat();
      result.current.handleSelectThread('thread-x');
      result.current.handleDeleteThread('thread-x');
      result.current.retryLatestThread();
    });

    expect(createThread).not.toHaveBeenCalled();
    expect(fetchThread).not.toHaveBeenCalled();
    expect(fetchLatestThread).not.toHaveBeenCalled();

    rerender({ authSession: TEST_SESSION, backendReady: false });
    await act(async () => {
      await result.current.handleNewChat();
      result.current.handleSelectThread('thread-x');
      result.current.handleDeleteThread('thread-x');
    });

    expect(createThread).not.toHaveBeenCalled();
    expect(fetchThread).not.toHaveBeenCalled();
    expect(clearSelection).not.toHaveBeenCalled();
  });

  it('logs initial create errors and clears the optimistic view', async () => {
    const clearSelection = vi.fn();
    const error = new Error('create failed');
    vi.mocked(createThread).mockRejectedValueOnce(error);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection,
    }));

    await waitFor(() => {
      expect(result.current.activeThreadId).toBeNull();
      expect(result.current.loadingThread).toBe(false);
    });

    expect(clearSelection).toHaveBeenCalled();
    expect(consoleError).toHaveBeenCalledWith('[thread] Failed to create initial thread:', 'create failed');
    consoleError.mockRestore();
  });

  it('keeps richer live state when reloading the same thread returns less data', async () => {
    vi.mocked(fetchThread)
      .mockResolvedValueOnce(
        makeThreadDetail(
          'thread-a',
          'Thread A',
          [
            { id: 'a1', role: 'user', content: 'Question A' },
            { id: 'a2', role: 'assistant', content: 'Answer A' },
          ],
          makeGraph('Graph A'),
        ),
      )
      .mockResolvedValueOnce(makeThreadDetail('thread-a', 'Thread A', [], null));

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => {
      result.current.handleSelectThread('thread-a');
    });

    await waitFor(() => {
      expect(result.current.threadSnapshot.messages).toHaveLength(2);
      expect(result.current.threadSnapshot.graphData).not.toBeNull();
    });

    act(() => {
      result.current.handleSelectThread('thread-a');
    });

    await waitFor(() => expect(fetchThread).toHaveBeenCalledTimes(2));
    expect(result.current.threadSnapshot.messages).toHaveLength(2);
    expect(result.current.threadSnapshot.graphData).not.toBeNull();
  });

  it('loads latest thread on retry and after deleting the active ready thread', async () => {
    vi.mocked(fetchLatestThread)
      .mockResolvedValueOnce(makeThreadDetail('latest-a', 'Latest A') as never)
      .mockResolvedValueOnce(makeThreadDetail('latest-b', 'Latest B') as never);

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => {
      result.current.retryLatestThread();
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('latest-a');
    });

    act(() => {
      result.current.handleDeleteThread('latest-a');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('latest-b');
      expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('latest-b');
    });
  });
});
