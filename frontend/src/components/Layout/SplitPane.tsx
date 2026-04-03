// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Layout/SplitPane.tsx
// Purpose: Resizable two-pane layout. Drag the divider to resize.
//          Left pane: graph canvas (min 40%, max 80%)
//          Right pane: chat (min 20%, max 60%)
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useRef, useState } from 'react';

interface SplitPaneProps {
  left: React.ReactNode;
  right: React.ReactNode;
  graphVisible?: boolean;
}

const MIN_LEFT_PCT  = 40;
const MAX_LEFT_PCT  = 80;
const DEFAULT_LEFT_PCT = 60;

export function SplitPane({ left, right, graphVisible = true }: SplitPaneProps) {
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const visibleLeftPct = graphVisible ? leftPct : 0;

  const onMouseDown = useCallback(() => {
    if (!graphVisible) return;
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [graphVisible]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pct = ((e.clientX - rect.left) / rect.width) * 100;
    setLeftPct(Math.min(MAX_LEFT_PCT, Math.max(MIN_LEFT_PCT, pct)));
  }, []);

  const onMouseUp = useCallback(() => {
    dragging.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  return (
    <div
      ref={containerRef}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      style={{ display: 'flex', flex: 1, overflow: 'hidden' }}
    >
      {/* Left pane */}
      <div
        style={{
          width: `${visibleLeftPct}%`,
          minWidth: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          opacity: graphVisible ? 1 : 0,
          transform: graphVisible ? 'translateX(0)' : 'translateX(-24px)',
          transition: 'width 360ms ease, opacity 280ms ease, transform 360ms ease',
        }}
      >
        {left}
      </div>

      {/* Drag handle */}
      <div
        onMouseDown={onMouseDown}
        style={{
          width: graphVisible ? '4px' : '0px',
          background: '#21262d',
          cursor: graphVisible ? 'col-resize' : 'default',
          flexShrink: 0,
          opacity: graphVisible ? 1 : 0,
          pointerEvents: graphVisible ? 'auto' : 'none',
          transition: 'width 360ms ease, opacity 220ms ease, background 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(167, 139, 250, 0.3)')}
        onMouseLeave={e => (e.currentTarget.style.background = '#21262d')}
      />

      {/* Right pane */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {right}
      </div>
    </div>
  );
}
