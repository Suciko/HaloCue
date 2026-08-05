(function () {
  'use strict';

  const $ = function (selector) { return document.querySelector(selector); };
  const $$ = function (selector) { return Array.from(document.querySelectorAll(selector)); };
  const state = {analysis: null, mapping: {}, preflight: null, preflightApproved: false, background: null, backgroundJob: null, buildActive: false, fileToken: null, sourcePath: null, browseMode: 'script', browseDirectory: '', profiles: [], workflowStage: 'script', review: {token: null, revision: 1, buildId: null, cards: [], selected: null}, reviewAssets: null, bgReplaceCard: null, operationId: 0, operations: {annotate: null, compile: null, build: null, analyze: null, preflight: null}, transitionId: 0, viewEpoch: 0, loadFailure: null};
  let activeFilePicker = null;
  let settingsPickerMode = '';
  let aaIndexPollTimer = null;
  let aaStatusSnapshot = {};
  const reviewActions = ['rvEdit', 'rvInsertLine', 'rvInsertDir', 'rvMoveUp', 'rvMoveDown', 'rvDelete', 'rvBind'];
  const MODEL_PRESETS = [
    {label: 'OpenAI', provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-4o', vision: true},
    {label: 'Anthropic', provider: 'anthropic', base_url: 'https://api.anthropic.com', model: 'claude-sonnet-4-5', vision: true},
    {label: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', vision: false},
    {label: 'Ollama', provider: 'openai', base_url: 'http://localhost:11434/v1', model: 'llama3.2-vision', vision: false},
    {label: '硅基流动', provider: 'openai', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-VL-72B-Instruct', vision: true},
    {label: 'OpenRouter', provider: 'openai', base_url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet-4-5', vision: true}
  ];

  function show(id, visible) { $(id).classList.toggle('on', Boolean(visible)); }
  const modalTriggers = {};
  function openModal(id, trigger) { modalTriggers[id] = trigger || document.activeElement; show(id, true); const dialog = $(id); dialog.setAttribute('aria-hidden', 'false'); const focusTarget = dialog.querySelector && dialog.querySelector('button, input, textarea, select, [tabindex]'); (focusTarget || dialog).focus(); }
  function closeModal(id) { const dialog = $(id); if (!dialog.classList.contains('on')) return; show(id, false); dialog.setAttribute('aria-hidden', 'true'); const trigger = modalTriggers[id]; if (trigger && trigger.focus) trigger.focus(); delete modalTriggers[id]; }
  function visible(id, value) { $(id).classList.toggle('is-visible', Boolean(value)); }
  function currentStory() { return window.StoryStore.get(); }
  function requireStory() { const story = currentStory(); if (!story) throw new Error('请先打开剧情'); return story; }
  function request(path, options) { return window.Api.request(path, options); }
  function post(path, payload) { return request(path, window.Api.json('POST', payload)); }
  function status(value) { $('#rvStatus').textContent = value; }
  function setWorkflowStage(name) {
    const names = ['script', 'preflight', 'prepare', 'review'];
    const currentIndex = Math.max(0, names.indexOf(name));
    state.workflowStage = names[currentIndex];
    $$('.workflow-stage').forEach(function (node) {
      const index = names.indexOf(node.dataset.stage);
      const current = index === currentIndex;
      node.classList.toggle('current', current);
      node.classList.toggle('complete', index >= 0 && index < currentIndex);
      node.setAttribute('aria-current', current ? 'step' : 'false');
      const label = node.querySelector && node.querySelector('small');
      if (label) label.textContent = current ? '当前' : (index < currentIndex ? '完成' : '等待');
    });
  }
  function showReviewPhase(value) {
    const phase = $('#reviewPhase');
    if (!phase) return;
    phase.classList.toggle('is-hidden', !value);
    phase.setAttribute('aria-hidden', String(!value));
  }
  const scriptScanPhases = ['workspace', 'format', 'rules', 'ai'];
  function setScriptScanProgress(phase, message, failed) {
    const root = $('#scriptScanProgress');
    if (!root) return;
    const index = Math.max(0, scriptScanPhases.indexOf(phase));
    root.classList.remove('is-hidden'); root.classList.toggle('is-failed', Boolean(failed));
    const title = $('#scriptScanTitle'); if (title) title.textContent = message || '正在读取剧本';
    const count = $('#scriptScanCount'); if (count) count.textContent = (failed ? index : index + 1) + ' / ' + scriptScanPhases.length;
    const bar = $('#scriptScanBar'); if (bar) bar.value = failed ? index : index + 1;
    const list = $('#scriptScanSteps');
    Array.prototype.forEach.call(list && list.children || [], function (node, stepIndex) {
      node.classList.toggle('done', !failed && stepIndex < index);
      node.classList.toggle('active', stepIndex === index);
    });
  }
  function resetScriptScanProgress() {
    const root = $('#scriptScanProgress'); if (!root) return;
    root.classList.add('is-hidden'); root.classList.remove('is-failed');
    const bar = $('#scriptScanBar'); if (bar) bar.value = 0;
  }
  function playerInstance() { return window.storyPlayer && typeof window.storyPlayer.loadCards === 'function' ? window.storyPlayer : null; }
  function ensurePlayer() {
    const existing = playerInstance();
    if (existing || !window.Player) return existing;
    window.storyPlayer = new window.Player($('#storyPlayer'));
    return playerInstance();
  }
  function contextStatus(values) { if (window.StoryContextStatus) window.StoryContextStatus.update(values); }
  function resetContextStatus() { if (window.StoryContextStatus) window.StoryContextStatus.reset(); }
  function log(value) { visible('#log', true); $('#log').textContent = value; }
  function captureView(story) { story = story || currentStory(); return {epoch: state.viewEpoch, storyToken: story && story.story_token}; }
  function isCurrentView(view) { const story = currentStory(); return Boolean(view && state.viewEpoch === view.epoch && story && story.story_token === view.storyToken); }
  function beginOperation(kind, reviewToken) { const story = currentStory(); const op = {id: ++state.operationId, storyToken: story && story.story_token, reviewToken: reviewToken || null, review: kind === 'compile' ? state.review : null, viewEpoch: state.viewEpoch}; state.operations[kind] = op; return op; }
  function isCurrentOperation(kind, op) { const story = currentStory(); return state.operations[kind] === op && state.viewEpoch === op.viewEpoch && story && story.story_token === op.storyToken && (!op.reviewToken || state.review.token === op.reviewToken) && (!op.review || state.review === op.review); }
  function invalidateOperations() { state.operations.compile = null; state.operations.build = null; }
  function beginTransition() { return ++state.transitionId; }
  function isCurrentTransition(id) { return state.transitionId === id; }
  function storyComponent(name) {
    const component = window[name];
    return component && typeof component.clear === 'function' ? component : {clear: function () {}, load: async function () {}, loadLatest: async function () {}};
  }
  async function replaceStory(next, options) {
    options = options || {};
    const transition = options.transition || beginTransition();
    if (!isCurrentTransition(transition)) return false;
    (window.StoryJobs || {detachView: function () {}}).detachView();
    storyComponent('StoryAssets').clear();
    storyComponent('ReviewWorkspace').clear();
    storyComponent('Preview').clear();
    clearStoryRuntime();
    state.fileToken = options.fileToken || null;
    state.sourcePath = options.sourcePath || null;
    state.loadFailure = null; $('#storyLoadRetry').hidden = true;
    window.StoryStore.set(next);
    $('#welcomePanel').hidden = true;
    $('#path').value = state.sourcePath || next.source_name || '';
    $('#proj').value = next.project;
    try {
      await Promise.all([
        storyComponent('StoryAssets').load(next.story_token),
        storyComponent('ReviewWorkspace').loadLatest(next),
      ]);
      if (isCurrentTransition(transition) && currentStory() && currentStory().story_token === next.story_token) { $('#s1info').textContent = ''; $('#storyLoadRetry').hidden = true; }
    } catch (error) {
      if (isCurrentTransition(transition) && currentStory() && currentStory().story_token === next.story_token) {
        state.loadFailure = {story: next, options: {fileToken: state.fileToken, sourcePath: state.sourcePath}};
        $('#s1info').textContent = '当前剧情已打开，但部分内容无法加载。可重试加载：' + error.message;
        $('#storyLoadRetry').hidden = false;
      }
    }
    return isCurrentTransition(transition) && currentStory() && currentStory().story_token === next.story_token;
  }

  function resetReview(message) {
    state.review = {token: null, revision: 1, buildId: null, cards: [], selected: null}; state.reviewAssets = null; state.bgReplaceCard = null;
    clearElement($('#rvDraftSelect'));
    const option = document.createElement('option'); option.value = ''; option.textContent = '没有草稿'; $('#rvDraftSelect').appendChild(option);
    clearElement($('#rvCards')); $('#rvOpen').disabled = true; $('#rvApproveAll').disabled = true; $('#rvValidate').disabled = true; $('#rvCompile').disabled = true; $('#rvInstall').disabled = true; setReviewActions(false, false); showReviewPhase(false);
    const player = playerInstance(); if (player) { player.pause(); player.loadCards([]); }
    status(message || '尚未打开草稿');
    resetContextStatus();
  }

  function clearStoryRuntime() {
    state.viewEpoch += 1;
    state.analysis = null; state.mapping = {}; state.preflight = null; state.preflightApproved = false; state.background = null; state.backgroundJob = null; state.buildActive = false; state.fileToken = null; state.sourcePath = null; state.reviewAssets = null; state.bgReplaceCard = null;
    clearElement($('#cast')); clearElement($('#bggrid')); clearElement($('#storyPlayer')); clearElement($('#preflightCast')); clearElement($('#preflightAssets')); clearElement($('#preflightIssues')); clearElement($('#preflightSummary')); $('#bgTimeline').textContent = ''; $('#bgsel').textContent = '未选择时使用 BG_Black'; $('#s2sum').textContent = ''; $('#preflightStatus').textContent = '等待分析'; $('#preflightHint').textContent = ''; $('#s1info').textContent = ''; $('#log').textContent = ''; resetScriptScanProgress(); visible('#log', false); ['#s2preflight', '#s2', '#s3', '#s4'].forEach(function (id) { $(id).classList.add('off'); }); $('#preflightApprove').disabled = true;
    $('#backgroundRequestsPanel').classList.remove('open'); clearElement($('#backgroundRequestList')); $('#continueBackgroundBuild').disabled = true; $('#backgroundContinueHint').textContent = ''; $('#goAnnotate').disabled = false; $('#rvCompile').disabled = true; $('#rvInstall').disabled = true;
    resetReview('尚未打开草稿'); setWorkflowStage('script'); checkReady();
  }

  function setDrawer(name, open) {
    const drawer = $('#' + name + 'Drawer');
    const backdrop = $('#' + name + 'Backdrop');
    drawer.classList.toggle('open', open); backdrop.classList.toggle('open', open);
    drawer.setAttribute('aria-hidden', String(!open));
    const locked = ['settings', 'help'].some(function (drawerName) {
      const candidate = $('#' + drawerName + 'Drawer');
      return candidate && candidate.classList.contains('open');
    });
    if (document.documentElement) document.documentElement.classList.toggle('drawer-open', locked);
    if (document.body) document.body.classList.toggle('drawer-open', locked);
    if (name === 'settings' && !open) stopAAIndexPolling();
  }
  function readiness(id, ok, detail) {
    const card = $(id); card.dataset.state = ok ? 'ready' : 'attention';
    card.querySelector('.readiness-state').textContent = ok ? '可用' : '需要处理';
    card.querySelector('.readiness-detail').textContent = detail;
  }
  async function loadSetupStatus() {
    try {
      const result = await request('/api/setup/status');
      readiness('#readyAA', result.aa.connected, result.aa.connected ? result.aa.path : '请检查 AA 工作区');
      readiness('#readyDatabase', result.database.ready, result.database.ready ? '素材索引已准备好' : '缺少素材数据库');
      readiness('#readyModel', result.model.configured, result.model.configured ? result.model.name + ' · ' + result.model.model : '仅转换格式时无需 AI');
    } catch (_) { ['#readyAA', '#readyDatabase', '#readyModel'].forEach(function (id) { readiness(id, false, '暂时无法读取状态'); }); }
  }
  async function loadState() {
    try {
      const result = await request('/api/state');
      const stats = result.stats || {}; const chars = stats['角色'] || [0]; const backgrounds = stats['背景(可直接用)'] || [0];
      $('#stat').textContent = chars[0] >= 0 && backgrounds[0] >= 0 ? '运行环境已就绪' : '运行环境需要检查';
    } catch (_) { $('#stat').textContent = '运行环境状态暂不可用'; }
  }

  function sourceName(path) { return path.split(/[\\/]/).pop().replace(/\.[^.]+$/, ''); }
  async function openPath(path, project, openingTransition) {
    const transition = openingTransition || beginTransition(); const picker = await post('/api/picker', {path: path}); if (!isCurrentTransition(transition)) return null;
    const story = await post('/api/stories/open', {file_token: picker.file_token, project: project || sourceName(path)}); if (!await replaceStory(story, {transition: transition, fileToken: picker.file_token, sourcePath: path})) return null;
    await recentStories.refresh();
    return story;
  }
  async function openScript(trigger) {
    state.browseMode = 'script'; $('#browseTitle').textContent = '选择剧情文本';
    if (storyFilePicker) { activeFilePicker = storyFilePicker; storyFilePicker.open(trigger); return; }
    openModal('#mBrowse', trigger); await browse($('#path').value.trim());
  }
  async function openSelectedStory(selection) {
    const transition = beginTransition(); const name = selection && selection.name || '';
    if (!selection || !selection.file_token || !name) return null;
    $('#path').value = name; setScriptScanProgress('workspace', '正在建立当前章节工作区…');
    try {
      const story = await post('/api/stories/open', {file_token: selection.file_token, project: sourceName(name)});
      if (!isCurrentTransition(transition)) return null;
      if (!await replaceStory(story, {transition: transition, fileToken: selection.file_token, sourcePath: name})) return null;
      await recentStories.refresh(); await analyze(); return story;
    } catch (error) { if (isCurrentTransition(transition)) { $('#s1info').textContent = error.message; setScriptScanProgress('workspace', '无法打开剧情：' + error.message, true); } return null; }
  }
  async function openRecent(story) {
    const transition = beginTransition();
    try {
      const context = await request('/api/story/current?story_token=' + encodeURIComponent(story.story_token));
      await replaceStory(context, {transition: transition, fileToken: context.file_token || null, sourcePath: context.source_name || ''});
    } catch (error) { if (isCurrentTransition(transition)) $('#s1info').textContent = '无法恢复剧情：' + error.message; }
  }

  function clearElement(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function backgroundCard(item) {
    const card = document.createElement('button'); card.type = 'button'; card.className = 'bgc';
    card.dataset.name = item.name; card.classList.toggle('sel', state.background === item.name);
    const label = document.createElement('span'); label.className = 'cap'; label.textContent = item.label || item.name;
    card.appendChild(label); card.addEventListener('click', function () { selectBackground(item.name); }); return card;
  }
  async function loadBackgrounds() {
    const view = captureView();
    const query = encodeURIComponent($('#bgq').value); const ready = $('#bgready').checked ? '1' : '0';
    try { const items = await request('/api/backgrounds?q=' + query + '&ready=' + ready); if (!isCurrentView(view)) return; const root = $('#bggrid'); clearElement(root); items.forEach(function (item) { root.appendChild(backgroundCard(item)); }); }
    catch (_) { if (isCurrentView(view)) $('#bggrid').textContent = '背景列表加载失败'; }
  }
  function selectBackground(name) {
    if (state.backgroundJob && state.backgroundJob.resolveRequestId) { resolveBackground(state.backgroundJob.resolveRequestId, name); return; }
    state.background = name; $('#bgsel').textContent = '开场背景：' + name; $$('.bgc').forEach(function (node) { node.classList.toggle('sel', node.dataset.name === name); }); checkReady();
  }
  function fallbackPreflight() {
    const speakers = state.analysis && state.analysis.speakers || [];
    const characters = speakers.map(function (speaker) {
      const mapping = state.mapping[speaker.who] || {};
      return {speaker: speaker.who, kind: mapping.kind || 'unset', id: mapping.id || '', name: mapping.name || '', custom: Boolean(mapping.custom), confidence: mapping.kind ? 0.65 : 0, reason: '规则分析结果，可手动修改。'};
    });
    const nonstandard = state.analysis && state.analysis.format && state.analysis.format.confidence === 'low';
    const issue = nonstandard
      ? {severity: 'error', code: 'nonstandard_format_requires_ai', message: '当前剧本是非标准格式，但 AI 全文初审没有完成。', action: '请配置可用模型后重新初审，或按帮助中的“角色名：台词”格式整理剧本。'}
      : {severity: 'warning', code: 'preflight_unavailable', message: 'AI 初审暂时不可用，已保留规则分析结果。', action: '检查模型配置后重试，或确认规则结果继续。'};
    return {ok: true, ai_status: 'failed', characters: characters, assets: [], available_assets: {characters: [], backgrounds: [], sounds: [], bgms: []}, issues: [issue]};
  }
  function applyPreflightMapping(result) {
    (result.characters || []).forEach(function (item) {
      if (!item || !item.speaker) return;
      const kind = item.kind || 'unset';
      state.mapping[item.speaker] = kind === 'unset' ? {kind: 'unset'} : {kind: kind, id: item.id || '', name: item.name || item.speaker, custom: Boolean(item.custom)};
    });
  }
  function preflightKindLabel(kind) { return kind === 'background' ? '背景' : kind === 'sound' ? '音效' : kind === 'character' ? '骨骼' : kind === 'bgm' ? 'BGM' : kind; }
  function buildPreflightAssetTasks(preflight) {
    return (preflight && Array.isArray(preflight.assets) ? preflight.assets : []).filter(function (item) {
      return item && item.status === 'missing' && ['background', 'sound', 'character'].includes(item.kind);
    }).map(function (item) {
      const location = String(item.location || '位置未标注');
      const name = String(item.name || '未命名素材');
      return {
        task_id: [item.kind, name, location].join(':'),
        kind: item.kind,
        requested_name: name,
        source_location: {label: location},
        reason: '剧本引用但当前剧情未登记',
        candidate_keys: []
      };
    });
  }
  function openPreflightAssetWorkbench(kind, trigger) {
    const story = currentStory();
    if (!story || !window.openAssetWorkbench) return;
    const tasks = buildPreflightAssetTasks(state.preflight).filter(function (task) { return task.kind === kind; });
    state.preflightWorkbenchReturn = {
      x: Number(window.scrollX || 0), y: Number(window.scrollY || 0), trigger: trigger || null
    };
    window.openAssetWorkbench({
      origin: 'preflight', story_token: story.story_token, asset_kind: kind, tasks: tasks
    });
  }
  function renderPreflight(result) {
    state.preflight = result || null;
    const root = $('#s2preflight');
    if (!root || !result) return;
    if (result.analysis && Array.isArray(result.analysis.speakers) && state.analysis) {
      state.analysis = Object.assign({}, state.analysis, result.analysis, {path: state.analysis.path});
      renderCast();
    }
    root.classList.remove('off');
    if (!state.preflightApproved) setWorkflowStage('preflight');
    const statusEl = $('#preflightStatus');
    const statusLabel = result.ai_status === 'completed' ? 'AI 已完成' : result.ai_status === 'failed' ? '规则结果（AI 未完成）' : '规则初审';
    statusEl.textContent = statusLabel;
    const issues = Array.isArray(result.issues) ? result.issues.filter(function (item) {
      if (!item) return false;
      if (item.code === 'speaker_unmapped') { const speaker = item.speaker || ((String(item.message || '').match(/“([^”]+)”/) || [])[1] || ''); const mapping = state.mapping[speaker]; return !mapping || !mapping.kind || mapping.kind === 'unset'; }
      return true;
    }) : [];
    result.issues = issues;
    const errors = issues.filter(function (item) { return item && item.severity === 'error'; });
    const summary = $('#preflightSummary'); clearElement(summary);
    const summaryText = document.createElement('p'); summaryText.className = errors.length ? 'preflight-summary-error' : 'preflight-summary-ok'; summaryText.textContent = errors.length ? ('发现 ' + errors.length + ' 项需要先处理；处理后可再次确认。') : '未发现阻塞问题，可以检查并确认角色映射。'; summary.appendChild(summaryText);
    const format = result.analysis && result.analysis.format;
    if (format && format.label) { const formatText = document.createElement('p'); formatText.className = 'preflight-format dim'; formatText.textContent = '剧本格式：' + format.label + ' · ' + (format.message || '已完成结构识别。'); summary.appendChild(formatText); }
    const castRoot = $('#preflightCast'); clearElement(castRoot);
    (result.characters || []).forEach(function (item) {
      const row = document.createElement('div'); row.className = 'preflight-row';
      const main = document.createElement('div'); main.className = 'preflight-row-main';
      const name = document.createElement('b'); name.textContent = item.speaker || '未命名说话者'; main.appendChild(name);
      const map = document.createElement('span'); map.className = 'dim'; map.textContent = item.kind === 'narrator' ? '旁白' : item.kind === 'unset' ? '未指定' : ((item.name || item.id || '未命名角色') + (item.custom ? ' · 本章自定义骨骼' : item.kind === 'portrait' ? ' · AA 骨骼角色' : ' · 语音角色')); main.appendChild(map);
      const reason = document.createElement('small'); reason.textContent = item.reason || ''; main.appendChild(reason);
      row.appendChild(main);
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'ghost'; edit.textContent = '修改'; edit.addEventListener('click', function () { openCastPicker(item.speaker); }); row.appendChild(edit); castRoot.appendChild(row);
    });
    if (!(result.characters || []).length) castRoot.appendChild(document.createElement('p')).textContent = '没有识别到说话者。';
    const assetRoot = $('#preflightAssets'); clearElement(assetRoot);
    (result.assets || []).forEach(function (item) {
      const row = document.createElement('div'); row.className = 'preflight-row preflight-asset-row ' + (item.status === 'missing' ? 'is-missing' : 'is-ready');
      const assetStatus = item.status === 'missing' ? '待补' : item.status === 'builtin' ? 'AA 内置可用' : '本章已登记';
      const text = document.createElement('span'); text.textContent = preflightKindLabel(item.kind) + ' · ' + (item.name || '未命名') + ' · ' + (item.location || '') + ' · ' + assetStatus + (item.detected_by === 'ai' ? ' · AI 全文识别' : ''); row.appendChild(text);
      if (item.status === 'missing' && item.kind === 'bgm') {
        const unavailable = document.createElement('small'); unavailable.className = 'preflight-asset-unavailable'; unavailable.textContent = '当前版本尚未开放自定义 BGM 登记'; row.appendChild(unavailable);
      }
      if (item.status === 'missing' && ['background', 'sound', 'character'].includes(item.kind) && window.openAssetWorkbench) {
        const workbench = document.createElement('button'); workbench.type = 'button'; workbench.className = 'ghost'; workbench.dataset.preflightAction = 'open-workbench'; workbench.textContent = '去补素材'; workbench.addEventListener('click', function () { openPreflightAssetWorkbench(item.kind, workbench); }); row.appendChild(workbench);
      }
      if (item.status === 'missing' && item.kind !== 'bgm' && window.StoryAssets && window.StoryAssets.importLocal) {
        const local = document.createElement('button'); local.type = 'button'; local.className = 'ghost'; local.textContent = '从本地导入'; local.addEventListener('click', async function () { await window.StoryAssets.importLocal(item.kind, {name: item.name}); await rerunPreflight(); }); row.appendChild(local);
      }
      if (item.status === 'missing' && item.kind !== 'bgm' && window.HistoryDrawer && window.HistoryDrawer.open) {
        const history = document.createElement('button'); history.type = 'button'; history.className = 'ghost'; history.textContent = '从历史导入'; history.addEventListener('click', function () { window.HistoryDrawer.open({kind: item.kind === 'background' ? 'background' : item.kind === 'sound' ? 'sound' : 'background', trigger: history, onApplied: function () { return rerunPreflight(); }}); }); row.appendChild(history);
      }
      assetRoot.appendChild(row);
    });
    if (!(result.assets || []).length) assetRoot.appendChild(document.createElement('p')).textContent = '没有发现 @bg / @sound / @bgm 引用。';
    const issueRoot = $('#preflightIssues'); clearElement(issueRoot);
    issues.forEach(function (item) { const row = document.createElement('div'); row.className = 'preflight-issue ' + (item.severity === 'error' ? 'is-error' : 'is-warning'); const message = document.createElement('b'); message.textContent = (item.severity === 'error' ? '需要处理：' : '提示：') + (item.message || '未命名问题'); const action = document.createElement('span'); action.textContent = item.action || ''; row.append(message, action); issueRoot.appendChild(row); });
    if (!issues.length) issueRoot.appendChild(document.createElement('p')).textContent = '暂无问题。';
    $('#preflightHint').textContent = errors.length ? '请处理上方错误；素材导入或角色修改后可重新初审。' : '确认后才会进入演员、默认场景和生成设置。';
    $('#preflightApprove').disabled = Boolean(errors.length);
    if (state.preflightApproved) revealFormalSteps();
  }
  function revealFormalSteps() { ['#s2', '#s3', '#s4'].forEach(function (id) { $(id).classList.remove('off'); }); setWorkflowStage('prepare'); renderCast(); checkReady(); }
  function approvePreflight() {
    if (!state.preflight) return;
    const errors = (state.preflight.issues || []).filter(function (item) { return item && item.severity === 'error'; });
    const unmapped = (state.analysis && state.analysis.speakers || []).some(function (speaker) { const mapping = state.mapping[speaker.who]; return !mapping || !mapping.kind || mapping.kind === 'unset'; });
    if (errors.length || unmapped) { $('#preflightHint').textContent = errors.length ? '还有错误未处理，请先补齐素材或修改映射。' : '还有说话者未指定角色，请先点击“修改”。'; return; }
    state.preflightApproved = true; revealFormalSteps(); const nextStep = $('#s2'); if (nextStep.scrollIntoView) nextStep.scrollIntoView({behavior: 'smooth'}); $('#preflightHint').textContent = '初审已确认，可以继续。';
  }
  async function runPreflight(op, storyToken) {
    const story = currentStory();
    if (!story || !state.fileToken) return null;
    try {
      const response = await post('/api/preflight', {story_token: story.story_token, file_token: state.fileToken, model_profile_id: $('#modelProfileSelect').value});
      if (response && response.job_id) {
        const job = await window.Api.poll('/api/jobs/' + response.job_id, function (item) { return ['succeeded', 'failed', 'cancelled'].includes(item.state); }, {isCurrent: function () { return isCurrentOperation('analyze', op) && currentStory() && currentStory().story_token === storyToken; }, onRetry: function () { if (isCurrentOperation('analyze', op)) { $('#preflightStatus').textContent = '连接中断，正在重试'; setScriptScanProgress('ai', 'AI 初审连接中断，正在重试…'); } }});
        if (!job || job.state !== 'succeeded') throw new Error('初审任务未完成');
        const result = job.result || {};
        applyPreflightMapping(result); renderPreflight(result); return result;
      }
      if (response && Array.isArray(response.characters)) { applyPreflightMapping(response); renderPreflight(response); return response; }
      // 兼容尚未实现初审端点的旧后端；新版后端始终返回 job_id。
      state.preflightApproved = true;
      return null;
    } catch (_) {
      const result = fallbackPreflight(); renderPreflight(result); return result;
    }
  }
  async function rerunPreflight() {
    const story = currentStory();
    if (!story || !state.analysis) return null;
    const op = beginOperation('analyze');
    state.preflightApproved = false;
    ['#s2', '#s3', '#s4'].forEach(function (id) { $(id).classList.add('off'); });
    setWorkflowStage('preflight');
    $('#preflightRerun').disabled = true;
    $('#preflightStatus').textContent = '正在重新初审…'; setScriptScanProgress('ai', 'AI 正在重新通读全文并核对素材…');
    checkReady();
    try {
      const result = await runPreflight(op, story.story_token);
      if (result) { renderPreflight(result); setScriptScanProgress('ai', 'AI 初审已完成，请检查下方结果。'); }
      return result;
    } finally {
      if (isCurrentOperation('analyze', op)) $('#preflightRerun').disabled = false;
    }
  }
  function setWorkbenchRefreshFailure(context, error) {
    $('#preflightStatus').textContent = '初审刷新未完成';
    $('#preflightHint').textContent = '素材已保留；请重试初审，或返回工作台继续处理。' + (error && error.message ? ' ' + error.message : '');
    $('#preflightRerun').textContent = '重试初审';
    const back = $('#preflightReturnWorkbench');
    if (back) { back.hidden = false; back.onclick = function () { if (window.openAssetWorkbench) window.openAssetWorkbench(context); }; }
  }
  async function refreshAfterAssetWorkbench(context) {
    const story = currentStory();
    const safeContext = context && typeof context === 'object' ? context : {};
    if (!story || String(safeContext.story_token || '') !== String(story.story_token || '')) return false;
    const back = $('#preflightReturnWorkbench');
    if (back) back.hidden = true;
    $('#preflightRerun').textContent = '重新检查';
    const refreshKey = [story.story_token, safeContext.origin || '', safeContext.card_id || ''].join(':');
    if (state.workbenchRefresh && state.workbenchRefresh.key === refreshKey) return state.workbenchRefresh.promise;
    const refresh = (async function () {
    try {
      $('#preflightStatus').textContent = '正在读取当前剧情素材';
      if (window.StoryAssets && window.StoryAssets.load) await window.StoryAssets.load(story.story_token);
      if (safeContext.origin !== 'preflight') return true;
      $('#preflightStatus').textContent = 'AI 正在重新核对全文';
      const result = await rerunPreflight();
      if (!result) throw new Error('当前剧情尚未建立初审上下文');
      if (!currentStory() || currentStory().story_token !== story.story_token) return false;
      $('#preflightStatus').textContent = '初审结果已刷新';
      if (state.preflightWorkbenchReturn && window.scrollTo) {
        window.scrollTo(state.preflightWorkbenchReturn.x, state.preflightWorkbenchReturn.y);
      }
      return true;
    } catch (error) {
      if (currentStory() && currentStory().story_token === story.story_token) setWorkbenchRefreshFailure(safeContext, error);
      return false;
    }
    })();
    state.workbenchRefresh = {key: refreshKey, promise: refresh};
    try { return await refresh; }
    finally { if (state.workbenchRefresh && state.workbenchRefresh.promise === refresh) state.workbenchRefresh = null; }
  }
  async function analyze() {
    const path = $('#path').value.trim(); let op; if (!path) return; const transition = beginTransition(); setScriptScanProgress('workspace', '正在建立当前章节工作区…');
    try {
      if (!currentStory() || state.sourcePath !== path || !state.fileToken) await openPath(path, null, transition);
      if (!isCurrentTransition(transition) || state.sourcePath !== path) return; op = beginOperation('analyze'); const storyToken = currentStory() && currentStory().story_token; setScriptScanProgress('format', '正在识别写作格式与章节结构…');
      const sourceQuery = state.fileToken ? ('token=' + encodeURIComponent(state.fileToken)) : ('path=' + encodeURIComponent(path));
      const result = await request('/api/analyze?' + sourceQuery); if (!isCurrentOperation('analyze', op) || state.sourcePath !== path || !currentStory() || currentStory().story_token !== storyToken) return;
      if (result.error) throw new Error(result.error);
      state.analysis = result; state.preflightApproved = false; setScriptScanProgress('rules', '正在提取角色、AA 指令和素材线索…'); $('#s1info').textContent = (result.format && result.format.label ? ('识别为' + result.format.label + '。') : '') + '共 ' + result.lines + ' 行台词，' + result.speakers.length + ' 位说话者。正在进行 AI 初审…';
      $('#s2preflight').classList.remove('off'); ['#s2', '#s3', '#s4'].forEach(function (id) { $(id).classList.add('off'); });
      setWorkflowStage('preflight');
      if ($('#s2preflight').scrollIntoView) $('#s2preflight').scrollIntoView({behavior: 'smooth', block: 'start'});
      state.mapping = await request('/api/guess?' + sourceQuery); if (!isCurrentOperation('analyze', op) || !currentStory() || currentStory().story_token !== storyToken) return; renderCast(); await loadBackgrounds(); setScriptScanProgress('ai', 'AI 正在通读全文，核对角色、骨骼和素材…'); const preflight = await runPreflight(op, storyToken); if (!isCurrentOperation('analyze', op)) return; if (!preflight) { state.preflightApproved = true; revealFormalSteps(); } setScriptScanProgress('ai', 'AI 初审已完成，请检查下方结果。'); $('#s1info').textContent = '共 ' + result.lines + ' 行台词，' + result.speakers.length + ' 位说话者。初审结果可在上方编辑。'; checkReady();
    } catch (error) { if (isCurrentTransition(transition) && (!op || isCurrentOperation('analyze', op))) { setScriptScanProgress('ai', '读取或初审失败：' + error.message, true); $('#s1info').textContent = error.message; } }
  }
  function renderCast() {
    const root = $('#cast'); clearElement(root); const head = root.insertRow(); ['剧本里的名字', '台词数', '对应角色', '操作'].forEach(function (label) { const cell = document.createElement('th'); cell.textContent = label; head.appendChild(cell); });
    let unset = 0;
    state.analysis.speakers.forEach(function (speaker) {
      const mapping = state.mapping[speaker.who] || {};
      const row = root.insertRow();
      [speaker.who, String(speaker.n), mapping.name || (mapping.kind === 'narrator' ? '旁白' : '未指定')].forEach(function (value) { const cell = row.insertCell(); cell.textContent = value; });
      if (!mapping.kind || mapping.kind === 'unset') unset += 1;
      const op = row.insertCell();
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'ghost cast-edit'; edit.textContent = '修改'; edit.setAttribute('aria-label', '修改 ' + speaker.who + ' 的对应角色');
      edit.addEventListener('click', function () { openCastPicker(speaker.who); });
      op.appendChild(edit);
    });
    $('#s2sum').textContent = unset ? (unset + ' 个待处理') : '全部已匹配';
  }

  let castPickerSpeaker = '';
  let castSearchTimer = null;
  function openCastPicker(who) {
    castPickerSpeaker = who;
    const speakerLabel = $('#castPickerSpeaker'); if (speakerLabel) speakerLabel.textContent = '说话者：' + who;
    const search = $('#castSearch'); if (search) search.value = '';
    searchCharacters('');
    openModal('#mCast', document.activeElement);
  }
  async function searchCharacters(q) {
    const root = $('#castResults'); if (!root) return;
    clearElement(root);
    let items = [];
    try { items = await request('/api/characters?q=' + encodeURIComponent(q)); } catch (_) { const fail = document.createElement('p'); fail.className = 'dim'; fail.textContent = '角色搜索失败，请重试。'; root.appendChild(fail); return; }
    if (!Array.isArray(items) || !items.length) { const empty = document.createElement('p'); empty.className = 'dim'; empty.textContent = '没有匹配的角色，可换关键词试试。'; root.appendChild(empty); return; }
    items.forEach(function (item) {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'cast-result';
      const name = document.createElement('b'); name.textContent = item.name || item.ident;
      const meta = document.createElement('span'); meta.textContent = [item.club, item.ident, item.faces ? item.faces + ' 表情' : ''].filter(Boolean).join(' · ');
      row.append(name, meta);
      row.addEventListener('click', function () { pickCharacter(item); });
      root.appendChild(row);
    });
  }
  function pickCharacter(item) {
    const who = castPickerSpeaker;
    if (!who) return;
    state.mapping[who] = {kind: 'portrait', id: item.ident, name: item.name || item.ident, spine: item.spine || ''};
    renderCast();
    if (state.preflight) {
      const target = (state.preflight.characters || []).find(function (row) { return row.speaker === who; });
      if (target) { target.kind = 'portrait'; target.id = item.ident; target.name = item.name || item.ident; target.custom = Boolean(item.source === 'custom'); target.reason = '用户已手动修改映射。'; }
      renderPreflight(state.preflight);
    }
    closeModal('#mCast');
  }
  function castSetKind(kind) {
    const who = castPickerSpeaker;
    if (!who) return;
    if (kind === 'narrator') state.mapping[who] = {kind: 'narrator'};
    else delete state.mapping[who];
    renderCast();
    if (state.preflight) {
      const target = (state.preflight.characters || []).find(function (row) { return row.speaker === who; });
      if (target) { target.kind = kind === 'narrator' ? 'narrator' : 'unset'; target.id = ''; target.name = kind === 'narrator' ? '旁白' : ''; target.custom = false; target.reason = '用户已手动修改映射。'; }
      renderPreflight(state.preflight);
    }
    closeModal('#mCast');
  }
  function checkReady() {
    const paused = Boolean(state.buildActive || state.backgroundJob);
    const ready = Boolean(state.analysis && state.preflightApproved && currentStory() && !paused);
    $('#go').disabled = !ready;
    $('#hint').textContent = paused ? '当前生成任务尚未结束' : (ready ? (state.background ? '可以生成' : '未选背景时使用 BG_Black') : '请先选择并读取剧本');
  }

  async function browse(directory) {
    const query = new URLSearchParams({kind: state.browseMode}); if (directory) query.set('dir', directory);
    const result = await request('/api/browse?' + query.toString()); state.browseDirectory = result.dir; $('#bdir').textContent = result.dir;
    $('#chooseCurrentDir').classList.toggle('is-hidden', !result.can_choose_directory);
    const root = $('#blist'); clearElement(root); const list = document.createElement('ul');
    const add = function (label, handler) { const item = document.createElement('li'); const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = label; button.addEventListener('click', handler); item.appendChild(button); list.appendChild(item); };
    if (result.parent) add('[上一级]', function () { browse(result.parent); });
    (result.dirs || []).forEach(function (name) { add('DIR ' + name, function () { browse(result.dir + '\\' + name); }); });
    (result.files || []).forEach(function (file) { add(file.name, function () { chooseBrowseFile(result.dir + '\\' + file.name); }); });
    root.appendChild(list);
  }
  async function chooseBrowseFile(path) {
    if (state.browseMode !== 'script') return;
    $('#path').value = path; closeModal('#mBrowse'); await analyze();
  }
  function chooseCurrentDirectory() { if (state.browseMode === 'character' && state.browseDirectory) $('#path').value = state.browseDirectory; closeModal('#mBrowse'); }

  function modelPayload() { return window.ModelSettings.profilePayload(document); }
  function renderProfile(profile) {
    profile = profile || {};
    $('#modelProfileId').value = profile.id || '';
    $('#modelProfileName').value = profile.name || '';
    $('#modelProvider').value = profile.provider || 'openai';
    $('#modelBaseUrl').value = profile.base_url || '';
    $('#modelName').value = profile.model || '';
    $('#modelMaxTokens').value = profile.max_tokens || 16000;
    $('#modelVision').checked = profile.vision !== false;
    const keyInput = $('#modelApiKey'), saved = profile.secret_status === 'saved';
    keyInput.value = '';
    keyInput.placeholder = saved ? '已安全保存；留空则保持不变' : '输入 API Key';
    const badge = $('#modelSecretStatus');
    badge.textContent = saved ? '密钥已安全保存' : '未配置密钥';
    badge.dataset.status = saved ? 'saved' : 'missing';
    $('#modelSecretHint').textContent = saved ? '留空不会覆盖现有密钥' : '输入后将由 Windows 安全保存';
    $('#modelClearKey').disabled = !saved;
    $('#modelStatus').textContent = profile.id ? '配置已载入，可以验证连接。' : '填写连接信息并保存配置。';
  }
  async function loadProfiles(selected) {
    const result = await request('/api/llm/profiles'); state.profiles = result.profiles || [];
    const select = $('#modelProfileSelect'); clearElement(select);
    state.profiles.forEach(function (profile) { const option = document.createElement('option'); option.value = profile.id; option.textContent = profile.name + ' · ' + profile.model; select.appendChild(option); });
    const id = selected || result.active_profile_id || (state.profiles[0] || {}).id || '';
    select.value = id;
    const profile = state.profiles.find(function (item) { return item.id === id; });
    renderProfile(profile);
    return profile;
  }
  async function saveProfile() {
    $('#modelStatus').textContent = '正在安全保存配置…';
    try {
      const result = await post('/api/llm/profiles/save', modelPayload());
      const profile = await loadProfiles(result.id);
      $('#modelStatus').textContent = profile && profile.secret_status === 'saved'
        ? '配置和密钥已保存，可以开始验证连接。'
        : '配置已保存；使用接口前还需要填写 API Key。';
    } catch (error) { $('#modelStatus').textContent = error.message; }
  }
  async function clearProfileKey() {
    const payload = modelPayload();
    if (!payload.id) return;
    payload.api_key = '';
    payload.clear_secret = true;
    $('#modelStatus').textContent = '正在清除密钥…';
    try {
      const result = await post('/api/llm/profiles/save', payload);
      await loadProfiles(result.id);
      $('#modelStatus').textContent = '密钥已清除。';
    } catch (error) { $('#modelStatus').textContent = error.message; }
  }
  function applyModelPreset(preset) {
    $('#modelProvider').value = preset.provider;
    $('#modelBaseUrl').value = preset.base_url;
    $('#modelName').value = preset.model;
    $('#modelVision').checked = Boolean(preset.vision);
    $('#modelStatus').textContent = '已填入 ' + preset.label + ' 预设，填写密钥后点「测试」确认。';
  }
  function setAAStatusValue(id, text, stateName) {
    const node = $(id);
    if (!node) return;
    node.textContent = text;
    node.dataset.state = stateName || '';
  }
  function renderAAStatus(aa) {
    aaStatusSnapshot = Object.assign({}, aaStatusSnapshot, aa || {});
    aa = aaStatusSnapshot;
    const program = aa.program || {};
    const projects = aa.projects || {};
    const saves = aa.saves || {};
    const resource = aa.resource || {};
    const preview = aa.preview_index || {status: 'not_built'};
    setAAStatusValue('#aaProgramState', program.status === 'recognized' ? '已识别' + (program.path ? ' · ' + program.path : '') : program.status === 'invalid' ? '所选程序无法识别' : '尚未选择 AA 程序', program.status === 'recognized' ? 'ready' : 'attention');
    setAAStatusValue('#aaProjectsState', projects.status === 'ready' ? (projects.path || '项目目录已就绪') : '尚未找到 projects 目录', projects.status === 'ready' ? 'ready' : 'attention');
    setAAStatusValue('#aaSavesState', saves.status === 'ready' ? (saves.path || '存档目录已就绪') : '可选存档目录未找到', saves.status === 'ready' ? 'ready' : 'attention');
    const resourceText = resource.status === 'installed' ? '资源包已安装' + (resource.path ? ' · ' + resource.path : '') : resource.status === 'invalid' ? 'AA 资源目录无效' : '尚未安装 AA 资源包';
    setAAStatusValue('#aaResourceState', resourceText, resource.status === 'installed' ? 'ready' : resource.status === 'invalid' ? 'failed' : 'attention');
    const counts = Number(preview.backgrounds || 0) + Number(preview.avatars || 0);
    const previewText = preview.status === 'building'
      ? '正在建立图片预览' + (preview.total ? '（' + Number(preview.current || 0) + ' / ' + Number(preview.total) + '）' : '')
      : preview.status === 'ready' ? '图片预览已就绪' + (counts ? '（' + counts + ' 项）' : '')
      : preview.status === 'partial' ? '图片预览可用，已跳过 ' + Number(preview.failed || 0) + ' 个损坏资源'
      : preview.status === 'stale' ? '资源包已更新，需要重新建立图片预览'
      : preview.status === 'failed' ? '建立失败，请检查 AA 资源包后重试'
      : '尚未建立图片预览';
    setAAStatusValue('#aaPreviewState', previewText, ['ready', 'partial'].includes(preview.status) ? 'ready' : preview.status === 'failed' ? 'failed' : 'attention');
    const progress = $('#aaIndexProgress');
    const building = preview.status === 'building';
    if (progress) {
      progress.value = Number(preview.current || 0);
      progress.max = Math.max(1, Number(preview.total || 1));
      progress.textContent = progress.value + ' / ' + progress.max;
      progress.classList.toggle('is-active', building);
    }
    const indexButton = $('#buildAAIndex');
    if (indexButton) {
      indexButton.disabled = resource.status !== 'installed' || building;
      indexButton.textContent = ['ready', 'partial', 'stale', 'failed'].includes(preview.status) ? '重新建立图片预览' : '建立图片预览';
    }
  }
  function settingsDrawerOpen() {
    const drawer = $('#settingsDrawer');
    return Boolean(drawer && drawer.classList.contains('open'));
  }
  function stopAAIndexPolling() {
    if (aaIndexPollTimer !== null) clearTimeout(aaIndexPollTimer);
    aaIndexPollTimer = null;
  }
  function scheduleAAIndexPoll() {
    stopAAIndexPolling();
    if (!settingsDrawerOpen()) return;
    aaIndexPollTimer = setTimeout(function () {
      aaIndexPollTimer = null;
      return pollAAIndex();
    }, 1000);
  }
  async function pollAAIndex() {
    if (!settingsDrawerOpen()) {
      stopAAIndexPolling();
      return null;
    }
    try {
      const result = await request('/api/resources/index');
      const preview = result && result.preview_index;
      if (preview) renderAAStatus({preview_index: preview});
      if (preview && preview.status === 'building') scheduleAAIndexPoll();
      else stopAAIndexPolling();
      return result;
    } catch (error) {
      if ($('#aaInstallStatus')) $('#aaInstallStatus').textContent = error.message || '暂时无法读取图片预览状态。';
      stopAAIndexPolling();
      return null;
    }
  }
  async function buildAAIndex() {
    const button = $('#buildAAIndex');
    if (button && button.disabled) return null;
    stopAAIndexPolling();
    try {
      const result = await post('/api/resources/index', {});
      if (result && result.preview_index) renderAAStatus({preview_index: result.preview_index});
      if (result && result.preview_index && result.preview_index.status === 'building') scheduleAAIndexPoll();
      return result;
    } catch (error) {
      if ($('#aaInstallStatus')) $('#aaInstallStatus').textContent = error.message || '图片预览建立失败。';
      return null;
    }
  }
  async function loadAAData() {
    try {
      const result = await request('/api/setup/status');
      loadToolSettings(result);
      renderAAStatus(result && result.aa);
      const aa = result && result.aa || {};
      const path = aa.program && aa.program.path || aa.path || '';
      if (path && $('#aaInstallInput')) $('#aaInstallInput').value = path;
      if ($('#aaInstallStatus')) $('#aaInstallStatus').textContent = path ? '已读取当前 AA 路径。' : '请选择 AA 程序或安装目录。';
    } catch (_) {
      if ($('#aaInstallStatus')) $('#aaInstallStatus').textContent = '暂时无法读取 AA 安装状态。';
    }
  }
  async function loadToolSettings(result) {
    const spine = result && result.spine;
    if (!spine) return;
    if (spine.path) $('#spineCliInput').value = spine.path;
    $('#spineCliInfo').textContent = spine.configured
      ? 'Spine CLI 已就绪：' + (spine.resolved_path || spine.path)
      : '骨骼表情渲染需要 Spine 3.8 的 Spine.com 命令行程序。';
  }

  function renderAAWorkspaceCandidates(candidates, requestPayload) {
    const root = $('#aaWorkspaceCandidates');
    clearElement(root);
    state.aaInstallRequest = Object.assign({}, requestPayload);
    $('#aaWorkspaceConfirm').disabled = true;
    (candidates || []).forEach(function (candidate) {
      const label = document.createElement('label');
      label.className = 'aa-workspace-candidate';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'aa-workspace';
      radio.value = String(candidate.path || '');
      radio.checked = false;
      radio.addEventListener('change', function () {
        $('#aaWorkspaceConfirm').disabled = false;
      });
      const path = document.createElement('b');
      path.textContent = radio.value;
      const source = document.createElement('span');
      source.textContent = '来源：' + String(candidate.source || 'AA 工作区');
      label.appendChild(radio);
      label.appendChild(path);
      label.appendChild(source);
      root.appendChild(label);
    });
    $('#aaWorkspaceConflict').hidden = false;
  }
  async function saveAAInstall(payload) {
    payload = payload || {aa_install: $('#aaInstallInput').value.trim()};
    payload = Object.assign({}, payload);
    if (!payload.entry_token && !payload.aa_install) {
      $('#aaInstallStatus').textContent = '请选择 AA 程序或安装目录。';
      return;
    }
    $('#aaInstallStatus').textContent = '正在识别 AA 程序与工作区…';
    try {
      const result = await post('/api/settings/aa-install', payload);
      if (result.aa) renderAAStatus(result.aa);
      if (result.aa && result.aa.program && result.aa.program.path) $('#aaInstallInput').value = result.aa.program.path;
      $('#aaWorkspaceConflict').hidden = true;
      $('#aaInstallStatus').textContent = result.restart_required
        ? '路径已保存，重启后使用新的 AA 工作区'
        : 'AA 路径已保存';
      state.aaInstallRequest = null;
      return result;
    } catch (error) {
      if (error.code === 'aa_workspace_selection_required') {
        renderAAWorkspaceCandidates(error.candidates, payload);
        $('#aaInstallStatus').textContent = '发现多个 AA 工作区，请先确认当前使用的位置。';
        return null;
      }
      $('#aaInstallStatus').textContent = error.message || '保存失败';
      return null;
    }
  }
  async function confirmAAWorkspace() {
    const selected = $('input[name="aa-workspace"]:checked');
    if (!selected || !selected.value || !state.aaInstallRequest) {
      $('#aaInstallStatus').textContent = '请先选择当前使用的 AA 工作区。';
      return null;
    }
    return saveAAInstall(Object.assign({}, state.aaInstallRequest, {
      aa_data: selected.value,
    }));
  }
  async function testProfile(mode) {
    $('#modelStatus').textContent = mode === 'vision' ? '正在验证图片识别…' : '正在验证文字连接…';
    try { const result = await post('/api/llm/test', {id: $('#modelProfileId').value, mode: mode}); $('#modelStatus').textContent = (mode === 'vision' ? '图片识别可用：' : '文字连接可用：') + result.model; } catch (error) { $('#modelStatus').textContent = error.message; }
  }

  async function saveSpineCli() {
    const path = $('#spineCliInput').value.trim();
    if (!path) { $('#spineCliInfo').textContent = '请选择 Spine.com 文件。'; return; }
    try {
      const result = await post('/api/settings/spine-cli', {spine_cli: path});
      $('#spineCliInfo').textContent = result.ok ? (result.e || 'Spine CLI 路径已保存') : (result.e || '保存失败');
    } catch (error) { $('#spineCliInfo').textContent = error.message || '保存失败'; }
  }
  async function saveSettingsEntry(selection) {
    if (!selection || !selection.entry_token) return;
    if (settingsPickerMode === 'aa') return saveAAInstall({entry_token: selection.entry_token});
    try {
      const result = await post('/api/settings/spine-cli', {entry_token: selection.entry_token});
      if (result.ok) $('#spineCliInput').value = result.path || selection.name || '';
      $('#spineCliInfo').textContent = result.e || (result.ok ? '设置已保存' : '保存失败');
    } catch (error) {
      $('#spineCliInfo').textContent = error.message || '保存失败';
    }
  }
  async function saveSettingsEntryAndReset(selection) {
    try { return await saveSettingsEntry(selection); }
    finally { activeFilePicker = storyFilePicker; }
  }

  function setReviewActions(enabled, bind) {
    reviewActions.forEach(function (id) { $('#' + id).disabled = !enabled || (id === 'rvBind' && !bind); });
    const toolbar = $('#rvCardToolbar');
    if (toolbar) toolbar.classList.toggle('is-hidden', !enabled);
    if (!enabled && $('#rvSelectionLabel')) $('#rvSelectionLabel').textContent = '选择卡片后可编辑';
  }
  async function refreshDrafts() {
    const story = currentStory();
    if (!story) { resetReview('请先打开剧情'); return; }
    const view = captureView(story);
    const storyToken = story.story_token; const list = await request('/api/drafts');
    if (!isCurrentView(view)) return;
    const select = $('#rvDraftSelect'); clearElement(select);
    const scoped = list.filter(function (draft) { return draft.story_token === storyToken; });
    if (!scoped.length) { resetReview('当前剧情没有草稿'); return; }
    scoped.forEach(function (draft) { const option = document.createElement('option'); option.value = draft.draft_token; option.textContent = (draft.project || '未命名工程') + ' · v' + draft.draft_version; select.appendChild(option); });
    select.value = story.latest_draft_token || scoped[0].draft_token;
    $('#rvOpen').disabled = false;
    showReviewPhase(true);
    setWorkflowStage('review');
    status('找到 ' + scoped.length + ' 份草稿，打开后可继续审查');
    contextStatus({draft: '草稿：v' + (scoped.find(function (draft) { return draft.draft_token === select.value; }) || scoped[0]).draft_version, save: '保存：未修改'});
  }
  async function loadReview() {
    const story = currentStory(); const token = $('#rvDraftSelect').value; if (!story || !token) { resetReview('请先打开当前剧情的草稿'); return; } const view = captureView(story); const storyToken = story.story_token; const draft = await request('/api/draft?token=' + encodeURIComponent(token));
    if (!isCurrentView(view)) return;
    if (draft.story_token !== storyToken) { resetReview('草稿不属于当前剧情'); return; }
    const selectedId = state.review && state.review.token === token && state.review.selected ? state.review.selected.card_id : null;
    const cards = draft.cards || [];
    state.review = {token: token, revision: draft.draft_version, buildId: draft.last_compiled_build_id || null, cards: cards, selected: selectedId ? cards.find(function (card) { return card.card_id === selectedId; }) || null : null}; const counts = draft.counts || {};
    showReviewPhase(true); setWorkflowStage('review'); $('#rvOpen').disabled = false;
    contextStatus({draft: '草稿：v' + draft.draft_version, save: '保存：未修改', review: '审查：待审 ' + (counts.pending || 0) + ' · 待处理 ' + (counts.blocking_errors || 0), compile: state.review.buildId ? '编译：已完成' : '编译：未编译', install: draft.last_installed_build_id ? ('安装：已安装' + (draft.last_installed_project ? ' · ' + draft.last_installed_project : '')) : '安装：未安装'});
    status('待审 ' + (counts.pending || 0) + ' · 待处理 ' + (counts.blocking_errors || 0) + ' · v' + draft.draft_version); $('#rvApproveAll').disabled = false; $('#rvValidate').disabled = false; $('#rvCompile').disabled = Boolean(counts.pending || counts.blocking_errors); $('#rvInstall').disabled = !state.review.buildId; setReviewActions(Boolean(state.review.selected), Boolean(state.review.selected && state.review.selected.kind === 'line'));
    if (state.review.selected) $('#rvSelectionLabel').textContent = '已选 #' + state.review.selected.line_no;
    renderReviewCards();
    const player = ensurePlayer(); if (player) player.loadCards(state.review.cards);
    renderReviewAssets();
    renderBackgroundTimeline({characters: [], backgrounds: [], sounds: [], bgms: []});
  }
  function renderReviewCards() {
    const all = state.review && state.review.cards ? state.review.cards : [];
    const limit = state.review.cardLimit || 80;
    const shown = all.length > limit ? all.slice(0, limit) : all;
    if (window.CardList) window.CardList.renderCardList($('#rvCards'), shown, {onSelectCard: selectCard, onFillBackground: fillBackgroundFromHistory});
    applyCardSelection();
    if (all.length > shown.length) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'ghost card-list-more'; more.textContent = '显示全部 ' + all.length + ' 条';
      more.addEventListener('click', function () { state.review.cardLimit = all.length; renderReviewCards(); });
      $('#rvCards').appendChild(more);
    }
  }
  async function renderReviewAssets() {
    const story = currentStory();
    const root = $('#reviewAssets');
    if (!root) return;
    clearElement(root);
    if (!story) return;
    const view = captureView(story);
    let data;
    try { data = await request('/api/story/assets?story_token=' + encodeURIComponent(story.story_token)); } catch (_) { return; }
    if (!isCurrentView(view) || !currentStory() || currentStory().story_token !== story.story_token) return;
    state.reviewAssets = data || {characters: [], backgrounds: [], sounds: [], bgms: []};
    renderBackgroundTimeline(state.reviewAssets);
    const title = document.createElement('h3'); title.className = 'review-assets-title'; title.textContent = '本剧情自定义素材';
    root.appendChild(title);
    const groups = [['characters', '角色'], ['backgrounds', '背景'], ['sounds', '音效'], ['bgms', 'BGM']];
    const counts = groups.map(function (pair) { const items = data ? data[pair[0]] : []; return Array.isArray(items) ? items.length : 0; });
    if (counts.every(function (n) { return n === 0; })) {
      const empty = document.createElement('p'); empty.className = 'dim'; empty.textContent = '还没有自定义素材，可在“本剧情素材”区导入。'; root.appendChild(empty);
      return;
    }
    groups.forEach(function (pair) {
      const items = Array.isArray(data[pair[0]]) ? data[pair[0]] : [];
      if (!items.length) return;
      const group = document.createElement('div'); group.className = 'review-asset-group';
      const label = document.createElement('b'); label.textContent = pair[1] + ' ' + items.length;
      group.appendChild(label);
      const list = document.createElement('div'); list.className = 'review-asset-thumbs';
      items.slice(0, 20).forEach(function (item) {
        const tile = document.createElement('div'); tile.className = 'review-asset-tile';
        if (pair[0] === 'sounds') {
          tile.classList.add('review-asset-sound');
          const key = item.aa_key || item.name || '';
          const src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=sound&key=' + encodeURIComponent(key);
          tile.setAttribute('role', 'button'); tile.tabIndex = 0; tile.title = '点击播放：' + (item.name || key);
          tile.addEventListener('click', function () {
            let audio = document.getElementById('reviewSoundPlayer');
            if (!audio) { audio = document.createElement('audio'); audio.id = 'reviewSoundPlayer'; document.body.appendChild(audio); }
            if (audio.dataset.src === src) { audio.pause(); audio.removeAttribute('src'); audio.load(); audio.dataset.src = ''; tile.classList.remove('is-playing'); return; }
            audio.src = src; audio.dataset.src = src; tile.classList.add('is-playing');
            audio.play().catch(function () { tile.classList.remove('is-playing'); });
            audio.onended = function () { tile.classList.remove('is-playing'); };
          });
        } else {
          if (pair[0] === 'backgrounds' && item.preview_available) {
            const img = document.createElement('img'); img.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=background&key=' + encodeURIComponent(item.aa_key || item.name || ''); img.alt = item.name || '背景'; img.loading = 'lazy'; tile.appendChild(img);
          } else if (pair[0] === 'characters' && item.preview_available) {
            const img = document.createElement('img'); img.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=character&key=' + encodeURIComponent(item.aa_key || item.name || ''); img.alt = item.name || '角色'; img.loading = 'lazy'; tile.appendChild(img);
          } else {
            tile.classList.add('is-text');
          }
        }
        const cap = document.createElement('span'); cap.textContent = item.name || item.aa_key || ''; tile.appendChild(cap);
        list.appendChild(tile);
      });
      group.appendChild(list);
      root.appendChild(group);
    });
  }
  function applyCardSelection() {
    const list = $('#rvCards'); const selected = state.review && state.review.selected;
    if (!list || !selected || !list.querySelectorAll) return;
    Array.prototype.forEach.call(list.querySelectorAll('.card-item'), function (el) { const active = el.dataset.cardId === selected.card_id; el.classList.toggle('selected', active); el.setAttribute('aria-selected', String(active)); });
  }
  function selectCard(card) { state.review.selected = card; setReviewActions(true, card.kind === 'line'); $('#rvSelectionLabel').textContent = '已选 #' + card.line_no + ' · ' + (card.kind === 'line' ? '台词' : card.kind === 'dir' ? '指令' : '卡片'); applyCardSelection(); applyTimelineSelection(); const player = playerInstance(); if (player && typeof player.jumpToCard === 'function') player.jumpToCard(card.card_id); }
  function customBackgroundFor(card, data) {
    const list = data && Array.isArray(data.backgrounds) ? data.backgrounds : [];
    const arg = card && card.current ? String(card.current.arg || '').trim().toLowerCase() : '';
    return list.find(function (item) {
      return String(item.name || '').trim().toLowerCase() === arg
        || String(item.aa_key || '').trim().toLowerCase() === arg;
    });
  }
  function renderBackgroundTimeline(data) {
    const root = $('#bgTimeline'); if (!root) return;
    clearElement(root);
    const cards = (state.review && state.review.cards || []).filter(function (card) { return card.kind === 'dir' && card.current && String(card.current.cmd || '').toLowerCase() === 'bg'; });
    const title = document.createElement('div'); title.className = 'bg-timeline-heading'; const heading = document.createElement('h3'); heading.textContent = '背景时间线'; const hint = document.createElement('span'); hint.className = 'dim'; hint.textContent = cards.length ? ('共 ' + cards.length + ' 次切换 · 点击节点跳转到对应卡片') : '本场没有 @bg 指令'; title.appendChild(heading); title.appendChild(hint); root.appendChild(title);
    if (!cards.length) return;
    const track = document.createElement('div'); track.className = 'bg-timeline-track'; const story = currentStory();
    cards.forEach(function (card, index) {
      const custom = customBackgroundFor(card, data || {}); const node = document.createElement('article'); node.className = 'bg-timeline-node' + (custom ? '' : ' is-missing'); node.dataset.cardId = card.card_id;
      const jump = document.createElement('button'); jump.type = 'button'; jump.className = 'bg-timeline-jump'; jump.addEventListener('click', function () { selectCard(card); let target = document.querySelector ? document.querySelector('[data-card-id="' + card.card_id.replace(/"/g, '\\"') + '"]') : null; if (!target && state.review.cards && state.review.cards.length) { state.review.cardLimit = state.review.cards.length; renderReviewCards(); target = document.querySelector ? document.querySelector('[data-card-id="' + card.card_id.replace(/"/g, '\\"') + '"]') : null; } if (target && target.scrollIntoView) target.scrollIntoView({behavior: 'smooth', block: 'center'}); });
      if (custom && custom.preview_available && story) { const img = document.createElement('img'); img.loading = 'lazy'; img.alt = custom.name || card.current.arg || '背景'; img.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=background&key=' + encodeURIComponent(custom.aa_key || custom.name || ''); jump.appendChild(img); } else { const placeholder = document.createElement('span'); placeholder.className = 'bg-timeline-placeholder'; placeholder.textContent = custom ? '无预览' : '待补'; jump.appendChild(placeholder); }
      const name = document.createElement('b'); name.textContent = card.current.arg || '未命名背景'; jump.appendChild(name); const meta = document.createElement('span'); meta.className = 'dim'; meta.textContent = custom ? '本剧情自定义' : '不在本剧情自定义素材中'; jump.appendChild(meta); node.appendChild(jump);
      const replace = document.createElement('button'); replace.type = 'button'; replace.className = 'ghost bg-timeline-replace'; replace.textContent = '更换'; replace.addEventListener('click', function (event) { event.stopPropagation(); openBgReplace(card, replace); }); node.appendChild(replace); track.appendChild(node);
      if (story && window.openAssetWorkbench) {
        const workbench = document.createElement('button'); workbench.type = 'button'; workbench.className = 'ghost bg-timeline-workbench'; workbench.textContent = '在素材工作台中查找'; workbench.dataset.bgAction = 'open-workbench'; workbench.addEventListener('click', function (event) {
          event.stopPropagation();
          window.openAssetWorkbench({origin: 'review', story_token: story.story_token, draft_token: state.review.token, card_id: card.card_id, asset_kind: 'background'});
        });
        node.appendChild(workbench);
      }
      if (index < cards.length - 1) { const arrow = document.createElement('span'); arrow.className = 'bg-timeline-arrow'; arrow.textContent = '→'; track.appendChild(arrow); }
    });
    root.appendChild(track); applyTimelineSelection();
  }
  function applyTimelineSelection() { const selected = state.review && state.review.selected; const root = $('#bgTimeline'); if (!root || !root.querySelectorAll) return; Array.prototype.forEach.call(root.querySelectorAll('.bg-timeline-node'), function (node) { node.classList.toggle('selected', Boolean(selected && node.dataset.cardId === selected.card_id)); }); }
  async function openBgReplace(card, trigger) {
    if (!card || !state.review.token) return;
    state.bgReplaceCard = card; const story = currentStory(); if (!story) return;
    openModal('#mBgReplace', trigger);
    $('#bgReplaceHint').textContent = '选择当前剧情已登记的自定义背景；也可以从历史项目复制。';
    const root = $('#bgReplaceOptions'); clearElement(root); root.textContent = '正在读取本剧情背景…';
    try { if (!state.reviewAssets) state.reviewAssets = await request('/api/story/assets?story_token=' + encodeURIComponent(story.story_token)); if (!state.bgReplaceCard || state.bgReplaceCard.card_id !== card.card_id) return; clearElement(root); const items = state.reviewAssets && state.reviewAssets.backgrounds || []; if (!items.length) { root.textContent = '当前剧情还没有自定义背景。'; return; } items.forEach(function (item) { const button = document.createElement('button'); button.type = 'button'; button.className = 'bg-replace-option'; if (item.preview_available) { const img = document.createElement('img'); img.loading = 'lazy'; img.alt = item.name || '背景'; img.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=background&key=' + encodeURIComponent(item.aa_key || item.name || ''); button.appendChild(img); } const label = document.createElement('span'); label.textContent = item.name || item.aa_key || '未命名'; button.appendChild(label); button.addEventListener('click', function () { applyBgReplace(card, item.aa_key || item.name); }); root.appendChild(button); }); } catch (error) { root.textContent = '本剧情背景读取失败：' + error.message; }
  }
  async function applyBgReplace(card, name) { try { await reviewPost('/api/cards/update', {card_id: card.card_id, patch: {cmd: 'bg', arg: String(name || '')}}); closeModal('#mBgReplace'); state.bgReplaceCard = null; await loadReview(); } catch (error) { $('#bgReplaceHint').textContent = '更换失败：' + error.message; } }
  function openBgHistory() { const card = state.bgReplaceCard; if (!card || !window.HistoryDrawer || !window.HistoryDrawer.open) return; closeModal('#mBgReplace'); window.HistoryDrawer.open({kind: 'background', trigger: document.activeElement, replaceCardId: card.card_id, draftToken: state.review.token, draftVersion: state.review.revision, onApplied: function () { state.bgReplaceCard = null; return loadReview(); }}); }
  async function fillBackgroundFromHistory(card) {
    if (!card || card.kind !== 'background_request' || !state.review.token || !card.card_id) return null;
    if (!window.HistoryDrawer || !window.HistoryDrawer.open) return null;
    return window.HistoryDrawer.open({
      kind: 'background',
      trigger: document.activeElement,
      triggerCardId: card.card_id,
      draftToken: state.review.token,
      requestId: card.card_id,
      draftVersion: state.review.revision,
      onApplied: function () { return loadReview(); }
    });
  }
  async function applyWorkbenchBackground(context, detail) {
    const story = currentStory();
    if (!story || !context || context.origin !== 'review' || context.story_token !== story.story_token || !context.draft_token || !context.card_id) return true;
    const key = String(detail && detail.aa_key || detail && detail.asset && detail.asset.aa_key || '');
    if (!key) return false;
    try {
      const latest = await request('/api/draft?token=' + encodeURIComponent(context.draft_token));
      if (!latest || latest.story_token !== story.story_token) return false;
      const card = (latest.cards || []).find(function (item) { return item.card_id === context.card_id; });
      if (!card) throw new Error('原背景卡已不存在，请重新确认草稿。');
      const result = await request('/api/cards/update', window.Api.json('POST', {
        token: context.draft_token,
        card_id: context.card_id,
        patch: {cmd: 'bg', arg: key},
        expected_draft_version: latest.draft_version
      }));
      if (!result || result.ok === false) throw new Error(result && (result.e || result.code) || '背景卡更新失败');
      if (state.review && state.review.token === context.draft_token) state.review.revision = result.draft_version || latest.draft_version;
      await loadReview();
      return true;
    } catch (error) {
      const conflict = Number(error && (error.status || error.statusCode)) === 409 || error && (error.code === 'revision_conflict' || error.code === 'draft_conflict');
      if (conflict) {
        await loadReview();
        status('素材已复制；草稿已变化，请再次确认应用');
      } else status('素材已复制，但背景卡尚未应用：' + (error.message || '请重新确认'));
      return false;
    }
  }
  async function reviewPost(path, payload, method) { const review = state.review; const view = captureView(); if (!review.token || !isCurrentView(view)) return null; const body = Object.assign({token: review.token, expected_draft_version: review.revision}, payload); const result = await request(path, window.Api.json(method || 'POST', body)); if (!isCurrentView(view) || state.review !== review) return null; if (!result.ok) throw new Error(result.e || result.code); review.revision = result.draft_version || review.revision; contextStatus({save: '保存：已保存'}); return result; }
  function setBusyButton(id, busy, busyText, idleText) { const button = $(id); button.disabled = Boolean(busy); button.textContent = busy ? busyText : idleText; button.setAttribute('aria-busy', String(Boolean(busy))); }
  async function approveAll() {
    const view = captureView();
    if (window.confirm && !window.confirm('把当前草稿的全部卡片标记为已审？')) return;
    setBusyButton('#rvApproveAll', true, '正在处理…', '全部标记已审'); status('正在标记全部卡片…');
    try { const result = await reviewPost('/api/review/approve', {}); if (!result || !isCurrentView(view)) return; await loadReview(); }
    catch (error) { if (isCurrentView(view)) status('操作失败：' + error.message); }
    finally { if (isCurrentView(view)) setBusyButton('#rvApproveAll', false, '', '全部标记已审'); }
  }
  async function validateReview() {
    const view = captureView(); setBusyButton('#rvValidate', true, '检查中…', '检查问题'); status('正在检查草稿…');
    try { const result = await reviewPost('/api/validate', {}); if (!result || !isCurrentView(view)) return; status(result.blocking_errors ? ('检查完成 · ' + result.blocking_errors + ' 项待处理') : '检查通过，可以编译'); contextStatus({review: result.blocking_errors ? ('审查：已校验 · 有 ' + result.blocking_errors + ' 项待处理') : '审查：校验通过'}); }
    catch (error) { if (isCurrentView(view)) status('检查失败：' + error.message); }
    finally { if (isCurrentView(view)) setBusyButton('#rvValidate', false, '', '检查问题'); }
  }
  async function compile() {
    const op = beginOperation('compile', state.review.token); if (!op.storyToken || !op.reviewToken) return;
    try {
      setBusyButton('#rvCompile', true, '编译中…', '编译工程'); status('正在编译工程…'); $('#rvInstall').disabled = true;
      const result = await reviewPost('/api/compile', {}); if (!result || !isCurrentOperation('compile', op)) return; const job = await window.Api.poll('/api/jobs/' + result.job_id, function (item) { return ['succeeded', 'failed', 'cancelled'].includes(item.state); }, {isCurrent: function () { return isCurrentOperation('compile', op); }, onRetry: function () { if (isCurrentOperation('compile', op)) status('连接中断，正在重试'); }}); if (!isCurrentOperation('compile', op)) return;
      if (job.state !== 'succeeded' || !result.build_id) throw new Error(job.error || (job.state === 'cancelled' ? '编译已取消' : '编译失败'));
      state.review.buildId = result.build_id; $('#rvInstall').disabled = false; status('编译成功，可安装'); contextStatus({compile: '编译：已完成'});
    } catch (error) { if (!isCurrentOperation('compile', op)) return; state.review.buildId = null; $('#rvInstall').disabled = true; status('编译失败：' + error.message); contextStatus({compile: '编译：失败'}); }
    finally { if (isCurrentOperation('compile', op)) setBusyButton('#rvCompile', false, '', '编译工程'); }
  }
  function updateInstallProjectPreview() {
    const category = $('#installCategory').value.trim();
    const storyName = $('#installStoryName').value.trim();
    const invalidCategory = category.includes('-');
    $('#installCategory').setAttribute('aria-invalid', String(invalidCategory));
    $('#installStoryName').setAttribute('aria-invalid', String(!storyName));
    $('#installProjectPreview').textContent = storyName ? (category ? category + '-' + storyName : storyName) : '请填写剧情名称';
    $('#installConfirm').disabled = invalidCategory || !storyName;
  }
  function showInstallLocation(result, stateLabel) {
    $('#installResultState').textContent = stateLabel || '安装完成';
    $('#installResultProject').textContent = result.project || '';
    $('#installAapPath').textContent = result.aap_path || '';
    $('#installProjectDir').textContent = result.project_dir || '';
    $('#installSaveDir').textContent = result.save_dir || '';
    $('#installOpenHint').textContent = '请在 AA 中选择“打开项目”，再选择上面的 .aap 文件；本工具不会改写 AA 的最近项目记录。';
    $('#installResult').hidden = false;
  }
  async function copyInstallAapPath() {
    const value = $('#installAapPath').textContent.trim();
    if (!value) return;
    try {
      if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
        await window.navigator.clipboard.writeText(value);
        $('#installDialogStatus').textContent = '已复制 AA 工程文件路径。';
        return;
      }
    } catch (_) {}
    $('#installDialogStatus').textContent = '无法自动复制，请选中上方路径后复制。';
  }
  async function openInstallDialog(trigger) {
    const review = state.review;
    const view = captureView();
    if (!review.token || !review.buildId || !isCurrentView(view)) {
      status('请先编译当前草稿');
      return;
    }
    const story = currentStory();
    $('#installCategory').value = '';
    $('#installStoryName').value = story && story.project || '';
    clearElement($('#installCategoryOptions'));
    $('#installResult').hidden = true;
    $('#installDialogStatus').textContent = '正在读取 AA 中已有的分类…';
    updateInstallProjectPreview();
    openModal('#mInstall', trigger);
    try {
      const query = new URLSearchParams({token: review.token, build_id: review.buildId});
      const result = await request('/api/install/options?' + query.toString());
      if (!isCurrentView(view) || state.review !== review) return;
      $('#installCategory').value = result.default_category || '';
      $('#installStoryName').value = result.default_story_name || (story && story.project) || '';
      (result.categories || []).forEach(function (category) {
        const option = document.createElement('option'); option.value = category; $('#installCategoryOptions').appendChild(option);
      });
      if (result.existing_install) {
        showInstallLocation(result.existing_install, '已有安装');
        $('#installDialogStatus').textContent = '已找到已有安装；可按下方路径在 AA 中打开，也可以修改名称后另行安装。';
      } else $('#installDialogStatus').textContent = '分类可以留空；AA 只会按最终名称显示这一个工程。';
      updateInstallProjectPreview();
    } catch (error) {
      if (!isCurrentView(view) || state.review !== review) return;
      $('#installDialogStatus').textContent = '无法读取安装信息：' + error.message;
      $('#installConfirm').disabled = true;
    }
  }
  async function confirmInstall() {
    const view = captureView();
    const category = $('#installCategory').value.trim();
    const storyName = $('#installStoryName').value.trim();
    updateInstallProjectPreview();
    if (!storyName || category.includes('-')) {
      $('#installDialogStatus').textContent = !storyName ? '请填写剧情名称。' : '分类只能填一级，不能包含连字符。';
      return;
    }
    setBusyButton('#installConfirm', true, '安装中…', '确认安装');
    $('#installDialogStatus').textContent = '正在安装到 AA…';
    $('#installResult').hidden = true;
    try {
      const result = await reviewPost('/api/install', {
        build_id: state.review.buildId,
        category: category,
        story_name: storyName
      });
      if (!result || !isCurrentView(view)) return;
      showInstallLocation(result);
      $('#installDialogStatus').textContent = '文件已写入；请按下方位置在 AA 中打开。';
      status('安装完成：' + result.project);
      contextStatus({install: '安装：已安装'});
    } catch (error) {
      if (isCurrentView(view)) {
        $('#installDialogStatus').textContent = '安装失败：' + error.message;
        status('安装失败：' + error.message);
        contextStatus({install: '安装：失败'});
      }
    } finally {
      if (isCurrentView(view)) setBusyButton('#installConfirm', false, '', '确认安装');
    }
  }
  function editCard(trigger) { const card = state.review.selected; if (!card) return; const current = card.current || {}; $('#editWho').value = current.who || ''; $('#editText').value = card.kind === 'line' ? current.text || '' : current.arg || ''; ['Face', 'Emo', 'Act', 'Fx'].forEach(function (key) { $('#edit' + key).value = current[key.toLowerCase()] || ''; }); $('#editTitle').textContent = '编辑卡片 #' + card.line_no; openModal('#mEdit', trigger); }
  async function saveEdit() { const card = state.review.selected; if (!card) return; const patch = card.kind === 'line' ? {who: $('#editWho').value.trim(), text: $('#editText').value, face: $('#editFace').value.trim(), emo: $('#editEmo').value.trim(), act: $('#editAct').value.trim(), fx: $('#editFx').value.trim()} : {arg: $('#editText').value.trim()}; try { await reviewPost('/api/cards/update', {card_id: card.card_id, patch: patch}); closeModal('#mEdit'); await loadReview(); } catch (error) { status(error.message); } }
  async function insertCard(kind) { const card = state.review.selected; if (!card) return; try { await reviewPost('/api/cards/insert', {after_card_id: card.card_id, kind: kind, payload: kind === 'line' ? {who: '', text: '新台词'} : {cmd: 'bg', arg: 'BG_Black'}}); await loadReview(); } catch (error) { status(error.message); } }
  async function moveCard(direction) { const review = state.review; const index = review.cards.indexOf(review.selected); if (index < 0) return; const before = direction === 'up' ? review.cards[index - 1] : review.cards[index + 2]; if ((direction === 'up' && index === 0) || (direction === 'down' && index === review.cards.length - 1)) return; try { await reviewPost('/api/cards/move', {card_id: review.selected.card_id, before_card_id: before ? before.card_id : null}); await loadReview(); } catch (error) { status(error.message); } }
  async function deleteCard() { if (!state.review.selected || !window.confirm('删除该卡片？')) return; try { await reviewPost('/api/cards/' + encodeURIComponent(state.review.selected.card_id), {}, 'DELETE'); await loadReview(); } catch (error) { status(error.message); } }
  async function bindCast() { const card = state.review.selected; if (!card || card.kind !== 'line') return; const ident = window.prompt('输入 AA 角色 ident；留空设为旁白', ''); if (ident === null) return; try { await reviewPost('/api/draft/cast/update', {speaker: card.current.who, mapping: ident ? {id: ident, name: card.current.who, portrait: true} : {narrator: true}}); await loadReview(); } catch (error) { status(error.message); } }

  async function annotate() {
    const op = beginOperation('annotate'); const useAI = $('input[name=anno]:checked').value === 'ai';
    try {
      const story = requireStory(); if (!state.analysis || !state.fileToken) throw new Error('请先读取剧本');
      setBusyButton('#goAnnotate', true, useAI ? 'AI 生成中…' : '正在转换…', '生成审查草稿');
      log(useAI ? 'AI 正在安排演出并生成草稿…' : '正在按原文生成审查草稿…');
      const result = await post('/api/annotate', {story_token: story.story_token, file_token: state.fileToken, mapping: state.mapping, bg: state.background || 'BG_Black', annotate: useAI, model_profile_id: $('#modelProfileSelect').value});
      if (!isCurrentOperation('annotate', op)) return;
      const job = await window.Api.poll('/api/jobs/' + result.job_id, function (item) { return ['succeeded', 'failed', 'cancelled'].includes(item.state); }, {isCurrent: function () { return isCurrentOperation('annotate', op); }, onRetry: function () { if (isCurrentOperation('annotate', op)) log('连接中断，正在重试'); }});
      if (!isCurrentOperation('annotate', op) || !job) return;
      if (job.state !== 'succeeded') throw new Error(job.error || '草稿生成失败');
      await refreshDrafts(); if (!isCurrentOperation('annotate', op)) return;
      $('#rvDraftSelect').value = job.result.draft_token; await loadReview();
      if (isCurrentOperation('annotate', op)) { log('草稿已生成，请完成审查后再编译安装'); if ($('#reviewPhase').scrollIntoView) $('#reviewPhase').scrollIntoView({behavior: 'smooth', block: 'start'}); }
    } catch (error) { if (isCurrentOperation('annotate', op)) log('草稿生成失败：' + error.message); }
    finally { if (isCurrentOperation('annotate', op)) setBusyButton('#goAnnotate', false, '', '生成审查草稿'); }
  }
  function renderBackgroundRequests(job) {
    state.backgroundJob = Object.assign({}, state.backgroundJob || {}, {token: job.resume_token || (state.backgroundJob || {}).token || '', ready: Boolean(job.backgrounds_ready || job.ready), resolveRequestId: null});
    const panel = $('#backgroundRequestsPanel'); const requests = job.background_requests || job.requests || []; panel.classList.add('open');
    const root = $('#backgroundRequestList'); clearElement(root);
    requests.forEach(function (item) {
      const row = document.createElement('div'); row.className = 'background-request-card'; row.textContent = item.description || item.id;
      if (item.status !== 'resolved') { const button = document.createElement('button'); button.type = 'button'; button.dataset.action = 'resolve-background'; button.dataset.requestId = item.id; button.textContent = '从已有背景中选择'; row.appendChild(button); }
      root.appendChild(row);
    });
    const ready = state.backgroundJob.ready; $('#continueBackgroundBuild').disabled = !ready || state.backgroundJob.continuing; $('#backgroundContinueHint').textContent = ready ? '背景已齐全，可继续生成。' : '请先为每项选择已登记背景。'; checkReady();
  }
  async function resolveBackground(requestId, backgroundName) {
    const job = state.backgroundJob; const view = captureView(); if (!job || !job.token || !isCurrentView(view)) return;
    try { const result = await post('/api/build/background/resolve', {token: job.token, request_id: requestId, background_name: backgroundName}); if (!isCurrentView(view) || state.backgroundJob !== job) return; renderBackgroundRequests(result); }
    catch (error) { if (isCurrentView(view) && state.backgroundJob === job) $('#backgroundContinueHint').textContent = error.message; }
  }
  async function continueBackground() {
    const job = state.backgroundJob; const op = state.operations.build; const view = captureView(); if (!job || !job.token || !job.ready || job.continuing || !op || !isCurrentOperation('build', op) || !isCurrentView(view)) return;
    try { job.continuing = true; $('#continueBackgroundBuild').disabled = true; await post('/api/build/background/continue', {token: job.token}); if (!isCurrentView(view) || !isCurrentOperation('build', op) || state.backgroundJob !== job) return; await pollBuild(op); }
    catch (error) { if (!isCurrentView(view) || !isCurrentOperation('build', op) || state.backgroundJob !== job) return; job.continuing = false; $('#continueBackgroundBuild').disabled = !job.ready; $('#backgroundContinueHint').textContent = error.message; checkReady(); }
  }
  async function pollBuild(op, attempt) {
    op = op || state.operations.build; attempt = attempt || 0; if (!op || !isCurrentOperation('build', op)) return;
    let job; try { job = await request('/api/job'); } catch (error) { if (!isCurrentOperation('build', op)) return; log('连接中断，正在重试'); $('#backgroundContinueHint').textContent = '连接中断，正在重试'; const delay = Math.min(8000, 500 * Math.pow(2, attempt)); setTimeout(function () { return pollBuild(op, attempt + 1); }, delay); return; }
    if (!isCurrentOperation('build', op)) return;
    if (job.running || !job.done || job.state === 'running') { setTimeout(function () { return pollBuild(op, 0); }, 700); return job; }
    if (job.state === 'needs_backgrounds' || job.state === 'backgrounds_ready') { renderBackgroundRequests(job); return job; }
    if (['succeeded', 'failed', 'cancelled'].includes(job.state)) { state.buildActive = false; state.backgroundJob = null; }
    if (job.state === 'failed' || job.state === 'cancelled') { log(job.error || (job.state === 'cancelled' ? '生成已取消' : '生成失败')); }
    else if (job.state === 'succeeded') { log('生成完成'); $('#backgroundRequestsPanel').classList.remove('open'); }
    checkReady(); return job;
  }
  async function build() { if (state.buildActive || state.backgroundJob) return; const op = beginOperation('build'); try { const story = requireStory(); if (!state.analysis) throw new Error('请先读取剧本'); state.buildActive = true; log('启动中…'); checkReady(); await post('/api/build', {story_token: story.story_token, project: story.project, script: state.analysis.path, mapping: state.mapping, bg: state.background || 'BG_Black', annotate: $('input[name=anno]:checked').value === 'ai', model_profile_id: $('#modelProfileSelect').value, install: $('#install').checked}); if (!isCurrentOperation('build', op)) return; return await pollBuild(op); } catch (error) { if (!isCurrentOperation('build', op)) return; state.buildActive = false; log(error.message); } finally { if (isCurrentOperation('build', op)) checkReady(); } }

  const recentStories = new window.StoryUI.RecentStories($('#recentStories'), openRecent);
  const storyFilePicker = window.StoryUI && window.StoryUI.StoryFilePicker ? new window.StoryUI.StoryFilePicker($('#mBrowse'), {title: '选择剧情文本', onChoose: openSelectedStory}) : null;
  const settingsFilePicker = window.StoryUI && window.StoryUI.StoryFilePicker ? new window.StoryUI.StoryFilePicker($('#mBrowse'), {hostEndpoint: '/api/settings/host', selectEndpoint: '/api/settings/entry', title: '选择设置路径', emptyStatus: '这个文件夹中没有可选择的设置路径', onChoose: saveSettingsEntryAndReset}) : null;
  if (settingsFilePicker) {
    const closeSettingsPicker = settingsFilePicker.close.bind(settingsFilePicker);
    settingsFilePicker.close = function () {
      const result = closeSettingsPicker();
      activeFilePicker = storyFilePicker;
      return result;
    };
  }
  activeFilePicker = storyFilePicker;
  new window.StoryUI.StoryContextBar($('#storyContextBar'));
  window.StoryContextStatus = window.StoryContextStatus || (window.StoryUI.StoryContextStatus ? new window.StoryUI.StoryContextStatus() : {reset: function () {}, update: function () {}});
  window.StoryAssets = window.StoryAssets || new window.StoryUI.StoryAssetStrip($('#storyAssetStrip'));
  window.ReviewWorkspace = window.ReviewWorkspace || {
    clear: function () { resetReview('正在加载当前剧情草稿'); },
    loadLatest: async function () { await refreshDrafts(); }
  };
  window.Preview = window.Preview || {clear: function () { clearElement($('#storyPlayer')); const player = playerInstance(); if (player) { player.pause(); player.loadCards([]); } }};
  window.StoryJobs = window.StoryJobs || {detachView: function () {}};
  let activeStoryToken = currentStory() && currentStory().story_token;
  window.StoryStore.subscribe(function (story) {
    $('#recentStories').classList.toggle('is-hidden', Boolean(story));
    const nextToken = story && story.story_token;
    if (nextToken !== activeStoryToken) { activeStoryToken = nextToken; resetReview(nextToken ? '正在加载当前剧情草稿' : '请先打开剧情'); }
  });
  const actions = {
    'save-spine-cli': saveSpineCli,
    'confirm-aa-workspace': confirmAAWorkspace,
    'build-aa-index': function () { return buildAAIndex(); },
    'browse-aa-install': function (trigger) { if (settingsFilePicker) { settingsPickerMode = 'aa'; activeFilePicker = settingsFilePicker; settingsFilePicker.openPath(trigger); } },
    'browse-spine-cli': function (trigger) { if (settingsFilePicker) { settingsPickerMode = 'spine'; activeFilePicker = settingsFilePicker; settingsFilePicker.openPath(trigger); } },
    'show-create': function () { $('#view-create').scrollIntoView({behavior: 'smooth'}); }, 'open-script': openScript, analyze: analyze, 'retry-story-load': function () { if (state.loadFailure) replaceStory(state.loadFailure.story, state.loadFailure.options); }, 'dismiss-welcome': function () { $('#welcomePanel').hidden = true; localStorage.setItem('aa-welcome-dismissed-v1', '1'); }, 'show-welcome': function () { $('#welcomePanel').hidden = false; localStorage.removeItem('aa-welcome-dismissed-v1'); }, 'open-settings': function () { setDrawer('settings', true); loadAAData(); }, 'close-settings': function () { setDrawer('settings', false); }, 'save-aa-install': function () { return saveAAInstall(); }, 'open-help': function () { setDrawer('help', true); }, 'close-help': function () { setDrawer('help', false); }, 'close-browse': function () { if (storyFilePicker) storyFilePicker.close(); else closeModal('#mBrowse'); }, 'story-picker-device': function () { if (storyFilePicker) storyFilePicker.chooseDevice(); }, 'story-picker-host': function () { if (storyFilePicker) storyFilePicker.openHost(); }, 'story-picker-refresh': function () { if (storyFilePicker) storyFilePicker.load(storyFilePicker.locationToken, false); }, 'story-picker-source': function () { if (storyFilePicker) storyFilePicker.open(storyFilePicker.trigger); }, 'choose-current-dir': chooseCurrentDirectory, 'close-cast': function () { closeModal('#mCast'); }, 'close-bg-replace': function () { closeModal('#mBgReplace'); state.bgReplaceCard = null; }, 'bg-replace-history': openBgHistory, 'approve-preflight': approvePreflight, 'rerun-preflight': rerunPreflight, 'cast-narrator': function () { castSetKind('narrator'); }, 'cast-unset': function () { castSetKind('unset'); }, 'resolve-background': function (target) { state.backgroundJob = Object.assign({}, state.backgroundJob, {resolveRequestId: target.dataset.requestId}); $('#s3').scrollIntoView({behavior: 'smooth'}); }, 'continue-background': continueBackground, 'refresh-drafts': refreshDrafts, 'load-review': loadReview, 'approve-all': approveAll, validate: validateReview, compile: compile, install: openInstallDialog, 'confirm-install': confirmInstall, 'close-install': function () { closeModal('#mInstall'); }, 'edit-card': editCard, 'save-edit': saveEdit, 'close-edit': function () { closeModal('#mEdit'); }, 'insert-line': function () { insertCard('line'); }, 'insert-dir': function () { insertCard('dir'); }, 'move-up': function () { moveCard('up'); }, 'move-down': function () { moveCard('down'); }, 'delete-card': deleteCard, 'bind-cast': bindCast, annotate: annotate, build: build, 'new-profile': function () { renderProfile(null); }, 'activate-profile': async function () { try { await post('/api/llm/profiles/activate', {id: $('#modelProfileId').value}); await loadProfiles($('#modelProfileId').value); } catch (error) { $('#modelStatus').textContent = error.message; } }, 'delete-profile': async function () { try { await post('/api/llm/profiles/delete', {id: $('#modelProfileId').value, delete_credential: true}); await loadProfiles(); } catch (error) { $('#modelStatus').textContent = error.message; } }, 'save-profile': saveProfile, 'clear-profile-key': clearProfileKey, 'discover-models': async function () { $('#modelStatus').textContent = '正在读取可用模型…'; try { const result = await post('/api/llm/models', {id: $('#modelProfileId').value}); const list = $('#modelOptions'); clearElement(list); result.models.forEach(function (name) { const option = document.createElement('option'); option.value = name; list.appendChild(option); }); $('#modelStatus').textContent = '已读取 ' + result.models.length + ' 个模型，可在模型输入框中选择。'; } catch (error) { $('#modelStatus').textContent = error.message; } }, 'test-text': function () { testProfile('text'); }, 'test-vision': function () { testProfile('vision'); }, 'preset-openai': function () { applyModelPreset(MODEL_PRESETS[0]); }, 'preset-anthropic': function () { applyModelPreset(MODEL_PRESETS[1]); }, 'preset-deepseek': function () { applyModelPreset(MODEL_PRESETS[2]); }, 'preset-ollama': function () { applyModelPreset(MODEL_PRESETS[3]); }, 'preset-silicon': function () { applyModelPreset(MODEL_PRESETS[4]); }, 'preset-openrouter': function () { applyModelPreset(MODEL_PRESETS[5]); }
  };
  actions['copy-install-aap'] = function () { return copyInstallAapPath(); };
  actions['close-browse'] = function () { if (activeFilePicker) activeFilePicker.close(); else closeModal('#mBrowse'); activeFilePicker = storyFilePicker; };
  actions['story-picker-refresh'] = function () { if (activeFilePicker) activeFilePicker.load(activeFilePicker.locationToken, false); };
  document.addEventListener('click', function (event) { const sortTarget = event.target.closest('[data-story-sort]'); if (sortTarget && activeFilePicker) { activeFilePicker.sortBy(sortTarget.dataset.storySort); return; } const target = event.target.closest('[data-action]'); if (target && actions[target.dataset.action]) actions[target.dataset.action](target); });
  $('#bgq').addEventListener('input', loadBackgrounds); $('#bgready').addEventListener('change', loadBackgrounds); $('#rvDraftSelect').addEventListener('change', loadReview); $('#installCategory').addEventListener('input', updateInstallProjectPreview); $('#installStoryName').addEventListener('input', updateInstallProjectPreview); $('#modelProfileSelect').addEventListener('change', function () { renderProfile(state.profiles.find(function (profile) { return profile.id === $('#modelProfileSelect').value; })); }); const castSearchInput = $('#castSearch'); if (castSearchInput) castSearchInput.addEventListener('input', function () { clearTimeout(castSearchTimer); const value = this.value; castSearchTimer = setTimeout(function () { searchCharacters(value); }, 180); }); document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { setDrawer('settings', false); setDrawer('help', false); if ($('#mInstall').classList.contains('on')) closeModal('#mInstall'); else if ($('#mBgReplace').classList.contains('on')) { closeModal('#mBgReplace'); state.bgReplaceCard = null; } else if ($('#mCast').classList.contains('on')) closeModal('#mCast'); else if ($('#mEdit').classList.contains('on')) closeModal('#mEdit'); else if (activeFilePicker && !$('#mBrowse').hidden) { activeFilePicker.close(); activeFilePicker = storyFilePicker; } else closeModal('#mBrowse'); } });
  // 记住工作台偏好（生成方式 / 是否安装），同一浏览器内持续生效。
  function restoreWorkbenchPreferences() {
    try {
      const saved = JSON.parse(localStorage.getItem('aa-workbench-preferences-v1') || '{}');
      const anno = saved.anno === 'no' ? 'no' : 'ai';
      const radios = document.querySelectorAll ? Array.from(document.querySelectorAll('input[name=anno]')) : [];
      radios.forEach(function (radio) { radio.checked = radio.value === anno; });
      const install = document.querySelector ? document.querySelector('#install') : null;
      if (install && typeof saved.install === 'boolean') install.checked = saved.install;
    } catch (_) { /* 首次使用，保持默认 */ }
  }
  function persistWorkbenchPreferences() {
    try {
      const annoRadio = document.querySelector ? document.querySelector('input[name=anno]:checked') : null;
      const install = document.querySelector ? document.querySelector('#install') : null;
      localStorage.setItem('aa-workbench-preferences-v1', JSON.stringify({
        anno: annoRadio ? annoRadio.value : 'ai',
        install: install ? install.checked : true
      }));
    } catch (_) {}
  }
  restoreWorkbenchPreferences();
  if (document.querySelectorAll) Array.from(document.querySelectorAll('input[name=anno]')).forEach(function (radio) { radio.addEventListener('change', persistWorkbenchPreferences); });
  const installBox = document.querySelector ? document.querySelector('#install') : null;
  if (installBox) installBox.addEventListener('change', persistWorkbenchPreferences);
  window.replaceStory = replaceStory;
  window.refreshAfterAssetWorkbench = refreshAfterAssetWorkbench;
  window.addEventListener('assetworkbench:copied', function (event) {
    const detail = event && event.detail || {};
    const story = currentStory();
    if (!story || detail.story_token !== story.story_token) return;
    const context = detail.context || {origin: 'preflight', story_token: detail.story_token, asset_kind: detail.kind};
    if (context.origin === 'review') applyWorkbenchBackground(context, detail);
    else refreshAfterAssetWorkbench(context);
  });
  window.AppRuntime = {analyze: analyze, annotate: annotate, build: build, compile: compile, beginOperation: beginOperation, loadBackgrounds: loadBackgrounds, loadReview: loadReview, refreshDrafts: refreshDrafts, reviewPost: reviewPost, renderBackgroundRequests: renderBackgroundRequests, resolveBackground: resolveBackground, pollBuild: pollBuild, continueBackground: continueBackground, replaceStory: replaceStory, fillBackgroundFromHistory: fillBackgroundFromHistory, renderCast: renderCast, searchCharacters: searchCharacters, pickCharacter: pickCharacter, castSetKind: castSetKind, openCastPicker: openCastPicker, renderReviewCards: renderReviewCards, renderReviewAssets: renderReviewAssets, renderPreflight: renderPreflight, buildPreflightAssetTasks: buildPreflightAssetTasks, refreshAfterAssetWorkbench: refreshAfterAssetWorkbench, applyWorkbenchBackground: applyWorkbenchBackground, approvePreflight: approvePreflight, rerunPreflight: rerunPreflight, renderBackgroundTimeline: renderBackgroundTimeline, openBgReplace: openBgReplace, applyBgReplace: applyBgReplace, renderAAStatus: renderAAStatus, openInstallDialog: openInstallDialog, confirmInstall: confirmInstall, updateInstallProjectPreview: updateInstallProjectPreview};
  window.AppRuntime.buildAAIndex = buildAAIndex;
  window.AppRuntime.pollAAIndex = pollAAIndex;
  window.addEventListener('load', function () { if (localStorage.getItem('aa-welcome-dismissed-v1') === '1') $('#welcomePanel').hidden = true; loadSetupStatus(); loadState(); loadProfiles().catch(function () {}); recentStories.refresh().catch(function () {}); });
})();
