import type { AnalyticsEventName, AnalyticsEventProperties, AuthSession } from '../types';
import { captureAnalyticsEvent as mirrorAnalyticsEvent } from './api';

type PostHogClient = typeof import('posthog-js')['default'];

const STORAGE_KEY = 'agent.analytics.anonymous_id';
const POSTHOG_KEY = (import.meta.env.VITE_POSTHOG_KEY as string | undefined)?.trim() ?? '';
const POSTHOG_HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined)?.trim() || 'https://us.i.posthog.com';
const ANALYTICS_ENABLED = import.meta.env.VITE_ANALYTICS_ENABLED !== 'false';
const PUBLIC_EVENTS = new Set<AnalyticsEventName>([
  'auth_viewed',
  'otp_requested',
  'otp_verified',
  'google_signin_started',
]);

let initialised = false;
let posthogPromise: Promise<PostHogClient | null> | null = null;

function withPostHog(action: (client: PostHogClient) => void): void {
  if (!POSTHOG_KEY) return;
  posthogPromise ??= import('posthog-js')
    .then(module => module.default)
    .catch(error => {
      console.warn('[analytics] Failed to load PostHog', error);
      return null;
    });
  void posthogPromise.then(client => {
    if (client) action(client);
  });
}

function ensureAnonymousId(): string {
  const existing = localStorage.getItem(STORAGE_KEY);
  if (existing) {
    return existing;
  }
  const generated = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  localStorage.setItem(STORAGE_KEY, generated);
  return generated;
}

export function getAnalyticsAnonymousId(): string {
  return ensureAnonymousId();
}

export function initAnalytics(): void {
  if (initialised || !ANALYTICS_ENABLED || !POSTHOG_KEY) {
    initialised = true;
    return;
  }
  withPostHog(client => {
    client.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      persistence: 'localStorage',
    });
  });
  initialised = true;
}

export function identifyAnalyticsUser(session: AuthSession | null): void {
  initAnalytics();
  if (!ANALYTICS_ENABLED || !POSTHOG_KEY || !session) {
    return;
  }
  withPostHog(client => client.identify(session.user.id));
}

export function resetAnalytics(): void {
  if (ANALYTICS_ENABLED && POSTHOG_KEY) {
    withPostHog(client => client.reset());
  }
}

export async function trackEvent(
  event: AnalyticsEventName,
  properties: AnalyticsEventProperties = {},
  session?: AuthSession | null,
): Promise<void> {
  initAnalytics();
  const anonymousId = ensureAnonymousId();
  const payload: AnalyticsEventProperties = { ...properties };

  if (ANALYTICS_ENABLED && POSTHOG_KEY) {
    withPostHog(client => client.capture(event, payload));
  }

  try {
    if (!session && !PUBLIC_EVENTS.has(event)) {
      return;
    }
    await mirrorAnalyticsEvent(event, anonymousId, payload, session);
  } catch (error) {
    console.warn('[analytics] Failed to mirror event', event, error);
  }
}
