from __future__ import annotations

import base64
import json

import pytest

from halocue_writing.aap_import import parse_aap_payload


def _payload() -> dict:
    project = {
        "ProjectName": "测试工程",
        "nodes": {"$values": [
            {"$type": "EntryNodeData, Assembly-CSharp", "ConnectionsTo": {"$values": ["scene-1"]}},
            {"$type": "ScriptNodeData, Assembly-CSharp", "NodeName": "场景一", "Scripts": {"$values": [
                {"text": "开场旁白", "isDialogScript": False, "speakerSlotNum": 0, "characters": {"$values": [{"name": ""}]}, "bgFriendlyName": "BG_Classroom", "sound": ""},
                {"text": "早上好。", "isDialogScript": True, "speakerSlotNum": 0, "characters": {"$values": [{"name": "爱丽丝"}]}, "bgFriendlyName": "BG_Classroom", "sound": "SE_Door"},
            ]}},
        ]},
    }
    raw = json.dumps(project, ensure_ascii=False).encode("utf-8")
    return {"filename": "测试工程.aap", "content_base64": base64.b64encode(raw).decode("ascii")}


def test_aap_preview_is_read_only_and_keeps_user_visible_summary():
    preview = parse_aap_payload(_payload())
    assert preview["schema_version"] == "story-import/1.0"
    assert preview["write_boundary"] == "preview_only_until_user_confirmation"
    assert preview["counts"] == {"scenes": 1, "lines": 2, "characters": 1, "backgrounds": 1, "sounds": 1}
    assert preview["scenes"][0]["title"] == "场景一"
    assert preview["characters"][0]["name"] == "爱丽丝"


def test_aap_preview_rejects_non_aap_file():
    payload = _payload()
    payload["filename"] = "story.txt"
    with pytest.raises(ValueError, match=r"\.aap"):
        parse_aap_payload(payload)
