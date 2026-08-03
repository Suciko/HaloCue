# -*- coding: utf-8 -*-
"""素材工作台前端模块、导航状态和 CSP 行为。"""

import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
MODULES = (
    "library_preview.js",
    "library_transfer.js",
    "library_copies.js",
    "library_faces.js",
    "library.js",
)


def run_library(script: str) -> dict:
    output = subprocess.check_output(
        ["node", "-e", script, *[str(HERE / "js" / name) for name in MODULES]],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def test_material_workbench_is_full_screen_and_loads_split_csp_safe_modules():
    html = (HERE / "ui.html").read_text(encoding="utf-8")

    assert 'id="appShell"' in html
    assert 'id="assetWorkbench"' in html
    assert 'id="assetWorkbenchBody"' in html
    assert 'id="assetWorkbenchList"' in html
    assert 'id="assetWorkbenchDetail"' in html
    assert 'id="assetWorkbenchTasks"' in html
    assert 'aria-controls="assetWorkbench"' in html
    assert 'id="storyAssetStrip"' in html
    assert html.index('id="storyAssetStrip"') < html.index('id="assetWorkbench"')
    ordered_scripts = [f'<script src="/js/{name}"></script>' for name in MODULES]
    positions = [html.index(script) for script in ordered_scripts]
    assert positions == sorted(positions)
    assert "onclick=" not in html
    assert "onchange=" not in html


def test_face_workspace_uses_database_backed_editable_cards():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    source = (HERE / "js" / "library_faces.js").read_text(encoding="utf-8")
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")

    assert 'class="face-workspace-cards"' in html
    assert "/api/assets/faces/labels" in source
    assert "已保存到数据库" in source
    assert "face-workspace-card" in source
    assert "grid-template-columns:repeat(4" in css


def test_asset_workbench_opens_full_screen_sanitizes_context_and_restores_focus():
    script = r'''
const fs=require('fs'),vm=require('vm');
const sources=process.argv.slice(1).map(path=>fs.readFileSync(path,'utf8'));
const nodes={},listeners={};let document;
function node(id){
  let own='',attrs={},events={},classes=new Set();
  const n={id:id||'',children:[],parentNode:null,dataset:{},className:'',hidden:false,value:'',disabled:false,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x)},
    appendChild(child){child.parentNode=this;this.children.push(child);return child},
    addEventListener(kind,fn){events[kind]=fn},dispatch(kind,event){if(events[kind])events[kind](Object.assign({target:this},event||{}))},
    setAttribute(key,value){attrs[key]=String(value)},getAttribute(key){return attrs[key]},removeAttribute(key){delete attrs[key]},
    focus(){document.activeElement=this},querySelector(){return null},closest(){return null},
    set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}
  };return n;
}
['appShell','assetWorkbench','assetWorkbenchBack','assetWorkbenchContext','assetWorkbenchTaskToggle','assetWorkbenchBody','assetWorkbenchFilters','assetWorkbenchList','assetWorkbenchDetail','assetWorkbenchTasks','assetWorkbenchStatus'].forEach(id=>nodes[id]=node(id));
nodes.assetWorkbench.hidden=true;nodes.appShell.hidden=false;
const trigger=node('trigger');
document={activeElement:trigger,getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener:(kind,fn)=>listeners[kind]=fn};
const requests=[];
const response={characters:[],backgrounds:[{kind:'background',aa_key:'rain',sha256:'digest',name:'雨夜天台',copies:[],copy_count:0}],sounds:[],bgms:[]};
const window={StoryUI:{},StoryStore:{get:()=>({story_token:'story-1',project:'第一章'})},Api:{request:async path=>{requests.push(path);return response},json:(method,payload)=>({method,payload})}};
const context={window,document,Promise,Error,console,setTimeout,clearTimeout,encodeURIComponent,CustomEvent:function(name,options){this.type=name;this.detail=options&&options.detail}};
sources.forEach(source=>vm.runInNewContext(source,context));
(async()=>{
  const workbench=window.AssetWorkbench;
  await workbench.open({origin:'preflight',story_token:'story-1',tasks:[],source_path:'C:\\private\\story.txt'});
  const opened={workbenchHidden:nodes.assetWorkbench.hidden,appHidden:nodes.appShell.hidden,request:requests[0],context:workbench.context,modules:{preview:!!workbench.preview,transfer:!!workbench.transfer,copies:!!workbench.copies}};
  await workbench.close();
  console.log(JSON.stringify({opened,closed:{workbenchHidden:nodes.assetWorkbench.hidden,appHidden:nodes.appShell.hidden,focus:document.activeElement.id}}));
})();
'''
    result = run_library(script)

    assert result["opened"]["workbenchHidden"] is False
    assert result["opened"]["appHidden"] is True
    assert result["opened"]["request"] == "/api/assets/library?story_token=story-1"
    assert result["opened"]["context"] == {
        "origin": "preflight",
        "story_token": "story-1",
        "tasks": [],
    }
    assert result["opened"]["modules"] == {
        "preview": True,
        "transfer": True,
        "copies": True,
    }
    assert result["closed"] == {
        "workbenchHidden": True,
        "appHidden": False,
        "focus": "trigger",
    }


def test_current_tasks_drawer_includes_face_job_and_polls_while_it_runs():
    script = r'''
const fs=require('fs'),vm=require('vm');
const sources=process.argv.slice(1).map(path=>fs.readFileSync(path,'utf8'));
const nodes={},listeners={},timers=[];let document;
function node(id){
  let own='',attrs={},events={},classes=new Set();
  return {id:id||'',children:[],parentNode:null,dataset:{},className:'',hidden:false,value:'',disabled:false,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x)},
    appendChild(child){child.parentNode=this;this.children.push(child);return child},
    addEventListener(kind,fn){events[kind]=fn},setAttribute(key,value){attrs[key]=String(value)},getAttribute(key){return attrs[key]},removeAttribute(key){delete attrs[key]},
    focus(){document.activeElement=this},querySelector(){return null},closest(){return null},
    set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}
  };
}
['appShell','assetWorkbench','assetWorkbenchBack','assetWorkbenchContext','assetWorkbenchTaskToggle','assetWorkbenchBody','assetWorkbenchFilters','assetWorkbenchList','assetWorkbenchDetail','assetWorkbenchTasks','assetWorkbenchStatus'].forEach(id=>nodes[id]=node(id));
nodes.assetWorkbench.hidden=true;nodes.appShell.hidden=false;
document={activeElement:node('trigger'),getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener:(kind,fn)=>listeners[kind]=fn};
const requests=[];
const assets={characters:[{kind:'character',aa_key:'626652156',sha256:'digest',name:'凯伊（约会服）',copies:[],details:{file_count:4,face_count:44}}],backgrounds:[],sounds:[],bgms:[]};
const jobs=[
  {running:true,done:false,ok:false,ident:'626652156',phase:'AI 识别',message:'正在识别第 3 批',current:27,total:44,log:['九宫格 2/5 完成'],result:{rendered_count:44,labeled_count:18,saved_count:18,failed_count:0}},
  {running:false,done:true,ok:true,ident:'626652156',phase:'完成',message:'标注完成',current:44,total:44,log:['数据库写入完成'],result:{rendered_count:44,labeled_count:44,saved_count:44,failed_count:0,completed_at:'2026-08-03 14:26:30'}}
];
const window={StoryUI:{},StoryStore:{get:()=>({story_token:'story-1'})},Api:{request:async path=>{requests.push(path);return path.startsWith('/api/assets/faces/job')?jobs.shift():assets},json:(method,payload)=>({method,payload})}};
const context={window,document,Promise,Error,console,encodeURIComponent,CustomEvent:function(){},ResizeObserver:undefined,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length},clearTimeout(){},setImmediate};
sources.forEach(source=>vm.runInNewContext(source,context));
(async()=>{
  await window.AssetWorkbench.open({story_token:'story-1',tasks:[{task_id:'bg-1',kind:'background',requested_name:'雨夜天台',reason:'剧情引用但未登记'}]});
  const running={text:nodes.assetWorkbenchTasks.textContent,timers:timers.map(item=>item.delay)};
  timers.shift().fn();
  await new Promise(resolve=>setImmediate(resolve));
  console.log(JSON.stringify({requests,running,completed:{text:nodes.assetWorkbenchTasks.textContent,timers:timers.map(item=>item.delay)}}));
})();
'''
    result = run_library(script)

    assert "/api/assets/faces/job" in result["requests"]
    assert "雨夜天台" in result["running"]["text"]
    assert "凯伊（约会服）" in result["running"]["text"]
    assert "27 / 44" in result["running"]["text"]
    assert "已渲染 44" in result["running"]["text"]
    assert "AI 标注 18" in result["running"]["text"]
    assert "数据库 18" in result["running"]["text"]
    assert result["running"]["timers"] == [1000]
    assert "完成时间 2026-08-03 14:26:30" in result["completed"]["text"]
    assert "查看标注" in result["completed"]["text"]
    assert result["completed"]["timers"] == []


def test_current_tasks_drawer_retries_an_initial_job_poll_failure():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const nodes={},timers=[];let document;
function node(id){let own='',attrs={},classes=new Set();return {id:id||'',children:[],dataset:{},hidden:false,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x)},appendChild(child){this.children.push(child);return child},addEventListener(){},setAttribute(k,v){attrs[k]=String(v)},focus(){},querySelector(){return null},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
['appShell','assetWorkbench','assetWorkbenchContext','assetWorkbenchTaskToggle','assetWorkbenchBody','assetWorkbenchFilters','assetWorkbenchList','assetWorkbenchDetail','assetWorkbenchTasks','assetWorkbenchStatus'].forEach(id=>nodes[id]=node(id));
document={activeElement:null,getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener(){}};
let rejectRequest,requests=0;
const window={StoryUI:{AssetPreview:function(){this.stop=function(){}},TransferController:function(){},CopyManager:function(){}},Api:{request:()=>{requests++;return new Promise((resolve,reject)=>{rejectRequest=reject})}}};
vm.runInNewContext(source,{window,document,Promise,Error,console,ResizeObserver:undefined,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length},clearTimeout(){},encodeURIComponent});
(async()=>{nodes.assetWorkbench.hidden=false;const first=window.AssetWorkbench.refreshTasks(),second=window.AssetWorkbench.refreshTasks();rejectRequest(new Error('disconnect'));await Promise.all([first,second]);console.log(JSON.stringify({requests,timers:timers.map(item=>item.delay),text:nodes.assetWorkbenchTasks.textContent}));})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library.js")],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["requests"] == 1
    assert result["timers"] == [3000]
    assert "自动重试" in result["text"]


def test_asset_workbench_modules_do_not_build_untrusted_html_or_use_eval():
    for name in MODULES:
        source = (HERE / "js" / name).read_text(encoding="utf-8")
        assert "innerHTML" not in source
        assert "eval(" not in source


def test_face_workspace_is_split_and_keeps_contact_sheet_and_semantic_results():
    source = (HERE / "js" / "library_faces.js").read_text(encoding="utf-8")
    library = (HERE / "js" / "library.js").read_text(encoding="utf-8")

    assert "renderLabels" in source
    assert "semantic_faces" in source
    assert "/api/assets/faces/contact-sheet" in source
    assert "rendered_count" in source
    assert "function FaceWorkspace" not in library
    assert "new window.StoryUI.FaceWorkspace" not in library


def test_face_workspace_hides_workbench_and_returns_to_selected_asset_and_scroll():
    source = (HERE / "js" / "library_faces.js").read_text(encoding="utf-8")

    assert "workbench.root.hidden = true" in source
    assert "workbench.root.hidden = false" in source
    assert "workbench.selectedKey" in source
    assert "scrollTop" in source


def test_face_workspace_recovers_after_a_transient_job_poll_failure():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const nodes={},timers=[];
function node(id){
  let own='',classes=new Set();
  return {id:id||'',children:[],dataset:{},hidden:false,disabled:false,src:'',
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},
    appendChild(child){this.children.push(child);return child},addEventListener(){},setAttribute(){},removeAttribute(key){this[key]=''},focus(){},closest(){return null},
    set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}
  };
}
['faceWorkspaceBackdrop','faceWorkspace','faceWorkspaceCharacter','faceWorkspacePhase','faceWorkspaceProgress','faceWorkspaceResult','faceWorkspaceForceVision','faceWorkspaceStart','faceWorkspaceStatus','faceWorkspaceSheet','faceWorkspaceLabels','faceWorkspaceLog'].forEach(id=>nodes[id]=node(id));
nodes.faceWorkspace.classList.add('open');
const document={activeElement:null,getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener(){}};
let requests=0;
const responses=[
  new Error('temporary disconnect'),
  {running:true,done:false,ok:false,ident:'626652156',phase:'rendering',message:'正在渲染 01',current:1,total:2,log:['正在渲染 01']},
  {running:false,done:true,ok:true,ident:'626652156',phase:'complete',message:'渲染完成',current:2,total:2,log:['渲染完成'],result:{rendered_count:2,semantic_faces:[]}}
];
const window={StoryUI:{},Api:{request:()=>{requests++;const value=responses.shift();return value instanceof Error?Promise.reject(value):Promise.resolve(value)}}};
const context={window,document,Promise,Error,console,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length},clearTimeout(){},setImmediate};
vm.runInNewContext(source,context);
(async()=>{
  const workspace=window.FaceWorkspace;
  workspace.selected={kind:'character',aa_key:'626652156',name:'凯伊'};
  await workspace.refresh();
  const afterFailure={timerCount:timers.length,delay:timers[0]&&timers[0].delay,status:nodes.faceWorkspaceStatus.textContent,disabled:nodes.faceWorkspaceStart.disabled};
  if (!timers.length) {
    console.log(JSON.stringify({afterFailure,afterRecovery:null,final:null}));
    return;
  }
  timers.shift().fn();
  await new Promise(resolve=>setImmediate(resolve));
  const afterRecovery={requests,timerCount:timers.length,progress:nodes.faceWorkspaceProgress.textContent,status:nodes.faceWorkspaceStatus.textContent,pollFailures:workspace.pollFailures,disabled:nodes.faceWorkspaceStart.disabled};
  timers.shift().fn();
  await new Promise(resolve=>setImmediate(resolve));
  console.log(JSON.stringify({afterFailure,afterRecovery,final:{requests,timerCount:timers.length,phase:nodes.faceWorkspacePhase.textContent,result:nodes.faceWorkspaceResult.textContent}}));
})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_faces.js")],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["afterFailure"]["timerCount"] == 1
    assert result["afterFailure"]["delay"] > 850
    assert "自动重试" in result["afterFailure"]["status"]
    assert result["afterFailure"]["disabled"] is True
    assert result["afterRecovery"] == {
        "requests": 2,
        "timerCount": 1,
        "progress": "1 / 2",
        "status": "正在渲染 01",
        "pollFailures": 0,
        "disabled": True,
    }
    assert result["final"] == {
        "requests": 3,
        "timerCount": 0,
        "phase": "complete",
        "result": "2 个差分",
    }


def test_face_workspace_keeps_polling_while_another_character_job_runs():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const nodes={},timers=[];
function node(id){let own='',classes=new Set();return {id:id||'',children:[],dataset:{},hidden:false,disabled:false,src:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},appendChild(child){this.children.push(child);return child},addEventListener(){},setAttribute(){},removeAttribute(key){this[key]=''},focus(){},closest(){return null},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
['faceWorkspaceBackdrop','faceWorkspace','faceWorkspaceCharacter','faceWorkspacePhase','faceWorkspaceProgress','faceWorkspaceResult','faceWorkspaceForceVision','faceWorkspaceStart','faceWorkspaceStatus','faceWorkspaceSheet','faceWorkspaceLabels','faceWorkspaceLog'].forEach(id=>nodes[id]=node(id));
nodes.faceWorkspace.classList.add('open');
const document={activeElement:null,getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener(){}};
const window={StoryUI:{},Api:{request:async()=>({running:true,done:false,ok:false,ident:'another-character',phase:'rendering',message:'另一项处理中',current:1,total:3,log:[]})}};
vm.runInNewContext(source,{window,document,Promise,Error,console,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length},clearTimeout(){}});
(async()=>{const workspace=window.FaceWorkspace;workspace.selected={kind:'character',aa_key:'626652156',name:'凯伊'};await workspace.refresh();console.log(JSON.stringify({timers:timers.map(timer=>timer.delay),disabled:nodes.faceWorkspaceStart.disabled,phase:nodes.faceWorkspacePhase.textContent}));})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_faces.js")],
        text=True,
        encoding="utf-8",
    )

    assert json.loads(output) == {
        "timers": [850],
        "disabled": True,
        "phase": "另一项骨骼正在处理",
    }


def test_face_workspace_ignores_an_older_poll_that_finishes_after_a_newer_one():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const nodes={},timers=[],pending=[];
function node(id){let own='',classes=new Set();return {id:id||'',children:[],dataset:{},hidden:false,disabled:false,src:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},appendChild(child){this.children.push(child);return child},addEventListener(){},setAttribute(){},removeAttribute(key){this[key]=''},focus(){},closest(){return null},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
['faceWorkspaceBackdrop','faceWorkspace','faceWorkspaceCharacter','faceWorkspacePhase','faceWorkspaceProgress','faceWorkspaceResult','faceWorkspaceForceVision','faceWorkspaceStart','faceWorkspaceStatus','faceWorkspaceSheet','faceWorkspaceLabels','faceWorkspaceLog'].forEach(id=>nodes[id]=node(id));
nodes.faceWorkspace.classList.add('open');
const document={activeElement:null,getElementById:id=>nodes[id]||null,createElement:tag=>node(tag),addEventListener(){}};
const window={StoryUI:{},Api:{request:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))}};
vm.runInNewContext(source,{window,document,Promise,Error,console,setTimeout:(fn,delay)=>{timers.length=0;timers.push({fn,delay});return 1},clearTimeout(){timers.length=0},setImmediate});
(async()=>{
  const workspace=window.FaceWorkspace;workspace.selected={kind:'character',aa_key:'626652156',name:'凯伊'};
  const older=workspace.refresh(),newer=workspace.refresh();
  pending[1].resolve({running:true,done:false,ok:false,ident:'626652156',phase:'rendering',message:'新进度',current:1,total:2,log:['新进度'],result:{}});
  await newer;
  pending[0].reject(new Error('旧请求失败'));
  await older;
  console.log(JSON.stringify({status:nodes.faceWorkspaceStatus.textContent,progress:nodes.faceWorkspaceProgress.textContent,pollFailures:workspace.pollFailures,timers:timers.map(timer=>timer.delay),disabled:nodes.faceWorkspaceStart.disabled}));
})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_faces.js")],
        text=True,
        encoding="utf-8",
    )

    assert json.loads(output) == {
        "status": "新进度",
        "progress": "1 / 2",
        "pollFailures": 0,
        "timers": [850],
        "disabled": True,
    }


def test_typed_preview_renders_safe_background_character_and_sound_details():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(tag){let own='';return {tagName:tag,children:[],className:'',hidden:false,src:'',alt:'',controls:false,dataset:{},appendChild(child){this.children.push(child);return child},pause(){this.paused=true},load(){this.loaded=true},removeAttribute(key){this[key]=''},setAttribute(key,value){this[key]=String(value)},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
const root=node('section'),document={createElement:node};const window={StoryUI:{}};vm.runInNewContext(source,{window,document});
const preview=new window.StoryUI.AssetPreview(root),results=[];
preview.render({kind:'background',name:'雨夜天台',preview_token:'preview-bg',preview_available:true,details:{resolution:'1920×1080',labels:{place:'屋顶'}}});results.push({text:root.textContent,src:root.children.find(child=>child.tagName==='img').src});
preview.render({kind:'character',name:'阿洛娜',preview_token:'preview-character',preview_available:true,details:{file_count:4,face_count:7,expression_status:'known'}});results.push({text:root.textContent});
preview.render({kind:'sound',name:'开门声',preview_token:'preview-sound',preview_available:true,details:{duration:1.25,codec:'wav'}});const audio=root.children.find(child=>child.tagName==='audio');results.push({text:root.textContent,src:audio.src,controls:audio.controls});
console.log(JSON.stringify(results));
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_preview.js")],
        text=True,
        encoding="utf-8",
    )
    background, character, sound = json.loads(output)

    assert "1920×1080" in background["text"] and "屋顶" in background["text"]
    assert background["src"] == "/api/assets/library/preview?preview_token=preview-bg"
    assert "4 个骨骼文件" in character["text"] and "7 个表情" in character["text"]
    assert "1.25 秒" in sound["text"] and "wav" in sound["text"]
    assert sound["src"].endswith("preview-sound") and sound["controls"] is True


def test_copy_controller_reports_four_stable_phases_and_dispatches_safe_result():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const phases=[],requests=[],events=[];
const window={StoryUI:{},Api:{json:(method,payload)=>({method,payload}),request:async(path,options)=>{requests.push({path,options});return {ok:true,state:'registered',asset:{kind:'background',aa_key:'rain_roof',name:'雨夜天台'}}}},dispatchEvent:event=>events.push(event.detail)};
const CustomEvent=function(name,options){this.type=name;this.detail=options.detail};
vm.runInNewContext(source,{window,CustomEvent,Error,Promise});
const workbench={context:{story_token:'story-1'},setTransferState:(state)=>phases.push(state),refresh:async()=>{workbench.refreshed=true}};
const item={kind:'background',aa_key:'rain_roof',sha256:'digest',copies:[{copy_token:'copy-source'}]};
(async()=>{const result=await new window.StoryUI.TransferController(workbench).copy(item);console.log(JSON.stringify({phases,requests,events,result,refreshed:workbench.refreshed}));})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_transfer.js")],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["phases"] == ["正在校验", "正在复制", "正在登记", "本章已登记"]
    assert result["requests"] == [{
        "path": "/api/assets/library/copy-to-story",
        "options": {
            "method": "POST",
            "payload": {
                "story_token": "story-1",
                "kind": "background",
                "aa_key": "rain_roof",
                "sha256": "digest",
                "source_copy_token": "copy-source",
            },
        },
    }]
    assert result["events"][0]["story_token"] == "story-1"
    assert result["events"][0]["aa_key"] == "rain_roof"
    assert result["refreshed"] is True


def test_copy_manager_blocks_referenced_copy_before_posting_removal():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8'),requests=[];
function node(){let own='';return {children:[],dataset:{},className:'',type:'',disabled:false,appendChild(child){this.children.push(child);return child},addEventListener(){},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
const document={createElement:node};const window={StoryUI:{},Api:{request:async path=>{requests.push(path);return {ok:true,copies:[{copy_token:'copy-1',chapter:'第二章',references:[{card_id:'bg-1',label:'@bg rain_roof'}]}]}}}};
vm.runInNewContext(source,{window,document,encodeURIComponent,Error,Promise});
const detail=node(),states=[],workbench={detail,setCopyState:text=>states.push(text),focusReference:reference=>{workbench.focused=reference}};
(async()=>{const manager=new window.StoryUI.CopyManager(workbench);await manager.open({name:'雨夜天台',preview_token:'preview-1'});await manager.remove(manager.copies[0]);console.log(JSON.stringify({requests,states,text:detail.textContent,focused:workbench.focused}));})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library_copies.js")],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["requests"] == [
        "/api/assets/library/copies?preview_token=preview-1"
    ]
    assert "仍被草稿引用" in result["states"][-1]
    assert "移除该章节副本" not in result["text"]
    assert result["focused"]["card_id"] == "bg-1"


def test_catalog_combines_filter_hierarchy_auxiliary_detail_and_explicit_actions():
    script = r'''
const fs=require('fs'),vm=require('vm'),sources=process.argv.slice(1).map(path=>fs.readFileSync(path,'utf8'));const nodes={};let document;
function node(tag){let own='',classes=new Set(),events={};return {tagName:tag,id:'',children:[],parentNode:null,dataset:{},className:'',hidden:false,value:'',type:'',disabled:false,src:'',alt:'',controls:false,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x)},appendChild(child){child.parentNode=this;this.children.push(child);return child},addEventListener(type,handler){events[type]=handler},setAttribute(){},removeAttribute(){},focus(){document.activeElement=this},pause(){},load(){},closest(){return null},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
['appShell','assetWorkbench','assetWorkbenchContext','assetWorkbenchTaskToggle','assetWorkbenchFilters','assetWorkbenchList','assetWorkbenchDetail','assetWorkbenchTasks','assetWorkbenchStatus'].forEach(id=>{nodes[id]=node('div');nodes[id].id=id});nodes.assetWorkbench.hidden=true;
document={activeElement:node('button'),getElementById:id=>nodes[id]||null,createElement:node,addEventListener(){}};
const payload={characters:[],backgrounds:[{kind:'background',aa_key:'rain_roof',sha256:'digest',name:'雨夜天台',registered_in_current:false,preview_available:true,preview_token:'preview-bg',copy_count:1,copies:[{chapter:'第一章',copy_token:'copy-1'}],details:{resolution:'1920×1080',labels:{place:'屋顶'}}}],sounds:[],bgms:[]};
const window={StoryUI:{},StoryStore:{get:()=>({story_token:'story-1',project:'第二章'})},Api:{request:async()=>payload,json:(method,payload)=>({method,payload})}};
sources.forEach(source=>vm.runInNewContext(source,{window,document,Promise,Error,console,setTimeout,clearTimeout,encodeURIComponent,CustomEvent:function(){}}));
(async()=>{await window.AssetWorkbench.open({origin:'topbar',story_token:'story-1'});console.log(JSON.stringify({filters:nodes.assetWorkbenchFilters.textContent,row:nodes.assetWorkbenchList.children[0].textContent,detail:nodes.assetWorkbenchDetail.textContent}));})();
'''
    result = run_library(script)

    assert all(label in result["filters"] for label in ("全部", "骨骼", "背景", "音效"))
    assert all(value in result["row"] for value in ("雨夜天台", "背景", "未登记", "1920×1080"))
    assert "1920×1080" in result["detail"] and "屋顶" in result["detail"]
    assert "复制到当前剧情" in result["detail"]
    assert "管理副本" in result["detail"]
