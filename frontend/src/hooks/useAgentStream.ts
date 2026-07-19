// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/hooks/useAgentStream.ts
// Purpose: React hook that wraps the agent transport and dispatches incoming
//          WebSocket/SSE events to the correct state update handlers.
//          Components call sendMessage/selectNode — they never touch
//          transport details directly.
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
// Connects to: services/agentTransport.ts, types/index.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { agentTransport, createClientRequestId } from '../services/agentTransport';
import { trackEvent } from '../services/analytics';
import type {
  AuthSession,
  ComplexityLevel,
  GraphCandidate,
  GraphNotice,
  GraphData,
  GraphMode,
  GraphNode,
  Message,
  RetrievalNotice,
  SelectedNode,
  ServerEvent,
  WorkerStatus,
  WorkflowProgress,
} from '../types';
import { graphStructureKey } from '../utils/graphStructureKey';
import { normalizeGraphData } from '../utils/graphData';
import { initialNodeSuggestions } from './nodeSuggestions';

function makeId() {
  return createClientRequestId();
}

const IDLE_WORKER_STATUS: WorkerStatus = {
  rag: null,
  graph: null,
  critic: null,
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
  const [graphCandidate, setGraphCandidate] = useState<GraphCandidate | null>(null);
  const [workflowProgress, setWorkflowProgress] = useState<WorkflowProgress[]>([]);
  const [explanationPaused, setExplanationPaused] = useState(false);

  // 'connected' = idle, 'generating' = stream in flight
  const [streamStatus, setStreamStatus] = useState<'generating' | 'connected' | 'disconnected'>('connected');

  // Non-null while the response is being served by the OpenAI fallback
  const [providerNotice, setProviderNotice] = useState<string | null>(null);

  // Tracks the ID of the assistant message currently being streamed
  const streamingIdRef = useRef<string | null>(null);
  const activeChatStreamIdRef = useRef<string | null>(null);
  const activeNodeStreamIdRef = useRef<string | null>(null);
  const userAbortedChatRef = useRef(false);
  const authSessionRef = useRef<AuthSession | null>(authSession);
  const graphDataRef = useRef<GraphData | null>(null);
  const selectedNodeRef = useRef<SelectedNode | null>(null);
  const activeChatTerminalRef = useRef<string | null>(null);
  const explanationPausedRef = useRef(false);
  const queuedExplanationBlocksRef = useRef<Array<{
    id: string;
    title: string;
    content: string;
    relatedNodeIds: string[];
  }>>([]);
  const activeExplanationMessageIdsRef = useRef<string[]>([]);
  const activeChatAnalyticsRef = useRef<{
    threadId: string;
    clientRequestId: string;
    complexity: ComplexityLevel;
    graphMode: GraphMode;
    researchEnabled: boolean;
    backendReadinessState?: string;
    hasSelectedTextContext?: boolean;
  } | null>(null);

  // Caches suggested questions per node ID so repeat clicks skip the LLM call
  const suggestionsCacheRef = useRef<Map<string, string[]>>(new Map());
  const lastGraphKeyRef = useRef<string>('null');

  const resetThreadView = useCallback(() => {
    setMessages([]);
    setGraphData(null);
    setSelectedNode(null);
    setGraphCandidate(null);
    setWorkflowProgress([]);
    setExplanationPaused(false);
    explanationPausedRef.current = false;
    queuedExplanationBlocksRef.current = [];
    activeExplanationMessageIdsRef.current = [];
    graphDataRef.current = null;
    selectedNodeRef.current = null;
    suggestionsCacheRef.current.clear();
    lastGraphKeyRef.current = 'null';
    streamingIdRef.current = null;
    activeChatStreamIdRef.current = null;
    activeNodeStreamIdRef.current = null;
    userAbortedChatRef.current = false;
    activeChatAnalyticsRef.current = null;
    activeChatTerminalRef.current = null;
    setWorkerStatus(IDLE_WORKER_STATUS);
    setRetrievalNotice(null);
    setGraphNotice(null);
    setProviderNotice(null);
    setStreamStatus('connected');
  }, []);

  useEffect(() => {
    resetThreadView();
  }, [activeThreadId, resetThreadView]);

  useEffect(() => {
    authSessionRef.current = authSession;
  }, [authSession]);

  useEffect(() => {
    graphDataRef.current = graphData;
  }, [graphData]);

  useEffect(() => {
    selectedNodeRef.current = selectedNode;
  }, [selectedNode]);

  const hydrateThread = useCallback((thread: { messages: Message[]; graphData: GraphData | null }) => {
    resetThreadView();
    setMessages(thread.messages);
    const nextGraph = normalizeGraphData(thread.graphData);
    lastGraphKeyRef.current = graphStructureKey(nextGraph);
    graphDataRef.current = nextGraph;
    setGraphData(nextGraph);
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

      case 'response_reset':
        if (meta.kind !== 'chat') break;
        if (streamingIdRef.current) {
          const id = streamingIdRef.current;
          setMessages(prev => prev.filter(message => message.id !== id));
          streamingIdRef.current = null;
        }
        setProviderNotice(null);
        if (activeExplanationMessageIdsRef.current.length > 0) {
          const obsolete = new Set(activeExplanationMessageIdsRef.current);
          setMessages(prev => prev.filter(message => !obsolete.has(message.id)));
          activeExplanationMessageIdsRef.current = [];
        }
        queuedExplanationBlocksRef.current = [];
        setGraphCandidate(null);
        setWorkflowProgress([]);
        break;

      case 'workflow_progress':
        if (meta.kind !== 'chat') break;
        setWorkflowProgress(prev => {
          const index = prev.findIndex(item => item.phase === event.phase);
          const next = {
            phase: event.phase,
            status: event.status,
            title: event.title,
            detail: event.detail,
          };
          if (index < 0) return [...prev, next].slice(-8);
          return prev.map((item, itemIndex) => itemIndex === index ? next : item);
        });
        break;

      case 'graph_candidate':
        if (meta.kind !== 'chat') break;
        setGraphCandidate({
          evaluationId: event.evaluation_id,
          graphVersion: event.graph_version,
          data: normalizeGraphData(event.data) ?? event.data,
        });
        break;

      case 'explanation_block': {
        if (meta.kind !== 'chat') break;
        const id = makeId();
        const block = {
          id,
          title: event.title,
          content: event.content,
          relatedNodeIds: event.related_node_ids,
        };
        activeExplanationMessageIdsRef.current.push(id);
        if (explanationPausedRef.current) {
          queuedExplanationBlocksRef.current.push(block);
        } else {
          setMessages(prev => [...prev, {
            ...block,
            role: 'assistant',
            kind: 'explanation',
            isStreaming: false,
          }]);
        }
        break;
      }

      case 'command_rejected':
        if (meta.kind !== 'chat') break;
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'assistant',
          content: `Steering was not applied: ${event.reason}`,
          isStreaming: false,
        }]);
        break;

      case 'steer_applied':
      case 'stopped':
        break;

      case 'done':
        if (meta.kind === 'chat') {
          const analytics = activeChatAnalyticsRef.current;
          const terminalAlreadyRecorded = activeChatTerminalRef.current === meta.clientRequestId;
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
          setGraphCandidate(null);
          if (!explanationPausedRef.current) {
            setWorkflowProgress([]);
          }
          if (analytics && !terminalAlreadyRecorded) {
            activeChatTerminalRef.current = analytics.clientRequestId;
            void trackEvent(
              'chat_stream_completed',
              {
                thread_id: analytics.threadId,
                client_request_id: analytics.clientRequestId,
                complexity: analytics.complexity,
                graph_mode: analytics.graphMode,
                research_enabled: analytics.researchEnabled,
                backend_readiness_state: analytics.backendReadinessState,
                has_selected_text_context: analytics.hasSelectedTextContext,
              },
              authSessionRef.current,
            );
          }
        }
        break;

      case 'graph_data':
        if (meta.kind !== 'chat') break;
        {
          const nextGraph = normalizeGraphData(event.data);
          setGraphCandidate(null);
          const nextGraphKey = graphStructureKey(nextGraph);
          const graphChanged = lastGraphKeyRef.current !== nextGraphKey;
          lastGraphKeyRef.current = nextGraphKey;

          if (graphChanged) {
            suggestionsCacheRef.current.clear();
            setGraphNotice(null);
            const currentSelected = selectedNodeRef.current;
            if (!currentSelected || !nextGraph) {
              selectedNodeRef.current = null;
              setSelectedNode(null);
            } else {
              const liveNode = nextGraph.nodes.find((node) => node.id === currentSelected.node.id);
              const nextSelection = liveNode
                ? { node: liveNode, suggestions: initialNodeSuggestions(liveNode.label) }
                : null;
              selectedNodeRef.current = nextSelection;
              setSelectedNode(nextSelection);
            }
          }

          const prevGraph = graphDataRef.current;
          if (prevGraph && nextGraph && graphStructureKey(prevGraph) === graphStructureKey(nextGraph)) {
            break;
          }
          graphDataRef.current = nextGraph;
          setGraphData(nextGraph);
        }
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
        if (event.questions.length === 0) break;
        setSelectedNode(prev => {
          if (prev) {
            // Cache so the next click on this node skips the LLM call
            suggestionsCacheRef.current.set(prev.node.id, event.questions);
            const nextSelection = { ...prev, suggestions: event.questions };
            selectedNodeRef.current = nextSelection;
            return nextSelection;
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
          const analytics = activeChatAnalyticsRef.current;
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
          setGraphCandidate(null);
          if (analytics) {
            activeChatTerminalRef.current = analytics.clientRequestId;
            void trackEvent(
              'chat_stream_failed',
              {
                thread_id: analytics.threadId,
                client_request_id: analytics.clientRequestId,
                complexity: analytics.complexity,
                graph_mode: analytics.graphMode,
                research_enabled: analytics.researchEnabled,
                backend_readiness_state: analytics.backendReadinessState,
                has_selected_text_context: analytics.hasSelectedTextContext,
                error_code: event.content.slice(0, 80),
              },
              authSessionRef.current,
            );
          }
        }
        break;
    }
  }, []);

  useEffect(() => {
    const offEvent = agentTransport.onEvent(handleEvent);
    return () => { offEvent(); };
  }, [handleEvent]);

  const sendMessage = useCallback((
    content: string,
    opts?: {
      complexity?: ComplexityLevel;
      graphMode?: GraphMode;
      researchEnabled?: boolean;
      displayContent?: string;
      backendReadinessState?: string;
      hasSelectedTextContext?: boolean;
    },
  ) => {
    if (!authSession || !activeThreadId) {
      setMessages(prev => [...prev, {
        id: makeId(), role: 'assistant', content: 'Error: You must be signed in with an active thread.', isStreaming: false,
      }]);
      return;
    }
    if (streamStatus === 'generating') {
      const displayContent = opts?.displayContent ?? content;
      if (agentTransport.steerGeneration(content)) {
        setMessages(prev => [...prev, {
          id: makeId(),
          role: 'user',
          content: `Steer: ${displayContent}`,
          isStreaming: false,
        }]);
        setWorkerStatus(prev => ({
          ...prev,
          orchestrator: 'Steering sent — waiting for the workflow to restart…',
        }));
        return;
      }
    }
    setMessages(prev => [...prev, {
      id: makeId(),
      role: 'user',
      content: opts?.displayContent ?? content,
      isStreaming: false,
    }]);
    setRetrievalNotice(null);
    setGraphNotice(null);
    setGraphCandidate(null);
    setWorkflowProgress([]);
    setExplanationPaused(false);
    explanationPausedRef.current = false;
    queuedExplanationBlocksRef.current = [];
    activeExplanationMessageIdsRef.current = [];
    setStreamStatus('generating');
    setWorkerStatus(OPTIMISTIC_CHAT_STATUS);
    userAbortedChatRef.current = false;
    const clientRequestId = makeId();
    activeChatStreamIdRef.current = clientRequestId;
    activeChatTerminalRef.current = null;
    const analytics = {
      threadId: activeThreadId,
      clientRequestId,
      complexity: opts?.complexity ?? 'auto',
      graphMode: opts?.graphMode ?? 'auto',
      researchEnabled: opts?.researchEnabled ?? false,
      backendReadinessState: opts?.backendReadinessState,
      hasSelectedTextContext: opts?.hasSelectedTextContext,
    };
    activeChatAnalyticsRef.current = analytics;
    void trackEvent(
      'chat_sent',
      {
        thread_id: analytics.threadId,
        client_request_id: analytics.clientRequestId,
        complexity: analytics.complexity,
        graph_mode: analytics.graphMode,
        research_enabled: analytics.researchEnabled,
        backend_readiness_state: analytics.backendReadinessState,
        has_selected_text_context: analytics.hasSelectedTextContext,
      },
      authSession,
    );
    void trackEvent(
      'chat_stream_started',
      {
        thread_id: analytics.threadId,
        client_request_id: analytics.clientRequestId,
        complexity: analytics.complexity,
        graph_mode: analytics.graphMode,
        research_enabled: analytics.researchEnabled,
        backend_readiness_state: analytics.backendReadinessState,
        has_selected_text_context: analytics.hasSelectedTextContext,
      },
      authSession,
    );

    agentTransport.sendMessage(authSession, activeThreadId, content, opts, clientRequestId).then(sawDone => {
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
        setRetrievalNotice(null);
        setProviderNotice(null);
        setStreamStatus('connected');
        if (activeChatTerminalRef.current !== clientRequestId) {
          activeChatTerminalRef.current = clientRequestId;
          void trackEvent(
            'chat_stream_failed',
            {
              thread_id: analytics.threadId,
              client_request_id: analytics.clientRequestId,
              complexity: analytics.complexity,
              graph_mode: analytics.graphMode,
              research_enabled: analytics.researchEnabled,
              backend_readiness_state: analytics.backendReadinessState,
              has_selected_text_context: analytics.hasSelectedTextContext,
              error_code: 'stream_closed',
            },
            authSession,
          );
        }
      }
    }).catch(err => {
      if (activeChatStreamIdRef.current !== clientRequestId) {
        return;
      }
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
      setRetrievalNotice(null);
      setProviderNotice(null);
      setStreamStatus('connected');
      if (activeChatTerminalRef.current !== clientRequestId) {
        activeChatTerminalRef.current = clientRequestId;
        void trackEvent(
          'chat_stream_failed',
          {
            thread_id: analytics.threadId,
            client_request_id: analytics.clientRequestId,
            complexity: analytics.complexity,
            graph_mode: analytics.graphMode,
            research_enabled: analytics.researchEnabled,
            backend_readiness_state: analytics.backendReadinessState,
            has_selected_text_context: analytics.hasSelectedTextContext,
            error_code: err.message,
          },
          authSession,
        );
      }
    }).finally(() => {
      if (activeChatStreamIdRef.current === clientRequestId) {
        activeChatStreamIdRef.current = null;
      }
      userAbortedChatRef.current = false;
      if (activeChatAnalyticsRef.current?.clientRequestId === clientRequestId) {
        activeChatAnalyticsRef.current = null;
      }
    });
  }, [activeThreadId, authSession, streamStatus]);

  const requestSearchTool = useCallback(async () => {
    if (!authSession || !activeThreadId || !retrievalNotice || retrievalNotice.requested) {
      return;
    }

    setRetrievalNotice({ ...retrievalNotice, requested: true });
    void trackEvent(
      'search_tool_requested',
      {
        thread_id: activeThreadId,
        request_id: retrievalNotice.requestId,
      },
      authSession,
    );
    try {
      const result = await agentTransport.useSearchTool(authSession, activeThreadId, retrievalNotice.requestId);
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

  const selectNode = useCallback((node: GraphNode) => {
    const cached = suggestionsCacheRef.current.get(node.id);
    const nextSelection = {
      node,
      suggestions: cached ?? initialNodeSuggestions(node.label),
    };
    // Keep the synchronous ref and rendered state in lockstep so a nearby
    // graph event cannot clear a just-selected node before React commits.
    selectedNodeRef.current = nextSelection;
    setSelectedNode(nextSelection);
    if (!authSession || !activeThreadId) return;
    // Check cache — if we already have questions for this node, apply immediately
    // without hitting the backend (saves LLM cost + latency on repeat clicks)
    if (cached) {
      return;
    }
    const clientRequestId = makeId();
    activeNodeStreamIdRef.current = clientRequestId;
    agentTransport.sendNodeSelected(
      authSession,
      activeThreadId,
      node.id,
      node.label,
      node.detail ?? node.description ?? '',
      clientRequestId,
    ).catch(err => {
      console.error('[sse] node-selected error:', err);
    }).finally(() => {
      if (activeNodeStreamIdRef.current === clientRequestId) {
        activeNodeStreamIdRef.current = null;
      }
    });
  }, [activeThreadId, authSession]);

  const clearSelectedNode = useCallback(() => {
    selectedNodeRef.current = null;
    setSelectedNode(null);
  }, []);

  const stopGeneration = useCallback(() => {
    const analytics = activeChatAnalyticsRef.current;
    userAbortedChatRef.current = true;
    agentTransport.stopGeneration();
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
    setGraphCandidate(null);
    setStreamStatus('connected');
    if (analytics) {
      activeChatTerminalRef.current = analytics.clientRequestId;
      void trackEvent(
        'chat_stopped',
        {
          thread_id: analytics.threadId,
          client_request_id: analytics.clientRequestId,
          complexity: analytics.complexity,
          graph_mode: analytics.graphMode,
          research_enabled: analytics.researchEnabled,
          backend_readiness_state: analytics.backendReadinessState,
          has_selected_text_context: analytics.hasSelectedTextContext,
        },
        authSession,
      );
    }
  }, [authSession]);

  const toggleExplanationPause = useCallback(() => {
    const nextPaused = !explanationPausedRef.current;
    explanationPausedRef.current = nextPaused;
    setExplanationPaused(nextPaused);
    if (!nextPaused && queuedExplanationBlocksRef.current.length > 0) {
      const queued = queuedExplanationBlocksRef.current.splice(0);
      setMessages(prev => [
        ...prev,
        ...queued.map(block => ({
          ...block,
          role: 'assistant' as const,
          kind: 'explanation' as const,
          isStreaming: false,
        })),
      ]);
    }
    if (!nextPaused && activeChatTerminalRef.current) {
      setWorkflowProgress([]);
    }
  }, []);

  return {
    messages,
    graphData,
    graphCandidate,
    workflowProgress,
    explanationPaused,
    workerStatus,
    retrievalNotice,
    graphNotice,
    selectedNode,
    selectNode,
    clearSelectedNode,
    streamStatus,
    providerNotice,
    hydrateThread,
    sendMessage,
    requestSearchTool,
    stopGeneration,
    toggleExplanationPause,
  };
}
