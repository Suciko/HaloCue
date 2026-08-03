import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import spine_face_renderer
from spine_face_renderer import (
    _prepare_warmed_project,
    _run_spine,
    bundle_signature,
    crop_head_preview,
    discover_renderable_face_ids,
    extend_face_animation_duration,
    is_textured_render,
    render_face_variations,
    sanitize_spine_output,
    select_final_frame,
)


def test_png_export_settings_render_only_the_warmed_final_frame(tmp_path):
    settings = spine_face_renderer._export_settings(
        project=tmp_path / "project.spine",
        output=tmp_path / "face",
        animation="11",
        compression=9,
    )

    assert settings["fps"] == 1
    assert settings["rangeStart"] == 8
    assert settings["rangeEnd"] == 8
    assert settings["lastFrame"] is False


def test_discover_renderable_faces_keeps_every_numbered_expression_including_99():
    combinations = {
        "00": {"special": False},
        "01": {"special": False},
        "09": {"special": False},
        "42": {"special": False},
        "99": {"special": True},
        "Idle_01": {"special": False},
    }

    assert discover_renderable_face_ids(combinations) == ["00", "01", "09", "42", "99"]


def test_zero_duration_face_animation_gets_nonvisual_warmup_timeline():
    skeleton = {
        "bones": [{"name": "root"}],
        "animations": {
            "08": {"slots": {"Eyes": {"attachment": [{"name": "side-eye"}]}}},
            "09": {"bones": {"root": {"translate": [{"time": 8}]}}},
        },
    }

    extend_face_animation_duration(skeleton, ["08", "09"], duration=8)

    assert skeleton["animations"]["08"]["bones"]["root"]["translate"] == [{"time": 8}]
    assert skeleton["animations"]["09"]["bones"]["root"]["translate"] == [{"time": 8}]


def test_bundle_signature_changes_when_any_spine_source_file_changes(tmp_path):
    for name, content in {
        "actor.skel": b"skeleton",
        "actor.atlas": b"atlas",
        "actor.png": b"texture",
    }.items():
        (tmp_path / name).write_bytes(content)

    first = bundle_signature(tmp_path)
    (tmp_path / "actor.atlas").write_bytes(b"changed atlas")
    second = bundle_signature(tmp_path)

    assert first != second
    expected = hashlib.sha256()
    for name in ("actor.atlas", "actor.png", "actor.skel"):
        expected.update(name.encode("utf-8"))
        expected.update((tmp_path / name).read_bytes())
    assert second == expected.hexdigest()


def test_spine_output_sanitizer_removes_licensee_and_registry_noise():
    raw = "\n".join(
        [
            "Spine 3.8.75 Professional",
            "Licensed to: private-name, private@example.com",
            "WARNING: Could not create windows registry node Software\\JavaSoft\\Prefs",
            "WARNING: Trying to recreate Windows registry node",
            "PNG export: Actor",
            "Complete.",
        ]
    )

    clean = sanitize_spine_output(raw)

    assert "Licensed to:" not in clean
    assert "private@example.com" not in clean
    assert "registry node" not in clean
    assert clean.splitlines() == [
        "Spine 3.8.75 Professional",
        "PNG export: Actor",
        "Complete.",
    ]


def test_spine_runner_times_out_instead_of_hanging_forever(monkeypatch):
    def fake_run(*args, **kwargs):
        assert kwargs["timeout"] == 17
        raise subprocess.TimeoutExpired(
            args[0],
            timeout=17,
            output="Spine 3.8.75 Professional\nLicensed to: private",
            stderr="still rendering",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 17 seconds") as error:
        _run_spine(["Spine.com", "--export"], timeout_seconds=17)

    assert "Licensed to:" not in str(error.value)


def test_final_frame_selection_uses_highest_numeric_suffix(tmp_path):
    for name in ("face_0.png", "face_8.png", "face_12.png", "notes.png"):
        (tmp_path / name).write_bytes(b"x")

    assert select_final_frame(tmp_path).name == "face_12.png"


def test_white_silhouette_is_rejected_but_colored_texture_is_accepted(tmp_path):
    white = tmp_path / "white.png"
    washed = tmp_path / "washed.png"
    colored = tmp_path / "colored.png"
    truncated = tmp_path / "truncated.png"
    Image.new("RGBA", (128, 128), (255, 255, 255, 255)).save(white)
    Image.new("RGBA", (128, 128), (230, 190, 180, 155)).save(washed)
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 119, 119), fill=(245, 240, 236, 255))
    draw.ellipse((35, 30, 93, 88), fill=(210, 45, 85, 255))
    image.save(colored)
    truncated.write_bytes(b"\x89PNG\r\n\x1a\npartial")

    assert not is_textured_render(white)
    assert not is_textured_render(washed)
    assert not is_textured_render(truncated)
    assert is_textured_render(colored)


def test_head_preview_uses_upper_part_of_visible_portrait(tmp_path):
    source = tmp_path / "portrait.png"
    output = tmp_path / "head.png"
    image = Image.new("RGBA", (300, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((75, 30, 225, 210), fill=(230, 190, 180, 255))
    draw.rectangle((50, 190, 250, 580), fill=(40, 80, 160, 255))
    image.save(source)

    crop_head_preview(source, output, size=256)
    head = Image.open(output)

    assert head.size == (256, 256)
    # The upper face remains, while the bottom of the full portrait is excluded.
    assert head.getpixel((128, 80))[3] > 0
    assert head.getpixel((128, 245))[:3] != (40, 80, 160)


def test_default_head_preview_is_large_enough_for_visual_labeling(tmp_path):
    source = tmp_path / "portrait.png"
    output = tmp_path / "head.png"
    Image.new("RGBA", (300, 600), (220, 60, 100, 255)).save(source)

    crop_head_preview(source, output)

    assert Image.open(output).size == (768, 768)


def test_unpacked_region_images_are_restored_to_skeleton_attachment_size(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGBA", (65, 32), "red").save(images / "eyes.png")
    Image.new("RGBA", (65, 65), "blue").save(images / "base.png")
    skeleton = {
        "skins": [{
            "name": "default",
            "attachments": {
                "Eyes": {
                    "wide": {
                        "path": "eyes",
                        "width": 100,
                        "height": 50,
                    }
                },
                "base": {
                    "base": {
                        "type": "mesh",
                        "path": "base",
                        "width": 100,
                        "height": 100,
                    }
                },
            },
        }]
    }

    restore = getattr(
        spine_face_renderer,
        "restore_region_attachment_images",
        lambda skeleton, images: [],
    )
    restored = restore(skeleton, images)

    assert restored == [{"path": "eyes.png", "from": [65, 32], "to": [100, 50]}]
    assert Image.open(images / "eyes.png").size == (100, 50)
    assert Image.open(images / "base.png").size == (65, 65)
    assert restore(skeleton, images) == []


def test_cached_warmed_project_restores_images_overwritten_by_repeat_unpack(tmp_path):
    warmed = tmp_path / "render-warmup-v4.spine"
    patched = tmp_path / "render-warmup-v4.json"
    image = tmp_path / "eyes.png"
    warmed.write_bytes(b"project")
    Image.new("RGBA", (65, 32), "red").save(image)
    patched.write_text(
        json.dumps(
            {
                "skins": [{
                    "name": "default",
                    "attachments": {
                        "Eyes": {
                            "wide": {
                                "path": "eyes",
                                "width": 100,
                                "height": 50,
                            }
                        }
                    },
                }]
            }
        ),
        encoding="utf-8",
    )

    def should_not_run(_command):
        raise AssertionError("cached warmed project should not invoke Spine")

    result = _prepare_warmed_project(
        execute=should_not_run,
        cli=tmp_path / "Spine.com",
        project=tmp_path / "source.spine",
        work=tmp_path,
        face_ids=["01"],
    )

    assert result == warmed
    assert Image.open(image).size == (100, 50)


def test_renderer_uses_content_cache_and_never_changes_source_bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "actor.skel").write_bytes(b"fake skeleton")
    (source / "actor.atlas").write_text("actor.png\n", encoding="utf-8")
    Image.new("RGBA", (32, 32), (200, 40, 80, 255)).save(source / "actor.png")
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
    }
    calls = []
    progress_events = []

    def fake_runner(command):
        calls.append(command)
        if "--unpack" in command:
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (16, 16), (200, 40, 80, 255)).save(
                output / "base.png"
            )
        elif "--import" in command:
            project = Path(command[command.index("--output") + 1])
            project.write_bytes(b"fake project")
        elif "--export" in command:
            settings = json.loads(
                Path(command[command.index("--export") + 1]).read_text(encoding="utf-8")
            )
            if settings["class"].endswith("$ExportJson"):
                output = Path(command[command.index("--output") + 1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "actor.json").write_text(
                    json.dumps(
                        {
                            "skeleton": {},
                            "bones": [{"name": "root"}],
                            "animations": {"01": {}, "Idle_01": {}},
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                output = Path(settings["output"])
                output.parent.mkdir(parents=True, exist_ok=True)
                image = Image.new("RGBA", (300, 600), (0, 0, 0, 0))
                draw = ImageDraw.Draw(image)
                draw.ellipse((75, 30, 225, 210), fill=(220, 60, 100, 255))
                draw.rectangle((50, 190, 250, 580), fill=(40, 80, 160, 255))
                image.save(output.with_name(output.name + "_8.png"))
        return "Complete."

    first = render_face_variations(
        source,
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        face_ids=["00", "01"],
        runner=fake_runner,
        progress=lambda face_id, current, total: progress_events.append(
            (face_id, current, total)
        ),
    )
    call_count = len(calls)
    second = render_face_variations(
        source,
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        face_ids=["00", "01"],
        runner=fake_runner,
    )

    assert first.cached is False
    assert second.cached is True
    assert len(calls) == call_count
    assert [item.face_id for item in first.faces] == ["00", "01"]
    assert progress_events == [
        ("00", 0, 2),
        ("00", 1, 2),
        ("01", 1, 2),
        ("01", 2, 2),
    ]
    assert all(item.portrait_path.exists() and item.head_path.exists() for item in first.faces)
    assert before == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.iterdir()
    }

    # A poisoned cache must be regenerated instead of silently becoming labels.
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(
        first.faces[0].portrait_path
    )
    repaired = render_face_variations(
        source,
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        face_ids=["00", "01"],
        runner=fake_runner,
    )
    assert repaired.cached is False
    assert len(calls) > call_count
    assert is_textured_render(repaired.faces[0].portrait_path)
