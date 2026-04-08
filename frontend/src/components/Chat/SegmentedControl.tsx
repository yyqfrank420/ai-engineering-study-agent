// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/SegmentedControl.tsx
// Purpose: Reusable segmented control (VS Code-style). Renders a rounded
//          container with options separated by hairline dividers. The active
//          option gets a filled background. Used by both the popover settings
//          in ChatInput and the top-level ModeBar.
// Language: TypeScript / React
// Connects to: (standalone UI primitive, no external dependencies)
// Consumed by: components/Chat/ChatInput.tsx, components/Chat/ModeBar.tsx
// ─────────────────────────────────────────────────────────────────────────────

import { useState } from 'react';
import type { CSSProperties } from 'react';

interface SegmentedControlProps<T extends string> {
  options:  { value: T; label: string }[];
  value:    T;
  onChange: (v: T) => void;
  /** Override the outer container style (defaults to ModeBar's segGroupStyle). */
  containerStyle?: CSSProperties;
  /** Override the divider between options. */
  dividerStyle?: CSSProperties;
  /** Override individual option styling. Receives active + hovered state. */
  optionStyle?: (isActive: boolean, isHovered: boolean) => CSSProperties;
  /** Wrapper around each option span (e.g. ChatInput wraps in a flex container). */
  optionWrapper?: (children: React.ReactNode, index: number) => React.ReactNode;
}

// ── Default styles (match ModeBar's SegmentedGroup exactly) ──────────────────

const defaultContainerStyle: CSSProperties = {
  display:      'inline-flex',
  alignItems:   'center',
  background:   'rgba(255,255,255,0.03)',
  border:       '1px solid #30363d',
  borderRadius: '6px',
  overflow:     'hidden',
  flexShrink:   0,
};

const defaultDividerStyle: CSSProperties = {
  width:      '1px',
  height:     '14px',
  background: '#30363d',
  flexShrink: 0,
};

function defaultOptionStyle(isActive: boolean, isHovered: boolean): CSSProperties {
  return {
    padding:    '3px 8px',
    fontSize:   '0.72rem',
    fontWeight: isActive ? 600 : 400,
    color:      isActive ? '#a78bfa' : isHovered ? '#8b949e' : '#6e7681',
    background: isActive
                  ? 'rgba(167,139,250,0.15)'
                  : isHovered
                  ? 'rgba(255,255,255,0.04)'
                  : 'transparent',
    cursor:     isActive ? 'default' : 'pointer',
    userSelect: 'none',
    transition: 'background 0.12s, color 0.12s',
    whiteSpace: 'nowrap',
    lineHeight: '1.5',
  };
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  containerStyle = defaultContainerStyle,
  dividerStyle   = defaultDividerStyle,
  optionStyle    = defaultOptionStyle,
  optionWrapper,
}: SegmentedControlProps<T>) {
  const [hovered, setHovered] = useState<T | null>(null);

  return (
    <div style={containerStyle}>
      {options.map((opt, i) => {
        const isActive  = opt.value === value;
        const isHovered = opt.value === hovered && !isActive;
        const inner = (
          <>
            {i > 0 && <span style={dividerStyle} />}
            <span
              style={optionStyle(isActive, isHovered)}
              onClick={() => onChange(opt.value)}
              onMouseEnter={() => setHovered(opt.value)}
              onMouseLeave={() => setHovered(null)}
            >
              {opt.label}
            </span>
          </>
        );

        if (optionWrapper) {
          return <span key={opt.value}>{optionWrapper(inner, i)}</span>;
        }
        return (
          <span key={opt.value} style={{ display: 'flex', alignItems: 'center' }}>
            {inner}
          </span>
        );
      })}
    </div>
  );
}
