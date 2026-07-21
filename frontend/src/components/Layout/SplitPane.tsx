// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Layout/SplitPane.tsx
// Purpose: Resizable two-pane layout. Drag the divider to resize.
//          Left pane: graph canvas (min 40%, max 80%)
//          Right pane: chat (min 20%, max 60%)
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';

interface SplitPaneProps {
  left: React.ReactNode;
  right: React.ReactNode;
  graphVisible?: boolean;
}

const MIN_LEFT_PCT  = 40;
const MAX_LEFT_PCT  = 80;
const DEFAULT_LEFT_PCT = 60;
const STACKED_QUERY = '(max-width: 1023px)';

function matchesStackedLayout(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(STACKED_QUERY).matches
    : false;
}

export function SplitPane({ left, right, graphVisible = true }: SplitPaneProps) {
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT);
  const [stacked, setStacked] = useState(matchesStackedLayout);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const visibleLeftPct = graphVisible ? leftPct : 0;

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(STACKED_QUERY);
    const update = () => setStacked(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!graphVisible) return;
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.style.cursor = stacked ? 'row-resize' : 'col-resize';
    document.body.style.userSelect = 'none';
  }, [graphVisible, stacked]);

  const onPointerMove = useCallback((event: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const offset = stacked ? event.clientY - rect.top : event.clientX - rect.left;
    const extent = stacked ? rect.height : rect.width;
    const pct = extent > 0 ? (offset / extent) * 100 : DEFAULT_LEFT_PCT;
    setLeftPct(Math.min(MAX_LEFT_PCT, Math.max(MIN_LEFT_PCT, pct)));
  }, [stacked]);

  const onPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  const onSeparatorKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    let next: number | null = null;
    if (event.key === 'Home') next = MIN_LEFT_PCT;
    if (event.key === 'End') next = MAX_LEFT_PCT;
    if ((!stacked && event.key === 'ArrowLeft') || (stacked && event.key === 'ArrowUp')) {
      next = leftPct - 5;
    }
    if ((!stacked && event.key === 'ArrowRight') || (stacked && event.key === 'ArrowDown')) {
      next = leftPct + 5;
    }
    if (next === null) return;
    event.preventDefault();
    setLeftPct(Math.min(MAX_LEFT_PCT, Math.max(MIN_LEFT_PCT, next)));
  }, [leftPct, stacked]);

  return (
    <div
      ref={containerRef}
      className={`split-pane ${stacked ? 'split-pane--stacked' : 'split-pane--side-by-side'}`}
      style={{ display: 'flex', flexDirection: stacked ? 'column' : 'row', flex: 1, overflow: 'hidden' }}
    >
      {/* Left pane */}
      <div
        className="split-pane__graph"
        style={{
          width: stacked ? '100%' : `${visibleLeftPct}%`,
          height: stacked ? `${visibleLeftPct}%` : '100%',
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
        className="split-pane__separator"
        role="separator"
        aria-label="Resize graph and conversation panes"
        aria-orientation={stacked ? 'horizontal' : 'vertical'}
        aria-valuemin={MIN_LEFT_PCT}
        aria-valuemax={MAX_LEFT_PCT}
        aria-valuenow={Math.round(leftPct)}
        tabIndex={graphVisible ? 0 : -1}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onSeparatorKeyDown}
        style={{
          width: stacked ? '100%' : graphVisible ? '4px' : '0px',
          height: stacked ? graphVisible ? '4px' : '0px' : '100%',
          background: '#21262d',
          cursor: graphVisible ? stacked ? 'row-resize' : 'col-resize' : 'default',
          flexShrink: 0,
          opacity: graphVisible ? 1 : 0,
          pointerEvents: graphVisible ? 'auto' : 'none',
          transition: 'width 360ms ease, opacity 220ms ease, background 0.15s',
        }}
        onPointerEnter={e => (e.currentTarget.style.background = 'rgba(167, 139, 250, 0.3)')}
        onPointerLeave={e => {
          e.currentTarget.style.background = '#21262d';
          if (dragging.current) onPointerUp(e);
        }}
      />

      {/* Right pane */}
      <div className="split-pane__conversation" style={{ flex: 1, minHeight: 0, minWidth: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {right}
      </div>
    </div>
  );
}
