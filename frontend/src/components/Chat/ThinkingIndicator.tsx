// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/ThinkingIndicator.tsx
// Purpose: Status rows shown while the agent is working. Each active worker
//          appears as a labeled row with a bouncing dot, so the user can see
//          which pipeline phases are running simultaneously.
// ─────────────────────────────────────────────────────────────────────────────

import type { WorkerStatus, WorkflowProgress } from '../../types';

interface ThinkingIndicatorProps {
  workerStatus: WorkerStatus;
  workflowProgress?: WorkflowProgress[];
  isGenerating?: boolean;
  explanationPaused?: boolean;
  onTogglePause?: () => void;
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
  { key: 'critic',       label: 'Design critic', color: '#f59e0b' },
];

export function ThinkingIndicator({
  workerStatus,
  workflowProgress = [],
  isGenerating = false,
  explanationPaused = false,
  onTogglePause,
}: ThinkingIndicatorProps) {
  const active = WORKER_CONFIG.filter(w => workerStatus[w.key] !== null);

  if (active.length === 0 && workflowProgress.length === 0) return null;

  return (
    <div style={{
      padding: '0.65rem 1rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.5rem',
      borderTop: '1px solid #21262d',
      background: 'linear-gradient(180deg, rgba(13,17,23,0.45), rgba(22,27,34,0.75))',
    }}>
      {workflowProgress.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <div>
              <div style={{ color: '#d8dee9', fontSize: '0.74rem', fontWeight: 650 }}>
                {explanationPaused ? 'Explanation reveal paused' : 'Building your architecture'}
              </div>
              <div style={{ color: '#6e7681', fontSize: '0.64rem', marginTop: 2 }}>
                Candidate diagrams stay private until the clarity check passes.
              </div>
            </div>
            {(isGenerating || explanationPaused) && onTogglePause && (
              <button
                type="button"
                onClick={onTogglePause}
                style={{
                  border: '1px solid rgba(167,139,250,0.3)',
                  background: explanationPaused ? 'rgba(167,139,250,0.18)' : 'rgba(167,139,250,0.08)',
                  color: '#c4b5fd',
                  borderRadius: 999,
                  padding: '0.28rem 0.65rem',
                  fontSize: '0.64rem',
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
              >
                {explanationPaused ? 'Resume reveal' : 'Pause reveal'}
              </button>
            )}
          </div>
          <div style={{ display: 'grid', gap: '0.34rem' }}>
            {workflowProgress.slice(-4).map(item => (
              <div key={item.phase} style={{ display: 'grid', gridTemplateColumns: '14px 1fr', columnGap: '0.45rem' }}>
                <span style={{
                  color: item.status === 'complete' ? '#3fb950' : item.status === 'retry' ? '#f59e0b' : '#a78bfa',
                  fontSize: '0.72rem',
                  lineHeight: 1.35,
                }}>
                  {item.status === 'complete' ? '✓' : item.status === 'retry' ? '↻' : '●'}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: '#aeb6c2', fontSize: '0.68rem', lineHeight: 1.35 }}>{item.title}</div>
                  <div style={{ color: '#69717d', fontSize: '0.62rem', lineHeight: 1.35 }}>{item.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
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
