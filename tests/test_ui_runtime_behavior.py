import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
HARNESS = HERE / "tests" / "ui_runtime_harness.js"


def run_harness(script):
    return json.loads(subprocess.check_output(
        ["node", "-e", script, str(HARNESS)], text=True, encoding="utf-8"
    ))


def test_aa_executable_is_a_non_modal_gate_for_the_first_workflow_step():
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness();
const missing={connected:false,program:{status:'missing',path:''}};
const ready={connected:true,program:{status:'recognized',path:'E:/AA/AzureArchive.exe'}};
h.window.AppRuntime.applyAAReadiness(missing);
const before={gate:h.get('#aaSetupGate').hidden,choose:h.get('#chooseStoryButton').disabled,analyze:h.get('#analyzeStoryButton').disabled};
h.window.AppRuntime.applyAAReadiness(ready);
console.log(JSON.stringify({before,after:{gate:h.get('#aaSetupGate').hidden,choose:h.get('#chooseStoryButton').disabled,analyze:h.get('#analyzeStoryButton').disabled}}));
'''
    assert run_harness(script) == {
        "before": {"gate": False, "choose": False, "analyze": True},
        "after": {"gate": True, "choose": False, "analyze": False},
    }


def test_story_import_remains_available_before_aa_connection():
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness();
h.window.AppRuntime.applyAAReadiness({connected:false,program:{status:'missing',path:''}});
console.log(JSON.stringify({choose:h.get('#chooseStoryButton').disabled,context:h.get('#storyContextAction').disabled,analyze:h.get('#analyzeStoryButton').disabled}));
'''
    assert run_harness(script) == {
        "choose": False,
        "context": False,
        "analyze": True,
    }


def test_story_picker_opens_instead_of_redirecting_to_settings_before_aa_connection():
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness();
h.window.AppRuntime.applyAAReadiness({connected:false,program:{status:'missing',path:''}});
h.clickAction('open-script',h.get('#chooseStoryButton'));
console.log(JSON.stringify({picker:h.get('#mBrowse').classList.contains('on'),settings:h.get('#settingsDrawer').classList.contains('open')}));
'''
    assert run_harness(script) == {"picker": True, "settings": False}


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


def test_review_all_waits_for_in_app_confirmation_and_cancel_sends_nothing():
    script = r'''
const {createHarness}=require(process.argv[1]);const approvals=[];
const h=createHarness({request:async(p,o)=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:1,blocking_errors:0},cards:[{card_id:'c1',kind:'line',line_no:1,review_state:'pending',issues:[],current:{who:'凯伊',text:'待审'}}]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p==='/api/review/approve'){approvals.push(o);return {ok:true,draft_version:2};}return {};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const trigger=h.get('#rvApproveAll');h.clickAction('approve-all',trigger);await h.drain();const opened=h.get('#mApproveAll').classList.contains('on');h.clickAction('cancel-approve-all',h.get('#approveAllCancel'));await h.drain();console.log(JSON.stringify({opened,closed:!h.get('#mApproveAll').classList.contains('on'),approvals:approvals.length}));})();
'''
    assert run_harness(script) == {"opened": True, "closed": True, "approvals": 0}


def test_review_all_focuses_the_dialog_and_double_confirm_submits_once():
    script = r'''
const {createHarness}=require(process.argv[1]);let approvals=0,release;
const pending=new Promise(resolve=>{release=resolve});
const h=createHarness({request:async(p)=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:1,blocking_errors:0},cards:[{card_id:'c1',kind:'line',line_no:1,review_state:'pending',issues:[],current:{who:'凯伊',text:'待审'}}]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p==='/api/review/approve'){approvals+=1;await pending;return {ok:true,draft_version:2};}return {};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const trigger=h.get('#rvApproveAll');trigger.focus();h.clickAction('approve-all',trigger);const dialogFocused=h.getActiveElement()===h.get('#approveAllConfirm');h.clickAction('confirm-approve-all',h.get('#approveAllConfirm'));h.clickAction('confirm-approve-all',h.get('#approveAllConfirm'));await h.drain();const whileBusy=approvals;release();await h.drain();console.log(JSON.stringify({dialogFocused,whileBusy,total:approvals,focusReturned:h.getActiveElement()===trigger}));})();
'''
    assert run_harness(script) == {
        "dialogFocused": True,
        "whileBusy": 1,
        "total": 1,
        "focusReturned": True,
    }


def test_review_all_failure_stays_in_the_dialog_and_can_be_retried():
    script = r'''
const {createHarness}=require(process.argv[1]);let approvals=0;
const h=createHarness({request:async(p)=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:1,blocking_errors:0},cards:[{card_id:'c1',kind:'line',line_no:1,review_state:'pending',issues:[],current:{who:'凯伊',text:'待审'}}]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p==='/api/review/approve'){approvals+=1;throw new Error('草稿版本已变化');}return {};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();h.clickAction('approve-all',h.get('#rvApproveAll'));h.clickAction('confirm-approve-all',h.get('#approveAllConfirm'));await h.drain();console.log(JSON.stringify({open:h.get('#mApproveAll').classList.contains('on'),message:h.get('#approveAllStatus').textContent,confirmDisabled:h.get('#approveAllConfirm').disabled,approvals}));})();
'''
    assert run_harness(script) == {
        "open": True,
        "message": "操作失败：草稿版本已变化",
        "confirmDisabled": False,
        "approvals": 1,
    }


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


def test_completed_checkpoint_log_explains_that_no_model_was_called():
    script = r'''
const {createHarness}=require(process.argv[1]);
const story={story_token:'S',project:'S',preflight_snapshot:{state:'fresh',approved:true,result:{ai_status:'completed',analysis:{lines:1,speakers:[],scenes:[]},characters:[],assets:[],issues:[]}}};
const h=createHarness({poll:async()=>({state:'succeeded',result:{draft_token:'d',resumed_chunks:8,reused_draft:true,agent_metrics:{requests:0,input_tokens:0,output_tokens:0}}}),request:async(p)=>{if(p==='/api/annotate')return {job_id:'annotate-1'};if(p==='/api/drafts')return [{draft_token:'d',story_token:'S',project:'S',draft_version:1}];if(p==='/api/draft?token=d')return {story_token:'S',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.window.replaceStory(story);await h.window.AppRuntime.annotate();console.log(JSON.stringify({log:h.get('#log').textContent}));})();
'''
    message = run_harness(script)["log"]
    assert "本次未调用模型" in message
    assert "请求 0 次" not in message
    assert "复用 8 段" in message


def test_quota_failure_restores_the_open_draft_and_offers_model_settings():
    script = r'''
const {createHarness}=require(process.argv[1]);let shown=[];
const cards=Array.from({length:269},(_,i)=>({card_id:'card-'+(i+1),kind:'line',line_no:i+1,review_state:'approved',issues:[],current:{who:'凯伊',text:'台词'}}));
const story={story_token:'S',project:'S',latest_draft_token:'old',preflight_snapshot:{state:'fresh',approved:true,result:{ai_status:'completed',analysis:{path:'story.txt',lines:269,speakers:[],scenes:[]},characters:[],assets:[],issues:[]}}};
const h=createHarness({cardList:{renderCardList(_root,value){shown=value.map(x=>x.card_id);}},poll:async()=>({state:'failed',error:'quota-model 接口返回 HTTP 403: 用户额度不足 request_id=req_secret',error_code:'insufficient_quota',error_detail:{model:'quota-model',retryable:false,http_status:403}}),request:async(p)=>{if(p==='/api/annotate')return {job_id:'annotate-1'};if(p==='/api/drafts')return [{draft_token:'old',story_token:'S',project:'S',generation_version:5}];if(p==='/api/draft?token=old')return {story_token:'S',draft_version:5,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p==='/api/llm/workbench')return {connections:[],models:[],assignments:{},presets:[]};return {profiles:[]};}});
(async()=>{await h.window.replaceStory(story);h.get('#rvDraftSelect').value='old';await h.window.AppRuntime.loadReview('card-7');await h.window.AppRuntime.annotate();const before={hidden:h.get('#generationFailure').hidden,title:h.get('#generationFailureTitle').textContent,message:h.get('#generationFailureMessage').textContent,action:h.get('#generationFailureAction').textContent,technical:h.get('#generationFailureTechnical').textContent,retryDisabled:h.get('#generationFailureRetry').disabled,draftHidden:h.get('#generationFailureDraft').hidden,selected:h.get('#rvDraftSelect').value,reviewHidden:h.get('#reviewPhase').classList.contains('is-hidden'),shown:shown.length};await h.clickAction('open-model-settings');await h.drain();console.log(JSON.stringify({before,settings:h.get('#settingsDrawer').classList.contains('open')}));})();
'''
    result = run_harness(script)
    assert result["before"]["hidden"] is False
    assert result["before"]["title"] == "当前模型额度不足"
    assert "正式剧本生成" in result["before"]["message"]
    assert "切换基础模型" in result["before"]["action"]
    assert "req_secret" not in result["before"]["technical"]
    assert result["before"]["retryDisabled"] is True
    assert result["before"]["draftHidden"] is False
    assert result["before"]["selected"] == "old"
    assert result["before"]["reviewHidden"] is False
    assert result["before"]["shown"] == 80
    assert result["settings"] is True


def test_connection_test_copy_states_that_it_is_only_a_basic_check():
    app = (HERE / "js" / "app.js").read_text(encoding="utf-8")
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    assert "基础连通通过" in app
    assert "不验证正式剧本所需额度" in html


def test_annotation_progress_formatter_describes_live_model_activity():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness();
console.log(JSON.stringify({
  waiting:h.window.AppRuntime.annotationProgressDetail({state:'waiting',detail:'正在标注第 1/4 个场景块',model:'deepseek-v4-flash'}),
  receiving:h.window.AppRuntime.annotationProgressDetail({state:'receiving',detail:'正在标注第 1/4 个场景块',received_chars:8192,elapsed_ms:7300,model:'deepseek-v4-flash'}),
  reasoning:h.window.AppRuntime.annotationProgressDetail({state:'reasoning',detail:'正在标注第 1/4 个场景块',reasoning_chars:4096,elapsed_ms:7300,model:'deepseek-v4-flash'}),
  retrying:h.window.AppRuntime.annotationProgressDetail({state:'retrying',detail:'正在标注第 1/4 个场景块',retry_count:1,model:'deepseek-v4-flash'}),
  reasoningCapacity:h.window.AppRuntime.annotationProgressDetail({state:'retrying',reason:'reasoning_capacity',detail:'正在标注第 1/4 个场景块',retry_count:1,model:'deepseek-v4-flash'}),
  subdividing:h.window.AppRuntime.annotationProgressDetail({state:'subdividing',detail:'正在标注第 1/4 个场景块',subdivision_count:2,model:'deepseek-v4-flash'})
}));
'''
    result = run_harness(script)
    assert "等待模型首段响应" in result["waiting"]
    assert "已接收 8,192 字符" in result["receiving"]
    assert "已思考 4,096 字符" in result["reasoning"]
    assert "正在纠正返回格式" in result["retrying"]
    assert "增加预算并保留推理" in result["reasoningCapacity"]
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
    assert "累计思考 80,000" in result["hit"]
    assert "缓存未报告" in result["unknown"]


def test_partial_annotation_is_visible_and_disables_compile_and_install():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async p=>{
  if(p==='/api/draft?token=d') return {
    story_token:'S',draft_version:1,last_compiled_build_id:'stale-build',
    annotation_status:{status:'partial',completed_targets:213,total_targets:240,pending_targets:27,pending_start_line:434,pending_end_line:486},
    counts:{pending:0,blocking_errors:1},cards:[]
  };
  if(p.startsWith('/api/story/assets')) return {characters:[],backgrounds:[],sounds:[],bgms:[]};
  return {profiles:[]};
}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();console.log(JSON.stringify({status:h.get('#rvStatus').textContent,compile:h.get('#rvCompile').disabled,install:h.get('#rvInstall').disabled}));})();
'''
    result = run_harness(script)
    assert "AI 标注 213/240" in result["status"]
    assert "剩余 27" in result["status"]
    assert result["compile"] is True
    assert result["install"] is True


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
