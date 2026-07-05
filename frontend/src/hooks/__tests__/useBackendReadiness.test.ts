import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useBackendReadiness } from '../useBackendReadiness';

vi.mock('../../services/api', () => ({
  captureAnalyticsEvent: vi.fn().mockResolvedValue(undefined),
  prepareBackend: vi.fn(),
}));

import { prepareBackend } from '../../services/api';

const TEST_SESSION = {
  access_token: 'token',
  refresh_token: 'refresh',
  user: {
    id: 'user-1',
    email: 'friend@example.com',
  },
};

describe('useBackendReadiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts unknown for an authenticated production session until prepare succeeds', () => {
    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    expect(result.current.backendReadiness).toBe('unknown');
    expect(result.current.isBackendReady).toBe(false);
  });

  it('marks the backend ready only after /api/prepare succeeds', async () => {
    vi.mocked(prepareBackend).mockResolvedValueOnce({
      status: 'ready',
      faiss_loaded: true,
    });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
      expect(result.current.isBackendReady).toBe(true);
      expect(result.current.prepareMessage).toBeNull();
    });
  });

  it('surfaces prepare failures and allows a retry', async () => {
    vi.mocked(prepareBackend)
      .mockRejectedValueOnce(new Error('Backend unavailable'))
      .mockResolvedValueOnce({
        status: 'ready',
        faiss_loaded: true,
      });

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('error');
      expect(result.current.prepareMessage).toBe('Backend unavailable');
    });

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
      expect(result.current.isBackendReady).toBe(true);
      expect(result.current.prepareMessage).toBeNull();
    });
  });

  it('resets the prepared cache when the authenticated user changes', async () => {
    vi.mocked(prepareBackend).mockResolvedValue({
      status: 'ready',
      faiss_loaded: true,
    });

    const { result, rerender } = renderHook(
      ({ session }) => useBackendReadiness(session),
      { initialProps: { session: TEST_SESSION } },
    );

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('ready');
    });

    rerender({
      session: {
        ...TEST_SESSION,
        user: {
          id: 'user-2',
          email: 'second@example.com',
        },
      },
    });

    await waitFor(() => {
      expect(result.current.backendReadiness).toBe('unknown');
      expect(result.current.isBackendReady).toBe(false);
    });

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(prepareBackend).toHaveBeenCalledTimes(2);
  });

  it('does nothing without an auth session and can clear prepared cache', async () => {
    vi.mocked(prepareBackend).mockResolvedValue({ status: 'ready', faiss_loaded: true });

    const { result, rerender } = renderHook(
      ({ session }) => useBackendReadiness(session),
      { initialProps: { session: null as typeof TEST_SESSION | null } },
    );

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(prepareBackend).not.toHaveBeenCalled();

    rerender({ session: TEST_SESSION });
    await act(async () => {
      await result.current.prepareBackendNow();
    });
    await waitFor(() => expect(result.current.backendReadiness).toBe('ready'));

    act(() => {
      result.current.clearPreparedCache();
    });

    expect(result.current.backendReadiness).toBe('unknown');
  });

  it('polls startup steps and rotates index copy', async () => {
    vi.useFakeTimers();
    const indexError = Object.assign(new Error('warming'), { step: 'index' });
    vi.mocked(prepareBackend).mockRejectedValue(indexError);

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(result.current.backendReadiness).toBe('preparing');
    expect(result.current.prepareMessage).toContain('cold-start');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(result.current.backendReadiness).toBe('preparing');
    expect(result.current.prepareMessage).not.toBeNull();
  });

  it('shows non-index startup steps and fails from interval polling errors', async () => {
    vi.useFakeTimers();
    const databaseStep = Object.assign(new Error('warming'), { step: 'database' });
    vi.mocked(prepareBackend)
      .mockRejectedValueOnce(databaseStep)
      .mockRejectedValueOnce(new Error('Backend gone'));

    const { result } = renderHook(() => useBackendReadiness(TEST_SESSION));

    await act(async () => {
      await result.current.prepareBackendNow();
    });

    expect(result.current.prepareMessage).toBe('Initializing database…');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.backendReadiness).toBe('error');
    expect(result.current.prepareMessage).toBe('Backend gone');
  });
});
