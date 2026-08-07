import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../services/analytics', () => ({
  trackEvent: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../services/auth', () => ({
  requestOtp: vi.fn(),
  signInWithGoogle: vi.fn(),
  verifyOtp: vi.fn(),
}));

vi.mock('./TurnstileWidget', () => ({
  TurnstileWidget: ({
    onVerify,
    onExpire,
  }: {
    onVerify: (token: string) => void;
    onExpire: () => void;
  }) => (
    <div>
      <button onClick={() => onVerify('captcha-token')}>Complete CAPTCHA</button>
      <button onClick={onExpire}>Expire CAPTCHA</button>
    </div>
  ),
}));

import { trackEvent } from '../../services/analytics';
import { requestOtp, signInWithGoogle, verifyOtp } from '../../services/auth';
import type { AuthSession } from '../../types';
import { AuthScreen } from './AuthScreen';


const session: AuthSession = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  user: { id: 'user-1', email: 'user@example.com' },
};


describe('AuthScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(requestOtp).mockResolvedValue({ ok: true, captcha_required: false });
    vi.mocked(signInWithGoogle).mockResolvedValue(undefined);
    vi.mocked(verifyOtp).mockResolvedValue(session);
  });

  it('completes the email code flow from keyboard input', async () => {
    const onAuthenticated = vi.fn();
    render(<AuthScreen onAuthenticated={onAuthenticated} />);

    expect(trackEvent).toHaveBeenCalledWith('auth_viewed');
    const email = screen.getByPlaceholderText('you@example.com');
    fireEvent.focus(email);
    fireEvent.change(email, { target: { value: 'user@example.com' } });
    fireEvent.blur(email);
    fireEvent.keyDown(email, { key: 'Enter' });

    await screen.findByText('Check your email');
    expect(requestOtp).toHaveBeenCalledWith('user@example.com', undefined);
    expect(trackEvent).toHaveBeenCalledWith('otp_requested', { value: 'direct' });

    const code = screen.getByPlaceholderText('00000000');
    fireEvent.focus(code);
    fireEvent.change(code, { target: { value: '12a3456789' } });
    expect(code).toHaveProperty('value', '12345678');
    fireEvent.blur(code);
    fireEvent.keyDown(code, { key: 'Enter' });

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(session));
    expect(verifyOtp).toHaveBeenCalledWith('user@example.com', '12345678', undefined);
    expect(trackEvent).toHaveBeenCalledWith('otp_verified', {}, session);
  });

  it('requires and forwards a CAPTCHA token before retrying OTP delivery', async () => {
    vi.mocked(requestOtp)
      .mockResolvedValueOnce({ ok: false, captcha_required: true })
      .mockResolvedValueOnce({ ok: true, captcha_required: false });
    render(<AuthScreen onAuthenticated={vi.fn()} />);
    const email = screen.getByPlaceholderText('you@example.com');
    fireEvent.change(email, { target: { value: 'captcha@example.com' } });
    fireEvent.click(screen.getByText('Send code'));

    await screen.findByText('Please complete the CAPTCHA challenge.');
    expect(screen.getByText('Send code')).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByText('Complete CAPTCHA'));
    expect(screen.queryByText('Please complete the CAPTCHA challenge.')).toBeNull();
    fireEvent.click(screen.getByText('Expire CAPTCHA'));
    expect(screen.getByText('Send code')).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByText('Complete CAPTCHA'));
    fireEvent.click(screen.getByText('Send code'));
    await screen.findByText('Check your email');

    expect(requestOtp).toHaveBeenLastCalledWith('captcha@example.com', 'captcha-token');
    expect(trackEvent).toHaveBeenCalledWith('otp_requested', { value: 'captcha_required' });
  });

  it('surfaces provider errors and lets the user return to email entry', async () => {
    vi.mocked(signInWithGoogle).mockRejectedValueOnce(new Error('OAuth unavailable'));
    vi.mocked(requestOtp).mockRejectedValueOnce('offline');
    render(<AuthScreen onAuthenticated={vi.fn()} />);

    fireEvent.click(screen.getByText('Continue with Google'));
    await screen.findByText('OAuth unavailable');
    expect(trackEvent).toHaveBeenCalledWith('google_signin_started');

    const email = screen.getByPlaceholderText('you@example.com');
    fireEvent.change(email, { target: { value: 'user@example.com' } });
    fireEvent.click(screen.getByText('Send code'));
    await screen.findByText('Failed to send code');

    vi.mocked(requestOtp).mockResolvedValueOnce({ ok: true, captcha_required: false });
    fireEvent.click(screen.getByText('Send code'));
    await screen.findByText('Check your email');
    fireEvent.click(screen.getByText('Use a different email'));

    expect(screen.getByText('Sign in')).toBeTruthy();
    expect(screen.queryByPlaceholderText('00000000')).toBeNull();
    expect(screen.queryByText('Failed to send code')).toBeNull();
  });

  it('requests CAPTCHA recovery after a verification rejection', async () => {
    vi.mocked(verifyOtp)
      .mockRejectedValueOnce(new Error('CAPTCHA expired'))
      .mockRejectedValueOnce('invalid response');
    render(<AuthScreen onAuthenticated={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), {
      target: { value: 'user@example.com' },
    });
    fireEvent.click(screen.getByText('Send code'));
    await screen.findByText('Check your email');

    const code = screen.getByPlaceholderText('00000000');
    fireEvent.change(code, { target: { value: '12345678' } });
    fireEvent.click(screen.getByText('Verify code'));
    await screen.findByText('CAPTCHA expired');

    fireEvent.click(screen.getByText('Complete CAPTCHA'));
    fireEvent.click(screen.getByText('Verify code'));
    await screen.findByText('Failed to verify code');
    expect(verifyOtp).toHaveBeenLastCalledWith(
      'user@example.com',
      '12345678',
      'captcha-token',
    );
  });
});
