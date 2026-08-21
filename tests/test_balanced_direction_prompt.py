from annotate import SCHEMA, build_batch_context
import prompt
from director_state import (
    BEAT_REASONS,
    DIRECTION_REASONS,
    RELATION_DISTANCES,
    SCENE_FUNCTIONS,
)
from prompt import build_rules


def test_prompt_coordinates_direction_dimensions_and_explains_boundaries():
    rules = build_rules()

    for phrase in (
        "先判断这一句的情绪阶段、身体反应和镜头重点",
        "Dot / 沉默",
        "Exclaim / 惊叹",
        "Steam / 冒烟",
        "动作 act 是原地身体反应",
        "走位 move 是人物真实位置变化",
        "普通感叹号不能单独触发 jump",
    ):
        assert phrase in rules


def test_prompt_allows_semantic_comedy_reaction_chains_without_blanket_caps():
    rules = build_rules()

    assert "一段 10 行最多 2-3 个" not in rules
    assert "任意两句相邻对白绝不连续使用气泡" not in rules
    assert "喜剧连击" in rules
    assert "连续使用气泡" in rules
    assert "比 jump 多跳一下或形成连跳" in rules
    assert "结巴、掩饰、反讽" in rules
    assert "！？" in rules


def test_prompt_reserves_wait_for_schema_backed_dialogue_free_beats():
    rules = build_rules()

    assert "Schema 包含 beats" in rules
    assert "独立无对话框反应" in rules
    assert "普通对白" in rules
    assert "wait_ms" in rules


def test_prompt_uses_official_style_dialogue_actions_as_character_performance():
    rules = build_rules("bond")

    assert "不要求原文先写出“跳了一下”" in rules
    assert "强烈反驳" in rules
    assert "突然自信" in rules
    assert "身体真的僵住、发颤" in rules
    assert "台词本身就是身体反应的证据" in rules
    assert "physical_reaction" in rules


def test_batch_context_includes_recent_emoticon_and_action_choices():
    items = [
        {
            "kind": "line",
            "who": "凯伊",
            "text": "不行。",
            "face": "05",
            "emo": "冒烟",
            "act": "jump",
        }
    ]

    context = build_batch_context(items, [0])

    assert "face=05" in context
    assert "emo=冒烟" in context
    assert "act=jump" in context


def test_annotation_schema_uses_the_real_direction_contract():
    fields = SCHEMA["properties"]["lines"]["items"]["properties"]

    assert "瞬时心理反应" in fields["emo"]["description"]
    assert "原地身体反应" in fields["act"]["description"]
    assert "真实位置变化" in fields["move"]["description"]
    assert "通讯 / 黑屏剪影 / 特写" in fields["fx"]["description"]


def test_prompt_limits_long_term_memory_to_evidence_backed_events():
    rules = build_rules()
    assert "memory_events" in rules
    assert "原样摘录" in rules
    assert "不能把猜测升级为事实" in rules
    assert "普通表情变化" in rules


def test_prompt_contains_story_modes_scene_functions_and_continuity():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    text = prompt.build_system(idx, {}, [], {}, story_type="event")

    assert "main / event / bond" in text
    assert "喜剧升级" in text and "情绪转折" in text
    assert "listener" in text and "offscreen_space" in text
    assert "start / hold / escalate / end" in text
    assert "不要按固定次数、比例或每 N 行配额" in text
    assert "每次有立绘角色发言" in text
    assert "一次表情拍通常覆盖该角色 1～2 次发言" in text
    assert "同一 face 不重复输出" in text
    assert "authored=..." in text


def test_prompt_forbids_mechanical_face_rotation_and_dialogue_rewrite():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    text = prompt.build_system(idx, {}, [], {}, story_type="bond")

    assert "不要为了画面变化而换 face" in text
    assert "一个字都不改" in text
    assert "优先选择一个与上一句不同" not in text


def test_prompt_requires_comparing_the_latest_dialogue_or_silent_performance_node():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    text = prompt.build_system(idx, {}, [], {}, story_type="event")

    assert "逐节点演出状态比较" in text
    assert "对白或无对白 beat" in text
    assert "CURRENT_DIRECTION_STATE.last_performance_node" in text
    assert "至少选择一个语义匹配的可见承载" in text
    assert "没有“每句换脸”" in text


def test_each_story_mode_receives_a_distinct_directing_priority():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    main = prompt.build_system(idx, {}, [], {}, story_type="main")
    event = prompt.build_system(idx, {}, [], {}, story_type="event")
    bond = prompt.build_system(idx, {}, [], {}, story_type="bond")

    assert "画外动作" in main
    assert "群体同步" in event
    assert "关系距离" in bond
    assert len({main, event, bond}) == 3


def test_prompt_uses_preflight_scene_type_as_a_first_stage_mode_selection():
    rules = build_rules("auto")

    assert "两阶段演出模式选择" in rules
    assert "DIRECTOR_CONTEXT.scene_type" in rules
    assert "ACTIVE_MODE_POLICY" in rules
    assert "多人同步必须有共同刺激" not in rules
    assert "保持镜头比频繁切换更重要" not in rules

    assert "多人同步必须有共同刺激" in prompt.scene_mode_policy("event")
    assert "保持镜头比频繁切换更重要" in prompt.scene_mode_policy("bond")
    assert "中性电影语法" in prompt.scene_mode_policy("other")


def test_prompt_can_offer_two_preflight_approved_modes_without_unrelated_rules():
    policy = prompt.scene_mode_policy("event", ["event", "bond"])

    assert "ACTIVE_MODE_POLICIES=event,bond" in policy
    assert "本场按活动策略" in policy
    assert "本场按羁绊策略" in policy
    assert "本场按主线策略" not in policy


def test_prompt_defines_scene_sequences_emotion_chains_and_reason_contract():
    rules = build_rules("bond")

    for scene_function in (
        "建立场景", "日常对话", "喜剧升级", "情绪转折", "信息揭示",
        "做出决定", "动作事件", "转场", "余波",
    ):
        assert scene_function in rules
    assert rules.count("触发：") >= 9
    assert rules.count("序列：") >= 9
    assert rules.count("禁用：") >= 9
    assert rules.count("退出：") >= 9
    assert "平静 → 注意 → 疑惑 → 确认 → 释然" in rules
    assert "direction.reason" in rules
    assert "短枚举值" in rules


def test_prompt_director_values_match_the_validated_protocol_enums():
    rules = build_rules("main")

    assert "scene_function 只使用：" + " / ".join(SCENE_FUNCTIONS) in rules
    assert "relation_distance 只使用：" + " / ".join(RELATION_DISTANCES) in rules
    assert "direction.reason 只使用：" + " / ".join(DIRECTION_REASONS) in rules
    assert "beat.reason 只使用：" + " / ".join(BEAT_REASONS) in rules
    assert "confrontational" not in rules


def test_rules_require_speaker_activation_without_mechanical_face_churn():
    rules = build_rules()

    assert "从听者重新变成说话者" in rules
    assert "优先选择一个与当前持有表情不同" in rules
    assert "同一句拆开的连续气口" in rules
    assert "相邻的同一角色连续发言" in rules


def test_prompt_preserves_faces_in_silent_beats_and_reserves_late_peak():
    rules = build_rules()

    assert "无对白 beat 不是“重新生成一张默认立绘”" in rules
    assert "不要用 face=00 作为占位符" in rules
    assert "`BG_Black` 只用于正文明确要求黑场" in rules
    assert "后一句的峰值" in rules
    assert "单人居中构图" in rules
    assert "carriers 默认是可替代实现集合" in rules
    assert "require_all=true" in rules
    assert "不能以删除其他已规划的入场" in rules


def test_prompt_blocks_stationary_layer_swaps_and_quiet_focusline():
    rules = build_rules(layout_mode="pure_ai")

    assert "[A,B] → [A,C]" in rules
    assert "A 可以在新镜头继续同一侧" in rules
    assert "不需要为切镜补一段物理退场" in rules
    assert "不要把它误写成 hold、reframe 或 move" in rules
    assert "FocusLine 只属于单人居中的明确爆发" in rules


def test_stable_layout_mode_omits_relationship_distance_decisions():
    text = prompt.build_system(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {}, [], {}, layout_mode="rules",
    )

    assert "稳定规则模式" in text
    assert "省略 relation_distance" in text


def test_pure_ai_prompt_owns_entry_exit_positions_and_multi_stage_beats():
    rules = build_rules(layout_mode="pure_ai")

    assert "当前使用纯 AI 演出模式" in rules
    assert "镜头名单、具体槽位、立绘显现、人物入场、退场、镜内位移" in rules
    assert "一个 anchor 可以有多个连续 beat" in rules
    assert "不要设置固定事件数量" in rules
    assert "编译器只为场景内第一次出现提供默认渐入" in rules
    assert "不会因为离镜时间长就擅自再次渐入" in rules
    assert "画外线索→显现/进入→停住→换脸/气泡→移动→他人反应→重构图" in rules


def test_staging_fewshot_is_kept_when_dynamic_face_shortlists_are_enabled():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
    )

    assert "对照式导演示范" in rules
    assert "语义表情示范" in rules
    assert "编号表情示范" not in rules
    assert "不组成可复用的事件链" in rules
    assert "不必自动插入 feedback / verification 静默拍" in rules
    assert "没有犹豫证据时直接完成问答" in rules
    assert "连续强句不固定把峰值放在后句" in rules


def test_numbered_face_mode_also_receives_the_shared_staging_fewshot():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=False,
    )

    assert "对照式导演示范" in rules
    assert "编号表情示范" in rules
    assert "语义表情示范" not in rules


def test_prompt_covers_supported_events_without_completing_missing_chains():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
    )

    assert "哪些察觉、反应、结果或余波真正存在" in rules
    assert "不能补齐正文没有的事件链" in rules
    assert "不设置固定数量或字符预算" in rules
    assert "不能为了避免误用而把整场重效果机械归零" in rules
    assert "不是官方节点答案" in rules


def test_planned_execution_prompt_keeps_safety_boundaries_without_repeating_planner_course():
    full = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
    )
    execution = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    for phrase in (
        "已规划场景的执行合同", "SCENE_EVENT_PLAN", "单镜最多三人",
        "硬切是正常镜头语法", "对白可以采用说话者单人、听者单人反应或关系构图",
        "Wait 只属于没有对话框", "不得用 face=00 占位",
        "不设固定数量、冷却、相邻禁用或字符预算",
    ):
        assert phrase in execution
    assert "九种场景功能" not in execution
    assert "对照式导演示范" not in execution
    assert len(execution) < len(full)


def test_planned_execution_prompt_discourages_rotating_one_side_of_a_pair():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "所有人轮流对他说话" in rules
    assert "优先连续的单人正反打，或切到真正的新关系组" in rules


def test_prompt_distinguishes_reveal_entry_exit_and_background_transition():
    rules = build_rules(layout_mode="pure_ai")

    assert "镜头显现" in rules
    assert "立绘显现 reveal" in rules
    assert "立绘离镜 conceal" in rules
    assert "普通情况用 fade" in rules
    assert "第一次与" in rules and "建立联系" in rules
    assert "原本就在房间里的人" in rules and "不属于真实入场" in rules
    assert "说“我要走了”只是意图" in rules
    assert "实际迈步的拍点输出 exit" in rules
    assert "普通反打" in rules and "不要填 trans" in rules
    assert "物件操作" in rules and "蒙太奇与余波" in rules
    assert "reveal/conceal" in rules and "cut 互斥" in rules


def test_planned_execution_prompt_keeps_reveal_and_cut_mutually_exclusive():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )

    assert "reveal/conceal" in rules and "cut 互斥" in rules
    assert "连续镜头显隐用 reveal/conceal，完整新构图只用 cut" in rules


def test_prompt_does_not_throttle_semantic_shakes_but_keeps_object_operation_guard():
    rules = build_rules(layout_mode="pure_ai")

    assert "不设固定次数、冷却或相邻禁用规则" in rules
    assert "即使上一拍已经有动作或气泡" in rules
    assert "不要用 stiff/shake 冒充操作" in rules


def test_prompt_teaches_layered_emotion_combinations_without_fixed_recipes():
    rules = build_rules(layout_mode="pure_ai", dynamic_face_shortlists=True)

    for phrase in (
        "压住火气",
        "短促爆发/强烈反驳",
        "更重、更强烈的兴奋或怒气",
        "明显失控、恐惧、痛苦或挣扎",
        "害羞/被戳穿",
        "SHY",
        "fire",
        "上文刺激 -> 承受者 -> 阶段变化 -> 可读 carrier",
    ):
        assert phrase in rules
    assert "固定配方" in rules


def test_planned_execution_prompt_keeps_layered_emotion_and_space_examples():
    rules = build_rules(
        "event", layout_mode="pure_ai", dynamic_face_shortlists=True,
        planned_execution=True,
    )
    for phrase in (
        "愤怒 face + `emo=怒筋`",
        "`move/reframe` 更新旧角色的物理槽位",
        "只有地点、时间、黑场",
        "或叙事层真正改变",
        "特写泄漏到后续镜头",
    ):
        assert phrase in rules


def test_prompt_treats_stable_groups_as_defaults_and_avoids_short_reverse_shot_ping_pong():
    rules = build_rules()

    assert "不是逐句反打命令" in rules
    assert "不是把下一位说话者自动塞进画面" in rules
    assert "不会因为“连续性”\n自动合并成三人" in rules
    assert "立绘宽度与防\n重叠校验" in rules
    assert "允许用新的单人/双人组完整硬切" in rules


def test_prompt_separates_hit_target_shot_from_camera_framing():
    rules = build_rules(layout_mode="pure_ai")

    assert "只表示受击目标，不表示景别" in rules
    assert "不要把 `medium_close`、`close`、`relation`、`wide`、`group`" in rules
    assert "景别只在 G1 计划的 `shot_group.framing` 中表达" in rules


def test_prompt_allows_a_report_to_land_on_a_solo_shot_without_forcing_it():
    rules = build_rules(layout_mode="pure_ai")

    assert "独立的信息落点" in rules
    assert "汇报者单人" in rules
    assert "这不是固定模板" in rules
    assert "不能额外添加 Wait" in rules


def test_prompt_explains_physical_space_shot_group_and_interaction_axis():
    rules = build_rules(layout_mode="pure_ai")

    assert "scene_presence：人物是否仍在这个物理场景" in rules
    assert "shot_group：摄影机当前拍摄的完整人物组与构图" in rules
    assert "interaction_axis：当前事件中谁向谁行动、谁承受刺激" in rules
    assert "anchor_i / hold_until_i" in rules
    assert "区间内部不要因 speaker 改变而输出 cut" in rules
    assert "硬切后的静态落位" in rules
    assert "已有角色先让出位置，另一人再加入" in rules


def test_prompt_treats_hold_until_as_a_revisable_plan_hypothesis():
    rules = build_rules(layout_mode="pure_ai")

    assert "首选连续镜头范围" in rules
    assert "不是第二阶段不可推翻的硬边界" in rules
    assert "对计划的显式偏离" in rules


def test_prompt_keeps_observer_out_of_stable_relationship_group():
    rules = build_rules(layout_mode="pure_ai")
    assert "观察者是独立的镜头角色" in rules
    assert "不自动触发" in rules


def test_prompt_hard_caps_every_shot_at_three_visible_portraits():
    for mode in ("rules", "ai", "pure_ai"):
        rules = build_rules(layout_mode=mode)

        assert "任何单个镜头最多只允许三名可见角色" in rules
        assert "三人是硬上限而不是默认人数" in rules
        assert "绝对不要输出四人或更多人的 visible_characters / positions" in rules
        assert "beat 中临时塞入第四人" in rules
