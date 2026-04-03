import { useCallback, useEffect, useState } from 'react';
import type { AuthSession, GraphData, Message } from '../types';
import { createThread, fetchLatestThread, fetchThread } from '../services/api';
import { mapThreadMessages, storageKeyForThread } from '../utils/threadState';

type ThreadSnapshot = {
  messages: Message[];
  graphData: GraphData | null;
};

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
    messages: [],
    graphData: null,
  });

  const resetThreadState = useCallback(() => {
    setActiveThreadId(null);
    setThreadTitle('New chat');
    setThreadError(null);
    setThreadSnapshot({ messages: [], graphData: null });
  }, []);

  const loadThread = useCallback(
    async (session: AuthSession, threadId?: string | null) => {
      setLoadingThread(true);
      setThreadError(null);

      try {
        const detail = threadId
          ? await fetchThread(session, threadId)
          : await fetchLatestThread(session);

        setActiveThreadId(detail.thread.id);
        setThreadTitle(detail.thread.title);
        localStorage.setItem(storageKeyForThread(session.user.id), detail.thread.id);
        setThreadSnapshot({
          messages: mapThreadMessages(detail.messages),
          graphData: detail.thread.graph_data,
        });
      } finally {
        setLoadingThread(false);
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
    if (!authSession || !backendReady) {
      resetThreadState();
      return;
    }

    const rememberedThreadId = localStorage.getItem(storageKeyForThread(authSession.user.id));
    const initialLoad = rememberedThreadId
      ? loadThread(authSession, rememberedThreadId).catch(() => loadThread(authSession, null))
      : loadThread(authSession, null);

    initialLoad.catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'Could not connect to backend';
      console.error('[thread] Failed to load thread:', message);
      setThreadError(message);
    });
  }, [authSession, backendReady, loadThread, resetThreadState]);

  const handleNewChat = useCallback(async () => {
    if (!authSession || !backendReady) {
      return;
    }

    clearSelection();
    setLoadingThread(true);

    try {
      const detail = await createThread(authSession);
      setActiveThreadId(detail.thread.id);
      setThreadTitle(detail.thread.title);
      localStorage.setItem(storageKeyForThread(authSession.user.id), detail.thread.id);
      setThreadSnapshot({
        messages: mapThreadMessages(detail.messages),
        graphData: detail.thread.graph_data,
      });
    } finally {
      setLoadingThread(false);
    }
  }, [authSession, backendReady, clearSelection]);

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
      if (threadId !== activeThreadId || !authSession || !backendReady) {
        return;
      }

      loadThread(authSession, null).catch(console.error);
    },
    [activeThreadId, authSession, backendReady, loadThread],
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
