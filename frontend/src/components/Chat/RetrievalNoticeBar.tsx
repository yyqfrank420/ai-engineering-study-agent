import type { GraphNotice, RetrievalNotice } from '../../types';

interface RetrievalNoticeBarProps {
  notice: RetrievalNotice | GraphNotice | null;
  onUseSearchTool?: () => void;
}

export function RetrievalNoticeBar({ notice, onUseSearchTool }: RetrievalNoticeBarProps) {
  if (!notice) return null;
  const isSearchNotice = 'requestId' in notice;

  return (
    <div style={{
      padding: '0.55rem 1rem',
      borderTop: '1px solid rgba(255,255,255,0.05)',
      background: isSearchNotice ? 'rgba(217,119,6,0.08)' : 'rgba(96,165,250,0.08)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '0.75rem',
      flexWrap: 'wrap',
    }}>
      <div style={{
        fontSize: '0.74rem',
        color: isSearchNotice ? '#d4b078' : '#a9c7f7',
        lineHeight: 1.5,
        maxWidth: '44rem',
      }}>
        {notice.message}
      </div>

      {isSearchNotice && onUseSearchTool ? (
        <button
          onClick={onUseSearchTool}
          disabled={notice.requested}
          style={{
            border: '1px solid rgba(217,119,6,0.35)',
            background: notice.requested ? 'rgba(217,119,6,0.08)' : 'rgba(217,119,6,0.16)',
            color: notice.requested ? '#9f7a45' : '#f0c27a',
            borderRadius: '999px',
            padding: '0.34rem 0.85rem',
            fontSize: '0.7rem',
            cursor: notice.requested ? 'default' : 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {notice.requested ? 'Using search tool…' : 'Use search tool'}
        </button>
      ) : null}
    </div>
  );
}
