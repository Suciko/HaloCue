"""Keep explicit background choices through generation, without adding scene state."""

import pytest
import annotate
from tests.test_conservative_annotation import options, BackgroundProvider


class EveryLineBackgroundProvider(BackgroundProvider):
    def complete_json(self, static, volatile, user, schema):
        result = super().complete_json(static, volatile, user, schema)
        for row in result["lines"]:
            row.update(bg="BG_Roof", bg_request=self.request)
        return result


@pytest.mark.parametrize("profile", ["standard", "conservative"])
@pytest.mark.parametrize("agent", [True, False])
@pytest.mark.parametrize("bg_request", ["", "new scenery"])
def test_explicit_background_is_protected_for_every_line(tmp_path, profile, agent, bg_request):
    source = "## classroom night\n@bg BG_Classroom\nKai: first\nKai: second\nKai: third\n"
    config = options(tmp_path, profile=profile, source=source)
    config["agent_enabled"] = agent
    result = annotate.annotate_script(
        config, provider_instance=EveryLineBackgroundProvider(request=bg_request)
    )
    assert result["text"].count("@bg BG_Classroom") == 1
    assert "@bg BG_Roof" not in result["text"]
    assert "待生成自定义背景" not in result["text"]
    for text in ("first", "second", "third"):
        assert f"Kai: {text}" in result["text"]


def test_background_protection_resets_at_scene_boundary_and_follows_manual_change(tmp_path):
    config = options(
        tmp_path,
        profile="standard",
        source="## one\n@bg BG_Classroom\nKai: first\n@bg BG_Roof\nKai: second\n## two\nKai: third\n",
    )
    rows = annotate.parse_lines(config["script"], {"Kai": {"portrait": True}})
    lines = [row for row in rows if row["kind"] == "line"]
    assert [row.get("_authored_background", "") for row in lines] == ["BG_Classroom", "BG_Roof", ""]


def test_renderer_tracks_raw_background_before_model_switch():
    rows = [
        {"kind": "other", "raw": "@bg BG_Roof"},
        {"kind": "line", "who": "Kai", "text": "same", "bg": "BG_Roof"},
    ]
    assert annotate.render_annotated_items(rows).count("@bg BG_Roof") == 1
