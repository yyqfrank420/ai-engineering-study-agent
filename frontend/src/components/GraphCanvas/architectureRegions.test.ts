import { describe, expect, it } from 'vitest';

import type { GraphGroup, GraphNode, NodeType } from '../../types';
import { architectureRegions, regionRole } from './architectureRegions';

function node(id: string, label: string, type: NodeType, lane: GraphNode['lane'] = 'main'): GraphNode {
  return {
    id,
    label,
    type,
    lane,
    technology: '',
    description: '',
    detail: null,
  };
}

describe('architecture region roles', () => {
  it('keeps main-lane business metrics stores with other data stores', () => {
    const stores = [
      node('approval', 'Approval lifecycle store', 'datastore'),
      node('metrics', 'Campaign metrics store', 'datastore'),
    ];
    const genericData: GraphGroup = {
      id: 'data', label: 'Data', kind: 'data', nodeIds: stores.map(store => store.id),
    };

    expect(regionRole(stores)).toBe('datastore');
    expect(architectureRegions(stores, [genericData])).toEqual([{
      ...genericData,
      id: 'data:datastore',
      label: 'Data stores',
    }]);
  });

  it('keeps main-lane metrics services with other services', () => {
    const services = [
      node('api', 'Campaign API', 'service'),
      node('metrics', 'Business metrics service', 'service'),
    ];
    const runtime: GraphGroup = {
      id: 'runtime', label: 'Runtime', kind: 'runtime', nodeIds: services.map(service => service.id),
    };

    expect(regionRole(services)).toBe('service');
    expect(architectureRegions(services, [runtime])).toEqual([{
      ...runtime,
      id: 'runtime:service',
      label: 'Application services',
    }]);
  });

  it('places a named human review group with its client even when both members have bottom lanes', () => {
    const reviewNodes = [
      node('workspace', 'Reviewer workspace', 'client', 'bottom'),
      node('review', 'Review service', 'service', 'bottom'),
    ];
    const group: GraphGroup = {
      id: 'human_review', label: 'Human review', kind: 'operations', nodeIds: reviewNodes.map(item => item.id),
    };

    expect(architectureRegions(reviewNodes, [group])).toEqual([group]);
    expect(regionRole(reviewNodes)).toBe('client');
    expect(regionRole(reviewNodes.map(item => ({ ...item, lane: 'main' })))).toBe('client');
  });

  it.each(['Audit log', 'Logs', 'Logging', 'Monitoring', 'Telemetry'])(
    'keeps explicit support label %s in the support role',
    label => {
      expect(regionRole([node('support', label, 'datastore')])).toBe('support');
    },
  );

  it('keeps bottom-lane metrics in the existing support group', () => {
    const metrics = node('metrics', 'Delivery Metrics', 'service', 'bottom');
    const operations: GraphGroup = {
      id: 'operations', label: 'Operations', kind: 'operations', nodeIds: [metrics.id],
    };

    expect(regionRole([metrics])).toBe('support');
    expect(architectureRegions([metrics], [operations])).toEqual([{
      ...operations,
      id: 'operations:support',
      label: 'Logs and monitoring',
    }]);
  });

  it('leaves other all-bottom mixed regions in the support role', () => {
    expect(regionRole([
      node('client', 'Operator UI', 'client', 'bottom'),
      node('ledger', 'Audit ledger', 'datastore', 'bottom'),
    ])).toBe('support');
  });
});
