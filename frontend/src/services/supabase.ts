import { createClient } from '@supabase/supabase-js';
import { evalAuthBootstrapEnabled } from './evalAuthBootstrap';

const CONFIGURED_SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? '';
const CONFIGURED_SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY ?? '';
const SUPABASE_URL = CONFIGURED_SUPABASE_URL || (evalAuthBootstrapEnabled ? 'http://127.0.0.1:54321' : '');
const SUPABASE_ANON_KEY = CONFIGURED_SUPABASE_ANON_KEY || (evalAuthBootstrapEnabled ? 'eval-auth-bootstrap' : '');

if ((!CONFIGURED_SUPABASE_URL || !CONFIGURED_SUPABASE_ANON_KEY) && !evalAuthBootstrapEnabled) {
  console.warn('[auth] Missing Supabase environment variables');
}

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: 'ai-engineering-auth',
  },
});
