"""Activity is a read-only projection; it must not invent completion or duplicate runs."""

from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def page():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        p = browser.new_page(viewport={"width": 1280, "height": 800})
        p.on("pageerror", lambda error: pytest.fail(str(error)))
        yield p
        browser.close()


def install(page, work):
    import json

    source = (WEB / "app.js").read_text(encoding="utf8")
    helpers = source[
        source.index("function writingActivityItems(") : source.index("function renderChrome(")
    ]
    renderer = source[
        source.index("function renderMobileTasks(") : source.index(
            "function artifact(", source.index("function renderMobileTasks(")
        )
    ]
    production = source[
        source.index("const productionActivity=") : source.index(
            "async function loadProductionActivity("
        )
    ]
    page.set_content('<main id="workspace"></main>')
    page.add_script_tag(
        content="""
      const hcArray=v=>Array.isArray(v)?v:[],esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
      const scenes=()=>[{id:'scene-1',chapter_id:'chapter-1',title:'第一场'}];
      const frame=(eyebrow,title,detail,body)=>`<h2>${title}</h2><p>${detail}</p>${body}`;
      const state={work:"""
        + json.dumps(work, ensure_ascii=False)
        + """,activityFilter:'all'};
      let loads=0;const loadProductionActivity=()=>{loads++};
    """
        + helpers
        + production
        + renderer
        + "productionActivity.loaded=true;renderMobileTasks(document.querySelector('main'));"
    )


def test_conversation_runs_appear_once_and_pending_is_not_always_proposal(page):
    work = {
        "title": "测试作品",
        "runs": [
            {
                "id": "r",
                "work_items": [
                    {
                        "id": "job-1",
                        "type": "agent.scene.review",
                        "status": "succeeded",
                        "scope_type": "scene",
                        "scope_id": "scene-1",
                        "acceptance": {"agent_run_id": "agent-linked"},
                        "attempts": [],
                    }
                ],
            }
        ],
        "agent_runs": [
            {"id": "agent-linked", "status": "completed"},
            {
                "id": "agent-waiting",
                "status": "waiting_user",
                "scope_type": "work",
                "policy": {"thread_id": "thread-a"},
            },
        ],
    }
    install(page, work)
    assert page.evaluate("writingActivityItems(state.work).length") == 2
    expect(page.locator("[data-task-open-thread]")).to_have_text("打开对话")
    expect(
        page.get_by_text("助手正在等待补充信息或确认下一步；当前没有待采纳候选。")
    ).to_be_visible()
    expect(page.locator("[data-task-open-scope]")).to_have_text("查看场景")
    assert page.evaluate("loads") == 0


def test_proposal_status_and_filters_use_authoritative_state(page):
    work = {
        "title": "test",
        "agent_runs": [
            {"id": "a", "status": "completed", "proposal_id": "p", "policy": {"thread_id": "t"}},
            {"id": "b", "status": "queued", "policy": {"thread_id": "t2"}},
        ],
        "proposals": [{"id": "p", "status": "pending"}],
    }
    install(page, work)
    expect(page.locator("[data-activity-filter=active]")).to_contain_text("1")
    expect(page.locator("[data-activity-filter=attention]")).to_contain_text("1")
    expect(page.locator("[data-task-open-thread=t]")).to_have_text("查看待审修改")
    page.evaluate(
        "state.activityFilter='history';renderMobileTasks(document.querySelector('main'))"
    )
    expect(page.locator(".task-item")).to_have_count(0)
    expect(page.get_by_role("heading", name="当前分类没有活动")).to_be_visible()
    page.evaluate(
        "state.work.proposals[0].status='accepted';state.activityFilter='history';renderMobileTasks(document.querySelector('main'))"
    )
    expect(page.locator(".task-item")).to_have_count(1)
    expect(page.locator("[data-task-open-thread=t]")).to_have_text("打开对话")


def test_production_rows_escape_server_text_and_offer_navigation_not_direct_execution(page):
    install(page, {"title": "test"})
    page.evaluate(
        "productionActivity.items=[{job_id:'j',run_id:'production-1',state:'failed',label:'<img src=x onerror=alert(1)>',error:{message:'请查看配置'}}];renderMobileTasks(document.querySelector('main'))"
    )
    expect(page.locator(".production-activity img")).to_have_count(0)
    expect(page.locator("[data-open-production]")).to_have_attribute(
        "data-open-production", "production-1"
    )
    expect(page.locator(".production-activity button")).to_have_text("打开制作项目")
    page.evaluate(
        "productionActivity.error='制作活动暂时无法读取。';renderMobileTasks(document.querySelector('main'))"
    )
    expect(page.locator("[data-production-activity-refresh]")).to_be_visible()
    expect(page.locator("[data-activity-filter]")).to_have_count(4)


def test_activity_order_and_recovery_require_actual_retry_link(page):
    work = {
        "title": "test",
        "agent_runs": [
            {
                "id": "old",
                "status": "failed",
                "created_at": "2026-09-24T10:00:00Z",
                "scope_type": "scene",
                "scope_id": "scene-1",
                "policy": {"thread_id": "t"},
            },
            {
                "id": "new",
                "status": "completed",
                "created_at": "2026-09-24T11:00:00Z",
                "scope_type": "scene",
                "scope_id": "scene-1",
                "policy": {"thread_id": "t"},
            },
        ],
    }
    install(page, work)
    assert page.evaluate("writingActivityItems(state.work).map(x=>x.id)") == ["new", "old"]
    expect(page.locator(".task-item.failed")).to_have_count(1)
    page.evaluate(
        "state.work.agent_runs[1].policy.retry_of='old';renderMobileTasks(document.querySelector('main'))"
    )
    expect(page.locator(".task-item.recovered")).to_have_count(1)


def test_refresh_controller_scope_cancellation_and_retry():
    import subprocess
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("activity_refresh_cases.cjs"))],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("newer_version", [3, 4])
def test_activity_late_read_does_not_regress_another_refresh(page, newer_version):
    install(page, {"id": "work-a", "version": 3, "title": "Original", "agent_runs": []})
    source = (WEB / "app.js").read_text(encoding="utf8")
    adapter = source[source.index("// Activity is a scoped, read-only view."):]
    page.add_script_tag(content="""
        let hcNavigationEpoch=1,hcComposing=false,hcCommandDepth=0,adapterOptions;
        const registerRenderHook=()=>{};
        state.route={section:'tasks'};
        window.HaloCueActivityRefresh={create:options=>{adapterOptions=options;return {sync(){},stop(){}}}};
        window.fetch=async url=>({ok:true,json:async()=>url.includes('/jobs')?{ok:true,items:[]}:{ok:true,data:{id:'work-a',version:3,title:'Late',agent_runs:[]}}});
    """ + adapter)
    page.evaluate("window.delayedActivity=adapterOptions.load('work-a:1',new AbortController().signal)")
    page.evaluate("version=>{state.work={id:'work-a',version,title:'More recent refresh',agent_runs:[]}}", newer_version)
    page.evaluate("async()=>adapterOptions.apply(await window.delayedActivity)")
    assert page.evaluate("state.work.title") == "More recent refresh"
    assert page.evaluate("state.work.version") == newer_version


def test_activity_dialog_does_not_get_replaced_by_background_result(page):
    install(page, {"id": "work-a", "version": 3, "title": "Original", "agent_runs": []})
    source = (WEB / "app.js").read_text(encoding="utf8")
    adapter = source[source.index("// Activity is a scoped, read-only view."):]
    page.add_script_tag(content="""
        let hcNavigationEpoch=1,hcComposing=false,hcCommandDepth=0,adapterOptions;
        const registerRenderHook=()=>{};
        state.route={section:'tasks'};
        window.HaloCueActivityRefresh={create:options=>{adapterOptions=options;return {sync(){},stop(){}}}};
        const dialog=document.createElement('dialog');dialog.textContent='Keep this decision';document.body.append(dialog);dialog.showModal();
    """ + adapter)
    page.evaluate("adapterOptions.apply({workId:'work-a',readBase:state.work,work:{status:'fulfilled',value:{id:'work-a',version:4,title:'Changed'}},jobs:{status:'fulfilled',value:{items:[]}}})")
    expect(page.get_by_role("dialog")).to_have_text("Keep this decision")
    assert page.evaluate("state.work.version") == 3


@pytest.mark.parametrize("usage_status", ["not_reported", "invalid"])
def test_activity_unknown_usage_is_not_zero(page, usage_status):
    install(page, {"agent_runs": [{"id": "a", "status": "failed", "request_usage": {
        "physical_request_count": 2, "logical_request_count": 1, "unknown_usage_count": 2,
        "totals": {"usage_status": usage_status, "input_tokens": 0, "output_tokens": 0, "cache_status": "unknown"},
    }}]})
    page.locator(".task-details summary").click()
    panel = page.get_by_role("region", name="Token 用量明细")
    expect(panel).to_contain_text("不代表零消耗")
    expect(panel).to_contain_text("未知（缺少单价或用量）")
    assert "0 tokens" not in panel.inner_text()


def test_activity_full_receipt_exact_values_cache_and_cost(page):
    install(page, {"runs": [{"id": "production", "work_items": [{
        "id": "job", "type": "agent.scene.review", "status": "succeeded",
        "acceptance": {"agent_run_id": "a"}, "attempts": [],
    }]}], "agent_runs": [{"id": "a", "status": "completed", "request_usage": {
        "physical_request_count": 3, "logical_request_count": 2, "unknown_usage_count": 0,
        "pending_count": 0, "interrupted_count": 0,
        "totals": {"usage_status": "reported", "input_tokens": 1234567, "output_tokens": 4321,
                   "cache_read_tokens": 1000000, "cache_write_tokens": 125,
                   "cache_status": "supported_hit", "input_tokens_semantics": "total_including_cache",
                   "estimated_cost": 0.123456, "cost_status": "complete_estimate"},
    }}]})
    expect(page.locator(".task-item")).to_have_count(1)
    expect(page.locator(".task-token-summary")).to_contain_text("1,234,567")
    page.locator(".task-details summary").click()
    panel = page.get_by_role("region", name="Token 用量明细")
    for text in ("1,234,567 tokens", "4,321 tokens", "1,000,000 tokens", "125 tokens", "USD 0.123456", "不要再次相加", "3 / 2"):
        expect(panel).to_contain_text(text)


def test_activity_legacy_estimate_and_later_failed_request_keep_cost(page):
    install(page, {"agent_runs": [{"id": "a", "status": "failed", "failure": {
        "code": "model_context_limit", "message": "输入估算约 1618781 tokens，超出配置的输入容量 1050000；请减少引用范围或调整真实容量。",
    }}]})
    page.locator(".task-details summary").click()
    panel = page.get_by_role("region", name="Token 用量明细")
    for text in ("1,618,781", "1,050,000", "568,781", "历史错误记录", "不能补造实际用量"):
        expect(panel).to_contain_text(text)
    page.evaluate("""() => {
        state.work.agent_runs[0].failure.token_diagnostics={request_status:'rejected_before_http',estimated_input_tokens:100,input_limit_tokens:50,overage_tokens:50};
        state.work.agent_runs[0].request_usage={physical_request_count:1,logical_request_count:1,unknown_usage_count:0,totals:{usage_status:'reported',input_tokens:99,output_tokens:10,estimated_cost:0.5,cost_status:'complete_estimate'}};
        renderMobileTasks(document.querySelector('main'));
    }""")
    page.locator(".task-details summary").click()
    expect(panel).to_contain_text("不抵消前面请求的消耗")
    expect(panel).to_contain_text("USD 0.500000")
    expect(panel).not_to_contain_text("本运行未记录 HTTP")
