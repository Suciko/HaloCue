# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
import build_bundle
from build_bundle import BuildBundleManager, CompileInputStaleError
from draft_store import DraftStore


@pytest.fixture
def temp_draft_store(tmp_path):
    store_dir = tmp_path / "drafts"
    return DraftStore(base_dir=str(store_dir))


def test_build_bundle_structure_and_atomic_seal(
    temp_draft_store, tmp_path, monkeypatch
):
    store = temp_draft_store
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides"):
        (aa_data / name).mkdir(parents=True)
    monkeypatch.setenv("AA_DATA", str(aa_data))
    token = "bundle-token-1"
    sample_text = "## 场景1\n旁白: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text, project="Bundle测试项目")
    draft_dir = store.get_draft_path(token)
    (draft_dir / "cast.json").write_text(
        json.dumps({"cast": {"旁白": {"narrator": True}}}), encoding="utf-8"
    )
    (draft_dir / "resources.json").write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1},
                "sounds": [],
                "characters": [],
                "enums": {
                    "emoticon": {},
                    "action": {},
                    "appear": {},
                    "shape": {},
                },
            }
        ),
        encoding="utf-8",
    )
    manager = BuildBundleManager(store=store)

    # 锁定快照
    build_id = manager.create_compile_snapshot(token=token, expected_draft_version=1)
    assert build_id.startswith("build-") or len(build_id) > 5

    # 模拟 Worker 编译产出 Bundle
    bundle_info = manager.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])

    # 1. 验证包含 bundle.complete 标记
    assert (bundle_dir / "bundle.complete").is_file()

    # 2. 验证 files.json 包含全文件 hash 清单
    assert (bundle_dir / "files.json").is_file()
    files_manifest = json.loads((bundle_dir / "files.json").read_text(encoding="utf-8"))
    assert isinstance(files_manifest, list)
    assert any(item["path"] == "build.json" for item in files_manifest)

    # 3. 验证 manifest_delta.json 存在
    assert (bundle_dir / "project" / "manifest_delta.json").is_file()


def test_stale_compile_snapshot_raises_409(temp_draft_store):
    store = temp_draft_store
    token = "bundle-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    store.create_draft(token=token, text=sample_text)
    manager = BuildBundleManager(store=store)

    # 传入过期的 expected_draft_version (例如 999) 抛出 CompileInputStaleError
    with pytest.raises(CompileInputStaleError):
        manager.create_compile_snapshot(token=token, expected_draft_version=999)


def test_compile_snapshot_captures_the_draft_cast_and_resource_index(
    temp_draft_store,
):
    """Dropping either file makes the worker fall back to unrelated app defaults."""
    store = temp_draft_store
    token = "bundle-draft-inputs"
    store.create_draft(token=token, text="凯伊: 你好\n", project="草稿输入测试")
    draft_dir = store.get_draft_path(token)
    cast = {
        "default_bg": "BG_Draft",
        "cast": {"凯伊": {"id": "draft-kei", "portrait": True}},
    }
    resources = {
        "bg": {"BG_Draft": 123},
        "characters": [{"identifier": "draft-kei", "name": "凯伊"}],
    }
    (draft_dir / "cast.json").write_text(
        json.dumps(cast, ensure_ascii=False), encoding="utf-8"
    )
    (draft_dir / "resources.json").write_text(
        json.dumps(resources, ensure_ascii=False), encoding="utf-8"
    )

    build_id = BuildBundleManager(store=store).create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    snapshot = draft_dir / "builds" / ".tmp" / build_id / "input"

    assert json.loads((snapshot / "cast.json").read_text(encoding="utf-8")) == cast
    assert json.loads(
        (snapshot / "resources.json").read_text(encoding="utf-8")
    ) == resources


def test_build_worker_compiles_from_the_snapshot_cast_and_resource_index(
    temp_draft_store, tmp_path, monkeypatch
):
    """Using process-wide defaults would compile a different actor and background."""
    store = temp_draft_store
    token = "bundle-worker-inputs"
    store.create_draft(token=token, text="凯伊: 你好\n", project="快照编译测试")
    draft_dir = store.get_draft_path(token)
    (draft_dir / "cast.json").write_text(
        json.dumps(
            {"cast": {"凯伊": {"id": "draft-kei", "portrait": True}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (draft_dir / "resources.json").write_text(
        json.dumps({"bg": {"BG_Draft": 123}}, ensure_ascii=False),
        encoding="utf-8",
    )

    def compile_fixture(options):
        cast = json.loads(Path(options["cast"]).read_text(encoding="utf-8"))
        resources = json.loads(Path(options["index"]).read_text(encoding="utf-8"))
        generated = tmp_path / "generated"
        project = generated / "project"
        project.mkdir(parents=True)
        (project / "compile-inputs.json").write_text(
            json.dumps(
                {
                    "character": cast["cast"]["凯伊"]["id"],
                    "backgrounds": sorted(resources["bg"]),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        aap = generated / "draft.aap"
        aap.write_text("compiled", encoding="utf-8")
        return {"aap_file": str(aap), "project_dir": str(project)}

    monkeypatch.setattr(build_bundle, "compile_script", compile_fixture)
    manager = BuildBundleManager(store=store)
    build_id = manager.create_compile_snapshot(token=token, expected_draft_version=1)
    result = manager.execute_build_worker(token=token, build_id=build_id)
    compiled = json.loads(
        (Path(result["bundle_dir"]) / "project" / "compile-inputs.json").read_text(
            encoding="utf-8"
        )
    )

    assert compiled == {"character": "draft-kei", "backgrounds": ["BG_Draft"]}


def test_compile_snapshot_accepts_the_existing_per_draft_resource_file(
    temp_draft_store, tmp_path, monkeypatch
):
    """Existing review drafts keep their index at out/<draft>.resources.json."""
    store = temp_draft_store
    token = "legacy-resource-layout"
    store.create_draft(token=token, text="旁白: 你好\n", project="旧草稿")
    draft_dir = store.get_draft_path(token)
    (draft_dir / "cast.json").write_text(
        json.dumps({"cast": {"旁白": {"narrator": True}}}), encoding="utf-8"
    )
    resources = {"bg": {"BG_Legacy": 456}}
    legacy_dir = tmp_path / "out"
    legacy_dir.mkdir()
    (legacy_dir / f"{token}.resources.json").write_text(
        json.dumps(resources), encoding="utf-8"
    )
    monkeypatch.setattr(build_bundle, "HERE", tmp_path)

    build_id = BuildBundleManager(store=store).create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    snapshot = draft_dir / "builds" / ".tmp" / build_id / "input"

    assert json.loads(
        (snapshot / "resources.json").read_text(encoding="utf-8")
    ) == resources


def test_packaged_compile_uses_user_runtime_paths_without_bundle_writes(
    temp_draft_store, tmp_path, monkeypatch
):
    resource_root = tmp_path / "read-only bundle"
    resource_root.mkdir()
    (resource_root / "marker.bin").write_bytes(b"immutable")
    before = {
        path.relative_to(resource_root): path.read_bytes()
        for path in resource_root.rglob("*") if path.is_file()
    }
    output_root = tmp_path / "user state" / "out"
    resource_index = tmp_path / "user state" / "aa_resources.json"
    resource_index.parent.mkdir(parents=True)
    resource_index.write_text(
        json.dumps({"bg": {"BG_Black": 0}, "characters": []}),
        encoding="utf-8",
    )
    store = temp_draft_store
    token = "packaged-user-root"
    store.create_draft(token=token, text="旁白: 发布验收。\n", project="发布验收")
    captured = {}

    def compile_fixture(options):
        captured.update(options)
        generated = Path(options["output_root"]) / "compiler-output"
        project = generated / "project"
        project.mkdir(parents=True)
        aap = generated / "release.aap"
        aap.write_bytes(b"aap")
        return {"aap_file": str(aap), "project_dir": str(project)}

    monkeypatch.setattr(build_bundle, "HERE", resource_root)
    monkeypatch.setattr(build_bundle, "compile_script", compile_fixture)
    manager = BuildBundleManager(
        store=store,
        output_root=output_root,
        resource_index_path=resource_index,
    )

    build_id = manager.create_compile_snapshot(token=token, expected_draft_version=1)
    result = manager.execute_build_worker(token=token, build_id=build_id)

    assert captured["output_root"] == str(output_root)
    assert captured["aa_data"] is None
    snapshot = store.get_draft_path(token) / "builds" / "1" / build_id / "project"
    assert Path(result["bundle_dir"]) == snapshot.parent
    after = {
        path.relative_to(resource_root): path.read_bytes()
        for path in resource_root.rglob("*") if path.is_file()
    }
    assert after == before


def test_build_worker_passes_the_selected_aa_data_to_the_compiler(
    temp_draft_store, tmp_path, monkeypatch
):
    aa_data = tmp_path / "external AA" / "data"
    for name in ("projects", "saves", "overrides"):
        (aa_data / name).mkdir(parents=True, exist_ok=True)
    store = temp_draft_store
    token = "selected-aa-data"
    store.create_draft(token=token, text="旁白: 路径必须保留。\n", project="Selected")
    draft_dir = store.get_draft_path(token)
    (draft_dir / "cast.json").write_text(
        json.dumps({"cast": {"旁白": {"narrator": True}}}), encoding="utf-8"
    )
    (draft_dir / "resources.json").write_text(
        json.dumps({"bg": {"BG_Black": 0}, "characters": [], "enums": {"emoticon": {}, "action": {}, "appear": {}, "shape": {}}}),
        encoding="utf-8",
    )
    captured = {}

    def compile_fixture(options):
        captured.update(options)
        generated = tmp_path / "compiler-output"
        project = generated / "project"
        project.mkdir(parents=True)
        aap = generated / "selected.aap"
        aap.write_bytes(b"aap")
        return {"aap_file": str(aap), "project_dir": str(project)}

    monkeypatch.setattr(build_bundle, "compile_script", compile_fixture)
    manager = BuildBundleManager(store=store, aa_data=aa_data)
    build_id = manager.create_compile_snapshot(token=token, expected_draft_version=1)
    manager.execute_build_worker(token=token, build_id=build_id)

    assert captured["aa_data"] == str(aa_data)


def test_compile_script_respects_explicit_non_install_output_root(tmp_path):
    script = tmp_path / "story.txt"
    script.write_text("旁白: 发布验收。\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({"cast": {"旁白": {"narrator": True}}}), encoding="utf-8")
    index = tmp_path / "resources.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 0}, "characters": [],
        "enums": {"emoticon": {}, "action": {}, "appear": {}, "shape": {}},
    }), encoding="utf-8")
    output_root = tmp_path / "user-state" / "out"
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides"):
        (aa_data / name).mkdir(parents=True, exist_ok=True)

    from script2aap import compile_script

    result = compile_script({
        "script": str(script), "out": "Demo", "cast": str(cast), "index": str(index),
        "output_root": str(output_root), "aa_data": str(aa_data), "install": False,
    })

    assert Path(result["aap_file"]) == output_root / "Demo.aap"
    assert Path(result["project_dir"]) == output_root / "Demo"
