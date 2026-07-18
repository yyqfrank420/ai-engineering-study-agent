import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/api', () => ({
  prepareBackend: vi.fn().mockResolvedValue({ status: 'ready', faiss_loaded: true }),
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
import {
  fetchDashboardFailures,
  fetchDashboardFunnel,
  fetchDashboardLLMPerformance,
  fetchDashboardOverview,
  fetchDashboardTrends,
  prepareBackend,
} from '../services/api';

const SESSION = {
  access_token: 'token',
  refresh_token: '',
  user: { id: 'user-1', email: 'admin@example.com' },
};

describe('InternalDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders KPI data after loading', async () => {
    render(<InternalDashboard authSession={SESSION} />);

    expect(screen.getByText('Loading dashboard…')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Observability dashboard')).toBeTruthy();
    });

    expect(prepareBackend).toHaveBeenCalledTimes(1);
    expect(screen.getByText('DAU')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('Provider mix')).toBeTruthy();
  });

  it('renders operational tables with fallback values and supports refresh', async () => {
    vi.mocked(fetchDashboardFailures).mockResolvedValueOnce({
      recent_failed_requests: [
        { created_at_epoch: 0, request_id: null },
      ],
      slow_requests: [
        { path: '/api/chat', latency_ms: 2400, trace_id: null, created_at_epoch: 0 },
      ],
      provider_fallbacks: [
        { operation: 'synthesis', provider: 'openai', model: 'gpt', trace_id: null, created_at_epoch: 0 },
      ],
      most_used_modes: [
        { label: 'production/on', count: 3 },
      ],
    });
    vi.mocked(fetchDashboardLLMPerformance).mockResolvedValueOnce({
      operations: [
        {
          operation: 'synthesis',
          provider: 'anthropic',
          model: 'claude',
          calls: 4,
          avg_duration_ms: 1200,
          fallback_rate: 0.25,
          error_rate: 0,
        },
      ],
      recent_fallbacks: [],
    });

    render(<InternalDashboard authSession={SESSION} />);

    await waitFor(() => {
      expect(screen.getByText('Recent failed requests')).toBeTruthy();
    });

    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.getByText('/api/chat')).toBeTruthy();
    expect(screen.getAllByText('synthesis').length).toBeGreaterThan(1);
    expect(screen.getByText('production/on')).toBeTruthy();
    expect(screen.getByText('25%')).toBeTruthy();

    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => {
      expect(fetchDashboardOverview).toHaveBeenCalledTimes(2);
    });
  });

  it('shows an error state and retries loading', async () => {
    vi.mocked(fetchDashboardOverview)
      .mockRejectedValueOnce(new Error('not allowed'))
      .mockResolvedValueOnce({
        window_hours: 24,
        kpis: {
          dau: 1,
          wau: 1,
          prepares: 1,
          chats_sent: 1,
          chats_completed: 1,
          chats_failed: 0,
          stop_rate: 0,
          search_tool_request_rate: 0,
          avg_chat_latency_ms: 10,
        },
        providers: {},
      });

    render(<InternalDashboard authSession={SESSION} />);

    await waitFor(() => expect(screen.getByText('not allowed')).toBeTruthy());

    fireEvent.click(screen.getByText('Retry'));

    await waitFor(() => expect(screen.getByText('Observability dashboard')).toBeTruthy());
  });

  it('shows empty state when any dashboard response is missing', async () => {
    vi.mocked(fetchDashboardFunnel).mockResolvedValueOnce(null as never);

    render(<InternalDashboard authSession={SESSION} />);

    await waitFor(() => {
      expect(screen.getByText('No dashboard data available yet.')).toBeTruthy();
    });
    expect(fetchDashboardTrends).toHaveBeenCalledWith(SESSION, 'day');
    expect(fetchDashboardTrends).toHaveBeenCalledWith(SESSION, 'hour');
  });
});
