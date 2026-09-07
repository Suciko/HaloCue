"""Real DOM tests of the shipping adaptation controller with synthetic transport."""

from pathlib import Path
import pytest

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def page():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<button id='opener'>open</button>")
        page.add_script_tag(
            content=r"""
window.calls=[]; window.activeWork={id:'work-1',version:7,title:'Synthetic',chapters:[{id:'chapter-1',title:'第一章',scenes:[]}],agent_runs:[],proposals:[],artifacts:[]};
window.source={id:'source-saved',filename:'saved.txt',completion_state:'ongoing',chapters:[{id:'saved-ch',title:'原文章节',paragraphs:[{id:'paragraph',text:'门口的灯亮了。'}]}]};
window.plans=[];window.applied=[];window.fail=false;
window.provider={kind:'fake',is_simulation:true,config_digest:'simulation'};
window.bridge={getWork:()=>activeWork, guard:action=>action(), setWork:work=>{activeWork=work;applied.push(work.id)}, navigate:()=>{},
 encode:buffer=>btoa(String.fromCharCode(...new Uint8Array(buffer))),
 api:async (route,options)=>{const body=options?.body?JSON.parse(options.body):null;calls.push({route,body,method:options?.method||'GET'});
  if(fail)throw Error('synthetic <img> error');
  if(route==='/capabilities')return {providers:[provider]};
  if(route==='/works/work-1')return activeWork;
  if(route.endsWith('/source'))return source;
  if(route.endsWith('/source:preview'))return {preview_digest:'digest',document:{...source,chapters:[{id:'preview-only',title:'Preview',paragraphs:[]}]},changes:[{title:'Preview',kind:'added',diff:['+新内容']}],duplicate:false};
  if(route.endsWith('/source:update'))return {source,duplicate:false};
  if(route.endsWith('/adaptations')&&!body)return plans;
  if(route.endsWith('/adaptations')){const plan={id:'plan-1',source_version_id:source.id,status:'awaiting_plan',plan_digest:'pd',selected_chapter_ids:body.chapter_ids,plan:{rules:['只改编已提供内容'],character_mapping:body.character_mapping},budget:{max_calls:body.max_calls,reserved_calls:0},chapters:[{id:'adapt-ch',source_chapter_id:'saved-ch',status:'planned',candidate:{},dependency:{}}]};plans=[plan];return plan;}
  if(route.endsWith('/plan:approve')){plans[0].status='ready';return plans[0];}
  if(route.endsWith('/candidate:generate')){activeWork.agent_runs=[{id:'agent-1',scope_id:'adapt-ch',status:'running',policy:{workflow:'adaptation.chapter.generate'}}];return {agent_run_id:'agent-1',job:{id:'job-1'}};}
  if(route.endsWith('agent-1:cancel')){activeWork.agent_runs[0].status='cancelled';return activeWork.agent_runs[0];}
  if(route.endsWith('/accept'))return {scene_id:'scene-1',revision_id:'revision-1',work:{...activeWork,version:8}};
  throw Error('unexpected '+route);
 }};
"""
        )
        page.add_script_tag(content=(WEB / "adaptation-workbench.js").read_text(encoding="utf-8"))
        page.evaluate("window.ui = createAdaptationWorkbench(bridge)")
        yield page
        browser.close()


def test_open_and_reopen_only_read_durable_state(page):
    page.evaluate("ui.open()")
    page.wait_for_selector("dialog.adaptation-workbench[open]")
    assert page.locator(".adaptation-workbench").inner_text().find("原文章节") >= 0
    assert page.evaluate("calls.every(c=>c.method==='GET')")
    page.keyboard.press("Escape")
    assert not page.locator("dialog.adaptation-workbench").evaluate("d=>d.open")
    page.evaluate("ui.open()")
    assert page.evaluate("calls.every(c=>c.method==='GET')")


def test_plan_uses_saved_chapter_ids_and_no_generation_until_requested(page):
    page.evaluate("ui.open()")
    page.get_by_role("button", name="建立改编计划", exact=True).click()
    body = page.evaluate("calls.find(c=>c.route.endsWith('/adaptations')&&c.body).body")
    assert body["chapter_ids"] == ["saved-ch"]
    assert not page.evaluate("calls.some(c=>c.route.endsWith('candidate:generate'))")
    page.get_by_role("button", name="确认计划", exact=True).click()
    page.get_by_role("button", name="生成模拟候选", exact=True).click()
    body = page.evaluate("calls.find(c=>c.route.endsWith('candidate:generate')).body")
    assert body["expected_provider"]["is_simulation"] is True
    page.get_by_role("button", name="停止本轮", exact=True).click()
    assert page.evaluate("calls.some(c=>c.route.endsWith('agent-1:cancel'))")


def test_source_apply_uses_confirmed_digest_not_transient_preview_ids(page):
    page.evaluate("ui.open()")
    page.get_by_role("button", name="原文", exact=True).click()
    page.locator("[data-adaptation-file]").set_input_files(
        {"name": "新章.txt", "mimeType": "text/plain", "buffer": "第一章\n灯亮了。".encode()}
    )
    page.get_by_role("button", name="预览原文变化", exact=True).click()
    assert "+新内容" in page.locator(".adaptation-workbench").inner_text()
    page.get_by_role("button", name="确认保存原文", exact=True).click()
    body = page.evaluate("calls.find(c=>c.route.endsWith('source:update')).body")
    assert body["base_version_id"] == "source-saved"
    assert body["preview_digest"] == "digest"
    page.get_by_role("button", name="建立改编计划", exact=True).click()
    assert page.evaluate(
        "calls.find(c=>c.route.endsWith('/adaptations')&&c.body).body.chapter_ids"
    ) == ["saved-ch"]


def test_candidate_text_is_escaped_and_target_visible_before_acceptance(page):
    page.evaluate(
        r"""plans=[{id:'plan-1',source_version_id:source.id,status:'ready',plan:{},budget:{max_calls:5,reserved_calls:1},chapters:[{id:'adapt-ch',source_chapter_id:'saved-ch',status:'candidate',dependency:{},candidate:{formal:false,proposal_id:'proposal-1',text:'老师: <img src=x onerror=alert(1)>',source_refs:[{paragraph_id:'paragraph',quote:'灯亮了。'}],target:{scene_id:null,chapter_id:'chapter-1'}}}]}];ui.open()"""
    )
    card = page.locator(".adaptation-card")
    assert "<img src=x" in card.inner_text()
    assert card.locator("img").count() == 0
    assert "第一章" in card.inner_text()
    assert "新建场景" in card.inner_text()
    page.get_by_role("button", name="采纳到此场景", exact=True).click()
    assert page.evaluate("calls.find(c=>c.route.endsWith('/accept')).body.expected_version") == 7


def test_closed_dialog_ignores_late_open_response(page):
    page.evaluate(
        "window.resolveLate=null;const api=bridge.api;bridge.api=(route,opt)=>route==='/works/work-1'?new Promise(resolve=>resolveLate=resolve):api(route,opt);void ui.open()"
    )
    page.get_by_role("button", name="关闭改编工作台", exact=True).click()
    page.evaluate("resolveLate({...activeWork,title:'late'})")
    assert not page.locator(".adaptation-workbench").evaluate("d=>d.open")
    assert page.evaluate("applied.length") == 0


def test_existing_import_entry_routes_prose_without_changing_aap_contract():
    source = (WEB / "app.js").read_text(encoding="utf-8")
    reader = source[
        source.index("async function readAapImportFile(") : source.index(
            "function openAapImportDialog"
        )
    ]
    assert "openAdaptationWorkbench(payload)" in reader
    assert "if(!isAap)" in reader
    assert "data-open-adaptation" in source
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "adaptation-workbench.js" in html
    assert "adaptation-workbench.css" in html


def test_controls_are_locked_while_source_preview_is_pending(page):
    page.evaluate("ui.open()")
    page.get_by_role("button", name="原文", exact=True).click()
    page.locator("[data-adaptation-file]").set_input_files(
        {"name": "chapter.txt", "mimeType": "text/plain", "buffer": b"chapter"}
    )
    page.evaluate(
        "const original=bridge.api;bridge.api=(route,options)=>route.endsWith('source:preview')?new Promise(()=>{}):original(route,options);void 0"
    )
    page.get_by_role("button", name="预览原文变化", exact=True).click()
    assert page.locator("[data-field=completion]").is_disabled()
    assert page.locator("[data-field=mode]").is_disabled()
    assert page.locator("[data-field=scope]").is_disabled()
    page.get_by_role("button", name="关闭改编工作台", exact=True).click()


def test_legacy_pending_candidate_can_confirm_default_target(page):
    page.evaluate(
        r"""plans=[{id:'plan-1',source_version_id:source.id,status:'ready',plan:{},budget:{max_calls:5,reserved_calls:1},chapters:[{id:'adapt-ch',source_chapter_id:'saved-ch',status:'candidate',dependency:{},resolved_target:{scene_id:null,chapter_id:'chapter-1'},candidate:{formal:false,proposal_id:'proposal-old',text:'老师: 旧候选。',source_refs:[]}}]}];ui.open()"""
    )
    assert "旧候选" in page.locator(".adaptation-workbench").inner_text()
    button = page.get_by_role("button", name="确认目标并采纳旧候选", exact=True)
    button.click()
    body = page.evaluate("calls.find(c=>c.route.endsWith('/accept')).body")
    assert body["target_chapter_id"] == "chapter-1"


def test_cross_work_switch_ignores_late_state_response(page):
    page.evaluate(
        "const original=bridge.api;window.finish=null;bridge.api=(route,options)=>route==='/works/work-1'?new Promise(resolve=>finish=resolve):original(route,options);void ui.open()"
    )
    page.evaluate("activeWork={id:'work-2',title:'Other'};finish({id:'work-1',title:'Late'})")
    assert page.evaluate("activeWork.id") == "work-2"
    assert not page.evaluate("applied.includes('work-1')")


def test_update_chapters_use_source_order_not_click_order(page):
    page.evaluate("source.chapters.push({id:'second',title:'第二原文章',paragraphs:[]});ui.open()")
    page.get_by_role("button", name="原文", exact=True).click()
    page.locator("[data-field=mode]").select_option("update")
    page.locator("[data-update-chapter=second]").check()
    page.locator("[data-update-chapter=saved-ch]").uncheck()
    page.locator("[data-update-chapter=saved-ch]").check()
    page.locator("[data-adaptation-file]").set_input_files(
        {"name": "update.txt", "mimeType": "text/plain", "buffer": b"update"}
    )
    page.get_by_role("button", name="预览原文变化", exact=True).click()
    assert page.evaluate("calls.find(c=>c.route.endsWith('source:preview')).body.chapter_ids") == [
        "saved-ch",
        "second",
    ]


def test_legacy_pending_uses_server_resolved_target_not_work_first_chapter(page):
    page.evaluate(
        r"""activeWork.chapters.unshift({id:'display-first',title:'显示第一章',scenes:[]});plans=[{id:'plan-1',source_version_id:source.id,status:'ready',plan:{},budget:{max_calls:5,reserved_calls:1},chapters:[{id:'adapt-ch',source_chapter_id:'saved-ch',status:'candidate',dependency:{},resolved_target:{chapter_id:'chapter-1',scene_id:'scene-existing',base_revision_id:'rev',mode:'replace'},candidate:{formal:false,proposal_id:'proposal-old',text:'老师: 旧候选。',source_refs:[]}}]}];ui.open()"""
    )
    card = page.locator(".adaptation-card")
    assert "替换已关联场景" in card.inner_text()
    page.get_by_role("button", name="确认目标并采纳旧候选", exact=True).click()
    assert (
        page.evaluate("calls.find(c=>c.route.endsWith('/accept')).body.target_chapter_id")
        == "chapter-1"
    )


def test_cancelled_entrypoint_file_read_cannot_open_for_another_work(page):
    source = (WEB / "app.js").read_text(encoding="utf-8")
    start = source.index("async function readAapImportFile(")
    end = source.index("let adaptationWorkbench", start)
    page.add_script_tag(
        content="""
      let aapImportState=null;const state={work:{id:'A'}};window.entryState=state;
      const entryDialog=document.createElement('dialog');document.body.append(entryDialog);entryDialog.showModal();
      const aapImportDialog=()=>entryDialog;const renderAapImportDialog=()=>{};
      const characterImportBase64=()=> 'synthetic'; const api=async()=>({});
      window.entryCalls=[]; const openAdaptationWorkbench=payload=>entryCalls.push({payload,work:state.work.id});
      window.cancelEntry=()=>{aapImportState=null;entryDialog.close();};
    """
        + source[start:end]
    )
    page.evaluate(
        "window.finishRead=null;void readAapImportFile({name:'A.txt',size:1,arrayBuffer:()=>new Promise(resolve=>finishRead=resolve)})"
    )
    page.evaluate("cancelEntry();entryState.work={id:'B'};finishRead(new ArrayBuffer(1))")
    assert page.evaluate("entryCalls") == []


def test_unsaved_character_mapping_does_not_leak_to_another_work(page):
    page.evaluate("ui.open()")
    page.locator("[data-field=mapping]").fill("甲 = 乙")
    page.get_by_role("button", name="关闭改编工作台", exact=True).click()
    page.evaluate(
        "activeWork={...activeWork,id:'work-2'};const api=bridge.api;bridge.api=(route,opt)=>route==='/works/work-2'?Promise.resolve(activeWork):api(route,opt);ui.open()"
    )
    assert page.locator("[data-field=mapping]").input_value() == ""


def test_inflight_poll_snapshot_cannot_restore_already_accepted_candidate(page):
    page.evaluate(r"""
      plans=[{id:'plan-1',source_version_id:source.id,status:'ready',plan:{},budget:{max_calls:5,reserved_calls:1},chapters:[
        {id:'adapt-A',source_chapter_id:'saved-ch',status:'candidate',dependency:{},candidate:{formal:false,proposal_id:'proposal-A',text:'老师: 待采纳。',target:{scene_id:null,chapter_id:'chapter-1'}}},
        {id:'adapt-B',source_chapter_id:'second',status:'planned',dependency:{},candidate:{}}]}];
      activeWork.agent_runs=[{id:'run-B',scope_id:'adapt-B',status:'running',policy:{workflow:'adaptation.chapter.generate'}}];
      window.oldReads=[];window.holdReads=false;window.pollTimer=null;
      window.setTimeout=fn=>{pollTimer=fn;return 1;};window.clearTimeout=()=>{};
      const original=bridge.api;
      bridge.api=async(route,options)=>{
        if(route.endsWith('/agent-runs/run-B'))return {...activeWork.agent_runs[0],status:'completed'};
        if(route.endsWith('/accept')){
          calls.push({route,body:JSON.parse(options.body)});
          plans[0].chapters[0].status='accepted';plans[0].chapters[0].candidate.formal=true;
          plans[0].chapters[0].dependency.scene_target={scene_id:'scene-A'};
          activeWork.agent_runs[0].status='completed';activeWork.version=8;
          return {work:activeWork,scene_id:'scene-A'};
        }
        const value=await original(route,options);
        if(holdReads){const old=structuredClone(value);return new Promise(resolve=>oldReads.push(()=>resolve(old)));}
        return value;
      };
      ui.open()
    """)
    page.evaluate("holdReads=true;void pollTimer()")
    page.wait_for_function("oldReads.length===4")
    page.evaluate("holdReads=false")
    page.get_by_role("button", name="采纳到此场景", exact=True).click()
    page.get_by_role("button", name="查看正式场景", exact=True).wait_for()
    page.evaluate("oldReads.forEach(resolve=>resolve())")
    assert page.get_by_role("button", name="查看正式场景", exact=True).count() == 1
    assert page.get_by_role("button", name="采纳到此场景", exact=True).count() == 0
