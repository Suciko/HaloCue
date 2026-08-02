import json
import sys

import annotate
import llm


def test_main_with_mock_provider_writes_a_portrait_annotation(tmp_path, monkeypatch):
    script = tmp_path / "scene.txt"
    script.write_text("Kai: hello\n", encoding="utf-8")
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "default_bg": "BG_Black", "default_bgm": 0, "scene_bg": {},
        "cast": {"Kai": {"id": "kai", "portrait": True}}, "alias": {},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "bg": {"BG_Black": 1}, "sounds": [],
        "characters": [{"identifier": "kai", "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}]}],
        "enums": {
            "emoticon": {"1": {"sym": "[!]", "cn": "惊讶"}},
            "action": {"6": {"verb": "jump", "cn": "跳跃"}},
        },
    }), encoding="utf-8")
    output = tmp_path / "annotated.txt"
    monkeypatch.setattr(sys, "argv", [
        "annotate.py", str(script), "-o", str(output), "--cast", str(cast),
        "--index", str(index), "--provider", "mock",
    ])
    monkeypatch.setattr(
        annotate,
        "make_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("profile provider instance was ignored")
        ),
    )

    annotate.main(provider_instance=llm.MockProvider({}))

    assert output.read_text(encoding="utf-8") == "Kai(00): hello\n"
