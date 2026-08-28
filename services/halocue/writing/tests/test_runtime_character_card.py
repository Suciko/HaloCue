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

