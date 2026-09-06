const DECISION_CUSTOM_OPTION_ID='__custom__';
// Compatibility marker: activation is performed by requestProduction('/activate'),
// after the candidate test has completed; the old two-call flow is intentionally absent.
// await requestProduction('/test')
const state={works:[],work:null,userStatus:null,userStatusVersion:null,userStatusLoading:false,agentPresentation:null,currentProjection:null,currentProjectionVersion:null,currentProjectionLoading:false,releaseDetails:{},releaseDetailLoading:{},releaseDetailErrors:{},capabilities:null,stage:'overview',surface:'works',sceneId:null,context:null,inspector:'agent',mobileView:'writing',writingChapterId:'',libraryView:'overview',libraryEditorOpen:false,showGlobalSurfaces:true,editCardId:'',editCard:null,characterCardDraft:null,characterImportProfile:null,characterImportFileName:'',worldImportProfile:null,worldImportFileName:'',highlightCardId:'',libraryCharacterFilter:'active',libraryQuery:'',librarySourceFilter:'all',libraryStatusFilter:'all',historyCardId:'',editCanonFactId:'',canonHistoryOpen:false,officialReferenceQuery:'',officialReferenceResults:[],officialReferenceSearched:false,officialReferenceLimit:6,worldQuery:'',worldKindFilter:'all',worldSourceFilter:'all',worldStatusFilter:'all',graphFocus:'',graphTypeFilter:'all',editWorldEntry:null,worldCardDraft:null,worldHistoryOpen:false,sceneContextEditorOpen:false,sceneContractOpen:false,manuscriptDirty:false,manuscriptSceneId:'',manuscriptDraftBlocks:null,manuscriptDirtyUrl:'',manuscriptBlockCounter:0,sceneTextSelection:null,sceneDiffSelections:{},structureDraft:null,structureDirty:false,conversationThreadId:'',renamingThreadId:'',workAgentExpanded:false,mobileThreadOpen:false,composerAttachmentIds:[],composerPrefill:'',composerImportMode:'',composerImportId:'',composerImportPreview:null,composerImportStatus:'',composerImportError:'',threadRailQuery:'',threadRailSearchOpen:false,assetSurfaceOpen:false,assetUpload:null,assetCatalog:{scope:'custom',kind:'characters',query:'',items:[],total:0,offset:0,limit:36,hasMore:false,loading:false,error:null,requestId:0},decisionCardDismissedFor:'',decisionCardDockClosed:false,decisionCardWaitingForAgent:false,decisionCardSelections:{},decisionCardCustomDrafts:{},decisionCardSubmitting:false,staleProposalIds:new Set(),firstUseOpen:false,lastError:null,feedbackError:null,sceneRecovery:null};
let lastRenderedSurfaceKey='';

function sceneRecoveryStorageKey(workId=state.work?.id){return workId?`halocue:scene-recovery:${workId}`:''}
function captureSceneRecovery(scene=selectedScene()){
  if(!scene||!state.work)return null;
  const target={work_id:state.work.id,chapter_id:scene.chapter_id,scene_id:scene.id,scene_title:scene.title||'当前场景'};
  state.sceneRecovery=target;
  try{sessionStorage.setItem(sceneRecoveryStorageKey(target.work_id),JSON.stringify(target))}catch(_){/* The in-memory target still supports this session. */}
  return target;
}
function currentSceneRecovery(){
  const current=state.sceneRecovery;
  if(current?.work_id===state.work?.id)return current;
  try{
    const stored=JSON.parse(sessionStorage.getItem(sceneRecoveryStorageKey())||'null');
    if(stored?.work_id===state.work?.id&&stored.scene_id){state.sceneRecovery=stored;return stored}
  }catch(_){/* A malformed browser value must not break the library. */}
  return null;
}
function clearSceneRecovery(){
  const workId=state.sceneRecovery?.work_id||state.work?.id;
  state.sceneRecovery=null;
  try{if(workId)sessionStorage.removeItem(sceneRecoveryStorageKey(workId))}catch(_){/* Best-effort browser cleanup. */}
}
function focusCharacterCardName(){
  requestAnimationFrame(()=>requestAnimationFrame(()=>$('#libraryCharacterForm input[name="name"]')?.focus()));
}
function sceneRecoveryCharacterName(scene=selectedScene()){
  const finding=(state.work?.review_findings||[]).find(item=>item.scene_id===scene?.id&&item.kind==='character_card_missing'&&item.status==='open');
  const candidates=[...(finding?.evidence?.speakers||[]),...(Array.isArray(scene?.contract?.characters)?scene.contract.characters:[])]
    .map(value=>String(value||'').trim()).filter(Boolean);
  const unique=[...new Set(candidates)];
  if(unique.length===1)return unique[0];
  if(unique.length)return '';
  // A title such as "爱丽丝在废弃车站" is only a prefill hint; the user still
  // decides whether to save or confirm the resulting character card.
  const inferred=String(scene?.title||'').trim().match(/^(.{1,24}?)(?:在|与|和|遇到|来到)/)?.[1]?.trim();
  return inferred||'';
}

function providerDisclosure(){
  const provider=state.capabilities?.providers?.[0];
  if(!provider)return '当前 Provider 状态尚未加载。';
  if(provider.is_simulation)return '当前使用明确标注的模拟 Provider，只验证候选与 Diff 流程。';
  return `当前使用已配置的真实 Provider${provider.display_name?`：${provider.display_name}`:''}。`;
}

const ONBOARDING_TOUR_KEY='halocue:onboarding:interface-v2';
let onboardingTourSteps=[];
let onboardingTourIndex=0;

function onboardingSteps(){
  if(!state.work){
    return [
      {selector:'.intent-start',title:'从一句想法开始',body:'不用先理解作品结构。先说你想写什么，系统会带你进入讨论。'},
      {selector:'#intentMessage',title:'把想法写在这里',body:'一句话就可以。之后还能继续补充、反悔或换方向。'},
      {selector:'[data-intent-submit]',title:'先开始讨论',body:'这里不会直接生成正式正文；Agent 会先与你讨论，并把需要确认的内容交给你决定。'},
      {selector:'.primary-nav [data-section="writing"]',title:'写作',body:'方向确认后，在这里安排章节、场景并逐场审查正文。'},
      {selector:'.primary-nav [data-section="production"]',title:'AA 制作',body:'只有正式发布后的剧本才会进入这里，不会跳过前面的确认。'},
    ];
  }
  if(state.surface==='writing'&&state.stage==='draft'){
    return [
      {selector:'.scene-head',title:'先认准当前场景',body:'这里告诉你正在写哪一场。下面的正文、候选和 Agent 都只服务这一场。'},
      {selector:'.manuscript-desk, .scene-diff-desk',title:pendingProposal()?'在上下文里审查候选':'阅读和编辑正文',body:pendingProposal()?'先读完整正文，再勾选想要的改动；红色表示删除，绿色表示新增。点击应用后才会建立新正文。':'正文按段落阅读。点击文字即可编辑；保存会建立新的正文版本，历史不会被覆盖。'},
      {selector:'[data-scene-change]',title:'选择要应用的变化',body:'可以只勾选其中几项。未勾选的句子会继续保留当前版本。'},
      {selector:'.inspector-tabs [data-inspector="context"]',title:'上下文只回答“依据什么写”',body:'这里可以查看本场会读取的资料。它是参考范围，不是需要你逐项操作的表单。'},
      {selector:'.inspector-tabs [data-inspector="agent"]',title:'Agent 只负责讨论和提案',body:'把想法说给 Agent。Agent 只能产生候选，不能越过你的决定直接改正文。'},
      {selector:'.scene-conversation-composer',title:'从这里继续对话',body:'先输入要求并发送。等你确认后，再点击“形成正文候选”；候选会回到正文区审查。'},
      {selector:'.primary-nav [data-section="production"]',title:'AA 制作',body:'完成场景、连续性和发布检查后，再从这里把正式发布版本交给制作。'},
    ];
  }
  return [
    {selector:'.primary-nav [data-section="works"]',title:'作品',body:'在这里和作品 Agent 讨论整部故事，并确认方向、人物和结构候选。'},
    {selector:'.work-agent-rail',title:'创作对话',body:'每段对话独立保存。可以新建对话，也可以回到较早讨论。'},
    {selector:'.work-agent-thread',title:'聊天与候选',body:'Agent 的回复、需要确认的候选和真正的异常都会出现在这里。普通运行细节不会打扰你。'},
    {selector:'.official-script-candidate',title:'正文候选不是聊天文案',body:'这种独立框表示 Agent 已写出一份正文候选，但尚未写入。点击按钮后到写作页结合上下文审查。'},
    {selector:'#workConversationForm',title:'继续和 Agent 说话',body:'像正常聊天一样补充要求。聊天不会直接覆盖正式作品。'},
    {selector:'#workConversationForm .permission-menu',title:'审核协作',body:'决定正式修改如何落地。默认会把修改交给你审查；核心设定、发布和制作交接始终需要确认。'},
    {selector:'#workConversationForm .attachment-menu',title:'添加参考材料',body:'图片或文档只作为当前讨论的输入，不会自动登记成正式资料或修改正文。'},
    {selector:'.primary-nav [data-section="writing"]',title:'写作',body:'方向确认后，在这里安排章节、选择场景、审查正文候选。'},
    {selector:'.primary-nav [data-section="production"]',title:'AA 制作',body:'冻结发布后从这里进入制作；未确认的候选不会被交给 AA。'},
  ];
}

function onboardingOverlay(){
  let root=$('#onboardingTour');
  if(root)return root;
  root=document.createElement('div');
  root.id='onboardingTour';
  root.className='onboarding-tour';
  root.hidden=true;
  root.innerHTML=`<div class="onboarding-highlight" aria-hidden="true"></div><section class="onboarding-coach" role="dialog" aria-modal="true" aria-labelledby="onboardingTitle"><span data-onboarding-count></span><h2 id="onboardingTitle" data-onboarding-title></h2><p data-onboarding-body></p><div class="onboarding-actions"><button type="button" class="quiet" data-onboarding-skip>跳过</button><button type="button" class="primary" data-onboarding-next>下一步</button></div></section>`;
  root.addEventListener('click',event=>{
    const control=event.target?.closest?.('[data-onboarding-next],[data-onboarding-skip]');
    if(!control)return;
    event.preventDefault();
    if(control.matches('[data-onboarding-skip]')){finishOnboardingTour();return}
    onboardingTourIndex+=1;
    if(onboardingTourIndex>=onboardingTourSteps.length)finishOnboardingTour();
    else positionOnboardingStep();
  });
  root.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();finishOnboardingTour();return}
    if(event.key==='Enter'&&event.target?.matches?.('[data-onboarding-next]')){
      event.preventDefault();
      onboardingTourIndex+=1;
      if(onboardingTourIndex>=onboardingTourSteps.length)finishOnboardingTour();
      else positionOnboardingStep();
    }
  });
  document.body.append(root);
  return root;
}

function positionOnboardingStep(){
  const root=$('#onboardingTour');
  if(!root||root.hidden)return;
  const step=onboardingTourSteps[onboardingTourIndex],target=step&&$(step.selector);
  if(!target||!target.getClientRects().length){
    onboardingTourIndex+=1;
    if(onboardingTourIndex>=onboardingTourSteps.length){finishOnboardingTour();return}
    positionOnboardingStep();return;
  }
  target.scrollIntoView({block:'nearest',inline:'nearest'});
  const rect=target.getBoundingClientRect(),highlight=root.querySelector('.onboarding-highlight'),coach=root.querySelector('.onboarding-coach');
  const pad=7;
  const highlightTop=Math.max(6,rect.top-pad),highlightLeft=Math.max(6,rect.left-pad);
  Object.assign(highlight.style,{left:`${highlightLeft}px`,top:`${highlightTop}px`,width:`${Math.min(innerWidth-highlightLeft-6,rect.width+pad*2)}px`,height:`${Math.min(innerHeight-highlightTop-6,rect.height+pad*2)}px`});
  root.querySelector('[data-onboarding-count]').textContent=`${onboardingTourIndex+1} / ${onboardingTourSteps.length}`;
  root.querySelector('[data-onboarding-title]').textContent=step.title;
  root.querySelector('[data-onboarding-body]').textContent=step.body;
  const coachWidth=Math.min(340,innerWidth-24),below=rect.bottom+14,above=rect.top-coach.offsetHeight-14;
  const top=below+coach.offsetHeight<=innerHeight-12?below:Math.max(12,above);
  const left=Math.min(innerWidth-coachWidth-12,Math.max(12,rect.left));
  Object.assign(coach.style,{width:`${coachWidth}px`,left:`${left}px`,top:`${top}px`});
  const next=root.querySelector('[data-onboarding-next]');
  next.textContent=onboardingTourIndex===onboardingTourSteps.length-1?'完成':'下一步';
  next.focus({preventScroll:true});
}

function startOnboardingTour(force=false){
  if(!force){try{if(localStorage.getItem(ONBOARDING_TOUR_KEY))return}catch(_){/* Continue without persistence. */}}
  onboardingTourSteps=onboardingSteps().filter(step=>$(step.selector)?.getClientRects().length);
  if(!onboardingTourSteps.length)return;
  onboardingTourIndex=0;
  const root=onboardingOverlay();
  root.hidden=false;
  document.body.classList.add('onboarding-open');
  requestAnimationFrame(positionOnboardingStep);
}

function finishOnboardingTour(){
  const root=$('#onboardingTour');
  if(root)root.hidden=true;
  document.body.classList.remove('onboarding-open');
  try{localStorage.setItem(ONBOARDING_TOUR_KEY,'completed')}catch(_){/* The guide still works for this session. */}
}

window.addEventListener('resize',()=>requestAnimationFrame(positionOnboardingStep));
window.addEventListener('scroll',()=>requestAnimationFrame(positionOnboardingStep),true);
document.addEventListener('click',event=>{
  const start=event.target.closest('[data-onboarding-start]');
  if(start){event.preventDefault();$('#settingsDialog')?.close();setTimeout(()=>startOnboardingTour(true),80);return}
},true);

let pendingManuscriptNavigation=null;
let writingTargetSavePromise=Promise.resolve();
let workDialogOpener=null;

function intentComposerMarkup(){
  return `<section class="intent-start" aria-labelledby="intentStartTitle"><div class="intent-start-copy"><p class="eyebrow">第一次使用</p><h2 id="intentStartTitle">先说一句你想写的故事</h2><p>不用先填作品名、方向或章节。你可以随时补充或反悔，正式内容只会在你确认后保存。</p><p class="first-use-guide" aria-label="第一次使用流程"><span>1 说想法</span><span>2 和 Agent 讨论</span><span>3 你确认后再写第一场</span></p></div><form id="intentForm" class="intent-composer"><label for="intentMessage" class="sr-only">告诉 HaloCue 你想创作什么</label><textarea id="intentMessage" name="message" required maxlength="4000" placeholder="例如：我想写一个爱丽丝在废弃车站遇到老师的短篇同人故事，先从第一幕开始。"></textarea><div class="intent-composer-meta"><span>聊天不会直接改动正式作品。</span><button type="button" class="quiet" data-intent-clarify>帮我说清楚</button></div><div class="intent-clarify-preview" data-intent-clarify-preview hidden></div><div class="intent-composer-actions"><label class="intent-attachment"><input id="intentAttachment" type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,.txt,.md,.pdf,.docx"><span>添加附件</span></label><button type="submit" class="primary" data-intent-submit>开始讨论</button></div></form><div class="intent-import-entry"><span>已经有文稿？</span><button type="button" class="quiet" data-aap-import>导入已有内容</button></div><p class="intent-start-note">没有作品时会自动创建；已有作品会继续当前讨论。</p></section>`;
}

function firstUseFormMarkup(){
  return `<section class="first-use-form" aria-labelledby="firstUseTitle"><div class="first-use-form-head"><p class="eyebrow">NEW WORK</p><h3 id="firstUseTitle">开始一个新故事</h3><p>先保存一句想法。它会进入后续讨论，不会自动变成正式设定。</p></div><form id="firstWorkForm"><label class="new-work-idea">先说一句你想看的故事<textarea name="idea" required maxlength="600" placeholder="例如：爱丽丝和凯伊发现一台只在深夜回应的旧机器。"></textarea><small>建立后会直接进入多轮讨论。</small></label><label>作品名称（可选）<input name="title" maxlength="80" placeholder="留空时会从想法生成临时名称"></label><fieldset class="world-seed-picker"><legend>世界观底稿</legend><label class="world-seed-option"><input type="radio" name="world_seed" value="ba_starter" checked><span><b>从 BA 世界观开始</b><small>创建可编辑的 BA 设定库，条目先标为待核对。</small></span></label><label class="world-seed-option"><input type="radio" name="world_seed" value="blank"><span><b>从原创世界开始</b><small>建立空白资料库，之后自行添加人物、地点、组织与规则。</small></span></label></fieldset><div class="actions first-use-form-actions"><button type="button" class="quiet" data-close-work-dialog>取消</button><button type="submit" data-submit="work" class="primary">建立作品</button></div></form></section>`;
}

function bindFirstUseForm(root){
  const form=root.querySelector('#firstWorkForm');
  if(!form)return;
  form.addEventListener('submit',event=>{
    event.preventDefault();
    event.stopPropagation();
    void submitWorkDialog(form);
  });
  form.querySelector('[data-submit="work"]')?.addEventListener('click',event=>{
    event.preventDefault();
    event.stopPropagation();
    void submitWorkDialog(form);
  });
}

async function readIntentAttachments(input){
  const files=[...(input?.files||[])].slice(0,4);
  return Promise.all(files.map(file=>new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve({filename:file.name,media_type:file.type,content_base64:String(reader.result).split(',')[1]||''});
    reader.onerror=()=>reject(new Error(`无法读取附件：${file.name}`));
    reader.readAsDataURL(file);
  })));
}

let aapImportState = null;

function aapImportDialog(){
  let dialog = document.getElementById('aapImportDialog');
  if(dialog)return dialog;
  dialog=document.createElement('dialog');
  dialog.id='aapImportDialog';
  dialog.className='aap-import-dialog';
  document.body.append(dialog);
  return dialog;
}

function renderAapImportDialog(){
  const dialog=aapImportDialog(),flow=aapImportState||{};
  const preview=flow.preview;
  const isAap=preview?.source_type==='aap';
  const suggestions=preview?(preview.warnings||preview.repair_suggestions||[]):[];
  const units=preview?(isAap?`${preview.counts.scenes} 场 · ${preview.counts.lines} 行`:`${preview.counts.chapters} 章 · ${preview.counts.scenes} 场 · ${preview.counts.paragraphs} 段`):'';
  const people=preview?(isAap?`${preview.counts.characters} 位角色 · ${preview.counts.backgrounds} 个背景`:`${preview.counts.characters} 位角色 · ${preview.counts.dialogues} 段对白`):'';
  dialog.innerHTML=`<header><div><p class="eyebrow">导入已有内容</p><h2>先检查，再交给 Agent</h2><p>TXT、DOCX 和 .aap 会先检查结构，再加入当前作品的 Agent 对话。Agent 只会提出剧本候选，正式正文仍需你确认。</p></div><button type="button" class="icon-button" data-aap-close aria-label="关闭导入">×</button></header>
    <section class="aap-import-file"><label class="aap-import-drop"><input type="file" accept=".txt,text/plain,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.aap,application/json" data-aap-file><b>${flow.filename||'选择 TXT、DOCX 或 .aap'}</b><span>文稿最大 16 MB，AA 工程最大 32 MB</span></label></section>
    ${flow.error?`<p class="aap-import-error" role="alert">${esc(flow.error)}</p>`:''}
    ${preview?`<section class="aap-import-preview" aria-live="polite"><div class="aap-import-summary"><div><span>${isAap?'工程':'文稿'}</span><b>${esc(preview.project_title)}</b></div><div><span>识别到</span><b>${units}</b></div><div><span>${isAap?'角色与资源':'正文内容'}</span><b>${people}</b></div></div><h3>导入前预览</h3><ul class="aap-import-scenes">${(preview.scenes||[]).slice(0,12).map(scene=>`<li><b>${esc(scene.title)}</b><span>${scene.line_count??scene.paragraph_count??0} ${isAap?'行':'段'}</span></li>`).join('')||'<li>没有识别到场景</li>'}</ul>${suggestions.length?`<details class="aap-import-warnings"><summary>${suggestions.length} 项需要确认</summary><ul>${suggestions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></details>`:'<p class="aap-import-ok">没有发现需要人工补充的结构提示。</p>'}<details class="aap-import-boundary"><summary>导入边界</summary><p>确认后会保留原文件和解析预览，并把文件加入当前 Agent 对话。不会自动发送，也不会静默修改正式作品、正文、资料或发布版本。</p></details></section>`:''}
    <footer class="aap-import-actions"><button type="button" class="quiet" data-aap-close>取消</button>${preview?`<button type="button" class="primary" data-aap-confirm ${flow.staging?'disabled':''}>${flow.staging?'正在加入 Agent':'交给 Agent 转换'}</button>`:''}</footer>`;
  if(!dialog.open)dialog.showModal();
}

async function readAapImportFile(file){
  if(!file)return;
  aapImportState={filename:file.name,preview:null,error:'',staging:false};
  renderAapImportDialog();
  try{
    const suffix=file.name.toLowerCase().split('.').pop();
    if(!['aap','txt','docx'].includes(suffix))throw new Error('请选择 TXT、DOCX 或 .aap 文件。');
    const isAap=suffix==='aap';
    if(file.size>(isAap?32000000:16000000))throw new Error(isAap?'.aap 文件不能超过 32 MB。':'文稿不能超过 16 MB。');
    const payload={filename:file.name,content_base64:characterImportBase64(await file.arrayBuffer())};
    aapImportState.payload=payload;
    aapImportState.importKind=isAap?'aap':'story';
    aapImportState.preview=await api(`/imports/${aapImportState.importKind}:preview`,{method:'POST',body:JSON.stringify(payload)});
  }catch(error){aapImportState.error=error.message||'无法读取导入文件。'}
  renderAapImportDialog();
}

function openAapImportDialog(){aapImportState=null;renderAapImportDialog()}

function importAttachmentMediaType(filename){
  const suffix=String(filename||'').toLowerCase().split('.').pop();
  return ({aap:'application/json',txt:'text/plain',md:'text/markdown',pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})[suffix]||'application/octet-stream';
}

async function handoffImportToAgent(flow){
  const title=String(flow.filename||'导入作品').replace(/\.[^.]+$/,'').trim()||'导入作品';
  const importMode=flow.importKind==='aap'?'aap_to_script':'story_to_script';
  if(!state.work){
    const created=await api('/works',{method:'POST',body:JSON.stringify({title,world_seed:'blank'})});
    state.work=created;
    state.works=[created,...(state.works||[]).filter(item=>item.id!==created.id)];
  }
  let thread=workConversationThread();
  if(!thread)throw new Error('当前作品没有可用的 Agent 对话，请重新打开作品后重试。');
  let attachment=flow.attachmentId?{attachment_id:flow.attachmentId,work:state.work}:null;
  if(!attachment){
    attachment=await api(`/works/${state.work.id}/threads/${thread.id}/attachments`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,filename:flow.payload.filename,media_type:importAttachmentMediaType(flow.payload.filename),content_base64:flow.payload.content_base64,import_id:flow.stageResult?.import_id||null})});
    flow.attachmentId=attachment.attachment_id;
  }
  state.work=attachment.work;
  state.composerAttachmentIds=[attachment.attachment_id];
  state.composerImportMode=importMode;
  state.composerImportId=flow.stageResult?.import_id||'';
  state.composerImportPreview=flow.preview?{source_type:flow.preview.source_type,project_title:flow.preview.project_title,counts:flow.preview.counts,scenes:(flow.preview.scenes||[]).slice(0,12).map(scene=>({title:scene.title,line_count:scene.line_count,paragraph_count:scene.paragraph_count})),warnings:(flow.preview.warnings||flow.preview.repair_suggestions||[]).slice(0,12)}:null;
  state.composerImportStatus='attached';
  state.composerImportError='';
  state.composerPrefill=`导入任务：${importMode}\n请读取刚加入的文件，并先给出一份可审查的剧本转换候选。\n必须整理：章节、场景、人物映射、对白、旁白、舞台动作；同时列出无法识别的节点、需要人工补充的内容和来源片段。\n只生成 Proposal，不直接修改正式正文、人物卡、世界观或发布版本；等我审查后再决定下一步。`;
  state.surface='works';state.mobileView='writing';state.stage='overview';state.inspector='agent';
  render();
  requestAnimationFrame(()=>document.querySelector('#workConversationForm textarea')?.focus());
  toast('导入文件已加入 Agent，对话框中已经预填转换要求；点击发送后才会调用模型。');
}

async function confirmAapImport(){
  const flow=aapImportState;if(!flow?.preview||flow.staging)return;
  flow.staging=true;renderAapImportDialog();
  try{
    if(!flow.stageResult){
      flow.stageResult=await api(`/imports/${flow.importKind||'aap'}:stage`,{method:'POST',body:JSON.stringify({...flow.payload,confirm:true,idempotency_key:flow.idempotencyKey||(flow.idempotencyKey=globalThis.crypto?.randomUUID?.()||`import-${Date.now()}-${Math.random().toString(16).slice(2)}`)})});
    }
    await handoffImportToAgent(flow);
    aapImportState=null;aapImportDialog().close();
  }catch(error){flow.staging=false;flow.error=error.message||'导入文件加入 Agent 失败。';state.composerImportStatus='failed';state.composerImportError=flow.error;renderAapImportDialog()}
}

window.addEventListener('click',event=>{
  const open=event.target.closest?.('[data-aap-import],[data-open-import-dialog]');
  if(open){event.preventDefault();event.stopImmediatePropagation();open.closest('details')?.removeAttribute('open');openAapImportDialog();return}
  const close=event.target.closest?.('[data-aap-close]');
  if(close){event.preventDefault();event.stopImmediatePropagation();aapImportDialog().close();aapImportState=null;return}
  const confirm=event.target.closest?.('[data-aap-confirm]');
  if(confirm){event.preventDefault();event.stopImmediatePropagation();void confirmAapImport()}
  const retry=event.target.closest?.('[data-import-retry]');
  if(retry&&aapImportState){event.preventDefault();event.stopImmediatePropagation();void confirmAapImport()}
},true);
document.addEventListener('change',event=>{if(event.target.matches?.('[data-aap-file]'))void readAapImportFile(event.target.files?.[0])},true);

function showIntentClarifyPreview(form){
  const input=form?.querySelector('textarea[name="message"]'),preview=form?.querySelector('[data-intent-clarify-preview]');
  if(!input||!preview)return;
  const original=input.value.trim();
  if(!original){input.focus();return}
  const optimized=`请围绕以下创作意图先建立可恢复的作品骨架，读取相关正式资料，明确目标范围与关键不确定项，再从用户指定的章节或场景开始：\n\n${original}`;
  preview.hidden=false;
  preview.innerHTML=`<b>整理后的表达</b><p>${esc(optimized)}</p><div><button type="button" class="quiet" data-intent-use-optimized>使用优化表达</button><button type="button" class="quiet" data-intent-use-original>发送原文</button></div>`;
  preview.dataset.optimized=optimized;
}

function useIntentExpression(form,use){
  const input=form?.querySelector('textarea[name="message"]'),preview=form?.querySelector('[data-intent-clarify-preview]');
  if(input&&preview){if(use.hasAttribute('data-intent-use-optimized'))input.value=preview.dataset.optimized||input.value;preview.hidden=true;input.focus();input.setSelectionRange(input.value.length,input.value.length)}
}

async function submitIntent(form){
  const submit=form.querySelector('[data-intent-submit]'),message=String(form.elements.message?.value||'').trim();
  if(!message||form.dataset.submitting==='true')return;
  form.dataset.submitting='true';if(submit)submit.disabled=true;
  try{
    setBusy('正在准备作品与创作范围');
    const attachments=await readIntentAttachments(form.querySelector('#intentAttachment'));
    const result=await api('/intent',{method:'POST',body:JSON.stringify({message,work_id:state.work?.id||null,attachments,idempotency_key:globalThis.crypto?.randomUUID?.()||`intent-${Date.now()}-${Math.random().toString(16).slice(2)}`})});
    state.work=result.work;state.works=state.works.filter(item=>item.id!==result.work_id);state.works.unshift(result.work);state.stage='overview';state.surface='works';state.mobileView='writing';state.inspector='agent';state.conversationThreadId=result.thread_id;state.activeAgentRunId=result.result?.agent_run_id||'';
    setBusy(result.requires_confirmation?'等待你的确认':result.status==='running'?'创作 Agent 正在处理':'创作计划已保存');
    toast(result.requires_confirmation?'这条请求涉及高风险操作，请先确认':'已开始自然语言创作');
    render();
    if(result.result?.agent_run_id)scheduleAgentRunPoll(result.result.agent_run_id,0);
  }catch(error){setBusy('自然语言请求未生效');toast(error.message,true)}finally{delete form.dataset.submitting;if(submit)submit.disabled=false}
}

async function openIntentTarget(button){
  if(!state.work)return;
  const scene=scenes().find(item=>item.id===button.dataset.intentOpenScene);
  if(!scene){toast('目标场景已经变化，请重新加载作品。',true);return}
  const chapter=state.work.chapters.find(item=>item.id===scene.chapter_id);
  try{
    button.disabled=true;
    if(chapter)await persistWritingTarget(chapter.id,scene.id);
    state.writingChapterId=chapter?.id||scene.chapter_id;
    state.sceneId=scene.id;state.context=null;state.inspector='agent';state.surface='writing';state.mobileView='writing';
    const targetStage=stageGate('draft').allowed?'draft':'structure';
    const targetUrl=`?section=writing&work_id=${encodeURIComponent(state.work.id)}&stage=${targetStage}&chapter_id=${encodeURIComponent(chapter?.id||scene.chapter_id)}&scene_id=${encodeURIComponent(scene.id)}`;
    // Commit the same URL that the card advertises before rendering. The
    // writing shell owns URL synchronization and otherwise may replace this
    // transition with the previous Works overview during its render pass.
    state.stage=targetStage==='draft'&&stageGate('draft').allowed?'draft':'structure';
    if(targetUrl&&`${location.pathname}${location.search}`!==targetUrl){
      history.pushState({halocue:true},'',targetUrl);
    }
    render();
    toast(`已跳转到《${scene.title}》`);
  }catch(error){button.disabled=false;toast(error.message,true)}
}

function bindIntentComposer(root){
  const form=root.querySelector('#intentForm');
  if(!form)return;
  form.dataset.intentBound='true';
  form.querySelector('[data-intent-clarify]')?.addEventListener('click',event=>{
    event.preventDefault();
    showIntentClarifyPreview(form);
  });
  form.querySelector('[data-intent-clarify-preview]')?.addEventListener('click',event=>{
    const use=event.target.closest('[data-intent-use-optimized],[data-intent-use-original]');
    if(!use)return;
    event.preventDefault();
    useIntentExpression(form,use);
  });
  form.addEventListener('submit',event=>{
    event.preventDefault();
    event.stopPropagation();
    void submitIntent(form);
  });
}

// The empty-work composer is the first action a new user sees. Keep its
// clarification controls above the legacy delegated click graph so a later
// surface listener cannot turn them into a silent no-op.
window.addEventListener('click',event=>{
  const target=event.target instanceof Element?event.target:null;
  const clarify=target?.closest('[data-intent-clarify]');
  const choice=target?.closest('[data-intent-use-optimized],[data-intent-use-original]');
  if(!clarify&&!choice)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const form=(clarify||choice)?.closest('form')||document.querySelector('#intentForm');
  if(clarify){showIntentClarifyPreview(form);return}
  useIntentExpression(form,choice);
},true);

// The legacy delegated click graph predates the natural-language composer.
// Capture the primary first-use action as well, so an empty workspace cannot
// leave a valid request looking clickable while its submit event is swallowed.
window.addEventListener('click',event=>{
  const target=event.target instanceof Element?event.target:null;
  const submit=target?.closest('[data-intent-submit]');
  if(!submit)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  void submitIntent(submit.closest('form')||document.querySelector('#intentForm'));
},true);

// Handle the inline first-use controls before the larger delegated click graph.
// This keeps the first-use path independent from later presentation listeners.
window.addEventListener('click',event=>{
  const target=event.target instanceof Element?event.target:null;
  const close=target?.closest('[data-close-work-dialog]');
  if(close){event.preventDefault();event.stopImmediatePropagation();closeWorkDialog();return}
  const submit=target?.closest('#firstWorkForm [data-submit="work"]');
  if(submit){event.preventDefault();event.stopImmediatePropagation();void submitWorkDialog(submit.form);}
},true);

function openWorkDialog(opener=document.activeElement){
  const dialog=document.getElementById('workDialog');
  if(!state.work){
    if(state.firstUseOpen)return;
    workDialogOpener=opener&&typeof opener.focus==='function'?opener:null;
    state.firstUseOpen=true;
    render();
    queueMicrotask(()=>document.querySelector('#firstWorkForm textarea[name="idea"]')?.focus());
    return;
  }
  if(!dialog||!dialog.hidden)return;
  const switchDialog=document.getElementById('workSwitchDialog');
  if(switchDialog?.open)switchDialog.close();
  workDialogOpener=opener&&typeof opener.focus==='function'?opener:null;
  document.getElementById('app')?.setAttribute('inert','');
  document.body.classList.add('work-dialog-open');
  dialog.hidden=false;
  queueMicrotask(()=>dialog.querySelector('textarea[name="idea"]')?.focus());
}

function closeWorkDialog(){
  if(state.firstUseOpen){
    state.firstUseOpen=false;
    render();
    const fallback=document.querySelector('[data-action="new-work"]:not([hidden])');
    const target=workDialogOpener?.isConnected?workDialogOpener:fallback;
    workDialogOpener=null;
    queueMicrotask(()=>target?.focus());
    return;
  }
  const dialog=document.getElementById('workDialog');
  if(dialog&&!dialog.hidden)dialog.hidden=true;
  document.getElementById('app')?.removeAttribute('inert');
  document.body.classList.remove('work-dialog-open');
  const fallback=document.querySelector('[data-action="new-work"]:not([hidden])');
  const target=workDialogOpener?.isConnected?workDialogOpener:fallback;
  workDialogOpener=null;
  queueMicrotask(()=>target?.focus());
}

async function submitWorkDialog(form){
  if(!form||form.dataset.submitting==='true')return;
  if(typeof form.reportValidity==='function'&&!form.reportValidity())return;
  const submit=form.querySelector('[data-submit="work"]');
  form.dataset.submitting='true';
  if(submit)submit.disabled=true;
  try{
    const work=await api('/works',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});
    state.works.unshift(work);state.work=work;state.stage='brief';state.inspector='agent';closeWorkDialog();form.reset();toast('作品骨架与创作主对话已保存');render();
  }catch(error){toast(error.message,true)}finally{delete form.dataset.submitting;if(submit)submit.disabled=false}
}

document.querySelector('#workForm [data-submit="work"]')?.addEventListener('click',event=>{
  event.preventDefault();
  void submitWorkDialog(document.getElementById('workForm'));
});

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||document.getElementById('workDialog')?.hidden!==false)return;
  event.preventDefault();event.stopImmediatePropagation();closeWorkDialog();
},true);

function discardManuscriptDraft(){
  state.manuscriptDirty=false;
  state.manuscriptDraftBlocks=null;
  state.manuscriptDirtyUrl='';
  const badge=document.getElementById('manuscriptSaveState');
  if(badge){badge.textContent='已保存';badge.className='manuscript-state saved'}
}

function manuscriptNavigationControl(target){
  if(!(target instanceof Element))return null;
  const control=target.closest('[data-select-work],[data-scene],[data-scene-open],[data-writing-chapter],[data-memory-open-scene],[data-section],[data-stage],[data-stage-jump],[data-mobile],[data-work-surface],[data-agent-open-library],[data-open-production]');
  if(!control)return null;
  const sceneId=control.dataset.scene||control.dataset.sceneOpen||control.dataset.memoryOpenScene;
  if(sceneId&&sceneId===state.manuscriptSceneId&&state.stage==='draft')return null;
  if(control.dataset.writingChapter===state.writingChapterId)return null;
  if((control.dataset.stage||control.dataset.stageJump)==='draft'&&!sceneId&&state.stage==='draft')return null;
  if(control.dataset.mobile==='writing'&&state.stage==='draft')return null;
  if(control.dataset.selectWork===state.work?.id)return null;
  return control;
}

function requestManuscriptNavigation(action){
  const dialog=document.getElementById('unsavedManuscriptDialog');
  if(!dialog){
    if(window.confirm('当前场景有未保存修改。放弃修改并离开吗？')){discardManuscriptDraft();action()}
    return;
  }
  pendingManuscriptNavigation=action;
  if(!dialog.open)dialog.showModal();
  dialog.querySelector('[data-unsaved-manuscript-cancel]')?.focus();
}

function routeKeepsCurrentManuscript(url){
  const params=url.searchParams;
  return params.get('section')==='writing'
    && params.get('stage')==='draft'
    && (!params.get('scene_id')||params.get('scene_id')===state.manuscriptSceneId);
}

function guardManuscriptPopState(event){
  if(!state.manuscriptDirty||routeKeepsCurrentManuscript(new URL(location.href)))return;
  const restoreUrl=state.manuscriptDirtyUrl||`${location.pathname}?section=writing&stage=draft&scene_id=${encodeURIComponent(state.manuscriptSceneId)}`;
  history.pushState({halocue:true},'',restoreUrl);
  event.stopImmediatePropagation();
  requestManuscriptNavigation(()=>history.back());
}

document.addEventListener('click',event=>{
  const target=event.target;
  if(!(target instanceof Element))return;
  if(target.closest('[data-unsaved-manuscript-cancel]')){
    event.preventDefault();pendingManuscriptNavigation=null;document.getElementById('unsavedManuscriptDialog')?.close();return;
  }
  if(target.closest('[data-unsaved-manuscript-discard]')){
    event.preventDefault();const action=pendingManuscriptNavigation;pendingManuscriptNavigation=null;discardManuscriptDraft();document.getElementById('unsavedManuscriptDialog')?.close();action?.();return;
  }
  if(!state.manuscriptDirty)return;
  if(target.closest('[data-action="assemble-context"],[data-action="generate-candidate"],[data-action="review-scene"]')){
    event.preventDefault();event.stopImmediatePropagation();toast('请先保存正文，再运行依赖正式正文的操作',true);return;
  }
  const control=manuscriptNavigationControl(target);
  if(!control)return;
  event.preventDefault();event.stopImmediatePropagation();requestManuscriptNavigation(()=>control.click());
},true);

window.addEventListener('beforeunload',event=>{
  if(!state.manuscriptDirty)return;
  event.preventDefault();event.returnValue='';
});
window.addEventListener('popstate',guardManuscriptPopState);

function resetCharacterImportDialog(){
  state.characterImportProfile=null;state.characterImportFileName='';
  const form=$('#characterImportForm'),preview=$('#characterImportPreview'),error=$('#characterImportError'),submit=form?.querySelector('[type="submit"]');
  form?.reset();if(preview)preview.hidden=true;if(error){error.hidden=true;error.textContent=''}if(submit){submit.disabled=true;submit.textContent='验证通过后导入'}
}

function showCharacterImportError(message){
  state.characterImportProfile=null;
  const error=$('#characterImportError'),preview=$('#characterImportPreview'),submit=$('#characterImportForm [type="submit"]');
  if(error){error.textContent=message;error.hidden=false}if(preview)preview.hidden=true;if(submit)submit.disabled=true;
}

function characterImportBase64(buffer){
  const bytes=new Uint8Array(buffer);let binary='';
  for(let offset=0;offset<bytes.length;offset+=32768)binary+=String.fromCharCode(...bytes.subarray(offset,offset+32768));
  return btoa(binary);
}

function characterImportIssues(items,limit=5){
  if(!items?.length)return'';
  return `<ul>${items.slice(0,limit).map(item=>`<li><code>${esc(item.path||'root')}</code><span>${esc(item.message||item.code)}</span></li>`).join('')}</ul>${items.length>limit?`<small>另有 ${items.length-limit} 项，可修正后重新选择文件。</small>`:''}`;
}

function renderCharacterImportPreview(preview){
  const report=preview.validation_report||{},counts=report.counts||{},valid=report.status==='PASS';
  $('[data-character-import-name]')?.replaceChildren(document.createTextNode(preview.character||'未识别角色'));
  $('[data-character-import-file]')?.replaceChildren(document.createTextNode(`${preview.filename} · ${(Number(preview.byte_size||0)/1024).toFixed(1)} KB`));
  $('[data-character-import-summary]')?.replaceChildren(document.createTextNode(`${counts.voice_examples||0} 条单句 · ${counts.voice_sequences||0} 段连续样本 · ${counts.bidirectional_sequences||0} 段双向承接`));
  const status=$('[data-character-import-status]');if(status){status.textContent=valid?'结构验证通过':'结构验证未通过';status.className=`character-import-status ${valid?'pass':'fail'}`}
  const readiness=$('[data-character-import-readiness]');if(readiness)readiness.innerHTML=`<span class="${report.production_ready?'ready':''}">普通写作<b>${report.production_ready?'可用':'不可用'}</b></span><span class="${report.open_humanness_ready?'ready':''}">开放式人味<b>${report.open_humanness_ready?'就绪':'证据不足'}</b></span><span class="${report.controlled_rewrite_ready?'ready':''}">受控复写<b>${report.controlled_rewrite_ready?'就绪':'证据不足'}</b></span>`;
  const errors=$('[data-character-import-errors]');if(errors){errors.hidden=!report.errors?.length;errors.innerHTML=report.errors?.length?`<b>需要修正</b>${characterImportIssues(report.errors)}`:''}
  const warnings=$('[data-character-import-warnings]');if(warnings){warnings.hidden=!report.warnings?.length;warnings.innerHTML=report.warnings?.length?`<summary>${report.warnings.length} 项提醒，不阻止普通写作导入</summary><div>${characterImportIssues(report.warnings,8)}</div>`:''}
  const fixes=$('[data-character-import-fixes]');if(fixes){fixes.textContent=report.safe_fixes?.length?`已安全清理 ${report.safe_fixes.length} 处引用残留或空白。`:'未修改人物语义或台词。'}
  const submit=$('#characterImportForm [type="submit"]');if(submit){submit.disabled=!valid;submit.textContent=valid?'导入正式人物卡':'验证通过后导入'}
  const previewNode=$('#characterImportPreview');if(previewNode)previewNode.hidden=false;
}

async function loadCharacterImportFile(file){
  if(!file)return;
  if(!file.name.toLocaleLowerCase('zh-CN').endsWith('.json')){showCharacterImportError('请选择 .json 人物卡文件。');return}
  if(file.size>5000000){showCharacterImportError('人物卡超过 5 MB，请确认文件中没有误带大型二进制内容。');return}
  try{
    const submit=$('#characterImportForm [type="submit"]'),error=$('#characterImportError');if(submit){submit.disabled=true;submit.textContent='正在验证'}if(error){error.hidden=true;error.textContent=''}
    const payload={filename:file.name,content_base64:characterImportBase64(await file.arrayBuffer())};
    const preview=await api(`/works/${state.work.id}/character-cards:validate`,{method:'POST',body:JSON.stringify(payload)});
    state.characterImportProfile={payload,preview};state.characterImportFileName=file.name;renderCharacterImportPreview(preview);
  }catch(error){showCharacterImportError(error.message)}
}

function openCharacterImportDialog(){
  if(!state.work){toast('请先选择作品，再导入人物卡。',true);return}
  resetCharacterImportDialog();$('#characterImportDialog')?.showModal();
}

document.addEventListener('click',event=>{
  const open=event.target.closest('[data-import-character]'),close=event.target.closest('[data-close-character-import]');
  if(open){event.preventDefault();event.stopImmediatePropagation();open.closest('details')?.removeAttribute('open');openCharacterImportDialog();return}
  if(close){event.preventDefault();event.stopImmediatePropagation();$('#characterImportDialog')?.close();resetCharacterImportDialog()}
},true);

document.addEventListener('change',event=>{
  if(event.target.id==='characterImportFile')loadCharacterImportFile(event.target.files?.[0]);
},true);

for(const eventName of ['dragenter','dragover'])document.addEventListener(eventName,event=>{
  const zone=event.target.closest('[data-character-import-dropzone]');if(!zone)return;event.preventDefault();zone.classList.add('dragging');
},true);
for(const eventName of ['dragleave','drop'])document.addEventListener(eventName,event=>{
  const zone=event.target.closest('[data-character-import-dropzone]');if(!zone)return;event.preventDefault();zone.classList.remove('dragging');if(eventName==='drop')loadCharacterImportFile(event.dataTransfer?.files?.[0]);
},true);

async function saveLibraryMutation(path,payload,{artifactId=''}){
  const workBefore=state.work;
  const request=version=>api(path,{method:'POST',body:JSON.stringify({...payload,expected_version:version})});
  try{return await request(payload.expected_version)}catch(error){
    if(error.code!=='revision_conflict'||!workBefore?.id)throw error;
    const refreshed=await api(`/works/${workBefore.id}`);
    if(artifactId){
      const previous=workBefore.artifacts?.find(item=>item.id===artifactId);
      const current=refreshed.artifacts?.find(item=>item.id===artifactId);
      if((previous?.current_revision_id||null)!==(current?.current_revision_id||null)){
        state.work=refreshed;
        throw new Error('这份资料在你编辑期间已经有新版本。当前填写内容仍保留在此页，请对照最新内容后再保存。');
      }
    }
    state.work=refreshed;
    return request(refreshed.version);
  }
}

document.addEventListener('submit',event=>{
  if(event.target.id!=='characterImportForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const form=event.target,selection=state.characterImportProfile,submit=form.querySelector('[type="submit"]');
  if(!selection?.preview?.can_import){showCharacterImportError('请先选择并验证一张结构完整的人物卡。');return}
  if(submit)submit.disabled=true;
  (async()=>{try{
    const result=await api(`/works/${state.work.id}/character-cards:import`,{method:'POST',body:JSON.stringify({...selection.payload,expected_version:state.work.version,source_label:String(form.elements.source_label?.value||'用户导入的 BA 正式人物卡').trim()})});
    state.work=result.work;state.libraryView='characters';state.libraryStatusFilter='confirmed';state.librarySourceFilter='official_reference';state.libraryCharacterFilter='active';state.libraryQuery=selection.preview.character;state.highlightCardId=result.card_id;state.editCardId='';state.editCard=null;state.libraryEditorOpen=false;
    $('#characterImportDialog')?.close();resetCharacterImportDialog();toast(result.import_mode==='updated'?`已更新「${selection.preview.character}」的正式人物卡修订。`:`已导入「${selection.preview.character}」，现在可用于受控写作。`);render();
    setTimeout(()=>document.querySelector(`[data-edit-card="${CSS.escape(result.card_id)}"]`)?.scrollIntoView({block:'nearest'}),0);
  }catch(error){showCharacterImportError(error.message)}finally{if(submit&&$('#characterImportDialog')?.open)submit.disabled=!state.characterImportProfile?.preview?.can_import}})();
},true);

// The central scene command must enter the same conversation surface as the
// Agent composer; leaving this action as a silent no-op strands users between
// the manuscript and the only surface that can create a Proposal.
document.addEventListener('click',event=>{
  const button=event.target.closest?.('[data-action="generate-candidate"]');
  if(!button||!state.work||state.stage!=='draft')return;
  event.preventDefault();
  event.stopImmediatePropagation();
  state.inspector='agent';
  state.writingMobileView='agent';
  render();
  requestAnimationFrame(()=>{
    const input=document.querySelector('#sceneConversationForm textarea[name="text"]');
    if(input&&!input.disabled){
      input.focus();
      input.setSelectionRange(input.value.length,input.value.length);
    }
  });
},true);

document.addEventListener('click',event=>{
  const submit=event.target.closest('button[data-submit="work"]');
  if(!submit)return;
  event.preventDefault();
  submitWorkDialog(document.getElementById('workForm'));
});

function resetWorldImportDialog(){
  state.worldImportProfile=null;state.worldImportFileName='';
  const form=$('#worldImportForm'),preview=$('#worldImportPreview'),error=$('#worldImportError'),submit=form?.querySelector('[type="submit"]');
  form?.reset();if(preview)preview.hidden=true;if(error){error.hidden=true;error.textContent=''}if(submit){submit.disabled=true;submit.textContent='验证通过后导入'}
}
function showWorldImportError(message){
  state.worldImportProfile=null;const error=$('#worldImportError'),preview=$('#worldImportPreview'),submit=$('#worldImportForm [type="submit"]');
  if(error){error.textContent=message;error.hidden=false}if(preview)preview.hidden=true;if(submit)submit.disabled=true;
}
function renderWorldImportPreview(preview){
  const report=preview.validation_report||{},counts=report.counts||{},valid=report.status==='PASS';
  $('[data-world-import-title]')?.replaceChildren(document.createTextNode(preview.title||'未识别世界观'));
  $('[data-world-import-file]')?.replaceChildren(document.createTextNode(`${preview.filename} · ${(Number(preview.byte_size||0)/1024).toFixed(1)} KB`));
  $('[data-world-import-summary]')?.replaceChildren(document.createTextNode(`${counts.entities||0} 张卡 · ${counts.rules||0} 条规则 · ${counts.timeline||0} 个时间线事件`));
  const status=$('[data-world-import-status]');if(status){status.textContent=valid?'结构验证通过':'结构验证未通过';status.className=`character-import-status ${valid?'pass':'fail'}`}
  const issues=(items,limit=6)=>items?.length?`<ul>${items.slice(0,limit).map(item=>`<li><code>${esc(item.path||'root')}</code><span>${esc(item.message||item.code)}</span></li>`).join('')}</ul>${items.length>limit?`<small>另有 ${items.length-limit} 项。</small>`:''}`:'';
  const errors=$('[data-world-import-errors]');if(errors){errors.hidden=!report.errors?.length;errors.innerHTML=report.errors?.length?`<b>需要修正</b>${issues(report.errors)}`:''}
  const warnings=$('[data-world-import-warnings]');if(warnings){warnings.hidden=!report.warnings?.length;warnings.innerHTML=report.warnings?.length?`<summary>${report.warnings.length} 项提醒，不阻止导入</summary><div>${issues(report.warnings,8)}</div>`:''}
  const fixes=$('[data-world-import-fixes]');if(fixes)fixes.textContent=report.safe_fixes?.length?`已安全清理 ${report.safe_fixes.length} 处引用残留或空白。`:'未修改世界观语义。';
  const submit=$('#worldImportForm [type="submit"]');if(submit){submit.disabled=!valid;submit.textContent=valid?'导入世界观资料':'验证通过后导入'}
  const previewNode=$('#worldImportPreview');if(previewNode)previewNode.hidden=false;
}
async function loadWorldImportFile(file){
  if(!file)return;if(!file.name.toLocaleLowerCase('zh-CN').endsWith('.json')){showWorldImportError('请选择 .json 世界观卡文件。');return}if(file.size>5000000){showWorldImportError('世界观卡超过 5 MB。');return}
  try{const submit=$('#worldImportForm [type="submit"]'),error=$('#worldImportError');if(submit){submit.disabled=true;submit.textContent='正在验证'}if(error){error.hidden=true;error.textContent=''}const payload={filename:file.name,content_base64:characterImportBase64(await file.arrayBuffer())};const preview=await api(`/works/${state.work.id}/world-bible:validate`,{method:'POST',body:JSON.stringify(payload)});state.worldImportProfile={payload,preview};state.worldImportFileName=file.name;renderWorldImportPreview(preview)}catch(error){showWorldImportError(error.message)}
}
function openWorldImportDialog(){if(!state.work){toast('请先选择作品，再导入世界观卡。',true);return}resetWorldImportDialog();$('#worldImportDialog')?.showModal()}
document.addEventListener('click',event=>{const open=event.target.closest('[data-import-world]'),close=event.target.closest('[data-close-world-import]');if(open){event.preventDefault();event.stopImmediatePropagation();open.closest('details')?.removeAttribute('open');openWorldImportDialog();return}if(close){event.preventDefault();event.stopImmediatePropagation();$('#worldImportDialog')?.close();resetWorldImportDialog()}},true);
document.addEventListener('change',event=>{if(event.target.id==='worldImportFile')loadWorldImportFile(event.target.files?.[0])},true);
for(const eventName of ['dragenter','dragover'])document.addEventListener(eventName,event=>{const zone=event.target.closest('[data-world-import-dropzone]');if(!zone)return;event.preventDefault();zone.classList.add('dragging')},true);
for(const eventName of ['dragleave','drop'])document.addEventListener(eventName,event=>{const zone=event.target.closest('[data-world-import-dropzone]');if(!zone)return;event.preventDefault();zone.classList.remove('dragging');if(eventName==='drop')loadWorldImportFile(event.dataTransfer?.files?.[0])},true);
document.addEventListener('submit',event=>{if(event.target.id!=='worldImportForm')return;event.preventDefault();event.stopImmediatePropagation();const form=event.target,selection=state.worldImportProfile,submit=form.querySelector('[type="submit"]');if(!selection?.preview?.can_import){showWorldImportError('请先选择并验证一份结构完整的世界观资料。');return}if(submit)submit.disabled=true;(async()=>{try{const result=await api(`/works/${state.work.id}/world-bible:import`,{method:'POST',body:JSON.stringify({...selection.payload,expected_version:state.work.version,source_label:String(form.elements.source_label?.value||'用户导入的 BA 世界观卡').trim()})});state.work=result.work;state.libraryView='world';state.worldQuery='';$('#worldImportDialog')?.close();resetWorldImportDialog();toast(result.import_mode==='updated'?'已更新世界观卡修订。':'已导入世界观资料；待核对条目不会进入 Agent。');render()}catch(error){showWorldImportError(error.message)}finally{if(submit&&$('#worldImportDialog')?.open)submit.disabled=!state.worldImportProfile?.preview?.can_import}})()},true);
document.addEventListener('click',event=>{
  const button=event.target.closest('button');
  if(!button)return;
  if(button.tagName==='BUTTON'&&button.dataset.intentOpenScene&&!button.dataset.scene){
    event.preventDefault();
    event.stopImmediatePropagation();
    void openIntentTarget(button);
    return;
  }
  if(button.dataset.section&&button.dataset.section!=='assets')state.assetSurfaceOpen=false;
  if(button.dataset.section==='works'||button.dataset.section==='references'||button.dataset.workSurface&&button.dataset.workSurface!=='writing')state.surface='works';
  if(button.dataset.section==='writing'||button.dataset.workSurface==='writing'||button.dataset.scene||button.dataset.sceneOpen||button.dataset.writingChapter)state.surface='writing';
},true);
document.addEventListener('submit',event=>{if(event.target.id==='workForm')state.surface='works'},true);
document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-mobile]');
  if(!button)return;
  button.closest('.mobile-more-menu')?.removeAttribute('open');
  // The asset catalog is a temporary overlay, not a second mobile section.
  // Leaving it active here made the URL change to writing while the catalog
  // remained rendered underneath.
  state.assetSurfaceOpen=false;
  if(button.dataset.mobile==='works'){
    event.preventDefault();event.stopImmediatePropagation();
    state.mobileView='writing';state.surface='works';state.stage='overview';state.inspector='decision';render();
  }else if(button.dataset.mobile==='references'){
    event.preventDefault();event.stopImmediatePropagation();
    state.mobileView='writing';state.surface='works';state.stage='references';state.libraryView='overview';render();
  }else if(button.dataset.mobile==='writing'){
    event.preventDefault();event.stopImmediatePropagation();
    state.mobileView='writing';state.surface='writing';if(['overview','brief','blueprint','references'].includes(state.stage))state.stage='structure';render();
  }
},true);

document.addEventListener('click',event=>{
  const summary=event.target.closest('.mobile-more-menu > summary');
  if(summary){
    event.preventDefault();
    const menu=summary.parentElement;
    const shouldOpen=!menu.hasAttribute('open');
    setTimeout(()=>menu.toggleAttribute('open',shouldOpen),0);
    return;
  }
  document.querySelectorAll('.mobile-more-menu[open]').forEach(menu=>{
    if(!menu.contains(event.target))menu.removeAttribute('open');
  });
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('.mobile-more-menu button');
  if(button)button.closest('details')?.removeAttribute('open');
},true);

// Agent composers use the common chat convention: Enter submits and
// Shift+Enter inserts a newline. IME composition must never submit early.
document.addEventListener('keydown',event=>{
  const textarea=event.target.closest('#workConversationForm textarea, #mobileWorkConversationForm textarea');
  if(!textarea||event.key!=='Enter'||event.shiftKey||event.isComposing||event.keyCode===229)return;
  event.preventDefault();
  const form=textarea.form;
  if(!textarea.value.trim()||form?.dataset.submitting==='true')return;
  form?.requestSubmit();
},true);

// Decision cards behave like a compact radio group while the Composer is
// covered. Keyboard movement never rebuilds the page, so focus remains stable.
document.addEventListener('keydown',event=>{
  const dock=event.target.closest('.work-decision-dock');
  if(!dock)return;
  if(event.key==='Escape'){
    event.preventDefault();
    dock.querySelector('[data-decision-dismiss]')?.click();
    return;
  }
  const customInput=event.target.closest('[data-decision-custom]');
  if(customInput){
    if(event.key==='Enter'&&!event.isComposing&&event.keyCode!==229){
      event.preventDefault();
      dock.querySelector('[data-submit-decision]')?.click();
    }
    return;
  }
  const option=event.target.closest('[data-decision-option]');
  if(!option)return;
  const key=option.dataset.decisionOption||'';
  const options=[...document.querySelectorAll(`[data-decision-option="${CSS.escape(key)}"]`)];
  const index=options.indexOf(option);
  if(event.key==='ArrowDown'||event.key==='ArrowRight'||event.key==='ArrowUp'||event.key==='ArrowLeft'){
    event.preventDefault();
    const delta=event.key==='ArrowDown'||event.key==='ArrowRight'?1:-1;
    const next=options[(index+delta+options.length)%options.length];
    next?.click();
    return;
  }
  if(event.key==='Enter'){
    event.preventDefault();
    document.querySelector(`[data-submit-decision="${CSS.escape(key)}"]`)?.click();
    return;
  }
},true);

document.addEventListener('input',event=>{
  const customInput=event.target.closest('[data-decision-custom]');
  if(!customInput)return;
  customInput.removeAttribute('aria-invalid');
  const dock=customInput.closest('.work-decision-dock');
  const key=dock?.dataset.decisionKey||'';
  if(key)state.decisionCardCustomDrafts[key]=customInput.value;
  const customSelected=dock?.querySelector(`[data-option-id="${DECISION_CUSTOM_OPTION_ID}"]`)?.getAttribute('aria-checked')==='true';
  const submit=dock?.querySelector('[data-submit-decision]');
  if(submit&&customSelected&&!state.decisionCardSubmitting)submit.disabled=!customInput.value.trim();
},true);

const renderStructureBeforeCompactGuidance=renderStructure;
renderStructure=function(el){
  renderStructureBeforeCompactGuidance(el);
  const inner=$('.workspace-inner',el);if(!inner)return;
  const title=inner.querySelector('h2'),lede=inner.querySelector('.lede');
  if(title)title.textContent='章节与场景';
  if(lede)lede.textContent='选择当前章节，再管理这一章的场景。全作方向、人物和世界观请回到“作品”。';
  inner.querySelector('.structure-scope-note')?.remove();
  const targets=[...inner.querySelectorAll('.writing-target-bar')];
  targets.slice(1).forEach(node=>node.remove());
  targets[0]?.classList.add('writing-target-compact');
  inner.querySelector('[data-structure-add-volume]')?.classList.replace('primary','quiet');
};

function decorateCurrentStepGuidance(){
  if(!state.work||['overview','brief','blueprint','references'].includes(state.stage))return;
  const hints={
    structure:'选择当前章节，并管理本章的场景',
    draft:'选择一个场景，写作并审查候选',
    release:'完成全篇审查，再冻结发布版本',
  };
  const current=$(`[data-stage="${state.stage}"]`);
  const small=current?.querySelector('small');
  if(small)small.textContent=hints[state.stage]||'处理当前任务';
}

const renderBeforeFeedbackAndGuidance=render;
render=function(){renderBeforeFeedbackAndGuidance();decorateCurrentStepGuidance()};

const renderReferencesBeforeWorldImport=renderReferences;
renderReferences=function(el){
  renderReferencesBeforeWorldImport(el);
  if(state.libraryView!=='world')return;
  const actionBar=[...el.querySelectorAll('.asset-primary-actions')].find(node=>node.textContent.includes('世界观卡'));
  if(actionBar&&!actionBar.querySelector('[data-import-world]')){
    const target=actionBar.querySelector('div');
    target?.insertAdjacentHTML('afterbegin','<button class="quiet" type="button" data-import-world>从文件导入</button>');
  }
};

const renderMobileTasksBeforeFeedback=renderMobileTasks;
renderMobileTasks=function(el){
  renderMobileTasksBeforeFeedback(el);
  const actions=el.querySelector('.actions');
  if(actions)actions.insertAdjacentHTML('beforeend','<button class="quiet" type="button" data-action="feedback">反馈问题</button>');
};

function feedbackContext(){
  const chapter=state.work?writingChapter():null,scene=state.work?selectedScene():null;
  return {
    path:location.pathname,
    stage:state.stage,
    mobile_view:state.mobileView,
    work_version:state.work?.version||null,
    chapter_id:chapter?.id||null,
    scene_id:scene?.id||null,
    viewport:{width:window.innerWidth,height:window.innerHeight},
  };
}

function openFeedbackDialog(errorReport=null){
  const form=$('#feedbackForm');
  if(!form)return;
  state.feedbackError=errorReport||null;
  const category=form.elements.category;
  const severity=form.elements.severity;
  const summary=form.elements.summary;
  const details=form.elements.details;
  if(errorReport){
    category.value='runtime_error';
    severity.value=errorReport.status>=500?'blocker':'major';
    summary.value=String(errorReport.code||'系统报错').slice(0,120);
    details.value=`我当时想完成：\n${errorReport.action||'当前页面操作'}\n\n实际发生：\n${errorReport.message||'请求失败'}\n\n错误码：${errorReport.code||'unknown'}\n请求路径：${errorReport.path||location.pathname}`;
  }
  $('#feedbackDialog')?.showModal();
  setTimeout(()=>summary?.focus(),0);
}

document.addEventListener('click',event=>{
  const open=event.target.closest('[data-action="feedback"]');
  const close=event.target.closest('[data-close-feedback]');
  const report=event.target.closest('[data-toast-report]');
  if(report){event.preventDefault();event.stopImmediatePropagation();dismissToast();openFeedbackDialog(state.feedbackError);return;}
  if(open){event.preventDefault();event.stopImmediatePropagation();openFeedbackDialog();return;}
  if(close){event.preventDefault();event.stopImmediatePropagation();$('#feedbackDialog')?.close();}
},true);

document.addEventListener('submit',event=>{
  if(event.target.id!=='feedbackForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const form=event.target,fields=new FormData(form),submit=form.querySelector('[type="submit"]');
  if(submit)submit.disabled=true;
  (async()=>{try{
    const attach=fields.get('attach_context')==='on';
    const result=await api('/feedback',{method:'POST',body:JSON.stringify({
      work_id:state.work?.id||null,
      category:fields.get('category'),
      summary:fields.get('summary'),
      details:fields.get('details'),
      severity:fields.get('severity'),
      context:attach?feedbackContext():{},
      error:state.feedbackError?.error||{},
    })});
    form.reset();state.feedbackError=null;state.lastError=null;$('#feedbackDialog')?.close();
    toast(result.remote?.status==='synced'?'反馈已同步到服务器':result.remote?.status==='pending'?'反馈已保存到本机，服务器待重试':`反馈已保存到本机 · ${result.id}`);
  }catch(error){toast(error.message,true)}finally{if(submit)submit.disabled=false}})();
},true);

/* Final surface overrides. Keep these at EOF while the original vertical
   slice is still present above; this is the only render path the browser uses. */
conversationTaskContract=function(thread){
  const scope=agentTaskScope(),hasBrief=Boolean(brief()),hasBlueprint=blueprintIsConfirmed();
  let id='brief.build',task='理解这句想法，提出需要讨论的方向，不写入任何正式设定。';
  if(scope.surface==='work'){
    if(hasBrief){id='blueprint.generate';task='在作品栏目维护全作方向、人物关系和世界观边界；任何调整都先形成新的 StoryBlueprint Proposal。';}
  }else if(hasBlueprint){id='chapter.plan';task=`只规划《${writingChapter()?.title||'当前章节'}》内部的章节目标、承接点和场景节拍，不重写全作 StoryBlueprint。`;}
  else {id='blueprint.generate';task='全作方向尚未确认，请先回到作品栏目完成确认。';}
  const template=(state.capabilities?.writing_pack?.templates||[]).find(item=>item.id===id)||{};
  if(scope.import_mode){
    id='import.script';
    task=scope.import_mode==='aap_to_script'?'检查已加入的 AAP 工程并整理为可审查剧本候选。':'检查已加入的小说/文稿并整理为可审查剧本候选。';
  }
  return {...template,id,task,task_scope:{...scope,chapter_id:scope.surface==='chapter'?writingChapter()?.id:null,chapter_title:scope.surface==='chapter'?writingChapter()?.title:null},write_boundary:'正式方案、章节细纲和正文都必须经过对应 Proposal 或 Gate。'};
};
renderConversationTask=function(contract){
  const execution={user_confirmed:'等待确认',proposal_then_confirm:'先提案后确认',automatic_proposal_only:'仅生成候选',automatic_gate_then_user_freeze:'审查后冻结'}[contract?.execution]||'受阶段约束';
  const scope=contract?.task_scope?.surface==='chapter'?'章内写作':'作品规划';
  return `<section class="director-task-contract"><div><span>当前任务 · ${esc(scope)}${contract?.task_scope?.chapter_title?` · ${esc(contract.task_scope.chapter_title)}`:''}</span><b>${esc(contract?.id||'writing')}</b><small>${esc(contract?.task||'继续当前阶段的讨论；正式变更仍需经过 Proposal 和 Gate。')}</small></div><em>${esc(execution)}</em></section>`;
};
renderConversationAction=function(contract,proposal){
  if(proposal)return '';
  if(contract?.id==='chapter.plan')return '<button class="quiet" type="button" data-organize-conversation>整理章内细纲</button>';
  if(['brief.build','blueprint.generate'].includes(contract?.id))return '<button class="quiet" type="button" data-organize-conversation>形成全作方案</button>';
  return '';
};
renderConversationMessage=function(message){
  const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[],proposal=message.proposal_id?state.work?.proposals?.find(item=>item.id===message.proposal_id):null,target=proposal?.kind==='chapter_plan'?'structure':'brief';
  return `<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${message.proposal_id?`<button class="message-proposal-link" type="button" data-stage-jump="${target}">查看待审方案</button>`:''}</div></article>`;
};
renderWorkConversationInspector=function(){
  const el=$('#inspectorContent'),thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread),chapter=writingChapter(),workSurface=agentTaskScope().surface==='work';
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));
  if(!thread){el.innerHTML='<div class="inspector-body"><p>当前作品还没有创作主对话。</p></div>';return;}
  const pending=proposal?`<div class="director-pending"><b>${workSurface?'全作故事方案':`《${esc(chapter?.title||'当前章节')}》章内细纲`}等待决定</b><span>正式产物尚未改变。先审查，再决定采纳或退回。</span><div class="director-pending-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div>`:'';
  el.innerHTML=`<div class="director-panel"><header class="director-header"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h3>${workSurface?'全作创作导演':'章内写作助手'}</h3><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><small>${workSurface?'作品栏目 · 全局方向、人物和世界观':'写作栏目 · '+esc(chapter?.title||'尚未选择章节')} · 对话连续保留</small></div></header>${renderConversationTask(task)}<div class="conversation-scroll" data-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${pending}<form id="workConversationForm" class="conversation-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};
renderMobileAgent=function(el){
  const thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread),chapter=writingChapter(),workSurface=agentTaskScope().surface==='work';
  if(!thread){el.innerHTML=frame('CREATIVE DIRECTOR','创作对话','当前作品还没有创作主对话。','<div class="notice">重新打开作品后会自动恢复对话。</div>');return;}
  const pending=proposal?`<div class="director-pending"><b>${workSurface?'全作故事方案':`《${esc(chapter?.title||'当前章节')}》章内细纲`}等待决定</b><span>正式产物尚未改变。</span><div class="director-pending-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div>`:'';
  el.innerHTML=`<div class="mobile-agent-page"><header class="mobile-agent-head"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h2>${workSurface?'全作创作导演':'章内写作助手'}</h2><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><p>${esc(state.work.title)} · ${workSurface?'作品规划':'写作 · '+(chapter?.title||'未选择章节')}</p></div></header>${renderConversationTask(task)}<div class="mobile-conversation-scroll" data-mobile-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${pending}<form id="mobileWorkConversationForm" class="conversation-composer mobile-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-mobile-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};
var writingStructureBase=renderStructure;
renderStructure=function(el){
  writingStructureBase(el);
  const inner=$('.workspace-inner',el),chapter=writingChapter();if(!inner)return;
  const target=document.createElement('section');target.className='writing-target-bar';target.innerHTML=`<div><p class="eyebrow">CURRENT WRITING TARGET</p><h3>${chapter?esc(chapter.title):'还没有可写章节'}</h3><p>章内细纲、场景上下文和 Agent 讨论都会绑定这一章。全作方向请回到“作品”。</p></div><label>当前章节<select data-select-writing-chapter>${(state.work?.chapters||[]).map(item=>`<option value="${esc(item.id)}" ${item.id===chapter?.id?'selected':''}>${esc(item.title)}</option>`).join('')}</select></label>`;
  inner.querySelector('.structure-scope-note, .structure-command')?.before(target);
  const planArtifact=(state.work.artifacts||[]).find(item=>item.kind==='chapter_plan'&&item.scope_id===chapter?.id),plan=planArtifact?.current_revision?.content;
  if(plan){const note=document.createElement('section');note.className='chapter-plan-summary';note.innerHTML=`<div><p class="eyebrow">CHAPTER PLAN · 已采纳</p><h3>${esc(plan.title||`${chapter.title}细纲`)}</h3><p>${esc(plan.chapter_goal||'本章目标已保存。')}</p></div><button class="quiet" type="button" data-inspector="agent">继续讨论本章</button>`;inner.querySelector('.structure-scope-note, .structure-command')?.before(note)}
};
var renderSurfaceBase=render;
render=function(){renderSurfaceBase();decorateVolumeTree();decorateTopStatus();if(state.stage==='draft'&&state.sceneId)queueMicrotask(()=>ensureSceneContext(state.sceneId));};

// Product boundary: Works owns the whole-story director; Writing owns one
// persisted chapter at a time. The same thread remains continuous, but every
// turn receives the server-validated scope below.
function writingTarget(){return artifact('writing_target')||{chapter_id:state.writingChapterId||'',anchor_scene_id:''}}
async function persistWritingTarget(chapterId,anchorSceneId=null){
  const operation=writingTargetSavePromise.then(async()=>{
    if(!state.work||!chapterId)return state.work;
    const current=writingTarget(),normalizedAnchor=anchorSceneId||null;
    if(current.chapter_id===chapterId&&(current.anchor_scene_id||null)===normalizedAnchor)return state.work;
    const workId=state.work.id;
    const save=()=>api(`/works/${workId}/writing-target`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,chapter_id:chapterId,anchor_scene_id:normalizedAnchor})});
    let result;
    try{
      result=await save();
    }catch(error){
      if(error.code!=='revision_conflict'||state.work?.id!==workId)throw error;
      const refreshed=await api(`/works/${workId}`);
      if(state.work?.id!==workId)return state.work;
      state.work=refreshed;
      const latest=writingTarget();
      if(latest.chapter_id===chapterId&&(latest.anchor_scene_id||null)===normalizedAnchor)return state.work;
      result=await save();
    }
    if(state.work?.id===workId)state.work=result.work;
    return result.work;
  });
  writingTargetSavePromise=operation.catch(()=>{});
  return operation;
}
function writingChapter(){const id=writingTarget().chapter_id||state.writingChapterId;return (state.work?.chapters||[]).find(ch=>ch.id===id)||state.work?.chapters?.find(ch=>ch.status!=='placeholder')||state.work?.chapters?.[0]||null}
function agentTaskScope(){
  const chapter=writingChapter();
  const isWorkSurface=state.surface==='works';
  const scope=isWorkSurface?{surface:'work'}:{surface:'chapter',chapter_id:chapter?.id||null,chapter_title:chapter?.title||null};
  if(state.composerImportMode){
    scope.import_mode=state.composerImportMode;
    if(state.composerImportId)scope.import_id=state.composerImportId;
    if(state.composerImportPreview)scope.import_preview=state.composerImportPreview;
  }
  return scope;
}
function chapterPlanProposal(){const chapter=writingChapter();return (state.work?.proposals||[]).find(item=>item.kind==='chapter_plan'&&item.status==='pending'&&(!chapter||item.scope_id===chapter.id))||null}
function activeConversationProposal(){return agentTaskScope().surface==='chapter'?chapterPlanProposal():workPlanProposal()}

renderConversationTask=function(contract){
  const execution={user_confirmed:'等待确认',proposal_then_confirm:'先提案后确认',automatic_proposal_only:'仅生成候选',automatic_gate_then_user_freeze:'审查后冻结'}[contract?.execution]||'受阶段约束';
  const scope=contract?.task_scope?.surface==='chapter'?'章内写作': '作品规划';
  const title=contract?.task_scope?.chapter_title?`${scope} · ${contract.task_scope.chapter_title}`:scope;
  return `<section class="director-task-contract"><div><span>当前任务 · ${esc(title)}</span><b>${esc(contract?.id||'writing')}</b><small>${esc(contract?.task||'继续当前阶段的讨论；正式变更仍需经过 Proposal 和 Gate。')}</small></div><em>${esc(execution)}</em></section>`;
};
renderConversationAction=function(contract,proposal){
  if(proposal)return '';
  if(contract?.id==='chapter.plan')return '<button class="quiet" type="button" data-organize-conversation>整理章内细纲</button>';
  if(['brief.build','blueprint.generate'].includes(contract?.id))return '<button class="quiet" type="button" data-organize-conversation>形成全作方案</button>';
  return '';
};
renderConversationMessage=function(message){
  const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[],proposal=message.proposal_id?state.work?.proposals?.find(item=>item.id===message.proposal_id):null;
  const target=proposal?.kind==='chapter_plan'?'structure':'brief';
  return `<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${message.proposal_id?`<button class="message-proposal-link" type="button" data-stage-jump="${target}">查看待审方案</button>`:''}</div></article>`;
};

function directorPendingMarkup(proposal){
  if(!proposal)return '';
  const chapter=proposal.kind==='chapter_plan'?writingChapter():null;
  return `<div class="director-pending"><b>${chapter?`《${esc(chapter.title)}》章内细纲候选`:'全作故事方案'}等待决定</b><span>正式产物尚未改变。先审查，再决定采纳或退回。</span><div class="director-pending-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div>`;
}
renderWorkConversationInspector=function(){
  const el=$('#inspectorContent'),thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread);
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));
  if(!thread){el.innerHTML='<div class="inspector-body"><p>当前作品还没有创作主对话。</p></div>';return;}
  const chapter=writingChapter(),workSurface=agentTaskScope().surface==='work';
  el.innerHTML=`<div class="director-panel"><header class="director-header"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h3>${workSurface?'全作创作导演':'章内写作助手'}</h3><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><small>${workSurface?'作品栏目 · 全局方向、人物和世界观':'写作栏目 · '+esc(chapter?.title||'尚未选择章节')} · 对话连续保留</small></div></header>${renderConversationTask(task)}<div class="conversation-scroll" data-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${directorPendingMarkup(proposal)}<form id="workConversationForm" class="conversation-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};
renderMobileAgent=function(el){
  const thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread),chapter=writingChapter();
  if(!thread){el.innerHTML=frame('CREATIVE DIRECTOR','创作对话','当前作品还没有创作主对话。','<div class="notice">重新打开作品后会自动恢复对话。</div>');return;}
  const workSurface=agentTaskScope().surface==='work';
  el.innerHTML=`<div class="mobile-agent-page"><header class="mobile-agent-head"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h2>${workSurface?'全作创作导演':'章内写作助手'}</h2><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><p>${esc(state.work.title)} · ${workSurface?'作品规划':'写作 · '+(chapter?.title||'未选择章节')}</p></div></header>${renderConversationTask(task)}<div class="mobile-conversation-scroll" data-mobile-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${directorPendingMarkup(proposal)}<form id="mobileWorkConversationForm" class="conversation-composer mobile-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-mobile-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};

const renderStructureBeforeWritingTarget=renderStructure;
renderStructure=function(el){
  renderStructureBeforeWritingTarget(el);
  const inner=$('.workspace-inner',el),chapter=writingChapter();
  if(!inner)return;
  const plan=chapter?artifact('chapter_plan')&&((state.work.artifacts||[]).find(item=>item.kind==='chapter_plan'&&item.scope_id===chapter.id)?.current_revision?.content):null;
  const target=document.createElement('section');target.className='writing-target-bar';target.innerHTML=`<div><p class="eyebrow">CURRENT WRITING TARGET</p><h3>${chapter?`第 ${esc(chapter.title)}`:'还没有可写章节'}</h3><p>后续章内细纲、场景上下文和 Agent 讨论都会绑定这一章。全作方向请回到“作品”。</p></div><label>当前章节<select data-select-writing-chapter>${(state.work?.chapters||[]).map(item=>`<option value="${esc(item.id)}" ${item.id===chapter?.id?'selected':''}>${esc(item.title)}</option>`).join('')}</select></label>`;
  inner.querySelector('.structure-command')?.before(target);
  if(plan){const note=document.createElement('section');note.className='chapter-plan-summary';note.innerHTML=`<div><p class="eyebrow">CHAPTER PLAN · 已采纳</p><h3>${esc(plan.title||`${chapter.title}细纲`)}</h3><p>${esc(plan.chapter_goal||'本章目标已保存。')}</p></div><button class="quiet" type="button" data-inspector="agent">继续讨论本章</button>`;inner.querySelector('.structure-command')?.before(note)}
};

document.addEventListener('change',event=>{
  const select=event.target.closest('select[data-select-writing-chapter]');
  if(!select||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  (async()=>{try{const nextScene=state.work.chapters.find(ch=>ch.id===select.value)?.scenes?.[0]?.id||null;await persistWritingTarget(select.value,nextScene);state.writingChapterId=select.value;state.sceneId=nextScene||state.sceneId;state.context=null;toast('当前写作章节与承接场景已保存');render()}catch(error){toast(error.message,true);render()}})();
},true);
document.addEventListener('click',event=>{
  const selectAll=event.target.closest('[data-select-all-knowledge]');
  if(selectAll){
    event.preventDefault();event.stopImmediatePropagation();
    const proposalId=selectAll.dataset.selectAllKnowledge;
    document.querySelectorAll(`[data-knowledge-field="${CSS.escape(proposalId)}"]`).forEach(input=>{input.checked=true});
    syncKnowledgeSelection(proposalId);
    return;
  }
  const accept=event.target.closest('[data-accept-director-proposal]'),reject=event.target.closest('[data-reject-director-proposal]');
  if(!accept&&!reject)return;
  event.preventDefault();event.stopImmediatePropagation();
  const proposalId=(accept||reject).dataset.acceptDirectorProposal||(accept||reject).dataset.rejectDirectorProposal;
  const proposal=(state.work?.proposals||[]).find(item=>item.id===proposalId);
  const backgroundSuggestion=Boolean(proposal?.evidence?.background_suggestion);
  // Boolean data attributes are intentionally empty (`data-partial-knowledge`).
  // Check presence instead of the empty dataset value so partial acceptance
  // cannot silently fall back to accepting every field.
  const partial=Boolean(accept?.hasAttribute('data-partial-knowledge'));
  const selectedFields=partial?[...document.querySelectorAll(`[data-knowledge-field="${CSS.escape(proposalId)}"]:checked`)].map(input=>input.value):undefined;
  if(partial&&!selectedFields.length){toast('请先勾选至少一项变更。',true);return;}
  const impactDigest=accept?.dataset.impactDigest||'';
  (async()=>{try{const result=await api(`/works/${state.work.id}/proposals/${proposalId}/${accept?'accept':'reject'}`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:accept?(partial?'采用选中的资料变更':backgroundSuggestion?'采用后台整理的作品事实建议':'在当前工作面审查后采纳'):backgroundSuggestion?'用户决定不采用这条后台资料建议':'退回当前 Agent 继续讨论',...(partial?{selected_fields:selectedFields}:{}),...(impactDigest?{expected_impact_digest:impactDigest}:{})})});state.staleProposalIds?.delete(proposalId);state.work=result.work;await refreshAgentPresentation();toast(accept?(partial?'选中的变更已保存为新修订':backgroundSuggestion?'建议已写入作品事实的新修订':'候选已采纳为正式修订'):backgroundSuggestion?'这条建议已忽略，正式资料没有改变':'候选已退回，讨论仍保留');render()}catch(error){
    if(accept&&['proposal_impact_changed','proposal_impact_mismatch','proposal_impact_required'].includes(error.code)){
      state.staleProposalIds?.add(proposalId);
      try{state.work=await api(`/works/${state.work.id}`);await refreshAgentPresentation()}catch(_){/* Keep the stale decision visible if refresh is unavailable. */}
      setBusy('候选已过期，需要重新整理');
      toast('当前作品状态已经变化，这条候选不能直接采纳。请退回并按最新状态重新整理。',true);
      render();
      return;
    }
    toast(error.message,true);
  }})();
},true);

function syncKnowledgeSelection(proposalId){
  const fields=[...document.querySelectorAll(`[data-knowledge-field="${CSS.escape(proposalId)}"]`)];
  if(!fields.length)return;
  const selectedCount=fields.filter(input=>input.checked).length;
  const button=document.querySelector(`[data-knowledge-apply-count="${CSS.escape(proposalId)}"]`);
  const summary=document.querySelector(`[data-knowledge-selection-summary="${CSS.escape(proposalId)}"]`);
  if(button){button.textContent=`应用 ${selectedCount} 项修改`;button.disabled=selectedCount===0;button.setAttribute('aria-disabled',String(selectedCount===0))}
  if(summary)summary.textContent=`已选择 ${selectedCount} / ${fields.length} 项`;
}

document.addEventListener('change',event=>{
  const field=event.target.closest('[data-knowledge-field]');
  if(field)syncKnowledgeSelection(field.dataset.knowledgeField);
},true);

// Context assembly is automatic when a scene becomes the active writing task.
function ensureSceneContext(sceneId){
  if(!sceneId||!state.work||state._contextLoadingScene===sceneId||state.context?.scene_id===sceneId)return;
  if(state._contextErrorScene===sceneId)return;
  if(!blueprintIsConfirmed()){
    state._contextBlocked='请先保存写作想法并确认故事方向。';
    state._contextErrorScene=sceneId;
    setBusy('请先完成全作方向');
    render();
    return;
  }
  state._contextLoadingScene=sceneId;state._contextError='';state._contextBlocked='';setBusy('正在准备本场上下文');
  api(`/works/${state.work.id}/scenes/${sceneId}/context:assemble`,{method:'POST',body:'{}'}).then(context=>{if(state.sceneId===sceneId){state.context=context;state._contextErrorScene='';setBusy('本场上下文已准备');render()}}).catch(error=>{if(state.sceneId===sceneId){state._contextError=error.message;state._contextErrorScene=sceneId;setBusy('本场上下文准备失败');render()}}).finally(()=>{if(state._contextLoadingScene===sceneId)state._contextLoadingScene='';});
}
async function confirmIntentPlan(planId, submitButton){
  try{
    setBusy('正在确认并继续这条请求');
    const result=await api(`/intent-plans/${planId}:confirm`,{method:'POST',body:JSON.stringify({confirmed:true})});
    state.work=result.work;
    state.activeAgentRunId=result.result?.agent_run_id||'';
    state.decisionCardDockClosed=false;
    state.decisionCardWaitingForAgent=Boolean(state.activeAgentRunId);
    toast(state.activeAgentRunId?'确认已记录，Agent 正在继续处理':'确认已记录，等待审查候选');
    render();
    if(result.result?.agent_run_id)scheduleAgentRunPoll(result.result.agent_run_id,0);
  }catch(error){
    if(submitButton)submitButton.disabled=false;
    setBusy('请求仍在等待确认');
    toast(error.message,true);
  }
}

// A native dialog blocks pointer input, but it does not reliably remove the
// writing surface from the keyboard/accessibility tree in every browser. Keep
// the confirmation as one focused task and restore the trigger on cancellation.
let intentDialogAccessibility = [];
let intentDialogTrigger = null;
function setIntentDialogAccessibility(open, trigger = null) {
  if (open) {
    if (intentDialogAccessibility.length) return;
    intentDialogTrigger = trigger;
    const dialog = document.getElementById('agentIntentConfirmDialog');
    const appShell = document.getElementById('app');
    const composer = document.querySelector('.work-agent-composer, #workConversationForm, #mobileWorkConversationForm');
    const elements = [...new Set([appShell, composer].filter(Boolean))];
    intentDialogAccessibility = elements.map(element => ({
      element,
      ariaHidden: element.getAttribute('aria-hidden'),
      inert: element.inert,
    }));
    intentDialogAccessibility.forEach(({ element }) => {
      element.inert = true;
      element.setAttribute('aria-hidden', 'true');
    });
    dialog?.setAttribute('aria-modal', 'true');
    return;
  }
  const triggerToRestore = intentDialogTrigger;
  intentDialogAccessibility.forEach(({ element, ariaHidden, inert }) => {
    element.inert = inert;
    if (ariaHidden === null) element.removeAttribute('aria-hidden');
    else element.setAttribute('aria-hidden', ariaHidden);
  });
  intentDialogAccessibility = [];
  intentDialogTrigger = null;
  if (triggerToRestore && !triggerToRestore.disabled) {
    requestAnimationFrame(() => triggerToRestore.focus({ preventScroll: true }));
  }
}
const intentDialog = document.getElementById('agentIntentConfirmDialog');
intentDialog?.addEventListener('close', () => setIntentDialogAccessibility(false));

const renderAfterScope=render;
render=function(){renderAfterScope();if(state.stage==='draft'&&state.sceneId)queueMicrotask(()=>ensureSceneContext(state.sceneId));};

// Mobile uses one full task surface at a time. The desktop inspector remains
// available in the DOM, but the conversation below has distinct form IDs so
// the two layouts never compete for focus or submission.
function renderMobileConversationMessage(message){
  const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[];
  return `<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${content.simulation_notice?`<small>${esc(content.simulation_notice)}</small>`:''}${message.proposal_id?'<button class="message-proposal-link" type="button" data-stage-jump="brief">查看待审方案</button>':''}</div></article>`;
}

function renderPermissionMenu(thread){
  const managed=thread.permission_mode==='managed';
  return `<details class="permission-menu ${managed?'managed':''}"><summary title="设置 Agent 权限">${managed?'托管创作':'审核协作'}</summary><div class="permission-popover" role="menu" aria-label="Agent 权限"><header><b>Agent 权限</b><small>决定正式修改如何落地</small></header><button type="button" role="menuitemradio" aria-checked="${managed?'false':'true'}" class="${managed?'':'active'}" data-permission-mode="review"><span><b>审核协作</b><small>所有正式修改先成为候选并显示差异，由你决定是否采纳</small></span><i aria-hidden="true">&#10003;</i></button><button type="button" role="menuitemradio" aria-checked="${managed?'true':'false'}" class="${managed?'active':''}" data-permission-mode="managed"><span><b>托管创作</b><small>只在限定范围内自动采纳普通、低风险的写作修改</small></span><i aria-hidden="true">&#10003;</i></button><p>核心设定、大规模删除、冻结发布和 AA 交接始终需要确认。</p></div></details>`;
}

function renderMobileAgent(el){
  const thread=workConversationThread(),proposal=workPlanProposal();
  if(!thread){el.innerHTML=frame('CREATIVE DIRECTOR','创作导演','当前作品还没有创作主对话。','<div class="notice">旧作品需要重新打开一次，系统会补建主对话。</div>');return}
  const discuss=thread.phase==='discuss';
  el.innerHTML=`<div class="mobile-agent-page"><header class="mobile-agent-head"><div><p class="eyebrow">CREATIVE DIRECTOR</p><h2>全作 · 创作主对话</h2><p>${esc(state.work.title)} · 对话 v${thread.version}</p></div></header><div class="director-modes" role="group" aria-label="创作导演状态"><button type="button" data-thread-phase="discuss" class="${discuss?'active':''}">讨论创作</button><button type="button" data-thread-phase="execute" class="${!discuss?'active':''}">执行修改</button></div><div class="mobile-conversation-scroll" data-mobile-conversation-scroll>${thread.messages.map(renderMobileConversationMessage).join('')||'<p class="conversation-empty">先说一句你想看的故事。</p>'}</div>${proposal?'<div class="director-pending"><b>故事方案等待决定</b><span>正式 Brief 和故事方向尚未改变。</span><button type="button" data-stage-jump="brief">查看方案</button></div>':''}<form id="mobileWorkConversationForm" class="conversation-composer mobile-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="补充、反悔、比较方向，或直接说明哪里不对……"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}<button class="quiet" type="button" data-organize-conversation ${proposal?'disabled':''}>整理为方案</button></div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-mobile-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
}

const renderWorkspaceBeforeMobileAgent=renderWorkspace;
renderWorkspace=function(){
  if(state.work&&window.matchMedia('(max-width: 640px)').matches&&state.mobileView==='agent'){
    const el=$('#workspace');renderMobileAgent(el);el.scrollTop=0;return;
  }
  return renderWorkspaceBeforeMobileAgent();
};

mobileLabel=function(view){return({works:'作品结构',agent:'创作导演',context:'上下文',tasks:'任务'})[view]||'写作'};

document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-inspector="agent"]');
  if(!button||!window.matchMedia('(max-width: 640px)').matches)return;
  event.preventDefault();event.stopImmediatePropagation();
  // Scene recovery must stay inside the scene workbench. The same
  // inspector affordance is also used by the whole-work director, so use
  // the nearest scene surface to avoid leaking into the global mobile view.
  if(button.closest('.scene-workbench, .scene-harness')){
    state.writingMobileView='agent';
    state.inspector='agent';
    render();
    return;
  }
  state.mobileView='agent';render();
},true);

document.addEventListener('submit',async event=>{
  if(event.target.id!=='mobileWorkConversationForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const thread=workConversationThread(),fields=new FormData(event.target);
  try{
    setBusy('创作导演正在回应');
    const result=await api(`/works/${state.work.id}/threads/${thread.id}/messages`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,text:fields.get('text'),attachment_ids:state.composerAttachmentIds||[],task_scope:agentTaskScope()})});
    state.work=result.work;state.composerAttachmentIds=[];state.composerPrefill='';state.composerImportStatus=state.composerImportMode?'sent':'';state.composerImportMode='';state.composerImportId='';state.composerImportPreview=null;state.composerImportError='';setBusy('对话已保存');toast(result.simulation?'模拟回应已保存，可继续讨论':'回应已保存');render();
  }catch(error){await recoverFailedAgentTurn(error);setBusy('对话发送失败');toast(error.message,true)}
},true);

// The overview is a projection of the same Work/Volume/Chapter/Scene data,
// not a second copy of the outline. It keeps the current writing scope visible
// and gives the user one decision without hiding the underlying structure.
function renderOverviewV3(el){
  const work=state.work,volumes=work.volumes||[],sceneList=scenes(),total=sceneList.length,drafted=sceneList.filter(scene=>scene.current_revision_id).length;
  const planProposal=workPlanProposal(),savedBrief=brief(),formal=blueprintIsConfirmed(),pending=work.proposals.filter(item=>item.status==='pending').length;
  const blocker=(work.review_findings||[]).filter(item=>item.status==='open'&&item.severity==='blocking').length;
  const activeScene=selectedScene(),activeChapter=(work.chapters||[]).find(chapter=>chapter.scenes.some(scene=>scene.id===activeScene?.id))||(work.chapters||[])[0];
  const activeVolume=volumes.find(volume=>volume.chapters.some(chapter=>chapter.id===activeChapter?.id))||volumes[0];
  let next={stage:'brief',title:'继续和创作导演讨论',detail:'可以补充、反悔或比较方向；聊清楚后再把共识整理成正式方案。',label:'查看讨论与方案',agent:true};
  if(planProposal)next={stage:'brief',title:'审查刚整理的故事方案',detail:'方案仍是 Proposal。采纳后才会建立正式 Brief 与 StoryBlueprint 修订。',label:'审查方案'};
  else if(savedBrief&&!formal)next={stage:'brief',title:'继续确认故事方向',detail:'当前想法已经保存，但整体故事方向仍需确认。',label:'查看故事方向'};
  else if(formal&&!total)next={stage:'structure',title:'规划第一章的第一场',detail:'第一卷和第一章已经存在。现在只需要说明第一场发生什么变化。',label:'安排第一个场景'};
  else if(pending)next={stage:'draft',title:'先处理待决定的候选',detail:`有 ${pending} 份 Proposal 等待采纳、局部修改或退回。`,label:'查看候选'};
  else if(blocker)next={stage:'draft',title:'处理审查阻塞项',detail:`有 ${blocker} 个阻塞项需要处理，完成后才可冻结版本。`,label:'处理审查'};
  else if(total&&drafted<total)next={stage:'draft',title:'继续下一场写作',detail:`还有 ${total-drafted} 个场景没有已采纳正文。Agent 结果会先进入 Diff 审查。`,label:'打开逐场写作'};
  else if(total)next={stage:'release',title:'运行全篇审查',detail:'确认连续性、人物约束和正文修订后，再冻结交给制作的定稿。',label:'检查并发布'};
  const progress=total?Math.round(drafted/total*100):0,cards=libraryCards(),worldEntities=(worldBible().entities||[]).filter(item=>item.status!=='archived');
  const scope=[activeVolume?.title,activeChapter?.title,activeScene?.title].filter(Boolean);
  const volumeMarkup=volumes.map((volume,volumeIndex)=>`<section class="overview-volume"><header><span>卷 ${String(volumeIndex+1).padStart(2,'0')}</span><b>${esc(volume.title)}</b><small>${volume.chapters.length} 章</small></header>${volume.chapters.map(chapter=>`<button type="button" class="overview-chapter-line" data-writing-chapter="${esc(chapter.id)}"><span>${esc(chapter.title)}</span><b>${chapter.scenes.length} 场</b><small>${chapter.scenes.filter(scene=>scene.current_revision_id).length} 场已有正文</small></button>`).join('')}</section>`).join('');
  el.innerHTML=`<div class="overview-workbench overview-v3"><header class="overview-header"><div><p class="eyebrow">WORK OVERVIEW</p><h2>${esc(work.title)}</h2><p>${scope.length?`当前范围：${scope.map(esc).join(' / ')}`:'作品骨架已经建立，尚未选择场景。'}</p></div><button class="quiet" data-stage-jump="references">管理资料库</button></header><section class="overview-next overview-next-calm"><div><p class="eyebrow">RECOMMENDED DECISION</p><h3>${next.title}</h3><p>${next.detail}</p></div><button class="primary" ${next.agent?'data-focus-discussion':`data-stage-jump="${next.stage}"`}>${next.agent?'进入全作讨论':next.label}</button></section><div class="overview-progress-line"><b>正文进度 ${progress}%</b><span>${drafted} / ${total} 个场景已有正式正文</span>${pending||blocker?`<button class="text-link ${blocker?'has-attention':''}" data-stage-jump="draft">${pending+blocker} 项等待决定</button>`:''}</div><section class="overview-foundation-strip"><button data-stage-jump="references" data-library-target="characters"><span>人物卡</span><b>${cards.length} 张</b><small>${cards.filter(card=>card.source_type==='custom').length} 张自定义</small></button><button data-stage-jump="references" data-library-target="world"><span>世界设定</span><b>${worldEntities.length} 项</b><small>${worldEntities.filter(item=>item.confidence_status==='confirmed').length} 项已确认</small></button><div><span>创作对话</span><b>${workConversationThread()?.messages?.length||0} 条</b><small>${planProposal?'有方案等待决定':'讨论与正式产物分开保存'}</small></div></section><section class="overview-structure-v3"><div class="overview-section-head"><div><p class="eyebrow">STORY BINDER</p><h3>卷、章与场景</h3></div><button class="quiet" data-stage-jump="structure">管理结构</button></div>${volumeMarkup||'<p class="overview-empty">尚未建立卷结构。</p>'}</section></div>`;
}

// Keep the guided path visible in the stage list, but do not repeat the same
// instruction in a second, competing side-panel card.
function renderWorkflowGuide(){
  const guide=$('#workflowGuide');
  if(guide)guide.replaceChildren();
  if(!state.work)return;
  const progress=workflowProgress();
  const nextStage=FLOW_STAGES.find(stage=>!progress.done[stage])||'release';
  $$('[data-stage]').forEach(button=>{
    const stage=button.dataset.stage;
    const gate=stageGate(stage);
    const small=button.querySelector('small');
    const complete=Boolean(progress.done[stage]);
    const current=stage===state.stage;
    const next=stage===nextStage&&!complete;
    button.disabled=!gate.allowed;
    button.classList.toggle('is-complete',complete);
    button.classList.toggle('is-current',current);
    button.classList.toggle('is-next',next&&!current);
    button.setAttribute('aria-current',current?'step':'false');
    button.setAttribute('aria-disabled',String(!gate.allowed));
    button.title=gate.allowed?(complete?'已完成，可随时查看':'可进入此阶段'):gate.reason;
    if(small){
      small.textContent=complete?'已完成':current?'正在进行':gate.allowed?'可随时查看':'完成前一步后可继续';
    }
  });
  const production=$('[data-section="production"]');
  if(production)production.title='打开 AA 制作工作台';
}

function renderBrief(el){
  const b=brief()||{};
  const isSaved=Boolean(brief());
  el.innerHTML=frame(
    '第 1 步 / 5',
    '先把故事开头说清楚',
    '这张写作想法只记录你此刻的创作意图。人物卡、世界观和正文仍在各自的资料与写作页面管理。',
    `<section class="brief-clarity-band">
      <div><p class="eyebrow">THIS STEP</p><h3>先回答三个问题，其他设定以后再补。</h3><p>故事要写什么、用什么写法、谁是主要角色。保存后才会解锁故事方向。</p></div>
      <span class="brief-step-state ${isSaved?'is-saved':''}">${isSaved?'已保存，可继续':'等待填写'}</span>
    </section>
    <form id="briefForm" class="brief-form">
      <label class="brief-idea">一句想法<textarea name="idea" required placeholder="例如：凯伊发现游戏开发部的旧机器在深夜自行启动">${esc(b.idea)}</textarea><small>用一句话说清这部作品最想发生什么。</small></label>
      <div class="brief-core-grid">
        <label>写作模式<select name="mode"><option value="bond_short" ${b.mode==='bond_short'?'selected':''}>羁绊短场景</option><option value="main_battle" ${b.mode==='main_battle'?'selected':''}>主线与战斗</option><option value="long_comedy" ${b.mode==='long_comedy'?'selected':''}>长篇喜剧</option><option value="text_reading" ${b.mode==='text_reading'?'selected':''}>小说化阅读</option></select></label>
        <label>主要角色<input name="characters" value="${esc((b.characters||[]).join('、'))}" placeholder="爱丽丝、凯伊"><small>用顿号分隔；之后可到人物库完善卡片。</small></label>
      </div>
      <details class="brief-optional" ${b.target_length||b.constraints||b.has_sensei?'open':''}>
        <summary>补充设定（可选）</summary>
        <div class="brief-optional-fields">
          <label>目标长度<select name="target_length"><option value="short" ${b.target_length==='short'?'selected':''}>短场景</option><option value="chapter" ${b.target_length==='chapter'?'selected':''}>单章</option><option value="long" ${b.target_length==='long'?'selected':''}>长篇</option></select></label>
          <label class="brief-constraint">额外约束<textarea name="constraints" placeholder="不可提前揭示的事实、希望保留的关系距离……">${esc(b.constraints)}</textarea></label>
          <label class="check brief-check"><span><input type="checkbox" name="has_sensei" ${b.has_sensei?'checked':''}> 老师在场</span></label>
        </div>
      </details>
      <div class="brief-actions">
        <div><b>${isSaved?'修改会新建一份写作想法修订':'保存后不会自动生成正文或改写资料库'}</b><small>${isSaved?'故事方向、章节和场景会继续引用这份简报。':'你仍可随时回到这里修改。'}</small></div>
        <div class="actions"><button class="primary" type="submit">${isSaved?'保存修改':'保存写作想法'}</button>${isSaved?'<button class="quiet" type="button" data-stage-jump="blueprint">下一步：确认故事方向</button>':''}</div>
      </div>
    </form>`
  );
}

function renderOverview(el){
  const work=state.work;
  const sceneList=scenes();
  const total=sceneList.length;
  const drafted=sceneList.filter(scene=>scene.current_revision_id).length;
  const cards=libraryCards();
  const world=worldBible();
  const worldEntities=(world.entities||[]).filter(item=>item.status!=='archived');
  const pending=work.proposals.filter(item=>item.status==='pending').length;
  const blocker=(work.review_findings||[]).filter(item=>item.status==='open'&&item.severity==='blocking').length;
  let next={stage:'brief',title:'先提供一句创作想法',detail:'只要说出想看什么；系统会在下一步提出角色、世界观依据和写作组成候选。',label:'开始写作想法'};
  if(brief()&&!blueprintIsConfirmed())next={stage:'blueprint',title:'审查故事方向候选',detail:'系统先提出角色、写作组成与世界观依据；确认后才会建立章节。',label:'审查故事方向'};
  else if(blueprintIsConfirmed()&&!work.chapters.length)next={stage:'structure',title:'建立章节与场景',detail:'先建立第一章，再把故事拆成有稳定身份的场景。',label:'建立章节与场景'};
  else if(pending)next={stage:'draft',title:'先审查待处理候选',detail:`有 ${pending} 份候选等待你采纳、局部修改或退回。`,label:'查看候选'};
  else if(blocker)next={stage:'draft',title:'处理审查阻塞项',detail:`有 ${blocker} 个阻塞项。处理完成后才可以冻结发布版本。`,label:'处理审查'};
  else if(total&&drafted<total)next={stage:'draft',title:'开始下一场写作',detail:`还有 ${total-drafted} 个场景没有已采纳正文，生成结果会先进入候选审查。`,label:'打开逐场写作'};
  else if(total)next={stage:'release',title:'运行全篇审查',detail:'确认连续性、人物约束和正文修订后，再冻结交给制作的定稿。',label:'检查并发布'};
  const progress=total?Math.round(drafted/total*100):0;
  el.innerHTML=`<div class="overview-workbench overview-workbench-calm">
    <header class="overview-header"><div><p class="eyebrow">WORK OVERVIEW</p><h2>${esc(work.title)}</h2><p>从这里看清作品当前走到哪里，以及接下来只需要做哪一个决定。</p></div><button class="quiet" data-stage-jump="references">管理资料库</button></header>
    <section class="overview-next overview-next-calm"><div><p class="eyebrow">NEXT STEP</p><h3>${next.title}</h3><p>${next.detail}</p></div><button class="primary" data-stage-jump="${next.stage}">${next.label}</button></section>
    <section class="overview-signal-strip" aria-label="作品概况">
      <div class="overview-signal"><b>${progress}%</b><span>正文进度</span><small>${drafted}/${total||0} 个场景已采纳</small></div>
      <button class="overview-signal overview-signal-link" data-stage-jump="references" data-library-target="characters"><b>${cards.length}</b><span>人物卡</span><small>${cards.filter(card=>card.source_type==='custom').length} 张自定义</small></button>
      <button class="overview-signal overview-signal-link" data-stage-jump="references" data-library-target="world"><b>${worldEntities.length}</b><span>世界观卡</span><small>${worldEntities.filter(item=>item.confidence_status==='confirmed').length} 张已确认</small></button>
      <button class="overview-signal overview-signal-link ${pending||blocker?'has-attention':''}" data-stage-jump="draft"><b>${pending+blocker}</b><span>等待决定</span><small>${blocker?'有审查阻塞项':'候选与审查事项'}</small></button>
    </section>
    <section class="overview-columns overview-columns-calm"><div><div class="overview-section-head"><h3>作品结构</h3><button class="quiet" data-stage-jump="structure">管理章节</button></div>${work.chapters.length?work.chapters.map(ch=>`<div class="overview-chapter"><b>${esc(ch.title)}</b><span>${ch.scenes.length} 个场景</span><small>${ch.scenes.filter(scene=>scene.current_revision_id).length} 已完成</small></div>`).join(''):'<p class="overview-empty">尚未建立章节。完成故事方向后，再把它拆成第一章和场景。</p>'}</div><div><div class="overview-section-head"><h3>写作基础</h3><span class="status-chip ${pending||blocker?'amber':''}">${pending||blocker?'等待你的决定':'暂无待处理项'}</span></div><ul class="overview-checks"><li><i class="check-dot"></i>作品与修订已保存到本地</li><li><i class="check-dot ${cards.length?'':'muted'}"></i>${cards.length?'人物卡已登记':'尚未建立人物卡'}</li><li><i class="check-dot ${worldEntities.length?'':'muted'}"></i>${worldEntities.length?'世界观卡已登记':'尚未建立 BA 或自定义世界观卡'}</li></ul></div></section>
  </div>`;
}

function stageDecisionModel(){
  const scene=selectedScene();
  const proposal=pendingProposal();
  const latest=state.work?.releases?.[0];
  const definitions={
    overview:{kicker:'WORKFLOW',title:'按推荐下一步推进即可',body:'作品总览只保留一个推荐行动，其他入口仍在左侧导航。',impact:'不会自动生成、修改或发布任何内容。'},
    brief:{kicker:'STEP 1',title:brief()?'写作想法已保存':'先建立写作想法',body:brief()?'可以修改这份创作意图，或继续确认故事方向。':'填写一句想法、写作模式和主要角色；其他设定可以稍后补充。',impact:'保存后会建立 Brief 修订，并解锁故事方向。'},
    blueprint:{kicker:'STEP 2',title:blueprint()?'检查故事方向':'先生成故事方向',body:blueprint()?'确认故事范围、冲突与收束方式，再开始建立章节。':'这一步只生成结构化方向，不会改动正文。',impact:'生成结果会保存为独立 StoryBlueprint。'},
    structure:{kicker:'STEP 3',title:'建立稳定的章节与场景',body:'场景会拥有稳定 ID；改标题或调整顺序不会丢失正文和资料引用。',impact:'保存结构会使旧的全篇审查失效，需要重新检查。'},
    draft:{kicker:'STEP 4',title:proposal?'审查本场候选':scene?`推进「${scene.title}」`:'先建立一个场景',body:proposal?'候选可以局部修改；采纳前不会进入正文。':scene?'先装配上下文，再生成候选或检查已有正文。':'回到章节安排，先建立场景。',impact:proposal?'采纳时才会建立新的正文修订。':'Agent 只能提交候选，不能静默修改正文或资料。'},
    references:{kicker:'WORK LIBRARY',title:'确认可进入 Agent 的资料',body:'人物、世界观、事实与来源证据分别管理。待核对条目不会自动作为写作事实。',impact:'只有确认采用的资料会出现在下一场可选择的上下文中。'},
    release:{kicker:'第 5 步',title:latest?'确认交给制作的定稿':'先完成全篇审查',body:latest?'冻结版本不会随正文修改而改变；新稿需要创建新的发布版本。':'所有场景都有已采纳正文后，才能运行全篇审查与冻结。',impact:latest?'提交制作只交付当前定稿。':'全篇审查通过前，发布操作保持锁定。'}
  };
  return definitions[state.stage]||definitions.overview;
}

function renderInspector(){
  const el=$('#inspectorContent');
  if(!el)return;
  const scene=selectedScene();
  const proposal=pendingProposal();
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector===state.inspector));
  if(!state.work){el.innerHTML='';return;}
  if(state.inspector==='decision'){
    const decision=stageDecisionModel();
    el.innerHTML=`<div class="inspector-body inspector-decision"><p class="eyebrow">${decision.kicker}</p><h3>${esc(decision.title)}</h3><p class="inspector-copy">${esc(decision.body)}</p><section class="inspector-impact"><span>保存或确认后</span><b>${esc(decision.impact)}</b></section><ul class="inspector-checklist"><li><i class="status-dot"></i>作品与版本已持久化</li><li><i class="status-dot ${proposal?'amber':''}"></i>${proposal?'当前有候选等待审查':'没有会被静默写入的内容'}</li><li><i class="status-dot"></i>当前操作由中央工作区完成</li></ul></div>`;
    return;
  }
  if(state.inspector==='context'){
    const c=state.context;
    el.innerHTML=`<div class="inspector-body"><p class="eyebrow">SCENE CONTEXT</p><h3>当前作用域</h3><p>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'尚未选择场景'}</p><ul class="context-list">${c?`<li>规则包<br><b>${esc(c.rules.pack_version)}</b></li><li>单一模式<br><b>${esc(c.rules.mode)}</b></li><li>固定输入修订<br><b>${c.source_revision_ids.length} 个</b></li><li>真实 BA 写作<br><b>${esc(c.readiness.real_ba_writing)}</b></li>`:'<li>进入“逐场写作”并装配上下文后，这里会列出实际读取的版本。</li>'}</ul></div>`;
    return;
  }
  if(state.stage!=='draft'){
    el.innerHTML=`<div class="inspector-body"><p class="eyebrow">CREATIVE DIRECTOR</p><h3>Agent 在逐场写作时才出现</h3><p>先在中央工作区完成当前阶段。Agent 只依附一个场景和明确任务，不会取代作品结构或资料库。</p><button class="quiet" type="button" data-stage-jump="draft" ${stageGate('draft').allowed?'':'disabled'}>打开逐场写作</button></div>`;
    return;
  }
  const existing=scene?.current_revision_id;
  const latestRun=(state.work?.agent_runs||[]).find(run=>run.scope_id===scene?.id);
  el.innerHTML=`<div class="inspector-body"><p class="eyebrow">CREATIVE DIRECTOR</p><h3>只为当前场景提供候选</h3><p>它读取固定场景合同、BA 规则和已确认的人物卡；结果必须先以候选形式交给你审查。</p>${latestRun?`<section class="agent-run"><b>${esc(latestRun.status)}</b><p>工具记录 ${latestRun.tool_calls.length} 项${latestRun.proposal_id?` · Proposal ${latestRun.proposal_id}`:''}</p></section>`:''}<form id="agentRunForm"><label>本场指令<textarea name="instruction" placeholder="例如：以爱丽丝先观察、凯伊后补充的节奏起草本场" ${scene&&!existing?'':'disabled'}></textarea></label><button class="primary" type="submit" ${scene&&!existing&&!proposal?'':'disabled'}>运行 BA 场景 Agent</button></form><p class="form-note">${existing?'当前已有正文：受控复写会以新候选返回。':providerDisclosure()}</p></div>`;
}
document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-library-target]');
  if(button)state.libraryView=button.dataset.libraryTarget;
},true);
const $=(q,root=document)=>root.querySelector(q);const $$=(q,root=document)=>[...root.querySelectorAll(q)];
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function captureClientError(error,meta={}){state.feedbackError={message:String(error?.message||'请求失败'),code:String(error?.code||'client_error'),status:Number(error?.status||0),details:error?.details||{},path:meta.path||location.pathname,action:meta.action||'当前页面操作',error:{code:String(error?.code||'client_error'),http_status:Number(error?.status||0),details:error?.details||{}}};state.lastError=state.feedbackError}
async function api(path,options={}){try{const response=await fetch('/api/v1'+path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});let result;try{result=await response.json()}catch(_){const error=new Error(`服务器返回了无法解析的响应（${response.status}）`);error.code='invalid_server_response';error.status=response.status;throw error}if(!response.ok||result.ok===false){const error=new Error(result.error?.message||'请求失败');error.code=result.error?.code;error.details=result.error?.details||{};error.status=response.status;throw error}return result.data??result}catch(error){captureClientError(error,{path});throw error}}
async function officialReferenceSearch(query){return api(`/official-references/search?q=${encodeURIComponent(query)}&limit=18`)}
function toast(message,bad=false){const el=$('#toast');if(!el)return;el.textContent=message;el.classList.toggle('error',bad);el.classList.toggle('actionable',Boolean(bad&&state.feedbackError));if(bad&&state.feedbackError){const button=document.createElement('button');button.type='button';button.dataset.toastReport='1';button.className='toast-report';button.textContent='报告此错误';el.appendChild(button)}el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),5200)}
function dismissToast(){const el=$('#toast');if(!el)return;clearTimeout(toast.timer);el.textContent='';el.classList.remove('show','error','actionable')}
function setBusy(message){const el=$('#saveStatus');if(!el)return;el.textContent=message;el.dataset.state=/失败|未保存|未完成/.test(message)?'error':/正在|联系/.test(message)?'busy':'saved'}
function brief(){return state.work?.artifacts.find(x=>x.kind==='brief')?.current_revision?.content}
function blueprint(){return state.work?.artifacts.find(x=>x.kind==='story_blueprint')?.current_revision?.content}
function scenes(){return (state.work?.chapters||[]).flatMap(ch=>ch.scenes.map(s=>({...s,chapterTitle:ch.title})))}
function selectedScene(){return scenes().find(s=>s.id===state.sceneId)||scenes()[0]}
function pendingProposal(){const scene=selectedScene();return state.work?.proposals.find(p=>p.kind==='scene_script'&&p.scope_id===scene?.id&&p.status==='pending')}
function recommendedStage(){if(state.work?.releases?.length)return'release';if(scenes().some(s=>s.current_revision_id))return'draft';if(scenes().length||state.work?.chapters?.length)return'structure';if(blueprint())return'blueprint';return'brief'}
async function refreshAgentPresentation(){
  const thread=workConversationThread();
  if(!state.work?.id||!thread?.id){state.agentPresentation=null;return}
  try{state.agentPresentation=await api(`/works/${state.work.id}/threads/${thread.id}/agent-presentation?limit=80`)}catch(error){state.agentPresentation=null}
}
async function refreshCurrentProjection(){
  if(!state.work||state.currentProjectionLoading)return state.currentProjection;
  const workId=state.work.id,workVersion=state.work.version;
  state.currentProjectionLoading=true;
  try{
    const projection=await api(`/works/${workId}/current-projection`);
    if(state.work?.id===workId){state.currentProjection=projection;state.currentProjectionVersion=workVersion}
    return projection;
  }catch(error){
    if(state.work?.id===workId){state.currentProjection=null;state.currentProjectionVersion=null}
    captureClientError(error,{source:'current-projection',work_id:workId});
    return null;
  }finally{state.currentProjectionLoading=false}
}
async function refreshUserStatus(){
  if(!state.work||state.userStatusLoading)return state.userStatus;
  const workId=state.work.id;
  state.userStatusLoading=true;
  try{
    const status=await api(`/works/${workId}/user-status`);
    if(state.work?.id===workId){state.userStatus=status;state.userStatusVersion=status.work_version}
    return status;
  }catch(_){
    if(state.work?.id===workId){state.userStatus=null;state.userStatusVersion=null}
    return null;
  }finally{state.userStatusLoading=false}
}
function ensureUserStatus(){
  if(!state.work||state.userStatusLoading||state.userStatusVersion===state.work.version)return;
  const workId=state.work.id;
  refreshUserStatus().then(()=>{if(state.work?.id===workId)render()});
}
function currentProjectionReady(){return Boolean(state.currentProjection&&state.currentProjectionVersion===state.work?.version)}
function ensureCurrentProjection(){
  if(!state.work||currentProjectionReady()||state.currentProjectionLoading)return;
  refreshCurrentProjection().then(()=>{if(state.stage==='references')render()});
}
async function loadWork(id,{resume=true}={}){state.work=await api('/works/'+id);state.userStatus=null;state.userStatusVersion=null;state.currentProjection=null;state.currentProjectionVersion=null;state.releaseDetails={};state.releaseDetailLoading={};state.releaseDetailErrors={};state.sceneDiffSelections={};const target=artifact('writing_target')||{};const targetChapter=state.work.chapters?.find(ch=>ch.id===target.chapter_id);const fallbackChapter=state.work.chapters?.find(ch=>ch.status!=='placeholder')||state.work.chapters?.[0];state.writingChapterId=targetChapter?.id||fallbackChapter?.id||'';const availableScenes=scenes(),anchoredScene=target.anchor_scene_id&&availableScenes.find(scene=>scene.id===target.anchor_scene_id&&scene.chapter_id===state.writingChapterId);state.sceneId=anchoredScene?.id||(availableScenes.some(scene=>scene.id===state.sceneId)?state.sceneId:state.work.chapters?.find(ch=>ch.id===state.writingChapterId)?.scenes?.[0]?.id||availableScenes[0]?.id||null);await Promise.all([refreshAgentPresentation(),refreshCurrentProjection(),refreshUserStatus()]);if(resume){state.stage='overview';state.surface='works'}render()}
async function boot(){try{const caps=await api('/capabilities');state.capabilities=caps;const provider=caps.providers?.[0];$('#providerBadge').textContent=provider?.is_simulation?'本地模式':'模型已连接';await api('/settings/feedback/sync',{method:'POST',body:'{}'});state.works=await api('/works');if(state.works[0])await loadWork(state.works[0].id);else render()}catch(error){render();toast(error.message,true)}finally{document.body.classList.remove('app-loading');$('#bootScreen')?.setAttribute('hidden','');if(!state.work)requestAnimationFrame(()=>requestAnimationFrame(()=>{$('#intentMessage')?.focus();startOnboardingTour()}));else scheduleWorkDecisionFocus()}}
function isCompactViewport(){return window.matchMedia('(max-width: 640px)').matches}
let previousCompactViewport=isCompactViewport();
window.addEventListener('resize',()=>{
  const compact=isCompactViewport();
  if(compact===previousCompactViewport)return;
  previousCompactViewport=compact;
  if(['agent','context'].includes(state.mobileView))render();
});
function render(){
  // Phone-only views must not survive a resize into the desktop workbench.
  if(!isCompactViewport()&&['agent','context'].includes(state.mobileView))state.mobileView='writing';
  const app=$('#app');
  app?.classList.toggle('overview-stage',Boolean(state.work&&state.mobileView==='writing'&&state.stage==='overview'));
  app?.classList.toggle('tasks-stage',Boolean(state.work&&state.mobileView==='tasks'));
  renderChrome();renderWorkspace();decorateLibrary();decorateSceneContext();renderInspector();ensureUserStatus()
}
function workActivityCounts(items=[]){
  const list=Array.isArray(items)?items:[];
  return {
    running:list.filter(item=>['running','ready'].includes(item.status)).length,
    pending:list.filter(item=>item.status==='waiting_user').length,
  };
}

function setCrumb(work,scope){const crumb=$('#crumb');if(!crumb)return;if(work){const label=scope||'写作工作台';const compactLabel=window.matchMedia?.('(max-width: 760px)').matches&&label.includes('/')?`… / ${label.split('/').pop().trim()}`:label;crumb.innerHTML=`<span class="crumb-work" title="${esc(work.title)}">${esc(work.title)}</span><span class="crumb-divider" aria-hidden="true"> / </span><span class="crumb-scope" title="${esc(label)}">${esc(compactLabel)}</span>`;crumb.setAttribute('aria-label',`${work.title} / ${label}`)}else{const label=scope?`HaloCue / ${scope}`:'HaloCue / 写作工作台';crumb.textContent=label;crumb.setAttribute('aria-label',label)}}
function renderChrome(){const work=state.work;$('#workTitle').textContent=work?.title||'尚未建立作品';setCrumb(work,work?(state.mobileView==='writing'?stageLabel(state.stage):mobileLabel(state.mobileView)):null);$('#versionStatus').textContent='';$('#taskStatus').textContent='';$('#saveStatus').textContent=work?'已保存':'等待建立作品';const headerNewWork=$('[data-header-new-work]');if(headerNewWork)headerNewWork.hidden=!work;const workSurfaceNote=$('.work-surface-note');if(workSurfaceNote)workSurfaceNote.hidden=!work;const stageList=$('#stageList');if(stageList)stageList.hidden=!work;$$('[data-stage]').forEach(b=>b.classList.toggle('active',b.dataset.stage===state.stage));const primarySection=state.mobileView==='tasks'?'tasks':state.stage==='references'?'works':(['overview','brief','blueprint'].includes(state.stage)?'works':'writing');$$('[data-section]').forEach(b=>b.classList.toggle('active',b.dataset.section===primarySection));const mobileActive=state.stage==='references'&&state.mobileView==='writing'?'works':state.mobileView;$$('[data-mobile]').forEach(b=>b.classList.toggle('active',b.dataset.mobile===mobileActive));const tree=$('#sceneTree');const treeChapters=state.stage==='structure'?(work?.chapters||[]):(work?.chapters||[]).filter(chapter=>chapter.scenes.length);tree.innerHTML=treeChapters.map(ch=>`<p class="tree-chapter">${esc(ch.title)}</p>${ch.scenes.map(s=>`<button class="scene-link ${s.id===state.sceneId?'active':''}" data-scene="${s.id}">${esc(s.title)} <small>· ${esc(s.status)}</small></button>`).join('')}`).join('');const switchList=$('#workSwitchList');if(switchList)switchList.innerHTML=state.works.length?state.works.map(item=>`<button type="button" class="work-switch-row ${item.id===work?.id?'active':''}" data-select-work="${esc(item.id)}"><span><b>${esc(item.title)}</b><small>${item.id===work?.id?'当前打开':'作品数据独立保存'}</small></span><em>${item.id===work?.id?'当前':''}</em></button>`).join(''):'<p class="form-note">尚未建立作品。</p>'}
function stageLabel(stage){return({overview:'作品总览',brief:'全作创作方向',blueprint:'全作故事方向',structure:'章节细纲',draft:'逐场写作',references:'创作资料',release:'检查并发布'})[stage]}
function mobileLabel(view){return({works:'作品结构',context:'上下文',tasks:'任务'})[view]||'写作'}
function frame(kicker,title,lede,body){return `<div class="workspace-inner"><p class="eyebrow">${kicker}</p><h2>${title}</h2><p class="lede">${lede}</p>${body}</div>`}
function renderWorkspace(){const el=$('#workspace');if(!state.work){el.innerHTML=frame('WRITING WORKSPACE','从一句想法开始','这里保存作品结构、正文版本和审查决定。模型只能提出候选，不会直接覆盖正式内容。',intentComposerMarkup());bindIntentComposer(el);queueMicrotask(()=>el.querySelector('#intentMessage')?.focus());return}if(state.mobileView==='works')renderMobileWorks(el);else if(state.mobileView==='context')renderMobileContext(el);else if(state.mobileView==='tasks')renderMobileTasks(el);else if(state.stage==='overview')renderOverview(el);else if(state.stage==='references')renderReferences(el);else if(state.stage==='brief')renderBrief(el);else if(state.stage==='blueprint')renderBlueprint(el);else if(state.stage==='structure')renderStructure(el);else if(state.stage==='draft')renderDraft(el);else if(state.stage==='release')renderRelease(el)}
function renderOverview(el){
  const work=state.work, sceneList=scenes(), total=sceneList.length, drafted=sceneList.filter(scene=>scene.current_revision_id).length;
  const cards=libraryCards(), world=worldBible(), pending=work.proposals.filter(item=>item.status==='pending').length;
  const blocker=(work.review_findings||[]).filter(item=>item.status==='open'&&item.severity==='blocking').length;
  let next={stage:'brief',title:'先保存写作想法',detail:'把一句想法、主要角色和写作范围存成 Brief。',label:'开始写作想法'};
  if(brief()&&!blueprint())next={stage:'blueprint',title:'确认故事方向',detail:'系统会生成一份可检查的 StoryBlueprint，你决定是否采用。',label:'确认故事方向'};
  else if(blueprint()&&!work.chapters.length)next={stage:'structure',title:'建立章节与场景',detail:'先给作品一个章节，再把它拆成稳定 ID 的场景。',label:'建立结构'};
  else if(total&&drafted<total)next={stage:'draft',title:'开始下一场写作',detail:`${total-drafted} 个场景还没有正文，候选会先进入 Proposal。`,label:'打开逐场写作'};
  else if(pending)next={stage:'draft',title:'审查待处理候选',detail:`有 ${pending} 份候选等待采纳、局部修改或退回。`,label:'查看候选'};
  else if(blocker)next={stage:'draft',title:'处理审查阻塞项',detail:`有 ${blocker} 个阻塞项，解决后才能继续冻结发布。`,label:'处理审查'};
  else if(total)next={stage:'release',title:'运行全篇审查',detail:'确认连续性、人物约束和当前正文后，再生成制作定稿。',label:'检查并发布'};
  const progress=total?Math.round(drafted/total*100):0;
  const worldEntities=(world.entities||[]).filter(item=>item.status!=='archived');
  el.innerHTML=`<div class="overview-workbench"><header class="overview-header"><div><p class="eyebrow">WORK OVERVIEW</p><h2>${esc(work.title)}</h2><p>这是这部作品的控制台。系统保存了什么、现在卡在哪里、下一步由你决定，都从这里开始。</p></div><button class="quiet" data-stage-jump="references">打开资料库</button></header><section class="overview-next"><div><span class="overview-label">推荐下一步</span><h3>${next.title}</h3><p>${next.detail}</p></div><button class="primary" data-stage-jump="${next.stage}">${next.label}</button></section><section class="overview-grid"><div class="overview-stat"><b>${progress}%</b><span>正文进度</span><small>${drafted}/${total||0} 个场景已采纳正文</small><div class="progress-track"><i style="width:${progress}%"></i></div></div><button class="overview-stat overview-link" data-stage-jump="references" data-library-target="characters"><b>${cards.length}</b><span>人物卡</span><small>${cards.filter(card=>card.source_type==='official_reference').length} 原作参考 · ${cards.filter(card=>card.source_type==='custom').length} 自定义</small></button><button class="overview-stat overview-link" data-stage-jump="references" data-library-target="world"><b>${worldEntities.length}</b><span>世界观卡</span><small>${worldEntities.filter(item=>item.confidence_status==='confirmed').length} 已确认 · ${world.rules.length} 条规则</small></button><button class="overview-stat overview-link" data-stage-jump="draft"><b>${pending}</b><span>待处理候选</span><small>${blocker} 个开放阻塞项</small></button></section><section class="overview-columns"><div><div class="overview-section-head"><h3>作品结构</h3><button class="quiet" data-stage-jump="structure">管理章节</button></div>${work.chapters.length?work.chapters.map(ch=>`<div class="overview-chapter"><b>${esc(ch.title)}</b><span>${ch.scenes.length} 个场景</span><small>${ch.scenes.filter(scene=>scene.current_revision_id).length} 已完成</small></div>`).join(''):'<p class="overview-empty">还没有章节。下一步会引导你建立第一章。</p>'}</div><div><div class="overview-section-head"><h3>系统状态</h3><span class="status-chip ${pending?'amber':''}">${pending?'等待你的决定':'暂无待处理项'}</span></div><ul class="overview-checks"><li><i class="check-dot"></i>作品与版本已持久化</li><li><i class="check-dot"></i>${cards.length?'人物卡已登记':'尚未建立人物卡'}</li><li><i class="check-dot"></i>${worldEntities.length?'世界观卡已登记':'尚未建立 BA/自定义世界观卡'}</li></ul></div></section></div>`;
}
function renderMobileWorks(el){el.innerHTML=frame('WORK TREE','作品结构','从章节进入一场写作。场景 ID 不会因标题变化而改变。',`${state.work.chapters.map(ch=>`<section class="artifact"><h3>${esc(ch.title)}</h3>${ch.scenes.map(s=>`<div class="structure-row"><div><h3>${esc(s.title)}</h3><p>${esc(s.contract.goal||'场景目标待定')} · ${esc(s.status)}</p></div><button class="quiet" data-scene-open="${s.id}">打开</button></div>`).join('')||'<p>本章还没有场景。</p>'}</section>`).join('')||'<div class="notice">作品还没有章节。</div>'}<div class="actions"><button class="primary" data-mobile="writing">返回写作</button><button class="quiet" data-stage-jump="structure">编辑结构</button></div>`)}
function renderMobileContext(el){
  const scene=selectedScene(),c=state.context,readiness=sceneReadinessView(c);
  el.innerHTML=frame('SCENE CONTEXT','当前场景上下文',scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'尚未选择场景',`${c?`<div class="notice ${readiness.canRun?'good':'bad'}"><b>${esc(readiness.label)}</b> · ${esc(readiness.detail)}</div><section class="artifact"><h3>固定输入</h3><p>规则包：${esc(c.rules.pack_version)}</p><p>单一模式：${esc(c.rules.mode)}</p><p>来源修订：${c.source_revision_ids.length} 个</p><p>资料证据：${c.reference_files?.length||0} 个（不会自动变成事实）</p><p>缺少运行时人物卡：${esc(readiness.missingCharacters.join('、')||'无')}</p></section>`:'<div class="notice">尚未装配本场上下文。回到写作页后系统会自动准备。</div>'}<div class="actions"><button class="primary" data-mobile="writing">返回写作</button>${scene?'<button class="quiet" data-action="assemble-context">重新准备</button>':''}</div>`)}
function renderMobileTasks(el){
  const items=state.work.runs.flatMap(run=>run.work_items.map(item=>({...item,runId:run.id}))).reverse();
  const statusLabel={ready:'等待执行',running:'正在运行',waiting_user:'等待你的决定',succeeded:'已完成',failed:'运行失败',cancelled:'已取消',skipped:'已跳过'};
  const typeLabel={'agent.scene.draft.generate':'场景起草','agent.scene.draft.rewrite':'场景改写','agent.scene.review':'场景审查','agent.continuity.review':'连续性审查','agent.release.review':'发布审查','scene.draft.generate':'模拟场景候选'};
  let primaryActionAssigned=false;
  const body=items.length?`<div class="task-list">${items.map((item,index)=>{
    const attempt=item.attempts?.at(-1),agentRunId=item.acceptance?.agent_run_id;
    const retryable=Boolean(item.error?.retryable&&agentRunId&&['ready','failed'].includes(item.status));
    const inputRefs=item.input_refs||[],outputRefs=item.output_refs||[],attempts=item.attempts||[];
    const scene=item.scope_type==='scene'?scenes().find(candidate=>candidate.id===item.scope_id):null;
    const taskName=typeLabel[item.type]||'后台任务';
    const scopeLabel=scene?`场景「${scene.title}」`:item.scope_type==='work'?'当前作品':'当前任务';
    const recovered=item.status==='failed'&&items.slice(0,index).some(newer=>newer.scope_type===item.scope_type&&newer.scope_id===item.scope_id&&['waiting_user','succeeded'].includes(newer.status));
    const displayStatus=recovered?'已恢复':statusLabel[item.status]||'状态已更新';
    const summary=recovered?'之前的运行没有产生可用结果，后续运行已经继续了这个流程。':item.error?.message||(item.status==='ready'?'任务已经保存，等待系统开始。':item.status==='waiting_user'?'结果已经生成，正在等待你审查候选。':'运行记录与正式内容分开保存。');
    const recentStatus=attempt?`最近一次运行 · ${esc(statusLabel[attempt.status]||'状态已更新')}`:'尚未开始运行';
    const attemptHistory=attempts.length?`<ol class="task-attempts">${attempts.map(entry=>`<li><b>第 ${esc(entry.ordinal)} 次运行</b><span>${esc(statusLabel[entry.status]||'状态已更新')}</span><small>${entry.output_ref?'结果已安全保存':entry.error_code?'未生成可用结果':'没有生成结果'}</small></li>`).join('')}</ol>`:'<p>系统尚未开始这项任务。</p>';
    let action='';
    if(retryable&&!recovered){
      action=`<button class="${primaryActionAssigned?'quiet':'primary'}" type="button" data-task-retry-run="${esc(agentRunId)}">重新运行</button>`;
    }else if(!recovered&&scene&&item.status==='waiting_user'){
      action=`<button class="${primaryActionAssigned?'quiet':'primary'}" type="button" data-task-open-scope="${esc(scene.id)}" data-task-stage="draft">审查候选</button>`;
    }else if(!recovered&&scene&&item.status==='failed'){
      action=`<button class="${primaryActionAssigned?'quiet':'primary'}" type="button" data-task-open-scope="${esc(scene.id)}" data-task-stage="draft">回到场景处理</button>`;
    }else if(!recovered&&item.scope_type==='work'&&item.status==='failed'){
      action=`<button class="${primaryActionAssigned?'quiet':'primary'}" type="button" data-task-open-scope="work" data-task-stage="release">回到发布检查</button>`;
    }
    if(action)primaryActionAssigned=true;
    return `<section class="task-item ${recovered?'recovered':item.status}"><div class="task-item-head"><div><span>${esc(taskName)}</span><b>${esc(displayStatus)}</b></div><em>${attempts.length||item.attempt_count||0} 次运行</em></div><p>${esc(summary)}</p><small>${recovered?'已由后续运行恢复':recentStatus}</small><details class="task-details" data-task-details="${esc(item.id)}"><summary>查看详情</summary><dl><div><dt>任务位置</dt><dd>${esc(scopeLabel)}</dd></div><div><dt>准备内容</dt><dd>${inputRefs.length?`已固定 ${inputRefs.length} 项输入`:'没有需要固定的输入'}</dd></div><div><dt>结果</dt><dd>${outputRefs.length?`已保存 ${outputRefs.length} 项结果`:'尚无可审查结果'}</dd></div>${item.error?`<div><dt>失败原因</dt><dd>${esc(item.error.message||'本次运行没有完成。')}</dd></div>`:''}</dl>${attemptHistory}</details>${action}</section>`;
  }).join('')}</div>`:'<div class="notice good">当前没有后台任务。</div>';
  el.innerHTML=frame('TASKS','后台任务','这里只保留当前进度、失败原因和一个明确的恢复入口。',`${body}<div class="actions"><button class="${primaryActionAssigned?'quiet':'primary'}" data-mobile="writing">返回写作</button></div>`);
}
function artifact(kind){return state.work.artifacts.find(x=>x.kind===kind)?.current_revision?.content}
function renderReferences(el){const canon=artifact('work_canon')||{facts:[]},cards=state.work.artifacts.filter(x=>x.kind==='character_card').map(x=>x.current_revision?.content).filter(Boolean),files=state.work.reference_files||[];el.innerHTML=frame('REFERENCES','确认这部作品的事实','事实、人物卡和资料分别保存，有来源才能成为场景上下文。',`<div class="step-band"><strong>现在需要你决定</strong><span>确认哪些事实与人物声音可以被下一场读取</span></div><div class="reference-grid"><section class="artifact"><p class="eyebrow">WORK CANON</p><h3>已确定的事实</h3>${canon.facts.length?`<ul class="fact-list">${canon.facts.map(f=>`<li><b>${esc(f.text)}</b><small>${esc(f.source)} · ${esc(f.confidence_status)}</small></li>`).join('')}</ul>`:'<p class="lede">还没有已确认事实。</p>'}<form id="canonForm"><label>新增事实<textarea name="text" placeholder="例如：旧机器没有接通电源"></textarea></label><label>来源<input name="source" placeholder="用户确认 / 场景修订 / 已登记资料"></label><div class="actions"><button class="primary">确认事实</button></div></form></section><section class="artifact"><p class="eyebrow">CHARACTER CARDS</p><h3>人物声音与边界</h3>${cards.length?cards.map(c=>`<div class="card-row"><b>${esc(c.name)}</b><small>${esc((c.voice_anchors||[]).join(' / ')||'无声音锚点')}<br>${esc((c.source_refs||[]).join('、'))}</small></div>`).join(''):'<p class="lede">还没有人物卡。</p>'}<form id="characterForm"><label>角色名称<input name="name" placeholder="爱丽丝"></label><label>声音锚点<input name="voice" placeholder="短句、直接、把判断落到当前操作"></label><label>OOC 红线<input name="ooc" placeholder="不替他人说出隐藏动机"></label><label>来源<input name="source" placeholder="官方剧情索引 / 用户确认"></label><div class="actions"><button class="primary">保存人物卡</button></div></form></section><section class="artifact"><p class="eyebrow">REFERENCE FILES</p><h3>已登记资料</h3>${files.length?files.map(f=>`<div class="card-row"><b>${esc(f.title)}</b><small>${esc(f.source_label)} · ${esc(f.trust_status)}</small></div>`).join(''):'<p class="lede">还没有资料文件。</p>'}<form id="referenceForm"><label>资料名称<input name="title" placeholder="场景前提笔记"></label><label>来源标签<input name="source_label" placeholder="用户导入"></label><label>资料内容<textarea name="content" placeholder="资料正文会以版本化文件保存"></textarea></label><div class="actions"><button class="quiet">登记资料</button></div></form></section></div>`)}
function renderBrief(el){const b=brief()||{};el.innerHTML=frame('01 / BRIEF','你想写一个怎样的故事？','先固定创作意图、角色与范围。保存后它会成为可追溯的创意简报修订。',`<div class="step-band"><strong>现在需要你决定</strong><span>一句想法、写作模式和主要角色</span></div><form id="briefForm" class="field-grid"><label class="wide">一句想法<textarea name="idea" required placeholder="例如：凯伊发现游戏开发部的旧机器在深夜自行启动">${esc(b.idea)}</textarea></label><label>写作模式<select name="mode"><option value="bond_short" ${b.mode==='bond_short'?'selected':''}>羁绊短场景</option><option value="main_battle" ${b.mode==='main_battle'?'selected':''}>主线与战斗</option><option value="long_comedy" ${b.mode==='long_comedy'?'selected':''}>长篇喜剧</option><option value="text_reading" ${b.mode==='text_reading'?'selected':''}>小说化阅读</option></select></label><label>目标长度<select name="target_length"><option value="short">短场景</option><option value="chapter">单章</option><option value="long">长篇</option></select></label><label class="wide">主要角色<input name="characters" value="${esc((b.characters||[]).join('、'))}" placeholder="爱丽丝、凯伊"></label><label class="wide">额外约束<textarea name="constraints" placeholder="不可提前揭示的事实、希望保留的关系距离……">${esc(b.constraints)}</textarea></label><label class="check"><span><input type="checkbox" name="has_sensei" ${b.has_sensei?'checked':''}> 老师在场</span></label><div class="actions wide"><button class="primary" type="submit">保存写作想法</button><button class="quiet" type="button" data-stage-jump="blueprint" ${brief()?'':'disabled'}>继续确认故事方向</button></div></form>`)}
function renderBlueprint(el){const b=blueprint();el.innerHTML=frame('02 / STORY BLUEPRINT','确认故事方向','系统把写作想法整理成结构化方向。当前纵切使用明确标注的本地模拟 Provider。',`<div class="step-band"><strong>${b?'系统已整理故事方向':'系统尚未生成方向'}</strong><span>${b?'检查冲突、范围与停止方式':'先保存写作想法'}</span></div>${!brief()?'<div class="notice bad">请先回到“写作想法”保存创意简报。</div>':b?`<div class="notice">模拟结果 · 未调用真实模型，也未自动写入正文。</div><section class="artifact"><h3>${esc(b.title)}</h3><p>${esc(b.premise)}</p><p><b>核心冲突：</b>${esc(b.central_conflict)}</p><p><b>主题方向：</b>${esc(b.theme)}</p><ol class="direction-list">${b.direction.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></section><div class="actions"><button class="primary" data-stage-jump="structure">确认并建立章节</button><button class="quiet" data-action="generate-blueprint">重新生成方向</button></div>`:`<div class="empty-state"><div class="number">02</div><h3>把一句想法整理成可检查的方向</h3><p class="lede">结果会单独保存为 StoryBlueprint，不与聊天或正文混在一起。</p><button class="primary" data-action="generate-blueprint">生成故事方向</button></div>`}`)}
function structureSeed(){return {chapter_ids:(state.work?.chapters||[]).map(chapter=>chapter.id),scene_placements:(state.work?.chapters||[]).flatMap(chapter=>chapter.scenes.map(scene=>({scene_id:scene.id,chapter_id:chapter.id})))} }
function structureDraft(){const canonical=structureSeed(),draft=state.structureDraft;const needsRefresh=!draft||draft.workId!==state.work?.id||(!state.structureDirty&&(draft.chapter_ids.length!==canonical.chapter_ids.length||draft.scene_placements.length!==canonical.scene_placements.length||canonical.chapter_ids.some(id=>!draft.chapter_ids.includes(id))||canonical.scene_placements.some(item=>!draft.scene_placements.some(entry=>entry.scene_id===item.scene_id))));if(needsRefresh){state.structureDraft={workId:state.work?.id,...canonical};state.structureDirty=false}return state.structureDraft}
function draftScenesForChapter(chapterId){const lookup=new Map(scenes().map(scene=>[scene.id,scene]));return structureDraft().scene_placements.filter(item=>item.chapter_id===chapterId).map(item=>lookup.get(item.scene_id)).filter(Boolean)}
function resetStructureDraft(){state.structureDraft={workId:state.work?.id,...structureSeed()};state.structureDirty=false}
function moveListEntry(items,from,to){if(to<0||to>=items.length)return false;const [entry]=items.splice(from,1);items.splice(to,0,entry);return true}
function moveDraftChapter(chapterId,direction){const draft=structureDraft(),from=draft.chapter_ids.indexOf(chapterId);if(from<0||!moveListEntry(draft.chapter_ids,from,from+(direction==='up'?-1:1)))return;state.structureDirty=true;render()}
function moveDraftScene(sceneId,direction){const draft=structureDraft(),entry=draft.scene_placements.find(item=>item.scene_id===sceneId);if(!entry)return;const siblings=draft.scene_placements.filter(item=>item.chapter_id===entry.chapter_id),from=siblings.findIndex(item=>item.scene_id===sceneId),to=from+(direction==='up'?-1:1);if(to<0||to>=siblings.length)return;const other=siblings[to],fromIndex=draft.scene_placements.indexOf(entry),toIndex=draft.scene_placements.indexOf(other);[draft.scene_placements[fromIndex],draft.scene_placements[toIndex]]=[draft.scene_placements[toIndex],draft.scene_placements[fromIndex]];state.structureDirty=true;render()}
function placeDraftScene(sceneId,chapterId){const draft=structureDraft(),from=draft.scene_placements.findIndex(item=>item.scene_id===sceneId);if(from<0||!draft.chapter_ids.includes(chapterId)||draft.scene_placements[from].chapter_id===chapterId)return;const [entry]=draft.scene_placements.splice(from,1);entry.chapter_id=chapterId;const lastTarget=[...draft.scene_placements].map((item,index)=>item.chapter_id===chapterId?index:-1).filter(index=>index>=0).pop();draft.scene_placements.splice(lastTarget===undefined?draft.scene_placements.length:lastTarget+1,0,entry);state.structureDirty=true;render()}
function renderStructure(el){const chapters=state.work.chapters,draft=structureDraft(),hasChanges=state.structureDirty;el.innerHTML=frame('03 / STRUCTURE','章节安排','章节和场景是作品的骨架。调整位置不会改变场景 ID、正文修订或资料关联；保存后需要重新运行全篇审查。',`<section class="structure-command"><div><p class="eyebrow">STORY ORDER</p><h3>${chapters.length?'整理章节与场景':'现在需要你决定'}</h3><p>${chapters.length?(hasChanges?'结构有未保存调整。保存后，旧全篇审查会过期。':'拖动前先用方向按钮调整；每次保存都可追溯。'):'先建立第一章，再把故事拆成稳定场景。'}</p></div>${chapters.length?`<div class="structure-command-actions"><span class="structure-save-state ${hasChanges?'dirty':'saved'}">${hasChanges?'未保存调整':'当前顺序已保存'}</span><button class="quiet" type="button" data-structure-reset ${hasChanges?'':'disabled'}>撤销调整</button><button class="primary" type="button" data-structure-save ${hasChanges?'':'disabled'}>保存章节安排</button></div>`:''}</section><div class="structure-board">${chapters.map(ch=>{const chapterPosition=draft.chapter_ids.indexOf(ch.id),orderedScenes=draftScenesForChapter(ch.id);return `<section class="chapter-lane" data-chapter-lane="${esc(ch.id)}"><header class="chapter-lane-head"><div><p>第 ${String(chapterPosition+1).padStart(2,'0')} 章</p><h3>${esc(ch.title)}</h3><small>${orderedScenes.length} 个场景 · ${orderedScenes.filter(scene=>scene.current_revision_id).length} 个已有正文</small></div><div class="lane-actions"><button class="icon-button" type="button" title="章节上移" aria-label="章节上移" data-structure-chapter-move="up" data-chapter-id="${esc(ch.id)}" ${chapterPosition===0?'disabled':''}>↑</button><button class="icon-button" type="button" title="章节下移" aria-label="章节下移" data-structure-chapter-move="down" data-chapter-id="${esc(ch.id)}" ${chapterPosition===draft.chapter_ids.length-1?'disabled':''}>↓</button><button class="quiet" type="button" data-structure-add-scene="${esc(ch.id)}">添加场景</button></div></header><div class="scene-arrangement-list">${orderedScenes.length?orderedScenes.map((scene,index)=>`<article class="scene-arrangement"><div class="scene-order">${String(index+1).padStart(2,'0')}</div><div class="scene-arrangement-copy"><b>${esc(scene.title)}</b><p>${esc(scene.contract.goal||'尚未填写本场目标')}</p><small>${scene.current_revision_id?'已有正文':'尚未起草'} · ${esc(scene.id)}</small></div><div class="scene-arrangement-actions"><button class="icon-button" type="button" title="场景上移" aria-label="场景上移" data-structure-scene-move="up" data-scene-id="${esc(scene.id)}" ${index===0?'disabled':''}>↑</button><button class="icon-button" type="button" title="场景下移" aria-label="场景下移" data-structure-scene-move="down" data-scene-id="${esc(scene.id)}" ${index===orderedScenes.length-1?'disabled':''}>↓</button><label class="scene-chapter-select"><span>放入</span><select data-structure-scene-target="${esc(scene.id)}">${draft.chapter_ids.map((targetId,targetIndex)=>{const target=chapters.find(item=>item.id===targetId);return `<option value="${esc(targetId)}" ${targetId===ch.id?'selected':''}>第${targetIndex+1}章 · ${esc(target?.title||'')}</option>`}).join('')}</select></label><button class="quiet" type="button" data-scene-open="${esc(scene.id)}">写本场</button></div></article>`).join(''):'<div class="scene-arrangement-empty">本章还没有场景。可以先添加一场，再安排到合适的位置。</div>'}</div></section>`}).join('')||'<div class="empty-state"><div class="number">03</div><h3>先建立第一章</h3><p class="lede">章节与场景是正文的稳定结构，不依赖标题或数组顺序作为身份。</p></div>'}</div><div class="actions structure-footer-actions"><button class="primary" data-structure-add-chapter>${chapters.length?'添加章节':'建立第一章'}</button>${chapters.length?`<button class="quiet" data-structure-add-scene="${chapters[0].id}">添加场景</button>`:''}</div>`)}
function renderDraft(el){const scene=selectedScene(),proposal=pendingProposal(),findings=(state.work.review_findings||[]).filter(f=>f.scene_id===scene?.id&&f.status==='open');if(!scene){el.innerHTML=frame('04 / SCENE DRAFT','还没有可写的场景','先建立章节和场景，再为一个稳定 Scene ID 装配上下文。','<button class="primary" data-stage-jump="structure">建立场景</button>');return}const current=state.work.artifacts.find(a=>a.kind==='scene_script'&&a.scope_id===scene.id)?.current_revision?.content?.text||'';el.innerHTML=frame('04 / SCENE DRAFT',esc(scene.title),`${esc(scene.chapterTitle)} · ${esc(scene.contract.location||'地点待定')} · ${esc(scene.contract.goal||'目标待定')}`,`<div class="step-band"><strong>${proposal?'现在需要你审查候选':current?'正文已采纳，可继续生成新候选':'系统可以装配本场上下文'}</strong><span>Agent 作用域：仅当前场景与固定输入修订</span></div>${findings.length?`<section class="review-findings ${findings.some(x=>x.severity==='blocking')?'has-blocker':''}"><p class="eyebrow">REVIEW FINDINGS</p><h3>本场需要你的决定</h3>${findings.map(x=>`<div class="finding-row"><div><b>${esc(x.severity)}</b><p>${esc(x.message)}</p></div><button class="quiet" data-resolve-finding="${x.id}">处理</button></div>`).join('')}</section>`:''}${proposal?`<div class="notice">模拟候选 · 可修改后部分采纳。采纳才会建立新的正文修订。</div><div class="proposal-layout"><label>候选正文<textarea class="editor" id="candidateText">${esc(proposal.candidate)}</textarea></label><div><label>与当前稿件的差异</label><pre class="diff-view">${proposal.diff.map(line=>`<span class="${line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-del':''}">${esc(line)}</span>`).join('\n')}</pre><p class="code-meta">Proposal ${proposal.id}<br>Base ${proposal.base_revision_id||'空白正文'}</p></div></div><div class="actions"><button class="primary" data-accept="${proposal.id}">采纳当前内容</button><button class="danger" data-reject="${proposal.id}">退回候选</button></div>`:`${current?`<label>当前正文<textarea class="editor" readonly>${esc(current)}</textarea></label>`:'<div class="notice">本场还没有正文。生成会先创建 WorkItem 和 JobAttempt，结果只进入 Proposal。</div>'}<div class="actions"><button class="primary" data-action="assemble-context">装配上下文</button><button class="quiet" data-action="review-scene" ${current?'':'disabled'}>检查本场</button><button class="quiet" data-action="generate-candidate">生成模拟候选</button></div>`}`)}
// The compatibility manuscript button shares the real Provider endpoint. Keep
// its completion message aligned with the runtime that actually produced it.
document.addEventListener('click',event=>{
  const button=event.target.closest?.('[data-action="generate-candidate"]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  (async()=>{try{
    button.disabled=true;setBusy('正在运行 scene.draft.generate');
    const result=await api(`/works/${state.work.id}/scenes/${selectedScene().id}/candidate:generate`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});
    state.work=result.work;
    toast(`${result.simulation?'模拟':'真实 Provider'}候选已生成，等待你的决定`);
    render();
  }catch(error){
    button.disabled=false;setBusy('候选未生成，正式正文没有修改');toast(error.message,true);
  }})();
},true);

function releaseSceneRevisionRefs(){return scenes().map(scene=>{const artifact=state.work?.artifacts?.find(item=>item.kind==='scene_script'&&item.scope_id===scene.id),revision=artifact?.current_revision;return {scene_id:scene.id,revision_id:scene.current_revision_id,content_hash:revision?.content_hash||null,asset_references:(scene.asset_references||[]).map(reference=>({reference_id:reference.id,asset_kind:reference.asset_kind,source_type:reference.source_type,source_asset_id:reference.source_asset_id,display_name:reference.display_name,source_version:reference.source_version,content_hash:reference.content_hash,content_hash_kind:reference.content_hash_kind,source_snapshot:reference.source_snapshot,production_copy:reference.production_copy||null}))}})}
function releaseDependencyRefs(){return (state.work?.artifacts||[]).filter(item=>['brief','story_blueprint','work_canon','world_bible','character_card'].includes(item.kind)&&item.current_revision_id).map(item=>({kind:item.kind,scope_type:item.scope_type,scope_id:item.scope_id,revision_id:item.current_revision_id,content_hash:item.current_revision?.content_hash||null})).sort((left,right)=>`${left.kind}:${left.scope_id}`.localeCompare(`${right.kind}:${right.scope_id}`))}
function releaseActiveWritingDigest(){const value=String(state.capabilities?.ba_writing_skill?.source_digest||'');return value.startsWith('sha256:')?value:`sha256:${value}`}
function latestWorkGate(kind){return (state.work?.gates||[]).filter(item=>item.kind===kind).sort((left,right)=>String(left.created_at||'').localeCompare(String(right.created_at||''))).at(-1)||null}
function releaseRefsEqual(left,right){return JSON.stringify(left||[])===JSON.stringify(right||[])}
function releaseAssetRefsEqual(left,right){const signature=items=>(items||[]).map(item=>[item.reference_id||item.id,item.asset_kind,item.source_type,item.source_asset_id,item.display_name,item.source_version,item.content_hash,item.content_hash_kind,JSON.stringify(item.source_snapshot||{}),JSON.stringify(item.production_copy||null)].map(value=>String(value??'')).join('\u001f')).sort();return releaseRefsEqual(signature(left),signature(right))}
function releaseSceneRefsEqual(left,right){const normalize=items=>(items||[]).map(item=>({scene_id:item.scene_id,revision_id:item.revision_id,content_hash:item.content_hash,asset_references:item.asset_references||[]})).sort((a,b)=>String(a.scene_id).localeCompare(String(b.scene_id)));const a=normalize(left),b=normalize(right);return a.length===b.length&&a.every((item,index)=>item.scene_id===b[index].scene_id&&item.revision_id===b[index].revision_id&&item.content_hash===b[index].content_hash&&releaseAssetRefsEqual(item.asset_references,b[index].asset_references))}
function releaseSnapshotDrift(snapshot,currentRefs,currentDependencies){if(!snapshot)return[];const previous=new Map((snapshot.scene_revision_refs||[]).map(item=>[item.scene_id,item]));const drift=[];for(const current of currentRefs){const prior=previous.get(current.scene_id);const scene=scenes().find(item=>item.id===current.scene_id);const title=scene?.title||current.scene_id;if(!prior){drift.push(`新增场景：${title}`);continue}if(prior.revision_id!==current.revision_id||prior.content_hash!==current.content_hash)drift.push(`正文变化：${title}`);else if(!releaseAssetRefsEqual(prior.asset_references,current.asset_references))drift.push(`素材引用变化：${title}`)}if((snapshot.scene_revision_refs||[]).some(item=>!currentRefs.some(current=>current.scene_id===item.scene_id)))drift.push('场景结构发生变化');const signature=item=>[item.kind,item.scope_type,item.scope_id,item.revision_id,item.content_hash].map(value=>String(value||'')).join('\u001f');const priorDeps=(snapshot.dependency_refs||[]).map(signature).sort(),currentDeps=(currentDependencies||[]).map(signature).sort();if(!releaseRefsEqual(priorDeps,currentDeps))drift.push('正式资料依赖发生变化');if(snapshot.writing_pack_version!==state.work?.active_writing_pack_version)drift.push('写作规则包版本发生变化');const configured=String(state.capabilities?.ba_writing_skill?.source_digest||'');const digest=configured.startsWith('sha256:')?configured:`sha256:${configured}`;if(snapshot.ba_writing_source_digest!==digest)drift.push('BA 写作来源发生变化');return drift}
function renderRelease(el){
  const releases=state.work.releases||[];
  const ready=scenes().length&&scenes().every(scene=>scene.current_revision_id);
  const sourceIds=scenes().map(scene=>scene.current_revision_id);
  const latestSources=releases[0]?JSON.parse(releases[0].source_revision_ids_json):[];
  const currentRefs=releaseSceneRevisionRefs(),currentDependencies=releaseDependencyRefs();
  const latestManifest=releases[0]?state.releaseDetails[releases[0].id]?.manifest:null;
  const latestRefs=latestManifest?.scenes?.map(scene=>({scene_id:scene.scene_id,revision_id:scene.revision_id,content_hash:scene.content_hash,asset_references:(latestManifest.asset_references||[]).find(group=>group.scene_id===scene.scene_id)?.references||[]}));
  const alreadyFrozen=ready&&sourceIds.length===latestSources.length&&sourceIds.every((id,index)=>id===latestSources[index])&&(!latestRefs||releaseSceneRefsEqual(latestRefs,currentRefs));
  const reviewGate=latestWorkGate('release.review'),snapshot=reviewGate?.snapshot;
  const drift=snapshot?releaseSnapshotDrift(snapshot,currentRefs,currentDependencies):[];
  const reviewCurrent=Boolean(snapshot&&!drift.length);
  const canFreeze=ready&&!alreadyFrozen&&reviewGate?.status==='passed'&&reviewCurrent;
  const assetCount=currentRefs.reduce((total,scene)=>total+(scene.asset_references||[]).length,0);
  const missingScene=scenes().find(scene=>!scene.current_revision_id);
  const preflight=canFreeze?`<section class="release-freeze-preflight" role="status"><header><div><p class="eyebrow">冻结前复核</p><h3>确认本次制作内容</h3><p>以下内容会作为本次制作定稿；生成定稿不会修改作品原件。</p></div><span>等待你的确认</span></header><dl><div><dt>场景正文</dt><dd>${currentRefs.length} 场</dd></div><div><dt>素材引用</dt><dd>${assetCount} 项</dd></div><div><dt>正式资料</dt><dd>${currentDependencies.length} 份</dd></div><div><dt>审查记录</dt><dd>2 项</dd></div></dl></section>`:'';
  const status=!ready?`还缺少 ${scenes().filter(scene=>!scene.current_revision_id).length} 个场景正文。`:reviewGate?`${reviewGate.status==='passed'&&reviewCurrent?'审查覆盖当前正文、素材与正式资料，未发现阻塞项':`审查 ${reviewGate.status==='passed'?'已过期':'未通过'}`} · 已检查 ${snapshot?.checked_scene_count||0} 个场景 · 阻塞项 ${snapshot?.blocking_finding_ids?.length||0}`:'尚未运行全篇审查。';
  const actions=!ready&&missingScene
    ? `<div class="actions"><button class="primary" data-release-missing-scene="${esc(missingScene.id)}">去完成「${esc(missingScene.title)}」</button></div>`
    : `<div class="actions"><button class="quiet" data-action="review-release">运行全篇审查</button><button class="primary" data-action="freeze-release" ${canFreeze?'':'disabled'}>${alreadyFrozen?'当前正文已冻结':'冻结新的发布版本'}</button></div>`;
  const releaseCards=releases.map(release=>`<section class="artifact"><h3>制作定稿 ${esc(release.display_version)}</h3><p>${release.production_run_id?'已送往 AA 制作':'尚未送往 AA 制作'}</p><div class="actions"><button class="quiet" data-handoff="${release.id}" ${release.production_run_id?'disabled':''}>${release.production_run_id?'已提交制作':'交给 AA 制作'}</button></div></section>`).join('');
  el.innerHTML=frame('检查与发布','检查并发布定稿','检查当前正文和素材，确认后再生成制作定稿。',`<div class="step-band"><strong>${alreadyFrozen?'当前正文已冻结':canFreeze?'全篇审查已通过':'等待全篇审查'}</strong><span>${alreadyFrozen?'正文或素材变化后可发布下一版':canFreeze?'现在由你决定是否冻结':ready?'先运行全篇审查，确认当前正文与依赖':'每个场景都必须有已采纳正文'}</span></div><div class="notice ${canFreeze||alreadyFrozen?'good':'bad'}">${status}</div>${ready&&drift.length?`<section class="release-gate-drift" role="status"><b>当前审查已失效</b><p>以下输入在上次审查后发生变化，不能直接冻结：</p><ul>${drift.map(item=>`<li>${esc(item)}</li>`).join('')}</ul><strong>下一步：先运行连续性审查，再运行发布审查。</strong></section>`:''}${preflight}${actions}${releaseCards}`);
}
function renderInspector(){const el=$('#inspectorContent'),scene=selectedScene(),proposal=pendingProposal(),latest=state.work?.releases?.[0];$$('[data-inspector]').forEach(b=>b.classList.toggle('active',b.dataset.inspector===state.inspector));if(state.inspector==='decision'){el.innerHTML=`<div class="inspector-body"><h3>现在需要你决定</h3><div class="notice ${proposal?'':'good'}">${proposal?'检查候选正文，并采纳、局部修改或退回。':state.stage==='release'&&latest&&!latest.production_run_id?'确认是否把冻结版本交给制作。':state.stage==='release'&&latest?'当前发布版本已完成交接。':'完成当前阶段的推荐动作。'}</div><h3>系统已经做了什么</h3><ul class="context-list"><li><span class="status-dot"></span>作品与版本已持久化</li><li><span class="status-dot ${proposal?'amber':''}"></span>${proposal?'候选等待审查':'没有待处理候选'}</li><li><span class="status-dot"></span>Agent 不可直接写回正文</li></ul></div>`}else if(state.inspector==='context'){const c=state.context;el.innerHTML=`<div class="inspector-body"><h3>当前作用域</h3><p>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'未选择场景'}</p><ul class="context-list">${c?`<li>规则包<br><b>${esc(c.rules.pack_version)}</b></li><li>单一模式<br><b>${esc(c.rules.mode)}</b></li><li>固定输入修订<br><b>${c.source_revision_ids.length} 个</b></li><li>真实 BA 写作<br><b>${esc(c.readiness.real_ba_writing)}</b></li>`:'<li>点击“装配上下文”查看本场固定输入。</li>'}</ul></div>`}else{const existing=scene?.current_revision_id,latestRun=(state.work?.agent_runs||[]).find(run=>run.scope_id===scene?.id);el.innerHTML=`<div class="inspector-body"><h3>创作导演</h3><p>本次运行只读取固定场景合同、单一 BA 模式和运行时人物卡。它只提交一次 Proposal，不能改正文或长期事实。</p>${latestRun?`<section class="agent-run"><b>${esc(latestRun.status)}</b><p>工具记录 ${latestRun.tool_calls.length} 项${latestRun.proposal_id?` · Proposal ${esc(latestRun.proposal_id)}`:''}</p></section>`:''}<form id="agentRunForm"><label>本场指令<textarea name="instruction" placeholder="例如：以爱丽丝先观察、凯伊后补充的节奏起草本场" ${scene&&!existing?'':'disabled'}></textarea></label><button class="primary" type="submit" ${scene&&!existing&&!proposal?'':'disabled'}>运行 BA 场景 Agent</button></form><p class="form-note">${existing?'当前已有正文：首次 BA Agent 不读取旧稿，受控复写将在后续工作流开放。':providerDisclosure()}</p></div>`}}
document.addEventListener('click',async event=>{const b=event.target.closest('button');if(!b)return;try{if(b.dataset.submit==='work'){event.preventDefault();await submitWorkDialog(document.getElementById('workForm'));return}if(b.dataset.action==='new-work'){openWorkDialog(b);return}if(b.dataset.mobile){state.mobileView=b.dataset.mobile;render();return}if(b.dataset.stage){navigateToStage(b.dataset.stage);return}if(b.dataset.stageJump){navigateToStage(b.dataset.stageJump);return}if((b.dataset.scene||b.dataset.sceneOpen)&&state.surface==='writing'&&state.stage==='draft'&&b.closest('#sceneTree'))return;if(b.dataset.scene){state.sceneId=b.dataset.scene;navigateToStage('draft');state.context=null;state.sceneContextEditorOpen=false;render();return}if(b.dataset.sceneOpen){state.sceneId=b.dataset.sceneOpen;navigateToStage('draft');state.sceneContextEditorOpen=false;render();return}if(b.dataset.inspector){state.inspector=b.dataset.inspector;renderInspector();return}if(b.dataset.action==='generate-blueprint'){setBusy('正在建立故事方向');const x=await api(`/works/${state.work.id}/blueprint:generate`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=x.work;toast('故事方向已保存');render();return}if(b.dataset.action==='add-chapter'){const title=prompt('章节名称','第一章');if(!title)return;const x=await api(`/works/${state.work.id}/chapters`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title})});state.work=x.work;toast('章节已建立');render();return}if(b.dataset.addScene){const title=prompt('场景名称','场景 01');if(!title)return;const goal=prompt('本场需要发生什么变化？','确认异常提示灯的来源')||'';const x=await api(`/works/${state.work.id}/chapters/${b.dataset.addScene}/scenes`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title,goal,location})});state.work=x.work;state.sceneId=x.scene_id;toast('场景已建立');render();return}if(b.dataset.action==='assemble-context'){state.context=await api(`/works/${state.work.id}/scenes/${selectedScene().id}/context:assemble`,{method:'POST',body:'{}'});state.inspector='context';toast('本场上下文已装配');render();return}if(b.dataset.action==='generate-candidate'){return}if(b.dataset.accept){const x=await api(`/works/${state.work.id}/proposals/${b.dataset.accept}/accept`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,text:$('#candidateText').value})});state.work=x.work;toast('候选已采纳为新正文修订');render();return}if(b.dataset.reject){const x=await api(`/works/${state.work.id}/proposals/${b.dataset.reject}/reject`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:'用户在工作台退回'})});state.work=x.work;toast('候选已退回');render();return}if(b.dataset.action==='freeze-release'){const x=await api(`/works/${state.work.id}/releases:freeze`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=x.work;toast(`已冻结 ${x.manifest.display_version}`);render();return}if(b.dataset.handoff){setBusy('正在联系 AA 制作后端');const x=await api(`/releases/${b.dataset.handoff}/handoff`,{method:'POST',body:'{}'});toast(`已建立制作任务 ${x.production_run_id}`);await loadWork(state.work.id);return}if(b.dataset.section==='works'){state.stage='overview';state.mobileView='writing';render();return}if(b.dataset.section==='writing'){navigateToStage(blueprintIsConfirmed()?'structure':'brief');return}if(b.dataset.section==='production'){const gate=stageGate('release');if(!gate.allowed){toast(`检查并发布尚未开放：${gate.reason}`,true);return}state.stage='release';state.mobileView='writing';render();return}if(b.dataset.section==='references'){state.stage='references';state.mobileView='writing';state.libraryView='overview';render();return}if(b.dataset.section==='tasks'){state.mobileView='tasks';render();return}}catch(error){setBusy('操作失败，作品数据未丢失');toast(error.message,true)}});
$('#workForm').addEventListener('submit',event=>{event.preventDefault();const submitter=event.submitter;if(submitter&&submitter.dataset.submit!=='work')return;submitWorkDialog(event.target)});
document.addEventListener('submit',async event=>{if(event.target.id!=='briefForm')return;event.preventDefault();try{const f=new FormData(event.target);const payload={idea:String(f.get('idea')||'').trim(),intent_only:true,expected_version:state.work.version};setBusy('正在保存想法');const intent=await api(`/works/${state.work.id}/brief`,{method:'POST',body:JSON.stringify(payload)});state.work=intent.work;setBusy('正在分析故事方向');const analysis=await api(`/works/${state.work.id}/blueprint:generate`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=analysis.work;state.stage='blueprint';toast(analysis.simulation?'已生成模拟方向候选，等待你的确认':'已生成故事方向候选，等待你的确认');render()}catch(error){setBusy('分析未完成，想法已安全保存');toast(error.message,true)}});
const officialCatalogObserver=new MutationObserver(()=>{
  if(state.capabilities?.official_references?.available!==false)return;
  const library=$('#workspace .library-workbench');
  if(!library)return;
  const main=$('.library-main',library);
  if(main&&!$('.catalog-availability',main)){
    const notice=document.createElement('div');
    notice.className='catalog-availability';
    notice.classList.add('catalog-availability-warning');
    notice.setAttribute('role','status');
    notice.textContent='BA 原作语料库当前不可读取。你仍可编辑 BA 起始结构、自定义角色和世界观；原作检索会在语料库恢复可读后开放。';
    main.prepend(notice);
  }
  $$('[data-library-view="official"]',library).forEach(button=>{
    if(!button.disabled){
      button.disabled=true;
      button.setAttribute('aria-disabled','true');
      button.title='官方演出语料库目录当前不可读取';
      button.textContent='BA 原作语料库当前不可读取';
    }
  });
});
officialCatalogObserver.observe($('#workspace'),{childList:true,subtree:true});
// Draft scene buttons are handled by writing-workbench.js so the same path
// can update the active marker, route, and smooth-scroll target without a
// second render. The generic workflow handler above intentionally leaves these
// buttons alone in both the desktop tree and mobile drawer.
boot();

// The workflow guard is deliberately a view-layer policy. It never mutates a
// Work: server-side commands still validate their own domain preconditions.
const FLOW_STAGES=['structure','draft','release'];
const FLOW_REQUIREMENTS={
  structure:'先在作品栏目确认全作故事方向，并选择当前章节',
  draft:'先建立至少一个章节和场景',
  release:'先为每个场景采纳正文，并处理待决定的候选'
};
function isBackgroundKnowledgeProposal(proposal){
  return Boolean(proposal?.evidence?.background_suggestion);
}
function blockingPendingProposals(){
  return (state.work?.proposals||[]).filter(proposal=>proposal.status==='pending'&&!isBackgroundKnowledgeProposal(proposal));
}
function backgroundKnowledgeSuggestions(){
  return (state.work?.proposals||[]).filter(proposal=>proposal.status==='pending'&&isBackgroundKnowledgeProposal(proposal));
}
function usesGuidedWorkflow(){
  const creation=state.work?.runs?.find(run=>run.kind==='creation');
  return creation?.automation_level!=='milestone';
}
function workflowProgress(){
  const sceneList=scenes();
  const hasStructure=Boolean(state.work?.chapters?.length&&sceneList.length);
  const pending=blockingPendingProposals().length>0;
  const allManuscripts=Boolean(sceneList.length)&&sceneList.every(scene=>Boolean(scene.current_revision_id));
  const sourceRevisionIds=sceneList.map(scene=>scene.current_revision_id).filter(Boolean);
  const latestRelease=state.work?.releases?.[0];
  let frozenRevisionIds=[];
  try{frozenRevisionIds=latestRelease?JSON.parse(latestRelease.source_revision_ids_json||'[]'):[]}catch(_){frozenRevisionIds=[]}
  const releaseIsCurrent=Boolean(latestRelease&&allManuscripts&&sourceRevisionIds.length===frozenRevisionIds.length&&sourceRevisionIds.every((id,index)=>id===frozenRevisionIds[index]));
  return {
    done:{
      brief:Boolean(brief()),
      blueprint:blueprintIsConfirmed(),
      structure:hasStructure,
      draft:allManuscripts&&!pending,
      release:releaseIsCurrent
    },
    sceneList,
    pending,
    allManuscripts
  };
}
function stageGate(stage){
  if(!FLOW_STAGES.includes(stage))return{allowed:true,reason:''};
  if(!state.work)return{allowed:stage==='brief',reason:'请先建立作品。'};
  const progress=workflowProgress();
  if(!usesGuidedWorkflow())return{allowed:true,reason:'里程碑模式允许浏览各阶段；写入动作仍会检查前置条件。',progress};
  const allowed={
    structure:progress.done.blueprint||progress.done.structure,
    draft:progress.done.structure,
    release:progress.done.draft||Boolean(state.work?.releases?.length)
  }[stage];
  let reason=FLOW_REQUIREMENTS[stage];
  if(stage==='release'&&progress.sceneList.length&&!progress.allManuscripts){
    reason=`还有 ${progress.sceneList.filter(scene=>!scene.current_revision_id).length} 个场景没有已采纳正文`;
  }else if(stage==='release'&&progress.pending){
    reason='先审查并采纳或退回待决定的候选';
  }
  return{allowed,reason,progress};
}
function navigateToStage(stage,{quiet=false}={}){
  const gate=stageGate(stage);
  if(!gate.allowed){
    if(!quiet)toast(`尚未解锁「${stageLabel(stage)}」：${gate.reason}`,true);
    return false;
  }
  state.stage=stage;
  state.mobileView='writing';
  render();
  return true;
}
function renderWorkflowGuide(){
  const guide=$('#workflowGuide');
  if(!guide)return;
  if(!state.work){guide.innerHTML='';return;}
  const progress=workflowProgress();
  const nextStage=FLOW_STAGES.find(stage=>!progress.done[stage])||'release';
  const nextGate=stageGate(nextStage);
  const completed=FLOW_STAGES.filter(stage=>progress.done[stage]).length;
  const modeText=usesGuidedWorkflow()?'引导模式':'里程碑模式';
  const detail=progress.done.release
    ?'当前正文已经形成冻结发布版本。正文出现新修订时，会重新回到全篇审查。'
    :`${nextGate.reason}。完成后，系统会解锁下一步。`;
  guide.innerHTML=`<p>${modeText} · ${completed}/5</p><h2>${progress.done.release?'发布版本已冻结':`现在完成：${stageLabel(nextStage)}`}</h2><small>${detail}</small>${progress.done.release?'':`<button class="guide-action" type="button" data-guide-next="${nextStage}">去完成这一步</button>`}`;
  $$('[data-stage]').forEach(button=>{
    const stage=button.dataset.stage;
    const gate=stageGate(stage);
    const small=button.querySelector('small');
    if(small&&!button.dataset.stageDescription)button.dataset.stageDescription=small.textContent;
    const complete=Boolean(progress.done[stage]);
    const isNext=stage===nextStage&&!complete;
    button.disabled=!gate.allowed;
    button.classList.toggle('is-complete',complete);
    button.classList.toggle('is-next',isNext);
    button.setAttribute('aria-disabled',String(!gate.allowed));
    button.title=gate.allowed?(complete?'已完成，可随时返回查看':'可进入此阶段'):gate.reason;
    if(small){
      small.textContent=complete?`已完成 · ${button.dataset.stageDescription}`:gate.allowed?`可进行 · ${button.dataset.stageDescription}`:`待解锁 · ${gate.reason}`;
    }
  });
  const production=$('[data-section="production"]');
  if(production)production.title='打开 AA 制作工作台';
}
const renderBeforeWorkflowGuard=render;
render=function(){renderBeforeWorkflowGuard();renderWorkflowGuide();syncWorkbenchGuards()};
function syncWorkbenchGuards(){
  const blueprintForm=$('#blueprintReviewForm');
  if(blueprintForm){
    const confirmButton=blueprintForm.querySelector('button[name="review_action"][value="confirm"]');
    if(confirmButton)confirmButton.disabled=blueprint()?.narrator_only!==true&&!blueprintForm.querySelector('input[name="character_card_ids"]:checked');
  }
  if(state.stage==='draft'){
    const contextNote=$('.scene-context-head p:last-child'),legacyMode=$('.context-mode.legacy');
    if(contextNote&&legacyMode){
      contextNote.textContent='系统会按已确认方向中的角色、全部已确认世界设定和资料自动装配。保存选择后，可固定为本场的明确范围。';
      legacyMode.textContent='自动范围';
    }
  }
  if(state.context&&state.inspector==='context'){
    const modeItem=$$('.context-list li').find(item=>item.textContent.trim().startsWith('单一模式'));
    const modeValue=modeItem?.querySelector('b');
    if(modeValue)modeValue.textContent=sceneModeLabel(state.context.rules.mode_key||selectedScene()?.contract?.writing_mode||brief()?.mode);
  }
}
document.addEventListener('change',event=>{
  if(event.target.matches('#blueprintReviewForm input[name="character_card_ids"]'))syncWorkbenchGuards();
},true);
document.addEventListener('click',event=>{
  const button=event.target.closest('button');
  if(!button)return;
  const stage=button.dataset.guideNext||button.dataset.stage||button.dataset.stageJump||(button.dataset.scene||button.dataset.sceneOpen?'draft':'');
  if(!stage)return;
  const gate=stageGate(stage);
  if(!gate.allowed){
    event.preventDefault();
    event.stopImmediatePropagation();
    toast(`尚未解锁「${stageLabel(stage)}」：${gate.reason}`,true);
    return;
  }
  if(button.dataset.guideNext){
    event.preventDefault();
    event.stopImmediatePropagation();
    state.stage=stage;
    state.mobileView='writing';
    render();
  }
},true);

// These product surfaces are deliberately isolated from the older, monolithic
// event handler above while the workbench is being expanded incrementally.
function stageLabel(stage){return({overview:'作品总览',brief:'写作想法',blueprint:'故事方向',structure:'章节与场景',draft:'逐场写作',references:'创作资料',release:'检查并发布'})[stage]||'写作'}
async function runDurableAgentJob(operation,scopeId,request){
  const workId=state.work.id;
  const job=await api(`/works/${workId}/agent-jobs`,{method:'POST',body:JSON.stringify({operation,scope_id:scopeId,request})});
  const deadline=Date.now()+120000;
  let current=job;
  while(Date.now()<deadline){
    if(['succeeded','failed','cancelled'].includes(current.status))break;
    await new Promise(resolve=>setTimeout(resolve,300));
    current=await api(`/works/${workId}/agent-jobs/${job.id}`);
  }
  if(current.status==='failed')throw new Error(current.error?.message||'Agent 任务未能完成');
  if(current.status==='cancelled')throw new Error('Agent 任务已取消，正式内容没有改变');
  if(current.status!=='succeeded')throw new Error('Agent 任务仍在后台运行，可在任务页查看');
  await loadWork(workId,{resume:false});
  return current;
}
function openFindingResolutionDialog(findingId){
  const finding=(state.work?.review_findings||[]).find(item=>item.id===findingId);
  if(!finding)return;
  let dialog=$('#findingResolveDialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='findingResolveDialog';dialog.className='finding-resolve-dialog';document.body.append(dialog)}
  dialog.innerHTML=`<form method="dialog" data-finding-resolve-form><header class="dialog-head"><div><p class="eyebrow">REVIEW DECISION</p><h2>记录处理决定</h2></div><button type="button" class="icon-button" data-finding-resolve-close aria-label="关闭">×</button></header><div class="finding-resolve-summary"><b>${esc(sceneFindingLabel(finding.kind))} · ${esc(finding.severity==='blocking'?'阻塞':finding.severity==='warning'?'建议':'提示')}</b><p>${esc(finding.message)}</p></div><label>处理理由<textarea name="note" required maxlength="500" placeholder="例如：已修改正文，将在下一次场景审查中复核"></textarea></label><p class="form-note">这只记录你的审查决定，不会自动修改正文；当前 Gate 需要重新检查后才会更新。</p><div class="dialog-actions"><button type="button" class="quiet" data-finding-resolve-close>取消</button><button type="submit" class="primary">标记已处理</button></div></form>`;
  dialog.showModal();
  const form=dialog.querySelector('[data-finding-resolve-form]');
  const close=()=>dialog.close();
  dialog.querySelectorAll('[data-finding-resolve-close]').forEach(button=>button.addEventListener('click',close,{once:true}));
  form?.addEventListener('submit',async event=>{
    event.preventDefault();
    const note=String(new FormData(form).get('note')||'').trim();
    if(!note){form.elements.note?.focus();return}
    const submit=form.querySelector('button[type="submit"]');
    if(submit)submit.disabled=true;
    try{
      const result=await api(`/works/${state.work.id}/findings/${findingId}/resolve`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note})});
      state.work=result.work;dialog.close();toast('审查发现已记录为已处理；请重新检查本场');render();
    }catch(error){if(submit)submit.disabled=false;toast(error.message,true)}
  },{once:true});
  requestAnimationFrame(()=>form?.elements.note?.focus());
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!button)return;
  if(['works','writing','production','tasks'].includes(button.dataset.section)){
    event.preventDefault();event.stopImmediatePropagation();
    if(button.dataset.section==='works'){state.mobileView='writing';state.stage='overview';state.inspector='agent'}
    else if(button.dataset.section==='tasks'){state.mobileView='tasks'}
    else {state.mobileView='writing';state.stage=button.dataset.section==='production'?'release':'structure'}
    $$('.primary-nav .nav-item').forEach(item=>item.classList.toggle('active',item===button));
    render();return;
  }
  if(button.dataset.section==='references'){
    event.preventDefault();event.stopImmediatePropagation();
    state.stage='references';state.mobileView='writing';
    $$('.primary-nav .nav-item').forEach(item=>item.classList.toggle('active',item===button));
    render();return;
  }
  if(button.dataset.action==='review-release'){
    event.preventDefault();event.stopImmediatePropagation();
    try{
      setBusy('全篇审查正在后台运行');await runDurableAgentJob('release.review',state.work.id,{expected_version:state.work.version});
      toast('全篇审查完成，请查看门禁结果');render();
    }catch(error){toast(error.message,true)}
    return;
  }
  if(button.dataset.action==='review-continuity'){
    event.preventDefault();event.stopImmediatePropagation();
    try{
      setBusy('连续性审查正在后台运行');await runDurableAgentJob('continuity.review',state.work.id,{expected_version:state.work.version});
      toast('连续性审查完成，请查看审查结果');render();
    }catch(error){toast(error.message,true)}
    return;
  }
  if(button.dataset.resolveFinding){
    event.preventDefault();event.stopImmediatePropagation();
    openFindingResolutionDialog(button.dataset.resolveFinding);
    return;
  }
  if(button.dataset.action!=='review-scene')return;
  event.preventDefault();event.stopImmediatePropagation();
  try{
    const scene=selectedScene();
    setBusy('本场审查正在后台运行');await runDurableAgentJob('scene.review',scene.id,{expected_version:state.work.version});
    state.inspector='decision';toast('本场审查完成，请查看发现');render();
  }catch(error){toast(error.message,true)}
},true);
document.addEventListener('submit',async event=>{
  const form=event.target;
  if(!['canonForm','characterForm','referenceForm','agentRunForm'].includes(form.id))return;
  event.preventDefault();event.stopImmediatePropagation();
  const fields=new FormData(form);
  try{
    if(form.id==='agentRunForm'){
      const scene=selectedScene();
      const operation=form.dataset.agentMode==='rewrite'?'scene.draft.rewrite':'scene.draft.generate';
       const selection=state.sceneTextSelection?.sceneId===scene.id?state.sceneTextSelection:null;
       setBusy('BA 场景 Agent 正在后台运行');await runDurableAgentJob(operation,scene.id,{expected_version:state.work.version,instruction:fields.get('instruction'),selection});
       state.sceneTextSelection=null;state.inspector='decision';toast(selection?'已提交选段改写候选，等待你的决定':'BA 场景 Agent 已提交一次候选，等待你的决定');render();return;
    }
    let path,payload,success;
    if(form.id==='canonForm'){
      path=`/works/${state.work.id}/canon`;
      payload={expected_version:state.work.version,facts:[{text:fields.get('text'),source:fields.get('source'),confidence_status:'confirmed',scope:'work'}]};success='事实已确认并保存';
    }else if(form.id==='characterForm'){
      path=`/works/${state.work.id}/character-cards`;
      payload={expected_version:state.work.version,name:fields.get('name'),voice_anchors:[fields.get('voice')],ooc_constraints:[fields.get('ooc')],source_refs:[fields.get('source')],trust_status:'confirmed'};success='人物卡已保存';
    }else{
      path=`/works/${state.work.id}/reference-files`;
      payload={expected_version:state.work.version,title:fields.get('title'),source_label:fields.get('source_label'),content:fields.get('content'),trust_status:'unverified'};success='资料已登记';
    }
    const result=await api(path,{method:'POST',body:JSON.stringify(payload)});
    state.work=result.work;form.reset();toast(success);render();
  }catch(error){toast(error.message,true)}
},true);

function openStructureDialog(kind,chapterId='',volumeId=''){
  const dialog=$('#structureDialog'),form=$('#structureForm');
  if(!dialog||!form)return;
  form.reset();form.elements.kind.value=kind;form.elements.chapter_id.value=chapterId;form.elements.volume_id.value=volumeId;
  if(form.elements.writing_mode)form.elements.writing_mode.value=blueprint()?.decision?.mode||brief()?.mode||'bond_short';
  const scene=kind==='scene',volume=kind==='volume';
  $('#structureDialogKicker').textContent=scene?'SCENE':volume?'VOLUME':'CHAPTER';
  $('#structureDialogTitle').textContent=scene?'建立一个场景':volume?'建立一个卷':'建立一个章节';
  $('#structureDialogNote').textContent=scene?'填写地点和本场变化，系统会保存稳定 Scene ID。':volume?'卷是长篇结构的正式层级，建立时会同时创建第一章占位。':'章节是场景的容器，建立后可以继续添加场景。';
  $('#sceneStructureFields').classList.toggle('dialog-fields-hidden',!scene);
  dialog.showModal();
  setTimeout(()=>form.elements.title.focus(),0);
}

function revisionTimestampLabel(value){
  const date=new Date(value||'');
  if(Number.isNaN(date.getTime()))return '保存时间未知';
  return date.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
}

function revisionAuthorLabel(value){
  if(value==='user')return '由你保存';
  if(value==='agent')return '由 Agent 整理';
  return '已保存';
}

function revisionHistoryMarkup(artifact,label){
  if(!artifact)return'<p>暂无历史修订。</p>';
  const currentId=artifact.current_revision_id;
  return (artifact.revisions||[]).map(revision=>`<div class="revision-history-row"><div><b>${revision.id===currentId?'当前版本':'较早版本'}</b><small>${esc(revisionTimestampLabel(revision.created_at))} · ${esc(revisionAuthorLabel(revision.created_by))}</small></div><button class="quiet" type="button" data-compare-artifact="${esc(artifact.id)}" data-compare-revision="${esc(revision.id)}" ${revision.id===currentId?'disabled':''}>${revision.id===currentId?'当前版本':'查看差异'}</button></div>`).join('')||'<p>暂无历史修订。</p>';
}

function revisionDisplayText(value){
  if(value===null||value===undefined)return'';
  if(Array.isArray(value))return value.map(item=>revisionDisplayText(item)).filter(Boolean).join('；');
  if(typeof value!=='object')return String(value);
  return [value.name,value.canonical_name,value.target,value.kind,value.summary,value.text,value.role]
    .map(item=>revisionDisplayText(item)).filter(Boolean).join(' · ')||'资料内容已更新';
}

function revisionDisplayValue(value,key){
  const text=revisionDisplayText(value);
  if(!text)return'';
  if(key==='status')return {active:'使用中',archived:'已归档'}[text]||text;
  if(key==='confidence_status'||key==='trust_status')return {confirmed:'已确认',inferred:'推断',open:'待核对',pending:'待决定'}[text]||text;
  if(key==='scope')return typeof worldRuleScopeLabel==='function'?worldRuleScopeLabel(text):text;
  return text;
}

function revisionDisplayEntries(value){
  if(value===null||value===undefined)return[];
  if(typeof value!=='object'||Array.isArray(value)){
    const text=revisionDisplayText(value);
    return text?[{label:'',value:text}]:[];
  }
  const labels={name:'名称',canonical_name:'标准名称',aliases:'别名',summary:'摘要',text:'内容',role:'故事职责',voice_anchors:'声音锚点',knowledge_boundary:'知情边界',ooc_constraints:'OOC 红线',relationships:'人物关系',target:'关联对象',kind:'关系类型',source:'来源',scope:'适用范围',confidence_status:'可信状态',trust_status:'可信状态',status:'使用状态',participants:'涉及角色',exceptions:'例外'};
  const entries=Object.entries(labels).flatMap(([key,label])=>{
    if(!(key in value))return[];
    const text=revisionDisplayValue(value[key],key);
    return text?[{label,value:text}]:[];
  });
  return entries.length?entries:[{label:'',value:'资料内容已更新'}];
}

function revisionValueMarkup(value){
  if(value===null||value===undefined)return'<span class="revision-value-empty">未设置</span>';
  const entries=revisionDisplayEntries(value);
  return `<dl class="revision-value-details">${entries.map(entry=>entry.label?`<dt>${esc(entry.label)}</dt><dd>${esc(entry.value)}</dd>`:`<dd class="revision-value-plain">${esc(entry.value)}</dd>`).join('')}</dl>`;
}

function revisionPathLabel(path){
  const labels={name:'名称',canonical_name:'标准名称',aliases:'别名',summary:'摘要',role:'故事职责',voice_anchors:'声音锚点',knowledge_boundary:'知情边界',ooc_constraints:'OOC 红线',relationships:'人物关系',source_refs:'来源',source:'来源',source_type:'来源类型',trust_status:'可信状态',entities:'世界观卡',rules:'世界规则',timeline:'时间线',facts:'作品事实',text:'内容',scope:'作用域',confidence_status:'可信状态',status:'状态'};
  const parts=String(path||'/').split('/').filter(Boolean).map(item=>item.replace(/~1/g,'/').replace(/~0/g,'~'));
  const key=parts.at(-1)||'根内容';
  if(labels[key])return labels[key];
  return {entities:'一张世界观卡',rules:'一条世界规则',timeline:'一条时间线',facts:'一条作品事实',relationships:'一条人物关系'}[parts.at(-2)]||'资料内容';
}

function renderRevisionComparison(comparison){
  const title=$('#revisionCompareTitle'),meta=$('#revisionCompareMeta'),body=$('#revisionCompareBody');
  if(!title||!meta||!body)return;
  title.textContent='较早版本与当前版本的差异';
  meta.textContent=`共 ${comparison.total_change_count} 项变化`;
  if(!comparison.changes.length){body.innerHTML='<div class="revision-compare-empty"><b>两个版本内容相同</b><span>版本记录不同，但正文没有差异。</span></div>';return}
  const operationLabel={add:'新增',remove:'移除',replace:'修改'};
  body.innerHTML=`<div class="revision-compare-summary"><span>${comparison.change_counts.add} 新增</span><span>${comparison.change_counts.remove} 移除</span><span>${comparison.change_counts.replace} 修改</span>${comparison.truncated?'<strong>只显示前 200 项</strong>':''}</div><div class="revision-compare-list">${comparison.changes.map(change=>`<section class="revision-compare-change ${esc(change.operation)}"><header><b>${change.subject?`<em>${esc(change.subject)}</em> · `:''}${esc(revisionPathLabel(change.path))}</b><span>${operationLabel[change.operation]||'变化'}</span></header><div><section><small>历史修订</small>${revisionValueMarkup(change.before)}</section><section><small>当前修订</small>${revisionValueMarkup(change.after)}</section></div></section>`).join('')}</div>`;
}

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-compare-revision]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  const dialog=$('#revisionCompareDialog'),body=$('#revisionCompareBody');
  if(!dialog||!body)return;
  body.innerHTML='<div class="revision-compare-empty">正在校验并比较两个正式修订…</div>';
  dialog.showModal();
  (async()=>{try{
    const comparison=await api(`/works/${state.work.id}/artifacts/${button.dataset.compareArtifact}/revisions/${button.dataset.compareRevision}/compare`);
    renderRevisionComparison(comparison);
  }catch(error){body.innerHTML=`<div class="revision-compare-empty error"><b>无法比较修订</b><span>${esc(error.message)}</span></div>`}})();
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.structureChapterMove){event.preventDefault();event.stopImmediatePropagation();moveDraftChapter(button.dataset.chapterId,button.dataset.structureChapterMove);return}
  if(button.dataset.structureSceneMove){event.preventDefault();event.stopImmediatePropagation();moveDraftScene(button.dataset.sceneId,button.dataset.structureSceneMove);return}
  if(button.dataset.structureReset!==undefined){event.preventDefault();event.stopImmediatePropagation();resetStructureDraft();render();return}
  if(button.dataset.structureSave!==undefined){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const draft=structureDraft(),result=await api(`/works/${state.work.id}/structure:reorder`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,chapter_ids:draft.chapter_ids,scene_placements:draft.scene_placements})});state.work=result.work;resetStructureDraft();toast(result.changed?'章节安排已保存；全篇审查需要重新运行。':'章节安排没有变化。');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.structureAddChapter!==undefined){event.preventDefault();event.stopImmediatePropagation();openStructureDialog('chapter','',button.dataset.structureAddChapter);return}
  if(button.dataset.structureAddVolume!==undefined){event.preventDefault();event.stopImmediatePropagation();openStructureDialog('volume');return}
  if(button.dataset.structureAddScene){event.preventDefault();event.stopImmediatePropagation();openStructureDialog('scene',button.dataset.structureAddScene);return}
  if(button.dataset.libraryTarget){state.libraryView=button.dataset.libraryTarget}
  if(button.dataset.openContextCharacters!==undefined){event.preventDefault();event.stopImmediatePropagation();const scene=selectedScene();captureSceneRecovery(scene);state.stage='references';state.mobileView='writing';state.libraryView='characters';state.editCardId='';state.editCard=null;state.prefillCharacter=sceneRecoveryCharacterName(scene);state.sceneContextEditorOpen=false;render();focusCharacterCardName();return}
  if(button.dataset.toggleSceneContext!==undefined){event.preventDefault();event.stopImmediatePropagation();state.sceneContextEditorOpen=!state.sceneContextEditorOpen;render();return}
  if(button.dataset.toggleSceneContract!==undefined){event.preventDefault();event.stopImmediatePropagation();state.sceneContractOpen=!state.sceneContractOpen;render();return}
  if(button.dataset.closeStructureDialog!==undefined){event.preventDefault();event.stopImmediatePropagation();$('#structureDialog')?.close();return}
  if(button.dataset.action==='add-chapter'){event.preventDefault();event.stopImmediatePropagation();openStructureDialog('chapter');return}
  if(button.dataset.addScene){event.preventDefault();event.stopImmediatePropagation();openStructureDialog('scene',button.dataset.addScene);return}
},true);

document.addEventListener('change',event=>{
  const select=event.target.closest('select[data-structure-scene-target]');if(!select)return;
  event.preventDefault();event.stopImmediatePropagation();placeDraftScene(select.dataset.structureSceneTarget,select.value);
},true);

function decorateLibrary(){
  if(state.stage!=='references')return;
  const host=$('.library-page-head');
  if(!host)return;
  if(state.libraryView==='world'){
    const actionBar=[...document.querySelectorAll('.asset-primary-actions')].find(node=>node.textContent.includes('世界观卡'));
    if(actionBar&&!actionBar.querySelector('[data-import-world]')){
      actionBar.querySelector('div')?.insertAdjacentHTML('afterbegin','<button class="quiet" type="button" data-import-world>从文件导入</button>');
    }
  }
  if(state.libraryView==='overview'){
    const cards=libraryCards(),officialCount=cards.filter(card=>card.source_type==='official_reference').length,customCount=cards.filter(card=>card.source_type==='custom').length,legacyCount=cards.length-officialCount-customCount;
    const summary=$('.library-summary[data-library-view="characters"] b');
    if(summary&&legacyCount)summary.textContent=`${officialCount} 张原作参考 · ${customCount} 张自定义 · ${legacyCount} 张旧版未标注`;
  }
  if(state.libraryView==='characters'&&state.editCardId){
    const form=$('#libraryCharacterForm'),card=libraryCards().find(item=>item.id===state.editCardId);
    if(form&&card){
      const lifecycle=card.status==='archived'?`<button class="quiet" type="button" data-restore-card="${esc(card.id)}">恢复人物卡</button>`:`<button class="danger" type="button" data-archive-card="${esc(card.id)}">归档人物卡</button>`;
      const actions=document.createElement('div');actions.className='library-inline-actions';actions.innerHTML=`${lifecycle}<button class="quiet" type="button" data-card-history="${esc(card.id)}">${state.historyCardId===card.id?'收起历史':'查看历史修订'}</button>`;form.querySelector('.actions')?.append(actions);
      if(state.historyCardId===card.id){const history=document.createElement('div');history.className='revision-history';history.innerHTML=revisionHistoryMarkup(state.work.artifacts.find(item=>item.id===card.artifactId),'人物卡修订');form.append(history)}
    }
  }
  if(state.libraryView==='characters'&&state.characterCardDraft&&!state.editCardId){
    const form=$('#libraryCharacterForm'),draft=state.characterCardDraft;
    if(form){
      form.elements.source_type.value=draft.source_type||'official_reference';
      form.elements.trust_status.value='open';
      form.elements.name.value=draft.name||'';
      form.elements.canonical_name.value=draft.canonical_name||'';
      form.elements.role.value=draft.role||'';
      form.elements.voice.value=(draft.voice_anchors||[]).join('\n');
      form.elements.boundary.value=draft.knowledge_boundary||'';
      form.elements.ooc.value=(draft.ooc_constraints||[]).join('\n');
      form.elements.relationships.value=(draft.relationships||[]).map(item=>`${item.target} | ${item.kind} | ${item.summary}`).join('\n');
      form.elements.source.value=(draft.source_refs||[]).join('；');
      form.elements.name.focus();
      state.libraryEditorOpen=true;
      state.characterCardDraft=null;
      toast('已建立待核对人物卡草稿；确认身份和设定后，才能进入 Agent。');
    }
  }
  if(state.libraryView==='canon'){
    const form=$('#workCanonForm'),fact=(workCanon().facts||[]).find(item=>item.id===state.editCanonFactId);
    if(form&&fact){
      form.elements.text.value=fact.text||'';
      form.elements.source.value=fact.source||'';
      form.elements.confidence_status.value=fact.confidence_status||'open';
      form.elements.scope.value=fact.scope||'work';
      const lifecycle=document.createElement('button');
      lifecycle.type='button';
      if(fact.status==='archived'){
        lifecycle.className='primary';
        lifecycle.dataset.restoreCanonFact=fact.id;
        lifecycle.textContent='恢复作品事实';
      }else{
        lifecycle.className='danger';
        lifecycle.dataset.archiveCanonFact=fact.id;
        lifecycle.textContent='归档事实';
      }
      form.querySelector('.actions')?.append(lifecycle);
    }
    if(form&&state.canonHistoryOpen){
      const artifact=workCanonArtifact(),history=document.createElement('div');
      history.className='revision-history';
      history.innerHTML=revisionHistoryMarkup(artifact,'事实集修订');
      form.append(history);
    }
  }
  if(state.libraryView==='world'&&state.worldCardDraft&&!state.editWorldEntry){
    const form=$('#worldEntityForm'),draft=state.worldCardDraft;
    if(form){form.elements.kind.value=draft.kind||'custom';form.elements.source_type.value=draft.source_type||'custom';form.elements.name.value=draft.name||'';form.elements.summary.value=draft.summary||'';form.elements.aliases.value=(draft.aliases||[]).join('、');form.elements.source.value=draft.source||'';form.elements.confidence_status.value=draft.confidence_status||'open';form.elements.participants.value=(draft.participants||[]).join('、');form.elements.name.focus();state.libraryEditorOpen=true;state.worldCardDraft=null;if(draft.source)toast('已带入原作资料；请核对后决定本作采用的定义。')}
  }
  if(state.libraryView==='world'){
    const form=$('#worldEntityForm'),currentId=state.editWorldEntry?.type==='entity'?state.editWorldEntry.id:'';
    if(form){
      const selected=new Set(worldBible().entities?.find(item=>item.id===currentId)?.related_world_ids||[]),available=(worldBible().entities||[]).filter(item=>item.status!=='archived'&&item.id!==currentId),picker=document.createElement('fieldset');
      picker.className='world-link-picker';picker.innerHTML=`<legend>关联的世界观卡 <small>保存后会在知识图中形成真实连线</small></legend>${available.length?available.map(item=>`<label><input type="checkbox" name="related_world_ids" value="${esc(item.id)}" ${selected.has(item.id)?'checked':''}><span>${esc(item.name)}<small>${worldKindLabel(item.kind)}</small></span></label>`).join(''):'<p>还没有其他世界观卡。</p>'}`;
      form.querySelector('.actions')?.before(picker);
      const linkedEntity=worldBible().entities?.find(item=>item.id===currentId),linkedCharacters=new Set(linkedEntity?.participants||[]),linkedCharacterIds=new Set(linkedEntity?.participant_character_ids||[]),characterCards=libraryCards().filter(card=>card.status!=='archived'),characterPicker=document.createElement('fieldset');
      characterPicker.className='world-link-picker character-link-picker';characterPicker.innerHTML=`<legend>关联的人物卡 <small>保存后显示在知识图，可被场景上下文按需选择</small></legend>${characterCards.length?characterCards.map(card=>`<label><input type="checkbox" name="world_character_card_ids" value="${esc(card.id)}" ${linkedCharacterIds.has(card.id)||linkedCharacters.has(card.name)?'checked':''}><span>${esc(card.name)}<small>${libraryKindLabel(card.source_type)} · ${trustLabel(card.trust_status)}</small></span></label>`).join(''):'<p>先建立人物卡，再将角色与这张设定卡连起来。</p>'}`;
      form.querySelector('.actions')?.before(characterPicker);
    }
  }
  if(state.libraryView==='world'&&state.editWorldEntry?.type==='entity'&&state.worldHistoryOpen){
    const artifact=state.work.artifacts.find(item=>item.kind==='world_bible'),form=$('#worldEntityForm');
    if(artifact&&form){const history=document.createElement('div');history.className='revision-history';history.innerHTML=revisionHistoryMarkup(artifact,'世界观修订');form.append(history)}
  }
  if(state.libraryView==='rules'){$$('.world-rule').forEach((row,index)=>{const entry=worldBible().rules?.filter(item=>item.status!=='archived')?.[index];if(!entry)return;const actions=document.createElement('div');actions.className='entry-actions';actions.innerHTML=`<button class="quiet" type="button" data-edit-world-entry="rule:${esc(entry.id)}">编辑</button>`;row.append(actions)})}
  if(state.libraryView==='timeline'){$$('.timeline-event').forEach((row,index)=>{const entry=worldBible().timeline?.filter(item=>item.status!=='archived')?.[index];if(!entry)return;const actions=document.createElement('div');actions.className='entry-actions';actions.innerHTML=`<button class="quiet" type="button" data-edit-world-entry="event:${esc(entry.id)}">编辑</button>`;row.append(actions)})}
  if(state.libraryView==='official'){
    const rows=$$('.official-record');
    rows.forEach((row,index)=>{row.hidden=index>=state.officialReferenceLimit});
    if(rows.length>state.officialReferenceLimit){const more=document.createElement('button');more.className='quiet official-more';more.type='button';more.dataset.officialMore='';more.textContent=`再显示 ${Math.min(6,rows.length-state.officialReferenceLimit)} 条（共 ${rows.length} 条）`;$('.official-reference-workbench')?.append(more)}
  }
}

document.addEventListener('submit',async event=>{
  if(event.target.id!=='structureForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const form=event.target,fields=new FormData(form),kind=String(fields.get('kind'));
  try{
    let result;
    if(kind==='volume'){
      result=await api(`/works/${state.work.id}/volumes`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title:fields.get('title')})});
      toast('卷与第一章占位已建立');
    }else if(kind==='chapter'){
      result=await api(`/works/${state.work.id}/chapters`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title:fields.get('title'),volume_id:fields.get('volume_id')})});
      toast('章节已建立');
    }else{
      result=await api(`/works/${state.work.id}/chapters/${fields.get('chapter_id')}/scenes`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title:fields.get('title'),goal:fields.get('goal'),location:fields.get('location'),writing_mode:fields.get('writing_mode'),forbidden_reveals:splitLines(fields.get('forbidden_reveals'))})});
      state.sceneId=result.scene_id;toast('场景已建立');
    }
    state.work=result.work;$('#structureDialog').close();state.stage=kind==='scene'?'draft':'structure';render();
  }catch(error){toast(error.message,true)}
},true);

function sceneModeOptions(selected){return ['bond_short','main_battle','long_comedy','text_reading'].map(mode=>`<option value="${mode}" ${mode===selected?'selected':''}>${esc(sceneModeLabel(mode))}</option>`).join('')}
function sceneContractForm(scene){const contract=scene.contract||{},writingMode=contract.writing_mode||brief()?.mode||'bond_short';return `<section class="scene-contract-editor"><div><p class="eyebrow">SCENE CONTRACT</p><h3>编辑本场契约</h3><p>这里定义接下来生成时的地点、目标、已知事实和揭示边界，不会改动已有正文。</p></div><form id="sceneContractForm"><label>场景标题<input name="title" required value="${esc(scene.title)}"></label><label>发生地点<input name="location" value="${esc(contract.location||'')}" placeholder="例如：游戏开发部活动室"></label><label>本场目标<textarea name="goal" required placeholder="本场结束时，具体什么发生了变化？">${esc(contract.goal||'')}</textarea></label><label class="scene-mode-field">本场起草重心<select name="writing_mode">${sceneModeOptions(writingMode)}</select><small>作品可以混合推进；本场的 Agent 和候选生成只读取这一套规则包。</small></label><label>已知事实（每行一条）<textarea name="known_facts" placeholder="只写本场开始前已经成立的事实。">${esc((contract.known_facts||[]).join('\n'))}</textarea></label><label>禁止提前揭示（每行一条）<textarea name="forbidden_reveals" placeholder="例如：匿名发件人的身份。">${esc((contract.forbidden_reveals||[]).join('\n'))}</textarea></label><label>停止边界<textarea name="stop_boundary" required placeholder="达到什么状态就必须收束？">${esc(contract.stop_boundary||'')}</textarea></label><div class="contract-warning">${pendingProposal()?'保存后，当前待处理候选会标为“已替代”，不能再采纳。':'保存后会用于之后的上下文装配、Agent 和候选生成。'}</div><div class="actions"><button class="primary" type="submit">保存场景契约</button><button class="quiet" type="button" data-toggle-scene-contract>取消</button></div></form></section>`}
function sceneScriptArtifact(scene){return state.work?.artifacts.find(item=>item.kind==='scene_script'&&item.scope_id===scene?.id)}
function makeClientBlockId(){state.manuscriptBlockCounter+=1;return `block-${Date.now().toString(36)}-${state.manuscriptBlockCounter.toString(36)}`}
 function blockRowMarkup(block,index,editing=false){const type=['action','narration','dialogue'].includes(block.type)?block.type:'action',speaker=block.speaker||'',text=block.text||'',typeLabel={action:'动作',narration:'旁白',dialogue:'对白'}[type];return `<article class="manuscript-block ${type==='action'?'is-action':''} ${type==='narration'?'is-narration':''} ${editing?'is-editing':''}" data-manuscript-block data-block-id="${esc(block.id)}" data-block-type="${type}"><div class="block-gutter"><span>${String(index+1).padStart(2,'0')}</span><div class="block-move"><button type="button" class="icon-button" title="上移此块" aria-label="上移此块" data-manuscript-move="up">↑</button><button type="button" class="icon-button" title="下移此块" aria-label="下移此块" data-manuscript-move="down">↓</button></div></div><div class="block-fields"><div class="block-meta"><select name="type" aria-label="正文块类型"><option value="action" ${type==='action'?'selected':''}>动作</option><option value="narration" ${type==='narration'?'selected':''}>旁白</option><option value="dialogue" ${type==='dialogue'?'selected':''}>对白</option></select><input name="speaker" value="${esc(speaker)}" placeholder="说话人" aria-label="说话人" ${type!=='dialogue'?'disabled':''}><span class="manuscript-speaker-readonly" aria-hidden="true">${type==='dialogue'&&speaker?esc(speaker):''}</span></div><button type="button" class="manuscript-reading" data-manuscript-edit aria-label="编辑第 ${String(index+1).padStart(2,'0')} 段"><span class="manuscript-reading-type">${typeLabel}</span><span class="manuscript-reading-speaker" ${type!=='dialogue'?'aria-hidden="true"':''}>${type==='dialogue'?esc(speaker||'说话人'):''}</span><span class="manuscript-reading-text">${esc(text||'点击输入正文')}</span></button><textarea name="text" aria-label="正文内容" placeholder="${type==='dialogue'?'角色说的话':type==='narration'?'旁白内容':'动作、环境或叙述'}">${esc(text)}</textarea></div><button type="button" class="icon-button block-remove" title="删除此块" aria-label="删除此块" data-manuscript-remove>×</button></article>`}
function manuscriptInsertBarMarkup(afterId){return `<div class="manuscript-insert-bar" data-manuscript-insert-bar><span aria-hidden="true"></span><button type="button" class="manuscript-insert-button" data-manuscript-insert="${esc(afterId||'')}" aria-label="在此处插入正文段落" title="在此处插入正文段落"><span aria-hidden="true">+</span></button></div>`}
function manuscriptListMarkup(blocks){if(!blocks.length)return '<div class="manuscript-empty" data-manuscript-empty><b>本场还没有正文</b><button type="button" class="manuscript-empty-insert" data-manuscript-insert-empty><span aria-hidden="true">+</span><span>添加第一段</span></button></div>';return blocks.map((block,index)=>`${blockRowMarkup(block,index,false)}${manuscriptInsertBarMarkup(block.id)}`).join('')}
function manuscriptBlocks(content){return Array.isArray(content?.blocks)?content.blocks:[]}
function activeManuscriptBlocks(scene,content){return state.manuscriptDirty&&state.manuscriptSceneId===scene?.id&&Array.isArray(state.manuscriptDraftBlocks)?state.manuscriptDraftBlocks:manuscriptBlocks(content)}
function manuscriptMarkup(scene,artifact,proposal=null,options={}){const revision=artifact?.current_revision,blocks=activeManuscriptBlocks(scene,revision?.content),baseRevision=revision?.id||'',embedded=Boolean(options.embedded),body=proposal?sceneProposalReviewMarkup(proposal,{inline:true}):`<form id="sceneManuscriptForm" data-scene-id="${esc(scene?.id||'')}" data-base-revision="${esc(baseRevision)}"><div class="manuscript-toolbar"><div><b>正文段落</b><small>点击段落即可编辑；段落之间的 + 用来插入新内容。</small></div></div><div class="script-sheet block-editor-list" data-manuscript-list>${manuscriptListMarkup(blocks)}</div><div class="desk-actions manuscript-actions"><p>手工编辑不会调用 Agent；候选也必须经过你的审查。</p><button class="primary" type="submit">保存正文</button></div></form>`,head=`<div class="desk-head manuscript-head"><div><p class="eyebrow">${proposal?'正文 · 有一份改动待决定':`当前正文${revision?` · 第 ${revision.ordinal} 版`:''}`}</p><h3>正文</h3><p class="manuscript-meta">${proposal?'直接在正文里查看红删与绿增；勾选后应用，正文才会建立新版本。':revision?'直接点击段落即可编辑；在段落之间点击 + 可插入新内容。':'从段落之间的 + 开始添加正文；保存会建立第一版正文。'}</p></div><div class="desk-tools"><span id="manuscriptSaveState" class="manuscript-state ${state.manuscriptDirty?'dirty':'saved'}">${state.manuscriptDirty?'未保存修改':'已保存'}</span></div></div>`;return embedded?`${head}${body}`:`<section class="manuscript-desk ${proposal?'has-inline-review':''}">${head}${body}</section>`}
function chapterReadonlySceneMarkup(scene,index){const artifact=sceneScriptArtifact(scene),blocks=manuscriptBlocks(artifact?.current_revision?.content);return `<section class="chapter-manuscript-scene" id="chapter-scene-${esc(scene.id)}" data-chapter-scene-anchor="${esc(scene.id)}"><header class="chapter-manuscript-scene-head"><span>场景 ${index+1}</span><h3>${esc(scene.title)}</h3></header>${blocks.length?`<div class="script-sheet chapter-manuscript-reading">${blocks.map((block,blockIndex)=>blockRowMarkup(block,blockIndex,false)).join('')}</div>`:'<div class="chapter-manuscript-empty">本场还没有正文。</div>'}</section>`}
function sceneContractJsonText(value){if(value===undefined||value===null)return'';if(Array.isArray(value)&&!value.length)return'';if(!Array.isArray(value)&&typeof value==='object'&&!Object.keys(value).length)return'';try{return JSON.stringify(value,null,2)}catch{return''}}
sceneContractForm=function(scene){const contract=scene.contract||{},writingMode=contract.writing_mode||brief()?.mode||'bond_short',renderMode=contract.render_mode||'official_script',voiceVariant=contract.literary_voice_variant||'';return `<section class="scene-contract-editor"><div><p class="eyebrow">SCENE CONTRACT</p><h3>编辑本场契约</h3><p>这里定义接下来生成时的地点、目标、已知事实和揭示边界，不会改动已有正文。高级约束默认收起，只有需要控制情绪、信息归属或演出格式时再打开。</p></div><form id="sceneContractForm"><label>场景标题<input name="title" required value="${esc(scene.title)}"></label><label>发生地点<input name="location" value="${esc(contract.location||'')}" placeholder="例如：游戏开发部活动室"></label><label>本场目标<textarea name="goal" required placeholder="本场结束时，具体什么发生了变化？">${esc(contract.goal||'')}</textarea></label><label class="scene-mode-field">本场起草重心<select name="writing_mode">${sceneModeOptions(writingMode)}</select><small>作品可以混合推进；本场的 Agent 和候选生成只读取这一套规则包。</small></label><label>已知事实（每行一条）<textarea name="known_facts" placeholder="只写本场开始前已经成立的事实。">${esc((contract.known_facts||[]).join('\\n'))}</textarea></label><label>禁止提前揭示（每行一条）<textarea name="forbidden_reveals" placeholder="例如：匿名发件人的身份。">${esc((contract.forbidden_reveals||[]).join('\\n'))}</textarea></label><label>停止边界<textarea name="stop_boundary" required placeholder="达到什么状态就必须收束？">${esc(contract.stop_boundary||'')}</textarea></label><details class="scene-contract-advanced"><summary>高级写作约束（可选）</summary><p class="form-note">这些字段会直接进入 BA Writing Prompt。留空不会改变现有约束；结构化字段使用 JSON，不需要时不用填写。</p><div class="scene-contract-advanced-grid"><label>场景类型<input name="scene_type" value="${esc(contract.scene_type||'')}" placeholder="例如：调查、关系推进、战斗"></label><label>外部刺激<input name="external_trigger" value="${esc(contract.external_trigger||'')}" placeholder="什么具体事件逼人物回应？"></label><label>隐藏期待<input name="hidden_expectation" value="${esc(contract.hidden_expectation||'')}" placeholder="人物真正期待什么？"></label><label>防御方式<input name="defense" value="${esc(contract.defense||'')}" placeholder="人物如何掩饰或回避？"></label><label>本场选择<input name="choice" value="${esc(contract.choice||'')}" placeholder="谁做了什么选择或拒绝？"></label><label>局面变化<input name="plot_delta" value="${esc(contract.plot_delta||'')}" placeholder="结束时外部局面怎样改变？"></label><label>情绪变化<input name="emotion_delta" value="${esc(contract.emotion_delta||'')}" placeholder="例如：戒备转为有限合作"></label><label>余波<input name="residue" value="${esc(contract.residue||'')}" placeholder="下一场会继续承受什么？"></label><label>收尾兑现<input name="ending_payoff" value="${esc(contract.ending_payoff||'')}" placeholder="例如：事后道歉并为失态收场"></label><label class="scene-contract-check">老师在场<label><input name="has_sensei" type="checkbox" ${contract.has_sensei?'checked':''}><small>只在本场确实出现老师时勾选。</small></label></label><label>老师的场景职能<input name="sensei_scene_function" value="${esc(contract.sensei_scene_function||'')}" placeholder="例如：只确认行动边界"></label><label>输出格式<select name="render_mode"><option value="official_script" ${renderMode==='official_script'?'selected':''}>官方剧本</option><option value="text_reading" ${renderMode==='text_reading'?'selected':''}>小说化阅读</option><option value="engine_script" ${renderMode==='engine_script'?'selected':''}>演出脚本（需完整演出契约）</option></select></label><label>文学变体<input name="literary_voice_variant" value="${esc(voiceVariant)}" placeholder="例如：literary_voice_v4_5"><small>实验变体仍需人工复核。</small></label><label class="scene-contract-json">信息归属（JSON）<textarea name="information_ownership" rows="5" placeholder='{"提示灯闪烁":{"first_carrier":"画面","later_use":"迫使爱丽丝停止触碰"}}'>${esc(sceneContractJsonText(contract.information_ownership))}</textarea></label><label class="scene-contract-json">话轮因果链（JSON）<textarea name="exchange_chain" rows="5" placeholder='[{"trigger":"提示灯闪烁","responder":"爱丽丝","change":"停止触碰"}]'>${esc(sceneContractJsonText(contract.exchange_chain))}</textarea></label></div></details><div class="contract-warning">${pendingProposal()?'保存后，当前待处理候选会标为“已替代”，不能再采纳。':'保存后会用于之后的上下文装配、Agent 和候选生成。'}</div><div class="actions"><button class="primary" type="submit">保存场景契约</button><button class="quiet" type="button" data-toggle-scene-contract>取消</button></div></form></section>`}
function chapterActiveSceneMarkup(scene,index,manuscript,proposal,findings){const blocker=findings.find(f=>f.severity==='blocking'),warning=findings.find(f=>f.severity==='warning'),content=manuscript?.current_revision?.content||{},current=content.text||((Array.isArray(content.blocks)&&content.blocks.length)?'structured':''),providerSimulation=Boolean(state.capabilities?.providers?.[0]?.is_simulation),headline=proposal?'有一份候选等待决定':blocker?'先处理本场阻塞项':warning?'先补齐本场依据':current?'正文已就绪，可开始下一步':'先装配上下文，准备本场',action=proposal?`<button class="primary" data-focus-candidate aria-label="查看候选与 Diff">查看正文改动</button>`:blocker?`<button class="primary" data-resolve-finding="${blocker.id}">处理阻塞项</button>`:warning?`<button class="primary" data-action="open-character-card">补齐人物卡</button>`:current?`<button class="primary" data-action="generate-candidate">生成${providerSimulation?'模拟':''}候选</button>`:`<button class="primary" data-action="assemble-context">准备本场</button>`;return `<section class="chapter-manuscript-scene is-current" id="chapter-scene-${esc(scene.id)}" data-chapter-scene-anchor="${esc(scene.id)}"><header class="chapter-manuscript-scene-head"><span>场景 ${index+1} · 当前编辑</span><h3>${esc(scene.title)}</h3><button class="scene-contract ${state.sceneContractOpen?'active':''}" data-toggle-scene-contract>${state.sceneContractOpen?'收起设定':'本场设定'}</button></header>${state.sceneContractOpen?sceneContractForm(scene):''}<section class="next-command ${blocker?'blocked':warning?'attention':''}"><div><small>当前下一步</small><strong>${headline}</strong><p>${blocker?esc(blocker.message):warning?esc(warning.message):proposal?'改动已经显示在正文中；勾选后应用或退回。':current?'可先检查连续性，也可以让系统提出一份新的候选。':'将使用本场设定和已确认的人物卡。'}</p></div><div class="command-actions">${action}${current&&!proposal?'<button class="quiet" data-action="review-scene">检查本场</button>':''}</div></section>${sceneReviewFindingsMarkup(findings)}<div class="chapter-manuscript-editor ${proposal?'has-inline-review':''}">${manuscriptMarkup(scene,manuscript,proposal,{embedded:true})}</div></section>`}
// Continuous chapter reading is the default surface. Keep the existing
// per-scene editor behind an explicit disclosure so a second full正文 desk
// never appears underneath the chapter manuscript.
function chapterReadingBlockMarkup(block,index){
  const type=['action','narration','dialogue'].includes(block.type)?block.type:'action';
  const label={action:'动作',narration:'旁白',dialogue:'对白'}[type];
  const speaker=type==='dialogue'?(block.speaker||''):'';
  return `<article class="chapter-reading-block is-${type}" data-chapter-reading-block data-block-id="${esc(block.id||'')}" data-block-type="${type}"><div class="chapter-reading-gutter">${String(index+1).padStart(2,'0')}</div><div class="chapter-reading-copy"><div class="chapter-reading-meta"><span>${label}</span>${speaker?`<b>${esc(speaker)}</b>`:''}</div><p>${esc(block.text||'')}</p></div></article>`;
}

function chapterInlineManuscriptMarkup(scene,artifact){
  const revision=artifact?.current_revision,blocks=activeManuscriptBlocks(scene,revision?.content),baseRevision=revision?.id||'';
  return `<form id="sceneManuscriptForm" class="chapter-inline-manuscript" data-scene-id="${esc(scene?.id||'')}" data-base-revision="${esc(baseRevision)}"><div class="chapter-inline-manuscript-bar"><div><b>正文</b><small>点击段落即可编辑；段落之间的 + 用来插入新内容。</small></div><span id="manuscriptSaveState" class="manuscript-state ${state.manuscriptDirty?'dirty':'saved'}">${state.manuscriptDirty?'未保存修改':'已保存'}</span></div><div class="chapter-inline-manuscript-list" data-manuscript-list>${manuscriptListMarkup(blocks)}</div><div class="chapter-inline-manuscript-actions"><span>手工编辑不会调用 Agent</span><button class="primary" type="submit">保存正文</button></div></form>`;
}

chapterReadonlySceneMarkup=function(scene,index){
  const artifact=sceneScriptArtifact(scene),blocks=manuscriptBlocks(artifact?.current_revision?.content);
  return `<section class="chapter-manuscript-scene" id="chapter-scene-${esc(scene.id)}" data-chapter-scene-anchor="${esc(scene.id)}"><header class="chapter-manuscript-scene-head"><span>场景 ${index+1}</span><h3>${esc(scene.title)}</h3></header>${blocks.length?`<div class="chapter-manuscript-reading">${blocks.map(chapterReadingBlockMarkup).join('')}</div>`:'<div class="chapter-manuscript-empty">本场还没有正文。</div>'}</section>`;
};

chapterActiveSceneMarkup=function(scene,index,manuscript,proposal,findings){
  const content=manuscript?.current_revision?.content||{};
  const blocks=manuscriptBlocks(content);
  const blocker=findings.find(item=>item.severity==='blocking');
  const warning=findings.find(item=>item.severity==='warning');
  const current=Boolean(manuscript?.current_revision?.id||content.text||blocks.length);
  const providerSimulation=Boolean(state.capabilities?.providers?.[0]?.is_simulation);
  const headline=proposal?'有一份候选等待决定':blocker?'先处理本场阻塞项':warning?'先补齐本场依据':current?'正文已就绪，可开始下一步':'正在准备本场';
  const action=proposal
    ? '<button class="primary" data-focus-candidate aria-label="查看候选与 Diff">查看正文改动</button>'
    : blocker
      ? `<button class="primary" data-resolve-finding="${esc(blocker.id)}">处理阻塞项</button>`
      : warning
        ? '<button class="primary" data-action="open-character-card">补齐人物卡</button>'
        : current
          ? `<button class="primary" data-action="generate-candidate">生成${providerSimulation?'模拟':''}候选</button>`
          : '<button class="primary" data-action="assemble-context">准备本场</button>';
  const reading=proposal
    ? (blocks.length?`<div class="chapter-manuscript-reading">${blocks.map(chapterReadingBlockMarkup).join('')}</div>`:'<div class="chapter-manuscript-empty">本场还没有正文。</div>')
    : '';
  const review=findings.length?sceneReviewFindingsMarkup(findings):'';
  const editor=proposal
    ? sceneProposalReviewMarkup(proposal,{inline:true})
    : chapterInlineManuscriptMarkup(scene,manuscript);
  return `<section class="chapter-manuscript-scene is-current" id="chapter-scene-${esc(scene.id)}" data-chapter-scene-anchor="${esc(scene.id)}"><header class="chapter-manuscript-scene-head"><span>场景 ${index+1}</span><h3>${esc(scene.title)}</h3></header>${reading}${review}${editor}</section>`;
};

function sceneBlockLineMarkup(block, kind){
  if(!block)return '';
  const speaker=block.type==='narration'?'<b>旁白</b><span class="scene-diff-colon">：</span>':block.speaker?`<b>${esc(block.speaker)}</b><span class="scene-diff-colon">：</span>`:'';
  return `<div class="scene-diff-line ${kind||''}">${speaker}<span>${esc(block.text||'')}</span></div>`;
}

function sceneInlineDiffMarkup(change){
  const pairs=Array.isArray(change?.inline_diff)?change.inline_diff:[];
  if(!pairs.length)return '';
  const typeLabel={action:'动作',narration:'旁白',dialogue:'对白'};
  const rows=pairs.map((pair,index)=>{
    const oldLabel=pair.old_speaker||typeLabel[pair.old_type]||'原块';
    const newLabel=pair.new_speaker||typeLabel[pair.new_type]||'候选块';
    const segments=Array.isArray(pair.segments)?pair.segments:[];
    const oldContent=segments.filter(segment=>segment.kind==='equal'||segment.kind==='delete').map(segment=>`<span class="scene-inline-${esc(segment.kind)}">${esc(segment.text)}</span>`).join('')||'<span class="scene-inline-empty" aria-hidden="true">−</span>';
    const newContent=segments.filter(segment=>segment.kind==='equal'||segment.kind==='insert').map(segment=>`<span class="scene-inline-${esc(segment.kind)}">${esc(segment.text)}</span>`).join('')||'<span class="scene-inline-empty" aria-hidden="true">−</span>';
    const hasOld=Boolean(pair.old_block_id||pair.old_type||pair.old_text),hasNew=Boolean(pair.new_block_id||pair.new_type||pair.new_text);
    const meta=!hasOld?`<small>${esc(newLabel)} · 新增</small>`:!hasNew?`<small>${esc(oldLabel)} · 删除</small>`:oldLabel!==newLabel?`<small>${esc(oldLabel)} → ${esc(newLabel)}</small>`:`<small>${esc(newLabel)}</small>`;
    return `<div class="scene-inline-row" data-scene-inline-row="${index}"><div class="scene-inline-label">${meta}</div><div class="scene-inline-pair"><p><small>当前</small>${oldContent}</p><p><small>候选</small>${newContent}</p></div></div>`;
  }).join('');
  return `<details class="scene-inline-diff" open><summary>文字级改动</summary><div class="scene-inline-legend"><span class="scene-inline-delete">删除</span><span class="scene-inline-insert">新增</span></div><div class="scene-inline-rows">${rows}</div></details>`;
}

function sceneProposalRuntimeMarkup(proposal){
  const run=(state.work?.agent_runs||[]).find(item=>item.proposal_id===proposal?.id);
  const provider=proposal?.provider||run?.policy?.provider_runtime||{};
  const currentProvider=state.capabilities?.providers?.[0]||{};
  const usage=run?.policy?.usage||{};
  const simulation=Boolean(provider.is_simulation);
  const identity=provider.display_name||provider.model||provider.provider||'Provider 未记录';
  const generatedConfig=provider.config_revision||((provider.settings_version||'')?`model-config-${provider.settings_version}`:'');
  const configDrift=Boolean(generatedConfig&&currentProvider.config_revision&&generatedConfig!==currentProvider.config_revision);
  const tokens=Number(usage.input_tokens||0)+Number(usage.output_tokens||0);
  const usageLabel=tokens?` · ${Number(usage.input_tokens||0).toLocaleString()} 输入 / ${Number(usage.output_tokens||0).toLocaleString()} 输出 token`:'';
  const cache=usage.cache_read_tokens||usage.cache_write_tokens
    ? ` · 缓存读 ${Number(usage.cache_read_tokens||0).toLocaleString()} / 写 ${Number(usage.cache_write_tokens||0).toLocaleString()}`
    : '';
  const cacheStatus=String(usage.cache_status||usage.cache?.status||'').trim();
  const cacheLabel=cacheStatus?`缓存 ${cacheStatus}`:'缓存未报告';
  const cost=Number(usage.estimated_cost);
  const costLabel=Number.isFinite(cost)&&usage.estimated_cost!==null&&usage.estimated_cost!==undefined
    ? `费用估算 ${cost.toFixed(6)}`
    : '费用未报告';
  const configLabel=generatedConfig?`生成配置 ${generatedConfig}${configDrift?' · 当前配置已变化':''}`:'';
  const driftNote=configDrift?'<small class="proposal-runtime-note" title="候选固定在生成时配置；当前配置变化不会自动重跑，采纳前仍会校验正文基准版本">候选已固定，不会自动重跑；采纳前校验正文基准版本</small>':'';
  return `<details class="proposal-runtime-details"><summary>运行详情</summary><div class="proposal-runtime-meta" data-proposal-runtime><span class="${simulation?'is-simulation':'is-live'}">${simulation?'模拟 Provider':'真实 Provider'}</span><span class="proposal-runtime-identity"><small>生成时模型</small>${esc(identity)}</span>${configLabel?`<small class="proposal-runtime-config${configDrift?' is-drifted':''}">${esc(configLabel)}</small>`:''}${driftNote}<small>${run?`运行 ${esc(run.id)}${usageLabel}${cache}`:'运行证据待同步'}</small><small class="proposal-runtime-evidence">${cacheLabel} · ${costLabel}</small></div></details>`;
}

function sceneProposalImpactMarkup(proposal){
  const scene=selectedScene();
  const gates=state.work?.gates||[];
  const hadSceneReview=gates.some(gate=>gate.kind==='scene.review'&&gate.scope_id===scene?.id&&gate.snapshot?.revision_id===proposal?.base_revision_id);
  const hadWorkReview=gates.some(gate=>['continuity.review','release.review'].includes(gate.kind));
  const hasFrozenRelease=Boolean(state.work?.releases?.length);
  const items=['建立一版新的正式正文',hadSceneReview?'本场需要重新检查，当前检查结果不再适用':'本场需要重新检查'];
  if(hadWorkReview)items.push('连续性与发布检查需要重新运行');
  if(hasFrozenRelease)items.push('已有制作定稿保持不变');
  return `<div class="scene-proposal-impact" role="note" aria-label="应用后的影响"><b>应用后的影响</b><ul>${items.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`;
}

function sceneScriptLineParts(line){
  const match=String(line||'').match(/^([^:：]{1,24})[:：]\s*(.*)$/);
  if(!match)return{speaker:'',text:String(line||''),type:'action'};
  const speaker=match[1].trim(),text=match[2];
  return ['旁白','叙述'].includes(speaker)?{speaker:'',text,type:'narration'}:{speaker,text,type:'dialogue'};
}

function sceneContextLineMarkup(block,kind='',pair=null,side='new',lineNumber=''){
  const source=block||{type:'narration',text:''};
  const speaker=source.type==='narration'?'<b>旁白</b><span class="scene-diff-colon">：</span>':source.speaker?`<b>${esc(source.speaker)}</b><span class="scene-diff-colon">：</span>`:'';
  let content=esc(source.text||'');
  const segments=Array.isArray(pair?.segments)?pair.segments:[];
  if(segments.length){const visibleSegments=segments.filter(segment=>segment.kind==='equal'||(side==='old'?segment.kind==='delete':segment.kind==='insert')).map(segment=>`<span class="scene-inline-${esc(segment.kind)}">${esc(segment.text)}</span>`).join('');if(visibleSegments)content=visibleSegments}
  return `<div class="scene-context-line ${kind}"${lineNumber?` data-line="${lineNumber}"`:''}><span class="scene-context-number">${lineNumber||'·'}</span><span class="scene-context-copy">${speaker}<span>${content}</span></span></div>`;
}

function sceneFullContextMarkup(proposal,changes){
  const artifact=sceneScriptArtifact(selectedScene()),currentBlocks=artifact?.current_revision?.content?.blocks||[];
  const pairsByKey=new Map(),used=new Set();
  changes.forEach(change=>(change.inline_diff||[]).forEach(pair=>{if(pair.new_text!==undefined){const key=`${pair.new_speaker||''}|${pair.new_text||''}`;const entry={change,pair};const list=pairsByKey.get(key)||[];list.push(entry);pairsByKey.set(key,list)}}));
  const deletedAt=new Map();changes.filter(change=>change.kind==='delete').forEach(change=>deletedAt.set(Number(change.base_start)||0,[...(deletedAt.get(Number(change.base_start)||0)||[]),change]));
  const candidateLines=String(proposal.candidate||'').split(/\r?\n/).filter((line,index,all)=>line||index<all.length-1);
  const rows=[];let lineNumber=1;
  candidateLines.forEach((line,index)=>{
    (deletedAt.get(index)||[]).forEach(change=>(change.old_blocks||[]).forEach(block=>rows.push(sceneContextLineMarkup(block,'is-removed',null,'old',lineNumber++))));
    const block=sceneScriptLineParts(line),key=`${block.speaker}|${block.text}`,entry=(pairsByKey.get(key)||[]).find(item=>!used.has(`${item.change.id}|${item.pair.index}`));
    if(entry){used.add(`${entry.change.id}|${entry.pair.index}`);const oldBlock=entry.change.kind!=='insert'&&entry.pair.old_text!==undefined?{speaker:entry.pair.old_speaker,text:entry.pair.old_text,type:entry.pair.old_type||'dialogue'}:null;if(oldBlock&&oldBlock.text!==block.text)rows.push(sceneContextLineMarkup(oldBlock,'is-removed',entry.pair,'old',lineNumber));rows.push(sceneContextLineMarkup(block,'is-added',entry.pair,'new',lineNumber++));}
    else rows.push(sceneContextLineMarkup(block,'',null,'new',lineNumber++));
  });
  (deletedAt.get(candidateLines.length)||[]).forEach(change=>(change.old_blocks||[]).forEach(block=>rows.push(sceneContextLineMarkup(block,'is-removed',null,'old',lineNumber++))));
  return `<section class="scene-full-context" aria-label="完整正文预览"><header><div><b>完整正文预览</b><small>按需展开上下文；红色是将删除的原文，绿色是候选内容。</small></div><span>正文仍未写入</span><button type="button" class="quiet" data-scene-full-context-toggle>展开预览</button></header><div class="scene-context-lines" hidden>${rows.join('')}</div></section>`;
}

function sceneChangePreviewMarkup(change){
  const kind=String(change?.kind||'replace');
  const blocks=(kind==='delete'?change?.old_blocks:change?.new_blocks)||change?.old_blocks||[];
  const items=Array.isArray(blocks)?blocks.filter(block=>block&&String(block.text||'').trim()):[];
  if(!items.length)return '这项改动没有可显示的正文摘要';
  const first=items[0];
  const label=first.type==='narration'?'旁白':first.type==='action'?'动作':String(first.speaker||'对白');
  const suffix=items.length>1?` · 另有 ${items.length-1} 段`:'';
  return `${label}：${String(first.text).trim()}${suffix}`;
}

function sceneProposalReviewMarkup(proposal,options={}){
  const inline=Boolean(options.inline);
  const changes=Array.isArray(proposal.block_changes)?proposal.block_changes:[];
  if(!changes.length){
    return `<section class="candidate-desk scene-diff-desk ${inline?'scene-inline-review':''}"><div class="desk-head"><div><p class="eyebrow">正文改动 / 未写入</p><h3>这份候选没有可识别的改动</h3>${sceneProposalRuntimeMarkup(proposal)}</div><span class="status-chip amber">等待决定</span></div><div class="scene-diff-empty">请退回后重新生成；当前正文保持不变。</div><div class="desk-actions"><button class="quiet" data-reject="${esc(proposal.id)}">退回候选</button></div></section>`;
  }
  const knownIds=new Set(changes.map(change=>change.id));
  let selected=state.sceneDiffSelections[proposal.id];
  if(!(selected instanceof Set)){selected=new Set(knownIds);state.sceneDiffSelections[proposal.id]=selected}else selected=new Set([...selected].filter(id=>knownIds.has(id)));
  state.sceneDiffSelections[proposal.id]=selected;
  const changesMarkup=`<section class="scene-diff-choices" aria-label="选择要应用的修改">${changes.map((change,index)=>{const operation=change.kind==='insert'?'新增':change.kind==='delete'?'删除':'修改',preview=sceneChangePreviewMarkup(change);return`<label class="scene-diff-choice" title="${esc(preview)}"><input type="checkbox" value="${esc(change.id)}" data-scene-change ${selected.has(change.id)?'checked':''}><span><b>${operation} ${index+1}</b><small data-scene-change-preview>${esc(preview)}</small></span></label>`}).join('')}</section>`;
  return `<section class="candidate-desk scene-diff-desk ${inline?'scene-inline-review':''}" data-scene-diff-root="${esc(proposal.id)}"><div class="desk-head"><div><p class="eyebrow">正文改动 / 尚未写入</p><h3>改动已标在正文里</h3><p>在完整正文里审查改动：红色是将删除的原文，绿色是候选内容；先勾选，再应用到正文。</p>${sceneProposalRuntimeMarkup(proposal)}</div><span class="status-chip amber">等待决定</span></div>${changesMarkup}${sceneFullContextMarkup(proposal,changes)}${sceneProposalImpactMarkup(proposal)}<div class="desk-actions scene-diff-actions"><span class="scene-diff-count" data-scene-diff-count>已选择 ${selected.size} / ${changes.length} 项</span><button class="quiet" type="button" data-select-all-scene-changes="${esc(proposal.id)}">${selected.size===changes.length?'取消全选':'全部选择'}</button><button class="primary" type="button" data-apply-scene-changes="${esc(proposal.id)}" ${selected.size?'':'disabled'}>应用 ${selected.size} 项修改</button><button class="quiet" type="button" data-reject="${esc(proposal.id)}">退回候选</button></div></section>`;
}

function sceneFindingLabel(kind){return({ooc:'人物 OOC',continuity:'连续性',narration_ratio:'旁白占比',pacing_long_block:'段落节奏',pacing_turn_density:'对话节奏',meta_boundary:'元叙事边界',forbidden_reveal:'提前揭示',character_card_missing:'人物卡缺失'})[kind]||'场景检查'}
function sceneFindingEvidence(finding){const evidence=finding.evidence||{};if(finding.kind==='narration_ratio')return `旁白 ${Math.round(Number(evidence.narration_ratio||0)*100)}% · ${evidence.narration_block_count||0}/${evidence.block_count||0} 块`;if(finding.kind==='pacing_long_block')return `${(evidence.long_blocks||[]).length} 个长块 · 行 ${(evidence.long_blocks||[]).map(item=>item.line).join('、')}`;if(finding.kind==='pacing_turn_density')return `同一角色最多连续 ${evidence.max_same_speaker_turns||0} 次`;return evidence.source==='provider'?'BA 审查 Agent':'确定性检查'}
function sceneReviewFindingsMarkup(findings){if(!findings.length)return'';const severityLabel={blocking:'阻塞',warning:'建议处理',info:'提示'},blocking=findings.some(item=>item.severity==='blocking');return `<details class="scene-review-summary ${blocking?'has-blocker':''}"><summary><span class="scene-review-summary-label">审查</span><b>${findings.length} 项待处理</b><small>${blocking?'有发布阻塞，需要处理':'建议项不会自动改动正文'}</small><span class="scene-review-summary-chevron" aria-hidden="true">⌄</span></summary><div class="scene-review-findings-body">${findings.map(item=>`<article class="scene-review-finding ${esc(item.severity)}"><div><span>${esc(sceneFindingLabel(item.kind))} · ${esc(severityLabel[item.severity]||item.severity)}</span><b>${esc(item.message)}</b><small>${esc(sceneFindingEvidence(item))}</small></div><button class="quiet" type="button" data-resolve-finding="${esc(item.id)}">标记已处理</button></article>`).join('')}</div></details>`}

function renderDraft(el){
  const scene=selectedScene(),chapter=writingChapter(),chapterScenes=chapter?.scenes||[],proposal=pendingProposal(),findings=(state.work.review_findings||[]).filter(f=>f.scene_id===scene?.id&&f.status==='open');
  if(!scene){el.innerHTML=frame('04 / SCENE DRAFT','还没有可写的场景','先建立章节和场景，再开始本场工作。','<button class="primary" data-stage-jump="structure">建立场景</button>');return}
  if(state.manuscriptSceneId!==scene.id){state.manuscriptSceneId=scene.id;state.manuscriptDirty=false}
  const orderedScenes=chapterScenes.length?chapterScenes:(scene?[scene]:[]),manuscript=sceneScriptArtifact(scene);
  el.innerHTML=`<div class="chapter-continuous"><div class="chapter-continuous-head"><div><p class="eyebrow">04 / CHAPTER DRAFT</p><h2>${esc(chapter?.title||scene.chapterTitle)}</h2><p class="lede">这一章是一份连续正文；场景标题只是定位锚点，向下阅读不会切换页面。</p></div><div class="chapter-continuous-actions"><button type="button" class="primary" data-inspector="agent">让 Agent 修改</button><details class="chapter-more-tools"><summary>更多</summary><div><button type="button" class="quiet" data-toggle-scene-context>资料与设定</button><button type="button" class="quiet scene-assets-trigger" data-scene-asset-picker="${esc(scene.id)}">素材</button><button type="button" class="quiet" data-action="review-scene">检查本章</button></div></details></div></div><div class="chapter-manuscript-flow">${orderedScenes.map((item,index)=>item.id===scene.id?chapterActiveSceneMarkup(item,index,manuscript,proposal,findings):chapterReadonlySceneMarkup(item,index)).join('')}</div></div>`;
}
function sceneWorldItems(){const world=worldBible();return [...(world.entities||[]).map(item=>({...item,_collection:'entities',label:item.name||''})),...(world.rules||[]).map(item=>({...item,_collection:'rules',label:item.text||''})),...(world.timeline||[]).map(item=>({...item,_collection:'timeline',label:item.text||''}))].filter(item=>item.status!=='archived')}
function sceneContextSelection(scene){return scene?.contract?.context_selection||{mode:'legacy',character_card_ids:[],world_item_ids:[],reference_file_ids:[]}}
function contextPill(label,items){return `<div class="context-mini-group"><b>${label}</b><span>${items.length?items.map(esc).join('、'):'未选择'}</span></div>`}
function decorateSceneContext(){
  if(state.stage!=='draft'||state.mobileView!=='writing')return;
  const activeScene=selectedScene(),sceneHeadMeta=$('.scene-head > div > p:last-child');
  if(activeScene&&sceneHeadMeta&&!sceneHeadMeta.querySelector('[data-scene-mode]')){
    const mode=document.createElement('span');
    mode.dataset.sceneMode='';mode.className='scene-mode-inline';
    mode.textContent=` · ${sceneModeLabel(activeScene.contract?.writing_mode||brief()?.mode||'bond_short')}`;
    sceneHeadMeta.append(mode);
  }
  // The continuous chapter renderer replaced the legacy scene workbench.
  // Mount the context controls in that single-page flow so explicit scene
  // selections remain available without bringing back a second page.
  const scene=selectedScene(),host=$('.chapter-continuous');if(!scene||!host)return;
  const selection=sceneContextSelection(scene),explicit=selection.mode==='explicit',narratorOnly=blueprint()?.narrator_only===true,cards=libraryCards().filter(card=>card.status!=='archived'),worldItems=sceneWorldItems(),files=state.work.reference_files||[];
  const cardById=new Map(cards.map(card=>[card.id,card])),worldById=new Map(worldItems.map(item=>[item.id,item])),fileById=new Map(files.map(file=>[file.id,file]));
  const legacyCharacters=(brief()?.characters||[]),summaryCards=explicit?selection.character_card_ids.map(id=>cardById.get(id)?.name||id):legacyCharacters,summaryWorld=explicit?selection.world_item_ids.map(id=>worldById.get(id)?.label||id):worldItems.filter(item=>item.confidence_status==='confirmed').map(item=>item.label),summaryFiles=explicit?selection.reference_file_ids.map(id=>fileById.get(id)?.title||id):files.map(file=>file.title);
  const confirmedCards=cards.filter(card=>card.trust_status==='confirmed');
  const editor=state.sceneContextEditorOpen?(confirmedCards.length||narratorOnly?`<form id="sceneContextForm" class="scene-context-form"><p class="context-form-note">${narratorOnly?'这是纯旁白场景，不需要人物卡；可以只固定世界设定和证据资料。':'选择后，场景只读取这些条目。人物卡必须是“已确认”，世界设定必须是“已确认且未归档”；证据资料可以为空。'}</p><fieldset><legend>人物卡 <small>${narratorOnly?'纯旁白场景留空':'至少选择一张'}</small></legend>${narratorOnly?'<p class="context-empty">本场已明确为纯旁白，不会装配人物卡。</p>':cards.map(card=>`<label class="context-check ${card.trust_status==='confirmed'?'':'disabled'}"><input type="checkbox" name="character_card_ids" value="${esc(card.id)}" ${(explicit?selection.character_card_ids:cards.filter(item=>legacyCharacters.includes(item.name)&&item.trust_status==='confirmed').map(item=>item.id)).includes(card.id)?'checked':''} ${card.trust_status==='confirmed'?'':'disabled'}><span><b>${esc(card.name)}</b><small>${esc(libraryKindLabel(card.source_type))} · ${esc(trustLabel(card.trust_status))}</small></span></label>`).join('')}</fieldset><fieldset><legend>世界设定 <small>可留空</small></legend>${worldItems.length?worldItems.map(item=>`<label class="context-check ${item.confidence_status==='confirmed'?'':'disabled'}"><input type="checkbox" name="world_item_ids" value="${esc(item.id)}" ${(explicit?selection.world_item_ids:worldItems.filter(entry=>entry.confidence_status==='confirmed').map(entry=>entry.id)).includes(item.id)?'checked':''} ${item.confidence_status==='confirmed'?'':'disabled'}><span><b>${esc(item.label)}</b><small>${esc(worldKindLabel(item.kind)||item._collection)} · ${esc(confidenceLabel(item.confidence_status))}</small></span></label>`).join(''):'<p class="context-empty">暂无世界观条目；可以在资料库中添加。</p>'}</fieldset><fieldset><legend>证据资料 <small>可留空</small></legend>${files.length?files.map(file=>`<label class="context-check"><input type="checkbox" name="reference_file_ids" value="${esc(file.id)}" ${(explicit?selection.reference_file_ids:files.map(entry=>entry.id)).includes(file.id)?'checked':''}><span><b>${esc(file.title)}</b><small>${esc(referenceTrustLabel(file.trust_status))} · ${esc(file.source_label)}</small></span></label>`).join(''):'<p class="context-empty">暂无资料文件；可以在资料库中登记或导入原作摘录。</p>'}</fieldset><div class="actions"><button class="primary" type="submit">保存本场上下文</button><button class="quiet" type="button" data-toggle-scene-context>取消</button></div></form>`:`<div class="scene-context-blocked"><b>先建立本场人物卡</b><p>这场的 Brief 提到了 ${esc(legacyCharacters.join('、')||'角色')}，但资料库还没有已确认的人物卡。先补齐角色声音和知情边界，才能固定本场读取范围。</p><button class="primary" type="button" data-open-context-characters>去建立人物卡</button></div>`):'';
  const section=document.createElement('section');section.className='scene-context-panel';section.innerHTML=`<div class="scene-context-head"><div><p class="eyebrow">SCENE CONTEXT</p><h3>本场上下文</h3><p>${explicit?'以下选择已保存，只会影响下一次装配和生成。':'当前仍使用旧作品的兼容规则：按 Brief 角色、全部已确认世界观和全部资料装配。保存后可固定本场范围。'}</p></div><button class="quiet" data-toggle-scene-context>${state.sceneContextEditorOpen?'收起编辑':'编辑本场上下文'}</button></div><div class="scene-context-summary"><span class="context-mode ${explicit?'explicit':'legacy'}">${explicit?'已固定范围':'兼容范围'}</span>${contextPill('人物卡',summaryCards)}${contextPill('世界设定',summaryWorld)}${contextPill('证据资料',summaryFiles)}</div>${editor}`;
  const activeSection=document.getElementById(`chapter-scene-${scene.id}`);
  const anchor=$('.chapter-manuscript-flow',host);
  if(activeSection) activeSection.prepend(section);
  else anchor?.before(section);
}
document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;
  if(button.dataset.sceneFullContextToggle!==undefined){event.preventDefault();event.stopImmediatePropagation();const section=button.closest('.scene-full-context'),content=section?.querySelector('.scene-context-lines');if(content){content.hidden=!content.hidden;button.textContent=content.hidden?'展开预览':'收起预览'}return}
  if(button.dataset.agentCompleteCards!==undefined){event.preventDefault();event.stopImmediatePropagation();const scene=selectedScene();captureSceneRecovery(scene);state.prefillCharacter=sceneRecoveryCharacterName(scene);state.stage='references';state.mobileView='writing';state.libraryView='characters';state.libraryEditorOpen=true;state.characterCardDraft={name:state.prefillCharacter};state.editCardId='';state.editCard=null;state.writingMobileView='manuscript';render();focusCharacterCardName();return}
  if(button.dataset.action==='open-character-card'){event.preventDefault();event.stopImmediatePropagation();const scene=selectedScene();captureSceneRecovery(scene);state.prefillCharacter=sceneRecoveryCharacterName(scene);state.stage='references';state.mobileView='writing';state.libraryView='characters';render();focusCharacterCardName();}if(button.dataset.focusCandidate!==undefined){event.preventDefault();event.stopImmediatePropagation();const review=$('[data-scene-diff-root]');review?.scrollIntoView({block:'start',behavior:'smooth'});review?.querySelector('[data-scene-change]')?.focus()}if(button.dataset.agentInstruction){event.preventDefault();event.stopImmediatePropagation();const input=$('#agentRunForm textarea[name="instruction"]');if(input){input.value=button.dataset.agentInstruction;input.focus()}}},true);

function updateSceneDiffSelection(root){
  if(!root)return;
  const inputs=[...root.querySelectorAll('[data-scene-change]')],selected=inputs.filter(input=>input.checked),button=root.querySelector('[data-apply-scene-changes]'),selectAll=root.querySelector('[data-select-all-scene-changes]'),count=root.querySelector('[data-scene-diff-count]');
  state.sceneDiffSelections[root.dataset.sceneDiffRoot]=new Set(selected.map(input=>input.value));
  if(count)count.textContent=`已选择 ${selected.length} / ${inputs.length} 项`;
  if(button){button.textContent=`应用 ${selected.length} 项修改`;button.disabled=selected.length===0}
  if(selectAll)selectAll.textContent=selected.length===inputs.length?'取消全选':'全部选择';
}

document.addEventListener('change',event=>{
  if(!event.target.matches?.('[data-scene-change]'))return;
  updateSceneDiffSelection(event.target.closest('[data-scene-diff-root]'));
},true);

document.addEventListener('click',event=>{
  const selectAll=event.target.closest?.('[data-select-all-scene-changes]'),apply=event.target.closest?.('[data-apply-scene-changes]');
  if(!selectAll&&!apply)return;
  event.preventDefault();event.stopImmediatePropagation();
  const button=selectAll||apply,root=button.closest('[data-scene-diff-root]');
  if(selectAll){const inputs=[...root.querySelectorAll('[data-scene-change]')],next=!inputs.every(input=>input.checked);inputs.forEach(input=>{input.checked=next});updateSceneDiffSelection(root);return}
  const selected=[...root.querySelectorAll('[data-scene-change]:checked')].map(input=>input.value);
  if(!selected.length){toast('请至少选择一项正文修改。',true);return}
  (async()=>{try{button.disabled=true;const proposalId=button.dataset.applySceneChanges,result=await api(`/works/${state.work.id}/proposals/${proposalId}/accept`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,selected_change_ids:selected,note:`应用 ${selected.length} 项正文修改`})});state.work=result.work;state.sceneTextSelection=null;delete state.sceneDiffSelections[proposalId];toast('新正文版本已建立；旧审查结果不再适用，请先检查本场');render()}catch(error){button.disabled=false;toast(error.message,true)}})();
},true);
function captureManuscriptDraft(){if(!$('#sceneManuscriptForm'))return;state.manuscriptDraftBlocks=readManuscriptBlocks()}
function markManuscriptDirty(){if(!state.manuscriptDirty)state.manuscriptDirtyUrl=location.href;state.manuscriptDirty=true;captureManuscriptDraft();const badge=$('#manuscriptSaveState');if(badge){badge.textContent='未保存修改';badge.className='manuscript-state dirty'}}
 function normalizeManuscriptRows(){const rows=$$('[data-manuscript-block]');rows.forEach((row,index)=>{const indexLabel=$('.block-gutter>span',row);if(indexLabel)indexLabel.textContent=String(index+1).padStart(2,'0');const type=$('select[name="type"]',row)?.value||'action';row.dataset.blockType=type;row.classList.toggle('is-action',type==='action');row.classList.toggle('is-narration',type==='narration');const speaker=$('input[name="speaker"]',row);if(speaker){speaker.disabled=type!=='dialogue';if(type!=='dialogue')speaker.value=''}});const empty=$('[data-manuscript-empty]');if(empty)empty.remove()}
function beginManuscriptEditing(row){if(!row)return;document.querySelectorAll('[data-manuscript-block].is-editing').forEach(item=>{if(item!==row&&!item.contains(document.activeElement))item.classList.remove('is-editing')});row.classList.add('is-editing');const textarea=$('textarea[name="text"]',row);textarea?.focus();textarea?.setSelectionRange(textarea.value.length,textarea.value.length)}
function syncManuscriptReading(row){if(!row)return;const type=$('select[name="type"]',row)?.value||'action',speaker=$('input[name="speaker"]',row)?.value||'',text=$('textarea[name="text"]',row)?.value||'',typeLabel={action:'动作',narration:'旁白',dialogue:'对白'}[type],typeRead=$('.manuscript-reading-type',row),speakerRead=$('.manuscript-reading-speaker',row),reading=$('.manuscript-reading-text',row);if(typeRead)typeRead.textContent=typeLabel;if(speakerRead){speakerRead.textContent=type==='dialogue'?(speaker||'说话人'):'';speakerRead.toggleAttribute('aria-hidden',type!=='dialogue')}if(reading)reading.textContent=text||'点击输入正文';row.dataset.blockType=type}
function addManuscriptBlock(type,afterId=''){const list=$('[data-manuscript-list]');if(!list)return;const empty=list.querySelector('[data-manuscript-empty]');if(empty)list.innerHTML='';const block={id:makeClientBlockId(),type,text:'',speaker:''};const temp=document.createElement('div');temp.innerHTML=blockRowMarkup(block,$$('[data-manuscript-block]',list).length,true);const row=temp.firstElementChild;const target=afterId?list.querySelector(`[data-manuscript-insert="${CSS.escape(afterId)}"]`)?.closest('[data-manuscript-insert-bar]'):null;if(target){target.after(row);row.after(new DOMParser().parseFromString(manuscriptInsertBarMarkup(block.id),'text/html').body.firstElementChild)}else{list.append(row);list.insertAdjacentHTML('beforeend',manuscriptInsertBarMarkup(block.id))}normalizeManuscriptRows();markManuscriptDirty();beginManuscriptEditing(row)}
 function readManuscriptBlocks(){return $$('[data-manuscript-block]').map(row=>{const type=$('select[name="type"]',row)?.value||'action',text=$('textarea[name="text"]',row)?.value||'',block={id:row.dataset.blockId,type,text};if(type==='dialogue')block.speaker=$('input[name="speaker"]',row)?.value||'';return block})}
document.addEventListener('click',event=>{const edit=event.target.closest?.('[data-manuscript-edit]');if(edit){event.preventDefault();event.stopImmediatePropagation();beginManuscriptEditing(edit.closest('[data-manuscript-block]'));return}const insert=event.target.closest?.('[data-manuscript-insert]');if(insert){event.preventDefault();event.stopImmediatePropagation();addManuscriptBlock('narration',insert.dataset.manuscriptInsert||'');return}const emptyInsert=event.target.closest?.('[data-manuscript-insert-empty]');if(emptyInsert){event.preventDefault();event.stopImmediatePropagation();addManuscriptBlock('narration');return}const button=event.target.closest('button');if(!button)return;if(button.dataset.manuscriptAdd){event.preventDefault();event.stopImmediatePropagation();addManuscriptBlock(button.dataset.manuscriptAdd);return}if(button.dataset.manuscriptRemove!==undefined){event.preventDefault();event.stopImmediatePropagation();const row=button.closest('[data-manuscript-block]');if(!row)return;const following=row.nextElementSibling;if(following?.matches('[data-manuscript-insert-bar]'))following.remove();row.remove();normalizeManuscriptRows();if(!$$('[data-manuscript-block]').length){const list=$('[data-manuscript-list]');if(list)list.innerHTML='<div class="manuscript-empty" data-manuscript-empty><b>正文已清空</b><button type="button" class="manuscript-empty-insert" data-manuscript-insert-empty><span aria-hidden="true">+</span><span>添加第一段</span></button></div>'}markManuscriptDirty();return}if(button.dataset.manuscriptMove){event.preventDefault();event.stopImmediatePropagation();const row=button.closest('[data-manuscript-block]'),bar=row?.nextElementSibling;if(!row||!bar?.matches('[data-manuscript-insert-bar]'))return;if(button.dataset.manuscriptMove==='up'){const previous=row.previousElementSibling?.previousElementSibling;if(previous?.matches('[data-manuscript-block]'))previous.before(row,bar)}else{const next=bar.nextElementSibling,nextBar=next?.nextElementSibling;if(next?.matches('[data-manuscript-block]')&&nextBar?.matches('[data-manuscript-insert-bar]'))nextBar.after(row,bar)}normalizeManuscriptRows();markManuscriptDirty();return}},true);
document.addEventListener('change',event=>{const field=event.target.closest('[data-manuscript-block] select[name="type"]');if(!field)return;const row=field.closest('[data-manuscript-block]');normalizeManuscriptRows();syncManuscriptReading(row);markManuscriptDirty()},true);
document.addEventListener('input',event=>{const row=event.target.closest?.('[data-manuscript-block]');if(!row)return;syncManuscriptReading(row);markManuscriptDirty()},true);
document.addEventListener('focusin',event=>{const row=event.target.closest?.('[data-manuscript-block]');if(row)row.classList.add('is-editing')},true);
document.addEventListener('focusout',event=>{const row=event.target.closest?.('[data-manuscript-block]');if(row)setTimeout(()=>{if(!row.contains(document.activeElement))row.classList.remove('is-editing')},0)},true);
document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='sceneManuscriptForm')return;event.preventDefault();event.stopImmediatePropagation();try{const sceneId=form.dataset.sceneId||state.sceneId,scene=scenes().find(item=>item.id===sceneId),blocks=readManuscriptBlocks();if(!scene)throw new Error('当前正文所在场景已变化，请重新打开后再保存。');if(!blocks.length)throw new Error('请先新增至少一个动作或对白块。');setBusy('正在保存新的正文修订');const result=await api(`/works/${state.work.id}/scenes/${scene.id}/manuscript`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,expected_base_revision_id:form.dataset.baseRevision||null,blocks})});state.work=result.work;state.sceneId=scene.id;state.writingChapterId=scene.chapter_id;state._pendingChapterSceneScroll=scene.id;discardManuscriptDraft();state.sceneTextSelection=null;toast(result.superseded_proposal_ids?.length?'正文已保存为新修订；旧候选已替代。':'正文已保存为新修订');render()}catch(error){setBusy('正文未保存');toast(error.message,true)}},true);
function renderInspector(){const el=$('#inspectorContent'),scene=selectedScene(),proposal=pendingProposal(),latest=state.work?.releases?.[0],findings=(state.work?.review_findings||[]).filter(item=>item.scene_id===scene?.id&&item.status==='open'),blocker=findings.find(item=>item.severity==='blocking'),warning=findings.find(item=>item.severity==='warning');$$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector===state.inspector));if(state.inspector==='decision'){const message=proposal?'候选已经生成，正文尚未改变。请检查 Diff 后决定。':blocker?blocker.message:warning?warning.message:state.stage==='release'&&latest?'当前发布版本已完成交接。':'当前场景没有待处理阻塞项。';const action=proposal?'候选等待决定':blocker?'处理阻塞项':warning?'补齐人物卡后重新审查':'可以生成候选或检查本场';el.innerHTML=`<div class="inspector-body"><p class="eyebrow">SCENE DECISION</p><h3>${esc(action)}</h3><div class="notice ${blocker?'bad':warning?'':'good'}">${esc(message)}</div><ul class="context-list"><li><b>当前场景</b><br>${esc(scene?.title||'未选择')}</li><li><b>审查状态</b><br>${blocker?'存在阻塞项':warning?'存在提示项':'没有开放发现'}</li><li><b>写入规则</b><br>Agent 只能提交 Proposal，用户采纳后才建立修订。</li></ul></div>`}else if(state.inspector==='context'){const c=state.context;el.innerHTML=`<div class="inspector-body"><p class="eyebrow">PINNED CONTEXT</p><h3>本场固定输入</h3><p>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'未选择场景'}</p><ul class="context-list">${c?`<li>规则包<br><b>${esc(c.rules.pack_version)}</b></li><li>单一模式<br><b>${esc(c.rules.mode)}</b></li><li>固定输入修订<br><b>${c.source_revision_ids.length} 个</b></li><li>运行时人物卡<br><b>${c.runtime_character_cards.length} 张</b></li>`:'<li>执行“装配上下文”后查看本场固定输入。</li>'}</ul></div>`}else{const existing=scene?.current_revision_id,latestRun=(state.work?.agent_runs||[]).find(run=>run.scope_id===scene?.id),mode=existing?'rewrite':'draft',missingCharacters=(warning?.kind==='character_card_missing'?warning.evidence?.speakers||[]:[]),agentReady=!proposal&&!missingCharacters.length;const chips=existing?`<div class="agent-chips"><button type="button" class="quiet" data-agent-instruction="调整本场节奏：压缩解释，让动作和停顿先出现。">调整节奏</button><button type="button" class="quiet" data-agent-instruction="检查人物是否 OOC，并把需要调整的对白改写为更符合人物卡的表达。">检查 OOC</button><button type="button" class="quiet" data-agent-instruction="重写选中对白：保留本场事实、角色关系和停止边界。">重写选中对白</button></div>`:'';const blocked=missingCharacters.length?`<div class="notice bad">还不能运行：${esc(missingCharacters.join('、'))} 尚无已确认人物卡。补齐后才能把正文与人物约束一起交给 Agent。</div><button type="button" class="primary" data-agent-complete-cards>补齐人物卡</button>`:'';el.innerHTML=`<div class="inspector-body"><p class="eyebrow">BA WRITING AGENT</p><h3>${existing?'改写当前场景':'起草当前场景'}</h3><p>${existing?'当前正文会作为固定输入，Agent 只返回完整场景候选和 Diff，不会直接改动任何一句。':'只读取本场合同、单一 BA 模式和运行时人物卡；每次只提交一份 Proposal。'}</p>${latestRun?`<section class="agent-run"><b>${esc(latestRun.status)}</b><p>工具记录 ${latestRun.tool_calls.length} 项${latestRun.proposal_id?` · Proposal ${esc(latestRun.proposal_id)}`:''}</p></section>`:''}${blocked}<form id="agentRunForm" data-agent-mode="${mode}"><label>本场指令<textarea name="instruction" placeholder="${existing?'例如：压缩解释，保留爱丽丝先观察、凯伊后补充的节奏':'例如：以爱丽丝先观察、凯伊后补充的节奏起草本场'}" ${agentReady?'':'disabled'}></textarea></label>${agentReady?chips:''}<button class="primary" type="submit" ${agentReady?'':'disabled'}>${existing?'生成完整改写候选':'运行 BA 场景 Agent'}</button></form><p class="form-note">${existing?'完整候选不会写回正文，采纳后才建立新的正文修订。':providerDisclosure()}</p></div>`}}

// The library is a source-of-truth work surface, not a loose notes page.  It
// intentionally keeps original references distinct from work-local invention.
function libraryCards(){return state.work?.artifacts.filter(item=>item.kind==='character_card'&&item.current_revision?.content).map(item=>({id:item.scope_id,artifactId:item.id,...item.current_revision.content,revision:item.current_revision.ordinal,revisions:item.revisions||[]}))||[]}
function workCanon(){return artifact('work_canon')||{facts:[]}}
function workCanonArtifact(){return state.work?.artifacts.find(item=>item.kind==='work_canon')}
function worldBible(){return artifact('world_bible')||{title:'作品世界观',source_type:'custom',entities:[],rules:[],timeline:[]}}
function libraryKindLabel(type){return({official_reference:'原作参考',custom:'自定义设定',mixed:'原作参考 + 自定义',ba_starter:'BA 起始架构'})[type]||'旧版未标注'}
function trustLabel(status){return({confirmed:'可用于写作',open:'待核对',inferred:'推断待确认',unverified:'未核验',conflict:'存在冲突'})[status]||'待核对'}
function confidenceLabel(status){return({confirmed:'已确认',open:'待决定',inferred:'推断',unverified:'未核验',conflict:'存在冲突',retired:'已废弃'})[status]||'待决定'}
function referenceTrustLabel(status){return({official_reference:'原作摘录',confirmed:'已确认',open:'待核对',inferred:'推断待确认',unverified:'未核验',conflict:'存在冲突'})[status]||'待核对'}
function worldKindLabel(kind){return({place:'地点',academy:'学院',organization:'组织',object:'物件',technology:'技术',custom:'本作原创'})[kind]||'设定'}
function worldRuleScopeLabel(scope){return({work:'整部作品范围',chapter:'章节范围',scene:'场景范围'})[scope]||'范围待确认'}
function worldRuleCategoryLabel(category){return({general:'通用规则',technology:'技术规则',organization:'组织规则',place:'地点规则',adaptation:'本作改写'})[category]||String(category||'未分类')}
function normalizedSearch(value){return String(value||'').trim().toLocaleLowerCase('zh-CN')}
function includesSearch(values,query){const needle=normalizedSearch(query);return !needle||values.some(value=>normalizedSearch(value).includes(needle))}
function matchesTrust(status,filter){if(filter==='all')return true;if(filter==='confirmed')return status==='confirmed';return status!=='confirmed'}
function libraryToolbar({query,placeholder,queryName,filters=[]}){return `<div class="asset-toolbar"><label class="asset-search"><span>搜索</span><input name="${queryName}" value="${esc(query)}" placeholder="${esc(placeholder)}"></label><div class="asset-filters">${filters.map(filter=>`<label><span>${esc(filter.label)}</span><select data-library-filter-key="${esc(filter.key)}">${filter.options.map(option=>`<option value="${esc(option.value)}" ${filter.value===option.value?'selected':''}>${esc(option.label)}</option>`).join('')}</select></label>`).join('')}</div></div>`}
function relationRows(cards){return cards.flatMap(card=>(card.relationships||[]).map(link=>({...link,from:card.name,from_id:card.id,to_id:cards.find(item=>item.name===link.target)?.id||''})).filter(link=>link.to_id))}
function projectionNodeId(id){return String(id||'').replace(/^world_entity:/,'entity:').replace(/^world_rule:/,'rule:').replace(/^timeline_event:/,'event:').replace(/^canon_fact:/,'fact:')}
function projectionNodeType(type){return ({world_entity:'entity',world_rule:'rule',timeline_event:'event',canon_fact:'fact'})[type]||type}
function projectionStatusLabel(status){return ({confirmed:'已确认',inferred:'推断',open:'待核对',conflict:'有冲突',retired:'已停用'})[status]||status||'待核对'}
function graphRecords(){
  if(!currentProjectionReady())return[];
  return (state.currentProjection.knowledge_graph?.nodes||[]).map(node=>({
    id:projectionNodeId(node.id),type:projectionNodeType(node.type),label:node.label,
    meta:`${projectionStatusLabel(node.status)} · 当前修订`,target:node.source_ref?.item_id,
    sourceRef:node.source_ref,
  }));
}
function graphLinks(){
  if(!currentProjectionReady())return[];
  return (state.currentProjection.knowledge_graph?.edges||[]).map(link=>({
    id:link.id,from:projectionNodeId(link.from),to:projectionNodeId(link.to),
    kind:link.label,summary:link.summary||'关系说明待补充',resolution:link.resolution,
    sourceRef:link.source_ref,
  }));
}
function unconfirmedWorldCards(world){return (world.entities||[]).filter(item=>item.status!=='archived'&&item.confidence_status!=='confirmed')}
function pendingKnowledgeProposals(){
  const knowledgeKinds=new Set(['character_card','world_entity','world_rule','canon_fact']);
  return (state.work?.proposals||[]).filter(item=>item.status==='pending'&&item.scope_type==='work'&&knowledgeKinds.has(item.kind));
}
function libraryDecisionGuideMarkup(){
  const cards=libraryCards().filter(item=>item.status!=='archived'),world=worldBible(),worldCards=(world.entities||[]).filter(item=>item.status!=='archived'),worldRules=(world.rules||[]).filter(item=>item.status!=='archived'),canonFacts=(workCanon().facts||[]).filter(item=>item.status!=='archived'),pending=pendingKnowledgeProposals(),pendingWorld=unconfirmedWorldCards(world),nextWorld=pendingWorld[0],pendingCharacters=cards.filter(card=>card.trust_status!=='confirmed'),nextCharacter=pendingCharacters[0],graphNodes=graphRecords(),graphEdges=graphLinks(),isolated=graphNodes.filter(node=>!graphEdges.some(edge=>edge.from===node.id||edge.to===node.id)).length,formalCount=cards.length+worldCards.length+worldRules.length+canonFacts.length;
  let title='',detail='',actions='';
  if(pending.length){
    const target=pending[0],targetTitle=target.candidate?.content?.name||target.candidate?.content?.text||'资料候选';
    title=`先处理 ${pending.length} 项待审资料`;
    detail=`「${targetTitle}」仍是候选，尚未进入正式资料。审查后，这里的统计和后续写作状态会自动更新。`;
    actions='<button class="primary" type="button" data-library-view="suggestions">审查资料候选</button>';
  }else if(nextWorld){
    title=`先确认「${nextWorld.name}」在本作中的定义`;
    detail='BA 起始卡只是可编辑目录，不会冒充官方设定。打开后补充本作定义、证据和角色关联，再决定是否让它进入 Agent。';
    actions=`<button class="primary" data-edit-world-entry="entity:${esc(nextWorld.id)}">打开待核对世界卡</button><button class="quiet" data-library-view="official">检索 BA 原作证据</button>`;
  }else if(nextCharacter){
    title=`补齐「${nextCharacter.name}」的人物边界`;
    detail='人物卡必须明确声音、知情范围和 OOC 红线；确认后才会成为可选的场景上下文。';
    actions='<button class="primary" data-library-view="characters">管理人物卡</button><button class="quiet" data-library-view="relations">检查关系图</button>';
  }else if(!formalCount){
    title='先建立第一项创作资料';
    detail='回到作品 Agent，描述人物、世界规则或本作事实。Agent 会先生成候选，只有你审查并应用后才会成为正式资料。';
    actions='<button class="primary" type="button" data-library-return-to-agent>返回作品 Agent</button>';
  }else{
    title='资料库已具备可写基础';
    detail='现在可以检查知识图和场景上下文，决定哪些已确认资料给下一场使用。';
    actions='<button class="primary" data-library-view="relations">打开关系图</button><button class="quiet" data-stage-jump="draft">配置场景上下文</button>';
  }
  const queue=[
    [pendingWorld.length,'待核对世界卡','确认来源与本作采用范围','data-library-view="world"','处理'],
    [pendingCharacters.length,'待核对人物卡','补齐声音、边界与关系','data-library-view="characters"','处理'],
    [isolated,'尚未连线的条目','在关系图检查孤立设定','data-library-view="relations"','查看']
  ].filter(([count])=>count>0);
  return `<section class="library-control-deck"><div class="library-control-copy"><p class="eyebrow">NEXT DECISION</p><h3>${esc(title)}</h3><p>${esc(detail)}</p><div class="actions">${actions}</div></div>${queue.length?`<ol class="library-decision-queue">${queue.map(([count,label,description,action,verb])=>`<li><span>${count}</span><div><b>${label}</b><small>${description}</small></div><button class="quiet" ${action}>${verb}</button></li>`).join('')}</ol>`:''}</section>`;
}
function worldCardPayload(current,card){return {title:current.title,source_type:current.source_type,entities:(current.entities||[]).map(item=>item.id===card.id?card:item),rules:current.rules||[],timeline:current.timeline||[]}}
function cardLinkedWorldIds(card,world){return (world.entities||[]).filter(item=>(item.participants||[]).includes(card.name)&&item.status!=='archived').map(item=>item.id)}
let archiveConfirmationAction=null;
let archiveConfirmationOpener=null;
function archiveConfirmationDialog(){
  let dialog=$('#archiveConfirmationDialog');
  if(dialog)return dialog;
  dialog=document.createElement('dialog');
  dialog.id='archiveConfirmationDialog';
  dialog.className='archive-confirmation-dialog';
  dialog.innerHTML=`<section aria-labelledby="archiveConfirmationTitle"><header><p class="eyebrow">归档确认</p><h2 id="archiveConfirmationTitle"></h2></header><p data-archive-confirmation-detail></p><footer><button type="button" class="quiet" data-archive-confirm-cancel>取消</button><button type="button" class="danger" data-archive-confirm-accept></button></footer></section>`;
  dialog.addEventListener('click',event=>{
    const cancel=event.target.closest?.('[data-archive-confirm-cancel]');
    const accept=event.target.closest?.('[data-archive-confirm-accept]');
    if(!cancel&&!accept)return;
    event.preventDefault();
    if(cancel){dialog.close();return}
    const action=archiveConfirmationAction;
    archiveConfirmationAction=null;
    archiveConfirmationOpener=null;
    dialog.close();
    void action?.();
  });
  dialog.addEventListener('close',()=>{
    const opener=archiveConfirmationOpener;
    archiveConfirmationAction=null;
    archiveConfirmationOpener=null;
    requestAnimationFrame(()=>opener?.focus?.());
  });
  document.body.append(dialog);
  return dialog;
}
function requestArchiveConfirmation({title,detail,acceptLabel,action,opener}){
  const dialog=archiveConfirmationDialog();
  archiveConfirmationAction=action;
  archiveConfirmationOpener=opener||document.activeElement;
  dialog.querySelector('#archiveConfirmationTitle').textContent=title;
  dialog.querySelector('[data-archive-confirmation-detail]').textContent=detail;
  dialog.querySelector('[data-archive-confirm-accept]').textContent=acceptLabel;
  if(!dialog.open)dialog.showModal();
  dialog.querySelector('[data-archive-confirm-cancel]')?.focus();
}
function renderReferences(el){
  ensureCurrentProjection();
  const projectionReady=currentProjectionReady(),projection=projectionReady?state.currentProjection:null,view=state.libraryView||'overview',allCards=libraryCards(),cards=allCards.filter(card=>state.libraryCharacterFilter==='all'||card.status!=='archived'),archived=allCards.filter(card=>card.status==='archived'),canon=workCanon(),allCanonFacts=canon.facts||[],canonFacts=allCanonFacts.filter(item=>item.status!=='archived'),archivedCanonFacts=allCanonFacts.filter(item=>item.status==='archived'),world=worldBible(),files=state.work.reference_files||[],relations=relationRows(cards),official=cards.filter(card=>card.source_type==='official_reference').length,custom=cards.filter(card=>card.source_type==='custom').length,legacy=cards.filter(card=>!['official_reference','custom'].includes(card.source_type)).length,officialFiles=files.filter(file=>file.trust_status==='official_reference'),worldCards=(world.entities||[]).filter(item=>item.status!=='archived'),worldRules=(world.rules||[]).filter(item=>item.status!=='archived'),worldTimeline=projection?(projection.timeline?.events||[]):[],graphNodes=graphRecords(),graphEdges=graphLinks(),graphUnresolved=projection?.knowledge_graph?.unresolved_relationships||[],projectedStructure=projection?.story_structure||null;
  const nav=[['overview','资料总览',['overview']],['characters','角色卡',['characters']],['world','世界观',['world','rules','timeline']],['canon','作品事实',['canon']],['relations','关系图',['relations']],['files','证据资料',['files','official']]].map(([id,label,views])=>`<button class="library-nav-item ${views.includes(view)?'active':''}" data-library-view="${id}">${label}</button>`).join('');
  const worldSubnav=`<nav class="library-subnav" aria-label="世界库分类"><button class="${view==='world'?'active':''}" data-library-view="world">设定卡</button><button class="${view==='rules'?'active':''}" data-library-view="rules">世界规则</button><button class="${view==='timeline'?'active':''}" data-library-view="timeline">时间线</button></nav>`;
  const sourceSubnav=`<nav class="library-subnav" aria-label="证据资料分类"><button class="${view==='files'?'active':''}" data-library-view="files">已存资料</button><button class="${view==='official'?'active':''}" data-library-view="official">检索 BA 原作</button></nav>`;
  let body='';
  if(view==='overview'){const pendingWorld=unconfirmedWorldCards(world),nextWorld=pendingWorld[0],nextCharacter=cards.find(card=>card.trust_status!=='confirmed');body=`<section class="library-brief"><div><p class="eyebrow">CREATIVE BIBLE</p><h3>这里是作品的设定控制台</h3><p>人物、BA 世界观、本作私设、长期事实和证据分开管理。每项都有来源、确认状态和修订历史；只有已确认条目会进入下一场的受控 Agent。</p></div><div class="library-metrics"><b>${cards.length}<small>人物卡</small></b><b>${worldCards.length}<small>世界设定</small></b><b>${canonFacts.length}<small>作品事实</small></b><b>${graphEdges.length}<small>已登记关系</small></b></div></section><section class="library-control-deck"><div class="library-control-copy"><p class="eyebrow">NEXT DECISION</p><h3>${nextWorld?`先确认「${esc(nextWorld.name)}」在本作中的定义`:nextCharacter?`补齐「${esc(nextCharacter.name)}」的人物边界`:'资料库已具备可写基础'}</h3><p>${nextWorld?'BA 起始卡只是可编辑目录，不会冒充官方设定。打开后补充本作定义、证据和角色关联，再决定是否让它进入 Agent。':nextCharacter?'人物卡必须明确声音、知情范围和 OOC 红线；确认后才会成为可选的场景上下文。':'现在可以检查知识图和场景上下文，决定哪些已确认资料给下一场使用。'}</p><div class="actions">${nextWorld?`<button class="primary" data-edit-world-entry="entity:${esc(nextWorld.id)}">打开待核对世界卡</button><button class="quiet" data-library-view="official">检索 BA 原作证据</button>`:nextCharacter?`<button class="primary" data-library-view="characters">管理人物卡</button><button class="quiet" data-library-view="relations">检查关系图</button>`:`<button class="primary" data-library-view="relations">打开关系图</button><button class="quiet" data-stage-jump="draft">配置场景上下文</button>`}</div></div><ol class="library-decision-queue"><li><span>${pendingWorld.length}</span><div><b>待核对世界卡</b><small>确认来源与本作采用范围</small></div><button class="quiet" data-library-view="world">处理</button></li><li><span>${cards.filter(card=>card.trust_status!=='confirmed').length}</span><div><b>待核对人物卡</b><small>补齐声音、边界与关系</small></div><button class="quiet" data-library-view="characters">处理</button></li><li><span>${graphNodes.filter(node=>!graphEdges.some(edge=>edge.from===node.id||edge.to===node.id)).length}</span><div><b>尚未连线的条目</b><small>在关系图检查孤立设定</small></div><button class="quiet" data-library-view="relations">查看</button></li></ol></section><section class="library-summary-grid"><button class="library-summary" data-library-view="characters"><span>人物库</span><b>${official} 张原作参考 · ${custom} 张自定义</b><small>${cards.filter(card=>card.trust_status!=='confirmed').length} 张尚未确认；可管理人格、声音、边界与关系。</small></button><button class="library-summary" data-library-view="world"><span>世界库</span><b>${worldCards.length} 张设定卡 · ${worldRules.length} 条规则</b><small>${pendingWorld.length} 张待核对；BA 底稿与本作私设可以并存。</small></button><button class="library-summary" data-library-view="canon"><span>作品事实</span><b>${canonFacts.filter(fact=>fact.confidence_status==='confirmed').length} 条可用于写作 · ${canonFacts.filter(fact=>fact.confidence_status!=='confirmed').length} 条待确认</b><small>记录本作已经发生或明确成立的长期事实，不与世界设定混在一起。</small></button><button class="library-summary" data-library-view="relations"><span>关系图</span><b>${graphNodes.length} 个节点 · ${graphEdges.length} 条明确关系</b><small>查看人物如何连接到世界设定、规则和事件；所有连线都可回到来源编辑。</small></button></section>`;}
  if(view==='canon'){const factRow=fact=>`<div class="world-rule canon-fact ${fact.status==='archived'?'archived':''}"><span class="confidence ${esc(fact.confidence_status)}">${fact.status==='archived'?'已归档':confidenceLabel(fact.confidence_status)}</span><div><b>${esc(fact.text)}</b><small>${esc(fact.source)} · ${fact.scope==='scene'?'场景':fact.scope==='chapter'?'章节':'作品'}范围</small></div><div class="entry-actions"><button class="quiet" type="button" data-edit-canon-fact="${esc(fact.id)}">${fact.status==='archived'?'查看':'编辑'}</button></div></div>`;const archivedMarkup=archivedCanonFacts.length?`<details class="library-archived-facts"><summary>已归档（${archivedCanonFacts.length}）</summary><p>归档事实不会进入新的场景上下文；打开后可以恢复为新的正式修订。</p>${archivedCanonFacts.map(factRow).join('')}</details>`:'';body=`<section class="library-page-head"><div><h3>作品事实</h3><p>只保存这部作品已经明确成立、推断中或待决定的长期事实。保存新修订不会覆盖历史；只有“已确认”条目会进入场景上下文。</p></div><span class="source-pill">${canonFacts.length} 条当前事实 · ${canonFacts.filter(fact=>fact.confidence_status==='confirmed').length} 条可用于写作</span></section><div class="world-layout"><section class="world-rules">${canonFacts.length?canonFacts.map(factRow).join(''):'<div class="library-empty">还没有作品事实。可以登记已经明确成立的事件、身份、状态或不可变约束。</div>'}${archivedMarkup}</section><section class="library-editor"><p class="eyebrow">${state.editCanonFactId?'EDIT FACT':'WORK CANON'}</p><h3>${state.editCanonFactId?'修订作品事实':'新增作品事实'}</h3><form id="workCanonForm"><label>事实内容<textarea name="text" required placeholder="例如：旧机器当前没有接通外部电源。"></textarea></label><label>来源或证据<input name="source" required placeholder="用户确认 / 正文修订 / official-corpus://..."></label><label>可信状态<select name="confidence_status"><option value="confirmed">已确认，可用于写作</option><option value="inferred">推断，等待确认</option><option value="open">尚未决定</option><option value="conflict">存在冲突</option></select></label><label>作用范围<select name="scope"><option value="work">整部作品</option><option value="chapter">当前章节</option><option value="scene">当前场景</option></select></label><div class="actions"><button class="primary" type="submit">${state.editCanonFactId?'保存新修订':'保存作品事实'}</button><button class="quiet" type="button" data-canon-history>${state.canonHistoryOpen?'收起修订历史':'查看修订历史'}</button></div></form></section></div>`;}
  if(view==='characters'){
    const visibleCards=cards.filter(card=>(state.librarySourceFilter==='all'||card.source_type===state.librarySourceFilter)&&matchesTrust(card.trust_status,state.libraryStatusFilter)&&includesSearch([card.name,card.canonical_name,card.role,...(card.voice_anchors||[]),...(card.source_refs||[])],state.libraryQuery));
    body=`<section class="library-page-head"><div><h3>人物库</h3><p>原作人物和自定义人物分别管理。先搜索或筛选已有卡；右侧可以新建、修订，原作卡也可复制为本作自定义版本。</p></div><div class="source-count"><span>全部 ${allCards.filter(card=>card.status!=='archived').length}</span><span>原作 ${official}</span><span>自定义 ${custom}</span><span>待核对 ${cards.filter(card=>card.trust_status!=='confirmed').length}</span></div></section>${libraryToolbar({query:state.libraryQuery,queryName:'character_query',placeholder:'搜索名称、别名、职责或来源',filters:[{label:'来源',key:'librarySourceFilter',value:state.librarySourceFilter,options:[{value:'all',label:'全部来源'},{value:'official_reference',label:'原作参考'},{value:'custom',label:'自定义'}]},{label:'状态',key:'libraryStatusFilter',value:state.libraryStatusFilter,options:[{value:'all',label:'全部状态'},{value:'confirmed',label:'可用于写作'},{value:'pending',label:'待核对'}]},{label:'范围',key:'libraryCharacterFilter',value:state.libraryCharacterFilter,options:[{value:'active',label:'当前使用'},{value:'all',label:'含已归档'}]}]})}<div class="asset-primary-actions"><span>找到 ${visibleCards.length} 张人物卡</span><details class="library-add-menu"><summary>添加人物</summary><div><button type="button" data-import-character>从文件导入</button><button type="button" data-library-view="official">从 BA 原作检索</button><button type="button" data-library-new-card>新建自定义人物</button></div></details></div><div class="character-library"><section class="character-list">${visibleCards.length?visibleCards.map(card=>`<button class="character-record ${card.status==='archived'?'archived':''} ${card.id===state.editCardId?'active':''} ${card.id===state.highlightCardId?'recent':''}" data-edit-card="${esc(card.id)}"><span class="avatar-token">${esc(card.name.slice(0,1))}</span><span><b>${esc(card.name)}</b><small>${libraryKindLabel(card.source_type)} · ${trustLabel(card.trust_status)}</small></span><em>${esc((card.voice_anchors||[])[0]||'待补充声音')}</em></button>`).join(''):'<div class="library-empty"><b>没有符合条件的人物卡</b><span>调整搜索或筛选，或者建立一张新的自定义人物卡。</span></div>'}</section><section class="library-editor"><p class="eyebrow">${state.editCardId?'EDIT CARD':'NEW CARD'}</p><h3>${state.editCardId?`修订「${esc(state.editCard?.name||'人物')}」`:'新建自定义人物'}</h3><p class="editor-guidance">${state.editCardId?'保存会创建新修订；场景上下文仍固定原来的版本，直到下次重新装配。':'先写清角色在本作中的职责、说话方式、知情边界和不能做的事。'}</p><form id="libraryCharacterForm"><input type="hidden" name="card_id" value="${esc(state.editCardId||'')}"><label>来源类型<select name="source_type"><option value="custom" ${state.editCard?.source_type!=='official_reference'?'selected':''}>自定义设定</option><option value="official_reference" ${state.editCard?.source_type==='official_reference'?'selected':''}>原作参考</option></select></label><label>采用状态<select name="trust_status"><option value="confirmed" ${state.editCard?.trust_status==='confirmed'?'selected':''}>已确认，可用于写作</option><option value="open" ${state.editCard?.trust_status!=='confirmed'?'selected':''}>待核对，不进入 Agent</option></select></label><label>显示名称<input name="name" value="${esc(state.editCard?.name||state.prefillCharacter||'')}" required placeholder="例如：爱丽丝 / 原创角色名"></label><label>标准名称或别名<input name="canonical_name" value="${esc(state.editCard?.canonical_name||'')}" placeholder="用于检索和别名统一"></label><label>故事职责<textarea name="role" placeholder="她在这部作品中要推动什么？">${esc(state.editCard?.role||'')}</textarea></label><label>声音锚点<textarea name="voice" placeholder="短句、行动优先；遇到谜题会游戏化命名。">${esc((state.editCard?.voice_anchors||[]).join('\n'))}</textarea></label><label>知情边界<textarea name="boundary" placeholder="此时知道什么，绝对不知道什么。">${esc(state.editCard?.knowledge_boundary||'')}</textarea></label><label>OOC 红线<textarea name="ooc" placeholder="每行一条，例如：不替别人解释隐藏动机。">${esc((state.editCard?.ooc_constraints||[]).join('\n'))}</textarea></label><label>关系（每行：对象 | 关系 | 当前说明）<textarea name="relationships" placeholder="凯伊 | 队友 | 本场互相试探，但仍共同调查。">${esc((state.editCard?.relationships||[]).map(item=>`${item.target} | ${item.kind} | ${item.summary}`).join('\n'))}</textarea></label><label>来源或证据<input name="source" value="${esc((state.editCard?.source_refs||[]).join('；'))}" required placeholder="官方剧情索引 / 用户确认 / 本作设定文档"></label><div class="actions"><button class="primary" type="submit">${state.editCardId?'保存新修订':'建立人物卡'}</button>${state.editCardId&&state.editCard?.source_type==='official_reference'?'<button class="quiet" type="button" data-duplicate-card>复制为自定义</button>':''}<button class="quiet" type="button" data-library-new-card>${state.editCardId?'取消编辑':'清空表单'}</button></div></form></section></div>`;
  }
  if(view==='world'){
    const editing=state.editWorldEntry?.type==='entity',editCard=editing?worldCards.find(card=>card.id===state.editWorldEntry.id):null,starterPresent=worldCards.some(card=>card.id==='ba-starter-kivotos'),starterCount=worldCards.filter(card=>card.source_type==='ba_starter').length;
    const visibleWorldCards=worldCards.filter(card=>(state.worldKindFilter==='all'||card.kind===state.worldKindFilter)&&(state.worldSourceFilter==='all'||card.source_type===state.worldSourceFilter)&&matchesTrust(card.confidence_status,state.worldStatusFilter)&&includesSearch([card.name,card.summary,...(card.aliases||[]),card.source,...(card.participants||[])],state.worldQuery));
    body=`<section class="library-page-head"><div><h3>世界库</h3><p>管理 BA 世界底稿和本作自定义地点、学院、组织、物件与技术。搜索已有设定，确认采用范围，或创建新的世界观卡。</p></div><div class="source-count"><span>全部 ${worldCards.length}</span><span>BA 底稿 ${starterCount}</span><span>自定义 ${worldCards.filter(card=>card.source_type==='custom').length}</span><span>可用于写作 ${worldCards.filter(card=>card.confidence_status==='confirmed').length}</span></div></section>${libraryToolbar({query:state.worldQuery,queryName:'world_query',placeholder:'搜索名称、别名、定义、来源或关联角色',filters:[{label:'类型',key:'worldKindFilter',value:state.worldKindFilter,options:[{value:'all',label:'全部类型'},{value:'academy',label:'学院'},{value:'place',label:'地点'},{value:'organization',label:'组织'},{value:'object',label:'物件'},{value:'technology',label:'技术'},{value:'custom',label:'本作原创'}]},{label:'来源',key:'worldSourceFilter',value:state.worldSourceFilter,options:[{value:'all',label:'全部来源'},{value:'ba_starter',label:'BA 起始架构'},{value:'official_reference',label:'原作参考'},{value:'custom',label:'自定义'},{value:'mixed',label:'混合'}]},{label:'状态',key:'worldStatusFilter',value:state.worldStatusFilter,options:[{value:'all',label:'全部状态'},{value:'confirmed',label:'可用于写作'},{value:'pending',label:'待核对'}]}]})}<section class="world-onboarding"><div><p class="eyebrow">BA WORLD STARTER</p><h4>${starterPresent?'BA 世界观底稿已加入':'以 BA 世界观作为底稿'}</h4><p>${starterPresent?`当前有 ${starterCount} 张 BA 起始卡。它们是待核对的编辑入口，不是已确认的官方事实；逐项打开后补齐本作定义与来源。`:'一次复制一组可编辑的 BA 设定入口：基沃托斯、夏莱、联邦学生会、光环、社团与主要学院。'}</p>${starterPresent?'':`<div class="actions"><button class="primary" data-apply-ba-starter>加入 BA 世界观底稿</button><button class="quiet" data-library-view="official">先检索原作资料</button></div>`}</div><div><p class="eyebrow">CUSTOM WORLD</p><h4>自定义世界与 BA 可以并存</h4><p>私设学院、原创组织、改写地点和技术规则都能单独保存来源与确认状态，不会覆盖 BA 底稿。</p><div class="actions"><button class="primary" data-new-world-card>新建自定义设定</button></div></div></section><div class="asset-primary-actions"><span>找到 ${visibleWorldCards.length} 张世界观卡</span><div><button class="quiet" data-library-view="official">从 BA 原作建立</button><button class="primary" data-new-world-card>新建世界观卡</button></div></div><div class="world-layout"><section class="world-rules">${visibleWorldCards.length?visibleWorldCards.map(card=>`<div class="world-rule world-entity ${card.confidence_status==='open'?'pending':''} ${card.id===state.editWorldEntry?.id?'active':''}"><span class="confidence ${esc(card.confidence_status)}">${worldKindLabel(card.kind)}</span><div><b>${esc(card.name)}</b><p>${esc(card.summary||'尚未补充本作定义')}</p><small>${libraryKindLabel(card.source_type)} · ${confidenceLabel(card.confidence_status)}${card.participants?.length?` · 关联：${esc(card.participants.join('、'))}`:''}</small></div><div class="entry-actions">${card.confidence_status!=='confirmed'?`<button class="quiet" type="button" data-confirm-world-card="${esc(card.id)}">确认采用</button>`:''}<button class="quiet" type="button" data-edit-world-entry="entity:${esc(card.id)}">打开</button></div></div>`).join(''):'<div class="library-empty"><b>没有符合条件的世界观卡</b><span>调整搜索或筛选，也可以直接建立一张自定义设定卡。</span></div>'}</section><section class="library-editor"><p class="eyebrow">${editing?'EDIT WORLD CARD':'WORLD CARD'}</p><h3>${editing?`修订「${esc(editCard?.name||'世界观卡')}」`:'新增世界观卡'}</h3><p class="editor-guidance">${editing?'保存会创建整个 WorldBible 的新修订，并保留这张卡的稳定 ID。':'写清它在本作里是什么、有什么限制、依据来自哪里。'}</p><form id="worldEntityForm"><label>类型<select name="kind"><option value="place" ${editCard?.kind==='place'?'selected':''}>地点</option><option value="academy" ${editCard?.kind==='academy'?'selected':''}>学院</option><option value="organization" ${editCard?.kind==='organization'?'selected':''}>组织</option><option value="object" ${editCard?.kind==='object'?'selected':''}>物件</option><option value="technology" ${editCard?.kind==='technology'?'selected':''}>技术</option><option value="custom" ${editCard?.kind==='custom'?'selected':''}>本作原创</option></select></label><label>来源类型<select name="source_type"><option value="custom" ${editCard?.source_type==='custom'||!editCard?'selected':''}>自定义设定</option><option value="official_reference" ${editCard?.source_type==='official_reference'?'selected':''}>原作参考</option><option value="mixed" ${editCard?.source_type==='mixed'?'selected':''}>两者混合</option><option value="ba_starter" ${editCard?.source_type==='ba_starter'?'selected':''}>BA 起始架构</option></select></label><label>名称<input name="name" required value="${esc(editCard?.name||state.worldCardDraft?.name||'')}" placeholder="例如：夏莱 / 游戏开发部活动室"></label><label>本作定义与限制<textarea name="summary" placeholder="它在本作里是什么，能做什么，限制是什么？">${esc(editCard?.summary||state.worldCardDraft?.summary||'')}</textarea></label><label>别名<input name="aliases" value="${esc((editCard?.aliases||state.worldCardDraft?.aliases||[]).join('、'))}" placeholder="别名用顿号或逗号分隔"></label><label>来源或证据<input name="source" required value="${esc(editCard?.source||state.worldCardDraft?.source||'')}" placeholder="official-corpus://... / 用户确认"></label><label>可信状态<select name="confidence_status"><option value="confirmed" ${editCard?.confidence_status==='confirmed'?'selected':''}>已确认，可用于写作</option><option value="inferred" ${editCard?.confidence_status==='inferred'?'selected':''}>推断</option><option value="open" ${(editCard?.confidence_status||state.worldCardDraft?.confidence_status||'open')==='open'?'selected':''}>待决定，不进入 Agent</option></select></label><label>关联角色<input name="participants" value="${esc((editCard?.participants||state.worldCardDraft?.participants||[]).join('、'))}" placeholder="未建人物卡时可手动填写；已建人物在下方勾选"></label><div class="actions"><button class="primary" type="submit">${editing?'保存新修订':'保存世界观卡'}</button>${editing?`<button class="quiet" type="button" data-world-history>查看历史</button><button class="quiet" type="button" data-new-world-card>取消编辑</button><button class="danger" type="button" data-archive-world-entry="entity:${esc(editCard.id)}" ${editCard.status==='archived'?'disabled':''}>归档条目</button>`:''}</div></form></section></div>`
  }
  if(view==='rules')body=`<section class="library-page-head"><div><h3>世界规则</h3><p>规则表达“在这部作品里什么成立”，而世界观卡表达“有哪些人、地点、组织与物件”。只有已确认规则会进入场景上下文。</p></div><span class="source-pill">${worldRules.length} 条当前规则</span></section><div class="world-layout"><section class="world-rules">${worldRules.length?worldRules.map(rule=>`<div class="world-rule"><span class="confidence ${esc(rule.confidence_status)}">${confidenceLabel(rule.confidence_status)}</span><div><b>${esc(rule.text)}</b><small>${esc(worldRuleScopeLabel(rule.scope))} · ${esc(worldRuleCategoryLabel(rule.category))} · ${esc(rule.source)}${rule.participants?.length?` · 关联：${esc(rule.participants.join('、'))}`:''}</small></div></div>`).join(''):'<div class="library-empty">还没有规则。建立空间、技术、组织或本作改写边界。</div>'}</section><section class="library-editor"><p class="eyebrow">WORLD RULE</p><h3>新增或修订规则</h3><form id="worldBibleForm"><label>世界观来源<select name="source_type"><option value="custom" ${world.source_type==='custom'?'selected':''}>自定义设定</option><option value="official_reference" ${world.source_type==='official_reference'?'selected':''}>原作参考</option><option value="mixed" ${world.source_type==='mixed'?'selected':''}>两者混合</option></select></label><label>世界观标题<input name="title" value="${esc(world.title)}"></label><label>新增规则<textarea name="rule_text" placeholder="例如：本作的旧游戏机只能在零点后收到匿名指令。"></textarea></label><label>规则分类<input name="rule_category" placeholder="技术 / 组织 / 地点 / 本作改写"></label><label>规则来源<input name="rule_source" placeholder="用户确认 / 官方剧情索引 / 已登记资料"></label><label>可信状态<select name="rule_status"><option value="confirmed">已确认</option><option value="inferred">推断</option><option value="open">待决定</option></select></label><label>关联角色<input name="rule_participants" placeholder="爱丽丝、凯伊；会显示在关系图"></label><div class="actions"><button class="primary" type="submit">保存规则修订</button></div></form></section></div>`;
  if(view==='relations'){
    const typeNodes=state.graphTypeFilter==='all'?graphNodes:graphNodes.filter(node=>node.type===state.graphTypeFilter),focusId=typeNodes.some(node=>node.id===state.graphFocus)?state.graphFocus:'',visibleNodes=focusId?new Set([focusId,...graphEdges.filter(link=>link.from===focusId||link.to===focusId).flatMap(link=>[link.from,link.to])]):new Set(typeNodes.map(node=>node.id)),focusedNode=graphNodes.find(node=>node.id===focusId),focusedEdges=focusId?graphEdges.filter(link=>link.from===focusId||link.to===focusId):graphEdges.filter(link=>visibleNodes.has(link.from)&&visibleNodes.has(link.to)),visibleGraphNodes=graphNodes.filter(node=>visibleNodes.has(node.id));
    const openSource=focusedNode?`<button class="primary" data-open-graph-source="${esc(focusedNode.id)}">打开来源编辑</button>`:'';
    body=`<section class="library-page-head"><div><h3>作品知识图</h3><p>用来检查人物、世界设定、规则和事件有没有真实连接。这里只显示当前正式修订中的关系，不让模型猜测；点击节点聚焦，随后可直接打开来源编辑。</p></div><span class="source-pill">${graphNodes.length} 个节点 · ${graphEdges.length} 条明确关系</span></section><div class="graph-toolbar"><div class="segmented-control" aria-label="图谱类型"><button class="${state.graphTypeFilter==='all'?'active':''}" data-graph-type="all">全部</button><button class="${state.graphTypeFilter==='character'?'active':''}" data-graph-type="character">人物</button><button class="${state.graphTypeFilter==='entity'?'active':''}" data-graph-type="entity">世界观</button><button class="${state.graphTypeFilter==='rule'?'active':''}" data-graph-type="rule">规则</button><button class="${state.graphTypeFilter==='event'?'active':''}" data-graph-type="event">时间线</button><button class="${state.graphTypeFilter==='fact'?'active':''}" data-graph-type="fact">事实</button></div>${focusId?`<div class="graph-focus-actions"><span>已选：<b>${esc(focusedNode.label)}</b></span>${openSource}<button class="quiet" data-clear-graph-focus>返回全图</button></div>`:''}</div><section class="knowledge-map">${graphNodes.length?`<div class="knowledge-map-key"><span class="key-character">人物</span><span class="key-entity">世界观卡</span><span class="key-rule">世界规则</span><span class="key-event">时间线与事实</span></div>${focusId?`<div class="graph-focus-note"><b>正在查看：${esc(focusedNode.label)}</b><span>${focusedEdges.length?`关联 ${focusedEdges.length} 条已保存关系`:'该节点还没有与其他资料建立关系'}</span></div>`:''}<div class="knowledge-canvas"><div class="knowledge-branch character-branch"><p>人物</p>${visibleGraphNodes.filter(node=>node.type==='character').map(node=>`<button class="knowledge-node ${node.type} ${focusId===node.id?'active':''}" data-graph-node="${esc(node.id)}"><span>${esc(node.label.slice(0,1))}</span><b>${esc(node.label)}</b><small>${esc(node.meta)}</small></button>`).join('')||'<span class="branch-empty">当前没有人物节点</span>'}</div><div class="knowledge-hub"><span>CURRENT WORK</span><b>${esc(state.work.title)}</b><small>${graphEdges.length} 条已保存关系</small></div><div class="knowledge-branch world-branch"><p>世界与剧情</p>${visibleGraphNodes.filter(node=>node.type!=='character').map(node=>`<button class="knowledge-node ${node.type} ${focusId===node.id?'active':''}" data-graph-node="${esc(node.id)}"><span>${node.type==='entity'?'设':node.type==='rule'?'规':node.type==='fact'?'实':'事'}</span><b>${esc(node.label)}</b><small>${esc(node.meta)}</small></button>`).join('')||'<span class="branch-empty">当前没有世界或剧情节点</span>'}</div></div><div class="knowledge-links"><h4>${focusId?'关联明细':'当前筛选下的明确关系'}</h4>${focusedEdges.length?focusedEdges.map(link=>`<button class="knowledge-link" data-graph-node="${esc(link.from)}"><b>${esc(graphNodes.find(node=>node.id===link.from)?.label||'')}</b><span>${esc(link.kind)}</span><b>${esc(graphNodes.find(node=>node.id===link.to)?.label||'')}</b><small>${esc(link.summary)}</small></button>`).join(''):'<div class="library-empty">当前没有明确关系。可以在下方登记人物关系，也可以编辑世界观卡，在“关联角色”里选择人物。</div>'}</div>`:'<div class="library-empty">先建立人物卡或世界观卡，知识图会从当前正式修订自动形成。</div>'}</section><section class="relation-compose"><div><p class="eyebrow">ADD A LINK</p><h4>登记人物关系</h4><p>关系会写入起始人物的人物卡新修订，并立刻成为可追溯连线。</p></div>${allCards.filter(card=>card.status!=='archived').length>1?`<form id="relationForm"><label>起始人物<select name="from_card_id">${allCards.filter(card=>card.status!=='archived').map(card=>`<option value="${esc(card.id)}">${esc(card.name)}</option>`).join('')}</select></label><label>关联人物<select name="to_card_id">${allCards.filter(card=>card.status!=='archived').map(card=>`<option value="${esc(card.id)}">${esc(card.name)}</option>`).join('')}</select></label><label>关系类型<input name="kind" required placeholder="例如：队友 / 对手 / 同社团"></label><label>当前说明<input name="summary" placeholder="这部作品当前阶段的关系状态"></label><div class="actions"><button class="primary" type="submit">保存关系</button></div></form>`:'<div class="relation-compose-empty">至少需要两张未归档人物卡，才能登记人物关系。</div>'}</section>`
  }
  if(view==='timeline')body=`<section class="library-page-head"><div><h3>时间线</h3><p>时间线只读取当前 WorldBible 修订，供连续性审查和场景上下文引用；来源损坏时不会回退旧版本。</p></div><span class="source-pill">${worldTimeline.length} 个当前事件</span></section><div class="timeline-layout"><section class="timeline-list">${worldTimeline.length?worldTimeline.map((item,index)=>`<div class="timeline-event"><span>${String(index+1).padStart(2,'0')}</span><div><b>${esc(item.text)}</b><small>${esc(item.category)} · ${esc(item.source||'当前世界观修订')} · ${confidenceLabel(item.confidence_status)}${item.participants?.length?` · 关联：${esc(item.participants.join('、'))}`:''}</small></div></div>`).join(''):'<div class="library-empty">没有可验证的当前时间线事件。可以在这里添加过去事件、当前剧情或未来伏笔。</div>'}</section><section class="library-editor"><p class="eyebrow">TIMELINE EVENT</p><h3>添加事件</h3><form id="timelineForm"><label>事件内容<textarea name="event_text" placeholder="例如：零点后，旧游戏机第一次向爱丽丝发出提示。" required></textarea></label><label>事件类型<input name="event_category" placeholder="过去事件 / 当前剧情 / 未来伏笔"></label><label>来源<input name="event_source" required placeholder="用户确认 / 原作剧情索引 / 已登记资料"></label><label>可信状态<select name="event_status"><option value="confirmed">已确认</option><option value="inferred">推断</option><option value="open">待决定</option></select></label><label>关联角色<input name="event_participants" placeholder="爱丽丝、凯伊；会显示在关系图"></label><div class="actions"><button class="primary" type="submit">加入时间线</button></div></form></section></div>`;
  if(view==='files')body=`<section class="library-page-head"><div><h3>证据资料</h3><p>资料文件是证据或创作依据，不会自动变成世界观事实。核对后再从人物库、世界库或作品事实中明确采用。</p></div><span class="source-pill">${files.length} 个文件 · ${officialFiles.length} 个原作摘录</span></section><div class="world-layout"><section class="world-rules">${files.length?files.map(file=>`<div class="world-rule"><span class="confidence ${esc(file.trust_status)}">${referenceTrustLabel(file.trust_status)}</span><div><b>${esc(file.title)}</b><small>${esc(file.kind)} · ${esc(file.source_label)} · v${file.version}</small></div></div>`).join(''):'<div class="library-empty">还没有资料文件。可以手动登记，也可以检索 BA 原作资料并导入摘录。</div>'}</section><section class="library-editor"><p class="eyebrow">REFERENCE FILE</p><h3>登记资料</h3><form id="libraryReferenceForm"><label>资料名称<input name="title" required placeholder="例如：游戏开发部设定摘录"></label><label>来源标签<input name="source_label" required placeholder="官方剧情索引 / 用户导入"></label><label>资料内容<textarea name="content" required placeholder="粘贴可追溯的摘录、作者设定或参考摘要。"></textarea></label><div class="actions"><button class="primary" type="submit">保存资料文件</button></div></form></section></div>`;
  if(view==='official')body=`<section class="library-page-head"><div><h3>BA 原作资料导入</h3><p>在本机只读官方演出语料库中检索。结果可以保留为资料证据，或带来源建立待确认的人物卡、世界观卡；不会直接改写作品事实。</p></div><span class="source-pill">只读语料 · ${officialFiles.length} 个已导入</span></section><section class="official-reference-workbench"><form id="officialReferenceSearchForm" class="official-search"><label>检索原作资料<input name="query" value="${esc(state.officialReferenceQuery)}" required minlength="2" placeholder="例如：爱丽丝、凯伊、基沃托斯、夏莱"></label><button class="primary" type="submit">检索</button></form>${state.officialReferenceSearched?`<p class="search-summary">${state.officialReferenceResults.length?`找到 ${state.officialReferenceResults.length} 条可用资料。先检查故事归属、说话者和中文摘录，再决定要建立哪种资料卡。`:'没有找到匹配资料。可以尝试角色名、故事标题、说话者或地点关键词。'}</p>${state.officialReferenceResults.map(item=>`<article class="official-record"><div><p class="eyebrow">${esc(item.record_uid)}</p><h4>${esc(item.character_name||'未标注角色')} <span>/${esc(item.story_title||'未标注故事')}</span></h4><p class="record-meta">${esc(item.story_category||'未标注类别')} · ${esc((item.speakers||[]).join('、')||'未标注说话者')} · ${esc(item.source_file||item.record_file)}</p><p class="record-excerpt">${esc(item.zh_cn||'该记录未提供官方中文文本；可先导入索引信息，再人工核对。')}</p></div><div class="official-record-actions"><button class="quiet" type="button" data-official-to-character="${esc(item.record_uid)}">建立人物卡草稿</button><button class="quiet" type="button" data-official-to-world="${esc(item.record_uid)}">建立世界观卡草稿</button><button class="quiet" type="button" data-import-official="${esc(item.record_uid)}">导入为资料</button></div></article>`).join('')}`:'<div class="library-empty">输入关键词开始检索。资料导入只在本作品目录创建副本，不会修改原作语料库。</div>'}</section>`;
  if(view==='relations'){
    const projectionState=!projectionReady?'<div class="notice">正在从当前正式修订重建关系、时间线与章节结构……</div>':projection.complete?'<div class="notice good">投影来自当前正式修订 · 已通过来源 Hash 校验</div>':`<div class="notice bad">${projection.unavailable_sources.length} 个正式来源无法验证；未使用旧修订替代。</div>`;
    const unresolvedState=graphUnresolved.length?`<div class="notice">${graphUnresolved.length} 条旧名称或缺失目标关系尚未解析，系统没有自动猜测连接。</div>`:'';
    const structureMarkup=projectedStructure?.status!=='not_available'?`<section class="structure-projection"><header><div><p class="eyebrow">CURRENT REVISION / STRUCTURE</p><h3>章节结构投影</h3></div><span class="source-pill">${esc(projectedStructure?.source_revision_id||'')}</span></header><div class="structure-projection-volumes">${(projectedStructure?.volumes||[]).map((volume,index)=>`<div><b>卷 ${String(index+1).padStart(2,'0')} · ${esc(volume.title||'未命名卷')}</b><span>${(volume.chapters||[]).length} 章 · ${(volume.chapters||[]).reduce((sum,chapter)=>sum+(chapter.scenes||[]).length,0)} 场</span>${(volume.chapters||[]).map(chapter=>`<small>${esc(chapter.title||'未命名章节')} · ${(chapter.scenes||[]).length} 场</small>`).join('')}</div>`).join('')}</div></section>`:'<section class="structure-projection empty"><b>章节结构投影尚未建立</b><span>下一次保存卷、章或场景结构时会建立正式结构修订。</span></section>';
    body=projectionState+unresolvedState+body+structureMarkup;
  }
  if(['world','rules','timeline'].includes(view))body=worldSubnav+body;
  if(['files','official'].includes(view))body=sourceSubnav+body;
  el.innerHTML=`<div class="library-workbench"><header class="library-header"><div><p class="eyebrow">WORK / CREATIVE BIBLE</p><h2>当前作品 · 创作资料</h2><p>角色卡、世界观、作品事实、关系和证据都绑定当前作品。AI 会从讨论与正文中提出维护候选；采纳前不会改写正式资料。</p></div>${view==='overview'?'':'<button class="quiet" data-library-view="overview">返回资料总览</button>'}</header><div class="library-scope-banner"><div><span>当前作品</span><b>${esc(state.work?.title||'未选择作品')}</b></div><div><span>AI 维护状态</span><small>候选进入 Proposal · 你只在需要时审核</small></div><span class="status-chip">作品范围</span></div><div class="library-layout"><nav class="library-nav" aria-label="当前作品资料分类">${nav}</nav><main class="library-main">${body}</main></div></div>`;
}

function splitLines(value){return String(value||'').split(/\r?\n/).map(item=>item.trim()).filter(Boolean)}
function parseRelationships(value,existing=[]){return splitLines(value).map(line=>{const [target,kind,summary]=line.split('|').map(item=>item.trim());if(!target)return null;const card=libraryCards().find(item=>[item.name,item.canonical_name,...(item.aliases||[])].includes(target)),previous=existing.find(item=>(card&&item.target_character_id===card.id)||item.target===target);return {id:previous?.id,target_character_id:card?.id||previous?.target_character_id||'',target:card?.name||target,kind:kind||'关系待定',summary:summary||'',status:'confirmed'}}).filter(Boolean)}
function splitParticipants(value){return String(value||'').split(/[、,，]/).map(item=>item.trim()).filter(Boolean)}
function participantCharacterIds(names){const wanted=new Set(names);return libraryCards().filter(card=>[card.name,card.canonical_name,...(card.aliases||[])].some(name=>wanted.has(name))).map(card=>card.id)}
function mergeSourceTypes(types){const values=new Set(types.filter(type=>['official_reference','custom','mixed','ba_starter'].includes(type)));if(values.has('mixed')||(values.has('official_reference')&&values.has('custom'))||(values.has('ba_starter')&&values.size>1))return'mixed';if(values.has('ba_starter'))return'ba_starter';return values.has('official_reference')?'official_reference':'custom'}
function nextWorldSourceType(current,entity,editing){const remaining=(current.entities||[]).filter(item=>!editing||item.id!==editing.id);const types=remaining.map(item=>item.source_type);if(current.rules?.length||current.timeline?.length||remaining.length)types.push(current.source_type);types.push(entity.source_type);return mergeSourceTypes(types)}
function storeWorldMutation({entity,rule,event,replaceEntity,replaceRule,replaceEvent}){const current=worldBible();let entities=[...(current.entities||[])],rules=[...(current.rules||[])],timeline=[...(current.timeline||[])];if(replaceEntity)entities=entities.map(item=>item.id===replaceEntity.id?replaceEntity:item);else if(entity)entities.push(entity);if(replaceRule)rules=rules.map(item=>item.id===replaceRule.id?replaceRule:item);else if(rule)rules.push(rule);if(replaceEvent)timeline=timeline.map(item=>item.id===replaceEvent.id?replaceEvent:item);else if(event)timeline.push(event);return {title:current.title||'作品世界观',source_type:current.source_type||'custom',entities,rules,timeline}}

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.openWorkSwitch!==undefined){event.preventDefault();event.stopImmediatePropagation();$('#workSwitchDialog')?.showModal();return}
  if(button.dataset.selectWork){event.preventDefault();event.stopImmediatePropagation();const selected=button.dataset.selectWork;if(selected===state.work?.id){$('#workSwitchDialog')?.close();return}(async()=>{try{state.work=await api('/works/'+selected);state.currentProjection=null;state.currentProjectionVersion=null;await refreshCurrentProjection();state.sceneId=scenes()[0]?.id||null;state.context=null;state.stage='overview';state.surface='works';state.mobileView='writing';$('#workSwitchDialog')?.close();toast(`已切换到《${state.work.title}》`);render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.agentCompleteCards!==undefined){event.preventDefault();event.stopImmediatePropagation();state.stage='references';state.mobileView='writing';state.libraryView='characters';state.editCardId='';state.editCard=null;state.prefillCharacter=button.closest('.inspector-body')?.querySelector('.notice.bad')?.textContent.match(/：(.+?) 尚无/)?.[1]?.split('、')[0]||'';render();setTimeout(()=>$('#libraryCharacterForm input[name="name"]')?.focus(),0);return}
  if(button.dataset.characterFilter){event.preventDefault();event.stopImmediatePropagation();state.libraryCharacterFilter=button.dataset.characterFilter;render();return}
  if(button.dataset.duplicateCard!==undefined){event.preventDefault();event.stopImmediatePropagation();const card=state.editCard;if(!card)return;state.characterCardDraft={...card,name:card.name,canonical_name:card.canonical_name,source_type:'custom',trust_status:'open',source_refs:[...(card.source_refs||[]),`基于「${card.name}」的原作参考创建` ]};state.libraryEditorOpen=true;state.editCardId='';state.editCard=null;state.historyCardId='';render();toast('已复制为自定义人物草稿；确认本作改写后再保存。');return}
  if(button.dataset.archiveCard){event.preventDefault();event.stopImmediatePropagation();const card=libraryCards().find(item=>item.id===button.dataset.archiveCard);requestArchiveConfirmation({title:`归档「${card?.name||'这张人物卡'}」？`,detail:'归档后，这张人物卡不会进入新的场景上下文；已有修订历史仍会保留，之后也可以恢复。',acceptLabel:'归档人物卡',opener:button,action:async()=>{try{const result=await api(`/works/${state.work.id}/character-cards/${button.dataset.archiveCard}/archive`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=result.work;state.libraryCharacterFilter='all';toast('人物卡已归档');render()}catch(error){toast(error.message,true)}}});return}
  if(button.dataset.restoreCard){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/character-cards/${button.dataset.restoreCard}/restore`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=result.work;state.libraryCharacterFilter='active';toast('人物卡已恢复，将在之后的场景上下文中按确认状态参与选择。');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.cardHistory){event.preventDefault();event.stopImmediatePropagation();state.historyCardId=state.historyCardId===button.dataset.cardHistory?'':button.dataset.cardHistory;render();return}
  if(button.dataset.worldHistory!==undefined){event.preventDefault();event.stopImmediatePropagation();state.worldHistoryOpen=!state.worldHistoryOpen;render();return}
  if(button.dataset.officialMore!==undefined){event.preventDefault();event.stopImmediatePropagation();state.officialReferenceLimit+=6;render();return}
  if(button.dataset.canonHistory!==undefined){event.preventDefault();event.stopImmediatePropagation();state.canonHistoryOpen=!state.canonHistoryOpen;render();return}
  if(button.dataset.editCanonFact){event.preventDefault();event.stopImmediatePropagation();state.editCanonFactId=button.dataset.editCanonFact;state.libraryEditorOpen=true;state.canonHistoryOpen=false;render();return}
  if(button.dataset.restoreCanonFact){event.preventDefault();event.stopImmediatePropagation();const fact=(workCanon().facts||[]).find(item=>item.id===button.dataset.restoreCanonFact);if(!fact)return;(async()=>{try{const current=workCanon(),facts=(current.facts||[]).map(item=>item.id===fact.id?{...item,status:'active'}:item);const result=await api(`/works/${state.work.id}/canon`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,facts})});state.work=result.work;state.editCanonFactId='';state.canonHistoryOpen=false;toast('作品事实已恢复，将按可信状态参与之后的场景上下文。');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.archiveCanonFact){event.preventDefault();event.stopImmediatePropagation();const fact=(workCanon().facts||[]).find(item=>item.id===button.dataset.archiveCanonFact);requestArchiveConfirmation({title:'归档这条作品事实？',detail:`「${fact?.text||'这条事实'}」归档后不会进入新的场景上下文；已有修订历史仍会保留，之后也可以恢复。`,acceptLabel:'归档作品事实',opener:button,action:async()=>{try{const current=workCanon(),facts=(current.facts||[]).map(item=>item.id===button.dataset.archiveCanonFact?{...item,status:'archived'}:item);const result=await api(`/works/${state.work.id}/canon`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,facts})});state.work=result.work;state.editCanonFactId='';toast('作品事实已归档');render()}catch(error){toast(error.message,true)}}});return}
  if(button.dataset.applyBaStarter!==undefined){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/world-bible:starter`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=result.work;state.libraryView='world';toast(result.disclosure);render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.confirmWorldCard){event.preventDefault();event.stopImmediatePropagation();const current=worldBible(),existing=(current.entities||[]).find(item=>item.id===button.dataset.confirmWorldCard);if(!existing)return;(async()=>{try{const confirmed={...existing,confidence_status:'confirmed'};const result=await api(`/works/${state.work.id}/world-bible`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,...worldCardPayload(current,confirmed)})});state.work=result.work;toast(`已确认「${existing.name}」可用于本作写作。`);render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.editWorldEntry){event.preventDefault();event.stopImmediatePropagation();const [type,id]=button.dataset.editWorldEntry.split(':');const current=worldBible(),items=type==='entity'?current.entities:type==='rule'?current.rules:current.timeline,entry=items?.find(item=>item.id===id);if(!entry)return;state.editWorldEntry={type,id};state.libraryEditorOpen=true;state.worldHistoryOpen=false;if(type==='entity'){render();const workspace=$('#workspace'),form=$('#worldEntityForm');if(workspace&&form){const top=form.closest('.library-editor')?.offsetTop||0;workspace.scrollTo({top:Math.max(0,top-24),behavior:'smooth'})}return}const form=type==='rule'?$('#worldBibleForm'):$('#timelineForm');if(!form)return;const prefix=type==='rule'?'rule':'event';form.elements[`${prefix}_text`].value=entry.text||'';form.elements[`${prefix}_category`].value=entry.category||'';form.elements[`${prefix}_source`].value=entry.source||'';form.elements[`${prefix}_status`].value=entry.confidence_status||'confirmed';let participants=form.querySelector(`[name="${prefix}_participants"]`);if(!participants){const label=document.createElement('label');label.className='entry-participants';label.textContent='参与角色（用顿号或逗号分隔）';participants=document.createElement('input');participants.name=`${prefix}_participants`;participants.placeholder='例如：爱丽丝、凯伊';label.append(participants);form.querySelector('.actions')?.before(label)}participants.value=(entry.participants||[]).join('、');let archive=form.querySelector('[data-archive-world-entry]');if(!archive){archive=document.createElement('button');archive.className='danger';archive.type='button';form.querySelector('.actions')?.append(archive)}archive.dataset.archiveWorldEntry=`${type}:${id}`;archive.textContent=entry.status==='archived'?'已归档':'归档条目';archive.disabled=entry.status==='archived';const workspace=$('#workspace');if(workspace){const top=form.closest('.library-editor')?.offsetTop||0;workspace.scrollTo({top:Math.max(0,top-24),behavior:'smooth'})}return}
  if(button.dataset.archiveWorldEntry){event.preventDefault();event.stopImmediatePropagation();const [type,id]=button.dataset.archiveWorldEntry.split(':');const current=worldBible(),items=type==='entity'?[...current.entities]:type==='rule'?[...current.rules]:[...current.timeline],entry=items.find(item=>item.id===id);if(!entry)return;(async()=>{try{const next={...entry,status:'archived'};const payload={expected_version:state.work.version,title:current.title,source_type:current.source_type,entities:type==='entity'?items.map(item=>item.id===id?next:item):current.entities||[],rules:type==='rule'?items.map(item=>item.id===id?next:item):current.rules,timeline:type==='event'?items.map(item=>item.id===id?next:item):current.timeline};const result=await api(`/works/${state.work.id}/world-bible`,{method:'POST',body:JSON.stringify(payload)});state.work=result.work;state.editWorldEntry=null;toast('条目已归档，历史仍会保留');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.officialToWorld){event.preventDefault();event.stopImmediatePropagation();const item=state.officialReferenceResults.find(entry=>entry.record_uid===button.dataset.officialToWorld);if(!item)return;state.worldCardDraft={kind:'custom',source_type:'official_reference',name:item.story_title||item.character_name||'待命名 BA 设定',summary:`基于原作资料 ${item.record_uid} 的待确认世界观卡草稿。请核对摘录上下文，并写明本作中采用的定义、限制或改写边界。原始说话者：${(item.speakers||[]).join('、')||'未标注'}。`,aliases:[],source:item.evidence_uri||`official-corpus:${item.record_uid}`,confidence_status:'open',participants:[]};state.libraryView='world';state.editWorldEntry=null;render();return}
  if(button.dataset.officialToCharacter){event.preventDefault();event.stopImmediatePropagation();const item=state.officialReferenceResults.find(entry=>entry.record_uid===button.dataset.officialToCharacter);if(!item)return;state.characterCardDraft={name:item.character_name||'',canonical_name:item.character_name||'',source_type:'official_reference',trust_status:'open',role:'',voice_anchors:[],knowledge_boundary:'',ooc_constraints:[],relationships:[],source_refs:[item.evidence_uri||`official-corpus:${item.record_uid}`]};state.libraryView='characters';state.editCardId='';state.editCard=null;state.historyCardId='';render();return}
  if(button.dataset.clearGraphFocus!==undefined){event.preventDefault();event.stopImmediatePropagation();state.graphFocus='';render();return}
  if(button.dataset.graphType){event.preventDefault();event.stopImmediatePropagation();state.graphTypeFilter=button.dataset.graphType;state.graphFocus='';render();return}
  if(button.dataset.graphNode){event.preventDefault();event.stopImmediatePropagation();state.graphFocus=button.dataset.graphNode;render();return}
  if(button.dataset.openGraphSource){event.preventDefault();event.stopImmediatePropagation();const [type,id]=button.dataset.openGraphSource.split(':');state.graphFocus='';if(type==='character'){state.libraryView='characters';state.editCardId=id;state.editCard=libraryCards().find(card=>card.id===id)||null;render();return}if(type==='fact'){state.libraryView='canon';state.editCanonFactId=id;render();return}state.libraryView=type==='entity'?'world':type==='rule'?'rules':'timeline';state.editWorldEntry={type:type==='event'?'event':type,id};render();if(type!=='entity')setTimeout(()=>document.querySelector(`[data-edit-world-entry="${type==='event'?'event':type}:${CSS.escape(id)}"]`)?.click(),0);return}
  if(button.dataset.importOfficial){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/official-references:import`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,record_uid:button.dataset.importOfficial})});state.work=result.work;toast('原作摘录已导入本作品资料库');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.libraryOpenEditor){event.preventDefault();event.stopImmediatePropagation();state.libraryEditorOpen=true;if(button.dataset.libraryOpenEditor==='canon'){state.editCanonFactId='';}if(button.dataset.libraryOpenEditor==='files'){state.libraryView='files';}if(button.dataset.libraryOpenEditor==='timeline'){state.libraryView='timeline';}render();setTimeout(()=>document.querySelector('.library-editor textarea, .library-editor input')?.focus(),0);return}
  if(button.dataset.libraryView){event.preventDefault();event.stopImmediatePropagation();state.libraryView=button.dataset.libraryView;state.libraryEditorOpen=false;state.editCardId='';state.editCard=null;state.characterCardDraft=null;state.editCanonFactId='';state.canonHistoryOpen=false;state.editWorldEntry=null;state.worldCardDraft=null;state.worldHistoryOpen=false;dismissToast();render();return}
  if(button.dataset.newWorldCard!==undefined){event.preventDefault();event.stopImmediatePropagation();const closing=Boolean(state.editWorldEntry||state.worldCardDraft||state.libraryEditorOpen);state.libraryView='world';state.editWorldEntry=null;state.worldCardDraft=closing?null:{};state.libraryEditorOpen=!closing;state.worldHistoryOpen=false;dismissToast();render();if(!closing)setTimeout(()=>$('#worldEntityForm input[name="name"]')?.focus(),0);return}
  if(button.dataset.libraryNewCard!==undefined){event.preventDefault();event.stopImmediatePropagation();const closing=Boolean(state.editCardId||state.characterCardDraft||state.libraryEditorOpen);state.editCardId='';state.editCard=null;state.characterCardDraft=closing?null:{};state.libraryEditorOpen=!closing;state.prefillCharacter='';dismissToast();render();if(!closing)setTimeout(()=>$('#libraryCharacterForm input[name="name"]')?.focus(),0);return}
  if(button.dataset.editCard){event.preventDefault();event.stopImmediatePropagation();state.libraryView='characters';state.characterCardDraft=null;state.editCardId=button.dataset.editCard;state.editCard=libraryCards().find(card=>card.id===button.dataset.editCard)||null;render();setTimeout(()=>$('#libraryCharacterForm input[name="name"]')?.focus(),0);return}
},true);
document.addEventListener('change',event=>{
  const select=event.target.closest('select[data-library-filter-key]');if(!select)return;
  const key=select.dataset.libraryFilterKey;
  if(!['librarySourceFilter','libraryStatusFilter','libraryCharacterFilter','worldKindFilter','worldSourceFilter','worldStatusFilter'].includes(key))return;
  state[key]=select.value;render();
},true);
document.addEventListener('input',event=>{
  const input=event.target;if(!input.matches('input[name="character_query"],input[name="world_query"]'))return;
  const key=input.name==='character_query'?'libraryQuery':'worldQuery';state[key]=input.value;
  clearTimeout(state.librarySearchTimer);state.librarySearchTimer=setTimeout(()=>{const cursor=state[key].length;render();const next=document.querySelector(`input[name="${input.name}"]`);next?.focus();next?.setSelectionRange(cursor,cursor)},140);
},true);
document.addEventListener('submit',async event=>{
  if(event.target.id==='sceneContractForm'){
    event.preventDefault();event.stopImmediatePropagation();
    const fields=new FormData(event.target),scene=selectedScene();
    try{
      const parseJsonField=(name,label,fallback)=>{const raw=String(fields.get(name)||'').trim();if(!raw)return fallback;try{return JSON.parse(raw)}catch{throw new Error(`${label}必须是有效 JSON`)}};
      const result=await api(`/works/${state.work.id}/scenes/${scene.id}/contract`,{method:'POST',body:JSON.stringify({
        expected_version:state.work.version,
        title:fields.get('title'),
        location:fields.get('location'),
        goal:fields.get('goal'),
        writing_mode:fields.get('writing_mode'),
        known_facts:splitLines(fields.get('known_facts')),
        forbidden_reveals:splitLines(fields.get('forbidden_reveals')),
        stop_boundary:fields.get('stop_boundary'),
        scene_type:fields.get('scene_type'),
        external_trigger:fields.get('external_trigger'),
        hidden_expectation:fields.get('hidden_expectation'),
        defense:fields.get('defense'),
        choice:fields.get('choice'),
        plot_delta:fields.get('plot_delta'),
        emotion_delta:fields.get('emotion_delta'),
        residue:fields.get('residue'),
        ending_payoff:fields.get('ending_payoff'),
        sensei_scene_function:fields.get('sensei_scene_function'),
        literary_voice_variant:fields.get('literary_voice_variant'),
        render_mode:fields.get('render_mode'),
        has_sensei:fields.get('has_sensei')==='on',
        information_ownership:parseJsonField('information_ownership','信息归属',{}),
        exchange_chain:parseJsonField('exchange_chain','话轮因果链',[]),
      })});
      state.work=result.work;state.context=null;state.sceneContractOpen=false;toast(result.superseded_proposal_ids?.length?'场景契约已更新，旧候选已替代。':'场景契约已更新，下一次生成会使用新边界。');render();
    }catch(error){toast(error.message,true)}
    return;
  }
  if(event.target.id==='sceneContextForm'){
    event.preventDefault();event.stopImmediatePropagation();
    const fields=new FormData(event.target),ids=name=>fields.getAll(name).map(value=>String(value));
    try{
      const scene=selectedScene();
      const result=await api(`/works/${state.work.id}/scenes/${scene.id}/context:configure`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,character_card_ids:ids('character_card_ids'),world_item_ids:ids('world_item_ids'),reference_file_ids:ids('reference_file_ids')})});
      state.work=result.work;state.context=null;state.sceneContextEditorOpen=false;state.inspector='context';toast('本场上下文已保存；下一次装配和生成将使用这个范围。');render();
    }catch(error){toast(error.message,true)}
    return;
  }
  const form=event.target;if(form.id==='relationForm'){
    event.preventDefault();event.stopImmediatePropagation();const fields=new FormData(form),fromId=String(fields.get('from_card_id')||''),toId=String(fields.get('to_card_id')||'');
    try{if(!fromId||!toId)throw new Error('请选择两张人物卡。');if(fromId===toId)throw new Error('关系两端需要是不同人物。');const from=libraryCards().find(card=>card.id===fromId),to=libraryCards().find(card=>card.id===toId);if(!from||!to)throw new Error('所选人物卡已不存在。');const kind=String(fields.get('kind')||'').trim(),summary=String(fields.get('summary')||'').trim();if(!kind)throw new Error('请填写关系类型。');const existing=(from.relationships||[]).filter(link=>link.target_character_id!==to.id&&link.target!==to.name);const result=await api(`/works/${state.work.id}/character-cards`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,card_id:from.id,name:from.name,canonical_name:from.canonical_name,aliases:from.aliases||[],source_type:from.source_type,role:from.role,voice_anchors:from.voice_anchors||[],knowledge_boundary:from.knowledge_boundary,ooc_constraints:from.ooc_constraints||[],relationships:[...existing,{target_character_id:to.id,target:to.name,kind,summary,status:'confirmed'}],source_refs:from.source_refs||[],trust_status:from.trust_status,ba_profile:from.ba_profile||null,profile_format:from.profile_format||'halocue-character-card/1.1',source_hash:from.source_hash||'',extractor_version:from.extractor_version||'halocue-runtime-character/1.1'})});state.work=result.work;toast(`${from.name} 与 ${to.name} 的关系已保存为人物卡新修订。`);render()}catch(error){toast(error.message,true)}
    return;
  }
  if(!['workCanonForm','libraryCharacterForm','worldEntityForm','worldBibleForm','timelineForm','libraryReferenceForm','officialReferenceSearchForm'].includes(form.id))return;
  event.preventDefault();event.stopImmediatePropagation();const fields=new FormData(form);
  try{
    if(form.id==='officialReferenceSearchForm'){const query=String(fields.get('query')||'').trim();const result=await officialReferenceSearch(query);state.officialReferenceQuery=query;state.officialReferenceResults=result.items||[];state.officialReferenceSearched=true;state.officialReferenceLimit=6;render();return}
    let path,payload,success,artifactId='';
    if(form.id==='workCanonForm'){
      const current=workCanon(),existing=(current.facts||[]).find(item=>item.id===state.editCanonFactId);const fact={...(existing||{}),id:existing?.id,text:String(fields.get('text')||'').trim(),source:String(fields.get('source')||'').trim(),confidence_status:fields.get('confidence_status'),scope:fields.get('scope'),status:existing?.status||'active'};const facts=existing?current.facts.map(item=>item.id===existing.id?fact:item):[...(current.facts||[]),fact];path=`/works/${state.work.id}/canon`;payload={expected_version:state.work.version,facts};artifactId=workCanonArtifact()?.id||'';success=existing?'作品事实已保存为新修订':'作品事实已登记';
    }else if(form.id==='libraryCharacterForm'){
      path=`/works/${state.work.id}/character-cards`;payload={expected_version:state.work.version,card_id:fields.get('card_id'),name:fields.get('name'),canonical_name:fields.get('canonical_name'),aliases:state.editCard?.aliases||[],source_type:fields.get('source_type'),role:fields.get('role'),voice_anchors:splitLines(fields.get('voice')),knowledge_boundary:fields.get('boundary'),ooc_constraints:splitLines(fields.get('ooc')),relationships:parseRelationships(fields.get('relationships'),state.editCard?.relationships||[]),source_refs:String(fields.get('source')).split(/[；;]/).map(item=>item.trim()).filter(Boolean),trust_status:fields.get('trust_status'),ba_profile:state.editCard?.ba_profile||null,profile_format:state.editCard?.profile_format||'halocue-character-card/1.1',source_hash:state.editCard?.source_hash||'',extractor_version:state.editCard?.extractor_version||'halocue-runtime-character/1.1'};artifactId=state.editCard?.artifactId||'';success=fields.get('trust_status')==='confirmed'?'人物卡已确认并保存为新修订':'人物卡草稿已保存，尚不会进入 Agent';
    }else if(form.id==='worldEntityForm'){
      const edit=state.editWorldEntry?.type==='entity'?state.editWorldEntry:null,current=worldBible(),existing=edit?(current.entities||[]).find(item=>item.id===edit.id):null;
      const selectedCharacterIds=fields.getAll('world_character_card_ids').map(String),selectedCharacterNames=selectedCharacterIds.map(id=>libraryCards().find(card=>card.id===id)?.name).filter(Boolean),manualParticipantNames=splitParticipants(fields.get('participants')),participants=[...new Set([...manualParticipantNames,...selectedCharacterNames])],participant_character_ids=[...new Set([...selectedCharacterIds,...participantCharacterIds(manualParticipantNames)])];
      const entity={...(existing||{}),id:existing?.id,name:String(fields.get('name')||'').trim(),kind:fields.get('kind'),summary:String(fields.get('summary')||'').trim(),aliases:splitParticipants(fields.get('aliases')),source:String(fields.get('source')||'').trim(),source_type:fields.get('source_type'),confidence_status:fields.get('confidence_status'),participants,participant_character_ids,related_world_ids:fields.getAll('related_world_ids').map(value=>String(value)),scope:existing?.scope||'work',status:existing?.status||'active'};
      path=`/works/${state.work.id}/world-bible`;payload={expected_version:state.work.version,...storeWorldMutation(edit?{replaceEntity:entity}:{entity}),title:current.title,source_type:nextWorldSourceType(current,entity,edit)};artifactId=state.work.artifacts?.find(item=>item.kind==='world_bible')?.id||'';success=edit?'世界观卡已保存为新修订':'世界观卡已保存为新修订';
    }else if(form.id==='worldBibleForm'){
      const text=String(fields.get('rule_text')).trim(),source=String(fields.get('rule_source')).trim();if((text&&!source)||(!text&&source))throw new Error('新增世界规则时，需要同时填写内容和来源。');
      const edit=state.editWorldEntry?.type==='rule'?state.editWorldEntry:null,current=worldBible(),existing=edit?(current.rules||[]).find(item=>item.id===edit.id):null,participants=splitParticipants(fields.get('rule_participants'));const rule=text?{...(existing||{}),id:existing?.id,text,category:fields.get('rule_category')||'general',source,confidence_status:fields.get('rule_status'),scope:existing?.scope||'work',participants,participant_character_ids:participantCharacterIds(participants),status:existing?.status||'active'}:null;
      path=`/works/${state.work.id}/world-bible`;payload={expected_version:state.work.version,...storeWorldMutation(edit?{replaceRule:rule}:{rule}),title:fields.get('title'),source_type:fields.get('source_type')};artifactId=state.work.artifacts?.find(item=>item.kind==='world_bible')?.id||'';success=edit?'世界规则已保存为新修订':'世界观已保存为新修订';
    }else if(form.id==='timelineForm'){
      const edit=state.editWorldEntry?.type==='event'?state.editWorldEntry:null,current=worldBible(),existing=edit?(current.timeline||[]).find(item=>item.id===edit.id):null,participants=splitParticipants(fields.get('event_participants'));const entry={...(existing||{}),id:existing?.id,text:fields.get('event_text'),category:fields.get('event_category')||'当前剧情',source:fields.get('event_source'),confidence_status:fields.get('event_status'),scope:existing?.scope||'work',participants,participant_character_ids:participantCharacterIds(participants),status:existing?.status||'active'};
      path=`/works/${state.work.id}/world-bible`;payload={expected_version:state.work.version,...storeWorldMutation(edit?{replaceEvent:entry}:{event:entry})};artifactId=state.work.artifacts?.find(item=>item.kind==='world_bible')?.id||'';success=edit?'时间线事件已保存为新修订':'事件已加入时间线';
    }else{
      path=`/works/${state.work.id}/reference-files`;payload={expected_version:state.work.version,title:fields.get('title'),source_label:fields.get('source_label'),content:fields.get('content'),trust_status:'unverified'};success='资料文件已登记';
    }
     const result=await saveLibraryMutation(path,payload,{artifactId});state.work=result.work;state.libraryEditorOpen=false;state.editCardId='';state.editCard=null;state.characterCardDraft=null;state.editCanonFactId='';state.canonHistoryOpen=false;state.editWorldEntry=null;state.worldCardDraft=null;state.worldHistoryOpen=false;state.prefillCharacter='';toast(success);render();
  }catch(error){toast(error.message,true)}
},true);

// Final UI overrides: later declarations in this legacy single-file client are
// intentionally superseded here so the view used by the browser stays coherent.
renderWorkflowGuide=function(){
  const guide=$('#workflowGuide');
  if(guide)guide.replaceChildren();
  if(!state.work)return;
  const progress=workflowProgress();
  const nextStage=FLOW_STAGES.find(stage=>!progress.done[stage])||'release';
  $$('[data-stage]').forEach(button=>{
    const stage=button.dataset.stage,gate=stageGate(stage),small=button.querySelector('small');
    const complete=Boolean(progress.done[stage]),current=stage===state.stage,next=stage===nextStage&&!complete;
    button.disabled=!gate.allowed;
    button.classList.toggle('is-complete',complete);
    button.classList.toggle('is-current',current);
    button.classList.toggle('is-next',next&&!current);
    button.setAttribute('aria-current',current?'step':'false');
    button.setAttribute('aria-disabled',String(!gate.allowed));
    button.title=gate.allowed?(complete?'已完成，可随时查看':'可进入此阶段'):gate.reason;
    if(small)small.textContent=complete?'已完成':current?'正在进行':gate.allowed?'可随时查看':'完成前一步后可继续';
  });
  $$('[data-section="production"]').forEach(production=>{
    production.classList.remove('locked-nav');
    production.removeAttribute('aria-disabled');
    production.title='打开 AA 制作工作台';
  });
};

renderBrief=function(el){
  const b=brief()||{},isSaved=Boolean(brief());
  el.innerHTML=frame('第 1 步 / 5','先把故事开头说清楚','这张写作想法只记录你此刻的创作意图。人物卡、世界观和正文仍在各自的资料与写作页面管理。',`<section class="brief-clarity-band"><div><p class="eyebrow">THIS STEP</p><h3>先回答三个问题，其他设定以后再补。</h3><p>故事要写什么、用什么写法、谁是主要角色。保存后才会解锁故事方向。</p></div><span class="brief-step-state ${isSaved?'is-saved':''}">${isSaved?'已保存，可继续':'等待填写'}</span></section><form id="briefForm" class="brief-form"><label class="brief-idea">一句想法<textarea name="idea" required placeholder="例如：凯伊发现游戏开发部的旧机器在深夜自行启动">${esc(b.idea)}</textarea><small>用一句话说清这部作品最想发生什么。</small></label><div class="brief-core-grid"><label>写作模式<select name="mode"><option value="bond_short" ${b.mode==='bond_short'?'selected':''}>羁绊短场景</option><option value="main_battle" ${b.mode==='main_battle'?'selected':''}>主线与战斗</option><option value="long_comedy" ${b.mode==='long_comedy'?'selected':''}>长篇喜剧</option><option value="text_reading" ${b.mode==='text_reading'?'selected':''}>小说化阅读</option></select></label><label>主要角色<input name="characters" value="${esc((b.characters||[]).join('、'))}" placeholder="爱丽丝、凯伊"><small>用顿号分隔；之后可到人物库完善卡片。</small></label></div><details class="brief-optional" ${b.target_length||b.constraints||b.has_sensei?'open':''}><summary>补充设定（可选）</summary><div class="brief-optional-fields"><label>目标长度<select name="target_length"><option value="short" ${b.target_length==='short'?'selected':''}>短场景</option><option value="chapter" ${b.target_length==='chapter'?'selected':''}>单章</option><option value="long" ${b.target_length==='long'?'selected':''}>长篇</option></select></label><label class="brief-constraint">额外约束<textarea name="constraints" placeholder="不可提前揭示的事实、希望保留的关系距离……">${esc(b.constraints)}</textarea></label><label class="check brief-check"><span><input type="checkbox" name="has_sensei" ${b.has_sensei?'checked':''}> 老师在场</span></label></div></details><div class="brief-actions"><div><b>${isSaved?'修改会新建一份写作想法修订':'保存后不会自动生成正文或改写资料库'}</b><small>${isSaved?'故事方向、章节和场景会继续引用这份简报。':'你仍可随时回到这里修改。'}</small></div><div class="actions"><button class="primary" type="submit">${isSaved?'保存修改':'保存写作想法'}</button>${isSaved?'<button class="quiet" type="button" data-stage-jump="blueprint">下一步：确认故事方向</button>':''}</div></div></form>`);
};

renderOverview=function(el){
  const work=state.work,sceneList=scenes(),total=sceneList.length,drafted=sceneList.filter(scene=>scene.current_revision_id).length,cards=libraryCards(),world=worldBible(),worldEntities=(world.entities||[]).filter(item=>item.status!=='archived'),pending=blockingPendingProposals().length,backgroundSuggestions=backgroundKnowledgeSuggestions().length,blocker=(work.review_findings||[]).filter(item=>item.status==='open'&&item.severity==='blocking').length;
  let next={stage:'brief',title:'先提供一句创作想法',detail:'只要说出想看什么；系统会在下一步提出角色、世界观依据和写作组成候选。',label:'开始写作想法'};
  if(brief()&&!blueprintIsConfirmed())next={stage:'blueprint',title:'审查故事方向候选',detail:'系统先提出角色、写作组成与世界观依据；确认后才会建立章节。',label:'审查故事方向'};
  else if(blueprintIsConfirmed()&&!work.chapters.length)next={stage:'structure',title:'建立章节与场景',detail:'先建立第一章，再把故事拆成有稳定身份的场景。',label:'建立章节与场景'};
  else if(pending)next={stage:'draft',title:'先审查待处理候选',detail:`有 ${pending} 份候选等待你采纳、局部修改或退回。`,label:'查看候选'};
  else if(blocker)next={stage:'draft',title:'处理审查阻塞项',detail:`有 ${blocker} 个阻塞项。处理完成后才可以冻结发布版本。`,label:'处理审查'};
  else if(total&&drafted<total)next={stage:'draft',title:'开始下一场写作',detail:`还有 ${total-drafted} 个场景没有已采纳正文，生成结果会先进入候选审查。`,label:'打开逐场写作'};
  else if(total)next={stage:'release',title:'运行全篇审查',detail:'确认连续性、人物约束和正文修订后，再冻结交给制作的定稿。',label:'检查并发布'};
  const customCards=cards.filter(card=>card.source_type==='custom').length;
  const confirmedWorld=worldEntities.filter(item=>item.confidence_status==='confirmed').length;
  const visibleChapters=work.chapters.filter(chapter=>chapter.scenes.length);
  const libraryReadiness=`<section class="overview-readiness" aria-label="创作资料库">
    <div class="overview-readiness-copy"><p class="eyebrow">CREATIVE LIBRARY</p><h3>创作资料已经独立保存</h3><p>人物、世界设定、作品事实和证据不会混进对话或正文。需要时再进入资料库补齐。</p></div>
    <div class="overview-readiness-actions">
      <button class="readiness-link" data-stage-jump="references" data-library-target="characters"><span>人物卡</span><b>${cards.length} 张${customCards?` · ${customCards} 张自定义`:''}</b><small>${cards.length?'查看角色声音、边界与关系':'添加第一张人物卡'}</small></button>
      <button class="readiness-link" data-stage-jump="references" data-library-target="world"><span>世界设定</span><b>${worldEntities.length} 项${confirmedWorld?` · ${confirmedWorld} 项已确认`:''}</b><small>${worldEntities.length?'查看 BA 底稿与本作私设':'建立世界设定'}</small></button>
    </div>
  </section>`;
  if(!total){
    el.innerHTML=`<div class="overview-workbench overview-start-workbench">
      <header class="overview-header overview-start-header"><div><p class="eyebrow">WORK / START HERE</p><h2>${esc(work.title)}</h2><p>先把这部作品要写什么说清楚。章节、正文和审查会在你确认方向后逐步出现。</p></div></header>
      <section class="overview-start-command"><div><p class="eyebrow">CURRENT DECISION</p><h3>${next.title}</h3><p>${next.detail}</p><button class="primary overview-primary" data-stage-jump="${next.stage}">${next.label}</button></div><ol class="overview-flow-preview" aria-label="写作流程预览"><li class="active"><span>01</span><b>写作想法</b><small>现在开始</small></li><li><span>02</span><b>故事方向</b><small>确认后解锁</small></li><li><span>03</span><b>章节与场景</b><small>方向确定后建立</small></li><li><span>04</span><b>逐场写作与发布</b><small>按场审查，再冻结定稿</small></li></ol></section>
      ${libraryReadiness}
    </div>`;
    return;
  }
  const progress=Math.round(drafted/total*100);
  el.innerHTML=`<div class="overview-workbench overview-progress-workbench">
     <header class="overview-header"><div><p class="eyebrow">WORK OVERVIEW</p><h2>${esc(work.title)}</h2><p>按一个明确的下一步推进；正文、候选和审查决定始终分开保存。</p></div><button class="quiet" data-stage-jump="references">打开创作资料</button></header>
    <section class="overview-next overview-next-calm"><div><p class="eyebrow">NEXT STEP</p><h3>${next.title}</h3><p>${next.detail}</p></div><button class="primary" data-stage-jump="${next.stage}">${next.label}</button></section>
    <div class="overview-progress-line"><b>正文进度 ${progress}%</b><span>${drafted} / ${total} 个场景已有已采纳正文</span>${pending||blocker?`<button class="text-link ${blocker?'has-attention':''}" data-stage-jump="draft">${pending+blocker} 项等待决定</button>`:''}</div>
    ${backgroundSuggestions?`<button class="overview-background-suggestion" data-stage-jump="references" data-library-target="suggestions"><span>Agent 在后台整理了 ${backgroundSuggestions} 条可能需要长期保留的事实</span><b>稍后审查</b></button>`:''}
    ${libraryReadiness}
    ${visibleChapters.length?`<section class="overview-structure-summary"><div class="overview-section-head"><h3>已有场景</h3><button class="quiet" data-stage-jump="structure">管理章节</button></div>${visibleChapters.map(chapter=>`<button class="overview-chapter" data-stage-jump="structure"><b>${esc(chapter.title)}</b><span>${chapter.scenes.length} 个场景</span><small>${chapter.scenes.filter(scene=>scene.current_revision_id).length} 已完成</small></button>`).join('')}</section>`:''}
  </div>`;
};

stageDecisionModel=function(){
  const scene=selectedScene(),proposal=pendingProposal(),latest=state.work?.releases?.[0];
  const definitions={overview:{kicker:'当前步骤',title:'按推荐下一步推进即可',body:'作品总览只保留一个推荐行动，其他入口仍在左侧导航。',impact:'不会自动生成、修改或发布任何内容。'},brief:{kicker:'第 1 步',title:brief()?'想法已保存，等待分析':'先提供一句想法',body:'先让系统理解你想看什么；角色、写作组成和老师是否出场会以候选呈现，不要求你预先猜测。',impact:'系统会保存你的想法，并提供故事方向候选。'},blueprint:{kicker:'第 2 步',title:blueprintIsConfirmed()?'故事方向已确认':blueprint()?'审查故事方向候选':'等待系统分析',body:blueprintIsConfirmed()?'确认过的角色卡、世界观依据和第一场规则包会成为后续结构的边界。':'检查系统建议，点选人物卡、保留或覆盖老师出场建议，并决定是否采用。',impact:blueprintIsConfirmed()?'现在可以建立章节与场景。':'未确认前不会建立章节或写入正文。'},structure:{kicker:'第 3 步',title:'建立章节与场景',body:'改标题或调整顺序不会丢失正文和资料引用。',impact:'保存结构后需要重新进行全篇审查。'},draft:{kicker:'第 4 步',title:proposal?'审查本场候选':scene?`推进「${scene.title}」`:'先建立一个场景',body:proposal?'候选可以局部修改；采纳前不会进入正文。':scene?'先准备本场资料，再生成候选或检查已有正文。':'回到章节安排，先建立场景。',impact:proposal?'采纳时才会建立新的正文版本。':'Agent 只能提交候选，不能静默修改正文或资料。'},references:{kicker:'创作资料',title:'当前作品的创作资料',body:'角色卡、世界观、事实、关系和证据都绑定当前作品。AI 会持续提出维护候选，只有采纳后才进入 Agent 上下文。',impact:'待审核内容不会冒充正式资料。'},release:{kicker:'第 5 步',title:latest?'确认交给制作的定稿':'先完成全篇审查',body:latest?'制作定稿不会随正文修改而改变；新稿需要创建新的发布版本。':'所有场景都有已采纳正文后，才能运行全篇审查与冻结。',impact:latest?'提交制作只交付当前定稿。':'全篇审查通过前，发布操作保持锁定。'}};
  return definitions[state.stage]||definitions.overview;
};

function sceneModeLabel(mode){return({bond_short:'羁绊与日常互动',main_battle:'主线冲突与行动',long_comedy:'轻松喜剧推进',text_reading:'小说化叙事阅读'})[mode]||'待决定'}
function sceneReadinessView(context,findingSpeakers=[]){
  const readiness=context?.readiness||{},cards=context?.runtime_character_cards||[];
  const missingCharacters=[...new Set([
    ...(readiness.missing_runtime_character_cards||[]),
    ...(findingSpeakers||[]),
  ].filter(Boolean))];
  const blockingReasons=(readiness.blocking_reasons||[]).filter(Boolean);
  const blockingMessages=blockingReasons.map(item=>typeof item==='string'?item:item?.message).filter(Boolean);
  const simulation=Boolean(state.capabilities?.providers?.[0]?.is_simulation);
  const simulationReady=simulation&&readiness.real_ba_writing==='ready_for_provider'&&cards.length>0&&readiness.skill_source!=='blocked';
  const canRun=(typeof readiness.can_run==='boolean'?readiness.can_run:false)||simulationReady;
  let label='写作条件未满足',detail='本场上下文仍缺少运行所需的确认资料。';
  if(canRun){
    label=simulation?'模拟流程已准备':'已准备，可提交任务';
    detail=simulation?'当前使用明确标注的模拟 Provider，只验证完整审阅流程。':'本场合同、前文承接和已确认资料已经固定。';
  }else if(!context){
    label='正在准备本场上下文';
    detail='系统会读取章节方向、前文和已确认资料。';
  }else if(cards.length===0){
    label='还缺少人物卡';
    detail=missingCharacters.length
      ?`还缺少已确认、可用于运行时的人物卡：${missingCharacters.join('、')}。`
      :'本场还没有已确认、可用于运行时的人物卡。';
  }else if(blockingMessages.length){
    detail=blockingMessages.join('；');
  }else if(readiness.reason){
    detail=readiness.reason;
  }
  return {canRun,simulation,label,detail,missingCharacters,blockingReasons,blockingMessages,needsCharacterCard:cards.length===0||missingCharacters.length>0};
}
function briefWorldFoundation(){
  const world=worldBible(),items=['entities','rules','timeline'].flatMap(key=>(world[key]||[]).filter(item=>item.status!=='archived'));
  const label=world.source_type==='ba_starter'?'BA 起始架构':world.source_type==='mixed'?'BA 起始架构 + 本作自定义设定':items.length?'本作自定义世界观':'尚未建立世界观基础';
  return {label,detail:items.length?`当前资料库有 ${items.length} 项设定，${items.filter(item=>item.confidence_status==='confirmed').length} 项已确认；未确认条目不会当作既定事实。`:'当前作品还没有世界观条目。可以先分析想法，确认方向后再补充原创设定。'};
}
function blueprintIsConfirmed(){const value=blueprint();return Boolean(value&&value.status!=='proposed')}

renderBrief=function(el){
  const b=brief()||{},foundation=briefWorldFoundation(),hasIdea=Boolean(b.idea);
  el.innerHTML=frame('第 1 步 / 5','先告诉系统你想看什么','这一页只收集创作意图。角色、写作重心、老师是否出场和世界观采用范围，都由系统先提出候选，再由你确认。',`<section class="brief-intent-band"><div><p class="eyebrow">YOUR INPUT</p><h3>一句想法就够了</h3><p>可以写一个画面、人物关系、事件或情绪。系统会把它整理成可审查的故事方向，不会直接开始写正文。</p></div><span class="brief-step-state ${hasIdea?'is-saved':''}">${hasIdea?'已有想法，可重新分析':'等待你的想法'}</span></section><form id="briefForm" class="brief-intent-form"><label class="brief-idea">我想看<textarea name="idea" required placeholder="例如：游戏开发部的旧机器在深夜自行启动，爱丽丝和凯伊必须在天亮前确认它留下的线索。">${esc(b.idea||'')}</textarea><small>不必填写角色译名、写作类型或技术约束；这些会在下一步以候选和卡片选择呈现。</small></label><section class="brief-world-foundation"><div><p class="eyebrow">CURRENT WORLD BASIS</p><h3>${esc(foundation.label)}</h3><p>${esc(foundation.detail)}</p></div><button type="button" class="quiet" data-stage-jump="references" data-library-target="world">查看世界设定</button></section><div class="brief-intent-actions"><div><b>下一步：系统分析故事方向</b><small>会提出建议的角色卡、全作的混合走向、第一场的起草重心和老师出场建议。结果先是 Proposal。</small></div><button class="primary" type="submit">${hasIdea?'重新分析这句想法':'分析这句想法'}</button></div></form>`);
};

renderBlueprint=function(el){
  const b=blueprint(),cards=libraryCards().filter(card=>card.status!=='archived'),foundation=briefWorldFoundation();
  if(!brief()){
    el.innerHTML=frame('第 2 步 / 5','等待故事方向','先提供一句想法，系统才有可分析的输入。','<button class="primary" data-stage-jump="brief">返回写作想法</button>');
    return;
  }
  if(!b){
    el.innerHTML=frame('第 2 步 / 5','等待系统分析','想法已经保存。现在生成一份可修改、可退回的方向候选。',`<div class="empty-state"><div class="number">02</div><h3>还没有故事方向候选</h3><p class="lede">分析只会创建 StoryBlueprint Proposal，不会写正文或修改人物卡。</p><button class="primary" data-action="generate-blueprint">生成故事方向候选</button></div>`);
    return;
  }
  const proposal=b.status==='proposed',narratorOnly=b.narrator_only===true,recommendations=b.recommendations||{},suggestedMode=recommendations.primary_scene_mode||b.mode||'bond_short',secondary=(recommendations.secondary_scene_modes||[]).filter(mode=>mode!==suggestedMode),selectedIds=new Set(b.decision?.character_card_ids||recommendations.character_card_ids||[]),sensei=recommendations.sensei_presence||'absent',worldBasis=recommendations.world_basis||foundation;
  const story=`<section class="blueprint-story"><div><p class="eyebrow">STORY DIRECTION</p><h3>${esc(b.title)}</h3><p>${esc(b.premise)}</p></div><div class="blueprint-conflict"><span>核心冲突</span><b>${esc(b.central_conflict)}</b><span>主题方向</span><b>${esc(b.theme)}</b></div><ol class="direction-list">${(b.direction||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></section>`;
  if(!proposal){
    el.innerHTML=frame('第 2 步 / 5','故事方向已确认','这份确认过的方向会作为章节与场景的共同边界。要调整时，重新让系统分析并确认新的候选。',`<div class="notice good">已确认 · ${b.simulation_notice?esc(b.simulation_notice):'方向已保存为独立 StoryBlueprint 修订。'}</div>${story}<section class="blueprint-confirmed-summary"><span>已确认角色</span><b>${esc((b.decision?.character_card_ids||b.characters||[]).length?cards.filter(card=>(b.decision?.character_card_ids||[]).includes(card.id)).map(card=>card.name).join('、')||(b.characters||[]).join('、'):narratorOnly?'纯旁白，不需要人物卡':'尚未登记')}</b><span>第一场起草重心</span><b>${esc(sceneModeLabel(b.decision?.mode||suggestedMode))}</b></section><form id="blueprintReviewForm" class="blueprint-revisit"><label>这版方向需要怎样调整？<textarea name="feedback" placeholder="例如：保留调查线，但希望先用日常互动建立角色关系。"></textarea></label><button class="quiet" name="review_action" value="regenerate" type="submit">按这些意见重新分析</button></form><div class="actions"><button class="primary" data-stage-jump="structure">开始安排章节与场景</button></div>`);
    return;
  }
  const cardChoices=narratorOnly?'<div class="blueprint-empty-choice"><b>纯旁白方向</b><span>这篇作品不会装配人物卡，也不会生成角色对白。</span></div>':cards.length?cards.map(card=>`<label class="blueprint-character-choice ${selectedIds.has(card.id)?'suggested':''}"><input type="checkbox" name="character_card_ids" value="${esc(card.id)}" ${selectedIds.has(card.id)?'checked':''}><span class="avatar-token">${esc(card.name.slice(0,1))}</span><span><b>${esc(card.name)}</b><small>${esc(libraryKindLabel(card.source_type))} · ${esc(trustLabel(card.trust_status))}</small></span>${selectedIds.has(card.id)?'<em>系统建议</em>':''}</label>`).join(''):'<div class="blueprint-empty-choice"><b>还没有可选择的人物卡</b><span>先在人物库建立或导入角色；这里不会要求你手输译名。</span><button type="button" class="quiet" data-stage-jump="references" data-library-target="characters">去人物库</button></div>';
  el.innerHTML=frame('第 2 步 / 5','审查系统给出的故事方向','系统已经根据你的想法和当前作品资料库提出候选。现在由你调整并确认；未确认前不能建立章节。',`<section class="blueprint-proposal-status"><div><p class="eyebrow">PROPOSAL / NOT YET APPLIED</p><h3>这是一份${b.simulation_notice?'模拟':''}方向候选</h3><p>${b.simulation_notice?esc(b.simulation_notice):'结果来自已配置的写作 Provider。'} 它不会改正文、人物卡或世界观。</p></div><span class="status-chip amber">等待你的确认</span></section>${story}<form id="blueprintReviewForm" class="blueprint-review-form"><section class="blueprint-world-basis"><div><p class="eyebrow">WORLD BASIS USED FOR ANALYSIS</p><h3>${esc(worldBasis.label||foundation.label)}</h3><p>${esc(worldBasis.detail||foundation.detail)}</p></div><button type="button" class="quiet" data-stage-jump="references" data-library-target="world">查看或调整世界设定</button></section><fieldset class="blueprint-modes"><legend>系统建议的写作组成 <small>作品可以混合推进；每次场景生成只会固定使用一种规则包。</small></legend><p>当前建议以「${esc(sceneModeLabel(suggestedMode))}」作为第一场起草重心${secondary.length?`，并保留「${secondary.map(sceneModeLabel).map(esc).join('、')}」作为后续场景方向。`:''}</p><div class="mode-choice-grid">${['bond_short','main_battle','long_comedy','text_reading'].map(mode=>`<label class="mode-choice ${mode===suggestedMode?'suggested':''}"><input type="radio" name="mode" value="${mode}" ${mode===suggestedMode?'checked':''}><span><b>${esc(sceneModeLabel(mode))}</b><small>${mode===suggestedMode?'系统建议的第一场重心':'可在确认时改为此重心'}</small></span></label>`).join('')}</div></fieldset><fieldset class="blueprint-characters"><legend>${narratorOnly?'角色范围':'确认主要角色'} <small>${narratorOnly?'本方向只使用旁白，不需要人物卡。':'从已登记人物卡中点击选择，避免译名和手输错误。'}</small></legend><div class="blueprint-character-grid">${cardChoices}</div></fieldset><fieldset class="blueprint-sensei"><legend>老师是否出场 <small>${narratorOnly?'纯旁白方向固定为不出场。':`系统建议：${sensei==='present'?'本次出场':'本次不必出场'}。你可以保留自动判断或明确覆盖。`}</small></legend><div class="segmented-control"><label><input type="radio" name="sensei_presence" value="auto" ${narratorOnly?'disabled':'checked'}><span>采用系统建议</span></label><label><input type="radio" name="sensei_presence" value="present" ${narratorOnly?'disabled':''}><span>明确出场</span></label><label><input type="radio" name="sensei_presence" value="absent" ${narratorOnly?'checked':''}><span>明确不出场</span></label></div></fieldset><label class="blueprint-feedback">看完方向后再补充（可选）<textarea name="feedback" placeholder="例如：不希望把旧机器解释成反派阴谋；希望两人的关系先保持克制。">${esc(b.feedback||'')}</textarea><small>这里是对系统候选的反馈，不是让你预先猜模型需要什么。</small></label><div class="brief-actions"><div><b>确认后才会保存可执行 Brief</b><small>角色选择、第一场规则包和老师出场决定都会形成新的修订；角色卡和世界观本身不会被静默修改。</small></div><div class="actions"><button class="primary" name="review_action" value="confirm" type="submit" ${cards.length||narratorOnly?'':'disabled'}>确认方向，进入章节安排</button><button class="quiet" name="review_action" value="regenerate" type="submit">按反馈重新分析</button></div></div></form>`);
};

document.addEventListener('submit',async event=>{
  if(event.target.id!=='blueprintReviewForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const form=event.target,fields=new FormData(form),action=String(fields.get('review_action')||'confirm');
  try{
    if(action==='regenerate'){
      const feedback=String(fields.get('feedback')||'').trim();
      if(!feedback){toast('请先说明希望系统调整什么。',true);return;}
      setBusy('正在按反馈重新分析');
      const result=await api(`/works/${state.work.id}/blueprint:generate`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,feedback})});
      state.work=result.work;toast(result.simulation?'已生成新的模拟方向候选':'已生成新的方向候选');render();return;
    }
    const result=await api(`/works/${state.work.id}/blueprint:confirm`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,mode:fields.get('mode'),character_card_ids:fields.getAll('character_card_ids'),sensei_presence:fields.get('sensei_presence'),feedback:String(fields.get('feedback')||'').trim()})});
    state.work=result.work;state.stage='structure';toast('故事方向已确认，现在可以安排章节与场景');render();
  }catch(error){setBusy('确认未完成，候选仍安全保留');toast(error.message,true)}
},true);

renderInspector=function(){
  const el=$('#inspectorContent');
  if(!el)return;
  const scene=selectedScene(),proposal=pendingProposal(),latest=state.work?.releases?.[0];
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector===state.inspector));
  if(!state.work){el.innerHTML='';return;}
  if(state.inspector==='decision'){const decision=stageDecisionModel();el.innerHTML=`<div class="inspector-body inspector-decision"><p class="eyebrow">${decision.kicker}</p><h3>${esc(decision.title)}</h3><p class="inspector-copy">${esc(decision.body)}</p><section class="inspector-impact"><span>保存或确认后</span><b>${esc(decision.impact)}</b></section><ul class="inspector-checklist"><li><i class="status-dot"></i>作品与版本已持久化</li><li><i class="status-dot ${proposal?'amber':''}"></i>${proposal?'当前有候选等待审查':'没有会被静默写入的内容'}</li><li><i class="status-dot"></i>当前操作由中央工作区完成</li></ul></div>`;return;}
  if(state.inspector==='context'){const c=state.context;el.innerHTML=`<div class="inspector-body"><p class="eyebrow">SCENE CONTEXT</p><h3>当前作用域</h3><p>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'尚未选择场景'}</p><ul class="context-list">${c?`<li>规则包<br><b>${esc(c.rules.pack_version)}</b></li><li>本场起草重心<br><b>${esc(sceneModeLabel(c.rules.mode))}</b></li><li>固定输入修订<br><b>${c.source_revision_ids.length} 个</b></li><li>运行时人物卡<br><b>${c.runtime_character_cards.length} 张</b></li><li>BA 写作就绪状态<br><b>${esc(c.readiness.real_ba_writing)}</b></li>`:'<li>进入“逐场写作”并装配上下文后，这里会列出实际读取的版本。</li>'}</ul></div>`;return;}
  if(state.stage!=='draft'){el.innerHTML=`<div class="inspector-body"><p class="eyebrow">CREATIVE DIRECTOR</p><h3>Agent 在逐场写作时才出现</h3><p>先在中央工作区完成当前阶段。Agent 只依附一个场景和明确任务，不会取代作品结构或资料库。</p><button class="quiet" type="button" data-stage-jump="draft" ${stageGate('draft').allowed?'':'disabled'}>打开逐场写作</button></div>`;return;}
  if(!scene){el.innerHTML='<div class="inspector-body"><p class="eyebrow">BA WRITING AGENT</p><h3>先选择一个场景</h3><p>Agent 必须依附稳定 Scene ID，不能在空白聊天页中修改作品。</p></div>';return;}
  const existing=scene.current_revision_id,latestRun=(state.work.agent_runs||[]).find(run=>run.scope_id===scene.id),provider=state.capabilities?.providers?.[0]||{},providerLabel=provider.is_simulation?'当前为明确标注的模拟 Provider，只验证候选、Diff 和审查流程。':`当前使用已配置的真实 Provider${provider.display_name?`：${provider.display_name}`:''}。`,contextReady=Boolean(state.context),contextMissing=state.context?.readiness?.missing_runtime_character_cards||[],findings=(state.work.review_findings||[]).filter(item=>item.scene_id===scene.id&&item.status==='open'),warning=findings.find(item=>item.kind==='character_card_missing'),missingCharacters=contextMissing.length?contextMissing:(warning?.evidence?.speakers||[]),mode=existing?'rewrite':'draft',agentReady=contextReady&&!proposal&&!missingCharacters.length;
  const blocked=!contextReady?'<div class="notice">先在中央工作区装配本场上下文，Agent 才能读取固定的场景合同、规则包和人物卡修订。</div><button type="button" class="primary" data-action="assemble-context">装配本场上下文</button>':missingCharacters.length?`<div class="notice bad">还不能运行：${esc(missingCharacters.join('、'))} 尚无已确认人物卡。补齐后才能把正文与人物约束一起交给 Agent。</div><button type="button" class="primary" data-agent-complete-cards>补齐人物卡</button>`:proposal?'<div class="notice">当前已有候选等待决定。采纳或退回后，才能开始下一次 Agent 运行。</div>':'';
  const chips=existing&&agentReady?`<div class="agent-chips"><button type="button" class="quiet" data-agent-instruction="调整本场节奏：压缩解释，让动作和停顿先出现。">调整节奏</button><button type="button" class="quiet" data-agent-instruction="检查人物是否 OOC，并把需要调整的对白改写为更符合人物卡的表达。">检查 OOC</button><button type="button" class="quiet" data-agent-instruction="重写选中对白：保留本场事实、角色关系和停止边界。">重写对白</button></div>`:'';
  el.innerHTML=`<div class="inspector-body"><p class="eyebrow">BA WRITING AGENT</p><h3>${existing?'改写当前场景':'起草当前场景'}</h3><p>${existing?'当前正文会作为固定输入。Agent 只返回完整候选和 Diff，不会直接改动任何一句。':'只读取本场合同、单一 BA 模式和运行时人物卡；每次只提交一份 Proposal。'}</p>${latestRun?`<section class="agent-run"><b>${esc(latestRun.status)}</b><p>运行 ${esc(latestRun.id)} · 工具记录 ${latestRun.tool_calls.length} 项${latestRun.proposal_id?` · Proposal ${esc(latestRun.proposal_id)}`:''}</p>${latestRun.policy?.usage?`<small>${Number(latestRun.policy.usage.input_tokens||0).toLocaleString()} 输入 / ${Number(latestRun.policy.usage.output_tokens||0).toLocaleString()} 输出 token</small>`:''}</section>`:''}${blocked}<form id="agentRunForm" data-agent-mode="${mode}"><label>本场指令<textarea name="instruction" placeholder="${existing?'例如：压缩解释，保留爱丽丝先观察、凯伊后补充的节奏':'例如：让爱丽丝先观察异常，再把决定落到本场行动上'}" ${agentReady?'':'disabled'}></textarea></label>${chips}<button class="primary" type="submit" ${agentReady?'':'disabled'}>${existing?'生成完整改写候选':'运行 BA 场景 Agent'}</button></form><p class="form-note">${esc(providerLabel)} ${existing?'完整候选不会写回正文，采纳后才建立新的正文修订。':''}</p></div>`;
};

function sceneContextIsReady(){return Boolean(state.stage==='draft'&&selectedScene()&&state.context)}
function sceneAgentIsReady(){return sceneContextIsReady()&&sceneReadinessView(state.context).canRun}

function syncSceneActionGuidance(){
  if(state.stage!=='draft'||state.mobileView!=='writing')return;
  const scene=selectedScene(),proposal=pendingProposal();
  if(!scene||proposal)return;
  const current=Boolean(scene.current_revision_id),contextReady=sceneContextIsReady(),agentReady=sceneAgentIsReady(),command=$('.next-command');
  if(command){
    const headline=$('strong',command),copy=$('p',command),actions=$('.command-actions',command);
    if(!contextReady){
      if(headline)headline.textContent=current?'重新装配上下文，再继续改写':'先装配上下文，准备本场';
      if(copy)copy.textContent='将固定本场合同、单一 BA 模式、人物卡和所选世界设定修订。';
      if(actions)actions.innerHTML=`<button class="primary" data-action="assemble-context">${current?'重新装配上下文':'装配本场上下文'}</button>${current?'<button class="quiet" data-action="review-scene">检查本场</button>':''}`;
    }else if(!agentReady){
      const reason=state.context?.readiness?.reason||'需要至少一张已确认、可用于运行时的人物卡。';
      if(headline)headline.textContent='上下文已固定，但 BA Agent 尚未就绪';
      if(copy)copy.textContent=reason;
      if(actions)actions.innerHTML='<button class="primary" data-stage-jump="references" data-library-target="characters">补齐人物卡</button><button class="quiet" data-action="assemble-context">重新装配</button>';
    }else if(!current){
      if(headline)headline.textContent='上下文已固定，可以生成候选';
      if(copy)copy.textContent='生成结果只会进入 Proposal；你确认采纳前，正文仍保持空白。';
      if(actions)actions.innerHTML='<button class="primary" data-action="generate-candidate">生成本场候选</button>';
    }else{
      if(headline)headline.textContent='正文已就绪，决定下一次操作';
      if(copy)copy.textContent='可以检查连续性，也可以让 Agent 基于当前修订提出完整改写候选。';
      if(actions)actions.innerHTML='<button class="primary" data-action="generate-candidate">生成下一份候选</button><button class="quiet" data-action="review-scene">检查本场</button>';
    }
  }
  $$('[data-action="generate-candidate"]').forEach(button=>{
    button.disabled=!agentReady;
    button.title=agentReady?'结果只会进入 Proposal':contextReady?'缺少 BA Agent 所需的已确认人物卡':'请先装配本场上下文';
  });
  const contextButton=$('.manuscript-head [data-action="assemble-context"]');
  if(contextButton)contextButton.textContent=contextReady?'重新装配':'上下文';
}

stageDecisionModel=function(){
  const scene=selectedScene(),proposal=pendingProposal(),latest=state.work?.releases?.[0],current=Boolean(scene?.current_revision_id),contextReady=sceneContextIsReady(),sourceIds=scenes().map(item=>item.current_revision_id).filter(Boolean),releaseGate=(state.work?.gates||[]).find(gate=>gate.kind==='release.review'),releaseReviewCurrent=Boolean(releaseGate?.status==='passed'&&releaseGate.snapshot&&JSON.stringify(releaseGate.snapshot.scene_revision_ids)===JSON.stringify(sourceIds));
  const definitions={
    overview:{kicker:'WORKFLOW',title:'按推荐下一步推进即可',body:'作品总览只保留一个推荐行动，其他入口仍在左侧导航。',impact:'不会自动生成、修改或发布任何内容。'},
    brief:{kicker:'STEP 1',title:brief()?'想法已保存，等待分析':'先提供一句想法',body:'先让系统理解你想看什么；角色、写作组成和老师是否出场会以候选呈现，不要求你预先猜测。',impact:'系统会保存意图修订并生成 StoryBlueprint Proposal。'},
    blueprint:{kicker:'STEP 2',title:blueprintIsConfirmed()?'故事方向已确认':blueprint()?'审查故事方向候选':'等待系统分析',body:blueprintIsConfirmed()?'确认过的角色卡、世界观依据和第一场规则包会成为后续结构的边界。':'检查系统建议，点选人物卡、保留或覆盖老师出场建议，并决定是否采用。',impact:blueprintIsConfirmed()?'现在可以建立章节与场景。':'未确认前不会建立章节或写入正文。'},
    structure:{kicker:'STEP 3',title:'建立稳定的章节与场景',body:'场景拥有稳定 ID；改标题或调整顺序不会丢失正文和资料引用。',impact:'保存结构会使旧的全篇审查失效，需要重新检查。'},
    draft:{kicker:'STEP 4',title:proposal?'审查本场候选':!scene?'先建立一个场景':!contextReady?'先固定本场上下文':current?'检查或改写当前正文':'生成第一份场景候选',body:proposal?'候选可以直接编辑；采纳前不会进入正文。':!scene?'回到章节安排，先建立场景。':!contextReady?'先固定场景合同、单一 BA 模式和人物卡修订，再允许 Agent 运行。':current?'本场已有正式修订，可以检查连续性或通过 Agent 生成完整改写候选。':'上下文已就绪，下一次生成只会创建 Proposal。',impact:proposal?'采纳时才会建立新的正文修订。':'Agent 只能提交候选，不能静默修改正文或资料。'},
    references:{kicker:'WORK LIBRARY',title:'确认可进入 Agent 的资料',body:'人物、世界观、事实与来源证据分别管理。待核对条目不会自动作为写作事实。',impact:'只有确认采用的资料会出现在下一场可选择的上下文中。'},
    release:{kicker:'第 5 步',title:latest?'确认是否交给 AA 制作':releaseReviewCurrent?'审查已通过，等待冻结':'先完成全篇审查',body:latest?'这份制作定稿已固定；后续改稿不会改变它。':releaseReviewCurrent?'当前审查覆盖全部正式正文，冻结后才会出现制作交接入口。':'所有场景都有已采纳正文后，才能运行全篇审查与冻结。',impact:latest?'只有点击交接后，才会建立制作任务。':releaseReviewCurrent?'冻结会创建新的制作定稿。':'全篇审查通过前，发布操作保持锁定。'}
  };
  return definitions[state.stage]||definitions.overview;
};

const renderBeforeSceneGuidance=render;
render=function(){renderBeforeSceneGuidance();syncSceneActionGuidance()};

// Durable creation conversation and Volume-aware structure. These overrides
// are intentionally last because this client still carries the first vertical
// slice in one file while the product surfaces are being separated.
usesGuidedWorkflow=function(){return true};

function workConversationThread(){
  const threads=(state.work?.conversation_threads||[]).filter(thread=>thread.scope_type!=='scene');
  const selected=threads.find(thread=>thread.id===state.conversationThreadId&&thread.status==='active');
  const workThread=threads.find(thread=>thread.scope_type==='work'&&thread.scope_id===state.work.id&&thread.status==='active');
  const fallback=threads.find(thread=>thread.status==='active')||threads[0];
  const thread=selected||workThread||fallback;
  if(thread)state.conversationThreadId=thread.id;
  return thread;
}
function workPlanProposal(){
  return state.work?.proposals?.find(item=>['brief_blueprint','story_structure'].includes(item.kind)&&item.status==='pending');
}
function messageText(message){return message?.content?.text||''}

function conversationTextMarkup(text){
  const escaped=esc(String(text||''));
  return escaped.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
}

// Assistant text may quote trace identifiers when a provider explains a
// result. Keep those identifiers in the persisted message/API, but project
// them out of the ordinary conversation surface.
function publicMessageText(message){
  const text=messageText(message);
  if(message?.role!=='assistant')return text;
  return text
    .replace(/根据当前任务契约与工作流安全规范（?`?no_direct_writeback`?）?[，,]?/g,'按照当前写作规则，')
    .replace(/当前任务契约与工作流安全规范/g,'当前写作规则')
    .replace(/工作流安全规范/g,'写作规则')
    .replace(/任务契约/g,'当前写作要求')
    .replace(/写回边界(?:规范)?/g,'保存规则')
    .replace(/基于已锁定的基准版本（?`?当前正文版本`?）?/g,'基于当前已保存的正文')
    .replace(/HaloCue `ba-writing` 规则/g,'当前写作规则')
    .replace(/提案（候选）/g,'候选')
    .replace(/\b(?:revision|run|agent|proposal|scene|reference|copy|release|work|production)-[a-z0-9]+\b/gi,match=>({
      revision:'当前正文版本',run:'本轮运行',agent:'本轮运行',proposal:'候选',scene:'当前场景',reference:'引用',copy:'任务副本',release:'发布版本',work:'当前作品',production:'制作任务'
    }[match.split('-')[0].toLowerCase()]||'内部记录'))
    .replace(/\bsha256:[a-f0-9]{16,}\b/gi,'正文指纹')
    .replace(/\b(?:ScriptRelease|ProductionRun|WorkCanon|Revision|Proposal)\b/g,match=>({ScriptRelease:'发布版本',ProductionRun:'制作任务',WorkCanon:'作品正式资料',Revision:'正文修订',Proposal:'候选'}[match]||match))
    .replace(/(?:本轮)?基于已锁定的基准版本（?`?当前正文版本`?）?/g,'本轮基于当前已保存的正文')
    .replace(/改写候选\/提案（候选）/g,'正文候选')
    .replace(/静默覆盖/g,'自动覆盖')
    .replace(/(?<!`)`([^`\n]+)`(?!`)/g,'$1');
}

function extractOfficialScript(text){
  const source=String(text||'');
  const match=source.match(/```official_script\s*([\s\S]*?)```/i);
  if(!match)return {prose:source,script:''};
  return {prose:source.replace(match[0],'').replace(/\n{3,}/g,'\n\n').trim(),script:match[1].trim()};
}

/* class="official-script-candidate" is retained as the stable review-surface contract. */
function officialScriptCandidateMarkup(message){
  const extracted=extractOfficialScript(publicMessageText(message));
  if(!extracted.script)return '';
  const proposal=message?.proposal_id?(state.work?.proposals||[]).find(item=>item.id===message.proposal_id):null;
  const latestSceneTarget=(state.work?.intent_plans||[]).find(plan=>plan.target?.scene_id)?.target?.scene_id||'';
  const pendingScene=(state.work?.proposals||[]).find(item=>item.kind==='scene_script'&&item.status==='pending')?.scope_id||'';
  const sceneId=proposal?.scope_type==='scene'?proposal.scope_id:(latestSceneTarget||pendingScene);
  const pending=proposal?proposal.status==='pending':Boolean(pendingScene&&sceneId===pendingScene);
  const accepted=proposal?.status==='accepted';
  const lines=extracted.script.split(/\r?\n/).filter(Boolean);
  const linesMarkup=lines.map(line=>{const match=line.match(/^([^:：]{1,24})[:：]\s*(.*)$/);return match?`<p><b>${esc(match[1])}</b><span class="official-script-colon">：</span>${esc(match[2])}</p>`:`<p>${esc(line)}</p>`}).join('');
  const actionLabel=pending?'在写作页审查':accepted?'查看已采用正文':'查看当前正文';
  const action=sceneId?`<button type="button" class="quiet" data-open-official-script="${esc(sceneId)}">${actionLabel}</button>`:`<button type="button" class="quiet" data-stage-jump="structure">${actionLabel}</button>`;
  const title=pending?'这是一份尚未写入的正文':accepted?'这份正文候选已经采用':'这是一份较早的正文候选';
  const note=pending?'正式正文仍需在写作页审查，不会在构思对话里直接替换。':accepted?'当前正文已经保存在写作页。':'这份候选不会覆盖当前正文，可以在写作页查看最新内容。';
  const status=pending?'等待审查':accepted?'已经采用':'已经处理';
  return `<section class="official-script-candidate ${pending?'is-pending':'is-historical'}" aria-label="正文候选"><header><div><p class="eyebrow">正文候选</p><h4>${title}</h4><p>${note}</p></div><span class="status-chip ${pending?'amber':''}">${status}</span></header><div class="official-script-body">${linesMarkup}</div><div class="official-script-actions">${action}</div></section>`;
}

function renderConversationMessage(message){
  const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[];
  return `<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${content.simulation_notice?`<small>${esc(content.simulation_notice)}</small>`:''}${message.proposal_id?`<button class="message-proposal-link" type="button" data-stage-jump="brief">查看待审方案</button>`:''}</div></article>`;
}
function renderWorkConversationInspector(){
  const el=$('#inspectorContent'),thread=workConversationThread(),proposal=workPlanProposal();
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));
  if(!thread){el.innerHTML='<div class="inspector-body"><p>当前作品还没有创作主对话。</p></div>';return}
  const discuss=thread.phase==='discuss';
  el.innerHTML=`<div class="director-panel"><header class="director-header"><div><p class="eyebrow">CREATIVE DIRECTOR</p><h3>全作 · 创作主对话</h3><small>对话 v${thread.version} · ${state.capabilities?.providers?.[0]?.is_simulation?'模拟 Provider':'已配置模型'}</small></div></header><div class="director-modes" role="group" aria-label="创作导演状态"><button type="button" data-thread-phase="discuss" class="${discuss?'active':''}">讨论创作</button><button type="button" data-thread-phase="execute" class="${!discuss?'active':''}">执行修改</button></div><div class="conversation-scroll" data-conversation-scroll>${thread.messages.map(renderConversationMessage).join('')||'<p class="conversation-empty">先说一句你想看的故事。</p>'}</div>${proposal?`<div class="director-pending"><b>故事方案等待决定</b><span>正式 Brief 和故事方向尚未改变。</span><button type="button" data-stage-jump="brief">查看方案</button></div>`:''}<form id="workConversationForm" class="conversation-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="补充、反悔、比较方向，或直接说明哪里不对……"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}<button class="quiet" type="button" data-organize-conversation ${proposal?'disabled':''}>整理为方案</button></div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
}

const inspectorBeforeDurableConversation=renderInspector;
renderInspector=function(){
  if(state.work&&state.inspector==='agent'&&state.stage!=='draft')return renderWorkConversationInspector();
  return inspectorBeforeDurableConversation();
};

renderBrief=function(el){
  const proposal=workPlanProposal(),savedBrief=brief(),thread=workConversationThread();
  if(proposal){
    const candidate=proposal.candidate,plan=candidate.story_blueprint,changes=proposal.diff?.changes||[];
    el.innerHTML=frame('讨论整理 / 等待采纳','检查创作导演整理的故事方案','这份内容来自当前创作主对话。采纳前，正式 Brief、故事方向、人物卡和世界观都不会改变。',`<section class="work-plan-status"><div><p class="eyebrow">PROPOSAL / NOT APPLIED</p><h3>${esc(plan.title||'故事方向候选')}</h3><p>${esc(plan.premise||candidate.brief.idea)}</p></div><span class="status-chip amber">等待你的决定</span></section><div class="work-plan-grid"><section><p class="eyebrow">CENTRAL CONFLICT</p><h3>故事的核心变化</h3><p>${esc(plan.central_conflict||'待继续讨论')}</p><ol class="direction-list">${(plan.direction||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></section><section class="work-plan-diff"><p class="eyebrow">FROM DISCUSSION</p>${changes.map(item=>`<div><span>${esc(item.field)}</span><p>${esc(item.after||'未填写')}</p></div>`).join('')}</section></div><div class="plan-decision-bar"><div><b>采纳会建立两份正式修订</b><small>Brief 与 StoryBlueprint 会保留来源对话和 Proposal ID；仍不会生成正文。</small></div><div class="actions"><button class="primary" type="button" data-accept-work-plan="${esc(proposal.id)}">采纳方案</button><button class="quiet" type="button" data-reject-work-plan="${esc(proposal.id)}">退回继续讨论</button></div></div>`);
    return;
  }
  if(savedBrief){
    const plan=blueprint();
    el.innerHTML=frame('创作基础 / 已采纳','故事方向已经成为正式版本','你仍可在右侧继续讨论并提出新方案；旧修订不会被覆盖。',`<section class="accepted-plan"><p class="eyebrow">CURRENT FORMAL PLAN</p><h3>${esc(plan?.title||savedBrief.idea)}</h3><p>${esc(plan?.central_conflict||savedBrief.constraints||'可以继续补充本作约束。')}</p><div class="accepted-plan-meta"><span>Brief · 已确认</span><span>StoryBlueprint · 已接受</span><span>来源 · 创作主对话</span></div></section><div class="actions"><button class="primary" type="button" data-stage-jump="structure">查看卷、章与场景</button><button class="quiet" type="button" data-inspector="agent">继续讨论新方向</button></div>`);
    return;
  }
  el.innerHTML=frame('创作讨论 / 尚未成案','先和创作导演把想法聊清楚','作品骨架已经建立，但对话不是正式设定。你可以反悔、补充或比较方向，觉得足够后再整理为方案。',`<section class="discussion-start"><div><p class="eyebrow">当前范围</p><h3>${esc(state.work.title)} · 全作</h3><p>默认卷和第一章已经创建。当前 ${thread?.messages?.length||0} 条消息只属于创作讨论，不会写入作品事实。</p></div><div class="discussion-actions"><button class="primary" type="button" data-inspector="agent">打开创作导演</button><button class="quiet" type="button" data-organize-conversation>整理为方案</button></div></section><section class="discussion-boundary"><b>创作导演可以做什么</b><p>复述理解、提出关键不确定项、比较方向，并把共识整理成可审查的故事方案。</p><b>它不会做什么</b><p>不会把聊天静默写成人物卡、世界观、作品事实或正文。</p></section>`);
};

renderStructure=function(el){
  const volumes=state.work.volumes||[],formal=blueprintIsConfirmed();
  const volumeMarkup=volumes.map((volume,volumeIndex)=>`<section class="volume-section"><header class="volume-head"><div><p class="eyebrow">VOLUME ${String(volumeIndex+1).padStart(2,'0')}</p><h3>${esc(volume.title)}</h3><small>${volume.chapters.length} 章 · ${volume.chapters.reduce((sum,chapter)=>sum+chapter.scenes.length,0)} 个场景</small></div><button class="quiet" type="button" data-structure-add-chapter="${esc(volume.id)}" ${formal?'':'disabled'} title="${formal?'在本卷增加章节':'确认整体故事方向后可增加更多章节'}">新增章节</button></header><div class="volume-chapters">${volume.chapters.map((chapter,chapterIndex)=>`<section class="volume-chapter ${chapter.status==='placeholder'?'placeholder':''}"><header><div><span>第 ${String(chapterIndex+1).padStart(2,'0')} 章</span><h4>${esc(chapter.title)}</h4><small>${chapter.status==='placeholder'?'作品建立时创建，可直接规划第一场':`${chapter.scenes.length} 个场景`}</small></div><button class="quiet" type="button" data-structure-add-scene="${esc(chapter.id)}">新增场景</button></header><div class="volume-scenes">${chapter.scenes.length?chapter.scenes.map((scene,index)=>`<button type="button" class="volume-scene" data-scene-open="${esc(scene.id)}"><span>${String(index+1).padStart(2,'0')}</span><div><b>${esc(scene.title)}</b><small>${esc(scene.contract.goal||'尚未填写本场变化')} · ${scene.current_revision_id?'已有正文':'尚未起草'}</small></div></button>`).join(''):'<div class="volume-scene-empty">还没有场景。可以先建立第一场，再和创作导演讨论它应该发生什么。</div>'}</div></section>`).join('')}</div></section>`).join('');
  el.innerHTML=frame('STORY STRUCTURE','卷、章与场景','这些层级在建立作品时就存在，不需要等 AI 决定后才能查看。标题可以变化，稳定 ID 和正文修订不会变化。',`<section class="structure-scope-note"><div><b>${formal?'整体方向已确认':'整体方向仍在讨论'}</b><p>${formal?'可以继续增加卷章和场景。':'第一卷与第一章已经可用；新增更多章节前先确认整体方向，避免过早铺开结构。'}</p></div><button class="quiet" type="button" data-inspector="agent">和创作导演讨论结构</button></section><div class="volume-board">${volumeMarkup}</div><div class="structure-footer"><button class="primary" type="button" data-structure-add-volume>新增卷</button><span>新增卷会自动建立第一章占位。</span></div>`);
};

function decorateVolumeTree(){
  const tree=$('#sceneTree');if(!tree||!state.work)return;
  const volumes=state.work.volumes||[];
  tree.innerHTML=volumes.map((volume,index)=>`<div class="tree-volume"><p><span>卷 ${String(index+1).padStart(2,'0')}</span><b>${esc(volume.title)}</b></p>${volume.chapters.map(chapter=>`<div class="tree-chapter-group"><p class="tree-chapter">${esc(chapter.title)}</p>${chapter.scenes.map(scene=>`<button class="scene-link ${scene.id===state.sceneId?'active':''}" data-scene="${esc(scene.id)}">${esc(scene.title)} <small>· ${scene.current_revision_id?'正文':'计划'}</small></button>`).join('')}</div>`).join('')}</div>`).join('');
}

function decorateTopStatus(){
  const el=$('#saveStatus');if(!el)return;
  el.dataset.state=state.work?'saved':'idle';
  el.title=state.work?'内容已保存到本地':'尚未建立作品';
}

const renderBeforeDurableConversation=render;
render=function(){renderBeforeDurableConversation();decorateVolumeTree();decorateTopStatus()};

document.addEventListener('submit',async event=>{
  if(event.target.id==='workConversationForm'){
    event.preventDefault();event.stopImmediatePropagation();const thread=workConversationThread(),fields=new FormData(event.target);
    const activeRun=workAgentActiveRun(thread);
    event.target.dataset.submitting='true';
    try{
      setBusy(activeRun?'正在保存转向要求':'正在保存本轮输入');
      const body={expected_thread_version:thread.version,text:fields.get('text'),attachment_ids:state.composerAttachmentIds||[],task_scope:agentTaskScope()};
      const path=activeRun
        ?`/works/${state.work.id}/agent-runs/${activeRun.id}:redirect`
        :`/works/${state.work.id}/threads/${thread.id}/messages:enqueue`;
      if(activeRun)body.idempotency_key=globalThis.crypto?.randomUUID?.()||`redirect-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const result=await api(path,{method:'POST',body:JSON.stringify(body)});
      state.work=result.work;state.activeAgentRunId=result.agent_run_id;state.composerAttachmentIds=[];state.composerPrefill='';state.composerImportStatus=state.composerImportMode?'sent':'';state.composerImportMode='';state.composerImportId='';state.composerImportPreview=null;state.composerImportError='';
      setBusy(activeRun?'已转向，Agent 正在重新处理':'Agent 正在思考');render();scheduleAgentRunPoll(result.agent_run_id,0)
    }catch(error){await recoverFailedAgentTurn(error);event.target.dataset.submitting='false';setBusy(activeRun?'转向未生效':'对话发送失败');toast(error.message,true)}
    return;
  }
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||!state.work)return;
  if(button.dataset.permissionMode){event.preventDefault();event.stopImmediatePropagation();(async()=>{const thread=button.closest('.scene-harness')?sceneConversationThread():workConversationThread(),mode=button.dataset.permissionMode;if(!thread)return;try{const result=await api(`/works/${state.work.id}/threads/${thread.id}/settings`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,permission_mode:mode,phase:thread.phase})});state.work=result.work;toast(mode==='managed'?'已开启限定范围的托管创作':'已切换为所有修改均需审核');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.threadPhase){event.preventDefault();event.stopImmediatePropagation();(async()=>{const thread=workConversationThread();try{const result=await api(`/works/${state.work.id}/threads/${thread.id}/settings`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,permission_mode:thread.permission_mode,phase:button.dataset.threadPhase})});state.work=result.work;render()}catch(error){toast(error.message,true)}})();return}
    if(button.dataset.organizeConversation!==undefined){event.preventDefault();event.stopImmediatePropagation();(async()=>{const thread=workConversationThread(),task=conversationTaskContract(thread);try{setBusy(task.id==='structure.plan'?'正在整理作品结构':'正在整理讨论');const scope=agentTaskScope();const result=await api(`/works/${state.work.id}/threads/${thread.id}/proposal:organize`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,expected_thread_version:thread.version,task_scope:scope})});state.work=result.work;const created=(state.work.proposals||[]).find(item=>item.id===result.proposal_id);state.stage=scope.surface==='chapter'?'structure':state.stage;state.inspector='agent';const label=created?.kind==='story_structure'?'作品结构候选已生成，采纳前不会建立场景':scope.surface==='chapter'?'章内细纲候选已生成，等待你的决定':result.simulation?'已生成模拟故事方案，等待你的决定':'故事方案已整理，等待你的决定';toast(label);render()}catch(error){setBusy('未能整理方案');toast(error.message,true)}})();return}
  if(button.dataset.acceptWorkPlan){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/proposals/${button.dataset.acceptWorkPlan}/accept`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=result.work;state.stage='structure';toast('故事方案已采纳为正式修订');render()}catch(error){toast(error.message,true)}})();return}
  if(button.dataset.rejectWorkPlan){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/proposals/${button.dataset.rejectWorkPlan}/reject`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:'退回创作主对话继续讨论'})});state.work=result.work;state.inspector='agent';toast('方案已退回，对话和历史仍保留');render()}catch(error){toast(error.message,true)}})();return}
},true);

document.addEventListener('click',event=>{
  if(event.target.closest('.permission-menu'))return;
  $$('details.permission-menu[open]').forEach(menu=>menu.removeAttribute('open'));
});

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  $$('details.permission-menu[open]').forEach(menu=>menu.removeAttribute('open'));
});

renderOverview=renderOverviewV3;

/* The director is one conversation. Discussion, planning and a requested
   rewrite are different intents in the same thread, not tabs that duplicate
   the visible history. Keep the complete history for the provider, but keep
   the workbench readable by collapsing older messages. */
function conversationHistoryMarkup(messages){
  const all=Array.isArray(messages)?messages:[],visibleCount=4;
  const older=all.length>visibleCount?all.slice(0,-visibleCount):[],visible=all.slice(-visibleCount);
  const renderGroup=(items)=>items.map((message,index)=>renderConversationMessage(message,{grouped:index>0&&items[index-1]?.role===message.role})).join('');
  return `${older.length?`<details class="conversation-history"><summary>查看较早对话 · ${older.length} 条</summary>${renderGroup(older)}</details>`:''}${renderGroup(visible)}`;
}

function conversationTaskContract(thread){
  const progress=workflowProgress();
  const expected=!progress.done.brief?'brief.build':!progress.done.blueprint?'blueprint.generate':!progress.done.structure?'structure.plan':!progress.done.draft?'scene.draft.generate':'release.review';
  const assistant=[...(thread?.messages||[])].reverse().find(message=>message.role==='assistant'&&message.content?.task_contract);
  if(assistant&&assistant.content.task_contract.id===expected)return assistant.content.task_contract;
  const template=(state.capabilities?.writing_pack?.templates||[]).find(item=>item.id===expected)||{};
  const fallbackTasks={
    'brief.build':'理解这句想法，提出需要讨论的方向，不写入任何正式设定。',
    'blueprint.generate':'围绕当前想法讨论、比较并形成可审查的故事方向 Proposal。',
    'structure.plan':'基于已确认的故事方向，讨论卷、章与场景的稳定结构；结构变更需经用户确认。',
    'scene.draft.generate':'协助确定下一场的目标与修改约束；具体正文只能通过该场的 Proposal / Diff 提交。',
    'release.review':'协助全篇审查、确认未决事项，并在检查通过后准备制作定稿。'
  };
  return {...template,id:expected,task:fallbackTasks[expected]};
}
function renderConversationTask(contract){
  const execution={user_confirmed:'等待确认',proposal_then_confirm:'先提案后确认',automatic_proposal_only:'仅生成候选',automatic_gate_then_user_freeze:'审查后冻结'}[contract?.execution]||'受阶段约束';
  const stageName=state.stage==='overview'?'下一阶段':stageLabel(state.stage);
  return `<section class="director-task-contract"><div><span>当前任务</span><b>${esc(stageName)} · ${esc(contract?.id||'writing')}</b><small>${esc(contract?.task||'继续当前阶段的讨论；正式变更仍需经过 Proposal 和 Gate。')}</small></div><em>${esc(execution)}</em></section>`;
}
function pendingHarnessDecision(){
  return [state.agentPresentation?.guidance,state.work?.harness].some(harness=>harness?.outcome==='needs_user'&&harness?.primary_action?.id==='proposal.apply');
}
function renderConversationAction(contract,proposal){
  if(!['brief.build','blueprint.generate'].includes(contract?.id))return'';
  if(pendingHarnessDecision())return'';
  return `<button class="quiet" type="button" data-organize-conversation ${proposal?'disabled':''}>形成故事方向方案</button>`;
}

renderConversationMessage=function(message){
  const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[];
  return `<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}`:''}${message.proposal_id?`<button class="message-proposal-link" type="button" data-stage-jump="brief">查看待审方案</button>`:''}</div></article>`;
};

renderMobileAgent=function(el){
  const thread=workConversationThread(),proposal=workPlanProposal(),task=conversationTaskContract(thread);
  if(!thread){el.innerHTML=frame('CREATIVE DIRECTOR','创作对话','当前作品还没有创作主对话。','<div class="notice">重新打开作品后会自动恢复对话。</div>');return;}
  el.innerHTML=`<div class="mobile-agent-page"><header class="mobile-agent-head"><div><p class="eyebrow">CREATIVE DIRECTOR</p><div class="agent-title-row"><h2>创作导演</h2><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><p>${esc(state.work.title)} · 对话跨越全作连续保留</p></div></header>${renderConversationTask(task)}<div class="mobile-conversation-scroll" data-mobile-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于这部作品的对话。</p>'}</div>${proposal?'<div class="director-pending"><b>有一份故事方案等待决定</b><span>对话仍可继续，但正式产物尚未改变。</span><button type="button" data-stage-jump="brief">查看方案</button></div>':''}<form id="mobileWorkConversationForm" class="conversation-composer mobile-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-mobile-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};

renderWorkConversationInspector=function(){
  const el=$('#inspectorContent'),thread=workConversationThread(),proposal=workPlanProposal(),task=conversationTaskContract(thread);
  $$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));
  if(!thread){el.innerHTML='<div class="inspector-body"><p>当前作品还没有创作主对话。</p></div>';return;}
  el.innerHTML=`<div class="director-panel"><header class="director-header"><div><p class="eyebrow">CREATIVE DIRECTOR</p><div class="agent-title-row"><h3>创作导演</h3><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><small>全作 · 对话保留在当前作品</small></div></header>${renderConversationTask(task)}<div class="conversation-scroll" data-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于这部作品的对话。</p>'}</div>${proposal?`<div class="director-pending"><b>有一份故事方案等待决定</b><span>对话仍可继续，但正式产物尚未改变。</span><button type="button" data-stage-jump="brief">查看方案</button></div>`:''}<form id="workConversationForm" class="conversation-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;
  const scroll=$('[data-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
};

function sceneConversationThread(scene=selectedScene()){
  if(!scene)return null;
  return (state.work?.conversation_threads||[]).find(thread=>thread.scope_type==='scene'&&thread.scope_id===scene.id&&thread.status==='active')||null;
}

function sceneConversationMessageMarkup(message){
  const assistant=message.role==='assistant',content=message.content||{},tools=content.tool_activity||[],thinking=content.reasoning_summary||'';
  return `<article class="scene-conversation-message ${assistant?'assistant':'user'}"><div class="scene-message-role">${assistant?'Agent':'你'}</div><div class="scene-message-body"><p>${esc(messageText(message))}</p>${thinking?`<details><summary>思考摘要</summary><p>${esc(thinking)}</p></details>`:''}${tools.length?`<details><summary>工具调用 · ${tools.length} 项</summary><div class="scene-message-tools">${tools.map(tool=>`<span>${esc(agentToolLabel(tool.tool))}</span>`).join('')}</div></details>`:''}${message.proposal_id?'<button type="button" class="message-proposal-link" data-inspector="decision">查看正文候选</button>':''}</div></article>`;
}

function sceneConversationHistoryMarkup(thread){
  const messages=thread?.messages||[],visible=messages.slice(-6),older=messages.length-visible.length;
  return `${older?`<details class="scene-conversation-older"><summary>查看较早对话 · ${older} 条</summary>${messages.slice(0,older).map(sceneConversationMessageMarkup).join('')}</details>`:''}${visible.map(sceneConversationMessageMarkup).join('')}`;
}

function latestFailedSceneAgentRun(scene){
  if(!scene)return null;
  return [...(state.work?.agent_runs||[])].reverse().find(run=>
    run.scope_type==='scene'
    && run.scope_id===scene.id
    && run.status==='failed'
    && ['scene.draft.generate','scene.draft.rewrite'].includes(run.policy?.workflow)
    && !agentRunHasSuccessfulRetry(run.id)
  )||null;
}

function sceneAgentRecoveryMarkup(scene){
  const run=latestFailedSceneAgentRun(scene);
  if(!run)return'';
  const view=agentFailureView(run.failure||{});
  const action=view.action==='settings'
    ?'<button type="button" class="quiet" data-action="settings">打开模型设置</button>'
    :view.action==='reload'
      ?'<button type="button" class="quiet" data-agent-reload-work>重新加载工作台</button>'
      :`<button type="button" class="quiet" data-agent-retry-run="${esc(run.id)}">重试本轮</button>`;
  return `<section class="agent-recovery-card scene-agent-recovery-card" role="status"><span class="agent-recovery-mark" aria-hidden="true"></span><div><b>${esc(view.title==='模型调用失败'?'本轮没有完成':view.title)}</b><p>${esc(view.message)}</p><small>固定输入已经保存；正式正文没有修改。</small></div>${action}</section>`;
}

function renderSceneAgentInspector(){
  $$('.inspector-tabs [data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));
  const el=$('#inspectorContent'),scene=selectedScene(),proposal=pendingProposal(),findings=(state.work?.review_findings||[]).filter(item=>item.scene_id===scene?.id&&item.status==='open'),warning=findings.find(item=>item.kind==='character_card_missing'),readiness=sceneReadinessView(state.context,warning?.evidence?.speakers||[]),existing=Boolean(scene?.current_revision_id),thread=sceneConversationThread(scene),activeRun=thread?workAgentActiveRun(thread):null,contextLabel=state.context?readiness.label:state._contextBlocked?'先完成全作方向':state._contextError?'准备失败，可重试':'正在准备本场上下文',contextDetail=state._contextBlocked||readiness.detail,contextAction=state.context?'<button class="quiet" type="button" data-inspector="context">查看</button>':state._contextBlocked?'<button class="quiet" type="button" data-stage-jump="overview">返回作品 Agent</button>':state._contextError?'<button class="quiet" type="button" data-action="assemble-context">重试准备</button>':'';
  if(!scene){el.innerHTML='<div class="inspector-body"><p>先打开一个场景，Agent 才知道当前要处理哪一段。</p></div>';return;}
  const chips=`<div class="agent-chips"><button type="button" class="quiet" data-scene-agent-prompt="先讨论这场结束时必须发生什么变化，不要生成正文。">梳理本场</button><button type="button" class="quiet" data-scene-agent-prompt="检查本场人物是否可能 OOC，并说明应遵守的人物卡依据。">检查 OOC</button>${existing?'<button type="button" class="quiet" data-scene-agent-prompt="我想调整当前正文，请先和我确认需要保留的事实与关系边界。">讨论改写</button>':''}</div>`;
  const blocked=!readiness.canRun&&state.context?`<div class="scene-agent-blocked"><b>${esc(readiness.label)}</b><span>${esc(readiness.detail)}</span>${readiness.needsCharacterCard?'<button type="button" class="quiet" data-agent-complete-cards>补齐人物卡</button>':''}</div>`:'';
  const pending=proposal?'<div class="scene-agent-pending"><div><b>有一份正文候选等待审查</b><span>可以继续讨论，但不能生成第二份候选。</span></div><button type="button" class="quiet" data-inspector="decision">查看候选</button></div>':'';
  const threadBody=thread?`${sceneConversationHistoryMarkup(thread)}${activeRun?activeAgentRunMarkup(thread):''}${sceneAgentRecoveryMarkup(scene)}`:'<div class="scene-conversation-empty"><b>正在建立本场对话</b><span>对话会绑定当前 Scene ID，并在重启后恢复。</span></div>';
  const discussionOnly=!readiness.canRun;
  const canChat=Boolean(thread&&!activeRun),canPropose=Boolean(canChat&&!discussionOnly&&!proposal&&thread.messages?.some(message=>message.role==='user'));
  const sendAction=activeRun?`<button class="agent-stop-button" type="button" data-agent-cancel-run="${esc(activeRun.id)}" title="停止本轮" aria-label="停止本轮"><span aria-hidden="true"></span></button>`:`<button class="primary" type="submit" ${canChat?'':'disabled'}>发送</button>`;
  const composerPlaceholder=discussionOnly?'先讨论缺少的人物卡、场景目标或资料；资料满足后再生成正文候选。':'补充、反悔，或说明希望本场怎样变化…';
  el.innerHTML=`<div class="scene-agent-panel scene-harness"><header><h3>本章 Agent</h3><p>${esc(scene.chapterTitle)} · 统一上下文</p></header><section class="agent-context-brief"><div><span>本章上下文</span><b>${esc(contextLabel)}</b><small>${esc(contextDetail)}</small></div>${contextAction}</section>${blocked}<div class="scene-conversation-scroll" data-scene-conversation-scroll>${threadBody}</div>${pending}<form id="sceneConversationForm" class="scene-conversation-composer" data-discussion-only="${discussionOnly?'true':'false'}"><label class="sr-only" for="sceneAgentMessage">给本章 Agent 发送消息</label><textarea id="sceneAgentMessage" name="text" required placeholder="${composerPlaceholder}" ${canChat?'':'disabled'}></textarea>${chips}<div class="scene-agent-submit">${thread?renderPermissionMenu(thread):''}<button class="quiet" type="button" data-generate-scene-proposal ${canPropose?'':'disabled'}>${existing?'形成改写候选':'形成正文候选'}</button>${sendAction}</div></form></div>`;
  const scroll=$('[data-scene-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight;
}

const renderSceneAgentInspectorWithSelection=renderSceneAgentInspector;
renderSceneAgentInspector=function(){
  renderSceneAgentInspectorWithSelection();
  const scene=selectedScene(),selection=state.sceneTextSelection?.sceneId===scene?.id?state.sceneTextSelection:null,form=$('#sceneConversationForm');
  if(!form||!selection)return;
  form.insertAdjacentHTML('afterbegin',`<section class="scene-agent-selection"><div><span>本轮局部修改</span><b>已固定 ${selection.quote.length} 个字符</b><p>${esc(selection.quote)}</p></div><button type="button" class="quiet" data-clear-scene-selection>清除选段</button></section>`);
};

// The generic shell listener also handles data-inspector buttons. Re-apply the
// writing inspector state at the writing boundary so the visible tab and the
// rendered panel cannot drift apart after a context/Agent switch.
document.addEventListener('click',event=>{
  const button=event.target.closest('.writing-workbench-stage .inspector-tabs button[data-inspector]');
  if(!button||!state.work||state.stage!=='draft')return;
  event.preventDefault();event.stopImmediatePropagation();
  state.inspector=button.dataset.inspector;
  $$('.writing-workbench-stage .inspector-tabs button[data-inspector]').forEach(item=>item.classList.toggle('active',item.dataset.inspector===state.inspector));
  render();
},true);

async function ensureSceneConversation(sceneId){
  if(!sceneId||!state.work||sceneConversationThread()||state._sceneThreadLoading===sceneId)return;
  state._sceneThreadLoading=sceneId;state._sceneThreadError='';
  try{
    const scene=scenes().find(item=>item.id===sceneId);
    const result=await api(`/works/${state.work.id}/threads`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,scope_type:'scene',scope_id:sceneId,title:`${scene?.title||'当前场景'} · 写作讨论`,permission_mode:'review'})});
    if(state.sceneId===sceneId){state.work=result.work;render()}
  }catch(error){if(state.sceneId===sceneId){state._sceneThreadError=error.message;toast(error.message,true);render()}}
  finally{if(state._sceneThreadLoading===sceneId)state._sceneThreadLoading=''}
}

const renderBeforeSceneConversation=render;
render=function(){renderBeforeSceneConversation();if(state.stage==='draft'&&state.sceneId)queueMicrotask(()=>ensureSceneConversation(state.sceneId))};

document.addEventListener('submit',event=>{
  if(event.target.id!=='sceneConversationForm')return;
  event.preventDefault();event.stopImmediatePropagation();
  const form=event.target,thread=sceneConversationThread(),scene=selectedScene(),text=String(new FormData(form).get('text')||'').trim();
  if(!thread||!scene||!text||workAgentActiveRun(thread))return;
  form.dataset.submitting='true';
  (async()=>{try{
    setBusy('本轮输入已保存，Agent 正在思考');
    const result=await api(`/works/${state.work.id}/threads/${thread.id}/messages:enqueue`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,text,task_scope:{surface:'scene',scene_id:scene.id,discussion_only:form.dataset.discussionOnly==='true'}})});
    state.work=result.work;state.activeAgentRunId=result.agent_run_id;render();scheduleAgentRunPoll(result.agent_run_id,0);
  }catch(error){await recoverFailedAgentTurn(error);setBusy('本场对话发送失败');toast(error.message,true);form.dataset.submitting='false'}})();
},true);

document.addEventListener('click',event=>{
  const prompt=event.target.closest('[data-scene-agent-prompt]');
  if(prompt){event.preventDefault();event.stopImmediatePropagation();const input=$('#sceneConversationForm textarea[name="text"]');if(input){input.value=prompt.dataset.sceneAgentPrompt;input.focus();input.setSelectionRange(input.value.length,input.value.length)}return}
  const generate=event.target.closest('[data-generate-scene-proposal]');
  if(!generate||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  const thread=sceneConversationThread(),scene=selectedScene(),selection=state.sceneTextSelection?.sceneId===scene?.id?state.sceneTextSelection:null;
  if(!thread||!scene)return;
  generate.disabled=true;
  (async()=>{try{
    setBusy(scene.current_revision_id?'正在形成改写候选':'正在形成正文候选');
    const result=await api(`/works/${state.work.id}/threads/${thread.id}/scene-proposal:generate`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,expected_thread_version:thread.version,selection})});
    state.work=result.work;state.sceneTextSelection=null;state.inspector='decision';toast('正文候选已生成，采纳前不会修改正式正文');render();
  }catch(error){
    const recovered=await recoverFailedAgentTurn(error);
    if(recovered){state.inspector='agent';render();setTimeout(()=>document.querySelector('.scene-agent-recovery-card [data-agent-retry-run],.scene-agent-recovery-card [data-agent-reload-work]')?.focus(),0)}
    setBusy('候选未生成，讨论仍已保存');toast(error.message,true);generate.disabled=false
  }})();
},true);

document.addEventListener('keydown',event=>{
  const textarea=event.target.closest('#sceneConversationForm textarea');
  if(!textarea||event.key!=='Enter'||event.shiftKey||event.isComposing||event.keyCode===229)return;
  event.preventDefault();if(textarea.value.trim()&&textarea.form?.dataset.submitting!=='true')textarea.form?.requestSubmit();
},true);

const renderInspectorBeforeSceneAgent=renderInspector;
renderInspector=function(){
  if(state.work&&state.inspector==='agent'&&state.stage==='draft')return renderSceneAgentInspector();
  return renderInspectorBeforeSceneAgent();
};

document.addEventListener('select',event=>{
  const textarea=event.target.closest?.('.manuscript-block textarea[name="text"]');
  if(!textarea||!state.work||!selectedScene()||textarea.selectionStart===textarea.selectionEnd)return;
  const block=textarea.closest('[data-manuscript-block]');
  const form=textarea.closest('#sceneManuscriptForm');
  if(!block?.dataset.blockId||!form?.dataset.baseRevision)return;
  state.sceneTextSelection={
    sceneId:selectedScene().id,
    revision_id:form.dataset.baseRevision,
    block_id:block.dataset.blockId,
    local_start:textarea.selectionStart,
    local_end:textarea.selectionEnd,
    quote:textarea.value.slice(textarea.selectionStart,textarea.selectionEnd)
  };
  if(state.inspector==='agent')renderInspector();
},true);

document.addEventListener('click',event=>{
  const clear=event.target.closest?.('[data-clear-scene-selection]');
  if(!clear)return;
  state.sceneTextSelection=null;
  renderInspector();
},true);

// Selecting a scene is a read-only context preparation step. The user should
// not have to understand an internal "assemble" operation before chatting.
document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-scene],button[data-scene-open]');
  if(!button||!state.work)return;
  const sceneId=button.dataset.scene||button.dataset.sceneOpen;
  if(!sceneId||state._contextLoadingScene===sceneId)return;
  state._contextLoadingScene=sceneId;
  setBusy('正在准备本场上下文');
  api(`/works/${state.work.id}/scenes/${sceneId}/context:assemble`,{method:'POST',body:'{}'}).then(context=>{
    if(state.sceneId===sceneId){state.context=context;state.inspector='agent';render();setBusy('本场上下文已准备');}
  }).catch(error=>{if(state.sceneId===sceneId)toast(error.message,true)}).finally(()=>{if(state._contextLoadingScene===sceneId)state._contextLoadingScene='';});
},true);

// EOF product overrides: these must run after the legacy slice declarations.
conversationTaskContract=function(){
  const scope=agentTaskScope(),hasBrief=Boolean(brief()),hasBlueprint=blueprintIsConfirmed();
  const sceneCount=(state.work?.volumes||[]).reduce((total,volume)=>total+(volume.chapters||[]).reduce((chapterTotal,chapter)=>chapterTotal+(chapter.scenes||[]).length,0),0);
  let id='brief.build',task='理解这句想法，提出需要讨论的方向，不写入任何正式设定。';
  if(scope.surface==='work'&&hasBlueprint&&!sceneCount){id='structure.plan';task='基于已确认的故事方向，讨论并整理卷、章与场景树；采纳前不会建立正式结构。';}
  else if(scope.surface==='work'&&hasBrief){id='blueprint.generate';task='在作品栏目维护全作方向、人物关系和世界观边界；任何调整都先形成新的 StoryBlueprint Proposal。';}
  else if(scope.surface==='chapter'&&hasBlueprint){id='chapter.plan';task=`只规划《${writingChapter()?.title||'当前章节'}》内部的章节目标、承接点和场景节拍，不重写全作 StoryBlueprint。`;}
  else if(scope.surface==='chapter'){id='blueprint.generate';task='全作方向尚未确认，请先回到作品栏目完成确认。';}
  const template=(state.capabilities?.writing_pack?.templates||[]).find(item=>item.id===id)||{};
  return {...template,id,task,task_scope:{surface:scope.surface,chapter_id:scope.surface==='chapter'?writingChapter()?.id:null,chapter_title:scope.surface==='chapter'?writingChapter()?.title:null}};
};
renderConversationTask=function(contract){const execution={user_confirmed:'等待确认',proposal_then_confirm:'先提案后确认',automatic_proposal_only:'仅生成候选',automatic_gate_then_user_freeze:'审查后冻结'}[contract?.execution]||'受阶段约束';const scope=contract?.task_scope?.surface==='chapter'?'章内写作':'作品规划';return `<section class="director-task-contract"><div><span>当前任务 · ${esc(scope)}${contract?.task_scope?.chapter_title?` · ${esc(contract.task_scope.chapter_title)}`:''}</span><b>${esc(contract?.id||'writing')}</b><small>${esc(contract?.task||'继续当前阶段的讨论；正式变更仍需经过 Proposal 和 Gate。')}</small></div><em>${esc(execution)}</em></section>`};
function workAgentPendingOrganization(thread=workConversationThread()){
  const messages=Array.isArray(thread?.messages)?thread.messages:[];
  const latestAssistant=[...messages].reverse().find(item=>item.role==='assistant');
  if(!latestAssistant?.content?.ready_to_organize)return false;
  const latestUser=[...messages].reverse().find(item=>item.role==='user');
  if(!latestUser)return false;
  const directionRevision=(state.work?.artifacts||[]).find(item=>item.kind==='story_blueprint')?.current_revision;
  if(!directionRevision)return true;
  return Date.parse(latestUser.created_at||'')>Date.parse(directionRevision.created_at||'');
}
renderConversationAction=function(contract,proposal,thread=workConversationThread()){
  if(proposal)return'';
  if(pendingHarnessDecision())return'';
  if(contract?.id==='chapter.plan')return'<button class="quiet" type="button" data-organize-conversation aria-label="整理章内细纲"><span class="agent-action-wide">整理章内细纲</span><span class="agent-action-short" aria-hidden="true">整理细纲</span></button>';
  if(contract?.id==='structure.plan')return'<button class="quiet" type="button" data-organize-conversation aria-label="整理作品结构"><span class="agent-action-wide">整理作品结构</span><span class="agent-action-short" aria-hidden="true">整理结构</span></button>';
  if(!['brief.build','blueprint.generate'].includes(contract?.id))return'';
  const updating=blueprintIsConfirmed();
  if(updating&&!workAgentPendingOrganization(thread))return'';
  const label=updating?'整理本轮修改':'形成全作方案';
  const shortLabel=updating?'整理修改':'形成方案';
  return `<button class="quiet" type="button" data-organize-conversation aria-label="${label}"><span class="agent-action-wide">${label}</span><span class="agent-action-short" aria-hidden="true">${shortLabel}</span></button>`;
};
renderConversationMessage=function(message){const assistant=message.role==='assistant',content=message.content||{},questions=content.questions||[],proposal=message.proposal_id?state.work?.proposals?.find(item=>item.id===message.proposal_id):null,target=proposal?.kind==='chapter_plan'?'structure':'brief';return`<article class="conversation-message ${assistant?'assistant':'user'}"><div class="message-role">${assistant?'创作导演':'你'}</div><div class="message-bubble"><p>${esc(messageText(message))}</p>${questions.length?`<ul>${questions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${message.proposal_id?`<button class="message-proposal-link" type="button" data-stage-jump="${target}">查看待审方案</button>`:''}</div></article>`};
renderWorkConversationInspector=function(){const el=$('#inspectorContent'),thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread),chapter=writingChapter(),workSurface=agentTaskScope().surface==='work';$$('[data-inspector]').forEach(button=>button.classList.toggle('active',button.dataset.inspector==='agent'));if(!thread){el.innerHTML='<div class="inspector-body"><p>当前作品还没有创作主对话。</p></div>';return}const pending=proposal?`<div class="director-pending"><b>${workSurface?'全作故事方案':`《${esc(chapter?.title||'当前章节')}》章内细纲`}等待决定</b><span>正式产物尚未改变。先审查，再决定采纳或退回。</span><div class="director-pending-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div>`:'';el.innerHTML=`<div class="director-panel"><header class="director-header"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h3>${workSurface?'全作创作导演':'章内写作助手'}</h3><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><small>${workSurface?'作品栏目 · 全局方向、人物和世界观':'写作栏目 · '+esc(chapter?.title||'尚未选择章节')} · 对话连续保留</small></div></header>${renderConversationTask(task)}<div class="conversation-scroll" data-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${pending}<form id="workConversationForm" class="conversation-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;const scroll=$('[data-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight};
var finalStructureBase=renderStructure;
renderStructure=function(el){finalStructureBase(el);const inner=$('.workspace-inner',el),chapter=writingChapter();if(!inner)return;const target=document.createElement('section');target.className='writing-target-bar';target.innerHTML=`<div><p class="eyebrow">CURRENT WRITING TARGET</p><h3>${chapter?esc(chapter.title):'还没有可写章节'}</h3><p>章内细纲、场景上下文和 Agent 讨论都会绑定这一章。全作方向请回到“作品”。</p></div><label>当前章节<select data-select-writing-chapter>${(state.work?.chapters||[]).map(item=>`<option value="${esc(item.id)}" ${item.id===chapter?.id?'selected':''}>${esc(item.title)}</option>`).join('')}</select></label>`;inner.querySelector('.structure-scope-note, .structure-command')?.before(target);const plan=(state.work.artifacts||[]).find(item=>item.kind==='chapter_plan'&&item.scope_id===chapter?.id)?.current_revision?.content;if(plan){const note=document.createElement('section');note.className='chapter-plan-summary';note.innerHTML=`<div><p class="eyebrow">CHAPTER PLAN · 已采纳</p><h3>${esc(plan.title||`${chapter.title}细纲`)}</h3><p>${esc(plan.chapter_goal||'本章目标已保存。')}</p></div><button class="quiet" type="button" data-inspector="agent">继续讨论本章</button>`;inner.querySelector('.structure-scope-note, .structure-command')?.before(note)}};
var finalRenderBase=render;
renderMobileAgent=function(el){const thread=workConversationThread(),proposal=activeConversationProposal(),task=conversationTaskContract(thread),chapter=writingChapter(),workSurface=agentTaskScope().surface==='work';if(!thread){el.innerHTML=frame('CREATIVE DIRECTOR','创作对话','当前作品还没有创作主对话。','<div class="notice">重新打开作品后会自动恢复对话。</div>');return}const pending=proposal?`<div class="director-pending"><b>${workSurface?'全作故事方案':`《${esc(chapter?.title||'当前章节')}》章内细纲`}等待决定</b><span>正式产物尚未改变。</span><div class="director-pending-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div>`:'';el.innerHTML=`<div class="mobile-agent-page"><header class="mobile-agent-head"><div><p class="eyebrow">${workSurface?'WORK DIRECTOR':'CHAPTER DIRECTOR'}</p><div class="agent-title-row"><h2>${workSurface?'全作创作导演':'章内写作助手'}</h2><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div><p>${esc(state.work.title)} · ${workSurface?'作品规划':'写作 · '+(chapter?.title||'未选择章节')}</p></div></header>${renderConversationTask(task)}<div class="mobile-conversation-scroll" data-mobile-conversation-scroll>${conversationHistoryMarkup(thread.messages)||'<p class="conversation-empty">开始一段关于当前作品的讨论。</p>'}</div>${pending}<form id="mobileWorkConversationForm" class="conversation-composer mobile-composer"><label><span class="sr-only">给 Agent 发送消息</span><textarea name="text" required placeholder="输入消息…"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form></div>`;const scroll=$('[data-mobile-conversation-scroll]',el);if(scroll)scroll.scrollTop=scroll.scrollHeight};
function cleanAutomaticContextControls(){
  $$('[data-action="assemble-context"]').forEach(button=>{if(button.closest('.manuscript-head')){button.textContent='查看上下文';button.removeAttribute('data-action');button.dataset.inspector='context'}else if(!state._contextError)button.remove();else button.textContent='重试准备'});
  $$('.next-command strong').forEach(node=>{if(node.textContent.includes('装配'))node.textContent='正在准备本场上下文'});
  $$('.next-command .command-actions').forEach(actions=>{if(!actions.children.length)actions.innerHTML='<span class="context-auto-status">系统会自动准备本场上下文</span>'});
}
render=function(){finalRenderBase();decorateVolumeTree();decorateTopStatus();cleanAutomaticContextControls();if(blueprintIsConfirmed()&&state._contextBlocked){state._contextBlocked='';state._contextErrorScene='';}if(state.stage==='draft'&&state.sceneId)queueMicrotask(()=>ensureSceneContext(state.sceneId));};

/* Works is a whole-story surface. Keep chapter workflow out of this rail and
   make the real discussion visible in the center of the workbench. */
function renderWorkRail(){
  const rail=$('#stageList'),tree=$('#sceneTree');
  const note=$('.work-surface-note');
  if(!rail)return;
  if(!state.work){
    rail.hidden=true;
    tree?.replaceChildren();
    if(note){note.hidden=true;note.replaceChildren();}
    return;
  }
  const worksSurface=state.surface==='works';
  if(!worksSurface){
    if(!rail.classList.contains('stage-list')||rail.classList.contains('work-agent-rail')||rail.classList.contains('work-nav-list')){
      rail.className='stage-list';
      rail.setAttribute('aria-label','章节写作流程');
      rail.innerHTML='<li><button data-stage="structure"><span>01</span><b>章节细纲</b><small>只规划当前章节</small></button></li><li><button data-stage="draft"><span>02</span><b>逐场写作</b><small>候选、Diff 与正文</small></button></li><li><button data-stage="release"><span>03</span><b>检查并发布</b><small>生成制作定稿</small></button></li>';
    }
    if(note)note.hidden=false;
    if(note)note.innerHTML='<p>写作栏目</p><b>当前章节与正文</b><small>章内细纲、场景写作和发布检查都绑定当前写作目标。</small><button type="button" class="quiet" data-work-surface="discussion">返回全作讨论</button>';
    return;
  }
  const active=key=>key==='discussion'&&state.stage==='overview'||key==='direction'&&['brief','blueprint'].includes(state.stage)||key==='library'&&state.stage==='references'||key==='structure'&&state.stage==='structure';
  const formal=blueprintIsConfirmed();
  rail.className='work-nav-list';
  rail.setAttribute('aria-label','作品工作面');
  rail.innerHTML=`<li><button type="button" class="work-nav-item ${active('discussion')?'active':''}" data-work-surface="discussion"><span>01</span><b>全作讨论</b><small>和创作导演讨论整篇作品</small></button></li><li><button type="button" class="work-nav-item ${active('direction')?'active':''}" data-work-surface="direction"><span>02</span><b>全作方向</b><small>把讨论整理成正式方案</small></button></li><li><button type="button" class="work-nav-item ${active('structure')?'active':''}" data-work-surface="structure" ${formal?'':'disabled'}><span>03</span><b>作品结构</b><small>${formal?'管理卷、章与场景':'确认全作方向后开放'}</small></button></li><li class="work-nav-utility"><span>作品工具</span><button type="button" class="work-resource-entry ${active('library')?'active':''}" data-work-surface="library"><b>创作资料</b><small>人物、世界观、事实与证据 · AI 协作维护</small></button></li>`;
  if(tree)tree.replaceChildren();
  if(note)note.innerHTML='<p>作品栏目</p><b>先讨论整篇作品</b><small>这里处理全作方向、人物和世界观；章节正文在“写作”里进行。</small>';
}

function renderWorkDiscussion(){
  const thread=workConversationThread(),proposal=workPlanProposal(),task=conversationTaskContract(thread);
  const messages=thread?.messages||[];
  const panel=document.createElement('section');
  panel.className='work-discussion-panel';
  panel.id='workDiscussion';
  panel.innerHTML=`<header class="work-discussion-header"><div><p class="eyebrow">WORK / DISCUSSION</p><h3>全作讨论</h3><p>这里讨论整篇作品：故事方向、人物关系、世界观边界和整体节奏。聊清楚后，再整理为正式方案。</p></div><div class="work-discussion-header-actions"><span class="scope-chip">作品级</span><span class="agent-provider-chip">${state.capabilities?.providers?.[0]?.is_simulation?'本地模拟':'已连接'}</span></div></header><div class="work-discussion-scope"><div><b>当前讨论范围</b><span>整篇作品 · 不写入章节正文</span></div><button class="quiet" type="button" data-work-surface="direction">查看正式方向</button></div><div class="work-discussion-history" data-work-discussion-scroll>${conversationHistoryMarkup(messages)||'<p class="conversation-empty">从这里开始说。你可以先讲一个想法，也可以反悔、补充或比较多个方向。</p>'}</div>${directorPendingMarkup(proposal)}${thread?`<form id="workConversationForm" class="conversation-composer work-discussion-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="补充想法、推翻刚才的方向，或告诉 AI 哪些地方需要注意……"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form>`:'<div class="notice">当前作品还没有创作主对话，重新打开作品后会自动恢复。</div>'}</section>`;
  const scroll=panel.querySelector('[data-work-discussion-scroll]');
  if(scroll)scroll.scrollTop=scroll.scrollHeight;
  return panel;
}

const renderChromeBeforeWorkRail=renderChrome;
renderChrome=function(){
  renderChromeBeforeWorkRail();renderWorkRail();
  if(state.work&&state.surface==='works'&&state.stage==='structure')setCrumb(state.work,'作品结构');
  const primarySection=state.mobileView==='tasks'?'tasks':state.stage==='references'?'references':state.surface;
  $$('[data-section]').forEach(button=>button.classList.toggle('active',button.dataset.section===primarySection));
  if(state.surface==='works'&&state.mobileView==='writing'){
    const mobileSection=state.stage==='references'?'references':'works';
    $$('[data-mobile]').forEach(button=>button.classList.toggle('active',button.dataset.mobile===mobileSection));
  }
};

const renderBeforeWorkDiscussion=render;
render=function(){
  if(state.stage==='overview'&&state.mobileView==='writing')state.inspector='decision';
  renderBeforeWorkDiscussion();
  const workspace=$('#workspace');
  if(workspace&&state.stage==='overview'&&state.mobileView==='writing'){
    $('#sceneTree')?.replaceChildren();
    workspace.querySelector('#workDiscussion')?.remove();
    const overview=workspace.querySelector('.overview-workbench');
    const header=overview?.querySelector('.overview-header');
    if(header)header.insertAdjacentElement('afterend',renderWorkDiscussion());
  }
};

document.addEventListener('click',event=>{
  const toggle=event.target.closest('[data-work-surfaces-toggle]');
  if(toggle&&state.work){event.preventDefault();event.stopImmediatePropagation();state.showGlobalSurfaces=true;render();return;}
  const surface=event.target.closest('[data-work-surface]');
  if(surface&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const key=surface.dataset.workSurface;
    if(key==='discussion'){state.stage='overview';state.mobileView='writing';}
    else if(key==='direction'){state.stage=brief()?'blueprint':'brief';state.mobileView='writing';}
    else if(key==='library'){state.stage='references';state.mobileView='writing';state.libraryView='overview';}
    else if(key==='structure'){
      const gate=stageGate('structure');
      if(!gate.allowed){toast(`尚未开放作品结构：${gate.reason}`,true);return;}
      state.stage='structure';state.mobileView='writing';
    }else if(key==='writing'){
      state.stage=blueprintIsConfirmed()?'structure':'brief';state.mobileView='writing';
    }
    render();return;
  }
  const focus=event.target.closest('[data-focus-discussion]');
  if(focus&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    state.stage='overview';state.mobileView='writing';state.inspector='decision';render();
    setTimeout(()=>document.querySelector('#workDiscussion textarea')?.focus(),0);
  }
},true);

// Final presentation pass. These wrappers must remain after the legacy
// vertical-slice overrides above.
const renderStructureBeforeFinalCompact=renderStructure;
renderStructure=function(el){
  renderStructureBeforeFinalCompact(el);
  const inner=$('.workspace-inner',el);if(!inner)return;
  const title=inner.querySelector('h2'),lede=inner.querySelector('.lede');
  if(title)title.textContent=state.surface==='works'?'作品结构':'章节与场景';
  if(lede)lede.textContent=state.surface==='works'?'在这里管理整部作品的卷、章与场景顺序。进入“写作”后，再围绕当前章节细化和起草正文。':'选择当前章节，再管理这一章的场景。全作方向、人物和世界观请回到“作品”。';
  inner.querySelectorAll('.structure-scope-note').forEach(node=>node.remove());
  const targets=[...inner.querySelectorAll('.writing-target-bar')];
  targets.slice(1).forEach(node=>node.remove());
  if(state.surface==='works')targets.forEach(node=>node.remove());
  else targets[0]?.classList.add('writing-target-compact');
  if(state.surface==='works')inner.querySelectorAll('.chapter-plan-summary').forEach(node=>node.remove());
  inner.querySelector('[data-structure-add-volume]')?.classList.replace('primary','quiet');
  inner.querySelectorAll('.scene-arrangement-copy small').forEach(node=>{
    node.textContent=node.textContent.split(' · ')[0];
  });
  const targetKicker=inner.querySelector('.writing-target-bar .eyebrow');
  const planKicker=inner.querySelector('.chapter-plan-summary .eyebrow');
  if(targetKicker)targetKicker.textContent='当前章节';
  if(planKicker)planKicker.textContent='章节细纲 · 已采纳';
};

const renderMobileTasksBeforeFinalFeedback=renderMobileTasks;
renderMobileTasks=function(el){
  renderMobileTasksBeforeFinalFeedback(el);
  const actions=el.querySelector('.actions');
  if(actions&&!actions.querySelector('[data-action="feedback"]'))actions.insertAdjacentHTML('beforeend','<button class="quiet" type="button" data-action="feedback">反馈问题</button>');
};

const renderBeforeFinalGuidance=render;
render=function(){renderBeforeFinalGuidance();decorateCurrentStepGuidance()};

// The creative library is a work surface, not a second global workspace.
// Keep its maintenance forms closed until the user explicitly opens one.
function compactCreativeLibrary(){
  const library=$('#workspace .library-workbench');
  if(!library)return;
  const header=library.querySelector('.library-header');
  if(header){
    const title=header.querySelector('h2'),lede=header.querySelector('p:not(.eyebrow)');
    header.querySelector('.eyebrow')?.remove();
    if(title)title.textContent='创作资料';
    if(lede)lede.textContent='人物、设定、事实、关系和证据都在这里管理；只有确认项会进入后续写作。';
  }
  library.querySelector(':scope > .library-scope-banner')?.remove();
  library.querySelector('.library-brief')?.remove();
  const decisionLabel=library.querySelector('.library-control-copy .eyebrow');
  if(decisionLabel)decisionLabel.textContent='待你决定';
  const view=state.libraryView;
  const editor=library.querySelector('.library-editor');
  const open=Boolean(state.libraryEditorOpen||state.editCardId||state.characterCardDraft||state.editWorldEntry||state.editCanonFactId);
  editor?.classList.toggle('library-editor-collapsed',!open);
  const pageHead=library.querySelector('.library-page-head');
  if(pageHead&&!pageHead.querySelector('[data-library-open-editor]')){
    const type=view==='canon'?'canon':view==='files'?'files':view==='timeline'?'timeline':view==='rules'?'rules':'';
    if(type)pageHead.insertAdjacentHTML('beforeend',`<button class="quiet library-open-editor" type="button" data-library-open-editor="${type}">${type==='canon'?'新增作品事实':type==='files'?'登记证据资料':type==='timeline'?'添加时间线事件':'新增世界规则'}</button>`);
  }
}

const renderBeforeCompactCreativeLibrary=render;
render=function(){renderBeforeCompactCreativeLibrary();compactCreativeLibrary();};

// In the integrated shell, a handed-off release remains a useful navigation
// target instead of becoming a permanently disabled button.
const renderReleaseBeforeProductionNavigation=renderRelease;
renderRelease=function(el){
  renderReleaseBeforeProductionNavigation(el);
  for(const release of state.work?.releases||[]){
    const button=[...el.querySelectorAll('[data-handoff]')].find(item=>item.dataset.handoff===release.id);
    if(!button)continue;
    button.dataset.workId=state.work.id;
    button.dataset.releaseId=release.id;
    if(!release.production_run_id)continue;
    button.disabled=false;
    delete button.dataset.handoff;
    button.dataset.openProduction=release.production_run_id;
    button.dataset.workId=state.work.id;
    button.dataset.releaseId=release.id;
    button.textContent='打开 AA 制作任务';
  }
};

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-release-missing-scene]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  state.sceneId=button.dataset.releaseMissingScene;
  state.context=null;state.sceneContextEditorOpen=false;
  navigateToStage('draft');render();
  setTimeout(()=>{
    const heading=document.querySelector('#workspace h2');
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true})}
  },800);
},true);

const renderReleaseBeforeContinuityGuide=renderRelease;
renderRelease=function(el){
  renderReleaseBeforeContinuityGuide(el);
  const sourceIds=scenes().map(scene=>scene.current_revision_id).filter(Boolean);
  const currentRefs=releaseSceneRevisionRefs();
  const currentDependencies=releaseDependencyRefs();
  const gate=latestWorkGate('continuity.review');
  const drift=gate?.snapshot?releaseSnapshotDrift(gate.snapshot,currentRefs,currentDependencies):[];
  const current=Boolean(gate?.snapshot&&!drift.length);
  const passed=Boolean(gate?.status==='passed'&&current);
  const actions=el.querySelector('.actions');
  if(!actions)return;
  const guide=document.createElement('section');
  guide.className=`release-review-step ${passed?'is-complete':''}`;
  guide.innerHTML=`<div><span>审查 1 / 2</span><b>跨场景连续性</b><p>${passed?'当前场景顺序、知识状态、素材引用与正式资料已检查。':gate&&!current?`${drift.length?drift.join('；'):'正文或正式资料已变化'}，需要重新检查。`:'先检查场景之间的知识顺序、关系状态和伏笔。'}</p></div><button class="quiet" type="button" data-action="review-continuity" ${sourceIds.length===scenes().length&&sourceIds.length?'':'disabled'}>${passed?'重新检查':'运行连续性审查'}</button>`;
  actions.before(guide);
  const releaseGate=latestWorkGate('release.review');
  const releaseSnapshot=releaseGate?.snapshot;
  const releaseDrift=releaseSnapshot?releaseSnapshotDrift(releaseSnapshot,currentRefs,currentDependencies):[];
  const releaseCurrent=Boolean(releaseGate?.status==='passed'&&releaseSnapshot&&!releaseDrift.length);
  const releaseGuide=document.createElement('section');
  releaseGuide.className=`release-review-step ${releaseCurrent?'is-complete':''}`;
  releaseGuide.innerHTML=`<div><span>审查 2 / 2</span><b>发布完整性</b><p>${releaseCurrent?'发布审查覆盖当前正文、素材、正式资料与写作规则。':releaseGate&&!releaseCurrent?`${releaseDrift.length?releaseDrift.join('；'):'正文、资料或写作规则已变化'}，需要重新检查。`:'连续性通过后，检查发布范围、依赖和不可变交接。'}</p></div><span class="release-review-step-status">${releaseCurrent?'已通过':releaseGate?.status==='blocked'?'存在阻塞':'待检查'}</span>`;
  actions.before(releaseGuide);
  const releaseButton=actions.querySelector('[data-action="review-release"]');
  if(releaseButton&&!passed){
    releaseButton.disabled=true;
    releaseButton.title='先完成当前正文的连续性审查';
  }
  const freezeButton=actions.querySelector('[data-action="freeze-release"]');
  if(freezeButton&&!passed){
    freezeButton.disabled=true;
    freezeButton.title='冻结前必须通过当前依赖的连续性审查';
  }
};

function currentFlowStages(){
  if(state.surface==='works'){
    return ['overview',blueprint()?'blueprint':'brief','structure'];
  }
  return FLOW_STAGES;
}
function syncFlowNavigation(){
  if(!state.work){
    const previous=$('[data-flow-nav="previous"]'),next=$('[data-flow-nav="next"]');
    [previous,next].forEach(button=>{if(button){button.disabled=true;button.dataset.flowTarget='';button.setAttribute('aria-disabled','true');button.title='建立作品后可用';}});
    return;
  }
  const stages=currentFlowStages(),index=stages.indexOf(state.stage);
  const previous=$('[data-flow-nav="previous"]'),next=$('[data-flow-nav="next"]');
  const configure=(button,target,direction)=>{
    if(!button)return;
    const gate=target?stageGate(target):{allowed:false,reason:''};
    button.disabled=!target||!gate.allowed;
    button.dataset.flowTarget=target||'';
    button.setAttribute('aria-disabled',String(button.disabled));
    button.title=!target?(direction==='previous'?'已经是第一步':'已经是最后一步'):gate.allowed?`${direction==='previous'?'返回':'进入'}：${stageLabel(target)}`:`尚未解锁：${gate.reason}`;
  };
  configure(previous,index>0?stages[index-1]:'','previous');
  configure(next,index>=0&&index<stages.length-1?stages[index+1]:'','next');
}

const renderBeforeFlowNavigation=render;
render=function(){renderBeforeFlowNavigation();syncFlowNavigation();};

document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-flow-nav]');
  if(!button)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const target=button.dataset.flowTarget;
  if(target)navigateToStage(target);
},true);

/* Unified work Agent surface. Whole-work discovery, direction and structure
   are outputs in one durable conversation instead of three competing pages. */
function agentRunForMessage(message={}){
  if(!message.agent_run_id)return null;
  return (state.work?.agent_runs||[]).find(run=>run.id===message.agent_run_id)||null;
}

function agentRunHasSuccessfulRetry(runId){
  if(!runId)return false;
  return (state.work?.agent_runs||[]).some(run=>{
    if(['failed','cancelled'].includes(run.status))return false;
    const policy=run.policy||{};
    return String(policy.retry_of||policy.retry_of_agent_run_id||'')===String(runId);
  });
}

function agentRunThreadId(run={}){
  return String(run.policy?.thread_id||run.thread_id||'');
}

function agentRunSequence(run={}){
  const runs=state.work?.agent_runs||[];
  const timestamp=Date.parse(run.created_at||'');
  if(Number.isFinite(timestamp))return timestamp;
  return runs.findIndex(item=>item.id===run.id);
}

function agentFailureNeedsRecovery(run={}){
  if(run.status!=='failed'||agentRunHasSuccessfulRetry(run.id))return false;
  const threadId=agentRunThreadId(run);
  if(!threadId)return true;
  const sequence=agentRunSequence(run);
  return !(state.work?.agent_runs||[]).some(candidate=>{
    if(candidate.id===run.id||candidate.scope_type!=='work')return false;
    if(agentRunThreadId(candidate)!==threadId)return false;
    return agentRunSequence(candidate)>sequence;
  });
}

async function recoverFailedAgentTurn(error){
  if(error?.code!=='agent_failed'||!state.work?.id)return false;
  try{
    state.work=await api(`/works/${state.work.id}`);
    state.composerAttachmentIds=[];
    render();
    return true;
  }catch(refreshError){
    return false;
  }
}

function agentToolLabel(name){
  return ({
    load_workflow_template:'加载 BA 写作工作流',
    read_work_context:'读取作品上下文',
    read_conversation_history:'读取当前对话',
    search_character_cards:'检索人物卡',
    search_world_bible:'检索世界观资料',
    search_work_canon:'检索作品事实',
    draft_character_card:'生成人物卡讨论草稿',
    draft_world_card:'生成世界观讨论草稿',
    draft_world_rule:'生成世界规则讨论草稿',
    draft_canon_fact:'生成作品事实讨论草稿',
    create_knowledge_proposal:'整理资料候选',
    store_conversation_attachments:'保存对话附件',
  })[name]||name||'Agent 工具';
}

function compactTokenCount(value){
  const count=Number(value);
  if(!Number.isFinite(count))return'';
  if(count>=1000000)return`${(count/1000000).toFixed(count>=10000000?0:1)}M`;
  if(count>=1000)return`${(count/1000).toFixed(count>=10000?0:1)}K`;
  return String(count);
}

function agentUsageMarkup(message={}){
  const input=message.input_tokens,output=message.output_tokens,cacheRead=message.cache_read_tokens,cacheWrite=message.cache_write_tokens,cost=message.estimated_cost;
  const hasUsage=[input,output,cacheRead,cacheWrite,cost].some(value=>value!==null&&value!==undefined);
  if(!hasUsage)return'<span class="agent-usage-empty">用量未返回</span>';
  const parts=[];
  if(input!==null&&input!==undefined)parts.push(`<span title="模型输入 Tokens">输入 <b>${esc(compactTokenCount(input))}</b></span>`);
  if(output!==null&&output!==undefined)parts.push(`<span title="模型输出 Tokens">输出 <b>${esc(compactTokenCount(output))}</b></span>`);
  if(cacheRead!==null&&cacheRead!==undefined){
    const read=Number(cacheRead)||0,total=Number(input)||0;
    const ratio=total>0?Math.round(read/total*100):0;
    parts.push(`<span class="agent-cache ${read>0?'hit':'miss'}" title="缓存读取 ${esc(String(read))} Tokens">${read>0?`缓存命中 <b>${ratio}%</b>`:'缓存未命中'}</span>`);
  }
  if(cacheWrite!==null&&cacheWrite!==undefined&&Number(cacheWrite)>0)parts.push(`<span title="新写入缓存 Tokens">缓存写入 <b>${esc(compactTokenCount(cacheWrite))}</b></span>`);
  if(cost!==null&&cost!==undefined&&Number.isFinite(Number(cost)))parts.push(`<span title="Provider 返回的估算成本">估算 <b>$${Number(cost).toFixed(Number(cost)<0.01?4:2)}</b></span>`);
  return parts.join('');
}

function agentRuntimeBarMarkup(thread={}){
  const messages=Array.isArray(thread.messages)?thread.messages:[];
  const message=[...messages].reverse().find(item=>item.role==='assistant');
  const run=agentRunForMessage(message||{});
  const provider=message?.provider;
  const providerLabel=provider?.is_simulation?'模拟模式':'Agent 可用';
  const runLabel=run?.status==='failed'?'运行失败':run?.status==='running'?'运行中':'';
  return `<span class="composer-runtime-meta" aria-label="Agent 状态"><span>${esc(providerLabel)}</span>${runLabel?`<em>${esc(runLabel)}</em>`:''}</span>`;
}

function agentRunElapsedLabel(run){
  if(!run?.created_at)return'';
  const started=Date.parse(run.created_at),finished=Date.parse(run.finished_at||'');
  if(!Number.isFinite(started)||!Number.isFinite(finished)||finished<started)return'';
  const seconds=Math.max(1,Math.round((finished-started)/1000));
  return seconds<60?`${seconds} 秒`:`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`;
}

function agentFailureView(failure={}){
  const code=String(failure?.code||'');
  const kind=String(failure?.failure_kind||'');
  if(code==='agent_start_timeout')return {title:'输入保存超时',message:'本轮输入没有及时固定，正式资料没有修改。可以安全重试。',action:'retry'};
  if(code==='agent_turn_budget_exceeded'||code==='agent_cost_budget_exceeded')return {title:'Agent 授权预算已用完',message:'当前授权的轮次或成本预算已用完。调整授权或模型预算后再继续。',action:'settings'};
  if(kind==='provider_invalid_request')return {title:'模型请求被拒绝',message:String(failure?.details?.provider_message||'模型或请求参数不被 Provider 接受。请检查模型设置后重试。'),action:'settings',technicalOpen:true};
  if(kind==='provider_timeout')return {title:'模型服务超时',message:'模型服务没有在限定时间内响应，正式资料没有修改。可以安全重试。',action:'retry'};
  if(kind==='provider_rate_limited')return {title:'模型服务触发限流',message:'模型服务暂时限制请求频率，正式资料没有修改。稍后再重试。',action:'retry'};
  if(code==='agent_snapshot_integrity_failed'||code==='conversation_summary_integrity_failed')return {title:'固定输入完整性校验失败',message:'原始输入或摘要与保存的校验值不一致，系统已停止重复运行。重新加载工作台以重新读取诊断。',action:'reload',technicalOpen:true};
  return {title:'模型调用失败',message:String(failure?.message||'本轮没有完成，请检查模型服务后重试。'),action:'retry'};
}

function agentRunHasRecoveryPresentation(runId){
  if(!runId)return false;
  return (state.agentPresentation?.events||[]).some(event=>
    event?.event_type==='recovery.available'
    && String(event.refs?.agent_run_id||event.details?.target_id||'')===String(runId)
  );
}

function workAgentToolMarkup(content={},message={}){
  const contract=content.task_contract||{};
  const trace=content.agent_trace||{};
  const run=agentRunForMessage(message);
  const persistedCalls=Array.isArray(run?.tool_calls)?run.tool_calls.map(call=>({
    tool:call.tool_name,
    label:agentToolLabel(call.tool_name),
    status:call.status,
    output:call.output_ref,
    error:call.error,
  })):[];
  const activity=persistedCalls.length?persistedCalls:(Array.isArray(trace.steps)?trace.steps:(Array.isArray(content.tool_activity)?content.tool_activity:[]));
  const rows=[...activity];
  const traceSummary=String(trace.summary||'').trim();
  const reasoning=trace.reasoning||{};
  if(!rows.length&&!run?.id&&!traceSummary&&!reasoning.summary)return'';
  const status=run?.status||trace.status||'completed';
  const scope=trace.scope||contract.task_scope||{};
  const scopeLabel=scope.surface==='chapter'?(scope.chapter_title?`章节 · ${scope.chapter_title}`:'当前章节'):'作品全局';
  const summary=traceSummary||'已读取当前阶段所需的作品信息，并按权限边界完成本轮处理。';
  const reasoningLabel=reasoning.source==='provider'?(reasoning.is_simulation?'模拟推理摘要':'模型提供的可公开摘要'):'执行摘要';
  const reasoningContent=reasoning.summary?`<section class="agent-technical-reasoning"><b>${esc(reasoningLabel)}</b><p>${esc(reasoning.summary)}</p></section>`:'';
  const permission=run?.policy?.mode||'review';
  const permissionLabel=permission==='managed'?'受控托管':'所有修改需审核';
  const runFailure=run?.failure;
  const failureView=agentFailureView(runFailure||{});
  const technicalRows=rows.map(item=>{
    const itemStatus=item.status||'succeeded';
    const itemLabel={succeeded:'完成',running:'执行中',failed:'失败',waiting_user:'待确认',queued:'排队',blocked:'已阻塞',denied:'权限拒绝'}[itemStatus]||'已记录';
    const error=item.error&&typeof item.error==='object'?(item.error.message||item.error.code):item.error;
    return `<li data-status="${esc(itemStatus)}"><div><b>${esc(item.label||agentToolLabel(item.tool))}</b><code>${esc(item.tool||'agent_step')}</code></div><em>${esc(itemLabel)}</em>${error?`<pre class="agent-step-error">${esc(String(error))}</pre>`:''}</li>`;
  }).join('');
  if(status==='failed'){
    const action=agentFailureNeedsRecovery(run)?failureView.action==='settings'?'<button type="button" class="quiet" data-action="settings">打开模型设置</button>':failureView.action==='reload'?'<button type="button" class="quiet" data-agent-reload-work>重新加载工作台</button>':run?`<button type="button" class="quiet" data-agent-retry-run="${esc(run.id)}">重试本轮</button>`:'':'';
    const historyNote=action?'正式资料没有修改，失败输入已经保存。':'这次失败已由后续对话接续；失败输入和运行记录仍可追溯。';
    return `<section class="agent-failure-card"><span class="agent-failure-mark" aria-hidden="true">错</span><div><b>${esc(failureView.title)}</b><p>${esc(failureView.message)}</p><small>${esc(historyNote)}</small><details class="agent-technical"${failureView.technicalOpen?' open':''}><summary>技术详情</summary><div class="agent-technical-body"><div class="agent-technical-meta"><span>${esc(scopeLabel)}</span><span>${esc(permissionLabel)}</span>${run?.id?`<code>${esc(run.id)}</code>`:''}</div>${reasoningContent}${technicalRows?`<ol class="agent-technical-tools">${technicalRows}</ol>`:''}</div></details></div>${action}</section>`;
  }
  const active=['running','queued'].includes(status);
  const elapsed=agentRunElapsedLabel(run);
  const thinkingLabel=active?'正在思考…':`已思考${elapsed?` ${elapsed}`:''}`;
  const publicSummary=reasoning.summary||summary;
  const technical=technicalRows||run?.id?`<details class="agent-technical"><summary>运行详情</summary><div class="agent-technical-body"><div class="agent-technical-meta"><span>${esc(scopeLabel)}</span><span>${esc(permissionLabel)}</span>${run?.id?`<code>${esc(run.id)}</code>`:''}</div>${technicalRows?`<ol class="agent-technical-tools">${technicalRows}</ol>`:''}</div></details>`:'';
  return `<details class="agent-thinking" data-status="${esc(status)}"><summary><span class="agent-thinking-indicator" aria-hidden="true"></span><span>${esc(thinkingLabel)}</span><span class="agent-thinking-toggle" aria-hidden="true"></span></summary><div class="agent-thinking-body"><p>${esc(publicSummary)}</p>${technical}</div></details>`;
}

function compactParagraphNumber(value){
  const match=String(value||'').match(/(\d+)$/);
  return match?String(Number(match[1])):String(value||'');
}

function knowledgeSourceMarkup(sources=[]){
  const seen=new Set(),items=[];
  for(const source of Array.isArray(sources)?sources:[]){
    if(!source||typeof source!=='object')continue;
    const displayLabel=String(source.display_label||'').trim();
    const filename=String(source.filename||displayLabel.split(' · ')[0]||'').trim();
    if(!filename)continue;
    const paragraphIds=Array.isArray(source.paragraph_ids)?source.paragraph_ids.filter(Boolean):[];
    let paragraphLabel='';
    if(paragraphIds.length){
      const first=compactParagraphNumber(paragraphIds[0]),last=compactParagraphNumber(paragraphIds.at(-1));
      paragraphLabel=paragraphIds.length===1?`段落 ${first}`:`段落 ${first}-${last}`;
    }else if(displayLabel.includes(' · ')){
      paragraphLabel=displayLabel.split(' · ').slice(1).join(' · ');
    }
    const marker=`${filename}|${paragraphLabel}`;
    if(seen.has(marker))continue;
    seen.add(marker);
    items.push(`<span class="artifact-source"><b>${esc(filename)}</b>${paragraphLabel?`<small>${esc(paragraphLabel)}</small>`:''}</span>`);
  }
  return items.length?`<div class="artifact-sources" aria-label="候选来源"><span>来源</span>${items.join('')}</div>`:'';
}

function knowledgeFieldValue(value,key=''){
  if(value===undefined||value===null||value===''||(Array.isArray(value)&&!value.length))return '未设置';
  if(key==='source_refs'&&Array.isArray(value))return `${value.length} 条来源`;
  const text=Array.isArray(value)?value.map(item=>{
    if(item&&typeof item==='object')return item.display_label||item.filename||item.target||item.name||'资料条目';
    return String(item);
  }).join('；'):value&&typeof value==='object'?(value.display_label||value.filename||value.target||value.name||JSON.stringify(value)):String(value);
  return text.length>150?`${text.slice(0,150)}…`:text;
}

function knowledgeFieldChangesMarkup(changes=[],operation='create',proposalId='',selectable=false,selectionDisabled=false){
  const items=Array.isArray(changes)?changes.filter(item=>item&&item.field):[];
  if(!items.length)return '';
  const fieldLabel=operation==='update'?'本次将修改':'候选包含';
  const selectionNote=selectionDisabled?' · 新建资料需整体应用':'';
  return `<section class="artifact-field-changes" aria-label="本次资料变更"><b>${fieldLabel}${selectionNote}</b>${items.map(item=>`<div class="artifact-field-change">${selectable&&item.key?`<label class="artifact-field-select${selectionDisabled?' is-disabled':''}"><input type="checkbox" data-knowledge-field="${esc(proposalId)}" value="${esc(item.key)}" checked${selectionDisabled?' disabled aria-disabled="true"':''}><span>${esc(item.field)}</span></label>`:`<span>${esc(item.field)}</span>`}${operation==='update'?`<p><del>${esc(knowledgeFieldValue(item.before,item.key))}</del><ins>${esc(knowledgeFieldValue(item.after,item.key))}</ins></p>`:`<p><ins>${esc(knowledgeFieldValue(item.after,item.key))}</ins></p>`}</div>`).join('')}</section>`;
}

function knowledgeImpactMarkup(impact={}){
  if(!impact||typeof impact!=='object'||!Array.isArray(impact.affected_consumers))return'';
  const consumers=impact.affected_consumers.filter(item=>item?.label);
  const refs=Array.isArray(impact.affected_refs)?impact.affected_refs.filter(item=>item?.label):[];
  const conflict=impact.conflict_summary||{},conflictCount=Number(conflict.count||0);
  const conflictLabel=conflict.status==='clear'||!conflictCount
    ?'未发现冲突'
    :conflict.status==='blocking'
      ?`与 ${conflictCount} 条现有设定存在阻塞冲突`
      :`与 ${conflictCount} 条现有设定可能重叠`;
  return `<section class="knowledge-impact-preview"><header><b>影响预览</b><span class="${conflict.status==='blocking'?'blocked':conflictCount?'review':'clear'}">${esc(conflictLabel)}</span></header>${consumers.length?`<div><span>将影响</span>${consumers.map(item=>`<em>${esc(item.label)}</em>`).join('')}</div>`:''}${refs.length?`<div><span>具体范围</span>${refs.slice(0,6).map(item=>`<em>${esc(item.label)}</em>`).join('')}${refs.length>6?`<em>另 ${refs.length-6} 项</em>`:''}</div>`:''}</section>`;
}

function projectedAgentCard(message={}){
  const events=state.agentPresentation?.events||[];
  const matches=events.filter(event=>event?.details?.card&&(
    event.refs?.message_id===message.id||
    (message.proposal_id&&event.refs?.proposal_id===message.proposal_id)
  ));
  return matches.find(event=>event.event_type==='proposal.presented')?.details?.card||matches.at(-1)?.details?.card||null;
}

function projectedAgentCardMarkup(card={}){
  const labels={DirectionProposalCard:'故事方向',CharacterProposalCard:'人物卡',WorldEntityProposalCard:'世界观卡',WorldRuleProposalCard:'世界规则',CanonProposalCard:'作品事实'};
  const kindLabel=labels[card.component]||'创作产物';
  const proposal=card.decision||{},proposalId=proposal.proposal_id||'';
  const pending=card.status==='pending',accepted=card.status==='accepted',rejected=['rejected','superseded'].includes(card.status);
  const organized=card.status==='discussion_draft'&&(state.agentPresentation?.events||[]).some(event=>{
    const candidate=event?.details?.card;
    return event.event_type==='proposal.presented'&&candidate?.component===card.component&&candidate?.title===card.title;
  });
  if(organized){
    return `<details class="agent-inline-artifact draft organized"><summary><span class="artifact-kind">${esc(kindLabel)}</span><div><b>${esc(card.title||kindLabel)}</b><small>讨论草稿 · 已整理为下方候选</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body"><p>${esc(card.summary||'')}</p></div></details>`;
  }
  if(card.component==='DirectionProposalCard'){
    const direction=card.direction||{},options=Array.isArray(direction.options)?direction.options:[];
    const details=`<div class="direction-card-body">${card.summary?`<p>${esc(card.summary)}</p>`:''}${direction.central_conflict?`<dl><dt>核心冲突</dt><dd>${esc(direction.central_conflict)}</dd></dl>`:''}${options.length?`<ul>${options.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}</div>`;
    const actions=pending?`<div class="artifact-decision-actions"><button class="primary" type="button" data-accept-work-plan="${esc(proposalId)}">应用故事方向</button><button class="quiet" type="button" data-reject-work-plan="${esc(proposalId)}">退回继续讨论</button></div>`:accepted?'<div class="artifact-result accepted"><span aria-hidden="true">✓</span><div><b>故事方向已采用</b><small>正式版本与来源已经保存</small></div></div>':rejected?'<div class="artifact-result"><div><b>这份方向已退回</b><small>继续对话即可形成新候选</small></div></div>':'';
    return `<details class="agent-inline-artifact proposal ${esc(card.status||'pending')}" data-proposal-card="${esc(proposalId)}"${pending?' open':''}><summary><span class="artifact-kind">${kindLabel}</span><div><b>${esc(card.title||'故事方向候选')}</b><small>${pending?'等待你的决定':accepted?'已写入正式版本':'已处理'}</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body">${details}${actions}</div></details>`;
  }
  const changes=Array.isArray(card.changes)?card.changes.map(item=>({field:item.label,key:item.key,before:item.before,after:item.after})):[];
  const canPartial=Boolean(pending&&proposal.partial_accept_supported&&changes.length);
  const impact=Array.isArray(card.impact)?knowledgeImpactMarkup({affected_consumers:card.impact,affected_refs:card.impact_refs||[],conflict_summary:card.conflict_summary||{status:'clear',count:0,blocking_count:0}}):'';
  const sources=knowledgeSourceMarkup((card.sources||[]).map(item=>({display_label:item.label})));
  const changesMarkup=knowledgeFieldChangesMarkup(changes,card.operation||'create',proposalId,pending, pending&&!canPartial);
  const blocking=Number(card.conflict_summary?.blocking_count||0)>0;
  let actions='';
  if(card.status==='discussion_draft'){
    const kind={CharacterProposalCard:'character_card',WorldEntityProposalCard:'world_card',WorldRuleProposalCard:'world_rule',CanonProposalCard:'canon_fact'}[card.component]||'';
    actions=`<div class="artifact-decision-actions"><button type="button" class="primary" data-agent-propose-knowledge="${esc(kind)}">整理为${kindLabel}候选</button><button type="button" class="quiet" data-agent-continue-draft="请继续和我讨论：${esc(card.title||'')}">继续讨论</button></div>`;
  }else if(pending){
    const count=canPartial?changes.length:Math.max(1,changes.length);
    actions=`<div class="artifact-selection-summary" data-knowledge-selection-summary="${esc(proposalId)}">已选择 ${count} / ${count} 项</div><div class="artifact-decision-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposalId)}" ${canPartial?'data-partial-knowledge ':''}data-knowledge-apply-count="${esc(proposalId)}" data-impact-digest="${esc(proposal.impact_digest||'')}" ${blocking||!proposal.can_apply?'disabled aria-disabled="true"':''}>应用 ${count} 项修改</button>${canPartial?`<button class="quiet" type="button" data-select-all-knowledge="${esc(proposalId)}">全部选择</button>`:''}<button class="quiet" type="button" data-reject-director-proposal="${esc(proposalId)}">退回继续讨论</button></div>`;
  }else if(accepted){
    actions='<div class="artifact-result accepted"><span aria-hidden="true">✓</span><div><b>新修订已保存</b><small>后续上下文会读取这份正式资料</small></div></div>';
  }else if(rejected){
    actions='<div class="artifact-result"><div><b>这份候选已处理</b><small>正式资料没有被静默修改</small></div></div>';
  }
  const expanded=pending||card.status==='discussion_draft';
  return `<details class="agent-inline-artifact proposal ${esc(card.status||'discussion_draft')}" data-proposal-card="${esc(proposalId)}"${expanded?' open':''}><summary><span class="artifact-kind">${esc(kindLabel)}</span><div><b>${esc(card.title||kindLabel)}</b><small>${pending?'等待你的决定':card.status==='discussion_draft'?'对话草稿 · 尚未写入正式资料':accepted?'已写入正式资料':'已处理'}</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body">${card.summary?`<p>${esc(card.summary)}</p>`:''}${changesMarkup}${sources}${impact}${actions}</div></details>`;
}

function workAgentDraftMarkup(content={},message={}){
  const projected=projectedAgentCard(message);
  if(projected)return projectedAgentCardMarkup(projected);
  const draft=content.artifact_preview;
  if(!draft)return'';
  const character=draft.kind==='character_card';
  const fact=draft.kind==='canon_fact';
  const rule=draft.kind==='world_rule';
  const expectedProposalKind=character?'character_card':fact?'canon_fact':rule?'world_rule':'world_entity';
  const linkedProposal=(state.work?.proposals||[]).find(item=>item.kind===expectedProposalKind&&item.candidate?.source_message_ids?.includes(message.id));
  const proposalId=content.proposal_id||message.proposal_id||linkedProposal?.id||'';
  const proposal=proposalId?(state.work?.proposals||[]).find(item=>item.id===proposalId):null;
  const discussionAlreadyOrganized=draft.status==='discussion_draft'&&Boolean(linkedProposal);
  const status=discussionAlreadyOrganized?'organized':(proposal?.status||draft.status||'discussion_draft');
  const kindLabel=character?'人物卡':fact?'作品事实':rule?'世界规则':'世界观卡';
  const operation=draft.operation||proposal?.candidate?.operation||'create';
  const update=operation==='update';
  const conflicts=Array.isArray(draft.conflicts)?draft.conflicts:(Array.isArray(proposal?.candidate?.conflicts)?proposal.candidate.conflicts:[]);
  const blockingConflicts=conflicts.filter(item=>item?.blocking!==false);
  const sources=[draft.sources,proposal?.candidate?.document_citations,proposal?.evidence?.document_citations,proposal?.candidate?.content?.source_refs].find(items=>Array.isArray(items)&&items.length)||[];
  const fieldChanges=draft.field_changes||proposal?.candidate?.field_changes||proposal?.diff?.changes||[];
  const impactPreview=draft.impact_preview||proposal?.candidate?.impact_preview||{};
  const labels={discussion_draft:'对话草稿 · 尚未写入正式资料',organized:'讨论草稿 · 已整理为下方候选',proposal:'资料候选 · 等待你决定',pending:'资料候选 · 等待你决定',accepted:'已写入正式资料',rejected:'已退回 · 正式资料未改变',superseded:'已过期 · 需要重新整理'};
  let statusLabel=labels[status]||labels.discussion_draft;
  if(update&&['proposal','pending'].includes(status))statusLabel='更新候选 · 等待你决定';
  if(update&&status==='organized')statusLabel='更新候选 · 已整理';
  if(update&&status==='accepted')statusLabel='新修订已保存';
  if(blockingConflicts.length&&['proposal','pending'].includes(status))statusLabel='资料候选 · 存在阻塞冲突';
  const operationNote=update?`<div class="artifact-operation-note"><b>更新现有${kindLabel}</b><span>采用并保存新修订；旧版本与来源继续保留。</span></div>`:'';
  const canPartiallyAccept=update&&['proposal','pending'].includes(status)&&fieldChanges.some(item=>item?.key)&&!blockingConflicts.length;
  const changesMarkup=knowledgeFieldChangesMarkup(fieldChanges,operation,proposalId,canPartiallyAccept);
  const impactMarkup=knowledgeImpactMarkup(impactPreview);
  const sourceMarkup=knowledgeSourceMarkup(sources);
  const conflictMarkup=blockingConflicts.length?`<div class="artifact-conflict" role="alert"><b>存在阻塞冲突，暂时不能采纳</b><span>${blockingConflicts.map(item=>esc(item.label||'需要先选择或处理已有资料')).join('；')}</span></div>`:'';
  let actions='';
  if(status==='discussion_draft'){
    actions=`<div class="artifact-decision-actions"><button type="button" class="primary" data-agent-propose-knowledge="${character?'character_card':fact?'canon_fact':rule?'world_rule':'world_card'}">整理为${kindLabel}候选</button><button type="button" class="quiet" data-agent-continue-draft="${character?'请继续和我讨论这张人物卡：':fact?'请继续和我核对这条作品事实：':rule?'请继续和我核对这条世界规则：':'请继续和我讨论这条世界观：'}${esc(draft.title||'')}">继续讨论</button></div>`;
  }else if(status==='organized'){
    const decision={pending:'等待你决定',accepted:'已采用',rejected:'已退回',superseded:'已过期'}[linkedProposal?.status]||'已整理';
    actions=`<div class="artifact-result compact"><div><b>已整理为资料候选</b><small>${decision}，请查看下方候选卡。</small></div></div>`;
  }else if(status==='proposal'||status==='pending'){
    const disabled=blockingConflicts.length||!proposalId;
    const selectedCount=canPartiallyAccept?fieldChanges.filter(item=>item?.key).length:Math.max(1,fieldChanges.length);
    actions=`<div class="artifact-selection-summary" data-knowledge-selection-summary="${esc(proposalId)}">已选择 ${selectedCount} / ${Math.max(selectedCount,fieldChanges.length)} 项</div><div class="artifact-decision-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposalId)}" ${canPartiallyAccept?'data-partial-knowledge ':''}data-knowledge-apply-count="${esc(proposalId)}" data-impact-digest="${esc(impactPreview.digest||'')}" ${disabled?'disabled aria-disabled="true" title="先处理阻塞冲突后再采纳"':''}>应用 ${selectedCount} 项修改</button>${canPartiallyAccept?`<button class="quiet" type="button" data-select-all-knowledge="${esc(proposalId)}">全部选择</button>`:''}<button class="quiet" type="button" data-reject-director-proposal="${esc(proposalId)}">退回继续讨论</button></div>`;
  }else if(status==='accepted'){
    actions=`<div class="artifact-result accepted"><span aria-hidden="true">✓</span><div><b>${update?'新修订已保存':'已建立正式修订'}</b><small>后续修改仍会保留版本与来源</small></div><button type="button" class="quiet" data-agent-open-library="${fact?'canon':character?'characters':'world'}">在资料栏查看${fact?'事实':kindLabel}</button></div>`;
  }else{
    actions=`<div class="artifact-result"><div><b>${status==='rejected'?'这份候选已退回':'这份候选已失效'}</b><small>你可以继续对话，让 Agent 重新整理。</small></div></div>`;
  }
  const question=status==='discussion_draft'?`<div class="artifact-question"><span>Agent 下一步需要确认</span><b>${esc(draft.next_question||'继续补充这项设定。')}</b></div>`:'';
  const expanded=['discussion_draft','proposal','pending'].includes(status);
  return `<details class="agent-inline-artifact draft ${esc(status)} ${update?'update':''} ${blockingConflicts.length?'blocked':''}"${expanded?' open':''}><summary><span class="artifact-kind">${update?`${kindLabel}更新`:kindLabel}</span><div><b>${esc(draft.title||'讨论草稿')}</b><small>${esc(statusLabel)}</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body"><p>${esc(draft.summary||draft.content?.text||'')}</p>${operationNote}${changesMarkup}${sourceMarkup}${impactMarkup}${conflictMarkup}${question}${actions}</div></details>`;
}

function messageAttachmentsMarkup(message){
  const items=Array.isArray(message?.content?.attachments)?message.content.attachments:[];
  if(!items.length)return'';
  return `<div class="message-attachments">${items.map(item=>{const url=item.content_url||`/api/v1/works/${state.work.id}/attachments/${item.id}/content`,image=String(item.media_type||'').startsWith('image/'),extension=(String(item.filename||'文档').split('.').pop()||'DOC').slice(0,4).toUpperCase();return image?`<a href="${esc(url)}" target="_blank" rel="noreferrer" title="打开图片"><img src="${esc(url)}" alt="${esc(item.filename||'对话图片')}"><span>${esc(item.filename||'图片')}</span></a>`:`<a class="message-document" href="${esc(url)}" target="_blank" rel="noreferrer" title="打开文档"><span class="document-mark">${esc(extension)}</span><span><b>${esc(item.filename||'文档')}</b><small>已作为本轮上下文</small></span></a>`}).join('')}</div>`;
}

function importReviewMarkup(review){
  if(!review||typeof review!=='object')return '';
  const mode=review.mode==='aap_to_script'?'.aap 工程':'小说/文稿';
  const scenes=Array.isArray(review.scenes)?review.scenes:[],mappings=Array.isArray(review.character_mappings)?review.character_mappings:[],unknown=Array.isArray(review.unrecognized_nodes)?review.unrecognized_nodes:[],followups=Array.isArray(review.manual_followups)?review.manual_followups:[],citations=Array.isArray(review.source_citations)?review.source_citations:[];
  const list=(items,empty)=>items.length?`<ul>${items.slice(0,8).map(item=>`<li>${esc(typeof item==='string'?item:item.title||item.name||item.description||item.display_label||'待确认')}</li>`).join('')}</ul>`:`<p class="import-review-empty">${esc(empty)}</p>`;
  return `<details class="import-review-card" open><summary><span class="import-review-mark" aria-hidden="true">检</span><div><b>导入结构审查</b><small>${esc(mode)} · 仍是候选，不会直接写入</small></div><span>查看</span></summary><div class="import-review-body"><div class="import-review-grid"><section><b>场景</b><span>${scenes.length?`${scenes.length} 项已识别`:'等待 Agent 分段'}</span></section><section><b>人物映射</b><span>${mappings.length?`${mappings.length} 项待核对`:'尚未建立'}</span></section><section><b>来源片段</b><span>${citations.length?`${citations.length} 个可回查片段`:'暂无引用'}</span></section></div>${unknown.length?`<section><h4>无法自动识别</h4>${list(unknown,'没有发现')}</section>`:''}<section><h4>下一步需要确认</h4>${list(followups,'可以继续要求 Agent 生成剧本候选。')}</section>${citations.length?`<details class="import-review-sources"><summary>查看来源</summary>${list(citations,'暂无来源')}</details>`:''}<p class="import-review-boundary">确认结构后，再让 Agent 生成剧本 Proposal；原文件、对话和正式正文都会保留。</p></div></details>`;
}

function composerAttachmentMarkup(item){
  const image=String(item.media_type||'').startsWith('image/');
  if(image)return `<div class="composer-attachment"><img src="${esc(item.content_url)}" alt="${esc(item.filename)}"><button type="button" title="移除附件" aria-label="移除 ${esc(item.filename)}" data-composer-attachment-remove="${esc(item.id)}">×</button></div>`;
  const extension=(String(item.filename||'文档').split('.').pop()||'DOC').slice(0,4).toUpperCase();
  return `<div class="composer-attachment document"><span class="document-mark">${esc(extension)}</span><span><b>${esc(item.filename||'文档')}</b><small>文档</small></span><button type="button" title="移除附件" aria-label="移除 ${esc(item.filename)}" data-composer-attachment-remove="${esc(item.id)}">×</button></div>`;
}

renderConversationMessage=function(message){
  const assistant=message.role==='assistant',content=message.content||{};
  const options=arguments[1]||{};
  const grouped=Boolean(options.grouped);
  const sceneMemoryRequest=!assistant&&content.request_source==='scene_memory_action';
  const run=assistant?agentRunForMessage(message):null;
  if(assistant&&run?.status==='failed'&&!agentFailureNeedsRecovery(run)){
    const resumed=agentRunHasSuccessfulRetry(run.id)?'已由后续重试接续':'已由后续对话接续';
    return `<article class="conversation-message assistant agent-history-message ${grouped?'is-grouped':''}"><div class="message-avatar" aria-hidden="true">HC</div><div class="message-column"><details class="agent-history-note"><summary>较早一次未完成的模型调用 · ${resumed}</summary><p>这次输入与运行记录仍已保留，正式资料没有改变。</p></details></div></article>`;
  }
  const extracted=extractOfficialScript(publicMessageText(message));
  return `<article class="conversation-message ${assistant?'assistant':'user'} ${grouped?'is-grouped':''} ${sceneMemoryRequest?'scene-memory-request':''}"><div class="message-avatar" aria-hidden="true">${assistant?'HC':sceneMemoryRequest?'场':'你'}</div><div class="message-column"><div class="message-role">${assistant?'HaloCue 创作导演':sceneMemoryRequest?'场景资料检查':'你'}</div><div class="message-bubble">${messageAttachmentsMarkup(message)}${assistant?workAgentToolMarkup(content,message):''}${extracted.prose?`<p>${conversationTextMarkup(extracted.prose)}</p>`:''}${assistant?importReviewMarkup(content.import_review):''}${assistant?officialScriptCandidateMarkup(message):''}${workAgentDraftMarkup(content,message)}</div></div></article>`;
};

function currentWorkArtifactMarkup(){
  const artifacts=state.work?.artifacts||[];
  const briefArtifact=artifacts.find(item=>item.kind==='brief'),briefContent=briefArtifact?.current_revision?.content;
  const blueprintArtifact=artifacts.find(item=>item.kind==='story_blueprint'),plan=blueprintArtifact?.current_revision?.content;
  const characterCards=artifacts.filter(item=>item.kind==='character_card').map(item=>item.current_revision?.content).filter(Boolean);
  const world=artifacts.find(item=>item.kind==='world_bible')?.current_revision?.content||{};
  const activeWorld=(world.entities||[]).filter(item=>item.status!=='archived');
  const canon=artifacts.find(item=>item.kind==='work_canon')?.current_revision?.content||{};
  const volumes=state.work?.volumes||[],chapters=volumes.flatMap(volume=>volume.chapters||[]),sceneList=chapters.flatMap(chapter=>chapter.scenes||[]);
  if(!briefContent&&!plan&&!characterCards.length&&!activeWorld.length&&!chapters.length)return'';
  const idea=briefContent?.idea||plan?.premise||'尚未形成正式创作想法';
  const ideaCard=briefContent||plan?`<details class="agent-inline-artifact idea"><summary><span class="artifact-kind">创作想法</span><div><b>${esc(plan?.title||state.work.title)}</b><small>已确认的故事方向</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body"><p class="artifact-premise">${esc(idea)}</p>${plan?.central_conflict?`<div class="artifact-field"><span>核心变化</span><b>${esc(plan.central_conflict)}</b></div>`:''}${plan?.direction?.length?`<ol>${plan.direction.map(item=>`<li>${esc(item)}</li>`).join('')}</ol>`:''}</div></details>`:'';
  const contextSummary=`${briefContent||plan?'1 个方向':'方向待定'} · ${characterCards.length} 人物 · ${activeWorld.length} 条世界设定 · ${(canon.facts||[]).length} 条作品事实 · ${chapters.length} 章`;
  return `<details class="work-agent-context"><summary><span class="context-mark" aria-hidden="true">资</span><div><b>已确认的创作资料</b><small>${esc(contextSummary)}</small></div><span class="context-toggle">查看</span></summary><div class="work-agent-context-body"><p>这里汇总已经确认、可供 Agent 使用的资料；本轮对话不会直接改动它们。</p><div class="agent-artifact-grid">${ideaCard}<details class="agent-inline-artifact"><summary><span class="artifact-kind">人物</span><div><b>${characterCards.length?characterCards.map(card=>esc(card.name)).join('、'):'待讨论'}</b><small>${characterCards.length} 张已确认人物卡</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body">${characterCards.length?characterCards.map(card=>`<div class="artifact-person"><span>${esc((card.name||'?').slice(0,1))}</span><div><b>${esc(card.name||'未命名')}</b><small>${esc(card.role||card.voice_anchors?.[0]||'已建立人物边界')}</small></div></div>`).join(''):'<p>还没有已确认的人物卡。可以在对话里让 Agent 先提出候选。</p>'}<button type="button" class="quiet" data-agent-open-library="characters">在资料栏查看人物卡</button></div></details><details class="agent-inline-artifact"><summary><span class="artifact-kind">世界与事实</span><div><b>${activeWorld.length} 条世界设定 · ${(canon.facts||[]).length} 条作品事实</b><small>仅统计已正式采纳的内容</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body">${activeWorld.slice(0,3).map(item=>`<div class="artifact-line"><b>${esc(item.name)}</b><span>${esc(item.summary)}</span></div>`).join('')||'<p>当前没有已确认的世界观卡。</p>'}<button type="button" class="quiet" data-agent-open-library="world">在资料栏查看世界观</button></div></details><details class="agent-inline-artifact structure"><summary><span class="artifact-kind">作品结构</span><div><b>${volumes.length} 卷 · ${chapters.length} 章 · ${sceneList.length} 场</b><small>用于章节写作</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body">${volumes.map((volume,index)=>`<div class="artifact-structure-line"><span>卷 ${String(index+1).padStart(2,'0')}</span><div><b>${esc(volume.title)}</b><small>${(volume.chapters||[]).map(chapter=>esc(chapter.title)).join(' · ')||'尚无章节'}</small></div></div>`).join('')||'<p>尚未建立作品结构。</p>'}<button type="button" class="quiet" data-section="writing">进入章节写作</button></div></details></div></div></details>`;
}

function workUserStatusMarkup(){
  const status=state.userStatus;
  if(!status?.primary_action)return '';
  const action=status.primary_action;
  const alerts=(status.alerts||[]).map(item=>`<li class="work-user-status-alert ${esc(item.kind||'info')}">${esc(item.text||'')}</li>`).join('');
  return `<section class="work-user-status" aria-live="polite"><div class="work-user-status-copy"><p class="eyebrow">当前下一步</p><h3>${esc(action.label)}</h3><p>${esc(action.detail)}</p>${alerts?`<ul aria-label="当前需要留意的事项">${alerts}</ul>`:''}</div><button class="primary" type="button" data-user-status-action="${esc(action.id)}" data-user-status-target="${esc(action.target||'agent')}">${esc(action.label)}</button></section>`;
}

function workAgentProposalMarkup(proposal){
  if(!proposal)return'';
  const candidate=proposal.candidate||{},plan=candidate.story_blueprint||{},briefCandidate=candidate.brief||{};
  if(proposal.kind==='story_structure'){
    const structure=candidate.plan||{},volumes=Array.isArray(structure.volumes)?structure.volumes:[];
    const chapters=volumes.flatMap(volume=>Array.isArray(volume.chapters)?volume.chapters:[]);
    const sceneCount=chapters.reduce((total,chapter)=>total+(Array.isArray(chapter.scenes)?chapter.scenes.length:0),0);
    const tree=volumes.map((volume,volumeIndex)=>`<section class="structure-proposal-volume"><header><span>卷 ${String(volumeIndex+1).padStart(2,'0')}</span><div><b>${esc(volume.title||'未命名卷')}</b><small>${esc(volume.goal||'')}</small></div></header><div class="structure-proposal-chapters">${(volume.chapters||[]).map((chapter,chapterIndex)=>`<section class="structure-proposal-chapter"><div class="structure-proposal-chapter-head"><span>${String(chapterIndex+1).padStart(2,'0')}</span><div><b>${esc(chapter.title||'未命名章')}</b><small>${esc(chapter.goal||'')}</small></div></div><ol>${(chapter.scenes||[]).map(scene=>`<li><span></span><div><b>${esc(scene.title||'未命名场景')}</b><small>${esc(scene.contract?.goal||'待确认本场目标')}</small></div></li>`).join('')}</ol></section>`).join('')}</div></section>`).join('');
    return `<article class="conversation-message assistant proposal-message structure-proposal-message"><div class="message-avatar" aria-hidden="true">HC</div><div class="message-column"><div class="message-role">HaloCue 创作导演<span>需要你决定</span></div><div class="message-bubble"><p>我把已经确认的故事方向整理成了可执行的作品结构。现在仍只是候选，采用后才会建立卷、章和场景。</p><details class="agent-inline-artifact proposal structure-proposal" open><summary><span class="artifact-kind">结构候选</span><div><b>${volumes.length} 卷 · ${chapters.length} 章 · ${sceneCount} 场</b><small>候选 · 采用前不会建立结构</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body"><p class="structure-proposal-summary">${esc(structure.summary||'按当前全作方向建立第一版可逐场写作的结构。')}</p><div class="structure-proposal-tree">${tree}</div><div class="structure-proposal-safety"><span aria-hidden="true"></span><p><b>采纳后才会写入</b><small>系统会一次性建立整棵结构；若方向或现有结构已变化，本次候选会自动失效，不会部分写入。</small></p></div><div class="artifact-decision-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采用并建立结构</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div></details></div></div></article>`;
  }
  return `<article class="conversation-message assistant proposal-message"><div class="message-avatar" aria-hidden="true">HC</div><div class="message-column"><div class="message-role">HaloCue 创作导演<span>需要你决定</span></div><div class="message-bubble"><p>我把目前讨论整理成了一份故事方向候选。采纳前不会修改已确认的创作想法。</p><details class="agent-inline-artifact proposal" open><summary><span class="artifact-kind">方向候选</span><div><b>${esc(plan.title||'故事方向方案')}</b><small>候选 · 尚未采用</small></div><span class="artifact-open-label">展开</span></summary><div class="agent-inline-artifact-body"><p class="artifact-premise">${esc(plan.premise||briefCandidate.idea||'')}</p>${plan.central_conflict?`<div class="artifact-field"><span>核心变化</span><b>${esc(plan.central_conflict)}</b></div>`:''}${plan.direction?.length?`<ol>${plan.direction.map(item=>`<li>${esc(item)}</li>`).join('')}</ol>`:''}<div class="artifact-decision-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}">采纳为正式方向</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">退回继续讨论</button></div></div></details></div></div></article>`;
}

function renderUnifiedWorkAgent(){
  const thread=workConversationThread(),proposal=workPlanProposal(),task=conversationTaskContract(thread),messages=thread?.messages||[];
  const providerSimulated=Boolean(state.capabilities?.providers?.[0]?.is_simulation);
  const taskLabels={
    'brief.build':'理解你的想法，确认接下来最值得讨论的问题',
    'blueprint.generate':'继续讨论整篇作品，并把共识整理成方向候选',
    'structure.plan':'根据已经确认的方向，维护卷、章和场景骨架',
    'scene.draft.generate':'围绕当前场景讨论目标和修改要求',
    'release.review':'检查全篇连续性、人物一致性和未决伏笔'
  };
  const taskLabel=taskLabels[task?.id]||'继续理解作品，并维护清晰、可追溯的创作成果';
  return `<main class="work-agent-canvas"><header class="work-agent-header"><div class="work-agent-identity"><span class="work-agent-mark">HC</span><div><p class="eyebrow">WORK AGENT</p><h2>${esc(state.work.title)}</h2><p>和创作导演持续讨论整篇作品。方向、人物、世界观和结构会以可审查产物出现在对话中。</p></div></div><div class="work-agent-status"><span class="scope-chip">整部作品</span><span class="agent-provider-chip">${providerSimulated?'本地模拟':'模型已连接'}</span></div></header><section class="work-agent-task"><div><span>Agent 当前任务</span><b>${esc(taskLabel)}</b></div><small>正式修改会先交给你确认</small></section><section class="work-agent-thread" data-work-discussion-scroll>${currentWorkArtifactMarkup()}${messages.length?conversationHistoryMarkup(messages):'<div class="work-agent-empty"><span>HC</span><h3>从一个想法开始</h3><p>你可以补充、反悔或推翻前面的方向。Agent 会自己判断下一步应该讨论人物、世界观还是故事结构。</p><div><button type="button" data-agent-continue-draft="先复述你对这部作品的理解，并指出目前最关键的不确定项。">复述当前理解</button><button type="button" data-agent-continue-draft="检查目前还缺少哪些人物卡或世界观依据。">检查创作资料</button></div></div>'}${workAgentProposalMarkup(proposal)}</section>${thread?`<form id="workConversationForm" class="conversation-composer work-agent-composer"><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="告诉 Agent 你的想法，或要求它创建人物卡、整理世界观、调整故事方向……"></textarea></label><div class="composer-actions"><div class="composer-tools">${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}</div><button class="primary" type="submit" title="发送消息">发送</button></div></form>`:'<div class="notice">当前作品主对话未能恢复。</div>'}</main>`;
}

function renderUnifiedWorkRail(){
  const rail=$('#stageList'),tree=$('#sceneTree'),note=$('.work-surface-note');
  if(!rail)return;
  rail.className='work-agent-rail';
  rail.setAttribute('aria-label','作品 Agent');
  rail.innerHTML=`<li><button type="button" class="work-agent-rail-item active" data-work-surface="discussion"><span class="work-agent-rail-avatar">HC</span><div><b>作品 Agent</b><small>全作讨论与产物维护</small></div></button></li><li class="work-agent-rail-state"><span>当前作品</span><b>${esc(state.work.title)}</b><small>${workConversationThread()?.messages?.length||0} 条对话 · ${state.work.artifacts?.length||0} 项正式产物</small></li>`;
  tree?.replaceChildren();
  if(note)note.innerHTML='<p>作品栏目</p><b>一个持续的创作对话</b><small>人工资料管理请使用主导航中的“资料”。</small>';
}

const renderBeforeUnifiedWorkAgent=render;
render=function(){
  if(state.work&&state.surface==='works'&&['brief','blueprint','structure'].includes(state.stage))state.stage='overview';
  renderBeforeUnifiedWorkAgent();
  const active=Boolean(state.work&&state.surface==='works'&&state.mobileView==='writing'&&state.stage==='overview');
  const libraryActive=Boolean(state.work&&state.mobileView==='writing'&&state.stage==='references');
  $('#app')?.classList.toggle('work-agent-stage',active);
  $('#app')?.classList.toggle('library-stage',libraryActive);
  if(!active)return;
  renderUnifiedWorkRail();
  const workspace=$('#workspace');
  if(workspace)workspace.innerHTML=renderUnifiedWorkAgent();
  setCrumb(state.work,'作品 Agent');
  const scroll=workspace?.querySelector('[data-work-discussion-scroll]');
  if(scroll)scroll.scrollTop=(workConversationThread()?.messages?.length||0)?scroll.scrollHeight:0;
};

document.addEventListener('click',event=>{
  const official=event.target.closest('[data-open-official-script]');
  if(official&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const scene=scenes().find(item=>item.id===official.dataset.openOfficialScript);
    if(!scene){toast('正文候选对应的场景已变化，请先打开章节结构。',true);return;}
    const chapter=(state.work.chapters||[]).find(item=>item.id===scene.chapter_id);
    state.sceneId=scene.id;state.writingChapterId=chapter?.id||scene.chapter_id;state.surface='writing';state.mobileView='writing';state.stage='draft';state.inspector='decision';state.writingMobileView='review';state.context=null;state._contextError='';render();return;
  }
  const continueButton=event.target.closest('[data-agent-continue-draft]');
  if(continueButton){
    event.preventDefault();event.stopImmediatePropagation();
    const input=$('#workConversationForm textarea');
    if(input){input.value=continueButton.dataset.agentContinueDraft||'';input.focus();input.setSelectionRange(input.value.length,input.value.length)}
    return;
  }
  const libraryButton=event.target.closest('[data-agent-open-library]');
  if(libraryButton){
    event.preventDefault();event.stopImmediatePropagation();
    state.stage='references';state.mobileView='writing';state.libraryView=libraryButton.dataset.agentOpenLibrary;state.libraryEditorOpen=false;render();
    requestAnimationFrame(()=>{
      const heading=document.querySelector('.library-main h3');
      if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
    });
  }
},true);

document.addEventListener('click',event=>{
  const reloadButton=event.target.closest('[data-agent-reload-work]');
  if(reloadButton){
    event.preventDefault();event.stopImmediatePropagation();
    location.reload();
    return;
  }
  const button=event.target.closest('[data-agent-retry-run]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  const thread=workConversationThread(),runId=button.dataset.agentRetryRun;
  if(!thread||!runId)return;
  button.disabled=true;
  (async()=>{try{
    setBusy('正在重试失败的 Agent 运行');
    const result=await api(`/works/${state.work.id}/agent-runs/${runId}:retry`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,expected_version:state.work.version})});
    state.work=result.work;
    await refreshAgentPresentation();
    setBusy('重试结果已保存');
    toast(result.simulation?'模拟 Provider 已完成重试':'Agent 已完成重试');
    render();
    setTimeout(()=>{
      const target=state.stage==='draft'
        ?document.querySelector('.scene-agent-pending [data-inspector="decision"]')
        :document.querySelector('[data-agent-review-current]');
      target?.focus();
    },0);
  }catch(error){
    await recoverFailedAgentTurn(error);
    setBusy('Agent 重试失败');
    toast(error.message,true);
    button.disabled=false;
  }})();
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-task-open-scope]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  state.mobileView='writing';
  state.surface='writing';
  state.inspector='decision';
  state.assetSurfaceOpen=false;
  if(button.dataset.taskOpenScope!=='work'){
    const scene=scenes().find(candidate=>candidate.id===button.dataset.taskOpenScope);
    if(!scene){toast('这个场景已经不存在，任务记录仍然保留。',true);return}
    state.sceneId=scene.id;
    state.writingChapterId=scene.chapter_id;
    state.context=null;
  }
  navigateToStage(button.dataset.taskStage||'draft');
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    const target=document.querySelector('.scene-diff-desk button, .scene-head h3, .release-workbench h2, .workspace h2');
    if(target?.matches('button'))target.focus();
    else target?.scrollIntoView({block:'start',inline:'nearest'});
  }));
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-task-retry-run]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();button.disabled=true;
  (async()=>{try{
    setBusy('正在从固定输入恢复任务');
    const result=await api(`/works/${state.work.id}/agent-runs/${button.dataset.taskRetryRun}:retry`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});
    state.work=result.work;
    await refreshAgentPresentation();
    setBusy('重试结果已保存');
    toast('任务已重新运行，结果仍需你的决定');
    render();
  }catch(error){setBusy('任务重试失败');toast(error.message,true);button.disabled=false}
  })();
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-agent-propose-knowledge]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  const thread=workConversationThread(),kind=button.dataset.agentProposeKnowledge;
  if(!thread)return;
  button.disabled=true;
  (async()=>{try{
    setBusy('Agent 正在整理资料候选');
    const result=await api(`/works/${state.work.id}/threads/${thread.id}/knowledge:propose`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,expected_thread_version:thread.version,kind})});
    state.work=result.work;
    setBusy('资料候选等待决定');
    toast(kind==='character_card'?'人物卡候选已生成，采纳前不会写入资料库':kind==='canon_fact'?'作品事实候选已生成，采纳前不会写入资料库':'世界观候选已生成，采纳前不会写入资料库');
    render();
  }catch(error){setBusy('未能整理资料候选');toast(error.message,true);button.disabled=false}
  })();
},true);

/* ==========================================================================
   HaloCue 1.0 统一设置中心控制器 (Settings Controller)
   ========================================================================== */
const SettingsController = {
  dialog: null,
  archivedConversations: [],
  cachedPresets: [
    { id: 'deepseek', name: 'DeepSeek 官方', provider: 'openai', base_url: 'https://api.deepseek.com/v1', default_model: 'deepseek-chat', models: ['deepseek-chat', 'deepseek-reasoner'] },
    { id: 'siliconflow', name: '硅基流动', provider: 'openai', base_url: 'https://api.siliconflow.cn/v1', default_model: 'deepseek-ai/DeepSeek-V3', models: ['deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1', 'Qwen/Qwen2.5-72B-Instruct'] },
    { id: 'zhipu', name: '智谱 GLM', provider: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4-plus', models: ['glm-4-plus', 'glm-4-flash', 'glm-4-long'] },
    { id: 'moonshot', name: '月之暗面 Kimi', provider: 'openai', base_url: 'https://api.moonshot.cn/v1', default_model: 'moonshot-v1-auto', models: ['moonshot-v1-auto', 'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'] },
    { id: 'qwen', name: '通义千问 Qwen', provider: 'openai', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', default_model: 'qwen-max', models: ['qwen-max', 'qwen-plus', 'qwen-turbo'] },
    { id: 'ollama', name: '本地 Ollama', provider: 'openai', base_url: 'http://127.0.0.1:11434/v1', default_model: 'qwen2.5:7b', models: ['qwen2.5:7b', 'deepseek-r1:7b', 'llama3.1:8b'] },
    { id: 'openai', name: 'OpenAI 官方', provider: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o', models: ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'o1-preview'] },
    { id: 'anthropic', name: 'Anthropic Claude', provider: 'anthropic', base_url: 'https://api.anthropic.com', default_model: 'claude-3-5-sonnet-20241022', models: ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'] },
  ],
  activeTab: 'models',
  activePresetId: 'deepseek',
  providerSearchQuery: '',
  selectedBackup: null,

  init() {
    this.dialog = document.getElementById('settingsDialog');
    if (!this.dialog) return;

    // Open / Close Settings. Feedback has its own persisted controller above.
    const feedbackDialog = document.getElementById('feedbackDialog');

    document.addEventListener('click', (e) => {
      const openBtn = e.target.closest('[data-action="settings"], #openSettingsButton');
      const closeBtn = e.target.closest('[data-close-settings]');

      if (openBtn) {
        e.preventDefault();
        e.stopImmediatePropagation();
        this.open();
        return;
      }
      if (closeBtn) {
        e.preventDefault();
        e.stopImmediatePropagation();
        this.close();
        return;
      }
    }, true);

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('open_feedback') === '1') {
      feedbackDialog?.showModal();
    }

    // Tab navigation & Preset card clicks & Eye toggle
    this.dialog.addEventListener('click', (e) => {
      const tabBtn = e.target.closest('.settings-nav-btn[data-tab]');
      if (tabBtn) {
        this.switchTab(tabBtn.dataset.tab);
        return;
      }

      const vendorCard = e.target.closest('.vendor-card[data-preset-id]');
      if (vendorCard) {
        this.selectPreset(vendorCard.dataset.presetId);
        return;
      }

      const eyeBtn = e.target.closest('#toggleApiKeyVisibility');
      if (eyeBtn) {
        const input = document.getElementById('settingsApiKey');
        if (input) {
          const isPass = input.type === 'password';
          input.type = isPass ? 'text' : 'password';
          eyeBtn.textContent = isPass ? '隐藏' : '显示';
        }
        return;
      }

      const restoreButton = e.target.closest('[data-archived-conversation-restore]');
      if (restoreButton) {
        this.restoreArchivedConversation(restoreButton);
      }
    });

    document.getElementById('archivedConversationSearch')?.addEventListener('input', () => {
      this.renderArchivedConversations();
    });

    document.getElementById('providerPresetSearch')?.addEventListener('input', (event) => {
      this.providerSearchQuery = event.target.value || '';
      this.renderProviderPresets();
    });

    // Fetch Models button
    document.getElementById('fetchModelsBtn')?.addEventListener('click', async () => {
      await this.fetchModels();
    });

    // Test Connection button
    document.getElementById('testConnectionBtn')?.addEventListener('click', async () => {
      await this.testConnection();
    });

    // Model Form Submit (Save & Apply instantly)
    document.getElementById('settingsModelForm')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.saveModel(e.target);
    });

    // AA Inspector button
    document.getElementById('inspectAaBtn')?.addEventListener('click', async () => {
      await this.inspectAa();
    });

    // AA Adopt button
    document.getElementById('adoptAaBtn')?.addEventListener('click', async () => {
      await this.adoptAa();
    });

    // Preferences Form Submit
    document.getElementById('preferencesForm')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.savePreferences(e.target);
    });

    // Data maintenance actions
    document.getElementById('backupDataBtn')?.addEventListener('click', () => {
      this.exportBackup();
    });

    document.getElementById('restoreBackupFile')?.addEventListener('change', (event) => {
      this.inspectBackupFile(event.target.files?.[0]);
    });

    document.getElementById('cancelBackupRestoreBtn')?.addEventListener('click', () => {
      this.resetBackupRestore();
    });

    document.getElementById('confirmBackupRestoreBtn')?.addEventListener('click', () => {
      this.restoreBackup();
    });

    // Initial load of model status for topbar badge
    this.refreshTopBarBadge();
  },

  async open() {
    this.dialog?.showModal();
    await this.loadAll();
  },

  close() {
    this.dialog?.close();
  },

  switchTab(tabName) {
    this.activeTab = tabName;
    this.dialog.querySelectorAll('.settings-nav-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    this.dialog.querySelectorAll('.settings-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `pane-${tabName}`);
    });
  },

  async loadAll() {
    try {
      const [modelRes, prefRes, diagRes, conversationRes] = await Promise.allSettled([
        api('/settings/writing-model'),
        api('/settings/preferences'),
        api('/settings/diagnostics'),
        api('/settings/conversations'),
      ]);

      if (modelRes.status === 'fulfilled' && modelRes.value) {
        this.renderModelSettings(modelRes.value);
      }
      if (prefRes.status === 'fulfilled' && prefRes.value?.preferences) {
        this.renderPreferences(prefRes.value.preferences);
      }
      if (diagRes.status === 'fulfilled' && diagRes.value) {
        this.renderDiagnostics(diagRes.value);
      }
      if (conversationRes.status === 'fulfilled') {
        this.archivedConversations = Array.isArray(conversationRes.value) ? conversationRes.value : [];
        this.renderArchivedConversations();
      } else {
        this.archivedConversations = [];
        this.renderArchivedConversations('归档对话读取失败，请稍后重试。');
      }
    } catch (e) {
      console.warn('Settings load error:', e);
    }
  },

  renderArchivedConversations(errorMessage = '') {
    const list = document.getElementById('archivedConversationList');
    const count = document.getElementById('archivedConversationCount');
    const input = document.getElementById('archivedConversationSearch');
    if (!list || !count) return;

    const query = (input?.value || '').trim().toLocaleLowerCase();
    const conversations = this.archivedConversations.filter(item => !query ||
      `${item.work_title || ''} ${item.title || ''} ${item.preview || ''}`.toLocaleLowerCase().includes(query));
    count.textContent = errorMessage || (query
      ? `找到 ${conversations.length} 条归档对话`
      : `共 ${this.archivedConversations.length} 条归档对话`);

    if (errorMessage) {
      list.innerHTML = `<div class="archived-conversation-empty"><b>暂时无法读取</b><span>${esc(errorMessage)}</span></div>`;
      return;
    }
    if (!conversations.length) {
      list.innerHTML = `<div class="archived-conversation-empty"><b>${query ? '没有匹配结果' : '还没有归档对话'}</b><span>${query ? '换一个作品名或对话名称试试。' : '归档后的作品讨论会集中保存在这里。'}</span></div>`;
      return;
    }

    list.innerHTML = conversations.map(item => `
      <article class="archived-conversation-row">
        <span class="archived-conversation-mark" aria-hidden="true">${esc((item.title || '对').slice(0, 1))}</span>
        <div class="archived-conversation-copy">
          <div><b>${esc(item.title || '未命名对话')}</b><time>${esc(workAgentThreadTime(item.updated_at))}</time></div>
          <span>${esc(item.work_title || '未命名作品')}</span>
          <small>${esc(item.preview || '这段对话还没有消息')} · ${Number(item.message_count || 0)} 条消息</small>
        </div>
        <button type="button" class="quiet archived-conversation-restore" data-archived-conversation-restore="${esc(item.id)}">恢复</button>
      </article>
    `).join('');
  },

  async restoreArchivedConversation(button) {
    const item = this.archivedConversations.find(conversation => conversation.id === button.dataset.archivedConversationRestore);
    if (!item || button.disabled) return;
    button.disabled = true;
    button.textContent = '恢复中';
    try {
      const result = await api(`/works/${item.work_id}/threads/${item.id}`, {
        method: 'POST',
        body: JSON.stringify({ expected_thread_version: item.version, status: 'active' }),
      });
      this.archivedConversations = this.archivedConversations.filter(conversation => conversation.id !== item.id);
      if (state.work?.id === item.work_id) {
        state.work = result.work;
        state.conversationThreadId = item.id;
        render();
      }
      this.renderArchivedConversations();
      toast(`已恢复“${item.title}”`);
    } catch (error) {
      button.disabled = false;
      button.textContent = '恢复';
      toast(error.message || '恢复对话失败', true);
    }
  },

  renderModelSettings(data) {
    const model = data.model || {};
    const presets = data.presets || [];
    this.cachedPresets = presets;
    this.activePresetId = model.preset_id || 'custom';

    // 1. 渲染当前生效大模型运行状态看板
    const board = document.getElementById('activeModelStatusBoard');
    const nameEl = document.getElementById('activeModelDisplayName');
    const roleBadge = document.getElementById('activeModelRoleBadge');
    const latencyPill = document.getElementById('activeModelLatencyPill');
    const idText = document.getElementById('activeModelIdText');
    const vendorText = document.getElementById('activeModelVendorText');
    const endpointText = document.getElementById('activeModelEndpointText');
    const secretText = document.getElementById('activeModelSecretText');
    const scopeText = document.getElementById('activeModelScopeText');
    const modelConfigDetails = document.getElementById('modelConfigDetails');

    if (board) {
      if (model.configured && model.model) {
        board.className = 'active-model-card configured';
        if (nameEl) nameEl.textContent = `当前生效主力：${model.model}`;
        if (roleBadge) {
          roleBadge.textContent = '已连接';
          roleBadge.className = 'model-role-badge';
        }
        if (latencyPill) {
          latencyPill.textContent = model.activation_status === 'active'
            ? `${Number(model.last_test_latency_ms || 0)}ms · 已验证`
            : '已配置 · 待测试';
        }
        if (idText) idText.textContent = model.model;

        const currentPreset = presets.find(p => p.id === model.preset_id);
        if (vendorText) {
          vendorText.textContent = currentPreset?.name || (model.base_url?.includes('deepseek') ? 'DeepSeek 官方' : (model.base_url?.includes('siliconflow') ? '硅基流动 SiliconFlow' : (model.base_url?.includes('11434') ? '本地 Ollama' : '自定义接入点')));
        }
        if (endpointText) endpointText.textContent = model.base_url || '默认服务端点';
        if (secretText) {
          secretText.textContent = model.secret_source === 'environment'
            ? '由系统安全配置提供'
            : model.secret_source === 'dpapi' ? '本机加密保存' : '无需密钥';
        }
        if (scopeText) {
          scopeText.textContent = model.activation_status === 'active'
            ? '已通过连通测试，可以用于写作与 AA 制作。'
            : '已保存，但还没有最近一次连通测试记录。';
        }
      } else {
        board.className = 'active-model-card unconfigured';
        if (nameEl) nameEl.textContent = '尚未接入外部大模型';
        if (roleBadge) {
          roleBadge.textContent = '离线模式';
          roleBadge.className = 'model-role-badge';
        }
        if (latencyPill) latencyPill.textContent = '未连接';
        if (idText) idText.textContent = '本地离线模式';
        if (vendorText) vendorText.textContent = '未连接外部服务商';
        if (endpointText) endpointText.textContent = '尚未连接服务地址';
        if (secretText) secretText.textContent = '本机加密存储可用';
        if (scopeText) scopeText.textContent = '当前使用离线模式。展开下方配置即可接入外部模型。';
      }
    }

    if (modelConfigDetails) {
      modelConfigDetails.open = !Boolean(model.configured && model.model);
      const toggleLabel = modelConfigDetails.querySelector('.model-config-summary > strong');
      if (toggleLabel) toggleLabel.textContent = modelConfigDetails.open ? '收起' : '展开';
    }

    // 2. 服务商主列表与当前配置摘要
    this.renderProviderPresets();
    this.updateSelectedProviderSummary(presets.find(p => p.id === this.activePresetId));

    const providerEl = document.getElementById('settingsProvider');
    const baseUrlEl = document.getElementById('settingsBaseUrl');
    const modelNameEl = document.getElementById('settingsModelName');
    const maxTokensEl = document.getElementById('settingsMaxTokens');
    const timeoutEl = document.getElementById('settingsTimeout');
    const inputCostEl = document.getElementById('settingsInputCost');
    const outputCostEl = document.getElementById('settingsOutputCost');
    const reasoningEl = document.getElementById('settingsReasoningMode');
    const statusBadge = document.getElementById('modelConfigStatusBadge');
    const hintEl = document.getElementById('apiKeyStatusHint');

    if (providerEl && model.provider) providerEl.value = model.provider;
    if (baseUrlEl && model.base_url !== undefined) baseUrlEl.value = model.base_url;
    if (modelNameEl && model.model) modelNameEl.value = model.model;
    if (maxTokensEl && model.max_tokens) maxTokensEl.value = model.max_tokens;
    if (timeoutEl && model.timeout) timeoutEl.value = model.timeout;
    if (inputCostEl && model.input_cost_per_million !== undefined) inputCostEl.value = model.input_cost_per_million;
    if (outputCostEl && model.output_cost_per_million !== undefined) outputCostEl.value = model.output_cost_per_million;
    if (reasoningEl && model.reasoning_mode) reasoningEl.value = model.reasoning_mode;

    if (hintEl) {
      if (model.secret_source === 'dpapi') {
        hintEl.textContent = '密钥已安全保存在本机；重新配置时输入新 Key 即可覆盖。';
      } else if (model.secret_source === 'environment') {
        hintEl.textContent = '密钥由系统安全配置提供，无需在这里重复填写。';
      } else {
        hintEl.textContent = '支持粘贴 API Key（本地加密保存）或使用环境变量。';
      }
    }

    if (statusBadge) {
      if (model.configured) {
        statusBadge.className = 'status-chip good';
        statusBadge.textContent = `已配置：${model.model}`;
      } else {
        statusBadge.className = 'status-chip amber';
        statusBadge.textContent = '尚未完成大模型接入';
      }
    }
  },

  renderProviderPresets() {
    const grid = document.getElementById('vendorPresetGrid');
    const count = document.getElementById('providerPresetCount');
    if (!grid) return;
    const query = this.providerSearchQuery.trim().toLocaleLowerCase();
    const presets = this.cachedPresets.filter(preset => !query ||
      `${preset.name || ''} ${preset.notes || ''} ${preset.default_model || ''} ${(preset.models || []).join(' ')}`
        .toLocaleLowerCase().includes(query));
    if (count) {
      count.textContent = query
        ? `找到 ${presets.length} 个服务商`
        : `${this.cachedPresets.length} 个服务商 · 选择后配置连接`;
    }
    if (!presets.length) {
      grid.innerHTML = '<div class="vendor-empty"><b>没有匹配的服务商</b><span>可以搜索模型名，或清空关键词后选择“自定义接口”。</span></div>';
      return;
    }
    grid.innerHTML = presets.map(preset => {
      const selected = preset.id === this.activePresetId;
      return `
        <button type="button" role="option" aria-selected="${selected ? 'true' : 'false'}" class="vendor-card ${selected ? 'active' : ''}" data-preset-id="${esc(preset.id)}">
          <span class="vendor-card-title"><strong>${esc(preset.name)}</strong><span class="vendor-card-check" aria-hidden="true">✓</span></span>
          <small>${esc(preset.notes || preset.default_model || '手动配置连接')}</small>
        </button>
      `;
    }).join('');
  },

  updateSelectedProviderSummary(preset) {
    const name = document.getElementById('selectedProviderName');
    const notes = document.getElementById('selectedProviderNotes');
    const protocol = document.getElementById('selectedProviderProtocol');
    if (name) name.textContent = preset?.name || '自定义模型服务';
    if (notes) notes.textContent = preset?.notes || '手动填写兼容接口、模型名称和生效范围。';
    if (protocol) protocol.textContent = preset?.provider === 'anthropic' ? 'Anthropic Messages' : 'OpenAI 兼容';
  },

  selectPreset(presetId) {
    this.activePresetId = presetId;

    const preset = this.cachedPresets.find(p => p.id === presetId);
    if (!preset) return;
    this.renderProviderPresets();
    this.updateSelectedProviderSummary(preset);

    const providerEl = document.getElementById('settingsProvider');
    const baseUrlEl = document.getElementById('settingsBaseUrl');
    const modelNameEl = document.getElementById('settingsModelName');
    const datalist = document.getElementById('settingsModelDatalist');

    if (providerEl) providerEl.value = preset.provider;
    if (baseUrlEl) baseUrlEl.value = preset.base_url;
    if (modelNameEl) modelNameEl.value = preset.default_model || (preset.models && preset.models[0]) || '';

    if (datalist && preset.models) {
      datalist.innerHTML = preset.models.map(m => `<option value="${m}">`).join('');
    }

    toast(`已加载【${preset.name}】官方预设配置`);
  },

  async fetchModels() {
    const btn = document.getElementById('fetchModelsBtn');
    const baseUrl = document.getElementById('settingsBaseUrl')?.value || '';
    const apiKey = document.getElementById('settingsApiKey')?.value || '';
    const provider = document.getElementById('settingsProvider')?.value || 'openai';

    if (btn) {
      btn.disabled = true;
      btn.textContent = '获取中...';
    }

    try {
      const res = await api('/settings/writing-model/fetch-models', {
        method: 'POST',
        body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, provider })
      });
      const models = res.models || [];
      const datalist = document.getElementById('settingsModelDatalist');
      if (datalist && models.length) {
        datalist.innerHTML = models.map(m => `<option value="${m}">`).join('');
        toast(provider === 'anthropic'
          ? `已载入 ${models.length} 个 Anthropic 推荐模型，请确认后选择`
          : `已从接口获取 ${models.length} 个可用模型，请在模型输入框中选择`);
        document.getElementById('settingsModelName')?.focus();
      } else {
        toast('接口返回了空模型列表，请手动输入');
      }
    } catch (e) {
      toast(e.message || '获取模型列表失败', true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '获取模型';
      }
    }
  },

  async testConnection() {
    const btn = document.getElementById('testConnectionBtn');
    const diagCard = document.getElementById('modelDiagnosticsCard');
    const baseUrl = document.getElementById('settingsBaseUrl')?.value || '';
    const apiKey = document.getElementById('settingsApiKey')?.value || '';
    const provider = document.getElementById('settingsProvider')?.value || 'openai';
    const model = document.getElementById('settingsModelName')?.value || '';

    if (!model) {
      toast('请先输入或选择要测试的模型名称', true);
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.textContent = '正在体检...';
    }
    if (diagCard) {
      diagCard.classList.remove('hidden', 'error');
      diagCard.innerHTML = '<p>正在发送测试请求，诊断接口连通性与网络延迟...</p>';
    }

    try {
      const res = await api('/settings/writing-model/test', {
        method: 'POST',
        body: JSON.stringify({ base_url: baseUrl, api_key: apiKey, provider, model })
      });

      if (diagCard) {
        diagCard.className = 'diagnostics-card';
        diagCard.innerHTML = `
          <strong>连通性测试通过</strong>
          <p>模型 <b>${res.model}</b> 响应正常，往返延迟 <b>${res.latency_ms}ms</b>。</p>
          <div class="diagnostics-step-list">
            ${(res.diagnostics || []).map(d => `
              <div class="diagnostics-step-item ${d.status}">
                <span>${d.label}</span>
                <span>正常</span>
              </div>
            `).join('')}
          </div>
        `;
      }
      const latencyPill = document.getElementById('activeModelLatencyPill');
      if (latencyPill) latencyPill.textContent = `${res.latency_ms}ms · 正常`;
      toast(`连接成功，往返延迟 ${res.latency_ms}ms`);
    } catch (e) {
      if (diagCard) {
        diagCard.className = 'diagnostics-card error';
        const details = e.details?.diagnostics || [];
        diagCard.innerHTML = `
          <strong class="diagnostics-error-title">连通测试失败</strong>
          <p class="diagnostics-error-copy">${e.message || '网络或鉴权错误'}</p>
          ${details.length ? `
            <div class="diagnostics-step-list">
              ${details.map(d => `
                <div class="diagnostics-step-item ${d.status}">
                  <span>${d.label}</span>
                  <small>${d.hint || ''}</small>
                </div>
              `).join('')}
            </div>
          ` : ''}
        `;
      }
      toast(e.message || '连通性测试失败', true);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '测试连通性';
      }
    }
  },

  async saveModel(form) {
    const submitBtn = document.getElementById('saveAndApplyModelBtn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '正在保存并启用...';
    }

    let writingApplied = false;
    let directionApplied = false;
    try {
      const formData = new FormData(form);
      const payload = {
        preset_id: this.activePresetId,
        api_key_env: this.cachedPresets.find(item => item.id === this.activePresetId)?.api_key_env || '',
        provider: formData.get('provider'),
        base_url: formData.get('base_url'),
        model: formData.get('model'),
        api_key: formData.get('api_key'),
        max_tokens: parseInt(formData.get('max_tokens') || '8192', 10),
        timeout: parseInt(formData.get('timeout') || '120', 10),
        reasoning_mode: formData.get('reasoning_mode') || 'balanced',
        input_cost_per_million: parseFloat(formData.get('input_cost_per_million') || '0'),
        output_cost_per_million: parseFloat(formData.get('output_cost_per_million') || '0'),
      };

      const scope = formData.get('apply_scope') || 'both';

      if (scope === 'both' || scope === 'writing') {
        await api('/settings/writing-model:activate', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        writingApplied = true;
      }

      if (scope === 'both' || scope === 'direction') {
        const requestProduction = async path => {
          const response = await fetch(`/production/api/v1/settings/direction-model${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const result = await response.json().catch(() => ({}));
          if (!response.ok || result.ok === false) {
            throw new Error(result.error?.message || `AA 制作模型服务返回 HTTP ${response.status}`);
          }
          return result.data || result;
        };
        try {
          await requestProduction(':activate');
          directionApplied = true;
        } catch (error) {
          if (writingApplied) {
            await this.loadAll();
            this.updateTopBarBadge(payload.model, true);
            throw new Error(`写作模型已测试并启用，但 AA 制作同步失败：${error.message}`);
          }
          throw error;
        }
      }

      await this.loadAll();
      if (writingApplied) this.updateTopBarBadge(payload.model, true);
      else await this.refreshTopBarBadge();
      const scopeLabel = writingApplied && directionApplied ? '写作与 AA 制作' : writingApplied ? '写作' : 'AA 制作';
      toast(`模型【${payload.model}】已通过测试，并启用于${scopeLabel}`);

      setTimeout(() => {
        this.close();
      }, 350);
    } catch (e) {
      toast(e.message || '保存模型设置失败', true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '保存并立即启用';
      }
    }
  },

  async refreshTopBarBadge() {
    try {
      const res = await api('/settings/writing-model');
      if (res?.model) {
        this.updateTopBarBadge(res.model.model, res.model.configured);
      }
    } catch (e) {}
  },

  updateTopBarBadge(modelName, configured) {
    const badge = document.getElementById('providerBadge');
    if (!badge) return;
    badge.classList.toggle('configured', Boolean(configured && modelName));
    badge.classList.toggle('unconfigured', !configured || !modelName);
    if (configured && modelName) {
      badge.textContent = '模型已连接';
      badge.title = '写作模型已连接；具体配置可在设置中查看';
    } else {
      badge.textContent = '未配置大模型';
      badge.title = '点击导航栏“设置”配置 API 模型';
    }
  },

  async inspectAa() {
    const input = document.getElementById('aaWorkspaceInput');
    const card = document.getElementById('aaEnvironmentCard');
    const adoptBtn = document.getElementById('adoptAaBtn');
    const raw = (input?.value || '').trim();

    if (card) {
      card.className = 'environment-status-card';
      card.innerHTML = '<p>正在检查 AzureArchive 路径与工作区有效性...</p>';
    }

    try {
      const resp = await fetch('/production/api/v1/settings/aa-environment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selection: raw })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error?.message || 'AA 环境探测失败');

      const result = data.data || data;
      if (card) {
        card.className = 'environment-status-card valid';
        card.innerHTML = `
          <strong class="environment-valid-title">检测到有效的 AzureArchive 制作环境</strong>
          <p>工作区路径: <code>${result.workspace_path || result.resolved_workspace || raw}</code></p>
          <small>结构完整: projects, saves, overrides, settings 就绪。</small>
        `;
      }
      if (adoptBtn) adoptBtn.disabled = false;
      toast('AA 制作环境检测通过');
    } catch (e) {
      if (card) {
        card.className = 'environment-status-card';
        card.innerHTML = `
          <strong class="environment-error-title">未检测到有效 AA 工作区</strong>
          <p>${e.message || '请确认目录是否存在且为标准的 AzureArchive data 结构'}</p>
        `;
      }
      if (adoptBtn) adoptBtn.disabled = true;
      toast(e.message || 'AA 检测失败', true);
    }
  },

  async adoptAa() {
    const input = document.getElementById('aaWorkspaceInput');
    const raw = (input?.value || '').trim();
    try {
      const resp = await fetch('/production/api/v1/settings/aa-workspace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ aa_data: raw })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) throw new Error(data.error?.message || '采用工作区失败');
      toast('已成功采用并绑定该 AzureArchive 制作工作区');
    } catch (e) {
      toast(e.message || '采用 AA 工作区失败', true);
    }
  },

  renderPreferences(prefs) {
    const tone = document.getElementById('prefWritingTone');
    const charWarn = document.getElementById('prefCharWarning');
    const pacing = document.getElementById('prefAaPacing');
    const maxChars = document.getElementById('prefMaxStageCharacters');

    if (tone && prefs.writing_tone) tone.value = prefs.writing_tone;
    if (charWarn && prefs.char_warning_threshold) charWarn.value = prefs.char_warning_threshold;
    if (pacing && prefs.aa_pacing_wait_ms) pacing.value = prefs.aa_pacing_wait_ms;
    if (maxChars && prefs.max_stage_characters) maxChars.value = prefs.max_stage_characters;
  },

  async savePreferences(form) {
    const formData = new FormData(form);
    const payload = {
      writing_tone: formData.get('writing_tone'),
      char_warning_threshold: parseInt(formData.get('char_warning_threshold') || '35', 10),
      aa_pacing_wait_ms: parseInt(formData.get('aa_pacing_wait_ms') || '2500', 10),
      max_stage_characters: parseInt(formData.get('max_stage_characters') || '4', 10),
    };

    try {
      await api('/settings/preferences', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      toast('创作与演出偏好已成功保存');
    } catch (e) {
      toast(e.message || '保存偏好设置失败', true);
    }
  },

  renderDiagnostics(diag) {
    const writingEl = document.getElementById('diagWritingPort');
    const prodEl = document.getElementById('diagProductionPort');
    const dpapiEl = document.getElementById('diagDpapiStatus');
    const corpusEl = document.getElementById('corpusRecordStatus');

    if (writingEl) writingEl.textContent = '本地写作数据 · 运行中';
    if (prodEl) {
      const ok = diag.production_service?.status === 'online';
      prodEl.textContent = ok ? 'AA 制作服务在线' : 'AA 制作服务离线';
      prodEl.classList.toggle('diagnostic-ok',ok);
      prodEl.classList.toggle('diagnostic-error',!ok);
    }
    if (dpapiEl) {
      dpapiEl.textContent = diag.writing_service?.dpapi_available ? '已启用本机加密' : '系统安全配置';
    }
    if (corpusEl) {
      corpusEl.textContent = diag.corpus_status?.available
        ? `已收录 ${diag.corpus_status.count} 条 BA 官方剧情演出对照记录。`
        : '官方演出语料库未就绪。';
    }
  },

  async exportBackup() {
    try {
      const button = document.getElementById('backupDataBtn');
      if (button) { button.disabled = true; button.textContent = '正在打包'; }
      const response = await fetch('/api/v1/settings/backups/export');
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error?.message || `备份服务返回 HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const disposition = response.headers.get('Content-Disposition') || '';
      a.download = disposition.match(/filename="([^"]+)"/)?.[1] || `halocue-writing-${new Date().toISOString().slice(0,10)}.halocue`;
      a.click();
      URL.revokeObjectURL(url);
      toast('作品、资料和版本已完整导出');
    } catch (e) {
      toast('导出备份失败: ' + e.message, true);
    } finally {
      const button = document.getElementById('backupDataBtn');
      if (button) { button.disabled = false; button.textContent = '导出作品备份'; }
    }
  },

  async inspectBackupFile(file) {
    if (!file) return;
    this.resetBackupRestore(false);
    if (!file.name.toLocaleLowerCase('zh-CN').endsWith('.halocue')) {
      toast('请选择 .halocue 写作备份文件', true);
      this.resetBackupRestore();
      return;
    }
    if (file.size > 96 * 1024 * 1024) {
      toast('备份文件超过当前版本支持的 96 MB', true);
      this.resetBackupRestore();
      return;
    }
    const preview = document.getElementById('backupRestorePreview');
    const title = document.getElementById('backupRestoreTitle');
    if (preview) preview.hidden = false;
    if (title) title.textContent = '正在校验备份';
    try {
      const contentBase64 = characterImportBase64(await file.arrayBuffer());
      const summary = await api('/settings/backups/inspect', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, content_base64: contentBase64 }),
      });
      this.selectedBackup = { filename: file.name, content_base64: contentBase64, summary };
      const created = summary.created_at ? new Date(summary.created_at).toLocaleString('zh-CN') : '时间未知';
      const size = (Number(summary.compressed_bytes || 0) / 1024 / 1024).toFixed(1);
      if (title) title.textContent = '备份已通过校验';
      const meta = document.getElementById('backupRestoreMeta');
      if (meta) meta.textContent = `${summary.work_count} 个作品 · ${size} MB · ${created}`;
      const confirm = document.getElementById('confirmBackupRestoreBtn');
      if (confirm) confirm.disabled = false;
    } catch (error) {
      this.selectedBackup = null;
      if (title) title.textContent = '备份无法恢复';
      const meta = document.getElementById('backupRestoreMeta');
      if (meta) meta.textContent = error.message;
      const confirm = document.getElementById('confirmBackupRestoreBtn');
      if (confirm) confirm.disabled = true;
      toast(error.message, true);
    }
  },

  resetBackupRestore(clearInput = true) {
    this.selectedBackup = null;
    const preview = document.getElementById('backupRestorePreview');
    if (preview) preview.hidden = true;
    if (clearInput) {
      const input = document.getElementById('restoreBackupFile');
      if (input) input.value = '';
    }
  },

  async restoreBackup() {
    const selected = this.selectedBackup;
    if (!selected) return;
    const button = document.getElementById('confirmBackupRestoreBtn');
    if (button) { button.disabled = true; button.textContent = '正在恢复'; }
    try {
      const result = await api('/settings/backups/restore', {
        method: 'POST',
        body: JSON.stringify({
          filename: selected.filename,
          content_base64: selected.content_base64,
          expected_backup_hash: selected.summary.backup_hash,
          replace_all_works: true,
        }),
      });
      toast(`已恢复 ${result.work_count} 个作品，正在重新载入`);
      setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      toast(error.message || '恢复备份失败', true);
      if (button) { button.disabled = false; button.textContent = '确认替换并恢复'; }
    }
  }
};

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', () => SettingsController.init());
} else {
  SettingsController.init();
}

/* Final work-agent presentation pass: one conversation surface, with the
   durable thread list kept beside it. The older workflow renderers remain
   available for the Writing surface, but never compete with Works. */
function workAgentThreadScope(thread){
  if(thread?.scope_type==='chapter'){
    const chapter=(state.work?.chapters||[]).find(item=>item.id===thread.scope_id);
    return chapter?`章节 · ${chapter.title}`:'章节讨论';
  }
  return '整部作品';
}

function workAgentThreadPreview(thread){
  const messages=thread?.messages||[];
  const last=[...messages].reverse().find(item=>messageText(item).trim());
  const text=messageText(last).replace(/\s+/g,' ').trim();
  return text||'还没有开始讨论';
}

function workAgentThreadTime(value){
  if(!value)return '刚刚';
  const time=new Date(value),seconds=Math.max(0,Math.floor((Date.now()-time.getTime())/1000));
  if(Number.isNaN(time.getTime()))return '';
  if(seconds<60)return '刚刚';
  if(seconds<3600)return `${Math.floor(seconds/60)} 分钟前`;
  if(seconds<86400)return `${Math.floor(seconds/3600)} 小时前`;
  if(seconds<604800)return `${Math.floor(seconds/86400)} 天前`;
  return `${time.getMonth()+1}月${time.getDate()}日`;
}

function workAgentRailStats(){
  const artifacts=state.work?.artifacts||[];
  const characterCount=artifacts.filter(item=>item.kind==='character_card'&&item.current_revision).length;
  const world=artifacts.find(item=>item.kind==='world_bible')?.current_revision?.content||{};
  const worldCount=(world.entities||[]).filter(item=>item.status!=='archived').length;
  const chapters=(state.work?.volumes||[]).flatMap(volume=>volume.chapters||[]);
  return {characterCount,worldCount,chapterCount:chapters.length};
}

function workAgentUserHeadline(harness={}){
  if(harness.outcome==='needs_user')return '有一份候选等待你的决定';
  if(harness.outcome==='blocked'&&harness.phase==='agent_recovery')return '本轮没有完成';
  return ({
    brief:'继续讨论故事方向',
    blueprint:'整理已经讨论清楚的方向',
    structure:'确认章节和场景安排',
    scene_draft:'继续当前章节写作',
    memory:'整理本场发生的变化',
    release_review:'检查并准备发布',
    released:'制作定稿已经准备好',
    agent_recovery:'继续未完成的对话',
    agent_running:'Agent 正在处理本轮消息',
    commit_projection:'恢复尚未整理完成的结果'
  })[harness.phase]||harness.headline||'继续当前创作';
}

function workAgentNextAction(){
  const harness=state.agentPresentation?.guidance||state.work?.harness,primary=harness?.primary_action;
  const pendingKnowledge=(state.work?.proposals||[]).find(item=>['character_card','world_card','world_entity','world_rule','canon_fact'].includes(item.kind)&&item.status==='pending');
  if(pendingKnowledge){
    return {kicker:'等待你的决定',title:'有一项创作资料等待确认',detail:'先查看内容和影响，再决定采用或退回。',reason:'未确认的资料不会进入章节写作上下文。',label:'审查资料候选',action:'data-agent-open-library="suggestions"'};
  }
  const pendingSceneProposal=(state.work?.proposals||[]).find(item=>item.kind==='scene_script'&&item.status==='pending');
  if(pendingSceneProposal){
    return {kicker:'等待你的决定',title:'有一份正文候选等待审查',detail:'在完整正文中查看改动，再决定采用或退回。',reason:'正文候选尚未写入，只有你的决定可以建立新版本。',label:'审查正文候选',action:`data-open-official-script="${esc(pendingSceneProposal.scope_id||'')}"`};
  }
  if(primary){
    if(primary.id==='agent.retry'&&primary.target_id&&agentRunHasRecoveryPresentation(primary.target_id)){
      return {kicker:'需要继续',title:'本轮没有完成',detail:'失败输入已保存，可以从对话中的恢复卡继续。',reason:'恢复卡是本轮唯一的重试入口，其他位置只负责带你回到失败详情。',label:'查看恢复卡',action:'data-agent-focus-recovery'};
    }
    const kicker={ready:'建议下一步',in_progress:'正在处理',needs_user:'等待你的决定',blocked:'需要先处理',completed:'写作已完成'}[harness.outcome]||'当前状态';
    const detail=(harness.blockers?.[0]?.message)||(harness.warnings||[]).find(item=>item.code!=='provider_simulation')?.message||{
      brief:'继续在当前对话补充、反悔或比较方向。',
      blueprint:'把讨论共识整理成正式方向候选。',
      structure:'进入章节工作区建立稳定结构。',
      scene_draft:'进入当前章节，继续逐场写作。',
      memory:'正文已经保存，长期事实仍需单独决定。',
      release_review:'审查必须覆盖当前正文与资料修订。',
      released:'制作定稿已生成，后续改稿不会覆盖它。',
      agent_recovery:'固定输入仍然完整，可以从失败位置继续。',
      agent_running:'本轮输入已持久化，可以离开当前页面。',
      commit_projection:'正式正文没有变化，只需补齐失败的摘要、检索或维护待办。'
    }[harness.phase]||'系统会保留已经可信完成的步骤。';
    let action='data-agent-focus-composer',label=primary.label;
    if(primary.id==='proposal.apply'){
      action=`data-agent-review-proposal="${esc(primary.target_id||'')}"`;
      label='查看待审修改';
    }
    else if(primary.id==='agent.retry'&&primary.target_id)action=`data-agent-retry-run="${esc(primary.target_id)}"`;
    else if(primary.id==='agent.inspect')action='data-agent-inspect-run';
    else if(primary.id==='projection.retry'&&primary.target_id)action=`data-projection-retry="${esc(primary.target_id)}"`;
    else if(primary.id==='blueprint.generate')action='data-organize-conversation';
    else if(['chapter.create','scene.create','scene.context.assemble','scene.draft.generate','memory.extract','memory.skip'].includes(primary.id)){action='data-section="writing"';label='打开章节写作'}
    else if(['continuity.review','release.review','release.freeze'].includes(primary.id)){action='data-stage-jump="release"';label='打开检查与发布'}
    else if(primary.id==='production.open')action='data-section="production"';
    return {kicker,title:workAgentUserHeadline(harness),detail,reason:harness.decision_basis||detail,label,action};
  }
  const thread=workConversationThread(),proposal=workPlanProposal(),messages=thread?.messages||[];
  if(proposal)return {kicker:'等待你的决定',title:proposal.kind==='story_structure'?'审查作品结构候选':'审查故事方向候选',detail:proposal.kind==='story_structure'?'卷、章和场景尚未建立；采纳后才会一次性写入。':'Agent 已整理出方案；采纳前不会改变正式资料。',reason:'存在待审 Proposal，正式资料在你决定前不会改变。',label:'查看候选',action:'data-agent-review-current'};
  if(!messages.length)return {kicker:'从这里开始',title:'告诉 Agent 你想写什么',detail:'一句想法就够了，人物、世界观和故事方向会在对话中逐步讨论。',reason:'当前还没有对话或已确认的创意简报，所以先从用户意图开始。',label:'开始讨论',action:'data-agent-focus-composer'};
  if(!brief())return {kicker:'建议下一步',title:'继续讨论，形成全作方案',detail:'想法仍可反悔或补充；觉得清楚后再让 Agent 整理。',reason:'对话已经存在，但创意简报还没有确认，继续讨论不会直接写入正式资料。',label:'继续讨论',action:'data-agent-focus-composer'};
  if(workAgentPendingOrganization(thread))return {kicker:'本轮讨论可整理',title:'生成方向修改候选',detail:'先把这轮讨论整理成 Proposal；采纳前不会覆盖已保存方向。',reason:'本轮讨论出现了新的可整理共识，先生成 Proposal 等你决定。',label:'整理修改',action:'data-organize-conversation'};
  if(!blueprintIsConfirmed())return {kicker:'建议下一步',title:'形成全作方向方案',detail:'把已经讨论清楚的内容整理成 Proposal，再决定是否采用。',reason:'创意简报已经确认，但 StoryBlueprint 还没有确认。',label:'形成方案',action:'data-organize-conversation'};
  const sceneCount=(state.work?.volumes||[]).reduce((total,volume)=>total+(volume.chapters||[]).reduce((chapterTotal,chapter)=>chapterTotal+(chapter.scenes||[]).length,0),0);
  if(!sceneCount)return {kicker:'方向已经确认',title:'整理卷、章与场景树',detail:'先让 Agent 给出结构候选；采纳前不会建立任何正式场景。',reason:'作品方向已确认，但还没有完整的可写章节或场景结构。',label:'整理作品结构',action:'data-organize-conversation'};
  return {kicker:'全作方向已保存',title:'进入章节写作',detail:'选择当前章节，继续讨论章内细纲、场景与正文。',reason:'作品方向和结构已经存在，下一步进入具体章节与场景范围。',label:'打开写作',action:'data-section="writing"'};
}

function activeWorkDecision({includeDismissed=false}={}){
  // A user may have several unresolved decisions, but the conversation gets
  // one bottom dock. Closing it must not immediately surface an older card.
  const isDismissed=key=>!includeDismissed&&(
    state.decisionCardDockClosed
    ||state.decisionCardWaitingForAgent
    ||state.decisionCardDismissedFor===key
  );
  const thread=workConversationThread();
  // A confirmed high-risk Intent can remain in `waiting_user` while its
  // generated Proposal waits for review. That status means "review the
  // result", not "ask for confirmation again". Only keep the confirmation
  // dock for plans that explicitly require confirmation and have not recorded
  // a completed user.confirm action.
  const intentNeedsConfirmation=item=>{
    if(!item?.requires_confirmation||!['awaiting_confirmation','waiting_user'].includes(item.status))return false;
    if(item.result?.confirmed===true)return false;
    return !(item.actions||[]).some(action=>action.id==='user.confirm'&&action.status==='completed');
  };
  const answeredDecisionIds=new Set((thread?.messages||[]).filter(item=>item.role==='user').map(item=>item.content?.decision_response?.message_id).filter(Boolean));
  const latestChoiceMessage=[...(thread?.messages||[])].reverse().find(item=>item.role==='assistant'&&item.content?.decision_card?.options?.length>=2&&!answeredDecisionIds.has(item.id));
  const latestChoiceAt=latestChoiceMessage?Date.parse(latestChoiceMessage.created_at||''):Number.NaN;
  const isOlderThanChoice=item=>{
    if(!item)return true;
    if(!latestChoiceMessage||Number.isNaN(latestChoiceAt))return false;
    const itemAt=Date.parse(item?.updated_at||item?.created_at||'');
    return !Number.isNaN(itemAt)&&itemAt<latestChoiceAt;
  };
  // Keep one clear primary action: a newer bounded choice from the current
  // conversation should be shown before stale confirmations or proposals.
  if(latestChoiceMessage && !isDismissed(`message:${latestChoiceMessage.id}`)){
    const pendingIntent=(state.work?.intent_plans||[]).find(intentNeedsConfirmation);
    const pendingKnowledge=(state.work?.proposals||[]).find(item=>['character_card','world_card','world_entity','world_rule','canon_fact'].includes(item.kind)&&item.status==='pending');
    const proposal=workPlanProposal();
    if(isOlderThanChoice(pendingIntent)&&isOlderThanChoice(pendingKnowledge)&&isOlderThanChoice(proposal)){
      const card=latestChoiceMessage.content.decision_card;
      return {key:`message:${latestChoiceMessage.id}`,kind:'choose',kicker:'需要你决定 · Agent',title:card.title,body:'',note:'选择后会作为一条普通讨论消息发送，正式内容仍需后续审查。',message:latestChoiceMessage,card};
    }
  }
  const pendingIntent=(state.work?.intent_plans||[]).find(intentNeedsConfirmation);
  if(pendingIntent){
    const decision={key:`intent:${pendingIntent.id}`,kind:'confirm',kicker:'需要你确认 · Agent 请求',title:'确认继续处理这项请求？',body:pendingIntent.original_message?`你的请求：${pendingIntent.original_message}`:'这项请求会先整理成候选，供你审查。',note:'确认后只会生成可审查候选；不会直接覆盖正文或发布。',pendingIntent};
    if(!isDismissed(decision.key))return decision;
  }
  const pendingKnowledge=(state.work?.proposals||[]).find(item=>['character_card','world_card','world_entity','world_rule','canon_fact'].includes(item.kind)&&item.status==='pending');
  if(pendingKnowledge){
    const candidate=pendingKnowledge.candidate||{},content=candidate.content||{};
    const kindLabel={character_card:'人物卡',world_card:'世界观卡',world_entity:'世界观卡',world_rule:'世界规则',canon_fact:'作品事实'}[pendingKnowledge.kind]||'创作资料';
    const text=content.text||content.summary||candidate.summary||candidate.title||'Agent 整理了一项创作资料。';
    const impact=candidate.impact_preview?.affected_consumers?.map(item=>item.label).filter(Boolean).slice(0,3)||[];
    const stale=state.staleProposalIds?.has(pendingKnowledge.id);
    const decision={key:`proposal:${pendingKnowledge.id}`,kind:'proposal',stale,kicker:stale?'候选已过期':`需要你决定 · ${kindLabel}`,title:stale?'这条资料候选需要重新整理':'要把这项内容加入作品资料吗？',body:stale?'当前作品的审查范围已经变化，这份候选不能直接采纳。请退回后让 Agent 按最新状态重新整理。':text,note:stale?'退回只会移除过期候选，不会改变已确认资料。':impact.length?`确认后会用于${impact.join('、')}。`:'确认后才会进入后续写作；退回不会改变已确认资料。',pendingProposal:pendingKnowledge,digest:candidate.impact_preview?.digest||''};
    if(!isDismissed(decision.key))return decision;
  }
  const proposal=workPlanProposal();
  if(proposal){
    const label=proposal.kind==='story_structure'?'作品结构候选':'故事方向候选';
    const decision={key:`proposal:${proposal.id}`,kind:'proposal',kicker:'需要你决定',title:`要采用这份${label}吗？`,body:'候选仍保留在上方对话中，采纳后才会建立正式版本。',note:'正式产物只会在你采纳后建立。',pendingProposal:proposal};
    if(!isDismissed(decision.key))return decision;
  }
  const message=latestChoiceMessage;
  if(message){
    const card=message.content.decision_card;
    const decision={key:`message:${message.id}`,kind:'choose',kicker:'需要你决定 · Agent',title:card.title,body:'',note:'选择后会作为一条普通讨论消息发送，正式内容仍需后续审查。',message,card};
    if(!isDismissed(decision.key))return decision;
  }
  return null;
}

function workDecisionCardDismissed(decision){
  return Boolean(decision&&(state.decisionCardDockClosed||state.decisionCardDismissedFor===decision.key));
}

function workDecisionReopenMarkup(){
  // A newer pending card owns the dock. Only expose the reopen affordance
  // when no other pending decision is currently visible.
  if(state.decisionCardWaitingForAgent)return '';
  const visible=activeWorkDecision();
  if(visible)return '';
  const decision=activeWorkDecision({includeDismissed:true});
  if(!decision||!workDecisionCardDismissed(decision))return '';
  return `<button type="button" class="decision-reopen" data-decision-reopen aria-label="重新打开待决定卡"><span aria-hidden="true">!</span><span>待决定</span></button>`;
}

function workDecisionDockMarkup(){
  const decision=activeWorkDecision();
  if(!decision||workDecisionCardDismissed(decision))return '';
  const close='<button type="button" class="decision-card-close" data-decision-dismiss aria-label="稍后处理">×</button>';
  if(decision.kind==='choose'){
    const selected=state.decisionCardSelections[decision.key]||decision.card.options[0]?.id||'';
    const options=decision.card.options.map((option,index)=>`<button type="button" class="decision-option ${selected===option.id?'selected':''}" role="radio" aria-checked="${selected===option.id}" tabindex="${selected===option.id?'0':'-1'}" data-decision-option="${esc(decision.key)}" data-option-id="${esc(option.id)}" data-option-label="${esc(option.label)}"><span class="decision-option-index">${index+1}</span><span class="decision-option-copy"><b>${esc(option.label)}</b>${option.description?`<small>${esc(option.description)}</small>`:''}</span><span class="decision-option-arrow" aria-hidden="true">→</span></button>`).join('');
    const customSelected=selected===DECISION_CUSTOM_OPTION_ID;
    const customDraft=state.decisionCardCustomDrafts[decision.key]||'';
    const custom=decision.card.allow_custom?`<div class="decision-custom-option ${customSelected?'selected':''}" data-decision-custom-wrap><button type="button" class="decision-option decision-custom-trigger ${customSelected?'selected':''}" role="radio" aria-checked="${customSelected}" aria-expanded="${customSelected}" tabindex="${customSelected?'0':'-1'}" data-decision-option="${esc(decision.key)}" data-option-id="${DECISION_CUSTOM_OPTION_ID}" data-option-label="其他想法"><span class="decision-option-index decision-option-pencil" aria-hidden="true">&#9998;</span><span class="decision-option-copy"><b>其他想法</b><small>直接告诉 Agent 你想怎样推进</small></span><span class="decision-option-arrow" aria-hidden="true">→</span></button><div class="decision-custom-field" ${customSelected?'':'hidden'}><input type="text" data-decision-custom maxlength="1000" value="${esc(customDraft)}" aria-label="输入其他想法" placeholder="写下你的想法，然后按 Enter 提交" autocomplete="off"></div></div>`:'';
    return `<section class="work-decision-dock decision-choice-dock" role="dialog" aria-label="${esc(decision.title)}" data-decision-key="${esc(decision.key)}"><header class="decision-card-head"><h3>${esc(decision.title)}</h3>${close}</header><div class="decision-options" role="radiogroup" aria-label="可选项">${options}${custom}</div><footer class="decision-card-footer decision-choice-footer"><button type="button" class="primary decision-submit" data-submit-decision="${esc(decision.key)}" ${customSelected&&!customDraft.trim()?'disabled':''}>${esc(decision.card.submit_label||'提交')}</button></footer></section>`;
  }
  const action=decision.kind==='confirm'?`<button type="button" class="primary" data-confirm-intent="${esc(decision.pendingIntent.id)}">确认继续</button>`:decision.stale?`<button type="button" class="primary" data-reject-director-proposal="${esc(decision.pendingProposal.id)}">退回并重新整理</button>`:`<button type="button" class="primary" data-accept-director-proposal="${esc(decision.pendingProposal.id)}" ${decision.digest?`data-impact-digest="${esc(decision.digest)}"`:''}>采纳</button><button type="button" class="quiet" data-reject-director-proposal="${esc(decision.pendingProposal.id)}">退回</button>`;
  return `<section class="work-decision-dock ${decision.kind==='confirm'?'intent-decision-dock':''}${decision.stale?' is-stale':''}" role="dialog" aria-label="${esc(decision.title)}" data-decision-key="${esc(decision.key)}"><header class="decision-card-head"><div><span class="work-decision-kicker">${esc(decision.kicker)}</span><h3>${esc(decision.title)}</h3></div>${close}</header><p class="work-decision-body">${esc(decision.body)}</p><footer class="decision-card-footer"><small>${esc(decision.note)}</small><div class="work-decision-actions">${action}</div></footer></section>`;
}

function focusWorkDecision(dock=document.querySelector('.work-decision-dock')){
  const target=dock?.querySelector('.decision-option[aria-checked="true"]')
    ||dock?.querySelector('[data-confirm-intent], [data-accept-director-proposal], [data-reject-director-proposal]')
    ||dock?.querySelector('[data-decision-dismiss]');
  target?.focus({preventScroll:true});
}

var workDecisionFocusTimer=0;
function scheduleWorkDecisionFocus(){
  clearTimeout(workDecisionFocusTimer);
  const focusIfUnclaimed=()=>{
    const active=document.activeElement;
    if(active===document.body||active===document.documentElement||active?.id==='bootScreen')focusWorkDecision();
  };
  requestAnimationFrame(focusIfUnclaimed);
  workDecisionFocusTimer=setTimeout(focusIfUnclaimed,160);
}

function renderWorkAgentThreadList(){
  const allThreads=(state.work?.conversation_threads||[]).filter(thread=>thread.scope_type!=='scene'),query=(state.threadRailQuery||'').trim().toLocaleLowerCase();
  const threads=allThreads.filter(item=>item.status==='active').filter(item=>!query||`${item.title||''} ${workAgentThreadPreview(item)}`.toLocaleLowerCase().includes(query));
  const selected=workConversationThread();
  const stats=workAgentRailStats();
  const workSwitchGlyphMarkup='<span class="rail-work-switch-glyph" aria-hidden="true"></span>';
  const tools=state.threadRailSearchOpen?`<div class="thread-rail-tools"><label class="thread-search"><span class="thread-search-glyph" aria-hidden="true"></span><input type="search" value="${esc(state.threadRailQuery||'')}" placeholder="搜索当前对话" aria-label="搜索当前对话" data-thread-search></label></div>`:'';
  return `<div class="work-agent-rail-shell ${state.threadRailSearchOpen?'search-open':'compact-tools'}"><section class="work-agent-rail-head"><div><p class="eyebrow">构思</p><h3>创作对话</h3></div><div class="rail-head-actions"><button type="button" class="rail-thread-search-toggle ${state.threadRailSearchOpen?'active':''}" data-thread-search-toggle title="${state.threadRailSearchOpen?'关闭搜索':'搜索对话'}" aria-label="${state.threadRailSearchOpen?'关闭搜索':'搜索对话'}" aria-pressed="${state.threadRailSearchOpen}"><span class="thread-search-glyph" aria-hidden="true"></span></button><button type="button" class="rail-new-thread" data-thread-create title="新建一段对话"><span aria-hidden="true">＋</span>新对话</button><button type="button" class="rail-close-thread" data-mobile-thread-toggle title="关闭对话列表" aria-label="关闭对话列表">×</button></div><nav class="rail-resource-links rail-resource-links-head" aria-label="作品快捷入口"><button type="button" data-agent-open-library="characters"><b>${stats.characterCount}</b><span>人物</span></button><button type="button" data-agent-open-library="world"><b>${stats.worldCount}</b><span>设定</span></button><button type="button" data-section="writing"><b>${stats.chapterCount}</b><span>章节</span></button></nav></section>${tools}<div class="work-agent-thread-list">${threads.map(thread=>{const active=thread.id===selected?.id,rename=state.renamingThreadId===thread.id;return `<div class="work-agent-thread-row ${active?'active':''}"><button type="button" class="work-agent-thread-select" data-thread-select="${esc(thread.id)}"><span class="thread-avatar">${esc((thread.title||'新').slice(0,1))}</span><span class="thread-copy"><span class="thread-title-line"><b>${esc(thread.title)}</b><time>${esc(workAgentThreadTime(thread.updated_at))}</time></span><small>${esc(workAgentThreadScope(thread))}</small></span></button><details class="thread-actions"><summary aria-label="打开“${esc(thread.title)}”的对话操作"><span class="thread-more-glyph" aria-hidden="true"></span></summary><div class="thread-action-popover"><header><b>${esc(thread.title)}</b><span>${esc(state.work?.title||'当前作品')}</span></header><button type="button" data-thread-rename="${esc(thread.id)}">重命名</button><button type="button" data-thread-archive="${esc(thread.id)}">归档</button></div></details>${rename?`<form class="thread-rename-form" data-thread-rename-form="${esc(thread.id)}"><input name="title" value="${esc(thread.title)}" maxlength="80" aria-label="对话名称"><button type="submit" class="quiet">保存</button><button type="button" class="quiet" data-thread-rename-cancel>取消</button></form>`:''}</div>`}).join('')||`<div class="thread-list-empty"><b>${query?'没有匹配的对话':'还没有创作对话'}</b><span>${query?'换一个关键词试试。':'新建对话后，每段讨论都会独立保存。'}</span></div>`}</div></div>`;
}

var agentRunPollTimer=0;
var workAgentScrollKey='';

function workAgentActiveRun(thread=workConversationThread()){
  if(!thread)return null;
  const active=(state.work?.agent_runs||[]).find(run=>['queued','running'].includes(run.status)&&run.policy?.thread_id===thread.id);
  if(active)return active;
  return (state.work?.agent_runs||[]).find(run=>run.id===state.activeAgentRunId&&['queued','running'].includes(run.status))||null;
}

function activeAgentRunMarkup(thread){
  const run=workAgentActiveRun(thread);
  if(!run)return'';
  return `<article class="conversation-message assistant agent-running-message" aria-live="polite"><div class="message-avatar" aria-hidden="true">HC</div><div class="message-column"><div class="message-role">HaloCue 创作导演</div><div class="agent-running-line"><span class="agent-thinking-indicator" aria-hidden="true"></span><b>正在思考</b><small>本轮输入已保存，可以离开页面</small></div></div></article>`;
}

async function refreshAfterAgentRun(run){
  if(!state.work)return;
  const terminal=run?.status||'failed';
  state.work=await api(`/works/${state.work.id}`);
  await refreshAgentPresentation();
  state.activeAgentRunId='';
  state.decisionCardWaitingForAgent=false;
  setBusy(terminal==='cancelled'?'本轮已取消':terminal==='failed'?'Agent 运行失败':'回应已保存');
  render();
  if(terminal==='cancelled')toast('已停止本轮生成，正式资料没有改变');
  if(terminal==='failed')toast(run?.failure?.message||'Agent 运行失败，可在消息中重试',true);
}

function scheduleAgentRunPoll(runId,delay=500){
  clearTimeout(agentRunPollTimer);
  if(!runId||!state.work)return;
  agentRunPollTimer=setTimeout(async()=>{
    try{
      const run=await api(`/works/${state.work.id}/agent-runs/${runId}`);
      if(['queued','running'].includes(run.status)){scheduleAgentRunPoll(runId,600);return;}
      await refreshAfterAgentRun(run);
    }catch(error){
      setBusy('正在恢复 Agent 状态');
      agentRunPollTimer=setTimeout(()=>scheduleAgentRunPoll(runId,0),1500);
    }
  },delay);
}

function composerImportMarkup(){
  if(!state.composerImportMode)return '';
  const label=state.composerImportMode==='aap_to_script'?'.aap 工程转剧本':'小说转剧本';
  const preview=state.composerImportPreview||{};
  const scenes=Number(preview.counts?.scenes||0),chapters=Number(preview.counts?.chapters||0);
  const summary=[chapters?`${chapters} 章`:'',scenes?`${scenes} 场`:''].filter(Boolean).join(' · ')||'等待 Agent 检查结构';
  const status=state.composerImportStatus==='failed'?'加入失败，可重试':state.composerImportStatus==='sent'?'已发送，等待 Agent':'已加入 Agent，尚未发送';
  return `<section class="composer-import-state ${state.composerImportStatus==='failed'?'is-error':''}" aria-live="polite"><span class="composer-import-mark" aria-hidden="true">↗</span><div><b>${esc(label)}</b><small>${esc(status)}${summary?` · ${esc(summary)}`:''}</small>${state.composerImportError?`<em>${esc(state.composerImportError)}</em>`:''}</div>${state.composerImportStatus==='failed'?'<button type="button" class="quiet" data-import-retry>重试加入</button>':''}</section>`;
}

function renderWorkAgentComposer(thread, task, proposal){
  const attachments=(state.work?.conversation_threads||[]).find(item=>item.id===thread?.id)?.attachments||[];
  const staged=(state.composerAttachmentIds||[]).map(id=>attachments.find(item=>item.id===id)).filter(Boolean);
  const activeRun=workAgentActiveRun(thread);
  const action=activeRun?`<div class="composer-running-actions"><button class="agent-stop-button" type="button" data-agent-cancel-run="${esc(activeRun.id)}" title="停止生成" aria-label="停止生成"><span aria-hidden="true"></span></button><button class="send-button" type="submit">转向</button></div>`:'<button class="send-button" type="submit">发送</button>';
  return `<form id="workConversationForm" class="conversation-composer work-agent-composer ${activeRun?'is-running':''}">${composerImportMarkup()}<div class="composer-attachments">${staged.map(composerAttachmentMarkup).join('')}</div><label><span class="sr-only">给创作导演发送消息</span><textarea name="text" required placeholder="${activeRun?'补充一条转向要求；提交后会停止当前轮并按新要求继续。':'告诉 Agent 你的想法，或要求它创建人物卡、世界规则和故事方向……'}">${esc(state.composerPrefill||'')}</textarea></label><div class="composer-actions"><div class="composer-tools"><button type="button" class="mobile-thread-trigger composer-thread-trigger" data-mobile-thread-toggle title="查看对话列表" aria-label="查看对话列表"><span class="thread-list-glyph" aria-hidden="true"></span></button><details class="attachment-menu"><summary title="添加附件" aria-label="添加附件">＋</summary><div class="attachment-popover"><button type="button" data-attachment-upload="image"><b>上传图片</b><span>PNG、JPEG、WebP、GIF · 5 MB</span></button><button type="button" data-attachment-upload="document"><b>上传文档</b><span>TXT、Markdown、PDF、DOCX · 10 MB</span></button><button type="button" data-open-import-dialog><b>导入小说 / AAP</b><span>先预览，再交给 Agent 转换</span></button></div></details>${renderPermissionMenu(thread)}${renderConversationAction(task,proposal)}${agentRuntimeBarMarkup(thread)}</div><input id="workAgentImageInput" type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden><input id="workAgentDocumentInput" type="file" accept=".txt,.md,.pdf,.docx,.aap,text/plain,text/markdown,application/pdf,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden>${action}</div></form>`;
}

function agentPresentationMarkup(){
  const presentation=state.agentPresentation;
  if(!presentation?.events?.length)return '';
  const events=presentation.events;
  const operational=events.filter(event=>!event.event_type.startsWith('message.')&&!['run.started','run.reasoning_summary','recovery.available'].includes(event.event_type));
  const tools=events.filter(event=>event.event_type.startsWith('tool.')).length;
  const thinking=events.filter(event=>event.event_type==='run.reasoning_summary').length;
  const pending=events.filter(event=>event.event_type==='proposal.presented'&&event.state==='waiting_user').length;
  if(!operational.length&&!tools&&!thinking)return '';
  const summary='可展开查看处理过程';
  const issue=presentation.integrity?.complete?'':' · 需要重新加载';
  const rows=events.filter(event=>event.event_type.startsWith('tool.')||event.event_type==='proposal.presented'||event.event_type.startsWith('run.')).slice(-8).map(event=>`<li><span>${esc(event.event_type.startsWith('tool.')?'工具':event.event_type==='proposal.presented'?'候选':'运行')}</span><b>${esc(event.summary||event.details?.tool_name||event.state)}</b><small>${esc(event.source_status)}</small></li>`).join('');
  return `<details class="agent-presentation-summary"><summary><span class="agent-presentation-dot" aria-hidden="true"></span><span><b>运行详情</b><small>${esc(summary)}${pending?` · ${pending} 项等待决定`:''}${issue}</small></span><em>查看</em></summary><div class="agent-presentation-body">${rows?`<ul>${rows}</ul>`:''}</div></details>`;
}

function intentPlansMarkup(){
  const visibleStatuses=new Set(['blocked','failed']);
  const plans=(state.work?.intent_plans||[]).filter(item=>visibleStatuses.has(item.status));
  if(!plans.length)return '';
  const heading=(status,discussionOnly)=>{
    if(discussionOnly&&status==='completed')return '已完成，可继续讨论';
    return ({awaiting_confirmation:'等待你的确认',running:'正在执行',waiting_user:'已交给创作导演',completed:'已完成，可继续写作',blocked:'需要补齐写作输入',failed:'执行失败，可重试',cancelled:'本轮已停止'})[status]||'执行计划';
  };
  const targetMarkup=(plan,historical=false)=>{
    const target=plan.target;
    if(!target?.scene_id)return '';
    const scene=scenes().find(item=>item.id===target.scene_id);
    if(!scene)return `<div class="intent-target is-stale"><b>目标已变化</b><span>原场景已不在当前作品结构中，请先检查当前章节结构，再决定新的写作位置。</span><button type="button" class="quiet" data-stage-jump="structure">打开章节结构</button></div>`;
    const chapter=(state.work?.chapters||[]).find(item=>item.id===scene.chapter_id);
    const stage=stageGate('draft').allowed?'draft':'structure';
    const href=`?section=writing&work_id=${encodeURIComponent(state.work.id)}&stage=${stage}&chapter_id=${encodeURIComponent(chapter?.id||scene.chapter_id)}&scene_id=${encodeURIComponent(scene.id)}`;
    const renamed=Boolean((target.chapter_title&&chapter?.title&&target.chapter_title!==chapter.title)||(target.scene_title&&target.scene_title!==scene.title));
    // Intent navigation has its own guarded handler. Do not also mark this
    // control as a generic scene button: the writing shell captures those
    // events before the intent handler can persist the chapter target.
    const actionLabel=historical?'查看原目标':target.discussion_only?'查看这一幕':'去写这一幕';
    return `<div class="intent-target${renamed?' is-renamed':''}"><b>目标</b><span>${esc(chapter?.title||target.chapter_title||'章节')} · ${esc(scene.title)}${renamed?'<small>标题已变化，仍按稳定场景 ID 定位</small>':''}</span><button type="button" class="quiet" data-intent-open-scene="${esc(scene.id)}" data-intent-target-href="${href}">${actionLabel}</button></div>`;
  };
  const cardMarkup=(plan,historical=false)=>{const discussionOnly=Boolean(plan.target?.discussion_only);const execution=plan.result?.intent_execution;const retryableScene=['blocked','failed'].includes(plan.status)&&plan.target?.surface==='scene'&&!discussionOnly;const retryButton=retryableScene?`<button type="button" class="primary" data-retry-intent="${esc(plan.id)}">重新检查并继续</button>`:'';const footer=plan.status==='awaiting_confirmation'?`<footer><small>确认后 Agent 才会继续；正式作品仍会先以候选形式出现。</small><button type="button" class="primary" data-confirm-intent="${esc(plan.id)}">确认继续</button></footer>`:plan.status==='blocked'?`<footer><small>${esc(execution?.message||'还缺少必要信息，暂时不能继续。')}</small>${retryButton}</footer>`:plan.status==='failed'?`<footer><small>这次没有完成，原始请求仍保留，可以重新检查。</small>${retryButton}</footer>`:discussionOnly?'<small>本轮只讨论，没有修改正式作品。</small>':'<small>已完成，可以继续聊天；正式修改仍需你审核。</small>';return `<article class="intent-plan-card ${plan.status}${historical?' is-historical':''}"><header><div><p class="eyebrow">${historical?'较早请求':'当前请求'}</p><h3>${historical?'较早请求 · ':''}${heading(plan.status,discussionOnly)}</h3></div><span>${plan.risk_level==='high'?'需要确认':'讨论'}</span></header><p class="intent-plan-original">${esc(plan.original_message)}</p>${targetMarkup(plan,historical)}${footer}</article>`};
  const primary=plans[0];
  const unresolvedStatuses=new Set(['awaiting_confirmation','running','waiting_user','blocked','failed']);
  const pendingOlder=plans.slice(1).filter(plan=>unresolvedStatuses.has(plan.status));
  const history=plans.slice(1).filter(plan=>!unresolvedStatuses.has(plan.status)).slice(0,3);
  const pendingMarkup=pendingOlder.length?`<section class="intent-pending-decisions" aria-label="较早的待处理决定"><header><b>较早的待处理决定</b><span>${pendingOlder.length} 条不会被最新请求覆盖</span></header>${pendingOlder.map(plan=>cardMarkup(plan,true)).join('')}</section>`:'';
  return `<section class="intent-plan-list" aria-label="自然语言执行计划">${cardMarkup(primary)}${pendingMarkup}${history.length?`<details class="intent-plan-history"><summary>查看较早对话 · ${history.length} 条</summary><div>${history.map(plan=>cardMarkup(plan,true)).join('')}</div></details>`:''}</section>`;
}

function agentRecoveryMarkup(){
  const event=[...(state.agentPresentation?.events||[])].reverse().find(item=>item.event_type==='recovery.available');
  if(!event)return '';
  const runId=event.refs?.agent_run_id||event.details?.target_id;
  if(!runId)return '';
  const guidance=state.agentPresentation?.guidance||state.work?.harness;
  const primary=guidance?.primary_action;
  if(primary?.id!=='agent.retry'||primary.target_id!==runId)return '';
  const run=(state.work?.agent_runs||[]).find(item=>item.id===runId);
  if(!agentFailureNeedsRecovery(run))return '';
  const resolvedByRetry=Boolean(run?.resolved_by_retry||event.details?.resolved_by_retry||event.refs?.resolved_by_retry);
  const recoveryPresented=Boolean(state.agentPresentation?.recovery_presented);
  const recoveryMarkup=resolvedByRetry||recoveryPresented?'':null;
  if(recoveryMarkup==='')return '';
  const view=agentFailureView(run?.failure||{});
  const action=view.action==='settings'?'<button type="button" class="quiet" data-action="settings">打开模型设置</button>':view.action==='reload'?'<button type="button" class="quiet" data-agent-reload-work>重新加载工作台</button>':`<button type="button" class="quiet" data-agent-retry-run="${esc(runId)}">重试本轮</button>`;
  return `<section class="agent-recovery-card" role="status"><span class="agent-recovery-mark" aria-hidden="true"></span><div><b>${esc(view.title==='模型调用失败'?'本轮没有完成':view.title)}</b><p>${esc(view.message||event.summary||'输入已经保存，可以从失败位置继续。')}</p><small>已确认的资料没有改动。</small></div>${action}</section>`;
}

function renderFinalWorkAgentSurface(){
  const thread=workConversationThread(),proposal=workPlanProposal(),task=conversationTaskContract(thread),messages=thread?.messages||[];
  const statusMarkup=workUserStatusMarkup();
  const decisionDock=workDecisionDockMarkup();
  const decisionReopen=workDecisionReopenMarkup();
  const intentMarkup=intentPlansMarkup();
  const decisionDockClass=decisionDock||intentMarkup?'has-decision-dock':'';
  const decisionReopenClass=decisionReopen&&!decisionDock&&!intentMarkup?'has-decision-reopen':'';
  return `<main class="work-agent-canvas ${decisionDockClass} ${decisionReopenClass}"><section class="work-agent-thread" data-work-discussion-scroll>${statusMarkup}${currentWorkArtifactMarkup()}${messages.length||statusMarkup?conversationHistoryMarkup(messages):'<div class="work-agent-empty"><span>HC</span><h3>从一个想法开始</h3><p>你可以补充、反悔或推翻前面的方向。Agent 会自己判断下一步应该讨论人物、世界观还是故事结构。</p><div><button type="button" data-agent-continue-draft="先复述你对这部作品的理解，并指出目前最关键的不确定项。">复述当前理解</button><button type="button" data-agent-continue-draft="检查目前还缺少哪些人物卡或世界观依据。">检查创作资料</button></div></div>'}${activeAgentRunMarkup(thread)}${workAgentProposalMarkup(proposal)}${agentPresentationMarkup()}</section><div class="work-agent-bottom">${decisionDock}${decisionReopen}${intentMarkup}${thread?renderWorkAgentComposer(thread,task,proposal):'<div class="notice">当前作品对话未能恢复。</div>'}</div></main>`;
}

function renderFinalWorkAgentRail(){
  const rail=$('#stageList'),tree=$('#sceneTree'),note=$('.work-surface-note');
  if(!rail)return;
  rail.className='work-agent-rail';rail.setAttribute('aria-label','作品对话列表');rail.innerHTML=`<li>${renderWorkAgentThreadList()}</li>`;
  tree?.replaceChildren();
  if(note){note.hidden=true;note.replaceChildren();}
}

function sceneMemoryProposal(scene){
  if(!scene?.current_revision_id)return null;
  return (state.work?.proposals||[]).find(item=>
    item.kind==='memory_bundle'
    && item.status==='pending'
    && item.scope_id===scene.id
    && item.candidate?.source_scene_revision_id===scene.current_revision_id
  )||null;
}

function sceneMemoryWorkItem(scene){
  if(!scene?.current_revision_id)return null;
  return [...(state.work?.runs||[]).flatMap(run=>run.work_items||[])].reverse().find(item=>
    item.type==='memory.extract'
    && item.scope_id===scene.id
    && item.input_refs?.scene_revision_id===scene.current_revision_id
  )||null;
}

function memoryKindLabel(kind){
  return ({
    episode_memory:'情节记忆',
    scene_state_snapshot:'场末状态',
    open_thread:'未决伏笔',
    decision_record:'创作决定'
  })[kind]||'长期记忆';
}

function memoryOperationLabel(operation){
  return ({create:'新增',update:'更新',retire:'结束'})[operation]||'变更';
}

function memoryScopeLabel(item,scene){
  if(item.scope_type==='scene')return item.scope_id===scene?.id?'本场':'其他场景';
  if(item.scope_type==='chapter')return item.scope_id===scene?.chapter_id?'本章':'其他章节';
  if(item.scope_type==='work')return '全作';
  if(item.scope_type==='character')return '人物';
  return '作品范围';
}

function sceneMemoryReviewMarkup(scene,proposal){
  const candidate=proposal?.candidate||{},items=Array.isArray(candidate.items)?candidate.items:[];
  return `<section class="scene-memory-review" aria-label="本场长期记忆候选">
    <header><div><p class="eyebrow">MEMORY PROPOSAL</p><h3>本场需要沉淀的变化</h3><p>${esc(candidate.summary||'Agent 已从当前正式正文中整理出长期记忆候选。')}</p></div><span>等待决定</span></header>
    <div class="scene-memory-items">${items.map(item=>`<label class="scene-memory-item">
      <input type="checkbox" data-memory-item="${esc(proposal.id)}" value="${esc(item.id)}" checked>
      <span class="memory-check" aria-hidden="true"></span>
      <span class="memory-copy"><span><b>${esc(item.title||memoryKindLabel(item.kind))}</b><em>${esc(memoryOperationLabel(item.operation))}</em></span><p>${esc(item.summary||'')}</p><small>${esc(memoryKindLabel(item.kind))} · ${esc(memoryScopeLabel(item,scene))} · 来源为当前场景修订</small></span>
    </label>`).join('')||'<p class="scene-memory-empty">本次没有返回可审查的记忆条目，请退回后重新运行。</p>'}</div>
    <footer><p>只会写入你选中的条目；未选条目不会成为正式记忆。</p><div class="artifact-decision-actions"><button class="primary" type="button" data-memory-proposal-accept="${esc(proposal.id)}">采用全部</button><button class="quiet" type="button" data-memory-proposal-accept="${esc(proposal.id)}" data-memory-partial>采用选中项</button><button class="quiet" type="button" data-memory-proposal-reject="${esc(proposal.id)}">退回</button></div></footer>
  </section>`;
}

function decorateSceneMemoryAction(){
  if(state.stage!=='draft'||state.surface!=='writing')return;
  const scene=selectedScene();
  // The continuous chapter surface replaced the legacy scene-workbench. Keep
  // memory maintenance attached to the active scene's next-step bar so the
  // release gate never points to a control that is missing from the page.
  const sceneSurface=document.querySelector('.chapter-manuscript-scene.is-current, .scene-workbench');
  const actions=sceneSurface?.querySelector('.command-actions');
  if(!scene?.current_revision_id||!actions)return;
  const pending=sceneMemoryProposal(scene),workItem=sceneMemoryWorkItem(scene);
  const existing=actions.querySelector('[data-scene-memory]');
  if(existing){
    if(pending&&!sceneSurface.querySelector('.scene-memory-review')){
      sceneSurface.querySelector('.next-command')?.insertAdjacentHTML('afterend',sceneMemoryReviewMarkup(scene,pending));
    }
    return;
  }
  const finished=['succeeded','skipped'].includes(workItem?.status);
  const running=workItem?.status==='running';
  const button=document.createElement('button');
  button.type='button';button.className=`quiet scene-memory-action ${finished?'is-complete':''}`;button.dataset.sceneMemory=scene.id;
  button.textContent=pending?'审查记忆候选':running?'正在沉淀…':workItem?.status==='skipped'?'本场已确认无需沉淀':workItem?.status==='succeeded'?'本场记忆已沉淀':'沉淀本场变化';
  button.title=pending?'审查 Agent 从当前正式正文中提出的长期记忆':finished?'当前正文修订的长期记忆维护已完成':'从当前正式正文提取情节、状态、伏笔和创作决定';
  if(running||finished)button.disabled=true;
  actions.append(button);
  if(!pending&&!running&&!finished){
    const more=document.createElement('details');
    more.className='scene-memory-more';
    more.innerHTML='<summary title="更多记忆操作" aria-label="更多记忆操作">更多</summary><div><b>本场没有新增信息？</b><p>明确跳过后，发布审查会把这次决定与当前正文修订一起保存。</p><button type="button" data-scene-memory-skip>确认本场无需沉淀</button></div>';
    actions.append(more);
  }
  if(pending){
    if(!sceneSurface.querySelector('.scene-memory-review')){
      const command=sceneSurface.querySelector('.next-command');
      command?.insertAdjacentHTML('afterend',sceneMemoryReviewMarkup(scene,pending));
    }
  }
}

const renderBeforeFinalWorkAgentLayout=render;
render=function(){
  renderBeforeFinalWorkAgentLayout();
  // A scene Agent run can outlive this document (refresh/restart). Resume
  // polling from the durable Scene-scoped run instead of leaving the panel
  // stuck on its last "正在思考" state.
  if(state.work&&state.stage==='draft'&&state.sceneId){
    const scene=selectedScene(),thread=sceneConversationThread(scene),activeRun=thread?workAgentActiveRun(thread):null;
    if(activeRun)scheduleAgentRunPoll(activeRun.id);
  }
  const active=Boolean(state.work&&state.surface==='works'&&state.mobileView==='writing'&&state.stage==='overview');
  $('#app')?.classList.toggle('work-agent-expanded',active&&state.workAgentExpanded);
  $('#app')?.classList.toggle('mobile-thread-open',active&&state.mobileThreadOpen);
  const note=$('.work-surface-note');
  if(note)note.hidden=!state.work||active;
  decorateSceneMemoryAction();
  if(!active){workAgentScrollKey='';return;}
  renderFinalWorkAgentRail();
  const workspace=$('#workspace');if(workspace){
    const previousScrollTop=workspace.querySelector('[data-work-discussion-scroll]')?.scrollTop||0;
    const thread=workConversationThread(),messages=thread?.messages||[],lastMessage=messages.at(-1);
    const nextScrollKey=`${thread?.id||'missing'}:${messages.length}:${lastMessage?.id||lastMessage?.created_at||'empty'}`;
    const showLatest=nextScrollKey!==workAgentScrollKey;
    workspace.innerHTML=renderFinalWorkAgentSurface();
    const decision=activeWorkDecision();
    const decisionOpen=Boolean(decision&&!workDecisionCardDismissed(decision));
    const composer=workspace.querySelector('#workConversationForm');
    if(composer){
      if(decisionOpen)composer.setAttribute('inert','');
      else composer.removeAttribute('inert');
    }
    if(decisionOpen)scheduleWorkDecisionFocus();
    workspace.querySelectorAll('[data-intent-open-scene]').forEach(button=>button.addEventListener('click',event=>{
      if(button.tagName!=='BUTTON')return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void openIntentTarget(button);
    }));
    window.requestAnimationFrame(()=>{
      const scroll=workspace.querySelector('[data-work-discussion-scroll]');
      if(!scroll)return;
      if(showLatest){workspace.scrollTo({top:workspace.scrollHeight,behavior:'auto'});scroll.scrollTop=scroll.scrollHeight;}
      else scroll.scrollTop=Math.min(previousScrollTop,Math.max(0,scroll.scrollHeight-scroll.clientHeight));
    });
    workAgentScrollKey=nextScrollKey;
  }
  setCrumb(state.work,workConversationThread()?.title||'作品 Agent');
  const activeRun=workAgentActiveRun();if(activeRun)scheduleAgentRunPoll(activeRun.id);
};

async function submitWorkDecision(button){
  const decision=activeWorkDecision();
  if(!decision||decision.kind!=='choose'||state.decisionCardSubmitting)return;
  const optionId=state.decisionCardSelections[decision.key]||decision.card.options[0]?.id||'';
  const customSelected=decision.card.allow_custom&&optionId===DECISION_CUSTOM_OPTION_ID;
  const option=customSelected?{id:DECISION_CUSTOM_OPTION_ID,label:'其他想法'}:decision.card.options.find(item=>item.id===optionId);
  if(!option)return;
  const customInput=document.querySelector(`[data-decision-key="${CSS.escape(decision.key)}"] [data-decision-custom]`);
  const customText=customSelected?customInput?.value.trim()||'':'';
  if(customSelected&&!customText){
    customInput?.setAttribute('aria-invalid','true');
    customInput?.focus({preventScroll:true});
    return;
  }
  const thread=workConversationThread();
  if(!thread||!state.work)return;
  state.decisionCardSubmitting=true;
  button.disabled=true;
  document.querySelectorAll(`[data-decision-key="${CSS.escape(decision.key)}"] button`).forEach(item=>item.disabled=true);
  try{
    setBusy('正在保存你的选择');
    const text=customSelected?customText:option.label;
    const result=await api(`/works/${state.work.id}/threads/${thread.id}/messages:enqueue`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,text,attachment_ids:state.composerAttachmentIds||[],task_scope:agentTaskScope(),decision_response:{message_id:decision.message.id,option_id:option.id,label:option.label,...(customText?{custom_text:customText}:{})}})});
    state.work=result.work;
    state.activeAgentRunId=result.agent_run_id;
    state.composerAttachmentIds=[];
    delete state.decisionCardCustomDrafts[decision.key];
    state.decisionCardDismissedFor=decision.key;
    state.decisionCardDockClosed=false;
    state.decisionCardWaitingForAgent=Boolean(result.agent_run_id);
    state.decisionCardSubmitting=false;
    setBusy('Agent 正在思考');
    render();
    scheduleAgentRunPoll(result.agent_run_id,0);
  }catch(error){
    state.decisionCardSubmitting=false;
    state.decisionCardWaitingForAgent=false;
    setBusy('选择尚未提交');
    toast(error.message,true);
    render();
  }
}

document.addEventListener('click',event=>{
  const statusAction=event.target.closest('[data-user-status-action]');
  if(statusAction&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const action=statusAction.dataset.userStatusAction,target=statusAction.dataset.userStatusTarget||'agent';
    if(action==='review_knowledge'){
      state.stage='references';state.mobileView='writing';state.libraryView='suggestions';state.libraryEditorOpen=false;
    }else if(action==='review_scene_candidate'||action==='review_memory'||action==='review_blockers'||action==='continue_draft'){
      const pendingScene=(state.work.proposals||[]).find(item=>item.status==='pending'&&item.kind==='scene_script'&&item.scope_id);
      const pendingMemory=(state.work.proposals||[]).find(item=>item.status==='pending'&&item.kind==='memory_bundle'&&item.scope_id);
      const blockingScene=(state.work.review_findings||[]).find(item=>item.status==='open'&&item.severity==='blocking'&&item.scene_id);
      const targetScene=action==='review_scene_candidate'?pendingScene?.scope_id:action==='review_memory'?pendingMemory?.scope_id:blockingScene?.scene_id;
      if(targetScene){const match=scenes().find(scene=>scene.id===targetScene);if(match){state.sceneId=match.id;state.writingChapterId=match.chapter_id}}
      state.surface='writing';state.mobileView='writing';state.stage='draft';state.inspector='decision';
    }else if(action==='review_structure'){
      state.surface='writing';state.mobileView='writing';state.stage='structure';state.inspector='decision';
    }else if(action==='review_direction'||action==='review_pending'){
      state.surface='works';state.mobileView='writing';state.stage='overview';state.inspector='agent';
    }else if(action==='review_release'){
      state.surface='writing';state.mobileView='writing';state.stage='release';state.inspector='decision';
    }else if(action==='build_structure'){
      state.surface='writing';state.mobileView='writing';state.stage='structure';state.inspector='decision';
    }else if(action==='start_idea'||action==='confirm_direction'||action==='organize_conversation'||action==='recover_run'||action==='continue_discussion'){
      state.surface='works';state.mobileView='writing';state.stage='overview';state.inspector='agent';
    }else if(target==='draft'){
      state.surface='writing';state.mobileView='writing';state.stage='draft';
    }
    render();
    if(action==='organize_conversation'||action==='start_idea')requestAnimationFrame(()=>document.querySelector('#workConversationForm textarea')?.focus());
    return;
  }
  const intentTarget=event.target.closest('[data-intent-open-scene]');
  if(intentTarget&&intentTarget.tagName==='BUTTON'&&state.work){event.preventDefault();event.stopImmediatePropagation();void openIntentTarget(intentTarget);return;}
  const decisionDismiss=event.target.closest('[data-decision-dismiss]');
  if(decisionDismiss&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    state.decisionCardDismissedFor=decisionDismiss.closest('[data-decision-key]')?.dataset.decisionKey||'';
    state.decisionCardDockClosed=true;
    render();
    requestAnimationFrame(()=>document.querySelector('#workConversationForm textarea')?.focus());
    return;
  }
  const decisionReopen=event.target.closest('[data-decision-reopen]');
  if(decisionReopen&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    state.decisionCardDismissedFor='';
    state.decisionCardDockClosed=false;
    render();
    requestAnimationFrame(()=>focusWorkDecision());
    return;
  }
  const decisionOption=event.target.closest('[data-decision-option]');
  if(decisionOption&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const key=decisionOption.dataset.decisionOption||'',optionId=decisionOption.dataset.optionId||'';
    state.decisionCardSelections[key]=optionId;
    const dock=decisionOption.closest('.work-decision-dock');
    dock?.querySelectorAll(`[data-decision-option="${CSS.escape(key)}"]`).forEach(item=>{
      const selected=item.dataset.optionId===optionId;
      item.classList.toggle('selected',selected);
      item.setAttribute('aria-checked',String(selected));
      item.tabIndex=selected?0:-1;
    });
    const customSelected=optionId===DECISION_CUSTOM_OPTION_ID;
    const customWrap=dock?.querySelector('[data-decision-custom-wrap]');
    const customField=customWrap?.querySelector('.decision-custom-field');
    const customInput=customWrap?.querySelector('[data-decision-custom]');
    customWrap?.classList.toggle('selected',customSelected);
    customWrap?.querySelector('[data-decision-option]')?.setAttribute('aria-expanded',String(customSelected));
    if(customField)customField.hidden=!customSelected;
    const submit=dock?.querySelector('[data-submit-decision]');
    if(submit)submit.disabled=customSelected&&!customInput?.value.trim();
    if(customSelected)requestAnimationFrame(()=>customInput?.focus({preventScroll:true}));
    else decisionOption.focus({preventScroll:true});
    return;
  }
  const decisionSubmit=event.target.closest('[data-submit-decision]');
  if(decisionSubmit&&state.work){event.preventDefault();event.stopImmediatePropagation();void submitWorkDecision(decisionSubmit);return;}
  const confirmIntent=event.target.closest('[data-confirm-intent]');
  if(confirmIntent&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const dialog=$('#agentIntentConfirmDialog');
    const dock=confirmIntent.closest('.work-decision-dock');
    const card=confirmIntent.closest('.intent-plan-card') || dock;
    const title=card?.querySelector('h3')?.textContent?.trim()||'确认继续这条请求';
    const request=card?.querySelector('.intent-plan-original, .work-decision-body')?.textContent?.trim()||'确认后 Agent 才会继续处理这条固定请求。';
    const titleNode=dialog?.querySelector('[data-agent-confirm-title]');
    const summaryNode=dialog?.querySelector('[data-agent-confirm-summary]');
    const originalNode=dialog?.querySelector('[data-agent-confirm-original]');
    const originalDetails=dialog?.querySelector('.agent-confirm-original-details');
    const submit=dialog?.querySelector('[data-agent-confirm-submit]');
    if(!dialog||typeof dialog.showModal!=='function'){
      confirmIntent.disabled=true;void confirmIntentPlan(confirmIntent.dataset.confirmIntent,confirmIntent);return;
    }
    if(titleNode)titleNode.textContent=title;
    if(summaryNode)summaryNode.textContent='确认后 Agent 才会继续；正式作品仍会先以候选形式出现。';
    if(originalNode)originalNode.textContent=request;
    if(originalDetails)originalDetails.open=false;
    if(submit){
      submit.disabled=false;
      submit.onclick=()=>{submit.disabled=true;dialog.close('confirm');confirmIntent.disabled=true;void confirmIntentPlan(confirmIntent.dataset.confirmIntent,submit)};
    }
    setIntentDialogAccessibility(true,confirmIntent);
    dialog.showModal();
    return;
  }
  const retryIntent=event.target.closest('[data-retry-intent]');
  if(retryIntent&&state.work){event.preventDefault();event.stopImmediatePropagation();retryIntent.disabled=true;(async()=>{try{setBusy('正在用固定原始消息重新检查场景输入');const result=await api(`/intent-plans/${retryIntent.dataset.retryIntent}:retry`,{method:'POST',body:JSON.stringify({expected_version:state.work.version})});state.work=result.work;toast(result.status==='waiting_user'?'已生成新的场景候选，等待审查':'已重新检查当前场景输入');render()}catch(error){retryIntent.disabled=false;setBusy('场景计划仍未能继续');toast(error.message,true)}})();return;}
  const memory=event.target.closest('[data-scene-memory]');
  if(memory&&state.work){event.preventDefault();event.stopImmediatePropagation();const scene=selectedScene(),pending=sceneMemoryProposal(scene);if(!scene)return;if(pending){document.querySelector('.scene-memory-review')?.scrollIntoView({behavior:'smooth',block:'center'});return;}(async()=>{try{memory.disabled=true;setBusy('Agent 正在沉淀本场变化');await runDurableAgentJob('memory.extract',scene.id,{expected_version:state.work.version});toast('已生成记忆候选，等待你审核');render()}catch(error){memory.disabled=false;setBusy('长期记忆提取失败');toast(error.message,true)}})();return;}
  const skipMemory=event.target.closest('[data-scene-memory-skip]');
  if(skipMemory&&state.work){event.preventDefault();event.stopImmediatePropagation();const scene=selectedScene();if(!scene)return;(async()=>{try{skipMemory.disabled=true;setBusy('正在记录本场记忆决定');const result=await api(`/works/${state.work.id}/scenes/${scene.id}/memory:skip`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:'用户在场景工作台确认：本场没有需要沉淀的长期记忆。'})});state.work=result.work;toast('已记录本场无需沉淀，发布审查会保留这次决定');render()}catch(error){skipMemory.disabled=false;setBusy('未能记录本场决定');toast(error.message,true)}})();return;}
  const acceptMemory=event.target.closest('[data-memory-proposal-accept]'),rejectMemory=event.target.closest('[data-memory-proposal-reject]');
  if((acceptMemory||rejectMemory)&&state.work){event.preventDefault();event.stopImmediatePropagation();const button=acceptMemory||rejectMemory,proposalId=button.dataset.memoryProposalAccept||button.dataset.memoryProposalReject,partial=Boolean(acceptMemory?.hasAttribute('data-memory-partial'));const selectedIds=[...document.querySelectorAll(`[data-memory-item="${CSS.escape(proposalId)}"]:checked`)].map(input=>input.value);if(acceptMemory&&!selectedIds.length){toast('请至少选择一条需要沉淀的记忆。',true);return;}(async()=>{try{button.disabled=true;setBusy(acceptMemory?'正在保存长期记忆':'正在退回记忆候选');const result=await api(`/works/${state.work.id}/proposals/${proposalId}/${acceptMemory?'accept':'reject'}`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:acceptMemory?(partial?'采用选中的长期记忆':'采用本场全部长期记忆'):'退回本场长期记忆候选',...(acceptMemory?{selected_item_ids:selectedIds}:{})})});state.work=result.work;toast(acceptMemory?(selectedIds.length===document.querySelectorAll(`[data-memory-item="${CSS.escape(proposalId)}"]`).length?'本场长期记忆已保存':'选中的长期记忆已保存'):'记忆候选已退回，正式记忆没有改变');render()}catch(error){button.disabled=false;setBusy('记忆候选尚未处理');toast(error.message,true)}})();return;}
  const stop=event.target.closest('[data-agent-cancel-run]');
  if(stop&&state.work){event.preventDefault();event.stopImmediatePropagation();stop.disabled=true;(async()=>{try{const run=await api(`/works/${state.work.id}/agent-runs/${stop.dataset.agentCancelRun}:cancel`,{method:'POST',body:'{}'});await refreshAfterAgentRun(run)}catch(error){stop.disabled=false;toast(error.message,true)}})();return;}
  const searchToggle=event.target.closest('[data-thread-search-toggle]');
  if(searchToggle){event.preventDefault();event.stopImmediatePropagation();state.threadRailSearchOpen=!state.threadRailSearchOpen;if(!state.threadRailSearchOpen)state.threadRailQuery='';renderFinalWorkAgentRail();if(state.threadRailSearchOpen)setTimeout(()=>document.querySelector('[data-thread-search]')?.focus(),0);return;}
  const select=event.target.closest('[data-thread-select]');
  if(select&&state.work){event.preventDefault();event.stopImmediatePropagation();state.conversationThreadId=select.dataset.threadSelect;state.renamingThreadId='';state.mobileThreadOpen=false;state.agentPresentation=null;render();refreshAgentPresentation().then(render);return;}
  const create=event.target.closest('[data-thread-create]');
  if(create&&state.work){event.preventDefault();event.stopImmediatePropagation();(async()=>{try{const result=await api(`/works/${state.work.id}/threads`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,title:'新对话',scope_type:'work'})});state.work=result.work;state.conversationThreadId=result.thread_id;await refreshAgentPresentation();toast('已建立新的作品讨论');render();}catch(error){toast(error.message,true)}})();return;}
  const rename=event.target.closest('[data-thread-rename]');
  if(rename){event.preventDefault();event.stopImmediatePropagation();state.renamingThreadId=rename.dataset.threadRename;render();setTimeout(()=>document.querySelector(`[data-thread-rename-form="${rename.dataset.threadRename}"] input`)?.focus(),0);return;}
  const cancel=event.target.closest('[data-thread-rename-cancel]');
  if(cancel){event.preventDefault();event.stopImmediatePropagation();state.renamingThreadId='';render();return;}
  const archive=event.target.closest('[data-thread-archive]');
  if(archive&&state.work){event.preventDefault();event.stopImmediatePropagation();const thread=(state.work.conversation_threads||[]).find(item=>item.id===archive.dataset.threadArchive);if(!thread)return;(async()=>{try{const result=await api(`/works/${state.work.id}/threads/${thread.id}`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,status:'archived'})});state.work=result.work;state.conversationThreadId='';toast('对话已归档，可在设置的“对话管理”中恢复');render();}catch(error){toast(error.message,true)}})();return;}
  const focusComposer=event.target.closest('[data-agent-focus-composer]');
  if(focusComposer){event.preventDefault();event.stopImmediatePropagation();document.querySelector('#workConversationForm textarea')?.focus();return;}
  const inspectRun=event.target.closest('[data-agent-inspect-run]');
  if(inspectRun){event.preventDefault();event.stopImmediatePropagation();document.querySelector('.agent-running-message')?.scrollIntoView({block:'center'});return;}
  const projectionRetry=event.target.closest('[data-projection-retry]');
  if(projectionRetry&&state.work){event.preventDefault();event.stopImmediatePropagation();projectionRetry.disabled=true;(async()=>{try{setBusy('正在补齐正文派生数据');await api(`/works/${state.work.id}/commit-projections/${projectionRetry.dataset.projectionRetry}:retry`,{method:'POST',body:'{}'});state.work=await api(`/works/${state.work.id}`);setBusy('正文派生数据已同步');toast('已只补跑未完成项');render()}catch(error){projectionRetry.disabled=false;setBusy('派生数据仍有未完成项');toast(error.message,true)}})();return;}
  const reviewCurrent=event.target.closest('[data-agent-review-current]');
  if(reviewCurrent){event.preventDefault();event.stopImmediatePropagation();document.querySelector('.proposal-message')?.scrollIntoView({block:'center'});return;}
  const reviewProposal=event.target.closest('[data-agent-review-proposal]');
  if(reviewProposal){
    event.preventDefault();event.stopImmediatePropagation();
    const proposalId=reviewProposal.dataset.agentReviewProposal||'';
    const selector=CSS.escape(proposalId);
    const target=document.querySelector(`[data-proposal-card="${selector}"]`)||document.querySelector(`[data-accept-director-proposal="${selector}"]`)?.closest('.proposal');
    if(!target){toast('待审修改尚未出现在当前对话，请重新打开来源对话。',true);return;}
    if(target.matches('details'))target.open=true;
    target.classList.add('work-guide-target');
    target.scrollIntoView({behavior:'smooth',block:'center'});
    setTimeout(()=>target.querySelector('button:not([disabled])')?.focus({preventScroll:true}),180);
    setTimeout(()=>target.classList.remove('work-guide-target'),1400);
    return;
  }
  const expand=event.target.closest('[data-work-agent-expand]');
  if(expand){event.preventDefault();event.stopImmediatePropagation();state.workAgentExpanded=!state.workAgentExpanded;render();return;}
  const mobileThreads=event.target.closest('[data-mobile-thread-toggle]');
  if(mobileThreads){event.preventDefault();event.stopImmediatePropagation();state.mobileThreadOpen=!state.mobileThreadOpen;render();return;}
  const remove=event.target.closest('[data-composer-attachment-remove]');
  if(remove){event.preventDefault();event.stopImmediatePropagation();state.composerAttachmentIds=(state.composerAttachmentIds||[]).filter(id=>id!==remove.dataset.composerAttachmentRemove);render();return;}
  const upload=event.target.closest('[data-attachment-upload]');
  if(upload){event.preventDefault();event.stopImmediatePropagation();if((state.composerAttachmentIds||[]).length>=4){toast('每条消息最多附带 4 个附件',true);return;}document.querySelector(upload.dataset.attachmentUpload==='document'?'#workAgentDocumentInput':'#workAgentImageInput')?.click();return;}
},true);

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-agent-focus-recovery]');
  if(!button)return;
  event.preventDefault();event.stopImmediatePropagation();
  const card=document.querySelector('.agent-recovery-card');
  if(card){card.scrollIntoView({behavior:'smooth',block:'center'});card.querySelector('button')?.focus();}
},true);

document.addEventListener('click',event=>{
  document.querySelectorAll('.thread-actions[open]').forEach(menu=>{
    if(!menu.contains(event.target))menu.removeAttribute('open');
  });
});

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  const searchInput=event.target.closest?.('[data-thread-search]');
  if(searchInput&&state.threadRailSearchOpen){
    event.preventDefault();
    state.threadRailSearchOpen=false;
    state.threadRailQuery='';
    renderFinalWorkAgentRail();
    setTimeout(()=>document.querySelector('[data-thread-search-toggle]')?.focus(),0);
    return;
  }
  document.querySelectorAll('.thread-actions[open]').forEach(menu=>menu.removeAttribute('open'));
});

const renderReleaseBeforeMemoryGuidance=renderRelease;

function shortDigest(value){
  const digest=String(value||'').replace(/^sha256:/,'');
  return digest?`${digest.slice(0,12)}...${digest.slice(-8)}`:'未记录';
}

function requestReleaseDetails(){
  const workId=state.work?.id;
  for(const release of state.work?.releases||[]){
    if(state.releaseDetails[release.id]||state.releaseDetailLoading[release.id]||state.releaseDetailErrors[release.id])continue;
    state.releaseDetailLoading[release.id]=true;
    api(`/releases/${release.id}`).then(detail=>{
      if(state.work?.id===workId)state.releaseDetails[release.id]=detail;
    }).catch(error=>{
      if(state.work?.id===workId)state.releaseDetailErrors[release.id]={code:error.code||'release_read_failed',message:error.message};
    }).finally(()=>{
      delete state.releaseDetailLoading[release.id];
      if(state.work?.id===workId&&state.stage==='release')render();
    });
  }
}

function decorateReleaseIntegrity(el){
  const cards=[...el.querySelectorAll('.artifact')];
  for(const [index,release] of (state.work?.releases||[]).entries()){
    const card=cards[index];
    if(!card||card.querySelector('.release-integrity-summary'))continue;
    const detail=state.releaseDetails[release.id],error=state.releaseDetailErrors[release.id];
    const surface=document.createElement('section');
    surface.className=`release-integrity-summary ${error?'has-error':detail?'is-verified':'is-loading'}`;
    if(error){
      surface.innerHTML=`<header><b>交付内容核对失败</b><span>需要处理</span></header><p>${esc(error.message)} 此版本不会交给 AA 制作。</p>`;
      const action=card.querySelector('[data-handoff], [data-open-production]');
      if(action){action.disabled=true;action.title='发布完整性复验失败'}
    }else if(!detail){
      surface.innerHTML='<header><b>正在核对交付内容</b><span>读取中</span></header>';
    }else{
      const manifest=detail.manifest||{},sceneCount=manifest.scenes?.length||0,dependencyCount=manifest.dependency_refs?.length||0,gateCount=manifest.gate_snapshot_ids?.length||0;
      surface.innerHTML=`<header><b>交付内容已确认</b><span>可追溯</span></header><div class="release-source-grid"><span><b>${sceneCount}</b> 场正文</span><span><b>${dependencyCount}</b> 份正式资料</span><span><b>${gateCount}</b> 项审查记录</span><span><b>已固定</b> 写作规则</span></div><p>后续修改作品不会改变本次交付。</p><details><summary>技术详情</summary><dl><div><dt>来源校验</dt><dd>${esc(shortDigest(manifest.source_set_digest))}</dd></div><div><dt>写作规则校验</dt><dd>${esc(shortDigest(manifest.ba_writing_source_digest))}</dd></div><div><dt>正文校验</dt><dd>${esc(shortDigest(manifest.content_hash))}</dd></div><div><dt>冻结时间</dt><dd>${esc(manifest.released_at||release.released_at||'未记录')}</dd></div></dl></details>`;
    }
    card.querySelector('.actions')?.insertAdjacentElement('beforebegin',surface);
  }
  requestReleaseDetails();
}

renderRelease=function(el){
  renderReleaseBeforeMemoryGuidance(el);
  const releaseKicker=el.querySelector('.workspace-inner > .eyebrow');
  const releaseLede=el.querySelector('.workspace-inner > .lede');
  const preflightCopy=el.querySelector('.release-freeze-preflight header p:not(.eyebrow)');
  if(releaseKicker)releaseKicker.textContent='检查与发布';
  if(releaseLede)releaseLede.textContent='检查当前正文和素材，确认后再生成制作定稿。';
  if(preflightCopy)preflightCopy.textContent='以下内容会作为本次制作定稿；生成定稿不会修改作品原件。';
  const reviewGate=(state.work?.gates||[]).find(gate=>gate.kind==='release.review');
  const allFindings=state.work?.review_findings||[];
  const openFindings=allFindings.filter(finding=>finding.status==='open');
  const resolvedCount=allFindings.filter(finding=>finding.status==='resolved').length;
  const severityLabel={blocking:'阻塞',warning:'建议',info:'提示'};
  const severityCounts={blocking:0,warning:0,info:0};
  openFindings.forEach(finding=>{if(finding.severity in severityCounts)severityCounts[finding.severity]+=1});
  const findingsPanel=document.createElement('section');
  findingsPanel.className=`release-findings-surface ${severityCounts.blocking?'has-blocker':''}`;
  findingsPanel.innerHTML=`<header><div><p class="eyebrow">审查结果</p><h3>审查问题</h3></div><div class="release-finding-counts"><span class="blocking">${severityCounts.blocking} 阻塞</span><span>${severityCounts.warning} 建议</span><span>${severityCounts.info} 提示</span>${resolvedCount?`<span class="resolved">${resolvedCount} 已处理</span>`:''}</div></header>${openFindings.length?`<div class="release-finding-list">${openFindings.map(finding=>{const scene=scenes().find(item=>item.id===finding.scene_id);return `<article class="release-finding-row ${esc(finding.severity)}"><div><span>${esc(severityLabel[finding.severity]||finding.severity)}${scene?` · ${esc(scene.title)}`:''}</span><b>${esc(finding.message)}</b><small>${esc(sceneFindingLabel(finding.kind))}</small></div><button class="quiet" type="button" data-resolve-finding="${esc(finding.id)}">标记已处理</button></article>`}).join('')}</div>`:'<p class="release-findings-empty">当前没有未处理的审查问题。</p>'}`;
  const actions=el.querySelector('.actions');
  actions?.insertAdjacentElement('beforebegin',findingsPanel);
  decorateReleaseIntegrity(el);
  const incompleteIds=new Set(reviewGate?.snapshot?.incomplete_memory_scene_ids||[]);
  const incomplete=scenes().filter(scene=>
    scene.current_revision_id
    && (incompleteIds.has(scene.id)||!['succeeded','skipped'].includes(sceneMemoryWorkItem(scene)?.status))
  );
  if(!incomplete.length)return;
  const notice=el.querySelector('.notice');
  if(reviewGate?.status==='blocked'&&incompleteIds.size&&notice){
    notice.classList.remove('good');
    notice.classList.add('bad');
    notice.textContent=`还有 ${incomplete.length} 个场景没有完成长期记忆维护。处理后重新运行全篇审查。`;
  }
  const panel=document.createElement('section');
  panel.className='release-memory-guidance';
  panel.innerHTML=`<div><p class="eyebrow">RELEASE CHECK</p><h3>先完成场景记忆维护</h3><p>发布版本必须说明每个正式场景有哪些变化需要带到后文，或者明确确认本场无需沉淀。</p></div><div>${incomplete.map(scene=>`<button type="button" data-memory-open-scene="${esc(scene.id)}"><span>${esc(scene.chapterTitle)}</span><b>${esc(scene.title)}</b><em>去处理</em></button>`).join('')}</div>`;
  notice?.insertAdjacentElement('afterend',panel);
};

document.addEventListener('click',event=>{
  const open=event.target.closest('[data-memory-open-scene]');
  if(!open||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  state.sceneId=open.dataset.memoryOpenScene;
  state.stage='draft';state.surface='writing';state.mobileView='writing';state.context=null;
  render();
  requestAnimationFrame(()=>document.querySelector('.scene-memory-action')?.focus());
},true);

document.addEventListener('input',event=>{
  const input=event.target.closest('[data-thread-search]');
  if(!input)return;
  state.threadRailQuery=input.value;
  renderFinalWorkAgentRail();
  const next=document.querySelector('[data-thread-search]');
  if(next){next.focus();next.setSelectionRange(next.value.length,next.value.length);}
},true);

document.addEventListener('submit',event=>{
  const form=event.target.closest('[data-thread-rename-form]');
  if(!form||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();const thread=(state.work.conversation_threads||[]).find(item=>item.id===form.dataset.threadRenameForm);if(!thread)return;const title=new FormData(form).get('title');
  (async()=>{try{const result=await api(`/works/${state.work.id}/threads/${thread.id}`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,title,status:thread.status})});state.work=result.work;state.renamingThreadId='';toast('对话名称已保存');render();}catch(error){toast(error.message,true)}})();
},true);

document.addEventListener('change',event=>{
  const input=event.target.closest('#workAgentImageInput, #workAgentDocumentInput');
  if(!input||!state.work||!input.files?.length)return;
  const thread=workConversationThread(),file=input.files[0],documentUpload=input.id==='workAgentDocumentInput';input.value='';
  const reader=new FileReader();reader.onload=async()=>{try{setBusy(documentUpload?'正在读取文档':'正在保存图片附件');const result=await api(`/works/${state.work.id}/threads/${thread.id}/attachments`,{method:'POST',body:JSON.stringify({expected_thread_version:thread.version,filename:file.name,media_type:file.type,content_base64:String(reader.result).split(',')[1]||''})});state.work=result.work;const updated=workConversationThread();const attachment=(updated?.attachments||[]).find(item=>item.id===result.attachment_id);if(attachment)state.composerAttachmentIds=[...(state.composerAttachmentIds||[]),attachment.id];toast(documentUpload?'文档已提取文字并加入本轮消息':'图片已加入本轮消息');render();}catch(error){toast(error.message,true)}finally{setBusy('')}};reader.readAsDataURL(file);
},true);

function memorySourceScene(memory){
  const source=(memory.source_refs||[]).find(item=>item.kind==='scene_revision'&&item.scene_id);
  return source?scenes().find(scene=>scene.id===source.scene_id):null;
}

function memoryLibraryMarkup(){
  const memories=state.work?.memories||[],active=memories.filter(item=>item.lifecycle_status==='active'),archived=memories.filter(item=>item.lifecycle_status==='archived');
  const groups=[['episode_memory','情节记忆'],['scene_state_snapshot','场末状态'],['open_thread','未决伏笔'],['decision_record','创作决定']];
  const cards=items=>items.map(memory=>{const content=memory.content||{},scene=memorySourceScene(memory),source=(memory.source_refs||[])[0];return `<article class="memory-library-card ${memory.lifecycle_status==='archived'?'is-archived':''}">
    <header><span>${esc(memoryKindLabel(memory.kind))}</span><em>${memory.lifecycle_status==='archived'?'已归档':memory.confidence_status==='confirmed'?'可用于后续写作':confidenceLabel(memory.confidence_status)}</em></header>
    <h4>${esc(content.title||'未命名长期记忆')}</h4><p>${esc(content.summary||'')}</p>
    <footer><div><b>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'作品级来源'}</b><small>r${memory.version} · ${source?.block_ids?.length||0} 个正文块 · ${esc(memory.current_revision_id)}</small></div><button type="button" class="quiet" data-memory-lifecycle="${memory.lifecycle_status==='archived'?'restore':'archive'}" data-memory-id="${esc(memory.id)}">${memory.lifecycle_status==='archived'?'恢复使用':'归档'}</button></footer>
  </article>`}).join('');
  return `<section class="library-page-head memory-library-head"><div><h3>长期记忆</h3><p>这里展示 Agent 从正式正文中提取、并经你采纳的情节变化、场末状态、伏笔和创作决定。新内容由写作流程提出，不在这里手工造事实。</p></div><span class="source-pill">${active.length} 条正在使用 · ${archived.length} 条已归档</span></section>
    <section class="memory-library-summary">${groups.map(([kind,label])=>`<div><b>${active.filter(item=>item.kind===kind).length}</b><span>${label}</span></div>`).join('')}</section>
    <section class="memory-library-list">${active.length?cards(active):'<div class="library-empty"><b>还没有正式长期记忆</b><span>完成场景正文后，点击“沉淀本场变化”；只有采纳的候选才会出现在这里。</span></div>'}</section>
    ${archived.length?`<details class="memory-library-archive"><summary>已归档记忆 ${archived.length}</summary><div>${cards(archived)}</div></details>`:''}`;
}

function backgroundKnowledgeSuggestionsMarkup(){
  const suggestions=backgroundKnowledgeSuggestions();
  const cards=suggestions.map(proposal=>{
    const candidate=proposal.candidate||{},content=candidate.content||{};
    const scene=scenes().find(item=>item.id===proposal.scope_id)||scenes().find(item=>item.current_revision_id===proposal.evidence?.scene_revision_id);
    const impact=candidate.impact_preview||{};
    const integrity=proposal.candidate_integrity?.valid!==false;
    const sourceBlocks=proposal.evidence?.source_block_ids||[];
    if(!integrity){
      return `<article class="background-suggestion-card is-invalid"><header><div><span>作品事实建议</span><b>候选文件校验失败</b></div><em>不可应用</em></header><p>系统没有读取或展示损坏内容。可以忽略这条建议，再从当前场景修订重新整理。</p><div class="artifact-decision-actions"><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">忽略建议</button></div></article>`;
    }
    const blocking=Number(impact.conflict_summary?.blocking_count||0)>0;
    const affectedScenes=(impact.affected_refs||[]).filter(item=>item.kind==='scene').length;
    const reviewsAffected=(impact.affected_refs||[]).some(item=>item.kind==='gate'&&item.effect==='review_required');
    const frozenRelease=(impact.affected_refs||[]).some(item=>item.kind==='script_release'&&item.effect==='immutable_no_rewrite');
    const sourceLabel=scene?`${scene.chapterTitle} / ${scene.title}`:'已确认的场景正文';
    const impactItems=[
      affectedScenes?`后续 ${affectedScenes} 个场景会读取这项事实`:'后续场景会读取这项事实',
      reviewsAffected?'当前连续性与发布检查需要重新运行':'后续审查会包含这项事实',
      frozenRelease?'已有制作定稿保持不变':''
    ].filter(Boolean);
    return `<article class="background-suggestion-card ${blocking?'has-conflict':''}">
      <header><div><span>作品事实建议</span><b>${esc(content.text||'未命名事实')}</b></div><em>${scene?`${esc(scene.chapterTitle)} / ${esc(scene.title)}`:'正式场景正文'}</em></header>
      <p>Agent 从已确认正文中发现了可能影响后续章节的长期事实。采用前不会进入写作资料。</p>
      <div class="background-suggestion-source"><span>来自正文</span><b>${esc(sourceLabel)}</b><small>${sourceBlocks.length?`${sourceBlocks.length} 处直接依据`:'来源已保存'}</small></div>
      <div class="background-suggestion-impact"><b>采用后</b><ul>${impactItems.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>
      <details class="background-suggestion-technical"><summary>技术详情</summary><dl><dt>来源版本</dt><dd>${esc(proposal.evidence?.scene_revision_id||proposal.base_revision_id||'未记录')}</dd><dt>候选记录</dt><dd>${esc(proposal.id)}</dd></dl></details>
      <div class="artifact-decision-actions"><button class="primary" type="button" data-accept-director-proposal="${esc(proposal.id)}" data-impact-digest="${esc(impact.digest||'')}" ${blocking?'disabled aria-disabled="true" title="先处理阻塞冲突后再应用"':''}>应用这项修改</button><button class="quiet" type="button" data-reject-director-proposal="${esc(proposal.id)}">不采用</button></div>
    </article>`;
  }).join('');
  return `<section class="library-page-head background-suggestion-head"><div><h3>待整理建议</h3><p>Agent 会在场景正文形成正式版本后，安静检查可能需要长期保留的事实。建议有正文证据和影响预览；只有你应用后，才会写入作品事实。</p></div><span class="source-pill">${suggestions.length} 条等待审查</span></section>
    <div class="background-suggestion-list">${cards||'<div class="library-empty"><b>没有待整理建议</b><span>继续写作即可。后台检查不会打断当前场景，也不会自动改动作品资料。</span></div>'}</div>`;
}

const renderReferencesBeforeMemoryLibrary=renderReferences;
renderReferences=function(el){
  renderReferencesBeforeMemoryLibrary(el);
  const nav=el.querySelector('.library-nav'),main=el.querySelector('.library-main');
  if(!nav||!main)return;
  if(state.libraryView==='characters'){
    const recovery=currentSceneRecovery(),scene=recovery&&scenes().find(item=>item.id===recovery.scene_id);
    if(recovery&&scene){
      const anchor=document.createElement('section');anchor.className='library-scene-recovery';anchor.dataset.sceneRecoveryAnchor='';
      anchor.innerHTML=`<div><p class="eyebrow">RETURN TO SCENE</p><h3>补齐资料后回到「${esc(scene.title)}」</h3><p>返回时会按稳定场景 ID 重新准备上下文；不会自动发送 Agent 指令、生成候选或改动正文。</p></div><button type="button" class="quiet" data-return-recovery-scene="${esc(scene.id)}">返回当前场继续</button>`;
      main.querySelector('.library-page-head')?.after(anchor);
    }else if(recovery){clearSceneRecovery();}
  }
  if(state.libraryView==='overview'){
    main.querySelector('.library-control-deck')?.replaceWith(document.createRange().createContextualFragment(libraryDecisionGuideMarkup()));
    const decision=main.querySelector('.library-control-deck'),brief=main.querySelector('.library-brief');
    if(decision&&brief)main.insertBefore(decision,brief);
  }
  if(!nav.querySelector('[data-library-view="suggestions"]')){
    const button=document.createElement('button');button.type='button';button.className='library-nav-item';button.dataset.libraryView='suggestions';button.textContent=`待整理建议${backgroundKnowledgeSuggestions().length?` ${backgroundKnowledgeSuggestions().length}`:''}`;nav.append(button);
  }
  if(!nav.querySelector('[data-library-view="memories"]')){
    const button=document.createElement('button');button.type='button';button.className='library-nav-item';button.dataset.libraryView='memories';button.textContent='长期记忆';nav.append(button);
  }
  nav.querySelectorAll('.library-nav-item').forEach(button=>button.classList.toggle('active',button.dataset.libraryView===state.libraryView));
  if(state.libraryView==='suggestions')main.innerHTML=backgroundKnowledgeSuggestionsMarkup();
  if(state.libraryView==='memories')main.innerHTML=memoryLibraryMarkup();
};

document.addEventListener('click',event=>{
  const recoveryButton=event.target.closest('[data-return-recovery-scene]');
  if(recoveryButton&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const recovery=currentSceneRecovery(),scene=scenes().find(item=>item.id===recovery?.scene_id);
    const chapter=(state.work.chapters||[]).find(item=>item.id===scene?.chapter_id);
    if(!recovery||!scene||!chapter){clearSceneRecovery();toast('原场景已变化，请从章节结构重新选择写作位置。',true);render();return;}
    recoveryButton.disabled=true;
    (async()=>{try{
      await persistWritingTarget(chapter.id,scene.id);
      state.writingChapterId=chapter.id;state.sceneId=scene.id;state.context=null;state.inspector='agent';state.surface='writing';state.mobileView='writing';state.writingMobileView='agent';state.stage='draft';state.sceneContextEditorOpen=false;state._recoveryContextHint=true;
      const targetUrl=`?section=writing&work_id=${encodeURIComponent(state.work.id)}&stage=draft&chapter_id=${encodeURIComponent(chapter.id)}&scene_id=${encodeURIComponent(scene.id)}`;
      if(`${location.pathname}${location.search}`!==targetUrl)history.pushState({halocue:true},'',targetUrl);
      clearSceneRecovery();render();toast(`已回到《${scene.title}》；正在重新准备上下文，不会自动运行 Agent。`);
    }catch(error){recoveryButton.disabled=false;toast(`无法返回原场：${error.message}`,true)}})();
    return;
  }
  const reviewProposal=event.target.closest('[data-library-review-proposal]'),returnToAgent=event.target.closest('[data-library-return-to-agent]');
  if((reviewProposal||returnToAgent)&&state.work){
    event.preventDefault();event.stopImmediatePropagation();
    const proposalId=reviewProposal?.dataset.libraryReviewProposal||'',proposal=(state.work.proposals||[]).find(item=>item.id===proposalId),sourceThreadId=proposal?.candidate?.source_thread_id||'';
    if(sourceThreadId)state.conversationThreadId=sourceThreadId;
    state.surface='works';state.mobileView='writing';state.mobileThreadOpen=false;state.stage='overview';state.inspector='agent';state.agentPresentation=null;render();
    if(proposalId&&!sourceThreadId)requestAnimationFrame(()=>document.querySelector(`[data-agent-review-proposal="${CSS.escape(proposalId)}"]`)?.click());
    if(sourceThreadId)refreshAgentPresentation().then(()=>{render();if(proposalId)requestAnimationFrame(()=>document.querySelector(`[data-agent-review-proposal="${CSS.escape(proposalId)}"]`)?.click())});
    return;
  }
  const button=event.target.closest('[data-memory-lifecycle]');
  if(!button||!state.work)return;
  event.preventDefault();event.stopImmediatePropagation();
  const action=button.dataset.memoryLifecycle,memoryId=button.dataset.memoryId;
  (async()=>{try{button.disabled=true;setBusy(action==='archive'?'正在归档长期记忆':'正在恢复长期记忆');const result=await api(`/works/${state.work.id}/memories/${memoryId}/${action}`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,note:action==='archive'?'用户在资料库中归档长期记忆。':'用户在资料库中恢复长期记忆。'})});state.work=result.work;toast(action==='archive'?'长期记忆已归档，不再进入新场景上下文':'长期记忆已恢复，可再次进入后续场景上下文');render()}catch(error){button.disabled=false;setBusy('长期记忆状态未改变');toast(error.message,true)}})();
},true);

const ASSET_CATALOG_KINDS={
  characters:{label:'角色',singular:'角色',mark:'人',customKind:'character',description:'Spine 角色包、头像与表情索引'},
  backgrounds:{label:'背景',singular:'背景',mark:'景',customKind:'background',description:'场景背景与 AA 资源标识'},
  sounds:{label:'音效',singular:'音效',mark:'声',customKind:'sound',description:'演出可用的音效条目'},
  cg:{label:'插图',singular:'插图',mark:'图',customKind:'cg',description:'剧情插图与弹窗覆盖资源'},
};

function assetCatalogSourceLabel(source){
  return ({custom_library:'我的素材',resource_index:'AA 资源索引',aa_popup_override:'AA 弹窗覆盖'})[source]||'AA 本地资源';
}

function assetCatalogMeta(item,kind){
  if(item.source==='custom_library'){
    const metadata=item.metadata||{},labels=item.labels||{};
    if(kind==='characters')return [item.nickname||'未填写角色备注',`${(metadata.faces||[]).length} 个已验证表情`,metadata.spine_version?`Spine ${metadata.spine_version}`:'Spine 版本未识别'];
    if(kind==='sounds')return [metadata.duration?`${Number(metadata.duration).toFixed(1)} 秒`:'16-bit WAV',labels.mood||'未标情绪'];
    return [labels.scene_type||labels.place||'未标场景',labels.time_of_day||labels.time||'未标时间',labels.mood||'未标情绪'];
  }
  if(kind==='characters')return [item.club||'未标学院或社团',`${Number(item.face_count||0)} 个表情`,item.outfit_key||'默认服装'];
  if(kind==='backgrounds')return [item.aa_hash?`AA Hash ${item.aa_hash}`:'未记录 AA Hash'];
  if(kind==='sounds')return ['音效条目'];
  return ['剧情插图'];
}

function assetCatalogCard(item,kind){
  const config=ASSET_CATALOG_KINDS[kind],name=item.name||item.key||'未命名素材',meta=assetCatalogMeta(item,kind);
  const canPreview=kind!=='sounds';
  const custom=item.source==='custom_library',previewKey=custom?item.asset_id:(item.key||item.identifier||'');
  const tags=custom&&Array.isArray(item.tags)&&item.tags.length?`<div class="asset-card-tags">${item.tags.slice(0,4).map(tag=>`<span>${esc(tag)}</span>`).join('')}</div>`:'';
  const technicalKey=item.key||item.identifier||item.asset_id||'';
  const technicalVersion=item.metadata_version||item.version||item.source_version||'';
  return `<article class="asset-catalog-card">
    <div class="asset-card-visual ${esc(kind)}" aria-hidden="true">${custom&&canPreview?`<img src="/production/api/v1/custom-assets/${encodeURIComponent(item.asset_id)}/preview" alt="" loading="lazy">`:''}<span>${esc(config.mark)}</span><small>${esc(String(name).slice(0,18))}</small></div>
    <div class="asset-card-copy"><header><span>${esc(config.singular)}</span><em>${esc(assetCatalogSourceLabel(item.source))}</em></header><h3>${esc(name)}</h3><p>${meta.map(value=>esc(value)).join(' · ')}</p>${tags}${technicalKey?`<details class="asset-card-technical"><summary>技术详情</summary><dl><div><dt>资源标识</dt><dd><code>${esc(technicalKey)}</code></dd></div>${technicalVersion?`<div><dt>来源版本</dt><dd>${esc(technicalVersion)}</dd></div>`:''}</dl></details>`:''}</div>
    <footer>${custom?`<button type="button" class="quiet" data-custom-asset-edit="${esc(item.asset_id)}">编辑</button><button type="button" class="primary" data-asset-attach="${esc(item.asset_id)}">加入任务</button>`:canPreview?`<button type="button" class="quiet" data-asset-preview="${esc(previewKey)}" data-asset-preview-scope="builtin" title="查看本地预览">预览</button>`:'<span>只读索引</span>'}</footer>
  </article>`;
}

function renderAssetCatalog(){
  const catalog=state.assetCatalog,config=ASSET_CATALOG_KINDS[catalog.kind],el=$('#workspace');
  if(!el)return;
  const loaded=catalog.items.length,custom=catalog.scope==='custom';
  el.innerHTML=`<div class="asset-catalog-workbench">
    <header class="asset-catalog-hero"><div><p class="eyebrow">PRODUCTION ASSET LIBRARY</p><h2>素材库</h2><p>${custom?'集中保存你上传的背景、CG、音效和 Spine 角色包，并在需要时明确加入制作任务。':'浏览 AA 制作环境已有的内置资源；这些条目保持只读。'}</p></div><div class="asset-hero-actions">${custom?'<button type="button" class="primary" data-custom-asset-upload>上传素材</button>':''}<button type="button" class="quiet" data-section="production">打开 AA 制作</button></div></header>
    <nav class="asset-source-tabs" aria-label="素材来源"><button type="button" data-asset-scope="custom" class="${custom?'active':''}" aria-pressed="${custom}">我的素材</button><button type="button" data-asset-scope="builtin" class="${custom?'':'active'}" aria-pressed="${!custom}">AA 内置资源</button></nav>
    <section class="asset-catalog-boundary"><span>${custom?'确认边界':'只读边界'}</span><p>${custom?'AI 识别只会生成标签建议；你确认登记后才进入素材库，点击“加入任务”后才复制到所选制作任务。':'内置资源不会被改名或覆盖；需要自定义内容时切换到“我的素材”。'}</p></section>
    <div class="asset-catalog-toolbar"><nav aria-label="素材类型">${Object.entries(ASSET_CATALOG_KINDS).map(([kind,item])=>`<button type="button" data-asset-kind="${kind}" class="${kind===catalog.kind?'active':''}" aria-pressed="${kind===catalog.kind}"><span>${item.mark}</span><b>${item.label}</b><small>${item.description}</small></button>`).join('')}</nav><form data-asset-search><label><span class="sr-only">搜索${esc(config.label)}</span><input name="query" value="${esc(catalog.query)}" maxlength="120" placeholder="搜索${esc(config.label)}${custom?'名称、标签或场景':'名称或资源标识'}"></label><button type="submit" class="quiet">搜索</button></form></div>
    <section class="asset-catalog-results" aria-live="polite"><header><div><h3>${esc(config.label)}</h3><p>${catalog.error?'制作服务暂时不可用':catalog.loading&&!loaded?'正在读取素材索引':`已显示 ${loaded} / ${catalog.total} 项`}</p></div>${catalog.query?`<button type="button" class="quiet" data-asset-clear-search>清除“${esc(catalog.query)}”</button>`:''}</header>
      ${catalog.error?`<div class="asset-catalog-unavailable"><span aria-hidden="true">!</span><div><h3>制作服务不可用</h3><p>${esc(catalog.error)} 素材数据没有被缓存或伪造成可用数据。</p></div><button type="button" class="primary" data-asset-retry>重新连接</button></div>`:
      catalog.loading&&!loaded?'<div class="asset-catalog-loading"><span></span><span></span><span></span><p>正在读取素材库</p></div>':
      loaded?`<div class="asset-catalog-grid">${catalog.items.map(item=>assetCatalogCard(item,catalog.kind)).join('')}</div>${catalog.hasMore?`<div class="asset-catalog-more"><button type="button" class="quiet" data-asset-load-more ${catalog.loading?'disabled':''}>${catalog.loading?'正在加载':'加载更多'}</button></div>`:''}`:
      `<div class="asset-catalog-empty"><span>${esc(config.mark)}</span><h3>${custom&&!catalog.query?`还没有自定义${esc(config.label)}`:`没有匹配的${esc(config.label)}`}</h3><p>${custom&&!catalog.query?'上传后先检查格式，再由你决定是否采用 AI 标签建议。':custom?'换一个名称、标签或场景再试。':'换一个名称或资源标识再试。'}</p>${custom&&!catalog.query?'<button type="button" class="primary" data-custom-asset-upload>上传素材</button>':'<button type="button" class="quiet" data-asset-clear-search>清除搜索</button>'}</div>`}
    </section>
  </div>`;
}

async function loadAssetCatalog({append=false}={}){
  const catalog=state.assetCatalog,requestId=++catalog.requestId;
  if(!append){catalog.items=[];catalog.offset=0;catalog.total=0;catalog.hasMore=false}
  catalog.loading=true;catalog.error=null;render();
  const params=new URLSearchParams({q:catalog.query,offset:String(append?catalog.items.length:0),limit:String(catalog.limit)});
  try{
    const custom=catalog.scope==='custom';
    if(custom)params.set('kind',ASSET_CATALOG_KINDS[catalog.kind].customKind);
    const response=await fetch(custom?`/production/api/v1/custom-assets?${params}`:`/production/api/v1/resources/${encodeURIComponent(catalog.kind)}?${params}`);
    let payload;try{payload=await response.json()}catch(_){throw new Error('制作服务返回了无法解析的响应。')}
    if(!response.ok||payload.ok===false)throw new Error(payload.error?.message||`制作服务返回 ${response.status}。`);
    if(requestId!==catalog.requestId)return;
    const items=Array.isArray(payload.items)?payload.items:[];
    catalog.items=append?[...catalog.items,...items]:items;
    catalog.total=Number(payload.total||catalog.items.length);catalog.offset=Number(payload.offset||0);catalog.hasMore=Boolean(payload.has_more);
  }catch(error){
    if(requestId!==catalog.requestId)return;
    catalog.error=error.message||'无法连接 AA 制作资源接口。';catalog.items=[];catalog.total=0;catalog.hasMore=false;
  }finally{
    if(requestId===catalog.requestId){catalog.loading=false;if(state.assetSurfaceOpen)render()}
  }
}

function ensureAssetPreviewDialog(){
  let dialog=$('#assetPreviewDialog');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='assetPreviewDialog';dialog.className='asset-preview-dialog';
  dialog.innerHTML='<div class="dialog-head"><div><p>LOCAL PREVIEW</p><h2 data-asset-preview-title>素材预览</h2></div><button type="button" class="icon-button" data-asset-preview-close title="关闭">×</button></div><div class="asset-preview-media" data-asset-preview-media></div><p class="form-note">预览来自 AA 制作允许访问的本地资源，不会暴露磁盘路径。</p>';
  document.body.append(dialog);return dialog;
}

async function openAssetPreview(key,scope='builtin'){
  const button=document.querySelector(`[data-asset-preview="${CSS.escape(key)}"]`);if(button)button.disabled=true;
  try{
    const previewUrl=scope==='custom'?`/production/api/v1/custom-assets/${encodeURIComponent(key)}/preview`:`/production/api/v1/resources/${encodeURIComponent(state.assetCatalog.kind)}/${encodeURIComponent(key)}/preview`;
    const response=await fetch(previewUrl);
    if(!response.ok)throw new Error(response.status===404?'该素材暂时没有可用的本地预览。':'预览读取失败。');
    const dialog=ensureAssetPreviewDialog(),media=dialog.querySelector('[data-asset-preview-media]');
    media.innerHTML=`<img src="${esc(previewUrl)}" alt="素材本地预览">`;dialog.querySelector('[data-asset-preview-title]').textContent=scope==='custom'?'我的素材预览':key;dialog.showModal();
  }catch(error){toast(error.message,true)}finally{if(button)button.disabled=false}
}

async function productionJson(path,options={}){
  const response=await fetch(`/production/api/v1${path}`,options);
  let payload;try{payload=await response.json()}catch(_){throw new Error('制作服务返回了无法解析的响应。')}
  if(!response.ok||payload.ok===false)throw new Error(payload.error?.message||`制作服务返回 ${response.status}。`);
  return payload;
}

function ensureCustomAssetUploadDialog(){
  let dialog=$('#customAssetUploadDialog');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='customAssetUploadDialog';dialog.className='custom-asset-dialog';
  dialog.innerHTML=`<div class="dialog-head"><div><p>CUSTOM ASSET</p><h2>上传到我的素材</h2></div><button type="button" class="icon-button" data-custom-asset-close title="关闭">×</button></div>
    <form data-custom-asset-upload-form>
      <div class="custom-asset-form-grid">
        <label>素材类型<select name="kind" required><option value="background">背景图片</option><option value="cg">剧情插图 / CG</option><option value="sound">音效 WAV</option><option value="character">Spine 角色 ZIP</option></select></label>
        <label>选择文件<input name="file" type="file" accept=".png,.jpg,.jpeg,.wav,.zip" required></label>
        <label>角色 Identifier<input name="identifier" maxlength="80" placeholder="仅角色 ZIP 必填"></label>
        <label>显示名称<input name="display_name" maxlength="160" placeholder="可留空使用文件名或识别建议"></label>
        <label>角色备注<input name="nickname" maxlength="120" placeholder="例如学院、社团或服装说明"></label>
        <label>搜索标签<input name="tags" maxlength="240" placeholder="用逗号分隔"></label>
        <label>地点 / 场景<input name="place" maxlength="100"></label>
        <label>时间<input name="time" maxlength="80"></label>
        <label>情绪<input name="mood" maxlength="80"></label>
      </div>
      <p class="form-note">图片与角色包可选择 AI 识别；音效当前只做确定性格式检查。AI 结果不会自动入库。</p>
      <div class="custom-asset-dialog-actions"><button type="button" class="quiet" data-custom-asset-close>取消</button><button type="submit" class="primary">上传并检查</button></div>
    </form>
    <section class="custom-asset-review" data-custom-asset-review hidden aria-live="polite"></section>`;
  document.body.append(dialog);return dialog;
}

function customAssetValidationMeta(validation){
  const metadata=validation?.metadata||{},values=[];
  if(metadata.width&&metadata.height)values.push(`${metadata.width} × ${metadata.height}`);
  if(metadata.sample_rate)values.push(`${metadata.sample_rate} Hz · ${metadata.channels||1} 声道`);
  if(metadata.spine_version)values.push(`Spine ${metadata.spine_version}`);
  if(Array.isArray(metadata.faces))values.push(`${metadata.faces.length} 个已验证表情`);
  return values.join(' · ')||'技术格式已检查';
}

function renderCustomAssetReview(){
  const review=ensureCustomAssetUploadDialog().querySelector('[data-custom-asset-review]'),flow=state.assetUpload;
  if(!flow){review.hidden=true;review.innerHTML='';return}
  review.hidden=false;
  const validation=flow.validation||{},issues=Array.isArray(validation.issues)?validation.issues:[],recognition=flow.recognition,candidate=recognition?.candidate||{};
  review.innerHTML=`<header><div><p class="eyebrow">VALIDATION</p><h3>${validation.ok?'格式检查通过':'格式检查未通过'}</h3><p>${esc(customAssetValidationMeta(validation))}</p></div><span class="${validation.ok?'pass':'fail'}">${validation.ok?'PASS':'BLOCKED'}</span></header>
    ${issues.length?`<ul class="custom-asset-issues">${issues.map(item=>`<li>${esc(item.message||item.code)}</li>`).join('')}</ul>`:''}
    ${recognition?`<article class="asset-recognition-proposal"><div><p class="eyebrow">AI LABEL PROPOSAL</p><h3>${esc(candidate.title||'未命名建议')}</h3><p>${esc(candidate.summary||'没有摘要')}</p></div><dl><div><dt>搜索标签</dt><dd>${(candidate.tags||[]).map(tag=>`<span>${esc(tag)}</span>`).join('')||'无'}</dd></div><div><dt>场景</dt><dd>${esc([candidate.scene_type,candidate.time_of_day,candidate.mood].filter(Boolean).join(' · ')||'未判断')}</dd></div>${(candidate.expression_suggestions||[]).length?`<div><dt>表情建议</dt><dd>${candidate.expression_suggestions.map(item=>`<span>${esc(item.face_id)} · ${esc(item.label)}</span>`).join('')}</dd></div>`:''}</dl><label class="asset-recognition-accept"><input type="checkbox" data-accept-asset-recognition>采用这些名称与标签建议</label><p class="form-note">${recognition.evidence?.scope==='avatar_and_texture_preview'?'AI 只查看头像与贴图预览，没有渲染 Spine 动画。':'AI 只查看本次上传的图片。'}</p></article>`:flow.recognitionError?`<div class="notice bad"><b>AI 识别不可用</b><p>${esc(flow.recognitionError)} 你仍可使用手工名称和标签登记。</p></div>`:''}
    <div class="custom-asset-review-actions">${validation.ok&&flow.kind!=='sound'&&!recognition?'<button type="button" class="quiet" data-custom-asset-recognize>请求 AI 识别</button>':''}<button type="button" class="primary" data-custom-asset-register ${validation.ok?'':'disabled'}>确认登记到素材库</button></div>`;
}

function openCustomAssetUpload(){
  state.assetUpload=null;
  const dialog=ensureCustomAssetUploadDialog(),form=dialog.querySelector('[data-custom-asset-upload-form]');
  form.reset();form.querySelectorAll('input,select,button').forEach(control=>control.disabled=false);
  renderCustomAssetReview();dialog.showModal();
}

function ensureCustomAssetEditDialog(){
  let dialog=$('#customAssetEditDialog');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='customAssetEditDialog';dialog.className='custom-asset-dialog asset-edit-dialog';
  dialog.innerHTML=`<div class="dialog-head"><div><p>LIBRARY METADATA</p><h2>编辑素材信息</h2></div><button type="button" class="icon-button" data-custom-asset-close title="关闭">×</button></div><form data-custom-asset-edit-form><div data-custom-asset-edit-fields><p>正在读取素材信息…</p></div></form>`;
  document.body.append(dialog);return dialog;
}

async function openCustomAssetEdit(assetId){
  const dialog=ensureCustomAssetEditDialog(),container=dialog.querySelector('[data-custom-asset-edit-fields]');
  dialog.dataset.assetId=assetId;container.innerHTML='<p>正在读取素材信息…</p>';dialog.showModal();
  try{
    const result=await productionJson(`/custom-assets/${encodeURIComponent(assetId)}`),asset=result.asset||{},labels=asset.labels||{};
    dialog.dataset.metadataVersion=String(asset.metadata_version||1);
    container.innerHTML=`<div class="custom-asset-form-grid">
      <label>显示名称<input name="name" maxlength="160" required value="${esc(asset.name||'')}"></label>
      <label>角色备注<input name="nickname" maxlength="120" value="${esc(asset.nickname||'')}"></label>
      <label>搜索标签<input name="tags" maxlength="240" value="${esc((asset.tags||[]).join('，'))}" placeholder="用逗号分隔"></label>
      <label>地点 / 场景<input name="place" maxlength="100" value="${esc(labels.place||labels.scene_type||'')}"></label>
      <label>时间<input name="time" maxlength="80" value="${esc(labels.time||labels.time_of_day||'')}"></label>
      <label>情绪<input name="mood" maxlength="80" value="${esc(labels.mood||'')}"></label>
    </div><p class="form-note">只修改素材库中的检索信息；素材文件、类型、Identifier 和已复制进制作任务的副本不会改变。</p><div class="custom-asset-dialog-actions"><button type="button" class="quiet" data-custom-asset-close>取消</button><button type="submit" class="primary">保存修改</button></div>`;
  }catch(error){container.innerHTML=`<div class="notice bad"><b>无法读取素材信息</b><p>${esc(error.message)}</p></div><div class="custom-asset-dialog-actions"><button type="button" class="quiet" data-custom-asset-close>关闭</button></div>`}
}

function ensureCustomAssetAttachDialog(){
  let dialog=$('#customAssetAttachDialog');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='customAssetAttachDialog';dialog.className='custom-asset-dialog asset-attach-dialog';
  dialog.innerHTML=`<div class="dialog-head"><div><p>制作任务</p><h2>加入制作任务</h2></div><button type="button" class="icon-button" data-custom-asset-close title="关闭">×</button></div><form data-custom-asset-attach-form><div data-asset-run-options class="asset-run-options"><p>正在读取制作任务…</p></div><p class="form-note">素材会复制到所选任务；素材库原件保持不变。</p><div class="custom-asset-dialog-actions"><button type="button" class="quiet" data-custom-asset-close>取消</button><button type="submit" class="primary" disabled>加入所选任务</button></div></form>`;
  document.body.append(dialog);return dialog;
}

async function openCustomAssetAttach(assetId){
  const dialog=ensureCustomAssetAttachDialog(),container=dialog.querySelector('[data-asset-run-options]'),submit=dialog.querySelector('button[type="submit"]');
  dialog.dataset.assetId=assetId;container.innerHTML='<p>正在读取制作任务…</p>';submit.disabled=true;dialog.showModal();
  try{
    const result=await productionJson('/production-runs'),runs=Array.isArray(result.items)?result.items:[];
    const stateLabels={compiled:'已编译',installed:'已安装',waiting_for_review:'等待审查',direction_failed:'需要处理',draft:'准备中'};
    container.innerHTML=runs.length?`<label>选择制作任务<select name="run_id" required>${runs.map(run=>`<option value="${esc(run.run_id)}">${esc(run.project)} · ${esc(stateLabels[run.state]||'进行中')}</option>`).join('')}</select></label>`:'<div class="notice bad">还没有可以接收素材的制作任务。请先把定稿送往 AA 制作。</div>';
    submit.disabled=!runs.length;
  }catch(error){container.innerHTML=`<div class="notice bad">${esc(error.message)}</div>`}
}

const renderBeforeAssetCatalog=render;
render=function(){
  const surfaceKey=[state.assetSurfaceOpen?'assets':state.surface,state.stage,state.mobileView,state.sceneId||'',state.writingMobileView||''].join('|');
  const routeChanged=surfaceKey!==lastRenderedSurfaceKey;
  renderBeforeAssetCatalog();
  lastRenderedSurfaceKey=surfaceKey;
  if(routeChanged){
    const workspace=$('#workspace');
    if(workspace)workspace.scrollTop=0;
    requestAnimationFrame(()=>{ if(workspace)workspace.scrollTop=0; });
  }
  const app=$('#app'),active=state.assetSurfaceOpen;
  app?.classList.toggle('asset-stage',active);
  if(!active)return;
  app?.classList.remove('library-stage','tasks-stage','overview-stage','work-agent-stage','work-agent-expanded','mobile-thread-open');
  $$('.primary-nav [data-section], .mobile-nav [data-section], .mobile-nav [data-mobile]').forEach(button=>button.classList.toggle('active',button.dataset.section==='assets'));
  setCrumb(null,`素材库 / ${state.assetCatalog.scope==='custom'?'我的素材':'AA 内置资源'} / ${ASSET_CATALOG_KINDS[state.assetCatalog.kind].label}`);
  renderAssetCatalog();
};

document.addEventListener('click',event=>{
  const section=event.target.closest('[data-section]');
  if(section?.dataset.section==='assets'){
    event.preventDefault();section.closest('.mobile-more-menu')?.removeAttribute('open');
    state.assetSurfaceOpen=true;state.surface='assets';state.mobileView='writing';render();
    if(!state.assetCatalog.items.length&&!state.assetCatalog.loading)loadAssetCatalog();return;
  }
  if(section&&state.assetSurfaceOpen)state.assetSurfaceOpen=false;
  const scope=event.target.closest('[data-asset-scope]');
  if(scope){event.preventDefault();event.stopImmediatePropagation();if(scope.dataset.assetScope===state.assetCatalog.scope)return;state.assetCatalog.scope=scope.dataset.assetScope;state.assetCatalog.query='';loadAssetCatalog();return}
  const kind=event.target.closest('[data-asset-kind]');
  if(kind){event.preventDefault();event.stopImmediatePropagation();if(kind.dataset.assetKind===state.assetCatalog.kind)return;state.assetCatalog.kind=kind.dataset.assetKind;state.assetCatalog.query='';loadAssetCatalog();return}
  const more=event.target.closest('[data-asset-load-more]');
  if(more){event.preventDefault();event.stopImmediatePropagation();loadAssetCatalog({append:true});return}
  const retry=event.target.closest('[data-asset-retry]');
  if(retry){event.preventDefault();event.stopImmediatePropagation();loadAssetCatalog();return}
  const clear=event.target.closest('[data-asset-clear-search]');
  if(clear){event.preventDefault();event.stopImmediatePropagation();state.assetCatalog.query='';loadAssetCatalog();return}
  const preview=event.target.closest('[data-asset-preview]');
  if(preview){event.preventDefault();event.stopImmediatePropagation();openAssetPreview(preview.dataset.assetPreview,preview.dataset.assetPreviewScope);return}
  const upload=event.target.closest('[data-custom-asset-upload]');
  if(upload){event.preventDefault();event.stopImmediatePropagation();openCustomAssetUpload();return}
  const edit=event.target.closest('[data-custom-asset-edit]');
  if(edit){event.preventDefault();event.stopImmediatePropagation();openCustomAssetEdit(edit.dataset.customAssetEdit);return}
  const attach=event.target.closest('[data-asset-attach]');
  if(attach){event.preventDefault();event.stopImmediatePropagation();openCustomAssetAttach(attach.dataset.assetAttach);return}
  const recognize=event.target.closest('[data-custom-asset-recognize]');
  if(recognize){event.preventDefault();event.stopImmediatePropagation();recognize.disabled=true;(async()=>{try{const flow=state.assetUpload,result=await productionJson('/custom-assets/recognize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:flow.kind,upload_token:flow.uploadToken,identifier:flow.identifier})});flow.recognition=result.recognition;flow.recognitionError='';renderCustomAssetReview()}catch(error){state.assetUpload.recognitionError=error.message;renderCustomAssetReview()}})();return}
  const register=event.target.closest('[data-custom-asset-register]');
  if(register){event.preventDefault();event.stopImmediatePropagation();register.disabled=true;(async()=>{try{const dialog=ensureCustomAssetUploadDialog(),form=dialog.querySelector('[data-custom-asset-upload-form]'),fields=new FormData(form),flow=state.assetUpload,tags=String(fields.get('tags')||'').split(/[，,]/).map(value=>value.trim()).filter(Boolean),accept=Boolean(dialog.querySelector('[data-accept-asset-recognition]')?.checked);await productionJson('/custom-assets',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:flow.kind,upload_token:flow.uploadToken,identifier:flow.identifier,display_name:String(fields.get('display_name')||''),nickname:String(fields.get('nickname')||''),labels:{tags,place:String(fields.get('place')||''),time:String(fields.get('time')||''),mood:String(fields.get('mood')||'')},accept_recognition:accept,recognition_digest:flow.recognition?.digest||''})});dialog.close();state.assetUpload=null;toast('素材已登记到我的素材库');loadAssetCatalog()}catch(error){register.disabled=false;toast(error.message,true)}})();return}
  const closeCustom=event.target.closest('[data-custom-asset-close]');
  if(closeCustom){event.preventDefault();event.stopImmediatePropagation();closeCustom.closest('dialog')?.close();return}
  const close=event.target.closest('[data-asset-preview-close]');
  if(close){event.preventDefault();event.stopImmediatePropagation();close.closest('dialog')?.close()}
},true);

document.addEventListener('submit',event=>{
  const uploadForm=event.target.closest('[data-custom-asset-upload-form]');
  if(uploadForm){event.preventDefault();event.stopImmediatePropagation();(async()=>{const submit=uploadForm.querySelector('button[type="submit"]');try{submit.disabled=true;submit.textContent='正在检查';const fields=new FormData(uploadForm),file=fields.get('file'),kind=String(fields.get('kind')||''),identifier=String(fields.get('identifier')||'').trim();if(!(file instanceof File)||!file.size)throw new Error('请选择需要上传的素材文件。');const response=await fetch('/production/api/v1/custom-assets/uploads',{method:'POST',headers:{'X-HaloCue-Filename':encodeURIComponent(file.name)},body:file});let uploaded;try{uploaded=await response.json()}catch(_){throw new Error('制作服务返回了无法解析的上传响应。')}if(!response.ok||uploaded.ok===false)throw new Error(uploaded.error?.message||'素材上传失败。');const checked=await productionJson('/custom-assets/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,upload_token:uploaded.upload_token,identifier})});state.assetUpload={kind,identifier,uploadToken:uploaded.upload_token,validation:checked.validation,recognition:null,recognitionError:''};uploadForm.querySelectorAll('[name="kind"],[name="file"],[name="identifier"]').forEach(control=>control.disabled=true);submit.hidden=true;renderCustomAssetReview()}catch(error){submit.disabled=false;submit.textContent='上传并检查';toast(error.message,true)}})();return}
  const editForm=event.target.closest('[data-custom-asset-edit-form]');
  if(editForm){event.preventDefault();event.stopImmediatePropagation();(async()=>{const submit=editForm.querySelector('button[type="submit"]'),dialog=editForm.closest('dialog');try{submit.disabled=true;const fields=new FormData(editForm),tags=String(fields.get('tags')||'').split(/[，,]/).map(value=>value.trim()).filter(Boolean);await productionJson(`/custom-assets/${encodeURIComponent(dialog.dataset.assetId)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_metadata_version:Number(dialog.dataset.metadataVersion||1),name:String(fields.get('name')||''),nickname:String(fields.get('nickname')||''),tags,labels:{place:String(fields.get('place')||''),time:String(fields.get('time')||''),mood:String(fields.get('mood')||'')}})});dialog.close();toast('素材信息已更新');loadAssetCatalog()}catch(error){submit.disabled=false;toast(error.message,true)}})();return}
  const attachForm=event.target.closest('[data-custom-asset-attach-form]');
  if(attachForm){event.preventDefault();event.stopImmediatePropagation();(async()=>{const submit=attachForm.querySelector('button[type="submit"]');try{submit.disabled=true;const runId=String(new FormData(attachForm).get('run_id')||''),dialog=attachForm.closest('dialog'),assetId=dialog.dataset.assetId;if(!runId)throw new Error('请选择制作任务。');const detail=await productionJson(`/production-runs/${encodeURIComponent(runId)}`);await productionJson(`/production-runs/${encodeURIComponent(runId)}/library-assets/${encodeURIComponent(assetId)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_draft_version:detail.draft.draft_version})});dialog.close();toast('素材已复制到所选制作任务')}catch(error){submit.disabled=false;toast(error.message,true)}})();return}
  const form=event.target.closest('[data-asset-search]');if(!form)return;
  event.preventDefault();event.stopImmediatePropagation();state.assetCatalog.query=String(new FormData(form).get('query')||'').trim();loadAssetCatalog();
},true);
