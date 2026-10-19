/* Task guidance is a projection of existing work state, never a second workflow. */
(function (root) {
  'use strict';
  const storageKey = 'halocue.guided-authoring.v1';
  const modes = ['suggest', 'guided', 'free'];
  function preferences(value) {
    return {
      mode: modes.includes(value?.mode) ? value.mode : 'suggest',
      paused: value?.paused === true,
      deferred: value?.deferred && typeof value.deferred === 'object' && !Array.isArray(value.deferred) ? value.deferred : {},
    };
  }
  function project(input) {
    if (!input.workId || input.busy) return null;
    const task = (scope, action, dependency, title, detail, label) => ({
      scope, action, title, detail, label,
      key: JSON.stringify([input.workId, scope, action, dependency]),
    });
    if (input.surface === 'works') {
      if (!input.workAction || !input.threadId) return null;
      const descriptions = {
        organize: ['把讨论整理为候选', '先核对整理结果，再决定采用；也可以继续讨论。'],
        review: ['有一份结果等你核对', '打开候选，阅读后再决定采用哪些内容。'],
        structure: ['接下来安排章节与场景', '进入大纲继续安排；打开页面不会调用模型。'],
        draft: ['可以进入正文试写', '已有关联的场景，之前的构思要求会一起带入。'],
      };
      const copy = descriptions[input.nextStep];
      return copy ? task(`thread:${input.threadId}`, 'work', input.workDependency, ...copy, input.workLabel) : null;
    }
    if (input.surface !== 'writing' || !input.sceneId) return null;
    const scope = `scene:${input.sceneId}`;
    if (input.dirty) return task(scope, 'save', input.revisionId, '先保存正在修改的正文', '修改仍在本地草稿里，保存后再核对候选。', '保存正文');
    if (input.proposalId) {
      if (input.proposalBase !== input.revisionId) return task(scope, 'manual', [input.proposalId, input.revisionId], '这份候选的正文版本已变化', '先核对当前正文，再让助手重新整理修改；旧候选不会自动采用。', '查看当前正文');
      return task(scope, 'review', input.proposalId, '在原文位置核对这份修改', '阅读前后差异，只采用想保留的变化；采纳前正文保持原样。', '查看第一处改动');
    }
    if (input.revisionId) return task(scope, 'manual', input.revisionId, '正文已保存，可以继续打磨', '可以接着写或在对话中提出修改要求。保存不代表这一章已经写完。', '继续写这一场');
    return task(scope, input.canPrepare ? 'prepare' : 'manual', null, `从《${input.sceneTitle || '当前场景'}》开始`, input.canPrepare ? '先准备试写要求，发送后才生成候选；也可以自己写。' : '可以先自己写。需要助手时，再按当前提示补齐写作依据。', input.canPrepare ? '准备试写' : '自己写');
  }
  function visible(task, value, requested = false) {
    const prefs = preferences(value);
    return Boolean(task && (requested || (!prefs.paused && prefs.mode !== 'free' && prefs.deferred[task.scope] !== task.key)));
  }
  const exports = { preferences, project, visible };
  if (typeof module !== 'undefined' && module.exports) module.exports = exports;
  if (!root.document) return;

  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) { /* Preferences must never block authoring. */ }
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) stored = {};
  const perWork = new Map();
  let requestedKey = '', composing = false, pointerDown = false;
  function prefs() {
    const id = state.work?.id;
    if (!perWork.has(id)) perWork.set(id, preferences(stored[id]));
    return perWork.get(id);
  }
  function persist() {
    if (!state.work?.id) return;
    stored[state.work.id] = prefs();
    try { localStorage.setItem(storageKey, JSON.stringify(stored)); } catch (_) { /* Keep the current session usable. */ }
  }
  function legacyAction() {
    return document.querySelector('.work-agent-canvas .agent-reply-next-step');
  }
  function snapshot() {
    const surface = state.route?.section;
    const thread = surface === 'works' ? workConversationThread() : sceneConversationThread(selectedScene());
    const latest = [...(thread?.messages || [])].reverse().find(message => message.role === 'assistant');
    const scene = surface === 'works' ? nextWritingScene(state.work?.chapters || [], writingTarget().anchor_scene_id) : selectedScene();
    const revisionId = state.work?.artifacts?.find(item => item.kind === 'scene_script' && item.scope_id === scene?.id)?.current_revision?.id || scene?.current_revision_id || null;
    const proposal = surface === 'writing' ? pendingProposal() : null;
    const action = legacyAction();
    const original = action?.querySelector('button');
    const relevant = state.work?.proposals?.filter(item => item.status === 'pending' && (item.id === latest?.proposal_id || item.id === latest?.content?.proposal_id || item.scope_id === scene?.id)).map(item => item.id) || [];
    const baseInputs = (state.work?.artifacts || []).filter(item => ['brief', 'story_blueprint'].includes(item.kind)).map(item => item.current_revision?.id);
    const canPrepare = Boolean(surface === 'writing' && thread?.id && state.context?.scene_id === scene?.id && sceneReadinessView(state.context).canRun);
    return {
      workId: state.work?.id, surface: surface === 'writing' && state.stage !== 'draft' ? '' : surface,
      threadId: thread?.id, nextStep: latest?.content?.next_step,
      workAction: Boolean(original), workLabel: original?.textContent?.replace('↗', '').trim(),
      workDependency: [latest?.content?.next_step, scene?.id, revisionId, relevant, baseInputs],
      sceneId: scene?.id, sceneTitle: scene?.title, revisionId,
      proposalId: proposal?.id, proposalBase: proposal?.base_revision_id || null,
      dirty: Boolean(state.manuscriptDirty || root.HaloCueChapterAuthoring?.hasUnsavedDrafts),
      busy: Boolean(thread && workAgentActiveRun(thread)), canPrepare,
    };
  }
  function interactionBlocked() {
    const active = document.activeElement;
    return Boolean(composing || pointerDown || hcComposing || hcCommandDepth || state.manuscriptDirty || root.HaloCueChapterAuthoring?.hasUnsavedDrafts || document.querySelector('dialog[open]') || document.getSelection()?.type === 'Range' || active?.matches?.('textarea,input,select,[contenteditable="true"]'));
  }
  function toolbar() {
    let host = document.querySelector('.hc-discussion-tools, .chapter-authoring-save');
    if (!host) return;
    let node = host.querySelector('[data-guidance-controls]');
    if (!node) {
      node = document.createElement('div');
      node.className = 'hc-guidance-controls';
      node.dataset.guidanceControls = '';
      node.innerHTML = '<label><span>引导</span><select aria-label="用户引导模式" data-guidance-mode><option value="suggest">日常陪跑</option><option value="guided">带我完成</option><option value="free">自由创作</option></select></label><button type="button" class="quiet" data-guidance-pause></button><button type="button" class="quiet" data-guidance-request>下一步</button>';
      host.append(node);
    }
    node.querySelector('select').value = prefs().mode;
    const pause = node.querySelector('[data-guidance-pause]');
    pause.textContent = prefs().paused ? '恢复引导' : '暂停';
    pause.setAttribute('aria-pressed', String(prefs().paused));
    pause.hidden = prefs().mode === 'free';
    node.querySelector('[data-guidance-request]').textContent = prefs().paused ? '查看建议' : '下一步';
  }
  function markup(task, work) {
    const action = work ? '' : `<button type="button" class="quiet" data-guidance-action="${task.action}" data-guidance-key="${escape(task.key)}">${escape(task.label)}</button>`;
    const secondary = !work && task.action === 'prepare' ? '<button type="button" class="quiet" data-guidance-action="manual">自己写</button>' : '';
    return `<div class="hc-guidance-copy"><span>${work ? '建议下一步' : '当前任务'}</span><p>${escape(task.title)}</p><small>${escape(task.detail)}</small></div><div class="hc-guidance-actions">${action}${secondary}<button type="button" class="quiet" data-guidance-defer>${work ? '继续讨论' : '暂不提示'}</button></div>`;
  }
  function mount(revealRequested = false) {
    const section = state.route?.section;
    if (!state.work || !['works', 'writing'].includes(section)) return;
    toolbar();
    const input = snapshot(), task = project(input), forced = task?.key === requestedKey;
    const show = visible(task, prefs(), forced);
    const original = legacyAction();
    if (original) original.hidden = !show;
    const work = section === 'works';
    const owner = work ? original?.closest('.message-bubble') : document.querySelector('.chapter-authoring');
    const scroller = work ? original?.closest('[data-work-discussion-scroll]') : null;
    const pinned = scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
    let panel = document.querySelector('[data-guidance-panel]');
    const removePanel = () => {
      const moved = panel?.querySelector('.agent-reply-next-step');
      if (moved) panel.before(moved);
      panel?.remove();
    };
    const expanded = show && (!work || prefs().mode === 'guided' || forced);
    if (!expanded || !owner) { removePanel(); return; }
    if (!panel || panel.parentElement !== owner) {
      removePanel();
      panel = document.createElement('section');
      panel.className = 'hc-task-guidance';
      panel.dataset.guidancePanel = '';
      panel.setAttribute('aria-label', '当前任务引导');
      if (work) owner.insertBefore(panel, original); else owner.querySelector('.chapter-authoring-save')?.after(panel);
    }
    const html = markup(task, work);
    const changed = panel.dataset.taskKey !== task.key;
    if (panel._hcMarkup !== html) { panel.innerHTML = html; panel._hcMarkup = html; }
    if (work) panel.querySelector('.hc-guidance-actions').prepend(original);
    panel.dataset.taskKey = task.key;
    if (scroller && changed && !composing && !document.querySelector('dialog[open]') && ((revealRequested === true && !input.dirty) || (pinned && !interactionBlocked()))) scroller.scrollTop = scroller.scrollHeight;
  }
  function focusComposer() {
    const input = document.querySelector('#workConversationForm textarea');
    input?.focus({ preventScroll: true });
  }
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-guidance-mode]') || !state.work) return;
    prefs().mode = event.target.value;
    requestedKey = '';
    persist(); mount(true);
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-guidance-pause],[data-guidance-request],[data-guidance-defer],[data-guidance-action]');
    if (!button || !state.work) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (button.hasAttribute('data-guidance-pause')) {
      prefs().paused = !prefs().paused; requestedKey = ''; persist(); mount(); return;
    }
    const task = project(snapshot());
    if (button.hasAttribute('data-guidance-request')) {
      if (!task) { toast('当前没有需要推进的建议，可以继续创作。'); return; }
      requestedKey = task.key; mount(true); return;
    }
    const presentedKey = button.dataset.guidanceKey || button.closest('[data-guidance-panel]')?.dataset.taskKey;
    if (!task || (presentedKey && presentedKey !== task.key)) { mount(); return; }
    if (button.hasAttribute('data-guidance-defer')) {
      prefs().deferred[task.scope] = task.key; requestedKey = ''; persist(); mount();
      if (state.route.section === 'works') focusComposer();
      return;
    }
    const action = button.dataset.guidanceAction;
    if (action === 'review') { root.HaloCueWritingWorkbench?.focusDiff(); return; }
    if (action === 'save') { document.querySelector('[data-chapter-save],#sceneManuscriptForm button[type="submit"]')?.click(); return; }
    if (action === 'prepare' || action === 'manual') {
      const proxy = document.createElement('button');
      proxy.type = 'button'; proxy.hidden = true;
      proxy.setAttribute(action === 'prepare' ? 'data-start-scene-drafting' : 'data-start-scene-manual', '');
      document.body.append(proxy); proxy.click(); proxy.remove();
    }
  }, true);
  document.addEventListener('compositionstart', () => { composing = true; }, true);
  document.addEventListener('compositionend', () => { composing = false; }, true);
  document.addEventListener('pointerdown', () => { pointerDown = true; }, true);
  document.addEventListener('pointerup', () => { pointerDown = false; }, true);
  document.addEventListener('pointercancel', () => { pointerDown = false; }, true);
  root.addEventListener('blur', () => { pointerDown = false; });
  // Update only this projection; never rerender a manuscript or composer on input.
  document.addEventListener('input', event => {
    if (event.target.matches('[data-chapter-text],[data-chapter-speaker],#sceneManuscriptForm textarea')) queueMicrotask(mount);
  });
  root.HaloCueGuidance = { ...exports, mount, canReveal: () => !interactionBlocked() };
  registerRenderHook('guided-authoring', mount);
})(typeof window !== 'undefined' ? window : globalThis);
