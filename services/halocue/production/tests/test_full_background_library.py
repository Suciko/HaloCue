import json

import pytest

from halocue_production.service import ProductionService
from halocue_production.errors import ProductionError
from test_service import configured_resource_settings


def test_browse_full_library_and_adopt_only_selected_background(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    try:
        created = service.create_run({"project": "catalogue-test", "source": {"kind": "inline", "text": "## 教室\n@bg BG_Classroom\n旁白: 不改正文。\n"}})
        run = created["run"]["run_id"]
        token = service._run(run).draft_token
        path = service.adapter.store.get_draft_path(token) / "resources.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        original["bg"] = {"BG_Classroom": 3}
        path.write_text(json.dumps(original), encoding="utf-8")
        before = path.read_bytes()
        page = service.list_run_resources(run, "backgrounds", limit=1, filters={"scope": "library"})
        assert page["total"] == 4
        assert page["has_more"]
        assert service.list_run_resources(run, "backgrounds", filters={"scope": "library", "group": "scene"})["total"] == 3
        assert service.list_run_resources(run, "backgrounds", filters={"scope": "library", "group": "cg"})["total"] == 1
        assert path.read_bytes() == before
        assert service.list_run_resources(run, "backgrounds")["total"] == 1
        # Chinese search and subsequent pages must use the full catalogue.
        assert service.list_run_resources(run, "backgrounds", query="黑屏", filters={"scope": "library"})["items"][0]["key"] == "BG_Black"
        next_page = service.list_run_resources(run, "backgrounds", offset=1, limit=1, filters={"scope": "library"})
        assert page["items"][0]["key"] != next_page["items"][0]["key"]
        assert path.read_bytes() == before
        target = next(c for c in created["draft"]["cards"] if c["kind"] == "dir")
        version = created["draft"]["draft_version"]
        with pytest.raises(ProductionError):
            service.resolve_background_request(run, target["card_id"], {"background_key": "BG_RainyStation", "expected_draft_version": version - 1})
        assert path.read_bytes() == before
        with pytest.raises(ProductionError):
            service.resolve_background_request(run, "missing-card", {"background_key": "BG_RainyStation", "expected_draft_version": version})
        assert path.read_bytes() == before
        updated = service.resolve_background_request(run, target["card_id"], {"background_key": "BG_RainyStation", "expected_draft_version": version})
        frozen = json.loads(path.read_text(encoding="utf-8"))
        assert frozen["bg"] == {"BG_Classroom": 3, "BG_RainyStation": 2}
        assert frozen["characters"] == original["characters"]
        assert next(c for c in updated["draft"]["cards"] if c["card_id"] == target["card_id"])["current"]["arg"] == "BG_RainyStation"
    finally:
        service.jobs.close()


def test_insert_background_adopts_and_failed_insert_restores_snapshot(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    try:
        created = service.create_run({"project": "insert-test", "source": {"kind": "inline", "text": "## 教室\n旁白: 原文。\n"}})
        run = created["run"]["run_id"]
        path = service.adapter.store.get_draft_path(service._run(run).draft_token) / "resources.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["bg"] = {}
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        payload = {"kind": "dir", "fields": {"cmd": "bg", "arg": "BG_Classroom"}, "expected_draft_version": created["draft"]["draft_version"]}
        with pytest.raises(ProductionError):
            service.insert_card(run, {**payload, "after_card_id": "missing"})
        assert path.read_bytes() == before
        result = service.insert_card(run, {**payload, "after_card_id": created["draft"]["cards"][0]["card_id"]})
        assert json.loads(path.read_text(encoding="utf-8"))["bg"] == {"BG_Classroom": 3}
        assert any(c["current"].get("arg") == "BG_Classroom" for c in result["draft"]["cards"])
    finally:
        service.jobs.close()


def test_builtin_black_background_needs_no_asset_library(settings):
    service = ProductionService(settings)
    try:
        created = service.create_run({"project": "black-screen", "source": {"kind": "inline", "text": "## 废站\n旁白: 风停了。\n"}})
        run = created["run"]["run_id"]
        scene = next(card for card in created["draft"]["cards"] if card["kind"] == "scene")
        result = service.insert_card(run, {
            "after_card_id": scene["card_id"],
            "kind": "dir",
            "fields": {"cmd": "bg", "arg": "BG_Black"},
            "expected_draft_version": created["draft"]["draft_version"],
        })
        assert any(card["current"].get("arg") == "BG_Black" for card in result["draft"]["cards"])
    finally:
        service.jobs.close()
