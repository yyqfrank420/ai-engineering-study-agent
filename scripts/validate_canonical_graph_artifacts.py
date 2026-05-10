from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

_SETTINGS_DEFAULTS = {
    "ANTHROPIC_API_KEY": "ci-dummy",
    "OPENAI_API_KEY": "ci-dummy",
    "SUPABASE_URL": "https://ci-dummy.supabase.co",
    "SUPABASE_ANON_KEY": "ci-dummy",
    "SUPABASE_DB_URL": "postgresql://ci:ci@localhost:5432/ci",
    "SUPABASE_JWT_ISSUER": "https://ci-dummy.supabase.co/auth/v1",
    "SUPABASE_JWT_SECRET": "ci-dummy-secret-at-least-32-characters-long",
    "TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
    "FAISS_ARTIFACT_URL": "https://ci-dummy.example.com/faiss.tar.gz",
    "FAISS_ARTIFACT_SHA256": "0" * 64,
    "FRONTEND_ORIGIN": "http://localhost:5173",
}

for key, value in _SETTINGS_DEFAULTS.items():
    os.environ.setdefault(key, value)


ARTIFACT_FILES = (
    "concepts.json",
    "architecture_nodes.json",
    "edges.json",
    "chunk_links.json",
    "relations.json",
    "build_report.json",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_build_report(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized.pop("built_at", None)
    return normalized


def _normalize_payload(filename: str, payload: Any) -> Any:
    if filename == "build_report.json":
        if not isinstance(payload, dict):
            raise TypeError("build_report.json must contain an object")
        return _normalize_build_report(payload)
    return payload


def validate_artifacts(parent_docs: Path, artifact_dir: Path, schema_dir: Path) -> None:
    from graph.build import build_canonical_graph

    with tempfile.TemporaryDirectory(prefix="canonical-graph-ci-") as temp_dir:
        generated_dir = Path(temp_dir)
        build_canonical_graph(parent_docs, generated_dir, schema_dir)

        mismatches: list[str] = []
        for filename in ARTIFACT_FILES:
            expected_path = artifact_dir / filename
            generated_path = generated_dir / filename
            if not expected_path.exists():
                mismatches.append(f"missing committed artifact: {expected_path}")
                continue
            if not generated_path.exists():
                mismatches.append(f"builder did not produce artifact: {generated_path}")
                continue

            expected = _normalize_payload(filename, _load_json(expected_path))
            generated = _normalize_payload(filename, _load_json(generated_path))
            if expected != generated:
                mismatches.append(f"{filename} differs from a fresh canonical graph build")

        if mismatches:
            details = "\n".join(f"- {message}" for message in mismatches)
            raise SystemExit(f"Canonical graph artifacts are stale or invalid:\n{details}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate canonical graph artifacts and compare them with committed data/graph files."
    )
    parser.add_argument("--parent-docs", type=Path, default=Path("data/faiss/parent_docs.pkl"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/graph"))
    parser.add_argument("--schema-dir", type=Path, default=Path("data/graph_schema"))
    args = parser.parse_args()
    validate_artifacts(args.parent_docs, args.artifact_dir, args.schema_dir)


if __name__ == "__main__":
    main()
