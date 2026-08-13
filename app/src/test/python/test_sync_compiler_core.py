from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "sync-compiler-core.ps1"
SYNCED_FILES = (
    "script2aap.py",
    "stage.py",
    "camera.py",
    "performance_rules.py",
    "tables.py",
    "aapaths.py",
    "aa_install_discovery.py",
    "background_requests.py",
    "aa_registry.py",
    "aa_project_assets.py",
    "asset_validation.py",
    "asset_models.py",
    "document.py",
    "diagnostics.py",
    "cast.json",
    "aa_resources.json",
)


def test_sync_injects_android_alias_boundary_with_mixed_line_endings(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for name in SYNCED_FILES:
        (source / name).write_text("{}" if name.endswith(".json") else "", encoding="utf-8")

    fixture = (
        'import sys\r\nsys.stdout.reconfigure(encoding="utf-8")\r\n'
        "\ndef restore_registered_cast_assets(cast, aa_data):\n    return cast\n"
        "\r\ndef main():\r\n"
        "        scenes = build(events, cfg, cast, idx, project)\r\n"
        "        flat = [s for _, ss in scenes for s in ss]\r\n"
    )
    (source / "script2aap.py").write_bytes(fixture.encode("utf-8"))

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-SourceRoot",
            str(source),
            "-DestinationRoot",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    synced = (destination / "script2aap.py").read_text(encoding="utf-8")
    assert "def apply_identifier_aliases(scenes, aliases):" in synced
    assert "def identifier_aliases_for_cast(index, cast_config):" in synced
    assert "apply_identifier_aliases(scenes, identifier_aliases_for_cast(idx, cfg))" in synced
    compile(synced, str(destination / "script2aap.py"), "exec")
