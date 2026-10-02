/* One chapter editing surface; scene revisions remain the only persisted manuscript. */
(function(){
  'use strict';
  const drafts=new Map();
  const viewModes=new Map();
  const storageKey='halocue.chapter-drafts.v1';
  let review=null,reviewKey='',reviewBusy=false,saveBusy=false,notice='';
  try{for(const [key,value] of Object.entries(JSON.parse(sessionStorage.getItem(storageKey)||'{}')))drafts.set(key,value)}catch(_){/* a damaged session cache must not block writing */}
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const key=(work,scene)=>`${work}:${scene}`;
  const saveCache=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(Object.fromEntries(drafts)))}catch(_){}};
  const current=()=>({work:state.work,chapter:writingChapter()});
  const artifact=scene=>state.work?.artifacts?.find(item=>item.kind==='scene_script'&&item.scope_id===scene.id);
  const base=scene=>artifact(scene)?.current_revision?.id||null;
  const original=scene=>(artifact(scene)?.current_revision?.content?.blocks||[]).map(item=>({id:item.id,type:item.type,speaker:item.speaker||'',text:item.text||''}));
  const sizeField=field=>{field.style.height='auto';field.style.height=`${Math.max(36,field.scrollHeight+2)}px`};
  const entry=scene=>drafts.get(key(state.work.id,scene.id));
  const anyDirty=chapter=>Boolean(chapter?.scenes?.some(scene=>entry(scene)));
  const hasConflict=chapter=>Boolean(chapter?.scenes?.some(scene=>entry(scene)&&entry(scene).base_revision_id!==base(scene)));
  const modeKey=(work,chapter)=>`${work.id}:${chapter.id}`;
  const viewMode=(work,chapter)=>viewModes.get(modeKey(work,chapter))||'edit';
  const row=(scene,block,index)=>{
    const number=index+1;
    const options=[['action','动作'],['narration','旁白'],['dialogue','对白']]
      .map(([value,label])=>'<option value="'+value+'"'+(block.type===value?' selected':'')+'>'+label+'</option>').join('');
    return [
      '<article class="chapter-authoring-block" data-chapter-block data-block-id="'+escape(block.id)+'" data-block-type="'+escape(block.type)+'" aria-label="第 '+number+' 段">',
      '<span class="chapter-authoring-number" aria-hidden="true">'+String(number).padStart(2,'0')+'</span>',
      '<div class="chapter-authoring-block-body"><div class="chapter-authoring-block-meta">',
      '<span class="chapter-authoring-type"><select aria-label="段落类型" data-chapter-type>'+options+'</select></span>',
      '<input aria-label="说话人" data-chapter-speaker value="'+escape(block.speaker||'')+'" placeholder="说话人"'+(block.type==='dialogue'?'':' hidden')+'>',
      '</div><textarea aria-label="第 '+number+' 段正文" data-chapter-text rows="1" placeholder="写下这一段…">'+escape(block.text||'')+'</textarea></div>',
      '<div class="chapter-authoring-block-actions"><button type="button" data-chapter-move="up" aria-label="上移段落" title="上移段落">↑</button><button type="button" data-chapter-move="down" aria-label="下移段落" title="下移段落">↓</button><button type="button" data-chapter-remove aria-label="删除段落" title="删除段落">×</button></div>',
      '</article>',
    ].join('');
  };
  const insertRow=(block,index)=>'<div class="chapter-authoring-insert-row" data-chapter-insert-row><button type="button" class="chapter-authoring-insert" data-chapter-add data-chapter-after="'+escape(block.id)+'" aria-label="在第 '+(index+1)+' 段后插入段落" title="在这里插入段落"><span aria-hidden="true">+</span></button></div>';
  const renumberBlocks=container=>{
    [...container.querySelectorAll('[data-chapter-block]')].forEach((node,index)=>{
      const number=index+1;
      node.setAttribute('aria-label','第 '+number+' 段');
      node.querySelector('.chapter-authoring-number').textContent=String(number).padStart(2,'0');
      node.querySelector('[data-chapter-text]').setAttribute('aria-label','第 '+number+' 段正文');
      node.nextElementSibling?.querySelector('[data-chapter-add]')?.setAttribute('aria-label','在第 '+number+' 段后插入段落');
    });
  };
  const readRow=(scene,block,index)=>`<button type="button" class="chapter-reading-block" data-chapter-read-block="${escape(block.id)}" data-block-type="${escape(block.type)}" aria-label="编辑第 ${index+1} 段"><span class="chapter-reading-kind">${block.type==='dialogue'?escape(block.speaker||'对白'):block.type==='action'?'动作':'旁白'}</span><span class="chapter-reading-text">${escape(block.text||'点击写下这一段…')}</span></button>`;
  // Diff ranges use the original manuscript indices. Render every changed
  // range at that position, including inserts and deletes; keep unchanged
  // paragraphs in the same reading flow.
  function manuscriptRows(scene,blocks,reading,proposal){
    const normal=(block,index)=>reading?readRow(scene,block,index):row(scene,block,index)+insertRow(block,index);
    if(!proposal)return blocks.map(normal).join('');
    const changes=Array.isArray(proposal.block_changes)?proposal.block_changes:[];
    if(entry(scene)||base(scene)!==(proposal.base_revision_id||null)||!changes.length)
      return blocks.map(normal).join('')+`<div class="chapter-inline-review-unavailable" role="status">${entry(scene)?'请先保存本地正文，再核对这份修改。':'正文版本与这份修改不一致，请让助手重新整理。'}<button type="button" class="quiet" data-reject="${escape(proposal.id)}">退回修改</button></div>`;
    const known=new Set(changes.map(change=>change.id));
    let selected=state.sceneDiffSelections[proposal.id];
    selected=selected instanceof Set?new Set([...selected].filter(id=>known.has(id))):new Set(known);
    state.sceneDiffSelections[proposal.id]=selected;
    const copy=items=>(items||[]).map(block=>`<div class="chapter-inline-copy"><small>${escape(block.speaker||({action:'动作',narration:'旁白'}[block.type])||'对白')}</small><p>${escape(block.text||'')}</p></div>`).join('')||'<p class="chapter-inline-empty">（无内容）</p>';
    const result=[];let cursor=0;
    for(const change of [...changes].sort((a,b)=>a.base_start-b.base_start)){
      const start=Number(change.base_start)||0,end=Number(change.base_end)||start;
      if(start<cursor||end<start||end>blocks.length)return blocks.map(normal).join('')+`<p role="alert">修改范围无法核对，请重新整理。<button type="button" class="quiet" data-reject="${escape(proposal.id)}">保留原文</button></p>`;
      result.push(...blocks.slice(cursor,start).map((block,i)=>normal(block,cursor+i)));
      const label={insert:'新增段落',delete:'删除段落',replace:'段落修改'}[change.kind]||'段落修改';
      result.push(`<article class="chapter-inline-change" data-review-change="${escape(change.id)}" tabindex="-1" aria-label="${label} · 第 ${start+1} 段"><header><span class="chapter-inline-location">${String(start+1).padStart(2,'0')} · ${label}</span><label class="chapter-inline-choice"><input type="checkbox" data-scene-change value="${escape(change.id)}" ${selected.has(change.id)?'checked':''} aria-label="采用第 ${start+1} 段修改"><span>采用这处修改</span></label></header><div class="chapter-inline-pair"><section class="chapter-inline-before" aria-label="改前"><b>改前</b>${copy(change.old_blocks)}</section><section class="chapter-inline-after" aria-label="改后"><b>改后</b>${copy(change.new_blocks)}</section></div><footer><button type="button" class="primary" data-apply-scene-changes="${escape(proposal.id)}" ${selected.size?'':'disabled'}>应用 ${selected.size} 项修改</button><button type="button" class="quiet" data-discuss-scene-change="${escape(change.id)}" data-review-proposal="${escape(proposal.id)}">继续调整这处</button>${changes.length===1?`<button type="button" class="quiet" data-reject="${escape(proposal.id)}">保留原文</button>`:''}</footer></article>`);
      // Hidden original rows retain capture/save ordering. They never become
      // candidate text or enter the local draft before explicit acceptance.
      result.push(`<div hidden data-inline-original>${blocks.slice(start,end).map((block,i)=>row(scene,block,start+i)).join('')}</div>`);
      cursor=end;
    }
    result.push(...blocks.slice(cursor).map((block,i)=>normal(block,cursor+i)));
    return `<div class="chapter-inline-review" data-scene-diff-root="${escape(proposal.id)}">${result.join('')}${changes.length>1?`<footer class="chapter-inline-review-summary"><span data-scene-diff-count>已选择 ${selected.size} / ${changes.length} 项</span><button type="button" class="quiet" data-select-all-scene-changes="${escape(proposal.id)}">${selected.size===changes.length?'取消全选':'全部选择'}</button><button type="button" class="quiet" data-reject="${escape(proposal.id)}">全部保留原文</button></footer>`:''}</div>`;
  }
  const section=(scene,index)=>{const data=entry(scene),blocks=data?.blocks||original(scene),reading=viewMode(state.work,writingChapter())==='read',revision=artifact(scene)?.current_revision,proposal=state.work?.proposals?.find(item=>item.kind==='scene_script'&&item.scope_id===scene.id&&item.status==='pending'),findings=(state.work?.review_findings||[]).filter(item=>item.scene_id===scene.id&&item.status==='open'),conflict=data&&data.base_revision_id!==base(scene),empty=!blocks.length;return `<section class="chapter-authoring-scene chapter-manuscript-scene ${scene.id===selectedScene()?.id?'is-current':''}" id="chapter-scene-${escape(scene.id)}" data-chapter-scene="${escape(scene.id)}"><header><div><span>场景 ${index+1}${revision?` · 第 ${revision.ordinal} 版`:''}${data?' · 未保存':''}</span><h3>${escape(scene.title)}</h3></div></header>${conflict?`<div class="chapter-authoring-conflict" role="alert"><b>本场服务端正文已更新；本地草稿尚未覆盖它。</b><details><summary>对比服务端正文与本地草稿</summary><div><section><b>服务端</b><pre>${escape(original(scene).map(item=>item.text).join('\n')||'（空白）')}</pre></section><section><b>本地草稿</b><pre>${escape(blocks.map(item=>item.text).join('\n')||'（空白）')}</pre></section></div></details><button type="button" class="quiet" data-chapter-rebase="${escape(scene.id)}">用当前服务端版本作为保存基准</button></div>`:''}<div data-chapter-blocks>${manuscriptRows(scene,blocks,reading,proposal)}</div>${reading?'':empty?`<div class="chapter-authoring-empty-scene"><span class="chapter-authoring-empty-mark" aria-hidden="true">文</span><div><b>这一场还没有正文</b><p>先写下第一个段落；正文会留在本地草稿，保存后才建立修订。</p></div><button type="button" class="primary" data-chapter-add="${escape(scene.id)}">开始写作</button></div>`:''}${findings.length?`<details class="chapter-authoring-related"><summary>本场检查提示 ${findings.length} 项</summary>${sceneReviewFindingsMarkup(findings)}</details>`:''}</section>`};

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

  function render(host){const {work,chapter}=current();if(!work||!chapter)return false;const scenes=chapter.scenes||[],dirty=anyDirty(chapter),mode=viewMode(work,chapter),rkey=`${work.id}:${chapter.id}:${work.version}`;host.innerHTML=`<div class="chapter-authoring chapter-continuous" data-chapter-id="${escape(chapter.id)}"><header class="chapter-continuous-head"><div><p class="eyebrow">章节正文 <span class="chapter-save-state" data-chapter-save-state aria-live="polite">${escape(notice|| (dirty?'有未保存修改':'已保存'))}</span></p><h2>${escape(chapter.title)}</h2></div></header><div class="chapter-authoring-save" role="toolbar" aria-label="章节正文操作"><div class="chapter-view-switch" role="group" aria-label="正文显示模式"><button type="button" data-chapter-view="read" aria-pressed="${mode==='read'}" class="${mode==='read'?'active':''}">阅读</button><button type="button" data-chapter-view="edit" aria-pressed="${mode==='edit'}" class="${mode==='edit'?'active':''}">编辑</button></div><button type="button" class="primary" data-chapter-save ${dirty&&!saveBusy&&!hasConflict(chapter)?'':'disabled'}>${saveBusy?'保存中…':'保存整章'}</button></div>${scenes.length?`<div class="chapter-manuscript-flow">${scenes.map(section).join('')}</div>`:'<div class="chapter-authoring-empty"><p>这一章还没有正文。</p><button type="button" class="primary" data-chapter-start>开始写本章</button><button type="button" class="quiet" data-stage-jump="structure">先规划场景</button></div>'}<section class="chapter-review" data-chapter-review aria-label="整章检查">${scenes.length?reviewMarkup(chapter):'<p>先建立场景并保存正文。</p>'}</section></div>`;for(const field of host.querySelectorAll('[data-chapter-text]'))sizeField(field);for(const review of host.querySelectorAll('.chapter-inline-review')){for(const field of review.querySelectorAll('[data-chapter-text],[data-chapter-speaker]'))field.readOnly=true;for(const button of review.querySelectorAll('[data-chapter-type],[data-chapter-add],[data-chapter-remove],[data-chapter-move]'))button.disabled=true;}if(rkey!==reviewKey){reviewKey=rkey;review=null;void fetchReview(work.id,chapter.id,rkey)}return true}
  async function fetchReview(workId,chapterId,rkey){try{const result=await api(`/works/${workId}/chapters/${chapterId}/review`);if(reviewKey===rkey&&state.work?.id===workId&&writingChapter()?.id===chapterId){review=result;refresh()}}catch(error){if(reviewKey===rkey){review={status:'failed',result:{error:error.message}};refresh()}}}
  function capture(sceneId,container=document.querySelector(`[data-chapter-scene="${CSS.escape(sceneId)}"]`)){const scene=writingChapter()?.scenes?.find(item=>item.id===sceneId);if(!scene||!container)return;const previous=entry(scene),blocks=[...container.querySelectorAll('[data-chapter-block]')].map(node=>({id:node.dataset.blockId,type:node.querySelector('[data-chapter-type]').value,speaker:node.querySelector('[data-chapter-speaker]').value,text:node.querySelector('[data-chapter-text]').value}));if(JSON.stringify(blocks)===JSON.stringify(original(scene))){drafts.delete(key(state.work.id,sceneId))}else drafts.set(key(state.work.id,sceneId),{base_revision_id:previous?previous.base_revision_id:base(scene),blocks});saveCache();const sceneStatus=container.querySelector('header span');if(sceneStatus)sceneStatus.textContent=sceneStatus.textContent.replace(/ · 未保存$/,'')+(entry(scene)?' · 未保存':'');const dirty=anyDirty(writingChapter()),save=document.querySelector('[data-chapter-save]'),label=document.querySelector('[data-chapter-save-state]');if(save)save.disabled=!dirty||hasConflict(writingChapter())||saveBusy;if(label)label.textContent=dirty?'有未保存修改':'已保存';for(const button of document.querySelectorAll('[data-chapter-review-run],[data-chapter-review-decide]'))button.disabled=dirty||reviewBusy||sceneThreadPending()||!writingChapter()?.scenes?.some(scene=>original(scene).some(block=>block.text.trim()))}
  function refresh(){
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
  document.addEventListener('input',event=>{const node=event.target.closest('[data-chapter-scene]');if(event.target.matches('[data-chapter-text]'))sizeField(event.target);if(node&&event.target.matches('[data-chapter-type],[data-chapter-speaker],[data-chapter-text]'))capture(node.dataset.chapterScene,node)},true);
  document.addEventListener('change',event=>{if(event.target.matches('[data-chapter-type]')){const row=event.target.closest('[data-chapter-block]');row.dataset.blockType=event.target.value;row.querySelector('[data-chapter-speaker]').hidden=event.target.value!=='dialogue';capture(row.closest('[data-chapter-scene]').dataset.chapterScene)}},true);
  document.addEventListener('click',event=>{const button=event.target.closest('[data-chapter-start],[data-chapter-add],[data-chapter-remove],[data-chapter-move],[data-chapter-save],[data-chapter-review-run],[data-chapter-review-decide],[data-chapter-select-scene],[data-chapter-rebase],[data-chapter-view],[data-chapter-read-block]');if(!button||!button.closest('.chapter-authoring'))return;event.preventDefault();event.stopImmediatePropagation();const sceneNode=button.closest('[data-chapter-scene]');if(button.hasAttribute('data-chapter-view')||button.hasAttribute('data-chapter-read-block')){const {work,chapter}=current();if(!work||!chapter)return;if(viewMode(work,chapter)==='edit')for(const node of document.querySelectorAll('.chapter-authoring [data-chapter-scene]'))capture(node.dataset.chapterScene,node);const focusScene=sceneNode?.dataset.chapterScene,focusBlock=button.dataset.chapterReadBlock;viewModes.set(modeKey(work,chapter),button.hasAttribute('data-chapter-read-block')?'edit':button.dataset.chapterView);refresh();if(focusBlock)document.querySelector(`[data-chapter-scene="${CSS.escape(focusScene)}"] [data-block-id="${CSS.escape(focusBlock)}"] [data-chapter-text]`)?.focus();return}if(button.hasAttribute('data-chapter-start')){void startChapter();return}if(button.hasAttribute('data-chapter-save')){void saveChapter();return}if(button.hasAttribute('data-chapter-review-run')){void runReview();return}if(button.hasAttribute('data-chapter-review-decide')){void decideReview(button.dataset.chapterReviewDecide);return}if(button.hasAttribute('data-chapter-rebase')){const scene=writingChapter()?.scenes?.find(item=>item.id===button.dataset.chapterRebase),draft=scene&&entry(scene);if(draft){draft.base_revision_id=base(scene);saveCache();notice='已选择当前服务端版本作为保存基准；请核对本地正文后保存。';refresh()}return}if(button.hasAttribute('data-chapter-select-scene')){state.sceneId=button.dataset.chapterSelectScene;refresh();document.querySelector(`[data-chapter-scene="${CSS.escape(state.sceneId)}"] details`)?.setAttribute('open','');return}if(!sceneNode)return;const sceneId=sceneNode.dataset.chapterScene,container=sceneNode.querySelector('[data-chapter-blocks]');if(button.hasAttribute('data-chapter-add')){const rows=[...container.querySelectorAll('[data-chapter-block]')];const anchor=button.dataset.chapterAfter?rows.find(node=>node.dataset.blockId===button.dataset.chapterAfter):null;const index=anchor?rows.indexOf(anchor)+1:rows.length;const previous=anchor||rows[rows.length-1]||null;const inheritedType=previous?.querySelector('[data-chapter-type]')?.value;const type=['action','narration','dialogue'].includes(inheritedType)?inheritedType:'narration';const speaker=type==='dialogue'?(previous.querySelector('[data-chapter-speaker]')?.value||''):'';const block={id:makeClientBlockId(),type,speaker,text:''};const next=rows[index],markup=row(null,block,index)+insertRow(block,index);if(next)next.insertAdjacentHTML('beforebegin',markup);else container.insertAdjacentHTML('beforeend',markup);renumberBlocks(container);capture(sceneId);if(sceneNode.querySelector('.chapter-authoring-empty-scene'))refresh();document.querySelector('[data-chapter-scene="'+CSS.escape(sceneId)+'"] [data-block-id="'+CSS.escape(block.id)+'"] [data-chapter-text]')?.focus();return}const block=button.closest('[data-chapter-block]');if(!block)return;const separator=block.nextElementSibling?.matches('[data-chapter-insert-row]')?block.nextElementSibling:null;if(button.hasAttribute('data-chapter-remove')){separator?.remove();block.remove()}else if(button.dataset.chapterMove==='up'){const previous=block.previousElementSibling?.previousElementSibling;if(previous&&separator)previous.before(block,separator)}else if(button.dataset.chapterMove==='down'){const next=separator?.nextElementSibling,after=next?.nextElementSibling;if(after&&separator)after.after(block,separator)}renumberBlocks(container);capture(sceneId);if(!container.querySelector('[data-chapter-block]'))refresh()},true);
  async function startChapter(){const {work,chapter}=current();if(!work||!chapter||chapter.scenes?.length)return;notice='正在建立正文场景…';refresh();try{const result=await api(`/works/${work.id}/chapters/${chapter.id}/scenes`,{method:'POST',body:JSON.stringify({expected_version:work.version,title:'正文'})});if(state.work?.id!==work.id)return;state.work=result.work;state.sceneId=result.scene_id;drafts.set(key(work.id,result.scene_id),{base_revision_id:null,blocks:[{id:makeClientBlockId(),type:'narration',speaker:'',text:''}]});saveCache();notice='可以开始写作';refresh();document.querySelector('[data-chapter-scene] [data-chapter-text]')?.focus()}catch(error){notice=`建立失败：${error.message}`;refresh()}}
  async function saveChapter(){const {work,chapter}=current();if(!work||!chapter||saveBusy)return;if(viewMode(work,chapter)==='edit')for(const node of document.querySelectorAll('.chapter-authoring [data-chapter-scene]'))capture(node.dataset.chapterScene,node);if(hasConflict(chapter))return;const modified=chapter.scenes.filter(scene=>entry(scene)).map(scene=>({scene_id:scene.id,expected_base_revision_id:entry(scene).base_revision_id,blocks:entry(scene).blocks}));if(!modified.length)return;saveBusy=true;notice='保存中…';refresh();try{const result=await api(`/works/${work.id}/chapters/${chapter.id}/manuscript`,{method:'POST',body:JSON.stringify({expected_version:work.version,scenes:modified})});if(state.work?.id!==work.id)return;state.work=result.work;for(const item of modified)drafts.delete(key(work.id,item.scene_id));saveCache();notice='整章已保存';reviewKey='';refresh()}catch(error){notice=error.status===409?'保存冲突：本地修改已保留。请核对服务器新版本后重试。':`保存失败：${error.message}`;if(error.status===409){try{await loadWork(work.id,{renderNow:false});reviewKey=''}catch(_){}}refresh()}finally{saveBusy=false;refresh()}}
  async function runReview(){const {work,chapter}=current();if(!work||!chapter||reviewBusy||sceneThreadPending()||anyDirty(chapter)||!chapter.scenes?.some(scene=>original(scene).some(block=>block.text.trim())))return;reviewBusy=true;notice='正在检查整章…';refresh();try{await runDurableAgentJob('chapter.review',chapter.id,{expected_version:work.version});if(state.work?.id===work.id){reviewKey='';notice='整章检查已完成';refresh()}}catch(error){notice=`整章检查失败：${error.message}`;reviewKey='';refresh()}finally{reviewBusy=false;refresh()}}
  async function decideReview(decision){const {work,chapter}=current();if(!work||!chapter||!review?.id||reviewBusy||anyDirty(chapter))return;const selected=[...document.querySelectorAll('[data-chapter-review-item]:checked')].map(node=>node.value);if(decision==='accept'&&!selected.length){notice='请至少选择一项变化，或选择保持当前设定。';refresh();return}reviewBusy=true;try{const result=await api(`/works/${work.id}/chapters/${chapter.id}/review:decide`,{method:'POST',body:JSON.stringify({review_id:review.id,expected_version:work.version,decision,...(decision==='accept'?{selected_item_ids:selected}:{})})});if(state.work?.id===work.id){state.work=result.work;review=result.review;reviewKey=`${work.id}:${chapter.id}:${state.work.version}`;notice='已记录整章变化决定';refresh()}}catch(error){notice=`决定未保存：${error.message}`;refresh()}finally{reviewBusy=false;refresh()}}
  window.addEventListener('beforeunload',event=>{if(drafts.size){event.preventDefault();event.returnValue=''}});
  window.HaloCueChapterAuthoring={render,get active(){return Boolean(document.querySelector('.chapter-authoring'))}};
})();
