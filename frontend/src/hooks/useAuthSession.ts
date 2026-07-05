import { useCallback, useEffect, useState } from 'react';
import type { AuthSession } from '../types';
import { identifyAnalyticsUser, initAnalytics, resetAnalytics } from '../services/analytics';
import { getStoredSession, onAuthSessionChange } from '../services/auth';

const DEV_BYPASS_REQUESTED = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true';

if (import.meta.env.PROD && DEV_BYPASS_REQUESTED) {
  throw new Error('VITE_DEV_BYPASS_AUTH must be false in production builds');
}

const DEV_BYPASS = import.meta.env.DEV && DEV_BYPASS_REQUESTED;

const DEV_SESSION: AuthSession | null = DEV_BYPASS
  ? {
      access_token: 'dev-local',
      refresh_token: 'dev-local',
      token_type: 'bearer',
      user: { id: '00000000-0000-0000-0000-000000000dev', email: 'dev@local' },
    }
  : null;

export function useAuthSession() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(DEV_SESSION);
  const [authReady, setAuthReady] = useState(Boolean(DEV_SESSION));

  useEffect(() => {
    initAnalytics();

    if (DEV_SESSION) {
      return;
    }

    getStoredSession().then(session => {
      setAuthSession(session);
      setAuthReady(true);
    });

    return onAuthSessionChange(session => {
      setAuthSession(session);
      setAuthReady(true);
    });
  }, []);

  useEffect(() => {
    if (authSession) {
      identifyAnalyticsUser(authSession);
      return;
    }
    resetAnalytics();
  }, [authSession]);

  const handleAuthenticated = useCallback((session: AuthSession) => {
    setAuthSession(session);
  }, []);

  return {
    authSession,
    authReady,
    handleAuthenticated,
    setAuthSession,
  };
}
