import json
import os
from pathlib import Path

from aa_install_discovery import discover_aa
from runtime_paths import ensure_user_database, resolve_runtime_layout
from spine_face_analysis import resolve_spine_cli


def _make_data(root: Path) -> Path:
    data = root / "data"
    (data / "projects").mkdir(parents=True)
    return data


def _make_install(root: Path) -> Path:
    executable = root / "App" / "AzureArchive.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    app_info = executable.parent / "AzureArchive_Data" / "app.info"
    app_info.parent.mkdir()
    app_info.write_text("foxxlight\nAzureArchive\n", encoding="utf-8")
    return executable


def test_source_layout_uses_module_resources_and_user_data_override(tmp_path):
    resource_root = tmp_path / "program"
    module_file = resource_root / "runtime_paths.py"
    user_root = tmp_path / "portable-state"

    layout = resolve_runtime_layout(
        module_file=module_file,
        environ={"HALOCUE_USER_DATA_DIR": str(user_root)},
    )

    assert layout.resource_root == resource_root.resolve()
    assert layout.user_data_root == user_root.resolve()
    assert layout.config_path == user_root.resolve() / "aa_config.json"
    assert layout.legacy_config_path == resource_root.resolve() / "aa_config.json"
    assert layout.database_path == user_root.resolve() / "aa_assets.db"
    assert layout.database_seed_path == resource_root.resolve() / "aa_assets.db"
    assert layout.resource_index_path == user_root.resolve() / "aa_resources.json"
    assert layout.model_profiles_path == user_root.resolve() / "llm_profiles.json"
    assert layout.output_root == user_root.resolve() / "out"
    assert layout.thumbs_root == user_root.resolve() / ".thumbs"
    assert not user_root.exists()


def test_default_windows_state_uses_localappdata_halocue(tmp_path):
    local_app_data = tmp_path / "LocalAppData"

    layout = resolve_runtime_layout(
        module_file=tmp_path / "program" / "runtime_paths.py",
        environ={"LOCALAPPDATA": str(local_app_data)},
    )

    assert layout.user_data_root == (local_app_data / "HaloCue").resolve()


def test_frozen_layout_uses_explicit_bundle_resource_root(tmp_path):
    bundle = tmp_path / "bundle"
    executable = tmp_path / "installed" / "HaloCue.exe"

    layout = resolve_runtime_layout(
        module_file=tmp_path / "source" / "runtime_paths.py",
        executable=executable,
        frozen_root=bundle,
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )

    assert layout.resource_root == bundle.resolve()
    assert layout.database_seed_path == bundle.resolve() / "aa_assets.db"
    assert layout.legacy_config_path == executable.parent.resolve() / "aa_config.json"


def test_frozen_layout_uses_meipass_when_available(tmp_path, monkeypatch):
    bundle = tmp_path / "meipass"
    monkeypatch.setattr("sys._MEIPASS", str(bundle), raising=False)

    layout = resolve_runtime_layout(
        module_file=tmp_path / "source" / "runtime_paths.py",
        executable=tmp_path / "HaloCue.exe",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )

    assert layout.resource_root == bundle.resolve()


def test_database_seed_is_copied_once_without_overwriting_user_edits(tmp_path):
    resource_root = tmp_path / "program"
    resource_root.mkdir()
    seed = resource_root / "aa_assets.db"
    seed.write_bytes(b"packaged-seed")
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )

    initialized = ensure_user_database(layout)
    assert initialized == layout.database_path
    assert initialized.read_bytes() == b"packaged-seed"
    assert list(layout.user_data_root.glob("*.tmp")) == []

    initialized.write_bytes(b"user-edited")
    seed.write_bytes(b"new-packaged-seed")

    assert ensure_user_database(layout).read_bytes() == b"user-edited"


def test_legacy_config_is_fallback_and_new_saves_survive_restart(tmp_path):
    executable = _make_install(tmp_path / "AzureArchive")
    legacy_data = _make_data(tmp_path / "legacy-workspace")
    data = _make_data(tmp_path / "saved-workspace")
    cache = tmp_path / "cache"
    cache.mkdir()
    spine_cli = tmp_path / "Spine.com"
    spine_cli.write_bytes(b"spine")
    resource_root = tmp_path / "program"
    resource_root.mkdir()
    legacy = resource_root / "aa_config.json"
    legacy_payload = {"aa_data": str(legacy_data)}
    legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )

    first_run = discover_aa(
        config_path=layout.config_path,
        fallback_config_paths=(layout.legacy_config_path,),
        home=tmp_path / "home",
        environ={},
    )
    assert first_run.data == legacy_data.resolve()
    assert json.loads(legacy.read_text(encoding="utf-8")) == legacy_payload

    from aapaths import save_config

    save_config(
        data,
        executable=executable,
        cache_dir=cache,
        spine_cli=spine_cli,
        config_path=layout.config_path,
        fallback_config_paths=(layout.legacy_config_path,),
    )

    restarted = discover_aa(
        config_path=layout.config_path,
        fallback_config_paths=(layout.legacy_config_path,),
        home=tmp_path / "home",
        environ={},
    )
    assert restarted.executable == executable.resolve()
    assert restarted.data == data.resolve()
    assert restarted.resource_cache == cache.resolve()
    assert resolve_spine_cli(
        config_path=layout.config_path,
        fallback_config_paths=(layout.legacy_config_path,),
    ) == spine_cli.resolve()
    assert json.loads(legacy.read_text(encoding="utf-8")) == legacy_payload


def test_user_database_initialization_writes_nothing_beside_resources(tmp_path):
    resource_root = tmp_path / "read-only-program"
    resource_root.mkdir()
    seed = resource_root / "aa_assets.db"
    seed.write_bytes(b"seed")
    before = {path.relative_to(resource_root) for path in resource_root.rglob("*")}
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "writable-state")},
    )

    ensure_user_database(layout)

    after = {path.relative_to(resource_root) for path in resource_root.rglob("*")}
    assert after == before
    assert layout.database_path.read_bytes() == b"seed"
