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
    pool: 'forks',
    fileParallelism: true,
    maxWorkers: 4,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      thresholds: {
        statements: 90,
        lines: 90,
        functions: 90,
        branches: 75,
      },
    },
  },
});
