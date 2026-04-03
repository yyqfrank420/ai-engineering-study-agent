// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/ContextBar.tsx
// Purpose: Shows the selected graph node as a context pill + 3 suggested
//          follow-up chips. Clicking a chip sends it as a message.
// ─────────────────────────────────────────────────────────────────────────────

import type { SelectedNode } from '../../types';

interface ContextBarProps {
  selectedNode: SelectedNode | null;
  onSendMessage: (content: string) => void;
  onClear: () => void;
}

export function ContextBar({ selectedNode, onSendMessage, onClear }: ContextBarProps) {
  if (!selectedNode) return null;

  return (
    <div style={{
      padding:             '0.5rem 1rem',
      borderTop:           '1px solid rgba(255,255,255,0.06)',
      background:          'rgba(10,13,19,0.4)',
      backdropFilter:      'blur(12px)',
      WebkitBackdropFilter:'blur(12px)',
      display:             'flex',
      flexDirection:       'column',
      gap:                 '0.4rem',
    }}>
      {/* Context pill */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          padding: '2px 10px',
          borderRadius: '999px',
          background: 'rgba(167, 139, 250, 0.08)',
          color: '#a78bfa',
          fontSize: '0.75rem',
          border: '1px solid rgba(167, 139, 250, 0.2)',
        }}>
          <span style={{ color: '#a78bfa' }}>⊙</span>
          {selectedNode.node.label}
        </span>
        <button
          onClick={onClear}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#6e7681', fontSize: '0.75rem', padding: '0 4px',
          }}
        >
          ×
        </button>
      </div>

      {/* Suggestion chips */}
      {selectedNode.suggestions.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
          {selectedNode.suggestions.map((q, i) => (
            <button
              key={i}
              onClick={() => onSendMessage(q)}
              style={{
                padding:              '4px 10px',
                borderRadius:         '999px',
                background:           'rgba(255,255,255,0.04)',
                backdropFilter:       'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
                border:               '1px solid rgba(255,255,255,0.08)',
                boxShadow:            'inset 0 1px 0 rgba(255,255,255,0.05)',
                color:                '#8b949e',
                fontSize:             '0.72rem',
                cursor:               'pointer',
                transition:           'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'rgba(167,139,250,0.1)';
                e.currentTarget.style.borderColor = 'rgba(167,139,250,0.35)';
                e.currentTarget.style.color = '#a78bfa';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
                e.currentTarget.style.color = '#8b949e';
              }}
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
