"""Author-owned scene source snapshots, independent of production receipts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping


def source_reference_snapshot(references: Iterable[Mapping]) -> list[dict]:
    """Keep the 1.0 wire shape without importing run-owned consumption state."""
    snapshots = []
    for reference in references:
        row = dict(reference)
        source = row.get("source_snapshot")
        if source is None:
            source = json.loads(row.get("source_snapshot_json") or "{}")
        snapshots.append(
            {
                "reference_id": row["id"],
                "asset_kind": row["asset_kind"],
                "source_type": row["source_type"],
                "source_asset_id": row["source_asset_id"],
                "display_name": row["display_name"],
                "source_version": row["source_version"],
                "content_hash": row["content_hash"],
                "content_hash_kind": row["content_hash_kind"],
                "source_snapshot": source,
                # Retained for existing schema consumers; copies belong to a run.
                "production_copy": None,
            }
        )
    return snapshots
