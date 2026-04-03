// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/ChatInput.tsx
// Purpose: Text input + send/stop button at the bottom of the chat pane.
//          A small "+" button to the left of the textarea opens a floating
//          popover (ChatGPT-style) for choosing per-message settings:
//            • Complexity: auto | low | proto | prod
//            • Graph mode: auto | on | off
//            • Research:   toggle
//          The "+" button shows a violet dot when any setting differs from
//          its default.  Enter submits, Shift+Enter inserts a newline.
// Language: TypeScript / React
// Connects to: App.tsx (mode state lifted up), types/index.ts
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { ComplexityLevel, GraphMode } from '../../types';

interface ChatInputProps {
  onSend:        (content: string) => void;
  onStop:        () => void;
  onPrepare?:    () => void | Promise<void>;
  disabled?:     boolean;   // locks textarea (loading, no thread)
  sendDisabled?: boolean;   // blocks send while backend is not ready
  showPrepare?:  boolean;
  prepareDisabled?: boolean;
  isGenerating?: boolean;   // LLM actively streaming — show Stop instead of Send
  prepareMessage?: string | null; // non-null while backend is warming up or failed
  // Mode control state — passed from App.tsx
  complexity:         ComplexityLevel;
  graphMode:          GraphMode;
  researchEnabled:    boolean;
  onComplexityChange: (v: ComplexityLevel) => void;
  onGraphModeChange:  (v: GraphMode) => void;
  onResearchChange:   (v: boolean) => void;
  selectionSuggestion?: string | null;
  selectionReferenceActive?: boolean;
  onUseSelection?: () => void;
  onDismissSelection?: () => void;
  onClearSelectionReference?: () => void;
}

// ── Compact segmented row ─────────────────────────────────────────────────────

function SegRow<T extends string>({
  label, options, value, onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  const [hovered, setHovered] = useState<T | null>(null);
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
      <span style={miniLabelStyle}>{label}</span>
      <div style={segContainerStyle}>
        {options.map((opt, i) => (
          <span key={opt.value} style={{ display: 'flex', alignItems: 'stretch', flex: 1 }}>
            {i > 0 && <span style={thinDivStyle} />}
            <span
              onClick={() => onChange(opt.value)}
              onMouseEnter={() => setHovered(opt.value)}
              onMouseLeave={() => setHovered(null)}
              style={{
                flex:       1,
                textAlign:  'center',
                padding:    '3px 4px',
                fontSize:   '0.68rem',
                fontWeight: opt.value === value ? 600 : 400,
                color:      opt.value === value
                  ? '#a78bfa'
                  : hovered === opt.value
                  ? '#c9d1d9'
                  : '#6e7681',
                background: opt.value === value
                  ? 'rgba(167,139,250,0.14)'
                  : hovered === opt.value
                  ? 'rgba(255,255,255,0.05)'
                  : 'transparent',
                cursor:     opt.value === value ? 'default' : 'pointer',
                userSelect: 'none',
                transition: 'background 0.1s, color 0.1s',
                whiteSpace: 'nowrap',
                lineHeight: '1.6',
              }}
            >
              {opt.label}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Mode popover content ──────────────────────────────────────────────────────

interface PopoverProps {
  complexity:         ComplexityLevel;
  graphMode:          GraphMode;
  researchEnabled:    boolean;
  onComplexityChange: (v: ComplexityLevel) => void;
  onGraphModeChange:  (v: GraphMode) => void;
  onResearchChange:   (v: boolean) => void;
}

function ModePopover({
  complexity, graphMode, researchEnabled,
  onComplexityChange, onGraphModeChange, onResearchChange,
}: PopoverProps) {
  return (
    <div style={popoverStyle}>
      <SegRow
        label="COMPLEXITY"
        options={[
          { value: 'auto' as ComplexityLevel,       label: 'auto'  },
          { value: 'low' as ComplexityLevel,        label: 'low'   },
          { value: 'prototype' as ComplexityLevel,  label: 'proto' },
          { value: 'production' as ComplexityLevel, label: 'prod'  },
        ]}
        value={complexity}
        onChange={onComplexityChange}
      />

      <div style={popoverDivStyle} />

      <SegRow
        label="GRAPH"
        options={[
          { value: 'auto' as GraphMode, label: 'auto' },
          { value: 'on'   as GraphMode, label: 'on'   },
          { value: 'off'  as GraphMode, label: 'off'  },
        ]}
        value={graphMode}
        onChange={onGraphModeChange}
      />

      <div style={popoverDivStyle} />

      {/* Research toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span style={miniLabelStyle}>RESEARCH</span>
          <div style={{ fontSize: '0.62rem', color: '#3d444d', marginTop: '1px' }}>
            Augment with Web Search
          </div>
        </div>
        <div
          onClick={() => onResearchChange(!researchEnabled)}
          style={{
            width:        '32px',
            height:       '18px',
            borderRadius: '9px',
            background:   researchEnabled ? 'rgba(124,58,237,0.8)' : 'rgba(255,255,255,0.08)',
            border:       `1px solid ${researchEnabled ? 'rgba(167,139,250,0.4)' : 'rgba(255,255,255,0.1)'}`,
            position:     'relative',
            cursor:       'pointer',
            transition:   'background 0.2s, border-color 0.2s',
            flexShrink:   0,
          }}
        >
          <div style={{
            position:     'absolute',
            top:          '2px',
            left:         researchEnabled ? '15px' : '2px',
            width:        '12px',
            height:       '12px',
            borderRadius: '50%',
            background:   researchEnabled ? '#fff' : 'rgba(255,255,255,0.4)',
            transition:   'left 0.2s ease, background 0.2s',
            boxShadow:    '0 1px 3px rgba(0,0,0,0.4)',
          }} />
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ChatInput({
  onSend, onStop, onPrepare, disabled, isGenerating,
  sendDisabled, showPrepare, prepareDisabled, prepareMessage,
  complexity, graphMode, researchEnabled,
  onComplexityChange, onGraphModeChange, onResearchChange,
  selectionSuggestion, selectionReferenceActive, onUseSelection, onDismissSelection, onClearSelectionReference,
}: ChatInputProps) {
  const [value, setValue]         = useState('');
  const [popoverOpen, setPopover] = useState(false);
  const [containerHovered, setContainerHovered] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popoverRef  = useRef<HTMLDivElement>(null);
  const triggerRef  = useRef<HTMLButtonElement>(null);

  // Has non-default settings
  const hasActiveSettings =
    complexity !== 'auto' || graphMode !== 'auto' || researchEnabled;

  const resizeTextarea = useCallback((element: HTMLTextAreaElement) => {
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 120)}px`;
  }, []);

  const seedSelection = useCallback(() => {
    if (!selectionSuggestion) return;
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
    onUseSelection?.();
  }, [onUseSelection, selectionSuggestion]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || sendDisabled) return;
    // Clear immediately on submit — don't wait for disabled cycle
    setValue('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onSend(trimmed);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  const onInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (selectionSuggestion && !selectionReferenceActive && e.target.value.trim() !== '') {
      onUseSelection?.();
    }
    setValue(e.target.value);
    resizeTextarea(e.target);
  };

  // Close popover on outside click
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (
      popoverRef.current && !popoverRef.current.contains(e.target as Node) &&
      triggerRef.current && !triggerRef.current.contains(e.target as Node)
    ) {
      setPopover(false);
    }
  }, []);

  useEffect(() => {
    if (popoverOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
    }
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [popoverOpen, handleOutsideClick]);

  const isReady = !disabled && !sendDisabled && !!value.trim();
  const placeholder = (selectionReferenceActive || !!selectionSuggestion)
    ? 'Ask a question about the highlighted text…'
    : 'Ask a question…';

  return (
    <div style={{
      padding:             '0.75rem 1rem',
      background:          'rgba(10,13,19,0.65)',
      backdropFilter:      'blur(40px) saturate(160%)',
      WebkitBackdropFilter:'blur(40px) saturate(160%)',
      borderTop:           '1px solid rgba(255,255,255,0.06)',
      boxShadow:           'inset 0 1px 0 rgba(255,255,255,0.04)',
      flexShrink:          0,
      position:            'relative',
    }}
    onMouseEnter={() => setContainerHovered(true)}
    onMouseLeave={() => setContainerHovered(false)}
    >
      {selectionSuggestion && (
        <div
          style={selectionSuggestionStyle(containerHovered, !!selectionReferenceActive)}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.7rem' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '0.64rem', color: '#a78bfa', fontWeight: 700, letterSpacing: '0.05em' }}>
                {selectionReferenceActive ? 'REFERENCE ACTIVE' : 'HIGHLIGHTED TEXT'}
              </div>
              <div style={{
                fontSize: '0.7rem',
                color: '#c9d1d9',
                lineHeight: 1.45,
                marginTop: '0.18rem',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '28rem',
              }}>
                {selectionSuggestion}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexShrink: 0 }}>
              <button
                onClick={seedSelection}
                style={selectionActionButtonStyle}
              >
                {selectionReferenceActive ? 'Referenced' : 'Use in chat'}
              </button>
              <button
                onClick={onDismissSelection}
                aria-label="Dismiss highlighted text"
                style={selectionDismissButtonStyle}
              >
                ×
              </button>
            </div>
          </div>
        </div>
      )}

      {prepareMessage && (
        <div style={prepareNoticeStyle}>
          {prepareMessage}
        </div>
      )}

      {/* Floating mode popover — anchored above the "+" button */}
      {popoverOpen && (
        <div ref={popoverRef} style={popoverAnchorStyle}>
          <ModePopover
            complexity={complexity}
            graphMode={graphMode}
            researchEnabled={researchEnabled}
            onComplexityChange={onComplexityChange}
            onGraphModeChange={onGraphModeChange}
            onResearchChange={onResearchChange}
          />
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.5rem' }}>
        {/* "+" trigger button */}
        <button
          ref={triggerRef}
          onClick={() => setPopover(p => !p)}
          aria-label="Message options"
          style={triggerButtonStyle(popoverOpen)}
        >
          {/* + icon */}
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <line x1="7" y1="1" x2="7" y2="13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <line x1="1" y1="7" x2="13" y2="7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {/* Active indicator dot */}
          {hasActiveSettings && !popoverOpen && (
            <span style={{
              position:     'absolute',
              top:          '3px',
              right:        '3px',
              width:        '5px',
              height:       '5px',
              borderRadius: '50%',
              background:   '#a78bfa',
            }} />
          )}
        </button>

        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={onInput}
          onKeyDown={onKeyDown}
          onClick={() => {
            if (selectionReferenceActive && !value.trim()) {
              onClearSelectionReference?.();
            }
          }}
          onFocus={() => {
            if (selectionReferenceActive && !value.trim()) {
              onClearSelectionReference?.();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          style={textareaStyle}
          onFocusCapture={e => {
            setContainerHovered(true);
            e.currentTarget.style.borderColor = 'rgba(167,139,250,0.5)';
            e.currentTarget.style.boxShadow   = '0 0 0 3px rgba(167,139,250,0.12), inset 0 1px 0 rgba(255,255,255,0.06)';
          }}
          onBlur={e => {
            setContainerHovered(false);
            e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
            e.currentTarget.style.boxShadow   = 'inset 0 1px 0 rgba(255,255,255,0.04)';
          }}
        />

        {/* Send / Stop — Stop only when LLM is actively generating */}
        {isGenerating ? (
          <button
            onClick={onStop}
            aria-label="Stop generation"
            style={stopButtonStyle}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(248, 81, 73, 0.2)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(248, 81, 73, 0.1)'; }}
          >
            Stop
          </button>
        ) : showPrepare ? (
          <button
            onClick={() => void onPrepare?.()}
            disabled={prepareDisabled}
            aria-label="Prepare backend"
            style={sendButtonStyle(!prepareDisabled, 'Prepare')}
          >
            {prepareMessage && !prepareMessage.toLowerCase().includes('unavailable')
              ? 'Preparing…'
              : 'Prepare'}
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!isReady}
            aria-label="Send message"
            style={sendButtonStyle(isReady, 'Send')}
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const popoverAnchorStyle: CSSProperties = {
  position:     'absolute',
  bottom:       'calc(100% + 6px)',
  left:         '1rem',
  zIndex:       100,
};

const selectionSuggestionStyle = (hovered: boolean, active: boolean): CSSProperties => ({
  background: 'rgba(10,13,19,0.82)',
  border: active ? '1px solid rgba(167,139,250,0.35)' : '1px solid rgba(167,139,250,0.22)',
  borderRadius: '12px',
  padding: '0.65rem 0.8rem',
  backdropFilter: 'blur(18px)',
  WebkitBackdropFilter: 'blur(18px)',
  boxShadow: '0 12px 32px rgba(0,0,0,0.42)',
  opacity: hovered ? 1 : 0.66,
  transition: 'opacity 0.15s ease',
  marginBottom: '0.65rem',
});

const selectionActionButtonStyle: CSSProperties = {
  border: '1px solid rgba(167,139,250,0.3)',
  background: 'rgba(167,139,250,0.12)',
  color: '#d9c9ff',
  borderRadius: '999px',
  padding: '0.32rem 0.72rem',
  fontSize: '0.68rem',
  cursor: 'pointer',
};

const selectionDismissButtonStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#6e7681',
  fontSize: '1rem',
  lineHeight: 1,
  cursor: 'pointer',
  padding: '0.1rem',
};

const prepareNoticeStyle: CSSProperties = {
  marginBottom: '0.65rem',
  padding: '0.55rem 0.8rem',
  borderRadius: '10px',
  border: '1px solid rgba(96,165,250,0.18)',
  background: 'rgba(37,99,235,0.08)',
  color: '#c9d1d9',
  fontSize: '0.72rem',
  lineHeight: 1.45,
};

const popoverStyle: CSSProperties = {
  width:                '272px',
  background:           'rgba(18,22,30,0.97)',
  backdropFilter:       'blur(48px) saturate(200%)',
  WebkitBackdropFilter: 'blur(48px) saturate(200%)',
  border:               '1px solid rgba(255,255,255,0.1)',
  borderRadius:         '14px',
  padding:              '0.75rem',
  boxShadow:            [
    'inset 0 1px 0 rgba(255,255,255,0.12)',
    'inset 0 -1px 0 rgba(0,0,0,0.2)',
    '0 16px 48px rgba(0,0,0,0.6)',
    '0 0 0 1px rgba(167,139,250,0.08)',
  ].join(', '),
  display:              'flex',
  flexDirection:        'column',
  gap:                  '0.6rem',
};

const miniLabelStyle: CSSProperties = {
  fontSize:      '0.6rem',
  fontWeight:    600,
  color:         '#484f58',
  letterSpacing: '0.07em',
  flexShrink:    0,
  userSelect:    'none',
  width:         '72px',   // fixed so all controls left-align
};

const segContainerStyle: CSSProperties = {
  display:      'flex',
  alignItems:   'stretch',
  flex:         1,           // fills remaining width after fixed label
  border:       '1px solid rgba(255,255,255,0.08)',
  borderRadius: '5px',
  overflow:     'hidden',
  background:   'rgba(255,255,255,0.02)',
};

const popoverDivStyle: CSSProperties = {
  height:     '1px',
  background: 'rgba(255,255,255,0.05)',
};

const thinDivStyle: CSSProperties = {
  width:      '1px',
  alignSelf:  'stretch',
  background: 'rgba(255,255,255,0.07)',
  flexShrink: 0,
};

function triggerButtonStyle(open: boolean): CSSProperties {
  return {
    position:             'relative',
    width:                '34px',
    height:               '34px',
    borderRadius:         '10px',
    border:               `1px solid ${open ? 'rgba(167,139,250,0.35)' : 'rgba(255,255,255,0.08)'}`,
    background:           open ? 'rgba(167,139,250,0.12)' : 'rgba(255,255,255,0.04)',
    backdropFilter:       'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    boxShadow:            open
      ? 'inset 0 1px 0 rgba(167,139,250,0.15)'
      : 'inset 0 1px 0 rgba(255,255,255,0.06)',
    color:                open ? '#a78bfa' : '#8b949e',
    display:              'flex',
    alignItems:           'center',
    justifyContent:       'center',
    cursor:               'pointer',
    flexShrink:           0,
    transition:           'background 0.15s, border-color 0.15s, color 0.15s, box-shadow 0.15s',
  };
}

const textareaStyle: CSSProperties = {
  flex:                1,
  resize:              'none',
  background:          'rgba(255,255,255,0.04)',
  backdropFilter:      'blur(8px)',
  WebkitBackdropFilter:'blur(8px)',
  border:              '1px solid rgba(255,255,255,0.08)',
  borderRadius:        '10px',
  padding:             '0.5rem 0.75rem',
  color:               '#e6edf3',
  fontSize:            '0.875rem',
  lineHeight:          1.5,
  outline:             'none',
  fontFamily:          'inherit',
  minHeight:           '38px',
  maxHeight:           '120px',
  overflow:            'auto',
  transition:          'border-color 0.15s, box-shadow 0.15s',
  boxShadow:           'inset 0 1px 0 rgba(255,255,255,0.04)',
};

const stopButtonStyle: CSSProperties = {
  padding:              '0.5rem 1rem',
  borderRadius:         '10px',
  background:           'rgba(248,81,73,0.08)',
  backdropFilter:       'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  color:                '#f85149',
  border:               '1px solid rgba(248,81,73,0.25)',
  boxShadow:            'inset 0 1px 0 rgba(255,255,255,0.04)',
  cursor:               'pointer',
  fontSize:             '0.875rem',
  fontWeight:           500,
  whiteSpace:           'nowrap',
  minHeight:            '38px',
  transition:           'background 0.15s',
};

function sendButtonStyle(isReady: boolean, variant: 'Send' | 'Prepare'): CSSProperties {
  const isPrepare = variant === 'Prepare';
  return {
    padding:              '0.5rem 1rem',
    borderRadius:         '10px',
    background:           isReady
      ? isPrepare
        ? 'linear-gradient(135deg, rgba(37,99,235,0.9), rgba(14,165,233,0.88))'
        : 'linear-gradient(135deg, rgba(124,58,237,0.9), rgba(59,130,246,0.9))'
      : 'rgba(255,255,255,0.04)',
    backdropFilter:       'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    boxShadow:            isReady
      ? isPrepare
        ? 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(37,99,235,0.25)'
        : 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(124,58,237,0.25)'
      : 'inset 0 1px 0 rgba(255,255,255,0.04)',
    color:                isReady ? '#fff' : '#6e7681',
    border:               isReady
      ? isPrepare
        ? '1px solid rgba(96,165,250,0.3)'
        : '1px solid rgba(167,139,250,0.3)'
      : '1px solid rgba(255,255,255,0.06)',
    cursor:               isReady ? 'pointer' : 'not-allowed',
    fontSize:             '0.875rem',
    fontWeight:           500,
    transition:           'opacity 0.15s, box-shadow 0.15s',
    whiteSpace:           'nowrap',
    minHeight:            '38px',
    opacity:              isReady ? 1 : 0.5,
  };
}
