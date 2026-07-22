import { useCallback, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { trackEvent } from '../services/analytics';
import { prepareBackend } from '../services/api';
import type { PrepareResponse } from '../services/api';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const IS_TEST_ENV =
  import.meta.env.MODE === 'test' ||
  import.meta.env.VITEST === 'true' ||
  (typeof navigator !== 'undefined' && navigator.userAgent.includes('jsdom'));

const PREPARE_BYPASS =
  !IS_TEST_ENV &&
  (
    import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' ||
    import.meta.env.DEV
  );
const DEFAULT_READINESS: BackendReadiness = PREPARE_BYPASS ? 'ready' : 'unknown';

export interface BackendPrepareProgress {
  completedUnits: number;
  totalUnits: number;
  percent: number;
}

const STEP_MESSAGES: Record<string, string> = {
  database: 'Initializing database…',
  artifacts: 'Checking knowledge-base files…',
  index: 'Loading the retrieval index…',
};

function normaliseProgress(result: PrepareResponse): BackendPrepareProgress | null {
  const progress = result.progress;
  if (!progress) return null;
  const rawTotal = Number(progress.total_units);
  const rawCompleted = Number(progress.completed_units);
  const rawPercent = Number(progress.percent);
  if (![rawTotal, rawCompleted, rawPercent].every(Number.isFinite)) return null;
  const totalUnits = Math.max(1, Math.round(rawTotal));
  const completedUnits = Math.min(totalUnits, Math.max(0, Math.round(rawCompleted)));
  return {
    completedUnits,
    totalUnits,
    percent: Math.min(100, Math.max(0, Math.round(rawPercent))),
  };
}

export function useBackendReadiness(authSession: AuthSession | null) {
  const [readinessState, setReadinessState] = useState<{
    userId: string | null;
    readiness: BackendReadiness;
    message: string | null;
    progress: BackendPrepareProgress | null;
  }>({
    userId: null,
    readiness: DEFAULT_READINESS,
    message: null,
    progress: null,
  });
  const preparingForUserRef = useRef<string | null>(null);

  const stateBelongsToUser = !!authSession && readinessState.userId === authSession.user.id;
  const backendReadiness = stateBelongsToUser ? readinessState.readiness : DEFAULT_READINESS;
  const prepareMessage = stateBelongsToUser ? readinessState.message : null;
  const prepareProgress = stateBelongsToUser ? readinessState.progress : null;

  const prepareBackendNow = useCallback(async () => {
    if (!authSession) return;
    const userId = authSession.user.id;
    if (preparingForUserRef.current === userId) return;
    preparingForUserRef.current = userId;
    setReadinessState({
      userId,
      readiness: 'preparing',
      message: 'Starting the service…',
      progress: { completedUnits: 0, totalUnits: 3, percent: 0 },
    });
    void trackEvent('prepare_clicked', { backend_readiness_state: backendReadiness }, authSession);

    let pollTimer: number | null = null;

    const cleanup = () => {
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    };

    const markPrepareFailed = (err: unknown) => {
      preparingForUserRef.current = null;
      setReadinessState({
        userId,
        readiness: 'error',
        message: err instanceof Error ? err.message : 'Backend unavailable — please reload.',
        progress: null,
      });
      void trackEvent(
        'prepare_failed',
        {
          backend_readiness_state: 'error',
          error_code: err instanceof Error ? err.message : 'prepare_failed',
        },
        authSession,
      );
      cleanup();
    };

    // The server owns milestone completion; the browser only renders reported progress.
    const pollPrepare = async () => {
      const result = await prepareBackend();
      if (result.status === 'ready') {
        preparingForUserRef.current = null;
        setReadinessState({ userId, readiness: 'ready', message: null, progress: null });
        void trackEvent('prepare_succeeded', { backend_readiness_state: 'ready' }, authSession);
        cleanup();
        return true;
      }
      const message = result.detail?.trim() || STEP_MESSAGES[result.step ?? ''] || 'Warming up backend…';
      setReadinessState({
        userId,
        readiness: 'preparing',
        message,
        progress: normaliseProgress(result),
      });
      return false;
    };

    try {
      // Initial check
      if (await pollPrepare()) {
        return;
      }

      // Schedule the next check only after the previous one settles. Overlapping
      // requests can arrive out of order and otherwise regress a ready service
      // back to an older startup milestone.
      const schedulePoll = () => {
        pollTimer = window.setTimeout(async () => {
          pollTimer = null;
          try {
            if (!await pollPrepare()) schedulePoll();
          } catch (err) {
            markPrepareFailed(err);
          }
        }, 500);
      };
      schedulePoll();
    } catch (err) {
      markPrepareFailed(err);
    }
  }, [authSession, backendReadiness]);

  const clearPreparedCache = useCallback(() => {
    if (!authSession) return;
    preparingForUserRef.current = null;
    setReadinessState({
      userId: authSession.user.id,
      readiness: DEFAULT_READINESS,
      message: null,
      progress: null,
    });
  }, [authSession]);

  return {
    backendReadiness,
    prepareMessage,
    prepareProgress,
    isBackendReady: backendReadiness === 'ready',
    prepareBackendNow,
    clearPreparedCache,
  };
}
