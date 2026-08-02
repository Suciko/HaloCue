import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
HARNESS = HERE / "tests" / "ui_runtime_harness.js"


def run_runtime(script):
    output = subprocess.check_output(
        ["node", "-e", script, str(HARNESS)], text=True, encoding="utf-8"
    )
    return json.loads(output)


def test_ai_preflight_blocks_formal_steps_until_user_confirms():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const h=createHarness({poll:async()=>({state:'succeeded',result:{ai_status:'completed',characters:[{speaker:'凯伊',kind:'portrait',id:'hero-id',name:'凯伊',custom:true,confidence:.9,reason:'已匹配自定义骨骼'}],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]}}),request:async(p,o)=>{calls.push(p);if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[{who:'凯伊',n:1,sample:'你好'}],scenes:[]};if(p.startsWith('/api/guess'))return {'凯伊':{kind:'unset'}};if(p==='/api/preflight')return {job_id:'preflight-1'};if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();const before={preflightOff:h.get('#s2preflight').classList.contains('off'),formalOff:h.get('#s2').classList.contains('off'),approveDisabled:h.get('#preflightApprove').disabled,goDisabled:h.get('#go').disabled,text:h.get('#preflightCast').textContent};h.clickAction('approve-preflight',h.get('#preflightApprove'));const after={formalOff:h.get('#s2').classList.contains('off'),goDisabled:h.get('#go').disabled,hint:h.get('#preflightHint').textContent};console.log(JSON.stringify({before,after,preflightCalls:calls.filter(x=>x==='/api/preflight').length}));})();
'''
    result = run_runtime(script)
    assert result["before"] == {
        "preflightOff": False,
        "formalOff": True,
        "approveDisabled": False,
        "goDisabled": True,
        "text": "凯伊凯伊 · 本章自定义骨骼已匹配自定义骨骼修改",
    }
    assert result["after"]["formalOff"] is False
    assert result["after"]["goDisabled"] is False
    assert "已确认" in result["after"]["hint"]
    assert result["preflightCalls"] == 1


def test_preflight_missing_asset_opens_workbench_with_safe_tasks():
    script = r'''
const {createHarness}=require(process.argv[1]);let opened=null;
const h=createHarness();
h.window.openAssetWorkbench=context=>{opened=context;};
h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.AppRuntime.renderPreflight({ai_status:'completed',characters:[],assets:[
  {kind:'background',name:'雨夜天台',status:'missing',location:'第 46 行'},
  {kind:'bgm',name:'紧张曲',status:'missing',location:'第 50 行'}
],issues:[]});
const rows=h.get('#preflightAssets').children;
rows[0].children.find(child=>child.dataset.preflightAction==='open-workbench').click();
console.log(JSON.stringify({opened,bgmText:rows[1].textContent,tasks:h.window.AppRuntime.buildPreflightAssetTasks({assets:[{kind:'sound',name:'敲门',status:'missing',location:'第 9 行'}]})}));
'''
    result = run_runtime(script)
    assert result["opened"] == {
        "origin": "preflight",
        "story_token": "story-1",
        "asset_kind": "background",
        "tasks": [
            {
                "task_id": "background:雨夜天台:第 46 行",
                "kind": "background",
                "requested_name": "雨夜天台",
                "source_location": {"label": "第 46 行"},
                "reason": "剧本引用但当前剧情未登记",
                "candidate_keys": [],
            }
        ],
    }
    assert result["tasks"][0]["task_id"] == "sound:敲门:第 9 行"
    assert "当前版本尚未开放自定义 BGM 登记" in result["bgmText"]


def test_workbench_copy_refreshes_assets_and_preflight_but_ignores_stale_story():
    script = r'''
const {createHarness}=require(process.argv[1]);const phases=[],calls=[];
const preflight={ai_status:'completed',characters:[],assets:[],issues:[]};
const h=createHarness({onText:(selector,value)=>{if(selector==='#preflightStatus')phases.push(value);},storyAssets:{clear(){},load:async token=>{calls.push('assets:'+token);}},request:async(p,o)=>{calls.push(p);if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return preflight;if(p==='/api/drafts')return [];if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();calls.length=0;phases.length=0;h.window.dispatchEvent(new CustomEvent('assetworkbench:copied',{detail:{story_token:'old-story',kind:'background',aa_key:'old'}}));h.window.dispatchEvent(new CustomEvent('assetworkbench:copied',{detail:{story_token:'story-1',kind:'background',aa_key:'rain'}}));await h.drain();console.log(JSON.stringify({calls,phases,hint:h.get('#preflightHint').textContent}));})();
'''
    result = run_runtime(script)
    assert result["calls"].count("assets:story-1") == 1
    assert result["calls"].count("/api/preflight") == 1
    assert result["phases"][-1] == "初审结果已刷新"
    assert "AI 正在重新核对全文" in result["phases"]


def test_format_only_mode_reaches_review_without_requesting_ai_annotation():
    script = r'''
const {createHarness}=require(process.argv[1]);let draftReady=false,annotatePayload=null;
const emptyPreflight={ai_status:'completed',characters:[],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]};
const h=createHarness({poll:async()=>{draftReady=true;return {state:'succeeded',result:{draft_token:'draft-format'}}},request:async(p,o)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return emptyPreflight;if(p==='/api/annotate'){annotatePayload=o.payload;return {job_id:'annotate-1'}}if(p==='/api/drafts')return draftReady?[{draft_token:'draft-format',story_token:'story-1',project:'测试',draft_version:1}]:[];if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';h.get('#modelProfileSelect').value='profile-x';await h.window.AppRuntime.analyze();h.window.AppRuntime.approvePreflight();await h.window.AppRuntime.annotate();await h.drain();console.log(JSON.stringify({payload:annotatePayload,reviewHidden:h.get('#reviewPhase').classList.contains('is-hidden'),button:h.get('#goAnnotate').textContent,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["payload"]["annotate"] is False
    assert result["payload"]["model_profile_id"] == "profile-x"
    assert result["reviewHidden"] is False
    assert result["button"] == "生成审查草稿"
    assert "待审 0" in result["status"]


def test_background_timeline_keeps_order_and_replaces_the_same_card_with_revision():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];const cards=[{card_id:'bg-1',kind:'dir',line_no:1,current:{cmd:'bg',arg:'rain'}},{card_id:'line-1',kind:'line',line_no:2,current:{who:'凯伊',text:'你好'}},{card_id:'bg-2',kind:'dir',line_no:3,current:{cmd:'bg',arg:'sunny'}}];
const assets={characters:[],backgrounds:[{name:'雨夜',aa_key:'rain',preview_available:true},{name:'晴天',aa_key:'sunny',preview_available:true}],sounds:[],bgms:[]};
const h=createHarness({request:async(p,o)=>{calls.push({p,o});if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:7,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return assets;if(p==='/api/cards/update')return {ok:true,draft_version:8};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';await h.window.AppRuntime.loadReview();const track=h.get('#bgTimeline').children[1];const first=track.children[0];first.children[0].click();const jumped=h.get('#rvSelectionLabel').textContent;first.children[1].dispatch('click',{target:first.children[1],stopPropagation(){}});await h.drain();const options=h.get('#bgReplaceOptions');options.children[1].click();await h.drain();const update=calls.find(x=>x.p==='/api/cards/update');console.log(JSON.stringify({timeline:track.textContent,trackChildren:track.children.length,jumped,modal:h.get('#mBgReplace').classList.contains('on'),optionCount:options.children.length,payload:update&&update.o.payload}));})();
'''
    result = run_runtime(script)
    assert "rain" in result["timeline"] and "sunny" in result["timeline"]
    assert result["trackChildren"] == 3
    assert "#1" in result["jumped"]
    assert result["optionCount"] == 2
    assert result["payload"] == {
        "token": "draft-1",
        "expected_draft_version": 7,
        "card_id": "bg-1",
        "patch": {"cmd": "bg", "arg": "sunny"},
    }
