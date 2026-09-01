from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request

from .agent_tools import AgentToolRegistry
from .errors import DomainError


@dataclass(frozen=True)
class ProviderUsageSnapshot:
    """Normalized usage: input_tokens always includes cache reads and writes."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated_cost: float | None = None
    usage_status: str = "not_reported"
    cache_status: str = "unknown"

    def as_dict(self) -> dict:
        return {
            "schema_version": "provider-usage/1.0",
            "input_tokens_semantics": "total_including_cache",
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "estimated_cost": self.estimated_cost,
            "usage_status": self.usage_status,
            "cache_status": self.cache_status,
        }


@dataclass(frozen=True)
class ProviderToolCall:
    id: str
    name: str
    arguments_json: str

    def as_dict(self) -> dict:
        return {"id": self.id, "tool": self.name, "arguments": json.loads(self.arguments_json)}


@dataclass(frozen=True)
class PendingToolExchange:
    protocol: str
    user_prompt: str
    assistant_json: str
    tool_calls: tuple[ProviderToolCall, ...]
    # Native protocol history before ``assistant_json``.  A model can need a
    # second, read-only lookup after seeing the first result, so retaining just
    # the immediately preceding tool exchange would make the next request
    # invalid for both OpenAI-compatible and Anthropic APIs.
    prior_messages_json: str = "[]"


@dataclass(frozen=True)
class LLMCallResult:
    text: str
    reasoning_content: str
    tool_calls: tuple[ProviderToolCall, ...]
    usage: ProviderUsageSnapshot
    pending_exchange: PendingToolExchange | None = None


class WritingProvider(ABC):
    kind: str
    display_name: str
    is_simulation: bool

    @abstractmethod
    def generate_blueprint(self, brief: dict, analysis_context: dict | None = None) -> dict: ...

    @abstractmethod
    def generate_scene(self, context: dict) -> str: ...

    @abstractmethod
    def rewrite_scene(self, context: dict, base_text: str, instruction: str) -> str: ...

    @abstractmethod
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict: ...

    @abstractmethod
    def generate_chapter_plan(self, messages: list[dict], chapter_context: dict) -> dict: ...

    @abstractmethod
    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict: ...

    @abstractmethod
    def extract_memory_bundle(self, memory_context: dict) -> dict: ...

    def sweep_memory_bundle(self, memory_context: dict) -> dict:
        return self.extract_memory_bundle(memory_context)

    @abstractmethod
    def review_scene(self, context: dict, text: str) -> list[dict]: ...

    def review_continuity(self, context: dict) -> list[dict]:
        return []

    def review_release(self, context: dict) -> list[dict]:
        return []

    def capability_descriptor(self) -> dict:
        if self.is_simulation:
            return {
                "schema_version": "provider-capabilities/1.0",
                "usage": {"support": "unsupported", "source": "no_model_call"},
                "cache": {"support": "unsupported", "mode": "none"},
                "reasoning_summary": {
                    "support": "unsupported",
                    "mode": "none",
                    "hidden_chain_exposed": False,
                },
            }
        return {
            "schema_version": "provider-capabilities/1.0",
            "usage": {"support": "unknown", "source": "provider_response"},
            "cache": {"support": "unknown", "mode": "provider_specific"},
            "reasoning_summary": {
                "support": "unknown",
                "mode": "provider_specific",
                "hidden_chain_exposed": False,
            },
        }

    def descriptor(self) -> dict:
        return {
            "kind": self.kind,
            "display_name": self.display_name,
            "is_simulation": self.is_simulation,
            "can_call_model": not self.is_simulation,
            "provider": "fake" if self.is_simulation else self.kind,
            "model": "local-rules" if self.is_simulation else "",
            "settings_version": 0,
            "config_revision": "simulation",
            "config_digest": "simulation" if self.is_simulation else "",
            "capabilities": self.capability_descriptor(),
        }

    def last_usage(self) -> dict:
        return {}

    def project_commit_revision(self, projection_kind: str, projection_input: dict) -> dict:
        """Build cheap, replaceable derivatives from one pinned Revision.

        Providers may override this hook, but the default intentionally avoids a
        model call. It keeps save-time maintenance predictable and makes the
        simulation boundary explicit instead of pretending an LLM ran.
        """
        content = projection_input.get("content")
        if not isinstance(content, dict):
            content = {}
        raw_text = str(content.get("text") or "").strip()
        if not raw_text:
            raw_text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        compact = " ".join(raw_text.split())
        scene_id = projection_input.get("scene_id")
        is_scene = projection_input.get("artifact_kind") == "scene_script" and bool(scene_id)
        if projection_kind == "summary":
            output = {
                "text": compact[:360],
                "method": "deterministic_excerpt",
                "requires_model": False,
            }
        elif projection_kind == "search":
            candidates = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,12}", compact)
            terms = []
            for value in candidates:
                if value not in terms:
                    terms.append(value)
                if len(terms) >= 48:
                    break
            output = {
                "terms": terms,
                "text": compact[:4000],
                "method": "deterministic_terms",
                "requires_model": False,
            }
        elif projection_kind == "memory_followup":
            output = {
                "required": is_scene,
                "action": "memory.extract" if is_scene else None,
                "scene_id": scene_id,
                "reason": "scene_revision_committed" if is_scene else "not_scene_script",
            }
        elif projection_kind == "review_followup":
            output = {
                "required": is_scene,
                "action": "scene.review" if is_scene else None,
                "scene_id": scene_id,
                "reason": "scene_revision_committed" if is_scene else "not_scene_script",
            }
        else:
            raise DomainError(
                "commit_projection_kind_unknown",
                "未知的提交投影步骤。",
                details={"projection_kind": projection_kind},
            )
        return {
            "schema_version": "commit-projection-output/1.0",
            "kind": projection_kind,
            "source_revision_id": projection_input.get("revision_id"),
            "content": output,
            "provider": {
                "kind": self.kind,
                "is_simulation": self.is_simulation,
                "model_called": False,
            },
        }


class FakeWritingProvider(WritingProvider):
    kind = "fake"
    display_name = "本地模拟 Provider"
    is_simulation = True

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        scene = memory_context.get("scene") if isinstance(memory_context.get("scene"), dict) else {}
        manuscript = memory_context.get("manuscript") if isinstance(memory_context.get("manuscript"), dict) else {}
        blocks = manuscript.get("blocks") if isinstance(manuscript.get("blocks"), list) else []
        text = str(manuscript.get("text") or "").strip()
        block_ids = [str(item.get("id")) for item in blocks if isinstance(item, dict) and item.get("id")]
        title = str(scene.get("title") or "当前场景")
        excerpt = " ".join(text.split())[:600] or "场景正文已经形成正式修订。"
        return {
            "schema_version": "memory-bundle/1.0",
            "summary": "本地模拟只从已固定的场景正文建立可审查记忆，不调用真实模型。",
            "items": [
                {
                    "kind": "episode_memory",
                    "operation": "create",
                    "title": f"{title} · 已发生事件",
                    "summary": excerpt,
                    "details": {"scene_title": title},
                    "scope_type": "work",
                    "scope_id": memory_context.get("work_id"),
                    "confidence_status": "open",
                    "source_block_ids": block_ids,
                },
                {
                    "kind": "scene_state_snapshot",
                    "operation": "create",
                    "title": f"{title} · 场景结束状态",
                    "summary": "记录本场正式正文结束时的可见状态，供下一场装配时回查。",
                    "details": {"scene_title": title, "text_excerpt": excerpt},
                    "scope_type": "scene",
                    "scope_id": scene.get("id"),
                    "confidence_status": "open",
                    "source_block_ids": block_ids,
                },
            ],
            "simulation_notice": "本地模拟 Provider 只验证记忆 Proposal 流程。",
        }

    def sweep_memory_bundle(self, memory_context: dict) -> dict:
        scenes = memory_context.get("scenes") if isinstance(memory_context.get("scenes"), list) else []
        scene = scenes[-1] if scenes else {}
        manuscript = scene.get("manuscript") if isinstance(scene.get("manuscript"), dict) else {}
        text = str(manuscript.get("text") or "").strip()
        block_ids = [
            str(item.get("id"))
            for item in manuscript.get("blocks", [])
            if isinstance(item, dict) and item.get("id")
        ]
        title = str(memory_context.get("chapter", {}).get("title") or "当前章节")
        excerpt = " ".join(text.split())[:600] or "章节场景已经形成正式修订。"
        return {
            "schema_version": "memory-bundle/1.0",
            "summary": "本地模拟只验证章节级记忆清扫候选，不调用真实模型。",
            "items": [{
                "kind": "episode_memory",
                "operation": "create",
                "title": f"{title} · 章节进展",
                "summary": excerpt,
                "details": {"chapter_title": title},
                "scope_type": "chapter",
                "scope_id": memory_context.get("chapter", {}).get("id"),
                "confidence_status": "open",
                "source_refs": [{"scene_id": scene.get("id"), "source_block_ids": block_ids}],
            }],
            "simulation_notice": "本地模拟 Provider 只验证章节级记忆清扫流程。",
        }

    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        blueprint = structure_context.get("story_blueprint") if isinstance(structure_context.get("story_blueprint"), dict) else {}
        direction = [str(item).strip() for item in blueprint.get("direction", []) if str(item).strip()]
        premise = str(blueprint.get("premise") or "让主要人物在一次事件中完成可见变化。").strip()
        beats = direction[:3] or [premise]
        chapters = []
        for index, beat in enumerate(beats, start=1):
            chapters.append({
                "title": f"第{index}章 · {'开端' if index == 1 else '推进' if index < len(beats) else '回应'}",
                "goal": beat,
                "scenes": [{
                    "title": f"场景 {index}-1",
                    "goal": beat,
                    "location": "待在逐场写作前确认",
                    "stop_boundary": "本场目标成立后停止",
                }],
            })
        return {
            "schema_version": "story-structure-plan/1.0",
            "volumes": [{"title": "第一卷", "purpose": premise, "chapters": chapters}],
            "status": "proposed",
            "simulation_notice": "本地模拟 Provider 只用于验证可替换流程，未调用真实模型。",
        }

    def generate_chapter_plan(self, messages: list[dict], chapter_context: dict) -> dict:
        user_notes = [
            str(message.get("text", "")).strip()
            for message in messages
            if message.get("role") == "user" and str(message.get("text", "")).strip()
        ]
        chapter_title = str(chapter_context.get("chapter_title") or "当前章节")
        latest = user_notes[-1] if user_notes else "先明确本章要完成的变化。"
        return {
            "schema_version": "chapter-plan/1.0",
            "title": f"{chapter_title}细纲",
            "chapter_goal": latest,
            "beats": user_notes[-4:] or [latest],
            "continuity_notes": ["承接已确认的全作方向和此前正式正文。"],
            "status": "proposed",
            "simulation_notice": "本地模拟 Provider 只用于验证可替换流程，未调用真实模型。",
        }

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        task_contract = work_context.get("task_contract") or {}
        task_id = task_contract.get("id", "brief.build")
        latest = next(
            (
                str(message.get("text", "")).strip()
                for message in reversed(messages)
                if message.get("role") == "user" and str(message.get("text", "")).strip()
            ),
            "",
        )
        idea = str(work_context.get("idea") or latest).strip()
        lower = latest.lower()
        user_turns = [
            str(message.get("text", "")).strip()
            for message in messages
            if message.get("role") == "user" and str(message.get("text", "")).strip()
        ]

        tool_activity = [
            {"tool": "load_workflow_template", "label": "加载任务契约", "status": "succeeded"},
            {"tool": "read_work_context", "label": "读取作品上下文", "status": "succeeded"},
        ]
        artifact_preview = None

        import re
        import_mode = str((task_contract.get("task_scope") or {}).get("import_mode") or "").strip()
        if import_mode in {"story_to_script", "aap_to_script"}:
            import_preview = (task_contract.get("task_scope") or {}).get("import_preview")
            import_preview = import_preview if isinstance(import_preview, dict) else {}
            source_type = "aap" if import_mode == "aap_to_script" else "story_document"
            source_label = "AAP 工程" if import_mode == "aap_to_script" else "小说或文稿"
            scenes = import_preview.get("scenes") if isinstance(import_preview.get("scenes"), list) else []
            counts = import_preview.get("counts") if isinstance(import_preview.get("counts"), dict) else {}
            warnings = import_preview.get("warnings") if isinstance(import_preview.get("warnings"), list) else []
            citations = []
            document_context = work_context.get("document_context")
            if isinstance(document_context, dict):
                citations = [
                    {
                        "display_label": str(item.get("display_label") or "")[:160],
                        "chunk_id": str(item.get("chunk_id") or "")[:120],
                        "paragraph_ids": [str(value)[:40] for value in (item.get("paragraph_ids") or [])[:20]],
                    }
                    for item in (document_context.get("citations") or [])[:8]
                    if isinstance(item, dict)
                ]
            review_scenes = [
                {
                    "title": str(item.get("title") or "未命名场景")[:160],
                    "line_count": int(item.get("line_count") or item.get("paragraph_count") or 0),
                }
                for item in scenes[:30] if isinstance(item, dict)
            ]
            manual_followups = [
                "确认章节与场景的边界，再决定是否整理为正式剧本候选。",
                "补充无法从来源确定的角色、背景或舞台动作。",
            ]
            text = (
                f"我已把这份{source_label}接入当前 Agent 对话，并完成第一轮结构检查。"
                "下面是转换审查清单；它仍然只是导入候选，不会直接改动正式作品。"
            )
            import_review = {
                "schema_version": "script-import-review/1.0",
                "mode": import_mode,
                "source_type": source_type,
                "source_label": source_label,
                "chapters": [{"title": "待 Agent 根据来源确认", "scene_count": int(counts.get("scenes") or len(review_scenes))}],
                "scenes": review_scenes,
                "character_mappings": [],
                "unrecognized_nodes": [str(item)[:320] for item in warnings[:20]],
                "manual_followups": manual_followups,
                "source_citations": citations,
            }
            return {
                "text": text,
                "questions": ["先确认章节和场景边界，还是先补齐角色映射？"],
                "ready_for_proposal": True,
                "ready_to_organize": True,
                "import_review": import_review,
                "reasoning_summary": "导入内容先经过结构、来源和人工补充项审查，再进入剧本候选，不直接写回正式作品。",
                "tool_activity": tool_activity,
                "simulation_notice": "当前使用的是本地模拟 Provider；真实模型会在同一任务契约下补全剧本候选。",
            }
        char_match = re.search(r"《([^》]+)》.*(?:角色|人物)", latest) or re.search(r"(?:角色|人物).*《([^》]+)》", latest)
        world_match = re.search(r"《([^》]+)》.*(?:地点|世界观|设定)", latest) or re.search(r"(?:地点|世界观|设定).*《([^》]+)》", latest)
        rule_match = re.search(r"《([^》]+)》.*(?:世界规则|规则)", latest) or re.search(r"(?:世界规则|规则).*《([^》]+)》", latest)
        fact_match = re.search(r"(?:事实|记住|规则)[：:]?\s*(.+)", latest)

        if char_match:
            char_name = char_match.group(1).strip()
            artifact_preview = {
                "kind": "character_card",
                "title": char_name,
                "status": "discussion_draft",
                "content": {
                    "name": char_name,
                    "summary": f"由对话讨论生成的自定义角色卡草稿：{latest}",
                }
            }
            tool_activity.append({"tool": "draft_character_card", "label": "生成角色卡草稿", "status": "succeeded"})
        elif rule_match:
            rule_name = rule_match.group(1).strip()
            rule_text = re.split(r"[：:]", latest, maxsplit=1)[-1].strip() or latest
            artifact_preview = {
                "kind": "world_rule",
                "title": rule_name,
                "status": "discussion_draft",
                "content": {
                    "name": rule_name,
                    "text": rule_text,
                    "scope": "work",
                    "confidence_status": "open",
                },
            }
            tool_activity.append({"tool": "draft_world_rule", "label": "生成世界规则草稿", "status": "succeeded"})
        elif world_match:
            world_name = world_match.group(1).strip()
            artifact_preview = {
                "kind": "world_card",
                "title": world_name,
                "status": "discussion_draft",
                "content": {
                    "name": world_name,
                    "summary": f"由对话讨论生成的世界观设定草稿：{latest}",
                }
            }
            tool_activity.append({"tool": "draft_world_card", "label": "生成世界观草稿", "status": "succeeded"})
        elif fact_match and fact_match.group(1).strip().rstrip("。！？"):
            fact_text = fact_match.group(1).strip().rstrip("。！？")
            artifact_preview = {
                "kind": "canon_fact",
                "title": "作品事实",
                "status": "discussion_draft",
                "content": {
                    "text": fact_text,
                    "source": "作品主对话（待确认）",
                    "confidence_status": "open",
                },
            }
            tool_activity.append({"tool": "draft_canon_fact", "label": "生成作品事实草稿", "status": "succeeded"})

        if task_id == "canon.assemble":
            memory_context = work_context.get("scene_memory_context") if isinstance(work_context.get("scene_memory_context"), dict) else {}
            scene = memory_context.get("scene") if isinstance(memory_context.get("scene"), dict) else {}
            contract = scene.get("contract") if isinstance(scene.get("contract"), dict) else {}
            scene_title = str(scene.get("title") or "当前场景")
            goal = str(contract.get("goal") or "本场正文已形成新的可追溯状态").strip().rstrip("。！？")
            revision_id = str(scene.get("revision_id") or "")
            fact_text = f"在《{scene_title}》结束时，{goal}。"
            artifact_preview = {
                "kind": "canon_fact",
                "title": "作品事实",
                "status": "discussion_draft",
                "content": {
                    "text": fact_text,
                    "source": f"场景修订 {revision_id}",
                    "source_refs": [f"场景修订 {revision_id}"],
                    "confidence_status": "open",
                },
            }
            tool_activity.append({"tool": "draft_canon_fact", "label": "整理本场资料变化草稿", "status": "succeeded"})
            text = (
                f"我已固定读取《{scene_title}》的正式正文修订，并整理出一条作品事实草稿。"
                "这只是资料候选；你可以继续要求我检查人物关系或伏笔，也可以先把这条事实整理成 Proposal。"
            )
            questions = ["这场是否还改变了人物之间的关系或知情边界？"]
            ready = True
        elif task_id == "structure.plan":
            text = (
                "故事方向已经确认。现在先讨论卷、章和场景各自要完成的变化，"
                "再由你确认结构；我不会把聊天内容直接改成章节或场景。"
            )
            questions = ["第一卷结束时，人物关系应当发生什么可见变化？", "开场这一章需要先让读者看见哪一个具体问题？"]
            ready = True
        elif task_id == "chapter.plan":
            chapter_title = str(task_contract.get("task_scope", {}).get("chapter_title") or "当前章节")
            text = (
                f"现在只讨论《{chapter_title}》内部的细纲：本章要完成的变化、场景节拍和承接点。"
                "全作方向仍来自作品栏目；这里不会重写 StoryBlueprint，也不会静默建立场景。"
            )
            questions = ["本章结束时，人物或事实必须发生什么变化？", "这一章要承接上一段正文的哪个状态？"]
            ready = True
        elif task_id in {"scene.draft.generate", "scene.draft.rewrite"}:
            scene_context = (
                work_context.get("scene_conversation_context")
                if isinstance(work_context.get("scene_conversation_context"), dict)
                else {}
            )
            scene = scene_context.get("scene") if isinstance(scene_context.get("scene"), dict) else {}
            contract = scene.get("contract") if isinstance(scene.get("contract"), dict) else {}
            scene_title = str(scene.get("title") or task_contract.get("task_scope", {}).get("scene_title") or "当前场景")
            goal = str(contract.get("goal") or "完成本场合同中的可见变化")
            recent_constraints = "；".join(user_turns[-3:]) or "尚未提供具体约束"
            manuscript = scene_context.get("current_manuscript")
            if task_id == "scene.draft.rewrite" and isinstance(manuscript, dict):
                revision_id = str(manuscript.get("revision_id") or "当前修订")
                text = (
                    f"我正在只读检查《{scene_title}》的正式正文 {revision_id}。"
                    f"本场目标是“{goal}”；最近几轮作者约束是：{recent_constraints}。"
                    "这些约束会一起进入改写候选，未被后续消息否定的要求继续保留，正文不会在讨论中直接改变。"
                )
            else:
                text = (
                    f"我正在围绕《{scene_title}》讨论第一份正文候选。"
                    f"本场目标是“{goal}”；最近几轮作者约束是：{recent_constraints}。"
                    "我会把这些约束整理进同一份候选，讨论本身不会创建或覆盖正式正文。"
                )
            questions = ["还有哪些对白语气、节奏或停止边界必须保持？"]
            ready = True
        elif task_id == "release.review":
            text = (
                "所有场景已有已采纳正文。现在的任务是核对连续性、人物一致性和未决伏笔，"
                "Gate 通过后才可以冻结不可变的 ScriptRelease。"
            )
            questions = ["是否有需要作为全篇问题处理的角色或伏笔？"]
            ready = True
        elif any(token in lower for token in ("整理", "形成方案", "生成方案", "定下来")):
            text = "我已经把目前的讨论整理成一份可审查方案。它仍是候选，只有你采纳后才会写入正式 Brief 和故事方向。"
            questions = []
            ready = True
        elif len(user_turns) >= 2 or len(latest) >= 18:
            text = f"你提到了“{latest[:36]}”。结合全作想法，我们可以在开场用一个小事件把人物的处境拉开，再逐步交代原因。"
            questions = ["你希望谁最先意识到异常？", "这次事件要保持完全私密，还是会被更多人察觉？"]
            ready = True
        else:
            text = f"我们先围绕“{idea}”理清故事主线。你希望这篇二创从谁的视角先进入，第一幕最关键的选择是什么？"
            questions = ["主要出场角色是谁？", "故事的基调更偏向日常互动、战斗悬疑还是搞笑闹剧？"]
            ready = False

        res = {
            "text": text,
            "questions": questions,
            "ready_for_proposal": ready,
            "ready_to_organize": ready,
            "reasoning_summary": (
                "先按当前阶段读取作品正式上下文，再判断这轮应继续追问、生成资料讨论草稿，"
                "还是已经足够整理为 Proposal。"
            ),
            "tool_activity": tool_activity,
            "simulation_notice": "当前使用的是本地模拟 Provider；可在设置中接入真实大模型进行智能创作。",
        }
        if artifact_preview:
            res["artifact_preview"] = artifact_preview
        return res

    def generate_blueprint(self, brief: dict, analysis_context: dict | None = None) -> dict:
        idea = brief.get("idea", "未命名的故事想法")
        characters = brief.get("characters") or []
        narrator_request = f"{idea} {brief.get('constraints', '')}".lower()
        narrator_only = any(token in narrator_request for token in (
            "纯旁白", "只用旁白", "仅用旁白", "不出现对白角色", "narrator-only", "narrator only",
        ))
        analysis_context = analysis_context or {}
        runtime_characters = analysis_context.get("runtime_character_cards", [])
        mentioned_cards = [
            card
            for card in runtime_characters
            if card.get("name") in characters or card.get("name") in idea
        ]
        if narrator_only:
            characters = []
        elif not characters:
            characters = [card.get("name") for card in mentioned_cards if card.get("name")]
        if not characters and not narrator_only:
            if "爱丽丝" in idea or "凯伊" in idea:
                characters = ["爱丽丝", "凯伊"]
            elif "日奈" in idea or "亚子" in idea:
                characters = ["日奈", "亚子"]
            else:
                characters = ["爱丽丝", "凯伊"]
        primary_mode = "text_reading" if narrator_only else "bond_short"
        secondary_modes = []
        normalized_idea = idea.lower()
        if any(token in normalized_idea for token in ("战斗", "突入", "任务", "敌人", "防线", "行动", "枪战")):
            primary_mode = "main_battle"
            secondary_modes.append("bond_short")
        elif any(token in normalized_idea for token in ("喜剧", "搞笑", "闹剧", "日常")):
            primary_mode = "long_comedy"
            secondary_modes.append("bond_short")
        elif any(token in normalized_idea for token in ("小说", "内心", "叙述", "阅读")):
            primary_mode = "text_reading"
        if any(token in normalized_idea for token in ("异常", "线索", "调查", "秘密", "谜")) and primary_mode != "bond_short":
            secondary_modes.append("bond_short")
        if not secondary_modes and any(token in normalized_idea for token in ("异常", "线索", "调查", "秘密", "谜")):
            secondary_modes.append("main_battle")
        sensei = "present" if any(token in normalized_idea for token in ("老师", "sensei")) else "absent"
        world = analysis_context.get("world", {"label": "尚未建立世界观基础", "detail": "当前作品没有可供分析的世界观条目。"})
        return {
            "title": f"围绕“{idea[:24]}”的故事方向",
            "premise": idea,
            "theme": "在具体选择中确认彼此，而不是由旁白替人物总结关系。",
            "central_conflict": (
                "在有限篇幅内只用旁白交代环境变化和行动结果。"
                if narrator_only
                else f"{characters[0]}必须处理眼前的异常，同时避免让真实目的过早暴露。"
            ),
            "direction": [
                "先用可见的小问题建立场景压力",
                "让人物的局部目标互相干扰并产生选择",
                "在必要事实成立后停止，不追加主题升华",
            ],
            "characters": characters,
            "narrator_only": narrator_only,
            "mode": primary_mode,
            "status": "proposed",
            "recommendations": {
                "primary_scene_mode": primary_mode,
                "secondary_scene_modes": secondary_modes,
                "character_card_ids": [card["id"] for card in mentioned_cards],
                "sensei_presence": sensei,
                "world_basis": world,
            },
            "simulation_notice": "结构由本地 Fake Provider 生成，仅用于验证工作流。",
        }

    def generate_scene(self, context: dict) -> str:
        contract = context["scene_contract"]
        characters = [card.get("name") for card in context.get("runtime_character_cards", []) if card.get("name")]
        if not characters:
            characters = context["brief"].get("characters") or []
        if not characters:
            location = contract.get("location") or "现场"
            goal = contract.get("goal") or "确认眼前发生了什么"
            return (
                f"旁白: {location}里，异常仍停留在能够确认的范围内。\n"
                f"旁白: 本场先完成“{goal}”，没有替尚未建立人物卡的角色发言。\n"
            )
        first = characters[0]
        second = characters[1] if len(characters) > 1 else first
        goal = contract.get("goal") or "确认眼前发生了什么"
        location = contract.get("location") or "活动室"
        return "\n".join(
            [
                f"旁白: {location}里，只剩桌上的提示灯还亮着。",
                f"{first}: 先别碰。它刚才明明没有亮。",
                f"{second}: 我还什么都没做。你是不是已经有结论了？",
                f"{first}: 没有结论。只是如果目标是“{goal}”，现在停下来比较快。",
                f"{second}: 好，那我不碰。你来告诉我第一步看哪里。",
                f"旁白: {first}把手收了回来，提示灯又闪了一次。",
            ]
        ) + "\n"

    def rewrite_scene(self, context: dict, base_text: str, instruction: str) -> str:
        contract = context["scene_contract"]
        cards = context.get("runtime_character_cards", [])
        characters = [card.get("name") for card in cards if card.get("name")]
        first = characters[0] if characters else "角色"
        anchor = next(
            (
                item
                for card in cards
                if card.get("name") == first
                for item in card.get("voice_anchors", [])
                if item
            ),
            "先确认眼前的情况。",
        )
        location = contract.get("location") or "现场"
        lines = [
            line.rstrip() if ":" in line else f"旁白: {line.rstrip()}"
            for line in str(base_text).splitlines()
            if line.strip()
        ]
        if not lines:
            return self.generate_scene(context)
        lowered = instruction.lower()
        if any(token in lowered for token in ("节奏", "紧凑", "缩短", "收束")):
            revision_line = f"旁白: {location}里，没有人把判断说得太满，下一步已经留在眼前。"
        elif any(token in lowered for token in ("ooc", "人物", "语气", "对白")):
            revision_line = f"{first}: {anchor}"
        else:
            revision_line = f"旁白: {location}里的停顿被保留下来，所有人先回到眼前能确认的事。"
        if lines[-1] != revision_line:
            lines.append(revision_line)
        return "\n".join(lines) + "\n"

    def review_scene(self, context: dict, text: str) -> list[dict]:
        return []


class LLMWritingProvider(WritingProvider):
    """Real LLM Provider supporting OpenAI-compatible and Anthropic protocols."""

    kind = "llm"
    is_simulation = False
    request_attempts = 3

    def __init__(self, credentials: dict, prompt_assembler=None):
        self.credentials = credentials
        self.provider_type = credentials.get("provider", "openai")
        self.base_url = credentials.get("base_url", "")
        self.model = credentials.get("model", "gpt-4o")
        self.api_key = credentials.get("api_key", "")
        self.max_tokens = int(credentials.get("max_tokens", 8192))
        self.timeout = int(credentials.get("timeout", 120))
        self.display_name = f"{self.model} ({self.provider_type})"
        # Gemini 3 OpenAI-compatible gateways commonly reserve `max_tokens`
        # for hidden reasoning and return an empty public answer. Their
        # compatible output budget is exposed as `max_completion_tokens`.
        self.token_limit_parameter = (
            "max_completion_tokens"
            if self.provider_type == "openai" and self.model.lower().startswith("gemini-3")
            else "max_tokens"
        )
        self._thread_state = threading.local()
        self.prompt_assembler = prompt_assembler
        self.input_cost_per_million = float(credentials.get("input_cost_per_million") or 0)
        self.output_cost_per_million = float(credentials.get("output_cost_per_million") or 0)
        self.cache_read_cost_multiplier = float(credentials.get("cache_read_cost_multiplier") or 0.1)
        self.cache_write_cost_multiplier = float(credentials.get("cache_write_cost_multiplier") or 1.25)
        declared_cache_support = str(credentials.get("cache_support") or "").strip().lower()
        if declared_cache_support in {"supported", "unsupported", "unknown"}:
            self.cache_support = declared_cache_support
        elif self.provider_type == "anthropic" or "api.openai.com" in self.base_url.lower():
            self.cache_support = "supported"
        else:
            self.cache_support = "unknown"
        requested_reasoning_mode = str(credentials.get("reasoning_mode") or "balanced").strip().lower()
        self.reasoning_mode = (
            requested_reasoning_mode
            if requested_reasoning_mode in {"balanced", "creative", "strict"}
            else "balanced"
        )

    def capability_descriptor(self) -> dict:
        return {
            "schema_version": "provider-capabilities/1.0",
            "usage": {
                "support": "supported",
                "source": "provider_response",
                "missing_response_policy": "not_reported",
            },
            "cache": {
                "support": self.cache_support,
                "mode": (
                    "explicit_ephemeral"
                    if self.provider_type == "anthropic"
                    else "provider_managed"
                    if self.cache_support == "supported"
                    else "response_reported"
                    if self.cache_support == "unknown"
                    else "none"
                ),
                "observation_values": [
                    "unsupported", "unknown", "supported_miss", "supported_hit",
                ],
            },
            "reasoning_summary": {
                "support": "supported",
                "mode": "model_authored_public_summary",
                "hidden_chain_exposed": False,
                "required_for": ["work_discussion"],
            },
        }

    def descriptor(self) -> dict:
        return {
            **super().descriptor(),
            "provider": self.provider_type,
            "model": self.model,
            "settings_version": max(1, int(self.credentials.get("settings_version") or 1)),
            "config_revision": str(self.credentials.get("config_revision") or "model-config-1"),
            "config_digest": str(self.credentials.get("config_digest") or "unversioned"),
        }

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        value = str(text or "").strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            value = "\n".join(lines).strip()
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("模型必须返回一个 JSON 对象")
        return parsed

    @staticmethod
    def _discussion_text_fallback(text: str) -> dict:
        """Keep provider-authored prose visible without treating it as a proposal.

        Discussion is an exploratory surface. Some OpenAI-compatible gateways
        return the requested public answer as prose even when the prompt asks
        for JSON. Preserve that answer for the author, but keep the formal
        proposal gate closed until a structured response is available.
        """
        visible_text = str(text or "").strip()
        return {
            "text": visible_text,
            "questions": [],
            "reasoning_summary": "模型返回了公开讨论文本；本轮未形成结构化 Proposal。",
            "ready_for_proposal": False,
        }

    def _skill_system_prompt(
        self,
        task_id: str,
        context: dict | None = None,
        *,
        output_mode: str = "official_script",
    ) -> str:
        context = context or {}
        task_contract = context.get("task_contract") if isinstance(context.get("task_contract"), dict) else {}
        skill_runtime = task_contract.get("skill_runtime") if isinstance(task_contract.get("skill_runtime"), dict) else {}
        rules = context.get("rules") if isinstance(context.get("rules"), dict) else {}
        brief = context.get("brief") if isinstance(context.get("brief"), dict) else context
        mode_key = rules.get("mode_key") or skill_runtime.get("mode_key") or brief.get("mode")
        scene_contract = context.get("scene_contract") if isinstance(context.get("scene_contract"), dict) else {}
        has_sensei = bool(
            scene_contract.get("has_sensei")
            if "has_sensei" in scene_contract
            else (brief.get("has_sensei") or skill_runtime.get("has_sensei"))
        )
        if self.prompt_assembler is None:
            raise DomainError(
                "writing_skill_unavailable",
                "真实 Provider 没有绑定 ba-writing PromptAssembler。",
                status=503,
            )
        assembled = self.prompt_assembler.assemble(
            task_id,
            mode_key=mode_key,
            has_sensei=has_sensei,
            output_mode=output_mode,
        )
        if assembled.get("status") != "ready":
            raise DomainError(
                "writing_skill_unavailable",
                "ba-writing 当前阶段规则源不完整，真实模型调用已停止。",
                status=503,
                details={
                    "task_id": task_id,
                    "missing_files": assembled.get("missing_files", []),
                },
            )
        system_prompt = assembled["system_prompt"]
        conversation_summary = context.get("conversation_summary")
        if isinstance(conversation_summary, dict) and conversation_summary.get("archived_message_count"):
            system_prompt += (
                "\n\n对话摘要可信边界：conversation_summary 只是可重建的派生对话索引，"
                "不是 WorkCanon、人物卡或 OfficialEvidence，也不能单独作为 Proposal 证据。"
                "事实冲突时，已采纳的正式产物优先；较新的原始用户消息优先于旧摘要；"
                "corrections_and_rejections 优先于它明确否决的旧约束。"
                "摘要声明有未展开上下文时，涉及正式资料的结论必须回查原始来源或向用户确认。"
            )
        return system_prompt

    def _scene_skill_request(
        self,
        task_id: str,
        context: dict,
        *,
        payload: dict | None = None,
        output_mode: str = "official_script",
    ) -> dict:
        if self.prompt_assembler is None:
            raise DomainError(
                "writing_skill_unavailable",
                "真实 Provider 没有绑定 ba-writing PromptAssembler。",
                status=503,
            )
        assembled = self.prompt_assembler.assemble_scene_request(
            task_id,
            context,
            payload=payload,
            output_mode=output_mode,
        )
        if assembled.get("status") != "ready":
            raise DomainError(
                assembled.get("error_code", "writing_skill_unavailable"),
                "ba-writing 动态场景规则包未就绪，真实模型调用已停止。",
                status=503,
                details={"missing": assembled.get("missing_files", [])},
            )
        return assembled

    def last_usage(self) -> dict:
        snapshot = getattr(self._thread_state, "last_usage", ProviderUsageSnapshot())
        return snapshot.as_dict()

    def _reasoning_instruction(self) -> str:
        mode_instructions = {
            "balanced": "在创意推进、事实约束和回答篇幅之间保持平衡。",
            "creative": "先比较多个可行方向，再选择最有表现力且不违反已确认事实的方向。",
            "strict": "优先核对来源、既有事实、人物约束和冲突；证据不足时明确保留不确定性。",
        }
        return (
            "\n\n运行模式："
            + mode_instructions[self.reasoning_mode]
            + "不要输出、转述或要求展示隐藏思维链。需要说明判断依据时，只在任务约定的 "
            "reasoning_summary 字段中给出一句面向作者、可独立验证的简短摘要；任务没有该字段时不要新增推理过程。"
        )

    def _capture_usage(self, data: dict) -> ProviderUsageSnapshot:
        usage_reported = isinstance(data.get("usage"), dict)
        usage = data.get("usage") if usage_reported else {}
        cache_signal_reported = False
        if self.provider_type == "anthropic":
            uncached_input = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            cache_signal_reported = (
                "cache_read_input_tokens" in usage
                or "cache_creation_input_tokens" in usage
            )
            cache_read = int(usage.get("cache_read_input_tokens") or 0)
            cache_write = int(usage.get("cache_creation_input_tokens") or 0)
            input_tokens = uncached_input + cache_read + cache_write
        else:
            details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            # OpenAI-compatible gateways use both the nested OpenAI field and
            # the flat Gemini relay fields.  Prefer an explicit flat value,
            # while retaining compatibility with the older nested contract.
            flat_cache_read = usage.get("prompt_cache_hit_tokens")
            flat_cache_miss = usage.get("prompt_cache_miss_tokens")
            nested_cache_read = details.get("cached_tokens")
            cache_read_value = flat_cache_read if flat_cache_read is not None else nested_cache_read
            cache_signal_reported = cache_read_value is not None or flat_cache_miss is not None
            cache_read = int(cache_read_value or 0)
            cache_write = 0
            uncached_input = (
                max(0, int(flat_cache_miss or 0))
                if flat_cache_miss is not None
                else max(0, input_tokens - cache_read)
            )
        if cache_signal_reported:
            cache_status = "supported_hit" if cache_read > 0 else "supported_miss"
        elif not usage_reported:
            cache_status = "unknown"
        elif self.cache_support == "unsupported":
            cache_status = "unsupported"
        elif self.cache_support == "supported":
            cache_status = "supported_miss"
        else:
            cache_status = "unknown"
        estimated_cost = None
        if usage_reported and (self.input_cost_per_million or self.output_cost_per_million):
            estimated_cost = (
                uncached_input * self.input_cost_per_million
                + cache_read * self.input_cost_per_million * self.cache_read_cost_multiplier
                + cache_write * self.input_cost_per_million * self.cache_write_cost_multiplier
                + output_tokens * self.output_cost_per_million
            ) / 1_000_000
        return ProviderUsageSnapshot(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            estimated_cost=estimated_cost,
            usage_status="reported" if usage_reported else "not_reported",
            cache_status=cache_status,
        )

    @staticmethod
    def _agent_tool_contract() -> list[dict]:
        """Expose the registry contract to models without executable handlers."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in AgentToolRegistry(service=None).specs()
        ]

    @staticmethod
    def _tool_arguments(value, tool_name: str) -> dict:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"工具 {tool_name} 的参数不是有效 JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"工具 {tool_name} 的参数必须是 JSON 对象")
        return parsed

    @staticmethod
    def _openai_text(content) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(text, dict) and isinstance(text.get("value"), str):
                parts.append(text["value"])
        return "".join(parts)

    @staticmethod
    def _result_content(result: dict) -> str:
        return json.dumps(
            {
                "status": str(result.get("status") or "failed"),
                "output": result.get("output"),
                "error": result.get("error"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _validate_tool_calls(calls: tuple[ProviderToolCall, ...], is_followup: bool) -> tuple[ProviderToolCall, ...]:
        if len(calls) > 12:
            raise ValueError("模型单轮工具调用超过 12 个，未执行任何工具")
        ids = [call.id for call in calls]
        if any(not item for item in ids):
            raise ValueError("模型工具调用缺少调用 ID，未执行任何工具")
        if len(ids) != len(set(ids)):
            raise ValueError("模型工具调用 ID 重复，未执行任何工具")
        # A follow-up may legitimately require one more bounded, read-only
        # lookup.  The service caps the whole discussion at three tool rounds;
        # validation here only protects this individual Provider response.
        return calls

    def _native_followup_messages(self, tool_results: list[dict]) -> list[dict]:
        pending = getattr(self._thread_state, "pending_exchange", None)
        if not isinstance(pending, PendingToolExchange) or pending.protocol != self.provider_type:
            raise ValueError("缺少与本轮工具结果对应的模型工具调用上下文")

        remaining = list(pending.tool_calls)
        matched: list[tuple[ProviderToolCall, dict]] = []
        extra: list[dict] = []
        for result in tool_results:
            name = str(result.get("tool") or "")
            index = next((i for i, call in enumerate(remaining) if call.name == name), None)
            if index is None:
                extra.append(result)
                continue
            matched.append((remaining.pop(index), result))
        if remaining:
            names = ", ".join(call.name for call in remaining)
            raise ValueError(f"模型工具调用缺少执行结果：{names}")
        if any(not call.id for call, _result in matched):
            raise ValueError("模型工具调用缺少可用于原生回传的调用 ID")

        assistant = json.loads(pending.assistant_json)
        try:
            prior_messages = json.loads(pending.prior_messages_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("模型工具调用上下文损坏") from exc
        if not isinstance(prior_messages, list):
            raise ValueError("模型工具调用上下文格式无效")
        if self.provider_type == "anthropic":
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": self._result_content(result),
                    "is_error": str(result.get("status")) != "succeeded",
                }
                for call, result in matched
            ]
            if extra:
                blocks.append({
                    "type": "text",
                    "text": "服务端附加检查结果：" + json.dumps(extra, ensure_ascii=False, sort_keys=True),
                })
            return [
                *prior_messages,
                {"role": "assistant", "content": assistant},
                {"role": "user", "content": blocks},
            ]

        messages = [
            *prior_messages,
            # OpenAI-compatible gateways do not share one complete message
            # schema. In particular, some Gemini relays return a
            # ``reasoning_content`` field that they reject when it is replayed
            # as the assistant turn before a tool result. Keep only the native
            # tool-exchange fields required by the Chat Completions contract.
            {
                "role": "assistant",
                **{
                    key: assistant[key]
                    for key in ("content", "tool_calls", "name")
                    if key in assistant
                },
            },
            *[
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": self._result_content(result),
                }
                for call, result in matched
            ],
        ]
        if extra:
            messages.append({
                "role": "user",
                "content": "服务端附加检查结果：" + json.dumps(extra, ensure_ascii=False, sort_keys=True),
            })
        return messages

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict] | None = None,
        tool_results: list[dict] | None = None,
    ) -> LLMCallResult:
        system_prompt = system_prompt.rstrip() + self._reasoning_instruction()
        if tool_results is None:
            self._thread_state.pending_exchange = None
        native_messages = self._native_followup_messages(tool_results) if tool_results is not None else None
        if self.provider_type == "anthropic":
            base_url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
            if base_url == "https://api.anthropic.com":
                base_url += "/v1"
            endpoint = f"{base_url}/messages"
            req_data = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                "messages": native_messages or [{"role": "user", "content": user_prompt}],
            }
            if tools:
                req_data["tools"] = [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool["input_schema"],
                    }
                    for tool in tools
                ]
                req_data["tool_choice"] = {"type": "auto"}
            req_bytes = json.dumps(req_data).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("anthropic-version", "2023-06-01")
            req.add_header("x-api-key", self.api_key)
        else:
            endpoint = f"{self.base_url or 'https://api.openai.com/v1'}/chat/completions"
            req_data = {
                "model": self.model,
                self.token_limit_parameter: self.max_tokens,
                "messages": [{"role": "system", "content": system_prompt}, *(native_messages or [{"role": "user", "content": user_prompt}])],
            }
            if tools:
                req_data["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["input_schema"],
                        },
                    }
                    for tool in tools
                ]
                req_data["tool_choice"] = "auto"
            req_bytes = json.dumps(req_data).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")

        with self._open_with_retry(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            usage = self._capture_usage(data)
            self._thread_state.last_usage = usage
            if self.provider_type == "anthropic":
                content_blocks = data.get("content", [])
                normalized_calls = self._validate_tool_calls(tuple(
                    ProviderToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments_json=json.dumps(
                            self._tool_arguments(block.get("input"), str(block.get("name") or "")),
                            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        ),
                    )
                    for block in content_blocks
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name")
                ), tool_results is not None)
                text = "".join(
                    str(block.get("text") or "")
                    for block in content_blocks
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                pending = PendingToolExchange(
                    protocol=self.provider_type,
                    user_prompt=user_prompt,
                    assistant_json=json.dumps(content_blocks, ensure_ascii=False, sort_keys=True),
                    tool_calls=normalized_calls,
                    prior_messages_json=json.dumps(
                        native_messages or [{"role": "user", "content": user_prompt}],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ) if normalized_calls else None
                self._thread_state.pending_exchange = pending
                # Provider-native thinking blocks are deliberately not propagated. The product
                # contract exposes only the model-authored reasoning_summary in normal output.
                return LLMCallResult(text, "", normalized_calls, usage, pending)

            choices = data.get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            normalized_calls = []
            for item in message.get("tool_calls") or []:
                if not isinstance(item, dict) or item.get("type", "function") != "function":
                    continue
                function = item.get("function") if isinstance(item.get("function"), dict) else {}
                name = str(function.get("name") or "")
                if not name:
                    continue
                normalized_calls.append(ProviderToolCall(
                    id=str(item.get("id") or ""),
                    name=name,
                    arguments_json=json.dumps(
                        self._tool_arguments(function.get("arguments"), name),
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    ),
                ))
            normalized_calls_tuple = self._validate_tool_calls(tuple(normalized_calls), tool_results is not None)
            pending = PendingToolExchange(
                protocol=self.provider_type,
                user_prompt=user_prompt,
                assistant_json=json.dumps(message, ensure_ascii=False, sort_keys=True),
                tool_calls=normalized_calls_tuple,
                prior_messages_json=json.dumps(
                    native_messages or [{"role": "user", "content": user_prompt}],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ) if normalized_calls_tuple else None
            self._thread_state.pending_exchange = pending
            return LLMCallResult(
                self._openai_text(message.get("content")),
                "",
                normalized_calls_tuple,
                usage,
                pending,
            )

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        if isinstance(exc, urllib.error.HTTPError):
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                if retry_after is not None:
                    return min(5.0, max(0.0, float(retry_after)))
            except (TypeError, ValueError):
                pass
        return (0.25, 0.75)[min(attempt, 1)]

    @staticmethod
    def _is_transient_request_error(exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in {408, 429} or 500 <= exc.code <= 599
        if isinstance(exc, urllib.error.URLError):
            return True
        return isinstance(exc, (TimeoutError, socket.timeout))

    def _open_with_retry(self, request: urllib.request.Request):
        """Retry only failures that can plausibly succeed without user action."""
        for attempt in range(self.request_attempts):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if not self._is_transient_request_error(exc) or attempt + 1 >= self.request_attempts:
                    raise
                time.sleep(self._retry_delay(exc, attempt))
        raise RuntimeError("unreachable provider retry state")

    def _provider_failure(self, operation: str, exc: Exception | None = None):
        details = {"operation": operation, "provider": self.provider_type, "model": self.model}
        failure_kind = "provider_error"
        message = f"模型未能完成{operation}，本次没有回退为模拟结果。"
        if exc is not None:
            details["reason"] = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                details["http_status"] = exc.code
                # Keep only a bounded, provider-authored diagnostic.  The body
                # can explain model alias or request-shape failures, while the
                # request (including credentials and prompts) is never stored.
                try:
                    response_body = exc.read(2048).decode("utf-8", errors="replace")
                except Exception:
                    response_body = ""
                if response_body:
                    details["provider_response"] = response_body[:2048]
                    try:
                        parsed = json.loads(response_body)
                    except (TypeError, ValueError):
                        parsed = None
                    provider_message = (
                        parsed.get("error", {}).get("message")
                        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict)
                        else None
                    )
                    if provider_message:
                        details["provider_message"] = str(provider_message)[:1000]
                if exc.code == 429:
                    failure_kind = "provider_rate_limited"
                    message = f"模型服务限制了{operation}的请求，本次没有回退为模拟结果。"
                elif exc.code in {408, 504}:
                    failure_kind = "provider_timeout"
                    message = f"模型服务处理{operation}超时，本次没有回退为模拟结果。"
                elif 400 <= exc.code < 500:
                    failure_kind = "provider_invalid_request"
                    message = f"模型服务拒绝了{operation}的请求，请检查模型或请求参数。"
            elif isinstance(exc, (TimeoutError, socket.timeout)):
                failure_kind = "provider_timeout"
                message = f"模型服务处理{operation}超时，本次没有回退为模拟结果。"
            elif isinstance(exc, urllib.error.URLError):
                failure_kind = "provider_unavailable"
                message = f"模型服务暂时不可达，未能完成{operation}，本次没有回退为模拟结果。"
            details["failure_kind"] = failure_kind
        error = DomainError(
            "writing_provider_failed",
            message,
            status=502,
            details=details,
        )
        if exc is not None:
            raise error from exc
        raise error

    def generate_chapter_plan(self, messages: list[dict], chapter_context: dict) -> dict:
        try:
            system_prompt = self._skill_system_prompt("chapter.plan", chapter_context) + (
                "\n\n你负责把讨论记录与当前章节目标整理为章节细纲，不写正文。\n"
                "必须以纯 JSON 返回，格式：\n"
                "{\n"
                '  "schema_version": "chapter-plan/1.0",\n'
                '  "title": "章节名称",\n'
                '  "chapter_goal": "核心目标",\n'
                '  "beats": ["场景1节拍", "场景2节拍", ...],\n'
                '  "continuity_notes": ["承接说明..."]\n'
                "}"
            )
            chat_history = "\n".join(f"{m.get('role')}: {m.get('text', '')}" for m in messages)
            user_prompt = f"章节上下文: {json.dumps(chapter_context, ensure_ascii=False)}\n讨论历史:\n{chat_history}"
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            data["status"] = "proposed"
            return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("章节细纲生成", exc)
        self._provider_failure("章节细纲生成")

    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        try:
            system_prompt = self._skill_system_prompt("structure.plan", structure_context) + (
                "\n\n你负责把已确认的 StoryBlueprint 与当前讨论整理为卷、章、场景结构，不写正文。"
                "稳定 ID 由系统分配，你不得返回或猜测任何 ID。\n"
                "必须以纯 JSON 返回，格式：\n"
                "{\n"
                '  "schema_version": "story-structure-plan/1.0",\n'
                '  "volumes": [{"title":"卷名","purpose":"本卷变化",'
                '"chapters":[{"title":"章名","goal":"本章变化",'
                '"scenes":[{"title":"场景名","goal":"本场变化",'
                '"location":"地点或待确认","stop_boundary":"何时停止"}]}]}]\n'
                "}\n"
                "每章至少一场；每场必须有明确 goal。控制规模，只建立当前故事真正需要的结构。"
            )
            chat_history = "\n".join(
                f"{message.get('role')}: {message.get('text', '')}" for message in messages[-12:]
            )
            user_prompt = (
                f"结构上下文: {json.dumps(structure_context, ensure_ascii=False)}\n"
                f"讨论历史:\n{chat_history}"
            )
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            data["status"] = "proposed"
            return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("作品结构生成", exc)
        self._provider_failure("作品结构生成")

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        try:
            system_prompt = self._skill_system_prompt("canon.assemble", memory_context) + (
                "\n\n你负责从一份已经固定的场景正式修订中提取长期写作记忆，不修改正文或正式资料。"
                "只记录正文能够支持的内容，不把推测写成事实；已有记忆需要推进或回收时，"
                "可用 update/retire 并指定系统提供的 target_memory_id。新记忆不得返回任何 ID。\n"
                "必须返回纯 JSON：\n"
                "{\n"
                '  "schema_version":"memory-bundle/1.0",\n'
                '  "summary":"本次提取说明",\n'
                '  "items":[{\n'
                '    "kind":"episode_memory|scene_state_snapshot|open_thread|decision_record",\n'
                '    "operation":"create|update|retire",\n'
                '    "target_memory_id":null,\n'
                '    "title":"简短标题",\n'
                '    "summary":"正文能够支持的记忆",\n'
                '    "details":{},\n'
                '    "scope_type":"work|chapter|scene|character",\n'
                '    "scope_id":"系统上下文中的真实 ID",\n'
                '    "confidence_status":"open|inferred",\n'
                '    "source_block_ids":["正文块 ID"]\n'
                "  }],\n"
                '  "knowledge_suggestions":[{\n'
                '    "kind":"canon_fact",\n'
                '    "text":"正文直接支持、值得跨场景维护的事实",\n'
                '    "scope":"work|chapter|scene",\n'
                '    "confidence_status":"open|inferred",\n'
                '    "source_block_ids":["正文块 ID"]\n'
                "  }]\n"
                "}\n"
                "knowledge_suggestions 是可选数组，只放需要进入正式资料审核的长期事实；"
                "不要重复已有 WorkCanon。摘要、记忆和资料建议都不是正式事实；"
                "用户分别采纳对应 Proposal 后系统才会建立 confirmed Revision。"
            )
            user_prompt = "记忆提取上下文: " + json.dumps(memory_context, ensure_ascii=False)
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            data["status"] = "proposed"
            return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("长期记忆提取", exc)
        self._provider_failure("长期记忆提取")

    def sweep_memory_bundle(self, memory_context: dict) -> dict:
        try:
            system_prompt = self._skill_system_prompt("memory.sweep", memory_context) + (
                "\n\n你负责清扫一章中全部已固定场景修订，找出跨场景遗漏、需要推进或应回收的长期记忆。"
                "不得修改正文或正式资料，不得把推测写成事实；已有记忆可用 update/retire，"
                "新记忆使用 create。系统 ID 只能从输入中引用，新记忆不得自行分配 ID。\n"
                "必须返回纯 JSON，schema_version 为 memory-bundle/1.0；items 字段与场景记忆提取相同，"
                "但每条必须额外提供 source_refs: "
                '[{"scene_id":"输入中的场景 ID","source_block_ids":["对应正文块 ID"]}]。'
                "用户采纳 Proposal 前，任何结果都不是正式长期记忆。"
            )
            user_prompt = "章节记忆清扫上下文: " + json.dumps(memory_context, ensure_ascii=False)
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            data["status"] = "proposed"
            return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("章节长期记忆清扫", exc)
        self._provider_failure("章节长期记忆清扫")

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        try:
            tool_followup = bool(work_context.get("tool_followup"))
            task_contract = work_context.get("task_contract") if isinstance(work_context.get("task_contract"), dict) else {}
            task_id = str(task_contract.get("id") or "brief.build")
            system_prompt = self._skill_system_prompt(
                task_id,
                work_context,
                output_mode="discussion_json",
            ) + (
                "\n\n你是作品当前阶段的创作导演，协助作者讨论并理清故事方向、人物关系与事实边界。\n"
                "conversation_summary 只是由历史消息派生的续聊索引，不是 WorkCanon、人物卡、世界观卡或官方证据。"
                "冲突时严格按已采纳正式 Artifact、较新的原始用户消息、派生摘要的顺序判断；"
                "摘要不能单独支持任何正式资料 Proposal，必须回到原始消息、场景修订或文档引用。\n"
                "语气温和、敏锐、富有二创文学素养。需要核对已有正式资料或生成资料讨论草稿时，"
                "使用已提供的工具；工具调用只是执行请求，不得声称工具已经成功，也不得声称正式资料已经修改。\n"
                "如果不需要调用工具，请回复 JSON；调用工具时也可以同时返回这份 JSON：\n"
                "{\n"
                '  "text": "对作者想法的提炼分析与推进建议",\n'
                '  "questions": ["1-2个引导性问题"],\n'
                '  "decision_card": null,\n'
                '  "reasoning_summary": "一句面向作者的判断依据摘要，不输出隐藏推理过程",\n'
                '  "ready_for_proposal": true/false\n'
                "}\n"
                "只有当作者需要在 2-6 个明确互斥或可比较的选项中作选择时，才返回 decision_card；"
                "普通选项卡的 kind 必须严格写成 choose（不要使用 choice/options/select 等别名）；"
                "确认卡或 Proposal 卡才分别使用 confirm 或 proposal。它必须包含 kind、title、options（每项含 id、label、description）、submit_label 和 allow_custom。"
                "开放式问题继续放在 questions，不要为了显示卡片而把普通追问改成选项。"
            )
            if task_id == "canon.assemble":
                system_prompt += (
                    "\n当前任务是检查一份已经采纳的场景正文，提取新成立的事实、人物关系变化、"
                    "知情边界或伏笔状态。只提取正文能够支持的内容，不把推测写成事实。"
                    "需要沉淀时调用 draft_canon_fact，并把 scene_memory_context.scene.revision_id"
                    " 写入 source_refs；每轮最多形成一份资料讨论草稿，正式写回仍由 Proposal 决定。"
                )
            document_skill = work_context.get("document_skill")
            if isinstance(document_skill, dict):
                rules = document_skill.get("rules") if isinstance(document_skill.get("rules"), list) else []
                system_prompt += (
                    f"\n当前启用默认文档规则包 {document_skill.get('id', 'document.read')}@{document_skill.get('version', '1.0.0')}：\n"
                    + "\n".join(f"- {rule}" for rule in rules)
                )
                document_context = work_context.get("document_context")
                if isinstance(document_context, dict):
                    system_prompt += (
                        "\n文档上下文只包含系统按当前任务检索出的有限片段。"
                        "不得声称读取了未命中的部分；引用事实时使用 citation 的 display_label，"
                        "并保留 filename、chunk_id 和 paragraph_ids 以供界面核验。"
                    )
            if tool_followup:
                system_prompt += (
                    "\n系统已经执行完上一轮工具。优先根据 tool_results 生成最终 JSON 回复；"
                    "只有确实缺少另一项已提供的只读资料时，才能请求下一轮工具。"
                    "整个用户回合最多允许三轮工具调用，绝不因此修改正式资料。"
                )
            user_prompt = f"作品上下文: {json.dumps(work_context, ensure_ascii=False)}\n历史消息:\n" + "\n".join(
                f"{m.get('role')}: {m.get('text', '')}" for m in messages[-8:]
            )
            call = self._call_llm(
                system_prompt,
                user_prompt,
                tools=self._agent_tool_contract(),
                tool_results=work_context.get("tool_results") if tool_followup else None,
            )
            if call.text.strip():
                try:
                    data = self._parse_json_object(call.text)
                except (TypeError, ValueError, json.JSONDecodeError):
                    data = self._discussion_text_fallback(call.text)
                if call.tool_calls:
                    data["tool_calls"] = [item.as_dict() for item in call.tool_calls]
                return data
            if call.tool_calls:
                data = {
                    "text": "模型已请求调用作品工具；系统将按当前权限执行，并以实际执行结果为准。",
                    "questions": [],
                    "reasoning_summary": "模型发出了工具调用请求，尚未由 Provider 宣称执行成功。",
                    "ready_for_proposal": False,
                    "tool_calls": [item.as_dict() for item in call.tool_calls],
                }
                return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("作品讨论", exc)
        self._provider_failure("作品讨论")

    def generate_blueprint(self, brief: dict, analysis_context: dict | None = None) -> dict:
        try:
            prompt_context = {**(analysis_context or {}), **brief}
            system_prompt = self._skill_system_prompt(
                "blueprint.generate",
                prompt_context,
                output_mode="story_blueprint_json",
            ) + (
                "\n\n你负责把已讨论的创意简报整理为结构化 StoryBlueprint，不写正文。\n"
                "必须返回纯 JSON，包含 title, premise, theme, central_conflict, direction (数组), characters (数组), mode。\n"
                "如果用户明确要求全篇只有旁白且没有任何对白角色，必须额外返回 narrator_only=true、characters=[]，"
                "并建议 sensei_presence=absent；否则 narrator_only=false 且 characters 至少包含一个主要角色。\n"
            )
            user_prompt = f"Brief: {json.dumps(brief, ensure_ascii=False)}\nContext: {json.dumps(analysis_context or {}, ensure_ascii=False)}"
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            data["status"] = "proposed"
            return data
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("故事方向生成", exc)
        self._provider_failure("故事方向生成")

    def generate_scene(self, context: dict) -> str:
        try:
            request = self._scene_skill_request("scene.draft.generate", context)
            system_prompt = request["system_prompt"] + (
                "\n\n根据用户消息中的场景合同、运行时人物卡和已确认事实生成一次正文候选。"
                "不要解释规则，不输出标题、分析、备选版本或修订建议。"
            )
            user_prompt = request["user_prompt"]
            call = self._call_llm(system_prompt, user_prompt)
            if call.text.strip():
                return call.text.strip() + "\n"
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("场景起草", exc)
        self._provider_failure("场景起草")

    def rewrite_scene(self, context: dict, base_text: str, instruction: str) -> str:
        try:
            request = self._scene_skill_request(
                "scene.draft.rewrite",
                context,
                payload={"base_text": base_text, "instruction": instruction, "selection": context.get("selection")},
            )
            system_prompt = request["system_prompt"] + (
                "\n\n根据作者的修改意见重写固定范围，保留未要求改变的事实、关系和场景结果。"
                "只返回完整候选正文，不输出解释或第二版。"
            )
            user_prompt = request["user_prompt"]
            call = self._call_llm(system_prompt, user_prompt)
            if call.text.strip():
                return call.text.strip() + "\n"
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("场景改写", exc)
        self._provider_failure("场景改写")

    def review_scene(self, context: dict, text: str) -> list[dict]:
        try:
            request = self._scene_skill_request(
                "scene.review", context, payload={"text": text}, output_mode="review_findings"
            )
            system_prompt = request["system_prompt"] + (
                "\n\n你负责审查一份已经采纳的场景正文，不改写正文。"
                "只返回 JSON 对象，格式为 {\"findings\":[...]}。"
                "每条 finding 只允许 kind、severity、message、evidence 四个字段；"
                "severity 只能是 blocking、warning、info。"
                "重点检查 OOC、连续性、信息归属、BA 风格、第四面墙、禁止揭示和停止边界。"
                "每条 finding 必须同时包含非空 kind、合法 severity、非空 message 和 evidence 对象；"
                "证据没有额外字段时也必须写 evidence: {}，不能省略或写 null。"
                "例如：{\"findings\":[{\"kind\":\"ooc\",\"severity\":\"warning\",\"message\":\"人物语气需要复核。\",\"evidence\":{\"source\":\"dialogue\"}}]}。"
                "没有任何问题时只能返回 {\"findings\":[]}，不要放入空对象、字符串或其它字段。"
                "不要输出 Markdown、解释文字或隐藏思维链。"
            )
            user_prompt = request["user_prompt"]
            call = self._call_llm(system_prompt, user_prompt)
            data = self._parse_json_object(call.text)
            raw_findings = data.get("findings", [])
            if not isinstance(raw_findings, list):
                raise DomainError("provider_output_invalid", "场景审查结果必须包含 findings 数组。", status=502)
            findings = []
            allowed_severities = {"blocking", "warning", "info"}
            for index, item in enumerate(raw_findings):
                if not isinstance(item, dict):
                    raise DomainError("provider_output_invalid", "场景审查条目格式无效。", status=502, details={"index": index})
                kind = str(item.get("kind", "")).strip()
                severity = str(item.get("severity", "")).strip()
                message = str(item.get("message", "")).strip()
                evidence = item.get("evidence", {})
                if not kind or severity not in allowed_severities or not message or not isinstance(evidence, dict):
                    raise DomainError("provider_output_invalid", "场景审查条目缺少有效字段。", status=502, details={"index": index})
                findings.append({"kind": kind, "severity": severity, "message": message, "evidence": evidence})
            return findings
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("场景审查", exc)
        self._provider_failure("场景审查")

    def _review_work(self, task_id: str, context: dict) -> list[dict]:
        if not self.prompt_assembler:
            raise DomainError("prompt_assembly_failed", "BA 写作 Prompt 装配器不可用。", status=503)
        request = self.prompt_assembler.assemble_work_review_request(task_id, context)
        if request.get("status") != "ready":
            raise DomainError(
                request.get("error_code") or "prompt_assembly_failed",
                "作品级审查所需的 BA 写作规则或固定输入不可用。",
                status=409,
                details={"missing_files": request.get("missing_files", [])},
            )
        focus = (
            "跨场景检查知识获得顺序、地点与道具状态、人物关系变化、伏笔建立与回收。"
            if task_id == "continuity.review"
            else "全篇检查人物一致性、BA 风格、叙事完成度、未决伏笔与发布阻塞问题。"
        )
        system_prompt = request["system_prompt"] + (
            "\n\n你是只读审查 Agent，不得改写正文或正式资料。"
            + focus
            + "只返回 JSON 对象 {\"findings\":[...]}。"
            "每条 finding 必须包含 scene_id、revision_id、kind、severity、message、evidence；"
            "severity 只能是 blocking、warning、info。没有问题时返回空数组。"
            "evidence 必须指出相关场景或正文证据。不要输出隐藏思维链。"
        )
        try:
            call = self._call_llm(system_prompt, request["user_prompt"])
            data = self._parse_json_object(call.text)
            raw_findings = data.get("findings", [])
            if not isinstance(raw_findings, list):
                raise DomainError("provider_output_invalid", "作品级审查结果必须包含 findings 数组。", status=502)
            findings = []
            for index, item in enumerate(raw_findings):
                if not isinstance(item, dict):
                    raise DomainError("provider_output_invalid", "作品级审查条目格式无效。", status=502, details={"index": index})
                normalized = {
                    "scene_id": str(item.get("scene_id", "")).strip(),
                    "revision_id": str(item.get("revision_id", "")).strip(),
                    "kind": str(item.get("kind", "")).strip(),
                    "severity": str(item.get("severity", "")).strip(),
                    "message": str(item.get("message", "")).strip(),
                    "evidence": item.get("evidence", {}),
                }
                if (
                    not normalized["scene_id"]
                    or not normalized["revision_id"]
                    or not normalized["kind"]
                    or normalized["severity"] not in {"blocking", "warning", "info"}
                    or not normalized["message"]
                    or not isinstance(normalized["evidence"], dict)
                ):
                    raise DomainError("provider_output_invalid", "作品级审查条目缺少有效字段。", status=502, details={"index": index})
                findings.append(normalized)
            return findings
        except DomainError:
            raise
        except Exception as exc:
            self._provider_failure("作品级审查", exc)
        self._provider_failure("作品级审查")

    def review_continuity(self, context: dict) -> list[dict]:
        return self._review_work("continuity.review", context)

    def review_release(self, context: dict) -> list[dict]:
        return self._review_work("release.review", context)


def make_writing_provider(settings_or_credentials, prompt_assembler=None) -> WritingProvider:
    if hasattr(settings_or_credentials, "get_credentials"):
        creds = settings_or_credentials.get_credentials()
        pub = settings_or_credentials.public()["model"]
    elif isinstance(settings_or_credentials, dict):
        creds = settings_or_credentials
        pub = creds
    else:
        return FakeWritingProvider()

    if pub.get("configured") and creds.get("model"):
        return LLMWritingProvider(creds, prompt_assembler)
    return FakeWritingProvider()
