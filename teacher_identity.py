"""Production-owned teacher identity, independent of source names and portraits."""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any


SCHEMA_VERSION = "teacher-identity/1.0"
PRESETS = (
    {"id": "sensei_shale", "display_name": "sensei", "organization": "沙勒"},
    {"id": "sensei_xialai", "display_name": "sensei", "organization": "夏莱"},
    {"id": "teacher_shale", "display_name": "老师", "organization": "沙勒"},
    {"id": "teacher_xialai", "display_name": "老师", "organization": "夏莱"},
    {"id": "custom", "display_name": None, "organization": None},
)
TEACHER_ID = re.compile(r"hc-teacher-[0-9a-f]{32}")


class TeacherIdentityError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _text(value: Any, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 80
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise TeacherIdentityError(
            "invalid_teacher_identity", "名称和组织须为不超过 80 字的单行文本"
        )
    value = value.strip()
    if not value and not empty:
        raise TeacherIdentityError("invalid_teacher_identity", "老师名称不能为空")
    return value


def validate_teacher_identity(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise TeacherIdentityError("teacher_identity_corrupt", "老师身份版本无效", status=409)
    identifier = value.get("character_id")
    if not isinstance(identifier, str) or not TEACHER_ID.fullmatch(identifier):
        raise TeacherIdentityError("teacher_identity_corrupt", "老师身份标识无效", status=409)
    preset = next((p for p in PRESETS if p["id"] == value.get("preset_id")), None)
    if preset is None:
        raise TeacherIdentityError("teacher_identity_corrupt", "老师身份预设无效", status=409)
    try:
        name = _text(value.get("display_name"))
        organization = _text(value.get("organization"), empty=True)
    except TeacherIdentityError as exc:
        raise TeacherIdentityError(
            "teacher_identity_corrupt", "老师身份名称或组织无效", status=409
        ) from exc
    if preset["id"] != "custom" and (name, organization) != (
        preset["display_name"],
        preset["organization"],
    ):
        raise TeacherIdentityError("teacher_identity_corrupt", "老师身份与预设不一致", status=409)
    return {
        "schema_version": SCHEMA_VERSION,
        "character_id": identifier,
        "preset_id": preset["id"],
        "display_name": name,
        "organization": organization,
    }


def teacher_override_from_mapping(mapping: dict[str, Any]) -> dict[str, Any] | None:
    if mapping.get("role") != "teacher":
        return None
    identity = validate_teacher_identity(
        {
            "schema_version": mapping.get("teacher_identity_schema"),
            "character_id": mapping.get("id"),
            "preset_id": mapping.get("teacher_preset_id"),
            "display_name": mapping.get("name"),
            "organization": mapping.get("club"),
        }
    )
    if (
        mapping.get("kind") != "voice"
        or mapping.get("portrait") is not False
        or mapping.get("narrator") is not False
        or mapping.get("custom")
        or any(mapping.get(key) for key in ("spine", "spine_signature", "outfit_key"))
    ):
        raise TeacherIdentityError(
            "teacher_identity_conflict", "老师身份必须是无立绘角色", status=409
        )
    return {
        "Identifier": identity["character_id"],
        "Name": identity["display_name"],
        "Nickname": identity["organization"],
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": None,
        "SmallPortraitPath": None,
    }


def prepare_teacher_binding(
    cast_data: dict[str, Any],
    resources: dict[str, Any],
    speaker: str,
    selection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if not isinstance(selection, dict):
        raise TeacherIdentityError("invalid_teacher_identity", "老师身份请求须为对象")
    if selection.get("schema_version") != SCHEMA_VERSION:
        raise TeacherIdentityError(
            "teacher_identity_version_unsupported", "不支持该老师身份合同版本"
        )
    if selection.get("kind") != "teacher" or set(selection) - {
        "kind",
        "schema_version",
        "preset_id",
        "display_name",
        "organization",
    }:
        raise TeacherIdentityError("invalid_teacher_identity", "老师身份请求字段无效")
    preset = next((p for p in PRESETS if p["id"] == selection.get("preset_id")), None)
    if preset is None:
        raise TeacherIdentityError("invalid_teacher_preset", "请选择有效的老师身份预设")
    if preset["id"] == "custom":
        name = _text(selection.get("display_name"))
        organization = _text(selection.get("organization", ""), empty=True)
    else:
        if "display_name" in selection or "organization" in selection:
            raise TeacherIdentityError(
                "invalid_teacher_identity", "预设名称和组织不可覆盖，请选择自定义"
            )
        name, organization = preset["display_name"], preset["organization"]
    if not isinstance(cast_data, dict) or not isinstance(resources, dict):
        raise TeacherIdentityError("teacher_identity_corrupt", "演员或资源声明不可读取", status=409)
    updated = copy.deepcopy(cast_data)
    catalogue = copy.deepcopy(resources)
    actors = updated.setdefault("cast", {})
    characters = catalogue.setdefault("characters", [])
    if not isinstance(actors, dict) or not isinstance(characters, list):
        raise TeacherIdentityError("teacher_identity_corrupt", "演员或资源声明不可读取", status=409)
    existing = updated.get("teacher_identity")
    old = validate_teacher_identity(existing) if existing is not None else None
    identifier = old["character_id"] if old else "hc-teacher-" + uuid.uuid4().hex
    aliases = [
        key for key, row in actors.items() if isinstance(row, dict) and row.get("role") == "teacher"
    ]
    if any(actors[key].get("id") != identifier for key in aliases):
        raise TeacherIdentityError("teacher_identity_corrupt", "老师别名绑定不一致", status=409)
    for key in aliases:
        alias = actors[key]
        teacher_override_from_mapping(alias)
        if not old or (alias.get("name"), alias.get("club"), alias.get("teacher_preset_id")) != (
            old["display_name"],
            old["organization"],
            old["preset_id"],
        ):
            raise TeacherIdentityError(
                "teacher_identity_corrupt", "老师别名与身份声明不一致", status=409
            )
    if any(
        isinstance(row, dict) and row.get("id") == identifier and row.get("role") != "teacher"
        for row in actors.values()
    ):
        raise TeacherIdentityError(
            "teacher_identity_conflict", "老师身份标识已被其他角色使用", status=409
        )
    matches = [
        row for row in characters if isinstance(row, dict) and row.get("identifier") == identifier
    ]
    face_capabilities = catalogue.get("face_capabilities", {})
    if not isinstance(face_capabilities, dict):
        raise TeacherIdentityError("teacher_identity_corrupt", "表情能力声明不可读取", status=409)
    if (
        len(matches) > 1
        or (old and not matches)
        or any(
            row.get("role") != "teacher"
            or row.get("source") != "halocue_teacher"
            or row.get("spine")
            or row.get("faces")
            or row.get("portrait") is not False
            for row in matches
        )
        or identifier in face_capabilities
    ):
        raise TeacherIdentityError(
            "teacher_identity_conflict", "老师标识与已有素材冲突", status=409
        )
    if any(
        isinstance(row, dict)
        and (row.get("role") == "teacher" or row.get("source") == "halocue_teacher")
        and row.get("identifier") != identifier
        for row in characters
    ):
        raise TeacherIdentityError(
            "teacher_identity_conflict", "草稿只能使用一个托管老师身份", status=409
        )
    if old and (matches[0].get("name"), matches[0].get("club")) != (
        old["display_name"],
        old["organization"],
    ):
        raise TeacherIdentityError(
            "teacher_identity_corrupt", "老师资源与身份声明不一致", status=409
        )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "character_id": identifier,
        "preset_id": preset["id"],
        "display_name": name,
        "organization": organization,
    }
    updated["teacher_identity"] = identity
    affected = []
    for alias in sorted(set(aliases + [speaker])):
        binding = {
            "kind": "voice",
            "role": "teacher",
            "id": identifier,
            "name": name,
            "club": organization,
            "portrait": False,
            "narrator": False,
            "teacher_identity_schema": SCHEMA_VERSION,
            "teacher_preset_id": preset["id"],
        }
        if actors.get(alias) != binding:
            affected.append(alias)
        actors[alias] = binding
    resource = {
        "identifier": identifier,
        "name": name,
        "club": organization,
        "role": "teacher",
        "source": "halocue_teacher",
        "portrait": False,
        "spine": "",
        "faces": [],
    }
    if matches:
        characters[characters.index(matches[0])] = resource
    else:
        characters.append(resource)
    return updated, catalogue, affected
