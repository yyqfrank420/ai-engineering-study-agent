// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/index.tsx
// Purpose: Graph pane container. Composes D3Graph, NodeDetailPopup, and
//          SequenceBar. Manages which node popup is open.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useMemo, useRef } from 'react';
import type { AuthSession, GraphData, GraphNode, GraphViewState, SelectedNode } from '../../types';
import { useGraph } from '../../hooks/useGraph';
import { graphStructureKey } from '../../utils/graphStructureKey';
import { D3Graph } from './D3Graph';
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
}: GraphCanvasProps) {
  const { currentStep, totalSteps, hasSequence, activeNodeIds, stepDescription, goToStep } = useGraph(graphData, animateSequence);
  const [sequenceDismissed, setSequenceDismissed] = useState(false);
  const viewStateCacheRef = useRef(new Map<string, GraphViewState>());
  const [pendingPersistViewState, setPendingPersistViewState] = useState<GraphViewState | null>(null);
  const graphContentKey = useMemo(() => graphStructureKey(graphData), [graphData]);
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
  const persistedViewState = graphViewKey ? viewStateCacheRef.current.get(graphViewKey) ?? graphData?.view_state ?? null : null;

  // Reset dismissed state only when the graph structure changes, not when
  // async node-detail enrichment swaps the object reference.
  useEffect(() => { setSequenceDismissed(false); }, [graphContentKey]);

  useEffect(() => {
    if (!graphViewKey || !graphData?.view_state) return;
    if (!viewStateCacheRef.current.has(graphViewKey)) {
      viewStateCacheRef.current.set(graphViewKey, graphData.view_state);
    }
  }, [graphData, graphViewKey]);

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
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a0f1a',
        color: '#21262d',
        fontSize: '0.875rem',
      }}>
        Graph will appear here
      </div>
    );
  }

  return (
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
            onClick={() => setSequenceDismissed(false)}
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
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <D3Graph
          graphData={graphData}
          currentStep={currentStep}
          activeNodeIds={activeNodeIds}
          onNodeClick={onNodeClick}
          initialViewState={persistedViewState ?? undefined}
          onViewStateChange={(viewState) => {
            if (!graphViewKey) return;
            const existingViewState = viewStateCacheRef.current.get(graphViewKey) ?? graphData.view_state ?? null;
            if (sameGraphViewState(existingViewState, viewState)) {
              return;
            }
            viewStateCacheRef.current.set(graphViewKey, viewState);
            setPendingPersistViewState(viewState);
          }}
        />

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
          onDismiss={() => { goToStep(-1); setSequenceDismissed(true); }}
        />
      )}
    </div>
  );
}
