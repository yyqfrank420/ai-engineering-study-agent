// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/Chat/MessageList.tsx
// Purpose: Renders the conversation thread with full markdown support.
//          Uses react-markdown + remark-gfm for headings, bold, italic,
//          lists, tables, and code fences.
//          LaTeX ($...$ inline, $$...$$ block) is rendered via KaTeX.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { InlineMath, BlockMath } from 'react-katex';
import 'katex/dist/katex.min.css';
import type { Message } from '../../types';

interface MessageListProps {
  messages: Message[];
}

// ── LaTeX pre-processor ───────────────────────────────────────────────────────
// react-markdown doesn't handle LaTeX natively. Split the text on $...$ / $$...$$
// boundaries before handing the plain-text portions to ReactMarkdown.

type Segment = { type: 'text'; value: string } | { type: 'inline-math' | 'block-math'; value: string };

function splitLatex(text: string): Segment[] {
  const segments: Segment[] = [];
  const regex = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) segments.push({ type: 'text', value: text.slice(last, m.index) });
    const raw = m[0];
    if (raw.startsWith('$$')) segments.push({ type: 'block-math', value: raw.slice(2, -2).trim() });
    else                       segments.push({ type: 'inline-math', value: raw.slice(1, -1).trim() });
    last = regex.lastIndex;
  }
  if (last < text.length) segments.push({ type: 'text', value: text.slice(last) });
  return segments;
}

// ── Shared markdown component overrides ──────────────────────────────────────
// These inline styles keep the markdown visually consistent with the dark theme.

const mdComponents = {
  // Headings
  h1: ({ children }: any) => (
    <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#e6edf3', margin: '0.75rem 0 0.35rem', borderBottom: '1px solid #21262d', paddingBottom: '0.25rem' }}>{children}</h1>
  ),
  h2: ({ children }: any) => (
    <h2 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#e6edf3', margin: '0.65rem 0 0.3rem' }}>{children}</h2>
  ),
  h3: ({ children }: any) => (
    <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: '#c9d1d9', margin: '0.5rem 0 0.25rem' }}>{children}</h3>
  ),
  // Paragraphs
  p: ({ children }: any) => (
    <p style={{ margin: '0.35rem 0', lineHeight: 1.65 }}>{children}</p>
  ),
  // Bold / italic
  strong: ({ children }: any) => (
    <strong style={{ color: '#e6edf3', fontWeight: 600 }}>{children}</strong>
  ),
  em: ({ children }: any) => (
    <em style={{ color: '#c9d1d9', fontStyle: 'italic' }}>{children}</em>
  ),
  // Unordered + ordered lists
  ul: ({ children }: any) => (
    <ul style={{ margin: '0.35rem 0', paddingLeft: '1.4rem', lineHeight: 1.65 }}>{children}</ul>
  ),
  ol: ({ children }: any) => (
    <ol style={{ margin: '0.35rem 0', paddingLeft: '1.4rem', lineHeight: 1.65 }}>{children}</ol>
  ),
  li: ({ children }: any) => (
    <li style={{ margin: '0.15rem 0' }}>{children}</li>
  ),
  // Inline code
  code: ({ inline, children, className }: any) => {
    if (inline) {
      return (
        <code style={{
          background: '#0d1117',
          border: '1px solid #21262d',
          borderRadius: '4px',
          padding: '1px 5px',
          fontSize: '0.82rem',
          fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
          color: '#a78bfa',
        }}>
          {children}
        </code>
      );
    }
    return (
      <pre style={{
        background: '#0d1117',
        border: '1px solid #21262d',
        borderRadius: '6px',
        padding: '0.75rem 1rem',
        overflowX: 'auto',
        fontSize: '0.82rem',
        lineHeight: 1.6,
        margin: '0.5rem 0',
        fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
      }}>
        <code className={className}>{children}</code>
      </pre>
    );
  },
  // Block quotes
  blockquote: ({ children }: any) => (
    <blockquote style={{
      borderLeft: '3px solid rgba(167,139,250,0.4)',
      paddingLeft: '0.75rem',
      margin: '0.5rem 0',
      color: '#8b949e',
      fontStyle: 'italic',
    }}>
      {children}
    </blockquote>
  ),
  // Tables (GFM)
  table: ({ children }: any) => (
    <div style={{ overflowX: 'auto', margin: '0.5rem 0' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: '0.82rem', width: '100%' }}>{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th style={{ border: '1px solid #30363d', padding: '6px 10px', background: '#161b22', color: '#e6edf3', fontWeight: 600, textAlign: 'left' }}>{children}</th>
  ),
  td: ({ children }: any) => (
    <td style={{ border: '1px solid #21262d', padding: '6px 10px', color: '#8b949e' }}>{children}</td>
  ),
  // Horizontal rule
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid #21262d', margin: '0.75rem 0' }} />,
  // Links
  a: ({ href, children }: any) => (
    <a href={href} style={{ color: '#60a5fa', textDecoration: 'none' }} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
};

// ── Message content renderer ──────────────────────────────────────────────────
// Splits on LaTeX first, then renders each text segment through ReactMarkdown.
function MessageContent({ content }: { content: string }) {
  const segments = splitLatex(content);
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'block-math') return <BlockMath key={i} math={seg.value} />;
        if (seg.type === 'inline-math') return <InlineMath key={i} math={seg.value} />;
        return (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={mdComponents}>
            {seg.value}
          </ReactMarkdown>
        );
      })}
    </>
  );
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: '1rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
    }}>
      {messages.length === 0 && (
        <div style={{
          color: '#6e7681',
          fontSize: '0.875rem',
          textAlign: 'center',
          marginTop: '2rem',
        }}>
          Ask a question about AI Engineering…
        </div>
      )}

      {messages.map(msg => (
        <div
          key={msg.id}
          style={{
            display: 'flex',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}
        >
          <div style={{
            maxWidth: '85%',
            padding: '0.6rem 0.875rem',
            borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
            background: msg.role === 'user' ? '#1c2d4f' : '#161b22',
            border: msg.role === 'user'
              ? '1px solid rgba(96, 165, 250, 0.15)'
              : '1px solid #21262d',
            color: '#8b949e',
            fontSize: '0.875rem',
            lineHeight: 1.65,
          }}>
            <MessageContent content={msg.content} />
            {msg.isStreaming && (
              <span style={{
                display: 'inline-block',
                width: '8px',
                height: '12px',
                background: '#a78bfa',
                borderRadius: '1px',
                marginLeft: '2px',
                verticalAlign: 'text-bottom',
                animation: 'blink 1s step-end infinite',
              }} />
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
