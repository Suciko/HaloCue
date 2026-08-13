import json

import annotate
from script2aap import build, parse_script

from direction_rules import (
    apply_model_directions,
    infer_direction_cues,
    mark_explicit_directions,
    normalize_direction_density,
    supplement_directions,
)


def test_requested_examples_receive_balanced_direction_cues():
    assert infer_direction_cues(
        "全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。"
    )["emo"] == "冒烟"
    assert infer_direction_cues(
        "……你为什么要把「普通」说得那么不普通。"
    )["emo"] == "沉默"
    assert infer_direction_cues("……！")["emo"] == "惊叹"
    assert infer_direction_cues("那就更不行了！！")["act"] == "jump"


def test_punctuation_alone_does_not_over_direct_ordinary_dialogue():
    assert infer_direction_cues("好的！") == {}
    assert infer_direction_cues("那么……我们继续说明下一项。") == {}
    assert infer_direction_cues("现在出发！") == {}
    assert infer_direction_cues("今天的折扣很大！！") == {}


def test_supplement_only_fills_empty_portrait_fields():
    items = [
        {"kind": "line", "who": "凯伊", "text": "……！", "emo": None},
        {"kind": "line", "who": "老师", "text": "……！", "emo": None},
        {
            "kind": "line",
            "who": "凯伊",
            "text": "那就更不行了！！",
            "act": "stiff",
        },
    ]
    cast = {
        "凯伊": {"portrait": True, "narrator": False},
        "老师": {"portrait": False, "narrator": False},
    }

    changes = supplement_directions(items, cast)

    assert items[0]["emo"] == "惊叹"
    assert not items[1].get("emo")
    assert items[2]["act"] == "stiff"
    assert changes == [
        {
            "item_index": 0,
            "field": "emo",
            "before": None,
            "after": "惊叹",
            "rule": "punctuation_only_exclaim",
        }
    ]
    assert items[0]["_direction_origins"] == {
        "emo": "deterministic_supplement"
    }


def test_source_direction_has_priority_over_model_and_supplement():
    item = {
        "kind": "line",
        "who": "凯伊",
        "text": "……！",
        "emo": "疑问",
        "act": "stiff",
    }
    mark_explicit_directions(item)

    applied = apply_model_directions(
        item, {"emo": "惊叹", "act": "jump", "face": "03"}
    )
    supplement_directions(
        [item], {"凯伊": {"portrait": True, "narrator": False}}
    )

    assert item["emo"] == "疑问"
    assert item["act"] == "stiff"
    assert item["face"] == "03"
    assert applied == {"face": "03"}
    assert item["_direction_origins"] == {"face": "model"}


def test_balanced_density_limits_automatic_symbols_and_strong_actions():
    items = [
        {
            "kind": "line",
            "who": "凯伊",
            "emo": "惊叹",
            "_direction_origins": {"emo": "model"},
        },
        {
            "kind": "line",
            "who": "桃井",
            "emo": "沉默",
            "_direction_origins": {"emo": "model"},
        },
        {
            "kind": "line",
            "who": "凯伊",
            "act": "jump",
            "_direction_origins": {"act": "model"},
        },
        {
            "kind": "line",
            "who": "桃井",
            "act": "jump",
            "_direction_origins": {"act": "model"},
        },
    ]

    normalize_direction_density(items)

    assert items[0]["emo"] == "惊叹"
    assert not items[1].get("emo")
    assert items[2]["act"] == "jump"
    assert not items[3].get("act")
    assert "emo" not in items[1]["_direction_origins"]
    assert "act" not in items[3]["_direction_origins"]


def test_explicit_symbols_and_actions_are_never_removed_by_density_control():
    items = [
        {"kind": "line", "who": "凯伊", "emo": "惊叹", "act": "jump"},
        {"kind": "line", "who": "桃井", "emo": "沉默", "act": "jump"},
    ]
    for item in items:
        mark_explicit_directions(item)

    normalize_direction_density(items)

    assert [(item["emo"], item["act"]) for item in items] == [
        ("惊叹", "jump"),
        ("沉默", "jump"),
    ]


def test_same_automatic_symbol_obeys_four_line_and_shy_eight_line_cooldowns():
    items = [
        {
            "kind": "line",
            "who": "凯伊",
            "emo": "惊叹",
            "_direction_origins": {"emo": "model"},
        },
        *({"kind": "line", "who": "老师"} for _ in range(4)),
        {
            "kind": "line",
            "who": "凯伊",
            "emo": "惊叹",
            "_direction_origins": {"emo": "model"},
        },
        {"kind": "line", "who": "老师"},
        {
            "kind": "line",
            "who": "凯伊",
            "emo": "脸红",
            "_direction_origins": {"emo": "model"},
        },
        *({"kind": "line", "who": "老师"} for _ in range(8)),
        {
            "kind": "line",
            "who": "凯伊",
            "emo": "脸红",
            "_direction_origins": {"emo": "model"},
        },
    ]

    normalize_direction_density(items)

    assert items[0]["emo"] == "惊叹"
    assert items[5]["emo"] == "惊叹"
    assert items[7]["emo"] == "脸红"
    assert items[-1]["emo"] == "脸红"


def test_annotation_preserves_authored_direction_and_supplements_a_later_gap(tmp_path):
    script = tmp_path / "scene.txt"
    script.write_text(
        "凯伊[疑问]: 先这样。\n凯伊: 我知道了。\n凯伊: ……！\n",
        encoding="utf-8",
    )
    cast_path = tmp_path / "cast.json"
    cast_path.write_text(
        json.dumps(
            {
                "default_bg": "BG_Black",
                "default_bgm": 0,
                "scene_bg": {},
                "cast": {"凯伊": {"id": "kei", "portrait": True}},
                "alias": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1},
                "sounds": [],
                "characters": [{"identifier": "kei", "faces": []}],
                "enums": {
                    "emoticon": {
                        "3": {"sym": "[!]", "cn": "惊叹"},
                        "6": {"sym": "[?]", "cn": "疑问"},
                    },
                    "action": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    llm_path = tmp_path / "llm.json"
    llm_path.write_text(
        json.dumps({"chunk_lines": 40, "context_lines": 10}), encoding="utf-8"
    )
    output = tmp_path / "annotated.txt"

    class Provider:
        name = "direction-test"
        model = "direction-test"

        def complete_json(self, _static, _volatile, _user, _schema):
            return {
                "lines": [
                    {"i": 0, "emo": "惊叹"},
                    {"i": 1},
                    {"i": 2},
                ]
            }

        def report(self):
            return "direction-test"

    annotate.annotate_script(
        {
            "script": str(script),
            "out": str(output),
            "cast": str(cast_path),
            "index": str(index_path),
            "llm": str(llm_path),
        },
        provider_instance=Provider(),
    )

    assert output.read_text(encoding="utf-8") == (
        "凯伊[疑问]: 先这样。\n凯伊: 我知道了。\n凯伊[惊叹]: ……！\n"
    )


def test_supplement_failure_keeps_existing_direction_and_returns_a_diagnostic(
    monkeypatch,
):
    items = [
        {"kind": "line", "who": "凯伊", "text": "……！", "face": "03"}
    ]

    def fail_supplement(_items, _cast):
        raise RuntimeError("rule failure")

    monkeypatch.setattr(annotate, "supplement_directions", fail_supplement)

    changes, diagnostics = annotate.apply_direction_supplements(
        items, {"凯伊": {"portrait": True}}
    )

    assert changes == []
    assert items[0]["face"] == "03"
    assert diagnostics == [
        {
            "code": "direction_supplement_failed",
            "level": "warning",
            "message": "自动演出补全已跳过：rule failure",
        }
    ]


def test_balanced_direction_reaches_the_correct_aap_character_fields(tmp_path):
    texts = [
        "全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。",
        "先听我说。",
        "……你为什么要把「普通」说得那么不普通。",
        "我只是照实描述。",
        "……！",
        "所以呢？",
        "那就更不行了！！",
    ]
    items = [
        {"kind": "line", "who": "凯伊", "text": text}
        for text in texts
    ]
    cast = {"凯伊": {"id": "kei", "portrait": True, "narrator": False}}

    supplement_directions(items, cast)
    normalize_direction_density(items)
    script = tmp_path / "balanced.txt"
    script.write_text(
        "\n".join(annotate.render(item) for item in items) + "\n",
        encoding="utf-8",
    )
    index = {
        "bg": {"BG_Black": 1},
        "sounds": [],
        "characters": [{"identifier": "kei", "faces": []}],
        "enums": {
            "emoticon": {
                "2": {"sym": "…", "cn": "沉默"},
                "3": {"sym": "[!]", "cn": "惊叹"},
                "17": {"sym": "{Steam}", "cn": "冒烟"},
            },
            "action": {"6": {"verb": "jump", "cn": "跳"}},
        },
    }

    events = parse_script(script, cast)
    scenes = build(
        events,
        {"default_bg": "BG_Black", "default_bgm": 0},
        cast,
        index,
        "BalancedDirection",
    )
    scripts = scenes[0][1]

    def speaker_character(line_index):
        row = scripts[line_index]
        return row["characters"]["$values"][row["speakerSlotNum"]]

    assert [event["text"] for event in events if event["k"] == "line"] == texts
    assert speaker_character(0)["emoticon"] == 17
    assert speaker_character(2)["emoticon"] == 2
    assert speaker_character(4)["emoticon"] == 3
    assert speaker_character(6)["action"] == 6
    assert speaker_character(6)["emoticon"] == -1


def test_explicit_comedy_escalation_keeps_adjacent_emoticons():
    items = [
        {
            "kind": "line", "who": "A", "text": "什么？", "emo": "疑问",
            "_director": {"continuity": {"emo": "start"}, "reason": "new_stimulus"},
        },
        {
            "kind": "line", "who": "A", "text": "真的？", "emo": "惊叹",
            "_director": {"continuity": {"emo": "escalate"}, "reason": "comedy_escalation"},
        },
        {
            "kind": "line", "who": "A", "text": "你骗我！", "emo": "怒筋",
            "_director": {"continuity": {"emo": "escalate"}, "reason": "comedy_escalation"},
        },
    ]

    normalize_direction_density(items)

    assert [item["emo"] for item in items] == ["疑问", "惊叹", "怒筋"]


def test_transient_hold_without_new_stimulus_does_not_bypass_cooldown():
    items = [
        {"kind": "line", "who": "A", "emo": "惊叹"},
        {
            "kind": "line", "who": "A", "emo": "惊叹",
            "_director": {"continuity": {"emo": "hold"}, "reason": "continuity_hold"},
        },
    ]

    normalize_direction_density(items)

    assert items[0]["emo"] == "惊叹"
    assert "emo" not in items[1]
