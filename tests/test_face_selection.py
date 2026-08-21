from annotation_chunks import assign_annotation_ids
from face_selection import (
    infer_face_intent, rank_face_candidates, silent_reaction_shortlists,
    target_face_shortlists,
)


def _face(
    face_id, semantic, *, beats=(), delivery=(), tags=(), intensity=1,
    frequency="common", expression_class="base", avoid="", ready=True,
    official=None, modes=(),
):
    return {
        "id": face_id,
        "semantic_cn": semantic,
        "beat_fit": list(beats),
        "delivery_fit": list(delivery),
        "semantic_tags": list(tags),
        "intensity": intensity,
        "usage_frequency": frequency,
        "expression_class": expression_class,
        "avoid_when_cn": avoid,
        "backend_selection_ready": ready,
        "official_usage_profile": dict(official or {}),
        "semantic_modes": list(modes),
    }


def _aris_faces():
    return [
        _face(
            "01", "平静好奇｜适合询问和倾听",
            beats=("question", "listening"),
            delivery=("listening", "soft_speech", "normal_speech"),
            tags=("curious",),
        ),
        _face(
            "02", "无神平淡｜只适合失神停顿",
            beats=("idle", "hesitation"),
            delivery=("silent_reaction", "listening"),
            tags=("blank",), frequency="rare",
            avoid="普通对话、正式报告或需要鲜活反应时不要使用",
            official={
                "total_count": 10, "lexical_dialogue_count": 0,
                "nonlexical_dialogue_count": 5, "no_dialogue_count": 5,
            },
        ),
        _face(
            "05", "认真坚定｜正式报告、任务推进或认真确认",
            beats=("exposition", "tension"),
            delivery=("normal_speech", "emphatic_speech"),
            tags=("focused", "serious", "determined"), intensity=2,
            official={"total_count": 63, "lexical_dialogue_count": 58},
        ),
    ]


def test_label_backend_prefers_aris_question_face_over_blank_face():
    intent = infer_face_intent("是在哪里找到的？真奇怪。")
    ranked = rank_face_candidates(_aris_faces(), intent)
    assert [item["id"] for item in ranked[:2]] == ["01", "05"]
    assert ranked[-1]["id"] == "02"


def test_label_backend_prefers_aris_report_face_and_uses_official_profile():
    intent = infer_face_intent("报告：检查结果已确认完毕。")
    ranked = rank_face_candidates(_aris_faces(), intent)
    assert ranked[0]["id"] == "05"
    assert ranked[-1]["id"] == "02"


def test_negative_discovery_report_is_not_mistaken_for_a_reveal():
    intent = infer_face_intent("报告：入口区域没有发现异常。")
    assert "exposition" in intent["beats"]
    assert "reveal" not in intent["beats"]
    assert "surprised" not in intent["semantic_tags"]


def test_exploration_start_is_an_outward_action_celebration():
    intent = infer_face_intent("探索任务开始了！！")
    assert {"exposition", "celebration", "action"} <= set(intent["beats"])
    assert {"joyful", "determined"} <= set(intent["semantic_tags"])
    assert intent["delivery"] == "shout"


def test_serious_shout_is_not_automatically_a_surprise_reaction():
    intent = infer_face_intent("我是认真的！！")
    assert "exposition" in intent["beats"]
    assert "reaction" not in intent["beats"]
    assert {"serious", "assertive", "determined"} <= set(intent["semantic_tags"])


def test_serious_shout_prefers_a_serious_face_over_a_generic_shout_face():
    faces = [
        _face(
            "00", "热血宣告", beats=("action", "exposition"),
            delivery=("shout", "emphatic_speech"),
            tags=("assertive", "determined", "joyful"), intensity=2,
            frequency="default",
        ),
        _face(
            "05", "认真据理力争", beats=("conflict", "exposition"),
            delivery=("normal_speech", "emphatic_speech"),
            tags=("serious", "assertive", "determined"), intensity=2,
        ),
    ]

    ranked = rank_face_candidates(faces, infer_face_intent("我是认真的！！"))
    assert ranked[0]["id"] == "05"


def test_serious_shout_accepts_assertive_determined_face_without_literal_serious_tag():
    faces = [
        _face(
            "05", "激烈主张", beats=("conflict", "denial"),
            delivery=("emphatic_speech", "shout"),
            tags=("assertive", "angry"), intensity=2,
            modes=({
                "label_cn": "激烈主张", "beat_fit": ["conflict"],
                "delivery_fit": ["emphatic_speech", "shout"], "intensity": 2,
                "semantic_tags": ["assertive", "determined"],
                "avoid_when_cn": "没有明确立场时",
            },),
        ),
        _face(
            "07", "压着不满的认真", beats=("exposition", "tension"),
            delivery=("normal_speech", "emphatic_speech"),
            tags=("serious", "resigned"), intensity=1,
        ),
    ]

    ranked = rank_face_candidates(faces, infer_face_intent("我是认真的！！"))
    assert ranked[0]["id"] == "05"


def test_intent_reads_defensive_objectivity_as_denial_and_hesitation():
    intent = infer_face_intent("强装客观的辩解")

    assert {"denial", "hesitation"} <= set(intent["beats"])
    assert {"resigned", "assertive"} <= set(intent["semantic_tags"])


def test_intent_reads_command_peak_without_mapping_to_a_specific_face():
    intent = infer_face_intent("删掉。全部。现在。")

    assert {"conflict", "denial"} <= set(intent["beats"])
    assert {"angry", "assertive"} <= set(intent["semantic_tags"])
    assert intent["intensity"] >= 2


def test_intent_reads_withheld_speech_as_embarrassed_hesitation():
    intent = infer_face_intent("你——")

    assert "hesitation" in intent["beats"]
    assert {"embarrassed", "resigned"} <= set(intent["semantic_tags"])


def test_crying_shout_prefers_setback_face():
    faces = [
        _face(
            "00", "热血宣告", beats=("action", "exposition"),
            delivery=("shout",), tags=("assertive", "joyful"), intensity=2,
        ),
        _face(
            "06", "委屈崩溃", beats=("setback", "comedy"),
            delivery=("shout", "soft_speech"),
            tags=("distressed", "sad", "resigned"), intensity=3,
            frequency="conditional", expression_class="peak",
        ),
    ]

    ranked = rank_face_candidates(faces, infer_face_intent("呜哇，怎么会这样啊！！"))
    assert ranked[0]["id"] == "06"


def test_distressed_refusal_is_not_misread_as_angry_conflict():
    intent = infer_face_intent("不要啊，怎么会这样！！")

    assert "setback" in intent["beats"]
    assert "conflict" not in intent["beats"]
    assert {"afraid", "distressed", "sad"} <= set(intent["semantic_tags"])
    assert "angry" not in intent["semantic_tags"]


def test_shocked_stutter_is_not_automatically_embarrassment():
    intent = infer_face_intent("怎、怎么会这样！？")

    assert {"reaction", "setback"} <= set(intent["beats"])
    assert "embarrassment" not in intent["beats"]
    assert {"surprised", "afraid", "distressed"} <= set(intent["semantic_tags"])
    assert "embarrassed" not in intent["semantic_tags"]


def test_more_specific_shock_face_beats_generic_collapse_face():
    faces = [
        _face(
            "04", "恐慌崩溃", beats=("reaction", "setback"),
            delivery=("emphatic_speech", "shout"),
            tags=("afraid", "surprised", "distressed"), intensity=3,
            frequency="conditional", expression_class="peak",
        ),
        _face(
            "08", "恐惧追问", beats=("question", "reaction", "setback"),
            delivery=("emphatic_speech", "shout"),
            tags=("curious", "afraid", "surprised"), intensity=3,
            frequency="conditional", expression_class="peak",
        ),
    ]

    ranked = rank_face_candidates(faces, infer_face_intent("怎、怎么会这样！？"))
    assert ranked[0]["id"] == "08"


def test_action_launch_does_not_invent_laughter_to_use_a_laughing_face():
    faces = [
        _face(
            "03", "兴奋喜悦", beats=("celebration", "action"),
            delivery=("emphatic_speech", "shout"),
            tags=("joyful", "determined"), intensity=2,
        ),
        _face(
            "07", "开怀欢笑", beats=("celebration",),
            delivery=("shout",), tags=("joyful", "playful"), intensity=3,
        ),
    ]

    ranked = rank_face_candidates(faces, infer_face_intent("探索任务开始了！！"))
    assert ranked[0]["id"] == "03"


def test_nonlexical_official_profile_brings_blank_pause_face_forward():
    ranked = rank_face_candidates(_aris_faces(), infer_face_intent("……"))
    assert ranked[0]["id"] == "02"


def test_alternate_semantic_mode_can_match_without_rewriting_primary_label():
    faces = [_face(
        "99", "闭目从容",
        beats=("listening",), delivery=("listening",), tags=("gentle",),
        modes=({
            "label_cn": "平静说明",
            "beat_fit": ["exposition"],
            "delivery_fit": ["soft_speech", "normal_speech"],
            "intensity": 1,
            "semantic_tags": ["serious", "gentle"],
            "avoid_when_cn": "激烈喊叫",
        },),
    )]
    ranked = rank_face_candidates(faces, infer_face_intent("报告：目前情况稳定。"))
    assert ranked[0]["id"] == "99"
    assert ranked[0]["modes"] == ["平静说明"]


def test_special_face_can_rank_first_only_when_its_label_matches_the_line():
    faces = [
        _face("00", "平静回应", beats=("dialogue",), delivery=("normal_speech",)),
        _face(
            "04", "空白眼冷汗｜荒谬冲击后思维短路",
            beats=("reaction", "comedy"), delivery=("silent_reaction",),
            tags=("blank", "surprised"), intensity=3, frequency="rare",
            expression_class="special",
        ),
    ]
    ordinary = rank_face_candidates(faces, infer_face_intent("我知道了。"))
    reveal = rank_face_candidates(faces, infer_face_intent("竟然会在这里！？"))
    assert ordinary[0]["id"] == "00"
    assert reveal[0]["id"] == "04"


def test_backend_blocked_face_never_enters_shortlist():
    faces = _aris_faces() + [_face("14", "红眼人格状态", ready=False)]
    ranked = rank_face_candidates(faces, infer_face_intent("报告：任务开始。"))
    assert "14" not in {item["id"] for item in ranked}


def test_normal_aris_persona_faces_are_blocked_even_with_stale_v3_backend_state():
    faces = [
        _face("05", "严肃专注", beats=("exposition",), tags=("serious",)),
        _face("12", "阴暗失控", beats=("exposition",), tags=("serious",)),
        _face("13", "释怀感动", beats=("comfort",), tags=("gentle",)),
        _face("17", "冰冷凝视", beats=("exposition",), tags=("serious",)),
    ]

    ranked = rank_face_candidates(
        faces, infer_face_intent("报告：情况已确认。"), character_id="아리스N",
    )

    assert {item["id"] for item in ranked} == {"05", "13"}


def test_target_shortlist_is_per_line_and_keeps_previous_face_as_soft_context():
    items = [
        {"kind": "line", "who": "爱丽丝", "text": "这是在哪里找到的？"},
        {"kind": "line", "who": "爱丽丝", "text": "报告：任务开始。"},
    ]
    result = target_face_shortlists(
        items,
        [0, 1],
        cast={"爱丽丝": {"id": "aris", "portrait": True}},
        constraints={"face_records_by_id": {"aris": _aris_faces()}},
        last_faces={"爱丽丝": "01"},
    )
    assert result[0]["candidates"][0]["id"] == "01"
    assert result[1]["candidates"][0]["id"] == "05"
    assert result[0]["previous_face"] == "01"


def test_target_full_options_keep_rank_order_but_include_every_safe_face():
    items = [{
        "kind": "line", "who": "爱丽丝", "text": "这是在哪里找到的？",
    }]
    result = target_face_shortlists(
        items,
        [0],
        cast={"爱丽丝": {"id": "aris", "portrait": True}},
        constraints={"face_records_by_id": {"aris": _aris_faces()}},
        include_all=True,
    )

    assert {candidate["id"] for candidate in result[0]["candidates"]} == {
        "01", "02", "05",
    }
    assert result[0]["candidates"][0]["id"] == "01"


def test_target_shortlist_uses_face_arc_as_a_soft_plan_signal():
    items = assign_annotation_ids([{
        "kind": "line", "line_no": 1, "split_index": 0,
        "who": "爱丽丝", "text": "我知道了。", "raw": "爱丽丝: 我知道了。",
    }])
    anchor_id = items[0]["annotation_id"]
    cheerful = _face(
        "00", "轻松开心", beats=("dialogue",), tags=("joyful",),
    )
    cheerful["visual_facts"] = {
        "eye_openness": "open", "gaze": "forward", "brow_shape": "raised",
        "mouth_openness": "open", "mouth_shape": "smile",
    }
    serious = _face(
        "05", "认真坚定", beats=("exposition",),
        tags=("serious", "focused", "determined"), intensity=2,
    )
    serious["visual_facts"] = {
        "eye_openness": "open", "gaze": "forward", "brow_shape": "knitted",
        "mouth_openness": "closed", "mouth_shape": "neutral",
    }
    plan = {"events": [{
        "source_ids": [anchor_id],
        "face_arcs": [{
            "who": "爱丽丝", "stages": [{
                "anchor_id": anchor_id, "position": "on",
                "semantic_state": "认真而坚定地接手任务",
                "change_reason": "从轻松闲聊切换到任务执行",
            }],
        }],
        "performance_intents": [{
            "anchor_id": anchor_id, "subjects": ["爱丽丝"],
            "carriers": ["face_change"], "purpose": "表现状态转折",
        }],
        "peaks": [],
    }]}

    result = target_face_shortlists(
        items, [0],
        cast={"爱丽丝": {"id": "aris", "portrait": True}},
        constraints={"face_records_by_id": {"aris": [cheerful, serious]}},
        last_faces={"爱丽丝": "00"}, scene_event_plan=plan,
    )

    assert result[0]["candidates"][0]["id"] == "05"
    assert "stage_change" in result[0]["candidates"][0]["match"]
    assert result[0]["plan"]["semantic_state"] == "认真而坚定地接手任务"
    assert result[0]["plan"]["stage_change"] is True


def test_face_arc_state_is_not_contaminated_by_another_characters_change_reason():
    items = assign_annotation_ids([{
        "kind": "line", "line_no": 1, "split_index": 0,
        "who": "爱丽丝", "text": "没错！来跟爱丽丝和伙伴们一起玩游戏吧！",
        "raw": "爱丽丝: 没错！来跟爱丽丝和伙伴们一起玩游戏吧！",
    }])
    anchor_id = items[0]["annotation_id"]
    faces = [
        _face(
            "03", "开怀欢呼致谢", beats=("celebration",),
            delivery=("emphatic_speech", "shout"), tags=("joyful",), intensity=2,
        ),
        _face(
            "05", "严肃专注", beats=("exposition",),
            delivery=("emphatic_speech",), tags=("serious", "focused"), intensity=2,
        ),
        _face(
            "06", "慌乱无措", beats=("reaction", "setback"),
            delivery=("shout",), tags=("surprised", "distressed"), intensity=3,
        ),
        _face(
            "07", "崩溃哀鸣", beats=("setback",),
            delivery=("shout",), tags=("sad", "distressed"), intensity=3,
        ),
    ]
    plan = {"events": [{
        "source_ids": [anchor_id],
        "face_arcs": [{
            "who": "爱丽丝", "stages": [{
                "anchor_id": anchor_id, "position": "on",
                "semantic_state": "更直接热切的邀请",
                "change_reason": "圣娅意外反问后再次确认",
            }],
        }],
        "performance_intents": [{
            "anchor_id": anchor_id, "subjects": ["爱丽丝"],
            "carriers": ["face_change"], "purpose": "坚定纳入伙伴",
        }],
        "peaks": [],
    }]}

    result = target_face_shortlists(
        items, [0],
        cast={"爱丽丝": {"id": "aris", "portrait": True}},
        constraints={"face_records_by_id": {"aris": faces}},
        scene_event_plan=plan, limit=4,
    )

    ranked_ids = [candidate["id"] for candidate in result[0]["candidates"]]
    assert ranked_ids[0] == "03"
    assert ranked_ids.index("03") < ranked_ids.index("06")
    assert ranked_ids.index("03") < ranked_ids.index("07")


def test_duplicate_semantic_tokens_remain_unambiguous():
    faces = [
        _face("01", "认真", beats=("exposition",), tags=("serious",)),
        _face("05", "认真", beats=("exposition",), tags=("serious",)),
    ]

    ranked = rank_face_candidates(
        faces, infer_face_intent("报告：已经确认。"), limit=2,
    )

    assert [candidate["id"] for candidate in ranked] == ["01", "05"]
    assert len({candidate["token"] for candidate in ranked}) == 2
    assert ranked[1]["token"].endswith("·2]")


def test_silent_shortlist_is_only_created_for_planned_emotional_beats():
    items = assign_annotation_ids([{
        "kind": "line", "line_no": 1, "split_index": 0,
        "who": "爱丽丝", "text": "我们找到了。", "raw": "爱丽丝: 我们找到了。",
    }])
    anchor_id = items[0]["annotation_id"]
    plan = {"events": [{
        "kind": "discovery", "stimulus": "发现异常线索", "outcome": "众人惊讶",
        "peak_reason": "发现", "silent_beats": [{
            "anchor_id": anchor_id, "position": "after", "phase": "group_reaction",
            "purpose": "共同看到线索", "participants": ["爱丽丝"],
        }, {
            "anchor_id": anchor_id, "position": "after", "phase": "time_bridge",
            "purpose": "时间经过", "participants": ["爱丽丝"],
        }],
    }]}

    result = silent_reaction_shortlists(
        items,
        [0],
        cast={"爱丽丝": {"id": "aris", "portrait": True}},
        constraints={"face_records_by_id": {"aris": _aris_faces()}},
        scene_event_plan=plan,
    )

    assert len(result) == 1
    assert result[0]["phase"] == "group_reaction"
    assert result[0]["faces"]["爱丽丝"][0]["token"].startswith("[Emo:")
