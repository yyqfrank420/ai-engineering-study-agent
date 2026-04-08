// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/ModeBar.tsx
// Purpose: Single-row toolbar with segmented controls above the chat input.
//
//          Layout (horizontal, never wraps):
//            complexity  [auto│low│proto│prod]   graph  [auto│on│off]  [● research]
//
//          Design: VS Code-style segmented containers — one rounded rectangle
//          per group, active option filled inside, thin dividers between items.
//
// Language: TypeScript / React
// Connects to: App.tsx (state lifted up), types/index.ts
// Inputs:  complexity, graphMode, researchEnabled + their setters
// Outputs: visual controls; state changes propagate to handleSend in App.tsx
// ─────────────────────────────────────────────────────────────────────────────

import { useState } from 'react';
import type { CSSProperties } from 'react';
import type { ComplexityLevel, GraphMode } from '../../types';
import { SegmentedControl } from './SegmentedControl';

interface ModeBarProps {
  complexity:          ComplexityLevel;
  graphMode:           GraphMode;
  researchEnabled:     boolean;
  onComplexityChange:  (v: ComplexityLevel) => void;
  onGraphModeChange:   (v: GraphMode) => void;
  onResearchChange:    (v: boolean) => void;
}

// SegmentedControl imported from ./SegmentedControl

// ── Research toggle ───────────────────────────────────────────────────────────

function ResearchToggle({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      style={{
        ...segGroupStyle,
        background: enabled ? 'rgba(167,139,250,0.12)' : 'rgba(255,255,255,0.03)',
        borderColor: enabled ? 'rgba(167,139,250,0.35)' : '#30363d',
        transition: 'background 0.15s, border-color 0.15s',
      }}
      onClick={() => onChange(!enabled)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span style={{
        display: 'flex',
        alignItems: 'center',
        gap: '5px',
        padding: '3px 8px',
        fontSize: '0.72rem',
        fontWeight: 500,
        color: enabled ? '#a78bfa' : hovered ? '#8b949e' : '#6e7681',
        cursor: 'pointer',
        userSelect: 'none',
        transition: 'color 0.12s',
        whiteSpace: 'nowrap',
      }}>
        {/* Dot indicator — filled when on, ring when off */}
        <svg width="7" height="7" viewBox="0 0 7 7" style={{ flexShrink: 0 }}>
          <circle
            cx="3.5" cy="3.5" r="3"
            fill={enabled ? '#a78bfa' : 'none'}
            stroke={enabled ? '#a78bfa' : hovered ? '#8b949e' : '#6e7681'}
            strokeWidth="1.2"
          />
        </svg>
        research
      </span>
    </div>
  );
}

// ── Section label ─────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: string }) {
  return (
    <span style={{
      fontSize:      '0.62rem',
      fontWeight:    600,
      color:         '#484f58',
      letterSpacing: '0.04em',
      flexShrink:    0,
      userSelect:    'none',
    }}>
      {children}
    </span>
  );
}

// ── Options ───────────────────────────────────────────────────────────────────

const COMPLEXITY_OPTIONS: { value: ComplexityLevel; label: string }[] = [
  { value: 'auto',       label: 'auto'  },
  { value: 'low',        label: 'low'   },
  { value: 'prototype',  label: 'proto' },
  { value: 'production', label: 'prod'  },
];

const GRAPH_MODE_OPTIONS: { value: GraphMode; label: string }[] = [
  { value: 'auto', label: 'auto' },
  { value: 'on',   label: 'on'   },
  { value: 'off',  label: 'off'  },
];

// ── Main component ────────────────────────────────────────────────────────────

export function ModeBar({
  complexity,
  graphMode,
  researchEnabled,
  onComplexityChange,
  onGraphModeChange,
  onResearchChange,
}: ModeBarProps) {
  return (
    <div style={{
      display:       'flex',
      alignItems:    'center',
      gap:           '7px',
      padding:       '0.4rem 0.9rem',
      borderTop:     '1px solid #21262d',
      background:    '#0d1117',
      flexShrink:    0,
      overflowX:     'auto',   // scrolls rather than wraps on very narrow panes
      overflowY:     'visible',
      // Hide scrollbar — still scrollable, just not intrusive
      scrollbarWidth: 'none',
    }}>
      <SectionLabel>complexity</SectionLabel>
      <SegmentedControl
        options={COMPLEXITY_OPTIONS}
        value={complexity}
        onChange={onComplexityChange}
      />

      <span style={outerDividerStyle} />

      <SectionLabel>graph</SectionLabel>
      <SegmentedControl
        options={GRAPH_MODE_OPTIONS}
        value={graphMode}
        onChange={onGraphModeChange}
      />

      <span style={outerDividerStyle} />

      <ResearchToggle enabled={researchEnabled} onChange={onResearchChange} />
    </div>
  );
}

// ── Style constants ───────────────────────────────────────────────────────────

const segGroupStyle: CSSProperties = {
  display:       'inline-flex',
  alignItems:    'center',
  background:    'rgba(255,255,255,0.03)',
  border:        '1px solid #30363d',
  borderRadius:  '6px',
  overflow:      'hidden',
  flexShrink:    0,
};

const outerDividerStyle: CSSProperties = {
  display:    'inline-block',
  width:      '1px',
  height:     '12px',
  background: '#21262d',
  flexShrink: 0,
  marginLeft: '1px',
  marginRight: '1px',
};

// segOptionStyle moved to SegmentedControl.tsx
