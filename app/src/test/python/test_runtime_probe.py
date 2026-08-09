from runtime_probe import health


def test_health_reports_stable_android_bridge_contract():
    assert health() == {
        "runtime": "python",
        "ready": True,
        "schema": 1,
        "message": "本地 Python 已启动",
    }
