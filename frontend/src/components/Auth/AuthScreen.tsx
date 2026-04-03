import { useState } from 'react';
import type { CSSProperties } from 'react';
import { requestOtp, verifyOtp } from '../../services/auth';
import type { AuthSession } from '../../types';
import { TurnstileWidget } from './TurnstileWidget';

interface AuthScreenProps {
  onAuthenticated: (session: AuthSession) => void;
}

export function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [email, setEmail]               = useState('');
  const [code, setCode]                 = useState('');
  const [step, setStep]                 = useState<'email' | 'verify'>('email');
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [emailFocused, setEmailFocused] = useState(false);
  const [codeFocused, setCodeFocused]   = useState(false);

  const submitEmail = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await requestOtp(email, captchaToken ?? undefined);
      if (result.captcha_required) {
        setCaptchaRequired(true);
        setError('Please complete the CAPTCHA challenge.');
        return;
      }
      setStep('verify');
      setCaptchaRequired(false);
      setCaptchaToken(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send code');
    } finally {
      setLoading(false);
    }
  };

  const submitCode = async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await verifyOtp(email, code, captchaToken ?? undefined);
      setCaptchaRequired(false);
      setCaptchaToken(null);
      onAuthenticated(session);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify code';
      setError(message);
      if (message.toLowerCase().includes('captcha')) {
        setCaptchaRequired(true);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={overlayStyle}>
      <div style={cardStyle}>

        {/* Branding */}
        <div style={{ textAlign: 'center', marginBottom: '1.75rem' }}>
          <div style={{
            fontSize: '1.35rem',
            fontWeight: 700,
            background: 'linear-gradient(90deg, #a78bfa, #60a5fa)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            letterSpacing: '0.01em',
            marginBottom: '0.4rem',
          }}>
            AI Engineering
          </div>
          <div style={{
            display: 'inline-block',
            fontSize: '0.7rem',
            padding: '2px 10px',
            borderRadius: '999px',
            background: 'rgba(167, 139, 250, 0.1)',
            border: '1px solid rgba(167, 139, 250, 0.2)',
            color: '#a78bfa',
            fontWeight: 500,
            letterSpacing: '0.04em',
          }}>
            Chip Huyen · O'Reilly
          </div>
        </div>

        {/* Heading */}
        <h2 style={{
          margin: '0 0 0.35rem',
          fontSize: '1.05rem',
          fontWeight: 600,
          color: '#e6edf3',
          textAlign: 'center',
        }}>
          {step === 'email' ? 'Sign in' : 'Check your email'}
        </h2>
        <p style={{
          margin: '0 0 1.5rem',
          fontSize: '0.82rem',
          color: '#6e7681',
          textAlign: 'center',
          lineHeight: 1.5,
        }}>
          {step === 'email'
            ? 'Enter your email to receive a one-time code.'
            : `We sent an 8-digit code to ${email}`}
        </p>

        {/* Fields */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
          <input
            type="email"
            value={email}
            disabled={step === 'verify' || loading}
            onChange={e => setEmail(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && step === 'email' && !loading && email && submitEmail()}
            onFocus={() => setEmailFocused(true)}
            onBlur={() => setEmailFocused(false)}
            placeholder="you@example.com"
            autoComplete="email"
            style={inputStyle(emailFocused, step === 'verify')}
          />

          {step === 'verify' && (
            <input
              type="text"
              value={code}
              disabled={loading}
              onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
              onKeyDown={e => e.key === 'Enter' && !loading && code.length === 8 && submitCode()}
              onFocus={() => setCodeFocused(true)}
              onBlur={() => setCodeFocused(false)}
              placeholder="00000000"
              autoComplete="one-time-code"
              inputMode="numeric"
              style={{
                ...inputStyle(codeFocused, false),
                fontSize: '1.5rem',
                letterSpacing: '0.3em',
                textAlign: 'center',
                fontWeight: 600,
                fontVariantNumeric: 'tabular-nums',
              }}
            />
          )}

          {captchaRequired && (
            <div style={{ paddingTop: '0.25rem' }}>
              <TurnstileWidget
                onVerify={token => { setCaptchaToken(token); setError(null); }}
                onExpire={() => setCaptchaToken(null)}
              />
            </div>
          )}

          {error && (
            <div style={{
              fontSize: '0.8rem',
              color: '#f87171',
              padding: '0.5rem 0.75rem',
              background: 'rgba(248, 113, 113, 0.08)',
              border: '1px solid rgba(248, 113, 113, 0.2)',
              borderRadius: '8px',
            }}>
              {error}
            </div>
          )}

          <button
            onClick={step === 'email' ? submitEmail : submitCode}
            disabled={loading || !email || (step === 'verify' && code.length < 8) || (captchaRequired && !captchaToken)}
            style={primaryButtonStyle(loading)}
          >
            {loading
              ? 'Working…'
              : step === 'email'
              ? 'Send code'
              : 'Verify code'}
          </button>

          {step === 'verify' && (
            <button
              onClick={() => { setStep('email'); setCode(''); setCaptchaRequired(false); setCaptchaToken(null); setError(null); }}
              disabled={loading}
              style={ghostButtonStyle}
            >
              Use a different email
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const overlayStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  // Subtle dark veil over the blurred app preview behind
  background: 'rgba(0, 0, 0, 0.45)',
  padding: '1.5rem',
  zIndex: 50,
  // Fade-in handled by CSS animation class below — applied via className isn't
  // available here (no CSS modules), so we use a short opacity transition on mount
  animation: 'authFadeIn 0.25s ease',
};

const cardStyle: CSSProperties = {
  width: '100%',
  maxWidth: '380px',
  // Liquid glass card
  background: 'rgba(12,16,23,0.7)',
  backdropFilter: 'blur(48px) saturate(200%)',
  WebkitBackdropFilter: 'blur(48px) saturate(200%)',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: '20px',
  padding: '2rem 1.75rem',
  boxShadow: [
    'inset 0 1px 0 rgba(255,255,255,0.12)',
    'inset 0 -1px 0 rgba(0,0,0,0.2)',
    '0 24px 60px rgba(0,0,0,0.55)',
    '0 0 0 1px rgba(167,139,250,0.07)',
  ].join(', '),
  animation: 'authSlideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
};

function inputStyle(focused: boolean, disabled: boolean): CSSProperties {
  return {
    width: '100%',
    background: focused ? 'rgba(167,139,250,0.06)' : 'rgba(255,255,255,0.04)',
    backdropFilter: 'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    color: disabled ? '#6e7681' : '#e6edf3',
    border: `1px solid ${focused ? 'rgba(167,139,250,0.5)' : 'rgba(255,255,255,0.08)'}`,
    borderRadius: '10px',
    padding: '0.8rem 1rem',
    fontSize: '0.95rem',
    outline: 'none',
    transition: 'border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease',
    boxShadow: focused
      ? '0 0 0 3px rgba(167,139,250,0.12), inset 0 1px 0 rgba(255,255,255,0.06)'
      : 'inset 0 1px 0 rgba(255,255,255,0.04)',
    cursor: disabled ? 'not-allowed' : 'text',
    boxSizing: 'border-box',
  };
}

function primaryButtonStyle(loading: boolean): CSSProperties {
  return {
    width: '100%',
    border: 'none',
    borderRadius: '10px',
    padding: '0.85rem 1rem',
    background: loading
      ? 'rgba(99, 102, 241, 0.4)'
      : 'linear-gradient(135deg, #7c3aed, #2563eb)',
    color: '#fff',
    fontSize: '0.9rem',
    fontWeight: 600,
    cursor: loading ? 'not-allowed' : 'pointer',
    transition: 'opacity 0.15s ease, transform 0.1s ease',
    opacity: loading ? 0.7 : 1,
    letterSpacing: '0.01em',
  };
}

const ghostButtonStyle: CSSProperties = {
  width: '100%',
  borderRadius: '10px',
  padding: '0.65rem 1rem',
  background: 'transparent',
  border: 'none',
  color: '#6e7681',
  fontSize: '0.82rem',
  cursor: 'pointer',
  transition: 'color 0.15s ease',
};
