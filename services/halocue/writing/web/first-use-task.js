/* First-use teaching follows the author's own work and retires after learning. */
(function (root) {
  'use strict';
  const storageKey = 'halocue:onboarding:authoring-v1';
  function lesson(input, record) {
    const item = (step, title, detail, action, label, target = '') => ({step, title, detail, action, label, target});
    if (record.status !== 'active') return null;
    if (input.workMissing) return item(1, input.canRestoreTeaching ? '恢复原来的教学作品' : '教学作品已移出作品列表', input.canRestoreTeaching ? '点亮起的“恢复作品”，原有正文和版本会一起保留。恢复后可返回原教学继续，也可以重新选定自己的作品。' : '可以从作品页的回收站恢复它，再继续原来的教学；也可以重新选定自己的作品。', 'restart', input.workId ? '用当前作品继续' : '从新作品开始', '[data-project-trash-toggle],[data-section="projects"]');
    if (record.workId && input.workId !== record.workId) return item(1, '回到正在学习的作品', '这次教学跟着你选定的作品进行，切换作品不会重置学习记录。', 'return', '返回教学作品');
    if (!input.workId) return item(1, '先建立你自己的作品', '起一个名称就可以，人物、世界观和模型都不必现在填完。', 'create', '建立我的作品', '[data-action="new-work"]');
    if (input.targetMissing) return item(3, '重新选择要学习的场景', '之前的场景已经移除。打开章节大纲，选择或建立另一个场景后继续。', 'structure', '重新选择场景');
    if (input.saved) return item(5, '第一段正文已经保存', '你已走过建立作品、进入正文和保存的过程。后续创作不再默认显示教学；需要时可从帮助里重看。', 'finish', '完成教学');
    if (input.atProjects) return input.inTrash ? item(1, '回到作品列表继续', '作品已经恢复。点亮起的“返回作品”，再打开这部作品继续教学。', 'projects', '返回作品列表', '[data-project-trash-toggle]') : item(1, '打开自己的作品继续', '点亮起的“打开构思”，回到这部作品。已有内容和教学进度都会保留。', 'open-work', '打开教学作品');
    if (!record.manual && input.recovery) return item(input.sceneId ? 4 : 3, '这一步还没有完成', '先看亮起的失败说明，按提示重试或调整设置。之前的输入仍保留；也可以选择先自己写。', 'recover', '定位恢复操作');
    if (!record.manual && !input.hasIdea && !input.sceneId) return item(2, '说说你想写什么', '在构思输入框写一句人物、场景或看点。使用助手需要连接写作模型，也可以先自己写。', 'idea', '去写下想法', '#workConversationForm textarea');
    if (!input.sceneId) {
      if (input.busy) return item(3, '正在整理你的想法', '等这次操作结束后，再核对结果；教学不会代你确认。', '', '等待本轮结束');
      if (input.planPending) {
        const copy = input.planKind === 'brief_blueprint' ? ['确认故事方向', '核对人物、核心冲突和结尾，再点“采纳为正式方向”。这只保存故事方向，还没有正文；不满意可退回继续讨论。'] : input.planKind === 'story_structure' ? ['确认章节和场景安排', '这里安排每一场写什么。核对后点“采用并建立结构”，建立目录和空白场景；正文要进入场景后再写。'] : ['确认本章细纲', '核对本章目标和情节安排，再决定采纳或继续讨论。细纲用于安排写作，还没有正文。'];
        return item(3, ...copy, 'plan', '定位待确认方案', '[data-accept-director-proposal]');
      }
      if (input.hasNextAction) return item(3, '顺着这条回复继续', `点亮起的“${input.nextLabel || '下一步操作'}”。整理出的内容仍是候选，需要你核对后决定。`, 'next', '定位下一步操作', '.agent-reply-next-step button');
      if (input.atStructure) return item(3, '添加故事的第一场', input.addSceneVisible === false ? '先点亮起的“目录”展开场景栏，再点“添加场景”。' : '点亮起的“添加场景”。先填名称，就能进入这一场的正文。', 'add-scene', '添加第一场', '[data-structure-add-scene]');
      if (!record.manual && input.hasDirection) return item(3, '方向已确认，接着安排场景', input.atDiscussion ? '刚才保存的是故事方向，还没有正文。在亮起的输入框描述第一场发生什么，请助手整理章节和场景；只写一场也可以。' : input.compactNav ? '故事方向已保存。在亮起的视图菜单选择“构思讨论”，再请助手安排第一场；也可以先自己写。' : '故事方向已保存。点亮起的“构思讨论”，再请助手安排第一场；也可以先自己写。', 'arrange', '安排自己的第一场');
      return item(3, '先找到正文的位置', input.compactNav ? '在亮起的视图菜单里选择“章节大纲”，再添加第一场。' : '点顶部亮起的“章节大纲”，再为自己的故事添加第一场。', 'structure', '打开章节大纲', '[data-creation-view="structure"]');
    }
    if (!input.atDraft) return item(3, '打开这一场的正文', input.inDraftView ? input.draftSceneVisible ? '点左侧亮起的场景，选定这次要写的正文。' : '先点亮起的“目录”展开场景栏，再选择要写的那一场。' : input.compactNav ? '在亮起的视图菜单里选择“正文写作”，再选择要写的场景。' : '点顶部亮起的“正文写作”，再从左侧目录选择要写的场景。', 'draft', '进入第一场正文');
    if (input.contextEditing) return item(4, '为这一场选好人物', '勾选本场实际出场的人物，让助手知道参考谁的设定。点“保存本场上下文”只保存资料选择，正文接下来再写。', 'context', '固定本场读取范围', '#sceneContextForm');
    if (!record.manual && input.preparingScene) return item(4, '正在准备本场资料', '系统正在读取本场资料并建立对话。准备好后会指出需要补齐的项目，或带你提出试写要求。', 'wait', '等待资料准备');
    if (input.reading && (input.dirty || !input.proposalId && (record.manual || !input.canPrepare))) return item(4, '先切到编辑，再动笔', '点亮起的“编辑”，再写下或修改正文。切换后会保留原有文字和未保存内容。', 'edit', '切到编辑模式', '[data-chapter-view="edit"]');
    if (input.dirty && input.emptyField) return item(4, '先在亮起的段落里写一句', '空白段落还不能保存。先写正文；选择“对白”时，也要填上说话人。', 'write', '写下第一句', '[data-chapter-text]');
    if (input.dirty) return item(4, '写好后，点这里保存', '这些文字还是未保存的草稿。点亮起的“保存整章”，把本章改动保存为正式正文版本；保存成功就完成教学。', 'save', '保存这段正文', '[data-chapter-save]');
    if (!record.manual && input.sceneBusy) return item(4, '正在准备本场候选', '这一轮仍在处理，结束后再核对结果。需要中断时，可以点亮起区域中的“停止本轮”。', 'wait', '等待本轮结束');
    if (input.proposalId) return item(4, input.reviewSelectionEmpty ? '先勾选想留下的文字' : '先审查，再采用助手的文字', input.reviewSelectionEmpty ? '当前没有勾选，暂时不能应用。勾选想保留的改动后，再点“应用”；也可以继续调整候选。' : '比较“改前”和“改后”，只保存勾选的部分。点“应用”后即保存为正式正文，无需再点“保存整章”；保存成功就完成教学。', 'review', '查看本次改动', '[data-scene-change]');
    if (!record.manual && input.proposalSuperseded) return item(4, '之前的候选已失效', input.canPrepare ? input.agentVisible ? '本场设定或正文已经变化，旧候选不能继续采用。在亮起的输入框按当前设定重新提出要求，也可以先自己写。' : '本场设定或正文已经变化，旧候选不能继续采用。先展开亮起的“Agent”，按当前设定重新提出要求，也可以先自己写。' : '本场设定或正文已经变化，旧候选不能继续采用。先按亮起区域的说明补齐写作依据，也可以选择先自己写。', input.canPrepare ? 'prepare' : 'setup', '准备新的试写要求');
    if (!record.manual && input.preparationRequired) return item(4, '先补齐本场写作依据', input.agentVisible ? '亮起的区域列出了当前缺项。按其中的按钮补齐人物或资料，准备好后再告诉助手怎么写；也可以先自己写。' : '先点亮起的“Agent”展开助手，查看本场缺少的写作依据；也可以先自己写。', 'setup', '查看本场缺项');
    return item(4, input.revisionId ? '试着修改并保存一处正文' : '写下你自己的第一段', input.canPrepare && !record.manual ? input.agentVisible ? '在亮起的输入框告诉助手“起草本场”。发送后先审查候选；也可以选择自己写。' : '先点亮起的“Agent”展开助手，再告诉它“起草本场”。也可以选择自己写。' : input.revisionId ? '直接修改亮起的段落，再点“保存整章”。段落左上角可以选择旁白、动作或对白。' : '点亮起的“开始写作”，写一两句。段落左上角可以选择旁白、动作或对白。', input.canPrepare && !record.manual ? 'prepare' : 'manual', input.canPrepare && !record.manual ? '准备试写要求' : '自己写第一段', '[data-chapter-add],[data-chapter-text]');
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
      toast('第一段正文已保存，首次创作教学已完成。以后可从帮助里重看。'); return;
    }
    const offered = record.status === 'offered';
    if (offered) task = {step:1, title:'从你自己的作品开始', detail:'跟着亮起的按钮和小指针，学会写下并保存第一段。学会后就退出。', action:'create', target:'[data-action="new-work"]'};
    const modal = currentModal();
    if (modal && !['workDialog', 'structureDialog'].includes(modal.id)) { clear(); return; }
    if (modal?.id === 'workDialog') task = {...task, title:'这是自己的作品', detail:'名称可留空，其他以后补。填好点“建立作品”。'};
    if (modal?.id === 'structureDialog') task = {...task, title:'给第一场起名', detail:'名称必填，地点和目标可补。点“保存结构”后写正文。'};
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
