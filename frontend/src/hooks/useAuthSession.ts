import { useCallback, useEffect, useState } from 'react';
import type { AuthSession } from '../types';
import { getStoredSession, onAuthSessionChange } from '../services/auth';

const DEV_BYPASS = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true';

const DEV_SESSION: AuthSession | null = DEV_BYPASS
  ? {
      access_token: 'dev-local',
      refresh_token: 'dev-local',
      token_type: 'bearer',
      user: { id: '00000000-0000-0000-0000-000000000dev', email: 'dev@local' },
    }
  : null;

export function useAuthSession() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
    if (DEV_SESSION) {
      setAuthSession(DEV_SESSION);
      setAuthReady(true);
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
