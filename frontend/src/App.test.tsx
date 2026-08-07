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
    onSend: (content: string) => void;
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
  GraphCanvas: ({ onNodeClick, onTellMeMore, onExpandGraph }: {
    onNodeClick: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onTellMeMore: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
    onExpandGraph: (node: { id: string; label: string; type: 'service'; technology: string; description: string; detail: null }) => void;
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
        <button onClick={() => onNodeClick(node)}>Choose node</button>
        <button onClick={() => onTellMeMore(node)}>Tell me more</button>
        <button onClick={() => onExpandGraph(node)}>Expand graph</button>
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
  retryLatestThread: vi.fn(),
};

const agentState = {
  messages: [
    { id: 'm1', role: 'user' as const, content: 'Question' },
    { id: 'm2', role: 'assistant' as const, content: 'Grounded answer' },
  ],
  graphData: graph,
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
        graphMode: 'auto',
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

  it('blocks sending while the backend warms and exposes preparation and retry', () => {
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
    fireEvent.click(screen.getByText('Retry'));
    expect(readinessState.prepareBackendNow).toHaveBeenCalledTimes(1);
    expect(threadState.retryLatestThread).toHaveBeenCalledTimes(1);
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
