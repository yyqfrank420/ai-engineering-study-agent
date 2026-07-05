// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/services/__tests__/auth.test.ts
// Purpose: Unit tests for signInWithGoogle() in auth.ts
// Language: TypeScript (Vitest)
// Connects to: src/services/auth.ts, src/services/supabase.ts (mocked)
// Inputs:  Mock supabase client responses
// Outputs: Assertion results — redirect, error-throw, missing-URL-throw
// ─────────────────────────────────────────────────────────────────────────────

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mock the supabase module so no real network calls are made ────────────────
// vi.mock hoists to top of file; factory runs before any import of auth.ts
vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      signInWithOAuth: vi.fn(),
      setSession: vi.fn(),
      getSession: vi.fn(),
      refreshSession: vi.fn(),
      onAuthStateChange: vi.fn(),
      signOut: vi.fn(),
    },
  },
}));

// Import AFTER vi.mock so the mocked version is used
import {
  getStoredSession,
  onAuthSessionChange,
  requestOtp,
  signInWithGoogle,
  signOut,
  verifyOtp,
} from '../auth';
import { supabase } from '../supabase';

// ── Helpers ───────────────────────────────────────────────────────────────────

// Cast supabase.auth.signInWithOAuth to a typed mock for cleaner assertions
const mockSignInWithOAuth = vi.mocked(supabase.auth.signInWithOAuth);
const mockSetSession = vi.mocked(supabase.auth.setSession);
const mockGetSession = vi.mocked(supabase.auth.getSession);
const mockRefreshSession = vi.mocked(supabase.auth.refreshSession);
const mockOnAuthStateChange = vi.mocked(supabase.auth.onAuthStateChange);
const mockSignOut = vi.mocked(supabase.auth.signOut);
type OAuthResponse = Awaited<ReturnType<typeof supabase.auth.signInWithOAuth>>;

const oauthErrorResponse = (error: Error): OAuthResponse => ({
  data: { url: null, provider: 'google' },
  error: error as NonNullable<OAuthResponse['error']>,
});

const malformedOAuthResponseWithoutUrl = (): OAuthResponse => ({
  data: { url: null, provider: 'google' },
  error: null,
} as unknown as OAuthResponse);

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  // Reset window.location.assign to a spy so we can assert on it without
  // actually navigating (jsdom doesn't support full navigation)
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    origin: 'https://ai-engineering-study-agent.vercel.app',
    assign: vi.fn(),
  } as unknown as Location);
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('signInWithGoogle', () => {
  it('calls signInWithOAuth with provider google and current origin as redirectTo', async () => {
    mockSignInWithOAuth.mockResolvedValueOnce({
      data: { url: 'https://accounts.google.com/o/oauth2/auth?state=abc', provider: 'google' },
      error: null,
    });

    await signInWithGoogle();

    expect(mockSignInWithOAuth).toHaveBeenCalledOnce();
    expect(mockSignInWithOAuth).toHaveBeenCalledWith({
      provider: 'google',
      options: { redirectTo: 'https://ai-engineering-study-agent.vercel.app' },
    });
  });

  it('redirects to the OAuth URL returned by Supabase on success', async () => {
    const oauthUrl = 'https://accounts.google.com/o/oauth2/auth?state=abc';
    mockSignInWithOAuth.mockResolvedValueOnce({
      data: { url: oauthUrl, provider: 'google' },
      error: null,
    });

    await signInWithGoogle();

    expect(window.location.assign).toHaveBeenCalledWith(oauthUrl);
  });

  it('throws when Supabase returns an error', async () => {
    const supabaseError = new Error('OAuth provider not enabled');
    mockSignInWithOAuth.mockResolvedValueOnce(oauthErrorResponse(supabaseError));

    await expect(signInWithGoogle()).rejects.toThrow('OAuth provider not enabled');
  });

  it('throws when Supabase returns no URL and no error', async () => {
    mockSignInWithOAuth.mockResolvedValueOnce(malformedOAuthResponseWithoutUrl());

    await expect(signInWithGoogle()).rejects.toThrow('Failed to start Google sign-in');
  });

  it('does not call window.location.assign when Supabase returns an error', async () => {
    const supabaseError = new Error('OAuth provider not enabled');
    mockSignInWithOAuth.mockResolvedValueOnce(oauthErrorResponse(supabaseError));

    await expect(signInWithGoogle()).rejects.toThrow();
    expect(window.location.assign).not.toHaveBeenCalled();
  });
});

describe('OTP auth helpers', () => {
  it('requests an OTP with optional captcha token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, captcha_required: false }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestOtp('friend@example.com', 'captcha-token')).resolves.toEqual({
      ok: true,
      captcha_required: false,
    });
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/request-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'friend@example.com', captcha_token: 'captcha-token' }),
    });
  });

  it('maps failed OTP requests to thrown errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Too many attempts' }),
    }));

    await expect(requestOtp('friend@example.com')).rejects.toThrow('Too many attempts');
  });

  it('verifies OTP and persists the Supabase session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        session: {
          access_token: 'backend-access',
          refresh_token: 'backend-refresh',
        },
      }),
    }));
    mockSetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'access',
          refresh_token: 'refresh',
          expires_in: 3600,
          token_type: 'bearer',
        },
        user: { id: 'user-1', email: 'friend@example.com' },
      },
      error: null,
    } as never);

    await expect(verifyOtp('friend@example.com', '123456')).resolves.toEqual({
      access_token: 'access',
      refresh_token: 'refresh',
      expires_in: 3600,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'friend@example.com' },
    });
    expect(mockSetSession).toHaveBeenCalledWith({
      access_token: 'backend-access',
      refresh_token: 'backend-refresh',
    });
  });

  it('throws when backend verification requires captcha or returns no session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, captcha_required: true }),
    }));

    await expect(verifyOtp('friend@example.com', '123456')).rejects.toThrow('CAPTCHA required');
  });

  it('throws when Supabase cannot persist the verified session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        session: {
          access_token: 'backend-access',
          refresh_token: 'backend-refresh',
        },
      }),
    }));
    mockSetSession.mockResolvedValueOnce({
      data: { session: null, user: null },
      error: new Error('persist failed'),
    } as never);

    await expect(verifyOtp('friend@example.com', '123456')).rejects.toThrow('persist failed');
  });
});

describe('stored auth session helpers', () => {
  it('returns null when no stored session exists', async () => {
    mockGetSession.mockResolvedValueOnce({ data: { session: null }, error: null } as never);

    await expect(getStoredSession()).resolves.toBeNull();
  });

  it('returns existing stored session when it is not expiring soon', async () => {
    const now = 2_000_000;
    vi.spyOn(Date, 'now').mockReturnValue(now * 1000);
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'access',
          refresh_token: 'refresh',
          expires_in: 3600,
          expires_at: now + 3600,
          token_type: 'bearer',
          user: { id: 'user-1', email: 'friend@example.com' },
        },
      },
      error: null,
    } as never);

    await expect(getStoredSession()).resolves.toEqual({
      access_token: 'access',
      refresh_token: 'refresh',
      expires_in: 3600,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'friend@example.com' },
    });
    expect(mockRefreshSession).not.toHaveBeenCalled();
  });

  it('refreshes an expiring stored session', async () => {
    const now = 2_000_000;
    vi.spyOn(Date, 'now').mockReturnValue(now * 1000);
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'old',
          refresh_token: 'old-refresh',
          expires_in: 3600,
          expires_at: now + 30,
          token_type: 'bearer',
          user: { id: 'user-1', email: 'friend@example.com' },
        },
      },
      error: null,
    } as never);
    mockRefreshSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'new',
          refresh_token: 'new-refresh',
          expires_in: 3600,
          token_type: 'bearer',
          user: { id: 'user-1', email: 'friend@example.com' },
        },
      },
      error: null,
    } as never);

    await expect(getStoredSession()).resolves.toEqual({
      access_token: 'new',
      refresh_token: 'new-refresh',
      expires_in: 3600,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'friend@example.com' },
    });
  });

  it('returns null when stored or refreshed sessions have no email', async () => {
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'access',
          refresh_token: 'refresh',
          expires_in: 3600,
          expires_at: 0,
          token_type: 'bearer',
          user: { id: 'user-1', email: null },
        },
      },
      error: null,
    } as never);

    await expect(getStoredSession()).resolves.toBeNull();
  });

  it('notifies session changes and unsubscribes', () => {
    const unsubscribe = vi.fn();
    let listener: (event: string, session: unknown) => void = () => undefined;
    mockOnAuthStateChange.mockImplementationOnce((callback) => {
      listener = callback as never;
      return { data: { subscription: { unsubscribe } } } as never;
    });
    const callback = vi.fn();

    const off = onAuthSessionChange(callback);
    listener('SIGNED_IN', {
      access_token: 'access',
      refresh_token: 'refresh',
      expires_in: 3600,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'friend@example.com' },
    });
    listener('SIGNED_OUT', null);
    off();

    expect(callback).toHaveBeenNthCalledWith(1, {
      access_token: 'access',
      refresh_token: 'refresh',
      expires_in: 3600,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'friend@example.com' },
    });
    expect(callback).toHaveBeenNthCalledWith(2, null);
    expect(unsubscribe).toHaveBeenCalled();
  });

  it('signs out through Supabase', async () => {
    await signOut();

    expect(mockSignOut).toHaveBeenCalled();
  });
});
