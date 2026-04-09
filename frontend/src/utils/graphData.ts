import type { GraphData, GraphNode } from '../types';

const CONTROL_HINT = /\b(access control|control de acceso|policy engine|motor de politicas|motor de políticas|policy filter|authorization|authorizes?|authorized|authz|autoriz(a|ación|acion|ado|ados)?|guardrail|guardrails|validator|validat(es|or|ion)?|moderation|safety filter|safety check|content filter|permission(s)?|permisos?|rbac|abac|seguridad|proteccion|protección)\b/i;

function shouldNormalizeToControl(node: GraphNode): boolean {
  if (node.type !== 'decision') return false;
  const haystack = [node.label, node.technology, node.description].filter(Boolean).join(' ');
  return CONTROL_HINT.test(haystack);
}

export function normalizeGraphData(graphData: GraphData | null): GraphData | null {
  if (!graphData) return null;

  let changed = false;
  const nodes = graphData.nodes.map((node) => {
    if (!shouldNormalizeToControl(node)) return node;
    changed = true;
    return { ...node, type: 'control' as const };
  });

  return changed ? { ...graphData, nodes } : graphData;
}
