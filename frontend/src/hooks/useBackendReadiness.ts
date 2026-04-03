import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { prepareBackend } from '../services/api';
import { storageKeyForPrepare } from '../utils/threadState';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const PREPARE_TTL_MS = 12 * 60 * 1000;
const PREPARE_BYPASS = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' || import.meta.env.DEV;

export function useBackendReadiness(authSession: AuthSession | null) {
  const [backendReadiness, setBackendReadiness] = useState<BackendReadiness>(
    PREPARE_BYPASS ? 'ready' : 'unknown',
  );
  const [prepareMessage, setPrepareMessage] = useState<string | null>(null);
  // Prevent double-firing auto-prepare if authSession object identity changes (e.g. token refresh)
  const preparingForUserRef = useRef<string | null>(null);

  useEffect(() => {
    if (!authSession) {
      setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
      setPrepareMessage(null);
      preparingForUserRef.current = null;
      return;
    }

    const rememberedReadyAt = Number(localStorage.getItem(storageKeyForPrepare(authSession.user.id)) ?? '0');
    const isFresh = PREPARE_BYPASS || (rememberedReadyAt > 0 && Date.now() - rememberedReadyAt < PREPARE_TTL_MS);
    setBackendReadiness(isFresh ? 'ready' : 'unknown');
    setPrepareMessage(null);
  }, [authSession]);

  const handlePrepare = useCallback(async (session: AuthSession) => {
    if (preparingForUserRef.current === session.user.id) return;
    preparingForUserRef.current = session.user.id;
    setBackendReadiness('preparing');
    setPrepareMessage('Waking up backend…');
    const timerIds = [
      window.setTimeout(() => setPrepareMessage('Loading retrieval index…'), 1400),
      window.setTimeout(() => setPrepareMessage('Almost ready…'), 4200),
    ];
    try {
      await prepareBackend();
      localStorage.setItem(storageKeyForPrepare(session.user.id), String(Date.now()));
      setBackendReadiness('ready');
      setPrepareMessage(null);
    } catch (err) {
      preparingForUserRef.current = null;
      setBackendReadiness('error');
      setPrepareMessage(err instanceof Error ? err.message : 'Backend unavailable — please reload.');
    } finally {
      timerIds.forEach(id => window.clearTimeout(id));
    }
  }, []);

  // Auto-trigger prepare silently when the user is authenticated and backend is not warm.
  // Never show an explicit Prepare button — the user shouldn't need to do this manually.
  useEffect(() => {
    if (authSession && backendReadiness === 'unknown') {
      handlePrepare(authSession);
    }
  }, [authSession, backendReadiness, handlePrepare]);

  const clearPreparedCache = useCallback(() => {
    if (!authSession) return;
    localStorage.removeItem(storageKeyForPrepare(authSession.user.id));
    preparingForUserRef.current = null;
  }, [authSession]);

  return {
    backendReadiness,
    prepareMessage,
    isBackendReady: backendReadiness === 'ready',
    clearPreparedCache,
  };
}
