import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { trackEvent } from '../services/analytics';
import { createThread, fetchLatestThread, fetchThread } from '../services/api';
import {
  clearThreadSnapshot,
  mapThreadMessages,
  storageKeyForThread,
  type ThreadSnapshot,
} from '../utils/threadState';
import { normalizeGraphData } from '../utils/graphData';

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
  const activeThreadIdRef = useRef<string | null>(null);
  const threadRequestSeqRef = useRef(0);

  const resetThreadState = useCallback(() => {
    loadedUserIdRef.current = null;
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
        let detail: Awaited<ReturnType<typeof fetchThread>>;
        try {
          detail = threadId
            ? await fetchThread(session, threadId)
            : await fetchLatestThread(session);
        } catch (error) {
          if (requestSeq !== threadRequestSeqRef.current) {
            return;
          }
          throw error;
        }
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
          graphData: normalizeGraphData(detail.thread.graph_data),
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

  const createFreshThread = useCallback(
    async (session: AuthSession, { clearDraftState = true }: { clearDraftState?: boolean } = {}) => {
      const requestSeq = ++threadRequestSeqRef.current;
      if (clearDraftState) {
        clearSelection();
        clearActiveThreadView();
      }
      localStorage.removeItem(storageKeyForThread(session.user.id));
      setLoadingThread(true);
      setThreadError(null);

      try {
        const detail = await createThread(session);
        if (requestSeq !== threadRequestSeqRef.current) {
          return;
        }
        setActiveThreadId(detail.thread.id);
        activeThreadIdRef.current = detail.thread.id;
        setThreadTitle(detail.thread.title);
        localStorage.setItem(storageKeyForThread(session.user.id), detail.thread.id);
        void trackEvent('thread_created', { thread_id: detail.thread.id }, session);
        setThreadSnapshot({
          title: detail.thread.title,
          messages: mapThreadMessages(detail.messages),
          graphData: normalizeGraphData(detail.thread.graph_data),
        });
      } finally {
        if (requestSeq === threadRequestSeqRef.current) {
          setLoadingThread(false);
        }
      }
    },
    [clearActiveThreadView, clearSelection],
  );

  useEffect(() => {
    // Reset everything only on sign-out — never on backend going not-ready.
    // Wiping state when the backend TTL expires or is re-preparing would
    // destroy live streamed content that hasn't been persisted yet.
    if (!authSession) {
      let cancelled = false;
      queueMicrotask(() => {
        if (!cancelled) resetThreadState();
      });
      return () => {
        cancelled = true;
      };
    }

    // Backend warming up — preserve existing state, wait for it to become ready.
    if (!backendReady) return;

    // Guard against token refresh events: Supabase fires onAuthStateChange
    // with a new session object when the token is refreshed (same user, different
    // object reference). Re-fetching would wipe live streamed state.
    if (loadedUserIdRef.current === authSession.user.id) return;
    loadedUserIdRef.current = authSession.user.id;

    createFreshThread(authSession, { clearDraftState: true }).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'Could not connect to backend';
      console.error('[thread] Failed to create initial thread:', message);
      setThreadError(message);
      clearActiveThreadView();
    });
  }, [authSession, backendReady, clearActiveThreadView, createFreshThread, resetThreadState]);

  const handleNewChat = useCallback(async () => {
    if (!authSession || !backendReady) {
      return;
    }

    await createFreshThread(authSession);
  }, [authSession, backendReady, createFreshThread]);

  const handleSelectThread = useCallback(
    (threadId: string) => {
      if (!authSession || !backendReady) {
        return;
      }

      clearSelection();
      void trackEvent('thread_selected', { thread_id: threadId }, authSession);
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
      void trackEvent('thread_deleted', { thread_id: threadId }, authSession);

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
