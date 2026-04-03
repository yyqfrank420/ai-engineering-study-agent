// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/ThinkingIndicator.tsx
// Purpose: Status rows shown while the agent is working. Each active worker
//          appears as a labeled row with a bouncing dot, so the user can see
//          which pipeline phases are running simultaneously.
// ─────────────────────────────────────────────────────────────────────────────

import type { WorkerStatus } from '../../types';

interface ThinkingIndicatorProps {
  workerStatus: WorkerStatus;
}

// Display labels and dot colors per worker, in pipeline order
const WORKER_CONFIG: {
  key: keyof WorkerStatus;
  label: string;
  color: string;
}[] = [
  { key: 'orchestrator', label: 'Orchestrator',  color: '#a78bfa' },
  { key: 'rag',          label: 'Book search',   color: '#84a4fb' },
  { key: 'research',     label: 'Web research',  color: '#60c5fa' },
  { key: 'graph',        label: 'Graph builder', color: '#60a5fa' },
];

export function ThinkingIndicator({ workerStatus }: ThinkingIndicatorProps) {
  const active = WORKER_CONFIG.filter(w => workerStatus[w.key] !== null);

  if (active.length === 0) return null;

  return (
    <div style={{
      padding: '0.4rem 1rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.3rem',
      borderTop: '1px solid #21262d',
    }}>
      {active.map((w, i) => (
        <div key={w.key} style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
        }}>
          {/* Bouncing dot */}
          <div style={{
            width: 5, height: 5,
            borderRadius: '50%',
            background: w.color,
            animation: `bounce 1.2s ease-in-out ${i * 0.15}s infinite`,
            flexShrink: 0,
          }} />
          {/* Worker label */}
          <span style={{
            fontSize: '0.7rem',
            color: '#6e7681',
            minWidth: '80px',
          }}>
            {w.label}
          </span>
          {/* Status text from server */}
          <span style={{
            fontSize: '0.7rem',
            color: '#8b949e',
            letterSpacing: '0.02em',
          }}>
            {workerStatus[w.key]}
          </span>
        </div>
      ))}
    </div>
  );
}
