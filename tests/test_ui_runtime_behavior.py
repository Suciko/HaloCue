import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def test_story_runtime_scopes_drafts_and_handles_build_terminal_states():
    """A stale story or failed compile must never leave an actionable review/install UI."""
    script = r'''
const fs=require('fs'), vm=require('vm');
const source=fs.readFileSync(process.argv[1], 'utf8');
const calls=[], nodes={}, subscribers=[];
function node(){ return {value:'',checked:false,disabled:false,hidden:false,textContent:'',dataset:{},children:[],
  classList:{toggle(){},add(){},remove(){}},appendChild(x){this.children.push(x);return x},append(...xs){xs.forEach(x=>this.appendChild(x))},
  removeChild(){this.children.shift()},get firstChild(){return this.children[0]},addEventListener(){},setAttribute(){},insertRow(){const x=node();this.children.push(x);return x},insertCell(){const x=node();this.children.push(x);return x},closest(){return null}}; }
function get(sel){ return nodes[sel]||(nodes[sel]=node()); }
['#rvDraftSelect','#rvStatus','#rvInstall','#rvCompile','#rvApproveAll','#rvValidate','#rvCards','#storyPlayer','#log','#go','#goAnnotate','#path','#proj','#bgq','#bgready','#backgroundRequestsPanel','#backgroundRequestList','#continueBackgroundBuild','#backgroundContinueHint','#hint','#s1info','#s2','#s3','#s4','#bggrid','#bgsel','#modelProfileSelect','#welcomePanel'].forEach(get);
nodes['input[name=anno]:checked']=node(); nodes['input[name=anno]:checked'].value='no';
const timers=[];
let story=null, jobState='failed', slowDrafts=false, releaseDrafts, backgroundReady=false, buildRequests=0, continueAttempts=0, continueShouldFail=true, continuationInFlight=false, resumedPolls=0;
const api={
  json(method,payload){ return {method,payload}; },
  async request(path, options){ calls.push({path,options});
    if(path==='/api/drafts') return slowDrafts ? new Promise(resolve=>releaseDrafts=resolve) : [{draft_token:'draft-a',story_token:'story-a',project:'A',draft_version:1}];
    if(path.startsWith('/api/draft?')) return {draft_version:1,counts:{pending:0,blocking_errors:0},cards:[],story_token:'story-a'};
    if(path==='/api/compile') return {ok:true,build_id:'build-a',job_id:'compile-a'};
    if(path==='/api/build') { buildRequests++; return {ok:true}; }
    if(path==='/api/job') {
      if(continuationInFlight) { resumedPolls++; return resumedPolls===1 ? {state:'backgrounds_ready',running:true,done:false,resume_token:'resume-1',background_requests:[{id:'bg-1',status:'resolved'}],backgrounds_ready:true,log:[]} : {state:'succeeded',running:false,done:true,log:[]}; }
      return {state:backgroundReady?'backgrounds_ready':'needs_backgrounds',running:false,done:true,resume_token:'resume-1',background_requests:[{id:'bg-1',status:backgroundReady?'resolved':'pending'}],backgrounds_ready:backgroundReady,log:[]};
    }
    if(path==='/api/build/background/continue') { continueAttempts++; if(continueShouldFail) throw new Error('temporary resume failure'); continuationInFlight=true; return {ok:true}; }
    if(path==='/api/picker') return {file_token:'file-a'};
    if(path==='/api/stories/open') return {story_token:'story-a',project:'A',source_name:'a.txt'};
    if(path.startsWith('/api/analyze?')) return {path:'C:/stories/a.txt',lines:1,speakers:[],scenes:[]};
    if(path.startsWith('/api/guess?')) return {};
    if(path.startsWith('/api/backgrounds?')) return [];
    return {profiles:[],stats:{}};
  },
    async poll(){ return {state:jobState,error:'broken'}; }
};
const window={Api:api,StoryStore:{get(){return story},set(v){story=v;subscribers.forEach(fn=>fn(v))},subscribe(fn){subscribers.push(fn);return()=>{}}},
  StoryUI:{StoryContextBar:function(){},StoryAssetStrip:function(){},RecentStories:function(){this.refresh=async()=>{}}},
  ModelSettings:{profilePayload(){return {}}},CardList:{renderCardList(){}},Player:function(){this.loadCards=()=>{};this.pause=()=>{};this.jumpToCard=()=>{}},
  addEventListener(){},confirm(){return true},prompt(){return null}};
const document={querySelector:get,querySelectorAll:()=>[],createElement:node,createDocumentFragment:node,addEventListener(){}};
const sandbox={window,document,localStorage:{getItem(){return null},setItem(){},removeItem(){}},setTimeout(fn){timers.push(fn)},console};
vm.runInNewContext(source,sandbox);
(async()=>{
  await window.AppRuntime.refreshDrafts();
  const noStory={draftRequests:calls.filter(x=>x.path==='/api/drafts').length, disabled:nodes['#rvInstall'].disabled};
  window.StoryStore.set({story_token:'story-a',project:'A'});
  slowDrafts=true; const staleRequest=window.AppRuntime.refreshDrafts();
  window.StoryStore.set({story_token:'story-b',project:'B'}); releaseDrafts([{draft_token:'draft-a',story_token:'story-a',project:'A',draft_version:1}]); await staleRequest;
  const staleDiscarded={draft: nodes['#rvDraftSelect'].value, status:nodes['#rvStatus'].textContent};
  slowDrafts=false; window.StoryStore.set({story_token:'story-a',project:'A'});
  nodes['#rvDraftSelect'].value='draft-a';
  await window.AppRuntime.loadReview();
  await window.AppRuntime.compile();
  const failed={install:nodes['#rvInstall'].disabled,status:nodes['#rvStatus'].textContent};
  jobState='succeeded';
  await window.AppRuntime.compile();
  const succeeded={install:nodes['#rvInstall'].disabled,status:nodes['#rvStatus'].textContent};
  nodes['#path'].value='C:/stories/a.txt';
  await window.AppRuntime.analyze();
  window.AppRuntime.renderPreflight({ai_status:'completed',characters:[],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]});
  window.AppRuntime.approvePreflight();
  await window.AppRuntime.build();
  const paused={goDisabled:nodes['#go'].disabled, buildRequests};
  await window.AppRuntime.build();
  const duplicateBuildRequests=buildRequests;
  backgroundReady=true; await window.AppRuntime.pollBuild();
  await window.AppRuntime.continueBackground();
  const retryAfterContinueFailure={continueDisabled:nodes['#continueBackgroundBuild'].disabled, goDisabled:nodes['#go'].disabled, continueAttempts};
  const backgroundDisabledAfterFailure=nodes['#continueBackgroundBuild'].disabled;
  continueShouldFail=false;
  await window.AppRuntime.continueBackground();
  const scheduledContinuationPolls=timers.length;
  while(timers.length) await timers.shift()();
  const continued={goDisabled:nodes['#go'].disabled,continueDisabled:nodes['#continueBackgroundBuild'].disabled,resumedPolls};
  const build=calls.find(x=>x.path==='/api/build');
  console.log(JSON.stringify({noStory,staleDiscarded,failed,succeeded,build:build.options.payload,backgroundDisabled:backgroundDisabledAfterFailure,paused,duplicateBuildRequests,retryAfterContinueFailure,scheduledContinuationPolls,continued}));
})();
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(HERE / "js" / "app.js")],
        text=True,
        encoding="utf-8",
    )
    result = json.loads(output)

    assert result["noStory"] == {"draftRequests": 0, "disabled": True}
    assert result["staleDiscarded"]["draft"] == ""
    assert "正在加载当前剧情草稿" in result["staleDiscarded"]["status"]
    assert result["failed"]["install"] is True
    assert "失败" in result["failed"]["status"]
    assert result["succeeded"]["install"] is False
    assert result["build"] == {
        "story_token": "story-a", "project": "A", "script": "C:/stories/a.txt",
        "mapping": {}, "bg": "BG_Black", "annotate": False,
        "model_profile_id": "", "install": False,
    }
    # A transient continue request failure leaves the resolved task retryable,
    # while the primary build action remains locked behind that task.
    assert result["backgroundDisabled"] is False
    assert result["paused"] == {"goDisabled": True, "buildRequests": 1}
    assert result["duplicateBuildRequests"] == 1
    assert result["retryAfterContinueFailure"] == {
        "continueDisabled": False, "goDisabled": True, "continueAttempts": 1,
    }
    # A defensive ``backgrounds_ready`` response can still be running just
    # after continue; it must be polled through to the terminal state.
    assert result["scheduledContinuationPolls"] == 1
    assert result["continued"] == {
        "goDisabled": False, "continueDisabled": True, "resumedPolls": 2,
    }
