from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scene_agent_exposes_durable_run_recovery_and_one_composer():
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert "function workAgentActiveRun" in script
    assert "function activeAgentRunMarkup" in script
    assert "function scheduleAgentRunPoll" in script
    assert "data-agent-cancel-run" in script
    assert "data-agent-retry-run" in script
    assert "本轮输入已保存，可以离开页面" in script
    assert "sceneAgentRecoveryMarkup" in script
    assert 'id="sceneConversationForm"' in script


def test_scene_context_auto_prepare_stops_after_a_blocked_prerequisite():
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert "if(state._contextErrorScene===sceneId)return;" in script
    assert "if(!blueprintIsConfirmed())" in script
    assert "state._contextBlocked='请先保存写作想法并确认故事方向。'" in script
    assert 'data-stage-jump="overview"' in script


def test_blocked_structure_scene_actions_do_not_enter_draft_or_assemble_context():
    script = (ROOT / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    # A scene row remains visible for orientation, but both entry points must
    # use the same writing gate while the work direction is unconfirmed.
    assert 'class="writing-scene ${scene.id === state.sceneId && state.stage === \'draft\' ? \'active\' : \'\'} ${readiness.blocked ? \'writing-gate-locked\' : \'\'}"' in script
    assert 'data-writing-gate="${esc(sceneReason)}" aria-label="进入本场未开放，点击查看原因"' in script
    assert 'class="${scene.current_revision_id ? \'quiet\' : \'primary\'} ${readiness.blocked ? \'writing-gate-locked\' : \'\'}"' in script


def test_scene_contract_keeps_advanced_ba_controls_collapsed_by_default():
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "shell.css").read_text(encoding="utf-8")

    assert 'class="scene-contract-advanced"' in script
    assert 'name="emotion_delta"' in script
    assert 'name="ending_payoff"' in script
    assert 'name="literary_voice_variant"' in script
    assert 'name="information_ownership"' in script
    assert 'name="exchange_chain"' in script
    assert "parseJsonField" in script
    assert ".scene-contract-advanced > summary" in styles
    assert ".scene-contract-advanced[open] > summary::before" in styles
