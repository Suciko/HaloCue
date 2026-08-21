import hashlib
import json
import sys
from pathlib import Path

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


def test_annotation_static_system_uses_confirmed_plan_window_without_full_source():
    static = annotate.build_annotation_static_system(
        "RULES", "Kai: full source should stay in the execution window\n",
        source_context_strategy="planned_window",
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

    assert output.read_text(encoding="utf-8") == "Kai: hello\n"


def test_mock_provider_never_invents_closeups_movement_or_shake():
    provider = llm.MockProvider({})
    user = "需要标注的段落：\n" + "\n".join(
        f"[{index}] Kai: line {index}" for index in range(25)
    )

    response = provider.complete_json("", "", user, annotate.SCHEMA)

    assert response["lines"]
    assert all(not row.get("fx") for row in response["lines"])
    assert all(not row.get("move") for row in response["lines"])
    assert all(not row.get("shake") for row in response["lines"])


def test_all_three_layout_modes_are_accepted():
    assert [annotate.normalize_layout_mode(value) for value in ("pure_ai", "ai", "rules")] == [
        "pure_ai", "ai", "rules",
    ]


def test_agent_mode_accepts_mock_provider_source_identity_response(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        annotate, "apply_speaker_turn_face_activation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stateful Agent must not use phrase-based face guessing")
        ),
    )
    original_build_static = annotate.build_static
    official_context_paths = []

    def capture_build_static(*args, **kwargs):
        official_context_paths.append(kwargs.get("official_db_path"))
        return original_build_static(*args, **kwargs)

    monkeypatch.setattr(annotate, "build_static", capture_build_static)
    result = annotate.annotate_script({
        "script": str(script), "out": str(output), "cast": str(cast),
        "index": str(index), "llm": str(llm_config), "agent_enabled": True,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }, provider_instance=llm.MockProvider({}))
    assert result["agent"]["enabled"] is True
    assert official_context_paths == [None]
    assert output.read_text(encoding="utf-8") == "Kai: hello\nKai: goodbye\n"
    trace = json.loads(Path(result["trace"]).read_text(encoding="utf-8"))
    assert trace["annotated_source_sha256"] == hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
    checkpoint = json.loads(next((tmp_path / "checkpoints").rglob("checkpoint.json")).read_text(encoding="utf-8"))
    assert checkpoint["schema_version"] == 3
    assert checkpoint["chunk_outputs"]
    assert checkpoint["fingerprint"]["schema_version"] == 3
    assert checkpoint["fingerprint"]["chunk_version"] == "scene-v3"
    assert checkpoint["fingerprint"]["director_version"] == "stateful-v1"
    assert checkpoint["fingerprint"]["story_type"] == "auto"
    assert checkpoint["fingerprint"]["run_mode"] == "balanced"
    assert checkpoint["fingerprint"]["source_id"] == str(script.resolve())
    assert checkpoint["fingerprint"]["model"]["source_context_strategy"] == "window"
    assert checkpoint["director_plan"]["story_type"] == "auto"
    assert checkpoint["memory"]["story"]["type"] == "auto"
    assert Path(result["model_audit"]).is_file()


def test_render_trace_maps_directives_and_silent_beat_to_persistent_ids():
    dialogue = {
        "kind": "line", "raw": "", "who": "凯伊", "text": "你好",
        "annotation_id": "source-1", "_annotation_scene_id": "scene-1",
        "_annotation_chunk_id": "chunk-1", "_plan_event_ids": ["event-1"],
        "face": "05", "emo": "", "act": "", "fx": "", "se": "",
        "bg": "", "trans": "", "bgfx": "", "place": "", "move": 0,
        "shake": False,
    }
    beat = annotate._beat_item({
        "beat_id": "beat-stable", "anchor_id": "source-1", "position": "before",
        "who": "凯伊", "face": "", "emo": "疑问", "act": "",
        "wait_ms": 500, "reason": "decision_pause",
        "_scene_id": "scene-1", "_chunk_id": "chunk-1",
        "_plan_event_ids": ["event-1"],
    })

    rendered, trace = annotate.render_annotated_items_with_trace([beat, dialogue])

    assert trace["annotated_source_sha256"] == __import__("hashlib").sha256(
        rendered.encode("utf-8")
    ).hexdigest()
    beat_rows = [row for row in trace["lines"] if row["beat_id"] == "beat-stable"]
    assert {row["command"] for row in beat_rows} >= {"wait", "nodialog"}
    assert all(row["source_id"] == "source-1" for row in beat_rows)
    rendered_lines = rendered.splitlines()
    assert all(
        1 <= row["line"] <= len(rendered_lines)
        and (
            not row["command"]
            or rendered_lines[row["line"] - 1].startswith("@" + row["command"])
        )
        for row in trace["lines"]
    )


def test_render_trace_preserves_a_narration_line_listener_reaction():
    narration = {
        "kind": "line", "raw": "", "who": "旁白", "text": "屏幕亮起",
        "annotation_id": "source-narration", "_annotation_scene_id": "scene-1",
        "_annotation_chunk_id": "chunk-1", "face": "", "emo": "", "act": "",
        "fx": "", "se": "", "bg": "", "trans": "", "bgfx": "", "place": "",
        "move": 0, "shake": False,
        "_reactions": [{"who": "凯伊", "face": "31", "emo": "惊疑", "act": "stiff"}],
    }

    rendered, trace = annotate.render_annotated_items_with_trace([narration])

    assert '@react {"who":"凯伊","face":"31","emo":"惊疑","act":"stiff"}' in rendered
    reaction_rows = [row for row in trace["lines"] if row["command"] == "react"]
    assert len(reaction_rows) == 1
    assert reaction_rows[0]["source_id"] == "source-narration"
    assert reaction_rows[0]["target"] == "凯伊"


def test_model_output_audit_exposes_raw_validated_applied_and_rendered_stages():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{
                "i": 1, "face": "[Emo:认真]", "visible_characters": ["A"],
                "positions": {"A": 3},
            }], "beats": [{
                "anchor_id": 1, "position": "after", "who": "B",
                "face": "03", "emo": "疑问", "act": "stiff", "wait_ms": 300,
                "reason": "listener_reaction", "reactions": [{
                    "who": "A", "face": "05", "emo": "惊叹", "act": "jump",
                }],
            }]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "face": "[Emo:认真]", "direction": {
                    "visible_characters": ["A"], "positions": {"A": 3},
                },
            }], "beats": [{
                "anchor_id": "L1", "position": "after", "who": "B",
                "face": "03", "emo": "疑问", "act": "stiff", "wait_ms": 300,
                "reason": "listener_reaction", "reactions": [{
                    "who": "A", "face": "05", "emo": "惊叹", "act": "jump",
                }],
            }]},
            "validated_response": {"lines_by_id": {"L1": {
                "face": "05", "direction_intent": {
                    "visible_characters": ["A"], "positions": {"A": 3},
                },
            }}, "beats": [{
                "beat_id": "beat-1", "anchor_id": "L1", "position": "after",
                "who": "B", "face": "03", "emo": "疑问", "act": "stiff",
                "wait_ms": 300, "reason": "listener_reaction", "reactions": [{
                    "who": "A", "face": "05", "emo": "惊叹", "act": "jump",
                }],
            }]},
        }],
        "lines_by_id": {"L1": {
            "face": "05", "direction_intent": {
                "visible_characters": ["A"], "positions": {"A": 3},
            },
        }},
        "beats_by_id": {"beat-1": {
            "beat_id": "beat-1", "anchor_id": "L1", "position": "after",
            "who": "B", "face": "03", "emo": "疑问", "act": "stiff",
            "wait_ms": 300, "reason": "listener_reaction", "reactions": [{
                "who": "A", "face": "05", "emo": "惊叹", "act": "jump",
            }],
        }},
    }}
    items = [{
        "annotation_id": "L1", "face": "05",
        "_director": {"visible_characters": ["A"], "positions": {"A": 3}},
        "_director_intent": {"visible_characters": ["A"], "positions": {"A": 3}},
    }]
    policy_beats = list(chunks["chunk-1"]["beats_by_id"].values())
    trace = [
        {"source_id": "L1", "beat_id": "", "command": "camera_hold", "line": 1},
        {"source_id": "L1", "beat_id": "", "command": "move", "line": 2},
        {"source_id": "L1", "beat_id": "beat-1", "command": "wait", "line": 3},
        {"source_id": "L1", "beat_id": "beat-1", "command": "react", "line": 4},
        {"source_id": "L1", "beat_id": "", "command": "", "kind": "line", "line": 5},
        {"source_id": "L1", "beat_id": "beat-1", "command": "", "kind": "line", "line": 6},
    ]

    audit = annotate.build_model_output_audit(
        chunks, items, trace, [], policy_beats=policy_beats,
    )

    assert audit["summary"]["attempts"] == 1
    assert audit["summary"]["accepted_attempts"] == 1
    assert audit["summary"]["missing_after_validation"] == 0
    assert audit["summary"]["missing_after_policy"] == 0
    assert {
        key: audit["summary"]["director_fields"][key]
        for key in (
            "raw_top_level", "raw_nested_d", "expanded",
            "direction_intent", "compiled_to_aap",
        )
    } == {
        "raw_top_level": 2,
        "raw_nested_d": 0,
        "expanded": 2,
        "direction_intent": 2,
        "compiled_to_aap": 2,
    }
    decisions = audit["chunks"][0]["attempts"][0]["decisions"]
    camera = next(entry for entry in decisions if entry["field"] == "visible_characters")
    assert camera == {
        "source_id": "L1", "chunk_id": "chunk-1", "layer": "direction",
        "field": "visible_characters", "origin": "top_level",
        "ai_raw_value": ["A"], "expanded_value": ["A"],
        "validated_value": ["A"], "policy_value": ["A"],
        "final_aap_trace": [trace[0]], "status": "applied_or_stateful",
        "diagnostics": [], "discard_reason": "",
    }
    reaction = next(entry for entry in decisions if entry["field"] == "reactions")
    assert reaction["layer"] == "beat"
    assert reaction["validated_value"][0]["act"] == "jump"
    assert reaction["policy_value"][0]["emo"] == "惊叹"
    assert reaction["final_aap_trace"][0]["command"] == "react"
    assert reaction["status"] == "applied"
    assert audit["chunks"][0]["render_trace"]["L1"][0]["command"] == "camera_hold"


def test_model_output_audit_matches_stateful_memory_events_by_identity_not_array_order():
    raw_events = [
        {"kind": "object_status", "source_ids": [1], "summary": "手把丢失"},
        {"kind": "accusation", "source_ids": [2], "summary": "尚未证实的指认"},
    ]
    expanded_events = [
        {"kind": "object_status", "source_ids": ["L1"], "summary": "手把丢失"},
        {"kind": "accusation", "source_ids": ["L2"], "summary": "尚未证实的指认"},
    ]
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1", "L2"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [], "state_delta": {}, "memory_events": raw_events},
            "expanded_response": {
                "lines": [], "state_delta": {}, "memory_events": expanded_events,
            },
            "validated_response": {
                "lines_by_id": {}, "state_delta": {},
                "memory_events": expanded_events,
            },
        }],
        "lines_by_id": {}, "beats_by_id": {}, "state_delta": {},
        "memory_events": list(reversed(expanded_events)),
    }}

    audit = annotate.build_model_output_audit(chunks, [], [], [])

    assert audit["summary"]["missing_after_policy"] == 0
    decisions = audit["chunks"][0]["attempts"][0]["decisions"]
    assert decisions
    assert {row["status"] for row in decisions} == {"applied_or_stateful"}
    assert {
        (row["source_id"], row["field"], row["policy_value"])
        for row in decisions if row["field"] == "summary"
    } == {
        ("L1", "summary", "手把丢失"),
        ("L2", "summary", "尚未证实的指认"),
    }


def test_model_output_audit_preserves_hard_protocol_repairs():
    repairs = [{
        "source_id": "L1", "speaker": "老师", "field": "face",
        "value": "[Emo:平静·2]", "reason": "non_portrait_speaker_resource",
    }]
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "protocol_repairs": repairs,
            "response": {"lines": [{"i": 1, "face": "[Emo:平静·2]"}]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "face": "[Emo:平静·2]",
            }]},
            "validated_response": {"lines_by_id": {"L1": {"face": ""}}},
        }],
        "lines_by_id": {"L1": {"face": ""}}, "beats_by_id": {},
        "state_delta": {}, "memory_events": [],
    }}

    audit = annotate.build_model_output_audit(chunks, [], [], [])

    assert audit["chunks"][0]["attempts"][0]["protocol_repairs"] == repairs


def test_model_output_audit_does_not_excuse_valid_zero_face_loss_as_placeholder_repair():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [], "beats": [{
                "anchor_id": 1, "position": "after", "who": "A",
                "face": "00", "emo": "", "act": "", "wait_ms": 300,
                "reason": "listener_reaction",
            }]},
            "expanded_response": {"lines": [], "beats": [{
                "anchor_id": "L1", "position": "after", "who": "A",
                "face": "00", "emo": "", "act": "", "wait_ms": 300,
                "reason": "listener_reaction",
            }]},
            "validated_response": {"lines_by_id": {}, "beats": [{
                "beat_id": "beat-1", "anchor_id": "L1", "position": "after",
                "who": "A", "face": "00", "emo": "", "act": "",
                "wait_ms": 300, "reason": "listener_reaction",
            }]},
        }],
        "lines_by_id": {},
        "beats_by_id": {"beat-1": {
            "beat_id": "beat-1", "anchor_id": "L1", "position": "after",
            "who": "A", "face": "", "emo": "", "act": "",
            "wait_ms": 300, "reason": "listener_reaction",
        }},
    }}
    diagnostics = [{
        "code": "default_face_placeholder", "field": "face",
        "anchor_id": "L1", "beat_id": "beat-1",
        "message": "00 placeholder removed",
    }]

    audit = annotate.build_model_output_audit(
        chunks, [], [{
            "source_id": "L1", "beat_id": "beat-1", "kind": "line",
            "command": "", "line": 1,
        }], diagnostics,
        policy_beats=list(chunks["chunk-1"]["beats_by_id"].values()),
    )

    face = next(
        row for row in audit["chunks"][0]["attempts"][0]["decisions"]
        if row["field"] == "face"
    )
    assert face["validated_value"] == "00"
    assert face["policy_value"] == ""
    assert face["final_aap_trace"] == []
    assert face["status"] == "missing_after_policy"
    assert face["loss_stage"] == "policy"
    assert face["discard_reason"] == "00 placeholder removed"


def test_model_output_audit_prefers_exact_resource_loss_over_fieldless_stale_issue():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{"i": 1, "emo": "惊疑[?!]"}]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "emo": "惊疑[?!]",
            }]},
            "validated_response": {"lines_by_id": {"L1": {
                "emo": "惊疑[?!]",
            }}},
        }],
        "lines_by_id": {"L1": {"emo": ""}}, "beats_by_id": {},
    }}
    diagnostics = [{
        "code": "overlapping_shot_hold_ranges", "anchor_id": "L1",
        "message": "旧 G1 镜头区间重叠",
    }, {
        "code": "director_resource_downgraded", "source_id": "L1",
        "field": "emo", "message": "未知气泡 惊疑[?!]",
    }]

    audit = annotate.build_model_output_audit(
        chunks, [{"kind": "line", "annotation_id": "L1", "emo": ""}],
        [], diagnostics,
    )

    emo = next(
        row for row in audit["chunks"][0]["attempts"][0]["decisions"]
        if row["field"] == "emo"
    )
    assert emo["status"] == "missing_after_policy"
    assert emo["discard_reason"] == "未知气泡 惊疑[?!]"
    assert emo["diagnostics"][0]["code"] == "director_resource_downgraded"


def test_model_output_audit_treats_explicit_repair_clear_as_supersession_not_policy_loss():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "target_ids": ["L1"],
            "response": {"lines": [{"i": 1, "fx": "特写"}]},
            "expanded_response": {"lines": [{"source_id": "L1", "fx": "特写"}]},
            "validated_response": {"lines_by_id": {"L1": {"fx": "特写"}}},
        }, {
            "phase": "g2_repair", "request_index": 2, "outcome": "accepted",
            "target_ids": ["L1"],
            "response": {"lines": [{"source_id": "L1", "fx": ""}]},
            "expanded_response": {"lines": [{"source_id": "L1", "fx": ""}]},
            "validated_response": {"lines_by_id": {"L1": {"fx": ""}}},
        }],
        "lines_by_id": {"L1": {"fx": ""}}, "beats_by_id": {},
    }}
    diagnostics = [{
        "code": "closeup_with_multiple_characters", "anchor_id": "L1",
        "message": "单人特写仍保留多人构图。", "severity": "high",
    }]

    audit = annotate.build_model_output_audit(
        chunks, [{"kind": "line", "annotation_id": "L1", "fx": ""}],
        [], diagnostics,
    )

    execution = audit["chunks"][0]["attempts"][0]["decisions"][0]
    repair = audit["chunks"][0]["attempts"][1]["decisions"][0]
    assert execution["status"] == "superseded_by_accepted_repair"
    assert execution["superseded_status"] == "missing_after_policy"
    assert execution["discard_reason"] == "superseded_by_later_accepted_attempt"
    assert execution["superseded_by"] == {
        "phase": "g2_repair", "request_index": 2,
    }
    assert "loss_stage" not in execution
    assert repair["status"] == "explicit_empty"
    assert audit["summary"]["superseded_decisions"] == 1
    assert audit["summary"]["explicit_decisions"] == 1
    assert audit["summary"]["explicit_empty"] == 1
    assert audit["summary"]["missing_after_policy"] == 0


def test_model_output_audit_records_explicit_validation_clear_with_reason():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{
                "i": 1, "focus_character": "旁白",
            }]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "direction": {"focus_character": "旁白"},
            }]},
            "validated_response": {
                "lines_by_id": {"L1": {
                    "direction_intent": {"focus_character": ""},
                }},
                "diagnostics": [{
                    "code": "director_non_displayable_character",
                    "source_id": "L1", "field": "focus_character",
                    "message": "Character cannot be displayed: 旁白",
                }],
            },
        }],
        "lines_by_id": {"L1": {"_director": {}, "_director_intent": {}}},
        "beats_by_id": {},
    }}

    audit = annotate.build_model_output_audit(chunks, [], [], [])
    decision = audit["chunks"][0]["attempts"][0]["decisions"][0]
    assert decision["field"] == "focus_character"
    assert decision["validated_value"] == ""
    assert decision["status"] == "missing_after_validation"
    assert decision["loss_stage"] == "validation"
    assert decision["discard_reason"] == "Character cannot be displayed: 旁白"
    assert decision["diagnostics"][0]["source_id"] == "L1"
    assert audit["summary"]["missing_after_validation"] == 1


def test_checkpoint_quality_diagnostics_use_current_canonical_resolution():
    diagnostics = annotate.reclassify_quality_diagnostics([{
        "code": "planned_shot_span_unfulfilled",
        "severity": "high",
        "resolution": "ai_repair",
        "needs_review": True,
    }])

    assert diagnostics == [{
        "code": "planned_shot_span_unfulfilled",
        "severity": "high",
        "resolution": "advisory",
        "needs_review": False,
    }]


def test_rendered_camera_cut_supersedes_pre_render_closeup_warning():
    diagnostics = annotate.reconcile_quality_diagnostics_with_rendered_trace(
        [{
            "code": "closeup_requires_hard_cut",
            "severity": "high",
            "anchor_id": "L1",
            "resolution": "ai_repair",
            "needs_review": True,
        }],
        [{"source_id": "L1", "command": "camera_cut", "line": 2}],
    )

    assert diagnostics[0]["resolution"] == "deterministic"
    assert diagnostics[0]["needs_review"] is False
    assert diagnostics[0]["evidence_status"] == "superseded_by_rendered_trace"
    assert diagnostics[0]["superseded_reason"] == "final_render_contains_camera_cut"


def test_model_output_audit_names_protocol_expansion_loss_explicitly():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "rejected",
            "response": {"lines": [{"i": 2, "face": "05"}]},
            "expanded_response": {}, "validated_response": {},
        }],
        "lines_by_id": {}, "beats_by_id": {},
    }}

    audit = annotate.build_model_output_audit(chunks, [], [], [])

    decision = audit["chunks"][0]["attempts"][0]["decisions"][0]
    assert decision["status"] == "missing_after_protocol"
    assert decision["loss_stage"] == "protocol_expansion"
    assert decision["discard_reason"] == "missing_after_protocol_expansion"
    assert audit["summary"]["rejected_attempt_statuses"] == {
        "missing_after_protocol": 1,
    }


def test_model_output_audit_counts_render_loss_without_policy_double_count():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{"i": 1, "bg_request": "custom room"}]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "bg_request": "custom room",
            }]},
            "validated_response": {"lines_by_id": {"L1": {
                "bg_request": "custom room",
            }}},
        }],
        "lines_by_id": {"L1": {"bg_request": "custom room"}},
        "beats_by_id": {},
    }}
    items = [{"annotation_id": "L1", "bg_request": "custom room"}]

    audit = annotate.build_model_output_audit(chunks, items, [], [])

    decision = audit["chunks"][0]["attempts"][0]["decisions"][0]
    assert decision["loss_stage"] == "render"
    assert decision["discard_reason"] == "not_compiled_to_aap"
    assert audit["summary"]["missing_after_render"] == 1
    assert audit["summary"]["missing_after_policy"] == 0


def test_model_output_audit_explains_suppressed_initial_background_transition():
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{
                "i": 1, "bg": "BG_First", "trans": "淡入淡出",
            }]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "bg": "BG_First", "trans": "淡入淡出",
            }]},
            "validated_response": {"lines_by_id": {"L1": {
                "bg": "BG_First", "trans": "淡入淡出",
            }}},
        }],
        "lines_by_id": {"L1": {"bg": "BG_First", "trans": "淡入淡出"}},
        "beats_by_id": {},
    }}
    items = [{
        "kind": "line", "annotation_id": "L1", "who": "旁白", "text": "开场",
        "bg": "BG_First", "trans": "淡入淡出",
    }]
    trace = [
        {"line": 1, "kind": "directive", "command": "bg", "source_id": "L1"},
        {"line": 2, "kind": "line", "command": "", "source_id": "L1"},
    ]

    audit = annotate.build_model_output_audit(chunks, items, trace, [])

    transition = next(
        row for row in audit["chunks"][0]["attempts"][0]["decisions"]
        if row["field"] == "trans"
    )
    assert transition["status"] == "applied_or_stateful"
    assert transition["discard_reason"] == "initial_background_transition_suppressed"
    assert audit["summary"]["missing_after_render"] == 0


def test_model_output_audit_treats_offscreen_relation_distance_as_metadata():
    direction = {"focus_kind": "offscreen_space", "relation_distance": "normal"}
    chunks = {"chunk-1": {
        "scene_id": "scene-1", "target_ids": ["L1"],
        "model_attempts": [{
            "phase": "execution", "request_index": 1, "outcome": "accepted",
            "response": {"lines": [{"i": 1, "d": direction}]},
            "expanded_response": {"lines": [{
                "source_id": "L1", "direction": direction,
            }]},
            "validated_response": {"lines_by_id": {"L1": {
                "direction_intent": direction,
            }}},
        }],
        "lines_by_id": {"L1": {"direction_intent": direction}},
        "beats_by_id": {},
    }}
    items = [{
        "kind": "line", "annotation_id": "L1", "who": "旁白", "text": "时间卡",
        "_director_intent": direction, "_director": direction,
    }]
    trace = [{"line": 1, "kind": "line", "command": "", "source_id": "L1"}]

    audit = annotate.build_model_output_audit(chunks, items, trace, [])

    distance = next(
        row for row in audit["chunks"][0]["attempts"][0]["decisions"]
        if row["field"] == "relation_distance"
    )
    assert distance["status"] == "applied_or_stateful"
    assert distance["discard_reason"] == "offscreen_space_has_no_layout"
    assert audit["summary"]["missing_after_render"] == 0


def test_compiled_trace_attaches_line_diagnostic_to_render_loss(tmp_path):
    from tools.replay_seia_v16_backend import attach_compiled_trace

    audit_path = tmp_path / "result.model-audit.json"
    audit_path.write_text(json.dumps({
        "summary": {"missing_after_render": 1, "missing_after_policy": 0},
        "chunks": [{
            "render_trace": {"L1": [{
                "line": 2, "kind": "directive", "command": "",
                "source_id": "L1",
            }]},
            "attempts": [{"decisions": [{
                "source_id": "L1", "layer": "annotation", "field": "bg_request",
                "final_aap_trace": [], "status": "missing_after_policy",
                "loss_stage": "render", "diagnostics": [],
                "discard_reason": "not_compiled_to_aap",
            }]}],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    attach_compiled_trace(audit_path, {
        "aap_file": "result.aap", "events": [],
        "compiled_scripts": [{
            "script_index": 0,
            "origins": [{"line": 2, "source_id": "L1", "beat_id": ""}],
        }],
        "quality": {"issues": [{
            "code": "unresolved_background_request", "line": 2,
            "message": "未解决的背景请求: custom room",
            "severity": "warning", "resolution": "ai_repair",
        }]},
    })

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    decision = audit["chunks"][0]["attempts"][0]["decisions"][0]
    assert decision["diagnostics"][0]["code"] == "unresolved_background_request"
    assert decision["diagnostics"][0]["resolution"] == "resource_required"
    assert decision["diagnostics"][0]["line"] == 2
    assert decision["status"] == "missing_after_render"
    assert decision["final_aap_trace"] == []
    assert decision["discard_reason"] == "unresolved_background_request"


def test_compiled_trace_marks_dropped_reaction_and_uses_physical_script(tmp_path):
    from tools.replay_seia_v16_backend import attach_compiled_trace

    audit_path = tmp_path / "result.model-audit.json"
    rendered = [{
        "line": 3, "kind": "line", "command": "", "source_id": "L1",
        "beat_id": "beat-1",
    }]
    audit_path.write_text(json.dumps({
        "summary": {
            "explicit_decisions": 2, "applied": 2, "applied_or_stateful": 0,
            "explicit_empty": 0, "missing_after_protocol": 0,
            "missing_after_validation": 0, "missing_after_policy": 0,
            "missing_after_render": 0,
        },
        "chunks": [{
            "render_trace": {"L1": rendered},
            "attempts": [{
                "outcome": "accepted",
                "decisions": [
                    {
                        "source_id": "L1", "beat_id": "beat-1", "layer": "beat",
                        "field": "face", "final_aap_trace": rendered,
                        "status": "applied", "diagnostics": [], "discard_reason": "",
                    },
                    {
                        "source_id": "L1", "beat_id": "beat-1", "layer": "beat",
                        "field": "reactions", "final_aap_trace": rendered,
                        "status": "applied", "diagnostics": [], "discard_reason": "",
                    },
                ],
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    physical = {
        "script_index": 1, "text": "", "is_dialog": False,
        "speaker_slot": 0, "additional_prompt": "",
        "origins": rendered,
        "characters": [{"name": "alice", "faceId": "04", "emoticon": 3}],
    }

    attach_compiled_trace(audit_path, {
        "aap_file": "result.aap",
        "compiled_scripts": [physical],
        "events": [],
        "quality": {"issues": [{
            "code": "compiler_annotation_dropped", "line": 3,
            "message": "@react 目标‘Bob’不在当前镜头，已忽略",
            "severity": "high", "resolution": "ai_repair",
        }]},
    })

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    face, reaction = audit["chunks"][0]["attempts"][0]["decisions"]
    assert face["status"] == "applied"
    assert face["final_aap_trace"] == [physical]
    assert reaction["status"] == "missing_after_render"
    assert reaction["loss_stage"] == "render"
    assert reaction["discard_reason"] == "compiler_annotation_dropped"
    assert reaction["final_aap_trace"] == []
    assert reaction["diagnostics"][0]["line"] == 3
    assert audit["summary"]["applied"] == 1
    assert audit["summary"]["missing_after_render"] == 1


def test_agent_reuses_one_window_only_static_prompt_across_chunks(tmp_path):
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
    assert "SOURCE_SCRIPT" not in provider.static_prompts[0]


def test_scene_plan_mode_uses_planned_window_and_fingerprints_strategy(tmp_path):
    script = tmp_path / "scene.txt"
    source = "Kai: line 1\nKai: line 2\n"
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
    checkpoint_dir = tmp_path / "checkpoints"
    annotate.annotate_script({
        "script": str(script), "out": str(tmp_path / "annotated.txt"),
        "cast": str(cast), "index": str(index), "agent_enabled": True,
        "scene_event_planning": True, "checkpoint_dir": str(checkpoint_dir),
    }, provider_instance=provider)

    assert provider.static_prompts
    assert all("SOURCE_SCRIPT" not in prompt for prompt in provider.static_prompts)
    assert any("场景事件规划器" in prompt for prompt in provider.static_prompts)
    execution_prompts = [
        prompt for prompt in provider.static_prompts
        if "已规划场景的执行合同" in prompt
    ]
    assert execution_prompts
    assert all("九种场景功能" not in prompt for prompt in execution_prompts)
    checkpoint = json.loads(next(checkpoint_dir.rglob("checkpoint.json")).read_text(encoding="utf-8"))
    assert checkpoint["fingerprint"]["model"]["source_context_strategy"] == "planned_window"


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

    tail_marker = "END_OF_CONFIRMED_PLAN"
    plan = [{
        "segment": "转场", "location": "夜间天台", "start": "第1行", "end": "第1行",
        "evidence": "夜色中的天台。", "needs": [{
            "kind": "background", "name": "BG_RoofNight", "status": "builtin",
            "aa_key": "BG_RoofNight",
            "location": "第1行", "reason": "已确认", "confidence": 0.98,
        }], "audit_tail": "证据" * 9000 + tail_marker,
    }]

    annotate.annotate_script({
        "script": str(script), "out": str(tmp_path / "annotated.txt"),
        "cast": str(cast), "index": str(index), "usage_chain": plan,
    }, provider_instance=Provider())

    assert "已确认的场景演出规划" in captured["volatile"]
    assert "BG_RoofNight" in captured["volatile"]
    assert tail_marker in captured["volatile"]
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


def test_response_row_stores_director_metadata_without_rewriting_source():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "A",
        "text": "原文", "raw": "A: 原文",
    }
    row = {"direction": {
        "scene_type": "bond", "scene_function": "emotional_turn",
        "emotion_phase": "waiting", "subtext": "等待对方回应",
        "focus_kind": "listener", "focus_character": "B",
        "visible_characters": ["B"],
        "continuity": {
            "face": "hold", "emo": "none", "act": "none",
            "fx": "none", "bgfx": "none",
        },
    }}
    constraints = {
        "faces_by_id": {"a": set()}, "sym2cn": {}, "ok_emo": set(),
        "ok_act": set(), "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
        "confirmed_bg": set(), "ok_shot": {"A", "B"},
    }
    diagnostics = []

    annotate.apply_annotation_response_row(
        item, row,
        {"A": {"id": "a", "portrait": True}, "B": {"id": "b", "portrait": True}},
        constraints, [], [], diagnostics,
    )

    assert (item["who"], item["text"], item["raw"], item["annotation_id"]) == (
        "A", "原文", "A: 原文", "src-1",
    )
    assert item["_director"]["focus_character"] == "B"
    assert item["_director"]["subtext"] == "等待对方回应"
    assert annotate.render_annotated_items([item]).endswith("A: 原文\n")
    assert diagnostics == []


def test_authored_place_is_not_overwritten_by_model_response():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "A",
        "text": "原文", "raw": "A: 原文",
        "place": "原作者地点",
        "_explicit_direction_fields": ("place",),
    }
    annotate.apply_annotation_response_row(
        item,
        {"place": "模型地点"},
        {"A": {"id": "a", "portrait": True}},
        {
            "faces_by_id": {"a": set()}, "sym2cn": {}, "ok_emo": set(),
            "ok_act": set(), "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
            "confirmed_bg": set(), "ok_shot": {"A"},
        },
        [], [], [],
    )

    assert item["place"] == "原作者地点"


def test_model_audit_labels_authored_field_precedence_as_non_loss():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "A",
        "text": "原文", "raw": "A: 原文",
        "bg": "BG_Authored", "_explicit_direction_fields": ("bg",),
    }
    audit = annotate.build_model_output_audit(
        {
            "chunk-1": {
                "target_ids": ["src-1"],
                "model_attempts": [{
                    "outcome": "accepted", "target_ids": ["src-1"],
                    "response": {"lines": [{
                        "source_id": "src-1", "text_fingerprint": "fp", "bg": "BG_Model",
                    }]},
                    "expanded_response": {"lines": [{
                        "source_id": "src-1", "bg": "BG_Model",
                    }]},
                    "validated_response": {"lines_by_id": {"src-1": {"bg": "BG_Model"}}},
                }],
            },
        },
        [item], [], [],
    )
    decision = audit["chunks"][0]["attempts"][0]["decisions"][0]

    assert decision["status"] == "applied_or_stateful"
    assert decision["discard_reason"] == "authored_source_precedence"
    assert audit["summary"]["missing_after_policy"] == 0


def test_response_row_downgrades_non_displayable_director_focus_with_diagnostic():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "A",
        "text": "原文", "raw": "A: 原文",
    }
    diagnostics = []

    annotate.apply_annotation_response_row(
        item,
        {"direction": {
            "focus_kind": "listener", "focus_character": "Voice",
            "visible_characters": ["Voice"],
        }},
        {"A": {"id": "a", "portrait": True}, "Voice": {"id": "v", "portrait": False}},
        {
            "faces_by_id": {"a": set()}, "sym2cn": {}, "ok_emo": set(),
            "ok_act": set(), "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
            "confirmed_bg": set(), "ok_shot": {"A"},
        },
        [], [], diagnostics,
    )

    assert item["_director"]["focus_character"] == ""
    assert item["_director"]["visible_characters"] == []
    assert any(entry["code"] == "director_non_displayable_character" for entry in diagnostics)


def test_named_offscreen_reaction_target_is_not_serialized_as_a_portrait_layout_target():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "老师",
        "text": "下次再来。", "raw": "老师: 下次再来。",
    }
    annotate.apply_annotation_response_row(
        item,
        {"direction": {
            "focus_character": "凯伊", "reaction_target": "老师",
            "relation_distance": "intimate",
            "visible_characters": ["凯伊"], "positions": {"凯伊": 3},
        }},
        {"凯伊": {"id": "kei", "portrait": True}, "老师": {"id": "sensei", "portrait": False}},
        {
            "faces_by_id": {"kei": set()}, "sym2cn": {}, "ok_emo": set(),
            "ok_act": set(), "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
            "confirmed_bg": set(), "ok_shot": {"凯伊"},
        },
        [], [], [],
    )

    rendered = annotate.render_annotated_items([item])
    assert "老师" in rendered.splitlines()[-1]
    assert '"reaction_target":"老师"' not in rendered
    assert '"relation_distance":"intimate"' not in rendered
    assert '@camera_hold 凯伊' in rendered


def test_listener_focus_renders_persistent_generated_camera_without_rewriting_source():
    item = {
        "kind": "line", "annotation_id": "src-1", "who": "A",
        "text": "原文", "raw": "A: 原文",
        "_director": {
            "visible_characters": ["B"], "focus_kind": "listener",
            "focus_character": "B", "continuity": {"fx": "none"},
        },
    }

    rendered = annotate.render_annotated_items([item])

    assert "@camera_hold B\n" in rendered
    assert rendered.endswith("A: 原文\n")


def test_explicit_fx_end_renders_a_named_clear_command():
    item = {
        "kind": "line", "annotation_id": "src-2", "who": "A",
        "text": "结束", "raw": "A: 结束",
        "_director": {
            "focus_kind": "speaker", "focus_character": "A",
            "visible_characters": ["A"], "continuity": {"fx": "end"},
        },
    }

    assert "@fx A 无" in annotate.annotation_directives(item)


def test_compact_fx_release_renders_command_instead_of_inline_effect():
    item = {
        "kind": "line", "annotation_id": "src-release", "who": "A",
        "text": "回到关系镜头", "raw": "A: 回到关系镜头", "fx": "无",
        "_speaker_has_portrait": True,
        "_director": {
            "focus_kind": "speaker", "focus_character": "A",
            "visible_characters": ["A", "B"], "continuity": {"fx": "end"},
        },
        "_director_intent": {"visible_characters": ["A", "B"]},
    }

    rendered = annotate.render_annotated_items([item])

    assert "@fx A 无\n" in rendered
    assert "A<无>:" not in rendered


def test_omitted_visibility_intent_does_not_render_an_empty_camera():
    item = {
        "kind": "line", "annotation_id": "src-3", "who": "A",
        "text": "继续", "raw": "A: 继续",
        "_director": {"visible_characters": [], "continuity": {"fx": "none"}},
        "_director_intent": {},
    }

    assert not any(line.startswith("@camera") for line in annotate.annotation_directives(item))


def test_cut_directive_precedes_static_target_positions():
    item = {
        "kind": "line", "annotation_id": "src-cut", "who": "A",
        "text": "重构", "raw": "A: 重构",
        "_director": {
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 4},
            "shot_transition": "cut",
            "continuity": {"fx": "none"},
        },
        "_director_intent": {
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 4},
            "shot_transition": "cut",
        },
    }

    assert annotate.annotation_directives(item)[:3] == [
        "@camera_cut A,B", "@move A 1", "@move B 4",
    ]


def test_camera_dedupe_tracks_reveal_before_restoring_a_previous_shot():
    initial = {
        "kind": "line", "annotation_id": "L1", "who": "A", "text": "x", "raw": "A: x",
        "_director": {"visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5}},
        "_director_intent": {"visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5}},
    }
    reveal = annotate._beat_item({
        "beat_id": "beat-reveal", "anchor_id": "L1", "position": "after",
        "who": "C", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "reveal": [{"who": "C", "slot": 3, "side": "left"}],
    })
    restore = annotate._beat_item({
        "beat_id": "beat-restore", "anchor_id": "L1", "position": "after",
        "who": "A", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction",
        "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5},
    })

    rendered = annotate.render_annotated_items([initial, reveal, restore])

    assert rendered.count("@camera_hold A,B\n") == 2
    assert "@reveal C 3 左\n" in rendered


def test_camera_dedupe_tracks_visual_conceal_without_real_exit():
    initial = {
        "kind": "line", "annotation_id": "L1", "who": "A", "text": "x", "raw": "A: x",
        "_director": {"visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5}},
        "_director_intent": {"visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5}},
    }
    conceal = annotate._beat_item({
        "beat_id": "beat-conceal", "anchor_id": "L1", "position": "after",
        "who": "A", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "relationship_turn", "conceal": [{"who": "B", "side": "fade"}],
    })
    restore = annotate._beat_item({
        "beat_id": "beat-restore", "anchor_id": "L1", "position": "after",
        "who": "A", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction",
        "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5},
    })

    rendered = annotate.render_annotated_items([initial, conceal, restore])

    assert "@conceal B\n" in rendered
    assert rendered.count("@camera_hold A,B\n") == 2
    assert "@exit B" not in rendered


def test_camera_dedupe_tracks_move_and_camera_reset():
    initial = {
        "kind": "line", "annotation_id": "L1", "who": "A", "text": "x", "raw": "A: x",
        "_director": {"visible_characters": ["A"], "positions": {"A": 1}},
        "_director_intent": {"visible_characters": ["A"], "positions": {"A": 1}},
    }
    moved = {
        "kind": "line", "annotation_id": "L2", "who": "A", "text": "y", "raw": "A: y",
        "move": 2,
    }
    reset = {
        "kind": "line", "annotation_id": "L3", "who": "A", "text": "z", "raw": "A: z",
        "_camera_reset": True,
    }
    restore = annotate._beat_item({
        "beat_id": "beat-restore", "anchor_id": "L3", "position": "after",
        "who": "A", "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction", "visible_characters": ["A"], "positions": {"A": 1},
    })

    rendered = annotate.render_annotated_items([initial, moved, reset, restore])

    assert rendered.count("@camera_hold A\n") == 2
    assert "@move A 2\n" in rendered
    assert "@camera_hold auto\n" in rendered


def test_dialogue_camera_dedupe_keeps_focus_layout_without_repeating_same_shot():
    first = {
        "kind": "line", "annotation_id": "L1", "who": "A",
        "text": "先看这里。", "raw": "A: 先看这里。",
        "_director": {
            "focus_character": "A",
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "shot_transition": "cut",
            "shot_operation": "switch_group",
        },
        "_director_intent": {
            "focus_character": "A",
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "shot_transition": "cut",
            "shot_operation": "switch_group",
        },
    }
    second = {
        "kind": "line", "annotation_id": "L2", "who": "B",
        "text": "我接着说。", "raw": "B: 我接着说。",
        "_director": {
            "focus_character": "B",
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "shot_transition": "reframe",
            "shot_operation": "replace_center_subject",
        },
        "_director_intent": {
            "focus_character": "B",
            "visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "shot_transition": "reframe",
            "shot_operation": "replace_center_subject",
        },
    }

    rendered, trace = annotate.render_annotated_items_with_trace([first, second])

    assert rendered.count("@camera_cut A,B\n") == 1
    assert "@camera_hold A,B\n" not in rendered
    assert rendered.count("@move A 1\n") == 1
    assert rendered.count("@move B 5\n") == 1
    assert '@layout {"focus_character":"B"}\n' in rendered
    second_commands = {
        row["command"] for row in trace["lines"] if row["source_id"] == "L2"
    }
    assert "layout" in second_commands
    assert second_commands.isdisjoint({"camera", "camera_hold", "camera_cut", "move"})
    assert second["_render_direction_drops"] == [
        {
            "field": "visible_characters",
            "reason": "render_dedup_unchanged_camera_signature",
        },
        {
            "field": "positions",
            "reason": "render_dedup_unchanged_camera_signature",
        },
        {
            "field": "shot_transition",
            "reason": "render_dedup_unchanged_camera_signature",
        },
    ]


def test_dialogue_camera_dedupe_preserves_explicit_same_signature_cut():
    items = []
    for source_id in ("L1", "L2"):
        items.append({
            "kind": "line", "annotation_id": source_id, "who": "A",
            "text": source_id, "raw": f"A: {source_id}",
            "_director": {
                "visible_characters": ["A"],
                "positions": {"A": 3},
                "shot_transition": "cut",
                "shot_operation": "impact_insert",
            },
            "_director_intent": {
                "visible_characters": ["A"],
                "positions": {"A": 3},
                "shot_transition": "cut",
                "shot_operation": "impact_insert",
            },
        })

    rendered = annotate.render_annotated_items(items)

    assert rendered.count("@camera_cut A\n") == 2
    assert rendered.count("@move A 3\n") == 2
    assert not items[1].get("_render_direction_drops")


def test_dialogue_camera_dedupe_removes_same_signature_switch_group_cut():
    items = []
    for source_id in ("L1", "L2"):
        items.append({
            "kind": "line", "annotation_id": source_id, "who": "A",
            "text": source_id, "raw": f"A: {source_id}",
            "_director": {
                "visible_characters": ["A"],
                "positions": {"A": 3},
                "shot_transition": "cut",
                "shot_operation": "switch_group",
            },
            "_director_intent": {
                "visible_characters": ["A"],
                "positions": {"A": 3},
                "shot_transition": "cut",
                "shot_operation": "switch_group",
            },
        })

    rendered, trace = annotate.render_annotated_items_with_trace(items)

    assert rendered.count("@camera_cut A\n") == 1
    assert rendered.count("@move A 3\n") == 1
    assert {row["command"] for row in trace["lines"] if row["source_id"] == "L2"}.isdisjoint(
        {"camera", "camera_hold", "camera_cut", "move"}
    )
    assert items[1]["_render_direction_drops"] == [
        {
            "field": "visible_characters",
            "reason": "render_dedup_unchanged_camera_signature",
        },
        {
            "field": "positions",
            "reason": "render_dedup_unchanged_camera_signature",
        },
        {
            "field": "shot_transition",
            "reason": "render_dedup_unchanged_camera_signature",
        },
    ]


def test_explicit_empty_visibility_intent_survives_row_application():
    item = {
        "kind": "line", "annotation_id": "src-4", "who": "A",
        "text": "画外", "raw": "A: 画外",
    }
    constraints = {
        "faces_by_id": {"a": set()}, "sym2cn": {}, "ok_emo": set(),
        "ok_act": set(), "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
        "confirmed_bg": set(), "ok_shot": {"A"},
    }

    annotate.apply_annotation_response_row(
        item,
        {
            "direction": {"visible_characters": []},
            "direction_intent": {"visible_characters": []},
        },
        {"A": {"id": "a", "portrait": True}}, constraints, [], [],
    )

    assert "@camera_hold -" in annotate.annotation_directives(item)
