"""Static, draft and compile gates share source-located Pending diagnostics."""

from dataclasses import replace
import json

import pytest

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


@pytest.fixture
def service(settings, isolated_legacy_root, tmp_path):
    index = isolated_legacy_root / "aa_resources.json"
    index.write_text(
        json.dumps({"bg": {}, "sounds": ["synthetic_se"], "characters": []}), encoding="utf-8"
    )
    workspace = tmp_path / "synthetic-aa"
    for name in ("projects", "saves", "overrides", "settings"):
        (workspace / name).mkdir(parents=True)
    instance = ProductionService(
        replace(settings, legacy_root=isolated_legacy_root, resource_index=index, aa_data=workspace)
    )
    try:
        yield instance
    finally:
        instance.jobs.close()


def locations(issues):
    return [
        (item["code"], item["line_no"], item["severity"])
        for item in issues
        if item["code"] == "dir.unconsumed"
    ]


@pytest.mark.parametrize("boundary", ["", "## Next\nNarrator: After.\n", "---\nNarrator: After.\n"])
def test_static_preflight_and_compile_agree(service, boundary):
    text = "Narrator: Before.\n@wait 100\n@se synthetic_se\n@clearst\n" + boundary
    result = service.preflight_source({"source": {"kind": "inline", "text": text}})
    document = service.adapter.document
    _, diagnostics = document.compile_document(
        document.parse_document_lossless(text), {"Narrator": {"narrator": True}}
    )
    expected = [("dir.unconsumed", line, "error") for line in (2, 3, 4)]
    assert locations(result["directives"]["issues"]) == expected
    assert locations(diagnostics) == expected
    assert result["directives"]["recognized"] == 3
    assert any(action["id"] == "repair_source" for action in result["actions"])


def test_static_preserves_invalid_issues_and_accepts_attached_and_persistent(service):
    text = "@unknown value\n@wait\n@!\n@clearst\nNarrator: After.\n@bg BG_Black\n@trans 0\n@bgm 999\n@music 999\n@bgfx 0\n@stage Actor@2\n@auto\n@camera_hold -\n"
    issues = service.preflight_source({"source": {"kind": "inline", "text": text}})["directives"][
        "issues"
    ]
    assert {item["code"] for item in issues} == {
        "unknown_directive",
        "missing_directive_argument",
        "invalid_directive",
    }
    assert locations(issues) == []


def create_mapped_run(service, text):
    created = service.create_run(
        {"project": "Synthetic terminal directives", "source": {"kind": "inline", "text": text}}
    )
    return service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "Narrator",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )


def test_exact_card_source_ids_block_review_and_compile(service):
    mapped = create_mapped_run(
        service, "Narrator: Before.\n@wait 100\n@se synthetic_se\n@clearst\n"
    )
    run_id = mapped["run"]["run_id"]
    original_ids = [(card["card_id"], card["source_id"]) for card in mapped["draft"]["cards"]]
    approved = service.approve_review(
        run_id, {"card_ids": None, "expected_draft_version": mapped["draft"]["draft_version"]}
    )
    draft = approved["draft"]
    assert draft["counts"]["blocking_errors"] == 3
    assert draft["counts"]["pending"] == 0
    assert not draft["review_ready"]
    assert approved["run"]["state"] == "waiting_for_review"
    assert [(card["card_id"], card["source_id"]) for card in draft["cards"]] == original_ids
    for card in draft["cards"]:
        assert card["source_id"]
        expected = [] if card["kind"] == "line" else [("dir.unconsumed", card["line_no"], "error")]
        assert locations(card["issues"]) == expected
    validation = service.adapter.validate(approved["run"]["draft_token"])
    assert {"code": "blocking_diagnostics", "count": 3} in validation["blockers"]
    with pytest.raises(ProductionError) as error:
        service.compile(run_id, {"expected_draft_version": draft["draft_version"]})
    assert error.value.code == "review_pending"
    assert error.value.details["blocking_errors"] == 3


def test_compile_revalidates_a_previously_ready_draft(service):
    mapped = create_mapped_run(service, "Narrator: Before.\n@camera_hold -\n")
    run_id = mapped["run"]["run_id"]
    approved = service.approve_review(
        run_id, {"card_ids": None, "expected_draft_version": mapped["draft"]["draft_version"]}
    )
    assert approved["run"]["state"] == "ready_to_compile"
    token = approved["run"]["draft_token"]
    card = approved["draft"]["cards"][-1]
    # Use the real draft store to simulate a persisted edit with a stale ready run.
    service.adapter.store.update_card_content(
        token=token,
        card_id=card["card_id"],
        patch={"cmd": "wait", "arg": "100"},
        expected_draft_version=approved["draft"]["draft_version"],
    )
    current = service.adapter.draft_detail(token)
    service.adapter.approve_cards(
        token=token, card_ids=None, expected_draft_version=current["draft_version"]
    )
    current = service.adapter.draft_detail(token)
    assert current["counts"]["pending"] == 0
    assert service._run(run_id).state == "ready_to_compile"
    with pytest.raises(ProductionError) as error:
        service.compile(run_id, {"expected_draft_version": current["draft_version"]})
    assert error.value.code == "review_pending"
    assert error.value.details["blocking_errors"] == 1
    assert service._run(run_id).pending_build_id is None
