// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/services/sse.ts
// Purpose: SSE client — posts requests to the backend and reads the response
//          as a Server-Sent Events stream. Uses fetch() + ReadableStream
//          because EventSource only supports GET requests.
//          Authenticated requests include a Supabase bearer token and thread ID.
// Language: TypeScript
// Connects to: hooks/useAgentStream.ts (consumed via sseClient singleton)
// Inputs:  VITE_API_URL env var (empty string = relative URL, proxied by Vite
//          dev server; set to full backend URL in production)
// Outputs: ServerEvent objects dispatched to registered handlers
// ─────────────────────────────────────────────────────────────────────────────

import type { AuthSession, ComplexityLevel, GraphMode, ServerEvent } from '../types';
import { API_BASE } from './config';

export interface StreamMeta {
  kind: 'chat' | 'node-selected';
  clientRequestId: string;
}

export type EventHandler = (event: ServerEvent, meta: StreamMeta) => void;

function dispatchSSEChunk(chunk: string, handlers: EventHandler[], meta: StreamMeta): boolean {
  const line = chunk.trim();
  if (!line.startsWith('data: ')) return false;

  try {
    const event = JSON.parse(line.slice(6)) as ServerEvent;
    handlers.forEach(handler => handler(event, meta));
    return event.type === 'done';
  } catch {
    console.error('[sse] Failed to parse event:', line);
    return false;
  }
}

/**
 * Read an SSE stream from a fetch Response and dispatch each event to handlers.
 *
 * SSE wire format:
 *   data: <json>\n\n
 *
 * We split on double-newlines rather than using EventSource because EventSource
 * only supports GET requests.
 */
async function consumeSSEStream(response: Response, handlers: EventHandler[], meta: StreamMeta): Promise<boolean> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  if (!response.body) {
    throw new Error('Response has no body');
  }

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = '';
  let sawDone   = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // stream: true tells the decoder this chunk may be mid-codepoint
    buffer += decoder.decode(value, { stream: true });

    // SSE events are delimited by a blank line. Accept both LF and CRLF framing.
    const chunks = buffer.split(/\r?\n\r?\n/);
    buffer = chunks.pop()!;  // last element is the incomplete trailing chunk

    for (const chunk of chunks) {
      sawDone = dispatchSSEChunk(chunk, handlers, meta) || sawDone;
    }
  }

  if (buffer.trim()) {
    sawDone = dispatchSSEChunk(buffer, handlers, meta) || sawDone;
  }

  return sawDone;
}

export class SSEClient {
  private eventHandlers: EventHandler[] = [];
  // AbortController for the active /api/chat stream (null when idle)
  private _chatAbort: AbortController | null = null;

  /**
   * POST /api/chat — runs the agent pipeline and streams events.
   * Rejects if the HTTP request itself fails (network error, non-2xx status).
   * Application-level errors arrive as { type: 'error' } SSE events.
   * AbortError (from stopGeneration) is swallowed — it's an intentional cancel.
   */
  async sendMessage(
    session: AuthSession,
    threadId: string,
    content: string,
    opts?: { complexity?: ComplexityLevel; graphMode?: GraphMode; researchEnabled?: boolean },
    clientRequestId = Math.random().toString(36).slice(2),
  ): Promise<boolean> {
    this._chatAbort = new AbortController();
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          thread_id:        threadId,
          content,
          complexity:       opts?.complexity       ?? 'auto',
          graph_mode:       opts?.graphMode        ?? 'auto',
          research_enabled: opts?.researchEnabled  ?? false,
        }),
        signal: this._chatAbort.signal,
      });
      return await consumeSSEStream(response, this.eventHandlers, {
        kind: 'chat',
        clientRequestId,
      });
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return false;
      throw err;
    } finally {
      this._chatAbort = null;
    }
  }

  /** Cancel an in-flight /api/chat stream. No-op if nothing is streaming. */
  stopGeneration(): void {
    this._chatAbort?.abort();
    this._chatAbort = null;
  }

  /**
   * POST /api/node-selected — generates suggested questions for a graph node.
   * Streams a suggested_questions event then a done event.
   */
  async sendNodeSelected(
    session: AuthSession,
    threadId: string,
    nodeId: string,
    title: string,
    description: string,
    clientRequestId = Math.random().toString(36).slice(2),
  ): Promise<boolean> {
    const response = await fetch(`${API_BASE}/api/node-selected`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        thread_id: threadId,
        node_id: nodeId,
        title,
        description,
      }),
    });
    return await consumeSSEStream(response, this.eventHandlers, {
      kind: 'node-selected',
      clientRequestId,
    });
  }

  async useSearchTool(session: AuthSession, threadId: string, requestId: string): Promise<{ ok: boolean; status: string }> {
    const response = await fetch(`${API_BASE}/api/chat/use-search-tool`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        thread_id: threadId,
        request_id: requestId,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
  }

  /** Register a handler that fires for every SSE event, across all requests. */
  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.push(handler);
    return () => {
      this.eventHandlers = this.eventHandlers.filter(h => h !== handler);
    };
  }
}

// Module-level singleton — one SSE client for the whole app lifetime
export const sseClient = new SSEClient();
