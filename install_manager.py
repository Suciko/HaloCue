# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 安装管理器 (install_manager.py)
实现 Build Bundle 校验、AA 退出拦截 423、delta 合并与 project_install_record.json 安装记录
"""

import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import aapaths
from aa_project_assets import assert_aa_closed
from build_bundle import calc_file_sha256
from draft_store import DraftStore

HERE = Path(__file__).resolve().parent


class AARunningError(RuntimeError):
    """AA 客户端运行中拦截异常 (HTTP 423 code: aa_running)"""
    pass


class AACorruptBundleError(ValueError):
    """Bundle 损坏或校验失败异常 (HTTP 400 code: corrupted_bundle)"""
    pass


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

    def install_build(self, token: str, build_id: str) -> Dict[str, Any]:
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
        project_name = build_meta["project"]

        projects_dir = Path(aa_data) / "projects"
        saves_dir = Path(aa_data) / "saves"
        projects_dir.mkdir(parents=True, exist_ok=True)
        saves_dir.mkdir(parents=True, exist_ok=True)

        # 5. 复制安装 AAP 与工程文件
        aap_source = bundle_dir / f"{project_name}.aap"
        aap_dest = projects_dir / f"{project_name}.aap"
        if aap_source.is_file():
            shutil.copy2(aap_source, aap_dest)

        proj_res_source = bundle_dir / "project"
        proj_res_dest = projects_dir / project_name
        if proj_res_source.is_dir():
            shutil.copytree(proj_res_source, proj_res_dest, dirs_exist_ok=True)
            # 同时也复制到 saves 镜像
            shutil.copytree(proj_res_source, saves_dir / project_name, dirs_exist_ok=True)

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
                sess["installed_at"] = datetime.datetime.now().isoformat()
                session_file.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "project": project_name,
            "installed_build_id": build_id,
        }
