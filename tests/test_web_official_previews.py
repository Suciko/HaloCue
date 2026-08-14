import io
from pathlib import Path
import contextlib
import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image
import pytest

import assetdb
import webui
from official_preview_index import OfficialPreviewIndex, PreviewIndexState


@pytest.fixture(autouse=True)
def _isolate_local_aa_discovery(monkeypatch):
    monkeypatch.setattr(
        webui,
        "_current_aa_discovery",
        lambda: type("Discovery", (), {
            "catalog": None,
            "resource_cache": None,
        })(),
    )


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
        '{"schema_version":3,"status":"ready",'
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


def test_character_avatar_uses_preview_matching_official_spine(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))

    assert webui.character_avatar_path(
        "", "UIs/03_Scenario/02_Character/CharacterSpine_Hifumi"
    ) == (store.root / "official-avatar.png")


def test_character_list_exposes_avatar_route_only_when_preview_exists(
    tmp_path,
    monkeypatch,
):
    _configure_preview_store(tmp_path, monkeypatch)
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    import asset_catalog
    asset_catalog.migrate(con)
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


def test_character_list_hides_unnamed_observed_aap_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    con.execute(
        "INSERT INTO character(ident, name, source) VALUES(?, NULL, 'observed')",
        ("1113",),
    )
    con.execute(
        "INSERT INTO face(ident, face_id, raw, label, label_cn, source) "
        "VALUES(?, '00', '00', '', '', 'observed')",
        ("1113",),
    )
    assetdb.import_index(con, {"characters": [{
        "identifier": "hifumi", "name": "Hifumi", "avatar": "",
        "spine": "", "faces": [],
    }]})
    con.close()

    rows = webui.list_characters()

    assert [row["ident"] for row in rows] == ["hifumi"]


def test_character_list_imports_official_catalog_once(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    discovery = type("Discovery", (), {
        "catalog": catalog,
        "resource_cache": cache,
    })()
    monkeypatch.setattr(webui, "_current_aa_discovery", lambda: discovery)
    calls = []

    def load_official(*, cache_root, catalog_path):
        calls.append((cache_root, catalog_path))
        return [{
            "identifier": "official-hifumi", "name": "Hifumi",
            "club": "Trinity", "spine": "official/spine",
            "avatar": "Student_Portrait_Hifumi",
            "source": "official_flatdata", "faces": [],
        }]

    monkeypatch.setattr(webui, "harvest_official_characters", load_official)

    first = webui.list_characters()
    second = webui.list_characters()

    assert [row["ident"] for row in first] == ["official-hifumi"]
    assert [row["ident"] for row in second] == ["official-hifumi"]
    assert calls == [(cache, catalog)]


def test_character_list_orders_official_default_before_outfit_variant(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    assetdb.import_index(con, {"characters": [
        {"identifier": "winter", "name": "爱丽丝", "spine": "characters/NP0234_spr/NP0234_spr", "avatar": "", "faces": []},
        {"identifier": "아리스N", "name": "愛麗絲", "spine": "UIs/03_Scenario/02_Character/CharacterSpine_aris_noweapon", "avatar": "Student_Portrait_Aris", "faces": []},
        {"identifier": "아리스", "name": "愛麗絲", "spine": "UIs/03_Scenario/02_Character/CharacterSpine_aris", "avatar": "Student_Portrait_Aris", "faces": []},
    ]})
    con.execute("UPDATE character SET name='爱丽丝', source='overrides' WHERE ident='winter'")
    con.execute("UPDATE character SET name='愛麗絲', source='observed' WHERE ident IN ('아리스N','아리스')")
    con.commit()
    con.close()
    rows = webui.list_characters("爱丽丝", 20)
    assert rows[0]["ident"] == "아리스"


def test_character_list_uses_registered_custom_avatar_when_catalog_row_has_no_avatar(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    import asset_catalog
    asset_catalog.migrate(con)
    assetdb.import_index(con, {"characters": [{
        "identifier": "custom-kei", "name": "凯伊", "avatar": "", "spine": "", "faces": [],
    }]})
    installed = tmp_path / "projects" / "chapter" / "characters" / "custom-kei"
    _make_image(installed / "kei-avatar.png", "red")
    con.execute(
        """INSERT INTO asset_install
        (scope,kind,aa_key,display_name,source_path,sha256,status,install_path,metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            str(installed.parents[2]), "character", "custom-kei", "凯伊", str(installed), "digest",
            "registered", str(installed), json.dumps({
                "files": {"avatar": "private/source/kei-avatar.png"},
                "catalog_source": "history_import",
            }),
        ),
    )
    con.commit()
    con.close()

    row = webui.list_characters("凯伊")[0]

    assert row["avatar"] == "/thumb/av/custom-kei"
    assert str(tmp_path) not in repr(row)


def test_official_background_picker_excludes_story_registered_custom_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    import asset_catalog
    asset_catalog.migrate(con)
    con.executemany(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        [
            ("BG_GameCenter", 101, "Game Center"),
            ("3040691084", 3040691084, "自定义游戏中心"),
        ],
    )
    con.execute(
        """INSERT INTO asset_install
        (scope,kind,aa_key,display_name,source_path,sha256,status,install_path,metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            str(tmp_path / "project"), "background", "3040691084", "自定义游戏中心",
            str(tmp_path / "custom.png"), "digest", "registered",
            str(tmp_path / "project" / "bgs" / "custom.png"), "{}",
        ),
    )
    con.commit()
    con.close()

    rows = webui.list_backgrounds(only_ready=True, only_official=True)

    assert [row["name"] for row in rows] == ["BG_GameCenter"]


def test_character_list_uses_catalog_avatar_when_database_row_lacks_it(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)
    catalog = tmp_path / "aa_resources.json"
    catalog.write_text(json.dumps({"characters": [{
        "identifier": "observed-hifumi", "name": "Hifumi",
        "spine": "UIs/03_Scenario/02_Character/CharacterSpine_Hifumi",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Hifumi",
    }]}), encoding="utf-8")
    monkeypatch.setattr(webui, "INDEX", str(catalog))
    monkeypatch.setattr(
        webui, "CHARACTER_CATALOG_METADATA", {"stamp": None, "items": {}},
        raising=False,
    )
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    assetdb.import_index(con, {"characters": [{
        "identifier": "observed-hifumi", "name": "Hifumi", "avatar": "", "spine": "",
        "faces": [],
    }]})
    con.close()

    row = webui.list_characters("Hifumi")[0]

    assert row["avatar"] == "/thumb/av/Student_Portrait_Hifumi"
    assert store.root.as_posix() not in repr(row)
    assert store.root.as_posix() not in repr(row)


def test_character_search_returns_default_catalog_identity_for_simplified_alias(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)
    catalog = tmp_path / "aa_resources.json"
    catalog.write_text(json.dumps({"characters": [{
        "identifier": "\uc544\ub9ac\uc2a4N", "name": "\u611b\u9e97\u7d72",
        "spine": "UIs/03_Scenario/02_Character/CharacterSpine_aris_noweapon",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Aris",
    }]}), encoding="utf-8")
    monkeypatch.setattr(webui, "INDEX", str(catalog))
    monkeypatch.setattr(
        webui, "CHARACTER_CATALOG_METADATA", {"stamp": None, "items": {}},
        raising=False,
    )
    monkeypatch.setitem(webui.CFG, "overrides", str(tmp_path / "empty"))
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(webui.DB)
    assetdb.import_index(con, {"characters": [{
        "identifier": "\uc544\ub9ac\uc2a4N", "name": "\u611b\u9e97\u7d72", "avatar": "", "spine": "",
        "faces": [],
    }, {
        "identifier": "\u7231\u4e3d\u4e1d\uff08\u9632\u5bd2\u670d-\u51ac\u88c5\uff09", "name": "\u7231\u4e3d\u4e1d", "avatar": "", "spine": "characters/winter", "source": "overrides",
        "faces": [],
    }]})
    con.execute(
        "UPDATE character SET source='overrides' WHERE ident=?",
        ("\u7231\u4e3d\u4e1d\uff08\u9632\u5bd2\u670d-\u51ac\u88c5\uff09",),
    )
    con.execute(
        "UPDATE character SET source='observed' WHERE ident=?",
        ("\uc544\ub9ac\uc2a4N",),
    )
    assetdb.seed_alias(con)
    con.close()

    rows = webui.list_characters("\u7231\u4e3d\u4e1d")

    assert rows[0]["ident"] == "\uc544\ub9ac\uc2a4N"
    assert rows[1]["ident"] == "\u7231\u4e3d\u4e1d\uff08\u9632\u5bd2\u670d-\u51ac\u88c5\uff09"


def test_avatar_thumb_keeps_transparent_background_as_png(tmp_path, monkeypatch):
    source = tmp_path / "portrait.png"
    image = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    image.paste((20, 80, 180, 255), (6, 2, 18, 15))
    image.save(source)
    monkeypatch.setattr(webui, "THUMBS", str(tmp_path / "thumbs"))

    data, content_type = webui.avatar_thumb(source, 96, "transparent")

    assert content_type == "image/png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert Image.open(io.BytesIO(data)).getchannel("A").getextrema()[0] == 0


def test_avatar_thumb_preserves_full_transparent_canvas_without_crop(tmp_path, monkeypatch):
    source = tmp_path / "wide-portrait.png"
    image = Image.new("RGBA", (240, 80), (0, 0, 0, 0))
    image.paste((20, 80, 180, 255), (100, 20, 140, 60))
    image.save(source)
    monkeypatch.setattr(webui, "THUMBS", str(tmp_path / "thumbs"))

    data, content_type = webui.avatar_thumb(source, 96, "wide")

    out = Image.open(io.BytesIO(data))
    assert content_type == "image/png"
    assert out.size == (96, 96)
    bbox = out.getchannel("A").getbbox()
    assert bbox is not None
    assert bbox[0] > 30 and bbox[2] < 66
    assert bbox[1] > 30 and bbox[3] < 66


@contextlib.contextmanager
def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _json_request(base, path, *, method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        base + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _wait_for_index(base):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status, payload = _json_request(base, "/api/resources/index")
        if payload["preview_index"]["status"] != "building":
            return status, payload
        time.sleep(0.01)
    raise AssertionError("index job did not finish")


def test_index_job_rejects_duplicates_and_reports_progress(
    tmp_path,
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()

    class BlockingStore:
        root = tmp_path / "previews"

        def build(self, _catalog, _cache, *, progress=None):
            progress(PreviewIndexState(
                "building", 1, 0, 0, "test", current=1, total=2
            ))
            started.set()
            assert release.wait(2)
            return PreviewIndexState(
                "ready", 2, 1, 0, "test", current=2, total=2
            )

    monkeypatch.setattr(webui, "OFFICIAL_PREVIEW_INDEX", BlockingStore())
    monkeypatch.setattr(webui, "_current_aa_discovery", lambda: type("D", (), {
        "catalog": tmp_path / "catalog.json",
        "resource_cache": tmp_path / "cache",
    })())
    monkeypatch.setattr(webui, "RESOURCE_INDEX_JOB", webui._empty_resource_index_job())

    with _server() as base:
        first_status, first = _json_request(
            base, "/api/resources/index", method="POST", payload={}
        )
        assert first_status == 202
        assert started.wait(1)
        second_status, second = _json_request(
            base, "/api/resources/index", method="POST", payload={}
        )
        assert second_status == 409
        assert second["code"] == "index_already_running"
        _, running = _json_request(base, "/api/resources/index")
        assert running["preview_index"]["current"] == 1
        assert running["preview_index"]["total"] == 2
        release.set()
        done_status, done = _wait_for_index(base)

    assert done_status == 200
    assert done["preview_index"]["status"] == "ready"
    assert done["preview_index"]["avatars"] == 1


def test_failed_index_job_reports_action_and_can_be_retried(
    tmp_path,
    monkeypatch,
):
    class RetryStore:
        root = tmp_path / "previews"

        def __init__(self):
            self.attempts = 0

        def build(self, _catalog, _cache, *, progress=None):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("broken bundle")
            return PreviewIndexState(
                "ready", 2, 1, 0, "test", current=3, total=3
            )

    store = RetryStore()
    monkeypatch.setattr(webui, "OFFICIAL_PREVIEW_INDEX", store)
    monkeypatch.setattr(webui, "_current_aa_discovery", lambda: type("D", (), {
        "catalog": tmp_path / "catalog.json",
        "resource_cache": tmp_path / "cache",
    })())
    monkeypatch.setattr(webui, "RESOURCE_INDEX_JOB", webui._empty_resource_index_job())

    with _server() as base:
        first_status, _ = _json_request(
            base, "/api/resources/index", method="POST", payload={}
        )
        failed_status, failed = _wait_for_index(base)
        retry_status, _ = _json_request(
            base, "/api/resources/index", method="POST", payload={}
        )
        ready_status, ready = _wait_for_index(base)

    assert first_status == retry_status == 202
    assert failed_status == ready_status == 200
    assert failed["preview_index"]["status"] == "failed"
    assert failed["preview_index"]["action"] == "请检查 AA 资源包后重试索引"
    assert "broken bundle" not in json.dumps(failed, ensure_ascii=False)
    assert ready["preview_index"]["status"] == "ready"
    assert store.attempts == 2


def test_preview_endpoint_streams_known_key_and_hides_local_paths(
    tmp_path,
    monkeypatch,
):
    store = _configure_preview_store(tmp_path, monkeypatch)

    with _server() as base:
        with urlopen(
            base + "/api/resources/preview?" + urlencode({
                "kind": "background", "key": "BG_Classroom",
            })
        ) as response:
            body = response.read()
            assert response.headers["Content-Type"] == "image/webp"
        unknown_status, unknown = _json_request(
            base,
            "/api/resources/preview?" + urlencode({
                "kind": "background", "key": "missing",
            }),
        )
        traversal_status, traversal = _json_request(
            base,
            "/api/resources/preview?" + urlencode({
                "kind": "background", "key": "../secret",
            }),
        )

    assert body == (store.root / "official.webp").read_bytes()
    assert unknown_status == traversal_status == 404
    encoded = json.dumps([unknown, traversal], ensure_ascii=False)
    assert str(tmp_path) not in encoded
