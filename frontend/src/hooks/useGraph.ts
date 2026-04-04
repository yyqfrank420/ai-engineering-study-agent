// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/hooks/useGraph.ts
// Purpose: Manages graph sequence playback state (the scrubber at the bottom
//          of the graph pane). Tracks the current step and which nodes are
//          active/dimmed at that step.
// Connects to: types/index.ts, components/GraphCanvas/SequenceBar.tsx
// ─────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { GraphData } from '../types';

const AUTO_PLAY_STEP_MS = 900;

function graphSignature(graphData: GraphData | null): string {
  if (!graphData) return 'none';
  return JSON.stringify({
    title: graphData.title,
    nodes: graphData.nodes.map(node => node.id),
    edges: graphData.edges.map(edge => `${edge.source}->${edge.target}:${edge.label}`),
    sequence: graphData.sequence.map(step => `${step.step}:${step.nodes.join('|')}`),
  });
}

export function useGraph(graphData: GraphData | null, animateSequence: boolean) {
  // -1 = overview (all nodes visible). Steps 0..N-1 dim non-active nodes.
  const [currentStep, setCurrentStep] = useState(-1);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);
  const lastGraphSignatureRef = useRef<string>('none');

  const totalSteps = graphData?.sequence?.length ?? 0;
  const hasSequence = totalSteps > 1;
  const signature = useMemo(() => graphSignature(graphData), [graphData]);

  // Reset / autoplay whenever a new graph arrives.
  useEffect(() => {
    const changed = signature !== lastGraphSignatureRef.current;
    lastGraphSignatureRef.current = signature;

    if (!graphData) {
      setCurrentStep(-1);
      setIsAutoPlaying(false);
      return;
    }

    if (!changed) {
      return;
    }

    if (animateSequence && hasSequence) {
      setCurrentStep(0);
      setIsAutoPlaying(true);
      return;
    }

    setCurrentStep(-1);
    setIsAutoPlaying(false);
  }, [animateSequence, graphData, hasSequence, signature]);

  useEffect(() => {
    if (!isAutoPlaying || !hasSequence) return;

    const timeout = window.setTimeout(() => {
      if (currentStep >= totalSteps - 1) {
        setCurrentStep(-1);
        setIsAutoPlaying(false);
        return;
      }
      setCurrentStep(prev => Math.min(prev + 1, totalSteps - 1));
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
    setIsAutoPlaying(false);
    // -1 is a valid value (overview). Clamp everything else to 0..N-1.
    if (step === -1) { setCurrentStep(-1); return; }
    setCurrentStep(Math.max(0, Math.min(step, totalSteps - 1)));
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
