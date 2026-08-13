from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import android_web_server
from android_incoming_files import IncomingFileError, claim_incoming, claim_incoming_tree


def _stage(root, token: str, name: str, content: bytes) -> None:
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / f"{token}.bin").write_bytes(content)
    (incoming / f"{token}.json").write_text(
        json.dumps({"name": name, "size": len(content)}), encoding="utf-8"
    )


def _stage_tree(root, token: str, name: str, files: dict[str, bytes]) -> None:
    incoming = root / "incoming"
    tree = incoming / f"{token}.tree"
    tree.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (incoming / f"{token}.tree.json").write_text(
        json.dumps(
            {
                "name": name,
                "size": sum(len(content) for content in files.values()),
                "fileCount": len(files),
            }
        ),
        encoding="utf-8",
    )


def test_claim_moves_staged_story_once_into_private_workspace(tmp_path, monkeypatch):
    token = "a" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage(tmp_path, token, "story.md", b"# story")

    claimed = claim_incoming(token, [".txt", ".md"])

    assert claimed == tmp_path / "workspace" / "imports" / token / "story.md"
    assert claimed.read_bytes() == b"# story"
    assert not (tmp_path / "incoming" / f"{token}.json").exists()
    with pytest.raises(IncomingFileError, match="invalid_incoming_token"):
        claim_incoming(token, [".txt", ".md"])


def test_claim_tree_moves_complete_spine_directory_once(tmp_path, monkeypatch):
    token = "1" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage_tree(
        tmp_path,
        token,
        "Arona",
        {
            "Arona.skel": b"skeleton",
            "Arona.atlas": b"Arona.png\n",
            "textures/Arona.png": b"png",
        },
    )

    claimed = claim_incoming_tree(token)

    assert claimed == tmp_path / "workspace" / "imports" / token / "Arona"
    assert (claimed / "Arona.skel").read_bytes() == b"skeleton"
    assert (claimed / "textures" / "Arona.png").read_bytes() == b"png"
    with pytest.raises(IncomingFileError, match="invalid_incoming_token"):
        claim_incoming_tree(token)


def test_claim_tree_rejects_tampered_contents_without_moving(tmp_path, monkeypatch):
    token = "2" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage_tree(tmp_path, token, "Assets", {"bg.png": b"png"})
    (tmp_path / "incoming" / f"{token}.tree" / "extra.png").write_bytes(b"extra")

    with pytest.raises(IncomingFileError, match="incoming_tree_changed"):
        claim_incoming_tree(token)

    assert (tmp_path / "incoming" / f"{token}.tree" / "bg.png").is_file()


@pytest.mark.parametrize("token", ["", "../secret", "a" * 31, "g" * 32])
def test_claim_rejects_invalid_or_traversing_tokens(tmp_path, monkeypatch, token):
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))

    with pytest.raises(IncomingFileError, match="invalid_incoming_token"):
        claim_incoming(token, [".txt", ".md"])


def test_claim_rejects_unsupported_suffix_without_moving_payload(tmp_path, monkeypatch):
    token = "b" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage(tmp_path, token, "story.exe", b"not a story")

    with pytest.raises(IncomingFileError, match="unsupported_incoming_type"):
        claim_incoming(token, [".txt", ".md"])

    assert (tmp_path / "incoming" / f"{token}.bin").read_bytes() == b"not a story"


def test_claim_rejects_tampered_metadata_size(tmp_path, monkeypatch):
    token = "c" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage(tmp_path, token, "story.txt", b"content")
    metadata = tmp_path / "incoming" / f"{token}.json"
    metadata.write_text(json.dumps({"name": "story.txt", "size": 999}), encoding="utf-8")

    with pytest.raises(IncomingFileError, match="incoming_file_changed"):
        claim_incoming(token, [".txt", ".md"])


def test_claim_rejects_symlinked_metadata(tmp_path, monkeypatch):
    token = "e" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage(tmp_path, token, "story.txt", b"content")
    metadata = tmp_path / "incoming" / f"{token}.json"
    external = tmp_path / "external.json"
    external.write_text(json.dumps({"name": "story.txt", "size": 7}), encoding="utf-8")
    metadata.unlink()
    try:
        metadata.symlink_to(external)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    with pytest.raises(IncomingFileError, match="invalid_incoming_token"):
        claim_incoming(token, [".txt", ".md"])


def test_concurrent_claim_maps_loser_to_used_token_error(tmp_path, monkeypatch):
    token = "f" * 32
    monkeypatch.setenv("HALOCUE_ANDROID_FILES_DIR", str(tmp_path))
    _stage(tmp_path, token, "story.txt", b"content")
    target_dir = tmp_path / "workspace" / "imports" / token
    barrier = threading.Barrier(2)
    original_exists = Path.exists

    def synchronized_exists(path):
        if path == target_dir:
            barrier.wait(timeout=2)
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", synchronized_exists)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda _index: _claim_outcome(token),
                range(2),
            )
        )

    assert sorted(outcomes) == ["claimed", "invalid_incoming_token"]


def _claim_outcome(token: str) -> str:
    try:
        claim_incoming(token, [".txt", ".md"])
        return "claimed"
    except IncomingFileError as exc:
        return exc.code


def test_android_story_select_endpoint_claims_native_token_once(tmp_path):
    android_web_server.stop()
    token = "d" * 32
    _stage(tmp_path, token, "picked.txt", b"picked story")
    server = android_web_server.start(str(tmp_path), "incoming-session")
    origin = server["url"].split("?", 1)[0].rstrip("/")

    def select():
        request = urllib.request.Request(
            origin + "/api/story-files/select",
            data=json.dumps({"incoming_token": token}).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-HaloCue-Session": "incoming-session",
            },
        )
        return json.load(urllib.request.urlopen(request))

    try:
        selected = select()
        assert selected["ok"] is True
        assert selected["name"] == "picked.txt"
        assert selected["size"] == len(b"picked story")
        assert selected["file_token"].startswith("ft-")
        with pytest.raises(urllib.error.HTTPError) as reused:
            select()
        assert reused.value.code == 404
        assert json.load(reused.value)["code"] == "invalid_incoming_token"
    finally:
        android_web_server.stop()
