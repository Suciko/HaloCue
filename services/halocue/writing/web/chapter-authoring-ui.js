/* One chapter editing surface; scene revisions remain the only persisted manuscript. */
(function(){
  'use strict';
  const drafts=new Map();
  const storageKey='halocue.chapter-drafts.v1';
  let review=null,reviewKey='',reviewBusy=false,saveBusy=false,notice='',refreshAfterComposition=false,textSelection=null;
  try{for(const [key,value] of Object.entries(JSON.parse(sessionStorage.getItem(storageKey)||'{}')))drafts.set(key,value)}catch(_){/* a damaged session cache must not block writing */}
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const key=(work,scene)=>`${work}:${scene}`;
  const saveCache=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(Object.fromEntries(drafts)))}catch(_){}};
  const current=()=>({work:state.work,chapter:writingChapter()});
  const artifact=scene=>state.work?.artifacts?.find(item=>item.kind==='scene_script'&&item.scope_id===scene.id);
  const base=scene=>artifact(scene)?.current_revision?.id||null;
  const original=scene=>(artifact(scene)?.current_revision?.content?.blocks||[]).map(item=>({id:item.id,type:item.type,speaker:item.speaker||'',text:item.text||''}));
  const entry=scene=>drafts.get(key(state.work.id,scene.id));
  const anyDirty=chapter=>Boolean(chapter?.scenes?.some(scene=>entry(scene)));
  const hasConflict=chapter=>Boolean(chapter?.scenes?.some(scene=>entry(scene)&&entry(scene).base_revision_id!==base(scene)));
  const documentEditor=()=>window.HaloCueManuscriptDocument;
  const clean=blocks=>documentEditor().canonical(blocks);
  const row=(scene,block,index)=>`<article class="chapter-document-static" data-chapter-block data-block-id="${escape(block.id)}" aria-label="第 ${index+1} 段"><span class="chapter-document-static-kind">${escape(block.type==='dialogue'?block.speaker:block.type==='action'?'动作':'旁白')}</span><p>${escape(block.text||'')}</p></article>`;
  // Diff ranges use the original manuscript indices. Render every changed
  // range at that position, including inserts and deletes; keep unchanged
  // paragraphs in the same reading flow.
  function manuscriptRows(scene,blocks,proposal){
    const normal=(block,index)=>row(scene,block,index);
    if(!proposal)return blocks.map(normal).join('');
    const changes=Array.isArray(proposal.block_changes)?proposal.block_changes:[];
    if(entry(scene)||base(scene)!==(proposal.base_revision_id||null)||!changes.length)
      return blocks.map(normal).join('')+`<div class="chapter-inline-review-unavailable" role="status">${entry(scene)?'请先保存本地正文，再核对这份修改。':'正文版本与这份修改不一致，请让助手重新整理。'}<button type="button" class="quiet" data-reject="${escape(proposal.id)}">退回修改</button></div>`;
    const known=new Set(changes.map(change=>change.id));
    let selected=state.sceneDiffSelections[proposal.id];
    selected=selected instanceof Set?new Set([...selected].filter(id=>known.has(id))):new Set(known);
    state.sceneDiffSelections[proposal.id]=selected;
    const copy=items=>(items||[]).map(block=>`<div class="chapter-inline-copy"><small>${escape(block.speaker||({action:'动作',narration:'旁白'}[block.type])||'对白')}</small><p>${escape(block.text||'')}</p></div>`).join('')||'<p class="chapter-inline-empty">（无内容）</p>';
    const initialDraft=!blocks.length&&changes.every(change=>change.kind==='insert');
    const result=[];let cursor=0,offset=0;
    for(const change of [...changes].sort((a,b)=>a.base_start-b.base_start)){
      const start=Number(change.base_start)||0,end=Number(change.base_end)||start;
      if(start<cursor||end<start||end>blocks.length)return blocks.map(normal).join('')+`<p role="alert">修改范围无法核对，请重新整理。<button type="button" class="quiet" data-reject="${escape(proposal.id)}">保留原文</button></p>`;
      result.push(...blocks.slice(cursor,start).map((block,i)=>normal(block,cursor+i)));
      const label={insert:'新增段落',delete:'删除段落',replace:'段落修改'}[change.kind]||'段落修改';
      // Inserts share an original anchor; number them in the proposed prose.
      const number=start+1+(change.kind==='insert'?offset:0);
      result.push(`<article class="chapter-inline-change" data-review-change="${escape(change.id)}" tabindex="-1" aria-label="${label} · 第 ${number} 段"><header><span class="chapter-inline-location">${String(number).padStart(2,'0')} · ${label}</span><label class="chapter-inline-choice"><input type="checkbox" data-scene-change value="${escape(change.id)}" ${selected.has(change.id)?'checked':''} aria-label="采用第 ${number} 段修改"><span>采用这处修改</span></label></header><div class="chapter-inline-pair">${initialDraft?'':`<section class="chapter-inline-before" aria-label="改前"><b>改前</b>${copy(change.old_blocks)}</section>`}<section class="chapter-inline-after" aria-label="${initialDraft?'新正文':'改后'}">${initialDraft?'':'<b>改后</b>'}${copy(change.new_blocks)}</section></div><footer><button type="button" class="quiet" data-discuss-scene-change="${escape(change.id)}" data-review-proposal="${escape(proposal.id)}">继续调整这处</button></footer></article>`);
      // Hidden original rows retain capture/save ordering. They never become
      // candidate text or enter the local draft before explicit acceptance.
      result.push(`<div hidden data-inline-original>${blocks.slice(start,end).map((block,i)=>row(scene,block,start+i)).join('')}</div>`);
      cursor=end;
      offset+=(change.new_blocks||[]).length-(end-start);
    }
    result.push(...blocks.slice(cursor).map((block,i)=>normal(block,cursor+i)));
    return `<div class="chapter-inline-review ${initialDraft?'is-initial-draft':''}" data-scene-diff-root="${escape(proposal.id)}"><div class="chapter-inline-review-toolbar" role="toolbar" aria-label="本场正文改动"><div class="chapter-inline-review-status"><b>${initialDraft?'新稿待确认':'本场修改待确认'}</b><span data-scene-diff-count>已选择 ${selected.size} / ${changes.length} 项</span></div><div class="chapter-inline-review-actions"><button type="button" class="quiet" data-select-all-scene-changes="${escape(proposal.id)}">${selected.size===changes.length?'取消全选':'全部选择'}</button><button type="button" class="quiet" data-reject="${escape(proposal.id)}">${initialDraft?'放弃这份草稿':'全部保留原文'}</button><button type="button" class="primary" data-apply-scene-changes="${escape(proposal.id)}" ${selected.size?'':'disabled'}>应用 ${selected.size} 项修改</button></div></div>${result.join('')}</div>`;
  }
  const section=(scene,index)=>{
    const data=entry(scene),blocks=data?.blocks||original(scene),revision=artifact(scene)?.current_revision;
    const proposal=state.work?.proposals?.find(item=>item.kind==='scene_script'&&item.scope_id===scene.id&&item.status==='pending');
    const findings=(state.work?.review_findings||[]).filter(item=>item.scene_id===scene.id&&item.status==='open');
    const conflict=data&&data.base_revision_id!==base(scene);
    const canReview=proposal&&!data&&base(scene)===(proposal.base_revision_id||null)&&proposal.block_changes?.length;
    return `<section class="chapter-authoring-scene chapter-manuscript-scene ${scene.id===selectedScene()?.id?'is-current':''}" id="chapter-scene-${escape(scene.id)}" data-chapter-scene="${escape(scene.id)}"><header><div><span>场景 ${index+1}${revision?` · 第 ${revision.ordinal} 版`:''}${data?' · 未保存':''}</span><h3>${escape(scene.title)}</h3></div></header>${conflict?`<div class="chapter-authoring-conflict" role="alert"><b>本场服务端正文已更新；本地草稿尚未覆盖它。</b><details><summary>对比服务端正文与本地草稿</summary><div><section><b>服务端</b><pre>${escape(original(scene).map(item=>item.text).join('\n')||'（空白）')}</pre></section><section><b>本地草稿</b><pre>${escape(blocks.map(item=>item.text).join('\n')||'（空白）')}</pre></section></div></details><button type="button" class="quiet" data-chapter-rebase="${escape(scene.id)}">用当前服务端版本作为保存基准</button></div>`:''}<div data-chapter-blocks>${canReview?manuscriptRows(scene,blocks,proposal):`<div data-chapter-editor="${escape(scene.id)}"></div>`}</div>${proposal&&!canReview?`<div class="chapter-inline-review-unavailable" role="status">${data?'请先保存本地正文，再核对这份修改。':'正文版本与这份修改不一致，请让助手重新整理。'}<button type="button" class="quiet" data-reject="${escape(proposal.id)}">退回修改</button></div>`:''}${findings.length?`<details class="chapter-authoring-related"><summary>本场检查提示 ${findings.length} 项</summary>${sceneReviewFindingsMarkup(findings)}</details>`:''}</section>`;
  };

  const sceneThreadPending=()=>Boolean(state.sceneId&&!state._sceneThreadErrorScene&&!sceneConversationThread(selectedScene()));
  const reviewMarkup=chapter=>{
    if(!review)return '<p>正在读取章节检查状态…</p>';
    const status=review.status,labels={not_checked:'尚未检查',running:'检查中',failed:'检查失败',stale:'正文已变化，需要重查',blocked:'有问题待处理',awaiting_changes:'待确认剧情记忆',complete:'检查完成'};
    const items=review.proposal?.candidate?.items||[],findings=review.findings||[];
    const pending=status==='awaiting_changes'&&!review.stale;
    const blocked=reviewBusy||sceneThreadPending()||anyDirty(chapter)||!chapter.scenes?.some(scene=>original(scene).some(block=>block.text.trim()));
    const itemText=item=>`<span><b>${escape(item.title||'剧情记忆')}</b><small>${escape(item.summary||'')}</small></span>`;
    const memories=items.length?(pending?`<fieldset class="chapter-review-memories"><legend>记住哪些剧情进展？</legend><p>选中的内容会供后续写作参考。</p>${items.map(item=>`<label class="chapter-review-item"><input type="checkbox" data-chapter-review-item value="${escape(item.id)}" checked>${itemText(item)}</label>`).join('')}</fieldset>`:`<details class="chapter-review-memories"><summary>${status==='complete'?'查看本次剧情记忆':'查看待确认剧情记忆'} · ${items.length} 条</summary>${items.map(item=>`<div class="chapter-review-memory">${itemText(item)}</div>`).join('')}</details>`):'';
    return `<header class="chapter-review-head"><div class="chapter-review-title"><h3>检查正文与连贯性</h3><p class="chapter-review-status" role="status">${escape(labels[status]||status)}${review.stale?' · 旧结果仅供参考':''}</p></div><button type="button" class="quiet" data-chapter-review-run title="检查本章各场正文、前后连贯性，并整理剧情记忆；会调用模型" ${blocked?'disabled':''}>${reviewBusy?'正在检查…':status==='not_checked'?'检查本章':'重新检查'}</button></header><div class="chapter-review-body">${review.result?.error?`<p class="chapter-authoring-error">${escape(review.result.error.message||review.result.error)}</p>`:''}${findings.length?`<details><summary>查看检查发现 · ${findings.length} 项</summary><ul>${findings.map(item=>`<li>${escape(item.message||item.summary||item.kind||'检查发现')}</li>`).join('')}</ul></details>`:''}${memories}${pending?`<div class="chapter-review-actions"><button type="button" class="primary" data-chapter-review-decide="${items.length?'accept':'keep'}" ${blocked?'disabled':''}>${items.length?'保存选中的剧情记忆':'完成检查'}</button>${items.length?`<button type="button" class="quiet" data-chapter-review-decide="keep" ${blocked?'disabled':''}>不添加记忆</button>`:''}</div>`:''}${anyDirty(chapter)?'<small>保存正文后再检查。</small>':''}</div>`;
  };

  function render(host){
    const {work,chapter}=current();if(!work||!chapter)return false;
    const focus=documentEditor().preserveFocus(),scenes=chapter.scenes||[],dirty=anyDirty(chapter),rkey=`${work.id}:${chapter.id}:${work.version}`;
    host.innerHTML=`<div class="chapter-authoring chapter-continuous" data-chapter-id="${escape(chapter.id)}"><header class="chapter-continuous-head"><div><p class="eyebrow">章节正文 <span class="chapter-save-state" data-chapter-save-state aria-live="polite">${escape(statusText())}</span></p><h2>${escape(chapter.title)}</h2></div></header><div class="chapter-authoring-save" role="toolbar" aria-label="章节正文操作"><div class="chapter-document-history"><button type="button" class="quiet" data-chapter-undo title="Ctrl / ⌘ + Z">撤销</button><button type="button" class="quiet" data-chapter-redo title="Ctrl / ⌘ + Shift + Z">重做</button><span class="chapter-document-hint">直接点击正文修改 · Enter 分段</span></div><button type="button" class="primary" data-chapter-save ${dirty&&!saveBusy&&!hasConflict(chapter)?'':'disabled'}>${saveBusy?'保存中…':'保存整章'}</button></div>${scenes.length?`<div class="chapter-manuscript-flow">${scenes.map(section).join('')}</div>`:'<div class="chapter-authoring-empty"><p>这一章还没有正文。</p><button type="button" class="primary" data-chapter-start>开始写本章</button><button type="button" class="quiet" data-stage-jump="structure">先规划场景</button></div>'}<section class="chapter-review" data-chapter-review aria-label="整章检查">${scenes.length?reviewMarkup(chapter):'<p>先建立场景并保存正文。</p>'}</section></div>`;
    documentEditor().retain(new Set(scenes.map(scene=>key(work.id,scene.id))));
    for(const container of host.querySelectorAll('[data-chapter-editor]')){
      const scene=scenes.find(item=>item.id===container.dataset.chapterEditor);
      documentEditor().mount(container,{key:key(work.id,scene.id),blocks:entry(scene)?.blocks||original(scene),onChange:blocks=>capture(scene.id,null,blocks),onSelection:selection=>selectionActions(scene,selection)});
    }
    documentEditor().restoreFocus(focus);syncStatus();
    if(rkey!==reviewKey){reviewKey=rkey;review=null;void fetchReview(work.id,chapter.id,rkey)}
    return true;
  }
  function statusText(){return saveBusy?'保存中…':hasConflict(writingChapter())?'正文版本有冲突':/失败|冲突/.test(notice)?notice:anyDirty(writingChapter())?'有未保存修改':notice||'已保存';}
  function syncStatus(){
    const {chapter}=current();if(!chapter||!document.querySelector('.chapter-authoring'))return;
    const dirty=anyDirty(chapter),label=document.querySelector('[data-chapter-save-state]'),button=document.querySelector('[data-chapter-save]');
    if(label)label.textContent=statusText();
    if(button)button.disabled=!dirty||saveBusy||hasConflict(chapter);
    for(const action of ['undo','redo']){const control=document.querySelector(`[data-chapter-${action}]`);if(control)control.disabled=!documentEditor().can(action);}
    const top=document.getElementById('saveStatus');
    if(top){top.textContent=saveBusy?'正文保存中…':hasConflict(chapter)?'正文版本有冲突':dirty?'正文未保存':'已保存';if(/失败|冲突/.test(notice))top.textContent=notice;top.dataset.state=/失败|冲突/.test(notice)||hasConflict(chapter)?'error':saveBusy?'busy':dirty?'dirty':'saved';top.title=/失败|冲突/.test(notice)?notice:dirty?'手工正文修改尚未建立正式版本':'正文已保存到本地';}
  }
  function selectionActions(scene,selection){
    textSelection=null;if(!selection)return null;
    if(!base(scene)||entry(scene))return '<span>保存正文后可让助手改写</span>';
    textSelection={sceneId:scene.id,revision_id:base(scene),...selection};
    return '<button type="button" data-chapter-selection data-ask-scene-selection>问助手</button><button type="button" data-chapter-selection data-suggest-scene-selection>建议改写</button>';
  }
  function refreshReview(){const {chapter}=current();const panel=document.querySelector('.chapter-authoring [data-chapter-review]');if(chapter&&panel)panel.innerHTML=chapter.scenes?.length?reviewMarkup(chapter):'<p>先建立场景并保存正文。</p>'}
  async function fetchReview(workId,chapterId,rkey){try{const result=await api(`/works/${workId}/chapters/${chapterId}/review`);if(reviewKey===rkey&&state.work?.id===workId&&writingChapter()?.id===chapterId){review=result;refreshReview()}}catch(error){if(reviewKey===rkey&&state.work?.id===workId&&writingChapter()?.id===chapterId){review={status:'failed',result:{error:error.message}};refreshReview()}}}
  function capture(sceneId,container=null,provided=null){
    const scene=writingChapter()?.scenes?.find(item=>item.id===sceneId);if(!scene)return;
    const blocks=provided||documentEditor().get(key(state.work.id,sceneId))?.blocks();if(!blocks)return;
    const previous=entry(scene);
    if(JSON.stringify(clean(blocks))===JSON.stringify(original(scene)))drafts.delete(key(state.work.id,sceneId));
    else drafts.set(key(state.work.id,sceneId),{base_revision_id:previous?previous.base_revision_id:base(scene),blocks});
    notice='';saveCache();
    if(state.sceneTextSelection?.sceneId===sceneId)clearSceneTextSelection();
    const node=document.querySelector(`[data-chapter-scene="${CSS.escape(sceneId)}"]`),sceneStatus=node?.querySelector('header span');
    if(sceneStatus)sceneStatus.textContent=sceneStatus.textContent.replace(/ · 未保存$/,'')+(entry(scene)?' · 未保存':'');
    syncStatus();if(typeof syncSceneManuscriptNotice==='function')syncSceneManuscriptNotice();
    for(const button of document.querySelectorAll('[data-chapter-review-run],[data-chapter-review-decide]'))button.disabled=anyDirty(writingChapter())||reviewBusy||sceneThreadPending()||!writingChapter()?.scenes?.some(scene=>original(scene).some(block=>block.text.trim()));
    window.HaloCueFirstTask?.mount?.();window.HaloCueGuidance?.mount?.();
  }
  function refresh(){
    if(documentEditor().composing){refreshAfterComposition=true;return;}
    const host=document.querySelector('.chapter-authoring')?.parentElement;
    if(!host)return;
    const readingWorkspace=host.closest('.workspace');
    const readingTop=readingWorkspace?.scrollTop;
    const previous=document.querySelector('#sceneConversationForm textarea[name="text"]');
    const composer=previous?{
      value:previous.value,
      start:previous.selectionStart,
      end:previous.selectionEnd,
      focused:previous===document.activeElement,
    }:null;
    render(host);
    // Local chapter refreshes replace the manuscript DOM without the root
    // render pipeline. Restore the same explicit scene context controls.
    if(typeof decorateSceneContext==='function')decorateSceneContext();
    window.HaloCueWritingWorkbench?.refreshChrome?.();
    window.HaloCueKnowledgeImpact?.mount?.();
    window.HaloCueGuidance?.mount?.();
    window.HaloCueFirstTask?.mount?.();
    const input=document.querySelector('#sceneConversationForm textarea[name="text"]');
    if(input&&composer){
      input.value=composer.value;
      input.setSelectionRange(composer.start,composer.end);
      if(composer.focused&&!input.disabled)input.focus({preventScroll:true});
    }
    // Review data arrives after the Agent's root render and can rebuild this
    // manuscript independently. Preserve the current position, including an
    // explicit inline-change jump, rather than relying on browser anchoring.
    if(readingWorkspace?.isConnected&&typeof readingTop==='number')readingWorkspace.scrollTop=readingTop;
  }
  document.addEventListener('compositionend',()=>queueMicrotask(()=>{if(refreshAfterComposition){refreshAfterComposition=false;refresh();}}));
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-chapter-start],[data-chapter-save],[data-chapter-review-run],[data-chapter-review-decide],[data-chapter-rebase],[data-chapter-undo],[data-chapter-redo],[data-save-for-agent],[data-chapter-selection]');
    if(!button||!button.closest('.chapter-authoring')&&!(button.hasAttribute('data-save-for-agent')&&document.querySelector('.chapter-authoring')))return;
    if(button.hasAttribute('data-chapter-selection')){
      if(!textSelection){event.preventDefault();event.stopImmediatePropagation();return;}
      state.sceneReviewTarget=null;state.sceneTextSelection={...textSelection};return;
    }
    event.preventDefault();event.stopImmediatePropagation();
    if(button.hasAttribute('data-chapter-undo')||button.hasAttribute('data-chapter-redo')){documentEditor().run(button.hasAttribute('data-chapter-undo')?'undo':'redo');syncStatus();return;}
    if(button.hasAttribute('data-save-for-agent')){void saveChapter();return;}
    if(button.hasAttribute('data-chapter-start')){void startChapter();return;}
    if(button.hasAttribute('data-chapter-save')){void saveChapter();return;}
    if(button.hasAttribute('data-chapter-review-run')){void runReview();return;}
    if(button.hasAttribute('data-chapter-review-decide')){void decideReview(button.dataset.chapterReviewDecide);return;}
    const scene=writingChapter()?.scenes?.find(item=>item.id===button.dataset.chapterRebase),draft=scene&&entry(scene);
    if(draft){draft.base_revision_id=base(scene);saveCache();notice='已选择当前服务端版本作为保存基准；请核对本地正文后保存。';refresh();}
  },true);
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.isComposing||event.altKey||event.shiftKey||!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=='s')return;
    const host=document.querySelector('.chapter-authoring');
    if(!host||document.querySelector('dialog[open]')||event.target.closest?.('input,textarea,[contenteditable]')&&!host.contains(event.target))return;
    event.preventDefault();if(!event.repeat)void saveChapter();
  });
  async function startChapter(){const {work,chapter}=current();if(!work||!chapter||chapter.scenes?.length)return;notice='正在建立正文场景…';refresh();try{const result=await api(`/works/${work.id}/chapters/${chapter.id}/scenes`,{method:'POST',body:JSON.stringify({expected_version:work.version,title:'正文'})});if(state.work?.id!==work.id)return;state.work=result.work;state.sceneId=result.scene_id;drafts.set(key(work.id,result.scene_id),{base_revision_id:null,blocks:[{id:makeClientBlockId(),type:'narration',speaker:'',text:''}]});saveCache();notice='可以开始写作';refresh();documentEditor().get(key(work.id,result.scene_id))?.focus()}catch(error){notice=`建立失败：${error.message}`;refresh()}}
  async function saveChapter(){
    const {work,chapter}=current(),session=hcWorkLoadEpoch;
    if(!work||!chapter||saveBusy)return;
    for(const node of document.querySelectorAll('.chapter-authoring [data-chapter-editor]'))capture(node.dataset.chapterEditor);
    if(hasConflict(chapter)||!anyDirty(chapter))return;
    saveBusy=true;notice='保存中…';refresh();
    try{
      // This owned background write bumps work.version. Use its completed
      // response before saving; external manuscript conflicts still need rebase.
      await state._sceneThreadPromise;
      if(state.work?.id!==work.id||hcWorkLoadEpoch!==session||writingChapter()?.id!==chapter.id)return;
      const latest=writingChapter();
      if(hasConflict(latest)){notice='服务器正文已更新，请先核对本地草稿。';return;}
      const modified=latest.scenes.filter(scene=>entry(scene)).map(scene=>({scene_id:scene.id,expected_base_revision_id:entry(scene).base_revision_id,blocks:clean(entry(scene).blocks)}));
      if(!modified.length)return;
      const result=await api(`/works/${work.id}/chapters/${chapter.id}/manuscript`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,scenes:modified})});
      if(state.work?.id!==work.id||hcWorkLoadEpoch!==session)return;
      if(result.work.version>=state.work.version)state.work=result.work;
      for(const item of modified){
        const draft=drafts.get(key(work.id,item.scene_id));
        if(JSON.stringify(draft&&clean(draft.blocks))===JSON.stringify(item.blocks))drafts.delete(key(work.id,item.scene_id));
        else if(draft?.base_revision_id===item.expected_base_revision_id){
          const saved=result.work.artifacts.find(artifact=>artifact.kind==='scene_script'&&artifact.scope_id===item.scene_id);
          draft.base_revision_id=saved?.current_revision?.id||null;
        }
      }
      saveCache();notice='整章已保存';reviewKey='';refresh();
    }catch(error){
      notice=error.status===409?'保存冲突：本地修改已保留。请核对服务器新版本后重试。':`保存失败：${error.message}`;
      if(error.status===409){try{await loadWork(work.id,{renderNow:false});reviewKey=''}catch(_){}}
      refresh();
    }finally{saveBusy=false;refresh()}
  }
  async function runReview(){const {work,chapter}=current();if(!work||!chapter||reviewBusy||sceneThreadPending()||anyDirty(chapter)||!chapter.scenes?.some(scene=>original(scene).some(block=>block.text.trim())))return;reviewBusy=true;notice='正在检查整章…';refresh();try{await runDurableAgentJob('chapter.review',chapter.id,{expected_version:work.version});if(state.work?.id===work.id){reviewKey='';notice='整章检查已完成';refresh()}}catch(error){notice=`整章检查失败：${error.message}`;reviewKey='';refresh()}finally{reviewBusy=false;refresh()}}
  async function decideReview(decision){const {work,chapter}=current();if(!work||!chapter||!review?.id||reviewBusy||anyDirty(chapter))return;const selected=[...document.querySelectorAll('[data-chapter-review-item]:checked')].map(node=>node.value);if(decision==='accept'&&!selected.length){notice='请至少选择一项变化，或选择保持当前设定。';refresh();return}reviewBusy=true;try{const result=await api(`/works/${work.id}/chapters/${chapter.id}/review:decide`,{method:'POST',body:JSON.stringify({review_id:review.id,expected_version:work.version,decision,...(decision==='accept'?{selected_item_ids:selected}:{})})});if(state.work?.id===work.id){state.work=result.work;review=result.review;reviewKey=`${work.id}:${chapter.id}:${state.work.version}`;notice='已记录整章变化决定';refresh()}}catch(error){notice=`决定未保存：${error.message}`;refresh()}finally{reviewBusy=false;refresh()}}
  window.addEventListener('beforeunload',event=>{if(drafts.size){event.preventDefault();event.returnValue=''}});
  window.HaloCueChapterAuthoring={render,get active(){return Boolean(document.querySelector('.chapter-authoring'))},syncStatus,save:saveChapter,get hasUnsavedDrafts(){return anyDirty(writingChapter())}};
})();
