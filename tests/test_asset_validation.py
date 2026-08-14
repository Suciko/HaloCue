import wave
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from asset_validation import (
    validate_background,
    validate_sound,
    validate_spine,
)


def make_wav(path: Path, *, rate=22050, channels=1, width=2):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"\0" * (rate * channels * width // 20))


def make_spine_bundle(root: Path, stem="CH0335_noweapon_spr"):
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"\x00spine\x004.2.33\x00")
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\n"
        "size:2048,2048\n"
        "format:RGBA8888\n"
        "filter:Linear,Linear\n"
        "repeat:none\n"
        "00_default\n"
        "bounds:0,0,1,1\n"
        "03_smile\n"
        "bounds:1,1,1,1\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (8, 8)).save(root / f"{stem}.png")
    Image.new("RGBA", (4, 4)).save(root / f"{stem}-avatar.png")
    return root


def test_background_returns_hand_checked_aa_hash(tmp_path):
    path = tmp_path / "ChatGPT Image 2026年7月19日 01_00_25.png"
    Image.new("RGB", (16, 9), "navy").save(path)

    result = validate_background(path)

    assert result.ok
    assert result.candidate.stem == "ChatGPT Image 2026年7月19日 01_00_25"
    assert result.candidate.aa_key == 3077983933
    assert result.candidate.metadata["mode"] == "RGB"
    assert result.candidate.metadata["width"] == 16
    assert result.candidate.metadata["height"] == 9


def test_background_rejects_casefold_name_conflict(tmp_path):
    path = tmp_path / "Scene.png"
    Image.new("RGBA", (8, 8)).save(path)

    result = validate_background(path, existing_names=["scene"])

    assert not result.ok
    assert [issue.code for issue in result.issues] == ["name_conflict"]


def test_background_rejects_cmyk_jpeg(tmp_path):
    path = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (8, 8)).save(path)

    result = validate_background(path)

    assert not result.ok
    assert result.issues[0].code == "unsupported_color_mode"


def test_pcm16_wav_uses_filename_stem_as_aa_key(tmp_path):
    path = tmp_path / "测试音效.wav"
    make_wav(path, rate=22050, channels=1, width=2)

    result = validate_sound(path)

    assert result.ok
    assert result.candidate.aa_key == "测试音效"
    assert result.candidate.metadata["codec"] == "pcm_s16le"
    assert result.candidate.metadata["sample_rate"] == 22050
    assert result.candidate.metadata["channels"] == 1
    assert result.candidate.metadata["bits_per_sample"] == 16


def test_non_pcm16_wav_reports_transcode_required(tmp_path):
    path = tmp_path / "eight-bit.wav"
    make_wav(path, width=1)

    result = validate_sound(path)

    assert not result.ok
    assert result.issues[0].code == "transcode_required"


def test_spine_requires_user_identifier(tmp_path):
    root = make_spine_bundle(tmp_path / "kai")

    result = validate_spine(root, identifier="")

    assert not result.ok
    assert result.issues[0].code == "identifier_required"


def test_spine_preserves_identifier_and_finds_atlas_faces(tmp_path):
    root = make_spine_bundle(tmp_path / "kai")

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert result.candidate.aa_key == "1516544"
    assert result.candidate.metadata["spine_version"] == "4.2.33"
    assert result.candidate.metadata["atlas_pages"] == ["CH0335_noweapon_spr.png"]
    assert result.candidate.metadata["faces"] == ["00", "03"]
    assert result.candidate.metadata["expression_status"] == "known"


def test_spine_accepts_windows_gb18030_atlas_text(tmp_path):
    root = make_spine_bundle(tmp_path / "kai")
    atlas = root / "CH0335_noweapon_spr.atlas"
    atlas.write_bytes(
        (
            "CH0335_noweapon_spr.png\n"
            "size:2048,2048\n"
            "format:RGBA8888\n"
            "凯伊(普通睁眼)\n"
            "bounds:0,0,1,1\n"
            "03_smile\n"
            "bounds:1,1,1,1\n"
        ).encode("gb18030")
    )

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert not any(issue.code == "atlas_unreadable" for issue in result.issues)
    assert result.candidate.metadata["faces"] == ["03"]


def test_spine_metadata_uses_skeleton_signature_and_keeps_atlas_as_candidate(tmp_path):
    """Changing skeleton bytes must change the variant key; atlas omission is not a rejection."""
    root = make_spine_bundle(tmp_path / "kai")
    skel = root / "CH0335_noweapon_spr.skel"
    skel.write_bytes(b"independent skeleton bytes")

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert result.candidate.metadata["spine_signature"] == hashlib.sha256(
        b"independent skeleton bytes"
    ).hexdigest()
    assert result.candidate.metadata["outfit_key"] == "CH0335_noweapon_spr"
    assert result.candidate.metadata["faces"] == ["00", "03"]
    assert "99" not in result.candidate.metadata["faces"]


def test_spine_rejects_missing_atlas_page(tmp_path):
    root = make_spine_bundle(tmp_path / "kai")
    (root / "CH0335_noweapon_spr.png").unlink()

    result = validate_spine(root, identifier="1516544")

    assert not result.ok
    assert any(issue.code == "atlas_page_missing" for issue in result.issues)


def test_spine_collects_all_atlas_pages_with_relative_subdirectories(tmp_path):
    root = make_spine_bundle(tmp_path / "multipage")
    stem = "CH0335_noweapon_spr"
    extra = root / "pages" / "effects.png"
    extra.parent.mkdir()
    Image.new("RGBA", (4, 4)).save(extra)
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\n"
        "size:2048,2048\n"
        "format:RGBA8888\n"
        "pages/effects.png\n"
        "size:512,512\n"
        "format:RGBA8888\n"
        "00_default\n"
        "bounds:0,0,1,1\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert result.candidate.metadata["atlas_pages"] == [
        f"{stem}.png",
        "pages/effects.png",
    ]
    assert result.candidate.metadata["all_files"] == {
        "skel": str((root / f"{stem}.skel").resolve()),
        "atlas": str((root / f"{stem}.atlas").resolve()),
        "atlas_page_0": str((root / f"{stem}.png").resolve()),
        "atlas_page_1": str(extra.resolve()),
        "avatar": str((root / f"{stem}-avatar.png").resolve()),
    }


def test_spine_digest_changes_when_an_atlas_page_changes(tmp_path):
    root = make_spine_bundle(tmp_path / "multipage")
    stem = "CH0335_noweapon_spr"
    page = root / "effects.png"
    Image.new("RGBA", (4, 4), "red").save(page)
    atlas = root / f"{stem}.atlas"
    atlas.write_text(
        f"{stem}.png\nsize:2048,2048\n"
        "effects.png\nsize:4,4\n",
        encoding="utf-8",
    )
    before = validate_spine(root, identifier="1516544")

    Image.new("RGBA", (4, 4), "blue").save(page)
    after = validate_spine(root, identifier="1516544")

    assert before.ok and after.ok
    assert before.candidate.sha256 != after.candidate.sha256


@pytest.mark.parametrize("page_name", ["../outside.png", "C:/outside.png"])
def test_spine_rejects_atlas_pages_outside_the_bundle(tmp_path, page_name):
    root = make_spine_bundle(tmp_path / "unsafe")
    stem = "CH0335_noweapon_spr"
    (root / f"{stem}.atlas").write_text(
        f"{page_name}\nsize:8,8\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="1516544")

    assert not result.ok
    assert any(issue.code == "atlas_page_missing" for issue in result.issues)


def test_spine_rejects_atlas_page_case_mismatch(tmp_path):
    root = make_spine_bundle(tmp_path / "case")
    stem = "CH0335_noweapon_spr"
    (root / f"{stem}.png").rename(root / "PAGE.PNG")
    (root / f"{stem}.atlas").write_text(
        "page.png\nsize:8,8\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="1516544")

    assert not result.ok
    assert any(issue.code == "atlas_page_missing" for issue in result.issues)


def test_spine_accepts_an_atlas_whose_first_page_has_a_custom_name(tmp_path):
    root = make_spine_bundle(tmp_path / "custom-page")
    stem = "CH0335_noweapon_spr"
    custom_page = root / "body-page.png"
    (root / f"{stem}.png").rename(custom_page)
    (root / f"{stem}.atlas").write_text(
        "body-page.png\nsize:8,8\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert result.candidate.metadata["files"]["texture"] == str(custom_page.resolve())


def test_spine_without_numbered_regions_marks_faces_unresolved(tmp_path):
    root = make_spine_bundle(tmp_path / "date", stem="Kei_Date_Outfit")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\n"
        "size:8,8\n"
        "format:RGBA8888\n"
        "普通睁眼\n"
        "  rotate:false\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="626652156")

    assert result.ok
    assert result.candidate.metadata["faces"] == []
    assert result.candidate.metadata["expression_status"] == "unresolved"


def test_binary_semantic_face_ids_mark_modular_character_known(
    tmp_path, monkeypatch
):
    root = make_spine_bundle(tmp_path / "date", stem="Kei_Date_Outfit")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\nsize:8,8\n普通睁眼\n  rotate:false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "spine_semantic_faces.extract_semantic_face_combinations",
        lambda _: {
            "00": {
                "face_id": "00",
                "raw_parts": ["普通睁眼"],
                "labels": ["平静"],
                "special": False,
            },
            "99": {
                "face_id": "99",
                "raw_parts": ["闭眼"],
                "labels": ["闭眼"],
                "special": True,
            },
        },
    )

    result = validate_spine(root, identifier="626652156")

    assert result.candidate.metadata["expression_status"] == "known"
    assert result.candidate.metadata["semantic_face_count"] == 2


def test_spine_classifies_numbered_complete_faces_without_semantic_parts(tmp_path):
    root = make_spine_bundle(tmp_path / "numbered")

    result = validate_spine(root, identifier="1516544")

    assert result.ok
    assert result.candidate.metadata["expression_mode"] == "numbered_composite"
    assert result.candidate.metadata["faces"] == ["00", "03"]
    assert result.candidate.metadata["expression_parts"] == []


def test_spine_extracts_semantic_modular_parts_from_chinese_atlas(tmp_path):
    root = make_spine_bundle(tmp_path / "date", stem="Kei_Date_Outfit")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\n"
        "size:8,8\n"
        "圆睁高光眼（惊讶、震惊、期待、好奇）\n"
        "  bounds:0,0,1,1\n"
        "小幅上扬嘴（微笑、开心、满意、友好）\n"
        "  bounds:1,1,1,1\n"
        "普通脸红（默认）\n"
        "  bounds:2,2,1,1\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="626652156")

    assert result.ok
    assert result.candidate.metadata["expression_mode"] == "semantic_modular"
    assert result.candidate.metadata["faces"] == []
    assert result.candidate.metadata["expression_parts"] == [
        {
            "kind": "eyes",
            "raw_name": "圆睁高光眼（惊讶、震惊、期待、好奇）",
            "labels": ["惊讶", "震惊", "期待", "好奇"],
            "source": "atlas_semantic",
        },
        {
            "kind": "mouth",
            "raw_name": "小幅上扬嘴（微笑、开心、满意、友好）",
            "labels": ["微笑", "开心", "满意", "友好"],
            "source": "atlas_semantic",
        },
        {
            "kind": "blush",
            "raw_name": "普通脸红（默认）",
            "labels": ["默认"],
            "source": "atlas_semantic",
        },
    ]


def test_spine_classifies_unlabeled_regions_as_opaque_custom(tmp_path):
    root = make_spine_bundle(tmp_path / "opaque", stem="Creator_Character")
    (root / "Creator_Character.atlas").write_text(
        "Creator_Character.png\n"
        "size:8,8\n"
        "RegionA\n"
        "  bounds:0,0,1,1\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="opaque-01")

    assert result.ok
    assert result.candidate.metadata["expression_mode"] == "opaque_custom"
    assert result.candidate.metadata["faces"] == []
    assert result.candidate.metadata["expression_parts"] == []


def test_semantic_part_kind_uses_component_name_not_words_inside_its_note(tmp_path):
    root = make_spine_bundle(tmp_path / "date", stem="Kei_Date_Outfit")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\n"
        "size:8,8\n"
        "大喊大叫嘴（需要与生气眼配合）\n"
        "  bounds:0,0,1,1\n"
        "八字下垂眉（悲痛、委屈）(更适合闭眼)\n"
        "  bounds:1,1,1,1\n",
        encoding="utf-8",
    )

    result = validate_spine(root, identifier="626652156")

    assert [part["kind"] for part in result.candidate.metadata["expression_parts"]] == [
        "mouth", "brows"
    ]
