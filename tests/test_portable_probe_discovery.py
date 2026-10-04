from pathlib import Path

import asset_validation


def test_missing_path_probe_never_checks_a_build_machine_drive(monkeypatch):
    monkeypatch.setattr(asset_validation.shutil, "which", lambda name: None)

    def unexpected_probe(path):
        raise AssertionError(f"implicit machine-specific path checked: {path}")

    monkeypatch.setattr(Path, "is_file", unexpected_probe)
    assert asset_validation._find_ffprobe(None) is None


def test_explicit_audio_probe_remains_supported(tmp_path, monkeypatch):
    probe = tmp_path / "tools" / "ffprobe.exe"
    probe.parent.mkdir()
    probe.write_bytes(b"synthetic probe")
    monkeypatch.setattr(asset_validation.shutil, "which", lambda name: None)
    assert asset_validation._find_ffprobe(probe) == str(probe)
