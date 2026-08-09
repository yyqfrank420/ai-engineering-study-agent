import json
from types import SimpleNamespace

import pytest


def test_applied_graph_prompts_define_record_scoped_repair_boundaries():
    from agent.nodes.graph_worker import (
        _APPLIED_GRAPH_PATCH_PROMPT_VERSION,
        _APPLIED_GRAPH_PATCH_SYSTEM,
        _APPLIED_GRAPH_TOPOLOGY_PROMPT_VERSION,
        _APPLIED_GRAPH_TOPOLOGY_SYSTEM,
    )

    assert _APPLIED_GRAPH_PATCH_PROMPT_VERSION == "applied_architecture_patch_v34"
    assert _APPLIED_GRAPH_TOPOLOGY_PROMPT_VERSION == "applied_topology_v16"
    assert (
        "Choose graph size from the material design" in _APPLIED_GRAPH_TOPOLOGY_SYSTEM
    )
    assert "presentation metadata" in _APPLIED_GRAPH_TOPOLOGY_SYSTEM
    assert "complete" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "mutation authority" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert (
        "Passing layers and uncited records are immutable"
        in _APPLIED_GRAPH_PATCH_SYSTEM
    )
    assert "directed components and edges" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "complete replacements" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "Map every blocking finding" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert (
        "Declared addition counts are exact required operations"
        in _APPLIED_GRAPH_PATCH_SYSTEM
    )
    assert "Every update must" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "repair-only edge_id values" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "non-adjacent records" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "source and destination group IDs" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "server enforces the exact directed endpoints" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "post-patch critic verifies the" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "does not supply omitted behavior" in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "cache lookup separate from" not in _APPLIED_GRAPH_PATCH_SYSTEM
    assert "approval-only route" not in _APPLIED_GRAPH_PATCH_SYSTEM


def test_applied_graph_text_limits_preserve_sentence_or_word_boundaries():
    from agent.nodes.graph_worker import _required_text

    complete = (
        "A complete first sentence. A second sentence that exceeds the diagram field."
    )
    assert _required_text(complete, "description", 34) == "A complete first sentence."

    long_phrase = "one two three four five six seven eight"
    bounded = _required_text(long_phrase, "technology", 24)
    assert bounded.endswith("…")
    assert not bounded.endswith(" …")


@pytest.mark.parametrize(
    "edge",
    [
        "not-an-object",
        {
            "source": "known",
            "target": "missing",
            "label": "claims safe delivery",
            "technology": "JSON",
            "description": "A reassuring label cannot repair an unknown boundary.",
        },
        {
            "source": "known",
            "target": "known",
            "label": "retries internally",
            "technology": "retry loop",
            "description": "A self-edge cannot express a separately owned recovery path.",
        },
    ],
)
def test_applied_graph_rejects_malformed_or_unverifiable_edges(edge):
    from agent.nodes.graph_worker import _normalise_edges

    with pytest.raises(ValueError):
        _normalise_edges([edge], {"known": "known"}, max_edges=4)


@pytest.mark.asyncio
async def test_graph_worker_uses_canonical_artifacts_without_llm(monkeypatch, tmp_path):
    from tests.test_canonical_graph import SCHEMA_DIR, _write_parent_docs
    from graph.artifacts import load_canonical_graph
    from graph.build import build_canonical_graph
    import agent.nodes.graph_worker as graph_worker
    import agent.stream_utils as stream_utils_mod

    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)

    async def fail_stream_response(**_kwargs):
        raise AssertionError("canonical graph worker must not call the LLM")
        yield ("text", "")

    monkeypatch.setattr(stream_utils_mod, "stream_response", fail_stream_response)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: artifacts)

    events = []

    async def send(event):
        events.append(event)

    state = {
        "send": send,
        "user_id": "user-1",
        "session_id": "thread-1",
        "user_message": "Explain retrieval augmented generation",
        "graph_data": None,
        "complexity": "auto",
        "research_context": "",
        "rag_chunks": [{"parent_chunk_id": "ai-eng:p42:pc0", "text": ""}],
    }

    result = await graph_worker.graph_worker_node(state, tools=[])

    assert events[0] == {
        "type": "worker_status",
        "worker": "graph",
        "status": "Selecting grounded concepts…",
    }
    assert result["graph_data"]["graph_type"] == "concept"
    assert result["graph_data"]["version"]
    assert all(node.get("canonical_id") for node in result["graph_data"]["nodes"])


@pytest.mark.asyncio
async def test_explicit_runtime_flow_uses_applied_architecture_not_concept_map(
    monkeypatch,
):
    import agent.nodes.graph_worker as graph_worker

    async def fake_generate(_state, query, profile):
        assert query == (
            "Explain retrieval-augmented generation, ground the explanation in the "
            "AI Engineering material, and draw the runtime flow."
        )
        assert profile.resolved == "prototype"
        return {
            "graph_type": "architecture",
            "design_origin": "applied",
            "title": "Grounded RAG Runtime",
            "nodes": [],
            "edges": [],
            "sequence": [],
        }

    def fail_canonical_load():
        raise AssertionError(
            "explicit runtime flow must not use the concept-map selector"
        )

    monkeypatch.setattr(graph_worker, "_generate_applied_architecture", fake_generate)
    monkeypatch.setattr(
        graph_worker, "load_canonical_graph_cached", fail_canonical_load
    )

    async def send(_event):
        return None

    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": (
                "Explain retrieval-augmented generation, ground the explanation in the "
                "AI Engineering material, and draw the runtime flow."
            ),
            "graph_data": None,
            "complexity": "auto",
            "research_context": "",
            "rag_chunks": [],
        },
        tools=[],
    )

    assert result["graph_data"]["graph_type"] == "architecture"
    assert result["graph_data"]["design_origin"] == "applied"


def _approved_rebuild_graph():
    return {
        "graph_type": "architecture",
        "design_origin": "applied",
        "title": "Approved support ownership",
        "version": "approved-v1",
        "assumptions": ["The CRM is the accepted customer record."],
        "nodes": [{"id": "support_owner", "label": "Support Owner"}],
        "edges": [],
        "sequence": [],
    }


@pytest.mark.asyncio
async def test_broad_expansion_preserves_approved_graph_for_clarification(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    existing = _approved_rebuild_graph()
    accepted = json.loads(json.dumps(existing))
    calls = []
    events = []

    async def fake_generate(generation_state, _query, _profile):
        calls.append(generation_state)
        raise graph_worker.GraphPatchRejected(
            "graph_edit_scope_ambiguous",
            "the expansion is broader than a narrow patch",
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(graph_worker, "_generate_applied_architecture", fake_generate)
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Expand the diagram to show every support owner",
            "design_query": "Expand the support ownership architecture",
            "graph_intent": "edit",
            "graph_data": existing,
            "approved_graph_data": accepted,
            "complexity": "prototype",
        },
        tools=[],
    )

    assert len(calls) == 1
    assert result["graph_data"] == existing
    assert result["graph_data"] is not existing
    assert result["graph_failure_code"] == "graph_edit_scope_ambiguous"
    assert result["graph_operation"] == {
        "kind": "edit",
        "status": "failed",
        "failure_code": "graph_edit_scope_ambiguous",
    }
    assert any(
        event.get("status") == "rejected"
        and event.get("failure_code") == "graph_edit_scope_ambiguous"
        for event in events
    )


@pytest.mark.asyncio
async def test_graph_worker_abstains_without_canonical_support(monkeypatch, tmp_path):
    from tests.test_canonical_graph import SCHEMA_DIR, _write_parent_docs
    from graph.artifacts import load_canonical_graph
    from graph.build import build_canonical_graph
    import agent.nodes.graph_worker as graph_worker

    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: artifacts)

    async def send(_event):
        pass

    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Explain an unsupported concept",
            "graph_data": None,
            "complexity": "auto",
            "research_context": "",
            "rag_chunks": [{"parent_chunk_id": "ai-eng:p999:pc0", "text": ""}],
        },
        tools=[],
    )

    assert result["graph_data"] is None


@pytest.mark.asyncio
async def test_graph_worker_customises_growth_marketing_architecture(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    payload = {
        "graph_type": "architecture",
        "title": "Growth Campaign Optimisation Loop",
        "assumptions": ["Advertising channels expose read and write APIs."],
        "nodes": [
            {
                "id": "objective_config",
                "label": "Objective Config",
                "type": "decision",
                "technology": "Metric contract",
                "description": "Defines the measurable goal, constraints, and optimisation horizon.",
            },
            {
                "id": "campaign_brief",
                "label": "Campaign Brief",
                "type": "client",
                "technology": "Structured brief",
                "description": "Captures product, audience, claims, budget, and channel intent.",
            },
            {
                "id": "event_quality",
                "label": "Event Quality Gate",
                "type": "control",
                "technology": "Schema and identity checks",
                "description": "Rejects ambiguous or untrusted conversion signals before optimisation.",
            },
            {
                "id": "performance_store",
                "label": "Performance Store",
                "type": "datastore",
                "technology": "Campaign event warehouse",
                "description": "Stores spend, exposure, conversion, and attribution observations.",
            },
            {
                "id": "strategy_engine",
                "label": "Strategy Engine",
                "type": "service",
                "technology": "Constrained decision engine",
                "description": "Chooses the next campaign hypothesis against the objective and budget.",
            },
            {
                "id": "creative_studio",
                "label": "Creative Studio",
                "type": "service",
                "technology": "Copy generation workflow",
                "description": "Produces traceable copy variants from an approved campaign brief.",
            },
            {
                "id": "audience_optimizer",
                "label": "Audience Optimizer",
                "type": "service",
                "technology": "Targeting policy",
                "description": "Proposes audience and bid changes within configured boundaries.",
            },
            {
                "id": "policy_gate",
                "label": "Policy Approval Gate",
                "type": "control",
                "technology": "Rules plus human approval",
                "description": "Blocks unsupported claims, excessive spend shifts, and unsafe targeting.",
            },
            {
                "id": "channel_executor",
                "label": "Channel Executor",
                "type": "external",
                "technology": "Advertising platform adapters",
                "description": "Publishes approved creative, targeting, and budget changes idempotently.",
            },
            {
                "id": "outcome_attribution",
                "label": "Outcome Attribution",
                "type": "service",
                "technology": "Incrementality measurement",
                "description": "Estimates which campaign changes caused the observed business outcomes.",
            },
            {
                "id": "release_registry",
                "label": "Strategy Release Registry",
                "type": "control",
                "technology": "Versioned canary registry",
                "description": "Promotes or rolls back evaluated strategy releases without live feedback updates.",
            },
        ],
        "edges": [
            {
                "source": "campaign_brief",
                "target": "strategy_engine",
                "label": "submits campaign constraints",
                "technology": "Validated JSON",
                "sync": "sync",
                "description": "The brief defines the design space.",
            },
            {
                "source": "objective_config",
                "target": "strategy_engine",
                "label": "constrains optimisation",
                "technology": "Versioned metric contract",
                "sync": "sync",
                "description": "The objective and hard limits govern decisions.",
            },
            {
                "source": "performance_store",
                "target": "strategy_engine",
                "label": "supplies performance window",
                "technology": "Feature view",
                "sync": "sync",
                "description": "Recent observations inform the next hypothesis.",
            },
            {
                "source": "strategy_engine",
                "target": "creative_studio",
                "label": "requests copy variants",
                "technology": "Creative specification",
                "sync": "sync",
                "description": "The strategy becomes bounded creative tasks.",
            },
            {
                "source": "strategy_engine",
                "target": "audience_optimizer",
                "label": "requests targeting change",
                "technology": "Targeting proposal",
                "sync": "sync",
                "description": "The strategy becomes an auditable audience proposal.",
            },
            {
                "source": "creative_studio",
                "target": "policy_gate",
                "label": "submits claim variants",
                "technology": "Copy plus provenance",
                "sync": "sync",
                "description": "Generated claims are reviewed before publication.",
            },
            {
                "source": "audience_optimizer",
                "target": "policy_gate",
                "label": "submits audience proposal",
                "technology": "Policy diff",
                "sync": "sync",
                "description": "Targeting and budget changes are bounded.",
            },
            {
                "source": "policy_gate",
                "target": "channel_executor",
                "label": "releases approved changes",
                "technology": "Signed change set",
                "sync": "async",
                "description": "Only approved mutations reach ad platforms.",
            },
            {
                "source": "channel_executor",
                "target": "event_quality",
                "label": "emits delivery outcomes",
                "technology": "Channel events",
                "sync": "async",
                "description": "Delivery and conversion observations return for validation.",
            },
            {
                "source": "event_quality",
                "target": "performance_store",
                "label": "writes trusted events",
                "technology": "Canonical event schema",
                "sync": "async",
                "description": "Only valid signals enter optimisation history.",
            },
            {
                "source": "performance_store",
                "target": "outcome_attribution",
                "label": "provides exposure outcomes",
                "technology": "Attribution dataset",
                "sync": "async",
                "description": "Measurement compares actions with outcomes.",
            },
            {
                "source": "outcome_attribution",
                "target": "strategy_engine",
                "label": "returns causal score",
                "technology": "Attribution report",
                "sync": "async",
                "description": "Measured impact closes the decision loop.",
                "type": "loop",
            },
            {
                "source": "outcome_attribution",
                "target": "release_registry",
                "label": "submits offline evaluation evidence",
                "technology": "Versioned evaluation set",
                "sync": "async",
                "description": "Measured outcomes enter a reviewed release process.",
            },
            {
                "source": "release_registry",
                "target": "strategy_engine",
                "label": "promotes evaluated strategy version",
                "technology": "Immutable release pointer",
                "sync": "async",
                "description": "Only reviewed canaries update production strategy behavior.",
            },
        ],
        "sequence": [
            {
                "step": 1,
                "nodes": ["campaign_brief", "objective_config"],
                "description": "Define campaign intent and measurable constraints.",
            },
            {
                "step": 2,
                "nodes": ["strategy_engine", "creative_studio", "audience_optimizer"],
                "description": "Form and materialise a campaign hypothesis.",
            },
            {
                "step": 3,
                "nodes": ["policy_gate", "channel_executor"],
                "description": "Approve and publish bounded changes.",
            },
            {
                "step": 4,
                "nodes": ["event_quality", "performance_store", "outcome_attribution"],
                "description": "Validate outcomes and close the optimisation loop.",
            },
        ],
        "groups": [
            {
                "id": "intent",
                "label": "Intent and Constraints",
                "nodeIds": ["campaign_brief", "objective_config"],
            },
            {
                "id": "decision",
                "label": "Decision and Creation",
                "nodeIds": ["strategy_engine", "creative_studio", "audience_optimizer"],
            },
            {
                "id": "execution",
                "label": "Controlled Execution",
                "nodeIds": ["policy_gate", "channel_executor"],
            },
            {
                "id": "measurement",
                "label": "Measurement Loop",
                "nodeIds": [
                    "event_quality",
                    "performance_store",
                    "outcome_attribution",
                    "release_registry",
                ],
            },
        ],
    }
    captured = {}

    type_codes = {
        "client": 100,
        "service": 101,
        "datastore": 102,
        "queue": 103,
        "gateway": 104,
        "network": 105,
        "external": 106,
        "control": 107,
        "decision": 108,
    }
    group_codes = {
        "runtime": 600,
        "data": 601,
        "operations": 602,
        "delivery": 603,
        "external": 604,
    }
    group_definitions = [
        [group["label"], group_codes[group.get("kind", "runtime")]]
        for group in payload["groups"]
    ]
    node_group_indexes = {
        node_id: group_index
        for group_index, group in enumerate(payload["groups"])
        for node_id in group["nodeIds"]
    }
    topology = {
        "root": [
            payload["nodes"][0]["label"],
            type_codes[payload["nodes"][0]["type"]],
            payload["nodes"][0]["description"][:80],
            node_group_indexes[payload["nodes"][0]["id"]],
        ],
        "components": [
            [
                index - 1,
                node["label"],
                type_codes[node["type"]],
                node["description"][:80],
                node_group_indexes[node["id"]],
                f"routes validated work to {node['label']}",
                400,
                500,
            ]
            for index, node in enumerate(payload["nodes"])
            if index > 0
        ],
        "connections": {
            "links": [
                [9, 4, "Measured outcome feedback", 402, 501],
                [10, 4, "Promotes evaluated strategy version", 403, 501],
                [7, 5, "Reject campaign revision", 401, 500],
            ],
        },
        "composition": {
            "title": payload["title"],
            "groups": group_definitions,
            "steps": [[index] for index in range(len(payload["nodes"]))],
        },
    }

    async def fake_stream_structured_llm(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text=json.dumps(topology), finish_reason="end_turn")

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )

    events = []

    async def send(event):
        events.append(event)

    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": (
                "growth and performance marketing AI agent system that auto evaluates, writes "
                "and adjusts copy, strategy, targeting and event definitions to maximise an objective function"
            ),
            "history": [],
            "graph_data": None,
            "complexity": "auto",
            "research_context": "",
            "rag_chunks": [{"parent_chunk_id": "ai-eng:p473:pc0", "text": ""}],
            "architect_plan": {
                "diagram_requirements": [
                    "Cache versioned channel reads within a bounded freshness window",
                    "Let reporting-only requests bypass the external write approval path",
                    "Return every creative and targeting branch to measured attribution",
                ]
            },
            "challenger_review": {
                "risks": [{"area": "safety", "risk": "Unapproved campaign writes"}],
            },
            "architecture_ready": True,
            "approved_graph_data": None,
        },
        tools=[],
    )

    graph = result["graph_data"]
    assert graph is not None
    assert graph["graph_type"] == "architecture"
    labels = {node["label"] for node in graph["nodes"]}
    assert {
        "Objective Config",
        "Creative Studio",
        "Audience Optimizer",
        "Policy Approval Gate",
        "Outcome Attribution",
        "Strategy Release Registry",
    } <= labels
    assert not (
        {"Agent", "Tool Use", "Planning", "Evaluation", "Foundation Model"} & labels
    )
    assert graph["design_origin"] == "applied"
    assert graph["resolved_complexity"] == "production"
    assert graph["assumptions"] == []
    assert len(graph["groups"]) == 4
    assert {edge["flow"] for edge in graph["edges"]} == {
        "runtime",
        "feedback",
        "control",
        "deployment",
    }
    # Low effort leaves room for the independent critic without letting
    # unbounded private reasoning consume the complete request deadline.
    assert captured["effort"] == "low"
    assert captured["response_schema"]["properties"]["components"]["type"] == "array"
    links = captured["response_schema"]["properties"]["connections"]["properties"][
        "links"
    ]
    assert links["type"] == "array"
    assert links["items"]["items"] == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }
    assert "$ref" not in json.dumps(captured["response_schema"])
    assert "schema-constrained object" in captured["system"]
    prompt = captured["messages"][0]["content"]
    assert '"node_budget"' not in prompt
    assert "Cache versioned channel reads" in prompt
    assert '"reviewed_plan"' in prompt
    assert '"challenger_review"' not in prompt
    assert '"diagram_commitments"' not in prompt
    assert "Designing a production domain architecture" in events[0]["status"]


def test_applied_graph_validator_rejects_generic_book_taxonomy():
    from agent.nodes.graph_worker import _normalise_applied_graph

    labels = [
        "Agent",
        "Tool Use",
        "Planning",
        "Evaluation",
        "Foundation Model",
        "Generation",
        "Tokenization",
        "Memory",
    ]
    nodes = [
        {
            "id": f"n{index}",
            "label": label,
            "type": "service",
            "technology": "Book concept",
            "description": "Generic concept node.",
        }
        for index, label in enumerate(labels)
    ]
    edges = [
        {
            "source": f"n{index}",
            "target": f"n{index + 1}",
            "label": "depends on",
            "technology": "Book evidence",
            "sync": "sync",
            "description": "Generic relationship.",
        }
        for index in range(len(nodes) - 1)
    ]

    with pytest.raises(ValueError, match="generic concept labels"):
        _normalise_applied_graph(
            {"title": "Agent Map", "nodes": nodes, "edges": edges},
            safety_max_nodes=13,
            resolved_complexity="prototype",
        )


def test_applied_graph_validator_rejects_one_standalone_generic_label():
    from agent.nodes.graph_worker import _normalise_applied_graph

    labels = [
        "Agent",
        "Campaign Intake",
        "Audience Signals",
        "Policy Gate",
        "Outcome Attribution",
    ]
    nodes = [
        {
            "id": f"n{index}",
            "label": label,
            "type": "service",
            "technology": "Domain capability",
            "description": "Owns one specific campaign responsibility.",
        }
        for index, label in enumerate(labels)
    ]
    edges = [
        {
            "source": f"n{index}",
            "target": f"n{index + 1}",
            "label": "passes campaign state",
            "technology": "Validated event",
            "sync": "async",
            "description": "Moves validated campaign state forward.",
        }
        for index in range(len(nodes) - 1)
    ]

    with pytest.raises(ValueError, match="generic concept labels"):
        _normalise_applied_graph(
            {"title": "Campaign system", "nodes": nodes, "edges": edges},
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_applied_graph_validator_ignores_scalar_collection_fields():
    from agent.nodes.graph_worker import _normalise_applied_graph

    nodes = [
        {
            "id": f"node_{index}",
            "label": f"Domain Step {index}",
            "type": "service",
            "technology": "Explicit capability",
            "description": "Owns a distinct domain responsibility.",
        }
        for index in range(5)
    ]
    edges = [
        {
            "source": f"node_{index}",
            "target": f"node_{index + 1}",
            "label": f"passes payload {index}",
            "technology": "Validated event",
            "sync": "async",
            "description": "Moves one explicit payload.",
        }
        for index in range(4)
    ]

    graph = _normalise_applied_graph(
        {
            "title": "Specific domain flow",
            "nodes": nodes,
            "edges": edges,
            "assumptions": "not a list",
            "sequence": [{"nodes": "node_1", "description": "invalid scalar nodes"}],
            "groups": [{"label": "Invalid", "nodeIds": "node_1"}],
        },
        safety_max_nodes=9,
        resolved_complexity="prototype",
    )

    assert graph["assumptions"] == []
    assert graph["sequence"] == []
    assert "groups" not in graph


def test_applied_graph_validator_rejects_isolated_concept_islands():
    from agent.nodes.graph_worker import _normalise_applied_graph

    nodes = [
        {
            "id": f"node_{index}",
            "label": f"Campaign Component {index}",
            "type": "service",
            "technology": "Domain capability",
            "description": "Owns one campaign responsibility.",
        }
        for index in range(5)
    ]
    edges = [
        {
            "source": f"node_{index}",
            "target": f"node_{(index + 1) % 4}",
            "label": "passes campaign payload",
            "technology": "Validated event",
            "sync": "async",
            "description": "Moves campaign state forward.",
        }
        for index in range(4)
    ]

    with pytest.raises(ValueError, match="isolated nodes"):
        _normalise_applied_graph(
            {"title": "Disconnected campaign map", "nodes": nodes, "edges": edges},
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_applied_graph_validator_rejects_book_metadata_subtitles():
    from agent.nodes.graph_worker import _normalise_applied_graph

    nodes = [
        {
            "id": f"node_{index}",
            "label": f"Campaign Component {index}",
            "type": "service",
            "technology": "Book method" if index == 0 else "Domain capability",
            "description": "Owns one campaign responsibility.",
        }
        for index in range(5)
    ]
    edges = [
        {
            "source": f"node_{index}",
            "target": f"node_{index + 1}",
            "label": "passes campaign payload",
            "technology": "Validated event",
            "sync": "async",
            "description": "Moves campaign state forward.",
        }
        for index in range(4)
    ]

    with pytest.raises(ValueError, match="book metadata"):
        _normalise_applied_graph(
            {"title": "Campaign system", "nodes": nodes, "edges": edges},
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


@pytest.mark.asyncio
async def test_generation_does_not_compact_material_node_to_old_profile_cap(
    monkeypatch,
):
    import agent.nodes.graph_worker as graph_worker

    def payload(node_count):
        nodes = [
            {
                "id": f"node_{index}",
                "label": f"Cold Chain Step {index}",
                "type": "service",
                "technology": "Bounded capability",
                "description": "Owns one explicit cold-chain responsibility.",
            }
            for index in range(node_count)
        ]
        edges = [
            {
                "source": f"node_{index}",
                "target": f"node_{index + 1}",
                "label": f"passes validated reading {index}",
                "technology": "Signed event",
                "sync": "async",
                "description": "Moves a validated cold-chain payload.",
            }
            for index in range(node_count - 1)
        ]
        edges.append(
            {
                "source": f"node_{node_count - 1}",
                "target": "node_0",
                "label": "returns measured outcome",
                "technology": "Outcome event",
                "sync": "async",
                "description": "Closes the measured operating loop.",
                "type": "loop",
            }
        )
        return {
            "title": "Cold-chain advisory loop",
            "nodes": nodes,
            "edges": edges,
            "sequence": [
                {
                    "step": 1,
                    "nodes": [f"node_{index}" for index in range(node_count)],
                    "description": "Move a validated reading through every responsibility.",
                }
            ],
            "groups": [
                {
                    "id": "cold_chain_runtime",
                    "label": "Cold-chain runtime",
                    "kind": "runtime",
                    "nodeIds": [f"node_{index}" for index in range(node_count)],
                }
            ],
        }

    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps(payload(9))

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = graph_worker._normalise_applied_graph_candidate(
        payload(9),
        safety_max_nodes=graph_worker.settings.graph_safety_max_nodes,
        resolved_complexity="production",
        context="unit.no-design-compaction",
    )

    assert len(result["nodes"]) == 9
    assert len({node["id"] for node in result["nodes"]}) == 9
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_refinement_raises_for_the_workflow_to_preserve(monkeypatch):
    import agent.nodes.graph_worker as graph_worker

    existing = {
        "graph_type": "architecture",
        "title": "Customer Support Runtime",
        "design_origin": "applied",
        "resolved_complexity": "production",
        "version": "approved-v1",
        "assumptions": ["CRM supports idempotent actions."],
        "nodes": [
            {
                "id": f"node_{index}",
                "label": f"Support Responsibility {index}",
                "type": "service",
                "technology": "Domain capability",
                "description": "Owns one bounded customer support responsibility.",
                "tier": "private",
                "lane": "main",
            }
            for index in range(5)
        ],
        "edges": [],
        "sequence": [
            {"step": 1, "nodes": ["node_0"], "description": "Accept request."}
        ],
        "groups": [
            {
                "id": "runtime",
                "label": "Support Runtime",
                "nodeIds": [f"node_{index}" for index in range(5)],
            }
        ],
    }
    invalid_candidate = {
        "title": "Oversized replacement",
        "nodes": [{"id": f"replacement_{index}"} for index in range(9)],
        "edges": [],
    }
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps(invalid_candidate)

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    with pytest.raises(graph_worker.GraphPatchRejected) as caught:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": (
                    "Add an action proposal service connected to Support Responsibility 0"
                ),
                "design_query": (
                    "customer support chatbot add an action proposal service connected "
                    "to Support Responsibility 0"
                ),
                "history": [],
                "graph_data": existing,
                "complexity": "production",
                "research_context": "",
                "rag_chunks": [],
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            (
                "customer support chatbot add an action proposal service connected "
                "to Support Responsibility 0"
            ),
            SimpleNamespace(resolved="production"),
            existing,
        )

    assert caught.value.code == "graph_patch_invalid_preserved_existing_graph"
    assert existing["title"] == "Customer Support Runtime"
    assert len(calls) == 1
    assert calls[0]["model"] == graph_worker.settings.graph_builder_model
    assert calls[0]["effort"] == "high"
    assert calls[0]["telemetry"]["metadata"]["patch_attempt"] == 0
    prompt = calls[0]["messages"][0]["content"]
    assert "currently has 5 nodes" in prompt
    assert "minimal patch" in prompt
    assert "60%" not in prompt
    assert "node_0" in prompt
    assert "Support Responsibility 0" in prompt
    assert '"nodes"' in prompt
    assert '"edges":[]' in prompt or '"edges": []' in prompt
    assert prompt.count("Domain capability") == 1
    assert prompt.count("Owns one bounded customer support responsibility.") == 1
    assert "CRM supports idempotent actions." not in prompt
    assert '"groups"' in prompt


@pytest.mark.asyncio
async def test_node_detail_prompt_prefers_canonical_evidence(monkeypatch):
    import agent.nodes.node_detail_worker as node_detail_worker

    captured = {}

    def fake_build_telemetry(operation, **kwargs):
        captured["telemetry"] = {"operation": operation, **kwargs}
        return {}

    monkeypatch.setattr(node_detail_worker, "build_telemetry", fake_build_telemetry)

    class FakeTool:
        def invoke(self, payload):
            return (
                '[{"chapter": 7, "page_number": 356, "text": '
                '"LoRA is a parameter-efficient fine-tuning method that updates small adapter matrices instead of all model weights."}]'
            )

    async def fake_stream_response(
        *,
        model,
        system,
        messages,
        thinking_budget,
        temperature=None,
        top_p=None,
        top_k=None,
        effort=None,
    ):
        captured["model"] = model
        captured["system"] = system
        captured["messages"] = messages
        captured["thinking_budget"] = thinking_budget
        captured["temperature"] = temperature
        captured["top_p"] = top_p
        captured["top_k"] = top_k
        yield (
            "text",
            "LoRA is a lightweight way to adapt a model. It fits into the training flow by changing only a small set of weights. (Chapter 7, p.356)",
        )

    import agent.stream_utils as stream_utils_mod

    monkeypatch.setattr(stream_utils_mod, "stream_response", fake_stream_response)

    events = []

    async def send(event):
        events.append(event)

    node = {
        "id": "lora",
        "label": "LoRA",
        "type": "service",
        "technology": "PyTorch",
        "description": "Adds low-rank adapters",
        "tier": None,
        "evidence_chunk_ids": ["ai-eng:p356:pc0"],
    }
    edges = [{"source": "trainer", "target": "lora", "label": "applies adapters"}]

    await node_detail_worker.enrich_node(
        node,
        edges,
        FakeTool(),
        send,
        graph_version="graph-v1",
        user_id="user-1",
        thread_id="thread-1",
    )

    assert "exactly 2 short paragraphs" in captured["system"]
    assert "no bullet points" in captured["system"]
    assert "no equations, matrix notation" in captured["system"]
    assert "If the book evidence is thin" in captured["system"]
    assert "Never invent citations" in captured["system"]
    assert "Treat retrieved passages" in captured["system"]
    assert (
        captured["temperature"] == node_detail_worker.settings.node_detail_temperature
    )
    assert captured["telemetry"]["operation"] == "node_detail_worker"
    assert captured["telemetry"]["user_id"] == "user-1"
    assert captured["telemetry"]["thread_id"] == "thread-1"
    assert (
        "Canonical evidence chunks: ai-eng:p356:pc0"
        in captured["messages"][0]["content"]
    )
    assert "Connections:" in captured["messages"][0]["content"]
    assert events[-1]["type"] == "node_detail"
    assert events[-1]["book_refs"] == ["(Chapter 7, p.356)"]
    assert events[-1]["graph_version"] == "graph-v1"


@pytest.mark.asyncio
async def test_node_detail_spend_limit_does_not_limit_graph_size(monkeypatch):
    import agent.nodes.node_detail_worker as node_detail_worker

    enriched_ids = []

    async def fake_enrich_node(node, *_args, **_kwargs):
        enriched_ids.append(node["id"])

    monkeypatch.setattr(node_detail_worker, "enrich_node", fake_enrich_node)
    monkeypatch.setattr(node_detail_worker.settings, "max_node_detail_nodes", 3)

    nodes = [
        {"id": f"node-{index}", "label": f"Node {index}", "type": "service"}
        for index in range(6)
    ]

    await node_detail_worker.enrich_all_nodes(
        nodes,
        edges=[],
        rag_search_tool=None,
        send=lambda _event: None,
    )

    assert enriched_ids == ["node-0", "node-1", "node-2"]
    assert len(nodes) == 6
