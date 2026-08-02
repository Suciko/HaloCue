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
