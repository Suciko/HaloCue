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
const h=createHarness({poll:async()=>({state:'succeeded',result:{ai_status:'completed',characters:[{speaker:'凯伊',kind:'portrait',id:'hero-id',name:'凯伊',custom:true,confidence:.9,reason:'已匹配自定义骨骼'}],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]}}),request:async(p,o)=>{calls.push(p);if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[{who:'凯伊',n:1,sample:'你好'}],scenes:[]};if(p.startsWith('/api/guess'))return {'凯伊':{kind:'unset'}};if(p==='/api/preflight')return {job_id:'preflight-1'};if(p.startsWith('/api/characters'))return [{ident:'hero-id',name:'凯伊',source:'custom',avatar:'/thumb/hero.jpg'}];if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();const avatar=h.get('#preflightCast').children[0].children[0].children[0];const before={preflightOff:h.get('#s2preflight').classList.contains('off'),generationOff:h.get('#s4').classList.contains('off'),approveDisabled:h.get('#preflightApprove').disabled,goDisabled:h.get('#go').disabled,text:h.get('#preflightCast').textContent,avatar:avatar&&avatar.src||''};h.clickAction('approve-preflight',h.get('#preflightApprove'));const after={generationOff:h.get('#s4').classList.contains('off'),goDisabled:h.get('#go').disabled,hint:h.get('#preflightHint').textContent};console.log(JSON.stringify({before,after,preflightCalls:calls.filter(x=>x==='/api/preflight').length}));})();
'''
    result = run_runtime(script)
    assert result["before"] == {
        "preflightOff": False,
        "generationOff": True,
        "approveDisabled": False,
        "goDisabled": True,
        "text": "凯伊凯伊 · 本章自定义骨骼已匹配自定义骨骼修改",
        "avatar": "/thumb/hero.jpg",
    }
    assert result["after"]["generationOff"] is False
    assert result["after"]["goDisabled"] is False
    assert "已确认" in result["after"]["hint"]
    assert result["preflightCalls"] == 1


def test_preflight_approval_sends_selected_character_identity_for_persistence():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const h=createHarness({request:async(p,o)=>{calls.push({path:p,payload:o&&o.payload});return {ok:true,profiles:[]};}});
h.window.StoryStore.set({story_token:'story-save',project:'story'});
h.window.AppRuntime.renderPreflight({ai_status:'completed',characters:[{speaker:'Alice',kind:'portrait',id:'aris',name:'Alice',spine:'UIs/CharacterSpine_aris',avatar:'/thumb/av/Student_Portrait_Aris'}],assets:[],issues:[]});
(async()=>{await h.window.AppRuntime.approvePreflight();const request=calls.find(item=>item.path==='/api/preflight/approve');console.log(JSON.stringify(request&&request.payload));})();
'''
    assert run_runtime(script) == {
        "story_token": "story-save",
        "approved": True,
        "characters": [{
            "speaker": "Alice", "kind": "portrait", "id": "aris",
            "name": "Alice", "spine": "UIs/CharacterSpine_aris",
            "avatar": "/thumb/av/Student_Portrait_Aris",
        }],
    }


def test_preflight_cast_picker_shows_avatars_and_custom_group_first():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async p=>p.startsWith('/api/characters')?[
  {ident:'official-id',name:'官方角色',club:'官方社团',faces:3,source:'official',avatar:'/thumb/official.jpg'},
  {ident:'custom-id',name:'自定义角色',club:'自定义社团',faces:5,source:'custom',avatar:'/thumb/custom.jpg'}
]:{profiles:[]}});
const result={ai_status:'completed',characters:[
  {speaker:'凯伊',kind:'portrait',id:'custom-id',name:'自定义角色',custom:true,avatar:'/thumb/custom.jpg',reason:'已匹配'},
  {speaker:'老师',kind:'portrait',id:'official-id',name:'官方角色',custom:false,avatar:'/thumb/official.jpg',reason:'已匹配'}
],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]};
(async()=>{h.window.AppRuntime.renderPreflight(result);h.window.AppRuntime.openCastPicker('凯伊');await h.drain();const cards=[];const walk=node=>{(node.children||[]).forEach(child=>{if(String(child.className||'').split(' ').includes('cast-result'))cards.push(child);walk(child);});};walk(h.get('#castResults'));const groups=[];h.get('#castResults').children.forEach(child=>{if(child.dataset&&child.dataset.castGroup)groups.push(child.dataset.castGroup);});console.log(JSON.stringify({groups,firstAvatar:cards[0]&&cards[0].children[0]&&cards[0].children[0].children[0]&&cards[0].children[0].children[0].src||'',firstSelected:cards[0]&&cards[0].getAttribute('aria-pressed'),rowAvatar:h.get('#preflightCast').children[0]&&h.get('#preflightCast').children[0].children[0]&&h.get('#preflightCast').children[0].children[0].children[0]&&h.get('#preflightCast').children[0].children[0].children[0].src||''}));})();
'''
    result = run_runtime(script)
    assert result == {
        "groups": ["custom", "official"],
        "firstAvatar": "/thumb/custom.jpg",
        "firstSelected": "true",
        "rowAvatar": "/thumb/custom.jpg",
    }


def test_preflight_cast_avatar_falls_back_to_initial_when_preview_is_missing():
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness();
h.window.AppRuntime.renderPreflight({ai_status:'completed',characters:[{speaker:'凯伊',kind:'portrait',id:'missing',name:'凯伊',custom:true}],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]});
const row=h.get('#preflightCast').children[0];const avatar=row.children[0];const image=avatar&&avatar.children[0];if(image) image.dispatch('error');
console.log(JSON.stringify({className:avatar&&avatar.className,text:avatar&&avatar.textContent}));
'''
    result = run_runtime(script)
    assert result == {"className": "preflight-avatar", "text": "凯"}


def test_picking_custom_skeleton_keeps_its_avatar_in_preflight_row():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async p=>p.startsWith('/api/characters')?[{ident:'custom-id',name:'自定义凯伊',source:'custom',avatar:'/thumb/custom.jpg'}]:{profiles:[]}});
h.window.AppRuntime.renderPreflight({ai_status:'completed',characters:[{speaker:'凯伊',kind:'unset',id:'',name:'',custom:false}],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]});
(async()=>{h.window.AppRuntime.openCastPicker('凯伊');await h.drain();const card=h.get('#castResults').children.find(child=>String(child.className||'').split(' ').includes('cast-result'));card.click();const row=h.get('#preflightCast').children[0];console.log(JSON.stringify({src:row.children[0].children[0]&&row.children[0].children[0].src||'',text:row.textContent}));})();
'''
    result = run_runtime(script)
    assert result["src"] == "/thumb/custom.jpg"
    assert "本章自定义骨骼" in result["text"]


def test_background_request_uses_contextual_picker_instead_of_removed_prepare_step():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness();
h.window.AppRuntime.renderBackgroundRequests({resume_token:'job-1',backgrounds_ready:false,background_requests:[{id:'request-1',description:'雨夜车站',status:'pending'}]});
const button=h.get('#backgroundRequestList').children[0].children[0];
h.clickAction('resolve-background',button);
console.log(JSON.stringify({pickerOpen:h.get('#mBackgroundPicker').classList.contains('on')}));
'''
    assert run_runtime(script) == {"pickerOpen": True}


def test_review_background_request_can_use_default_black_without_history_import():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];let cardOptions=null;
const card={card_id:'card-18',kind:'background_request',line_no:12,current:{description:'雨夜车站'},review_state:'pending'};
const h=createHarness({cardList:{renderCardList(_root,_cards,options){cardOptions=options;}},request:async(p,o)=>{calls.push({p,o});if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:3,counts:{pending:1,blocking_errors:1},cards:[card]};if(p==='/api/drafts/draft-1/backgrounds/card-18/resolve')return {ok:true,draft_version:4,content_revision:2};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';await h.window.AppRuntime.loadReview();await cardOptions.onUseDefaultBackground(card);const call=calls.find(x=>x.p==='/api/drafts/draft-1/backgrounds/card-18/resolve');console.log(JSON.stringify({payload:call&&call.o.payload,draftLoads:calls.filter(x=>x.p.startsWith('/api/draft?')).length}));})();
'''
    assert run_runtime(script) == {
        "payload": {"bg_name": "BG_Black", "expected_draft_version": 3},
        "draftLoads": 2,
    }


def test_review_background_request_can_pick_from_official_catalog():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];let cardOptions=null;
const card={card_id:'card-18',kind:'background_request',line_no:12,current:{description:'雨夜车站'},review_state:'pending'};
const h=createHarness({cardList:{renderCardList(_root,_cards,options){cardOptions=options;}},request:async(p,o)=>{calls.push({p,o});if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:3,counts:{pending:1,blocking_errors:1},cards:[card]};if(p.startsWith('/api/backgrounds'))return [{name:'BG_RainyStation',label:'雨夜车站',img:true}];if(p==='/api/drafts/draft-1/backgrounds/card-18/resolve')return {ok:true,draft_version:4,content_revision:2};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';await h.window.AppRuntime.loadReview();cardOptions.onChooseBackground(card,h.get('#rvCards'));await h.drain();h.get('#bggrid').children[0].click();await h.drain();const call=calls.find(x=>x.p==='/api/drafts/draft-1/backgrounds/card-18/resolve');console.log(JSON.stringify({pickerOpen:h.get('#mBackgroundPicker').classList.contains('on'),payload:call&&call.o.payload}));})();
'''
    assert run_runtime(script) == {
        "pickerOpen": False,
        "payload": {"bg_name": "BG_RainyStation", "expected_draft_version": 3},
    }


def test_preflight_job_failure_keeps_the_reason_and_does_not_claim_no_asset_needs():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({poll:async()=>({state:'failed',error:'HTTP 502: upstream timeout'}),request:async(p,o)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[],scenes:[],format:{label:'角色台词格式',confidence:'high'}};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return {job_id:'preflight-1'};if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();console.log(JSON.stringify({status:h.get('#preflightStatus').textContent,summary:h.get('#preflightSummary').textContent,issues:h.get('#preflightIssues').textContent,assets:h.get('#preflightAssets').textContent}));})();
'''
    result = run_runtime(script)
    assert result["status"] == "AI 初审未完成"
    assert "演出规划未完成" in result["summary"]
    assert "不代表剧本错误" in result["summary"]
    assert "HTTP 502" in result["issues"]
    assert "初审进度详情" in result["issues"]
    assert "AI 诊断：" not in result["issues"]
    assert "演出规划未完成" in result["assets"]
    assert "@bg" not in result["assets"]
    assert "未发现阻塞问题" not in result["summary"]


def test_structured_output_failure_is_presented_as_response_pending_not_call_failure():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness();
h.window.AppRuntime.renderPreflight({
  ai_status:'failed',
  usage_chain_status:'unavailable',
  characters:[],
  assets:[],
  issues:[{severity:'warning',code:'ai_preflight_failed',message:'AI 已响应，但初审结果格式尚未整理完成。',action:'系统已自动重试一次。'}],
  ai_diagnostics:{stage:'structured_output',message:'返回结果格式不符合要求'}
});
console.log(JSON.stringify({
  status:h.get('#preflightStatus').textContent,
  summary:h.get('#preflightSummary').textContent,
  plan:h.get('#preflightScenePlan').textContent,
  issues:h.get('#preflightIssues').textContent
}));
'''
    result = run_runtime(script)
    assert result["status"] == "AI 已响应，结果待整理"
    assert "AI 已响应" in result["summary"]
    assert "不代表剧本错误" in result["summary"]
    assert "返回结果格式不符合要求" in result["issues"]
    assert "AI 诊断：" not in result["issues"]


def test_analyze_progress_matches_structured_output_pending_state():
    script = r'''
const {createHarness}=require(process.argv[1]);
const pending={ai_status:'failed',usage_chain_status:'unavailable',characters:[],assets:[],issues:[],ai_diagnostics:{stage:'structured_output',message:'格式待整理'}};
const h=createHarness({poll:async()=>({state:'succeeded',result:pending}),request:async(p,o)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:238,speakers:[{who:'凯伊',n:1,sample:'你好'}],scenes:[],format:{label:'角色台词格式',confidence:'high'}};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return {job_id:'preflight-1'};if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();console.log(JSON.stringify({progress:h.get('#scriptScanTitle').textContent,progressValue:h.get('#scriptScanBar').value,progressText:h.get('#scriptScanBar').textContent,info:h.get('#s1info').textContent,status:h.get('#preflightStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["status"] == "AI 已响应，结果待整理"
    assert result["progress"] == "AI 已响应，结果待整理；请检查下方规则结果。"
    assert result["progressValue"] == 3
    assert result["progressText"] == "3 / 4"
    assert "AI 已响应，结果待整理" in result["info"]
    assert "初审已完成" not in result["progress"]


def test_analyze_progress_marks_completed_preflight_consistently():
    script = r'''
const {createHarness}=require(process.argv[1]);
const completed={ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[]};
const h=createHarness({poll:async()=>({state:'succeeded',result:completed}),request:async(p)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:2,speakers:[],scenes:[],format:{label:'格式',confidence:'high'}};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return {job_id:'preflight-1'};return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();console.log(JSON.stringify({scan:h.get('#scriptScanTitle').textContent,bar:h.get('#scriptScanBar').textContent,status:h.get('#preflightStatus').textContent,info:h.get('#s1info').textContent}));})();
'''
    result = run_runtime(script)
    assert result["scan"] == "AI 初审已完成，请检查下方结果。"
    assert result["bar"] == "4 / 4"
    assert result["status"] == "AI 已完成"
    assert "AI 初审已完成" in result["info"]


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


def test_preflight_character_history_import_keeps_character_kind():
    script = r'''
const {createHarness}=require(process.argv[1]);let opened=null;
const h=createHarness();h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.HistoryDrawer={open:context=>{opened=context;}};
h.window.AppRuntime.renderPreflight({ai_status:'completed',characters:[],assets:[
  {kind:'character',name:'凯伊特殊服装',status:'missing',location:'第 8 行'}
],issues:[]});
const row=h.get('#preflightAssets').children[0];const history=row.children.find(child=>child.textContent==='从历史导入');history.click();console.log(JSON.stringify({kind:opened&&opened.kind}));
'''
    assert run_runtime(script) == {"kind": "character"}


def test_preflight_renders_scene_usage_chain_and_editable_background_prompt():
    script = r'''
const {createHarness}=require(process.argv[1]);
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const h=createHarness();
h.window.AppRuntime.renderPreflight({ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[{segment:'开场',location:'教室',start:'第1行',end:'第8行',evidence:'教室里，凯伊推开门。',needs:[
  {kind:'background',name:'教室',status:'registered',location:'第1行',reason:'已找到当前剧情背景',confidence:.94},
  {kind:'bgm',name:'轻松日常',status:'unsupported',location:'第1行',reason:'当前版本待验证',confidence:.61},
  {kind:'sound',name:'开门声',status:'missing',location:'第2行',reason:'正文描述动作',confidence:.86}
]},{segment:'转场',location:'夜间天台',start:'第9行',end:'第15行',evidence:'夜色中的天台很安静。',needs:[
  {kind:'background',name:'夜间天台',status:'missing',location:'第9行',reason:'官方库没有相近背景',confidence:.91,generation_prompt:'请生成一张用于剧情演出的二次元游戏背景图。\\n场景：夜间天台\\n无人物、无文字、无水印。'}
]}]});
const plan=h.get('#preflightScenePlan');const trigger=find(plan,node=>node.dataset&&node.dataset.usageAction==='generate-prompt');trigger.click();
console.log(JSON.stringify({plan:plan.textContent,modal:h.get('#mGenerationPrompt').classList.contains('on'),prompt:h.get('#generationPromptText').value}));
'''
    result = run_runtime(script)
    assert "开场" in result["plan"] and "背景" in result["plan"]
    assert "BGM" in result["plan"] and "开门声" in result["plan"]
    assert result["modal"] is True
    assert "夜间天台" in result["prompt"]
    assert "无人物" in result["prompt"]
    assert "低噪点" in result["prompt"]
    assert "无颗粒" in result["prompt"]
    assert "无 JPEG 压缩伪影" in result["prompt"]


def test_preflight_compacts_long_scene_range_without_changing_scene_title():
    script = r'''
const {createHarness}=require(process.argv[1]);
function findByClass(node,className){if(node.className===className)return node;for(const child of node.children||[]){const found=findByClass(child,className);if(found)return found;}return null;}
const h=createHarness();
h.window.AppRuntime.renderPreflight({ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[{severity:'warning',code:'optional_asset_suggestion',message:'场景一可选使用音效“环境人声喧嚣”。',action:'可直接跳过。'}],usage_chain:[{
  segment:'场景 1：商店街钟塔集合',location:'商店街入口的钟塔下',
  start:'旁白：休息日下午，商店街入口的钟塔下。远处传来钟声，来往的人群渐渐多了起来。',
  end:'凯伊：全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。',
  evidence:'休息日下午，商店街入口的钟塔下。',
  needs:[{kind:'background',name:'商店街入口钟塔',status:'missing',location:'开场',reason:'正文明确场景',confidence:.95}]
}]});
const plan=h.get('#preflightScenePlan');const title=findByClass(plan,'usage-scene-title');const range=findByClass(plan,'usage-scene-range');
console.log(JSON.stringify({title:title.textContent,range:range.textContent,length:range.textContent.length,ellipsis:(range.textContent.match(/…/g)||[]).length}));
'''
    result = run_runtime(script)
    assert result["title"] == "场景 1：商店街钟塔集合 · 商店街入口的钟塔下"
    assert result["length"] <= 67
    assert " → " in result["range"]
    assert result["range"].endswith("…")
    assert "所有人都跟上" not in result["range"]


def test_preflight_offers_background_candidate_and_custom_workflow_below_ninety_percent():
    script = r'''
const {createHarness}=require(process.argv[1]);
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const h=createHarness({request:async p=>p==='/api/preflight/background-binding'?{ok:true,preflight_snapshot:{state:'fresh',approved:false,result:{ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[{segment:'场景一',location:'商店街入口钟塔',evidence:'众人在商店街入口集合。',needs:[{kind:'background',name:'商店街入口钟塔',status:'registered',location:'场景一',reason:'已采用 Shopping District（BG_ShoppingDistrict）',confidence:.95,aa_key:'BG_ShoppingDistrict',selected_label:'Shopping District',source:'official',preview_source:'official',preview_available:true,candidates:[]}]}]}}}:{profiles:[]}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.AppRuntime.renderPreflight({ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[
  {kind:'background',name:'商店街入口钟塔',status:'approximate',location:'场景一',detected_by:'ai'},
  {kind:'sound',name:'环境人声喧嚣',status:'missing',location:'场景一',detected_by:'ai'},
  {kind:'bgm',name:'轻松日常BGM',status:'unsupported',location:'场景一',detected_by:'ai'}
],issues:[],usage_chain:[{
  segment:'场景一',location:'商店街入口钟塔',start:'开场',end:'集合后',evidence:'众人在商店街入口集合。',needs:[
    {kind:'background',name:'商店街入口钟塔',status:'approximate',location:'场景一',reason:'表现集合地点',confidence:.95,generation_prompt:'请生成商店街入口钟塔背景',candidates:[{aa_key:'BG_ShoppingDistrict',label:'Shopping District',confidence:.70,reason:'已有商店街背景，但没有突出钟塔',preview_available:false},{aa_key:'BG_CityTown',label:'City Town',confidence:.65,reason:'城市街道备选',preview_available:true}]},
    {kind:'sound',name:'环境人声喧嚣',status:'missing',location:'场景一',reason:'增强街道氛围',confidence:.75,candidates:[]},
    {kind:'bgm',name:'轻松日常BGM',status:'unsupported',location:'场景一',reason:'增强轻松氛围',confidence:.80,candidates:[]}
  ]
}]});
  const plan=h.get('#preflightScenePlan');const optional=find(plan,node=>node.className==='usage-optional');const custom=find(plan,node=>node.className==='usage-custom-background');const apply=find(plan,node=>node.dataset&&node.dataset.usageAction==='apply-candidate');const image=find(plan,node=>node.className==='usage-candidate-preview');const placeholder=find(plan,node=>node.className==='usage-candidate-placeholder');
  const before={text:plan.textContent,flatAssets:h.get('#preflightAssets').textContent,optionalPresent:Boolean(optional),optionalOpen:optional&&optional.open,customPresent:Boolean(custom),customOpen:custom&&custom.open,applyPresent:Boolean(apply),approveDisabled:h.get('#preflightApprove').disabled,image:image&&image.src,placeholder:placeholder&&placeholder.textContent,button:apply&&apply.textContent};
    (async()=>{if(apply)await apply.click();await h.drain();console.log(JSON.stringify({before,after:h.get('#preflightScenePlan').textContent,issues:h.get('#preflightIssues').textContent}));})();
'''
    result = run_runtime(script)
    assert "近似可用" in result["before"]["text"]
    assert "可选演出增强（2）" in result["before"]["text"]
    assert "近似候选" in result["before"]["flatAssets"]
    assert "环境人声喧嚣" not in result["before"]["flatAssets"]
    assert "轻松日常BGM" not in result["before"]["flatAssets"]
    assert result["before"]["optionalPresent"] is True
    assert result["before"]["optionalOpen"] is False
    assert result["before"]["customPresent"] is True
    assert result["before"]["customOpen"] is False
    assert "自定义背景工作流" in result["before"]["text"]
    assert result["before"]["applyPresent"] is True
    assert result["before"]["approveDisabled"] is False
    assert result["before"]["image"].endswith("/thumb/bg/BG_CityTown?px=240")
    assert result["before"]["placeholder"] == "暂无预览"
    assert result["before"]["button"] == "采用此背景"
    assert "已采用" in result["after"]
    assert "已采用 Shopping District（BG_ShoppingDistrict）" in result["after"]
    assert "生成提示词" not in result["after"]
    assert "环境人声喧嚣" not in result["issues"]


def test_official_background_choice_uses_persisted_binding_snapshot():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const source={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[],scenes:[]},characters:[],assets:[],issues:[],usage_chain:[{segment:'场景一',location:'商店街入口',needs:[{kind:'background',name:'商店街入口钟塔',status:'approximate',location:'第1行',reason:'需要集合地点',confidence:.95,candidates:[{aa_key:'BG_ShoppingDistrict',label:'Shopping District',source:'official',preview_source:'official',preview_available:true,confidence:.72,reason:'商店街近似'}]}]}]};
const bound=JSON.parse(JSON.stringify(source));Object.assign(bound.usage_chain[0].needs[0],{status:'registered',aa_key:'BG_ShoppingDistrict',selected_label:'Shopping District',source:'official',preview_source:'official',preview_available:true,candidates:[]});
const h=createHarness({request:async(p,o)=>{calls.push({path:p,payload:o&&o.payload});if(p==='/api/preflight/background-binding')return {ok:true,preflight_snapshot:{state:'fresh',approved:false,result:bound}};return {profiles:[]};}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.window.AppRuntime.renderPreflight(source);
const apply=find(h.get('#preflightScenePlan'),node=>node.dataset&&node.dataset.usageAction==='apply-candidate');
(async()=>{const pending=apply.click();await pending;await h.drain();const preview=find(h.get('#preflightScenePlan'),node=>node.className==='usage-bound-background-preview');console.log(JSON.stringify({binding:calls.find(x=>x.path==='/api/preflight/background-binding'),plan:h.get('#preflightScenePlan').textContent,preview:preview&&preview.src}));})();
'''
    result = run_runtime(script)
    assert result["binding"]["payload"] == {
        "story_token": "story-1",
        "selector": {
            "segment": "场景一",
            "location": "第1行",
            "requested_name": "商店街入口钟塔",
        },
        "binding": {
            "aa_key": "BG_ShoppingDistrict",
            "selected_label": "Shopping District",
        },
    }
    assert "已采用" in result["plan"]
    assert result["preview"].endswith("/thumb/bg/BG_ShoppingDistrict?px=480")


def test_adopted_official_and_custom_backgrounds_show_the_same_asset_identity_ui():
    script = r'''
const {createHarness}=require(process.argv[1]);
function findAll(node,predicate,found=[]){if(predicate(node))found.push(node);for(const child of node.children||[])findAll(child,predicate,found);return found;}
const h=createHarness();h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.AppRuntime.renderPreflight({ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[
  {segment:'场景一',location:'商店街入口',needs:[{kind:'background',name:'商店街入口钟塔',status:'registered',location:'第1行',reason:'剧情指定集合地点。',selected_label:'Shopping District',aa_key:'BG_ShoppingDistrict',source:'official',preview_source:'official',preview_available:false,candidates:[]}]},
  {segment:'场景二',location:'游戏中心',needs:[{kind:'background',name:'游戏中心室内',status:'registered',location:'第2行',reason:'剧情指定室内机台。',selected_label:'游戏中心',aa_key:'3040691084',source:'custom',preview_source:'story',preview_available:true,candidates:[]}]}
]});
const cards=findAll(h.get('#preflightScenePlan'),node=>node.className==='usage-bound-background');
console.log(JSON.stringify(cards.map(card=>({text:card.textContent,images:findAll(card,node=>Boolean(node.src)).map(node=>node.src),placeholder:findAll(card,node=>node.className==='usage-bound-background-placeholder').map(node=>node.textContent)}))));
'''
    result = run_runtime(script)
    assert result == [{
        "text": "预览暂不可用Shopping DistrictBG_ShoppingDistrict · AA 官方背景",
        "images": [],
        "placeholder": ["预览暂不可用"],
    }, {
        "text": "游戏中心3040691084 · 本剧情自定义背景",
        "images": [
            "/api/story/assets/preview?story_token=story-1&kind=background&key=3040691084"
        ],
        "placeholder": [],
    }]


def test_custom_background_workflow_exposes_generation_import_history_and_workbench_actions():
    script = r'''
const {createHarness}=require(process.argv[1]);const imports=[];let history=null;let workbenchContext=null;
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const listing={entries:[],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
const h=createHarness({storyPicker:true,request:async p=>p.startsWith('/api/assets/host')?listing:{profiles:[]},storyAssets:{importLocal:async(kind,context)=>{imports.push({kind,context});}}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.HistoryDrawer={open:context=>{history=context;}};
h.window.openAssetWorkbench=context=>{workbenchContext=context;};
function result(confidence){return {ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[{segment:'场景一',location:'商店街钟塔',evidence:'众人在钟塔下集合。',needs:[{kind:'background',name:'商店街钟塔',status:'recommended',location:'场景一',reason:'官方背景缺少钟塔细节',confidence:.95,candidates:[{aa_key:'BG_ShoppingDistrict',label:'Shopping District',confidence,reason:'缺少钟塔',preview_available:true}]}]}]};}
h.window.AppRuntime.renderPreflight(result(.89));
let plan=h.get('#preflightScenePlan');const custom=find(plan,node=>node.className==='usage-custom-background');
const prompt=find(custom,node=>node.dataset&&node.dataset.usageAction==='generate-prompt');
const local=find(custom,node=>node.dataset&&node.dataset.usageAction==='import-generated-background');
const fromHistory=find(custom,node=>node.dataset&&node.dataset.usageAction==='import-background-history');
const openWorkbench=find(custom,node=>node.dataset&&node.dataset.usageAction==='open-background-workbench');
  (async()=>{prompt.click();local.click();await h.drain();fromHistory.click();openWorkbench.click();
  const low={text:custom.textContent,open:custom.open,prompt:Boolean(prompt),promptLabel:prompt&&prompt.textContent,promptText:h.get('#generationPromptText').value,local:Boolean(local),history:Boolean(fromHistory),workbench:Boolean(openWorkbench),modal:h.get('#mGenerationPrompt').classList.contains('on'),pickerOpen:h.get('#mBrowse').classList.contains('on'),imports,historyKind:history&&history.kind,workbenchContext};
h.window.AppRuntime.renderPreflight(result(.90));plan=h.get('#preflightScenePlan');const high=find(plan,node=>node.className==='usage-custom-background');
console.log(JSON.stringify({low,highPresent:Boolean(high)}));})();
'''
    result = run_runtime(script)
    assert result["low"]["open"] is False
    assert "自定义背景工作流" in result["low"]["text"]
    assert result["low"]["prompt"] is True
    assert result["low"]["promptLabel"] == "生成生图提示词"
    assert "商店街钟塔" in result["low"]["promptText"]
    assert "16:9" in result["low"]["promptText"]
    assert result["low"]["local"] is True
    assert result["low"]["history"] is True
    assert result["low"]["workbench"] is True
    assert result["low"]["modal"] is False
    assert result["low"]["pickerOpen"] is True
    assert result["low"]["imports"] == []
    assert result["low"]["historyKind"] == "background"
    assert result["low"]["workbenchContext"]["tasks"][0]["candidate_keys"] == [
        "BG_ShoppingDistrict"
    ]
    assert result["highPresent"] is False


def test_generation_prompt_modal_chooses_an_image_and_shows_the_imported_preview():
    script = r'''
const {createHarness}=require(process.argv[1]);const imports=[],requests=[];
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const listing={entries:[{entry_token:'entry-image',name:'rain-night.png',kind:'file',size:2048,modified:'2026-08-05T00:00:00Z',type:'PNG 图片'}],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
const h=createHarness({storyPicker:true,request:async(p,o)=>{requests.push(p);if(p.startsWith('/api/assets/host'))return listing;if(p==='/api/assets/select')return {ok:true,file_token:'ft-image',name:'rain-night.png',size:2048};return {profiles:[]};},storyAssets:{importLocal:async(kind,context)=>{imports.push({kind,context});return {ok:true,status:'registered',kind:'background',stem:'rain-night',aa_key:'rain-night'};}}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});
h.window.AppRuntime.renderPreflight({ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[],scenes:[]},characters:[],assets:[],issues:[],usage_chain:[{segment:'场景一',location:'雨夜车站',needs:[{kind:'background',name:'雨夜车站',status:'missing',location:'场景一',reason:'需要雨夜氛围',candidates:[]}]}]});
const prompt=find(h.get('#preflightScenePlan'),node=>node.dataset&&node.dataset.usageAction==='generate-prompt');
(async()=>{prompt.click();const before=h.get('#mGenerationPrompt').classList.contains('on');h.clickAction('import-generation-result');await h.drain();const pickerOpen=h.get('#mBrowse').classList.contains('on'),pickerTitle=h.get('#browseTitle').textContent,searchPlaceholder=h.get('#storyPickerSearch').placeholder;h.get('#storyPickerEntries').children[0].click();await h.get('#storyPickerOpen').click();await h.drain();console.log(JSON.stringify({before,pickerOpen,pickerTitle,searchPlaceholder,after:h.get('#mGenerationPrompt').classList.contains('on'),resultVisible:!h.get('#generationImportResult').hidden,preview:h.get('#generationImportPreview').src,status:h.get('#generationPromptStatus').textContent,imports,requests}));})();
'''
    assert run_runtime(script) == {
        "before": True,
        "pickerOpen": True,
        "pickerTitle": "选择生成的背景图片",
        "searchPlaceholder": "搜索背景图片",
        "after": False,
        "resultVisible": True,
        "preview": "/api/story/assets/preview?story_token=story-1&kind=background&key=rain-night",
        "status": "已导入并登记到当前剧情。",
        "imports": [{
            "kind": "background",
            "context": {
                "name": "雨夜车站", "fileToken": "ft-image",
                "labels": {"label": "雨夜车站", "description": "需要雨夜氛围", "place": "雨夜车站"},
            },
        }],
        "requests": [
            "/api/assets/host?sort=name&direction=asc",
            "/api/assets/select",
            "/api/preflight/background-binding",
        ],
    }


def test_generation_import_inherits_scene_labels_binds_snapshot_and_renders_preview():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[],imports=[];
function find(node,predicate){if(predicate(node))return node;for(const child of node.children||[]){const found=find(child,predicate);if(found)return found;}return null;}
const sourceResult={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[],scenes:[]},characters:[],assets:[],issues:[],usage_chain:[{segment:'开场',location:'车站',needs:[{kind:'background',name:'雨夜车站',status:'missing',location:'第1行',reason:'雨夜候车氛围',candidates:[]}]}]};
const bound=JSON.parse(JSON.stringify(sourceResult));Object.assign(bound.usage_chain[0].needs[0],{status:'registered',aa_key:'9001',selected_label:'雨夜车站',source:'custom',preview_source:'story',preview_available:true,candidates:[]});
const listing={entries:[{entry_token:'entry-image',name:'rain-night.png',kind:'file',size:2048,modified:'2026-08-05T00:00:00Z',type:'PNG 图片'}],breadcrumbs:[],roots:[],parent_token:'',location_token:'root'};
const h=createHarness({storyPicker:true,request:async(p,o)=>{calls.push({path:p,payload:o&&o.payload});if(p.startsWith('/api/assets/host'))return listing;if(p==='/api/assets/select')return {ok:true,file_token:'ft-image',name:'rain-night.png',size:2048};if(p==='/api/preflight/background-binding')return {ok:true,preflight_snapshot:{state:'fresh',approved:false,result:bound}};return {profiles:[]};},storyAssets:{importLocal:async(kind,context)=>{imports.push({kind,context});return {ok:true,status:'registered',kind:'background',stem:'rain-night',aa_key:'9001'};}}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.window.AppRuntime.renderPreflight(sourceResult);
const local=find(h.get('#preflightScenePlan'),node=>node.dataset&&node.dataset.usageAction==='import-generated-background');
(async()=>{local.click();await h.drain();const promptWhilePicking=h.get('#mGenerationPrompt').classList.contains('on');h.get('#storyPickerEntries').children[0].click();await h.get('#storyPickerOpen').click();await h.drain();const preview=find(h.get('#preflightScenePlan'),node=>node.className==='usage-bound-background-preview');console.log(JSON.stringify({promptWhilePicking,imports,binding:calls.find(x=>x.path==='/api/preflight/background-binding'),preview:preview&&preview.src,plan:h.get('#preflightScenePlan').textContent}));})();
'''
    result = run_runtime(script)
    assert result["promptWhilePicking"] is False
    assert result["imports"] == [{
        "kind": "background",
        "context": {
            "name": "雨夜车站", "fileToken": "ft-image",
            "labels": {"label": "雨夜车站", "description": "雨夜候车氛围", "place": "车站"},
        },
    }]
    assert result["binding"]["payload"] == {
        "story_token": "story-1",
        "selector": {"segment": "开场", "location": "第1行", "requested_name": "雨夜车站"},
        "binding": {"aa_key": "9001", "selected_label": "雨夜车站"},
    }
    assert result["preview"] == (
        "/api/story/assets/preview?story_token=story-1&kind=background&key=9001"
    )
    assert "已采用" in result["plan"]


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
const {createHarness}=require(process.argv[1]);let draftReady=false,annotatePayload=null,preflightPayload=null;
const emptyPreflight={ai_status:'completed',usage_chain_status:'completed',usage_chain:[{segment:'开场',location:'教室',start:'第1行',end:'第1行',evidence:'教室里。',needs:[{kind:'background',name:'BG_Classroom',status:'builtin',location:'第1行',reason:'已匹配',confidence:.95}]}],characters:[],assets:[],available_assets:{characters:[],backgrounds:[],sounds:[],bgms:[]},issues:[]};
const h=createHarness({poll:async()=>{draftReady=true;return {state:'succeeded',result:{draft_token:'draft-format'}}},request:async(p,o)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight'){preflightPayload=o.payload;return emptyPreflight}if(p==='/api/annotate'){annotatePayload=o.payload;return {job_id:'annotate-1'}}if(p==='/api/drafts')return draftReady?[{draft_token:'draft-format',story_token:'story-1',project:'测试',draft_version:1}]:[];if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';h.get('#modelProfileSelect').value='profile-x';await h.window.AppRuntime.analyze();h.window.AppRuntime.approvePreflight();await h.window.AppRuntime.annotate();await h.drain();console.log(JSON.stringify({payload:annotatePayload,preflightPayload,reviewHidden:h.get('#reviewPhase').classList.contains('is-hidden'),button:h.get('#goAnnotate').textContent,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["payload"]["annotate"] is False
    assert result["preflightPayload"]["model_profile_id"] == ""
    assert result["payload"]["model_profile_id"] == ""
    assert result["payload"]["usage_chain"][0]["needs"][0]["name"] == "BG_Classroom"
    assert result["reviewHidden"] is False
    assert result["button"] == "生成审查草稿"
    assert "待审 0" in result["status"]


def test_ai_annotation_shows_wait_time_when_model_detail_stays_stale():
    script = r'''
const {createHarness}=require(process.argv[1]);const logs=[];
const emptyPreflight={ai_status:'completed',usage_chain_status:'completed',characters:[],assets:[],issues:[],usage_chain:[]};
const h=createHarness({onText:(selector,text)=>{if(selector==='#log')logs.push(text);},poll:async(_path,_done,options)=>{options.onProgress({state:'running',detail:'正在标注第 7/17 个场景块',updated_at:new Date(Date.now()-65000).toISOString()});return {state:'failed',error:'stop'};},request:async(p)=>{if(p==='/api/picker')return {file_token:'file-1'};if(p==='/api/stories/open')return {story_token:'story-1',project:'测试',source_name:'story.txt'};if(p.startsWith('/api/analyze'))return {path:'server-private',lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/preflight')return emptyPreflight;if(p==='/api/annotate')return {job_id:'annotate-1'};if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{h.get('#path').value='story.txt';await h.window.AppRuntime.analyze();h.window.AppRuntime.approvePreflight();h.get('input[name=anno]:checked').value='ai';await h.window.AppRuntime.annotate();console.log(JSON.stringify(logs));})();
'''
    result = run_runtime(script)
    assert "正在标注第 7/17 个场景块 · 模型仍在响应（已等待 1 分钟）" in result


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


def test_background_timeline_uses_official_preview_before_marking_asset_missing():
    script = r'''
const {createHarness}=require(process.argv[1]);
const cards=[{card_id:'bg-official',kind:'dir',line_no:6,current:{cmd:'bg',arg:'BG_ShoppingDistrict'}}];
const h=createHarness({request:async p=>{if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:1,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';await h.window.AppRuntime.loadReview();const node=h.get('#bgTimeline').children[1].children[0],jump=node.children[0],image=jump.children[0],placeholder=jump.children[1],meta=jump.children[3];const before={missing:node.classList.contains('is-missing'),src:image.src,meta:meta.textContent};image.dispatch('load',{target:image});const loaded={missing:node.classList.contains('is-missing'),meta:meta.textContent};image.dispatch('error',{target:image});const failed={missing:node.classList.contains('is-missing'),placeholder:placeholder.textContent,meta:meta.textContent};console.log(JSON.stringify({before,loaded,failed}));})();
'''
    result = run_runtime(script)
    assert result["before"] == {
        "missing": False,
        "src": "/thumb/bg/BG_ShoppingDistrict?px=320",
        "meta": "正在检查 AA 背景预览",
    }
    assert result["loaded"] == {"missing": False, "meta": "AA 官方背景"}
    assert result["failed"] == {
        "missing": True,
        "placeholder": "素材缺失",
        "meta": "AA 资源中未找到此背景",
    }


def test_background_timeline_opens_workbench_and_applies_copy_to_same_card_from_latest_revision():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];let opened=null;
const cards=[{card_id:'bg-card-2',kind:'dir',line_no:4,current:{cmd:'bg',arg:'old'}}];
const h=createHarness({request:async(p,o)=>{calls.push({p,o});if(p.startsWith('/api/draft?'))return {story_token:'story-1',draft_version:7,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p==='/api/cards/update')return {ok:true,draft_version:8};return {profiles:[]};}});
h.window.openAssetWorkbench=context=>{opened=context;};h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';
(async()=>{await h.window.AppRuntime.loadReview();const node=h.get('#bgTimeline').children[1].children[0];node.children[2].dispatch('click',{target:node.children[2],stopPropagation(){}});h.window.dispatchEvent(new CustomEvent('assetworkbench:copied',{detail:{story_token:'story-1',kind:'background',aa_key:'rain_roof',context:opened}}));await h.drain();const update=calls.find(x=>x.p==='/api/cards/update');console.log(JSON.stringify({opened,update:update&&update.o.payload,refreshed:calls.filter(x=>x.p.startsWith('/api/draft?')).length,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["opened"] == {
        "origin": "review",
        "story_token": "story-1",
        "draft_token": "draft-1",
        "card_id": "bg-card-2",
        "asset_kind": "background",
    }
    assert result["update"] == {
        "token": "draft-1",
        "card_id": "bg-card-2",
        "patch": {"cmd": "bg", "arg": "rain_roof"},
        "expected_draft_version": 7,
    }
    assert result["refreshed"] >= 2


def test_background_workbench_copy_conflict_keeps_copy_and_requests_confirmation():
    script = r'''
const {createHarness}=require(process.argv[1]);let latest=0;
const h=createHarness({request:async(p,o)=>{if(p.startsWith('/api/draft?')){latest++;return {story_token:'story-1',draft_version:latest===1?7:8,counts:{pending:0,blocking_errors:0},cards:[{card_id:'bg-card-2',kind:'dir',line_no:4,current:{cmd:'bg',arg:'other'}}]};}if(p==='/api/cards/update'){const error=new Error('revision conflict');error.status=409;throw error;}if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
h.window.StoryStore.set({story_token:'story-1',project:'测试'});h.get('#rvDraftSelect').value='draft-1';
(async()=>{await h.window.AppRuntime.loadReview();await h.window.AppRuntime.applyWorkbenchBackground({origin:'review',story_token:'story-1',draft_token:'draft-1',card_id:'bg-card-2'},{aa_key:'rain_roof'});console.log(JSON.stringify({status:h.get('#rvStatus').textContent,latest}));})();
'''
    result = run_runtime(script)
    assert result["latest"] == 3
    assert result["status"] == "素材已复制；草稿已变化，请再次确认应用"
