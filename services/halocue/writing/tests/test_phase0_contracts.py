from pathlib import Path


ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"


def test_canonical_tokens_are_loaded_before_shell_and_shell_has_no_late_root():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    tokens = index.index("/tokens.css")
    shell = index.index("/shell.css")
    assert tokens < shell
    assert (WEB / "tokens.css").read_text(encoding="utf-8").count(":root") == 1
    assert ":root" not in (WEB / "shell.css").read_text(encoding="utf-8")


def test_main_styles_do_not_use_global_transition_all():
    for path in WEB.glob("*.css"):
        assert "transition: all" not in path.read_text(encoding="utf-8").lower(), path.name


def test_presentation_contract_is_not_a_command_surface():
    app = (ROOT / "src/halocue_writing/app.py").read_text(encoding="utf-8")
    assert "agent-presentation" in app
    assert "get_agent_presentation" in app


def test_work_agent_uses_presentation_without_exposing_raw_tool_arguments():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert "refreshAgentPresentation" in script
    assert "agentPresentationMarkup" in script
    assert "agentRecoveryMarkup" in script
    assert "sceneAgentRecoveryMarkup" in script
    assert "latestFailedSceneAgentRun" in script
    assert "recovery.available" in script
    assert "data-agent-retry-run" in script
    assert "agentFailureView" in script
    assert "provider_timeout" in script
    assert "provider_rate_limited" in script
    assert "data-agent-reload-work" in script
    assert "parameters=item.input" not in script
    assert "<pre>输入" not in script


def test_scene_candidate_and_asset_suggestion_labels_preserve_runtime_boundary():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    workbench = (WEB / "writing-workbench.js").read_text(encoding="utf-8")

    assert "result.simulation?'模拟':'真实 Provider'" in script
    assert "真实 Provider'}候选已生成" in script
    assert "本地规则建议 · 未调用模型" in workbench


def test_scene_candidate_has_one_runtime_click_handler_and_neutral_legacy_copy():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    # The compatibility handler is the single owner of this request.  The
    # earlier delegated graph must not issue a second network call.
    assert script.count("/candidate:generate") == 1
    assert "toast('模拟候选已生成，等待你的决定')" not in script
    assert "result.simulation?'模拟':'真实 Provider'" in script


def test_header_separates_running_tasks_from_pending_proposals():
    script = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function workActivityCounts(items=[])" in script
    assert "后台任务 ${activity.running}" not in script
    assert "内容已保存到本地" in script
    assert "待审查 ${activity.pending}" not in script
    assert "pending:list.filter(item=>item.status==='waiting_user').length" in script
