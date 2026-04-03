import type { Message, ThreadDetail } from '../types';

export function storageKeyForThread(userId: string) {
  return `active-thread:${userId}`;
}

export function storageKeyForPrepare(userId: string) {
  return `backend-ready:${userId}`;
}

export function mapThreadMessages(messages: ThreadDetail['messages']): Message[] {
  return messages.map(message => ({
    id: message.id,
    role: message.role,
    content: message.content,
    isStreaming: false,
  }));
}
