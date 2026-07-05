import { afterEach, describe, expect, it, vi } from 'vitest';

function setHostname(hostname: string) {
  Object.defineProperty(window, 'location', {
    value: { hostname },
    configurable: true,
  });
}

describe('config service', () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    setHostname('localhost');
  });

  it('uses a relative API base on localhost', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_API_URL', 'https://backend.example');
    setHostname('localhost');

    const { API_BASE } = await import('./config');

    expect(API_BASE).toBe('');
  });

  it('uses VITE_API_URL on deployed hosts', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_API_URL', 'https://backend.example ');
    setHostname('demo.vercel.app');

    const { API_BASE } = await import('./config');

    expect(API_BASE).toBe('https://backend.example');
  });

  it('warns and falls back to relative API base when deployed without VITE_API_URL', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_API_URL', '');
    setHostname('demo.vercel.app');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { API_BASE } = await import('./config');

    expect(API_BASE).toBe('');
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('VITE_API_URL is not set.'));
  });
});
