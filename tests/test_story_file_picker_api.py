import contextlib
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pytest

import webui
from picker_token import resolve_file_token
from story_file_picker import StoryFilePicker, StoryFilePickerError, windows_host_roots


@contextlib.contextmanager
def _server(picker, monkeypatch):
    monkeypatch.setattr(webui, "STORY_FILE_PICKER", picker)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _request(base, path, *, method="GET", data=None, headers=None):
    request = Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_device_upload_returns_only_an_opaque_token_and_owned_copy(tmp_path, monkeypatch):
    picker = StoryFilePicker(roots=[tmp_path], upload_dir=tmp_path / "uploads")
    with _server(picker, monkeypatch) as base:
        status, payload = _request(
            base,
            "/api/story-files/upload",
            method="POST",
            data="凯伊：早上好".encode(),
            headers={
                "Content-Type": "application/octet-stream",
                "X-AA-Filename": quote("第一章.md"),
            },
        )

    assert status == 200
    assert payload == {
        "ok": True,
        "file_token": payload["file_token"],
        "name": "第一章.md",
        "size": 18,
    }
    assert payload["file_token"].startswith("ft-")
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)
    resolved = resolve_file_token(payload["file_token"])
    assert resolved is not None
    assert (tmp_path / "uploads") in __import__("pathlib").Path(resolved).parents
    assert __import__("pathlib").Path(resolved).read_text(encoding="utf-8") == "凯伊：早上好"


@pytest.mark.parametrize(
    "name,content,code",
    [
        ("story.pdf", b"text", "unsupported_story_type"),
        ("story.txt", b"", "empty_story_file"),
        ("story.md", b"\x81", "unreadable_story_text"),
    ],
)
def test_device_upload_rejects_invalid_story_files(tmp_path, name, content, code):
    picker = StoryFilePicker(roots=[tmp_path], upload_dir=tmp_path / "uploads")

    with pytest.raises(StoryFilePickerError) as error:
        picker.upload(name, content)

    assert error.value.code == code


def test_device_upload_rejects_content_over_ten_mebibytes(tmp_path):
    picker = StoryFilePicker(roots=[tmp_path], upload_dir=tmp_path / "uploads")

    with pytest.raises(StoryFilePickerError) as error:
        picker.upload("large.txt", b"a" * (10 * 1024 * 1024 + 1))

    assert error.value.code == "story_file_too_large"


def test_host_browser_filters_metadata_and_selects_only_the_issued_file(tmp_path):
    folder = tmp_path / "chapters"
    folder.mkdir()
    story = folder / "chapter-02.md"
    story.write_text("story", encoding="utf-8")
    (folder / "ignore.png").write_bytes(b"png")
    (folder / "chapter-01.txt").write_text("one", encoding="utf-8")
    picker = StoryFilePicker(roots=[tmp_path], upload_dir=tmp_path / "uploads")

    root = picker.list_directory()
    directory = next(row for row in root["entries"] if row["name"] == "chapters")
    listed = picker.list_directory(directory["entry_token"], sort="size", direction="desc")
    selected_row = next(row for row in listed["entries"] if row["name"] == story.name)
    selected = picker.select(selected_row["entry_token"])

    assert [row["name"] for row in listed["entries"]] == ["chapter-02.md", "chapter-01.txt"]
    assert selected == {
        "file_token": selected["file_token"],
        "name": "chapter-02.md",
        "size": 5,
    }
    assert resolve_file_token(selected["file_token"]) == str(story.resolve())
    encoded = json.dumps(listed, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "ignore.png" not in encoded
    assert all({"entry_token", "name", "kind", "size", "modified", "type"} <= set(row) for row in listed["entries"])


def test_host_entry_token_cannot_escape_roots_or_change_targets(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    story = allowed / "story.txt"
    story.write_text("story", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    picker = StoryFilePicker(roots=[allowed], upload_dir=tmp_path / "uploads")
    listed = picker.list_directory()
    token = next(row["entry_token"] for row in listed["entries"] if row["name"] == "story.txt")
    story.rename(allowed / "renamed.txt")

    with pytest.raises(StoryFilePickerError) as stale:
        picker.select(token)
    with pytest.raises(StoryFilePickerError) as escaped:
        picker._issue_entry(outside)

    assert stale.value.code == "host_entry_changed"
    assert escaped.value.code == "host_entry_outside_roots"


def test_settings_picker_can_select_directories_and_non_story_files(tmp_path):
    from story_file_picker import StoryFilePicker

    aa_data = tmp_path / "aa-data"
    aa_data.mkdir()
    (aa_data / "projects").mkdir()
    spine = tmp_path / "Spine.com"
    spine.write_bytes(b"binary cli")
    picker = StoryFilePicker(
        roots=[tmp_path], upload_dir=tmp_path / "uploads", allowed_suffixes=None
    )

    listing = picker.list_directory()
    aa_row = next(row for row in listing["entries"] if row["name"] == "aa-data")
    spine_row = next(row for row in listing["entries"] if row["name"] == "Spine.com")
    assert picker.resolve_entry_path(aa_row["entry_token"], expected_kind="directory") == aa_data.resolve()
    assert picker.resolve_entry_path(spine_row["entry_token"], expected_kind="file") == spine.resolve()
    assert "path" not in aa_row and "path" not in spine_row


def test_host_http_routes_use_entry_tokens_instead_of_paths(tmp_path, monkeypatch):
    (tmp_path / "story.txt").write_text("story", encoding="utf-8")
    picker = StoryFilePicker(roots=[tmp_path], upload_dir=tmp_path / "uploads")

    with _server(picker, monkeypatch) as base:
        status, listed = _request(base, "/api/story-files/host?" + urlencode({"sort": "name"}))
        entry = listed["entries"][0]
        selected_status, selected = _request(
            base,
            "/api/story-files/select",
            method="POST",
            data=json.dumps({"entry_token": entry["entry_token"]}).encode(),
            headers={"Content-Type": "application/json"},
        )

    assert status == selected_status == 200
    assert entry["name"] == selected["name"] == "story.txt"
    assert "path" not in entry and "path" not in selected


def test_settings_host_route_validates_an_entry_without_exposing_path(tmp_path, monkeypatch):
    (tmp_path / "Spine.com").write_bytes(b"binary cli")
    picker = StoryFilePicker(
        roots=[tmp_path], upload_dir=tmp_path / "uploads", allowed_suffixes=None
    )
    monkeypatch.setattr(webui, "SETTINGS_FILE_PICKER", picker)

    with _server(picker, monkeypatch) as base:
        status, listed = _request(base, "/api/settings/host")
        entry = next(row for row in listed["entries"] if row["name"] == "Spine.com")
        selected_status, selected = _request(
            base,
            "/api/settings/entry",
            method="POST",
            data=json.dumps({"entry_token": entry["entry_token"]}).encode(),
            headers={"Content-Type": "application/json"},
        )

    assert status == selected_status == 200
    assert selected == {
        "ok": True,
        "entry_token": entry["entry_token"],
        "name": "Spine.com",
        "kind": "file",
    }
    assert str(tmp_path) not in json.dumps(selected)


def test_windows_host_roots_include_useful_existing_locations_without_duplicates(tmp_path):
    home = tmp_path / "home"
    desktop = home / "Desktop"
    documents = home / "Documents"
    downloads = home / "Downloads"
    workspace = tmp_path / "workspace"
    for path in (workspace, desktop, documents, downloads):
        path.mkdir(parents=True, exist_ok=True)

    roots = windows_host_roots(workspace, home=home, drives=[])

    assert roots == [
        (tmp_path / "workspace").resolve(),
        desktop.resolve(),
        documents.resolve(),
        downloads.resolve(),
    ]
