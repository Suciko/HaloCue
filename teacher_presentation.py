"""Task-wide teacher presentation, separate from the no-portrait identity."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from teacher_identity import TeacherIdentityError


SCHEMA_VERSION = "teacher-presentation/1.0"
MODES = ("slot_zero", "sel_single")
# UUID5(URL, "https://github.com/Suciko/HaloCue/teacher-presentation/1.0").
REPLY_NAMESPACE = UUID("4c830e20-491b-5ff6-ba83-e70990a095d5")


def validate_teacher_presentation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TeacherIdentityError(
            "invalid_teacher_presentation", "Teacher presentation must be an object"
        )
    if value.get("schema_version") != SCHEMA_VERSION:
        raise TeacherIdentityError(
            "teacher_presentation_version_unsupported", "Unsupported teacher presentation version"
        )
    if set(value) != {"schema_version", "mode"} or value.get("mode") not in MODES:
        raise TeacherIdentityError(
            "invalid_teacher_presentation", "Invalid teacher presentation fields or mode"
        )
    return {"schema_version": SCHEMA_VERSION, "mode": value["mode"]}


def effective_teacher_presentation(cast_data: dict[str, Any]) -> dict[str, str]:
    if not isinstance(cast_data, dict):
        raise TeacherIdentityError(
            "teacher_presentation_corrupt", "Teacher presentation cannot be read", status=409
        )
    if "teacher_presentation" not in cast_data:
        return {"schema_version": SCHEMA_VERSION, "mode": "slot_zero"}
    try:
        return validate_teacher_presentation(cast_data["teacher_presentation"])
    except TeacherIdentityError as exc:
        raise TeacherIdentityError(
            "teacher_presentation_corrupt", "Stored teacher presentation is invalid", status=409
        ) from exc


def teacher_reply_ids(card_id: str) -> dict[str, str]:
    """Derive reply/continuation IDs from a stable source card, never text or order."""
    if (
        not isinstance(card_id, str)
        or not card_id
        or len(card_id) > 256
        or card_id != card_id.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in card_id)
    ):
        raise TeacherIdentityError(
            "invalid_teacher_reply_source", "A stable source card ID is required"
        )
    return {
        "reply_id": str(uuid5(REPLY_NAMESPACE, "reply:" + card_id)),
        "continuation_id": str(uuid5(REPLY_NAMESPACE, "continuation:" + card_id)),
    }
