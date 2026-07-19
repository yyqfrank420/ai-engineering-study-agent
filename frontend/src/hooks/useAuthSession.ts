import { useCallback, useEffect, useState } from 'react';
import type { AuthSession } from '../types';
import { identifyAnalyticsUser, initAnalytics, resetAnalytics } from '../services/analytics';
import { getStoredSession, onAuthSessionChange } from '../services/auth';
import { readEvalAuthSession } from '../services/evalAuthBootstrap';

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

const EVAL_SESSION = readEvalAuthSession();
const INITIAL_SESSION = DEV_SESSION ?? EVAL_SESSION;

export function useAuthSession() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(INITIAL_SESSION);
  const [authReady, setAuthReady] = useState(Boolean(INITIAL_SESSION));

  useEffect(() => {
    initAnalytics();

    if (INITIAL_SESSION) {
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
