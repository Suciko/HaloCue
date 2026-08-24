import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


def save_card(service, work, name, *, aliases=None, relationships=None, card_id=None):
    identity = {"card_id": card_id} if card_id else {}
    return service.save_character_card(
        work["id"],
        {
            **identity,
            "expected_version": work["version"],
            "name": name,
            "aliases": aliases or [],
            "role": f"{name}的当前作品职责",
            "relationships": relationships or [],
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )


def add_story_structure_revision(service, work_id):
    content = {
        "schema_version": "story-structure/1.0",
        "summary": "第一卷先确认异常来源。",
        "status": "accepted",
        "volumes": [
            {
                "id": "volume-stable",
                "title": "第一卷",
                "chapters": [
                    {
                        "id": "chapter-stable",
                        "title": "第一章",
                        "scenes": [
                            {
                                "id": "scene-stable",
                                "title": "门禁记录",
                                "contract": {"goal": "确认温室门禁记录。"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with service.repo.transaction() as connection:
        artifact = service._artifact(
            connection, work_id, "story_structure", "work", work_id
        )
        return service._add_revision(
            connection,
            artifact,
            content,
            "user",
            {"workflow": "test.story_structure"},
            schema_version="story-structure/1.0",
        )


def projection_fixture(service):
    work = service.create_work({"title": "当前作品投影"})
    kei = save_card(service, work, "凯伊", aliases=["Kei"])
    work = kei["work"]
    alice = save_card(service, work, "爱丽丝", aliases=["重复称呼"])
    work = alice["work"]
    yuuka = save_card(service, work, "优香", aliases=["重复称呼"])
    work = yuuka["work"]
    hoshino = save_card(
        service,
        work,
        "星野",
        relationships=[
            {
                "id": "relation-stable",
                "target_character_id": kei["card_id"],
                "target": "旧译名不参与解析",
                "kind": "队友",
            },
            {"id": "relation-legacy", "target": "Kei", "kind": "旧名称关系"},
            {"id": "relation-ambiguous", "target": "重复称呼", "kind": "待核对"},
            {"id": "relation-missing", "target": "不存在的人物", "kind": "待核对"},
        ],
    )
    work = hoshino["work"]
    world = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            "title": "本作世界观",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-greenhouse",
                    "name": "温室",
                    "kind": "place",
                    "summary": "夜间受门禁限制。",
                    "source": "用户确认",
                    "source_type": "custom",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊"],
                    "participant_character_ids": [kei["card_id"]],
                }
            ],
            "rules": [],
            "timeline": [
                {
                    "id": "event-curfew",
                    "text": "温室夜间门禁启动。",
                    "category": "当前剧情",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "participants": ["凯伊", "重复称呼", "不存在的人物"],
                    "participant_character_ids": [kei["card_id"]],
                }
            ],
        },
    )
    work = world["work"]
    canon = service.save_work_canon(
        work["id"],
        {
            "expected_version": work["version"],
            "facts": [
                {
                    "id": "fact-curfew",
                    "text": "门禁记录没有被删除。",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "scope": "work",
                }
            ],
        },
    )
    add_story_structure_revision(service, work["id"])
    return canon["work"], {
        "kei": kei,
        "alice": alice,
        "yuuka": yuuka,
        "hoshino": hoshino,
        "world": world,
    }


def test_current_projection_aggregates_current_revisions_with_explicit_resolution(tmp_path):
    service = WritingService(tmp_path)
    work, saved = projection_fixture(service)

    projection = service.get_current_projection(work["id"])

    assert projection["schema_version"] == "current-work-projection/1.0"
    assert projection["complete"] is True
    assert projection["unavailable_sources"] == []
    assert projection["source_set_digest"].startswith("sha256:")
    assert all(source["available"] for source in projection["source_revisions"])

    graph = projection["knowledge_graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    assert f"character:{saved['kei']['card_id']}" in node_ids
    assert "world_entity:world-greenhouse" in node_ids
    assert "timeline_event:event-curfew" in node_ids
    assert "canon_fact:fact-curfew" in node_ids

    stable = next(edge for edge in graph["edges"] if edge["source_ref"]["item_id"] == "relation-stable")
    legacy = next(edge for edge in graph["edges"] if edge["source_ref"]["item_id"] == "relation-legacy")
    assert stable["to"] == f"character:{saved['kei']['card_id']}"
    assert stable["resolution"] == "resolved"
    assert legacy["to"] == f"character:{saved['kei']['card_id']}"
    assert legacy["resolution"] == "legacy_name_resolved"
    participation = next(
        edge
        for edge in graph["edges"]
        if edge["type"] == "participation"
        and edge["to"] == "world_entity:world-greenhouse"
    )
    assert participation["from"] == f"character:{saved['kei']['card_id']}"
    assert participation["resolution"] == "resolved"

    unresolved = {item["source_ref"]["item_id"]: item for item in graph["unresolved_relationships"]}
    assert unresolved["relation-ambiguous"]["resolution"] == "ambiguous"
    assert unresolved["relation-ambiguous"]["candidate_character_ids"] == sorted(
        [saved["alice"]["card_id"], saved["yuuka"]["card_id"]]
    )
    assert unresolved["relation-missing"]["resolution"] == "unresolved"
    assert projection["timeline"]["events"][0]["id"] == "event-curfew"
    assert projection["story_structure"]["source_revision_id"]
    assert projection["story_structure"]["volumes"][0]["chapters"][0]["scenes"][0]["id"] == "scene-stable"


def test_current_projection_never_reads_superseded_revision_and_get_is_read_only(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "只读当前版本"})
    target = save_card(service, work, "凯伊")
    source = save_card(
        service,
        target["work"],
        "星野",
        relationships=[{"id": "old-link", "target_character_id": target["card_id"], "kind": "旧关系"}],
    )
    changed = save_card(
        service,
        source["work"],
        "星野",
        card_id=source["card_id"],
        relationships=[],
    )
    with service.repo.connect() as connection:
        before_revision_count = connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]
        before_version = connection.execute(
            "SELECT version FROM works WHERE id=?", (work["id"],)
        ).fetchone()[0]

    projection = service.get_current_projection(work["id"])

    assert not any(
        edge["source_ref"]["item_id"] == "old-link"
        for edge in projection["knowledge_graph"]["edges"]
    )
    current_source = next(
        item
        for item in projection["source_revisions"]
        if item["scope_id"] == source["card_id"]
    )
    assert current_source["revision_id"] == changed["revision_id"]
    with service.repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == before_revision_count
        assert connection.execute(
            "SELECT version FROM works WHERE id=?", (work["id"],)
        ).fetchone()[0] == before_version


def test_stable_character_relationship_survives_target_rename(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "改名不应断边"})
    target = save_card(service, work, "旧译名", card_id="character-kei")
    source = save_card(
        service,
        target["work"],
        "星野",
        relationships=[{
            "id": "relation-kei",
            "target_character_id": "character-kei",
            "target": "旧译名",
            "kind": "队友",
        }],
    )
    renamed = save_card(
        service,
        source["work"],
        "凯伊",
        aliases=["旧译名"],
        card_id="character-kei",
    )

    projection = service.get_current_projection(work["id"])

    target_node = next(
        node for node in projection["knowledge_graph"]["nodes"]
        if node["id"] == "character:character-kei"
    )
    edge = next(
        item for item in projection["knowledge_graph"]["edges"]
        if item["source_ref"]["item_id"] == "relation-kei"
    )
    assert target_node["label"] == "凯伊"
    assert edge["to"] == "character:character-kei"
    assert edge["resolution"] == "resolved"
    assert renamed["card_id"] == "character-kei"


def test_manual_structure_changes_create_current_story_structure_revisions(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "手工结构投影"})
    brief = service.save_brief(
        work["id"],
        {"expected_version": work["version"], "idea": "检查手工结构。", "mode": "bond_short"},
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {"expected_version": blueprint["work"]["version"], "title": "第一章"},
    )
    first_projection = service.get_current_projection(work["id"])
    first_revision_id = first_projection["story_structure"]["source_revision_id"]
    assert first_projection["story_structure"]["volumes"][0]["chapters"][0]["id"] == chapter["chapter_id"]

    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {"expected_version": chapter["work"]["version"], "title": "第一场", "goal": "确认变化"},
    )
    second_projection = service.get_current_projection(work["id"])
    structure = second_projection["story_structure"]
    assert structure["source_revision_id"] != first_revision_id
    assert structure["volumes"][0]["chapters"][0]["scenes"][0]["id"] == scene["scene_id"]
    artifact = next(
        item for item in scene["work"]["artifacts"] if item["kind"] == "story_structure"
    )
    assert [revision["ordinal"] for revision in artifact["revisions"]] == [2, 1]


def test_current_projection_survives_restart_and_rejects_corrupt_current_source(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "投影恢复"})
    first = save_card(service, work, "凯伊", card_id="character-kei")
    second = save_card(
        service,
        first["work"],
        "凯伊",
        aliases=["当前修订"],
        card_id="character-kei",
    )
    before_restart = service.get_current_projection(work["id"])
    restarted = WritingService(tmp_path)
    assert restarted.get_current_projection(work["id"]) == before_restart

    artifact = next(
        item
        for item in second["work"]["artifacts"]
        if item["kind"] == "character_card" and item["scope_id"] == "character-kei"
    )
    restarted.repo.atomic_write_text(
        artifact["current_revision"]["content_uri"],
        json.dumps({"name": "被篡改的当前修订"}, ensure_ascii=False) + "\n",
    )
    damaged = restarted.get_current_projection(work["id"])

    assert damaged["complete"] is False
    unavailable = next(item for item in damaged["unavailable_sources"] if item["scope_id"] == "character-kei")
    assert unavailable["revision_id"] == second["revision_id"]
    assert unavailable["reason"] == "content_hash_mismatch"
    assert not any(node["id"] == "character:character-kei" for node in damaged["knowledge_graph"]["nodes"])
    assert all(item["revision_id"] != first["revision_id"] for item in damaged["source_revisions"])


def test_current_projection_http_route_returns_versioned_contract(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "投影接口"})
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/current-projection"
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["ok"] is True
        assert payload["data"]["schema_version"] == "current-work-projection/1.0"
        assert payload["data"]["work_id"] == work["id"]
        assert set(payload["data"]) >= {
            "knowledge_graph",
            "timeline",
            "story_structure",
            "source_revisions",
            "source_set_digest",
            "complete",
            "unavailable_sources",
        }
    finally:
        server.shutdown()
        server.server_close()
