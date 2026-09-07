"""Reaction integrity failures must remain source-located and never publish drafts."""

import json
from dataclasses import replace

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


@pytest.fixture
def prepared(settings, tmp_path):
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {},
                "characters": [{"identifier": "synthetic", "name": "Synthetic", "faces": []}],
                "sounds": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(replace(settings, resource_index=index))
    result = service.create_run(
        {"project": "Synthetic reaction", "source": {"kind": "inline", "text": "旁白: 原文。\n"}}
    )
    mapped = service.update_cast(
        result["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": result["draft"]["draft_version"],
        },
    )
    yield service, mapped
    service.jobs.close()


class Provider:
    name = "synthetic"
    model = "synthetic"
    stats = {}


def test_reaction_validation_error_preserves_draft_and_located_details(prepared, monkeypatch):
    service, mapped = prepared
    token = mapped["run"]["draft_token"]
    diagnostic = {
        "code": "reaction.intent_lost",
        "severity": "error",
        "line_no": 1,
        "source_id": "source-original",
        "beat_id": "reaction-synthetic",
        "message": "目标不在镜头内",
    }

    class IntegrityFailure(ValueError):
        code = "reaction_intent_lost"
        details = {"diagnostics": [diagnostic]}

    def fail(*args, **kwargs):
        raise IntegrityFailure("反应目标没有被编译保留")

    monkeypatch.setattr(service.adapter._modules["annotate"], "annotate_script", fail)
    with pytest.raises(ProductionError) as rejected:
        service.adapter.execute_direction_generation(
            token=token,
            generation_id="direction-reaction-invalid",
            provider=Provider(),
            expected_draft_version=mapped["draft"]["draft_version"],
            story_type="auto",
            layout_mode="pure_ai",
        )
    assert rejected.value.code == "reaction_intent_lost"
    assert rejected.value.status == 409
    assert rejected.value.details["diagnostics"] == [diagnostic]
    current = service.adapter.draft_detail(token)
    assert current["draft_version"] == mapped["draft"]["draft_version"]
    assert [c["current"]["text"] for c in current["cards"] if c["kind"] == "line"] == ["原文。"]


def test_reaction_sidecar_remains_in_generation_audit_not_script(prepared, monkeypatch):
    service, mapped = prepared
    record = {
        "beat_id": "reaction-synthetic",
        "anchor_id": "source-original",
        "source_line": 1,
        "output_line": 2,
        "compiled_index": 1,
        "who": "Target",
        "face": "01",
        "emo": "",
        "act": "",
        "wait_ms": 1200,
    }
    result = {
        "text": "旁白: 原文。\n",
        "proposals": [],
        "direction_change_count": 1,
        "reaction_records": [record],
        "diagnostics": [],
    }
    monkeypatch.setattr(
        service.adapter._modules["annotate"], "annotate_script", lambda *a, **kw: result
    )
    staged = service.adapter.execute_direction_generation(
        token=mapped["run"]["draft_token"],
        generation_id="direction-reaction-audit",
        provider=Provider(),
        expected_draft_version=mapped["draft"]["draft_version"],
        story_type="auto",
        layout_mode="pure_ai",
    )
    saved = staged.summary["reaction_records"][0]
    assert {key: saved[key] for key in record} == record
    assert saved["source_card_id"] == mapped["draft"]["cards"][0]["card_id"]
    assert saved["source_id"] == mapped["draft"]["cards"][0]["source_id"]
    assert record["beat_id"] not in staged.result["text"]


def test_real_annotation_and_staging_preserve_reaction_target_and_source_card(
    settings, tmp_path, monkeypatch
):
    index = tmp_path / "reaction-index.json"
    characters = [
        {
            "identifier": name.lower(),
            "name": name,
            "club": "synthetic",
            "faces": [{"id": "01", "label": "smile"}],
        }
        for name in "AB"
    ]
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1},
                "sounds": [],
                "characters": characters,
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(replace(settings, resource_index=index))
    try:
        mapped = service.create_run(
            {
                "project": "Synthetic reaction pipeline",
                "source": {
                    "kind": "inline",
                    "text": "@camera_hold A\nA: 原文甲。\nB: 原文乙。\nA: 后续甲。\n",
                },
            }
        )
        run_id = mapped["run"]["run_id"]
        for name in "AB":
            mapped = service.update_cast(
                run_id,
                {
                    "speaker": name,
                    "mapping": {"kind": "portrait", "id": name.lower()},
                    "expected_draft_version": mapped["draft"]["draft_version"],
                },
            )
        source_card = next(c for c in mapped["draft"]["cards"] if c["kind"] == "line")

        class FakeProvider(Provider):
            cfg = {}

            def report(self):
                return "synthetic"

        def fake_agent(items, **kwargs):
            anchor = next(i for i in items if i["kind"] == "line")
            return {
                "rows_by_id": {},
                "beats": [
                    {
                        "anchor_id": anchor["annotation_id"],
                        "position": "after",
                        "who": "B",
                        "face": "01",
                        "emo": "",
                        "act": "",
                        "wait_ms": 1200,
                        "reason": "listener_reaction",
                    }
                ],
            }

        monkeypatch.setattr(
            service.adapter._modules["annotate"], "run_annotation_agent", fake_agent
        )
        staged = service.adapter.execute_direction_generation(
            token=mapped["run"]["draft_token"],
            generation_id="direction-reaction-real",
            provider=FakeProvider(),
            expected_draft_version=mapped["draft"]["draft_version"],
            story_type="auto",
            layout_mode="pure_ai",
        )
        record = staged.summary["reaction_records"][0]
        assert record["compiled_index"] == 1
        assert record["source_card_id"] == source_card["card_id"]
        service.adapter.commit_direction_generation(staged)
        current = service.adapter.draft_detail(mapped["run"]["draft_token"])
        lines = [c for c in current["cards"] if c["kind"] == "line"]
        assert [c["current"]["text"] for c in lines] == ["原文甲。", "", "原文乙。", "后续甲。"]
        assert lines[1]["current"]["who"] == "B"
        assert not [d for d in current["diagnostics"] if d["severity"] == "error"]
    finally:
        service.jobs.close()


@pytest.mark.parametrize("stale", [{}, {"portrait": False, "narrator": True}])
def test_explicit_portrait_binding_sets_compiler_flags(prepared, stale):
    service, mapped = prepared
    updated = service.update_cast(
        mapped["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "portrait", "id": "synthetic", **stale},
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    binding = service.adapter.store.load_cast(updated["run"]["draft_token"])["cast"]["旁白"]
    assert binding["portrait"] is True
    assert binding["narrator"] is False
