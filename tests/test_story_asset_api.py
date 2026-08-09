# -*- coding: utf-8 -*-
"""Story-scoped asset API contract."""

import contextlib
import json
import threading
import time
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from PIL import Image

import assetdb
import aa_project_assets
import webui
from asset_catalog import upsert_candidate
from asset_models import AssetCandidate
from asset_validation import validate_background
from aa_registry import write_manifest_atomic
from history_assets import HistoryAssetBrowser
from story_workspace import StoryWorkspaceRegistry
from webui import H


@contextlib.contextmanager
def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "aa-data"))
    monkeypatch.setattr(
        webui,
        "STORY_WORKSPACE",
        StoryWorkspaceRegistry(tmp_path / "out" / "story-index.json", tmp_path / "aa-data"),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _request(base, path, payload=None, method="GET"):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        base + path, data=raw, method=method,
        headers={"Content-Type": "application/json"} if raw else {},
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except Exception as exc:
        with exc as response:
            return response.status, json.loads(response.read())


def _request_bytes(base, path):
    request = Request(base + path)
    try:
        with urlopen(request) as response:
            return response.status, response.headers["Content-Type"], response.read()
    except Exception as exc:
        with exc as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()


def _open_story(base, tmp_path):
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    token = webui.register_file_token(str(script))
    status, opened = _request(base, "/api/stories/open", {"file_token": token}, "POST")
    assert status == 200
    return opened


def _open_named_story(base, tmp_path, name):
    script = tmp_path / f"{name}.txt"
    script.write_text("scene", encoding="utf-8")
    token = webui.register_file_token(str(script))
    status, opened = _request(base, "/api/stories/open", {
        "file_token": token, "project": name,
    }, "POST")
    assert status == 200
    return opened


def _background(path: Path, color="navy"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), color).save(path)


def _character(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "hero.skel").write_bytes(b"spine 4.2.33")
    (root / "hero.atlas").write_text(
        "hero.png\nsize: 32,32\nformat: RGBA8888\n\n00_default\n  rotate: false\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (32, 32), "white").save(root / "hero.png")
    Image.new("RGBA", (16, 16), "white").save(root / "hero-avatar.png")


def _sound(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\0\0" * 2205)


def test_library_copy_refuses_stale_target_story(tmp_path, monkeypatch):
    """A copy request from a workbench bound to another story must not write to an old scope."""
    aa_data = tmp_path / "aa-data"
    source_project = aa_data / "projects" / "Source"
    source = source_project / "bgs" / "rain_roof.png"
    _background(source)
    write_manifest_atomic(source_project, {"BgOverrides": [r"bgs\rain_roof.png"]})
    con = assetdb.connect(tmp_path / "assets.db")
    digest = validate_background(source).candidate.sha256
    upsert_candidate(
        con, AssetCandidate(
            "background", source, "rain_roof", "rain_roof", digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(source_project), status="registered", install_path=str(source),
    )
    con.close()
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    with _server(tmp_path, monkeypatch) as base:
        old_story = _open_named_story(base, tmp_path, "Old Story")
        _, library = _request(base, "/api/assets/library?story_token=" + old_story["story_token"])
        source_copy_token = library["backgrounds"][0]["copies"][0]["copy_token"]
        new_story = _open_named_story(base, tmp_path, "New Story")
        _request(base, "/api/assets/library?story_token=" + new_story["story_token"])
        status, body = _request(base, "/api/assets/library/copy-to-story", {
            "story_token": old_story["story_token"],
            "source_copy_token": source_copy_token,
            "kind": "background",
            "aa_key": "rain_roof",
            "sha256": digest,
        }, "POST")

    assert status == 409
    assert body["code"] == "story_context_changed"
    assert body["message"]
    assert body["action"]


def test_library_copy_returns_a_safe_story_asset_card(tmp_path, monkeypatch):
    """Returning copy paths would make a successful workbench copy leak server locations."""
    aa_data = tmp_path / "aa-data"
    source_project = aa_data / "projects" / "Source"
    source = source_project / "bgs" / "rain_roof.png"
    _background(source)
    write_manifest_atomic(source_project, {"BgOverrides": [r"bgs\rain_roof.png"]})
    con = assetdb.connect(tmp_path / "assets.db")
    digest = validate_background(source).candidate.sha256
    upsert_candidate(
        con, AssetCandidate(
            "background", source, "rain_roof", "rain_roof", digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(source_project), status="registered", install_path=str(source),
    )
    con.close()
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    with _server(tmp_path, monkeypatch) as base:
        story = _open_named_story(base, tmp_path, "Current")
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])
        source_copy_token = library["backgrounds"][0]["copies"][0]["copy_token"]
        status, body = _request(base, "/api/assets/library/copy-to-story", {
            "story_token": story["story_token"],
            "source_copy_token": source_copy_token,
            "kind": "background",
            "aa_key": "rain_roof",
            "sha256": digest,
        }, "POST")

    assert status == 200
    assert body["state"] == "registered"
    assert body["asset"]["name"] == "rain_roof"
    assert "install_path" not in repr(body)
    assert str(aa_data) not in repr(body)


@pytest.mark.parametrize("field, value", [
    ("kind", "sound"),
    ("aa_key", "other"),
    ("sha256", "not-the-issued-digest"),
])
def test_library_copy_rejects_request_fields_that_do_not_match_its_token(
    tmp_path, monkeypatch, field, value
):
    """Trusting client-supplied copy metadata lets one opaque token target another asset."""
    aa_data = tmp_path / "aa-data"
    source_project = aa_data / "projects" / "Source"
    source = source_project / "bgs" / "rain_roof.png"
    _background(source)
    write_manifest_atomic(source_project, {"BgOverrides": [r"bgs\rain_roof.png"]})
    con = assetdb.connect(tmp_path / "assets.db")
    digest = validate_background(source).candidate.sha256
    upsert_candidate(
        con, AssetCandidate(
            "background", source, "rain_roof", "rain_roof", digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(source_project), status="registered", install_path=str(source),
    )
    con.close()
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    with _server(tmp_path, monkeypatch) as base:
        story = _open_named_story(base, tmp_path, "Current")
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])
        payload = {
            "story_token": story["story_token"],
            "source_copy_token": library["backgrounds"][0]["copies"][0]["copy_token"],
            "kind": "background", "aa_key": "rain_roof", "sha256": digest,
        }
        payload[field] = value
        status, body = _request(base, "/api/assets/library/copy-to-story", payload, "POST")

    assert status == 409
    assert body["code"] == "library_copy_mismatch"
    assert body["message"]
    assert body["action"]


def test_library_copy_returns_a_recovery_action_when_aa_is_running(tmp_path, monkeypatch):
    """A generic failure leaves the workbench unable to guide the user through AA's write lock."""
    aa_data = tmp_path / "aa-data"
    source_project = aa_data / "projects" / "Source"
    source = source_project / "bgs" / "rain_roof.png"
    _background(source)
    write_manifest_atomic(source_project, {"BgOverrides": [r"bgs\rain_roof.png"]})
    con = assetdb.connect(tmp_path / "assets.db")
    digest = validate_background(source).candidate.sha256
    upsert_candidate(
        con, AssetCandidate(
            "background", source, "rain_roof", "rain_roof", digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(source_project), status="registered", install_path=str(source),
    )
    con.close()
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    monkeypatch.setattr(aa_project_assets, "is_aa_running", lambda: True)
    with _server(tmp_path, monkeypatch) as base:
        story = _open_named_story(base, tmp_path, "Current")
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])
        status, body = _request(base, "/api/assets/library/copy-to-story", {
            "story_token": story["story_token"],
            "source_copy_token": library["backgrounds"][0]["copies"][0]["copy_token"],
            "kind": "background", "aa_key": "rain_roof", "sha256": digest,
        }, "POST")

    assert status == 409
    assert body == {
        "ok": False,
        "code": "aa_running",
        "message": "AA 正在运行，当前不能写入素材。",
        "action": "关闭 AA 后在原位置重试。",
    }


@pytest.mark.parametrize("payload", [None, ["story_token"]])
def test_library_copy_rejects_non_object_payloads_with_a_structured_error(
    tmp_path, monkeypatch, payload
):
    """Letting malformed JSON reach the handler exception path breaks workbench recovery."""
    with _server(tmp_path, monkeypatch) as base:
        status, body = _request(base, "/api/assets/library/copy-to-story", payload, "POST")

    assert status == 400
    assert body == {
        "ok": False,
        "code": "library_copy_mismatch",
        "message": "素材信息与当前副本不一致。",
        "action": "刷新素材工作台后重新选择素材。",
    }


def test_library_copy_reports_an_invalid_story_token_separately(tmp_path, monkeypatch):
    """Mislabeling a dead story token as a copy failure sends the user to the wrong recovery flow."""
    with _server(tmp_path, monkeypatch) as base:
        status, body = _request(base, "/api/assets/library/copy-to-story", {
            "story_token": "story-expired",
            "source_copy_token": "copy-anything",
            "kind": "background", "aa_key": "rain_roof", "sha256": "digest",
        }, "POST")

    assert status == 404
    assert body == {
        "ok": False,
        "code": "invalid_story_token",
        "message": "当前剧情已失效。",
        "action": "重新打开剧情后刷新素材工作台。",
    }


def _registered_library_background(tmp_path, chapter="Chapter One"):
    aa_data = tmp_path / "aa-data"
    project = aa_data / "projects" / chapter
    save = aa_data / "saves" / chapter
    project_file = project / "bgs" / "rain_roof.png"
    save_file = save / "bgs" / "rain_roof.png"
    _background(project_file)
    save_file.parent.mkdir(parents=True)
    save_file.write_bytes(project_file.read_bytes())
    for root in (project, save):
        write_manifest_atomic(root, {"BgOverrides": [r"bgs\rain_roof.png"]})
    digest = validate_background(project_file).candidate.sha256
    con = assetdb.connect(tmp_path / "assets.db")
    upsert_candidate(
        con,
        AssetCandidate(
            "background",
            project_file,
            "rain_roof",
            "rain_roof",
            digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(project),
        status="registered",
        install_path=str(project_file),
        display_name="雨夜天台",
    )
    con.close()
    return aa_data, project


def test_library_copy_management_api_describes_and_removes_one_safe_copy(
    tmp_path, monkeypatch
):
    """Copy management must not expose paths or turn one confirmation into bulk removal."""
    aa_data, project = _registered_library_background(tmp_path)
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    with _server(tmp_path, monkeypatch) as base:
        story = _open_story(base, tmp_path)
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])
        item = library["backgrounds"][0]
        copy_token = item["copies"][0]["copy_token"]
        status, copies = _request(
            base,
            "/api/assets/library/copies?preview_token=" + item["preview_token"],
        )
        remove_status, removed = _request(
            base,
            "/api/assets/library/remove-copy",
            {"copy_token": copy_token, "confirm_chapter": "Chapter One"},
            "POST",
        )

    assert status == 200
    assert copies["copies"][0]["chapter"] == "Chapter One"
    assert copies["copies"][0]["references"] == []
    assert str(tmp_path) not in repr(copies)
    assert "scope" not in repr(copies)
    assert remove_status == 200
    assert removed == {
        "ok": True,
        "removed": True,
        "kind": "background",
        "aa_key": "rain_roof",
        "sha256": item["sha256"],
        "chapter": "Chapter One",
    }
    assert not (project / "bgs" / "rain_roof.png").exists()


def test_library_remove_copy_rejects_wrong_chapter_with_structured_recovery(
    tmp_path, monkeypatch
):
    """A stale confirmation must yield a recoverable conflict instead of deleting."""
    aa_data, project = _registered_library_background(tmp_path)
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    with _server(tmp_path, monkeypatch) as base:
        story = _open_story(base, tmp_path)
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])
        copy_token = library["backgrounds"][0]["copies"][0]["copy_token"]
        status, body = _request(
            base,
            "/api/assets/library/remove-copy",
            {"copy_token": copy_token, "confirm_chapter": "Other"},
            "POST",
        )

    assert status == 409
    assert body["code"] == "copy_confirmation_mismatch"
    assert body["message"] and body["action"]
    assert body["details"] == {}
    assert (project / "bgs" / "rain_roof.png").is_file()


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    con = assetdb.connect(tmp_path / "assets.db")
    project_root = tmp_path / "aa-data" / "projects" / "Chapter One"
    preview = project_root / "bgs" / "night.png"
    _background(preview)
    digest = validate_background(preview).candidate.sha256
    upsert_candidate(
        con, AssetCandidate("background", tmp_path / "private" / "night.png", "night", "night", digest),
        scope=str(project_root), status="registered", install_path=str(preview),
    )
    con.close()
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=tmp_path / "aa-data"))
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        yield base, opened["story_token"], project_root


def test_library_preview_uses_opaque_token_and_rejects_tampering(running_server):
    """Accepting a client path or an altered token would expose arbitrary installed files."""
    base, story_token, project_root = running_server
    status, payload = _request(base, "/api/assets/library?story_token=" + story_token)
    token = payload["backgrounds"][0]["preview_token"]

    assert status == 200
    assert str(project_root) not in repr(payload)
    assert _request_bytes(base, "/api/assets/library/preview?preview_token=" + token)[0] == 200
    assert _request_bytes(base, "/api/assets/library/preview?preview_token=" + token + "x")[0] == 404


def test_preflight_endpoint_runs_as_a_scoped_job_without_exposing_source_path(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: None)
    script = tmp_path / "Private Chapter.txt"
    script.write_text("旁白: 开始。\n", encoding="utf-8")
    file_token = webui.register_file_token(str(script))
    with _server(tmp_path, monkeypatch) as base:
        open_status, opened = _request(
            base, "/api/stories/open", {"file_token": file_token}, "POST"
        )
        status, accepted = _request(base, "/api/preflight", {
            "story_token": opened["story_token"], "file_token": file_token,
        }, "POST")
        job = None
        for _ in range(100):
            _, job = _request(base, "/api/jobs/" + accepted["job_id"])
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        _, current = _request(
            base, "/api/story/current?story_token=" + opened["story_token"]
        )
        approve_status, _ = _request(base, "/api/preflight/approve", {
            "story_token": opened["story_token"], "approved": True,
        }, "POST")
        _, confirmed = _request(
            base, "/api/story/current?story_token=" + opened["story_token"]
        )

    assert open_status == 200 and status == 202
    assert job["state"] == "succeeded"
    assert job["result"]["snapshot_saved"] is True
    assert job["result"]["characters"][0]["kind"] == "narrator"
    assert current["preflight_snapshot"]["state"] == "fresh"
    assert current["preflight_snapshot"]["approved"] is False
    assert approve_status == 200
    assert confirmed["preflight_snapshot"]["approved"] is True
    public = json.dumps(job["result"], ensure_ascii=False)
    assert str(script) not in public
    assert "source_path" not in public


def test_preflight_uses_story_source_after_the_picker_token_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: None)
    script = tmp_path / "Long Review.txt"
    script.write_text("旁白: 十分钟后继续。\n", encoding="utf-8")
    opening_token = webui.register_file_token(str(script))
    with _server(tmp_path, monkeypatch) as base:
        _, opened = _request(
            base, "/api/stories/open", {"file_token": opening_token}, "POST"
        )
        status, accepted = _request(base, "/api/preflight", {
            "story_token": opened["story_token"],
            "file_token": "ft-expired",
        }, "POST")
        job = None
        if status == 202:
            for _ in range(100):
                _, job = _request(base, "/api/jobs/" + accepted["job_id"])
                if job["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.01)

    assert status == 202
    assert job["state"] == "succeeded"
    assert job["result"]["analysis"]["lines"] == 1


def test_preflight_job_returns_result_when_snapshot_persistence_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: None)
    monkeypatch.setattr(
        webui.StoryWorkspaceRegistry,
        "set_preflight_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    script = tmp_path / "Unsaved Chapter.txt"
    script.write_text("旁白：开始。\n", encoding="utf-8")
    file_token = webui.register_file_token(str(script))
    with _server(tmp_path, monkeypatch) as base:
        _, opened = _request(base, "/api/stories/open", {"file_token": file_token}, "POST")
        status, accepted = _request(base, "/api/preflight", {
            "story_token": opened["story_token"], "file_token": file_token,
        }, "POST")
        for _ in range(100):
            _, job = _request(base, "/api/jobs/" + accepted["job_id"])
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)

    assert status == 202
    assert job["state"] == "succeeded"
    assert job["result"]["snapshot_saved"] is False
    assert job["result"]["characters"][0]["kind"] == "narrator"


def test_story_asset_list_excludes_other_project_assets_and_never_exposes_paths(tmp_path, monkeypatch):
    """Removing the scope predicate or serializing source_path would leak another story."""
    con = assetdb.connect(tmp_path / "assets.db")
    for project, stem in (("Chapter One", "one-night"), ("Other", "other-night")):
        source = tmp_path / f"{stem}.png"
        _background(source)
        upsert_candidate(
            con,
            AssetCandidate("background", source, stem, stem, stem),
            scope=str(tmp_path / "aa-data" / "projects" / project),
            status="registered",
            install_path=str(tmp_path / "aa-data" / "projects" / project / "bgs" / source.name),
        )
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        status, payload = _request(base, "/api/story/assets?story_token=" + opened["story_token"])

    assert status == 200
    assert [row["name"] for row in payload["backgrounds"]] == ["one-night"]
    assert payload["bgms"] == []
    assert "other-night" not in json.dumps(payload)
    assert str(tmp_path) not in json.dumps(payload)
    assert payload["counts"] == {"characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0}


def test_story_asset_cards_expose_safe_metadata_and_only_scoped_preview(tmp_path, monkeypatch):
    """Cards may show derived facts and a same-origin preview, never stored paths."""
    con = assetdb.connect(tmp_path / "assets.db")
    source = tmp_path / "private-source" / "night.png"
    _background(source)
    installed = tmp_path / "aa-data" / "projects" / "Chapter One" / "bgs" / "night.png"
    _background(installed)
    upsert_candidate(
        con,
        AssetCandidate("background", source, "night", "night", "digest", {
            "width": 32, "height": 18, "format": "PNG", "labels": {"place": "屋顶"},
        }),
        scope=str(tmp_path / "aa-data" / "projects" / "Chapter One"),
        status="registered", install_path=str(installed),
    )
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        token = opened["story_token"]
        status, catalog = _request(base, "/api/story/assets?story_token=" + token)
        preview_status, content_type, image = _request_bytes(
            base, "/api/story/assets/preview?story_token=" + token + "&kind=background&key=night"
        )
        other_status, _, _ = _request_bytes(
            base, "/api/story/assets/preview?story_token=" + token + "&kind=background&key=missing"
        )

    row = catalog["backgrounds"][0]
    assert status == 200
    assert row["width"] == 32 and row["height"] == 18
    assert row["aspect_ratio"] == "16:9"
    assert row["preview_available"] is True
    assert "待检测" not in row["resolution"]
    assert str(tmp_path) not in json.dumps(catalog)
    assert preview_status == 200 and content_type.startswith("image/png") and image.startswith(b"\x89PNG")
    assert other_status == 404


def test_story_asset_preview_and_metadata_cover_background_sound_character_and_scope(tmp_path, monkeypatch):
    """Every preview comes from a registered asset in this story, with safe card facts only."""
    con = assetdb.connect(tmp_path / "assets.db")
    project = tmp_path / "aa-data" / "projects" / "Chapter One"
    source = tmp_path / "private-source"
    bg_source, bg_install = source / "night.png", project / "bgs" / "night.png"
    _background(bg_source); _background(bg_install)
    sound_source, sound_install = source / "rain.wav", project / "sounds" / "rain.wav"
    _sound(sound_source); _sound(sound_install)
    character_source, character_install = source / "hero", project / "characters" / "hero-id"
    _character(character_source); _character(character_install)
    scope = str(project)
    upsert_candidate(con, AssetCandidate("background", bg_source, "night", "night", "bg", {
        "width": 32, "height": 18,
    }), scope=scope, status="registered", install_path=str(bg_install))
    upsert_candidate(con, AssetCandidate("sound", sound_source, "rain", "rain", "sound", {
        "duration": 0.1, "codec": "pcm_s16le", "sample_rate": 22050, "channels": 1,
    }), scope=scope, status="registered", install_path=str(sound_install))
    upsert_candidate(con, AssetCandidate("character", character_source, "hero", "hero-id", "hero", {
        "files": {name: str(character_source / filename) for name, filename in {
            "skel": "hero.skel", "atlas": "hero.atlas", "texture": "hero.png", "avatar": "hero-avatar.png",
        }.items()}, "faces": ["default"], "expression_status": "known",
    }), scope=scope, status="registered", install_path=str(character_install))
    # A card with incomplete metadata must label it honestly rather than inventing dimensions.
    unknown_source, unknown_install = source / "unknown.png", project / "bgs" / "unknown.png"
    _background(unknown_source); _background(unknown_install)
    upsert_candidate(con, AssetCandidate("background", unknown_source, "unknown", "unknown", "unknown"),
        scope=scope, status="registered", install_path=str(unknown_install))
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        token = opened["story_token"]
        status, catalog = _request(base, "/api/story/assets?story_token=" + token)
        bg = _request_bytes(base, "/api/story/assets/preview?story_token=" + token + "&kind=background&key=night")
        sound = _request_bytes(base, "/api/story/assets/preview?story_token=" + token + "&kind=sound&key=rain")
        character = _request_bytes(base, "/api/story/assets/preview?story_token=" + token + "&kind=character&key=hero-id")
        other_script = tmp_path / "Other.txt"; other_script.write_text("scene", encoding="utf-8")
        other_picker = webui.register_file_token(str(other_script))
        _, other = _request(base, "/api/stories/open", {"file_token": other_picker}, "POST")
        cross = _request_bytes(base, "/api/story/assets/preview?story_token=" + other["story_token"] + "&kind=character&key=hero-id")

    assert status == 200
    backgrounds = {item["aa_key"]: item for item in catalog["backgrounds"]}
    assert backgrounds["night"]["resolution"] == "32×18"
    assert backgrounds["night"]["aspect_ratio"] == "16:9"
    assert backgrounds["unknown"]["resolution"] == backgrounds["unknown"]["aspect_ratio"] == "待检测"
    sound_card = catalog["sounds"][0]
    assert {key: sound_card[key] for key in ("duration", "codec", "sample_rate", "channels")} == {
        "duration": 0.1, "codec": "pcm_s16le", "sample_rate": 22050, "channels": 1,
    }
    character_card = catalog["characters"][0]
    assert character_card["file_completeness"] == "完整"
    assert character_card["expression_status"] == "known"
    assert bg[0] == 200 and bg[1].startswith("image/png") and bg[2].startswith(b"\x89PNG")
    assert sound[0] == 200 and sound[1].startswith("audio/wav") and sound[2].startswith(b"RIFF")
    assert character[0] == 200 and character[1].startswith("image/png") and character[2].startswith(b"\x89PNG")
    assert cross[0] == 404


def test_story_preview_rejects_catalog_paths_outside_the_story_root_and_supports_sound_ranges(tmp_path, monkeypatch):
    """A scoped DB row must not turn a forged install_path into an arbitrary file reader."""
    con = assetdb.connect(tmp_path / "assets.db")
    project = tmp_path / "aa-data" / "projects" / "Chapter One"
    secret = tmp_path / "secret.wav"; _sound(secret)
    source = tmp_path / "source.wav"; _sound(source)
    upsert_candidate(con, AssetCandidate("sound", source, "leak", "leak", "digest", {}),
        scope=str(project), status="registered", install_path=str(secret))
    safe = project / "sounds" / "safe.wav"; _sound(safe)
    upsert_candidate(con, AssetCandidate("sound", source, "safe", "safe", "digest2", {}),
        scope=str(project), status="registered", install_path=str(safe))
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path); token = opened["story_token"]
        denied = _request_bytes(base, "/api/story/assets/preview?story_token=" + token + "&kind=sound&key=leak")
        request = Request(base + "/api/story/assets/preview?story_token=" + token + "&kind=sound&key=safe", headers={"Range": "bytes=0-3"})
        with urlopen(request) as response:
            partial = (response.status, response.headers["Content-Type"], response.headers["Content-Range"], response.headers["Accept-Ranges"], response.read())
        invalid = Request(base + "/api/story/assets/preview?story_token=" + token + "&kind=sound&key=safe", headers={"Range": "bytes=999999-"})
        try:
            with urlopen(invalid) as response:
                invalid_status = response.status
        except Exception as exc:
            with exc as response:
                invalid_status = response.status

    assert denied[0] == 404 and secret.read_bytes() not in denied[2]
    assert partial == (206, "audio/wav", "bytes 0-3/4454", "bytes", b"RIFF")
    assert invalid_status == 416


def test_story_asset_list_excludes_a_row_with_invalid_source_metadata(tmp_path):
    """A malformed metadata record cannot prove an explicit custom source and must fail closed."""
    con = assetdb.connect(tmp_path / "assets.db")
    scope = str(tmp_path / "project")
    source = tmp_path / "one.png"; _background(source)
    upsert_candidate(con, AssetCandidate("background", source, "one", "one", "digest"), scope=scope, status="registered", install_path=str(source))
    con.execute("UPDATE asset_install SET metadata_json='{bad json' WHERE scope=?", (scope,)); con.commit()
    payload = __import__("asset_catalog").list_story_assets(con, scope=scope)
    assert payload["backgrounds"] == []


def test_history_endpoints_copy_background_and_keep_history_path_private(tmp_path, monkeypatch):
    """Using a browser-provided source path instead of a history token would fail this boundary."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    source = history / "bgs" / "night.png"
    _background(source)
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        status, projects = _request(base, "/api/history/projects")
        assert status == 200
        assert str(history) not in json.dumps(projects)
        status, assets = _request(base, "/api/history/assets?history_token=" + projects[0]["history_token"])
        assert status == 200
        assert str(source) not in json.dumps(assets)
        status, copied = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")
        catalog_status, catalog = _request(
            base, "/api/story/assets?story_token=" + opened["story_token"]
        )

    assert status == 200
    assert copied["kind"] == "background"
    assert "source_path" not in copied
    assert catalog_status == 200
    assert catalog["backgrounds"][0]["source_project"] == "Old Project"
    assert str(source) not in json.dumps(catalog)
    assert (aa_data / "projects" / "Chapter One" / "bgs" / "night.png").is_file()
    assert (aa_data / "saves" / "Chapter One" / "bgs" / "night.png").is_file()


def test_history_copy_returns_stable_missing_source_status(tmp_path, monkeypatch):
    """Treating a disappeared source as an internal error breaks recovery UI."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    source = history / "bgs" / "night.png"
    _background(source)
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        _, projects = _request(base, "/api/history/projects")
        old_project = next(row for row in projects if row["project"] == "Old Project")
        _, assets = _request(base, "/api/history/assets?history_token=" + old_project["history_token"])
        source.unlink()
        status, result = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")

    assert status == 410
    assert result["code"] == "history_source_missing"


def test_history_copy_returns_stable_conflict_and_aa_running_statuses(tmp_path, monkeypatch):
    """Collapsing operational conflicts into 500 prevents the asset task UI recovering."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    source = history / "bgs" / "night.png"
    _background(source, "navy")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        _, projects = _request(base, "/api/history/projects")
        _, assets = _request(base, "/api/history/assets?history_token=" + projects[0]["history_token"])
        _background(aa_data / "projects" / "Chapter One" / "bgs" / "night.png", "red")
        status, conflict = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")
        assert status == 409
        assert conflict["code"] == "same_name_different_content"

        (aa_data / "projects" / "Chapter One" / "bgs" / "night.png").unlink()
        monkeypatch.setattr(aa_project_assets, "is_aa_running", lambda: True)
        status, running = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")

    assert status == 409
    assert running["code"] == "aa_running"


def test_history_copy_returns_validation_failed_for_a_manifested_invalid_file(tmp_path, monkeypatch):
    """Skipping current validation would install a malformed historical asset."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    source = history / "bgs" / "broken.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not an image")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\broken.png"]})
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        _, projects = _request(base, "/api/history/projects")
        old_project = next(row for row in projects if row["project"] == "Old Project")
        _, assets = _request(base, "/api/history/assets?history_token=" + old_project["history_token"])
        status, result = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")

    assert status == 422
    assert result["code"] == "validation_failed"


def test_history_character_identifier_conflict_is_a_stable_409(tmp_path, monkeypatch):
    """Misclassifying an existing Identifier with another identity as validation hides a conflict."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    _character(history / "characters" / "custom-hero")
    history_entry = {
        "Identifier": "custom-hero", "Name": "Archive Hero", "Nickname": "Archive",
        "SpinePortraitPath": r"characters\custom-hero\hero",
        "SmallPortraitPath": r"characters\custom-hero\hero-avatar.png",
    }
    write_manifest_atomic(history, {"CharacterOverrides": [history_entry]})
    conflicting_entry = {**history_entry, "Name": "Current Hero", "Nickname": "Current"}
    for root in (aa_data / "projects" / "Chapter One", aa_data / "saves" / "Chapter One"):
        write_manifest_atomic(root, {"CharacterOverrides": [conflicting_entry]})

    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        _, projects = _request(base, "/api/history/projects")
        old_project = next(row for row in projects if row["project"] == "Old Project")
        _, assets = _request(base, "/api/history/assets?history_token=" + old_project["history_token"])
        status, result = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")

    assert status == 409
    assert result["code"] == "same_name_different_content"


def test_history_copy_error_payloads_do_not_disclose_internal_paths(tmp_path, monkeypatch):
    """Forwarding a registry exception verbatim leaks AA and history filesystem paths."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "Old Project"
    source = history / "bgs" / "night.png"
    _background(source, "navy")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    destination = aa_data / "projects" / "Chapter One" / "bgs" / "night.png"
    _background(destination, "red")
    with _server(tmp_path, monkeypatch) as base:
        opened = _open_story(base, tmp_path)
        _, projects = _request(base, "/api/history/projects")
        old_project = next(row for row in projects if row["project"] == "Old Project")
        _, assets = _request(base, "/api/history/assets?history_token=" + old_project["history_token"])
        status, response = _request(base, "/api/story/assets/copy", {
            "story_token": opened["story_token"],
            "history_asset_token": assets[0]["history_asset_token"],
        }, "POST")

    assert status == 409
    payload = response["e"]
    assert str(aa_data) not in payload
    assert str(history) not in payload
    assert str(destination) not in payload


def test_background_label_registration_queues_server_side_analysis(tmp_path, monkeypatch):
    """A context-free background import must become usable before vision labeling runs."""
    queued = []

    def queue(payload):
        queued.append(dict(payload))
        return {"status": "labeling", "queued": True, "job_id": "background-label-test"}

    monkeypatch.setattr(webui, "queue_background_label_analysis", queue, raising=False)
    source = tmp_path / "incoming" / "night-platform.png"
    _background(source)
    file_token = webui.register_file_token(str(source))
    with _server(tmp_path, monkeypatch) as base:
        story = _open_story(base, tmp_path)
        status, body = _request(base, "/api/assets/register", {
            "kind": "background",
            "file_token": file_token,
            "story_token": story["story_token"],
            "display_name": "夜间站台",
        }, "POST")

    assert status == 200
    assert body["status"] == "registered"
    assert body["background_analysis"] == {
        "status": "labeling", "queued": True, "job_id": "background-label-test",
    }
    assert queued == [{"aa_key": body["aa_key"], "sha256": body["sha256"]}]
    assert str(source) not in repr(body)
    assert str(source) not in repr(queued)


def test_background_label_registration_uses_supplied_scene_labels_without_vision(
    tmp_path, monkeypatch
):
    """Scene semantics are already known, so registration must persist them without a second AI call."""
    monkeypatch.setattr(
        webui,
        "queue_background_label_analysis",
        lambda payload: pytest.fail("scene labels must skip vision"),
        raising=False,
    )
    source = tmp_path / "incoming" / "rain-room.png"
    _background(source)
    file_token = webui.register_file_token(str(source))
    labels = {
        "label": "雨夜候车厅", "description": "玻璃窗外有雨",
        "place": "候车厅", "indoor_outdoor": "室内", "time": "夜晚",
        "weather": "雨", "season": "", "mood": "安静", "tags": ["雨夜", "车站"],
    }
    with _server(tmp_path, monkeypatch) as base:
        story = _open_story(base, tmp_path)
        status, body = _request(base, "/api/assets/register", {
            "kind": "background", "file_token": file_token,
            "story_token": story["story_token"], "display_name": "雨夜候车厅",
            "labels": labels,
        }, "POST")
        _, library = _request(base, "/api/assets/library?story_token=" + story["story_token"])

    assert status == 200
    assert body["background_analysis"] == {"status": "ready", "queued": False}
    details = library["backgrounds"][0]["details"]
    assert details["label_status"] == "ready"
    assert details["labels"]["label"] == "雨夜候车厅"
    assert details["labels"]["tags"] == "雨夜, 车站"


def test_background_label_manual_save_updates_library_and_retry_rejects_browser_path(
    tmp_path, monkeypatch
):
    """Workbench edits use immutable catalog identity; retry never trusts a browser path."""
    aa_data, _ = _registered_library_background(tmp_path)
    monkeypatch.setattr(webui, "HISTORY_ASSET_BROWSER", HistoryAssetBrowser(aa_data=aa_data))
    queued = []
    monkeypatch.setattr(
        webui,
        "queue_background_label_analysis",
        lambda payload: queued.append(dict(payload)) or {
            "status": "labeling", "queued": True, "job_id": "background-label-retry"
        },
        raising=False,
    )
    con = assetdb.connect(tmp_path / "assets.db")
    row = con.execute(
        "SELECT aa_key,sha256 FROM asset_install WHERE kind='background' LIMIT 1"
    ).fetchone()
    con.close()
    identity = {"aa_key": row["aa_key"], "sha256": row["sha256"]}

    with _server(tmp_path, monkeypatch) as base:
        save_status, saved = _request(base, "/api/assets/library/background-labels", {
            **identity,
            "labels": {
                "label": "雨夜天台", "description": "湿润的屋顶", "place": "屋顶",
                "indoor_outdoor": "室外", "time": "夜晚", "weather": "雨",
                "season": "", "mood": "冷清", "tags": ["屋顶", "雨夜"],
            },
        }, "POST")
        _, library = _request(base, "/api/assets/library")
        bad_status, bad = _request(base, "/api/assets/library/background-label", {
            **identity, "source": str(tmp_path / "private.png")
        }, "POST")
        retry_status, retry = _request(
            base, "/api/assets/library/background-label", identity, "POST"
        )

    assert save_status == 200 and saved["label_status"] == "ready"
    details = library["backgrounds"][0]["details"]
    assert details["labels"]["label"] == "雨夜天台"
    assert details["labels"]["tags"] == "屋顶, 雨夜"
    assert bad_status == 400 and bad["code"] == "invalid_background_label_request"
    assert retry_status == 202
    assert retry["job_id"] == "background-label-retry"
    assert queued == [identity]


def test_background_label_worker_persists_failed_status_when_vision_fails(tmp_path, monkeypatch):
    """A model failure must not roll back the already registered background."""
    aa_data, _ = _registered_library_background(tmp_path)
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class FailingProvider:
        def complete_json_vision(self, *args, **kwargs):
            raise RuntimeError("vision unavailable")

    monkeypatch.setattr(
        webui, "_optional_vision_provider", lambda: (FailingProvider(), None)
    )
    con = assetdb.connect(tmp_path / "assets.db")
    row = con.execute(
        "SELECT aa_key,sha256 FROM asset_install WHERE kind='background' LIMIT 1"
    ).fetchone()
    con.close()

    with pytest.raises(RuntimeError, match="vision unavailable"):
        webui.background_label_worker({"aa_key": row["aa_key"], "sha256": row["sha256"]})

    con = assetdb.connect(tmp_path / "assets.db")
    library = __import__("asset_catalog").list_library_assets(con)
    con.close()
    details = library["backgrounds"][0]["details"]
    assert details["label_status"] == "failed"
    assert details["label_error"] == "vision unavailable"
    assert library["backgrounds"][0]["copy_count"] == 1


def test_background_label_failure_never_exposes_the_registered_copy_path(tmp_path, monkeypatch):
    """Provider and decoder exceptions may contain paths that the workbench must never receive."""
    _registered_library_background(tmp_path)
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    private_path = tmp_path / "aa-data" / "projects" / "Chapter One" / "bgs" / "rain_roof.png"

    class FailingProvider:
        def complete_json_vision(self, *args, **kwargs):
            raise RuntimeError(f"cannot decode {private_path}")

    monkeypatch.setattr(
        webui, "_optional_vision_provider", lambda: (FailingProvider(), None)
    )
    con = assetdb.connect(tmp_path / "assets.db")
    row = con.execute(
        "SELECT aa_key,sha256 FROM asset_install WHERE kind='background' LIMIT 1"
    ).fetchone()
    con.close()

    with pytest.raises(RuntimeError):
        webui.background_label_worker({"aa_key": row["aa_key"], "sha256": row["sha256"]})

    con = assetdb.connect(tmp_path / "assets.db")
    library = __import__("asset_catalog").list_library_assets(con)
    con.close()
    label_error = library["backgrounds"][0]["details"]["label_error"]
    assert label_error == "背景识别失败，请重试或手动补充"
    assert str(private_path) not in repr(library)


def test_custom_background_candidate_preflight_job_keeps_story_preview_scope(tmp_path, monkeypatch):
    """A preflight job may return only a current-story custom candidate and scoped preview marker."""
    source = tmp_path / "incoming" / "rain-station.png"
    _background(source)
    captured = {}

    class Provider:
        def complete_json(self, _static, volatile, _user, _schema):
            custom = json.loads(volatile)["custom_backgrounds"]
            captured["custom"] = custom
            key = str(custom[0]["aa_key"])
            return {
                "characters": [], "assets": [], "issues": [],
                "usage_chain": [{
                    "segment": "开场", "location": "车站", "start": "第1行", "end": "第1行",
                    "evidence": "雨夜的车站。", "needs": [{
                        "kind": "background", "name": "雨夜车站", "location": "第1行",
                        "reason": "场景匹配", "confidence": 0.95,
                        "candidates": [
                            {"aa_key": key, "confidence": 0.92, "reason": "本章已生成"},
                            {"aa_key": "forged", "confidence": 0.99, "reason": "跨章伪造"},
                        ],
                    }],
                }],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    with _server(tmp_path, monkeypatch) as base:
        story = _open_story(base, tmp_path)
        file_token = webui.register_file_token(str(source))
        _, imported = _request(base, "/api/assets/register", {
            "kind": "background", "file_token": file_token,
            "story_token": story["story_token"],
            "labels": {"label": "雨夜车站", "place": "车站", "time": "夜晚"},
        }, "POST")
        script = tmp_path / "Chapter One.txt"
        script_token = webui.register_file_token(str(script))
        status, accepted = _request(base, "/api/preflight", {
            "story_token": story["story_token"], "file_token": script_token,
        }, "POST")
        for _ in range(100):
            _, job = _request(base, "/api/jobs/" + accepted["job_id"])
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        preview = _request_bytes(
            base,
            "/api/story/assets/preview?story_token=" + story["story_token"]
            + "&kind=background&key=" + str(imported["aa_key"]),
        )

    assert status == 202 and job["state"] == "succeeded"
    candidate = job["result"]["usage_chain"][0]["needs"][0]["candidates"][0]
    assert candidate["aa_key"] == str(imported["aa_key"])
    assert candidate["source"] == "custom"
    assert candidate["preview_source"] == "story"
    assert [item["aa_key"] for item in captured["custom"]] == [str(imported["aa_key"])]
    assert preview[0] == 200 and preview[2].startswith(b"\x89PNG")
    assert "forged" not in json.dumps(job["result"])
    assert str(tmp_path) not in json.dumps(job["result"], ensure_ascii=False)


def test_background_binding_api_accepts_only_current_story_registered_background(
    tmp_path, monkeypatch
):
    source = tmp_path / "incoming" / "rain-station.png"
    _background(source)
    with _server(tmp_path, monkeypatch) as base:
        current = _open_named_story(base, tmp_path, "Current")
        other = _open_named_story(base, tmp_path, "Other")
        file_token = webui.register_file_token(str(source))
        _, imported = _request(base, "/api/assets/register", {
            "kind": "background", "file_token": file_token,
            "story_token": current["story_token"],
            "labels": {"label": "雨夜车站", "place": "车站"},
        }, "POST")
        for story, segment in ((current, "当前章"), (other, "其他章")):
            webui.story_workspace().set_preflight_snapshot(story["story_token"], {
                "ai_status": "completed", "usage_chain_status": "completed",
                "characters": [], "assets": [], "issues": [],
                "usage_chain": [{"segment": segment, "location": "车站", "needs": [{
                    "kind": "background", "name": "雨夜车站", "location": "第1行",
                    "status": "missing", "candidates": [],
                }]}],
            })
        rejected_status, rejected = _request(base, "/api/preflight/background-binding", {
            "story_token": other["story_token"],
            "selector": {"segment": "其他章", "location": "第1行",
                         "requested_name": "雨夜车站"},
            "binding": {"aa_key": str(imported["aa_key"]),
                        "selected_label": "雨夜车站"},
        }, "POST")
        accepted_status, accepted = _request(base, "/api/preflight/background-binding", {
            "story_token": current["story_token"],
            "selector": {"segment": "当前章", "location": "第1行",
                         "requested_name": "雨夜车站"},
            "binding": {"aa_key": str(imported["aa_key"]),
                        "selected_label": "雨夜车站"},
        }, "POST")

    assert rejected_status == 404
    assert rejected["code"] == "background_not_registered"
    assert accepted_status == 200
    need = accepted["preflight_snapshot"]["result"]["usage_chain"][0]["needs"][0]
    assert need["status"] == "registered"
    assert need["aa_key"] == str(imported["aa_key"])
    assert need["source"] == "custom"
    assert need["preview_source"] == "story"
    assert str(tmp_path) not in json.dumps(accepted, ensure_ascii=False)


def test_background_binding_api_accepts_verified_official_key_and_persists_it(
    tmp_path, monkeypatch
):
    with _server(tmp_path, monkeypatch) as base:
        story = _open_named_story(base, tmp_path, "OfficialBinding")
        con = webui.db()
        try:
            con.execute(
                "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
                ("BG_ShoppingDistrict", 101, "Shopping District"),
            )
            con.commit()
        finally:
            con.close()
        webui.story_workspace().set_preflight_snapshot(story["story_token"], {
            "ai_status": "completed", "usage_chain_status": "completed",
            "characters": [], "assets": [], "issues": [],
            "usage_chain": [{"segment": "场景一", "location": "商店街", "needs": [{
                "kind": "background", "name": "商店街入口钟塔", "location": "第1行",
                "status": "approximate", "candidates": [{
                    "aa_key": "BG_ShoppingDistrict", "source": "official",
                }],
            }]}],
        })

        status, accepted = _request(base, "/api/preflight/background-binding", {
            "story_token": story["story_token"],
            "selector": {"segment": "场景一", "location": "第1行",
                         "requested_name": "商店街入口钟塔"},
            "binding": {"aa_key": "BG_ShoppingDistrict",
                        "selected_label": "untrusted client label"},
        }, "POST")
        _, restored = _request(
            base, "/api/story/current?story_token=" + story["story_token"],
            method="GET",
        )

    assert status == 200
    need = accepted["preflight_snapshot"]["result"]["usage_chain"][0]["needs"][0]
    assert need["status"] == "registered"
    assert need["aa_key"] == "BG_ShoppingDistrict"
    assert need["selected_label"] == "Shopping District"
    assert need["source"] == "official"
    assert need["preview_source"] == "official"
    assert restored["preflight_snapshot"]["result"]["usage_chain"][0]["needs"][0] == need
