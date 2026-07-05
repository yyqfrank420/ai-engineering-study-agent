import importlib
import pickle
import sys
import types

from langchain_core.documents import Document

from config import settings
from rag.faiss_retriever import _find_parent, retrieve


class _FakeVectorstore:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def similarity_search(self, query, k, filter=None):
        self.calls.append({"query": query, "k": k, "filter": filter})
        return self.results


def _doc(text, **metadata):
    return Document(page_content=text, metadata=metadata)


def test_retrieve_expands_child_hits_to_unique_parent_documents():
    parent_a = _doc("parent A", book="AI Engineering", chapter=6, page_number=299, parent_chunk_index=1)
    parent_b = _doc("parent B", book="AI Engineering", chapter=6, page_number=300, parent_chunk_index=2)
    child_a1 = _doc("child A1", book="AI Engineering", chapter=6, page_number=299, parent_chunk_index=1)
    child_a2 = _doc("child A2", book="AI Engineering", chapter=6, page_number=299, parent_chunk_index=1)
    child_b = _doc("child B", book="AI Engineering", chapter=6, page_number=300, parent_chunk_index=2)
    vectorstore = _FakeVectorstore([child_a1, child_a2, child_b])

    parents = retrieve(
        vectorstore,
        [parent_a, parent_b],
        "retrieval augmented generation",
        k=3,
        filter={"chapter": 6},
    )

    assert parents == [parent_a, parent_b]
    assert vectorstore.calls == [
        {
            "query": "retrieval augmented generation",
            "k": 3,
            "filter": {"chapter": 6},
        }
    ]


def test_retrieve_skips_child_hits_without_matching_parent():
    parent = _doc("parent", book="AI Engineering", chapter=6, page_number=299, parent_chunk_index=1)
    orphan_child = _doc("orphan", book="AI Engineering", chapter=7, page_number=350, parent_chunk_index=9)
    vectorstore = _FakeVectorstore([orphan_child])

    assert retrieve(vectorstore, [parent], "query") == []


def test_find_parent_matches_all_parent_metadata_keys():
    parent = _doc("parent", book="AI Engineering", chapter=6, page_number=299, parent_chunk_index=1)

    assert _find_parent(
        [parent],
        {"book": "AI Engineering", "chapter": 6, "page_number": 299, "parent_chunk_index": 1},
    ) == parent
    assert _find_parent(
        [parent],
        {"book": "AI Engineering", "chapter": 6, "page_number": 300, "parent_chunk_index": 1},
    ) is None


def test_load_faiss_loads_vectorstore_and_parent_docs(temp_data_dir, monkeypatch):
    fake_sentence_module = types.ModuleType("rag.sentence_embedder")

    class FakeSentenceEmbedder:
        pass

    fake_sentence_module.SentenceEmbedder = FakeSentenceEmbedder
    monkeypatch.setitem(sys.modules, "rag.sentence_embedder", fake_sentence_module)

    import rag.faiss_loader as faiss_loader

    faiss_loader = importlib.reload(faiss_loader)
    faiss_dir = settings.faiss_dir
    faiss_dir.mkdir(parents=True)
    (faiss_dir / "index.faiss").write_bytes(b"index")
    (faiss_dir / "index.pkl").write_bytes(b"pickle")
    parent_docs = [_doc("parent", book="AI Engineering")]
    with (faiss_dir / "parent_docs.pkl").open("wb") as handle:
        pickle.dump(parent_docs, handle)

    loaded = object()
    calls = []

    def fake_load_local(path, embedder, allow_dangerous_deserialization):
        calls.append(
            {
                "path": path,
                "embedder_type": type(embedder),
                "allow_dangerous_deserialization": allow_dangerous_deserialization,
            }
        )
        return loaded

    monkeypatch.setattr(faiss_loader.FAISS, "load_local", fake_load_local)

    vectorstore, loaded_parent_docs = faiss_loader.load_faiss()

    assert vectorstore is loaded
    assert loaded_parent_docs == parent_docs
    assert calls == [
        {
            "path": str(faiss_dir),
            "embedder_type": FakeSentenceEmbedder,
            "allow_dangerous_deserialization": True,
        }
    ]


def test_load_faiss_fails_fast_when_required_file_missing(temp_data_dir, monkeypatch):
    fake_sentence_module = types.ModuleType("rag.sentence_embedder")
    fake_sentence_module.SentenceEmbedder = object
    monkeypatch.setitem(sys.modules, "rag.sentence_embedder", fake_sentence_module)

    import rag.faiss_loader as faiss_loader

    faiss_loader = importlib.reload(faiss_loader)
    settings.faiss_dir.mkdir(parents=True)
    (settings.faiss_dir / "index.faiss").write_bytes(b"index")

    try:
        faiss_loader.load_faiss()
    except FileNotFoundError as exc:
        assert "index.pkl" in str(exc)
    else:
        raise AssertionError("expected missing FAISS file to raise")
