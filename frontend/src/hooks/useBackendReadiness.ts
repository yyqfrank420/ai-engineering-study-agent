import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { prepareBackend } from '../services/api';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const PREPARE_BYPASS = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' || import.meta.env.DEV;

export function useBackendReadiness(authSession: AuthSession | null) {
  const [backendReadiness, setBackendReadiness] = useState<BackendReadiness>(
    PREPARE_BYPASS ? 'ready' : 'unknown',
  );
  const [prepareMessage, setPrepareMessage] = useState<string | null>(null);
  const preparingForUserRef = useRef<string | null>(null);
  const activeUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!authSession) {
      activeUserIdRef.current = null;
      setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
      setPrepareMessage(null);
      preparingForUserRef.current = null;
      return;
    }

    if (activeUserIdRef.current === authSession.user.id) {
      return;
    }
    activeUserIdRef.current = authSession.user.id;
    setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
    setPrepareMessage(null);
  }, [authSession]);

  const prepareBackendNow = useCallback(async () => {
    if (!authSession) return;
    if (preparingForUserRef.current === authSession.user.id) return;
    preparingForUserRef.current = authSession.user.id;
    setBackendReadiness('preparing');
    setPrepareMessage('Waking up backend…');
    const timerIds = [
      window.setTimeout(() => setPrepareMessage('Loading retrieval index…'), 1400),
      window.setTimeout(() => setPrepareMessage('Almost ready…'), 4200),
    ];
    try {
      await prepareBackend();
      setBackendReadiness('ready');
      setPrepareMessage(null);
    } catch (err) {
      preparingForUserRef.current = null;
      setBackendReadiness('error');
      setPrepareMessage(err instanceof Error ? err.message : 'Backend unavailable — please reload.');
    } finally {
      timerIds.forEach(id => window.clearTimeout(id));
    }
  }, [authSession]);

  const clearPreparedCache = useCallback(() => {
    if (!authSession) return;
    preparingForUserRef.current = null;
    setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
    setPrepareMessage(null);
  }, [authSession]);

  return {
    backendReadiness,
    prepareMessage,
    isBackendReady: backendReadiness === 'ready',
    prepareBackendNow,
    clearPreparedCache,
  };
}
