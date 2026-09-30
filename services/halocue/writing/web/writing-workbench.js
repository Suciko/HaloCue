/* Focused presentation layer for Works and Writing.
   Domain commands remain in app.js; this file only projects persisted state. */
(() => {
  const scrollBehavior = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
  const ROUTE_STAGES = HC_WRITING_STAGES;
  const chapterTreeExpansion = new Map();
  let trackedChapterWorkspace = null;
  let chapterScrollFrame = 0;
  let chapterPositionTicket = 0;
  let mobileViewTicket = 0;
  let chapterScrollIntentAt = 0;
  let mobileScrollTop = 0;
  let mobileScrollSceneId = '';
  state.writingMobileView ||= 'manuscript';
  const syncRoute = () => syncAppRoute('replace');

  function chapterStatus(chapter) {
    const sceneList = chapter.scenes || [];
    if (!sceneList.length) return { label: '待拆场', tone: 'idle' };
    if (sceneList.every(scene => scene.current_revision_id)) return { label: '正文齐全', tone: 'done' };
    if (sceneList.some(scene => scene.current_revision_id)) return { label: '写作中', tone: 'active' };
    return { label: '待起草', tone: 'idle' };
  }

  function writingReadinessView() {
    if (state.stage === 'structure' || (state.stage === 'draft' && scenes().length)) return {
      blocked: false, tone: 'is-ready', stateLabel: '可手工安排章节',
      progressLabel: '', title: '从章节大纲开始',
      detail: '可以先手工整理卷章与正文；运行 Agent 时仍会检查必要的方向与资料。',
      reason: '', actionLabel: '', targetId: '',
    };
    const harness = state.agentPresentation?.guidance || state.work?.harness || null;
    const formal = typeof blueprintIsConfirmed === 'function' && blueprintIsConfirmed();
    const pending = (state.work?.proposals || []).filter(item => item.status === 'pending' && item.scope_type === 'work');
    const primary = harness?.primary_action || null;
    const direction = harness?.progress?.steps?.find(item => item.id === 'direction');
    const completed = Number(harness?.progress?.completed || 0);
    const total = Number(harness?.progress?.total || 5);
    const targetId = primary?.id === 'proposal.apply' ? primary.target_id || '' : '';
    const needsDecision = harness?.outcome === 'needs_user' && Boolean(targetId);

    if (needsDecision) {
      const proposal=(state.work?.proposals||[]).find(item=>item.id===targetId);
      if(proposal?.kind==='story_structure')return {
        blocked:true,tone:'is-waiting',stateLabel:'章节安排还未采纳',
        progressLabel:`${completed} / ${total} 阶段完成`,
        title:'先确认章节安排，再开始写正文',
        detail:'Agent 已给出章节方案，但还没有建立正式场景。返回构思审查后，点击“采用并建立结构”。',
        reason:'采纳后会出现“开始写第一场”，可直接进入正文；也可以退回继续讨论。',
        actionLabel:'回到构思，审查章节安排',targetId,
      };
      return {
        blocked: true,
        tone: 'is-blocked',
        stateLabel: '作品有待决定事项',
        progressLabel: `${completed} / ${total} 阶段完成`,
        title: harness.headline || '作品建议等待你的决定',
        detail: `有 ${Math.max(1, pending.length)} 项作品 Proposal 尚未处理。写作页已同步这项状态，不会把候选当成正式资料。`,
        reason: '处理或退回待审建议后，系统会重新检查全作方向；方向确认后才开放更多卷章。',
        actionLabel: '返回作品处理建议',
        targetId,
      };
    }
    if (!formal) {
      const ideaAlreadyShared = state.userStatus?.primary_action?.id === 'continue_idea';
      return {
        blocked: true,
        tone: 'is-waiting',
        stateLabel: direction?.status === 'current' ? '全作方向尚未确认' : '全作方向尚未建立',
        progressLabel: `${completed} / ${total} 阶段完成`,
        title: ideaAlreadyShared ? '想法已记录，整理可确认的方向' : (harness?.headline || '先在作品中确认全作方向'),
        detail: '聊天内容不会自动成为正式方向。请在构思中整理方向候选并确认。',
        reason: (state.work?.chapters || []).some(chapter => (chapter.scenes || []).length)
          ? '已有场景仍需先确认全作方向；确认后才开放本场正文。'
          : '先确认全作方向，再建立场景，之后才能写正文。',
        actionLabel: ideaAlreadyShared ? '返回构思整理方向' : '返回构思继续讨论',
        targetId: '',
      };
    }
    return {
      blocked: false,
      tone: 'is-ready',
      stateLabel: '作品状态已同步',
      progressLabel: `${completed} / ${total} 阶段完成`,
      title: '全作方向已确认，写作范围已开放',
      detail: '写作模块读取的是当前正式方向与结构状态；作品资料变化后，这里会自动重新检查。',
      reason: '现在可以继续规划卷章。建立至少一个场景后，正文阶段会开放。',
      actionLabel: '',
      targetId: '',
    };
  }

  function writingReadinessMarkup(readiness = writingReadinessView()) {
    // Once the writing surface is open, the real empty state and primary
    // command teach the workflow without a permanent onboarding panel.
    if (!readiness.blocked) return '';
    const action = readiness.actionLabel
      ? `<button type="button" class="primary" data-writing-return-to-work="${esc(readiness.targetId)}">${esc(readiness.actionLabel)}</button>`
      : '';
    return `<section class="writing-readiness ${readiness.tone}" id="writingReadiness" tabindex="-1" aria-live="polite">
      <div class="writing-readiness-inline">
        <header><span>${esc(readiness.stateLabel)}</span></header>
        <div class="writing-readiness-body"><b>${esc(readiness.title)}</b><p>${esc(readiness.detail)}</p></div>
        ${action}
        <details class="writing-readiness-detail"><summary>查看原因</summary>${writingProgressMarkup()}<p>${esc(readiness.reason)}</p></details>
      </div>
    </section>`;
  }

  function writingBlockedEmptyMarkup(readiness, copy) {
    const action = readiness.actionLabel
      ? `<button type="button" class="primary" data-writing-return-to-work="${esc(readiness.targetId)}">${esc(readiness.actionLabel)}</button>`
      : '';
    return `<section class="chapter-blocked-empty" aria-live="polite">
      <span class="eyebrow">${esc(readiness.stateLabel)}</span>
      <h2>${esc(readiness.title)}</h2>
      <p>${esc(readiness.detail||copy)}</p>
      ${action}
      <details class="chapter-blocked-explanation"><summary>查看原因</summary>${writingProgressMarkup()}<p>${esc(readiness.reason)}</p></details>
    </section>`;
  }

  const blockedSceneNextStepCopy = '先处理作品中的待审决定，完成后这里会开放建立第一场。';

  function writingProgressMarkup() {
    const harness = state.agentPresentation?.guidance || state.work?.harness || {};
    const fallback = [
      { id: 'direction', status: 'current' },
      { id: 'structure', status: 'upcoming' },
      { id: 'draft', status: 'upcoming' },
      { id: 'review', status: 'upcoming' },
      { id: 'release', status: 'upcoming' },
    ];
    const labels = { direction: '方向', structure: '结构', draft: '正文', review: '审查', release: '发布' };
    const steps = harness.progress?.steps?.length ? harness.progress.steps : fallback;
    return `<ol class="writing-progress" aria-label="创作路线">${steps.map((step, index) => `<li class="${esc(step.status || 'upcoming')}" ${step.status === 'current' ? 'aria-current="step"' : ''}><span>${String(index + 1).padStart(2, '0')}</span><b>${esc(labels[step.id] || step.label || step.id)}</b></li>`).join('')}</ol>`;
  }

  function focusWritingReadiness(reason = '', stage = 'structure') {
    const readiness = document.getElementById('writingReadiness');
    if (!readiness) {
      if (reason) showStageGateNotice(stage, reason);
      return;
    }
    readiness.classList.remove('is-explaining');
    void readiness.offsetWidth;
    readiness.classList.add('is-explaining');
    readiness.focus();
    window.setTimeout(() => readiness.classList.remove('is-explaining'), 900);
  }

  function focusWorkProposal(targetId) {
    if (!targetId) return false;
    const selector = CSS.escape(targetId);
    const target = document.querySelector(`[data-proposal-card="${selector}"]`)
      || document.querySelector(`[data-accept-director-proposal="${selector}"]`)?.closest('.proposal');
    if (!target) return false;
    if (target.matches('details')) target.open = true;
    target.classList.add('writing-return-target');
    target.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
    const action = target.querySelector('button:not([disabled])');
    window.setTimeout(() => action?.focus({ preventScroll: true }), 180);
    window.setTimeout(() => target.classList.remove('writing-return-target'), 1400);
    return true;
  }

  async function returnToWorkDecision(targetId = '') {
    const proposal = (state.work?.proposals || []).find(item => item.id === targetId);
    const sourceThreadId = proposal?.candidate?.source_thread_id || '';
    if (sourceThreadId) state.conversationThreadId = sourceThreadId;
    state.surface = 'works';
    state.mobileView = 'writing';
    state.mobileThreadOpen = false;
    state.stage = 'overview';
    state.inspector = 'agent';
    render();
    window.requestAnimationFrame(() => focusWorkProposal(targetId));
    if (sourceThreadId && typeof refreshAgentPresentation === 'function') {
      await refreshAgentPresentation();
      render();
      window.requestAnimationFrame(() => focusWorkProposal(targetId));
    }
  }

  function writingTreeVolumes(){
    const volumes=state.work?.volumes||[],seen=new Set(volumes.flatMap(volume=>(volume.chapters||[]).map(chapter=>chapter.id)));
    const ungrouped=(state.work?.chapters||[]).filter(chapter=>!seen.has(chapter.id));
    return ungrouped.length?[...volumes,{id:'',title:'未分卷章节',chapters:ungrouped,display_only:true}]:volumes;
  }

  function renderWritingTree() {
    const panel = document.getElementById('treePanel');
    if (!panel || !state.work) return;
    const activeChapterId = writingChapter()?.id || state.writingChapterId;
    const releaseGate = stageGate('release');
    const draftGate = stageGate('draft');
    const formal = stageGate('structure').allowed;
    const readiness = writingReadinessView();
    const directionReason = '先建立作品，再安排卷章。';
    const sceneReason = readiness.reason || '先完成当前作品决定，再继续规划场景。';
    panel.innerHTML = `
      <header class="writing-project-head">
        <div><span>当前作品</span><h1 id="workTitle" title="${esc(state.work.title)}">${esc(state.work.title)}</h1></div>
        <button type="button" data-open-work-switch aria-label="切换作品" title="切换作品"><span aria-hidden="true"></span></button>
      </header>
      <section class="writing-tree-head">
        <div><span>作品结构</span><b>${state.work.volumes?.length || 0} 卷 · ${state.work.chapters?.length || 0} 章 · ${scenes().length} 场</b></div>
        <button type="button" data-structure-add-volume class="${formal ? '' : 'writing-gate-locked'}" ${formal ? '' : `data-writing-gate="${esc(directionReason)}"`} aria-label="${formal ? '新建卷' : '新建卷未开放，点击查看原因'}" title="${formal ? '新建卷' : esc(directionReason)}">＋</button>
      </section>
      <div class="scene-tree writing-scene-tree" id="sceneTree">
        ${writingTreeVolumes().map((volume, volumeIndex) => `<section class="writing-volume" data-writing-volume="${esc(volume.id)}">
          <header class="writing-volume-head">
            <div><span>${volume.display_only?'作品章节':'卷 '+String(volumeIndex + 1).padStart(2, '0')}</span><b title="${esc(volume.title)}">${esc(volume.title)}</b></div>
            <button type="button" data-structure-add-chapter="${esc(volume.id)}" class="${formal ? '' : 'writing-gate-locked'}" ${formal ? '' : `data-writing-gate="${esc(directionReason)}"`} aria-label="${formal ? `在${esc(volume.title)}新增章节` : '新增章节未开放，点击查看原因'}" title="${formal ? '在本卷新增章节' : esc(directionReason)}">＋</button>
          </header>
          <div class="writing-volume-chapters">
            ${(volume.chapters || []).map((chapter, chapterIndex) => {
              const status = chapterStatus(chapter);
              const open = chapterTreeExpansion.get(`${state.work.id}:${chapter.id}`) ?? (chapter.id === activeChapterId || (chapter.scenes || []).some(scene => scene.id === state.sceneId));
              return `<section class="writing-chapter ${open ? 'open' : ''}">
                <div class="writing-chapter-row">
                <button type="button" class="writing-chapter-button" data-writing-chapter="${esc(chapter.id)}" aria-current="${chapter.id === activeChapterId ? 'location' : 'false'}">
                  <span class="chapter-index">${String(chapterIndex + 1).padStart(2, '0')}</span>
                  <span class="chapter-copy"><b title="${esc(chapter.title)}">${esc(chapter.title)}</b><small class="chapter-meta"><span>${chapter.scenes?.length || 0} 场</span><em class="${status.tone}">${status.label}</em></small></span>
                </button>
                <button type="button" class="writing-chapter-toggle" data-toggle-writing-chapter="${esc(chapter.id)}" aria-expanded="${open}" aria-label="${open ? '收起' : '展开'}${esc(chapter.title)}的场景"><i aria-hidden="true"></i></button>
                </div>
                <div class="writing-scene-list">
                  ${(chapter.scenes || []).map((scene, sceneIndex) => `<button type="button" class="writing-scene ${scene.id === state.sceneId && state.stage === 'draft' ? 'active' : ''} ${readiness.blocked ? 'writing-gate-locked' : ''}" data-scene="${esc(scene.id)}" ${readiness.blocked ? `data-writing-gate="${esc(sceneReason)}" aria-label="进入本场未开放，点击查看原因"` : ''}>
                    <span>${String(sceneIndex + 1).padStart(2, '0')}</span>
                    <span><b title="${esc(scene.title)}">${esc(scene.title)}</b><small title="${esc(scene.contract?.location || '地点待定')}">${esc(scene.contract?.location || '地点待定')}</small></span>
                    <i class="${scene.current_revision_id ? 'done' : ''}" title="${scene.current_revision_id ? '已有正式正文' : '尚无正文'}"></i>
                  </button>`).join('') || '<p class="writing-tree-empty">本章还没有场景</p>'}
                  <button type="button" class="writing-add-scene ${readiness.blocked ? 'writing-gate-locked' : ''}" data-structure-add-scene="${esc(chapter.id)}" ${readiness.blocked ? `data-writing-gate="${esc(sceneReason)}" aria-label="添加场景未开放，点击查看原因"` : ''}>＋ 添加场景</button>
                </div>
              </section>`;
            }).join('') || '<p class="writing-tree-empty">本卷还没有章节</p>'}
          </div>
        </section>`).join('') || '<div class="writing-tree-zero"><b>先建立第一卷</b><p>可先手工整理卷章结构。</p><button type="button" data-structure-add-volume>建立卷</button></div>'}
      </div>
      <section class="work-surface-note" hidden></section>
      <section class="workflow-guide" id="workflowGuide" hidden></section>`;
  }

  function currentWritingVolume(chapter) {
    const volumes = state.work?.volumes || [];
    return volumes.find(volume => (volume.chapters || []).some(item => item.id === chapter?.id)) || volumes[0] || null;
  }

  function renderCompactStructureWorkspace() {
    const workspace = document.getElementById('workspace');
    if (workspace && window.HaloCueAuthoringWorkspace?.renderOutline(workspace)) return;
    const chapter = writingChapter();
    if (!workspace) return;
    const readiness = writingReadinessView();
    const sceneReason = readiness.reason || '先完成当前作品决定，再继续规划场景。';
    if (!chapter) {
      if (readiness.blocked) {
        workspace.innerHTML = `<div class="chapter-structure-workspace">${writingBlockedEmptyMarkup(readiness, '完成决定后，这里会开放建立第一章。')}</div>`;
      } else {
        workspace.innerHTML = `<div class="chapter-structure-workspace"><section class="chapter-structure-zero"><span>01</span><h2>先建立第一章</h2><p>章节是细纲、场景和正文的稳定范围。建立后，再和 Agent 讨论这一章具体要发生什么。</p><button type="button" class="primary" data-structure-add-chapter>建立第一章</button></section></div>`;
      }
      return;
    }
    const volume = currentWritingVolume(chapter);
    const chapterIndex = Math.max(0, (volume?.chapters || state.work?.chapters || []).findIndex(item => item.id === chapter.id));
    const sceneList = chapter.scenes || [];
    const formal = stageGate('structure').allowed;
    const recommended=nextWritingScene([chapter],writingTarget().anchor_scene_id);
    const hasDraft=sceneList.some(scene=>scene.current_revision_id);
    const entryLabel=recommended?.current_revision_id?'继续写这一场':hasDraft?'开始写下一场':'开始写第一场';
    const command = readiness.blocked ? '' : recommended ? `<section class="writing-handoff" aria-label="本章下一步">
      <div class="writing-handoff-copy"><span>${hasDraft?'继续本章写作':'章节安排已就绪'}</span><h3>${esc(recommended.title)}</h3><p>${esc(recommended.contract?.goal||'从这一场开始，把剧情变成正文。')}</p><small>点击后直接打开正文，不会自动调用模型。下方目录可选择其他场景。</small></div>
      <div class="writing-handoff-actions"><button type="button" class="primary" data-scene-open="${esc(recommended.id)}">${entryLabel} →</button><button type="button" class="quiet" data-inspector="agent">先讨论本章</button></div>
    </section>` : `<section class="chapter-plan-command"><div><span>现在做什么</span><b>先建立本章的第一场</b><small>填写场景名称和目标，保存后就能进入正文。</small></div><button type="button" class="primary" data-structure-add-scene="${esc(chapter.id)}">建立第一场</button></section>`;
    const blockedEmpty = readiness.blocked && !sceneList.length;
    workspace.innerHTML = `<div class="chapter-structure-workspace">
      ${blockedEmpty ? '' : writingReadinessMarkup(readiness)}
      <header class="chapter-structure-head">
        <div>
          <p class="eyebrow">${esc(volume?.title || '第一卷')} · 第 ${String(chapterIndex + 1).padStart(2, '0')} 章</p>
          <h2>${esc(chapter.title)}</h2>
          <p>从推荐场景开始，或在下方选择另一场。这里管理章节安排，正文在具体场景里写。</p>
        </div>
      </header>
      ${command}
      <section class="chapter-scene-board">
        <header><div><span>本章场景</span><b>${sceneList.length} 场</b></div>${sceneList.length && !readiness.blocked ? `<button type="button" class="primary" data-structure-add-scene="${esc(chapter.id)}">新增场景</button>` : ''}</header>
        <div class="chapter-scene-list">${sceneList.length ? sceneList.map((scene, index) => `<article class="chapter-scene-row">
          <span class="scene-order">${String(index + 1).padStart(2, '0')}</span>
          <div class="scene-open">
            <b>${esc(scene.title)}</b>
            <small>${esc(scene.contract?.goal || '本场变化待继续讨论')}</small>
          </div>
          <div class="scene-writing-action">
            <span class="scene-state ${scene.current_revision_id ? 'done' : ''}">${scene.current_revision_id ? '已有正文' : '待起草'}</span>
            <button type="button" class="${scene.current_revision_id ? 'quiet' : 'primary'} ${readiness.blocked ? 'writing-gate-locked' : ''}" data-scene-open="${esc(scene.id)}" ${readiness.blocked ? `data-writing-gate="${esc(sceneReason)}" aria-label="进入本场未开放，点击查看原因"` : ''}>${scene.current_revision_id ? '继续写作' : '打开这一场'}</button>
          </div>
        </article>`).join('') : blockedEmpty ? writingBlockedEmptyMarkup(readiness, blockedSceneNextStepCopy) : `<div class="chapter-scene-empty"><b>这一章还没有场景</b><p>建立第一场后，Agent、上下文和正文都会绑定稳定的场景 ID。</p><button type="button" class="primary" data-structure-add-scene="${esc(chapter.id)}">建立第一场</button></div>`}</div>
      </section>
      <footer class="chapter-structure-actions">
        <button type="button" class="quiet ${formal ? '' : 'writing-gate-locked'}" data-structure-add-chapter="${esc(volume?.id || '')}" ${formal ? '' : `data-writing-gate="${esc(stageGate('structure').reason)}" aria-label="新增章节未开放，点击查看原因"`}>新增章节</button>
        <button type="button" class="quiet ${formal ? '' : 'writing-gate-locked'}" data-structure-add-volume ${formal ? '' : `data-writing-gate="${esc(stageGate('structure').reason)}" aria-label="新增卷未开放，点击查看原因"`}>新增卷</button>
        <span>卷章可以随时手工整理；正文仍按场景逐一审查。</span>
      </footer>
    </div>`;
  }

  function decorateWritingInspector() {
    if (state.surface !== 'writing') return;
    const inspector = document.getElementById('inspectorContent');
    const panel = inspector?.querySelector('.director-panel');
    if (!panel) return;
    panel.querySelector('.director-header')?.remove();
    const chapter = writingChapter();
    const contract = panel.querySelector('.director-task-contract');
    if (contract) {
      const taskLabel = state.stage === 'structure' ? '规划本章细纲' : state.stage === 'draft' ? '处理当前场景' : '检查发布条件';
      contract.classList.add('writing-agent-scope');
      contract.innerHTML = `<div><b>${esc(chapter?.title || '当前章节')}</b><span>${taskLabel}</span></div><em>修改先审查</em>`;
    }
  }

  function decorateWorksRail() {
    const active = Boolean(state.work && state.surface === 'works' && state.stage === 'overview');
    if (!active) return;
    const project = document.querySelector('.work-agent-project');
    if (project) {
      project.hidden = false;
      const projectCopy = project.querySelector(':scope > div');
      if (projectCopy && !projectCopy.querySelector('.project-kicker')) {
        projectCopy.insertAdjacentHTML('afterbegin', '<span class="project-kicker">当前作品</span>');
      }
    }
    const actions = document.querySelector('.work-agent-rail-head .rail-head-actions');
    actions?.querySelector('.rail-work-switch-compact')?.remove();
    const footer = document.querySelector('.work-agent-rail-footer');
    const next = footer?.querySelector('.rail-next-action');
    if (next) next.classList.add('compact-next-action');
  }

  function runStatusLabel(status) {
    return ({ queued: '等待运行', running: '正在思考', waiting_user: '等待你的决定', succeeded: '已完成', failed: '运行失败', cancelled: '已停止' })[status] || status || '已记录';
  }

  function sceneRunPresentation(run) {
    const proposal = run.proposal_id
      ? (state.work?.proposals || []).find(item => item.id === run.proposal_id)
      : null;
    const proposalLabels = {
      pending: '等待你决定',
      accepted: '候选已采用',
      partially_accepted: '候选已部分采用',
      rejected: '候选已退回',
      superseded: '候选已失效',
    };
    return {
      label: proposalLabels[proposal?.status] || runStatusLabel(run.status),
      tone: proposal?.status || run.status || 'recorded',
      proposal,
    };
  }

  function compactSceneContext() {
    const panel = document.querySelector('.scene-context-panel');
    // Keep the full selector visible while the user is editing it. The
    // compact summary is useful at rest, but replacing the form here would
    // make the only explicit context configuration control impossible to use.
    if (!panel || state.stage !== 'draft' || state.sceneContextEditorOpen) return;
    const cards = state.context?.runtime_character_cards?.length || 0;
    const revisions = state.context?.source_revision_ids?.length || 0;
    const assetReferences = state.context?.scene_asset_references?.length || 0;
    const ready = Boolean(state.context);
    const previous = state.context?.previous_scene_context;
    const continuation = previous
      ? `承接《${previous.title}》`
      : '作品起点 · 无前场正文';
    panel.classList.add('scene-context-compact', 'scene-context-secondary');
    panel.innerHTML = `<div class="scene-context-compact-copy">
      <span>章节资料</span>
      <b>${ready ? '已准备' : '准备中'}</b>
      <small>${ready ? `${cards} 张人物卡 · ${assetReferences} 个素材引用 · ${revisions} 份写作资料 · ${esc(continuation)}` : '会读取本章方向、前文和已确认资料'}</small>
    </div><button type="button" class="quiet" data-toggle-scene-context>查看资料</button>`;
  }

  const SCENE_ASSET_KIND_CONFIG = {
    background: { label: '背景', catalogKind: 'backgrounds', customKind: 'background' },
    character: { label: '角色', catalogKind: 'characters', customKind: 'character' },
    sound: { label: '音效', catalogKind: 'sounds', customKind: 'sound' },
    cg: { label: 'CG', catalogKind: 'cg', customKind: 'cg' },
  };

  function sceneAssetReferences(scene = selectedScene()) {
    return Array.isArray(scene?.asset_references) ? scene.asset_references : [];
  }

  function sceneAssetDisplayName(reference) {
    const config = SCENE_ASSET_KIND_CONFIG[reference?.asset_kind] || { label: '素材' };
    const displayName = String(reference?.display_name || '').trim();
    const sourceAssetId = String(reference?.source_asset_id || '').trim();
    if (displayName && displayName !== sourceAssetId) return displayName;
    return config.label === '素材' ? '素材' : `${config.label}素材`;
  }

  function sceneAssetReferenceMarkup(reference) {
    const config = SCENE_ASSET_KIND_CONFIG[reference.asset_kind] || { label: reference.asset_kind || '素材' };
    const source = reference.source_type === 'custom_library'
      ? '全局原件 · 我的素材'
      : reference.source_snapshot?.source === 'writing_catalog'
        ? '1.0 写作资源 · 只读'
        : '全局原件 · AA 资源索引';
    const copyLabel = '副本回执按发布版本记录，不改变本场的原件引用';
    return `<li><span>${esc(config.label)}</span><b>${esc(sceneAssetDisplayName(reference))}</b><small>${esc(source)}</small><details class="scene-asset-reference-details"><summary>技术详情</summary><dl><div><dt>资源标识</dt><dd><code>${esc(reference.source_asset_id || '未记录')}</code></dd></div><div><dt>引用 ID</dt><dd><code>${esc(reference.id || '未记录')}</code></dd></div><div><dt>原件版本</dt><dd>${esc(reference.source_version || '未记录')}</dd></div><div><dt>原件 Hash</dt><dd><code>${esc(reference.content_hash || '未记录')}</code> · ${esc(reference.content_hash_kind || '未标注类型')}</dd></div><div><dt>任务副本状态</dt><dd>${esc(copyLabel)}</dd></div></dl></details></li>`;
  }

  function sceneAssetSuggestionsMarkup(sceneId) {
    const result = state.sceneAssetSuggestions?.[sceneId];
    if (!result) return '<p class="scene-assets-suggestions-loading">正在整理本场建议…</p>';
    if (!result.suggestions?.length) return '<p class="scene-assets-suggestions-empty">当前引用已经覆盖本地规则能识别的素材需求。</p>';
    return `<div class="scene-assets-suggestions-head"><span>本场建议</span><small>本地规则建议 · 未调用模型</small></div><ul>${result.suggestions.map(item => `<li><div><b>${esc(item.label)}</b><small>${esc(item.reason)}</small></div><button type="button" class="quiet" data-scene-asset-suggestion-kind="${esc(item.asset_kind)}" data-scene-asset-suggestion-query="${esc(item.query || '')}" data-scene-asset-suggestion-scene="${esc(sceneId)}">选择${esc(item.label.replace('本场', ''))}</button></li>`).join('')}</ul>`;
  }

  async function loadSceneAssetSuggestions(sceneId) {
    state.sceneAssetSuggestions ||= {};
    try {
      state.sceneAssetSuggestions[sceneId] = await api(`/works/${state.work.id}/scenes/${sceneId}/asset-suggestions`);
    } catch (_) {
      state.sceneAssetSuggestions[sceneId] = { suggestions: [] };
    }
    const panel = document.querySelector('[data-scene-asset-suggestions]');
    if (panel?.dataset.sceneAssetSuggestions === sceneId) panel.innerHTML = sceneAssetSuggestionsMarkup(sceneId);
  }

  function decorateSceneAssets() {
    const scene = selectedScene();
    const contextPanel = document.querySelector('#workspace .scene-context-panel');
    if (!scene || !contextPanel || document.querySelector('[data-scene-assets-panel]')) return;
    const references = sceneAssetReferences(scene);
    if (!references.length) return;
    contextPanel.insertAdjacentHTML('afterend', `<section class="scene-assets-panel" data-scene-assets-panel>
      <div><p class="eyebrow">已选素材</p><h3>${references.length} 项已准备</h3><p>背景、角色和音效只作为本章正文的参考。</p></div>
      <div class="scene-assets-panel-content">${references.length ? `<ul>${references.map(sceneAssetReferenceMarkup).join('')}</ul>` : '<span class="scene-assets-empty">尚未选择素材</span>'}<button type="button" class="quiet" data-scene-asset-picker="${esc(scene.id)}">管理素材</button></div>
      <div class="scene-assets-suggestions" data-scene-asset-suggestions="${esc(scene.id)}">${sceneAssetSuggestionsMarkup(scene.id)}</div>
    </section>`);
    void loadSceneAssetSuggestions(scene.id);
  }

  function sceneAssetPicker() {
    return state.sceneAssetPicker || null;
  }

  function sceneAssetPickerDialog() {
    let dialog = document.getElementById('sceneAssetPickerDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'sceneAssetPickerDialog';
    dialog.className = 'scene-asset-picker-dialog';
    document.body.append(dialog);
    return dialog;
  }

  function sceneAssetComparable(reference) {
    return {
      asset_kind: reference.asset_kind,
      source_type: reference.source_type,
      source_asset_id: reference.source_asset_id,
      display_name: reference.display_name,
      source_version: reference.source_version,
      content_hash: reference.content_hash,
      content_hash_kind: reference.content_hash_kind,
      source_snapshot: reference.source_snapshot || {},
    };
  }

  function stableSceneAssetJson(value) {
    if (Array.isArray(value)) return `[${value.map(stableSceneAssetJson).join(',')}]`;
    if (value && typeof value === 'object') {
      return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableSceneAssetJson(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
  }

  async function sceneAssetSnapshotHash(snapshot) {
    const bytes = new TextEncoder().encode(stableSceneAssetJson(snapshot));
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
  }

  async function loadSceneAssetPickerItems() {
    const picker = sceneAssetPicker();
    if (!picker) return;
    picker.loading = true;
    picker.error = '';
    renderSceneAssetPicker();
    const config = SCENE_ASSET_KIND_CONFIG[picker.kind];
    try {
      const query = new URLSearchParams({ limit: '12', offset: '0', q: picker.query || '' });
      let path;
      if (picker.scope === 'writing') {
        if (!['backgrounds', 'characters'].includes(config.catalogKind)) {
          picker.items = [];
          picker.error = '1.0 写作资源库目前只提供背景和角色语义；音效、CG 请从 AA 内置资源或我的素材中选择。';
          picker.errorCode = 'writing_catalog_kind_unsupported';
          return;
        }
        query.set('kind', config.catalogKind);
        path = `/api/v1/resources/search?${query}`;
      } else {
        if (picker.scope === 'custom') query.set('kind', config.customKind);
        path = picker.scope === 'custom'
          ? `/production/api/v1/custom-assets?${query}`
          : `/production/api/v1/resources/${config.catalogKind}?${query}`;
      }
      const response = await fetch(path);
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        const error = new Error(payload.error?.message || '素材库没有返回可用条目。');
        error.code = [404, 502, 503, 504].includes(response.status) || payload.error?.code === 'production_unavailable'
          ? 'asset_catalog_unavailable'
          : 'asset_catalog_error';
        throw error;
      }
      const items = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.data?.items) ? payload.data.items : [];
      picker.items = items.filter(item => sceneAssetItemMatchesPicker(item, picker));
    } catch (error) {
      picker.items = [];
      picker.errorCode = error.code || 'asset_catalog_error';
      picker.error = picker.errorCode === 'asset_catalog_unavailable'
        ? '素材库服务未连接。'
        : error.message || '素材库暂时不可用。';
    } finally {
      picker.loading = false;
      renderSceneAssetPicker();
    }
  }

  function sceneAssetPickerQuickQueries(picker) {
    if (picker.scope !== 'writing') return [];
    if (picker.kind === 'background') return ['室内', '室外', '白天', '夜晚'];
    if (picker.kind === 'character') return ['阿拜多斯', '千年', '格黑娜', '崔尼蒂'];
    return [];
  }

  function sceneAssetSourceOptions(kind) {
    if (kind === 'background') return [['writing', '1.0 写作资源'], ['custom', '我的素材']];
    if (kind === 'character') return [['writing', '1.0 写作资源'], ['builtin', 'AA 内置'], ['custom', '我的素材']];
    return [['builtin', 'AA 内置'], ['custom', '我的素材']];
  }

  function sceneAssetItemKey(item, picker) {
    if (picker.scope === 'writing') return String(item.technical?.key || item.key || '').trim();
    if (item.source === 'custom_library') return String(item.asset_id || '').trim();
    return String(item.key || item.identifier || '').trim();
  }

  function sceneAssetItemMatchesPicker(item, picker) {
    if (picker.scope !== 'custom') return true;
    return item?.source === 'custom_library'
      && String(item.kind || '').trim() === String(picker.kind || '').trim();
  }

  function sceneAssetPreviewUrl(item, picker) {
    const key = sceneAssetItemKey(item, picker);
    if (!key || picker.kind === 'sound') return '';
    if (item.source === 'custom_library') {
      return `/production/api/v1/custom-assets/${encodeURIComponent(key)}/preview`;
    }
    const kind = picker.kind === 'character' ? 'characters' : picker.kind === 'background' ? 'backgrounds' : 'cg';
    return `/production/api/v1/resources/${kind}/${encodeURIComponent(key)}/preview`;
  }

  function sceneAssetReadableValue(value) {
    const normalized = String(value || '').trim();
    return ({ indoor: '室内', outdoor: '室外', day: '白天', night: '夜晚', unknown: '' })[normalized] ?? normalized;
  }

  function sceneAssetItemMeta(item, picker) {
    if (picker.scope !== 'writing') {
      return item.source === 'custom_library' ? ['我的素材'] : ['AA 内置资源'];
    }
    if (picker.kind === 'character') {
      const outfitCount = Array.isArray(item.outfits) ? item.outfits.length : 0;
      return [item.club, outfitCount ? `${outfitCount} 套服装` : '', item.avatar_available ? '有头像' : ''].filter(Boolean);
    }
    return [item.place, item.indoor_outdoor, item.time, item.weather, item.mood]
      .map(sceneAssetReadableValue)
      .filter(Boolean)
      .slice(0, 4);
  }

  function sceneAssetItemSelected(item, picker) {
    const key = sceneAssetItemKey(item, picker);
    return picker.references.some(reference => reference.asset_kind === picker.kind && reference.source_asset_id === key);
  }

  function sceneAssetPickerResultMarkup(item, index, picker, config) {
    const name = item.name || item.display_name || `${config.label}素材`;
    const meta = sceneAssetItemMeta(item, picker);
    const preview = sceneAssetPreviewUrl(item, picker);
    const selected = sceneAssetItemSelected(item, picker);
    const fallback = String(name).trim().slice(0, 1) || config.label.slice(0, 1);
    const description = picker.scope === 'writing'
      ? String(item.description || item.usage_hint || '').trim()
      : '';
    return `<article class="scene-asset-result ${selected ? 'selected' : ''}">
      <div class="scene-asset-result-preview" aria-hidden="true"><span>${esc(fallback)}</span>${preview ? `<img src="${esc(preview)}" alt="" loading="lazy" data-scene-asset-preview>` : ''}</div>
      <div class="scene-asset-result-copy"><b>${esc(name)}</b>${meta.length ? `<div class="scene-asset-result-meta">${meta.map(value => `<span>${esc(value)}</span>`).join('')}</div>` : ''}${description ? `<small>${esc(description)}</small>` : ''}</div>
      <button type="button" class="${selected ? 'scene-asset-selected' : 'quiet'}" data-scene-asset-add="${index}" ${selected ? 'disabled' : ''}>${selected ? '已选择' : '选择'}</button>
    </article>`;
  }

  function renderSceneAssetPicker() {
    const picker = sceneAssetPicker();
    const dialog = sceneAssetPickerDialog();
    if (!picker) return;
    const config = SCENE_ASSET_KIND_CONFIG[picker.kind];
    const current = picker.references.filter(reference => reference.asset_kind === picker.kind);
    const hasError = Boolean(picker.error);
    const unavailable = picker.errorCode === 'asset_catalog_unavailable';
    const quickQueries = sceneAssetPickerQuickQueries(picker);
    const sourceOptions = sceneAssetSourceOptions(picker.kind);
    dialog.innerHTML = `<header class="scene-asset-picker-head"><div><p class="eyebrow">本场素材</p><h2>选择本场素材</h2><p>选择只会加入当前场景；素材库原件不会改变。</p></div><button type="button" class="icon-button" data-scene-asset-picker-close aria-label="关闭素材选择">×</button></header>
      <nav class="scene-asset-kind-tabs" aria-label="本场素材类型">${Object.entries(SCENE_ASSET_KIND_CONFIG).map(([kind, item]) => `<button type="button" data-scene-asset-kind="${kind}" class="${picker.kind === kind ? 'active' : ''}" aria-pressed="${picker.kind === kind}">${item.label}</button>`).join('')}</nav>
      <div class="scene-asset-picker-toolbar"><div class="scene-asset-source-toggle">${sourceOptions.map(([scope, label]) => `<button type="button" data-scene-asset-source="${scope}" class="${picker.scope === scope ? 'active' : ''}" aria-pressed="${picker.scope === scope}">${label}</button>`).join('')}</div><span>${current.length ? `已选 ${current.length} 项` : '尚未选择'}</span></div>
      <form class="scene-asset-search" data-scene-asset-search><label for="sceneAssetSearch">搜索${esc(config.label)}</label><div><input id="sceneAssetSearch" name="query" value="${esc(picker.query)}" maxlength="120" autocomplete="off" placeholder="${picker.kind === 'background' ? '例如：雨夜的校园屋顶' : picker.kind === 'character' ? '输入角色名、别名或学校' : `输入${config.label}名称`}"><button type="submit" class="primary">搜索</button></div>${quickQueries.length ? `<div class="scene-asset-quick-filters" aria-label="快捷筛选">${quickQueries.map(value => `<button type="button" data-scene-asset-quick-query="${esc(value)}" class="${picker.query === value ? 'active' : ''}">${esc(value)}</button>`).join('')}</div>` : ''}</form>
      <section class="scene-asset-picker-current"><b>当前${esc(config.label)}引用</b>${current.length ? `<ul>${current.map(reference => `<li><span>${esc(sceneAssetDisplayName(reference))}</span><button type="button" class="quiet" data-scene-asset-remove="${esc(`${reference.asset_kind}:${reference.source_type}:${reference.source_asset_id}`)}">移除</button></li>`).join('')}</ul>` : '<p>还没有本场引用。</p>'}</section>
      <section class="scene-asset-picker-results" aria-live="polite">${picker.loading ? '<p>正在读取素材库…</p>' : picker.error ? `<div class="scene-asset-picker-error"><strong>${esc(picker.error)}</strong><p>${unavailable ? '当前写作服务只保存场景引用，素材条目需要制作服务提供。连接素材库后再选择；不会伪造可选素材。' : picker.scope === 'writing' ? '推荐资源只提供可读的地点、时间和角色信息；选择后仍然只是本场引用。' : '请检查素材库服务状态后重试。'}</p></div>` : picker.items.length ? picker.items.map((item, index) => sceneAssetPickerResultMarkup(item, index, picker, config)).join('') : `<p>${picker.query ? '没有找到匹配素材，换一个地点、角色名或氛围试试。' : '输入名称或使用上方筛选开始查找。'}</p>`}</section>
      <footer class="scene-asset-picker-actions"><span>${hasError ? '素材库未返回条目；场景引用尚未改变。' : '场景 Agent 会读取已确认的引用；不会展示或生成隐藏思维链。'}</span>${hasError ? '<div><button type="button" class="quiet" data-scene-asset-picker-close>关闭</button><button type="button" class="primary" data-scene-asset-picker-retry>重试素材库</button></div>' : `<button type="button" class="primary" data-scene-asset-save ${picker.saving ? 'disabled' : ''}>${picker.saving ? '正在保存' : '确认本场素材'}</button>`}</footer>`;
  }

  async function sceneAssetReferenceFromItem(item, kind) {
    const config = SCENE_ASSET_KIND_CONFIG[kind];
    const writing = sceneAssetPicker()?.scope === 'writing';
    const custom = item.source === 'custom_library';
    const declaredKind = String(item.kind || '').trim();
    if (custom && declaredKind !== kind) {
      throw new Error(`这项自定义素材属于${SCENE_ASSET_KIND_CONFIG[declaredKind]?.label || '其他类型'}，不能放入${config.label}引用。`);
    }
    if (custom && !declaredKind) {
      throw new Error('自定义素材缺少类型信息，未加入本场引用。');
    }
    const sourceAssetId = String(writing ? (item.technical?.key || item.key || '') : custom ? item.asset_id : (item.key || item.identifier || '')).trim();
    const snapshot = {
      source: writing ? 'writing_catalog' : custom ? 'custom_library' : 'resource_index',
      kind,
      asset_id: sourceAssetId,
      key: writing ? (item.technical?.key || item.key || '') : (item.key || item.identifier || ''),
      name: item.name || item.display_name || sourceAssetId,
      aa_hash: item.aa_hash ?? null,
      writing_resource: writing ? { place: item.place || '', time: item.time || '', weather: item.weather || '', season: item.season || '', mood: item.mood || '', club: item.club || '' } : null,
      metadata_version: item.metadata_version ?? null,
      sha256: item.sha256 || item.content_hash || null,
    };
    const fallbackHash = await sceneAssetSnapshotHash(snapshot);
    const declaredHash = String(item.sha256 || item.content_hash || item.aa_hash || fallbackHash);
    return {
      asset_kind: kind,
      // The writing catalog is a semantic view of the same immutable resource
      // identity contract. Persist it as resource_index so the scene reference
      // table and 10's handoff adapter keep their existing boundary.
      source_type: custom ? 'custom_library' : 'resource_index',
      source_asset_id: sourceAssetId,
      display_name: String(item.name || item.display_name || sourceAssetId),
      source_version: String(item.metadata_version || item.version || item.technical?.source_version || `catalog:${fallbackHash.slice(0, 12)}`),
      content_hash: declaredHash,
      content_hash_kind: item.sha256 || item.content_hash ? 'file_sha256' : item.aa_hash ? 'aa_resource_hash' : 'catalog_snapshot_sha256',
      source_snapshot: snapshot,
    };
  }

  async function openSceneAssetPicker(sceneId, kind = 'background', query = '') {
    const scene = scenes().find(item => item.id === sceneId);
    if (!scene) return;
    state.sceneAssetPicker = {
      sceneId,
      kind: SCENE_ASSET_KIND_CONFIG[kind] ? kind : 'background',
      scope: ['background', 'character'].includes(kind) ? 'writing' : 'builtin',
      query: String(query || '').trim(),
      references: sceneAssetReferences(scene).map(sceneAssetComparable),
      items: [],
      loading: false,
      error: '',
      saving: false,
    };
    const dialog = sceneAssetPickerDialog();
    renderSceneAssetPicker();
    if (!dialog.open) dialog.showModal();
    await loadSceneAssetPickerItems();
  }

  async function saveSceneAssetReferences() {
    const picker = sceneAssetPicker();
    if (!picker || !state.work) return;
    picker.saving = true;
    renderSceneAssetPicker();
    try {
      const result = await api(`/works/${state.work.id}/scenes/${picker.sceneId}/asset-references`, {
        method: 'POST',
        body: JSON.stringify({ expected_version: state.work.version, references: picker.references }),
      });
      state.work = result.work;
      state.context = null;
      state.sceneAssetPicker = null;
      sceneAssetPickerDialog().close();
      toast(result.invalidated_proposal_ids?.length ? '素材引用已更新；基于旧上下文的正文候选已失效。' : '本场素材引用已保存；正文与正式资料没有改动。');
      render();
    } catch (error) {
      picker.saving = false;
      picker.error = error.message || '素材引用没有保存。';
      renderSceneAssetPicker();
    }
  }

  function decorateSceneAgent() {
    const panel = document.querySelector('.scene-agent-panel');
    const scene = selectedScene();
    if (!panel || !scene) return;
    if (panel.classList.contains('scene-harness')) {
      return;
    }
    const runs = (state.work?.agent_runs || [])
      .filter(run => run.scope_id === scene.id && !String(run.policy?.workflow || '').startsWith('memory.'))
      .slice(-4)
      .reverse();
    const oldRun = panel.querySelector('.agent-run');
    if (oldRun) oldRun.remove();
    const contextStatus = panel.querySelector('.agent-context-brief b');
    const readiness = state.context?.readiness || {};
    const readinessView = sceneReadinessView(state.context);
    if (contextStatus && state.context && !readinessView.canRun) {
      contextStatus.textContent = readinessView.missingCharacters.length
        ? '已固定，但还缺人物卡'
        : (readinessView.detail || '').includes('Provider') || (readinessView.detail || '').includes('模型')
          ? '已固定，等待真实模型'
          : '已固定，仍有输入未满足';
    }
    const context = panel.querySelector('.agent-context-brief');
    if (context) {
      const cards = state.context?.runtime_character_cards?.length || 0;
      const revisions = state.context?.source_revision_ids?.length || 0;
      context.classList.add('compact');
      context.innerHTML = `<div><b>${state.context ? '本场资料已准备' : '正在准备本场资料'}</b><small>${state.context ? `${cards} 张人物卡 · ${revisions} 份写作资料` : '章节方向、前文与确认资料'}</small></div>${state.context ? '<button class="quiet" type="button" data-inspector="context">查看</button>' : ''}`;
    }
    const history = document.createElement('section');
    history.className = 'scene-agent-history';
    history.innerHTML = `<header><b>最近任务</b><small>${runs.length ? `${runs.length} 条` : '尚未运行'}</small></header>
      ${runs.length ? runs.map((run, index) => {
        const tools = run.tool_calls || [];
        const thinking = run.thinking_summary || run.summary || '';
        const presentation = sceneRunPresentation(run);
        return `<article class="scene-run ${esc(presentation.tone)}">
          <div class="scene-run-line"><span class="run-dot"></span><div><b>${esc(run.instruction || '本场写作任务')}</b><small>${index === 0 ? '最近一次' : '历史任务'} · ${esc(presentation.label)}</small></div></div>
          ${thinking ? `<details class="scene-run-thinking"><summary>查看思考摘要</summary><p>${esc(thinking)}</p></details>` : ''}
          ${tools.length ? `<details class="scene-run-tools"><summary>查看运行过程 · ${tools.length} 项</summary><div>${tools.map(tool => `<span>${esc(tool.display_name || tool.name || tool.tool_name || '写作工具')}</span>`).join('')}</div></details>` : ''}
        </article>`;
      }).join('') : '<p class="scene-agent-empty">先讨论本场目标，或直接让 Agent 提出一份可审阅候选。所有修改都会先进入 Proposal。</p>'}`;
    (context || panel.firstElementChild)?.after(history);
    const panelHeader = panel.querySelector(':scope > header');
    if (panelHeader) {
      panelHeader.querySelector('.eyebrow')?.remove();
      const title = panelHeader.querySelector('h3');
      const scope = panelHeader.querySelector('p');
      if (title) title.textContent = '场景 Agent';
      if (scope) scope.textContent = `${scene.chapterTitle} · ${scene.title} · 仅处理当前场景`;
    }
    const textarea = panel.querySelector('#agentRunForm textarea');
    if (textarea) textarea.placeholder = '描述希望 Agent 检查或改写的内容…';
    const discussChip = panel.querySelector('[data-agent-instruction^="先讨论这场"]');
    if (discussChip) {
      discussChip.dataset.agentInstruction = '调整本场节奏：压缩解释，让动作和停顿先出现。';
      discussChip.textContent = '调整节奏';
    }
    const submit = panel.querySelector('#agentRunForm button[type="submit"]');
    if (submit) submit.textContent = '提交任务';
  }

  function focusSceneDiff(changeId = '', restoring = false) {
    // Explicit review navigation wins over the scene-position correction
    // scheduled by the render that just mounted this result.
    chapterPositionTicket++;
    // Review lives in the manuscript. Do not focus an inert, hidden diff
    // while the mobile Agent tab is still selected.
    if (window.matchMedia('(max-width: 760px)').matches && state.writingMobileView !== 'manuscript') {
      // Use the same tab transition as the user. Re-rendering here used to
      // replace the cached Agent composer with a decision panel, losing the
      // discussion on the second round trip.
      const manuscriptTab = document.querySelector('[data-writing-mobile-view="manuscript"]');
      if (manuscriptTab) manuscriptTab.click();
      else { state.writingMobileView = 'manuscript'; state.inspector = 'agent'; render(); }
    }
    const proposal=typeof pendingProposal==='function'?pendingProposal():null;
    const diff = proposal?document.querySelector(`[data-scene-diff-root="${CSS.escape(proposal.id)}"]`):document.querySelector('[data-scene-diff-root]');
    if (!diff) {
      toast('候选 Diff 还没有准备好，请稍后再试。', true);
      return false;
    }
    if(!restoring)state._pendingSceneReviewFocus={proposalId:diff.dataset.sceneDiffRoot,sceneId:state.sceneId,changeId};
    const target = changeId ? [...diff.querySelectorAll('[data-review-change]')].find(item => item.dataset.reviewChange === changeId) || diff.querySelector('[data-review-change]') || diff : diff.querySelector('[data-review-change]') || diff;
    // The continuous chapter wraps its review in a collapsed details panel.
    // Open that ancestry before scrolling or focusing its hidden controls.
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (parent.matches('details')) parent.open = true;
    }
    target.querySelectorAll('.scene-review-detail').forEach((detail,index) => { if(changeId || index === 0)detail.open=true; });
    target.classList.add('writing-return-target');
    if(target.matches('.chapter-inline-change')){
      const ticket=chapterPositionTicket,proposalId=diff.dataset.sceneDiffRoot,scrollIntent=chapterScrollIntentAt;
      window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{
        if(scrollIntent!==chapterScrollIntentAt){state._pendingSceneReviewFocus=null;return;}
        if(ticket!==chapterPositionTicket||!target.isConnected||pendingProposal()?.id!==proposalId)return;
        const workspace=target.closest('.workspace'),rect=target.getBoundingClientRect();
        if(workspace){const offset=Math.max(100,(workspace.clientHeight-rect.height)/2);workspace.scrollTo({top:workspace.scrollTop+rect.top-workspace.getBoundingClientRect().top-offset,behavior:'instant'});}
        else target.scrollIntoView({block:'center',behavior:'instant'});
        if(state._pendingSceneReviewFocus?.proposalId===proposalId)state._pendingSceneReviewFocus=null;
      }));
    }else{target.scrollIntoView({behavior:scrollBehavior(),block:'start'});state._pendingSceneReviewFocus=null;}
    const firstChange = target.querySelector('input[type="checkbox"]');
    window.setTimeout(() => firstChange?.focus({ preventScroll: true }), 180);
    window.setTimeout(() => target.classList.remove('writing-return-target'), 1400);
    return true;
  }

  function focusSceneReview() {
    const review = document.querySelector('.scene-review-summary, .review-findings');
    if (!review) {
      state.inspector = 'decision';
      state.writingMobileView = 'review';
      render();
      return true;
    }
    if (review.matches('details')) review.open = true;
    review.classList.add('writing-return-target');
    review.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
    const firstAction = review.querySelector('button:not([disabled])');
    window.setTimeout(() => firstAction?.focus({ preventScroll: true }), 180);
    window.setTimeout(() => review.classList.remove('writing-return-target'), 1400);
    return true;
  }

  function currentSceneReview(scene = selectedScene()) {
    if (!scene?.current_revision_id) return { gate: null, findings: [], blockers: [] };
    const gates = (state.work?.gates || []).filter(gate =>
      gate.kind === 'scene.review'
      && gate.scope_id === scene.id
      && gate.snapshot?.revision_id === scene.current_revision_id
    );
    // The work API returns gates newest-first. The current Revision must use
    // the newest matching gate; taking the last item resurrects an older
    // blocked result after a successful re-check.
    const gate = gates.length ? gates[0] : null;
    const findings = (state.work?.review_findings || []).filter(finding =>
      finding.scene_id === scene.id
      && finding.revision_id === scene.current_revision_id
      && finding.status === 'open'
    );
    return {
      gate,
      findings,
      blockers: findings.filter(finding => finding.severity === 'blocking'),
    };
  }

  function renderMobileSceneDrawer() {
    let dialog = document.getElementById('mobileSceneDrawer');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'mobileSceneDrawer';
      dialog.className = 'mobile-scene-drawer';
      document.body.append(dialog);
    }
    const tree = document.getElementById('sceneTree');
    dialog.innerHTML = `<div class="mobile-scene-drawer-shell">
      <header><div><span>当前作品</span><b>${esc(state.work.title)}</b></div><button type="button" data-close-mobile-scenes aria-label="关闭场景列表">×</button></header>
      <div class="mobile-scene-drawer-tree">${tree?.innerHTML || '<p>还没有章节与场景。</p>'}</div>
      <footer><button type="button" data-stage="structure">管理章节与场景</button></footer>
    </div>`;
    const trigger = document.querySelector('.mobile-scene-trigger');
    if (trigger) trigger.onclick = event => {
      event.preventDefault();
      if (!dialog.open) dialog.showModal();
    };
    dialog.querySelector('[data-close-mobile-scenes]')?.addEventListener('click', () => dialog.close());
  }

  async function openScene(sceneId, control = null) {
    const scene = scenes().find(item => item.id === sceneId);
    if (!scene) return false;
    const gate = stageGate('draft');
    if (!gate.allowed) {
      explainWritingGate(gate.reason);
      return false;
    }
    const chapter = (state.work?.chapters || []).find(item =>
      (item.scenes || []).some(candidate => candidate.id === scene.id)
    );
    if (!chapter) {
      toast('目标场景已经不在当前章节结构中，请重新加载作品。', true);
      return false;
    }
    if (control) control.disabled = true;
    try {
      if (typeof persistWritingTarget === 'function') {
        await persistWritingTarget(chapter.id, scene.id);
      }
    } catch (error) {
      if (control) control.disabled = false;
      toast(`场景没有切换：恢复位置保存失败。${error.message}`, true);
      return false;
    }
    state.sceneId = scene.id;
    state.writingChapterId = chapter.id;
    state.surface = 'writing';
    state.mobileView = 'writing';
    state.writingMobileView = 'manuscript';
    state.stage = 'draft';
    state.inspector = 'agent';
    state.context = null;
    state._contextError = '';
    state.sceneContextEditorOpen = false;
    state._pendingChapterSceneScroll = scene.id;
    document.getElementById('mobileSceneDrawer')?.close();
    render();
    return true;
  }

  function scrollToChapterScene(sceneId) {
    const anchor = document.getElementById(`chapter-scene-${sceneId}`);
    if (!anchor) return false;
    const mobileTabs = document.querySelector('.writing-mobile-tabs');
    const mobileOffset = window.matchMedia?.('(max-width: 760px)').matches
      ? (mobileTabs?.getBoundingClientRect().height || 0) + 12
      : 18;
    const workspace = anchor.closest('.workspace');
    if (workspace) {
      // The chapter heading belongs to the first scene's entry, not offscreen.
      const firstScene=anchor.closest('.chapter-continuous')?.querySelector('[data-chapter-scene-anchor]');
      const top = firstScene===anchor ? 0 : anchor.getBoundingClientRect().top
        - workspace.getBoundingClientRect().top
        + workspace.scrollTop - mobileOffset;
      workspace.scrollTo({ top: Math.max(0, top), behavior: scrollBehavior() });
    } else {
      anchor.scrollIntoView({ block: 'start', behavior: scrollBehavior() });
    }
    return true;
  }

  function scheduleChapterPosition(sceneId) {
    const ticket=++chapterPositionTicket,workId=state.work?.id,chapterId=state.writingChapterId;
    const intent=chapterScrollIntentAt;
    // One layout-frame correction, never delayed retries that fight the reader.
    window.requestAnimationFrame(()=>{
      if(ticket!==chapterPositionTicket||state.work?.id!==workId||state.writingChapterId!==chapterId||state.sceneId!==sceneId)return;
      if(state.surface!=='writing'||state.stage!=='draft'||chapterScrollIntentAt!==intent)return;
      if(window.matchMedia('(max-width:760px)').matches&&state.writingMobileView!=='manuscript')return;
      scrollToChapterScene(sceneId);
    });
  }

  function focusChapterScene(sceneId) {
    const target = scenes().find(scene => scene.id === sceneId);
    const chapter = (state.work?.chapters || []).find(item =>
      (item.scenes || []).some(scene => scene.id === sceneId)
    );
    const anchor = document.getElementById(`chapter-scene-${sceneId}`);
    if (!target || !chapter || !anchor) return false;

    // Scene buttons are locators inside the chapter, not page navigation. Keep
    // the continuous manuscript mounted and only move its reading position.
    state.surface = 'writing';
    state.mobileView = 'writing';
    state.stage = 'draft';
    state.sceneId = target.id;
    state.writingChapterId = chapter.id;
    state._lastChapterSceneScroll = target.id;
    // A background run refresh may rebuild the chapter once after this click;
    // leave a stable anchor for the render wrapper to restore instead of
    // letting that refresh return the reader to the top.
    state._pendingChapterSceneScroll = target.id;
    state._ignoreChapterScrollUntil = Date.now() + 1000;
    document.getElementById('mobileSceneDrawer')?.close();
    syncSceneChrome(target);

    if (typeof persistWritingTarget === 'function') {
      void persistWritingTarget(chapter.id, target.id).catch(error => {
        toast(`场景位置未保存，但正文没有改变：${error.message}`, true);
      });
    }

    return scrollToChapterScene(target.id);
  }

  function sceneAtReadingPosition(workspace) {
    const anchors = [...workspace.querySelectorAll('[data-chapter-scene-anchor]')];
    if (!anchors.length) return null;
    if (workspace.scrollTop + workspace.clientHeight >= workspace.scrollHeight - 8) {
      return anchors[anchors.length - 1].dataset.chapterSceneAnchor || null;
    }
    const workspaceTop = workspace.getBoundingClientRect().top;
    // Keep the active scene stable while its heading is in the upper reading
    // band; this avoids flickering when a heading is close to the viewport.
    const threshold = Math.min(180, Math.max(88, workspace.clientHeight * 0.22));
    let current = anchors[0];
    for (const anchor of anchors) {
      if (anchor.getBoundingClientRect().top - workspaceTop <= threshold) current = anchor;
      else break;
    }
    return current.dataset.chapterSceneAnchor || null;
  }

  function syncSceneFromScroll() {
    chapterScrollFrame = 0;
    if (state.stage !== 'draft' || state.surface !== 'writing' || state.mobileView !== 'writing' || state.writingMobileView !== 'manuscript') return;
    if (state._writingMobileRestoreUntil && Date.now() < state._writingMobileRestoreUntil) return;
    if (state._mobileViewSwitching) return;
    if (state._ignoreChapterScrollUntil && Date.now() < state._ignoreChapterScrollUntil) return;
    // Browser focus management can scroll a sticky view switch into view before
    // its click event runs. That movement is not a reading decision and must
    // not switch the active scene back to the first heading.
    if (!chapterScrollIntentAt || Date.now() - chapterScrollIntentAt > 1200) return;
    // Never discard an in-progress manuscript draft just because the reader
    // crossed another scene heading. Save or explicitly leave first.
    if (state.manuscriptDirty) return;
    const workspace = document.getElementById('workspace');
    if (!workspace || !workspace.querySelector('[data-chapter-scene-anchor]')) return;
    const nextSceneId = sceneAtReadingPosition(workspace);
    if (!nextSceneId || nextSceneId === state.sceneId) return;
    const nextScene = scenes().find(scene => scene.id === nextSceneId);
    if (!nextScene) return;
    state.sceneId = nextScene.id;
    state.writingChapterId = nextScene.chapter_id;
    // The chapter keeps one shared context while the reader moves between
    // scene headings. Scene-local contracts remain internal inputs.
    // Keep the continuous manuscript DOM stable. Replacing the active scene's
    // editor here changes document height and makes a normal scroll feel like
    // a page jump. Explicit scene actions can still render the editor.
    state._lastChapterSceneScroll = nextScene.id;
    state._pendingChapterSceneScroll = '';
    mobileScrollSceneId = nextScene.id;
    syncSceneChrome(nextScene);
  }

  function scheduleSceneScrollSync() {
    const workspace = document.getElementById('workspace');
    if (workspace
      && state.stage === 'draft'
      && state.surface === 'writing'
      && state.mobileView !== 'tasks'
      && state.writingMobileView === 'manuscript'
      && !state._writingMobileRestoreUntil
      && !state._mobileViewSwitching
      && !state._pendingMobileViewSwitch) {
      // Keep the latest real manuscript position independently of scene
      // inference so Agent/review pane focus cannot replace it.
      mobileScrollTop = workspace.scrollTop;
      workspace.dataset.manuscriptScrollTop = String(workspace.scrollTop);
    }
    if (chapterScrollFrame) return;
    chapterScrollFrame = window.requestAnimationFrame(syncSceneFromScroll);
  }

  function bindChapterScrollTracking() {
    const workspace = document.getElementById('workspace');
    if (!workspace || state.stage !== 'draft') return;
    if (trackedChapterWorkspace === workspace) return;
    trackedChapterWorkspace?.removeEventListener('scroll', scheduleSceneScrollSync);
    trackedChapterWorkspace?.removeEventListener('wheel', markChapterScrollIntent);
    trackedChapterWorkspace?.removeEventListener('touchmove', markChapterScrollIntent);
    trackedChapterWorkspace?.removeEventListener('keydown', markChapterScrollIntent);
    trackedChapterWorkspace?.removeEventListener('pointerdown', markChapterScrollIntent);
    trackedChapterWorkspace = workspace;
    workspace.addEventListener('scroll', scheduleSceneScrollSync, { passive: true });
    workspace.addEventListener('wheel', markChapterScrollIntent, { passive: true });
    workspace.addEventListener('touchmove', markChapterScrollIntent, { passive: true });
    workspace.addEventListener('keydown', markChapterScrollIntent, { passive: true });
    workspace.addEventListener('pointerdown', markChapterScrollIntent, { passive: true });
  }

  function markChapterScrollIntent(event) {
    if (event.type === 'pointerdown') {
      const viewButton = event.target.closest?.('.writing-mobile-tabs button[data-writing-mobile-view]');
      if (viewButton) {
        const workspace = document.getElementById('workspace');
        state._pendingMobileViewSwitch = true;
        if (viewButton.dataset.writingMobileView !== 'manuscript' && workspace) {
          mobileScrollTop = workspace.scrollTop;
          workspace.dataset.manuscriptScrollTop = String(workspace.scrollTop);
          mobileScrollSceneId = document.querySelector('[data-chapter-scene-anchor].is-current')?.dataset.chapterSceneAnchor || state.sceneId || '';
        }
        return;
      }
      if (event.target.closest?.('.writing-mobile-tabs, .mobile-scene-trigger, button, input, textarea, select')) return;
    }
    chapterScrollIntentAt = Date.now();
  }

  function syncSceneChrome(scene) {
    if (!scene) return;
    const action=document.querySelector('[data-scene-draft-action]');
    if(action&&typeof sceneDraftActionMarkup==='function')action.outerHTML=sceneDraftActionMarkup(scene,pendingProposal());
    document.querySelectorAll('#sceneTree .writing-scene').forEach(button => {
      button.classList.toggle('active', button.dataset.scene === scene.id);
    });
    document.querySelectorAll('#sceneTree .writing-chapter').forEach(chapter => {
      const active = Boolean(chapter.querySelector(`[data-scene="${CSS.escape(scene.id)}"]`));
      const button=chapter.querySelector('.writing-chapter-button'),toggle=chapter.querySelector('.writing-chapter-toggle');
      const open=chapterTreeExpansion.get(`${state.work.id}:${button?.dataset.writingChapter}`) ?? active;
      chapter.classList.toggle('open',open);
      button?.setAttribute('aria-current',active?'location':'false');
      toggle?.setAttribute('aria-expanded',String(open));
      const title=button?.querySelector('.chapter-copy b')?.textContent||'';
      toggle?.setAttribute('aria-label',`${open?'收起':'展开'}${title}的场景`);
    });
    document.querySelectorAll('[data-chapter-scene-anchor]').forEach(anchor => {
      const current = anchor.dataset.chapterSceneAnchor === scene.id;
      anchor.classList.toggle('is-current', current);
      anchor.classList.toggle('is-reading-current', current);
      if (current) anchor.setAttribute('aria-current', 'location');
      else anchor.removeAttribute('aria-current');
    });
    // Update the scene assistant without rebuilding the manuscript scroll
    // owner. A new active scene must not keep the previous scene's chat.
    if (state.stage === 'draft') {
      if(state.context?.scene_id!==scene.id){state.context=null;state._contextError='';state._contextBlocked='';}
      renderInspector();
      ensureSceneContext(scene.id,renderInspector);
      ensureSceneConversation(scene.id);
    }
    if (typeof syncRoute === 'function') syncRoute();
    const crumb = document.getElementById('crumb');
    if (crumb && typeof currentWritingVolume === 'function' && typeof writingChapter === 'function') {
      const chapter = writingChapter();
      const volume = currentWritingVolume(chapter);
      const label = `${volume?.title || '未分卷'} / ${scene.chapterTitle} / ${scene.title}`;
      if (typeof setCrumb === 'function') setCrumb(state.work, label);
      else crumb.textContent = `${state.work.title} / ${label}`;
    }
  }

  function moveInspectorToMobilePane() {
    const narrow = window.matchMedia('(max-width: 760px)').matches;
    const inspector = document.getElementById('inspector');
    const manuscript = document.querySelector('.chapter-manuscript-flow');
    const source = document.getElementById('inspectorContent');
    const existing = document.getElementById('writingMobilePane');
    const setInert = (element, disabled) => {
      if (!element) return;
      element.toggleAttribute('inert', disabled);
      if ('inert' in element) element.inert = disabled;
    };
    if (!narrow || state.stage !== 'draft') {
      if (existing && source) {
        while (existing.firstChild) source.append(existing.firstChild);
        existing.remove();
      }
      inspector?.removeAttribute('aria-hidden');
      setInert(inspector, false);
      manuscript?.removeAttribute('aria-hidden');
      setInert(manuscript, false);
      return;
    }
    const manuscriptHidden = state.writingMobileView !== 'manuscript';
    if (manuscript) {
      if (manuscriptHidden) manuscript.setAttribute('aria-hidden', 'true');
      else manuscript.removeAttribute('aria-hidden');
      setInert(manuscript, manuscriptHidden);
    }
    if (inspector) {
      inspector.setAttribute('aria-hidden', 'true');
      setInert(inspector, true);
    }
    if (existing && state.writingMobileView === 'manuscript') {
      const chatScroll = existing.querySelector('[data-scene-conversation-scroll]');
      if (chatScroll && !existing.hidden) existing.dataset.chatScrollTop = String(chatScroll.scrollTop);
      existing.hidden = true;
      existing.setAttribute('aria-hidden', 'true');
      setInert(existing, true);
      return;
    }
    if (existing) {
      existing.hidden = false;
      existing.setAttribute('role', 'tabpanel');
      existing.setAttribute('aria-labelledby', `writingMobileTab-${state.writingMobileView}`);
      existing.removeAttribute('aria-hidden');
      setInert(existing, false);
      if (existing.dataset.chatScrollTop !== undefined) {
        const savedTop = Number(existing.dataset.chatScrollTop);
        delete existing.dataset.chatScrollTop;
        requestAnimationFrame(() => {
          const scroll = existing.querySelector('[data-scene-conversation-scroll]');
          if (scroll && !existing.hidden) scroll.scrollTop = savedTop;
        });
      }
      return;
    }
    if (state.writingMobileView === 'manuscript') return;
    const tabs = document.querySelector('.writing-mobile-tabs');
    if (!source || !tabs) return;
    const pane = document.createElement('section');
    pane.id = 'writingMobilePane';
    pane.className = `writing-mobile-pane ${state.writingMobileView}`;
    pane.setAttribute('role', 'tabpanel');
    pane.setAttribute('aria-labelledby', `writingMobileTab-${state.writingMobileView}`);
    pane.setAttribute('aria-live', 'polite');
    while (source.firstChild) pane.append(source.firstChild);
    tabs.after(pane);
    requestAnimationFrame(() => {
      const scroll = pane.querySelector('[data-scene-conversation-scroll]');
      if (scroll && pane.isConnected && !pane.hidden) scroll.scrollTop = scroll.scrollHeight;
    });
  }

  function decorateWritingWorkspace() {
    const active = Boolean(state.work && state.surface === 'writing' && state.mobileView === 'writing' && ROUTE_STAGES.has(state.stage));
    const app = document.getElementById('app');
    app?.classList.toggle('writing-workbench-stage', active);
    if (!active) return;
    bindChapterScrollTracking();
    renderWritingTree();
    if (state.stage === 'draft') {
      state.inspector ||= 'agent';
      document.querySelectorAll('.inspector-tabs button').forEach(button => {
        const labels = { agent: 'Agent', context: '上下文', decision: '审查' };
        button.textContent = labels[button.dataset.inspector] || button.textContent;
        button.classList.toggle('active', button.dataset.inspector === state.inspector);
      });
      // The continuous chapter renderer does not expose the old `.scene-head`.
      // Mount mobile controls on the actual chapter header so they survive the
      // single-page manuscript layout and remain available on narrow screens.
      const sceneHead = document.querySelector('.scene-head');
      const chapterHead = document.querySelector('.chapter-continuous-head');
      const mobileHead = sceneHead || chapterHead;
      if (mobileHead && !document.querySelector('.writing-mobile-tabs')) {
        if (sceneHead) sceneHead.insertAdjacentHTML('beforeend', '<button type="button" class="mobile-scene-trigger" data-mobile-scene-drawer>场景</button>');
        else mobileHead.insertAdjacentHTML('beforeend', '<button type="button" class="mobile-scene-trigger" data-mobile-scene-drawer>场景</button>');
        const tabAnchor = !sceneHead && chapterHead?.nextElementSibling?.classList.contains('chapter-authoring-save')
          ? chapterHead.nextElementSibling : mobileHead;
        tabAnchor.insertAdjacentHTML('afterend', `<nav class="writing-mobile-tabs" role="tablist" aria-orientation="horizontal" aria-label="场景工作区">
          <button id="writingMobileTab-manuscript" type="button" role="tab" aria-controls="writingMobilePane" aria-selected="${state.writingMobileView === 'manuscript' ? 'true' : 'false'}" tabindex="${state.writingMobileView === 'manuscript' ? '0' : '-1'}" data-writing-mobile-view="manuscript" class="${state.writingMobileView === 'manuscript' ? 'active' : ''}">正文</button>
          <button id="writingMobileTab-agent" type="button" role="tab" aria-controls="writingMobilePane" aria-selected="${state.writingMobileView === 'agent' ? 'true' : 'false'}" tabindex="${state.writingMobileView === 'agent' ? '0' : '-1'}" data-writing-mobile-view="agent" class="${state.writingMobileView === 'agent' ? 'active' : ''}">Agent</button>
          <button id="writingMobileTab-review" type="button" role="tab" aria-controls="writingMobilePane" aria-selected="${state.writingMobileView === 'review' ? 'true' : 'false'}" tabindex="${state.writingMobileView === 'review' ? '0' : '-1'}" data-writing-mobile-view="review" class="${state.writingMobileView === 'review' ? 'active' : ''}">审查</button>
        </nav>`);
      }
      if (sceneHead) {
        const scene = selectedScene();
        const volume = currentWritingVolume(writingChapter());
        const meta = sceneHead.querySelector(':scope > div > p:last-child');
        if (scene && meta) meta.textContent = `${volume?.title || '未分卷'} · ${scene.chapterTitle} · ${scene.contract?.location || '地点待定'} · ${scene.contract?.goal || '场景目标待定'}`;
      }
      app.dataset.writingMobileView = state.writingMobileView;
      const nextCommand = document.querySelector('.next-command');
      const readiness = sceneReadinessView(state.context);
      if (nextCommand && state.context) {
        const scene = selectedScene();
        const title = nextCommand.querySelector('strong');
        const detail = nextCommand.querySelector('p');
        const actions = nextCommand.querySelector('.command-actions');
        if (detail) detail.hidden = false;
        const writingReady = readiness.canRun;
        const proposal = typeof pendingProposal === 'function' ? pendingProposal() : null;
        const hasCurrentRevision = Boolean(scene?.current_revision_id);
        const hasConfirmedCard = (state.work?.artifacts || []).some(item => item.kind === 'character_card' && item.current_revision?.content?.trust_status === 'confirmed' && item.current_revision?.content?.status !== 'archived');
        const review = currentSceneReview(scene);
        const sceneComplete = Boolean(!proposal && hasCurrentRevision && review.gate?.status === 'passed');
        nextCommand.classList.toggle('is-complete', sceneComplete);
        if (proposal) {
          if (title) title.textContent = '有一份候选等待决定';
          if (detail) detail.textContent = '逐项查看候选与 Diff；正式正文仍未改变。';
        } else if (hasCurrentRevision && !review.gate) {
          if (title) title.textContent = '正文已采纳，先检查本场';
          if (detail) detail.textContent = '新的正式 Revision 已建立；完成场景审查后，才进入下一场或发布检查。';
        } else if (hasCurrentRevision && review.gate?.status === 'blocked') {
          if (review.blockers.length) {
            if (title) title.textContent = `本场检查有 ${review.blockers.length} 个阻塞项`;
            if (detail) detail.textContent = '先查看并处理本次 Revision 的审查发现；发布 Gate 保持锁定。';
          } else {
            if (title) title.textContent = '阻塞项已处理，需重新检查';
            if (detail) detail.textContent = '处理记录已经保留；当前 Gate 仍是上一次的阻塞快照，重新检查本场后才会更新。';
          }
        } else if (hasCurrentRevision && review.gate?.status === 'passed') {
          if (title) title.textContent = '本场已检查';
          if (detail) {
            detail.textContent = review.findings.length ? `${review.findings.length} 项建议可查看` : '';
            detail.hidden = !review.findings.length;
          }
        } else {
          if (title) title.textContent = writingReady ? '本场上下文已准备' : '先补齐 Agent 起草依据，也可以自己写';
          if (detail) detail.textContent = writingReady
            ? (state.capabilities?.providers?.[0]?.is_simulation
              ? '当前为明确标注的模拟 Provider；可以验证完整审阅流程，但不会冒充真实模型输出。'
              : 'Agent 已读取本场合同、前文承接和确认资料，可以继续讨论或提出候选。')
            : readiness.needsCharacterCard && hasConfirmedCard
              ? '已有人物卡，但本场尚未选择。先将人物卡加入本场上下文。'
              : readiness.detail;
        }
        if (actions) {
          const nextUnwrittenScene = scenes().find(candidate => !candidate.current_revision_id && candidate.id !== scene?.id);
          const nextAction = writingReady
            ? '<button type="button" class="primary" data-start-scene-drafting>让 Agent 起草本场</button><button type="button" class="quiet" data-start-scene-manual>自己写</button>'
            : readiness.needsCharacterCard
              ? `<button type="button" class="primary" data-agent-complete-cards>${hasConfirmedCard ? '选择本场人物卡' : '补齐人物卡'}</button>`
              : '<button type="button" class="primary" data-inspector="agent">查看缺少的输入</button>';
          if (proposal) {
            actions.innerHTML = '<button type="button" class="primary" data-focus-scene-diff>查看候选与 Diff</button>';
          } else if (hasCurrentRevision && !review.gate) {
            actions.innerHTML = '<button type="button" class="primary" data-action="review-scene">检查本场</button><button type="button" class="quiet" data-inspector="agent">继续讨论</button>';
          } else if (hasCurrentRevision && review.gate?.status === 'blocked') {
            actions.innerHTML = review.blockers.length
              ? '<button type="button" class="primary" data-focus-scene-review>查看审查结果</button><button type="button" class="quiet" data-action="review-scene">重新检查</button>'
              : '<button type="button" class="primary" data-action="review-scene">重新检查本场</button><button type="button" class="quiet" data-focus-scene-review>查看处理记录</button>';
          } else if (hasCurrentRevision && review.gate?.status === 'passed') {
            actions.innerHTML = nextUnwrittenScene
              ? `<button type="button" class="primary" data-scene-open="${esc(nextUnwrittenScene.id)}">写下一场</button>${review.findings.length ? '<button type="button" class="quiet" data-focus-scene-review>查看建议</button>' : ''}`
              : `<button type="button" class="primary" data-stage="release">检查与发布</button>${review.findings.length ? '<button type="button" class="quiet" data-focus-scene-review>查看建议</button>' : ''}`;
          } else {
            if(writingReady&&!hasCurrentRevision){
              if(title)title.textContent='这一场还没有正文，从这里开始';
              if(detail)detail.textContent='“让 Agent 起草本场”会填好请求，确认发送后才调用模型；“自己写”会直接把光标放进正文。';
            }
            actions.innerHTML = nextAction + (!writingReady&&!hasCurrentRevision?'<button type="button" class="quiet" data-start-scene-manual>自己写</button>':'');
          }
        }
      }
      if(nextCommand){
        const emptyScene=!selectedScene()?.current_revision_id&&!pendingProposal();
        nextCommand.classList.toggle('is-writing-hint',emptyScene);
        if(emptyScene){
          const title=nextCommand.querySelector('strong'),detail=nextCommand.querySelector('p'),actions=nextCommand.querySelector('.command-actions');
          if(title)title.textContent='可以直接写正文';
          if(detail){detail.hidden=false;detail.textContent=!state.context?'可直接写作，助手资料正在准备。':readiness.canRun?'可直接写作，也可与助手讨论；候选由你确认后采用。':'可直接写作；使用助手起草前需补齐资料。';}
          if(actions)actions.replaceChildren();
        }
      }
      // The continuous chapter renderer owns the command bar. Re-attach the
      // release-required memory action after this decorator has projected the
      // current scene state, otherwise its button is overwritten above.
      if (typeof decorateSceneMemoryAction === 'function') decorateSceneMemoryAction();
      decorateSceneAgent();
      compactSceneContext();
      decorateSceneAssets();
      renderMobileSceneDrawer();
      moveInspectorToMobilePane();
      if (state.sceneId && state._lastChapterSceneScroll !== state.sceneId) {
        state._lastChapterSceneScroll = state.sceneId;
        scheduleChapterPosition(state.sceneId);
      }
    }
    if (state.stage === 'structure') renderCompactStructureWorkspace();
    decorateWritingInspector();
    const crumb = document.getElementById('crumb');
    if (crumb) {
      const scene = selectedScene();
      const volume = currentWritingVolume(writingChapter());
      const label = state.stage === 'draft' && scene
        ? `${volume?.title || '未分卷'} / ${scene.chapterTitle} / ${scene.title}`
        : `${state.stage === 'structure' ? '章节细纲' : '检查与发布'}`;
      if (typeof setCrumb === 'function') setCrumb(state.work, label);
      else crumb.textContent = `${state.work.title} / ${label}`;
    }
  }

  function decoratePanelControls() {
    const treeToggle = document.querySelector('.panel-divider-toggle-left');
    if (!treeToggle) return;

    // This control sits on the splitter, not in the toolbar.  It must remain
    // an icon: replacing its contents with a label was causing “隐藏章节” to
    // wrap into a conspicuous vertical word stack on the divider.
    const works = Boolean(state.work && state.surface === 'works' && state.stage === 'overview');
    const railName = works ? '对话栏' : state.work ? '章节与场景栏' : '作品栏';
    const collapsed = treeToggle.getAttribute('aria-pressed') === 'true';
    const label = `${collapsed ? '展开' : '收起'}${railName}`;
    treeToggle.hidden = false;
    treeToggle.setAttribute('aria-label', label);
    treeToggle.title = label;

    if (treeToggle.classList.contains('panel-divider-toggle')) {
      const glyph = treeToggle.querySelector('[aria-hidden="true"]');
      if (glyph) glyph.textContent = collapsed ? '›' : '‹';
    } else {
      treeToggle.textContent = label;
    }
  }


  registerRenderHook('writing-workbench', route => {
    if(route.section !== 'writing') return;
    decorateWritingWorkspace();
    decoratePanelControls();
    const pendingSceneId = state._pendingChapterSceneScroll;
    if(pendingSceneId){
      state._pendingChapterSceneScroll = '';
      scheduleChapterPosition(pendingSceneId);
    }
    // A queued context render can replace the first DOM before its layout
    // frame. Carry the intent to the fresh paragraph instead of losing it.
    const pendingReview=state._pendingSceneReviewFocus;
    if(pendingReview){
      if(pendingReview.sceneId===state.sceneId&&pendingProposal()?.id===pendingReview.proposalId)focusSceneDiff(pendingReview.changeId,true);
      else state._pendingSceneReviewFocus=null;
    }
  });
  window.HaloCueWritingWorkbench=Object.freeze({focusScene:focusChapterScene,focusDiff:focusSceneDiff,openScene,refreshChrome:()=>{
    const restoreComposerFocus=document.activeElement?.id==='sceneAgentMessage';
    if(state.stage==='draft'&&state.inspector==='agent')renderSceneAgentInspector();
    const pane=document.getElementById('writingMobilePane'),source=document.getElementById('inspectorContent');
    if(window.matchMedia('(max-width:760px)').matches&&state.stage==='draft'&&pane&&source) pane.replaceChildren(...source.childNodes);
    decorateWritingWorkspace();
    if(restoreComposerFocus)document.querySelector('#writingMobilePane #sceneAgentMessage')?.focus({preventScroll:true});
  }});

  registerAppClick(event => {
    const blockedControl = event.target.closest('[data-writing-gate]');
    if (blockedControl) {
      event.preventDefault();
      claimAppEvent(event);
      focusWritingReadiness(blockedControl.dataset.writingGate || '当前步骤的前置条件尚未满足。', blockedControl.dataset.stage || 'structure');
      return;
    }
    if(event.target.closest('[data-agent-complete-cards]')){
      event.preventDefault();claimAppEvent(event);
      if(libraryCards().some(card=>card.trust_status==='confirmed'&&card.status!=='archived')){
        state.sceneContextEditorOpen=true;
        render();
        document.querySelector('.scene-context-panel')?.scrollIntoView({block:'start'});
        return;
      }
      state.libraryView='characters';
      navigateToStage('references');
      return;
    }
    if(event.target.closest('[data-show-scene-agent]')){
      event.preventDefault();claimAppEvent(event);
      const wasAgent=state.inspector==='agent';
      state.inspector='agent';
      if(window.matchMedia('(max-width:760px)').matches){
        document.querySelector('[data-writing-mobile-view="agent"]')?.click();
      }else{
        window.HaloCuePanels?.open('inspector');
        if(!wasAgent||!document.querySelector('#sceneConversationForm'))renderSceneAgentInspector();
      }
      const suggestion=event.target.closest('[data-show-scene-agent]').dataset.sceneEntryPrompt;
      const focusInput=()=>{
        const input=document.querySelector('#sceneConversationForm textarea[name="text"]');
        if(!input||input.disabled)return;
        // Opening the assistant must never replace an unfinished instruction.
        if(suggestion&&!input.value.trim()){
          input.value=suggestion;
          input.dispatchEvent(new Event('input',{bubbles:true}));
        }
        input.focus({preventScroll:true});
      };
      // Run after the mobile tab's own focus restoration.
      if(window.matchMedia('(max-width:760px)').matches)window.requestAnimationFrame(focusInput);
      else focusInput();
      return;
    }
    const startDraft=event.target.closest('[data-start-scene-drafting]');
    if(startDraft){
      event.preventDefault();claimAppEvent(event);
      const scene=selectedScene();if(!scene||pendingProposal())return;
      state.inspector='agent';
      if(window.matchMedia('(max-width:760px)').matches){
        document.querySelector('[data-writing-mobile-view="agent"]')?.click();
      }else{window.HaloCuePanels?.open('inspector');renderSceneAgentInspector();}
      const input=document.querySelector('#sceneConversationForm textarea[name="text"]');
      if(input&&!input.disabled){
        if(!input.value.trim())input.value=`请根据已确认的故事方向、人物资料和本场目标，为《${scene.title}》起草正文候选。保留停止边界，先交给我审查，不要直接写入正式正文。`;
        input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
      }else toast('本场对话正在准备，请稍后再试。',true);
      return;
    }
    if(event.target.closest('[data-start-scene-manual]')){
      event.preventDefault();claimAppEvent(event);
      let chapterEditor=document.querySelector('.chapter-authoring');
      if(chapterEditor){
        const editButton=chapterEditor.querySelector('[data-chapter-view="edit"]');
        if(editButton?.getAttribute('aria-pressed')!=='true')editButton?.click();
        chapterEditor=document.querySelector('.chapter-authoring');
        const sceneId=selectedScene()?.id||state.sceneId;
        const sceneSelector=sceneId?`[data-chapter-scene="${CSS.escape(sceneId)}"]`:'.chapter-authoring-scene.is-current';
        let sceneEditor=chapterEditor?.querySelector(sceneSelector)||chapterEditor?.querySelector('.chapter-authoring-scene.is-current');
        if(!sceneEditor){toast('当前场景的正文编辑区尚未打开。',true);return}
        let field=sceneEditor.querySelector('[data-chapter-text]');
        if(!field){
          sceneEditor.querySelector('[data-chapter-add],[data-chapter-start]')?.click();
          chapterEditor=document.querySelector('.chapter-authoring');
          sceneEditor=chapterEditor?.querySelector(sceneSelector)||chapterEditor?.querySelector('.chapter-authoring-scene.is-current');
          field=sceneEditor?.querySelector('[data-chapter-text]');
        }
        if(field){field.focus();field.setSelectionRange(field.value.length,field.value.length)}
        else toast('本场还没有可编辑的正文段落。',true);
        return;
      }
      const form=document.querySelector('#sceneManuscriptForm');
      if(!form)return;
      form.querySelector('[data-manuscript-insert-empty]')?.click();
      const field=form.querySelector('textarea[name="text"]');
      field?.closest('[data-manuscript-block]')?.classList.add('is-editing');
      field?.focus();return;
    }
    const focusDiff = event.target.closest('[data-focus-scene-diff],[data-return-scene-change]');
    if (focusDiff) {
      event.preventDefault();
      claimAppEvent(event);
      focusSceneDiff(focusDiff.dataset.returnSceneChange || '');
      return;
    }
    const focusReview = event.target.closest('[data-focus-scene-review]');
    if (focusReview) {
      event.preventDefault();
      claimAppEvent(event);
      focusSceneReview();
      return;
    }
    const returnButton = event.target.closest('[data-writing-return-to-work]');
    if (returnButton) {
      event.preventDefault();
      claimAppEvent(event);
      void returnToWorkDecision(returnButton.dataset.writingReturnToWork || '');
      return;
    }
    if (event.target.closest('[data-action="new-work"]')) {
      event.preventDefault();
      claimAppEvent(event);
      openWorkDialog(event.target.closest('[data-action="new-work"]'));
      return;
    }
    if (event.target.closest('[data-mobile-scene-drawer]')) {
      event.preventDefault();
      claimAppEvent(event);
      const dialog = document.getElementById('mobileSceneDrawer');
      if (dialog && !dialog.open) dialog.showModal();
      return;
    }
    const workSwitch = event.target.closest('[data-select-work]');
    // An empty workspace has no work-switch control. Do not let the optional
    // chain turn `undefined === undefined` into a match that consumes every
    // click, including onboarding and first-use actions.
    if (workSwitch && workSwitch.dataset.selectWork === state.work?.id) {
      event.preventDefault();
      claimAppEvent(event);
      document.getElementById('workSwitchDialog')?.close();
      return;
    }
  },0);

  // Capture mobile view intent before the browser focuses a sticky tab and
  // scrolls its ancestor. The workspace listener intentionally runs later
  // for ordinary reading gestures.
  document.addEventListener('pointerdown', event => {
    const viewButton = event.target.closest?.('.writing-mobile-tabs button[data-writing-mobile-view]');
    if (!viewButton) return;
    state._pendingMobileViewSwitch = true;
    if (viewButton.dataset.writingMobileView === 'manuscript') return;
    const workspace = document.getElementById('workspace');
    if (!workspace) return;
    mobileScrollTop = workspace.scrollTop;
    workspace.dataset.manuscriptScrollTop = String(workspace.scrollTop);
    mobileScrollSceneId = document.querySelector('[data-chapter-scene-anchor].is-current')?.dataset.chapterSceneAnchor || state.sceneId || '';
  }, true);

  document.addEventListener('mousedown', event => {
    const viewButton = event.target.closest?.('.writing-mobile-tabs button[data-writing-mobile-view]');
    if (!viewButton) return;
    // Clicking a sticky tab should not invoke the browser's implicit focus
    // scroll. Keyboard activation remains available through normal focus.
    event.preventDefault();
  }, true);

  // Keep the mobile workspace tabs usable without a pointer. Arrow keys wrap
  // between views; Home/End jump to the first/last view and activate it.
  document.addEventListener('keydown', event => {
    const viewButton = event.target.closest?.('.writing-mobile-tabs button[data-writing-mobile-view]');
    if (!viewButton) return;
    const tabs = [...document.querySelectorAll('.writing-mobile-tabs button[data-writing-mobile-view]')];
    if (!tabs.length) return;
    let nextIndex = tabs.indexOf(viewButton);
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (nextIndex + 1) % tabs.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (nextIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabs.length - 1;
    else return;
    event.preventDefault();
    const nextTab = tabs[nextIndex];
    nextTab.focus({ preventScroll: true });
    if (nextTab !== viewButton) nextTab.click();
  }, true);

  registerAppClick(event => {
    const assetSuggestion = event.target.closest('[data-scene-asset-suggestion-kind]');
    if (assetSuggestion) {
      event.preventDefault();
      claimAppEvent(event);
      void openSceneAssetPicker(
        assetSuggestion.dataset.sceneAssetSuggestionScene,
        assetSuggestion.dataset.sceneAssetSuggestionKind,
        assetSuggestion.dataset.sceneAssetSuggestionQuery,
      );
      return;
    }
    const assetPickerOpen = event.target.closest('[data-scene-asset-picker]');
    if (assetPickerOpen) {
      event.preventDefault();
      claimAppEvent(event);
      void openSceneAssetPicker(assetPickerOpen.dataset.sceneAssetPicker);
      return;
    }
    const assetPickerClose = event.target.closest('[data-scene-asset-picker-close]');
    if (assetPickerClose) {
      event.preventDefault();
      claimAppEvent(event);
      state.sceneAssetPicker = null;
      assetPickerClose.closest('dialog')?.close();
      return;
    }
    const assetPickerRetry = event.target.closest('[data-scene-asset-picker-retry]');
    if (assetPickerRetry) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      if (!picker) return;
      picker.error = '';
      picker.errorCode = '';
      void loadSceneAssetPickerItems();
      return;
    }
    const assetKind = event.target.closest('[data-scene-asset-kind]');
    if (assetKind) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      if (!picker || picker.kind === assetKind.dataset.sceneAssetKind) return;
      picker.kind = assetKind.dataset.sceneAssetKind;
      const allowedSources = sceneAssetSourceOptions(picker.kind).map(([scope]) => scope);
      if (!allowedSources.includes(picker.scope)) picker.scope = allowedSources[0];
      picker.query = '';
      void loadSceneAssetPickerItems();
      return;
    }
    const assetSource = event.target.closest('[data-scene-asset-source]');
    if (assetSource) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      if (!picker || picker.scope === assetSource.dataset.sceneAssetSource) return;
      picker.scope = assetSource.dataset.sceneAssetSource;
      picker.query = '';
      void loadSceneAssetPickerItems();
      return;
    }
    const quickQuery = event.target.closest('[data-scene-asset-quick-query]');
    if (quickQuery) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      if (!picker) return;
      picker.query = quickQuery.dataset.sceneAssetQuickQuery || '';
      void loadSceneAssetPickerItems();
      return;
    }
    const assetAdd = event.target.closest('[data-scene-asset-add]');
    if (assetAdd) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      const item = picker?.items?.[Number(assetAdd.dataset.sceneAssetAdd)];
      if (!picker || !item) return;
      void (async () => {
        try {
          const reference = await sceneAssetReferenceFromItem(item, picker.kind);
        if (!reference.source_asset_id) {
          picker.error = '该素材缺少稳定资源标识，不能作为场景引用。';
          renderSceneAssetPicker();
          return;
        }
        const same = candidate => candidate.asset_kind === reference.asset_kind
          && candidate.source_type === reference.source_type
          && candidate.source_asset_id === reference.source_asset_id;
        picker.references = picker.references.filter(candidate => {
          if (candidate.asset_kind !== reference.asset_kind) return true;
          return reference.asset_kind === 'character' && !same(candidate);
        });
        if (!picker.references.some(same)) picker.references.push(reference);
          picker.error = '';
          renderSceneAssetPicker();
        } catch (error) {
          picker.error = error.message || '素材类型不匹配，未加入本场引用。';
          renderSceneAssetPicker();
        }
      })();
      return;
    }
    const assetRemove = event.target.closest('[data-scene-asset-remove]');
    if (assetRemove) {
      event.preventDefault();
      claimAppEvent(event);
      const picker = sceneAssetPicker();
      const identity = assetRemove.dataset.sceneAssetRemove;
      if (!picker || !identity) return;
      picker.references = picker.references.filter(reference => `${reference.asset_kind}:${reference.source_type}:${reference.source_asset_id}` !== identity);
      renderSceneAssetPicker();
      return;
    }
    const assetSave = event.target.closest('[data-scene-asset-save]');
    if (assetSave) {
      event.preventDefault();
      claimAppEvent(event);
      void saveSceneAssetReferences();
      return;
    }
    const close = event.target.closest('[data-close-work-dialog]');
    if (close) {
      event.preventDefault();
      claimAppEvent(event);
      closeWorkDialog();
      return;
    }
    const sceneButton = event.target.closest('[data-scene], [data-scene-open]');
    if (sceneButton) {
      event.preventDefault();
      claimAppEvent(event);
      const sceneId = sceneButton.dataset.scene || sceneButton.dataset.sceneOpen;
      if (state.surface === 'writing' && state.stage === 'draft'
        && sceneButton.closest('#sceneTree, #mobileSceneDrawer')) {
        focusChapterScene(sceneId);
      } else {
        void openScene(sceneId, sceneButton);
      }
      return;
    }
    const chapterToggle=event.target.closest('[data-toggle-writing-chapter]');
    if(chapterToggle){
      event.preventDefault();claimAppEvent(event);
      const row=chapterToggle.closest('.writing-chapter'),open=!row.classList.contains('open');
      chapterTreeExpansion.set(`${state.work.id}:${chapterToggle.dataset.toggleWritingChapter}`,open);
      row.classList.toggle('open',open);chapterToggle.setAttribute('aria-expanded',String(open));
      const title=row.querySelector('.chapter-copy b')?.textContent||'';
      chapterToggle.setAttribute('aria-label',`${open?'收起':'展开'}${title}的场景`);
      return;
    }
    const chapter = event.target.closest('[data-writing-chapter]');
    if(chapter){handleAppRouteClick(event);return;}
    const mobileView = event.target.closest('.writing-mobile-tabs button[data-writing-mobile-view]');
    if (mobileView) {
      event.preventDefault();
      claimAppEvent(event);
      // A focused sticky tab may cause the browser to move the manuscript
      // before/after the click. Freeze scene inference for the whole view
      // transition so that movement cannot overwrite the last reading scene.
      state._mobileViewSwitching = true;
      state._ignoreChapterScrollUntil = Date.now() + 1200;
      chapterScrollIntentAt = 0;
      const viewTicket=++mobileViewTicket,viewWorkId=state.work?.id,viewChapterId=state.writingChapterId;
      const currentViewTask=()=>viewTicket===mobileViewTicket&&state.work?.id===viewWorkId&&state.writingChapterId===viewChapterId&&state.surface==='writing'&&state.stage==='draft';
      const readingWorkspace = document.getElementById('workspace');
      const currentView = state.writingMobileView;
      const activeReadingAnchor = document.querySelector('[data-chapter-scene-anchor].is-current');
      const preservedScrollTop = currentView === 'manuscript'
        ? (readingWorkspace?.scrollTop || 0)
        : Number(readingWorkspace?.dataset.manuscriptScrollTop || mobileScrollTop || 0);
      if (currentView === 'manuscript') {
        mobileScrollTop = preservedScrollTop;
        mobileScrollSceneId = activeReadingAnchor?.dataset.chapterSceneAnchor || state.sceneId || '';
        if (readingWorkspace) readingWorkspace.dataset.manuscriptScrollTop = String(preservedScrollTop);
      }
      state.writingMobileView = mobileView.dataset.writingMobileView;
      if (state.writingMobileView === 'manuscript') state._writingMobileRestoreUntil = Date.now() + 550;
      state.inspector = state.writingMobileView === 'review' ? 'decision' : 'agent';
      const mobilePane = document.getElementById('writingMobilePane');
      const inspectorSource = document.getElementById('inspectorContent');
      if (mobilePane && inspectorSource && (state.writingMobileView === 'review' || currentView === 'review')) {
        while (mobilePane.firstChild) inspectorSource.append(mobilePane.firstChild);
        mobilePane.remove();
      }
      const app = document.getElementById('app');
      if (app) app.dataset.writingMobileView = state.writingMobileView;
      document.querySelectorAll('.writing-mobile-tabs button[data-writing-mobile-view]').forEach(button => {
        const active = button.dataset.writingMobileView === state.writingMobileView;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
      });
      // Review changes the Inspector contents, but neither review nor Agent
      // should rebuild the continuous manuscript or reset its scroll owner.
      if (state.writingMobileView === 'review' || currentView === 'review') {
        if (typeof renderInspector === 'function') renderInspector();
      }
      moveInspectorToMobilePane();
      // The capture-phase mousedown guard prevents sticky-tab scroll jumps,
      // so restore keyboard focus after the target pane has been mounted.
      window.requestAnimationFrame(() => {if(currentViewTask())mobileView.focus({ preventScroll: true });});
      const nextWorkspace = document.getElementById('workspace');
      if (nextWorkspace && state.writingMobileView === 'manuscript') {
        if (mobileScrollSceneId) {
          const restoreScene = scenes().find(scene => scene.id === mobileScrollSceneId);
          if (restoreScene) {
            state.sceneId = restoreScene.id;
            syncSceneChrome(restoreScene);
          }
        }
        [0, 50, 150, 300, 650].forEach(delay => window.setTimeout(() => {
          const workspace = document.getElementById('workspace');
          if (workspace && currentViewTask() && chapterScrollIntentAt===0 && state.writingMobileView === 'manuscript') {
            // Sticky view tabs can receive focus after the click handler and
            // move the scroll owner. Re-focus without browser scrolling, then
            // restore once more after that focus task has settled.
            mobileView.focus({ preventScroll: true });
            workspace.scrollTo({ top: preservedScrollTop, behavior: 'auto' });
          }
        }, delay));
        window.setTimeout(() => { if(currentViewTask())state._writingMobileRestoreUntil = 0; }, 760);
      }
      window.setTimeout(() => {
        if(viewTicket!==mobileViewTicket)return;
        state._mobileViewSwitching = false;
        state._pendingMobileViewSwitch = false;
        state._ignoreChapterScrollUntil = 0;
      }, 1200);
      return;
    }
    const sceneDrawer = event.target.closest('[data-mobile-scene-drawer]');
    if (sceneDrawer) {
      event.preventDefault();
      claimAppEvent(event);
      document.getElementById('mobileSceneDrawer')?.showModal();
      return;
    }
    const closeScenes = event.target.closest('[data-close-mobile-scenes]');
    if (closeScenes) {
      event.preventDefault();
      claimAppEvent(event);
      document.getElementById('mobileSceneDrawer')?.close();
      return;
    }
    if (event.target.closest('#mobileSceneDrawer [data-scene], #mobileSceneDrawer [data-stage]')) {
      document.getElementById('mobileSceneDrawer')?.close();
    }
  },10);

  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-scene-asset-search]');
    if (!form) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const picker = sceneAssetPicker();
    if (!picker) return;
    picker.query = String(new FormData(form).get('query') || '').trim();
    void loadSceneAssetPickerItems();
  }, true);

  document.addEventListener('error', event => {
    if (event.target.matches?.('[data-scene-asset-preview]')) event.target.hidden = true;
  }, true);

  let previousWritingNarrow = window.matchMedia('(max-width: 760px)').matches;
  window.addEventListener('resize', () => {
    const narrow = window.matchMedia('(max-width: 760px)').matches;
    if (narrow === previousWritingNarrow) return;
    previousWritingNarrow = narrow;
    window.requestAnimationFrame(() => {
      if (state.surface === 'writing' && state.stage === 'draft') moveInspectorToMobilePane();
    });
  });

  // Initial routes and browser history are owned by HaloCueRouter.
  // Compatibility contract marker:
  // initialRequestedRoute.get('section') === 'production'
  // await applyRouteFromLocation(initialRequestedRoute);
})();
