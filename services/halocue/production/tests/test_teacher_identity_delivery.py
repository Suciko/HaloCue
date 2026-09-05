from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService
from test_direction_profiles import finished_job
from test_teacher_identity_service import select_teacher


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("cg", [False, True])
def test_release_teacher_review_bundle_and_explicit_install(settings, tmp_path, cg):
    aa_data = tmp_path / "synthetic-aa"
    for name in ("projects", "saves", "settings", "overrides"):
        (aa_data / name).mkdir(parents=True)
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 0, "BG_CS_Fixture": 1},
                "sounds": [],
                "characters": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(replace(settings, aa_data=aa_data, resource_index=index))
    try:
        source = "SourceTeacher: Keep the released text.\n"
        release = {
            "id": "release-0123456789ab",
            "display_version": "v1",
            "content_hash": hashlib.sha256(source.encode()).hexdigest(),
        }
        created = service.create_run(
            {
                "project": "Teacher delivery",
                "source": {"kind": "inline", "text": source},
                "script_release": release,
            }
        )
        frozen_release = files(settings.data_dir / "releases")
        selected = select_teacher(service, created)
        run_id = selected["run"]["run_id"]
        identifier = selected["draft"]["cast"]["teacher_identity"]["character_id"]
        if cg:
            card = selected["draft"]["cards"][0]
            selected = service.create_cg_segment(
                run_id,
                {
                    "start_card_id": card["card_id"],
                    "end_card_id": card["card_id"],
                    "background_key": "BG_CS_Fixture",
                    "label": "Fixture CG",
                    "expected_draft_version": selected["draft"]["draft_version"],
                },
            )
        with pytest.raises(ProductionError) as blocked:
            service.compile(run_id, {"expected_draft_version": selected["draft"]["draft_version"]})
        assert blocked.value.code == "review_pending"
        approved = service.approve_review(
            run_id, {"card_ids": None, "expected_draft_version": selected["draft"]["draft_version"]}
        )
        before_compile = files(aa_data)
        status, submitted = service.compile(
            run_id, {"expected_draft_version": approved["draft"]["draft_version"]}
        )
        assert status == 202
        job = finished_job(service, submitted["job"]["job_id"])
        assert job["state"] == "succeeded", job
        assert files(aa_data) == before_compile
        bundles = settings.data_dir / "drafts" / approved["run"]["draft_token"] / "builds"
        bundle = next(p.parent for p in bundles.glob("*/*/bundle.complete"))
        manifest = json.loads((bundle / "project" / "manifest.json").read_text(encoding="utf-8"))
        teacher = next(
            item for item in manifest["CharacterOverrides"] if item["Identifier"] == identifier
        )
        assert (teacher["Name"], teacher["Nickname"]) == ("老师", "沙勒")
        assert not teacher["SpinePortraitPath"]
        aap = json.loads(next(bundle.glob("*.aap")).read_text(encoding="utf-8"))
        rows = [
            row
            for node in aap["nodes"]["$values"]
            for row in node.get("Scripts", {}).get("$values", [])
        ]
        spoken = next(row for row in rows if row.get("text") == "Keep the released text.")
        assert spoken["speakerSlotNum"] == 0
        assert spoken["characters"]["$values"][0]["name"] == identifier
        frozen_bundle = files(bundle)
        service.install(run_id, {"category": "", "story_name": None})
        installed = json.loads(
            (aa_data / "projects" / "Teacher delivery" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert teacher in installed["CharacterOverrides"]
        renamed = select_teacher(
            service,
            service.run_detail(run_id),
            preset="custom",
            display_name="Guide",
            organization="",
        )
        assert renamed["draft"]["cast"]["teacher_identity"]["character_id"] == identifier
        assert renamed["run"]["last_build_id"] is None
        assert files(bundle) == frozen_bundle
        assert files(settings.data_dir / "releases") == frozen_release
    finally:
        service.jobs.close()
