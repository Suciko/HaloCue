import json
from pathlib import Path

from runtime_layout import prepare_user_state, resolve_runtime_layout


def test_frozen_layout_separates_resources_from_local_app_data(tmp_path):
    resources = tmp_path / "便携 包" / "_internal"
    executable = tmp_path / "便携 包" / "HaloCue.exe"
    local = tmp_path / "Local App Data"

    layout = resolve_runtime_layout(
        module_file=resources / "runtime_layout.py",
        executable=executable,
        environ={"LOCALAPPDATA": str(local)},
        frozen_root=resources,
    )

    assert layout.resource_root == resources.resolve()
    assert layout.user_data_root == (local / "HaloCue").resolve()
    assert layout.out_root == (local / "HaloCue" / "out").resolve()
    assert layout.config_path == (local / "HaloCue" / "aa_config.json").resolve()


def test_first_frozen_start_copies_seed_data_without_the_build_machine_path(tmp_path):
    resources = tmp_path / "resources"
    state = tmp_path / "state"
    resources.mkdir()
    (resources / "aa_assets.db").write_bytes(b"sqlite-seed")
    (resources / "aa_resources.json").write_text(
        json.dumps({"_source": r"E:\\AzureArchive\\data", "bg": {"BG_Black": 1}}),
        encoding="utf-8",
    )
    layout = resolve_runtime_layout(
        module_file=resources / "runtime_layout.py",
        executable=tmp_path / "HaloCue.exe",
        environ={"HALOCUE_USER_DATA_DIR": str(state)},
        frozen_root=resources,
    )

    prepare_user_state(layout)

    assert (state / "aa_assets.db").read_bytes() == b"sqlite-seed"
    copied_index = json.loads((state / "aa_resources.json").read_text(encoding="utf-8"))
    assert copied_index == {"_source": "", "bg": {"BG_Black": 1}}


def test_frozen_start_installs_release_overlays_without_replacing_user_settings(tmp_path):
    resources = tmp_path / "resources"
    state = tmp_path / "state"
    (resources / "databases").mkdir(parents=True)
    (resources / "aa_assets.db").write_bytes(b"primary")
    (resources / "aa_resources.json").write_text("{}", encoding="utf-8")
    (resources / "databases" / "overlay-1-aa-assets.db").write_bytes(b"overlay")
    (resources / "aa_config.seed.json").write_text(
        json.dumps({
            "pipeline": "0.95",
            "prompt_revision": "v10-canonical-emo-protocol",
            "asset_databases": ["databases/overlay-1-aa-assets.db"],
            "database_policy": "read_only_overlay",
        }),
        encoding="utf-8",
    )
    state.mkdir()
    (state / "aa_config.json").write_text(
        json.dumps({"aa_data": "E:/user/data", "custom": True}),
        encoding="utf-8",
    )
    layout = resolve_runtime_layout(
        module_file=resources / "runtime_layout.py",
        executable=tmp_path / "HaloCue.exe",
        environ={"HALOCUE_USER_DATA_DIR": str(state)},
        frozen_root=resources,
    )

    prepare_user_state(layout)

    assert (state / "databases" / "overlay-1-aa-assets.db").read_bytes() == b"overlay"
    config = json.loads((state / "aa_config.json").read_text(encoding="utf-8"))
    assert config["aa_data"] == "E:/user/data"
    assert config["custom"] is True
    assert config["pipeline"] == "0.95"
    assert config["asset_databases"] == ["databases/overlay-1-aa-assets.db"]


def test_frozen_start_upgrades_stale_resource_index_without_dropping_custom_rows(tmp_path):
    resources = tmp_path / "resources"
    state = tmp_path / "state"
    resources.mkdir()
    (resources / "aa_assets.db").write_bytes(b"primary")
    (resources / "aa_resources.json").write_text(
        json.dumps({
            "_source": r"E:\\old\\data",
            "characters": [{
                "identifier": "aris",
                "name": "旧爱丽丝",
                "spine": "old_spine",
                "faces": [{"id": "00"}],
            }, {
                "identifier": "arisuN",
                "name": "普通爱丽丝",
                "spine": "CharacterSpine_aris_noweapon",
            }],
            "sounds": ["old_sound"],
        }),
        encoding="utf-8",
    )
    state.mkdir()
    (state / "aa_resources.json").write_text(
        json.dumps({
            "_source": r"E:\\user\\data",
            "characters": [{"identifier": "custom", "name": "自定义角色"}],
            "sounds": ["old_sound"],
        }),
        encoding="utf-8",
    )
    layout = resolve_runtime_layout(
        module_file=resources / "runtime_layout.py",
        executable=tmp_path / "HaloCue.exe",
        environ={"HALOCUE_USER_DATA_DIR": str(state)},
        frozen_root=resources,
    )

    prepare_user_state(layout)

    merged = json.loads((state / "aa_resources.json").read_text(encoding="utf-8"))
    assert merged["_source"] == ""
    identifiers = [row["identifier"] for row in merged["characters"]]
    assert identifiers == ["custom", "aris", "arisuN"]
    assert merged["characters"][1]["name"] == "旧爱丽丝"
    assert merged["characters"][1]["spine"] == "old_spine"
    assert merged["sounds"] == ["old_sound"]
