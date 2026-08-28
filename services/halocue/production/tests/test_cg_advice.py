import os
import time

from halocue_production.config import Settings
from halocue_production.service import ProductionService


def test_cg_advice_only_uses_the_author_selected_range_and_never_mutates_draft(settings, tmp_path, monkeypatch):
    index = tmp_path / "resources.json"
    index.write_text('{"bg":{},"sounds":[],"characters":[],"enums":{}}', encoding="utf-8")
    configured = Settings(
        project_root=settings.project_root,
        data_dir=settings.data_dir,
        legacy_root=settings.legacy_root,
        resource_index=index,
        aa_data=None,
        host="127.0.0.1",
        port=0,
    )
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )

    class FakeProvider:
        name = "fake"
        model = "cg-advice"
        stats = {"calls": 0}

        def complete_json(self, static, _volatile, user, _schema):
            assert static.startswith("You are a visual-novel CG consultant")
            assert "Author-selected range" in user
            self.stats["calls"] += 1
            return {
                "recommended": True,
                "reason": "这两句构成一个明确的情绪转折。",
                "story_beat": "emotional_peak",
                "image_prompt": "横向 16:9 的日系视觉小说 CG，表现两位角色在雨夜走廊停下脚步的瞬间。中近景，人物位于画面左右两侧，走廊尽头的冷色反光与窗外雨光形成纵深，保留克制而紧张的停顿感。",
                "reference_note": "如在图像生成时上传角色参考图，以参考图中的角色设计为准。",
                "continuity_notes": ["与前一张背景的雨夜色温保持连续。"],
                "generation_notes": ["先上传角色参考图和最终 CG，再回到此面板手动插入。"],
            }

    service.direction_models.provider = lambda: FakeProvider()
    created = service.create_run(
        {"project": "CG 咨询", "source": {"kind": "inline", "text": "旁白: 她停下了脚步。\n旁白: 雨声盖住了回答。\n"}}
    )
    cards = created["draft"]["cards"]
    before = service.run_detail(created["run"]["run_id"])["draft"]
    status, accepted = service.request_cg_advice(
        created["run"]["run_id"],
        {
            "start_card_id": cards[0]["card_id"],
            "end_card_id": cards[1]["card_id"],
            "expected_draft_version": before["draft_version"],
        },
    )
    assert status == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = service.job_detail(accepted["job"]["job_id"])["job"]
        if job["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert job["state"] == "succeeded", job
    assert job["result"]["read_only"] is True
    assert job["result"]["advice"]["recommended"] is True
    after = service.run_detail(created["run"]["run_id"])["draft"]
    assert after["draft_version"] == before["draft_version"]
    assert after["cg_segments"] == []
    service.jobs.close()
