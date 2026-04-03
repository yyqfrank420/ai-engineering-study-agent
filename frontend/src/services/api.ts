import type { AuthSession, ThreadDetail, ThreadSummary } from '../types';
import { API_BASE } from './config';

async function authedFetch(path: string, session: AuthSession, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
      ...(init?.headers ?? {}),
    },
  });
}

export async function fetchLatestThread(session: AuthSession): Promise<ThreadDetail> {
  const response = await authedFetch('/api/threads/latest', session);
  if (!response.ok) throw new Error('Failed to load latest thread');
  return response.json();
}

export async function fetchThread(session: AuthSession, threadId: string): Promise<ThreadDetail> {
  const response = await authedFetch(`/api/threads/${threadId}`, session);
  if (!response.ok) throw new Error('Failed to load thread');
  return response.json();
}

export async function createThread(session: AuthSession, title = 'New chat'): Promise<ThreadDetail> {
  const response = await authedFetch('/api/threads', session, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
  if (!response.ok) throw new Error('Failed to create thread');
  return response.json();
}

export async function listThreads(session: AuthSession): Promise<ThreadSummary[]> {
  const response = await authedFetch('/api/threads', session);
  if (!response.ok) throw new Error('Failed to list threads');
  const data = await response.json() as { threads: ThreadSummary[] };
  return data.threads;
}

export async function deleteThread(session: AuthSession, threadId: string): Promise<void> {
  const response = await authedFetch(`/api/threads/${threadId}`, session, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete thread');
}

export async function prepareBackend(): Promise<{ status: string; faiss_loaded: boolean }> {
  const response = await fetch(`${API_BASE}/api/prepare`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? 'Backend is still warming up');
  }
  return data as { status: string; faiss_loaded: boolean };
}
