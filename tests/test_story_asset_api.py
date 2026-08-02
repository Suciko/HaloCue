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

from PIL import Image

import assetdb
import aa_project_assets
import webui
from asset_catalog import upsert_candidate
from asset_models import AssetCandidate
from aa_registry import write_manifest_atomic
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

    assert open_status == 200 and status == 202
    assert job["state"] == "succeeded"
    assert job["result"]["characters"][0]["kind"] == "narrator"
    public = json.dumps(job["result"], ensure_ascii=False)
    assert str(script) not in public
    assert "source_path" not in public


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


def test_story_asset_list_survives_one_invalid_metadata_json_row(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = str(tmp_path / "project")
    source = tmp_path / "one.png"; _background(source)
    upsert_candidate(con, AssetCandidate("background", source, "one", "one", "digest"), scope=scope, status="registered", install_path=str(source))
    con.execute("UPDATE asset_install SET metadata_json='{bad json' WHERE scope=?", (scope,)); con.commit()
    payload = __import__("asset_catalog").list_story_assets(con, scope=scope)
    assert payload["backgrounds"][0]["resolution"] == "待检测"


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
