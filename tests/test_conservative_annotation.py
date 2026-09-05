import json
from pathlib import Path

import pytest

import llm
import annotate


def options(tmp_path, *, profile="conservative", source="## rooftop evening\nKai: hello\n"):
    script = tmp_path / "scene.txt"
    script.write_text(source, encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(
        json.dumps(
            {
                "default_bg": "BG_Black",
                "scene_bg": {},
                "cast": {"Kai": {"id": "kai", "portrait": True}},
                "alias": {},
            }
        ),
        encoding="utf-8",
    )
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1, "BG_Roof": 1, "BG_Classroom": 100},
                "bg_label": {"BG_Roof": "rooftop evening", "BG_Classroom": "classroom morning"},
                "sounds": [],
                "characters": [{"identifier": "kai", "faces": []}],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "llm.json"
    config.write_text("{}", encoding="utf-8")
    return {
        "script": str(script),
        "cast": str(cast),
        "index": str(index),
        "llm": str(config),
        "out": str(tmp_path / "annotated.txt"),
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "agent_enabled": True,
        "direction_profile": profile,
    }


def test_conservative_generation_fills_missing_background_from_frozen_labels(tmp_path):
    result = annotate.annotate_script(options(tmp_path), provider_instance=llm.MockProvider({}))

    assert "@bg BG_Roof" in result["text"]
    assert "Kai: hello" in result["text"]
    assert "待生成自定义背景" not in result["text"]
    assert any(d["code"] == "background_approximate_match" for d in result["diagnostics"])


class BackgroundProvider(llm.MockProvider):
    def __init__(self, background="", request=""):
        super().__init__({})
        self.background = background
        self.request = request
        self.prompts = []

    def complete_json(self, static, volatile, user, schema):
        self.prompts.append((static, volatile))
        result = super().complete_json(static, volatile, user, schema)
        if result["lines"]:
            result["lines"][0].update(bg=self.background, bg_request=self.request)
        return result


def test_conservative_valid_model_background_wins_and_request_becomes_advice(tmp_path):
    result = annotate.annotate_script(
        options(tmp_path),
        provider_instance=BackgroundProvider("BG_Roof", "rooftop evening"),
    )

    assert result["text"].count("@bg BG_Roof") == 1
    assert "待生成自定义背景" not in result["text"]
    assert any(d["code"] == "background_approximate_match" for d in result["diagnostics"])


def test_standard_keeps_its_existing_missing_background_workflow(tmp_path):
    result = annotate.annotate_script(
        options(tmp_path, profile="standard"),
        provider_instance=BackgroundProvider("BG_Roof", "rooftop evening"),
    )

    assert "@bg" not in result["text"]
    assert "待生成自定义背景" in result["text"]


def test_conservative_keeps_authored_background_through_the_scene(tmp_path):
    source = "## rooftop evening\n@bg BG_Classroom\nKai: first\nKai: second\n"
    result = annotate.annotate_script(
        options(tmp_path, source=source),
        provider_instance=BackgroundProvider("BG_Roof"),
    )

    assert result["text"].count("@bg BG_Classroom") == 1
    assert "@bg BG_Roof" not in result["text"]
    assert "Kai: first\nKai: second" in result["text"]


def test_conservative_keeps_background_and_review_advice_across_resume(tmp_path):
    config = options(tmp_path, source="## rooftop evening\n" + "Kai: hello\n" * 80)
    first = BackgroundProvider()
    initial = annotate.annotate_script(config, provider_instance=first)
    assert len(first.prompts) > 1
    assert '"background":"BG_Roof"' in first.prompts[1][1]
    resumed = BackgroundProvider()
    result = annotate.annotate_script(config, provider_instance=resumed)

    assert resumed.prompts == []
    assert result["text"] == initial["text"]
    assert result["text"].count("@bg BG_Roof") == 1
    assert any(d["code"] == "background_approximate_match" for d in result["diagnostics"])


def test_changing_profile_does_not_reuse_the_other_profiles_checkpoint(tmp_path):
    config = options(tmp_path)
    annotate.annotate_script(config, provider_instance=BackgroundProvider())
    provider = BackgroundProvider()
    result = annotate.annotate_script(
        {**config, "direction_profile": "standard"}, provider_instance=provider
    )

    assert len(provider.prompts) == 1
    assert result["agent"]["resumed_chunks"] == 0
    assert "@bg" not in result["text"]


@pytest.mark.parametrize("missing", [True, False])
def test_conservative_rejects_missing_or_unregistered_backgrounds(tmp_path, missing):
    config = options(tmp_path)
    if missing:
        index = json.loads(Path(config["index"]).read_text(encoding="utf-8"))
        index["bg"] = {}
        Path(config["index"]).write_text(json.dumps(index), encoding="utf-8")
    provider = BackgroundProvider("BG_Missing")

    with pytest.raises(ValueError) as error:
        annotate.annotate_script(config, provider_instance=provider)
    assert error.value.code == (
        "background_catalog_empty" if missing else "background_not_in_manifest"
    )
    if missing:
        assert provider.prompts == []


def test_conservative_stateless_entry_uses_the_same_background_policy(tmp_path):
    config = options(tmp_path)
    config["agent_enabled"] = False
    result = annotate.annotate_script(config, provider_instance=BackgroundProvider())

    assert "@bg BG_Roof" in result["text"]


def test_profile_rules_change_requires_new_generation_before_a_model_call(tmp_path):
    config = options(tmp_path)
    config["direction_profile_snapshot"] = {
        "id": "conservative",
        "version": "99.0",
        "rules_sha256": "0" * 64,
    }
    provider = BackgroundProvider()
    with pytest.raises(ValueError) as error:
        annotate.annotate_script(config, provider_instance=provider)
    assert error.value.code == "direction_profile_changed"
    assert provider.prompts == []


def test_inherited_scene_keeps_previous_background_instead_of_choosing_again(tmp_path):
    config = options(
        tmp_path, source="## rooftop evening\nKai: first\n## classroom morning\nKai: second\n"
    )
    config["usage_chain"] = [
        {"start": "2", "end": "2", "location": "rooftop evening"},
        {"start": "4", "end": "4", "location": "classroom morning", "inherits_from": "scene-1"},
    ]
    result = annotate.annotate_script(config, provider_instance=BackgroundProvider())

    assert result["text"].count("@bg BG_Roof") == 1
    assert "@bg BG_Classroom" not in result["text"]


def test_configured_scene_background_is_not_overridden_by_model(tmp_path):
    config = options(tmp_path)
    cast = json.loads(Path(config["cast"]).read_text(encoding="utf-8"))
    cast["scene_bg"] = {"rooftop evening": "BG_Classroom"}
    Path(config["cast"]).write_text(json.dumps(cast), encoding="utf-8")
    result = annotate.annotate_script(config, provider_instance=BackgroundProvider("BG_Roof"))

    assert "@bg BG_Classroom" in result["text"]
    assert "@bg BG_Roof" not in result["text"]


def test_changed_background_plan_invalidates_previous_checkpoint(tmp_path):
    config = options(tmp_path)
    annotate.annotate_script(config, provider_instance=BackgroundProvider())
    config["usage_chain"] = [
        {
            "start": "2",
            "end": "2",
            "needs": [
                {"kind": "background", "status": "confirmed", "aa_key": "BG_Classroom"},
            ],
        }
    ]
    provider = BackgroundProvider()
    result = annotate.annotate_script(config, provider_instance=provider)

    assert len(provider.prompts) == 1
    assert "@bg BG_Classroom" in result["text"]
    assert result["agent"]["resumed_chunks"] == 0
