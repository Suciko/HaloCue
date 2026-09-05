from __future__ import annotations

import importlib
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import mimetypes
import copy
from pathlib import Path
from typing import Any

from .config import Settings
from . import cg_advice, cg_segments
from .errors import ProductionError
from .models import StagedDirectionResult, new_id, utc_now
from .name_baseline import CharacterNameBaseline
from .resource_previews import ResourcePreviewCatalog


_IMPORT_LOCK = threading.RLock()
_COMPILE_LOCK = threading.RLock()
AA_WORKSPACE_DIRS = ("projects", "saves", "overrides", "settings")
RESOURCE_SNAPSHOT_PREWARM_BYTES = 8 * 1024 * 1024


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


class Legacy093Adapter:
    """Translate the 1.0 contract to an explicitly selected legacy checkout.

    The adapter keeps one implementation for the 0.9 compatibility family,
    while reporting the actual checkout version instead of claiming that every
    source tree is 0.9.3.  This is important when a local 0.95 checkout is used
    for production acceptance.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.compat_root = settings.data_dir / "legacy-runtime"
        self.compat_root.mkdir(parents=True, exist_ok=True)
        self.legacy_version = self._detect_legacy_version(settings.legacy_root)
        self._modules: dict[str, Any] = {}
        self._resource_snapshot_lock = threading.RLock()
        self._resource_snapshot_signature: tuple[tuple[str, int, int], ...] | None = None
        self._resource_snapshot: dict[str, Any] | None = None
        self._resource_snapshot_scope: str | None = None
        self.name_baseline = CharacterNameBaseline(settings.name_baseline)
        self.previews = ResourcePreviewCatalog(settings.legacy_root, settings.aa_data)
        self._load_modules()
        self.store = self._modules["draft_store"].DraftStore(
            base_dir=str(settings.data_dir / "drafts")
        )
        # Building the labelled resource base can be expensive for a full AA
        # catalogue. Prewarm only that case before accepting HTTP work so
        # release handoff does not race a fixed client timeout; small indexes
        # retain the usual on-demand initialization for fast tests and tools.
        if self._should_prewarm_resource_snapshot():
            self._refresh_resource_snapshot()

    def _load_modules(self) -> None:
        if not self.settings.legacy_root.is_dir():
            raise ProductionError(
                "legacy_adapter_unavailable",
                "找不到兼容转换模块",
                status=503,
                details={"legacy_root": str(self.settings.legacy_root)},
            )
        with _IMPORT_LOCK:
            os.environ.setdefault("HALOCUE_USER_DATA_DIR", str(self.compat_root))
            legacy = str(self.settings.legacy_root)
            if legacy not in sys.path:
                sys.path.insert(0, legacy)
            for name in (
                "document",
                "draft_store",
                "build_bundle",
                "install_manager",
                "annotate",
                "assetdb",
                "asset_catalog",
                "portrait_layout",
                "asset_import",
                "aa_install_discovery",
            ):
                self._modules[name] = importlib.import_module(name)

    @staticmethod
    def _detect_legacy_version(root: Path) -> str:
        """Read a version marker without importing or mutating the legacy app."""
        candidates = (root / "pyproject.toml", root / "halocue_meta.py", root / "VERSION")
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            match = re.search(r"(?im)(?:^version\s*=\s*|HALOCUE_VERSION\s*=\s*[\"'])([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][^\s\"']+)?)", text)
            if match:
                return match.group(1)
            match = re.search(r"\b(0\.9(?:\.\d+)?|0\.95(?:\.\d+)?)\b", text)
            if match:
                return match.group(1)
        return "unknown"

    @property
    def document(self):
        return self._modules["document"]

    @staticmethod
    def _file_signature(path: Path | None) -> tuple[str, int, int]:
        if not path:
            return ("", 0, 0)
        try:
            stat = path.stat()
        except OSError:
            return (str(path), 0, 0)
        return (str(path), int(stat.st_mtime_ns), int(stat.st_size))

    def _resource_snapshot_sources(self) -> tuple[tuple[str, int, int], ...]:
        layout_catalog = Path(
            str(getattr(self._modules.get("portrait_layout"), "DEFAULT_CATALOG", ""))
        )
        return (
            self._file_signature(self.settings.resource_index),
            self._file_signature(self.settings.legacy_root / "aa_assets.db"),
            self._file_signature(self.settings.name_baseline),
            self._file_signature(layout_catalog),
        )

    def _should_prewarm_resource_snapshot(self) -> bool:
        index_path = self.settings.resource_index
        if not index_path:
            return False
        try:
            return index_path.stat().st_size >= RESOURCE_SNAPSHOT_PREWARM_BYTES
        except OSError:
            return False

    def _refresh_resource_snapshot(self, scope: str | None = None) -> None:
        """Cache the immutable labelled base used to create task snapshots."""
        index_path = self.settings.resource_index
        if not index_path:
            return
        signature = self._resource_snapshot_sources()
        prewarm = self._should_prewarm_resource_snapshot()
        snapshot_scope = "__resource_snapshot_base__" if prewarm else str(scope or "__resource_snapshot_base__")
        with self._resource_snapshot_lock:
            if (
                self._resource_snapshot is not None
                and signature == self._resource_snapshot_signature
                and (prewarm or snapshot_scope == self._resource_snapshot_scope)
            ):
                return
            try:
                source_resources = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProductionError("resource_index_corrupted", "资源索引无法读取", status=500) from exc
            database = self.settings.legacy_root / "aa_assets.db"
            if database.is_file():
                connection = None
                try:
                    connection = self._modules["assetdb"].connect(database)
                    source_resources = self._modules["asset_catalog"].merge_model_constraints(
                        source_resources, connection, scope=snapshot_scope,
                    )
                except Exception as exc:
                    raise ProductionError(
                        "face_label_catalog_unavailable",
                        "无法把 AA 表情语义标签冻结到制作任务",
                        status=500,
                    ) from exc
                finally:
                    if connection is not None:
                        connection.close()
            source_resources = self._modules["portrait_layout"].enrich_resource_index(
                source_resources
            )
            self._resource_snapshot = self.name_baseline.decorate_resource_payload(
                source_resources
            )
            self._resource_snapshot_signature = signature
            self._resource_snapshot_scope = snapshot_scope

    def _task_resource_snapshot(self, scope: str | None = None) -> dict[str, Any]:
        self._refresh_resource_snapshot(scope)
        if self._resource_snapshot is None:
            return {}
        return copy.deepcopy(self._resource_snapshot)

    def capabilities(self) -> dict[str, Any]:
        resource_ready = bool(
            self.settings.resource_index and self.settings.resource_index.is_file()
        )
        aa_ready = bool(
            self.settings.aa_data
            and self.settings.aa_data.is_dir()
            and all(
                (self.settings.aa_data / name).is_dir()
                for name in AA_WORKSPACE_DIRS
            )
        )
        return {
            "legacy_adapter": {
                "state": "available",
                "version": self.legacy_version,
                "mode": "domain_modules",
            },
            "script_import": {"state": "available"},
            "performance_draft": {"state": "available"},
            "generation_modes": {
                "format_only": {"state": "available"},
                "ai_direction": {
                    "state": "not_configured",
                    "reason": "model_provider_not_configured",
                },
            },
            "compile": {
                "state": "available" if resource_ready and aa_ready else "not_configured",
                "resource_index": resource_ready,
                "aa_workspace": aa_ready,
            },
            "install": {
                "state": "available" if aa_ready else "not_configured",
                "aa_workspace": aa_ready,
            },
        }

    def discover_aa_environment(self, selection: str | None = None) -> dict[str, Any]:
        discovery = self._modules["aa_install_discovery"].discover_aa(
            selection or None,
            config_path=self.settings.legacy_root / "aa_config.json",
        )

        def value(path: Path | None) -> str | None:
            return str(path) if path else None

        required = {
            "projects": discovery.projects is not None,
            "saves": discovery.saves is not None,
            "overrides": discovery.overrides is not None,
            "settings": discovery.settings is not None,
        }
        return {
            "selection": str(selection or ""),
            "executable": value(discovery.executable),
            "install_root": value(discovery.install_root),
            "workspace": {
                "path": value(discovery.data),
                "valid": bool(discovery.data and all(required.values())),
                "directories": required,
                "source": discovery.source,
            },
            "resource_cache": {
                "available": discovery.resource_cache is not None,
                "path": value(discovery.resource_cache),
            },
            "recent_projects": [path.name for path in discovery.recent_project_files[:12]],
            "requires_selection": discovery.requires_selection,
            "candidates": [
                {"path": str(item.path), "source": item.source, "valid": item.valid}
                for item in discovery.data_candidates
            ],
            "issues": [
                {"code": item.code, "message": item.message, "path": value(item.path)}
                for item in discovery.issues
            ],
        }

    def inspect_script(self, text: str) -> dict[str, Any]:
        nodes = self.document.normalize_draft_nodes(
            self.document.parse_document_lossless(text)
        )
        speaker_details: dict[str, dict[str, Any]] = {}
        for node in nodes:
            if node.kind != "line":
                continue
            speaker = str(node.fields.get("who") or "").strip()
            if not speaker:
                continue
            row = speaker_details.setdefault(
                speaker,
                {"speaker": speaker, "count": 0, "sample": "", "first_line": node.line_no},
            )
            row["count"] += 1
            if not row["sample"]:
                row["sample"] = str(node.fields.get("text") or "").strip()[:64]
        speakers = sorted(speaker_details, key=str.casefold)
        return {
            "line_count": len(text.splitlines()),
            "card_count": len(nodes),
            "scene_count": sum(1 for node in nodes if node.kind == "scene"),
            "dialogue_count": sum(1 for node in nodes if node.kind == "line"),
            "directive_count": sum(1 for node in nodes if node.kind == "dir"),
            "speakers": speakers,
            "speaker_details": sorted(
                speaker_details.values(), key=lambda item: (-item["count"], item["speaker"].casefold())
            ),
            "scenes": [
                {"title": str(node.fields.get("title") or "未命名场景"), "line_no": node.line_no}
                for node in nodes if node.kind == "scene"
            ],
        }

    def preflight_script(self, text: str, *, commands: set[str], no_argument_commands: set[str]) -> dict[str, Any]:
        """Return a deterministic, read-only explanation of what the parser sees."""
        nodes = self.document.parse_document_lossless(text)
        dialogue_nodes = [node for node in nodes if node.kind == "line"]
        directive_nodes = [node for node in nodes if node.kind == "dir"]
        scene_nodes = [node for node in nodes if node.kind == "scene"]
        meaningful = [node for node in nodes if node.kind not in {"blank", "separator"}]
        speaker_rows: dict[str, dict[str, Any]] = {}
        for node in dialogue_nodes:
            who = str(node.fields.get("who") or "").strip()
            if not who:
                continue
            row = speaker_rows.setdefault(who, {"name": who, "count": 0, "sample": "", "first_line": node.line_no})
            row["count"] += 1
            if not row["sample"]:
                row["sample"] = str(node.fields.get("text") or "").strip()[:64]
        speakers = sorted(speaker_rows.values(), key=lambda item: (-item["count"], item["name"].casefold()))

        issues: list[dict[str, Any]] = []
        for node in directive_nodes:
            command = str(node.fields.get("cmd") or "").strip().casefold()
            argument = str(node.fields.get("arg") or "").strip()
            if command not in commands:
                issues.append({"severity": "error", "code": "unknown_directive", "line_no": node.line_no, "message": f"第 {node.line_no} 行使用了未支持的 @{command} 指令。", "action": "检查拼写，或改为当前版本支持的 AA 指令。"})
            elif command not in no_argument_commands and not argument:
                issues.append({"severity": "error", "code": "missing_directive_argument", "line_no": node.line_no, "message": f"第 {node.line_no} 行的 @{command} 缺少参数。", "action": "在指令后补充所需参数；背景和音效会在任务内从素材库选择。"})
        for node in nodes:
            if node.kind == "unknown" and str(node.raw).lstrip().startswith("@"):
                issues.append({"severity": "error", "code": "invalid_directive", "line_no": node.line_no, "message": f"第 {node.line_no} 行的 AA 指令格式无法识别。", "action": "请使用“@指令 参数”的格式后重新检查。"})

        if not meaningful:
            format_summary = {"kind": "empty", "label": "空剧本", "confidence": "low", "message": "没有读到可转换内容。请先输入剧本文本。"}
        elif len(dialogue_nodes) >= 2:
            marked = bool(directive_nodes or scene_nodes)
            format_summary = {"kind": "aa_mixed" if marked else "dialogue", "label": "AA 指令混合格式" if marked else "角色台词格式", "confidence": "high" if len(dialogue_nodes) >= 4 else "medium", "message": "已识别“角色: 台词”结构。建立任务后，请确认每位说话者的角色映射。"}
        elif dialogue_nodes:
            format_summary = {"kind": "partial_dialogue", "label": "部分角色台词格式", "confidence": "medium", "message": "只识别到少量角色台词；建立任务后请核对识别结果。"}
        else:
            format_summary = {"kind": "freeform", "label": "自由文本或非标准格式", "confidence": "low", "message": "没有稳定识别到“角色: 台词”。仍可建立任务，但后续需要逐卡审查。"}
        actions = [{"id": "create_run", "label": "建立制作任务", "detail": "冻结当前剧本文本，并进入角色映射与逐卡审查。", "available": bool(meaningful)}]
        if speakers:
            actions.insert(0, {"id": "map_speakers", "label": "任务建立后确认角色映射", "detail": f"已识别 {len(speakers)} 位说话者；每位可选择立绘、旁白或无立绘角色。", "available": True})
        if issues:
            actions.insert(0, {"id": "repair_source", "label": "先修正指令问题", "detail": "修正后再次检查，避免把明显的格式错误带入制作草稿。", "available": True})
        return {
            "ok": True, "kind": "static_preflight", "format": format_summary, "speakers": speakers,
            "scenes": [{"title": str(node.fields.get("title") or "未命名场景"), "line_no": node.line_no} for node in scene_nodes],
            "directives": {"total": len(directive_nodes), "recognized": len(directive_nodes) - sum(1 for issue in issues if issue["code"] == "unknown_directive"), "issues": issues},
            "actions": actions,
        }

    @staticmethod
    def initial_cast(speakers: list[str]) -> dict[str, Any]:
        return {
            "default_bg": "BG_Black",
            "default_bgm": 999,
            "layout_mode": "ai",
            "scene_bg": {},
            "cast": {},
            "alias": {},
            "detected_speakers": speakers,
        }

    def create_performance_draft(
        self, *, project: str, text: str, speakers: list[str], cg_keys: list[str] | None = None
    ) -> dict[str, Any] | StagedDirectionResult:
        token = new_id("draft")
        cast = self.initial_cast(speakers)
        result = self.store.create_draft(
            token=token,
            text=text,
            project=project,
            source_text=text,
            cast=cast,
            annotation_status={
                "status": "complete",
                "completed_targets": 0,
                "total_targets": 0,
                "pending_targets": 0,
            },
        )
        self.store.save_cast(token, cast)
        if self.settings.resource_index:
            resource_path = self.store.get_draft_path(token) / "resources.json"
            resources = self._task_resource_snapshot(str(self.store.get_draft_path(token)))
            if cg_keys is not None:
                resources["popups"] = sorted(
                    {str(key) for key in cg_keys if str(key).strip()}, key=str.casefold,
                )
            resource_path.write_text(
                json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif cg_keys is not None:
            resource_path = self.store.get_draft_path(token) / "resources.json"
            resources = {"popups": []}
            resources["popups"] = sorted({str(key) for key in cg_keys if str(key).strip()}, key=str.casefold)
            resource_path.write_text(
                json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return result

    def _draft_resources(self, token: str) -> dict[str, Any]:
        resource_file = self.store.get_draft_path(token) / "resources.json"
        if not resource_file.is_file():
            return {}
        try:
            value = json.loads(resource_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def draft_resource_contains(self, token: str, kind: str, key: str) -> bool:
        resources = self._draft_resources(token)
        if kind == "backgrounds":
            values = resources.get("bg")
            return isinstance(values, dict) and key in values
        if kind == "sounds":
            values = resources.get("sounds")
            return isinstance(values, list) and key in {str(item) for item in values}
        if kind == "characters":
            values = resources.get("characters")
            return isinstance(values, list) and any(
                isinstance(item, dict) and str(item.get("identifier") or "") == key
                for item in values
            )
        if kind == "cg":
            values = resources.get("popups")
            return isinstance(values, list) and key in {str(item) for item in values}
        return False

    def draft_cg_background_contains(self, token: str, key: str) -> bool:
        return any(
            str(item.get("key") or "") == key
            for item in self._cg_background_items(token, self._draft_resources(token))
        )

    @staticmethod
    def _asset_issue_payload(issue: Any) -> dict[str, Any]:
        return {
            "code": str(getattr(issue, "code", "validation_failed")),
            "message": str(getattr(issue, "message", "素材验证失败")),
            "severity": str(getattr(issue, "severity", "error")),
        }

    @staticmethod
    def _asset_metadata_public(kind: str, metadata: Any) -> dict[str, Any]:
        value = metadata if isinstance(metadata, dict) else {}
        allowed = {
            "background": ("width", "height", "mode", "format", "has_icc_profile"),
            "cg": ("width", "height", "mode", "format", "has_icc_profile"),
            "sound": ("codec", "sample_rate", "channels", "sample_fmt", "bits_per_sample", "duration"),
            "character": (
                "identifier", "faces", "expression_parts", "expression_mode",
                "expression_status", "semantic_face_count",
                "semantic_face_combinations", "spine_version", "spine_signature",
                "outfit_key",
            ),
        }.get(kind, ())
        return {name: value[name] for name in allowed if name in value}

    def validate_task_asset(
        self, *, source: Path, kind: str, identifier: str = ""
    ) -> dict[str, Any]:
        request = {"kind": "background" if kind == "cg" else kind, "source": str(source)}
        if kind == "character":
            request["identifier"] = identifier
        try:
            result = self._modules["asset_import"].validate_asset_request(request)
        except self._modules["asset_import"].AssetImportRequestError as exc:
            raise ProductionError(getattr(exc, "code", "invalid_asset_request"), str(exc)) from exc
        return {
            "ok": bool(result.get("ok")),
            "kind": kind,
            "stem": str(result.get("stem") or ""),
            "aa_key": str(result.get("aa_key") or ""),
            "sha256": str(result.get("sha256") or ""),
            "metadata": self._asset_metadata_public(kind, result.get("metadata")),
            "issues": [
                {
                    "code": str(issue.get("code") or "validation_failed"),
                    "message": str(issue.get("message") or "素材验证失败"),
                    "severity": str(issue.get("severity") or "error"),
                }
                for issue in result.get("issues", []) if isinstance(issue, dict)
            ],
        }

    @staticmethod
    def _custom_assets_path(draft_dir: Path) -> Path:
        return draft_dir / "custom-assets.json"

    def _task_custom_assets(self, token: str) -> list[dict[str, Any]]:
        path = self._custom_assets_path(self.store.get_draft_path(token))
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _resource_items(self, resources: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        if kind == "backgrounds":
            raw = resources.get("bg") if isinstance(resources.get("bg"), dict) else {}
            labels = resources.get("bg_label") if isinstance(resources.get("bg_label"), dict) else {}
            rows = []
            for key in raw:
                label = labels.get(str(key))
                if isinstance(label, dict):
                    label = label.get("label") or label.get("description")
                rows.append({"key": str(key), "name": str(label or key)})
            return rows
        if kind == "sounds":
            raw = resources.get("sounds") if isinstance(resources.get("sounds"), list) else []
            return [{"key": str(value), "name": str(value)} for value in raw if isinstance(value, (str, int))]
        if kind == "characters":
            raw = resources.get("characters") if isinstance(resources.get("characters"), list) else []
            rows = []
            for value in raw:
                if not isinstance(value, dict) or not str(value.get("identifier") or "").strip():
                    continue
                faces = value.get("faces") if isinstance(value.get("faces"), list) else []
                rows.append({
                    "key": str(value["identifier"]), "identifier": str(value["identifier"]),
                    "name": str(value.get("name") or value["identifier"]),
                    "aliases": self.name_baseline.resolve(value)["aliases"],
                    "name_source": str(value.get("name_source") or "legacy_source_unreviewed"),
                    "club": str(value.get("club") or ""), "spine": str(value.get("spine") or ""),
                    "avatar_key": str(value.get("avatar") or value.get("avatar_key") or ""),
                    "outfit_key": str(value.get("outfit_key") or ""), "face_count": len(faces),
                })
            return rows
        if kind == "cg":
            raw = resources.get("popups") if isinstance(resources.get("popups"), list) else []
            labels = resources.get("popup_labels") if isinstance(resources.get("popup_labels"), dict) else {}
            return [
                {"key": str(value), "name": str(labels.get(str(value)) or value)}
                for value in raw
                if str(value).strip()
            ]
        raise ProductionError("resource_kind_not_found", "该任务不支持此资源类型", status=404)

    def _preview_available(self, token: str, kind: str, item: dict[str, Any]) -> bool:
        preview_kind = "backgrounds" if kind == "cg-backgrounds" else kind
        if preview_kind not in {"characters", "backgrounds", "cg"}:
            return False
        key = str(item.get("key") or "")
        if self.task_asset_preview(token, preview_kind, key) is not None:
            return True
        if preview_kind == "characters":
            return self.previews.avatar(
                avatar_key=str(item.get("avatar_key") or ""),
                spine=str(item.get("spine") or ""),
            ) is not None
        if preview_kind == "backgrounds":
            return self.previews.background(key) is not None
        return self.previews.cg(key) is not None

    def _registered_custom_background_keys(self) -> set[str]:
        database = self.settings.legacy_root / "aa_assets.db"
        if not database.is_file():
            return set()
        import sqlite3

        try:
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT DISTINCT display_name FROM asset_install "
                    "WHERE kind='background' AND status='registered'"
                ).fetchall()
        except sqlite3.Error:
            return set()
        return {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}

    def _cg_background_items(
        self, token: str, resources: dict[str, Any]
    ) -> list[dict[str, Any]]:
        task_keys = {
            str(item.get("key") or "")
            for item in self._task_custom_assets(token)
            if item.get("kind") == "background"
        }
        registered_keys = self._registered_custom_background_keys()
        rows = []
        for item in self._resource_items(resources, "backgrounds"):
            key = str(item.get("key") or "")
            if key.startswith("BG_CS_"):
                rows.append({**item, "cg_source": "official_cg"})
            elif key in task_keys or key in registered_keys:
                rows.append({**item, "cg_source": "custom_background"})
        return rows

    def list_draft_resources(
        self, token: str, kind: str, *, query: str = "", offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        resources = self._draft_resources(token)
        needle = query.strip().casefold()
        internal_kind = {"backgrounds": "background", "cg-backgrounds": "background", "sounds": "sound", "characters": "character", "cg": "cg"}.get(kind)
        imported = {
            str(asset.get("key") or ""): self.task_asset_public(asset)
            for asset in self._task_custom_assets(token)
            if asset.get("kind") == internal_kind
        }
        source_items = self._cg_background_items(token, resources) if kind == "cg-backgrounds" else self._resource_items(resources, kind)
        items = [
            {
                **{key: value for key, value in item.items() if key != "avatar_key"},
                "source": "task_import" if str(item.get("key") or "") in imported else "task_snapshot",
                "preview_available": self._preview_available(token, kind, item),
                **({"asset_id": imported[str(item.get("key") or "")]["asset_id"]}
                   if str(item.get("key") or "") in imported else {}),
            }
            for item in source_items
            if not needle or any(needle in str(item.get(name) or "").casefold() for name in ("key", "name", "club"))
            or any(needle in str(alias).casefold() for alias in item.get("aliases", []))
        ]
        items.sort(key=lambda item: (str(item.get("name") or "").casefold(), str(item["key"]).casefold()))
        start = max(0, offset)
        page_size = max(1, min(limit, 200))
        page = items[start : start + page_size]
        return {
            "ok": True,
            "kind": kind,
            "query": query,
            "items": page,
            "total": len(items),
            "offset": start,
            "limit": page_size,
            "has_more": start + len(page) < len(items),
            "frozen": True,
        }

    def draft_character_detail(self, token: str, identifier: str) -> dict[str, Any]:
        """Return a character from the task's frozen resource snapshot only."""
        key = str(identifier or "").strip()
        resources = self._draft_resources(token)
        rows = resources.get("characters") if isinstance(resources.get("characters"), list) else []
        value = next(
            (
                item for item in rows
                if isinstance(item, dict) and str(item.get("identifier") or "") == key
            ),
            None,
        )
        if value is None:
            raise ProductionError(
                "character_not_found", "该角色不在当前任务冻结的素材清单中", status=404
            )
        raw_faces = value.get("faces") if isinstance(value.get("faces"), list) else []
        faces = []
        for face in raw_faces:
            if isinstance(face, dict):
                face_id = str(face.get("id") or "").strip()
                raw = str(face.get("raw") or "").strip()
                label = str(face.get("label") or "").strip()
            else:
                face_id = raw = label = str(face or "").strip()
            if face_id or raw or label:
                faces.append({"id": face_id, "raw": raw, "label": label})
        return {
            "ok": True,
            "frozen": True,
            "character": {
                "key": key,
                "identifier": key,
                "name": str(value.get("name") or key),
                "name_zh_cn": str(value.get("name_zh_cn") or ""),
                "name_ja_fandom": str(value.get("name_ja_fandom") or ""),
                "aliases": self.name_baseline.resolve(value)["aliases"],
                "source_name": str(value.get("source_name") or value.get("legacy_name") or value.get("name") or key),
                "name_source": str(value.get("name_source") or "legacy_source_unreviewed"),
                "club": str(value.get("club") or ""),
                "spine": str(value.get("spine") or ""),
                "outfit_key": str(value.get("outfit_key") or ""),
                "faces": faces,
            },
        }

    def task_asset_preview(self, token: str, kind: str, key: str) -> tuple[Path, str] | None:
        internal_kind = {"backgrounds": "background", "characters": "character", "sounds": "sound", "cg": "cg"}.get(kind, kind)
        for item in self._task_custom_assets(token):
            if item.get("kind") != internal_kind or str(item.get("key") or "") != key:
                continue
            base = Path(str(item.get("private_source") or ""))
            if internal_kind in {"background", "cg"}:
                candidate = base
            elif internal_kind == "character":
                candidate = base / f"{item.get('outfit_key')}-avatar.png"
            else:
                return None
            if candidate.is_file():
                return candidate, mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if internal_kind == "background":
            database = self.settings.legacy_root / "aa_assets.db"
            if database.is_file():
                import sqlite3

                try:
                    with sqlite3.connect(database) as connection:
                        rows = connection.execute(
                            "SELECT install_path FROM asset_install "
                            "WHERE kind='background' AND status='registered' AND display_name=?",
                            (key,),
                        ).fetchall()
                except sqlite3.Error:
                    rows = []
                for row in rows:
                    candidate = Path(str(row[0] or ""))
                    if candidate.is_file():
                        return candidate, mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return None

    def list_task_assets(self, token: str) -> list[dict[str, Any]]:
        return [self.task_asset_public(item) for item in self._task_custom_assets(token)]

    def remove_task_asset(
        self, *, token: str, asset_id: str, expected_draft_version: int
    ) -> dict[str, Any]:
        """Remove an unused task-local custom asset and restore the prior frozen index."""
        if not re.fullmatch(r"asset-[0-9a-f]{12}", asset_id):
            raise ProductionError("invalid_task_asset_id", "素材标识无效")
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            session_path = draft_dir / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            if session["draft_version"] != expected_draft_version:
                raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
            items = self._task_custom_assets(token)
            target = next((item for item in items if item.get("asset_id") == asset_id), None)
            if target is None:
                raise ProductionError("task_asset_not_found", "当前任务没有这条自定义素材", status=404)
            detail = self.draft_detail(token)
            key = str(target.get("key") or "")
            kind = str(target.get("kind") or "")
            used = any(
                (kind == "background" and str((card.get("current") or {}).get("cmd") or "").casefold() == "bg" and str((card.get("current") or {}).get("arg") or "") == key)
                or (kind == "sound" and str((card.get("current") or {}).get("cmd") or "").casefold() in {"se", "sound"} and str((card.get("current") or {}).get("arg") or "") == key)
                or (kind == "background" and str((card.get("cg") or {}).get("background_key") or "") == key)
                for card in detail["cards"]
            )
            cast = detail.get("cast") if isinstance(detail.get("cast"), dict) else {}
            cast_values = (cast.get("cast") or {}).values() if isinstance(cast.get("cast"), dict) else []
            if kind == "character":
                used = used or any(str(value.get("id") or "") == key for value in cast_values if isinstance(value, dict))
            if used:
                raise ProductionError("asset_in_use", "该素材仍被当前草稿引用，请先替换引用后再移除", status=409)
            resources = self._draft_resources(token)
            if kind == "background":
                resources.get("bg", {}).pop(key, None)
                resources.get("bg_label", {}).pop(key, None)
            elif kind == "sound":
                resources["sounds"] = [value for value in resources.get("sounds", []) if str(value) != key]
            elif kind == "cg":
                resources["popups"] = [value for value in resources.get("popups", []) if str(value) != key]
                resources.get("popup_labels", {}).pop(key, None)
            elif kind == "character":
                resources["characters"] = [value for value in resources.get("characters", []) if not isinstance(value, dict) or str(value.get("identifier") or "") != key]
            remaining = [item for item in items if item is not target]
            (draft_dir / "resources.json").write_text(json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8")
            self._custom_assets_path(draft_dir).write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
            identities_path = draft_dir / "identity.json"
            identities = json.loads(identities_path.read_text(encoding="utf-8"))
            for identity in identities:
                identity["review_state"] = "pending"
            identity_text = json.dumps(identities, ensure_ascii=False, indent=2)
            identities_path.write_text(identity_text, encoding="utf-8")
            session["draft_version"] += 1
            session["content_revision"] += 1
            session["identity_sha256"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
            temporary = session_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, session_path)
        # Only remove the directory named by the server-generated asset id. Never derive
        # a deletion target from the persisted source path.
        shutil.rmtree(draft_dir / "custom-assets" / asset_id, ignore_errors=True)
        return self.draft_detail(token)

    def register_task_asset(
        self,
        *,
        token: str,
        source: Path,
        kind: str,
        identifier: str,
        display_name: str,
        nickname: str,
        labels: dict[str, Any],
        expected_draft_version: int,
        library_asset_id: str = "",
        recognition: dict[str, Any] | None = None,
        recognition_accepted: bool = False,
    ) -> dict[str, Any]:
        result = self.validate_task_asset(source=source, kind=kind, identifier=identifier)
        if not result["ok"]:
            return {"ok": False, "status": "rejected", **result}
        draft_dir = self.store.get_draft_path(token)
        asset_id = new_id("asset")
        private_root = draft_dir / "custom-assets" / asset_id
        if kind == "character":
            shutil.copytree(source, private_root)
            private_source = private_root
        else:
            private_root.mkdir(parents=True, exist_ok=False)
            private_source = private_root / source.name
            shutil.copy2(source, private_source)

        key = result["stem"] if kind in {"background", "sound", "cg"} else str(identifier).strip()
        metadata = result["metadata"]
        default_name = labels.get("label") if kind == "cg" else ""
        record = {
            "asset_id": asset_id, "kind": kind, "key": key, "display_name": display_name.strip() or default_name or key,
            "nickname": nickname.strip(), "labels": labels if isinstance(labels, dict) else {},
            "sha256": result["sha256"], "metadata": metadata, "private_source": str(private_source),
            "outfit_key": str(metadata.get("outfit_key") or result["stem"]), "created_at": utc_now(),
        }
        if recognition is not None:
            record["recognition"] = recognition
            record["recognition_accepted"] = bool(recognition_accepted)
        if library_asset_id:
            record["library_asset_id"] = library_asset_id
        try:
            with self.store.draft_lock(token):
                session_path = draft_dir / "session.json"
                session = json.loads(session_path.read_text(encoding="utf-8"))
                if session["draft_version"] != expected_draft_version:
                    raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
                resources = self._draft_resources(token)
                existing = self._task_custom_assets(token)
                if any(str(item.get("key") or "").casefold() == key.casefold() and item.get("kind") == kind for item in existing):
                    raise ProductionError("task_asset_conflict", "当前任务已登记同名素材", status=409)
                if kind == "background":
                    resources.setdefault("bg", {})[key] = int(result["aa_key"])
                    resources.setdefault("bg_label", {})[key] = record["labels"].get("label") or key
                elif kind == "sound":
                    values = resources.setdefault("sounds", [])
                    if key not in {str(value) for value in values}:
                        values.append(key)
                elif kind == "cg":
                    values = resources.setdefault("popups", [])
                    if key not in {str(value) for value in values}:
                        values.append(key)
                    resources.setdefault("popup_labels", {})[key] = record["display_name"]
                else:
                    rows = resources.setdefault("characters", [])
                    rows.append({
                        "identifier": key, "name": record["display_name"], "club": record["nickname"],
                        "spine": str(Path("characters") / key / record["outfit_key"]),
                        "outfit_key": record["outfit_key"], "spine_signature": metadata.get("spine_signature", ""),
                        "faces": [{"id": str(face), "raw": str(face), "label": str(face)} for face in metadata.get("faces", [])],
                    })
                resources_path = draft_dir / "resources.json"
                resources_text = json.dumps(resources, ensure_ascii=False, indent=2)
                resources_path.write_text(resources_text, encoding="utf-8")
                existing.append(record)
                self._custom_assets_path(draft_dir).write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                identities_path = draft_dir / "identity.json"
                identities = json.loads(identities_path.read_text(encoding="utf-8"))
                for identity in identities:
                    identity["review_state"] = "pending"
                identity_text = json.dumps(identities, ensure_ascii=False, indent=2)
                identities_path.write_text(identity_text, encoding="utf-8")
                session["draft_version"] += 1
                session["content_revision"] += 1
                session["identity_sha256"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
                temporary = session_path.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, session_path)
        except Exception:
            shutil.rmtree(private_root, ignore_errors=True)
            raise
        return {"ok": True, "status": "registered", "asset": self.task_asset_public(record), **result}

    @staticmethod
    def task_asset_public(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return {
            "asset_id": str(item.get("asset_id") or ""), "kind": str(item.get("kind") or ""),
            "key": str(item.get("key") or ""), "name": str(item.get("display_name") or item.get("key") or ""),
            "club": str(item.get("nickname") or ""), "labels": item.get("labels") if isinstance(item.get("labels"), dict) else {},
            "metadata": Legacy093Adapter._asset_metadata_public(str(item.get("kind") or ""), metadata),
            "library_asset_id": str(item.get("library_asset_id") or ""),
            "recognition": item.get("recognition") if isinstance(item.get("recognition"), dict) else None,
            "recognition_accepted": bool(item.get("recognition_accepted")),
            "created_at": str(item.get("created_at") or ""),
        }

    def draft_detail(self, token: str) -> dict[str, Any]:
        try:
            draft = self.store.load_draft(token)
        except FileNotFoundError as exc:
            raise ProductionError("draft_not_found", "演出草稿不存在", status=404) from exc
        nodes = self.document.normalize_draft_nodes(
            self.document.parse_document_lossless(draft["edited_text"])
        )
        cast_data = self.store.load_cast(token)
        cast = cast_data.get("cast") if isinstance(cast_data.get("cast"), dict) else cast_data
        _, diagnostics = self.document.compile_document(
            nodes,
            cast if isinstance(cast, dict) else {},
            self._draft_resources(token),
        )
        cards = []
        for node, identity in zip(nodes, draft["identities"]):
            card_id = identity["card_id"]
            issues = [
                item
                for item in diagnostics
                if item.get("card_id") == card_id
                or (not item.get("card_id") and item.get("line_no") == node.line_no)
            ]
            cards.append(
                {
                    "card_id": card_id,
                    "source_id": identity.get("source_id"),
                    "origin": identity.get("origin", "source"),
                    "order_key": identity.get("order_key"),
                    "line_no": node.line_no,
                    "kind": node.kind,
                    "current": node.fields,
                    "raw": node.raw,
                    "review_state": identity.get("review_state", "pending"),
                    "issues": issues,
                }
            )
        segments = cg_segments.load(self.store.get_draft_path(token) / "cg-segments.json")
        cg_issues, cg_membership = cg_segments.validate(segments=segments, cards=cards)
        diagnostics.extend(cg_issues)
        for card in cards:
            card["cg"] = cg_membership.get(card["card_id"])
            card["issues"].extend(
                issue for issue in cg_issues if issue.get("card_id") == card["card_id"]
            )
        counts = {
            "total": len(cards),
            "pending": sum(card["review_state"] == "pending" for card in cards),
            "unresolved_issues": sum(
                item.get("severity") in ("error", "warning") for item in diagnostics
            ),
            "blocking_errors": sum(
                item.get("severity") == "error" for item in diagnostics
            ),
        }
        return {
            "draft_token": token,
            "project": draft["session"].get("project"),
            "draft_version": draft["session"]["draft_version"],
            "content_revision": draft["session"]["content_revision"],
            "cards": cards,
            "diagnostics": diagnostics,
            "counts": counts,
            "cast": self.store.load_cast(token),
            "cg_segments": segments,
            "review_ready": not any(
                counts[key] for key in ("pending", "unresolved_issues", "blocking_errors")
            ),
        }

    _AI_PREFLIGHT_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "potential_speakers": {
                "type": "array", "maxItems": 32,
                "items": {"type": "string", "maxLength": 28},
            },
            "scenes": {
                "type": "array", "maxItems": 80,
                "items": {
                    "type": "object", "additionalProperties": True,
                    "properties": {
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                        "location": {"type": "string", "maxLength": 100},
                        "time": {"type": "string", "maxLength": 40},
                        "background_need": {"type": "string", "maxLength": 120},
                    },
                    # Location/time/background are advisory and models may
                    # omit them when the frozen script does not provide
                    # enough evidence. Normalize those fields to empty
                    # strings below instead of failing the whole preflight.
                    "required": [],
                },
            },
            "ambiguities": {
                "type": "array", "maxItems": 80,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "line": {"type": "integer", "minimum": 1},
                        "message": {"type": "string", "maxLength": 240},
                    },
                    "required": ["line", "message"],
                },
            },
        },
        "required": ["potential_speakers", "scenes", "ambiguities"],
    }

    @staticmethod
    def _ai_preflight_text(value: Any, *, maximum: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) > maximum:
            raise ProductionError("ai_preflight_invalid_output", "AI 初审结果包含过长字段", status=502)
        return text

    def _validate_ai_preflight_result(self, value: Any, *, line_count: int) -> dict[str, Any]:
        """Validate the narrow read-only contract independently of the provider."""
        if not isinstance(value, dict) or set(value) != set(self._AI_PREFLIGHT_SCHEMA["required"]):
            raise ProductionError("ai_preflight_invalid_output", "AI 初审没有返回约定的结构化结果", status=502)
        speakers = value.get("potential_speakers")
        scenes = value.get("scenes")
        ambiguities = value.get("ambiguities")
        if not all(isinstance(item, list) for item in (speakers, scenes, ambiguities)):
            raise ProductionError("ai_preflight_invalid_output", "AI 初审结果字段类型不正确", status=502)
        if len(speakers) > 32 or len(scenes) > 80 or len(ambiguities) > 80:
            raise ProductionError("ai_preflight_invalid_output", "AI 初审结果条目过多", status=502)

        normalized_speakers: list[str] = []
        seen_speakers: set[str] = set()
        for item in speakers:
            if not isinstance(item, str):
                raise ProductionError("ai_preflight_invalid_output", "AI 初审包含无效说话者", status=502)
            name = self._ai_preflight_text(item, maximum=28)
            key = name.casefold()
            if name and key not in seen_speakers:
                normalized_speakers.append(name)
                seen_speakers.add(key)

        normalized_scenes: list[dict[str, Any]] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            start, end = item.get("start_line"), item.get("end_line")
            if start is None:
                start = item.get("line_start") or item.get("start")
            if end is None:
                end = item.get("line_end") or item.get("end")
            if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
                continue
            if start < 1 or end < start or end > max(1, line_count):
                raise ProductionError("ai_preflight_invalid_output", "AI 初审场景行号超出冻结剧本范围", status=502)
            normalized_scenes.append({
                "start_line": start,
                "end_line": end,
                "location": self._ai_preflight_text(item.get("location"), maximum=100),
                "time": self._ai_preflight_text(item.get("time"), maximum=40),
                "background_need": self._ai_preflight_text(item.get("background_need"), maximum=120),
            })

        normalized_ambiguities: list[dict[str, Any]] = []
        for item in ambiguities:
            if not isinstance(item, dict) or set(item) != {"line", "message"}:
                raise ProductionError("ai_preflight_invalid_output", "AI 初审包含无效待确认项", status=502)
            line = item.get("line")
            if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= max(1, line_count):
                raise ProductionError("ai_preflight_invalid_output", "AI 初审待确认项行号无效", status=502)
            message = self._ai_preflight_text(item.get("message"), maximum=240)
            if message:
                normalized_ambiguities.append({"line": line, "message": message})
        return {
            "potential_speakers": normalized_speakers,
            "scenes": normalized_scenes,
            "ambiguities": normalized_ambiguities,
        }

    def execute_ai_preflight(self, *, token: str, preflight_id: str, provider: Any) -> dict[str, Any]:
        """Run a source-only AI preflight without modifying the draft or cast."""
        draft_dir = self.store.get_draft_path(token)
        draft = self.store.load_draft(token)
        text = str(draft.get("source_text") or draft.get("edited_text") or "")
        if not text.strip():
            raise ProductionError("ai_preflight_source_missing", "冻结剧本内容不可用，无法执行 AI 初审", status=409)
        lines = text.splitlines()
        system = (
            "你是 AA 剧本制作的只读初审助手。只分析冻结剧本，不改写台词，不生成 AA 指令，"
            "不选择角色骨骼、不登记素材。只返回 JSON。potential_speakers 只列出规则解析可能遗漏的说话者；"
            "scenes 只在地点、室内外或时间明确变化时分段；background_need 写该段需要的背景描述，"
            "不确定则留空字符串；ambiguities 只列必须由用户确认、且会影响场景或角色理解的信息。"
        )
        # Keep server-only validation metadata out of the model context. The
        # provider validates the returned JSON against a strict schema, and
        # exposing line_count invites otherwise harmless metadata echoing.
        volatile = ""
        numbered = "\n".join(f"L{index + 1}\t{line}" for index, line in enumerate(lines) if line.strip())
        user = "请分析以下带行号的冻结剧本。行号仅用于定位，直接返回 JSON。\n\n" + numbered
        try:
            result = provider.complete_json(system, volatile, user, self._AI_PREFLIGHT_SCHEMA)
        except ProductionError:
            raise
        except Exception as exc:
            raise ProductionError("ai_preflight_failed", str(exc), status=502) from exc
        analysis = self._validate_ai_preflight_result(result, line_count=len(lines))
        record = {
            "kind": "ai_preflight",
            "plan_version": 1,
            "preflight_id": preflight_id,
            "created_at": utc_now(),
            "source": {
                "kind": "frozen_source",
                "line_count": len(lines),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            },
            "model": {"provider": str(getattr(provider, "name", "")), "name": str(getattr(provider, "model", ""))},
            "analysis": analysis,
        }
        output_dir = draft_dir / "ai-preflights"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{preflight_id}.json"
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, output)
        return record

    def ai_preflights(self, token: str) -> dict[str, Any]:
        root = self.store.get_draft_path(token) / "ai-preflights"
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("preflight-*.json"), reverse=True) if root.is_dir() else []:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("kind") != "ai_preflight":
                continue
            analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
            items.append({
                "preflight_id": str(record.get("preflight_id") or ""),
                "created_at": str(record.get("created_at") or ""),
                "source": {"kind": "frozen_source", "line_count": int((record.get("source") or {}).get("line_count") or 0)},
                "model": {
                    "provider": str((record.get("model") or {}).get("provider") or ""),
                    "name": str((record.get("model") or {}).get("name") or ""),
                },
                "analysis": {
                    "potential_speakers": analysis.get("potential_speakers") if isinstance(analysis.get("potential_speakers"), list) else [],
                    "scenes": analysis.get("scenes") if isinstance(analysis.get("scenes"), list) else [],
                    "ambiguities": analysis.get("ambiguities") if isinstance(analysis.get("ambiguities"), list) else [],
                },
            })
        return {"ok": True, "kind": "ai_preflight_results", "read_only": True, "items": items}

    def _compatible_performance_plan(
        self, token: str, source_text: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        root = self.store.get_draft_path(token) / "ai-preflights"
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        candidates: list[dict[str, Any]] = []
        for path in root.glob("preflight-*.json") if root.is_dir() else []:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
            if (
                record.get("kind") != "ai_preflight"
                or int(record.get("plan_version") or 0) != 1
                or source.get("sha256") != source_hash
                or not isinstance(analysis.get("scenes"), list)
            ):
                continue
            candidates.append(record)
        if not candidates:
            return [], None
        record = max(candidates, key=lambda item: str(item.get("created_at") or ""))
        scenes = []
        for index, scene in enumerate((record.get("analysis") or {}).get("scenes") or [], 1):
            if not isinstance(scene, dict):
                continue
            scenes.append({
                "segment": f"AI 初审场景 {index}",
                "start": int(scene.get("start_line") or 0),
                "end": int(scene.get("end_line") or 0),
                "location": str(scene.get("location") or ""),
                "time": str(scene.get("time") or ""),
                "reason": str(scene.get("background_need") or ""),
                "needs": [],
                "source": "ai_preflight",
            })
        return scenes, {
            "plan_version": 1,
            "preflight_id": str(record.get("preflight_id") or ""),
            "scene_count": len(scenes),
            "source_sha256": source_hash,
        }

    @staticmethod
    def _proposal_value_public(value: Any) -> str | None:
        """Keep the audit useful without exposing arbitrary model payloads."""
        if value is None:
            return None
        value = str(value).strip()
        return value[:240] if value else None

    def direction_proposals(self, token: str) -> dict[str, Any]:
        """Expose task-local AI suggestions with conservative stable-card links."""
        root = self.store.get_draft_path(token) / "direction-generations"
        generations: list[dict[str, Any]] = []
        if not root.is_dir():
            return {"ok": True, "total": 0, "generations": []}
        current_revision = self.draft_detail(token).get("content_revision")
        for attempt_dir in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
            result_file = attempt_dir / "result.json"
            proposals_file = attempt_dir / "proposals.json"
            if not result_file.is_file():
                continue
            try:
                result = json.loads(result_file.read_text(encoding="utf-8"))
                proposals = json.loads(proposals_file.read_text(encoding="utf-8")) if proposals_file.is_file() else []
            except (OSError, json.JSONDecodeError):
                continue
            public_items = []
            for proposal in proposals if isinstance(proposals, list) else []:
                if not isinstance(proposal, dict):
                    continue
                proposal_type = str(proposal.get("type") or "")
                if proposal_type not in {"applied_pending", "suggested_fix"}:
                    continue
                field = str(proposal.get("field") or "")
                if field not in {"face", "emo", "act", "fx"}:
                    continue
                safe_card_id = str(proposal.get("safe_card_id") or "")
                content_revision = proposal.get("based_on_content_revision")
                safe = bool(
                    proposal_type == "applied_pending"
                    and safe_card_id
                    and content_revision == current_revision
                    and proposal.get("state") == "pending"
                )
                if safe:
                    reason = "已唯一对应到当前草稿中的一张台词。你可以保留这项 AI 标注，或撤销并恢复生成前的值。"
                elif proposal_type == "suggested_fix":
                    reason = "模型提出了建议，但它没有写入草稿；请在逐卡审查器中自行决定是否采用。"
                elif safe_card_id:
                    reason = "这条建议已经处理，或草稿内容已变化；为避免覆盖后续编辑，不能再次执行。"
                else:
                    reason = "生成结果无法唯一对应到一张当前台词；为避免误改，系统只保留这条记录供参考。"
                public_items.append(
                    {
                        "proposal_id": str(proposal.get("proposal_id") or ""),
                        "type": proposal_type,
                        "rule": str(proposal.get("rule") or ""),
                        "field": field,
                        "before": self._proposal_value_public(proposal.get("before")),
                        "after": self._proposal_value_public(proposal.get("after")),
                        "state": str(proposal.get("state") or "pending"),
                        "card_id": safe_card_id if safe_card_id else None,
                        "can_apply_safely": safe,
                        "apply_reason": reason,
                    }
                )
            raw_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
            public_metrics = {
                key: raw_metrics.get(key)
                for key in (
                    "requests", "retries", "transport_retries", "subdivisions", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens", "uncached_input_tokens",
                    "cache_hit_rate", "cache_reported", "warm_cache_read_tokens",
                    "warm_uncached_input_tokens", "warm_cache_hit_rate",
                    "failed_request_count", "failed_request_input_tokens",
                    "failed_request_output_tokens", "input_tokens_per_completed_target",
                    "uncached_input_tokens_per_completed_target", "stable_prefix_consistent",
                    "elapsed_ms", "completed_targets", "total_targets",
                )
                if key in raw_metrics
            }
            if isinstance(raw_metrics.get("prompt_optimization"), dict):
                optimization = raw_metrics["prompt_optimization"]
                public_metrics["prompt_optimization"] = {
                    key: optimization.get(key)
                    for key in (
                        "version", "background_count", "sound_count",
                        "full_background_count", "full_sound_count",
                        "full_resource_prompt_chars", "candidate_resource_prompt_chars",
                        "resource_prompt_reduction", "source_context_strategy",
                        "source_script_chars_in_static_prompt",
                    )
                    if key in optimization
                }
            if isinstance(raw_metrics.get("request_records"), list):
                public_metrics["request_records"] = [
                    {
                        str(key)[:80]: value
                        for key, value in record.items()
                        if key not in {
                            "prompt", "user", "volatile", "static_system",
                            "reasoning_text",
                        }
                    }
                    for record in raw_metrics["request_records"][-50:]
                    if isinstance(record, dict)
                ]
            public_diagnostics = []
            for diagnostic in result.get("diagnostics") or []:
                if not isinstance(diagnostic, dict):
                    continue
                public_diagnostics.append({
                    key: str(diagnostic.get(key) or "")[:500]
                    for key in ("code", "level", "message", "detail", "scene_id", "chunk_id")
                    if diagnostic.get(key) not in (None, "")
                })
                if len(public_diagnostics) >= 50:
                    break
            raw_error = result.get("error") if isinstance(result.get("error"), dict) else None
            public_error = None
            if raw_error:
                public_error = {
                    "code": str(raw_error.get("code") or "direction_generation_failed")[:160],
                    "message": str(raw_error.get("message") or "演出生成失败")[:1000],
                    "type": str(raw_error.get("type") or "")[:160],
                }
            generations.append(
                {
                    "generation_id": str(result.get("generation_id") or attempt_dir.name),
                    "model": str(result.get("model") or ""),
                    "story_type": str(result.get("story_type") or "auto"),
                    "layout_mode": str(result.get("layout_mode") or "ai"),
                    "status": str(result.get("status") or "succeeded"),
                    "draft_version": result.get("draft_version"),
                    "pending_targets": int(result.get("pending_targets") or 0),
                    "metrics": public_metrics,
                    "diagnostics": public_diagnostics,
                    "error": public_error,
                    "proposal_count": len(public_items),
                    "proposals": public_items,
                }
            )
        return {
            "ok": True,
            "total": sum(item["proposal_count"] for item in generations),
            "generations": generations,
        }

    @staticmethod
    def _proposal_card_matches(
        *, proposal: dict[str, Any], source_cards: list[dict[str, Any]], result_cards: list[dict[str, Any]]
    ) -> list[str]:
        """Return a card only when the proposal delta identifies it uniquely.

        The old annotator's proposal IDs were created before the draft write and
        may be random.  A match therefore needs both the generated field value
        and an unchanged speaker/text anchor back to a source card.  Duplicate
        dialogue or an inserted beat makes the result intentionally ambiguous.
        """
        if str(proposal.get("type") or "") != "applied_pending":
            return []
        field = str(proposal.get("field") or "")
        if field not in {"face", "emo", "act", "fx"}:
            return []
        before = str(proposal.get("before") or "").strip()
        after = str(proposal.get("after") or "").strip()
        if not after or before == after:
            return []
        source_by_dialogue: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for card in source_cards:
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            if card.get("kind") != "line":
                continue
            key = (str(current.get("who") or "").strip(), str(current.get("text") or "").strip())
            source_by_dialogue.setdefault(key, []).append(card)
        matches: list[str] = []
        for card in result_cards:
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            if card.get("kind") != "line" or str(current.get(field) or "").strip() != after:
                continue
            key = (str(current.get("who") or "").strip(), str(current.get("text") or "").strip())
            source = source_by_dialogue.get(key) or []
            if len(source) != 1 or str(source[0].get("current", {}).get(field) or "").strip() != before:
                continue
            matches.append(str(card.get("card_id") or ""))
        return [card_id for card_id in matches if card_id]

    def _anchor_direction_proposals(
        self, *, token: str, proposals: list[dict[str, Any]], source_cards: list[dict[str, Any]], content_revision: int
    ) -> list[dict[str, Any]]:
        result_cards = self.draft_detail(token).get("cards") or []
        anchored: list[dict[str, Any]] = []
        for original in proposals:
            proposal = dict(original) if isinstance(original, dict) else {}
            matches = self._proposal_card_matches(
                proposal=proposal, source_cards=source_cards, result_cards=result_cards
            )
            if len(matches) == 1:
                proposal["safe_card_id"] = matches[0]
                proposal["based_on_content_revision"] = content_revision
            else:
                proposal.pop("safe_card_id", None)
            anchored.append(proposal)
        return anchored

    def decide_direction_proposal(
        self, *, token: str, proposal_id: str, action: str, expected_draft_version: int
    ) -> dict[str, Any]:
        """Confirm or safely revert an AI-applied annotation.

        Confirming records an audit decision only. Reverting changes exactly one
        card through the normal version-checked update path.
        """
        if action not in {"approve", "reject"}:
            raise ProductionError("invalid_proposal_action", "只能保留或撤销 AI 已写入的建议")
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            root = draft_dir / "direction-generations"
            selected: tuple[Path, list[dict[str, Any]], dict[str, Any]] | None = None
            for attempt_dir in root.iterdir() if root.is_dir() else []:
                proposals_file = attempt_dir / "proposals.json"
                if not proposals_file.is_file():
                    continue
                try:
                    proposals = json.loads(proposals_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for proposal in proposals if isinstance(proposals, list) else []:
                    if not isinstance(proposal, dict):
                        continue
                    if str(proposal.get("proposal_id") or "") == proposal_id:
                        selected = (proposals_file, proposals, proposal)
                        break
                if selected:
                    break
            if not selected:
                raise ProductionError("proposal_not_found", "找不到这条 AI 演出建议", status=404)
            proposals_file, proposals, proposal = selected
            if proposal.get("type") != "applied_pending" or not proposal.get("safe_card_id"):
                raise ProductionError("proposal_not_safely_actionable", "这条建议无法安全地作用到当前草稿，请在逐卡审查器中处理", status=409)
            if proposal.get("state") != "pending":
                raise ProductionError("proposal_already_decided", "这条建议已经处理过", status=409)
            detail = self.draft_detail(token)
            if detail.get("draft_version") != expected_draft_version:
                raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
            if proposal.get("based_on_content_revision") != detail.get("content_revision"):
                raise ProductionError("proposal_stale", "草稿内容已经变化；这条建议不再适用", status=409)
            card_id = str(proposal["safe_card_id"])
            card = next((item for item in detail.get("cards") or [] if item.get("card_id") == card_id), None)
            field = str(proposal.get("field") or "")
            if not card or str((card.get("current") or {}).get(field) or "").strip() != str(proposal.get("after") or "").strip():
                raise ProductionError("proposal_stale", "对应台词已经被修改；这条建议不再适用", status=409)
            if action == "reject":
                self.update_card(
                    token=token, card_id=card_id,
                    patch={field: str(proposal.get("before") or "")},
                    expected_draft_version=expected_draft_version,
                )
            proposal["state"] = "approved" if action == "approve" else "rejected"
            proposal["decision"] = "kept" if action == "approve" else "reverted"
            temporary = proposals_file.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, proposals_file)
        return self.draft_detail(token)

    def create_cg_segment(
        self,
        *,
        token: str,
        start_card_id: str,
        end_card_id: str,
        background_key: str,
        label: str,
        expected_draft_version: int,
    ) -> dict[str, Any]:
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            session_path = draft_dir / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            if session["draft_version"] != expected_draft_version:
                raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
            segments = cg_segments.load(draft_dir / "cg-segments.json")
            segment = cg_segments.create(
                start_card_id=start_card_id,
                end_card_id=end_card_id,
                background_key=background_key,
                label=label,
            )
            segments.append(segment)
            detail = self.draft_detail(token)
            issues, _ = cg_segments.validate(segments=segments, cards=detail["cards"])
            if issues:
                raise ProductionError("cg_segment_invalid", "CG 段落无法建立", details={"issues": issues})
            cg_segments.save(draft_dir / "cg-segments.json", segments)
            identities_path = draft_dir / "identity.json"
            identities = json.loads(identities_path.read_text(encoding="utf-8"))
            for identity in identities:
                identity["review_state"] = "pending"
            identity_text = json.dumps(identities, ensure_ascii=False, indent=2)
            identities_path.write_text(identity_text, encoding="utf-8")
            session["draft_version"] += 1
            session["content_revision"] += 1
            session["identity_sha256"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
            temporary = session_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, session_path)
        return self.draft_detail(token)

    def execute_cg_advice(
        self, *, token: str, provider: Any, start_card_id: str, end_card_id: str
    ) -> dict[str, Any]:
        detail = self.draft_detail(token)
        advice = cg_advice.advise(
            provider,
            cards=detail["cards"],
            start_card_id=start_card_id,
            end_card_id=end_card_id,
        )
        return {
            "ok": True,
            "kind": "cg_advice",
            "read_only": True,
            "range": {"start_card_id": start_card_id, "end_card_id": end_card_id},
            "advice": advice,
            "model": {"provider": str(getattr(provider, "name", "")), "name": str(getattr(provider, "model", ""))},
            "usage": dict(getattr(provider, "stats", {}) or {}),
        }

    def delete_cg_segment(
        self, *, token: str, segment_id: str, expected_draft_version: int
    ) -> dict[str, Any]:
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            session_path = draft_dir / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            if session["draft_version"] != expected_draft_version:
                raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
            segments = cg_segments.load(draft_dir / "cg-segments.json")
            remaining = [item for item in segments if item.get("segment_id") != segment_id]
            if len(remaining) == len(segments):
                raise ProductionError("cg_segment_not_found", "CG 段落不存在", status=404)
            cg_segments.save(draft_dir / "cg-segments.json", remaining)
            identities_path = draft_dir / "identity.json"
            identities = json.loads(identities_path.read_text(encoding="utf-8"))
            for identity in identities:
                identity["review_state"] = "pending"
            identity_text = json.dumps(identities, ensure_ascii=False, indent=2)
            identities_path.write_text(identity_text, encoding="utf-8")
            session["draft_version"] += 1
            session["content_revision"] += 1
            session["identity_sha256"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
            temporary = session_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, session_path)
        return self.draft_detail(token)

    def update_cast_binding(
        self,
        *,
        token: str,
        speaker: str,
        mapping: dict[str, Any],
        expected_draft_version: int,
    ) -> dict[str, Any]:
        allowed_kinds = {"portrait", "voice", "narrator", "unset"}
        kind = str(mapping.get("kind") or "").strip()
        if kind not in allowed_kinds:
            raise ProductionError(
                "invalid_cast_kind",
                "角色映射类型无效",
                details={"allowed": sorted(allowed_kinds)},
            )
        normalized = dict(mapping)
        if kind == "narrator":
            normalized = {"kind": "narrator", "narrator": True}
        elif kind == "voice":
            normalized = {
                "kind": "voice",
                "id": str(mapping.get("display_name") or speaker),
                "name": str(mapping.get("display_name") or speaker),
                "portrait": False,
                "narrator": False,
            }
        elif kind == "unset":
            normalized = {"kind": "unset"}
        elif not str(mapping.get("id") or "").strip():
            raise ProductionError("cast_id_required", "有立绘角色必须提供 AA 角色 ID")
        try:
            self.store.update_cast(
                token=token,
                speaker=speaker,
                mapping=normalized,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        return self.draft_detail(token)

    def approve_cards(
        self, *, token: str, card_ids: list[str] | None, expected_draft_version: int
    ) -> dict[str, Any]:
        try:
            self.store.batch_approve_reviews(
                token=token,
                card_ids=card_ids,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        return self.draft_detail(token)

    def update_card(
        self,
        *,
        token: str,
        card_id: str,
        patch: dict[str, Any],
        expected_draft_version: int,
    ) -> dict[str, Any]:
        try:
            updated = self.store.update_card_content(
                token=token,
                card_id=card_id,
                patch=patch,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        except KeyError as exc:
            raise ProductionError("card_not_found", "卡片不存在", status=404) from exc
        for identity in updated["identities"]:
            if identity.get("card_id") == card_id:
                identity["review_state"] = "pending"
                break
        self._repair_updated_card_fingerprint(token, card_id, updated)
        return self.draft_detail(token)

    def _repair_updated_card_fingerprint(
        self, token: str, card_id: str, updated: dict[str, Any]
    ) -> None:
        """Repair a 0.9.2 single-card fingerprint without changing its source."""
        nodes = self.document.normalize_draft_nodes(
            self.document.parse_document_lossless(updated["edited_text"])
        )
        identities = updated["identities"]
        target_index = next(
            (index for index, item in enumerate(identities) if item["card_id"] == card_id),
            None,
        )
        if target_index is None or target_index >= len(nodes):
            raise ProductionError(
                "draft_identity_corrupted",
                "卡片修改后无法保持稳定身份",
                status=500,
            )
        identities[target_index]["text_fingerprint"] = hashlib.sha1(
            nodes[target_index].raw.strip().encode("utf-8")
        ).hexdigest()

        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            identity_text = json.dumps(identities, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_text, encoding="utf-8")
            session_path = draft_dir / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8"))
            session["identity_sha256"] = hashlib.sha256(
                identity_text.encode("utf-8")
            ).hexdigest()
            temporary = session_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, session_path)

    def insert_card(
        self,
        *,
        token: str,
        after_card_id: str | None,
        kind: str,
        fields: dict[str, Any],
        expected_draft_version: int,
    ) -> dict[str, Any]:
        try:
            self.store.insert_card(
                token=token,
                after_card_id=after_card_id,
                kind=kind,
                payload=fields,
                origin="manual",
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        return self.draft_detail(token)

    def move_card(
        self,
        *,
        token: str,
        card_id: str,
        before_card_id: str | None,
        expected_draft_version: int,
    ) -> dict[str, Any]:
        try:
            self.store.move_card(
                token=token,
                card_id=card_id,
                before_card_id=before_card_id,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        except KeyError as exc:
            raise ProductionError("card_not_found", "卡片不存在", status=404) from exc
        return self.draft_detail(token)

    def delete_card(
        self,
        *,
        token: str,
        card_id: str,
        expected_draft_version: int,
    ) -> dict[str, Any]:
        detail = self.draft_detail(token)
        card = next((item for item in detail["cards"] if item["card_id"] == card_id), None)
        if not card:
            raise ProductionError("card_not_found", "卡片不存在", status=404)
        if card["kind"] == "background_request":
            raise ProductionError(
                "request_card_requires_resolution",
                "背景请求卡必须明确选择背景或黑屏，不能直接删除",
                status=409,
            )
        try:
            self.store.delete_card(
                token=token,
                card_id=card_id,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        return self.draft_detail(token)

    def resolve_background(
        self,
        *,
        token: str,
        card_id: str,
        background_key: str,
        expected_draft_version: int,
    ) -> dict[str, Any]:
        detail = self.draft_detail(token)
        card = next((item for item in detail["cards"] if item["card_id"] == card_id), None)
        if not card:
            raise ProductionError("card_not_found", "卡片不存在", status=404)
        if card["kind"] != "background_request":
            raise ProductionError(
                "card_is_not_background_request",
                "只能处理背景请求卡",
                status=409,
            )
        try:
            self.store.resolve_background_request(
                token=token,
                card_id=card_id,
                bg_name=background_key,
                expected_draft_version=expected_draft_version,
            )
        except self._modules["draft_store"].RevisionConflictError as exc:
            raise ProductionError("revision_conflict", str(exc), status=409) from exc
        return self.draft_detail(token)

    def resolve_sound(
        self,
        *,
        token: str,
        card_id: str,
        action: str,
        sound_key: str | None,
        expected_draft_version: int,
    ) -> dict[str, Any]:
        detail = self.draft_detail(token)
        card = next((item for item in detail["cards"] if item["card_id"] == card_id), None)
        if not card:
            raise ProductionError("card_not_found", "卡片不存在", status=404)
        current = card.get("current") if isinstance(card.get("current"), dict) else {}
        if card["kind"] != "dir" or str(current.get("cmd") or "").casefold() not in {
            "se",
            "sound",
        }:
            raise ProductionError(
                "card_is_not_sound_directive",
                "只能处理音效指令卡",
                status=409,
            )
        if action == "remove":
            try:
                self.store.delete_card(
                    token=token,
                    card_id=card_id,
                    expected_draft_version=expected_draft_version,
                )
            except self._modules["draft_store"].RevisionConflictError as exc:
                raise ProductionError("revision_conflict", str(exc), status=409) from exc
        else:
            try:
                updated = self.store.update_card_content(
                    token=token,
                    card_id=card_id,
                    patch={"cmd": "se", "arg": sound_key},
                    expected_draft_version=expected_draft_version,
                )
            except self._modules["draft_store"].RevisionConflictError as exc:
                raise ProductionError("revision_conflict", str(exc), status=409) from exc
            self._repair_updated_card_fingerprint(token, card_id, updated)
        return self.draft_detail(token)

    def validate(self, token: str) -> dict[str, Any]:
        detail = self.draft_detail(token)
        blockers = []
        if detail["counts"]["blocking_errors"]:
            blockers.append(
                {
                    "code": "blocking_diagnostics",
                    "count": detail["counts"]["blocking_errors"],
                }
            )
        if detail["counts"].get("unresolved_issues"):
            blockers.append(
                {
                    "code": "unresolved_issues",
                    "count": detail["counts"]["unresolved_issues"],
                }
            )
        if detail["counts"]["pending"]:
            blockers.append(
                {"code": "pending_review", "count": detail["counts"]["pending"]}
            )
        return {
            "ok": True,
            "review_ready": detail["review_ready"],
            "counts": detail["counts"],
            "blockers": blockers,
        }

    def create_compile_snapshot(self, token: str, expected_draft_version: int) -> str:
        capabilities = self.capabilities()["compile"]
        if capabilities["state"] != "available":
            raise ProductionError(
                "compile_not_configured",
                "编译需要资源索引和明确配置的 AA 工作区",
                status=409,
                details=capabilities,
            )
        detail = self.draft_detail(token)
        if (
            detail["counts"]["blocking_errors"]
            or detail["counts"].get("unresolved_issues")
            or detail["counts"]["pending"]
        ):
            raise ProductionError(
                "review_pending",
                "草稿仍有待审卡片或未解决错误",
                status=409,
                details=detail["counts"],
            )
        draft_dir = self.store.get_draft_path(token)
        try:
            self.store.assert_review_ready(token)
            manager = self._modules["build_bundle"].BuildBundleManager(store=self.store)
            build_id = manager.create_compile_snapshot(token, expected_draft_version)
            source = draft_dir / "edited.txt"
            identities = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            segments = cg_segments.load(draft_dir / "cg-segments.json")
            if segments:
                transformed, aliases = cg_segments.transform_for_compile(
                    text=source.read_text(encoding="utf-8"), identities=identities, segments=segments
                )
                input_dir = draft_dir / "builds" / ".tmp" / build_id / "input"
                (input_dir / "edited.txt").write_text(transformed, encoding="utf-8")
                cast_path = input_dir / "cast.json"
                cast_data = json.loads(cast_path.read_text(encoding="utf-8"))
                cast_data.setdefault("cast", {}).update(aliases)
                cast_path.write_text(json.dumps(cast_data, ensure_ascii=False, indent=2), encoding="utf-8")
                (input_dir / "cg-plan.json").write_text(
                    json.dumps({"segments": segments, "mode": "named_slot_zero_no_portraits"}, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            return build_id
        except self._modules["draft_store"].ReviewPendingError as exc:
            raise ProductionError(
                getattr(exc, "code", "review_pending"),
                str(exc),
                status=409,
                details=getattr(exc, "counts", {}),
            ) from exc
        except self._modules["build_bundle"].CompileInputStaleError as exc:
            raise ProductionError("compile_input_stale", str(exc), status=409) from exc

    def execute_compile(self, token: str, build_id: str) -> dict[str, Any]:
        with _COMPILE_LOCK:
            script2aap = importlib.import_module("script2aap")
            original_here = script2aap.HERE
            build_bundle = self._modules["build_bundle"]
            original_compile = build_bundle.compile_script

            def isolated_compile(options: dict, **kwargs: Any) -> dict[str, Any]:
                isolated_options = dict(options)
                isolated_options["aa_data"] = str(self.settings.aa_data)
                isolated_options["portrait_layout_mode"] = "snapshot_only"
                return original_compile(isolated_options, **kwargs)

            script2aap.HERE = str(self.compat_root)
            build_bundle.compile_script = isolated_compile
            try:
                manager = build_bundle.BuildBundleManager(store=self.store)
                result = manager.execute_build_worker(token, build_id)
                self._inject_task_assets_into_bundle(token=token, bundle_dir=Path(result["bundle_dir"]))
                return result
            finally:
                build_bundle.compile_script = original_compile
                script2aap.HERE = original_here

    def _inject_task_assets_into_bundle(self, *, token: str, bundle_dir: Path) -> None:
        """Attach task-owned custom files after legacy compilation, before install validation."""
        custom_assets = self._task_custom_assets(token)
        if not custom_assets:
            return
        project = bundle_dir / "project"
        aa_registry = importlib.import_module("aa_registry")
        manifest = aa_registry.load_manifest(project)
        for item in custom_assets:
            kind = str(item.get("kind") or "")
            source = Path(str(item.get("private_source") or ""))
            key = str(item.get("key") or "")
            if kind == "background" and source.is_file():
                destination = project / "bgs" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                value = str(Path("bgs") / source.name).replace("/", "\\")
                if value not in manifest["BgOverrides"]:
                    manifest["BgOverrides"].append(value)
            elif kind == "sound" and source.is_file():
                destination = project / "sounds" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                value = str(Path("sounds") / source.name).replace("/", "\\")
                if value not in manifest["SoundOverrides"]:
                    manifest["SoundOverrides"].append(value)
            elif kind == "cg" and source.is_file():
                # `cg` is the foreground image/popup asset kind. CG scenes use
                # regular backgrounds and therefore enter through BgOverrides.
                destination = project / "popups" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                value = str(Path("popups") / source.name).replace("/", "\\")
                if value not in manifest["PopupOverrides"]:
                    manifest["PopupOverrides"].append(value)
            elif kind == "character" and source.is_dir():
                destination = project / "characters" / key
                shutil.copytree(source, destination, dirs_exist_ok=True)
                outfit = str(item.get("outfit_key") or "")
                if outfit:
                    row = next((value for value in manifest["CharacterOverrides"] if str(value.get("Identifier") or "") == key), None)
                    if row is None:
                        row = {"Identifier": key, "Name": str(item.get("display_name") or key), "Nickname": str(item.get("nickname") or ""), "CharacterReference": None, "OriginalIdentifier": None}
                        manifest["CharacterOverrides"].append(row)
                    row["SpinePortraitPath"] = f"characters\\{key}\\{outfit}"
                    avatar = destination / f"{outfit}-avatar.png"
                    row["SmallPortraitPath"] = f"characters\\{key}\\{outfit}-avatar.png" if avatar.is_file() else None
        aa_registry.write_manifest_atomic(project, manifest)
        files = []
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file() and path.name not in {"files.json", "bundle.complete"}:
                files.append({"path": path.relative_to(bundle_dir).as_posix(), "size": path.stat().st_size, "sha256": self._modules["build_bundle"].calc_file_sha256(path)})
        (bundle_dir / "files.json").write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")

    def install(
        self,
        *,
        token: str,
        build_id: str,
        category: str,
        story_name: str | None,
    ) -> dict[str, Any]:
        if self.capabilities()["install"]["state"] != "available":
            raise ProductionError(
                "aa_workspace_not_configured",
                "安装前必须明确配置 AA 工作区",
                status=409,
            )
        manager = self._modules["install_manager"].InstallManager(
            store=self.store,
            aa_data_dir=str(self.settings.aa_data),
            record_path=str(self.settings.data_dir / "project_install_record.json"),
        )
        try:
            return manager.install_build(
                token,
                build_id,
                category=category,
                story_name=story_name,
            )
        except self._modules["install_manager"].AARunningError as exc:
            raise ProductionError("aa_running", str(exc), status=423) from exc
        except self._modules["install_manager"].AAInstallTargetExistsError as exc:
            raise ProductionError("install_target_exists", str(exc), status=409) from exc
        except self._modules["install_manager"].AACorruptBundleError as exc:
            raise ProductionError("corrupted_bundle", str(exc), status=400) from exc

    def install_options(self, *, token: str, build_id: str) -> dict[str, Any]:
        if self.capabilities()["install"]["state"] != "available":
            raise ProductionError(
                "aa_workspace_not_configured",
                "查看安装选项前必须配置 AA 工作区",
                status=409,
            )
        manager = self._modules["install_manager"].InstallManager(
            store=self.store,
            aa_data_dir=str(self.settings.aa_data),
            record_path=str(self.settings.data_dir / "project_install_record.json"),
        )
        try:
            result = manager.install_options(token=token, build_id=build_id)
        except self._modules["install_manager"].AACorruptBundleError as exc:
            raise ProductionError("corrupted_bundle", str(exc), status=400) from exc
        existing = result.get("existing_install")
        return {
            "ok": True,
            "source_project": result["source_project"],
            "default_category": result.get("default_category", ""),
            "default_story_name": result.get("default_story_name", result["source_project"]),
            "categories": result.get("categories", []),
            "existing_install": (
                {"project": str(existing.get("project") or "")}
                if isinstance(existing, dict)
                else None
            ),
        }

    def check_install_target(
        self,
        *,
        token: str,
        build_id: str,
        category: str,
        story_name: str | None,
    ) -> dict[str, Any]:
        options = self.install_options(token=token, build_id=build_id)
        install_manager = self._modules["install_manager"]
        try:
            project = install_manager.compose_install_project_name(
                category,
                options["source_project"] if story_name is None else story_name,
            )
        except ValueError as exc:
            raise ProductionError("invalid_install_name", str(exc)) from exc
        aa_data = Path(str(self.settings.aa_data))
        projects = aa_data / "projects"
        renamed = project != options["source_project"]
        occupied = renamed and any(
            target.exists()
            for target in (
                projects / f"{project}.aap",
                projects / project,
                aa_data / "saves" / project,
            )
        )
        return {
            "ok": True,
            "target": {
                "project": project,
                "source_project": options["source_project"],
                "category": str(category or "").strip(),
                "story_name": (
                    options["source_project"] if story_name is None else str(story_name).strip()
                ),
                "mode": "renamed_copy" if renamed else "update_source",
                "available": not occupied,
                "conflict": occupied,
            },
        }

    def execute_direction_generation(
        self,
        *,
        token: str,
        generation_id: str,
        provider: Any,
        expected_draft_version: int,
        story_type: str,
        layout_mode: str,
        resume: bool = False,
        progress: Any = None,
        model_activity: Any = None,
        cancelled: Any = None,
    ) -> dict[str, Any]:
        draft_dir = self.store.get_draft_path(token)
        detail = self.draft_detail(token)
        if int(detail.get("draft_version") or -1) != int(expected_draft_version):
            raise ProductionError(
                "revision_conflict",
                "AI 生成所基于的草稿版本已经变化",
                status=409,
            )
        source_cards = detail.get("cards") or []
        attempt_dir = draft_dir / "direction-generations" / generation_id
        if resume:
            attempt_dir.mkdir(parents=True, exist_ok=True)
        else:
            try:
                attempt_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError as exc:
                raise ProductionError(
                    "direction_generation_exists",
                    "该演出生成记录已经存在，只能通过继续任务复用它",
                    status=409,
                    details={"generation_id": generation_id},
                ) from exc
        cast_path = draft_dir / "cast.json"
        with self.store.draft_lock(token):
            cast_data = (
                json.loads(cast_path.read_text(encoding="utf-8"))
                if cast_path.is_file()
                else {}
            )
        cast_data["layout_mode"] = layout_mode
        staged_cast_path = attempt_dir / "cast.json"
        _write_json_atomic(staged_cast_path, cast_data)
        source = attempt_dir / "source.txt"
        output = attempt_dir / "annotated.txt"
        current_source = (draft_dir / "edited.txt").read_text(encoding="utf-8")
        performance_plan, performance_plan_ref = self._compatible_performance_plan(
            token, current_source,
        )
        if source.is_file():
            if source.read_text(encoding="utf-8") != current_source:
                raise ProductionError(
                    "revision_conflict",
                    "当前草稿与演出检查点的源文本不一致，不能继续旧任务",
                    status=409,
                    details={"generation_id": generation_id},
                )
        else:
            source.write_text(current_source, encoding="utf-8")
        resource_index = draft_dir / "resources.json"
        if not resource_index.is_file():
            raise ProductionError(
                "resource_index_not_configured",
                "AI 安排演出需要冻结的资源索引",
                status=409,
            )
        resources = self._draft_resources(token)
        missing = [
            name
            for name in ("bg", "sounds", "characters", "enums")
            if name not in resources
        ]
        if missing:
            raise ProductionError(
                "resource_index_incomplete",
                "冻结资源索引缺少 AI 演出所需数据",
                status=409,
                details={"missing": missing},
            )
        def audit_summary(
            result: dict[str, Any] | None,
            *,
            status: str,
            error: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            value = result if isinstance(result, dict) else {}
            agent = value.get("agent") if isinstance(value.get("agent"), dict) else {}
            return {
                "generation_id": generation_id,
                "status": status,
                "story_type": value.get("story_type") or story_type,
                "layout_mode": layout_mode,
                "agent": agent,
                "metrics": agent.get("metrics") if isinstance(agent.get("metrics"), dict) else {},
                "diagnostics": list(value.get("diagnostics") or []),
                "proposal_count": len(value.get("proposals") or []),
                "direction_change_count": int(value.get("direction_change_count") or 0),
                "cancelled": bool(value.get("cancelled")),
                "timed_out": bool(value.get("timed_out")),
                "incomplete": bool(value.get("incomplete")),
                "pending_targets": int(
                    value.get("pending_targets")
                    or agent.get("pending_targets")
                    or 0
                ),
                "provider": str(getattr(provider, "name", "")),
                "model": str(getattr(provider, "model", "")),
                "usage": dict(getattr(provider, "stats", {}) or {}),
                "error": error,
            }

        def persisted_request_records() -> tuple[list[dict[str, Any]], list[str]]:
            records: list[dict[str, Any]] = []
            paths: list[str] = []
            checkpoint_root = attempt_dir / "checkpoints"
            for path in sorted(checkpoint_root.rglob("requests.jsonl")) if checkpoint_root.is_dir() else []:
                try:
                    paths.append(str(path.relative_to(attempt_dir)))
                except ValueError:
                    paths.append(path.name)
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in lines[-100:]:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
            return records[-100:], paths

        try:
            result = self._modules["annotate"].annotate_script(
                {
                    "script": str(source),
                    "out": str(output),
                    "cast": str(staged_cast_path),
                    "index": str(resource_index),
                    "agent_enabled": True,
                    "checkpoint_dir": str(attempt_dir / "checkpoints"),
                    "story_type": story_type,
                    "layout_mode": layout_mode,
                    "usage_chain": performance_plan,
                    "progress": progress,
                    "model_activity": model_activity,
                    "cancelled": cancelled,
                },
                provider_instance=provider,
            )
        except Exception as exc:
            request_records, request_log_files = persisted_request_records()
            exception_details = getattr(exc, "details", None)
            error = {
                "code": str(getattr(exc, "code", "direction_generation_failed")),
                "message": str(exc),
                "type": type(exc).__name__,
                "details": {
                    **(exception_details if isinstance(exception_details, dict) else {}),
                    "request_log_files": request_log_files,
                },
            }
            failure_result = {
                "agent": {
                    "metrics": {
                        "requests": len(request_records),
                        "failed_request_count": sum(
                            1 for record in request_records
                            if record.get("outcome") == "failed"
                        ),
                        "request_records": request_records,
                    },
                },
            }
            _write_json_atomic(
                attempt_dir / "result.json",
                audit_summary(failure_result, status="failed", error=error),
            )
            if isinstance(exc, ProductionError):
                raise
            raise ProductionError(
                "direction_generation_failed",
                f"AI 安排演出失败：{exc}",
                status=502,
                details={
                    "generation_id": generation_id,
                    "type": type(exc).__name__,
                    "result_file": str(attempt_dir / "result.json"),
                    "request_log_files": request_log_files,
                },
            ) from exc

        incomplete = bool(
            result.get("incomplete")
            or result.get("cancelled")
            or result.get("timed_out")
            or int(result.get("pending_targets") or 0) > 0
            or not str(result.get("text") or "").strip()
        )
        if performance_plan_ref:
            agent = result.setdefault("agent", {})
            if isinstance(agent, dict):
                agent["performance_plan"] = performance_plan_ref
        if incomplete:
            result["incomplete"] = True
            summary = audit_summary(result, status="incomplete")
            _write_json_atomic(attempt_dir / "result.json", summary)
            return summary

        effective_proposals = [
            proposal
            for proposal in (result.get("proposals") or [])
            if isinstance(proposal, dict)
            and proposal.get("type") == "applied_pending"
            and proposal.get("before") != proposal.get("after")
            and proposal.get("after") not in (None, "", False, 0, [], {})
        ]
        direction_change_count = max(
            int(result.get("direction_change_count") or 0),
            len(effective_proposals),
        )
        result["direction_change_count"] = direction_change_count
        if direction_change_count == 0:
            summary = audit_summary(
                result,
                status="failed",
                error={
                    "code": "direction_generation_empty",
                    "message": "模型完成了请求，但没有生成任何有效演出修改",
                    "type": "ProductionError",
                    "details": {},
                },
            )
            _write_json_atomic(attempt_dir / "result.json", summary)
            raise ProductionError(
                "direction_generation_empty",
                "模型没有生成任何有效演出修改，草稿未被覆盖",
                status=422,
                details={
                    "generation_id": generation_id,
                    "agent": result.get("agent") or {},
                    "diagnostics": result.get("diagnostics") or [],
                },
            )
        output.write_text(str(result["text"]), encoding="utf-8")
        staged_summary = audit_summary(result, status="staged")
        _write_json_atomic(attempt_dir / "result.json", staged_summary)
        return StagedDirectionResult(
            token=token,
            generation_id=generation_id,
            expected_draft_version=expected_draft_version,
            layout_mode=layout_mode,
            source_cards=[dict(card) for card in source_cards if isinstance(card, dict)],
            result=dict(result),
            summary=staged_summary,
        )

    def discard_direction_generation(
        self,
        staged: StagedDirectionResult,
        *,
        status: str,
        cancelled: bool = False,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = dict(staged.summary)
        summary.update({"status": status, "cancelled": cancelled, "error": error})
        attempt_dir = (
            self.store.get_draft_path(staged.token)
            / "direction-generations"
            / staged.generation_id
        )
        _write_json_atomic(attempt_dir / "result.json", summary)
        return summary

    def commit_direction_generation(
        self,
        staged: StagedDirectionResult,
    ) -> dict[str, Any]:
        result = staged.result
        draft_dir = self.store.get_draft_path(staged.token)
        attempt_dir = draft_dir / "direction-generations" / staged.generation_id
        proposals_path = attempt_dir / "proposals.json"
        tracked_paths = [
            draft_dir / name
            for name in (
                "edited.txt",
                "identity.json",
                "diagnostics.json",
                "session.json",
                "cast.json",
            )
        ] + [proposals_path]

        def restore(snapshot: dict[Path, bytes | None]) -> None:
            for path, content in snapshot.items():
                if content is None:
                    path.unlink(missing_ok=True)
                    continue
                temporary = path.with_suffix(path.suffix + ".rollback.tmp")
                temporary.write_bytes(content)
                os.replace(temporary, path)

        try:
            with self.store.draft_lock(staged.token):
                snapshot = {
                    path: path.read_bytes() if path.is_file() else None
                    for path in tracked_paths
                }
                try:
                    updated = self.store.update_draft_content(
                        token=staged.token,
                        new_text=result["text"],
                        expected_draft_version=staged.expected_draft_version,
                        is_content_change=True,
                    )
                    cast_path = draft_dir / "cast.json"
                    cast_data = (
                        json.loads(cast_path.read_text(encoding="utf-8"))
                        if cast_path.is_file()
                        else {}
                    )
                    cast_data["layout_mode"] = staged.layout_mode
                    _write_json_atomic(cast_path, cast_data)
                    anchored_proposals = self._anchor_direction_proposals(
                        token=staged.token,
                        proposals=result.get("proposals") or [],
                        source_cards=staged.source_cards,
                        content_revision=int(
                            (updated.get("session") or {}).get("content_revision") or 0
                        ),
                    )
                    _write_json_atomic(proposals_path, anchored_proposals)
                    summary = {**staged.summary, "status": "succeeded"}
                    summary.update({
                        "proposal_count": len(anchored_proposals),
                        "diagnostic_count": len(result.get("diagnostics") or []),
                        "draft_version": (updated.get("session") or {}).get("draft_version"),
                    })
                    _write_json_atomic(attempt_dir / "result.json", summary)
                except Exception:
                    restore(snapshot)
                    raise
        except self._modules["draft_store"].RevisionConflictError as exc:
            _write_json_atomic(
                attempt_dir / "result.json",
                {
                    **staged.summary,
                    "status": "superseded",
                    "error": {
                        "code": "revision_conflict",
                        "message": "AI 生成期间草稿已被修改，结果未写回",
                        "type": type(exc).__name__,
                        "details": {"generation_id": staged.generation_id},
                    },
                },
            )
            raise ProductionError(
                "revision_conflict",
                "AI 生成期间草稿已被修改，结果已保留但未覆盖当前草稿",
                status=409,
                details={"generation_id": staged.generation_id},
            ) from exc
        except Exception as exc:
            try:
                _write_json_atomic(
                    attempt_dir / "result.json",
                    {
                        **staged.summary,
                        "status": "failed",
                        "error": {
                            "code": "direction_commit_failed",
                            "message": str(exc),
                            "type": type(exc).__name__,
                            "details": {"generation_id": staged.generation_id},
                        },
                    },
                )
            except OSError:
                pass
            raise
        return summary
