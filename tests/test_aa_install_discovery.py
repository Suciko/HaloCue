import json
from pathlib import Path

from aa_install_discovery import (
    UnityIdentity,
    discover_aa,
    normalize_aa_data_path,
    read_unity_identity,
    resolve_aa_executable,
)


def make_install(root: Path, app_info: str = "foxxlight\nAzureArchive\n") -> Path:
    exe = root / "App" / "AzureArchive.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    unity_data = exe.parent / "AzureArchive_Data"
    unity_data.mkdir()
    (unity_data / "app.info").write_text(app_info, encoding="utf-8")
    catalog = unity_data / "StreamingAssets" / "aa" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}", encoding="utf-8")
    return exe


def make_data(root: Path, *optional_directories: str) -> Path:
    data = root / "data"
    (data / "projects").mkdir(parents=True)
    for name in optional_directories:
        (data / name).mkdir()
    return data


def local_settings_path(home: Path) -> Path:
    return (
        home
        / "AppData"
        / "LocalLow"
        / "foxxlight"
        / "AzureArchive"
        / "data"
        / "settings"
        / "user_settings.json"
    )


def write_local_settings(home: Path, payload: object) -> Path:
    path = local_settings_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_resolves_exe_file_app_directory_and_install_root(tmp_path):
    exe = make_install(tmp_path / "AzureArchive")

    assert resolve_aa_executable(exe) == exe.resolve()
    assert resolve_aa_executable(exe.parent) == exe.resolve()
    assert resolve_aa_executable(tmp_path / "AzureArchive") == exe.resolve()


def test_rejects_named_exe_without_unity_identity(tmp_path):
    exe = tmp_path / "AzureArchive.exe"
    exe.write_bytes(b"MZ")

    assert resolve_aa_executable(exe) is None


def test_reads_identity_after_trimming_bom_blank_lines_and_whitespace(tmp_path):
    exe = make_install(
        tmp_path / "AzureArchive",
        "\ufeff\n foxxlight \n\n AzureArchive  \n",
    )

    assert read_unity_identity(exe) == UnityIdentity(
        vendor="foxxlight", product="AzureArchive"
    )


def test_rejects_app_info_without_two_identity_lines(tmp_path):
    exe = make_install(tmp_path / "AzureArchive", "foxxlight\n")

    assert read_unity_identity(exe) is None
    assert resolve_aa_executable(exe) is None


def test_normalizes_data_directory_or_its_workspace_parent(tmp_path):
    data = make_data(tmp_path / "workspace")

    assert normalize_aa_data_path(data) == data.resolve()
    assert normalize_aa_data_path(data.parent) == data.resolve()
    assert normalize_aa_data_path(tmp_path / "missing") is None


def test_discovers_relocated_workspace_cache_and_recent_files(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    workspace = tmp_path / "disk-e" / "储存文件"
    data = make_data(workspace, "saves", "overrides", "settings")
    cache = tmp_path / "disk-e" / "资源文件"
    cache.mkdir()
    external = tmp_path / "external" / "chapter.aap"
    external.parent.mkdir()
    external.write_text("{}", encoding="utf-8")
    write_local_settings(
        home,
        {
            "workspacePath": str(workspace),
            "cachePath": str(cache),
            "visitedFiles": [
                str(external),
                str(tmp_path / "gone.aas"),
                str(tmp_path / "note.txt"),
            ],
        },
    )

    result = discover_aa(exe, home=home)

    assert result.data == data.resolve()
    assert result.projects == (data / "projects").resolve()
    assert result.saves == (data / "saves").resolve()
    assert result.overrides == (data / "overrides").resolve()
    assert result.settings == (data / "settings").resolve()
    assert result.resource_cache == cache.resolve()
    assert result.catalog == (
        exe.parent / "AzureArchive_Data" / "StreamingAssets" / "aa" / "catalog.json"
    ).resolve()
    assert result.recent_project_files == (external.resolve(),)
    assert result.source == "user_settings.workspacePath"


def test_explicit_data_selection_precedes_install_settings_and_legacy_config(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    explicit = make_data(tmp_path / "explicit")
    configured = make_data(tmp_path / "configured")
    legacy = make_data(tmp_path / "legacy")
    write_local_settings(home, {"workspacePath": str(configured.parent)})
    config = tmp_path / "aa_config.json"
    config.write_text(json.dumps({"aa_data": str(legacy)}), encoding="utf-8")

    result = discover_aa(explicit.parent, config_path=config, home=home)

    assert result.executable is None
    assert result.data == explicit.resolve()
    assert result.source == "explicit data"
    assert result.requires_selection is False


def test_ignores_malformed_or_non_object_user_settings_and_uses_legacy_config(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    legacy = make_data(tmp_path / "legacy")
    config = tmp_path / "aa_config.json"
    config.write_text(json.dumps({"aa_data": str(legacy)}), encoding="utf-8")
    settings_path = local_settings_path(home)
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{not json", encoding="utf-8")

    malformed = discover_aa(exe, config_path=config, home=home)

    assert malformed.data == legacy.resolve()
    assert malformed.source == "aa_config.json.aa_data"
    assert any(issue.code == "settings_invalid" for issue in malformed.issues)

    settings_path.write_text("[]", encoding="utf-8")
    non_object = discover_aa(exe, config_path=config, home=home)

    assert non_object.data == legacy.resolve()
    assert any(issue.code == "settings_invalid" for issue in non_object.issues)


def test_empty_workspace_path_falls_back_to_local_low_data_and_reports_missing_optionals(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    data = make_data(
        home / "AppData" / "LocalLow" / "foxxlight" / "AzureArchive"
    )
    write_local_settings(home, {"workspacePath": "   "})

    result = discover_aa(exe, home=home)

    assert result.data == data.resolve()
    assert result.source == "LocalLow data"
    assert result.saves is None
    assert result.overrides is None
    assert result.settings == local_settings_path(home).parent.resolve()
    assert any(issue.code == "optional_directory_missing" for issue in result.issues)


def test_conflicting_legacy_candidates_require_explicit_selection(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    configured = make_data(tmp_path / "configured")
    environment = make_data(tmp_path / "environment")
    config = tmp_path / "aa_config.json"
    config.write_text(json.dumps({"aa_data": str(configured)}), encoding="utf-8")

    result = discover_aa(
        exe,
        config_path=config,
        home=home,
        environ={"AA_DATA": str(environment)},
    )

    assert result.data is None
    assert result.requires_selection is True
    assert {(candidate.path, candidate.source, candidate.valid) for candidate in result.data_candidates} == {
        (configured.resolve(), "aa_config.json.aa_data", True),
        (environment.resolve(), "environment.AA_DATA", True),
    }
    assert any(issue.code == "workspace_selection_required" for issue in result.issues)


def test_ambiguous_workspaces_preserve_existing_recent_project_files(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    configured = make_data(tmp_path / "configured")
    environment = make_data(tmp_path / "environment")
    first = tmp_path / "recent" / "first.aap"
    second = tmp_path / "recent" / "second.aas"
    first.parent.mkdir()
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    config = tmp_path / "aa_config.json"
    config.write_text(json.dumps({"aa_data": str(configured)}), encoding="utf-8")
    write_local_settings(
        home,
        {
            "visitedFiles": [
                str(first),
                str(tmp_path / "missing.aap"),
                str(tmp_path / "note.txt"),
                str(second),
            ],
        },
    )

    result = discover_aa(
        exe,
        config_path=config,
        home=home,
        environ={"AA_DATA": str(environment)},
    )

    assert result.data is None
    assert result.requires_selection is True
    assert result.recent_project_files == (first.resolve(), second.resolve())


def test_authoritative_workspace_does_not_conflict_with_lower_priority_legacy_paths(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    workspace_data = make_data(tmp_path / "workspace")
    legacy = make_data(tmp_path / "legacy")
    write_local_settings(home, {"workspacePath": str(workspace_data.parent)})
    config = tmp_path / "aa_config.json"
    config.write_text(json.dumps({"aa_data": str(legacy)}), encoding="utf-8")

    result = discover_aa(exe, config_path=config, home=home)

    assert result.data == workspace_data.resolve()
    assert result.source == "user_settings.workspacePath"
    assert result.requires_selection is False
    assert result.data_candidates == (
        result.data_candidates[0],
    )
    assert result.data_candidates[0].path == workspace_data.resolve()


def test_recent_files_keep_existing_aap_and_aas_in_configuration_order_without_duplicates(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    workspace = tmp_path / "workspace"
    make_data(workspace)
    first = tmp_path / "external" / "first.aap"
    second = tmp_path / "external" / "second.aas"
    first.parent.mkdir()
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    write_local_settings(
        home,
        {
            "workspacePath": str(workspace),
            "visitedFiles": [
                str(first),
                str(first.parent / "." / first.name),
                str(second),
                str(tmp_path / "missing.aap"),
                str(tmp_path / "plain.txt"),
            ],
        },
    )

    result = discover_aa(exe, home=home)

    assert result.recent_project_files == (first.resolve(), second.resolve())
