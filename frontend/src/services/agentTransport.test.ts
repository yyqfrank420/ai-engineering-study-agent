import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, ServerEvent } from '../types';
import { AgentTransport } from './agentTransport';


class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}


const session: AuthSession = {
  access_token: 'secret-access-token',
  refresh_token: '',
  user: { id: 'user-1', email: 'user@example.com' },
};


describe('AgentTransport WebSocket protocol', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('authenticates in the first frame and sends steering on the active channel', async () => {
    const transport = new AgentTransport();
    const events: ServerEvent[] = [];
    transport.onEvent(event => events.push(event));

    const completed = transport.sendMessage(
      session,
      'thread-1',
      'design the system',
      { complexity: 'production', graphMode: 'on' },
      'client-1',
    );
    const socket = MockWebSocket.instances[0];
    expect(socket.url).toContain('/api/chat/ws');

    socket.open();
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: 'auth',
      access_token: 'secret-access-token',
    });

    socket.receive({ type: 'ready' });
    expect(JSON.parse(socket.sent[1])).toMatchObject({
      type: 'start',
      thread_id: 'thread-1',
      client_request_id: 'client-1',
    });
    expect(transport.steerGeneration('focus on approvals')).toBe(true);
    expect(JSON.parse(socket.sent[2])).toMatchObject({
      type: 'steer',
      content: 'focus on approvals',
    });

    socket.receive({ type: 'response_delta', content: 'revised' });
    socket.receive({ type: 'done' });

    await expect(completed).resolves.toBe(true);
    expect(events).toEqual([
      { type: 'response_delta', content: 'revised' },
      { type: 'done' },
    ]);
  });

  it('queues steering while the socket is still connecting', () => {
    const transport = new AgentTransport();
    void transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-2');
    const socket = MockWebSocket.instances[0];

    expect(transport.steerGeneration('make it smaller')).toBe(true);
    socket.open();
    socket.receive({ type: 'ready' });

    expect(JSON.parse(socket.sent[2])).toMatchObject({
      type: 'steer',
      content: 'make it smaller',
    });
    socket.receive({ type: 'done' });
  });

  it('queues steering while authentication is open but start is not ready', () => {
    const transport = new AgentTransport();
    void transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-auth');
    const socket = MockWebSocket.instances[0];

    socket.open();
    expect(transport.steerGeneration('wait for the start frame')).toBe(true);
    expect(socket.sent).toHaveLength(1);

    socket.receive({ type: 'ready' });
    expect(JSON.parse(socket.sent[2])).toMatchObject({
      type: 'steer',
      content: 'wait for the start frame',
      client_request_id: 'client-auth',
    });
    socket.receive({ type: 'done' });
  });

  it('retries one failed connection before sending the start frame', async () => {
    vi.useFakeTimers();
    const transport = new AgentTransport();
    const completed = transport.sendMessage(
      session,
      'thread-1',
      'design',
      undefined,
      'client-retry',
    );
    const first = MockWebSocket.instances[0];

    expect(transport.steerGeneration('retain this steer')).toBe(true);
    first.onerror?.();
    await vi.advanceTimersByTimeAsync(250);

    const second = MockWebSocket.instances[1];
    second.open();
    second.receive({ type: 'ready' });
    expect(JSON.parse(second.sent[1])).toMatchObject({
      type: 'start',
      client_request_id: 'client-retry',
    });
    expect(JSON.parse(second.sent[2])).toMatchObject({
      type: 'steer',
      content: 'retain this steer',
      client_request_id: 'client-retry',
    });
    second.receive({ type: 'done' });

    await expect(completed).resolves.toBe(true);
    vi.useRealTimers();
  });

  it('does not replay a request after its start frame was sent', async () => {
    vi.useFakeTimers();
    const transport = new AgentTransport();
    const completed = transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-started');
    const socket = MockWebSocket.instances[0];
    socket.open();
    socket.receive({ type: 'ready' });
    const rejected = expect(completed).rejects.toThrow('WebSocket connection failed');

    socket.onerror?.();
    await vi.advanceTimersByTimeAsync(250);

    await rejected;
    expect(MockWebSocket.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  it('uploads a rendered diagram in bounded idempotent chunks', () => {
    const transport = new AgentTransport();
    void transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-3');
    const socket = MockWebSocket.instances[0];
    socket.open();
    socket.receive({ type: 'ready' });

    const encoded = 'a'.repeat(17_000);
    expect(transport.submitDiagramEvaluation(
      'eval-1',
      'graph-v1',
      {
        viewport_width: 960,
        viewport_height: 640,
        rendered_nodes: 8,
        rendered_edges: 9,
        overlap_count: 0,
        clipped_nodes: 0,
        minimum_text_px: 7,
      },
      `data:image/jpeg;base64,${encoded}`,
    )).toBe(true);

    const frames = socket.sent.slice(2).map(frame => JSON.parse(frame));
    expect(frames[0]).toMatchObject({
      type: 'diagram_evaluation_start',
      evaluation_id: 'eval-1',
      graph_version: 'graph-v1',
      total_chunks: 3,
    });
    expect(frames.filter(frame => frame.type === 'diagram_evaluation_chunk')).toHaveLength(3);
    expect(frames.at(-1)).toEqual({
      type: 'diagram_evaluation_complete',
      evaluation_id: 'eval-1',
    });
    socket.receive({ type: 'done' });
  });
});
