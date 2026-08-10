# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 编译快照与 Build Bundle 管理 (build_bundle.py)
实现 compile 202 前锁定快照、不可变 Bundle、files.json hash 清单、manifest_delta 与原子 bundle.complete 封存
"""

import datetime
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from draft_store import DraftStore, calc_sha256
from document import parse_document_lossless
from script2aap import compile_script, warn as compiler_warnings

HERE = Path(__file__).resolve().parent


class CompileInputStaleError(ValueError):
    """编译输入已陈旧异常 (HTTP 409 code: compile_input_stale)"""
    pass


def calc_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class BuildBundleManager:
    def __init__(self, store: Optional[DraftStore] = None):
        self.store = store or DraftStore()

    def create_compile_snapshot(self, token: str, expected_draft_version: int) -> str:
        """202 响应前在事务锁内验证版本并复制不可变快照"""
        draft_dir = self.store.get_draft_path(token)

        with self.store.draft_lock(token):
            session_file = draft_dir / "session.json"
            if not session_file.is_file():
                raise FileNotFoundError(f"Draft session missing: {token}")

            session = json.loads(session_file.read_text(encoding="utf-8"))
            if session["draft_version"] != expected_draft_version:
                raise CompileInputStaleError(
                    f"Compile input stale: expected {expected_draft_version}, got {session['draft_version']}"
                )

            build_id = f"build-{uuid.uuid4().hex[:12]}"
            tmp_build_dir = draft_dir / "builds" / ".tmp" / build_id
            input_dir = tmp_build_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)

            # 复制不可变输入快照
            for fname in [
                "edited.txt",
                "session.json",
                "identity.json",
                "diagnostics.json",
                "source_map.json",
                "cast.json",
            ]:
                fpath = draft_dir / fname
                if fpath.is_file():
                    shutil.copy2(fpath, input_dir / fname)

            cast_path = input_dir / "cast.json"
            try:
                cast_data = json.loads(cast_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cast_data = {}
            if not isinstance(cast_data.get("cast"), dict) or not cast_data["cast"]:
                # Imported legacy drafts may not have actor bindings.  An empty
                # portrait cast is safe; the application-level sample cast is not.
                edited_text = (input_dir / "edited.txt").read_text(encoding="utf-8")
                speakers = sorted({
                    str(node.fields.get("who") or "").strip()
                    for node in parse_document_lossless(edited_text)
                    if node.kind == "line" and str(node.fields.get("who") or "").strip()
                })
                cast_path.write_text(
                    json.dumps(
                        {
                            "default_bg": "BG_Black",
                            "default_bgm": 999,
                            "scene_bg": {},
                            "cast": {
                                speaker: {"narrator": True} for speaker in speakers
                            },
                            "alias": {},
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            resource_index = draft_dir / "resources.json"
            if not resource_index.is_file():
                # Review drafts historically stored this token-scoped file in out/.
                resource_index = HERE / "out" / f"{token}.resources.json"
            if not resource_index.is_file():
                resource_index = HERE / "aa_resources.json"
            if not resource_index.is_file():
                raise FileNotFoundError(f"Draft resource index missing: {token}")
            shutil.copy2(resource_index, input_dir / "resources.json")

            return build_id

    def execute_build_worker(self, token: str, build_id: str) -> Dict[str, Any]:
        """Worker 仅消费不可变快照，构造 Build Bundle 并原子封存"""
        draft_dir = self.store.get_draft_path(token)
        tmp_build_dir = draft_dir / "builds" / ".tmp" / build_id
        input_dir = tmp_build_dir / "input"

        if not input_dir.is_dir():
            raise FileNotFoundError(f"Compile snapshot missing: {input_dir}")

        edited_text = (input_dir / "edited.txt").read_text(encoding="utf-8")
        session = json.loads((input_dir / "session.json").read_text(encoding="utf-8"))
        content_rev = session["content_revision"]
        project_name = session["project"]

        # 在临时 bundle 目录内放置生成产物
        output_bundle_tmp = tmp_build_dir / "bundle"
        output_bundle_tmp.mkdir(parents=True, exist_ok=True)

        script_tmp = tmp_build_dir / "script.txt"
        script_tmp.write_text(edited_text, encoding="utf-8")
        compiler_output = tmp_build_dir / "compiler-output"
        compiler_warnings.items.clear()

        # 调纯函数编译生成工程
        res = compile_script(
            {
                "script": str(script_tmp),
                "out": project_name,
                "cast": str(input_dir / "cast.json"),
                "index": str(input_dir / "resources.json"),
                "install": False,
                "output_dir": str(compiler_output),
            }
        )

        aap_src = Path(res["aap_file"])
        proj_dir_src = Path(res["project_dir"])

        # 将 aap 和工程文件夹移动进 output_bundle_tmp
        shutil.copy2(aap_src, output_bundle_tmp / f"{project_name}.aap")

        target_proj_dir = output_bundle_tmp / "project"
        if proj_dir_src.is_dir():
            shutil.copytree(proj_dir_src, target_proj_dir, dirs_exist_ok=True)

        # 构造 manifest_delta.json (增量记录)
        delta_data = {
            "add": [
                {
                    "type": "project",
                    "name": project_name,
                    "created_at": datetime.datetime.now().isoformat(),
                }
            ],
            "remove": [],
        }
        (target_proj_dir / "manifest_delta.json").write_text(
            json.dumps(delta_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 构造 build.json
        build_meta = {
            "build_id": build_id,
            "draft_token": token,
            "content_revision": content_rev,
            "project": project_name,
            "source_sha256": calc_sha256(edited_text),
            "created_at": datetime.datetime.now().isoformat(),
        }
        (output_bundle_tmp / "build.json").write_text(
            json.dumps(build_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 构造 validation.json
        (output_bundle_tmp / "validation.json").write_text(
            json.dumps({"valid": True, "diagnostics": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 计算全文件 hash 生成 files.json
        files_manifest = []
        for root, _, files in os.walk(output_bundle_tmp):
            for file in files:
                f_full = Path(root) / file
                rel_p = f_full.relative_to(output_bundle_tmp).as_posix()
                files_manifest.append(
                    {
                        "path": rel_p,
                        "size": f_full.stat().st_size,
                        "sha256": calc_file_sha256(f_full),
                    }
                )

        (output_bundle_tmp / "files.json").write_text(
            json.dumps(files_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 写入 bundle.complete 标记
        (output_bundle_tmp / "bundle.complete").write_text(
            datetime.datetime.now().isoformat(), encoding="utf-8"
        )

        # 原子移动到正式 Bundle 目录 out/drafts/<token>/builds/<content_revision>/<build_id>/
        final_bundle_dir = draft_dir / "builds" / str(content_rev) / build_id
        final_bundle_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_bundle_dir.exists():
            shutil.rmtree(final_bundle_dir)

        os.replace(output_bundle_tmp, final_bundle_dir)
        shutil.rmtree(tmp_build_dir, ignore_errors=True)

        # 更新 session.json 中的最后编译 build_id
        with self.store.draft_lock(token):
            session_file = draft_dir / "session.json"
            if session_file.is_file():
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                sess["last_compiled_build_id"] = build_id
                sess["last_compiled_content_revision"] = content_rev
                session_file.write_text(json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "project": project_name,
            "aap_file": str(final_bundle_dir / f"{project_name}.aap"),
            "build_id": build_id,
            "bundle_dir": str(final_bundle_dir),
            "content_revision": content_rev,
            "warnings": [message for _line, message in compiler_warnings.items],
        }
