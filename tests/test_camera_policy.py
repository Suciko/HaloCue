from camera import plan_camera


def test_default_camera_keeps_portrait_through_consecutive_narration():
    shots = plan_camera([
        {"speaker": "kei", "text": "我在这里。"},
        {"speaker": None, "text": "她看向远处。"},
        {"speaker": None, "text": "风吹过街道。"},
    ])

    assert shots == [["kei"], ["kei"], ["kei"]]


def test_explicit_listener_shot_overrides_speaker_policy():
    assert plan_camera([
        {"speaker": "a", "text": "A", "visible_characters": ["b"]},
    ]) == [["b"]]


def test_explicit_empty_shot_is_one_line_and_next_line_returns_to_auto_camera():
    shots = plan_camera([
        {"speaker": "a", "text": "offscreen", "visible_characters": []},
        {"speaker": "a", "text": "onscreen"},
    ])

    assert shots == [[], ["a"]]
