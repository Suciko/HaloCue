import contextlib
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import asset_catalog
import assetdb
import webui
from history_assets import HistoryAssetBrowser
from story_workspace import StoryContext


def _insert_asset(
    con, *, kind, key, name, digest, scope, source="history_import", metadata=None,
    install_path=None,
):
    payload = {"catalog_source": source, **(metadata or {})}
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,install_path,status,metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            kind, str(key), name, rf"C:\private\source\{name}", digest,
            scope, str(install_path or rf"C:\private\installed\{name}"), "registered",
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    con.commit()


def library_fixture(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    first = tmp_path / "aa-data" / "projects" / "系列A-第一章"
    second = tmp_path / "aa-data" / "projects" / "系列A-第二章"
    first_preview = first / "bgs" / "rain.png"
    second_preview = second / "bgs" / "rain.png"
    first_preview.parent.mkdir(parents=True)
    second_preview.parent.mkdir(parents=True)
    first_preview.write_bytes(b"first-rain")
    second_preview.write_bytes(b"second-rain")
    _insert_asset(
        con, kind="background", key="rain_roof", name="雨夜天台", digest="digest-001",
        scope=str(first), metadata={"width": 1920, "height": 1080}, install_path=first_preview,
    )
    _insert_asset(
        con, kind="background", key="rain_roof", name="雨夜天台", digest="digest-001",
        scope=str(second), install_path=second_preview,
    )
    current = StoryContext(
        story_token="story-current", project="系列A-第二章", project_dir=second,
        save_dir=tmp_path / "aa-data" / "saves" / "系列A-第二章", source_path=None,
        latest_draft_token=None, bgm_default={},
    )
    return con, current, HistoryAssetBrowser(aa_data=tmp_path / "aa-data")


def mixed_source_library_fixture(tmp_path):
    con, current, browser = library_fixture(tmp_path)
    scope = str(current.project_dir)
    _insert_asset(con, kind="sound", key="official", name="官方音效", digest="official", scope=scope, source="observed")
    _insert_asset(con, kind="sound", key="verified", name="验证音效", digest="verified", scope=scope, source="verified")
    _insert_asset(con, kind="bgm", key="theme", name="主题曲", digest="theme", scope=scope)
    return con, current, browser


def test_library_groups_custom_copies_and_marks_current_story(tmp_path):
    """Dropping tokenized copy state or current-scope matching would break the workbench contract."""
    con, current, browser = library_fixture(tmp_path)

    payload = browser.list_library(con, current_context=current)
    rain = payload["backgrounds"][0]

    assert rain["name"] == "雨夜天台"
    assert rain["registered_in_current"] is True
    assert rain["copy_count"] == 2
    assert all(copy["copy_token"].startswith("copy-") for copy in rain["copies"])
    assert "scope" not in repr(payload)
    assert str(tmp_path) not in repr(payload)


def test_library_excludes_observed_verified_and_bgm_rows(tmp_path):
    """Treating observed/verified catalog records as reusable custom assets leaks built-ins into the library."""
    con, current, browser = mixed_source_library_fixture(tmp_path)

    payload = browser.list_library(con, current_context=current)

    assert payload["counts"] == {
        "characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0,
    }


@contextlib.contextmanager
def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _post(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_library_groups_custom_copies_by_content_without_exposing_paths(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    first = str(tmp_path / "projects" / "系列A-第一章")
    second = str(tmp_path / "projects" / "系列A-第二章")
    _insert_asset(
        con, kind="background", key="101", name="雨夜天台", digest="a" * 64,
        scope=first,
        metadata={
            "width": 1920, "height": 1080,
            "labels": {"place": "天台", "usage": str(tmp_path / "private-label")},
        },
    )
    _insert_asset(
        con, kind="background", key="101", name="雨夜天台", digest="a" * 64,
        scope=second,
    )
    _insert_asset(
        con, kind="sound", key="SE_Official", name="内置门铃", digest="b" * 64,
        scope=first, source="verified",
    )

    result = asset_catalog.list_library_assets(con)

    assert result["counts"] == {
        "characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0,
    }
    assert result["backgrounds"][0]["chapters"] == ["系列A-第一章", "系列A-第二章"]
    assert result["backgrounds"][0]["copy_count"] == 2
    assert result["backgrounds"][0]["details"] == {
        "resolution": "1920×1080", "labels": {"place": "天台"},
    }
    encoded = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "private" not in encoded.casefold()
    assert not {"source_path", "install_path", "scope"} & set(result["backgrounds"][0])


def test_library_profile_persists_series_classification_and_requires_series_name(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="character", key="kei-date", name="凯伊约会服",
        digest="c" * 64, scope=str(tmp_path / "projects" / "约会篇-第一章"),
        metadata={"expression_status": "known", "faces": [{"id": "00"}]},
    )

    with pytest.raises(ValueError, match="系列名称"):
        asset_catalog.update_library_profile(
            con, kind="character", aa_key="kei-date", sha256="c" * 64,
            asset_role="series_shared", series_name="",
        )

    saved = asset_catalog.update_library_profile(
        con, kind="character", aa_key="kei-date", sha256="c" * 64,
        asset_role="series_shared", series_name="  凯伊约会篇  ",
    )
    result = asset_catalog.list_library_assets(con)

    assert saved["series_name"] == "凯伊约会篇"
    assert result["characters"][0]["asset_role"] == "series_shared"
    assert result["characters"][0]["series_name"] == "凯伊约会篇"
    assert result["characters"][0]["details"]["face_count"] == 1


def test_library_profile_rejects_builtin_registered_rows(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="background", key="99", name="官方教室", digest="d" * 64,
        scope=str(tmp_path / "projects" / "第一章"), source="observed",
    )

    with pytest.raises(KeyError):
        asset_catalog.update_library_profile(
            con, kind="background", aa_key="99", sha256="d" * 64,
            asset_role="chapter_only", series_name="",
        )


def test_character_face_analysis_target_uses_only_installed_custom_copy(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    installed = tmp_path / "projects" / "第一章" / "characters" / "hero-id"
    installed.mkdir(parents=True)
    _insert_asset(
        con, kind="character", key="hero-id", name="主角骨骼",
        digest="1" * 64, scope=str(tmp_path / "projects" / "第一章"),
        metadata={"spine_signature": "sig-1", "outfit_key": "school"},
    )
    con.execute(
        "UPDATE asset_install SET install_path=? WHERE kind='character' AND aa_key='hero-id'",
        (str(installed),),
    )
    con.commit()

    target = asset_catalog.library_character_analysis_target(
        con, aa_key="hero-id", sha256="1" * 64
    )

    assert target == {
        "source": str(installed), "ident": "hero-id", "name": "主角骨骼",
        "spine_signature": "sig-1", "outfit_key": "school",
    }


def test_library_api_lists_and_updates_safe_profiles(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="sound", key="敲门", name="敲门", digest="e" * 64,
        scope=str(tmp_path / "projects" / "第二章"),
        metadata={"duration": 1.25, "codec": "pcm_s16le"},
    )
    con.close()

    with _server(tmp_path, monkeypatch) as base:
        with urlopen(base + "/api/assets/library") as response:
            listed = json.loads(response.read())
        status, saved = _post(base, "/api/assets/library/profile", {
            "kind": "sound", "aa_key": "敲门", "sha256": "e" * 64,
            "asset_role": "series_shared", "series_name": "校园篇",
        })

    assert listed["counts"]["sounds"] == 1
    assert str(tmp_path) not in json.dumps(listed, ensure_ascii=False)
    assert status == 200
    assert saved == {
        "ok": True, "kind": "sound", "aa_key": "敲门",
        "sha256": "e" * 64, "asset_role": "series_shared",
        "series_name": "校园篇",
    }


def test_library_api_rejects_shared_profile_without_series_name(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    asset_catalog.migrate(con)
    _insert_asset(
        con, kind="sound", key="敲门", name="敲门", digest="f" * 64,
        scope=str(tmp_path / "projects" / "第二章"),
    )
    con.close()

    with _server(tmp_path, monkeypatch) as base:
        status, body = _post(base, "/api/assets/library/profile", {
            "kind": "sound", "aa_key": "敲门", "sha256": "f" * 64,
            "asset_role": "series_shared", "series_name": "",
        })

    assert status == 400
    assert body["code"] == "invalid_library_profile"
    assert "系列名称" in body["e"]


def test_face_job_snapshot_never_exposes_server_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(webui, "FACE_JOB", {
        "running": False, "done": True, "ok": True, "phase": "complete",
        "message": "已完成", "current": 3, "total": 3, "log": ["渲染完成"],
        "contact_sheet": str(tmp_path / "cache" / "sheet.jpg"),
        "ident": "hero-id", "outfit_key": "school", "error": None,
        "result": {
            "rendered_count": 3, "render_cache": str(tmp_path / "cache"),
            "contact_sheet": str(tmp_path / "cache" / "sheet.jpg"),
            "vision_status": "labeled", "labeled_count": 3,
            "semantic_faces": [{
                "face_id": "03", "primary_emotion": "惊讶",
                "semantic_labels": ["惊讶", "意外"],
                "head_path": str(tmp_path / "private" / "03.png"),
            }],
        },
    })

    snapshot = webui.face_job_snapshot()

    assert snapshot["contact_sheet_available"] is True
    assert snapshot["result"]["semantic_faces"] == [{
        "face_id": "03", "primary_emotion": "惊讶",
        "semantic_labels": ["惊讶", "意外"],
    }]
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "render_cache" not in encoded
