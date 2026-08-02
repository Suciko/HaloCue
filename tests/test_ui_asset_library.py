import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def run_library(script: str) -> dict:
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "library.js")],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def test_material_workbench_is_separate_from_current_story_assets_and_csp_safe():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    assert 'id="assetLibraryDrawer"' in html
    assert 'data-library-action="open"' in html
    assert 'id="storyAssetStrip"' in html
    assert 'id="faceWorkspace"' in html
    assert 'id="faceWorkspaceStart"' in html
    assert html.index('id="storyAssetStrip"') < html.index('id="assetLibraryDrawer"')
    assert "归类不等于已导入" in html
    assert "每章仍需" in html
    assert '<script src="/js/library.js"></script>' in html
    assert "onclick=" not in html
    assert "onchange=" not in html


def test_character_card_opens_a_separate_face_workspace():
    source = (HERE / "js" / "library.js").read_text(encoding="utf-8")
    assert "表情标注" in source
    assert "FaceWorkspace" in source
    assert "/api/assets/library/character/face-analysis" in source
    assert "/api/assets/faces/job" in source
    assert "innerHTML" not in source
    assert "eval(" not in source


def test_material_workbench_loads_safe_history_and_saves_series_profile():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={},listeners={},requests=[];
function node(tag){let own='',classes=new Set(),events={};const n={tagName:tag||'div',children:[],parentNode:null,dataset:{},className:'',value:'',disabled:false,hidden:false,type:'',placeholder:'',maxLength:0,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){x.parentNode=this;this.children.push(x);return x},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(k,f){events[k]=f},dispatch(k,e){if(events[k])events[k](Object.assign({target:this},e||{}))},setAttribute(k,v){this[k]=v},focus(){this.focused=true},scrollIntoView(){this.scrolled=true},closest(selector){let p=this;while(p){if(selector==='.asset-library-card'&&String(p.className).split(/\s+/).includes('asset-library-card'))return p;if(selector==='[data-library-action]'&&p.dataset.libraryAction)return p;p=p.parentNode}return null},querySelector(selector){const match=selector.match(/^\[data-library-field="([^"]+)"\]$/);let found=null;function walk(p){p.children.forEach(c=>{if(found)return;if(match&&c.dataset.libraryField===match[1])found=c;else walk(c)})}walk(this);return found},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}};return n}
['assetLibraryDrawer','assetLibraryBackdrop','assetLibraryList','assetLibrarySummary','assetLibraryStatus','assetLibrarySearch','assetLibraryKind','assetLibraryRole','assetLibraryUseCurrent','storyAssetStrip'].forEach(id=>nodes[id]=node());nodes.assetLibraryKind.value='all';nodes.assetLibraryRole.value='all';
const response={characters:[{kind:'character',aa_key:'kei-date',sha256:'c'.repeat(64),name:'凯伊约会服',asset_role:'chapter_only',series_name:'',chapters:['第一章','第二章'],copy_count:2,details:{face_count:3,expression_status:'known'}}],backgrounds:[],sounds:[],bgms:[]};
const window={Api:{request:async(path,opts)=>{requests.push({path,opts});if(path==='/api/assets/library')return response;if(path==='/api/assets/library/profile')return {ok:true,asset_role:'series_shared',series_name:'凯伊约会篇'};throw new Error(path)},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>({story_token:'story-1'})},StoryUI:{}};
const document={getElementById:id=>nodes[id]||null,createElement:node,activeElement:node(),addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,Promise,Error,console,setTimeout:(f)=>f()});
(async()=>{const wb=window.AssetLibraryWorkbench,trigger=node();wb.open(trigger);await Promise.resolve();await Promise.resolve();await Promise.resolve();const loaded=nodes.assetLibraryList.textContent;const card=nodes.assetLibraryList.children[0],role=card.querySelector('[data-library-field="asset-role"]'),series=card.querySelector('[data-library-field="series-name"]'),form=card.children.find(x=>x.className==='asset-library-profile'),save=form.children[2];role.value='series_shared';nodes.assetLibraryDrawer.dispatch('change',{target:role});series.value='凯伊约会篇';await wb.save(save);const post=requests.find(x=>x.path==='/api/assets/library/profile');console.log(JSON.stringify({loaded,status:nodes.assetLibraryStatus.textContent,payload:post&&post.opts.payload,summary:nodes.assetLibrarySummary.textContent,privateLeak:loaded.includes('C:\\private')}));})();
'''
    result = run_library(script)
    assert "凯伊约会服" in result["loaded"]
    assert "第一章" in result["loaded"] and "第二章" in result["loaded"]
    assert "已识别 3 个表情候选" in result["loaded"]
    assert result["payload"] == {
        "kind": "character",
        "aa_key": "kei-date",
        "sha256": "c" * 64,
        "asset_role": "series_shared",
        "series_name": "凯伊约会篇",
    }
    assert "已保存" in result["status"]
    assert "自定义素材" in result["summary"] and "章节副本" in result["summary"]
    assert result["privateLeak"] is False


def test_material_workbench_bgm_filter_explains_verified_gate():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={};function n(){let own='',classes=new Set();const x={children:[],dataset:{},className:'',value:'',disabled:false,classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),contains:v=>classes.has(v)},appendChild(c){c.parentNode=this;this.children.push(c);return c},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(c=>c.textContent||'').join('')},addEventListener(){},setAttribute(){},focus(){},closest(){return null}};return x}['assetLibraryDrawer','assetLibraryBackdrop','assetLibraryList','assetLibrarySummary','assetLibraryStatus','assetLibrarySearch','assetLibraryKind','assetLibraryRole','assetLibraryUseCurrent'].forEach(id=>nodes[id]=n());nodes.assetLibraryKind.value='bgm';nodes.assetLibraryRole.value='all';const window={Api:{request:async()=>({characters:[],backgrounds:[],sounds:[],bgms:[]})},StoryStore:{get:()=>null},StoryUI:{}};const document={getElementById:id=>nodes[id]||null,createElement:n,activeElement:n(),addEventListener(){}};vm.runInNewContext(source,{window,document,Promise,Error,console,setTimeout});window.AssetLibraryWorkbench.items=[];window.AssetLibraryWorkbench.loading=false;window.AssetLibraryWorkbench.render();console.log(JSON.stringify({text:nodes.assetLibraryList.textContent,currentDisabled:nodes.assetLibraryUseCurrent.disabled}));
'''
    result = run_library(script)
    assert "BGM 登记暂未开放" in result["text"]
    assert "BgmOverrides" in result["text"]
    assert result["currentDisabled"] is True
