from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.prepare_blind_anchor_round import prepare_round


def make_scene(tmp_path: Path, name: str, *, header: bool = False) -> dict:
    source = tmp_path / f"{name}.txt"
    lines = (["## Blind scene"] if header else []) + [
        f"A: {name} line {index}" if index % 2 else f"B: {name} line {index}"
        for index in range(1, 13)
    ]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cast = tmp_path / f"{name}.cast.json"
    cast.write_text(json.dumps({"cast": {"A": {}, "B": {}}}), encoding="utf-8")
    return {
        "source_id": name,
        "directory": name,
        "source": str(source),
        "cast": str(cast),
        "story_type": "main",
        "output_stem_prefix": f"{name}-V4",
        "anchors": [
            {
                "anchor_id": f"anchor-{index}",
                "category": "generic blind category",
                "rationale": "selected from dialogue causality before official review",
                "start_dialogue": index,
                "end_dialogue": index + 3,
            }
            for index in (1, 4, 7)
        ],
    }


def make_spec(tmp_path: Path) -> Path:
    spec = {
        "campaign_id": "proactive-v4-test",
        "round_version": "V4",
        "selection_basis": "dialogue-only generic semantic anchors",
        "run_mode": "balanced",
        "provider": "codex-sol-subagent",
        "model": "gpt-5.6-sol",
        "scenes": [
            make_scene(tmp_path, "main-p03", header=True),
            make_scene(tmp_path, "codebox-seia"),
            make_scene(tmp_path, "main-3-1-7"),
        ],
    }
    path = tmp_path / "anchors.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_prepare_round_seals_windows_and_declares_sequential_jobs(tmp_path: Path):
    spec = make_spec(tmp_path)
    output = tmp_path / "campaign"

    manifest = prepare_round(spec, output)

    jobs = json.loads((output / "stage-a" / "jobs.json").read_text(encoding="utf-8"))
    assert manifest["campaign_id"] == "proactive-v4-test"
    assert manifest["execution_mode"] == "sequential"
    assert jobs["execution_mode"] == "sequential"
    assert len(jobs["jobs"]) == 9
    assert [job["name"] for job in jobs["jobs"][:3]] == [
        "main-p03-anchor-1", "main-p03-anchor-4", "main-p03-anchor-7",
    ]
    sealed = output / "stage-a" / "sealed-inputs" / "main-p03" / "anchor-1" / "dialogue.txt"
    assert sealed.read_text(encoding="utf-8").splitlines() == [
        "## Blind scene",
        "A: main-p03 line 1",
        "B: main-p03 line 2",
        "A: main-p03 line 3",
        "B: main-p03 line 4",
    ]


def test_prepare_round_is_idempotent_but_rejects_changed_sealed_input(tmp_path: Path):
    spec = make_spec(tmp_path)
    output = tmp_path / "campaign"
    prepare_round(spec, output)
    prepare_round(spec, output)

    source = tmp_path / "main-p03.txt"
    source.write_text(source.read_text(encoding="utf-8").replace("line 1", "changed"), encoding="utf-8")

    with pytest.raises(ValueError, match="sealed artifact differs"):
        prepare_round(spec, output)


def test_prepare_round_requires_three_to_four_anchors_per_scene(tmp_path: Path):
    spec_path = make_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["scenes"][0]["anchors"] = spec["scenes"][0]["anchors"][:2]
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ValueError, match="3 or 4 anchors"):
        prepare_round(spec_path, tmp_path / "campaign")


def test_scene_title_with_colon_is_header_not_dialogue(tmp_path: Path):
    source = tmp_path / "scene.txt"
    source.write_text("## Code:BOX: room\nA: first\nB: second\n", encoding="utf-8")

    from tools.prepare_blind_anchor_round import extract_window

    window, total = extract_window(source.read_text(encoding="utf-8"), 1, 2)

    assert total == 2
    assert window.splitlines() == ["## Code:BOX: room", "A: first", "B: second"]
