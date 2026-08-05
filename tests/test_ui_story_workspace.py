from pathlib import Path
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
(async()=>{await h.load();const startup={cta:h.get('#storyContextAction').textContent,assetEmpty:h.get('#storyAssetStrip').classList.contains('is-empty')};const list=h.get('#recentStories').children[1];const entry=list.children[0];await entry.click();await h.drain();console.log(JSON.stringify({startup,entry:{source:entry.children[0].children[0].textContent,project:entry.children[0].children[1].textContent,time:entry.children[0].children[2].textContent,resume:entry.children[1].textContent},story:h.window.StoryStore.get(),currentCalls:calls.filter(x=>x.startsWith('/api/story/current?'))}));})();
'''
    result = run_runtime(script)
    assert result["startup"] == {"cta": "打开剧情文件", "assetEmpty": True}
    assert result["entry"] == {
        "source": "第二章.txt", "project": "AA 工程：第二章工程",
        "time": "最近打开：08/01 17:30", "resume": "继续",
    }
    assert result["story"]["story_token"] == "story-b"
    assert result["currentCalls"] == ["/api/story/current?story_token=story-b"]


def test_replace_story_clears_real_dom_scope_before_showing_the_next_story():
    """Removing one scoped DOM reset leaks A's actors, preview, or build UI into B."""
    script = r'''
const {createHarness}=require(process.argv[1]);const h=createHarness({request:async(p)=>{if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});function fill(id,text){const n=h.get(id);n.textContent=text;n.appendChild({});return n}
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});['#cast','#bggrid','#rvCards','#storyPlayer'].forEach(id=>fill(id,'A'));['#bgsel','#s2sum','#s1info','#log'].forEach(id=>h.get(id).textContent='A');h.get('#log').classList.add('is-visible');['#s2','#s3','#s4'].forEach(id=>h.get(id).classList.remove('off'));await h.window.replaceStory({story_token:'B',project:'B',source_name:'B'});console.log(JSON.stringify({name:h.get('#storyContextName').textContent,cast:h.get('#cast').children.length,bg:h.get('#bggrid').children.length,cards:h.get('#rvCards').children.length,player:h.get('#storyPlayer').children.length,bgsel:h.get('#bgsel').textContent,sum:h.get('#s2sum').textContent,info:h.get('#s1info').textContent,log:{text:h.get('#log').textContent,visible:h.get('#log').classList.contains('is-visible')},steps:['#s2','#s3','#s4'].map(id=>h.get(id).classList.contains('off'))}));})();
'''
    assert run_runtime(script) == {
        "name": "B", "cast": 0, "bg": 0, "cards": 0, "player": 0,
        "bgsel": "未选择时使用 BG_Black", "sum": "", "info": "",
        "log": {"text": "", "visible": False}, "steps": [True, True, True],
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
    assert result["loaded"] == ["草稿：v3", "审查：待审 0 · 待处理 0"]
    assert result["reset"] == ["草稿：未载入", "保存：未载入", "审查：未审查", "编译：未编译", "安装：未安装"]


def test_old_background_response_cannot_populate_a_replaced_story_view():
    """An A background response after B commits must be silently discarded."""
    script = r'''
const {createHarness}=require(process.argv[1]);let release;const h=createHarness({request:async(p)=>{if(p.startsWith('/api/backgrounds'))return new Promise(r=>release=r);if(p==='/api/drafts')return [];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});const loading=h.window.AppRuntime.loadBackgrounds();await h.drain();await h.window.replaceStory({story_token:'B',project:'B'});release([{name:'A_BG'}]);await loading;console.log(JSON.stringify({grid:h.get('#bggrid').children.length,text:h.get('#bggrid').textContent}));})();
'''
    assert run_runtime(script) == {"grid": 0, "text": ""}


def test_same_token_old_draft_list_cannot_overwrite_a_newer_view_epoch():
    """A v1 response from a previous same-token attempt must not replace v2."""
    script = r'''
const {createHarness}=require(process.argv[1]);let releaseOld,calls=0;const h=createHarness({request:async(p)=>{if(p==='/api/drafts'){calls++;return calls===1?new Promise(r=>releaseOld=r):[{draft_token:'d2',story_token:'S',project:'S',draft_version:2}]}if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'S',project:'S'});const old=h.window.AppRuntime.refreshDrafts();await h.drain();await h.window.replaceStory({story_token:'S',project:'S',latest_draft_token:'d2'});releaseOld([{draft_token:'d1',story_token:'S',project:'S',draft_version:1}]);await old;console.log(JSON.stringify({selected:h.get('#rvDraftSelect').value,status:h.get('#storyDraftStatus').textContent}));})();
'''
    assert run_runtime(script) == {"selected": "d2", "status": "草稿：v2"}


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
