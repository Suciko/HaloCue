import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def run_assets(script: str) -> dict:
    """Run the browser component in a small DOM, keeping network at its API boundary."""
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "assets.js")],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def run_history(script: str) -> dict:
    """Run the history drawer with the real asset task pipeline in a tiny DOM."""
    output = subprocess.check_output(
        [
            "node", "-e", script,
            str(HERE / "js" / "assets.js"),
            str(HERE / "js" / "history.js"),
        ],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def run_cards(script: str) -> dict:
    """Run the read-only card renderer in a small DOM."""
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "cards.js")],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def test_asset_task_card_keeps_one_card_through_validation_and_aa_waiting_states():
    """Replacing a task card instead of updating it loses the user's recovery context."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(){let own='';const classes=new Set();return {children:[],dataset:{},className:'',type:'',value:'',placeholder:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(), story={story_token:'story-a',project:'A'}, window={Api:{request:async()=>({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}}),json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});
const assets=new window.StoryUI.StoryAssetStrip(root);const card=assets.beginTask({kind:'background',name:'night.png',storyToken:'story-a'});assets.updateTask(card.id,{state:'validated'});assets.updateTask(card.id,{state:'waiting_for_aa'});const waiting={id:card.id,state:assets.tasks[0].state,text:root.textContent};assets.updateTask(card.id,{state:'failed',code:'validation_failed',message:'图片格式不支持'});const failed={state:assets.tasks[0].state,text:root.textContent};console.log(JSON.stringify({waiting,failed,taskCount:assets.tasks.length}));
'''
    result = run_assets(script)
    assert result["taskCount"] == 1
    assert result["waiting"]["state"] == "waiting_for_aa"
    assert "关闭 AA" in result["waiting"]["text"]
    assert result["failed"]["state"] == "failed"
    assert "重新选择" in result["failed"]["text"]


def test_asset_tasks_map_running_and_interrupted_to_retryable_guidance():
    """A stable backend code must leave a useful next action on the same task card."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(), story={story_token:'story-a',project:'A'}, window={Api:{request:async()=>({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}}),json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});
const assets=new window.StoryUI.StoryAssetStrip(root);const card=assets.beginTask({kind:'sound',name:'rain.wav',storyToken:'story-a'});assets.updateTask(card.id,{state:'failed',code:'aa_running'});const running=root.textContent;assets.updateTask(card.id,{state:'interrupted'});console.log(JSON.stringify({running,interrupted:root.textContent}));
'''
    result = run_assets(script)
    assert "关闭 AA" in result["running"]
    assert "重试" in result["running"]
    assert "重试" in result["interrupted"]


def test_load_uses_story_scoped_endpoint_and_discards_a_late_other_story_response():
    """Dropping the captured token check would render story A's assets in story B."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');let release;let story={story_token:'story-a',project:'A'};let requested='';
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:p=>{requested=p;return new Promise(r=>release=r)},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);const loading=assets.load('story-a');story={story_token:'story-b',project:'B'};release({characters:[{name:'A Hero',status:'registered'}],backgrounds:[],sounds:[],bgms:[],counts:{characters:1,backgrounds:0,sounds:0,bgms:0}});await loading;console.log(JSON.stringify({requested,text:root.textContent}));})();
'''
    result = run_assets(script)
    assert result["requested"] == "/api/story/assets?story_token=story-a"
    assert "A Hero" not in result["text"]


def test_recovery_marks_only_its_story_task_interrupted_when_a_job_is_gone():
    """A 404/410 is terminal: recovery must not retry it or mutate another story task."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');let polls=0;let story={story_token:'story-a',project:'A'};
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:async()=>({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}}),json:(m,p)=>({method:m,payload:p}),poll:()=>{polls++;return Promise.reject(Object.assign(new Error('gone'),{status:410}))}},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console,setTimeout});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);const a=assets.beginTask({kind:'sound',name:'a.wav',storyToken:'story-a',jobId:'gone'});assets.updateTask(a.id,{state:'registering'});const b=assets.beginTask({kind:'sound',name:'b.wav',storyToken:'story-b',jobId:'live'});assets.updateTask(b.id,{state:'registering'});assets.recoverTasks('story-a');await Promise.resolve();await Promise.resolve();console.log(JSON.stringify({polls,a:assets.tasks.find(x=>x.id===a.id).state,b:assets.tasks.find(x=>x.id===b.id).state}));})();
'''
    result = run_assets(script)
    assert result == {"polls": 1, "a": "interrupted", "b": "registering"}


def test_character_import_uses_identifier_display_name_file_token_and_story_token():
    """The character dialog must never fall through to an empty-context import."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');let requests=[];const story={story_token:'story-a',project:'A'};
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const responses=[{file_token:'picker-token'},{ok:true},{ok:true,status:'registered'}];const root=node(),window={Api:{request:(path,opts)=>{requests.push({path,opts});return Promise.resolve(responses.shift()||{characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}})},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);await assets.importLocal('character',{path:'C:/private/hero',identifier:'hero-id',displayName:'Hero'});console.log(JSON.stringify(requests));})();
'''
    requests = run_assets(script)
    assert requests[0]["path"] == "/api/picker"
    assert requests[1]["opts"]["payload"] == {
        "kind": "character", "file_token": "picker-token", "story_token": "story-a",
        "identifier": "hero-id", "display_name": "Hero",
    }
    assert requests[2]["opts"]["payload"] == requests[1]["opts"]["payload"]


def test_background_import_uses_selected_file_token_without_prompting_for_a_path():
    """A picker selection must go straight to validation without asking for a host path."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const requests=[];const story={story_token:'story-a',project:'A'};
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={prompt(){throw new Error('path prompt must not open')},Api:{request:(path,opts)=>{requests.push({path,opts});if(path==='/api/assets/validate')return Promise.resolve({ok:true});if(path==='/api/assets/register')return Promise.resolve({ok:true,status:'registered',kind:'background',aa_key:'rain-night'});return Promise.resolve({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}})},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);const result=await assets.importLocal('background',{fileToken:'ft-image',name:'rain.png'});console.log(JSON.stringify({result,requests}));})();
'''
    result = run_assets(script)
    assert [request["path"] for request in result["requests"][:2]] == [
        "/api/assets/validate", "/api/assets/register",
    ]
    assert result["requests"][0]["opts"]["payload"] == {
        "kind": "background", "file_token": "ft-image", "story_token": "story-a",
    }
    assert result["result"]["aa_key"] == "rain-night"


def test_visual_background_import_labels_then_stays_available_when_ai_fails():
    """Background registration succeeds independently from the optional vision job."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const requests=[];const story={story_token:'story-a',project:'A'};let finishPoll;
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:(path,opts)=>{requests.push({path,opts});if(path==='/api/picker')return Promise.resolve({file_token:'ft-image'});if(path==='/api/assets/validate')return Promise.resolve({ok:true});if(path==='/api/assets/register')return Promise.resolve({ok:true,status:'registered',kind:'background',aa_key:'rain-night',background_analysis:{status:'labeling',queued:true,job_id:'bg-label-1'}});if(path.indexOf('/api/story/assets?')===0)return Promise.resolve({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}});return Promise.reject(new Error(path));},poll:()=>new Promise(resolve=>{finishPoll=resolve}),json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);await assets.importLocal('background',{path:'C:/private/rain.png',name:'rain.png',displayName:'雨夜候车厅'});const labeling={state:assets.tasks[0].state,text:root.textContent};finishPoll({state:'failed',error:'vision unavailable'});await Promise.resolve();await Promise.resolve();await Promise.resolve();console.log(JSON.stringify({labeling,final:{state:assets.tasks[0].state,code:assets.tasks[0].code,text:root.textContent},payload:requests.find(x=>x.path==='/api/assets/register').opts.payload}));})();
'''
    result = run_assets(script)
    assert result["labeling"]["state"] == "labeling"
    assert "正在识别背景场景" in result["labeling"]["text"]
    assert result["final"]["state"] == "available"
    assert result["final"]["code"] == "background_label_failed"
    assert "背景已登记，AI 标注失败，可在素材工作台补充" in result["final"]["text"]
    assert result["payload"]["display_name"] == "雨夜候车厅"


def test_character_import_modal_is_csp_safe_and_collects_required_fields():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    assert 'id="mAssetCharacter"' in html
    assert 'id="assetCharacterIdentifier"' in html
    assert 'id="assetCharacterDisplayName"' in html
    assert 'id="assetCharacterPath"' in html
    assert "角色标识" in html
    assert "角色 Identifier" not in html
    assert "onclick=" not in html


def test_asset_import_actions_follow_active_type_filter_without_duplicate_selector():
    """The type tabs are the sole import-kind control."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const opened=[];
function node(){let own='';const classes=new Set(),events={};return {children:[],dataset:{},className:'',type:'',value:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},addEventListener(t,f){events[t]=f},click(){if(events.click)events.click({target:this})},setAttribute(k,v){this[k]=String(v)},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),story={story_token:'story-a',project:'A'};const window={Api:{},HistoryDrawer:{open:context=>opened.push(context.kind)},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});const assets=new window.StoryUI.StoryAssetStrip(root);assets.render();let controls=root.children[1];const allHasSelector=Boolean(controls.children.find(x=>String(x.className).includes('asset-import-kind')));const allHasHistory=Boolean(controls.children.find(x=>String(x.className).includes('asset-import-history')));controls.children.filter(x=>String(x.className).includes('asset-filter'))[2].click();controls=root.children[1];const history=controls.children.find(x=>String(x.className).includes('asset-import-history'));history.click();console.log(JSON.stringify({title:root.children[0].textContent,allHasSelector,allHasHistory,label:history.textContent,opened}));
'''
    result = run_assets(script)
    assert result == {
        "title": "本剧情自定义素材角色 0 · 背景 0 · 音效 0 · BGM 0",
        "allHasSelector": False,
        "allHasHistory": False,
        "label": "从历史导入背景",
        "opened": ["background"],
    }


def test_asset_cards_translate_internal_status_values():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(){let own='';return {children:[],dataset:{},className:'',classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),story={story_token:'story-a'};const window={Api:{},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});const assets=new window.StoryUI.StoryAssetStrip(root);assets.items={characters:[{name:'凯伊',status:'registered',expression_status:'known',faces:[{id:'00'}]}],backgrounds:[],sounds:[],bgms:[],counts:{characters:1}};assets.render();console.log(JSON.stringify({text:root.textContent}));
'''
    text = run_assets(script)["text"]
    assert "已识别表情编号" in text
    assert "已登记" in text
    assert "known" not in text
    assert "registered" not in text


def test_task_session_never_persists_source_path_and_detached_notice_stays_visible():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');let saved='';
function node(){let own='';const classes=new Set();return {children:[],dataset:{},classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:async()=>({}),json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>null,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(k,v){saved=v},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});const assets=new window.StoryUI.StoryAssetStrip(root);assets.beginTask({kind:'background',storyToken:'story-a',name:'night.png',source:'C:/private/night.png'});assets.clear();console.log(JSON.stringify({saved,text:root.textContent,empty:root.classList.contains('is-empty')}));
'''
    result = run_assets(script)
    assert "C:/private/night.png" not in result["saved"]
    assert result["empty"] is False
    assert "原剧情" in result["text"]


def test_successful_registration_stays_available_when_catalog_refresh_fails():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const story={story_token:'story-a',project:'A'};let calls=0;
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:(path)=>{calls++;if(path==='/api/picker')return Promise.resolve({file_token:'token'});if(path==='/api/assets/validate')return Promise.resolve({ok:true});if(path==='/api/assets/register')return Promise.resolve({ok:true,status:'registered'});return Promise.reject(Object.assign(new Error('offline'),{status:503}))},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node};
vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);await assets.importLocal('background',{path:'C:/private/night.png'});console.log(JSON.stringify({state:assets.tasks[0].state,code:assets.tasks[0].code,message:assets.tasks[0].message,text:root.textContent,calls}));})();
'''
    result = run_assets(script)
    assert result["state"] == "available"
    assert result["code"] == "refresh_failed"
    assert "已登记" in result["message"]


def test_successful_local_import_dispatches_path_free_workbench_identity():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const events=[];const story={story_token:'story-a',project:'A'};
function node(){let own='';return {children:[],dataset:{},classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),window={Api:{request:(path)=>{if(path==='/api/assets/validate')return Promise.resolve({ok:true,kind:'sound',aa_key:'door',sha256:'digest'});if(path==='/api/assets/register')return Promise.resolve({ok:true,status:'registered',kind:'sound',aa_key:'door',sha256:'digest'});if(path.startsWith('/api/story/assets?'))return Promise.resolve({characters:[],backgrounds:[],sounds:[],bgms:[],counts:{}});return Promise.reject(new Error(path));},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},dispatchEvent:event=>events.push({type:event.type,detail:event.detail})};
const document={createElement:node,createDocumentFragment:node};const CustomEvent=function(type,options){this.type=type;this.detail=options.detail};
vm.runInNewContext(source,{window,document,CustomEvent,encodeURIComponent,Promise,Error,console});
(async()=>{const assets=new window.StoryUI.StoryAssetStrip(root);await assets.importLocal('sound',{fileToken:'ft-sound',name:'door.wav',path:'C:/must-not-leak/door.wav'});console.log(JSON.stringify({events}));})();
'''
    result = run_assets(script)

    assert result["events"] == [{
        "type": "storyassets:imported",
        "detail": {
            "identity": {"kind": "sound", "aa_key": "door", "sha256": "digest"},
            "story_token": "story-a",
        },
    }]
    assert "must-not-leak" not in json.dumps(result)


def test_character_modal_restores_trigger_clears_fields_and_never_double_binds():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');let submit=0,key;const nodes={};function n(){const c=new Set(),ls={};return {value:'',dataset:{},classList:{add:x=>c.add(x),remove:x=>c.delete(x),toggle:(x,v)=>v?c.add(x):c.delete(x),contains:x=>c.has(x)},addEventListener:(k,f)=>ls[k]=f,fire:k=>ls[k]&&ls[k](),setAttribute(k,v){this[k]=v},focus(){this.focused=true},children:[],appendChild(x){this.children.push(x)},set textContent(v){this._t=v;this.children=[]},get textContent(){return this._t||''}}}['mAssetCharacter','assetCharacterIdentifier','assetCharacterDisplayName','assetCharacterPath','assetCharacterError','assetCharacterCancel','assetCharacterCancelSecondary','assetCharacterConfirm'].forEach(id=>nodes[id]=n());const trigger=n(),root=n(),story={story_token:'s'};const window={Api:{},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:n,createDocumentFragment:n,getElementById:id=>nodes[id],addEventListener:(k,f)=>{if(k==='keydown')key=f},activeElement:trigger};vm.runInNewContext(source,{window,document,encodeURIComponent,Promise,Error,console});const a=new window.StoryUI.StoryAssetStrip(root);a.importLocal=()=>submit++;const b=new window.StoryUI.StoryAssetStrip(root);a.openCharacterForm();nodes.assetCharacterConfirm.fire('click');const invalid=nodes.assetCharacterIdentifier['aria-invalid'];nodes.assetCharacterIdentifier.value='id';nodes.assetCharacterDisplayName.value='name';nodes.assetCharacterPath.value='path';key({key:'Escape'});console.log(JSON.stringify({focused:nodes.assetCharacterIdentifier.focused,invalid,closed:!nodes.mAssetCharacter.classList.contains('on'),restored:trigger.focused,cleared:[nodes.assetCharacterIdentifier.value,nodes.assetCharacterDisplayName.value,nodes.assetCharacterPath.value],submit}));
'''
    result = run_assets(script)
    assert result == {"focused": True, "invalid": "true", "closed": True, "restored": True, "cleared": ["", "", ""], "submit": 0}


def test_tasks_are_bounded_scrubbed_and_clear_releases_audio_previews():
    script = r'''
const fs=require('fs'),vm=require('vm'),s=fs.readFileSync(process.argv[1],'utf8');let paused=0,removed=0,loaded=0;function n(tag){const c=new Set();return {tagName:tag,children:[],dataset:{},classList:{add:x=>c.add(x),remove:x=>c.delete(x),toggle:(x,v)=>v?c.add(x):c.delete(x)},appendChild(x){this.children.push(x);return x},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){this.children=[]},pause(){paused++},removeAttribute(){removed++},load(){loaded++}}}const root=n('div'),story={story_token:'s'};const window={Api:{},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(k,v){this.saved=v},removeItem(){}}},document={createElement:n,createDocumentFragment:()=>n('f'),querySelectorAll:()=>[n('audio'),n('audio')]};vm.runInNewContext(s,{window,document,encodeURIComponent,Promise,Error,console});const a=new window.StoryUI.StoryAssetStrip(root);for(let i=0;i<100;i++){let t=a.beginTask({kind:'sound',name:'x',source:'C:/secret/'+i});a.updateTask(t.id,{state:'available',fileToken:'token',jobId:'job'})}a.clear();console.log(JSON.stringify({count:a.tasks.length,clean:a.tasks.every(x=>!x.source&&!x.fileToken&&!x.jobId),saved:window.sessionStorage.saved,paused,removed,loaded}));
'''
    result = run_assets(script)
    assert result["count"] <= 30 and result["clean"] is True
    assert "C:/secret" not in result["saved"]
    assert result["paused"] == result["removed"] == result["loaded"] > 0


def test_render_releases_existing_audio_and_refuses_the_31st_active_task():
    script = r'''
const fs=require('fs'),vm=require('vm'),s=fs.readFileSync(process.argv[1],'utf8');let p=0,r=0,l=0;function n(){const c=new Set();return {children:[],dataset:{},classList:{add:x=>c.add(x),remove:x=>c.delete(x),toggle:(x,v)=>v?c.add(x):c.delete(x)},appendChild(x){this.children.push(x);return x},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},set textContent(v){this.children=[]},pause(){p++},removeAttribute(){r++},load(){l++}}}const root=n(),story={story_token:'s'};root.querySelectorAll=()=>[n()];const window={Api:{},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:n,createDocumentFragment:n,querySelectorAll:()=>[]};vm.runInNewContext(s,{window,document,encodeURIComponent,Promise,Error,console});const a=new window.StoryUI.StoryAssetStrip(root);for(let i=0;i<30;i++)a.beginTask({kind:'sound',name:'x',storyToken:'s'});let err='';try{a.beginTask({kind:'sound',name:'31',storyToken:'s'})}catch(e){err=e.code}a.render();console.log(JSON.stringify({count:a.tasks.length,first:a.tasks[0].name,err,p,r,l}));
'''
    result = run_assets(script)
    assert result["count"] == 30 and result["first"] == "x" and result["err"] == "too_many_active_tasks"
    assert result["p"] == result["r"] == result["l"] > 0


def test_history_drawer_copies_only_current_kind_and_returns_to_its_trigger():
    """A history copy is a current-story task, never a BGM/link or cross-story write."""
    script = r'''
const fs=require('fs'),vm=require('vm'),asset=fs.readFileSync(process.argv[1],'utf8'),history=fs.readFileSync(process.argv[2],'utf8');let story={story_token:'story-a',project:'A'},requests=[],applied=0;
function node(){let own='',cls=new Set();return {children:[],dataset:{},className:'',disabled:false,hidden:false,classList:{add:x=>cls.add(x),remove:x=>cls.delete(x),toggle:(x,v)=>v?cls.add(x):cls.delete(x),contains:x=>cls.has(x)},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},focus(){this.focused=true},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),drawerNode=node(),events=[];const window={Api:{request:(path,opts)=>{requests.push({path,opts});if(path==='/api/history/projects')return Promise.resolve([{history_token:'history-1',project:'旧剧情'}]);if(path.indexOf('/api/history/assets?')===0)return Promise.resolve([{history_asset_token:'asset-bg',kind:'background',name:'雨夜',aa_key:'rain',sha256:'digest'},{history_asset_token:'asset-bgm',kind:'bgm',name:'不应显示'}]);if(path==='/api/story/assets/copy')return Promise.resolve({ok:true,kind:'background',name:'雨夜',aa_key:'rain',sha256:'digest'});if(path.indexOf('/api/story/assets?')===0)return Promise.resolve({characters:[],backgrounds:[{name:'雨夜'}],sounds:[],bgms:[],counts:{backgrounds:1}});return Promise.reject(new Error(path));},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},dispatchEvent:event=>events.push({type:event.type,detail:event.detail})},document={createElement:node,createDocumentFragment:node,activeElement:node(),addEventListener(){}};const CustomEvent=function(type,options){this.type=type;this.detail=options.detail};
vm.runInNewContext(asset,{window,document,encodeURIComponent,Promise,Error,console,setTimeout,CustomEvent});window.StoryAssets=new window.StoryUI.StoryAssetStrip(root);vm.runInNewContext(history,{window,document,encodeURIComponent,Promise,Error,console,setTimeout,CustomEvent});(async()=>{const drawer=new window.StoryUI.HistoryDrawer(drawerNode);await drawer.open({kind:'background',triggerCardId:'card-18',onApplied:()=>{applied++}});await drawer.copy('asset-bg');console.log(JSON.stringify({text:drawerNode.textContent,copy:requests.find(x=>x.path==='/api/story/assets/copy').opts.payload,applied,state:window.StoryAssets.tasks[0].state,events}));})();
'''
    result = run_history(script)
    assert result["copy"] == {"story_token": "story-a", "history_asset_token": "asset-bg"}
    assert result["applied"] == 1
    assert result["state"] == "available"
    assert result["events"] == [{
        "type": "storyassets:imported",
        "detail": {
            "identity": {"kind": "background", "aa_key": "rain", "sha256": "digest"},
            "story_token": "story-a",
        },
    }]
    assert "不应显示" not in result["text"]
    assert "已复制到当前剧情" in result["text"]


def test_embedded_history_browser_searches_without_rendering_a_second_close_surface():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[2],'utf8');
function node(){let own='',classes=new Set();return {children:[],dataset:{},className:'',hidden:false,disabled:false,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},appendChild(child){this.children.push(child);return child},addEventListener(){},setAttribute(){},focus(){},set textContent(value){own=String(value||'');this.children=[]},get textContent(){return own+this.children.map(child=>child.textContent||'').join('')}}}
const root=node(),window={StoryUI:{},StoryStore:{get:()=>({story_token:'story-a'}),subscribe:()=>()=>{}},Api:{}};const document={createElement:node,activeElement:node(),addEventListener(){},getElementById(){return null}};
vm.runInNewContext(source,{window,document,console,encodeURIComponent,Promise,Error});
const drawer=new window.StoryUI.HistoryDrawer(root,{embedded:true});drawer.context={kind:'background'};drawer.assets=[
  {history_asset_token:'old',kind:'background',name:'门声',aa_key:'door',project:'第一章',imported_at:'2026-08-01T00:00:00Z'},
  {history_asset_token:'new',kind:'background',name:'雨夜天台',aa_key:'rain',project:'第三章',imported_at:'2026-08-07T00:00:00Z'}
];drawer.render();const before=root.textContent;const hasSearch=typeof drawer.setSearchQuery==='function';if(hasSearch)drawer.setSearchQuery('雨夜');const after=root.textContent;
console.log(JSON.stringify({before,after,hasSearch}));
'''
    result = run_history(script)

    assert result["hasSearch"] is True
    assert "关闭" not in result["before"]
    assert result["before"].index("雨夜天台") < result["before"].index("门声")
    assert "雨夜天台" in result["after"]
    assert "门声" not in result["after"]


def test_history_missing_source_uses_local_picker_after_closing_the_drawer():
    """A native picker cannot be used while its source-missing history drawer covers it."""
    script = r'''
const fs=require('fs'),vm=require('vm'),asset=fs.readFileSync(process.argv[1],'utf8'),history=fs.readFileSync(process.argv[2],'utf8');const story={story_token:'story-a'};function node(){const c=new Set();return {children:[],dataset:{},hidden:false,classList:{add:x=>c.add(x),remove:x=>c.delete(x),toggle:(x,v)=>v?c.add(x):c.delete(x),contains:x=>c.has(x)},appendChild(x){this.children.push(x);return x},set textContent(v){this.children=[]},addEventListener(){},setAttribute(){},focus(){this.focused=true}}}const root=node(),drawerNode=node();let picked=null;const window={Api:{request:async()=>[]},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node,activeElement:node(),addEventListener(){}};vm.runInNewContext(asset,{window,document,encodeURIComponent,Promise,Error,console,setTimeout});window.StoryAssets=new window.StoryUI.StoryAssetStrip(root);window.StoryAssets.importLocal=(kind,context)=>{picked={kind,context};};vm.runInNewContext(history,{window,document,encodeURIComponent,Promise,Error,console,setTimeout});(async()=>{const drawer=new window.StoryUI.HistoryDrawer(drawerNode);await drawer.open({kind:'background',triggerCardId:'missing-1'});drawer.replaceLocal();console.log(JSON.stringify({closed:!drawerNode.classList.contains('on'),picked}));})();
'''
    result = run_history(script)
    assert result == {"closed": True, "picked": {"kind": "background", "context": {"triggerCardId": "missing-1"}}}


def test_history_drawer_with_draft_context_resolves_the_background_card():
    """A history copy launched from a missing background card backfills that card's draft request."""
    script = r'''
const fs=require('fs'),vm=require('vm'),asset=fs.readFileSync(process.argv[1],'utf8'),history=fs.readFileSync(process.argv[2],'utf8');let story={story_token:'story-a',project:'A'},requests=[],applied=0;
function node(){let own='',cls=new Set();return {children:[],dataset:{},className:'',disabled:false,hidden:false,classList:{add:x=>cls.add(x),remove:x=>cls.delete(x),toggle:(x,v)=>v?cls.add(x):cls.delete(x),contains:x=>cls.has(x)},appendChild(x){this.children.push(x);return x},append(){Array.from(arguments).forEach(x=>this.appendChild(x))},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},focus(){this.focused=true},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own+this.children.map(x=>x.textContent||'').join('')}}}
const root=node(),drawerNode=node();const window={Api:{request:(path,opts)=>{requests.push({path,opts});if(path==='/api/history/projects')return Promise.resolve([{history_token:'history-1',project:'旧剧情'}]);if(path.indexOf('/api/history/assets?')===0)return Promise.resolve([{history_asset_token:'asset-bg',kind:'background',name:'雨夜',aa_key:'rain'}]);if(path==='/api/story/assets/copy')return Promise.resolve({ok:true,kind:'background',name:'雨夜',aa_key:'rain'});if(path.indexOf('/api/story/assets?')===0)return Promise.resolve({characters:[],backgrounds:[{name:'雨夜'}],sounds:[],bgms:[],counts:{backgrounds:1}});if(path.indexOf('/resolve')>=0)return Promise.resolve({ok:true,draft_version:4,content_revision:2});return Promise.reject(new Error(path));},json:(m,p)=>({method:m,payload:p})},StoryStore:{get:()=>story,subscribe:()=>()=>{}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}}},document={createElement:node,createDocumentFragment:node,activeElement:node(),addEventListener(){}};
vm.runInNewContext(asset,{window,document,encodeURIComponent,Promise,Error,console,setTimeout});window.StoryAssets=new window.StoryUI.StoryAssetStrip(root);vm.runInNewContext(history,{window,document,encodeURIComponent,Promise,Error,console,setTimeout});(async()=>{const drawer=new window.StoryUI.HistoryDrawer(drawerNode);await drawer.open({kind:'background',triggerCardId:'card-18',draftToken:'draft-tok-1',requestId:'card-18',draftVersion:3,onApplied:()=>{applied++}});await drawer.copy('asset-bg');const resolve=requests.find(x=>x.path==='/api/drafts/draft-tok-1/backgrounds/card-18/resolve');console.log(JSON.stringify({applied,resolve:resolve&&resolve.opts.payload,state:window.StoryAssets.tasks[0].state}));})();
'''
    result = run_history(script)
    assert result["applied"] == 1
    assert result["resolve"] == {"bg_name": "rain", "expected_draft_version": 3}
    assert result["state"] == "available"


def test_background_request_card_offers_default_official_and_history_actions():
    """A missing background card exposes every existing resolution path in place."""
    script = r'''
const fs=require('fs'),vm=require('vm'),cards=fs.readFileSync(process.argv[1],'utf8');
function node(tag){const ch=[],cls=new Set();return {children:ch,dataset:{},className:'',tagName:(tag||'div').toUpperCase(),hidden:false,_txt:'',classList:{add:x=>cls.add(x),remove:x=>cls.delete(x),toggle:(x,v)=>v?cls.add(x):cls.delete(x),contains:x=>cls.has(x)},appendChild(x){ch.push(x);return x},append(){Array.from(arguments).forEach(x=>ch.push(x))},addEventListener(type,fn){this._onClick=fn},set textContent(v){this._txt=String(v||'');ch.length=0},get textContent(){return this._txt+ch.map(x=>x.textContent||'').join('')}}}
const window={},document={createElement:node,createDocumentFragment:function(){return node('fragment')}};
vm.runInNewContext(cards,{window,document,console});
const card={card_id:'card-18',kind:'background_request',line_no:12,review_state:'pending',current:{description:'雨夜车站'}};
let selected=null,usedDefault=null,chosen=null,filled=null;
const el=window.CardList.createCardElement(card,{onSelectCard:c=>selected=c.card_id,onUseDefaultBackground:c=>usedDefault=c.card_id,onChooseBackground:c=>chosen=c.card_id,onFillBackground:c=>filled=c.card_id});
const buttons={};function walk(n){if(n.tagName==='BUTTON')buttons[n._txt]=n;(n.children||[]).forEach(walk)}walk(el);
['使用默认黑屏','选择官方背景','从历史项目复制'].forEach(label=>buttons[label]._onClick({stopPropagation(){}}));
console.log(JSON.stringify({usedDefault,chosen,filled,selected,labels:Object.keys(buttons),text:el.textContent}));
'''
    result = run_cards(script)
    assert result["usedDefault"] == "card-18"
    assert result["chosen"] == "card-18"
    assert result["filled"] == "card-18"
    assert result["selected"] is None
    assert result["labels"] == ["使用默认黑屏", "选择官方背景", "从历史项目复制"]


def test_separator_card_renders_as_scene_divider_instead_of_raw_marker():
    script = r'''
const fs=require('fs'),vm=require('vm'),cards=fs.readFileSync(process.argv[1],'utf8');
function node(tag){const ch=[],cls=new Set();return {children:ch,dataset:{},className:'',tagName:(tag||'div').toUpperCase(),_txt:'',classList:{add:x=>cls.add(x),remove:x=>cls.delete(x),toggle:(x,v)=>v?cls.add(x):cls.delete(x),contains:x=>cls.has(x)},appendChild(x){ch.push(x);return x},addEventListener(){},set textContent(v){this._txt=String(v||'');ch.length=0},get textContent(){return this._txt+ch.map(x=>x.textContent||'').join('')}}}
const window={},document={createElement:node,createDocumentFragment:function(){return node('fragment')}};
vm.runInNewContext(cards,{window,document,console});
const card={card_id:'separator-1',kind:'separator',line_no:3,review_state:'approved',raw:'---\n',current:{marker:'---'}};
const el=window.CardList.createCardElement(card,{});
console.log(JSON.stringify({text:el.textContent,className:el.className}));
'''
    result = run_cards(script)
    assert "场景分隔" in result["text"]
    assert "---" not in result["text"]
    assert "card-kind-separator" in result["className"]
