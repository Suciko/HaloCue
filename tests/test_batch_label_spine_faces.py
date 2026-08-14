import hashlib
from pathlib import Path

import batch_label_spine_faces
from batch_label_spine_faces import (
    FreshSpineRenderer,
    discover_main_character_targets,
    persist_target_visual_face_labels,
    select_target_shard,
)


def _bundle(root: Path, stem: str) -> Path:
    folder = root / "characters" / stem
    folder.mkdir(parents=True)
    base = folder / stem
    base.with_suffix(".skel").write_bytes(b"binary spine 4.2.33 payload")
    base.with_suffix(".atlas").write_text(
        f"{stem}.png\nsize: 16,16\nformat: RGBA8888\nfilter: Linear,Linear\nrepeat: none\n",
        encoding="utf-8",
    )
    base.with_suffix(".png").write_bytes(b"png")
    return base


def _character(identifier: str, stem: str, count: int) -> dict:
    return {
        "identifier": identifier,
        "name": identifier.split("（", 1)[0],
        "club": "测试社团",
        "spine": f"characters\\{stem}\\{stem}",
        "spine_signature": hashlib.sha256(stem.encode()).hexdigest(),
        "outfit_key": stem,
        "faces": [{"id": f"{index:02d}", "raw": str(index)} for index in range(count)],
    }


def test_discovers_complete_main_portraits_and_reports_exclusion_reasons(tmp_path):
    for stem in ("CH0001_spr", "NP0002_spr", "NP0003_spr", "CH0004_spr"):
        _bundle(tmp_path, stem)
    index = {"characters": [
        _character("爱丽丝", "CH0001_spr", 5),
        _character("主角变体", "NP0002_spr", 4),
        _character("某校学生A", "NP0003_spr", 7),
        _character("表情太少", "CH0004_spr", 3),
        _character("缺少文件", "CH0005_spr", 8),
    ]}

    targets, excluded = discover_main_character_targets(index, overrides_root=tmp_path)

    assert {(item.identifier, item.face_count) for item in targets} == {
        ("爱丽丝", 5), ("主角变体", 4),
    }
    assert {item["identifier"]: item["reason"] for item in excluded} == {
        "某校学生A": "anonymous_supporting_character",
        "表情太少": "too_few_faces",
        "缺少文件": "missing_bundle",
    }
    assert all(item.spine_version == "4.2.33" for item in targets)


def test_can_include_anonymous_supporting_portraits_explicitly(tmp_path):
    _bundle(tmp_path, "NP0010_spr")
    index = {"characters": [_character("阿里乌斯学生B", "NP0010_spr", 6)]}

    targets, excluded = discover_main_character_targets(
        index, overrides_root=tmp_path, include_supporting=True
    )

    assert [item.identifier for item in targets] == ["阿里乌斯学生B"]
    assert excluded == []


def test_discovery_uses_base_and_extra_roots_without_name_prefix_filter(tmp_path):
    base_root = tmp_path / "base"
    extra_root = tmp_path / "extra"
    _bundle(base_root, "CharacterSpine_hihumi")
    index = {"characters": [_character("日富美", "CharacterSpine_hihumi", 4)]}

    targets, excluded = discover_main_character_targets(
        index, overrides_root=[extra_root, base_root]
    )

    assert [item.outfit_key for item in targets] == ["CharacterSpine_hihumi"]
    assert targets[0].source_dir == str((base_root / "characters" / "CharacterSpine_hihumi").resolve())
    assert excluded == []


def test_shared_skeleton_keeps_every_real_identity_binding(tmp_path):
    _bundle(tmp_path, "CH0001_spr")
    index = {"characters": [
        _character("identity-a", "CH0001_spr", 4),
        _character("identity-b", "CH0001_spr", 4),
    ]}

    targets, excluded = discover_main_character_targets(index, overrides_root=tmp_path)

    assert len(targets) == 1
    assert [item.identifier for item in targets[0].bindings] == [
        "identity-a", "identity-b",
    ]
    assert not any(item.get("reason") == "duplicate_skeleton" for item in excluded)


def test_one_visual_result_is_persisted_for_every_identity_binding(tmp_path, monkeypatch):
    _bundle(tmp_path, "CH0001_spr")
    index = {"characters": [
        _character("identity-a", "CH0001_spr", 4),
        _character("identity-b", "CH0001_spr", 4),
    ]}
    target = discover_main_character_targets(index, overrides_root=tmp_path)[0][0]
    calls = []

    def fake_persist(_con, **kwargs):
        calls.append(kwargs)
        return {"saved_count": len(kwargs["labels"]), "failed_count": 0}

    monkeypatch.setattr(batch_label_spine_faces, "persist_visual_face_labels", fake_persist)
    result = persist_target_visual_face_labels(
        object(), target=target, model="current-model", labels=[{"face_id": "00"}]
    )

    assert [item["ident"] for item in calls] == ["identity-a", "identity-b"]
    assert all(item["model"] == "current-model" for item in calls)
    assert result["saved_count"] == 1
    assert result["identity_rows_saved"] == 2


def test_target_shards_are_disjoint_and_cover_every_target(tmp_path):
    for index in range(7):
        _bundle(tmp_path, f"CH{index:04d}_spr")
    index = {"characters": [
        _character(f"identity-{number}", f"CH{number:04d}_spr", 4)
        for number in range(7)
    ]}
    targets = discover_main_character_targets(index, overrides_root=tmp_path)[0]

    shards = [
        select_target_shard(targets, shard_count=3, shard_index=shard)
        for shard in range(3)
    ]

    assert [len(items) for items in shards] == [3, 2, 2]
    assert {item.source_dir for items in shards for item in items} == {
        item.source_dir for item in targets
    }


def test_fresh_renderer_retries_oserror_in_a_new_session(tmp_path, monkeypatch):
    sessions = []

    class FakeRenderer:
        def __init__(self, *, canvas_size, spine_version):
            self.canvas_size = canvas_size
            self.spine_version = spine_version
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def render(self, *_args, **_kwargs):
            if len(sessions) == 1:
                raise OSError(22, "Invalid argument")
            return "rendered"

    monkeypatch.setattr("batch_label_spine_faces.SpineWebRenderer", FakeRenderer)
    bundle = _bundle(tmp_path, "CH0001_spr").parent

    with FreshSpineRenderer(canvas_size=1024) as renderer:
        assert renderer.render(bundle, face_ids=("00",), cache_root="cache") == "rendered"

    assert [session.canvas_size for session in sessions] == [1024, 1024]
    assert [session.spine_version for session in sessions] == ["4.2.33", "4.2.33"]
