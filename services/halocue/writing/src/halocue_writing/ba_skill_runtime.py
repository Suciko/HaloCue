from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .workflow_pack import (
    COMMON_RULES,
    ENGINE_RULE_SOURCE,
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
        output_mode: str | None = None,
    ) -> list[str]:
        paths = list(WORKFLOW_RULE_SOURCES.get(task_id, ["SKILL.md", *COMMON_RULES]))
        if mode_key in MODE_SOURCES:
            paths.append(MODE_SOURCES[mode_key])
        if has_sensei:
            paths.append("knowledge/老师在场规则.md")
        if output_mode == "engine_script":
            paths.append(ENGINE_RULE_SOURCE)
        return list(dict.fromkeys(paths))

    def compile(
        self,
        mode_key: str | None = None,
        has_sensei: bool = False,
        *,
        task_id: str | None = None,
        output_mode: str | None = None,
    ) -> dict:
        paths = self.required_paths(
            mode_key,
            has_sensei,
            task_id=task_id,
            output_mode=output_mode,
        )
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
        # engine_script is an optional output surface. Include its contract in
        # the immutable snapshot when supplied, but do not make ordinary
        # writing health depend on an AA-only document.
        engine_path = self._file_record(ENGINE_RULE_SOURCE)
        if engine_path["status"] == "available":
            files.append(engine_path)
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
        *,
        output_mode: str | None = None,
    ) -> dict:
        selected = self.required_paths(
            mode_key,
            has_sensei,
            task_id=task_id,
            output_mode=output_mode,
        )
        manifest = self._manifest
        if not manifest or manifest.get("status") != "ready" or self._repo is None:
            contract = self.compile(
                mode_key,
                has_sensei,
                task_id=task_id,
                output_mode=output_mode,
            )
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
        bundle = self.registry.prompt_bundle(
            task_id,
            mode_key,
            has_sensei,
            output_mode=output_mode,
        )
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
        bundle = self.registry.prompt_bundle(
            task_id,
            mode_key,
            has_sensei,
            output_mode=output_mode,
        )
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
        stage_guidance = self._stage_guidance(task_id)
        if stage_guidance:
            header += "\n\n本阶段额外边界：\n" + "\n".join(
                f"- {item}" for item in stage_guidance
            )
        return {
            **bundle,
            "pack_version": PACK_VERSION,
            "template_version": contract["version"],
            "checks": contract["checks"],
            "stage_guidance": stage_guidance,
            "output_mode": output_mode,
            "system_prompt": header + "\n\n" + bundle["system_rules"],
        }

    @staticmethod
    def _stage_guidance(task_id: str) -> list[str]:
        """Keep planning prompts useful without importing the whole writer SOP."""
        guidance = {
            "brief.build": [
                "当前只澄清创意简报：不写正文、不创建正式人物卡/世界观卡、不声称已经保存。",
                "把用户原话、原作证据、用户私设和 Agent 推断分开标记；不确定内容只能作为待核对问题。",
                "一次最多提出两个真正会改变方向的关键问题；其余细节留到下一轮，避免把讨论变成表单。",
                "只选择一个主写作模式；无法判断时先询问用户，不要混合加载多个模式。",
            ],
            "blueprint.generate": [
                "当前只整理 StoryBlueprint 候选，不写正文、不修改正式资料；输出必须等待用户采纳。",
                "方向、人物和世界观边界必须区分已确认事实、用户选择和创作提案，不得把推断升格为事实。",
                "保留单一主写作模式，并让中央冲突与至少一个可观察的关系/局面变化对应；不要输出空泛主题口号。",
                "候选只保留足够让作者作决定的字段；不要重复整份资料或暴露 Provider、Run、Revision 等内部字段。",
            ],
            "structure.plan": [
                "当前只规划卷、章、场景结构；不得写正文或替换已确认的全作方向。",
                "每个场景必须有可观察的局面变化或关系变化；没有变化的流程场景应合并或删除。",
                "只提出一份可审查的结构候选，稳定 ID 和原有结构必须保留，破坏性调整要明确标记。",
            ],
            "chapter.plan": [
                "当前只规划目标章节内部的节拍与场景卡；不得重写全作 StoryBlueprint 或直接生成正文。",
                "每场写清刺激、选择、plot_delta、emotion_delta 或 residue 中至少一项可验证变化，并说明下一场承接。",
                "只提出一份章内细纲候选，问题与取舍保持简短，让作者能先决定方向再补细节。",
            ],
        }
        return guidance.get(task_id, [])

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
        requested_render_mode = str(scene_contract.get("render_mode") or output_mode).strip()
        if requested_render_mode not in {"official_script", "text_reading", "engine_script"}:
            requested_render_mode = output_mode
        assembled = self.assemble(
            task_id,
            mode_key=rules.get("mode_key") or brief.get("mode"),
            has_sensei=has_sensei,
            output_mode=requested_render_mode,
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
        conditional_guidance = self._scene_conditional_guidance(
            scene_contract,
            output_mode=requested_render_mode,
        )
        dynamic_input = {
            "scene_writing_pack": scene_pack,
            "task_payload": payload or {},
            "conditional_guidance": conditional_guidance,
        }
        input_json = json.dumps(dynamic_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_digest = "sha256:" + hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        system_prompt = assembled["system_prompt"]
        if conditional_guidance:
            system_prompt += "\n\n本场条件化写作规则（只执行命中的条目）：\n" + "\n".join(
                f"- {item}" for item in conditional_guidance
            )
        return {
            **assembled,
            "system_prompt": system_prompt,
            "conditional_guidance": conditional_guidance,
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

    @staticmethod
    def _scene_conditional_guidance(
        scene_contract: dict,
        *,
        output_mode: str,
    ) -> list[str]:
        """Translate scene-level triggers into short, auditable guardrails.

        The source Skill intentionally keeps these rules conditional.  The
        product must therefore inject the mechanism only when the scene
        contract calls for it, instead of paying the context cost (and
        confusing the model) with the full SOP on every request.
        """
        if not isinstance(scene_contract, dict):
            return []
        guidance: list[str] = []
        emotion = str(scene_contract.get("emotion_delta") or "").casefold()
        if any(token in emotion for token in ("被击中", "震撼", "灵感爆发", "兴奋失控")):
            guidance.append(
                "本场是被击中型兴奋：用短句爆破和认知确认递进承载注意变化；"
                "禁止一开口报菜名或写成连续美术技法鉴赏稿，技法只能作为零碎、可观察的创作反应。"
            )

        ending = " ".join(
            str(scene_contract.get(key) or "") for key in ("ending_payoff", "residue")
        ).casefold()
        if any(token in ending for token in ("道歉", "自我总结", "为失态收场", "失态")):
            guidance.append(
                "收尾包含道歉或失态：道歉只针对一个具体行为；角色不得在现场总结自己的弧光、"
                "动机或本场主题，让主题由行为和后果呈现。"
            )
        if any(token in emotion + " " + ending for token in ("越界", "隐私暴露", "真实受伤", "伤害", "不适")):
            guidance.append(
                "玩笑或试探已经造成真实越界/伤害：后果出现后立即停止喜剧升级，先写停止、退开、归还或承担；"
                "安全重新建立前不得用笑话盖过伤害。"
            )

        variant = str(
            scene_contract.get("literary_voice_variant")
            or scene_contract.get("literary_voice")
            or scene_contract.get("prompt_variant")
            or ""
        ).strip().casefold()
        variant_rules = {
            "literary_voice_v4_2": "使用信息归属和话轮承接：为事实标明首次载体与后续用途，为每轮标明刺激、响应者和实际变化；不要把它们翻译成逐句台词。",
            "literary_voice_v4_3": "在 V4.2 基础上按关系距离组织老师接话；老师不是选项按钮、审讯者、说明员或价值总结者。",
            "literary_voice_v4_4": "在 V4.3 基础上先判断信息是否必须由旁白承载；相邻对白已经证明的动作不重复，连续操作压成改变局面的结果。",
            "literary_voice_v4_5": "在 V4.4 基础上让独立短句承载态度、判断、疑问、选择或会改变下一句的迟疑；纯听见确认不单独占一轮。",
            "literary_voice_v4_6": "启用留白实验：保留可观察动作、学生声音和关系承接，不把潜台词说透，不把回收写成漂亮总结；该变体仍需人工复核。",
        }
        if variant in variant_rules:
            guidance.append(variant_rules[variant])

        if scene_contract.get("information_ownership"):
            guidance.append("按 scene_contract.information_ownership 的事实载体和后续用途组织信息，不新增未声明事实。")
        if scene_contract.get("exchange_chain"):
            guidance.append("按 scene_contract.exchange_chain 保留刺激到响应的因果承接，不把角色轮流发言当作对话节拍。")
        if output_mode == "engine_script":
            guidance.append("当前输出为 engine_script：只写已声明演出资源能够表达的画面/对白层，不使用 official_script 的默认行格式假设。")
        elif output_mode == "text_reading":
            guidance.append("当前输出为 text_reading：可写读者必须看见的叙述和空间关系，但仍不得把角色心理总结成作者旁白。")
        return guidance

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
