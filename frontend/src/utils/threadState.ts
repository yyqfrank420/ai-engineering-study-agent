import type { GraphData, Message, ThreadDetail } from '../types';
import { normalizeGraphData } from './graphData';

export function storageKeyForThread(userId: string) {
  return `active-thread:${userId}`;
}

export type ThreadSnapshot = {
  title: string;
  messages: Message[];
  graphData: GraphData | null;
};

export function storageKeyForThreadSnapshot(userId: string, threadId: string) {
  return `thread-snapshot:${userId}:${threadId}`;
}

export function readThreadSnapshot(userId: string, threadId: string): ThreadSnapshot | null {
  try {
    const raw = localStorage.getItem(storageKeyForThreadSnapshot(userId, threadId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ThreadSnapshot;
    if (!Array.isArray(parsed.messages)) return null;
    return {
      title: parsed.title || 'New chat',
      messages: parsed.messages.map(message => ({
        ...message,
        isStreaming: false,
      })),
      graphData: normalizeGraphData(parsed.graphData ?? null),
    };
  } catch {
    return null;
  }
}

export function writeThreadSnapshot(userId: string, threadId: string, snapshot: ThreadSnapshot): void {
  localStorage.setItem(
    storageKeyForThreadSnapshot(userId, threadId),
    JSON.stringify({
      ...snapshot,
      graphData: normalizeGraphData(snapshot.graphData),
    }),
  );
}

export function shouldPersistThreadSnapshot(
  liveSnapshot: ThreadSnapshot,
  baselineSnapshot: ThreadSnapshot,
): boolean {
  const liveHasGraph = liveSnapshot.graphData !== null;
  const baselineHasGraph = baselineSnapshot.graphData !== null;

  // During app bootstrap or post-deploy prepare, the live stream state can be
  // momentarily empty before hydrateThread() replays the cached thread. Never
  // overwrite a richer cached snapshot with that transient empty state.
  if (liveSnapshot.messages.length < baselineSnapshot.messages.length) {
    return false;
  }
  if (!liveHasGraph && baselineHasGraph) {
    return false;
  }
  return true;
}

export function clearThreadSnapshot(userId: string, threadId: string): void {
  localStorage.removeItem(storageKeyForThreadSnapshot(userId, threadId));
}

export function mapThreadMessages(messages: ThreadDetail['messages']): Message[] {
  return messages.map(message => ({
    id: message.id,
    role: message.role,
    content: message.content,
    isStreaming: false,
  }));
}
