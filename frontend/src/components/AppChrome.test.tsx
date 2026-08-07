import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ContextBar } from './Chat/ContextBar';
import { ModeBar } from './Chat/ModeBar';
import { RetrievalNoticeBar } from './Chat/RetrievalNoticeBar';
import { TitleBar } from './Layout/TitleBar';


describe('application chrome', () => {
  it('exposes navigation, connection state, provider notice, and account actions', () => {
    const actions = {
      toggle: vi.fn(),
      dashboard: vi.fn(),
      chat: vi.fn(),
      logout: vi.fn(),
    };
    const view = render(
      <TitleBar
        streamStatus="generating"
        providerNotice="Using fallback provider"
        userEmail="user@example.com"
        threadTitle="Architecture review"
        sidebarOpen={true}
        showDashboardLink={true}
        dashboardActive={false}
        onToggleSidebar={actions.toggle}
        onOpenDashboard={actions.dashboard}
        onOpenChat={actions.chat}
        onLogout={actions.logout}
      />,
    );

    expect(screen.getByText('generating')).toBeTruthy();
    expect(screen.getByText('Using fallback provider')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Hide chat history'));
    fireEvent.click(screen.getByText('Dashboard'));
    fireEvent.click(screen.getByText('Sign out'));
    expect(actions.toggle).toHaveBeenCalledTimes(1);
    expect(actions.dashboard).toHaveBeenCalledTimes(1);
    expect(actions.logout).toHaveBeenCalledTimes(1);

    view.rerender(
      <TitleBar
        streamStatus="disconnected"
        providerNotice={null}
        userEmail="user@example.com"
        threadTitle="Internal dashboard"
        sidebarOpen={false}
        showDashboardLink={true}
        dashboardActive={true}
        onToggleSidebar={actions.toggle}
        onOpenDashboard={actions.dashboard}
        onOpenChat={actions.chat}
        onLogout={actions.logout}
      />,
    );
    fireEvent.click(screen.getByLabelText('Show chat history'));
    fireEvent.click(screen.getByText('Back to chat'));
    expect(actions.chat).toHaveBeenCalledTimes(1);
  });

  it('changes complexity, graph, and research controls', () => {
    const onComplexityChange = vi.fn();
    const onGraphModeChange = vi.fn();
    const onResearchChange = vi.fn();
    render(
      <ModeBar
        complexity="auto"
        graphMode="auto"
        researchEnabled={false}
        onComplexityChange={onComplexityChange}
        onGraphModeChange={onGraphModeChange}
        onResearchChange={onResearchChange}
      />,
    );

    fireEvent.click(screen.getByText('prod'));
    fireEvent.click(screen.getByText('off'));
    const research = screen.getByText('research').parentElement as HTMLElement;
    fireEvent.mouseEnter(research);
    fireEvent.mouseLeave(research);
    fireEvent.click(research);

    expect(onComplexityChange).toHaveBeenCalledWith('production');
    expect(onGraphModeChange).toHaveBeenCalledWith('off');
    expect(onResearchChange).toHaveBeenCalledWith(true);
  });

  it('sends and dismisses selected-node suggestions', () => {
    const onSendMessage = vi.fn();
    const onClear = vi.fn();
    const view = render(
      <ContextBar selectedNode={null} onSendMessage={onSendMessage} onClear={onClear} />,
    );
    expect(view.container.firstChild).toBeNull();

    view.rerender(
      <ContextBar
        selectedNode={{
          node: {
            id: 'retrieval',
            label: 'Retrieval API',
            type: 'service',
            technology: 'FastAPI',
            description: 'Finds evidence.',
            detail: null,
          },
          suggestions: ['How is evidence ranked?'],
        }}
        onSendMessage={onSendMessage}
        onClear={onClear}
      />,
    );
    const suggestion = screen.getByTestId('suggested-question');
    fireEvent.mouseEnter(suggestion);
    fireEvent.mouseLeave(suggestion);
    fireEvent.click(suggestion);
    fireEvent.click(screen.getByText('×'));

    expect(onSendMessage).toHaveBeenCalledWith('How is evidence ranked?');
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('offers one bounded search action and renders passive graph notices', () => {
    const onUseSearchTool = vi.fn();
    const view = render(
      <RetrievalNoticeBar
        notice={{ requestId: 'request-1', message: 'More evidence is available.', requested: false }}
        onUseSearchTool={onUseSearchTool}
      />,
    );
    fireEvent.click(screen.getByText('Use search tool'));
    expect(onUseSearchTool).toHaveBeenCalledTimes(1);

    view.rerender(
      <RetrievalNoticeBar
        notice={{ requestId: 'request-1', message: 'Search requested.', requested: true }}
        onUseSearchTool={onUseSearchTool}
      />,
    );
    expect(screen.getByText('Using search tool…')).toHaveProperty('disabled', true);

    view.rerender(<RetrievalNoticeBar notice={{ message: 'Graph preserved.' }} />);
    expect(screen.getByText('Graph preserved.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();

    view.rerender(<RetrievalNoticeBar notice={null} />);
    expect(view.container.firstChild).toBeNull();
  });
});
