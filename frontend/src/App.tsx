import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import type { GraphNode } from './types';
import { useAgentStream } from './hooks/useAgentStream';
import { TitleBar } from './components/Layout/TitleBar';
import { SplitPane } from './components/Layout/SplitPane';
import { ThreadSidebar } from './components/Layout/ThreadSidebar';
import { ThinkingIndicator } from './components/Chat/ThinkingIndicator';
import { RetrievalNoticeBar } from './components/Chat/RetrievalNoticeBar';
import { ContextBar } from './components/Chat/ContextBar';
import { ChatInput } from './components/Chat/ChatInput';
import { AuthScreen } from './components/Auth/AuthScreen';
import { signOut } from './services/auth';
import { useAuthSession } from './hooks/useAuthSession';
import { useBackendReadiness } from './hooks/useBackendReadiness';
import { useSelectionSuggestion } from './hooks/useSelectionSuggestion';
import { useThreadSession } from './hooks/useThreadSession';
import { storageKeyForThread, writeThreadSnapshot } from './utils/threadState';

import type { ComplexityLevel, GraphMode } from './types';

const GraphCanvas = lazy(() =>
  import('./components/GraphCanvas').then(module => ({ default: module.GraphCanvas })),
);
const MessageList = lazy(() =>
  import('./components/Chat/MessageList').then(module => ({ default: module.MessageList })),
);

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [graphRevealed, setGraphRevealed] = useState(false);
  const { authReady, handleAuthenticated, setAuthSession, authSession } = useAuthSession();
  const {
    selectionSuggestion,
    selectionReferenceActive,
    clearSelection,
    activateSelectionReference,
    dismissSelection,
    clearSelectionReference,
  } = useSelectionSuggestion();
  const {
    backendReadiness,
    prepareMessage,
    isBackendReady,
    prepareBackendNow,
    clearPreparedCache,
  } = useBackendReadiness(authSession);

  const {
    activeThreadId,
    threadTitle,
    loadingThread,
    threadError,
    threadSnapshot,
    handleNewChat,
    handleSelectThread,
    handleDeleteThread,
    retryLatestThread,
  } = useThreadSession({
    authSession,
    backendReady: isBackendReady,
    clearSelection,
  });

  const {
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
  } = useAgentStream(authSession, activeThreadId);

  const [complexity,      setComplexity]      = useState<ComplexityLevel>('auto');
  const [graphMode,       setGraphMode]       = useState<GraphMode>('auto');
  const [researchEnabled, setResearchEnabled] = useState(false);

  useEffect(() => {
    hydrateThread(threadSnapshot);
  }, [hydrateThread, threadSnapshot]);

  useEffect(() => {
    setGraphRevealed(false);
  }, [activeThreadId]);

  useEffect(() => {
    if (messages.length > 0 || !!graphData) {
      setGraphRevealed(true);
    }
  }, [graphData, messages.length]);

  const handleLogout = useCallback(async () => {
    if (authSession) {
      localStorage.removeItem(storageKeyForThread(authSession.user.id));
      clearPreparedCache();
    }

    await signOut();
    setAuthSession(null);
  }, [authSession, clearPreparedCache, setAuthSession]);

  const handleSend = useCallback((content: string) => {
    if (backendReadiness !== 'ready') {
      return;
    }
    const requestContent = selectionReferenceActive && selectionSuggestion
      ? [
          'Explain this highlighted part in beginner-friendly terms and relate it to the diagram.',
          '',
          `Highlighted text: "${selectionSuggestion}"`,
          '',
          `User question: ${content}`,
        ].join('\n')
      : content;

    clearSelection();
    sendMessage(requestContent, {
      complexity,
      graphMode,
      researchEnabled,
      displayContent: content,
    });
  }, [backendReadiness, clearSelection, complexity, graphMode, researchEnabled, selectionReferenceActive, selectionSuggestion, sendMessage]);

  // isGenerating: LLM is actively streaming — show Stop button
  const isGenerating = messages.some(m => m.isStreaming);
  // isStreaming: any busy state — used to disable sidebar/new-chat during loads
  const isStreaming = isGenerating || loadingThread;
  const composerLocked = streamStatus === 'generating' || loadingThread;
  const sendLocked = composerLocked || backendReadiness !== 'ready' || !activeThreadId;
  const showPrepare = !!authSession && backendReadiness !== 'ready';
  const prepareDisabled = composerLocked || !authSession || backendReadiness === 'preparing';

  const handleNodeClick = (node: GraphNode) => {
    setSelectedNode({ node, suggestions: [] });
    sendNodeSelected(node.id, node.label, node.detail ?? '');
  };

  const handleTellMeMore = useCallback((node: GraphNode) => {
    handleSend(
      `Tell me more about ${node.label}. Walk me through how it fits into this architecture like I am a beginner, and use simple analogies.`,
    );
  }, [handleSend]);

  const effectiveThreadTitle = useMemo(
    () => threadTitle || 'New chat',
    [threadTitle],
  );

  useEffect(() => {
    if (!authSession || !activeThreadId) {
      return;
    }

    writeThreadSnapshot(authSession.user.id, activeThreadId, {
      title: effectiveThreadTitle,
      messages,
      graphData,
    });
  }, [activeThreadId, authSession, effectiveThreadTitle, graphData, messages]);

  const latestAssistantText = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant')?.content ?? '',
    [messages],
  );

  const handleToggleSidebar = useCallback(() => {
    setSidebarOpen(open => !open);
  }, []);

  if (!authReady) {
    return <div style={loadingScreenStyle}>Loading session…</div>;
  }

  const showGraphPane = graphRevealed;

  return (
    <div style={{ position: 'relative', height: '100vh', overflow: 'hidden' }}>
    {/* Auth overlay — sits above blurred app when unauthenticated */}
    {!authSession && <AuthScreen onAuthenticated={handleAuthenticated} />}
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      // Ambient gradient backdrop — vivid enough for glass panels to refract color
      background: `
        radial-gradient(ellipse 80% 60% at 10% -5%, rgba(124,58,237,0.55) 0%, transparent 60%),
        radial-gradient(ellipse 70% 50% at 90% 105%, rgba(37,99,235,0.45) 0%, transparent 60%),
        radial-gradient(ellipse 50% 40% at 75% 25%, rgba(5,150,105,0.18) 0%, transparent 50%),
        radial-gradient(ellipse 40% 30% at 25% 70%, rgba(124,58,237,0.12) 0%, transparent 50%),
        #070a10
      `,
      color: '#e2e8f0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      // Blur + dim the app when unauthenticated so it shows as a preview behind auth
      ...(authSession ? {} : {
        filter: 'blur(6px)',
        opacity: 0.35,
        pointerEvents: 'none',
        userSelect: 'none',
      }),
    }}>
      <TitleBar
        streamStatus={streamStatus}
        providerNotice={providerNotice}
        userEmail={authSession?.user.email ?? ''}
        threadTitle={effectiveThreadTitle}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={handleToggleSidebar}
        onLogout={handleLogout}
      />

      {/* Main body: sidebar + split pane side-by-side */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <ThreadSidebar
          authSession={authSession}
          activeThreadId={activeThreadId}
          backendReady={isBackendReady}
          onNewChat={handleNewChat}
          onSelectThread={handleSelectThread}
          onDeleteThread={handleDeleteThread}
          isLoading={isStreaming}
          isOpen={sidebarOpen}
        />
        <SplitPane
          graphVisible={showGraphPane}
          left={
            <Suspense fallback={<div style={panelFallbackStyle}>Loading graph…</div>}>
              <GraphCanvas
                graphData={graphData}
                animateSequence={streamStatus === 'generating'}
                onNodeClick={handleNodeClick}
                onTellMeMore={handleTellMeMore}
                selectedNode={selectedNode}
                onClosePopup={() => setSelectedNode(null)}
                sourceTexts={[latestAssistantText]}
              />
            </Suspense>
          }
          right={
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
              {threadError && (
                <div style={{
                  margin: '1rem',
                  padding: '0.75rem 1rem',
                  borderRadius: '8px',
                  background: 'rgba(248,81,73,0.08)',
                  border: '1px solid rgba(248,81,73,0.2)',
                  color: '#f85149',
                  fontSize: '0.8rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '0.75rem',
                  flexShrink: 0,
                }}>
                  <span>Backend unreachable: {threadError}</span>
                  <button
                    onClick={retryLatestThread}
                    style={{
                      background: 'rgba(248,81,73,0.12)',
                      border: '1px solid rgba(248,81,73,0.3)',
                      borderRadius: '6px',
                      color: '#f85149',
                      fontSize: '0.75rem',
                      padding: '3px 10px',
                      cursor: 'pointer',
                      flexShrink: 0,
                    }}
                  >
                    Retry
                  </button>
                </div>
              )}
              <Suspense fallback={<div style={panelFallbackStyle}>Loading conversation…</div>}>
                <MessageList messages={messages} />
              </Suspense>
              <ThinkingIndicator workerStatus={workerStatus} />
              <RetrievalNoticeBar
                notice={retrievalNotice}
                onUseSearchTool={requestSearchTool}
              />
              <RetrievalNoticeBar
                notice={graphNotice}
              />
              <ContextBar
                selectedNode={selectedNode}
                onSendMessage={handleSend}
                onClear={() => setSelectedNode(null)}
              />
              <ChatInput
                key={activeThreadId ?? 'no-thread'}
                onSend={handleSend}
                onStop={stopGeneration}
                onPrepare={prepareBackendNow}
                isGenerating={isGenerating}
                disabled={composerLocked}
                sendDisabled={sendLocked}
                showPrepare={showPrepare}
                prepareDisabled={prepareDisabled}
                prepareMessage={prepareMessage}
                complexity={complexity}
                graphMode={graphMode}
                researchEnabled={researchEnabled}
                onComplexityChange={setComplexity}
                onGraphModeChange={setGraphMode}
                onResearchChange={setResearchEnabled}
                selectionSuggestion={selectionSuggestion}
                selectionReferenceActive={selectionReferenceActive}
                onUseSelection={activateSelectionReference}
                onDismissSelection={dismissSelection}
                onClearSelectionReference={clearSelectionReference}
              />
            </div>
          }
        />
      </div>
    </div>
    </div>
  );
}

const loadingScreenStyle: CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: '#0d1117',
  color: '#e6edf3',
};

const panelFallbackStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#8b949e',
  fontSize: '0.85rem',
};
