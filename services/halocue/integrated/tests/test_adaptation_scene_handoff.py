"""Synthetic original-prose to normal frozen scene to Production HTTP handoff."""

import base64
import json
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
for context in ("writing", "production", "integrated"):
    sys.path.insert(0, str(REPO / "services/halocue" / context / "src"))

from halocue_integrated.server import IntegratedRuntime  # noqa: E402
from halocue_writing.providers import FakeWritingProvider  # noqa: E402
from halocue_writing.workflow_pack import ENGINE_RULE_SOURCE, MODE_SOURCES, WORKFLOW_RULE_SOURCES  # noqa: E402


def test_adopted_scene_passes_normal_review_freeze_and_production_handoff(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    paths = [path for group in WORKFLOW_RULE_SOURCES.values() for path in group]
    paths += list(MODE_SOURCES.values()) + [ENGINE_RULE_SOURCE, "knowledge/老师在场规则.md"]
    for relative in paths:
        target = rules / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic rule, not official source.\n", encoding="utf-8")
    monkeypatch.setenv("HALOCUE_BA_WRITING_SKILL_DIR", str(rules))
    index = tmp_path / "resources.json"
    index.write_text(json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8")
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=index,
    )
    runtime.start_upstreams()
    gateway = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    gateway.start()
    writing = runtime.writing_service
    writing.agent_dispatcher.close()
    try:
        assert runtime.production_service.settings.legacy_root.is_relative_to(tmp_path)
        work = writing.create_work({"title": "Synthetic chapter adoption"})
        brief = writing.save_brief(
            work["id"],
            {
                "expected_version": work["version"],
                "idea": "忠实改编已提供的门前片段",
                "mode": "bond_short",
                "characters": ["老师"],
            },
        )
        blueprint = writing.generate_blueprint(
            work["id"], {"expected_version": brief["work"]["version"]}
        )
        work = blueprint["work"]
        request = {
            "filename": "novel.txt",
            "content_base64": base64.b64encode(
                "第一章 起点\n老师在门口停下，门里的灯亮着。".encode()
            ).decode(),
        }
        preview = writing.sources.preview(work["id"], request)
        source = writing.sources.apply(
            work["id"], {**request, "preview_digest": preview["preview_digest"]}
        )["source"]
        adaptation = writing.adaptations.create(work["id"], {"source_version_id": source["id"]})
        writing.adaptations.approve_plan(
            adaptation["id"], {"plan_digest": adaptation["plan_digest"]}
        )
        chapter = source["chapters"][0]
        paragraph = chapter["paragraphs"][0]
        expected = "老师: 我们进去看看。\n旁白: 门前的灯亮着。\n"

        class Provider(FakeWritingProvider):
            def generate_scene(self, context):
                return json.dumps(
                    {
                        "schema_version": "adaptation-chapter/1.0",
                        "text": expected,
                        "source_refs": [
                            {"paragraph_id": paragraph["id"], "quote": paragraph["text"]}
                        ],
                        "deviations": [],
                        "open_threads": [],
                    }
                )

        writing.provider = Provider()
        proposed = writing.adaptations.generate_chapter_candidate(adaptation["id"], chapter["id"])
        accepted = writing.accept_proposal(
            work["id"], proposed["proposal_id"], {"expected_version": work["version"]}
        )
        scene_id = accepted["scene_id"]
        writing.provider = FakeWritingProvider()
        reviewed = writing.review_scene(
            work["id"], scene_id, {"expected_version": accepted["work"]["version"]}
        )
        maintenance = writing.skip_scene_memory_maintenance(
            work["id"],
            scene_id,
            {"expected_version": reviewed["work"]["version"], "note": "Synthetic explicit skip"},
        )
        continuity = writing.review_continuity(
            work["id"], {"expected_version": maintenance["work"]["version"]}
        )
        release_review = writing.review_release(
            work["id"], {"expected_version": continuity["work"]["version"]}
        )
        frozen = writing.freeze_release(
            work["id"], {"expected_version": release_review["work"]["version"]}
        )
        release_id = frozen["release_id"]
        with writing.repo.connect() as c:
            release = c.execute(
                "SELECT * FROM script_releases WHERE id=?", (release_id,)
            ).fetchone()
            revision = c.execute(
                "SELECT * FROM revisions WHERE id=?", (accepted["revision_id"],)
            ).fetchone()
        manifest = json.loads(writing.repo.read_text(release["manifest_uri"]))
        assert accepted["revision_id"] in json.dumps(manifest)
        assert expected.strip() in writing.repo.read_text(release["content_uri"])
        provenance = json.loads(revision["provenance_json"])
        assert provenance["source_version_id"] == source["id"]
        assert provenance["source_refs"][0]["paragraph_id"] == paragraph["id"]
        handoff = writing.handoff_release(release_id)
        run = runtime.production_service.repository.get_run(handoff["production_run_id"])
        assert run.source_summary["upstream_release"]["release_id"] == release_id
        draft = runtime.production_service.adapter.store.load_draft(run.draft_token)
        assert "我们进去看看" in json.dumps(draft, ensure_ascii=False)
        assert "门前的灯亮着" in json.dumps(draft, ensure_ascii=False)
    finally:
        runtime.close()
        gateway.join(3)
