import hashlib
import stat
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

from config import settings

REQUIRED_FAISS_FILES = ("index.faiss", "index.pkl", "parent_docs.pkl")


def has_required_faiss_files(faiss_dir: Path | None = None) -> bool:
    target_dir = faiss_dir or settings.faiss_dir
    return all((target_dir / name).exists() for name in REQUIRED_FAISS_FILES)


def ensure_faiss_artifacts() -> Path:
    faiss_dir = settings.faiss_dir
    if has_required_faiss_files(faiss_dir):
        return faiss_dir

    artifact_url = settings.faiss_artifact_url.strip()
    if not artifact_url:
        missing = ", ".join(str(faiss_dir / name) for name in REQUIRED_FAISS_FILES)
        raise FileNotFoundError(
            "Missing FAISS artifacts and FAISS_ARTIFACT_URL is not configured. "
            f"Expected files: {missing}"
        )

    faiss_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faiss-artifact-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        archive_path = temp_dir / _artifact_filename(artifact_url)
        _download_artifact(artifact_url, archive_path)
        expected_sha256 = settings.faiss_artifact_sha256.strip()
        if not expected_sha256:
            raise ValueError("FAISS_ARTIFACT_SHA256 is required when downloading FAISS artifacts")
        _verify_checksum(archive_path, expected_sha256)
        extracted_dir = temp_dir / "extracted"
        extracted_dir.mkdir()
        _extract_archive(archive_path, extracted_dir)
        _copy_required_files(extracted_dir, faiss_dir)

    if not has_required_faiss_files(faiss_dir):
        raise FileNotFoundError(
            "Downloaded FAISS artifact bundle did not contain the required files: "
            + ", ".join(REQUIRED_FAISS_FILES)
        )
    return faiss_dir


def _artifact_filename(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "faiss-artifact.tar.gz"


def _download_artifact(url: str, destination: Path) -> None:
    timeout = httpx.Timeout(settings.faiss_artifact_timeout_s)
    downloaded_bytes = 0
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes():
                if chunk:
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > settings.faiss_artifact_max_download_bytes:
                        raise ValueError(
                            "FAISS artifact download exceeds configured size limit "
                            f"({settings.faiss_artifact_max_download_bytes} bytes)"
                        )
                    output.write(chunk)


def _verify_checksum(archive_path: Path, expected_sha256: str) -> None:
    if not expected_sha256:
        return

    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    actual = digest.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise ValueError(
            f"FAISS artifact checksum mismatch: expected {expected_sha256}, got {actual}"
        )


def _extract_archive(archive_path: Path, destination: Path) -> None:
    name = archive_path.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            _validate_archive_limits(
                file_count=len(members),
                extracted_bytes=sum(member.size for member in members if member.isfile()),
            )
            for member in members:
                _validate_extraction_path(destination, member.name)
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f"Unsupported entry in FAISS artifact archive: {member.name}")
            archive.extractall(destination, filter="data")
        return
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            _validate_archive_limits(
                file_count=len(members),
                extracted_bytes=sum(member.file_size for member in members if not member.is_dir()),
            )
            for member in members:
                _validate_extraction_path(destination, member.filename)
                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise ValueError(
                        f"Unsupported entry in FAISS artifact archive: {member.filename}"
                    )
            for member in members:
                target = destination / member.filename
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return
    raise ValueError(
        "Unsupported FAISS artifact archive format. Use .tar.gz, .tgz, .tar, or .zip."
    )


def _copy_required_files(extracted_dir: Path, faiss_dir: Path) -> None:
    located_files = {}
    for required_name in REQUIRED_FAISS_FILES:
        matches = [path for path in extracted_dir.rglob(required_name) if path.is_file()]
        if not matches:
            raise FileNotFoundError(f"Missing {required_name} in extracted FAISS artifact bundle")
        if len(matches) > 1:
            raise ValueError(f"Duplicate {required_name} files in FAISS artifact bundle")
        match = matches[0]
        if match.is_symlink():
            raise ValueError(f"Unsupported symlink in FAISS artifact bundle: {required_name}")
        located_files[required_name] = match

    for required_name, source in located_files.items():
        destination = faiss_dir / required_name
        shutil.copy2(source, destination)


def _validate_extraction_path(destination: Path, member_name: str) -> None:
    target_path = (destination / member_name).resolve()
    destination_root = destination.resolve()
    if destination_root != target_path and destination_root not in target_path.parents:
        raise ValueError(f"Unsafe path in FAISS artifact archive: {member_name}")


def _validate_archive_limits(*, file_count: int, extracted_bytes: int) -> None:
    if file_count > settings.faiss_artifact_max_files:
        raise ValueError(
            "FAISS artifact contains too many entries "
            f"({file_count} > {settings.faiss_artifact_max_files})"
        )
    if extracted_bytes > settings.faiss_artifact_max_extracted_bytes:
        raise ValueError(
            "FAISS artifact expands beyond configured size limit "
            f"({extracted_bytes} > {settings.faiss_artifact_max_extracted_bytes} bytes)"
        )
