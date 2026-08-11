from __future__ import annotations

import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[2] / "main" / "python"


def run_node(script: str, *sources: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script, *(str(HERE / source) for source in sources)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_story_summary_prefers_source_filename_over_internal_workspace_path():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function classList(){const values=new Set();return {add:v=>values.add(v),remove:v=>values.delete(v),toggle:(v,on)=>on?values.add(v):values.delete(v),contains:v=>values.has(v)}}
function n(){return {hidden:false,textContent:'',classList:classList(),append(){},appendChild(){},addEventListener(){}}}
const nodes={storyContextName:n(),storyContextMeta:n(),storyContextAction:n(),storyContextStatus:n()};
const window={Api:{request:async()=>[]}};
const document={getElementById:id=>nodes[id]||null,createElement:n};
vm.runInNewContext(source,{window,document,Date,Number,Set,console});
const root=n(),bar=new window.StoryUI.StoryContextBar(root);
bar.render({source_display:'/workspace/imports/hidden-token/chapter-01.txt',source_name:'chapter-01.txt',project:'chapter-01'});
console.log(JSON.stringify({title:nodes.storyContextName.textContent}));
"""

    result = run_node(script, "js/story.js")

    assert result == {"title": "chapter-01.txt"}


def test_asset_strip_marks_only_the_genuinely_empty_story_as_compact():
    script = r"""
const fs=require('fs'),vm=require('vm');
function classList(){const values=new Set();return {add:v=>values.add(v),remove:v=>values.delete(v),toggle:(v,on)=>on?values.add(v):values.delete(v),contains:v=>values.has(v)}}
function n(){
  let content='';
  return {hidden:false,disabled:false,dataset:{},children:[],className:'',classList:classList(),
    appendChild(x){this.children.push(x);return x},append(...xs){this.children.push(...xs)},
    addEventListener(){},setAttribute(){},querySelectorAll(){return []},querySelector(){return null},
    get firstChild(){return this.children[0]},get textContent(){return content},set textContent(v){content=v;this.children=[]}};
}
let story={story_token:'story-1'};
const window={StoryUI:{},StoryStore:{get:()=>story},Api:{request:async()=>({}),poll:async()=>({})}};
const document={getElementById:()=>null,createElement:n,querySelectorAll:()=>[],activeElement:null,addEventListener(){}};
const context={window,document,Set,Object,Array,Promise,Error,console,encodeURIComponent,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const root=n(),strip=new window.StoryUI.StoryAssetStrip(root);
strip.render(false,null);
const empty=root.classList.contains('is-empty-state');
strip.tasks=[{id:'task-1',storyToken:'story-1',kind:'background',state:'validating',name:'new-bg.png'}];
strip.render(false,null);
const withTask=root.classList.contains('is-empty-state');
strip.tasks=[];
strip.items.backgrounds=[{aa_key:'bg-1',display_name:'Classroom'}];
strip.render(false,null);
const withAsset=root.classList.contains('is-empty-state');
strip.items.backgrounds=[];
strip.render(true,null);
const whileLoading=root.classList.contains('is-empty-state');
strip.render(false,'load failed');
const withError=root.classList.contains('is-empty-state');
console.log(JSON.stringify({empty,withTask,withAsset,whileLoading,withError}));
"""

    result = run_node(script, "js/assets.js")

    assert result == {
        "empty": True,
        "withTask": False,
        "withAsset": False,
        "whileLoading": False,
        "withError": False,
    }


def test_preflight_hydration_syncs_avatar_and_faces_back_to_mapping():
    javascript = (HERE / "js" / "app.js").read_text(encoding="utf-8")

    assert "syncPreflightCharacterMapping(item)" in javascript
    assert "await hydratePreflightCharacters(result); applyPreflightMapping(result)" in javascript
    assert "faces: item.faces !== undefined" in javascript


def test_asset_workbench_without_story_uses_empty_state_not_service_error():
    javascript = (HERE / "js" / "library.js").read_text(encoding="utf-8")

    assert "if (!this.context.story_token)" in javascript
    assert "请先打开剧情；之后可在这里浏览和导入素材。" in javascript


def test_cast_picker_searches_current_speaker_before_rendering_catalog():
    javascript = (HERE / "js" / "app.js").read_text(encoding="utf-8")

    assert "if (search) search.value = who;" in javascript
    assert "searchCharacters(who);" in javascript


def test_deepseek_preset_uses_requested_flash_model():
    javascript = (HERE / "js" / "app.js").read_text(encoding="utf-8")
    profiles = (HERE / "model_profiles.py").read_text(encoding="utf-8")

    assert "model: 'deepseek-v4-flash'" in javascript
    assert '"model": "deepseek-v4-flash"' in profiles


def test_empty_model_name_uses_first_discovered_model():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const window={};
vm.runInNewContext(source,{window,Number,Object,Array,String,Set});
const choose=window.ModelSettings.preferredDiscoveredModel;
console.log(JSON.stringify({
  empty:choose('',[{model_id:'first-model'},{model_id:'second-model'}]),
  existing:choose('manual-model',[{model_id:'first-model'}]),
  none:choose('',[])
}));
"""

    result = run_node(script, "js/model.js")

    assert result == {
        "empty": "first-model",
        "existing": "manual-model",
        "none": "",
    }


def test_command_controls_are_centered_without_centering_catalog_rows():
    css = (HERE / "css" / "layout.css").read_text(encoding="utf-8")

    assert ".asset-workbench-header button," in css
    assert ".review-build-toolbar button," in css
    assert "justify-content:center;\n  text-align:center;" in css
    assert ".asset-workbench-row{width:100%" in css
    assert "background:transparent;color:var(--fg);text-align:left" in css


def test_custom_character_display_name_falls_back_to_selected_bundle_name():
    javascript = (HERE / "js" / "library_import.js").read_text(encoding="utf-8")

    assert "selectionDisplayName" in javascript
    assert "(!identifier || !displayName)" not in javascript
    assert "if (this.kind === 'character' && !identifier)" in javascript
