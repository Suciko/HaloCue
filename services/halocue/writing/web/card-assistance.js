/* Focused card editing reuses the work conversation and Proposal review. */
(() => {
  'use strict';
  const storageKey='halocue:card-assistance:1';
  const restartHint='当前后端尚未启用定向调整，请正常重启 HaloCue 服务后使用。手动编辑和普通讨论不受影响。';
  const supported=()=>state.capabilities?.capabilities?.includes('card_assistance/1.0');
  const fields={characters:{role:'故事职责',voice_anchors:'声音锚点',knowledge_boundary:'知情边界',ooc_constraints:'OOC 红线',relationships:'人物关系'},world:{summary:'本作定义与限制',aliases:'别名',participants:'关联人物',participant_character_ids:'人物关联 ID',related_world_ids:'关联设定'}};
  let session=null;
  try{const saved=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(saved?.version===1&&saved.workId&&saved.values&&saved.kind in fields)session=saved;}catch(_){/* Storage is optional. */}
  const persist=()=>{try{if(session)sessionStorage.setItem(storageKey,JSON.stringify(session));else sessionStorage.removeItem(storageKey);}catch(_){/* Keep this tab's memory copy. */}};
  function identity(kind){
    const id=kind==='characters'?state.editCardId:state.editWorldEntry?.type==='entity'?state.editWorldEntry.id:'';
    const artifact=(state.work?.artifacts||[]).find(item=>kind==='characters'?item.kind==='character_card'&&item.scope_id===id:item.kind==='world_bible');
    return {id:id||'',revision:id?(artifact?.current_revision_id||artifact?.current_revision?.id||''):''};
  }
  function snapshot(form){
    const values={};
    for(const input of form.elements){
      if(!input.name||['submit','button'].includes(input.type))continue;
      if(input.type==='checkbox'){values[input.name]??=[];if(input.checked)values[input.name].push(input.value);}
      else values[input.name]=input.value;
    }
    return values;
  }
  function restore(form,values){
    for(const input of form.elements){
      if(!input.name||!(input.name in values)||['submit','button'].includes(input.type))continue;
      if(input.type==='checkbox')input.checked=Array.isArray(values[input.name])&&values[input.name].includes(input.value);
      else if(typeof values[input.name]==='string')input.value=values[input.name];
    }
    form.querySelectorAll('.world-link-picker input[type="checkbox"]').forEach(input=>input.dispatchEvent(new Event('change',{bubbles:true})));
    syncLibraryEditorHealth(form,form.dataset.libraryEditorKind);
  }
  function currentSession(thread){return session&&session.workId===state.work?.id&&(!thread||session.threadId===thread.id)?session:null;}
  function panel(form,kind){
    if(form.querySelector('[data-card-assistance-panel]'))return;
    const target=identity(kind),options=Object.entries(fields[kind]).filter(([key])=>key!=='participant_character_ids');
    const example=kind==='characters'?'例如：让她更警惕老师，但保持原来的说话方式':'例如：补充夜间进入档案室的限制，保留原有地点与来源';
    const host=document.createElement('details');host.className='card-assistance-panel';host.dataset.cardAssistancePanel='';
    host.innerHTML=`<summary>和助手定向调整</summary><div class="card-assistance-body"><p>说清想改什么、想保留什么。只生成建议，先看差异再决定。</p><label>这次想怎么改<textarea name="assistance_intent" rows="3" maxlength="2000" placeholder="${example}"></textarea></label><label>允许调整<select name="assistance_scope" aria-label="允许调整"><option value="all">写作字段，由我逐项审查</option>${options.map(([key,label])=>`<option value="${key}">只调整${label}</option>`).join('')}</select></label><small>${target.id?'身份、原有来源与采用状态保持不变；草稿只作讨论材料，不会自动覆盖已保存内容。':'尚未保存的新卡只能先讨论；需要锁定具体修改字段时，先手动保存为待核对卡片。'}</small><div class="actions"><button type="button" class="primary" data-card-assistance-start>带草稿去讨论</button></div><p class="card-assistance-error" data-card-assistance-error role="alert" hidden></p></div>`;
    const button=form.querySelector('[data-library-assist]');
    if(button)button.replaceWith(host);else form.append(host);
    if(!supported()){host.innerHTML=`<summary>和助手定向调整</summary><div class="card-assistance-body"><p role="status">${restartHint}</p><button type="button" disabled>带草稿去讨论</button></div>`;return;}
    host.querySelector('[data-card-assistance-start]').addEventListener('click',()=>start(form,kind));
    host.addEventListener('input',()=>{host.querySelector('[data-card-assistance-error]').hidden=true;});
    if(currentSession()&&session.kind===kind&&session.targetId===target.id&&session.baseRevision===target.revision){
      restore(form,session.values);
      if(session.step!==undefined)form._libraryEditorActivate?.(session.step);
      host.open=true;
      host.closest('.library-editor-assist')?.setAttribute('open','');
    }else if(currentSession()&&session.kind===kind&&session.targetId===target.id){
      host.open=true;
      host.closest('.library-editor-assist')?.setAttribute('open','');
      const note=document.createElement('p');note.className='card-assistance-stale';note.textContent='卡片已有新修订，当前展示已保存内容；未用旧草稿覆盖。';host.querySelector('summary').after(note);
      const draft=document.createElement('details');draft.innerHTML='<summary>查看之前的未保存草稿</summary><pre></pre>';draft.querySelector('pre').textContent=JSON.stringify(session.values,null,2);host.append(draft);
    }
    form.addEventListener('input',()=>{
      if(currentSession()&&session.kind===kind&&session.targetId===target.id&&session.baseRevision===target.revision){session.values=snapshot(form);persist();}
    });
    form.addEventListener('change',()=>{
      if(currentSession()&&session.kind===kind&&session.targetId===target.id&&session.baseRevision===target.revision){session.values=snapshot(form);persist();}
    });
  }
  function start(form,kind){
    const intent=form.elements.assistance_intent.value.trim();
    const fail=message=>{const p=form.querySelector('[data-card-assistance-error]');p.hidden=false;p.textContent=message;};
    if(!intent){fail('请先写一句想改什么，或写“检查这张卡有哪些缺漏”。');form.elements.assistance_intent.focus();return;}
    const thread=(state.work?.conversation_threads||[]).find(item=>item.scope_type==='work'&&item.status==='active');
    if(!thread){fail('当前作品没有可用的创作对话，请先在构思页建立对话。');return;}
    if(workAgentActiveRun(thread)){fail('创作对话仍在运行，请等本轮结束后再带入卡片。');return;}
    const target=identity(kind),scope=form.elements.assistance_scope.value;
    const allowed=scope==='all'?Object.keys(fields[kind]):scope==='participants'?['participants','participant_character_ids']:[scope];
    // Do not clobber an existing unsent conversation draft.
    const viewKey=JSON.stringify([state.work.id,'works',thread.id]);
    const pending=hcTransientViews.get(viewKey);
    const pendingTexts=[state.composerPrefill,...(pending?.fields||[]).map(item=>item.value)].filter(text=>text?.trim());
    const ownedPending=currentSession(thread)&&session.kind===kind&&session.targetId===target.id&&session.baseRevision===target.revision&&session.generatedPrompt&&pendingTexts.every(text=>text===session.generatedPrompt);
    if(pendingTexts.length&&!ownedPending){fail('创作对话还有未发送的内容，请先回到构思处理，再带入这张卡片。');return;}
    const prompt=target.id?`请调整「${form.elements.name.value}」的${kind==='characters'?'人物卡':'世界观卡'}：${intent}\n只调整${allowed.map(key=>fields[kind][key]).join('、')}，其余保持不变。附带草稿仅作讨论材料；请区分已有依据、本作设想与待核对推断，不编造原作认证。请给出可整理为 Proposal 的字段修改，确认前不保存。`:`${libraryEditorAssistantPrompt(form,kind)}\n这次想讨论：${intent}`;
    session={version:1,workId:state.work.id,threadId:thread.id,kind,targetId:target.id,baseRevision:target.revision,allowedFields:allowed,generatedPrompt:prompt,values:snapshot(form),step:Number(form.querySelector('[data-library-editor-step][aria-selected="true"]')?.dataset.libraryEditorStep||0),name:form.elements.name?.value||'未命名卡片'};
    persist();
    if(ownedPending)hcTransientViews.delete(viewKey);
    state.conversationThreadId=thread.id;state.composerPrefill=prompt;
    navigateRoute({section:'works'});
    toast('草稿已保留；在对话中点击发送后才会调用助手。');
    requestAnimationFrame(()=>document.querySelector('#workConversationForm textarea')?.focus());
  }
  function requestContext(thread){
    const active=currentSession(thread);
    if(!active?.targetId)return null;
    if(!supported())throw new Error(restartHint);
    const draft=Object.fromEntries(Object.entries(active.values).filter(([key])=>!['card_id','assistance_intent','assistance_scope'].includes(key)));
    return {schema_version:'card-assistance/1.0',kind:active.kind==='characters'?'character_card':'world_card',target_id:active.targetId,base_revision_id:active.baseRevision,allowed_fields:active.allowedFields,draft};
  }
  function returnToCard(){
    if(!currentSession())return;
    const form=document.querySelector('#workConversationForm');
    if(form?.elements.text)state.composerPrefill=form.elements.text.value;
    const {kind,targetId}=session;
    clearLibraryEditor();state.libraryEditorOpen=true;
    if(kind==='characters'){
      state.editCardId=targetId;state.editCard=libraryCards().find(card=>card.id===targetId)||null;
      if(targetId&&!state.editCard){toast('原人物卡已不存在，草稿仍保留在本标签页。',true);return;}
    }else state.editWorldEntry=targetId?{type:'entity',id:targetId}:null;
    navigateRoute({section:'references',library:kind});
    requestAnimationFrame(()=>document.querySelector('form[data-library-editor-kind]')?.scrollIntoView({block:'start'}));
  }
  function mount(){
    document.querySelectorAll('form[data-library-editor-kind]').forEach(form=>panel(form,form.dataset.libraryEditorKind));
    const composer=document.querySelector('#workConversationForm');
    if(!composer)return;
    const active=currentSession(workConversationThread());
    if(!active||composer.querySelector('[data-card-assistance-banner]'))return;
    const artifact=(state.work?.artifacts||[]).find(item=>active.kind==='characters'?item.kind==='character_card'&&item.scope_id===active.targetId:item.kind==='world_bible');
    const stale=active.targetId&&artifact?.current_revision_id!==active.baseRevision;
    const banner=document.createElement('div');banner.className='card-assistance-banner';banner.dataset.cardAssistanceBanner='';
    banner.innerHTML=`<div><b>正在调整「${esc(active.name)}」</b><small>${stale?'卡片已有新修订；返回卡片核对后再发起下一轮调整。':'建议先审查；旧草稿与已保存卡片分开保留。'}</small></div><button type="button" class="quiet" data-card-assistance-return>返回卡片</button><button type="button" class="quiet" data-card-assistance-end aria-label="结束本次定向调整，保留卡片草稿">结束调整</button>`;
    banner.querySelector('[data-card-assistance-return]').addEventListener('click',returnToCard);
    banner.querySelector('[data-card-assistance-end]').addEventListener('click',()=>{session.threadId='';persist();banner.remove();});
    const preview=document.createElement('details');preview.className='card-assistance-draft-preview';
    preview.innerHTML='<summary>查看本次附带的卡片草稿</summary><pre></pre>';
    preview.querySelector('pre').textContent=JSON.stringify(active.values,null,2);
    banner.append(preview);
    composer.prepend(banner);
  }
  window.HaloCueCardAssistance={mount,requestContext,open(form,kind){panel(form,kind);const panelElement=form.querySelector('[data-card-assistance-panel]');panelElement.open=true;panelElement.querySelector('textarea')?.focus();}};
  registerRenderHook('card-assistance',mount);
  mount();
})();
