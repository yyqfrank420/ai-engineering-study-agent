import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, GraphData, ServerEvent } from '../types';

const mocks = vi.hoisted(() => ({
  eventHandler: null as null | ((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => void),
  sendMessage: vi.fn(),
  sendNodeSelected: vi.fn(),
  isChatActive: vi.fn(),
  steerGeneration: vi.fn(),
  stopGeneration: vi.fn(),
  cancelNodeSelection: vi.fn(),
  useSearchTool: vi.fn(),
  trackEvent: vi.fn(),
  saveGraphContentEdit: vi.fn(),
}));

vi.mock('../services/api', () => ({
  saveGraphContentEdit: mocks.saveGraphContentEdit,
}));

vi.mock('../services/agentTransport', () => ({
  createClientRequestId: () => crypto.randomUUID(),
  agentTransport: {
    onEvent: vi.fn((handler: NonNullable<typeof mocks.eventHandler>) => {
      mocks.eventHandler = handler;
      return vi.fn();
    }),
    sendMessage: mocks.sendMessage,
    sendNodeSelected: mocks.sendNodeSelected,
    isChatActive: mocks.isChatActive,
    steerGeneration: mocks.steerGeneration,
    stopGeneration: mocks.stopGeneration,
    cancelNodeSelection: mocks.cancelNodeSelection,
    useSearchTool: mocks.useSearchTool,
  },
}));

vi.mock('../services/analytics', () => ({
  trackEvent: mocks.trackEvent,
}));

import { useAgentStream } from './useAgentStream';
import { graphStructureKey } from '../utils/graphStructureKey';

const session: AuthSession = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: { id: 'user-1', email: 'user@example.com' },
};

const diagramCriteria = {
  viewport_width: 1440,
  viewport_height: 960,
  minimum_text_px: 11,
} as const;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function graph(version = '1'): GraphData {
  return {
    graph_type: 'concept',
    title: 'Agent Map',
    version,
    nodes: [
      {
        id: 'agent',
        label: 'Agent',
        type: 'service',
        technology: 'LLM',
        description: 'Plans tool use.',
        detail: null,
      },
    ],
    edges: [],
    sequence: [],
  };
}

function Harness({
  auth = session,
  threadId = 'thread-1',
}: {
  auth?: AuthSession | null;
  threadId?: string | null;
}) {
  const agent = useAgentStream(auth, threadId);
  return (
    <div>
      <div data-testid="status">{agent.streamStatus}</div>
      <div data-testid="messages">{agent.messages.map((message) => `${message.role}:${message.content}:${message.isStreaming ? 'streaming' : 'done'}`).join('|')}</div>
      <div data-testid="worker">{JSON.stringify(agent.workerStatus)}</div>
      <div data-testid="provider">{agent.providerNotice ?? ''}</div>
      <div data-testid="retrieval">{agent.retrievalNotice?.message ?? ''}</div>
      <div data-testid="retrieval-requested">{agent.retrievalNotice?.requested ? 'yes' : 'no'}</div>
      <div data-testid="graph-notice">{agent.graphNotice?.message ?? ''}</div>
      <div data-testid="graph-title">{agent.graphData?.title ?? ''}</div>
      <div data-testid="preview-title">{agent.graphPreview?.title ?? ''}</div>
      <div data-testid="candidate-title">{agent.graphCandidate?.data.title ?? ''}</div>
      <div data-testid="candidate-node-type">{agent.graphCandidate?.data.nodes[0]?.type ?? ''}</div>
      <div data-testid="candidate-criteria">{JSON.stringify(agent.graphCandidate?.criteria ?? null)}</div>
      <div data-testid="progress">{JSON.stringify(agent.workflowProgress)}</div>
      <div data-testid="paused">{agent.explanationPaused ? 'yes' : 'no'}</div>
      <div data-testid="node-detail">{agent.graphData?.nodes[0]?.detail ?? ''}</div>
      <div data-testid="selected">{agent.selectedNode ? `${agent.selectedNode.node.id}:${agent.selectedNode.suggestions.join(',')}` : ''}</div>
      <button onClick={() => agent.sendMessage('hello', { complexity: 'production', graphMode: 'on', researchEnabled: true })}>send</button>
      <button onClick={() => agent.requestSearchTool()}>search</button>
      <button onClick={() => agent.selectNode(graph().nodes[0])}>node</button>
      <button onClick={() => {
        if (agent.graphPreview?.nodes[0]) {
          agent.selectNode(agent.graphPreview.nodes[0]);
        }
      }}>preview node</button>
      <button onClick={() => agent.stopGeneration()}>stop</button>
      <button onClick={() => agent.toggleExplanationPause()}>pause</button>
      <button onClick={() => agent.hydrateThread({ messages: [{ id: 'm1', role: 'user', content: 'old' }], graphData: graph('2') })}>hydrate</button>
    </div>
  );
}

describe('useAgentStream', () => {
  it('publishes an accepted overview when only graph detail level changes', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'overview-promotion'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));

    emit({ type: 'graph_data', data: graph() });
    expect(result.current.graphData?.detail_level).toBeUndefined();
    emit({ type: 'graph_data', data: { ...graph(), detail_level: 'overview' } });
    expect(result.current.graphData?.detail_level).toBe('overview');
    expect(result.current.publishedGraphKey).toBe(graphStructureKey(result.current.graphData));
  });

  it('holds the answer through stream completion until the committed graph paints', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'ordering'));
    act(() => result.current.sendMessage('Draw a retrieval system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'response_delta', content: 'The answer' });
    expect(result.current.visibleMessages.map(message => message.content)).not.toContain('The answer');
    expect(result.current.messages.map(message => message.content)).toContain('The answer');
    emit({ type: 'graph_data', data: graph() });
    emit({ type: 'done' });
    expect(result.current.answerPending).toBe(true);
    act(() => result.current.acknowledgeGraphRendered('stale-graph'));
    expect(result.current.answerPending).toBe(true);
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphData)));
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('The answer');
    expect(result.current.diagramRequested).toBe(true);
  });

  it.each(['done', 'error', 'stop', 'disconnect'] as const)('releases an answer without a graph on %s', async terminal => {
    const pending = deferred<boolean>();
    mocks.sendMessage.mockReturnValue(pending.promise);
    const { result } = renderHook(() => useAgentStream(session, 'no-graph'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => mocks.eventHandler?.({ type: 'response_delta', content: 'Available explanation' }, { kind: 'chat', clientRequestId }));
    expect(result.current.answerPending).toBe(true);
    await act(async () => {
      if (terminal === 'stop') result.current.stopGeneration();
      else if (terminal === 'disconnect') pending.resolve(false);
      else mocks.eventHandler?.(terminal === 'error' ? { type: 'error', content: 'Failed' } : { type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('Available explanation');
    expect(result.current.diagramRequested).toBe(true);
  });

  it('streams text-only answers and resets presentation when switching threads', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), { initialProps: { threadId: 'one' } });
    act(() => result.current.sendMessage('Explain retrieval', { graphMode: 'off' }));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    act(() => mocks.eventHandler?.({ type: 'response_delta', content: 'Text only' }, { kind: 'chat', clientRequestId }));
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('Text only');
    rerender({ threadId: 'two' });
    expect(result.current.diagramRequested).toBe(false);
    expect(result.current.visibleMessages).toEqual([]);
  });

  it('accepts an already-painted preview only after that graph is committed and the stream ends', () => {
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'preview-handoff'));
    act(() => result.current.sendMessage('Draw a system'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)![4] as string;
    const emit = (event: ServerEvent) => act(() => mocks.eventHandler?.(event, { kind: 'chat', clientRequestId }));
    emit({ type: 'graph_preview', data: graph() });
    act(() => result.current.acknowledgeGraphRendered(graphStructureKey(result.current.graphPreview)));
    emit({ type: 'explanation_block', block_id: 'one', title: 'How it works', content: 'The walkthrough', related_node_ids: ['agent'], evidence_refs: [] });
    expect(result.current.visibleMessages.map(message => message.content)).not.toContain('The walkthrough');
    emit({ type: 'graph_data', data: graph() });
    expect(result.current.answerPending).toBe(true);
    emit({ type: 'done' });
    expect(result.current.answerPending).toBe(false);
    expect(result.current.visibleMessages.map(message => message.content)).toContain('The walkthrough');
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.eventHandler = null;
    mocks.sendMessage.mockResolvedValue(true);
    mocks.sendNodeSelected.mockResolvedValue(true);
    mocks.isChatActive.mockReturnValue(false);
    mocks.steerGeneration.mockReturnValue(false);
    mocks.useSearchTool.mockResolvedValue({ ok: true, status: 'search_requested' });
    mocks.saveGraphContentEdit.mockReset();
  });

  it('keeps canonical graph unchanged until an edit saves and retains the saved graph after a later stream error', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));
    act(() => result.current.selectNode(graph('original').nodes[0]));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Edited Agent' }] });
    });
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledWith(
      session,
      'thread-1',
      'original',
      { nodes: [{ id: 'agent', label: 'Edited Agent' }] },
    );
    expect(result.current.graphData?.nodes[0].label).toBe('Agent');
    expect(result.current.isSavingGraphEdit).toBe(true);
    act(() => result.current.sendMessage('new request'));
    expect(mocks.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve({ ...graph('edited'), nodes: [{ ...graph('edited').nodes[0], label: 'Edited Agent' }] });
      await savePromise;
    });
    expect(result.current.graphData?.version).toBe('edited');
    expect(result.current.selectedNode?.node.label).toBe('Edited Agent');
    expect(result.current.isSavingGraphEdit).toBe(false);

    act(() => result.current.sendMessage('new request'));
    const clientRequestId = mocks.sendMessage.mock.calls.at(-1)?.[4] as string;
    act(() => mocks.eventHandler?.({ type: 'error', content: 'later failure' }, { kind: 'chat', clientRequestId }));
    expect(result.current.graphData?.nodes[0].label).toBe('Edited Agent');
  });

  it('preserves the graph and allows retry after an edit save fails', async () => {
    mocks.saveGraphContentEdit.mockRejectedValueOnce(new Error('The diagram changed.'));
    mocks.saveGraphContentEdit.mockResolvedValueOnce({ ...graph('retry'), title: 'Saved on retry' });
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Attempt' }] })).rejects.toThrow('The diagram changed.');
    expect(result.current.graphData?.version).toBe('original');
    expect(result.current.isSavingGraphEdit).toBe(false);
    await act(async () => result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Retry' }] }));
    expect(result.current.graphData?.version).toBe('retry');
  });

  it('preserves an explicitly edited decision type with authorization text after save and hydration', async () => {
    const editedNode = {
      ...graph('saved').nodes[0],
      label: 'Authorization gate',
      description: 'Authorization determines access.',
      type: 'decision' as const,
      user_edited_fields: ['type'],
    };
    const savedGraph = { ...graph('saved'), nodes: [editedNode] };
    mocks.saveGraphContentEdit.mockResolvedValue(savedGraph);
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    await act(async () => result.current.saveGraphEdit({
      nodes: [{ id: 'agent', type: 'decision', description: 'Authorization determines access.' }],
    }));
    expect(result.current.graphData?.nodes[0].type).toBe('decision');
    act(() => result.current.hydrateThread({ messages: [], graphData: savedGraph }));
    expect(result.current.graphData?.nodes[0].type).toBe('decision');
  });

  it('ignores an edit response after switching threads', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    const { result, rerender } = renderHook(({ threadId }) => useAgentStream(session, threadId), {
      initialProps: { threadId: 'thread-a' },
    });
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('a') }));

    let savePromise!: Promise<void>;
    act(() => {
      savePromise = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'A edited' }] });
    });
    rerender({ threadId: 'thread-b' });
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('b') }));
    await act(async () => {
      save.resolve({ ...graph('a-edited'), title: 'A edited' });
      await savePromise;
    });
    expect(result.current.graphData?.version).toBe('b');
    expect(result.current.isSavingGraphEdit).toBe(false);
  });

  it('rejects overlapping graph edits and edits during active generation', async () => {
    const save = deferred<GraphData>();
    mocks.saveGraphContentEdit.mockReturnValue(save.promise);
    mocks.sendMessage.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentStream(session, 'thread-1'));
    act(() => result.current.hydrateThread({ messages: [], graphData: graph('original') }));

    let firstSave!: Promise<void>;
    act(() => {
      firstSave = result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'First' }] });
    });
    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'Second' }] }))
      .rejects.toThrow('Wait for the current diagram edit');
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledTimes(1);

    await act(async () => {
      save.resolve(graph('saved'));
      await firstSave;
    });
    act(() => result.current.sendMessage('generate'));
    await expect(result.current.saveGraphEdit({ nodes: [{ id: 'agent', label: 'During generation' }] }))
      .rejects.toThrow('Wait for diagram generation');
    expect(mocks.saveGraphContentEdit).toHaveBeenCalledTimes(1);
  });

  it('streams chat events into messages, graph state, notices, and completion analytics', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    expect(screen.getByTestId('status').textContent).toBe('generating');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_sent',
      expect.objectContaining({ complexity: 'production', graph_mode: 'on', research_enabled: true }),
      session,
    );

    act(() => {
      mocks.eventHandler?.({ type: 'worker_status', worker: 'rag', status: 'Searching book…' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'Hello ' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'world' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'provider_switch', provider: 'openai' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-1', message: 'Weak match' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'graph_data', data: graph('1') }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'graph_notice', message: 'No graph available' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'node_detail',
        node_id: 'agent',
        description: 'Detailed agent description',
        book_refs: ['Chapter 6, p.329'],
        graph_version: '1',
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).toContain('assistant:Hello world:done');
    expect(screen.getByTestId('worker').textContent).toContain('"rag":null');
    expect(screen.getByTestId('provider').textContent).toBe('');
    expect(screen.getByTestId('retrieval').textContent).toBe('');
    expect(screen.getByTestId('graph-notice').textContent).toBe('No graph available');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('node-detail').textContent).toBe('Detailed agent description');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_completed',
      expect.objectContaining({ thread_id: 'thread-1', client_request_id: clientRequestId }),
      session,
    );
  });

  it('ignores stale chat events from an old client request id', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'stale' }, { kind: 'chat', clientRequestId: 'old' });
    });

    expect(screen.getByTestId('messages').textContent).toContain('user:hello:done');
    expect(screen.getByTestId('messages').textContent).not.toContain('stale');
  });

  it('records SSE error events and resets stream state', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'partial' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'error', content: 'backend failed' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).toContain('assistant:partial:done');
    expect(screen.getByTestId('messages').textContent).toContain('assistant:Error: backend failed:done');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_failed',
      expect.objectContaining({ error_code: 'backend failed' }),
      session,
    );
  });

  it('does not count an error followed by done as a completed stream', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'error', content: 'rejected' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });

    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_failed',
      expect.objectContaining({ error_code: 'rejected' }),
      session,
    );
    expect(mocks.trackEvent).not.toHaveBeenCalledWith(
      'chat_stream_completed',
      expect.anything(),
      expect.anything(),
    );
  });

  it('adds connection-closed and network-failure messages from sendMessage promise outcomes', async () => {
    mocks.sendMessage.mockResolvedValueOnce(false);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection closed before the response finished');
    });

    mocks.sendMessage.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection error: offline');
    });
  });

  it('requests the optional search tool', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-1', message: 'Weak match' }, { kind: 'chat', clientRequestId });
    });

    fireEvent.click(screen.getByText('search'));
    await waitFor(() => {
      expect(mocks.useSearchTool).toHaveBeenCalledWith(session, 'thread-1', 'req-1');
      expect(screen.getByTestId('retrieval-requested').textContent).toBe('yes');
    });
  });

  it('handles expired optional search tool requests', async () => {
    mocks.useSearchTool.mockResolvedValueOnce({ ok: false, status: 'expired' });
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-2', message: 'Still weak' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('search'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Search tool is no longer available');
    });
  });

  it('shows a connection error when requesting the search tool fails', async () => {
    mocks.useSearchTool.mockRejectedValueOnce(new Error('offline'));
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'retrieval_notice', request_id: 'req-3', message: 'Weak match' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('search'));

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('Connection error: offline');
      expect(screen.getByTestId('retrieval').textContent).toBe('');
    });
  });

  it('hydrates thread state and resets it when active thread changes', () => {
    const { rerender } = render(<Harness threadId="thread-1" />);

    fireEvent.click(screen.getByText('hydrate'));
    expect(screen.getByTestId('messages').textContent).toContain('user:old');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');

    rerender(<Harness threadId="thread-2" />);

    expect(screen.getByTestId('messages').textContent).toBe('');
    expect(screen.getByTestId('graph-title').textContent).toBe('');
  });

  it('streams node-selected suggestions and reuses cached suggestions on repeat click', async () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;

    expect(screen.getByTestId('selected').textContent).toBe(
      'agent:Explain Agent clearly,Expand graph around Agent,Compare Agent trade-offs',
    );

    act(() => {
      mocks.eventHandler?.({ type: 'suggested_questions', questions: ['Explain', 'Expand'] }, { kind: 'node-selected', clientRequestId });
    });

    expect(screen.getByTestId('selected').textContent).toBe('agent:Explain,Expand');

    fireEvent.click(screen.getByText('node'));

    expect(mocks.sendNodeSelected).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('selected').textContent).toBe('agent:Explain,Expand');
  });

  it('keeps immediate node suggestions when model refinement is empty', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'suggested_questions', questions: [] }, { kind: 'node-selected', clientRequestId });
    });

    expect(screen.getByTestId('selected').textContent).toBe(
      'agent:Explain Agent clearly,Expand graph around Agent,Compare Agent trade-offs',
    );
  });

  it('logs node-selected request failures', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    mocks.sendNodeSelected.mockRejectedValueOnce(new Error('node offline'));
    render(<Harness />);

    fireEvent.click(screen.getByText('node'));

    await waitFor(() => {
      expect(consoleError).toHaveBeenCalledWith('[sse] node-selected error:', expect.any(Error));
    });
    consoleError.mockRestore();
  });

  it('stops generation and records stop analytics', () => {
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'partial' }, { kind: 'chat', clientRequestId });
    });
    fireEvent.click(screen.getByText('stop'));

    expect(mocks.stopGeneration).toHaveBeenCalledWith(clientRequestId);
    expect(screen.getByTestId('messages').textContent).toContain('assistant:partial:done');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stopped',
      expect.objectContaining({ thread_id: 'thread-1', client_request_id: clientRequestId }),
      session,
    );
  });

  it('cancels request-scoped work when the active thread changes and ignores late events', async () => {
    const chat = deferred<boolean>();
    const node = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(chat.promise);
    mocks.sendNodeSelected.mockReturnValueOnce(node.promise);
    const { rerender } = render(<Harness threadId="thread-a" />);

    fireEvent.click(screen.getByText('send'));
    const chatRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'private A draft' }, { kind: 'chat', clientRequestId: chatRequestId });
    });
    fireEvent.click(screen.getByText('node'));
    const nodeRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;

    rerender(<Harness threadId="thread-b" />);

    expect(mocks.stopGeneration).toHaveBeenCalledWith(chatRequestId);
    expect(mocks.cancelNodeSelection).toHaveBeenCalledWith(nodeRequestId);
    expect(screen.getByTestId('messages').textContent).toBe('');
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'late A' }, { kind: 'chat', clientRequestId: chatRequestId });
      mocks.eventHandler?.({ type: 'graph_data', data: graph('late-a') }, { kind: 'chat', clientRequestId: chatRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId: chatRequestId });
      chat.resolve(false);
      node.resolve(false);
    });

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('status').textContent).toBe('connected');
    });
  });

  it('freezes a stopped partial and rejects late reset, delta, and done events', async () => {
    const chat = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(chat.promise);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'keep this partial' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-stop',
        graph_version: 'candidate-stop',
        criteria: diagramCriteria,
        data: graph('candidate-stop'),
      }, { kind: 'chat', clientRequestId });
    });

    fireEvent.click(screen.getByText('stop'));
    expect(screen.getByTestId('candidate-title').textContent).toBe('');
    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'late mutation' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
      chat.resolve(false);
    });

    await waitFor(() => {
      expect(screen.getByTestId('messages').textContent).toContain('assistant:keep this partial:done');
      expect(screen.getByTestId('messages').textContent).not.toContain('late mutation');
      expect(screen.getByTestId('messages').textContent).not.toContain('Connection closed before');
      expect(screen.getByTestId('status').textContent).toBe('connected');
    });
  });

  it('clears private candidates after premature close and network rejection', async () => {
    const closed = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(closed.promise);
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const firstRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-close',
        graph_version: 'candidate-close',
        criteria: diagramCriteria,
        data: graph('candidate-close'),
      }, { kind: 'chat', clientRequestId: firstRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview-close'), title: 'Closing preview' },
      }, { kind: 'chat', clientRequestId: firstRequestId });
      closed.resolve(false);
    });
    await waitFor(() => {
      expect(screen.getByTestId('candidate-title').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('preview-title').textContent).toBe('');
    });

    const rejected = deferred<boolean>();
    mocks.sendMessage.mockReturnValueOnce(rejected.promise);
    fireEvent.click(screen.getByText('send'));
    const secondRequestId = mocks.sendMessage.mock.calls[1][4] as string;
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-reject',
        graph_version: 'candidate-reject',
        criteria: diagramCriteria,
        data: graph('candidate-reject'),
      }, { kind: 'chat', clientRequestId: secondRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview-reject'), title: 'Rejected preview' },
      }, { kind: 'chat', clientRequestId: secondRequestId });
      rejected.reject(new Error('offline'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('candidate-title').textContent).toBe('');
      expect(screen.getByTestId('graph-title').textContent).toBe('');
      expect(screen.getByTestId('preview-title').textContent).toBe('');
    });
  });

  it('steers the active WebSocket run instead of opening a second run', () => {
    mocks.steerGeneration.mockReturnValue(true);
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    fireEvent.click(screen.getByText('send'));

    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    expect(mocks.steerGeneration).toHaveBeenCalledWith('hello');
    expect(screen.getByTestId('messages').textContent).toContain('user:hello:done');
    expect(screen.getByTestId('messages').textContent).not.toContain('Steer:');
  });

  it('discards partial assistant output when a steer restarts the workflow', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'response_delta', content: 'obsolete draft' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'response_delta', content: 'revised answer' }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('messages').textContent).not.toContain('obsolete draft');
    expect(screen.getByTestId('messages').textContent).toContain('revised answer');
  });

  it('displays previews separately and keeps only authoritative graph data across restarts', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('hydrate'));
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('preview'), title: 'Preview graph' },
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('preview-title').textContent).toBe('Preview graph');

    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_data',
        data: { ...graph('committed'), title: 'Committed graph' },
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: { ...graph('later-preview'), title: 'Later preview' },
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({ type: 'error', content: 'failed' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('Committed graph');
    expect(screen.getByTestId('preview-title').textContent).toBe('');
  });

  it('clears previews on every terminal chat event', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    const preview = (title: string) => {
      act(() => {
        mocks.eventHandler?.({
          type: 'graph_preview',
          data: { ...graph(title), title },
        }, { kind: 'chat', clientRequestId });
      });
      expect(screen.getByTestId('preview-title').textContent).toBe(title);
    };

    preview('Reset preview');
    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Stopped preview');
    act(() => {
      mocks.eventHandler?.({ type: 'stopped' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Done preview');
    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');

    preview('Error preview');
    act(() => {
      mocks.eventHandler?.({ type: 'error', content: 'failed' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');
  });

  it('clears a preview-only selection after rollback while keeping authoritative graph', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('hydrate'));
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const previewGraph = {
      ...graph('preview-only'),
      title: 'Transient preview',
      nodes: [
        {
          id: 'preview-node',
          label: 'Transient',
          type: 'service' as const,
          technology: 'LLM',
          description: 'Draft-only node',
          detail: null,
        },
      ],
    };

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_preview',
        data: previewGraph,
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('Transient preview');

    fireEvent.click(screen.getByText('preview node'));
    expect(screen.getByTestId('selected').textContent).toContain('preview-node:');

    act(() => {
      mocks.eventHandler?.({ type: 'response_reset' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('preview-title').textContent).toBe('');
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('selected').textContent).toBe('');
  });

  it('publishes a queued authoritative graph on next send after paused explanation', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    fireEvent.click(screen.getByText('pause'));
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_data',
        data: { ...graph('committed'), title: 'Published graph' },
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('');

    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('');

    fireEvent.click(screen.getByText('send'));
    expect(screen.getByTestId('graph-title').textContent).toBe('Published graph');
  });

  it('keeps candidates hidden and queues explanation blocks while reveal is paused', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({
        type: 'workflow_progress',
        phase: 'architect',
        status: 'complete',
        title: 'Primary design ready',
        detail: 'Runtime loop identified.',
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-1',
        graph_version: 'candidate-v1',
        criteria: {
          viewport_width: 1440,
          viewport_height: 960,
          minimum_text_px: 11,
        },
        data: graph('candidate-v1'),
      }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('candidate-criteria').textContent).toBe(
      '{"viewport_width":1440,"viewport_height":960,"minimum_text_px":11}',
    );
    expect(screen.getByTestId('graph-title').textContent).toBe('');
    expect(screen.getByTestId('progress').textContent).toContain('Primary design ready');

    fireEvent.click(screen.getByText('pause'));
    expect(screen.getByTestId('paused').textContent).toBe('yes');
    act(() => {
      mocks.eventHandler?.({
        type: 'graph_data',
        data: graph('candidate-v1'),
      }, { kind: 'chat', clientRequestId });
      mocks.eventHandler?.({
        type: 'explanation_block',
        block_id: 'overview',
        title: 'In one minute',
        content: 'A queued explanation.',
        related_node_ids: ['agent'],
        evidence_refs: [],
        graph_version: 'candidate-v1',
      }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('graph-title').textContent).toBe('');
    expect(screen.getByTestId('messages').textContent).not.toContain('A queued explanation.');

    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(screen.getByTestId('progress').textContent).toContain('Primary design ready');

    fireEvent.click(screen.getByText('pause'));
    expect(screen.getByTestId('graph-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('messages').textContent).toContain('A queued explanation.');
    expect(screen.getByTestId('progress').textContent).toContain('Primary design ready');
  });

  it('renders the exact private candidate without legacy node-type normalization', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;
    const candidate = graph('candidate-v1');
    candidate.nodes[0] = {
      ...candidate.nodes[0],
      label: 'Access control decision',
      type: 'decision',
    };

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-exact',
        graph_version: 'candidate-v1',
        criteria: diagramCriteria,
        data: candidate,
      }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-node-type').textContent).toBe('decision');
  });

  it.each([
    undefined,
    { viewport_width: 1440, viewport_height: 960 },
    { ...diagramCriteria, minimum_text_px: Number.NaN },
    { ...diagramCriteria, viewport_width: 1280 },
    { ...diagramCriteria, extra: true },
  ])('fails closed for unsupported private render criteria: %j', criteria => {
    render(<Harness />);
    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({
        type: 'graph_candidate',
        evaluation_id: 'eval-missing-criteria',
        graph_version: 'candidate-v1',
        criteria,
        data: graph('candidate-v1'),
      } as unknown as ServerEvent, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-title').textContent).toBe('');
  });

  it('shows an auth/thread error when sending without prerequisites', () => {
    render(<Harness auth={null} threadId={null} />);

    fireEvent.click(screen.getByText('send'));

    expect(screen.getByTestId('messages').textContent).toContain('Error: You must be signed in with an active thread.');
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });
});
