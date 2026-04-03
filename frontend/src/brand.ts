/**
 * brand.ts
 * Language: TypeScript
 * Purpose: Single source of truth for design tokens — mirrors the CSS custom
 *          properties in index.css so inline styles and JS animations can stay
 *          consistent without re-reading computed styles at runtime.
 * Connects to: index.css (kept in sync manually), any component using inline styles.
 * Inputs:  none (static constants)
 * Outputs: exported token objects — colors, typography, radii, shadows.
 *
 * Update BOTH this file AND index.css :root block when changing tokens.
 */

// ── Backgrounds ────────────────────────────────────────────────────────────────
export const BG = {
  base:    '#0d1117',
  panel:   '#161b22',
  overlay: '#1c2128',
} as const;

// ── Borders ────────────────────────────────────────────────────────────────────
export const BORDER = {
  subtle:  '#21262d',
  default: '#30363d',
} as const;

// ── Text ───────────────────────────────────────────────────────────────────────
export const TEXT = {
  primary:   '#e6edf3',
  secondary: '#8b949e',
  tertiary:  '#6e7681',
  // Deliberately faded — for footer, captions, legal copy
  muted:     'rgba(139,148,158,0.55)',
  ghost:     'rgba(110,118,129,0.45)',
} as const;

// ── Accent ─────────────────────────────────────────────────────────────────────
export const ACCENT = {
  violet: '#a78bfa',
  blue:   '#60a5fa',
  grad:   'linear-gradient(135deg, #a78bfa, #60a5fa)',
} as const;

// ── Status ─────────────────────────────────────────────────────────────────────
export const STATUS = {
  green:  '#3fb950',
  yellow: '#d29922',
  red:    '#f85149',
} as const;

// ── Typography ─────────────────────────────────────────────────────────────────
export const FONT = {
  family: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  size: {
    xs:  '0.68rem',
    sm:  '0.75rem',
    md:  '0.875rem',
    base:'1rem',
  },
  weight: {
    normal:   400,
    medium:   500,
    semibold: 600,
  },
} as const;

// ── Radii ──────────────────────────────────────────────────────────────────────
export const RADIUS = {
  pill: '999px',
  sm:   '4px',
  md:   '8px',
  lg:   '12px',
} as const;
