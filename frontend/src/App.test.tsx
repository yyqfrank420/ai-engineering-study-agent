import { useEffect, useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./hooks/useAuthSession', () => ({ useAuthSession: vi.fn() }));
vi.mock('./hooks/useBackendReadiness', () => ({ useBackendReadiness: vi.fn() }));
vi.mock('./hooks/useSelectionSuggestion', () => ({ useSelectionSuggestion: vi.fn() }));
vi.mock('./hooks/useThreadSession', () => ({ useThreadSession: vi.fn() }));
vi.mock('./hooks/useAgentStream', () => ({ useAgentStream: vi.fn() }));

vi.mock('./services/analytics', () => ({ trackEvent: vi.fn().mockResolvedValue(undefined) }));
vi.mock('./services/auth', () => ({ signOut: vi.fn().mockResolvedValue(undefined) }));
vi.mock('./utils/threadState', () => ({
  shouldPersistThreadSnapshot: vi.fn(() => true),
  storageKeyForThread: vi.fn(userId => `thread:${userId}`),
  writeThreadSnapshot: vi.fn(),
}));

vi.mock('./components/Auth/AuthScreen', () => ({
  AuthScreen: ({ onAuthenticated }: { onAuthenticated: (session: unknown) => void }) => (
    <button onClick={() => onAuthenticated({ user: { id: 'new-user' } })}>Authenticate</button>
  ),
}));

vi.mock('./components/Layout/TitleBar', () => ({
  TitleBar: ({
    threadTitle,
    onToggleSidebar,
    onOpenDashboard,
    onOpenChat,
    onLogout,
    dashboardActive,
  }: {
    threadTitle: string;
    onToggleSidebar: () => void;
    onOpenDashboard?: () => void;
    onOpenChat?: () => void;
    onLogout: () => void;
    dashboardActive?: boolean;
  }) => (
    <header>
      <span>{threadTitle}</span>
      <button onClick={onToggleSidebar}>Toggle sidebar</button>
      <button onClick={dashboardActive ? onOpenChat : onOpenDashboard}>
        {dashboardActive ? 'Back to chat' : 'Open dashboard'}
      </button>
      <button onClick={onLogout}>Log out</button>
    </header>
  ),
}));

vi.mock('./components/Layout/SplitPane', () => ({
  SplitPane: ({ left, right, graphVisible }: {
    left: React.ReactNode;
    right: React.ReactNode;
    graphVisible: boolean;
  }) => (
    <main data-testid="split-pane" data-graph-visible={String(graphVisible)}>
      {left}
      {right}
    </main>
  ),
}));

vi.mock('./components/Layout/ThreadSidebar', () => ({
  ThreadSidebar: ({ onNewChat, onSelectThread, onDeleteThread, isOpen }: {
    onNewChat: () => void;
    onSelectThread: (threadId: string) => void;
    onDeleteThread: (threadId: string) => void;
    isOpen: boolean;
  }) => (
    <aside data-sidebar-open={String(isOpen)}>
      <button onClick={onNewChat}>New chat</button>
      <button onClick={() => onSelectThread('thread-2')}>Select thread</button>
      <button onClick={() => onDeleteThread('thread-2')}>Delete thread</button>
    </aside>
  ),
}));

vi.mock('./components/Chat/ThinkingIndicator', () => ({
  ThinkingIndicator: ({ onTogglePause }: { onTogglePause: () => void }) => (
    <button onClick={onTogglePause}>Toggle explanation</button>
  ),
}));

vi.mock('./components/Chat/RetrievalNoticeBar', () => ({
  RetrievalNoticeBar: ({ notice, onUseSearchTool }: {
    notice: { message: string } | null;
    onUseSearchTool?: () => void;
  }) => notice ? (
    <div>
      {notice.message}
      {onUseSearchTool && <button onClick={onUseSearchTool}>Request search</button>}
    </div>
  ) : null,
}));

vi.mock('./components/Chat/ContextBar', () => ({
  ContextBar: ({ selectedNode, onSendMessage, onClear }: {
    selectedNode: unknown;
    onSendMessage: (content: string) => void;
    onClear: () => void;
  }) => selectedNode ? (
    <div>
      <button onClick={() => onSendMessage('Explain selected context')}>Ask context</button>
      <button onClick={onClear}>Clear context</button>
    </div>
  ) : null,
}));

vi.mock('./components/Chat/ChatInput', () => ({
  ChatInput: ({
    onSend,
    onStop,
    onPrepare,
    onComplexityChange,
    onGraphModeChange,
    onResearchChange,
    onUseSelection,
    onDismissSelection,
    onClearSelectionReference,
    showPrepare,
  }: {
    onSend: (content: string, diagramChoice?: 'on' | 'off') => void;
    onStop: () => void;
    onPrepare: () => void;
    onComplexityChange: (value: 'production') => void;
    onGraphModeChange: (value: 'off') => void;
    onResearchChange: (value: boolean) => void;
    onUseSelection: () => void;
    onDismissSelection: () => void;
    onClearSelectionReference: () => void;
    showPrepare: boolean;
  }) => (
    <div>
      <button onClick={() => onSend('User question')}>Send message</button>
      <button onClick={() => onSend('AI trading bot?', 'on')}>Confirm diagram</button>
      <button onClick={onStop}>Stop generation</button>
      {showPrepare && <button onClick={onPrepare}>Prepare backend</button>}
      <button onClick={() => onComplexityChange('production')}>Use production</button>
      <button onClick={() => onGraphModeChange('off')}>Disable graph</button>
      <button onClick={() => onResearchChange(false)}>Disable research</button>
      <button onClick={onUseSelection}>Use selection</button>
      <button onClick={onDismissSelection}>Dismiss selection</button>
      <button onClick={onClearSelectionReference}>Clear selection reference</button>
    </div>
  ),
}));

vi.mock('./components/GraphCanvas', () => ({
  GraphCanvas: ({ graphData, isPreview, isAcceptedGraph, onNodeClick, onTellMeMore, onExpandGraph, onSaveGraphEdit, onEditDraftChange, editingDisabled }: {
    graphData: GraphData | null;
    isPreview?: boolean;
    isAcceptedGraph?: boolean;
    onNodeClick: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onTellMeMore: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onExpandGraph: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onSaveGraphEdit?: (edit: { nodes: Array<{ id: string; label: string }> }) => Promise<void>;
    onEditDraftChange?: (dirty: boolean) => void;
    editingDisabled?: boolean;
  }) => {
    const node = {
      id: 'retrieval',
      label: 'Retrieval API',
      type: 'service' as const,
      technology: 'FastAPI',
      description: 'Finds evidence.',
      detail: null,
    };
    return (
      <section data-testid="graph-canvas">
        <span data-testid="rendered-graph-title">{graphData?.title ?? ''}</span>
        <span data-testid="rendered-graph-preview">{isPreview ? 'yes' : 'no'}</span>
        <span data-testid="rendered-graph-accepted">{isAcceptedGraph ? 'yes' : 'no'}</span>
        <span data-testid="graph-edit-disabled">{String(editingDisabled)}</span>
        <button onClick={() => onNodeClick(node)}>Choose node</button>
        <button onClick={() => onTellMeMore(node)}>Tell me more</button>
        <button onClick={() => onExpandGraph(node)}>Expand graph</button>
        <button onClick={() => onEditDraftChange?.(true)}>Start graph edit</button>
        <button onClick={() => onEditDraftChange?.(false)}>Cancel graph edit</button>
        <button onClick={() => void onSaveGraphEdit?.({ nodes: [{ id: 'retrieval', label: 'Edited retrieval' }] })}>Save graph edit</button>
      </section>
    );
  },
}));

vi.mock('./components/Chat/MessageList', () => ({
  MessageList: ({ messages }: { messages: unknown[] }) => (
    <div data-testid="message-list">{messages.length} messages</div>
  ),
}));

vi.mock('./components/InternalDashboard', () => ({
  InternalDashboard: () => <div data-testid="internal-dashboard">Dashboard content</div>,
}));

import App from './App';
import { useAgentStream } from './hooks/useAgentStream';
import { useAuthSession } from './hooks/useAuthSession';
import { useBackendReadiness } from './hooks/useBackendReadiness';
import { useSelectionSuggestion } from './hooks/useSelectionSuggestion';
import { useThreadSession } from './hooks/useThreadSession';
import { trackEvent } from './services/analytics';
import { signOut } from './services/auth';
import type { AuthSession, GraphData } from './types';
import { shouldPersistThreadSnapshot, writeThreadSnapshot } from './utils/threadState';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};

const graph: GraphData = {
  graph_type: 'architecture',
  title: 'Reviewed architecture',
  nodes: [],
  edges: [],
  sequence: [],
};

const authState = {
  authReady: true,
  handleAuthenticated: vi.fn(),
  setAuthSession: vi.fn(),
  authSession: session,
};

const selectionState = {
  selectionSuggestion: null as string | null,
  selectionReferenceActive: false,
  clearSelection: vi.fn(),
  activateSelectionReference: vi.fn(),
  dismissSelection: vi.fn(),
  clearSelectionReference: vi.fn(),
};

const readinessState = {
  backendReadiness: 'ready' as const,
  prepareMessage: null,
  prepareProgress: null,
  isBackendReady: true,
  prepareBackendNow: vi.fn(),
  clearPreparedCache: vi.fn(),
};

const threadState = {
  activeThreadId: 'thread-1',
  threadTitle: 'Architecture thread',
  loadingThread: false,
  threadError: null as string | null,
  threadSnapshot: { title: 'Architecture thread', messages: [], graphData: graph },
  handleNewChat: vi.fn(),
  handleSelectThread: vi.fn(),
  handleDeleteThread: vi.fn(),
  retryThread: vi.fn(),
};

const agentState = {
  visibleMessages: [
    { id: 'm1', role: 'user' as const, content: 'Question' },
    { id: 'm2', role: 'assistant' as const, content: 'Grounded answer' },
  ],
  answerPending: false,
  diagramRequested: false,
  acknowledgeGraphRendered: vi.fn(),
  messages: [
    { id: 'm1', role: 'user' as const, content: 'Question' },
    { id: 'm2', role: 'assistant' as const, content: 'Grounded answer' },
  ],
  graphData: graph,
  isSavingGraphEdit: false,
    publishedGraphKey: null,
    graphPreview: null,
  graphCandidate: null,
  workflowProgress: [],
  explanationPaused: false,
  workerStatus: {
    rag: null,
    graph: null,
    critic: null,
    orchestrator: null,
    research: null,
  },
  retrievalNotice: { requestId: 'request-1', message: 'Search available', requested: false },
  graphNotice: { message: 'Approved graph retained' },
  selectedNode: {
    node: {
      id: 'retrieval',
      label: 'Retrieval API',
      type: 'service' as const,
      technology: 'FastAPI',
      description: 'Finds evidence.',
      detail: null,
    },
    suggestions: ['Explain retrieval'],
  },
  selectNode: vi.fn(),
  clearSelectedNode: vi.fn(),
  streamStatus: 'connected' as const,
  providerNotice: null,
  hydrateThread: vi.fn(),
  sendMessage: vi.fn(),
  saveGraphEdit: vi.fn().mockResolvedValue(undefined),
  requestSearchTool: vi.fn(),
  stopGeneration: vi.fn(),
  toggleExplanationPause: vi.fn(),
};


describe('App coordination', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = '';
    localStorage.clear();
    localStorage.setItem('thread:user-1', 'cached');
    vi.mocked(useAuthSession).mockReturnValue(authState);
    vi.mocked(useSelectionSuggestion).mockReturnValue(selectionState);
    vi.mocked(useBackendReadiness).mockReturnValue(readinessState);
    vi.mocked(useThreadSession).mockReturnValue(threadState);
    vi.mocked(useAgentStream).mockReturnValue(agentState);
    vi.mocked(shouldPersistThreadSnapshot).mockReturnValue(true);
  });

  it('renders a bounded loading state before authentication initializes', () => {
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authReady: false });

    render(<App />);

    expect(screen.getByText('Loading session…')).toBeTruthy();
    expect(screen.queryByTestId('split-pane')).toBeNull();
  });

  it('coordinates authenticated chat, graph, selection, and thread actions', async () => {
    render(<App />);

    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('split-pane').dataset.graphVisible).toBe('true');
    expect(agentState.hydrateThread).toHaveBeenCalledWith(threadState.threadSnapshot);
    expect(writeThreadSnapshot).toHaveBeenCalledWith(
      'user-1',
      'thread-1',
      expect.objectContaining({ title: 'Architecture thread', graphData: graph }),
    );

    fireEvent.click(screen.getByText('Send message'));
    expect(selectionState.clearSelection).toHaveBeenCalled();
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      'User question',
      expect.objectContaining({
        complexity: 'auto',
        graphMode: 'on',
        researchEnabled: true,
      }),
    );

    fireEvent.click(screen.getByText('Choose node'));
    fireEvent.click(screen.getByText('Tell me more'));
    fireEvent.click(screen.getByText('Expand graph'));
    expect(agentState.selectNode).toHaveBeenCalled();
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      expect.stringContaining('Tell me more about Retrieval API'),
      expect.any(Object),
    );
    expect(agentState.sendMessage).toHaveBeenCalledWith(
      expect.stringContaining('Expand the current graph around Retrieval API'),
      expect.objectContaining({ graphMode: 'on' }),
    );
    expect(agentState.clearSelectedNode).toHaveBeenCalled();
    expect(trackEvent).toHaveBeenCalledWith(
      'node_selected',
      expect.objectContaining({ node_id: 'retrieval' }),
      session,
    );
    expect(trackEvent).toHaveBeenCalledWith(
      'expand_graph_clicked',
      expect.objectContaining({ node_id: 'retrieval' }),
      session,
    );

    fireEvent.click(screen.getByText('Ask context'));
    fireEvent.click(screen.getByText('Clear context'));
    fireEvent.click(screen.getByText('Request search'));
    fireEvent.click(screen.getByText('Toggle explanation'));
    fireEvent.click(screen.getByText('Stop generation'));
    expect(agentState.requestSearchTool).toHaveBeenCalledTimes(1);
    expect(agentState.toggleExplanationPause).toHaveBeenCalledTimes(1);
    expect(agentState.stopGeneration).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('New chat'));
    fireEvent.click(screen.getByText('Select thread'));
    fireEvent.click(screen.getByText('Delete thread'));
    expect(threadState.handleNewChat).toHaveBeenCalledTimes(1);
    expect(threadState.handleSelectThread).toHaveBeenCalledWith('thread-2');
    expect(threadState.handleDeleteThread).toHaveBeenCalledWith('thread-2');

    fireEvent.click(screen.getByText('Toggle sidebar'));
    expect(screen.getByText('New chat').parentElement?.dataset.sidebarOpen).toBe('false');
  });

  it('blocks chat and thread changes while a graph edit draft is open', async () => {
    render(<App />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByText('Start graph edit'));

    expect(screen.getByText('Save or cancel component edits to continue.')).toBeTruthy();
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByText('Send message'));
    fireEvent.click(screen.getByText('New chat'));
    fireEvent.click(screen.getByText('Select thread'));
    fireEvent.click(screen.getByText('Delete thread'));
    fireEvent.click(screen.getByText('Expand graph'));
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    expect(threadState.handleNewChat).not.toHaveBeenCalled();
    expect(threadState.handleSelectThread).not.toHaveBeenCalled();
    expect(threadState.handleDeleteThread).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Cancel graph edit'));
    expect(screen.queryByText('Save or cancel component edits to continue.')).toBeNull();
    fireEvent.click(screen.getByText('Send message'));
    expect(agentState.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('wires graph edits to the hook and disables editing while save is pending', async () => {
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, isSavingGraphEdit: true });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('graph-edit-disabled').textContent).toBe('true');
    expect(screen.getByText('Saving component edits…')).toBeTruthy();
    fireEvent.click(screen.getByText('Save graph edit'));
    expect(agentState.saveGraphEdit).toHaveBeenCalledWith({
      nodes: [{ id: 'retrieval', label: 'Edited retrieval' }],
    });
  });

  it('renders a preview without writing it into the durable thread snapshot', async () => {
    const preview = { ...graph, title: 'Private preview', detail_level: 'overview' as const };
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, graphPreview: preview });

    render(<App />);

    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Private preview');
    expect(screen.getByTestId('rendered-graph-preview').textContent).toBe('yes');
    expect(screen.getByTestId('rendered-graph-accepted').textContent).toBe('no');
    expect(writeThreadSnapshot).toHaveBeenCalledWith(
      'user-1',
      'thread-1',
      expect.objectContaining({ graphData: graph }),
    );
  });

  it('keeps the connected graph visible during a component-only expansion preview', async () => {
    const connected = { ...graph, detail_level: 'overview' as const, edges: [{ source: 'a', target: 'b', label: 'Request', technology: '', sync: 'sync' as const, description: '' }] };
    vi.mocked(useAgentStream).mockReturnValue({ ...agentState, graphData: connected,
      graphPreview: { ...graph, title: 'Components only', edges: [] } });
    render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe(graph.title);
    expect(screen.getByTestId('rendered-graph-preview').textContent).toBe('yes');
    expect(screen.getByTestId('rendered-graph-accepted').textContent).toBe('yes');
  });

  it('grounds a selected-text request and records mode changes', async () => {
    vi.mocked(useSelectionSuggestion).mockReturnValue({
      ...selectionState,
      selectionSuggestion: 'A selected architecture passage',
      selectionReferenceActive: true,
    });
    render(<App />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByText('Use production'));
    fireEvent.click(screen.getByText('Disable graph'));
    fireEvent.click(screen.getByText('Disable research'));
    fireEvent.click(screen.getByText('Use selection'));
    fireEvent.click(screen.getByText('Dismiss selection'));
    fireEvent.click(screen.getByText('Clear selection reference'));
    fireEvent.click(screen.getByText('Send message'));

    expect(agentState.sendMessage).toHaveBeenLastCalledWith(
      expect.stringContaining('Highlighted text: "A selected architecture passage"'),
      expect.objectContaining({
        complexity: 'production',
        graphMode: 'off',
        researchEnabled: false,
        hasSelectedTextContext: true,
      }),
    );
    await waitFor(() => expect(trackEvent).toHaveBeenCalledWith(
      'mode_changed',
      { mode: 'composer', value: 'production|off|research-off' },
      session,
    ));
  });

  it('blocks sending and thread retry while the backend warms', () => {
    vi.mocked(useBackendReadiness).mockReturnValue({
      ...readinessState,
      backendReadiness: 'preparing',
      isBackendReady: false,
    });
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      threadError: 'database unavailable',
    });
    render(<App />);

    fireEvent.click(screen.getByText('Send message'));
    expect(agentState.sendMessage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Prepare backend'));
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(retry);
    expect(readinessState.prepareBackendNow).toHaveBeenCalledTimes(1);
    expect(threadState.retryThread).not.toHaveBeenCalled();
  });

  it('shows a thread creation error with an available retry', () => {
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      activeThreadId: null,
      loadingThread: false,
      threadError: 'Could not start a new chat. Try again.',
    });
    render(<App />);

    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Could not start a new chat. Try again.');
    expect(alert.textContent).not.toContain('Backend unreachable');
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(retry);
    expect(threadState.retryThread).toHaveBeenCalledTimes(1);
  });

  it('prevents duplicate thread retries while a thread is loading', () => {
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      loadingThread: true,
      threadError: 'Could not open this chat. Try again.',
    });
    render(<App />);

    const retry = screen.getByRole('button', { name: 'Retry' });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(retry);
    expect(threadState.retryThread).not.toHaveBeenCalled();
  });

  it('isolates workspace state by account while retaining it across token refresh', async () => {
    const mountedOwners: string[] = [];
    const cleanedOwners: string[] = [];
    vi.mocked(useThreadSession).mockImplementation(({ authSession }) => {
      const [owner] = useState(() => authSession?.user.id ?? 'signed-out');
      const ownedGraph = owner === 'user-1' ? graph : null;
      const ownedMessages = owner === 'user-1' ? agentState.messages : [];
      return {
        ...threadState,
        activeThreadId: owner === 'signed-out' ? null : `thread-${owner}`,
        threadTitle: owner === 'user-1' ? 'Account A chat' : 'New chat',
        threadSnapshot: {
          title: owner === 'user-1' ? 'Account A chat' : 'New chat',
          messages: ownedMessages,
          graphData: ownedGraph,
        },
      };
    });
    vi.mocked(useAgentStream).mockImplementation((authSession) => {
      const [owner] = useState(() => authSession?.user.id ?? 'signed-out');
      useEffect(() => {
        mountedOwners.push(owner);
        return () => { cleanedOwners.push(owner); };
      }, [owner]);
      const ownedMessages = owner === 'user-1' ? agentState.messages : [];
      return {
        ...agentState,
        messages: ownedMessages,
        visibleMessages: ownedMessages,
        graphData: owner === 'user-1' ? graph : null,
        selectedNode: null,
      };
    });

    const view = render(<App />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Reviewed architecture');
    expect(mountedOwners).toEqual(['user-1']);
    expect(cleanedOwners).toEqual([]);

    const refreshedSession = { ...session, access_token: 'refreshed-token' };
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: refreshedSession });
    view.rerender(<App />);
    expect(mountedOwners).toEqual(['user-1']);
    expect(cleanedOwners).toEqual([]);
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('Reviewed architecture');

    const otherSession = {
      ...session,
      access_token: 'account-b-token',
      user: { ...session.user, id: 'user-2' },
    };
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: otherSession });
    view.rerender(<App />);
    expect(cleanedOwners).toEqual(['user-1']);
    expect(mountedOwners).toEqual(['user-1', 'user-2']);
    expect(screen.getByTestId('rendered-graph-title').textContent).toBe('');
    expect(screen.getByTestId('message-list').textContent).toBe('0 messages');
    expect(writeThreadSnapshot).toHaveBeenCalledWith('user-2', 'thread-user-2', {
      title: 'New chat',
      messages: [],
      graphData: null,
    });
    expect(vi.mocked(writeThreadSnapshot).mock.calls
      .filter(([userId]) => userId === 'user-2')
      .every(([, , snapshot]) => snapshot.graphData === null && snapshot.messages.length === 0)).toBe(true);
  });

  it('moves between dashboard and chat and clears local state on logout', async () => {
    window.location.hash = '#/internal/dashboard';
    render(<App />);

    await screen.findByTestId('internal-dashboard');
    expect(screen.getByText('Internal dashboard')).toBeTruthy();
    fireEvent.click(screen.getByText('Back to chat'));
    await screen.findByTestId('split-pane');
    expect(window.location.hash).toBe('');

    fireEvent.click(screen.getByText('Open dashboard'));
    await screen.findByTestId('internal-dashboard');
    expect(window.location.hash).toBe('#/internal/dashboard');

    fireEvent.click(screen.getByText('Log out'));
    await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem('thread:user-1')).toBeNull();
    expect(readinessState.clearPreparedCache).toHaveBeenCalledTimes(1);
    expect(authState.setAuthSession).toHaveBeenCalledWith(null);
  });

  it('sends diagram confirmation separately from the unchanged learner message', async () => {
    vi.mocked(useSelectionSuggestion).mockReturnValue({ ...selectionState, selectionSuggestion: null, selectionReferenceActive: false });
    render(<App />);
    fireEvent.click(await screen.findByText('Confirm diagram'));
    expect(agentState.sendMessage).toHaveBeenCalledWith('AI trading bot?', expect.objectContaining({
      diagramRequested: true, graphMode: 'on', displayContent: 'AI trading bot?',
    }));
  });

  it('keeps the diagram pane after a graphless completion and displays only released messages', async () => {
    vi.mocked(useAgentStream).mockReturnValue({
      ...agentState,
      graphData: null,
      diagramRequested: true,
      answerPending: true,
      visibleMessages: [agentState.messages[0]],
    });
    render(<App />);
    const pane = await screen.findByTestId('split-pane');
    expect(pane.getAttribute('data-graph-visible')).toBe('true');
    expect(screen.getByTestId('message-list').textContent).toBe('1 messages');
  });

  it('shows authentication and skips persistence without an active session', () => {
    vi.mocked(useAuthSession).mockReturnValue({ ...authState, authSession: null });
    vi.mocked(useThreadSession).mockReturnValue({
      ...threadState,
      activeThreadId: null,
      threadTitle: '',
    });
    vi.mocked(useAgentStream).mockReturnValue({
      ...agentState,
      graphData: null,
      graphCandidate: null,
      selectedNode: null,
      streamStatus: 'disconnected',
    });
    render(<App />);

    expect(screen.getByText('Authenticate')).toBeTruthy();
    expect(screen.getByText('New chat', { selector: 'span' })).toBeTruthy();
    expect(writeThreadSnapshot).not.toHaveBeenCalled();
  });
});
