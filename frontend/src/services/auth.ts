import type { AuthSession } from '../types';
import { supabase } from './supabase';
import { API_BASE } from './config';

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? data.message ?? 'Request failed');
  }
  return data as T;
}

export async function requestOtp(email: string, captchaToken?: string): Promise<{ ok: boolean; captcha_required: boolean; }> {
  return postJSON('/api/auth/request-otp', { email, captcha_token: captchaToken ?? null });
}

export async function verifyOtp(email: string, token: string, captchaToken?: string): Promise<AuthSession> {
  const result = await postJSON<{ ok: boolean; captcha_required?: boolean; session?: AuthSession }>(
    '/api/auth/verify-otp',
    { email, token, captcha_token: captchaToken ?? null },
  );
  if (!result.session) {
    throw new Error(result.captcha_required ? 'CAPTCHA required' : 'Verification failed');
  }
  const { data, error } = await supabase.auth.setSession({
    access_token: result.session.access_token,
    refresh_token: result.session.refresh_token,
  });
  if (error || !data.session || !data.user?.email) {
    throw error ?? new Error('Failed to persist session');
  }
  return {
    access_token: data.session.access_token,
    refresh_token: data.session.refresh_token,
    expires_in: data.session.expires_in,
    token_type: data.session.token_type,
    user: {
      id: data.user.id,
      email: data.user.email,
    },
  };
}

function toAuthSession(session: NonNullable<Awaited<ReturnType<typeof supabase.auth.getSession>>['data']['session']>): AuthSession {
  return {
    access_token:  session.access_token,
    refresh_token: session.refresh_token,
    expires_in:    session.expires_in,
    token_type:    session.token_type,
    user: {
      id:    session.user.id,
      email: session.user.email!,
    },
  };
}

export async function getStoredSession(): Promise<AuthSession | null> {
  const { data } = await supabase.auth.getSession();
  const session = data.session;
  if (!session) return null;

  // If the access token is expired or expiring within 60s, force a refresh
  // rather than relying on the background timer (which resets on page load).
  const nowSecs   = Math.floor(Date.now() / 1000);
  const expiresAt = (session as { expires_at?: number }).expires_at ?? 0;
  if (expiresAt > 0 && expiresAt - nowSecs < 60) {
    const { data: refreshed, error } = await supabase.auth.refreshSession();
    if (error || !refreshed.session?.user.email) return null;
    return toAuthSession(refreshed.session);
  }

  if (!session.user.email) return null;
  return toAuthSession(session);
}

export function onAuthSessionChange(callback: (session: AuthSession | null) => void): () => void {
  const { data } = supabase.auth.onAuthStateChange(async (_event, session) => {
    if (!session || !session.user.email) {
      callback(null);
      return;
    }
    callback({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      expires_in: session.expires_in,
      token_type: session.token_type,
      user: {
        id: session.user.id,
        email: session.user.email,
      },
    });
  });
  return () => { data.subscription.unsubscribe(); };
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut();
}
