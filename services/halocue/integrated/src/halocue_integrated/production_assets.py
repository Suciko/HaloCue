from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


ASSET_KIND_TO_RESOURCE_KIND = {
    "background": "backgrounds",
    "sound": "sounds",
    "character": "characters",
    "cg": "cg",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_hash(value: Any) -> str:
    digest = str(value or "").strip().casefold()
    return digest.removeprefix("sha256:")


class IntegratedProductionService(ProductionService):
    """Own the versioned scene-asset handoff at the 09/08 integration boundary."""

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._asset_receipt_dir = Path(settings.data_dir) / "scene-asset-receipts"

    def capabilities(self) -> dict[str, Any]:
        capabilities = super().capabilities()
        capabilities["scene_asset_handoff"] = {
            "state": "available",
            "schema_version": "production-asset-handoff/1.0",
            "receipt_schema_version": "production-asset-usage/1.0",
            "source_types": ["resource_index", "custom_library"],
            "requires_identity_match": True,
        }
        return capabilities

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        references = self._validate_asset_handoff(payload)
        result = super().create_run(payload)
        if not references:
            return result

        run_id = str(
            result.get("run_id")
            or result.get("run", {}).get("run_id")
            or ""
        )
        if not run_id:
            raise ProductionError(
                "production_asset_run_missing",
                "ProductionRun was created without a stable run ID.",
                status=500,
            )
        receipt = self._build_asset_receipt(run_id, references)
        self._write_asset_receipt(run_id, receipt)
        result["asset_handoff"] = {
            "status": "complete",
            "schema_version": "production-asset-handoff/1.0",
            "receipt_schema_version": receipt["schema_version"],
            "confirmed_count": len(receipt["references"]),
        }
        return result

    def resource_usage(self, run_id: str) -> dict[str, Any]:
        receipt = self._read_asset_receipt(run_id)
        if receipt is not None:
            return receipt
        return super().resource_usage(run_id)

    def _validate_asset_handoff(self, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        handoff = payload.get("asset_handoff")
        if handoff is None:
            return []
        if not isinstance(handoff, dict) or handoff.get("schema_version") != "production-asset-handoff/1.0":
            raise ProductionError("invalid_asset_handoff", "Scene asset handoff schema is invalid.")

        release = payload.get("script_release")
        if not isinstance(release, dict):
            raise ProductionError("invalid_asset_handoff", "Scene assets require a ScriptRelease identity.")
        if handoff.get("release_id") != release.get("id"):
            raise ProductionError("asset_handoff_identity_mismatch", "Asset handoff release ID does not match ScriptRelease.", status=409)
        if handoff.get("source_set_digest") != release.get("source_set_digest"):
            raise ProductionError("asset_handoff_identity_mismatch", "Asset handoff source digest does not match ScriptRelease.", status=409)

        groups = handoff.get("references")
        if not isinstance(groups, list) or not groups:
            raise ProductionError("invalid_asset_handoff", "Scene asset handoff references are missing.")
        normalized: list[tuple[str, dict[str, Any]]] = []
        identities: set[tuple[str, str]] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ProductionError("invalid_asset_handoff", "Scene asset handoff group is invalid.")
            scene_id = str(group.get("scene_id") or "").strip()
            refs = group.get("references")
            if not scene_id or not isinstance(refs, list):
                raise ProductionError("invalid_asset_handoff", "Scene asset handoff group is incomplete.")
            if group.get("digest") != _sha256_text(_canonical_json(refs)):
                raise ProductionError("asset_handoff_digest_mismatch", "Scene asset reference digest does not match the frozen release.", status=409)
            for reference in refs:
                self._validate_reference(scene_id, reference)
                identity = (scene_id, str(reference["reference_id"]))
                if identity in identities:
                    raise ProductionError("asset_handoff_identity_mismatch", "Scene asset handoff contains a duplicate reference.", status=409)
                identities.add(identity)
                normalized.append((scene_id, dict(reference)))
        return normalized

    def _validate_reference(self, scene_id: str, reference: Any) -> None:
        if not isinstance(reference, dict):
            raise ProductionError("invalid_asset_handoff", "Scene asset reference is invalid.")
        required = (
            "reference_id",
            "asset_kind",
            "source_type",
            "source_asset_id",
            "source_version",
            "content_hash",
            "content_hash_kind",
        )
        if not scene_id or any(not str(reference.get(field) or "").strip() for field in required):
            raise ProductionError("invalid_asset_handoff", "Scene asset reference identity is incomplete.")
        if reference.get("production_copy") is not None:
            raise ProductionError("asset_handoff_preclaimed_copy", "Writing cannot pre-claim a ProductionRun asset copy.", status=409)
        kind = str(reference["asset_kind"])
        if kind not in ASSET_KIND_TO_RESOURCE_KIND:
            raise ProductionError("invalid_asset_handoff", "Scene asset kind is unsupported.")
        source_type = str(reference["source_type"])
        if source_type == "resource_index":
            self._validate_resource_index_reference(reference)
        elif source_type == "custom_library":
            asset = self.custom_asset_detail(str(reference["source_asset_id"])).get("asset", {})
            snapshot = reference.get("source_snapshot")
            source_id = str(reference["source_asset_id"])
            if (
                str(asset.get("asset_id") or "") != source_id
                or str(asset.get("kind") or "") != kind
                or not isinstance(snapshot, dict)
                or str(snapshot.get("source") or "") != "custom_library"
                or str(snapshot.get("asset_id") or "") != source_id
                or str(snapshot.get("metadata_version") or "") != str(reference["source_version"])
                or str(reference.get("content_hash_kind") or "") != "file_sha256"
                or not _normalized_hash(asset.get("sha256"))
                or _normalized_hash(asset.get("sha256")) != _normalized_hash(reference.get("content_hash"))
                or _normalized_hash(snapshot.get("sha256")) != _normalized_hash(reference.get("content_hash"))
            ):
                raise ProductionError(
                    "asset_handoff_source_mismatch",
                    "Custom asset identity, version, or hash does not match the frozen reference.",
                    status=409,
                )
        else:
            raise ProductionError("invalid_asset_handoff", "Scene asset source type is unsupported.")

    def _validate_resource_index_reference(self, reference: dict[str, Any]) -> None:
        source_id = str(reference["source_asset_id"])
        kind = ASSET_KIND_TO_RESOURCE_KIND[str(reference["asset_kind"])]
        catalog = self.list_resources(kind, query=source_id, offset=0, limit=200)
        item = next(
            (
                candidate
                for candidate in catalog.get("items", [])
                if str(candidate.get("key") or candidate.get("identifier") or "") == source_id
            ),
            None,
        )
        if item is None:
            raise ProductionError("asset_handoff_source_missing", "Referenced AA asset is not present in the production catalog.", status=409)
        snapshot = reference.get("source_snapshot")
        if not isinstance(snapshot, dict) or str(snapshot.get("key") or snapshot.get("asset_id") or "") != source_id:
            raise ProductionError("asset_handoff_source_mismatch", "AA asset snapshot identity does not match the frozen reference.", status=409)
        if item.get("aa_hash") is not None and str(reference.get("content_hash")) != str(item["aa_hash"]):
            raise ProductionError("asset_handoff_source_mismatch", "AA asset hash does not match the current production catalog.", status=409)

    def _build_asset_receipt(
        self,
        run_id: str,
        references: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        run = self._run(run_id)
        token = str(run.draft_token or "")
        receipts = []
        for scene_id, reference in references:
            source_type = str(reference["source_type"])
            if source_type == "custom_library":
                task_copy = self._attach_custom_copy(run_id, str(reference["source_asset_id"]))
                copy_id = str(task_copy.get("asset_id") or "")
                copy_hash = str(task_copy.get("sha256") or reference["content_hash"])
                if copy_hash and not copy_hash.startswith("sha256:") and len(copy_hash) == 64:
                    copy_hash = "sha256:" + copy_hash
            else:
                resource_kind = ASSET_KIND_TO_RESOURCE_KIND[str(reference["asset_kind"])]
                source_id = str(reference["source_asset_id"])
                if not self.adapter.draft_resource_contains(token, resource_kind, source_id):
                    raise ProductionError("production_asset_snapshot_missing", "Referenced AA asset was not frozen into the ProductionRun snapshot.", status=409)
                seed = f"{run_id}:{scene_id}:{reference['reference_id']}:{source_id}"
                copy_id = "copy-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
                copy_hash = str(reference["content_hash"])
            receipts.append(
                {
                    "scene_id": scene_id,
                    "reference_id": reference["reference_id"],
                    "source_asset_id": reference["source_asset_id"],
                    "source_version": reference["source_version"],
                    "content_hash": reference["content_hash"],
                    "production_copy": {
                        "copy_id": copy_id,
                        "content_hash": copy_hash,
                        "content_hash_kind": reference["content_hash_kind"],
                    },
                }
            )
        return {
            "schema_version": "production-asset-usage/1.0",
            "production_run_id": run_id,
            "references": receipts,
        }

    def _attach_custom_copy(self, run_id: str, library_asset_id: str) -> dict[str, Any]:
        existing = next(
            (
                item
                for item in self.task_assets(run_id).get("items", [])
                if item.get("library_asset_id") == library_asset_id
            ),
            None,
        )
        if existing is not None:
            return existing
        detail = self.run_detail(run_id)
        draft_version = int(detail.get("draft", {}).get("session", {}).get("draft_version", -1))
        if draft_version < 0:
            raise ProductionError("production_asset_snapshot_missing", "ProductionRun draft version is unavailable.", status=409)
        self.attach_custom_asset(
            run_id,
            library_asset_id,
            {"expected_draft_version": draft_version},
        )
        copied = next(
            (
                item
                for item in self.task_assets(run_id).get("items", [])
                if item.get("library_asset_id") == library_asset_id
            ),
            None,
        )
        if copied is None:
            raise ProductionError("production_asset_snapshot_missing", "Custom asset was not copied into the ProductionRun.", status=409)
        return copied

    def _receipt_path(self, run_id: str) -> Path:
        return self._asset_receipt_dir / f"{run_id}.json"

    def _write_asset_receipt(self, run_id: str, receipt: dict[str, Any]) -> None:
        self._asset_receipt_dir.mkdir(parents=True, exist_ok=True)
        path = self._receipt_path(run_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _read_asset_receipt(self, run_id: str) -> dict[str, Any] | None:
        path = self._receipt_path(run_id)
        if not path.is_file():
            return None
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError("production_asset_receipt_corrupt", "ProductionRun asset receipt is unreadable.", status=500) from exc
        if receipt.get("schema_version") != "production-asset-usage/1.0" or receipt.get("production_run_id") != run_id:
            raise ProductionError("production_asset_receipt_corrupt", "ProductionRun asset receipt identity is invalid.", status=500)
        return receipt
