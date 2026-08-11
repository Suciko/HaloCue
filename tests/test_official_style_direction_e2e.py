import hashlib
import json
import re

import pytest

import annotate
from script2aap import build, parse_script


FIELDS = (
    "face", "emo", "act", "fx", "se", "bg", "bg_request", "place",
    "bgfx", "trans", "shot",
)


class DirectedProvider:
    name = "fixture"
    model = "fixture"
    cfg = {}

    def __init__(self, story_type, directions):
        self.story_type = story_type
        self.directions = directions
        self.static = ""
        self.stats = {"calls": 0, "in": 0, "out": 0}

    def complete_json(self, static, _volatile, user, _schema):
        self.static = static
        matches = re.findall(
            r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user
        )
        rows = []
        for index, (source_id, fingerprint) in enumerate(matches):
            row = {field: "" for field in FIELDS}
            row.update({
                "source_id": source_id,
                "text_fingerprint": fingerprint,
                "shake": False,
                "move": 0,
                **self.directions[index],
            })
            rows.append(row)
        self.stats["calls"] += 1
        return {"lines": rows, "state_delta": {}, "memory_events": []}

    def report(self):
        return "fixture"


CASES = {
    "bond": {
        "source": "Rin: 你还会来吗？\nKai: 我会来。\n",
        "directions": [
            {"direction": {
                "scene_type": "bond", "scene_function": "emotional_turn",
                "focus_kind": "listener", "focus_character": "Kai",
                "visible_characters": ["Kai"], "relation_distance": "approaching",
                "subtext": "等待确认", "reason": "listener_reaction",
            }},
            {"direction": {
                "scene_type": "bond", "scene_function": "closing",
                "visible_characters": ["Rin", "Kai"],
                "relation_distance": "intimate", "reason": "relation_shift",
            }},
        ],
    },
    "event": {
        "source": "Momo: 我没有迟到！\nAlice: 门还没开。\nYuzu: 现在更尴尬了。\n",
        "directions": [
            {"emo": "惊讶", "direction": {
                "scene_type": "event", "scene_function": "entrance",
                "visible_characters": ["Momo", "Alice", "Yuzu"],
                "reason": "new_stimulus", "continuity": {"emo": "start"},
            }},
            {"direction": {
                "scene_type": "event", "scene_function": "comedy_escalation",
                "focus_kind": "listener", "focus_character": "Momo",
                "visible_characters": ["Momo", "Alice", "Yuzu"],
                "reason": "comedy_escalation",
            }},
            {"direction": {
                "scene_type": "event", "scene_function": "comedy_escalation",
                "focus_kind": "group",
                "visible_characters": ["Momo", "Alice", "Yuzu"],
                "reason": "group_sync",
            }},
        ],
    },
    "main": {
        "source": "Operator: 前方通道已经封锁。\nLeader: 改走东侧入口。\n",
        "directions": [
            {"fx": "通讯", "direction": {
                "scene_type": "main", "scene_function": "exposition",
                "focus_kind": "speaker", "focus_character": "Operator",
                "visible_characters": ["Operator"], "relation_distance": "remote",
                "reason": "new_stimulus", "continuity": {"fx": "start"},
            }},
            {"direction": {
                "scene_type": "main", "scene_function": "action",
                "focus_kind": "speaker", "focus_character": "Leader",
                "visible_characters": ["Leader"], "relation_distance": "normal",
                "reason": "action_impact",
            }},
        ],
    },
}


@pytest.mark.parametrize("story_type", ["bond", "event", "main"])
def test_story_mode_preserves_source_and_compiles_director_cues(tmp_path, story_type):
    case = CASES[story_type]
    source_path = tmp_path / f"{story_type}.txt"
    source_path.write_text(case["source"], encoding="utf-8")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    names = sorted(set(re.findall(r"^([^:]+):", case["source"], re.M)))
    cast_data = {
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "camera": {"enabled": False},
        "cast": {name: {"id": name.lower(), "portrait": True} for name in names},
        "alias": {},
    }
    cast_path = tmp_path / "cast.json"
    cast_path.write_text(json.dumps(cast_data), encoding="utf-8")
    index = {
        "bg": {"BG_Black": 1}, "sounds": [], "characters": [],
        "enums": {
            "emoticon": {"1": {"sym": "[!]", "cn": "惊讶"}},
            "action": {},
        },
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    llm_path = tmp_path / "llm.json"
    llm_path.write_text("{}", encoding="utf-8")
    output = tmp_path / f"{story_type}.annotated.txt"
    provider = DirectedProvider(story_type, case["directions"])

    result = annotate.annotate_script({
        "script": str(source_path), "out": str(output), "cast": str(cast_path),
        "index": str(index_path), "llm": str(llm_path), "agent_enabled": True,
        "checkpoint_dir": str(tmp_path / "checkpoints"), "story_type": story_type,
    }, provider_instance=provider)

    annotated = output.read_text(encoding="utf-8")
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash
    assert [line.split(":", 1)[1] for line in case["source"].splitlines()] == [
        line.split(":", 1)[1]
        for line in annotated.splitlines() if ":" in line and not line.startswith("@")
    ]
    assert "等待确认" not in annotated
    assert "listener_reaction" not in annotated
    assert annotated.count("@camera") == len(case["directions"])
    assert ("@fx Operator 通讯" in annotated) == (story_type == "main")
    assert result["story_type"] == story_type
    assert f"当前剧情类型：{story_type}" in provider.static
    checkpoint = json.loads(next(
        (tmp_path / "checkpoints").rglob("checkpoint.json")
    ).read_text(encoding="utf-8"))
    assert checkpoint["fingerprint"]["story_type"] == story_type
    assert checkpoint["director_plan"]["story_type"] == story_type

    cast = cast_data["cast"]
    scenes = build(parse_script(output, cast), cast_data, cast, index, story_type)
    rows = [row for _title, scripts in scenes for row in scripts]
    assert len(rows) == len(case["source"].splitlines())
    for row in rows:
        assert row["$type"].startswith("ScriptData")
        visible = [
            character for character in row["characters"]["$values"][1:]
            if character["name"]
        ]
        assert len(visible) <= 5
        assert 0 <= row["speakerSlotNum"] <= 5
