# -*- coding: utf-8 -*-
import sys
import contextlib
import json
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from story_workspace import StoryWorkspaceRegistry, public_story_context


def test_open_story_uses_source_stem_and_returns_opaque_token(tmp_path):
    """Changing token generation to expose a canonical source path is a bug."""
    registry = StoryWorkspaceRegistry(
        tmp_path / "story-index.json", aa_data=tmp_path / "data"
    )

    context = registry.open_path(tmp_path / "第一章.txt")

    assert context.project == "第一章"
    assert context.story_token.startswith("story-")
    assert str(tmp_path) not in context.story_token
    assert context.bgm_default == {
        "enabled": False,
        "arrangement": "manual",
        "bgmId": 999,
    }


def test_reopen_moves_story_to_front_without_duplicate(tmp_path):
    """A reopened project must replace its old recent entry rather than duplicate it."""
    registry = StoryWorkspaceRegistry(
        tmp_path / "story-index.json", aa_data=tmp_path / "data"
    )

    first = registry.open_path(tmp_path / "第一章.txt")
    registry.open_path(tmp_path / "第二章.txt")
    again = registry.open_path(tmp_path / "第一章.txt", project=first.project)

    assert [row.project for row in registry.list_recent()] == ["第一章", "第二章"]
    assert again.story_token == first.story_token


def test_recent_index_persists_metadata_but_not_server_paths_in_summary(tmp_path):
    """Restarted registries must restore resume metadata without returning source paths."""
    index_path = tmp_path / "out" / "story-index.json"
    first_registry = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    context = first_registry.open_path(tmp_path / "第一章.txt")
    first_registry.set_latest_draft_token(context.story_token, "draft-123")

    second_registry = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    summary = second_registry.list_recent()[0]

    assert summary.story_token == context.story_token
    assert summary.project == "第一章"
    assert summary.source_name == "第一章.txt"
    assert summary.latest_draft_token == "draft-123"
    assert str(tmp_path) not in repr(summary)
    assert second_registry.resolve_story_token(summary.story_token).source_path == (
        tmp_path / "第一章.txt"
    ).resolve()


def test_preflight_snapshot_persists_safely_and_reports_source_freshness(tmp_path):
    index_path = tmp_path / "out" / "story-index.json"
    aa_data = tmp_path / "data"
    source = tmp_path / "story.txt"
    source.write_text("凯伊：出发。\n", encoding="utf-8")
    registry = StoryWorkspaceRegistry(index_path, aa_data=aa_data)
    context = registry.open_path(source, project="SnapshotStory")

    registry.set_preflight_snapshot(context.story_token, {
        "ai_status": "completed",
        "analysis": {"lines": 1, "speakers": [{"who": "凯伊"}]},
        "characters": [{"speaker": "凯伊", "kind": "portrait", "id": "hero"}],
        "usage_chain": [],
        "issues": [],
        "ai_diagnostics": {"message": "private provider detail"},
    })
    registry.set_preflight_approved(context.story_token, True)

    reloaded = StoryWorkspaceRegistry(index_path, aa_data=aa_data)
    summary = reloaded.list_recent()[0]
    payload = public_story_context(reloaded.resolve_story_token(summary.story_token))
    snapshot = payload["preflight_snapshot"]

    assert snapshot["state"] == "fresh"
    assert snapshot["approved"] is True
    assert snapshot["saved_at"]
    assert snapshot["result"]["analysis"]["lines"] == 1
    assert "ai_diagnostics" not in snapshot["result"]
    assert "fingerprint" not in snapshot
    assert str(tmp_path) not in json.dumps(snapshot, ensure_ascii=False)


def test_preflight_mapping_update_persists_exact_spine_identity(tmp_path):
    source = tmp_path / "story.txt"
    source.write_text("爱丽丝：出发。\n", encoding="utf-8")
    index_path = tmp_path / "out" / "story-index.json"
    registry = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    context = registry.open_path(source, project="MappingStory")
    registry.set_preflight_snapshot(context.story_token, {
        "ai_status": "completed", "characters": [{
            "speaker": "爱丽丝", "kind": "portrait", "id": "아리스N",
            "name": "爱丽丝", "spine": "CharacterSpine_aris_noweapon",
        }], "assets": [], "usage_chain": [], "issues": [],
    })

    registry.update_preflight_mapping(context.story_token, [{
        "speaker": "爱丽丝", "kind": "portrait", "id": "아리스",
        "name": "爱丽丝", "spine": "CharacterSpine_aris",
    }])

    restored = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    token = restored.list_recent()[0].story_token
    snapshot = public_story_context(restored.resolve_story_token(token))["preflight_snapshot"]
    assert snapshot["result"]["characters"][0]["id"] == "아리스"
    assert snapshot["result"]["characters"][0]["spine"] == "CharacterSpine_aris"

def test_preflight_background_binding_updates_exact_scene_and_persists(tmp_path):
    index_path = tmp_path / "out" / "story-index.json"
    source = tmp_path / "story.txt"
    source.write_text("旁白：雨夜的车站。\n", encoding="utf-8")
    registry = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    context = registry.open_path(source, project="BindingStory")
    registry.set_preflight_snapshot(context.story_token, {
        "ai_status": "completed", "usage_chain_status": "completed",
        "analysis": {"lines": 1, "speakers": [], "scenes": []},
        "characters": [], "assets": [], "issues": [],
        "usage_chain": [{
            "segment": "开场", "location": "车站", "needs": [{
                "kind": "background", "name": "雨夜车站", "location": "第1行",
                "status": "missing", "generation_prompt": "生成雨夜车站",
                "candidates": [
                    {"aa_key": "BG_Official", "confidence": 0.9, "reason": "宽泛匹配"},
                    {"aa_key": "BG_SubwayHall", "confidence": 0.6, "reason": "售票口匹配"},
                ],
            }],
        }, {
            "segment": "后续对话", "location": "车站站台", "needs": [{
                "kind": "background", "name": "车站站台", "location": "第2行",
                "status": "inherited", "candidates": [],
                "inherits_from": {
                    "segment": "开场", "location": "第1行", "requested_name": "雨夜车站",
                },
            }],
        }],
    })

    registry.bind_preflight_background(
        context.story_token,
        {"segment": "开场", "location": "第1行", "requested_name": "雨夜车站"},
        {"aa_key": "9001", "selected_label": "雨夜车站", "source": "custom",
         "preview_source": "story", "preview_available": True},
    )

    restored = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    restored_token = restored.list_recent()[0].story_token
    snapshot = public_story_context(
        restored.resolve_story_token(restored_token)
    )["preflight_snapshot"]
    need = snapshot["result"]["usage_chain"][0]["needs"][0]
    assert need == {
        "kind": "background", "name": "雨夜车站", "location": "第1行",
        "status": "registered", "aa_key": "9001", "selected_label": "雨夜车站",
        "source": "custom", "preview_source": "story", "preview_available": True,
        "candidates": [
            {"aa_key": "BG_Official", "confidence": 0.9, "reason": "宽泛匹配"},
            {"aa_key": "BG_SubwayHall", "confidence": 0.6, "reason": "售票口匹配"},
        ],
    }
    continued = snapshot["result"]["usage_chain"][1]["needs"][0]
    assert continued["status"] == "inherited"
    assert continued["aa_key"] == "9001"
    assert continued["selected_label"] == "雨夜车站"
    assert continued["source"] == "custom"
    assert snapshot["approved"] is False


def test_preflight_background_binding_rejects_stale_or_cross_story_selector(tmp_path):
    index_path = tmp_path / "story-index.json"
    registry = StoryWorkspaceRegistry(index_path, aa_data=tmp_path / "data")
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("第一章", encoding="utf-8")
    second_source.write_text("第二章", encoding="utf-8")
    first = registry.open_path(first_source, project="First")
    second = registry.open_path(second_source, project="Second")
    registry.set_preflight_snapshot(first.story_token, {
        "usage_chain": [{"segment": "第一章", "needs": [{
            "kind": "background", "name": "教室", "location": "第1行",
        }]}],
    })
    registry.set_preflight_snapshot(second.story_token, {
        "usage_chain": [{"segment": "第二章", "needs": [{
            "kind": "background", "name": "天台", "location": "第2行",
        }]}],
    })

    with pytest.raises(ValueError, match="scene"):
        registry.bind_preflight_background(
            first.story_token,
            {"segment": "第二章", "location": "第2行", "requested_name": "天台"},
            {"aa_key": "other", "selected_label": "天台", "source": "custom",
             "preview_source": "story", "preview_available": True},
        )
    first_source.write_text("第一章已修改", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        registry.bind_preflight_background(
            first.story_token,
            {"segment": "第一章", "location": "第1行", "requested_name": "教室"},
            {"aa_key": "9001", "selected_label": "教室", "source": "custom",
             "preview_source": "story", "preview_available": True},
        )


def test_public_story_context_exposes_safe_source_metadata_without_path(tmp_path):
    source = tmp_path / "章节" / "第一章.md"
    source.parent.mkdir()
    source.write_text("正文", encoding="utf-8")
    registry = StoryWorkspaceRegistry(
        tmp_path / "story-index.json", aa_data=tmp_path / "data"
    )

    payload = public_story_context(registry.open_path(source))

    assert payload["source_name"] == "第一章.md"
    assert payload["source_type"] == "Markdown"
    assert payload["source_size"] == len("正文".encode("utf-8"))
    assert payload["source_modified"]
    assert payload["source_display"].endswith("章节 / 第一章.md")
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)


def test_open_story_rejects_unsafe_project_name(tmp_path):
    """A client project path must never become an AA project directory."""
    registry = StoryWorkspaceRegistry(
        tmp_path / "story-index.json", aa_data=tmp_path / "data"
    )

    with pytest.raises(ValueError, match="project name"):
        registry.open_path(tmp_path / "第一章.txt", project="..\\outside")


@contextlib.contextmanager
def _story_server(tmp_path, monkeypatch):
    import webui
    from draft_store import DraftStore
    from webui import H

    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "data"))
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    monkeypatch.setattr(
        webui,
        "DraftStore",
        lambda **kw: DraftStore(base_dir=str(tmp_path / "drafts"), **kw),
    )
    monkeypatch.setattr(
        webui,
        "STORY_WORKSPACE",
        StoryWorkspaceRegistry(tmp_path / "out" / "story-index.json", tmp_path / "data"),
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


def _request(base, path, payload=None, method="POST"):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        base + path,
        data=raw,
        method=method,
        headers={"Content-Type": "application/json"} if raw else {},
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except Exception as exc:
        with exc as response:
            return response.status, json.loads(response.read())


def test_story_http_routes_use_file_tokens_and_reject_project_mismatch(tmp_path, monkeypatch):
    """Accepting a raw project during import could cross a story's asset scope."""
    import webui

    source = tmp_path / "第一章.txt"
    source.write_text("## 场景1\n凯伊: 你好\n", encoding="utf-8")
    token = webui.register_file_token(str(source))

    with _story_server(tmp_path, monkeypatch) as base:
        status, opened = _request(base, "/api/stories/open", {
            "file_token": token,
            "project": "第一章",
        })
        assert status == 200
        assert opened["project"] == "第一章"
        assert str(tmp_path) not in json.dumps(opened, ensure_ascii=False)

        status, current = _request(
            base,
            "/api/story/current?story_token=" + opened["story_token"],
            method="GET",
        )
        assert status == 200
        assert current["source_name"] == "第一章.txt"
        assert "source_path" not in current

        status, rejected = _request(base, "/api/drafts/import", {
            "file_token": token,
            "story_token": opened["story_token"],
            "project": "别的项目",
        })
        assert status == 409
        assert rejected["code"] == "project_mismatch"

        status, imported = _request(base, "/api/drafts/import", {
            "file_token": token,
            "story_token": opened["story_token"],
        })
        assert status == 200
        assert imported["project"] == "第一章"

        status, detail = _request(
            base, "/api/draft?token=" + imported["draft_token"], method="GET"
        )
        assert status == 200
        assert detail["project"] == "第一章"
        assert detail["story_token"] == opened["story_token"]
        assert detail["bgm_policy"]["bgmId"] == 999
        assert detail["cast"] == {"count": 0, "speakers": []}


def test_annotate_story_context_uses_file_token_and_updates_recent(tmp_path, monkeypatch):
    """An annotation job must retain its original story when the UI later switches."""
    import time
    import webui

    source = tmp_path / "第一章.txt"
    source.write_text("凯伊: 你好\n", encoding="utf-8")
    token = webui.register_file_token(str(source))
    seen = []

    def fake_worker(payload):
        seen.append(dict(payload))
        return {"draft_token": "draft-annotated", "project": payload["project"], "lines": 1, "proposals": 0}

    monkeypatch.setattr(webui, "annotate_draft_worker", fake_worker)
    with _story_server(tmp_path, monkeypatch) as base:
        _, opened = _request(base, "/api/stories/open", {"file_token": token})
        story_token = opened["story_token"]

        status, rejected = _request(base, "/api/annotate", {
            "file_token": token,
            "story_token": story_token,
            "project": "别的项目",
            "mapping": {},
        })
        assert status == 409
        assert rejected["code"] == "project_mismatch"

        status, queued = _request(base, "/api/annotate", {
            "file_token": token,
            "story_token": story_token,
            "mapping": {},
        })
        assert status == 202
        for _ in range(40):
            _, job = _request(base, "/api/jobs/" + queued["job_id"], method="GET")
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)

        assert job["state"] == "succeeded"
        assert seen[0]["project"] == "第一章"
        assert seen[0]["story_token"] == story_token
        assert seen[0]["bgm_policy"]["bgmId"] == 999
        _, recent = _request(base, "/api/stories/recent", method="GET")
        assert recent[0]["latest_draft_token"] == "draft-annotated"


def test_annotate_story_context_uses_trusted_source_after_file_token_expires(
    tmp_path, monkeypatch
):
    import time
    import webui

    source = tmp_path / "长时间审查.txt"
    source.write_text("旁白: 继续。\n", encoding="utf-8")
    opening_token = webui.register_file_token(str(source))
    seen = []

    def fake_worker(payload):
        seen.append(dict(payload))
        return {
            "draft_token": "draft-after-expiry",
            "project": payload["project"],
            "lines": 1,
            "proposals": 0,
        }

    monkeypatch.setattr(webui, "annotate_draft_worker", fake_worker)
    with _story_server(tmp_path, monkeypatch) as base:
        _, opened = _request(base, "/api/stories/open", {
            "file_token": opening_token,
        })
        status, queued = _request(base, "/api/annotate", {
            "story_token": opened["story_token"],
            "file_token": "ft-expired",
            "mapping": {},
        })
        job = None
        if status == 202:
            for _ in range(40):
                _, job = _request(base, "/api/jobs/" + queued["job_id"], method="GET")
                if job["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.05)

    assert status == 202
    assert job["state"] == "succeeded"
    assert seen[0]["script"] == str(source.resolve())


def test_build_inherits_story_project_and_rejects_mismatched_project(tmp_path, monkeypatch):
    """A build request must not escape the project carried by its story token."""
    import webui

    source = tmp_path / "build-story.txt"
    source.write_text("旁白: 测试\n", encoding="utf-8")
    file_token = webui.register_file_token(str(source))
    queued = []
    received = []

    monkeypatch.setattr(
        webui.global_job_manager,
        "submit",
        lambda fn, **_kwargs: queued.append(fn) or "build-test",
    )
    monkeypatch.setattr(
        webui,
        "run_build",
        lambda payload, job=None: received.append(dict(payload)),
    )
    with _story_server(tmp_path, monkeypatch) as base:
        _, story = _request(base, "/api/stories/open", {
            "file_token": file_token, "project": "StoryBound",
        })

        status, rejected = _request(base, "/api/build", {
            "story_token": story["story_token"], "project": "OtherProject",
            "script": str(source), "mapping": {},
        })
        assert status == 409
        assert rejected["code"] == "project_mismatch"

        status, accepted = _request(base, "/api/build", {
            "story_token": story["story_token"], "script": str(source), "mapping": {},
        })
        assert status == 200
        assert accepted["ok"] is True
        queued[0](object())

    assert received == [{
        "story_token": story["story_token"], "script": str(source),
        "mapping": {}, "layout_mode": "ai", "project": "StoryBound",
        "bgm_policy": {"enabled": False, "arrangement": "manual", "bgmId": 999},
    }]


def test_legacy_draft_import_validates_project_name(tmp_path, monkeypatch):
    """Legacy imports must not turn a browser string into a project path."""
    import webui

    source = tmp_path / "旧剧本.txt"
    source.write_text("## 场景1\n凯伊: 你好\n", encoding="utf-8")
    token = webui.register_file_token(str(source))

    with _story_server(tmp_path, monkeypatch) as base:
        for unsafe_name in ("..\\outside", ".", "..", "bad:name", "CON"):
            status, response = _request(base, "/api/drafts/import", {
                "file_token": token,
                "project": unsafe_name,
            })
            assert status == 400
            assert response["ok"] is False
            assert response["code"] == "invalid_project_name"

        status, imported = _request(base, "/api/drafts/import", {
            "file_token": token,
            "project": "旧版工程",
        })
        assert status == 200
        assert imported["project"] == "旧版工程"


def test_legacy_draft_import_keeps_existing_default_project_name(tmp_path, monkeypatch):
    """Changing the legacy fallback project name breaks existing draft workflows."""
    import webui

    source = tmp_path / "旧剧本.txt"
    source.write_text("## 场景1\n凯伊: 你好\n", encoding="utf-8")
    token = webui.register_file_token(str(source))

    with _story_server(tmp_path, monkeypatch) as base:
        status, imported = _request(base, "/api/drafts/import", {"file_token": token})
        assert status == 200
        assert imported["project"] == "未命名工程"

        status, detail = _request(
            base, "/api/draft?token=" + imported["draft_token"], method="GET"
        )
        assert status == 200
        assert detail["project"] == "未命名工程"


def test_story_workspace_initialization_is_singleton_per_aa_root(tmp_path, monkeypatch):
    """Concurrent first access must not publish two registry instances for one AA root."""
    import webui

    actual_registry = webui.StoryWorkspaceRegistry
    entered_factory = threading.Event()
    factory_calls = []

    def delayed_registry(index_path, aa_data):
        factory_calls.append((index_path, aa_data))
        entered_factory.set()
        # Without an initialization lock, both callers have already passed the
        # check by the time this short wait completes.
        threading.Event().wait(0.15)
        return actual_registry(index_path, aa_data)

    monkeypatch.setattr(webui, "StoryWorkspaceRegistry", delayed_registry)
    monkeypatch.setattr(webui, "STORY_WORKSPACE", None)
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "data"))
    start = threading.Barrier(3)
    returned = []

    def resolve():
        start.wait(timeout=3)
        returned.append(webui.story_workspace())

    workers = [threading.Thread(target=resolve) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait(timeout=3)
    for worker in workers:
        worker.join(timeout=3)

    assert len(factory_calls) == 1
    assert len({id(workspace) for workspace in returned}) == 1


def test_web_registry_migrates_legacy_index_without_writing_to_aa_data(
    tmp_path, monkeypatch
):
    import webui

    aa_data = tmp_path / "aa-data"
    source = tmp_path / "story.txt"
    source.write_text("旁白: 开始。\n", encoding="utf-8")
    legacy_path = aa_data / ".story-index.json"
    legacy = StoryWorkspaceRegistry(legacy_path, aa_data=aa_data)
    context = legacy.open_path(source, project="只读迁移")
    legacy.set_latest_draft_token(context.story_token, "draft-legacy")
    before_bytes = legacy_path.read_bytes()
    before_mtime = legacy_path.stat().st_mtime_ns

    monkeypatch.setattr(webui, "STORY_WORKSPACE", None)
    monkeypatch.setitem(webui.CFG, "aa_data", str(aa_data))

    migrated = webui.story_workspace()

    assert migrated.index_path.parent == (
        webui.LAYOUT.out_root / "story-workspaces"
    ).resolve()
    assert migrated.list_recent()[0].latest_draft_token == "draft-legacy"
    assert legacy_path.read_bytes() == before_bytes
    assert legacy_path.stat().st_mtime_ns == before_mtime


def test_story_open_uses_stable_project_error_code_and_keeps_token_code(tmp_path, monkeypatch):
    """Project validation errors must not leak validator wording into the API code."""
    import webui

    source = tmp_path / "第一章.txt"
    source.write_text("## 场景1\n", encoding="utf-8")
    token = webui.register_file_token(str(source))

    with _story_server(tmp_path, monkeypatch) as base:
        status, invalid_project = _request(base, "/api/stories/open", {
            "file_token": token,
            "project": "..\\outside",
        })
        assert status == 400
        assert invalid_project["ok"] is False
        assert invalid_project["code"] == "invalid_project_name"
        assert invalid_project["e"]

        status, invalid_token = _request(base, "/api/stories/open", {
            "file_token": "ft-invalid",
            "project": "第一章",
        })
        assert status == 400
        assert invalid_token["code"] == "invalid_file_token"


def test_invalid_draft_token_is_a_400_for_reads_and_writes(tmp_path, monkeypatch):
    """An unsafe draft token must not become a server error or a CAS conflict."""
    with _story_server(tmp_path, monkeypatch) as base:
        status, detail = _request(base, "/api/draft?token=..%5Coutside", method="GET")
        assert status == 400
        assert detail["ok"] is False
        assert detail["code"] == "invalid_draft_token"
        assert detail["e"]

        status, write = _request(base, "/api/cards/update", {
            "token": "..\\outside",
            "card_id": "card-1",
            "patch": {"text": "should not write"},
            "expected_draft_version": 1,
        })
        assert status == 400
        assert write["ok"] is False
        assert write["code"] == "invalid_draft_token"
        assert write["e"]

        status, background = _request(
            base,
            "/api/drafts/..%5Coutside/backgrounds/card-1/resolve",
            {"bg_name": "night", "expected_draft_version": 1},
        )
        assert status == 400
        assert background["code"] == "invalid_draft_token"
