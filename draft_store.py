# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 草稿存储与加载校验 (draft_store.py)
管理 out/drafts/<token>/ 存储布局、写事务、session sha256 加载校验与身份重建流程
包含双版本 CAS 控制 (draft_version 与 content_revision)
"""

import datetime
import hashlib
import json
import os
import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from aa_project_assets import validate_windows_path_component
from document import compile_document, normalize_draft_nodes, parse_document_lossless
from draft_identity import (
    CardIdentity,
    assign_identity,
    compute_text_fingerprint,
    create_source_map,
)
from story_workspace import normalize_bgm_policy
from runtime_layout import LAYOUT

HERE = LAYOUT.user_data_root if LAYOUT.frozen else Path(__file__).resolve().parent
_DRAFT_LOCKS_GUARD = threading.Lock()
_DRAFT_LOCKS: Dict[str, threading.RLock] = {}


def _parse_draft_nodes(text: str) -> List[Any]:
    return normalize_draft_nodes(parse_document_lossless(text))


class RevisionConflictError(ValueError):
    """草稿版本冲突异常 (HTTP 409 code: revision_conflict)"""
    pass


class InvalidDraftTokenError(ValueError):
    """A requested draft token is not a safe component below the drafts root."""


class ReviewPendingError(ValueError):
    """未通过审查门控异常 (HTTP 409 code: review_pending)"""
    def __init__(self, message="Draft has pending reviews or unresolved errors", code="review_pending", counts=None):
        super().__init__(message)
        self.code = code
        self.counts = counts or {}


class AnnotationIncompleteError(ReviewPendingError):
    """AI 标注尚未完成，草稿只能继续审查或续跑。"""
    def __init__(self, status=None):
        status = normalize_annotation_status(status)
        super().__init__(
            message=(
                "AI annotation is incomplete: "
                f"completed={status['completed_targets']}, "
                f"total={status['total_targets']}, "
                f"pending={status['pending_targets']}"
            ),
            code="annotation_incomplete",
            counts={"annotation_pending": status["pending_targets"]},
        )
        self.annotation_status = status


def normalize_annotation_status(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    total = max(0, int(value.get("total_targets") or 0))
    completed = max(0, min(total, int(value.get("completed_targets") or 0)))
    pending = max(0, int(value.get("pending_targets") or (total - completed)))
    pending = min(total, pending) if total else 0
    state = "partial" if value.get("status") == "partial" or pending else "complete"
    return {
        "status": state,
        "completed_targets": completed,
        "total_targets": total,
        "pending_targets": pending,
        "pending_start_line": value.get("pending_start_line") if pending else None,
        "pending_end_line": value.get("pending_end_line") if pending else None,
    }


def calc_sha256(content: str) -> str:
    """计算 UTF-8 文本的 SHA256"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DraftStore:
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = HERE / "out" / "drafts"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_draft_path(self, token: str) -> Path:
        try:
            safe_token = validate_windows_path_component(
                str(token), label="draft token"
            )
        except ValueError as exc:
            raise InvalidDraftTokenError(str(exc)) from exc
        base_dir = self.base_dir.resolve()
        draft_dir = (base_dir / safe_token).resolve()
        try:
            draft_dir.relative_to(base_dir)
        except ValueError as exc:
            raise InvalidDraftTokenError("draft token escapes drafts root") from exc
        return draft_dir

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List drafts with a read-only generation number for each source lineage."""
        rows = []
        if self.base_dir.is_dir():
            for draft_dir in self.base_dir.iterdir():
                if not draft_dir.is_dir():
                    continue
                session_file = draft_dir / "session.json"
                source_file = draft_dir / "source.txt"
                if not session_file.is_file() or not source_file.is_file():
                    continue
                try:
                    session = json.loads(session_file.read_text(encoding="utf-8"))
                    source_hash = calc_sha256(source_file.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                if isinstance(session, dict):
                    rows.append((session, source_hash))

        rows.sort(key=lambda row: (
            str(row[0].get("created_at") or ""),
            str(row[0].get("draft_token") or ""),
        ))
        lineage_versions: Dict[tuple[str, str], int] = {}
        sessions = []
        for session, source_hash in rows:
            project = str(session.get("project") or "").strip().casefold()
            lineage = (project, source_hash)
            generation_version = lineage_versions.get(lineage, 0) + 1
            lineage_versions[lineage] = generation_version
            item = dict(session)
            item["generation_version"] = generation_version
            sessions.append(item)
        return sessions

    def generation_version(self, token: str) -> int:
        for session in self.list_sessions():
            if session.get("draft_token") == token:
                return int(session["generation_version"])
        return 1

    def find_identical_complete_draft(
        self, *, text: str, source_text: str, project: str,
        story_token: Optional[str] = None,
    ) -> Optional[str]:
        """Return the newest untouched complete draft with identical inputs/output."""
        text_hash = calc_sha256(text)
        source_hash = calc_sha256(source_text)
        sessions = sorted(
            self.list_sessions(),
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("draft_token") or ""),
            ),
            reverse=True,
        )
        for session in sessions:
            if str(session.get("project") or "") != str(project or ""):
                continue
            if str(session.get("story_token") or "") != str(story_token or ""):
                continue
            if normalize_annotation_status(session.get("annotation_status"))["status"] != "complete":
                continue
            if session.get("edited_sha256") != text_hash:
                continue
            token = str(session.get("draft_token") or "")
            draft_dir = self.get_draft_path(token)
            source_file = draft_dir / "source.txt"
            annotated_file = draft_dir / "annotated.txt"
            try:
                if calc_sha256(source_file.read_text(encoding="utf-8")) != source_hash:
                    continue
                if calc_sha256(annotated_file.read_text(encoding="utf-8")) != text_hash:
                    continue
            except OSError:
                continue
            return token
        return None

    @contextmanager
    def draft_lock(self, token: str):
        draft_dir = self.get_draft_path(token)
        lock_key = str(draft_dir.resolve()).casefold()
        with _DRAFT_LOCKS_GUARD:
            local_lock = _DRAFT_LOCKS.setdefault(lock_key, threading.RLock())
        with local_lock:
            draft_dir.mkdir(parents=True, exist_ok=True)
            yield

    def create_draft(
        self,
        token: str,
        text: str,
        project: str = "未命名工程",
        source_text: Optional[str] = None,
        cast: Optional[Dict[str, Any]] = None,
        story_token: Optional[str] = None,
        bgm_policy: Optional[Dict[str, Any]] = None,
        annotation_status: Optional[Dict[str, Any]] = None,
        annotation_trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """新建草稿目录并保存各真相源文件"""
        cast = cast if isinstance(cast, dict) else {}
        frozen_bgm_policy = normalize_bgm_policy(bgm_policy)
        draft_dir = self.get_draft_path(token)
        draft_dir.mkdir(parents=True, exist_ok=True)

        source_content = source_text if source_text is not None else text

        with self.draft_lock(token):
            (draft_dir / "annotated.txt").write_text(text, encoding="utf-8")
            (draft_dir / "edited.txt").write_text(text, encoding="utf-8")
            (draft_dir / "source.txt").write_text(source_content, encoding="utf-8")
            (draft_dir / "cast.json").write_text(
                json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if annotation_trace is not None:
                if not isinstance(annotation_trace, dict):
                    raise ValueError("annotation_trace must be an object")
                if annotation_trace.get("annotated_source_sha256") != calc_sha256(text):
                    raise ValueError("annotation_trace does not match annotated text")
                if not isinstance(annotation_trace.get("lines"), list):
                    raise ValueError("annotation_trace lines must be an array")
                (draft_dir / "annotation_trace.json").write_text(
                    json.dumps(annotation_trace, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            source_map = create_source_map(source_content)
            with open(draft_dir / "source_map.json", "w", encoding="utf-8") as f:
                json.dump(source_map, f, ensure_ascii=False, indent=2)

            nodes = _parse_draft_nodes(text)
            identities = assign_identity(nodes, source_map=source_map, origin_override="source")
            identities_data = [card.to_dict() for card in identities]
            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            edited_sha256 = calc_sha256(text)
            identity_sha256 = calc_sha256(identity_json_str)

            session = {
                "draft_token": token,
                "draft_version": 1,
                "content_revision": 1,
                "last_compiled_build_id": None,
                "last_compiled_content_revision": 0,
                "last_installed_build_id": None,
                "installed_at": None,
                "project": project,
                "story_token": story_token,
                "bgm_policy": frozen_bgm_policy,
                "annotation_status": normalize_annotation_status(annotation_status),
                "edited_sha256": edited_sha256,
                "identity_sha256": identity_sha256,
                "created_at": datetime.datetime.now().isoformat(),
            }

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def save_cast(self, token: str, cast: Dict[str, Any]) -> None:
        """保存草稿演员表（供诊断重算与 cast/update 使用）。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            (draft_dir / "cast.json").write_text(
                json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_cast(self, token: str) -> Dict[str, Any]:
        """读取草稿演员表（无锁，供持锁方法内部调用）。"""
        with self.draft_lock(token):
            draft_dir = self.get_draft_path(token)
            f = draft_dir / "cast.json"
            if f.is_file():
                return json.loads(f.read_text(encoding="utf-8"))
            return {}

    def _diagnostic_cast(
        self, token: str, cast: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return the flat speaker map expected by the document compiler."""
        value = cast
        if value is None:
            cast_file = self.get_draft_path(token) / "cast.json"
            value = (
                json.loads(cast_file.read_text(encoding="utf-8"))
                if cast_file.is_file()
                else {}
            )
        if not isinstance(value, dict):
            return {}
        wrapped = value.get("cast")
        return wrapped if isinstance(wrapped, dict) else value

    def update_cast(
        self,
        token: str,
        speaker: str,
        mapping: Dict[str, Any],
        expected_draft_version: int,
    ) -> Dict[str, Any]:
        """更新草稿演员表的单个说话人绑定：重算诊断、重置该说话人卡片为待审、双版本 +1。

        cast 变化会影响编译结果，因此同时递增 content_revision。
        """
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            cast_file = draft_dir / "cast.json"
            cast = {}
            if cast_file.is_file():
                cast = json.loads(cast_file.read_text(encoding="utf-8"))
            cast.setdefault("cast", {})[speaker] = mapping
            cast_file.write_text(json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identities_data = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            nodes = _parse_draft_nodes(edited_text)

            # 重算诊断（cast 变化会影响未绑定演员等诊断）
            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            # 该说话人的 line 卡片重置为待审
            for node, card in zip(nodes, identities_data):
                if node.kind == "line" and node.fields.get("who") == speaker:
                    card["review_state"] = "pending"

            session["draft_version"] += 1
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": edited_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def load_draft(self, token: str, cast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self.draft_lock(token):
            return self._load_draft_locked(token, cast=cast)

    def find_asset_references(
        self, *, token: str, kind: str, aa_key: str
    ) -> List[Dict[str, Any]]:
        """返回可安全展示的草稿素材引用，不暴露路径或剧本全文。"""
        command_kinds = {
            "background": {"bg"},
            "sound": {"se", "sound"},
        }
        if kind not in {*command_kinds, "character"}:
            raise ValueError("不支持的素材类型")

        expected_key = str(aa_key).strip().casefold()
        with self.draft_lock(token):
            draft_dir = self.get_draft_path(token)
            session_file = draft_dir / "session.json"
            if not session_file.is_file():
                raise FileNotFoundError(f"草稿会话文件不存在: {session_file}")

            nodes = _parse_draft_nodes(
                (draft_dir / "edited.txt").read_text(encoding="utf-8")
            )
            cards = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            if len(nodes) != len(cards):
                raise ValueError("Nodes and identities mismatched")

            if kind == "character":
                cast_file = draft_dir / "cast.json"
                cast_data = (
                    json.loads(cast_file.read_text(encoding="utf-8"))
                    if cast_file.is_file()
                    else {}
                )
                speakers = self._speakers_bound_to_asset(cast_data, expected_key)
                return self._character_asset_references(nodes, cards, speakers)
            return self._directive_asset_references(
                nodes, cards, command_kinds[kind], expected_key
            )

    @staticmethod
    def _directive_asset_references(
        nodes: List[Any], cards: List[Dict[str, Any]], commands: set[str], aa_key: str
    ) -> List[Dict[str, Any]]:
        references = []
        for line_hint, (node, card) in enumerate(zip(nodes, cards), 1):
            command = str(node.fields.get("cmd") or "").casefold()
            argument = str(node.fields.get("arg") or "").strip()
            if node.kind != "dir" or command not in commands:
                continue
            if argument.casefold() != aa_key:
                continue
            references.append({
                "card_id": card["card_id"],
                "kind": "directive",
                "label": f"@{command} {argument}",
                "line_hint": line_hint,
            })
        return references

    @staticmethod
    def _speakers_bound_to_asset(cast_data: Dict[str, Any], aa_key: str) -> set[str]:
        """从最终演员表和兼容的绑定表中反查角色素材。"""
        speakers = set()
        binding_sets = [cast_data.get("cast"), cast_data.get("bindings")]
        if not any(isinstance(bindings, dict) for bindings in binding_sets):
            binding_sets.append(cast_data)
        for bindings in binding_sets:
            if not isinstance(bindings, dict):
                continue
            for speaker, binding in bindings.items():
                if not isinstance(binding, dict):
                    continue
                keys = [binding.get(name) for name in ("key", "aa_key", "id")]
                custom = binding.get("custom")
                if isinstance(custom, dict):
                    keys.append(custom.get("asset"))
                if any(str(value).strip().casefold() == aa_key for value in keys if value):
                    speakers.add(str(speaker))
        return speakers

    @staticmethod
    def _character_asset_references(
        nodes: List[Any], cards: List[Dict[str, Any]], speakers: set[str]
    ) -> List[Dict[str, Any]]:
        references = []
        for line_hint, (node, card) in enumerate(zip(nodes, cards), 1):
            speaker = str(node.fields.get("who") or "")
            if node.kind != "line" or speaker not in speakers:
                continue
            references.append({
                "card_id": card["card_id"],
                "kind": "line",
                "label": speaker,
                "line_hint": line_hint,
            })
        return references

    def _load_draft_locked(self, token: str, cast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """加载草稿并校验 edited_sha256, identity_sha256 与卡片指纹。校验失败自动重建身份。"""
        draft_dir = self.get_draft_path(token)
        session_file = draft_dir / "session.json"
        if not session_file.is_file():
            raise FileNotFoundError(f"草稿会话文件不存在: {session_file}")

        session = json.loads(session_file.read_text(encoding="utf-8"))
        edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
        identity_str = (draft_dir / "identity.json").read_text(encoding="utf-8")

        curr_edited_sha = calc_sha256(edited_text)
        curr_identity_sha = calc_sha256(identity_str)

        is_valid = True
        if curr_edited_sha != session.get("edited_sha256"):
            is_valid = False
        if curr_identity_sha != session.get("identity_sha256"):
            is_valid = False

        nodes = _parse_draft_nodes(edited_text)
        identities_data = json.loads(identity_str)

        if is_valid:
            if len(nodes) != len(identities_data):
                is_valid = False
            else:
                for node, card_dict in zip(nodes, identities_data):
                    fp = compute_text_fingerprint(node.raw)
                    if fp != card_dict.get("text_fingerprint"):
                        is_valid = False
                        break

        if not is_valid:
            return self.rebuild_identity(token, cast=cast)

        _, diagnostics = compile_document(
            nodes, self._diagnostic_cast(token, cast), {}
        )

        return {
            "session": session,
            "edited_text": edited_text,
            "identities": identities_data,
            "diagnostics": diagnostics,
            "identity_rebuilt": False,
        }

    def rebuild_identity(self, token: str, cast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """重建卡片身份；仅为哈希可信且文本未变的卡片保留审查状态。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            session = json.loads((draft_dir / "session.json").read_text(encoding="utf-8"))
            identity_file = draft_dir / "identity.json"
            old_identity_text = (
                identity_file.read_text(encoding="utf-8")
                if identity_file.is_file()
                else ""
            )
            trusted_old_identities = (
                calc_sha256(edited_text) == session.get("edited_sha256")
                and calc_sha256(old_identity_text) == session.get("identity_sha256")
            )

            source_map = {}
            map_file = draft_dir / "source_map.json"
            if map_file.is_file():
                source_map = json.loads(map_file.read_text(encoding="utf-8"))

            nodes = _parse_draft_nodes(edited_text)
            new_identities = assign_identity(nodes, source_map=source_map, origin_override="manual")
            if trusted_old_identities:
                old_by_fingerprint = defaultdict(deque)
                for old in json.loads(old_identity_text):
                    fingerprint = old.get("text_fingerprint")
                    if fingerprint:
                        old_by_fingerprint[fingerprint].append(old)
                for node, identity in zip(nodes, new_identities):
                    matches = old_by_fingerprint.get(compute_text_fingerprint(node.raw))
                    if not matches:
                        continue
                    old = CardIdentity.from_dict(matches.popleft())
                    identity.card_id = old.card_id
                    identity.source_id = old.source_id
                    identity.origin = old.origin
                    identity.parent_id = old.parent_id
                    identity.review_state = old.review_state
            new_identities_data = [card.to_dict() for card in new_identities]

            identity_json_str = json.dumps(new_identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(edited_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": edited_text,
                "identities": new_identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": True,
            }

    def update_draft_content(
        self,
        token: str,
        new_text: str,
        expected_draft_version: int,
        is_content_change: bool = True,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """带 CAS 控制的草稿内容更新。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            session["draft_version"] += 1
            if is_content_change:
                session["content_revision"] += 1

            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")
            source_map = {}
            map_file = draft_dir / "source_map.json"
            if map_file.is_file():
                source_map = json.loads(map_file.read_text(encoding="utf-8"))

            nodes = _parse_draft_nodes(new_text)
            identities = assign_identity(nodes, source_map=source_map, origin_override="manual")
            identities_data = [card.to_dict() for card in identities]
            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def update_card_review(
        self,
        token: str,
        card_id: str,
        review_state: str,
        expected_draft_version: int,
    ) -> Dict[str, Any]:
        """纯审查更新：仅 draft_version +1，content_revision 保持不变。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            identity_file = draft_dir / "identity.json"
            identities_data = json.loads(identity_file.read_text(encoding="utf-8"))

            card_found = False
            for card in identities_data:
                if card["card_id"] == card_id:
                    card["review_state"] = review_state
                    card_found = True
                    break

            if not card_found:
                raise KeyError(f"Card ID not found: {card_id}")

            session["draft_version"] += 1
            session["annotation_override_accepted"] = not any(
                card.get("review_state") == "pending" for card in identities_data
            )
            # content_revision 保持不变！

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            identity_file.write_text(identity_json_str, encoding="utf-8")

            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            diagnostics = []
            diag_file = draft_dir / "diagnostics.json"
            if diag_file.is_file():
                diagnostics = json.loads(diag_file.read_text(encoding="utf-8"))

            return {
                "session": session,
                "edited_text": edited_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def update_card_content(
        self,
        token: str,
        card_id: str,
        patch: Dict[str, Any],
        expected_draft_version: int,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """单卡内容修改，双版本 +1。若涉及指令更新则触发后续已审卡片重置为 pending。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identity_file = draft_dir / "identity.json"
            identities_data = json.loads(identity_file.read_text(encoding="utf-8"))

            nodes = _parse_draft_nodes(edited_text)
            if len(nodes) != len(identities_data):
                raise ValueError("Nodes and identities mismatched")

            target_index = -1
            for idx, item in enumerate(identities_data):
                if item["card_id"] == card_id:
                    target_index = idx
                    break

            if target_index == -1:
                raise KeyError(f"Card ID not found: {card_id}")

            target_node = nodes[target_index]
            target_node.fields.update(patch)
            target_node.dirty = True

            is_directive = target_node.kind in ("dir", "background_request")
            if is_directive:
                for idx in range(target_index + 1, len(identities_data)):
                    identities_data[idx]["review_state"] = "pending"

            # 重新序列化并写回
            from document import serialize_document
            new_text = serialize_document(nodes)
            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")

            # 更新 text_fingerprint
            identities_data[target_index]["text_fingerprint"] = compute_text_fingerprint(target_node.raw if not target_node.dirty else new_text)

            session["draft_version"] += 1
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            identity_file.write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def insert_card(
        self,
        token: str,
        after_card_id: Optional[str],
        kind: str,
        payload: Dict[str, Any],
        origin: str = "manual",
        expected_draft_version: int = 1,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """插入新卡片，双版本 +1。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identities_data = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            nodes = _parse_draft_nodes(edited_text)

            insert_idx = len(nodes)
            if after_card_id:
                for idx, item in enumerate(identities_data):
                    if item["card_id"] == after_card_id:
                        insert_idx = idx + 1
                        break

            # 构造 raw line
            if kind == "line":
                raw_line = f"{payload.get('who', '')}: {payload.get('text', '')}\n"
            elif kind == "dir":
                raw_line = f"@{payload.get('cmd', '')} {payload.get('arg', '')}\n"
            elif kind == "scene":
                raw_line = f"## {payload.get('title', '')}\n"
            else:
                raw_line = f"{payload.get('text', '')}\n"

            from document import DocNode, serialize_document
            import uuid
            from draft_identity import generate_order_key

            new_node = DocNode(
                kind=kind,
                raw=raw_line,
                line_no=insert_idx + 1,
                fields=payload,
                dirty=True,
                eol="\n",
            )
            nodes.insert(insert_idx, new_node)

            new_card_id = str(uuid.uuid4())
            new_card_identity = {
                "card_id": new_card_id,
                "source_id": None,
                "origin": origin,
                "parent_id": None,
                "order_key": generate_order_key(insert_idx + 1),
                "text_fingerprint": compute_text_fingerprint(raw_line),
                "review_state": "pending",
            }
            identities_data.insert(insert_idx, new_card_identity)

            new_text = serialize_document(nodes)
            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")

            session["draft_version"] += 1
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def delete_card(
        self,
        token: str,
        card_id: str,
        expected_draft_version: int,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """删除卡片，双版本 +1。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identities_data = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            nodes = _parse_draft_nodes(edited_text)

            target_idx = -1
            for idx, item in enumerate(identities_data):
                if item["card_id"] == card_id:
                    target_idx = idx
                    break

            if target_idx == -1:
                raise KeyError(f"Card ID not found: {card_id}")

            nodes.pop(target_idx)
            identities_data.pop(target_idx)

            from document import serialize_document
            new_text = serialize_document(nodes)
            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")

            session["draft_version"] += 1
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def move_card(
        self,
        token: str,
        card_id: str,
        before_card_id: Optional[str],
        expected_draft_version: int,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """移动卡片到 before_card_id 之前（before_card_id=None 移到末尾）。

        移动改变文本行顺序，因此同时重排 edited.txt 节点与 identity 数组，
        并按新顺序重排 order_key，双版本 +1。
        """
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identities_data = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            nodes = _parse_draft_nodes(edited_text)

            if len(nodes) != len(identities_data):
                raise ValueError("Nodes and identities mismatched")

            ids = [item["card_id"] for item in identities_data]
            if card_id not in ids:
                raise KeyError(f"Card ID not found: {card_id}")
            if before_card_id is not None and before_card_id not in ids:
                raise KeyError(f"Before card ID not found: {before_card_id}")

            from_idx = ids.index(card_id)
            node_item = nodes.pop(from_idx)
            identity_item = identities_data.pop(from_idx)

            if before_card_id is not None and before_card_id != card_id:
                insert_at = ids.index(before_card_id)
                if insert_at > from_idx:
                    insert_at -= 1
            else:
                insert_at = len(nodes)

            nodes.insert(insert_at, node_item)
            identities_data.insert(insert_at, identity_item)

            from document import serialize_document
            from draft_identity import generate_order_key
            new_text = serialize_document(nodes)
            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")

            for i, card in enumerate(identities_data, 1):
                card["order_key"] = generate_order_key(i, len(identities_data))

            session["draft_version"] += 1
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def add_proposals(self, token: str, proposals: List[Dict[str, Any]]):
        """保存提议列表到 proposals.json"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            prop_file = draft_dir / "proposals.json"
            existing = []
            if prop_file.is_file():
                try:
                    existing = json.loads(prop_file.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            existing.extend(proposals)
            prop_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def handle_proposal(
        self,
        token: str,
        proposal_id: str,
        action: str,
        expected_draft_version: int,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """处理 proposal: approve | reject | accept。带有双版本控制与两类 Proposal 语义。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            prop_file = draft_dir / "proposals.json"
            if not prop_file.is_file():
                raise KeyError(f"No proposals found for draft {token}")

            proposals = json.loads(prop_file.read_text(encoding="utf-8"))
            target_prop = None
            for p in proposals:
                if p["proposal_id"] == proposal_id:
                    target_prop = p
                    break

            if not target_prop:
                raise KeyError(f"Proposal ID not found: {proposal_id}")

            if target_prop.get("state") != "pending":
                raise RevisionConflictError(f"Proposal {proposal_id} is not pending")

            if target_prop.get("based_on_content_revision") != session["content_revision"]:
                raise RevisionConflictError(f"Stale proposal for {proposal_id}")

            p_type = target_prop.get("type", "applied_pending")
            card_id = target_prop["card_id"]
            field_name = target_prop["field"]

            is_content_change = False
            patch = None

            if p_type == "applied_pending":
                if action == "approve":
                    target_prop["state"] = "approved"
                elif action == "reject":
                    target_prop["state"] = "rejected"
                    is_content_change = True
                    patch = {field_name: target_prop.get("before")}
            elif p_type == "suggested_fix":
                if action == "accept":
                    target_prop["state"] = "approved"
                    is_content_change = True
                    patch = {field_name: target_prop.get("after")}
                elif action == "reject":
                    target_prop["state"] = "rejected"

            prop_file.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")

        if is_content_change and patch:
            return self.update_card_content(
                token=token,
                card_id=card_id,
                patch=patch,
                expected_draft_version=expected_draft_version,
                cast=cast,
            )
        else:
            return self.update_card_review(
                token=token,
                card_id=card_id,
                review_state="approved" if action in ("approve", "accept") else "pending",
                expected_draft_version=expected_draft_version,
            )

    def assert_review_ready(self, token: str, cast: Optional[Dict[str, Any]] = None):
        """检查草稿是否符合 review_ready 门控。未通过抛出 ReviewPendingError(code="review_pending")"""
        draft = self.load_draft(token, cast=cast)
        session = draft["session"]
        annotation_status = normalize_annotation_status(session.get("annotation_status"))
        diagnostics = draft["diagnostics"]
        identities = draft["identities"]

        pending_count = sum(1 for c in identities if c.get("review_state") == "pending")
        # A user who explicitly approves every card may compile a partial AI
        # result.  This is an intentional review decision, not a silent bypass:
        # the session keeps the partial annotation status for display/audit.
        forced_review = bool(
            session.get("annotation_override_accepted") or pending_count == 0
        )
        if (
            (annotation_status["status"] != "complete" or annotation_status["pending_targets"] > 0)
            and not forced_review
        ):
            raise AnnotationIncompleteError(annotation_status)
        blocking_errors = sum(1 for d in diagnostics if d.get("severity") == "error")
        unresolved_issues = sum(1 for d in diagnostics if d.get("severity") in ("error", "warning"))

        counts = {
            "pending": pending_count,
            "unresolved_issues": unresolved_issues,
            "blocking_errors": blocking_errors,
        }

        if pending_count > 0 or blocking_errors > 0 or unresolved_issues > 0:
            raise ReviewPendingError(
                message=f"Draft {token} not ready: pending={pending_count}, blocking={blocking_errors}",
                code="review_pending",
                counts=counts,
            )
        return True

    def assert_annotation_complete(self, token: str) -> bool:
        with self.draft_lock(token):
            session_file = self.get_draft_path(token) / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))
            status = normalize_annotation_status(session.get("annotation_status"))
        if status["status"] != "complete" or status["pending_targets"] > 0:
            raise AnnotationIncompleteError(status)
        return True

    def batch_approve_reviews(
        self,
        token: str,
        card_ids: Optional[List[str]],
        expected_draft_version: int,
    ) -> Dict[str, Any]:
        """单事务批量批准低风险卡片：仅产生一次 draft_version +1"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            identity_file = draft_dir / "identity.json"
            identities_data = json.loads(identity_file.read_text(encoding="utf-8"))

            target_set = set(card_ids) if card_ids else set(c["card_id"] for c in identities_data)

            for card in identities_data:
                if card["card_id"] in target_set:
                    card["review_state"] = "approved"

            session["draft_version"] += 1
            if not any(card.get("review_state") == "pending" for card in identities_data):
                session["annotation_override_accepted"] = True

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            identity_file.write_text(identity_json_str, encoding="utf-8")
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            diagnostics = []
            diag_file = draft_dir / "diagnostics.json"
            if diag_file.is_file():
                diagnostics = json.loads(diag_file.read_text(encoding="utf-8"))

            return {
                "session": session,
                "edited_text": edited_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
            }

    def resolve_background_request(
        self,
        token: str,
        card_id: str,
        bg_name: str,
        expected_draft_version: int,
        cast: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """将草稿中的 background_request 节点原地同卡转换为 dir bg，保持 card_id 不变，双版本 +1。"""
        draft_dir = self.get_draft_path(token)
        with self.draft_lock(token):
            session_file = draft_dir / "session.json"
            session = json.loads(session_file.read_text(encoding="utf-8"))

            if session["draft_version"] != expected_draft_version:
                raise RevisionConflictError(
                    f"Draft version mismatch: expected {expected_draft_version}, got {session['draft_version']}"
                )

            edited_text = (draft_dir / "edited.txt").read_text(encoding="utf-8")
            identities_data = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
            nodes = _parse_draft_nodes(edited_text)

            target_idx = -1
            for idx, item in enumerate(identities_data):
                if item["card_id"] == card_id:
                    target_idx = idx
                    break

            if target_idx == -1:
                raise KeyError(f"Card ID not found: {card_id}")

            target_node = nodes[target_idx]
            target_node.kind = "dir"
            target_node.fields = {"cmd": "bg", "arg": bg_name}
            target_node.raw = f"@bg {bg_name}{target_node.eol}"
            target_node.dirty = True

            identities_data[target_idx]["review_state"] = "pending"
            identities_data[target_idx]["text_fingerprint"] = compute_text_fingerprint(target_node.raw)

            identity_by_node = {
                id(node): identity
                for node, identity in zip(nodes, identities_data)
            }
            node_count_before_normalize = len(nodes)
            nodes = normalize_draft_nodes(nodes)
            merged_backgrounds = node_count_before_normalize - len(nodes)
            identities_data = [identity_by_node[id(node)] for node in nodes]

            from document import serialize_document
            new_text = serialize_document(nodes)
            (draft_dir / "edited.txt").write_text(new_text, encoding="utf-8")

            session["draft_version"] += 1
            session["annotation_override_accepted"] = not any(
                card.get("review_state") == "pending" for card in identities_data
            )
            session["content_revision"] += 1

            identity_json_str = json.dumps(identities_data, ensure_ascii=False, indent=2)
            (draft_dir / "identity.json").write_text(identity_json_str, encoding="utf-8")

            _, diagnostics = compile_document(
                nodes, self._diagnostic_cast(token, cast), {}
            )
            with open(draft_dir / "diagnostics.json", "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, ensure_ascii=False, indent=2)

            session["edited_sha256"] = calc_sha256(new_text)
            session["identity_sha256"] = calc_sha256(identity_json_str)

            session_tmp = draft_dir / "session.json.tmp"
            session_final = draft_dir / "session.json"
            session_tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(session_tmp, session_final)

            return {
                "session": session,
                "edited_text": new_text,
                "identities": identities_data,
                "diagnostics": diagnostics,
                "identity_rebuilt": False,
                "merged_backgrounds": merged_backgrounds,
            }
