"""Deterministic AA single-answer graph projection over frozen source cards."""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid5

from teacher_identity import TeacherIdentityError
from teacher_reply_plan import text_hash, validate_reply_text


SELECTION_TYPE = "SelectionNodeData, Assembly-CSharp"
STRING_LIST_TYPE = "System.Collections.Generic.List`1[[System.String, mscorlib]], mscorlib"
GUID_LIST_TYPE = "System.Collections.Generic.List`1[[System.Guid, mscorlib]], mscorlib"
SCRIPT_NODE_TYPE = "ScriptNodeData, Assembly-CSharp"


def selection_node_errors(node: dict[str, Any], node_ids: set[str]) -> list[str]:
    """Validate the supported single-answer AA shape, not general branching."""
    errors = []
    if set(node) != {"$type", "selectionTexts", "Guid", "ConnectionsTo", "X", "Y"}:
        errors.append("selection_node_shape_invalid")
    try:
        UUID(node["Guid"])
    except (ValueError, TypeError, AttributeError, KeyError):
        errors.append("selection_identity_invalid")
    texts = node.get("selectionTexts")
    if not isinstance(texts, dict) or texts.get("$type") != STRING_LIST_TYPE:
        errors.append("selection_text_invalid")
    else:
        values = texts.get("$values")
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 16
            or any(value != "" for value in values[1:])
        ):
            errors.append("selection_text_invalid")
        else:
            try:
                validate_reply_text(values[0])
            except TeacherIdentityError as exc:
                errors.append(exc.code)
    connections = node.get("ConnectionsTo")
    if not isinstance(connections, dict) or connections.get("$type") != GUID_LIST_TYPE:
        errors.append("selection_edge_invalid")
    else:
        values = connections.get("$values")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            errors.append("selection_edge_invalid")
        elif values[0] not in node_ids:
            errors.append("selection_target_missing")
        elif values[0] == node.get("Guid"):
            errors.append("selection_cycle")
    return errors


def _script_segment(original: dict[str, Any], identifier: str, rows: list) -> dict[str, Any]:
    # Copy node metadata only; copying the complete scene per answer is quadratic.
    node = {
        key: {"$type": value["$type"], "$values": rows}
        if key == "Scripts"
        else copy.deepcopy(value)
        for key, value in original.items()
    }
    node["Guid"] = identifier
    return node


def apply_teacher_selections(project: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Project an already validated reply plan without mutating compiler inputs."""
    projected = copy.deepcopy(project)
    source_nodes = projected["nodes"]["$values"]
    source_rows = [
        row for node in source_nodes for row in node.get("Scripts", {}).get("$values", [])
    ]
    records = plan["lines"]
    if len(source_rows) != len(records):
        raise TeacherIdentityError(
            "teacher_reply_source_mismatch",
            "Compiled dialogue does not match the frozen reply plan",
            status=409,
        )
    for row, record in zip(source_rows, records):
        if text_hash(row["text"]) != record["text_sha256"]:
            raise TeacherIdentityError(
                "teacher_reply_source_mismatch",
                "Compiled reply text does not match its source card",
                status=409,
            )
        if record["teacher"]:
            if (
                row["characters"]["$values"][row["speakerSlotNum"]]["name"]
                != record["character_id"]
            ):
                raise TeacherIdentityError(
                    "teacher_reply_source_mismatch",
                    "Compiled teacher does not match its source binding",
                    status=409,
                )
            validate_reply_text(row["text"])
    if not any(record["teacher"] for record in records):
        return projected

    nodes = []
    offset = 0
    continuation = None
    for original in source_nodes:
        if original["$type"] != SCRIPT_NODE_TYPE:
            if continuation is not None:
                original["Guid"] = continuation
                continuation = None
            nodes.append(original)
            continue
        rows = original["Scripts"]["$values"]
        associated = records[offset : offset + len(rows)]
        offset += len(rows)
        segment = []
        segment_id = continuation
        continuation = None
        for row, record in zip(rows, associated):
            if not segment:
                segment_id = segment_id or str(uuid5(UUID(record["reply_id"]), "stage"))
            answer = row["text"]
            if record["teacher"]:
                # Apply this line's stage and one-shot commands once before its answer.
                row.update(text="", voice="", isDialogScript=False)
            segment.append(row)
            if not record["teacher"]:
                continue
            nodes.append(_script_segment(original, segment_id, segment))
            nodes.append(
                {
                    "$type": SELECTION_TYPE,
                    "selectionTexts": {"$type": STRING_LIST_TYPE, "$values": [answer] + [""] * 15},
                    "Guid": record["reply_id"],
                    "ConnectionsTo": {"$type": GUID_LIST_TYPE, "$values": []},
                    "X": original["X"],
                    "Y": original["Y"],
                }
            )
            segment = []
            segment_id = record["continuation_id"]
        if segment:
            nodes.append(_script_segment(original, segment_id, segment))
        else:
            continuation = segment_id

    identities = [node["Guid"] for node in nodes]
    if len(set(identities)) != len(identities):
        raise TeacherIdentityError(
            "teacher_reply_plan_invalid", "Reply node identities collide", status=409
        )
    for position, node in enumerate(nodes):
        node["ConnectionsTo"]["$values"] = identities[position + 1 : position + 2]
        node["Y"] = -295.952026 * position
    projected["nodes"]["$values"] = nodes
    return projected
