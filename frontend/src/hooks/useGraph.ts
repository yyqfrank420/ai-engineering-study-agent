// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/hooks/useGraph.ts
// Purpose: Manages graph sequence playback state (the scrubber at the bottom
//          of the graph pane). Tracks the current step and which nodes are
//          active/dimmed at that step.
// Connects to: types/index.ts, components/GraphCanvas/SequenceBar.tsx
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useReducer } from 'react';
import type { GraphData } from '../types';

const AUTO_PLAY_STEP_MS = 900;

type PlaybackState = {
  signature: string;
  currentStep: number;
  isAutoPlaying: boolean;
};

type PlaybackAction =
  | {
      type: 'syncGraph';
      signature: string;
      hasGraph: boolean;
      shouldAutoPlay: boolean;
    }
  | {
      type: 'tick';
      totalSteps: number;
    }
  | {
      type: 'goToStep';
      step: number;
      totalSteps: number;
    };

function graphSignature(graphData: GraphData | null): string {
  if (!graphData) return 'none';
  return JSON.stringify({
    title: graphData.title,
    nodes: graphData.nodes.map(node => node.id),
    edges: graphData.edges.map(edge => `${edge.source}->${edge.target}:${edge.label}`),
    sequence: graphData.sequence.map(step => `${step.step}:${step.nodes.join('|')}`),
  });
}

function playbackReducer(state: PlaybackState, action: PlaybackAction): PlaybackState {
  switch (action.type) {
    case 'syncGraph':
      if (action.signature === state.signature) {
        return state;
      }
      if (!action.hasGraph) {
        return { signature: action.signature, currentStep: -1, isAutoPlaying: false };
      }
      if (action.shouldAutoPlay) {
        return { signature: action.signature, currentStep: 0, isAutoPlaying: true };
      }
      return { signature: action.signature, currentStep: -1, isAutoPlaying: false };

    case 'tick':
      if (!state.isAutoPlaying) {
        return state;
      }
      if (state.currentStep >= action.totalSteps - 1) {
        return { ...state, currentStep: -1, isAutoPlaying: false };
      }
      return {
        ...state,
        currentStep: Math.min(state.currentStep + 1, action.totalSteps - 1),
      };

    case 'goToStep': {
      if (action.step === -1) {
        return { ...state, currentStep: -1, isAutoPlaying: false };
      }
      const maxStep = Math.max(action.totalSteps - 1, 0);
      return {
        ...state,
        currentStep: Math.max(0, Math.min(action.step, maxStep)),
        isAutoPlaying: false,
      };
    }
  }
}

export function useGraph(graphData: GraphData | null, animateSequence: boolean) {
  // -1 = overview (all nodes visible). Steps 0..N-1 dim non-active nodes.
  const [playback, dispatchPlayback] = useReducer(playbackReducer, {
    signature: 'none',
    currentStep: -1,
    isAutoPlaying: false,
  });

  const totalSteps = graphData?.sequence?.length ?? 0;
  const hasSequence = totalSteps > 1;
  const hasGraph = Boolean(graphData);
  const signature = useMemo(() => graphSignature(graphData), [graphData]);
  const { currentStep, isAutoPlaying } = playback;

  // Reset / autoplay whenever a new graph arrives.
  useEffect(() => {
    dispatchPlayback({
      type: 'syncGraph',
      signature,
      hasGraph,
      shouldAutoPlay: animateSequence && hasSequence,
    });
  }, [animateSequence, hasGraph, hasSequence, signature]);

  useEffect(() => {
    if (!isAutoPlaying || !hasSequence) return;

    const timeout = window.setTimeout(() => {
      dispatchPlayback({ type: 'tick', totalSteps });
    }, AUTO_PLAY_STEP_MS);

    return () => window.clearTimeout(timeout);
  }, [currentStep, hasSequence, isAutoPlaying, totalSteps]);

  // When currentStep is -1 (overview), the set is empty → D3 shows all nodes.
  // When a step is selected, only that step's node IDs are in the set.
  const activeNodeIds: Set<string> = useMemo(() => new Set(
    hasSequence && graphData && currentStep >= 0
      ? (graphData.sequence[currentStep]?.nodes ?? [])
      : []
  ), [currentStep, graphData, hasSequence]);

  const stepDescription = hasSequence && graphData && currentStep >= 0
    ? graphData.sequence[currentStep]?.description ?? ''
    : '';

  const goToStep = useCallback((step: number) => {
    if (!graphData) return;
    dispatchPlayback({ type: 'goToStep', step, totalSteps });
  }, [graphData, totalSteps]);

  return {
    currentStep,
    totalSteps,
    hasSequence,
    activeNodeIds,
    stepDescription,
    goToStep,
  };
}
