from camera import plan_camera


def test_default_camera_keeps_portrait_through_consecutive_narration():
    shots = plan_camera([
        {"speaker": "kei", "text": "我在这里。"},
        {"speaker": None, "text": "她看向远处。"},
        {"speaker": None, "text": "风吹过街道。"},
    ])

    assert shots == [["kei"], ["kei"], ["kei"]]
