"""Runtime and public settings must choose the same synthetic local paths."""

import json
from dataclasses import replace

import pytest

from halocue_production.service import ProductionService
from halocue_production import spine_rendering


@pytest.fixture
def service(settings, tmp_path):
    assert settings.legacy_root.is_relative_to(tmp_path)
    instance = ProductionService(settings)
    yield instance
    instance.jobs.close()


def executable(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"synthetic placeholder: never execute")
    return path.resolve()


def workspace(tmp_path, name):
    path = tmp_path / name
    for child in ("projects", "saves", "overrides", "settings"):
        (path / child).mkdir(parents=True)
    return path.resolve()


def test_saved_spine_path_overrides_environment_and_legacy_fallback(service, tmp_path, monkeypatch):
    env = executable(tmp_path, "env.com")
    saved = executable(tmp_path, "saved.com")
    legacy = executable(tmp_path, "legacy.com")
    monkeypatch.setenv("HALOCUE_SPINE_CLI", str(env))
    (service.settings.legacy_root / "aa_config.json").write_text(
        json.dumps({"spine_cli": str(legacy)}), encoding="utf-8"
    )
    result = service.configure_spine_cli({"path": str(saved)})
    assert result["spine_cli"]["path"] == str(saved)
    assert (
        spine_rendering.resolve_cli(
            legacy_root=service.settings.legacy_root, data_dir=service.settings.data_dir
        )
        == saved
    )
    assert result["spine_cli"]["source"] == "settings"
    assert result["spine_cli"]["effective_path"] == str(saved)


def test_missing_saved_spine_path_never_silently_runs_environment_binary(
    service, tmp_path, monkeypatch
):
    env = executable(tmp_path, "env.com")
    saved = executable(tmp_path, "saved.com")
    monkeypatch.setenv("HALOCUE_SPINE_CLI", str(env))
    service.configure_spine_cli({"path": str(saved)})
    saved.unlink()
    result = service.spine_cli_settings()
    assert result["spine_cli"]["valid"] is False
    assert result["spine_cli"]["source"] == "settings"
    assert result["spine_cli"]["effective_path"] is None
    assert result["capability"]["state"] == "not_configured"
    assert (
        spine_rendering.resolve_cli(
            legacy_root=service.settings.legacy_root, data_dir=service.settings.data_dir
        )
        is None
    )


def test_clear_spine_restores_reported_environment_path(service, tmp_path, monkeypatch):
    env = executable(tmp_path, "env.com")
    saved = executable(tmp_path, "saved.com")
    monkeypatch.setenv("HALOCUE_SPINE_CLI", str(env))
    service.configure_spine_cli({"path": str(saved)})
    result = service.configure_spine_cli({"clear": True})
    assert result["spine_cli"]["path"] == str(env)
    assert result["spine_cli"]["source"] == "environment"
    assert result["spine_cli"]["persisted_path"] is None
    assert (
        spine_rendering.resolve_cli(
            legacy_root=service.settings.legacy_root, data_dir=service.settings.data_dir
        )
        == env
    )


def test_aa_override_status_explains_restart_without_changing_explicit_startup_path(
    settings, tmp_path
):
    assert settings.legacy_root.is_relative_to(tmp_path)
    startup = workspace(tmp_path, "startup")
    saved = workspace(tmp_path, "saved")
    value = replace(settings, aa_data=startup)
    service = ProductionService(value)
    try:
        changed = service.configure_aa_workspace({"path": str(saved)})["aa_workspace"]
        assert changed["path"] == str(saved)
        assert changed["persisted_path"] == str(saved)
        assert changed["startup_path"] == str(startup)
        assert changed["restart_path"] == str(startup)
        assert changed["session_override"] is True
        assert changed["source"] == "settings_session_override"
    finally:
        service.jobs.close()
    restarted = ProductionService(value)
    try:
        result = restarted.aa_workspace_settings()["aa_workspace"]
        assert result["path"] == str(startup)
        assert result["persisted_path"] == str(saved)
        assert result["source"] == "startup"
        assert result["startup_overrides_saved"] is True
    finally:
        restarted.jobs.close()


def test_without_startup_override_saved_aa_path_survives_restart(service, tmp_path):
    saved = workspace(tmp_path, "saved")
    result = service.configure_aa_workspace({"path": str(saved)})["aa_workspace"]
    assert result["restart_path"] == str(saved)
    assert result["session_override"] is False
    restarted = ProductionService(
        service.settings.__class__(**{**service.settings.__dict__, "aa_data": None})
    )
    try:
        assert restarted.aa_workspace_settings()["aa_workspace"]["path"] == str(saved)
        assert restarted.aa_workspace_settings()["aa_workspace"]["source"] == "settings"
    finally:
        restarted.jobs.close()


@pytest.mark.parametrize("source_name", ["environment", "legacy_config", "data_config"])
def test_fallback_selection_reports_the_same_path_as_execution(
    service, tmp_path, monkeypatch, source_name
):
    monkeypatch.delenv("HALOCUE_SPINE_CLI", raising=False)
    monkeypatch.delenv("SPINE_CLI", raising=False)
    path = executable(tmp_path, "fallback.com")
    if source_name == "environment":
        monkeypatch.setenv("SPINE_CLI", str(path))
    else:
        directory = (
            service.settings.legacy_root
            if source_name == "legacy_config"
            else service.settings.data_dir
        )
        (directory / "aa_config.json").write_text(
            json.dumps({"spine_cli": str(path)}), encoding="utf-8"
        )
    status = service.spine_cli_settings()["spine_cli"]
    assert status["source"] == source_name
    assert status["path"] == status["effective_path"] == str(path)
    assert (
        spine_rendering.resolve_cli(
            legacy_root=service.settings.legacy_root, data_dir=service.settings.data_dir
        )
        == path
    )


def test_saved_spine_is_the_exact_argument_given_to_renderer(service, tmp_path, monkeypatch):
    from types import SimpleNamespace

    saved = executable(tmp_path, "saved.com")
    env = executable(tmp_path, "env.com")
    monkeypatch.setenv("HALOCUE_SPINE_CLI", str(env))
    service.configure_spine_cli({"path": str(saved)})
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "student.skel").write_bytes(b"synthetic")
    (bundle / "student.atlas").write_bytes(b"synthetic")
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"synthetic evidence; not an executable")
    captured = []

    def render(*args, **kwargs):
        captured.append(kwargs["spine_cli"])
        return SimpleNamespace(
            faces=[SimpleNamespace(face_id="01", head_path=preview)],
            calibration=[],
            cache_dir=tmp_path,
            cached=False,
        )

    monkeypatch.setattr(
        spine_rendering,
        "_legacy_module",
        lambda name, root: SimpleNamespace(render_face_variations=render),
    )
    spine_rendering.render_preview(
        source=bundle,
        legacy_root=service.settings.legacy_root,
        data_dir=service.settings.data_dir,
        metadata={},
    )
    assert captured == [saved]
    assert service.spine_cli_settings()["spine_cli"]["effective_path"] == str(saved)


def test_invalid_selected_spine_does_not_load_or_execute_renderer(service, tmp_path, monkeypatch):
    from halocue_production.errors import ProductionError

    path = executable(tmp_path, "gone.com")
    service.configure_spine_cli({"path": str(path)})
    path.unlink()
    monkeypatch.setattr(
        spine_rendering,
        "_legacy_module",
        lambda *args: pytest.fail("must not load renderer or fallback"),
    )
    with pytest.raises(ProductionError) as rejected:
        spine_rendering.render_preview(
            source=tmp_path,
            legacy_root=service.settings.legacy_root,
            data_dir=service.settings.data_dir,
            metadata={},
        )
    assert rejected.value.code == "asset_spine_render_not_configured"


def test_startup_and_saved_aa_same_path_is_not_temporary(settings, tmp_path):
    path = workspace(tmp_path, "same")
    service = ProductionService(replace(settings, aa_data=path))
    try:
        result = service.configure_aa_workspace({"path": str(path)})["aa_workspace"]
        assert result["path"] == result["startup_path"] == result["restart_path"] == str(path)
        assert result["session_override"] is False
        assert result["startup_overrides_saved"] is False
    finally:
        service.jobs.close()


def test_invalid_saved_aa_workspace_is_not_reported_as_restart_target(service, tmp_path):
    saved = workspace(tmp_path, "missing-required-directory")
    service.configure_aa_workspace({"path": str(saved)})
    (saved / "projects").rmdir()
    status = service.aa_workspace_settings()["aa_workspace"]
    assert status["persisted_path"] == str(saved)
    assert status["valid"] is False
    assert status["restart_path"] is None
    restarted = ProductionService(replace(service.settings, aa_data=None))
    try:
        result = restarted.aa_workspace_settings()["aa_workspace"]
        assert result["path"] is result["restart_path"] is None
        assert result["persisted_path"] == str(saved)
    finally:
        restarted.jobs.close()


@pytest.mark.parametrize("source", ["legacy_config", "data_config", "environment"])
def test_fallback_provenance_matches_whitespace_normalization(
    service, tmp_path, monkeypatch, source
):
    path = executable(tmp_path, "trimmed.com")
    monkeypatch.setenv("HALOCUE_SPINE_CLI", str(tmp_path / "missing.com"))
    monkeypatch.delenv("SPINE_CLI", raising=False)
    if source == "environment":
        monkeypatch.setenv("SPINE_CLI", f"  {path}  ")
    else:
        directory = (
            service.settings.legacy_root if source == "legacy_config" else service.settings.data_dir
        )
        (directory / "aa_config.json").write_text(
            json.dumps({"spine_cli": f"  {path}  "}), encoding="utf-8"
        )
    status = service.spine_cli_settings()["spine_cli"]
    assert status["effective_path"] == str(path)
    assert status["source"] == source


@pytest.mark.parametrize("legacy_available", [True, False])
def test_fallback_preserves_legacy_first_config_key_policy(
    service, tmp_path, monkeypatch, legacy_available
):
    monkeypatch.delenv("HALOCUE_SPINE_CLI", raising=False)
    monkeypatch.delenv("SPINE_CLI", raising=False)
    import spine_face_analysis
    from types import SimpleNamespace

    monkeypatch.setattr(spine_face_analysis, "LAYOUT", SimpleNamespace(frozen=False))
    legacy = executable(tmp_path, "legacy.com")
    data = executable(tmp_path, "data.com")
    if not legacy_available:
        legacy.unlink()
    for directory, path in (
        (service.settings.legacy_root, legacy),
        (service.settings.data_dir, data),
    ):
        (directory / "aa_config.json").write_text(
            json.dumps({"spine_cli": str(path)}), encoding="utf-8"
        )
    status = service.spine_cli_settings()["spine_cli"]
    assert status["source"] == ("legacy_config" if legacy_available else "none")
    assert status["effective_path"] == (str(legacy) if legacy_available else None)
    assert spine_rendering.resolve_cli(
        legacy_root=service.settings.legacy_root, data_dir=service.settings.data_dir
    ) == (legacy if legacy_available else None)
