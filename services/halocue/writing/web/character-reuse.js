/* Explicit local character reuse. Domain validation and provenance stay server-owned. */
(() => {
  let dialog=null, flow=null, epoch=0, opener=null;
  function ensureDialog(){
    if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.id='characterReuseDialog';dialog.className='character-reuse-dialog';
    dialog.setAttribute('aria-labelledby','characterReuseTitle');
    dialog.innerHTML=`<form id="characterReuseForm"><header><div><h2 id="characterReuseTitle">从其他作品选取人物</h2><p data-reuse-target></p></div><button type="button" class="quiet" data-reuse-close aria-label="关闭人物选取">关闭</button></header>
      <p class="character-reuse-explanation">保留完整人物资料、样本和来源，复制为本作独立卡片；不会覆盖同名人物。复制后先标为待核对，不自动加入助手上下文。</p>
      <div class="character-reuse-filters"><label>来源作品<select name="source" required><option value="">选择来源作品</option></select></label><label>查找人物<input name="query" type="search" placeholder="名称或别名" autocomplete="off"></label></div>
      <p data-reuse-status role="status"></p><p data-reuse-error role="alert" hidden></p><button type="button" class="quiet" data-reuse-refresh-target hidden>刷新资料后重新选择</button>
      <div class="character-reuse-list" role="radiogroup" aria-label="选择要复制的人物"><div data-reuse-cards></div></div>
      <footer><button type="button" class="quiet" data-reuse-close>取消</button><button type="submit" class="primary" disabled>复制到本作</button></footer></form>`;
    document.body.append(dialog);
    dialog.addEventListener('click',event=>{if(event.target.closest('[data-reuse-close]'))close();if(event.target.closest('[data-reuse-refresh-target]'))void refreshTarget();});
    dialog.addEventListener('cancel',event=>{if(flow?.saving)event.preventDefault();});
    dialog.addEventListener('close',()=>{epoch++;flow=null;opener?.isConnected&&opener.focus({preventScroll:true});opener=null;});
    dialog.querySelector('[name=source]').addEventListener('change',loadSource);
    dialog.querySelector('[name=query]').addEventListener('input',renderCards);
    dialog.querySelector('[data-reuse-cards]').addEventListener('change',event=>{
      if(!flow||flow.loading||flow.saving||!event.target.matches('[name=card]'))return;
      flow.selected=event.target.value;dialog.querySelector('[type=submit]').disabled=false;
    });
    dialog.querySelector('form').addEventListener('submit',submit);
    return dialog;
  }
  function close(){if(!flow?.saving)dialog?.close();}
  function message(text,error=false){
    const node=dialog.querySelector(error?'[data-reuse-error]':'[data-reuse-status]');node.textContent=text;node.hidden=!text;
  }
  function tokens(card){return [card.name,card.canonical_name,...hcArray(card.aliases)].filter(Boolean).map(value=>String(value).trim().toLocaleLowerCase());}
  function renderCards(){
    if(!flow)return;
    const query=dialog.querySelector('[name=query]').value.trim().toLocaleLowerCase();
    const cards=flow.cards.filter(card=>tokens(card.content).some(value=>value.includes(query)));
    if(flow.selected&&!cards.some(card=>card.id===flow.selected))flow.selected='';
    dialog.querySelector('[data-reuse-cards]').innerHTML=cards.map(card=>{
      const c=card.content,duplicate=tokens(c).some(value=>flow.existing.has(value));
      return `<label class="character-reuse-option ${duplicate?'is-duplicate':''}"><input type="radio" name="card" value="${esc(card.id)}" ${flow.selected===card.id?'checked':''} ${duplicate||flow.loading||flow.saving?'disabled':''}><span><b>${esc(c.name)}</b><small>${c.source_type==='official_reference'?'原作参考':'自定义人物'}${duplicate?' · 本作已有同名或别名匹配项':''}</small><p>${esc(c.role||'完整资料将随来源一起保留。')}</p></span></label>`;
    }).join('')||'<p class="character-reuse-empty">'+(flow.loading?'正在读取人物资料…':flow.sourceId?'没有符合条件的可用人物。':'先选择来源作品。')+'</p>';
    if(flow.sourceId&&!flow.loading)message(`共 ${flow.cards.length} 张可用人物卡，当前显示 ${cards.length} 张。`);
    dialog.querySelector('[type=submit]').disabled=!flow.selected||flow.loading||flow.saving;
  }
  function open(button){
    if(!state.work)return;
    ensureDialog();if(dialog.open)return;
    opener=button;epoch++;
    flow={targetId:state.work.id,targetVersion:state.work.version,sourceId:'',cards:[],selected:'',loading:false,saving:false,existing:new Set(libraryCards().flatMap(tokens))};
    dialog.querySelector('[data-reuse-target]').textContent=`复制到「${state.work.title}」`;
    dialog.querySelector('form').reset();
    const sources=hcArray(state.works).filter(work=>work.id!==flow.targetId);
    dialog.querySelector('[name=source]').innerHTML='<option value="">选择来源作品</option>'+sources.map(work=>`<option value="${esc(work.id)}">${esc(work.title)}</option>`).join('');
    dialog.querySelectorAll('button,select,input').forEach(node=>node.disabled=false);
    message('');message('',true);dialog.querySelector('[data-reuse-refresh-target]').hidden=true;renderCards();
    if(!sources.length)message('还没有其他作品。可以先从文件导入人物卡，或在另一部作品建立参考资料。');
    button.closest('details')?.removeAttribute('open');dialog.showModal();dialog.querySelector('[name=source]').focus();
  }
  async function loadSource(){
    if(!flow||flow.saving)return;
    const current=flow,request=++epoch;
    current.sourceId=dialog.querySelector('[name=source]').value;current.cards=[];current.selected='';current.loading=!!current.sourceId;
    message('');message('',true);renderCards();if(!current.sourceId)return;
    try{
      const work=await api(`/works/${encodeURIComponent(current.sourceId)}`);
      if(flow!==current||request!==epoch)return;
      current.cards=hcArray(work.artifacts).filter(item=>item.kind==='character_card'&&item.current_revision?.content?.status!=='archived'&&item.current_revision?.content).map(item=>({id:item.scope_id,revisionId:item.current_revision.id,content:item.current_revision.content}));
    }catch(error){if(flow===current&&request===epoch)message('无法读取来源作品，请重新选择后重试。',true);}
    finally{if(flow===current&&request===epoch){current.loading=false;renderCards();}}
  }
  async function refreshTarget(){
    const current=flow;if(!current||current.saving||current.loading)return;
    const button=dialog.querySelector('[data-reuse-refresh-target]');button.disabled=true;
    current.loading=true;current.selected='';renderCards();
    try{
      const work=await api(`/works/${encodeURIComponent(current.targetId)}`);
      if(flow!==current)return;
      current.targetVersion=work.version;
      current.existing=new Set(hcArray(work.artifacts).filter(item=>item.kind==='character_card').flatMap(item=>tokens(item.current_revision?.content||{})));
      current.selected='';message('',true);button.hidden=true;
    }catch(error){if(flow===current)message('本作暂时无法刷新，请稍后重试。',true);}
    finally{button.disabled=false;if(flow===current){current.loading=false;if(button.hidden)void loadSource();else renderCards();}}
  }
  async function submit(event){
    event.preventDefault();const current=flow;if(!current||current.saving||current.loading)return;
    const card=current.cards.find(item=>item.id===current.selected);if(!card)return;
    if(state.work?.id!==current.targetId){message('当前作品已切换，请关闭后重新选择目标。',true);return;}
    current.saving=true;message('',true);dialog.querySelectorAll('button,select,input').forEach(node=>node.disabled=true);
    dialog.querySelector('[type=submit]').textContent='正在复制…';
    try{
      const result=await api(`/works/${encodeURIComponent(current.targetId)}/character-cards:reuse`,{method:'POST',body:JSON.stringify({expected_version:current.targetVersion,source_work_id:current.sourceId,source_card_id:card.id,source_revision_id:card.revisionId})});
      if(state.work?.id===current.targetId){
        // Do not replace a newer response from another operation with this snapshot.
        if(Number(result.work.version)>=Number(state.work.version))state.work=result.work;
        state.libraryView='characters';state.libraryQuery='';state.librarySourceFilter='all';state.libraryStatusFilter='all';state.libraryCharacterFilter='active';state.highlightCardId=result.card_id;clearLibraryEditor();render();
      }
      toast('人物资料已复制，确认采用后才会进入本作写作上下文。');current.saving=false;dialog.close();
    }catch(error){
      if(flow===current){message(error.message||'未能确认复制结果，请刷新本作后核对。不会覆盖已有资料。',true);dialog.querySelector('[data-reuse-refresh-target]').hidden=false;}
    }finally{
      current.saving=false;dialog.querySelectorAll('button,select,input').forEach(node=>node.disabled=false);
      dialog.querySelector('[type=submit]').textContent='复制到本作';if(flow===current)renderCards();
    }
  }
  registerAppClick(event=>{
    const button=event.target.closest?.('[data-reuse-character]');if(!button)return;
    event.preventDefault();claimAppEvent(event);open(button);
  },0);
  registerRenderHook('character-reuse-scope',()=>{if(flow&&state.work?.id!==flow.targetId&&!flow.saving)close();});
})();
