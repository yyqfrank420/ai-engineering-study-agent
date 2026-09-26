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

type ThreadRequestTarget =
  | { kind: 'create' }
  | { kind: 'load'; threadId: string | null };

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
  const retryTargetRef = useRef<ThreadRequestTarget | null>(null);
  const pendingInitialCreateRef = useRef<{
    userId: string;
    request: ReturnType<typeof createThread>;
  } | null>(null);

  const resetThreadState = useCallback(() => {
    threadRequestSeqRef.current += 1;
    retryTargetRef.current = null;
    loadedUserIdRef.current = null;
    activeThreadIdRef.current = null;
    pendingInitialCreateRef.current = null;
    setActiveThreadId(null);
    setThreadTitle('New chat');
    setLoadingThread(false);
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

  useEffect(() => () => {
    // A keyed workspace can unmount before a request settles; late results must not write storage.
    threadRequestSeqRef.current += 1;
    retryTargetRef.current = null;
    loadedUserIdRef.current = null;
    activeThreadIdRef.current = null;
  }, []);

  const loadThread = useCallback(
    async (session: AuthSession, threadId?: string | null) => {
      const requestSeq = ++threadRequestSeqRef.current;
      retryTargetRef.current = { kind: 'load', threadId: threadId ?? null };
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
      } catch {
        if (requestSeq === threadRequestSeqRef.current) {
          setThreadError('Could not open this chat. Try again.');
        }
      } finally {
        if (requestSeq === threadRequestSeqRef.current) {
          setLoadingThread(false);
        }
      }
    },
    [],
  );

  const createFreshThread = useCallback(
    async (session: AuthSession, { clearDraftState = true, initialization = false }:
      { clearDraftState?: boolean; initialization?: boolean } = {}) => {
      const requestSeq = ++threadRequestSeqRef.current;
      retryTargetRef.current = { kind: 'create' };
      setLoadingThread(true);
      setThreadError(null);
      if (!initialization) pendingInitialCreateRef.current = null;
      let createRequest: ReturnType<typeof createThread> | null = null;

      try {
        if (clearDraftState) {
          clearSelection();
          clearActiveThreadView();
        }
        localStorage.removeItem(storageKeyForThread(session.user.id));
        const pending = pendingInitialCreateRef.current;
        createRequest = initialization && pending?.userId === session.user.id
          ? pending.request : createThread(session);
        if (initialization) pendingInitialCreateRef.current = {
          userId: session.user.id,
          request: createRequest,
        };
        const detail = await createRequest;
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
      } catch {
        if (requestSeq === threadRequestSeqRef.current) {
          setThreadError('Could not start a new chat. Try again.');
        }
      } finally {
        if (pendingInitialCreateRef.current?.request === createRequest) {
          pendingInitialCreateRef.current = null;
        }
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
      threadRequestSeqRef.current += 1;
      retryTargetRef.current = null;
      loadedUserIdRef.current = null;
      activeThreadIdRef.current = null;
      pendingInitialCreateRef.current = null;
      let cancelled = false;
      queueMicrotask(() => {
        if (!cancelled) resetThreadState();
      });
      return () => {
        cancelled = true;
      };
    }

    // A different account cannot retain the previous account's thread while preparing.
    if (loadedUserIdRef.current && loadedUserIdRef.current !== authSession.user.id) {
      resetThreadState();
    }

    // Backend warming up — preserve state for the same user, then retry preparation.
    if (!backendReady) return;

    // Guard against token refresh events: Supabase fires onAuthStateChange
    // with a new session object when the token is refreshed (same user, different
    // object reference). Re-fetching would wipe live streamed state.
    if (loadedUserIdRef.current === authSession.user.id) return;
    loadedUserIdRef.current = authSession.user.id;

    void createFreshThread(authSession, { clearDraftState: true, initialization: true });
  }, [authSession, backendReady, createFreshThread, resetThreadState]);

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
      void loadThread(authSession, threadId);
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
      void loadThread(authSession, null);
    },
    [activeThreadId, authSession, backendReady, clearActiveThreadView, clearSelection, loadThread],
  );

  const retryThread = useCallback(() => {
    if (!authSession || !backendReady || !retryTargetRef.current) {
      return;
    }

    const target = retryTargetRef.current;
    if (target.kind === 'load') {
      void loadThread(authSession, target.threadId);
    } else {
      void createFreshThread(authSession, { clearDraftState: false });
    }
  }, [authSession, backendReady, createFreshThread, loadThread]);

  return {
    activeThreadId,
    threadTitle,
    loadingThread,
    threadError,
    threadSnapshot,
    handleNewChat,
    handleSelectThread,
    handleDeleteThread,
    retryThread,
  };
}
