import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/analytics', () => ({
  identifyAnalyticsUser: vi.fn(),
  initAnalytics: vi.fn(),
  resetAnalytics: vi.fn(),
}));

vi.mock('../../services/auth', () => ({
  getStoredSession: vi.fn(),
  onAuthSessionChange: vi.fn(),
}));

vi.mock('../../services/evalAuthBootstrap', () => ({
  readEvalAuthSession: vi.fn(() => null),
}));

import { identifyAnalyticsUser, initAnalytics, resetAnalytics } from '../../services/analytics';
import { getStoredSession, onAuthSessionChange } from '../../services/auth';
import type { AuthSession } from '../../types';
import { useAuthSession } from '../useAuthSession';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};


describe('useAuthSession', () => {
  let emitSession: (value: AuthSession | null) => void;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getStoredSession).mockResolvedValue(null);
    vi.mocked(onAuthSessionChange).mockImplementation(callback => {
      emitSession = callback;
      return vi.fn();
    });
  });

  it('loads the stored session and identifies its user', async () => {
    vi.mocked(getStoredSession).mockResolvedValueOnce(session);

    const { result } = renderHook(() => useAuthSession());

    expect(result.current.authReady).toBe(false);
    await waitFor(() => expect(result.current.authReady).toBe(true));
    expect(result.current.authSession).toEqual(session);
    expect(initAnalytics).toHaveBeenCalledTimes(1);
    expect(identifyAnalyticsUser).toHaveBeenCalledWith(session);
  });

  it('tracks provider session changes and supports explicit authentication', async () => {
    const { result, unmount } = renderHook(() => useAuthSession());
    await waitFor(() => expect(result.current.authReady).toBe(true));

    act(() => emitSession(session));
    expect(result.current.authSession).toEqual(session);

    act(() => result.current.setAuthSession(null));
    expect(resetAnalytics).toHaveBeenCalled();

    act(() => result.current.handleAuthenticated(session));
    expect(result.current.authSession).toEqual(session);
    expect(identifyAnalyticsUser).toHaveBeenLastCalledWith(session);

    unmount();
    expect(vi.mocked(onAuthSessionChange).mock.results[0].value).toHaveBeenCalledTimes(1);
  });
});
