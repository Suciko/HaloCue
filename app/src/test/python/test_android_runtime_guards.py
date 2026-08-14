import pytest
import json
import io
from pathlib import Path

from PIL import Image

from android_runtime_guard import AndroidCapabilityUnavailable
import assetdb
import asset_catalog
import spine_face_analysis
import spine_face_labeler
import spine_face_renderer
import webui
from install_manager import InstallManager
from spine_face_analysis import (
    analyze_character_faces,
    label_browser_rendered_faces,
    resolve_spine_cli,
    store_browser_rendered_face,
)
from spine_face_renderer import render_face_variations
from test_android_spine_parser import _spine_bundle


def _spine_42_atlas_bundle(root):
    root.mkdir()
    base = root / "CH0335_spr"
    base.with_suffix(".skel").write_bytes(b"\x00spine\x004.2.33\x00")
    base.with_suffix(".atlas").write_text(
        "CH0335_spr.png\nsize:8,8\n\n"
        "00_default\nbounds:0,0,1,1\n\n"
        "01_normal\nbounds:0,0,1,1\n\n"
        "03_smile\nbounds:0,0,1,1\n",
        encoding="utf-8",
    )
    return base


def test_direct_aa_install_is_disabled():
    manager = InstallManager()
    with pytest.raises(AndroidCapabilityUnavailable, match="direct_aa_install"):
        manager.install_options(token="draft", build_id="build")
    with pytest.raises(AndroidCapabilityUnavailable, match="direct_aa_install"):
        manager.install_build(token="draft", build_id="build")


def test_spine_cli_and_rendering_are_disabled():
    assert resolve_spine_cli("Spine.com") is None
    with pytest.raises(AndroidCapabilityUnavailable, match="spine_rendering"):
        render_face_variations()


def test_android_face_analysis_reports_preview_rendering_as_pending(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        result = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="626652156",
            spine_signature="test-signature",
            outfit_key="default",
        )
        assert result["status"] == "awaiting_render"
        assert result["rendered_count"] == 0
        assert result["vision_status"] == "awaiting_android_render"
        assert result["semantic_face_count"] == 4
        rows = con.execute(
            "SELECT face_id, source FROM face_evidence WHERE ident=? AND spine_signature=? AND outfit_key=?",
            ("626652156", "test-signature", "default"),
        ).fetchall()
        assert {row["face_id"] for row in rows} == {"00", "01", "42"}
        assert {row["source"] for row in rows} == {"spine_semantic"}
    finally:
        con.close()


def test_android_face_analysis_falls_back_for_spine_42_atlas(tmp_path):
    source = _spine_42_atlas_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        result = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="ch0335",
            spine_signature="4.2-signature",
            outfit_key="CH0335_spr",
        )
        assert result["status"] == "awaiting_render"
        assert result["semantic_face_count"] == 3
        assert result["semantic_source"] == "spine_atlas_fallback"
        assert {item["face_id"] for item in result["semantic_faces"]} == {"00", "01", "03"}
    finally:
        con.close()


def test_browser_renders_are_saved_only_after_a_complete_face_set(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="626652156",
            spine_signature="test-signature",
            outfit_key="default",
        )
        face_ids = [item["face_id"] for item in initial["semantic_faces"]]
        for index, face_id in enumerate(face_ids):
            image = Image.new("RGBA", (512, 512), (30 + index * 20, 90, 140, 255))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            result = store_browser_rendered_face(
                con,
                source_dir=source.parent,
                ident="626652156",
                spine_signature="test-signature",
                outfit_key="default",
                cache_root=tmp_path / "cache",
                face_id=face_id,
                png_bytes=buffer.getvalue(),
            )
            if index < len(face_ids) - 1:
                assert result == {
                    "ok": True,
                    "complete": False,
                    "received": index + 1,
                    "total": len(face_ids),
                }
        assert result["complete"] is True
        assert result["rendered_count"] == len(face_ids)
        rows = con.execute(
            "SELECT face_id, head_path FROM face_visual_label "
            "WHERE ident=? AND spine_signature=? AND outfit_key=?",
            ("626652156", "test-signature", "default"),
        ).fetchall()
        assert {row["face_id"] for row in rows} == set(face_ids)
        assert all(Path(row["head_path"]).is_file() for row in rows)
        assert all(Image.open(row["head_path"]).size == (768, 768) for row in rows)
    finally:
        con.close()


def test_mixed_resolution_browser_renders_do_not_complete_the_new_batch(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="626652156",
            spine_signature="test-signature",
            outfit_key="default",
        )
        face_ids = [item["face_id"] for item in initial["semantic_faces"]]

        def upload(face_id, size):
            image = Image.new("RGBA", (size, size), (30, 90, 140, 255))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return store_browser_rendered_face(
                con,
                source_dir=source.parent,
                ident="626652156",
                spine_signature="test-signature",
                outfit_key="default",
                cache_root=tmp_path / "cache",
                face_id=face_id,
                png_bytes=buffer.getvalue(),
            )

        for face_id in face_ids:
            assert upload(face_id, 512)["ok"] is True

        result = upload(face_ids[0], 2048)

        assert result == {
            "ok": True,
            "complete": False,
            "received": 1,
            "total": len(face_ids),
        }
    finally:
        con.close()


def test_validated_browser_png_is_stored_without_lossy_or_expensive_reencoding(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="626652156",
            spine_signature="test-signature",
            outfit_key="default",
        )
        face_id = initial["semantic_faces"][0]["face_id"]
        buffer = io.BytesIO()
        Image.new("RGBA", (2048, 2048), (30, 90, 140, 255)).save(
            buffer, format="PNG", compress_level=1
        )
        uploaded = buffer.getvalue()

        result = store_browser_rendered_face(
            con,
            source_dir=source.parent,
            ident="626652156",
            spine_signature="test-signature",
            outfit_key="default",
            cache_root=tmp_path / "cache",
            face_id=face_id,
            png_bytes=uploaded,
        )

        assert result["complete"] is False
        portrait = (
            tmp_path / "cache" / "test-signature" / "portraits-browser-v3" / f"{face_id}.png"
        )
        assert portrait.read_bytes() == uploaded
    finally:
        con.close()


def test_android_head_crops_use_bounded_parallel_workers(tmp_path, monkeypatch):
    calls = []
    real_executor = __import__("concurrent.futures").futures.ThreadPoolExecutor

    def recording_executor(*, max_workers):
        calls.append(max_workers)
        return real_executor(max_workers=max_workers)

    monkeypatch.setattr(spine_face_renderer, "ThreadPoolExecutor", recording_executor)
    faces = []
    for index in range(4):
        portrait = tmp_path / f"portrait-{index}.png"
        head = tmp_path / f"head-{index}.png"
        Image.new("RGBA", (512, 512), (30 + index, 90, 140, 255)).save(portrait)
        faces.append(spine_face_renderer.RenderedFace(str(index), portrait, head))

    result = spine_face_renderer.crop_face_previews(faces, size=128)

    assert calls == [2]
    assert [face.face_id for face in result] == ["0", "1", "2", "3"]
    assert all(Image.open(face.head_path).size == (128, 128) for face in result)


def test_android_face_analysis_rejects_legacy_low_resolution_previews(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
        )
        legacy = tmp_path / "legacy-heads"
        legacy.mkdir()
        labels = []
        for item in initial["semantic_faces"]:
            head = legacy / f"{item['face_id']}.png"
            Image.new("RGBA", (256, 256), (30, 90, 140, 255)).save(head)
            labels.append({
                **item,
                "confidence": 1.0,
                "head_path": str(head),
            })
        spine_face_labeler.persist_visual_face_labels(
            con,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
            model="legacy-render",
            labels=labels,
        )

        result = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
        )

        assert result["status"] == "awaiting_render"
        assert result["rendered_count"] == 0
        assert result["vision_status"] == "awaiting_android_render"
    finally:
        con.close()


def test_android_face_analysis_rejects_high_resolution_previews_from_old_renderer_cache(tmp_path):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
        )
        legacy = tmp_path / "cache" / "test-signature" / "heads-browser-v2"
        legacy.mkdir(parents=True)
        labels = []
        for item in initial["semantic_faces"]:
            head = legacy / f"{item['face_id']}.png"
            Image.new("RGBA", (768, 768), (30, 90, 140, 255)).save(head)
            labels.append({**item, "confidence": 1.0, "head_path": str(head)})
        spine_face_labeler.persist_visual_face_labels(
            con,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
            model="legacy-render",
            labels=labels,
        )

        result = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
            cache_root=tmp_path / "cache",
        )

        assert result["status"] == "awaiting_render"
        assert result["rendered_count"] == 0
        assert result["vision_status"] == "awaiting_android_render"
    finally:
        con.close()


def test_completed_browser_renders_are_sent_to_the_vision_model(tmp_path, monkeypatch):
    source = _spine_bundle(tmp_path / "character")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        initial = analyze_character_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
        )
        for index, item in enumerate(initial["semantic_faces"]):
            image = Image.new("RGBA", (2048, 2048), (30 + index * 20, 90, 140, 255))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            store_browser_rendered_face(
                con,
                source_dir=source.parent,
                ident="凯伊约会服",
                spine_signature="test-signature",
                outfit_key="default",
                cache_root=tmp_path / "cache",
                face_id=item["face_id"],
                png_bytes=buffer.getvalue(),
            )

        seen = {}

        def label(_provider, faces, **kwargs):
            seen["sizes"] = [Image.open(face.head_path).size for face in faces]
            return [{
                "face_id": face.face_id,
                "primary_emotion": "AI 看图：微笑",
                "usage_hint_cn": "适合温和回应",
                "confidence": 0.93,
                "head_path": str(face.head_path),
            } for face in faces]

        monkeypatch.setattr(spine_face_analysis.spine_face_labeler, "label_face_images", label)

        class Provider:
            model = "vision-test-model"

        result = label_browser_rendered_faces(
            con,
            source_dir=source.parent,
            ident="凯伊约会服",
            spine_signature="test-signature",
            outfit_key="default",
            cache_root=tmp_path / "cache",
            provider=Provider(),
        )

        assert result["vision_status"] == "labeled"
        assert result["saved_count"] == len(initial["semantic_faces"])
        assert set(seen["sizes"]) == {(768, 768)}
        rows = con.execute(
            "SELECT face_id,primary_emotion FROM face_visual_label WHERE model=?",
            ("vision-test-model",),
        ).fetchall()
        assert len(rows) == len(initial["semantic_faces"])
        assert {row["primary_emotion"] for row in rows} == {"AI 看图：微笑"}
    finally:
        con.close()


def test_face_labels_publish_the_imported_character_avatar(tmp_path):
    installed = tmp_path / "installed-character"
    installed.mkdir()
    avatar = installed / "Kei_Date_Outfit-avatar.png"
    avatar.write_bytes(b"valid-avatar-preview")
    con = assetdb.connect(str(tmp_path / "assets.db"))
    try:
        asset_catalog.migrate(con)
        con.execute(
            """
            INSERT INTO asset_install
              (kind,aa_key,display_name,source_path,sha256,scope,install_path,
               status,error,metadata_json,registered_at)
            VALUES ('character',?,?,?,?,?,?,?,NULL,?,CURRENT_TIMESTAMP)
            """,
            (
                "626652156", "凯伊约会服", str(installed), "kei-digest",
                "story:test", str(installed), asset_catalog.STORY_ASSET_STATUS,
                json.dumps({
                    "catalog_source": "custom",
                    "spine_signature": "kei-signature",
                    "outfit_key": "Kei_Date_Outfit",
                    "files": {"avatar": str(avatar)},
                }, ensure_ascii=False),
            ),
        )
        con.commit()

        target = asset_catalog.library_character_analysis_target(
            con, aa_key="626652156", sha256="kei-digest"
        )
        payload = webui.face_labels_payload(
            con, aa_key="626652156", sha256="kei-digest"
        )

        assert target["avatar_path"] == str(avatar)
        assert target["sha256"] == "kei-digest"
        assert "aa_key=626652156" in payload["avatar_url"]
        assert "sha256=kei-digest" in payload["avatar_url"]
        assert "outfit_key" not in payload["avatar_url"]
    finally:
        con.close()
