import type { GraphGroup, GraphNode } from '../../types';

type RegionRole = 'client' | 'service' | 'datastore' | 'support' | 'external';

const REGION_LABELS: Record<RegionRole, string> = {
  client: 'User interfaces',
  service: 'Application services',
  datastore: 'Data stores',
  support: 'Logs and monitoring',
  external: 'External systems',
};

function nodeRole(node: GraphNode): RegionRole {
  if (/\b(audit log|logs?|logging|monitoring|telemetry)\b/i.test(node.label)) return 'support';
  if (node.lane === 'bottom' && /\bmetrics\b/i.test(node.label)) return 'support';
  if (node.type === 'client') return 'client';
  if (node.type === 'datastore') return 'datastore';
  if (node.type === 'external') return 'external';
  return 'service';
}

/** Generic model categories are split by concrete roles only in the live presentation. */
export function architectureRegions(nodes: GraphNode[], groups: GraphGroup[]): GraphGroup[] {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const result: GraphGroup[] = [];
  const generic = new Map<RegionRole, GraphGroup>();
  for (const group of groups) {
    if (!/^(runtime|data|operations|external)$/i.test(group.label.trim())) {
      result.push(group);
      continue;
    }
    for (const id of new Set(group.nodeIds)) {
      const node = byId.get(id);
      if (!node) continue;
      const role = nodeRole(node);
      let region = generic.get(role);
      if (!region) {
        region = { ...group, id: `${group.id}:${role}`, label: REGION_LABELS[role], nodeIds: [] };
        generic.set(role, region);
        result.push(region);
      }
      if (!region.nodeIds.includes(id)) region.nodeIds.push(id);
    }
  }
  return result;
}

export function regionRole(nodes: GraphNode[]): RegionRole {
  const roles = nodes.map(nodeRole);
  if (roles.includes('client') && roles.every(role => role === 'client' || role === 'service')) return 'client';
  if (roles.every(role => role === 'support') || nodes.every(node => node.lane === 'bottom')) return 'support';
  if (roles.every(role => role === 'external')) return 'external';
  if (roles.every(role => role === 'datastore')) return 'datastore';
  if (roles.every(role => role === 'client')) return 'client';
  return 'service';
}
