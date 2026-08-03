# -*- coding: utf-8 -*-
"""
AA 剧本编译器 · 本地网页界面

  python webui.py

跑起来后浏览器打开 http://127.0.0.1:8770 。只监听本机，不对外。
只用标准库 + PIL（缩略图），不需要装框架。
"""
import argparse, io, json, mimetypes, os, re, socket, sys, threading, traceback, uuid, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Any, Optional
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, urlencode

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aapaths                                                  # noqa: E402
import asset_catalog                                            # noqa: E402
import asset_import                                             # noqa: E402
import assetdb                                                  # noqa: E402
from history_assets import HistoryAssetBrowser, HistoryAssetError  # noqa: E402
import background_workflow                                      # noqa: E402
import llm                                                      # noqa: E402
import model_profiles                                           # noqa: E402
import script2aap as S2A                                        # noqa: E402
import spine_face_analysis                                      # noqa: E402
import spine_face_labeler                                       # noqa: E402
from aa_project_assets import assert_aa_closed, validate_windows_path_component  # noqa: E402
from aa_registry import AssetRegistrationError, RegistrationConflictError  # noqa: E402
from build_index import faces_of                                # noqa: E402
from build_bundle import BuildBundleManager, CompileInputStaleError  # noqa: E402
from document import parse_document_lossless                    # noqa: E402
from draft_store import (                                       # noqa: E402
    DraftStore,
    InvalidDraftTokenError,
    RevisionConflictError,
)
from install_manager import InstallManager, AARunningError, AACorruptBundleError  # noqa: E402
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

STORY_ROOT = os.path.dirname(os.path.dirname(HERE))
BUILD_API_DEPRECATED = True
DB = os.path.join(HERE, "aa_assets.db")
INDEX = os.path.join(HERE, "aa_resources.json")
LLMCFG = os.path.join(HERE, "llm.json")
MODEL_PROFILES = model_profiles.ModelProfileStore(
    os.path.join(HERE, "llm_profiles.json")
)
THUMBS = os.path.join(HERE, ".thumbs")
STORY_FILE_PICKER = StoryFilePicker(
    roots=windows_host_roots(STORY_ROOT),
    upload_dir=os.path.join(HERE, "out", "story-uploads"),
)
SETTINGS_FILE_PICKER = StoryFilePicker(
    roots=windows_host_roots(STORY_ROOT),
    upload_dir=os.path.join(HERE, "out", "story-uploads"),
    allowed_suffixes=None,
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


class StoryProjectMismatchError(ValueError):
    """The client tried to attach a story-scoped draft to another project."""


class InvalidProjectNameError(ValueError):
    """A client value is not a single valid Windows project component."""


def story_workspace() -> StoryWorkspaceRegistry:
    """Return the server-local registry for the configured AA data root."""
    global STORY_WORKSPACE
    aa_data = Path(CFG.get("aa_data") or (Path(HERE) / "out" / "aa-data")).resolve()
    with STORY_WORKSPACE_LOCK:
        if STORY_WORKSPACE is None or STORY_WORKSPACE.aa_data != aa_data:
            STORY_WORKSPACE = StoryWorkspaceRegistry(
                # 索引随数据目录走：不同 aa_data 各自独立，测试不会污染真实最近记录。
                aa_data / ".story-index.json", aa_data=aa_data
            )
        return STORY_WORKSPACE


def history_asset_browser() -> HistoryAssetBrowser:
    """Return the server-local token registry for the configured AA data root."""
    global HISTORY_ASSET_BROWSER
    aa_data = Path(CFG.get("aa_data") or (Path(HERE) / "out" / "aa-data")).resolve()
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
            "rendered_count", "render_cached", "vision_status", "labeled_count",
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
    selected = str(
        profile_id or state.get("active_profile_id") or ""
    )
    if not selected:
        return None
    return profile_provider(selected)


def _optional_vision_provider():
    """Return the configured provider only when its key is available."""
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
            _face_progress(
                "rendering",
                f"{provider_issue}；本次仍会完成渲染和语义命名解析",
            )
        result = spine_face_analysis.analyze_character_faces(
            con,
            source_dir=payload["source"],
            ident=payload["ident"],
            spine_signature=payload.get("spine_signature") or "",
            outfit_key=payload.get("outfit_key") or "",
            spine_cli=payload["spine_cli"],
            cache_root=os.path.join(HERE, "out", "spine-face-cache"),
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


def setup_status():
    """Return non-sensitive readiness for the first-use UI and launcher."""
    aa_data = str(CFG.get("aa_data") or "")
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
    active_profile = MODEL_PROFILES.active_profile()
    model = {
        "configured": active_profile is not None,
        "name": "",
        "model": "",
    }
    if active_profile:
        model.update(
            name=str(active_profile.get("name") or ""),
            model=str(active_profile.get("model") or ""),
        )
    config_path = Path(HERE) / "aa_config.json"
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
        "aa": {
            "connected": bool(
                aa_data
                and os.path.isdir(
                    os.path.join(aa_data, "projects")
                )
            ),
            "path": aa_data,
        },
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
        "entry_file": "启动AA自动写剧本.cmd",
    }


def _write_settings_config(**updates: str) -> None:
    config_path = Path(HERE) / "aa_config.json"
    values: dict[str, object] = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                values.update(loaded)
        except (OSError, ValueError, TypeError):
            pass
    values.update({key: value for key, value in updates.items() if value})
    config_path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_characters(q="", limit=400):
    con = db()
    sql = ("SELECT c.ident, c.name, c.club, c.spine, c.source, "
           "  (SELECT COUNT(*) FROM face f WHERE f.ident=c.ident) AS nface "
           "FROM character c ")
    args = []
    if q:
        sql += "WHERE c.ident LIKE ? OR c.name LIKE ? OR c.club LIKE ? "
        args = [f"%{q}%"] * 3
    sql += "ORDER BY (c.name IS NULL), nface DESC, c.ident LIMIT ?"
    args.append(limit)
    out = []
    for r in con.execute(sql, args):
        out.append({"ident": r["ident"], "name": r["name"] or r["ident"],
                    "club": r["club"] or "", "spine": r["spine"] or "",
                    "faces": r["nface"], "source": r["source"],
                    "avatar": bool(r["spine"])})
    return out


def list_backgrounds(q="", only_ready=False, limit=300):
    con = db()
    sql = "SELECT name,hash,label,place,time,mood,tags FROM bg "
    where, args = [], []
    if q:
        where.append("(name LIKE ? OR label LIKE ? OR tags LIKE ?)")
        args += [f"%{q}%"] * 3
    if only_ready:
        where.append("hash IS NOT NULL")
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    # 多取一些，在 Python 里按“有预览图 → 有标签 → 名称”重排，
    # 避免把无标签的哈希名（00000-*）顶到前面。
    sql += "ORDER BY (hash IS NULL), name LIMIT ?"
    args.append(max(limit * 4, 1000))
    files = bg_files()
    out = []
    for r in con.execute(sql, args):
        out.append({"name": r["name"], "ready": r["hash"] is not None,
                    "label": r["label"] or "", "place": r["place"] or "",
                    "time": r["time"] or "", "mood": r["mood"] or "",
                    "tags": r["tags"] or "", "img": r["name"] in files})
    out.sort(key=lambda item: (not item["img"], not bool(item["label"]), item["name"].casefold()))
    return out[:limit]


_BGF = {}


def bg_files():
    if _BGF:
        return _BGF
    root = os.path.join(CFG["overrides"], "bgs")
    for dp, _, fns in os.walk(root):
        for fn in fns:
            stem, ext = os.path.splitext(fn)
            if ext.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                _BGF.setdefault(stem, os.path.join(dp, fn))
    return _BGF


def avatar_path(spine):
    if not spine:
        return None
    p = os.path.join(CFG["overrides"], spine.replace("\\", os.sep) + "-avatar.png")
    return p if os.path.exists(p) else None


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


def guess_mapping(speakers):
    """给每个说话者猜一个 AA 角色。

    先做名字/标识的完全一致匹配（避免被垃圾别名或变体带偏，如「桃井」应命中
    用户自己导入的「桃井」而不是别名里的占位 ???）；退回学过的别名时同样跳过
    占位垃圾角色。用户始终可在“确认演员”一步手动修改对应关系。"""
    con = db()
    assetdb.seed_alias(con)
    out = {}
    for sp in speakers:
        w = sp["who"]
        if w in ("旁白", "独白", "narration"):
            out[w] = {"kind": "narrator"}
            continue
        # 1. 名字/标识完全一致（用户自定义素材优先；如「凯伊」→基础版而非“约会服”）
        row = con.execute(
            "SELECT ident,name,spine FROM character WHERE name=? OR ident=? "
            "ORDER BY (ident<>?), (spine IS NULL), LENGTH(ident) LIMIT 1",
            (w, w, w)).fetchone()
        if row is not None and not assetdb._looks_placeholder(row["name"]):
            out[w] = {"kind": "portrait", "id": row["ident"],
                      "name": row["name"] or w, "spine": row["spine"] or ""}
            continue
        # 2. 学过的别名（portrait 别名已过滤占位垃圾）
        a = assetdb.best_alias(con, w)
        if a:
            if a["kind"] == "narrator":
                out[w] = {"kind": "narrator"}
                continue
            crow = con.execute("SELECT ident,name,spine FROM character WHERE ident=?",
                               (a["ident"],)).fetchone()
            if crow is not None and not assetdb._looks_placeholder(crow["name"]):
                out[w] = {"kind": a["kind"], "id": a["ident"],
                          "name": crow["name"] or w, "spine": crow["spine"] or "",
                          "learned": True}
                continue
            # voice 角色可能没有名字（无头像的语音位），仍按语音映射
            if a["kind"] == "voice":
                out[w] = {"kind": "voice", "id": a["ident"],
                          "name": w, "spine": "", "learned": True}
                continue
        out[w] = {"kind": "unset"}
    return out


_PREFLIGHT_SCHEMA = {
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
        "issues": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "properties": {
                "severity": {"type": "string"}, "code": {"type": "string"},
                "message": {"type": "string"}, "action": {"type": "string"},
                "speaker": {"type": "string"},
            }, "required": ["severity", "code", "message", "action"]},
        },
    },
    "required": ["characters", "assets", "issues"],
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
        add(item.get("aa_key"), item.get("name"), source="current_story_custom")
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


def _is_builtin_asset_ref(con, kind: str, name: str) -> bool:
    """内置素材不进入“本剧情自定义素材”清单，也不产生缺失错误。"""
    if kind == "bgm":
        return name.lstrip("-").isdigit()
    if kind == "background":
        row = con.execute(
            "SELECT 1 FROM bg WHERE name=? OR label=? LIMIT 1", (name, name)
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
        })
    return refs


_PREFLIGHT_COMMANDS = {
    "bg", "trans", "bgfx", "popup", "bgm", "music", "se", "sound",
    "place", "wait", "raw", "bgshake", "clearst", "hidemenu", "showmenu",
    "aronatouch", "shot", "st", "stm", "zoom", "enter", "exit", "move",
    "stage", "auto", "fx", "hl",
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


def _preflight_result(script: str, *, scope: str, model_profile_id: str | None = None) -> dict:
    """执行规则基线与可选 AI 初审，返回浏览器可编辑的安全结果。"""
    text = Path(script).read_text(encoding="utf-8", errors="replace")
    analysis = analyze(script)
    baseline = guess_mapping(analysis.get("speakers") or [])
    con = db()
    try:
        custom_assets = asset_catalog.list_story_assets(con, scope=scope)
        character_library = _preflight_character_library(
            con, analysis.get("speakers") or [], custom_assets, baseline
        )
        refs = _preflight_asset_refs(text, custom_assets, con)
        builtin_asset_names = {
            "background": {
                str(value).casefold()
                for row in con.execute("SELECT name,label FROM bg")
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
        characters.append({
            "speaker": who, "kind": str(mapping.get("kind") or "unset"),
            "id": str(mapping.get("id") or ""), "name": str(mapping.get("name") or ""),
            "custom": str(mapping.get("id") or "").casefold() in custom_ids,
            "confidence": 0.65 if mapping.get("kind") not in (None, "unset") else 0.0,
            "reason": "规则匹配结果，可在确认演员中修改。",
        })
    ai_status = "not_configured"
    ai_issues = []
    provider = annotation_provider(model_profile_id)
    if provider is not None:
        static = (
            "你是 AA 剧本编译器的剧本初审助手。只返回 JSON，不要编造文件路径。"
            "请通读全文，即使写法不是“角色：台词”，也要列出明确出场或说话的角色，以及明确提及的背景、音效和 BGM。"
            "只能把角色映射到提供的候选或明确标记为 unset；自定义角色/骨骼必须标记 custom=true。"
            "素材状态只能依据当前剧情自定义素材清单判断，不能把缺失素材改成已登记。"
        )
        volatile = json.dumps({
            "speakers": analysis.get("speakers", []),
            "rule_mapping": characters,
            "character_library": character_library,
            "custom_assets": custom_assets,
            "script_asset_refs": refs,
        }, ensure_ascii=False)
        user = "请先理解以下剧本全文，再给出可编辑的角色、素材和问题清单。\n\n剧本全文：\n" + text
        try:
            ai = provider.complete_json(static, volatile, user, _PREFLIGHT_SCHEMA)
            if isinstance(ai, dict):
                ai_status = "completed"
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
                        if kind == "narrator":
                            item.update(kind="narrator", id="", name="旁白", custom=False)
                        elif kind in {"portrait", "voice"} and candidate:
                            item.update(
                                kind=kind, id=candidate["id"], name=candidate["name"],
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
                kind_aliases = {
                    "bg": "background", "background": "background",
                    "se": "sound", "sound": "sound",
                    "bgm": "bgm", "music": "bgm",
                }
                present_refs = {(item["kind"], item["name"].casefold()) for item in refs}
                for (raw_kind, folded_name), suggestion in refs_by_key.items():
                    kind = kind_aliases.get(raw_kind)
                    name = str(suggestion.get("name") or "").strip()
                    if not kind or not name or len(name) > 160 or (kind, folded_name) in present_refs:
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
            ai_issues.append({
                "severity": "warning", "code": "ai_preflight_failed",
                "message": "AI 初审调用失败，已保留规则分析结果。",
                "action": "检查模型配置后重试，或直接编辑下方角色映射并继续。",
            })
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
            action = "请从本剧情素材导入，或从历史项目复制后再确认初审。"
            if ref["kind"] == "bgm":
                action = "当前版本尚未开放自定义 BGM 登记；请改用已知数字 BGM ID。"
            issues.append({
                "severity": "error", "code": "missing_custom_asset",
                "message": f"{ref['location']} 引用了未登记的{kind_name}“{ref['name']}”。",
                "action": action,
            })
    for item in characters:
        if item["kind"] == "unset":
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
    return _preflight_result(script, scope=scope, model_profile_id=payload.get("model_profile_id"))


# ---------------------------------------------------------------- 生成
def prepare_project_index(index_path, project_dir, output_path, *, con=None):
    """Build the exact official+registered allowlist used by AI and generator."""
    with open(index_path, encoding="utf-8") as source:
        index = json.load(source)
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

        cpath = os.path.join(HERE, "cast-" + re.sub(r"[^\w-]", "_", project)[:40] + ".json")
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump(cast, fh, ensure_ascii=False, indent=2)
        jlog(f"演员表已写入 {os.path.basename(cpath)}")
        index_path = os.path.join(
            HERE,
            "out",
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
            out = os.path.join(HERE, "out",
                               re.sub(r"[^\w-]", "_", project)[:40] + ".annotated.txt")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            opts = {
                "script": script,
                "out": out,
                "cast": cpath,
                "index": index_path,
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


def annotate_draft_worker(payload):
    """AI 演出标注 -> 建草稿 -> 存 cast/proposals。供 /api/annotate 的 Job 调用。"""
    import annotate as ANN
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
    cpath = os.path.join(HERE, "out", token + ".cast.json")
    os.makedirs(os.path.dirname(cpath), exist_ok=True)
    with open(cpath, "w", encoding="utf-8") as fh:
        json.dump(cast, fh, ensure_ascii=False, indent=2)
    index_path = os.path.join(HERE, "out", token + ".resources.json")
    prepare_project_index(INDEX, project_dir, index_path, con=con)
    out_path = os.path.join(HERE, "out", token + ".annotated.txt")

    source_text = ""
    try:
        source_text = open(payload["script"], encoding="utf-8").read()
    except OSError:
        pass

    result = {}
    if payload.get("annotate", True):
        opts = {
            "script": payload["script"],
            "out": out_path,
            "cast": cpath,
            "index": index_path,
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
    else:
        annotated = source_text

    store = DraftStore()
    store.create_draft(token=token, text=annotated, project=project,
                       source_text=source_text, cast=cast,
                       story_token=payload.get("story_token"),
                       bgm_policy=payload.get("bgm_policy"))
    store.save_cast(token, cast)
    proposals = result.get("proposals") or []
    if proposals:
        store.add_proposals(token, proposals)
    return {"draft_token": token, "project": project,
            "lines": len(annotated.splitlines()), "proposals": len(proposals)}


def get_draft_detail_data(token, store=None):
    if store is None:
        store = DraftStore()
    draft = store.load_draft(token)
    session = draft["session"]
    edited_text = draft["edited_text"]
    identities_data = draft["identities"]
    diagnostics = draft["diagnostics"]
    cast_data = store.load_cast(token)
    cast_members = cast_data.get("cast", {}) if isinstance(cast_data, dict) else {}
    cast_summary = {
        "count": len(cast_members) if isinstance(cast_members, dict) else 0,
        "speakers": sorted(cast_members) if isinstance(cast_members, dict) else [],
    }

    nodes = parse_document_lossless(edited_text)
    cards = []
    for node, card_id_info in zip(nodes, identities_data):
        cards.append({
            "card_id": card_id_info["card_id"],
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
            "issues": [],
            "proposal_ids": [],
        })

    pending_count = sum(1 for c in cards if c["review_state"] == "pending")
    unresolved_issues = sum(1 for d in diagnostics if d.get("severity") in ("error", "warning"))
    blocking_errors = sum(1 for d in diagnostics if d.get("severity") == "error")

    return {
        "cards": cards,
        "diagnostics": diagnostics,
        "counts": {
            "pending": pending_count,
            "unresolved_issues": unresolved_issues,
            "blocking_errors": blocking_errors,
        },
        "draft_version": session["draft_version"],
        "content_revision": session["content_revision"],
        "identity_rebuilt": draft.get("identity_rebuilt", False),
        "project": session.get("project"),
        "story_token": session.get("story_token"),
        "bgm_policy": normalize_bgm_policy(session.get("bgm_policy")),
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
    """搜索已登记音效的标签列表。"""
    try:
        con = db()
        rows = con.execute(
            "SELECT name, label_cn, category FROM sound WHERE name LIKE ? OR label_cn LIKE ?",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
        results = [{"name": r[0], "label_cn": r[1] or "", "category": r[2] or "SE"} for r in rows]
    except Exception:
        results = []

    if not results:
        try:
            idx = json.load(open(INDEX, encoding="utf-8"))
            for s in idx.get("sounds", []):
                if not q or q.lower() in s.lower():
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
    search_paths.extend([Path(HERE) / "out", Path(HERE) / "sounds"])

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
                active_profile = MODEL_PROFILES.active_profile()
                if active_profile:
                    prov = (
                        f"{active_profile['name']} / "
                        f"{active_profile['model']}"
                    )
                else:
                    prov = json.load(
                        open(LLMCFG, encoding="utf-8")
                    ).get("provider")
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
            if p == "/api/characters":
                return self._send(200, list_characters(q.get("q", "")))
            if p == "/api/backgrounds":
                return self._send(200, list_backgrounds(
                    q.get("q", ""), q.get("ready") == "1"))
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
                cache_dir = Path(HERE) / "out" / "spine-face-cache" / sig
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
                drafts_list = []
                if store.base_dir.is_dir():
                    for d_dir in store.base_dir.iterdir():
                        if d_dir.is_dir():
                            session_file = d_dir / "session.json"
                            if session_file.is_file():
                                try:
                                    sess = json.loads(session_file.read_text(encoding="utf-8"))
                                    drafts_list.append(sess)
                                except Exception:
                                    pass
                return self._send(200, drafts_list)
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
            if p.startswith("/thumb/bg/"):
                name = p[len("/thumb/bg/"):]
                f = bg_files().get(name)
                if not f:
                    return self._send(404, {"e": "no image"})
                return self._send(200, thumb(f, int(q.get("px", 240)), "bg_" + name),
                                  "image/jpeg")
            if p.startswith("/thumb/av/"):
                f = avatar_path(unquote(p[len("/thumb/av/"):]))
                if not f:
                    return self._send(404, {"e": "no avatar"})
                return self._send(200, thumb(f, int(q.get("px", 96)), "av_" + p[-40:]),
                                  "image/jpeg")
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
                if len(parts) == 5:
                    token = parts[2]
                    request_card_id = parts[4]
                    bg_name = data.get("bg_name")
                    expected_ver = data.get("expected_draft_version", 1)
                    try:
                        store = DraftStore()
                        res = store.resolve_background_request(token=token, card_id=request_card_id, bg_name=bg_name, expected_draft_version=expected_ver)
                        return self._send(200, {"ok": True, "draft_version": res["session"]["draft_version"], "content_revision": res["session"]["content_revision"]})
                    except Exception as exc:
                        return self._send(409, {"ok": False, "code": "revision_conflict", "e": str(exc)})

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
                    return self._send(409, {"ok": False, "code": "review_pending", "e": str(exc)})

                bundle_mgr = BuildBundleManager(store=store)
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
                    res = install_mgr.install_build(token=token, build_id=build_id)
                    return self._send(200, res)
                except AARunningError as exc:
                    return self._send(423, {"ok": False, "code": "aa_running", "e": str(exc)})
                except AACorruptBundleError as exc:
                    return self._send(400, {"ok": False, "code": "corrupted_bundle", "e": str(exc)})
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

            if p == "/api/preflight":
                try:
                    context = inherit_story_context(data)
                except StoryProjectMismatchError:
                    return self._send(409, {"ok": False, "code": "project_mismatch", "e": "project does not match story"})
                except ValueError:
                    return self._send(400, {"ok": False, "code": "invalid_story_token", "e": "invalid story token"})
                if not context:
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "初审必须绑定当前剧情"})
                script = resolve_file_token(str(data.get("file_token") or ""))
                if not script or not os.path.isfile(script):
                    return self._send(400, {"ok": False, "code": "invalid_file_token", "e": "缺少有效的 file_token"})
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
                    context = inherit_story_context(data)
                except StoryProjectMismatchError:
                    return self._send(409, {"ok": False, "code": "project_mismatch", "e": "project does not match story"})
                except ValueError as exc:
                    return self._send(400, {"ok": False, "code": str(exc), "e": "invalid story token"})
                if context:
                    script = resolve_file_token(str(data.get("file_token") or ""))
                    if not script or not os.path.isfile(script):
                        return self._send(400, {"ok": False, "code": "invalid_file_token", "e": "缺少有效的 file_token"})
                    data["script"] = script
                else:
                    script = data.get("script")
                if not script or not isinstance(mapping, dict) or not os.path.isfile(script):
                    return self._send(400, {"ok": False, "code": "bad_request", "e": "缺少有效的 script 与 mapping"})

                def annotate_task(job):
                    result = annotate_draft_worker(data)
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
                provider = profile_provider(str(data.get("id") or ""))
                return self._send(
                    200,
                    {"models": provider.list_models()},
                )
            if p == "/api/llm/test":
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
            return self._send(400, {"ok": False, "e": str(exc)})
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
                inherit_story_context(data)
                project_name = build_project_name(data)
            except StoryProjectMismatchError:
                return self._send(409, {
                    "ok": False, "code": "project_mismatch",
                    "e": "project does not match story",
                })
            except ValueError as exc:
                return self._send(400, {"ok": False, "e": str(exc)})
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
                result = asset_import.register_asset_request(
                    data,
                    con=db(),
                    saves_root=os.path.join(CFG["aa_data"], "saves"),
                )
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--overrides")
    ap.add_argument("--aa-data")
    ap.add_argument("--spine-cli")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    MODEL_PROFILES.bootstrap_legacy(LLMCFG)
    P = aapaths.require(a.aa_data)
    CFG["aa_data"] = a.aa_data or P["data"]
    CFG["overrides"] = a.overrides or P["overrides"]
    CFG["spine_cli"] = a.spine_cli
    print(f'AA 存储目录  {CFG["aa_data"]}   （来源：{P["source"]}）')

    if not os.path.exists(DB):
        print("素材库还没建，先跑:  python label_assets.py --init")
        sys.exit(1)

    port = free_port(a.port)
    url = f"http://127.0.0.1:{port}"
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"AA 剧本编译器  {url}")
    print("按 Ctrl+C 关闭")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭")


if __name__ == "__main__":
    main()
