from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

import android_web_server
from asset_import import AssetImportRequestError, discover_assets, resolve_character_source
from picker_token import resolve_file_token


@pytest.fixture(autouse=True)
def stopped_server():
    android_web_server.stop()
    yield
    android_web_server.stop()


def _stage_file(root, token: str, name: str, content: bytes) -> None:
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
                "size": sum(map(len, files.values())),
                "fileCount": len(files),
            }
        ),
        encoding="utf-8",
    )


def _post(server, path: str, payload: dict):
    origin = server["url"].split("?", 1)[0].rstrip("/")
    request = urllib.request.Request(
        origin + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-HaloCue-Session": "test-session",
        },
    )
    return urllib.request.urlopen(request)


def test_native_file_selection_returns_opaque_one_use_file_token(tmp_path):
    token = "a" * 32
    server = android_web_server.start(str(tmp_path), "test-session")
    _stage_file(tmp_path, token, "scene.png", b"png")

    payload = json.load(
        _post(
            server,
            "/api/assets/select-native",
            {"incoming_token": token, "kind": "background", "selection_type": "file"},
        )
    )

    assert payload["ok"] is True
    assert payload["name"] == "scene.png"
    assert "file_token" in payload
    assert str(tmp_path) not in json.dumps(payload)
    assert resolve_file_token(payload["file_token"]).endswith("scene.png")
    with pytest.raises(urllib.error.HTTPError) as reused:
        _post(
            server,
            "/api/assets/select-native",
            {"incoming_token": token, "kind": "background", "selection_type": "file"},
        )
    assert reused.value.code == 404
    assert json.load(reused.value)["code"] == "invalid_incoming_token"


def test_native_character_tree_resolves_the_unique_spine_bundle(tmp_path):
    token = "b" * 32
    server = android_web_server.start(str(tmp_path), "test-session")
    _stage_tree(
        tmp_path,
        token,
        "Characters",
        {
            "Arona/Arona.skel": b"skel",
            "Arona/Arona.atlas": b"Arona.png\n",
            "Arona/Arona.png": b"png",
        },
    )

    payload = json.load(
        _post(
            server,
            "/api/assets/select-native",
            {"incoming_token": token, "kind": "character", "selection_type": "tree"},
        )
    )

    source = resolve_file_token(payload["file_token"])
    assert payload["name"] == "Characters"
    assert payload["file_count"] == 3
    assert source.endswith("Arona")


def test_character_source_rejects_missing_and_ambiguous_bundles(tmp_path):
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(AssetImportRequestError) as absent:
        resolve_character_source(missing)
    assert absent.value.code == "character_bundle_missing"

    ambiguous = tmp_path / "ambiguous"
    for name in ("one", "two"):
        folder = ambiguous / name
        folder.mkdir(parents=True)
        (folder / f"{name}.skel").write_bytes(b"skel")
        (folder / f"{name}.atlas").write_text("texture.png\n", encoding="utf-8")
    with pytest.raises(AssetImportRequestError) as multiple:
        resolve_character_source(ambiguous)
    assert multiple.value.code == "character_bundle_ambiguous"


def test_batch_tree_token_preserves_all_discoverable_assets(tmp_path):
    token = "c" * 32
    server = android_web_server.start(str(tmp_path), "test-session")
    _stage_tree(
        tmp_path,
        token,
        "Batch",
        {
            "backgrounds/room.png": b"png",
            "sounds/door.ogg": b"ogg",
            "characters/Aru/Aru.skel": b"skel",
            "characters/Aru/Aru.atlas": b"Aru.png\n",
            "characters/Aru/Aru.png": b"png",
        },
    )

    payload = json.load(
        _post(
            server,
            "/api/assets/select-native",
            {"incoming_token": token, "kind": "batch", "selection_type": "tree"},
        )
    )
    rows = discover_assets(resolve_file_token(payload["file_token"]))

    assert {row["kind"] for row in rows} == {"background", "sound", "character"}
