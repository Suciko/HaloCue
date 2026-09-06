from __future__ import annotations

"""Read-only adapter for the local Blue Archive reference corpus.

The writing workspace owns only its imported excerpts.  The corpus remains an
external evidence source and is never modified or treated as a confirmed canon
without a user decision.
"""

import json
from pathlib import Path

from .errors import DomainError


class OfficialReferenceCatalog:
    def __init__(self, corpus_dir: Path | None):
        self.corpus_dir = Path(corpus_dir).resolve() if corpus_dir else None
        self._recent: dict[str, dict] = {}

    @property
    def available(self) -> bool:
        if not self.corpus_dir:
            return False
        try:
            return self.corpus_dir.is_dir()
        except OSError:
            # A read-only corpus is optional evidence. Permission changes must
            # not make the work-owned library or writing service unavailable.
            return False

    def descriptor(self) -> dict:
        return {
            "available": self.available,
            "source_kind": "official_corpus_read_only",
            "corpus_dir": str(self.corpus_dir) if self.corpus_dir else None,
            "disclosure": "检索结果是原作语料索引，不会自动成为 WorkCanon、角色卡或世界规则。",
        }

    def search(self, query: str, limit: int = 12) -> list[dict]:
        needle = str(query or "").strip().casefold()
        if len(needle) < 2:
            raise DomainError("validation_error", "请至少输入两个字符后检索原作资料。", details={"field": "q"})
        if not self.available:
            raise DomainError("official_corpus_unavailable", "未配置可读取的 BA 原作语料库。", status=503)

        results: list[dict] = []
        for path in sorted(self.corpus_dir.glob("*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        item = self._summarize(record, path.name)
                        haystack = " ".join(
                            [
                                item["record_uid"],
                                item["character_name"],
                                item["story_title"],
                                item["zh_cn"],
                                " ".join(item["speakers"]),
                                item["source_file"],
                            ]
                        ).casefold()
                        if needle not in haystack:
                            continue
                        self._recent[item["record_uid"]] = item
                        results.append(item)
                        if len(results) >= limit:
                            return results
            except OSError as exc:
                raise DomainError("official_corpus_unavailable", "无法读取 BA 原作语料库。", status=503, details={"file": path.name}) from exc
        return results

    def get(self, record_uid: str) -> dict:
        uid = str(record_uid or "").strip()
        if not uid:
            raise DomainError("validation_error", "请选择一条原作资料。", details={"field": "record_uid"})
        if uid in self._recent:
            return self._recent[uid]
        if not self.available:
            raise DomainError("official_corpus_unavailable", "未配置可读取的 BA 原作语料库。", status=503)

        for path in sorted(self.corpus_dir.glob("*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if str(record.get("record_uid", "")) == uid:
                            item = self._summarize(record, path.name)
                            self._recent[uid] = item
                            return item
            except OSError as exc:
                raise DomainError("official_corpus_unavailable", "无法读取 BA 原作语料库。", status=503, details={"file": path.name}) from exc
        raise DomainError("official_reference_not_found", "这条原作资料已不存在或不在当前语料库中。", status=404, details={"record_uid": uid})

    @staticmethod
    def _summarize(record: dict, record_file: str) -> dict:
        membership = record.get("primary_story_membership") or {}
        text = record.get("text") or {}
        zh_cn = str(text.get("zh_cn") or "").strip()
        return {
            "record_uid": str(record.get("record_uid") or ""),
            "record_file": record_file,
            "source_file": str(record.get("source_file") or ""),
            "source_row_index": record.get("source_row_index"),
            "story_category": str(membership.get("category") or ""),
            "character_name": str(membership.get("character_name") or ""),
            "story_title": str(membership.get("title") or ""),
            "speakers": [str(value) for value in record.get("speakers", []) if str(value).strip()],
            "zh_cn": zh_cn[:2400],
            "localization_status": str(text.get("localization_status") or ""),
            "evidence_uri": f"official-corpus://{record_file}#{record.get('record_uid')}",
        }

    @staticmethod
    def render_import_excerpt(item: dict) -> str:
        lines = [
            "# BA 原作语料摘录",
            "",
            f"- 记录：{item['record_uid']}",
            f"- 原始文件：{item['source_file'] or item['record_file']}",
            f"- 原始行：{item['source_row_index'] if item['source_row_index'] is not None else '未提供'}",
            f"- 故事：{item['character_name']} / {item['story_title']}",
            f"- 类别：{item['story_category'] or '未提供'}",
            f"- 说话者：{'、'.join(item['speakers']) or '未提供'}",
            f"- 本地化状态：{item['localization_status'] or '未提供'}",
            "",
            "此文件是原作资料索引与摘录。它不是自动确认的作品事实；引用到人物卡、世界规则或 WorkCanon 前，必须由用户检查并明确保存。",
        ]
        if item["zh_cn"]:
            lines.extend(["", "## 中文摘录", "", item["zh_cn"]])
        else:
            lines.extend(["", "## 中文摘录", "", "该记录未提供官方中文文本；保留索引信息，供继续核对来源。"])
        return "\n".join(lines) + "\n"
