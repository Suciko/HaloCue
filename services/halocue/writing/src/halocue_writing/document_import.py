"""Explicit document preview and adoption into existing authoring artifacts."""

from pathlib import PurePath

from .errors import DomainError
from .workspace_access import workspace_operation


class DocumentImport:
    def __init__(self, service):
        self.service, self.data_access = service, service.data_access

    @workspace_operation
    def preview(self, payload):
        preview = self.service.preview_story_import(payload)
        return {
            **preview,
            "purposes": ["manuscript", "outline", "world", "world_draft", "reference"],
            "write_boundary": "preview_only",
        }

    @workspace_operation
    def adopt(self, payload):
        if payload.get("confirm") is not True:
            raise DomainError(
                "import_confirmation_required", "请先预览并确认导入位置。", status=409
            )
        preview = self.preview(payload)
        if payload.get("source_digest") != preview["source_digest"]:
            raise DomainError(
                "import_preview_changed", "文件与预览不一致，请重新预览。", status=409
            )
        purpose = payload.get("purpose")
        text = preview["normalized_text"]
        title = str(payload.get("title") or PurePath(preview["filename"]).stem)
        if purpose == "manuscript":
            staged = self.service.stage_story_import({**payload, "confirm": True})
            return self.service.adopt_story_import(
                {"import_id": staged["import_id"], "confirm": True, "title": title}
            )
        if len(text) > 500_000:
            raise DomainError(
                "import_too_large", "资料或大纲单次导入最多 50 万字，请按卷拆分。", status=422
            )
        if purpose == "world_draft":
            return {"world": self.service.authoring.save_world({"title": title, "overview": text})}
        work_id = str(payload.get("work_id") or "")
        self.service.get_work(work_id)
        expected = payload.get("expected_version")
        if purpose == "outline":
            scope_type = payload.get("scope_type", "work")
            scope_id = payload.get("scope_id", work_id)
            document = next(
                (
                    item
                    for item in self.service.authoring.get_outline(work_id)["documents"]
                    if item["scope_type"] == scope_type and item["scope_id"] == scope_id
                ),
                None,
            )
            if not document:
                raise DomainError("import_target_invalid", "大纲导入位置不存在。", status=422)
            return self.service.authoring.save_outline(
                work_id,
                {
                    "expected_version": expected,
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "expected_base_revision_id": payload.get("expected_base_revision_id"),
                    "text": "\n\n".join(filter(None, [document["text"], text])),
                },
            )
        if purpose == "world":
            current = self.service._current_world_bible(work_id)
            return self.service.save_world_bible(
                work_id,
                {
                    **current,
                    "expected_version": expected,
                    "overview": "\n\n".join(filter(None, [current.get("overview", ""), text])),
                },
            )
        if purpose == "reference":
            return self.service.create_reference_file(
                work_id,
                {
                    "expected_version": expected,
                    "title": title,
                    "content": text,
                    "source_label": preview["filename"],
                    "kind": "document",
                    "trust_status": "unverified",
                },
            )
        raise DomainError(
            "import_purpose_invalid", "请选择正文、大纲、世界观底稿或参考文件。", status=422
        )
