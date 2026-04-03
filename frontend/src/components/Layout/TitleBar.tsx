// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Layout/TitleBar.tsx
// Purpose: App header — shows the book badge, connection status, and an optional
//          provider fallback notice (shown when Claude is unavailable and the
//          request is being served by the OpenAI GPT fallback).
// ─────────────────────────────────────────────────────────────────────────────

import type { CSSProperties } from 'react';

interface TitleBarProps {
  streamStatus: 'generating' | 'connected' | 'disconnected';
  providerNotice: string | null;
  userEmail: string;
  threadTitle: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onLogout: () => void;
}

const STATUS_COLORS = {
  connected:    '#3fb950',
  generating:   '#a78bfa',
  disconnected: '#f85149',
};

const STATUS_GLOWS = {
  connected:    '#3fb95066',
  generating:   '#a78bfa66',
  disconnected: '#f8514966',
};

export function TitleBar({
  streamStatus,
  providerNotice,
  userEmail,
  threadTitle,
  sidebarOpen,
  onToggleSidebar,
  onLogout,
}: TitleBarProps) {
  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 1.25rem',
      height: '48px',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      background: 'rgba(10,13,19,0.7)',
      backdropFilter: 'blur(40px) saturate(180%)',
      WebkitBackdropFilter: 'blur(40px) saturate(180%)',
      boxShadow: 'inset 0 -1px 0 rgba(255,255,255,0.04), 0 1px 0 rgba(0,0,0,0.4)',
      flexShrink: 0,
      position: 'relative',
      zIndex: 10,
      }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={onToggleSidebar}
          style={sidebarToggleStyle}
          aria-label={sidebarOpen ? 'Hide chat history' : 'Show chat history'}
          title={sidebarOpen ? 'Hide chat history' : 'Show chat history'}
        >
          {sidebarOpen ? '◧' : '☰'}
        </button>
        {/* Gradient title text */}
        <span style={{
          fontSize: '0.9375rem',
          fontWeight: 600,
          background: 'linear-gradient(90deg, #a78bfa, #60a5fa)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          letterSpacing: '0.01em',
        }}>
          AI Engineering
        </span>
        {/* Violet-tinted badge */}
        <span style={{
          fontSize: '0.7rem',
          padding: '2px 8px',
          borderRadius: '999px',
          background: 'rgba(167, 139, 250, 0.1)',
          border: '1px solid rgba(167, 139, 250, 0.2)',
          color: '#a78bfa',
          fontWeight: 500,
          letterSpacing: '0.03em',
        }}>
          Chip Huyen · O'Reilly
        </span>
        <span style={{ fontSize: '0.75rem', color: '#8b949e' }}>
          {threadTitle}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {providerNotice && (
          <span style={{
            fontSize: '0.7rem',
            padding: '2px 8px',
            borderRadius: '999px',
            background: 'rgba(167, 139, 250, 0.1)',
            border: '1px solid rgba(167, 139, 250, 0.2)',
            color: '#a78bfa',
            fontWeight: 500,
          }}>
            {providerNotice}
          </span>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {/* Glowing status dot — pulses violet when generating */}
          <div style={{
            width: 7, height: 7,
            borderRadius: '50%',
            background: STATUS_COLORS[streamStatus],
            boxShadow: `0 0 6px ${STATUS_GLOWS[streamStatus]}`,
            animation: streamStatus === 'generating' ? 'pulse 1.5s ease-in-out infinite' : undefined,
          }} />
          <span style={{ fontSize: '0.7rem', color: '#6e7681' }}>
            {streamStatus}
          </span>
        </div>
        <span style={{ fontSize: '0.75rem', color: '#8b949e' }}>
          {userEmail}
        </span>
        <button onClick={onLogout} style={buttonStyle}>
          Sign out
        </button>
      </div>
    </header>
  );
}

const buttonStyle: CSSProperties = {
  border: '1px solid rgba(255,255,255,0.1)',
  background: 'rgba(255,255,255,0.05)',
  color: '#c9d1d9',
  borderRadius: '999px',
  padding: '4px 10px',
  fontSize: '0.75rem',
  cursor: 'pointer',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  transition: 'background 0.15s, border-color 0.15s',
};

const sidebarToggleStyle: CSSProperties = {
  ...buttonStyle,
  width: '34px',
  height: '34px',
  padding: 0,
  display: 'grid',
  placeItems: 'center',
  fontSize: '0.95rem',
  color: '#dbe4ee',
};
