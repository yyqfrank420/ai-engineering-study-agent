// ─────────────────────────────────────────────────────────────────────────────
// File: frontend/src/utils/graphStructureKey.ts
// Purpose: Deterministic string key derived from graph structure. Used to detect
//          when a graph's topology/content has changed and a re-render or
//          re-animation is needed, ignoring transient fields like positions.
// Language: TypeScript
// Connects to: types/index.ts
// Consumed by: components/GraphCanvas/D3Graph.tsx, hooks/useAgentStream.ts
// Inputs:  GraphData object (or null)
// Outputs: stable JSON string key
// ─────────────────────────────────────────────────────────────────────────────

import type { GraphData } from '../types';

/**
 * Produce a stable string key from the structural parts of a GraphData object.
 * Two graphs with the same key are identical in topology, labels, and metadata
 * — only layout / transient state may differ.
 *
 * Accepts `null` for the hook's initial state (returns `'null'`).
 * When `graph.version` is present it short-circuits to avoid serialisation.
 */
export function graphStructureKey(graph: GraphData | null): string {
  if (!graph) return 'null';
  if (graph.version) return `version:${graph.version}`;
  return JSON.stringify({
    title: graph.title,
    graph_type: graph.graph_type,
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      label: node.label,
      type: node.type,
      technology: node.technology,
      description: node.description,
      tier: node.tier ?? null,
      lane: node.lane ?? null,
    })),
    edges: graph.edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      label: edge.label,
      technology: edge.technology,
      sync: edge.sync,
      description: edge.description,
    })),
    sequence: graph.sequence.map((step) => ({
      step: step.step,
      nodes: step.nodes,
      description: step.description,
    })),
    groups: (graph.groups ?? []).map((group) => ({
      id: group.id,
      label: group.label,
      nodeIds: group.nodeIds,
    })),
  });
}
