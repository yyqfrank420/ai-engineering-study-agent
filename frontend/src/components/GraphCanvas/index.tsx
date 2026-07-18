// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/index.tsx
// Purpose: Graph pane container. Composes D3Graph, NodeDetailPopup, and
//          SequenceBar. Manages which node popup is open.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useMemo, useRef } from 'react';
import type { AuthSession, GraphCandidate, GraphData, GraphNode, GraphViewState, SelectedNode, WorkflowProgress } from '../../types';
import { useGraph } from '../../hooks/useGraph';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { D3Graph } from './D3Graph';
import { HiddenGraphEvaluator } from './HiddenGraphEvaluator';
import { GlossaryDrawer } from './GlossaryDrawer';
import { NodeDetailPopup } from './NodeDetailPopup';
import { SequenceBar } from './SequenceBar';
import { updateThreadGraph } from '../../services/api';

interface GraphCanvasProps {
  graphData: GraphData | null;
  animateSequence: boolean;
  authSession: AuthSession | null;
  activeThreadId: string | null;
  onNodeClick: (node: GraphNode) => void;
  onTellMeMore: (node: GraphNode) => void;
  onExpandGraph: (node: GraphNode) => void;
  selectedNode: SelectedNode | null;
  onClosePopup: () => void;
  sourceTexts: string[];
  isBuilding?: boolean;
  workflowProgress?: WorkflowProgress[];
  graphCandidate?: GraphCandidate | null;
}

function sameGraphViewState(a: GraphViewState | null | undefined, b: GraphViewState | null | undefined): boolean {
  if (!a || !b) return a === b;
  if (a.viewport.x !== b.viewport.x || a.viewport.y !== b.viewport.y || a.viewport.k !== b.viewport.k) {
    return false;
  }
  const aEntries = Object.entries(a.nodePositions);
  const bEntries = Object.entries(b.nodePositions);
  if (aEntries.length !== bEntries.length) return false;
  return aEntries.every(([nodeId, pos]) => {
    const other = b.nodePositions[nodeId];
    return !!other && other.x === pos.x && other.y === pos.y;
  });
}

export function GraphCanvas({
  graphData,
  animateSequence,
  authSession,
  activeThreadId,
  onNodeClick,
  onTellMeMore,
  onExpandGraph,
  selectedNode,
  onClosePopup,
  sourceTexts,
  isBuilding = false,
  workflowProgress = [],
  graphCandidate = null,
}: GraphCanvasProps) {
  const { currentStep, totalSteps, hasSequence, activeNodeIds, stepDescription, goToStep } = useGraph(graphData, animateSequence);
  const [sequenceDismissal, setSequenceDismissal] = useState<{ key: string; dismissed: boolean } | null>(null);
  const [viewStateCache, setViewStateCache] = useState<Record<string, GraphViewState>>({});
  const [pendingPersistViewState, setPendingPersistViewState] = useState<GraphViewState | null>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const [evaluationViewport, setEvaluationViewport] = useState({ width: 760, height: 500 });
  const graphContentKey = useMemo(() => graphStructureKey(graphData), [graphData]);
  const sequenceDismissed = sequenceDismissal?.key === graphContentKey && sequenceDismissal.dismissed;
  const graphViewKey = useMemo(() => {
    if (!graphData || !activeThreadId) return null;
    return [
      activeThreadId,
      graphData.version ?? '',
      graphData.graph_type,
      graphData.title,
      graphData.nodes.map((node) => `${node.id}:${node.label}:${node.type}:${node.tier ?? ''}:${node.lane ?? ''}`).join('|'),
      graphData.edges.map((edge) => `${edge.source}->${edge.target}:${edge.label}:${edge.sync}`).join('|'),
      (graphData.groups ?? []).map((group) => `${group.id}:${group.nodeIds.join(',')}`).join('|'),
      graphData.sequence.map((step) => `${step.step}:${step.nodes.join(',')}`).join('|'),
    ].join('::');
  }, [activeThreadId, graphData]);
  const persistedViewState = graphViewKey ? viewStateCache[graphViewKey] ?? graphData?.view_state ?? null : null;

  useEffect(() => {
    if (!graphCandidate || !canvasHostRef.current) return;
    const rect = canvasHostRef.current.getBoundingClientRect();
    if (rect.width < 240 || rect.height < 240) return;
    setEvaluationViewport({
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    });
  }, [graphCandidate]);

  useEffect(() => {
    if (!authSession || !activeThreadId || !graphData || !pendingPersistViewState) {
      return;
    }

    const timer = window.setTimeout(() => {
      void updateThreadGraph(authSession, activeThreadId, {
        ...graphData,
        view_state: pendingPersistViewState,
      }).catch((error) => {
        console.error('[graph] Failed to persist graph view state:', error);
      });
    }, 400);

    return () => {
      window.clearTimeout(timer);
    };
  }, [activeThreadId, authSession, graphData, pendingPersistViewState]);

  if (!graphData) {
    const latest = workflowProgress.at(-1);
    return (
      <>
      <div ref={canvasHostRef} style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a0f1a',
        color: '#8b949e',
        fontSize: '0.8rem',
        flexDirection: 'column',
        gap: '1.1rem',
        padding: '2rem',
      }}>
        {isBuilding ? (
          <>
            <div style={{ position: 'relative', width: 'min(440px, 88%)', height: 180 }}>
              {[0, 1, 2].map(column => (
                <div key={column} style={{
                  position: 'absolute',
                  left: `${column * 37}%`,
                  top: `${26 + (column % 2) * 42}px`,
                  width: '26%',
                  height: 58,
                  border: '1px solid rgba(96,165,250,0.18)',
                  borderRadius: 8,
                  background: 'linear-gradient(110deg, rgba(22,27,34,0.8) 20%, rgba(49,60,78,0.55) 45%, rgba(22,27,34,0.8) 70%)',
                  backgroundSize: '240% 100%',
                  animation: 'blueprintShimmer 2.2s ease-in-out infinite',
                }} />
              ))}
              <div style={{ position: 'absolute', left: '26%', top: 56, width: '11%', height: 1, background: 'rgba(96,165,250,0.22)' }} />
              <div style={{ position: 'absolute', left: '63%', top: 78, width: '11%', height: 1, background: 'rgba(96,165,250,0.22)' }} />
            </div>
            <div style={{ textAlign: 'center', maxWidth: 460 }}>
              <div style={{ color: '#c9d1d9', fontWeight: 600, marginBottom: 5 }}>
                {latest?.title ?? 'Preparing the architecture workspace'}
              </div>
              <div style={{ color: '#6e7681', lineHeight: 1.55 }}>
                {latest?.detail ?? 'The design will appear after its structure and real browser layout pass review.'}
              </div>
            </div>
          </>
        ) : 'Graph will appear here'}
      </div>
      <HiddenGraphEvaluator candidate={graphCandidate} viewport={evaluationViewport} />
      </>
    );
  }

  return (
    <>
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {/* Graph title */}
      <div style={{
        padding: '0.5rem 1rem',
        fontSize: '0.75rem',
        color: '#6e7681',
        borderBottom: '1px solid #21262d',
        background: '#0d1117',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
      }}>
        <span style={{ color: '#a78bfa' }}>◈</span>
        <span style={{ color: '#8b949e' }}>{graphData.title}</span>
        <span style={{ color: '#30363d' }}>·</span>
        <span>{graphData.nodes.length}n · {graphData.edges.length}e</span>

        {/* Re-open sequence bar when dismissed */}
        {hasSequence && sequenceDismissed && (
          <button
            onClick={() => setSequenceDismissal({ key: graphContentKey, dismissed: false })}
            title="Show walkthrough steps"
            style={{
              marginLeft: 'auto',
              display: 'flex', alignItems: 'center', gap: '0.3rem',
              background: 'rgba(167,139,250,0.08)',
              border: '1px solid rgba(167,139,250,0.2)',
              borderRadius: '5px',
              color: '#a78bfa',
              fontSize: '0.65rem',
              cursor: 'pointer',
              padding: '2px 7px',
              whiteSpace: 'nowrap',
            }}
          >
            ▶ {totalSteps} steps
          </button>
        )}
      </div>

      {/* D3 canvas */}
      <div ref={canvasHostRef} style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <div style={{ width: '100%', height: '100%', opacity: isBuilding ? 0.56 : 1, transition: 'opacity 180ms ease' }}>
          <D3Graph
            graphData={graphData}
            currentStep={currentStep}
            activeNodeIds={activeNodeIds}
            onNodeClick={onNodeClick}
            initialViewState={persistedViewState ?? undefined}
            onViewStateChange={(viewState) => {
              if (!graphViewKey) return;
              const existingViewState = viewStateCache[graphViewKey] ?? graphData.view_state ?? null;
              if (sameGraphViewState(existingViewState, viewState)) {
                return;
              }
              setViewStateCache(prev => ({ ...prev, [graphViewKey]: viewState }));
              setPendingPersistViewState(viewState);
            }}
          />
        </div>

        {isBuilding && (
          <div style={{
            position: 'absolute',
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '0.38rem 0.7rem',
            borderRadius: 999,
            border: '1px solid rgba(167,139,250,0.25)',
            background: 'rgba(10,14,26,0.88)',
            color: '#c4b5fd',
            fontSize: '0.66rem',
            zIndex: 20,
            whiteSpace: 'nowrap',
          }}>
            Revising privately · current approved diagram stays visible
          </div>
        )}

        {/* Node detail popup — resolve live node from graphData so enrichment
            updates (node_detail events) are reflected without a re-click */}
        {selectedNode && (
          <NodeDetailPopup
            node={graphData.nodes.find(n => n.id === selectedNode.node.id) ?? selectedNode.node}
            edges={graphData.edges}
            onClose={onClosePopup}
            onTellMeMore={onTellMeMore}
            onExpandGraph={onExpandGraph}
          />
        )}

        <GlossaryDrawer
          graphData={graphData}
          sourceTexts={sourceTexts}
          bottomOffset={hasSequence ? '4.75rem' : '1rem'}
        />
      </div>

      {/* Sequence bar (only when there are steps and not dismissed) */}
      {hasSequence && !sequenceDismissed && (
        <SequenceBar
          currentStep={currentStep}
          totalSteps={totalSteps}
          stepDescription={stepDescription}
          onStepChange={goToStep}
          onDismiss={() => {
            goToStep(-1);
            setSequenceDismissal({ key: graphContentKey, dismissed: true });
          }}
        />
      )}
    </div>
    <HiddenGraphEvaluator candidate={graphCandidate} viewport={evaluationViewport} />
    </>
  );
}
