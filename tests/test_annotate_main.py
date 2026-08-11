import json
import sys

import annotate
import llm


def test_annotation_static_system_keeps_exact_source_after_rules():
    source = "Kai: original\n\nKai: do not rewrite\n"

    static = annotate.build_annotation_static_system("RULES", source)

    assert static.startswith("RULES")
    assert static.endswith(source)


def test_annotation_static_system_uses_window_only_when_explicitly_requested():
    static = annotate.build_annotation_static_system(
        "RULES", "Kai: keep this source\n", source_context_strategy="window",
    )

    assert static == "RULES"


def test_main_with_mock_provider_writes_a_portrait_annotation(tmp_path, monkeypatch):
    script = tmp_path / "scene.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "cast": {"Kai": {"id": "kai", "portrait": True}}, "alias": {},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 1}, "sounds": [],
        "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
        "enums": {
            "emoticon": {"1": {"sym": "[!]", "cn": "惊讶"}},
            "action": {"6": {"verb": "jump", "cn": "跳跃"}},
        },
    }), encoding="utf-8")
    output = tmp_path / "annotated.txt"
    monkeypatch.setattr(sys, "argv", [
        "annotate.py", str(script), "-o", str(output), "--cast", str(cast),
        "--index", str(index), "--provider", "mock",
    ])
    monkeypatch.setattr(
        annotate,
        "make_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("profile provider instance was ignored")
        ),
    )

    annotate.main(provider_instance=llm.MockProvider({}))

    assert output.read_text(encoding="utf-8") == "Kai(00): hello\n"


def test_agent_mode_accepts_mock_provider_source_identity_response(tmp_path):
    script = tmp_path / "scene.txt"
    script.write_text("Kai: hello\nKai: goodbye\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "cast": {"Kai": {"id": "kai", "portrait": True}}, "alias": {},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 1}, "sounds": [],
        "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
        "enums": {"emoticon": {}, "action": {}},
    }), encoding="utf-8")
    output = tmp_path / "annotated.txt"
    llm_config = tmp_path / "llm.json"
    llm_config.write_text("{}", encoding="utf-8")
    result = annotate.annotate_script({
        "script": str(script), "out": str(output), "cast": str(cast),
        "index": str(index), "llm": str(llm_config), "agent_enabled": True,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }, provider_instance=llm.MockProvider({}))
    assert result["agent"]["enabled"] is True
    assert output.read_text(encoding="utf-8") == "Kai: hello\nKai: goodbye\n"
    checkpoint = json.loads(next((tmp_path / "checkpoints").rglob("checkpoint.json")).read_text(encoding="utf-8"))
    assert checkpoint["schema_version"] == 2
    assert checkpoint["fingerprint"]["schema_version"] == 3
    assert checkpoint["fingerprint"]["chunk_version"] == "scene-v3"
    assert checkpoint["fingerprint"]["director_version"] == "stateful-v1"
    assert checkpoint["fingerprint"]["story_type"] == "auto"
    assert checkpoint["director_plan"]["story_type"] == "auto"
    assert checkpoint["memory"]["story"]["type"] == "auto"


def test_agent_reuses_one_source_prefixed_static_prompt_across_chunks(tmp_path):
    script = tmp_path / "scene.txt"
    source = "".join(f"Kai: line {index}\n" for index in range(80))
    script.write_text(source, encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "cast": {"Kai": {"id": "kai", "portrait": True}}, "alias": {},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 1}, "sounds": [],
        "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
        "enums": {"emoticon": {}, "action": {}},
    }), encoding="utf-8")

    class CaptureProvider(llm.MockProvider):
        def __init__(self):
            super().__init__({})
            self.static_prompts = []

        def complete_json(self, static_system, volatile_system, user, schema):
            self.static_prompts.append(static_system)
            return super().complete_json(static_system, volatile_system, user, schema)

    provider = CaptureProvider()
    annotate.annotate_script({
        "script": str(script), "out": str(tmp_path / "annotated.txt"),
        "cast": str(cast), "index": str(index), "agent_enabled": True,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }, provider_instance=provider)

    assert len(provider.static_prompts) >= 2
    assert len(set(provider.static_prompts)) == 1
    assert provider.static_prompts[0].endswith(source)


def test_confirmed_usage_chain_is_sent_as_annotation_context(tmp_path):
    script = tmp_path / "scene.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "cast": {"Kai": {"id": "kai", "portrait": True}}, "alias": {},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 1}, "sounds": [],
        "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
        "enums": {"emoticon": {}, "action": {}},
    }), encoding="utf-8")
    captured = {}

    class Provider:
        name = "capture"
        model = "capture"

        def complete_json(self, static, volatile, _user, _schema):
            captured["static"] = static
            captured["volatile"] = volatile
            return {"lines": []}

        def report(self):
            return "capture"

    plan = [{
        "segment": "转场", "location": "夜间天台", "start": "第1行", "end": "第1行",
        "evidence": "夜色中的天台。", "needs": [{
            "kind": "background", "name": "BG_RoofNight", "status": "builtin",
            "aa_key": "BG_RoofNight",
            "location": "第1行", "reason": "已确认", "confidence": 0.98,
        }],
    }]

    annotate.annotate_script({
        "script": str(script), "out": str(tmp_path / "annotated.txt"),
        "cast": str(cast), "index": str(index), "usage_chain": plan,
    }, provider_instance=Provider())

    assert "已确认的场景演出规划" in captured["volatile"]
    assert "BG_RoofNight" in captured["volatile"]
    assert "BG_RoofNight" in captured["static"]


def test_annotation_writer_does_not_repeat_same_background():
    items = [
        {
            "kind": "line",
            "raw": "旁白: 一",
            "who": "旁白",
            "text": "一",
            "bg": "BG_ShoppingDistrict",
            "trans": "淡入淡出",
            "place": "商店街",
        },
        {
            "kind": "line",
            "raw": "旁白: 二",
            "who": "旁白",
            "text": "二",
            "bg": "BG_ShoppingDistrict",
            "trans": "淡入淡出",
            "place": "可丽饼摊前",
        },
        {
            "kind": "line",
            "raw": "旁白: 三",
            "who": "旁白",
            "text": "三",
            "bg": "BG_GameCenter",
            "trans": "淡入淡出",
            "place": "游戏中心",
        },
    ]

    result = annotate.render_annotated_items(items)

    assert result.count("@bg BG_ShoppingDistrict") == 1
    assert result.count("@trans 淡入淡出") == 1
    assert "@bg BG_ShoppingDistrict\n@trans 淡入淡出" not in result
    assert "@place 可丽饼摊前\n旁白: 二" in result
    assert "@bg BG_GameCenter\n@trans 淡入淡出" in result
