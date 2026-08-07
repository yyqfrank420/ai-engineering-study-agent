import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSession, ServerEvent } from '../types';
import { AgentTransport, createClientRequestId } from './agentTransport';


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

  it('stops the exact request and ignores late frames from its superseded socket', async () => {
    const transport = new AgentTransport();
    const events: ServerEvent[] = [];
    transport.onEvent(event => events.push(event));
    const completed = transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-stop');
    const socket = MockWebSocket.instances[0];
    socket.open();
    socket.receive({ type: 'ready' });

    expect(transport.stopGeneration('client-stop')).toBe(true);
    expect(JSON.parse(socket.sent.at(-1)!)).toEqual({
      type: 'stop',
      client_request_id: 'client-stop',
    });
    socket.receive({ type: 'response_delta', content: 'late mutation' });
    socket.receive({ type: 'done' });
    socket.close();

    await expect(completed).resolves.toBe(false);
    expect(events).toEqual([]);
  });

  it('does not let stale cancellation close a newer request', async () => {
    const transport = new AgentTransport();
    const firstCompleted = transport.sendMessage(session, 'thread-1', 'first', undefined, 'client-old');
    const first = MockWebSocket.instances[0];
    first.open();
    first.receive({ type: 'ready' });

    const secondCompleted = transport.sendMessage(session, 'thread-2', 'second', undefined, 'client-new');
    const second = MockWebSocket.instances[1];
    expect(JSON.parse(first.sent.at(-1)!)).toEqual({
      type: 'stop',
      client_request_id: 'client-old',
    });
    expect(transport.stopGeneration('client-old')).toBe(false);
    expect(transport.isChatActive()).toBe(true);

    first.close();
    second.open();
    second.receive({ type: 'ready' });
    second.receive({ type: 'done' });

    await expect(firstCompleted).resolves.toBe(false);
    await expect(secondCompleted).resolves.toBe(true);
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
        clipped_edges: 0,
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

  it('creates browser request ids and contains malformed WebSocket frames', async () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'browser-request-id') });
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(createClientRequestId()).toBe('browser-request-id');

    const transport = new AgentTransport();
    const completed = transport.sendMessage(
      session,
      'thread-1',
      'design',
      undefined,
      'client-malformed',
    );
    const socket = MockWebSocket.instances[0];
    socket.open();
    socket.receive({ type: 'ready' });
    socket.onmessage?.({ data: '{invalid' });
    expect(error).toHaveBeenCalledWith('[ws] Failed to parse event:', '{invalid');
    socket.close();
    await expect(completed).resolves.toBe(false);
  });

  it('rejects inactive diagram submissions and cancellation', () => {
    const transport = new AgentTransport();
    expect(transport.stopGeneration()).toBe(false);
    expect(transport.steerGeneration('no active request')).toBe(false);
    expect(transport.submitDiagramEvaluation(
      'eval-1',
      null,
      {
        viewport_width: 320,
        viewport_height: 240,
        rendered_nodes: 0,
        rendered_edges: 0,
        overlap_count: 0,
        clipped_nodes: 0,
        clipped_edges: 0,
        minimum_text_px: 12,
      },
      'invalid-image',
    )).toBe(false);

    void transport.sendMessage(session, 'thread-1', 'design', undefined, 'client-image');
    const socket = MockWebSocket.instances[0];
    socket.open();
    socket.receive({ type: 'ready' });
    expect(transport.submitDiagramEvaluation(
      'eval-1',
      null,
      {
        viewport_width: 320,
        viewport_height: 240,
        rendered_nodes: 0,
        rendered_edges: 0,
        overlap_count: 0,
        clipped_nodes: 0,
        clipped_edges: 0,
        minimum_text_px: 12,
      },
      'invalid-image',
    )).toBe(false);
    socket.receive({ type: 'done' });
  });

  it('streams node suggestions across chunk boundaries and supports unsubscribe', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('ignored\n\ndata: {"type":"suggested_questions","questions":["One"]}\r\n\r\n'));
        controller.enqueue(encoder.encode('data: {invalid}\n\ndata: {"type":"done"}'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const transport = new AgentTransport();
    const events: ServerEvent[] = [];
    const unsubscribe = transport.onEvent(event => events.push(event));

    await expect(transport.sendNodeSelected(
      session,
      'thread-1',
      'node-1',
      'Retrieval API',
      'Finds evidence',
      'client-node-1',
    )).resolves.toBe(true);

    expect(events).toEqual([
      { type: 'suggested_questions', questions: ['One'] },
      { type: 'done' },
    ]);
    expect(error).toHaveBeenCalledWith('[sse] Failed to parse event:', 'data: {invalid}');
    expect(fetch).toHaveBeenCalledWith('/api/node-selected', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer secret-access-token' }),
      signal: expect.any(AbortSignal),
    }));

    unsubscribe();
    events.length = 0;
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      'data: {"type":"done"}\n\n',
      { status: 200 },
    ));
    await transport.sendNodeSelected(
      session,
      'thread-1',
      'node-1',
      'Retrieval API',
      'Finds evidence',
      'client-node-2',
    );
    expect(events).toEqual([]);
  });

  it('rejects failed or bodyless node streams', async () => {
    const transport = new AgentTransport();
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503, statusText: 'Unavailable' }))
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: 'OK', body: null }));

    await expect(transport.sendNodeSelected(
      session, 'thread-1', 'node-1', 'Node', 'Description', 'client-http-fail',
    )).rejects.toThrow('HTTP 503: Unavailable');
    await expect(transport.sendNodeSelected(
      session, 'thread-1', 'node-1', 'Node', 'Description', 'client-no-body',
    )).rejects.toThrow('Response has no body');
  });

  it('cancels only the matching node request and clears its controller', async () => {
    let rejectFetch: ((error: Error) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      rejectFetch = reject;
      init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
    })));
    const transport = new AgentTransport();
    const request = transport.sendNodeSelected(
      session, 'thread-1', 'node-1', 'Node', 'Description', 'client-cancel',
    );

    expect(transport.cancelNodeSelection('other-request')).toBe(false);
    expect(transport.cancelNodeSelection('client-cancel')).toBe(true);
    await expect(request).rejects.toThrow('aborted');
    expect(rejectFetch).toBeDefined();
    expect(transport.cancelNodeSelection()).toBe(false);
  });

  it('uses the authenticated search-tool boundary and reports HTTP failures', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ ok: true, status: 'requested' }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        statusText: 'Conflict',
      }));
    const transport = new AgentTransport();

    await expect(transport.useSearchTool(session, 'thread-1', 'request-1')).resolves.toEqual({
      ok: true,
      status: 'requested',
    });
    expect(fetch).toHaveBeenCalledWith('/api/chat/use-search-tool', expect.objectContaining({
      body: JSON.stringify({ thread_id: 'thread-1', request_id: 'request-1' }),
    }));
    await expect(transport.useSearchTool(session, 'thread-1', 'request-2')).rejects.toThrow(
      'HTTP 409: Conflict',
    );
  });
});
