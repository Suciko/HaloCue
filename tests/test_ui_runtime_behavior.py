import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
HARNESS = HERE / "tests" / "ui_runtime_harness.js"


def run_harness(script):
    return json.loads(subprocess.check_output(
        ["node", "-e", script, str(HARNESS)], text=True, encoding="utf-8"
    ))


def test_startup_does_not_reopen_the_previous_story_from_browser_storage():
    """Reintroducing automatic story restoration must fail this startup contract."""
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const h=createHarness({
  storage:{'aa-active-review-v1':JSON.stringify({story_token:'previous-story'})},
  request:async path=>{calls.push(path);if(path==='/api/state')return {stats:{}};if(path==='/api/setup/status')return {aa:{connected:true,path:''},database:{ready:true},model:{configured:false}};if(path==='/api/llm/profiles')return {profiles:[]};return {};}
});
(async()=>{await h.load();console.log(JSON.stringify({restored:calls.some(path=>path.indexOf('/api/story/current?story_token=previous-story')===0),story:h.window.StoryStore.get()}));})();
'''
    assert run_harness(script) == {"restored": False, "story": None}


def test_large_draft_filters_pending_blocking_and_direction_cards():
    """A filter wired only to labels instead of card behavior must fail this test."""
    script = r'''
const {createHarness}=require(process.argv[1]);let shown=[];
const cards=[
  {card_id:'approved',kind:'line',line_no:1,review_state:'approved',issues:[],current:{who:'凯伊',text:'完成'}},
  {card_id:'pending',kind:'line',line_no:2,review_state:'pending',issues:[],current:{who:'凯伊',text:'待审'}},
  {card_id:'blocking',kind:'line',line_no:3,review_state:'approved',issues:[{severity:'error',message:'角色未绑定'}],current:{who:'陌生人',text:'待处理'}},
  {card_id:'direction',kind:'dir',line_no:4,review_state:'approved',issues:[],current:{cmd:'bg',arg:'BG_GameDevRoom'}}
];
const h=createHarness({cardList:{renderCardList(_root,list){shown=list.map(card=>card.card_id);}},request:async p=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:1,blocking_errors:1},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const result={all:shown.slice()};for(const filter of ['pending','blocking','direction']){h.window.AppRuntime.setReviewFilter(filter);result[filter]=shown.slice();}console.log(JSON.stringify(result));})();
'''
    assert run_harness(script) == {
        "all": ["approved", "pending", "blocking", "direction"],
        "pending": ["pending"],
        "blocking": ["blocking"],
        "direction": ["direction"],
    }


def test_review_preview_rebuilds_after_story_scope_is_cleared():
    script = r'''
const {createHarness}=require(process.argv[1]);let currentStory='story-a',instances=[];
const cards=[{card_id:'card-1',kind:'line',line_no:1,review_state:'approved',current:{who:'望',text:'第一句'}}];
const h=createHarness({Player:function(){const id=instances.length+1;instances.push(id);this.pause=()=>{};this.loadCards=loaded=>{this.loaded=loaded;};this.jumpToCard=cardId=>{this.jumped=cardId;};},request:async p=>{if(p==='/api/draft?token=d')return {story_token:currentStory,draft_version:1,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {};}});
(async()=>{h.window.StoryStore.set({story_token:'story-a',project:'A'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const first=h.window.storyPlayer;currentStory='story-b';h.window.StoryStore.set({story_token:'story-b',project:'B'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();console.log(JSON.stringify({instances,rebuilt:first!==h.window.storyPlayer,selection:h.get('#rvSelectionLabel').textContent,preview:h.window.storyPlayer.loaded.length}));})();
'''
    assert run_harness(script) == {
        "instances": [1, 2], "rebuilt": True, "selection": "已选 #1 · 台词", "preview": 1,
    }


def test_card_number_jump_reveals_and_selects_a_card_beyond_the_initial_limit():
    """Keeping the 80-card slice must not make later card numbers unreachable."""
    script = r'''
const {createHarness}=require(process.argv[1]);let shown=[],jumped='';
const cards=Array.from({length:305},(_,index)=>({card_id:'card-'+(index+1),kind:'line',line_no:index+1,review_state:'approved',issues:[],current:{who:'凯伊',text:String(index+1)}}));
const h=createHarness({Player:function(){this.pause=()=>{};this.loadCards=()=>{};this.jumpToCard=id=>{jumped=id};},cardList:{renderCardList(_root,list){shown=list.map(card=>card.card_id);}},request:async p=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const initial=shown.length;h.get('#rvCardJump').value='200';const found=h.window.AppRuntime.jumpToReviewCard();console.log(JSON.stringify({initial,found,shown:shown.length,last:shown[shown.length-1],jumped,selection:h.get('#rvSelectionLabel').textContent}));})();
'''
    assert run_harness(script) == {
        "initial": 80, "found": True, "shown": 200, "last": "card-200",
        "jumped": "card-200", "selection": "已选 #200 · 台词",
    }


def test_review_navigation_controls_are_present_and_concise():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    for control_id in ("rvReviewFilters", "rvFilterAll", "rvFilterPending", "rvFilterBlocking", "rvFilterDirection", "rvCardJump", "rvJump"):
        assert f'id="{control_id}"' in html
    assert ">全部<" in html and ">待审<" in html and ">待处理<" in html and ">演出<" in html


def test_short_feedback_exposes_background_decision_cache_reuse_and_build_id():
    script = r'''
const {createHarness}=require(process.argv[1]);
const card={card_id:'bg-1',kind:'background_request',line_no:1,review_state:'pending',current:{description:'夜晚室内'}};
const h=createHarness({poll:async path=>({state:'succeeded',result:path.includes('annotate')?{draft_token:'d',resumed_chunks:3}:undefined}),request:async(p,o)=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[card]};if(p==='/api/drafts')return [{draft_token:'d',story_token:'S',draft_version:1}];if(p.startsWith('/api/drafts/d/backgrounds/'))return {ok:true,draft_version:2,merged_backgrounds:1};if(p==='/api/compile')return {ok:true,build_id:'build-short',job_id:'compile-1'};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();await h.window.AppRuntime.resolveDraftBackgroundRequest(card,'BG_Black');const background=h.get('#rvStatus').textContent;await h.window.AppRuntime.compile();console.log(JSON.stringify({background,compile:h.get('#rvStatus').textContent}));})();
'''
    result = run_harness(script)
    assert "合并" in result["background"]
    assert "默认黑屏" in result["background"]
    assert "build-short" in result["compile"]


def test_annotation_log_reports_checkpoint_reuse_count():
    script = r'''
const {createHarness}=require(process.argv[1]);
const story={story_token:'S',project:'S',preflight_snapshot:{state:'fresh',approved:true,result:{ai_status:'completed',analysis:{lines:1,speakers:[],scenes:[]},characters:[],assets:[],issues:[]}}};
const h=createHarness({poll:async()=>({state:'succeeded',result:{draft_token:'d',resumed_chunks:3}}),request:async(p)=>{if(p==='/api/annotate')return {job_id:'annotate-1'};if(p==='/api/drafts')return [{draft_token:'d',story_token:'S',project:'S',draft_version:1}];if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.window.replaceStory(story);await h.window.AppRuntime.annotate();console.log(JSON.stringify({log:h.get('#log').textContent}));})();
'''
    assert "复用 3 段" in run_harness(script)["log"]


def test_annotation_progress_formatter_describes_live_model_activity():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness();
console.log(JSON.stringify({
  waiting:h.window.AppRuntime.annotationProgressDetail({state:'waiting',detail:'正在标注第 1/4 个场景块',model:'deepseek-v4-flash'}),
  receiving:h.window.AppRuntime.annotationProgressDetail({state:'receiving',detail:'正在标注第 1/4 个场景块',received_chars:8192,elapsed_ms:7300,model:'deepseek-v4-flash'}),
  reasoning:h.window.AppRuntime.annotationProgressDetail({state:'reasoning',detail:'正在标注第 1/4 个场景块',reasoning_chars:4096,elapsed_ms:7300,model:'deepseek-v4-flash'}),
  retrying:h.window.AppRuntime.annotationProgressDetail({state:'retrying',detail:'正在标注第 1/4 个场景块',retry_count:1,model:'deepseek-v4-flash'}),
  subdividing:h.window.AppRuntime.annotationProgressDetail({state:'subdividing',detail:'正在标注第 1/4 个场景块',subdivision_count:2,model:'deepseek-v4-flash'})
}));
'''
    result = run_harness(script)
    assert "等待模型首段响应" in result["waiting"]
    assert "已接收 8,192 字符" in result["receiving"]
    assert "已思考 4,096 字符" in result["reasoning"]
    assert "正在纠正返回格式" in result["retrying"]
    assert "正在拆分当前场景块" in result["subdividing"]


def test_annotation_completion_formatter_reports_real_cache_state():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness();
console.log(JSON.stringify({
  hit:h.window.AppRuntime.formatAnnotationCompletion({actual_model:'deepseek-v4-flash',requests:7,retries:1,subdivisions:2,elapsed_ms:123456,cache_reported:true,cache_hit_rate:0.69,input_tokens:360075,output_tokens:118591,reasoning_tokens:80000,content_chars:12000}),
  unknown:h.window.AppRuntime.formatAnnotationCompletion({actual_model:'deepseek-v4-flash',requests:7,retries:1,subdivisions:2,elapsed_ms:123456,cache_reported:false,cache_hit_rate:null})
}));
'''
    result = run_harness(script)
    assert "69%" in result["hit"]
    assert "360,075" in result["hit"]
    assert "118,591" in result["hit"]
    assert "80,000" in result["hit"]
    assert "缓存未报告" in result["unknown"]


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
  nodes['#modelProfileSelect'].value='stale-profile-x';
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
