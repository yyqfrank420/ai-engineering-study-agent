// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/index.tsx
// Purpose: Graph pane container. Composes D3Graph, NodeDetailPopup, and
//          SequenceBar. Manages which node popup is open.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useMemo } from 'react';
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
  if (a.layoutVersion !== b.layoutVersion) return false;
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
      graphData.edges.map((edge) => `${edge.source}->${edge.target}:${edge.label}:${edge.sync}:${edge.flow ?? ''}`).join('|'),
      (graphData.groups ?? []).map((group) => `${group.id}:${group.kind ?? ''}:${group.nodeIds.join(',')}`).join('|'),
      graphData.sequence.map((step) => `${step.step}:${step.nodes.join(',')}`).join('|'),
    ].join('::');
  }, [activeThreadId, graphData]);
  const persistedViewState = graphViewKey ? viewStateCache[graphViewKey] ?? graphData?.view_state ?? null : null;

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
      <div style={{
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
      <HiddenGraphEvaluator candidate={graphCandidate} />
      </>
    );
  }

  const [title, subtitle] = splitGraphTitle(graphData.title);

  return (
    <>
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      {/* Graph title */}
      <div style={{
        padding: '0.65rem 1rem',
        fontSize: '0.75rem',
        color: '#6e7681',
        borderBottom: '1px solid #21262d',
        background: 'linear-gradient(180deg, rgba(16,22,34,0.98), rgba(10,15,26,0.98))',
        display: 'flex',
        alignItems: 'center',
        columnGap: '0.65rem',
        rowGap: '0.38rem',
        flexWrap: 'wrap',
        minHeight: 48,
      }}>
        <span style={{ color: '#a78bfa', fontSize: '0.88rem' }}>◈</span>
        <div title={graphData.title} style={{
          flex: '1 1 300px',
          minWidth: 0,
          lineHeight: 1.25,
        }}>
          <div style={{ color: '#d8dee9', fontWeight: 680, overflowWrap: 'anywhere' }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ color: '#8490a0', fontSize: '0.62rem', marginTop: 2, overflowWrap: 'anywhere' }}>
              {subtitle}
            </div>
          )}
        </div>
        <span style={{
          color: '#8490a0',
          fontSize: '0.62rem',
          padding: '0.18rem 0.45rem',
          borderRadius: 999,
          border: '1px solid rgba(148,163,184,0.16)',
          background: 'rgba(148,163,184,0.06)',
          flexShrink: 0,
          whiteSpace: 'nowrap',
        }}>
          {graphData.nodes.length} components
          {(graphData.groups?.length ?? 0) > 0 ? ` · ${graphData.groups!.length} zones` : ''}
        </span>

        {graphData.design_origin === 'applied' && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.65rem',
            marginLeft: 'auto',
            flexShrink: 0,
          }}>
            <FlowLegend color="#3b82f6" label="Runtime" />
            <FlowLegend color="#94a3b8" label="Control" dashed />
            <FlowLegend color="#a78bfa" label="Feedback" dashed />
          </div>
        )}

        {/* Re-open sequence bar when dismissed */}
        {hasSequence && sequenceDismissed && (
          <button
            onClick={() => setSequenceDismissal({ key: graphContentKey, dismissed: false })}
            title="Show walkthrough steps"
            style={{
              marginLeft: graphData.design_origin === 'applied' ? 0 : 'auto',
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
    <HiddenGraphEvaluator candidate={graphCandidate} />
    </>
  );
}

function FlowLegend({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.32rem', color: '#7d8795', fontSize: '0.58rem' }}>
      <span style={{
        width: 18,
        height: 0,
        borderTop: `1.5px ${dashed ? 'dashed' : 'solid'} ${color}`,
      }} />
      {label}
    </span>
  );
}

function splitGraphTitle(value: string): [string, string | null] {
  const separator = value.match(/\s(?:—|–)\s|:\s/);
  if (!separator?.index) return [value, null];
  const title = value.slice(0, separator.index).trim();
  const subtitle = value.slice(separator.index + separator[0].length).trim();
  return title && subtitle ? [title, subtitle] : [value, null];
}
