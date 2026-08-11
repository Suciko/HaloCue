import json

from annotation_chunks import assign_annotation_ids
from annotation_memory import (
    AnnotationCheckpointStore,
    apply_state_delta,
    assemble_chunk_context,
    build_run_fingerprint,
    initial_memory,
)


def test_initial_memory_contains_director_state():
    memory = initial_memory("summary", "bond")

    assert memory["story"]["type"] == "bond"
    assert memory["scene"]["scene_type"] == "bond"
    assert memory["direction"]["focus"] == {"kind": "speaker", "character": ""}
    assert memory["direction"]["continuity"] == {}


def test_fingerprint_changes_when_director_version_or_story_type_changes():
    base = build_run_fingerprint(
        "text", {}, {}, "p", 3, "scene-v3", {},
        story_type="main", director_version="d1",
    )
    changed_type = build_run_fingerprint(
        "text", {}, {}, "p", 3, "scene-v3", {},
        story_type="bond", director_version="d1",
    )
    changed_version = build_run_fingerprint(
        "text", {}, {}, "p", 3, "scene-v3", {},
        story_type="main", director_version="d2",
    )

    assert base != changed_type
    assert base != changed_version


def test_state_delta_preserves_background_and_rejects_unknown_character():
    memory = initial_memory("约会故事")
    updated = apply_state_delta(
        memory,
        {"background": "BG_Street", "visible_characters": ["凯伊"],
         "last_faces": {"不存在": "03"}},
        cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints={"ok_bg": {"BG_Street"}, "faces_by_id": {"kei": {"03"}}},
    )
    assert updated["direction"]["background"] == "BG_Street"
    assert updated["direction"]["visible_characters"] == ["凯伊"]
    assert "不存在" not in updated["direction"]["last_faces"]


def test_transient_effect_is_not_persisted_as_background_state():
    memory = initial_memory()
    updated = apply_state_delta(
        memory, {"bgfx": "集中线"}, cast={},
        constraints={"ok_bg": set(), "faces_by_id": {}},
    )
    assert updated["direction"]["bgfx"] is None


def make_items(count=80):
    return assign_annotation_ids([{
        "kind": "line", "line_no": index + 1, "split_index": 0,
        "who": "凯伊" if index % 2 else "老师", "text": f"第{index + 1}句。",
        "raw": f"角色: 第{index + 1}句。",
    } for index in range(count)])


def make_events(count):
    return [{
        "id": f"event-{index}", "kind": "callback", "participants": ["凯伊"],
        "keywords": [f"词{index}"], "summary": f"事件{index}",
        "source_ids": ["src"], "evidence": f"证据{index}",
        "importance": 1 - index / 100, "status": "open", "scene_id": "scene-1",
    } for index in range(count)]


def test_context_marks_target_past_and_future_and_limits_events():
    items = make_items()
    memory = initial_memory("约会故事")
    memory["direction"]["background"] = "BG_Street"
    volatile, user = assemble_chunk_context(
        items=items,
        chunk={"scene_id": "scene-1", "target_indices": list(range(30, 50))},
        memory=memory,
        events=make_events(12),
        usage_chain=[], before=15, after=10, max_events=8,
    )
    assert "CURRENT_DIRECTION_STATE" in volatile
    assert "BG_Street" in volatile
    assert user.count("[TARGET ") == 20
    assert user.count("[PAST_CONTEXT ") == 15
    assert user.count("[FUTURE_CONTEXT ") == 10
    event_payload = volatile.split("RELEVANT_MEMORY_EVENTS\n", 1)[1]
    assert len(json.loads(event_payload)) == 8
    assert "不得标注 FUTURE_CONTEXT" in user


def test_context_emits_bounded_director_context_and_continuity_instruction():
    items = make_items(3)
    memory = initial_memory("summary", "bond")
    memory["direction"]["emotion_phase"] = "x" * 5000

    volatile, user = assemble_chunk_context(
        items=items,
        chunk={"scene_id": "scene-1", "target_indices": [0, 1]},
        memory=memory, events=[], usage_chain=[], story_type="bond",
        before=0, after=0,
    )

    marker = volatile.split("DIRECTOR_CONTEXT\n", 1)[1].split("\n\n", 1)[0]
    director_context = json.loads(marker)
    assert director_context["story_type"] == "bond"
    assert director_context["scene_type"] == "bond"
    assert len(marker) <= 4000
    assert "continuity" in user.lower()
    assert "line" in user.lower()


def test_target_context_uses_short_indices_without_full_fingerprints():
    items = make_items(3)
    _volatile, user = assemble_chunk_context(
        items=items,
        chunk={"scene_id": "scene-1", "target_indices": [0, 1]},
        memory=initial_memory(), events=[], usage_chain=[], before=0, after=0,
        compact=True,
    )

    assert "[TARGET 1]" in user
    assert "[TARGET 2]" in user
    assert items[0]["text_fingerprint"] not in user
    assert "不复述规则、哈希、原文或候选比较" in user


def test_checkpoint_round_trip_and_no_temporary_file(tmp_path):
    store = AnnotationCheckpointStore(tmp_path)
    state = {"schema_version": 1, "progress": {"completed_chunks": ["chunk-1"]}}
    path = store.commit("run-a", state)
    assert store.load("run-a") == state
    assert path.name == "checkpoint.json"
    assert not list(tmp_path.rglob("*.tmp"))


def test_run_fingerprint_changes_when_reasoning_mode_changes():
    base = build_run_fingerprint(
        "script", {"凯伊": {"id": "kei"}}, {}, "prompt", 1, "chunk",
        {"provider": "openai", "model": "deepseek-v4-flash", "max_tokens": 384000,
         "annotation_max_tokens": 16000, "reasoning_mode": "balanced"},
    )
    speed = build_run_fingerprint(
        "script", {"凯伊": {"id": "kei"}}, {}, "prompt", 1, "chunk",
        {"provider": "openai", "model": "deepseek-v4-flash", "max_tokens": 384000,
         "annotation_max_tokens": 16000, "reasoning_mode": "speed"},
    )
    assert base != speed


def test_corrupt_checkpoint_is_ignored_without_deleting_it(tmp_path):
    path = tmp_path / "run-a" / "checkpoint.json"
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")
    store = AnnotationCheckpointStore(tmp_path)
    assert store.load("run-a") is None
    assert path.exists()


def three_scenes():
    return [{"scene_id": f"scene-{index}"} for index in range(1, 4)]


def fingerprints(scene_hashes, prompt="v1"):
    return {
        "script_sha256": "script", "cast_sha256": "cast", "resources_sha256": "resources",
        "prompt_version": prompt, "schema_version": 1, "chunk_version": "v1",
        "model": {"provider": "openai", "model": "test", "max_tokens": 16000},
        "scene_hashes": scene_hashes,
    }


def test_middle_scene_edit_reuses_prefix_and_invalidates_following_state(tmp_path):
    store = AnnotationCheckpointStore(tmp_path)
    plan = store.resume_plan(
        fingerprints(["a", "old-b", "c"]),
        fingerprints(["a", "new-b", "c"]),
        scenes=three_scenes(),
    )
    assert plan["reuse_scene_ids"] == ["scene-1"]
    assert plan["restart_scene_id"] == "scene-2"
    assert plan["reuse_after_restart"] is False


def test_prompt_change_invalidates_chunks_but_keeps_compatible_scene_map(tmp_path):
    store = AnnotationCheckpointStore(tmp_path)
    plan = store.resume_plan(
        fingerprints(["a", "b", "c"], prompt="v1"),
        fingerprints(["a", "b", "c"], prompt="v2"),
        three_scenes(),
    )
    assert plan["reuse_scene_map"] is True
    assert plan["reuse_chunk_results"] is False


def test_run_fingerprint_never_serializes_credentials_or_paths():
    fingerprint = build_run_fingerprint(
        "凯伊: 好。", {"凯伊": {"id": "kei"}}, {"bg": ["BG_Street"]},
        "prompt-v1", 1, "chunk-v1",
        {"provider": "openai", "model": "test", "max_tokens": 16000,
         "api_key": "secret", "base_url": "C:\\private\\proxy"},
    )
    serialized = json.dumps(fingerprint, ensure_ascii=False)
    assert "secret" not in serialized
    assert "private" not in serialized
