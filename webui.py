# -*- coding: utf-8 -*-
"""
AA 剧本编译器 · 本地网页界面

  python webui.py

跑起来后浏览器打开 http://127.0.0.1:8770 。只监听本机，不对外。
只用标准库 + PIL（缩略图），不需要装框架。
"""
import argparse, hashlib, io, json, mimetypes, os, re, signal, socket, sys, tempfile, threading, traceback, uuid, webbrowser
from contextlib import ExitStack
from dataclasses import replace
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Any, Optional
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, unquote, urlencode

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from runtime_layout import LAYOUT, prepare_user_state                 # noqa: E402
from halocue_meta import APP_ID, VERSION                              # noqa: E402

RUNTIME_LAYOUT = LAYOUT

if LAYOUT.frozen:
    prepare_user_state(LAYOUT)
HERE = str(LAYOUT.resource_root)
STATE_DIR = str(LAYOUT.user_data_root)
OUT_DIR = str(LAYOUT.out_root)
CONFIG_PATH = LAYOUT.config_path
sys.path.insert(0, HERE)


def runtime_config_path():
    if RUNTIME_LAYOUT is not LAYOUT:
        return RUNTIME_LAYOUT.config_path
    return CONFIG_PATH if LAYOUT.frozen else Path(HERE) / "aa_config.json"

import aapaths                                                  # noqa: E402
import asset_catalog                                            # noqa: E402
import asset_import                                             # noqa: E402
import assetdb                                                  # noqa: E402


# ---------------------------------------------------------------- 繁转简（搜索用）
_ZH_T2S_CONV = None


def _zh_t2s(text: str) -> str:
    """繁体转简体。opencc 不可用时原样返回（搜索降级但不报错）。"""
    global _ZH_T2S_CONV
    if _ZH_T2S_CONV is None:
        try:
            from opencc import OpenCC
        except Exception:
            _ZH_T2S_CONV = False
        else:
            _ZH_T2S_CONV = OpenCC("t2s")
    if _ZH_T2S_CONV:
        try:
            return _ZH_T2S_CONV.convert(text)
        except Exception:
            return text
    return text


def _zh_search_match(query_raw: str, query_s: str, *fields: str) -> bool:
    """子串匹配：原始内容（大小写不敏感）或繁转简后内容（简体查询可命中繁体名）。"""
    for field in fields:
        value = str(field or "")
        if query_raw in value.casefold() or query_s in _zh_t2s(value).casefold():
            return True
    return False
import background_labeler                                      # noqa: E402
from aa_install_discovery import AADiscoveryResult, discover_aa  # noqa: E402
from aa_resource_cache import probe_resource_cache               # noqa: E402
from history_assets import HistoryAssetBrowser, HistoryAssetError  # noqa: E402
import background_workflow                                      # noqa: E402
import llm                                                      # noqa: E402
import model_capabilities                                       # noqa: E402
import model_profiles                                           # noqa: E402
import model_router                                             # noqa: E402
from director_state import SCENE_FUNCTIONS, SCENE_TYPES        # noqa: E402
from official_preview_index import (                             # noqa: E402
    OfficialPreviewIndex,
    PreviewIndexState,
)
import script2aap as S2A                                        # noqa: E402
import spine_face_analysis                                      # noqa: E402
import spine_face_labeler                                       # noqa: E402
from aa_project_assets import assert_aa_closed, validate_windows_path_component  # noqa: E402
from aa_registry import AssetRegistrationError, RegistrationConflictError  # noqa: E402
from build_index import build_resource_index, faces_of              # noqa: E402
from build_bundle import BuildBundleManager, CompileInputStaleError  # noqa: E402
from document import normalize_draft_nodes, parse_document_lossless  # noqa: E402
from draft_store import (                                       # noqa: E402
    DraftStore,
    InvalidDraftTokenError,
    ReviewPendingError,
    RevisionConflictError,
    normalize_annotation_status,
)
from install_manager import (  # noqa: E402
    InstallManager,
    AACorruptBundleError,
    AAInstallTargetExistsError,
    AARunningError,
)
from jobs import global_job_manager                             # noqa: E402
from picker_token import register_file_token, resolve_file_token  # noqa: E402
from story_file_picker import StoryFilePicker, StoryFilePickerError, windows_host_roots  # noqa: E402
from story_workspace import (                                  # noqa: E402
    StoryContext,
    StoryWorkspaceRegistry,
    normalize_bgm_policy,
    public_story_context,
    public_story_summary,
)

STORY_ROOT = STATE_DIR if LAYOUT.frozen else os.path.dirname(os.path.dirname(HERE))
BUILD_API_DEPRECATED = True
DB = str(LAYOUT.database_path)
INDEX = str(LAYOUT.resource_index_path)
LLMCFG = str(LAYOUT.llm_config_path)
MODEL_PROFILES = model_profiles.ModelProfileStore(
    LAYOUT.model_profiles_path
)
THUMBS = os.path.join(STATE_DIR, ".thumbs")
CHARACTER_CATALOG_METADATA = {"stamp": None, "items": {}}
OFFICIAL_PREVIEW_INDEX = OfficialPreviewIndex(
    LAYOUT.out_root / "official-previews"
)
STORY_FILE_PICKER = StoryFilePicker(
    roots=windows_host_roots(STORY_ROOT),
    upload_dir=os.path.join(OUT_DIR, "story-uploads"),
)
SETTINGS_FILE_PICKER = StoryFilePicker(
    roots=windows_host_roots(STORY_ROOT),
    upload_dir=os.path.join(OUT_DIR, "story-uploads"),
    allowed_suffixes=None,
)
ASSET_FILE_PICKER = StoryFilePicker(
    roots=windows_host_roots(STORY_ROOT),
    upload_dir=os.path.join(OUT_DIR, "story-uploads"),
    allowed_suffixes={
        ".png", ".jpg", ".jpeg", ".wav", ".ogg", ".mp3", ".skel", ".atlas",
    },
)

CFG = {"overrides": None, "aa_data": None, "spine_cli": None}
STORY_WORKSPACE = None
STORY_WORKSPACE_LOCK = threading.RLock()
HISTORY_ASSET_BROWSER = None
HISTORY_ASSET_BROWSER_LOCK = threading.RLock()
_DRAFT_TOKEN_BODY_PATHS = frozenset({
    "/api/review/approve",
    "/api/compile",
    "/api/install",
    "/api/cards/update",
    "/api/cards/insert",
    "/api/cards/move",
    "/api/draft/cast/update",
    "/api/review/reset",
    "/api/validate",
})

# 后台任务状态
JOB = {"running": False, "log": [], "done": False, "ok": False}
JOB_LOCK = threading.Lock()
BUILD_RESUME = None
BUILD_RESUME_LOCK = threading.RLock()
FACE_JOB = {
    "running": False,
    "done": False,
    "ok": False,
    "phase": "idle",
    "message": "",
    "current": None,
    "total": None,
    "log": [],
}
FACE_JOB_LOCK = threading.Lock()
RESOURCE_INDEX_LOCK = threading.RLock()
_STORY_TYPES = frozenset({"auto", "main", "event", "bond"})
_BUILTIN_VOICE_CHARACTERS = {
    "老师": "45145456",
    "teacher": "45145456",
    "sensei": "45145456",
}
_BUILTIN_VOICE_CHARACTER_CLUBS = {
    "老师": "夏莱",
    "teacher": "夏莱",
    "sensei": "夏莱",
}


def normalize_story_type(value: object) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized not in _STORY_TYPES:
        raise ValueError("invalid_story_type")
    return normalized


def _empty_resource_index_job() -> dict:
    return {
        "status": "not_built",
        "backgrounds": 0,
        "avatars": 0,
        "failed": 0,
    }


RESOURCE_INDEX_JOB = _empty_resource_index_job()


class StoryProjectMismatchError(ValueError):
    """The client tried to attach a story-scoped draft to another project."""


class InvalidProjectNameError(ValueError):
    """A client value is not a single valid Windows project component."""


def _story_workspace_index_path(aa_data: Path) -> Path:
    identity = os.path.normcase(str(aa_data.resolve())).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:16]
    return LAYOUT.out_root / "story-workspaces" / f"{digest}.json"


def _migrate_legacy_story_index(aa_data: Path, index_path: Path) -> None:
    legacy_path = aa_data / ".story-index.json"
    if index_path.is_file() or not legacy_path.is_file():
        return
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_name(f".{index_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(legacy_path.read_bytes())
        os.replace(temp_path, index_path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def story_workspace() -> StoryWorkspaceRegistry:
    """Return app-owned story state scoped to the configured AA data root."""
    global STORY_WORKSPACE
    aa_data = Path(CFG.get("aa_data") or (LAYOUT.out_root / "aa-data")).resolve()
    with STORY_WORKSPACE_LOCK:
        if STORY_WORKSPACE is None or STORY_WORKSPACE.aa_data != aa_data:
            index_path = _story_workspace_index_path(aa_data)
            _migrate_legacy_story_index(aa_data, index_path)
            STORY_WORKSPACE = StoryWorkspaceRegistry(
                index_path, aa_data=aa_data
            )
        return STORY_WORKSPACE


def history_asset_browser() -> HistoryAssetBrowser:
    """Return the server-local token registry for the configured AA data root."""
    global HISTORY_ASSET_BROWSER
    aa_data = Path(CFG.get("aa_data") or (LAYOUT.out_root / "aa-data")).resolve()
    with HISTORY_ASSET_BROWSER_LOCK:
        if HISTORY_ASSET_BROWSER is None or HISTORY_ASSET_BROWSER.aa_data != aa_data:
            HISTORY_ASSET_BROWSER = HistoryAssetBrowser(aa_data=aa_data)
        return HISTORY_ASSET_BROWSER


def _public_history_copy(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep current/history filesystem paths inside the server boundary."""
    return {
        "ok": True,
        "kind": result["kind"],
        "name": result["name"],
        "aa_key": result["aa_key"],
        "changed": result["changed"],
    }


_LIBRARY_COPY_ERROR_TEXT = {
    "invalid_story_token": ("当前剧情已失效。", "重新打开剧情后刷新素材工作台。"),
    "aa_running": ("AA 正在运行，当前不能写入素材。", "关闭 AA 后在原位置重试。"),
    "same_name_different_content": ("当前剧情中已有同名但内容不同的素材。", "修改素材名称或处理冲突后重试。"),
    "story_context_changed": ("素材工作台已切换到其他剧情。", "返回当前剧情后刷新素材工作台再试。"),
    "library_copy_mismatch": ("素材信息与当前副本不一致。", "刷新素材工作台后重新选择素材。"),
    "invalid_library_copy_token": ("素材副本已失效。", "刷新素材工作台后重试。"),
    "library_copy_missing": ("素材副本已不存在。", "刷新素材工作台后选择其他可用副本。"),
    "library_copy_changed": ("素材副本已变化。", "刷新素材工作台后重试。"),
    "history_source_missing": ("素材源文件已不存在。", "刷新素材工作台后重试。"),
    "history_asset_stale": ("素材源文件已变化。", "刷新素材工作台后重试。"),
    "validation_failed": ("素材未通过当前校验。", "处理素材文件后重新选择。"),
    "copy_confirmation_mismatch": ("确认的章节与素材副本不一致。", "刷新副本记录后重新确认。"),
    "asset_in_use": ("该素材仍被草稿引用，当前不能移除。", "先跳转到引用卡片并更换素材。"),
    "asset_remove_failed": ("素材副本未能安全移除。", "刷新副本记录并核对 AA 工程后重试。"),
    "invalid_preview_token": ("素材副本记录已失效。", "刷新素材工作台后重试。"),
}


def _library_copy_error(code: str) -> Dict[str, Any]:
    message, action = _LIBRARY_COPY_ERROR_TEXT.get(
        code, ("素材复制未完成。", "刷新素材工作台后重试。")
    )
    return {"ok": False, "code": code, "message": message, "action": action}


def _library_copy_management_error(exc: HistoryAssetError) -> Dict[str, Any]:
    payload = _library_copy_error(exc.code)
    payload["details"] = dict(exc.details)
    return payload


def _library_story_asset_card(payload: Dict[str, Any], *, kind: str, aa_key: Any) -> Dict[str, Any] | None:
    bucket = {"background": "backgrounds", "sound": "sounds", "character": "characters"}.get(kind)
    if not bucket:
        return None
    for card in payload.get(bucket, []):
        if str(card.get("aa_key")) == str(aa_key):
            return card
    return None


PUBLIC_VALIDATION_MESSAGES = {
    "file_missing": "素材文件不存在，请重新选择。",
    "image_unreadable": "图片无法读取，请重新选择有效的 PNG 或 JPEG 文件。",
    "unsupported_image_format": "图片格式不受支持，请使用 PNG 或 JPEG 文件。",
    "unsupported_color_mode": "图片颜色模式不受支持，请使用 RGB 或 RGBA 图片。",
    "probe_unavailable": "音频检测工具不可用，暂时无法验证该文件。",
    "audio_unreadable": "音频无法读取，请重新选择有效的音频文件。",
    "transcode_required": "音频需要转换为 PCM 16-bit WAV 后再导入。",
    "empty_name": "素材名称不能为空。",
    "name_conflict": "素材名称与当前剧情中的已有素材冲突。",
    "identifier_required": "角色 Identifier 为必填项。",
    "skel_count": "角色目录需要且只能包含一个 .skel 文件。",
    "atlas_missing": "角色缺少 .atlas 文件。",
    "texture_missing": "角色缺少贴图文件。",
    "avatar_missing": "角色缺少头像文件。",
}


def _public_validation_issue(issue: Any) -> Dict[str, str]:
    """Use fixed copy: validator/decoder details can include local paths."""
    raw = issue if isinstance(issue, dict) else {}
    code = str(raw.get("code") or "validation_failed")
    severity = str(raw.get("severity") or "error")
    if severity not in {"error", "warning"}:
        severity = "error"
    return {
        "code": code,
        "severity": severity,
        "message": PUBLIC_VALIDATION_MESSAGES.get(code, "素材校验未通过。"),
    }


def _public_story_metadata(kind: str, metadata: Any) -> Dict[str, Any]:
    """Expose only derived, browser-useful metadata from an import result."""
    source = metadata if isinstance(metadata, dict) else {}
    if kind == "background":
        allowed = ("width", "height", "mode", "format", "has_icc_profile")
        return {name: source[name] for name in allowed if name in source}
    if kind == "sound":
        allowed = ("codec", "sample_rate", "channels", "sample_fmt", "bits_per_sample", "duration")
        return {name: source[name] for name in allowed if name in source}
    if kind == "character":
        public = {
            name: source[name] for name in (
                "identifier", "faces", "expression_mode", "expression_status",
                "semantic_face_count", "spine_version", "spine_signature", "outfit_key",
            ) if name in source
        }
        raw_files = source.get("files")
        if isinstance(raw_files, dict):
            public["files"] = {
                name: Path(str(raw_files[name])).name
                for name in ("skel", "atlas", "texture", "avatar") if raw_files.get(name)
            }
        raw_pages = source.get("atlas_pages")
        if isinstance(raw_pages, list):
            public["atlas_pages"] = [Path(str(page)).name for page in raw_pages]
        return public
    return {}


def _public_face_analysis(result: Any) -> Dict[str, Any] | None:
    raw = result if isinstance(result, dict) else {}
    public = {
        name: raw[name] for name in ("status", "queued", "job_id") if name in raw
    }
    return public or None


def _public_background_analysis(result: Any) -> Dict[str, Any] | None:
    raw = result if isinstance(result, dict) else {}
    public = {
        name: raw[name] for name in ("status", "queued", "job_id") if name in raw
    }
    return public or None


def _public_story_asset_import(result: Dict[str, Any], context: StoryContext) -> Dict[str, Any]:
    """Explicit allowlist for picker-token import responses (never paths/details)."""
    kind = str(result.get("kind") or "")
    public: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "kind": kind or None,
        "stem": result.get("stem"),
        "aa_key": result.get("aa_key"),
        "sha256": result.get("sha256"),
        "metadata": _public_story_metadata(kind, result.get("metadata")),
        "issues": [_public_validation_issue(issue) for issue in (result.get("issues") or [])],
        "story_token": context.story_token,
        "project": context.project,
    }
    for name in ("status", "changed", "job_id"):
        if name in result:
            public[name] = result[name]
    analysis = _public_face_analysis(result.get("face_analysis"))
    if analysis is not None:
        public["face_analysis"] = analysis
    background_analysis = _public_background_analysis(result.get("background_analysis"))
    if background_analysis is not None:
        public["background_analysis"] = background_analysis
    return public


def open_story(file_token: str, project: Optional[str] = None) -> StoryContext:
    """Open a story from a server-issued file token, never a browser path."""
    realpath = resolve_file_token(str(file_token or ""))
    if not realpath or not Path(realpath).is_file():
        raise ValueError("invalid_file_token")
    try:
        return story_workspace().open_path(realpath, project=project)
    except ValueError as exc:
        raise InvalidProjectNameError(str(exc)) from exc


def resolve_story_context(story_token: str) -> StoryContext:
    if not story_token:
        raise ValueError("invalid_story_token")
    try:
        return story_workspace().resolve_story_token(story_token)
    except KeyError as exc:
        raise ValueError("invalid_story_token") from exc


def scan_story_inbox(context, *, con=None, running_probe=None):
    """创建当前剧情的「素材收件箱」并批量登记兼容文件。

    收件箱位于 <项目目录>/inbox 下：bgs / sounds / characters / bgms。
    用户把自定义素材放进对应子目录后点「素材文件夹」即可扫描登记；
    已登记的文件不会从收件箱删除，重复扫描会以 skipped/失败 形式反馈。
    """
    inbox = context.project_dir / "inbox"
    created = []
    for folder in ("bgs", "sounds", "characters", "bgms"):
        target = inbox / folder
        target.mkdir(parents=True, exist_ok=True)
        created.append(str(target))
    results: Dict[str, list] = {"registered": [], "skipped": [], "errors": []}
    plans = [
        ("bgs", "background"),
        ("sounds", "sound"),
        ("characters", "character"),
        ("bgms", "bgm"),
    ]
    for folder, kind in plans:
        target = inbox / folder
        if kind == "bgm":
            continue  # BGM 原生契约未完成，保持隐藏
        try:
            any_file = any(item.is_file() for item in target.iterdir())
        except OSError:
            any_file = False
        if not any_file:
            continue
        try:
            rows = asset_import.discover_assets(str(target))
        except Exception as exc:
            results["errors"].append({"kind": kind, "source": "", "message": f"扫描失败：{exc}"})
            continue
        for row in rows:
            if row["kind"] != kind:
                continue
            payload = {"kind": kind, "source": row["source"], "project_dir": str(context.project_dir)}
            label = str(row["stem"])
            if kind == "character":
                payload["identifier"] = row["stem"]
                payload["display_name"] = row["stem"]
            try:
                res = asset_import.register_asset_request(
                    payload, con=con,
                    saves_root=os.path.join(CFG["aa_data"], "saves"),
                    running_probe=running_probe,
                )
            except Exception as exc:
                results["errors"].append({"kind": kind, "source": label, "message": str(exc)})
                continue
            bucket = "registered" if res.get("status") == "registered" else "skipped"
            issue = ((res.get("issues") or [{}])[0] or {})
            results[bucket].append({
                "kind": kind, "name": label,
                "status": res.get("status"), "aa_key": res.get("aa_key"),
                "message": issue.get("message") or "",
            })
    return {"ok": True, "inbox": created, "results": results}


def inherit_story_context(payload: Dict[str, Any]) -> StoryContext | None:
    """Resolve a supplied story token and reject an inconsistent raw project."""
    story_token = payload.get("story_token")
    if not story_token:
        return None
    context = resolve_story_context(str(story_token))
    raw_project = str(payload.get("project") or "").strip()
    if raw_project and raw_project != context.project:
        raise StoryProjectMismatchError("project_mismatch")
    payload["project"] = context.project
    payload["story_token"] = context.story_token
    payload["bgm_policy"] = normalize_bgm_policy(context.bgm_default)
    return context


def _client_draft_token_for_post(path: str, payload: Dict[str, Any]):
    if path in _DRAFT_TOKEN_BODY_PATHS:
        return payload.get("token")
    if path.startswith("/api/proposals/") or path.startswith("/api/fixes/"):
        return payload.get("token")
    if path.startswith("/api/drafts/") and "/backgrounds/" in path:
        parts = [part for part in path.split("/") if part]
        return unquote(parts[2]) if len(parts) >= 3 else None
    return None


def _validate_client_draft_token(token: object) -> None:
    if token:
        DraftStore().get_draft_path(str(token))


def _invalid_draft_token_payload(exc: InvalidDraftTokenError) -> dict:
    return {"ok": False, "code": "invalid_draft_token", "e": str(exc)}


def jlog(msg):
    JOB["log"].append(str(msg))
    print(msg)


def reserve_build_job() -> bool:
    """Atomically reserve the singleton build worker before starting its thread."""
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, log=[], done=False, ok=False)
        return True


def face_job_snapshot() -> dict:
    """Return browser-safe face job progress without cache or source paths."""
    def public_text(value: Any, limit: int = 500) -> str:
        text = " ".join(str(value or "").split())[:limit]
        text = re.sub(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s;，。]+", "（本地路径已隐藏）", text)
        text = re.sub(r"(?<![\w])/(?:[^\s/]+/)+[^\s;，。]+", "（本地路径已隐藏）", text)
        return text

    with FACE_JOB_LOCK:
        raw = dict(FACE_JOB)
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    semantic_faces = []
    for item in result.get("semantic_faces") or []:
        if not isinstance(item, dict):
            continue
        semantic_faces.append({
            "face_id": public_text(item.get("face_id"), 32),
            "primary_emotion": public_text(item.get("primary_emotion"), 120),
            "semantic_labels": [
                public_text(label, 120) for label in (item.get("semantic_labels") or [])[:12]
            ],
        })
    public_result = {
        name: result[name]
        for name in (
            "rendered_count", "refreshed_preview_count", "render_cached",
            "vision_status", "labeled_count",
            "saved_count", "failed_count", "completed_at", "model",
        )
        if name in result
    }
    if "status" in result:
        public_result["status"] = public_text(result["status"], 32)
    failures = []
    for item in result.get("failures") or []:
        if not isinstance(item, dict):
            continue
        failures.append({
            "face_id": public_text(item.get("face_id"), 32),
            "error": public_text(item.get("error"), 160),
        })
    if failures:
        public_result["failures"] = failures[:100]
    for name in ("actual_workers", "fallback_workers"):
        try:
            value = int(result[name])
        except (KeyError, TypeError, ValueError):
            continue
        public_result[name] = min(4, max(0, value))
    retried_faces = result.get("retried_faces")
    if isinstance(retried_faces, (list, tuple)):
        public_result["retried_faces"] = [
            public_text(face_id, 32) for face_id in retried_faces[:100]
        ]
    calibration = []
    for item in result.get("calibration") or []:
        if not isinstance(item, dict):
            continue
        calibration.append({
            name: public_text(item.get(name), 160 if name == "reason" else 80)
            for name in ("face_id", "status", "attachment", "slot", "reason")
            if item.get(name) is not None
        })
    if calibration:
        public_result["calibration"] = calibration[:100]
    if semantic_faces:
        public_result["semantic_faces"] = semantic_faces
    return {
        "running": bool(raw.get("running")),
        "done": bool(raw.get("done")),
        "ok": bool(raw.get("ok")),
        "phase": str(raw.get("phase") or "idle"),
        "message": public_text(raw.get("message")),
        "current": raw.get("current"),
        "total": raw.get("total"),
        "ident": public_text(raw.get("ident"), 120),
        "outfit_key": public_text(raw.get("outfit_key"), 120),
        "log": [public_text(line) for line in (raw.get("log") or [])[-30:]],
        "result": public_result,
        "error": public_text(raw.get("error")) if raw.get("error") else None,
    }


def _public_visual_face(record: dict, *, aa_key: str, sha256: str) -> dict:
    face_id = str(record.get("face_id") or "")
    return {
        "face_id": face_id,
        "model": str(record.get("model") or ""),
        "ai": dict(record.get("ai") or {}),
        "manual": dict(record.get("manual") or {}),
        "effective": dict(record.get("effective") or {}),
        "reviewed": bool(record.get("reviewed")),
        "version": int(record.get("version") or 1),
        "updated_at": str(record.get("updated_at") or ""),
        "preview_url": "/api/assets/faces/preview?" + urlencode({
            "aa_key": str(aa_key), "sha256": str(sha256), "face_id": face_id,
            "v": int(record.get("version") or 1),
        }),
    }


def face_labels_payload(con, *, aa_key: str, sha256: str) -> dict:
    """Return browser-safe persisted labels for one exact registered skeleton."""
    target = asset_catalog.library_character_analysis_target(
        con, aa_key=aa_key, sha256=sha256
    )
    records = spine_face_labeler.list_visual_face_labels(
        con,
        ident=target["ident"],
        spine_signature=target["spine_signature"],
        outfit_key=target["outfit_key"],
    )
    return {
        "ok": True,
        "ident": target["ident"],
        "name": target["name"],
        "saved_count": len(records),
        "faces": [
            _public_visual_face(record, aa_key=str(aa_key), sha256=str(sha256))
            for record in records
        ],
    }


def update_face_label_payload(
    con,
    *,
    aa_key: str,
    sha256: str,
    face_id: str,
    patch: dict,
    expected_version: int,
) -> dict:
    """Save one manual override and return explicit database evidence."""
    target = asset_catalog.library_character_analysis_target(
        con, aa_key=aa_key, sha256=sha256
    )
    record = spine_face_labeler.update_visual_face_label(
        con,
        ident=target["ident"],
        spine_signature=target["spine_signature"],
        outfit_key=target["outfit_key"],
        face_id=face_id,
        patch=patch,
        expected_version=expected_version,
    )
    public = _public_visual_face(
        record, aa_key=str(aa_key), sha256=str(sha256)
    )
    return {
        "ok": True,
        "saved_count": 1,
        "saved_at": public["updated_at"],
        "face": public,
    }


def face_preview_path(con, *, aa_key: str, sha256: str, face_id: str) -> Path:
    """Resolve a persisted preview without exposing its server-side path."""
    target = asset_catalog.library_character_analysis_target(
        con, aa_key=aa_key, sha256=sha256
    )
    records = spine_face_labeler.list_visual_face_labels(
        con,
        ident=target["ident"],
        spine_signature=target["spine_signature"],
        outfit_key=target["outfit_key"],
    )
    record = next(
        (item for item in records if str(item.get("face_id")) == str(face_id)),
        None,
    )
    if record is None:
        raise KeyError("表情预览不存在")
    path = Path(str(record.get("head_path") or ""))
    if path.suffix.casefold() != ".png" or not path.is_file():
        raise KeyError("表情预览不存在")
    return path.resolve()


def _face_progress(phase, message, current=None, total=None):
    with FACE_JOB_LOCK:
        FACE_JOB.update(
            phase=phase,
            message=str(message),
            current=current,
            total=total,
        )
        FACE_JOB["log"].append(str(message))
    print(message)


def profile_provider(profile_id=None):
    name, settings = MODEL_PROFILES.provider_settings(profile_id)
    return llm.make_provider_from_settings(name, settings)


def annotation_provider(profile_id=None):
    state = MODEL_PROFILES.public_state()
    if state.get("schema_version") == 2 and state.get("models"):
        try:
            return model_router.ModelRouter(MODEL_PROFILES).text_provider()
        except model_profiles.ModelProfileError:
            return None
    selected = str(
        profile_id or state.get("active_profile_id") or ""
    )
    if not selected:
        return None
    return profile_provider(selected)


def _optional_vision_provider():
    """Return the configured provider only when its key is available."""
    state = MODEL_PROFILES.public_state()
    if state.get("schema_version") == 2 and state.get("models"):
        try:
            provider = model_router.ModelRouter(MODEL_PROFILES).vision_provider()
            return provider, None
        except model_profiles.ModelProfileError as exc:
            return None, str(exc)
    active = MODEL_PROFILES.active_profile()
    if active is not None:
        if not active.get("vision", True):
            return None, "当前模型配置未启用图片能力"
        try:
            return profile_provider(active["id"]), None
        except Exception as exc:
            return None, str(exc)
    try:
        cfg = json.load(open(LLMCFG, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"无法读取 llm.json：{exc}"
    name = str(cfg.get("provider") or "anthropic")
    if name != "mock":
        provider_cfg = cfg.get(name) or {}
        env_name = str(provider_cfg.get("api_key_env") or "").strip()
        if not env_name or not os.environ.get(env_name, "").strip():
            return None, f"未设置环境变量 {env_name or 'API_KEY'}"
    try:
        return llm.make_provider(LLMCFG), None
    except Exception as exc:
        return None, str(exc)


def _background_label_public_error(exc: Exception) -> str:
    message = str(exc or "背景识别失败").strip() or "背景识别失败"
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer|token|secret)\s*[=:]\s*[^\s,;]+",
        r"\1=已隐藏",
        message,
    )[:240]
    if re.search(r"(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+[\\/])", message):
        return "背景识别失败，请重试或手动补充"
    return message


def _model_public_error(exc: Exception) -> str:
    message = str(exc or "模型连接失败").strip() or "模型连接失败"
    message = re.sub(r"(?i)(api[_ -]?key|authorization|bearer|token|secret)\s*[:=]?\s*[^\s,;]+", r"\1=已隐藏", message)
    if re.search(r"(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+[\\/])", message):
        return "模型连接测试失败，请检查接口设置"
    return message[:240]


def background_label_worker(payload: dict) -> dict:
    """Label one registered background resolved only from immutable catalog identity."""
    identity = {
        "aa_key": str(payload.get("aa_key") or "").strip(),
        "sha256": str(payload.get("sha256") or "").strip(),
    }
    con = db()
    try:
        target = asset_catalog.library_background_analysis_target(con, **identity)
    finally:
        con.close()

    try:
        provider, provider_issue = _optional_vision_provider()
        if provider_issue or provider is None:
            raise RuntimeError(provider_issue or "当前没有可用的视觉模型")
        labels = background_labeler.label_background(provider, Path(target["source"]))
    except Exception as exc:
        public_error = _background_label_public_error(exc)
        con = db()
        try:
            asset_catalog.update_background_labels(
                con, **identity, labels=target.get("labels") or {},
                status="failed", error=public_error,
            )
        finally:
            con.close()
        raise

    con = db()
    try:
        saved = asset_catalog.update_background_labels(
            con, **identity, labels=labels, status="ready", error=""
        )
    finally:
        con.close()
    return {"ok": True, **saved}


def queue_background_label_analysis(payload: dict) -> dict:
    """Queue vision only after proving a registered server-side copy exists."""
    identity = {
        "aa_key": str(payload.get("aa_key") or "").strip(),
        "sha256": str(payload.get("sha256") or "").strip(),
    }
    con = db()
    try:
        target = asset_catalog.library_background_analysis_target(con, **identity)
        asset_catalog.update_background_labels(
            con, **identity, labels=target.get("labels") or {},
            status="labeling", error="",
        )
    finally:
        con.close()
    job_id = global_job_manager.submit(
        lambda job: background_label_worker(identity),
        label=f"background-label:{identity['aa_key']}",
        prefix="background-label-",
    )
    return {"status": "labeling", "queued": True, "job_id": job_id}


_CONNECTION_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def test_profile_connection(profile_id, mode="text"):
    provider = profile_provider(profile_id)
    mode = str(mode or "text").strip().lower()
    if mode == "text":
        provider.complete_json(
            "你是接口连通测试器，只返回符合 schema 的 JSON。",
            "",
            "请返回 ok=true。",
            _CONNECTION_SCHEMA,
        )
    elif mode == "vision":
        profile = MODEL_PROFILES.profile_record(profile_id)
        if not profile.get("vision", True):
            raise model_profiles.ModelProfileError(
                "当前模型配置未启用图片能力"
            )
        from PIL import Image

        image = Image.new("RGB", (48, 48), (70, 120, 220))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        provider.complete_json_vision(
            "你是图片接口连通测试器，只返回符合 schema 的 JSON。",
            [("connection-test", buffer.getvalue())],
            "图中存在一个纯色方块，请返回 ok=true。",
            _CONNECTION_SCHEMA,
        )
    else:
        raise model_profiles.ModelProfileError(
            "mode 必须是 text 或 vision"
        )
    return {
        "ok": True,
        "mode": mode,
        "model": str(getattr(provider, "model", "") or ""),
    }


def reserve_face_job(payload: dict) -> bool:
    with FACE_JOB_LOCK:
        if FACE_JOB["running"]:
            return False
        FACE_JOB.update(
            running=True,
            done=False,
            ok=False,
            phase="queued",
            message="已加入表情解析队列",
            current=0,
            total=None,
            log=["已加入表情解析队列"],
            ident=str(payload.get("ident") or ""),
            outfit_key=str(payload.get("outfit_key") or ""),
            result=None,
            error=None,
        )
        return True


def run_face_job(payload: dict):
    con = None
    try:
        con = db()
        provider, provider_issue = _optional_vision_provider()
        if provider_issue:
            provider_message = (
                "当前任务未读取到模型密钥；保存配置后请重新开始任务。"
                "本次仍会完成渲染和语义命名解析"
                if "API Key" in provider_issue or "密钥" in provider_issue
                else f"{provider_issue}；本次仍会完成渲染和语义命名解析"
            )
            _face_progress(
                "rendering",
                provider_message,
            )
        result = spine_face_analysis.analyze_character_faces(
            con,
            source_dir=payload["source"],
            ident=payload["ident"],
            spine_signature=payload.get("spine_signature") or "",
            outfit_key=payload.get("outfit_key") or "",
            spine_cli=payload["spine_cli"],
            cache_root=os.path.join(OUT_DIR, "spine-face-cache"),
            provider=provider,
            force_vision=bool(payload.get("force_vision")),
            progress=_face_progress,
            workers=4,
        )
        if provider_issue:
            result["provider_issue"] = provider_issue
        with FACE_JOB_LOCK:
            FACE_JOB.update(
                ok=True,
                phase=(
                    result.get("status")
                    if result.get("status") in {"complete", "partial"}
                    else "complete"
                ),
                result=result,
            )
    except Exception as exc:
        traceback.print_exc()
        with FACE_JOB_LOCK:
            FACE_JOB.update(
                phase="failed",
                message=f"表情解析失败：{exc}",
                error=str(exc),
            )
            FACE_JOB["log"].append(FACE_JOB["message"])
    finally:
        if con is not None:
            con.close()
        with FACE_JOB_LOCK:
            FACE_JOB.update(running=False, done=True)


def queue_face_analysis(payload: dict) -> dict:
    cli = spine_face_analysis.resolve_spine_cli(
        payload.get("spine_cli") or CFG.get("spine_cli")
    )
    if cli is None:
        return {
            "started": False,
            "status": "spine_cli_missing",
            "message": "人物已导入，但未找到 Spine 3.8 命令行程序；填写路径后可重新导入触发表情渲染",
        }
    task = {**payload, "spine_cli": str(cli)}
    if not reserve_face_job(task):
        return {
            "started": False,
            "status": "busy",
            "message": "人物已导入；另一个人物的表情正在后台解析",
        }
    threading.Thread(target=run_face_job, args=(task,), daemon=True).start()
    return {
        "started": True,
        "status": "queued",
        "spine_cli": str(cli),
        "message": "人物已导入，表情差分正在后台渲染",
    }


# ---------------------------------------------------------------- 数据访问
def db():
    return assetdb.connect(DB)


def _settings_values() -> dict[str, object]:
    config_path = runtime_config_path()
    if not config_path.is_file():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _current_aa_discovery() -> AADiscoveryResult:
    """Refresh AA's own paths without modifying the installed application."""
    config_path = runtime_config_path()
    values = _settings_values()
    configured_executable = str(values.get("aa_executable") or "").strip()
    configured_data = str(CFG.get("aa_data") or "").strip()
    if configured_executable:
        program = discover_aa(
            selection=configured_executable,
            config_path=config_path,
        )
        if not configured_data:
            return program
        try:
            same_data = (
                program.data is not None
                and os.path.normcase(str(program.data.resolve()))
                == os.path.normcase(str(Path(configured_data).resolve()))
            )
        except (OSError, ValueError):
            same_data = False
        if same_data:
            return program
        explicit = discover_aa(
            selection=configured_data,
            config_path=config_path,
        )
        return replace(
            explicit,
            executable=program.executable,
            install_root=program.install_root,
            identity=program.identity,
            local_low_root=program.local_low_root,
            resource_cache=explicit.resource_cache or program.resource_cache,
            catalog=program.catalog,
            recent_project_files=program.recent_project_files,
        )
    if configured_data:
        return discover_aa(selection=configured_data, config_path=config_path)
    return discover_aa(config_path=config_path)


def _preview_public_state(state: PreviewIndexState | dict | None) -> dict:
    if isinstance(state, PreviewIndexState):
        payload = {
            "status": state.status,
            "backgrounds": int(state.backgrounds),
            "avatars": int(state.avatars),
            "failed": int(state.failed),
        }
        if state.status == "building":
            payload.update(current=int(state.current), total=int(state.total))
        return payload
    if isinstance(state, dict):
        payload = {
            key: state[key]
            for key in ("status", "backgrounds", "avatars", "failed")
            if key in state
        }
        if state.get("status") == "building":
            payload.update(current=int(state.get("current", 0)), total=int(state.get("total", 0)))
        if state.get("status") == "failed":
            payload["action"] = "请检查 AA 资源包后重试索引"
        return payload
    return _empty_resource_index_job()


def _preview_state_for_discovery(discovery: AADiscoveryResult) -> PreviewIndexState:
    if discovery.catalog is None or discovery.resource_cache is None:
        return PreviewIndexState("not_built", 0, 0, 0, "")
    try:
        return OFFICIAL_PREVIEW_INDEX.state(discovery.catalog, discovery.resource_cache)
    except (OSError, ValueError, TypeError):
        return PreviewIndexState("stale", 0, 0, 0, "")


def _public_aa_status(
    discovery: AADiscoveryResult,
    preview_state: PreviewIndexState | dict | None = None,
) -> dict:
    executable = discovery.executable
    if executable is None:
        program = {"status": "missing", "path": ""}
    elif discovery.identity is None:
        program = {"status": "invalid", "path": str(executable)}
    else:
        program = {"status": "recognized", "path": str(executable)}
    projects = {
        "status": "ready" if discovery.projects is not None else "missing",
        "path": str(discovery.projects or ""),
    }
    saves = {
        "status": "ready" if discovery.saves is not None else "missing",
        "path": str(discovery.saves or ""),
    }
    if discovery.resource_cache is None:
        resource = {"status": "not_installed", "path": ""}
    else:
        probe = probe_resource_cache(discovery.resource_cache)
        resource = {"status": probe.status, "path": str(discovery.resource_cache)}
    index = _preview_public_state(preview_state or _preview_state_for_discovery(discovery))
    data = discovery.data or (Path(str(CFG.get("aa_data"))) if CFG.get("aa_data") else None)
    try:
        resource_index = {"exists": True, "stamp": os.stat(INDEX).st_mtime_ns}
    except OSError:
        resource_index = {"exists": False, "stamp": 0}
    return {
        "connected": bool(discovery.projects),
        "path": str(data or ""),
        "program": program,
        "projects": projects,
        "saves": saves,
        "resource": resource,
        "resource_index": resource_index,
        "preview_index": index,
    }


def _temporary_profile_provider(payload):
    """Build a provider from unsaved form values without persisting them."""
    profile = dict(payload or {})
    profile.setdefault("name", "临时测试")
    profile.setdefault("service_preset", "custom")
    profile.setdefault("max_tokens", 16000)
    profile.setdefault("vision", True)
    record = MODEL_PROFILES._validated(profile, profile_id="temporary")
    secret = str(profile.get("api_key") or "").strip()
    if not secret:
        raise model_profiles.ModelProfileError("临时测试配置尚未设置 API Key")
    provider_name = str(record["provider"])
    reasoning = model_capabilities.resolve_reasoning_capability(
        str(record["model"]),
        service_preset=str(record.get("service_preset") or "custom"),
    )
    return llm.make_provider_from_settings(provider_name, {
        "model": record["model"], "base_url": record["base_url"],
        "max_tokens": record["max_tokens"], "vision": record["vision"],
        "annotation_max_tokens": record.get("annotation_max_tokens", min(record["max_tokens"], 16000)),
        "reasoning_mode": record.get("reasoning_mode", "balanced"),
        "reasoning_wire_protocol": reasoning["wire_protocol"],
        "reasoning_budget_min": reasoning.get("budget_min"),
        "reasoning_budget_max": reasoning.get("budget_max"),
        "api_key": secret,
    })


def _temporary_connection_provider(connection_payload, model_payload):
    """Build one provider from redacted workbench records plus a submitted key."""
    connection = dict(connection_payload or {})
    connection.setdefault("name", "临时连接")
    connection.setdefault("service_preset", "custom")
    record = MODEL_PROFILES._validated_connection(
        connection, connection_id=str(connection.get("id") or "temporary")
    )
    secret = str(connection.get("api_key") or "").strip()
    if not secret and connection.get("id"):
        secret = str(MODEL_PROFILES.resolve_connection_key(connection["id"]) or "")
    if not secret:
        raise model_profiles.ModelProfileError("模型连接尚未设置 API Key")
    model = dict(model_payload or {})
    model_name = str(model.get("model") or "").strip()
    if not model_name:
        raise model_profiles.ModelProfileError("模型名称不能为空")
    annotation_max_tokens, _source = model_profiles.resolve_annotation_budget(model)
    reasoning = model_capabilities.resolve_reasoning_capability(
        model_name,
        service_preset=str(record.get("service_preset") or "custom"),
    )
    return llm.make_provider_from_settings(record["protocol"], {
        "model": model_name,
        "base_url": record["base_url"],
        "max_tokens": int(model.get("max_tokens") or 16000),
        "annotation_max_tokens": annotation_max_tokens,
        "context_window_tokens": model.get("context_window_tokens"),
        "context_window_source": model.get("context_window_source", "unknown"),
        "reasoning_mode": str(model.get("reasoning_mode") or "balanced"),
        "reasoning_wire_protocol": reasoning["wire_protocol"],
        "reasoning_budget_min": reasoning.get("budget_min"),
        "reasoning_budget_max": reasoning.get("budget_max"),
        "vision": model.get("vision_status") != "unsupported",
        "api_key": secret,
    })


def _saved_workbench_provider(model_id):
    model = MODEL_PROFILES.model_record(str(model_id or ""))
    connection = MODEL_PROFILES.connection_record(model["connection_id"])
    connection["api_key"] = MODEL_PROFILES.resolve_connection_key(connection["id"])
    return _temporary_connection_provider(connection, model), model


def test_workbench_model(model_id, mode):
    provider, model = _saved_workbench_provider(model_id)
    mode = str(mode or "text").strip().lower()
    try:
        if mode == "text":
            provider.complete_json(
                "你是接口连通测试器，只返回符合 schema 的 JSON。", "",
                "请返回 ok=true。", _CONNECTION_SCHEMA,
            )
        elif mode == "vision":
            if model.get("vision_status") == "unsupported":
                raise model_profiles.ModelProfileError("当前模型不支持图片能力")
            from PIL import Image
            image = Image.new("RGB", (48, 48), (70, 120, 220))
            buffer = io.BytesIO(); image.save(buffer, format="JPEG", quality=90)
            provider.complete_json_vision(
                "你是图片接口连通测试器，只返回符合 schema 的 JSON。",
                [("connection-test", buffer.getvalue())],
                "图中存在一个纯色方块，请返回 ok=true。", _CONNECTION_SCHEMA,
            )
        else:
            raise model_profiles.ModelProfileError("mode 必须是 text 或 vision")
    except Exception:
        if mode in {"text", "vision"}:
            MODEL_PROFILES.set_model_capability(model["id"], mode, "failed")
        raise
    MODEL_PROFILES.set_model_capability(model["id"], mode, "passed")
    return {"ok": True, "mode": mode, "model": str(getattr(provider, "model", "") or "")}


def _v1_fallback_connection(connection):
    connection = dict(connection or {})
    protocol = str(connection.get("protocol") or connection.get("provider") or "").lower()
    base_url = str(connection.get("base_url") or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if protocol != "openai" or not parsed.netloc or parsed.path not in {"", "/"}:
        return None
    connection["base_url"] = base_url + "/v1"
    return connection


def list_workbench_models(connection, model_payload):
    def discovered(provider, preset):
        list_records = getattr(provider, "list_model_records", None)
        if not callable(list_records):
            return provider.list_models()
        resolved = {}
        for record in list_records():
            if not isinstance(record, dict):
                continue
            model_id = str(record.get("id") or "").strip()
            if not model_id:
                continue
            registry_record = model_capabilities.registry_model_record(
                model_id, service_preset=str(preset or "custom"),
            )
            capability = model_capabilities.resolve_output_capability(
                model_id,
                service_preset=str(preset or "custom"),
                remote_record=record,
                registry_record=registry_record,
            )
            capability["reasoning"] = model_capabilities.resolve_reasoning_capability(
                model_id,
                service_preset=str(preset or "custom"),
                remote_record=record,
                registry_record=registry_record,
            )
            resolved[model_id] = capability
        return sorted(resolved.values(), key=lambda item: item["model_id"].casefold())

    provider = _temporary_connection_provider(connection, model_payload)
    try:
        return {
            "models": discovered(provider, connection.get("service_preset")),
        }
    except Exception:
        fallback = _v1_fallback_connection(connection)
        if fallback is None:
            raise
    provider = _temporary_connection_provider(fallback, model_payload)
    return {
        "models": discovered(provider, fallback.get("service_preset")),
        "base_url": fallback["base_url"],
        "base_url_adjusted": True,
    }


def current_model_status():
    public_state = getattr(MODEL_PROFILES, "public_state", None)
    if callable(public_state):
        try:
            state = public_state()
        except Exception:
            # A damaged optional credential provider must not make setup status
            # unusable: AA and bundled Spine discovery do not depend on it.
            return {"configured": False, "name": "", "model": ""}
        models = {str(row.get("id")): row for row in state.get("models", [])}
        connections = {
            str(row.get("id")): row for row in state.get("connections", [])
        }
        assignments = state.get("assignments") or {}
        base = models.get(str(assignments.get("base_model_id") or ""))
        if base:
            connection = connections.get(str(base.get("connection_id") or ""), {})
            result = {
                "configured": True,
                "name": str(connection.get("name") or ""),
                "model": str(base.get("model") or ""),
            }
            vision_mode = str(assignments.get("vision_mode") or "disabled")
            vision_id = assignments.get("base_model_id") if vision_mode == "base" else assignments.get("vision_model_id")
            vision = models.get(str(vision_id or "")) if vision_mode != "disabled" else None
            if vision:
                vision_connection = connections.get(
                    str(vision.get("connection_id") or ""), {}
                )
                result.update(
                    vision_name=str(vision_connection.get("name") or ""),
                    vision_model=str(vision.get("model") or ""),
                )
            return result
    active_profile = MODEL_PROFILES.active_profile()
    if active_profile:
        return {
            "configured": True,
            "name": str(active_profile.get("name") or ""),
            "model": str(active_profile.get("model") or ""),
        }
    return {"configured": False, "name": "", "model": ""}


def runtime_diagnostics() -> dict:
    """Return a secret-free support snapshot for the local setup screen."""
    config_path = runtime_config_path()
    values = _settings_values()
    discovery = _current_aa_discovery()
    resolved_spine = spine_face_analysis.resolve_spine_cli(
        CFG.get("spine_cli") or values.get("spine_cli"),
        config_path=config_path,
    )
    bundled_spine = None
    if LAYOUT.frozen:
        candidate = Path(sys.executable).resolve().parent / "tools" / "spine" / "Spine.com"
        bundled_spine = candidate.is_file()
    return {
        "version": VERSION,
        "user_config": {
            "found": config_path.is_file(),
            "aa_saved": bool(str(values.get("aa_data") or "").strip()),
        },
        "aa": {
            "connected": discovery.data is not None,
            "projects_ready": discovery.projects is not None and discovery.projects.is_dir(),
            "program_recognized": discovery.executable is not None,
            "source": discovery.source,
        },
        "spine": {
            "bundled": bundled_spine,
            "resolved": resolved_spine is not None,
        },
        "credentials": {
            "available": bool(getattr(MODEL_PROFILES.credentials, "available", False)),
        },
    }


def test_profile_payload(payload, mode="text"):
    provider = _temporary_profile_provider(payload)
    mode = str(mode or "text").strip().lower()
    if mode == "text":
        provider.complete_json(
            "你是接口连通测试器，只返回符合 schema 的 JSON。", "",
            "请返回 ok=true。", _CONNECTION_SCHEMA,
        )
    elif mode == "vision":
        if not bool(payload.get("vision", True)):
            raise model_profiles.ModelProfileError("当前模型配置未启用图片能力")
        from PIL import Image
        image = Image.new("RGB", (48, 48), (70, 120, 220))
        buffer = io.BytesIO(); image.save(buffer, format="JPEG", quality=90)
        provider.complete_json_vision(
            "你是图片接口连通测试器，只返回符合 schema 的 JSON。",
            [("connection-test", buffer.getvalue())],
            "图中存在一个纯色方块，请返回 ok=true。", _CONNECTION_SCHEMA,
        )
    else:
        raise model_profiles.ModelProfileError("mode 必须是 text 或 vision")
    return {"ok": True, "mode": mode, "model": str(getattr(provider, "model", "") or "")}


def setup_status():
    """Return non-sensitive readiness for the first-use UI and launcher."""
    discovery = _current_aa_discovery()
    with RESOURCE_INDEX_LOCK:
        job = dict(RESOURCE_INDEX_JOB)
    preview_state = job if job.get("status") in {"building", "failed"} else None
    database_ready = os.path.isfile(DB)
    stats = {}
    if database_ready:
        con = db()
        try:
            stats = {
                key: list(value)
                for key, value in assetdb.stats(con).items()
            }
        finally:
            con.close()
    model = current_model_status()
    config_path = runtime_config_path()
    configured_spine = str(CFG.get("spine_cli") or "").strip()
    if not configured_spine and config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                configured_spine = str(loaded.get("spine_cli") or "").strip()
        except (OSError, ValueError, TypeError):
            configured_spine = ""
    resolved_spine = spine_face_analysis.resolve_spine_cli(
        configured_spine or None, config_path=config_path
    )
    return {
        "aa": _public_aa_status(discovery, preview_state),
        "database": {
            "ready": database_ready,
            "stats": stats,
        },
        "model": model,
        "spine": {
            "configured": bool(resolved_spine),
            "path": configured_spine or str(resolved_spine or ""),
            "resolved_path": str(resolved_spine or ""),
        },
        "app_id": APP_ID,
        "version": VERSION,
        "entry_file": "启动AA自动写剧本.cmd",
    }


def _write_settings_config(**updates: str) -> None:
    config_path = runtime_config_path()
    values = _settings_values()
    for key, value in updates.items():
        if value:
            values[key] = value
        else:
            values.pop(key, None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _resource_index_snapshot(discovery: AADiscoveryResult | None = None) -> dict:
    with RESOURCE_INDEX_LOCK:
        current = dict(RESOURCE_INDEX_JOB)
    if current.get("status") == "not_built":
        current = _preview_public_state(
            _preview_state_for_discovery(discovery or _current_aa_discovery())
        )
    return {"ok": True, "preview_index": _preview_public_state(current)}


def _update_resource_index_job(state: PreviewIndexState | dict) -> None:
    public = _preview_public_state(state)
    with RESOURCE_INDEX_LOCK:
        RESOURCE_INDEX_JOB.clear()
        RESOURCE_INDEX_JOB.update(public)


def _resource_index_worker(discovery: AADiscoveryResult) -> None:
    try:
        result = OFFICIAL_PREVIEW_INDEX.build(
            discovery.catalog,
            discovery.resource_cache,
            progress=_update_resource_index_job,
        )
        _update_resource_index_job(result)
    except Exception:
        with RESOURCE_INDEX_LOCK:
            counts = {
                key: int(RESOURCE_INDEX_JOB.get(key, 0))
                for key in ("backgrounds", "avatars", "failed")
            }
            RESOURCE_INDEX_JOB.clear()
            RESOURCE_INDEX_JOB.update(status="failed", **counts)


def _start_resource_index() -> tuple[int, dict]:
    discovery = _current_aa_discovery()
    if discovery.catalog is None or discovery.resource_cache is None:
        return 409, {
            "ok": False,
            "code": "aa_resources_not_ready",
            "e": "请先识别 AA 程序并确认官方资源包已安装",
        }
    with RESOURCE_INDEX_LOCK:
        if RESOURCE_INDEX_JOB.get("status") == "building":
            return 409, {
                "ok": False,
                "code": "index_already_running",
                "e": "官方资源预览索引正在建立",
                "preview_index": _preview_public_state(RESOURCE_INDEX_JOB),
            }
        RESOURCE_INDEX_JOB.clear()
        RESOURCE_INDEX_JOB.update(
            status="building",
            backgrounds=0,
            avatars=0,
            failed=0,
            current=0,
            total=0,
        )
        snapshot = _preview_public_state(RESOURCE_INDEX_JOB)
    threading.Thread(
        target=_resource_index_worker,
        args=(discovery,),
        daemon=True,
    ).start()
    return 202, {"ok": True, "preview_index": snapshot}


RESOURCE_REBUILD_LOCK = threading.RLock()


def _build_resource_index_from(discovery: AADiscoveryResult) -> None:
    """用给定的发现结果重建 aa_resources.json（带锁防并发，已存在则跳过）。

    与「图片预览」解耦：不要求 resource_cache（资源文件）存在。
    失败时抛出带指引的 RuntimeError，由调用方转成业务错误。
    """
    if discovery.data is None:
        raise RuntimeError(
            "缺少资源索引文件（aa_resources.json），且未找到 AA 工作区。"
            "请先在设置中选择 AzureArchive.exe。"
        )
    try:
        with RESOURCE_REBUILD_LOCK:
            if os.path.isfile(INDEX):
                return
            build_resource_index(
                str(discovery.data),
                cache=str(discovery.resource_cache) if discovery.resource_cache else None,
                aa_install=str(discovery.install_root) if discovery.install_root else None,
                out=INDEX,
            )
    except Exception as exc:
        raise RuntimeError(f"资源索引自动建立失败：{exc}") from exc


def _ensure_resource_index() -> None:
    """缺索引时自动重建 aa_resources.json（先发现工作区）。失败抛带指引错误。"""
    if os.path.isfile(INDEX):
        return
    _build_resource_index_from(_current_aa_discovery())


def _trigger_resource_index_if_missing(discovery: AADiscoveryResult | None = None) -> None:
    """连接 AA 后自动触发：缺索引时后台重建（幂等，已存在则跳过）。

    传入调用方已得到的 discovery 可避免二次发现；缺省时自动发现。
    """
    if os.path.isfile(INDEX):
        return
    if discovery is None:
        try:
            discovery = _current_aa_discovery()
        except Exception:
            return
    if discovery.data is None:
        return
    threading.Thread(target=_build_resource_index_from, args=(discovery,), daemon=True).start()


def registered_character_avatar_path(con, ident: str) -> Path | None:
    """Resolve one imported character avatar without exposing its source path."""
    if not ident:
        return None
    asset_catalog.migrate(con)
    rows = con.execute(
        """SELECT install_path, metadata_json FROM asset_install
           WHERE kind='character' AND aa_key=? AND status='registered'
           ORDER BY scope""",
        (str(ident),),
    ).fetchall()
    for row in rows:
        metadata = asset_catalog._safe_metadata(row["metadata_json"])
        preview = asset_catalog._preview_path("character", row["install_path"], metadata)
        if preview:
            return preview
    return None


def character_catalog_metadata(ident: str) -> dict:
    """Return stable avatar metadata from the exported AA resource catalog."""
    if not ident:
        return {}
    try:
        stat = os.stat(INDEX)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    if CHARACTER_CATALOG_METADATA["stamp"] != stamp:
        items = {}
        try:
            payload = json.load(open(INDEX, encoding="utf-8"))
            for row in payload.get("characters", []):
                key = str(row.get("identifier") or "")
                if key and key not in items:
                    items[key] = {
                        "avatar": str(row.get("avatar") or ""),
                        "spine": str(row.get("spine") or ""),
                    }
        except (OSError, ValueError, TypeError):
            items = {}
        CHARACTER_CATALOG_METADATA["stamp"] = stamp
        CHARACTER_CATALOG_METADATA["items"] = items
    return CHARACTER_CATALOG_METADATA["items"].get(str(ident), {})


def list_characters(q="", limit=400):
    con = db()
    sql = ("SELECT c.ident, c.name, c.club, c.spine, c.avatar, c.source, "
           "  (SELECT COUNT(*) FROM face f WHERE f.ident=c.ident) AS nface "
           "FROM character c ")
    if q:
        # 带搜索词时全量拉取 + Python 统一过滤（原始匹配 ∪ 繁转简匹配），
        # 否则 SQL 先截断 400 行，繁体名（如“響”）永远进不了结果集。
        q_raw = str(q).casefold()
        q_s = _zh_t2s(q).casefold()
        alias_map = {}
        for row in con.execute("SELECT ident, script_name FROM name_alias"):
            alias_map.setdefault(row["ident"], []).append(row["script_name"])
        builtin_ids = [
            ident for script_name, ident, kind in assetdb.SEED_ALIAS
            if ident and kind == "portrait" and q_raw in script_name.casefold()
        ]
        builtin_names = set()
        if builtin_ids:
            placeholders = ",".join("?" for _ in builtin_ids)
            for row in con.execute(
                "SELECT name FROM character WHERE ident IN (" + placeholders + ")",
                builtin_ids,
            ):
                if row["name"]:
                    builtin_names.add(row["name"])
        rows = [dict(row) for row in con.execute(sql)]
        keep = []
        for r in rows:
            if _zh_search_match(
                q_raw, q_s, r["ident"], r["name"], r["club"],
                " ".join(alias_map.get(r["ident"], [])),
            ):
                keep.append(r)
            elif r["ident"] in builtin_ids or r["name"] in builtin_names:
                keep.append(r)
        # 与原 SQL 排序一致：(c.name IS NULL) ASC, nface DESC, c.ident ASC
        keep.sort(key=lambda r: (
            1 if r["name"] is None else 0,
            -(r["nface"] or 0),
            str(r["ident"]).casefold(),
        ))
        rows = keep[:limit]
    else:
        sql += "ORDER BY (c.name IS NULL), nface DESC, c.ident LIMIT ?"
        rows = [dict(row) for row in con.execute(sql, (limit,))]
    return [character_item(con, r) for r in rows]


def character_item(con, r) -> dict:
    """把 character 行转成 API 输出项（含目录元数据与头像路径）。"""
    catalog = character_catalog_metadata(r["ident"])
    avatar_value = str(r["avatar"] or catalog.get("avatar") or "")
    spine_value = str(r["spine"] or catalog.get("spine") or "")
    avatar_key = Path(
        avatar_value.replace("\\", "/")
    ).name or spine_value
    avatar = character_avatar_path(avatar_value, spine_value)
    if not avatar:
        avatar = registered_character_avatar_path(con, r["ident"])
    if avatar and not avatar_key:
        avatar_key = str(r["ident"])
    return {"ident": r["ident"], "name": r["name"] or r["ident"],
            "club": r["club"] or "", "spine": spine_value,
            "faces": r["nface"], "source": r["source"],
            "avatar": (
                "/thumb/av/" + quote(avatar_key, safe="")
                if avatar and avatar_key else ""
            )}
    def variant_rank(item):
        stem = str(item.get("spine") or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
        suffix = stem[len("characterspine_"):] if stem.startswith("characterspine_") else ""
        return (0 if suffix and "_" not in suffix else 2 if suffix.endswith(("_noweapon", "_n", "_nf")) else 1,
                str(item.get("ident") or "").casefold())
    out.sort(key=lambda item: (
        0 if str(item.get("source") or "").casefold() not in {"overrides", "custom", "current_story_custom"} else 1,
        variant_rank(item), str(item.get("name") or "").casefold(),
    ))
    return out


def list_backgrounds(
    q="", only_ready=False, limit=80, only_official=False, offset=0,
    with_total=False,
):
    con = db()
    if only_official:
        asset_catalog.migrate(con)
    try:
        page_limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        page_limit = 80
    try:
        page_offset = max(0, int(offset))
    except (TypeError, ValueError):
        page_offset = 0
    sql = "SELECT name,hash,label,place,time,mood,tags FROM bg "
    where, args = [], []
    if q:
        # 搜索词留到 Python 层过滤（含繁转简），SQL 只保留非文本条件
        q_raw = str(q).casefold()
        q_s = _zh_t2s(q).casefold()
    if only_ready:
        where.append("hash IS NOT NULL")
    if only_official:
        where.append(
            "NOT EXISTS (SELECT 1 FROM asset_install AS custom "
            "WHERE custom.kind='background' AND custom.status='registered' "
            "AND CAST(custom.aa_key AS TEXT)=CAST(bg.hash AS TEXT))"
        )
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    # 多取一些，在 Python 里按“有预览图 → 有标签 → 名称”重排，
    # 避免把无标签的哈希名（00000-*）顶到前面。
    sql += "ORDER BY (hash IS NULL), name"
    out = []
    for r in con.execute(sql, args):
        if q and not _zh_search_match(
            q_raw, q_s, r["name"], r["label"], r["place"],
            r["time"], r["mood"], r["tags"],
        ):
            continue
        out.append({"name": r["name"], "ready": r["hash"] is not None,
                    "label": r["label"] or "", "place": r["place"] or "",
                    "time": r["time"] or "", "mood": r["mood"] or "",
                    "tags": r["tags"] or "",
                    "img": _background_preview_available(r["name"])})
    out.sort(key=lambda item: (not item["img"], not bool(item["label"]), item["name"].casefold()))
    label_counts = {}
    for item in out:
        visible_name = " ".join(str(item["label"] or item["name"]).split()).casefold()
        label_counts[visible_name] = label_counts.get(visible_name, 0) + 1
    for item in out:
        visible_name = " ".join(str(item["label"] or item["name"]).split()).casefold()
        item["disambiguate"] = label_counts[visible_name] > 1
    total = len(out)
    items = out[page_offset:page_offset + page_limit]
    if not with_total:
        return items
    return {
        "items": items,
        "total": total,
        "offset": page_offset,
        "limit": page_limit,
        "has_more": page_offset + len(items) < total,
    }


_BGF = {}


def bg_files():
    if _BGF:
        return _BGF
    overrides = CFG.get("overrides")
    if not overrides:
        return _BGF
    root = os.path.join(overrides, "bgs")
    for dp, _, fns in os.walk(root):
        for fn in fns:
            stem, ext = os.path.splitext(fn)
            if ext.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                _BGF.setdefault(stem, os.path.join(dp, fn))
    return _BGF


def background_preview_path(name: str) -> Path | None:
    custom = bg_files().get(str(name))
    if custom and Path(custom).is_file():
        return Path(custom)
    return OFFICIAL_PREVIEW_INDEX.resolve("background", str(name))


def _background_preview_available(name: str) -> bool:
    return background_preview_path(name) is not None


def avatar_path(spine):
    overrides = CFG.get("overrides")
    if not spine or not overrides:
        return None
    p = os.path.join(overrides, spine.replace("\\", os.sep) + "-avatar.png")
    return p if os.path.exists(p) else None


def official_avatar_key_from_spine(spine: str) -> str:
    """Derive the indexed portrait key for a standard AA character spine."""
    stem = Path(str(spine or "").replace("\\", "/")).name
    match = re.fullmatch(r"CharacterSpine_(.+)", stem, flags=re.IGNORECASE)
    return "Student_Portrait_" + match.group(1) if match else ""


def character_avatar_path(avatar: str, spine: str) -> Path | None:
    custom = avatar_path(spine)
    if custom:
        return Path(custom)
    key = Path(str(avatar or "").replace("\\", "/")).name
    preview = OFFICIAL_PREVIEW_INDEX.resolve("avatar", key) if key else None
    if preview:
        return preview
    derived_key = official_avatar_key_from_spine(spine)
    return OFFICIAL_PREVIEW_INDEX.resolve("avatar", derived_key) if derived_key else None


def avatar_thumb(src, px, key):
    """Render character thumbnails without replacing transparent pixels with black."""
    from PIL import Image

    with Image.open(src) as source:
        has_alpha = "A" in source.getbands() or (
            source.mode == "P" and "transparency" in source.info
        )
        if not has_alpha:
            return thumb(src, px, key), "image/jpeg"
        image = source.convert("RGBA")
    os.makedirs(THUMBS, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", key)[:120]
    dst = os.path.join(THUMBS, f"{safe}_{px}.png")
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return open(dst, "rb").read(), "image/png"
    image.thumbnail((px, px), Image.LANCZOS)
    canvas = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((px - image.width) // 2, (px - image.height) // 2))
    image = canvas
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    data = buffer.getvalue()
    open(dst, "wb").write(data)
    return data, "image/png"


def thumb(src, px, key):
    os.makedirs(THUMBS, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", key)[:120]
    dst = os.path.join(THUMBS, f"{safe}_{px}.jpg")
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return open(dst, "rb").read()
    from PIL import Image
    im = Image.open(src)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80, optimize=True)
    data = buf.getvalue()
    open(dst, "wb").write(data)
    return data


# ---------------------------------------------------------------- 剧本分析
def _script_format_summary(lines: list[str], dialogue_lines: int,
                           directive_lines: int, scene_lines: int) -> dict:
    """Describe how reliably the rule parser can read one script.

    This is guidance for the browser, not a validation gate.  The AI preflight
    still receives the whole original text for every format.
    """
    meaningful = [line.strip() for line in lines if line.strip()]
    if not meaningful:
        return {
            "kind": "empty", "label": "空剧本", "confidence": "low",
            "message": "没有读到可分析的内容，请确认文件编码和内容。",
        }
    if dialogue_lines >= 2:
        kind = "aa_marked" if directive_lines or scene_lines else "dialogue"
        label = "AA 指令混合格式" if kind == "aa_marked" else "角色台词格式"
        return {
            "kind": kind, "label": label,
            "confidence": "high" if dialogue_lines >= 4 else "medium",
            "message": "已识别“角色：台词”结构；AI 会继续核对角色和素材。",
        }
    colon_lines = sum(
        1 for line in meaningful
        if re.match(r"^.{1,28}[：:]\s*\S+", line)
    )
    if colon_lines:
        return {
            "kind": "mixed", "label": "混合写作格式", "confidence": "medium",
            "message": "部分内容像角色台词，AI 将通读全文补充识别；请确认结果。",
        }
    return {
        "kind": "freeform", "label": "自由文本／非标准格式", "confidence": "low",
        "message": "未识别稳定的角色台词格式；AI 会按全文提取角色与素材，请逐项确认。",
    }


def analyze(path):
    """不依赖演员表，先把剧本里所有说话者抓出来。"""
    if not os.path.exists(path):
        return {"error": f"找不到文件: {path}"}
    speakers, scenes, nline, samples = {}, [], 0, {}
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    directive_lines = 0
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith("## "):
            scenes.append(s[3:].strip())
            continue
        if s.startswith("@"):
            directive_lines += 1
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("<"):
            continue
        m = S2A.HEAD_RE.match(s)
        if not m:
            continue
        head = m.group("head").strip()
        mm = S2A.ANNO_RE.match(head)
        who = (mm.group("who").strip() if mm else head) or head
        if len(who) > 14:
            continue
        speakers[who] = speakers.get(who, 0) + 1
        samples.setdefault(who, m.group("text").strip()[:40])
        nline += 1
    return {"path": path, "lines": nline,
            "scenes": scenes or ["（无场景标记）"],
            "speakers": [{"who": w, "n": n, "sample": samples.get(w, "")}
                         for w, n in sorted(speakers.items(), key=lambda x: -x[1])],
            "format": _script_format_summary(lines, nline, directive_lines, len(scenes))}


def is_non_character_speaker(value: str) -> bool:
    return str(value or "").strip().casefold() in {
        "旁白", "独白", "narration", "system", "系统", "系统消息"
    }


def voice_character_mapping(value: str) -> dict:
    """Create the stable AA slot-0 identity used by a named offscreen speaker."""
    name = str(value or "").strip()
    builtin = _BUILTIN_VOICE_CHARACTERS.get(name.casefold())
    ident = builtin or str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"halocue://voice-character/{name.casefold()}"
    ))
    return {"kind": "voice", "id": ident, "name": name, "spine": ""}


def _preferred_variant(con, row):
    if row is None or row["source"] == "overrides":
        return row
    siblings = con.execute(
        "SELECT ident,name,club,spine,source FROM character WHERE name=? AND source<>?",
        (row["name"], "overrides"),
    ).fetchall()
    if not siblings:
        return row
    def key(item):
        stem = str(item["spine"] or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
        suffix = stem[len("characterspine_"):] if stem.startswith("characterspine_") else ""
        return (0 if suffix and "_" not in suffix else 2 if suffix.endswith(("_noweapon", "_n", "_nf")) else 1,
                str(item["ident"] or "").casefold())
    return sorted(siblings, key=key)[0]


def guess_mapping(speakers):
    """给每个说话者猜一个 AA 角色。

    先做名字/标识的完全一致匹配（避免被垃圾别名或变体带偏，如「桃井」应命中
    用户自己导入的「桃井」而不是别名里的占位 ???）；退回学过的别名时同样跳过
    占位垃圾角色。用户始终可在“确认演员”一步手动修改对应关系。"""
    con = db()
    out = {}
    for sp in speakers:
        w = sp["who"]
        if is_non_character_speaker(w):
            out[w] = {"kind": "narrator"}
            continue
        if str(w).strip().casefold() in _BUILTIN_VOICE_CHARACTERS:
            out[w] = voice_character_mapping(w)
            continue
        # 1. 名字/标识完全一致。全局 overrides 里的服装变体仍需让已学习的
        # 官方本体映射优先；当前剧情自定义素材会在预检拿到 scope 后单独提升。
        row = con.execute(
            "SELECT ident,name,club,spine,source FROM character WHERE name=? OR ident=? "
            "ORDER BY (ident<>?), (spine IS NULL), LENGTH(ident) LIMIT 1",
            (w, w, w)).fetchone()
        exact_valid = row is not None and not assetdb._looks_placeholder(row["name"])
        if not exact_valid:
            # 1b. 繁转简匹配：官方繁体名（如「沙織」「陽葵」）对简体说话者（「沙织」「日鞠」）
            folded_s = _zh_t2s(w).casefold()
            if folded_s:
                for r in con.execute(
                    "SELECT ident,name,club,spine,source FROM character "
                    "WHERE name IS NOT NULL AND name != '' "
                    "ORDER BY (spine IS NULL), LENGTH(ident)"
                ):
                    if folded_s == _zh_t2s(r["name"]).casefold() or \
                       folded_s == _zh_t2s(r["ident"]).casefold():
                        row = r
                        exact_valid = not assetdb._looks_placeholder(r["name"])
                        break
        if exact_valid and row["source"] != "overrides":
            row = _preferred_variant(con, row)
            out[w] = {"kind": "portrait", "id": row["ident"],
                      "name": row["name"] or w, "club": row["club"] or "",
                      "spine": row["spine"] or ""}
            continue
        # 2. 学过的别名（portrait 别名已过滤占位垃圾）
        a = assetdb.best_alias(con, w)
        if exact_valid and a is not None and a["kind"] != "portrait":
            a = None
        if a:
            if a["kind"] == "narrator":
                out[w] = {"kind": "narrator"}
                continue
            crow = con.execute(
                "SELECT ident,name,club,spine,source FROM character WHERE ident=?",
                (a["ident"],),
            ).fetchone()
            if crow is not None and not assetdb._looks_placeholder(crow["name"]):
                crow = _preferred_variant(con, crow)
                out[w] = {"kind": a["kind"], "id": crow["ident"],
                          "name": w, "club": crow["club"] or "",
                          "spine": crow["spine"] or "",
                          "learned": True}
                continue
            # voice 角色可能没有名字（无头像的语音位），仍按语音映射
            if a["kind"] == "voice":
                out[w] = {"kind": "voice", "id": a["ident"],
                          "name": w, "club": "", "spine": "", "learned": True}
                continue
        if exact_valid:
            out[w] = {"kind": "portrait", "id": row["ident"],
                      "name": row["name"] or w, "club": row["club"] or "",
                      "spine": row["spine"] or ""}
            continue
        # AA slot 0 is not synonymous with narration. Preserve every named
        # speaker even when no portrait exists, so its display name survives.
        out[w] = voice_character_mapping(w)
    return out


def _story_custom_character_mapping(who: str, custom_assets: dict) -> dict | None:
    """Resolve one unambiguous current-story character variant by display name."""
    folded_who = str(who or "").strip().casefold()
    if not folded_who:
        return None
    exact = []
    variants = []
    for item in custom_assets.get("characters", []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        folded_name = name.casefold()
        base_name = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", name).strip().casefold()
        if folded_name == folded_who:
            exact.append(item)
        elif base_name == folded_who:
            variants.append(item)
    matches = exact or variants
    if len(matches) != 1:
        return None
    item = matches[0]
    return {
        "kind": "portrait",
        "id": str(item.get("aa_key") or ""),
        "name": str(who),
        "club": str(item.get("club") or ""),
        "spine": "",
        "source": "current_story_custom",
    }


_LEGACY_PREFLIGHT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "characters": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "speaker": {"type": "string"}, "kind": {"type": "string"},
                "id": {"type": "string"}, "name": {"type": "string"},
                "custom": {"type": "boolean"}, "confidence": {"type": "number"},
                "reason": {"type": "string"},
            }, "required": ["speaker", "kind", "id", "name", "custom", "confidence", "reason"]},
        },
        "assets": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "kind": {"type": "string"}, "name": {"type": "string"},
                "status": {"type": "string"}, "location": {"type": "string"},
                "reason": {"type": "string"},
            }, "required": ["kind", "name", "status", "location", "reason"]},
        },
        "usage_chain": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "segment": {"type": "string"}, "location": {"type": "string"},
                "start": {"type": "string"}, "end": {"type": "string"},
                "evidence": {"type": "string"},
                "needs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
                    "kind": {"type": "string"}, "name": {"type": "string"},
                    "location": {"type": "string"}, "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                    "candidates": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "aa_key": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["aa_key", "confidence", "reason"],
                    }},
                }, "required": ["kind", "name", "location", "reason", "confidence"]}},
            }, "required": ["segment", "location", "start", "end", "evidence", "needs"]},
        },
        "issues": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "severity": {"type": "string"}, "code": {"type": "string"},
                "message": {"type": "string"}, "action": {"type": "string"},
                "speaker": {"type": "string"},
            }, "required": ["severity", "code", "message", "action"]},
        },
    },
    "required": ["characters", "assets", "usage_chain", "issues"],
}


_PREFLIGHT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "extra_speakers": {
            "type": "array", "maxItems": 64,
            "items": {"type": "string", "maxLength": 28},
        },
        "scenes": {
            "type": "array", "maxItems": 160,
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "label": {"type": "string", "maxLength": 80},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
                "location": {"type": "string", "maxLength": 120},
                "time": {"type": "string", "maxLength": 40},
                "story_type": {"type": "string", "enum": list(SCENE_TYPES)},
                "scene_function": {"type": "string", "enum": list(SCENE_FUNCTIONS)},
                "needs": {"type": "array", "maxItems": 8, "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": ["background", "sound", "bgm"]},
                        "name": {"type": "string", "maxLength": 120},
                        "required": {"type": "boolean"},
                    },
                    "required": ["kind", "name", "required"],
                }},
            }, "required": [
                "label", "start_line", "end_line", "location", "time",
                "story_type", "scene_function", "needs",
            ]},
        },
        "ambiguities": {
            "type": "array", "maxItems": 80,
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "code": {"type": "string", "maxLength": 80},
                "line": {"type": "integer", "minimum": 0},
                "message": {"type": "string", "maxLength": 240},
            }, "required": ["code", "line", "message"]},
        },
    },
    "required": ["extra_speakers", "scenes", "ambiguities"],
}


def _compact_preflight_evidence(value: object, max_chars: int = 160) -> str:
    """Keep one reviewable source excerpt instead of echoing a whole scene."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    first_sentence = re.split(r"(?<=[。！？!?])\s*", text, maxsplit=1)[0].strip()
    excerpt = first_sentence or text
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip("，,。.!！？?；;：:、 ")
    if len(excerpt) < len(text):
        excerpt += "…"
    return excerpt


def _preflight_scene_evidence(
    lines: list[str], start_line: int, end_line: int, location: str, time_label: str,
) -> str:
    """Choose one short line that best supports the scene's place and time."""
    candidates = [
        re.sub(r"\s+", " ", raw).strip()
        for raw in lines[start_line - 1:end_line]
        if raw.strip()
    ]
    if not candidates:
        return ""
    anchor = re.sub(r"\s+", "", f"{location}{time_label}")
    anchor_pairs = {
        anchor[index:index + 2]
        for index in range(max(0, len(anchor) - 1))
        if re.search(r"[\u4e00-\u9fff]", anchor[index:index + 2])
    }

    def relevance(row: tuple[int, str]) -> tuple[float, int]:
        index, text = row
        compact = re.sub(r"\s+", "", text)
        pair_hits = sum(1 for pair in anchor_pairs if pair in compact)
        narrator_bonus = 2.0 if re.match(r"^(?:#+\s*)?(?:旁白|场景|地点|时间)[：:]", text) else 0.0
        opening_bonus = max(0.0, 3.0 - index * 0.2)
        return pair_hits * 2.0 + narrator_bonus + opening_bonus, -index

    _index, best = max(enumerate(candidates), key=relevance)
    return _compact_preflight_evidence(best)


def _compact_preflight_to_internal(value: dict, text: str) -> dict:
    """Expand the small AI contract into the existing backend/UI contract."""
    lines = text.splitlines()
    usage_chain = []
    for index, scene in enumerate((value.get("scenes") or [])[:160]):
        if not isinstance(scene, dict):
            continue
        try:
            start_line = max(1, int(scene.get("start_line") or 1))
            end_line = max(start_line, int(scene.get("end_line") or start_line))
        except (TypeError, ValueError):
            continue
        if lines:
            start_line = min(start_line, len(lines))
            end_line = min(end_line, len(lines))
        location = str(scene.get("location") or "位置未标注")
        time_label = str(scene.get("time") or "")
        evidence = _preflight_scene_evidence(
            lines, start_line, end_line, location, time_label,
        )
        needs = []
        for need in (scene.get("needs") or [])[:8]:
            if not isinstance(need, dict):
                continue
            kind = _PREFLIGHT_KIND_ALIASES.get(str(need.get("kind") or "").casefold())
            name = str(need.get("name") or "").strip()
            if not kind or not name:
                continue
            required = bool(need.get("required", kind == "background"))
            if kind == "background":
                reason = "场景地点与时间需要稳定的空间背景。"
            elif required:
                reason = "正文中有明确的声音演出线索。"
            else:
                reason = "用于强化当前场景氛围的可选演出。"
            needs.append({
                "kind": kind, "name": name, "location": f"第{start_line}行",
                "reason": reason, "confidence": 0.9 if required else 0.65,
                "required": required,
            })
        usage_chain.append({
            "segment": str(scene.get("label") or f"场景 {index + 1}"),
            "location": location,
            "start": f"第{start_line}行", "end": f"第{end_line}行",
            "evidence": evidence,
            "time": time_label,
            "scene_type": str(scene.get("story_type") or "other"),
            "scene_function": str(scene.get("scene_function") or "dialogue"),
            "needs": needs,
        })

    issues = []
    for ambiguity in (value.get("ambiguities") or [])[:80]:
        if not isinstance(ambiguity, dict):
            continue
        try:
            line = max(0, int(ambiguity.get("line") or 0))
        except (TypeError, ValueError):
            line = 0
        location = f"第{line}行：" if line else ""
        issues.append({
            "severity": "warning",
            "code": str(ambiguity.get("code") or "ai_ambiguity"),
            "message": location + str(
                ambiguity.get("message") or "有一处语义需要人工确认。"
            ),
            "action": "请核对原剧本含义后再确认初审。",
        })
    speakers = [{
            "speaker": str(speaker), "kind": "unset", "id": "", "name": "",
            "custom": False, "confidence": 0.0,
            "reason": "AI 从非标准写法的全文中发现，等待确认。",
        } for speaker in (value.get("extra_speakers") or [])[:64]]
    return {
        "characters": speakers,
        "assets": [],
        "usage_chain": usage_chain,
        "issues": issues,
    }


def _preflight_script_windows(text: str, max_lines: int = 240) -> list[dict]:
    """Split only long scripts at nearby natural boundaries, preserving source line ids."""
    lines = text.splitlines()
    if not lines:
        return [{"start_line": 1, "end_line": 1, "text": ""}]
    windows = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        if end < len(lines):
            lower = min(end, start + max(1, int(max_lines * 0.70)))
            boundaries = [
                index for index in range(lower, end)
                if not lines[index].strip()
                or lines[index].lstrip().startswith(("## ", "---"))
            ]
            if boundaries:
                end = boundaries[-1]
        if end <= start:
            end = min(len(lines), start + max_lines)
        numbered = "\n".join(
            f"L{index + 1}\t{lines[index]}"
            for index in range(start, end)
            if lines[index].strip()
        )
        windows.append({
            "start_line": start + 1, "end_line": end, "text": numbered,
        })
        start = end
    return windows


def _merge_preflight_internal(parts: list[dict]) -> dict:
    """Merge bounded preflight windows without multiplying duplicate model output."""
    characters, assets, scenes, issues = [], [], [], []
    seen_characters, seen_assets, seen_scenes, seen_issues = set(), set(), set(), set()
    for part in parts:
        for item in part.get("characters") or []:
            key = str(item.get("speaker") or "").strip().casefold()
            if key and key not in seen_characters and len(characters) < 64:
                characters.append(item)
                seen_characters.add(key)
        for item in part.get("assets") or []:
            key = (
                str(item.get("kind") or "").casefold(),
                str(item.get("name") or "").strip().casefold(),
            )
            if all(key) and key not in seen_assets:
                assets.append(item)
                seen_assets.add(key)
        for item in part.get("usage_chain") or []:
            key = (
                str(item.get("start") or ""), str(item.get("end") or ""),
                str(item.get("location") or "").casefold(),
            )
            if key not in seen_scenes and len(scenes) < 160:
                scenes.append(item)
                seen_scenes.add(key)
        for item in part.get("issues") or []:
            key = (str(item.get("code") or ""), str(item.get("message") or ""))
            if key not in seen_issues and len(issues) < 80:
                issues.append(item)
                seen_issues.add(key)
    scenes.sort(key=lambda item: int((re.search(r"\d+", str(item.get("start") or "")) or [0])[0]))
    return {
        "characters": characters, "assets": assets,
        "usage_chain": scenes, "issues": issues,
    }


def _preflight_character_library(con, speakers: list[dict], custom_assets: dict,
                                 baseline: dict, limit: int = 160) -> dict:
    """给 AI 提供相关角色候选，避免把 1000+ 全库塞进提示词。"""
    total = int(con.execute("SELECT COUNT(*) FROM character").fetchone()[0])
    custom_ids = {
        str(item.get("aa_key") or "").casefold()
        for item in custom_assets.get("characters", [])
    }
    candidates = {}

    def add(ident, name, club="", source=""):
        ident = str(ident or "").strip()
        if not ident or ident.casefold() in candidates or len(candidates) >= limit:
            return
        candidates[ident.casefold()] = {
            "id": ident,
            "name": str(name or ident),
            "club": str(club or ""),
            "custom": ident.casefold() in custom_ids,
            "source": "current_story_custom" if ident.casefold() in custom_ids else str(source or "library"),
        }

    for item in custom_assets.get("characters", []):
        add(item.get("aa_key"), item.get("name"), item.get("club", ""), source="current_story_custom")
    for mapping in baseline.values():
        ident = str(mapping.get("id") or "")
        if not ident:
            continue
        row = con.execute(
            "SELECT ident,name,club,source FROM character WHERE ident=? LIMIT 1", (ident,)
        ).fetchone()
        add(ident, row["name"] if row else mapping.get("name"),
            row["club"] if row else "", row["source"] if row else "library")
    for speaker in speakers:
        who = str(speaker.get("who") or "").strip()
        if not who:
            continue
        rows = con.execute(
            """
            SELECT ident,name,club,source FROM character
            WHERE ident LIKE ? OR name LIKE ? OR club LIKE ?
            ORDER BY (ident=? OR name=?) DESC, (name IS NULL), ident
            LIMIT 16
            """,
            (f"%{who}%", f"%{who}%", f"%{who}%", who, who),
        ).fetchall()
        for row in rows:
            if not assetdb._looks_placeholder(row["name"]):
                add(row["ident"], row["name"], row["club"], row["source"])
    return {"total": total, "candidates": list(candidates.values())}


def _preflight_background_library(con, limit: int = 800) -> list[dict]:
    """Expose usable AA backgrounds to the model without filesystem details."""
    asset_catalog.migrate(con)
    rows = con.execute(
        """
        SELECT official.name,official.label,official.place,official.time,
               official.mood,official.tags
        FROM bg AS official
        WHERE official.hash IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM asset_install AS custom
              WHERE custom.kind='background' AND custom.status='registered'
                AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
          )
        ORDER BY official.name
        """,
    ).fetchall()
    preview_keys = {
        str(row["name"])
        for row in rows
        if _background_preview_available(str(row["name"]))
    }
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        aa_key = str(row["name"] or "")
        if not aa_key:
            continue
        label = str(row["label"] or aa_key)
        time = str(row["time"] or "")
        group_key = (label.casefold(), time.casefold())
        item = {
            "aa_key": aa_key, "label": label,
            "place": str(row["place"] or ""), "time": time,
            "mood": str(row["mood"] or ""), "tags": str(row["tags"] or ""),
        }
        existing = grouped.get(group_key)
        if existing is None or (
            aa_key in preview_keys and existing["aa_key"] not in preview_keys
        ):
            grouped[group_key] = item
    library = sorted(
        grouped.values(),
        key=lambda item: (item["label"].casefold(), item["time"].casefold(), item["aa_key"].casefold()),
    )
    return library[:limit]


def _preflight_custom_background_library(custom_assets: dict) -> list[dict]:
    """Expose only labeled, story-scoped custom backgrounds without paths."""
    library: list[dict] = []
    for item in custom_assets.get("backgrounds", []):
        if not isinstance(item, dict):
            continue
        aa_key = str(item.get("aa_key") or "").strip()
        if not aa_key:
            continue
        labels = background_labeler.normalize_background_labels(item.get("labels"))
        if not any(labels.values()):
            continue
        name = str(item.get("name") or aa_key).strip()[:240] or aa_key
        library.append({
            "aa_key": aa_key,
            "label": labels["label"] or name,
            "name": name,
            **{field: labels[field] for field in (
                "description", "place", "indoor_outdoor", "time",
                "weather", "season", "mood", "tags",
            )},
            "source": "custom",
            "preview_available": bool(item.get("preview_available")),
        })
    return library


def _is_builtin_asset_ref(con, kind: str, name: str) -> bool:
    """内置素材不进入“本剧情自定义素材”清单，也不产生缺失错误。"""
    if kind == "bgm":
        return name.lstrip("-").isdigit()
    if kind == "background":
        asset_catalog.migrate(con)
        row = con.execute(
            """SELECT 1 FROM bg AS official
               WHERE official.hash IS NOT NULL
                 AND (official.name=? OR official.label=?)
                 AND NOT EXISTS (
                     SELECT 1 FROM asset_install AS custom
                     WHERE custom.kind='background' AND custom.status='registered'
                       AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
                 )
               LIMIT 1""",
            (name, name),
        ).fetchone()
        return row is not None
    if kind == "sound":
        row = con.execute(
            "SELECT 1 FROM sound WHERE name=? OR label=? LIMIT 1", (name, name)
        ).fetchone()
        return row is not None
    return False


def _preflight_asset_refs(text: str, custom_assets: dict, con) -> list[dict]:
    """提取剧本中的素材指令，并只与当前剧情自定义素材比对。"""
    patterns = re.compile(r"^\s*@(?P<cmd>bg|se|sound|bgm|music)\s+(?P<arg>.+?)\s*$", re.I)
    seen = set()
    refs = []
    kind_map = {"bg": "background", "se": "sound", "sound": "sound", "bgm": "bgm", "music": "bgm"}
    for line_no, raw in enumerate(text.splitlines(), 1):
        match = patterns.match(raw)
        if not match:
            continue
        cmd = match.group("cmd").casefold()
        name = match.group("arg").strip().strip('"\'')
        key = (kind_map[cmd], name.casefold())
        if not name or key in seen:
            continue
        seen.add(key)
        bucket = custom_assets.get({"background": "backgrounds", "sound": "sounds", "bgm": "bgms"}[key[0]], [])
        found = next((item for item in bucket if str(item.get("name") or "").casefold() == name.casefold()
                      or str(item.get("aa_key") or "").casefold() == name.casefold()), None)
        if not found and _is_builtin_asset_ref(con, key[0], name):
            continue
        refs.append({
            "kind": key[0], "name": name,
            "status": "registered" if found else "missing",
            "location": "第%d行" % line_no,
            "reason": "已登记到当前剧情" if found else "未在当前剧情自定义素材中登记",
            "detected_by": "directive",
        })
    return refs


_PREFLIGHT_KIND_ALIASES = {
    "bg": "background", "background": "background",
    "se": "sound", "sound": "sound", "sfx": "sound",
    "bgm": "bgm", "music": "bgm",
}


def _compact_timeline_marker(value: object, max_chars: int = 32) -> str:
    """Keep AI-provided scene boundaries useful without turning them into dialogue blocks."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip("，,。.!！？?；;：:、 ") + "…"


def _safe_ai_error(exc: Exception) -> str:
    """Keep model diagnostics useful without echoing secrets or huge payloads."""
    message = str(exc or "AI 调用失败").strip() or "AI 调用失败"
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer|token|secret)\s*[=:]\s*[^\s,;]+",
        r"\1=已隐藏",
        message,
    )
    return message[:500]


def _background_generation_prompt(name: str, reason: str, evidence: str, location: str) -> str:
    """Create an editable provider-neutral prompt for one missing background."""
    detail = reason or "根据剧情场景补足背景。"
    source = evidence or location or "当前场景"
    return (
        "请生成一张用于剧情演出的二次元游戏背景图。\n"
        f"场景：{name}\n"
        f"场景证据：{source}\n"
        f"补充要求：{detail}\n"
        "构图要求：横向 16:9，保持清晰的环境空间关系，保留角色站位和对白区域。\n"
        "画面质量：清晰干净的游戏背景原画，自然材质细节，低噪点、无颗粒、无胶片噪声、"
        "无色带、无 JPEG 压缩伪影、无过度锐化、无脏污纹理、无模糊重影。\n"
        "排除内容：人物、文字、水印、UI、对白框、Logo 和边框。"
    )


_BACKGROUND_CATALOG_PLACE_HINTS = (
    (("商店街", "商业街", "购物街"), (("shopping", 5.0), ("district", 2.0))),
    (("教室", "课堂"), (("classroom", 5.0), ("school", 1.0))),
    (("车站", "站台", "候车厅", "火车站"), (("station", 5.0), ("train", 2.0), ("platform", 2.0))),
    (("公交站", "巴士站", "汽车站"), (("bus", 4.0), ("station", 3.0))),
    (("天台", "屋顶"), (("rooftop", 5.0), ("roof", 3.0))),
    (("公园",), (("park", 5.0),)),
    (("办公室", "办事处"), (("office", 5.0),)),
    (("咖啡馆", "咖啡厅", "咖啡店"), (("cafe", 5.0), ("coffee", 3.0))),
    (("餐厅", "食堂", "饭店"), (("restaurant", 5.0), ("cafeteria", 5.0), ("dining", 3.0))),
    (("医院", "医务室"), (("hospital", 5.0), ("medical", 3.0), ("clinic", 3.0))),
    (("图书馆", "阅览室"), (("library", 5.0),)),
    (("体育馆", "健身房", "训练场"), (("gym", 5.0), ("training", 3.0), ("stadium", 3.0))),
    (("游泳池", "泳池"), (("pool", 5.0), ("swimming", 3.0))),
    (("海滩", "沙滩", "海边"), (("beach", 5.0), ("seaside", 3.0))),
    (("街道", "大街", "巷道", "小巷"), (("street", 5.0), ("alley", 4.0))),
    (("走廊", "廊道"), (("corridor", 5.0), ("hallway", 5.0))),
    (("宿舍", "寝室"), (("dorm", 5.0), ("dormitory", 5.0))),
    (("礼堂", "会堂", "剧场"), (("auditorium", 5.0), ("theater", 4.0), ("stage", 2.0))),
    (("仓库",), (("warehouse", 5.0),)),
    (("博物馆", "美术馆"), (("museum", 5.0), ("gallery", 4.0))),
    (("广场",), (("plaza", 5.0), ("square", 4.0))),
    (("森林", "树林"), (("forest", 5.0), ("woods", 4.0))),
    (("神社", "寺庙", "寺院"), (("shrine", 5.0), ("temple", 5.0))),
    (("校门", "学校门口", "校园入口"), (("school", 3.0), ("front", 3.0), ("gate", 4.0))),
    (("社团室", "活动室", "部室"), (("club", 4.0), ("room", 3.0))),
)

_BACKGROUND_CATALOG_MODIFIER_HINTS = (
    (("夜晚", "晚上", "夜间", "深夜", "当晚"), (("night", 2.5),)),
    (("黄昏", "傍晚", "夕阳", "日落"), (("sunset", 2.5), ("evening", 2.0))),
    (("黎明", "清晨", "拂晓"), (("dawn", 2.5), ("morning", 1.5))),
    (("雨天", "下雨", "雨夜", "暴雨"), (("rain", 2.0), ("rainy", 2.0))),
    (("雪天", "下雪", "雪夜"), (("snow", 2.0), ("snowy", 2.0))),
    (("夏莱", "沙勒", "schale"), (("schale", 3.0), ("main", 1.5))),
    (("阿拜多斯", "abydos"), (("abydos", 3.0),)),
    (("崔尼蒂", "trinity"), (("trinity", 3.0),)),
    (("格黑娜", "gehenna"), (("gehenna", 3.0),)),
    (("千年", "millennium"), (("millennium", 3.0),)),
    (("百鬼夜行", "hyakkiyako"), (("hyakkiyako", 3.0),)),
)

_BACKGROUND_TIME_ALIASES = {
    "night": ("夜晚", "晚上", "夜间", "深夜", "当晚", "雨夜", "雪夜"),
    "sunset": ("黄昏", "傍晚", "夕阳", "日落"),
    "dawn": ("黎明", "清晨", "拂晓"),
    "day": ("白天", "上午", "中午", "下午", "日间"),
}

_BACKGROUND_INDOOR_ALIASES = (
    "室内", "屋内", "房内", "店内", "内部", "里面", "房间", "大厅", "办公室",
)
_BACKGROUND_OUTDOOR_ALIASES = (
    "室外", "户外", "街上", "街道", "商店街", "商业街", "购物街", "路边",
    "门外", "门口", "广场", "公园", "天台", "海滩", "沙滩",
)
_BACKGROUND_INDOOR_TERMS = ("inside", "interior", "room", "office", "hall", "corridor", "lobby")
_BACKGROUND_OUTDOOR_TERMS = ("outside", "outdoor", "street", "district", "park", "plaza", "rooftop", "beach")


def _catalog_background_candidates(con, *context: str, limit: int = 3) -> list[dict]:
    """Suggest official approximations only after an explicit place match."""
    query = " ".join(str(value or "") for value in context).casefold()
    place_groups: list[tuple[tuple[str, float], ...]] = []
    for aliases, terms in _BACKGROUND_CATALOG_PLACE_HINTS:
        if any(alias.casefold() in query for alias in aliases):
            place_groups.append(terms)
    if not place_groups:
        return []

    modifier_weights: dict[str, float] = {}
    for aliases, terms in _BACKGROUND_CATALOG_MODIFIER_HINTS:
        if any(alias.casefold() in query for alias in aliases):
            for term, weight in terms:
                modifier_weights[term] = max(modifier_weights.get(term, 0.0), weight)
    requested_times = {
        name for name, aliases in _BACKGROUND_TIME_ALIASES.items()
        if any(alias.casefold() in query for alias in aliases)
    }
    requested_space = (
        "indoor" if any(alias in query for alias in _BACKGROUND_INDOOR_ALIASES)
        else "outdoor" if any(alias in query for alias in _BACKGROUND_OUTDOOR_ALIASES)
        else ""
    )

    rows = con.execute(
        """SELECT official.name,official.label,official.place,official.time,
                  official.mood,official.tags
           FROM bg AS official
           WHERE official.hash IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM asset_install AS custom
                 WHERE custom.kind='background' AND custom.status='registered'
                   AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
             )""",
    ).fetchall()
    ranked: list[tuple[float, str, dict]] = []
    for row in rows:
        name = str(row["name"] or "")
        if not name:
            continue
        searchable = " ".join(str(row[field] or "").casefold() for field in (
            "name", "label", "place", "time", "mood", "tags",
        ))
        if requested_space == "outdoor" and any(term in searchable for term in _BACKGROUND_INDOOR_TERMS):
            continue
        if requested_space == "indoor" and any(term in searchable for term in _BACKGROUND_OUTDOOR_TERMS):
            continue
        place_score = max(
            sum(weight for term, weight in terms if term in searchable)
            for terms in place_groups
        )
        if place_score <= 0:
            continue
        candidate_times = {
            key for key in ("night", "sunset", "dawn") if key in searchable
        }
        if "day" in requested_times and candidate_times:
            continue
        if "night" in requested_times and candidate_times & {"sunset", "dawn"}:
            continue
        if "sunset" in requested_times and candidate_times & {"night", "dawn"}:
            continue
        if "dawn" in requested_times and candidate_times & {"night", "sunset"}:
            continue
        modifier_score = sum(
            weight for term, weight in modifier_weights.items() if term in searchable
        )
        score = place_score + modifier_score
        ranked.append((score, name.casefold(), {
            "aa_key": name,
            "label": str(row["label"] or name),
            "source": "official",
            "preview_source": "official",
            # A local fallback is deliberately never strong enough to auto-apply.
            "confidence": min(0.74, 0.52 + place_score * 0.025 + modifier_score * 0.02),
            "reason": "根据明确地点类别检索；时间、天气和学校信息只用于同类背景排序。",
            "preview_available": _background_preview_available(name),
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict] = []
    seen_labels: set[str] = set()
    for _score, _name, candidate in ranked:
        label_key = candidate["label"].casefold()
        if label_key in seen_labels:
            continue
        seen_labels.add(label_key)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


_CUSTOM_BACKGROUND_BROAD_PLACE_TOKENS = {
    "场景", "背景", "地点", "附近", "周边", "街道", "街上", "室内", "室外",
    "户外", "屋内", "房间", "建筑", "城市", "校园", "学校", "商店街", "商业街",
    "购物街", "白天", "上午", "中午", "下午", "傍晚", "黄昏", "夜晚", "晚上",
    "晴天", "雨天", "安静", "热闹", "轻松", "紧张",
}

_CUSTOM_BACKGROUND_PLACE_ALIASES = (
    ("游戏中心", "电玩城", "街机厅"),
    ("可丽饼摊", "薄饼摊"),
    ("天台", "屋顶"),
    ("咖啡馆", "咖啡厅", "咖啡店"),
    ("餐厅", "食堂", "饭店"),
    ("教室", "课堂"),
    ("办公室", "办事处"),
    ("车站", "站台", "候车厅"),
    ("河堤", "河岸", "堤岸"),
    ("公园",),
    ("图书馆", "阅览室"),
    ("体育馆", "健身房", "训练场"),
    ("海滩", "沙滩", "海边"),
)


def _custom_background_place_tokens(item: dict) -> list[tuple[str, float]]:
    tokens: dict[str, float] = {}
    for field, weight in (("label", 5.0), ("name", 4.5), ("place", 4.0), ("tags", 2.5)):
        value = str(item.get(field) or "").casefold()
        if field == "name":
            value = os.path.splitext(value)[0]
        for part in re.split(r"[,，、;/|\s]+", value):
            token = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "", part)
            if len(token) < 2 or token in _CUSTOM_BACKGROUND_BROAD_PLACE_TOKENS:
                continue
            tokens[token] = max(tokens.get(token, 0.0), weight)
    return list(tokens.items())


def _custom_background_candidates(custom_backgrounds: dict, *context: str, limit: int = 3) -> list[dict]:
    """Rank custom backgrounds only after a concrete place match."""
    query = " ".join(str(value or "") for value in context).casefold()
    if not query:
        return []
    ranked = []
    for item in custom_backgrounds.values():
        searchable = " ".join(
            str(item.get(field) or "")
            for field in ("aa_key", "label", "name", "description", "place", "time", "mood", "tags")
        ).casefold()
        requested_space = (
            "indoor" if any(alias in query for alias in _BACKGROUND_INDOOR_ALIASES)
            else "outdoor" if any(alias in query for alias in _BACKGROUND_OUTDOOR_ALIASES)
            else ""
        )
        candidate_space = str(item.get("indoor_outdoor") or "").casefold()
        if requested_space == "indoor" and any(alias in candidate_space for alias in ("室外", "户外", "outdoor")):
            continue
        if requested_space == "outdoor" and any(alias in candidate_space for alias in ("室内", "屋内", "indoor")):
            continue

        place_score = sum(weight for token, weight in _custom_background_place_tokens(item) if token in query)
        alias_score = 0.0
        for aliases in _CUSTOM_BACKGROUND_PLACE_ALIASES:
            if any(alias in query for alias in aliases) and any(alias in searchable for alias in aliases):
                alias_score = max(alias_score, 4.5)
        if place_score <= 0 and alias_score <= 0:
            continue
        modifier_score = 0.0
        for field in ("time", "weather", "season", "mood"):
            value = str(item.get(field) or "").strip().casefold()
            if value and value in query:
                modifier_score += 0.5
        score = place_score + alias_score + modifier_score
        ranked.append((score, str(item.get("aa_key") or "").casefold(), {
            "aa_key": str(item.get("aa_key") or ""),
            "label": str(item.get("label") or item.get("name") or ""),
            "source": "custom", "preview_source": "story",
            "confidence": min(0.89, 0.60 + score * 0.05),
            "reason": "先按具体地点匹配；时间、天气和氛围只用于同地点候选排序。",
            "preview_available": bool(item.get("preview_available")),
        }))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:limit]]


def _background_time_bucket(value: object) -> str:
    text = str(value or "").casefold()
    for name, aliases in _BACKGROUND_TIME_ALIASES.items():
        if any(alias in text for alias in aliases):
            return name
    clock = re.search(r"([0-2]?\d|[零〇一二两三四五六七八九十]{1,3})[点時时]", text)
    if clock:
        raw_hour = clock.group(1)
        if raw_hour.isdigit():
            hour = int(raw_hour)
        else:
            digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
                      "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
            if "十" in raw_hour:
                left, right = raw_hour.split("十", 1)
                hour = (digits.get(left, 1) * 10) + digits.get(right, 0)
            else:
                hour = digits.get(raw_hour, -1)
        if 0 <= hour <= 4:
            return "night"
        if 17 <= hour <= 18:
            return "sunset"
        if 19 <= hour <= 23:
            return "night"
        if 5 <= hour <= 16:
            return "day"
    return re.sub(r"\s+", "", text)


def _same_background_space(previous: dict, location: str, time_label: str) -> bool:
    previous_location = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(previous.get("location") or "").casefold())
    current_location = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(location or "").casefold())
    if not previous_location or not current_location or "位置未标注" in {previous_location, current_location}:
        return False
    same_location = previous_location == current_location
    if not same_location:
        shorter, longer = sorted((previous_location, current_location), key=len)
        same_location = len(shorter) >= 4 and shorter in longer
    if not same_location:
        same_location = any(
            any(alias in previous_location for alias in aliases)
            and any(alias in current_location for alias in aliases)
            for aliases in _CUSTOM_BACKGROUND_PLACE_ALIASES
        )
    if not same_location:
        return False
    previous_time = _background_time_bucket(previous.get("time"))
    current_time = _background_time_bucket(time_label)
    return not (previous_time and current_time and previous_time != current_time)


def _normalize_usage_chain(raw_chain: object, custom_assets: dict, con) -> tuple[list[dict], list[dict]]:
    """Normalize model scene segments and derive safe asset refs for each need."""
    if not isinstance(raw_chain, list):
        return [], []
    asset_catalog.migrate(con)
    buckets = {
        "background": custom_assets.get("backgrounds", []),
        "sound": custom_assets.get("sounds", []),
        "bgm": custom_assets.get("bgms", []),
    }
    custom_backgrounds = {
        item["aa_key"].casefold(): item
        for item in _preflight_custom_background_library(custom_assets)
    }
    chain: list[dict] = []
    refs: list[dict] = []
    ref_keys: set[tuple[str, str]] = set()
    for raw_segment in raw_chain[:160]:
        if not isinstance(raw_segment, dict):
            continue
        segment = str(raw_segment.get("segment") or "场景").strip()[:120]
        location = str(raw_segment.get("location") or "位置未标注").strip()[:160]
        time_label = str(raw_segment.get("time") or "").strip()[:40]
        start = _compact_timeline_marker(raw_segment.get("start"))
        end = _compact_timeline_marker(raw_segment.get("end"))
        evidence = _compact_preflight_evidence(raw_segment.get("evidence"))
        needs: list[dict] = []
        for raw_need in (raw_segment.get("needs") or [])[:80]:
            if not isinstance(raw_need, dict):
                continue
            kind = _PREFLIGHT_KIND_ALIASES.get(str(raw_need.get("kind") or "").casefold())
            name = str(raw_need.get("name") or "").strip().strip("\"'")[:160]
            if not kind or not name:
                continue
            need_location = str(raw_need.get("location") or start or location or "位置未标注").strip()[:160]
            reason = str(raw_need.get("reason") or "AI 根据全文识别出的演出需求。").strip()[:500]
            try:
                confidence = max(0.0, min(1.0, float(raw_need.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            candidates: list[dict] = []
            candidate_keys: set[str] = set()
            if kind == "background":
                for raw_candidate in (raw_need.get("candidates") or [])[:8]:
                    if not isinstance(raw_candidate, dict):
                        continue
                    aa_key = str(raw_candidate.get("aa_key") or "").strip()
                    folded_key = aa_key.casefold()
                    if not aa_key or folded_key in candidate_keys:
                        continue
                    try:
                        candidate_confidence = max(
                            0.0, min(1.0, float(raw_candidate.get("confidence", 0.0)))
                        )
                    except (TypeError, ValueError):
                        candidate_confidence = 0.0
                    if candidate_confidence < 0.60:
                        continue
                    custom = custom_backgrounds.get(folded_key)
                    if custom is not None:
                        candidates.append({
                            "aa_key": custom["aa_key"],
                            "label": custom["label"],
                            "source": "custom",
                            "preview_source": "story",
                            "preview_available": custom["preview_available"],
                            "confidence": candidate_confidence,
                            "reason": str(raw_candidate.get("reason") or "")[:500],
                        })
                        candidate_keys.add(folded_key)
                        continue
                    row = con.execute(
                        """SELECT official.name,official.label FROM bg AS official
                           WHERE official.name=? COLLATE NOCASE
                             AND official.hash IS NOT NULL
                             AND NOT EXISTS (
                                 SELECT 1 FROM asset_install AS custom
                                 WHERE custom.kind='background'
                                   AND custom.status='registered'
                                   AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
                             )
                           LIMIT 1""",
                        (aa_key,),
                    ).fetchone()
                    if row is None:
                        continue
                    candidates.append({
                        "aa_key": str(row["name"]),
                        "label": str(row["label"] or row["name"]),
                        "source": "official",
                        "preview_source": "official",
                        "confidence": candidate_confidence,
                        "reason": str(raw_candidate.get("reason") or "与场景语义接近。")[:500],
                        "preview_available": _background_preview_available(aa_key),
                    })
                    candidate_keys.add(folded_key)
                candidates.sort(key=lambda item: (-item["confidence"], item["aa_key"].casefold()))
                candidates = candidates[:3]
                if not candidates:
                    candidates = _custom_background_candidates(
                        custom_backgrounds, name, reason, evidence, need_location, location
                    )
                if not candidates:
                    candidates = _catalog_background_candidates(
                        con, name, reason, evidence, need_location, location
                    )
            found = next((item for item in buckets[kind] if (
                str(item.get("name") or "").casefold() == name.casefold()
                or str(item.get("aa_key") or "").casefold() == name.casefold()
            )), None)
            builtin_key = ""
            if not found:
                if kind == "background":
                    row = con.execute(
                        """SELECT official.name FROM bg AS official
                           WHERE official.hash IS NOT NULL
                             AND (official.name=? OR official.label=?)
                             AND NOT EXISTS (
                                 SELECT 1 FROM asset_install AS custom
                                 WHERE custom.kind='background'
                                   AND custom.status='registered'
                                   AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
                             )
                           LIMIT 1""",
                        (name, name),
                    ).fetchone()
                    builtin_key = str(row["name"] or "") if row else ""
                elif kind == "sound":
                    row = con.execute("SELECT name FROM sound WHERE name=? OR label=? LIMIT 1", (name, name)).fetchone()
                    builtin_key = str(row["name"] or "") if row else ""
                elif kind == "bgm" and name.lstrip("-").isdigit():
                    builtin_key = name
            builtin = bool(found is None and builtin_key)
            if found:
                status = "registered"
            elif builtin:
                status = "builtin"
            elif candidates and candidates[0]["confidence"] >= 0.75:
                status = "recommended"
            elif candidates:
                status = "approximate"
            elif kind == "bgm":
                status = "unsupported"
            else:
                status = "missing"
            need = {
                "kind": kind, "name": name, "location": need_location,
                "reason": reason, "confidence": confidence, "status": status,
                "required": bool(raw_need.get("required", kind == "background")),
                "evidence": evidence, "candidates": candidates if not (found or builtin) else [],
            }
            if found:
                need["aa_key"] = str(found.get("aa_key") or name)
            elif builtin_key:
                need["aa_key"] = builtin_key
            elif candidates:
                need["suggested_aa_key"] = candidates[0]["aa_key"]
            offer_custom_background = (
                kind == "background"
                and status in {"missing", "recommended", "approximate"}
                and (not candidates or candidates[0]["confidence"] < 0.90)
            )
            if offer_custom_background:
                need["generation_prompt"] = _background_generation_prompt(
                    name, reason, evidence, need_location
                )
            if kind == "background" and chain and _same_background_space(chain[-1], location, time_label):
                previous_need = next((
                    item for item in chain[-1].get("needs", [])
                    if isinstance(item, dict) and item.get("kind") == "background"
                ), None)
                if previous_need is not None:
                    inherited_from = previous_need.get("inherits_from") or {
                        "segment": chain[-1]["segment"],
                        "location": previous_need["location"],
                        "requested_name": previous_need["name"],
                    }
                    need.update({
                        "status": "inherited",
                        "candidates": [],
                        "inherits_from": dict(inherited_from),
                        "continuity_reason": "与上一段处于同一物理空间，沿用同一背景。",
                    })
                    for field in (
                        "aa_key", "selected_label", "source", "preview_source", "preview_available",
                    ):
                        if field in previous_need:
                            need[field] = previous_need[field]
                    need.pop("suggested_aa_key", None)
                    need.pop("generation_prompt", None)
            needs.append(need)
            key = (kind, name.casefold())
            if key not in ref_keys and need["status"] not in {"builtin", "inherited"}:
                refs.append({
                    "kind": kind, "name": name, "status": status,
                    "location": need_location, "reason": reason,
                    "detected_by": "ai", "evidence": evidence,
                    "confidence": confidence,
                })
                ref_keys.add(key)
        chain.append({
            "segment": segment, "location": location, "start": start,
            "end": end, "evidence": evidence,
            "time": time_label,
            "scene_type": str(raw_segment.get("scene_type") or "other").strip()[:32],
            "scene_function": str(raw_segment.get("scene_function") or "dialogue").strip()[:48],
            "needs": needs,
        })
    return chain, refs


_PREFLIGHT_COMMANDS = {
    "bg", "trans", "bgfx", "popup", "bgm", "music", "se", "sound",
    "place", "wait", "raw", "bgshake", "clearst", "hidemenu", "showmenu",
    "aronatouch", "shot", "st", "stm", "zoom", "enter", "exit", "move",
    "stage", "auto", "camera", "camera_hold", "fx", "hl",
}
_PREFLIGHT_ARG_REQUIRED = _PREFLIGHT_COMMANDS - {
    "bgshake", "clearst", "hidemenu", "showmenu", "aronatouch", "auto",
}


def _preflight_directive_issues(text: str) -> list[dict]:
    """在没有模型配置时也能提前拦住明显的指令拼写问题。"""
    directive = re.compile(r"^\s*@(?P<cmd>\w+)\s*(?P<arg>.*)$")
    issues = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.lstrip().startswith("@"):
            continue
        match = directive.match(raw)
        if not match:
            issues.append({
                "severity": "error", "code": "invalid_directive",
                "message": f"第{line_no}行的指令格式无法识别。",
                "action": "请按“@指令 参数”的格式修改。",
            })
            continue
        cmd = match.group("cmd").casefold()
        arg = match.group("arg").strip()
        if cmd not in _PREFLIGHT_COMMANDS:
            issues.append({
                "severity": "error", "code": "unknown_directive",
                "message": f"第{line_no}行使用了未知指令 @{cmd}。",
                "action": "请检查拼写，或改用帮助中列出的 AA 指令。",
            })
        elif cmd in _PREFLIGHT_ARG_REQUIRED and not arg:
            issues.append({
                "severity": "error", "code": "missing_directive_argument",
                "message": f"第{line_no}行的 @{cmd} 缺少参数。",
                "action": "请在指令后补充素材名或所需参数。",
            })
    return issues


def _preflight_output_budget(provider, analysis: dict) -> int:
    """Use a bounded, scene-scaled budget independent from annotation chunks."""
    line_count = max(1, int(analysis.get("lines") or 0))
    header_count = len(analysis.get("scenes") or [])
    estimated_scenes = max(header_count, (line_count + 39) // 40, 1)
    target = min(6000, max(2048, 2048 + estimated_scenes * 192))
    cfg = getattr(provider, "cfg", {}) or {}
    try:
        model_limit = int(cfg.get("annotation_max_tokens") or cfg.get("max_tokens") or target)
    except (TypeError, ValueError):
        model_limit = target
    return max(1, min(target, model_limit))


def _complete_preflight(
    provider, static: str, volatile: str, user: str, *, output_budget: int | None = None,
) -> dict:
    """Request compact preflight JSON with one strict-format retry."""
    def call(system):
        with ExitStack() as stack:
            reason_mode = getattr(provider, "temporary_reasoning_mode", None)
            if callable(reason_mode):
                stack.enter_context(reason_mode("speed"))
            budget_mode = getattr(provider, "temporary_output_budget", None)
            if output_budget and callable(budget_mode):
                stack.enter_context(budget_mode(output_budget))
            return provider.complete_json(system, volatile, user, _PREFLIGHT_SCHEMA)

    try:
        result = call(static)
        # A 0.9.1 provider/cache response remains readable during the rollout.
        if isinstance(result, dict) and {"characters", "assets", "usage_chain", "issues"} <= set(result):
            return llm.validate_json_schema(result, _LEGACY_PREFLIGHT_SCHEMA)
        return llm.validate_json_schema(result, _PREFLIGHT_SCHEMA)
    except llm.StructuredOutputError:
        retry_static = static + (
            "\n\n上一次返回不符合要求。请立即重试，严格只返回一个 JSON 对象。"
            "对象只能包含 extra_speakers、scenes、ambiguities；不要返回角色映射、素材状态、"
            "候选、证据原文、理由、问题文案、Markdown 或代码围栏。"
        )
        result = call(retry_static)
        if isinstance(result, dict) and {"characters", "assets", "usage_chain", "issues"} <= set(result):
            return llm.validate_json_schema(result, _LEGACY_PREFLIGHT_SCHEMA)
        return llm.validate_json_schema(result, _PREFLIGHT_SCHEMA)


def _preflight_result(script: str, *, scope: str, model_profile_id: str | None = None) -> dict:
    """执行规则基线与可选 AI 初审，返回浏览器可编辑的安全结果。"""
    text = Path(script).read_text(encoding="utf-8", errors="replace")
    analysis = analyze(script)
    baseline = guess_mapping(analysis.get("speakers") or [])
    con = db()
    try:
        custom_assets = asset_catalog.list_story_assets(con, scope=scope)
        for speaker in analysis.get("speakers") or []:
            who = str(speaker.get("who") or "")
            story_mapping = _story_custom_character_mapping(who, custom_assets)
            if story_mapping is not None:
                baseline[who] = story_mapping
        character_library = _preflight_character_library(
            con, analysis.get("speakers") or [], custom_assets, baseline
        )
        refs = _preflight_asset_refs(text, custom_assets, con)
        builtin_asset_names = {
            "background": {
                str(value).casefold()
                for row in con.execute(
                    """SELECT official.name,official.label FROM bg AS official
                       WHERE official.hash IS NOT NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM asset_install AS custom
                             WHERE custom.kind='background' AND custom.status='registered'
                               AND CAST(custom.aa_key AS TEXT)=CAST(official.hash AS TEXT)
                         )"""
                )
                for value in (row["name"], row["label"])
                if value
            },
            "sound": {
                str(value).casefold()
                for row in con.execute("SELECT name,label FROM sound")
                for value in (row["name"], row["label"])
                if value
            },
        }
    finally:
        con.close()
    custom_ids = {
        str(item.get("aa_key") or "").casefold()
        for item in custom_assets.get("characters", [])
    }
    characters = []
    for speaker in analysis.get("speakers", []):
        who = str(speaker.get("who") or "")
        mapping = dict(baseline.get(who) or {"kind": "unset"})
        current_story_custom = mapping.get("source") == "current_story_custom"
        characters.append({
            "speaker": who, "kind": str(mapping.get("kind") or "unset"),
            "id": str(mapping.get("id") or ""), "name": str(mapping.get("name") or ""),
            "club": str(mapping.get("club") or _BUILTIN_VOICE_CHARACTER_CLUBS.get(who.casefold(), "")),
            "custom": str(mapping.get("id") or "").casefold() in custom_ids,
            "confidence": (
                0.95 if current_story_custom
                else 0.65 if mapping.get("kind") not in (None, "unset") else 0.0
            ),
            "reason": (
                "当前剧情中唯一同名的自定义角色素材。"
                if current_story_custom else "规则匹配结果，可在确认演员中修改。"
            ),
        })
    ai_status = "not_configured"
    usage_chain_status = "not_run"
    usage_chain: list[dict] = []
    ai_diagnostics: dict | None = None
    ai_usage: dict | None = None
    ai_issues = []
    provider = annotation_provider(model_profile_id)
    if provider is not None:
        before_stats = dict(getattr(provider, "stats", {}) or {})
        static = (
            "你是 AA 剧本编译器的轻量初审规划器。你只做必须理解全文才能完成的语义判断，"
            "不改写台词，也不输出 AA 标注。只返回 schema 规定的紧凑 JSON。"
            "extra_speakers 只列规则结果遗漏、但正文明确说话或出场的人物；不要重复 speakers。"
            "scenes 只按会改变画面背景的边界覆盖正文：地点改变、室内外改变、时间段明显改变、"
            "原文明示转场或背景指令改变时才新建 scene，用 L 行号填写 start_line/end_line。"
            "同一物理地点中的动作升级、对话阶段、人物进出、镜头节拍或剧情转折都不算背景变化，"
            "不要因此拆出新 scene。相邻内容继续使用同一背景时合并到同一 scene。"
            "每场填写地点、时间、main/event/bond/other 和 scene_function。"
            "needs 只写语义素材名：每个真正发生背景变化的 scene 写一个 background；"
            "只有正文有明确声音线索时才写 sound，"
            "只有音乐对情绪结构不可替代时才写 bgm。不要输出候选、aa_key、状态、证据原文、理由或置信度。"
            "required 表示缺少该素材会破坏场景理解；纯氛围增强一律 false。"
            "ambiguities 只写真正需要人工确认、且后端规则无法确定的文本歧义；不要生成素材缺失、"
            "人物未映射、格式或指令问题，这些由后端确定性检查。"
            "不要输出 Markdown、解释、总结或重复剧本文本。"
        )
        windows = _preflight_script_windows(text)
        volatile_base = {
            "speakers": [{
                "name": str(item.get("who") or ""), "count": int(item.get("n") or 0),
            } for item in analysis.get("speakers", [])],
        }
        if len(windows) == 1:
            volatile_base["scene_headers"] = analysis.get("scenes", [])
        output_budgets = []
        prompt_chars = 0
        try:
            ai_parts = []
            for window_index, window in enumerate(windows, 1):
                volatile_payload = dict(volatile_base)
                if len(windows) > 1:
                    volatile_payload["window"] = {
                        "index": window_index, "count": len(windows),
                        "start_line": window["start_line"], "end_line": window["end_line"],
                    }
                volatile = json.dumps(
                    volatile_payload, ensure_ascii=False, separators=(",", ":")
                )
                user = (
                    "分析下列带行号剧本。行号仅用于定位，不属于原文。"
                    "只分析本窗口，不要补写窗口外场景。直接返回 JSON。\n\n"
                    + window["text"]
                )
                window_analysis = {
                    "lines": window["end_line"] - window["start_line"] + 1,
                    "scenes": analysis.get("scenes", []) if len(windows) == 1 else [],
                }
                output_budget = _preflight_output_budget(provider, window_analysis)
                output_budgets.append(output_budget)
                prompt_chars += len(static) + len(volatile) + len(user)
                part = _complete_preflight(
                    provider, static, volatile, user, output_budget=output_budget
                )
                if not {"characters", "assets", "usage_chain", "issues"} <= set(part):
                    part = _compact_preflight_to_internal(part, text)
                ai_parts.append(part)
            ai = _merge_preflight_internal(ai_parts)
            if isinstance(ai, dict):
                ai_status = "completed"
                usage_chain_status = "completed"
                chain_con = db()
                try:
                    usage_chain, chain_refs = _normalize_usage_chain(
                        ai.get("usage_chain"), custom_assets, chain_con
                    )
                finally:
                    chain_con.close()
                present_chain_refs = {
                    (item["kind"], item["name"].casefold()) for item in refs
                }
                chain_kinds = {
                    str(need.get("kind") or "")
                    for segment in usage_chain
                    for need in (segment.get("needs") or [])
                    if isinstance(need, dict)
                }
                for chain_ref in chain_refs:
                    key = (chain_ref["kind"], chain_ref["name"].casefold())
                    if key not in present_chain_refs:
                        refs.append(chain_ref)
                        present_chain_refs.add(key)
                candidates_by_id = {
                    str(row.get("id") or "").casefold(): row
                    for row in character_library["candidates"]
                }
                by_speaker = {
                    str(row.get("speaker") or "").strip(): row
                    for row in (ai.get("characters") or [])
                    if isinstance(row, dict) and str(row.get("speaker") or "").strip()
                }
                known_speakers = {item["speaker"] for item in characters}
                for speaker, suggestion in by_speaker.items():
                    # A free-form screenplay can contain roles the rule parser did
                    # not see.  Surface them for human confirmation; never invent
                    # an AA mapping or silently alter the source script.
                    if speaker in known_speakers or len(speaker) > 28:
                        continue
                    known_speakers.add(speaker)
                    characters.append({
                        "speaker": speaker, "kind": "unset", "id": "", "name": "",
                        "custom": False, "confidence": 0.0,
                        "reason": "AI 从非标准写法的全文中发现，等待确认。",
                        "detected_by": "ai",
                    })
                    analysis.setdefault("speakers", []).append({
                        "who": speaker, "n": 0, "sample": "AI 从全文识别，等待确认",
                    })
                for item in characters:
                    suggestion = by_speaker.get(item["speaker"])
                    if suggestion:
                        kind = str(suggestion.get("kind") or "unset").casefold()
                        ident = str(suggestion.get("id") or "").strip()
                        candidate = candidates_by_id.get(ident.casefold())
                        current_kind = str(item.get("kind") or "unset")
                        current_id = str(item.get("id") or "")
                        resolved = current_kind != "unset"
                        same_mapping = (
                            kind == current_kind
                            and (kind == "narrator" or ident.casefold() == current_id.casefold())
                        )
                        accepted = not resolved or same_mapping
                        if not accepted:
                            continue
                        if kind == "narrator":
                            item.update(kind="narrator", id="", name="旁白", custom=False)
                        elif kind == "voice":
                            # A named offscreen speaker does not need a library
                            # candidate.  Keep the screenplay name and derive the
                            # same stable slot-0 identity used by rule mapping.
                            voice = voice_character_mapping(item["speaker"])
                            item.update(
                                kind="voice", id=voice["id"], name=item["speaker"],
                                spine="", custom=False,
                            )
                        elif kind == "portrait" and candidate:
                            item.update(
                                kind=kind, id=candidate["id"],
                                name=item.get("name") or candidate["name"],
                                custom=bool(candidate["custom"]),
                            )
                        elif kind == "unset":
                            item.update(kind="unset", id="", name="", custom=False)
                        try:
                            item["confidence"] = max(0.0, min(1.0, float(suggestion.get("confidence", item["confidence"]))))
                        except (TypeError, ValueError):
                            pass
                        if suggestion.get("reason"):
                            item["reason"] = str(suggestion["reason"])
                refs_by_key = {
                    (str(row.get("kind") or "").casefold(), str(row.get("name") or "").strip().casefold()): row
                    for row in (ai.get("assets") or [])
                    if isinstance(row, dict) and str(row.get("name") or "").strip()
                }
                kind_aliases = _PREFLIGHT_KIND_ALIASES
                present_refs = {(item["kind"], item["name"].casefold()) for item in refs}
                for (raw_kind, folded_name), suggestion in refs_by_key.items():
                    kind = kind_aliases.get(raw_kind)
                    name = str(suggestion.get("name") or "").strip()
                    if not kind or not name or len(name) > 160 or (kind, folded_name) in present_refs:
                        continue
                    if kind in chain_kinds:
                        continue
                    bucket_name = {"background": "backgrounds", "sound": "sounds", "bgm": "bgms"}[kind]
                    bucket = custom_assets.get(bucket_name, [])
                    found = next((item for item in bucket if str(item.get("name") or "").casefold() == folded_name
                                  or str(item.get("aa_key") or "").casefold() == folded_name), None)
                    builtin = not found and (
                        (kind == "bgm" and name.lstrip("-").isdigit())
                        or folded_name in builtin_asset_names.get(kind, set())
                    )
                    if builtin:
                        continue
                    refs.append({
                        "kind": kind, "name": name,
                        "status": "registered" if found else "missing",
                        "location": str(suggestion.get("location") or "AI 从全文识别"),
                        "reason": str(suggestion.get("reason") or (
                            "已登记到当前剧情" if found else "AI 从全文发现，需导入或确认。"
                        )),
                        "detected_by": "ai",
                    })
                    present_refs.add((kind, folded_name))
                for ref in refs:
                    suggestion = refs_by_key.get((ref["kind"], ref["name"].casefold()))
                    if suggestion and suggestion.get("reason"):
                        ref["reason"] = str(suggestion["reason"])
                for row in (ai.get("issues") or []):
                    if not isinstance(row, dict):
                        continue
                    severity = str(row.get("severity") or "warning").casefold()
                    code = str(row.get("code") or "ai_issue")
                    if code in {"missing_custom_asset", "speaker_unmapped"}:
                        continue
                    if any(token in code.casefold() for token in (
                        "asset", "background", "sound", "bgm", "music"
                    )):
                        continue
                    issue = {
                        "severity": severity if severity in {"error", "warning"} else "warning",
                        "code": code,
                        "message": str(row.get("message") or "AI 发现一项需要检查的问题。"),
                        "action": str(row.get("action") or "请检查对应剧本内容。"),
                    }
                    if row.get("speaker"):
                        issue["speaker"] = str(row["speaker"])
                    ai_issues.append(issue)
        except Exception as exc:
            ai_status = "failed"
            usage_chain_status = "unavailable"
            usage_chain = []
            provider_name = str(getattr(provider, "name", provider.__class__.__name__))
            model_name = str(getattr(provider, "model", "") or "")
            structured = isinstance(exc, llm.StructuredOutputError)
            ai_diagnostics = {
                "stage": "structured_output" if structured else "model_call",
                "provider": provider_name[:80],
                "model": model_name[:120],
                "message": _safe_ai_error(exc),
            }
            ai_issues.append({
                "severity": "warning", "code": "ai_preflight_failed",
                "message": (
                    "AI 已响应，但初审结果格式尚未整理完成，已保留规则分析结果。"
                    if structured else "AI 初审尚未完成，已保留规则分析结果。"
                ),
                "action": (
                    "系统已自动重试一次；请检查模型配置是否支持结构化 JSON。"
                    if structured else
                    "检查模型配置、接口地址和网络后重试；场景演出规划暂未完成。"
                ),
            })
        after_stats = dict(getattr(provider, "stats", {}) or {})
        ai_usage = {
            "input_chars": prompt_chars,
            "input_tokens": max(
                0, int(after_stats.get("in", 0) or 0) - int(before_stats.get("in", 0) or 0)
            ),
            "output_tokens": max(
                0, int(after_stats.get("out", 0) or 0) - int(before_stats.get("out", 0) or 0)
            ),
            "calls": max(
                0, int(after_stats.get("calls", 0) or 0) - int(before_stats.get("calls", 0) or 0)
            ),
            "output_budget": max(output_budgets, default=0),
            "window_count": len(windows),
            "scene_count": len(usage_chain),
        }
    else:
        usage_chain_status = "unavailable"
        ai_diagnostics = {"stage": "configuration", "message": "未配置可用模型"}
    issues = _preflight_directive_issues(text)
    if analysis.get("format", {}).get("confidence") == "low":
        issues.append({
            "severity": "warning", "code": "nonstandard_script_format",
            "message": "未识别稳定的“角色：台词”格式，已改用全文 AI 初审补充角色和素材。",
            "action": "请重点确认 AI 新发现的角色、背景和音效；推荐格式见使用帮助。",
        })
        if ai_status != "completed":
            issues.append({
                "severity": "error", "code": "nonstandard_format_requires_ai",
                "message": "当前剧本是非标准格式，但 AI 全文初审没有完成，无法可靠识别角色和素材。",
                "action": "请配置可用模型后重新初审，或按帮助中的“角色名：台词”格式整理剧本。",
            })
    for ref in refs:
        if ref["status"] == "missing":
            kind_name = "背景" if ref["kind"] == "background" else "音效" if ref["kind"] == "sound" else "BGM"
            ai_suggestion = ref.get("detected_by") == "ai"
            action = "请从本剧情素材导入，或从历史项目复制后再确认初审。"
            if ref["kind"] == "bgm":
                action = "当前版本尚未开放自定义 BGM 登记；请改用已知数字 BGM ID。"
            elif ai_suggestion and ref["kind"] == "background":
                action = "没有找到可靠的 AA 近似背景；可以生成或导入新背景，也可以继续使用默认背景。"
            elif ai_suggestion:
                action = "这是可选演出增强，可以补充，也可以直接跳过。"
            issues.append({
                "severity": "warning" if ai_suggestion else "error",
                "code": (
                    "optional_asset_suggestion" if ai_suggestion and ref["kind"] in {"sound", "bgm"}
                    else "background_asset_suggestion" if ai_suggestion
                    else "bgm_not_supported" if ref["kind"] == "bgm"
                    else "missing_custom_asset"
                ),
                "message": (
                    f"{ref['location']} 可选使用{kind_name}“{ref['name']}”。"
                    if ai_suggestion and ref["kind"] in {"sound", "bgm"} else
                    f"{ref['location']} 建议使用背景“{ref['name']}”，但没有可靠的现有匹配。"
                    if ai_suggestion else
                    f"{ref['location']} 需要{kind_name}“{ref['name']}”，但当前剧情尚未登记。"
                ),
                "action": action,
            })
        elif ref["status"] == "unsupported":
            ai_suggestion = ref.get("detected_by") == "ai"
            issues.append({
                "severity": "warning",
                "code": "optional_asset_suggestion" if ai_suggestion else "bgm_not_supported",
                "message": (
                    f"{ref['location']} 可选使用 BGM“{ref['name']}”。"
                    if ai_suggestion else
                    f"{ref['location']} 需要 BGM“{ref['name']}”，当前版本暂不支持自定义 BGM 登记。"
                ),
                "action": (
                    "这是可选演出增强，可以直接跳过。"
                    if ai_suggestion else
                    "先保留为待验证演出需求；AA 原生 BGM 契约确认后再登记。"
                ),
            })
    for item in characters:
        if item["kind"] == "unset" and not is_non_character_speaker(item["speaker"]):
            issues.append({
                "severity": "error", "code": "speaker_unmapped", "speaker": item["speaker"],
                "message": f"说话者“{item['speaker']}”尚未对应 AA 角色。",
                "action": "点击“修改”选择角色或设为旁白。",
            })
    seen_issues = {(item["code"], item["message"]) for item in issues}
    for issue in ai_issues:
        key = (issue["code"], issue["message"])
        if key not in seen_issues:
            issues.append(issue)
            seen_issues.add(key)
    return {
        "ok": True, "ai_status": ai_status, "characters": characters,
        "assets": refs, "available_assets": custom_assets,
        "usage_chain": usage_chain,
        "usage_chain_status": usage_chain_status,
        "ai_diagnostics": ai_diagnostics,
        "ai_usage": ai_usage,
        "character_library": character_library, "issues": issues,
        "analysis": {"lines": analysis.get("lines", 0), "scenes": analysis.get("scenes", []),
                      "speakers": analysis.get("speakers", []),
                      "format": analysis.get("format", {})},
    }


def preflight_story_worker(payload: dict) -> dict:
    """后台执行 AI 初审；仅返回可公开的结果，不带脚本物理路径。"""
    script = str(payload.get("script") or "")
    scope = str(payload.get("scope") or "")
    if not script or not os.path.isfile(script) or not scope:
        raise ValueError("缺少有效的剧本或剧情作用域")
    result = _preflight_result(
        script, scope=scope, model_profile_id=payload.get("model_profile_id")
    )
    saved = False
    story_token = str(payload.get("story_token") or "")
    if story_token:
        try:
            story_workspace().set_preflight_snapshot(story_token, result)
            saved = True
        except (KeyError, OSError, TypeError, ValueError):
            pass
    result["snapshot_saved"] = saved
    return result


# ---------------------------------------------------------------- 生成
def prepare_project_index(index_path, project_dir, output_path, *, con=None):
    """Build the exact official+registered allowlist used by AI and generator."""
    if not os.path.isfile(index_path) and os.path.abspath(index_path) == os.path.abspath(INDEX):
        _ensure_resource_index()
    try:
        with open(index_path, encoding="utf-8") as source:
            index = json.load(source)
    except FileNotFoundError:
        raise RuntimeError(
            "缺少资源索引文件（aa_resources.json）。请确认已在设置中选择 "
            "AzureArchive.exe 后重试（也可运行 build_index.py）。"
        ) from None
    merged = S2A.merge_project_registered_assets(index, project_dir)
    if con is not None:
        merged = asset_catalog.merge_model_constraints(
            merged,
            con,
            scope=os.path.abspath(project_dir),
        )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as target:
        json.dump(merged, target, ensure_ascii=False, indent=1)
    return output_path


def attach_registered_variants(cast, con, project_dir):
    """Attach the registered Spine variant to every portrait cast entry."""
    registered = asset_catalog.export_model_constraints(
        con,
        scope=os.path.abspath(project_dir),
    )
    by_identifier = {
        str(record["identifier"]): record
        for record in registered["characters"]
    }
    for entry in cast.get("cast", {}).values():
        if not entry.get("portrait"):
            continue
        record = by_identifier.get(str(entry.get("id", "")))
        if not record:
            continue
        signature = record.get("spine_signature")
        outfit_key = record.get("outfit_key")
        if signature and outfit_key:
            entry["spine_signature"] = signature
            entry["outfit_key"] = outfit_key
            install_path = Path(str(record.get("install_path") or ""))
            if install_path.is_dir():
                entry["custom"] = {
                    "src": str(install_path),
                    "asset": outfit_key,
                }


def build_project_name(payload):
    """Normalize the user-facing build name into one safe Windows component."""
    value = str(payload.get("project") or "").strip() or "未命名"
    return validate_windows_path_component(value, label="project name")


def pause_for_backgrounds(src, context):
    """Pause one build if its annotated source requests custom backgrounds."""
    global BUILD_RESUME
    session = background_workflow.BackgroundResolutionSession.create(
        src,
        project=str(context.get("project") or ""),
    )
    state = session.public_state()
    if not state["requests"]:
        return False
    token = uuid.uuid4().hex
    with BUILD_RESUME_LOCK:
        BUILD_RESUME = {
            "token": token,
            "session": session,
            "context": dict(context),
        }
    with JOB_LOCK:
        JOB.update(
            running=False,
            done=True,
            ok=False,
            state="needs_backgrounds",
            resume_token=token,
            project=state["project"],
            background_requests=state["requests"],
            backgrounds_ready=state["ready"],
        )
    jlog(f"需要先补充 {len(state['requests'])} 张自定义背景，工程已暂停。")
    return True


def _resume_record(token):
    with BUILD_RESUME_LOCK:
        record = BUILD_RESUME
        if not record or str(record.get("token")) != str(token):
            raise background_workflow.BackgroundResolutionError(
                "这次背景补充任务已失效，请重新生成"
            )
        return record


def _registered_backgrounds_for_resume(context):
    index_path = str(context.get("index_path") or INDEX)
    project_dir = str(context.get("project_dir") or "")
    with open(index_path, encoding="utf-8") as handle:
        index = json.load(handle)
    merged = S2A.merge_project_registered_assets(index, project_dir)
    return set((merged.get("bg") or {}).keys())


def resolve_background_for_build(data, *, registered_backgrounds=None):
    """Resolve one pending request only with a background registered in scope."""
    record = _resume_record(data.get("token"))
    known = (
        set(registered_backgrounds)
        if registered_backgrounds is not None
        else _registered_backgrounds_for_resume(record["context"])
    )
    state = record["session"].resolve(
        str(data.get("request_id") or ""),
        str(data.get("background_name") or ""),
        registered_backgrounds=known,
    )
    with JOB_LOCK:
        JOB.update(
            state="backgrounds_ready" if state["ready"] else "needs_backgrounds",
            background_requests=state["requests"],
            backgrounds_ready=state["ready"],
        )
    return {
        **state,
        "resume_token": record["token"],
    }


def continue_background_build(token, *, compile_runner=None):
    """Continue conversion from the saved annotated source without another LLM call."""
    global BUILD_RESUME
    record = _resume_record(token)
    if not record["session"].public_state()["ready"]:
        raise background_workflow.BackgroundResolutionError(
            "背景请求尚未全部解决"
        )
    context = dict(record["context"])
    runner = compile_runner or _compile_saved_context
    with JOB_LOCK:
        JOB.update(
            running=True,
            done=False,
            ok=False,
            state="compiling",
        )
    try:
        jlog("背景已补齐，继续生成 .aap；不会重新调用模型。")
        runner(context)
        with JOB_LOCK:
            JOB.update(ok=True, state="succeeded")
        jlog("完成。" + (
            "已装进 AA，打开 AA 就能看到。"
            if context.get("install")
            else "文件已写入输出目录。"
        ))
        with BUILD_RESUME_LOCK:
            if BUILD_RESUME is record:
                BUILD_RESUME = None
    except Exception as exc:
        jlog(f"出错: {exc}")
        with JOB_LOCK:
            JOB.update(ok=False, state="failed")
    finally:
        with JOB_LOCK:
            JOB.update(running=False, done=True)


def _compile_saved_context(context):
    """Run only the deterministic script-to-AAP phase for one saved build."""
    jlog("正在生成 .aap …")
    argv = sys.argv
    sys.argv = [
        "script2aap.py",
        str(context["src"]),
        "-o",
        str(context["project"]),
        "--cast",
        str(context["cpath"]),
        "--index",
        str(context["index_path"]),
        "--aa-data",
        str(context["aa_data"]),
        "--output-root",
        str(RUNTIME_LAYOUT.output_root),
    ]
    if context.get("install"):
        assert_aa_closed()
        sys.argv.append("--install")
    try:
        S2A.warn.items = []
        S2A.main()
    finally:
        sys.argv = argv
    for no, msg in S2A.warn.items[:20]:
        jlog(f"  ! 第{no}行 {msg}" if no else f"  ! {msg}")


def run_build(payload, job=None):
    """后台线程：写演员表 -> (可选)标注 -> 转换 -> 装进 AA"""
    JOB.update(
        running=True,
        log=[],
        done=False,
        ok=False,
        state="running",
        resume_token="",
        background_requests=[],
        backgrounds_ready=False,
    )
    try:
        story_type = normalize_story_type(payload.get("story_type"))
        script = payload["script"]
        project = build_project_name(payload)
        cast = {"default_bg": payload.get("bg") or "BG_Black",
                "default_bgm": 999, "scene_bg": payload.get("scene_bg") or {},
                "cast": {}, "alias": payload.get("alias") or {}}
        for who, m in payload["mapping"].items():
            k = m.get("kind")
            if k == "narrator":
                cast["cast"][who] = {"narrator": True}
            elif k == "voice":
                cast["cast"][who] = {"id": m["id"], "name": m.get("name") or who,
                                     "club": m.get("club", ""), "portrait": False}
            elif k == "portrait":
                e = {"id": m["id"], "name": m.get("name") or who,
                     "club": m.get("club", ""), "portrait": True}
                if m.get("custom_src"):
                    e["custom"] = {"src": m["custom_src"], "asset": m["custom_asset"]}
                cast["cast"][who] = e
            # unset 的直接不写进演员表 -> 转换器会告警并跳过该角色的台词

        project_dir = os.path.join(CFG["aa_data"], "projects", project)
        con = db()                       # 记住这次的对应关系，下次自动猜中
        for who, m in payload["mapping"].items():
            if m.get("kind") in ("portrait", "voice", "narrator"):
                assetdb.remember_alias(con, who, m.get("id", ""), m["kind"])
        attach_registered_variants(cast, con, project_dir)

        cpath = os.path.join(str(RUNTIME_LAYOUT.output_root), "cast-" + re.sub(r"[^\w-]", "_", project)[:40] + ".json")
        RUNTIME_LAYOUT.output_root.mkdir(parents=True, exist_ok=True)
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump(cast, fh, ensure_ascii=False, indent=2)
        jlog(f"演员表已写入 {os.path.basename(cpath)}")
        index_path = os.path.join(
            str(RUNTIME_LAYOUT.output_root),
            re.sub(r"[^\w-]", "_", project)[:40] + ".resources.json",
        )
        prepare_project_index(INDEX, project_dir, index_path, con=con)

        src = script
        if payload.get("annotate"):
            jlog("正在调用 AI 做演出标注…（长剧本要几分钟）")
            import annotate as ANN
            selected_provider = annotation_provider(
                payload.get("model_profile_id")
            )
            out = os.path.join(str(RUNTIME_LAYOUT.output_root),
                               re.sub(r"[^\w-]", "_", project)[:40] + ".annotated.txt")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            opts = {
                "script": script,
                "out": out,
                "cast": cpath,
                "index": index_path,
                "checkpoint_dir": str(
                    RUNTIME_LAYOUT.output_root / "annotation-checkpoints"
                ),
                "story_type": story_type,
            }
            if payload.get("provider"):
                opts["provider"] = payload["provider"]
            try:
                ANN.annotate_script(opts, provider_instance=selected_provider)
                src = out
                jlog(f"标注完成 -> {os.path.basename(out)}")
            except Exception as e:
                raise RuntimeError(f"标注中断: {e}")

        compile_context = {
            "src": src,
            "project": project,
            "cpath": cpath,
            "index_path": index_path,
            "aa_data": CFG["aa_data"],
            "project_dir": project_dir,
            "install": bool(payload.get("install")),
        }
        if pause_for_backgrounds(src, compile_context):
            return
        _compile_saved_context(compile_context)
        JOB["ok"] = True
        JOB["state"] = "succeeded"
        jlog("完成。" + ("已装进 AA，打开 AA 就能看到。" if payload.get("install")
                        else "文件在 tools/aa/out/ 下。"))
    except Exception as e:
        jlog(f"出错: {e}")
        jlog(traceback.format_exc().splitlines()[-3])
        JOB["state"] = "failed"
    finally:
        with JOB_LOCK:
            JOB.update(running=False, done=True)


def annotate_draft_worker(payload, job=None):
    """AI 演出标注 -> 建草稿 -> 存 cast/proposals。供 /api/annotate 的 Job 调用。"""
    import annotate as ANN
    story_type = normalize_story_type(payload.get("story_type"))
    project = build_project_name(payload)
    cast = {"default_bg": payload.get("bg") or "BG_Black",
            "default_bgm": 999, "scene_bg": payload.get("scene_bg") or {},
            "cast": {}, "alias": payload.get("alias") or {}}
    for who, m in payload["mapping"].items():
        k = m.get("kind")
        if k == "narrator":
            cast["cast"][who] = {"narrator": True}
        elif k == "voice":
            cast["cast"][who] = {"id": m["id"], "name": m.get("name") or who,
                                 "club": m.get("club", ""), "portrait": False}
        elif k == "portrait":
            e = {"id": m["id"], "name": m.get("name") or who,
                 "club": m.get("club", ""), "portrait": True}
            if m.get("custom_src"):
                e["custom"] = {"src": m["custom_src"], "asset": m["custom_asset"]}
            cast["cast"][who] = e

    con = db()
    for who, m in payload["mapping"].items():
        if m.get("kind") in ("portrait", "voice", "narrator"):
            assetdb.remember_alias(con, who, m.get("id", ""), m["kind"])
    project_dir = os.path.join(CFG["aa_data"], "projects", project)
    attach_registered_variants(cast, con, project_dir)

    token = f"draft-{uuid.uuid4().hex[:12]}"
    cpath = os.path.join(OUT_DIR, token + ".cast.json")
    os.makedirs(os.path.dirname(cpath), exist_ok=True)
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(cast, fh, ensure_ascii=False, indent=2)
    index_path = os.path.join(OUT_DIR, token + ".resources.json")
    prepare_project_index(INDEX, project_dir, index_path, con=con)
    out_path = os.path.join(OUT_DIR, token + ".annotated.txt")

    source_text = ""
    try:
        source_text = open(payload["script"], encoding="utf-8").read()
    except OSError:
        pass

    result = {}
    if payload.get("annotate", True):
        def annotation_model_activity(activity):
            if not job or not hasattr(job, "update_activity"):
                return
            job.update_activity(activity)

        def annotation_progress(phase, current, total, detail):
            if not job:
                return
            if phase == "recovery":
                detail = str(detail)
            phase_start = {"planning": 0.0, "annotating": 0.10, "resumed": 0.10,
                           "recovery": 0.10, "review": 0.90, "cancelled": 0.0,
                           "timed_out": 0.10}.get(phase, 0.10)
            phase_end = {"planning": 0.10, "annotating": 0.90, "resumed": 0.90,
                         "recovery": 0.90, "review": 0.98, "cancelled": 1.0,
                         "timed_out": 0.90}.get(phase, 0.90)
            ratio = min(1.0, max(0.0, (current / total) if total else 0.0))
            job.update_progress((phase_start + (phase_end - phase_start) * ratio) * 100, detail)

        opts = {
            "script": payload["script"],
            "out": out_path,
            "cast": cpath,
            "index": index_path,
            "usage_chain": payload.get("usage_chain") or [],
            "agent_enabled": payload.get("agent_enabled", True),
            "checkpoint_dir": os.path.join(OUT_DIR, "annotation-checkpoints"),
            "progress": annotation_progress,
            "model_activity": annotation_model_activity,
            "cancelled": job.is_cancel_requested if job else None,
            "story_type": story_type,
        }
        if payload.get("provider"):
            opts["provider"] = payload["provider"]
        selected_provider = annotation_provider(payload.get("model_profile_id"))
        result = ANN.annotate_script(opts, provider_instance=selected_provider)
        annotated = ""
        if os.path.isfile(out_path):
            annotated = open(out_path, encoding="utf-8").read()
        if not annotated:
            annotated = result.get("text") or ""
        if result.get("cancelled"):
            return {"project": project, "lines": 0, "proposals": 0,
                    "diagnostics": result.get("diagnostics") or [], "cancelled": True,
                    "agent": result.get("agent") or {}, "story_type": story_type}
    else:
        annotated = source_text

    agent = result.get("agent") or {}
    total_targets = int(agent.get("total_targets") or 0)
    completed_targets = int(agent.get("completed_targets") or 0)
    pending_targets = int(agent.get("pending_targets") or 0)
    annotation_status = {
        "status": "partial" if agent.get("timed_out") or pending_targets else "complete",
        "completed_targets": completed_targets,
        "total_targets": total_targets,
        "pending_targets": pending_targets,
        "pending_start_line": agent.get("pending_start_line"),
        "pending_end_line": agent.get("pending_end_line"),
    }
    store = DraftStore()
    metrics = dict(agent.get("metrics") or {})
    fully_reused = bool(
        payload.get("annotate", True)
        and "requests" in metrics
        and int(metrics.get("requests") or 0) == 0
        and int(agent.get("resumed_chunks") or 0) > 0
        and total_targets > 0
        and completed_targets == total_targets
        and annotation_status["status"] == "complete"
    )
    if fully_reused:
        existing_token = store.find_identical_complete_draft(
            text=annotated,
            source_text=source_text,
            project=project,
            story_token=payload.get("story_token"),
        )
        if existing_token:
            return {
                "draft_token": existing_token,
                "project": project,
                "lines": len(annotated.splitlines()),
                "proposals": 0,
                "resumed_chunks": int(agent.get("resumed_chunks") or 0),
                "timed_out": False,
                "reused_draft": True,
                "agent_metrics": metrics,
                "diagnostics": result.get("diagnostics") or [],
                "story_type": story_type,
            }
    store.create_draft(token=token, text=annotated, project=project,
                       source_text=source_text, cast=cast,
                       story_token=payload.get("story_token"),
                       bgm_policy=payload.get("bgm_policy"),
                       annotation_status=annotation_status)
    store.save_cast(token, cast)
    proposals = result.get("proposals") or []
    if proposals:
        store.add_proposals(token, proposals)
    return {"draft_token": token, "project": project,
            "lines": len(annotated.splitlines()), "proposals": len(proposals),
             "resumed_chunks": int(agent.get("resumed_chunks") or 0),
             "timed_out": bool(agent.get("timed_out")),
             "agent_metrics": metrics,
             "diagnostics": result.get("diagnostics") or [],
             "story_type": story_type}


def get_draft_detail_data(token, store=None):
    if store is None:
        store = DraftStore()
    draft = store.load_draft(token)
    session = draft["session"]
    edited_text = draft["edited_text"]
    identities_data = draft["identities"]
    diagnostics = draft["diagnostics"]
    annotation_status = normalize_annotation_status(session.get("annotation_status"))
    if annotation_status["status"] != "complete":
        diagnostics = list(diagnostics) + [{
            "code": "annotation_incomplete",
            "severity": "error",
            "message": (
                f"AI 标注尚未完成：{annotation_status['completed_targets']}/"
                f"{annotation_status['total_targets']}，剩余 "
                f"{annotation_status['pending_targets']} 条"
            ),
            "pending_start_line": annotation_status.get("pending_start_line"),
            "pending_end_line": annotation_status.get("pending_end_line"),
        }]
    cast_data = store.load_cast(token)
    cast_members = cast_data.get("cast", {}) if isinstance(cast_data, dict) else {}
    cast_summary = {
        "count": len(cast_members) if isinstance(cast_members, dict) else 0,
        "speakers": sorted(cast_members) if isinstance(cast_members, dict) else [],
    }

    nodes = normalize_draft_nodes(parse_document_lossless(edited_text))
    cards = []
    for node, card_id_info in zip(nodes, identities_data):
        card_id = card_id_info["card_id"]
        card_issues = [
            item for item in diagnostics
            if item.get("card_id") == card_id
            or (not item.get("card_id") and item.get("line_no") == node.line_no)
        ]
        cards.append({
            "card_id": card_id,
            "source_id": card_id_info.get("source_id"),
            "origin": card_id_info.get("origin", "source"),
            "parent_id": card_id_info.get("parent_id"),
            "order_key": card_id_info.get("order_key", "a00000"),
            "line_no": node.line_no,
            "kind": node.kind,
            "raw": node.raw,
            "current": node.fields,
            "review_state": card_id_info.get("review_state", "pending"),
            "edit_state": "unchanged",
            "validation_state": "valid",
            "issues": card_issues,
            "proposal_ids": [],
        })

    pending_count = sum(1 for c in cards if c["review_state"] == "pending")
    unresolved_issues = sum(1 for d in diagnostics if d.get("severity") in ("error", "warning"))
    blocking_errors = sum(1 for d in diagnostics if d.get("severity") == "error")
    compiled_build_id = (
        session.get("last_compiled_build_id")
        if session.get("last_compiled_content_revision") == session.get("content_revision")
        else None
    )
    installed_build_id = (
        session.get("last_installed_build_id")
        if compiled_build_id
        and session.get("last_installed_build_id") == compiled_build_id
        else None
    )

    return {
        "cards": cards,
        "diagnostics": diagnostics,
        "counts": {
            "pending": pending_count,
            "unresolved_issues": unresolved_issues,
            "blocking_errors": blocking_errors,
        },
        "draft_version": session["draft_version"],
        "generation_version": store.generation_version(token),
        "content_revision": session["content_revision"],
        "last_compiled_build_id": compiled_build_id,
        "last_installed_build_id": installed_build_id,
        "last_installed_project": (
            session.get("last_installed_project") if installed_build_id else None
        ),
        "identity_rebuilt": draft.get("identity_rebuilt", False),
        "project": session.get("project"),
        "story_token": session.get("story_token"),
        "bgm_policy": normalize_bgm_policy(session.get("bgm_policy")),
        "annotation_status": annotation_status,
        "cast": cast_summary,
    }


def build_csp_headers() -> Dict[str, str]:
    return {
        "Content-Security-Policy": (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "media-src 'self' blob:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def search_sounds(q: str = "") -> List[Dict[str, Any]]:
    """搜索已登记音效的标签列表（含繁转简匹配）。"""
    try:
        con = db()
        rows = con.execute(
            "SELECT name, label_cn, category FROM sound WHERE name LIKE ? OR label_cn LIKE ?",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
        results = [{"name": r[0], "label_cn": r[1] or "", "category": r[2] or "SE"} for r in rows]
        if q and not results:
            q_raw = str(q).casefold()
            q_s = _zh_t2s(q).casefold()
            results = [
                {"name": r[0], "label_cn": r[1] or "", "category": r[2] or "SE"}
                for r in con.execute("SELECT name, label_cn, category FROM sound")
                if _zh_search_match(q_raw, q_s, r[0], r[1])
            ]
    except Exception:
        results = []

    if not results:
        try:
            idx = json.load(open(INDEX, encoding="utf-8"))
            q_raw = str(q).casefold()
            q_s = _zh_t2s(q).casefold()
            for s in idx.get("sounds", []):
                if not q or q_raw in s.casefold() or q_s in _zh_t2s(s).casefold():
                    results.append({"name": s, "label_cn": "", "category": "SE"})
        except Exception:
            pass

    return results


def get_sound_file(name: str, sound_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取音效物理文件数据与 MIME，支持 PCM16 WAV 承诺。"""
    search_paths = []
    if sound_dir:
        search_paths.append(Path(sound_dir))

    if CFG.get("aa_data"):
        search_paths.append(Path(CFG["aa_data"]) / "sounds")
    search_paths.extend([LAYOUT.out_root, Path(HERE) / "sounds"])

    for sp in search_paths:
        if sp.is_dir():
            for ext in (".wav", ".mp3", ".ogg"):
                fpath = sp / f"{name}{ext}"
                if fpath.is_file():
                    mime = "audio/wav" if ext == ".wav" else ("audio/mpeg" if ext == ".mp3" else "audio/ogg")
                    return {"mime": mime, "data": fpath.read_bytes()}

    # 兜底测试文件
    return None


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "AAStudio"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._apply_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_preview_file(self, path: Path, ctype: str):
        """Stream one already-scoped preview file; audio understands a single bytes range."""
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            start, end, code = 0, size - 1, 200
            range_header = self.headers.get("Range", "")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                if not match:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
                left, right = match.groups()
                if not left and not right:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
                if left:
                    start = int(left)
                    end = int(right) if right else size - 1
                else:
                    length = int(right)
                    start, end = max(0, size - length), size - 1
                if start >= size or end < start:
                    return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
                end = min(end, size - 1); code = 206
            length = end - start + 1
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length)); self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            if code == 206: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._apply_security_headers(); self.end_headers(); handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def _apply_basic_security_headers(self):
        """基础安全头（不含严格 CSP，避免破坏现有内联脚本前端）。"""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _apply_security_headers(self):
        for name, value in build_csp_headers().items():
            self.send_header(name, value)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = unquote(u.path)
        try:
            if p in ("/", "/index.html"):
                f = os.path.join(HERE, "ui.html")
                return self._send(200, open(f, encoding="utf-8").read(),
                                  "text/html; charset=utf-8")
            if p == "/api/state":
                con = db()
                st = assetdb.stats(con)
                model_status = current_model_status()
                if model_status["configured"]:
                    prov = f"{model_status['name']} / {model_status['model']}"
                else:
                    try:
                        with open(LLMCFG, encoding="utf-8") as handle:
                            legacy_model = json.load(handle)
                    except (OSError, ValueError, TypeError):
                        legacy_model = {}
                    prov = (
                        legacy_model.get("provider", "")
                        if isinstance(legacy_model, dict)
                        else ""
                    )
                return self._send(200, {
                    "stats": {k: list(v) for k, v in st.items()},
                    "provider": prov, "story_root": STORY_ROOT,
                    "aa_data": CFG["aa_data"],
                    "spine_cli": str(
                        spine_face_analysis.resolve_spine_cli(
                            CFG.get("spine_cli")
                        )
                        or ""
                    ),
                    "aa_ok": os.path.isdir(CFG["aa_data"])})
            if p == "/api/setup/status":
                return self._send(200, setup_status())
            if p == "/api/diagnostics/runtime":
                return self._send(200, runtime_diagnostics())
            if p == "/api/resources/index":
                return self._send(200, _resource_index_snapshot())
            if p == "/api/resources/preview":
                kind = q.get("kind", "")
                key = q.get("key", "")
                preview = OFFICIAL_PREVIEW_INDEX.resolve(kind, key)
                if preview is None:
                    return self._send(404, {
                        "ok": False,
                        "code": "official_preview_not_found",
                        "e": "官方资源预览不存在",
                    })
                content_type = {
                    ".webp": "image/webp",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                }.get(preview.suffix.casefold(), "application/octet-stream")
                return self._send_preview_file(preview, content_type)
            if p == "/api/browse":
                return self._send(
                    200,
                    browse(
                        q.get("dir") or STORY_ROOT,
                        kind=q.get("kind") or "script",
                    ),
                )
            if p == "/api/story-files/host":
                try:
                    return self._send(200, STORY_FILE_PICKER.list_directory(
                        q.get("entry_token", ""),
                        query=q.get("query", ""),
                        sort=q.get("sort", "name"),
                        direction=q.get("direction", "asc"),
                    ))
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
            if p == "/api/settings/host":
                try:
                    return self._send(200, SETTINGS_FILE_PICKER.list_directory(
                        q.get("entry_token", ""),
                        query=q.get("query", ""),
                        sort=q.get("sort", "name"),
                        direction=q.get("direction", "asc"),
                    ))
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
            if p == "/api/assets/host":
                try:
                    return self._send(200, ASSET_FILE_PICKER.list_directory(
                        q.get("entry_token", ""),
                        query=q.get("query", ""),
                        sort=q.get("sort", "name"),
                        direction=q.get("direction", "asc"),
                    ))
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
            if p == "/api/analyze":
                path = q.get("path", "")
                if not path:
                    path = resolve_file_token(q.get("token", "")) or ""
                return self._send(200, analyze(path))
            if p == "/api/guess":
                path = q.get("path", "")
                if not path:
                    path = resolve_file_token(q.get("token", "")) or ""
                sp = analyze(path).get("speakers", [])
                return self._send(200, guess_mapping(sp))
            if p == "/api/voice-character":
                speaker = str(q.get("speaker") or "").strip()
                if not speaker:
                    return self._send(400, {
                        "ok": False, "code": "speaker_required",
                        "e": "缺少无立绘角色名称",
                    })
                if is_non_character_speaker(speaker):
                    return self._send(400, {
                        "ok": False, "code": "narrator_not_voice",
                        "e": "旁白标记不能创建为无立绘角色",
                    })
                return self._send(200, voice_character_mapping(speaker))
            if p == "/api/characters":
                return self._send(200, list_characters(q.get("q", "")))
            if p == "/api/backgrounds":
                try:
                    background_limit = int(q.get("limit", 80))
                except (TypeError, ValueError):
                    background_limit = 80
                try:
                    background_offset = int(q.get("offset", 0))
                except (TypeError, ValueError):
                    background_offset = 0
                return self._send(200, list_backgrounds(
                    q.get("q", ""), q.get("ready") == "1",
                    limit=background_limit,
                    only_official=q.get("official") == "1",
                    offset=background_offset,
                    with_total=q.get("paged") == "1"))
            if p == "/api/install/options":
                try:
                    return self._send(200, InstallManager().install_options(
                        token=q.get("token", ""),
                        build_id=q.get("build_id", ""),
                    ))
                except AACorruptBundleError as exc:
                    return self._send(400, {
                        "ok": False, "code": "corrupted_bundle", "e": str(exc),
                    })
            if p == "/api/projects":
                root = os.path.join(CFG["aa_data"], "projects")
                names = []
                if os.path.isdir(root):
                    names = sorted(
                        os.path.splitext(name)[0]
                        for name in os.listdir(root)
                        if name.lower().endswith(".aap")
                    )
                return self._send(200, names)
            if p == "/api/sounds":
                return self._send(200, search_sounds(q.get("q", "")))
            if p == "/api/sound/preview":
                s_name = q.get("name", "")
                s_info = get_sound_file(s_name)
                if not s_info:
                    return self._send(404, {"e": "sound file not found"})
                return self._send(200, s_info["data"], s_info["mime"])
            if p == "/api/faces/thumb":
                ident = q.get("ident", "")
                sig = q.get("spine_signature", "")
                outfit = q.get("outfit_key", "")
                face = q.get("face", "")
                v_key = spine_face_analysis.make_variant_key(ident, sig, outfit, face)
                # 尝试从缓存读取变体隔离的表情图片
                cache_dir = LAYOUT.out_root / "spine-face-cache" / sig
                f_path = cache_dir / f"{face}.png"
                if f_path.is_file():
                    return self._send(200, f_path.read_bytes(), "image/png")
                return self._send(404, {"e": f"face thumb not found for key {v_key}"})

            if p == "/api/faces":
                con = db()
                rows = con.execute(
                    "SELECT face_id,raw,label,label_cn FROM face WHERE ident=? "
                    "ORDER BY face_id", (q.get("id", ""),)).fetchall()
                return self._send(200, [dict(r) for r in rows])
            if p == "/api/job":
                return self._send(200, JOB)
            if p == "/api/stories/recent":
                return self._send(200, [
                    public_story_summary(summary)
                    for summary in story_workspace().list_recent()
                ])
            if p == "/api/story/current":
                try:
                    context = resolve_story_context(q.get("story_token", ""))
                    payload = public_story_context(context)
                    if context.source_path is not None:
                        # 不泄漏物理路径，只签发不透明 file_token 供前端恢复源文件。
                        payload["file_token"] = register_file_token(str(context.source_path))
                    return self._send(200, payload)
                except ValueError as exc:
                    return self._send(404, {"ok": False, "code": str(exc), "e": "story not found"})
            if p == "/api/story/assets":
                try:
                    context = resolve_story_context(q.get("story_token", ""))
                    return self._send(200, asset_catalog.list_story_assets(
                        db(), scope=str(context.project_dir)
                    ))
                except ValueError as exc:
                    return self._send(404, {"ok": False, "code": str(exc), "e": "story not found"})
            if p == "/api/assets/library":
                try:
                    story_token = q.get("story_token", "")
                    context = resolve_story_context(story_token) if story_token else None
                    con = db()
                    try:
                        return self._send(200, history_asset_browser().list_library(
                            con, current_context=context
                        ))
                    finally:
                        con.close()
                except ValueError:
                    return self._send(404, {
                        "ok": False, "code": "invalid_story_token", "e": "story not found",
                    })
            if p == "/api/assets/library/preview":
                try:
                    preview, ctype = history_asset_browser().preview_path(
                        q.get("preview_token", "")
                    )
                    return self._send_preview_file(preview, ctype)
                except HistoryAssetError as exc:
                    return self._send(exc.status, {
                        "ok": False, "code": exc.code, "e": str(exc),
                    })
            if p == "/api/assets/library/copies":
                con = db()
                try:
                    payload = history_asset_browser().describe_preview_copies(
                        q.get("preview_token", ""),
                        con=con,
                        draft_store=DraftStore(),
                    )
                    return self._send(200, {"ok": True, **payload})
                except HistoryAssetError as exc:
                    return self._send(
                        exc.status, _library_copy_management_error(exc)
                    )
                finally:
                    con.close()
            if p == "/api/story/assets/preview":
                try:
                    context = resolve_story_context(q.get("story_token", ""))
                except ValueError:
                    return self._send(404, {"ok": False, "code": "invalid_story_token", "e": "story not found"})
                kind = str(q.get("kind", ""))
                aa_key = str(q.get("key", ""))
                preview = asset_catalog.story_asset_preview(
                    db(), scope=str(context.project_dir), kind=kind, aa_key=aa_key,
                )
                if not preview:
                    return self._send(404, {"ok": False, "code": "asset_preview_missing", "e": "asset preview not found"})
                mime_by_kind = {
                    "background": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"},
                    "character": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"},
                    "sound": {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"},
                }
                ctype = mime_by_kind.get(kind, {}).get(preview.suffix.casefold())
                try:
                    root = context.project_dir.resolve(strict=True)
                    final = preview.resolve(strict=True)
                    final.relative_to(root)
                except (OSError, ValueError):
                    return self._send(404, {"ok": False, "code": "asset_preview_missing", "e": "asset preview not found"})
                if not ctype or not final.is_file():
                    return self._send(404, {"ok": False, "code": "asset_preview_missing", "e": "asset preview not found"})
                return self._send_preview_file(final, ctype)
            if p == "/api/history/projects":
                return self._send(200, history_asset_browser().list_projects())
            if p == "/api/history/assets":
                try:
                    return self._send(200, history_asset_browser().list_assets(
                        q.get("history_token", "")
                    ))
                except HistoryAssetError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
            if p == "/api/draft":
                token = q.get("token")
                if not token:
                    return self._send(400, {"e": "missing token"})
                try:
                    _validate_client_draft_token(token)
                    return self._send(200, get_draft_detail_data(token))
                except InvalidDraftTokenError as exc:
                    return self._send(400, _invalid_draft_token_payload(exc))
                except FileNotFoundError as exc:
                    return self._send(404, {"e": str(exc)})
            if p == "/api/drafts":
                store = DraftStore()
                return self._send(200, store.list_sessions())
            if p.startswith("/api/jobs/"):
                job_id = p[len("/api/jobs/"):]
                job_info = global_job_manager.get(job_id)
                if not job_info:
                    return self._send(404, {"e": "job not found"})
                return self._send(200, job_info)
            if p == "/api/review/status":
                token = q.get("token")
                if not token:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token"})
                try:
                    _validate_client_draft_token(token)
                    store = DraftStore()
                    store.assert_review_ready(token)
                    ready = True
                except InvalidDraftTokenError as exc:
                    return self._send(400, _invalid_draft_token_payload(exc))
                except Exception:
                    ready = False
                detail = get_draft_detail_data(token, store=DraftStore())
                counts = detail["counts"]
                return self._send(200, {
                    "ok": True,
                    "ready": ready,
                    "pending": counts["pending"],
                    "unresolved_issues": counts["unresolved_issues"],
                    "blocking_errors": counts["blocking_errors"],
                    "draft_version": detail["draft_version"],
                    "content_revision": detail["content_revision"],
                })
            if p == "/api/assets/faces/job":
                return self._send(200, face_job_snapshot())
            if p == "/api/assets/faces/labels":
                con = db()
                try:
                    return self._send(200, face_labels_payload(
                        con, aa_key=q.get("aa_key", ""), sha256=q.get("sha256", "")
                    ))
                except KeyError as exc:
                    return self._send(404, {"ok": False, "code": "face_labels_not_found", "e": str(exc)})
                except ValueError as exc:
                    return self._send(400, {"ok": False, "code": "invalid_face_labels_request", "e": str(exc)})
                finally:
                    con.close()
            if p == "/api/assets/faces/preview":
                con = db()
                try:
                    preview = face_preview_path(
                        con,
                        aa_key=q.get("aa_key", ""),
                        sha256=q.get("sha256", ""),
                        face_id=q.get("face_id", ""),
                    )
                    return self._send_preview_file(preview, "image/png")
                except (KeyError, ValueError):
                    return self._send(404, {"ok": False, "code": "face_preview_not_found", "e": "表情预览不存在"})
                finally:
                    con.close()
            if p == "/api/llm/profiles":
                return self._send(200, MODEL_PROFILES.public_state())
            if p == "/api/llm/workbench":
                MODEL_PROFILES.migrate_legacy_profiles()
                return self._send(200, MODEL_PROFILES.public_state(include_links=True))
            if p.startswith("/thumb/bg/"):
                name = unquote(p[len("/thumb/bg/"):])
                f = background_preview_path(name)
                if not f:
                    return self._send(404, {"e": "no image"})
                return self._send(200, thumb(f, int(q.get("px", 240)), "bg_" + name),
                                  "image/jpeg")
            if p.startswith("/thumb/av/"):
                key = unquote(p[len("/thumb/av/"):])
                f = None
                con = db()
                try:
                    for row in con.execute("SELECT ident,avatar,spine FROM character"):
                        avatar_key = Path(
                            str(row["avatar"] or "").replace("\\", "/")
                        ).name
                        if key in {avatar_key, str(row["spine"] or ""), str(row["ident"] or "")}:
                            f = character_avatar_path(
                                row["avatar"], row["spine"]
                            )
                            if not f:
                                f = registered_character_avatar_path(con, row["ident"])
                            break
                finally:
                    con.close()
                if not f:
                    f = character_avatar_path(key, key)
                if not f:
                    return self._send(404, {"e": "no avatar"})
                data, content_type = avatar_thumb(
                    f, int(q.get("px", 96)), "av_" + p[-40:]
                )
                return self._send(200, data, content_type)
            if p.startswith("/js/"):
                rel_path = unquote(p[4:])
                if not rel_path.endswith(".js"):
                    return self._send(404, {"e": "js file not found"})
                safe_path = os.path.realpath(os.path.join(HERE, "js", rel_path))
                js_dir = os.path.realpath(os.path.join(HERE, "js"))
                if os.path.commonpath([safe_path, js_dir]) != js_dir or not os.path.isfile(safe_path):
                    return self._send(404, {"e": "js file not found"})
                return self._send(200, open(safe_path, "r", encoding="utf-8").read(), "application/javascript; charset=utf-8")
            if p.startswith("/css/"):
                rel_path = unquote(p[5:])
                if not rel_path.endswith(".css"):
                    return self._send(404, {"e": "css file not found"})
                safe_path = os.path.realpath(os.path.join(HERE, "css", rel_path))
                css_dir = os.path.realpath(os.path.join(HERE, "css"))
                if os.path.commonpath([safe_path, css_dir]) != css_dir or not os.path.isfile(safe_path):
                    return self._send(404, {"e": "css file not found"})
                return self._send(200, open(safe_path, "r", encoding="utf-8").read(), "text/css; charset=utf-8")
            if p == "/branding/halocue-favicon.png":
                favicon = Path(HERE) / "branding" / "halocue-favicon.png"
                if not favicon.is_file():
                    return self._send(404, {"e": "brand asset not found"})
                return self._send(200, favicon.read_bytes(), "image/png")
            return self._send(404, {"e": "not found"})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"e": str(e)})

    def do_PATCH(self):
        p = unquote(urlparse(self.path).path)
        if not p.startswith("/api/assets/faces/labels/"):
            return self._send(404, {"e": "not found"})
        face_id = p.rsplit("/", 1)[-1]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except (TypeError, ValueError):
            return self._send(400, {"ok": False, "code": "invalid_json", "e": "请求内容不是有效 JSON"})
        con = db()
        try:
            result = update_face_label_payload(
                con,
                aa_key=data.get("aa_key", ""),
                sha256=data.get("sha256", ""),
                face_id=face_id,
                patch=data.get("patch") or {},
                expected_version=int(data.get("version") or 0),
            )
            return self._send(200, result)
        except KeyError as exc:
            return self._send(404, {"ok": False, "code": "face_label_not_found", "e": str(exc)})
        except ValueError as exc:
            code = "face_label_conflict" if "版本" in str(exc) else "invalid_face_label"
            return self._send(409 if code == "face_label_conflict" else 400, {
                "ok": False, "code": code, "e": str(exc),
            })
        finally:
            con.close()

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/runtime/stop":
            if not getattr(self.server, "halocue_allow_api_shutdown", False):
                return self._send(404, {"ok": False, "e": "not found"})
            self._send(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        n = int(self.headers.get("Content-Length") or 0)
        if p == "/api/story-files/upload":
            if n > 10 * 1024 * 1024:
                return self._send(413, {
                    "ok": False, "code": "story_file_too_large", "e": "剧情文本不能超过 10 MiB",
                })
            try:
                name = unquote(self.headers.get("X-AA-Filename", ""))
                result = STORY_FILE_PICKER.upload(name, self.rfile.read(n))
                return self._send(200, {"ok": True, **result})
            except StoryFilePickerError as exc:
                return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        try:
            _validate_client_draft_token(_client_draft_token_for_post(p, data))
        except InvalidDraftTokenError as exc:
            return self._send(400, _invalid_draft_token_payload(exc))
        try:
            if p == "/api/picker":
                path_val = data.get("path")
                if not path_val or not os.path.exists(path_val):
                    return self._send(400, {"ok": False, "e": "路径无效或不存在"})
                ft_token = register_file_token(path_val)
                return self._send(200, {"ok": True, "file_token": ft_token})

            if p == "/api/story-files/select":
                try:
                    return self._send(200, {
                        "ok": True,
                        **STORY_FILE_PICKER.select(str(data.get("entry_token") or "")),
                    })
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})

            if p == "/api/assets/select":
                try:
                    return self._send(200, {
                        "ok": True,
                        **ASSET_FILE_PICKER.select(str(data.get("entry_token") or "")),
                    })
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})

            if p == "/api/settings/entry":
                try:
                    token = str(data.get("entry_token") or "")
                    entry = SETTINGS_FILE_PICKER._resolve_entry(token)
                    return self._send(200, {
                        "ok": True,
                        "entry_token": token,
                        "name": entry.path.name,
                        "kind": entry.kind,
                    })
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})

            if p == "/api/settings/aa-install":
                try:
                    entry_token = str(data.get("entry_token") or "").strip()
                    typed_install = str(data.get("aa_install") or "").strip()
                    if entry_token:
                        selection = SETTINGS_FILE_PICKER.resolve_entry_path(entry_token)
                    elif typed_install:
                        selection = Path(typed_install).expanduser()
                    else:
                        return self._send(400, {
                            "ok": False,
                            "code": "aa_install_required",
                            "e": "请选择 AzureArchive.exe 或 AA 安装目录",
                        })
                    selection = Path(selection).expanduser()
                    if (
                        not selection.is_file()
                        or selection.name.casefold() != "azurearchive.exe"
                    ):
                        return self._send(400, {
                            "ok": False,
                            "code": "aa_executable_required",
                            "e": "请选择 AA 主程序 AzureArchive.exe",
                        })
                    config_path = runtime_config_path()
                    discovery = discover_aa(
                        selection=selection,
                        config_path=config_path,
                    )
                    selected_data = str(data.get("aa_data") or "").strip()
                    if discovery.requires_selection:
                        candidates = [
                            {"path": str(row.path), "source": row.source}
                            for row in discovery.data_candidates
                            if row.valid
                        ]
                        if not selected_data:
                            return self._send(409, {
                                "ok": False,
                                "code": "aa_workspace_selection_required",
                                "e": "发现多个 AA 工作区，请明确选择一个",
                                "candidates": candidates,
                            })
                        selected_path = Path(selected_data).expanduser().resolve()
                        allowed = {
                            os.path.normcase(str(row.path.resolve()))
                            for row in discovery.data_candidates
                            if row.valid
                        }
                        if os.path.normcase(str(selected_path)) not in allowed:
                            return self._send(400, {
                                "ok": False,
                                "code": "invalid_aa_workspace_selection",
                                "e": "选择的 AA 工作区不在本次发现结果中",
                            })
                        discovery = discover_aa(
                            selection=selected_path,
                            config_path=config_path,
                        )
                    if discovery.projects is None or not discovery.projects.is_dir():
                        return self._send(400, {
                            "ok": False,
                            "code": "aa_workspace_not_found",
                            "e": "没有找到有效的 AA projects 工作区",
                        })
                    _write_settings_config(
                        aa_executable=str(discovery.executable or ""),
                        aa_data=str(discovery.data or ""),
                        aa_cache=str(discovery.resource_cache or ""),
                    )
                    CFG["aa_data"] = str(discovery.data)
                    CFG["overrides"] = str(discovery.overrides or "") or None
                    _trigger_resource_index_if_missing(discovery)
                    return self._send(200, {
                        "ok": True,
                        "restart_required": False,
                        "aa": _public_aa_status(discovery),
                    })
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {
                        "ok": False,
                        "code": exc.code,
                        "e": str(exc),
                    })
                except (OSError, TypeError, ValueError) as exc:
                    return self._send(400, {
                        "ok": False,
                        "code": "invalid_aa_install",
                        "e": str(exc),
                    })

            if p == "/api/resources/index":
                status, payload = _start_resource_index()
                return self._send(status, payload)

            if p == "/api/stories/open":
                try:
                    context = open_story(data.get("file_token", ""), data.get("project"))
                    return self._send(200, public_story_context(context))
                except InvalidProjectNameError as exc:
                    return self._send(400, {
                        "ok": False, "code": "invalid_project_name", "e": str(exc),
                    })
                except ValueError as exc:
                    code = str(exc)
                    return self._send(400, {"ok": False, "code": code, "e": code})

            if p == "/api/assets/library/background-label":
                expected_fields = {"aa_key", "sha256"}
                if not isinstance(data, dict) or set(data) != expected_fields:
                    return self._send(400, {
                        "ok": False, "code": "invalid_background_label_request",
                        "e": "背景标注请求无效",
                    })
                try:
                    queued = queue_background_label_analysis(data)
                    return self._send(202, {"ok": True, **queued})
                except KeyError:
                    return self._send(404, {
                        "ok": False, "code": "library_background_not_found",
                        "e": "没有可用于场景识别的已登记背景副本",
                    })
                except ValueError as exc:
                    return self._send(400, {
                        "ok": False, "code": "invalid_background_label_request",
                        "e": str(exc),
                    })

            if p == "/api/assets/library/background-labels":
                expected_fields = {"aa_key", "sha256", "labels"}
                if not isinstance(data, dict) or set(data) != expected_fields:
                    return self._send(400, {
                        "ok": False, "code": "invalid_background_label_request",
                        "e": "背景标注请求无效",
                    })
                con = db()
                try:
                    result = asset_catalog.update_background_labels(
                        con,
                        aa_key=data.get("aa_key", ""),
                        sha256=data.get("sha256", ""),
                        labels=data.get("labels"),
                        status="ready",
                        error="",
                    )
                    return self._send(200, {"ok": True, **result})
                except KeyError:
                    return self._send(404, {
                        "ok": False, "code": "library_background_not_found",
                        "e": "素材履历中不存在该已登记背景",
                    })
                except ValueError as exc:
                    return self._send(400, {
                        "ok": False, "code": "invalid_background_label_request",
                        "e": str(exc),
                    })
                finally:
                    con.close()

            if p == "/api/assets/library/profile":
                try:
                    result = asset_catalog.update_library_profile(
                        db(),
                        kind=data.get("kind", ""),
                        aa_key=data.get("aa_key", ""),
                        sha256=data.get("sha256", ""),
                        asset_role=data.get("asset_role", ""),
                        series_name=data.get("series_name", ""),
                    )
                    return self._send(200, {"ok": True, **result})
                except KeyError:
                    return self._send(404, {
                        "ok": False,
                        "code": "library_asset_not_found",
                        "e": "素材履历中不存在该已登记的自定义素材",
                    })
                except ValueError as exc:
                    return self._send(400, {
                        "ok": False,
                        "code": "invalid_library_profile",
                        "e": str(exc),
                    })

            if p == "/api/assets/library/character/face-analysis":
                con = db()
                try:
                    target = asset_catalog.library_character_analysis_target(
                        con,
                        aa_key=data.get("aa_key", ""),
                        sha256=data.get("sha256", ""),
                    )
                except KeyError:
                    return self._send(404, {
                        "ok": False,
                        "code": "library_character_not_found",
                        "e": "没有可用于表情标注的已登记骨骼副本",
                    })
                except ValueError as exc:
                    return self._send(400, {
                        "ok": False,
                        "code": "invalid_face_analysis_request",
                        "e": str(exc),
                    })
                finally:
                    con.close()
                queued = queue_face_analysis({
                    **target,
                    "force_vision": bool(data.get("force_vision")),
                })
                return self._send(200, {
                    "ok": bool(queued.get("started")),
                    "status": str(queued.get("status") or ""),
                    "message": str(queued.get("message") or ""),
                    "ident": target["ident"],
                    "name": target["name"],
                })

            if p == "/api/story/assets/copy":
                try:
                    context = resolve_story_context(str(data.get("story_token") or ""))
                    result = history_asset_browser().copy_to_story(
                        str(data.get("history_asset_token") or ""), context, con=db()
                    )
                    return self._send(200, _public_history_copy(result))
                except ValueError:
                    return self._send(404, {
                        "ok": False, "code": "invalid_story_token", "e": "story not found",
                    })
                except HistoryAssetError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})

            if p == "/api/assets/library/copy-to-story":
                expected_fields = {"story_token", "kind", "aa_key", "sha256", "source_copy_token"}
                if not isinstance(data, dict) or set(data) != expected_fields:
                    return self._send(400, _library_copy_error("library_copy_mismatch"))
                try:
                    context = resolve_story_context(str(data["story_token"] or ""))
                except ValueError:
                    return self._send(404, _library_copy_error("invalid_story_token"))
                try:
                    browser = history_asset_browser()
                    copy = browser._library_copy_for_token(str(data["source_copy_token"] or ""))
                    if (
                        str(data["kind"]) != copy.kind
                        or str(data["aa_key"]) != copy.aa_key
                        or str(data["sha256"]) != copy.sha256
                    ):
                        raise HistoryAssetError(
                            "library_copy_mismatch", "library copy metadata does not match", 409
                        )
                    con = db()
                    try:
                        result = browser.copy_library_asset(
                            str(data["source_copy_token"]), context, con=con
                        )
                        card = _library_story_asset_card(
                            asset_catalog.list_story_assets(con, scope=str(context.project_dir)),
                            kind=result["kind"], aa_key=result["aa_key"],
                        )
                    finally:
                        con.close()
                    if card is None:
                        raise HistoryAssetError("catalog_failed", "copied asset is not available", 500)
                    return self._send(200, {"ok": True, "state": result["state"], "asset": card})
                except HistoryAssetError as exc:
                    return self._send(exc.status, _library_copy_error(exc.code))

            if p == "/api/assets/library/remove-copy":
                expected_fields = {"copy_token", "confirm_chapter"}
                if not isinstance(data, dict) or set(data) != expected_fields:
                    error = HistoryAssetError(
                        "copy_confirmation_mismatch", "invalid removal confirmation", 400
                    )
                    return self._send(400, _library_copy_management_error(error))
                con = db()
                try:
                    result = history_asset_browser().remove_copy(
                        str(data["copy_token"] or ""),
                        con=con,
                        draft_store=DraftStore(),
                        confirm_chapter=str(data["confirm_chapter"] or ""),
                    )
                    return self._send(200, {"ok": True, **result})
                except HistoryAssetError as exc:
                    return self._send(
                        exc.status, _library_copy_management_error(exc)
                    )
                finally:
                    con.close()

            if p == "/api/story/assets/scan-inbox":
                try:
                    context = resolve_story_context(str(data.get("story_token") or ""))
                    return self._send(200, scan_story_inbox(context, con=db()))
                except ValueError:
                    return self._send(404, {
                        "ok": False, "code": "invalid_story_token", "e": "story not found",
                    })
                except Exception as exc:
                    return self._send(500, {"ok": False, "e": str(exc)})

            if p.startswith("/api/drafts/") and "/backgrounds/" in p and p.endswith("/resolve"):
                parts = [pt for pt in p.split("/") if pt]
                # /api/drafts/<token>/backgrounds/<request_id>/resolve
                if len(parts) == 6 and parts[1] == "drafts" and parts[3] == "backgrounds":
                    token = parts[2]
                    request_card_id = parts[4]
                    bg_name = str(data.get("bg_name") or "").strip()
                    expected_ver = data.get("expected_draft_version", 1)
                    if not bg_name:
                        return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 bg_name"})
                    try:
                        store = DraftStore()
                        res = store.resolve_background_request(token=token, card_id=request_card_id, bg_name=bg_name, expected_draft_version=expected_ver)
                        payload = {"ok": True, "draft_version": res["session"]["draft_version"], "content_revision": res["session"]["content_revision"]}
                        merged_backgrounds = int(res.get("merged_backgrounds") or 0)
                        if merged_backgrounds:
                            payload["merged_backgrounds"] = merged_backgrounds
                        return self._send(200, payload)
                    except RevisionConflictError as exc:
                        return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
                    except KeyError as exc:
                        return self._send(404, {"ok": False, "code": "card_not_found", "e": str(exc)})
                    except Exception as exc:
                        return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/settings/aa-data":
                try:
                    if data.get("entry_token"):
                        path = str(SETTINGS_FILE_PICKER.resolve_entry_path(
                            str(data.get("entry_token")), expected_kind="directory"
                        ))
                    else:
                        path = str(data.get("aa_data") or "").strip()
                except StoryFilePickerError as exc:
                    return self._send(exc.status, {"ok": False, "code": exc.code, "e": str(exc)})
                if not path or not os.path.isdir(os.path.join(path, "projects")):
                    return self._send(400, {"ok": False, "code": "invalid_aa_data", "e": "该目录下没有 projects 文件夹，请检查路径"})
                try:
                    _write_settings_config(aa_data=path)
                except OSError as exc:
                    return self._send(500, {"ok": False, "code": "write_failed", "e": str(exc)})
                return self._send(200, {"ok": True, "path": path, "e": "已保存，请重启程序后生效"})

            if p == "/api/settings/spine-cli":
                try:
                    if data.get("entry_token"):
                        path = SETTINGS_FILE_PICKER.resolve_entry_path(
                            str(data.get("entry_token")), expected_kind="file"
                        )
                    else:
                        path = Path(str(data.get("spine_cli") or "").strip()).expanduser()
                    path = path.resolve()
                except (OSError, StoryFilePickerError) as exc:
                    code = exc.code if isinstance(exc, StoryFilePickerError) else "invalid_spine_cli"
                    return self._send(400, {"ok": False, "code": code, "e": str(exc)})
                if not path.is_file():
                    return self._send(400, {"ok": False, "code": "invalid_spine_cli", "e": "Spine 命令行程序文件不存在，请选择 Spine.com"})
                try:
                    _write_settings_config(spine_cli=str(path))
                    CFG["spine_cli"] = str(path)
                except OSError as exc:
                    return self._send(500, {"ok": False, "code": "write_failed", "e": str(exc)})
                return self._send(200, {"ok": True, "path": str(path), "e": "Spine 命令行路径已保存"})

            if p == "/api/drafts/import":
                ft_token = data.get("file_token")
                if not ft_token:
                    return self._send(400, {"ok": False, "code": "invalid_file_token", "e": "缺少 file_token"})
                realpath = resolve_file_token(ft_token)
                if not realpath or not os.path.isfile(realpath):
                    return self._send(400, {"ok": False, "code": "invalid_file_token", "e": "无效或过期的 file_token"})
                try:
                    context = inherit_story_context(data)
                except StoryProjectMismatchError:
                    return self._send(409, {"ok": False, "code": "project_mismatch", "e": "project does not match story"})
                except ValueError as exc:
                    return self._send(400, {"ok": False, "code": str(exc), "e": "invalid story token"})
                if context:
                    project = context.project
                else:
                    try:
                        project = validate_windows_path_component(
                            str(data.get("project") or "未命名工程"),
                            label="project name",
                        )
                    except ValueError as exc:
                        return self._send(400, {
                            "ok": False, "code": "invalid_project_name", "e": str(exc),
                        })
                content = Path(realpath).read_text(encoding="utf-8")
                draft_token = f"draft-{uuid.uuid4().hex[:12]}"
                store = DraftStore()
                res = store.create_draft(
                    token=draft_token, text=content, project=project, source_text=content,
                    story_token=context.story_token if context else None,
                    bgm_policy=context.bgm_default if context else None,
                )
                if context:
                    story_workspace().set_latest_draft_token(context.story_token, draft_token)
                return self._send(200, {"ok": True, "draft_token": draft_token, "project": project})

            if p == "/api/review/approve":
                token = data.get("token")
                card_ids = data.get("card_ids")
                expected_ver = data.get("expected_draft_version", 1)
                try:
                    store = DraftStore()
                    res = store.batch_approve_reviews(token=token, card_ids=card_ids, expected_draft_version=expected_ver)
                    return self._send(200, {"ok": True, "draft_version": res["session"]["draft_version"], "content_revision": res["session"]["content_revision"]})
                except Exception as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})

            if p == "/api/compile":
                token = data.get("token")
                expected_ver = data.get("expected_draft_version", 1)
                store = DraftStore()
                try:
                    store.assert_review_ready(token)
                except Exception as exc:
                    return self._send(409, {
                        "ok": False,
                        "code": getattr(exc, "code", "review_pending"),
                        "e": str(exc),
                    })

                bundle_mgr = BuildBundleManager(
                    store=store,
                    output_root=RUNTIME_LAYOUT.output_root,
                    resource_index_path=RUNTIME_LAYOUT.resource_index_path,
                    aa_data=CFG.get("aa_data"),
                )
                try:
                    build_id = bundle_mgr.create_compile_snapshot(token=token, expected_draft_version=expected_ver)
                except CompileInputStaleError as exc:
                    return self._send(409, {"ok": False, "code": "compile_input_stale", "e": str(exc)})

                def build_worker_task(job):
                    return bundle_mgr.execute_build_worker(token=token, build_id=build_id)

                job_id = global_job_manager.submit(build_worker_task, label=f"compile:{token}", prefix="compile-")
                return self._send(202, {"ok": True, "job_id": job_id, "build_id": build_id})

            if p == "/api/install":
                token = data.get("token")
                build_id = data.get("build_id")
                install_mgr = InstallManager()
                try:
                    res = install_mgr.install_build(
                        token=token,
                        build_id=build_id,
                        category=data.get("category", ""),
                        story_name=data.get("story_name"),
                    )
                    return self._send(200, res)
                except ReviewPendingError as exc:
                    return self._send(409, {"ok": False, "code": exc.code, "e": str(exc)})
                except AARunningError as exc:
                    return self._send(423, {"ok": False, "code": "aa_running", "e": str(exc)})
                except AAInstallTargetExistsError as exc:
                    return self._send(409, {
                        "ok": False, "code": "install_target_exists", "e": str(exc),
                    })
                except AACorruptBundleError as exc:
                    return self._send(400, {"ok": False, "code": "corrupted_bundle", "e": str(exc)})
                except ValueError as exc:
                    return self._send(400, {
                        "ok": False, "code": "invalid_project_name", "e": str(exc),
                    })
                except Exception as exc:
                    return self._send(500, {"ok": False, "e": str(exc)})

            if p.startswith("/api/proposals/") or p.startswith("/api/fixes/"):
                parts = [pt for pt in p.split("/") if pt]
                # /api/proposals/<id>/approve|reject or /api/fixes/<id>/accept|reject
                if len(parts) == 4:
                    prop_id = parts[2]
                    action = parts[3]
                    token = data.get("token")
                    expected_ver = data.get("expected_draft_version", 1)
                    try:
                        store = DraftStore()
                        res = store.handle_proposal(token=token, proposal_id=prop_id, action=action, expected_draft_version=expected_ver)
                        return self._send(200, {"ok": True, "draft_version": res["session"]["draft_version"], "content_revision": res["session"]["content_revision"]})
                    except Exception as exc:
                        return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})

            if p == "/api/cards/update":
                token = data.get("token")
                card_id = data.get("card_id")
                patch = data.get("patch")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not card_id or not isinstance(patch, dict):
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/card_id/patch"})
                try:
                    store = DraftStore()
                    res = store.update_card_content(
                        token=token, card_id=card_id, patch=patch,
                        expected_draft_version=expected_ver)
                    return self._send(200, {
                        "ok": True,
                        "draft_version": res["session"]["draft_version"],
                        "content_revision": res["session"]["content_revision"],
                        "edited_text": res["edited_text"],
                    })
                except RevisionConflictError as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
                except Exception as exc:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/cards/insert":
                token = data.get("token")
                after_card_id = data.get("after_card_id")
                kind = data.get("kind")
                payload = data.get("payload")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not kind or not isinstance(payload, dict):
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/kind/payload"})
                try:
                    store = DraftStore()
                    res = store.insert_card(
                        token=token, after_card_id=after_card_id, kind=kind, payload=payload,
                        origin="manual", expected_draft_version=expected_ver)
                    return self._send(200, {
                        "ok": True,
                        "draft_version": res["session"]["draft_version"],
                        "content_revision": res["session"]["content_revision"],
                    })
                except RevisionConflictError as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
                except Exception as exc:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/cards/move":
                token = data.get("token")
                card_id = data.get("card_id")
                before_card_id = data.get("before_card_id")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not card_id:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/card_id"})
                try:
                    store = DraftStore()
                    res = store.move_card(
                        token=token, card_id=card_id, before_card_id=before_card_id,
                        expected_draft_version=expected_ver)
                    return self._send(200, {
                        "ok": True,
                        "draft_version": res["session"]["draft_version"],
                        "content_revision": res["session"]["content_revision"],
                    })
                except RevisionConflictError as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
                except Exception as exc:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/preflight/background-binding":
                try:
                    context = resolve_story_context(str(data.get("story_token") or ""))
                except ValueError:
                    return self._send(404, {
                        "ok": False, "code": "invalid_story_token", "e": "story not found",
                    })
                selector = data.get("selector")
                requested_binding = data.get("binding")
                if not isinstance(selector, dict) or not isinstance(requested_binding, dict):
                    return self._send(400, {
                        "ok": False, "code": "invalid_background_binding",
                        "e": "selector and binding are required",
                    })
                aa_key = str(requested_binding.get("aa_key") or "").strip()
                con = db()
                try:
                    backgrounds = asset_catalog.list_story_assets(
                        con, scope=str(context.project_dir)
                    ).get("backgrounds", [])
                    official = con.execute(
                        """SELECT name,label FROM bg
                           WHERE name=? COLLATE NOCASE AND hash IS NOT NULL
                           LIMIT 1""",
                        (aa_key,),
                    ).fetchone()
                finally:
                    con.close()
                background = next((
                    item for item in backgrounds
                    if str(item.get("aa_key") or "").casefold() == aa_key.casefold()
                    and item.get("preview_available")
                ), None)
                if background is None and official is None:
                    return self._send(404, {
                        "ok": False, "code": "background_not_registered",
                        "e": "background is not available in this story or the official catalog",
                    })
                if background is not None:
                    labels = background_labeler.normalize_background_labels(
                        background.get("labels")
                    )
                    selected_label = labels.get("label") or str(
                        background.get("name") or aa_key
                    )
                    binding_source = "custom"
                    preview_source = "story"
                    preview_available = True
                else:
                    aa_key = str(official["name"])
                    selected_label = str(official["label"] or official["name"])
                    binding_source = "official"
                    preview_source = "official"
                    preview_available = _background_preview_available(aa_key)
                try:
                    updated = story_workspace().bind_preflight_background(
                        context.story_token,
                        selector,
                        {
                            "aa_key": aa_key,
                            "selected_label": selected_label,
                            "source": binding_source,
                            "preview_source": preview_source,
                            "preview_available": preview_available,
                        },
                    )
                except ValueError as exc:
                    return self._send(409, {
                        "ok": False, "code": "background_binding_rejected", "e": str(exc),
                    })
                return self._send(200, {
                    "ok": True,
                    "preflight_snapshot": public_story_context(updated).get(
                        "preflight_snapshot"
                    ),
                })

            if p == "/api/preflight/approve":
                try:
                    context = resolve_story_context(str(data.get("story_token") or ""))
                    if not isinstance(data.get("approved"), bool):
                        return self._send(400, {
                            "ok": False, "code": "invalid_preflight_approval",
                            "e": "approved must be a boolean",
                        })
                    registry = story_workspace()
                    if isinstance(data.get("characters"), list):
                        registry.update_preflight_mapping(context.story_token, data["characters"])
                    updated = registry.set_preflight_approved(context.story_token, data["approved"])
                    return self._send(200, {
                        "ok": True,
                        "preflight_snapshot": public_story_context(updated).get(
                            "preflight_snapshot"
                        ),
                    })
                except (KeyError, ValueError) as exc:
                    return self._send(404, {
                        "ok": False, "code": "preflight_snapshot_not_found",
                        "e": str(exc),
                    })

            if p == "/api/preflight":
                try:
                    context = inherit_story_context(data)
                except StoryProjectMismatchError:
                    return self._send(409, {"ok": False, "code": "project_mismatch", "e": "project does not match story"})
                except ValueError:
                    return self._send(400, {"ok": False, "code": "invalid_story_token", "e": "invalid story token"})
                if not context:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "初审必须绑定当前剧情"})
                script = str(context.source_path or "")
                if not script or not os.path.isfile(script):
                    return self._send(400, {"ok": False, "code": "invalid_story_source", "e": "当前剧情原文不存在，请重新打开剧情"})
                task_payload = {
                    "script": script,
                    "scope": str(context.project_dir),
                    "story_token": context.story_token,
                    "model_profile_id": data.get("model_profile_id"),
                }
                job_id = global_job_manager.submit(
                    lambda job: preflight_story_worker(task_payload),
                    label="preflight", prefix="preflight-",
                )
                return self._send(202, {"ok": True, "job_id": job_id, "story_token": context.story_token})

            if p == "/api/annotate":
                mapping = data.get("mapping")
                try:
                    story_type = normalize_story_type(data.get("story_type"))
                    if "story_type" in data:
                        data["story_type"] = story_type
                except ValueError:
                    return self._send(400, {
                        "ok": False, "code": "invalid_story_type",
                        "e": "invalid story type",
                    })
                try:
                    context = inherit_story_context(data)
                except StoryProjectMismatchError:
                    return self._send(409, {"ok": False, "code": "project_mismatch", "e": "project does not match story"})
                except ValueError as exc:
                    return self._send(400, {"ok": False, "code": str(exc), "e": "invalid story token"})
                if context:
                    script = str(context.source_path or "")
                    if not script or not os.path.isfile(script):
                        return self._send(400, {"ok": False, "code": "invalid_story_source", "e": "当前剧情原文不存在，请重新打开剧情"})
                    data.pop("file_token", None)
                    data["script"] = script
                else:
                    script = data.get("script")
                if not script or not isinstance(mapping, dict) or not os.path.isfile(script):
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少有效的 script 与 mapping"})

                def annotate_task(job):
                    try:
                        result = annotate_draft_worker(data, job=job)
                    except TypeError as exc:
                        if "unexpected keyword argument 'job'" not in str(exc):
                            raise
                        result = annotate_draft_worker(data)
                    if result.get("cancelled"):
                        job.mark_cancelled()
                    if context and result.get("draft_token"):
                        story_workspace().set_latest_draft_token(
                            context.story_token, result["draft_token"]
                        )
                    return result

                job_id = global_job_manager.submit(
                    annotate_task, label="annotate", prefix="annotate-")
                return self._send(202, {"ok": True, "job_id": job_id})

            if p == "/api/draft/cast/update":
                token = data.get("token")
                speaker = data.get("speaker")
                mapping = data.get("mapping")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not speaker or not isinstance(mapping, dict):
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/speaker/mapping"})
                try:
                    store = DraftStore()
                    res = store.update_cast(
                        token=token, speaker=speaker, mapping=mapping,
                        expected_draft_version=expected_ver)
                    return self._send(200, {
                        "ok": True,
                        "draft_version": res["session"]["draft_version"],
                        "content_revision": res["session"]["content_revision"],
                    })
                except RevisionConflictError as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
                except Exception as exc:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/review/reset":
                token = data.get("token")
                card_id = data.get("card_id")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not card_id:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/card_id"})
                try:
                    store = DraftStore()
                    res = store.update_card_review(
                        token=token, card_id=card_id, review_state="pending",
                        expected_draft_version=expected_ver)
                    return self._send(200, {
                        "ok": True,
                        "draft_version": res["session"]["draft_version"],
                        "content_revision": res["session"]["content_revision"],
                    })
                except Exception as exc:
                    return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})

            if p.startswith("/api/jobs/") and p.endswith("/cancel"):
                job_id = p[len("/api/jobs/"):-len("/cancel")]
                if not job_id:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 job_id"})
                job = global_job_manager.cancel(job_id)
                if job is None:
                    return self._send(404, {"ok": False, "code": "job_not_found", "e": "任务不存在"})
                return self._send(200, {"ok": True, "job": job})

            if p == "/api/validate":
                token = data.get("token")
                if not token:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token"})
                try:
                    store = DraftStore()
                    draft = store.load_draft(token)
                    diagnostics = draft["diagnostics"]
                    blocking = sum(1 for d in diagnostics if d.get("severity") == "error")
                    return self._send(200, {
                        "ok": True,
                        "blocking_errors": blocking,
                        "diagnostics": diagnostics,
                        "draft_version": draft["session"]["draft_version"],
                        "content_revision": draft["session"]["content_revision"],
                    })
                except Exception as exc:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": str(exc)})

            if p == "/api/llm/profiles/save":
                return self._send(200, MODEL_PROFILES.save_profile(data))
            if p == "/api/llm/connections/save":
                return self._send(200, MODEL_PROFILES.save_connection(data))
            if p == "/api/llm/models/save":
                return self._send(200, MODEL_PROFILES.save_model(data))
            if p == "/api/llm/models/delete":
                return self._send(200, MODEL_PROFILES.delete_model(
                    str(data.get("id") or ""),
                    delete_empty_connection=bool(
                        data.get("delete_empty_connection", False)
                    ),
                ))
            if p == "/api/llm/assignments/save":
                return self._send(200, MODEL_PROFILES.set_assignments(data))
            if p == "/api/llm/models/test":
                return self._send(
                    200,
                    test_workbench_model(data.get("id"), data.get("mode") or "text"),
                )
            if p == "/api/llm/models/list":
                if data.get("connection"):
                    connection = dict(data["connection"])
                else:
                    connection = MODEL_PROFILES.connection_record(
                        str(data.get("connection_id") or "")
                    )
                    connection["api_key"] = MODEL_PROFILES.resolve_connection_key(
                        connection["id"]
                    )
                return self._send(200, list_workbench_models(
                    connection, data.get("model") or {"model": "model-list"}
                ))
            if p == "/api/llm/models/recommend":
                model_name = str(data.get("model") or "").strip()
                if not model_name:
                    raise model_profiles.ModelProfileError("妯″瀷鍚嶇О涓嶈兘涓虹┖")
                return self._send(
                    200,
                    dict(model_capabilities.resolve_output_capability(
                        model_name,
                        service_preset=str(data.get("service_preset") or "custom"),
                    ), reasoning=model_capabilities.resolve_reasoning_capability(
                        model_name,
                        service_preset=str(data.get("service_preset") or "custom"),
                    )),
                )
            if p == "/api/llm/vision/fallback-test":
                provider = model_router.ModelRouter(MODEL_PROFILES).one_shot_base_fallback()
                return self._send(200, {"ok": True, "model": provider.model})
            if p == "/api/llm/profiles/activate":
                return self._send(
                    200,
                    MODEL_PROFILES.set_active(str(data.get("id") or "")),
                )
            if p == "/api/llm/profiles/delete":
                MODEL_PROFILES.delete_profile(
                    str(data.get("id") or ""),
                    delete_credential=bool(
                        data.get("delete_credential", True)
                    ),
                )
                return self._send(200, {"ok": True})
            if p == "/api/llm/models":
                if data.get("profile"):
                    provider = _temporary_profile_provider(data["profile"])
                else:
                    provider = profile_provider(str(data.get("id") or ""))
                return self._send(
                    200,
                    {"models": provider.list_models()},
                )
            if p == "/api/llm/test":
                if data.get("profile"):
                    return self._send(
                        200, test_profile_payload(data["profile"], data.get("mode") or "text")
                    )
                return self._send(
                    200,
                    test_profile_connection(
                        str(data.get("id") or ""),
                        data.get("mode") or "text",
                    ),
                )
        except (
            model_profiles.ModelProfileError,
            model_profiles.CredentialStoreError,
            llm.LLMError,
        ) as exc:
            return self._send(400, {"ok": False, "e": _model_public_error(exc)})
        if p == "/api/build/background/resolve":
            try:
                return self._send(
                    200,
                    resolve_background_for_build(data),
                )
            except background_workflow.BackgroundResolutionError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
        if p == "/api/build/background/continue":
            try:
                record = _resume_record(data.get("token"))
                if not record["session"].public_state()["ready"]:
                    raise background_workflow.BackgroundResolutionError(
                        "背景请求尚未全部解决"
                    )
                with JOB_LOCK:
                    if JOB["running"]:
                        return self._send(409, {"ok": False, "e": "已有任务在跑"})
                    # Publish the running state before the worker is visible.
                    # The immediate GET after this HTTP response must never
                    # look like a resolved-but-paused background request.
                    JOB.update(running=True, done=False, ok=False, state="compiling")
                threading.Thread(
                    target=continue_background_build,
                    args=(str(data.get("token") or ""),),
                    daemon=True,
                ).start()
                return self._send(200, {"ok": True})
            except background_workflow.BackgroundResolutionError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
        if p == "/api/build":
            try:
                story_type = normalize_story_type(data.get("story_type"))
                if "story_type" in data:
                    data["story_type"] = story_type
                inherit_story_context(data)
                project_name = build_project_name(data)
            except StoryProjectMismatchError:
                return self._send(409, {
                    "ok": False, "code": "project_mismatch",
                    "e": "project does not match story",
                })
            except ValueError as exc:
                code = (
                    "invalid_story_type"
                    if str(exc) == "invalid_story_type"
                    else "bad_request"
                )
                return self._send(400, {"ok": False, "code": code, "e": str(exc)})
            if not reserve_build_job():
                return self._send(409, {"e": "已有任务在跑"})

            def run_build_task(job):
                fn = globals().get("run_build")
                try:
                    fn(data, job=job)
                except TypeError:
                    fn(data)

            global_job_manager.submit(
                run_build_task, label=f"build:{project_name}", prefix="build-"
            )
            return self._send(200, {"ok": True, "deprecated": True})
        if p == "/api/scan_custom":
            return self._send(200, scan_custom(data.get("dir") or STORY_ROOT))
        if p == "/api/assets/discover":
            try:
                return self._send(
                    200,
                    asset_import.discover_assets(
                        data.get("dir") or STORY_ROOT,
                        limit=int(data.get("limit") or 2000),
                    ),
                )
            except asset_import.AssetImportRequestError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
        if p == "/api/assets/validate":
            try:
                file_token = str(data.pop("file_token", "") or "")
                story_token = str(data.pop("story_token", "") or "")
                story_context = None
                if story_token:
                    try:
                        story_context = resolve_story_context(story_token)
                    except ValueError:
                        return self._send(404, {
                            "ok": False, "code": "invalid_story_token", "e": "story not found",
                        })
                if file_token:
                    source = resolve_file_token(file_token)
                    if not source or not os.path.exists(source):
                        return self._send(400, {
                            "ok": False, "code": "invalid_file_token",
                            "e": "无效或过期的 file_token",
                        })
                    # Browser task cards never receive a filesystem path back.
                    data["source"] = source
                result = asset_import.validate_asset_request(data)
                return self._send(200, _public_story_asset_import(result, story_context) if story_context else result)
            except asset_import.AssetImportRequestError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
        if p == "/api/assets/register":
            try:
                file_token = str(data.pop("file_token", "") or "")
                story_token = str(data.pop("story_token", "") or "")
                story_context = None
                if file_token:
                    source = resolve_file_token(file_token)
                    if not source or not os.path.exists(source):
                        return self._send(400, {
                            "ok": False, "code": "invalid_file_token",
                            "e": "无效或过期的 file_token",
                        })
                    data["source"] = source
                if story_token:
                    try:
                        story_context = resolve_story_context(story_token)
                    except ValueError:
                        return self._send(404, {
                            "ok": False, "code": "invalid_story_token", "e": "story not found",
                        })
                    supplied_project = str(data.pop("project", "") or "").strip()
                    if supplied_project and supplied_project != story_context.project:
                        return self._send(409, {
                            "ok": False, "code": "project_mismatch",
                            "e": "project does not match story",
                        })
                    if not file_token:
                        return self._send(400, {
                            "ok": False, "code": "invalid_file_token",
                            "e": "story-scoped import requires file_token",
                        })
                    data["project_dir"] = str(story_context.project_dir)
                project_name = str(data.pop("project", "") or "").strip()
                requested_spine_cli = str(data.pop("spine_cli", "") or "").strip()
                supplied_background_labels = {}
                if str(data.get("kind") or "") == "background" and "labels" in data:
                    supplied_background_labels = background_labeler.normalize_background_labels(
                        data.get("labels")
                    )
                    data["labels"] = supplied_background_labels
                if project_name:
                    if (
                        os.path.basename(project_name) != project_name
                        or project_name in {".", ".."}
                    ):
                        raise asset_import.AssetImportRequestError(
                            "project must be a project name, not a path"
                        )
                    data["project_dir"] = os.path.join(
                        CFG["aa_data"], "projects", project_name
                    )
                registration_con = db()
                try:
                    result = asset_import.register_asset_request(
                        data,
                        con=registration_con,
                        saves_root=os.path.join(CFG["aa_data"], "saves"),
                    )
                    if (
                        result.get("ok")
                        and result.get("status") == "registered"
                        and result.get("kind") == "background"
                        and any(supplied_background_labels.values())
                    ):
                        asset_catalog.update_background_labels(
                            registration_con,
                            aa_key=result.get("aa_key", ""),
                            sha256=result.get("sha256", ""),
                            labels=supplied_background_labels,
                            status="ready",
                            error="",
                        )
                        result["background_analysis"] = {
                            "status": "ready", "queued": False,
                        }
                finally:
                    registration_con.close()
                if (
                    result.get("ok")
                    and result.get("status") == "registered"
                    and result.get("kind") == "character"
                ):
                    metadata = result.get("metadata") or {}
                    result["face_analysis"] = queue_face_analysis(
                        {
                            "source": result.get("source") or data.get("source"),
                            "ident": str(result.get("aa_key") or ""),
                            "spine_signature": metadata.get("spine_signature") or "",
                            "outfit_key": metadata.get("outfit_key") or "",
                            "spine_cli": requested_spine_cli,
                        }
                    )
                if (
                    result.get("ok")
                    and result.get("status") == "registered"
                    and result.get("kind") == "background"
                    and not any(supplied_background_labels.values())
                ):
                    result["background_analysis"] = queue_background_label_analysis({
                        "aa_key": result.get("aa_key", ""),
                        "sha256": result.get("sha256", ""),
                    })
                if story_context:
                    # The story token is the browser's only asset scope.  Do not
                    # disclose canonical project/save/install paths to this UI.
                    result = _public_story_asset_import(result, story_context)
                return self._send(200, result)
            except asset_import.AssetImportRequestError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
            except AssetRegistrationError as exc:
                code = 409 if isinstance(exc, RegistrationConflictError) or "aa_running" in str(exc) else 400
                return self._send(code, {
                    "ok": False,
                    "code": (
                        "same_name_different_content" if isinstance(exc, RegistrationConflictError)
                        else "aa_running" if code == 409 else "registration_failed"
                    ),
                    "e": str(exc),
                })
        return self._send(404, {"e": "not found"})

    def do_DELETE(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        try:
            if p.startswith("/api/cards/"):
                card_id = p[len("/api/cards/"):]
                token = data.get("token")
                expected_ver = data.get("expected_draft_version", 1)
                if not token or not card_id:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少 token/card_id"})
                _validate_client_draft_token(token)
                store = DraftStore()
                res = store.delete_card(token=token, card_id=card_id, expected_draft_version=expected_ver)
                return self._send(200, {
                    "ok": True,
                    "draft_version": res["session"]["draft_version"],
                    "content_revision": res["session"]["content_revision"],
                })
            return self._send(404, {"e": "not found"})
        except InvalidDraftTokenError as exc:
            return self._send(400, _invalid_draft_token_payload(exc))
        except RevisionConflictError as exc:
            return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})
        except Exception as exc:
            return self._send(400, {"ok": False, "e": str(exc)})


def browse(d, *, kind="script"):
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        d = STORY_ROOT
    dirs, files = [], []
    extensions = {
        "script": {".txt", ".md"},
        "background": {".png", ".jpg", ".jpeg"},
        "sound": {".wav", ".ogg", ".mp3"},
        "character": {".skel", ".atlas", ".png"},
    }.get(str(kind), set())
    names = set()
    try:
        for e in sorted(os.scandir(d), key=lambda x: x.name):
            if e.name.startswith("."):
                continue
            if e.is_dir():
                dirs.append(e.name)
            elif os.path.splitext(e.name)[1].lower() in extensions:
                files.append({"name": e.name, "size": e.stat().st_size})
                names.add(e.name)
    except PermissionError:
        pass
    can_choose_directory = False
    if kind == "character":
        can_choose_directory = any(
            name.lower().endswith(".skel")
            and os.path.splitext(name)[0] + ".atlas" in names
            for name in names
        )
    return {
        "dir": d,
        "parent": os.path.dirname(d),
        "dirs": dirs,
        "files": files,
        "can_choose_directory": can_choose_directory,
        "selection_hint": (
            "选择当前骨骼目录"
            if can_choose_directory
            else ""
        ),
    }


def scan_custom(root):
    """在剧本工程里找自定义 Spine 骨骼（同目录下有 .skel + .atlas）。"""
    out = []
    for dp, _, fns in os.walk(root):
        if os.sep + ".git" in dp or os.sep + "out" in dp:
            continue
        skels = [f for f in fns if f.endswith(".skel")]
        for sk in skels:
            asset = sk[:-5]
            if asset + ".atlas" in fns:
                faces = faces_of(os.path.join(dp, asset + ".atlas"))
                rel = os.path.relpath(dp, root).replace(os.sep, "/")
                out.append({"src": rel, "asset": asset, "abs": dp,
                            "faces": len(faces),
                            "avatar": os.path.exists(os.path.join(dp, asset + "-avatar.png"))})
    return out


def free_port(start):
    for port in range(start, start + 30):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def _publish_ready_file(path, *, host, port):
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp") as handle:
            temporary = Path(handle.name)
            json.dump({"app_id": APP_ID, "version": VERSION, "host": host, "port": int(port)}, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _remove_ready_file(path):
    if path is None:
        return
    try:
        Path(path).expanduser().resolve().unlink()
    except FileNotFoundError:
        pass


def _install_shutdown_handlers(server):
    stop_requested = threading.Event()
    previous_handlers = {}

    def request_stop(_signum, _frame):
        stop_requested.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is None or signum in previous_handlers:
            continue
        try:
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except (OSError, ValueError):
            previous_handlers.pop(signum, None)

    worker = threading.Thread(target=lambda: (stop_requested.wait(), server.shutdown()), daemon=True)
    worker.start()

    def restore():
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
        stop_requested.set()
        worker.join(timeout=5)

    return restore


class LocalWebServer:
    """Own one loopback-only HaloCue HTTP server and its worker thread."""

    def __init__(self, *, port=8770, handler=H):
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self.url
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.05),
            name="halocue-http",
            daemon=True,
        )
        self._thread.start()
        return self.url

    def serve_forever(self):
        self._server.serve_forever(poll_interval=0.1)

    def stop(self):
        thread = self._thread
        if thread is not None and thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._thread = None


def initialize_runtime(*, aa_data=None, overrides=None, spine_cli=None):
    """Configure the process-wide HaloCue runtime before starting a server."""
    global P
    prepare_user_state(LAYOUT)
    MODEL_PROFILES.bootstrap_legacy(LLMCFG)
    P = aapaths.detect(aa_data)
    CFG["aa_data"] = aa_data or P["data"] or None
    CFG["overrides"] = overrides or P["overrides"]
    CFG["spine_cli"] = spine_cli
    if not os.path.exists(DB):
        raise FileNotFoundError(
            "素材库还没建立：缺少 aa_assets.db"
        )
    return P


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--overrides")
    ap.add_argument("--aa-data")
    ap.add_argument("--spine-cli")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--ready-file")
    a = ap.parse_args(argv)
    _remove_ready_file(a.ready_file)
    P = initialize_runtime(
        aa_data=a.aa_data,
        overrides=a.overrides,
        spine_cli=a.spine_cli,
    )
    print(f'AA 存储目录  {CFG["aa_data"]}   （来源：{P["source"]}）')

    port = free_port(a.port)
    url = f"http://127.0.0.1:{port}"
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    srv.halocue_allow_api_shutdown = bool(a.no_browser)
    restore_shutdown_handlers = _install_shutdown_handlers(srv)
    port = int(srv.server_port)
    url = f"http://127.0.0.1:{port}"
    print(f"AA 剧本编译器  {url}")
    print("按 Ctrl+C 关闭")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        if a.ready_file:
            _publish_ready_file(a.ready_file, host="127.0.0.1", port=port)
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭")
    finally:
        restore_shutdown_handlers()
        srv.server_close()
        _remove_ready_file(a.ready_file)
    return 0


if __name__ == "__main__":
    main()
