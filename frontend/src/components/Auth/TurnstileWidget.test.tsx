import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';


describe('TurnstileWidget', () => {
  afterEach(() => {
    document.getElementById('cf-turnstile-script')?.remove();
    delete window.turnstile;
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it('reports a missing site key without loading an external script', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', '');
    const { TurnstileWidget } = await import('./TurnstileWidget');

    render(<TurnstileWidget onVerify={vi.fn()} onExpire={vi.fn()} />);

    expect(screen.getByText('Turnstile site key is not configured.')).toBeTruthy();
    expect(document.getElementById('cf-turnstile-script')).toBeNull();
  });

  it('loads, renders, invokes callbacks, and removes the widget on cleanup', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', 'site-key');
    const onVerify = vi.fn();
    const onExpire = vi.fn();
    const remove = vi.fn();
    const renderWidget = vi.fn((_container, options) => {
      options.callback('verified-token');
      options['expired-callback']();
      return 'widget-1';
    });
    const { TurnstileWidget } = await import('./TurnstileWidget');
    const view = render(<TurnstileWidget onVerify={onVerify} onExpire={onExpire} />);
    const script = document.getElementById('cf-turnstile-script') as HTMLScriptElement;

    expect(script.src).toContain('challenges.cloudflare.com/turnstile');
    window.turnstile = { render: renderWidget, remove };
    act(() => script.onload?.(new Event('load')));

    await waitFor(() => expect(renderWidget).toHaveBeenCalled());
    expect(renderWidget.mock.calls[0][1]).toMatchObject({
      sitekey: 'site-key',
      theme: 'dark',
    });
    expect(onVerify).toHaveBeenCalledWith('verified-token');
    expect(onExpire).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(remove).toHaveBeenCalledWith('widget-1');
  });

  it('waits for an existing script and ignores it after unmount', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', 'site-key');
    const script = document.createElement('script');
    script.id = 'cf-turnstile-script';
    document.head.appendChild(script);
    const renderWidget = vi.fn(() => 'widget-1');
    window.turnstile = undefined;
    const { TurnstileWidget } = await import('./TurnstileWidget');
    const view = render(<TurnstileWidget onVerify={vi.fn()} onExpire={vi.fn()} />);

    view.unmount();
    window.turnstile = { render: renderWidget, remove: vi.fn() };
    act(() => script.dispatchEvent(new Event('load')));

    await Promise.resolve();
    expect(renderWidget).not.toHaveBeenCalled();
  });

  it('contains script load failures at the external boundary', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', 'site-key');
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { TurnstileWidget } = await import('./TurnstileWidget');
    render(<TurnstileWidget onVerify={vi.fn()} onExpire={vi.fn()} />);
    const script = document.getElementById('cf-turnstile-script') as HTMLScriptElement;

    act(() => script.onerror?.(new Event('error')));

    await waitFor(() => expect(error).toHaveBeenCalledWith(expect.any(Error)));
  });
});
