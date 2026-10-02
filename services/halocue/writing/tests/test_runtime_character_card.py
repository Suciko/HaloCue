from halocue_writing.service import WritingService


def test_runtime_character_card_projects_ba_profile_without_flattening_voice_evidence():
    content = {
        "profile_format": "ba-character-card/1",
        "name": "爱丽丝",
        "canonical_name": "天童爱丽丝",
        "aliases": ["爱丽丝"],
        "source_hash": "sha256:source",
        "extractor_version": "ba-writing/extract-character",
        "source_refs": ["official:aris"],
        "trust_status": "confirmed",
        "ba_profile": {
            "core": {"summary": "会把任务理解成冒险。"},
            "decision_patterns": {
                "routine_work": {"trigger": "日常任务", "response": "先确认目标"},
                "crisis_battle": {"trigger": "危机", "response": "保护同伴"},
            },
            "emotions": {
                "平静": {"language": "完整陈述"},
                "兴奋": {"language": "注意力集中在眼前的新发现"},
            },
            "relations": {"peers": {"凯伊": {"summary": "会认真接住她的纠偏。"}}},
            "ooc_constraints": ["不知道的事实不说。"],
            "speech": {
                "address_patterns": {"凯伊": "凯伊"},
                "sentence_traits": {"baseline": "完整、直接"},
                "voice_examples": [
                    {
                        "line": f"例句 {index}",
                        "source_id": f"source-{index}",
                        "evidence_status": "local_exact",
                        "state": "平静",
                    }
                    for index in range(10)
                ],
                "voice_sequences": [{
                    "source_id": "sequence-1",
                    "context": "活动室确认异常",
                    "function": "跨轮承接",
                    "turns": [
                        {"speaker": "爱丽丝", "line": "先确认目标。"},
                        {"speaker": "凯伊", "line": "目标是查看日志。"},
                        {"speaker": "爱丽丝", "line": "那么从最新一条开始。"},
                    ],
                }],
            },
        },
    }
    contract = {
        "scene_type": "日常调查",
        "decision_mode": "routine_work",
        "emotion_states": {"爱丽丝": ["平静"]},
    }

    runtime = WritingService._runtime_character_card(
        content, "revision-aris", contract, ["爱丽丝", "凯伊"], False
    )

    assert runtime["schema_version"] == "runtime-character-card/1.1"
    assert set(runtime["decision_patterns"]) == {"routine_work"}
    assert set(runtime["emotion_states"]) == {"平静"}
    assert len(runtime["speech"]["voice_examples"]) == 8
    assert runtime["speech"]["voice_sequences"][0]["source_id"] == "sequence-1"
    assert runtime["relations"]["peers"]["凯伊"]
    assert runtime["address_patterns"]["凯伊"] == "凯伊"
    assert runtime["validation"] == {"voice_evidence": "ready", "ooc_constraints": "ready"}
    assert runtime["runtime_hash"].startswith("sha256:")


def test_runtime_character_card_marks_legacy_missing_ooc_without_inventing_it():
    runtime = WritingService._runtime_character_card(
        {
            "name": "自定义角色",
            "voice_anchors": ["先确认眼前的情况。"],
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
        "revision-custom",
        {"scene_type": "日常"},
        ["自定义角色"],
        False,
    )

    assert runtime["speech"]["voice_examples"][0]["source_id"] == "character-card:revision-custom"
    assert runtime["ooc_constraints"] == []
    assert runtime["validation"]["ooc_constraints"] == "missing"


def test_runtime_card_only_keeps_scene_relations_and_dialogue_participants():
    content = {
        "name": "甲", "voice_anchors": ["先试灯。"],
        "ooc_constraints": ["不知道的事实不说。"],
        "ba_profile": {
            "relations": {"sensei": {"summary": "老师"}, "peers": {"乙": "同伴", "丙": "无关"}},
            "special_mechanisms": {"光环": "本场有关", "隐藏能力": "无关"},
            "speech": {
                "address_patterns": {"乙": "乙", "丙": "丙", "老师": "老师"},
                "voice_sequences": [
                    {"source_id": "local", "turns": [{"speaker": name, "line": "试灯"} for name in ["甲", "乙", "甲"]]},
                    {"source_id": "teacher", "turns": [{"speaker": name, "line": "试灯"} for name in ["甲", "老师", "甲"]]},
                ],
            },
        },
    }
    runtime = WritingService._runtime_character_card(content, "rev", {"goal": "光环映着灯光"}, ["甲", "乙"], False)
    assert runtime["relations"] == {"peers": {"乙": "同伴"}}
    assert runtime["address_patterns"] == {"乙": "乙"}
    assert [item["source_id"] for item in runtime["speech"]["voice_sequences"]] == ["local"]
    assert runtime["special_mechanisms"] == {"光环": "本场有关"}
    with_teacher = WritingService._runtime_character_card(content, "rev", {}, ["甲", "乙"], True)
    assert "sensei" in with_teacher["relations"]
    assert "老师" in with_teacher["address_patterns"]
    assert len(with_teacher["speech"]["voice_sequences"]) == 2
    assert "丙" in content["ba_profile"]["relations"]["peers"]


def test_runtime_card_uses_constraint_values_instead_of_category_keys():
    runtime = WritingService._runtime_character_card(
        {"name": "甲", "ba_profile": {"ooc_constraints": {"forbidden": ["不替别人猜动机。"], "boundary": "不读心。"}}},
        "rev", {}, ["甲"], False,
    )
    assert runtime["ooc_constraints"] == ["不替别人猜动机。", "不读心。"]

