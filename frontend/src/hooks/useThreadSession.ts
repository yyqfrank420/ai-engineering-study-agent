import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { createThread, fetchLatestThread, fetchThread } from '../services/api';
import {
  clearThreadSnapshot,
  mapThreadMessages,
  readThreadSnapshot,
  storageKeyForThread,
  type ThreadSnapshot,
} from '../utils/threadState';

type UseThreadSessionArgs = {
  authSession: AuthSession | null;
  backendReady: boolean;
  clearSelection: () => void;
};

export function useThreadSession({
  authSession,
  backendReady,
  clearSelection,
}: UseThreadSessionArgs) {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [threadTitle, setThreadTitle] = useState('New chat');
  const [loadingThread, setLoadingThread] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [threadSnapshot, setThreadSnapshot] = useState<ThreadSnapshot>({
    title: 'New chat',
    messages: [],
    graphData: null,
  });
  // Track which user's thread is already loaded so that token refresh events
  // (which change the authSession object reference without changing the user)
  // do not trigger a full reload and wipe live streamed state.
  const loadedUserIdRef = useRef<string | null>(null);
  const hydratedSnapshotUserIdRef = useRef<string | null>(null);
  const activeThreadIdRef = useRef<string | null>(null);
  const threadRequestSeqRef = useRef(0);

  const resetThreadState = useCallback(() => {
    loadedUserIdRef.current = null;
    hydratedSnapshotUserIdRef.current = null;
    activeThreadIdRef.current = null;
    setActiveThreadId(null);
    setThreadTitle('New chat');
    setThreadError(null);
    setThreadSnapshot({ title: 'New chat', messages: [], graphData: null });
  }, []);

  const clearActiveThreadView = useCallback(() => {
    setThreadError(null);
    setActiveThreadId(null);
    activeThreadIdRef.current = null;
    setThreadTitle('New chat');
    setThreadSnapshot({ title: 'New chat', messages: [], graphData: null });
  }, []);

  const loadThread = useCallback(
    async (session: AuthSession, threadId?: string | null) => {
      const requestSeq = ++threadRequestSeqRef.current;
      setLoadingThread(true);
      setThreadError(null);

      try {
        const detail = threadId
          ? await fetchThread(session, threadId)
          : await fetchLatestThread(session);
        if (requestSeq !== threadRequestSeqRef.current) {
          return;
        }

        const targetThreadId = detail.thread.id;
        const switchingThreads = activeThreadIdRef.current !== targetThreadId;
        setActiveThreadId(detail.thread.id);
        activeThreadIdRef.current = targetThreadId;
        setThreadTitle(detail.thread.title);
        localStorage.setItem(storageKeyForThread(session.user.id), targetThreadId);
        const fetchedSnapshot: ThreadSnapshot = {
          title: detail.thread.title,
          messages: mapThreadMessages(detail.messages),
          graphData: detail.thread.graph_data,
        };
        setThreadSnapshot(prev => {
          if (switchingThreads) {
            return fetchedSnapshot;
          }
          if (prev.messages.length > fetchedSnapshot.messages.length) {
            return prev;
          }
          if (prev.messages.length === fetchedSnapshot.messages.length && prev.graphData && !fetchedSnapshot.graphData) {
            return prev;
          }
          return fetchedSnapshot;
        });
      } finally {
        if (requestSeq === threadRequestSeqRef.current) {
          setLoadingThread(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    if (!authSession) {
      resetThreadState();
    }
  }, [authSession, resetThreadState]);

  useEffect(() => {
    if (!authSession) {
      return;
    }

    if (hydratedSnapshotUserIdRef.current === authSession.user.id) {
      return;
    }
    hydratedSnapshotUserIdRef.current = authSession.user.id;

    const rememberedThreadId = localStorage.getItem(storageKeyForThread(authSession.user.id));
    if (!rememberedThreadId) {
      return;
    }

    const cachedSnapshot = readThreadSnapshot(authSession.user.id, rememberedThreadId);
    if (!cachedSnapshot) {
      return;
    }

    setActiveThreadId(rememberedThreadId);
    activeThreadIdRef.current = rememberedThreadId;
    setThreadTitle(cachedSnapshot.title);
    setThreadSnapshot(cachedSnapshot);
  }, [authSession]);

  useEffect(() => {
    // Reset everything only on sign-out — never on backend going not-ready.
    // Wiping state when the backend TTL expires or is re-preparing would
    // destroy live streamed content that hasn't been persisted yet.
    if (!authSession) {
      resetThreadState();
      return;
    }

    // Backend warming up — preserve existing state, wait for it to become ready.
    if (!backendReady) return;

    // Guard against token refresh events: Supabase fires onAuthStateChange
    // with a new session object when the token is refreshed (same user, different
    // object reference). Re-fetching would wipe live streamed state.
    if (loadedUserIdRef.current === authSession.user.id) return;
    loadedUserIdRef.current = authSession.user.id;

    const rememberedThreadId = localStorage.getItem(storageKeyForThread(authSession.user.id));

    loadThread(authSession, rememberedThreadId).catch(async (error: unknown) => {
      if (!rememberedThreadId) {
        const message = error instanceof Error ? error.message : 'Could not connect to backend';
        console.error('[thread] Failed to load latest thread:', message);
        setThreadError(message);
        clearActiveThreadView();
        return;
      }

      localStorage.removeItem(storageKeyForThread(authSession.user.id));
      const message = error instanceof Error ? error.message : 'Could not connect to backend';
      console.error('[thread] Failed to load remembered thread, falling back to latest:', message);

      try {
        await loadThread(authSession, null);
      } catch (fallbackError: unknown) {
        const fallbackMessage = fallbackError instanceof Error ? fallbackError.message : 'Could not connect to backend';
        console.error('[thread] Failed to load latest thread after remembered-thread miss:', fallbackMessage);
        setThreadError(fallbackMessage);
        clearActiveThreadView();
      }
    });
  }, [authSession, backendReady, clearActiveThreadView, loadThread, resetThreadState]);

  const handleNewChat = useCallback(async () => {
    if (!authSession || !backendReady) {
      return;
    }

    const requestSeq = ++threadRequestSeqRef.current;
    clearSelection();
    localStorage.removeItem(storageKeyForThread(authSession.user.id));
    clearActiveThreadView();
    setLoadingThread(true);

    try {
      const detail = await createThread(authSession);
      if (requestSeq !== threadRequestSeqRef.current) {
        return;
      }
      setActiveThreadId(detail.thread.id);
      activeThreadIdRef.current = detail.thread.id;
      setThreadTitle(detail.thread.title);
      localStorage.setItem(storageKeyForThread(authSession.user.id), detail.thread.id);
      setThreadSnapshot({
        title: detail.thread.title,
        messages: mapThreadMessages(detail.messages),
        graphData: detail.thread.graph_data,
      });
    } finally {
      if (requestSeq === threadRequestSeqRef.current) {
        setLoadingThread(false);
      }
    }
  }, [authSession, backendReady, clearActiveThreadView, clearSelection]);

  const handleSelectThread = useCallback(
    (threadId: string) => {
      if (!authSession || !backendReady) {
        return;
      }

      clearSelection();
      loadThread(authSession, threadId).catch(console.error);
    },
    [authSession, backendReady, clearSelection, loadThread],
  );

  const handleDeleteThread = useCallback(
    (threadId: string) => {
      if (!authSession) {
        return;
      }

      clearThreadSnapshot(authSession.user.id, threadId);

      if (threadId !== activeThreadId || !backendReady) {
        return;
      }

      clearSelection();
      clearActiveThreadView();
      loadThread(authSession, null).catch(console.error);
    },
    [activeThreadId, authSession, backendReady, clearActiveThreadView, clearSelection, loadThread],
  );

  const retryLatestThread = useCallback(() => {
    if (!authSession) {
      return;
    }

    loadThread(authSession, null).catch(console.error);
  }, [authSession, loadThread]);

  return {
    activeThreadId,
    threadTitle,
    loadingThread,
    threadError,
    threadSnapshot,
    handleNewChat,
    handleSelectThread,
    handleDeleteThread,
    retryLatestThread,
  };
}
