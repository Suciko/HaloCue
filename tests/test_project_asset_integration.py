import json
import wave
from pathlib import Path

from PIL import Image

from aa_registry import (
    register_background,
    register_character,
    register_sound,
)
from asset_validation import (
    validate_background,
    validate_sound,
    validate_spine,
)
from verify import verify_project_assets


def make_wav(path: Path):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(b"\0" * 2205)


def make_spine(root: Path):
    root.mkdir()
    stem = "CH0335_noweapon_spr"
    (root / f"{stem}.skel").write_bytes(b"\0spine\04.2.33\0")
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize:8,8\nformat:RGBA8888\n"
        "00_default\nbounds:0,0,1,1\n03_smile\nbounds:1,1,1,1\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8)).save(root / f"{stem}.png")
    Image.new("RGBA", (4, 4)).save(root / f"{stem}-avatar.png")
    return root


def make_aap(path: Path, bg_stem: str, bg_key: int, sound: str, ident: str):
    script = {
        "bgFriendlyName": bg_stem,
        "bgName": bg_key,
        "sound": sound,
        "characters": {
            "$values": [
                {
                    "name": ident,
                    "faceId": "03",
                    "action": 1,
                }
            ]
        },
    }
    payload = {
        "nodes": {
            "$values": [
                {
                    "Scripts": {
                        "$values": [script],
                    }
                }
            ]
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_combined_custom_asset_project_has_closed_references(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    bg = source / "实验背景.png"
    Image.new("RGB", (16, 9), "navy").save(bg)
    sound = source / "实验音效.wav"
    make_wav(sound)
    spine = make_spine(source / "kai")
    project = tmp_path / "AA自动素材-组合测试"

    bg_result = validate_background(bg)
    register_background(bg_result, project)
    register_sound(validate_sound(sound), project)
    register_character(
        validate_spine(spine, identifier="1516544"),
        project,
        display_name="凯伊",
    )
    aap = tmp_path / "AA自动素材-组合测试.aap"
    make_aap(aap, bg.stem, bg_result.candidate.aa_key, sound.stem, "1516544")

    report = verify_project_assets(aap, project)

    assert report.ok
    assert report.errors == ()


def test_missing_registered_sound_is_reported(tmp_path):
    source = tmp_path / "sound.wav"
    make_wav(source)
    project = tmp_path / "project"
    register_sound(validate_sound(source), project)
    aap = tmp_path / "project.aap"
    make_aap(aap, "BG_Black", 1047754314, "sound", "")
    (project / "sounds" / "sound.wav").unlink()

    report = verify_project_assets(aap, project)

    assert not report.ok
    assert any("音效文件不存在" in message for message in report.errors)
