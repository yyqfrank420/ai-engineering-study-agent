import pickle
from pathlib import Path

from langchain_core.documents import Document

from graph.artifacts import load_canonical_graph
from graph.build import build_canonical_graph
from graph.ids import parent_chunk_id_from_metadata
from graph.runtime import choose_layer, select_canonical_graph
from graph.schema import load_relation_registry, validate_relation_registry, violates_negative_example


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "data" / "graph_schema"


def _doc(text: str, page: int, parent_index: int) -> Document:
    return Document(
        page_content=text,
        metadata={
            "book": "AI Engineering",
            "author": "Chip Huyen",
            "chapter": 10 if page >= 400 else 6,
            "chapter_title": "Agents" if page >= 400 else "Retrieval",
            "section": "Test section",
            "page_number": page,
            "parent_chunk_index": parent_index,
        },
    )


def _write_parent_docs(path: Path) -> None:
    docs = [
        _doc(
            "Retrieval-Augmented Generation (RAG) depends on Retrieval. "
            "Retrieval depends on Embeddings. Chunking feeds into Retrieval. "
            "Reranking improves Quality. Evaluation feeds into Model Selection. "
            "Benchmark evaluates Quality. Latency constrains Model Selection. "
            "Cost constrains Model Selection.",
            42,
            0,
        ),
        _doc(
            "User sends to Application. Application calls Orchestrator. "
            "Orchestrator calls Tool Service. Orchestrator routes to Retriever Service. "
            "Retriever Service implements Retrieval and reads from Vector Store. "
            "Application calls LLM Provider. "
            "Monitoring Service writes to Log Store. Evaluation Pipeline reads from Log Store.",
            473,
            0,
        ),
    ]
    with path.open("wb") as handle:
        pickle.dump(docs, handle)


def _build_test_artifacts(tmp_path: Path):
    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    _write_parent_docs(parent_docs_path)
    report = build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    return load_canonical_graph(output_dir), report


def test_parent_chunk_id_generation_is_stable():
    metadata = {"page_number": 42, "parent_chunk_index": 7}
    assert parent_chunk_id_from_metadata(metadata) == "ai-eng:p42:pc7"


def test_relation_registry_has_required_constraints():
    registry = load_relation_registry(SCHEMA_DIR / "relations.json")
    validate_relation_registry(registry)

    spec = registry["depends_on"]
    assert spec.definition
    assert spec.positive_examples
    assert spec.negative_examples
    assert "metric" not in spec.allowed_source_kinds
    assert "metric" not in spec.allowed_target_kinds
    assert "objective" not in spec.allowed_target_kinds
    assert violates_negative_example(spec, spec.negative_examples[0]) is True

    improves = registry["improves"]
    assert set(improves.allowed_source_kinds) == {"method", "control"}
    assert set(improves.allowed_target_kinds) == {"metric", "objective"}


def test_build_writes_valid_canonical_artifacts(tmp_path):
    artifacts, report = _build_test_artifacts(tmp_path)

    assert report["parent_chunk_count"] == 2
    assert report["canonical_concept_count"] >= 6
    assert report["canonical_architecture_count"] >= 6
    assert report["canonical_edge_count"] >= 6

    assert "concept:retrieval_augmented_generation" in artifacts.concepts
    assert "architecture:application" in artifacts.architecture_nodes

    for edge in artifacts.edges.values():
        assert edge["relation"] in artifacts.relations
        assert edge["supporting_chunk_ids"]
        assert edge["support_spans"]


def test_runtime_selects_bounded_concept_subgraph(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    graph = select_canonical_graph(
        query="Explain retrieval augmented generation",
        rag_chunks=[{"parent_chunk_id": "ai-eng:p42:pc0"}],
        artifacts=artifacts,
    )

    assert graph is not None
    assert graph["graph_type"] == "concept"
    assert 4 <= len(graph["nodes"]) <= 7
    assert len(graph["edges"]) >= 2
    canonical_ids = [node["canonical_id"] for node in graph["nodes"]]
    assert canonical_ids[0] == "concept:retrieval_augmented_generation"
    assert graph["title"].startswith("RAG")
    assert all(node.get("canonical_id") for node in graph["nodes"])
    assert all(edge.get("supporting_chunk_ids") for edge in graph["edges"])


def test_runtime_abstains_when_query_has_no_canonical_support(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    assert (
        select_canonical_graph(
            query="Explain photosynthesis",
            rag_chunks=[{"parent_chunk_id": "ai-eng:p42:pc0"}],
            artifacts=artifacts,
        )
        is None
    )


def test_runtime_selects_architecture_from_explicit_architecture_query(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    graph = select_canonical_graph(
        query="Show the system architecture and request flow",
        rag_chunks=[{"parent_chunk_id": "ai-eng:p473:pc0"}],
        artifacts=artifacts,
    )

    assert graph is not None
    assert graph["graph_type"] == "architecture"
    assert 5 <= len(graph["nodes"]) <= 10
    assert len(graph["edges"]) >= 2
    assert graph.get("groups")


def test_runtime_classifies_arbitrary_applied_domains_as_architecture():
    # Domain customisation is handled by the applied-design worker. The
    # canonical runtime only chooses the correct layer; it no longer contains a
    # hard-coded customer-support architecture unavailable to other domains.
    assert choose_layer("multi-agent customer support chatbot architecture") == "architecture"
    assert choose_layer("growth marketing agent system that optimizes targeting") == "architecture"


def test_runtime_abstains_when_specific_architecture_topic_is_unsupported(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    assert (
        select_canonical_graph(
            query="Show Kubernetes architecture",
            rag_chunks=[{"parent_chunk_id": "ai-eng:p473:pc0"}],
            artifacts=artifacts,
        )
        is None
    )


def test_runtime_includes_cross_layer_edges_when_query_requests_mapping(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    graph = select_canonical_graph(
        query="Map concepts to architecture for retrieval",
        rag_chunks=[{"parent_chunk_id": "ai-eng:p473:pc0"}],
        artifacts=artifacts,
    )

    assert graph is not None
    assert graph["graph_type"] == "architecture"
    assert 5 <= len(graph["nodes"]) <= 10
    assert {node["layer"] for node in graph["nodes"]} == {"architecture", "concept"}
    assert any(edge.get("relation") == "implements" for edge in graph["edges"])


def test_build_rejects_improves_edge_when_metric_gets_worse(tmp_path):
    parent_docs_path = tmp_path / "parent_docs.pkl"
    output_dir = tmp_path / "graph"
    docs = [
        _doc(
            "Generation increases Latency. Generation improves Quality. "
            "Generation improves Tokenization. "
            "Pruning isn't to reduce the Memory footprint or Latency, but to improve performance. "
            "Language Model serving can improve the volume of processed requests while adhering to Latency requirements. "
            "Customer-facing Code Generation requires lower Latency. "
            "Evaluation prompts mention response Quality and increase API calls. "
            "Accuracy requires Memory. Generation validates Planning. "
            "Caching reduces Latency.",
            112,
            0,
        )
    ]
    with parent_docs_path.open("wb") as handle:
        pickle.dump(docs, handle)

    build_canonical_graph(parent_docs_path, output_dir, SCHEMA_DIR)
    artifacts = load_canonical_graph(output_dir)

    assert "concept:generation__improves__concept:latency" not in artifacts.edges
    assert "concept:generation__improves__concept:tokenization" not in artifacts.edges
    assert "concept:memory__improves__concept:latency" not in artifacts.edges
    assert "concept:language_model__improves__concept:latency" not in artifacts.edges
    assert "concept:model_serving__improves__concept:latency" not in artifacts.edges
    assert "concept:evaluation__improves__concept:quality" not in artifacts.edges
    assert "concept:accuracy__depends_on__concept:memory" not in artifacts.edges
    assert "concept:generation__evaluates__concept:planning" not in artifacts.edges
    assert "concept:generation__improves__concept:quality" in artifacts.edges
    assert "concept:caching__improves__concept:latency" in artifacts.edges


def test_runtime_abstains_when_chunk_support_is_missing(tmp_path):
    artifacts, _ = _build_test_artifacts(tmp_path)

    assert choose_layer("How does PEFT work?") == "concept"
    assert choose_layer("Show the deployment request flow") == "architecture"
    assert (
        select_canonical_graph(
            query="Explain a topic with no retrieved support",
            rag_chunks=[{"parent_chunk_id": "ai-eng:p999:pc0"}],
            artifacts=artifacts,
        )
        is None
    )
