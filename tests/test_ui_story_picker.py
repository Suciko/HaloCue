import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def _run_picker(script: str) -> dict:
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "story_picker.js")],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def test_host_selection_returns_the_opaque_story_contract():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(tag){const listeners={};return {tagName:tag||'div',value:'',files:[],hidden:false,disabled:false,dataset:{},children:[],className:'',classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){for(const x of arguments)this.appendChild(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(k,f){listeners[k]=f},fire(k,e){return listeners[k]&&listeners[k](e||{target:this})},setAttribute(){},focus(){this.focused=true},click(){return this.fire('click')},set textContent(v){this._text=String(v||'');this.children=[]},get textContent(){return this._text||''}}}
const nodes={};const ids=['storyPicker','storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp'];ids.forEach(id=>nodes[id]=node());
const chosen=[],requests=[];const responses=[{entries:[{entry_token:'entry-host',name:'host.txt',kind:'file',size:5,modified:'2026-08-03T00:00:00Z',type:'文本文件'}],breadcrumbs:[],roots:[],parent_token:'',location_token:'dir-root'},{file_token:'ft-host',name:'host.txt',size:5}];
const window={Api:{request:async(p,o)=>{requests.push({p,o});return responses.shift()}},StoryUI:{}};const document={getElementById:id=>nodes[id],createElement:node,createDocumentFragment:()=>node('fragment'),activeElement:node('button'),addEventListener(){}};
vm.runInNewContext(source,{window,document,encodeURIComponent,URLSearchParams,Promise,Error,console});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(nodes.storyPicker,{onChoose:x=>chosen.push(x)});await picker.open();picker.selectEntry({entry_token:'entry-host',name:'host.txt',kind:'file',size:5});await picker.confirm();console.log(JSON.stringify({chosen,paths:requests.map(x=>x.p)}));})();
'''
    result = _run_picker(script)
    assert result["chosen"] == [
        {"file_token": "ft-host", "name": "host.txt", "size": 5},
    ]
    assert result["paths"] == [
        "/api/story-files/host?sort=name&direction=asc",
        "/api/story-files/select",
    ]


def test_picker_filters_shared_asset_listing_by_allowed_suffixes():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(tag){let own='';return {tagName:tag||'div',value:'',hidden:false,disabled:false,dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},append(){for(const x of arguments)this.appendChild(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){},set textContent(v){own=String(v||'');this.children=[]},get textContent(){return own}}}
const nodes={};['storyPicker','storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp'].forEach(id=>nodes[id]=node());
const listing={entries:[
  {entry_token:'image',name:'rain.png',kind:'file',size:1,modified:'2026-08-03T00:00:00Z',type:'PNG'},
  {entry_token:'sound',name:'door.wav',kind:'file',size:1,modified:'2026-08-03T00:00:00Z',type:'WAV'},
  {entry_token:'spine',name:'hero.skel',kind:'file',size:1,modified:'2026-08-03T00:00:00Z',type:'SKEL'},
  {entry_token:'folder',name:'assets',kind:'directory',size:0,modified:'2026-08-03T00:00:00Z',type:'文件夹'}
],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
const window={Api:{request:async()=>listing},StoryUI:{}};const document={getElementById:id=>nodes[id],createElement:node,createDocumentFragment:()=>node('fragment'),activeElement:node(),addEventListener(){}};
vm.runInNewContext(source,{window,document,encodeURIComponent,URLSearchParams,Promise,Error,console});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(nodes.storyPicker,{allowedSuffixes:['.png','.jpg','.jpeg']});await picker.open();console.log(JSON.stringify({names:nodes.storyPickerEntries.children.map(row=>row.children[1].textContent)}));})();
'''
    assert _run_picker(script)["names"] == ["rain.png", "assets"]


def test_host_navigation_search_sort_keyboard_and_stale_error_are_deterministic():
    """A stale token or navigation branch must not silently open a different host file."""
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(){const listeners={};return {value:'',hidden:false,disabled:false,dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(k,f){listeners[k]=f},fire(k,e){return listeners[k]&&listeners[k](e||{target:this,preventDefault(){}})},setAttribute(){},focus(){this.focused=true},set textContent(v){this._text=String(v||'');this.children=[]},get textContent(){return this._text||''}}}
const nodes={};['storyPicker','storyPickerDeviceInput','storyPickerSource','storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp'].forEach(id=>nodes[id]=node());let calls=[];
const listing=t=>({entries:[{entry_token:t,name:t+'.txt',kind:'file',size:1,modified:'2026-08-03T00:00:00Z',type:'文本文件'}],breadcrumbs:[],roots:[],parent_token:'up',location_token:t});
const window={Api:{request:async(p,o)=>{calls.push(p);if(p==='/api/story-files/select')throw Object.assign(new Error('文件已变化，请刷新后重试'),{code:'host_entry_changed'});return listing(p.includes('entry_token=folder')?'folder':'root')}},StoryUI:{}};const document={getElementById:id=>nodes[id],createElement:node,createDocumentFragment:node,activeElement:node(),addEventListener(){}};
vm.runInNewContext(source,{window,document,encodeURIComponent,URLSearchParams,Promise,Error,console});
(async()=>{const picker=new window.StoryUI.StoryFilePicker(nodes.storyPicker,{onChoose(){}});await picker.openHost();await picker.navigate('folder');nodes.storyPickerSearch.value='夜景';await nodes.storyPickerSearch.fire('input',{target:nodes.storyPickerSearch});await picker.sortBy('size');picker.selectEntry({entry_token:'folder',name:'night.txt',kind:'file',size:1});await picker.handleKey({key:'Enter',preventDefault(){}});console.log(JSON.stringify({calls,status:nodes.storyPickerStatus.textContent,back:picker.historyBack.length,forward:picker.historyForward.length}));})();
'''
    result = _run_picker(script)
    assert any("entry_token=folder" in call for call in result["calls"])
    assert any("query=%E5%A4%9C%E6%99%AF" in call for call in result["calls"])
    assert any("sort=size" in call for call in result["calls"])
    assert result["calls"][-1] == "/api/story-files/select"
    assert result["status"] == "文件已变化，请刷新后重试"
    assert result["back"] >= 1
    assert result["forward"] == 0


def test_picker_close_restores_focus_and_keeps_paths_out_of_browser_storage():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');function n(){return {hidden:false,disabled:false,value:'',dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x)},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},focus(){this.focused=true},set textContent(v){this.children=[]}}}const nodes={};['storyPicker','storyPickerDeviceInput','storyPickerSource','storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp'].forEach(id=>nodes[id]=n());const trigger=n(),requests=[];const listing={entries:[],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};const window={Api:{request:async path=>{requests.push(path);return listing}},StoryUI:{},localStorage:{setItem(){throw new Error('must not persist')},getItem(){throw new Error('must not read')}}};const document={getElementById:id=>nodes[id],createElement:n,createDocumentFragment:n,activeElement:trigger,addEventListener(){}};vm.runInNewContext(source,{window,document,encodeURIComponent,URLSearchParams,Promise,Error,console});(async()=>{const p=new window.StoryUI.StoryFilePicker(nodes.storyPicker,{onChoose(){}});await p.open(trigger);const hostVisible=!nodes.storyPickerHost.hidden;p.close();console.log(JSON.stringify({closed:nodes.storyPicker.hidden,restored:trigger.focused===true,hostVisible,requests}));})();
'''
    assert _run_picker(script) == {
        "closed": True,
        "restored": True,
        "hostVisible": True,
        "requests": ["/api/story-files/host?sort=name&direction=asc"],
    }


def test_settings_picker_can_choose_a_host_directory_or_any_file():
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
function node(){const listeners={};return {value:'',hidden:false,disabled:false,dataset:{},children:[],classList:{add(){},remove(){},toggle(){}},appendChild(x){this.children.push(x);return x},removeChild(){return this.children.shift()},get firstChild(){return this.children[0]},addEventListener(k,f){listeners[k]=f},fire(k,e){return listeners[k]&&listeners[k](e||{target:this})},setAttribute(){},focus(){},click(){return this.fire('click')},set textContent(v){this._text=String(v||'');this.children=[]},get textContent(){return this._text||''}}}
const nodes={};['storyPicker','storyPickerDeviceInput','storyPickerSource','storyPickerHost','storyPickerStatus','storyPickerEntries','storyPickerBreadcrumbs','storyPickerRoots','storyPickerSearch','storyPickerSelected','storyPickerOpen','storyPickerBack','storyPickerForward','storyPickerUp'].forEach(id=>nodes[id]=node());
const calls=[];const listing={entries:[{entry_token:'dir-1',name:'aa-data',kind:'directory',size:0,modified:'2026-08-03T00:00:00Z',type:'文件夹'},{entry_token:'spine-1',name:'Spine.com',kind:'file',size:5,modified:'2026-08-03T00:00:00Z',type:'文件'}],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
let selects=0;const window={Api:{request:async(p)=>{calls.push(p);if(p==='/api/settings/host?sort=name&direction=asc')return listing;selects+=1;return selects===1?{ok:true,entry_token:'dir-1',name:'aa-data',kind:'directory'}:{ok:true,entry_token:'spine-1',name:'Spine.com',kind:'file'};}},StoryUI:{}};const document={getElementById:id=>nodes[id],createElement:node,createDocumentFragment:node,activeElement:node(),addEventListener(){}};
vm.runInNewContext(source,{window,document,encodeURIComponent,URLSearchParams,Promise,Error,console});
(async()=>{const chosen=[];const picker=new window.StoryUI.StoryFilePicker(nodes.storyPicker,{hostEndpoint:'/api/settings/host',selectEndpoint:'/api/settings/entry',onChoose:x=>chosen.push(x)});await picker.openDirectory();picker.selectEntry(listing.entries[0],nodes.storyPickerEntries);await picker.confirm();await picker.openPath();picker.selectEntry(listing.entries[1],nodes.storyPickerEntries);await picker.confirm();console.log(JSON.stringify({chosen,calls}));})();
'''
    result = _run_picker(script)
    assert result["chosen"] == [
        {"ok": True, "entry_token": "dir-1", "name": "aa-data", "kind": "directory"},
        {"ok": True, "entry_token": "spine-1", "name": "Spine.com", "kind": "file"},
    ]
    assert result["calls"] == [
        "/api/settings/host?sort=name&direction=asc",
        "/api/settings/entry",
        "/api/settings/host?sort=name&direction=asc",
        "/api/settings/entry",
    ]
