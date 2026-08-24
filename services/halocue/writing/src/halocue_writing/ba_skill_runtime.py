from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .workflow_pack import (
    COMMON_RULES,
    MODE_SOURCES,
    PACK_VERSION,
    WORKFLOW_RULE_SOURCES,
    template_contract,
)


class BaWritingSkillRegistry:
    """Read-only bridge from the source Skill to the productized WritingPack.

    The source Skill stays outside the application data directory and is never
    treated as mutable work content.  A run receives logical source names and
    digests, while formal artifacts only keep the pack/source fingerprint.
    """

    skill_id = "ba-writing"
    source_revision = "ba-writing-source/1"

    def __init__(self, skill_dir: Path | None = None):
        configured = skill_dir or os.environ.get("HALOCUE_BA_WRITING_SKILL_DIR")
        if configured:
            root = Path(configured)
        else:
            # A repository-local Skill may be supplied later under this stable
            # boundary. User-specific writing material must be injected through
            # HALOCUE_BA_WRITING_SKILL_DIR and never becomes a repo prerequisite.
            repository_root = Path(__file__).resolve().parents[5]
            root = repository_root / "services" / "halocue" / "writing" / "skill" / "ba-writing"
        self.root = root
        self._repo = None
        self._manifest: dict | None = None

    def _path(self, logical_path: str) -> Path:
        candidate = (self.root / logical_path).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Skill source path escapes the Skill root") from exc
        return candidate

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _file_record(self, logical_path: str) -> dict:
        path = self._path(logical_path)
        if not path.is_file():
            return {"path": logical_path, "status": "missing"}
        data = path.read_bytes()
        return {
            "path": logical_path,
            "status": "available",
            "bytes": len(data),
            "sha256": self._digest(data),
        }

    def required_paths(
        self,
        mode_key: str | None = None,
        has_sensei: bool = False,
        *,
        task_id: str | None = None,
    ) -> list[str]:
        paths = list(WORKFLOW_RULE_SOURCES.get(task_id, ["SKILL.md", *COMMON_RULES]))
        if mode_key in MODE_SOURCES:
            paths.append(MODE_SOURCES[mode_key])
        if has_sensei:
            paths.append("knowledge/老师在场规则.md")
        return list(dict.fromkeys(paths))

    def compile(
        self,
        mode_key: str | None = None,
        has_sensei: bool = False,
        *,
        task_id: str | None = None,
    ) -> dict:
        paths = self.required_paths(mode_key, has_sensei, task_id=task_id)
        if self._manifest and self._manifest.get("status") == "ready":
            manifest_files = {item["path"]: item for item in self._manifest.get("files", [])}
            files = [
                {
                    key: item[key]
                    for key in ("path", "status", "bytes", "sha256")
                    if key in item
                }
                if (item := manifest_files.get(path))
                else {"path": path, "status": "missing"}
                for path in paths
            ]
        else:
            files = [self._file_record(path) for path in paths]
        missing = [item["path"] for item in files if item["status"] != "available"]
        material = "\n".join(
            f"{item['path']}:{item.get('sha256', 'missing')}" for item in files
        ).encode("utf-8")
        return {
            "id": self.skill_id,
            "pack_version": PACK_VERSION,
            "source_revision": self.source_revision,
            "status": "ready" if not missing else "unavailable",
            "mode_key": mode_key,
            "task_id": task_id,
            "has_sensei": bool(has_sensei),
            "required_files": files,
            "missing_files": missing,
            "source_digest": self._digest(material),
            "rule_policy": "source_files_are_read_only; formal_writes_require_proposals",
        }

    @staticmethod
    def _pack_paths() -> list[str]:
        paths = [
            path
            for sources in WORKFLOW_RULE_SOURCES.values()
            for path in sources
        ]
        paths.extend(MODE_SOURCES.values())
        paths.append("knowledge/老师在场规则.md")
        return list(dict.fromkeys(paths))

    def materialize(self, repo) -> dict:
        """Compile source rules into an immutable, manifest-committed snapshot."""
        files = [self._file_record(path) for path in self._pack_paths()]
        missing = [item["path"] for item in files if item["status"] != "available"]
        material = "\n".join(
            f"{item['path']}:{item.get('sha256', 'missing')}" for item in files
        ).encode("utf-8")
        digest = self._digest(material)
        manifest = {
            "schema_version": "writing-pack-manifest/1.0",
            "id": self.skill_id,
            "pack_version": PACK_VERSION,
            "source_revision": self.source_revision,
            "source_digest": digest,
            "status": "ready" if not missing else "unavailable",
            "files": files,
            "missing_files": missing,
            "manifest_uri": None,
        }
        if not missing:
            version_segment = PACK_VERSION.replace("/", "-")
            prefix = f"writing-packs/{version_segment}/{digest}"
            snapshot_files = []
            for item in files:
                data = self._path(item["path"]).read_bytes()
                uri, written_digest = repo.atomic_write_bytes(
                    f"{prefix}/sources/{item['path']}", data
                )
                if written_digest.removeprefix("sha256:") != item["sha256"]:
                    raise RuntimeError(f"WritingPack source digest changed while compiling: {item['path']}")
                snapshot_files.append({**item, "snapshot_uri": uri})
            manifest["files"] = snapshot_files
            manifest_uri, _ = repo.atomic_write_text(
                f"{prefix}/manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            manifest["manifest_uri"] = manifest_uri
            repo.atomic_write_text(
                manifest_uri,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        self._repo = repo
        self._manifest = manifest
        return self.public_manifest()

    def public_manifest(self) -> dict:
        manifest = self._manifest or {
            **self.compile(),
            "schema_version": "writing-pack-manifest/1.0",
            "files": self.compile()["required_files"],
            "manifest_uri": None,
        }
        return {
            key: manifest[key]
            for key in (
                "schema_version", "id", "pack_version", "source_revision",
                "source_digest", "status", "missing_files", "manifest_uri",
            )
            if key in manifest
        } | {"file_count": len(manifest.get("files", []))}

    def prompt_bundle(
        self,
        task_id: str,
        mode_key: str | None = None,
        has_sensei: bool = False,
    ) -> dict:
        selected = self.required_paths(mode_key, has_sensei, task_id=task_id)
        manifest = self._manifest
        if not manifest or manifest.get("status") != "ready" or self._repo is None:
            contract = self.compile(mode_key, has_sensei, task_id=task_id)
            return {
                "status": "unavailable",
                "task_id": task_id,
                "source_digest": contract["source_digest"],
                "source_files": selected,
                "missing_files": contract["missing_files"],
                "system_rules": "",
            }
        by_path = {item["path"]: item for item in manifest["files"]}
        missing = [path for path in selected if path not in by_path]
        if missing:
            return {
                "status": "unavailable", "task_id": task_id,
                "source_digest": manifest["source_digest"],
                "source_files": selected, "missing_files": missing,
                "system_rules": "",
            }
        sections = []
        for logical_path in selected:
            item = by_path[logical_path]
            sections.append(
                f"## 规则来源：{logical_path}\n"
                + self._repo.read_text(item["snapshot_uri"]).strip()
            )
        return {
            "status": "ready",
            "task_id": task_id,
            "source_digest": manifest["source_digest"],
            "source_files": selected,
            "missing_files": [],
            "system_rules": "\n\n".join(sections),
        }

    def descriptor(self) -> dict:
        base = self.public_manifest() if self._manifest else self.compile()
        return {
            "id": self.skill_id,
            "pack_version": PACK_VERSION,
            "source_revision": self.source_revision,
            "status": base["status"],
            "source_digest": base["source_digest"],
            "available_file_count": (
                base.get("file_count")
                or sum(item["status"] == "available" for item in base.get("required_files", []))
            ),
            "missing_files": base["missing_files"],
            "manifest_uri": base.get("manifest_uri"),
            "configured_by": "HALOCUE_BA_WRITING_SKILL_DIR" if os.environ.get("HALOCUE_BA_WRITING_SKILL_DIR") else "development_checkout",
        }


class BaWritingPromptAssembler:
    """Assemble one stage-specific, cache-stable system prefix."""

    def __init__(self, registry: BaWritingSkillRegistry):
        self.registry = registry

    def describe_bundle(
        self,
        task_id: str,
        *,
        mode_key: str | None = None,
        has_sensei: bool = False,
        output_mode: str = "official_script",
    ) -> dict:
        """Expose the versioned prompt contract without leaking rule bodies.

        Runtime prompts still come from ``assemble``. This descriptor is safe
        to persist in task contracts and return to the UI because it contains
        only source names, digests, versions and checks.
        """
        bundle = self.registry.prompt_bundle(task_id, mode_key, has_sensei)
        contract = template_contract(task_id)
        return {
            "schema_version": "ba-writing-prompt-bundle/1.0",
            "id": self.registry.skill_id,
            "status": bundle.get("status", "unavailable"),
            "pack_version": PACK_VERSION,
            "task_id": task_id,
            "template_version": contract["version"],
            "mode_key": mode_key,
            "has_sensei": bool(has_sensei),
            "output_mode": output_mode,
            "source_digest": bundle.get("source_digest"),
            "source_files": bundle.get("source_files", []),
            "missing_files": bundle.get("missing_files", []),
            "checks": contract["checks"],
            "cache_boundary": "static_skill_sources_then_dynamic_task_context",
        }

    def assemble(
        self,
        task_id: str,
        *,
        mode_key: str | None = None,
        has_sensei: bool = False,
        output_mode: str = "official_script",
    ) -> dict:
        bundle = self.registry.prompt_bundle(task_id, mode_key, has_sensei)
        if bundle["status"] != "ready":
            return bundle
        contract = template_contract(task_id)
        header = (
            f"你正在执行 HaloCue WritingPack {PACK_VERSION} 的 `{task_id}`。\n"
            "下列内容是本阶段唯一允许使用的 ba-writing 规则源；不要读取或臆造其他模式。\n"
            "规则文档中的旧文件路径、命令和调度工具只是来源说明，不是本轮可调用工具。\n"
            "正式资料和正文只能通过 Proposal/Diff 交给用户决定，不得声称已静默写回。\n"
            f"输出载体：{output_mode}。\n"
            f"本阶段检查项：{json.dumps(contract['checks'], ensure_ascii=False)}。"
        )
        if task_id in {"scene.draft.generate", "scene.draft.rewrite"}:
            header += (
                "\n只生成一个候选，不自评、不输出第二版。"
                "official_script 只允许 `角色: 内容` 或 `旁白: 内容` 行。"
            )
        return {
            **bundle,
            "pack_version": PACK_VERSION,
            "template_version": contract["version"],
            "checks": contract["checks"],
            "system_prompt": header + "\n\n" + bundle["system_rules"],
        }

    def assemble_scene_request(
        self,
        task_id: str,
        context: dict,
        *,
        payload: dict | None = None,
        output_mode: str = "official_script",
    ) -> dict:
        """Build the deterministic dynamic half of a scene model request."""
        rules = context.get("rules") if isinstance(context.get("rules"), dict) else {}
        brief = context.get("brief") if isinstance(context.get("brief"), dict) else {}
        scene_contract = context.get("scene_contract") if isinstance(context.get("scene_contract"), dict) else {}
        has_sensei = bool(
            scene_contract.get("has_sensei")
            if "has_sensei" in scene_contract
            else brief.get("has_sensei", False)
        )
        assembled = self.assemble(
            task_id,
            mode_key=rules.get("mode_key") or brief.get("mode"),
            has_sensei=has_sensei,
            output_mode=output_mode,
        )
        if assembled.get("status") != "ready":
            return assembled
        scene_pack = context.get("scene_writing_pack")
        if not isinstance(scene_pack, dict) or scene_pack.get("schema_version") != "scene-writing-pack/1.0":
            return {
                **assembled,
                "status": "unavailable",
                "missing_files": ["scene-writing-pack/1.0"],
                "error_code": "scene_writing_pack_unavailable",
            }
        dynamic_input = {
            "scene_writing_pack": scene_pack,
            "task_payload": payload or {},
        }
        input_json = json.dumps(dynamic_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_digest = "sha256:" + hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        return {
            **assembled,
            "user_prompt": (
                f"HaloCue 动态场景输入（{scene_pack['schema_version']}，{scene_pack['digest']}）：\n"
                + json.dumps(dynamic_input, ensure_ascii=False, indent=2)
            ),
            "fingerprints": {
                "static_rule_pack": (
                    assembled["source_digest"]
                    if str(assembled["source_digest"]).startswith("sha256:")
                    else f"sha256:{assembled['source_digest']}"
                ),
                "scene_writing_pack": scene_pack["digest"],
                "prompt_input": input_digest,
            },
        }

    def assemble_work_review_request(self, task_id: str, review_pack: dict) -> dict:
        """Build the cache-stable prompt boundary for work-level review agents."""
        if task_id not in {"continuity.review", "release.review"}:
            raise ValueError(f"unsupported work review task: {task_id}")
        if not isinstance(review_pack, dict) or review_pack.get("schema_version") != "work-review-pack/1.0":
            return {
                "status": "unavailable",
                "missing_files": ["work-review-pack/1.0"],
                "error_code": "work_review_pack_unavailable",
            }
        mode_key = review_pack.get("mode_key")
        assembled = self.assemble(
            task_id,
            mode_key=mode_key,
            has_sensei=bool(review_pack.get("has_sensei")),
            output_mode="review_findings",
        )
        if assembled.get("status") != "ready":
            return assembled
        dynamic_input = {"work_review_pack": review_pack}
        input_json = json.dumps(dynamic_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_digest = "sha256:" + hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        return {
            **assembled,
            "user_prompt": (
                f"HaloCue 作品级审查输入（{review_pack['schema_version']}，{review_pack['digest']}）：\n"
                + json.dumps(dynamic_input, ensure_ascii=False, indent=2)
            ),
            "fingerprints": {
                "static_rule_pack": (
                    assembled["source_digest"]
                    if str(assembled["source_digest"]).startswith("sha256:")
                    else f"sha256:{assembled['source_digest']}"
                ),
                "work_review_pack": review_pack["digest"],
                "prompt_input": input_digest,
            },
        }
