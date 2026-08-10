"""Protected localhost host for the reusable PC WebUI."""

from __future__ import annotations

import hmac
import json
import os
import shutil
import threading
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import assetdb
import aapaths
import model_profiles
import webui
from official_preview_index import OfficialPreviewIndex


_LOCK = threading.RLock()
_SERVER: ThreadingHTTPServer | None = None
_THREAD: threading.Thread | None = None
_SESSION_TOKEN = ""
_RUNTIME_SNAPSHOT: dict[str, object] | None = None

_EMPTY_RESOURCE_INDEX = {"bg": {}, "characters": {}, "sounds": []}
_ANDROID_ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".wav", ".ogg", ".mp3", ".skel", ".atlas",
}


_LEGACY_DATABASE_FILES = frozenset({
    "aa_assets.db", "aa_resources.json", "llm_profiles.json",
})
_LEGACY_CACHE_ROOTS = frozenset({"official-previews", "thumbs"})
_LEGACY_CACHE_SUFFIXES = frozenset({".json", ".png", ".jpg", ".jpeg", ".webp"})
_LEGACY_FILE_LIMIT = 20 * 1024 * 1024
_LEGACY_TOTAL_LIMIT = 100 * 1024 * 1024
_LEGACY_COUNT_LIMIT = 5000


def _safe_destination(target: Path, destination: Path) -> bool:
    current = destination
    while True:
        if current.is_symlink():
            return False
        if current == target:
            return True
        if target not in current.parents:
            return False
        current = current.parent


def _copy_legacy_tree(source: Path, target: Path, *, kind: str) -> None:
    if not source.is_dir():
        return
    copied_count = 0
    copied_bytes = 0
    for item in source.rglob("*"):
        if item.is_symlink():
            continue
        relative = item.relative_to(source)
        destination = target / relative
        if not item.is_file() or destination.exists():
            continue
        if kind == "databases":
            allowed = len(relative.parts) == 1 and relative.name in _LEGACY_DATABASE_FILES
        else:
            allowed = (
                bool(relative.parts)
                and relative.parts[0] in _LEGACY_CACHE_ROOTS
                and item.suffix.casefold() in _LEGACY_CACHE_SUFFIXES
            )
        if not allowed:
            continue
        size = item.stat().st_size
        if size > _LEGACY_FILE_LIMIT or copied_count >= _LEGACY_COUNT_LIMIT:
            continue
        if copied_bytes + size > _LEGACY_TOTAL_LIMIT:
            break
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not _safe_destination(target, destination.parent):
            continue
        shutil.copy2(item, destination)
        copied_count += 1
        copied_bytes += size


def _capture_runtime_snapshot() -> None:
    global _RUNTIME_SNAPSHOT
    if _RUNTIME_SNAPSHOT is not None:
        return
    names = (
        "HERE", "STORY_ROOT", "DB", "INDEX", "LLMCFG", "THUMBS",
        "MODEL_PROFILES", "OFFICIAL_PREVIEW_INDEX", "STORY_FILE_PICKER",
        "SETTINGS_FILE_PICKER", "ASSET_FILE_PICKER", "STORY_WORKSPACE",
        "HISTORY_ASSET_BROWSER",
    )
    _RUNTIME_SNAPSHOT = {
        "environment": {
            key: os.environ.get(key)
            for key in (
                "HALOCUE_PLATFORM", "HALOCUE_ANDROID_FILES_DIR",
                "HALOCUE_WORKSPACE_DIR",
            )
        },
        "webui": {name: getattr(webui, name) for name in names},
        "cfg": dict(webui.CFG),
    }


def _restore_runtime_snapshot() -> None:
    global _RUNTIME_SNAPSHOT
    snapshot = _RUNTIME_SNAPSHOT
    _RUNTIME_SNAPSHOT = None
    if snapshot is None:
        return
    for key, value in snapshot["environment"].items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    for name, value in snapshot["webui"].items():
        setattr(webui, name, value)
    webui.CFG.clear()
    webui.CFG.update(snapshot["cfg"])


def configure_android_runtime(workspace_dir: str) -> None:
    _capture_runtime_snapshot()
    root = Path(workspace_dir).resolve()
    workspace = root / "workspace"
    databases = workspace / "databases"
    cache = workspace / "cache"
    workspace.mkdir(parents=True, exist_ok=True)
    databases.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    _copy_legacy_tree(root / "databases", databases, kind="databases")
    _copy_legacy_tree(root / "cache", cache, kind="cache")
    os.environ["HALOCUE_PLATFORM"] = "android"
    os.environ["HALOCUE_ANDROID_FILES_DIR"] = str(root)
    os.environ["HALOCUE_WORKSPACE_DIR"] = str(workspace)
    runtime_paths = aapaths.detect()
    aa_data = Path(runtime_paths["data"])
    webui.HERE = str(Path(__file__).resolve().parent)
    webui.STORY_ROOT = str(root / "workspace")
    webui.DB = str(databases / "aa_assets.db")
    webui.INDEX = str(databases / "aa_resources.json")
    webui.LLMCFG = str(databases / "llm.json")
    webui.THUMBS = str(cache / "thumbs")
    index_path = Path(webui.INDEX)
    if not index_path.is_file():
        index_path.write_text(
            json.dumps(_EMPTY_RESOURCE_INDEX, ensure_ascii=False), encoding="utf-8"
        )
    webui.MODEL_PROFILES = model_profiles.ModelProfileStore(
        str(databases / "llm_profiles.json")
    )
    webui.OFFICIAL_PREVIEW_INDEX = OfficialPreviewIndex(cache / "official-previews")
    # Android receives documents through app-owned tokens, never host paths.
    uploads = cache / "picker-uploads"
    webui.STORY_FILE_PICKER = webui.StoryFilePicker(
        roots=(workspace,), upload_dir=uploads
    )
    webui.SETTINGS_FILE_PICKER = webui.StoryFilePicker(
        roots=(workspace,), upload_dir=uploads, allowed_suffixes=None
    )
    webui.ASSET_FILE_PICKER = webui.StoryFilePicker(
        roots=(workspace,), upload_dir=uploads, allowed_suffixes=_ANDROID_ASSET_SUFFIXES
    )
    webui.CFG.update({"overrides": None, "aa_data": str(aa_data), "spine_cli": None})
    webui.STORY_WORKSPACE = None
    webui.HISTORY_ASSET_BROWSER = None
    with webui.RESOURCE_INDEX_LOCK:
        webui.RESOURCE_INDEX_JOB.clear()
        webui.RESOURCE_INDEX_JOB.update(webui._empty_resource_index_job())
    with assetdb.connect(webui.DB) as connection:
        pass


class AndroidHandler(webui.H):
    session_token = ""

    def _request_path(self) -> str:
        return unquote(urlparse(self.path).path)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-HaloCue-Session", "")
        if not supplied:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookie.get("HaloCueSession")
            supplied = morsel.value if morsel else ""
        return bool(supplied) and hmac.compare_digest(supplied, self.session_token)

    def _guard_api(self) -> bool:
        if self._request_path().startswith("/api/") and not self._authorized():
            self._send(403, {"ok": False, "code": "invalid_session", "e": "会话已失效"})
            return False
        return True

    def _serve_root_with_cookie(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        supplied = query.get("session", [""])[0]
        if not hmac.compare_digest(supplied, self.session_token):
            return self._send(403, {"ok": False, "code": "invalid_session", "e": "会话已失效"})
        page = (Path(webui.HERE) / "ui.html").read_text(encoding="utf-8")
        return self._send(
            200,
            page,
            "text/html; charset=utf-8",
            {"Set-Cookie": f"HaloCueSession={self.session_token}; HttpOnly; SameSite=Strict; Path=/"},
        )

    def _capability_unavailable(self, capability: str) -> None:
        return self._send(
            501,
            {
                "ok": False,
                "code": f"{capability}_unavailable",
                "capability": capability,
                "e": f"{capability} is unavailable on Android",
            },
        )

    def do_GET(self):
        path = self._request_path()
        if path in ("/", "/index.html"):
            return self._serve_root_with_cookie()
        if not self._guard_api():
            return None
        if path == "/api/android/health":
            return self._send(200, {"ok": True, "runtime": "android-webui"})
        if path == "/api/install/options":
            return self._capability_unavailable("direct_aa_install")
        return super().do_GET()

    def do_POST(self):
        if not self._guard_api():
            return None
        path = self._request_path()
        if path in {"/api/install", "/api/settings/aa-install"}:
            return self._capability_unavailable("direct_aa_install")
        if path == "/api/settings/spine-cli":
            return self._capability_unavailable("spine_rendering")
        return super().do_POST()

    def do_PATCH(self):
        if not self._guard_api():
            return None
        return super().do_PATCH()

    def do_DELETE(self):
        if not self._guard_api():
            return None
        return super().do_DELETE()


def start(workspace_dir: str, session_token: str) -> dict[str, object]:
    global _SERVER, _THREAD, _SESSION_TOKEN
    with _LOCK:
        if _SERVER is not None:
            port = int(_SERVER.server_address[1])
            return {"port": port, "url": f"http://127.0.0.1:{port}/?{urlencode({'session': _SESSION_TOKEN})}", "ready": True}
        configure_android_runtime(workspace_dir)
        _SESSION_TOKEN = str(session_token)
        AndroidHandler.session_token = _SESSION_TOKEN
        _SERVER = ThreadingHTTPServer(("127.0.0.1", 0), AndroidHandler)
        _THREAD = threading.Thread(target=_SERVER.serve_forever, name="halocue-webui", daemon=True)
        _THREAD.start()
        port = int(_SERVER.server_address[1])
        return {"port": port, "url": f"http://127.0.0.1:{port}/?{urlencode({'session': _SESSION_TOKEN})}", "ready": True}


def stop() -> None:
    global _SERVER, _THREAD, _SESSION_TOKEN
    with _LOCK:
        server, thread = _SERVER, _THREAD
        _SERVER = None
        _THREAD = None
        _SESSION_TOKEN = ""
        AndroidHandler.session_token = ""
    if server is not None:
        server.shutdown()
        server.server_close()
    if thread is not None:
        thread.join(timeout=2)
    _restore_runtime_snapshot()
