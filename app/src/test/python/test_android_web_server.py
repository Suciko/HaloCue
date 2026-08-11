import json
import socket
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest

import assetdb
import android_web_server


@pytest.fixture(autouse=True)
def stopped_server():
    android_web_server.stop()
    yield
    android_web_server.stop()


@pytest.fixture
def running_server(tmp_path):
    return android_web_server.start(str(tmp_path), "test-session")


def _origin(server):
    return server["url"].split("?", 1)[0].rstrip("/")


def _session_request(url, method="GET", body=None, **headers):
    return urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"X-HaloCue-Session": "test-session", **headers},
    )


def test_api_rejects_missing_session(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(_origin(running_server) + "/api/android/health")

    assert exc.value.code == 403
    assert json.load(exc.value)["code"] == "invalid_session"


def test_encoded_api_path_rejects_missing_session(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(
            _origin(running_server) + "/api%2fandroid%2fhealth"
        )

    assert exc.value.code == 403
    assert json.load(exc.value)["code"] == "invalid_session"


def test_delete_api_rejects_missing_session(running_server):
    request = urllib.request.Request(
        _origin(running_server) + "/api/cards/card-1",
        data=b"{}",
        method="DELETE",
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request)

    assert exc.value.code == 403
    assert json.load(exc.value)["code"] == "invalid_session"


def test_api_accepts_session_header(running_server):
    payload = json.load(
        urllib.request.urlopen(
            _session_request(_origin(running_server) + "/api/android/health")
        )
    )

    assert payload == {"ok": True, "runtime": "android-webui"}


def test_root_sets_strict_cookie_and_cookie_authenticates_media(tmp_path):
    preview_root = tmp_path / "workspace" / "cache" / "official-previews"
    preview = preview_root / "avatars" / "student.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview-bytes")
    (preview_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ready",
                "fingerprint": "",
                "counts": {"backgrounds": 0, "avatars": 1, "failed": 0},
                "records": [
                    {
                        "kind": "avatar",
                        "key": "student",
                        "normalized_key": "student",
                        "path": "avatars/student.png",
                        "source_fingerprint": "test",
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    server = android_web_server.start(str(tmp_path), "test-session")

    root = urllib.request.urlopen(server["url"])
    cookie = root.headers["Set-Cookie"]
    assert cookie == "HaloCueSession=test-session; HttpOnly; SameSite=Strict; Path=/"
    assert b'id="viewTitle"' in root.read()

    media = urllib.request.Request(
        _origin(server) + "/api/resources/preview?kind=avatar&key=student",
        headers={"Cookie": cookie.split(";", 1)[0]},
    )
    assert urllib.request.urlopen(media).read() == b"preview-bytes"


def test_static_script_is_public_and_root_rejects_wrong_query_session(running_server):
    script = urllib.request.urlopen(_origin(running_server) + "/js/api.js")
    assert script.status == 200
    assert b"X-HaloCue-Session" in script.read()

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(_origin(running_server) + "/?session=wrong")
    assert exc.value.code == 403


def test_start_is_idempotent_and_stop_releases_loopback_port(tmp_path):
    first = android_web_server.start(str(tmp_path), "active-session")
    second = android_web_server.start(str(tmp_path / "ignored"), "other-session")

    assert second == first
    assert "session=active-session" in second["url"]
    port = first["port"]
    android_web_server.stop()
    android_web_server.stop()

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_android_runtime_uses_workspace_token_pickers_and_capability_errors(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    picker = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/story-files/host")
        )
    )
    assert [root["name"] for root in picker["roots"]] == ["workspace"]
    assert picker["roots"][0]["entry_token"].startswith("entry-")
    index = json.loads(
        (tmp_path / "workspace" / "databases" / "aa_resources.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(index["bg"]) >= 500
    assert len(index["characters"]) >= 900
    assert len(index["sounds"]) >= 300
    assert {row["identifier"] for row in index["characters"]} >= {
        "梦",
        "阿露(礼服)",
        "临战莉音",
    }
    assert index["identifier_aliases"]["阿露(礼服)"] == "阿露（礼服）"
    assert index["_android_mapping"]["summary"]["identifier_aliases"] == 52
    setup = json.load(
        urllib.request.urlopen(_session_request(origin + "/api/setup/status"))
    )
    assert setup["aa"]["resource_mapping"]["status"] == "ready"
    assert setup["aa"]["resource_mapping"]["characters"] == len(index["characters"])
    characters = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/characters?q=" + quote("阿露"))
        )
    )
    assert any(row["ident"] == "阿露(礼服)" for row in characters)

    with pytest.raises(urllib.error.HTTPError) as install_error:
        urllib.request.urlopen(
            _session_request(origin + "/api/install/options?token=draft&build_id=build")
        )
    assert install_error.value.code == 501
    assert json.load(install_error.value)["code"] == "direct_aa_install_unavailable"

    with pytest.raises(urllib.error.HTTPError) as spine_error:
        urllib.request.urlopen(
            _session_request(
                origin + "/api/settings/spine-cli",
                method="POST",
                body=b"{}",
                **{"Content-Type": "application/json"},
            )
        )
    assert spine_error.value.code == 501
    assert json.load(spine_error.value)["code"] == "spine_rendering_unavailable"


def test_android_runtime_seeds_and_serves_bundled_official_character_avatars(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    characters = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/characters?q=" + quote("日步美"))
        )
    )
    character = next(row for row in characters if row["name"] == "日步美")

    assert character["avatar"].startswith("/thumb/av/")
    avatar = urllib.request.urlopen(_session_request(origin + character["avatar"]))
    assert avatar.headers["Content-Type"] in {"image/png", "image/jpeg"}
    assert len(avatar.read()) > 100


def test_android_runtime_serves_extra_package_character_avatars(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    characters = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/characters?q=" + quote("\u548f\u53f6"))
        )
    )
    character = next(row for row in characters if row["name"] == "\u548f\u53f6")

    assert character["avatar"].startswith("/thumb/av/")
    avatar = urllib.request.urlopen(_session_request(origin + character["avatar"]))
    assert avatar.headers["Content-Type"] in {"image/png", "image/jpeg"}
    assert len(avatar.read()) > 100


def test_android_runtime_serves_extra_package_avatar_for_existing_pc_character(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    characters = json.load(
        urllib.request.urlopen(_session_request(origin + "/api/characters"))
    )
    character = next(
        row for row in characters if row["spine"].replace("\\", "/").endswith("/NP0176_spr")
    )

    assert character["faces"] == 11
    assert character["avatar"] == "/thumb/av/NP0176_spr"
    avatar = urllib.request.urlopen(_session_request(origin + character["avatar"]))
    assert avatar.headers["Content-Type"] == "image/png"
    assert len(avatar.read()) > 100


def test_character_picker_filters_placeholders_and_inherits_variant_club(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    characters = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/characters?q=" + quote("爱丽丝"))
        )
    )
    aris_variants = [
        row for row in characters
        if row["spine"].replace("\\", "/").endswith("/CharacterSpine_aris_noweapon")
    ]

    assert aris_variants
    assert all(row["club"] for row in aris_variants)
    assert not any("??" in str(row["ident"]) or "??" in str(row["name"]) for row in characters)


def test_placeholder_filter_recognizes_ascii_and_fullwidth_question_marks():
    assert assetdb._looks_placeholder("???") is True
    assert assetdb._looks_placeholder("???N") is True
    assert assetdb._looks_placeholder("？？？") is True
    assert assetdb._looks_placeholder("？？？N") is True
    assert assetdb._looks_placeholder("爱丽丝") is False


def test_android_runtime_serves_bundled_official_background_previews(tmp_path):
    server = android_web_server.start(str(tmp_path), "test-session")
    origin = _origin(server)

    backgrounds = json.load(
        urllib.request.urlopen(
            _session_request(origin + "/api/backgrounds?q=BG_GameDevRoom")
        )
    )
    background = next(row for row in backgrounds if row["name"] == "BG_GameDevRoom")

    assert background["img"] is True
    preview = urllib.request.urlopen(
        _session_request(origin + "/thumb/bg/BG_GameDevRoom?px=240")
    )
    assert preview.headers["Content-Type"] == "image/jpeg"
    assert len(preview.read()) > 100


def test_android_runtime_upgrades_legacy_empty_resource_index(tmp_path):
    databases = tmp_path / "workspace" / "databases"
    databases.mkdir(parents=True)
    index_path = databases / "aa_resources.json"
    index_path.write_text(
        json.dumps({"bg": {}, "characters": {}, "sounds": []}),
        encoding="utf-8",
    )

    android_web_server.configure_android_runtime(str(tmp_path))

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["characters"]) >= 900


def test_android_runtime_preserves_nonempty_resource_index(tmp_path):
    databases = tmp_path / "workspace" / "databases"
    databases.mkdir(parents=True)
    index_path = databases / "aa_resources.json"
    custom = {
        "bg": {"custom room": 123},
        "characters": [{"identifier": "custom-character", "faces": []}],
        "sounds": ["custom-sound"],
    }
    index_path.write_text(json.dumps(custom), encoding="utf-8")

    android_web_server.configure_android_runtime(str(tmp_path))

    assert json.loads(index_path.read_text(encoding="utf-8")) == custom
