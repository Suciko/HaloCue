"""Shipping scene-submit handler with delayed synthetic transport in Chromium."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def scene_page():
    pw = pytest.importorskip("playwright.sync_api")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index(
        "document.addEventListener('submit',event=>{\n  if(event.target.id!=='sceneConversationForm')"
    )
    handler = source[start : source.index("\nregisterAppClick", start)]
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(
            '<form id="sceneConversationForm" data-discussion-only="true"><textarea name="text">测试讨论</textarea><button type="submit">发送</button></form>'
        )
        page.add_script_tag(
            content="""
          const state={work:{id:'work-a',version:1},sceneId:'scene-a',context:{scene_id:'scene-a'},activeAgentRunId:''};
          let hcWorkLoadEpoch=1;
          const hcPendingMessages=new Set(),hcPendingProposals=new Set(),hcTransientViews=new Map();
          const io={calls:[],renders:0,recoveries:0,polls:[],status:[],toasts:[]};
          function sceneConversationThread(){return {id:'thread-'+state.sceneId,version:2};}
          function selectedScene(){return {id:state.sceneId};}
          function workAgentActiveRun(){return null;}
          function sceneReviewDiscussionContext(){return '';}
          function hcViewKey(){return state.work.id+':'+state.sceneId;}
          function setBusy(text){io.status.push(text);}
          function toast(text){io.toasts.push(text);}
          function render(){io.renders++;io.valueAtRender=document.querySelector('textarea').value;}
          function scheduleAgentRunPoll(id){io.polls.push(id);}
          async function recoverFailedAgentTurn(){io.recoveries++;}
          function api(path,options){return new Promise((resolve,reject)=>io.calls.push({path,body:options?.body?JSON.parse(options.body):null,resolve,reject}));}
          function complete(){io.calls[0].resolve({work:{id:'work-a',version:2},agent_run_id:'agent-a'});}
          function fail(){io.calls[0].reject(new Error('模拟请求失败'));}
          function submit(){document.querySelector('form').requestSubmit();}
        """
            + handler
        )
        yield page
        browser.close()


def test_scene_send_is_single_flight_even_after_form_replacement(scene_page):
    page = scene_page
    page.evaluate(
        "submit();submit();const form=document.querySelector('form');form.replaceWith(form.cloneNode(true));submit()"
    )
    assert page.evaluate("io.calls.length") == 1
    assert page.evaluate("io.calls[0].body.task_scope") == {
        "surface": "scene",
        "scene_id": "scene-a",
        "discussion_only": True,
    }
    page.evaluate("complete()")
    page.wait_for_function("io.renders===1")
    assert page.evaluate("hcPendingMessages.size") == 0


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_late_scene_response_cannot_replace_another_work(scene_page, outcome):
    page = scene_page
    page.evaluate(
        "submit();state.work={id:'work-b',version:3};state.sceneId='scene-b';hcWorkLoadEpoch++"
    )
    page.evaluate("complete()" if outcome == "success" else "fail()")
    page.wait_for_timeout(50)
    assert page.evaluate("state.work.id") == "work-b"
    assert page.evaluate("io.renders") == 0
    assert page.evaluate("io.recoveries") == 0
    assert page.evaluate("io.polls") == []
    assert page.evaluate("io.toasts") == []


def test_success_clears_only_the_submitted_text(scene_page):
    page = scene_page
    page.evaluate("submit();complete()")
    page.wait_for_function("io.renders===1")
    expect(page.locator("textarea")).to_have_value("")
    assert page.evaluate("io.valueAtRender") == ""


def test_new_composer_text_is_not_erased_by_previous_reply(scene_page):
    page = scene_page
    page.evaluate("submit()")
    page.locator("textarea").fill("下一条尚未发送")
    page.evaluate("complete()")
    page.wait_for_function("io.renders===1")
    expect(page.locator("textarea")).to_have_value("下一条尚未发送")


def test_send_failure_preserves_text_and_allows_retry(scene_page):
    page = scene_page
    page.evaluate("submit();fail()")
    page.wait_for_function("io.recoveries===1")
    expect(page.locator("textarea")).to_have_value("测试讨论")
    page.evaluate("submit()")
    assert page.evaluate("io.calls.length") == 2


def test_late_response_does_not_mark_another_scene_as_running(scene_page):
    page = scene_page
    page.evaluate("submit();state.sceneId='scene-b';complete()")
    page.wait_for_timeout(50)
    assert page.evaluate("state.sceneId") == "scene-b"
    assert page.evaluate("state.activeAgentRunId") == ""


@pytest.mark.parametrize("change", ["work", "scene", "session"])
def test_error_recovery_refresh_does_not_restore_a_stale_view(scene_page, change):
    page = scene_page
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index("async function recoverFailedAgentTurn(error)")
    recovery = source[start : source.index("\nfunction agentToolLabel", start)]
    page.add_script_tag(content=recovery)
    page.evaluate(
        "() => {window.recoveryDone=false;void recoverFailedAgentTurn({code:'agent_failed'}).then(()=>recoveryDone=true)}"
    )
    page.wait_for_function("io.calls.length===1")
    page.evaluate(
        {
            "work": "state.work={id:'work-b',version:3}",
            "scene": "state.sceneId='scene-b'",
            "session": "hcWorkLoadEpoch++",
        }[change]
    )
    page.evaluate("io.calls[0].resolve({id:'work-a',version:2})")
    page.wait_for_function("recoveryDone")
    assert page.evaluate("state.work.version") == (3 if change == "work" else 1)
    assert page.evaluate("io.renders") == 0


def test_pending_send_announces_busy_and_failure_restores_action(scene_page):
    page = scene_page
    page.evaluate("submit()")
    expect(page.locator("form")).to_have_attribute("aria-busy", "true")
    expect(page.get_by_role("button", name="正在发送…")).to_be_disabled()
    page.evaluate("fail()")
    page.wait_for_function("io.recoveries===1")
    expect(page.get_by_role("button", name="发送", exact=True)).to_be_enabled()
    expect(page.locator("form")).not_to_have_attribute("aria-busy", "true")


@pytest.mark.parametrize("dismiss", ["timeout", "button"])
def test_error_toast_cannot_leave_an_invisible_click_blocker(scene_page, dismiss):
    page = scene_page
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index("function toast(message,bad=false)")
    snippet = source[start : source.index("function setBusy", start)]
    # Use the shipping element so top-layer attributes cannot drift from the app.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    toast_element = re.search(r'<div\b[^>]*id="toast"[^>]*></div>', html)
    assert toast_element is not None
    page.set_content('<button id="under">继续重试</button>' + toast_element.group())
    for name in ["styles.css", "shell.css", "theme.css"]:
        page.add_style_tag(content=(WEB / name).read_text(encoding="utf-8"))
    page.add_script_tag(
        content="const $=s=>document.querySelector(s); state.feedbackError={message:'test'};"
        + snippet
    )
    page.evaluate("toast('测试错误',true)")
    expect(page.locator("#toast")).to_be_visible()
    if dismiss == "button":
        page.get_by_role("button", name="关闭提示", exact=True).click()
    else:
        page.clock.install()
        page.evaluate("toast('测试错误',true)")
        page.clock.fast_forward(5500)
    expect(page.locator("#toast")).not_to_be_visible()
    assert page.locator("#toast").evaluate("e=>getComputedStyle(e).pointerEvents") == "none"


@pytest.fixture
def candidate_page(scene_page):
    page = scene_page
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index(
        "registerAppClick(event=>{\n  const generate=event.target.closest('[data-generate-scene-proposal]')"
    )
    handler = source[start : source.index("\ndocument.addEventListener('keydown'", start)]
    page.add_script_tag(
        content="""
      function registerAppClick(handler){document.addEventListener('click',handler);}
      function claimAppEvent(){}
      function pendingProposal(){return null;}
      const sceneAgentComposerDrafts=new Map();
      function runDurableAgentJob(){return api('/synthetic-job');}
      const transport=api;
      api=function(path,options){return path==='/works/work-a'?Promise.resolve({id:'work-a',version:2}):transport(path,options);};
      state.writingMobileView='agent';state.inspector='agent';
      document.querySelector('form').insertAdjacentHTML('beforeend','<button type="button" data-generate-scene-proposal>形成正文候选</button>');
    """
        + handler
    )
    return page


def test_candidate_success_shows_manuscript_not_empty_agent_panel(candidate_page):
    page = candidate_page
    page.locator("[data-generate-scene-proposal]").click()
    expect(page.locator("[data-generate-scene-proposal]")).to_have_text("正在写作…")
    page.evaluate("complete()")
    page.wait_for_function("io.renders===1")
    assert page.evaluate("state.writingMobileView") == "manuscript"
    assert page.evaluate("state.inspector") == "agent"
    assert page.evaluate("state._pendingChapterSceneScroll") == "scene-a"


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_candidate_late_result_leaves_another_work_untouched(candidate_page, outcome):
    page = candidate_page
    page.locator("[data-generate-scene-proposal]").click()
    page.evaluate("state.work={id:'work-b',version:3};hcWorkLoadEpoch++")
    page.evaluate("complete()" if outcome == "success" else "fail()")
    page.wait_for_timeout(50)
    assert page.evaluate("state.work.id") == "work-b"
    assert page.evaluate("io.renders") == 0
    assert page.evaluate("io.toasts") == []


def test_candidate_single_flight_survives_button_replacement(candidate_page):
    page = candidate_page
    page.locator("[data-generate-scene-proposal]").click()
    page.evaluate(
        "const b=document.querySelector('[data-generate-scene-proposal]');const clone=b.cloneNode(true);clone.disabled=false;b.replaceWith(clone);clone.click()"
    )
    assert page.evaluate("io.calls.length") == 1
    page.evaluate("fail()")
    page.wait_for_function("io.toasts.length>0")
    page.locator("[data-generate-scene-proposal]").click()
    assert page.evaluate("io.calls.length") == 2
