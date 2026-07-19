import type { AuthSession } from '../types';

export const EVAL_AUTH_STORAGE_KEY = 'ai-engineering-eval-auth';

const EVAL_AUTH_REQUESTED = import.meta.env.VITE_EVAL_AUTH_BOOTSTRAP === 'true';

if (import.meta.env.PROD && EVAL_AUTH_REQUESTED) {
  throw new Error('VITE_EVAL_AUTH_BOOTSTRAP must be false in production builds');
}

export const evalAuthBootstrapEnabled = import.meta.env.DEV && EVAL_AUTH_REQUESTED;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseEvalAuthSession(serialized: string | null): AuthSession | null {
  if (!serialized) return null;

  try {
    const candidate: unknown = JSON.parse(serialized);
    if (!isRecord(candidate) || !isRecord(candidate.user)) return null;
    if (typeof candidate.access_token !== 'string' || candidate.access_token.length === 0) return null;
    if (typeof candidate.refresh_token !== 'string') return null;
    if (typeof candidate.user.id !== 'string' || candidate.user.id.length === 0) return null;
    if (typeof candidate.user.email !== 'string' || candidate.user.email.length === 0) return null;
    if (
      typeof candidate.expires_at !== 'number' ||
      !Number.isFinite(candidate.expires_at) ||
      candidate.expires_at <= Math.floor(Date.now() / 1000)
    ) {
      return null;
    }

    return {
      access_token: candidate.access_token,
      refresh_token: candidate.refresh_token,
      expires_in: typeof candidate.expires_in === 'number' ? candidate.expires_in : undefined,
      token_type: typeof candidate.token_type === 'string' ? candidate.token_type : undefined,
      user: {
        id: candidate.user.id,
        email: candidate.user.email,
      },
    };
  } catch {
    return null;
  }
}

export function readEvalAuthSession(): AuthSession | null {
  if (!evalAuthBootstrapEnabled || typeof localStorage === 'undefined') return null;
  return parseEvalAuthSession(localStorage.getItem(EVAL_AUTH_STORAGE_KEY));
}
