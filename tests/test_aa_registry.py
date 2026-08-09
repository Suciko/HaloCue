import hashlib
import json
import wave
from pathlib import Path

import pytest
from PIL import Image

import aa_registry
from aa_project_assets import AAProjectTarget
from aa_registry import (
    AssetRegistrationError,
    AssetRemovalError,
    load_manifest,
    register_background,
    register_character,
    register_sound,
    remove_registered_asset,
)
from asset_validation import (
    validate_background,
    validate_sound,
    validate_spine,
)


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_wav(path: Path):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(b"\0" * 2205)


def make_spine(root: Path, stem: str, color: str):
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"\0spine\0" + b"4.2.33\0" + color.encode())
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize:8,8\nformat:RGBA8888\n00_default\nbounds:0,0,1,1\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8), color).save(root / f"{stem}.png")
    Image.new("RGBA", (4, 4), color).save(root / f"{stem}-avatar.png")
    return root


def test_background_registration_is_project_private_and_idempotent(tmp_path):
    source = tmp_path / "source" / "夜景.png"
    source.parent.mkdir()
    Image.new("RGB", (16, 9), "navy").save(source)
    original = sha256(source)
    project = tmp_path / "project"
    result = validate_background(source)

    first = register_background(result, project)
    manifest_bytes = (project / "manifest.json").read_bytes()
    installed_bytes = (project / "bgs" / "夜景.png").read_bytes()
    second = register_background(result, project)

    assert first.changed
    assert not second.changed
    assert first.install_paths == (project / "bgs" / source.name,)
    assert first.manifest_paths == (project / "manifest.json",)
    assert sha256(source) == original
    assert (project / "manifest.json").read_bytes() == manifest_bytes
    assert (project / "bgs" / "夜景.png").read_bytes() == installed_bytes
    assert load_manifest(project)["BgOverrides"] == [r"bgs\夜景.png"]


def test_sound_registration_uses_stem_and_rejects_conflicting_content(tmp_path):
    source = tmp_path / "source" / "敲门.wav"
    source.parent.mkdir()
    make_wav(source)
    project = tmp_path / "project"

    installed = register_sound(validate_sound(source), project)

    assert installed.aa_key == "敲门"
    assert load_manifest(project)["SoundOverrides"] == [r"sounds\敲门.wav"]

    other = tmp_path / "other" / "敲门.wav"
    other.parent.mkdir()
    make_wav(other)
    other.write_bytes(other.read_bytes() + b"different")
    with pytest.raises(AssetRegistrationError, match="同名"):
        register_sound(validate_sound(other), project)


def test_character_registration_preserves_user_identifier(tmp_path):
    source = make_spine(tmp_path / "kai", "CH0335_noweapon_spr", "white")
    project = tmp_path / "project"

    installed = register_character(
        validate_spine(source, identifier="1516544"),
        project,
        display_name="凯伊",
        nickname="特殊现象调查部",
    )
    entry = load_manifest(project)["CharacterOverrides"][0]

    assert installed.aa_key == "1516544"
    assert entry["Identifier"] == "1516544"
    assert entry["Name"] == "凯伊"
    assert entry["SpinePortraitPath"] == (
        r"characters\1516544\CH0335_noweapon_spr"
    )
    assert entry["SmallPortraitPath"] == (
        r"characters\1516544\CH0335_noweapon_spr-avatar.png"
    )
    for suffix in (".skel", ".atlas", ".png", "-avatar.png"):
        assert (
            project
            / "characters"
            / "1516544"
            / f"CH0335_noweapon_spr{suffix}"
        ).is_file()


def test_character_identifier_cannot_be_reused_for_different_content(tmp_path):
    first = make_spine(tmp_path / "first", "kai", "white")
    second = make_spine(tmp_path / "second", "kai", "red")
    project = tmp_path / "project"
    register_character(
        validate_spine(first, identifier="1516544"),
        project,
        display_name="凯伊",
    )

    with pytest.raises(AssetRegistrationError, match="Identifier"):
        register_character(
            validate_spine(second, identifier="1516544"),
            project,
            display_name="凯伊（另一套）",
        )


def _paired_target(tmp_path: Path, project: str = "Chapter") -> AAProjectTarget:
    return AAProjectTarget(
        tmp_path / "aa-data" / "projects" / project,
        tmp_path / "aa-data" / "saves" / project,
        project,
    )


def test_remove_registered_background_updates_both_manifests_and_files(tmp_path):
    """Leaving either AA mirror registered would make the story copy inconsistent."""
    source = tmp_path / "source" / "rain_roof.png"
    source.parent.mkdir()
    Image.new("RGB", (16, 9), "navy").save(source)
    validation = validate_background(source)
    target = _paired_target(tmp_path)
    register_background(validation, target, running_probe=lambda: False)

    result = remove_registered_asset(
        target,
        kind="background",
        aa_key="rain_roof",
        expected_sha256=validation.candidate.sha256,
        running_probe=lambda: False,
    )

    assert result.changed is True
    for root in (target.project_dir, target.save_dir):
        assert load_manifest(root)["BgOverrides"] == []
        assert not (root / "bgs" / "rain_roof.png").exists()


def test_remove_registered_asset_rolls_back_files_and_manifests_on_failure(
    tmp_path, monkeypatch
):
    """A failed second manifest write must restore both mirrors and their files."""
    source = tmp_path / "source" / "door_open.wav"
    source.parent.mkdir()
    make_wav(source)
    validation = validate_sound(source)
    target = _paired_target(tmp_path)
    register_sound(validation, target, running_probe=lambda: False)
    original_write = aa_registry.write_manifest_atomic
    calls = 0

    def fail_second_manifest(directory, manifest):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second manifest failure")
        return original_write(directory, manifest)

    monkeypatch.setattr(aa_registry, "write_manifest_atomic", fail_second_manifest)

    with pytest.raises(AssetRemovalError):
        remove_registered_asset(
            target,
            kind="sound",
            aa_key="door_open",
            expected_sha256=validation.candidate.sha256,
            running_probe=lambda: False,
        )

    for root in (target.project_dir, target.save_dir):
        assert load_manifest(root)["SoundOverrides"] == [r"sounds\door_open.wav"]
        assert (root / "sounds" / "door_open.wav").is_file()
