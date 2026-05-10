import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('posthog-js', () => ({
  default: {
    init: vi.fn(),
    capture: vi.fn(),
    identify: vi.fn(),
    reset: vi.fn(),
  },
}));

vi.mock('./api', () => ({
  captureAnalyticsEvent: vi.fn().mockResolvedValue(undefined),
}));

import { captureAnalyticsEvent } from './api';
import { getAnalyticsAnonymousId, trackEvent } from './analytics';

describe('analytics service', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('reuses a stable anonymous id and mirrors events to the backend', async () => {
    const first = getAnalyticsAnonymousId();
    const second = getAnalyticsAnonymousId();

    await trackEvent('auth_viewed');

    expect(first).toBe(second);
    expect(captureAnalyticsEvent).toHaveBeenCalledWith(
      'auth_viewed',
      first,
      {},
      undefined,
    );
  });
});
