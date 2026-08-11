from __future__ import annotations

import json

import android_exports


class FakePlatformServices:
    def __init__(self):
        self.calls = []

    def publishAap(self, source, project):
        self.calls.append((source, project))
        return {
            "shareId": "share-123",
            "displayName": "Demo.aap",
            "relativePath": "Download/HaloCue/",
            "size": 42,
            "uri": "content://must-not-leak",
            "sourcePath": source,
        }


def test_publish_aap_returns_only_public_metadata(tmp_path):
    source = tmp_path / "workspace" / "builds" / "Demo.aap"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")
    backend = FakePlatformServices()
    android_exports.set_backend_for_tests(backend)
    try:
        result = android_exports.publish_aap(str(source), "Demo")
    finally:
        android_exports.set_backend_for_tests(None)

    assert backend.calls == [(str(source), "Demo")]
    assert result == {
        "shareId": "share-123",
        "displayName": "Demo.aap",
        "relativePath": "Download/HaloCue/",
        "size": 42,
    }
    assert "content://" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_preview_export_backend_copies_aap_into_isolated_workspace(tmp_path):
    source = tmp_path / "private" / "Demo.aap"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"compiled-aap")

    result = android_exports.PreviewExportBackend(tmp_path).publishAap(
        str(source), "Demo:Chapter"
    )
    exported = tmp_path / "exports" / "HaloCue" / "Demo_Chapter.aap"

    assert exported.read_bytes() == b"compiled-aap"
    assert result["displayName"] == "Demo_Chapter.aap"
    assert result["relativePath"] == "Preview exports/HaloCue/"
    assert result["size"] == len(b"compiled-aap")
    assert str(tmp_path) not in json.dumps(result)
