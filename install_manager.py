# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 安装管理器 (install_manager.py)
实现 Build Bundle 校验、AA 退出拦截 423、delta 合并与 project_install_record.json 安装记录
"""

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import aapaths
from aa_project_assets import assert_aa_closed, validate_windows_path_component
from build_bundle import calc_file_sha256
from draft_store import DraftStore

HERE = Path(__file__).resolve().parent


class AARunningError(RuntimeError):
    """AA 客户端运行中拦截异常 (HTTP 423 code: aa_running)"""
    pass


class AACorruptBundleError(ValueError):
    """Bundle 损坏或校验失败异常 (HTTP 400 code: corrupted_bundle)"""
    pass


class AAInstallTargetExistsError(FileExistsError):
    """A renamed installation would overwrite an existing AA project."""


def compose_install_project_name(category: str, story_name: str) -> str:
    """Compose one AA project component from an optional one-level category."""
    category = str(category or "").strip()
    story_name = str(story_name or "").strip()
    if category and "-" in category:
        raise ValueError("分类只能是一级分类，不能包含连字符")
    if not story_name:
        raise ValueError("剧情名称不能为空")
    normalized_story = validate_windows_path_component(story_name, label="story name")
    if not category:
        return normalized_story
    normalized_category = validate_windows_path_component(category, label="category")
    return validate_windows_path_component(
        f"{normalized_category}-{normalized_story}", label="project name"
    )


class InstallManager:
    def __init__(
        self,
        store: Optional[DraftStore] = None,
        aa_data_dir: Optional[str] = None,
        record_path: Optional[str] = None,
    ):
        self.store = store or DraftStore()
        self.aa_data_dir = aa_data_dir
        if record_path:
            self.record_path = Path(record_path)
        else:
            self.record_path = HERE / "out" / "project_install_record.json"

    def find_bundle_dir(self, token: str, build_id: str) -> Path:
        draft_dir = self.store.get_draft_path(token)
        builds_root = draft_dir / "builds"
        if not builds_root.is_dir():
            raise AACorruptBundleError(f"Builds directory missing for token {token}")

        # 遍历 builds/<content_revision>/<build_id>
        for rev_dir in builds_root.iterdir():
            if rev_dir.is_dir() and rev_dir.name != ".tmp":
                candidate = rev_dir / build_id
                if candidate.is_dir():
                    return candidate

        raise AACorruptBundleError(f"Build ID {build_id} not found under draft {token}")

    def verify_bundle(self, bundle_dir: Path):
        complete_file = bundle_dir / "bundle.complete"
        if not complete_file.is_file():
            raise AACorruptBundleError(f"Bundle incomplete: {bundle_dir}")

        files_manifest_file = bundle_dir / "files.json"
        if not files_manifest_file.is_file():
            raise AACorruptBundleError(f"Bundle files.json missing: {bundle_dir}")

        files_list = json.loads(files_manifest_file.read_text(encoding="utf-8"))
        for item in files_list:
            rel_path = item["path"]
            expected_sha = item["sha256"]
            target_f = bundle_dir / rel_path

            if not target_f.is_file():
                raise AACorruptBundleError(f"Bundle file missing: {rel_path}")

            actual_sha = calc_file_sha256(target_f)
            if actual_sha != expected_sha:
                raise AACorruptBundleError(f"Bundle file hash mismatch for {rel_path}")

    def install_options(self, token: str, build_id: str) -> Dict[str, Any]:
        bundle_dir = self.find_bundle_dir(token, build_id)
        try:
            build_meta = json.loads(
                (bundle_dir / "build.json").read_text(encoding="utf-8")
            )
            source_project = validate_windows_path_component(
                build_meta["project"], label="source project name"
            )
        except (KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
            raise AACorruptBundleError(f"Bundle build.json is invalid: {bundle_dir}") from exc

        aa_data = self.aa_data_dir
        if not aa_data:
            aa_data = aapaths.require(None)["data"]
        projects_dir = Path(aa_data) / "projects"
        categories = set()
        try:
            records = json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = {}
        if isinstance(records, dict):
            for record in records.values():
                if not isinstance(record, dict):
                    continue
                category = str(record.get("category") or "").strip()
                if category and "-" not in category:
                    try:
                        categories.add(
                            validate_windows_path_component(category, label="category")
                        )
                    except ValueError:
                        continue
        result = {
            "ok": True,
            "source_project": source_project,
            "default_category": "",
            "default_story_name": source_project,
            "categories": sorted(categories),
        }
        installed_project = source_project
        try:
            session = json.loads(
                (self.store.get_draft_path(token) / "session.json").read_text(
                    encoding="utf-8"
                )
            )
            if session.get("last_installed_build_id") == build_id:
                installed_project = validate_windows_path_component(
                    session.get("last_installed_project") or source_project,
                    label="installed project name",
                )
        except (OSError, json.JSONDecodeError, ValueError):
            installed_project = source_project
        installed_aap = projects_dir / f"{installed_project}.aap"
        if installed_aap.is_file():
            result["existing_install"] = {
                "project": installed_project,
                "aap_path": str(installed_aap),
                "project_dir": str(projects_dir / installed_project),
                "save_dir": str(Path(aa_data) / "saves" / installed_project),
            }
        return result

    @staticmethod
    def _write_renamed_aap(source: Path, destination: Path, project_name: str):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AACorruptBundleError(f"Bundle AAP is invalid: {source}") from exc
        if not isinstance(payload, dict) or "ProjectName" not in payload:
            raise AACorruptBundleError(f"Bundle AAP has no ProjectName: {source}")
        payload["ProjectName"] = project_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _copy_story_assets(source: Path, destination: Path):
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)

    @staticmethod
    def _rename_install_metadata(project_dir: Path, project_name: str):
        delta_file = project_dir / "manifest_delta.json"
        if not delta_file.is_file():
            return
        try:
            delta = json.loads(delta_file.read_text(encoding="utf-8"))
            for item in delta.get("add", []):
                if isinstance(item, dict) and item.get("type") == "project":
                    item["name"] = project_name
            delta_file.write_text(
                json.dumps(delta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise AACorruptBundleError(
                f"Bundle manifest_delta.json is invalid: {delta_file}"
            ) from exc

    def install_build(
        self,
        token: str,
        build_id: str,
        *,
        category: str = "",
        story_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1. 查找 Bundle
        bundle_dir = self.find_bundle_dir(token, build_id)

        # 2. 校验 Bundle SHA256
        self.verify_bundle(bundle_dir)

        # 3. 验证 AA 客户端已关闭
        try:
            assert_aa_closed()
        except RuntimeError as exc:
            raise AARunningError(str(exc)) from exc
        except Exception as exc:
            if type(exc).__name__ == "AARunningError":
                raise
            raise AARunningError(str(exc)) from exc

        # 4. 获取目标路径
        aa_data = self.aa_data_dir
        if not aa_data:
            P = aapaths.require(None)
            aa_data = P["data"]

        build_meta = json.loads((bundle_dir / "build.json").read_text(encoding="utf-8"))
        source_project = validate_windows_path_component(
            build_meta["project"], label="source project name"
        )
        category = str(category or "").strip()
        project_name = compose_install_project_name(
            category, source_project if story_name is None else story_name
        )

        projects_dir = Path(aa_data) / "projects"
        saves_dir = Path(aa_data) / "saves"
        projects_dir.mkdir(parents=True, exist_ok=True)
        saves_dir.mkdir(parents=True, exist_ok=True)

        aap_dest = projects_dir / f"{project_name}.aap"
        proj_res_dest = projects_dir / project_name
        save_res_dest = saves_dir / project_name
        if project_name != source_project and any(
            target.exists() for target in (aap_dest, proj_res_dest, save_res_dest)
        ):
            raise AAInstallTargetExistsError(
                f"AA 中已存在“{project_name}”，请更换分类或剧情名称"
            )

        # 5. 复制安装 AAP 与工程文件
        aap_source = bundle_dir / f"{source_project}.aap"
        if aap_source.is_file():
            if project_name == source_project:
                shutil.copy2(aap_source, aap_dest)
            else:
                self._write_renamed_aap(aap_source, aap_dest, project_name)

        proj_res_source = bundle_dir / "project"
        if project_name != source_project:
            self._copy_story_assets(projects_dir / source_project, proj_res_dest)
            self._copy_story_assets(saves_dir / source_project, save_res_dest)
        if proj_res_source.is_dir():
            shutil.copytree(proj_res_source, proj_res_dest, dirs_exist_ok=True)
            # 同时也复制到 saves 镜像
            shutil.copytree(proj_res_source, save_res_dest, dirs_exist_ok=True)
        if project_name != source_project:
            self._rename_install_metadata(proj_res_dest, project_name)
            self._rename_install_metadata(save_res_dest, project_name)

        # 6. 记录项目级安装状态 project_install_record.json
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        records = {}
        if self.record_path.is_file():
            try:
                records = json.loads(self.record_path.read_text(encoding="utf-8"))
            except Exception:
                records = {}

        records[project_name] = {
            "project": project_name,
            "source_project": source_project,
            "category": category,
            "installed_build_id": build_id,
            "installed_at": datetime.datetime.now().isoformat(),
            "source_draft_token": token,
        }
        self.record_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        # 7. 更新草稿会话中的安装记录
        draft_dir = self.store.get_draft_path(token)
        with self.store.draft_lock(token):
            session_file = draft_dir / "session.json"
            if session_file.is_file():
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                sess["last_installed_build_id"] = build_id
                sess["last_installed_project"] = project_name
                sess["installed_at"] = datetime.datetime.now().isoformat()
                session_file.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "project": project_name,
            "source_project": source_project,
            "installed_build_id": build_id,
            "aap_path": str(aap_dest),
            "project_dir": str(proj_res_dest),
            "save_dir": str(save_res_dest),
        }
