# -*- coding: utf-8 -*-
import hashlib
import json
import wave
from pathlib import Path

import pytest
from PIL import Image

from aa_project_assets import AAProjectTarget, resolve_project_target
from aa_registry import AssetRegistrationError, register_background, register_character, register_sound
from asset_validation import validate_background, validate_sound, validate_spine


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wav(path: Path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(b"\0" * 2205)


def _spine(root: Path, stem: str = "kai") -> Path:
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"\0spine\0" + b"4.2.33\0")
    (root / f"{stem}.atlas").write_text(f"{stem}.png\nsize:8,8\n", encoding="utf-8")
    Image.new("RGBA", (8, 8), "white").save(root / f"{stem}.png")
    Image.new("RGBA", (4, 4), "white").save(root / f"{stem}-avatar.png")
    return root


def _target(tmp_path: Path) -> AAProjectTarget:
    return resolve_project_target(tmp_path / "data" / "projects" / "Demo")


def test_resolves_exact_projects_layout_to_matching_save_directory(tmp_path):
    target = _target(tmp_path)

    assert target.project_dir == (tmp_path / "data" / "projects" / "Demo").resolve()
    assert target.save_dir == (tmp_path / "data" / "saves" / "Demo").resolve()
    assert target.project_name == "Demo"


def test_direct_target_requires_safe_components_and_rejects_empty_name(tmp_path):
    target = AAProjectTarget(tmp_path / "project" / "Demo", tmp_path / "save" / "Demo", "Demo")

    assert target.project_dir == (tmp_path / "project" / "Demo").resolve()
    assert target.save_dir == (tmp_path / "save" / "Demo").resolve()
    with pytest.raises(ValueError, match="name"):
        AAProjectTarget(tmp_path / "project", tmp_path / "save", "   ")
    with pytest.raises(ValueError, match="safe Windows"):
        AAProjectTarget(tmp_path / "project" / ".." / "Demo", tmp_path / "save" / "Demo", "Demo")


def test_resolves_explicit_saves_root(tmp_path):
    target = resolve_project_target(tmp_path / "scratch" / "Demo", saves_root=tmp_path / "custom-saves")

    assert target.save_dir == (tmp_path / "custom-saves" / "Demo").resolve()


def test_rejects_unrelated_directory_without_explicit_saves_root(tmp_path):
    with pytest.raises(ValueError, match="projects"):
        resolve_project_target(tmp_path / "scratch" / "Demo")


def test_background_is_registered_in_project_and_save_mirrors(tmp_path):
    source = tmp_path / "source" / "night.png"
    source.parent.mkdir()
    Image.new("RGB", (16, 9), "navy").save(source)
    target = _target(tmp_path)

    installed = register_background(validate_background(source), target, running_probe=lambda: False)

    assert installed.install_paths == (target.project_dir / "bgs" / "night.png", target.save_dir / "bgs" / "night.png")
    assert installed.manifest_paths == (target.project_dir / "manifest.json", target.save_dir / "manifest.json")
    for directory in (target.project_dir, target.save_dir):
        assert (directory / "bgs" / "night.png").is_file()
        assert json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["BgOverrides"] == [r"bgs\night.png"]


def test_sound_conflict_in_either_mirror_creates_no_file_in_other_mirror(tmp_path):
    source = tmp_path / "source" / "door.wav"
    source.parent.mkdir()
    _wav(source)
    target = _target(tmp_path)
    conflict = target.save_dir / "sounds" / "door.wav"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"conflict")

    with pytest.raises(AssetRegistrationError):
        register_sound(validate_sound(source), target, running_probe=lambda: False)

    assert not (target.project_dir / "sounds" / "door.wav").exists()
    assert conflict.read_bytes() == b"conflict"
    assert not (target.project_dir / "manifest.json").exists()
    assert not (target.save_dir / "manifest.json").exists()


def test_sound_is_registered_in_project_and_save_mirrors(tmp_path):
    source = tmp_path / "source" / "door.wav"
    source.parent.mkdir()
    _wav(source)
    target = _target(tmp_path)

    installed = register_sound(validate_sound(source), target, running_probe=lambda: False)

    assert installed.install_paths == (
        target.project_dir / "sounds" / "door.wav",
        target.save_dir / "sounds" / "door.wav",
    )
    for directory in (target.project_dir, target.save_dir):
        assert (directory / "sounds" / "door.wav").read_bytes() == source.read_bytes()
        assert json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["SoundOverrides"] == [r"sounds\door.wav"]


def test_project_mirror_conflict_creates_no_save_file_or_manifests(tmp_path):
    source = tmp_path / "source" / "door.wav"
    source.parent.mkdir()
    _wav(source)
    target = _target(tmp_path)
    conflict = target.project_dir / "sounds" / "door.wav"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"project conflict")

    with pytest.raises(AssetRegistrationError):
        register_sound(validate_sound(source), target, running_probe=lambda: False)

    assert conflict.read_bytes() == b"project conflict"
    assert not (target.save_dir / "sounds" / "door.wav").exists()
    assert not (target.project_dir / "manifest.json").exists()
    assert not (target.save_dir / "manifest.json").exists()


def test_character_is_registered_in_both_mirrors_with_user_identity(tmp_path):
    target = _target(tmp_path)
    source = _spine(tmp_path / "source")
    result = validate_spine(source, identifier="92707271")

    register_character(result, target, display_name="宸垎鍑紛7F3A91", nickname="鍘熺敓瀵煎叆娴嬭瘯", running_probe=lambda: False)

    for directory in (target.project_dir, target.save_dir):
        entry = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["CharacterOverrides"][0]
        assert {key: entry[key] for key in ("Identifier", "Name", "Nickname")} == {
            "Identifier": "92707271", "Name": "宸垎鍑紛7F3A91", "Nickname": "鍘熺敓瀵煎叆娴嬭瘯"
        }
        for filename in ("kai.skel", "kai.atlas", "kai.png", "kai-avatar.png"):
            assert (directory / "characters" / "92707271" / filename).is_file()


def test_character_same_identifier_rejects_changed_name_before_writing_either_mirror(tmp_path):
    target = _target(tmp_path)
    source = _spine(tmp_path / "source")
    result = validate_spine(source, identifier="92707271")
    register_character(result, target, display_name="First", nickname="Alias", running_probe=lambda: False)
    before = {path: path.read_bytes() for path in (target.project_dir / "manifest.json", target.save_dir / "manifest.json")}

    with pytest.raises(AssetRegistrationError, match="Identifier"):
        register_character(result, target, display_name="Different", nickname="Alias", running_probe=lambda: False)

    assert {path: path.read_bytes() for path in before} == before


def test_character_same_identifier_rejects_changed_nickname_before_writing_either_mirror(tmp_path):
    target = _target(tmp_path)
    source = _spine(tmp_path / "source")
    result = validate_spine(source, identifier="92707271")
    register_character(result, target, display_name="Same", nickname="First alias", running_probe=lambda: False)
    before = {path: path.read_bytes() for path in (target.project_dir / "manifest.json", target.save_dir / "manifest.json")}

    with pytest.raises(AssetRegistrationError, match="Identifier"):
        register_character(result, target, display_name="Same", nickname="Second alias", running_probe=lambda: False)

    assert {path: path.read_bytes() for path in before} == before
