import type { GraphData, GraphEdge, GraphNode } from '../../../types';


function node(
  id: string,
  label: string,
  type: GraphNode['type'],
  technology: string,
  description: string,
  lane: GraphNode['lane'] = 'main',
): GraphNode {
  return {
    id,
    label,
    type,
    lane,
    technology,
    description,
    detail: null,
    layer: 'architecture',
    design_origin: 'applied',
  };
}


function edge(
  source: string,
  target: string,
  label: string,
  technology: string = 'Validated runtime contract',
  sync: GraphEdge['sync'] = 'sync',
  flow: NonNullable<GraphEdge['flow']> = 'runtime',
  type?: GraphEdge['type'],
): GraphEdge {
  return {
    source,
    target,
    label,
    flow,
    type,
    technology,
    sync,
    description: label,
    edge_id: `applied:${source}__${label.replaceAll(' ', '_')}__${target}`,
    relation: label.replaceAll(' ', '_'),
  };
}


// Exact rendered graph submitted to the private browser in paid diagnostic
// 31825436257. The node technology strings are preserved because they affect
// the measured SVG bounds.
export const modelServingPaidCandidate: GraphData = {
  graph_type: 'architecture',
  design_origin: 'applied',
  version: '2ec29d89-fe85-44da-afda-53c16d9a1543',
  resolved_complexity: 'prototype',
  title: 'Model serving with monitoring',
  nodes: [
    node('n1', 'Client', 'client', 'Authenticated client', 'Submits prediction requests and receives inference results.'),
    node('n2', 'API gateway', 'gateway', 'Policy-enforcing gateway', 'Authenticates, validates, and routes inference requests; returns predictions or validation errors.'),
    node('n3', 'Inference service', 'service', 'Bounded application service', 'Loads the active model version and serves predictions; reports serving health.'),
    node('n4', 'Model registry', 'datastore', 'Versioned durable store', 'Authoritative store of versioned model artifacts and approval status.'),
    node('n5', 'Prediction log store', 'datastore', 'Versioned durable store', 'Durable record of requests, predictions, and model versions for later analysis.'),
    node('n6', 'Deployment controller', 'control', 'Deterministic control plane', 'Rolls out approved model versions to the inference service and executes rollback on demand.', 'bottom'),
    node('n7', 'Monitoring service', 'service', 'Bounded application service', 'Computes drift, latency, and error-rate signals from logged inference telemetry.', 'bottom'),
    node('n8', 'Metrics store', 'datastore', 'Versioned durable store', 'Authoritative time-series store for model quality and serving metrics.', 'bottom'),
    node('n9', 'Alert evaluator', 'control', 'Deterministic control plane', 'Compares metric windows against thresholds and raises degradation alerts.', 'bottom'),
    node('n10', 'On-call operator', 'external', 'External system boundary', 'Receives degradation alerts and can approve corrective action.'),
  ],
  edges: [
    edge('n1', 'n2', 'sends inference request'),
    edge('n2', 'n3', 'routes prediction request'),
    edge('n3', 'n4', 'loads model artifact'),
    edge('n3', 'n5', 'writes inference records', 'Validated runtime contract', 'async'),
    edge('n3', 'n6', 'reports serving health', 'Versioned feedback event', 'sync', 'feedback', 'loop'),
    edge('n5', 'n7', 'ships prediction telemetry', 'Validated runtime contract', 'async'),
    edge('n7', 'n8', 'writes drift and latency metrics', 'Validated runtime contract', 'async'),
    edge('n7', 'n9', 'evaluates quality thresholds', 'Typed control signal', 'sync', 'control'),
    edge('n9', 'n10', 'sends degradation alert', 'Typed control signal', 'async', 'control'),
    edge('n2', 'n1', 'returns prediction response'),
    edge('n3', 'n2', 'returns prediction result'),
    edge('n6', 'n4', 'fetches approved model artifact', 'Immutable deployment control', 'sync', 'deployment'),
    edge('n6', 'n3', 'deploys model version', 'Immutable deployment control', 'sync', 'deployment'),
    edge('n7', 'n6', 'triggers rollback on drift', 'Typed control signal', 'async', 'control'),
    edge('n8', 'n9', 'supplies metric aggregates'),
  ],
  groups: [
    {
      id: 'group_1',
      label: 'Product runtime',
      kind: 'runtime',
      nodeIds: ['n1', 'n2', 'n3'],
    },
    {
      id: 'group_2',
      label: 'Model platform',
      kind: 'data',
      nodeIds: ['n4', 'n5'],
    },
    {
      id: 'group_3',
      label: 'Serving operations',
      kind: 'operations',
      nodeIds: ['n6'],
    },
    {
      id: 'group_4',
      label: 'Observability',
      kind: 'operations',
      nodeIds: ['n7', 'n8', 'n9'],
    },
    {
      id: 'group_5',
      label: 'External operators',
      kind: 'external',
      nodeIds: ['n10'],
    },
  ],
  sequence: [
    { step: 1, nodes: ['n1'], description: 'Submits prediction requests and receives inference results.' },
    { step: 2, nodes: ['n2'], description: 'sends inference request' },
    { step: 3, nodes: ['n3'], description: 'routes prediction request' },
    { step: 4, nodes: ['n4', 'n5'], description: 'loads model artifact; writes inference records' },
  ],
  assumptions: [],
};
