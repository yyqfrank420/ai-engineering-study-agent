import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, GraphData, ServerEvent } from '../types';

const mocks = vi.hoisted(() => ({
  eventHandler: null as null | ((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => void),
  sendMessage: vi.fn(),
  sendNodeSelected: vi.fn(),
  isChatActive: vi.fn(),
  steerGeneration: vi.fn(),
  stopGeneration: vi.fn(),
  useSearchTool: vi.fn(),
  trackEvent: vi.fn(),
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
    useSearchTool: mocks.useSearchTool,
  },
}));

vi.mock('../services/analytics', () => ({
  trackEvent: mocks.trackEvent,
}));

import { useAgentStream } from './useAgentStream';

const session: AuthSession = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: { id: 'user-1', email: 'user@example.com' },
};

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
      <div data-testid="candidate-title">{agent.graphCandidate?.data.title ?? ''}</div>
      <div data-testid="progress">{JSON.stringify(agent.workflowProgress)}</div>
      <div data-testid="paused">{agent.explanationPaused ? 'yes' : 'no'}</div>
      <div data-testid="node-detail">{agent.graphData?.nodes[0]?.detail ?? ''}</div>
      <div data-testid="selected">{agent.selectedNode ? `${agent.selectedNode.node.id}:${agent.selectedNode.suggestions.join(',')}` : ''}</div>
      <button onClick={() => agent.sendMessage('hello', { complexity: 'production', graphMode: 'on', researchEnabled: true })}>send</button>
      <button onClick={() => agent.requestSearchTool()}>search</button>
      <button onClick={() => agent.sendNodeSelected('agent', 'Agent', 'Plans tool use.')}>node</button>
      <button onClick={() => agent.stopGeneration()}>stop</button>
      <button onClick={() => agent.toggleExplanationPause()}>pause</button>
      <button onClick={() => agent.setSelectedNode({ node: graph().nodes[0], suggestions: ['Immediate'] })}>select</button>
      <button onClick={() => agent.hydrateThread({ messages: [{ id: 'm1', role: 'user', content: 'old' }], graphData: graph('2') })}>hydrate</button>
    </div>
  );
}

describe('useAgentStream', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.eventHandler = null;
    mocks.sendMessage.mockResolvedValue(true);
    mocks.sendNodeSelected.mockResolvedValue(true);
    mocks.isChatActive.mockReturnValue(false);
    mocks.steerGeneration.mockReturnValue(false);
    mocks.useSearchTool.mockResolvedValue({ ok: true, status: 'search_requested' });
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

    fireEvent.click(screen.getByText('select'));
    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;

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

    fireEvent.click(screen.getByText('select'));
    fireEvent.click(screen.getByText('node'));
    const clientRequestId = mocks.sendNodeSelected.mock.calls[0][5] as string;
    act(() => {
      mocks.eventHandler?.({ type: 'suggested_questions', questions: [] }, { kind: 'node-selected', clientRequestId });
    });

    expect(screen.getByTestId('selected').textContent).toBe('agent:Immediate');
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

    expect(mocks.stopGeneration).toHaveBeenCalled();
    expect(screen.getByTestId('messages').textContent).toContain('assistant:partial:done');
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stopped',
      expect.objectContaining({ thread_id: 'thread-1', client_request_id: clientRequestId }),
      session,
    );
  });

  it('steers the active WebSocket run instead of opening a second run', () => {
    mocks.steerGeneration.mockReturnValue(true);
    render(<Harness />);

    fireEvent.click(screen.getByText('send'));
    fireEvent.click(screen.getByText('send'));

    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    expect(mocks.steerGeneration).toHaveBeenCalledWith('hello');
    expect(screen.getByTestId('messages').textContent).toContain('user:Steer: hello:done');
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
        data: graph('candidate-v1'),
      }, { kind: 'chat', clientRequestId });
    });

    expect(screen.getByTestId('candidate-title').textContent).toBe('Agent Map');
    expect(screen.getByTestId('graph-title').textContent).toBe('');
    expect(screen.getByTestId('progress').textContent).toContain('Primary design ready');

    fireEvent.click(screen.getByText('pause'));
    expect(screen.getByTestId('paused').textContent).toBe('yes');
    act(() => {
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
    expect(screen.getByTestId('messages').textContent).not.toContain('A queued explanation.');

    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });
    expect(screen.getByTestId('status').textContent).toBe('connected');
    expect(screen.getByTestId('progress').textContent).toContain('Primary design ready');

    fireEvent.click(screen.getByText('pause'));
    expect(screen.getByTestId('messages').textContent).toContain('A queued explanation.');
    expect(screen.getByTestId('progress').textContent).toBe('[]');
  });

  it('shows an auth/thread error when sending without prerequisites', () => {
    render(<Harness auth={null} threadId={null} />);

    fireEvent.click(screen.getByText('send'));

    expect(screen.getByTestId('messages').textContent).toContain('Error: You must be signed in with an active thread.');
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });
});
