from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import aapaths
import android_web_server
import webui
from draft_store import DraftStore


def _request(origin, path, payload=None, method="POST"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        origin + path,
        data=body,
        method=method,
        headers={
            "X-HaloCue-Session": "story-session",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def _stage(root: Path, token: str, name: str, content: bytes) -> None:
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / f"{token}.bin").write_bytes(content)
    (incoming / f"{token}.json").write_text(
        json.dumps({"name": name, "size": len(content)}), encoding="utf-8"
    )


def test_android_runtime_routes_story_and_draft_state_to_private_workspace(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HALOCUE_PLATFORM", "android")
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    monkeypatch.setenv("HALOCUE_WORKSPACE_DIR", str(tmp_path / "workspace"))

    android_web_server.configure_android_runtime(str(tmp_path))

    workspace = (tmp_path / "workspace").resolve()
    paths = aapaths.detect()
    expected = {
        "data": workspace / "aa-data",
        "projects": workspace / "aa-data" / "projects",
        "saves": workspace / "aa-data" / "saves",
        "overrides": workspace / "aa-data" / "overrides",
        "settings": workspace / "aa-data" / "settings",
        "cache": workspace / "cache",
    }
    for name, target in expected.items():
        assert Path(paths[name]).resolve() == target
        assert target.is_dir()

    assert DraftStore().base_dir.resolve() == workspace / "drafts"
    index = webui._story_workspace_index_path(Path(paths["data"]))
    assert index.parent.resolve() == workspace / "story-workspaces"
    assert aapaths.app_storage_path("exports").resolve() == workspace / "exports"


def test_android_story_draft_and_card_edit_survive_server_restart(tmp_path):
    android_web_server.stop()
    incoming_token = "9" * 32
    _stage(tmp_path, incoming_token, "chapter.txt", b"Narrator: Hello\n")

    server = android_web_server.start(str(tmp_path), "story-session")
    origin = server["url"].split("?", 1)[0].rstrip("/")
    try:
        selected = _request(
            origin, "/api/story-files/select", {"incoming_token": incoming_token}
        )
        opened = _request(
            origin,
            "/api/stories/open",
            {"file_token": selected["file_token"], "project": "AndroidStory"},
        )
        imported = _request(
            origin,
            "/api/drafts/import",
            {
                "file_token": selected["file_token"],
                "story_token": opened["story_token"],
            },
        )
        detail = _request(
            origin, "/api/draft?token=" + imported["draft_token"], method="GET"
        )
        line = next(card for card in detail["cards"] if card["kind"] == "line")
        updated = _request(
            origin,
            "/api/cards/update",
            {
                "token": imported["draft_token"],
                "card_id": line["card_id"],
                "patch": {"text": "Edited on Android"},
                "expected_draft_version": detail["draft_version"],
            },
        )
        assert updated["draft_version"] == detail["draft_version"] + 1
    finally:
        android_web_server.stop()

    restarted = android_web_server.start(str(tmp_path), "story-session")
    restarted_origin = restarted["url"].split("?", 1)[0].rstrip("/")
    try:
        restored = _request(
            restarted_origin,
            "/api/draft?token=" + imported["draft_token"],
            method="GET",
        )
        recent = _request(restarted_origin, "/api/stories/recent", method="GET")
    finally:
        android_web_server.stop()

    assert any(
        card["current"].get("text") == "Edited on Android"
        for card in restored["cards"]
    )
    assert recent[0]["story_token"] == opened["story_token"]
    assert recent[0]["latest_draft_token"] == imported["draft_token"]
    assert str(tmp_path) not in json.dumps({"restored": restored, "recent": recent})
    assert (
        tmp_path / "workspace" / "drafts" / imported["draft_token"] / "session.json"
    ).is_file()


def test_android_runtime_copies_legacy_database_and_cache_into_workspace(tmp_path):
    legacy_profile = tmp_path / "databases" / "llm_profiles.json"
    legacy_profile.parent.mkdir(parents=True)
    legacy_profile.write_text('{"profiles": []}', encoding="utf-8")
    legacy_preview = tmp_path / "cache" / "official-previews" / "manifest.json"
    legacy_preview.parent.mkdir(parents=True)
    legacy_preview.write_text('{"status": "ready"}', encoding="utf-8")

    android_web_server.configure_android_runtime(str(tmp_path))

    assert (
        tmp_path / "workspace" / "databases" / "llm_profiles.json"
    ).read_text(encoding="utf-8") == '{"profiles": []}'
    assert (
        tmp_path / "workspace" / "cache" / "official-previews" / "manifest.json"
    ).read_text(encoding="utf-8") == '{"status": "ready"}'
    assert legacy_profile.is_file()
    assert legacy_preview.is_file()


def test_pc_story_index_keeps_webui_here_as_its_storage_root(tmp_path, monkeypatch):
    monkeypatch.delenv("HALOCUE_PLATFORM", raising=False)
    monkeypatch.delenv("HALOCUE_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(webui, "HERE", str(tmp_path / "pc-tool"))

    index = webui._story_workspace_index_path(tmp_path / "aa-data")

    assert index.parent == tmp_path / "pc-tool" / "out" / "story-workspaces"
