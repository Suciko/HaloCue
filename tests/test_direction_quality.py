from direction_quality import (
    classify_quality_issue,
    is_automatic_repairable_quality_issue,
    sanitize_execution_beats,
    validate_annotated_source,
    validate_director_plan,
    validate_compiled_staging,
    validate_execution_quality,
    validate_plan_quality,
)


def test_quality_issue_resolution_keeps_semantic_choices_with_ai():
    assert classify_quality_issue({
        "code": "compiler_annotation_auto_repaired",
        "severity": "info",
    })["resolution"] == "deterministic"
    assert classify_quality_issue({
        "code": "stationary_layer_swap",
        "severity": "high",
    })["resolution"] == "ai_repair"
    assert classify_quality_issue({
        "code": "compiled_visible_over_three",
        "severity": "critical",
    })["resolution"] == "block"
    assert classify_quality_issue({
        "code": "missing_planned_silent_phase",
        "severity": "high",
    })["resolution"] == "advisory"
    assert classify_quality_issue({
        "code": "performance_layer_collapsed",
        "severity": "high",
    })["resolution"] == "advisory"
    assert classify_quality_issue({
        "code": "unresolved_background_request",
        "severity": "warning",
    })["resolution"] == "resource_required"


def test_offscreen_relationship_peak_accepts_the_visible_participant_only():
    cast = {
        "凯伊": {"portrait": True},
        "老师": {"portrait": False},
    }
    plan = {"events": [{
        "event_id": "e1",
        "source_ids": ["L1"],
        "phase_order": [],
        "shot_groups": [{
            "group_id": "g1", "anchor_id": "L1", "hold_until_id": "L1",
            "members": ["凯伊"], "_offscreen_members": ["老师"],
            "focus": "凯伊", "framing": "relation", "operation": "hold",
            "cut_motivation": "", "purpose": "凯伊回应画外老师",
        }],
        "performance_intents": [], "face_arcs": [], "silent_beats": [],
        "peaks": [{
            "peak_id": "L1", "subject": "凯伊", "peak_type": "relationship_peak",
            "position": "on", "release_position": "scene_end", "release_id": "",
        }],
    }]}
    targets = [{"annotation_id": "L1", "who": "老师", "text": "下次再来。"}]

    plan_report = validate_plan_quality(plan, targets=targets, cast=cast)
    execution_report = validate_execution_quality(
        plan, targets,
        {"L1": {
            "direction": {"visible_characters": ["凯伊"], "positions": {"凯伊": 3}},
            "direction_intent": {"visible_characters": ["凯伊"], "positions": {"凯伊": 3}},
        }},
        [], cast=cast,
    )

    assert "relationship_peak_bad_group" not in {
        issue["code"] for issue in plan_report["issues"]
    }
    assert "peak_composition_mismatch" not in {
        issue["code"] for issue in execution_report["issues"]
    }


def test_quality_issue_reclassifies_stale_known_resolution_from_old_audit():
    assert classify_quality_issue({
        "code": "missing_planned_silent_phase",
        "severity": "high",
        "resolution": "ai_repair",
        "needs_review": True,
    }) == {
        "code": "missing_planned_silent_phase",
        "severity": "high",
        "resolution": "advisory",
        "needs_review": False,
    }


def test_quality_issue_respects_explicit_deterministic_supersession():
    issue = classify_quality_issue({
        "code": "closeup_requires_hard_cut",
        "severity": "high",
        "resolution": "deterministic",
        "needs_review": True,
        "evidence_status": "superseded_by_rendered_trace",
    })

    assert issue["resolution"] == "deterministic"
    assert issue["needs_review"] is False


def test_plan_hypothesis_findings_do_not_force_automatic_g2_repair():
    for code in (
        "opening_arrival_event_missing",
        "enter_without_arrival_evidence",
        "missing_planned_silent_phase",
        "planned_shot_span_unfulfilled",
        "release_owner_not_visible",
        "performance_intent_unfulfilled",
        "solo_emphasis_closeup_unfulfilled",
    ):
        assert is_automatic_repairable_quality_issue({
            "code": code, "severity": "high",
        }) is False

    assert is_automatic_repairable_quality_issue({
        "code": "stationary_layer_swap", "severity": "high",
    }) is True
    assert is_automatic_repairable_quality_issue({
        "code": "performance_layer_collapsed", "severity": "high",
    }) is False


def _chain(**overrides):
    value = {
        "shot_steps": [],
        "silent_beats": [],
        "impact_lines": [],
        "performance_beats": [],
    }
    value.update(overrides)
    return value


def test_plan_rejects_redundant_shots_stationary_swap_and_group_impact():
    plan = {
        "event_chains": [_chain(
            shot_steps=[
                {
                    "anchor_line": 1,
                    "operation": "continue_group",
                    "visible_characters": ["A", "B"],
                    "focus": "A",
                    "framing": "medium",
                    "continuity": "hold",
                },
                {
                    "anchor_line": 2,
                    "operation": "continue_group",
                    "visible_characters": ["A", "B"],
                    "focus": "A",
                    "framing": "medium",
                    "continuity": "hold",
                },
                {
                    "anchor_line": 3,
                    "operation": "impact_insert",
                    "visible_characters": ["A", "C"],
                    "focus": "C",
                    "framing": "close",
                    "continuity": "hard_cut",
                },
            ],
            impact_lines=[{
                "line": 3,
                "subject": "C",
                "emphasis": "closeup+action",
                "release_at_line": 4,
            }],
        )],
    }

    report = validate_director_plan(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["result"] == "fail"
    assert "redundant_shot_step" in codes
    assert "stationary_pair_swap" in codes
    assert "impact_not_solo_close" in codes
    assert "impact_performance_missing" in codes


def test_plan_accepts_solo_peak_with_matching_performance_intent():
    plan = {
        "event_chains": [_chain(
            shot_steps=[{
                "anchor_line": 2,
                "operation": "impact_insert",
                "visible_characters": ["A"],
                "focus": "A",
                "framing": "close",
                "continuity": "hard_cut",
            }],
            impact_lines=[{
                "line": 2,
                "subject": "A",
                "emphasis": "closeup+action",
                "release_at_line": 3,
            }],
            performance_beats=[{
                "anchor_line": 2,
                "action_intent": "emphatic_body_response",
                "emoticon_intent": "surprise",
                "strength": "high",
            }],
        )],
    }

    assert validate_director_plan(plan)["result"] == "pass"


def _v2_event(**overrides):
    value = {
        "event_id": "event-1", "source_ids": ["L1", "L2", "L3"],
        "kind": "dialogue_cluster", "phase_order": [], "stimulus_targets": [],
        "result_owner": "", "aftershock_owner": "", "release_owner": "",
        "shot_groups": [], "performance_intents": [], "face_arcs": [],
        "silent_beats": [], "peaks": [],
    }
    value.update(overrides)
    return value


def test_plan_v2_rejects_owner_that_disagrees_with_declared_phase_and_beat():
    plan = {"events": [_v2_event(
        phase_order=["result", "aftershock"],
        result_owner="A",
        aftershock_owner="B",
        silent_beats=[{
            "anchor_id": "L2", "position": "after", "phase": "aftershock",
            "participants": ["A"], "purpose": "结果余波",
            "sound_motivated": False,
            "carrier_requirement": {
                "any_of": ["face_change"], "require_observable_change": True,
            },
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert "event_owner_participant_mismatch" in codes


def test_plan_v2_does_not_invent_owner_when_ai_leaves_owner_empty():
    plan = {"events": [_v2_event(
        phase_order=["result", "aftershock"],
        silent_beats=[{
            "anchor_id": "L2", "position": "after", "phase": "aftershock",
            "participants": ["A"], "purpose": "结果余波",
            "sound_motivated": False,
            "carrier_requirement": {
                "any_of": ["face_change"], "require_observable_change": True,
            },
        }],
    )]}

    codes = {issue["code"] for issue in validate_plan_quality(plan)["issues"]}

    assert "event_owner_participant_mismatch" not in codes
    assert "event_owner_phase_missing" not in codes


def test_plan_v2_rejects_unmotivated_pair_swap_and_grouped_solo_peak():
    plan = {"events": [_v2_event(
        shot_groups=[
            {
                "group_id": "g1", "anchor_id": "L1", "members": ["A", "B"],
                "focus": "A", "framing": "medium", "operation": "establish",
                "cut_motivation": "", "purpose": "establish",
            },
            {
                "group_id": "g2", "anchor_id": "L2", "members": ["A", "C"],
                "focus": "C", "framing": "close", "operation": "switch",
                "cut_motivation": "", "purpose": "impact",
            },
        ],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["C"],
            "carriers": ["camera_change"], "purpose": "impact",
        }],
        peaks=[{
            "subject": "C", "peak_type": "solo_emphasis", "peak_id": "L2",
            "position": "on", "visual_intent": "个人爆点", "release_id": "L3",
            "release_position": "on", "why": "完成升级",
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["result"] == "fail"
    assert "plan_stationary_pair_swap" in codes
    assert "solo_emphasis_not_solo" in codes


def test_plan_v2_accepts_relationship_peak_and_motivated_anchor_match_cut():
    plan = {"events": [_v2_event(
        shot_groups=[
            {
                "group_id": "g1", "anchor_id": "L1", "members": ["A", "B"],
                "focus": "A", "framing": "relation", "operation": "establish",
                "cut_motivation": "", "purpose": "建立原关系",
            },
            {
                "group_id": "g2", "anchor_id": "L2", "members": ["A", "C"],
                "focus": "C", "framing": "relation", "operation": "anchor_match_cut",
                "cut_motivation": "保持 A 为视觉锚点，切换到真正回应者 C",
                "purpose": "关系焦点交接",
            },
        ],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A", "C"],
            "carriers": ["face_change", "camera_change"], "purpose": "关系变化",
        }],
        peaks=[{
            "subject": "C", "peak_type": "relationship_peak", "peak_id": "L2",
            "position": "on", "visual_intent": "两人关系焦点变化",
            "release_id": "", "release_position": "scene_end", "why": "关系承接",
        }],
    )]}

    assert validate_plan_quality(plan)["result"] == "pass"


def test_plan_v2_relationship_peak_can_land_inside_held_shot_range():
    plan = {"events": [_v2_event(
        shot_groups=[
            {
                "group_id": "g1", "anchor_id": "L1", "hold_until_id": "L1",
                "members": ["A", "B"], "focus": "A", "framing": "relation",
                "operation": "establish", "cut_motivation": "", "purpose": "建立关系",
            },
            {
                "group_id": "g2", "anchor_id": "L2", "hold_until_id": "L3",
                "members": ["A", "B"], "focus": "A", "framing": "relation",
                "operation": "continue", "cut_motivation": "", "purpose": "保持邀请关系",
            },
        ],
        peaks=[{
            "subject": "A", "peak_type": "relationship_peak", "peak_id": "L3",
            "position": "on", "visual_intent": "邀请关系落点",
            "release_id": "", "release_position": "scene_end", "why": "关系成立",
        }],
    )]}

    report = validate_plan_quality(plan)

    assert "relationship_peak_bad_group" not in {
        issue["code"] for issue in report["issues"]
    }


def test_plan_v2_accepts_motivated_switch_as_a_complete_hard_cut():
    plan = {"events": [_v2_event(
        shot_groups=[
            {
                "group_id": "g1", "anchor_id": "L1", "members": ["A", "B"],
                "focus": "A", "framing": "relation", "operation": "establish",
                "cut_motivation": "", "purpose": "原关系",
            },
            {
                "group_id": "g2", "anchor_id": "L2", "members": ["A", "C"],
                "focus": "C", "framing": "relation", "operation": "switch",
                "cut_motivation": "切到新的回应关系", "purpose": "新关系",
            },
        ],
    )]}

    assert "plan_stationary_pair_swap" not in {
        issue["code"] for issue in validate_plan_quality(plan)["issues"]
    }


def test_dialogue_verification_can_be_carried_by_dialogue_without_silent_beat():
    plan = {"events": [_v2_event(
        kind="dialogue_cluster",
        phase_order=["action", "verification", "result"],
    )]}

    assert "event_required_silent_phase_missing" not in {
        issue["code"] for issue in validate_plan_quality(plan)["issues"]
    }


def test_plan_v2_requires_hard_cut_when_multi_shot_becomes_solo_closeup():
    plan = {"events": [_v2_event(shot_groups=[
        {
            "group_id": "pair", "anchor_id": "L1", "members": ["A", "B"],
            "focus": "B", "framing": "relation", "operation": "establish",
            "cut_motivation": "", "purpose": "问答",
        },
        {
            "group_id": "solo", "anchor_id": "L2", "members": ["A"],
            "focus": "A", "framing": "close", "operation": "shrink",
            "cut_motivation": "个人强调", "purpose": "单人近景",
        },
    ])]}

    report = validate_plan_quality(plan)

    assert "closeup_requires_hard_cut" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "fail"


def test_plan_v2_accepts_hard_cut_from_multi_shot_to_solo_closeup():
    plan = {"events": [_v2_event(shot_groups=[
        {
            "group_id": "pair", "anchor_id": "L1", "members": ["A", "B"],
            "focus": "B", "framing": "relation", "operation": "establish",
            "cut_motivation": "", "purpose": "问答",
        },
        {
            "group_id": "solo", "anchor_id": "L2", "members": ["A"],
            "focus": "A", "framing": "close", "operation": "switch",
            "cut_motivation": "切到个人强调", "purpose": "单人近景",
        },
    ])]}

    assert "closeup_requires_hard_cut" not in {
        issue["code"] for issue in validate_plan_quality(plan)["issues"]
    }


def test_plan_v2_requires_structured_silent_carrier_without_setting_a_count_quota():
    invalid = {"events": [_v2_event(silent_beats=[{
        "anchor_id": "L2", "position": "after", "phase": "group_reaction",
        "participants": ["A", "B"], "purpose": "共同反应",
        "carrier_requirement": {"any_of": [], "require_observable_change": True},
    }])]}
    empty_scene = {"events": [_v2_event()]}

    assert "silent_phase_no_carrier" in {
        issue["code"] for issue in validate_plan_quality(invalid)["issues"]
    }
    assert validate_plan_quality(empty_scene)["result"] == "pass"


def test_plan_v2_warns_on_template_phase_order_and_wrong_reaction_label():
    plan = {"events": [_v2_event(
        kind="object_test",
        phase_order=["result", "object_action", "group_reaction"],
        stimulus_targets=["A", "B"],
        silent_beats=[{
            "anchor_id": "L1", "position": "after", "phase": "group_reaction",
            "participants": ["A", "C"], "purpose": "共同看见反馈",
            "carrier_requirement": {
                "any_of": ["face_change"], "require_observable_change": True,
            },
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert "event_phase_dependency_reversed" in codes
    assert "group_reaction_stimulus_mismatch" in codes
    assert "event_required_silent_phase_missing" not in codes
    mismatch = next(
        issue for issue in report["issues"]
        if issue["code"] == "group_reaction_stimulus_mismatch"
    )
    assert mismatch["severity"] == "warning"
    assert mismatch["resolution"] == "advisory"
    assert report["result"] == "pass"


def test_plan_v2_advises_declared_object_feedback_and_verification_silent_beats():
    plan = {"events": [_v2_event(
        kind="object_test",
        phase_order=["object_action", "feedback", "verification", "result"],
        stimulus_targets=["A"],
        silent_beats=[{
            "anchor_id": "L1", "position": "before", "phase": "object_action",
            "participants": ["A"], "purpose": "启动",
            "carrier_requirement": {
                "any_of": ["action", "sound"], "require_observable_change": True,
            },
        }],
    )]}

    report = validate_plan_quality(plan)
    missing = next(
        issue for issue in report["issues"]
        if issue["code"] == "event_required_silent_phase_missing"
    )

    assert missing["missing"] == ["feedback", "verification"]
    assert missing["severity"] == "warning"
    assert report["result"] == "pass"


def test_plan_v2_requires_real_entry_carrier_for_arrival_event():
    plan = {"events": [_v2_event(
        kind="arrival", phase_order=["reveal"], stimulus_targets=["A"],
        silent_beats=[{
            "anchor_id": "L1", "position": "before", "phase": "reveal",
            "participants": ["A"], "purpose": "访客到场",
            "carrier_requirement": {
                "any_of": ["camera_change"], "require_observable_change": True,
            },
        }],
    )]}

    assert "arrival_without_entry_carrier" in {
        issue["code"] for issue in validate_plan_quality(plan)["issues"]
    }


def test_plan_v2_does_not_infer_true_entry_from_polite_opening_greeting():
    plan = {"events": [_v2_event(
        kind="dialogue_cluster", source_ids=["L1"],
    )]}

    report = validate_plan_quality(plan, targets=[{
        "annotation_id": "L1", "who": "访客",
        "text": "打扰了，我来归还资料。",
    }])

    assert "opening_arrival_event_missing" not in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "pass"


def test_plan_v2_reports_explicit_opening_arrival_as_advisory():
    plan = {"events": [_v2_event(
        kind="dialogue_cluster", source_ids=["L1"],
    )]}

    report = validate_plan_quality(plan, targets=[{
        "annotation_id": "L1", "who": "访客",
        "text": "我刚推门走进来，资料放这里。",
    }])
    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "opening_arrival_event_missing"
    )

    assert issue["severity"] == "warning"
    assert issue["resolution"] == "advisory"
    assert report["result"] == "pass"


def test_plan_v2_allows_non_speaker_reaction_on_dialogue_line():
    targets = [{"annotation_id": "L1", "who": "A", "text": "继续说。"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["B"],
            "carriers": ["face_change"], "purpose": "听者反应",
        }],
        face_arcs=[{
            "who": "B", "stages": [{
                "anchor_id": "L1", "position": "on",
                "semantic_state": "惊讶", "change_reason": "听到消息",
            }],
        }],
    )]}

    report = validate_plan_quality(plan, targets=targets)
    codes = {issue["code"] for issue in report["issues"]}

    assert "on_line_non_speaker_performance" not in codes
    assert "on_line_non_speaker_face_stage" not in codes
    assert report["result"] == "pass"


def test_plan_v2_rejects_repeating_the_same_shot_group_declaration():
    group = {
        "group_id": "pair", "members": ["A", "B"], "focus": "A",
        "framing": "relation", "cut_motivation": "", "purpose": "同一问答",
    }
    plan = {"events": [_v2_event(shot_groups=[
        {**group, "anchor_id": "L1", "operation": "establish"},
        {**group, "anchor_id": "L2", "operation": "hold"},
    ])]}

    report = validate_plan_quality(plan)

    assert "shot_step_redundant" in {issue["code"] for issue in report["issues"]}
    assert report["result"] == "fail"


def test_plan_v2_rejects_overlapping_shot_hold_ranges():
    plan = {"events": [_v2_event(shot_groups=[
        {
            "group_id": "pair", "anchor_id": "L1", "hold_until_id": "L2",
            "members": ["A", "B"], "focus": "A", "framing": "relation",
            "operation": "establish", "cut_motivation": "", "purpose": "问答",
        },
        {
            "group_id": "solo", "anchor_id": "L2", "hold_until_id": "L3",
            "members": ["C"], "focus": "C", "framing": "close",
            "operation": "switch", "cut_motivation": "新刺激", "purpose": "揭晓",
        },
    ])]}

    report = validate_plan_quality(plan)

    assert "overlapping_shot_hold_ranges" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "fail"


def test_plan_v2_advises_silent_group_reaction_for_shared_discovery():
    plan = {"events": [_v2_event(
        kind="discovery", stimulus_targets=["A", "B"],
        phase_order=["group_reaction", "focus_handoff"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A", "B"],
            "carriers": ["face_change"], "purpose": "共同发现",
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert "event_required_silent_phase_missing" in codes
    assert report["result"] == "pass"


def test_plan_v2_does_not_force_group_reaction_or_aftershock_for_shared_aftermath():
    plan = {"events": [_v2_event(
        kind="aftermath", stimulus_targets=["A", "B", "C"],
        phase_order=["focus_handoff"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["C"],
            "carriers": ["face_change"], "purpose": "由 C 收束",
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert "shared_stimulus_without_group_reaction" not in codes
    assert "shared_aftermath_without_aftershock" not in codes
    assert report["result"] == "pass"


def test_plan_v2_does_not_force_aftermath_pattern_onto_ordinary_group_dialogue():
    plan = {"events": [_v2_event(
        kind="dialogue_cluster", stimulus_targets=["A", "B", "C"],
        phase_order=["relay"],
    )]}

    assert validate_plan_quality(plan)["result"] == "pass"


def test_plan_v2_does_not_infer_decision_pause_from_invitation_label():
    plan = {"events": [_v2_event(
        kind="invitation", phase_order=["result"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A"],
            "carriers": ["face_change"], "purpose": "邀请",
        }],
    )]}

    report = validate_plan_quality(plan)
    codes = {issue["code"] for issue in report["issues"]}

    assert "event_required_phase_missing" not in codes
    assert "event_required_silent_phase_missing" not in codes
    assert report["result"] == "pass"


def test_plan_v2_requires_performance_for_reaction_driven_event():
    plan = {"events": [_v2_event(kind="discovery")]}

    report = validate_plan_quality(plan)

    assert "reaction_event_without_performance_intent" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "fail"


def test_plan_v2_requires_readable_performance_intent_for_semantic_stage_change():
    plan = {"events": [_v2_event(face_arcs=[{
        "who": "A",
        "stages": [
            {
                "anchor_id": "L1", "position": "on",
                "semantic_state": "平静观察", "change_reason": "建立初态",
            },
            {
                "anchor_id": "L2", "position": "on",
                "semantic_state": "突然理解", "change_reason": "发现线索",
            },
        ],
    }])]}

    report = validate_plan_quality(plan)

    assert "face_stage_change_without_intent" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "fail"

    plan["events"][0]["performance_intents"] = [{
        "anchor_id": "L2", "position": "on", "subjects": ["A"],
        "carriers": ["face_change"], "purpose": "用真实换脸承载理解变化",
    }]

    assert "face_stage_change_without_intent" not in {
        issue["code"] for issue in validate_plan_quality(plan)["issues"]
    }


def test_source_rejects_group_closeup_and_stationary_layer_swap_without_guessing_face_semantics():
    source = """\
@camera_cut A,B
A: first
@camera_hold A,C
@fx C 特写
C: impact
@nodialog
 C(00):
"""

    report = validate_annotated_source(source)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["result"] == "fail"
    assert "stationary_layer_swap" in codes
    assert "closeup_with_multiple_characters" in codes
    assert "default_face_placeholder" not in codes


def test_source_defers_full_cut_spatial_judgment_to_compiled_staging():
    report = validate_annotated_source("""\
@camera_cut A,B
A: first
@camera_cut A,C
C: second
""")

    assert "stationary_layer_swap" not in {
        issue["code"] for issue in report["issues"]
    }


def test_source_accepts_valid_zero_face_id_without_guessing_its_semantics():
    report = validate_annotated_source("A(01): first\nA(00): second\n")

    assert "explicit_default_face_reset" not in {
        issue["code"] for issue in report["issues"]
    }


def test_source_accepts_solo_closeup_and_explicit_reveal_transition():
    source = """\
@camera_cut A
A: first
@camera_hold A,C
@reveal C 左
C(06)[惊叹]{jump}: impact
@camera_cut C
@bgfx 集中线
C(07){hophop}<特写>: peak
"""

    report = validate_annotated_source(source)

    assert report["result"] == "pass"


def test_legacy_plan_accepts_motivated_pair_anchor_match_cut():
    plan = {
        "event_chains": [_chain(shot_steps=[
            {
                "anchor_line": 1,
                "operation": "continue_group",
                "visible_characters": ["A", "B"],
                "focus": "B",
                "framing": "relation",
                "continuity": "hold",
            },
            {
                "anchor_line": 2,
                "operation": "anchor_match_cut",
                "cut_motivation": "C takes over the reply",
                "visible_characters": ["A", "C"],
                "focus": "C",
                "framing": "relation",
                "continuity": "hard_cut",
            },
        ])],
    }

    assert "stationary_pair_swap" not in {
        issue["code"] for issue in validate_director_plan(plan)["issues"]
    }


def test_source_rejects_repeated_plain_camera_for_the_same_group():
    report = validate_annotated_source("""\
@camera A,B
A: first
@camera A,B
B: second
""")

    assert "redundant_camera_declaration" in {
        issue["code"] for issue in report["issues"]
    }


def test_source_rejects_repeated_cut_and_overwritten_camera_declarations():
    repeated = validate_annotated_source("""\
@camera_cut A,B
A: first
@camera_cut A,B
B: second
""")
    overwritten = validate_annotated_source("""\
@camera_hold auto
@camera_cut A
A: first
""")

    assert "redundant_camera_declaration" in {
        issue["code"] for issue in repeated["issues"]
    }
    assert "overwritten_camera_declaration" in {
        issue["code"] for issue in overwritten["issues"]
    }


def test_source_rejects_move_overwritten_by_camera_before_visible_node():
    overwritten = validate_annotated_source("""\
@camera_cut A,B
A: first
@move A 2
@camera_cut A,C
C: second
""")
    rendered = validate_annotated_source("""\
@camera_cut A,B
A: first
@move A 2
A: moves on screen
@camera_cut A,C
@reveal C 左
C: second
""")

    assert "overwritten_move_before_camera" in {
        issue["code"] for issue in overwritten["issues"]
    }
    assert "overwritten_move_before_camera" not in {
        issue["code"] for issue in rendered["issues"]
    }


def test_source_allows_move_to_land_with_camera_hold_on_same_visible_node():
    report = validate_annotated_source("""\
@camera_hold A,B
A: first
@move A 2
@camera_hold A,C
@reveal C 左
C: second
""")

    assert "overwritten_move_before_camera" not in {
        issue["code"] for issue in report["issues"]
    }


def test_source_requires_closeup_release_before_camera_change():
    leaked = validate_annotated_source("""\
@camera_cut A
A(03)<特写>: impact
@camera_cut A,B
B: response
""")
    released = validate_annotated_source("""\
@camera_cut A
A(03)<特写>: impact
@fx A 无
@camera_cut A,B
B: response
""")

    assert "unreleased_closeup_before_camera_change" in {
        issue["code"] for issue in leaked["issues"]
    }
    assert "unreleased_closeup_before_camera_change" not in {
        issue["code"] for issue in released["issues"]
    }


def _execution_row(source_id, visible, *, operation="switch_group", **values):
    row = {
        "source_id": source_id,
        "direction": {
            "visible_characters": list(visible),
            "positions": {name: 1 + index * 3 for index, name in enumerate(visible)},
            "shot_transition": "cut",
            "shot_operation": operation,
        },
        "direction_intent": {
            "visible_characters": list(visible),
            "positions": {name: 1 + index * 3 for index, name in enumerate(visible)},
            "shot_transition": "cut",
            "shot_operation": operation,
        },
        "face": "", "emo": "", "act": "", "fx": "", "se": "",
        "bg": "", "bgfx": "", "trans": "", "move": 0, "reveal": "",
    }
    row.update(values)
    return row


def test_execution_requires_declared_release_owner_at_concrete_release_anchor():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "我宣布完成。"},
        {"annotation_id": "L2", "who": "B", "text": "原来如此。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        release_owner="B",
        peaks=[{
            "subject": "A", "peak_type": "solo_emphasis", "peak_id": "L1",
            "position": "on", "visual_intent": "宣布结果", "release_id": "L2",
            "release_position": "on", "why": "观察承受者的反应",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A"], face="06", fx="特写"),
        "L2": _execution_row("L2", ["A"]),
    }

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": False}}, constraints={},
    )

    assert "release_owner_not_visible" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_accepts_declared_release_owner_at_concrete_release_anchor():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "我宣布完成。"},
        {"annotation_id": "L2", "who": "B", "text": "原来如此。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        release_owner="B",
        peaks=[{
            "subject": "A", "peak_type": "solo_emphasis", "peak_id": "L1",
            "position": "on", "visual_intent": "宣布结果", "release_id": "L2",
            "release_position": "on", "why": "观察承受者的反应",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A"], face="06", fx="特写"),
        "L2": _execution_row("L2", ["B"]),
    }

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "release_owner_not_visible" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_preserves_explicit_valid_zero_face_and_keeps_persistent_id():
    beats, issues = sanitize_execution_beats([{
        "beat_id": "beat-stable", "anchor_id": "L1", "position": "after",
        "who": "A", "face": "00", "emo": "疑问", "act": "", "wait_ms": 400,
        "reason": "listener_reaction",
    }])

    assert beats[0]["face"] == "00"
    assert beats[0]["beat_id"] == "beat-stable"
    assert issues == []


def test_execution_requires_solo_peak_camera_and_planned_silent_carrier():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "看这里！"},
        {"annotation_id": "L2", "who": "B", "text": "……"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change", "camera_change"], "purpose": "爆点",
        }],
        silent_beats=[{
            "anchor_id": "L2", "position": "after", "phase": "decision_pause",
            "participants": ["B"], "purpose": "承受停顿", "sound_motivated": False,
            "carrier_requirement": {"any_of": ["pose_hold"], "require_observable_change": False},
        }],
        peaks=[{
            "subject": "A", "peak_type": "solo_emphasis", "peak_id": "L1",
            "position": "on", "visual_intent": "个人爆点", "release_id": "L2",
            "release_position": "on", "why": "强调发现",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A", "B"], face="06"),
        "L2": _execution_row("L2", ["B"]),
    }

    report = validate_execution_quality(
        plan, targets, lines, [],
        memory={"direction": {"scene_presence": {"A": "unknown", "B": "unknown"}}},
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )
    codes = {issue["code"] for issue in report["issues"]}

    assert "solo_emphasis_not_solo_center" in codes
    assert "missing_planned_silent_phase" in codes
    assert report["needs_review"] is True


def test_execution_requires_readable_performance_on_solo_peak():
    targets = [{"annotation_id": "L1", "who": "A", "text": "就是现在！"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        shot_groups=[{
            "group_id": "solo", "anchor_id": "L1", "members": ["A"],
            "focus": "A", "framing": "close", "operation": "switch",
            "cut_motivation": "个人爆点", "purpose": "强调决定",
        }],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["camera_change"], "purpose": "只切近景",
        }],
        peaks=[{
            "subject": "A", "peak_type": "solo_emphasis", "peak_id": "L1",
            "position": "on", "visual_intent": "个人决定", "release_id": "",
            "release_position": "scene_end", "why": "完成升级",
        }],
    )]}
    lines = {"L1": _execution_row("L1", ["A"])}

    plan_report = validate_plan_quality(plan)
    execution_report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "solo_emphasis_without_performance_carrier" in {
        issue["code"] for issue in plan_report["issues"]
    }
    assert "solo_emphasis_performance_unfulfilled" in {
        issue["code"] for issue in execution_report["issues"]
    }
    assert "solo_emphasis_closeup_unfulfilled" in {
        issue["code"] for issue in execution_report["issues"]
    }


def test_execution_accepts_a_solo_peak_with_real_closeup_and_face_change():
    targets = [{"annotation_id": "L1", "who": "A", "text": "就是现在！"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        shot_groups=[{
            "group_id": "solo", "anchor_id": "L1", "members": ["A"],
            "focus": "A", "framing": "close", "operation": "switch",
            "cut_motivation": "个人爆点", "purpose": "强调决定",
        }],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change", "camera_change"], "purpose": "峰值表演",
        }],
        peaks=[{
            "subject": "A", "peak_type": "solo_emphasis", "peak_id": "L1",
            "position": "on", "visual_intent": "个人决定", "release_id": "",
            "release_position": "scene_end", "why": "完成升级",
        }],
    )]}
    lines = {"L1": _execution_row("L1", ["A"], face="06", fx="特写")}

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "solo_emphasis_closeup_unfulfilled" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_rejects_soft_reframe_from_pair_to_solo_closeup():
    targets = [
        {"annotation_id": "L1", "who": "B", "text": "先问。"},
        {"annotation_id": "L2", "who": "A", "text": "重点回答！"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row(
            "L2", ["A"], operation="shrink_group", fx="特写",
            direction={
                "visible_characters": ["A"], "positions": {"A": 3},
                "shot_transition": "reframe", "shot_operation": "shrink_group",
            },
            direction_intent={
                "visible_characters": ["A"], "positions": {"A": 3},
                "shot_transition": "reframe", "shot_operation": "shrink_group",
            },
        ),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "closeup_requires_hard_cut" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_accepts_hard_cut_from_pair_to_solo_closeup():
    targets = [
        {"annotation_id": "L1", "who": "B", "text": "先问。"},
        {"annotation_id": "L2", "who": "A", "text": "重点回答！"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["A"], fx="特写"),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "closeup_requires_hard_cut" not in {
        issue["code"] for issue in report["issues"]
    }


def test_plan_derived_peak_mismatch_is_advisory_not_automatic_repair():
    issue = {
        "code": "peak_composition_mismatch",
        "severity": "high",
        "needs_review": True,
    }
    classified = classify_quality_issue(issue)
    assert classified["resolution"] == "advisory"
    assert classified["needs_review"] is False
    assert is_automatic_repairable_quality_issue(issue) is False


def test_plan_derived_unreadable_face_stage_is_advisory_not_automatic_repair():
    issue = {
        "code": "face_stage_no_readable_change",
        "severity": "high",
        "needs_review": True,
    }
    classified = classify_quality_issue(issue)
    assert classified["resolution"] == "advisory"
    assert classified["needs_review"] is False
    assert is_automatic_repairable_quality_issue(issue) is False


def test_execution_requires_reveal_when_reframe_adds_an_offscreen_character():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先说。"},
        {"annotation_id": "L2", "who": "B", "text": "我也在。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A"]),
        "L2": _execution_row(
            "L2", ["A", "B"], operation="expand_group",
            direction={
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 4},
                "shot_transition": "reframe", "shot_operation": "expand_group",
            },
            direction_intent={
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 4},
                "shot_transition": "reframe", "shot_operation": "expand_group",
            },
        ),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "reframe_adds_character_without_reveal" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_requires_conceal_when_reframe_removes_a_visible_character():
    targets = [{"annotation_id": "L1", "who": "A", "text": "继续。"}]
    lines = {"L1": _execution_row("L1", ["A"])}
    base_beat = {
        "beat_id": "beat-shrink", "anchor_id": "L1", "position": "before", "who": "A",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "relationship_turn", "visible_characters": ["A"],
        "positions": {"A": 3}, "shot_transition": "reframe",
        "shot_operation": "shrink_group",
    }
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "scene_presence": {"A": "present", "B": "present"},
        },
    }

    missing = validate_execution_quality(
        None, targets, lines, [base_beat], memory=memory,
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )
    explicit = validate_execution_quality(
        None, targets, lines,
        [{**base_beat, "conceal": [{"who": "B", "side": "fade"}]}],
        memory=memory,
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "reframe_removes_character_without_conceal" in {
        issue["code"] for issue in missing["issues"]
    }
    assert "reframe_removes_character_without_conceal" not in {
        issue["code"] for issue in explicit["issues"]
    }


def test_execution_accepts_cut_or_reveal_when_a_new_character_becomes_visible():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先说。"},
        {"annotation_id": "L2", "who": "B", "text": "我也在。"},
    ]
    cut_lines = {
        "L1": _execution_row("L1", ["A"]),
        "L2": _execution_row("L2", ["A", "B"]),
    }
    reveal_lines = {
        "L1": _execution_row("L1", ["A"]),
        "L2": _execution_row(
            "L2", ["A", "B"], operation="expand_group",
            reveal=[{"who": "B", "slot": 4}],
            direction={
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 4},
                "shot_transition": "reframe", "shot_operation": "expand_group",
            },
            direction_intent={
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 4},
                "shot_transition": "reframe", "shot_operation": "expand_group",
            },
        ),
    }

    for lines in (cut_lines, reveal_lines):
        report = validate_execution_quality(
            None, targets, lines, [],
            cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
        )
        assert "reframe_adds_character_without_reveal" not in {
            issue["code"] for issue in report["issues"]
        }


def _face_stage_plan():
    return {"events": [_v2_event(
        source_ids=["L1", "L2"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A"],
            "carriers": ["face_change"], "purpose": "从观察转为理解",
        }],
        face_arcs=[{
            "who": "A",
            "stages": [
                {
                    "anchor_id": "L1", "position": "on",
                    "semantic_state": "平静观察", "change_reason": "建立初态",
                },
                {
                    "anchor_id": "L2", "position": "on",
                    "semantic_state": "突然理解", "change_reason": "发现线索",
                },
            ],
        }],
    )]}


def test_execution_rejects_blank_face_at_semantic_stage_change():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先看看。"},
        {"annotation_id": "L2", "who": "A", "text": "原来如此。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A"], face="03"),
        "L2": _execution_row(
            "L2", ["A"], direction={}, direction_intent={}, face="",
        ),
    }

    report = validate_execution_quality(
        _face_stage_plan(), targets, lines, [],
        cast={"A": {"portrait": True}}, constraints={},
    )

    assert "face_stage_change_unfulfilled" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["needs_review"] is True


def test_execution_checks_first_face_stage_change_across_chunk_boundary():
    targets = [{"annotation_id": "L2", "who": "A", "text": "原来如此。"}]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A"],
            "carriers": ["face_change"], "purpose": "跨块理解",
        }],
        face_arcs=[{
            "who": "A", "stages": [
                {
                    "anchor_id": "L1", "position": "on",
                    "semantic_state": "平静观察", "change_reason": "上一块",
                },
                {
                    "anchor_id": "L2", "position": "on",
                    "semantic_state": "突然理解", "change_reason": "当前块",
                },
            ],
        }],
    )]}
    lines = {"L2": _execution_row(
        "L2", ["A"], direction={}, direction_intent={}, face="",
    )}

    report = validate_execution_quality(
        plan, targets, lines, [],
        memory={"direction": {
            "shot_visible_characters": ["A"], "positions": {"A": 3},
            "last_faces": {"A": "03"},
        }},
        cast={"A": {"portrait": True}}, constraints={},
    )

    assert "face_stage_change_unfulfilled" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_rejects_same_face_at_semantic_stage_change():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先看看。"},
        {"annotation_id": "L2", "who": "A", "text": "原来如此。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A"], face="03"),
        "L2": _execution_row(
            "L2", ["A"], direction={}, direction_intent={}, face="03",
        ),
    }

    report = validate_execution_quality(
        _face_stage_plan(), targets, lines, [],
        cast={"A": {"portrait": True}}, constraints={},
    )

    assert "face_stage_reused_same_face" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["needs_review"] is True


def test_execution_allows_semantically_suitable_face_to_hold_when_action_changes():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先看看。"},
        {"annotation_id": "L2", "who": "A", "text": "原来如此。"},
    ]
    plan = _face_stage_plan()
    plan["events"][0]["performance_intents"][0]["carriers"] = ["action"]
    lines = {
        "L1": _execution_row("L1", ["A"], face="03"),
        "L2": _execution_row(
            "L2", ["A"], direction={}, direction_intent={}, face="03",
        ),
    }
    lines["L2"]["act"] = "jump"

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert report["result"] == "pass"
    repeated = [
        issue for issue in report["issues"]
        if issue["code"] == "face_stage_reused_same_face"
    ]
    assert repeated and repeated[0]["severity"] == "warning"


def test_execution_requires_every_declared_performance_carrier():
    targets = [{"annotation_id": "L1", "who": "A", "text": "就是现在！"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change", "action"], "require_all": True,
            "purpose": "情绪与身体同时爆发",
        }],
    )]}
    lines = {"L1": _execution_row("L1", ["A"], face="06")}

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "performance_intent_unfulfilled"
    )
    assert issue["missing"] == ["action"]
    assert issue["severity"] == "high"
    assert report["needs_review"] is True


def test_execution_accepts_one_of_default_alternative_performance_carriers():
    targets = [{"annotation_id": "L1", "who": "A", "text": "就是现在！"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change", "action"], "purpose": "给出可读反应",
        }],
    )]}
    lines = {"L1": _execution_row("L1", ["A"], face="06")}

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "performance_intent_unfulfilled" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_credits_same_line_listener_reaction_for_after_intent():
    targets = [
        {"annotation_id": "L1", "who": "旁白", "text": "屏幕显示计划已经改变。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "after", "subjects": ["B"],
            "carriers": ["face_change", "pose_hold"],
            "purpose": "让信息击中听者后先被观众看见",
        }],
    )]}
    lines = {"L1": _execution_row(
        "L1", ["B"], reactions=[{
            "who": "B", "face": "04", "emo": "反应", "act": "",
        }],
    )}

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={
            "旁白": {"portrait": False, "narrator": True},
            "B": {"portrait": True},
        },
        constraints={},
    )

    assert "performance_intent_unfulfilled" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_flags_chunk_wide_face_only_performance_collapse():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "怎么会这样！？"},
        {"annotation_id": "L2", "who": "A", "text": "真的成功了！"},
        {"annotation_id": "L3", "who": "B", "text": "太好了！！"},
    ]
    intents = [
        {
            "anchor_id": anchor_id, "position": "on", "subjects": [who],
            "carriers": ["face_change", carrier],
            "purpose": purpose,
        }
        for anchor_id, who, carrier, purpose in (
            ("L1", "A", "emoticon", "惊讶需要可读气泡或身体反应"),
            ("L2", "A", "action", "成功需要可读身体反应"),
            ("L3", "B", "emoticon", "欢呼需要可读气泡或身体反应"),
        )
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2", "L3"],
        performance_intents=intents,
    )]}
    lines = {
        "L1": _execution_row("L1", ["A"], face="03"),
        "L2": _execution_row("L2", ["A"], face="04"),
        "L3": _execution_row("L3", ["B"], face="05"),
    }

    report = validate_execution_quality(
        plan, targets, lines, [], cast={
            "A": {"portrait": True}, "B": {"portrait": True},
        }, constraints={},
    )

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "performance_layer_collapsed"
    )
    assert issue["planned_non_face_intents"] == 3
    assert issue["observed_non_face_intents"] == 0
    assert report["needs_review"] is True


def test_execution_does_not_flag_single_face_only_alternative():
    targets = [{"annotation_id": "L1", "who": "A", "text": "嗯。"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change", "emoticon"], "purpose": "可选反应",
        }],
    )]}
    lines = {"L1": _execution_row("L1", ["A"], face="03")}

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "performance_layer_collapsed" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_treats_previous_after_as_current_before_boundary():
    targets = [
        {"annotation_id": "L1", "who": "B", "text": "你真厉害。"},
        {"annotation_id": "L2", "who": "A", "text": "……谢谢。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        performance_intents=[{
            "anchor_id": "L2", "position": "before", "subjects": ["A"],
            "carriers": ["face_change", "action"], "purpose": "致谢前的尴尬反应",
        }],
        face_arcs=[{
            "who": "A", "stages": [
                {
                    "anchor_id": "L1", "position": "on",
                    "semantic_state": "平静观察", "change_reason": "建立初态",
                },
                {
                    "anchor_id": "L2", "position": "before",
                    "semantic_state": "被夸后的尴尬", "change_reason": "受到称赞",
                },
            ],
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A", "B"], face="01"),
        "L2": _execution_row("L2", ["A"], face="04"),
    }
    beats = [{
        "beat_id": "beat-gap", "anchor_id": "L1", "position": "after", "who": "A",
        "face": "04", "emo": "冷汗", "act": "stiff", "wait_ms": 400,
        "reason": "listener_reaction", "visible_characters": ["A", "B"],
        "positions": {"A": 1, "B": 5},
    }]

    report = validate_execution_quality(
        plan, targets, lines, beats,
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    codes = {issue["code"] for issue in report["issues"]}
    assert "performance_intent_unfulfilled" not in codes
    assert "face_stage_change_unfulfilled" not in codes
    assert "face_stage_no_readable_change" not in codes


def test_execution_rejects_silent_beat_performers_outside_current_shot():
    targets = [{"annotation_id": "L1", "who": "A", "text": "就是这样。"}]
    lines = {"L1": _execution_row("L1", ["A"])}
    beats = [{
        "beat_id": "beat-off-camera", "anchor_id": "L1",
        "position": "after", "who": "B", "face": "04",
        "emo": "惊疑", "act": "", "wait_ms": 0,
        "reason": "group_reaction",
        "reactions": [{"who": "C", "face": "02", "emo": "冷汗", "act": ""}],
    }]

    report = validate_execution_quality(
        None, targets, lines, beats,
        cast={
            "A": {"portrait": True},
            "B": {"portrait": True},
            "C": {"portrait": True},
        },
        constraints={},
    )

    hidden = [
        issue for issue in report["issues"]
        if issue["code"] == "beat_performer_not_visible"
    ]
    assert {issue["who"] for issue in hidden} == {"B", "C"}
    assert {issue["role"] for issue in hidden} == {"primary", "reaction"}
    assert all(issue["anchor_id"] == "L1" for issue in hidden)
    assert all(issue["beat_id"] == "beat-off-camera" for issue in hidden)
    assert report["needs_review"] is True


def test_execution_does_not_credit_personal_carrier_to_wrong_subject():
    targets = [{"annotation_id": "L1", "who": "A", "text": "我明白了。"}]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        performance_intents=[{
            "anchor_id": "L1", "position": "on", "subjects": ["A"],
            "carriers": ["face_change"], "purpose": "A 的态度转折",
        }],
    )]}
    lines = {"L1": _execution_row(
        "L1", ["A", "B"], reactions=[{
            "who": "B", "face": "04", "emo": "", "act": "",
        }],
    )}

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "performance_intent_unfulfilled" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_does_not_count_repeated_face_as_face_change():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先看看。"},
        {"annotation_id": "L2", "who": "A", "text": "还是这样。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        performance_intents=[{
            "anchor_id": "L2", "position": "on", "subjects": ["A"],
            "carriers": ["face_change"], "purpose": "态度发生变化",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A"], face="03"),
        "L2": _execution_row(
            "L2", ["A"], direction={}, direction_intent={}, face="03",
        ),
    }

    report = validate_execution_quality(
        plan, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "performance_intent_unfulfilled" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_presence_separates_real_enter_from_visual_reveal():
    targets = [{"annotation_id": "L1", "who": "A", "text": "继续说。"}]
    lines = {"L1": _execution_row("L1", ["A", "B"])}
    beats = [{
        "beat_id": "beat-1", "anchor_id": "L1", "position": "before", "who": "B",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "visible_characters": ["A", "B"],
        "positions": {"A": 1, "B": 4}, "enter": [{"who": "B", "slot": 4, "side": "right"}],
    }]

    report = validate_execution_quality(
        None, targets, lines, beats,
        memory={"direction": {"scene_presence": {"A": "present", "B": "present"}}},
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )
    assert "enter_person_already_present" in {issue["code"] for issue in report["issues"]}


def test_execution_does_not_treat_polite_greeting_as_true_entry_evidence():
    targets = [{"annotation_id": "L1", "who": "A", "text": "打扰了，我来归还资料。"}]
    lines = {"L1": _execution_row("L1", ["A"])}
    beats = [{
        "beat_id": "beat-enter", "anchor_id": "L1", "position": "before", "who": "A",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "visible_characters": ["A"],
        "positions": {"A": 3}, "enter": [{"who": "A", "slot": 3, "side": "right"}],
    }]

    report = validate_execution_quality(
        None, targets, lines, beats,
        memory={"direction": {"scene_presence": {"A": "unknown"}}},
        cast={"A": {"portrait": True}}, constraints={},
    )

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "enter_without_arrival_evidence"
    )
    assert issue["resolution"] == "advisory"


def test_execution_accepts_explicit_physical_arrival_evidence():
    targets = [{"annotation_id": "L1", "who": "A", "text": "我刚推门走进来。"}]
    lines = {"L1": _execution_row("L1", ["A"])}
    beats = [{
        "beat_id": "beat-enter", "anchor_id": "L1", "position": "before", "who": "A",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "visible_characters": ["A"],
        "positions": {"A": 3}, "enter": [{"who": "A", "slot": 3, "side": "right"}],
    }]

    report = validate_execution_quality(
        None, targets, lines, beats,
        memory={"direction": {"scene_presence": {"A": "unknown"}}},
        cast={"A": {"portrait": True}}, constraints={},
    )

    assert "enter_without_arrival_evidence" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_uses_later_evidence_from_same_arrival_event():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "……"},
        {"annotation_id": "L2", "who": "B", "text": "你怎么在这里？"},
        {"annotation_id": "L3", "who": "B", "text": "欢迎回来。"},
    ]
    plan = {"events": [_v2_event(
        kind="arrival", source_ids=["L1", "L2", "L3"],
        phase_order=["reveal"], stimulus_targets=["A"],
        silent_beats=[{
            "anchor_id": "L1", "position": "before", "phase": "reveal",
            "participants": ["A"], "purpose": "A 确实从场外到达",
            "carrier_requirement": {
                "any_of": ["entry_exit"], "require_all": False,
            },
        }],
    )]}
    lines = {
        target["annotation_id"]: _execution_row(
            target["annotation_id"], ["A"],
            direction={} if target["annotation_id"] != "L1" else None,
            direction_intent={} if target["annotation_id"] != "L1" else None,
        )
        for target in targets
    }
    beats = [{
        "beat_id": "beat-enter", "anchor_id": "L1", "position": "before",
        "who": "A", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "visible_characters": ["A"],
        "positions": {"A": 3},
        "enter": [{"who": "A", "slot": 3, "side": "right"}],
    }]

    report = validate_execution_quality(
        plan, targets, lines, beats,
        memory={"direction": {"scene_presence": {"A": "unknown"}}},
        cast={"A": {"portrait": True}, "B": {"portrait": True}},
        constraints={},
    )

    assert "enter_without_arrival_evidence" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_rejects_unmotivated_single_occupant_swap():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "C", "text": "二。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"], operation="continue_group"),
        "L2": _execution_row("L2", ["A", "C"], operation="continue_group"),
    }
    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABC"}, constraints={},
    )

    assert "unmotivated_single_occupant_swap" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_reports_repeated_static_camera_pivot_as_advisory():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "B", "text": "二。"},
        {"annotation_id": "L3", "who": "C", "text": "三。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["A", "C"]),
        "L3": _execution_row("L3", ["A", "B"]),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABC"}, constraints={},
    )
    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "repeated_static_camera_pivot"
    )

    assert issue["resolution"] == "advisory"
    assert issue["anchor_id"] == "L3"
    assert issue["pivot"] == "A"
    assert issue["pivot_slot"] == 1
    assert [shot["visible"] for shot in issue["history"]] == [
        ["A", "B"], ["A", "C"], ["A", "B"],
    ]


def test_execution_keeps_hard_cuts_legal_when_the_shared_actor_reframes():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "B", "text": "二。"},
        {"annotation_id": "L3", "who": "C", "text": "三。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["A", "C"]),
        "L3": _execution_row("L3", ["A", "B"]),
    }
    for source_id, slot in (("L1", 1), ("L2", 2), ("L3", 3)):
        for field in ("direction", "direction_intent"):
            lines[source_id][field]["positions"]["A"] = slot

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABC"}, constraints={},
    )

    assert "repeated_static_camera_pivot" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_reports_speaker_chasing_camera_relay_as_advisory():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "B", "text": "二。"},
        {"annotation_id": "L3", "who": "C", "text": "三。"},
        {"annotation_id": "L4", "who": "D", "text": "四。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["B", "C"]),
        "L3": _execution_row("L3", ["C", "D"]),
        "L4": _execution_row("L4", ["D", "A"]),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABCD"}, constraints={},
    )
    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "speaker_chasing_camera_relay"
    )

    assert issue["resolution"] == "advisory"
    assert issue["anchor_id"] == "L4"
    assert [shot["speaker"] for shot in issue["history"]] == ["A", "B", "C", "D"]


def test_execution_allows_a_single_reverse_shot_inside_a_hard_cut_sequence():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "B", "text": "二。"},
        {"annotation_id": "L3", "who": "C", "text": "三。"},
        {"annotation_id": "L4", "who": "D", "text": "四。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["B", "C"]),
        "L3": _execution_row("L3", ["C"]),
        "L4": _execution_row("L4", ["D", "A"]),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABCD"}, constraints={},
    )

    assert "speaker_chasing_camera_relay" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_held_dialogue_breaks_camera_relay_chain():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "B", "text": "二。"},
        {"annotation_id": "L3", "who": "C", "text": "三。"},
        {"annotation_id": "L4", "who": "D", "text": "四。"},
        {"annotation_id": "L5", "who": "A", "text": "五。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A", "B"]),
        "L2": _execution_row("L2", ["B", "C"]),
        "L3": _execution_row("L3", ["C", "D"]),
        "L4": _execution_row("L4", ["C", "D"], direction={}, direction_intent={}),
        "L5": _execution_row("L5", ["D", "A"]),
    }

    report = validate_execution_quality(
        None, targets, lines, [],
        cast={name: {"portrait": True} for name in "ABCD"}, constraints={},
    )

    assert "speaker_chasing_camera_relay" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_rejects_camera_redeclaration_without_visible_change():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "一。"},
        {"annotation_id": "L2", "who": "A", "text": "二。"},
    ]
    lines = {
        "L1": _execution_row("L1", ["A"], operation="switch_group"),
        "L2": _execution_row("L2", ["A"], operation="switch_group"),
    }

    report = validate_execution_quality(
        None, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "redundant_camera_declaration" in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_accepts_same_group_reframe_when_closeup_scale_changes():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先确认条件。"},
        {"annotation_id": "L2", "who": "A", "text": "测试继续。"},
    ]
    first = _execution_row("L1", ["A"], operation="switch_group")
    second = _execution_row("L2", ["A"], operation="continue_group", fx="特写")
    second["direction"]["shot_transition"] = "reframe"
    second["direction_intent"]["shot_transition"] = "reframe"
    lines = {"L1": first, "L2": second}

    report = validate_execution_quality(
        None, targets, lines, [], cast={"A": {"portrait": True}}, constraints={},
    )

    assert "redundant_camera_declaration" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_preserves_explicit_cut_override_inside_planned_shot_span():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先听我说。"},
        {"annotation_id": "L2", "who": "B", "text": "我在听。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        shot_groups=[{
            "group_id": "pair", "anchor_id": "L1", "hold_until_id": "L2",
            "members": ["A", "B"], "focus": "A", "framing": "relation",
            "operation": "establish", "cut_motivation": "", "purpose": "同一问答",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A", "B"], operation="switch_group"),
        "L2": _execution_row("L2", ["B"], operation="switch_group"),
    }

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )
    codes = {issue["code"] for issue in report["issues"]}

    assert "unplanned_camera_change_inside_shot_span" in codes
    assert "planned_shot_span_unfulfilled" in codes
    span_issues = [
        issue for issue in report["issues"]
        if issue["code"] in {
            "unplanned_camera_change_inside_shot_span",
            "planned_shot_span_unfulfilled",
        }
    ]
    assert all(issue["severity"] == "warning" for issue in span_issues)
    assert all(issue["explicit_cut_override"] is True for issue in span_issues)
    assert report["result"] == "pass"


def test_execution_still_rejects_unplanned_reframe_inside_planned_shot_span():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先听我说。"},
        {"annotation_id": "L2", "who": "B", "text": "我在听。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        shot_groups=[{
            "group_id": "pair", "anchor_id": "L1", "hold_until_id": "L2",
            "members": ["A", "B"], "focus": "A", "framing": "relation",
            "operation": "establish", "cut_motivation": "", "purpose": "同一问答",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A", "B"], operation="switch_group"),
        "L2": _execution_row("L2", ["B"], operation="shrink_group"),
    }
    for field in ("direction", "direction_intent"):
        lines["L2"][field]["shot_transition"] = "reframe"

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "unplanned_camera_change_inside_shot_span"
    )
    assert issue["severity"] == "high"
    assert issue["explicit_cut_override"] is False
    assert report["result"] == "fail"


def test_execution_accepts_inherited_camera_inside_planned_shot_span():
    targets = [
        {"annotation_id": "L1", "who": "A", "text": "先听我说。"},
        {"annotation_id": "L2", "who": "B", "text": "我在听。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1", "L2"],
        shot_groups=[{
            "group_id": "pair", "anchor_id": "L1", "hold_until_id": "L2",
            "members": ["A", "B"], "focus": "A", "framing": "relation",
            "operation": "establish", "cut_motivation": "", "purpose": "同一问答",
        }],
    )]}
    lines = {
        "L1": _execution_row("L1", ["A", "B"], operation="switch_group"),
        "L2": _execution_row(
            "L2", ["A", "B"], direction={}, direction_intent={},
        ),
    }

    report = validate_execution_quality(
        plan, targets, lines, [],
        cast={"A": {"portrait": True}, "B": {"portrait": True}}, constraints={},
    )

    assert "unplanned_camera_change_inside_shot_span" not in {
        issue["code"] for issue in report["issues"]
    }
    assert "planned_shot_span_unfulfilled" not in {
        issue["code"] for issue in report["issues"]
    }


def test_execution_does_not_require_narrator_in_planned_camera():
    targets = [
        {"annotation_id": "L1", "who": "旁白", "text": "第二天。"},
    ]
    plan = {"events": [_v2_event(
        source_ids=["L1"],
        shot_groups=[{
            "group_id": "time-card", "anchor_id": "L1", "hold_until_id": "L1",
            "members": ["旁白"], "focus": "旁白", "framing": "wide",
            "operation": "anchor_match_cut", "cut_motivation": "时间跳转",
            "purpose": "建立新的时空。",
        }],
    )]}

    report = validate_execution_quality(
        plan, targets, {"L1": {"source_id": "L1"}}, [],
        cast={"旁白": {"portrait": False, "narrator": True}}, constraints={},
    )

    assert "planned_shot_span_unfulfilled" not in {
        issue["code"] for issue in report["issues"]
    }


def _compiled_script(characters, *, speaker=1, trace=None, dialog=True):
    values = [{"name": "", "endingPos": 0, "faceId": "00", "shapeOverride": 0,
               "emoticon": -1, "action": 0}]
    values.extend({
        "name": name, "endingPos": position, "faceId": face,
        "shapeOverride": 0, "emoticon": -1, "action": 0,
    } for name, position, face in characters)
    return {
        "characters": {"$values": values}, "speakerSlotNum": speaker,
        "isDialogScript": dialog, "transition": 0, "bgFriendlyName": "BG_A",
        "_trace": list(trace or []),
    }


def test_compiled_g3_reports_stationary_pair_swap_with_provenance():
    first = _compiled_script([("A", 1, "05"), ("B", 4, "03")])
    second = _compiled_script(
        [("A", 1, "05"), ("C", 4, "07")],
        trace=[{
            "source_id": "L2", "beat_id": "", "scene_id": "scene-1",
            "chunk_id": "chunk-1", "plan_event_ids": ["event-1"],
            "command": "camera_hold",
        }],
    )

    report = validate_compiled_staging([first, second])
    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_stationary_layer_swap"
    )

    assert report["result"] == "fail"
    assert issue["source_id"] == "L2"
    assert issue["script_index"] == 1
    assert issue["plan_event_ids"] == ["event-1"]


def test_compiled_g3_reports_speaker_chasing_camera_relay_as_advisory():
    scripts = [
        _compiled_script(
            [("A", 1, "05"), ("B", 4, "03")],
            trace=[{"source_id": "L1", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("B", 1, "05"), ("C", 4, "03")],
            trace=[{"source_id": "L2", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("C", 1, "05"), ("D", 4, "03")],
            trace=[{"source_id": "L3", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("D", 1, "05"), ("A", 4, "03")],
            trace=[{"source_id": "L4", "command": "camera_cut"}],
        ),
    ]

    report = validate_compiled_staging(scripts)
    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_speaker_chasing_camera_relay"
    )

    assert issue["resolution"] == "advisory"
    assert issue["source_id"] == "L4"
    assert [entry["speaker"] for entry in issue["history"]] == ["A", "B", "C", "D"]


def test_compiled_g3_allows_single_reverse_shot_to_break_camera_relay():
    scripts = [
        _compiled_script(
            [("A", 1, "05"), ("B", 4, "03")],
            trace=[{"source_id": "L1", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("B", 1, "05"), ("C", 4, "03")],
            trace=[{"source_id": "L2", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("C", 3, "05")],
            trace=[{"source_id": "L3", "command": "camera_cut"}],
        ),
        _compiled_script(
            [("D", 1, "05"), ("A", 4, "03")],
            trace=[{"source_id": "L4", "command": "camera_cut"}],
        ),
    ]

    assert "compiled_speaker_chasing_camera_relay" not in {
        issue["code"] for issue in validate_compiled_staging(scripts)["issues"]
    }


def test_compiled_g3_does_not_treat_face_change_as_spatial_reframe():
    first = _compiled_script([("A", 1, "05"), ("B", 4, "03")])
    second = _compiled_script([("A", 1, "06"), ("C", 4, "07")])

    assert "compiled_stationary_layer_swap" in {
        issue["code"] for issue in validate_compiled_staging([first, second])["issues"]
    }


def test_compiled_g3_rejects_persistent_closeup_in_group_shot():
    script = _compiled_script([("A", 1, "03"), ("B", 5, "05")])
    script["characters"]["$values"][1]["shapeOverride"] = 4

    report = validate_compiled_staging([script])

    assert "compiled_closeup_leaked_into_group" in {
        issue["code"] for issue in report["issues"]
    }
    assert report["result"] == "fail"


def test_compiled_g3_ignores_noop_camera_hold_on_silent_wait():
    first = _compiled_script([("A", 3, "05")])
    second = _compiled_script(
        [("A", 3, "05")],
        trace=[
            {"source_id": "wait-1", "command": "wait"},
            {"source_id": "wait-1", "command": "nodialog"},
            {"source_id": "wait-1", "command": "camera_hold"},
            {"source_id": "wait-1", "command": "move"},
        ],
    )

    assert "compiled_redundant_camera_declaration" not in {
        issue["code"] for issue in validate_compiled_staging([first, second])["issues"]
    }


def test_compiled_g3_accepts_pair_change_with_explicit_reveal():
    first = _compiled_script([("A", 1, "05"), ("B", 4, "03")])
    second = _compiled_script(
        [("A", 1, "05"), ("C", 4, "07")],
        trace=[{"source_id": "L2", "command": "reveal", "target": "C"}],
    )

    assert "compiled_stationary_layer_swap" not in {
        issue["code"] for issue in validate_compiled_staging([first, second])["issues"]
    }


def test_compiled_g3_accepts_pair_anchor_match_camera_cut():
    first = _compiled_script([("A", 1, "05"), ("B", 4, "03")])
    second = _compiled_script(
        [("A", 1, "05"), ("C", 4, "07")],
        trace=[{
            "source_id": "L2", "command": "camera_cut",
            "plan_event_ids": ["event-new-focus"],
        }],
    )

    assert "compiled_stationary_layer_swap" not in {
        issue["code"] for issue in validate_compiled_staging([first, second])["issues"]
    }


def test_compiled_g3_reports_exit_that_remains_visible():
    script = _compiled_script(
        [("A", 3, "05")],
        trace=[{"source_id": "L1", "command": "exit", "target": "A"}],
    )

    report = validate_compiled_staging([script])

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_exit_still_visible"
    )
    assert issue["severity"] == "critical"
    assert issue["source_id"] == "L1"


def test_compiled_g3_reports_reappearance_without_enter_or_reveal():
    first = _compiled_script([("A", 3, "05")])
    exited = _compiled_script(
        [], dialog=False,
        trace=[{"source_id": "beat-1", "command": "exit", "target": "A"}],
    )
    returned = _compiled_script(
        [("A", 3, "07")], trace=[{"source_id": "L2", "command": ""}],
    )

    report = validate_compiled_staging([first, exited, returned])

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_presence_resurrection"
    )
    assert issue["character"] == "A"
    assert issue["source_id"] == "L2"


def test_compiled_g3_reports_transition_without_background_change():
    first = _compiled_script([], dialog=False)
    second = _compiled_script([], dialog=False)
    second["transition"] = 2
    second["_trace"] = [{"source_id": "L2", "command": "trans"}]

    report = validate_compiled_staging([first, second])

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_trans_without_bg_change"
    )
    assert issue["background"] == "BG_A"
    assert issue["source_id"] == "L2"


def test_compiled_g3_reports_more_than_three_visible_characters():
    script = _compiled_script([
        ("A", 1, "05"), ("B", 2, "03"), ("C", 4, "07"), ("D", 5, "01"),
    ])

    report = validate_compiled_staging([script])

    issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "compiled_visible_over_three"
    )
    assert issue["severity"] == "critical"
    assert issue["visible"] == ["A", "B", "C", "D"]


def test_compiled_g3_allows_an_explicit_listener_shot_for_a_dialogue_line():
    script = _compiled_script(
        [("A", 1, "05")], speaker=2,
        trace=[{"source_id": "L1", "command": ""}],
    )

    report = validate_compiled_staging([script])

    assert "compiled_speaker_missing" not in {
        issue["code"] for issue in report["issues"]
    }
