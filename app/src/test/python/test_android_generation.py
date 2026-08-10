from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest

import android_web_server
import android_exports
import annotate
import script2aap
import webui
from build_bundle import BuildBundleManager
from draft_store import DraftStore


class _FakeAndroidExportBackend:
    def __init__(self):
        self.calls = []

    def publishAap(self, source, project):
        self.calls.append((source, project))
        return {
            "shareId": "share-http-compile",
            "displayName": f"{project}.aap",
            "relativePath": "Download/HaloCue/",
            "size": Path(source).stat().st_size,
        }


@pytest.fixture
def android_export_backend():
    backend = _FakeAndroidExportBackend()
    android_exports.set_backend_for_tests(backend)
    try:
        yield backend
    finally:
        android_exports.set_backend_for_tests(None)
        android_web_server.stop()


def _request(origin: str, path: str, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        origin + path,
        data=body,
        headers={
            "X-HaloCue-Session": "generation-session",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_android_draft_build_writes_real_aap_inside_private_bundle(
    tmp_path, monkeypatch
):
    android_web_server.stop()
    android_web_server.configure_android_runtime(str(tmp_path))
    monkeypatch.setattr(script2aap, "HERE", str(tmp_path / "packaged-python"))
    monkeypatch.setattr(
        script2aap,
        "resolve_project_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Android compilation must not resolve an AA install target")
        ),
    )

    token = "draft-android-generation"
    store = DraftStore()
    created = store.create_draft(
        token=token,
        text="桃井: 安卓完整生成\n",
        project="AndroidFullGeneration",
    )
    manager = BuildBundleManager(store=store)
    build_id = manager.create_compile_snapshot(
        token=token,
        expected_draft_version=created["session"]["draft_version"],
    )
    result = manager.execute_build_worker(token=token, build_id=build_id)

    aap_file = Path(result["aap_file"]).resolve()
    workspace = (tmp_path / "workspace").resolve()
    payload = json.loads(aap_file.read_text(encoding="utf-8"))
    scripts = [
        item
        for node in payload["nodes"]["$values"]
        if node["$type"].startswith("ScriptNodeData")
        for item in node["Scripts"]["$values"]
    ]

    assert result["ok"] is True
    assert result["project"] == "AndroidFullGeneration"
    assert result["warnings"] == []
    assert aap_file.is_file()
    assert aap_file.is_relative_to(workspace)
    assert not (tmp_path / "packaged-python" / "out").exists()
    assert payload["ProjectName"] == "AndroidFullGeneration"
    assert scripts[0]["text"] == "安卓完整生成"
    android_web_server.stop()


def test_android_annotation_uses_mock_provider_and_persists_editable_draft(
    tmp_path, monkeypatch
):
    android_web_server.stop()
    android_web_server.configure_android_runtime(str(tmp_path))
    source = tmp_path / "workspace" / "imports" / "story.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("桃井: 原始台词\n", encoding="utf-8")
    provider = object()
    calls = []

    def fake_annotate(options, *, provider_instance):
        calls.append((dict(options), provider_instance))
        Path(options["out"]).write_text("桃井: AI 标注结果\n", encoding="utf-8")
        return {"proposals": [], "agent": {"metrics": {"chunks": 1}}}

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: provider)
    monkeypatch.setattr(annotate, "annotate_script", fake_annotate)
    result = webui.annotate_draft_worker(
        {
            "script": str(source),
            "project": "AndroidAnnotation",
            "mapping": {"桃井": {"kind": "narrator"}},
            "annotate": True,
        }
    )

    draft = DraftStore().load_draft(result["draft_token"])
    output_path = Path(calls[0][0]["out"]).resolve()
    assert calls[0][1] is provider
    assert output_path.is_relative_to((tmp_path / "workspace").resolve())
    assert draft["edited_text"] == "桃井: AI 标注结果\n"
    assert draft["session"]["project"] == "AndroidAnnotation"
    assert result["agent_metrics"] == {"chunks": 1}
    android_web_server.stop()


def test_android_compile_api_returns_completed_private_aap(
    tmp_path, android_export_backend
):
    android_web_server.stop()
    server = android_web_server.start(str(tmp_path), "generation-session")
    origin = server["url"].split("?", 1)[0].rstrip("/")
    token = "draft-android-api-generation"
    store = DraftStore()
    created = store.create_draft(
        token=token,
        text="桃井: API 生成成功\n",
        project="AndroidApiGeneration",
        cast={"cast": {"桃井": {"narrator": True}}},
    )
    approved = store.batch_approve_reviews(
        token=token,
        card_ids=None,
        expected_draft_version=created["session"]["draft_version"],
    )
    store.assert_review_ready(token)

    queued = _request(
        origin,
        "/api/compile",
        {
            "token": token,
            "expected_draft_version": approved["session"]["draft_version"],
        },
    )
    deadline = time.monotonic() + 5
    job = None
    while time.monotonic() < deadline:
        job = _request(origin, "/api/jobs/" + queued["job_id"])
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert job is not None
    assert job["state"] == "succeeded", job
    assert job["result"]["ok"] is True
    assert job["result"]["export"]["shareId"] == "share-http-compile"
    assert job["result"]["export"]["displayName"] == "AndroidApiGeneration.aap"
    assert job["result"]["export"]["relativePath"] == "Download/HaloCue/"
    assert job["result"]["export"]["size"] > 0
    assert "aap_file" not in job["result"]
    assert "bundle_dir" not in job["result"]
    assert android_export_backend.calls and Path(
        android_export_backend.calls[0][0]
    ).resolve().is_relative_to(
        (tmp_path / "workspace").resolve()
    )
