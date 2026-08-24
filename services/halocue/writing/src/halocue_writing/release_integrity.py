from __future__ import annotations

import json
import re
from collections.abc import Mapping

from .errors import DomainError
from .repository import canonical_json, sha256_text


SCRIPT_RELEASE_SCHEMA = "script-release/1.0"
PRODUCTION_HANDOFF_SCHEMA = "production-handoff/1.0"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANIFEST_KEYS = {
    "schema_version",
    "release_id",
    "work_id",
    "display_version",
    "content_hash",
    "writing_pack_version",
    "ba_writing_source_digest",
    "source_set_digest",
    "scenes",
    "asset_references",
    "dependency_refs",
    "memory_maintenance",
    "gate_snapshot_ids",
    "released_by",
    "released_at",
}
_SCENE_KEYS = {"scene_id", "revision_id", "title", "content_hash"}
_ASSET_REFERENCE_KEYS = {
    "reference_id",
    "asset_kind",
    "source_type",
    "source_asset_id",
    "display_name",
    "source_version",
    "content_hash",
    "content_hash_kind",
    "source_snapshot",
    "production_copy",
}
_ASSET_SCENE_KEYS = {"scene_id", "references", "digest"}
_DEPENDENCY_KEYS = {"kind", "scope_type", "scope_id", "revision_id", "content_hash"}
_MEMORY_KEYS = {
    "scene_id",
    "revision_id",
    "work_item_id",
    "status",
    "decision",
    "complete",
}


def source_set_payload(manifest: Mapping) -> dict:
    payload = {
        "scenes": manifest.get("scenes"),
        "dependencies": manifest.get("dependency_refs"),
        "memory_maintenance": manifest.get("memory_maintenance"),
        "gates": manifest.get("gate_snapshot_ids"),
        "writing_pack_version": manifest.get("writing_pack_version"),
        "ba_writing_source_digest": manifest.get("ba_writing_source_digest"),
    }
    # Releases created before scene asset freezing have no asset list. Keep
    # their source digest verifiable while including the frozen list in new
    # releases.
    if "asset_references" in manifest:
        payload["asset_references"] = manifest.get("asset_references")
    return payload


def source_set_digest(manifest: Mapping) -> str:
    return sha256_text(canonical_json(source_set_payload(manifest)))


def normalize_digest(value: str) -> str:
    value = str(value or "")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def verify_script_release(repository, release_row: Mapping) -> dict:
    release = dict(release_row)
    release_id = str(release.get("id") or "")
    try:
        manifest = json.loads(repository.read_text(release["manifest_uri"]))
        text = repository.read_text(release["content_uri"])
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _integrity_error(release_id, "release_material_unreadable") from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCRIPT_RELEASE_SCHEMA:
        raise _integrity_error(release_id, "unsupported_manifest_schema")

    _verify_manifest_shape(manifest, release_id)
    if not _valid_digest(manifest.get("ba_writing_source_digest")):
        raise _integrity_error(release_id, "writing_skill_digest_invalid")
    if not _valid_digest(manifest.get("source_set_digest")):
        raise _integrity_error(release_id, "source_set_digest_invalid")

    expected_identity = {
        "release_id": release_id,
        "work_id": release.get("work_id"),
        "display_version": release.get("display_version"),
        "content_hash": release.get("content_hash"),
        "writing_pack_version": release.get("writing_pack_version"),
        "released_by": release.get("released_by"),
        "released_at": release.get("released_at"),
    }
    if {key: manifest.get(key) for key in expected_identity} != expected_identity:
        raise _integrity_error(release_id, "database_identity_mismatch")

    actual_hash = sha256_text(text)
    if actual_hash != release.get("content_hash"):
        raise _integrity_error(release_id, "content_hash_mismatch")

    source_revision_ids = _json_list(release.get("source_revision_ids_json"), release_id)
    gate_snapshot_ids = _json_list(release.get("gate_snapshot_ids_json"), release_id)
    try:
        manifest_revision_ids = [item["revision_id"] for item in manifest["scenes"]]
    except (KeyError, TypeError) as exc:
        raise _integrity_error(release_id, "scene_reference_invalid") from exc
    if manifest_revision_ids != source_revision_ids:
        raise _integrity_error(release_id, "scene_revision_identity_mismatch")
    if not manifest_revision_ids or len(manifest_revision_ids) != len(set(manifest_revision_ids)):
        raise _integrity_error(release_id, "scene_revision_identity_invalid")
    if manifest["gate_snapshot_ids"] != gate_snapshot_ids:
        raise _integrity_error(release_id, "gate_identity_mismatch")
    if not gate_snapshot_ids or len(gate_snapshot_ids) != len(set(gate_snapshot_ids)):
        raise _integrity_error(release_id, "gate_identity_invalid")
    if source_set_digest(manifest) != manifest["source_set_digest"]:
        raise _integrity_error(release_id, "source_set_digest_mismatch")

    reconstructed_text = _verify_revision_references(repository, release_id, manifest)
    if reconstructed_text != text:
        raise _integrity_error(release_id, "release_composition_mismatch")
    gate_snapshots = _verify_gate_references(
        repository, release_id, release.get("work_id"), gate_snapshot_ids
    )
    asset_references_by_scene = {
        item["scene_id"]: item
        for item in manifest.get("asset_references", [])
    }
    expected_scene_refs = [
        {
            "scene_id": item.get("scene_id"),
            "revision_id": item.get("revision_id"),
            "content_hash": item.get("content_hash"),
            **(
                    {
                        "asset_references": asset_references_by_scene.get(item.get("scene_id"), {}).get("references", []),
                        "asset_reference_digest": asset_references_by_scene.get(item.get("scene_id"), {}).get("digest", sha256_text(canonical_json([]))),
                    }
                if "asset_references" in manifest else {}
            ),
        }
        for item in manifest["scenes"]
    ]
    for kind, snapshot in gate_snapshots:
        snapshot_matches = (
            snapshot.get("scene_revision_refs") == expected_scene_refs
            and snapshot.get("dependency_refs") == manifest["dependency_refs"]
            and snapshot.get("writing_pack_version") == manifest["writing_pack_version"]
            and normalize_digest(snapshot.get("ba_writing_source_digest"))
            == manifest["ba_writing_source_digest"]
        )
        if kind == "release.review":
            snapshot_matches = (
                snapshot_matches
                and snapshot.get("memory_maintenance") == manifest["memory_maintenance"]
            )
        if not snapshot_matches:
            raise _integrity_error(release_id, "release_gate_snapshot_mismatch")
    return {"release": release, "manifest": manifest, "text": text}


def build_production_handoff(verified_release: Mapping, project_name: str) -> dict:
    release = verified_release["release"]
    manifest = verified_release["manifest"]
    text = verified_release["text"]
    if sha256_text(text) != release.get("content_hash"):
        raise _integrity_error(str(release.get("id") or ""), "content_hash_mismatch")
    handoff = {
        "schema_version": PRODUCTION_HANDOFF_SCHEMA,
        "project": project_name,
        "generation_mode": "format_only",
        "source": {"kind": "inline", "text": text},
        "script_release": {
            "schema_version": "1.0",
            "id": release["id"],
            "work_id": release["work_id"],
            "display_version": release["display_version"],
            "content_hash": release["content_hash"].removeprefix("sha256:"),
            "writing_pack_version": release["writing_pack_version"],
            "ba_writing_source_digest": manifest["ba_writing_source_digest"],
            "source_set_digest": manifest["source_set_digest"],
        },
    }
    asset_references = manifest.get("asset_references") or []
    if asset_references:
        handoff["asset_handoff"] = {
            "schema_version": "production-asset-handoff/1.0",
            "release_id": release["id"],
            "source_set_digest": manifest["source_set_digest"],
            "references": asset_references,
        }
    return handoff


def _verify_revision_references(repository, release_id: str, manifest: Mapping) -> str:
    chunks = []
    with repository.connect() as connection:
        for ref in manifest["scenes"]:
            if not isinstance(ref, dict) or not ref.get("revision_id") or not _valid_digest(ref.get("content_hash")):
                raise _integrity_error(release_id, "revision_reference_invalid")
            row = connection.execute(
                """SELECT revision.content_hash,revision.content_uri,
                          artifact.kind,artifact.scope_type,artifact.scope_id
                   FROM revisions AS revision
                   JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                   WHERE revision.id=?""",
                (ref["revision_id"],),
            ).fetchone()
            if (
                not row
                or row["content_hash"] != ref["content_hash"]
                or row["kind"] != "scene_script"
                or row["scope_type"] != "scene"
                or row["scope_id"] != ref.get("scene_id")
            ):
                raise _integrity_error(release_id, "revision_reference_mismatch")
            raw = _verify_revision_file(repository, release_id, row)
            try:
                content = json.loads(raw)
                scene_text = content["text"]
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                raise _integrity_error(release_id, "scene_revision_material_invalid") from exc
            if not isinstance(ref.get("title"), str) or not isinstance(scene_text, str):
                raise _integrity_error(release_id, "scene_revision_material_invalid")
            chunks.append(f"## {ref['title']}\n{scene_text.rstrip()}\n")

        for ref in manifest["dependency_refs"]:
            if not isinstance(ref, dict) or not ref.get("revision_id") or not _valid_digest(ref.get("content_hash")):
                raise _integrity_error(release_id, "revision_reference_invalid")
            row = connection.execute(
                """SELECT revision.content_hash,revision.content_uri,
                          artifact.kind,artifact.scope_type,artifact.scope_id
                   FROM revisions AS revision
                   JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                   WHERE revision.id=?""",
                (ref["revision_id"],),
            ).fetchone()
            if (
                not row
                or row["content_hash"] != ref["content_hash"]
                or row["kind"] != ref.get("kind")
                or row["scope_type"] != ref.get("scope_type")
                or row["scope_id"] != ref.get("scope_id")
            ):
                raise _integrity_error(release_id, "revision_reference_mismatch")
            _verify_revision_file(repository, release_id, row)
    return "\n".join(chunks)


def _verify_revision_file(repository, release_id: str, revision) -> str:
    try:
        raw = repository.read_text(revision["content_uri"])
        actual_hash = sha256_text(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise _integrity_error(release_id, "revision_material_unreadable") from exc
    if actual_hash != revision["content_hash"]:
        raise _integrity_error(release_id, "revision_material_mismatch")
    return raw


def _verify_gate_references(
    repository, release_id: str, work_id: str, gate_ids: list
) -> list[tuple[str, dict]]:
    snapshots = []
    with repository.connect() as connection:
        for gate_id in gate_ids:
            row = connection.execute(
                "SELECT work_id,kind,status,result_json FROM gates WHERE id=?", (gate_id,)
            ).fetchone()
            if (
                not row
                or row["work_id"] != work_id
                or row["status"] != "passed"
                or row["kind"] not in {"continuity.review", "release.review"}
            ):
                raise _integrity_error(release_id, "gate_reference_mismatch")
            try:
                snapshot = json.loads(row["result_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise _integrity_error(release_id, "release_gate_invalid") from exc
            if not isinstance(snapshot, dict):
                raise _integrity_error(release_id, "release_gate_invalid")
            snapshots.append((row["kind"], snapshot))
    if [kind for kind, _ in snapshots] != ["continuity.review", "release.review"]:
        raise _integrity_error(release_id, "release_gate_missing")
    return snapshots


def _verify_manifest_shape(manifest: dict, release_id: str) -> None:
    legacy_keys = _MANIFEST_KEYS - {"asset_references"}
    manifest_keys = set(manifest)
    if manifest_keys != _MANIFEST_KEYS and manifest_keys != legacy_keys:
        raise _integrity_error(release_id, "manifest_shape_invalid")
    required_lists = ("scenes", "dependency_refs", "memory_maintenance", "gate_snapshot_ids")
    if any(not isinstance(manifest.get(key), list) for key in required_lists):
        raise _integrity_error(release_id, "manifest_shape_invalid")
    if not manifest["scenes"] or not manifest["gate_snapshot_ids"]:
        raise _integrity_error(release_id, "manifest_shape_invalid")
    if "asset_references" in manifest and not isinstance(manifest["asset_references"], list):
        raise _integrity_error(release_id, "manifest_shape_invalid")
    for key in (
        "release_id",
        "work_id",
        "display_version",
        "writing_pack_version",
        "released_by",
        "released_at",
    ):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise _integrity_error(release_id, "manifest_shape_invalid")
    if not _valid_digest(manifest.get("content_hash")):
        raise _integrity_error(release_id, "manifest_shape_invalid")

    scene_ids = []
    for item in manifest["scenes"]:
        if (
            not isinstance(item, dict)
            or set(item) != _SCENE_KEYS
            or any(not isinstance(item.get(key), str) or not item[key] for key in ("scene_id", "revision_id"))
            or not isinstance(item.get("title"), str)
            or not _valid_digest(item.get("content_hash"))
        ):
            raise _integrity_error(release_id, "manifest_shape_invalid")
        scene_ids.append(item["scene_id"])
    if len(scene_ids) != len(set(scene_ids)):
        raise _integrity_error(release_id, "scene_revision_identity_invalid")

    asset_scene_ids = []
    for item in manifest.get("asset_references", []):
        if not isinstance(item, dict) or set(item) != _ASSET_SCENE_KEYS:
            raise _integrity_error(release_id, "manifest_shape_invalid")
        if not isinstance(item["scene_id"], str) or not item["scene_id"]:
            raise _integrity_error(release_id, "manifest_shape_invalid")
        if item["scene_id"] not in scene_ids or item["scene_id"] in asset_scene_ids:
            raise _integrity_error(release_id, "manifest_shape_invalid")
        if not isinstance(item["references"], list) or not _valid_digest(item["digest"]):
            raise _integrity_error(release_id, "manifest_shape_invalid")
        for reference in item["references"]:
            if not isinstance(reference, dict) or set(reference) != _ASSET_REFERENCE_KEYS:
                raise _integrity_error(release_id, "manifest_shape_invalid")
            if any(not isinstance(reference.get(key), str) or not reference[key] for key in (
                "reference_id", "asset_kind", "source_type", "source_asset_id", "display_name",
                "source_version", "content_hash", "content_hash_kind",
            )):
                raise _integrity_error(release_id, "manifest_shape_invalid")
            if not isinstance(reference.get("source_snapshot"), dict):
                raise _integrity_error(release_id, "manifest_shape_invalid")
            if reference.get("production_copy") is not None and not isinstance(reference.get("production_copy"), dict):
                raise _integrity_error(release_id, "manifest_shape_invalid")
        if sha256_text(canonical_json(item["references"])) != item["digest"]:
            raise _integrity_error(release_id, "manifest_shape_invalid")
        asset_scene_ids.append(item["scene_id"])

    dependency_ids = []
    for item in manifest["dependency_refs"]:
        if (
            not isinstance(item, dict)
            or set(item) != _DEPENDENCY_KEYS
            or any(
                not isinstance(item.get(key), str) or not item[key]
                for key in ("kind", "scope_type", "scope_id", "revision_id")
            )
            or not _valid_digest(item.get("content_hash"))
        ):
            raise _integrity_error(release_id, "manifest_shape_invalid")
        dependency_ids.append(item["revision_id"])
    if len(dependency_ids) != len(set(dependency_ids)):
        raise _integrity_error(release_id, "manifest_shape_invalid")

    for item in manifest["memory_maintenance"]:
        if (
            not isinstance(item, dict)
            or set(item) != _MEMORY_KEYS
            or any(not isinstance(item.get(key), str) or not item[key] for key in ("scene_id", "revision_id"))
            or not isinstance(item.get("complete"), bool)
            or not isinstance(item.get("status"), str)
            or not item["status"]
            or (item.get("work_item_id") is not None and not isinstance(item["work_item_id"], str))
            or (item.get("decision") is not None and not isinstance(item["decision"], str))
        ):
            raise _integrity_error(release_id, "manifest_shape_invalid")


def _json_list(raw, release_id: str) -> list:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _integrity_error(release_id, "database_identity_invalid") from exc
    if not isinstance(value, list):
        raise _integrity_error(release_id, "database_identity_invalid")
    return value


def _valid_digest(value) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _integrity_error(release_id: str, reason: str) -> DomainError:
    return DomainError(
        "release_integrity_failed",
        "发布版本完整性校验失败，系统不会读取或交接损坏内容。",
        status=409,
        details={"release_id": release_id, "reason": reason},
    )
