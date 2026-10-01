const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
function load(name,ctx={}){
 const start=source.indexOf(`function ${name}(`),end=source.indexOf('\nfunction ',start+10);
 const sandbox={esc:escape,...ctx};vm.createContext(sandbox);vm.runInContext(source.slice(start,end),sandbox);return sandbox[name];
}
const prose=load('agentProseMarkup',{conversationTextMarkup:t=>escape(t).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')});
test('reply paragraphs and lists are real blocks, not a single escaped paragraph',()=>{
 const html=prose('## 转折\n\n第一段。\n\n- **保留**录音\n- 交给同伴\n\n1. 开始\n2. 结束');
 assert.match(html,/<h3>转折<\/h3>/);assert.match(html,/<p>第一段。<\/p>/);
 assert.match(html,/<ul><li><strong>保留<\/strong>录音<\/li>/);assert.match(html,/<ol><li>开始<\/li><li>结束<\/li><\/ol>/);
});
test('model HTML and fenced code cannot create active elements',()=>{
 const html=prose('<img src=x onerror=alert(1)>\n\n```html\n<script>alert(1)</script>\n```\n\n`**literal**`');
 assert.doesNotMatch(html,/<(?:img|script)\b/);assert.match(html,/&lt;img/);assert.match(html,/<pre><code>&lt;script/);assert.match(html,/<code>\*\*literal\*\*<\/code>/);
});
test('unfinished fences and CRLF do not lose text',()=>{
 assert.match(prose('第一段\r\n\r\n```\r\nconst x=1'),/<pre><code>const x=1<\/code><\/pre>/);
});
const tools=load('workAgentInlineToolsMarkup',{
 agentToolLabel:t=>t,agentRunElapsedLabel:()=> '2 秒',agentUsageMarkup:()=>'',agentObservedUsage:()=>({}),agentRequestUsageMarkup:()=>''
});
test('each tool row has a stable disclosure id and explicit status',()=>{
 const html=tools([{tool:'read',label:'读取人物卡',status:'succeeded'},{tool:'draft',status:'failed',error:{message:'<bad>'}}],{id:'message-1'},{id:'run-1'},'已核对');
 assert.match(html,/data-agent-disclosure="tool:message-1:0"/);assert.match(html,/data-agent-disclosure="tool:message-1:1"/);
 assert.match(html,/已完成/);assert.match(html,/&lt;bad&gt;/);assert.match(html,/本轮用时 2 秒/);
 assert.doesNotMatch(html,/details[^>]+ open/);
});
test('missing tool status is not presented as successful',()=>{
 const html=tools([{tool:'read'}],{id:'m'},null);
 assert.match(html,/已记录/);assert.doesNotMatch(html,/已完成/);
});
function surface(messages){
 const state={work:{}};
 return load('renderFinalWorkAgentSurface',{
 state,scenes:()=>[],workAgentActiveRun:()=>null,workConversationThread:()=>({id:'t',title:'创作主对话',messages}),workPlanProposal:()=>null,conversationTaskContract:()=>({}),hcArray:x=>x||[],activeWorkDecision:()=>null,workDecisionDockMarkup:()=>'',workDecisionReopenMarkup:()=>'',isDefaultScriptFormatQuestion:()=>false,conversationHistoryMarkup:()=>'<article>正文</article>',activeAgentRunMarkup:()=>'',workAgentProposalMarkup:()=>'',intentPlansMarkup:()=>'',workUserStatusMarkup:()=>'',agentRuntimeBarMarkup:()=>'<span class="composer-runtime-meta"></span>',renderWorkAgentComposer:()=>'<form id="workConversationForm"></form>'
 })();
}
test('notice-only thread gets the compact empty composition with one composer',()=>{
 const html=surface([{role:'assistant',kind:'notice'}]);
 assert.match(html,/is-empty-thread/);assert.match(html,/新的构思对话/);assert.equal((html.match(/id="workConversationForm"/g)||[]).length,1);
 assert.doesNotMatch(html,/data-section="tasks"/);
});
test('conversation keeps records reachable without duplicating the bottom timeline',()=>{
 const html=surface([{role:'user',kind:'message'}]);
 assert.match(html,/has-conversation/);assert.match(html,/data-section="tasks"/);assert.doesNotMatch(html,/agent-presentation-summary|hc-starters/);
});
test('desktop sidebar has a persistent header toggle and starter prefills emit input',()=>{
 assert.match(surface([{role:'user',kind:'message'}]),/class="agent-sidebar-toggle" data-panel-toggle="tree" aria-controls="worksPanel"/);
 assert.ok(source.includes("input.dispatchEvent(new Event('input',{bubbles:true}))"));
});

test('composer opens a real model picker rather than settings directly',()=>{
 const start=source.indexOf('function renderWorkAgentComposer('),end=source.indexOf('function agentPresentationMarkup',start);
 const composer=source.slice(start,end);
 assert.match(composer,/data-agent-model-picker aria-haspopup="dialog"/);
 assert.match(composer,/aria-label="选择写作模型，当前/);
 assert.doesNotMatch(composer,/agent-model-button" data-action="settings"/);
});
test('quick picker only uses registered settings and a centered SVG caret',()=>{
 const picker=fs.readFileSync(path.join(__dirname,'../web/agent-model-picker.js'),'utf8');
 assert.match(picker,/result\.registered_models/);
 assert.match(picker,/registered_model_id:id/);
 assert.doesNotMatch(picker,/fetch-models/);
 assert.match(source,/<svg class="agent-model-chevron"/);
});
test('conversation rail has an in-place collapse control without losing its icon',()=>{
 assert.match(source,/class="agent-rail-collapse" data-panel-toggle="tree" data-panel-icon aria-controls="worksPanel"/);
 const shell=fs.readFileSync(path.join(__dirname,'../web/shell.js'),'utf8');
 assert.match(shell,/!button\.hasAttribute\("data-panel-icon"\)/);
 assert.match(shell,/root\.querySelector\('\.agent-sidebar-toggle'\)\?\.focus/);
});
test('current work agent surface includes actionable status and runtime context without overflow-prone duplicate rails',()=>{
 const idx=source.indexOf('function renderFinalWorkAgentSurface');
 const renderer=source.slice(idx,source.indexOf('function renderFinalWorkAgentRail',idx));
 assert.match(renderer,/workUserStatusMarkup\(\)/);
 assert.match(renderer,/agentRuntimeBarMarkup\(thread\)/);
 assert.match(renderer,/agent-runtime-bar/);
 assert.match(renderer,/work-agent-bottom/);
});

test('new work entry invites intent in conversation instead of adding a second planning button',()=>{
 const index=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
 assert.match(index,/短篇、长篇、续写、改编/);
 assert.match(index,/Agent 会按类型引导/);
});

test('new work defaults to agent-led ideation instead of opening the outline first',()=>{
 const index=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
 assert.match(index,/接下来先做/);
 assert.match(index,/name="start_at" value="ideation" checked/);
 assert.doesNotMatch(index,/name="start_at" value="outline" checked/);
 assert.match(source,/const destination=fields\.start_at\|\|'ideation'/);
 assert.match(source,/name="start_at" value="ideation" checked/);
});

test('conversation task labels cover non-wizard creation intents',()=>{
 const start=source.indexOf('function userFacingConversationTask(');
 const end=source.indexOf('\n\n/* Final surface overrides',start);
 const sandbox={};vm.createContext(sandbox);vm.runInContext(source.slice(start,end),sandbox);
 const task=sandbox.userFacingConversationTask;
 const expected={
  short_story_ideation:'构思短篇',
  long_form_ideation:'构思长篇',
  continue_existing_draft:'继续已有文章',
  character_relationship_scene:'构思人物关系场景',
  worldbuilding_first:'先整理世界观',
  outline_only:'先整理大纲',
  script_or_scene_first:'先做场景或剧本',
  imported_draft_review:'检查已有文稿',
 };
 for(const [intent,title] of Object.entries(expected)){
  const view=task({id:'brief.build',creation_intent:intent,task_scope:{surface:'work'}});
  assert.equal(view.title,title,intent);
  assert.notEqual(view.subtitle,'从目标、人物、篇幅和限制开始，信息足够时自动整理候选。',intent);
 }
});
