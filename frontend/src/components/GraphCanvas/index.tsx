// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/components/GraphCanvas/index.tsx
// Purpose: Graph pane container. Composes D3Graph, NodeDetailPopup, and
//          SequenceBar. Manages which node popup is open.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react';
import type { GraphData, GraphNode, SelectedNode } from '../../types';
import { useGraph } from '../../hooks/useGraph';
import { D3Graph } from './D3Graph';
import { GlossaryDrawer } from './GlossaryDrawer';
import { NodeDetailPopup } from './NodeDetailPopup';
import { SequenceBar } from './SequenceBar';

interface GraphCanvasProps {
  graphData: GraphData | null;
  animateSequence: boolean;
  onNodeClick: (node: GraphNode) => void;
  onTellMeMore: (node: GraphNode) => void;
  selectedNode: SelectedNode | null;
  onClosePopup: () => void;
  sourceTexts: string[];
}

export function GraphCanvas({
  graphData,
  animateSequence,
  onNodeClick,
  onTellMeMore,
  selectedNode,
  onClosePopup,
  sourceTexts,
}: GraphCanvasProps) {
  const { currentStep, totalSteps, hasSequence, activeNodeIds, stepDescription, goToStep } = useGraph(graphData, animateSequence);
  const [sequenceDismissed, setSequenceDismissed] = useState(false);

  // Reset dismissed state whenever the graph changes (new topic = new sequence)
  useEffect(() => { setSequenceDismissed(false); }, [graphData]);

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
        />

        {/* Node detail popup — resolve live node from graphData so enrichment
            updates (node_detail events) are reflected without a re-click */}
        {selectedNode && (
          <NodeDetailPopup
            node={graphData.nodes.find(n => n.id === selectedNode.node.id) ?? selectedNode.node}
            edges={graphData.edges}
            onClose={onClosePopup}
            onTellMeMore={onTellMeMore}
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
