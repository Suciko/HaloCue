import prompt
from annotation_scene_planner import (
    PLANNER_SYSTEM_COMPACT,
    _event_schema,
    build_scene_planner_request,
)


def test_planned_prompt_has_one_layered_contract_and_no_full_director_manual():
    planned = prompt.build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "DIRECTOR PRINCIPLES" in planned
    assert "OUTPUT PROTOCOL" in planned
    assert "HARD CONSTRAINTS" in planned
    assert "本轮使用 `SCENE_EVENT_PLAN`，但计划不是官方答案" in planned
    assert planned.count("PROACTIVE STAGING RULE（积极导演规则") == 1
    assert planned.count("VISIBLE_CHANGE_RULE") == 1
    assert "Actively resist the lowest-effort bias" in planned
    assert "九种场景功能" not in planned
    assert "官方演出语义区分全部可用符号" not in planned


def test_planned_prompt_keeps_hard_constraints_separate_from_soft_choices():
    planned = prompt.build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    hard = planned.index("HARD CONSTRAINTS")
    soft = planned.index("SOFT DIRECTING")
    assert hard < soft
    assert "最多三名可见角色" in planned[hard:]
    assert "后端只负责" in planned[hard:]
    assert "不设固定数量、冷却、相邻禁用或字符预算" in planned[soft:]


def test_planned_prompt_invites_evidence_backed_silent_beats():
    planned = prompt.build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert planned.count("PROACTIVE STAGING RULE（积极导演规则") == 1
    assert "actively scan six directing" in planned
    assert "make it\nreadable by default" in planned
    assert "Use an independent silent beat only when" in planned
    assert "Omission, hold and face-only are not\nneutral safe defaults" in planned


def test_planned_prompt_learns_official_grammar_without_copying_official_rhythm():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "Performance inference is proactive; plot inference is strict" in planned
    assert "Official examples provide directing grammar" in planned
    assert "An object operation,\narrival/departure" in planned
    assert "CAST/VISIBILITY FACT" in planned
    assert "cast/resource list says who can be rendered; it is not\nthe opening shot" in planned
    assert "speak later, appear in DISPLAYABLE_CAST" in planned
    assert "Offscreen/narrator-only speakers" in planned


def test_planned_prompt_chooses_carriers_after_detecting_causal_opportunity():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    scan = planned.index("actively scan six directing")
    carrier = planned.index("most specific natural carrier")
    dialogue = planned.index("First ask whether it")
    silent = planned.index("Use an independent silent beat only when")
    compare = planned.index("compare a more embodied")
    assert scan < carrier < dialogue < silent < compare
    assert "Do not confuse low command count with restraint or quality" in planned


def test_planned_prompt_resists_lowest_effort_face_only_bias():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "compare a more embodied, relational or cinematic" in planned
    assert "Omission, hold and face-only are not\nneutral safe defaults" in planned
    assert "Do not confuse low command count with restraint or quality" in planned
    assert "主动抵抗最低工作量偏置" in PLANNER_SYSTEM_COMPACT
    assert "省略、hold 和 face-only 不是天然安全答案" in PLANNER_SYSTEM_COMPACT
    assert "低指令数量不等于克制或质量" in PLANNER_SYSTEM_COMPACT
    assert "primary phenomenon" not in planned
    assert "A speaking line normally deserves" not in planned


def test_planned_prompt_keeps_body_actions_semantically_specific():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "use a new\nact only when the body is doing something newly readable" in planned
    assert "A facial, attention or\nattitude change does not become clearer" in planned
    assert "选择 act 时先描述观众实际会看到的身体运动" in planned
    assert "先导演这一拍，再校准具体载体" in planned


def test_planned_prompt_repeats_action_affordance_without_suppressing_performance():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert planned.count("不要用 greeting 冒充操作物件") >= 2
    assert planned.count("只排除身体语义错误的动作") >= 2
    assert planned.count("不能因此减少正文有依据的") >= 2
    assert planned.count("不能把整段退回 face-only") >= 2


def test_planned_prompt_preserves_distinct_carriers_on_one_anchor():
    planned = prompt.build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "特别注意同一 anchor 上的多个载体" in planned
    assert "不要因为 carriers 默认可替代就自动只保留最省事的一层" in planned
    assert "不是每句叠加指令的数量要求" in planned
    assert "“软”只允许换成更合适的实现" in planned
    assert "不要用 face-only 默认吞掉它" in planned


def test_planned_prompt_does_not_force_a_dialogue_face_default():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "A speaking line normally deserves an intentional face choice" not in planned
    assert "An ordinary information exchange may simply hold" in planned
    assert "face-only are not\nneutral safe defaults" in planned


def test_planned_resource_list_explains_action_affordances():
    index = {
        "enums": {
            "emoticon": {},
            "action": {
                "1": {"verb": "greeting", "cn": "向下确认"},
                "4": {"verb": "stiff", "cn": "小颤抖"},
                "7": {"verb": "hophop", "cn": "蹦跳"},
            },
        },
        "sounds": [],
        "bg": {},
    }

    resources = prompt.build_resources(
        index, {}, [], {}, dynamic_face_shortlists=True,
    )

    assert "greeting=向下确认（短促向下点动" in resources
    assert "不是通用说话手势" in resources
    assert "stiff=小颤抖（小幅僵动或颤抖" in resources
    assert "hophop=蹦跳（连续多次跳动" in resources
    assert "比 jump 多跳一下或形成连跳" in resources


def test_planned_prompt_keeps_pending_answer_axis_available():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "question is still awaiting its answer" in planned
    assert "affected person available as the causal anchor" in planned
    assert "RELATION CONTINUITY" in planned


def test_compact_planner_reserves_require_all_for_combined_facts():
    assert "只有新出现的身体信息才把 action 列为载体" in PLANNER_SYSTEM_COMPACT
    assert "组合事实，例如可见操作与独立可听反馈共同构成结果" in PLANNER_SYSTEM_COMPACT
    assert "`require_all=true` 只表达正文已证明的" in PLANNER_SYSTEM_COMPACT


def test_prompts_calibrate_performance_intensity_without_quotas():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "一个准确的轻量 act 或 emo 往往比换一张更重的脸更克制" in planned
    assert "每一层都要能分别指出正文依据" in planned
    assert "确认、汇报、验证成功”本身不能证明点头" in PLANNER_SYSTEM_COMPACT
    assert "只有必须看清细节、关系距离或个人爆发时才规划近景" in PLANNER_SYSTEM_COMPACT
    assert "每一层都要能分别指出正文依据" in PLANNER_SYSTEM_COMPACT


def test_prompts_use_same_character_face_cadence_and_rich_custom_variants():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "同一角色上一次真正可见的发言或表演" in planned
    assert "自定义表情库提供许多近义脸" in planned
    assert "intentional_face_hold" in planned
    assert "这是语义推进，不是按编号轮换" in planned
    assert "同一角色上一次真正可见的发言或表演" in PLANNER_SYSTEM_COMPACT
    assert "自定义表情库中的近义脸" in PLANNER_SYSTEM_COMPACT


def test_prompts_calibrate_emoticons_and_no_dialogue_expression_beats():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "emo 字段只填资源表中的精确中文名" in planned
    assert "`emo=惊疑`" in planned
    assert "`emo=疑问`" in planned
    assert "`emo=反应`" in planned
    assert "`emo=冒烟`" in planned
    assert "惊疑[?!]" not in planned
    assert "疑问[?]" not in planned
    assert "反应/respond" not in planned
    assert "冒烟/steam" not in planned
    assert "无对话表情" in planned
    assert "极端惊讶是低频强反应" in PLANNER_SYSTEM_COMPACT
    assert "respond/反应" in PLANNER_SYSTEM_COMPACT


def test_prompts_require_readable_group_to_solo_and_hidden_reveals():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "STAGING COMPLETION CHECK" in planned
    assert "多人镜头收成单人时" in planned
    assert "从设备后站起" in planned
    assert "close release" in planned
    assert "只删名单不算聚焦" in PLANNER_SYSTEM_COMPACT
    assert "从柜中探头" in PLANNER_SYSTEM_COMPACT


def test_planner_request_uses_optional_execution_fields():
    targets = [
        {"kind": "line", "line_no": 1, "who": "A", "text": "你好"},
        {"kind": "line", "line_no": 2, "who": "B", "text": "嗯"},
    ]
    user, schema, _ = build_scene_planner_request(
        targets, {"scene_id": "s", "target_indices": [0, 1]},
    )
    event = schema["properties"]["events"]["items"]
    required = set(event["required"])
    assert {"event_id", "start_i", "end_i", "kind", "stimulus", "outcome"} <= required
    assert not required.intersection({
        "shot_groups", "focus_turns", "performance_intents", "face_arcs",
        "silent_beats", "peaks", "continuity_goal", "result_owner",
        "aftershock_owner", "release_owner",
    })


def test_legacy_schema_helper_remains_structurally_compatible():
    schema = _event_schema(2, ["A", "B"])
    event = schema["properties"]["events"]["items"]
    assert "shot_groups" in event["properties"]
    assert event["properties"]["shot_groups"]["items"]["properties"]["members"]["maxItems"] == 3


def test_repair_prompt_is_scoped_to_the_reported_layer():
    performance = prompt.build_repair_rules(["face_change", "performance_intent_unfulfilled"])
    camera = prompt.build_repair_rules(["repeated_static_camera_pivot"])

    assert "REPAIR PERFORMANCE" in performance
    assert "REPAIR CAMERA" not in performance
    assert "REPAIR CAMERA" in camera
    assert "REPAIR PERFORMANCE" not in camera
    assert "连续演出语法范例" not in performance
    assert "连续演出语法范例" not in camera


def test_repair_prompt_keeps_backend_and_model_ownership_distinct():
    rules = prompt.build_repair_rules(["camera_cut", "face_change"], layout_mode="pure_ai")

    assert "模型决定意义、表演、镜头、关系、调度和节奏" in rules
    assert "后端只负责协议解析" in rules
    assert "硬切没有" in rules


def test_repair_prompt_makes_closeup_geometry_fields_explicit():
    rules = prompt.build_repair_rules(["closeup_with_multiple_characters"])

    assert "REPAIR CLOSEUP GEOMETRY" in rules
    assert "明确把不合适的 `fx=特写` 清除" in rules
    assert 'shot_operation="switch_group"' in rules
    assert 'shot_transition="cut"' in rules
    assert "visible_characters" in rules
    assert "positions" in rules
    assert "不要返回不完整的 `reframe`" in rules


def test_repair_prompt_explains_line_reveal_and_non_speaker_fallback():
    rules = prompt.build_repair_rules(
        ["reframe_adds_character_without_reveal"], layout_mode="pure_ai",
    )

    assert "REPAIR LINE REVEAL" in rules
    assert "不是角色名" in rules
    assert 'shot_transition="cut"' in rules
    assert "1/3/5" in rules


def test_planned_protocol_assigns_each_compact_field_to_one_location():
    planned = prompt.build_rules(
        "main", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "导演状态只能放在该行的 `d` 对象中" in planned
    assert "不要把同一个字段同时写在行顶层和 `d` 中" in planned
    assert "`authored` 归原作者" in planned
    assert "同一可见名单、同一站位只做尺度收近" in planned


def test_repair_protocol_repeats_compact_field_location_contract():
    rules = prompt.build_repair_rules(["performance_intent_unfulfilled"])

    assert "紧凑协议" in rules
    assert "导演状态只能放在该行的 `d` 对象中" in rules
    assert "不要把同一个字段同时写在行顶层和 `d` 中" in rules


def test_repair_resource_context_is_filtered_by_scope():
    resource_text = """RULES
========== 本章可用资源 ==========

### 角色与表情
faces

### 气泡 emo
emos

### 动作 act
acts

### 人物效果 fx
fx

### 音效 se
sounds

### 背景 bg
backgrounds
"""
    face = prompt.select_repair_resources(resource_text, ["face_change"])
    staging = prompt.select_repair_resources(resource_text, ["background_transition"])

    assert "faces" in face and "emos" in face and "acts" in face
    assert "sounds" not in face and "backgrounds" not in face
    assert "sounds" in staging and "backgrounds" in staging
    assert "emos" not in staging
