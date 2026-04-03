// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Layout/ThreadSidebar.tsx
// Purpose: Left-rail chat history sidebar. Shows all threads grouped by
//          recency. Clicking a thread switches to it. Hovering reveals a
//          trash icon that opens a liquid-glass delete confirmation popup.
// Language: TypeScript / React
// Connects to: services/api.ts (listThreads, deleteThread), App.tsx (callbacks)
// Inputs:  authSession, activeThreadId, onNewChat, onSelectThread,
//          onDeleteThread, isLoading, isOpen
// Outputs: visual sidebar; user interactions call parent callbacks
// ─────────────────────────────────────────────────────────────────────────────

import { createPortal } from 'react-dom';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { AuthSession, ThreadSummary } from '../../types';
import { listThreads, deleteThread } from '../../services/api';

interface ThreadSidebarProps {
  authSession:     AuthSession | null;
  activeThreadId:  string | null;
  backendReady:    boolean;
  onNewChat:       () => void;
  onSelectThread:  (threadId: string) => void;
  onDeleteThread:  (threadId: string) => void;
  isLoading:       boolean;
  isOpen:          boolean;
}

// Must match settings.max_threads_per_user in backend/config.py
const MAX_THREADS = 5;

// ── Date grouping helpers ─────────────────────────────────────────────────────

type Group = 'Today' | 'Yesterday' | 'This week' | 'Older';

function getGroup(dateStr: string): Group {
  const now  = new Date();
  const date = new Date(dateStr);

  const diffMs   = now.getTime() - date.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  const todayStart     = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400 * 1000);

  if (date >= todayStart)     return 'Today';
  if (date >= yesterdayStart) return 'Yesterday';
  if (diffDays < 7)           return 'This week';
  return 'Older';
}

function groupThreads(threads: ThreadSummary[]): { label: Group; items: ThreadSummary[] }[] {
  const groups: Record<Group, ThreadSummary[]> = {
    Today:      [],
    Yesterday:  [],
    'This week': [],
    Older:      [],
  };
  for (const t of threads) {
    groups[getGroup(t.last_seen_at)].push(t);
  }
  const order: Group[] = ['Today', 'Yesterday', 'This week', 'Older'];
  return order
    .filter(g => groups[g].length > 0)
    .map(g => ({ label: g, items: groups[g] }));
}

// ── DeletePopup ───────────────────────────────────────────────────────────────
// Rendered via React portal at document.body so it escapes sidebar's
// overflow:hidden and can appear to the right of the sidebar at any viewport pos.

interface DeletePopupProps {
  onConfirm: () => void;
  onClose:   () => void;
  // Viewport-space anchor: right edge x, vertical center y of the trash button
  anchor:    { x: number; y: number };
}

function DeletePopup({ onConfirm, onClose, anchor }: DeletePopupProps) {
  const popupRef = useRef<HTMLDivElement>(null);

  // Close on outside click (anywhere outside this popup)
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  const style: CSSProperties = {
    ...portalPopupStyle,
    // position: fixed so it sits relative to the viewport, not any parent
    position:  'fixed',
    left:      anchor.x + 8,
    top:       anchor.y,
    transform: 'translateY(-50%)',
  };

  return createPortal(
    <div ref={popupRef} style={style}>
      <span style={popupTextStyle}>Permanently delete this chat?</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.55rem' }}>
        <button onClick={onConfirm} style={confirmButtonStyle}>Yes</button>
        <button onClick={onClose}   style={closeButtonStyle}>✕</button>
      </div>
    </div>,
    document.body,
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ThreadSidebar({
  authSession,
  activeThreadId,
  backendReady,
  onNewChat,
  onSelectThread,
  onDeleteThread,
  isLoading,
  isOpen,
}: ThreadSidebarProps) {
  const [threads, setThreads]           = useState<ThreadSummary[]>([]);
  const [fetching, setFetching]         = useState(false);
  const [hoveredId, setHoveredId]       = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  // Viewport coords of the trash button that opened the popup
  const [popupAnchor, setPopupAnchor]   = useState<{ x: number; y: number } | null>(null);

  const fetchThreads = useCallback(async () => {
    if (!authSession || !backendReady) return;
    setFetching(true);
    try {
      const list = await listThreads(authSession);
      setThreads(list);
    } catch {
      // Non-fatal — sidebar just stays empty
    } finally {
      setFetching(false);
    }
  }, [authSession, backendReady]);

  // Re-fetch whenever the active thread changes (new chat created, thread switched)
  useEffect(() => {
    fetchThreads();
  }, [fetchThreads, activeThreadId]);

  const handleDelete = useCallback(async (threadId: string) => {
    if (!authSession) return;
    setConfirmingId(null);
    setPopupAnchor(null);
    try {
      await deleteThread(authSession, threadId);
      setThreads(prev => prev.filter(t => t.id !== threadId));
      onDeleteThread(threadId);
    } catch {
      // Non-fatal — thread stays in list
    }
  }, [authSession, onDeleteThread]);

  const closePopup = useCallback(() => {
    setConfirmingId(null);
    setPopupAnchor(null);
  }, []);

  const grouped = groupThreads(threads);

  return (
    <div style={sidebarStyle(isOpen)}>
      <div style={sidebarInnerStyle(isOpen)}>
        {/* New chat button — disabled at thread limit */}
        <button
          onClick={onNewChat}
          disabled={isLoading || !authSession || !backendReady || threads.length >= MAX_THREADS}
          style={newChatButtonStyle(isLoading || !authSession || !backendReady || threads.length >= MAX_THREADS)}
        >
          <span style={{ fontSize: '1rem', lineHeight: 1 }}>+</span>
          New chat
        </button>
        {threads.length >= MAX_THREADS && (
          <div style={maxThreadsStyle}>Limit reached ({MAX_THREADS} chats)</div>
        )}

        {/* Thread list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0.25rem 0' }}>
          {fetching && threads.length === 0 && (
            <div style={emptyStyle}>Loading…</div>
          )}

          {!fetching && threads.length === 0 && (
            <div style={emptyStyle}>{backendReady ? 'No chats yet' : 'Prepare backend to load chats'}</div>
          )}

          {grouped.map(group => (
            <div key={group.label}>
              <div style={groupLabelStyle}>{group.label}</div>
              {group.items.map(thread => {
                const isActive     = thread.id === activeThreadId;
                const isHovered    = thread.id === hoveredId;
                const isConfirming = thread.id === confirmingId;
                const showControls = isHovered || isConfirming;

                return (
                  <div key={thread.id}>
                    {/* Single flex row */}
                    <div
                      style={threadItemStyle(isActive, showControls)}
                      onMouseEnter={() => setHoveredId(thread.id)}
                      onMouseLeave={() => setHoveredId(null)}
                    >
                      <span
                        onClick={() => backendReady && !isActive && onSelectThread(thread.id)}
                        style={{
                          flex: 1,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          cursor: !backendReady || isActive ? 'default' : 'pointer',
                        }}
                      >
                        {thread.title || 'New chat'}
                      </span>

                      {/* Trash button — inline in flex row, opacity-hidden when not hovered.
                          pointerEvents always 'auto' — prevents mid-hover invisible dead zone. */}
                      <button
                        onClick={e => {
                          e.stopPropagation();
                          if (isConfirming) {
                            closePopup();
                          } else {
                            // Capture viewport position of this button for the portal popup
                            const rect = (e.currentTarget as HTMLButtonElement).getBoundingClientRect();
                            setPopupAnchor({ x: rect.right, y: rect.top + rect.height / 2 });
                            setConfirmingId(thread.id);
                          }
                        }}
                        onMouseEnter={() => setHoveredId(thread.id)}
                        style={trashButtonStyle(isConfirming, showControls)}
                        title="Delete chat"
                      >
                        <svg width="11" height="12" viewBox="0 0 11 12" fill="currentColor">
                          <path d="M1 3h9M4 3V2h3v1M2 3l.7 7.3A.7.7 0 002.7 11h5.6a.7.7 0 00.7-.7L9.7 3" stroke="currentColor" strokeWidth="1" fill="none" strokeLinecap="round"/>
                        </svg>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Portal popup — rendered at document.body, escapes overflow:hidden */}
      {confirmingId && popupAnchor && (
        <DeletePopup
          onConfirm={() => handleDelete(confirmingId)}
          onClose={closePopup}
          anchor={popupAnchor}
        />
      )}
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

function sidebarStyle(isOpen: boolean): CSSProperties {
  return {
    width:               isOpen ? '240px' : '0',
    flexShrink:          0,
    display:             'flex',
    flexDirection:       'column',
    background:          'rgba(10,13,19,0.55)',
    backdropFilter:      'blur(40px) saturate(160%)',
    WebkitBackdropFilter:'blur(40px) saturate(160%)',
    borderRight:         isOpen ? '1px solid rgba(255,255,255,0.06)' : '1px solid transparent',
    boxShadow:           isOpen ? 'inset -1px 0 0 rgba(255,255,255,0.03)' : 'none',
    overflow:            'hidden',
    transition:          'width 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease',
  };
}

function sidebarInnerStyle(isOpen: boolean): CSSProperties {
  return {
    width:         '240px',
    flex:          1,
    display:       'flex',
    flexDirection: 'column',
    opacity:       isOpen ? 1 : 0,
    pointerEvents: isOpen ? 'auto' : 'none',
    transition:    'opacity 0.14s ease',
  };
}

function newChatButtonStyle(disabled: boolean): CSSProperties {
  return {
    display:             'flex',
    alignItems:          'center',
    gap:                 '0.5rem',
    margin:              '0.75rem 0.75rem 0.5rem',
    padding:             '0.55rem 0.85rem',
    background:          disabled ? 'rgba(167,139,250,0.04)' : 'rgba(167,139,250,0.1)',
    border:              '1px solid rgba(167,139,250,0.18)',
    borderRadius:        '8px',
    color:               disabled ? '#6e7681' : '#a78bfa',
    fontSize:            '0.82rem',
    fontWeight:          500,
    cursor:              disabled ? 'not-allowed' : 'pointer',
    backdropFilter:      'blur(12px)',
    WebkitBackdropFilter:'blur(12px)',
    boxShadow:           disabled ? 'none' : 'inset 0 1px 0 rgba(167,139,250,0.08)',
    transition:          'background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease',
    flexShrink:          0,
  };
}

const groupLabelStyle: CSSProperties = {
  padding:        '0.6rem 0.9rem 0.25rem',
  fontSize:       '0.62rem',
  fontWeight:     600,
  color:          '#6e7681',
  textTransform:  'uppercase',
  letterSpacing:  '0.06em',
};

function threadItemStyle(isActive: boolean, isHighlighted: boolean): CSSProperties {
  return {
    display:        'flex',
    alignItems:     'center',
    gap:            '0.25rem',
    padding:        '0.45rem 0.5rem 0.45rem 0.75rem',
    fontSize:       '0.82rem',
    color:          isActive ? '#e6edf3' : '#8b949e',
    borderLeft:     isActive ? '3px solid rgba(167,139,250,0.6)' : '3px solid transparent',
    background:     isActive
                      ? 'rgba(167,139,250,0.06)'
                      : isHighlighted
                      ? 'rgba(255,255,255,0.04)'
                      : 'transparent',
    transition:     'background 0.12s ease, color 0.12s ease',
    lineHeight:     '1.4',
    userSelect:     'none',
  };
}

function trashButtonStyle(active: boolean, visible: boolean): CSSProperties {
  return {
    display:         'flex',
    alignItems:      'center',
    justifyContent:  'center',
    flexShrink:      0,
    width:           20,
    height:          20,
    background:      active ? 'rgba(248,81,73,0.12)' : 'transparent',
    border:          'none',
    borderRadius:    '4px',
    color:           active ? '#f85149' : '#6e7681',
    cursor:          'pointer',
    padding:         0,
    opacity:         visible ? 1 : 0,
    transition:      'opacity 0.1s ease, background 0.12s ease, color 0.12s ease',
  };
}

// Portal popup is position:fixed — coords injected at render time from getBoundingClientRect()
const portalPopupStyle: CSSProperties = {
  zIndex:              1000,
  width:               '200px',
  padding:             '0.65rem 0.8rem',
  background:          'rgba(12,16,23,0.92)',
  backdropFilter:      'blur(24px) saturate(160%)',
  WebkitBackdropFilter:'blur(24px) saturate(160%)',
  border:              '1px solid rgba(255,255,255,0.1)',
  borderRadius:        '10px',
  boxShadow:           '0 8px 32px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.07)',
};

const popupTextStyle: CSSProperties = {
  fontSize:    '0.78rem',
  color:       '#c9d1d9',
  lineHeight:  1.4,
};

const confirmButtonStyle: CSSProperties = {
  flex:                1,
  padding:             '0.3rem 0',
  background:          'rgba(248,81,73,0.15)',
  border:              '1px solid rgba(248,81,73,0.35)',
  borderRadius:        '6px',
  color:               '#f85149',
  fontSize:            '0.76rem',
  fontWeight:          600,
  cursor:              'pointer',
  backdropFilter:      'blur(8px)',
  WebkitBackdropFilter:'blur(8px)',
  boxShadow:           'inset 0 1px 0 rgba(248,81,73,0.1)',
  transition:          'background 0.12s ease',
};

const closeButtonStyle: CSSProperties = {
  padding:     '0.3rem 0.5rem',
  background:  'rgba(255,255,255,0.05)',
  border:      '1px solid rgba(255,255,255,0.1)',
  borderRadius:'6px',
  color:       '#8b949e',
  fontSize:    '0.72rem',
  cursor:      'pointer',
  transition:  'background 0.12s ease',
};

const emptyStyle: CSSProperties = {
  padding:   '1rem 0.9rem',
  fontSize:  '0.78rem',
  color:     '#6e7681',
};

const maxThreadsStyle: CSSProperties = {
  padding:    '0.1rem 0.9rem 0.4rem',
  fontSize:   '0.68rem',
  color:      '#6e7681',
};
