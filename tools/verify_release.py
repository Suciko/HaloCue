"""Verify a public HaloCue Windows ZIP in clean, another-machine conditions."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from release_smoke import (  # noqa: E402
    create_synthetic_aa_workspace,
    python_free_path,
    tree_digests,
)


APP_ID = "halocue-local-server-v1"
VERSION = "0.9.0-beta.1"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def json_request(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=body,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_bytes(base: str, path: str) -> tuple[int, bytes, str]:
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.status, response.read(), response.headers.get_content_type()


def _content_type_matches(actual: str, expected: str) -> bool:
    accepted = {
        "html": {"text/html"},
        "css": {"text/css"},
        "javascript": {"application/javascript", "text/javascript"},
        "png": {"image/png"},
    }
    return actual in accepted[expected]


def _narrator_binding_payload(token: str, draft_version: int) -> dict:
    return {
        "token": token,
        "speaker": "旁白",
        "mapping": {"narrator": True},
        "expected_draft_version": draft_version,
    }


class _FakeModelHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        body = json.dumps({
            "id": "smoke-response",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def fake_model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


def _clean_environment(user_root: Path, fake_home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for name in list(environment):
        if name.upper().startswith("PYTHON") or name.upper() in {
            "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "VIRTUAL_ENV", "AA_DATA",
        }:
            environment.pop(name, None)
    temp_root = user_root / "os-temp"
    app_data = fake_home / "AppData" / "Roaming"
    local_app_data = fake_home / "AppData" / "Local"
    for path in (user_root, temp_root, app_data, local_app_data):
        path.mkdir(parents=True, exist_ok=True)
    environment.update({
        "PATH": python_free_path(),
        "HALOCUE_USER_DATA_DIR": str(user_root),
        "USERPROFILE": str(fake_home),
        "HOME": str(fake_home),
        "APPDATA": str(app_data),
        "LOCALAPPDATA": str(local_app_data),
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
    })
    require(shutil.which("python", path=environment["PATH"]) is None, "restricted PATH still finds Python")
    return environment


def _extract_archive(archive: Path, target: Path) -> Path:
    with zipfile.ZipFile(archive) as source:
        source.extractall(target)
    candidates = list(target.glob("*/HaloCue.exe"))
    require(len(candidates) == 1, "archive must contain exactly one top-level HaloCue.exe")
    return candidates[0].parent


def _json_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError(f"no JSON object in process output: {stdout[-1000:]}")


def _check_command(exe: Path, selection_flag: str, selection: Path, env: dict) -> dict:
    result = subprocess.run(
        [str(exe), "--check", "--json", selection_flag, str(selection)],
        cwd=exe.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    require(result.returncode == 0, f"packaged --check failed ({result.returncode}): {result.stderr}")
    payload = _json_line(result.stdout)
    require(payload.get("ok") is True, "packaged --check did not report ok=true")
    require(payload.get("aa", {}).get("connected") is True, "packaged --check did not connect synthetic AA")
    return payload


def _start(exe: Path, args: list[str], env: dict) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        [str(exe), *args],
        cwd=exe.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )


def _wait_ready(process: subprocess.Popen, ready_file: Path, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise VerificationError(
                f"HaloCue exited before readiness ({process.returncode})\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        if ready_file.is_file():
            try:
                payload = json.loads(ready_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            if payload.get("port"):
                return payload
        time.sleep(0.1)
    raise VerificationError("timed out waiting for packaged ready-file")


def _stop_cleanly(process: subprocess.Popen, ready_file: Path) -> tuple[str, str]:
    require(process.poll() is None, "HaloCue stopped before shutdown request")
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGINT)
    try:
        stdout, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate(timeout=10)
        raise VerificationError("HaloCue did not stop cleanly after Ctrl+C/Ctrl+Break") from exc
    require(process.returncode == 0, f"HaloCue clean shutdown returned {process.returncode}: {stderr}")
    deadline = time.monotonic() + 5
    while ready_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    require(not ready_file.exists(), "ready-file remained after shutdown")
    return stdout, stderr


def _assert_http_identity(base: str, expected_data: Path) -> dict:
    for path, expected_type in (
        ("/", "html"),
        ("/css/app.css", "css"),
        ("/js/app.js", "javascript"),
        ("/branding/halocue-favicon.png", "png"),
    ):
        status, body, content_type = get_bytes(base, path)
        require(status == 200 and body, f"{path} was not a non-empty HTTP 200")
        require(
            _content_type_matches(content_type, expected_type),
            f"{path} content type was {content_type}",
        )
    status, setup = json_request(base, "/api/setup/status")
    require(status == 200, "/api/setup/status was not HTTP 200")
    require(setup.get("app_id") == APP_ID and setup.get("version") == VERSION, "wrong HaloCue identity")
    require(Path(setup.get("aa", {}).get("path", "")).resolve() == expected_data.resolve(), "wrong persisted AA data path")
    require(setup.get("spine") == {"configured": False, "path": "", "resolved_path": ""}, "missing Spine was not safely unconfigured")
    status, workbench = json_request(base, "/api/llm/workbench")
    require(status == 200 and workbench.get("schema_version") == 2, "model workbench schema is not v2")
    return setup


def _browser_check(base: str, profile_dir: Path) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise VerificationError("Playwright is not installed; browser download is intentionally disabled") from exc
    errors: list[str] = []
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=True
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on(
            "console",
            lambda message: errors.append(f"console: {message.text}")
            if message.type == "error" else None,
        )
        response = page.goto(base + "/", wait_until="networkidle", timeout=30_000)
        require(response is not None and response.status == 200, "browser did not load HaloCue UI")
        require("HaloCue" in page.title(), "browser title does not identify HaloCue")
        page.wait_for_selector("body", timeout=10_000)
        context.close()
    require(not errors, "browser errors: " + " | ".join(errors))
    return errors


def _exercise_workflow(base: str, source_script: Path, model_url: str) -> str:
    upload = urllib.request.Request(
        base + "/api/story-files/upload",
        data=source_script.read_bytes(),
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-AA-Filename": urllib.parse.quote(source_script.name),
        },
    )
    with urllib.request.urlopen(upload, timeout=10) as response:
        selected = json.loads(response.read().decode("utf-8"))
    require(selected.get("file_token", "").startswith("ft-"), "story upload did not return an opaque file token")
    status, model_test = json_request(base, "/api/llm/test", {
        "mode": "text",
        "profile": {
            "name": "Local smoke model",
            "provider": "openai",
            "service_preset": "custom",
            "base_url": model_url,
            "model": "smoke-model",
            "api_key": "synthetic-not-a-credential",
            "vision": False,
        },
    })
    require(status == 200 and model_test.get("ok") is True, "fake local model response was rejected")
    status, imported = json_request(base, "/api/drafts/import", {
        "file_token": selected["file_token"], "project": "发布验收",
    })
    require(status == 200 and imported.get("draft_token", "").startswith("draft-"), "draft import failed")
    token = imported["draft_token"]
    status, detail = json_request(base, f"/api/draft?token={urllib.parse.quote(token)}")
    require(status == 200, "draft detail failed")
    status, bound = json_request(
        base,
        "/api/draft/cast/update",
        _narrator_binding_payload(token, detail["draft_version"]),
    )
    require(status == 200, "minimal narrator binding failed")
    status, approved = json_request(base, "/api/review/approve", {
        "token": token, "expected_draft_version": bound["draft_version"],
    })
    require(status == 200, "minimal draft review failed")
    status, compiled = json_request(base, "/api/compile", {
        "token": token, "expected_draft_version": approved["draft_version"],
    })
    require(status == 202 and compiled.get("job_id"), "minimal draft compile was not accepted")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, job = json_request(base, f"/api/jobs/{compiled['job_id']}")
        require(status == 200, "compile job disappeared")
        if job.get("state") in {"succeeded", "failed", "cancelled"}:
            require(job.get("state") == "succeeded", f"minimal compile failed: {job.get('error', '')}")
            break
        time.sleep(0.1)
    else:
        raise VerificationError("minimal compile timed out")
    return token


def verify(
    archive: Path,
    *,
    selection_mode: str,
    keep_temp: bool = False,
    browser_check: bool = True,
) -> dict:
    archive = archive.resolve(strict=True)
    scenario = Path(tempfile.mkdtemp(prefix="HaloCue 发布验收 "))
    process: subprocess.Popen | None = None
    result = {"archive": str(archive), "selection_mode": selection_mode, "scenario": str(scenario)}
    try:
        workspace = create_synthetic_aa_workspace(scenario)
        extract_root = scenario / "解压后的 程序" / "来自另一台电脑的长路径"
        bundle = _extract_archive(archive, extract_root)
        exe = bundle / "HaloCue.exe"
        user_root = scenario / "全新用户 数据" / "HaloCue"
        env = _clean_environment(user_root, workspace.fake_home)
        selection_flag = "--aa-data" if selection_mode == "data" else "--aa-install"
        selection = workspace.data if selection_mode == "data" else workspace.executable
        bundle_before = tree_digests(bundle)
        workspace_before = tree_digests(workspace.root)
        check = _check_command(exe, selection_flag, selection, env)
        seed = bundle / "data" / "halocue_labels.db"
        database = user_root / "aa_assets.db"
        require(seed.is_file() and database.is_file(), "sanitized database was not copied to user state")
        require(seed.read_bytes() == database.read_bytes(), "first-run database copy differs from packaged seed")
        (user_root / "aa_resources.json").write_text(json.dumps({
            "bg": {"BG_Black": 0}, "sounds": [], "characters": [],
            "enums": {"emoticon": {}, "action": {}, "appear": {}, "shape": {}},
            "face_capabilities": {},
        }), encoding="utf-8")
        ready = user_root / "run" / "first ready.json"
        process = _start(exe, [
            "--no-browser", "--port", "0", "--ready-file", str(ready),
            selection_flag, str(selection),
        ], env)
        ready_payload = _wait_ready(process, ready)
        require(ready_payload.get("app_id") == APP_ID and ready_payload.get("version") == VERSION, "ready-file identity mismatch")
        base = f"http://{ready_payload['host']}:{ready_payload['port']}"
        _assert_http_identity(base, workspace.data)
        if browser_check:
            _browser_check(base, user_root / "browser-profile")
        with fake_model_server() as model_url:
            draft_token = _exercise_workflow(base, workspace.source_script, model_url)
        status, changed = json_request(base, "/api/settings/aa-data", {"aa_data": str(workspace.alternate_data)})
        require(status == 200 and changed.get("ok") is True, "API path setting was not accepted")
        _stop_cleanly(process, ready)
        process = None
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS release_smoke_marker (value TEXT NOT NULL)")
            connection.execute("DELETE FROM release_smoke_marker")
            connection.execute("INSERT INTO release_smoke_marker(value) VALUES ('keep-on-restart')")
            connection.commit()
        ready2 = user_root / "run" / "second ready.json"
        process = _start(exe, ["--no-browser", "--port", "0", "--ready-file", str(ready2)], env)
        second_payload = _wait_ready(process, ready2)
        base2 = f"http://{second_payload['host']}:{second_payload['port']}"
        _assert_http_identity(base2, workspace.alternate_data)
        status, restored = json_request(base2, f"/api/draft?token={urllib.parse.quote(draft_token)}")
        status_list, sessions = json_request(base2, "/api/drafts")
        listed_tokens = {
            item.get("draft_token")
            for item in sessions
            if isinstance(item, dict)
        } if status_list == 200 and isinstance(sessions, list) else set()
        require(
            status == 200
            and isinstance(restored, dict)
            and restored.get("last_compiled_build_id")
            and draft_token in listed_tokens,
            "draft state did not survive restart",
        )
        _stop_cleanly(process, ready2)
        process = None
        with sqlite3.connect(database) as connection:
            marker = connection.execute("SELECT value FROM release_smoke_marker").fetchone()
        require(marker == ("keep-on-restart",), "second launch overwrote the user database")
        config = json.loads((user_root / "aa_config.json").read_text(encoding="utf-8"))
        require(Path(config["aa_data"]).resolve() == workspace.alternate_data.resolve(), "selected external path was not persisted")
        require(tree_digests(bundle) == bundle_before, "packaged bundle tree changed during smoke")
        require(tree_digests(workspace.root) == workspace_before, "runtime wrote into the synthetic external workspace")
        result.update({
            "ok": True,
            "check": check,
            "bundle": str(bundle),
            "user_data": str(user_root),
            "draft_token": draft_token,
            "console_errors": 0,
            "python_on_path": False,
        })
        return result
    except Exception as exc:
        if process is not None:
            if process.poll() is None:
                process.kill()
            stdout, stderr = process.communicate(timeout=10)
            process = None
            raise VerificationError(
                f"{exc}\npackaged stdout:\n{stdout[-8000:]}\n"
                f"packaged stderr:\n{stderr[-8000:]}"
            ) from exc
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        if not keep_temp:
            shutil.rmtree(scenario, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--selection", choices=("data", "install"), default="data")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(
            args.archive,
            selection_mode=args.selection,
            keep_temp=args.keep_temp,
            browser_check=not args.skip_browser,
        )
    except (OSError, ValueError, VerificationError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
