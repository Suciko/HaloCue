/* World-first authoring and editable outline documents. The service remains
   the only source of saved truth; this module keeps unsaved browser drafts. */
(() => {
  const worldCache = new Map();
  const worldEdits = new Map();
  const outlineCache = new Map();
  const outlineEdits = new Map();
  const workWorldEdits = new Map();
  const workWorldStatus = new Map();
  const outlineScopes = new Map();
  const outlineStatus = new Map();
  const outlineBases = new Map();
  const workWorldBases = new Map();
  let worlds = null, worldsLoading = false, worldsPromise = null, worldsError = '';
  let worldLoading = '', worldSaving = false, worldError = '';
  const draftKey = (kind, id) => `halocue:authoring:${kind}:${id}`;
  const readDraft = (kind, id) => {
    try { return JSON.parse(sessionStorage.getItem(draftKey(kind, id)) || 'null'); }
    catch (_) { return null; }
  };
  const writeDraft = (kind, id, value) => {
    try { sessionStorage.setItem(draftKey(kind, id), JSON.stringify(value)); } catch (_) {}
  };
  const clearDraft = (kind, id) => {
    try { sessionStorage.removeItem(draftKey(kind, id)); } catch (_) {}
  };
  const currentWorldId = () => state.route.worldDraftId || '';
  const worldEdit = id => {
    if (!worldEdits.has(id)) {
      const stored = readDraft('world', id);
      if (stored) worldEdits.set(id, stored);
    }
    return worldEdits.get(id);
  };
  const outlineKey = (workId, doc) => `${workId}:${doc.scope_type}:${doc.scope_id}`;
  const outlineEdit = key => {
    if (!outlineEdits.has(key)) {
      const stored = readDraft('outline', key);
      if (stored) { outlineEdits.set(key, stored.text); outlineBases.set(key, stored.baseRevisionId); }
    }
    return outlineEdits.get(key);
  };
  function refreshVisible(section) { if (state.route.section === section) render(); }
  async function loadWorlds(force = false) {
    if (worldsLoading) return worldsPromise;
    if (worlds && !force) return worlds;
    worldsLoading = true; worldsError = '';
    worldsPromise = (async () => {
      try { worlds = await api('/world-drafts'); }
      catch (error) { worldsError = error.message || '世界底稿暂时无法读取。'; }
      finally { worldsLoading = false; refreshVisible('worlds'); }
      return worlds;
    })();
    return worldsPromise;
  }
  async function loadWorld(id, force = false) {
    if (!id || worldLoading === id || (worldCache.has(id) && !force)) return;
    const comparing = worldError.includes('已有新版本');
    worldLoading = id; worldError = '';
    try { worldCache.set(id, await api(`/world-drafts/${encodeURIComponent(id)}`)); if(comparing)worldError='已重新载入服务端版本，请对比本地输入后再保存。'; }
    catch (error) { worldError = error.message || '底稿暂时无法读取。'; }
    finally { worldLoading = ''; if (currentWorldId() === id) refreshVisible('worlds'); }
  }
  async function populateWorkForm(form) {
    const select = form?.querySelector('[name="world_draft_id"]');
    if (!select) return;
    await loadWorlds();
    if (!select.isConnected) return;
    const selected = select.value;
    select.innerHTML = '<option value="">不使用已有底稿</option>' + (worlds || []).map(item =>
      `<option value="${esc(item.id)}" data-revision-id="${esc(item.current_revision_id)}">${esc(item.title)} · v${item.version}</option>`
    ).join('');
    select.value = selected;
  }
  function renderWorldDrafts(host) {
    if (!worlds && !worldsLoading && !worldsError) void loadWorlds();
    const id = currentWorldId();
    if (id && !worldCache.has(id) && worldLoading !== id && !worldError) void loadWorld(id);
    const selected = id ? worldCache.get(id) : null;
    const edit = worldEdit(id || 'new');
    const content = selected?.content || {};
    const title = edit?.title ?? content.title ?? '';
    const overview = edit?.overview ?? content.overview ?? '';
    const pending = Boolean(edit);
    const conflict = Boolean(selected && edit && edit.baseVersion !== selected.version);
    host.innerHTML = `<div class="authoring-worlds"><header class="authoring-page-head"><div><p class="eyebrow">独立世界底稿</p><h1>先整理世界，再决定写哪个故事</h1><p>底稿独立保存。从它创建作品时只复制当前版本，后续修改互不影响。</p></div><button type="button" class="quiet" data-section="projects">返回作品</button></header>
      <div class="authoring-world-grid"><aside class="authoring-world-list"><div class="authoring-world-list-head"><h2>世界底稿</h2><button type="button" class="primary" data-world-new>新建底稿</button></div>
        ${worldsError ? `<p class="authoring-error" role="alert">${esc(worldsError)} <button type="button" data-world-list-retry>重试</button></p>` : ''}
        ${worldsLoading && !worlds ? '<p role="status">正在读取底稿…</p>' : (worlds || []).map(item => `<button type="button" class="authoring-world-row ${id===item.id?'active':''}" data-world-open="${esc(item.id)}"><b>${esc(item.title)}</b><small>版本 ${item.version}</small></button>`).join('') || '<p class="authoring-empty">还没有世界底稿。右侧可先写一段世界总说明。</p>'}
      </aside><main class="authoring-world-editor">${id && !selected ? `<p role="status">${worldError ? esc(worldError) : '正在读取底稿…'}</p>${worldError?'<button type="button" data-world-retry>重试读取</button>':''}` : `
        <form id="worldDraftForm"><header><h2>${selected?'编辑世界底稿':'新建世界底稿'}</h2><span>${selected?`v${selected.version} · ${pending?'未保存修改':'已保存'}`:'尚未保存'}</span></header>
          <label>名称<input name="title" maxlength="200" value="${esc(title)}" placeholder="例如：雨后的基沃托斯"></label>
          <label>世界总说明<textarea name="overview" rows="13" maxlength="500000" placeholder="这里的世界如何运作？有哪些人物、地点与限制？">${esc(overview)}</textarea></label>
          ${selected?'':`<label class="authoring-seed"><input type="checkbox" name="world_seed" value="ba_starter" ${edit?.world_seed==='ba_starter'?'checked':''}> 从 BA 起始架构添加待核对条目（可选）</label>`}
          ${worldError||conflict?`<div class="authoring-error" role="alert">${esc(conflict?'底稿已有新版本；先对比本地草稿与服务端，再明确选择保存基准。':worldError)} <button type="button" data-world-retry>重新载入比较</button></div>${selected&&pending?`<details class="authoring-conflict-compare" ${conflict?'open':''}><summary>对比已保存版本与本地输入</summary><section><b>已保存版本</b><pre>${esc(content.overview||'（空白）')}</pre></section><section><b>本地输入</b><pre>${esc(overview||'（空白）')}</pre></section></details>`:''}${conflict?'<button type="button" class="quiet" data-world-rebase>用当前服务端版本作为保存基准</button>':''}`:''}
          <div class="authoring-form-actions"><button type="submit" class="primary" ${worldSaving||conflict?'disabled':''}>${worldSaving?'保存中…':'保存底稿'}</button>${pending?'<button type="button" class="quiet" data-world-discard>放弃本地修改</button>':''}</div>
        </form>
        ${selected?`<section class="authoring-world-followup"><h3>从此底稿建立作品</h3><p>复制版本 v${selected.version}。作品中的世界观可以独立编辑，原底稿保留。</p><form id="worldCreateWorkForm"><label>作品名称（可选）<input name="title" maxlength="80" placeholder="留空使用“未命名作品”"></label><label>建立后前往<select name="destination"><option value="world">作品世界观</option><option value="outline">大纲</option></select></label><button type="submit" class="quiet">建立作品</button></form></section>
          <details class="authoring-history"><summary>版本记录 · ${selected.history.length}</summary>${selected.history.map(item=>`<article><b>版本 ${item.ordinal}</b><time>${esc(item.created_at)}</time><p>${esc((item.content.overview||'').slice(0,180)||'尚无总说明')}</p></article>`).join('')}</details>`:''}`}</main></div></div>`;
  }
  function workOverviewMarkup(world) {
    const workId=state.work?.id;
    if(!workId)return '';
    if(!workWorldEdits.has(workId)){
      const stored=readDraft('work-world',workId);
      if(stored){workWorldEdits.set(workId,stored.text);workWorldBases.set(workId,stored.baseRevisionId);}
    }
    const revisionId=state.work.artifacts?.find(item=>item.kind==='world_bible')?.current_revision?.id||null;
    const conflict=workWorldEdits.has(workId)&&workWorldBases.get(workId)!==revisionId;
    const origin=state.work.artifacts?.find(item=>item.kind==='world_bible')?.revisions?.find(item=>item.provenance?.world_draft_id)?.provenance;
    const value=workWorldEdits.get(workId)??world.overview??'';
    const status=workWorldStatus.get(workId)||'';
    return `<section class="authoring-work-overview"><header><div><h3>世界总说明</h3>${origin?`<p>复制自世界底稿 ${esc(worldTitle(origin.world_draft_id))} · 来源修订 ${esc(origin.world_draft_revision_id)}。此作品现在独立保存。</p>`:'<p>概括这部作品的世界规则与限制，卡片在下方继续管理。</p>'}</div></header><form id="workWorldOverviewForm"><label class="sr-only" for="workWorldOverviewText">世界总说明</label><textarea id="workWorldOverviewText" name="overview" rows="6" placeholder="这个世界如何运作？本作采用哪些规则？">${esc(value)}</textarea>${conflict?`<div class="authoring-error" role="alert">世界观已有新版本；本地输入仍保留。请对比后选择保存基准。<details class="authoring-conflict-compare" open><summary>对比服务端与本地草稿</summary><section><b>服务端</b><pre>${esc(world.overview||'（空白）')}</pre></section><section><b>本地</b><pre>${esc(value||'（空白）')}</pre></section></details><button type="button" class="quiet" data-work-world-rebase>用当前服务端版本作为保存基准</button></div>`:status&&status!=='saved'?`<p class="authoring-error" role="alert">${esc(status)}</p>`:''}<div class="authoring-form-actions"><button type="submit" class="primary" ${conflict?'disabled':''}>保存总说明</button><span>${workWorldEdits.has(workId)?'未保存的输入会在本次浏览器会话中保留':status==='saved'?'已保存':''}</span></div></form></section>`;
  }
  function worldTitle(id){return worlds?.find(item=>item.id===id)?.title||id;}
  const outlineRecord = workId => {
    if (!outlineCache.has(workId)) outlineCache.set(workId, {data:null,loading:false,error:''});
    return outlineCache.get(workId);
  };
  async function loadOutline(workId, force = false) {
    const record = outlineRecord(workId);
    if (record.loading || (record.data && !force)) return;
    record.loading = true; record.error = '';
    try {
      record.data = await api(`/works/${encodeURIComponent(workId)}/outline`);
      const conflict = [...outlineStatus].some(([key,status]) => key.startsWith(`${workId}:`) && status === 'conflict');
      if (conflict && state.work?.id === workId && state.work.version < record.data.version) {
        state.work = await api(`/works/${encodeURIComponent(workId)}`);
      }
    }
    catch (error) { record.error = error.message || '大纲暂时无法读取。'; }
    finally { record.loading = false; if (state.work?.id === workId && state.route.section === 'writing' && state.stage === 'structure') render(); }
  }
  function renderOutline(host) {
    const work = state.work;
    if (!work) return false;
    const record = outlineRecord(work.id);
    if ((!record.data || record.data.version !== work.version) && !record.loading && !record.error) void loadOutline(work.id, true);
    if (!record.data) {
      host.innerHTML = `<div class="authoring-outline"><p role="status">${record.error ? esc(record.error) : '正在读取大纲…'}</p>${record.error?'<button type="button" data-outline-retry>重试读取</button>':''}</div>`;
      return true;
    }
    const documents = record.data.documents || [];
    let scope = outlineScopes.get(work.id);
    if (!documents.some(item => `${item.scope_type}:${item.scope_id}` === scope)) {
      const chapterId = state.sceneId ? state.writingChapterId : '';
      scope = chapterId && documents.some(item => item.scope_type === 'chapter' && item.scope_id === chapterId)
        ? `chapter:${chapterId}` : `work:${work.id}`;
    }
    outlineScopes.set(work.id, scope);
    const doc = documents.find(item => `${item.scope_type}:${item.scope_id}` === scope) || documents[0];
    if (!doc) return false;
    const key = outlineKey(work.id, doc), typed = outlineEdit(key), text = typed ?? doc.text ?? '';
    const dirty = typed !== undefined && typed !== doc.text;
    const conflict = typed !== undefined && outlineBases.get(key) !== doc.revision_id;
    const status = conflict ? 'conflict' : outlineStatus.get(key) || '';
    const chapter = doc.scope_type === 'chapter' ? work.chapters.find(item => item.id === doc.scope_id) : null;
    const acceptedPlan = chapter ? work.artifacts?.find(item => item.kind === 'chapter_plan' && item.scope_id === chapter.id)?.current_revision?.content : null;
    const pendingPlan = chapter ? work.proposals?.find(item => item.kind === 'chapter_plan' && item.scope_id === chapter.id && item.status === 'pending') : null;
    const planCard = (plan, label) => `<div class="outline-plan-copy"><p class="eyebrow">${label}</p><h3>${esc(plan.title || `${chapter.title}细纲`)}</h3><p class="outline-plan-goal">${esc(plan.chapter_goal || '')}</p>${plan.beats?.length ? `<div class="outline-plan-group"><b>情节推进</b><ol>${plan.beats.map(beat => `<li>${esc(beat)}</li>`).join('')}</ol></div>` : ''}${plan.continuity_notes?.length ? `<div class="outline-plan-group"><b>承接与限制</b><ul>${plan.continuity_notes.map(note => `<li>${esc(note)}</li>`).join('')}</ul></div>` : ''}</div>`;
    const chapterPlan = chapter ? `<section class="authoring-chapter-plan"><div class="authoring-chapter-plan-head"><div><p class="eyebrow">本章细纲</p><h2>先讨论，再决定写入</h2><p>讨论围绕《${esc(chapter.title)}》进行；整理出的候选由你确认，正文不会跟着改动。</p></div><button type="button" class="primary" data-outline-discuss="${esc(chapter.id)}">讨论本章细纲</button></div>${pendingPlan ? `<div class="outline-plan-pending">${planCard(pendingPlan.candidate?.chapter_plan || {}, '待确认的细纲候选')}<div class="outline-plan-actions"><button type="button" class="primary" data-accept-director-proposal="${esc(pendingPlan.id)}">采纳细纲</button><button type="button" class="quiet" data-reject-director-proposal="${esc(pendingPlan.id)}">继续讨论</button></div></div>` : ''}${acceptedPlan ? `<div class="outline-plan-accepted">${planCard(acceptedPlan, '已采用的细纲')}</div>` : `<p class="outline-plan-empty">还没有正式细纲。可以先讨论情节推进，也可以直接手写下方章纲。</p>`}</section>` : '';
    host.innerHTML = `<div class="authoring-outline"><header class="authoring-page-head"><div><p class="eyebrow">大纲</p><h1>${esc(work.title)}</h1><p>总纲、卷纲与章纲分别保存。构思成果会显示为参考，手写内容不会被自动覆盖。</p></div><span class="authoring-outline-state" role="status">${status==='saving'?'保存中…':dirty?'未保存':status==='saved'?'已保存':'可编辑'}</span></header>
      <div class="authoring-outline-grid"><nav class="authoring-outline-scopes" aria-label="大纲范围">${documents.map(item=>`<button type="button" class="${scope===`${item.scope_type}:${item.scope_id}`?'active':''}" data-outline-scope="${esc(item.scope_type)}:${esc(item.scope_id)}"><span>${item.scope_type==='work'?'总纲':item.scope_type==='volume'?'卷纲':'章纲'}</span><b>${esc(item.title)}</b></button>`).join('')}</nav>
      <section class="authoring-outline-main">${chapterPlan}<form id="outlineDocumentForm"><input type="hidden" name="scope_type" value="${esc(doc.scope_type)}"><input type="hidden" name="scope_id" value="${esc(doc.scope_id)}"><h2>${esc(doc.title)} · ${doc.scope_type==='work'?'总纲':doc.scope_type==='volume'?'卷纲':'章纲'}</h2>${chapter?'<p class="outline-editor-hint">可编辑文本版 · 适合补充细节和自由记录，与上方确认的细纲分别保存。</p>':''}<label class="sr-only" for="outlineText">大纲正文</label><textarea id="outlineText" name="text" rows="18" maxlength="500000" placeholder="写下这一层的大纲。可以先从一句话开始。">${esc(text)}</textarea>
        ${doc.source_changed?'<p class="authoring-notice">构思有更新；下方可对比，是否合并由你决定。</p>':''}
        <details class="authoring-source-compare"><summary>${doc.source_changed?'对比最新构思':'查看构思来源'}</summary><div><section><b>当前编辑</b><pre>${esc(text||'（空白）')}</pre></section><section><b>已采用的构思</b><pre>${esc(doc.adopted_text||'（尚无）')}</pre></section></div><button type="button" class="quiet" data-outline-append ${doc.adopted_text?'':'disabled'}>把构思附加到编辑</button><button type="button" class="quiet" data-outline-replace ${doc.adopted_text?'':'disabled'}>用构思替换编辑</button></details>
        ${record.error||(status && status!=='saving' && status!=='saved')?`<div class="authoring-error" role="alert">${esc(record.error|| (status==='conflict'?'大纲已有新版本；本地草稿仍在。请对比后明确选择保存基准。':status))}<button type="button" data-outline-retry>重新载入比较</button></div>${status==='conflict'?`<details class="authoring-conflict-compare" open><summary>对比服务端与本地草稿</summary><section><b>服务端已保存</b><pre>${esc(doc.text||'（空白）')}</pre></section><section><b>本地草稿</b><pre>${esc(text||'（空白）')}</pre></section></details><button type="button" class="quiet" data-outline-rebase>用当前服务端版本作为保存基准</button>`:''}`:''}
        <div class="authoring-form-actions"><button type="submit" class="primary" ${status==='saving'||conflict?'disabled':''}>保存大纲</button>${dirty?'<span>切换范围或刷新后仍会保留这份草稿。</span>':''}</div></form>
        <details class="authoring-history"><summary>版本记录 · ${doc.history.length}</summary>${doc.history.map(item=>`<article><b>版本 ${item.ordinal}</b><time>${esc(item.created_at)}</time><p>${esc((item.content?.text||'').slice(0,180)||'空白版本')}</p></article>`).join('')}</details>
        ${chapter?`<details class="authoring-scenes"><summary>本章场景 · ${(chapter.scenes||[]).length}</summary>${(chapter.scenes||[]).map(scene=>`<div><b>${esc(scene.title)}</b><button type="button" class="quiet" data-scene-open="${esc(scene.id)}">打开正文</button></div>`).join('')||'<p>本章还没有场景。</p>'}<button type="button" class="quiet" data-structure-add-scene="${esc(chapter.id)}">添加场景</button></details>`:''}
        <div class="authoring-structure-actions"><button type="button" class="quiet" data-structure-add-volume>新增卷</button><button type="button" class="quiet" data-structure-add-chapter="${esc(work.volumes?.[0]?.id||'')}">新增章节</button></div>
      </section></div></div>`;
    return true;
  }
  document.addEventListener('input', event => {
    const form = event.target.closest?.('#worldDraftForm,#outlineDocumentForm,#workWorldOverviewForm');
    if (!form) return;
    if (form.id === 'worldDraftForm') {
      const id = currentWorldId() || 'new';
      const value = {title:form.elements.title.value,overview:form.elements.overview.value,world_seed:form.elements.world_seed?.checked?'ba_starter':'',baseVersion:worldEdits.has(id)?worldEdits.get(id).baseVersion:(worldCache.get(id)?.version??null)};
      worldEdits.set(id,value); writeDraft('world',id,value);
    } else if(form.id==='workWorldOverviewForm'){
      const id=state.work.id;
      if(!workWorldBases.has(id))workWorldBases.set(id,state.work.artifacts?.find(item=>item.kind==='world_bible')?.current_revision?.id||null);
      workWorldEdits.set(id,form.elements.overview.value);writeDraft('work-world',id,{text:form.elements.overview.value,baseRevisionId:workWorldBases.get(id)});
    } else {
      const key = `${state.work.id}:${form.elements.scope_type.value}:${form.elements.scope_id.value}`;
      const doc=outlineRecord(state.work.id).data?.documents?.find(item=>`${item.scope_type}:${item.scope_id}`===`${form.elements.scope_type.value}:${form.elements.scope_id.value}`);
      if(!outlineBases.has(key))outlineBases.set(key,doc?.revision_id);
      outlineEdits.set(key,form.elements.text.value); writeDraft('outline',key,{text:form.elements.text.value,baseRevisionId:outlineBases.get(key)});
      const label=document.querySelector('.authoring-outline-state');if(label)label.textContent='未保存';
      const compared=document.querySelector('.authoring-source-compare section:first-child pre');if(compared)compared.textContent=form.elements.text.value||'（空白）';
      const local=document.querySelector('.authoring-conflict-compare section:last-child pre');if(local)local.textContent=form.elements.text.value||'（空白）';
    }
  });
  document.addEventListener('change', event => {
    if (event.target.matches?.('#worldDraftForm [name="world_seed"]')) event.target.dispatchEvent(new Event('input',{bubbles:true}));
  });
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-world-new],[data-world-open],[data-world-list-retry],[data-world-retry],[data-world-discard],[data-world-rebase],[data-work-world-rebase],[data-outline-scope],[data-outline-discuss],[data-outline-back],[data-outline-retry],[data-outline-rebase],[data-outline-append],[data-outline-replace]');
    if (!button) return;
    event.preventDefault(); claimAppEvent(event);
    if (button.hasAttribute('data-world-new')) { worldError=''; navigateRoute({section:'worlds',worldDraftId:''}); return; }
    if (button.dataset.worldOpen) { worldError=''; navigateRoute({section:'worlds',worldDraftId:button.dataset.worldOpen}); return; }
    if (button.hasAttribute('data-world-list-retry')) { worlds=null; void loadWorlds(true); return; }
    if (button.hasAttribute('data-world-retry')) { void loadWorld(currentWorldId(),true); return; }
    if (button.hasAttribute('data-world-discard')) { const id=currentWorldId()||'new'; worldEdits.delete(id); clearDraft('world',id); worldError=''; render(); return; }
    if (button.hasAttribute('data-world-rebase')) { const id=currentWorldId(),edit=worldEdits.get(id),world=worldCache.get(id);if(edit&&world){edit.baseVersion=world.version;writeDraft('world',id,edit);worldError='';render()}return; }
    if (button.hasAttribute('data-work-world-rebase')) { const id=state.work?.id;if(id){workWorldBases.set(id,state.work.artifacts?.find(item=>item.kind==='world_bible')?.current_revision?.id||null);writeDraft('work-world',id,{text:workWorldEdits.get(id),baseRevisionId:workWorldBases.get(id)});workWorldStatus.delete(id);render()}return; }
    if (button.dataset.outlineScope) { outlineScopes.set(state.work.id,button.dataset.outlineScope); if(button.dataset.outlineScope.startsWith('chapter:'))state.writingChapterId=button.dataset.outlineScope.slice(8); render(); return; }
    if (button.hasAttribute('data-outline-back')) { navigateRoute({section:'writing',stage:'structure',pane:'writing'}); return; }
    if (button.dataset.outlineDiscuss) {
      const chapter=state.work?.chapters?.find(item=>item.id===button.dataset.outlineDiscuss);
      if(!chapter)return;
      state.inspector='agent';
      navigateRoute({section:'writing',stage:'structure',chapterId:chapter.id,sceneId:chapter.scenes?.[0]?.id||null,pane:isCompactViewport()?'agent':'writing'});
      if(!isCompactViewport())window.HaloCuePanels?.open('inspector');
      document.querySelector('#workConversationForm textarea, #mobileWorkConversationForm textarea')?.focus();
      void persistWritingTarget(chapter.id,chapter.scenes?.[0]?.id||null).catch(error=>toast(`章节位置未保存：${error.message}`,true));
      return;
    }
    if (button.hasAttribute('data-outline-retry')) { void loadOutline(state.work.id,true); return; }
    if (button.hasAttribute('data-outline-rebase')) { const id=state.work.id,record=outlineRecord(id),scope=outlineScopes.get(id),doc=record.data?.documents?.find(item=>`${item.scope_type}:${item.scope_id}`===scope);if(doc){const key=outlineKey(id,doc);outlineBases.set(key,doc.revision_id);writeDraft('outline',key,{text:outlineEdits.get(key),baseRevisionId:doc.revision_id});outlineStatus.delete(key);render()}return; }
    if (button.hasAttribute('data-outline-append') || button.hasAttribute('data-outline-replace')) {
      const record=outlineRecord(state.work.id),scope=outlineScopes.get(state.work.id),doc=record.data?.documents?.find(item=>`${item.scope_type}:${item.scope_id}`===scope);
      if (!doc?.adopted_text) return;
      const textarea=document.getElementById('outlineText');if(!textarea)return;
      if (button.hasAttribute('data-outline-replace') && textarea.value.trim() && !window.confirm('用构思替换当前大纲编辑？本地草稿仍可在保存前撤销。')) return;
      textarea.value=button.hasAttribute('data-outline-append')&&textarea.value.trim()?`${textarea.value.trim()}\n\n${doc.adopted_text}`:doc.adopted_text;
      textarea.dispatchEvent(new Event('input',{bubbles:true})); textarea.focus();
    }
  });
  document.addEventListener('submit', event => {
    const form=event.target;
    if (!['worldDraftForm','worldCreateWorkForm','outlineDocumentForm','workWorldOverviewForm'].includes(form.id)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    void (async()=>{
      if(form.id==='worldDraftForm'){
        if(worldSaving)return;
        const id=currentWorldId(),current=id?worldCache.get(id):null;
        if(current&&worldEdits.has(id)&&worldEdits.get(id).baseVersion!==current.version)return;
        const payload={title:form.elements.title.value,overview:form.elements.overview.value};
        if(!id&&form.elements.world_seed?.checked)payload.world_seed='ba_starter';
        if(current)payload.expected_version=current.version;
        worldSaving=true;worldError='';render();
        try{const saved=await api(id?`/world-drafts/${encodeURIComponent(id)}`:'/world-drafts',{method:'POST',body:JSON.stringify(payload)});
          worldCache.set(saved.id,saved);worldEdits.delete(id||'new');clearDraft('world',id||'new');worlds=null;await loadWorlds(true);worldError='';navigateRoute({section:'worlds',worldDraftId:saved.id});
        }catch(error){worldError=error.status===409?'底稿已有新版本；本地输入仍保留。请重新载入比较。':error.message||'保存失败，请重试。';}
        finally{worldSaving=false;refreshVisible('worlds');}
      }else if(form.id==='worldCreateWorkForm'){
        const id=currentWorldId(),world=worldCache.get(id);if(!world)return;
        const button=form.querySelector('[type="submit"]');button.disabled=true;
        try{const result=await api(`/world-drafts/${encodeURIComponent(id)}:create-work`,{method:'POST',body:JSON.stringify({expected_version:world.version,title:form.elements.title.value})});
          state.work=result.work;state.works=[result.work,...state.works.filter(item=>item.id!==result.work.id)];
          navigateRoute(form.elements.destination.value==='outline'?{section:'writing',stage:'structure'}:{section:'references',library:'world'});
        }catch(error){worldError=error.message||'建立作品失败。';refreshVisible('worlds');}
        finally{button.disabled=false;}
      }else if(form.id==='workWorldOverviewForm'){
        const id=state.work.id,overview=form.elements.overview.value,current=worldBible();
        const currentRevision=state.work.artifacts?.find(item=>item.kind==='world_bible')?.current_revision?.id||null;
        if(workWorldEdits.has(id)&&workWorldBases.get(id)!==currentRevision)return;
        if(!workWorldBases.has(id))workWorldBases.set(id,currentRevision);
        workWorldEdits.set(id,overview);writeDraft('work-world',id,{text:overview,baseRevisionId:workWorldBases.get(id)});
        const button=form.querySelector('[type="submit"]');button.disabled=true;
        try{const result=await api(`/works/${encodeURIComponent(id)}/world-bible`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,...current,overview})});
          if(state.work?.id!==id)return;
          state.work=result.work;workWorldEdits.delete(id);workWorldBases.delete(id);clearDraft('work-world',id);workWorldStatus.set(id,'saved');render();
        }catch(error){workWorldStatus.set(id,error.status===409?'世界观已有新版本；本地输入仍保留，请重新载入并比较。':error.message||'保存失败，请重试。');
          const status=form.querySelector('.authoring-error')||document.createElement('p');status.className='authoring-error';status.setAttribute('role','alert');status.textContent=workWorldStatus.get(id);form.querySelector('.authoring-form-actions')?.before(status);
        }finally{button.disabled=false;}
      }else{
        const workId=state.work?.id,record=outlineRecord(workId),scope=outlineScopes.get(workId),doc=record.data?.documents?.find(item=>`${item.scope_type}:${item.scope_id}`===scope);
        if(!doc)return;
        const key=outlineKey(workId,doc),text=form.elements.text.value;
        if(outlineEdits.has(key)&&outlineBases.get(key)!==doc.revision_id)return;
        if(!outlineBases.has(key))outlineBases.set(key,doc.revision_id);
        outlineEdits.set(key,text);writeDraft('outline',key,{text,baseRevisionId:outlineBases.get(key)});outlineStatus.set(key,'saving');render();
        try{const result=await api(`/works/${encodeURIComponent(workId)}/outline`,{method:'POST',body:JSON.stringify({expected_version:state.work.version,scope_type:doc.scope_type,scope_id:doc.scope_id,expected_base_revision_id:doc.revision_id,text})});
          if(state.work?.id!==workId)return;
          state.work=result.work;record.data=result.outline;record.error='';outlineEdits.delete(key);outlineBases.delete(key);clearDraft('outline',key);outlineStatus.set(key,'saved');
        }catch(error){outlineStatus.set(key,error.status===409?'conflict':error.message||'保存失败，请重试。');}
        finally{if(state.work?.id===workId)render();}
      }
    })();
  },true);
  window.addEventListener('beforeunload', event => {
    if(!outlineEdits.size&&!worldEdits.size&&!workWorldEdits.size)return;
    // Drafts are saved in sessionStorage, but still make a deliberate reload visible.
    event.preventDefault();event.returnValue='';
  });
  window.HaloCueAuthoringWorkspace=Object.freeze({renderWorldDrafts,renderOutline,populateWorkForm,workOverviewMarkup,worldTitle});
})();
