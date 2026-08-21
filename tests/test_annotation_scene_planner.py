from annotation_chunks import assign_annotation_ids
from annotation_scene_planner import (
    EVENT_PHASES,
    PEAK_TYPES,
    PLANNER_SYSTEM,
    STAGING_PLANNER_SYSTEM,
    _event_schema,
    event_plan_fulfillment_errors,
    normalize_scene_event_plan,
    project_scene_event_plan,
    sanitize_scene_event_plan_for_cast,
)


def test_planner_treats_declared_carriers_as_flexible_contract_without_quotas():
    assert "当前输入文本及其上下文是唯一剧情证据" in PLANNER_SYSTEM
    assert "听者停顿" in PLANNER_SYSTEM
    assert "剧情事实采取严格标准" in PLANNER_SYSTEM
    assert "默认表示可替代的实现集合" in PLANNER_SYSTEM
    assert "require_all=true" in PLANNER_SYSTEM
    assert "低指令数量不等于克制或质量" in PLANNER_SYSTEM
    assert "单人正反打是正常且常用的镜头语法" in PLANNER_SYSTEM
    assert "有动机的完整硬切搭档轮换" in PLANNER_SYSTEM
    assert "角色可以跨 hard cut 保留同一侧" in STAGING_PLANNER_SYSTEM
    assert "不需要为了切镜虚构 move、enter 或 exit" in STAGING_PLANNER_SYSTEM
    assert "强标点只是必须复核的信号" in PLANNER_SYSTEM
    assert "peak 只表示场景内的相对升级" in PLANNER_SYSTEM
    assert "不能把首次露面自动当入场" in PLANNER_SYSTEM
    assert "不压成全员同步" in PLANNER_SYSTEM
    assert "给 G2 的语义假设" in PLANNER_SYSTEM
    assert "上一有效演出节点（对白或无对白）" in PLANNER_SYSTEM
    assert "才规划 silent_beat" in PLANNER_SYSTEM
    assert "不能在第二阶段被合并成普通对白" in STAGING_PLANNER_SYSTEM
    assert "让位/靠近" in STAGING_PLANNER_SYSTEM
    assert "普通反打、显现和人数变化不规划 trans" in STAGING_PLANNER_SYSTEM
    assert "OFFSCREEN_NAMED_SPEAKERS" in PLANNER_SYSTEM
    assert "不能为了双人关系构图虚构其立绘" in PLANNER_SYSTEM
    assert 'carriers=["action"]' in PLANNER_SYSTEM
    assert "不要把这种 action 与" in PLANNER_SYSTEM
    assert "物件操作本身不等于通用身体 action" in PLANNER_SYSTEM
    assert "不构成动作数量要求" in PLANNER_SYSTEM


def test_named_offscreen_speakers_keep_story_semantics_but_lose_portrait_work():
    plan = {"scene_id": "scene-1", "events": [{
        "event_id": "e1",
        "stimulus_targets": ["凯伊", "老师"],
        "shot_groups": [{
            "group_id": "g1", "anchor_id": "L1", "hold_until_id": "L1",
            "members": ["凯伊", "老师"], "focus": "老师", "framing": "relation",
        }],
        "focus_turns": ["老师", "凯伊"],
        "performance_intents": [
            {"anchor_id": "L1", "subjects": ["老师"], "carriers": ["action"]},
            {"anchor_id": "L1", "subjects": ["凯伊"], "carriers": ["face_change"]},
        ],
        "face_arcs": [{"who": "老师", "stages": [{}]}, {"who": "凯伊", "stages": [{}]}],
        "silent_beats": [{"anchor_id": "L1", "participants": ["老师"]}],
        "peaks": [{"peak_id": "L1", "subject": "凯伊", "peak_type": "relationship_peak"}],
    }]}
    cast = {
        "凯伊": {"portrait": True},
        "老师": {"portrait": False},
    }

    sanitized = sanitize_scene_event_plan_for_cast(plan, cast)
    event = sanitized["events"][0]

    assert event["stimulus_targets"] == ["凯伊", "老师"]
    assert event["shot_groups"][0]["members"] == ["凯伊"]
    assert event["shot_groups"][0]["_offscreen_members"] == ["老师"]
    assert event["shot_groups"][0]["focus"] == "凯伊"
    assert event["focus_turns"] == ["凯伊"]
    assert [item["subjects"] for item in event["performance_intents"]] == [["凯伊"]]
    assert [item["who"] for item in event["face_arcs"]] == ["凯伊"]
    assert event["silent_beats"] == []
    assert event["peaks"][0]["subject"] == "凯伊"


def test_planner_proactively_scans_staging_without_inventing_plot():
    assert PLANNER_SYSTEM.count("积极演出扫描（唯一版本）") == 1
    for opportunity in (
        "注意对象改变", "预期被打破", "回答前的犹豫", "可见身体意图",
        "关系压力或距离改变", "结果落地后的情绪余波",
    ):
        assert opportunity in PLANNER_SYSTEM
    assert "先判断变化能否自然承载在对白节点" in PLANNER_SYSTEM
    assert "必须在下一句开口前被观众单独读到" in PLANNER_SYSTEM
    assert "演出推断采取主动标准" in PLANNER_SYSTEM
    assert "剧情事实采取严格标准" in PLANNER_SYSTEM
    assert "不设节点、镜头或资源配额" in PLANNER_SYSTEM
    assert "主动抵抗最低工作量偏置" in PLANNER_SYSTEM
    assert "省略、hold 和 face-only 不是天然安全答案" in PLANNER_SYSTEM


def _targets():
    return assign_annotation_ids([
        {
            "kind": "line", "line_no": index, "split_index": 0,
            "who": who, "text": text, "raw": f"{who}: {text}",
        }
        for index, (who, text) in enumerate((
            ("圣娅", "……各位？"),
            ("桃井", "到底跑哪去了？"),
            ("绿", "为什么是弄丢的人在生气？"),
            ("圣娅", "那就一起试试看吧。"),
            ("桃井", "这个人怎么这么厉害？"),
        ), 1)
    ])


def _plan(targets):
    return normalize_scene_event_plan({"events": [
        {
            "event_id": "disturbance",
            "start_i": 1,
            "end_i": 3,
            "kind": "disturbance",
            "stimulus": "访客发现回应异常",
            "outcome": "画外争执被揭示",
            "phase_order": ["cue", "reveal", "group_reaction"],
            "shot_groups": [["圣娅"], ["桃井", "绿"]],
            "focus_turns": ["圣娅", "桃井", "绿"],
            "silent_beats": [
                {
                    "anchor_i": 1,
                    "position": "after",
                    "phase": "cue",
                    "purpose": "先听见画外骚动",
                    "participants": ["圣娅"],
                    "sound_motivated": True,
                },
                {
                    "anchor_i": 2,
                    "position": "before",
                    "phase": "reveal",
                    "purpose": "揭示争执来源",
                    "participants": ["桃井", "绿"],
                    "sound_motivated": False,
                },
            ],
            "continuity_goal": "从观察者切到声源小组",
            "peak_character": "桃井",
            "peak_reason": "争执爆点",
        },
        {
            "event_id": "play",
            "start_i": 4,
            "end_i": 5,
            "kind": "montage",
            "stimulus": "众人开始共同活动",
            "outcome": "时间推进到赛后评价",
            "phase_order": ["time_bridge", "relay"],
            "shot_groups": [["圣娅"], ["桃井"]],
            "focus_turns": ["圣娅", "桃井"],
            "silent_beats": [{
                "anchor_i": 4,
                "position": "after",
                "phase": "time_bridge",
                "purpose": "用声音推进共同活动和时间",
                "participants": [],
                "sound_motivated": True,
            }],
            "continuity_goal": "活动结束后重建评价者接力",
            "peak_character": "桃井",
            "peak_reason": "赛后第一反应",
        },
    ]}, targets, "scene-1")


def test_event_plan_supports_reveal_object_decision_time_bridge_and_relay():
    assert {
        "reveal", "object_action", "feedback", "verification",
        "decision_pause", "time_bridge", "relay",
    } <= set(EVENT_PHASES)


def test_plan_v2_schema_exposes_event_level_performance_face_and_peak_contracts():
    schema = _event_schema(5, ["圣娅", "桃井", "绿"])
    event = schema["properties"]["events"]["items"]
    properties = event["properties"]

    assert set(PEAK_TYPES) == {
        "solo_emphasis", "relationship_peak", "group_reaction",
    }
    assert {
        "stimulus_targets", "shot_groups", "performance_intents", "face_arcs",
        "silent_beats", "peaks", "result_owner", "aftershock_owner",
        "release_owner",
    } <= set(properties)
    assert "stimulus_targets" in event["required"]
    assert {
        "result_owner", "aftershock_owner", "release_owner",
    } <= set(event["required"])
    assert "maxItems" not in properties["stimulus_targets"]
    assert properties["shot_groups"]["items"]["properties"]["members"]["maxItems"] == 3
    assert properties["silent_beats"]["items"]["properties"]["participants"]["maxItems"] == 3
    carrier = properties["silent_beats"]["items"]["properties"]["carrier_requirement"]
    assert carrier["properties"]["any_of"]["minItems"] == 1
    performance = properties["performance_intents"]["items"]
    assert performance["properties"]["require_all"] == {"type": "boolean"}
    assert "require_all" not in performance["required"]
    shot_group = properties["shot_groups"]["items"]
    assert "hold_until_i" in shot_group["required"]
    assert "peak_character" not in event["required"]


def test_projected_face_arc_keeps_adjacent_stages_as_read_only_context():
    targets = _targets()
    plan = normalize_scene_event_plan({"events": [{
        "event_id": "face-chain",
        "start_i": 1,
        "end_i": 5,
        "kind": "inference",
        "stimulus": "逐步确认情况",
        "stimulus_targets": ["圣娅"],
        "outcome": "从疑惑转为确信",
        "phase_order": ["relay"],
        "shot_groups": [],
        "focus_turns": ["圣娅"],
        "performance_intents": [],
        "face_arcs": [{
            "who": "圣娅",
            "stages": [
                {"anchor_i": 1, "position": "on", "semantic_state": "疑惑", "change_reason": "尚未确认"},
                {"anchor_i": 3, "position": "on", "semantic_state": "认真", "change_reason": "开始推理"},
                {"anchor_i": 5, "position": "on", "semantic_state": "释然", "change_reason": "得到答案"},
            ],
        }],
        "silent_beats": [],
        "peaks": [],
        "continuity_goal": "保持同一反应链",
    }]}, targets, "scene-1")

    projected = project_scene_event_plan(plan, [targets[2]["annotation_id"]])
    stages = projected["active_events"][0]["face_arcs"][0]["stages"]

    assert [stage["context_role"] for stage in stages] == [
        "previous", "active", "next",
    ]
    assert [stage["anchor_i"] for stage in stages] == [0, 1, 0]


def test_normalize_repairs_flattened_model_arrays_without_changing_choices():
    targets = _targets()
    plan = normalize_scene_event_plan({"events": [{
        "event_id": "flat-arrays",
        "start_i": 1,
        "end_i": 2,
        "kind": "disturbance",
        "stimulus": "关系压力",
        "stimulus_targets": "圣娅, 桃井",
        "outcome": "两人停顿",
        "phase_order": ["cue"],
        "shot_groups": [{
            "group_id": "pair",
            "anchor_i": 1,
            "hold_until_i": 2,
            "members": "圣娅 桃井",
            "focus": "圣娅",
            "framing": "relation",
            "operation": "establish",
            "cut_motivation": "建立关系",
            "purpose": "保留互动",
        }],
        "focus_turns": "圣娅 桃井",
        "performance_intents": [{
            "anchor_i": 1,
            "position": "on",
            "subjects": "圣娅",
            "carriers": "face_change action",
            "purpose": "读出反应",
        }],
        "face_arcs": [],
        "silent_beats": [],
        "peaks": [],
        "continuity_goal": "保持关系",
    }]}, targets, "scene-1")

    event = plan["events"][0]
    assert event["stimulus_targets"] == ["圣娅", "桃井"]
    assert event["focus_turns"] == ["圣娅", "桃井"]
    assert event["shot_groups"][0]["members"] == ["圣娅", "桃井"]
    assert event["performance_intents"][0]["subjects"] == ["圣娅"]
    assert event["performance_intents"][0]["carriers"] == ["face_change", "action"]


def test_normalize_and_project_plan_v2_preserves_stable_source_anchors():
    targets = _targets()
    plan = normalize_scene_event_plan({"events": [{
        "event_id": "escalation",
        "start_i": 2,
        "end_i": 4,
        "kind": "group_escalation",
        "stimulus": "桃井提高音量",
        "outcome": "圣娅介入",
        "phase_order": ["group_reaction", "focus_handoff"],
        "shot_groups": [{
            "group_id": "momoi-solo", "anchor_i": 2, "members": ["桃井"],
            "focus": "桃井", "framing": "close", "operation": "switch",
            "cut_motivation": "个人情绪升级", "purpose": "先承接爆点",
        }, {
            "group_id": "seia-handoff", "anchor_i": 4, "members": ["圣娅"],
            "focus": "圣娅", "framing": "medium", "operation": "switch",
            "cut_motivation": "焦点承受者改变", "purpose": "介入",
        }],
        "focus_turns": ["桃井", "圣娅"],
        "performance_intents": [{
            "anchor_i": 2, "position": "on", "subjects": ["桃井"],
            "carriers": ["face_change", "action"], "purpose": "情绪爆发",
        }],
        "face_arcs": [{
            "who": "圣娅", "stages": [{
                "anchor_i": 4, "position": "on", "semantic_state": "认真介入",
                "change_reason": "决定接手问题",
            }],
        }],
        "silent_beats": [{
            "anchor_i": 3, "position": "after", "phase": "group_reaction",
            "purpose": "两人被叫停", "participants": ["桃井", "绿"],
            "sound_motivated": False,
            "carrier_requirement": {
                "any_of": ["face_change", "emoticon"],
                "require_observable_change": True,
            },
        }],
        "peaks": [{
            "subject": "桃井", "peak_type": "solo_emphasis",
            "peak_i": 2, "position": "on", "visual_intent": "个人喜剧爆点",
            "release_i": 3, "release_position": "on",
            "why": "这句完成升级",
        }],
        "continuity_goal": "从爆点交给介入者",
    }]}, targets, "scene-1")

    event = plan["events"][0]
    assert event["shot_groups"][0]["anchor_id"] == targets[1]["annotation_id"]
    assert event["shot_groups"][0]["hold_until_id"] == targets[2]["annotation_id"]
    assert event["shot_groups"][1]["hold_until_id"] == targets[3]["annotation_id"]
    assert event["performance_intents"][0]["anchor_id"] == targets[1]["annotation_id"]
    assert event["face_arcs"][0]["stages"][0]["anchor_id"] == targets[3]["annotation_id"]
    assert event["peaks"][0]["peak_id"] == targets[1]["annotation_id"]
    assert event["peaks"][0]["release_id"] == targets[2]["annotation_id"]

    projection = project_scene_event_plan(
        plan, [targets[1]["annotation_id"], targets[2]["annotation_id"]],
    )["active_events"][0]
    assert projection["shot_groups"][0]["anchor_i"] == 1
    assert projection["shot_groups"][0]["hold_until_i"] == 2
    assert projection["performance_intents"][0]["anchor_i"] == 1
    assert projection["silent_beats"][0]["anchor_i"] == 2
    assert projection["peaks"][0]["peak_i"] == 1
    assert projection["peaks"][0]["release_i"] == 2


def test_projection_keeps_active_events_but_only_neighbor_cause_and_outcome():
    targets = _targets()
    plan = _plan(targets)
    projection = project_scene_event_plan(
        plan, [targets[3]["annotation_id"]],
    )

    assert projection["previous_event"] == {
        "event_id": "disturbance", "outcome": "画外争执被揭示",
    }
    assert [event["event_id"] for event in projection["active_events"]] == ["play"]
    assert projection["next_event"] is None
    assert projection["active_events"][0]["silent_beats"][0]["anchor_i"] == 1


def test_fulfillment_rejects_empty_wait_for_sound_cue_and_time_bridge():
    targets = _targets()
    plan = _plan(targets)
    beats = [
        {
            "anchor_id": targets[0]["annotation_id"], "position": "after",
            "who": "圣娅", "face": "", "emo": "", "act": "",
            "wait_ms": 600, "reason": "offscreen_cue",
        },
        {
            "anchor_id": targets[3]["annotation_id"], "position": "after",
            "who": "圣娅", "face": "", "emo": "", "act": "",
            "wait_ms": 1200, "reason": "montage",
        },
    ]

    errors = event_plan_fulfillment_errors(
        plan,
        [targets[0]["annotation_id"], targets[3]["annotation_id"]],
        beats,
    )

    assert any("cue" in error and "声音" in error for error in errors)
    assert any("time_bridge" in error and "声画载体" in error for error in errors)


def test_fulfillment_accepts_motivated_cue_reveal_and_time_bridge():
    targets = _targets()
    plan = _plan(targets)
    beats = [
        {
            "anchor_id": targets[0]["annotation_id"], "position": "after",
            "who": "圣娅", "face": "", "emo": "", "act": "",
            "wait_ms": 500, "reason": "offscreen_cue", "se": "SE_Noise",
            "visible_characters": [], "positions": {},
        },
        {
            "anchor_id": targets[1]["annotation_id"], "position": "before",
            "who": "桃井", "face": "04", "emo": "", "act": "",
            "wait_ms": 0, "reason": "entrance_reveal",
            "visible_characters": ["桃井", "绿"],
            "positions": {"桃井": 2, "绿": 4}, "shot_transition": "cut",
        },
        {
            "anchor_id": targets[3]["annotation_id"], "position": "after",
            "who": "圣娅", "face": "", "emo": "", "act": "",
            "wait_ms": 1500, "reason": "montage", "se": "SE_Game",
            "visible_characters": [], "positions": {},
        },
    ]

    assert event_plan_fulfillment_errors(
        plan,
        [targets[0]["annotation_id"], targets[1]["annotation_id"], targets[3]["annotation_id"]],
        beats,
    ) == []


def test_fulfillment_rejects_actual_silent_phase_order_reversal():
    targets = _targets()
    first = targets[0]["annotation_id"]
    plan = {"events": [{
        "event_id": "ordered-reaction", "source_ids": [first],
        "phase_order": ["cue", "group_reaction"],
        "stimulus_targets": ["圣娅", "桃井"],
        "silent_beats": [{
            "anchor_id": first, "position": "after", "phase": "cue",
            "participants": ["圣娅"], "sound_motivated": True,
            "carrier_requirement": {
                "any_of": ["sound"], "require_observable_change": True,
            },
        }, {
            "anchor_id": first, "position": "after", "phase": "group_reaction",
            "participants": ["圣娅", "桃井"], "sound_motivated": False,
            "carrier_requirement": {
                "any_of": ["face_change"], "require_observable_change": True,
            },
        }],
    }]}
    beats = [{
        "anchor_id": first, "position": "after", "who": "圣娅",
        "face": "01", "emo": "", "act": "", "wait_ms": 500,
        "reason": "group_reaction",
        "reactions": [{"who": "桃井", "face": "04", "emo": "", "act": ""}],
    }, {
        "anchor_id": first, "position": "after", "who": "圣娅",
        "face": "", "emo": "", "act": "", "wait_ms": 500,
        "reason": "offscreen_cue", "se": "SE_Noise",
    }]

    errors = event_plan_fulfillment_errors(plan, [first], beats)

    assert any("实际锚点早于其依赖阶段" in error for error in errors)


def test_fulfillment_requires_enter_not_plain_reveal_for_true_arrival():
    anchor = _targets()[0]["annotation_id"]
    plan = {"events": [{
        "event_id": "arrival", "kind": "arrival", "source_ids": [anchor],
        "phase_order": ["reveal"], "stimulus_targets": ["圣娅"],
        "silent_beats": [{
            "anchor_id": anchor, "position": "before", "phase": "reveal",
            "participants": ["圣娅"], "sound_motivated": False,
            "carrier_requirement": {
                "any_of": ["entry_exit"], "require_observable_change": True,
            },
        }],
    }]}
    beats = [{
        "anchor_id": anchor, "position": "before", "who": "圣娅",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal",
        "reveal": [{"who": "圣娅", "slot": 3, "side": "right"}],
    }]

    errors = event_plan_fulfillment_errors(plan, [anchor], beats)

    assert any("没有使用真实 enter" in error for error in errors)


def test_fulfillment_accepts_sequential_reaction_relay_in_stable_group():
    anchor = _targets()[0]["annotation_id"]
    plan = {"events": [{
        "event_id": "reaction-relay", "kind": "aftermath", "source_ids": [anchor],
        "phase_order": ["action", "relay", "aftershock"],
        "stimulus_targets": ["圣娅", "桃井", "绿"],
        "silent_beats": [{
            "anchor_id": anchor, "position": "after", "phase": "action",
            "participants": ["圣娅"], "sound_motivated": False,
            "carrier_requirement": {"any_of": ["face_change"]},
        }, {
            "anchor_id": anchor, "position": "after", "phase": "relay",
            "participants": ["桃井"], "sound_motivated": False,
            "carrier_requirement": {"any_of": ["face_change"]},
        }, {
            "anchor_id": anchor, "position": "after", "phase": "aftershock",
            "participants": ["圣娅", "桃井", "绿"], "sound_motivated": False,
            "carrier_requirement": {"any_of": ["pose_hold"]},
        }],
    }]}
    beats = [{
        "anchor_id": anchor, "position": "after", "who": "圣娅",
        "face": "04", "emo": "", "act": "", "wait_ms": 500,
        "reason": "physical_reaction", "visible_characters": ["圣娅", "桃井", "绿"],
    }, {
        "anchor_id": anchor, "position": "after", "who": "桃井",
        "face": "03", "emo": "", "act": "", "wait_ms": 500,
        "reason": "listener_reaction", "visible_characters": ["圣娅", "桃井", "绿"],
    }, {
        "anchor_id": anchor, "position": "after", "who": "绿",
        "face": "", "emo": "", "act": "", "wait_ms": 700,
        "reason": "comedy_hold", "visible_characters": ["圣娅", "桃井", "绿"],
    }]

    assert event_plan_fulfillment_errors(plan, [anchor], beats) == []


def test_fulfillment_ignores_narrator_only_participant_for_display_match():
    anchor = _targets()[0]["annotation_id"]
    plan = {"events": [{
        "event_id": "time-jump", "kind": "montage", "source_ids": [anchor],
        "phase_order": ["time_bridge"], "stimulus_targets": [],
        "silent_beats": [{
            "anchor_id": anchor, "position": "after", "phase": "time_bridge",
            "participants": ["旁白"], "sound_motivated": False,
            "carrier_requirement": {"any_of": ["background_change"]},
        }],
    }]}
    beats = [{
        "anchor_id": anchor, "position": "after", "who": "圣娅",
        "face": "", "emo": "", "act": "", "wait_ms": 1000,
        "reason": "montage", "trans": "交叉渐变",
    }]

    assert event_plan_fulfillment_errors(plan, [anchor], beats) == []


def test_fulfillment_accepts_camera_change_as_aftershock_payload():
    anchor = _targets()[0]["annotation_id"]
    plan = {"events": [{
        "event_id": "camera-aftershock", "kind": "aftermath", "source_ids": [anchor],
        "phase_order": ["aftershock"], "stimulus_targets": ["A"],
        "silent_beats": [{
            "anchor_id": anchor, "position": "after", "phase": "aftershock",
            "participants": ["A"], "sound_motivated": False,
            "carrier_requirement": {"any_of": ["camera_change"]},
        }],
    }]}
    beats = [{
        "anchor_id": anchor, "position": "after", "who": "A",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction", "visible_characters": ["A", "B"],
        "positions": {"A": 2, "B": 4}, "shot_transition": "cut",
    }]

    assert event_plan_fulfillment_errors(plan, [anchor], beats) == []
