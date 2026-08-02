import contextlib
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

import webui
from background_workflow import BackgroundResolutionError


@pytest.fixture(autouse=True)
def reset_resume_state(monkeypatch):
    monkeypatch.setattr(webui, "BUILD_RESUME", None)
    webui.JOB.clear()
    webui.JOB.update(
        running=False,
        log=[],
        done=False,
        ok=False,
        state="idle",
    )


def test_pause_for_backgrounds_exposes_structured_recoverable_job(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：傍晚的咖啡厅\n凯伊：测试\n",
        encoding="utf-8",
    )

    paused = webui.pause_for_backgrounds(
        script,
        {
            "project": "约会短篇",
            "src": str(script),
            "project_dir": str(tmp_path / "project"),
        },
    )

    assert paused is True
    assert webui.JOB["state"] == "needs_backgrounds"
    assert webui.JOB["done"] is True
    assert webui.JOB["ok"] is False
    assert webui.JOB["resume_token"]
    assert webui.JOB["background_requests"][0]["description"] == "傍晚的咖啡厅"
    assert "16:9" in webui.JOB["background_requests"][0]["prompt"]
    assert "script_path" not in json.dumps(
        {
            "state": webui.JOB["state"],
            "background_requests": webui.JOB["background_requests"],
        },
        ensure_ascii=False,
    )


def test_resolve_and_continue_use_saved_annotation_without_model_rerun(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：傍晚的咖啡厅\n凯伊：测试\n",
        encoding="utf-8",
    )
    context = {
        "project": "约会短篇",
        "src": str(script),
        "project_dir": str(tmp_path / "project"),
    }
    assert webui.pause_for_backgrounds(script, context)
    token = webui.JOB["resume_token"]
    request_id = webui.JOB["background_requests"][0]["id"]

    state = webui.resolve_background_for_build(
        {
            "token": token,
            "request_id": request_id,
            "background_name": "BG_Custom_Cafe",
        },
        registered_backgrounds={"BG_Custom_Cafe"},
    )

    assert state["ready"] is True
    assert "@bg BG_Custom_Cafe" in script.read_text(encoding="utf-8")
    calls = []
    webui.continue_background_build(
        token,
        compile_runner=lambda saved: calls.append(dict(saved)),
    )

    assert len(calls) == 1
    assert calls[0]["src"] == str(script)
    assert webui.JOB["state"] == "succeeded"
    assert webui.JOB["ok"] is True
    assert webui.JOB["done"] is True


def test_continue_is_blocked_until_all_backgrounds_are_resolved(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：场景甲\n"
        "# 待生成自定义背景：场景乙\n",
        encoding="utf-8",
    )
    webui.pause_for_backgrounds(
        script,
        {"project": "测试", "src": str(script)},
    )

    with pytest.raises(BackgroundResolutionError, match="尚未全部解决"):
        webui.continue_background_build(
            webui.JOB["resume_token"],
            compile_runner=lambda _saved: None,
        )


def test_continue_failure_reports_the_frontend_terminal_failed_state(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text("# 待生成自定义背景：场景甲\n", encoding="utf-8")
    assert webui.pause_for_backgrounds(script, {"project": "测试", "src": str(script)})
    token = webui.JOB["resume_token"]
    request_id = webui.JOB["background_requests"][0]["id"]
    webui.resolve_background_for_build(
        {"token": token, "request_id": request_id, "background_name": "BG_A"},
        registered_backgrounds={"BG_A"},
    )

    webui.continue_background_build(
        token,
        compile_runner=lambda _saved: (_ for _ in ()).throw(RuntimeError("compile boom")),
    )

    assert webui.JOB["state"] == "failed"
    assert webui.JOB["done"] is True
    assert webui.JOB["ok"] is False


@contextlib.contextmanager
def _background_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _post_json(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def test_continue_http_marks_job_compiling_before_the_worker_can_run(tmp_path, monkeypatch):
    script = tmp_path / "annotated.txt"
    script.write_text("# 待生成自定义背景：场景甲\n", encoding="utf-8")
    assert webui.pause_for_backgrounds(script, {"project": "测试", "src": str(script)})
    token = webui.JOB["resume_token"]
    request_id = webui.JOB["background_requests"][0]["id"]
    webui.resolve_background_for_build(
        {"token": token, "request_id": request_id, "background_name": "BG_A"},
        registered_backgrounds={"BG_A"},
    )
    started, release = threading.Event(), threading.Event()

    def slow_continue(_token):
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(webui, "continue_background_build", slow_continue)
    try:
        with _background_server() as base:
            assert _post_json(base, "/api/build/background/continue", {"token": token}) == {"ok": True}
            assert started.wait(timeout=1)
            with webui.JOB_LOCK:
                state = {key: webui.JOB[key] for key in ("state", "running", "done")}
            assert state == {"state": "compiling", "running": True, "done": False}
    finally:
        release.set()


def test_wrong_resume_token_cannot_resolve_another_build(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text("# 待生成自定义背景：场景甲\n", encoding="utf-8")
    webui.pause_for_backgrounds(
        script,
        {"project": "测试", "src": str(script)},
    )
    request_id = webui.JOB["background_requests"][0]["id"]

    with pytest.raises(BackgroundResolutionError, match="已失效"):
        webui.resolve_background_for_build(
            {
                "token": "wrong",
                "request_id": request_id,
                "background_name": "BG_A",
            },
            registered_backgrounds={"BG_A"},
        )
