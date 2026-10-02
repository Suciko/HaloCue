"""Explicit, source-preserving character reuse between local writing works.

No model calls, no update-on-name-match, no cross-work live links. The target
receives a new unverified card; source revision and import bytes stay traceable.
"""

from copy import deepcopy
import json

from .errors import DomainError, NotFound
from .repository import new_id, sha256_bytes


def reuse_character_card(service, work_id: str, payload: dict) -> dict:
    source_work_id = str(payload.get("source_work_id", "")).strip()
    source_card_id = str(payload.get("source_card_id", "")).strip()
    source_revision_id = str(payload.get("source_revision_id", "")).strip()
    if not source_work_id or not source_card_id or not source_revision_id:
        raise DomainError("validation_error", "请选择来源作品、人物卡及具体修订。")
    if source_work_id == work_id:
        raise DomainError("validation_error", "请从其他作品选取人物；本作已有卡可直接编辑。")
    expected = int(payload.get("expected_version", -1))
    with service.repo.transaction() as connection:
        version = service._check_work_version(connection, work_id, expected)
        source = connection.execute(
            "SELECT * FROM artifacts WHERE work_id=? AND kind='character_card' "
            "AND scope_type='character' AND scope_id=?",
            (source_work_id, source_card_id),
        ).fetchone()
        if not source or not source["current_revision_id"]:
            raise NotFound("character_card", source_card_id)
        if source["current_revision_id"] != source_revision_id:
            raise DomainError(
                "character_source_changed", "来源人物卡已更新，请刷新后重新选择。", status=409
            )
        revision = connection.execute(
            "SELECT * FROM revisions WHERE id=?", (source_revision_id,)
        ).fetchone()
        content = json.loads(service.repo.read_text(revision["content_uri"]))
        if content.get("status") == "archived":
            raise DomainError(
                "character_source_archived", "来源人物卡已归档，请选择可用资料。", status=409
            )
        matches = service._matching_character_cards(connection, work_id, content)
        if matches:
            raise DomainError(
                "character_card_identity_conflict",
                "本作已有同名或别名匹配的人物卡，已停止复制，不会覆盖。",
                status=409,
                details={"matches": matches},
            )
        card_id = new_id("character")
        reuse_id = new_id("character-reuse")
        card = deepcopy(content)
        origin = {
            "work_id": source_work_id,
            "card_id": source_card_id,
            "revision_id": source_revision_id,
            "source_hash": content.get("source_hash", ""),
        }
        card["reuse_origin"] = origin
        card["source_refs"] = [
            *card.get("source_refs", []),
            {"kind": "work_character_reuse", **origin},
        ]
        card["trust_status"] = "unverified"
        card["status"] = "active"
        # Stable IDs for relationship targets belong to the source work. Retain
        # descriptive names and the immutable origin, never bind unrelated IDs.
        card["relationships"] = [
            {
                key: value
                for key, value in relationship.items()
                if key not in {"target_character_id", "id"}
            }
            for relationship in card.get("relationships", [])
            if relationship.get("target")
        ]
        files = []
        for kind in ("raw", "cleaned"):
            uri = card.get(f"{kind}_import_uri")
            if not uri:
                continue
            source_path = (service.repo.data_dir / uri).resolve()
            if service.repo.data_dir not in source_path.parents:
                raise DomainError(
                    "character_source_unavailable", "人物卡来源文件位置无效。", status=409
                )
            try:
                data = source_path.read_bytes()
            except OSError as error:
                raise DomainError(
                    "character_source_unavailable",
                    "人物卡来源文件无法读取，未复制任何人物卡。",
                    status=409,
                ) from error
            if sha256_bytes(data) != card.get(f"{kind}_import_hash"):
                raise DomainError(
                    "character_source_hash_mismatch",
                    "人物卡来源文件校验不一致，已停止复制。",
                    status=409,
                )
            files.append((kind, data))
        # Validate before writing any new files. Full profile, report, and source
        # status are copied verbatim; this never re-labels sample evidence.
        card = service._normalize_character_card_payload(card)
        for kind, data in files:
            uri, digest = service.repo.atomic_write_bytes(
                f"imports/character-cards/{work_id}/{card_id}/{reuse_id}/{kind}.json", data
            )
            card[f"{kind}_import_uri"] = uri
            card[f"{kind}_import_hash"] = digest
        revision_id = service._save_character_card_revision(
            connection,
            work_id,
            card_id,
            card,
            created_by="user",
            provenance={"workflow": "character.reuse", "source": origin, "reuse_id": reuse_id},
        )
        service._bump_work(connection, work_id, version)
    service._schedule_commit_projection(work_id, revision_id)
    return {"card_id": card_id, "revision_id": revision_id, "work": service.get_work(work_id)}
