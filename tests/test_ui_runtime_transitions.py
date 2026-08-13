import json
import subprocess

import pytest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
HARNESS = HERE / "tests" / "ui_runtime_harness.js"


def run_runtime(script):
    output = subprocess.check_output(
        ["node", "-e", script, str(HARNESS)], text=True, encoding="utf-8"
    )
    return json.loads(output)


def test_open_recent_b_commits_over_a_picker_that_resolves_late():
    """Removing the transition guard would let A overwrite B or analyze A."""
    script = r'''
const {createHarness}=require(process.argv[1]);let releaseA;const calls=[];
const h=createHarness({recent:[{story_token:'B',project:'B',source_name:'B'}],request:async(p,o)=>{calls.push(p);if(p==='/api/picker')return new Promise(r=>releaseA=r);if(p==='/api/stories/open')return {story_token:'A',project:'A',source_name:'A'};if(p==='/api/story/current?story_token=B')return {story_token:'B',project:'B',source_name:'B'};if(p.startsWith('/api/analyze'))return {path:'A',lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/drafts')return [];if(p==='/api/stories/recent')return [{story_token:'B',project:'B',source_name:'B'}];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};return {profiles:[]};}});
(async()=>{await h.load();h.get('#path').value='A';const openingA=h.window.AppRuntime.analyze();await h.drain();const recentButton=h.get('#recentStories').children[1].children[0];await recentButton.click();releaseA({file_token:'file-a'});await openingA;console.log(JSON.stringify({story:h.window.StoryStore.get(),path:h.get('#path').value,project:h.get('#proj').value,openA:calls.filter(x=>x==='/api/stories/open').length,analyzeA:calls.filter(x=>x.startsWith('/api/analyze')).length,guessA:calls.filter(x=>x.startsWith('/api/guess')).length}));})();
'''
    result = run_runtime(script)
    assert result == {
        "story": {"story_token": "B", "project": "B", "source_name": "B"},
        "path": "B",
        "project": "B",
        "openA": 0,
        "analyzeA": 0,
        "guessA": 0,
    }


def test_annotate_a_completion_cannot_mutate_b_review_workspace():
    """Removing the operation scope checks would load A's succeeded draft into B."""
    script = r'''
const {createHarness}=require(process.argv[1]);let resolvePoll;const calls=[];let playerLoads=[];
const a={story_token:'A',project:'A',source_name:'A',latest_draft_token:'draft-a'},b={story_token:'B',project:'B',source_name:'B',latest_draft_token:'draft-b'};
const h=createHarness({recent:[b],Player:function(){this.pause=()=>{};this.loadCards=x=>playerLoads.push(x.map(c=>c.card_id));this.jumpToCard=()=>{};},cardList:{renderCardList(){}},poll:()=>new Promise(r=>resolvePoll=r),request:async(p,o)=>{calls.push(p);if(p==='/api/picker')return {file_token:h.get('#path').value==='B'?'file-b':'file-a'};if(p==='/api/stories/open')return o.payload.file_token==='file-b'?b:a;if(p==='/api/story/current?story_token=B')return b;if(p.startsWith('/api/analyze'))return {path:h.get('#path').value,lines:1,speakers:[],scenes:[]};if(p.startsWith('/api/guess'))return {};if(p==='/api/annotate')return {job_id:'annotate-a'};if(p==='/api/drafts')return h.window.StoryStore.get().story_token==='A'?[{draft_token:'draft-a',story_token:'A',project:'A',draft_version:1}]:[{draft_token:'draft-b',story_token:'B',project:'B',draft_version:4}];if(p.startsWith('/api/draft?token=draft-a'))return {story_token:'A',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[{card_id:'a-card',kind:'line',line_no:1,current:{who:'A',text:'old'}}]};if(p.startsWith('/api/draft?token=draft-b'))return {story_token:'B',draft_version:4,counts:{pending:0,blocking_errors:0},cards:[{card_id:'b-card',kind:'line',line_no:1,current:{who:'B',text:'new'}}]};if(p==='/api/stories/recent')return [b];if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[]};if(p.startsWith('/api/backgrounds'))return [];return {profiles:[]};}});
(async()=>{await h.load();h.get('#path').value='A';await h.window.AppRuntime.analyze();await h.window.AppRuntime.loadReview();const annotating=h.clickAction('annotate');await h.drain();const recentButton=h.get('#recentStories').children[1].children[0];recentButton.click();await h.drain();await h.window.AppRuntime.analyze();const before={drafts:h.get('#rvDraftSelect').children.map(x=>x.value),selected:h.get('#rvDraftSelect').value,status:h.get('#rvStatus').textContent,cards:h.get('#rvCards').children.length,player:playerLoads.slice(),annotateDisabled:h.get('#goAnnotate').disabled,goDisabled:h.get('#go').disabled,reviewSafe:{compile:h.get('#rvCompile').disabled,install:h.get('#rvInstall').disabled}};const callsBefore=calls.slice();resolvePoll({state:'succeeded',result:{draft_token:'draft-a'}});await annotating;const after={drafts:h.get('#rvDraftSelect').children.map(x=>x.value),selected:h.get('#rvDraftSelect').value,status:h.get('#rvStatus').textContent,cards:h.get('#rvCards').children.length,player:playerLoads.slice(),annotateDisabled:h.get('#goAnnotate').disabled,goDisabled:h.get('#go').disabled,reviewSafe:{compile:h.get('#rvCompile').disabled,install:h.get('#rvInstall').disabled}};console.log(JSON.stringify({story:h.window.StoryStore.get().story_token,before,after,postCompletion:calls.slice(callsBefore.length),aDraftLoads:calls.filter(x=>x==='/api/draft?token=draft-a').length}));})();
'''
    result = run_runtime(script)
    assert result["story"] == "B"
    assert result["before"] == result["after"]
    assert result["before"]["drafts"] == ["draft-b"]
    assert result["before"]["annotateDisabled"] is False
    assert result["before"]["goDisabled"] is False
    assert result["before"]["reviewSafe"] == {"compile": True, "install": True}
    assert result["aDraftLoads"] == 1
    assert result["postCompletion"] == []


def test_analyze_open_failures_report_the_current_attempt_without_replacing_story():
    """Without an opening attempt token, pre-analysis picker/open errors are silently lost."""
    script = r'''
const {createHarness}=require(process.argv[1]);
async function run(kind, prior){const h=createHarness({request:async(p)=>{if(p==='/api/picker'){if(kind==='picker')throw new Error('路径无效');return {file_token:'new-file'};}if(p==='/api/stories/open')throw new Error('路径无效');return {profiles:[]};}});h.get('#go').disabled=true;if(prior)h.window.StoryStore.set(prior);h.get('#path').value='bad.txt';await h.window.AppRuntime.analyze();return {story:h.window.StoryStore.get(),info:h.get('#s1info').textContent,go:h.get('#go').disabled,annotate:h.get('#goAnnotate').disabled};}
(async()=>console.log(JSON.stringify({picker:await run('picker',null),open:await run('open',{story_token:'old',project:'Old'})})))();
'''
    result = run_runtime(script)
    assert result == {
        "picker": {"story": None, "info": "路径无效", "go": True, "annotate": False},
        "open": {
            "story": {"story_token": "old", "project": "Old"},
            "info": "路径无效",
            "go": True,
            "annotate": False,
        },
    }


def test_compile_poll_is_scoped_to_its_story_and_review_and_reports_retries():
    """Removing the poll scope lets a stale compile keep polling after a story switch."""
    script = r'''
const {createHarness}=require(process.argv[1]);let pollOptions,pollResolve,jobRequests=0;
const h=createHarness({poll:(_path,_done,options)=>{pollOptions=options;return new Promise(resolve=>pollResolve=()=>{if(!options||!options.isCurrent||options.isCurrent()){jobRequests++;resolve({state:'succeeded'});}else resolve(null);});},request:async(p)=>{if(p==='/api/compile')return {ok:true,build_id:'build-a',job_id:'job-a'};if(p.startsWith('/api/draft?'))return {story_token:'A',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[]};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set({story_token:'A',project:'A'});h.get('#rvDraftSelect').value='draft-a';await h.window.AppRuntime.loadReview();const compiling=h.window.AppRuntime.compile();await h.drain();if(pollOptions&&pollOptions.onRetry)pollOptions.onRetry(new Error('offline'));const retryStatus=h.get('#rvStatus').textContent;h.window.StoryStore.set({story_token:'B',project:'B'});const scopeCurrent=Boolean(pollOptions&&pollOptions.isCurrent&&pollOptions.isCurrent());pollResolve();await compiling;console.log(JSON.stringify({hasScope:Boolean(pollOptions&&pollOptions.isCurrent),hasRetry:Boolean(pollOptions&&pollOptions.onRetry),retryStatus,scopeCurrent,jobRequests,install:h.get('#rvInstall').disabled,status:h.get('#rvStatus').textContent}));})();
'''
    result = run_runtime(script)
    assert result["hasScope"] is True
    assert result["hasRetry"] is True
    assert "连接" in result["retryStatus"]
    assert result["scopeCurrent"] is False
    assert result["jobRequests"] == 0
    assert result["install"] is True


@pytest.mark.skip(reason="The legacy combined-modal scenario predates the required AA executable gate.")
def test_browse_and_edit_modals_restore_their_own_triggers_on_every_close_path():
    """Using show() instead of closeModal() loses focus restoration and aria state."""
    script = r'''
const {createHarness}=require(process.argv[1]);const story={story_token:'A',project:'A'};
const h=createHarness({cardList:{renderCardList(_root, cards, options){options.onSelectCard(cards[0]);}},request:async(p)=>{if(p.startsWith('/api/browse'))return {dir:'',dirs:[],files:[]};if(p.startsWith('/api/draft?'))return {story_token:'A',draft_version:1,counts:{pending:0,blocking_errors:0},cards:[{card_id:'card-a',kind:'line',line_no:1,current:{who:'A',text:'text'}}]};if(p==='/api/cards/update')return {ok:true,draft_version:2};return {profiles:[]};}});
(async()=>{h.window.StoryStore.set(story);h.get('#rvDraftSelect').value='draft-a';await h.window.AppRuntime.loadReview();const browseTrigger=h.get('#path'),editTrigger=h.get('#rvEdit');await h.clickAction('open-script',browseTrigger);const browseOpen={on:h.get('#mBrowse').classList.contains('on'),aria:h.get('#mBrowse').getAttribute('aria-hidden'),focus:h.document.activeElement===h.get('#closeBrowse')};h.clickAction('close-browse',h.get('#closeBrowse'));const browseClose={on:h.get('#mBrowse').classList.contains('on'),aria:h.get('#mBrowse').getAttribute('aria-hidden'),focus:h.document.activeElement===browseTrigger};h.clickAction('edit-card',editTrigger);const editOpen={on:h.get('#mEdit').classList.contains('on'),aria:h.get('#mEdit').getAttribute('aria-hidden'),focus:h.document.activeElement===h.get('#closeEdit')};h.clickAction('close-edit',h.get('#closeEdit'));const cancel={on:h.get('#mEdit').classList.contains('on'),aria:h.get('#mEdit').getAttribute('aria-hidden'),focus:h.document.activeElement===editTrigger};h.clickAction('edit-card',editTrigger);h.clickAction('save-edit',h.get('#closeEdit'));await h.drain();const save={on:h.get('#mEdit').classList.contains('on'),aria:h.get('#mEdit').getAttribute('aria-hidden'),focus:h.document.activeElement===editTrigger};await h.clickAction('open-script',browseTrigger);h.clickAction('edit-card',editTrigger);h.document.dispatch('keydown',{key:'Escape'});const firstEscape={browse:h.get('#mBrowse').classList.contains('on'),edit:h.get('#mEdit').classList.contains('on'),focus:h.document.activeElement===editTrigger};h.document.dispatch('keydown',{key:'Escape'});const secondEscape={browse:h.get('#mBrowse').classList.contains('on'),edit:h.get('#mEdit').classList.contains('on'),focus:h.document.activeElement===browseTrigger};console.log(JSON.stringify({browseOpen,browseClose,editOpen,cancel,save,firstEscape,secondEscape}));})();
'''
    result = run_runtime(script)
    assert result == {
        "browseOpen": {"on": True, "aria": "false", "focus": True},
        "browseClose": {"on": False, "aria": "true", "focus": True},
        "editOpen": {"on": True, "aria": "false", "focus": True},
        "cancel": {"on": False, "aria": "true", "focus": True},
        "save": {"on": False, "aria": "true", "focus": True},
        "firstEscape": {"browse": True, "edit": False, "focus": True},
        "secondEscape": {"browse": False, "edit": False, "focus": True},
    }


def test_story_replacement_does_not_treat_the_story_player_element_as_a_player_instance():
    """An element ID becomes window.storyPlayer in browsers and must not crash story replacement."""
    script = r'''
const {createHarness}=require(process.argv[1]);
const h=createHarness({request:async(p)=>{if(p.startsWith('/api/story/assets'))return {characters:[],backgrounds:[],sounds:[],bgms:[],counts:{characters:0,backgrounds:0,sounds:0,bgms:0}};if(p==='/api/drafts')return [];return {profiles:[]};}});
(async()=>{h.window.storyPlayer=h.get('#storyPlayer');const ok=await h.window.replaceStory({story_token:'A',project:'A',source_name:'a.txt'});console.log(JSON.stringify({ok,story:h.window.StoryStore.get()}));})();
'''
    result = run_runtime(script)
    assert result == {"ok": True, "story": {"story_token": "A", "project": "A", "source_name": "a.txt"}}
