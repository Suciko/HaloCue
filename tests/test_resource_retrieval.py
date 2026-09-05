import copy

from resource_retrieval import build_resource_candidate_index


def test_candidate_index_is_bounded_but_preserves_exact_and_usage_pins():
    index = {
        "bg": {f"BG_{index:03d}": index for index in range(200)},
        "sounds": [f"SE_{index:03d}" for index in range(300)],
        "bg_label": {"BG_155": {"place": "天台", "time": "黄昏"}},
        "sound_label": {"SE_244": {"label": "键盘敲击"}},
        "characters": [],
        "enums": {},
    }
    original = copy.deepcopy(index)
    candidate, manifest = build_resource_candidate_index(
        index,
        "黄昏时，天台传来键盘敲击。稍后明确使用 BG_199。",
        cast_config={"default_bg": "BG_198"},
        usage_chain=[{"needs": [
            {"kind": "background", "aa_key": "BG_197"},
            {"kind": "sound", "aa_key": "SE_299"},
        ]}],
        background_limit=8,
        sound_limit=10,
    )

    assert len(candidate["bg"]) == 8
    assert len(candidate["sounds"]) == 10
    assert {"BG_155", "BG_197", "BG_198", "BG_199"} <= set(candidate["bg"])
    assert {"SE_244", "SE_299"} <= set(candidate["sounds"])
    assert manifest["full_background_count"] == 200
    assert manifest["full_sound_count"] == 300
    assert index == original


def test_candidate_index_can_exceed_limit_only_for_mandatory_pins():
    index = {
        "bg": {f"BG_{number}": 0 for number in range(5)},
        "sounds": [],
    }
    candidate, manifest = build_resource_candidate_index(
        index,
        "",
        usage_chain=[{"needs": [
            {"kind": "background", "aa_key": f"BG_{number}"}
            for number in range(5)
        ]}],
        background_limit=2,
    )

    assert set(candidate["bg"]) == set(index["bg"])
    assert manifest["background_count"] == 5
