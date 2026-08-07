from annotation_chunks import (
    assign_annotation_ids,
    build_chunks,
    build_scene_map,
    context_indices,
)


def make_items(values, separator_index=None):
    items = []
    for index, value in enumerate(values):
        if value is None:
            items.append({"kind": "other", "raw": "---"})
            continue
        who, text = value
        items.append({
            "kind": "line", "line_no": index + 1, "split_index": 0,
            "who": who, "text": text, "raw": f"{who}: {text}",
        })
    return assign_annotation_ids(items)


def test_annotation_ids_are_stable_and_distinguish_split_segments():
    original = [
        {"kind": "line", "line_no": 7, "split_index": 0, "who": "凯伊", "text": "前半。"},
        {"kind": "line", "line_no": 7, "split_index": 1, "who": "凯伊", "text": "后半。"},
    ]
    first = assign_annotation_ids([dict(item) for item in original])
    second = assign_annotation_ids([dict(item) for item in original])
    assert [item["annotation_id"] for item in first] == [item["annotation_id"] for item in second]
    assert first[0]["annotation_id"] != first[1]["annotation_id"]
    assert first[0]["text_fingerprint"] != first[1]["text_fingerprint"]


def test_explicit_separator_closes_scene_and_chunk():
    items = make_items([
        ("旁白", "商店街入口。"),
        ("凯伊", "走吧。"),
        None,
        ("旁白", "游戏中心里。"),
        ("老师", "到了。"),
    ])
    scenes = build_scene_map(items)
    chunks = build_chunks(items, scenes, target=20, soft_limit=40, hard_limit=60)
    assert [scene["target_indices"] for scene in scenes] == [[0, 1], [3, 4]]
    assert [chunk["target_indices"] for chunk in chunks] == [[0, 1], [3, 4]]


def test_blank_lines_do_not_split_a_scene():
    items = assign_annotation_ids([
        {"kind": "line", "line_no": 1, "who": "凯伊", "text": "第一句。"},
        {"kind": "other", "raw": ""},
        {"kind": "line", "line_no": 3, "who": "老师", "text": "第二句。"},
    ])
    assert [scene["target_indices"] for scene in build_scene_map(items)] == [[0, 2]]


def test_chunk_uses_bounded_past_and_future_windows():
    dialogue = list(range(100))
    past, future = context_indices(dialogue, {"target_indices": list(range(30, 60))})
    assert past == list(range(15, 30))
    assert future == list(range(60, 70))


def test_default_chunks_target_forty_to_fifty_with_hard_cap_sixty():
    items = make_items([("凯伊", f"第{i}句。") for i in range(241)])
    scenes = build_scene_map(items)
    chunks = build_chunks(items, scenes)

    sizes = [len(chunk["target_indices"]) for chunk in chunks]
    assert 4 <= len(chunks) <= 6
    assert max(sizes) <= 60
    assert min(sizes) >= 40 or len(chunks) == 1
