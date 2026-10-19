/* First-use teaching follows the author's own work and retires after learning. */
(function (root) {
  'use strict';
  const storageKey = 'halocue:onboarding:authoring-v1';
  function lesson(input, record) {
    const item = (step, title, detail, action, label, target = '') => ({step, title, detail, action, label, target});
    if (record.status !== 'active') return null;
    if (record.workId && input.workId !== record.workId) return item(1, '回到正在学习的作品', '这次教学跟着你选定的作品进行，切换作品不会重置学习记录。', 'return', '返回教学作品');
    if (!input.workId) return item(1, '先建立你自己的作品', '起一个名称就可以，人物、世界观和模型都不必现在填完。', 'create', '建立我的作品', '[data-action="new-work"]');
    if (input.targetMissing) return item(3, '重新选择要学习的场景', '之前的场景已经移除。打开章节大纲，选择或建立另一个场景后继续。', 'structure', '重新选择场景');
    if (input.saved) return item(5, '第一段正文已经保存', '你已走过建立作品、进入正文和保存的过程。后续创作不再默认显示教学；需要时可从帮助里重看。', 'finish', '完成教学');
    if (!record.manual && !input.hasIdea && !input.sceneId) return item(2, '说说你想写什么', '在构思输入框写一句人物、场景或看点。使用助手需要连接写作模型，也可以先自己写。', 'idea', '去写下想法', '#workConversationForm textarea');
    if (!input.sceneId) {
      if (input.busy) return item(3, '正在整理你的想法', '等这次操作结束后，再核对结果；教学不会代你确认。', '', '等待本轮结束');
      if (input.planPending) return item(3, '先看懂这份方案候选', '这是助手给出的建议。读完后选择采用或继续修改；采用后才会建立正式方向或场景。', 'plan', '定位待确认方案', '[data-accept-director-proposal]');
      if (input.hasNextAction) return item(3, '把想法带到写作里', '跟着回复下方的下一步操作，建立可写的场景；不必先熟悉所有页面。', 'next', '定位下一步操作', '.agent-reply-next-step button');
      return item(3, '建立第一场正文的位置', '进入章节大纲，添加一个场景。场景就是这一段故事发生的地方。', 'structure', '打开章节大纲', '[data-structure-add-scene]');
    }
    if (!input.atDraft) return item(3, '打开这一场的正文', '左边目录负责找到场景，中间正文负责写作。现在先进入你要写的这一场。', 'draft', '进入第一场正文');
    if (input.dirty) return item(4, '把刚写的内容保存下来', '文字目前还在草稿里。点保存后，HC 才会建立可以回看的正文版本。', 'save', '保存这段正文', '[data-chapter-save]');
    if (input.proposalId) return item(4, '先审查，再采用助手的文字', '在原文位置比较改前与改后，勾选想保留的变化，再点“应用”。教学不会自动替你采纳。', 'review', '查看本次改动', '[data-scene-change]');
    return item(4, input.revisionId ? '试着修改并保存一处正文' : '写下你自己的第一段', input.canPrepare ? '可以让助手试写候选，也可以自己写。已有输入会保留，只有你发送要求后才会生成。' : '先写一两句就够了。没有配置模型也可以手写和保存。', input.canPrepare && !record.manual ? 'prepare' : 'manual', input.canPrepare && !record.manual ? '准备试写要求' : '自己写第一段', '[data-chapter-add],[data-chapter-text]');
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {lesson};
  if (!root.document) return;
  let record = null, completion = false;
  try { record = JSON.parse(localStorage.getItem(storageKey)); } catch (_) { /* A broken preference cannot block work. */ }
  if (!record || !['offered', 'active', 'paused', 'complete', 'dismissed', 'legacy'].includes(record.status)) record = null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const save = () => { try { localStorage.setItem(storageKey, JSON.stringify(record)); } catch (_) { /* Session teaching still works. */ } };
  const revisions = () => Object.fromEntries((state.work?.artifacts || []).filter(item => item.kind === 'scene_script').map(item => [item.scope_id, item.current_revision?.id || null]));
  function bind() {
    if (record?.status !== 'active' || record.workId || !state.work) return;
    record.workId = state.work.id; record.baseline = revisions(); save();
  }
  function snapshot() {
    const list = scenes(), selected = list.find(scene => scene.id === record?.sceneId);
    const scene = record?.sceneId ? selected : list.find(item => item.id === state.sceneId) || list[0];
    if (record?.status === 'active' && state.work?.id === record.workId && scene && !record.sceneId) { record.sceneId = scene.id; save(); }
    const revisionId = revisions()[scene?.id] || null;
    const thread = workConversationThread();
    return {
      workId: state.work?.id, sceneId: scene?.id, revisionId,
      targetMissing: Boolean(record?.sceneId && state.work?.id === record.workId && !scene),
      saved: Boolean(scene && revisionId && revisionId !== record?.baseline?.[scene.id]),
      hasIdea: Boolean(brief()?.idea || (thread?.messages || []).some(item => item.role === 'user')),
      atDraft: state.route?.section === 'writing' && state.stage === 'draft' && state.sceneId === scene?.id,
      dirty: Boolean(state.manuscriptDirty || root.HaloCueChapterAuthoring?.hasUnsavedDrafts),
      proposalId: (state.work?.proposals || []).find(item => item.kind === 'scene_script' && item.scope_id === scene?.id && item.status === 'pending')?.id,
      planPending: Boolean(workPlanProposal()), hasNextAction: Boolean(document.querySelector('.agent-reply-next-step button')),
      busy: Boolean(thread && workAgentActiveRun(thread)),
      canPrepare: Boolean(state.context?.scene_id === scene?.id && sceneReadinessView(state.context).canRun && sceneConversationThread(scene)),
    };
  }
  function clear() {
    document.querySelector('[data-first-task]')?.remove();
    document.querySelectorAll('.hc-first-use-target').forEach(node => node.classList.remove('hc-first-use-target'));
  }
  function mount() {
    if (!state.capabilities || state.projectsLoading) return;
    if (!record) {
      let oldTour = false;
      try { oldTour = Boolean(localStorage.getItem('halocue:onboarding:interface-v2')); } catch (_) { /* Use actual work state. */ }
      record = {status: state.work || state.works?.length || oldTour ? 'legacy' : 'offered'}; save();
    }
    if (!['offered', 'active'].includes(record.status) && !completion) { clear(); return; }
    if (completion && state.work?.id !== record.workId) { completion = false; clear(); return; }
    bind();
    const input = snapshot();
    let task = lesson(input, record);
    if (task?.step === 5) { record.status = 'complete'; save(); completion = true; root.HaloCueGuidance?.stop(); }
    if (completion) task = lesson(input, {...record, status:'active'});
    const owner = document.querySelector('.chapter-authoring') || document.querySelector('.hc-idea-canvas') || document.querySelector('.work-agent-thread') || document.querySelector('.project-home') || document.getElementById('workspace');
    if (!owner) return;
    let panel = document.querySelector('[data-first-task]');
    if (!panel || panel.parentElement !== owner) {
      clear(); panel = document.createElement('section'); panel.className = 'hc-first-task'; panel.dataset.firstTask = ''; panel.setAttribute('aria-label', '首次创作教学');
      const header = owner.matches('.hc-idea-canvas') && owner.querySelector('.hc-canvas-header');
      if (header) header.after(panel); else owner.prepend(panel);
    }
    const offered = record.status === 'offered';
    const html = offered
      ? '<div><span>第一次使用 HaloCue</span><h2>带着自己的作品，学会第一段创作</h2><p>边做边认识构思、正文和保存。完成后教学就会退出，不会在每部作品里重复出现。</p></div><div class="hc-first-task-actions"><button type="button" class="primary" data-first-task-action="start">带我开始</button><button type="button" class="quiet" data-first-task-action="dismiss">我已熟悉，跳过</button></div>'
      : `<div><span>${task.step === 5 ? '首次任务已完成' : `首次创作 · ${task.step} / 4`}</span><h2>${escape(task.title)}</h2><p>${escape(task.detail)}</p></div><div class="hc-first-task-actions"><button type="button" class="primary" data-first-task-action="${task.action}" ${task.action ? '' : 'disabled'}>${escape(task.label)}</button>${task.step === 2 || task.step === 4 && task.action === 'prepare' ? '<button type="button" class="quiet" data-first-task-action="self-write">先自己写</button>' : ''}${task.step === 2 ? '<button type="button" class="quiet" data-first-task-action="model">连接写作模型</button>' : ''}${task.step < 5 ? '<button type="button" class="quiet" data-first-task-action="pause">稍后继续</button>' : ''}</div>`;
    if (panel.innerHTML !== html) panel.innerHTML = html;
    document.querySelectorAll('.hc-first-use-target').forEach(node => node.classList.remove('hc-first-use-target'));
    if (!offered && task.target) document.querySelector(task.target)?.classList.add('hc-first-use-target');
  }
  function start() {
    document.getElementById('settingsDialog')?.close(); document.getElementById('helpDialog')?.close();
    record = record?.status === 'paused' ? {...record, status:'active'} : {status:'active', manual:false};
    completion = false; bind(); mount(); reveal('[data-first-task]');
  }
  function proxy(attribute) {
    const button = document.createElement('button'); button.type = 'button'; button.hidden = true; button.setAttribute(attribute, ''); document.body.append(button); button.click(); button.remove();
  }
  function reveal(selector) {
    const target = selector && document.querySelector(selector);
    if (!target) return;
    const scroll = target.closest('[data-work-discussion-scroll],.workspace');
    if (scroll) scroll.scrollTop += target.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 120;
    if (target.matches('textarea,input,button')) target.focus({preventScroll:true});
  }
  document.addEventListener('click', event => {
    if (event.target.closest('[data-first-task-start]')) { event.preventDefault(); start(); return; }
    const button = event.target.closest('[data-first-task-action]');
    if (!button) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const action = button.dataset.firstTaskAction;
    if (action === 'start') { start(); return; }
    if (action === 'dismiss' || action === 'pause' || action === 'finish') { record.status = action === 'dismiss' ? 'dismissed' : action === 'pause' ? 'paused' : 'complete'; completion = false; save(); clear(); return; }
    if (record?.status !== 'active') return;
    const input = snapshot();
    if (action === 'return') { void root.HaloCueRouter.openWork(record.workId); return; }
    if (input.workId !== record.workId) { mount(); return; }
    const current = lesson(input, record);
    const secondary = (action === 'self-write' && (current?.step === 2 || current?.step === 4)) || (action === 'model' && current?.step === 2);
    if (current?.action !== action && !secondary) { mount(); return; }
    if (action === 'create') { document.querySelector('[data-action="new-work"]')?.click(); return; }
    if (action === 'self-write') { record.manual = true; save(); mount(); return; }
    if (action === 'model') { document.getElementById('openSettingsButton')?.click(); return; }
    if (action === 'idea') { if (state.route.section !== 'works') root.HaloCueRouter.navigate({section:'works'}); reveal('#workConversationForm textarea'); return; }
    if (action === 'structure') { if (input.targetMissing) { delete record.sceneId; save(); } root.HaloCueRouter.navigate({section:'writing',stage:'structure'}); reveal('[data-structure-add-scene]'); return; }
    if (action === 'draft') { void root.HaloCueWritingWorkbench.openScene(input.sceneId); return; }
    if (action === 'plan') { reveal('[data-accept-director-proposal]'); return; }
    if (action === 'next') { reveal('.agent-reply-next-step button'); return; }
    if (action === 'review') { root.HaloCueWritingWorkbench.focusDiff(); return; }
    if (action === 'save') { document.querySelector('[data-chapter-save]')?.click(); return; }
    if (action === 'prepare' || action === 'manual') proxy(action === 'prepare' ? 'data-start-scene-drafting' : 'data-start-scene-manual');
  }, true);
  document.addEventListener('input', event => { if (event.target.matches('[data-chapter-text],[data-chapter-speaker]')) queueMicrotask(mount); });
  root.HaloCueFirstTask = {mount, start};
  registerRenderHook('first-use-task', mount);
})(typeof window !== 'undefined' ? window : globalThis);
