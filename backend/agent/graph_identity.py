"""Deterministic identities for newly created applied graph edges."""

from hashlib import sha256
import re


def applied_edge_metadata(source: str, target: str, label: str) -> dict[str, str]:
    # Match generic edge equality; casefold would merge separately admitted labels.
    normalized_label = label.strip().lower()
    readable = re.sub(r"[^a-z0-9]+", "_", normalized_label).strip("_")[:39]
    digest = sha256(normalized_label.encode("utf-8")).hexdigest()[:24]
    relation = f"{readable or 'relation'}_{digest}"
    return {
        "edge_id": f"applied:{source}__{relation}__{target}",
        "relation": relation,
    }
