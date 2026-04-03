/**
 * config.ts
 * Language: TypeScript
 * Purpose: Resolves the API base URL based on where the frontend is running.
 *          Single source of truth — import API_BASE from here, not from env directly.
 *
 * Routing logic:
 *   Local dev  (localhost / 127.0.0.1)
 *     → '' (empty string)
 *     → Vite dev server proxies /api → http://localhost:8000 (see vite.config.ts)
 *     → No cross-origin request, no CORS needed
 *
 *   Deployed   (Vercel, any non-localhost origin)
 *     → VITE_API_URL env var (set in Vercel dashboard → backend URL)
 *     → e.g. https://agent-backend-xxxxx.run.app
 *
 * To deploy: set VITE_API_URL=https://<your-backend-host>
 *            in the Vercel project's Environment Variables dashboard.
 * Locally:   leave VITE_API_URL unset (or blank) — Vite proxy handles routing.
 *
 * Connects to: services/api.ts, services/sse.ts
 */

const _isLocalhost =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
   window.location.hostname === '127.0.0.1');

const _envApiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim() ?? '';

// Local dev: always use relative URL (Vite proxy). Avoids cross-origin and CORS.
// Deployed: require VITE_API_URL — warn loudly if missing so it's not silent.
export const API_BASE: string = _isLocalhost
  ? ''
  : _envApiUrl || (() => {
      console.warn(
        '[config] VITE_API_URL is not set. ' +
        'Set it to your backend URL in the Vercel environment variables.',
      );
      return '';
    })();
