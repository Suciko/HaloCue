import json
from pathlib import Path

from PIL import Image

import assetdb
import spine_face_analysis
from spine_face_renderer import RenderReport, RenderedFace


def _report(tmp_path: Path) -> RenderReport:
    cache = tmp_path / "cache" / "bundle"
    faces = []
    for face_id, color in (("00", "white"), ("05", "pink")):
        portrait = cache / "portraits" / f"{face_id}.png"
        head = cache / "heads" / f"{face_id}.png"
        portrait.parent.mkdir(parents=True, exist_ok=True)
        head.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 96), color).save(portrait)
        Image.new("RGBA", (48, 48), color).save(head)
        faces.append(RenderedFace(face_id, portrait, head))
    return RenderReport(
        signature="bundle-signature",
        cache_dir=cache,
        faces=tuple(faces),
        cached=False,
    )


def _labels(faces):
    return [
        {
            "face_id": face.face_id,
            "primary_emotion": "平静" if face.face_id == "00" else "轻微微笑",
            "secondary_emotions": [],
            "valence": "neutral",
            "arousal": "low",
            "eyes": "自然睁眼",
            "brows": "放松",
            "mouth": "自然",
            "blush": False,
            "tears": False,
            "confidence": 0.9,
            "description_cn": "测试标注",
            "head_path": str(face.head_path),
        }
        for face in faces
    ]


def test_resolve_spine_cli_prefers_explicit_then_environment_then_config(
    tmp_path, monkeypatch
):
    explicit = tmp_path / "explicit.exe"
    environment = tmp_path / "environment.exe"
    configured = tmp_path / "configured.exe"
    for path in (explicit, environment, configured):
        path.write_bytes(b"exe")
    config = tmp_path / "aa_config.json"
    config.write_text(
        json.dumps({"spine_cli": str(configured)}), encoding="utf-8"
    )
    monkeypatch.setenv("SPINE_CLI", str(environment))

    assert spine_face_analysis.resolve_spine_cli(explicit, config_path=config) == explicit
    assert spine_face_analysis.resolve_spine_cli(config_path=config) == environment
    monkeypatch.delenv("SPINE_CLI")
    assert spine_face_analysis.resolve_spine_cli(config_path=config) == configured


def test_analysis_renders_contact_sheet_without_requiring_model_key(
    tmp_path, monkeypatch
):
    report = _report(tmp_path)
    monkeypatch.setattr(
        spine_face_analysis,
        "render_face_variations",
        lambda *args, **kwargs: report,
    )
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    result = spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=None,
    )

    assert result["ok"] is True
    assert result["rendered_count"] == 2
    assert result["vision_status"] == "skipped_missing_key"
    assert Path(result["contact_sheet"]).is_file()


def test_analysis_maps_per_face_render_progress_to_job_updates(tmp_path, monkeypatch):
    report = _report(tmp_path)
    updates = []

    def render(*args, **kwargs):
        callback = kwargs["progress"]
        callback("00", 0, 2)
        callback("00", 1, 2)
        return report

    monkeypatch.setattr(spine_face_analysis, "render_face_variations", render)
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=None,
        progress=lambda phase, message, current, total: updates.append(
            (phase, message, current, total)
        ),
    )

    render_updates = [update for update in updates if "00" in update[1]]
    assert render_updates == [
        ("rendering", "正在渲染表情 00（0 / 2）", 0, 2),
        ("rendering", "正在渲染表情 00（1 / 2）", 1, 2),
    ]


def test_analysis_uses_two_render_workers_by_default(tmp_path, monkeypatch):
    report = _report(tmp_path)
    observed = {}

    def render(*args, **kwargs):
        observed["workers"] = kwargs["workers"]
        return report

    monkeypatch.setattr(spine_face_analysis, "render_face_variations", render)
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=None,
    )

    assert observed["workers"] == 2


def test_analysis_returns_condensed_semantics_for_web_review(tmp_path, monkeypatch):
    report = _report(tmp_path)
    monkeypatch.setattr(
        spine_face_analysis,
        "render_face_variations",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(
        spine_face_analysis,
        "_semantic_hints",
        lambda source: {
            "00": {
                "face_id": "00",
                "primary_emotion": "平静",
                "semantic_labels": ["平静"],
                "raw_parts": ["普通睁眼", "无表情理性嘴"],
            },
            "05": {
                "face_id": "05",
                "primary_emotion": "轻微微笑",
                "semantic_labels": ["轻微微笑", "温和"],
                "raw_parts": ["普通睁眼", "微笑嘴"],
            },
        },
    )
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    result = spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=None,
    )

    assert result["semantic_faces"] == [
        {
            "face_id": "00",
            "primary_emotion": "平静",
            "semantic_labels": ["平静"],
        },
        {
            "face_id": "05",
            "primary_emotion": "轻微微笑",
            "semantic_labels": ["轻微微笑", "温和"],
        },
    ]


def test_analysis_persists_visual_labels_and_reuses_existing_model_rows(
    tmp_path, monkeypatch
):
    report = _report(tmp_path)
    calls = {"render": 0, "label": 0}

    def render(*args, **kwargs):
        calls["render"] += 1
        return report

    def label(provider, faces, **kwargs):
        calls["label"] += 1
        return _labels(faces)

    monkeypatch.setattr(spine_face_analysis, "render_face_variations", render)
    monkeypatch.setattr(spine_face_analysis, "label_face_images", label)
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    class Provider:
        model = "gemini-3.6-flash"

    first = spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=Provider(),
    )
    second = spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=Provider(),
    )

    assert first["vision_status"] == "labeled"
    assert first["labeled_count"] == 2
    assert second["vision_status"] == "cached"
    assert calls == {"render": 2, "label": 1}
    count = con.execute(
        """
        SELECT COUNT(*) FROM face_visual_label
        WHERE ident='custom-1' AND spine_signature='skel-signature'
          AND outfit_key='date' AND model='gemini-3.6-flash'
        """
    ).fetchone()[0]
    assert count == 2


def test_analysis_maps_nine_grid_and_review_progress_to_job_updates(tmp_path, monkeypatch):
    report = _report(tmp_path)
    updates = []
    monkeypatch.setattr(
        spine_face_analysis,
        "render_face_variations",
        lambda *args, **kwargs: report,
    )

    def label(provider, faces, **kwargs):
        callback = kwargs["progress"]
        callback(1, 2, 1, 0)
        callback(2, 2, 1, 1)
        return _labels(faces)

    monkeypatch.setattr(spine_face_analysis, "label_face_images", label)
    source = tmp_path / "spine"
    source.mkdir()
    con = assetdb.connect(tmp_path / "assets.db")

    class Provider:
        model = "gemini-3.6-flash"

    spine_face_analysis.analyze_character_faces(
        con,
        source_dir=source,
        ident="custom-1",
        spine_signature="skel-signature",
        outfit_key="date",
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        provider=Provider(),
        progress=lambda phase, message, current, total: updates.append(
            (phase, message, current, total)
        ),
    )

    labeling = [update for update in updates if update[0] == "labeling"]
    assert labeling[-2:] == [
        ("labeling", "AI 已识别 1 / 2 个表情（完成 1 个九宫格批次）", 1, 2),
        ("labeling", "AI 已识别 2 / 2 个表情（完成 1 个九宫格批次，单项复核 1 个）", 2, 2),
    ]
