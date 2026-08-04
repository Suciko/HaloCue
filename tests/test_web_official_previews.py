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

import assetdb
import webui
from official_preview_index import OfficialPreviewIndex, PreviewIndexState


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
