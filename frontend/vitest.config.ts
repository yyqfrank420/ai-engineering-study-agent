// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/vitest.config.ts
// Purpose: Vitest configuration for frontend unit tests
// Language: TypeScript
// Connects to: vite.config.ts (extends), jsdom (test environment)
// Inputs:  Source files under src/
// Outputs: Test results
// ─────────────────────────────────────────────────────────────────────────────

import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [],
  },
});
