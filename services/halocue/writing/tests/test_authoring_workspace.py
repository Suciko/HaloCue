import json
import base64
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


def test_document_import_preview_and_append_guard(service):
    source = {"filename": "设定.md", "content_base64": base64.b64encode("只在雨夜开放。".encode()).decode()}
    preview = service.authoring.imports.preview(source)
    assert not service.list_works() and not service.authoring.list_worlds()
    request = {**source, "source_digest": preview["source_digest"], "confirm": True}
    world = service.authoring.imports.adopt({**request, "purpose": "world_draft"})["world"]
    assert world["content"]["overview"] == "只在雨夜开放。"
    work = service.create_work({})
    saved = service.authoring.save_outline(work["id"], {"expected_version": work["version"], "scope_type": "work", "scope_id": work["id"], "text": "原有大纲"})
    append = {**request, "purpose": "outline", "work_id": work["id"], "expected_version": saved["work"]["version"], "expected_base_revision_id": saved["revision_id"]}
    result = service.authoring.imports.adopt(append)
    assert result["outline"]["documents"][0]["text"] == "原有大纲\n\n只在雨夜开放。"
    with pytest.raises(DomainError) as caught:
        service.authoring.imports.adopt(append)
    assert caught.value.status == 409
    with pytest.raises(DomainError, match="预览不一致"):
        service.authoring.imports.adopt({**request, "source_digest": "changed", "purpose": "world_draft"})


def test_chapter_retry_reuses_completed_scene_and_uses_scoped_outline(service, monkeypatch):
    work = service.create_work({})
    chapter = work["chapters"][0]["id"]
    for index in range(2):
        made = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": str(index)})
        work = service.save_scene_manuscript(work["id"], made["scene_id"], {"expected_version": made["work"]["version"], "blocks": [{"id": f"block-{index}", "type": "narration", "text": "窗外下着雨。", "speaker": ""}]})["work"]
    saved = service.authoring.save_outline(work["id"], {"expected_version": work["version"], "scope_type": "chapter", "scope_id": chapter, "text": "本章追踪归还记录。"})
    work = saved["work"]
    first, second = [scene["id"] for scene in work["chapters"][0]["scenes"]]
    context = service.assemble_context(work["id"], first)
    assert any(item["text"] == "本章追踪归还记录。" for item in context["author_outline"])
    assert saved["revision_id"] in context["source_revision_ids"]
    original = service.review_scene
    called = []
    def interrupted(work_id, scene_id, payload):
        called.append(scene_id)
        if scene_id == second and called.count(second) == 1:
            raise DomainError("test_unavailable", "模拟暂时断线", status=503)
        return original(work_id, scene_id, payload)
    monkeypatch.setattr(service, "review_scene", interrupted)
    with pytest.raises(DomainError, match="模拟暂时断线"):
        service.authoring.chapters.run(work["id"], chapter, {"expected_version": work["version"]})
    failed = service.authoring.chapters.get(work["id"], chapter)
    assert failed["status"] == "failed" and failed["result"]["scene_ids"] == [first]
    result = service.authoring.chapters.run(work["id"], chapter, {"expected_version": service.get_work(work["id"])["version"]})
    assert result["review"]["id"] == failed["id"]
    assert result["review"]["status"] in {"awaiting_changes", "blocked"}
    assert called == [first, second, second]

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from halocue_writing.providers import FakeWritingProvider


@pytest.fixture
def service(tmp_path):
    value = WritingService(tmp_path / "authoring")
    yield value
    value.close()


def test_world_exists_before_work_and_copies_are_independent(service):
    draft = service.authoring.save_world(
        {"title": "长篇世界", "overview": "夜间档案只能双人核验。"}
    )
    assert not service.list_works()

    def copy():
        return service.create_work(
            {"world_draft_id": draft["id"], "world_draft_revision_id": draft["current_revision_id"]}
        )

    first, second = copy(), copy()
    first_world = next(a for a in first["artifacts"] if a["kind"] == "world_bible")
    assert first_world["current_revision"]["provenance"]["world_draft_id"] == draft["id"]
    service.save_world_bible(
        first["id"], {"expected_version": first["version"], "overview": "本作只有白天开放。"}
    )
    changed = service.authoring.save_world(
        {"expected_version": 1, "overview": "底稿新说明"}, draft["id"]
    )
    assert changed["version"] == 2 and len(changed["history"]) == 2
    assert service._current_world_bible(second["id"])["overview"] == "夜间档案只能双人核验。"
    assert service._current_world_bible(first["id"])["overview"] == "本作只有白天开放。"
    with pytest.raises(DomainError) as caught:
        copy()
    assert caught.value.status == 409


def test_world_conflict_and_restore_schema(service):
    draft = service.authoring.save_world({"world_seed": "ba_starter"})
    assert draft["content"]["entities"]
    with pytest.raises(DomainError) as caught:
        service.authoring.save_world({"expected_version": 0, "title": "错误覆盖"}, draft["id"])
    assert caught.value.status == 409
    service.repo.initialize_after_restore()
    assert service.authoring.get_world(draft["id"])["title"] == draft["title"]


def test_manual_structure_and_outline_do_not_require_ai(service):
    work = service.create_work({})
    assert work["title"] == "未命名作品"
    result = service.create_volume(
        work["id"], {"expected_version": work["version"], "title": "第二卷"}
    )
    result = service.create_chapter(
        work["id"],
        {
            "expected_version": result["work"]["version"],
            "volume_id": result["volume_id"],
            "title": "转折",
        },
    )
    chapter_id = result["chapter_id"]
    work = result["work"]
    saved = service.authoring.save_outline(
        work["id"],
        {
            "expected_version": work["version"],
            "scope_type": "chapter",
            "scope_id": chapter_id,
            "expected_base_revision_id": None,
            "text": "找到钥匙，但没有打开门。",
        },
    )
    doc = next(d for d in saved["outline"]["documents"] if d["scope_id"] == chapter_id)
    assert doc["text"] == "找到钥匙，但没有打开门。"
    assert len(doc["history"]) == 1
    assert all(not chapter["scenes"] for chapter in saved["work"]["chapters"])
    with pytest.raises(DomainError) as caught:
        service.authoring.save_outline(
            work["id"],
            {
                "expected_version": saved["work"]["version"],
                "scope_type": "chapter",
                "scope_id": chapter_id,
                "expected_base_revision_id": None,
                "text": "旧窗口覆盖",
            },
        )
    assert caught.value.code == "outline_conflict"


def test_outline_projects_adopted_direction_without_overwriting_user_text(service):
    work = service.create_work({"title": "长篇"})

    def direction(text):
        with service.repo.transaction() as conn:
            artifact = service._artifact(conn, work["id"], "story_blueprint", "work", work["id"])
            service._add_revision(
                conn, artifact, {"premise": text, "direction": ["相遇", "分歧"]}, "user", {}
            )

    direction("最初的构思")
    outline = service.authoring.get_outline(work["id"])
    assert "最初的构思" in outline["documents"][0]["text"]
    saved = service.authoring.save_outline(
        work["id"],
        {
            "expected_version": work["version"],
            "scope_type": "work",
            "scope_id": work["id"],
            "text": "作者自己的总纲",
        },
    )
    direction("后来的构思")
    doc = service.authoring.get_outline(work["id"])["documents"][0]
    assert doc["source_changed"] and "后来的构思" in doc["adopted_text"]
    assert doc["text"] == "作者自己的总纲" and doc["revision_id"] == saved["revision_id"]


def test_structure_goals_visible_in_outline_and_survive_manual_scene_add(service):
    work = service.create_work({})
    volume, chapter = work["volumes"][0], work["chapters"][0]
    with service.repo.transaction() as connection:
        artifact = service._artifact(connection, work["id"], "story_structure", "work", work["id"])
        service._add_revision(connection, artifact, {"status": "accepted", "summary": "追查未来的归还记录", "volumes": [{"id": volume["id"], "title": volume["title"], "goal": "卷目标：发现秘密", "chapters": [{"id": chapter["id"], "title": chapter["title"], "goal": "章目标：找到凭条", "scenes": []}]}]}, "user", {})
    result = service.create_scene(work["id"], chapter["id"], {"expected_version": work["version"], "title": "门口"})
    documents = service.authoring.get_outline(work["id"])["documents"]
    assert "卷目标：发现秘密" in next(item for item in documents if item["scope_type"] == "volume")["text"]
    assert "章目标：找到凭条" in next(item for item in documents if item["scope_type"] == "chapter")["text"]
    assert "追查未来的归还记录" in documents[0]["text"]
    assert result["scene_id"]


def test_world_and_outline_http_round_trip(service):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).parents[1] / "web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, payload=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            return json.load(response)["data"]

    try:
        draft = request("/world-drafts", {"title": "独立底稿", "overview": "世界说明"})
        assert request("/world-drafts")[0]["id"] == draft["id"]
        work = request(f"/world-drafts/{draft['id']}:create-work", {"expected_version": 1})["work"]
        assert request(f"/works/{work['id']}/outline")["documents"][0]["scope_type"] == "work"
        result = request(
            f"/works/{work['id']}/outline",
            {
                "scope_type": "work",
                "scope_id": work["id"],
                "expected_version": work["version"],
                "text": "全文总纲",
            },
        )
        assert result["outline"]["documents"][0]["text"] == "全文总纲"
    finally:
        server.shutdown()
        server.server_close()


def test_chapter_save_is_atomic_and_retains_stable_blocks(service):
    work = service.create_work({"title": "整章编辑"})
    chapter_id = work["chapters"][0]["id"]
    first = service.create_scene(
        work["id"], chapter_id, {"expected_version": work["version"], "title": "一"}
    )
    second = service.create_scene(
        work["id"], chapter_id, {"expected_version": first["work"]["version"], "title": "二"}
    )
    edits = [
        {
            "scene_id": item["scene_id"],
            "expected_base_revision_id": None,
            "blocks": [
                {"id": f"block-{i}", "type": "narration", "text": f"第{i}场正文", "speaker": ""}
            ],
        }
        for i, item in enumerate([first, second])
    ]
    edits[1]["expected_base_revision_id"] = "stale-revision"
    with pytest.raises(DomainError) as caught:
        service.authoring.save_chapter(
            work["id"], chapter_id, {"expected_version": second["work"]["version"], "scenes": edits}
        )
    assert caught.value.code == "manuscript_conflict"
    unchanged = service.get_work(work["id"])
    assert unchanged["version"] == second["work"]["version"]
    assert all(not s["current_revision_id"] for s in unchanged["chapters"][0]["scenes"])
    edits[1]["expected_base_revision_id"] = None
    saved = service.authoring.save_chapter(
        work["id"], chapter_id, {"expected_version": unchanged["version"], "scenes": edits}
    )
    assert len(saved["scene_revisions"]) == 2
    assert saved["work"]["version"] == unchanged["version"] + 1
    scripts = [
        a["current_revision"]["content"]
        for a in saved["work"]["artifacts"]
        if a["kind"] == "scene_script"
    ]
    assert {c["blocks"][0]["id"] for c in scripts} == {"block-0", "block-1"}


@pytest.mark.parametrize("change_manuscript", [False, True])
def test_queued_chapter_review_checks_pinned_inputs_instead_of_background_version(service, monkeypatch, change_manuscript):
    service.provider = FakeWritingProvider()
    service._schedule_commit_projection = lambda *_: None
    work = service.create_work({"title": "队列版本回归"})
    chapter = work["chapters"][0]["id"]
    added = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": "本场"})
    payload = {"expected_version": added["work"]["version"], "blocks": [{"id": "block-one", "type": "narration", "text": "灯亮了。", "speaker": ""}]}
    work = service.save_scene_manuscript(work["id"], added["scene_id"], payload)["work"]
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: {"started": False})
    job = service.enqueue_agent_operation(work["id"], {"operation": "chapter.review", "scope_id": chapter, "request": {"expected_version": work["version"]}})
    if change_manuscript:
        payload["expected_version"] = work["version"]
        payload["expected_base_revision_id"] = work["chapters"][0]["scenes"][0]["current_revision_id"]
        payload["blocks"][0]["text"] = "灯灭了。"
        service.save_scene_manuscript(work["id"], added["scene_id"], payload)
    else:
        with service.repo.transaction() as connection:
            service._bump_work(connection, work["id"], work["version"])
    service.agent_dispatcher.run_once()
    result = service.get_agent_job(work["id"], job["id"])
    assert result["status"] == ("failed" if change_manuscript else "succeeded"), result


def test_queued_chapter_review_keeps_other_chapters_out_and_accepts_changes(service):
    class RecordingProvider(FakeWritingProvider):
        def review_continuity(self, pack):
            self.chapter_scenes = [item["scene_id"] for item in pack["scenes"]]
            return super().review_continuity(pack)
    provider = RecordingProvider()
    service.provider = provider
    service._schedule_commit_projection = lambda *_: None
    work = service.create_work({"title": "多章审查"})
    chapter = work["chapters"][0]["id"]
    own_ids = []
    for index in range(2):
        added = service.create_scene(work["id"], chapter, {"expected_version": work["version"], "title": f"本章{index}"})
        own_ids.append(added["scene_id"])
        work = service.save_scene_manuscript(work["id"], added["scene_id"], {
            "expected_version": added["work"]["version"],
            "blocks": [{"id": f"block-{index}", "type": "narration", "text": f"记录第{index}件物品。", "speaker": ""}],
        })["work"]
    volume = service.create_volume(work["id"], {"expected_version": work["version"], "title": "其他卷"})
    other = service.create_scene(work["id"], volume["chapter_id"], {"expected_version": volume["work"]["version"], "title": "不应审查"})
    work = service.save_scene_manuscript(work["id"], other["scene_id"], {
        "expected_version": other["work"]["version"], "blocks": [{"id": "block-other", "type": "narration", "text": "无关正文", "speaker": ""}],
    })["work"]
    job = service.enqueue_agent_operation(work["id"], {"operation": "chapter.review", "scope_id": chapter,
                                                      "request": {"expected_version": work["version"]}})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = service.get_agent_job(work["id"], job["id"])
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    assert status["status"] == "succeeded", status
    review = service.authoring.chapters.get(work["id"], chapter)
    assert status["agent_run_id"] == review["result"]["agent_run_id"]
    assert provider.chapter_scenes == own_ids
    before = service.get_work(work["id"])
    accepted = service.authoring.chapters.decide(work["id"], chapter, {
        "review_id": review["id"], "expected_version": before["version"], "decision": "accept"})
    after = service.authoring.chapters.decide(work["id"], chapter, {
        "review_id": review["id"], "expected_version": accepted["work"]["version"], "decision": "accept"})
    assert after["work"]["version"] == accepted["work"]["version"]
    assert after["review"]["result"]["decision"] == "accept"
    items = service._assemble_work_review_pack(work["id"], "release.review")["memory_maintenance"]
    assert all(item["complete"] for item in items if item["scene_id"] in own_ids)
    assert not next(item for item in items if item["scene_id"] == other["scene_id"])["complete"]


def test_chapter_review_checks_all_scenes_and_one_change_decision(service):
    work = service.create_work({"title": "一章"})
    chapter_id = work["chapters"][0]["id"]
    for index in range(2):
        added = service.create_scene(
            work["id"], chapter_id, {"expected_version": work["version"], "title": f"场景{index}"}
        )
        work = service.save_scene_manuscript(
            work["id"],
            added["scene_id"],
            {
                "expected_version": added["work"]["version"],
                "blocks": [
                    {
                        "id": f"block-{index}",
                        "type": "narration",
                        "text": f"管理员记录第{index}件物品。",
                        "speaker": "",
                    }
                ],
            },
        )["work"]
    reviewed = service.authoring.chapters.run(
        work["id"], chapter_id, {"expected_version": work["version"]}
    )
    assert len(reviewed["review"]["result"]["scene_ids"]) == 2
    assert reviewed["review"]["proposal"]["scope_type"] == "chapter"
    assert reviewed["review"]["status"] in {"awaiting_changes", "blocked"}
    decided = service.authoring.chapters.decide(
        work["id"],
        chapter_id,
        {
            "review_id": reviewed["review"]["id"],
            "decision": "keep",
            "expected_version": reviewed["work"]["version"],
        },
    )
    pack = service._assemble_work_review_pack(work["id"], "release.review")
    assert all(item["complete"] for item in pack["memory_maintenance"])
    assert all(
        item["chapter_review_id"] == reviewed["review"]["id"] for item in pack["memory_maintenance"]
    )
    # Editing one scene invalidates the chapter-level evidence for the entire chapter.
    scene = decided["work"]["chapters"][0]["scenes"][0]
    service.save_scene_manuscript(
        work["id"],
        scene["id"],
        {
            "expected_version": decided["work"]["version"],
            "expected_base_revision_id": scene["current_revision_id"],
            "blocks": [
                {"id": "block-0", "type": "narration", "text": "管理员改写记录。", "speaker": ""}
            ],
        },
    )
    assert service.authoring.chapters.get(work["id"], chapter_id)["status"] == "stale"
    assert not all(
        item["complete"]
        for item in service._assemble_work_review_pack(work["id"], "release.review")[
            "memory_maintenance"
        ]
    )
