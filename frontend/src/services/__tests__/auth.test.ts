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
    },
  },
}));

// Import AFTER vi.mock so the mocked version is used
import { signInWithGoogle } from '../auth';
import { supabase } from '../supabase';

// ── Helpers ───────────────────────────────────────────────────────────────────

// Cast supabase.auth.signInWithOAuth to a typed mock for cleaner assertions
const mockSignInWithOAuth = vi.mocked(supabase.auth.signInWithOAuth);

beforeEach(() => {
  vi.clearAllMocks();
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockSignInWithOAuth.mockResolvedValueOnce({ data: { url: null, provider: 'google' }, error: supabaseError } as any);

    await expect(signInWithGoogle()).rejects.toThrow('OAuth provider not enabled');
  });

  it('throws when Supabase returns no URL and no error', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockSignInWithOAuth.mockResolvedValueOnce({ data: { url: null, provider: 'google' }, error: null } as any);

    await expect(signInWithGoogle()).rejects.toThrow('Failed to start Google sign-in');
  });

  it('does not call window.location.assign when Supabase returns an error', async () => {
    const supabaseError = new Error('OAuth provider not enabled');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockSignInWithOAuth.mockResolvedValueOnce({ data: { url: null, provider: 'google' }, error: supabaseError } as any);

    await expect(signInWithGoogle()).rejects.toThrow();
    expect(window.location.assign).not.toHaveBeenCalled();
  });
});
