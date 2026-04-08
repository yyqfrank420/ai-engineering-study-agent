// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/hooks/useAgentStream.ts
// Purpose: React hook that wraps the SSE client and dispatches incoming
//          server events to the correct state update handlers.
//          Components call sendMessage/sendNodeSelected — they never touch
//          the SSE client directly.
//
//          streamStatus semantics:
//            'connected'    — idle, ready to send
//            'generating'   — a request stream is in flight
//            'disconnected' — not used (all transient errors recover to 'connected')
//
//          providerNotice — non-null while a response is being served by the
//            OpenAI fallback (cleared on 'done').
//
// Language: TypeScript
// Connects to: services/sse.ts, types/index.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { sseClient } from '../services/sse';
import type {
  AuthSession,
  ComplexityLevel,
  GraphNotice,
  GraphData,
  GraphMode,
  Message,
  RetrievalNotice,
  SelectedNode,
  ServerEvent,
  WorkerStatus,
} from '../types';
import { graphStructureKey } from '../utils/graphStructureKey';

function makeId() {
  return Math.random().toString(36).slice(2);
}

const IDLE_WORKER_STATUS: WorkerStatus = {
  rag: null,
  graph: null,
  orchestrator: null,
  research: null,
};

const OPTIMISTIC_CHAT_STATUS: WorkerStatus = {
  ...IDLE_WORKER_STATUS,
  orchestrator: 'Question received — starting the workflow…',
};

// graphStructureKey imported from ../utils/graphStructureKey

export function useAgentStream(authSession: AuthSession | null, activeThreadId: string | null) {
  const [messages,     setMessages]     = useState<Message[]>([]);
  const [graphData,    setGraphData]    = useState<GraphData | null>(null);
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus>(IDLE_WORKER_STATUS);
  const [retrievalNotice, setRetrievalNotice] = useState<RetrievalNotice | null>(null);
  const [graphNotice, setGraphNotice] = useState<GraphNotice | null>(null);
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);

  // 'connected' = idle, 'generating' = stream in flight
  const [streamStatus, setStreamStatus] = useState<'generating' | 'connected' | 'disconnected'>('connected');

  // Non-null while the response is being served by the OpenAI fallback
  const [providerNotice, setProviderNotice] = useState<string | null>(null);

  // Tracks the ID of the assistant message currently being streamed
  const streamingIdRef = useRef<string | null>(null);
  const activeChatStreamIdRef = useRef<string | null>(null);
  const activeNodeStreamIdRef = useRef<string | null>(null);
  const userAbortedChatRef = useRef(false);

  // Caches suggested questions per node ID so repeat clicks skip the LLM call
  const suggestionsCacheRef = useRef<Map<string, string[]>>(new Map());

  const resetThreadView = useCallback(() => {
    setMessages([]);
    setGraphData(null);
    setSelectedNode(null);
    suggestionsCacheRef.current.clear();
    streamingIdRef.current = null;
    activeChatStreamIdRef.current = null;
    activeNodeStreamIdRef.current = null;
    userAbortedChatRef.current = false;
    setWorkerStatus(IDLE_WORKER_STATUS);
    setRetrievalNotice(null);
    setGraphNotice(null);
    setProviderNotice(null);
    setStreamStatus('connected');
  }, []);

  useEffect(() => {
    const offEvent = sseClient.onEvent(handleEvent);
    return () => { offEvent(); };
  // handleEvent is stable (useCallback with [] deps) so this runs once
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    resetThreadView();
  }, [activeThreadId, resetThreadView]);

  const hydrateThread = useCallback((thread: { messages: Message[]; graphData: GraphData | null }) => {
    resetThreadView();
    setMessages(thread.messages);
    setGraphData(thread.graphData);
  }, [resetThreadView]);

  const handleEvent = useCallback((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => {
    if (meta.kind === 'chat' && activeChatStreamIdRef.current !== meta.clientRequestId) {
      return;
    }
    if (meta.kind === 'node-selected' && activeNodeStreamIdRef.current !== meta.clientRequestId) {
      return;
    }

    switch (event.type) {

      case 'worker_status':
        if (meta.kind !== 'chat') break;
        setWorkerStatus(prev => ({ ...prev, [event.worker]: event.status }));
        break;

      case 'response_delta': {
        if (meta.kind !== 'chat') break;
        if (!streamingIdRef.current) {
          // First delta — create the streaming message
          const id = makeId();
          streamingIdRef.current = id;
          setMessages(prev => [...prev, {
            id, role: 'assistant', content: event.content, isStreaming: true,
          }]);
        } else {
          // Append to the existing streaming message
          const id = streamingIdRef.current;
          setMessages(prev => prev.map(m =>
            m.id === id ? { ...m, content: m.content + event.content } : m
          ));
        }
        break;
      }

      case 'provider_switch':
        if (meta.kind !== 'chat') break;
        setProviderNotice(
          event.provider === 'openai'
            ? 'Claude unavailable — responding with GPT'
            : `Responding with ${event.provider}`
        );
        break;

      case 'done':
        if (meta.kind === 'chat') {
          if (streamingIdRef.current) {
            const id = streamingIdRef.current;
            setMessages(prev => prev.map(m =>
              m.id === id ? { ...m, isStreaming: false } : m
            ));
            streamingIdRef.current = null;
          }
          setWorkerStatus(IDLE_WORKER_STATUS);
          setRetrievalNotice(null);
          setProviderNotice(null);
          setStreamStatus('connected');
        }
        break;

      case 'graph_data':
        if (meta.kind !== 'chat') break;
        setGraphData(prev => {
          if (prev && graphStructureKey(prev) === graphStructureKey(event.data)) {
            return prev;
          }
          return event.data;
        });
        break;

      case 'node_detail':
        if (meta.kind !== 'chat') break;
        setGraphData(prev => {
          if (!prev) return prev;
          if (event.graph_version && prev.version && event.graph_version !== prev.version) {
            return prev;
          }
          return {
            ...prev,
            nodes: prev.nodes.map(n =>
              n.id === event.node_id
                ? { ...n, detail: event.description, book_refs: event.book_refs }
                : n
            ),
          };
        });
        break;

      case 'suggested_questions':
        if (meta.kind !== 'node-selected') break;
        setSelectedNode(prev => {
          if (prev) {
            // Cache so the next click on this node skips the LLM call
            suggestionsCacheRef.current.set(prev.node.id, event.questions);
            return { ...prev, suggestions: event.questions };
          }
          return prev;
        });
        break;

      case 'retrieval_notice':
        if (meta.kind !== 'chat') break;
        setRetrievalNotice({
          requestId: event.request_id,
          message: event.message,
          requested: false,
        });
        break;

      case 'graph_notice':
        if (meta.kind !== 'chat') break;
        setGraphNotice({ message: event.message });
        break;

      case 'error':
        if (meta.kind === 'chat') {
          if (streamingIdRef.current) {
            const id = streamingIdRef.current;
            setMessages(prev => prev.map(m =>
              m.id === id ? { ...m, isStreaming: false } : m
            ));
            streamingIdRef.current = null;
          }
          setMessages(prev => [...prev, {
            id: makeId(), role: 'assistant',
            content: `Error: ${event.content}`, isStreaming: false,
          }]);
          setWorkerStatus(IDLE_WORKER_STATUS);
          setRetrievalNotice(null);
          setProviderNotice(null);
          setStreamStatus('connected');
        }
        break;
    }
  }, []);

  const sendMessage = useCallback((
    content: string,
    opts?: {
      complexity?: ComplexityLevel;
      graphMode?: GraphMode;
      researchEnabled?: boolean;
      displayContent?: string;
    },
  ) => {
    if (!authSession || !activeThreadId) {
      setMessages(prev => [...prev, {
        id: makeId(), role: 'assistant', content: 'Error: You must be signed in with an active thread.', isStreaming: false,
      }]);
      return;
    }
    setMessages(prev => [...prev, {
      id: makeId(),
      role: 'user',
      content: opts?.displayContent ?? content,
      isStreaming: false,
    }]);
    setGraphNotice(null);
    setStreamStatus('generating');
    setWorkerStatus(OPTIMISTIC_CHAT_STATUS);
    userAbortedChatRef.current = false;
    const clientRequestId = makeId();
    activeChatStreamIdRef.current = clientRequestId;

    sseClient.sendMessage(authSession, activeThreadId, content, opts, clientRequestId).then(sawDone => {
      if (!sawDone && !userAbortedChatRef.current && activeChatStreamIdRef.current === clientRequestId) {
        if (streamingIdRef.current) {
          const id = streamingIdRef.current;
          setMessages(prev => prev.map(m =>
            m.id === id ? { ...m, isStreaming: false } : m
          ));
          streamingIdRef.current = null;
        }
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: 'Connection closed before the response finished. Please try again.',
          isStreaming: false,
        }]);
        setWorkerStatus(IDLE_WORKER_STATUS);
        setStreamStatus('connected');
      }
    }).catch(err => {
      // Network-level failure (not an SSE error event)
      if (streamingIdRef.current) {
        const id = streamingIdRef.current;
        setMessages(prev => prev.map(m =>
          m.id === id ? { ...m, isStreaming: false } : m
        ));
        streamingIdRef.current = null;
      }
      setMessages(prev => [...prev, {
        id: makeId(), role: 'assistant',
        content: `Connection error: ${err.message}`, isStreaming: false,
      }]);
      setWorkerStatus(IDLE_WORKER_STATUS);
      setStreamStatus('connected');
    }).finally(() => {
      if (activeChatStreamIdRef.current === clientRequestId) {
        activeChatStreamIdRef.current = null;
      }
      userAbortedChatRef.current = false;
    });
  }, [activeThreadId, authSession]);

  const requestSearchTool = useCallback(async () => {
    if (!authSession || !activeThreadId || !retrievalNotice || retrievalNotice.requested) {
      return;
    }

    setRetrievalNotice({ ...retrievalNotice, requested: true });
    try {
      const result = await sseClient.useSearchTool(authSession, activeThreadId, retrievalNotice.requestId);
      if (!result.ok) {
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: 'Search tool is no longer available for this response. Please ask again if you still want web context.',
          isStreaming: false,
        }]);
        setRetrievalNotice(null);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: makeId(),
        role: 'assistant',
        content: `Connection error: ${err instanceof Error ? err.message : 'Could not request search tool'}`,
        isStreaming: false,
      }]);
      setRetrievalNotice(null);
    }
  }, [activeThreadId, authSession, retrievalNotice]);

  const sendNodeSelected = useCallback((nodeId: string, title: string, description: string) => {
    if (!authSession || !activeThreadId) return;
    // Check cache — if we already have questions for this node, apply immediately
    // without hitting the backend (saves LLM cost + latency on repeat clicks)
    const cached = suggestionsCacheRef.current.get(nodeId);
    if (cached) {
      setSelectedNode(prev => prev ? { ...prev, suggestions: cached } : prev);
      return;
    }
    const clientRequestId = makeId();
    activeNodeStreamIdRef.current = clientRequestId;
    sseClient.sendNodeSelected(authSession, activeThreadId, nodeId, title, description, clientRequestId).catch(err => {
      console.error('[sse] node-selected error:', err);
    }).finally(() => {
      if (activeNodeStreamIdRef.current === clientRequestId) {
        activeNodeStreamIdRef.current = null;
      }
    });
  }, [activeThreadId, authSession]);

  const stopGeneration = useCallback(() => {
    userAbortedChatRef.current = true;
    sseClient.stopGeneration();
    // Finalise any streaming message so it renders as complete
    if (streamingIdRef.current) {
      const id = streamingIdRef.current;
      setMessages(prev => prev.map(m =>
        m.id === id ? { ...m, isStreaming: false } : m
      ));
      streamingIdRef.current = null;
    }
    setWorkerStatus(IDLE_WORKER_STATUS);
    setProviderNotice(null);
    setStreamStatus('connected');
  }, []);

  return {
    messages,
    graphData,
    workerStatus,
    retrievalNotice,
    graphNotice,
    selectedNode,
    setSelectedNode,
    streamStatus,
    providerNotice,
    hydrateThread,
    sendMessage,
    requestSearchTool,
    sendNodeSelected,
    stopGeneration,
  };
}
