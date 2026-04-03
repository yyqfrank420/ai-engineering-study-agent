// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/SequenceBar.tsx
// Purpose: Media-player-style walkthrough bar for graph sequences.
//          Controls: Back · Play/Pause (autoplay) · Next · dot scrubber · Exit.
//          Autoplay advances one step every 1.8 s; stops at last step.
//          Exit (✕) dismisses the bar and resets to overview via onDismiss.
// Language: TypeScript / React
// Connects to: GraphCanvas/index.tsx (currentStep, onStepChange, onDismiss)
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react';
import type React from 'react';
import type { CSSProperties } from 'react';

interface SequenceBarProps {
  currentStep:     number;   // -1 = overview / not started
  totalSteps:      number;
  stepDescription: string;
  onStepChange:    (step: number) => void;
  onDismiss:       () => void;
}

export function SequenceBar({
  currentStep,
  totalSteps,
  stepDescription,
  onStepChange,
  onDismiss,
}: SequenceBarProps) {
  const [isPlaying, setIsPlaying] = useState(false);

  const atOverview = currentStep === -1;
  const atLast     = currentStep === totalSteps - 1;

  // ── Navigation ─────────────────────────────────────────────────────────────

  const goPrev = () => {
    setIsPlaying(false);
    if (atOverview) return;
    if (currentStep === 0) onStepChange(-1);
    else onStepChange(currentStep - 1);
  };

  const goNext = () => {
    if (!atOverview && atLast) return;
    onStepChange(atOverview ? 0 : currentStep + 1);
  };

  const togglePlay = () => {
    if (atLast) {
      // Restart from step 0 then play
      onStepChange(0);
      setIsPlaying(true);
      return;
    }
    // If at overview, jump to step 0 first
    if (atOverview) onStepChange(0);
    setIsPlaying(p => !p);
  };

  // ── Autoplay ticker ────────────────────────────────────────────────────────
  // Re-fires on every step change so the closure is always fresh.

  useEffect(() => {
    if (!isPlaying) return;
    if (atLast) { setIsPlaying(false); return; }

    const id = setTimeout(() => {
      onStepChange(atOverview ? 0 : currentStep + 1);
    }, 1800);
    return () => clearTimeout(id);
  }, [isPlaying, currentStep, atOverview, atLast, onStepChange]);

  // ── Derived labels ─────────────────────────────────────────────────────────

  const stepLabel = atOverview
    ? `${totalSteps} step${totalSteps !== 1 ? 's' : ''}`
    : `Step ${currentStep + 1} of ${totalSteps}`;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={barStyle}>
      {/* Controls row */}
      <div style={rowStyle}>

        {/* ◀ Back */}
        <IconButton
          onClick={goPrev}
          disabled={atOverview}
          label="Previous step"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <polygon points="10,0 0,5 10,10" />
          </svg>
        </IconButton>

        {/* ▶ / ⏸ Play-Pause */}
        <button
          onClick={togglePlay}
          aria-label={isPlaying ? 'Pause' : 'Play'}
          style={playButtonStyle(isPlaying)}
        >
          {isPlaying
            ? /* pause bars */
              <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor">
                <rect x="0" y="0" width="3.5" height="12" rx="1" />
                <rect x="6.5" y="0" width="3.5" height="12" rx="1" />
              </svg>
            : /* play triangle */
              <svg width="10" height="11" viewBox="0 0 10 11" fill="currentColor">
                <polygon points="0,0 10,5.5 0,11" />
              </svg>
          }
        </button>

        {/* ▶▶ Next */}
        <IconButton
          onClick={goNext}
          disabled={!atOverview && atLast}
          label="Next step"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <polygon points="0,0 10,5 0,10" />
          </svg>
        </IconButton>

        {/* Dot progress scrubber */}
        <div style={dotsRowStyle}>
          {totalSteps <= 12
            ? Array.from({ length: totalSteps }, (_, i) => (
                <button
                  key={i}
                  onClick={() => { setIsPlaying(false); onStepChange(i); }}
                  aria-label={`Go to step ${i + 1}`}
                  style={dotStyle(i === currentStep, i < currentStep)}
                />
              ))
            : <span style={counterStyle}>{stepLabel}</span>
          }
        </div>

        {/* Step label (hidden if dots show the count already) */}
        {totalSteps <= 12 && (
          <span style={stepLabelStyle}>{stepLabel}</span>
        )}

        {/* ✕ Exit */}
        <button
          onClick={onDismiss}
          aria-label="Exit walkthrough"
          title="Exit walkthrough"
          style={exitButtonStyle}
        >
          ✕
        </button>
      </div>

      {/* Step description */}
      {stepDescription && !atOverview && (
        <div style={descStyle}>{stepDescription}</div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function IconButton({
  onClick, disabled, label, children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      style={{
        display:         'flex',
        alignItems:      'center',
        justifyContent:  'center',
        width:           26,
        height:          26,
        background:      'transparent',
        border:          '1px solid rgba(255,255,255,0.1)',
        borderRadius:    6,
        color:           disabled ? 'rgba(139,148,158,0.3)' : '#8b949e',
        cursor:          disabled ? 'default' : 'pointer',
        padding:         0,
        flexShrink:      0,
        transition:      'color 0.12s, border-color 0.12s, background 0.12s',
      }}
      onMouseEnter={e => {
        if (!disabled) {
          e.currentTarget.style.color = '#e6edf3';
          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.22)';
          e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
        }
      }}
      onMouseLeave={e => {
        e.currentTarget.style.color = disabled ? 'rgba(139,148,158,0.3)' : '#8b949e';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)';
        e.currentTarget.style.background = 'transparent';
      }}
    >
      {children}
    </button>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const barStyle: CSSProperties = {
  padding:             '0.55rem 1rem',
  borderTop:           '1px solid rgba(255,255,255,0.06)',
  background:          'rgba(10,13,19,0.88)',
  backdropFilter:      'blur(24px) saturate(160%)',
  WebkitBackdropFilter:'blur(24px) saturate(160%)',
  flexShrink:          0,
};

const rowStyle: CSSProperties = {
  display:    'flex',
  alignItems: 'center',
  gap:        '0.5rem',
};

function playButtonStyle(playing: boolean): CSSProperties {
  return {
    display:             'flex',
    alignItems:          'center',
    justifyContent:      'center',
    width:               32,
    height:              32,
    background:          playing ? 'rgba(167,139,250,0.18)' : 'rgba(167,139,250,0.1)',
    border:              `1px solid ${playing ? 'rgba(167,139,250,0.5)' : 'rgba(167,139,250,0.25)'}`,
    borderRadius:        8,
    color:               '#a78bfa',
    cursor:              'pointer',
    padding:             0,
    flexShrink:          0,
    boxShadow:           playing ? '0 0 10px rgba(167,139,250,0.2)' : 'none',
    transition:          'background 0.15s, border-color 0.15s, box-shadow 0.15s',
  };
}

const dotsRowStyle: CSSProperties = {
  display:    'flex',
  alignItems: 'center',
  gap:        '5px',
  flex:       1,
  justifyContent: 'center',
};

function dotStyle(active: boolean, past: boolean): CSSProperties {
  return {
    width:        active ? 8 : 6,
    height:       active ? 8 : 6,
    borderRadius: '50%',
    background:   active
                    ? '#a78bfa'
                    : past
                    ? 'rgba(167,139,250,0.45)'
                    : 'rgba(139,148,158,0.25)',
    border:       'none',
    padding:      0,
    cursor:       'pointer',
    flexShrink:   0,
    transition:   'background 0.15s, width 0.15s, height 0.15s',
  };
}

const counterStyle: CSSProperties = {
  fontSize:   '0.7rem',
  color:      '#6e7681',
  whiteSpace: 'nowrap',
};

const stepLabelStyle: CSSProperties = {
  fontSize:   '0.7rem',
  color:      '#6e7681',
  whiteSpace: 'nowrap',
  minWidth:   '5rem',
  textAlign:  'right',
};

const exitButtonStyle: CSSProperties = {
  display:         'flex',
  alignItems:      'center',
  justifyContent:  'center',
  width:           24,
  height:          24,
  background:      'transparent',
  border:          'none',
  borderRadius:    5,
  color:           'rgba(139,148,158,0.5)',
  cursor:          'pointer',
  fontSize:        '0.7rem',
  padding:         0,
  flexShrink:      0,
  transition:      'color 0.12s, background 0.12s',
  marginLeft:      '0.25rem',
};

const descStyle: CSSProperties = {
  fontSize:    '0.7rem',
  color:       '#8b949e',
  marginTop:   '0.35rem',
  paddingLeft: '0.5rem',
  borderLeft:  '2px solid rgba(167,139,250,0.3)',
  lineHeight:  1.4,
};
