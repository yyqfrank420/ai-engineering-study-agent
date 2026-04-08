// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/utils/graphColors.ts
// Purpose: Canonical node-type color palette for architecture graph rendering.
//          Each node type maps to fill (background), stroke (border), and badge
//          (accent/text) colors. Single source of truth — consumed by both the
//          D3 canvas renderer and the node detail popup.
// Language: TypeScript
// Connects to: (standalone constants, no runtime dependencies)
// Consumed by: components/GraphCanvas/D3Graph.tsx, components/GraphCanvas/NodeDetailPopup.tsx
// ─────────────────────────────────────────────────────────────────────────────

export interface TypeStyle {
  fill:   string;  // translucent background
  stroke: string;  // border / outline
  badge:  string;  // solid accent color (badges, text highlights)
}

/** Per-type color palette for graph nodes. */
export const TYPE_STYLE: Record<string, TypeStyle> = {
  client:    { fill: 'rgba(59,130,246,0.12)',  stroke: 'rgba(59,130,246,0.85)',  badge: '#60a5fa'  },
  service:   { fill: 'rgba(139,92,246,0.12)',  stroke: 'rgba(139,92,246,0.85)',  badge: '#a78bfa'  },
  datastore: { fill: 'rgba(16,185,129,0.12)',  stroke: 'rgba(16,185,129,0.85)',  badge: '#34d399'  },
  gateway:   { fill: 'rgba(217,119,6,0.12)',   stroke: 'rgba(217,119,6,0.85)',   badge: '#fbbf24'  },
  network:   { fill: 'rgba(239,68,68,0.10)',   stroke: 'rgba(239,68,68,0.80)',   badge: '#f87171'  },
  external:  { fill: 'rgba(100,116,139,0.08)', stroke: 'rgba(100,116,139,0.6)',  badge: '#94a3b8'  },
  decision:  { fill: 'rgba(14,165,233,0.10)',  stroke: 'rgba(14,165,233,0.82)',  badge: '#38bdf8'  },
};

/** Fallback style for unknown / unrecognised node types. */
export const FALLBACK_STYLE: TypeStyle = {
  fill: 'rgba(100,116,139,0.08)', stroke: 'rgba(100,116,139,0.6)', badge: '#94a3b8',
};
