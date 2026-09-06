from pathlib import Path


def test_agent_showcase_keeps_tools_proposals_and_safe_prototype_boundary():
    web = Path(__file__).resolve().parents[1] / "web"
    html = (web / "agent-showcase.html").read_text(encoding="utf-8")
    styles = (web / "agent-showcase.css").read_text(encoding="utf-8")
    script = (web / "agent-showcase.js").read_text(encoding="utf-8")

    assert "交互原型 · 未连接正式资料库" in html
    assert "执行了 4 个步骤，均已完成" in html
    assert "read_scene_revision" in html
    assert "create_knowledge_proposal" in html
    assert html.count('class="proposal-card"') == 2
    assert "角色卡更新 · Proposal" in html
    assert "新建世界卡 · Proposal" in html
    assert "影响预览" in html
    assert "应用 2 项修改" in html
    assert "全部接受" not in html
    assert "置信度" not in html
    assert "未发现冲突" in html
    assert "data-select-all" in html
    assert "@media (max-width: 780px)" in styles
    assert "font-size: 14px; line-height: 1.75" in styles
    assert "原型预览：正式接入后" in script
    assert "fetch(" not in script
    assert "/api/" not in script
