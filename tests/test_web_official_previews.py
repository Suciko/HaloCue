from pathlib import Path

from PIL import Image

import assetdb
import webui
from official_preview_index import OfficialPreviewIndex


def _make_image(path: Path, color: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 16), color).save(path)


def _configure_preview_store(tmp_path, monkeypatch):
    root = tmp_path / "previews"
    store = OfficialPreviewIndex(root)
    output = root / "official.webp"
    _make_image(output, "blue")
    avatar = root / "official-avatar.png"
    _make_image(avatar, "green")
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "manifest.json").write_text(
        '{"schema_version":1,"status":"ready",'
        '"fingerprint":"test","counts":{"backgrounds":1,"avatars":0,"failed":0},'
        '"records":[{"kind":"background","key":"bg_classroom",'
        '"normalized_key":"bg_classroom","path":"official.webp",'
        '"source_fingerprint":"test"},{"kind":"avatar",'
        '"key":"Student_Portrait_Hifumi",'
        '"normalized_key":"student_portrait_hifumi",'
        '"path":"official-avatar.png","source_fingerprint":"test"}],'
        '"failures":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "OFFICIAL_PREVIEW_INDEX", store)
    return store


def test_custom_background_preview_precedes_official(tmp_path, monkeypatch):
    _configure_preview_store(tmp_path, monkeypatch)
    custom = tmp_path / "overrides" / "bgs" / "BG_Classroom.png"
    _make_image(custom, "red")
    monkeypatch.setitem(webui.CFG, "overrides", str(custom.parents[1]))
    webui._BGF.clear()

    assert webui.background_preview_path("BG_Classroom") == custom


def test_official_background_preview_is_used_when_custom_is_missing(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))
    webui._BGF.clear()

    assert webui.background_preview_path("BG_Classroom") == (
        store.root / "official.webp"
    )


def test_preflight_candidate_reports_official_preview(tmp_path, monkeypatch):
    _configure_preview_store(tmp_path, monkeypatch)
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))

    assert webui._background_preview_available("BG_Classroom") is True


def test_character_avatar_prefers_custom_then_uses_official(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)
    overrides = tmp_path / "overrides"
    monkeypatch.setitem(webui.CFG, "overrides", str(overrides))
    avatar_key = "UIs/01_Common/01_Character/Student_Portrait_Hifumi"
    spine = "characters/Hifumi"

    assert webui.character_avatar_path(avatar_key, spine) == (
        store.root / "official-avatar.png"
    )

    custom = overrides / "characters" / "Hifumi-avatar.png"
    _make_image(custom, "red")
    assert webui.character_avatar_path(avatar_key, spine) == custom


def test_character_list_exposes_avatar_route_only_when_preview_exists(
    tmp_path,
    monkeypatch,
):
    _configure_preview_store(tmp_path, monkeypatch)
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    assetdb.import_index(con, {"characters": [{
        "identifier": "hifumi",
        "name": "日步美",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Hifumi",
        "spine": "characters/Hifumi",
        "faces": [],
    }, {
        "identifier": "missing",
        "name": "无头像",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Missing",
        "spine": "characters/Missing",
        "faces": [],
    }]})
    con.close()

    rows = {row["ident"]: row for row in webui.list_characters()}

    assert rows["hifumi"]["avatar"].endswith(
        "/Student_Portrait_Hifumi"
    )
    assert rows["missing"]["avatar"] == ""
