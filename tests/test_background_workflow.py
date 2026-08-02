from pathlib import Path

import pytest

from background_workflow import (
    BackgroundResolutionError,
    BackgroundResolutionSession,
)


def test_session_exposes_deduplicated_requests_with_prompts(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：傍晚咖啡厅\n"
        "凯伊：第一句\n"
        "# 待生成自定义背景：傍晚咖啡厅\n"
        "# 待生成自定义背景：游戏开发部纸箱角落\n",
        encoding="utf-8",
    )

    session = BackgroundResolutionSession.create(script, project="约会短篇")
    public = session.public_state()

    assert public["project"] == "约会短篇"
    assert public["ready"] is False
    assert [item["description"] for item in public["requests"]] == [
        "傍晚咖啡厅",
        "游戏开发部纸箱角落",
    ]
    assert all(item["id"] for item in public["requests"])
    assert all("16:9" in item["prompt"] for item in public["requests"])
    assert all(item["status"] == "pending" for item in public["requests"])
    assert public["requests"][0]["lines"] == [1, 3]
    assert public["requests"][1]["lines"] == [4]
    assert "script_path" not in public


def test_resolve_requires_a_registered_background_and_rewrites_exact_request(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：傍晚咖啡厅\n"
        "凯伊：第一句\n"
        "# 待生成自定义背景：游戏开发部纸箱角落\n",
        encoding="utf-8",
    )
    session = BackgroundResolutionSession.create(script, project="约会短篇")
    first_id = session.public_state()["requests"][0]["id"]

    with pytest.raises(BackgroundResolutionError, match="尚未登记"):
        session.resolve(
            first_id,
            "BG_NotRegistered",
            registered_backgrounds={"BG_Existing"},
        )

    state = session.resolve(
        first_id,
        "BG_Custom_Cafe",
        registered_backgrounds={"BG_Custom_Cafe", "BG_Existing"},
    )

    assert state["ready"] is False
    assert state["requests"][0]["status"] == "resolved"
    assert state["requests"][0]["background_name"] == "BG_Custom_Cafe"
    rewritten = script.read_text(encoding="utf-8")
    assert "@bg BG_Custom_Cafe" in rewritten
    assert "# 待生成自定义背景：傍晚咖啡厅" not in rewritten
    assert "# 待生成自定义背景：游戏开发部纸箱角落" in rewritten


def test_session_becomes_ready_only_after_every_request_is_resolved(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text(
        "# 待生成自定义背景：场景甲\n"
        "# 待生成自定义背景：场景乙\n",
        encoding="utf-8",
    )
    session = BackgroundResolutionSession.create(script, project="测试")
    ids = [item["id"] for item in session.public_state()["requests"]]

    session.resolve(ids[0], "BG_A", registered_backgrounds={"BG_A", "BG_B"})
    final = session.resolve(
        ids[1],
        "BG_B",
        registered_backgrounds={"BG_A", "BG_B"},
    )

    assert final["ready"] is True
    assert all(item["status"] == "resolved" for item in final["requests"])


def test_resolution_rejects_unknown_request_and_directive_injection(tmp_path):
    script = tmp_path / "annotated.txt"
    script.write_text("# 待生成自定义背景：场景甲\n", encoding="utf-8")
    session = BackgroundResolutionSession.create(script, project="测试")

    with pytest.raises(BackgroundResolutionError, match="找不到"):
        session.resolve("missing", "BG_A", registered_backgrounds={"BG_A"})
    request_id = session.public_state()["requests"][0]["id"]
    with pytest.raises(BackgroundResolutionError, match="背景名称"):
        session.resolve(
            request_id,
            "BG_A\n@se attack",
            registered_backgrounds={"BG_A\n@se attack"},
        )
