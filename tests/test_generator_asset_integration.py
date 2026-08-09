import wave
from pathlib import Path

from PIL import Image

from aa_registry import (
    load_manifest,
    register_background,
    register_sound,
    write_manifest_atomic,
)
from asset_validation import validate_background, validate_sound
from script2aap import (
    finalize_project_manifest,
    merge_project_registered_assets,
    restore_registered_cast_assets,
)


def make_wav(path: Path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\0\0" * 2205)


def make_spine(root: Path, stem: str):
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"spine 4.2.33")
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize: 32,32\nformat: RGBA8888\n\n"
        "00_default\n  rotate: false\n"
        "03_smile\n  rotate: false\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (32, 32), "white").save(root / f"{stem}.png")
    Image.new("RGBA", (16, 16), "white").save(
        root / f"{stem}-avatar.png"
    )


def test_generator_preserves_registered_assets_and_delegates_character(tmp_path):
    project = tmp_path / "projects" / "组合工程"
    sources = tmp_path / "sources"
    sources.mkdir()
    background = sources / "带 空格的背景.png"
    Image.new("RGB", (32, 18), "navy").save(background)
    sound = sources / "齿轮声.wav"
    make_wav(sound)
    spine = sources / "凯伊骨骼"
    make_spine(spine, "CH0335_noweapon_spr")

    register_background(validate_background(background), project)
    register_sound(validate_sound(sound), project)
    cast = {
        "凯伊": {
            "id": "1516544",
            "name": "凯伊",
            "club": "特殊现象调查部",
            "portrait": True,
            "custom": {
                "src": str(spine),
                "asset": "CH0335_noweapon_spr",
            },
        }
    }

    finalize_project_manifest(
        cast,
        {"1516544"},
        story_root=tmp_path,
        project_dir=project,
        voice_overrides=[],
    )
    first = (project / "manifest.json").read_bytes()
    finalize_project_manifest(
        cast,
        {"1516544"},
        story_root=tmp_path,
        project_dir=project,
        voice_overrides=[],
    )

    manifest = load_manifest(project)
    assert manifest["BgOverrides"] == [r"bgs\带 空格的背景.png"]
    assert manifest["SoundOverrides"] == [r"sounds\齿轮声.wav"]
    assert manifest["CharacterOverrides"][0]["Identifier"] == "1516544"
    assert (project / "manifest.json").read_bytes() == first

    merged = merge_project_registered_assets(
        {"bg": {}, "sounds": [], "characters": []},
        project,
    )
    assert merged["bg"]["带 空格的背景"] == validate_background(
        background
    ).candidate.aa_key
    assert merged["sounds"] == ["齿轮声"]


def test_generator_upgrades_empty_character_placeholder_to_registered_spine(tmp_path):
    project = tmp_path / "projects" / "legacy-output"
    write_manifest_atomic(project, {
        "CharacterOverrides": [{
            "Identifier": "custom-character",
            "Name": "测试角色",
            "Nickname": "",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": None,
            "SmallPortraitPath": None,
        }],
    })
    spine = tmp_path / "spine"
    make_spine(spine, "Date_Outfit")
    cast = {"测试角色": {
        "id": "custom-character",
        "name": "测试角色",
        "club": "",
        "portrait": True,
        "custom": {"src": str(spine), "asset": "Date_Outfit"},
    }}

    finalize_project_manifest(
        cast,
        {"custom-character"},
        story_root=tmp_path,
        project_dir=project,
        voice_overrides=[],
    )

    row = load_manifest(project)["CharacterOverrides"][0]
    assert row["SpinePortraitPath"] == r"characters\custom-character\Date_Outfit"
    assert row["SmallPortraitPath"] == (
        r"characters\custom-character\Date_Outfit-avatar.png"
    )


def test_generator_does_not_write_empty_override_for_official_portrait(tmp_path):
    project = tmp_path / "projects" / "official"
    cast = {
        "官方角色": {
            "id": "official-id", "name": "官方角色", "portrait": True,
        },
        "老师": {
            "id": "teacher-id", "name": "老师", "portrait": False,
        },
    }

    finalize_project_manifest(
        cast, {"official-id", "teacher-id"},
        story_root=tmp_path, project_dir=project, voice_overrides=[],
    )

    overrides = load_manifest(project)["CharacterOverrides"]
    assert [entry["Identifier"] for entry in overrides] == ["teacher-id"]


def test_generator_refreshes_screenplay_names_in_existing_overrides(tmp_path):
    project = tmp_path / "projects" / "display-names"
    spine_dir = project / "characters" / "626652156"
    spine_dir.mkdir(parents=True)
    for suffix in (".skel", ".atlas", ".png"):
        (spine_dir / f"Kei_Date_Outfit{suffix}").write_bytes(suffix.encode("ascii"))
    (spine_dir / "Kei_Date_Outfit-avatar.png").write_bytes(b"avatar")
    write_manifest_atomic(project, {
        "CharacterOverrides": [
            {
                "Identifier": "45145456",
                "Name": "45145456",
                "Nickname": "",
                "CharacterReference": None,
                "OriginalIdentifier": None,
                "SpinePortraitPath": None,
                "SmallPortraitPath": None,
            },
            {
                "Identifier": "shop-clerk",
                "Name": "shop-clerk",
                "Nickname": "",
                "CharacterReference": None,
                "OriginalIdentifier": None,
                "SpinePortraitPath": None,
                "SmallPortraitPath": None,
            },
        ],
    })
    cast = {
        "凯伊": {
            "id": "626652156",
            "name": "凯伊",
            "portrait": True,
            "spine_signature": "registered-date-outfit",
            "outfit_key": "Kei_Date_Outfit",
        },
        "老师": {"id": "45145456", "name": "老师", "portrait": False},
        "店员": {"id": "shop-clerk", "name": "店员", "portrait": False},
    }

    finalize_project_manifest(
        cast,
        {"626652156", "45145456", "shop-clerk"},
        story_root=tmp_path,
        project_dir=project,
        voice_overrides=[],
    )

    overrides = {
        entry["Identifier"]: entry
        for entry in load_manifest(project)["CharacterOverrides"]
    }
    assert overrides["626652156"]["Name"] == "凯伊"
    assert overrides["626652156"]["SpinePortraitPath"] == (
        r"characters\626652156\Kei_Date_Outfit"
    )
    assert overrides["626652156"]["SmallPortraitPath"] == (
        r"characters\626652156\Kei_Date_Outfit-avatar.png"
    )
    assert overrides["45145456"]["Name"] == "老师"
    assert overrides["shop-clerk"]["Name"] == "店员"


def test_generator_restores_legacy_draft_custom_source_from_registered_spine(tmp_path):
    aa_data = tmp_path / "data"
    registered = aa_data / "projects" / "registered-story"
    character_dir = registered / "characters" / "custom-character"
    character_dir.mkdir(parents=True)
    stem = "Date_Outfit"
    skel = character_dir / f"{stem}.skel"
    skel.write_bytes(b"registered-spine")
    for suffix in (".atlas", ".png"):
        (character_dir / f"{stem}{suffix}").write_bytes(suffix.encode("ascii"))
    (character_dir / f"{stem}-avatar.png").write_bytes(b"avatar")
    write_manifest_atomic(registered, {
        "CharacterOverrides": [{
            "Identifier": "custom-character",
            "Name": "测试角色",
            "Nickname": "",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": rf"characters\custom-character\{stem}",
            "SmallPortraitPath": rf"characters\custom-character\{stem}-avatar.png",
        }],
    })
    import hashlib
    cast = {"测试角色": {
        "id": "custom-character",
        "name": "测试角色",
        "portrait": True,
        "spine_signature": hashlib.sha256(skel.read_bytes()).hexdigest(),
        "outfit_key": stem,
    }}

    restore_registered_cast_assets(cast, aa_data)

    assert cast["测试角色"]["custom"] == {
        "src": str(character_dir),
        "asset": stem,
    }
