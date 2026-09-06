from __future__ import annotations

from halocue_writing.agent_tools import ToolExecutionContext
from halocue_writing.service import WritingService


def save_card(service: WritingService, work: dict, *, role: str) -> dict:
    return service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": role,
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )


def test_projection_search_returns_current_formal_revision(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料投影检索"})
    saved = save_card(service, work, role="负责判断旧终端的调查风险。")
    service.run_commit_projection(
        work["id"], saved["revision_id"], projection_kinds=["search"]
    )

    result = service.search_commit_projections(
        work["id"], "凯伊", artifact_kinds=["character_card"]
    )

    assert result["schema_version"] == "commit-projection-search/1.0"
    assert result["complete"] is True
    assert result["source_revision_count"] == 1
    assert result["searched_revision_count"] == 1
    assert len(result["results"]) == 1
    match = result["results"][0]
    assert match["source"]["kind"] == "character_card"
    assert match["source"]["revision_id"] == saved["revision_id"]
    assert match["content"]["name"] == "凯伊"
    assert match["content"]["role"] == "负责判断旧终端的调查风险。"
    assert match["projection"]["output_hash"]


def test_projection_search_never_returns_superseded_revision(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料投影当前版本"})
    first = save_card(service, work, role="旧版职责：记录温室门禁。")
    service.run_commit_projection(
        work["id"], first["revision_id"], projection_kinds=["search"]
    )
    second = save_card(
        service,
        first["work"],
        role="新版职责：检查封闭空间中的警觉反应。",
    )
    service.run_commit_projection(
        work["id"], second["revision_id"], projection_kinds=["search"]
    )

    old = service.search_commit_projections(
        work["id"], "记录温室门禁", artifact_kinds=["character_card"]
    )
    current = service.search_commit_projections(
        work["id"], "封闭空间", artifact_kinds=["character_card"]
    )

    assert old["results"] == []
    assert [item["source"]["revision_id"] for item in current["results"]] == [
        second["revision_id"]
    ]


def test_projection_search_rejects_corrupt_derivative_without_hiding_source(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料投影完整性"})
    saved = save_card(service, work, role="负责检查资料完整性。")
    projection = service.run_commit_projection(
        work["id"], saved["revision_id"], projection_kinds=["search"]
    )
    search_item = next(item for item in projection["items"] if item["kind"] == "search")
    service.repo.atomic_write_text(search_item["output_ref"], "{}\n")

    result = service.search_commit_projections(
        work["id"], "凯伊", artifact_kinds=["character_card"]
    )

    assert result["complete"] is False
    assert result["searched_revision_count"] == 0
    assert result["results"] == []
    assert result["unavailable"] == [
        {
            "kind": "character_card",
            "scope_type": "character",
            "scope_id": "character-kei",
            "revision_id": saved["revision_id"],
            "reason": "integrity_failed",
        }
    ]


def test_agent_tool_falls_back_to_formal_revision_when_index_is_unavailable(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料检索回退"})
    saved = save_card(service, work, role="负责保留正式资料回退路径。")
    projection = service.get_commit_projection(work["id"], saved["revision_id"])
    with service.repo.transaction() as connection:
        connection.execute(
            """UPDATE commit_projection_items
               SET status='pending',output_ref=NULL,output_hash=NULL
               WHERE projection_id=? AND kind='search'""",
            (projection["id"],),
        )
        connection.execute(
            "UPDATE commit_projections SET status='pending' WHERE id=?",
            (projection["id"],),
        )
    with service.repo.connect() as connection:
        thread = service.get_work(work["id"])["conversation_threads"][0]
        context = ToolExecutionContext(
            connection=connection,
            service=service,
            work_id=work["id"],
            thread_id=thread["id"],
            scope_type="work",
            scope_id=work["id"],
            permission_mode="review",
        )
        result = service.agent_tools.execute(
            context,
            "search_character_cards",
            {"query": "凯伊"},
        )

    assert result.status == "succeeded"
    assert result.output[0]["content"]["name"] == "凯伊"
