from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService
from test_direction_profiles import finished_job
from test_teacher_identity_service import select_teacher
from test_teacher_identity_delivery import files


@pytest.mark.parametrize("cg", [False, True])
def test_sel_release_review_build_install_and_switch_back(settings, tmp_path, cg):
    aa_data = tmp_path / "synthetic-aa"
    for part in ("projects", "saves", "settings", "overrides"):
        (aa_data / part).mkdir(parents=True)
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 0, "BG_CS_Fixture": 1},
                "characters": [],
                "sounds": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(replace(settings, aa_data=aa_data, resource_index=index))
    try:
        source = "SourceTeacher: Start.\nAliasTeacher: Continue.\nClerk: Welcome.\nSourceTeacher: Finish.\n"
        created = service.create_run(
            {
                "project": "Sel delivery",
                "source": {"kind": "inline", "text": source},
                "script_release": {
                    "id": "release-0123456789ab",
                    "display_version": "v1",
                    "content_hash": hashlib.sha256(source.encode()).hexdigest(),
                },
            }
        )
        run_id = created["run"]["run_id"]
        frozen_release = files(settings.data_dir / "releases")
        selected = select_teacher(
            service,
            created,
            presentation={"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        )
        selected = select_teacher(service, selected, speaker="AliasTeacher")
        selected = service.update_cast(
            run_id,
            {
                "speaker": "Clerk",
                "mapping": {"kind": "voice"},
                "expected_draft_version": selected["draft"]["draft_version"],
            },
        )
        if cg:
            cards = selected["draft"]["cards"]
            selected = service.create_cg_segment(
                run_id,
                {
                    "start_card_id": cards[0]["card_id"],
                    "end_card_id": cards[2]["card_id"],
                    "background_key": "BG_CS_Fixture",
                    "expected_draft_version": selected["draft"]["draft_version"],
                },
            )
        with pytest.raises(ProductionError) as blocked:
            service.compile(run_id, {"expected_draft_version": selected["draft"]["draft_version"]})
        assert blocked.value.code == "review_pending"
        approved = service.approve_review(
            run_id, {"card_ids": None, "expected_draft_version": selected["draft"]["draft_version"]}
        )
        preview = service.performance_preview(run_id)
        preview_replies = [
            frame["teacher_reply"] for frame in preview["frames"] if "teacher_reply" in frame
        ]
        before_compile = files(aa_data)
        _, submitted = service.compile(
            run_id, {"expected_draft_version": approved["draft"]["draft_version"]}
        )
        result = finished_job(service, submitted["job"]["job_id"])
        assert result["state"] == "succeeded", result
        assert files(aa_data) == before_compile
        draft_dir = settings.data_dir / "drafts" / approved["run"]["draft_token"]
        bundle = next(path.parent for path in (draft_dir / "builds").glob("*/*/bundle.complete"))
        project = json.loads(next(bundle.glob("*.aap")).read_text(encoding="utf-8"))
        selections = [
            node
            for node in project["nodes"]["$values"]
            if node["$type"].startswith("SelectionNodeData")
        ]
        assert [node["selectionTexts"]["$values"][0] for node in selections] == [
            "Start.",
            "Continue.",
            "Finish.",
        ]
        assert [node["Guid"] for node in selections] == [
            reply["reply_id"] for reply in preview_replies
        ]
        assert all(len(node["ConnectionsTo"]["$values"]) == 1 for node in selections)
        scripts = [
            row
            for node in project["nodes"]["$values"]
            for row in node.get("Scripts", {}).get("$values", [])
        ]
        assert [row["text"] for row in scripts if row["text"]] == ["Welcome."]
        plan = json.loads((bundle / "teacher-reply-plan.json").read_text(encoding="utf-8"))
        assert plan["presentation"]["mode"] == "sel_single"
        assert [row["card_id"] for row in plan["lines"]] == [
            row["card_id"] for row in created["draft"]["cards"]
        ]
        frozen_bundle = files(bundle)
        service.install(run_id, {"category": "", "story_name": None})
        installed = json.loads(
            (aa_data / "projects" / "Sel delivery.aap").read_text(encoding="utf-8")
        )
        assert installed == project
        switched = select_teacher(
            service,
            service.run_detail(run_id),
            presentation={"schema_version": "teacher-presentation/1.0", "mode": "slot_zero"},
        )
        assert switched["run"]["last_build_id"] is None
        assert (
            switched["draft"]["cast"]["teacher_identity"]
            == selected["draft"]["cast"]["teacher_identity"]
        )
        assert files(bundle) == frozen_bundle
        assert files(settings.data_dir / "releases") == frozen_release
        assert (draft_dir / "source.txt").read_text(encoding="utf-8") == source
    finally:
        service.jobs.close()
