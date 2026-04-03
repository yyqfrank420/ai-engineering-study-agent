import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useBackendReadiness } from '../useBackendReadiness';

vi.mock('../../services/api', () => ({
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
});
