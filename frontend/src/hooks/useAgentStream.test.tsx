import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AuthSession, ServerEvent } from '../types';

const mocks = vi.hoisted(() => ({
  eventHandler: null as null | ((event: ServerEvent, meta: { kind: 'chat' | 'node-selected'; clientRequestId: string }) => void),
  sendMessage: vi.fn(),
  trackEvent: vi.fn(),
}));

vi.mock('../services/sse', () => ({
  sseClient: {
    onEvent: vi.fn((handler: NonNullable<typeof mocks.eventHandler>) => {
      mocks.eventHandler = handler;
      return vi.fn();
    }),
    sendMessage: mocks.sendMessage,
    sendNodeSelected: vi.fn(),
    stopGeneration: vi.fn(),
    useSearchTool: vi.fn(),
  },
}));

vi.mock('../services/analytics', () => ({
  trackEvent: mocks.trackEvent,
}));

import { useAgentStream } from './useAgentStream';

function Harness({ session }: { session: AuthSession | null }) {
  const agent = useAgentStream(session, 'thread-1');
  return <button onClick={() => agent.sendMessage('hello')}>send</button>;
}

describe('useAgentStream', () => {
  it('uses the current auth session for terminal SSE analytics', () => {
    const session: AuthSession = {
      access_token: 'token',
      refresh_token: '',
      user: { id: 'user-1', email: 'user@example.com' },
    };
    mocks.sendMessage.mockImplementation(() => new Promise<boolean>(() => {}));

    const { rerender } = render(<Harness session={null} />);
    rerender(<Harness session={session} />);

    fireEvent.click(screen.getByText('send'));
    const clientRequestId = mocks.sendMessage.mock.calls[0][4] as string;

    act(() => {
      mocks.eventHandler?.({ type: 'done' }, { kind: 'chat', clientRequestId });
    });

    expect(mocks.trackEvent).toHaveBeenCalledWith(
      'chat_stream_completed',
      expect.objectContaining({
        thread_id: 'thread-1',
        client_request_id: clientRequestId,
      }),
      session,
    );
  });
});
