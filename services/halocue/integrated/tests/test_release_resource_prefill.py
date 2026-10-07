"""Writing handoffs retain frozen scene locations and prefill local AA resources."""

import json
from dataclasses import replace

from halocue_integrated.production_assets import IntegratedProductionService
from halocue_production.config import Settings
from halocue_writing.service import WritingService
from halocue_writing.release_integrity import build_production_handoff
from services.halocue.writing.tests.test_release_integrity import _build_release


def test_writing_release_prefills_resources_without_approving_or_rematching(tmp_path):
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Club": "synthetic-club"},
                "bg_label": {"BG_Club": {"label": "游戏开发部活动室", "place": "游戏开发部活动室"}},
                "characters": [
                    {
                        "identifier": "arisu",
                        "name": "爱丽丝",
                        "spine": "CharacterSpine_arisu",
                        "faces": ["00"],
                    },
                    {
                        "identifier": "kei",
                        "name": "凯伊",
                        "spine": "CharacterSpine_kei",
                        "faces": ["00"],
                    },
                ],
                "sounds": [],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    writing = WritingService(tmp_path / "writing")
    production = IntegratedProductionService(
        replace(
            Settings.from_env(data_dir=tmp_path / "production"),
            resource_index=index,
            legacy_root=tmp_path,
        )
    )
    try:
        _work, release = _build_release(writing)
        frozen = writing.get_release(release["release_id"])
        assert frozen["manifest"]["scenes"][0]["location"] == "游戏开发部活动室"
        assert frozen["text"].startswith("## 提示灯 · 游戏开发部活动室\n")
        handoff = build_production_handoff(
            {"release": frozen, "manifest": frozen["manifest"], "text": frozen["text"]}, "QA"
        )
        assert handoff["auto_match_resources"] is True
        first = production.create_run(handoff)
        draft = first["draft"]
        assert draft["cast"]["cast"]["爱丽丝"]["id"] == "arisu"
        assert draft["cast"]["cast"]["凯伊"]["id"] == "kei"
        assert any(c["current"].get("arg") == "BG_Club" for c in draft["cards"])
        assert all(c["review_state"] != "approved" for c in draft["cards"])
        second = production.create_run(handoff)
        assert second["run"]["run_id"] == first["run"]["run_id"]
        assert second["draft"]["draft_version"] == draft["draft_version"]
        assert writing.get_release(release["release_id"])["text"] == frozen["text"]
    finally:
        writing.close()
        production.jobs.close()
