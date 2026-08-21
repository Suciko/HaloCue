import copy
import re
from contextlib import contextmanager

import pytest

import llm

from annotation_agent import (
    AnnotationAgentError,
    _compact_g2_previous_lines,
    _compact_g2_repair_issues,
    _g2_face_change_token_options,
    _interleaved_director_events,
    _introduced_g2_repair_regressions,
    _merge_g2_repair,
    _merge_director_rows,
    _strip_nonportrait_line_resources,
    apply_review_patches,
    build_review_windows,
    estimate_chunk_output_budget,
    grow_chunk_output_budget,
    _resolve_response_face_tokens,
    run_annotation_agent,
)
from annotation_protocol import validate_review_patches
from annotation_chunks import assign_annotation_ids
from annotation_memory import AnnotationCheckpointStore, build_run_fingerprint
from direction_quality import validate_execution_quality


FIELDS = ("face", "emo", "act", "fx", "se", "bg", "bg_request", "place", "bgfx", "trans", "shot")


def test_chunk_output_budget_uses_configured_maximum_without_local_compression():
    compact = estimate_chunk_output_budget(
        20, compact=True, reasoning_mode="balanced", maximum=384_000,
    )
    full = estimate_chunk_output_budget(
        20, compact=False, reasoning_mode="balanced", maximum=384_000,
    )
    deep = estimate_chunk_output_budget(
        20, compact=True, reasoning_mode="deep", maximum=384_000,
    )

    assert compact == 384_000
    assert full == 384_000
    assert deep == 384_000


def test_chunk_output_budget_respects_ceiling_and_can_grow_to_auto_ceiling():
    assert estimate_chunk_output_budget(
        20, compact=False, reasoning_mode="balanced", maximum=16_000,
    ) == 16_000
    assert grow_chunk_output_budget(16_000, 384_000) == 32_000
    assert grow_chunk_output_budget(256_000, 384_000) == 384_000
    assert grow_chunk_output_budget(384_000, 384_000) is None


def make_items(count, separator_at=None):
    items = []
    for index in range(count):
        if separator_at is not None and index == separator_at:
            items.append({"kind": "other", "raw": "---"})
        items.append({
            "kind": "line", "line_no": index + 1, "split_index": 0,
            "who": "凯伊", "text": f"第{index + 1}句。", "raw": f"凯伊: 第{index + 1}句。",
        })
    return assign_annotation_ids(items)


def empty_row(source_id, fingerprint):
    row = {name: "" for name in FIELDS}
    row.update({"source_id": source_id, "text_fingerprint": fingerprint, "shake": False, "move": 0})
    return row


def test_after_beat_camera_state_becomes_the_next_chunk_memory():
    targets = make_items(1)
    source_id = targets[0]["annotation_id"]
    row = empty_row(source_id, targets[0]["text_fingerprint"])
    row["direction"] = {
        "visible_characters": ["凯伊"],
        "positions": {"凯伊": 3},
        "shot_transition": "cut",
    }
    row["direction_intent"] = copy.deepcopy(row["direction"])
    beats = [{
        "anchor_id": source_id, "position": "after", "who": "爱丽丝",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction",
        "visible_characters": ["爱丽丝", "绿"],
        "positions": {"爱丽丝": 1, "绿": 4},
        "shot_transition": "cut",
    }]
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "爱丽丝": {"id": "aris", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }
    constraints = {
        "faces_by_id": {}, "ok_emo": set(), "ok_act": set(), "ok_fx": set(),
        "ok_se": set(), "ok_bg": set(), "ok_bgfx": set(),
    }

    events = _interleaved_director_events(
        {source_id: row}, targets, beats, cast, constraints,
    )
    memory = _merge_director_rows({}, events, {source_id: "凯伊"})

    assert memory["direction"]["shot_visible_characters"] == ["爱丽丝", "绿"]
    assert memory["direction"]["positions"] == {"爱丽丝": 1, "绿": 4}
    assert memory["direction"]["shot_transition"] == "cut"
    assert memory["direction"]["last_performance_node"]["silent"] is True
    assert memory["direction"]["last_performance_node"]["visible_characters"] == ["爱丽丝", "绿"]


def test_line_move_and_reveal_update_next_chunk_spatial_memory_without_direction_patch():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
        },
    }
    rows = [{
        "source_id": "L1", "direction": {}, "direction_intent": {},
        "move": 2, "reveal": "left", "_speaker": "A",
    }]

    updated = _merge_director_rows(memory, rows)

    assert updated["direction"]["shot_visible_characters"] == ["A", "B"]
    assert updated["direction"]["positions"] == {"A": 2, "B": 5}
    assert updated["direction"]["scene_presence"]["A"] == "present"


def test_explicit_camera_members_replace_stale_shot_group_even_without_operation():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "shot_group": {
                "group_id": "old", "members": ["A", "B"],
                "focus_owner": "B", "status": "active", "spatial_mode": "stable",
            },
        },
    }
    rows = [{
        "source_id": "L1", "_speaker": "C",
        "direction": {"visible_characters": ["C"]},
        "direction_intent": {"visible_characters": ["C"]},
    }]

    updated = _merge_director_rows(memory, rows)

    assert updated["direction"]["shot_visible_characters"] == ["C"]
    assert updated["direction"]["shot_group"]["members"] == ["C"]
    assert updated["direction"]["shot_group"]["focus_owner"] == "C"


def test_beat_entry_exit_slots_and_secondary_reactions_update_next_chunk_memory():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
        },
    }
    rows = [{
        "source_id": "beat-1", "direction": {}, "direction_intent": {},
        "_speaker": "A", "face": "01", "emo": "", "act": "",
        "_reveal": ["C"], "_enter": [], "_exit": ["B"],
        "_position_updates": {"C": 4},
        "_reactions": [{"who": "C", "face": "03", "emo": "疑问", "act": "stiff"}],
    }]

    updated = _merge_director_rows(memory, rows)
    direction = updated["direction"]

    assert direction["shot_visible_characters"] == ["A", "C"]
    assert direction["positions"] == {"A": 1, "C": 4}
    assert direction["scene_presence"] == {"C": "present", "B": "absent"}
    assert direction["last_faces"] == {"A": "01", "C": "03"}
    assert direction["recent_emoticons"] == ["疑问"]
    assert direction["recent_actions"] == ["stiff"]
    assert direction["last_performance_node"]["source_id"] == "beat-1"
    assert direction["last_performance_node"]["reactions"] == [
        {"who": "C", "face": "03", "emo": "疑问", "act": "stiff"},
    ]


def test_beat_conceal_removes_portrait_but_preserves_scene_presence():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "scene_presence": {"A": "present", "B": "present"},
            "shot_group": {
                "group_id": "pair", "members": ["A", "B"],
                "focus_owner": "B", "status": "active", "spatial_mode": "stable",
            },
        },
    }
    rows = [{
        "source_id": "beat-conceal", "direction": {}, "direction_intent": {},
        "_speaker": "A", "face": "", "emo": "", "act": "",
        "_reveal": [], "_conceal": ["B"], "_enter": [], "_exit": [],
        "_position_updates": {}, "_reactions": [],
    }]

    updated = _merge_director_rows(memory, rows)
    direction = updated["direction"]

    assert direction["shot_visible_characters"] == ["A"]
    assert direction["positions"] == {"A": 1}
    assert direction["scene_presence"]["B"] == "present"
    assert direction["shot_group"]["members"] == ["A"]
    assert direction["shot_group"]["focus_owner"] == ""


class RecordingProvider:
    name = "fake"
    model = "fake"

    def __init__(self, fail_after=None, omit_last_calls=0):
        self.fail_after = fail_after
        self.omit_last_calls = omit_last_calls
        self.calls = 0
        self.requests = []

    def complete_json(self, static, volatile, user, schema):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("forced failure")
        ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
        fingerprints = dict(re.findall(r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user))
        self.requests.append({"volatile": volatile, "user": user, "target_ids": ids})
        rows = [empty_row(source_id, fingerprints[source_id]) for source_id in ids]
        if self.calls <= self.omit_last_calls and rows:
            rows.pop()
        delta = {}
        events = []
        if self.calls == 1 and rows:
            delta = {"background": "BG_Street", "visible_characters": ["凯伊"]}
            first_id = ids[0]
            text_match = re.search(rf"\[TARGET {re.escape(first_id)}\] [^:]+: ([^|]+) \|", user)
            evidence = text_match.group(1).strip() if text_match else ""
            events = [{
                "kind": "relationship_callback", "participants": ["凯伊"],
                "keywords": ["第1句"], "summary": "记住第一句", "source_ids": [first_id],
                "evidence": evidence, "importance": .9, "status": "open",
            }]
        return {"lines": rows, "state_delta": delta, "memory_events": events}

    def report(self):
        return f"fake calls={self.calls}"


def fixture(
    tmp_path, provider, count=70, cancelled=None, progress=None,
    model_activity=None, constraints_override=None, **agent_options,
):
    items = make_items(count)
    constraints = {
        "ok_bg": {"BG_Street"}, "confirmed_bg": set(),
        "faces_by_id": {"kei": {"00"}}, "sym2cn": {},
        "ok_emo": set(), "ok_act": set(), "ok_se": set(),
        "ok_shot": {"凯伊"},
    }
    if constraints_override:
        constraints.update(constraints_override)
    story_type = str(agent_options.get("story_type") or "auto")
    fingerprint = build_run_fingerprint(
        "\n".join(item.get("raw", "") for item in items), {"凯伊": {"id": "kei"}},
        {"bg": ["BG_Street"]}, "v1", 1, "v1",
        {"provider": "fake", "model": "fake", "max_tokens": 16000},
        story_type=story_type, director_version="stateful-v1",
    )
    return run_annotation_agent(
        items, provider=provider, static_system="rules", cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints=constraints, usage_chain=[], checkpoint_store=AnnotationCheckpointStore(tmp_path),
        run_fingerprint=fingerprint, cancelled=cancelled, progress=progress,
        model_activity=model_activity,
        **agent_options,
    )


def _offscreen_fixture(tmp_path, provider):
    """Run one compact chunk whose speaker is explicitly not portrait-backed."""
    items = assign_annotation_ids([{
        "kind": "line", "line_no": 1, "split_index": 0,
        "who": "老师", "text": "先确认一下。", "raw": "老师: 先确认一下。",
    }])
    cast = {"老师": {"id": "teacher", "portrait": False, "narrator": False}}
    constraints = {
        "faces_by_id": {"teacher": set()}, "sym2cn": {},
        "ok_emo": {"惊疑"}, "ok_act": {"stiff"}, "ok_fx": {"特写"},
        "ok_se": set(), "ok_bg": set(), "ok_bgfx": set(), "ok_shot": set(),
    }
    fingerprint = build_run_fingerprint(
        items[0]["raw"], cast, {"bg": []}, "v1", 1, "v1",
        {"provider": "fake", "model": "fake", "max_tokens": 16000},
        story_type="auto", director_version="stateful-v1",
    )
    return run_annotation_agent(
        items, provider=provider, static_system="rules", cast=cast,
        constraints=constraints, usage_chain=[],
        checkpoint_store=AnnotationCheckpointStore(tmp_path),
        run_fingerprint=fingerprint,
    )


def test_compact_g2_clears_resources_on_an_explicitly_nonportrait_speaker(tmp_path):
    class TeacherResourceProvider:
        name = "teacher-resource"
        model = "teacher-resource"
        supports_compact_annotation = True

        def __init__(self):
            self.calls = 0

        def complete_json(self, _static, _volatile, user, _schema):
            self.calls += 1
            return {
                "lines": [{
                    "i": 1, "face": "[Emo:意外]", "emo": "惊疑",
                    "act": "stiff", "fx": "特写",
                }],
                "state_delta": {}, "memory_events": [],
            }

    provider = TeacherResourceProvider()
    result = _offscreen_fixture(tmp_path, provider)

    assert provider.calls == 1
    row = next(iter(result["rows_by_id"].values()))
    assert all(not row.get(field) for field in ("face", "emo", "act", "fx"))
    attempt = next(iter(result["chunk_outputs"].values()))["model_attempts"][0]
    assert attempt["response"]["lines"][0]["face"] == "[Emo:意外]"
    assert len(attempt["protocol_repairs"]) == 4
    assert {repair["field"] for repair in attempt["protocol_repairs"]} == {
        "face", "emo", "act", "fx",
    }


def test_g2_repair_clears_nonportrait_resources_again_after_a_structural_retry(tmp_path):
    class TeacherRepairProvider:
        name = "teacher-repair"
        model = "teacher-repair"
        supports_compact_annotation = True

        def __init__(self):
            self.calls = 0

        def complete_json(self, _static, _volatile, user, _schema):
            self.calls += 1
            row = {
                "i": 1, "face": "[Emo:意外]", "emo": "惊疑",
                "act": "stiff", "fx": "特写",
            }
            if self.calls == 1:
                row.update({
                    "reveal": "left",
                    "shot_transition": "cut",
                    "visible_characters": [],
                    "positions": {},
                })
            return {"lines": [row], "state_delta": {}, "memory_events": []}

    provider = TeacherRepairProvider()
    result = _offscreen_fixture(tmp_path, provider)

    assert provider.calls == 2
    row = next(iter(result["rows_by_id"].values()))
    assert all(not row.get(field) for field in ("face", "emo", "act", "fx"))
    attempts = next(iter(result["chunk_outputs"].values()))["model_attempts"]
    assert attempts[0]["outcome"] == "rejected"
    assert attempts[1]["outcome"] == "accepted"
    assert all(len(attempt.get("protocol_repairs") or []) == 4 for attempt in attempts)


def test_checkpoint_reuse_reapplies_nonportrait_resource_boundary(tmp_path):
    first_provider = type("FirstProvider", (), {
        "name": "checkpoint-teacher",
        "model": "checkpoint-teacher",
        "supports_compact_annotation": True,
        "__init__": lambda self: setattr(self, "calls", 0),
        "complete_json": lambda self, _static, _volatile, _user, _schema: (
            setattr(self, "calls", self.calls + 1) or {
                "lines": [{"i": 1, "face": "[Emo:意外]", "emo": "惊疑", "act": "stiff", "fx": "特写"}],
                "state_delta": {}, "memory_events": [],
            }
        ),
    })()
    first = _offscreen_fixture(tmp_path, first_provider)
    assert first_provider.calls == 1

    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    store = AnnotationCheckpointStore(tmp_path)
    saved = store.load(checkpoint_path.parent.name)
    chunk_id = saved["chunk_order"][0]
    source_id = next(iter(saved["chunk_outputs"][chunk_id]["lines_by_id"]))
    saved["chunk_outputs"][chunk_id]["lines_by_id"][source_id].update({
        "face": "99", "emo": "惊疑", "act": "stiff", "fx": "特写",
    })
    store.commit(checkpoint_path.parent.name, saved)

    second_provider = type("SecondProvider", (), {
        "name": "checkpoint-teacher",
        "model": "checkpoint-teacher",
        "supports_compact_annotation": True,
        "__init__": lambda self: setattr(self, "calls", 0),
        "complete_json": lambda self, *_args: setattr(self, "calls", self.calls + 1),
    })()
    resumed = _offscreen_fixture(tmp_path, second_provider)

    assert second_provider.calls == 0
    row = next(iter(resumed["rows_by_id"].values()))
    assert all(not row.get(field) for field in ("face", "emo", "act", "fx"))
    output = next(iter(resumed["chunk_outputs"].values()))
    assert all(
        not output["lines_by_id"][source_id].get(field)
        for field in ("face", "emo", "act", "fx")
    )
    assert any(
        item.get("stage") == "checkpoint_reuse"
        for item in resumed["diagnostics"]
        if isinstance(item, dict)
    )


def test_nonportrait_resource_helper_preserves_portrait_speaker_resources():
    response = {"lines": [{
        "source_id": "L1", "face": "[Emo:意外]", "emo": "惊疑",
        "act": "stiff", "fx": "特写",
    }]}
    targets = [{"annotation_id": "L1", "who": "凯伊"}]
    repairs = _strip_nonportrait_line_resources(
        response, targets,
        {"凯伊": {"id": "kei", "portrait": True, "narrator": False}},
    )

    assert repairs == []
    assert response["lines"][0]["face"] == "[Emo:意外]"


def test_agent_carries_state_and_event_into_next_chunk(tmp_path):
    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70)
    assert provider.calls == 2
    assert "BG_Street" in provider.requests[1]["volatile"]
    assert "记住第一句" in provider.requests[1]["volatile"]
    assert result["completed_chunks"] == 2
    assert len(result["rows_by_id"]) == 70


def test_protocol_retry_receives_previous_response_and_preserves_directing_contract(tmp_path):
    class ProtocolRetryProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["lines"][0]["reveal"] = "left"
                response["lines"][0]["direction"] = {
                    "shot_transition": "cut",
                    "visible_characters": ["凯伊"],
                    "positions": {"凯伊": 3},
                }
            return response

    provider = ProtocolRetryProvider()
    result = fixture(tmp_path, provider, count=1)

    assert result["completed_chunks"] == 1
    assert provider.calls == 2
    retry = provider.requests[1]["user"]
    assert "G2_EXECUTION_REPAIR" in retry
    assert "PREVIOUS_RESPONSE" in retry
    assert "不是重新导演" in retry
    assert '"reveal":"left"' in retry
    assert '"shot_transition":"cut"' in retry


def test_agent_retries_face_outside_backend_shortlist(tmp_path):
    class WrongFaceOnceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["face"] = (
                "99" if self.calls == 1 else "[Emo:平静回应]"
            )
            return response

    provider = WrongFaceOnceProvider()
    records = [{
        "id": "00", "semantic_cn": "平静回应", "beat_fit": ["dialogue"],
        "delivery_fit": ["normal_speech"], "usage_frequency": "common",
        "backend_selection_ready": True,
    }, {
        "id": "99", "semantic_cn": "未复核特殊人格脸",
        "backend_selection_ready": False,
    }]
    result = fixture(
        tmp_path,
        provider,
        count=1,
        constraints_override={
            "faces_by_id": {"kei": {"00", "99"}},
            "face_records_by_id": {"kei": records},
        },
    )

    assert provider.calls == 2
    assert next(iter(result["rows_by_id"].values()))["face"] == "00"


def test_agent_rejects_a_raw_face_id_even_when_it_is_in_the_shortlist(tmp_path):
    class RawIdOnceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["face"] = (
                "00" if self.calls == 1 else "[Emo:平静回应]"
            )
            return response

    provider = RawIdOnceProvider()
    result = fixture(
        tmp_path,
        provider,
        count=1,
        constraints_override={
            "face_records_by_id": {"kei": [{
                "id": "00", "semantic_cn": "平静回应",
                "beat_fit": ["dialogue"], "delivery_fit": ["normal_speech"],
                "usage_frequency": "common", "backend_selection_ready": True,
            }]},
        },
    )

    assert provider.calls == 2
    assert next(iter(result["rows_by_id"].values()))["face"] == "00"
    assert "[Emo:平静回应]" in provider.requests[1]["user"]
    assert "可用：00" not in provider.requests[1]["user"]


def test_agent_accepts_a_valid_character_face_outside_the_ranked_target_subset(tmp_path):
    class ValidButNotTopRankedFaceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["face"] = "[Emo:沉稳剖析]"
            return response

    provider = ValidButNotTopRankedFaceProvider()
    records = [
        {
            "id": "00", "semantic_cn": "平静回应", "beat_fit": ["dialogue"],
            "delivery_fit": ["normal_speech"], "usage_frequency": "common",
            "backend_selection_ready": True,
        },
        {
            "id": "01", "semantic_cn": "日常说明", "beat_fit": ["dialogue"],
            "delivery_fit": ["normal_speech"], "usage_frequency": "common",
            "backend_selection_ready": True,
        },
        {
            "id": "02", "semantic_cn": "温和交流", "beat_fit": ["dialogue"],
            "delivery_fit": ["normal_speech"], "usage_frequency": "common",
            "backend_selection_ready": True,
        },
        {
            "id": "03", "semantic_cn": "轻松应答", "beat_fit": ["dialogue"],
            "delivery_fit": ["normal_speech"], "usage_frequency": "common",
            "backend_selection_ready": True,
        },
        {
            "id": "05", "semantic_cn": "沉稳剖析", "beat_fit": ["exposition"],
            "semantic_tags": ["serious"], "expression_class": "special",
            "backend_selection_ready": True,
        },
    ]
    result = fixture(
        tmp_path,
        provider,
        count=1,
        constraints_override={
            "faces_by_id": {"kei": {record["id"] for record in records}},
            "face_records_by_id": {"kei": records},
        },
    )

    assert provider.calls == 1
    assert next(iter(result["rows_by_id"].values()))["face"] == "05"


def test_compact_agent_resolves_semantic_face_token(tmp_path):
    class CompactSemanticProvider:
        name = "compact-semantic"
        model = "compact-semantic"
        supports_compact_annotation = True

        def __init__(self):
            self.calls = 0

        def complete_json(self, _static, _volatile, _user, _schema):
            self.calls += 1
            return {
                "lines": [{"i": 1, "face": "[Emo:平静回应]"}],
                "state_delta": {}, "memory_events": [],
            }

    result = fixture(
        tmp_path,
        CompactSemanticProvider(),
        count=1,
        constraints_override={
            "face_records_by_id": {"kei": [{
                "id": "00", "semantic_cn": "平静回应",
                "beat_fit": ["dialogue"], "delivery_fit": ["normal_speech"],
                "usage_frequency": "common", "backend_selection_ready": True,
            }]},
        },
    )

    assert next(iter(result["rows_by_id"].values()))["face"] == "00"


def test_agent_resolves_silent_beat_semantic_token_by_anchor_and_character(tmp_path):
    class PlannedSilentProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            if "场景事件规划器" in static:
                self.calls += 1
                return {"events": [{
                    "event_id": "pause", "start_i": 1, "end_i": 1,
                    "kind": "decision", "stimulus": "需要作出决定",
                    "outcome": "角色认真思考后回应",
                    "phase_order": ["decision_pause"],
                    "shot_groups": [["凯伊"]], "focus_turns": ["凯伊"],
                    "silent_beats": [{
                        "anchor_i": 1, "position": "before",
                        "phase": "decision_pause", "purpose": "思考后再回答",
                        "participants": ["凯伊"], "sound_motivated": False,
                    }],
                    "continuity_goal": "保持单人镜头", "peak_character": "凯伊",
                    "peak_reason": "决定前停顿",
                }]}
            response = super().complete_json(static, volatile, user, schema)
            source_id = response["lines"][0]["source_id"]
            response["beats"] = [{
                "anchor_id": source_id, "position": "before", "who": "凯伊",
                "face": "[Emo:认真思考]", "emo": "", "act": "",
                "wait_ms": 700, "reason": "decision_pause",
            }]
            return response

    provider = PlannedSilentProvider()
    result = fixture(
        tmp_path,
        provider,
        count=1,
        scene_event_planning=True,
        constraints_override={
            "face_records_by_id": {"kei": [{
                "id": "00", "semantic_cn": "认真思考｜决定前停顿",
                "beat_fit": ["hesitation", "listening", "reaction"],
                "delivery_fit": ["silent_reaction"],
                "semantic_tags": ["serious"], "usage_frequency": "common",
                "backend_selection_ready": True,
            }]},
            "faces_by_id": {"kei": {"00"}},
        },
    )

    assert result["beats"][0]["face"] == "00"
    assert "SILENT_REACTION_SHORTLIST_BY_TARGET" in provider.requests[0]["volatile"]
    assert "[Emo:认真思考]" in provider.requests[0]["volatile"]


def test_unplanned_silent_beat_uses_unambiguous_character_face_token():
    response = {
        "lines": [],
        "beats": [{
            "anchor_id": "src-1",
            "position": "after",
            "who": "凯伊",
            "face": "[Emo:意外]",
            "emo": "",
            "act": "",
        }],
    }

    _resolve_response_face_tokens(
        response,
        face_tokens_by_target={},
        silent_tokens_by_beat={},
        face_tokens_by_character={"凯伊": {"[Emo:意外]": "17"}},
    )

    assert response["beats"][0]["face"] == "17"


def test_scene_event_planner_repairs_one_invalid_v2_plan_before_execution(tmp_path):
    class RepairingPlanProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.plan_calls = 0

        def complete_json(self, static, volatile, user, schema):
            if "场景事件规划器" not in static:
                return super().complete_json(static, volatile, user, schema)
            self.calls += 1
            self.plan_calls += 1
            framing = "medium" if self.plan_calls == 1 else "close"
            carriers = (
                ["camera_change"]
                if self.plan_calls == 1
                else ["camera_change", "face_change"]
            )
            return {"events": [{
                "event_id": "impact", "start_i": 1, "end_i": 1,
                "kind": "group_escalation", "stimulus": "语气升级",
                "outcome": "个人爆点完成", "phase_order": ["action"],
                "shot_groups": [{
                    "group_id": "solo", "anchor_i": 1, "members": ["凯伊"],
                    "focus": "凯伊", "framing": framing, "operation": "switch",
                    "cut_motivation": "个人爆点", "purpose": "承接升级",
                }],
                "focus_turns": ["凯伊"],
                "performance_intents": [{
                    "anchor_i": 1, "position": "on", "subjects": ["凯伊"],
                    "carriers": carriers, "purpose": "突出升级",
                }],
                "face_arcs": [], "silent_beats": [],
                "peaks": [{
                    "subject": "凯伊", "peak_type": "solo_emphasis",
                    "peak_i": 1, "position": "on", "visual_intent": "个人情绪升级",
                    "release_i": 0, "release_position": "scene_end",
                    "why": "在本句完成升级",
                }],
                "continuity_goal": "在场景末尾释放",
            }]}

    provider = RepairingPlanProvider()
    result = fixture(
        tmp_path, provider, count=1, scene_event_planning=True,
    )

    scene = result["director_plan"]["scenes"][0]
    assert provider.plan_calls == 2
    assert scene["event_plan_source"] == "model_repaired"
    assert scene["event_plan_quality"]["result"] == "pass"
    assert scene["event_plan"]["events"][0]["shot_groups"][0]["framing"] == "close"


def test_g2_does_not_repair_only_to_satisfy_a_planner_silent_beat(tmp_path):
    class G2RepairProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.g2_calls = 0

        def complete_json(self, static, volatile, user, schema):
            if "场景事件规划器" in static:
                self.calls += 1
                return {"events": [{
                    "event_id": "impact", "start_i": 1, "end_i": 1,
                    "kind": "group_escalation", "stimulus": "语气升级",
                    "outcome": "个人爆点后停住", "phase_order": ["action", "decision_pause"],
                    "shot_groups": [{
                        "group_id": "solo", "anchor_i": 1, "members": ["凯伊"],
                        "focus": "凯伊", "framing": "close", "operation": "switch",
                        "cut_motivation": "个人爆点", "purpose": "突出主体",
                    }],
                    "focus_turns": ["凯伊"],
                    "performance_intents": [{
                        "anchor_i": 1, "position": "on", "subjects": ["凯伊"],
                        "carriers": ["camera_change", "face_change"],
                        "purpose": "建立单人近景并换成峰值表情",
                    }],
                    "face_arcs": [], "silent_beats": [{
                        "anchor_i": 1, "position": "after", "phase": "decision_pause",
                        "purpose": "爆点后停住", "participants": ["凯伊"],
                        "sound_motivated": False,
                        "carrier_requirement": {
                            "any_of": ["pose_hold"], "require_observable_change": False,
                        },
                    }],
                    "peaks": [{
                        "subject": "凯伊", "peak_type": "solo_emphasis",
                        "peak_i": 1, "position": "on", "visual_intent": "个人爆点",
                        "release_i": 0, "release_position": "scene_end", "why": "收束",
                    }],
                    "continuity_goal": "场景末释放",
                }]}
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["fx"] = "特写"
            response["lines"][0]["direction"] = {
                "visible_characters": ["凯伊"], "positions": {"凯伊": 3},
                "shot_transition": "cut", "shot_operation": "impact_insert",
            }
            if "G2_EXECUTION_REPAIR" in user:
                self.g2_calls += 1
                source_id = response["lines"][0]["source_id"]
                response["lines"][0]["face"] = "05"
                response["beats"] = [{
                    "anchor_id": source_id, "position": "after", "who": "凯伊",
                    "face": "", "emo": "", "act": "", "wait_ms": 500,
                    "reason": "decision_pause", "visible_characters": ["凯伊"],
                    "positions": {"凯伊": 3},
                }]
            return response

    provider = G2RepairProvider()
    result = fixture(
        tmp_path, provider, count=1, scene_event_planning=True,
    )

    quality = result["director_plan"]["scenes"][0]["execution_quality"][0]
    assert provider.g2_calls == 0
    assert quality["repaired_once"] is False
    assert quality["result"] == "fail"
    assert "missing_planned_silent_phase" in {
        issue["code"] for issue in quality["issues"]
    }
    assert result["rows_by_id"][next(iter(result["rows_by_id"]))]["direction"]["visible_characters"] == ["凯伊"]


def test_checkpoint_replays_only_g2_repair_when_repair_response_is_refreshed(
    tmp_path, monkeypatch,
):
    class RefreshableG2Provider(RecordingProvider):
        def __init__(self, refresh=False):
            super().__init__()
            self.refresh = refresh
            self.g2_calls = 0

        def checkpoint_replay_mode(self, _saved_output):
            return "g2_repair" if self.refresh else "reuse"

        def complete_json(self, static, volatile, user, schema):
            if "场景事件规划器" in static:
                self.calls += 1
                return {"events": []}
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["direction"] = {
                "visible_characters": ["凯伊"], "positions": {"凯伊": 3},
                "shot_transition": "cut", "shot_operation": "impact_insert",
            }
            if "G2_EXECUTION_REPAIR" in user:
                self.g2_calls += 1
                response["lines"][0]["face"] = "05"
            else:
                response["lines"][0]["face"] = "00"
            return response

    def forced_quality(_plan, targets, lines, _beats, **_kwargs):
        source_id = str(targets[0].get("annotation_id") or "")
        face = str((lines.get(source_id) or {}).get("face") or "")
        if face == "05":
            return {"result": "pass", "issues": []}
        return {"result": "fail", "issues": [{
            "code": "forced_refresh_probe", "severity": "high",
            "resolution": "ai_repair", "anchor_id": source_id,
            "detail": "test repair refresh",
        }]}

    monkeypatch.setattr("annotation_agent.validate_execution_quality", forced_quality)

    first = RefreshableG2Provider()
    fixture(tmp_path, first, count=1, scene_event_planning=True)

    resumed = RefreshableG2Provider(refresh=True)
    result = fixture(tmp_path, resumed, count=1, scene_event_planning=True)

    assert resumed.g2_calls == 1
    assert resumed.calls == 1
    assert resumed.requests[0]["user"].find("G2_EXECUTION_REPAIR") >= 0
    assert any(
        item.get("code") == "checkpoint_g2_repair_refresh"
        for item in result["diagnostics"]
    )


def test_g2_repair_replaces_memory_events_for_repaired_sources():
    original = {
        "lines_by_id": {"src-a": {"face": "01"}, "src-b": {"face": "02"}},
        "beats": [],
        "state_delta": {},
        "memory_events": [
            {"event_id": "old-a", "source_ids": ["src-a"]},
            {"event_id": "old-b", "source_ids": ["src-b"]},
            {"event_id": "old-shared", "source_ids": ["src-a", "src-b"]},
        ],
        "diagnostics": [],
    }
    repaired = {
        "lines_by_id": {"src-a": {"face": "05"}},
        "beats": [],
        "state_delta": {},
        "memory_events": [{"event_id": "new-a", "source_ids": ["src-a"]}],
        "diagnostics": [],
    }

    merged = _merge_g2_repair(original, repaired, {"src-a"})

    assert merged["lines_by_id"] == {
        "src-a": {"face": "05"}, "src-b": {"face": "02"},
    }
    assert [event["event_id"] for event in merged["memory_events"]] == [
        "old-b", "new-a",
    ]


def test_g2_camera_repair_with_empty_memory_patch_preserves_original_events():
    original = {
        "lines_by_id": {"src-a": {"face": "01"}},
        "beats": [], "state_delta": {},
        "memory_events": [{
            "kind": "object_status", "source_ids": ["src-a", "src-b"],
            "summary": "手把仍然丢失",
        }],
        "diagnostics": [],
    }
    repaired = {
        "lines_by_id": {"src-a": {
            "source_id": "src-a", "reveal": "fade",
            "annotation_intent_fields": ["reveal"],
        }},
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }

    merged = _merge_g2_repair(original, repaired, {"src-a"})

    assert merged["memory_events"] == original["memory_events"]


def test_g2_repair_regression_guard_detects_new_downstream_lifecycle_issue():
    before = {"result": "fail", "issues": [{
        "code": "reframe_adds_character_without_reveal",
        "severity": "high", "anchor_id": "L1",
    }]}
    after = {"result": "fail", "issues": [
        {
            "code": "reframe_adds_character_without_reveal",
            "severity": "high", "anchor_id": "L1",
        },
        {
            "code": "reframe_adds_character_without_reveal",
            "severity": "high", "anchor_id": "L3",
            "missing_reveal": ["C"],
        },
        {
            "code": "performance_intent_unfulfilled",
            "severity": "high", "anchor_id": "L2",
        },
    ]}

    regressions = _introduced_g2_repair_regressions(before, after)

    assert [(issue["code"], issue["anchor_id"]) for issue in regressions] == [
        ("reframe_adds_character_without_reveal", "L3"),
    ]


def test_g2_repair_regression_guard_detects_new_multi_character_closeup():
    before = {"result": "fail", "issues": [{
        "code": "forced_repair_probe", "severity": "high", "anchor_id": "L1",
    }]}
    after = {"result": "fail", "issues": [{
        "code": "closeup_with_multiple_characters", "severity": "high",
        "anchor_id": "L3", "visible": ["A", "B"],
    }]}

    regressions = _introduced_g2_repair_regressions(before, after)

    assert [(issue["code"], issue["anchor_id"]) for issue in regressions] == [
        ("closeup_with_multiple_characters", "L3"),
    ]


def test_g2_repair_regression_guard_uses_real_camera_timeline_for_missing_reveal():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "scene_presence": {"A": "present", "B": "present", "C": "present"},
        },
    }
    cast = {
        "A": {"portrait": True},
        "B": {"portrait": True},
        "C": {"portrait": True},
    }
    targets = [
        {"annotation_id": "L2", "who": "B", "text": "two"},
        {"annotation_id": "L3", "who": "C", "text": "three"},
    ]
    l3_direction = {
        "visible_characters": ["A", "C", "B"],
        "positions": {"A": 1, "C": 3, "B": 5},
        "shot_transition": "reframe", "shot_operation": "expand_group",
    }
    before = {
        "lines_by_id": {
            "L2": {
                "source_id": "L2", "fx": "特写", "direction": {},
                "direction_intent": {}, "annotation_intent_fields": ["fx"],
            },
            "L3": {
                "source_id": "L3", "reveal": "fade",
                "direction": copy.deepcopy(l3_direction),
                "direction_intent": copy.deepcopy(l3_direction),
                "annotation_intent_fields": ["reveal"],
            },
        },
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }
    repaired_direction = {
        "visible_characters": ["B"], "positions": {"B": 3},
        "shot_transition": "cut", "shot_operation": "switch_group",
    }
    repair = {
        "lines_by_id": {"L2": {
            "source_id": "L2",
            "direction": copy.deepcopy(repaired_direction),
            "direction_intent": copy.deepcopy(repaired_direction),
            "annotation_intent_fields": [],
        }},
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }

    before_report = validate_execution_quality(
        None, targets, before["lines_by_id"], before["beats"],
        memory=memory, cast=cast, constraints={},
    )
    candidate = _merge_g2_repair(before, repair, {"L2"})
    candidate_report = validate_execution_quality(
        None, targets, candidate["lines_by_id"], candidate["beats"],
        memory=memory, cast=cast, constraints={},
    )
    regressions = _introduced_g2_repair_regressions(
        before_report, candidate_report,
    )

    assert not any(
        issue["code"] == "reframe_adds_character_without_reveal"
        for issue in before_report["issues"]
    )
    assert candidate["lines_by_id"]["L3"] == before["lines_by_id"]["L3"]
    assert [(issue["anchor_id"], issue["missing_reveal"]) for issue in regressions] == [
        ("L3", ["A"]),
    ]


def test_g2_repair_regression_guard_uses_real_camera_timeline_for_missing_conceal():
    memory = {
        "direction": {
            "shot_visible_characters": ["A", "B"],
            "positions": {"A": 1, "B": 5},
            "scene_presence": {"A": "present", "B": "present", "C": "present"},
        },
    }
    cast = {
        "A": {"portrait": True},
        "B": {"portrait": True},
        "C": {"portrait": True},
    }
    targets = [
        {"annotation_id": "L2", "who": "B", "text": "two"},
        {"annotation_id": "L3", "who": "A", "text": "three"},
    ]
    before = {
        "lines_by_id": {
            "L2": {
                "source_id": "L2", "fx": "特写", "direction": {},
                "direction_intent": {}, "annotation_intent_fields": ["fx"],
            },
            "L3": {
                "source_id": "L3", "direction": {}, "direction_intent": {},
                "annotation_intent_fields": [],
            },
        },
        "beats": [{
            "beat_id": "beat-L3-before", "anchor_id": "L3",
            "position": "before", "who": "A", "face": "", "emo": "",
            "act": "", "wait_ms": 0, "reason": "shrink",
            "visible_characters": ["A"], "positions": {"A": 3},
            "shot_transition": "reframe", "shot_operation": "shrink_group",
            "conceal": [{"who": "B", "side": "fade"}],
        }],
        "state_delta": {}, "memory_events": [], "diagnostics": [],
    }
    repaired_direction = {
        "visible_characters": ["A", "B", "C"],
        "positions": {"A": 1, "B": 3, "C": 5},
        "shot_transition": "cut", "shot_operation": "switch_group",
    }
    repair = {
        "lines_by_id": {"L2": {
            "source_id": "L2", "fx": "",
            "direction": copy.deepcopy(repaired_direction),
            "direction_intent": copy.deepcopy(repaired_direction),
            "annotation_intent_fields": ["fx"],
        }},
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }

    before_report = validate_execution_quality(
        None, targets, before["lines_by_id"], before["beats"],
        memory=memory, cast=cast, constraints={},
    )
    candidate = _merge_g2_repair(before, repair, {"L2"})
    candidate_report = validate_execution_quality(
        None, targets, candidate["lines_by_id"], candidate["beats"],
        memory=memory, cast=cast, constraints={},
    )
    regressions = _introduced_g2_repair_regressions(
        before_report, candidate_report,
    )

    assert not any(
        issue["code"] == "reframe_removes_character_without_conceal"
        for issue in before_report["issues"]
    )
    assert candidate["beats"] == before["beats"]
    assert [(issue["anchor_id"], issue["missing_conceal"]) for issue in regressions] == [
        ("L3", ["C"]),
    ]


def test_g2_repair_rejects_candidate_that_introduces_structural_regression(
    tmp_path, monkeypatch,
):
    class RegressingRepairProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["face"] = (
                "05" if "G2_EXECUTION_REPAIR" in user else "00"
            )
            return response

    def forced_quality(_plan, targets, lines, _beats, **_kwargs):
        source_id = str(targets[0].get("annotation_id") or "")
        face = str((lines.get(source_id) or {}).get("face") or "")
        if face == "05":
            return {"result": "fail", "needs_review": True, "issues": [{
                "code": "reframe_adds_character_without_reveal",
                "severity": "high", "anchor_id": "later-anchor",
                "missing_reveal": ["爱丽丝"],
            }]}
        return {"result": "fail", "needs_review": True, "issues": [{
            "code": "forced_repair_probe", "severity": "high",
            "resolution": "ai_repair", "anchor_id": source_id,
        }]}

    monkeypatch.setattr("annotation_agent.validate_execution_quality", forced_quality)
    result = fixture(
        tmp_path, RegressingRepairProvider(), count=1,
        constraints_override={"faces_by_id": {"kei": {"00", "05"}}},
        scene_event_planning=True,
    )
    source_id = next(iter(result["rows_by_id"]))

    assert result["rows_by_id"][source_id]["face"] == "00"
    quality = result["director_plan"]["scenes"][0]["execution_quality"][0]
    assert quality["repaired_once"] is False
    assert quality["issues"][0]["code"] == "forced_repair_probe"
    assert any(
        item.get("code") == "g2_repair_introduced_structural_regression"
        for item in result["diagnostics"]
    )


def test_g2_sparse_repair_preserves_unmodified_reveal_and_direction_fields():
    original = {
        "lines_by_id": {"src-a": {
            "source_id": "src-a", "text_fingerprint": "fp", "face": "01",
            "emo": "疑问", "reveal": "left",
            "direction": {
                "relation_distance": "distant", "focus_character": "B",
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5},
            },
            "direction_intent": {
                "relation_distance": "distant", "focus_character": "B",
                "visible_characters": ["A", "B"], "positions": {"A": 1, "B": 5},
            },
            "annotation_intent_fields": ["face", "emo", "reveal"],
        }},
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }
    repaired = {
        "lines_by_id": {"src-a": {
            "source_id": "src-a", "text_fingerprint": "fp", "face": "06",
            "emo": "", "reveal": "", "direction": {"focus_character": ""},
            "direction_intent": {"focus_character": ""},
            "annotation_intent_fields": ["face"],
        }},
        "beats": [], "state_delta": {}, "memory_events": [], "diagnostics": [],
    }

    merged = _merge_g2_repair(original, repaired, {"src-a"})
    row = merged["lines_by_id"]["src-a"]

    assert row["face"] == "06"
    assert row["emo"] == "疑问"
    assert row["reveal"] == "left"
    assert row["direction"]["relation_distance"] == "distant"
    assert row["direction"]["focus_character"] == ""
    assert row["direction_intent"]["focus_character"] == ""


def test_g2_sparse_repair_preserves_omitted_beats_at_failed_anchor():
    original = {
        "lines_by_id": {"src-a": {"face": "01"}},
        "beats": [
            {
                "beat_id": "beat-entry", "anchor_id": "src-a", "position": "before",
                "who": "A", "reason": "entrance_reveal", "face": "", "emo": "",
                "act": "", "wait_ms": 0, "enter": [{"who": "A", "slot": 2, "side": "left"}],
            },
            {
                "beat_id": "beat-reaction", "anchor_id": "src-a", "position": "after",
                "who": "A", "reason": "listener_reaction", "face": "01", "emo": "疑问",
                "act": "", "wait_ms": 600,
            },
        ],
        "state_delta": {}, "memory_events": [], "diagnostics": [],
    }
    repaired = {
        "lines_by_id": {"src-a": {"face": "02"}},
        "beats": [{
            "beat_id": "beat-reaction", "anchor_id": "src-a", "position": "after",
            "who": "A", "reason": "listener_reaction", "face": "02", "emo": "",
            "act": "", "wait_ms": 600,
        }],
        "state_delta": {}, "memory_events": [], "diagnostics": [],
    }

    merged = _merge_g2_repair(original, repaired, {"src-a"})

    assert [beat["beat_id"] for beat in merged["beats"]] == [
        "beat-entry", "beat-reaction",
    ]
    assert merged["beats"][0]["enter"][0]["who"] == "A"
    assert merged["beats"][1]["face"] == "02"


def test_g2_face_change_repair_excludes_adjacent_physical_faces():
    targets = [
        {"annotation_id": "L1", "who": "A"},
        {"annotation_id": "L2", "who": "A"},
        {"annotation_id": "L3", "who": "A"},
    ]
    validated = {"lines_by_id": {
        "L1": {"face": "00"},
        "L2": {"face": "00"},
        "L3": {"face": "02"},
    }}
    report = {"issues": [{
        "anchor_id": "L2", "missing": ["face_change"],
    }]}
    tokens = {"L2": {
        "[Emo:平静]": "00",
        "[Emo:好奇]": "02",
        "[Emo:热情]": "04",
    }}

    filtered = _g2_face_change_token_options(
        targets, validated, report, tokens,
    )

    assert filtered["L2"] == {"[Emo:热情]": "04"}


def test_g2_face_change_repair_excludes_chunk_start_physical_face():
    filtered = _g2_face_change_token_options(
        [{"annotation_id": "L1", "who": "A"}],
        {"lines_by_id": {"L1": {"face": ""}}},
        {"issues": [{"anchor_id": "L1", "missing": ["face_change"]}]},
        {"L1": {"[Emo:继承脸]": "03", "[Emo:新阶段]": "04"}},
        {"direction": {"last_faces": {"A": "03"}}},
    )

    assert filtered["L1"] == {"[Emo:新阶段]": "04"}


def test_g2_repair_prompt_collapses_span_noise_and_internal_row_fields():
    issues = [
        {
            "code": "planned_shot_span_unfulfilled", "severity": "high",
            "anchor_id": anchor, "event_id": "E1", "expected": ["A", "B"],
            "span_start": "L1", "hold_until_id": "L3", "message": "span",
        }
        for anchor in ("L1", "L2", "L3")
    ]

    compact_issues = _compact_g2_repair_issues(issues)
    compact_lines = _compact_g2_previous_lines({
        "L1": {
            "source_id": "L1", "text_fingerprint": "large-internal-value",
            "face": "03", "direction": {
                "scene_type": "event", "visible_characters": ["A"],
                "positions": {"A": 3}, "shot_transition": "cut",
                "emotion_phase": "", "subtext": "",
            },
            "direction_intent": {"large": "internal"},
        },
    }, ["L1"])

    assert compact_issues == [{
        "code": "planned_shot_span_unfulfilled", "message": "span",
        "anchor_id": "L1", "event_id": "E1", "expected": ["A", "B"],
        "span_start": "L1", "hold_until_id": "L3",
    }]
    assert compact_lines == {"L1": {
        "source_id": "L1", "face": "03", "direction": {
            "scene_type": "event", "shot_transition": "cut", "visible_characters": ["A"],
            "positions": {"A": 3},
        },
    }}


def test_g2_repair_prompt_filters_issues_outside_current_targets():
    compact_issues = _compact_g2_repair_issues([
        {
            "code": "solo_emphasis_closeup_unfulfilled", "severity": "high",
            "anchor_id": "L1", "message": "repair L1",
        },
        {
            "code": "missing_planned_silent_phase", "severity": "high",
            "anchor_id": "L9", "message": "do not leak L9",
        },
    ], anchor_ids={"L1"})

    assert compact_issues == [{
        "code": "solo_emphasis_closeup_unfulfilled",
        "message": "repair L1",
        "anchor_id": "L1",
    }]


def test_g2_repair_prompt_keeps_performance_carrier_policy():
    compact = _compact_g2_repair_issues([{
        "code": "performance_intent_unfulfilled", "severity": "high",
        "anchor_id": "L1", "event_id": "E1", "subjects": ["A"],
        "expected": ["action", "sound"], "observed": ["action"],
        "missing": ["sound"], "require_all": True, "message": "missing sound",
    }])

    assert compact == [{
        "code": "performance_intent_unfulfilled", "message": "missing sound",
        "anchor_id": "L1", "event_id": "E1", "subjects": ["A"],
        "missing": ["sound"], "expected": ["action", "sound"],
        "observed": ["action"], "require_all": True,
    }]


def test_g2_previous_execution_keeps_reveal_and_explicit_empty_direction_values():
    compact = _compact_g2_previous_lines({
        "L1": {
            "source_id": "L1", "reveal": "right",
            "direction": {
                "relation_distance": "distant", "focus_character": "",
                "reaction_target": "",
            },
            "direction_intent": {
                "relation_distance": "distant", "focus_character": "",
                "reaction_target": "",
            },
        },
    }, ["L1"])

    assert compact == {"L1": {
        "source_id": "L1", "reveal": "right",
        "direction": {
            "relation_distance": "distant", "focus_character": "",
            "reaction_target": "",
        },
    }}


def test_agent_resolves_semantic_emo_token_to_character_clip_id(tmp_path):
    class SemanticFaceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][0]["face"] = "[Emo:平静回应]"
            return response

    result = fixture(
        tmp_path,
        SemanticFaceProvider(),
        count=1,
        constraints_override={
            "faces_by_id": {"kei": {"00"}},
            "face_records_by_id": {"kei": [{
                "id": "00", "semantic_cn": "平静回应｜普通说明或安静倾听",
                "beat_fit": ["dialogue"], "delivery_fit": ["normal_speech"],
                "usage_frequency": "common", "backend_selection_ready": True,
            }]},
        },
    )

    assert next(iter(result["rows_by_id"].values()))["face"] == "00"


def test_compact_agent_accepts_a_fully_sparse_noop_response(tmp_path):
    class SparseProvider:
        name = "sparse"
        model = "sparse"
        supports_compact_annotation = True

        def __init__(self):
            self.calls = 0

        def complete_json(self, _static, _volatile, _user, _schema):
            self.calls += 1
            return {"lines": [], "state_delta": {}, "memory_events": []}

    provider = SparseProvider()
    result = fixture(tmp_path, provider, count=35)

    assert provider.calls >= 1
    assert len(result["rows_by_id"]) == 35
    assert all(not row.get("face") and not row.get("emo") for row in result["rows_by_id"].values())


def test_compact_agent_persists_raw_expanded_and_validated_attempt_stages(tmp_path):
    class CompactDirectorProvider:
        name = "compact-director"
        model = "compact-director"
        supports_compact_annotation = True

        def complete_json(self, _static, _volatile, _user, _schema):
            return {
                "lines": [{
                    "i": 1,
                    "face": "[Emo:平静回应]",
                    "visible_characters": ["凯伊"],
                    "positions": {"凯伊": 3},
                    "shot_transition": "cut",
                }],
                "state_delta": {},
                "memory_events": [],
            }

    result = fixture(
        tmp_path,
        CompactDirectorProvider(),
        count=1,
        constraints_override={
            "face_records_by_id": {"kei": [{
                "id": "00", "semantic_cn": "平静回应",
                "backend_selection_ready": True,
            }]},
        },
    )

    attempt = next(iter(result["chunk_outputs"].values()))["model_attempts"][0]
    assert attempt["response"]["lines"][0]["visible_characters"] == ["凯伊"]
    assert attempt["expanded_response"]["lines"][0]["direction"]["visible_characters"] == ["凯伊"]
    source_id = result["items"][0]["annotation_id"]
    assert attempt["validated_response"]["lines_by_id"][source_id]["direction_intent"] == {
        "visible_characters": ["凯伊"],
        "positions": {"凯伊": 3},
        "shot_transition": "cut",
    }


def test_agent_persists_line_focus_and_continuity_without_overwriting_visible_snapshot(tmp_path):
    class DirectorProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["lines"][-1]["fx"] = "通讯"
                response["lines"][-1]["direction"] = {
                    "scene_type": "bond",
                    "focus_kind": "listener",
                    "focus_character": "凯伊",
                    "visible_characters": ["凯伊"],
                    "relation_distance": "approaching",
                    "emotion_phase": "waiting",
                    "continuity": {"fx": "start"},
                }
            return response

    provider = DirectorProvider()
    result = fixture(tmp_path, provider, count=70, story_type="bond")

    assert '"scene_type":"bond"' in provider.requests[0]["volatile"]
    assert result["memory"]["direction"]["focus"] == {
        "kind": "listener", "character": "凯伊",
    }
    assert result["memory"]["direction"]["continuity"]["fx"] == "通讯"
    assert result["memory"]["direction"]["shot_visible_characters"] == ["凯伊"]
    assert "visible_characters" not in result["memory"]["direction"]
    assert '"character":"凯伊"' in provider.requests[1]["volatile"]

    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    checkpoint = AnnotationCheckpointStore(tmp_path).load(checkpoint_path.parent.name)
    assert checkpoint["schema_version"] == 3
    assert checkpoint["chunk_outputs"]
    assert checkpoint["chunk_order"]
    assert checkpoint["director_plan"]["story_type"] == "bond"
    assert checkpoint["director_plan"]["scenes"][0]["mode_source"] == "user"
    assert checkpoint["memory"]["story"]["type"] == "bond"


def test_agent_memory_ignores_resource_values_rejected_by_final_application(tmp_path):
    class InvalidResourceProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                response["lines"][-1].update({
                    "face": "99", "emo": "missing-emo", "act": "missing-act",
                    "fx": "missing-fx", "se": "missing-se", "bg": "missing-bg",
                    "direction": {"continuity": {"fx": "start"}},
                })
            return response

    provider = InvalidResourceProvider()
    result = fixture(tmp_path, provider, count=70)
    direction = result["memory"]["direction"]

    assert direction["last_faces"] == {}
    assert direction["recent_emoticons"] == []
    assert direction["recent_actions"] == []
    assert direction["recent_sounds"] == []
    assert "fx" not in direction["continuity"]
    assert all("missing-" not in request["volatile"] for request in provider.requests[1:])


def test_partial_director_intent_does_not_reset_prior_focus(tmp_path):
    character = make_items(1)[0]["who"]

    class PartialDirectorProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["lines"][-2]["direction"] = {
                "focus_kind": "listener",
                "focus_character": character,
            }
            response["lines"][-1]["direction"] = {"scene_type": "bond"}
            return response

    result = fixture(tmp_path, PartialDirectorProvider(), count=10, story_type="bond")

    assert result["memory"]["direction"]["focus"] == {
        "kind": "listener", "character": character,
    }
    assert result["memory"]["scene"]["scene_type"] == "bond"


def test_agent_attaches_request_telemetry_to_chunk_without_prompt_text(tmp_path):
    class TelemetryProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({
                "request_index": self.calls,
                "input_tokens": 100,
                "cache_read_tokens": 70,
                "uncached_input_tokens": 30,
                "output_tokens": 9,
                "reasoning_tokens": 7,
                "reasoning_chars": 5,
                "content_chars": 2,
                "finish_reason": "stop",
            })
            return result

    result = fixture(tmp_path, TelemetryProvider(), count=10)

    records = result["metrics"]["request_records"]
    assert records[0]["scene_id"] == "scene-1"
    assert records[0]["chunk_id"] == "scene-1-chunk-1"
    assert records[0]["request_index"] == 1
    assert records[0]["retry_count"] == 0
    assert records[0]["subdivision_count"] == 0
    assert records[0]["stable_prefix_hash"]
    assert records[0]["dynamic_tail_hash"]
    assert records[0]["schema_hash"]
    assert records[0]["target_count"] == 10
    assert records[0]["adaptation_reason"] == "initial"
    assert "user" not in records[0]
    assert "volatile" not in records[0]


def test_agent_writes_reasoning_diagnostics_outside_checkpoint(tmp_path):
    class ReasoningProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.reasoning_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({"request_index": self.calls})
            self.reasoning_records.append({
                "request_index": self.calls,
                "model": self.model,
                "reasoning_text": "重复检查 TARGET 格式",
                "reasoning_chars": 10,
                "content_chars": 2,
                "finish_reason": "stop",
            })
            return result

    provider = ReasoningProvider()
    fixture(tmp_path, provider, count=10)

    files = list((tmp_path / "annotation-telemetry").rglob("reasoning.jsonl"))
    assert len(files) == 1
    assert "重复检查 TARGET 格式" in files[0].read_text(encoding="utf-8")
    assert "scene-1-chunk-1" in files[0].read_text(encoding="utf-8")
    assert not list((tmp_path / "annotation-checkpoints").rglob("*reasoning*"))


def test_reasoning_cursor_is_independent_from_request_record_cursor(tmp_path):
    class LateReasoningProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.request_records = []
            self.reasoning_records = []

        def complete_json(self, static, volatile, user, schema):
            result = super().complete_json(static, volatile, user, schema)
            self.request_records.append({"request_index": self.calls})
            if self.calls == 2:
                self.reasoning_records.append({
                    "request_index": 2, "reasoning_text": "late reasoning",
                    "reasoning_chars": 14, "content_chars": 2, "finish_reason": "stop",
                })
            return result

    fixture(tmp_path, LateReasoningProvider(), count=70)

    files = list((tmp_path / "annotation-telemetry").rglob("reasoning.jsonl"))
    assert len(files) == 1
    assert "late reasoning" in files[0].read_text(encoding="utf-8")


def test_structural_failure_retries_without_partial_commit(tmp_path):
    provider = RecordingProvider(omit_last_calls=1)
    result = fixture(tmp_path, provider, count=25)
    assert provider.calls == 3
    assert result["completed_chunks"] == 2
    assert len(result["memory"]["progress"]["completed_target_ids"]) == 25
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["subdivisions"] == 1


def test_provider_json_failure_subdivides_chunk_instead_of_aborting(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length; response was truncated")
            return super().complete_json(static, volatile, user, schema)

    provider = LengthLimitedProvider()

    result = fixture(tmp_path, provider, count=25)

    assert result["completed_chunks"] == 2
    assert len(result["rows_by_id"]) == 25
    assert provider.calls == 3
    assert any(diagnostic["code"] == "chunk_subdivided" for diagnostic in result["diagnostics"])


def test_resume_after_subdivision_requests_only_unfinished_targets(tmp_path):
    class InterruptedSubdivisionProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            if self.calls >= 2:
                self.calls += 1
                raise RuntimeError("interrupted")
            return super().complete_json(static, volatile, user, schema)

    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, InterruptedSubdivisionProvider(), count=25)

    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=25)

    assert len(resumed.requests) == 1
    assert len(resumed.requests[0]["target_ids"]) == 5
    completed_ids = result["memory"]["progress"]["completed_target_ids"]
    assert len(completed_ids) == len(set(completed_ids)) == 25


def test_empty_stop_response_retries_once_without_partial_commit(tmp_path):
    class EmptyOnceProvider(RecordingProvider):
        def __init__(self):
            super().__init__()
            self.empty = True

        def complete_json(self, static, volatile, user, schema):
            if self.empty:
                self.empty = False
                self.calls += 1
                raise llm.EmptyModelResponseError("empty stop response")
            return super().complete_json(static, volatile, user, schema)

    provider = EmptyOnceProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.calls == 2
    assert result["completed_chunks"] == 1
    assert len(result["rows_by_id"]) == 10
    assert result["metrics"]["retries"] == 1


def test_reasoning_only_empty_response_retries_without_lowering_effort(tmp_path):
    class ReasoningEmptyProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            if self.calls == 0:
                self.calls += 1
                raise llm.EmptyModelResponseError(
                    "empty stop response", finish_reason="stop", reasoning_chars=1200,
                )
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningEmptyProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "deep"]
    assert provider.cfg["reasoning_mode"] == "deep"
    assert result["metrics"]["retries"] == 1


def test_configured_output_budget_is_passed_through_without_disabling_thinking(tmp_path):
    class ReasoningCapacityProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "balanced"}
            self.modes = []
            self.budgets = []
            self.request_records = []

        @contextmanager
        def temporary_output_budget(self, maximum):
            self.budgets.append(maximum)
            yield

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningCapacityProvider()
    result = fixture(
        tmp_path, provider, count=10,
        reasoning_mode="balanced", annotation_max_tokens=384_000,
    )

    assert provider.modes == ["balanced"]
    assert provider.budgets == [384_000]
    assert provider.cfg["reasoning_mode"] == "balanced"
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["subdivisions"] == 0
    assert result["metrics"]["chunk_adaptations"] == []


def test_reasoning_capacity_at_ceiling_subdivides_without_disabling_thinking(tmp_path):
    class ReasoningCapacityProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "balanced"}
            self.modes = []
            self.request_records = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 5:
                self.calls += 1
                self.request_records.append({
                    "finish_reason": "length", "reasoning_tokens": 16_000,
                    "reasoning_chars": 40_000, "content_chars": 0,
                })
                raise llm.OutputCapacityError("reasoning exhausted output budget")
            return super().complete_json(static, volatile, user, schema)

    provider = ReasoningCapacityProvider()
    result = fixture(
        tmp_path, provider, count=10,
        reasoning_mode="balanced", annotation_max_tokens=16_000,
    )

    assert all(mode == "balanced" for mode in provider.modes)
    assert result["metrics"]["retries"] == 0
    assert result["metrics"]["subdivisions"] == 1


def test_reasoning_mode_is_restored_when_empty_retry_exhausts(tmp_path):
    class AlwaysReasoningEmptyProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            raise llm.EmptyModelResponseError(
                "empty stop response", finish_reason="stop", reasoning_chars=1200,
            )

    provider = AlwaysReasoningEmptyProvider()
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "deep"]
    assert provider.cfg["reasoning_mode"] == "deep"


def test_empty_without_reasoning_does_not_lower_effort(tmp_path):
    class EmptyWithoutReasoningProvider(RecordingProvider):
        supports_compact_annotation = False

        def __init__(self):
            super().__init__()
            self.cfg = {"reasoning_mode": "deep"}
            self.modes = []

        def complete_json(self, static, volatile, user, schema):
            self.modes.append(self.cfg["reasoning_mode"])
            if self.calls == 0:
                self.calls += 1
                raise llm.EmptyModelResponseError(
                    "empty stop response", finish_reason="stop", reasoning_chars=0,
                )
            return super().complete_json(static, volatile, user, schema)

    provider = EmptyWithoutReasoningProvider()
    result = fixture(tmp_path, provider, count=10)

    assert provider.modes == ["deep", "deep"]
    assert result["metrics"]["retries"] == 1


def test_chunk_recovery_progress_explains_retry_and_subdivision(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    provider = LengthLimitedProvider()
    result = fixture(tmp_path, provider, count=25, progress=lambda *args: events.append(args))

    assert result["completed_chunks"] == 2
    assert any("自动缩小" in str(event[-1]) for event in events)


def test_subdivision_keeps_user_progress_total_stable(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    fixture(
        tmp_path,
        LengthLimitedProvider(),
        count=25,
        progress=lambda *args: events.append(args),
    )

    annotation_events = [event for event in events if event[0] == "annotating"]
    assert {(event[1], event[2]) for event in annotation_events} == {(1, 1)}


def test_large_structured_failure_records_explicit_fallback_chain(tmp_path):
    class FailingLargeProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("response too large")
            return super().complete_json(static, volatile, user, schema)

    provider = FailingLargeProvider()
    result = fixture(tmp_path, provider, count=55)

    limits = [d["maximum"] for d in result["diagnostics"] if d["code"] == "chunk_subdivided"]
    assert limits == [50, 30, 20]


def test_agent_chunk_request_explicitly_uses_source_identity_protocol(tmp_path):
    provider = RecordingProvider()

    fixture(tmp_path, provider, count=2)

    request = provider.requests[0]["user"]
    assert "source_id" in request
    assert "text_fingerprint" in request
    assert "state_delta" in request
    assert "memory_events" in request


def test_failed_later_chunk_keeps_previous_checkpoint(tmp_path):
    provider = RecordingProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, provider, count=70)
    checkpoints = list(tmp_path.rglob("checkpoint.json"))
    assert len(checkpoints) == 1
    saved = AnnotationCheckpointStore(tmp_path).load(checkpoints[0].parent.name)
    assert saved["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_resume_skips_completed_provider_calls(tmp_path):
    first = RecordingProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, first, count=70)
    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=70)
    assert resumed.calls == 1
    assert result["resumed_chunks"] == 1
    assert len(result["rows_by_id"]) == 70


def test_checkpoint_replay_restores_unresolved_g2_diagnostics(tmp_path):
    fixture(tmp_path, RecordingProvider(), count=10)
    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    store = AnnotationCheckpointStore(tmp_path)
    saved = store.load(checkpoint_path.parent.name)
    chunk = saved["chunk_outputs"][saved["chunk_order"][0]]
    chunk["execution_quality"] = {
        "result": "fail",
        "issues": [{
            "code": "unplanned_camera_change_inside_shot_span", "severity": "critical",
            "resolution": "block", "anchor_id": chunk["target_ids"][0],
        }],
    }
    store.commit(checkpoint_path.parent.name, saved)

    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=10)

    assert resumed.calls == 0
    issue = next(
        item for item in result["diagnostics"]
        if item.get("code") == "unplanned_camera_change_inside_shot_span"
    )
    assert issue["resolution"] == "advisory"
    assert issue["needs_review"] is False
    assert issue["stage"] == "G2"


def test_resume_discards_checkpoint_schema_older_than_two(tmp_path):
    fixture(tmp_path, RecordingProvider(), count=70)
    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    store = AnnotationCheckpointStore(tmp_path)
    saved = store.load(checkpoint_path.parent.name)
    saved["schema_version"] = 1
    store.commit(checkpoint_path.parent.name, saved)

    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70)

    assert provider.calls == 2
    assert result["resumed_chunks"] == 0


def test_resume_preserves_dialogue_free_beats_from_completed_chunks(tmp_path):
    class BeatProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 1:
                anchor_id = self.requests[-1]["target_ids"][0]
                response["beats"] = [{
                    "anchor_id": anchor_id, "position": "after", "who": "凯伊",
                    "face": "00", "emo": "", "act": "", "wait_ms": 2500,
                    "reason": "listener_reaction",
                }]
            return response

    first = BeatProvider(fail_after=1)
    with pytest.raises(AnnotationAgentError):
        fixture(tmp_path, first, count=70)

    resumed = RecordingProvider()
    result = fixture(tmp_path, resumed, count=70)

    assert len(result["beats"]) == 1
    assert result["beats"][0]["wait_ms"] == 2500
    assert result["beats"][0]["reason"] == "listener_reaction"


def test_cancellation_stops_before_next_call_and_keeps_checkpoint(tmp_path):
    provider = RecordingProvider()
    result = fixture(tmp_path, provider, count=70, cancelled=lambda: provider.calls >= 1)
    assert result["cancelled"] is True
    assert provider.calls == 1
    assert result["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_review_windows_include_chunk_boundaries_and_open_events():
    source = make_items(70)
    scenes = [{"scene_id": "scene-1", "target_indices": list(range(70))}]
    events = [{
        "id": "event-name", "kind": "relationship_callback", "participants": ["凯伊"],
        "keywords": ["凯伊酱"], "summary": "凯伊酱称呼", "source_ids": [source[0]["annotation_id"]],
        "evidence": "第1句。", "importance": .9, "status": "open",
    }]
    windows = build_review_windows(source, scenes, events, chunk_size=30)
    assert any(window["kind"] == "chunk_boundary" for window in windows)
    assert any("凯伊酱" in window["context"] for window in windows)


def test_review_patch_cannot_change_dialogue_or_unseen_line():
    source = make_items(2)
    response = {"patches": [
        {"source_id": source[0]["annotation_id"], "field": "text", "before": "原文", "after": "改写", "reason": "润色", "evidence_source_ids": [source[0]["annotation_id"]]},
        {"source_id": "unknown", "field": "face", "before": "01", "after": "03", "reason": "调整", "evidence_source_ids": [source[0]["annotation_id"]]},
    ]}
    assert validate_review_patches(response, source, {}) == []


def test_review_patch_requires_matching_before_value():
    source = make_items(1)
    source[0]["face"] = "01"
    patch = {"source_id": source[0]["annotation_id"], "field": "face", "before": "00", "after": "03", "reason": "情绪变化", "evidence_source_ids": [source[0]["annotation_id"]]}
    updated, diagnostics = apply_review_patches(source, [patch])
    assert updated[0]["face"] == "01"
    assert diagnostics[0]["code"] == "review_before_mismatch"


def test_seventh_chunk_optional_state_null_finishes_without_retry(tmp_path):
    class NullStateProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls == 7:
                response["state_delta"] = {"bgfx": None}
            return response

    provider = NullStateProvider()
    result = fixture(tmp_path, provider, count=301)

    assert result["cancelled"] is False
    assert len(result["rows_by_id"]) == 301
    assert result["metrics"]["retries"] == 0


def test_protocol_error_gets_one_correction_and_never_subdivides(tmp_path):
    class WrongTypeProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            response["state_delta"] = {"positions": []}
            return response

    provider = WrongTypeProvider()
    with pytest.raises(AnnotationAgentError, match="invalid_state_delta"):
        fixture(tmp_path, provider, count=25)

    assert provider.calls == 2


def test_capacity_success_teaches_remaining_chunks_the_safe_limit(tmp_path):
    class TenLineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 10:
                self.calls += 1
                self.requests.append({"target_ids": ids, "user": user, "volatile": volatile})
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    provider = TenLineProvider()
    result = fixture(tmp_path, provider, count=80)
    successful_sizes = [
        len(row["target_ids"])
        for row in provider.requests
        if len(row["target_ids"]) <= 10
    ]

    assert result["metrics"]["subdivisions"] >= 1
    assert successful_sizes
    assert all(size <= 10 for size in successful_sizes)
    first_safe = next(
        i for i, row in enumerate(provider.requests) if len(row["target_ids"]) <= 10
    )
    assert all(len(row["target_ids"]) <= 10 for row in provider.requests[first_safe:])


def test_reasoning_mode_does_not_change_chunk_capacity(tmp_path):
    speed = RecordingProvider()
    deep = RecordingProvider()

    fixture(tmp_path / "speed", speed, count=80, reasoning_mode="speed")
    fixture(tmp_path / "deep", deep, count=80, reasoning_mode="deep")

    assert [len(request["target_ids"]) for request in speed.requests] == [
        len(request["target_ids"]) for request in deep.requests
    ]


def test_request_deadline_returns_checkpointed_partial_result(tmp_path):
    class DeadlineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            raise llm.RequestDeadlineError("deadline")

    result = fixture(tmp_path, DeadlineProvider(), count=25)
    assert result["timed_out"] is True
    assert result["completed_chunks"] == 0
    assert result["rows_by_id"] == {}
    assert result["total_targets"] == 25
    assert result["completed_targets"] == 0
    assert result["pending_targets"] == 25
    assert result["pending_start_line"] == 1
    assert result["pending_end_line"] == 25
    assert any(item["code"] == "request_deadline" for item in result["diagnostics"])

    checkpoint_path = next(tmp_path.rglob("checkpoint.json"))
    checkpoint = AnnotationCheckpointStore(tmp_path).load(checkpoint_path.parent.name)
    assert checkpoint["memory"]["progress"]["resume_target_limit"] == 12


def test_resume_after_deadline_uses_smaller_target_batches(tmp_path):
    class DeadlineProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            self.requests.append({
                "target_ids": re.findall(r"\[TARGET ([^\]]+)\]", user),
            })
            raise llm.RequestDeadlineError("deadline")

    first_provider = DeadlineProvider()
    first = fixture(tmp_path, first_provider, count=25)
    assert first["timed_out"] is True
    assert len(first_provider.requests[0]["target_ids"]) == 25

    resumed_provider = RecordingProvider()
    resumed = fixture(tmp_path, resumed_provider, count=25)

    assert resumed["timed_out"] is False
    assert resumed["completed_targets"] == 25
    assert resumed["pending_targets"] == 0
    assert resumed_provider.requests
    assert max(len(call["target_ids"]) for call in resumed_provider.requests) <= 12


def test_model_activity_adds_chunk_context_to_provider_events(tmp_path):
    events = []
    fixture(tmp_path, RecordingProvider(), count=10, model_activity=events.append)

    assert events
    assert events[0]["state"] == "waiting"
    assert events[-1]["state"] == "completed"
    assert events[0]["scene_id"] == "scene-1"
    assert events[0]["chunk_id"] == "scene-1-chunk-1"
    assert events[0]["request_index"] == 1


def test_non_stream_activity_uses_one_request_clock(tmp_path, monkeypatch):
    clock = iter([1000.0, 1000.25])
    monkeypatch.setattr("annotation_agent.time.time", lambda: next(clock))
    events = []

    fixture(tmp_path, RecordingProvider(), count=10, model_activity=events.append)

    waiting, completed = events[0], events[-1]
    assert waiting["request_started_at_ms"] == completed["request_started_at_ms"] == 1000000
    assert completed["elapsed_ms"] == 250


def test_agent_recovery_events_include_request_context(tmp_path):
    class LengthLimitedProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            ids = re.findall(r"\[TARGET ([^\]]+)\]", user)
            if len(ids) > 20:
                self.calls += 1
                raise llm.OutputCapacityError("finish_reason=length")
            return super().complete_json(static, volatile, user, schema)

    events = []
    fixture(tmp_path, LengthLimitedProvider(), count=25, model_activity=events.append)

    recovery = [event for event in events if event["state"] == "subdividing"]
    assert recovery
    assert recovery[0]["scene_id"] == "scene-1"
    assert recovery[0]["chunk_id"] == "scene-1-chunk-1"
    assert recovery[0]["chunk_current"] == recovery[0]["chunk_total"] == 1
    assert recovery[0]["request_index"] == 1


def test_later_protocol_failure_keeps_prior_checkpoint_without_subdivision(tmp_path):
    class FailingSecondChunkProvider(RecordingProvider):
        def complete_json(self, static, volatile, user, schema):
            response = super().complete_json(static, volatile, user, schema)
            if self.calls >= 2:
                response["state_delta"] = {"positions": []}
            return response

    provider = FailingSecondChunkProvider()
    with pytest.raises(AnnotationAgentError, match="invalid_state_delta") as failure:
        fixture(tmp_path, provider, count=70)

    assert failure.value.partial_result is not None
    assert failure.value.partial_result["completed_targets"] > 0
    assert failure.value.partial_result["partial_failure"]["chunk_id"] == "scene-1-chunk-2"

    assert provider.calls == 3
    checkpoints = list(tmp_path.rglob("checkpoint.json"))
    assert len(checkpoints) == 1
    saved = AnnotationCheckpointStore(tmp_path).load(checkpoints[0].parent.name)
    assert saved["memory"]["progress"]["completed_chunks"] == ["scene-1-chunk-1"]


def test_agent_metrics_distinguish_reported_cache_from_missing_telemetry(tmp_path):
    provider = RecordingProvider()
    provider.stats = {
        "in": 100,
        "out": 20,
        "cache_read": 70,
        "cache_miss": 30,
        "cache_write": 0,
        "cache_reports": 1,
        "calls": 0,
    }

    result = fixture(tmp_path, provider, count=10)

    assert result["metrics"]["cache_reported"] is False
    assert result["metrics"]["cache_read_tokens"] is None
    assert result["metrics"]["uncached_input_tokens"] is None
    assert result["metrics"]["actual_model"] == "fake"
