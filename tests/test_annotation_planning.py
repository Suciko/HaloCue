from annotation_chunks import assign_annotation_ids, build_scene_map
from annotation_memory import (
    assemble_chunk_context,
    build_story_plan,
    complete_scene,
    initial_memory,
    merge_memory_events,
    retrieve_events,
)


def items():
    return assign_annotation_ids([
        {"kind": "line", "line_no": 1, "split_index": 0, "who": "旁白", "text": "商店街入口。"},
        {"kind": "line", "line_no": 2, "split_index": 0, "who": "凯伊", "text": "走吧。"},
        {"kind": "other", "raw": "---"},
        {"kind": "line", "line_no": 21, "split_index": 0, "who": "旁白", "text": "夜色中的天台。"},
        {"kind": "line", "line_no": 22, "split_index": 0, "who": "老师", "text": "到了。"},
    ])


def test_confirmed_usage_chain_names_scene_and_preserves_evidence():
    source = items()
    plan = build_story_plan(source, build_scene_map(source), [{
        "segment": "开场", "location": "商店街", "start": "第1行", "end": "第2行",
        "evidence": "商店街入口。", "needs": [],
    }, {
        "segment": "转场", "location": "夜间天台", "start": "第21行", "end": "第22行",
        "evidence": "夜色中的天台。", "needs": [],
    }])
    assert plan["scenes"][1]["location"] == "夜间天台"
    assert plan["scenes"][1]["evidence"] == "夜色中的天台。"


def test_confirmed_usage_chain_preserves_per_scene_director_metadata():
    source = items()
    plan = build_story_plan(source, build_scene_map(source), [{
        "segment": "开场", "location": "商店街", "start": "第1行", "end": "第2行",
        "scene_type": "event", "scene_function": "entrance", "time": "傍晚",
    }])
    assert plan["scenes"][0]["scene_type"] == "event"
    assert plan["scenes"][0]["scene_function"] == "entrance"
    assert plan["scenes"][0]["time"] == "傍晚"


def test_planned_second_scene_enters_the_actual_chunk_director_context():
    source = items()
    usage_chain = [{
        "segment": "开场", "start": "第1行", "end": "第2行",
        "scene_type": "event", "scene_function": "dialogue",
    }, {
        "segment": "天台", "start": "第21行", "end": "第22行",
        "scene_type": "bond", "scene_function": "emotional_turn", "time": "夜间",
    }]
    scenes = build_scene_map(source, usage_chain)
    plan = build_story_plan(source, scenes, usage_chain)
    second = plan["scenes"][1]
    memory = complete_scene(initial_memory(), second, second["evidence"])
    volatile, _user = assemble_chunk_context(
        source,
        {"scene_id": second["scene_id"], "target_indices": second["target_indices"]},
        memory, [], usage_chain, story_type="auto",
    )

    assert '"scene_type":"bond"' in volatile
    assert '"scene_function":"emotional_turn"' in volatile
    assert '"time":"夜间"' in volatile


def test_entering_a_scene_resets_visual_state_but_keeps_story_memory():
    memory = initial_memory("summary", "bond")
    memory["story"]["open_threads"] = ["约定"]
    memory["direction"].update({
        "background": "BG_Old", "visible_characters": ["凯伊"],
        "shot_visible_characters": ["凯伊"], "last_faces": {"凯伊": "03"},
        "recent_emoticons": ["疑问"], "continuity": {"face": "03"},
        "focus": {"kind": "listener", "character": "凯伊"},
        "emotion_phase": "等待回应", "subtext": "试探",
    })

    updated = complete_scene(memory, {
        "scene_id": "scene-2", "scene_type": "bond",
        "scene_function": "establishing",
    }, "新地点")

    assert updated["story"]["open_threads"] == ["约定"]
    assert updated["direction"]["background"] is None
    assert updated["direction"]["visible_characters"] == []
    assert updated["direction"]["last_faces"] == {}
    assert updated["direction"]["continuity"] == {}
    assert updated["direction"]["focus"] == {"kind": "speaker", "character": ""}


def test_no_usage_chain_produces_deterministic_story_summary():
    source = items()
    plan = build_story_plan(source, build_scene_map(source), [])
    assert plan["summary"]
    assert set(plan["speakers"]) == {"凯伊", "老师", "旁白"}


def event(source_ids, evidence, *, kind="relationship_callback", status="open", importance=.9):
    return {
        "kind": kind, "participants": ["凯伊", "老师"], "keywords": ["凯伊酱"],
        "summary": "老师用特殊称呼，凯伊否认", "source_ids": source_ids,
        "evidence": evidence, "importance": importance, "status": status,
        "scene_id": "scene-1",
    }


def test_event_without_exact_evidence_is_dropped():
    visible = [{"annotation_id": "src-4", "text": "才不是凯伊酱好吗！"}]
    candidates = [event(["src-4"], "不存在的台词")]
    assert merge_memory_events([], candidates, visible) == []


def test_open_name_callback_beats_unrelated_recent_event():
    unrelated = {
        **event(["src-2"], "按钮", kind="button", status="reference", importance=.95),
        "participants": ["桃井"], "keywords": ["按钮"], "id": "event-unrelated",
    }
    named = {**event(["src-1"], "凯伊酱"), "id": "event-name"}
    selected = retrieve_events(
        [named, unrelated], [{"who": "老师", "text": "凯伊酱老师？"}], "scene-3", limit=1,
    )
    assert selected[0]["kind"] == "relationship_callback"
