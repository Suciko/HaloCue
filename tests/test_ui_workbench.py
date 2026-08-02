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
const window={Api:{request:async()=>({profiles:[]}),json:()=>({})},StoryStore:{get:()=>null,subscribe(){}},StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},ModelSettings:{profilePayload:()=>({})},CardList:{renderCardList(){}},Player:function(){},addEventListener(){}};const document={querySelector:$,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener:(k,f)=>listeners[k]=f};vm.runInNewContext(source,{window,document,localStorage:{getItem(){},setItem(){},removeItem(){}},setTimeout(){},console});function click(action){const target=node();target.dataset.action=action;listeners.click({target})}click('open-settings');click('open-help');console.log(JSON.stringify({settings:$('#settingsDrawer').classList.contains('open'),help:$('#helpDrawer').classList.contains('open'),settingsAria:$('#settingsDrawer')['aria-hidden'],helpAria:$('#helpDrawer')['aria-hidden']}));
'''
    result = json.loads(subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")], text=True, encoding="utf-8"
    ))
    assert result == {"settings": True, "help": True, "settingsAria": "false", "helpAria": "false"}
