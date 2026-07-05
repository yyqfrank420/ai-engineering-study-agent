import hashlib
import io
import tarfile
import zipfile

import pytest

from config import settings


def _write_required_files(root):
    for name in ("index.faiss", "index.pkl", "parent_docs.pkl"):
        path = root / name
        path.write_bytes(f"{name}-bytes".encode("utf-8"))


def test_ensure_faiss_artifacts_returns_existing_directory(tmp_path, monkeypatch):
    from rag.faiss_artifact import ensure_faiss_artifacts

    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    _write_required_files(faiss_dir)
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    assert ensure_faiss_artifacts() == faiss_dir


def test_ensure_faiss_artifacts_requires_url_when_files_missing(tmp_path, monkeypatch):
    from rag.faiss_artifact import ensure_faiss_artifacts

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "faiss_artifact_url", " ")

    with pytest.raises(FileNotFoundError, match="FAISS_ARTIFACT_URL"):
        ensure_faiss_artifacts()


def test_ensure_faiss_artifacts_requires_checksum_for_download(tmp_path, monkeypatch):
    from rag import faiss_artifact

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "faiss_artifact_url", "https://example.com/faiss.zip")
    monkeypatch.setattr(settings, "faiss_artifact_sha256", "")
    monkeypatch.setattr(faiss_artifact, "_download_artifact", lambda _url, destination: destination.write_bytes(b"zip"))

    with pytest.raises(ValueError, match="FAISS_ARTIFACT_SHA256"):
        faiss_artifact.ensure_faiss_artifacts()


def test_extract_archive_rejects_unsupported_and_unsafe_paths(tmp_path):
    from rag.faiss_artifact import _extract_archive, _validate_extraction_path

    with pytest.raises(ValueError, match="Unsupported"):
        _extract_archive(tmp_path / "artifact.rar", tmp_path)

    with pytest.raises(ValueError, match="Unsafe path"):
        _validate_extraction_path(tmp_path, "../escape.pkl")

    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.pkl", "bad")
    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive_path, tmp_path / "out")


def test_extract_zip_and_copy_required_files(tmp_path):
    from rag.faiss_artifact import _copy_required_files, _extract_archive

    source = tmp_path / "source"
    source.mkdir()
    nested = source / "nested"
    nested.mkdir()
    _write_required_files(nested)
    archive_path = tmp_path / "faiss.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file_path in nested.iterdir():
            archive.write(file_path, arcname=f"bundle/{file_path.name}")

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    destination = tmp_path / "faiss"
    destination.mkdir()

    _extract_archive(archive_path, extracted)
    _copy_required_files(extracted, destination)

    assert sorted(path.name for path in destination.iterdir()) == ["index.faiss", "index.pkl", "parent_docs.pkl"]


def test_copy_required_files_reports_first_missing_file(tmp_path):
    from rag.faiss_artifact import _copy_required_files

    with pytest.raises(FileNotFoundError, match="Missing index.faiss"):
        _copy_required_files(tmp_path, tmp_path / "faiss")


def test_download_and_extract_tar_archive(tmp_path, monkeypatch):
    from rag import faiss_artifact

    source = tmp_path / "source"
    source.mkdir()
    _write_required_files(source)
    archive_path = tmp_path / "faiss.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for file_path in source.iterdir():
            archive.add(file_path, arcname=f"bundle/{file_path.name}")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield archive_path.read_bytes()
            yield b""

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "faiss_artifact_url", "https://example.com/faiss.tar.gz")
    monkeypatch.setattr(settings, "faiss_artifact_sha256", digest)
    monkeypatch.setattr(faiss_artifact.httpx, "stream", lambda *args, **kwargs: _Response())

    assert faiss_artifact.ensure_faiss_artifacts() == tmp_path / "faiss"


def test_extract_tar_rejects_path_traversal(tmp_path):
    from rag.faiss_artifact import _extract_archive

    archive_path = tmp_path / "unsafe.tar"
    data = b"bad"
    info = tarfile.TarInfo("../escape.pkl")
    info.size = len(data)
    with tarfile.open(archive_path, "w") as archive:
        archive.addfile(info, io.BytesIO(data))

    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive_path, tmp_path / "out")
