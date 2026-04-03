import hashlib
import tarfile
from pathlib import Path

import pytest

from config import settings
from rag.faiss_artifact import ensure_faiss_artifacts, has_required_faiss_files


def _write_required_files(directory: Path) -> None:
    for name in ("index.faiss", "index.pkl", "parent_docs.pkl"):
        (directory / name).write_bytes(f"content-for-{name}".encode("utf-8"))


def test_has_required_faiss_files(temp_data_dir):
    faiss_dir = settings.faiss_dir
    faiss_dir.mkdir(parents=True, exist_ok=True)
    assert has_required_faiss_files(faiss_dir) is False

    _write_required_files(faiss_dir)
    assert has_required_faiss_files(faiss_dir) is True


def test_ensure_faiss_artifacts_downloads_bundle(temp_data_dir, monkeypatch, tmp_path):
    source_dir = tmp_path / "artifact-source"
    source_dir.mkdir()
    _write_required_files(source_dir)

    archive_path = tmp_path / "faiss-bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("index.faiss", "index.pkl", "parent_docs.pkl"):
            archive.add(source_dir / name, arcname=f"nested/faiss/{name}")

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    monkeypatch.setattr(settings, "faiss_artifact_url", "https://artifacts.example/faiss-bundle.tar.gz")
    monkeypatch.setattr(settings, "faiss_artifact_sha256", digest)

    def fake_download(url: str, destination: Path) -> None:
        assert url == "https://artifacts.example/faiss-bundle.tar.gz"
        destination.write_bytes(archive_path.read_bytes())

    monkeypatch.setattr("rag.faiss_artifact._download_artifact", fake_download)

    resolved = ensure_faiss_artifacts()
    assert resolved == settings.faiss_dir
    for name in ("index.faiss", "index.pkl", "parent_docs.pkl"):
        assert (resolved / name).read_bytes() == (source_dir / name).read_bytes()


def test_ensure_faiss_artifacts_rejects_bad_checksum(temp_data_dir, monkeypatch, tmp_path):
    archive_path = tmp_path / "faiss-bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        sample = tmp_path / "index.faiss"
        sample.write_text("bad-artifact")
        archive.add(sample, arcname="index.faiss")

    monkeypatch.setattr(settings, "faiss_artifact_url", "https://artifacts.example/faiss-bundle.tar.gz")
    monkeypatch.setattr(settings, "faiss_artifact_sha256", "deadbeef")
    monkeypatch.setattr(
        "rag.faiss_artifact._download_artifact",
        lambda _url, destination: destination.write_bytes(archive_path.read_bytes()),
    )

    with pytest.raises(ValueError, match="checksum mismatch"):
        ensure_faiss_artifacts()
