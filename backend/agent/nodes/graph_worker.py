# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/graph_worker.py
# Purpose: Phase 1 graph worker — decides how to handle the knowledge graph
#          based on the current query and existing graph state.
#
#          Three actions:
#            NO_GRAPH  — query is a follow-up; keep existing graph unchanged
#            replace   — topic has shifted; replace graph entirely
#            update    — same topic; merge new nodes/edges into existing graph
#            new_chat  — topic is unrelated enough that the user should start a new chat
#
#          The model outputs ONLY a JSON object when generating/updating,
#          so parsing is reliable. The backend performs the merge for "update".
# Language: Python
# Connects to: adapters/llm_adapter.py, agent/tools/graph_worker_tools/,
#              agent/state.py, config.py
# Inputs:  AgentState (user_message, graph_data)
# Outputs: AgentState update: graph_data (merged | replaced | None = keep as-is)
# ─────────────────────────────────────────────────────────────────────────────

import json
import uuid

from adapters.llm_adapter import build_telemetry
from agent.state import AgentState, GraphData
from agent.stream_utils import stream_llm
from config import settings

# Complexity hint prefixes prepended to the system prompt when set by the user.
# Each hint overrides the default "auto" behaviour of the graph worker.
_COMPLEXITY_HINTS: dict[str, str] = {
    "low":        "COMPLEXITY: low — 3–5 nodes max. Concept-diagram style. No groups, no networking.",
    "prototype":  "COMPLEXITY: prototype — 5–8 nodes. Basic architecture only. Skip observability.",
    "production": "COMPLEXITY: production — 8–15 nodes. Full AWS-style: all networking, monitoring lane, external services.",
}

_SYSTEM = """<role>
You are the graph planner for the book "AI Engineering" by Chip Huyen.
You build small, faithful graphs that help a beginner understand the retrieved evidence.
</role>

<task>
Decide how to update the knowledge graph shown alongside the chat.
The graph must stay grounded in the retrieved book evidence, not in generic infra patterns.
</task>

<decision_policy>
Pick ONE action:

1. NO_GRAPH
   Use this ONLY when:
   - the user is asking a short follow-up or clarifying question that adds no new structure, AND
   - a meaningful graph already exists that already covers the topic.
   Do NOT use NO_GRAPH just because a brand name or specific product is not in the book.
   If the user asks how to build, replicate, or implement something, map it to the closest
   book concept and build a graph for that.
   Output ONLY the two words: NO_GRAPH

2. "replace"
   The question is about a different concept, architecture, or learning flow,
   but it is still a natural continuation of the current thread.
   Output a brand-new graph that replaces the existing one entirely.

3. "update"
   The question stays on the same topic but adds structure or detail.
   Output ONLY the new nodes and edges to add.

4. "new_chat"
   Use this when ALL of the following are true:
   - a graph already exists
   - the user is asking for a graph / architecture / diagram / expansion
   - the new request is about a clearly unrelated topic, so replacing the current graph would be confusing
   In this case, do NOT redraw over the old graph.
   Output ONLY this JSON object:
   {"action":"new_chat"}
</decision_policy>

<output_contract>
When outputting a graph, respond with ONLY a JSON object:
{
  "action": "replace" | "update" | "new_chat",
  "graph_type": "architecture" | "concept",
  "title": "<2-5 word title>",
  "nodes": [
    {
      "id": "<snake_id>",
      "label": "<MAX 3 words, MAX 20 chars — e.g. 'API Gateway', 'Vector Store', 'LLM Engine'>",
      "type": "<client|service|datastore|gateway|network|external|control|decision>",
      "technology": "<MAX 25 chars — e.g. 'Python / FastAPI', 'FAISS', 'Redis 7', 'vLLM / A100'>",
      "description": "<1 sentence: what this node is responsible for>",
      "tier": "<public|private>",
      "lane": "<bottom — only for cross-cutting observability nodes; omit for all others>"
    }
  ],
  "edges": [
    {
      "source": "<id>",
      "target": "<id>",
      "label": "<2-4 word verb phrase>",
      "technology": "<transport + format: 'HTTPS/JSON', 'gRPC/Protobuf', 'Kafka', 'SQS'>",
      "sync": "<sync|async>",
      "description": "<1 sentence: what data flows here>"
    }
  ],
  "sequence": [{"step": 1, "nodes": ["<id>"], "description": "<one sentence>"}],
  "groups": [
    {"id": "<snake_id>_layer", "label": "<Layer Name>", "nodeIds": ["<id_a>", "<id_b>"]}
  ]
}

For "update": nodes/edges are ONLY the additions — do not duplicate existing ones.
For "replace": include the complete graph.
For "new_chat": return ONLY {"action":"new_chat"} and nothing else.
Sequence is [] unless there is a meaningful process order.
Groups: for architecture graphs with 5+ nodes, define 2–4 named layers that cluster related
nodes. Examples: "Orchestration Layer", "Storage Layer", "Tool Execution Layer",
"Network/Gateway Layer", "Monitoring Layer". Omit groups for concept graphs or small diagrams.

No markdown, no prose, no code fence — only the JSON or NO_GRAPH.
</output_contract>

<grounding_rules>
  - Use the retrieved book evidence as the source of truth.
  - Prefer concepts, components, and relations that are explicitly present in the evidence.
  - If the user is asking how to build, design, compose, customise, replace, self-host,
    open-source, or implement a system, stack, pipeline, or agent, you MUST return a graph.
    Those are design questions, not "NO_GRAPH" follow-ups.
  - If the exact product is out of book but the underlying pattern is in book, graph the pattern.
  - Do NOT invent generic AWS / production architecture components unless the user is clearly
    asking for a system architecture, deployment pipeline, serving topology, or infrastructure flow.
  - Do NOT drift into random enterprise boxes like VPCs, gateways, registries, checkpoints,
    or neuron-layer internals unless the retrieved evidence clearly supports them.
  - If the question is about a method, idea, tradeoff, or technique (for example LoRA, PEFT,
    quantization, reranking, batching, fine-tuning), prefer a "concept" graph.
  - For concept graphs, nodes should be concepts or roles in the learning flow, not random services.
  - Use type "control" for policy/security enforcement nodes such as access control,
    guardrails, validators, filters, moderation, or retrieval authorization.
  - Use type "decision" only for explicit technical choices, routing points, approval gates,
    budgets, tradeoffs, or other checkpoints that steer what happens next.
  - Good control nodes: "Access Control", "Policy Filter", "Input Guardrails",
    "Output Guardrails", "Safety Validator".
  - Good decision nodes: "Gateway Check", "Model Router", "Technical Decision",
    "Approval Gate", "Compute Budget".
  - If the flow has upstream pressures, prefer separate nodes instead of overloading decision:
      - type "external" for outside forces or actors, e.g. "External Factors", attackers,
        regulators, vendor APIs, compliance pressure.
      - a normal concept/service node for internal framing inputs, e.g. "Business Requirements",
        "Security Goals", "Product Constraints".
  - Do NOT label ordinary concepts or enforcement controls as decisions just because they influence later steps.
    "Prompt Threats", "Instruction Hierarchy", "Fine-Tuned Model", and "Output Guardrails"
    are usually concepts / controls / services unless the user explicitly frames them as a choice point.
  - Avoid drifting into very low-level math or internal neuron-layer detail unless the user explicitly asks.
  - If the retrieved evidence is narrow, keep the graph small and faithful instead of making it look "complete".
</grounding_rules>

<graph_type_choice>
  Use "concept" when the user asks about:
    - a method, technique, concept, comparison, tradeoff, or relationship between ideas
    - how something works in plain English
    - why a concept matters
    - a security / guardrail / prompt-engineering flow
    - a step-by-step policy, control, or reasoning flow
    - decision logic inside a system rather than deployed infrastructure

  Use "architecture" only when the user clearly asks for:
    - system architecture
    - service / component flow
    - deployment / infrastructure / serving pipeline
    - request path through a real system

  If in doubt, choose "concept".
  If the request is mostly about logical stages, requirements, controls, or decisions,
  choose "concept" even if words like gateway, router, or model appear.
</graph_type_choice>

<sizing_constraints>
  "label"       — HARD MAX 3 words, HARD MAX 20 characters.
                  GOOD: "API Gateway", "Vector Store", "LLM Engine", "Eval Runner"
                  BAD:  "Retrieval-Augmented Generation (RAG)", "Large Language Model Inference Server"
  "technology"  — HARD MAX 25 characters. Abbreviate if needed.
                  GOOD: "Python / FastAPI", "FAISS / HNSWlib", "vLLM / A100"
                  BAD:  "Python / FastAPI + Pydantic + Uvicorn"
  groups.label  — MAX 4 words (e.g. "Storage Layer", "Orchestration Layer")
  title         — MAX 5 words
</sizing_constraints>

<terminal_node_rule>
  Every node must be one of two terminal states:

  END (data sinks) — datastores, caches, databases, vector stores, output logs.
    These naturally terminate the flow. No return edge required. The graph stops here.

  LOOP (feedback / control cycles) — a service node that loops back to drive another
    iteration (e.g. an agent orchestrator that receives a tool result and re-evaluates).
    Add a SINGLE loop edge using "type": "loop":
      {"source": "<loop_node_id>", "target": "<orchestrator_id>", "type": "loop",
       "label": "re-evaluates", "technology": "in-process/function call", "sync": "sync",
       "description": "Agent loops back to re-plan after receiving tool output"}
    Loop edges are hidden by default in the UI and revealed only when the user hovers
    the source node. Use them sparingly — only for genuine iterative control flows.

  DO NOT draw a return edge from terminal datastores or from every node back to the client.
  The CLIENT node does not need an incoming return arc — it is implied by the architecture.
</terminal_node_rule>

<node_types>
  "client"    — external actors: users, browsers, mobile apps, IoT devices
  "service"   — processing logic: APIs, microservices, ML models, workers, pipelines
  "datastore" — persistent state: databases, caches, vector stores, message queues, S3
  "gateway"   — traffic entry & control: load balancers, API gateways, CDN, reverse proxies
  "network"   — boundaries & plumbing: VPC, subnet, NAT gateway, firewall, VPC endpoint
  "external"  — third-party dependencies: SaaS APIs, managed services outside your control
  "control"   — policy/security enforcement: access control, guardrails, validators, filters, moderation
  "decision"  — non-service constraints or choices: compute budget, approval gate, tradeoff, business rule
</node_types>

<node_fields>
  "technology" — the specific tech stack, e.g. "Python / FastAPI", "Redis 7", "vLLM / A100".
                 For concept graphs, use the framework or paper, e.g. "Transformer / PyTorch".
  "description" — one sentence: what this node IS and what it DOES.
                  Good: "Embedding service that converts text chunks into dense vectors for retrieval"
                  Bad:  "Handles embeddings" (too vague)
  "tier" — "public" (internet-facing) or "private" (VPC-internal / not directly accessible).
           Always set for architecture graphs. Omit for concept graphs.
</node_fields>

<edge_rules>
  - Every edge is UNIDIRECTIONAL. Never use bidirectional edges.
  - ALL edges must flow in the FORWARD direction (left → right in the layout).
    NEVER draw a backward edge from a downstream node back to an upstream node.
    The only exception is edges with "type": "loop" — and even those are used sparingly.
    Forward means: client → gateway → services → datastores/external (never the reverse).
  - "label" must be a specific action phrase (verb + object).
      Good: "sends query", "returns predictions", "streams embeddings", "publishes event"
      Bad:  "uses", "connects", "outputs", "internal" (these say nothing)
  - "technology" = transport + data format. Examples:
      "HTTPS/JSON", "gRPC/Protobuf", "WebSocket/binary", "Kafka", "SQS",
      "Redis Pub/Sub", "S3 event", "in-process/function call"
  - "sync" = "sync" for request-response, "async" for fire-and-forget / event-driven / queues.
  - "description" = one sentence about what data actually flows, e.g.
      "User query text and conversation history sent for inference"
</edge_rules>

<architecture_guidelines>
  - Think like an AWS Solutions Architect drawing a production system only when the question is truly architectural.
  - Always distinguish public vs private resources via the "tier" field.
  - Include critical networking components: API Gateway, ALB/NLB, NAT Gateway,
    VPC Endpoints, CloudFront/CDN — these are real nodes, not decoration.
  - 5–10 nodes total (for replace); 1–5 new nodes (for update).
  - HARD EDGE LIMIT: max 12 edges for replace, max 5 for update. Keep only the edges that
    carry meaningful data flow. Cut redundant or implied connections — if A→B→C is clear,
    don't also draw A→C unless a direct path truly exists.
  - Every node must appear in at least one edge.
  - Use Chip Huyen's AI Engineering terminology.
</architecture_guidelines>

<concept_graph_guidelines>
  - 4–7 nodes total for replace; 1–4 nodes for update.
  - Prefer a clean left-to-right learning flow over an infra-style deployment map.
  - When the user gives numbered stages or asks for the "full flow", mirror that order directly.
  - Use "sequence" to anchor the main stages in order.
  - For concept graphs, omit "tier" and avoid public/private infrastructure framing unless the user explicitly asks.
  - Keep decision nodes scarce and meaningful: use them only where the flow truly hinges on a choice,
    requirement, or routing decision.
  - Title should name the learning topic, not a visual category. Good:
      "PEFT Fine-Tuning", "LoRA Training Flow", "Latency Tradeoffs"
    Bad:
      "Fine tuning architecture", "neuron layers", "system components"
  - Node labels should be the learner-facing concepts that matter most.
  - Edges should explain conceptual relationships with simple verbs:
      "adapts", "updates", "reduces cost", "stores weights", "feeds into"
  - Sequence should walk through the idea in the order a beginner should understand it.
</concept_graph_guidelines>

<layout_rules>
  The frontend places nodes in topological columns and respects the "lane" and "tier" fields.
  Structure your graph to produce the following visual layout:

  COLUMN ORDER (left → right):
    1. Client / User-facing (left)  — browsers, apps, external consumers
    2. Gateway / Entry points       — API Gateway, ALB, CDN, reverse proxies
    3. Core services / AI logic     — orchestrators, LLM inference, agents, pipelines
    4. Storage / Data               — vector stores, databases, caches, queues
    5. External services (right)    — third-party APIs, managed AI providers

  STRICT DATA-FLOW COLUMN RULE:
    If node B receives data from node A, node B MUST be in a column to the RIGHT of node A.
    A node that performs the FINAL generation step (e.g. LLM inference, fine-tuned model)
    must always be placed AFTER all retrieval nodes — never parallel to them.
    Violation example (wrong): putting Fine-Tuned LLM in the same column as Vector Retriever.
    Correct: retrieval nodes are upstream → LLM inference is downstream → LLM goes further right.

  TIER ORDER (left = public, right = private):
    - Set tier:"public" for client-facing and internet-exposed nodes (columns 1-2).
    - Set tier:"private" for all internal services and datastores (columns 3-5).
    - Direction of exposure: public → private from left to right.

  STORAGE PLACEMENT:
    - Attach storage/datastore nodes to the service that primarily owns them.
    - Do NOT cluster all datastores in one column; spread them next to their service.

  DECISION / CONSTRAINT PLACEMENT:
    - Use type:"control" for policy/security enforcement nodes that continuously evaluate or enforce rules.
    - Use type:"decision" for nodes that represent a requirement, tradeoff, checkpoint,
      routing choice, or explicit technical/business decision.
    - A control node is a real stage in the flow and should usually sit inline with the system it protects.
    - A decision node can appear upstream of the service or concept it shapes.
    - Do NOT relabel ordinary concepts as decisions just because they are important.
    - Do NOT label a budget, tradeoff, or approval gate as type:"service" just to make the diagram fit.

  OBSERVABILITY / MONITORING lane field:
    - "lane": "bottom"  — use for monitoring, logging, or observability nodes that
      instrument the ENTIRE pipeline (e.g. Prometheus, Grafana, CloudWatch, Jaeger).
      These render in a dedicated bottom band spanning the full diagram width.
    - "lane": "main"   — all other nodes (default; omit this field entirely if main).
    - If a monitoring node is only paired with ONE service, omit the lane field and
      place it as a normal node adjacent to its service in the same column.

  CLIENT OUTPUT:
    - Do NOT add a return edge back to the client.
    - The UI already implies that the final service produces the user-visible output.
    - Keep the graph strictly forward-flowing unless an edge is a genuine "loop" control cycle.
</layout_rules>"""

_FORCE_GRAPH_APPEND = """

IMPORTANT OVERRIDE:
- A graph is required for this turn.
- Do NOT respond with NO_GRAPH.
- Return a JSON graph now, even if it must stay small and concept-focused.
"""

_FORCE_REPLACE_APPEND = """

IMPORTANT OVERRIDE:
- The user is intentionally changing topics within the same chat.
- Do NOT tell them to start a new chat.
- Use action:"replace" and return a complete fresh graph for the new topic now.
"""


def _task_specific_hint(user_message: str) -> str:
    message = (user_message or "").lower()
    if not any(
        token in message
        for token in (
            "step", "steps", "flow", "decision", "guardrail", "guardrails",
            "prompt injection", "jailbreak",
            "paso", "pasos", "flujo", "seguridad", "proteccion", "protección",
            "control", "acceso", "inyeccion", "inyección",
        )
    ):
        return ""
    return (
        "TASK-SPECIFIC OVERRIDE:\n"
        "- This request is asking for a staged control flow, not infrastructure deployment.\n"
        '- Prefer graph_type "concept".\n'
        "- Mirror the user's step order directly in the graph and in sequence.\n"
        "- If the flow includes upstream influences, add separate nodes such as External Factors or Business Requirements.\n"
        "- Use control nodes for guardrails, policy engines, access control, and validators.\n"
        "- Use decision nodes for technical choices or routing checkpoints, not for every upstream concept.\n"
        "- Do not label threat categories, policy sources, model stages, or guardrail stages as decisions unless they are framed as explicit choice points.\n"
    )


async def _generate_raw_graph_response(
    system: str,
    messages: list[dict],
    send,
    *,
    telemetry: dict | None = None,
) -> str:
    return await stream_llm(
        model=settings.worker_model,
        system=system,
        messages=messages,
        temperature=settings.graph_temperature,
        top_p=settings.graph_top_p,
        top_k=settings.graph_top_k,
        telemetry=telemetry,
        send=send,
    )


async def graph_worker_node(state: AgentState, tools: list) -> AgentState:
    """
    Run the graph worker.

    Returns:
        state with graph_data set to:
          - new/merged graph dict if the model generated/updated
          - None if the model said NO_GRAPH (caller preserves existing graph)
    """
    send = state["send"]
    await send({"type": "worker_status", "worker": "graph", "status": "Checking graph…"})

    tool_map = {t.name: t for t in tools}
    generate_graph = tool_map.get("generate_graph")

    existing: GraphData | None = state.get("graph_data")

    # Describe current graph state to the model
    if existing:
        existing_nodes = ", ".join(n["label"] for n in existing.get("nodes", []))
        current_context = (
            f"Current graph: \"{existing.get('title', '?')}\" — nodes: [{existing_nodes}]\n\n"
        )
    else:
        current_context = "No graph exists yet — you MUST use action 'replace' to create one.\n\n"

    # Prepend complexity hint if the user selected a non-auto level
    hint = _COMPLEXITY_HINTS.get(state.get("complexity", "auto"), "")
    task_hint = _task_specific_hint(state.get("user_message", ""))
    system_parts = [part for part in (hint, task_hint, _SYSTEM) if part]
    system = "\n\n".join(system_parts)

    # Inject web research context if available (from research_worker)
    research_block = ""
    if state.get("research_context"):
        research_block = f"\nWeb research:\n{state['research_context']}\n"

    rag_block = ""
    if state.get("rag_chunks"):
        rag_block = f"\nRetrieved book evidence:\n{_format_rag_context(state['rag_chunks'])}\n"

    messages = [{
        "role": "user",
        "content": (
            f"{current_context}"
            f"{rag_block}"
            f"{research_block}"
            f"User question: {state['user_message']}"
        ),
    }]
    telemetry = build_telemetry(
        "graph_worker",
        user_id=state.get("user_id"),
        thread_id=state.get("session_id"),
        metadata={"graph_mode": state.get("graph_mode", "auto")},
    )

    try:
        raw = await _generate_raw_graph_response(system, messages, send, telemetry=telemetry)

        # Model decided no graph change needed
        if "NO_GRAPH" in raw.strip().upper()[:120] and not raw.strip().startswith("{"):
            if existing is None:
                raw = await _generate_raw_graph_response(
                    f"{system}\n{_FORCE_GRAPH_APPEND}",
                    messages,
                    send,
                    telemetry=telemetry,
                )
                if "NO_GRAPH" in raw.strip().upper()[:120] and not raw.strip().startswith("{"):
                    return {**state, "graph_data": None}
            else:
                return {**state, "graph_data": None}

        parsed = _parse_json(raw)
        if parsed is None:
            print(f"[graph_worker] Parse failed. Raw:\n{raw[:500]}")
            return {**state, "graph_data": None}

        action = parsed.get("action", "replace")
        if action == "new_chat":
            if existing:
                raw = await _generate_raw_graph_response(
                    f"{system}\n{_FORCE_REPLACE_APPEND}",
                    messages,
                    send,
                    telemetry=telemetry,
                )
                if "NO_GRAPH" in raw.strip().upper()[:120] and not raw.strip().startswith("{"):
                    await send({
                        "type": "graph_notice",
                        "message": (
                            "This looks like a different graph topic, but the graph generator failed to redraw it. "
                            "Try again or start a new chat if you want a clean break."
                        ),
                    })
                    return {**state, "graph_data": None, "graph_notice_sent": True}
                parsed = _parse_json(raw)
                if parsed is None:
                    return {**state, "graph_data": None}
                action = parsed.get("action", "replace")
            else:
                # new_chat with no existing graph is invalid — re-prompt for a real graph
                raw = await _generate_raw_graph_response(
                    f"{system}\n{_FORCE_GRAPH_APPEND}",
                    messages,
                    send,
                    telemetry=telemetry,
                )
                if "NO_GRAPH" in raw.strip().upper()[:120] and not raw.strip().startswith("{"):
                    return {**state, "graph_data": None}
                parsed = _parse_json(raw)
                if parsed is None:
                    return {**state, "graph_data": None}
                # Fall through to validation with the new response

        if action == "update" and existing:
            merged = _merge_graphs(existing, parsed, generate_graph)
            return {**state, "graph_data": _attach_graph_version(merged)}

        validated = _validate(parsed, generate_graph)
        return {**state, "graph_data": _attach_graph_version(validated)}
    except Exception as exc:
        print(f"[graph_worker] Unhandled error: {type(exc).__name__}: {exc}")
        return {**state, "graph_data": None}


def _parse_json(text: str) -> dict | None:
    """Strip markdown fences and find the first valid JSON object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(cleaned):
        start = cleaned.find("{", idx)
        if start == -1:
            break
        try:
            data, _ = decoder.raw_decode(cleaned, start)
            if isinstance(data, dict) and (data.get("nodes") or data.get("action") in ("update", "new_chat")):
                return data
            idx = start + 1
        except json.JSONDecodeError:
            idx = start + 1
    return None


def _validate(data: dict, generate_graph_tool) -> GraphData | None:
    """Run data through the generate_graph tool for field validation."""
    if not generate_graph_tool:
        return data
    try:
        invoke_args = {
            "graph_type": data.get("graph_type", "concept"),
            "title":      data.get("title", "Knowledge Graph"),
            "nodes":      data.get("nodes", []),
            "edges":      data.get("edges", []),
            "sequence":   data.get("sequence", []),
        }
        if data.get("groups"):
            invoke_args["groups"] = data["groups"]
        result_json = generate_graph_tool.invoke(invoke_args)
        return json.loads(result_json)
    except Exception as exc:
        print(f"[graph_worker] Validation error: {exc}")
        return None


def _attach_graph_version(graph: GraphData | None) -> GraphData | None:
    if graph is None:
        return None
    stamped = dict(graph)
    stamped["version"] = str(uuid.uuid4())
    return stamped


def _format_rag_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks[:4], 1):
        citation = f"Chapter {chunk.get('chapter', '?')}, p.{chunk.get('page_number', '?')}"
        section = chunk.get("section") or chunk.get("chapter_title") or "Section"
        text = chunk.get("text", "").strip().replace("\n", " ")
        parts.append(f"[{i}] {section} — {citation}\n{text[:500]}")
    return "\n\n".join(parts)


def _merge_graphs(existing: GraphData, delta: dict, generate_graph_tool) -> GraphData:
    """
    Merge delta nodes/edges into existing graph.
    Deduplicates by node id and (source, target) edge pairs.
    Updates title if the delta provides a non-default one.
    """
    existing_ids  = {n["id"] for n in existing.get("nodes", [])}
    existing_pairs = {(e["source"], e["target"]) for e in existing.get("edges", [])}

    new_nodes = [n for n in delta.get("nodes", []) if n["id"] not in existing_ids]
    new_edges = [
        e for e in delta.get("edges", [])
        if (e["source"], e["target"]) not in existing_pairs
    ]

    merged_nodes = existing.get("nodes", []) + new_nodes
    merged_edges = existing.get("edges", []) + new_edges
    merged_sequence = existing.get("sequence", []) + delta.get("sequence", [])

    # Keep existing title unless delta explicitly provides a new one
    title = delta.get("title") or existing.get("title", "Knowledge Graph")

    # Groups: use delta's groups if provided, else keep existing
    merged_groups = delta.get("groups") or existing.get("groups", [])

    merged: GraphData = {
        "graph_type": delta.get("graph_type") or existing.get("graph_type", "concept"),
        "title":      title,
        "nodes":      merged_nodes,
        "edges":      merged_edges,
        "sequence":   merged_sequence,
    }
    if merged_groups:
        merged["groups"] = merged_groups

    # Re-validate merged graph through the tool
    validated = _validate(merged, generate_graph_tool)
    return validated if validated is not None else merged
