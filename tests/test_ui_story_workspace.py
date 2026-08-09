from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess


HERE = Path(__file__).resolve().parents[1]
UI = HERE / "ui.html"
HARNESS = HERE / "tests" / "ui_runtime_harness.js"


def run_runtime(script):
    return json.loads(subprocess.check_output(
        ["node", "-e", script, str(HARNESS)], text=True, encoding="utf-8"
    ))


def test_workspace_shell_loads_only_external_runtime_and_styles():
    """A strict CSP must still allow the initial workspace to boot."""
    html = UI.read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]+\bsrc=)[^>]*>", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)
    assert not re.search(r"\sstyle\s*=", html, re.I)
    assert '<script src="/js/api.js"></script>' in html
    assert '<script src="/js/story.js"></script>' in html
    assert '<script src="/js/app.js"></script>' in html


def test_workspace_uses_single_story_context_instead_of_asset_page():
    html = UI.read_text(encoding="utf-8")
    assert 'id="storyContextBar"' in html
    assert 'id="storyAssetStrip"' in html
    assert 'id="recentStories"' in html
    assert 'id="view-assets"' not in html
    # Recent stories are a top-of-workspace startup/change affordance; the
    # active-story flow remains context then assets.
    assert html.index('id="recentStories"') < html.index('id="storyContextBar"') < html.index('id="storyAssetStrip"')
    assert 'id="reviewPhase"' in html and 'review-layout is-hidden' in html


def test_workspace_exposes_a_history_switch_button_in_the_active_story_bar():
    html = UI.read_text(encoding="utf-8")
    assert 'id="storyHistoryAction"' in html
    assert 'data-action="show-history"' in html
    assert '>历史剧情<' in html


def test_replace_story_detaches_old_view_clears_scopes_and_keeps_new_story_on_load_error():
    """Deleting replaceStory or restoring a prior scope must fail this browser-level contract."""
    script = r'''
const {createHarness}=require(process.argv[1]);const events=[];
const assets={clear(){events.push('assets.clear')},async load(token){events.push('assets.load:'+token);throw new Error('assets offline')}};
const review={clear(){events.push('review.clear')},async loadLatest(story){events.push('review.load:'+story.story_token)}};
const preview={clear(){events.push('preview.clear')}};
const jobs={detachView(){events.push('jobs.detach')},cancel(){events.push('jobs.cancel')}};
const h=createHarness({storyAssets:assets,reviewWorkspace:review,preview:preview,storyJobs:jobs});
(async()=>{h.window.StoryStore.set({story_token:'story-a',project:'A'});await h.window.replaceStory({story_token:'story-b',project:'B',source_name:'B'});console.log(JSON.stringify({events,story:h.window.StoryStore.get(),error:h.get('#s1info').textContent}));})();
'''
    result = run_runtime(script)
    assert result["events"] == [
        "jobs.detach", "assets.clear", "review.clear", "preview.clear",
        "assets.load:story-b", "review.load:story-b",
    ]
    assert result["story"] == {"story_token": "story-b", "project": "B", "source_name": "B"}
    assert "无法加载" in result["error"]
    assert "story-a" not in result["error"]


def test_startup_and_recent_story_resume_render_only_one_current_workspace():
    """The empty CTA, rich recent entry, and safe-token resume are visible behavior."""
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const recent={story_token:'story-b',source_name:'第二章.txt',project:'第二章工程',last_opened_at:'2026-08-01T09:30:00Z'};
const h=createHarness({recent:[recent],request:async(p)=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-b')return Object.assign({},recent);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();const startup={cta:h.get('#storyContextAction').textContent,assetEmpty:h.get('#storyAssetStrip').classList.contains('is-empty')};const list=h.get('#recentStories').children[1];const entry=list.children[0];await entry.click();await h.drain();console.log(JSON.stringify({startup,entry:{source:entry.children[0].children[0].textContent,project:entry.children[0].children[1].textContent,time:entry.children[0].children[2].textContent,resume:entry.children[1].textContent},timezoneOffset:new Date(recent.last_opened_at).getTimezoneOffset(),story:h.window.StoryStore.get(),currentCalls:calls.filter(x=>x.startsWith('/api/story/current?'))}));})();
'''
    result = run_runtime(script)
    local_time = datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc) - timedelta(
        minutes=result["timezoneOffset"]
    )
    assert result["startup"] == {"cta": "打开剧情文件", "assetEmpty": True}
    assert result["entry"] == {
        "source": "第二章.txt", "project": "AA 工程：第二章工程",
        "time": f"最近打开：{local_time:%m/%d %H:%M}", "resume": "继续",
    }
    assert result["story"]["story_token"] == "story-b"
    assert result["currentCalls"] == ["/api/story/current?story_token=story-b"]


def test_recent_story_list_shows_three_then_expands_and_collapses():
    script = r'''
const {createHarness}=require(process.argv[1]);
const recent=Array.from({length:5},(_,index)=>({story_token:'story-'+index,source_name:'story-'+index+'.txt',project:'工程'+index,last_opened_at:'2026-08-01T09:3'+index+':00Z'}));
const h=createHarness({recent,request:async p=>p==='/api/stories/recent'?recent:[]});
(async()=>{await h.load();let list=h.get('#recentStories').children[1];const first={count:list.children.length,more:list.children.length>3?list.children[list.children.length-1].textContent:''};if(first.more){await list.children[list.children.length-1].click();await h.drain();}list=h.get('#recentStories').children[1];const expanded={count:list.children.length,more:list.children[list.children.length-1].textContent};if(expanded.more){await list.children[list.children.length-1].click();await h.drain();}const collapsed={count:h.get('#recentStories').children[1].children.length};console.log(JSON.stringify({first,expanded,collapsed}));})();
'''
    assert run_runtime(script) == {
        "first": {"count": 4, "more": "打开查看更多"},
        "expanded": {"count": 6, "more": "收起"},
        "collapsed": {"count": 4},
    }


def test_refresh_restores_the_active_story_draft_and_selected_card_from_safe_tokens():
    """Removing startup recovery must return the refreshed UI to the recent-story screen."""
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const saved=JSON.stringify({story_token:'story-a',draft_token:'draft-a',card_id:'card-2'});
const story={story_token:'story-a',source_name:'第一章.txt',project:'第一章'};
const cards=[{card_id:'card-1',kind:'line',line_no:1,review_state:'approved',current:{who:'凯伊',text:'一'}},{card_id:'card-2',kind:'line',line_no:2,review_state:'pending',current:{who:'凯伊',text:'二'}}];
const h=createHarness({storage:{'aa-active-review-v1':saved},request:async(p)=>{calls.push(p);if(p==='/api/story/current?story_token=story-a')return story;if(p==='/api/stories/recent')return [story];if(p==='/api/drafts')return [{draft_token:'draft-a',story_token:'story-a',project:'第一章',draft_version:2}];if(p==='/api/draft?token=draft-a')return {draft_token:'draft-a',story_token:'story-a',project:'第一章',draft_version:2,counts:{pending:1,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.drain();console.log(JSON.stringify({story:h.window.StoryStore.get(),path:h.get('#path').value,draft:h.get('#rvDraftSelect').value,status:h.get('#rvStatus').textContent,selection:h.get('#rvSelectionLabel').textContent,calls,stored:JSON.parse(h.storage['aa-active-review-v1'])}));})();
'''
    result = run_runtime(script)
    assert result["story"]["story_token"] == "story-a"
    assert result["path"] == ""
    assert result["draft"] == "draft-a"
    assert result["selection"] == "已选 #2"
    assert "/api/story/current?story_token=story-a" in result["calls"]
    assert "/api/draft?token=draft-a" in result["calls"]
    assert result["stored"] == {
        "story_token": "story-a", "draft_token": "draft-a", "card_id": "card-2",
    }


def test_active_story_exposes_history_button_that_reopens_recent_stories():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const saved=JSON.stringify({story_token:'story-a',draft_token:'draft-a',card_id:null});
const story={story_token:'story-a',source_name:'a.txt',project:'A'};
const recent=[story,{story_token:'story-b',source_name:'b.txt',project:'B'}];
const h=createHarness({storage:{'aa-active-review-v1':saved},recent,request:async p=>{calls.push(p);if(p==='/api/story/current?story_token=story-a')return story;if(p==='/api/stories/recent')return recent;if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.drain();const before=h.get('#recentStories').classList.contains('is-hidden');h.clickAction('show-history');await h.drain();console.log(JSON.stringify({before,after:h.get('#recentStories').classList.contains('is-hidden'),entries:h.get('#recentStories').children[1].children.length,calls:calls.filter(x=>x==='/api/stories/recent').length}));})();
'''
    assert run_runtime(script) == {
        "before": True, "after": False, "entries": 2, "calls": 2,
    }


def test_refresh_discards_stale_active_review_tokens_and_falls_back_safely():
    """A deleted server-side story must not trap every later startup in recovery."""
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const h=createHarness({storage:{'aa-active-review-v1':JSON.stringify({story_token:'missing',draft_token:'old',card_id:'gone'})},request:async(p)=>{calls.push(p);if(p==='/api/story/current?story_token=missing')throw new Error('not found');if(p==='/api/stories/recent')return [];if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.drain();console.log(JSON.stringify({story:h.window.StoryStore.get(),saved:Object.prototype.hasOwnProperty.call(h.storage,'aa-active-review-v1'),welcome:h.get('#welcomePanel').hidden,calls}));})();
'''
    result = run_runtime(script)
    assert result["story"] is None
    assert result["saved"] is False
    assert result["welcome"] is False
    assert result["calls"].count("/api/story/current?story_token=missing") == 1


def test_refresh_reveals_a_restored_card_beyond_the_initial_render_limit():
    script = r'''
const {createHarness}=require(process.argv[1]);let shown=[];
const story={story_token:'story-a',project:'第一章'};
const cards=Array.from({length:305},(_,index)=>({card_id:'card-'+(index+1),kind:'line',line_no:index+1,review_state:'approved',current:{who:'凯伊',text:String(index+1)}}));
const h=createHarness({storage:{'aa-active-review-v1':JSON.stringify({story_token:'story-a',draft_token:'draft-a',card_id:'card-200'})},cardList:{renderCardList(_root,list){shown=list.map(card=>card.card_id);}},request:async p=>{if(p==='/api/story/current?story_token=story-a')return story;if(p==='/api/stories/recent')return [story];if(p==='/api/drafts')return [{draft_token:'draft-a',story_token:'story-a',project:'第一章',draft_version:1}];if(p==='/api/draft?token=draft-a')return {story_token:'story-a',draft_version:1,counts:{pending:0,blocking_errors:0},cards};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.drain();console.log(JSON.stringify({shown:shown.length,last:shown[shown.length-1],selection:h.get('#rvSelectionLabel').textContent}));})();
'''
    assert run_runtime(script) == {"shown": 200, "last": "card-200", "selection": "已选 #200"}


def test_recent_story_restore_rechecks_the_source_when_a_file_token_is_available():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const recent={story_token:'story-b',source_name:'第二章.txt',source_display:'桌面 / 第二章.txt',project:'第二章工程',file_token:'file-b',last_opened_at:'2026-08-01T09:30:00Z'};
const h=createHarness({recent:[recent],request:async(p)=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-b')return recent;if(p.startsWith('/api/analyze?token=file-b'))return {path:'private',lines:1,speakers:[],scenes:[],format:{label:'角色台词格式',confidence:'high'}};if(p.startsWith('/api/guess?token=file-b'))return {};if(p==='/api/preflight')return {characters:[],assets:[],issues:[],ai_status:'completed'};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/drafts'))return [];return {profiles:[]};}});
(async()=>{await h.load();const entry=h.get('#recentStories').children[1].children[0];await entry.click();await h.drain();console.log(JSON.stringify({source:h.get('#storyContextName').textContent,display:h.get('#storyContextMeta').textContent,analyze:calls.some(x=>x.startsWith('/api/analyze?token=file-b'))}));})();
'''
    result = run_runtime(script)
    assert result == {
        "source": "桌面 / 第二章.txt",
        "display": "AA 工程：第二章工程",
        "analyze": True,
    }


def test_recent_story_restores_fresh_approved_preflight_without_recalling_ai():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const result={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[{who:'凯伊',n:1,sample:'出发'}],scenes:[],format:{label:'角色台词格式',confidence:'high'}},characters:[{speaker:'凯伊',kind:'portrait',id:'hero',name:'凯伊',confidence:.98,reason:'已确认'}],assets:[],usage_chain:[],issues:[]};
const recent={story_token:'story-fresh',source_name:'fresh.txt',project:'Fresh',file_token:'file-fresh',last_opened_at:'2026-08-05T09:30:00Z',preflight_snapshot:{state:'fresh',approved:true,saved_at:'2026-08-05T09:31:00Z',result}};
const h=createHarness({recent:[recent],request:async(p)=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-fresh')return recent;if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.get('#recentStories').children[1].children[0].click();await h.drain();console.log(JSON.stringify({aiCalls:calls.filter(x=>x.startsWith('/api/analyze')||x==='/api/preflight'),cast:h.get('#preflightCast').textContent,status:h.get('#preflightStatus').textContent,generationOff:h.get('#s4').classList.contains('off'),approveDisabled:h.get('#preflightApprove').disabled}));})();
'''
    result = run_runtime(script)
    assert result["aiCalls"] == []
    assert "凯伊" in result["cast"]
    assert result["status"] == "AI 已完成"
    assert result["generationOff"] is False
    assert result["approveDisabled"] is False


def test_restored_preflight_snapshot_hydrates_character_avatar_without_recalling_ai():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const result={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[{who:'凯伊'}],scenes:[]},characters:[{speaker:'凯伊',kind:'portrait',id:'hero',name:'凯伊',custom:true}],assets:[],usage_chain:[],issues:[]};
const recent={story_token:'story-fresh',source_name:'fresh.txt',project:'Fresh',preflight_snapshot:{state:'fresh',approved:true,result}};
const h=createHarness({recent:[recent],request:async p=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-fresh')return recent;if(p.startsWith('/api/characters?q=hero'))return [{ident:'hero',name:'凯伊',source:'custom',avatar:'/thumb/hero.jpg'}];if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.get('#recentStories').children[1].children[0].click();await h.drain();const avatar=h.get('#preflightCast').children[0].children[0].children[0];console.log(JSON.stringify({src:avatar&&avatar.src||'',characterCalls:calls.filter(p=>p.startsWith('/api/characters')),aiCalls:calls.filter(p=>p.startsWith('/api/analyze')||p==='/api/preflight')}));})();
'''
    assert run_runtime(script) == {
        "src": "/thumb/hero.jpg",
        "characterCalls": ["/api/characters?q=hero"],
        "aiCalls": [],
    }


def test_restored_preflight_uses_named_avatar_when_exact_identifier_has_none():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const result={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[{who:'Alice'}],scenes:[]},characters:[{speaker:'Alice',kind:'portrait',id:'legacy-alice',name:'Alice'}],assets:[],usage_chain:[],issues:[]};
const recent={story_token:'story-alice',source_name:'alice.txt',project:'Alice',preflight_snapshot:{state:'fresh',approved:true,result}};
const h=createHarness({recent:[recent],request:async p=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-alice')return recent;if(p==='/api/characters?q=legacy-alice')return [{ident:'legacy-alice',name:'Alice',source:'observed',avatar:''}];if(p==='/api/characters?q=Alice')return [{ident:'winter-alice',name:'Alice',source:'overrides',avatar:'/thumb/alice.jpg'}];if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.get('#recentStories').children[1].children[0].click();await h.drain();await h.drain();const avatar=h.get('#preflightCast').children[0].children[0].children[0];console.log(JSON.stringify({src:avatar&&avatar.src||'',characterCalls:calls.filter(p=>p.startsWith('/api/characters'))}));})();
'''
    assert run_runtime(script) == {
        "src": "/thumb/alice.jpg",
        "characterCalls": [
            "/api/characters?q=legacy-alice",
            "/api/characters?q=Alice",
        ],
    }


def test_recent_story_keeps_stale_preflight_visible_but_blocks_it_until_rerun():
    script = r'''
const {createHarness}=require(process.argv[1]);const calls=[];
const old={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[],scenes:[],format:{label:'小说体',confidence:'high'}},characters:[],assets:[],usage_chain:[{segment:'旧场景',location:'旧地点',needs:[]}],issues:[]};
const refreshed={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:2,speakers:[],scenes:[],format:{label:'小说体',confidence:'high'}},characters:[],assets:[],usage_chain:[],issues:[]};
const recent={story_token:'story-stale',source_name:'stale.txt',project:'Stale',file_token:'file-stale',last_opened_at:'2026-08-05T09:30:00Z',preflight_snapshot:{state:'stale',approved:true,saved_at:'2026-08-05T09:31:00Z',result:old}};
const h=createHarness({recent:[recent],request:async(p)=>{calls.push(p);if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-stale')return recent;if(p==='/api/preflight')return refreshed;if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.get('#recentStories').children[1].children[0].click();await h.drain();const before={status:h.get('#preflightStatus').textContent,hint:h.get('#preflightHint').textContent,approveDisabled:h.get('#preflightApprove').disabled,generationOff:h.get('#s4').classList.contains('off'),plan:h.get('#preflightScenePlan').textContent,aiCalls:calls.filter(x=>x.startsWith('/api/analyze')||x==='/api/preflight').length};await h.window.AppRuntime.rerunPreflight();const after={status:h.get('#preflightStatus').textContent,approveDisabled:h.get('#preflightApprove').disabled,preflightCalls:calls.filter(x=>x==='/api/preflight').length};console.log(JSON.stringify({before,after}));})();
'''
    result = run_runtime(script)
    assert result["before"]["status"] == "原文已变化"
    assert "重新初审" in result["before"]["hint"]
    assert result["before"]["approveDisabled"] is True
    assert result["before"]["generationOff"] is True
    assert "旧场景" in result["before"]["plan"]
    assert result["before"]["aiCalls"] == 0
    assert result["after"] == {
        "status": "AI 已完成", "approveDisabled": False, "preflightCalls": 1,
    }


def test_restored_story_can_generate_without_a_picker_file_token():
    script = r'''
const {createHarness}=require(process.argv[1]);let annotatePayload=null,draftReady=false;
const result={ai_status:'completed',usage_chain_status:'completed',analysis:{lines:1,speakers:[],scenes:[],format:{label:'小说体',confidence:'high'}},characters:[],assets:[],usage_chain:[],issues:[]};
const recent={story_token:'story-restored',source_name:'restored.txt',project:'Restored',preflight_snapshot:{state:'fresh',approved:true,result}};
const h=createHarness({recent:[recent],poll:async()=>({state:'succeeded',result:{draft_token:'draft-restored'}}),request:async(p,o)=>{if(p==='/api/stories/recent')return [recent];if(p==='/api/story/current?story_token=story-restored')return recent;if(p==='/api/annotate'){annotatePayload=o.payload;draftReady=true;return {job_id:'annotate-restored'}}if(p==='/api/drafts')return draftReady?[{draft_token:'draft-restored',story_token:'story-restored',project:'Restored',draft_version:1}]:[];if(p.startsWith('/api/draft?'))return {story_token:'story-restored',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();await h.get('#recentStories').children[1].children[0].click();await h.drain();await h.window.AppRuntime.annotate();await h.drain();console.log(JSON.stringify({payload:annotatePayload,status:h.get('#rvStatus').textContent,log:h.get('#log').textContent}));})();
'''
    result = run_runtime(script)
    assert result["payload"]["story_token"] == "story-restored"
    assert "file_token" not in result["payload"]
    assert "待审 0" in result["status"]
    assert result["log"] == "草稿已生成，请完成审查后再编译安装"


def test_replace_story_clears_real_dom_scope_before_showing_the_next_story():
    """Removing one scoped DOM reset leaks A's actors, preview, or build UI into B."""
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness({request:async(p)=>{if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});function fill(id,text){const n=h.get(id);n.textContent=text;n.appendChild({});return n}
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});['#preflightCast','#preflightScenePlan','#bggrid','#rvCards','#storyPlayer'].forEach(id=>fill(id,'A'));['#s1info','#log'].forEach(id=>h.get(id).textContent='A');h.get('#log').classList.add('is-visible');h.get('#s4').classList.remove('off');await h.window.replaceStory({story_token:'B',project:'B',source_name:'B'});console.log(JSON.stringify({name:h.get('#storyContextName').textContent,cast:h.get('#preflightCast').children.length,scene:h.get('#preflightScenePlan').children.length,bg:h.get('#bggrid').children.length,cards:h.get('#rvCards').children.length,player:h.get('#storyPlayer').children.length,info:h.get('#s1info').textContent,log:{text:h.get('#log').textContent,visible:h.get('#log').classList.contains('is-visible')},generationOff:h.get('#s4').classList.contains('off')}));})();
'''
    assert run_runtime(script) == {
        "name": "B", "cast": 0, "scene": 0, "bg": 0, "cards": 0, "player": 0,
        "info": "", "log": {"text": "", "visible": False}, "generationOff": True,
    }


def test_only_the_current_transition_can_report_story_load_errors_and_retry_can_recover():
    """A late failed attempt must not overwrite a newer success, including for the same token."""
    script = r'''
const {createHarness}=require(process.argv[1]);let rejectA,resolveB,attempts=0;
const h=createHarness({storyAssets:{clear(){},load(){attempts++;return attempts===1?new Promise((_,r)=>rejectA=r):new Promise(r=>resolveB=r)}},reviewWorkspace:{clear(){},async loadLatest(){}},preview:{clear(){}},request:async()=>({profiles:[]})});
(async()=>{const a=h.window.replaceStory({story_token:'same',project:'A'});await h.drain();const b=h.window.replaceStory({story_token:'same',project:'B'});await h.drain();resolveB();await b;rejectA(new Error('old offline'));await a;const afterRace={story:h.window.StoryStore.get(),error:h.get('#s1info').textContent,retry:h.get('#storyLoadRetry').hidden};let offline=true;h.window.StoryAssets.load=async()=>{if(offline)throw new Error('offline')};await h.window.replaceStory({story_token:'retry',project:'Retry'});const failed={story:h.window.StoryStore.get(),error:h.get('#s1info').textContent,retry:h.get('#storyLoadRetry').hidden};offline=false;h.window.StoryAssets.load=async()=>{};await h.clickAction('retry-story-load');await h.drain();console.log(JSON.stringify({afterRace,failed,recovered:{story:h.window.StoryStore.get(),error:h.get('#s1info').textContent,retry:h.get('#storyLoadRetry').hidden}}));})();
'''
    result = run_runtime(script)
    assert result["afterRace"] == {"story": {"story_token": "same", "project": "B"}, "error": "", "retry": True}
    assert result["failed"]["story"] == {"story_token": "retry", "project": "Retry"}
    assert "重试加载" in result["failed"]["error"] and result["failed"]["retry"] is False
    assert result["recovered"] == {"story": {"story_token": "retry", "project": "Retry"}, "error": "", "retry": True}


def test_late_recent_restore_error_cannot_replace_a_newer_recent_restore():
    """The failed A /api/story/current response must not surface after B has resumed."""
    script = r'''
const {createHarness}=require(process.argv[1]);let rejectA,resolveB;const a={story_token:'A',project:'A'},b={story_token:'B',project:'B'};
const h=createHarness({recent:[a,b],request:async(p)=>{if(p==='/api/stories/recent')return [a,b];if(p==='/api/story/current?story_token=A')return new Promise((_,r)=>rejectA=r);if(p==='/api/story/current?story_token=B')return new Promise(r=>resolveB=r);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();const entries=h.get('#recentStories').children[1].children;entries[0].click();await h.drain();entries[1].click();await h.drain();resolveB(b);await h.drain();rejectA(new Error('A offline'));await h.drain();console.log(JSON.stringify({story:h.window.StoryStore.get(),error:h.get('#s1info').textContent,retry:h.get('#storyLoadRetry').hidden}));})();
'''
    assert run_runtime(script) == {"story": {"story_token": "B", "project": "B"}, "error": "", "retry": True}


def test_context_status_is_derived_and_resets_when_the_story_changes():
    """Status chips must never claim that an unopened/replaced story was reviewed or installed."""
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness({request:async(p)=>{if(p==='/api/drafts')return [{draft_token:'d',story_token:'A',project:'A',draft_version:3}];if(p.startsWith('/api/draft?'))return {story_token:'A',draft_version:3,counts:{pending:0,blocking_errors:0},cards:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A',latest_draft_token:'d'});await h.window.AppRuntime.refreshDrafts();await h.window.AppRuntime.loadReview();const loaded=[h.get('#storyDraftStatus').textContent,h.get('#storyReviewStatus').textContent];await h.window.replaceStory({story_token:'B',project:'B'});console.log(JSON.stringify({loaded,reset:[h.get('#storyDraftStatus').textContent,h.get('#storySaveStatus').textContent,h.get('#storyReviewStatus').textContent,h.get('#storyCompileStatus').textContent,h.get('#storyInstallStatus').textContent]}));})();
'''
    result = run_runtime(script)
    assert result["loaded"] == ["草稿：v1", "审查：待审 0 · 待处理 0"]
    assert result["reset"] == ["草稿：未载入", "保存：未载入", "审查：未审查", "编译：未编译", "安装：未安装"]


def test_generated_draft_labels_use_generation_version_instead_of_cas_revision():
    """Generating twice must show v1/v2 even though both new drafts have CAS revision one."""
    script = r'''
const {createHarness}=require(process.argv[1]);
const drafts=[
  {draft_token:'d1',story_token:'S',project:'同一工程',draft_version:1,created_at:'2026-08-05T10:00:00'},
  {draft_token:'d2',story_token:'S',project:'同一工程',draft_version:1,created_at:'2026-08-05T11:00:00'}
];
const h=createHarness({request:async(p)=>{if(p==='/api/drafts')return drafts;if(p==='/api/draft?token=d2')return {draft_token:'d2',story_token:'S',project:'同一工程',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'同一工程',latest_draft_token:'d2'});await h.window.AppRuntime.refreshDrafts();const labels=h.get('#rvDraftSelect').children.map(x=>x.textContent);await h.window.AppRuntime.loadReview();console.log(JSON.stringify({labels,status:h.get('#rvStatus').textContent,context:h.get('#storyDraftStatus').textContent}));})();
'''
    assert run_runtime(script) == {
        "labels": ["同一工程 · v1", "同一工程 · v2"],
        "status": "待审 0 · 待处理 0 · v2",
        "context": "草稿：v2",
    }


def test_restored_latest_draft_keeps_generation_version_when_it_is_the_only_visible_option():
    """A restored second generation must remain v2 after older story tokens are scoped out."""
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(p)=>{if(p==='/api/drafts')return [{draft_token:'d2',story_token:'S',project:'同一工程',draft_version:1,generation_version:2,created_at:'2026-08-05T11:00:00'}];if(p==='/api/draft?token=d2')return {draft_token:'d2',story_token:'S',project:'同一工程',draft_version:1,generation_version:2,counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'同一工程',latest_draft_token:'d2'});await h.window.AppRuntime.refreshDrafts();await h.window.AppRuntime.loadReview();console.log(JSON.stringify({label:h.get('#rvDraftSelect').children[0].textContent,status:h.get('#rvStatus').textContent,context:h.get('#storyDraftStatus').textContent}));})();
'''
    assert run_runtime(script) == {
        "label": "同一工程 · v2",
        "status": "待审 0 · 待处理 0 · v2",
        "context": "草稿：v2",
    }


def test_restart_can_restore_legacy_draft_with_same_project_and_old_story_token():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async p=>{if(p==='/api/drafts')return [{draft_token:'legacy-draft',story_token:'old-story-token',project:'同一工程',draft_version:4},{draft_token:'foreign-draft',story_token:'other-token',project:'其他工程',draft_version:2}];if(p==='/api/draft?token=legacy-draft')return {draft_token:'legacy-draft',story_token:'old-story-token',project:'同一工程',draft_version:4,counts:{pending:0,blocking_errors:0},cards:[{card_id:'line-1',kind:'line',line_no:1,current:{who:'旁白',text:'已恢复'}}]};if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'new-story-token',project:'同一工程',latest_draft_token:'legacy-draft'});await h.window.AppRuntime.refreshDrafts();const before={options:h.get('#rvDraftSelect').children.length,selected:h.get('#rvDraftSelect').value,openDisabled:h.get('#rvOpen').disabled};await h.window.AppRuntime.loadReview();console.log(JSON.stringify({before,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["before"] == {
        "options": 1,
        "selected": "legacy-draft",
        "openDisabled": False,
    }
    assert "待审 0" in result["status"]


def test_old_background_response_cannot_populate_a_replaced_story_view():
    """An A background response after B commits must be silently discarded."""
    script = r'''
const {createHarness}=require(process.argv[1]);let release;const h=createHarness({request:async(p)=>{if(p.startsWith('/api/backgrounds'))return new Promise(r=>release=r);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});const loading=h.window.AppRuntime.loadBackgrounds();await h.drain();await h.window.replaceStory({story_token:'B',project:'B'});release([{name:'A_BG'}]);await loading;console.log(JSON.stringify({grid:h.get('#bggrid').children.length,text:h.get('#bggrid').textContent}));})();
'''
    assert run_runtime(script) == {"grid": 0, "text": ""}


def test_slow_old_background_search_cannot_overwrite_newer_results():
    script = r'''
const {createHarness}=require(process.argv[1]);let releaseOld;
const h=createHarness({request:async(p)=>{if(p.includes('q=old'))return new Promise(r=>releaseOld=r);if(p.includes('q=new'))return [{name:'BG_New',label:'新结果'}];return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#bgq').value='old';const oldSearch=h.window.AppRuntime.loadBackgrounds();await h.drain();h.get('#bgq').value='new';await h.window.AppRuntime.loadBackgrounds();releaseOld([{name:'BG_Old',label:'旧结果'}]);await oldSearch;console.log(JSON.stringify({count:h.get('#bggrid').children.length,text:h.get('#bggrid').textContent}));})();
'''
    assert run_runtime(script) == {"count": 1, "text": "暂无预览新结果"}


def test_same_token_old_draft_list_cannot_overwrite_a_newer_view_epoch():
    """A v1 response from a previous same-token attempt must not replace v2."""
    script = r'''
const {createHarness}=require(process.argv[1]);let releaseOld,calls=0;const h=createHarness({request:async(p)=>{if(p==='/api/drafts'){calls++;return calls===1?new Promise(r=>releaseOld=r):[{draft_token:'d2',story_token:'S',project:'S',draft_version:2}]}if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});const old=h.window.AppRuntime.refreshDrafts();await h.drain();await h.window.replaceStory({story_token:'S',project:'S',latest_draft_token:'d2'});releaseOld([{draft_token:'d1',story_token:'S',project:'S',draft_version:1}]);await old;console.log(JSON.stringify({selected:h.get('#rvDraftSelect').value,status:h.get('#storyDraftStatus').textContent}));})();
'''
    assert run_runtime(script) == {"selected": "d2", "status": "草稿：v1"}


def test_old_review_read_or_mutation_cannot_restore_cards_or_status_after_replace():
    """A stale review GET/POST must not repopulate the next view, even with the same token."""
    script = r'''
const {createHarness}=require(process.argv[1]);let releaseDraft,releasePost;const h=createHarness({request:async(p)=>{if(p.startsWith('/api/draft?'))return new Promise(r=>releaseDraft=r);if(p==='/api/review/approve')return new Promise(r=>releasePost=r);if(p==='/api/drafts')return [{draft_token:'d',story_token:'S',project:'S',draft_version:2}];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';const oldRead=h.window.AppRuntime.loadReview();await h.drain();await h.window.replaceStory({story_token:'S',project:'S'});releaseDraft({story_token:'S',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[{card_id:'old'}]});await oldRead;h.get('#rvDraftSelect').value='d';const currentRead=h.window.AppRuntime.loadReview();await h.drain();releaseDraft({story_token:'S',draft_version:2,counts:{pending:0,blocking_errors:0},cards:[]});await currentRead;const oldPost=h.window.AppRuntime.reviewPost('/api/review/approve',{});await h.drain();await h.window.replaceStory({story_token:'S',project:'S'});releasePost({ok:true,draft_version:3});await oldPost;console.log(JSON.stringify({cards:h.get('#rvCards').children.length,status:h.get('#rvStatus').textContent,save:h.get('#storySaveStatus').textContent}));})();
'''
    assert run_runtime(script) == {"cards": 0, "status": "找到 1 份草稿，打开后可继续审查", "save": "保存：未修改"}


def test_old_background_resolution_cannot_reopen_the_new_story_panel():
    """A resolving A request must not render its result after B replaces the view."""
    script = r'''
const {createHarness}=require(process.argv[1]);let resolve;const h=createHarness({request:async(p)=>{if(p==='/api/build/background/resolve')return new Promise(r=>resolve=r);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});h.window.AppRuntime.renderBackgroundRequests({resume_token:'a-job',backgrounds_ready:false,background_requests:[{id:'a-1',status:'pending'}]});const old=h.window.AppRuntime.resolveBackground('a-1','A_BG');await h.drain();await h.window.replaceStory({story_token:'B',project:'B'});resolve({resume_token:'a-job',backgrounds_ready:true,background_requests:[{id:'a-1',status:'resolved'}]});await old;console.log(JSON.stringify({open:h.get('#backgroundRequestsPanel').classList.contains('open'),items:h.get('#backgroundRequestList').children.length,hint:h.get('#backgroundContinueHint').textContent,disabled:h.get('#continueBackgroundBuild').disabled}));})();
'''
    assert run_runtime(script) == {"open": False, "items": 0, "hint": "", "disabled": True}


def test_old_background_continue_response_or_error_cannot_reactivate_the_new_story():
    """The old continuation POST and its catch/finally must stay inside A's view epoch."""
    script = r'''
const {createHarness}=require(process.argv[1]);let resolve;const h=createHarness({request:async(p)=>{if(p==='/api/build/background/continue')return new Promise(r=>resolve=r);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});h.window.AppRuntime.beginOperation('build');h.window.AppRuntime.renderBackgroundRequests({resume_token:'a-job',backgrounds_ready:true,background_requests:[]});const old=h.window.AppRuntime.continueBackground();await h.drain();await h.window.replaceStory({story_token:'B',project:'B'});resolve({ok:true});await old;console.log(JSON.stringify({open:h.get('#backgroundRequestsPanel').classList.contains('open'),items:h.get('#backgroundRequestList').children.length,hint:h.get('#backgroundContinueHint').textContent,disabled:h.get('#continueBackgroundBuild').disabled,go:h.get('#go').disabled}));})();
'''
    assert run_runtime(script) == {"open": False, "items": 0, "hint": "", "disabled": True, "go": True}


def test_old_compile_post_cannot_mutate_a_new_review_instance_with_the_same_token():
    """A v1 compile response must not poll or change v2 review controls/status."""
    script = r'''
        const {createHarness}=require(process.argv[1]);let resolvePost,drafts=0,polls=0;const h=createHarness({request:async(p)=>{if(p==='/api/draft?token=d')return {story_token:'S',draft_version:drafts===0?1:2,counts:{pending:0,blocking_errors:0},cards:[]};if(p==='/api/compile')return new Promise(r=>resolvePost=r);return {profiles:[]};},poll:async()=>{polls++;return {state:'succeeded'}}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const old=h.window.AppRuntime.compile();await h.drain();drafts=1;await h.window.AppRuntime.loadReview();const before={status:h.get('#rvStatus').textContent,install:h.get('#rvInstall').disabled};resolvePost({ok:true,build_id:'old',job_id:'old'});await old;console.log(JSON.stringify({before,after:{status:h.get('#rvStatus').textContent,install:h.get('#rvInstall').disabled},polls}));})();
'''
    assert run_runtime(script) == {"before": {"status": "待审 0 · 待处理 0 · v2", "install": True}, "after": {"status": "待审 0 · 待处理 0 · v2", "install": True}, "polls": 0}


def test_asset_strip_and_recent_list_replace_children_between_renders():
    """A second story render must replace, rather than append to, the first DOM tree."""
    script = r'''
const {createHarness}=require(process.argv[1]);let recentCalls=0;const h=createHarness({request:async(p)=>{if(p.startsWith('/api/story/assets?story_token=A'))return {characters:['a'],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/story/assets?story_token=B'))return {characters:[],backgrounds:['b','c'],sounds:[],bgms:[]};if(p==='/api/stories/recent'){recentCalls++;return recentCalls===1?[{story_token:'A',project:'A',source_name:'A'}]:[{story_token:'B',project:'B',source_name:'B'}]}return {profiles:[]};}});const assets=new h.window.StoryUI.StoryAssetStrip(h.get('#storyAssetStrip'));const recent=new h.window.StoryUI.RecentStories(h.get('#recentStories'),()=>{});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});await assets.load('A');h.window.StoryStore.set({story_token:'B',project:'B'});await assets.load('B');await recent.refresh();await recent.refresh();const asset=h.get('#storyAssetStrip'),recentRoot=h.get('#recentStories'),entry=recentRoot.children[1].children[0];console.log(JSON.stringify({assetChildren:asset.children.length,assetHasB:asset.textContent.includes('backgrounds 2'),recentChildren:recentRoot.children.length,recentEntries:recentRoot.children[1].children.length,recentHasB:entry.textContent.startsWith('B')}));})();
'''
    assert run_runtime(script) == {"assetChildren": 2, "assetHasB": True, "recentChildren": 2, "recentEntries": 1, "recentHasB": True}


def test_recent_refresh_uses_latest_generation_and_a_click_opens_once():
    """Late A must not overwrite B, and nested recent labels must not double-open."""
    script = r'''
const {createHarness}=require(process.argv[1]);let a,b,calls=0,opens=0;const h=createHarness({request:async(p)=>{if(p==='/api/stories/recent'){calls++;return calls===1?new Promise(r=>a=r):new Promise(r=>b=r)}return {profiles:[]};}});const recent=new h.window.StoryUI.RecentStories(h.get('#recentStories'),()=>opens++);
(async()=>{const first=recent.refresh();await h.drain();const second=recent.refresh();await h.drain();b([{story_token:'B',project:'B',source_name:'B'}]);await second;a([{story_token:'A',project:'A',source_name:'A'}]);await first;const entry=h.get('#recentStories').children[1].children[0];entry.click();console.log(JSON.stringify({label:entry.textContent,entries:h.get('#recentStories').children[1].children.length,opens}));})();
'''
    assert run_runtime(script) == {"label": "BAA 工程：B最近打开：未知继续", "entries": 1, "opens": 1}


def test_install_button_opens_optional_category_confirmation_without_installing():
    script = r'''
const {createHarness}=require(process.argv[1]);let installPosts=0;
const h=createHarness({request:async(p,o)=>{if(p==='/api/draft?token=d')return {story_token:'S',project:'第一幕-第一章',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p==='/api/compile')return {ok:true,build_id:'b',job_id:'j'};if(p.startsWith('/api/install/options?'))return {ok:true,source_project:'第一幕-第一章',default_category:'',default_story_name:'第一幕-第一章',categories:['大故事']};if(p==='/api/install'){installPosts++;return {ok:true}}return {profiles:[]};},poll:async()=>({state:'succeeded'})});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'第一幕-第一章'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();await h.window.AppRuntime.compile();await h.window.AppRuntime.openInstallDialog(h.get('#rvInstall'));console.log(JSON.stringify({open:h.get('#mInstall').classList.contains('on'),category:h.get('#installCategory').value,story:h.get('#installStoryName').value,preview:h.get('#installProjectPreview').textContent,options:h.get('#installCategoryOptions').children.map(x=>x.value),installPosts}));})();
'''
    assert run_runtime(script) == {
        "open": True,
        "category": "",
        "story": "第一幕-第一章",
        "preview": "第一幕-第一章",
        "options": ["大故事"],
        "installPosts": 0,
    }


def test_confirm_install_shows_exact_aa_locations_and_manual_open_instruction():
    script = r'''
const {createHarness}=require(process.argv[1]);let payload;
const h=createHarness({request:async(p,o)=>{if(p==='/api/draft?token=d')return {story_token:'S',project:'第一幕-第一章',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};if(p==='/api/compile')return {ok:true,build_id:'b',job_id:'j'};if(p.startsWith('/api/install/options?'))return {ok:true,source_project:'第一幕-第一章',default_category:'',default_story_name:'第一幕-第一章',categories:[]};if(p==='/api/install'){payload=o.payload;return {ok:true,project:'大故事-第一幕-第一章',aap_path:'E:\\AA\\data\\projects\\大故事-第一幕-第一章.aap',project_dir:'E:\\AA\\data\\projects\\大故事-第一幕-第一章',save_dir:'E:\\AA\\data\\saves\\大故事-第一幕-第一章'}}return {profiles:[]};},poll:async()=>({state:'succeeded'})});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'第一幕-第一章'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();await h.window.AppRuntime.compile();await h.window.AppRuntime.openInstallDialog();h.get('#installCategory').value='大故事';h.get('#installStoryName').value='第一幕-第一章';h.get('#installCategory').dispatch('input');await h.window.AppRuntime.confirmInstall();console.log(JSON.stringify({payload,preview:h.get('#installProjectPreview').textContent,resultHidden:h.get('#installResult').hidden,aap:h.get('#installAapPath').textContent,project:h.get('#installProjectDir').textContent,save:h.get('#installSaveDir').textContent,instruction:h.get('#installOpenHint').textContent,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["payload"] == {
        "token": "d",
        "expected_draft_version": 1,
        "build_id": "b",
        "category": "大故事",
        "story_name": "第一幕-第一章",
    }
    assert result["preview"] == "大故事-第一幕-第一章"
    assert result["resultHidden"] is False
    assert result["aap"].endswith("大故事-第一幕-第一章.aap")
    assert result["project"].endswith("大故事-第一幕-第一章")
    assert result["save"].endswith("大故事-第一幕-第一章")
    assert "AA" in result["instruction"] and ".aap" in result["instruction"]
    assert result["status"] == "安装完成：大故事-第一幕-第一章"


def test_install_result_copies_the_exact_aap_path_with_visible_feedback():
    script = r'''
const {createHarness}=require(process.argv[1]);let copied='';
const h=createHarness({request:async(p)=>{if(p==='/api/draft?token=d')return {story_token:'S',project:'第一幕-第一章',draft_version:1,last_compiled_build_id:'b',last_installed_build_id:'b',counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/install/options?'))return {ok:true,source_project:'第一幕-第一章',default_category:'',default_story_name:'第一幕-第一章',categories:[],existing_install:{project:'第一幕-第一章',aap_path:'E:\\AA\\data\\projects\\第一幕-第一章.aap',project_dir:'E:\\AA\\data\\projects\\第一幕-第一章',save_dir:'E:\\AA\\data\\saves\\第一幕-第一章'}};return {profiles:[]};}});
h.window.navigator={clipboard:{writeText:async(value)=>{copied=value;}}};
(async()=>{h.window.StoryStore.set({story_token:'S',project:'第一幕-第一章'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();await h.window.AppRuntime.openInstallDialog();await h.clickAction('copy-install-aap');await h.drain();console.log(JSON.stringify({copied,status:h.get('#installDialogStatus').textContent}));})();
'''
    assert run_runtime(script) == {
        "copied": r"E:\AA\data\projects\第一幕-第一章.aap",
        "status": "已复制 AA 工程文件路径。",
    }


def test_reopened_draft_restores_install_button_and_shows_existing_aap_location():
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(p)=>{if(p==='/api/draft?token=d')return {story_token:'S',project:'第一章',draft_version:2,last_compiled_build_id:'b',last_installed_build_id:'b',last_installed_project:'大故事-第一章',counts:{pending:0,blocking_errors:0},cards:[]};if(p.startsWith('/api/install/options?'))return {ok:true,source_project:'第一章',default_category:'',default_story_name:'第一章',categories:['大故事'],existing_install:{project:'大故事-第一章',aap_path:'E:\\AA\\data\\projects\\大故事-第一章.aap',project_dir:'E:\\AA\\data\\projects\\大故事-第一章',save_dir:'E:\\AA\\data\\saves\\大故事-第一章'}};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'第一章'});h.get('#rvDraftSelect').value='d';await h.window.AppRuntime.loadReview();const before={disabled:h.get('#rvInstall').disabled,compile:h.get('#storyCompileStatus').textContent,install:h.get('#storyInstallStatus').textContent};await h.window.AppRuntime.openInstallDialog();console.log(JSON.stringify({before,resultHidden:h.get('#installResult').hidden,resultState:h.get('#installResultState').textContent,resultProject:h.get('#installResultProject').textContent,aap:h.get('#installAapPath').textContent,status:h.get('#installDialogStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["before"] == {
        "disabled": False,
        "compile": "编译：已完成",
        "install": "安装：已安装 · 大故事-第一章",
    }
    assert result["resultHidden"] is False
    assert result["resultState"] == "已有安装"
    assert result["resultProject"] == "大故事-第一章"
    assert result["aap"].endswith("大故事-第一章.aap")
    assert "已有安装" in result["status"]
