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

import webui
from webui import H
from draft_store import DraftStore


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
    assert result["proposals"] == 0
