import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../services/api', () => ({
  fetchDashboardOverview: vi.fn().mockResolvedValue({
    window_hours: 24,
    kpis: {
      dau: 3,
      wau: 4,
      prepares: 2,
      chats_sent: 5,
      chats_completed: 4,
      chats_failed: 1,
      stop_rate: 0.2,
      search_tool_request_rate: 0.4,
      avg_chat_latency_ms: 123,
    },
    providers: { anthropic: 4, openai: 1 },
  }),
  fetchDashboardTrends: vi.fn().mockResolvedValue({
    bucket: 'day',
    points: [
      {
        start_epoch: 0,
        label: 'Apr 10',
        chat_sent: 5,
        chat_completed: 4,
        chat_failed: 1,
        avg_chat_latency_ms: 123,
        completion_rate: 0.8,
        provider_usage: { anthropic: 4 },
      },
    ],
  }),
  fetchDashboardFunnel: vi.fn().mockResolvedValue({
    window_days: 7,
    steps: [{ event_type: 'auth_viewed', actors: 5, conversion_from_previous: null }],
  }),
  fetchDashboardFailures: vi.fn().mockResolvedValue({
    recent_failed_requests: [],
    slow_requests: [],
    provider_fallbacks: [],
    most_used_modes: [],
  }),
  fetchDashboardLLMPerformance: vi.fn().mockResolvedValue({
    operations: [],
    recent_fallbacks: [],
  }),
}));

import { InternalDashboard } from './InternalDashboard';

describe('InternalDashboard', () => {
  it('renders KPI data after loading', async () => {
    render(
      <InternalDashboard
        authSession={{
          access_token: 'token',
          refresh_token: '',
          user: { id: 'user-1', email: 'admin@example.com' },
        }}
      />,
    );

    expect(screen.getByText('Loading dashboard…')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Observability dashboard')).toBeTruthy();
    });

    expect(screen.getByText('DAU')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('Provider mix')).toBeTruthy();
  });
});
