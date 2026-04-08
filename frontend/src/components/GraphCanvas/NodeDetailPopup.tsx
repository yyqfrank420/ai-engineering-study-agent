// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/NodeDetailPopup.tsx
// Purpose: Popup shown when a graph node is clicked. Shows:
//          - Type badge + tier badge (public/private)
//          - Node label + technology
//          - Description (always present, from graph worker)
//          - Book detail (async enrichment from Node Detail Worker, or subtle placeholder)
//          - Book references
//          - Direct connections from the graph
// Connects to: types/index.ts
// ─────────────────────────────────────────────────────────────────────────────

import type { GraphEdge, GraphNode } from '../../types';
import { TYPE_STYLE } from '../../utils/graphColors';

// Derive the flat color / background maps that this component uses from the
// canonical TYPE_STYLE. badge → accent color, fill → background.
const TYPE_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(TYPE_STYLE).map(([k, v]) => [k, v.badge]),
);
const TYPE_BG: Record<string, string> = Object.fromEntries(
  Object.entries(TYPE_STYLE).map(([k, v]) => [k, v.fill]),
);

interface NodeDetailPopupProps {
  node: GraphNode;
  edges: GraphEdge[];   // full graph edges — used to derive connections
  onClose: () => void;
  onTellMeMore: (node: GraphNode) => void;
  onExpandGraph: (node: GraphNode) => void;
}

export function NodeDetailPopup({ node, edges, onClose, onTellMeMore, onExpandGraph }: NodeDetailPopupProps) {
  // Derive which nodes this node connects to/from
  const outgoing = edges.filter(e => e.source === node.id || (e.source as any)?.id === node.id);
  const incoming = edges.filter(e => e.target === node.id || (e.target as any)?.id === node.id);
  const showExpandGraph = node.type !== 'decision';

  return (
    <div style={{
      position: 'absolute',
      top: '1rem',
      right: '1rem',
      width: '290px',
      background: 'rgba(10,14,26,0.96)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      border: '1px solid rgba(167,139,250,0.2)',
      borderTop: `3px solid ${TYPE_COLORS[node.type] ?? '#6b7280'}`,
      borderRadius: '8px',
      padding: '0.9rem 1rem',
      zIndex: 10,
      boxShadow: '0 0 0 1px rgba(167,139,250,0.06), 0 20px 56px rgba(0,0,0,0.7)',
      maxHeight: 'calc(100% - 2rem)',
      overflowY: 'auto',
    }}>
      {/* Header — type badge + tier badge + close button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.6rem' }}>
        <div>
          {/* Badges row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginBottom: '0.2rem' }}>
            <span style={{
              fontSize: '0.55rem',
              fontWeight: 700,
              letterSpacing: '0.07em',
              padding: '1px 5px',
              borderRadius: 3,
              background: TYPE_BG[node.type] ?? 'rgba(100,116,139,0.12)',
              color: TYPE_COLORS[node.type] ?? '#8b949e',
              border: `1px solid ${TYPE_COLORS[node.type] ?? '#6b7280'}33`,
            }}>
              {node.type.toUpperCase()}
            </span>
            {node.tier && (
              <span style={{
                fontSize: '0.5rem',
                fontWeight: 700,
                letterSpacing: '0.06em',
                padding: '1px 4px',
                borderRadius: 3,
                background: node.tier === 'public'
                  ? 'rgba(251,191,36,0.12)' : 'rgba(100,116,139,0.10)',
                color: node.tier === 'public' ? '#fbbf24' : '#6e7681',
                border: `1px solid ${node.tier === 'public' ? 'rgba(251,191,36,0.25)' : 'rgba(100,116,139,0.2)'}`,
              }}>
                {node.tier === 'public' ? 'PUBLIC' : 'PRIVATE'}
              </span>
            )}
          </div>
          {/* Label */}
          <div style={{
            fontWeight: 600,
            fontSize: '0.9rem',
            color: '#e6edf3',
            lineHeight: 1.3,
          }}>
            {node.label}
          </div>
          {/* Technology */}
          {node.technology && (
            <div style={{
              fontSize: '0.68rem',
              color: '#6e7681',
              marginTop: '0.1rem',
            }}>
              {node.technology}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          aria-label="Close node detail"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#6e7681', fontSize: '1.1rem', lineHeight: 1,
            padding: '0.25rem',
            minWidth: '28px', minHeight: '28px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: '4px',
            flexShrink: 0,
            transition: 'color 0.15s, background 0.15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.color = '#e6edf3';
            e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
          }}
          onMouseLeave={e => {
            e.currentTarget.style.color = '#6e7681';
            e.currentTarget.style.background = 'none';
          }}
        >
          ×
        </button>
      </div>

      {/* Divider */}
      <div style={{ borderTop: '1px solid #1e2a3a', marginBottom: '0.6rem' }} />

      {/* Description — always present from graph worker, immediate */}
      {node.description && (
        <p style={{
          fontSize: '0.76rem',
          color: '#8b949e',
          lineHeight: 1.6,
          margin: '0 0 0.5rem',
        }}>
          {node.description}
        </p>
      )}

      {/* Book detail — enriched async by Node Detail Worker */}
      {node.detail && (
        <p style={{
          fontSize: '0.74rem',
          color: '#c9d1d9',
          lineHeight: 1.65,
          margin: '0 0 0.6rem',
          borderLeft: '2px solid rgba(167,139,250,0.3)',
          paddingLeft: '0.5rem',
        }}>
          {node.detail}
        </p>
      )}

      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: '0.45rem',
        marginBottom: '0.6rem',
      }}>
        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
          <button
            onClick={() => onTellMeMore(node)}
            style={{
              background: 'rgba(167,139,250,0.12)',
              border: '1px solid rgba(167,139,250,0.28)',
              color: '#d9c9ff',
              borderRadius: '999px',
              padding: '0.3rem 0.75rem',
              fontSize: '0.7rem',
              cursor: 'pointer',
            }}
          >
            Tell me more
          </button>
          {showExpandGraph && (
            <button
              onClick={() => onExpandGraph(node)}
              style={{
                background: 'rgba(56,189,248,0.12)',
                border: '1px solid rgba(56,189,248,0.28)',
                color: '#bfefff',
                borderRadius: '999px',
                padding: '0.3rem 0.75rem',
                fontSize: '0.7rem',
                cursor: 'pointer',
              }}
            >
              Expand graph
            </button>
          )}
        </div>
        <div style={{
          color: '#6e7681',
          fontSize: '0.67rem',
          lineHeight: 1.45,
        }}>
          {showExpandGraph
            ? 'Ask the chat to explain this part or expand the nearby graph structure.'
            : 'Ask the chat to explain this constraint more clearly.'}
        </div>
      </div>

      {/* Book references */}
      {node.book_refs && node.book_refs.length > 0 && (
        <>
          <div style={{ fontSize: '0.62rem', color: '#6e7681', fontWeight: 600, letterSpacing: '0.06em', marginBottom: '0.25rem' }}>
            BOOK REFS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', marginBottom: '0.6rem' }}>
            {node.book_refs.map((ref, i) => (
              <span key={i} style={{
                fontSize: '0.68rem',
                color: '#60a5fa',
                background: 'rgba(59,130,246,0.08)',
                border: '1px solid rgba(59,130,246,0.15)',
                borderRadius: 3,
                padding: '1px 6px',
                display: 'inline-block',
              }}>
                {ref}
              </span>
            ))}
          </div>
        </>
      )}

      {/* Connections */}
      {(outgoing.length > 0 || incoming.length > 0) && (
        <>
          <div style={{ borderTop: '1px solid #1e2a3a', marginBottom: '0.4rem' }} />
          <div style={{ fontSize: '0.62rem', color: '#6e7681', fontWeight: 600, letterSpacing: '0.06em', marginBottom: '0.3rem' }}>
            CONNECTIONS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
            {outgoing.map((e, i) => (
              <div key={`out-${i}`} style={{ fontSize: '0.68rem', color: '#6e7681', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <span style={{ color: '#34d399', fontWeight: 600, fontSize: '0.62rem' }}>→</span>
                <span style={{ color: '#8b949e' }}>{e.label}</span>
                {e.technology && (
                  <span style={{ color: '#a78bfa', fontSize: '0.58rem', background: 'rgba(139,92,246,0.1)', padding: '0 4px', borderRadius: 2 }}>
                    {e.technology}
                  </span>
                )}
                {e.sync === 'async' && (
                  <span style={{ color: '#fbbf24', fontSize: '0.5rem', background: 'rgba(251,191,36,0.12)', padding: '0 3px', borderRadius: 2 }}>
                    ASYNC
                  </span>
                )}
              </div>
            ))}
            {incoming.map((e, i) => (
              <div key={`in-${i}`} style={{ fontSize: '0.68rem', color: '#6e7681', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <span style={{ color: '#60a5fa', fontWeight: 600, fontSize: '0.62rem' }}>←</span>
                <span style={{ color: '#8b949e' }}>{e.label}</span>
                {e.technology && (
                  <span style={{ color: '#a78bfa', fontSize: '0.58rem', background: 'rgba(139,92,246,0.1)', padding: '0 4px', borderRadius: 2 }}>
                    {e.technology}
                  </span>
                )}
                {e.sync === 'async' && (
                  <span style={{ color: '#fbbf24', fontSize: '0.5rem', background: 'rgba(251,191,36,0.12)', padding: '0 3px', borderRadius: 2 }}>
                    ASYNC
                  </span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
