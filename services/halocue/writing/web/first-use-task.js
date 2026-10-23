/* First-use teaching follows the author's own work and retires after learning. */
(function (root) {
  'use strict';
  const storageKey = 'halocue:onboarding:authoring-v1';
  function lesson(input, record) {
    const item = (step, title, detail, action, label, target = '') => ({step, title, detail, action, label, target});
    if (record.status !== 'active') return null;
    if (input.workMissing) return item(1, input.canRestoreTeaching ? '恢复刚才的作品' : '找不到刚才的作品', input.canRestoreTeaching ? '点“恢复作品”就能找回来，正文和旧版本都还在。也可以换一部作品继续。' : '可以去回收站找找，恢复后接着做。也可以从新作品开始。', 'restart', input.workId ? '用当前作品继续' : '从新作品开始', '[data-project-trash-toggle],[data-section="projects"]');
    if (record.workId && input.workId !== record.workId) return item(1, '回到刚才的作品', '刚才还没做完，先回到那部作品接着写。', 'return', '回到刚才的作品');
    if (!input.workId) return item(1, '先建立你自己的作品', '想好名字就填上，暂时没想好也可以留空。其他内容以后再补。', 'create', '建立我的作品', '[data-action="new-work"]');
    if (input.targetMissing) return item(3, '换一个场景继续', '刚才的场景已经删掉了。打开章节大纲，选一个场景，或新建一场。', 'structure', '重新选择场景');
    if (input.saved) return item(5, '第一段正文已经保存', '接下来可以自己写了。想再看一遍操作，到“帮助”里打开新手教学。', 'finish', '完成教学');
    if (input.atProjects) return input.inTrash ? item(1, '回到作品列表继续', '作品已经恢复了。点“返回作品”，再打开它接着写。', 'projects', '返回作品列表', '[data-project-trash-toggle]') : item(1, '打开自己的作品继续', '点“打开构思”，回到刚才的作品。', 'open-work', '打开刚才的作品');
    if (!record.manual && input.recovery) return item(input.sceneId ? 4 : 3, '这次没有成功', '看看这里的原因，再重试或调整设置。刚才发的消息还在；想先动笔，也可以点“先自己写”。', 'recover', '查看重试方法');
    if (!record.manual && !input.hasIdea && !input.sceneId) return item(2, '说说你想写什么', '想写谁？故事从哪里开始？写一点想法，发给助手聊聊。还没连接模型的话，也可以先自己写。', 'idea', '写下想法', '#workConversationForm textarea');
    if (!input.sceneId) {
      if (input.busy) return item(3, '正在整理你的想法', '稍等，整理好后会放在这里，供你确认。', '', '等待回复');
      if (input.planPending) {
        const copy = input.planKind === 'brief_blueprint' ? ['确认故事方向', '看看人物和情节是不是你想要的。合适就点“采纳为正式方向”，不合适可以退回再聊。这一步还没有正文。'] : input.planKind === 'story_structure' ? ['确认章节和场景安排', '看看每一场准备写什么。点“采用并建立结构”会建立目录和空白场景，接下来再写正文。'] : ['确认本章细纲', '看看这一章的情节安排。合适就采纳，还想改就继续聊；正文接下来再写。'];
        return item(3, ...copy, 'plan', '定位待确认方案', '[data-accept-director-proposal]');
      }
      if (input.hasNextAction) return item(3, '按这条回复继续', `点“${input.nextLabel || '下一步操作'}”看看整理结果。读过以后，再决定要不要采用。`, 'next', '找到下一步操作', '.agent-reply-next-step button');
      if (input.atStructure) return item(3, '添加故事的第一场', input.addSceneVisible === false ? '点“目录”展开场景栏，再点“添加场景”。' : '点“添加场景”，给第一场起个名字，就能开始写了。', 'add-scene', '添加第一场', '[data-structure-add-scene]');
      if (!record.manual && input.hasDirection) return item(3, '方向已确认，接着安排场景', input.atDiscussion ? '刚才保存了故事方向，还没有正文。在输入框里说说第一场发生什么，请助手安排章节和场景。只写一场也可以。' : input.compactNav ? '故事方向已经保存。在视图菜单里选“构思讨论”，请助手安排第一场。' : '故事方向已经保存。点“构思讨论”，请助手安排第一场。', 'arrange', '安排第一场');
      return item(3, '先找到正文的位置', input.compactNav ? '在视图菜单里选“章节大纲”，再添加第一场。' : '点顶部的“章节大纲”，再添加第一场。', 'structure', '打开章节大纲', '[data-creation-view="structure"]');
    }
    if (!input.atDraft) return item(3, '打开这一场的正文', input.inDraftView ? input.draftSceneVisible ? '点左侧高亮的场景，开始写这一场。' : '点“目录”展开场景栏，再选要写的那一场。' : input.compactNav ? '在视图菜单里选“正文写作”，再选场景。' : '点顶部的“正文写作”，再从左侧目录选场景。', 'draft', '进入第一场正文');
    if (input.contextEditing) return item(4, '为这一场选好人物', '勾选这场戏里的人物，让助手参考他们的设定，再点“保存资料选择”。这里保存的是参考资料，正文还没开始写。', 'context', '选择参考资料', '#sceneContextForm');
    if (!record.manual && input.preparingScene) return item(4, '正在准备本场资料', '正在读取这一场的参考资料，稍等一下。', 'wait', '等待资料准备');
    if (input.reading && (input.dirty || !input.proposalId && (record.manual || !input.canPrepare))) return item(4, '先切到编辑，再动笔', '点“编辑”就能改正文，刚才写的内容会保留。', 'edit', '切到编辑模式', '[data-chapter-view="edit"]');
    if (input.dirty && input.emptyField) return item(4, '先把这一段填好', '正文不能为空。如果选了“对白”，也要填上说话人。', 'write', '写下第一句', '[data-chapter-text]');
    if (input.dirty) return item(4, '写好后，点这里保存', '点“保存整章”，保存这一章里刚才改过的正文。保存成功，这次教学就结束了。', 'save', '保存这段正文', '[data-chapter-save]');
    if (!record.manual && input.sceneBusy) return item(4, '助手正在回复', '等回复出来再看。想中断的话，点“停止本轮”。', 'wait', '等待回复');
    if (input.proposalId) return item(4, input.reviewSelectionEmpty ? '先勾选想留下的文字' : '看看这段写得怎么样', input.reviewSelectionEmpty ? '还没选中任何改动。勾选想留下的部分，就能点“应用”了；不满意也可以让助手继续改。' : `${input.initialDraft ? '读一遍新稿' : '对照“改前”和“改后”'}，勾选想留下的部分，再点上方的“应用”。这就保存为正式正文了，不用再点“保存整章”。`, 'review', '查看改动', '[data-scene-change]');
    if (!record.manual && input.proposalSuperseded) return item(4, '这份候选不能再用了', input.canPrepare ? input.agentVisible ? '正文或设定已经改过，需要让助手按现在的内容重新写。在这里说说你的要求。' : '正文或设定已经改过。点“Agent”打开助手，让它按现在的内容重新写。' : '正文或设定已经改过。先补上这里提示缺少的资料，再让助手重新写。', input.canPrepare ? 'prepare' : 'setup', '重新写下要求');
    if (!record.manual && input.preparationRequired) return item(4, '先选人物和参考资料', input.agentVisible ? '这里列出了还缺什么，按提示选好人物或补充资料，就可以请助手写了。' : '点“Agent”打开助手，看看还缺哪些资料。', 'setup', '看看还缺什么');
    return item(4, input.revisionId ? '试着修改并保存一处正文' : '写下你自己的第一段', input.canPrepare && !record.manual ? input.agentVisible ? '在这里告诉助手“起草本场”，也可以加上你自己的要求。写好后，由你决定留下哪些。' : '点“Agent”打开助手，再告诉它“起草本场”。' : input.revisionId ? '改一处正文，再点“保存整章”。左上角可以选旁白、动作或对白。' : '点“开始写作”，先写一两句。段落左上角可以选旁白、动作或对白。', input.canPrepare && !record.manual ? 'prepare' : 'manual', input.canPrepare && !record.manual ? '写下要求' : '自己写第一段', '[data-chapter-add],[data-chapter-text]');
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {lesson};
  if (!root.document) return;
  let record = null, layer = null, targets = [], frame = 0;
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
    const plan = workPlanProposal();
    const proposal = (state.work?.proposals || []).find(item => item.kind === 'scene_script' && item.scope_id === scene?.id);
    const reviewChoices = scene ? [...document.querySelectorAll(`[data-chapter-scene="${CSS.escape(scene.id)}"] [data-scene-change]`)] : [];
    return {
      workId: state.work?.id, sceneId: scene?.id, revisionId,
      atProjects: state.route?.section === 'projects', inTrash: Boolean(state.projectsTrashOpen),
      workMissing: Boolean(record?.workId && state.work?.id !== record.workId && !state.works?.some(item => item.id === record.workId)),
      canRestoreTeaching: Boolean(record?.workId && pick(`[data-restore-work="${CSS.escape(record.workId)}"]`)),
      targetMissing: Boolean(record?.sceneId && state.work?.id === record.workId && !scene),
      saved: Boolean(scene && revisionId && revisionId !== record?.baseline?.[scene.id]),
      hasIdea: Boolean(brief()?.idea || (thread?.messages || []).some(item => item.role === 'user')),
      atDraft: state.route?.section === 'writing' && state.stage === 'draft' && state.sceneId === scene?.id,
      inDraftView: state.route?.section === 'writing' && state.stage === 'draft',
      draftSceneVisible: Boolean(scene && pick(`[data-scene="${CSS.escape(scene.id)}"],[data-scene-open="${CSS.escape(scene.id)}"]`)),
      contextEditing: Boolean(pick('#sceneContextForm')),
      preparingScene: Boolean(scene && blueprintIsConfirmed() && state.context?.scene_id !== scene.id && !state._contextBlocked && !state._contextError),
      sceneBusy: Boolean(scene && sceneConversationThread(scene) && workAgentActiveRun(sceneConversationThread(scene))),
      reading: Boolean(document.querySelector('[data-chapter-view="read"][aria-pressed="true"]')),
      atStructure: state.route?.section === 'writing' && state.stage === 'structure',
      compactNav: Boolean(document.querySelector('[data-creation-select]')?.getClientRects().length),
      addSceneVisible: Boolean([...document.querySelectorAll('[data-structure-add-scene]')].some(node => node.getClientRects().length)),
      dirty: Boolean(state.manuscriptDirty || root.HaloCueChapterAuthoring?.hasUnsavedDrafts),
      emptyField: Boolean([...document.querySelectorAll('.chapter-authoring [data-chapter-block]')].some(node => !node.querySelector('[data-chapter-text]')?.value.trim() || node.dataset.blockType === 'dialogue' && !node.querySelector('[data-chapter-speaker]')?.value.trim())),
      proposalId: (state.work?.proposals || []).find(item => item.kind === 'scene_script' && item.scope_id === scene?.id && item.status === 'pending')?.id,
      proposalSuperseded: proposal?.status === 'superseded',
      recovery: Boolean(pick('.scene-agent-recovery-card:has(button),.agent-failure-card:has(button),.agent-recovery-card:has(button)')),
      planPending: Boolean(plan), planKind: plan?.kind,
      hasDirection: blueprintIsConfirmed(), atDiscussion: state.route?.section === 'works',
      reviewSelectionEmpty: Boolean(reviewChoices.length && reviewChoices.every(node => !node.checked)),
      initialDraft: Boolean(scene && document.querySelector(`[data-chapter-scene="${CSS.escape(scene.id)}"] .chapter-inline-review.is-initial-draft`)),
      hasNextAction: Boolean(document.querySelector('.agent-reply-next-step button')),
      nextLabel: document.querySelector('.agent-reply-next-step button')?.textContent.replace('↗', '').trim(),
      busy: Boolean(thread && workAgentActiveRun(thread)),
      canPrepare: Boolean(state.context?.scene_id === scene?.id && sceneReadinessView(state.context).canRun && sceneConversationThread(scene)),
      preparationRequired: Boolean(blueprintIsConfirmed() && state.context?.scene_id === scene?.id && !sceneReadinessView(state.context).canRun),
      agentVisible: Boolean(document.querySelector('#sceneConversationForm')?.getClientRects().length),
    };
  }
  function clear() {
    geometryObserver.disconnect(); layer?.remove(); layer = null; targets = []; document.documentElement.classList.remove('hc-first-use-active');
  }
  const visibleNode = node => Boolean(node?.getClientRects().length && !node.closest('[hidden]'));
  const currentModal = () => [...document.querySelectorAll('dialog[open],#workDialog:not([hidden])')].filter(visibleNode).at(-1);
  function pick(selector) {
    if (!selector) return null;
    const nodes = [...document.querySelectorAll(selector)].filter(node => !node.closest('[data-first-task]') && visibleNode(node));
    return nodes.find(node => node.closest('#workspace')) || nodes[0] || null;
  }
  function taskTargets(task, input) {
    const modal = currentModal();
    if (modal) return [modal];
    const scene = input.sceneId && document.querySelector(`[data-chapter-scene="${CSS.escape(input.sceneId)}"]`);
    if (task.action === 'idea') return [pick('#workConversationForm')];
    if (task.action === 'arrange') return [input.atDiscussion ? pick('#workConversationForm') : pick('[data-creation-view="works"]') || pick('[data-creation-select]')];
    if (task.action === 'prepare') return [pick('#sceneConversationForm') || pick('[data-inspector="agent"]') || pick('[data-panel-toggle="inspector"]')];
    if (task.action === 'setup') return [pick('#sceneConversationForm .scene-discussion-mode') || pick('#sceneConversationForm') || pick('[data-inspector="agent"]') || pick('[data-panel-toggle="inspector"]')];
    if (task.action === 'wait') return [pick('[data-scene-conversation-scroll]'), pick('#sceneConversationForm')];
    if (task.action === 'recover') return [pick('.scene-agent-recovery-card:has(button),.agent-failure-card:has(button),.agent-recovery-card:has(button)')];
    if (task.action === 'restart') return [pick(`[data-restore-work="${CSS.escape(record.workId)}"]`) || pick('[data-project-trash-toggle]') || pick('[data-section="projects"]')];
    if (task.action === 'open-work') return [pick(`.project-open[data-select-work="${CSS.escape(record.workId)}"]`)];
    if (task.action === 'plan') return [pick('[data-accept-director-proposal]')?.closest('.agent-inline-artifact,.work-decision-dock')];
    if (task.action === 'review') return [scene];
    if (!task.action) return [pick('[data-work-discussion-scroll]')];
    if (task.action === 'structure') return [pick(task.target) || pick('[data-creation-select]')];
    if (task.action === 'add-scene') return [pick(task.target) || pick('[data-panel-toggle="tree"]')];
    if (task.action === 'manual') return [scene?.querySelector('[data-chapter-block]') || scene?.querySelector('[data-chapter-add]')];
    if (task.action === 'write') {
      const blocks = [...document.querySelectorAll('.chapter-authoring [data-chapter-block]')];
      return [blocks.find(node => !node.querySelector('[data-chapter-text]')?.value.trim() || node.dataset.blockType === 'dialogue' && !node.querySelector('[data-chapter-speaker]')?.value.trim())];
    }
    if (task.action === 'save') return [pick(task.target), scene];
    if (task.action === 'draft') return [pick(`[data-scene="${CSS.escape(input.sceneId)}"],[data-scene-open="${CSS.escape(input.sceneId)}"]`) || pick(state.route?.section === 'writing' ? '[data-panel-toggle="tree"]' : '[data-creation-view="draft"]') || pick('[data-creation-select]')];
    return [pick(task.target)];
  }
  function clippedRect(node) {
    const rect = node.getBoundingClientRect();
    let left = Math.max(6, rect.left - 5), top = Math.max(6, rect.top - 5), right = Math.min(innerWidth - 6, rect.right + 5), bottom = Math.min(innerHeight - 6, rect.bottom + 5);
    for (let parent = node.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom); }
      if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) { left = Math.max(left, bounds.left); right = Math.min(right, bounds.right); }
    }
    return {left, top, right, bottom, width: Math.max(0, right - left), height: Math.max(0, bottom - top)};
  }
  function position() {
    if (!layer?.isConnected) return;
    const rects = targets.filter(visibleNode).map(clippedRect).filter(rect => rect.width > 1 && rect.height > 1);
    const veil = layer.querySelector('svg'), tip = layer.querySelector('.hc-first-use-tip');
    veil.setAttribute('viewBox', `0 0 ${innerWidth} ${innerHeight}`);
    veil.innerHTML = `<defs><mask id="hc-first-use-mask"><rect width="100%" height="100%" fill="white"/>${rects.map(rect => `<rect x="${rect.left}" y="${rect.top}" width="${rect.width}" height="${rect.height}" rx="7" fill="black"/>`).join('')}</mask></defs><rect width="100%" height="100%" fill="black" fill-opacity=".66" mask="url(#hc-first-use-mask)"/>${rects.map(rect => `<rect x="${rect.left}" y="${rect.top}" width="${rect.width}" height="${rect.height}" rx="7" fill="none" stroke="var(--hc-first-use-accent)" stroke-width="2"/>`).join('')}`;
    const rect = rects[0], margin = 16, gap = 22;
    const sideSpace = rect && Math.max(rect.left, innerWidth - rect.right) - gap - margin;
    tip.style.width = `${Math.min(280, innerWidth - 32, sideSpace >= 110 ? Math.floor(sideSpace) - 2 : 280)}px`;
    const width = tip.offsetWidth, height = tip.offsetHeight;
    let left = margin, top = margin, side = 'dock';
    const clamp = (value, max) => Math.max(margin, Math.min(value, max));
    if (rect) {
      if (innerWidth - rect.right >= width + gap + margin) { left = rect.right + gap; top = clamp(rect.top + rect.height / 2 - height / 2, innerHeight - height - margin); side = 'right'; }
      else if (rect.left >= width + gap + margin) { left = rect.left - gap - width; top = clamp(rect.top + rect.height / 2 - height / 2, innerHeight - height - margin); side = 'left'; }
      else if (innerHeight - rect.bottom >= height + gap + margin) { left = clamp(rect.left + rect.width / 2 - width / 2, innerWidth - width - margin); top = rect.bottom + gap; side = 'bottom'; }
      else if (rect.top >= height + gap + margin) { left = clamp(rect.left + rect.width / 2 - width / 2, innerWidth - width - margin); top = rect.top - gap - height; side = 'top'; }
      else { left = clamp(rect.left, innerWidth - width - margin); top = margin; }
    }
    tip.style.left = `${left}px`; tip.style.top = `${top}px`; tip.dataset.side = side;
    tip.style.setProperty('--pointer-x', `${rect ? clamp(rect.left + rect.width / 2 - left, width - 20) : 20}px`);
    tip.style.setProperty('--pointer-y', `${rect ? clamp(rect.top + rect.height / 2 - top, height - 20) : 20}px`);
    layer.querySelector('[data-first-task-locate]').hidden = Boolean(rect) || !targets.length;
  }
  function schedulePosition() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; position(); }); }
  const geometryObserver = new ResizeObserver(schedulePosition);
  function watchTargets() {
    geometryObserver.disconnect();
    const nodes = new Set();
    for (const target of targets) {
      for (let node = target; node; node = node.parentElement) nodes.add(node);
    }
    nodes.forEach(node => geometryObserver.observe(node));
  }
  function mount() {
    if (!state.capabilities || state.projectsLoading) return;
    document.querySelectorAll('[data-first-task-start]').forEach(button => {
      const label = button.querySelector('b') || button;
      label.textContent = record?.status === 'paused' ? '继续首次创作教学' : button.closest('#helpDialog') ? '重看新手教学' : '重看首次创作教学';
    });
    if (!record) {
      let oldTour = false;
      try { oldTour = Boolean(localStorage.getItem('halocue:onboarding:interface-v2')); } catch (_) { /* Use actual work state. */ }
      record = {status: state.work || state.works?.length || oldTour ? 'legacy' : 'offered'}; save();
    }
    if (record.status === 'offered' && state.work) { record = {status:'active', manual:false}; save(); }
    if (!['offered', 'active'].includes(record.status)) { clear(); return; }
    bind();
    const input = snapshot();
    let task = lesson(input, record);
    if (task?.step === 5) {
      record.status = 'complete'; save(); clear(); root.HaloCueGuidance?.stop();
      toast('正文保存好了。接下来可以自己写了，想重看操作时去“帮助”就行。'); return;
    }
    const offered = record.status === 'offered';
    if (offered) task = {step:1, title:'从你自己的作品开始', detail:'一起新建一部作品，写几句，再保存下来。跟着高亮的地方操作就行。', action:'create', target:'[data-action="new-work"]'};
    const modal = currentModal();
    if (modal && !['workDialog', 'structureDialog'].includes(modal.id)) { clear(); return; }
    if (modal?.id === 'workDialog') task = {...task, title:'先建一部作品', detail:'名字可以留空，其他以后再补。填好后点“建立作品”。'};
    if (modal?.id === 'structureDialog') task = {...task, title:'给第一场起个名字', detail:'先填场景名称，地点和目标以后再补。点“保存结构”后就能写正文。'};
    const owner = modal || document.body;
    if (!layer) {
      layer = document.createElement('div'); layer.className = 'hc-first-use-layer'; layer.dataset.firstTask = ''; layer.setAttribute('popover', 'manual');
      layer.innerHTML = '<svg aria-hidden="true" class="hc-first-use-veil"></svg><section class="hc-first-use-tip" role="region" aria-label="首次创作教学"><div data-first-task-copy aria-live="polite"></div><div class="hc-first-use-actions"></div></section>';
    }
    if (layer.parentElement !== owner) owner.append(layer);
    if (!layer.matches(':popover-open')) layer.showPopover();
    document.documentElement.classList.add('hc-first-use-active');
    const copy = `<span>${offered ? '第一次使用 HaloCue' : `首次创作 · ${task.step} / 4`}</span><h2>${escape(task.title)}</h2><p>${escape(task.detail)}</p>`;
    const body = layer.querySelector('[data-first-task-copy]'); if (body.innerHTML !== copy) body.innerHTML = copy;
    const controls = `${offered ? '<button type="button" class="primary" data-first-task-action="start">带我开始</button><button type="button" class="quiet" data-first-task-action="dismiss">我已熟悉，跳过</button>' : `${task.step === 2 || ['arrange', 'prepare', 'setup', 'recover'].includes(task.action) ? '<button type="button" class="quiet" data-first-task-action="self-write">先自己写</button>' : ''}${task.step === 2 ? '<button type="button" class="quiet" data-first-task-action="model">连接写作模型</button>' : ''}${['return', 'restart'].includes(task.action) || input.targetMissing ? `<button type="button" class="primary" data-first-task-action="${task.action}">${escape(task.label)}</button>` : ''}<button type="button" class="quiet" data-first-task-action="pause">稍后继续</button>`}<button type="button" class="quiet" data-first-task-locate>定位当前操作</button>`;
    const actions = layer.querySelector('.hc-first-use-actions'); if (actions.innerHTML !== controls) actions.innerHTML = controls;
    targets = taskTargets(task, input).filter(Boolean); watchTargets(); schedulePosition();
  }
  function start() {
    document.getElementById('settingsDialog')?.close(); document.getElementById('helpDialog')?.close();
    record = record?.status === 'paused' ? {...record, status:'active'} : {status:'active', manual:false};
    save(); bind(); mount(); targets[0] && revealNode(targets[0]);
  }
  function revealNode(target) {
    if (!target) return;
    const scroll = target.closest('[data-work-discussion-scroll],.workspace,.tree-panel');
    if (scroll) scroll.scrollTop += target.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 120;
    if (target.matches('textarea,input,button')) target.focus({preventScroll:true});
    schedulePosition();
  }
  const reveal = selector => revealNode(pick(selector));
  document.addEventListener('click', event => {
    if (event.target.closest('[data-first-task-locate]')) { revealNode(targets[0]); return; }
    if (event.target.closest('[data-first-task-start]')) { event.preventDefault(); start(); return; }
    const button = event.target.closest('[data-first-task-action]');
    if (!button) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const action = button.dataset.firstTaskAction;
    if (action === 'start') { start(); return; }
    if (action === 'dismiss' || action === 'pause') { record.status = action === 'dismiss' ? 'dismissed' : 'paused'; save(); clear(); mount(); if (action === 'pause') toast('教学已暂停，可从“帮助 → 继续首次创作教学”接着做。'); return; }
    if (record?.status !== 'active') return;
    const input = snapshot();
    if (action === 'restart' && input.workMissing) { record = {status:'active', manual:false}; save(); bind(); mount(); return; }
    if (action === 'return') { void root.HaloCueRouter.openWork(record.workId); return; }
    if (input.workId !== record.workId) { mount(); return; }
    const current = lesson(input, record);
    const secondary = (action === 'self-write' && (current?.step === 2 || current?.step === 4 || ['arrange', 'recover'].includes(current?.action))) || (action === 'model' && current?.step === 2);
    if (current?.action !== action && !secondary) { mount(); return; }
    if (action === 'self-write') { record.manual = true; save(); mount(); return; }
    if (action === 'model') { document.getElementById('openSettingsButton')?.click(); return; }
    if (action === 'structure') { if (input.targetMissing) { delete record.sceneId; save(); } root.HaloCueRouter.navigate({section:'writing',stage:'structure'}); reveal('[data-structure-add-scene]'); return; }
  }, true);
  document.addEventListener('input', event => { if (event.target.matches('[data-chapter-text],[data-chapter-speaker]')) queueMicrotask(mount); });
  document.addEventListener('change', event => { if (event.target.matches('[data-chapter-type],[data-scene-change]')) queueMicrotask(mount); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && record?.status === 'active' && !currentModal()) { record.status = 'paused'; save(); clear(); mount(); } });
  document.addEventListener('scroll', schedulePosition, true); window.addEventListener('resize', schedulePosition);
  new MutationObserver(changes => { if (changes.some(change => !change.target.closest?.('[data-first-task]'))) queueMicrotask(mount); }).observe(document.body, {subtree:true, attributes:true, attributeFilter:['open','hidden']});
  root.HaloCueFirstTask = {mount, start};
  registerRenderHook('first-use-task', mount);
})(typeof window !== 'undefined' ? window : globalThis);
