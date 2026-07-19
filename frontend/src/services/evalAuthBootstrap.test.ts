import { describe, expect, it, vi } from 'vitest';

import { parseEvalAuthSession } from './evalAuthBootstrap';

const VALID_SESSION = {
  access_token: 'signed-access-token',
  refresh_token: '',
  expires_in: 1800,
  expires_at: 2_000_000_000,
  token_type: 'bearer',
  user: { id: 'user-1', email: 'eval@example.com' },
};

describe('evaluation auth bootstrap', () => {
  it('accepts a bounded internal session without requiring a refresh token', () => {
    expect(parseEvalAuthSession(JSON.stringify(VALID_SESSION))).toEqual({
      access_token: 'signed-access-token',
      refresh_token: '',
      expires_in: 1800,
      token_type: 'bearer',
      user: { id: 'user-1', email: 'eval@example.com' },
    });
  });

  it.each([
    null,
    'not-json',
    JSON.stringify({ ...VALID_SESSION, access_token: '' }),
    JSON.stringify({ ...VALID_SESSION, expires_at: undefined }),
    JSON.stringify({ ...VALID_SESSION, user: { id: '', email: 'eval@example.com' } }),
  ])('rejects malformed session input', serialized => {
    expect(parseEvalAuthSession(serialized)).toBeNull();
  });

  it('rejects an expired session', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2033-05-18T03:33:21Z'));
    expect(parseEvalAuthSession(JSON.stringify(VALID_SESSION))).toBeNull();
    vi.useRealTimers();
  });
});
