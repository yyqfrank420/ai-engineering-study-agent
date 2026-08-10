import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

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
import posthog from 'posthog-js';

describe('analytics service', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
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

  it('does not mirror private events without a session', async () => {
    await trackEvent('thread_selected', { thread_id: 'thread-1' });

    expect(captureAnalyticsEvent).not.toHaveBeenCalled();
  });

  it('mirrors private events with a session and swallows mirror failures', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(captureAnalyticsEvent).mockRejectedValueOnce(new Error('mirror down'));
    const session = {
      access_token: 'token',
      refresh_token: 'refresh',
      user: { id: 'user-1', email: 'friend@example.com' },
    };

    await trackEvent('thread_selected', { thread_id: 'thread-1' }, session);

    expect(captureAnalyticsEvent).toHaveBeenCalledWith(
      'thread_selected',
      expect.any(String),
      { thread_id: 'thread-1' },
      session,
    );
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('initialises identifies captures and resets PostHog when configured', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_POSTHOG_KEY', 'ph-key');
    vi.stubEnv('VITE_POSTHOG_HOST', 'https://posthog.example');
    vi.stubEnv('VITE_IS_PRODUCTION', 'true');
    const analytics = await import('./analytics');

    const session = {
      access_token: 'token',
      refresh_token: 'refresh',
      user: { id: 'user-1', email: 'friend@example.com' },
    };

    analytics.identifyAnalyticsUser(session);
    await analytics.trackEvent('auth_viewed', { mode: 'test' }, session);
    analytics.resetAnalytics();

    await vi.waitFor(() => {
      expect(posthog.init).toHaveBeenCalledWith('ph-key', expect.objectContaining({
        api_host: 'https://posthog.example',
        autocapture: false,
      }));
      expect(posthog.identify).toHaveBeenCalledWith('user-1');
      expect(posthog.capture).toHaveBeenCalledWith('auth_viewed', {
        mode: 'test',
        is_production: true,
      });
      expect(posthog.reset).toHaveBeenCalled();
    });
  });
});
