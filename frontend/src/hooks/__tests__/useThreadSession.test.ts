import { StrictMode } from 'react';
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
vi.mock('../../services/analytics', () => ({
  trackEvent: vi.fn().mockResolvedValue(undefined),
}));

import { createThread, fetchLatestThread, fetchThread } from '../../services/api';
import { trackEvent } from '../../services/analytics';

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

  it('hydrates the accepted overview detail level from a saved thread', async () => {
    vi.mocked(fetchThread).mockResolvedValueOnce(
      makeThreadDetail('thread-overview', 'Overview thread', [], {
        ...makeGraph('System overview'),
        detail_level: 'overview',
      }),
    );
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => result.current.handleSelectThread('thread-overview'));
    await waitFor(() => expect(result.current.threadSnapshot.graphData?.detail_level).toBe('overview'));
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

  it('ignores a stale load error after another thread is selected', async () => {
    const staleLoad = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(fetchThread).mockImplementation((_, threadId: string) => (
      threadId === 'thread-a'
        ? staleLoad.promise
        : Promise.resolve(makeThreadDetail('thread-b', 'Thread B'))
    ) as never);
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    act(() => {
      result.current.handleSelectThread('thread-a');
      result.current.handleSelectThread('thread-b');
    });
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-b'));
    await act(async () => staleLoad.reject(new Error('stale failure')));

    expect(result.current.threadError).toBeNull();
    expect(result.current.activeThreadId).toBe('thread-b');
    expect(result.current.loadingThread).toBe(false);
  });

  it('ignores a pending create result after sign-out', async () => {
    const staleCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    const clearSelection = vi.fn();
    vi.mocked(createThread).mockReturnValueOnce(staleCreate.promise as never);
    const { result, rerender } = renderHook(
      ({ authSession, backendReady }) => useThreadSession({
        authSession,
        backendReady,
        clearSelection,
      }),
      { initialProps: { authSession: TEST_SESSION as typeof TEST_SESSION | null, backendReady: true } },
    );
    expect(result.current.loadingThread).toBe(true);

    rerender({ authSession: null, backendReady: false });
    await waitFor(() => expect(result.current.loadingThread).toBe(false));
    await act(async () => staleCreate.resolve(makeThreadDetail('stale-thread', 'Stale')));

    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.threadError).toBeNull();
    expect(result.current.threadSnapshot.graphData).toBeNull();
  });

  it('does not persist or track a create result after workspace unmount', async () => {
    const staleCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread).mockReturnValueOnce(staleCreate.promise as never);
    const view = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode });
    expect(createThread).toHaveBeenCalledTimes(1);

    view.unmount();
    await act(async () => staleCreate.resolve(makeThreadDetail('stale-thread', 'Stale')));

    expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBeNull();
    expect(trackEvent).not.toHaveBeenCalledWith(
      'thread_created', expect.anything(), TEST_SESSION,
    );
  });

  it('does not persist a load result after workspace unmount', async () => {
    const staleLoad = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(fetchThread).mockReturnValueOnce(staleLoad.promise as never);
    const view = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));
    await waitFor(() => expect(view.result.current.activeThreadId).toBe('thread-initial'));

    act(() => view.result.current.handleSelectThread('thread-b'));
    const trackedBeforeUnmount = vi.mocked(trackEvent).mock.calls.length;
    view.unmount();
    localStorage.removeItem(storageKeyForThread(TEST_SESSION.user.id));
    await act(async () => staleLoad.resolve(makeThreadDetail('thread-b', 'Stale')));

    expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBeNull();
    expect(trackEvent).toHaveBeenCalledTimes(trackedBeforeUnmount);
  });

  it('reuses one pending initial create when StrictMode replays mount effects', async () => {
    const initialCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread).mockReturnValueOnce(initialCreate.promise as never);
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode });

    expect(createThread).toHaveBeenCalledTimes(1);
    expect(result.current.loadingThread).toBe(true);
    await act(async () => initialCreate.resolve(makeThreadDetail('current-thread', 'Current')));
    await waitFor(() => expect(result.current.activeThreadId).toBe('current-thread'));
    expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('current-thread');
    expect(trackEvent).toHaveBeenCalledTimes(1);
    expect(result.current.activeThreadId).toBe('current-thread');
    expect(result.current.threadError).toBeNull();
  });

  it('retains four distinct initial threads across concurrent StrictMode mounts', async () => {
    const requests = Array.from({ length: 4 }, () => deferred<ReturnType<typeof makeThreadDetail>>());
    let requestIndex = 0;
    vi.mocked(createThread).mockImplementation(() => requests[requestIndex++].promise as never);
    const views = requests.map(() => renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode }));

    expect(createThread).toHaveBeenCalledTimes(4);
    await act(async () => {
      requests.forEach((request, index) => request.resolve(makeThreadDetail(`thread-${index + 1}`, 'New chat')));
      await Promise.all(requests.map(request => request.promise));
    });
    views.forEach((view, index) => {
      expect(view.result.current.activeThreadId).toBe(`thread-${index + 1}`);
      expect(view.result.current.loadingThread).toBe(false);
    });
    expect(trackEvent).toHaveBeenCalledTimes(4);
  });

  it('creates a distinct explicit New chat while the initial request is pending', async () => {
    const initialCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    const explicitCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread)
      .mockReturnValueOnce(initialCreate.promise as never)
      .mockReturnValueOnce(explicitCreate.promise as never);
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode });

    act(() => { void result.current.handleNewChat(); });
    expect(createThread).toHaveBeenCalledTimes(2);
    await act(async () => explicitCreate.resolve(makeThreadDetail('explicit-thread', 'New chat')));
    await act(async () => initialCreate.resolve(makeThreadDetail('stale-initial-thread', 'New chat')));
    expect(result.current.activeThreadId).toBe('explicit-thread');
    expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('explicit-thread');
    expect(trackEvent).toHaveBeenCalledTimes(1);
  });

  it('does not reuse an unmounted workspace request in a new hook instance', async () => {
    const staleCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread)
      .mockReturnValueOnce(staleCreate.promise as never)
      .mockResolvedValueOnce(makeThreadDetail('remounted-thread', 'New chat') as never);
    const first = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode });
    expect(createThread).toHaveBeenCalledTimes(1);
    first.unmount();

    const second = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }), { wrapper: StrictMode });
    await waitFor(() => expect(second.result.current.activeThreadId).toBe('remounted-thread'));
    await act(async () => staleCreate.resolve(makeThreadDetail('stale-thread', 'Stale')));

    expect(createThread).toHaveBeenCalledTimes(2);
    expect(second.result.current.activeThreadId).toBe('remounted-thread');
    expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('remounted-thread');
    expect(trackEvent).toHaveBeenCalledTimes(1);
  });

  it('starts a fresh request when the same user signs back in before reset completes', async () => {
    const staleCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(createThread)
      .mockReturnValueOnce(staleCreate.promise as never)
      .mockResolvedValueOnce(makeThreadDetail('new-session-thread', 'New chat') as never);
    const clearSelection = vi.fn();
    const { result, rerender } = renderHook(
      ({ authSession }) => useThreadSession({
        authSession,
        backendReady: true,
        clearSelection,
      }),
      { initialProps: { authSession: TEST_SESSION as typeof TEST_SESSION | null }, wrapper: StrictMode },
    );

    rerender({ authSession: null });
    rerender({ authSession: TEST_SESSION });
    await waitFor(() => expect(result.current.activeThreadId).toBe('new-session-thread'));
    await act(async () => staleCreate.resolve(makeThreadDetail('stale-thread', 'Stale')));

    expect(createThread).toHaveBeenCalledTimes(2);
    expect(result.current.activeThreadId).toBe('new-session-thread');
    expect(result.current.threadError).toBeNull();
  });

  it('clears the prior account and ignores its pending create on account switch', async () => {
    const staleCreate = deferred<ReturnType<typeof makeThreadDetail>>();
    const secondSession = {
      ...TEST_SESSION,
      user: { ...TEST_SESSION.user, id: 'user-2' },
    };
    vi.mocked(createThread).mockImplementation((session) => (
      session.user.id === TEST_SESSION.user.id
        ? staleCreate.promise
        : Promise.resolve(makeThreadDetail('user-2-thread', 'New chat'))
    ) as never);
    const { result, rerender } = renderHook(
      ({ authSession }) => useThreadSession({
        authSession,
        backendReady: true,
        clearSelection: vi.fn(),
      }),
      { initialProps: { authSession: TEST_SESSION }, wrapper: StrictMode },
    );

    rerender({ authSession: secondSession });
    await waitFor(() => expect(result.current.activeThreadId).toBe('user-2-thread'));
    await act(async () => staleCreate.resolve(makeThreadDetail('user-1-thread', 'Old account')));

    expect(createThread).toHaveBeenCalledTimes(2);
    expect(result.current.activeThreadId).toBe('user-2-thread');
    expect(result.current.threadError).toBeNull();
    expect(localStorage.getItem(storageKeyForThread(secondSession.user.id))).toBe('user-2-thread');
  });

  it('clears the prior account before the new account backend is ready', async () => {
    const secondSession = {
      ...TEST_SESSION,
      user: { ...TEST_SESSION.user, id: 'user-2' },
    };
    const { result, rerender } = renderHook(
      ({ authSession, backendReady }) => useThreadSession({
        authSession,
        backendReady,
        clearSelection: vi.fn(),
      }),
      { initialProps: { authSession: TEST_SESSION, backendReady: true } },
    );
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    rerender({ authSession: secondSession, backendReady: false });
    await waitFor(() => expect(result.current.activeThreadId).toBeNull());
    expect(result.current.threadSnapshot).toEqual({ title: 'New chat', messages: [], graphData: null });
    expect(result.current.loadingThread).toBe(false);
    expect(createThread).toHaveBeenCalledTimes(1);
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
      result.current.retryThread();
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

  it('shows an initial create error and leaves a retryable empty view', async () => {
    const clearSelection = vi.fn();
    vi.mocked(createThread).mockRejectedValueOnce(new Error('private transport detail'));

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection,
    }));

    await waitFor(() => {
      expect(result.current.activeThreadId).toBeNull();
      expect(result.current.loadingThread).toBe(false);
      expect(result.current.threadError).toBe('Could not start a new chat. Try again.');
    });

    expect(clearSelection).toHaveBeenCalled();
    expect(result.current.threadSnapshot).toEqual({
      title: 'New chat',
      messages: [],
      graphData: null,
    });
  });

  it('reports a failed New chat creation and retries without clearing the draft', async () => {
    const clearSelection = vi.fn();
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection,
    }));
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    vi.mocked(createThread).mockRejectedValueOnce(new Error('private transport detail'));
    await act(async () => {
      await result.current.handleNewChat();
    });

    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.loadingThread).toBe(false);
    expect(result.current.threadError).toBe('Could not start a new chat. Try again.');
    const clearCount = clearSelection.mock.calls.length;

    vi.mocked(createThread).mockResolvedValueOnce(makeThreadDetail('thread-recovered', 'New chat') as never);
    act(() => result.current.retryThread());
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-recovered'));
    expect(result.current.threadError).toBeNull();
    expect(clearSelection).toHaveBeenCalledTimes(clearCount);
    expect(fetchLatestThread).not.toHaveBeenCalled();
  });

  it('reports a failed active-thread reload and retries that exact thread', async () => {
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    vi.mocked(fetchThread).mockRejectedValueOnce(new Error('private transport detail'));
    act(() => result.current.handleSelectThread('thread-initial'));
    await waitFor(() => expect(result.current.threadError).toBe('Could not open this chat. Try again.'));
    expect(result.current.activeThreadId).toBe('thread-initial');
    expect(result.current.loadingThread).toBe(false);

    vi.mocked(fetchThread).mockResolvedValueOnce(makeThreadDetail('thread-initial', 'Recovered') as never);
    act(() => result.current.retryThread());
    await waitFor(() => expect(result.current.threadTitle).toBe('Recovered'));
    expect(fetchThread).toHaveBeenNthCalledWith(1, TEST_SESSION, 'thread-initial');
    expect(fetchThread).toHaveBeenNthCalledWith(2, TEST_SESSION, 'thread-initial');
    expect(fetchLatestThread).not.toHaveBeenCalled();
    expect(result.current.threadError).toBeNull();
  });

  it('retries the requested chat after a failed switch instead of reloading the active chat', async () => {
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    vi.mocked(fetchThread).mockRejectedValueOnce(new Error('unavailable'));
    act(() => result.current.handleSelectThread('thread-b'));
    await waitFor(() => expect(result.current.threadError).toBe('Could not open this chat. Try again.'));
    expect(result.current.activeThreadId).toBe('thread-initial');

    vi.mocked(fetchThread).mockResolvedValueOnce(makeThreadDetail('thread-b', 'Thread B') as never);
    act(() => result.current.retryThread());
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-b'));
    expect(fetchThread).toHaveBeenNthCalledWith(1, TEST_SESSION, 'thread-b');
    expect(fetchThread).toHaveBeenNthCalledWith(2, TEST_SESSION, 'thread-b');
    expect(result.current.threadError).toBeNull();
  });

  it('keeps the newer failed selection as retry target when an older load fails', async () => {
    const staleLoad = deferred<ReturnType<typeof makeThreadDetail>>();
    vi.mocked(fetchThread)
      .mockReturnValueOnce(staleLoad.promise as never)
      .mockRejectedValueOnce(new Error('newer failure'))
      .mockResolvedValueOnce(makeThreadDetail('thread-b', 'Thread B') as never);
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    act(() => {
      result.current.handleSelectThread('thread-a');
      result.current.handleSelectThread('thread-b');
    });
    await waitFor(() => expect(result.current.threadError).toBe('Could not open this chat. Try again.'));
    await act(async () => staleLoad.reject(new Error('stale failure')));
    expect(result.current.threadError).toBe('Could not open this chat. Try again.');

    act(() => result.current.retryThread());
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-b'));
    expect(vi.mocked(fetchThread).mock.calls.map(([, id]) => id)).toEqual([
      'thread-a', 'thread-b', 'thread-b',
    ]);
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

  it('loads the latest thread after deleting the active ready thread', async () => {
    vi.mocked(fetchLatestThread).mockResolvedValueOnce(makeThreadDetail('latest-b', 'Latest B') as never);

    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));

    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    act(() => {
      result.current.handleDeleteThread('thread-initial');
    });

    await waitFor(() => {
      expect(result.current.activeThreadId).toBe('latest-b');
      expect(localStorage.getItem(storageKeyForThread(TEST_SESSION.user.id))).toBe('latest-b');
    });
  });

  it('retries the latest-thread fallback after its load fails', async () => {
    vi.mocked(fetchLatestThread)
      .mockRejectedValueOnce(new Error('unavailable'))
      .mockResolvedValueOnce(makeThreadDetail('fallback', 'Fallback') as never);
    const { result } = renderHook(() => useThreadSession({
      authSession: TEST_SESSION,
      backendReady: true,
      clearSelection: vi.fn(),
    }));
    await waitFor(() => expect(result.current.activeThreadId).toBe('thread-initial'));

    act(() => result.current.handleDeleteThread('thread-initial'));
    await waitFor(() => expect(result.current.threadError).toBe('Could not open this chat. Try again.'));
    expect(result.current.activeThreadId).toBeNull();

    act(() => result.current.retryThread());
    await waitFor(() => expect(result.current.activeThreadId).toBe('fallback'));
    expect(fetchLatestThread).toHaveBeenCalledTimes(2);
    expect(createThread).toHaveBeenCalledTimes(1);
    expect(result.current.threadError).toBeNull();
  });
});
