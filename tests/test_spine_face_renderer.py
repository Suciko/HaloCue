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


def test_render_worker_count_is_capped_at_four():
    assert spine_face_renderer.bounded_render_workers(1) == 1
    assert spine_face_renderer.bounded_render_workers(4) == 4
    assert spine_face_renderer.bounded_render_workers(12) == 4


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


def test_atlas_metadata_parser_keeps_region_transform_fields(tmp_path):
    atlas = tmp_path / "actor.atlas"
    atlas.write_text(
        "actor.png\n"
        "size: 512,512\n"
        "format: RGBA8888\n"
        "filter: Linear,Linear\n"
        "repeat: none\n"
        "eyes\n"
        "  rotate: true\n"
        "  xy: 10, 20\n"
        "  size: 60, 20\n"
        "  orig: 80, 40\n"
        "  offset: 10, 5\n"
        "  index: -1\n",
        encoding="utf-8",
    )

    parse = getattr(
        spine_face_renderer,
        "parse_atlas_metadata",
        lambda path: {},
    )

    assert parse(atlas) == {
        "eyes.png": {
            "rotate": True,
            "size": [60, 20],
            "orig": [80, 40],
            "offset": [10, 5],
        }
    }


def test_atlas_metadata_parser_appends_png_after_complete_dotted_region_name(
    tmp_path,
):
    atlas = tmp_path / "actor.atlas"
    atlas.write_text(
        "actor.png\n"
        "size: 512,512\n"
        "format: RGBA8888\n"
        "filter: Linear,Linear\n"
        "repeat: none\n"
        "faces/eyes.variant.1.5\n"
        "  rotate: false\n"
        "  xy: 10, 20\n"
        "  size: 60, 20\n"
        "  orig: 80, 40\n"
        "  offset: 10, 5\n"
        "  index: -1\n",
        encoding="utf-8",
    )

    metadata = spine_face_renderer.parse_atlas_metadata(atlas)

    assert list(metadata) == ["faces/eyes.variant.1.5.png"]


def test_attachment_restore_resolves_nested_dotted_logical_name_and_png_path(
    tmp_path,
):
    images = tmp_path / "images"
    nested = images / "faces"
    nested.mkdir(parents=True)
    Image.new("RGBA", (24, 12), "red").save(
        nested / "eyes.variant.1.5.png"
    )
    Image.new("RGBA", (20, 10), "blue").save(nested / "already.png")
    skeleton = {
        "skins": [{
            "attachments": {
                "Eyes": {
                    "dotted": {
                        "path": "faces/eyes.variant.1.5",
                        "width": 48,
                        "height": 24,
                    },
                    "existing-suffix": {
                        "path": "faces/already.png",
                        "width": 40,
                        "height": 20,
                    },
                }
            }
        }]
    }

    diagnostics = spine_face_renderer.restore_attachment_images(skeleton, images)

    assert [item["path"] for item in diagnostics] == [
        "faces/eyes.variant.1.5.png",
        "faces/already.png",
    ]
    assert all(
        item["reason"] == "restored_region_without_atlas_metadata"
        for item in diagnostics
    )
    assert Image.open(nested / "eyes.variant.1.5.png").size == (48, 24)
    assert Image.open(nested / "already.png").size == (40, 20)


def test_attachment_restore_rebuilds_trimmed_region_and_preserves_mesh_geometry(
    tmp_path,
):
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGBA", (60, 20), (255, 0, 0, 255)).save(images / "eyes.png")
    Image.new("RGBA", (32, 32), (0, 0, 255, 255)).save(images / "face-mesh.png")
    skeleton = {
        "skins": [{
            "name": "default",
            "attachments": {
                "Eyes": {
                    "angry": {
                        "path": "eyes",
                        "width": 100,
                        "height": 50,
                    }
                },
                "Face": {
                    "mesh": {
                        "type": "mesh",
                        "path": "face-mesh",
                        "uvs": [0, 0, 1, 0, 1, 1, 0, 1],
                        "vertices": [0, 0, 32, 0, 32, 32, 0, 32],
                        "triangles": [0, 1, 2, 2, 3, 0],
                    }
                },
            },
        }]
    }
    atlas = {
        "eyes.png": {
            "rotate": False,
            "size": [60, 20],
            "orig": [80, 40],
            "offset": [10, 5],
        },
        "face-mesh.png": {
            "rotate": False,
            "size": [32, 32],
            "orig": [32, 32],
            "offset": [0, 0],
        },
    }

    restore = getattr(
        spine_face_renderer,
        "restore_attachment_images",
        lambda skeleton, images, atlas_metadata=None: [],
    )
    diagnostics = restore(skeleton, images, atlas)

    region = next(item for item in diagnostics if item["attachment"] == "angry")
    mesh = next(item for item in diagnostics if item["attachment"] == "mesh")
    assert region == {
        "attachment": "angry",
        "slot": "Eyes",
        "path": "eyes.png",
        "type": "region",
        "status": "restored",
        "reason": "restored_trimmed_region_to_attachment_geometry",
        "from": [60, 20],
        "to": [100, 50],
    }
    restored = Image.open(images / "eyes.png").convert("RGBA")
    assert restored.size == (100, 50)
    assert restored.getpixel((0, 0))[3] == 0
    assert restored.getpixel((50, 25)) == (255, 0, 0, 255)
    assert mesh["type"] == "mesh"
    assert mesh["status"] == "preserved_geometry"
    assert Image.open(images / "face-mesh.png").size == (32, 32)


def test_attachment_restore_marks_unsafe_mesh_and_incomplete_region_for_calibration(
    tmp_path,
):
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGBA", (24, 12), "blue").save(images / "mesh.png")
    Image.new("RGBA", (12, 8), "red").save(images / "region.png")
    skeleton = {
        "skins": [{
            "name": "default",
            "attachments": {
                "Face": {
                    "unsafe-mesh": {
                        "type": "mesh",
                        "path": "mesh",
                        "uvs": [0, 0, 1, 1],
                    }
                },
                "Eyes": {
                    "incomplete-region": {
                        "path": "region",
                        "width": 100,
                    }
                },
            },
        }]
    }

    restore = getattr(
        spine_face_renderer,
        "restore_attachment_images",
        lambda skeleton, images, atlas_metadata=None: [],
    )
    diagnostics = restore(skeleton, images)

    assert diagnostics == [
        {
            "attachment": "unsafe-mesh",
            "slot": "Face",
            "path": "mesh.png",
            "type": "mesh",
            "status": "needs_manual_calibration",
            "reason": "missing_mesh_geometry:triangles,vertices",
        },
        {
            "attachment": "incomplete-region",
            "slot": "Eyes",
            "path": "region.png",
            "type": "region",
            "status": "needs_manual_calibration",
            "reason": "missing_region_geometry:height",
        },
    ]
    assert Image.open(images / "mesh.png").size == (24, 12)
    assert Image.open(images / "region.png").size == (12, 8)


def test_attachment_restore_marks_invalid_atlas_transform_for_calibration(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGBA", (60, 20), "red").save(images / "eyes.png")
    skeleton = {
        "skins": [{
            "attachments": {
                "Eyes": {
                    "angry": {
                        "path": "eyes",
                        "width": 100,
                        "height": 50,
                    }
                }
            }
        }]
    }
    malformed_atlas = {
        "eyes.png": {
            "rotate": False,
            "size": [60, 20],
            "orig": [80, 40],
            # Missing offset means the trim cannot be reconstructed safely.
        }
    }

    diagnostics = spine_face_renderer.restore_attachment_images(
        skeleton,
        images,
        malformed_atlas,
    )

    assert diagnostics[0]["status"] == "needs_manual_calibration"
    assert diagnostics[0]["reason"] == "restored_region_without_valid_atlas_metadata"
    assert Image.open(images / "eyes.png").size == (100, 50)


def test_attachment_restore_marks_missing_mesh_texture_for_calibration(tmp_path):
    skeleton = {
        "skins": [{
            "attachments": {
                "Face": {
                    "mesh": {
                        "type": "mesh",
                        "path": "missing-mesh",
                        "uvs": [0, 0, 1, 0, 1, 1],
                        "vertices": [0, 0, 1, 0, 1, 1],
                        "triangles": [0, 1, 2],
                    }
                }
            }
        }]
    }

    diagnostics = spine_face_renderer.restore_attachment_images(
        skeleton,
        tmp_path,
    )

    assert diagnostics[0]["status"] == "needs_manual_calibration"
    assert diagnostics[0]["reason"] == "missing_attachment_image"


def test_attachment_calibration_maps_37_through_40_like_other_animations():
    skeleton = {
        "animations": {
            face_id: {
                "slots": {
                    "Eyes": {
                        "attachment": [{"name": "angry"}],
                    }
                }
            }
            for face_id in ("37", "38", "39", "40", "41")
        }
    }
    attachment_diagnostics = [{
        "attachment": "angry",
        "slot": "Eyes",
        "path": "eyes.png",
        "type": "region",
        "status": "needs_manual_calibration",
        "reason": "missing_region_geometry:height",
    }]

    map_calibration = getattr(
        spine_face_renderer,
        "map_attachment_calibration_to_faces",
        lambda skeleton, face_ids, diagnostics: [],
    )
    calibration = map_calibration(
        skeleton,
        ["37", "38", "39", "40", "41"],
        attachment_diagnostics,
    )

    assert [item["face_id"] for item in calibration] == [
        "37",
        "38",
        "39",
        "40",
        "41",
    ]
    assert all(item["attachment"] == "angry" for item in calibration)
    assert len({item["reason"] for item in calibration}) == 1


def test_render_validation_and_report_calibration_are_backward_compatible(tmp_path):
    portrait = tmp_path / "portrait.png"
    head = tmp_path / "head.png"
    Image.new("RGBA", (100, 200), (220, 60, 100, 255)).save(portrait)
    Image.new("RGBA", (80, 80), (220, 60, 100, 255)).save(head)
    face = spine_face_renderer.RenderedFace("37", portrait, head)

    validate = getattr(
        spine_face_renderer,
        "validate_rendered_face",
        lambda face: {},
    )
    diagnostic = validate(face)
    report = spine_face_renderer.RenderReport(
        signature="signature",
        cache_dir=tmp_path,
        faces=(face,),
        cached=False,
    )

    assert diagnostic["face_id"] == "37"
    assert diagnostic["status"] == "validated"
    assert diagnostic["alpha_bounds"] == [0, 0, 100, 200]
    assert diagnostic["visible_coverage"] == 1.0
    assert diagnostic["head_bounds"] == [0, 0, 80, 80]
    assert diagnostic["stability"] == {
        "portrait_aspect_ratio": 0.5,
        "head_aspect_ratio": 1.0,
        "head_to_portrait_width": 0.8,
    }
    assert report.calibration == ()


def test_cached_warmed_project_restores_images_overwritten_by_repeat_unpack(tmp_path):
    warmed = tmp_path / "render-warmup-v6.spine"
    patched = tmp_path / "render-warmup-v6.json"
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
        workers=1,
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


def test_parallel_render_retries_only_failed_faces_and_preserves_evidence(tmp_path):
    """A transient parallel export failure must not discard completed faces."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "actor.skel").write_bytes(b"fake skeleton")
    (source / "actor.atlas").write_text("actor.png\n", encoding="utf-8")
    Image.new("RGBA", (32, 32), (200, 40, 80, 255)).save(source / "actor.png")
    export_attempts = {}

    def runner(command):
        if "--unpack" in command:
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (16, 16), (200, 40, 80, 255)).save(output / "base.png")
        elif "--import" in command:
            Path(command[command.index("--output") + 1]).write_bytes(b"project")
        elif "--export" in command:
            settings = json.loads(
                Path(command[command.index("--export") + 1]).read_text(encoding="utf-8")
            )
            if settings["class"].endswith("$ExportJson"):
                output = Path(command[command.index("--output") + 1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "actor.json").write_text(
                    json.dumps({
                        "skeleton": {}, "bones": [{"name": "root"}],
                        "animations": {"Idle_01": {}, "01": {}, "02": {}},
                    }),
                    encoding="utf-8",
                )
            else:
                animation = settings["animation"]
                export_attempts[animation] = export_attempts.get(animation, 0) + 1
                if animation == "01" and export_attempts[animation] <= 2:
                    raise RuntimeError("Spine resource exhausted")
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
        face_ids=["02", "01", "00"],
        runner=runner,
    )
    second = render_face_variations(
        source,
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        face_ids=["00", "01", "02"],
        runner=lambda _command: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert [face.face_id for face in first.faces] == ["00", "01", "02"]
    assert first.actual_workers == 4
    assert first.retried_faces == ("01",)
    assert first.fallback_workers == 1
    assert export_attempts["01"] == 3
    assert second.cached is True
    assert second.actual_workers == 4
    assert second.retried_faces == ("01",)
    assert second.fallback_workers == 1
