from __future__ import annotations

import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[2] / "main" / "python"


def test_android_native_picker_claims_token_through_existing_select_api():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){this.focused=true},querySelector(){return null},set textContent(v){this.children=[]}}}
const nodes={};['storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp','browseTitle'].forEach(id=>nodes[id]=n());
const calls=[],chosen=[],nativeCalls=[];
const window={Api:{json:(method,payload)=>({method,payload}),request:async(path,options)=>{calls.push({path,options});return {ok:true,file_token:'ft-native',name:'picked.txt',size:12}}},StoryUI:{},HaloCueNative:{pickDocument:(requestId,purpose,suffixes)=>nativeCalls.push({requestId,purpose,suffixes})}};
const document={getElementById:id=>nodes[id],createElement:n,activeElement:n()};
vm.runInNewContext(source,{window,document,URLSearchParams,Promise,Error,console,setTimeout});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(n(),{allowedSuffixes:['.txt','.md'],onChoose:value=>chosen.push(value)});const pending=picker.open();const requestId=nativeCalls[0].requestId;window.HaloCueAndroid.documentPicked({requestId,ok:true,token:'a'.repeat(32),name:'picked.txt',size:12});await pending;await new Promise(resolve=>setTimeout(resolve,0));console.log(JSON.stringify({nativeCalls,calls,chosen}));})();
"""
    completed = subprocess.run(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result["nativeCalls"][0]["purpose"] == "story"
    assert json.loads(result["nativeCalls"][0]["suffixes"]) == [".txt", ".md"]
    assert result["calls"] == [
        {
            "path": "/api/story-files/select",
            "options": {
                "method": "POST",
                "payload": {"incoming_token": "a" * 32},
            },
        }
    ]
    assert result["chosen"] == [
        {"file_token": "ft-native", "name": "picked.txt", "size": 12}
    ]


def test_browser_picker_keeps_existing_host_and_select_flow():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){},querySelector(){return null},set textContent(v){this.children=[]}}}
const nodes={};['storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp','browseTitle'].forEach(id=>nodes[id]=n());
const calls=[],chosen=[],listing={entries:[],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
const window={Api:{json:(method,payload)=>({method,payload}),request:async(path,options)=>{calls.push({path,options});return path.startsWith('/api/story-files/host')?listing:{ok:true,file_token:'ft-host',name:'host.txt',size:4}}},StoryUI:{}};
const document={getElementById:id=>nodes[id],createElement:n,activeElement:n()};
vm.runInNewContext(source,{window,document,URLSearchParams,Promise,Error,console});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(n(),{onChoose:value=>chosen.push(value)});await picker.open();picker.selected={entry_token:'entry-host',name:'host.txt',kind:'file',size:4};await picker.confirm();console.log(JSON.stringify({calls,chosen}));})();
"""
    completed = subprocess.run(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result["calls"][0]["path"].startswith("/api/story-files/host?")
    assert result["calls"][1] == {
        "path": "/api/story-files/select",
        "options": {"method": "POST", "payload": {"entry_token": "entry-host"}},
    }
    assert result["chosen"] == [
        {"file_token": "ft-host", "name": "host.txt", "size": 4}
    ]


def test_recreated_page_recovers_one_unmatched_native_result_only_once():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){},querySelector(){return null},set textContent(v){this.children=[]}}}
const nodes={};['storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp','browseTitle'].forEach(id=>nodes[id]=n());
const calls=[],chosen=[];
const window={Api:{json:(method,payload)=>({method,payload}),request:async(path,options)=>{calls.push({path,options});return {ok:true,file_token:'ft-recovered',name:'recovered.txt',size:9}}},StoryUI:{},HaloCueNative:{pickDocument(){}}};
const document={getElementById:id=>nodes[id],createElement:n,activeElement:n()};
vm.runInNewContext(source,{window,document,URLSearchParams,Promise,Error,console,setTimeout});
(async()=>{new window.StoryUI.StoryFilePicker(n(),{onChoose:value=>chosen.push(value)});const payload={requestId:'before-recreate',ok:true,token:'b'.repeat(32),name:'recovered.txt',size:9};window.HaloCueAndroid.documentPicked(payload);window.HaloCueAndroid.documentPicked(payload);await new Promise(resolve=>setTimeout(resolve,0));console.log(JSON.stringify({calls,chosen}));})();
"""
    completed = subprocess.run(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert len(result["calls"]) == 1
    assert result["calls"][0]["options"]["payload"] == {"incoming_token": "b" * 32}
    assert result["chosen"] == [
        {"file_token": "ft-recovered", "name": "recovered.txt", "size": 9}
    ]


def test_native_picker_cancellation_is_acknowledged_without_select_request():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){},querySelector(){return null},set textContent(v){this.children=[]}}}
const nodes={};['storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp','browseTitle'].forEach(id=>nodes[id]=n());
const calls=[],acks=[],nativeCalls=[];
const window={Api:{request:async(path,options)=>{calls.push({path,options})},json:(method,payload)=>({method,payload})},StoryUI:{},HaloCueNative:{pickDocument:(requestId)=>nativeCalls.push(requestId),ackDocumentResult:(requestId,claimed)=>acks.push({requestId,claimed})}};
const document={getElementById:id=>nodes[id],createElement:n,activeElement:n()};
vm.runInNewContext(source,{window,document,URLSearchParams,Promise,Error,console,setTimeout});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(n(),{onChoose(){}});const pending=picker.open();const payload={requestId:nativeCalls[0],ok:false,code:'cancelled'};window.HaloCueAndroid.documentPicked(payload);window.HaloCueAndroid.documentPicked(payload);await pending;await new Promise(resolve=>setTimeout(resolve,0));console.log(JSON.stringify({calls,acks}));})();
"""
    completed = subprocess.run(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert result["calls"] == []
    assert len(result["acks"]) == 1
    assert result["acks"][0]["requestId"].startswith("story-")
    assert result["acks"][0]["claimed"] is False


def test_native_picker_acknowledges_server_claim_when_ui_callback_fails():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){},querySelector(){return null},set textContent(v){this.children=[]}}}
const nodes={};['storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp','browseTitle'].forEach(id=>nodes[id]=n());
const acks=[],nativeCalls=[];
const window={Api:{json:(method,payload)=>({method,payload}),request:async()=>({ok:true,file_token:'ft-claimed',name:'picked.txt',size:12})},StoryUI:{},HaloCueNative:{pickDocument:(requestId)=>nativeCalls.push(requestId),ackDocumentResult:(requestId,claimed)=>acks.push({requestId,claimed})}};
const document={getElementById:id=>nodes[id],createElement:n,activeElement:n()};
vm.runInNewContext(source,{window,document,URLSearchParams,Promise,Error,console,setTimeout});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(n(),{onChoose:async()=>{throw new Error('render failed')}});const pending=picker.open();window.HaloCueAndroid.documentPicked({requestId:nativeCalls[0],ok:true,token:'c'.repeat(32),name:'picked.txt',size:12});await pending;await new Promise(resolve=>setTimeout(resolve,0));console.log(JSON.stringify({acks}));})();
"""
    completed = subprocess.run(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)

    assert len(result["acks"]) == 1
    assert result["acks"][0]["claimed"] is True
