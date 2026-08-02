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


def test_asset_workbench_modules_do_not_build_untrusted_html_or_use_eval():
    for name in MODULES:
        source = (HERE / "js" / name).read_text(encoding="utf-8")
        assert "innerHTML" not in source
        assert "eval(" not in source


def test_existing_face_workspace_keeps_contact_sheet_and_semantic_results_until_split():
    source = (HERE / "js" / "library.js").read_text(encoding="utf-8")

    assert "renderLabels" in source
    assert "semantic_faces" in source
    assert "/api/assets/faces/contact-sheet" in source
    assert "rendered_count" in source


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
