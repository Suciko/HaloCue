from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import ProductionError
from .direction_models import DirectionModelGateway
from .jobs import JobRegistry
from .legacy_adapter import Legacy093Adapter
from .models import ProductionRun, ScriptRelease, WorkItem, content_sha256, new_id, utc_now
from .model_settings import DirectionModelSettings
from .repository import ProductionRepository
from .resource_catalog import ResourceCatalog
from .name_baseline import CharacterNameBaseline
from .resource_previews import ResourcePreview
from .settings_store import SettingsStore
from .asset_staging import AssetStaging
from .asset_recognition import recognize as recognize_asset_content
from .custom_asset_library import CustomAssetLibrary


INVALID_PROJECT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
BUILD_ID = re.compile(r"build-[0-9a-f]{12}")
UPSTREAM_RELEASE_ID = re.compile(r"release-[0-9a-f]{12}")
WORK_ID = re.compile(r"work-[0-9a-f]{12}")
SHA256 = re.compile(r"[0-9a-f]{64}")
LAYOUT_MODES = frozenset({"pure_ai", "ai", "rules"})
DIRECTIVE_COMMANDS = frozenset({
    "bg", "trans", "bgfx", "popup", "bgm", "music", "se", "sound", "place", "wait",
    "enter", "exit", "move", "stage", "auto", "camera", "camera_hold", "fx", "hl",
    "bgshake", "clearst", "hidemenu", "showmenu", "shot", "aronatouch", "st", "stm", "zoom", "raw",
})
RESOURCE_DIRECTIVES = frozenset({"bg", "se", "sound"})
NO_ARGUMENT_DIRECTIVES = frozenset({"auto", "bgshake", "clearst", "hidemenu", "showmenu", "aronatouch"})


class ProductionService:
    def __init__(self, settings: Settings) -> None:
        settings.prepare()
        self.settings = settings
        self.repository = ProductionRepository(settings.data_dir)
        self.settings_store = SettingsStore(settings.data_dir)
        persisted = self.settings_store.load()
        if settings.aa_data is None and persisted.get("aa_data"):
            try:
                configured_aa = self.settings_store.validate_aa_workspace(
                    persisted["aa_data"]
                )
            except ProductionError:
                configured_aa = None
            if configured_aa:
                self.settings = replace(settings, aa_data=configured_aa)
        self.adapter = Legacy093Adapter(self.settings)
        self.name_baseline = CharacterNameBaseline(self.settings.name_baseline)
        self.resources = ResourceCatalog(
            self.settings.resource_index,
            self.settings.aa_data,
            self.settings.legacy_root,
            self.name_baseline,
        )
        self.direction_model_settings = DirectionModelSettings(settings.data_dir)
        self.direction_models = DirectionModelGateway(
            self.direction_model_settings, settings.legacy_root
        )
        self.jobs = JobRegistry(settings.data_dir / "jobs")
        self.asset_staging = AssetStaging(settings.data_dir / "uploads")
        self.custom_assets = CustomAssetLibrary(settings.data_dir / "custom-asset-library")
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        for run in self.repository.list_runs():
            recovery_state = {
                "compiling": "compile_interrupted",
                "generating_direction": "direction_interrupted",
            }.get(run.state)
            if not recovery_state:
                continue
            run.state = recovery_state
            run.pending_build_id = None
            run.updated_at = utc_now()
            self.repository.save_run(run)

    @staticmethod
    def _project_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ProductionError("project_required", "AA 工程名称不能为空")
        if len(name) > 80 or INVALID_PROJECT.search(name) or name.endswith((".", " ")):
            raise ProductionError("invalid_project_name", "AA 工程名称包含 Windows 不允许的字符")
        return name

    @staticmethod
    def _layout_mode(value: Any) -> str:
        mode = str(value or "ai").strip().lower()
        if mode not in LAYOUT_MODES:
            raise ProductionError(
                "invalid_layout_mode",
                "站位模式无效",
                details={"allowed": sorted(LAYOUT_MODES)},
            )
        return mode

    @staticmethod
    def _source_text(payload: dict[str, Any]) -> tuple[str, str, str | None]:
        source = payload.get("source")
        if not isinstance(source, dict) or source.get("kind") not in {"inline", "file_upload"}:
            raise ProductionError(
                "unsupported_source",
                "当前版本只接受直接输入或本地文本文件",
                details={"supported": ["inline", "file_upload"]},
            )
        text = source.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ProductionError("source_empty", "剧本文本不能为空")
        if len(text.encode("utf-8")) > 5 * 1024 * 1024:
            raise ProductionError("source_too_large", "剧本文本不能超过 5 MiB", status=413)
        kind = str(source.get("kind"))
        filename: str | None = None
        if kind == "file_upload":
            filename = Path(str(source.get("filename") or "")).name.strip()
            if not filename or Path(filename).suffix.casefold() not in {".txt", ".md", ".markdown"}:
                raise ProductionError(
                    "source_file_type_unsupported",
                    "剧本文件必须是 TXT、MD 或 Markdown",
                    details={"allowed": [".txt", ".md", ".markdown"]},
                )
        return text.replace("\x00", ""), kind, filename

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": "halocue-production",
            "version": "1.0.0a1",
            "api_version": "v1",
            "capabilities": self.capabilities(),
        }

    def capabilities(self) -> dict[str, Any]:
        capabilities = self.adapter.capabilities()
        model = self.direction_model_settings.public()["model"]
        capabilities["ai_preflight"] = {
            "state": "available" if model["configured"] else "not_configured",
            "reason": None if model["configured"] else "model_provider_not_configured",
        }
        if model["configured"]:
            capabilities["generation_modes"]["ai_direction"] = {
                "state": "available",
                "provider": model.get("provider"),
                "model": model.get("model"),
            }
        capabilities["custom_assets"] = {
            "state": "available",
            "schema_version": "custom-asset-library/1.0",
            "flow": [
                "upload",
                "validate",
                "optional_ai_proposal",
                "confirm_library",
                "edit_metadata",
                "attach_to_task",
            ],
            "kinds": ["background", "sound", "character", "cg"],
            "recognition": {
                "state": "available" if model["configured"] else "not_configured",
                "supported_kinds": ["background", "character", "cg"],
                "unsupported_kinds": ["sound"],
                "requires_confirmation": True,
                "spine_animation_rendered": False,
            },
        }
        capabilities["script_release_handoff"] = {
            "state": "available",
            "schema_version": "1.0",
            "identity_fields": ["id", "display_version", "content_hash"],
            "content_hash": "sha256",
            "idempotent": True,
        }
        return capabilities

    @staticmethod
    def _upstream_script_release(
        payload: dict[str, Any], text: str
    ) -> dict[str, Any] | None:
        value = payload.get("script_release")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ProductionError(
                "invalid_script_release", "script_release 必须是对象"
            )
        release_id = str(value.get("id") or "").strip()
        display_version = str(value.get("display_version") or "").strip()
        declared_hash = str(value.get("content_hash") or "").strip().casefold()
        if not UPSTREAM_RELEASE_ID.fullmatch(release_id):
            raise ProductionError(
                "invalid_script_release", "写作发布版本 ID 无效"
            )
        if not display_version or len(display_version) > 40:
            raise ProductionError(
                "invalid_script_release", "写作发布版本号无效"
            )
        if not SHA256.fullmatch(declared_hash):
            raise ProductionError(
                "invalid_script_release", "写作发布版本内容哈希无效"
            )
        actual_hash = content_sha256(text)
        if declared_hash != actual_hash:
            raise ProductionError(
                "script_release_hash_mismatch",
                "写作发布版本的正文与内容哈希不一致，已拒绝交接",
                status=409,
                details={"release_id": release_id},
            )

        origin = {
            "kind": "halocue_writing",
            "schema_version": str(value.get("schema_version") or "1.0"),
            "release_id": release_id,
            "display_version": display_version,
            "content_hash": declared_hash,
        }
        work_id = str(value.get("work_id") or "").strip()
        if work_id:
            if not WORK_ID.fullmatch(work_id):
                raise ProductionError(
                    "invalid_script_release", "写作作品 ID 无效"
                )
            origin["work_id"] = work_id
        writing_pack_version = str(value.get("writing_pack_version") or "").strip()
        if writing_pack_version:
            if len(writing_pack_version) > 120:
                raise ProductionError(
                    "invalid_script_release", "WritingPack 版本号过长"
                )
            origin["writing_pack_version"] = writing_pack_version
        return origin

    def direction_model_settings_public(self) -> dict[str, Any]:
        return self.direction_model_settings.public()

    def request_cg_advice(self, run_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not self.direction_model_settings.public()["model"]["configured"]:
            raise ProductionError(
                "cg_advice_not_configured", "获取 AI 制作意见前，请先配置演出模型", status=409
            )
        run = self._run(run_id)
        expected = self._expected_version(payload)
        detail = self.adapter.draft_detail(str(run.draft_token))
        if detail["draft_version"] != expected:
            raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
        start_card_id = str(payload.get("start_card_id") or "").strip()
        end_card_id = str(payload.get("end_card_id") or "").strip()
        provider = self.direction_models.provider()

        def work() -> dict[str, Any]:
            return self.adapter.execute_cg_advice(
                token=str(run.draft_token), provider=provider,
                start_card_id=start_card_id, end_card_id=end_card_id,
            )

        job = self.jobs.submit(
            "cg_advice",
            work,
            run_id=run_id,
            retry_context={
                "expected_draft_version": expected,
                "start_card_id": start_card_id,
                "end_card_id": end_card_id,
            },
        )
        return 202, {"ok": True, "job": self._job_public(job.to_dict())}

    def configure_direction_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.direction_model_settings.save(payload)

    def fetch_direction_models(self, payload: dict[str, Any] | None = None) -> list[str]:
        return self.direction_model_settings.fetch_models(payload)

    def test_direction_model(self) -> tuple[int, dict[str, Any]]:
        job = self.jobs.submit(
            "model_connection_test", self.direction_models.test_connection, retry_context={}
        )
        return 202, {"ok": True, "job": self._job_public(job.to_dict())}

    def generate_direction(
        self, run_id: str, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        run = self._run(run_id)
        if run.source_summary.get("generation_mode") != "ai_direction":
            raise ProductionError(
                "direction_mode_not_selected",
                "该制作任务不是 AI 安排演出模式",
                status=409,
            )
        expected = self._expected_version(payload)
        detail = self.adapter.draft_detail(str(run.draft_token))
        if detail["draft_version"] != expected:
            raise ProductionError("revision_conflict", "草稿版本已经变化", status=409)
        actor_errors = [
            issue
            for issue in detail["diagnostics"]
            if str(issue.get("code") or "").startswith("actor.")
            and issue.get("severity") == "error"
        ]
        if actor_errors:
            raise ProductionError(
                "cast_mapping_required",
                "AI 安排演出前必须完成角色映射",
                status=409,
                details={"count": len(actor_errors)},
            )
        story_type = str(payload.get("story_type") or "auto").strip()
        if story_type not in {"auto", "main", "event", "bond"}:
            raise ProductionError("invalid_story_type", "剧情类型无效")
        layout_mode = self._layout_mode(payload.get("layout_mode"))
        generation_id = new_id("direction")
        provider = self.direction_models.provider()
        run.state = "generating_direction"
        run.current_stage = "generation"
        run.source_summary["layout_mode"] = layout_mode
        run.updated_at = utc_now()
        self.repository.save_run(run)

        def work() -> dict[str, Any]:
            try:
                result = self.adapter.execute_direction_generation(
                    token=str(run.draft_token),
                    generation_id=generation_id,
                    provider=provider,
                    expected_draft_version=expected,
                    story_type=story_type,
                    layout_mode=layout_mode,
                )
            except Exception:
                latest = self._run(run_id)
                latest.state = "direction_failed"
                latest.updated_at = utc_now()
                self.repository.save_run(latest)
                raise
            latest = self._run(run_id)
            latest.state = "waiting_for_review"
            latest.current_stage = "review_install"
            latest.updated_at = utc_now()
            self.repository.save_run(latest)
            return {"run_id": run_id, **result}

        job = self.jobs.submit(
            "direction_generation",
            work,
            run_id=run_id,
            retry_context={
                "expected_draft_version": expected,
                "story_type": story_type,
                "layout_mode": layout_mode,
            },
        )
        return 202, {
            "ok": True,
            "job": self._job_public(job.to_dict()),
            "generation_id": generation_id,
            "layout_mode": layout_mode,
        }

    def aa_workspace_settings(self) -> dict[str, Any]:
        path = self.settings.aa_data
        valid = bool(
            path
            and path.is_dir()
            and all(
                (path / name).is_dir()
                for name in ("projects", "saves", "overrides", "settings")
            )
        )
        return {
            "ok": True,
            "aa_workspace": {
                "configured": bool(path),
                "path": str(path) if path else None,
                "valid": valid,
            },
            "capabilities": self.capabilities(),
        }

    def inspect_aa_environment(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        selection = str(payload.get("selection") or "").strip() or None
        environment = self.adapter.discover_aa_environment(selection)
        adopted = False
        if payload.get("adopt") is True:
            workspace = environment.get("workspace") or {}
            if not workspace.get("path"):
                raise ProductionError(
                    "aa_workspace_not_discovered",
                    "没有检测到可采用的 AA 工作区",
                    status=409,
                    details={"issues": environment.get("issues", [])},
                )
            self.configure_aa_workspace({"path": workspace["path"]})
            adopted = True
            environment = self.adapter.discover_aa_environment(str(workspace["path"]))
        return {
            "ok": True,
            "environment": environment,
            "adopted": adopted,
            "aa_workspace": self.aa_workspace_settings()["aa_workspace"],
            "capabilities": self.capabilities(),
        }

    def configure_aa_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.settings_store.validate_aa_workspace(payload.get("path"))
        current = self.settings_store.load()
        current["aa_data"] = str(path)
        self.settings_store.save(current)
        self.settings = replace(self.settings, aa_data=path)
        self.adapter.settings = self.settings
        self.resources = ResourceCatalog(
            self.settings.resource_index,
            self.settings.aa_data,
            self.settings.legacy_root,
            self.name_baseline,
        )
        return self.aa_workspace_settings()

    def list_resources(
        self, kind: str, *, query: str = "", offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        return self.resources.list(kind, query=query, offset=offset, limit=limit)

    def character_resource(self, identifier: str) -> dict[str, Any]:
        return self.resources.character_detail(identifier)

    def resource_preview(self, kind: str, key: str) -> ResourcePreview:
        preview = self.resources.preview(kind, key)
        if preview is None:
            raise ProductionError("resource_preview_not_found", "该资源没有可用的本地预览", status=404)
        return preview

    def list_run_resources(
        self, run_id: str, kind: str, *, query: str = "", offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        run = self._run(run_id)
        return self.adapter.list_draft_resources(
            str(run.draft_token), kind, query=query, offset=offset, limit=limit
        )

    def run_character_resource(self, run_id: str, identifier: str) -> dict[str, Any]:
        run = self._run(run_id)
        return self.adapter.draft_character_detail(str(run.draft_token), identifier)

    def upload_asset(self, *, filename: str, content: bytes) -> dict[str, Any]:
        return self.asset_staging.upload(filename=filename, content=content)

    @staticmethod
    def _asset_kind(value: Any) -> str:
        kind = str(value or "").strip().casefold()
        if kind not in {"background", "sound", "character", "cg"}:
            raise ProductionError(
                "invalid_asset_kind", "素材类型必须是背景、音效或角色骨骼",
                details={"allowed": ["background", "sound", "character", "cg"]},
            )
        return kind

    def _validate_staged_asset(self, payload: dict[str, Any]) -> tuple[str, str, Path, dict[str, Any]]:
        kind = self._asset_kind(payload.get("kind"))
        token = str(payload.get("upload_token") or "").strip()
        source = self.asset_staging.source_for(token, kind)
        validation = self.adapter.validate_task_asset(
            source=source,
            kind=kind,
            identifier=str(payload.get("identifier") or "").strip(),
        )
        return kind, token, source, validation

    def list_custom_assets(
        self, *, kind: str = "", query: str = "", offset: int = 0, limit: int = 80
    ) -> dict[str, Any]:
        normalized_kind = self._asset_kind(kind) if kind else ""
        return self.custom_assets.list(
            kind=normalized_kind, query=query, offset=offset, limit=limit
        )

    def custom_asset_detail(self, asset_id: str) -> dict[str, Any]:
        return {"ok": True, "asset": self.custom_assets.detail(asset_id)}

    def update_custom_asset(self, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            expected_metadata_version = int(payload.get("expected_metadata_version"))
        except (TypeError, ValueError) as exc:
            raise ProductionError(
                "custom_asset_metadata_version_required",
                "更新素材信息时必须提供当前版本",
            ) from exc
        asset = self.custom_assets.update_metadata(
            asset_id,
            expected_metadata_version=expected_metadata_version,
            name=str(payload.get("name") or ""),
            nickname=str(payload.get("nickname") or ""),
            tags=payload.get("tags"),
            labels=payload.get("labels"),
        )
        return {"ok": True, "asset": asset}

    def validate_custom_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        _, token, _, validation = self._validate_staged_asset(payload)
        return {"ok": True, "upload_token": token, "validation": validation}

    def recognize_custom_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind, token, source, validation = self._validate_staged_asset(payload)
        if not validation.get("ok"):
            raise ProductionError(
                "asset_validation_failed",
                "素材没有通过确定性检查，不能提交 AI 识别",
                status=422,
                details={"issues": validation.get("issues", [])},
            )
        if kind == "sound":
            raise ProductionError(
                "asset_recognition_media_unsupported",
                "当前 Provider 协议尚不支持音频内容识别；音效仍可按技术参数登记",
                status=409,
            )
        model_state = self.direction_model_settings.public().get("model") or {}
        digest = self.custom_assets.recognition_digest({
            "kind": kind,
            "sha256": validation.get("sha256"),
            "identifier": str(payload.get("identifier") or "").strip(),
            "provider": model_state.get("provider"),
            "model": model_state.get("model"),
        })
        cached = self.asset_staging.recognition_for(token, digest)
        if cached:
            return {"ok": True, "upload_token": token, "recognition": cached, "idempotent": True}
        try:
            provider = self.direction_models.provider()
        except ProductionError as exc:
            if exc.code == "direction_generation_not_configured":
                raise ProductionError(
                    "asset_recognition_not_configured",
                    "尚未配置可查看图片的制作模型；可以跳过 AI 识别并手工登记",
                    status=409,
                ) from exc
            raise
        proposal = recognize_asset_content(
            provider,
            source=source,
            kind=kind,
            metadata=validation.get("metadata") or {},
            filename=self.asset_staging.filename_for(token),
        )
        proposal["digest"] = digest
        self.asset_staging.save_recognition(token, proposal)
        return {"ok": True, "upload_token": token, "recognition": proposal, "idempotent": False}

    def register_custom_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind, token, source, validation = self._validate_staged_asset(payload)
        if not validation.get("ok"):
            raise ProductionError(
                "asset_validation_failed", "素材没有通过检查，尚未登记",
                status=422, details={"issues": validation.get("issues", [])},
            )
        labels = payload.get("labels") or {}
        if not isinstance(labels, dict):
            raise ProductionError("invalid_asset_labels", "素材标签必须是对象")
        recognition = None
        recognition_accepted = payload.get("accept_recognition") is True
        recognition_digest = str(payload.get("recognition_digest") or "").strip()
        if recognition_digest:
            recognition = self.asset_staging.recognition_for(token, recognition_digest)
            if recognition is None:
                raise ProductionError(
                    "asset_recognition_stale",
                    "AI 识别建议已经变化，请重新检查后再采用",
                    status=409,
                )
        if recognition_accepted and recognition is None:
            raise ProductionError(
                "asset_recognition_stale",
                "AI 识别建议已经变化，请重新检查后再采用",
                status=409,
            )
        asset, idempotent = self.custom_assets.register(
            source=source,
            kind=kind,
            validation=validation,
            filename=self.asset_staging.filename_for(token),
            identifier=str(payload.get("identifier") or "").strip(),
            display_name=str(payload.get("display_name") or "").strip(),
            nickname=str(payload.get("nickname") or "").strip(),
            labels=labels,
            recognition=recognition,
            recognition_accepted=recognition_accepted,
        )
        return {"ok": True, "asset": asset, "idempotent": idempotent}

    def custom_asset_preview(self, asset_id: str) -> ResourcePreview:
        path = self.custom_assets.preview(asset_id)
        if path is None:
            raise ProductionError(
                "custom_asset_preview_not_found", "该素材没有可用的图片预览", status=404
            )
        return ResourcePreview(
            path=path,
            media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )

    def attach_custom_asset(self, run_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        asset = self.custom_assets.detail(asset_id)
        source = self.custom_assets.source_for(asset_id)
        result = self.adapter.register_task_asset(
            token=str(run.draft_token),
            source=source,
            kind=str(asset.get("kind") or ""),
            identifier=str(asset.get("key") or ""),
            display_name=str(asset.get("name") or ""),
            nickname=str(asset.get("nickname") or ""),
            labels=asset.get("labels") if isinstance(asset.get("labels"), dict) else {},
            expected_draft_version=self._expected_version(payload),
            library_asset_id=asset_id,
        )
        if result.get("status") == "rejected":
            raise ProductionError(
                "asset_validation_failed", "素材没有通过检查，尚未加入制作任务",
                status=422, details={"issues": result.get("issues", [])},
            )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        detail = self.run_detail(run_id)
        return {
            **result,
            "library_asset_id": asset_id,
            "run": detail["run"],
            "draft": detail["draft"],
            "gates": detail["gates"],
        }

    def validate_task_asset(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._run(run_id)
        kind = self._asset_kind(payload.get("kind"))
        token = str(payload.get("upload_token") or "").strip()
        source = self.asset_staging.source_for(token, kind)
        result = self.adapter.validate_task_asset(
            source=source, kind=kind, identifier=str(payload.get("identifier") or "").strip()
        )
        return {"ok": True, "upload_token": token, "validation": result}

    def register_task_asset(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        kind = self._asset_kind(payload.get("kind"))
        token = str(payload.get("upload_token") or "").strip()
        source = self.asset_staging.source_for(token, kind)
        labels = payload.get("labels") or {}
        if not isinstance(labels, dict):
            raise ProductionError("invalid_asset_labels", "素材标签必须是对象")
        result = self.adapter.register_task_asset(
            token=str(run.draft_token),
            source=source,
            kind=kind,
            identifier=str(payload.get("identifier") or "").strip(),
            display_name=str(payload.get("display_name") or "").strip(),
            nickname=str(payload.get("nickname") or "").strip(),
            labels=labels,
            expected_draft_version=self._expected_version(payload),
        )
        if result.get("status") == "rejected":
            raise ProductionError(
                "asset_validation_failed", "素材没有通过检查，尚未登记",
                status=422, details={"issues": result.get("issues", [])},
            )
        if result.get("status") == "registered":
            run.state = "waiting_for_review"
            run.updated_at = utc_now()
            self.repository.save_run(run)
            result["run"] = self.run_detail(run_id)["run"]
            result["draft"] = self.run_detail(run_id)["draft"]
            result["gates"] = self.run_detail(run_id)["gates"]
        return result

    def task_assets(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        return {"ok": True, "run_id": run_id, "items": self.adapter.list_task_assets(str(run.draft_token))}

    def remove_task_asset(self, run_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        self.adapter.remove_task_asset(
            token=str(run.draft_token), asset_id=asset_id,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def run_resource_preview(self, run_id: str, kind: str, key: str) -> ResourcePreview:
        run = self._run(run_id)
        custom = self.adapter.task_asset_preview(str(run.draft_token), kind, key)
        if custom:
            return ResourcePreview(path=custom[0], media_type=custom[1])
        return self.resource_preview(kind, key)

    def resource_usage(self, run_id: str) -> dict[str, Any]:
        """Return safe, task-local usage locations for registered resources."""
        run = self._run(run_id)
        detail = self.adapter.draft_detail(str(run.draft_token))
        usage: dict[str, list[dict[str, Any]]] = {}

        def add(kind: str, key: str, card: dict[str, Any], label: str) -> None:
            normalized = str(key or "").strip()
            if not normalized:
                return
            usage.setdefault(f"{kind}:{normalized}", []).append(
                {"card_id": card.get("card_id"), "line_no": card.get("line_no"), "label": label}
            )

        for card in detail.get("cards", []):
            if not isinstance(card, dict):
                continue
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            cmd = str(current.get("cmd") or "").casefold()
            if cmd == "bg":
                add("backgrounds", str(current.get("arg") or ""), card, "背景")
            elif cmd in {"se", "sound"}:
                add("sounds", str(current.get("arg") or ""), card, "音效")
            cg = card.get("cg") if isinstance(card.get("cg"), dict) else None
            if cg:
                add("backgrounds", str(cg.get("background_key") or ""), card, str(cg.get("label") or "CG 背景"))

        cast = detail.get("cast") if isinstance(detail.get("cast"), dict) else {}
        cast_map = cast.get("cast") if isinstance(cast.get("cast"), dict) else {}
        for speaker, mapping in cast_map.items():
            if isinstance(mapping, dict) and mapping.get("kind") == "portrait":
                add("characters", str(mapping.get("id") or ""), {"card_id": None, "line_no": None}, f"角色映射：{speaker}")
        return {"ok": True, "run_id": run_id, "usage": usage}

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        generation_mode = str(payload.get("generation_mode") or "format_only").strip()
        if generation_mode not in {"format_only", "ai_direction"}:
            raise ProductionError(
                "invalid_generation_mode",
                "不支持的草稿生成模式",
                details={"allowed": ["format_only", "ai_direction"]},
            )
        if generation_mode == "ai_direction":
            if not self.direction_model_settings.public()["model"]["configured"]:
                raise ProductionError(
                    "direction_generation_not_configured",
                    "AI 安排演出需要先配置 1.0 模型 Provider",
                    status=409,
                )
        project = self._project_name(payload.get("project"))
        text, source_kind, source_filename = self._source_text(payload)
        upstream_release = self._upstream_script_release(payload, text)
        if upstream_release:
            existing = self._run_for_upstream_release(upstream_release)
            if existing:
                result = self.run_detail(existing.run_id)
                result["handoff"] = {
                    "kind": "script_release",
                    "idempotent": True,
                    "upstream_release": upstream_release,
                }
                return result
        release = ScriptRelease.create(project, text, source_kind)
        self.repository.save_release(release, text)

        summary = self.adapter.inspect_script(text)
        summary["source_kind"] = source_kind
        if source_filename:
            summary["source_filename"] = source_filename
        if upstream_release:
            summary["upstream_release"] = upstream_release
        draft = self.adapter.create_performance_draft(
            project=project,
            text=text,
            speakers=summary["speakers"],
            cg_keys=self.resources.cg_keys(),
        )
        now = utc_now()
        run = ProductionRun(
            run_id=new_id("run"),
            project=project,
            release_id=release.release_id,
            draft_token=draft["session"]["draft_token"],
            state="waiting_for_review",
            current_stage="preflight",
            created_at=now,
            updated_at=now,
            source_summary=summary,
            work_items=[
                WorkItem("workspace", "建立剧情工作区", "succeeded", 100, "剧本发布版本已冻结"),
                WorkItem("structure", "识别格式与场景结构", "succeeded", 100, f'{summary["scene_count"]} 个场景'),
                WorkItem("clues", "提取角色、指令与素材线索", "succeeded", 100, f'{len(summary["speakers"])} 个说话角色'),
                WorkItem("preflight", "建立初审与演出草稿", "succeeded", 100, "等待角色映射与逐卡审查"),
            ],
        )
        run.source_summary["generation_mode"] = generation_mode
        self.repository.save_run(run)
        result = self.run_detail(run.run_id)
        if upstream_release:
            result["handoff"] = {
                "kind": "script_release",
                "idempotent": False,
                "upstream_release": upstream_release,
            }
        return result

    def _run_for_upstream_release(
        self, upstream_release: dict[str, Any]
    ) -> ProductionRun | None:
        release_id = upstream_release["release_id"]
        content_hash = upstream_release["content_hash"]
        for run in self.repository.list_runs():
            origin = run.source_summary.get("upstream_release")
            if not isinstance(origin, dict) or origin.get("release_id") != release_id:
                continue
            if origin.get("content_hash") != content_hash:
                raise ProductionError(
                    "script_release_identity_conflict",
                    "同一写作发布版本 ID 已绑定到不同正文，已拒绝交接",
                    status=409,
                    details={"release_id": release_id, "run_id": run.run_id},
                )
            return run
        return None

    def preflight_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Inspect source text without creating a release, draft, or background job."""
        text, _, _ = self._source_text(payload)
        return self.adapter.preflight_script(
            text,
            commands=set(DIRECTIVE_COMMANDS),
            no_argument_commands=set(NO_ARGUMENT_DIRECTIVES),
        )

    def start_ai_preflight(self, run_id: str) -> tuple[int, dict[str, Any]]:
        """Submit a source-only AI review without changing any production state."""
        run = self._run(run_id)
        if not self.direction_model_settings.public()["model"]["configured"]:
            raise ProductionError(
                "ai_preflight_not_configured",
                "运行 AI 初审前需要先在设置中配置演出模型",
                status=409,
            )
        preflight_id = new_id("preflight")
        provider = self.direction_models.provider()

        def work() -> dict[str, Any]:
            result = self.adapter.execute_ai_preflight(
                token=str(run.draft_token), preflight_id=preflight_id, provider=provider
            )
            return {
                "run_id": run_id,
                "preflight_id": preflight_id,
                "scene_count": len(result["analysis"]["scenes"]),
                "ambiguity_count": len(result["analysis"]["ambiguities"]),
            }

        job = self.jobs.submit("ai_preflight", work, run_id=run_id, retry_context={})
        return 202, {"ok": True, "job": self._job_public(job.to_dict()), "preflight_id": preflight_id}

    def ai_preflights(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        result = self.adapter.ai_preflights(str(run.draft_token))
        return {"run_id": run_id, **result}

    def list_runs(self) -> dict[str, Any]:
        return {"ok": True, "items": [item.to_dict() for item in self.repository.list_runs()]}

    def _run(self, run_id: str) -> ProductionRun:
        return self.repository.get_run(run_id)

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        draft = self.adapter.draft_detail(str(run.draft_token)) if run.draft_token else None
        gates = self._gates(run, draft)
        return {"ok": True, "run": run.to_dict(), "gates": gates, "draft": draft}

    def performance_preview(self, run_id: str) -> dict[str, Any]:
        """Build a read-only, task-local representation for the draft preview.

        This deliberately describes the current PerformanceDraft rather than a
        finished AA render. The client receives stable card IDs and safe resource
        keys only, then requests allowlisted previews through the existing routes.
        """
        run = self._run(run_id)
        detail = self.adapter.draft_detail(str(run.draft_token))
        cast_data = detail.get("cast") if isinstance(detail.get("cast"), dict) else {}
        cast = cast_data.get("cast") if isinstance(cast_data.get("cast"), dict) else {}
        background = str(cast_data.get("default_bg") or "BG_Black")
        frames: list[dict[str, Any]] = []
        for index, card in enumerate(detail.get("cards") or []):
            if not isinstance(card, dict):
                continue
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            kind = str(card.get("kind") or "")
            command = str(current.get("cmd") or "").casefold() if kind == "dir" else ""
            if command == "bg" and str(current.get("arg") or "").strip():
                background = str(current["arg"]).strip()
            speaker = str(current.get("who") or "").strip()
            mapping = cast.get(speaker) if isinstance(cast.get(speaker), dict) else {"kind": "unset"}
            cg = card.get("cg") if isinstance(card.get("cg"), dict) else None
            annotations = [
                {"kind": label, "value": str(current.get(key) or "").strip()}
                for key, label in (("face", "表情"), ("emo", "情绪"), ("act", "动作"), ("fx", "画面效果"))
                if str(current.get(key) or "").strip()
            ]
            if cg:
                background = str(cg.get("background_key") or background)
                presentation = "cg"
                title = str(cg.get("label") or "CG 段落")
                text = str(current.get("text") or "") if kind == "line" else ""
            elif kind == "line":
                presentation = "dialogue"
                title = speaker if mapping.get("kind") != "narrator" else "旁白"
                text = str(current.get("text") or "")
            elif kind == "scene":
                presentation = "scene"
                title = "场景切换"
                text = str(current.get("title") or "")
            elif kind == "background_request":
                presentation = "request"
                title = "待处理背景"
                text = str(current.get("description") or card.get("raw") or "")
            elif kind == "dir":
                presentation = "direction"
                title = f"@{command or '指令'}"
                text = str(current.get("arg") or card.get("raw") or "")
            else:
                presentation = "note"
                title = kind or "文本"
                text = str(current.get("text") or current.get("title") or card.get("raw") or "")
            frames.append(
                {
                    "index": index,
                    "card_id": str(card.get("card_id") or ""),
                    "line_no": card.get("line_no"),
                    "card_kind": kind,
                    "presentation": presentation,
                    "background_key": background,
                    "cg": (
                        {"background_key": str(cg.get("background_key") or ""), "label": str(cg.get("label") or "CG 段落")}
                        if cg else None
                    ),
                    "speaker": {
                        "name": speaker,
                        "mapping_kind": str(mapping.get("kind") or "unset"),
                        "character_id": str(mapping.get("id") or ""),
                    },
                    "title": title,
                    "text": text,
                    "annotations": annotations,
                    "review_state": str(card.get("review_state") or "pending"),
                }
            )
        return {
            "ok": True,
            "kind": "draft_performance_preview",
            "read_only": True,
            "run_id": run_id,
            "draft_version": detail.get("draft_version"),
            "frames": frames,
        }

    def direction_proposals(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        audit = self.adapter.direction_proposals(str(run.draft_token))
        return {
            "ok": True,
            "kind": "direction_proposal_audit",
            "read_only": True,
            "run_id": run_id,
            "generation_mode": run.source_summary.get("generation_mode"),
            "draft_version": self.adapter.draft_detail(str(run.draft_token)).get("draft_version"),
            **audit,
        }

    def decide_direction_proposal(self, run_id: str, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        self.adapter.decide_direction_proposal(
            token=str(run.draft_token),
            proposal_id=proposal_id,
            action=str(payload.get("action") or "").strip(),
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)


    def task_preflight_summary(self, run_id: str) -> dict[str, Any]:
        """Explain task-local production decisions without invoking an AI provider."""
        run = self._run(run_id)
        detail = self.adapter.draft_detail(str(run.draft_token))
        cast_data = detail.get("cast") if isinstance(detail.get("cast"), dict) else {}
        cast = cast_data.get("cast") if isinstance(cast_data.get("cast"), dict) else {}
        details = run.source_summary.get("speaker_details")
        if not isinstance(details, list):
            details = [{"speaker": name, "count": 0, "sample": "", "first_line": None} for name in run.source_summary.get("speakers", [])]
        speakers = []
        missing = 0
        for item in details:
            if not isinstance(item, dict):
                continue
            name = str(item.get("speaker") or "").strip()
            if not name:
                continue
            mapping = cast.get(name) if isinstance(cast.get(name), dict) else {"kind": "unset"}
            kind = str(mapping.get("kind") or "unset")
            if kind == "unset":
                missing += 1
            speakers.append(
                {
                    "speaker": name,
                    "count": int(item.get("count") or 0),
                    "sample": str(item.get("sample") or ""),
                    "first_line": item.get("first_line"),
                    "mapping": {
                        "kind": kind,
                        "name": str(mapping.get("name") or mapping.get("display_name") or mapping.get("id") or ""),
                    },
                }
            )
        requests = []
        for card in detail.get("cards", []):
            if not isinstance(card, dict) or card.get("kind") not in {"background_request", "sound_request"}:
                continue
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            requests.append(
                {
                    "card_id": str(card.get("card_id") or ""),
                    "line_no": card.get("line_no"),
                    "kind": str(card.get("kind") or ""),
                    "description": str(current.get("description") or current.get("text") or card.get("raw") or "").strip()[:100],
                    "state": str(card.get("review_state") or "pending"),
                }
            )
        diagnostics = [
            {
                "severity": str(item.get("severity") or "warning"),
                "code": str(item.get("code") or "diagnostic"),
                "message": str(item.get("message") or "需要检查的项目"),
                "line_no": item.get("line_no"),
                "card_id": item.get("card_id"),
            }
            for item in detail.get("diagnostics", []) if isinstance(item, dict)
        ]
        diagnostics.sort(key=lambda item: (0 if item["severity"] == "error" else 1, item["line_no"] or 0, item["code"]))
        if missing:
            next_action = {"stage": "mapping", "label": f"先处理 {missing} 位未映射说话者", "detail": "每位说话者都要明确使用立绘、旁白或无立绘角色，才能安全进入后续演出制作。"}
        elif requests:
            next_action = {"stage": "review", "label": f"处理 {len(requests)} 项素材请求", "detail": "在审查器内从当前任务的冻结素材清单选择背景或音效。"}
        elif detail["counts"].get("pending"):
            next_action = {"stage": "review", "label": f"审查 {detail['counts']['pending']} 张待确认卡片", "detail": "逐卡确认台词、演出和场景后，系统才会开放编译。"}
        else:
            next_action = {"stage": "review", "label": "进入编译前检查", "detail": "草稿已无待审卡片；请在审查页运行检查并确认编译门禁。"}
        return {
            "ok": True,
            "kind": "task_preflight_summary",
            "source": "frozen_draft",
            "speakers": speakers,
            "scenes": run.source_summary.get("scenes") if isinstance(run.source_summary.get("scenes"), list) else [],
            "requests": requests,
            "diagnostics": diagnostics,
            "counts": detail.get("counts") or {},
            "next_action": next_action,
        }

    def _gates(
        self, run: ProductionRun, draft: dict[str, Any] | None
    ) -> dict[str, Any]:
        caps = self.adapter.capabilities()
        if not draft:
            return {
                "preflight": {"passed": False, "blockers": ["draft_missing"]},
                "compile": {"passed": False, "blockers": ["draft_missing"]},
                "install": {"passed": False, "blockers": ["build_missing"]},
            }
        blockers = []
        if draft["counts"]["blocking_errors"]:
            blockers.append("blocking_diagnostics")
        if draft["counts"]["pending"]:
            blockers.append("pending_review")
        if caps["compile"]["state"] != "available":
            blockers.append("compile_not_configured")
        return {
            "preflight": {
                "passed": draft["counts"]["blocking_errors"] == 0,
                "blockers": ["blocking_diagnostics"] if draft["counts"]["blocking_errors"] else [],
            },
            "compile": {"passed": not blockers, "blockers": blockers},
            "install": {
                "passed": bool(run.last_build_id)
                and caps["install"]["state"] == "available",
                "blockers": ([] if run.last_build_id else ["build_missing"])
                + (
                    ["aa_workspace_not_configured"]
                    if caps["install"]["state"] != "available"
                    else []
                ),
            },
        }

    def update_cast(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        speaker = str(payload.get("speaker") or "").strip()
        mapping = payload.get("mapping")
        if not speaker or not isinstance(mapping, dict):
            raise ProductionError("invalid_cast_binding", "speaker 和 mapping 为必填项")
        if str(mapping.get("kind") or "") == "portrait":
            identifier = str(mapping.get("id") or "").strip()
            if identifier and not self.adapter.draft_resource_contains(
                str(run.draft_token), "characters", identifier
            ):
                raise ProductionError(
                    "character_not_found",
                    "所选角色不在该草稿冻结的资源索引中",
                    status=404,
                )
            if identifier:
                character = self.adapter.draft_character_detail(
                    str(run.draft_token), identifier
                )["character"]
                mapping = dict(mapping)
                # The task snapshot owns display names. Ignore stale client labels.
                mapping["name"] = str(character.get("name") or identifier)
        try:
            expected = int(payload["expected_draft_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionError("expected_version_required", "必须提供 expected_draft_version") from exc
        self.adapter.update_cast_binding(
            token=str(run.draft_token),
            speaker=speaker,
            mapping=mapping,
            expected_draft_version=expected,
        )
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def approve_review(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        card_ids = payload.get("card_ids")
        if card_ids is not None and not isinstance(card_ids, list):
            raise ProductionError("invalid_card_ids", "card_ids 必须是数组或 null")
        try:
            expected = int(payload["expected_draft_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionError("expected_version_required", "必须提供 expected_draft_version") from exc
        draft = self.adapter.approve_cards(
            token=str(run.draft_token), card_ids=card_ids, expected_draft_version=expected
        )
        run.state = "ready_to_compile" if draft["review_ready"] else "waiting_for_review"
        run.current_stage = "review_install"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    @staticmethod
    def _expected_version(payload: dict[str, Any]) -> int:
        try:
            return int(payload["expected_draft_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionError(
                "expected_version_required", "必须提供 expected_draft_version"
            ) from exc

    def update_card(
        self, run_id: str, card_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._run(run_id)
        patch = payload.get("patch")
        if not isinstance(patch, dict) or not patch:
            raise ProductionError("card_patch_required", "patch 必须是非空对象")
        detail = self.adapter.draft_detail(str(run.draft_token))
        card = next((item for item in detail["cards"] if item["card_id"] == card_id), None)
        if not card:
            raise ProductionError("card_not_found", "卡片不存在", status=404)
        patch = self._validated_card_patch(card, patch)
        if str(card.get("kind") or "") == "line":
            self._validate_line_performance(run, detail, card, patch)
        self.adapter.update_card(
            token=str(run.draft_token),
            card_id=card_id,
            patch=patch,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def _validate_line_performance(
        self, run: ProductionRun, detail: dict[str, Any], card: dict[str, Any], patch: dict[str, Any]
    ) -> None:
        """Keep line-level face choices within the speaker's frozen portrait mapping."""
        current = card.get("current") if isinstance(card.get("current"), dict) else {}
        face = str(patch.get("face", current.get("face") or "")).strip()
        if not face:
            return
        speaker = str(patch.get("who") or current.get("who") or "").strip()
        cast_data = detail.get("cast") if isinstance(detail.get("cast"), dict) else {}
        cast = cast_data.get("cast") if isinstance(cast_data.get("cast"), dict) else {}
        mapping = cast.get(speaker) if isinstance(cast.get(speaker), dict) else {}
        if mapping.get("kind") != "portrait":
            raise ProductionError(
                "face_requires_portrait_mapping",
                "只有已映射立绘的说话者才能设置表情；请先在角色映射中选择骨骼角色",
                status=409,
            )
        identifier = str(mapping.get("id") or "").strip()
        character = self.adapter.draft_character_detail(str(run.draft_token), identifier)["character"]
        choices = {
            str(value).strip()
            for item in character.get("faces", [])
            if isinstance(item, dict)
            for value in (item.get("id"), item.get("raw"), item.get("label"))
            if str(value or "").strip()
        }
        if face not in choices:
            raise ProductionError(
                "face_not_available_for_character",
                "所选表情不属于当前说话者映射的冻结角色素材",
                status=409,
                details={"speaker": speaker, "character": identifier},
            )

    @staticmethod
    def _validated_card_patch(card: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "line": {"who", "text", "face", "emo", "act", "fx"},
            "dir": {"cmd", "arg"}, "scene": {"title"}, "title": {"title"}, "meta": {"text"},
        }.get(str(card.get("kind") or ""))
        if allowed is None:
            raise ProductionError("card_not_editable", "这类卡片需要通过专用操作处理，不能直接编辑", status=409)
        unexpected = sorted(set(patch) - allowed)
        if unexpected:
            raise ProductionError("card_patch_field_not_allowed", "该卡片不支持修改这些字段", details={"fields": unexpected, "allowed": sorted(allowed)})
        normalized = {key: str(value) for key, value in patch.items()}
        kind = str(card.get("kind") or "")
        if kind == "dir":
            current = card.get("current") if isinstance(card.get("current"), dict) else {}
            command = normalized.get("cmd", str(current.get("cmd") or "")).strip().casefold()
            argument = normalized.get("arg", str(current.get("arg") or "")).strip()
            if command not in DIRECTIVE_COMMANDS:
                raise ProductionError("directive_not_supported", "请选择已支持的 AA 演出指令，或使用“原样 AA 指令”", details={"command": command, "allowed": sorted(DIRECTIVE_COMMANDS)})
            if command in RESOURCE_DIRECTIVES:
                raise ProductionError("directive_requires_resource_picker", "背景和音效必须从当前任务的素材选择器中选取，不能直接输入名称", status=409, details={"command": command})
            if command in NO_ARGUMENT_DIRECTIVES:
                argument = ""
            elif not argument:
                raise ProductionError("directive_argument_required", f"@{command} 需要填写参数")
            if command == "wait" and not argument.isdigit():
                raise ProductionError("directive_argument_invalid", "@wait 的参数必须是毫秒整数")
            if command == "move":
                parts = argument.split()
                if len(parts) < 2 or parts[1] not in {"1", "2", "3", "4", "5"}:
                    raise ProductionError("directive_argument_invalid", "@move 请填写“角色名 位置”，位置为 1 到 5")
            if command == "stage" and (not argument or any(not re.fullmatch(r".+@[1-5]", slot) for slot in argument.split())):
                raise ProductionError("directive_argument_invalid", "@stage 请填写“角色@位置”，位置为 1 到 5")
            return {"cmd": command, "arg": argument}
        if kind in {"line", "meta"} and "text" in normalized and not normalized["text"].strip():
            raise ProductionError("card_text_required", "文本内容不能为空")
        if kind in {"scene", "title"} and "title" in normalized and not normalized["title"].strip():
            raise ProductionError("card_title_required", "标题不能为空")
        return normalized

    def insert_card(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        kind = str(payload.get("kind") or "").strip()
        fields = payload.get("fields")
        if kind not in {"line", "dir", "scene", "meta"}:
            raise ProductionError(
                "invalid_card_kind",
                "不支持的卡片类型",
                details={"allowed": ["line", "dir", "scene", "meta"]},
            )
        if not isinstance(fields, dict):
            raise ProductionError("card_fields_required", "fields 必须是对象")
        self.adapter.insert_card(
            token=str(run.draft_token),
            after_card_id=(str(payload["after_card_id"]) if payload.get("after_card_id") else None),
            kind=kind,
            fields=fields,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def create_cg_segment(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        background_key = str(payload.get("background_key") or "").strip()
        if not self.adapter.draft_cg_background_contains(str(run.draft_token), background_key):
            raise ProductionError(
                "cg_background_not_found",
                "所选素材不是当前任务可用的自定义背景或官方 CG",
                status=404,
            )
        self.adapter.create_cg_segment(
            token=str(run.draft_token),
            start_card_id=str(payload.get("start_card_id") or ""),
            end_card_id=str(payload.get("end_card_id") or ""),
            background_key=background_key,
            label=str(payload.get("label") or ""),
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def delete_cg_segment(
        self, run_id: str, segment_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._run(run_id)
        self.adapter.delete_cg_segment(
            token=str(run.draft_token),
            segment_id=segment_id,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def move_card(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        card_id = str(payload.get("card_id") or "").strip()
        if not card_id:
            raise ProductionError("card_id_required", "card_id 为必填项")
        before = str(payload.get("before_card_id") or "").strip() or None
        self.adapter.move_card(
            token=str(run.draft_token),
            card_id=card_id,
            before_card_id=before,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def delete_card(
        self, run_id: str, card_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._run(run_id)
        self.adapter.delete_card(
            token=str(run.draft_token),
            card_id=card_id,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def resolve_background_request(
        self, run_id: str, card_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._run(run_id)
        action = str(payload.get("action") or "select").strip()
        if action not in {"select", "black"}:
            raise ProductionError(
                "invalid_background_resolution",
                "背景请求只能选择背景或使用黑屏",
            )
        background_key = (
            "BG_Black" if action == "black" else str(payload.get("background_key") or "").strip()
        )
        if not background_key:
            raise ProductionError("background_key_required", "必须选择一个背景")
        if not self.adapter.draft_resource_contains(
            str(run.draft_token), "backgrounds", background_key
        ):
            raise ProductionError("background_not_found", "所选背景不在资源索引中", status=404)
        self.adapter.resolve_background(
            token=str(run.draft_token),
            card_id=card_id,
            background_key=background_key,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def resolve_sound_request(
        self, run_id: str, card_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        run = self._run(run_id)
        action = str(payload.get("action") or "select").strip()
        if action not in {"select", "remove"}:
            raise ProductionError(
                "invalid_sound_resolution",
                "音效请求只能选择已登记音效或移除声音指令",
            )
        sound_key = str(payload.get("sound_key") or "").strip() or None
        if action == "select":
            if not sound_key:
                raise ProductionError("sound_key_required", "必须选择一个音效")
            if not self.adapter.draft_resource_contains(
                str(run.draft_token), "sounds", sound_key
            ):
                raise ProductionError("sound_not_found", "所选音效不在资源索引中", status=404)
        self.adapter.resolve_sound(
            token=str(run.draft_token),
            card_id=card_id,
            action=action,
            sound_key=sound_key,
            expected_draft_version=self._expected_version(payload),
        )
        run.state = "waiting_for_review"
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return self.run_detail(run_id)

    def validate(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        return self.adapter.validate(str(run.draft_token))

    def compile(self, run_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._run(run_id)
        try:
            expected = int(payload["expected_draft_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductionError("expected_version_required", "必须提供 expected_draft_version") from exc
        build_id = self.adapter.create_compile_snapshot(str(run.draft_token), expected)
        run.state = "compiling"
        run.current_stage = "review_install"
        run.pending_build_id = build_id
        run.updated_at = utc_now()
        self.repository.save_run(run)

        def work() -> dict[str, Any]:
            try:
                result = self.adapter.execute_compile(str(run.draft_token), build_id)
            except Exception:
                latest = self._run(run_id)
                latest.state = "compile_failed"
                latest.pending_build_id = None
                latest.updated_at = utc_now()
                self.repository.save_run(latest)
                raise
            else:
                latest = self._run(run_id)
                latest.state = "compiled"
                latest.pending_build_id = None
                latest.last_build_id = build_id
                latest.updated_at = utc_now()
                self.repository.save_run(latest)
                return {"run_id": run_id, "build_id": build_id, "bundle": result}

        job = self.jobs.submit(
            "compile",
            work,
            run_id=run_id,
            retry_context={"expected_draft_version": expected},
        )
        return 202, {"ok": True, "job": self._job_public(job.to_dict()), "build_id": build_id}

    def job_detail(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if not job:
            raise ProductionError("job_not_found", "后台任务不存在", status=404)
        return {"ok": True, "job": self._job_public(job.to_dict())}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if not job:
            raise ProductionError("job_not_found", "后台任务不存在", status=404)
        if not self.jobs.cancel(job_id):
            raise ProductionError(
                "job_not_cancellable",
                "只能取消尚未开始的排队任务；运行中的任务不会被强制终止",
                status=409,
                details={"state": job.state},
            )
        return {"ok": True, "job": self._job_public(job.to_dict())}

    def retry_job(self, job_id: str) -> dict[str, Any]:
        """Resubmit a failed stage using only persisted, non-sensitive inputs."""
        job = self.jobs.get(job_id)
        if not job:
            raise ProductionError("job_not_found", "后台任务不存在", status=404)
        if job.state not in {"failed", "interrupted"}:
            raise ProductionError(
                "job_not_retryable",
                "只能重新提交已失败或服务重启中断的任务",
                status=409,
                details={"state": job.state},
            )

        context = job.retry_context if isinstance(job.retry_context, dict) else {}
        kind = job.kind
        run_id = job.run_id
        if kind == "model_connection_test":
            _, response = self.test_direction_model()
        elif kind == "ai_preflight" and run_id:
            _, response = self.start_ai_preflight(run_id)
        elif kind in {"cg_advice", "direction_generation", "compile"} and run_id:
            if "expected_draft_version" not in context:
                raise ProductionError(
                    "job_retry_unavailable",
                    "旧任务没有保存可恢复的草稿版本，无法安全重试",
                    status=409,
                    details={"kind": kind},
                )
            try:
                expected = int(context["expected_draft_version"])
            except (TypeError, ValueError) as exc:
                raise ProductionError(
                    "job_retry_unavailable",
                    "任务的草稿版本信息无效，无法安全重试",
                    status=409,
                    details={"kind": kind},
                ) from exc
            payload: dict[str, Any] = {"expected_draft_version": expected}
            if kind == "cg_advice":
                if not {"start_card_id", "end_card_id"}.issubset(context):
                    raise ProductionError(
                        "job_retry_unavailable",
                        "旧 CG 咨询任务缺少卡片范围，无法安全重试",
                        status=409,
                        details={"kind": kind},
                    )
                payload.update(
                    start_card_id=str(context.get("start_card_id") or ""),
                    end_card_id=str(context.get("end_card_id") or ""),
                )
                _, response = self.request_cg_advice(run_id, payload)
            elif kind == "direction_generation":
                payload["story_type"] = str(context.get("story_type") or "auto")
                payload["layout_mode"] = str(context.get("layout_mode") or "ai")
                _, response = self.generate_direction(run_id, payload)
            else:
                _, response = self.compile(run_id, payload)
        else:
            raise ProductionError(
                "job_retry_unavailable",
                "该任务类型或关联任务信息不足，无法安全重试",
                status=409,
                details={"kind": kind},
            )

        return {"ok": True, "retried_from": job_id, "job": response["job"]}

    def list_jobs(self) -> dict[str, Any]:
        return {"ok": True, "items": [self._job_public(job.to_dict()) for job in self.jobs.list()]}

    @staticmethod
    def _job_public(job: dict[str, Any]) -> dict[str, Any]:
        kind = str(job.get("kind") or "")
        state = str(job.get("state") or "")
        retry_context = job.get("retry_context") if isinstance(job.get("retry_context"), dict) else {}
        retryable = state in {"failed", "interrupted"} and (
            kind == "model_connection_test"
            or (kind == "ai_preflight" and bool(job.get("run_id")))
            or (
                kind in {"cg_advice", "direction_generation", "compile"}
                and bool(job.get("run_id"))
                and "expected_draft_version" in retry_context
                and (
                    kind != "cg_advice"
                    or {"start_card_id", "end_card_id"}.issubset(retry_context)
                )
            )
        )
        label = {
            "compile": "编译 AA 工程",
            "direction_generation": "AI 安排演出",
            "ai_preflight": "AI 初审（只读建议）",
            "model_connection_test": "测试演出模型连接",
            "cg_advice": "生成 CG 制作意见",
        }.get(kind, kind or "后台任务")
        if state == "succeeded":
            next_action = {"label": "已完成", "detail": "结果已写回关联任务。", "stage": None}
        elif state == "cancelled":
            next_action = {"label": "已取消", "detail": "任务尚未开始，未写入任何结果。", "stage": None}
        elif state in {"failed", "interrupted"}:
            stage = "mapping" if kind == "ai_preflight" else "review" if kind in {"compile", "direction_generation"} else None
            next_action = {
                "label": "查看失败原因并回到任务处理",
                "detail": "修正问题后，从对应步骤重新提交；系统不会自动覆盖现有草稿。",
                "stage": stage,
            }
        else:
            next_action = {"label": "正在执行", "detail": "完成后任务状态会自动更新。", "stage": None}
        public = {key: value for key, value in job.items() if key != "retry_context"}
        return {
            **public,
            "retryable": retryable,
            "retry_label": "重试此阶段" if retryable else None,
            "label": label,
            "next_action": next_action,
        }

    def install(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._run(run_id)
        build_id = str(payload.get("build_id") or run.last_build_id or "").strip()
        if not build_id:
            raise ProductionError("build_required", "安装前必须先完成编译", status=409)
        if not BUILD_ID.fullmatch(build_id):
            raise ProductionError("invalid_build_id", "构建 ID 无效")
        if run.state != "compiled" or build_id != run.last_build_id:
            raise ProductionError(
                "build_not_installable",
                "只能安装当前制作任务最近一次成功完成的构建",
                status=409,
                details={"state": run.state, "last_build_id": run.last_build_id},
            )
        result = self.adapter.install(
            token=str(run.draft_token),
            build_id=build_id,
            category=str(payload.get("category") or ""),
            story_name=(str(payload["story_name"]) if payload.get("story_name") else None),
        )
        run.state = "installed"
        run.last_installed_project = str(result.get("project") or run.project)
        run.updated_at = utc_now()
        self.repository.save_run(run)
        return {"ok": True, "run": run.to_dict(), "install": result}

    def _installable_build(self, run_id: str, build_id: str | None = None) -> tuple[ProductionRun, str]:
        run = self._run(run_id)
        selected = str(build_id or run.last_build_id or "").strip()
        if not selected:
            raise ProductionError("build_required", "必须先完成编译", status=409)
        if not BUILD_ID.fullmatch(selected):
            raise ProductionError("invalid_build_id", "构建 ID 无效")
        if selected != run.last_build_id or run.state not in {"compiled", "installed"}:
            raise ProductionError(
                "build_not_installable",
                "只能查看当前制作任务最近一次成功构建的安装信息",
                status=409,
            )
        return run, selected

    def install_options(self, run_id: str, build_id: str | None = None) -> dict[str, Any]:
        run, selected = self._installable_build(run_id, build_id)
        return self.adapter.install_options(token=str(run.draft_token), build_id=selected)

    def check_install(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run, selected = self._installable_build(
            run_id, str(payload.get("build_id") or "") or None
        )
        return self.adapter.check_install_target(
            token=str(run.draft_token),
            build_id=selected,
            category=str(payload.get("category") or ""),
            story_name=(str(payload["story_name"]) if payload.get("story_name") is not None else None),
        )
