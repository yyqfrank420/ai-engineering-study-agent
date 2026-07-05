import json

import pytest
from langchain_core.documents import Document

from agent.tools.graph_worker_tools.generate_graph_tool import generate_graph
from agent.tools.graph_worker_tools.get_section_tool import make_get_section_tool as make_graph_get_section_tool
from agent.tools.node_detail_worker_tools.get_section_tool import make_get_section_tool as make_node_get_section_tool
from agent.tools.rag_worker_tools.get_section_tool import make_get_section_tool as make_rag_get_section_tool
from agent.tools.rag_worker_tools.rag_search_tool import make_rag_search_tool


def _doc(text: str, **metadata):
    return Document(page_content=text, metadata=metadata)


def test_generate_graph_adds_optional_node_defaults_and_groups():
    payload = json.loads(
        generate_graph.invoke(
            {
                "graph_type": "architecture",
                "title": "RAG Pipeline",
                "nodes": [
                    {
                        "id": "retriever",
                        "label": "Retriever",
                        "type": "service",
                        "technology": "FAISS",
                        "description": "Finds chunks.",
                    }
                ],
                "edges": [
                    {
                        "source": "retriever",
                        "target": "llm",
                        "label": "sends context",
                        "technology": "Python",
                        "sync": "sync",
                        "description": "Context enters synthesis.",
                    }
                ],
                "sequence": [{"step": 1, "nodes": ["retriever"], "description": "Retrieve."}],
                "groups": [{"id": "backend", "label": "Backend", "nodeIds": ["retriever"]}],
            }
        )
    )

    assert payload["nodes"][0]["detail"] is None
    assert payload["nodes"][0]["tier"] is None
    assert payload["nodes"][0]["lane"] is None
    assert payload["groups"] == [{"id": "backend", "label": "Backend", "nodeIds": ["retriever"]}]


def test_generate_graph_rejects_malformed_nodes_and_edges():
    with pytest.raises(ValueError, match="Node missing required fields"):
        generate_graph.invoke(
            {
                "graph_type": "concept",
                "title": "Bad",
                "nodes": [{"id": "missing-fields"}],
                "edges": [],
                "sequence": [],
            }
        )

    with pytest.raises(ValueError, match="Edge missing required fields"):
        generate_graph.invoke(
            {
                "graph_type": "concept",
                "title": "Bad",
                "nodes": [
                    {
                        "id": "n1",
                        "label": "Node",
                        "type": "service",
                        "technology": "Python",
                        "description": "Works.",
                    }
                ],
                "edges": [{"source": "n1", "target": "n2"}],
                "sequence": [],
            }
        )


@pytest.mark.parametrize(
    "factory",
    [make_rag_get_section_tool, make_graph_get_section_tool, make_node_get_section_tool],
)
def test_get_section_tools_filter_by_book_chapter_and_section(factory):
    parent_docs = [
        _doc(
            "RAG details",
            book="AI Engineering",
            chapter=6,
            chapter_title="RAG and Agents",
            section="Retrieval-Augmented Generation",
            page_number=299,
            parent_chunk_index=3,
        ),
        _doc(
            "Agent details",
            book="AI Engineering",
            chapter=6,
            chapter_title="RAG and Agents",
            section="Agents",
            page_number=329,
            parent_chunk_index=8,
        ),
        _doc(
            "Wrong book",
            book="Other",
            chapter=6,
            section="Retrieval-Augmented Generation",
            page_number=1,
            parent_chunk_index=1,
        ),
    ]

    tool = factory(parent_docs)
    result = json.loads(
        tool.invoke(
            {
                "book": "AI Engineering",
                "chapter": 6,
                "section": "retrieval",
            }
        )
    )

    assert len(result) == 1
    assert result[0]["text"] == "RAG details"
    if "parent_chunk_id" in result[0]:
        assert result[0]["parent_chunk_id"]


def test_get_section_tools_cap_results_at_five():
    docs = [
        _doc(
            f"Section {index}",
            book="AI Engineering",
            chapter=6,
            section="Agents",
            page_number=index,
            parent_chunk_index=index,
        )
        for index in range(7)
    ]

    tool = make_rag_get_section_tool(docs)

    assert len(json.loads(tool.invoke({"book": "AI Engineering", "chapter": 6, "section": None}))) == 5


def test_rag_search_tool_formats_retrieved_documents(monkeypatch):
    retrieved = [
        _doc(
            "Parent text",
            book="AI Engineering",
            chapter=6,
            chapter_title="RAG and Agents",
            section="Agents",
            page_number=329,
            parent_chunk_index=8,
        )
    ]
    calls = []

    def fake_retrieve(vectorstore, parent_docs, query, k, filter=None):
        calls.append((vectorstore, parent_docs, query, k, filter))
        return retrieved

    monkeypatch.setattr("rag.faiss_retriever.retrieve", fake_retrieve)
    vectorstore = object()
    parent_docs = [object()]
    tool = make_rag_search_tool(vectorstore, parent_docs)

    payload = json.loads(tool.invoke({"query": "agents", "k": 4}))

    assert calls == [(vectorstore, parent_docs, "agents", 4, None)]
    assert payload == [
        {
            "text": "Parent text",
            "book": "AI Engineering",
            "chapter": 6,
            "chapter_title": "RAG and Agents",
            "section": "Agents",
            "page_number": 329,
            "parent_chunk_index": 8,
            "parent_chunk_id": "ai-eng:p329:pc8",
        }
    ]
