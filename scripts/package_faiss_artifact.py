import argparse
import hashlib
import tarfile
from pathlib import Path

REQUIRED_FILES = ("index.faiss", "index.pkl", "parent_docs.pkl")


def package_artifact(source_dir: Path, output_path: Path) -> str:
    for name in REQUIRED_FILES:
        if not (source_dir / name).exists():
            raise FileNotFoundError(f"Missing required FAISS file: {source_dir / name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as archive:
        for name in REQUIRED_FILES:
            archive.add(source_dir / name, arcname=f"faiss/{name}")

    digest = hashlib.sha256()
    with output_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package FAISS files into a deployable artifact bundle.")
    parser.add_argument("--source-dir", type=Path, required=True, help="Directory containing index.faiss, index.pkl, parent_docs.pkl")
    parser.add_argument("--output", type=Path, required=True, help="Output .tar.gz path")
    args = parser.parse_args()

    checksum = package_artifact(args.source_dir, args.output)
    print(f"Created {args.output}")
    print(f"SHA256 {checksum}")
