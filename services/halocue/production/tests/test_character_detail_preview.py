"""Exact character lookup supplies truthful capabilities from the frozen task."""

import json

import pytest

from halocue_production.service import ProductionService
from test_service import configured_resource_settings


@pytest.mark.parametrize("available", [True, False])
def test_character_detail_retains_frozen_preview_and_face_count(settings, tmp_path, available):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["characters"][0]["avatar"] = "Student_Portrait_Test"
    configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
    if available:
        folder = tmp_path / "out" / "official-previews"
        folder.mkdir(parents=True)
        (folder / "portrait.png").write_bytes(b"synthetic-thumbnail")
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "records": [
                        {"kind": "avatar", "key": "Student_Portrait_Test", "path": "portrait.png"}
                    ]
                }
            ),
            encoding="utf-8",
        )
    service = ProductionService(configured)
    try:
        created = service.create_run(
            {"project": "Frozen preview", "source": {"kind": "inline", "text": "爱丽丝: Hi."}}
        )
        run_id = created["run"]["run_id"]
        before = service.run_character_resource(run_id, "alice-school")
        assert before["character"]["preview_available"] is available
        assert before["character"]["face_count"] == 2
        assert "path" not in before["character"]
        index["characters"] = []
        configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
        assert service.run_character_resource(run_id, "alice-school") == before
        listed = service.list_run_resources(run_id, "characters")["items"][0]
        assert listed["preview_available"] is available
    finally:
        service.jobs.close()
