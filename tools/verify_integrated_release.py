"""Verify the actual integrated EXE in isolated state, including restart persistence."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_release import _start, _wait_ready, require  # noqa: E402
from tests.release_smoke import tree_digests, python_free_path  # noqa: E402


def request(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def verify(exe, screenshots=None, *, fresh_profile=False, working_directory=None):
    exe = Path(exe).resolve()
    before = tree_digests(exe.parent)
    with tempfile.TemporaryDirectory(prefix="HaloCue 发布验收 ") as temporary:
        root = Path(temporary)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("HALOCUE_")
            and key
            not in {
                "PYTHONPATH",
                "PYTHONHOME",
                "VIRTUAL_ENV",
                "ELECTRON_RUN_AS_NODE",
            }
        }
        env["PATH"] = python_free_path()
        if fresh_profile:
            profile = root / "另一位用户"
            local = profile / "AppData" / "Local"
            state = local / "HaloCue"
            env.update(
                USERPROFILE=str(profile),
                HOME=str(profile),
                LOCALAPPDATA=str(local),
                APPDATA=str(profile / "AppData" / "Roaming"),
            )
        else:
            state = root / "用户数据"
            env["HALOCUE_USER_DATA_DIR"] = str(state)
        cwd = Path(working_directory).resolve() if working_directory else root / "无关工作目录"
        cwd.mkdir(parents=True, exist_ok=True)
        work_id = None
        for iteration in range(2):
            ready = root / f"ready-{iteration}.json"
            process = _start(
                exe,
                ["--no-update", "--no-browser", "--port", "0", "--ready-file", str(ready)],
                env,
                cwd=cwd,
            )
            try:
                payload = _wait_ready(process, ready)
                require(
                    payload.get("interface") == "integrated",
                    "EXE did not open the integrated interface",
                )
                base = payload["url"]
                require(b"integration-shell.js" in request(base, "/"), "integrated page is missing")
                for path in (
                    "/writing-workbench.js",
                    "/production-embed.js",
                    "/integration-shell.js",
                    "/production/app.js",
                    "/production/app-embedded.js",
                ):
                    require(bool(request(base, path)), f"missing packaged resource: {path}")
                for path, identity in (
                    ("/api/v1/health", b"halocue-writing"),
                    ("/production/api/v1/health", b"halocue-production"),
                ):
                    require(identity in request(base, path), f"unhealthy service: {path}")
                health = json.loads(request(base, "/api/v1/health"))
                require(
                    health["ba_writing_skill"]["status"] == "ready",
                    "bundled writing rules are unavailable",
                )
                require(
                    (state / "integrated" / "writing").is_dir(),
                    "writing state is outside the selected profile",
                )
                require(
                    (state / "integrated" / "production").is_dir(),
                    "production state is outside the selected profile",
                )
                if iteration == 0:
                    created = json.loads(request(base, "/api/v1/works", {"title": "发布重启验收"}))
                    work_id = (
                        created["data"]["work"]["id"]
                        if "work" in created["data"]
                        else created["data"]["id"]
                    )
                else:
                    require(
                        work_id.encode() in request(base, "/api/v1/works"),
                        "work did not survive restart",
                    )
                if iteration == 0 and screenshots:
                    from playwright.sync_api import sync_playwright

                    output = Path(screenshots).resolve()
                    output.mkdir(parents=True, exist_ok=True)
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        page = browser.new_page(viewport={"width": 1360, "height": 860})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(base, wait_until="networkidle")
                        page.screenshot(path=str(output / "writing.png"), full_page=True)
                        page.goto(base + "/?section=production", wait_until="networkidle")
                        page.wait_for_function(
                            "document.querySelector('#productionModule')?.shadowRoot?.querySelector('.stage-sidebar')"
                        )
                        page.screenshot(path=str(output / "production.png"), full_page=True)
                        browser.close()
                        require(not errors, "packaged page JavaScript errors: " + str(errors))
                stop = urllib.request.Request(
                    base + "/integration/runtime/stop",
                    data=b"{}",
                    headers={
                        "X-HaloCue-Shutdown": payload["shutdown_token"],
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(stop, timeout=5) as response:
                    require(response.status == 200, "shutdown was not acknowledged")
                process.communicate(timeout=30)
                require(process.returncode == 0, f"unclean shutdown: {process.returncode}")
                require(not ready.exists(), "stale readiness file after exit")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=15)
        require(tree_digests(exe.parent) == before, "EXE wrote into its program directory")
    return {
        "ok": True,
        "interface": "integrated",
        "launches": 2,
        "work_persisted": True,
        "fresh_profile": fresh_profile,
        "unrelated_working_directory": cwd != exe.parent,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument(
        "--fresh-profile",
        action="store_true",
        help="use isolated LocalAppData without a HaloCue data override",
    )
    parser.add_argument("--working-directory", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                args.exe,
                args.screenshots,
                fresh_profile=args.fresh_profile,
                working_directory=args.working_directory,
            ),
            ensure_ascii=True,
        )
    )
