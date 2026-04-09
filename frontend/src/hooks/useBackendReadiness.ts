import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession } from '../types';
import { prepareBackend } from '../services/api';

export type BackendReadiness = 'unknown' | 'preparing' | 'ready' | 'error';

const PREPARE_BYPASS = import.meta.env.VITE_DEV_BYPASS_AUTH === 'true' || import.meta.env.DEV;

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
  const [backendReadiness, setBackendReadiness] = useState<BackendReadiness>(
    PREPARE_BYPASS ? 'ready' : 'unknown',
  );
  const [prepareMessage, setPrepareMessage] = useState<string | null>(null);
  const preparingForUserRef = useRef<string | null>(null);
  const activeUserIdRef = useRef<string | null>(null);
  const rotationIndexRef = useRef(0);

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
    preparingForUserRef.current = null;
    setBackendReadiness(PREPARE_BYPASS ? 'ready' : 'unknown');
    setPrepareMessage(null);
  }, [authSession]);

  const prepareBackendNow = useCallback(async () => {
    if (!authSession) return;
    if (preparingForUserRef.current === authSession.user.id) return;
    preparingForUserRef.current = authSession.user.id;
    setBackendReadiness('preparing');
    setPrepareMessage('Waking up backend…');

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

    // Poll /api/prepare to get current step and rotate messages if on "index" step
    const pollPrepare = async () => {
      try {
        const result = await prepareBackend();
        if (result.status === 'ready') {
          setBackendReadiness('ready');
          setPrepareMessage(null);
          cleanup();
          return true; // done
        }
      } catch (err) {
        if (err instanceof Error) {
          currentStep = (err as any).step || 'unknown';
          const stepMsg = STEP_MESSAGES[currentStep];

          if (currentStep === 'index') {
            // For the index step, start rotating messages if not already
            if (rotationTimer === null) {
              rotationIndexRef.current = 0;
              const rotateMessage = () => {
                setPrepareMessage(INDEX_ROTATION[rotationIndexRef.current % INDEX_ROTATION.length]);
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
            setPrepareMessage(stepMsg || 'Warming up backend…');
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
        if (await pollPrepare()) {
          if (pollInterval !== null) {
            window.clearInterval(pollInterval);
          }
        }
      }, 500);
    } catch (err) {
      preparingForUserRef.current = null;
      setBackendReadiness('error');
      setPrepareMessage(err instanceof Error ? err.message : 'Backend unavailable — please reload.');
      cleanup();
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
