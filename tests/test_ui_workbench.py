import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
HTML = (HERE / "ui.html").read_text(encoding="utf-8")


def test_workbench_keeps_review_and_settings_contracts_after_runtime_extraction():
    for element_id in (
        "view-create", "modelSettings", "settingsDrawer",
        "helpDrawer", "welcomePanel", "s1", "s2", "s3", "s4", "go",
        "rvDraftSelect", "rvCards", "backgroundRequestsPanel",
    ):
        assert f'id="{element_id}"' in HTML


def test_asset_entry_is_story_scoped_and_not_a_standalone_workspace():
    assert 'id="storyAssetStrip"' in HTML
    assert 'id="storyContextBar"' in HTML
    assert 'id="view-assets"' not in HTML
    assert '<script src="/js/assets.js"></script>' in HTML


def test_help_and_setup_remain_available_from_the_workbench():
    assert 'aria-controls="helpDrawer"' in HTML
    assert 'id="readyAA"' in HTML
    assert 'id="readyDatabase"' in HTML
    assert 'id="readyModel"' in HTML


def test_settings_explain_install_workspace_resource_and_preview_separately():
    for element_id in (
        "aaInstallInput", "aaProgramState", "aaProjectsState", "aaSavesState",
        "aaResourceState", "aaPreviewState", "aaIndexProgress", "buildAAIndex",
    ):
        assert f'id="{element_id}"' in HTML
    assert "AA 数据目录（内含 projects / overrides）" not in HTML
    assert "选择 AA 程序或安装目录" in HTML


def test_aa_status_renderer_keeps_resource_and_preview_states_distinct():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const nodes={},listeners={};
function node(){const classes=new Set();return {value:'',max:0,disabled:false,hidden:false,textContent:'',dataset:{},children:[],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},closest(){return this},insertRow(){return node()},insertCell(){return node()}}}
function $(s){return nodes[s]||(nodes[s]=node())}
['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#mBrowse','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum','#aaInstallInput','#aaProgramState','#aaProjectsState','#aaSavesState','#aaResourceState','#aaPreviewState','#aaIndexProgress','#buildAAIndex','#aaInstallStatus','#aaWorkspaceConflict','#aaWorkspaceCandidates','#aaWorkspaceConfirm'].forEach($);$('input[name=anno]:checked').value='no';
const window={Api:{request:async()=>({profiles:[]}),json:()=>({})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};
const body=node();const document={body,documentElement:node(),querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};
vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},console});
window.AppRuntime.renderAAStatus({resource:{status:'installed'},preview_index:{status:'not_built'}});
const installed={resource:nodes['#aaResourceState'].textContent,preview:nodes['#aaPreviewState'].textContent,enabled:!nodes['#buildAAIndex'].disabled};
window.AppRuntime.renderAAStatus({resource:{status:'not_installed'},preview_index:{status:'not_built'}});
const missing={resource:nodes['#aaResourceState'].textContent,enabled:!nodes['#buildAAIndex'].disabled};
window.AppRuntime.renderAAStatus({resource:{status:'installed'},preview_index:{status:'building',current:31,total:1554}});
const building={preview:nodes['#aaPreviewState'].textContent,value:nodes['#aaIndexProgress'].value,max:nodes['#aaIndexProgress'].max,enabled:!nodes['#buildAAIndex'].disabled};
console.log(JSON.stringify({installed,missing,building}));
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert "资源包已安装" in result["installed"]["resource"]
    assert "尚未建立图片预览" in result["installed"]["preview"]
    assert result["installed"]["enabled"] is True
    assert "尚未安装 AA 资源包" in result["missing"]["resource"]
    assert result["missing"]["enabled"] is False
    assert "正在建立图片预览" in result["building"]["preview"]
    assert result["building"]["value"] == 31
    assert result["building"]["max"] == 1554
    assert result["building"]["enabled"] is False


def test_workbench_has_no_fixed_sidebar_and_keeps_topbar_drawer_controls():
    assert 'class="sidebar"' not in HTML
    assert 'id="workspaceNav"' not in HTML
    assert 'class="workspace-nav"' not in HTML
    assert 'id="topbarActions"' in HTML
    assert 'data-action="open-settings"' in HTML
    assert 'data-action="open-help"' in HTML
    assert HTML.index('id="storyContextBar"') < HTML.index('id="storyAssetStrip"') < HTML.index('id="reviewWorkspace"')


def test_topbar_settings_and_help_actions_open_the_existing_drawers():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={},listeners={};
function node(){const classes=new Set();return {value:'',checked:false,disabled:false,textContent:'',dataset:{},children:[],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},closest(){return this},insertRow(){return node()},insertCell(){return node()}}}
function $(s){return nodes[s]||(nodes[s]=node())}['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum'].forEach($);$('input[name=anno]:checked').value='no';
const window={Api:{request:async()=>({profiles:[]}),json:()=>({})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};const body=node();const document={body,querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},console});function click(action){const target=node();target.dataset.action=action;listeners.click({target})}click('open-settings');const settingsLocked=body.classList.contains('drawer-open');click('open-help');const bothLocked=body.classList.contains('drawer-open');click('close-settings');click('close-help');const restored=!body.classList.contains('drawer-open');console.log(JSON.stringify({settings:$('#settingsDrawer').classList.contains('open'),help:$('#helpDrawer').classList.contains('open'),settingsAria:$('#settingsDrawer')['aria-hidden'],helpAria:$('#helpDrawer')['aria-hidden'],settingsLocked,bothLocked,restored}));
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result == {
        "settings": False,
        "help": False,
        "settingsAria": "true",
        "helpAria": "true",
        "settingsLocked": True,
        "bothLocked": True,
        "restored": True,
    }


def test_aa_install_picker_saves_files_and_directories_then_reclaims_shared_modal():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={},listeners={},requests=[];
function node(){const classes=new Set();return {value:'',checked:false,disabled:false,hidden:false,textContent:'',dataset:{},children:[],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},closest(sel){return sel==='[data-story-sort]'?null:this},insertRow(){return node()},insertCell(){return node()},scrollIntoView(){}}}
function $(s){return nodes[s]||(nodes[s]=node())}
['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#mBrowse','#browseTitle','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum','#aaInstallInput','#aaProgramState','#aaProjectsState','#aaSavesState','#aaResourceState','#aaPreviewState','#aaIndexProgress','#buildAAIndex','#aaInstallStatus','#aaWorkspaceConflict','#aaWorkspaceCandidates','#aaWorkspaceConfirm'].forEach($);$('input[name=anno]:checked').value='no';
const pickers=[];function Picker(root,options){this.options=options;this.openCalls=0;this.openPathCalls=0;this.hostCalls=0;this.closeCalls=0;pickers.push(this)}
Picker.prototype.open=function(){this.openCalls++};Picker.prototype.openHost=function(){this.hostCalls++};Picker.prototype.openDirectory=function(){};Picker.prototype.openPath=function(){this.openPathCalls++};Picker.prototype.close=function(){this.closeCalls++};Picker.prototype.chooseDevice=function(){};Picker.prototype.load=function(){};Picker.prototype.sortBy=function(){};
const aa={program:{status:'recognized',path:'E:/AzureArchive/App/AzureArchive.exe'},projects:{status:'ready',path:'E:/AzureArchive/data/projects'},saves:{status:'ready',path:'E:/AzureArchive/data/saves'},resource:{status:'installed'},preview_index:{status:'not_built'}};
const window={Api:{request:async(path,options)=>{requests.push({path,payload:options&&options.payload});return path==='/api/settings/aa-install'?{ok:true,restart_required:true,aa}:{ok:true}},json:(method,payload)=>({method,payload})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}},StoryFilePicker:Picker},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};const body=node();const document={body,documentElement:node(),querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},console});
function click(action){const target=node();target.dataset.action=action;listeners.click({target})}
(async()=>{click('browse-aa-install');await pickers[1].options.onChoose({entry_token:'exe-1',kind:'file',name:'AzureArchive.exe'});click('browse-aa-install');await pickers[1].options.onChoose({entry_token:'dir-1',kind:'directory',name:'AzureArchive'});pickers[1].close();click('open-script');click('story-picker-host');console.log(JSON.stringify({aaRequests:requests.filter(x=>x.path==='/api/settings/aa-install'),message:nodes['#aaInstallStatus'].textContent,openPath:pickers[1].openPathCalls,storyOpen:pickers[0].openCalls,storyHost:pickers[0].hostCalls,settingsHost:pickers[1].hostCalls}));})();
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result["aaRequests"] == [
        {"path": "/api/settings/aa-install", "payload": {"entry_token": "exe-1"}},
        {"path": "/api/settings/aa-install", "payload": {"entry_token": "dir-1"}},
    ]
    assert result["message"] == "路径已保存，重启后使用新的 AA 工作区"
    assert result["openPath"] == 2
    assert result["storyOpen"] == result["storyHost"] == 1
    assert result["settingsHost"] == 0


def test_aa_workspace_conflict_waits_for_explicit_candidate_confirmation():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={},listeners={},requests=[],radios=[];
function node(tag){const classes=new Set(),events={};return {tagName:tag||'',value:'',checked:false,disabled:false,hidden:false,textContent:'',dataset:{},children:[],className:'',name:'',type:'',classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(k,f){events[k]=f},fire(k){if(events[k])events[k]({target:this})},setAttribute(k,v){this[k]=v},closest(){return this},insertRow(){return node()},insertCell(){return node()}}}
function $(s){return nodes[s]||(nodes[s]=node())}
['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum','#aaInstallInput','#aaProgramState','#aaProjectsState','#aaSavesState','#aaResourceState','#aaPreviewState','#aaIndexProgress','#buildAAIndex','#aaInstallStatus','#aaWorkspaceConflict','#aaWorkspaceCandidates','#aaWorkspaceConfirm'].forEach($);$('input[name=anno]:checked').value='no';
const candidates=[{path:'E:/AzureArchive/storage/data',source:'AA 当前设置'},{path:'D:/OldAA/data',source:'旧配置'}];
const aa={program:{status:'recognized'},projects:{status:'ready',path:candidates[1].path+'/projects'},saves:{status:'missing'},resource:{status:'installed'},preview_index:{status:'not_built'}};
const window={Api:{request:async(path,options)=>{const payload=options&&options.payload||{};requests.push({path,payload});if(path==='/api/settings/aa-install'&&!payload.aa_data)throw Object.assign(new Error('请选择工作区'),{status:409,code:'aa_workspace_selection_required',candidates});return {ok:true,restart_required:true,aa}},json:(method,payload)=>({method,payload})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};
const body=node();const document={body,documentElement:node(),querySelector:s=>s==='input[name="aa-workspace"]:checked'?(radios.find(x=>x.checked)||null):$(s),querySelectorAll:()=>[],createElement:tag=>{const x=node(tag);if(tag==='input')radios.push(x);return x},createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},console});
function click(action){const target=node();target.dataset.action=action;listeners.click({target})}
(async()=>{$('#aaInstallInput').value='E:/AzureArchive';click('save-aa-install');await new Promise(resolve=>setImmediate(resolve));const before={requests:requests.length,hidden:$('#aaWorkspaceConflict').hidden,checked:radios.map(x=>x.checked),sources:$('#aaWorkspaceCandidates').children.map(x=>x.children[2]&&x.children[2].textContent),confirmDisabled:$('#aaWorkspaceConfirm').disabled};radios[1].checked=true;radios[1].fire('change');click('confirm-aa-workspace');await new Promise(resolve=>setImmediate(resolve));console.log(JSON.stringify({before,requests,message:$('#aaInstallStatus').textContent}));})();
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result["before"] == {
        "requests": 1,
        "hidden": False,
        "checked": [False, False],
        "sources": ["来源：AA 当前设置", "来源：旧配置"],
        "confirmDisabled": True,
    }
    assert result["requests"][1] == {
        "path": "/api/settings/aa-install",
        "payload": {
            "aa_install": "E:/AzureArchive",
            "aa_data": "D:/OldAA/data",
        },
    }
    assert result["message"] == "路径已保存，重启后使用新的 AA 工作区"


def test_aa_index_starts_once_polls_each_second_and_stops_when_ready_or_closed():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={},listeners={},requests=[],timers=[];
function node(){const classes=new Set();return {value:'',max:0,disabled:false,hidden:false,textContent:'',dataset:{},children:[],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},closest(){return this},insertRow(){return node()},insertCell(){return node()}}}
function $(s){return nodes[s]||(nodes[s]=node())}
['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum','#aaInstallInput','#aaProgramState','#aaProjectsState','#aaSavesState','#aaResourceState','#aaPreviewState','#aaIndexProgress','#buildAAIndex','#aaInstallStatus','#aaWorkspaceConflict','#aaWorkspaceCandidates','#aaWorkspaceConfirm'].forEach($);$('input[name=anno]:checked').value='no';$('#settingsDrawer').classList.add('open');
const snapshots=[{status:'building',backgrounds:31,avatars:0,failed:0,current:31,total:1554},{status:'building',backgrounds:50,avatars:0,failed:0,current:50,total:1554},{status:'ready',backgrounds:1554,avatars:805,failed:0}];
const window={Api:{request:async(path,options)=>{requests.push({path,method:options&&options.method||'GET'});return {ok:true,preview_index:snapshots.shift()}},json:(method,payload)=>({method,payload})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};
const document={body:node(),documentElement:node(),querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout:(f,ms)=>{timers.push({f,ms});return timers.length},clearTimeout(){},console});
window.AppRuntime.renderAAStatus({program:{status:'recognized'},projects:{status:'ready'},saves:{status:'ready'},resource:{status:'installed'},preview_index:{status:'not_built'}});
(async()=>{await window.AppRuntime.buildAAIndex();const afterStart={requests:requests.slice(),delay:timers[0]&&timers[0].ms,value:$('#aaIndexProgress').value};await timers.shift().f();const secondDelay=timers[0]&&timers[0].ms;await timers.shift().f();const afterReady={requests:requests.slice(),timers:timers.length,preview:$('#aaPreviewState').textContent,disabled:$('#buildAAIndex').disabled};$('#settingsDrawer').classList.remove('open');await window.AppRuntime.pollAAIndex();console.log(JSON.stringify({afterStart,secondDelay,afterReady,afterClosed:{requests:requests.length,timers:timers.length}}));})();
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result["afterStart"] == {
        "requests": [{"path": "/api/resources/index", "method": "POST"}],
        "delay": 1000,
        "value": 31,
    }
    assert result["secondDelay"] == 1000
    assert result["afterReady"]["requests"] == [
        {"path": "/api/resources/index", "method": "POST"},
        {"path": "/api/resources/index", "method": "GET"},
        {"path": "/api/resources/index", "method": "GET"},
    ]
    assert result["afterReady"]["timers"] == 0
    assert "图片预览已就绪" in result["afterReady"]["preview"]
    assert result["afterReady"]["disabled"] is False
    assert result["afterClosed"] == {"requests": 3, "timers": 0}


def test_aa_index_poll_preserves_install_and_workspace_status_rows():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');const nodes={};
function node(){const classes=new Set();return {value:'',max:0,disabled:false,textContent:'',dataset:{},children:[],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>v?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},appendChild(x){this.children.push(x);return x},removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(k,v){this[k]=v},closest(){return this},insertRow(){return node()},insertCell(){return node()}}}
function $(s){return nodes[s]||(nodes[s]=node())}
['#settingsDrawer','#settingsBackdrop','#helpDrawer','#helpBackdrop','#recentStories','#storyContextBar','#storyAssetStrip','#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel','#cast','#s2sum','#aaInstallInput','#aaProgramState','#aaProjectsState','#aaSavesState','#aaResourceState','#aaPreviewState','#aaIndexProgress','#buildAAIndex','#aaInstallStatus','#aaWorkspaceConflict','#aaWorkspaceCandidates','#aaWorkspaceConfirm'].forEach($);$('input[name=anno]:checked').value='no';$('#settingsDrawer').classList.add('open');
const window={Api:{request:async()=>({ok:true,preview_index:{status:'ready',backgrounds:1554,avatars:805,failed:0}}),json:()=>({})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};
const document={body:node(),documentElement:node(),querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener(){}};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},clearTimeout(){},console});
window.AppRuntime.renderAAStatus({program:{status:'recognized',path:'E:/AzureArchive/App/AzureArchive.exe'},projects:{status:'ready',path:'E:/AzureArchive/storage/data/projects'},saves:{status:'ready',path:'E:/AzureArchive/storage/data/saves'},resource:{status:'installed'},preview_index:{status:'building',current:50,total:1554}});
(async()=>{await window.AppRuntime.pollAAIndex();console.log(JSON.stringify({program:$('#aaProgramState').textContent,projects:$('#aaProjectsState').textContent,saves:$('#aaSavesState').textContent}));})();
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result == {
        "program": "已识别 · E:/AzureArchive/App/AzureArchive.exe",
        "projects": "E:/AzureArchive/storage/data/projects",
        "saves": "E:/AzureArchive/storage/data/saves",
    }
