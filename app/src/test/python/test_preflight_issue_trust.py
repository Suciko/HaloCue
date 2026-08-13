import webui


def test_preflight_discards_ai_operational_hallucinations_but_keeps_rule_errors(
    tmp_path, monkeypatch
):
    script = tmp_path / "story.txt"
    script.write_text(
        "旁白: 终端亮起。\n@not_a_real_aa_command build-freeze\n",
        encoding="utf-8",
    )
    fake_result = {
        "characters": [],
        "assets": [],
        "usage_chain": [],
        "issues": [
            {
                "severity": "error",
                "code": "build_frozen",
                "message": "构建被冻结，禁止继续修改资源编号。",
                "action": "清理临时目录。",
            },
            {
                "severity": "error",
                "code": "private_log_exposure",
                "message": "本地调用日志泄露了私人内容。",
                "action": "删除可见内容。",
            },
            {
                "severity": "warning",
                "code": "release_upload_blocked",
                "message": "游戏原型无法按计划上传。",
                "action": "延期或回滚。",
            },
        ],
    }
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: object())
    monkeypatch.setattr(webui, "_complete_preflight", lambda *_args: fake_result)

    result = webui._preflight_result(str(script), scope="issue-trust-test")
    codes = {issue["code"] for issue in result["issues"]}

    assert "unknown_directive" in codes
    assert "build_frozen" not in codes
    assert "private_log_exposure" not in codes
    assert "release_upload_blocked" not in codes
