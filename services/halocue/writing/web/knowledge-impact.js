/* Explain saved knowledge changes in existing card/scene surfaces, on demand. */
(() => {
  'use strict';
  const schema='knowledge-change-impact/1.0';
  const openPanels=new Set();
  let cached=null,pending=null,pendingKey='',jumpScene='';
  const versionKey=()=>`${state.work?.id||''}:${state.work?.version||0}`;
  const supported=()=>state.capabilities?.capabilities?.includes(schema);
  const statusLabel={changed:'待复查',added:'新增到本场',removed:'已移出本场',unavailable:'资料不可用',unchanged:'资料未变化',not_reviewed:'尚未检查',baseline_unavailable:'基准不可读取'};
  const reasonLabel={manuscript_changed:'正文在上次检查后已更新',scene_contract_changed:'场景范围或契约已调整'};

  async function report(key){
    if(cached?.key===key)return cached.data;
    if(pending&&pendingKey===key)return pending;
    const workId=state.work.id;
    pendingKey=key;
    const request=(async()=>{
      const response=await fetch(`/api/v1/works/${encodeURIComponent(workId)}/knowledge-impact`);
      const envelope=await response.json();
      if(!response.ok||!envelope.ok)throw new Error(envelope.error?.message||'未能读取资料变化，请重试。');
      const data=envelope.data;
      if(data.schema_version!==schema||data.work_id!==workId)throw new Error('资料变化报告格式不匹配。');
      if(`${data.work_id}:${data.work_version}`!==key)throw new Error('作品已在其他操作中更新，请重新载入作品后查看。');
      if(versionKey()===key)cached={key,data};
      return data;
    })();
    pending=request;
    try{return await request;}finally{if(pending===request){pending=null;pendingKey='';}}
  }
  function unsaved(form){
    return form&&[...form.elements].some(input=>{
      if(!input.name||input.name.startsWith('assistance_')||['button','submit','hidden'].includes(input.type))return false;
      if(['checkbox','radio'].includes(input.type))return input.checked!==input.defaultChecked;
      if(input.tagName==='SELECT')return input.value!==([...input.options].find(option=>option.defaultSelected)||input.options[0])?.value;
      return input.value!==input.defaultValue;
    });
  }
  function dependencyText(item){
    const fields=item.fields.map(field=>field.label).filter((label,index,labels)=>labels.indexOf(label)===index);
    return [statusLabel[item.status]||'需核对',fields.length?fields.join('、')+'发生变化':'',!item.available&&item.selected?'当前未确认、已归档或不可用':''].filter(Boolean).join(' · ');
  }
  function sceneStatus(row){
    if(row.status==='needs_review')return '待复查';
    return statusLabel[row.status]||'需核对';
  }
  function rowMarkup(row, target){
    const dependencies=target?row.dependencies.filter(item=>item.kind===target.kind&&item.target_id===target.id):row.dependencies;
    const changed=dependencies.filter(item=>item.status!=='unchanged');
    const description=(changed.length?changed:dependencies).map(item=>`<li><b>${esc(item.name)}</b><span>${esc(dependencyText(item))}</span></li>`).join('');
    const reasons=row.reasons.map(reason=>reasonLabel[reason]).filter(Boolean);
    const basis=row.selection_mode==='legacy'?'兼容范围，按已保存的故事方向选用':'按本场固定资料 ID 关联';
    const baseline=row.baseline.status==='ready'?`上次检查${row.baseline.checked_at?'：'+new Date(row.baseline.checked_at).toLocaleString():''}${row.baseline.gate_status==='blocked'?' · 检查存在阻塞项':''}`:row.baseline.status==='missing'?'没有已完成的本场检查，无法判断修改前后':'最近检查记录不可读取，不能判断为已核对';
    const action=target?`<button type="button" class="quiet" data-impact-scene-open="${esc(row.scene_id)}" data-scene-open="${esc(row.scene_id)}">打开场景</button>`:'';
    return `<article class="knowledge-impact-row" data-impact-scene="${esc(row.scene_id)}"><header><div><b>${esc(row.chapter_title)} / ${esc(row.scene_title)}</b><small>${esc(basis)}</small></div><span data-impact-status="${esc(row.status)}">${esc(sceneStatus(row))}</span></header>${description?`<ul>${description}</ul>`:''}${reasons.length?`<p>${esc(reasons.join('；'))}</p>`:''}<small>${esc(baseline)}</small>${action}</article>`;
  }
  function content(data,target,sceneId){
    const rows=target?data.scenes.filter(row=>row.dependencies.some(item=>item.kind===target.kind&&item.target_id===target.id)):data.scenes.filter(row=>row.scene_id===sceneId);
    const need=rows.filter(row=>row.status==='needs_review').length;
    const summary=target?`关联 ${rows.length} 个场景${need?' · '+need+' 个待复查':''}`:rows[0]?sceneStatus(rows[0]):'没有找到当前场景';
    const empty=target?'当前没有固定选用或历史检查引用这张卡的场景。未登记的正文提及不会被自动识别。':'本场尚无资料记录。';
    const action=!target&&rows[0]?.has_manuscript?`<div class="knowledge-impact-actions"><button type="button" class="quiet" data-action="review-scene" data-impact-review-scene="${esc(sceneId)}" ${state.manuscriptDirty?'disabled':''}>${rows[0].baseline.status==='missing'?'检查本场':'重新检查本场'}</button><small>${state.manuscriptDirty?'请先保存正文，再检查当前版本。':'检查会使用当前写作服务，只产生检查结果，不改正文。'}</small></div>`:'';
    return `<p class="knowledge-impact-summary" role="status">${esc(summary)}</p><p class="knowledge-impact-note">只比较已保存的人物卡、世界观卡与上次本场检查。变化不等于剧情矛盾；不会自动改正文或已冻结定稿。</p>${rows.length?`<div class="knowledge-impact-list">${rows.map(row=>rowMarkup(row,target)).join('')}</div>`:`<p>${empty}</p>`}${action}<button type="button" class="quiet" data-impact-refresh>刷新结果</button><p data-impact-error role="alert" hidden></p>`;
  }
  function bind(panel,target=null,sceneId=''){
    if(panel.dataset.knowledgeImpactBound)return;
    panel.dataset.knowledgeImpactBound='true';
    panel.classList.add('knowledge-impact-panel');
    const owner=state.work.id;
    const key=JSON.stringify([owner,target?.kind||'scene',target?.id||sceneId]);
    const body=document.createElement('div');body.className='knowledge-impact-body';
    [...panel.children].filter(child=>child.tagName!=='SUMMARY').forEach(child=>child.remove());
    panel.append(body);
    async function load(force=false){
      const version=versionKey();
      if(force)cached=null;
      body.innerHTML='<p role="status">正在比对已保存资料…</p>';
      panel.dataset.impactVersion=version;
      try{
        const data=await report(version);
        if(!panel.isConnected||state.work?.id!==owner||versionKey()!==version||panel.dataset.impactVersion!==version)return;
        body.innerHTML=content(data,target,sceneId);
        if(!target){
          const row=data.scenes.find(item=>item.scene_id===sceneId);
          panel.querySelector('summary').textContent=`资料变更检查${row?.status==='needs_review'?' · 待复查':''}`;
          const command=panel.closest('.chapter-manuscript-scene')?.querySelector('.next-command');
          const title=command?.querySelector('strong');
          if(row?.status==='needs_review'&&command?.classList.contains('is-complete')&&title){
            title.dataset.impactOriginalTitle=title.textContent;title.textContent='资料有变化，建议复查本场';command.classList.remove('is-complete');
          }else if(row?.status==='unchanged'&&title?.dataset.impactOriginalTitle){
            title.textContent=title.dataset.impactOriginalTitle;delete title.dataset.impactOriginalTitle;command.classList.add('is-complete');
          }
        }
      }catch(error){
        if(!panel.isConnected||state.work?.id!==owner||versionKey()!==version)return;
        body.innerHTML=`<p role="alert">${esc(error.message||'未能读取，请重试。')}</p><button type="button" class="quiet" data-impact-refresh>重试</button>`;
      }
    }
    panel.addEventListener('toggle',()=>{
      if(panel.open){openPanels.add(key);if(panel.dataset.impactVersion!==versionKey())void load();}
      else openPanels.delete(key);
    });
    panel.addEventListener('click',event=>{
      if(event.target.closest('[data-impact-refresh]'))void load(true);
      if(!event.target.closest('[data-scene-open],[data-action="review-scene"]'))event.stopPropagation();
    });
    // Guard before the main app's navigation handler; never discard a card draft.
    panel.addEventListener('click',event=>{
      if(event.target.closest('[data-action="review-scene"]')&&state.manuscriptDirty){
        event.preventDefault();event.stopImmediatePropagation();
        const error=body.querySelector('[data-impact-error]');error.hidden=false;error.textContent='请先保存正文，再检查当前版本。';return;
      }
      const open=event.target.closest('[data-impact-scene-open]');
      if(!open)return;
      if(unsaved(panel.closest('form'))){
        event.preventDefault();event.stopImmediatePropagation();
        const error=body.querySelector('[data-impact-error]');error.hidden=false;error.textContent='卡片还有未保存的修改。请先保存，再打开场景；当前结果只反映已保存资料。';
        return;
      }
      jumpScene=open.dataset.impactSceneOpen;
    },true);
    if(openPanels.has(key)||(!target&&jumpScene===sceneId)){panel.open=true;jumpScene='';void load();}
    else body.innerHTML='<p>展开后读取已保存的场景引用与检查记录，不会调用模型。</p>';
  }
  function mount(){
    if(!state.work||!supported())return;
    document.querySelectorAll('form[data-library-editor-kind]').forEach(form=>{
      const kind=form.dataset.libraryEditorKind;
      const id=kind==='characters'?state.editCardId:state.editWorldEntry?.type==='entity'?state.editWorldEntry.id:'';
      const panel=form.querySelector('.library-impact-preview');
      if(!panel||!id)return;
      bind(panel,{kind:kind==='characters'?'character_card':'world_card',id});
    });
    const scene=state.stage==='draft'?selectedScene():null;
    const section=scene?document.getElementById(`chapter-scene-${scene.id}`):null;
    if(section&&!section.querySelector('[data-scene-knowledge-impact]')){
      const panel=document.createElement('details');panel.dataset.sceneKnowledgeImpact='';panel.innerHTML='<summary>资料变更检查</summary>';
      const manuscript=section.querySelector('.chapter-inline-manuscript');
      if(manuscript)manuscript.before(panel);else section.append(panel);
      bind(panel,null,scene.id);
    }
  }
  registerRenderHook('knowledge-change-impact',mount);
  window.HaloCueKnowledgeImpact=Object.freeze({mount});
  mount();
})();
