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
