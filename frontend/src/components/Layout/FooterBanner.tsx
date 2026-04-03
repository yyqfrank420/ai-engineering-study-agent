/**
 * FooterBanner.tsx
 * Language: TypeScript / React (TSX)
 * Purpose: Persistent single-line footer — project info, contact note, legal copy.
 *          Ghost-level opacity so it doesn't compete with content above.
 * Connects to: brand.ts (design tokens)
 * Inputs:  none (static content)
 * Outputs: <footer> JSX element
 */

import type { CSSProperties } from 'react';
import { BORDER, FONT, TEXT } from '../../brand';

export function FooterBanner() {
  return (
    <footer style={footerStyle}>
      <div style={rowStyle}>

        {/* About section */}
        <span style={labelStyle}>About</span>
        <span style={textStyle}>Graph-guided study companion for AI Engineering by Chip Huyen.</span>

        <span style={dotStyle}>·</span>

        {/* Contact section */}
        <span style={labelStyle}>Contact</span>
        <span style={textStyle}>Message me on LinkedIn for access to the guided study version.</span>

        <span style={dotStyle}>·</span>

        {/* Legal */}
        <span style={legalStyle}>© 2026 Yang Yuqing</span>
        <span style={dotStyle}>·</span>
        <span style={legalStyle}>Non-profit, educational use only.</span>
        <span style={dotStyle}>·</span>
        <span style={legalStyle}>Book content and all related rights remain with Chip Huyen and O&apos;Reilly Media.</span>

      </div>
    </footer>
  );
}

const footerStyle: CSSProperties = {
  flexShrink: 0,
  borderTop: `1px solid ${BORDER.subtle}`,
  background: 'rgba(8,11,17,0.5)',
  backdropFilter: 'blur(24px)',
  WebkitBackdropFilter: 'blur(24px)',
};

const rowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.4rem',
  padding: '0.55rem 1.1rem',
  flexWrap: 'nowrap',
  overflow: 'hidden',
  whiteSpace: 'nowrap',
};

const labelStyle: CSSProperties = {
  fontSize: FONT.size.xs,
  fontWeight: FONT.weight.semibold,
  color: TEXT.secondary,
  flexShrink: 0,
};

const textStyle: CSSProperties = {
  fontSize: FONT.size.xs,
  color: TEXT.muted,
  flexShrink: 1,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
};

const legalStyle: CSSProperties = {
  fontSize: FONT.size.xs,
  color: TEXT.ghost,
  flexShrink: 1,
};

const dotStyle: CSSProperties = {
  fontSize: FONT.size.xs,
  color: 'rgba(110,118,129,0.28)',
  flexShrink: 0,
  userSelect: 'none',
};
