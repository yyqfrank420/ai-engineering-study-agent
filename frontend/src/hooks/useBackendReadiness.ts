import { useCallback, useEffect, useState } from 'react';
import type { AuthSession } from '../types';
import { prepareBackend } from '../services/api';
import { storageKeyForPrepare } from '../utils/threadState';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const PREPARE_TTL_MS = 12 * 60 * 1000;
const PREPARE_BYPASS = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' || import.meta.env.DEV;
const DEFAULT_PREPARE_MESSAGE = 'Backend is asleep to save cost. Click Prepare to warm it up.';

export function useBackendReadiness(authSession: AuthSession | null) {
  const [backendReadiness, setBackendReadiness] = useState<BackendReadiness>(
    PREPARE_BYPASS ? 'ready' : 'unknown',
  );
  const [prepareMessage, setPrepareMessage] = useState<string | null>(
    PREPARE_BYPASS ? null : DEFAULT_PREPARE_MESSAGE,
  );

  useEffect(() => {
    if (!authSession) {
      setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
      setPrepareMessage(PREPARE_BYPASS ? null : DEFAULT_PREPARE_MESSAGE);
      return;
    }

    const rememberedReadyAt = Number(localStorage.getItem(storageKeyForPrepare(authSession.user.id)) ?? '0');
    const isFresh = PREPARE_BYPASS || (rememberedReadyAt > 0 && Date.now() - rememberedReadyAt < PREPARE_TTL_MS);
    setBackendReadiness(isFresh ? 'ready' : 'unknown');
    setPrepareMessage(isFresh ? null : DEFAULT_PREPARE_MESSAGE);
  }, [authSession]);

  const handlePrepare = useCallback(async () => {
    if (!authSession) return;
    setBackendReadiness('preparing');
    setPrepareMessage('Starting study backend…');
    const timerIds = [
      window.setTimeout(() => setPrepareMessage('Loading retrieval index…'), 1400),
      window.setTimeout(() => setPrepareMessage('Almost ready…'), 4200),
    ];
    try {
      await prepareBackend();
      localStorage.setItem(storageKeyForPrepare(authSession.user.id), String(Date.now()));
      setBackendReadiness('ready');
      setPrepareMessage(null);
    } catch (err) {
      setBackendReadiness('error');
      setPrepareMessage(err instanceof Error ? err.message : 'Backend is still warming up. Please try again.');
    } finally {
      timerIds.forEach(id => window.clearTimeout(id));
    }
  }, [authSession]);

  const clearPreparedCache = useCallback(() => {
    if (!authSession) return;
    localStorage.removeItem(storageKeyForPrepare(authSession.user.id));
  }, [authSession]);

  return {
    backendReadiness,
    prepareMessage,
    isBackendReady: backendReadiness === 'ready',
    handlePrepare,
    clearPreparedCache,
  };
}
