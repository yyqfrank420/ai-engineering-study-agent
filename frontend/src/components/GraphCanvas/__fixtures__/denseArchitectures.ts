import type { GraphData, GraphEdge, GraphNode } from '../../../types';

// Captured topology shapes used as deterministic renderer regressions. Their
// prose is illustrative; tests assert structural and visual behavior.
type NodeSeed = [string, string, string, GraphNode['type'], GraphNode['lane']?];
type EdgeSeed = [
  string,
  string,
  string,
  NonNullable<GraphEdge['flow']>?,
  GraphEdge['type']?,
];

function nodes(seeds: NodeSeed[]): GraphNode[] {
  return seeds.map(([id, label, technology, type, lane = 'main']) => ({
    id,
    label,
    technology,
    type,
    lane,
    tier: type === 'client' ? 'public' : 'private',
    description: `${label} owns its named responsibility in this captured architecture fixture.`,
    detail: null,
    design_origin: 'applied',
  }));
}

function edges(seeds: EdgeSeed[]): GraphEdge[] {
  return seeds.map(([source, target, label, flow = 'runtime', type]) => ({
    source,
    target,
    label,
    flow,
    type,
    technology: flow === 'control' ? 'Typed policy command' : 'Typed domain event',
    sync: flow === 'feedback' ? 'async' : 'sync',
    description: `${label} from ${source} to ${target}.`,
  }));
}

export const growthMarketingDenseGraph: GraphData = {
  graph_type: 'architecture',
  design_origin: 'applied',
  title: 'Supervisor-Orchestrated Multi-Agent Growth Marketing System',
  nodes: nodes([
    ['marketer_console', 'Marketer Console', 'Web UI for campaign briefs', 'client'],
    ['supervisor_agent', 'Supervisor Agent', 'Planning orchestrator (strong LLM)', 'control'],
    ['segmentation_agent', 'Segmentation Agent', 'Consent-aware audience model', 'service'],
    ['content_agent', 'Content Agent', 'Creative and copy generation model', 'service'],
    ['policy_validator', 'Policy Validator', 'Rule-based and LLM policy checker', 'decision'],
    ['approval_console', 'Approval Console', 'Human-in-loop sign-off UI', 'control'],
    ['dispatch_executor', 'Dispatch Executor', 'Idempotent channel API client', 'service'],
    ['campaign_warehouse', 'Campaign Warehouse', 'Governed SQL data warehouse', 'datastore'],
    ['feedback_analyzer', 'Feedback Analyzer', 'Event dedup and KPI aggregation engine', 'service'],
    ['observability_audit', 'Observability & Audit', 'Tracing, drift, and audit-log platform', 'control', 'bottom'],
  ]),
  edges: edges([
    ['marketer_console', 'supervisor_agent', 'submit campaign brief'],
    ['supervisor_agent', 'segmentation_agent', 'dispatch segmentation task'],
    ['supervisor_agent', 'content_agent', 'dispatch content-generation task'],
    ['segmentation_agent', 'campaign_warehouse', 'query consented audience'],
    ['content_agent', 'campaign_warehouse', 'fetch creative performance'],
    ['segmentation_agent', 'supervisor_agent', 'return audience segment'],
    ['content_agent', 'supervisor_agent', 'return draft creative'],
    ['supervisor_agent', 'policy_validator', 'submit assembled plan'],
    ['policy_validator', 'approval_console', 'escalate ambiguous action', 'control'],
    ['policy_validator', 'dispatch_executor', 'auto-clear low-risk plan'],
    ['approval_console', 'dispatch_executor', 'release approved action'],
    ['approval_console', 'supervisor_agent', 'request plan revision', 'control'],
    ['dispatch_executor', 'campaign_warehouse', 'write execution record'],
    ['dispatch_executor', 'feedback_analyzer', 'emit performance events'],
    ['feedback_analyzer', 'campaign_warehouse', 'store deduped outcomes'],
    ['feedback_analyzer', 'supervisor_agent', 'feed optimization signal', 'feedback', 'loop'],
    ['dispatch_executor', 'observability_audit', 'stream execution trace', 'control'],
    ['policy_validator', 'observability_audit', 'log validation decisions', 'control'],
    ['observability_audit', 'supervisor_agent', 'alert on drift', 'control'],
  ]),
  groups: [
    { id: 'orchestration', label: 'Planning & Specialized Agents', nodeIds: ['marketer_console', 'supervisor_agent', 'segmentation_agent', 'content_agent'], kind: 'runtime' },
    { id: 'governance', label: 'Policy & Human Approval', nodeIds: ['policy_validator', 'approval_console'], kind: 'runtime' },
    { id: 'execution', label: 'Execution & Canonical Data', nodeIds: ['dispatch_executor', 'campaign_warehouse'], kind: 'data' },
    { id: 'feedback', label: 'Measurement & Feedback', nodeIds: ['feedback_analyzer'], kind: 'runtime' },
    { id: 'operations', label: 'Cross-Cutting Operations', nodeIds: ['observability_audit'], kind: 'operations' },
  ],
  sequence: [
    { step: 1, nodes: ['marketer_console', 'supervisor_agent'], description: 'Interpret the campaign brief.' },
    { step: 2, nodes: ['segmentation_agent', 'content_agent', 'campaign_warehouse'], description: 'Build audience and creative candidates.' },
    { step: 3, nodes: ['supervisor_agent', 'policy_validator'], description: 'Validate the assembled plan.' },
    { step: 4, nodes: ['policy_validator', 'approval_console'], description: 'Escalate risky action.' },
    { step: 5, nodes: ['dispatch_executor', 'campaign_warehouse'], description: 'Execute idempotently.' },
    { step: 6, nodes: ['feedback_analyzer', 'supervisor_agent'], description: 'Close the measured feedback loop.' },
    { step: 7, nodes: ['observability_audit'], description: 'Monitor every boundary.' },
  ],
};

export const customerSupportDenseGraph: GraphData = {
  graph_type: 'architecture',
  design_origin: 'applied',
  title: 'Customer Support Chatbot: Grounded Response, Human Escalation, and Approved Account Actions',
  nodes: nodes([
    ['customer_channel', 'Customer Chat Channel', 'Web and app messaging widget', 'client'],
    ['orchestrator', 'Dialogue Orchestrator', 'Conversation orchestration service', 'service'],
    ['knowledge_retriever', 'Support KB Retriever', 'Grounded retrieval over policy and KB corpus', 'service'],
    ['memory_store', 'Session & Preference Memory', 'Ephemeral session cache and reviewed fact store', 'datastore'],
    ['response_generator', 'Response Generator', 'LLM generation with confidence scoring', 'service'],
    ['escalation_router', 'Escalation Decision', 'Confidence and risk routing policy', 'decision'],
    ['agent_console', 'Human Agent Console', 'Agent handoff and context transfer UI', 'service'],
    ['action_proposal_service', 'Action Proposal Service', 'Write-intent proposal API without execution rights', 'control'],
    ['sor_executor', 'Account/Order Executor', 'Idempotent system-of-record write gateway', 'gateway'],
    ['eval_observability', 'Eval & Observability Hub', 'Evaluation, telemetry, and rollout control', 'service', 'bottom'],
  ]),
  edges: edges([
    ['customer_channel', 'orchestrator', 'submit customer message'],
    ['orchestrator', 'knowledge_retriever', 'request grounding context'],
    ['orchestrator', 'memory_store', 'read session state'],
    ['knowledge_retriever', 'response_generator', 'pass sanitized context'],
    ['memory_store', 'response_generator', 'supply reviewed facts'],
    ['response_generator', 'escalation_router', 'deliver draft and confidence'],
    ['escalation_router', 'customer_channel', 'send direct answer'],
    ['escalation_router', 'agent_console', 'escalate with context'],
    ['escalation_router', 'action_proposal_service', 'flag action request'],
    ['action_proposal_service', 'agent_console', 'request explicit approval', 'control'],
    ['agent_console', 'sor_executor', 'approve action execution', 'control'],
    ['sor_executor', 'customer_channel', 'confirm resolution status'],
    ['agent_console', 'customer_channel', 'send agent resolution'],
    ['customer_channel', 'eval_observability', 'emit CSAT signal', 'feedback'],
    ['sor_executor', 'eval_observability', 'report write outcome', 'feedback'],
    ['agent_console', 'eval_observability', 'report correction', 'feedback'],
    ['eval_observability', 'orchestrator', 'push reviewed thresholds', 'feedback', 'loop'],
    ['eval_observability', 'escalation_router', 'trigger kill switch', 'control'],
  ]),
  groups: [
    { id: 'conversation', label: 'Conversation Runtime', nodeIds: ['customer_channel', 'orchestrator', 'response_generator', 'escalation_router', 'agent_console'], kind: 'runtime' },
    { id: 'knowledge', label: 'Knowledge & Memory', nodeIds: ['knowledge_retriever', 'memory_store'], kind: 'data' },
    { id: 'actions', label: 'Action & Approval Boundary', nodeIds: ['action_proposal_service', 'sor_executor'], kind: 'runtime' },
    { id: 'operations', label: 'Evaluation & Operations', nodeIds: ['eval_observability'], kind: 'operations' },
  ],
  sequence: [
    { step: 1, nodes: ['customer_channel', 'orchestrator'], description: 'Open the session.' },
    { step: 2, nodes: ['knowledge_retriever', 'memory_store'], description: 'Gather trusted context.' },
    { step: 3, nodes: ['response_generator', 'escalation_router'], description: 'Draft and route.' },
    { step: 4, nodes: ['customer_channel', 'agent_console'], description: 'Answer or escalate.' },
    { step: 5, nodes: ['action_proposal_service', 'agent_console'], description: 'Approve consequential writes.' },
    { step: 6, nodes: ['sor_executor'], description: 'Execute safely.' },
    { step: 7, nodes: ['eval_observability', 'orchestrator', 'escalation_router'], description: 'Evaluate and control rollout.' },
  ],
};
