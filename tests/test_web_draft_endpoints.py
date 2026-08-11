# -*- coding: utf-8 -*-
"""审查工作区新增 HTTP 端点的真实 HTTP 层测试。

覆盖：cards/update|insert|move|delete、review/reset、review/status、jobs/cancel、validate，
以及"严格 CSP 尚未启用"（前端仍含内联脚本，CSP 启用会导致页面不可用）。
"""
import contextlib
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

import webui
from webui import H
from draft_store import DraftStore
from install_manager import AAInstallTargetExistsError


@contextlib.contextmanager
def draft_server(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "data"))
    drafts_dir = tmp_path / "drafts"
    monkeypatch.setattr(
        webui,
        "DraftStore",
        lambda **kw: DraftStore(base_dir=str(drafts_dir), **kw),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", str(drafts_dir)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def req(base, path, payload=None, method="POST"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as exc:
        with exc as resp:
            return resp.status, json.loads(resp.read())


def make_draft(drafts_dir, text, token="draft-http-1"):
    store = DraftStore(base_dir=drafts_dir)
    store.create_draft(token=token, text=text, project="测试工程", source_text=text)
    return token


SAMPLE = "## 场景1\n凯伊: 第一句。\n老师: 第二句。\n"


@pytest.mark.parametrize("value", ["auto", "main", "event", "bond"])
def test_normalize_story_type_accepts_supported_values(value):
    assert webui.normalize_story_type(value) == value


def test_normalize_story_type_defaults_and_rejects_unknown_values():
    assert webui.normalize_story_type(None) == "auto"
    with pytest.raises(ValueError, match="invalid_story_type"):
        webui.normalize_story_type("unknown")


def test_strict_csp_is_applied_to_the_external_runtime(tmp_path, monkeypatch):
    """The markup-only shell is served with the strict CSP contract."""
    with draft_server(tmp_path, monkeypatch) as (base, _):
        with urlopen(base + "/") as resp:
            assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
            assert "'unsafe-inline'" not in resp.headers["Content-Security-Policy"]
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_cards_update_success_and_revision_conflict(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, SAMPLE)
        status, draft = req(base, "/api/draft?token=" + token, method="GET")
        assert status == 200
        card = draft["cards"][1]  # 凯伊 台词行
        card_id = card["card_id"]
        v = draft["draft_version"]

        status, res = req(base, "/api/cards/update", {
            "token": token, "card_id": card_id,
            "patch": {"text": "第一句（改）"},
            "expected_draft_version": v,
        })
        assert status == 200
        assert res["draft_version"] == v + 1
        assert res["content_revision"] == draft["content_revision"] + 1

        # 陈旧 version → 409
        status, res = req(base, "/api/cards/update", {
            "token": token, "card_id": card_id,
            "patch": {"text": "再次改"},
            "expected_draft_version": v,
        })
        assert status == 409
        assert res["code"] == "revision_conflict"


def test_draft_detail_attaches_diagnostics_to_the_affected_card(tmp_path, monkeypatch):
    """The UI needs card-scoped diagnostics to implement a truthful pending-work filter."""
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, "## 场景1\n未绑定角色: 你好\n")
        status, draft = req(base, "/api/draft?token=" + token, method="GET")
        assert status == 200
        card = next(item for item in draft["cards"] if item["line_no"] == 2)
        assert any(issue["severity"] == "error" for issue in card["issues"])


def test_cards_insert_move_delete(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, SAMPLE)
        _, draft = req(base, "/api/draft?token=" + token, method="GET")
        card2_id = draft["cards"][2]["card_id"]  # 老师 台词行
        v = draft["draft_version"]

        # insert 到 card2 之后
        status, res = req(base, "/api/cards/insert", {
            "token": token, "after_card_id": card2_id, "kind": "line",
            "payload": {"who": "爱丽丝", "text": "插入行。"},
            "expected_draft_version": v,
        })
        assert status == 200
        _, draft2 = req(base, "/api/draft?token=" + token, method="GET")
        assert any(c["current"].get("text") == "插入行。" for c in draft2["cards"])
        v2 = draft2["draft_version"]
        new_id = next(c["card_id"] for c in draft2["cards"]
                      if c["current"].get("text") == "插入行。")

        # move：把新增行移到最前
        first_id = draft2["cards"][0]["card_id"]
        status, res = req(base, "/api/cards/move", {
            "token": token, "card_id": new_id, "before_card_id": first_id,
            "expected_draft_version": v2,
        })
        assert status == 200
        _, draft3 = req(base, "/api/draft?token=" + token, method="GET")
        assert draft3["cards"][0]["current"].get("text") == "插入行。"
        v3 = draft3["draft_version"]

        # delete
        status, res = req(base, "/api/cards/" + new_id, {
            "token": token, "expected_draft_version": v3,
        }, method="DELETE")
        assert status == 200
        _, draft4 = req(base, "/api/draft?token=" + token, method="GET")
        assert all(c["card_id"] != new_id for c in draft4["cards"])


def test_review_approve_reset_and_status(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, SAMPLE)
        _, draft = req(base, "/api/draft?token=" + token, method="GET")
        v = draft["draft_version"]

        # 初始未就绪
        status, res = req(base, "/api/review/status?token=" + token, method="GET")
        assert status == 200 and res["ready"] is False

        # 批准全部（不带 card_ids → 全部低风险卡）。注意 SAMPLE 中凯伊/老师未绑定演员，
        # 会产生 blocking error，因此 ready 仍为 False（门控还要求 blocking_errors==0）——
        # 这里验证的是 pending 归零与 reset 后回升的语义。
        status, res = req(base, "/api/review/approve", {
            "token": token, "expected_draft_version": v,
        })
        assert status == 200

        status, res = req(base, "/api/review/status?token=" + token, method="GET")
        assert status == 200
        assert res["pending"] == 0          # 全部已审
        assert res["blocking_errors"] >= 1  # 未绑定演员仍是阻塞项
        assert res["ready"] is False

        # 重置单卡 → pending 回升
        _, draft2 = req(base, "/api/draft?token=" + token, method="GET")
        target = next(c for c in draft2["cards"] if c["review_state"] == "approved")
        status, res = req(base, "/api/review/reset", {
            "token": token, "card_id": target["card_id"],
            "expected_draft_version": draft2["draft_version"],
        })
        assert status == 200
        status, res = req(base, "/api/review/status?token=" + token, method="GET")
        assert status == 200 and res["ready"] is False
        assert res["pending"] >= 1


def test_validate_endpoint(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, SAMPLE)
        status, res = req(base, "/api/validate", {"token": token})
        assert status == 200
        assert isinstance(res["blocking_errors"], int)
        assert isinstance(res["diagnostics"], list)


def test_background_request_resolve_route_replaces_the_card(tmp_path, monkeypatch):
    text = "## 场景1\n# 待生成自定义背景：雨夜车站\n旁白: 到站了。\n"
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, text, token="background-http-1")
        _, draft = req(base, "/api/draft?token=" + token, method="GET")
        card = next(item for item in draft["cards"] if item["kind"] == "background_request")

        status, result = req(
            base,
            f"/api/drafts/{token}/backgrounds/{card['card_id']}/resolve",
            {"bg_name": "BG_Black", "expected_draft_version": draft["draft_version"]},
        )

        assert status == 200
        assert result == {
            "ok": True,
            "draft_version": draft["draft_version"] + 1,
            "content_revision": draft["content_revision"] + 1,
        }
        _, resolved = req(base, "/api/draft?token=" + token, method="GET")
        assert resolved["cards"][1]["card_id"] == card["card_id"]
        assert resolved["cards"][1]["current"] == {"cmd": "bg", "arg": "BG_Black"}


def test_draft_endpoint_uses_normalized_card_nodes(tmp_path, monkeypatch):
    text = "旁白: 第一行。\n\n---\n\n旁白: 第二行。\n"
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, text)

        status, draft = req(base, "/api/draft?token=" + token, method="GET")

        assert status == 200
        assert [card["kind"] for card in draft["cards"]] == [
            "line",
            "separator",
            "line",
        ]
        assert [card["line_no"] for card in draft["cards"]] == [1, 3, 5]


def test_jobs_cancel(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        # 提交一个卡住的 job（不存在的 token 会让 worker 抛错，但我们先 cancel queued）
        from jobs import global_job_manager

        def slow(job):
            import time
            for i in range(100):
                if job.is_cancel_requested():
                    raise RuntimeError("cancelled-by-request")
                job.update_progress(i / 100)
                time.sleep(0.05)
            return "done"

        job_id = global_job_manager.submit(slow, label="cancel-test", prefix="cancel-")
        status, res = req(base, "/api/jobs/" + job_id + "/cancel", {})
        assert status == 200
        assert res["job"]["state"] in ("cancelled", "running")


def test_cast_update_binds_speaker_and_resets_pending(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, SAMPLE)
        _, draft = req(base, "/api/draft?token=" + token, method="GET")
        v = draft["draft_version"]

        status, res = req(base, "/api/draft/cast/update", {
            "token": token, "speaker": "凯伊",
            "mapping": {"id": "kei-ident", "name": "凯伊", "portrait": True},
            "expected_draft_version": v,
        })
        assert status == 200
        assert res["draft_version"] == v + 1
        assert res["content_revision"] == draft["content_revision"] + 1

        # cast 已保存到草稿
        store = DraftStore(base_dir=drafts_dir)
        cast = store.load_cast(token)
        assert cast["cast"]["凯伊"]["id"] == "kei-ident"

        # 凯伊的 line 卡重置为待审
        _, draft2 = req(base, "/api/draft?token=" + token, method="GET")
        kei_cards = [c for c in draft2["cards"]
                     if c["kind"] == "line" and c["current"].get("who") == "凯伊"]
        assert kei_cards
        assert all(c["review_state"] == "pending" for c in kei_cards)

        # 陈旧 version → 409
        status, res = req(base, "/api/draft/cast/update", {
            "token": token, "speaker": "老师",
            "mapping": {"id": "x", "portrait": True},
            "expected_draft_version": v,
        })
        assert status == 409
        assert res["code"] == "revision_conflict"


def test_annotate_endpoint_submits_job(tmp_path, monkeypatch):
    """/api/annotate 是异步 Job：mock worker 返回假草稿，验证 202 + job 轮询。"""
    monkeypatch.setattr(
        webui, "annotate_draft_worker",
        lambda payload: {"draft_token": "draft-mock", "project": "p",
                         "lines": 1, "proposals": 0},
    )
    with draft_server(tmp_path, monkeypatch) as (base, _):
        script = tmp_path / "剧本.txt"
        script.write_text("凯伊: 你好。\n", encoding="utf-8")

        status, res = req(base, "/api/annotate", {
            "script": str(script),
            "mapping": {"凯伊": {"kind": "portrait", "id": "kai"}},
            "bg": "BG_Black",
        })
        assert status == 202
        job_id = res["job_id"]

        import time
        job = {"state": "queued"}
        for _ in range(60):
            _, job = req(base, "/api/jobs/" + job_id, method="GET")
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert job["state"] == "succeeded"
        assert job["result"]["draft_token"] == "draft-mock"


def test_annotate_endpoint_rejects_missing_script(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, _):
        status, res = req(base, "/api/annotate", {
            "script": str(tmp_path / "不存在.txt"), "mapping": {},
        })
        assert status == 400


def test_annotate_endpoint_rejects_unknown_story_type_before_submitting_job(
    tmp_path, monkeypatch,
):
    with draft_server(tmp_path, monkeypatch) as (base, _):
        script = tmp_path / "剧本.txt"
        script.write_text("凯伊: 你好。\n", encoding="utf-8")

        status, res = req(base, "/api/annotate", {
            "script": str(script),
            "mapping": {"凯伊": {"kind": "portrait", "id": "kai"}},
            "story_type": "side-story",
        })

        assert status == 400
        assert res["code"] == "invalid_story_type"


def test_legacy_build_endpoint_rejects_unknown_story_type(tmp_path, monkeypatch):
    with draft_server(tmp_path, monkeypatch) as (base, _):
        status, res = req(base, "/api/build", {"story_type": "side-story"})

        assert status == 400
        assert res["code"] == "invalid_story_type"


def test_legacy_build_worker_forwards_story_type_to_annotator(tmp_path, monkeypatch):
    source = tmp_path / "原稿.txt"
    source.write_text("旁白: 保留原文\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(webui, "HERE", str(tmp_path))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "aa-data"))
    monkeypatch.setattr(webui, "db", lambda: object())
    monkeypatch.setattr(webui, "prepare_project_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "attach_registered_variants", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "annotation_provider", lambda *_: object())
    monkeypatch.setattr(webui, "pause_for_backgrounds", lambda *_: False)
    monkeypatch.setattr(webui, "_compile_saved_context", lambda *_: None)

    def fake_annotate(options, provider_instance=None):
        captured["options"] = options
        return {"text": "旁白: 保留原文\n"}

    monkeypatch.setattr("annotate.annotate_script", fake_annotate)

    webui.run_build({
        "script": str(source), "project": "旧入口测试", "mapping": {},
        "annotate": True, "story_type": "event",
    })

    assert captured["options"]["story_type"] == "event"


def test_annotate_worker_can_create_review_draft_without_calling_model(tmp_path, monkeypatch):
    source = tmp_path / "原稿.txt"
    source.write_text("旁白: 保留原文\n@bg BG_Black\n", encoding="utf-8")
    captured = {}

    class FakeStore:
        def create_draft(self, **kwargs):
            captured.update(kwargs)

        def save_cast(self, token, cast):
            captured["saved_cast"] = cast

        def add_proposals(self, token, proposals):
            raise AssertionError("仅转换格式不应产生 AI 提案")

    monkeypatch.setattr(webui, "HERE", str(tmp_path))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "aa-data"))
    monkeypatch.setattr(webui, "db", lambda: object())
    monkeypatch.setattr(webui, "prepare_project_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "attach_registered_variants", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "DraftStore", FakeStore)
    monkeypatch.setattr(
        webui, "annotation_provider",
        lambda *_: (_ for _ in ()).throw(AssertionError("不应读取模型")),
    )

    result = webui.annotate_draft_worker({
        "script": str(source),
        "project": "仅转换测试",
        "story_token": "story-format-only",
        "mapping": {},
        "annotate": False,
    })

    assert captured["text"] == source.read_text(encoding="utf-8")
    assert captured["source_text"] == captured["text"]
    assert captured["story_token"] == "story-format-only"


def test_annotate_worker_exposes_agent_checkpoint_reuse(tmp_path, monkeypatch):
    source = tmp_path / "原稿.txt"
    source.write_text("旁白: 保留原文\n", encoding="utf-8")

    class FakeStore:
        def create_draft(self, **_kwargs):
            pass

        def save_cast(self, _token, _cast):
            pass

        def add_proposals(self, _token, _proposals):
            pass

    monkeypatch.setattr(webui, "HERE", str(tmp_path))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "aa-data"))
    monkeypatch.setattr(webui, "db", lambda: object())
    monkeypatch.setattr(webui, "prepare_project_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "attach_registered_variants", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "DraftStore", FakeStore)
    monkeypatch.setattr(webui, "annotation_provider", lambda *_: object())
    monkeypatch.setattr("annotate.annotate_script", lambda *_args, **_kwargs: {
        "text": "旁白: 保留原文\n", "agent": {"resumed_chunks": 3}, "proposals": [],
    })

    result = webui.annotate_draft_worker({
        "script": str(source), "project": "复用测试", "mapping": {}, "annotate": True,
    })

    assert result["resumed_chunks"] == 3
    assert result["proposals"] == 0


def test_annotate_worker_forwards_model_activity_and_returns_agent_metrics(tmp_path, monkeypatch):
    source = tmp_path / "原稿.txt"
    source.write_text("旁白: 保留原文\n", encoding="utf-8")
    captured = {}

    class FakeStore:
        def create_draft(self, **kwargs):
            captured["draft"] = kwargs

        def save_cast(self, _token, _cast):
            pass

        def add_proposals(self, _token, _proposals):
            pass

    class FakeJob:
        def __init__(self):
            self.activities = []

        def update_activity(self, activity):
            self.activities.append(dict(activity))

        def is_cancel_requested(self):
            return False

    job = FakeJob()
    monkeypatch.setattr(webui, "HERE", str(tmp_path))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "aa-data"))
    monkeypatch.setattr(webui, "db", lambda: object())
    monkeypatch.setattr(webui, "prepare_project_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "attach_registered_variants", lambda *args, **kwargs: None)
    monkeypatch.setattr(webui, "DraftStore", FakeStore)
    monkeypatch.setattr(webui, "annotation_provider", lambda *_: object())

    def fake_annotate(options, provider_instance=None):
        captured["options"] = options
        options["model_activity"]({
            "state": "receiving",
            "model": "deepseek-v4-flash",
            "received_chars": 128,
        })
        return {
            "text": "旁白: 保留原文\n",
            "agent": {
                "resumed_chunks": 3,
                "metrics": {
                    "actual_model": "deepseek-v4-flash",
                    "requests": 7,
                    "cache_reported": True,
                    "cache_read_tokens": 130432,
                    "uncached_input_tokens": 58682,
                    "cache_hit_rate": 0.69,
                },
            },
            "proposals": [],
        }

    monkeypatch.setattr("annotate.annotate_script", fake_annotate)
    result = webui.annotate_draft_worker({
        "script": str(source), "project": "活动测试", "mapping": {}, "annotate": True,
        "story_type": "event",
    }, job=job)

    assert captured["options"]["model_activity"] is not None
    assert captured["options"]["story_type"] == "event"
    assert job.activities[-1] == {
        "state": "receiving",
        "model": "deepseek-v4-flash",
        "received_chars": 128,
    }
    assert result["agent_metrics"] == {
        "actual_model": "deepseek-v4-flash",
        "requests": 7,
        "cache_reported": True,
        "cache_read_tokens": 130432,
        "uncached_input_tokens": 58682,
        "cache_hit_rate": pytest.approx(0.69, abs=0.01),
    }
    assert result["story_type"] == "event"


def test_install_options_and_confirmed_name_are_forwarded_through_http(
    tmp_path, monkeypatch
):
    calls = []

    class FakeInstallManager:
        def install_options(self, token, build_id):
            calls.append(("options", token, build_id))
            return {
                "ok": True,
                "source_project": "第一幕-第一章",
                "default_category": "",
                "default_story_name": "第一幕-第一章",
                "categories": ["大故事"],
            }

        def install_build(self, token, build_id, *, category, story_name):
            calls.append(("install", token, build_id, category, story_name))
            return {
                "ok": True,
                "project": "大故事-第一幕-第一章",
                "aap_path": r"E:\AA\data\projects\大故事-第一幕-第一章.aap",
                "project_dir": r"E:\AA\data\projects\大故事-第一幕-第一章",
                "save_dir": r"E:\AA\data\saves\大故事-第一幕-第一章",
            }

    monkeypatch.setattr(webui, "InstallManager", FakeInstallManager)
    with draft_server(tmp_path, monkeypatch) as (base, _):
        status, options = req(
            base,
            "/api/install/options?token=draft-one&build_id=build-one",
            method="GET",
        )
        assert status == 200
        assert options["default_category"] == ""
        assert options["categories"] == ["大故事"]

        status, result = req(base, "/api/install", {
            "token": "draft-one",
            "build_id": "build-one",
            "category": "大故事",
            "story_name": "第一幕-第一章",
        })

    assert status == 200
    assert result["project"] == "大故事-第一幕-第一章"
    assert result["aap_path"].endswith("大故事-第一幕-第一章.aap")
    assert calls == [
        ("options", "draft-one", "build-one"),
        ("install", "draft-one", "build-one", "大故事", "第一幕-第一章"),
    ]


def test_install_target_conflict_is_reported_as_409(tmp_path, monkeypatch):
    class ConflictingInstallManager:
        def install_build(self, token, build_id, *, category, story_name):
            raise AAInstallTargetExistsError("AA 中已存在同名工程")

    monkeypatch.setattr(webui, "InstallManager", ConflictingInstallManager)
    with draft_server(tmp_path, monkeypatch) as (base, _):
        status, result = req(base, "/api/install", {
            "token": "draft-one",
            "build_id": "build-one",
            "category": "大故事",
            "story_name": "第一章",
        })

    assert status == 409
    assert result == {
        "ok": False,
        "code": "install_target_exists",
        "e": "AA 中已存在同名工程",
    }


def test_draft_detail_restores_current_compile_and_install_state(
    tmp_path, monkeypatch
):
    with draft_server(tmp_path, monkeypatch) as (base, drafts_dir):
        token = make_draft(drafts_dir, "旁白: 已完成\n", token="restored-build")
        store = DraftStore(base_dir=drafts_dir)
        session_file = store.get_draft_path(token) / "session.json"
        session = json.loads(session_file.read_text(encoding="utf-8"))
        session.update({
            "last_compiled_build_id": "build-current",
            "last_compiled_content_revision": session["content_revision"],
            "last_installed_build_id": "build-current",
            "last_installed_project": "大故事-第一章",
        })
        session_file.write_text(
            json.dumps(session, ensure_ascii=False), encoding="utf-8"
        )

        status, result = req(base, "/api/draft?token=" + token, method="GET")

    assert status == 200
    assert result["last_compiled_build_id"] == "build-current"
    assert result["last_installed_build_id"] == "build-current"
    assert result["last_installed_project"] == "大故事-第一章"
