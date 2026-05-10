import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

import {
  fetchDashboardFailures,
  fetchDashboardFunnel,
  fetchDashboardLLMPerformance,
  fetchDashboardOverview,
  fetchDashboardTrends,
} from '../services/api';
import type {
  AuthSession,
  DashboardFailuresResponse,
  DashboardFunnelResponse,
  DashboardLLMPerformanceResponse,
  DashboardOverviewResponse,
  DashboardTrendsResponse,
} from '../types';

interface InternalDashboardProps {
  authSession: AuthSession;
}

export function InternalDashboard({ authSession }: InternalDashboardProps) {
  const [overview, setOverview] = useState<DashboardOverviewResponse | null>(null);
  const [dayTrends, setDayTrends] = useState<DashboardTrendsResponse | null>(null);
  const [hourTrends, setHourTrends] = useState<DashboardTrendsResponse | null>(null);
  const [funnel, setFunnel] = useState<DashboardFunnelResponse | null>(null);
  const [failures, setFailures] = useState<DashboardFailuresResponse | null>(null);
  const [llmPerformance, setLlmPerformance] = useState<DashboardLLMPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextOverview, nextDayTrends, nextHourTrends, nextFunnel, nextFailures, nextLlm] = await Promise.all([
        fetchDashboardOverview(authSession),
        fetchDashboardTrends(authSession, 'day'),
        fetchDashboardTrends(authSession, 'hour'),
        fetchDashboardFunnel(authSession),
        fetchDashboardFailures(authSession),
        fetchDashboardLLMPerformance(authSession),
      ]);
      setOverview(nextOverview);
      setDayTrends(nextDayTrends);
      setHourTrends(nextHourTrends);
      setFunnel(nextFunnel);
      setFailures(nextFailures);
      setLlmPerformance(nextLlm);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [authSession]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <div style={emptyStateStyle}>Loading dashboard…</div>;
  }

  if (error) {
    return (
      <div style={emptyStateStyle}>
        <div>{error}</div>
        <button onClick={() => void load()} style={actionButtonStyle}>Retry</button>
      </div>
    );
  }

  if (!overview || !dayTrends || !hourTrends || !funnel || !failures || !llmPerformance) {
    return <div style={emptyStateStyle}>No dashboard data available yet.</div>;
  }

  const kpis: Array<[string, string | number]> = [
    ['DAU', overview.kpis.dau],
    ['WAU', overview.kpis.wau],
    ['Prepares', overview.kpis.prepares],
    ['Chats sent', overview.kpis.chats_sent],
    ['Completed', overview.kpis.chats_completed],
    ['Failed', overview.kpis.chats_failed],
    ['Stop rate', formatRate(overview.kpis.stop_rate)],
    ['Search-tool rate', formatRate(overview.kpis.search_tool_request_rate)],
  ];

  return (
    <div style={pageStyle}>
      <div style={heroRowStyle}>
        <div>
          <div style={eyebrowStyle}>Internal analytics</div>
          <h1 style={titleStyle}>Observability dashboard</h1>
          <p style={subtitleStyle}>Backend ops, chat funnel, and model/provider behavior from the live app.</p>
        </div>
        <button onClick={() => void load()} style={actionButtonStyle}>Refresh</button>
      </div>

      <div style={cardGridStyle}>
        {kpis.map(([label, value]) => (
          <MetricCard key={label} label={label} value={String(value)} />
        ))}
      </div>

      <div style={twoColumnStyle}>
        <Panel title="Daily trends">
          <TrendBars points={dayTrends.points} valueKey="chat_sent" color="#60a5fa" />
          <MetricTable
            headers={['Bucket', 'Sent', 'Completed', 'Failed', 'Avg latency']}
            rows={dayTrends.points.map((point) => [
              point.label,
              point.chat_sent,
              point.chat_completed,
              point.chat_failed,
              point.avg_chat_latency_ms ?? '—',
            ])}
          />
        </Panel>
        <Panel title="Hourly trends">
          <TrendBars points={hourTrends.points} valueKey="chat_sent" color="#34d399" />
          <MetricTable
            headers={['Bucket', 'Completion', 'Providers']}
            rows={hourTrends.points.map((point) => [
              point.label,
              formatRate(point.completion_rate),
              Object.entries(point.provider_usage).map(([name, count]) => `${name}:${count}`).join(', ') || '—',
            ])}
          />
        </Panel>
      </div>

      <div style={twoColumnStyle}>
        <Panel title="Funnel">
          <MetricTable
            headers={['Step', 'Actors', 'Conv.']}
            rows={funnel.steps.map((step) => [
              step.event_type,
              step.actors,
              step.conversion_from_previous === null ? '—' : formatRate(step.conversion_from_previous),
            ])}
          />
        </Panel>
        <Panel title="Provider mix">
          <MetricTable
            headers={['Provider', 'Calls']}
            rows={Object.entries(overview.providers).map(([provider, calls]) => [provider, calls])}
          />
        </Panel>
      </div>

      <div style={twoColumnStyle}>
        <Panel title="Recent failed requests">
          <MetricTable
            headers={['Path', 'Status', 'Latency', 'Request']}
            rows={failures.recent_failed_requests.map((row) => [
              row.path ?? '—',
              row.status_code ?? '—',
              row.latency_ms ?? '—',
              row.request_id ?? '—',
            ])}
          />
        </Panel>
        <Panel title="Slow requests">
          <MetricTable
            headers={['Path', 'Latency', 'Trace']}
            rows={failures.slow_requests.map((row) => [
              row.path ?? '—',
              row.latency_ms ?? '—',
              row.trace_id ?? '—',
            ])}
          />
        </Panel>
      </div>

      <div style={twoColumnStyle}>
        <Panel title="Provider fallbacks">
          <MetricTable
            headers={['Operation', 'Provider', 'Model', 'Trace']}
            rows={failures.provider_fallbacks.map((row) => [
              row.operation,
              row.provider,
              row.model,
              row.trace_id ?? '—',
            ])}
          />
        </Panel>
        <Panel title="Most-used modes">
          <MetricTable
            headers={['Mode', 'Count']}
            rows={failures.most_used_modes.map((row) => [row.label, row.count])}
          />
        </Panel>
      </div>

      <Panel title="LLM performance">
        <MetricTable
          headers={['Operation', 'Provider', 'Model', 'Calls', 'Avg ms', 'Fallback', 'Error']}
          rows={llmPerformance.operations.map((row) => [
            row.operation,
            row.provider,
            row.model,
            row.calls,
            row.avg_duration_ms,
            formatRate(row.fallback_rate),
            formatRate(row.error_rate),
          ])}
        />
      </Panel>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={metricCardStyle}>
      <div style={metricLabelStyle}>{label}</div>
      <div style={metricValueStyle}>{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={panelStyle}>
      <div style={panelTitleStyle}>{title}</div>
      {children}
    </section>
  );
}

function TrendBars({
  points,
  valueKey,
  color,
}: {
  points: DashboardTrendsResponse['points'];
  valueKey: 'chat_sent' | 'chat_completed' | 'chat_failed';
  color: string;
}) {
  const max = Math.max(1, ...points.map((point) => Number(point[valueKey] ?? 0)));
  return (
    <div style={barsStyle}>
      {points.map((point, index) => (
        <div key={index} style={barColumnStyle}>
          <div
            style={{
              ...barStyle,
              height: `${Math.max(10, (Number(point[valueKey] ?? 0) / max) * 120)}px`,
              background: color,
            }}
          />
          <div style={barLabelStyle}>{String(point.label ?? '')}</div>
        </div>
      ))}
    </div>
  );
}

function MetricTable({ headers, rows }: { headers: string[]; rows: Array<Array<string | number>> }) {
  if (rows.length === 0) {
    return <div style={smallEmptyStyle}>No data yet.</div>;
  }

  return (
    <div style={tableWrapStyle}>
      <table style={tableStyle}>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header} style={tableHeaderStyle}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((value, valueIndex) => (
                <td key={`${rowIndex}-${valueIndex}`} style={tableCellStyle}>{value}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatRate(value: number): string {
  return `${Math.round(value * 100)}%`;
}

const pageStyle: CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '1.5rem',
  display: 'flex',
  flexDirection: 'column',
  gap: '1rem',
};

const heroRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  gap: '1rem',
};

const eyebrowStyle: CSSProperties = {
  fontSize: '0.75rem',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: '#7dd3fc',
  marginBottom: '0.4rem',
};

const titleStyle: CSSProperties = {
  margin: 0,
  fontSize: '1.5rem',
  color: '#f8fafc',
};

const subtitleStyle: CSSProperties = {
  margin: '0.4rem 0 0',
  color: '#94a3b8',
  maxWidth: '42rem',
};

const cardGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: '0.75rem',
};

const metricCardStyle: CSSProperties = {
  padding: '1rem',
  borderRadius: '16px',
  background: 'rgba(15,23,42,0.7)',
  border: '1px solid rgba(148,163,184,0.16)',
};

const metricLabelStyle: CSSProperties = {
  fontSize: '0.75rem',
  color: '#94a3b8',
  marginBottom: '0.35rem',
};

const metricValueStyle: CSSProperties = {
  fontSize: '1.35rem',
  color: '#f8fafc',
  fontWeight: 700,
};

const twoColumnStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
  gap: '1rem',
};

const panelStyle: CSSProperties = {
  padding: '1rem',
  borderRadius: '18px',
  background: 'rgba(10,13,19,0.74)',
  border: '1px solid rgba(255,255,255,0.08)',
};

const panelTitleStyle: CSSProperties = {
  fontSize: '0.95rem',
  fontWeight: 600,
  color: '#e2e8f0',
  marginBottom: '0.75rem',
};

const barsStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-end',
  gap: '0.5rem',
  minHeight: '150px',
  marginBottom: '0.75rem',
};

const barColumnStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: '0.35rem',
  flex: 1,
};

const barStyle: CSSProperties = {
  width: '100%',
  borderRadius: '10px 10px 4px 4px',
  opacity: 0.9,
};

const barLabelStyle: CSSProperties = {
  fontSize: '0.68rem',
  color: '#94a3b8',
};

const tableWrapStyle: CSSProperties = {
  overflowX: 'auto',
};

const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '0.8rem',
};

const tableHeaderStyle: CSSProperties = {
  textAlign: 'left',
  color: '#94a3b8',
  fontWeight: 500,
  padding: '0 0 0.5rem',
  borderBottom: '1px solid rgba(148,163,184,0.16)',
};

const tableCellStyle: CSSProperties = {
  color: '#e2e8f0',
  padding: '0.55rem 0',
  borderBottom: '1px solid rgba(148,163,184,0.08)',
  verticalAlign: 'top',
};

const emptyStateStyle: CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: '0.75rem',
  color: '#94a3b8',
};

const smallEmptyStyle: CSSProperties = {
  color: '#94a3b8',
  fontSize: '0.8rem',
};

const actionButtonStyle: CSSProperties = {
  border: '1px solid rgba(125,211,252,0.25)',
  background: 'rgba(14,165,233,0.12)',
  color: '#bae6fd',
  borderRadius: '999px',
  padding: '0.45rem 0.85rem',
  cursor: 'pointer',
};
