import { useCallback, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { trackEvent } from '../services/analytics';
import { prepareBackend } from '../services/api';

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

// Messages for each startup step
const STEP_MESSAGES: Record<string, string> = {
  database: 'Initializing database…',
  artifacts: 'Downloading knowledge base…',
  index: 'Loading embeddings…',
};

// Rotating messages for the "index" step (the long 20-second one)
// First message includes the cold-start warning
const INDEX_ROTATION = [
  'Loading embeddings… (cold-start may take ~30 seconds)',
  'Building retrieval index…',
  'Preparing knowledge base…',
];

export function useBackendReadiness(authSession: AuthSession | null) {
  const [readinessState, setReadinessState] = useState<{
    userId: string | null;
    readiness: BackendReadiness;
    message: string | null;
  }>({
    userId: null,
    readiness: DEFAULT_READINESS,
    message: null,
  });
  const preparingForUserRef = useRef<string | null>(null);
  const rotationIndexRef = useRef(0);

  const stateBelongsToUser = !!authSession && readinessState.userId === authSession.user.id;
  const backendReadiness = stateBelongsToUser ? readinessState.readiness : DEFAULT_READINESS;
  const prepareMessage = stateBelongsToUser ? readinessState.message : null;

  const prepareBackendNow = useCallback(async () => {
    if (!authSession) return;
    const userId = authSession.user.id;
    if (preparingForUserRef.current === userId) return;
    preparingForUserRef.current = userId;
    setReadinessState({ userId, readiness: 'preparing', message: 'Waking up backend…' });
    void trackEvent('prepare_clicked', { backend_readiness_state: backendReadiness }, authSession);

    let pollInterval: number | null = null;
    let rotationTimer: number | null = null;
    let currentStep = 'unknown';

    const cleanup = () => {
      if (pollInterval !== null) {
        window.clearInterval(pollInterval);
      }
      if (rotationTimer !== null) {
        window.clearInterval(rotationTimer);
      }
    };

    const markPrepareFailed = (err: unknown) => {
      preparingForUserRef.current = null;
      setReadinessState({
        userId,
        readiness: 'error',
        message: err instanceof Error ? err.message : 'Backend unavailable — please reload.',
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

    // Poll /api/prepare to get current step and rotate messages if on "index" step
    const pollPrepare = async () => {
      try {
        const result = await prepareBackend();
        if (result.status === 'ready') {
          preparingForUserRef.current = null;
          setReadinessState({ userId, readiness: 'ready', message: null });
          void trackEvent('prepare_succeeded', { backend_readiness_state: 'ready' }, authSession);
          cleanup();
          return true; // done
        }
      } catch (err) {
        if (err instanceof Error) {
          const step = (err as Error & { step?: string }).step;
          if (!step) {
            throw err;
          }
          currentStep = step;
          const stepMsg = STEP_MESSAGES[currentStep];

          if (currentStep === 'index') {
            // For the index step, start rotating messages if not already
            if (rotationTimer === null) {
              rotationIndexRef.current = 0;
              const rotateMessage = () => {
                setReadinessState({
                  userId,
                  readiness: 'preparing',
                  message: INDEX_ROTATION[rotationIndexRef.current % INDEX_ROTATION.length],
                });
                rotationIndexRef.current += 1;
              };
              rotateMessage();
              rotationTimer = window.setInterval(rotateMessage, 2500);
            }
          } else {
            // For other steps, show the step message and clear rotation
            if (rotationTimer !== null) {
              window.clearInterval(rotationTimer);
              rotationTimer = null;
            }
            setReadinessState({
              userId,
              readiness: 'preparing',
              message: stepMsg || 'Warming up backend…',
            });
          }
        }
      }
      return false; // not done yet
    };

    try {
      // Initial check
      if (await pollPrepare()) {
        return;
      }

      // Poll every 500ms until ready
      pollInterval = window.setInterval(async () => {
        try {
          if (await pollPrepare()) {
            if (pollInterval !== null) {
              window.clearInterval(pollInterval);
            }
          }
        } catch (err) {
          markPrepareFailed(err);
        }
      }, 500);
    } catch (err) {
      markPrepareFailed(err);
    }
  }, [authSession, backendReadiness]);

  const clearPreparedCache = useCallback(() => {
    if (!authSession) return;
    preparingForUserRef.current = null;
    setReadinessState({ userId: authSession.user.id, readiness: DEFAULT_READINESS, message: null });
  }, [authSession]);

  return {
    backendReadiness,
    prepareMessage,
    isBackendReady: backendReadiness === 'ready',
    prepareBackendNow,
    clearPreparedCache,
  };
}
