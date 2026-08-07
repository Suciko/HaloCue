(function () {
  'use strict';

  const $ = function (selector) { return document.querySelector(selector); };
  const $$ = function (selector) { return Array.from(document.querySelectorAll(selector)); };
  const state = {analysis: null, mapping: {}, preflight: null, preflightApproved: false, preflightStale: false, background: null, backgroundJob: null, generationPrompt: null, generationPromptTarget: null, generationPromptStoryToken: null, buildActive: false, fileToken: null, sourcePath: null, browseMode: 'script', browseDirectory: '', profiles: [], profileBaseline: null, modelWorkbench: null, discoveredModelCapabilities: [], modelRole: 'text', modelEditorMode: 'new', workflowStage: 'script', review: {token: null, revision: 1, buildId: null, cards: [], selected: null, filter: 'all', cardLimit: 80}, reviewAssets: null, bgReplaceCard: null, reviewBackgroundRequest: null, operationId: 0, operations: {annotate: null, compile: null, build: null, analyze: null, preflight: null}, transitionId: 0, viewEpoch: 0, loadFailure: null};
  let activeFilePicker = null;
  let settingsPickerMode = '';
  let aaIndexPollTimer = null;
  let aaStatusSnapshot = {};
  let backgroundLoadId = 0;
  const reviewActions = ['rvEdit', 'rvInsertLine', 'rvInsertDir', 'rvMoveUp', 'rvMoveDown', 'rvDelete', 'rvBind'];
  const ACTIVE_REVIEW_KEY = 'aa-active-review-v1';
  const MODEL_PRESETS = [
    {key: 'deepseek', label: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-v4-flash', vision: false, official_url: 'https://www.deepseek.com/', api_key_url: 'https://platform.deepseek.com/api_keys'},
    {key: 'glm', label: 'GLM / 智谱', provider: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4.6', vision: true, official_url: 'https://open.bigmodel.cn/', api_key_url: 'https://open.bigmodel.cn/usercenter/apikeys'},
    {key: 'qwen', label: '千问 / 百炼', provider: 'openai', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-max', vision: true, official_url: 'https://bailian.console.aliyun.com/', api_key_url: 'https://bailian.console.aliyun.com/?apiKey=1'},
    {key: 'moonshot', label: 'Kimi / Moonshot', provider: 'openai', base_url: 'https://api.moonshot.cn/v1', model: 'kimi-k2-0905-preview', vision: false, official_url: 'https://platform.kimi.com/', api_key_url: 'https://platform.kimi.com/console/api-keys'},
    {key: 'siliconflow', label: '硅基流动', provider: 'openai', base_url: 'https://api.siliconflow.cn/v1', model: 'deepseek-ai/DeepSeek-V3', vision: false, official_url: 'https://siliconflow.cn/', api_key_url: 'https://cloud.siliconflow.cn/account/ak'},
    {key: 'openai', label: 'OpenAI', provider: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-4o', vision: true, official_url: 'https://openai.com/api/', api_key_url: 'https://platform.openai.com/api-keys'},
    {key: 'anthropic', label: 'Anthropic', provider: 'anthropic', base_url: 'https://api.anthropic.com', model: 'claude-sonnet-4-5', vision: true, official_url: 'https://www.anthropic.com/api', api_key_url: 'https://console.anthropic.com/settings/keys'},
    {key: 'gemini', label: 'Gemini', provider: 'openai', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', model: 'gemini-2.5-flash', vision: true, official_url: 'https://ai.google.dev/gemini-api/docs', api_key_url: 'https://aistudio.google.com/apikey'},
    {key: 'openrouter', label: 'OpenRouter', provider: 'openai', base_url: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini', vision: true, official_url: 'https://openrouter.ai/', api_key_url: 'https://openrouter.ai/settings/keys'},
    {key: 'ollama', label: 'Ollama', provider: 'openai', base_url: 'http://localhost:11434/v1', model: 'llama3.2', vision: false, official_url: 'https://ollama.com/', api_key_url: ''}
  ];

  function show(id, visible) { $(id).classList.toggle('on', Boolean(visible)); }
  const modalTriggers = {};
  function openModal(id, trigger) { modalTriggers[id] = trigger || document.activeElement; show(id, true); const dialog = $(id); dialog.setAttribute('aria-hidden', 'false'); const focusTarget = dialog.querySelector && dialog.querySelector('button, input, textarea, select, [tabindex]'); (focusTarget || dialog).focus(); }
  function closeModal(id) { const dialog = $(id); if (!dialog.classList.contains('on')) return; show(id, false); dialog.setAttribute('aria-hidden', 'true'); const trigger = modalTriggers[id]; if (trigger && trigger.focus) trigger.focus(); delete modalTriggers[id]; }
  function visible(id, value) { $(id).classList.toggle('is-visible', Boolean(value)); }
  function currentStory() { return window.StoryStore.get(); }
  function readActiveReview() {
    try {
      const value = JSON.parse(localStorage.getItem(ACTIVE_REVIEW_KEY) || 'null');
      return value && typeof value.story_token === 'string' ? value : null;
    } catch (_) { return null; }
  }
  function rememberActiveReview(values) {
    const current = readActiveReview() || {};
    const next = Object.assign({}, current, values || {});
    if (!next.story_token) { localStorage.removeItem(ACTIVE_REVIEW_KEY); return; }
    ['story_token', 'draft_token', 'card_id'].forEach(function (key) { if (!next[key]) delete next[key]; });
    localStorage.setItem(ACTIVE_REVIEW_KEY, JSON.stringify(next));
  }
  function forgetActiveReview() { localStorage.removeItem(ACTIVE_REVIEW_KEY); }
  function requireStory() { const story = currentStory(); if (!story) throw new Error('请先打开剧情'); return story; }
  function request(path, options) { return window.Api.request(path, options); }
  function post(path, payload) { return request(path, window.Api.json('POST', payload)); }
  function legacyModelProfileId() {
    return state.modelWorkbench && state.modelWorkbench.compatibility_mode === 'legacy'
      ? $('#modelProfileSelect').value
      : '';
  }
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
  function setScriptScanProgress(phase, message, failed, completedValue) {
    const root = $('#scriptScanProgress');
    if (!root) return;
    const index = Math.max(0, scriptScanPhases.indexOf(phase));
    root.classList.remove('is-hidden'); root.classList.toggle('is-failed', Boolean(failed));
    const title = $('#scriptScanTitle'); if (title) title.textContent = message || '正在读取剧本';
    const value = completedValue === undefined ? (failed ? index : index + 1) : completedValue;
    const count = $('#scriptScanCount'); if (count) count.textContent = value + ' / ' + scriptScanPhases.length;
    const bar = $('#scriptScanBar'); if (bar) { bar.value = value; bar.textContent = value + ' / ' + scriptScanPhases.length; }
    const list = $('#scriptScanSteps');
    Array.prototype.forEach.call(list && list.children || [], function (node, stepIndex) {
      node.classList.toggle('done', !failed && stepIndex < index);
      node.classList.toggle('active', stepIndex === index);
    });
  }
  function resetScriptScanProgress() {
    const root = $('#scriptScanProgress'); if (!root) return;
    root.classList.add('is-hidden'); root.classList.remove('is-failed');
    const bar = $('#scriptScanBar'); if (bar) { bar.value = 0; bar.textContent = '0 / ' + scriptScanPhases.length; }
  }
  function playerInstance() { return window.storyPlayer && typeof window.storyPlayer.loadCards === 'function' ? window.storyPlayer : null; }
  function destroyPlayer() {
    const player = playerInstance();
    if (player && typeof player.pause === 'function') player.pause();
    window.storyPlayer = null;
    clearElement($('#storyPlayer'));
  }
  function ensurePlayer() {
    const existing = playerInstance();
    if (existing || !window.Player) return existing;
    window.storyPlayer = new window.Player($('#storyPlayer'));
    return playerInstance();
  }
  function contextStatus(values) { if (window.StoryContextStatus) window.StoryContextStatus.update(values); }
  function resetContextStatus() { if (window.StoryContextStatus) window.StoryContextStatus.reset(); }
  function log(value) { visible('#log', true); $('#log').textContent = value; }
  function annotationProgressDetail(item) {
    item = item || {};
    const activity = item.activity && typeof item.activity === 'object' ? item.activity : item;
    const detail = String(item.detail || '');
    const activityState = String(activity.state || '');
    const chars = Number(activity.received_chars);
    const reasoningChars = Number(activity.reasoning_chars);
    const elapsed = Number(activity.elapsed_ms);
    const suffix = function (value) { return detail ? detail + ' · ' + value : value; };
    if (activityState === 'waiting') return suffix('等待模型首段响应');
    if (activityState === 'reasoning') {
      const count = Number.isFinite(reasoningChars) ? '已思考 ' + reasoningChars.toLocaleString('en-US') + ' 字符' : '模型思考中';
      const waited = Number.isFinite(elapsed) && elapsed >= 1000 ? ' · 已用时 ' + Math.max(1, Math.floor(elapsed / 1000)) + ' 秒' : '';
      return suffix(count + waited);
    }
    if (activityState === 'receiving') {
      const received = Number.isFinite(chars) ? '已接收 ' + chars.toLocaleString('en-US') + ' 字符' : '正在接收模型输出';
      const waited = Number.isFinite(elapsed) && elapsed >= 1000 ? ' · 已等待 ' + Math.max(1, Math.floor(elapsed / 1000)) + ' 秒' : '';
      return suffix(received + waited);
    }
    if (activityState === 'retrying') return suffix('正在纠正返回格式');
    if (activityState === 'subdividing') return suffix('正在拆分当前场景块');
    if (!detail || !item.updated_at || item.state !== 'running') return detail;
    const age = Date.now() - Date.parse(item.updated_at);
    if (!Number.isFinite(age) || age < 60000) return detail;
    return detail + ' · 模型仍在响应（已等待 ' + Math.max(1, Math.floor(age / 60000)) + ' 分钟）';
  }
  function formatAnnotationCompletion(metrics) {
    metrics = metrics || {};
    const model = String(metrics.actual_model || metrics.model || '模型未知');
    const requests = Number(metrics.requests);
    const retries = Number(metrics.retries);
    const subdivisions = Number(metrics.subdivisions);
    const elapsed = Number(metrics.elapsed_ms);
    const parts = ['模型 ' + model];
    if (Number.isFinite(requests)) parts.push('请求 ' + requests + ' 次');
    if (Number.isFinite(retries)) parts.push('重试 ' + retries + ' 次');
    if (Number.isFinite(subdivisions)) parts.push('缩块 ' + subdivisions + ' 次');
    if (Number.isFinite(elapsed)) {
      const seconds = Math.max(0, Math.round(elapsed / 1000));
      parts.push('耗时 ' + (seconds >= 60 ? Math.floor(seconds / 60) + ' 分 ' + (seconds % 60) + ' 秒' : seconds + ' 秒'));
    }
    if (metrics.cache_reported === true && Number.isFinite(Number(metrics.cache_hit_rate))) {
      parts.push('缓存命中 ' + Math.round(Number(metrics.cache_hit_rate) * 100) + '%');
    } else {
      parts.push('缓存未报告');
    }
    return parts.join(' · ');
  }
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
    const remembered = readActiveReview();
    rememberActiveReview(remembered && remembered.story_token === next.story_token
      ? {story_token: next.story_token}
      : {story_token: next.story_token, draft_token: null, card_id: null});
    $('#welcomePanel').hidden = true;
    $('#path').value = options.showSourcePath === false ? '' : (state.sourcePath || next.source_name || '');
    $('#proj').value = next.project;
    try {
      await Promise.all([
        storyComponent('StoryAssets').load(next.story_token),
        storyComponent('ReviewWorkspace').loadLatest(next),
      ]);
      if (isCurrentTransition(transition) && currentStory() && currentStory().story_token === next.story_token) {
        restorePreflightSnapshot(next.preflight_snapshot);
        $('#s1info').textContent = ''; $('#storyLoadRetry').hidden = true;
      }
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
    state.review = {token: null, revision: 1, buildId: null, cards: [], selected: null, filter: 'all', cardLimit: 80}; state.reviewAssets = null; state.bgReplaceCard = null; state.reviewBackgroundRequest = null;
    clearElement($('#rvDraftSelect'));
    const option = document.createElement('option'); option.value = ''; option.textContent = '没有草稿'; $('#rvDraftSelect').appendChild(option);
    clearElement($('#rvCards')); $('#rvOpen').disabled = true; $('#rvApproveAll').disabled = true; $('#rvValidate').disabled = true; $('#rvCompile').disabled = true; $('#rvInstall').disabled = true; setReviewActions(false, false); showReviewPhase(false);
    destroyPlayer();
    status(message || '尚未打开草稿');
    resetContextStatus();
  }

  function clearStoryRuntime() {
    state.viewEpoch += 1;
    state.analysis = null; state.mapping = {}; state.preflight = null; state.preflightApproved = false; state.preflightStale = false; state.background = null; state.backgroundJob = null; state.buildActive = false; state.fileToken = null; state.sourcePath = null; state.reviewAssets = null; state.bgReplaceCard = null;
    state.generationPrompt = null; state.generationPromptTarget = null; state.generationPromptStoryToken = null;
    if ($('#preflightScenePlan')) clearElement($('#preflightScenePlan'));
    const promptModal = $('#mGenerationPrompt');
    if (promptModal && promptModal.classList && promptModal.classList.contains && promptModal.classList.contains('on')) closeModal('#mGenerationPrompt');
    const installModal = $('#mInstall');
    if (installModal && installModal.classList && installModal.classList.contains && installModal.classList.contains('on')) closeModal('#mInstall');
    clearElement($('#bggrid')); clearElement($('#storyPlayer')); clearElement($('#preflightCast')); clearElement($('#preflightAssets')); clearElement($('#preflightIssues')); clearElement($('#preflightSummary')); $('#bgTimeline').textContent = ''; $('#preflightStatus').textContent = '等待分析'; $('#preflightHint').textContent = ''; $('#s1info').textContent = ''; $('#log').textContent = ''; resetScriptScanProgress(); visible('#log', false); ['#s2preflight', '#s4'].forEach(function (id) { $(id).classList.add('off'); }); $('#preflightApprove').disabled = true;
    const backgroundPicker = $('#mBackgroundPicker');
    if (backgroundPicker && backgroundPicker.classList && backgroundPicker.classList.contains && backgroundPicker.classList.contains('on')) closeModal('#mBackgroundPicker');
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
      const modelDetail = window.ModelSettings && window.ModelSettings.modelReadinessLabel
        ? window.ModelSettings.modelReadinessLabel(result.model)
        : (result.model.configured ? result.model.name + ' · ' + result.model.model : '仅转换格式时无需 AI');
      readiness('#readyModel', result.model.configured, modelDetail);
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
  async function showRecentStories() {
    const root = $('#recentStories');
    root.classList.remove('is-hidden');
    await recentStories.refresh();
    if (root.scrollIntoView) root.scrollIntoView({behavior: 'smooth', block: 'start'});
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
      const restored = await replaceStory(context, {transition: transition, fileToken: context.file_token || null, sourcePath: context.source_name || ''});
      const hasSnapshot = Boolean(context.preflight_snapshot && context.preflight_snapshot.result);
      if (restored && context.file_token && !hasSnapshot && isCurrentTransition(transition)) await analyze();
    } catch (error) { if (isCurrentTransition(transition)) $('#s1info').textContent = '无法恢复剧情：' + error.message; }
  }

  async function restoreActiveReview() {
    const saved = readActiveReview();
    if (!saved) return false;
    const transition = beginTransition();
    try {
      const context = await request('/api/story/current?story_token=' + encodeURIComponent(saved.story_token));
      if (!isCurrentTransition(transition)) return false;
      const restored = await replaceStory(context, {transition: transition, fileToken: context.file_token || null, sourcePath: context.source_name || '', showSourcePath: false});
      if (!restored || !isCurrentTransition(transition)) return false;
      if (saved.draft_token) {
        const option = Array.prototype.find.call($('#rvDraftSelect').children, function (item) { return item.value === saved.draft_token; });
        if (option) { $('#rvDraftSelect').value = saved.draft_token; await loadReview(saved.card_id); }
      }
      return true;
    } catch (_) {
      if (isCurrentTransition(transition)) {
        forgetActiveReview();
        window.StoryStore.set(null);
        $('#welcomePanel').hidden = false;
      }
      return false;
    }
  }

  function restorePreflightSnapshot(snapshot) {
    if (!snapshot || !snapshot.result || typeof snapshot.result !== 'object') return false;
    const result = snapshot.result;
    state.preflightStale = snapshot.state !== 'fresh';
    state.preflightApproved = !state.preflightStale && snapshot.approved === true;
    state.analysis = Object.assign({lines: 0, speakers: [], scenes: []}, result.analysis || {});
    state.mapping = {};
    applyPreflightMapping(result);
    renderPreflight(result);
    hydratePreflightCharacters(result).then(function () {
      if (state.preflight === result) {
        renderPreflight(result);
        if (state.preflightStale) applyStalePreflightState();
      }
    });
    finishPreflightProgress(result, state.analysis);
    if (state.preflightStale) applyStalePreflightState();
    return true;
  }

  function applyStalePreflightState() {
    state.preflightApproved = false;
    $('#s4').classList.add('off');
    setWorkflowStage('preflight');
    $('#preflightStatus').textContent = '原文已变化';
    $('#preflightHint').textContent = '当前显示上次保存的判断；原文已变化，请重新初审后再继续。';
    $('#preflightApprove').disabled = true;
    checkReady();
  }

  function clearElement(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function backgroundCard(item) {
    const card = document.createElement('button'); card.type = 'button'; card.className = 'bgc';
    card.dataset.name = item.name; card.classList.toggle('sel', state.background === item.name);
    if (item.img) {
      const image = document.createElement('img'); image.loading = 'lazy'; image.alt = item.label || item.name || '背景';
      image.src = '/thumb/bg/' + encodeURIComponent(item.name) + '?px=240'; card.appendChild(image);
    } else {
      const placeholder = document.createElement('span'); placeholder.className = 'ph'; placeholder.textContent = '暂无预览'; card.appendChild(placeholder);
    }
    const label = document.createElement('span'); label.className = 'cap'; label.textContent = item.label || item.name;
    card.appendChild(label); card.addEventListener('click', function () { selectBackground(item.name); }); return card;
  }
  async function loadBackgrounds() {
    const view = captureView();
    const loadId = ++backgroundLoadId;
    const query = encodeURIComponent($('#bgq').value); const ready = $('#bgready').checked ? '1' : '0';
    try { const items = await request('/api/backgrounds?q=' + query + '&ready=' + ready); if (!isCurrentView(view) || loadId !== backgroundLoadId) return; const root = $('#bggrid'); clearElement(root); items.forEach(function (item) { root.appendChild(backgroundCard(item)); }); }
    catch (_) { if (isCurrentView(view) && loadId === backgroundLoadId) $('#bggrid').textContent = '背景列表加载失败'; }
  }
  function selectBackground(name, label) {
    if (state.reviewBackgroundRequest) {
      const card = state.reviewBackgroundRequest;
      state.reviewBackgroundRequest = null;
      closeModal('#mBackgroundPicker');
      resolveDraftBackgroundRequest(card, name);
      return;
    }
    if (state.backgroundJob && state.backgroundJob.resolveRequestId) {
      const requestId = state.backgroundJob.resolveRequestId;
      closeModal('#mBackgroundPicker'); resolveBackground(requestId, name); return;
    }
    state.background = name; $$('.bgc').forEach(function (node) { node.classList.toggle('sel', node.dataset.name === name); }); checkReady();
  }
  function safePreflightError(value) {
    const message = String(value || '').replace(/(api[_ -]?key|authorization|bearer|token|secret)\s*[=:]\s*[^\s,;]+/ig, '$1=已隐藏');
    return message.slice(0, 500);
  }
  function fallbackPreflight(error) {
    const speakers = state.analysis && state.analysis.speakers || [];
    const characters = speakers.map(function (speaker) {
      const mapping = state.mapping[speaker.who] || {};
      return {speaker: speaker.who, kind: mapping.kind || 'unset', id: mapping.id || '', name: mapping.name || '', custom: Boolean(mapping.custom), confidence: mapping.kind ? 0.65 : 0, reason: '规则分析结果，可手动修改。'};
    });
    const nonstandard = state.analysis && state.analysis.format && state.analysis.format.confidence === 'low';
    const detail = safePreflightError(error && error.message);
    const issue = nonstandard
      ? {severity: 'error', code: 'nonstandard_format_requires_ai', message: '当前剧本是非标准格式，但 AI 全文初审没有完成。', action: '请配置可用模型后重新初审，或按帮助中的“角色名：台词”格式整理剧本。'}
      : {severity: 'warning', code: 'preflight_unavailable', message: 'AI 初审暂时不可用，已保留规则分析结果。', action: '检查模型配置后重试，或确认规则结果继续。'};
    if (detail) issue.action += ' 失败原因：' + detail;
    return {
      ok: true, ai_status: 'failed', characters: characters, assets: [],
      usage_chain: [], usage_chain_status: 'unavailable',
      ai_diagnostics: {stage: 'job', message: detail || '初审任务未完成'},
      available_assets: {characters: [], backgrounds: [], sounds: [], bgms: []},
      issues: [issue],
    };
  }
  function applyPreflightMapping(result) {
    (result.characters || []).forEach(function (item) {
      if (!item || !item.speaker) return;
      const kind = item.kind || 'unset';
      state.mapping[item.speaker] = kind === 'unset' ? {kind: 'unset'} : {kind: kind, id: item.id || '', name: item.name || item.speaker, spine: item.spine || '', source: item.source || '', avatar: item.avatar || '', custom: Boolean(item.custom)};
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
  function usageBackgroundAssetTask(need) {
    const location = String(need && need.location || '位置未标注');
    const name = String(need && need.name || '未命名背景');
    return {
      task_id: ['background', name, location].join(':'),
      kind: 'background',
      requested_name: name,
      source_location: {label: location},
      reason: '官方背景匹配低于 90%，可补充更贴合场景的自定义背景',
      candidate_keys: (need && Array.isArray(need.candidates) ? need.candidates : []).map(function (candidate) {
        return String(candidate && candidate.aa_key || '');
      }).filter(Boolean)
    };
  }
  function usageBackgroundTarget(segment, need) {
    if (!segment || !need) return null;
    return {
      selector: {
        segment: String(segment.segment || ''),
        location: String(need.location || ''),
        requested_name: String(need.name || '')
      },
      place: String(segment.location || '')
    };
  }
  function openPreflightAssetWorkbench(kind, trigger, usageNeed, segment) {
    const story = currentStory();
    if (!story || !window.openAssetWorkbench) return;
    const tasks = buildPreflightAssetTasks(state.preflight).filter(function (task) { return task.kind === kind; });
    if (kind === 'background' && usageNeed) {
      const usageTask = usageBackgroundAssetTask(usageNeed);
      if (!tasks.some(function (task) { return task.task_id === usageTask.task_id; })) tasks.unshift(usageTask);
    }
    state.preflightWorkbenchReturn = {
      x: Number(window.scrollX || 0), y: Number(window.scrollY || 0), trigger: trigger || null
    };
    const context = {
      origin: 'preflight', story_token: story.story_token, asset_kind: kind, tasks: tasks
    };
    if (kind === 'background' && usageNeed && segment) {
      context.background_target = usageBackgroundTarget(segment, usageNeed);
    }
    window.openAssetWorkbench(context);
  }
  function usageStatusLabel(status, kind) {
    if (['sound', 'bgm'].includes(kind) && !['registered', 'builtin'].includes(status)) return '可选';
    return status === 'registered' ? (kind === 'background' ? '已采用' : '本剧情已登记') : status === 'builtin' ? 'AA 内置可用' : status === 'recommended' ? '推荐可用' : status === 'approximate' ? '近似可用' : status === 'unsupported' ? '待验证' : status === 'missing' ? '待补充' : '待确认';
  }
  function usageKindLabel(kind) {
    return kind === 'background' ? '背景' : kind === 'bgm' ? 'BGM' : kind === 'sound' ? '音效' : kind;
  }
  function compactUsageMarker(value) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (text.length <= 32) return text;
    return text.slice(0, 31).replace(/[，,。.!！？?；;：:、\s]+$/g, '') + '…';
  }
  function syncDefaultBackgroundFromUsageChain(result) {
    const chain = result && Array.isArray(result.usage_chain) ? result.usage_chain : [];
    const needs = chain.reduce(function (all, segment) {
      return all.concat(Array.isArray(segment.needs) ? segment.needs.filter(function (need) { return need.kind === 'background'; }) : []);
    }, []);
    const first = needs.find(function (need) { return ['registered', 'builtin'].includes(need.status); });
    if (!state.background && first) selectBackground(first.aa_key || first.name, first.name);
  }
  function backgroundGenerationPrompt(need) {
    const existing = String(need && need.generation_prompt || '').trim();
    const quality = '画面质量：清晰干净的游戏背景原画，自然材质细节，低噪点、无颗粒、无胶片噪声、无色带、无 JPEG 压缩伪影、无过度锐化、无脏污纹理、无模糊重影。';
    const exclusions = '排除内容：人物、文字、水印、UI、对白框、Logo 和边框。';
    if (existing) return existing + (existing.includes('低噪点') ? '' : '\n' + quality + '\n' + exclusions);
    const name = String(need && need.name || '未命名场景').trim();
    const location = String(need && need.location || '当前场景').trim();
    const reason = String(need && need.reason || '根据剧情内容补充贴合场景的环境背景。').trim();
    return [
      '请生成一张用于剧情演出的日系二次元游戏背景图。',
      '场景：' + name,
      '剧情位置：' + location,
      '场景要求：' + reason,
      '构图要求：横向 16:9，环境空间关系清晰，保留角色站位和对白区域。',
      quality,
      exclusions
    ].join('\n');
  }
  function resetGenerationImportResult() {
    const result = $('#generationImportResult'); if (result) result.hidden = true;
    const preview = $('#generationImportPreview'); if (preview) { preview.src = ''; preview.alt = ''; }
    const name = $('#generationImportName'); if (name) name.textContent = '';
    const meta = $('#generationImportMeta'); if (meta) meta.textContent = '';
  }
  function openBackgroundPrompt(need, trigger, segment) {
    state.generationPrompt = need || null;
    state.generationPromptTarget = usageBackgroundTarget(segment, need);
    const story = currentStory(); state.generationPromptStoryToken = story && story.story_token || null;
    const title = $('#generationPromptTitle');
    const scene = $('#generationPromptScene');
    const hint = $('#generationPromptHint');
    const text = $('#generationPromptText');
    const status = $('#generationPromptStatus');
    if (title) title.textContent = '生图提示词';
    if (scene) scene.textContent = need && need.name || '未命名背景';
    if (hint) hint.textContent = '这是可编辑的提示词草稿。可复制到豆包、Gemini 或 GPT 等图片生成工具，再把生成的图片导入当前剧情。';
    if (text) text.value = backgroundGenerationPrompt(need);
    if (status) status.textContent = '';
    resetGenerationImportResult();
    openModal('#mGenerationPrompt', trigger);
  }
  async function copyGenerationPrompt() {
    const text = $('#generationPromptText');
    const value = text && text.value || '';
    if (!value) return;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        $('#generationPromptStatus').textContent = '已复制，可粘贴到图片生成工具。';
        return;
      }
    } catch (_) {}
    if (text && text.select) text.select();
    $('#generationPromptStatus').textContent = '提示词已选中，请复制。';
  }
  function structuredOutputPending(result) {
    return Boolean(result && result.ai_diagnostics && result.ai_diagnostics.stage === 'structured_output');
  }
  function finishPreflightProgress(result, analysis) {
    let progress = 'AI 初审未完成，已保留规则分析结果。';
    let suffix = 'AI 初审未完成，可检查下方规则分析结果。';
    if (structuredOutputPending(result)) {
      progress = 'AI 已响应，结果待整理；请检查下方规则结果。';
      suffix = 'AI 已响应，结果待整理；当前可检查下方规则分析结果。';
    } else if (result && result.ai_status === 'completed') {
      progress = 'AI 初审已完成，请检查下方结果。';
      suffix = 'AI 初审已完成，可在下方检查结果。';
    }
    setScriptScanProgress('ai', progress, false, result && result.ai_status === 'completed' ? 4 : 3);
    if (analysis) $('#s1info').textContent = '共 ' + analysis.lines + ' 行台词，' + analysis.speakers.length + ' 位说话者。' + suffix;
  }
  async function applyUsageBackgroundCandidate(segment, need, candidate, button) {
    const story = currentStory();
    const target = usageBackgroundTarget(segment, need);
    if (!story || !target || !candidate || !candidate.aa_key) return null;
    const view = captureView(story);
    const originalText = button && button.textContent || '采用此背景';
    if (button) { button.disabled = true; button.textContent = '正在采用…'; }
    try {
      const binding = await post('/api/preflight/background-binding', {
        story_token: story.story_token,
        selector: target.selector,
        binding: {
          aa_key: String(candidate.aa_key),
          selected_label: String(candidate.label || candidate.aa_key)
        }
      });
      if (!isCurrentView(view)) return binding;
      if (binding && binding.preflight_snapshot) restorePreflightSnapshot(binding.preflight_snapshot);
      return binding;
    } catch (error) {
      if (isCurrentView(view)) {
        if (button) { button.disabled = false; button.textContent = '重新采用'; }
        $('#preflightHint').textContent = '背景采用失败：' + String(error && error.message || '请重试');
      }
      return null;
    } finally {
      if (button && isCurrentView(view) && !button.disabled) button.textContent = button.textContent || originalText;
    }
  }
  function shouldOfferCustomBackground(need) {
    if (!need || need.kind !== 'background' || !['missing', 'recommended', 'approximate'].includes(need.status)) return false;
    const confidences = (Array.isArray(need.candidates) ? need.candidates : []).map(function (candidate) {
      return Number(candidate && candidate.confidence);
    }).filter(Number.isFinite);
    return !confidences.length || Math.max.apply(Math, confidences) < 0.90;
  }
  function customBackgroundWorkflow(segment, need) {
    const details = document.createElement('details'); details.className = 'usage-custom-background'; details.open = !(Array.isArray(need.candidates) && need.candidates.length);
    const summary = document.createElement('summary'); summary.textContent = '自定义背景工作流'; details.appendChild(summary);
    const body = document.createElement('div'); body.className = 'usage-custom-background-body';
    const hint = document.createElement('p'); hint.className = 'dim'; hint.textContent = '官方背景匹配低于 90%，可以生成或导入更贴合当前场景的背景。'; body.appendChild(hint);
    const actions = document.createElement('div'); actions.className = 'usage-custom-background-actions';
    const prompt = document.createElement('button'); prompt.type = 'button'; prompt.className = 'usage-prompt-primary'; prompt.dataset.usageAction = 'generate-prompt'; prompt.textContent = '生成生图提示词';
    prompt.addEventListener('click', function () { openBackgroundPrompt(need, prompt, segment); }); actions.appendChild(prompt);
    if (window.StoryAssets && window.StoryAssets.importLocal) {
      const local = document.createElement('button'); local.type = 'button'; local.className = 'ghost'; local.dataset.usageAction = 'import-generated-background'; local.textContent = '导入生成结果';
      local.addEventListener('click', function () { openBackgroundPrompt(need, local, segment); openGeneratedBackgroundPicker($('#generationImportButton') || local); }); actions.appendChild(local);
    }
    if (window.HistoryDrawer && window.HistoryDrawer.open) {
      const history = document.createElement('button'); history.type = 'button'; history.className = 'ghost'; history.dataset.usageAction = 'import-background-history'; history.textContent = '从历史背景导入';
      history.addEventListener('click', function () { window.HistoryDrawer.open({kind: 'background', trigger: history, onApplied: function () { return rerunPreflight(); }}); }); actions.appendChild(history);
    }
    if (window.openAssetWorkbench) {
      const workbench = document.createElement('button'); workbench.type = 'button'; workbench.className = 'ghost'; workbench.dataset.usageAction = 'open-background-workbench'; workbench.textContent = '打开素材工作台';
      workbench.addEventListener('click', function () { openPreflightAssetWorkbench('background', workbench, need, segment); }); actions.appendChild(workbench);
    }
    body.appendChild(actions); details.appendChild(body); return details;
  }
  function usageNeedCard(segment, need) {
    const card = document.createElement('article'); card.className = 'usage-need usage-need-' + (need.status || 'unknown') + (['sound', 'bgm'].includes(need.kind) ? ' usage-need-optional' : '');
    const heading = document.createElement('div'); heading.className = 'usage-need-heading';
    const name = document.createElement('b'); name.textContent = usageKindLabel(need.kind) + '：' + (need.name || '未命名');
    const stateText = document.createElement('span'); stateText.className = 'usage-need-status'; stateText.textContent = usageStatusLabel(need.status, need.kind);
    heading.append(name, stateText); card.appendChild(heading);
    const meta = document.createElement('p'); meta.className = 'usage-need-meta dim';
    const confidence = Number(need.confidence);
    meta.textContent = [need.location, Number.isFinite(confidence) ? '置信度 ' + Math.round(confidence * 100) + '%' : ''].filter(Boolean).join(' · ');
    card.appendChild(meta);
    if (need.kind === 'background' && need.status === 'registered' && need.aa_key) {
      const selected = document.createElement('div'); selected.className = 'usage-bound-background';
      if (need.preview_available) {
        const preview = document.createElement('img');
        preview.className = 'usage-bound-background-preview';
        preview.loading = 'lazy';
        preview.alt = (need.selected_label || need.name || need.aa_key) + ' 预览';
        preview.src = need.preview_source === 'official'
          ? '/thumb/bg/' + encodeURIComponent(need.aa_key) + '?px=480'
          : '/api/story/assets/preview?story_token=' + encodeURIComponent((currentStory() || {}).story_token || '') + '&kind=background&key=' + encodeURIComponent(need.aa_key);
        selected.appendChild(preview);
      } else {
        const placeholder = document.createElement('span');
        placeholder.className = 'usage-bound-background-placeholder';
        placeholder.textContent = '预览暂不可用';
        selected.appendChild(placeholder);
      }
      const selectedBody = document.createElement('div'); selectedBody.className = 'usage-bound-background-body';
      const selectedLabel = document.createElement('b'); selectedLabel.textContent = need.selected_label || need.aa_key;
      const selectedMeta = document.createElement('small'); selectedMeta.className = 'dim';
      selectedMeta.textContent = need.aa_key + ' · ' + (need.source === 'official' ? 'AA 官方背景' : '本剧情自定义背景');
      selectedBody.append(selectedLabel, selectedMeta); selected.append(selectedBody); card.appendChild(selected);
    }
    if (need.reason) { const reason = document.createElement('p'); reason.className = 'usage-need-reason'; reason.textContent = need.reason; card.appendChild(reason); }
    if (need.evidence && need.evidence !== segment.evidence) { const source = document.createElement('p'); source.className = 'usage-need-evidence dim'; source.textContent = '证据：' + need.evidence; card.appendChild(source); }
    const candidates = Array.isArray(need.candidates) ? need.candidates : [];
    if (need.kind === 'background' && ['recommended', 'approximate'].includes(need.status) && candidates.length) {
      const candidateList = document.createElement('div'); candidateList.className = 'usage-candidates';
      candidates.forEach(function (candidate) {
        const option = document.createElement('div'); option.className = 'usage-candidate';
        let preview;
        if (candidate.preview_available) {
          preview = document.createElement('img'); preview.className = 'usage-candidate-preview'; preview.loading = 'lazy'; preview.alt = (candidate.label || candidate.aa_key || '背景') + ' 预览'; preview.src = candidate.preview_source === 'story' ? '/api/story/assets/preview?story_token=' + encodeURIComponent((currentStory() || {}).story_token || '') + '&kind=background&key=' + encodeURIComponent(candidate.aa_key) : '/thumb/bg/' + encodeURIComponent(candidate.aa_key) + '?px=240';
        } else {
          preview = document.createElement('span'); preview.className = 'usage-candidate-placeholder'; preview.textContent = '暂无预览';
        }
        const body = document.createElement('div'); body.className = 'usage-candidate-body';
        const label = document.createElement('b'); label.textContent = candidate.label || candidate.aa_key;
        const candidateConfidence = Number(candidate.confidence);
        const key = document.createElement('small'); key.className = 'dim'; key.textContent = candidate.aa_key + (Number.isFinite(candidateConfidence) ? ' · 匹配 ' + Math.round(candidateConfidence * 100) + '%' : '');
        const difference = document.createElement('p'); difference.textContent = candidate.reason || '与当前场景语义接近。';
        const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'ghost'; apply.dataset.usageAction = 'apply-candidate'; apply.textContent = '采用此背景'; apply.addEventListener('click', function () { return applyUsageBackgroundCandidate(segment, need, candidate, apply); });
        body.append(label, key, difference, apply); option.append(preview, body); candidateList.appendChild(option);
      });
      card.appendChild(candidateList);
    }
    if (shouldOfferCustomBackground(need)) card.appendChild(customBackgroundWorkflow(segment, need));
    const actions = document.createElement('div'); actions.className = 'usage-need-actions';
    if (need.status === 'missing' && need.kind === 'sound' && window.openAssetWorkbench) {
      const workbench = document.createElement('button'); workbench.type = 'button'; workbench.className = 'ghost'; workbench.textContent = '可选补充';
      workbench.addEventListener('click', function () { openPreflightAssetWorkbench(need.kind, workbench); }); actions.appendChild(workbench);
    }
    if (need.status === 'unsupported' && need.kind === 'bgm') {
      const note = document.createElement('span'); note.className = 'usage-need-note'; note.textContent = '可直接跳过；当前版本暂不登记自定义 BGM。'; actions.appendChild(note);
    }
    if (actions.children.length) card.appendChild(actions);
    return card;
  }
  function renderUsageChain(result) {
    const root = $('#preflightScenePlan');
    if (!root) return;
    clearElement(root);
    const incomplete = !result || result.ai_status !== 'completed' || result.usage_chain_status === 'unavailable';
    if (incomplete) {
      const message = document.createElement('p'); message.className = 'usage-chain-state usage-chain-unavailable';
      message.textContent = structuredOutputPending(result)
        ? 'AI 已响应，但初审结果格式尚未整理完成。当前先显示规则分析结果；这不代表剧本错误，背景、BGM 和音效需求将在结果整理完成后显示。'
        : 'AI 演出规划未完成，当前先显示规则分析结果；这不代表剧本错误，背景、BGM 和音效需求将在 AI 初审完成后显示。';
      root.appendChild(message);
      syncDefaultBackgroundFromUsageChain(result);
      return;
    }
    const chain = Array.isArray(result.usage_chain) ? result.usage_chain : [];
    if (!chain.length) {
      const message = document.createElement('p'); message.className = 'usage-chain-state dim';
      message.textContent = 'AI 未识别到明确的场景演出需求。';
      root.appendChild(message);
      syncDefaultBackgroundFromUsageChain(result);
      return;
    }
    chain.forEach(function (segment) {
      const details = document.createElement('details'); details.className = 'usage-scene'; details.open = true;
      const summary = document.createElement('summary');
      const title = document.createElement('span'); title.className = 'usage-scene-title'; title.textContent = (segment.segment || '场景') + (segment.location ? ' · ' + segment.location : '');
      const rangeText = [segment.start, segment.end].map(compactUsageMarker).filter(Boolean).join(' → ');
      const range = document.createElement('span'); range.className = 'usage-scene-range'; range.textContent = rangeText;
      summary.appendChild(title); if (rangeText) summary.appendChild(range); details.appendChild(summary);
      if (segment.evidence) {
        const evidence = document.createElement('p'); evidence.className = 'usage-evidence'; evidence.textContent = '原文证据：' + segment.evidence; details.appendChild(evidence);
      }
      const needs = document.createElement('div'); needs.className = 'usage-needs';
      const segmentNeeds = Array.isArray(segment.needs) ? segment.needs : [];
      segmentNeeds.filter(function (need) { return !['sound', 'bgm'].includes(need.kind); }).forEach(function (need) { needs.appendChild(usageNeedCard(segment, need)); });
      const optionalNeeds = segmentNeeds.filter(function (need) { return ['sound', 'bgm'].includes(need.kind); });
      if (optionalNeeds.length) {
        const optional = document.createElement('details'); optional.className = 'usage-optional'; optional.open = false;
        const optionalSummary = document.createElement('summary'); optionalSummary.textContent = '可选演出增强（' + optionalNeeds.length + '）';
        const optionalList = document.createElement('div'); optionalList.className = 'usage-optional-list';
        optionalNeeds.forEach(function (need) { optionalList.appendChild(usageNeedCard(segment, need)); });
        optional.append(optionalSummary, optionalList); needs.appendChild(optional);
      }
      details.appendChild(needs); root.appendChild(details);
    });
    syncDefaultBackgroundFromUsageChain(result);
  }
  function characterInitial(value) {
    const text = String(value || '').trim();
    return text ? Array.from(text)[0] : '?';
  }
  function characterAvatar(item, className) {
    const data = item || {};
    const wrapper = document.createElement('span');
    wrapper.className = className || 'cast-avatar';
    wrapper.setAttribute('aria-hidden', 'true');
    const fallback = function () {
      clearElement(wrapper);
      const initial = document.createElement('span');
      initial.className = 'cast-avatar-fallback';
      initial.textContent = characterInitial(data.name || data.ident || data.speaker);
      wrapper.appendChild(initial);
    };
    if (data.avatar) {
      const image = document.createElement('img');
      image.loading = 'lazy';
      image.alt = (data.name || data.ident || data.speaker || '角色') + '头像';
      image.src = data.avatar;
      image.addEventListener('error', fallback);
      wrapper.appendChild(image);
    } else fallback();
    return wrapper;
  }
  function isCustomCharacter(item) {
    const source = String(item && item.source || '').toLowerCase();
    return Boolean(item && item.custom) || source === 'custom' || source === 'current_story_custom';
  }
  async function hydratePreflightCharacters(result) {
    const characters = Array.isArray(result && result.characters) ? result.characters : [];
    const lookups = characters.filter(function (item) {
      return item && item.kind === 'portrait' && item.id && !item.avatar;
    });
    if (!lookups.length) return result;
    const cache = Object.create(null);
    let storyAssets = null;
    let storyAssetsPromise = null;
    const story = currentStory();
    async function loadStoryAssets() {
      if (storyAssets !== null || !story) return storyAssets;
      if (!storyAssetsPromise) storyAssetsPromise = request('/api/story/assets?story_token=' + encodeURIComponent(story.story_token)).catch(function () { return {}; });
      storyAssets = await storyAssetsPromise;
      return storyAssets;
    }
    await Promise.all(lookups.map(async function (item) {
      const key = String(item.id || item.name || '').trim();
      if (!key || cache[key]) return;
      try {
        const candidates = await request('/api/characters?q=' + encodeURIComponent(key));
        const chooseCandidate = function (items, requireAvatar) {
          if (!Array.isArray(items)) return null;
          const preferred = [
            items.find(function (candidate) { return String(candidate.ident || '') === String(item.id); }),
            items.find(function (candidate) { return String(candidate.name || '') === String(item.name || ''); }),
            items[0],
          ].filter(Boolean);
          return requireAvatar
            ? preferred.find(function (candidate) { return Boolean(candidate.avatar); }) || items.find(function (candidate) { return Boolean(candidate.avatar); }) || null
            : preferred[0] || null;
        };
        let match = chooseCandidate(candidates, false);
        const name = String(item.name || '').trim();
        if ((!match || !match.avatar) && name && name !== key) {
          const namedCandidates = await request('/api/characters?q=' + encodeURIComponent(name));
          const namedMatch = chooseCandidate(namedCandidates, true);
          if (namedMatch) match = namedMatch;
        }
        if (match) cache[key] = match;
        const assets = await loadStoryAssets();
        const custom = (assets && Array.isArray(assets.characters) ? assets.characters : []).find(function (candidate) {
          return String(candidate.aa_key || '') === String(item.id || '') || String(candidate.name || '') === String(item.name || '');
        });
        if (custom) cache[key] = Object.assign({}, cache[key] || {}, {
          avatar: custom.preview_available && story
            ? '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=character&key=' + encodeURIComponent(custom.aa_key || item.id || '')
            : '',
          source: 'current_story_custom',
          faces: Array.isArray(custom.faces) ? custom.faces.length : custom.faces,
        });
      } catch (_) {}
    }));
    characters.forEach(function (item) {
      const match = cache[String(item.id || item.name || '').trim()];
      if (!match) return;
      ['avatar', 'source', 'club', 'faces', 'spine'].forEach(function (field) {
        if (match[field] !== undefined && match[field] !== null && match[field] !== '') item[field] = match[field];
      });
      item.custom = isCustomCharacter(item);
    });
    return result;
  }
  function renderPreflight(result) {
    state.preflight = result || null;
    const root = $('#s2preflight');
    if (!root || !result) return;
    if (result.analysis && Array.isArray(result.analysis.speakers) && state.analysis) {
      state.analysis = Object.assign({}, state.analysis, result.analysis, {path: state.analysis.path});
    }
    root.classList.remove('off');
    if (!state.preflightApproved) setWorkflowStage('preflight');
    const statusEl = $('#preflightStatus');
    const statusLabel = result.ai_status === 'completed' ? 'AI 已完成' : structuredOutputPending(result) ? 'AI 已响应，结果待整理' : result.ai_status === 'failed' ? 'AI 初审未完成' : '等待 AI 初审';
    statusEl.textContent = statusLabel;
    const issues = Array.isArray(result.issues) ? result.issues.filter(function (item) {
      if (!item) return false;
      if (item.code === 'speaker_unmapped') { const speaker = item.speaker || ((String(item.message || '').match(/“([^”]+)”/) || [])[1] || ''); const mapping = state.mapping[speaker]; return !mapping || !mapping.kind || mapping.kind === 'unset'; }
      return true;
    }) : [];
    result.issues = issues;
    renderUsageChain(result);
    const errors = issues.filter(function (item) { return item && item.severity === 'error'; });
    const summary = $('#preflightSummary'); clearElement(summary);
    const planningIncomplete = result.ai_status !== 'completed' || result.usage_chain_status === 'unavailable';
    const summaryText = document.createElement('p');
    summaryText.className = errors.length ? 'preflight-summary-error' : planningIncomplete ? 'preflight-summary-warning' : 'preflight-summary-ok';
    summaryText.textContent = errors.length
      ? ('发现 ' + errors.length + ' 项需要先处理；处理后可再次确认。')
      : planningIncomplete
        ? (structuredOutputPending(result)
          ? '规则分析已完成，但 AI 已响应的初审结果格式尚未整理完成；当前显示的是规则分析结果，不代表剧本错误。背景、BGM 和音效需求将在结果整理完成后显示。'
          : '规则分析已完成，但 AI 演出规划未完成；当前显示的是规则分析结果，不代表剧本错误。背景、BGM 和音效需求将在 AI 初审完成后显示。')
        : '未发现阻塞问题，可以检查并确认角色映射和演出规划。';
    summary.appendChild(summaryText);
    const format = result.analysis && result.analysis.format;
    if (format && format.label) { const formatText = document.createElement('p'); formatText.className = 'preflight-format dim'; formatText.textContent = '剧本格式：' + format.label + ' · ' + (format.message || '已完成结构识别。'); summary.appendChild(formatText); }
    const castRoot = $('#preflightCast'); clearElement(castRoot);
    (result.characters || []).forEach(function (item) {
      const row = document.createElement('div'); row.className = 'preflight-row preflight-cast-row';
      row.appendChild(characterAvatar({name: item.name || item.speaker, ident: item.id, speaker: item.speaker, avatar: item.avatar}, 'preflight-avatar'));
      const main = document.createElement('div'); main.className = 'preflight-row-main';
      const name = document.createElement('b'); name.textContent = item.speaker || '未命名说话者'; main.appendChild(name);
      const map = document.createElement('span'); map.className = 'dim'; map.textContent = item.kind === 'narrator' ? '旁白' : item.kind === 'unset' ? '未指定' : ((item.name || item.id || '未命名角色') + (item.custom ? ' · 本章自定义骨骼' : item.kind === 'portrait' ? ' · AA 骨骼角色' : ' · 语音角色')); main.appendChild(map);
      const reason = document.createElement('small'); reason.textContent = item.reason || ''; main.appendChild(reason);
      row.appendChild(main);
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'ghost'; edit.textContent = '修改'; edit.addEventListener('click', function () { openCastPicker(item.speaker); }); row.appendChild(edit); castRoot.appendChild(row);
    });
    if (!(result.characters || []).length) castRoot.appendChild(document.createElement('p')).textContent = '没有识别到说话者。';
    const assetRoot = $('#preflightAssets'); clearElement(assetRoot);
    const visibleAssets = (result.assets || []).filter(function (item) {
      return !(item && item.detected_by === 'ai' && ['sound', 'bgm'].includes(item.kind));
    });
    visibleAssets.forEach(function (item) {
      const row = document.createElement('div'); row.className = 'preflight-row preflight-asset-row ' + (item.status === 'missing' ? 'is-missing' : 'is-ready');
      const assetStatus = item.status === 'missing' ? '待补'
        : item.status === 'builtin' ? 'AA 内置可用'
          : item.status === 'recommended' ? '高匹配候选'
            : item.status === 'approximate' ? '近似候选'
              : '本章已登记';
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
        const history = document.createElement('button'); history.type = 'button'; history.className = 'ghost'; history.textContent = '从历史导入'; history.addEventListener('click', function () { window.HistoryDrawer.open({kind: item.kind, trigger: history, onApplied: function () { return rerunPreflight(); }}); }); row.appendChild(history);
      }
      assetRoot.appendChild(row);
    });
    if (!visibleAssets.length) {
      assetRoot.appendChild(document.createElement('p')).textContent = planningIncomplete
        ? (structuredOutputPending(result)
          ? 'AI 已响应，但初审结果格式尚未整理完成；当前先保留规则分析结果。'
          : 'AI 演出规划未完成，当前先保留规则分析结果；背景、BGM 和音效需求将在 AI 初审完成后显示。')
        : 'AI 未识别到需要补充的背景、BGM 或音效。';
    }
    const issueRoot = $('#preflightIssues'); clearElement(issueRoot);
    const visibleIssues = issues.filter(function (item) { return item.code !== 'optional_asset_suggestion'; });
    visibleIssues.forEach(function (item) { const row = document.createElement('div'); row.className = 'preflight-issue ' + (item.severity === 'error' ? 'is-error' : 'is-warning'); const message = document.createElement('b'); message.textContent = (item.severity === 'error' ? '需要处理：' : '提示：') + (item.message || '未命名问题'); const action = document.createElement('span'); action.textContent = item.action || ''; row.append(message, action); issueRoot.appendChild(row); });
    if (result.ai_diagnostics && result.ai_diagnostics.message) {
      const diagnostic = document.createElement('details'); diagnostic.className = 'preflight-issue is-warning preflight-diagnostic';
      const heading = document.createElement('summary'); heading.textContent = '初审进度详情';
      const detail = document.createElement('p'); detail.textContent = (structuredOutputPending(result)
        ? 'AI 已响应，但初审结果格式尚未整理完成，系统未将其当作最终初审结果。'
        : 'AI 初审尚未完成，系统已保留规则分析结果。') + ' 技术信息：' + result.ai_diagnostics.message;
      const action = document.createElement('small'); action.textContent = '重新检查会再次请求 AI；如持续未完成，请检查模型配置。';
      diagnostic.append(heading, detail, action); issueRoot.appendChild(diagnostic);
    }
    if (!visibleIssues.length && !(result.ai_diagnostics && result.ai_diagnostics.message)) issueRoot.appendChild(document.createElement('p')).textContent = '暂无必须处理的问题。';
    $('#preflightHint').textContent = errors.length ? '请处理上方错误；素材导入或角色修改后可重新初审。' : '确认后进入生成设置。';
    $('#preflightApprove').disabled = Boolean(errors.length);
    if (state.preflightApproved) revealFormalSteps();
  }
  function revealFormalSteps() { $('#s4').classList.remove('off'); setWorkflowStage('prepare'); checkReady(); }
  async function approvePreflight() {
    if (!state.preflight) return;
    if (state.preflightStale) { $('#preflightHint').textContent = '原文已变化，请先重新初审。'; return; }
    const errors = (state.preflight.issues || []).filter(function (item) { return item && item.severity === 'error'; });
    const unmapped = (state.analysis && state.analysis.speakers || []).some(function (speaker) { const mapping = state.mapping[speaker.who]; return !mapping || !mapping.kind || mapping.kind === 'unset'; });
    if (errors.length || unmapped) { $('#preflightHint').textContent = errors.length ? '还有错误未处理，请先补齐素材或修改映射。' : '还有说话者未指定角色，请先点击“修改”。'; return; }
    state.preflightApproved = true; revealFormalSteps(); const nextStep = $('#s4'); if (nextStep.scrollIntoView) nextStep.scrollIntoView({behavior: 'smooth'}); $('#preflightHint').textContent = '初审已确认，可以继续。';
    const story = currentStory();
    if (story) {
      try { await post('/api/preflight/approve', {story_token: story.story_token, approved: true, characters: state.preflight && state.preflight.characters || []}); }
      catch (_) { $('#preflightHint').textContent = '初审已确认，但本次确认状态未能保存；重新打开后可能需要再次确认。'; }
    }
  }
  async function runPreflight(op, storyToken) {
    const story = currentStory();
    if (!story) return null;
    try {
      const response = await post('/api/preflight', {story_token: story.story_token, model_profile_id: legacyModelProfileId()});
      if (response && response.job_id) {
        const job = await window.Api.poll('/api/jobs/' + response.job_id, function (item) { return ['succeeded', 'failed', 'cancelled'].includes(item.state); }, {isCurrent: function () { return isCurrentOperation('analyze', op) && currentStory() && currentStory().story_token === storyToken; }, onRetry: function () { if (isCurrentOperation('analyze', op)) { $('#preflightStatus').textContent = '连接中断，正在重试'; setScriptScanProgress('ai', 'AI 初审连接中断，正在重试…'); } }});
        if (!job || job.state !== 'succeeded') throw new Error((job && job.error) || (job && job.state === 'cancelled' ? '初审任务已取消' : '初审任务未完成'));
        const result = job.result || {};
        applyPreflightMapping(result); await hydratePreflightCharacters(result); renderPreflight(result); return result;
      }
      if (response && Array.isArray(response.characters)) { applyPreflightMapping(response); await hydratePreflightCharacters(response); renderPreflight(response); return response; }
      // 兼容尚未实现初审端点的旧后端；新版后端始终返回 job_id。
      state.preflightApproved = true;
      return null;
    } catch (error) {
      const result = fallbackPreflight(error); renderPreflight(result); return result;
    }
  }
  async function rerunPreflight() {
    const story = currentStory();
    if (!story || !state.analysis) return null;
    const op = beginOperation('analyze');
    state.preflightApproved = false;
    state.preflightStale = false;
    ['#s4'].forEach(function (id) { $(id).classList.add('off'); });
    setWorkflowStage('preflight');
    $('#preflightRerun').disabled = true;
    $('#preflightStatus').textContent = '正在重新初审…'; setScriptScanProgress('ai', 'AI 正在重新通读全文并核对素材…');
    checkReady();
    try {
      const result = await runPreflight(op, story.story_token);
      if (result) { renderPreflight(result); finishPreflightProgress(result); }
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
      $('#s2preflight').classList.remove('off'); ['#s4'].forEach(function (id) { $(id).classList.add('off'); });
      setWorkflowStage('preflight');
      if ($('#s2preflight').scrollIntoView) $('#s2preflight').scrollIntoView({behavior: 'smooth', block: 'start'});
      state.mapping = await request('/api/guess?' + sourceQuery); if (!isCurrentOperation('analyze', op) || !currentStory() || currentStory().story_token !== storyToken) return; setScriptScanProgress('ai', 'AI 正在通读全文，核对角色、骨骼和素材…', false, 3); const preflight = await runPreflight(op, storyToken); if (!isCurrentOperation('analyze', op)) return; if (!preflight) { state.preflightApproved = true; revealFormalSteps(); } finishPreflightProgress(preflight, result); checkReady();
    } catch (error) { if (isCurrentTransition(transition) && (!op || isCurrentOperation('analyze', op))) { setScriptScanProgress('ai', '读取或初审失败：' + error.message, true); $('#s1info').textContent = error.message; } }
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
    const current = (state.mapping && state.mapping[castPickerSpeaker]) || ((state.preflight && state.preflight.characters || []).find(function (item) { return item.speaker === castPickerSpeaker; }) || {});
    const groups = [
      {key: 'custom', label: '自定义骨骼', items: items.filter(isCustomCharacter)},
      {key: 'official', label: '官方骨骼', items: items.filter(function (item) { return !isCustomCharacter(item); })},
    ];
    groups.forEach(function (group) {
      if (!group.items.length) return;
      const heading = document.createElement('div'); heading.className = 'cast-group-heading'; heading.dataset.castGroup = group.key; heading.textContent = group.label;
      root.appendChild(heading);
      group.items.forEach(function (item) {
        const selected = String(current.id || '') === String(item.ident || '');
        const row = document.createElement('button'); row.type = 'button'; row.className = 'cast-result' + (selected ? ' is-selected' : ''); row.dataset.ident = item.ident || ''; row.setAttribute('aria-pressed', selected ? 'true' : 'false');
        row.appendChild(characterAvatar({name: item.name || item.ident, ident: item.ident, avatar: item.avatar}, 'cast-avatar'));
        const body = document.createElement('span'); body.className = 'cast-result-body';
        const name = document.createElement('b'); name.textContent = item.name || item.ident;
        const meta = document.createElement('span'); meta.className = 'cast-result-meta'; meta.textContent = [item.club, item.ident, item.spine ? item.spine.split('/').pop() : '', item.faces ? item.faces + ' 表情' : ''].filter(Boolean).join(' · ');
        body.append(name, meta); row.appendChild(body);
        row.addEventListener('click', function () { pickCharacter(item); });
        root.appendChild(row);
      });
    });
  }
  function pickCharacter(item) {
    const who = castPickerSpeaker;
    if (!who) return;
    state.mapping[who] = {kind: 'portrait', id: item.ident, name: item.name || item.ident, spine: item.spine || '', source: item.source || '', avatar: item.avatar || ''};
    if (state.preflight) {
      const target = (state.preflight.characters || []).find(function (row) { return row.speaker === who; });
      if (target) { target.kind = 'portrait'; target.id = item.ident; target.name = item.name || item.ident; target.spine = item.spine || ''; target.source = item.source || ''; target.avatar = item.avatar || ''; target.club = item.club || ''; target.faces = item.faces || 0; target.custom = isCustomCharacter(item); target.reason = '用户已手动修改映射。'; }
      renderPreflight(state.preflight);
    }
    closeModal('#mCast');
  }
  function castSetKind(kind) {
    const who = castPickerSpeaker;
    if (!who) return;
    if (kind === 'narrator') state.mapping[who] = {kind: 'narrator'};
    else delete state.mapping[who];
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
  function clearDiscoveredModels() {
    const root = $('#modelDiscoveryList');
    if (!root) return;
    state.discoveredModelCapabilities = [];
    clearElement(root); root.hidden = true;
  }
  function normalizeDiscoveredModel(model) {
    if (typeof model === 'string') {
      return {model_id: model, max_output_tokens: null, source: 'unknown', source_label: '上限未识别', source_url: '', verified_at: '', context_length: null};
    }
    model = model || {};
    return {
      model_id: String(model.model_id || model.id || '').trim(),
      max_output_tokens: Number(model.max_output_tokens || 0) || null,
      source: model.source || 'unknown',
      source_label: model.source_label || '上限未识别',
      source_url: model.source_url || '',
      verified_at: model.verified_at || '',
      context_length: Number(model.context_length || 0) || null
    };
  }
  function currentOutputLimitState() {
    const input = $('#modelMaxTokens');
    return {
      value: input.value,
      source: input.dataset.source || 'legacy',
      recommended: Number(input.dataset.recommended || 0) || null,
      recommendationSource: input.dataset.recommendationSource || 'unknown',
      recommendationLabel: input.dataset.recommendationLabel || '上限未识别'
    };
  }
  function renderOutputLimitState(next, modelId) {
    const input = $('#modelMaxTokens');
    next = next || {};
    if (next.value !== undefined && next.value !== null) input.value = next.value;
    input.dataset.source = next.source || 'unknown';
    if (next.recommended) input.dataset.recommended = next.recommended;
    else delete input.dataset.recommended;
    input.dataset.recommendationSource = next.recommendationSource || 'unknown';
    input.dataset.recommendationLabel = next.recommendationLabel || '上限未识别';
    if (modelId !== undefined) input.dataset.model = modelId || '';
    const hint = $('#modelMaxTokensHint');
    if (hint) hint.textContent = input.dataset.source === 'manual' ? '手动设置' : input.dataset.recommendationLabel;
    const restore = $('#modelRestoreMaxTokens');
    if (restore) restore.hidden = !(input.dataset.source === 'manual' && Number(input.dataset.recommended || 0));
  }
  function renderReasoningCapability() {
    const select = $('#modelReasoningMode');
    if (!select || !window.ModelSettings || !window.ModelSettings.reasoningCapability) return;
    const capability = window.ModelSettings.reasoningCapability($('#modelName').value, $('#modelServicePreset').value);
    const current = select.value;
    clearElement(select);
    const options = [];
    if (capability.toggle) options.push(['speed', '速度（关闭思考）']);
    if (capability.efforts.indexOf('low') >= 0) options.push(['low', '低（开启思考）']);
    if (capability.efforts.indexOf('medium') >= 0) options.push(['balanced', '均衡（开启思考）']);
    if (capability.efforts.indexOf('high') >= 0) options.push(['deep', '深入（开启思考）']);
    if (!options.length) options.push(['provider_default', '供应商默认']);
    options.forEach(function (entry) { const option = document.createElement('option'); option.value = entry[0]; option.textContent = entry[1]; select.appendChild(option); });
    select.value = options.some(function (entry) { return entry[0] === current; }) ? current : options[0][0];
    const hint = $('#modelReasoningHint');
    if (hint) hint.textContent = capability.toggle ? '默认开启思考；速度模式会关闭思考，复杂场景质量可能下降。' : '此模型未确认支持关闭或调节思考，使用供应商默认行为。';
  }
  function applyOutputCapability(capability, options) {
    options = options || {};
    const next = window.ModelSettings.nextOutputLimitState(currentOutputLimitState(), capability, options);
    renderOutputLimitState(next, options.modelId);
    return next;
  }
  function renderDiscoveredModels(models) {
    const root = $('#modelDiscoveryList');
    if (!root) return;
    clearElement(root);
    state.discoveredModelCapabilities = (models || []).map(normalizeDiscoveredModel).filter(function (model) { return model.model_id; });
    state.discoveredModelCapabilities.forEach(function (model, index) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'ghost model-discovery-option';
      button.textContent = model.model_id; button.dataset.model = model.model_id; button.dataset.modelIndex = String(index);
      button.dataset.action = 'choose-discovered-model'; button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', String($('#modelName').value === model.model_id));
      root.appendChild(button);
    });
    root.hidden = !root.children.length;
  }
  function chooseDiscoveredModel(target) {
    const capability = state.discoveredModelCapabilities[Number(target.dataset.modelIndex)] || state.discoveredModelCapabilities.find(function (item) { return item.model_id === target.dataset.model; });
    if (!capability || !capability.model_id) return;
    const previousModel = $('#modelName').value;
    $('#modelName').value = capability.model_id;
    applyOutputCapability(capability, {modelChanged: previousModel !== capability.model_id, modelId: capability.model_id});
    Array.prototype.forEach.call($('#modelDiscoveryList').children, function (option) {
      option.setAttribute('aria-selected', String(option === target));
    });
    $('#modelStatus').textContent = '已选择 ' + capability.model_id + '。';
  }
  async function recommendOutputForModel(modelId, options) {
    modelId = String(modelId || '').trim();
    if (!modelId) return;
    options = Object.assign({}, options || {}, {modelId: modelId});
    const discovered = state.discoveredModelCapabilities.find(function (item) { return item.model_id === modelId; });
    if (discovered) return applyOutputCapability(discovered, options);
    const capability = await post('/api/llm/models/recommend', {model: modelId, service_preset: $('#modelServicePreset').value || 'custom'});
    return applyOutputCapability(capability, options);
  }
  function modelPresets() {
    const remote = state.modelWorkbench && state.modelWorkbench.presets;
    if (!remote || !Object.keys(remote).length) return MODEL_PRESETS.slice();
    const byKey = remote;
    const ordered = MODEL_PRESETS.map(function (fallback) {
      return Object.assign({}, fallback, byKey[fallback.key] || {}, {key: fallback.key});
    });
    Object.keys(byKey).forEach(function (key) {
      if (!ordered.some(function (item) { return item.key === key; })) ordered.push(Object.assign({key: key}, byKey[key]));
    });
    return ordered;
  }
  function presetByKey(key) { return modelPresets().find(function (preset) { return preset.key === key; }); }
  function renderProviderLinks(preset) {
    preset = preset || {};
    const official = $('#modelProviderOfficial'), keyLink = $('#modelProviderApiKey');
    official.hidden = !preset.official_url; official.href = preset.official_url || '#';
    keyLink.hidden = !preset.api_key_url; keyLink.href = preset.api_key_url || '#';
  }
  function renderProviderCatalog() {
    const root = $('#modelProviderCatalog'), template = $('#modelProviderCardTemplate');
    if (!root || !template) return;
    clearElement(root);
    modelPresets().filter(function (preset) { return preset.key !== 'custom'; }).forEach(function (preset) {
      const card = template.content.firstElementChild.cloneNode(true);
      card.dataset.preset = preset.key;
      card.querySelector('.model-provider-mark').textContent = String(preset.label || preset.key).slice(0, 1).toUpperCase();
      card.querySelector('b').textContent = preset.label || preset.key;
      card.querySelector('.model-provider-copy>span').textContent = preset.base_url || '';
      const official = card.querySelector('[data-action="open-provider-site"]');
      official.href = preset.official_url || '#'; official.hidden = !preset.official_url;
      const keyLink = card.querySelector('.provider-key-link');
      keyLink.href = preset.api_key_url || '#'; keyLink.hidden = !preset.api_key_url;
      card.querySelector('[data-action="use-provider-preset"]').dataset.preset = preset.key;
      root.appendChild(card);
    });
  }
  function renderModelFilters() {
    const select = $('#modelSelectionProvider'); if (!select || !state.modelWorkbench) return;
    const selected = select.value; clearElement(select);
    const all = document.createElement('option'); all.value = ''; all.textContent = '全部供应商'; select.appendChild(all);
    (state.modelWorkbench.connections || []).forEach(function (connection) {
      const option = document.createElement('option'); option.value = connection.id; option.textContent = connection.name; select.appendChild(option);
    });
    select.value = selected;
  }
  function renderModelWorkbench(statePayload) {
    state.modelWorkbench = statePayload || null;
    if (!statePayload || !statePayload.assignments) return;
    const connections = statePayload.connections || [];
    const displayConnection = function (connection) {
      if (!connection) return '';
      return window.ModelSettings && window.ModelSettings.connectionDisplayName
        ? window.ModelSettings.connectionDisplayName(connection, statePayload.presets || {})
        : connection.name;
    };
    const models = (statePayload.models || []).map(function (model) {
      const connection = connections.find(function (item) { return item.id === model.connection_id; });
      return Object.assign({}, model, {connection_name: displayConnection(connection), provider: connection && connection.id});
    });
    state.modelWorkbench.models = models;
    const byId = function (id) { return models.find(function (item) { return item.id === id; }); };
    const base = byId(statePayload.assignments.base_model_id);
    const vision = statePayload.assignments.vision_mode === 'separate' ? byId(statePayload.assignments.vision_model_id) : (statePayload.assignments.vision_mode === 'base' ? base : null);
    const baseConnection = base && (statePayload.connections || []).find(function (item) { return item.id === base.connection_id; });
    const visionConnection = vision && (statePayload.connections || []).find(function (item) { return item.id === vision.connection_id; });
    $('#modelBaseAssignment').textContent = base ? (baseConnection ? displayConnection(baseConnection) + ' · ' : '') + base.model : '未设置';
    $('#modelBaseStatus').textContent = base ? window.ModelSettings.statusLabel('text', base.text_status) : '未设置';
    $('#modelVisionAssignment').textContent = vision ? (visionConnection ? displayConnection(visionConnection) + ' · ' : '') + vision.model : '未设置';
    $('#modelVisionStatus').textContent = vision ? window.ModelSettings.statusLabel('vision', vision.vision_status) : (statePayload.assignments.vision_mode === 'disabled' ? '已关闭' : '未设置');
    const secretState = window.ModelSettings.assignmentSecretStatus(statePayload);
    const secretBadge = $('#modelSecretStatus');
    secretBadge.textContent = secretState === 'saved' ? '密钥已保存' : (base ? '缺少密钥' : '未配置密钥');
    secretBadge.dataset.status = secretState;
    const addButton = $('[data-action="add-model"]'); if (addButton) { addButton.disabled = statePayload.compatibility_mode === 'legacy'; addButton.title = addButton.disabled ? '重新启动程序后可添加模型' : ''; }
    renderModelFilters(); renderProviderCatalog();
  }
  function renderModelSelection() {
    const root = $('#modelSelectionList'); if (!root || !state.modelWorkbench || !window.ModelSettings) return;
    clearElement(root);
    const query = $('#modelSelectionQuery').value, status = $('#modelSelectionStatus').value, provider = $('#modelSelectionProvider').value;
    const models = window.ModelSettings.filterModels(state.modelWorkbench.models || [], state.modelRole, query, provider, status);
    if (!models.length) { root.textContent = '暂无模型'; return; }
    models.forEach(function (model) {
      const row = document.createElement('div'); row.className = 'model-selection-item';
      const copy = document.createElement('div'); copy.className = 'model-selection-copy';
      const name = document.createElement('b'); name.textContent = model.model; copy.appendChild(name);
      const meta = document.createElement('span'); meta.textContent = [model.connection_name, window.ModelSettings.statusLabel(state.modelRole, state.modelRole === 'vision' ? model.vision_status : model.text_status)].filter(Boolean).join(' · '); copy.appendChild(meta);
      const actions = document.createElement('div'); actions.className = 'model-selection-actions';
      const use = document.createElement('button'); use.type = 'button'; use.className = 'ghost'; use.textContent = '使用'; use.dataset.modelId = model.id; use.dataset.profileId = model.legacy_profile_id || ''; use.dataset.action = 'choose-model';
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'ghost'; edit.textContent = '编辑'; edit.dataset.modelId = model.id; edit.dataset.action = 'edit-workbench-model'; edit.disabled = state.modelWorkbench.compatibility_mode === 'legacy';
      const assignments = state.modelWorkbench.assignments || {};
      const assigned = model.id === assignments.base_model_id || model.id === assignments.vision_model_id;
      const deleteControl = window.ModelSettings.modelDeleteControl(assigned, state.modelWorkbench.compatibility_mode === 'legacy');
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'ghost danger-text'; remove.textContent = '删除'; remove.dataset.modelId = model.id; remove.dataset.action = 'delete-workbench-model'; remove.disabled = deleteControl.disabled; remove.title = deleteControl.title;
      actions.append(use, edit, remove); row.append(copy, actions); root.appendChild(row);
    });
  }
  async function loadModelWorkbench() {
    const notice = $('#modelWorkbenchNotice');
    try {
      const result = await request('/api/llm/workbench'); renderModelWorkbench(result); notice.hidden = true; notice.textContent = '';
    } catch (error) {
      try {
        const legacy = await request('/api/llm/profiles'); renderModelWorkbench(window.ModelSettings.legacyWorkbench(legacy));
        notice.hidden = false; notice.textContent = '当前运行的是旧版服务。已显示原有模型，请重新启动程序后使用完整模型管理。';
      } catch (_) {
        notice.hidden = false; notice.textContent = '模型配置读取失败：' + (error.message || '请重新启动程序');
      }
    }
  }
  function openModelRole(target) {
    state.modelRole = target.dataset.role || 'text';
    $('#modelSelectionTitle').textContent = state.modelRole === 'vision' ? '选择图片识别模型' : '选择基础模型';
    $('#modelVisionModeActions').hidden = state.modelRole !== 'vision';
    $('#modelSelectionLayer').hidden = false; $('#modelRoleOverview').hidden = true;
    renderModelSelection();
  }
  async function chooseModel(target) {
    if (!state.modelWorkbench) return;
    if (state.modelWorkbench.compatibility_mode === 'legacy') {
      try { await post('/api/llm/profiles/activate', {id: target.dataset.profileId}); await loadModelWorkbench(); $('#modelSelectionLayer').hidden = true; $('#modelRoleOverview').hidden = false; } catch (error) { $('#modelWorkbenchNotice').hidden = false; $('#modelWorkbenchNotice').textContent = error.message; }
      return;
    }
    const assignments = Object.assign({}, state.modelWorkbench.assignments);
    if (state.modelRole === 'vision') { assignments.vision_mode = 'separate'; assignments.vision_model_id = target.dataset.modelId; }
    else assignments.base_model_id = target.dataset.modelId;
    try { await post('/api/llm/assignments/save', assignments); await loadModelWorkbench(); $('#modelSelectionLayer').hidden = true; $('#modelRoleOverview').hidden = false; } catch (error) { $('#modelStatus').textContent = error.message; }
  }
  async function saveVisionMode(mode) {
    if (!state.modelWorkbench || state.modelWorkbench.compatibility_mode === 'legacy') return;
    const assignments = Object.assign({}, state.modelWorkbench.assignments, {vision_mode: mode, vision_model_id: ''});
    try {
      await post('/api/llm/assignments/save', assignments); await loadModelWorkbench(); $('#modelSelectionLayer').hidden = true; $('#modelRoleOverview').hidden = false;
    } catch (error) {
      const notice = $('#modelWorkbenchNotice'); notice.hidden = false; notice.textContent = error.message;
    }
  }
  function renderProfile(profile) {
    profile = profile || {};
    clearDiscoveredModels();
    $('#modelProfileId').value = profile.id || '';
    $('#modelProfileName').value = profile.name || '';
    $('#modelProvider').value = profile.provider || 'openai';
    if ($('#modelServicePreset')) $('#modelServicePreset').value = profile.service_preset || 'custom';
    $('#modelBaseUrl').value = profile.base_url || '';
    $('#modelName').value = profile.model || '';
    if ($('#modelReasoningMode')) $('#modelReasoningMode').value = profile.reasoning_mode || 'balanced';
    renderOutputLimitState({
      value: profile.max_tokens || 16000,
      source: profile.max_tokens_source || 'legacy',
      recommended: profile.recommended_max_tokens || null,
      recommendationSource: profile.recommended_source || 'unknown',
      recommendationLabel: profile.recommended_label || '上限未识别'
    }, profile.model || '');
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
    renderProviderLinks(presetByKey(profile.service_preset || 'custom'));
    state.profileBaseline = modelPayload();
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
      await loadModelWorkbench();
      $('#modelConnectionEditor').hidden = true; $('#modelRoleOverview').hidden = false;
      $('#modelStatus').textContent = profile && profile.secret_status === 'saved'
        ? '配置和密钥已保存，可以开始验证连接。'
        : '配置已保存；使用接口前还需要填写 API Key。';
    } catch (error) { $('#modelStatus').textContent = error.message; }
  }
  function openProviderLayer() {
    $('#modelRoleOverview').hidden = true; $('#modelSelectionLayer').hidden = true; $('#modelConnectionEditor').hidden = true; $('#modelProviderLayer').hidden = false; renderProviderCatalog();
  }
  function openNewModelEditor(preset) {
    state.modelEditorMode = 'new';
    $('#modelProviderLayer').hidden = true; $('#modelSelectionLayer').hidden = true; $('#modelRoleOverview').hidden = true; $('#modelConnectionEditor').hidden = false;
    $('#modelConnectionId').value = ''; $('#modelRecordId').value = ''; $('#modelProfileId').value = '';
    renderProfile(window.ModelSettings.newProfileDraft());
    $('#modelServicePreset').disabled = false; $('#modelSaveAsNew').hidden = true; $('#modelEditorTitle').textContent = '添加模型'; $('#modelEditorSubtitle').textContent = '新连接';
    if (preset) { applyModelPreset(preset); $('#modelProfileName').value = preset.label; }
    $('#modelName').focus();
  }
  function editWorkbenchModel(target) {
    if (!state.modelWorkbench || state.modelWorkbench.compatibility_mode === 'legacy') return;
    const model = (state.modelWorkbench.models || []).find(function (item) { return item.id === target.dataset.modelId; });
    const connection = model && (state.modelWorkbench.connections || []).find(function (item) { return item.id === model.connection_id; });
    if (!model || !connection) return;
    state.modelEditorMode = 'edit';
    $('#modelSelectionLayer').hidden = true; $('#modelProviderLayer').hidden = true; $('#modelRoleOverview').hidden = true; $('#modelConnectionEditor').hidden = false;
    $('#modelConnectionId').value = connection.id; $('#modelRecordId').value = model.id; $('#modelProfileId').value = '';
    renderProfile({name: connection.name, provider: connection.protocol, service_preset: connection.service_preset, base_url: connection.base_url, model: model.model, max_tokens: model.max_tokens, max_tokens_source: model.max_tokens_source, recommended_max_tokens: model.recommended_max_tokens, recommended_source: model.recommended_source, recommended_label: model.recommended_label, reasoning_mode: model.reasoning_mode, vision: model.vision_status !== 'unsupported', secret_status: connection.secret_status});
    $('#modelServicePreset').disabled = true; $('#modelSaveAsNew').hidden = false; $('#modelEditorTitle').textContent = '编辑模型'; $('#modelEditorSubtitle').textContent = connection.name;
  }
  async function deleteWorkbenchModel(target) {
    if (!state.modelWorkbench || state.modelWorkbench.compatibility_mode === 'legacy') return;
    const model = (state.modelWorkbench.models || []).find(function (item) { return item.id === target.dataset.modelId; });
    if (!model) return;
    const assignments = state.modelWorkbench.assignments || {};
    if (model.id === assignments.base_model_id || model.id === assignments.vision_model_id) {
      const assignedNotice = $('#modelWorkbenchNotice'); assignedNotice.hidden = false; assignedNotice.textContent = '当前模型正在使用，请先更换';
      return;
    }
    const connectionModels = (state.modelWorkbench.models || []).filter(function (item) { return item.connection_id === model.connection_id; });
    const deleteEmptyConnection = connectionModels.length === 1;
    const prompt = deleteEmptyConnection
      ? '这是该连接下最后一个模型。删除后将同时移除供应商连接和 Windows 中保存的 API Key。确定删除“' + model.model + '”吗？'
      : '确定删除模型“' + model.model + '”吗？供应商连接和 API Key 会保留。';
    if (!window.confirm(prompt)) return;
    try {
      await post('/api/llm/models/delete', {id: model.id, delete_empty_connection: deleteEmptyConnection});
      await loadModelWorkbench(); renderModelSelection();
      const notice = $('#modelWorkbenchNotice'); notice.hidden = false; notice.textContent = deleteEmptyConnection ? '模型、空连接和对应 API Key 已删除。' : '模型已删除。';
    } catch (error) {
      const notice = $('#modelWorkbenchNotice'); notice.hidden = false; notice.textContent = error.message;
    }
  }
  async function saveWorkbenchModel() {
    const payload = modelPayload();
    $('#modelStatus').textContent = '正在安全保存模型…';
    try {
      const connection = await post('/api/llm/connections/save', {id: $('#modelConnectionId').value, name: payload.name, protocol: payload.provider, service_preset: payload.service_preset, base_url: payload.base_url, api_key: payload.api_key});
      if (connection.secret_status === 'saved') {
        $('#modelApiKey').value = '';
        $('#modelApiKey').placeholder = '已安全保存；留空则保持不变';
        $('#modelSecretStatus').textContent = '密钥已安全保存';
        $('#modelSecretStatus').dataset.status = 'saved';
        $('#modelSecretHint').textContent = '留空不会覆盖现有密钥';
        $('#modelClearKey').disabled = false;
      }
      const existing = state.modelWorkbench && (state.modelWorkbench.models || []).find(function (item) { return item.id === $('#modelRecordId').value; });
      const sameModel = existing && existing.model === payload.model;
      const model = await post('/api/llm/models/save', {id: $('#modelRecordId').value, connection_id: connection.id, model: payload.model, max_tokens: payload.max_tokens, max_tokens_source: payload.max_tokens_source, recommended_max_tokens: payload.recommended_max_tokens, recommended_source: payload.recommended_source, recommended_label: payload.recommended_label, text_status: sameModel ? existing.text_status : 'untested', vision_status: payload.vision ? (sameModel ? existing.vision_status : 'untested') : 'unsupported'});
      $('#modelConnectionId').value = connection.id; $('#modelRecordId').value = model.id; state.modelEditorMode = 'edit';
      await loadModelWorkbench(); $('#modelServicePreset').disabled = true; $('#modelSaveAsNew').hidden = false; $('#modelEditorTitle').textContent = '编辑模型'; $('#modelEditorSubtitle').textContent = connection.name;
      $('#modelStatus').textContent = connection.secret_status === 'saved' ? '模型和密钥已保存。' : '模型已保存；调用前还需要填写 API Key。';
    } catch (error) { $('#modelStatus').textContent = error.message; }
  }
  function saveProfileAsNew() {
    state.modelEditorMode = 'new'; $('#modelConnectionId').value = ''; $('#modelRecordId').value = ''; $('#modelProfileId').value = ''; $('#modelApiKey').value = '';
    $('#modelServicePreset').disabled = false; $('#modelSaveAsNew').hidden = true; $('#modelEditorTitle').textContent = '另存为新连接'; $('#modelEditorSubtitle').textContent = 'API Key 需要重新输入'; $('#modelProfileName').focus();
  }
  async function clearProfileKey() {
    const payload = modelPayload();
    const connectionId = $('#modelConnectionId').value;
    if (connectionId) {
      $('#modelStatus').textContent = '正在清除密钥…';
      try { await post('/api/llm/connections/save', {id: connectionId, name: payload.name, protocol: payload.provider, service_preset: payload.service_preset, base_url: payload.base_url, clear_secret: true}); await loadModelWorkbench(); $('#modelStatus').textContent = '密钥已清除。'; } catch (error) { $('#modelStatus').textContent = error.message; }
      return;
    }
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
    const previousModel = $('#modelName').value;
    clearDiscoveredModels();
    if ($('#modelServicePreset')) $('#modelServicePreset').value = preset.key || 'custom';
    $('#modelProvider').value = preset.provider;
    $('#modelBaseUrl').value = preset.base_url;
    $('#modelName').value = preset.model;
    $('#modelVision').checked = Boolean(preset.vision);
    renderProviderLinks(preset);
    $('#modelStatus').textContent = '已选择 ' + preset.label + '。';
    if (preset.model) recommendOutputForModel(preset.model, {modelChanged: previousModel !== preset.model}).catch(function (error) { $('#modelStatus').textContent = error.message; });
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
    try {
      const modelId = $('#modelRecordId').value;
      const result = modelId
        ? await post('/api/llm/models/test', {id: modelId, mode: mode})
        : await post('/api/llm/test', {id: $('#modelProfileId').value, profile: modelPayload(), mode: mode});
      await loadModelWorkbench();
      $('#modelStatus').textContent = (mode === 'vision' ? '图片识别可用：' : '文字连接可用：') + result.model;
    } catch (error) { $('#modelStatus').textContent = error.message; }
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

  function openGeneratedBackgroundPicker(trigger) {
    if (!state.generationPrompt || !assetFilePicker) {
      $('#generationPromptStatus').textContent = '当前剧情的图片选择功能暂不可用。';
      return null;
    }
    $('#generationPromptStatus').textContent = '请选择生成好的 PNG 或 JPG 背景图。';
    closeModal('#mGenerationPrompt');
    activeFilePicker = assetFilePicker;
    return assetFilePicker.open(trigger || $('#generationImportButton'));
  }

  async function importGeneratedBackgroundSelection(selection) {
    const need = state.generationPrompt;
    const target = state.generationPromptTarget;
    const story = currentStory();
    if (!need || !target || !story || story.story_token !== state.generationPromptStoryToken) return null;
    if (!selection || !selection.file_token) {
      $('#generationPromptStatus').textContent = '没有取得所选图片，请重新选择。';
      return null;
    }
    $('#generationPromptStatus').textContent = '正在检查并导入背景…';
    try {
      const result = await window.StoryAssets.importLocal('background', {
        name: need.name,
        fileToken: selection.file_token,
        labels: {
          label: String(need.name || ''),
          description: String(need.reason || ''),
          place: String(target.place || '')
        }
      });
      if (!result || !result.ok || !result.aa_key) {
        openModal('#mGenerationPrompt', $('#generationImportButton'));
        $('#generationPromptStatus').textContent = '背景未能导入，请检查素材工作台中的任务详情。';
        return null;
      }
      const preview = $('#generationImportPreview');
      preview.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=background&key=' + encodeURIComponent(result.aa_key);
      preview.alt = (need.name || selection.name || '已导入背景') + ' 预览';
      $('#generationImportName').textContent = need.name || result.stem || selection.name || result.aa_key;
      $('#generationImportMeta').textContent = '背景键：' + result.aa_key;
      $('#generationImportResult').hidden = false;
      let binding;
      try {
        binding = await post('/api/preflight/background-binding', {
          story_token: story.story_token,
          selector: target.selector,
          binding: {
            aa_key: String(result.aa_key),
            selected_label: String(need.name || result.stem || result.aa_key)
          }
        });
      } catch (bindingError) {
        openModal('#mGenerationPrompt', $('#generationImportButton'));
        $('#generationPromptStatus').textContent = '背景已导入，但场景绑定未保存：' + String(bindingError && bindingError.message || '请重试');
        return result;
      }
      if (binding && binding.preflight_snapshot) {
        restorePreflightSnapshot(binding.preflight_snapshot);
      }
      $('#generationPromptStatus').textContent = '已导入并登记到当前剧情。';
      state.generationPrompt = null;
      state.generationPromptTarget = null;
      state.generationPromptStoryToken = null;
      return result;
    } catch (error) {
      openModal('#mGenerationPrompt', $('#generationImportButton'));
      $('#generationPromptStatus').textContent = error && error.message ? error.message : '背景导入失败，请重试。';
      return null;
    }
  }

  function setReviewActions(enabled, bind) {
    reviewActions.forEach(function (id) { $('#' + id).disabled = !enabled || (id === 'rvBind' && !bind); });
    const toolbar = $('#rvCardToolbar');
    if (toolbar) toolbar.classList.toggle('is-hidden', !enabled);
    if (!enabled && $('#rvSelectionLabel')) $('#rvSelectionLabel').textContent = '选择卡片后可编辑';
  }
  function displayedDraftVersion(token, fallback) {
    const option = Array.prototype.find.call($('#rvDraftSelect').children, function (item) { return item.value === token; });
    return Number(option && option.dataset.generationVersion || fallback || 1);
  }
  async function refreshDrafts() {
    const story = currentStory();
    if (!story) { resetReview('请先打开剧情'); return; }
    const view = captureView(story);
    const storyToken = story.story_token; const list = await request('/api/drafts');
    if (!isCurrentView(view)) return;
    const select = $('#rvDraftSelect'); clearElement(select);
    const scoped = list.filter(function (draft) { return draftBelongsToStory(draft, story); }).sort(function (left, right) {
      const byTime = String(left.created_at || '').localeCompare(String(right.created_at || ''));
      return byTime || String(left.draft_token || '').localeCompare(String(right.draft_token || ''));
    });
    if (!scoped.length) { resetReview('当前剧情没有草稿'); return; }
    scoped.forEach(function (draft, index) { const option = document.createElement('option'); const generation = Number(draft.generation_version || index + 1); option.value = draft.draft_token; option.dataset.generationVersion = String(generation); option.textContent = (draft.project || '未命名工程') + ' · v' + generation; select.appendChild(option); });
    select.value = story.latest_draft_token || scoped[0].draft_token;
    $('#rvOpen').disabled = false;
    showReviewPhase(true);
    setWorkflowStage('review');
    status('找到 ' + scoped.length + ' 份草稿，打开后可继续审查');
    contextStatus({draft: '草稿：v' + displayedDraftVersion(select.value), save: '保存：未修改'});
  }
  function draftBelongsToStory(draft, story, requestedToken) {
    if (!draft || !story) return false;
    if (draft.story_token === story.story_token) return true;
    const draftToken = String(draft.draft_token || requestedToken || '');
    return Boolean(
      story.latest_draft_token && draftToken === story.latest_draft_token
      && String(draft.project || '') === String(story.project || '')
    );
  }
  async function loadReview(restoredCardId) {
    const story = currentStory(); const token = $('#rvDraftSelect').value; if (!story || !token) { resetReview('请先打开当前剧情的草稿'); return; } const view = captureView(story); const storyToken = story.story_token; const draft = await request('/api/draft?token=' + encodeURIComponent(token));
    if (!isCurrentView(view)) return;
    if (!draftBelongsToStory(draft, story, token)) { resetReview('草稿不属于当前剧情'); return; }
    const previousReview = state.review;
    const sameDraft = previousReview && previousReview.token === token;
    const selectedId = restoredCardId || (sameDraft && previousReview.selected ? previousReview.selected.card_id : null);
    const cards = draft.cards || [];
    const selectedCard = selectedId ? cards.find(function (card) { return card.card_id === selectedId; }) || null : null;
    const selectedIndex = selectedCard ? cards.indexOf(selectedCard) : -1;
    const baseCardLimit = sameDraft ? previousReview.cardLimit || 80 : 80;
    state.review = {token: token, revision: draft.draft_version, buildId: draft.last_compiled_build_id || null, cards: cards, selected: selectedCard, filter: sameDraft ? previousReview.filter || 'all' : 'all', cardLimit: Math.max(baseCardLimit, selectedIndex + 1)}; const counts = draft.counts || {};
    showReviewPhase(true); setWorkflowStage('review'); $('#rvOpen').disabled = false;
    contextStatus({draft: '草稿：v' + displayedDraftVersion(token, draft.draft_version), save: '保存：未修改', review: '审查：待审 ' + (counts.pending || 0) + ' · 待处理 ' + (counts.blocking_errors || 0), compile: state.review.buildId ? '编译：已完成' : '编译：未编译', install: draft.last_installed_build_id ? ('安装：已安装' + (draft.last_installed_project ? ' · ' + draft.last_installed_project : '')) : '安装：未安装'});
    status('待审 ' + (counts.pending || 0) + ' · 待处理 ' + (counts.blocking_errors || 0) + ' · v' + displayedDraftVersion(token, draft.draft_version)); $('#rvApproveAll').disabled = false; $('#rvValidate').disabled = false; $('#rvCompile').disabled = Boolean(counts.pending || counts.blocking_errors); $('#rvInstall').disabled = !state.review.buildId; setReviewActions(Boolean(state.review.selected), Boolean(state.review.selected && state.review.selected.kind === 'line'));
    if (state.review.selected) $('#rvSelectionLabel').textContent = '已选 #' + state.review.selected.line_no;
    rememberActiveReview({story_token: story.story_token, draft_token: token, card_id: state.review.selected && state.review.selected.card_id});
    renderReviewCards();
    const player = ensurePlayer(); if (player) player.loadCards(state.review.cards);
    if (state.review.selected) {
      selectCard(state.review.selected);
      if (restoredCardId) $('#rvSelectionLabel').textContent = '已选 #' + state.review.selected.line_no;
    }
    else if (state.review.cards.length) selectCard(state.review.cards[0]);
    renderReviewAssets();
    renderBackgroundTimeline({characters: [], backgrounds: [], sounds: [], bgms: []});
  }
  function renderReviewCards() {
    const all = state.review && state.review.cards ? state.review.cards : [];
    const filtered = all.filter(function (card) { return cardMatchesReviewFilter(card, state.review.filter); });
    const limit = state.review.cardLimit || 80;
    const shown = filtered.length > limit ? filtered.slice(0, limit) : filtered;
    if (window.CardList) window.CardList.renderCardList($('#rvCards'), shown, {
      onSelectCard: selectCard,
      onUseDefaultBackground: function (card) { return resolveDraftBackgroundRequest(card, 'BG_Black'); },
      onChooseBackground: openDraftBackgroundPicker,
      onFillBackground: fillBackgroundFromHistory
    });
    updateReviewFilterControls(filtered.length, all.length);
    applyCardSelection();
    if (filtered.length > shown.length) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'ghost card-list-more'; more.textContent = '显示全部 ' + all.length + ' 条';
      more.addEventListener('click', function () { state.review.cardLimit = filtered.length; renderReviewCards(); });
      $('#rvCards').appendChild(more);
    }
  }
  function cardMatchesReviewFilter(card, filter) {
    if (filter === 'pending') return card.review_state === 'pending';
    if (filter === 'blocking') return (card.issues || []).some(function (item) { return item.severity === 'error'; });
    if (filter === 'direction') return card.kind === 'dir' || card.kind === 'background_request';
    return true;
  }
  function updateReviewFilterControls(filteredCount, totalCount) {
    const ids = {all: 'rvFilterAll', pending: 'rvFilterPending', blocking: 'rvFilterBlocking', direction: 'rvFilterDirection'};
    Object.keys(ids).forEach(function (filter) {
      const button = $('#' + ids[filter]); if (!button) return;
      const active = (state.review.filter || 'all') === filter;
      button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', String(active));
    });
    const label = $('#rvFilterStatus'); if (label) label.textContent = filteredCount === totalCount ? totalCount + ' 条' : filteredCount + ' / ' + totalCount + ' 条';
  }
  function setReviewFilter(filter) {
    if (!['all', 'pending', 'blocking', 'direction'].includes(filter)) return false;
    state.review.filter = filter; state.review.cardLimit = 80;
    if (state.review.selected && !cardMatchesReviewFilter(state.review.selected, filter)) { state.review.selected = null; setReviewActions(false, false); }
    renderReviewCards();
    return true;
  }
  function jumpToReviewCard() {
    const lineNo = Number($('#rvCardJump').value);
    const card = state.review.cards.find(function (item) { return Number(item.line_no) === lineNo; });
    if (!Number.isFinite(lineNo) || !card) { status('未找到 #' + ($('#rvCardJump').value || '')); return false; }
    state.review.filter = 'all';
    state.review.cardLimit = Math.max(80, state.review.cards.indexOf(card) + 1);
    renderReviewCards(); selectCard(card);
    const target = document.querySelector ? document.querySelector('[data-card-id="' + card.card_id.replace(/"/g, '\\"') + '"]') : null;
    if (target && target.scrollIntoView) target.scrollIntoView({behavior: 'smooth', block: 'center'});
    return true;
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
      const empty = document.createElement('p'); empty.className = 'dim'; empty.textContent = '还没有自定义素材，可在“本剧情自定义素材”区导入。'; root.appendChild(empty);
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
  function selectCard(card) { state.review.selected = card; const story = currentStory(); if (story) rememberActiveReview({story_token: story.story_token, draft_token: state.review.token, card_id: card.card_id}); setReviewActions(true, card.kind === 'line'); $('#rvSelectionLabel').textContent = '已选 #' + card.line_no + ' · ' + (card.kind === 'line' ? '台词' : card.kind === 'dir' ? '指令' : '卡片'); applyCardSelection(); applyTimelineSelection(); const player = playerInstance(); if (player && typeof player.jumpToCard === 'function') player.jumpToCard(card.card_id); }
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
    const title = document.createElement('div'); title.className = 'bg-timeline-heading'; const heading = document.createElement('h3'); heading.textContent = '背景时间线'; const hint = document.createElement('span'); hint.className = 'dim'; hint.textContent = cards.length ? ('共 ' + cards.length + ' 次切换 · 点击节点跳转到对应卡片') : '本场没有背景切换'; title.appendChild(heading); title.appendChild(hint); root.appendChild(title);
    if (!cards.length) return;
    const track = document.createElement('div'); track.className = 'bg-timeline-track'; const story = currentStory();
    cards.forEach(function (card, index) {
      const custom = customBackgroundFor(card, data || {}); const node = document.createElement('article'); node.className = 'bg-timeline-node'; node.dataset.cardId = card.card_id;
      const jump = document.createElement('button'); jump.type = 'button'; jump.className = 'bg-timeline-jump'; jump.addEventListener('click', function () { selectCard(card); let target = document.querySelector ? document.querySelector('[data-card-id="' + card.card_id.replace(/"/g, '\\"') + '"]') : null; if (!target && state.review.cards && state.review.cards.length) { state.review.cardLimit = state.review.cards.length; renderReviewCards(); target = document.querySelector ? document.querySelector('[data-card-id="' + card.card_id.replace(/"/g, '\\"') + '"]') : null; } if (target && target.scrollIntoView) target.scrollIntoView({behavior: 'smooth', block: 'center'}); });
      const name = document.createElement('b'); name.textContent = card.current.arg || '未命名背景';
      const meta = document.createElement('span'); meta.className = 'dim';
      if (custom && custom.preview_available && story) {
        const img = document.createElement('img'); img.loading = 'lazy'; img.alt = custom.name || card.current.arg || '背景'; img.src = '/api/story/assets/preview?story_token=' + encodeURIComponent(story.story_token) + '&kind=background&key=' + encodeURIComponent(custom.aa_key || custom.name || ''); jump.appendChild(img); meta.textContent = '本剧情自定义';
      } else if (custom) {
        const placeholder = document.createElement('span'); placeholder.className = 'bg-timeline-placeholder'; placeholder.textContent = '无预览'; jump.appendChild(placeholder); meta.textContent = '本剧情自定义 · 暂无预览';
      } else {
        const img = document.createElement('img'); img.loading = 'lazy'; img.alt = (card.current.arg || 'AA 背景') + ' 预览';
        const placeholder = document.createElement('span'); placeholder.className = 'bg-timeline-placeholder'; placeholder.textContent = '素材缺失'; placeholder.hidden = true;
        img.addEventListener('load', function () { meta.textContent = 'AA 官方背景'; node.classList.remove('is-missing'); });
        img.addEventListener('error', function () { img.hidden = true; placeholder.hidden = false; meta.textContent = 'AA 资源中未找到此背景'; node.classList.add('is-missing'); });
        img.src = '/thumb/bg/' + encodeURIComponent(card.current.arg || '') + '?px=320';
        jump.appendChild(img); jump.appendChild(placeholder); meta.textContent = '正在检查 AA 背景预览';
      }
      jump.appendChild(name); jump.appendChild(meta); node.appendChild(jump);
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
  function openDraftBackgroundPicker(card, trigger) {
    if (!card || card.kind !== 'background_request' || !state.review.token) return;
    state.reviewBackgroundRequest = card;
    if (state.backgroundJob) state.backgroundJob.resolveRequestId = null;
    $('#backgroundPickerTitle').textContent = '选择官方背景';
    openModal('#mBackgroundPicker', trigger);
    loadBackgrounds();
  }
  async function resolveDraftBackgroundRequest(card, bgName) {
    const review = state.review;
    const view = captureView();
    if (!card || card.kind !== 'background_request' || !review.token || !card.card_id || !bgName) return null;
    try {
      const result = await request(
        '/api/drafts/' + encodeURIComponent(review.token) + '/backgrounds/' + encodeURIComponent(card.card_id) + '/resolve',
        window.Api.json('POST', {bg_name: String(bgName), expected_draft_version: review.revision})
      );
      if (!isCurrentView(view) || state.review !== review) return null;
      review.revision = result.draft_version || review.revision;
      state.reviewBackgroundRequest = null;
      await loadReview();
      if (isCurrentView(view)) {
        const merged = Number(result && result.merged_backgrounds || 0);
        status((String(bgName) === 'BG_Black' ? '已设为默认黑屏' : '背景已设置') + (merged ? ' · 已合并重复背景切换 ' + merged + ' 处' : ''));
      }
      return result;
    } catch (error) {
      if (isCurrentView(view)) status('背景设置失败：' + error.message);
      return null;
    }
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
      state.review.buildId = result.build_id; $('#rvInstall').disabled = false; status('编译成功 · ' + result.build_id + ' · 可安装'); contextStatus({compile: '编译：已完成 · ' + result.build_id});
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
      const story = requireStory(); if (!state.analysis) throw new Error('请先读取剧本');
      setBusyButton('#goAnnotate', true, useAI ? 'AI 生成中…' : '正在转换…', '生成审查草稿');
      log(useAI ? 'AI 正在安排演出并生成草稿…' : '正在按原文生成审查草稿…');
      const result = await post('/api/annotate', {story_token: story.story_token, mapping: state.mapping, bg: state.background || 'BG_Black', usage_chain: state.preflight && Array.isArray(state.preflight.usage_chain) ? state.preflight.usage_chain : [], annotate: useAI, model_profile_id: legacyModelProfileId()});
      if (!isCurrentOperation('annotate', op)) return;
      let lastAnnotationDetail = '';
      const job = await window.Api.poll('/api/jobs/' + result.job_id, function (item) { return ['succeeded', 'failed', 'cancelled'].includes(item.state); }, {isCurrent: function () { return isCurrentOperation('annotate', op); }, onProgress: function (item) { const detail = annotationProgressDetail(item); if (isCurrentOperation('annotate', op) && detail && detail !== lastAnnotationDetail) { lastAnnotationDetail = detail; log(detail); } }, onRetry: function () { if (isCurrentOperation('annotate', op)) log('连接中断，正在重试'); }});
      if (!isCurrentOperation('annotate', op) || !job) return;
      if (job.state !== 'succeeded') throw new Error(job.error || '草稿生成失败');
      await refreshDrafts(); if (!isCurrentOperation('annotate', op)) return;
      $('#rvDraftSelect').value = job.result.draft_token; await loadReview();
      if (isCurrentOperation('annotate', op)) { const resumed = Number(job.result && job.result.resumed_chunks || 0); const metrics = job.result && job.result.agent_metrics; const timedOut = Boolean(job.result && job.result.timed_out); log((timedOut ? '部分草稿已保存，当前块超时；再次生成会从检查点继续' : '草稿已生成') + (metrics ? ' · ' + formatAnnotationCompletion(metrics) : '') + (resumed ? ' · 复用 ' + resumed + ' 段' : '') + '，请完成审查后再编译安装'); if ($('#reviewPhase').scrollIntoView) $('#reviewPhase').scrollIntoView({behavior: 'smooth', block: 'start'}); }
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
  async function build() { if (state.buildActive || state.backgroundJob) return; const op = beginOperation('build'); try { const story = requireStory(); if (!state.analysis) throw new Error('请先读取剧本'); state.buildActive = true; log('启动中…'); checkReady(); await post('/api/build', {story_token: story.story_token, project: story.project, script: state.analysis.path, mapping: state.mapping, bg: state.background || 'BG_Black', annotate: $('input[name=anno]:checked').value === 'ai', model_profile_id: legacyModelProfileId(), install: $('#install').checked}); if (!isCurrentOperation('build', op)) return; return await pollBuild(op); } catch (error) { if (!isCurrentOperation('build', op)) return; state.buildActive = false; log(error.message); } finally { if (isCurrentOperation('build', op)) checkReady(); } }

  const recentStories = new window.StoryUI.RecentStories($('#recentStories'), openRecent);
  const storyFilePicker = window.StoryUI && window.StoryUI.StoryFilePicker ? new window.StoryUI.StoryFilePicker($('#mBrowse'), {title: '选择剧情文本', onChoose: openSelectedStory}) : null;
  const settingsFilePicker = window.StoryUI && window.StoryUI.StoryFilePicker ? new window.StoryUI.StoryFilePicker($('#mBrowse'), {hostEndpoint: '/api/settings/host', selectEndpoint: '/api/settings/entry', title: '选择设置路径', searchPlaceholder: '搜索文件或文件夹', emptyStatus: '这个文件夹中没有可选择的设置路径', onChoose: saveSettingsEntryAndReset}) : null;
  const assetFilePicker = window.StoryUI && window.StoryUI.StoryFilePicker ? new window.StoryUI.StoryFilePicker($('#mBrowse'), {hostEndpoint: '/api/assets/host', selectEndpoint: '/api/assets/select', allowedSuffixes: ['.png', '.jpg', '.jpeg'], title: '选择生成的背景图片', searchPlaceholder: '搜索背景图片', emptyStatus: '这个文件夹中没有可选择的 PNG 或 JPG 图片', openingStatus: '正在导入所选背景图片…', onChoose: importGeneratedBackgroundSelection}) : null;
  if (settingsFilePicker) {
    const closeSettingsPicker = settingsFilePicker.close.bind(settingsFilePicker);
    settingsFilePicker.close = function () {
      const result = closeSettingsPicker();
      activeFilePicker = storyFilePicker;
      return result;
    };
  }
  if (assetFilePicker) {
    const closeAssetPicker = assetFilePicker.close.bind(assetFilePicker);
    assetFilePicker.close = function () {
      const result = closeAssetPicker();
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
  window.Preview = window.Preview || {clear: destroyPlayer};
  window.StoryJobs = window.StoryJobs || {detachView: function () {}};
  let activeStoryToken = currentStory() && currentStory().story_token;
  window.StoryStore.subscribe(function (story) {
    $('#recentStories').classList.toggle('is-hidden', Boolean(story));
    const nextToken = story && story.story_token;
    if (nextToken !== activeStoryToken) { activeStoryToken = nextToken; resetReview(nextToken ? '正在加载当前剧情草稿' : '请先打开剧情'); }
  });
  const actions = {
    'save-spine-cli': saveSpineCli,
    'open-model-role': openModelRole,
    'choose-model': chooseModel,
    'use-base-for-vision': function () { return saveVisionMode('base'); },
    'disable-vision-model': function () { return saveVisionMode('disabled'); },
    'close-model-layer': function () { $('#modelSelectionLayer').hidden = true; $('#modelRoleOverview').hidden = false; },
    'open-help-api': function () {
      const template = $('#helpApiModelsTemplate'); const sections = $('#helpDrawer .help-sections');
      if (template && sections && !$('#helpApiModels')) sections.appendChild(template.content.cloneNode(true));
      setDrawer('help', true);
    },
    'add-model': openProviderLayer,
    'close-provider-layer': function () { $('#modelProviderLayer').hidden = true; $('#modelSelectionLayer').hidden = false; renderModelSelection(); },
    'use-provider-preset': function (target) { openNewModelEditor(presetByKey(target.dataset.preset)); },
    'use-custom-provider': function () { openNewModelEditor({key: 'custom', label: '自定义接口', provider: 'openai', base_url: '', model: '', vision: true}); },
    'edit-workbench-model': editWorkbenchModel,
    'delete-workbench-model': deleteWorkbenchModel,
    'save-workbench-model': saveWorkbenchModel,
    'save-profile-as-new': saveProfileAsNew,
    'choose-discovered-model': chooseDiscoveredModel,
    'restore-model-max-tokens': function () { renderOutputLimitState(window.ModelSettings.restoreOutputLimitState(currentOutputLimitState()), $('#modelName').value); },
    'close-model-editor': function () { $('#modelConnectionEditor').hidden = true; $('#modelProviderLayer').hidden = true; $('#modelRoleOverview').hidden = false; },
    'confirm-aa-workspace': confirmAAWorkspace,
    'build-aa-index': function () { return buildAAIndex(); },
    'browse-aa-install': function (trigger) { if (settingsFilePicker) { settingsPickerMode = 'aa'; activeFilePicker = settingsFilePicker; settingsFilePicker.openPath(trigger); } },
    'browse-spine-cli': function (trigger) { if (settingsFilePicker) { settingsPickerMode = 'spine'; activeFilePicker = settingsFilePicker; settingsFilePicker.openPath(trigger); } },
    'show-create': function () { $('#view-create').scrollIntoView({behavior: 'smooth'}); }, 'open-script': openScript, analyze: analyze, 'retry-story-load': function () { if (state.loadFailure) replaceStory(state.loadFailure.story, state.loadFailure.options); }, 'dismiss-welcome': function () { $('#welcomePanel').hidden = true; localStorage.setItem('aa-welcome-dismissed-v1', '1'); }, 'show-welcome': function () { $('#welcomePanel').hidden = false; localStorage.removeItem('aa-welcome-dismissed-v1'); }, 'open-settings': function () { setDrawer('settings', true); loadAAData(); }, 'close-settings': function () { setDrawer('settings', false); }, 'save-aa-install': function () { return saveAAInstall(); }, 'open-help': function () { setDrawer('help', true); }, 'close-help': function () { setDrawer('help', false); }, 'close-browse': function () { if (storyFilePicker) storyFilePicker.close(); else closeModal('#mBrowse'); }, 'story-picker-device': function () { if (storyFilePicker) storyFilePicker.chooseDevice(); }, 'story-picker-host': function () { if (storyFilePicker) storyFilePicker.openHost(); }, 'story-picker-refresh': function () { if (storyFilePicker) storyFilePicker.load(storyFilePicker.locationToken, false); }, 'story-picker-source': function () { if (storyFilePicker) storyFilePicker.open(storyFilePicker.trigger); }, 'choose-current-dir': chooseCurrentDirectory, 'close-cast': function () { closeModal('#mCast'); }, 'close-bg-replace': function () { closeModal('#mBgReplace'); state.bgReplaceCard = null; }, 'bg-replace-history': openBgHistory, 'approve-preflight': approvePreflight, 'rerun-preflight': rerunPreflight, 'cast-narrator': function () { castSetKind('narrator'); }, 'cast-unset': function () { castSetKind('unset'); }, 'resolve-background': function (target) { state.backgroundJob = Object.assign({}, state.backgroundJob, {resolveRequestId: target.dataset.requestId}); openModal('#mBackgroundPicker', target); loadBackgrounds(); }, 'continue-background': continueBackground, 'refresh-drafts': refreshDrafts, 'load-review': loadReview, 'approve-all': approveAll, validate: validateReview, compile: compile, install: openInstallDialog, 'confirm-install': confirmInstall, 'close-install': function () { closeModal('#mInstall'); }, 'edit-card': editCard, 'save-edit': saveEdit, 'close-edit': function () { closeModal('#mEdit'); }, 'insert-line': function () { insertCard('line'); }, 'insert-dir': function () { insertCard('dir'); }, 'move-up': function () { moveCard('up'); }, 'move-down': function () { moveCard('down'); }, 'delete-card': deleteCard, 'bind-cast': bindCast, annotate: annotate, build: build, 'new-profile': function () { renderProfile(null); }, 'activate-profile': async function () { try { await post('/api/llm/profiles/activate', {id: $('#modelProfileId').value}); await loadProfiles($('#modelProfileId').value); } catch (error) { $('#modelStatus').textContent = error.message; } }, 'delete-profile': async function () { try { await post('/api/llm/profiles/delete', {id: $('#modelProfileId').value, delete_credential: true}); await loadProfiles(); } catch (error) { $('#modelStatus').textContent = error.message; } }, 'save-profile': saveProfile, 'clear-profile-key': clearProfileKey, 'discover-models': async function () { $('#modelStatus').textContent = '正在读取可用模型…'; try { const result = await post('/api/llm/models', {id: $('#modelProfileId').value}); const list = $('#modelOptions'); clearElement(list); result.models.forEach(function (name) { const option = document.createElement('option'); option.value = name; list.appendChild(option); }); $('#modelStatus').textContent = '已读取 ' + result.models.length + ' 个模型，可在模型输入框中选择。'; } catch (error) { $('#modelStatus').textContent = error.message; } }, 'test-text': function () { testProfile('text'); }, 'test-vision': function () { testProfile('vision'); }, 'preset-openai': function () { applyModelPreset(presetByKey('openai')); }, 'preset-anthropic': function () { applyModelPreset(presetByKey('anthropic')); }, 'preset-deepseek': function () { applyModelPreset(presetByKey('deepseek')); }, 'preset-ollama': function () { applyModelPreset(presetByKey('ollama')); }, 'preset-silicon': function () { applyModelPreset(presetByKey('siliconflow')); }, 'preset-openrouter': function () { applyModelPreset(presetByKey('openrouter')); }
  };
  actions['close-browse'] = function () { if (activeFilePicker) activeFilePicker.close(); else closeModal('#mBrowse'); activeFilePicker = storyFilePicker; };
  actions['new-profile'] = openProviderLayer;
  actions['discover-models'] = async function () {
    $('#modelStatus').textContent = '正在读取可用模型…';
    clearDiscoveredModels();
    const payload = modelPayload();
    try {
      const connectionId = $('#modelConnectionId').value;
      const requestPayload = {
        connection: {
          id: connectionId,
          name: payload.name || '临时连接',
          protocol: payload.provider,
          service_preset: payload.service_preset,
          base_url: payload.base_url,
          api_key: payload.api_key
        },
        model: {model: payload.model || 'model-list', max_tokens: payload.max_tokens}
      };
      const result = await post('/api/llm/models/list', requestPayload);
      const list = $('#modelOptions'); clearElement(list); (result.models || []).map(normalizeDiscoveredModel).forEach(function (model) { const option = document.createElement('option'); option.value = model.model_id; list.appendChild(option); });
      renderDiscoveredModels(result.models);
      if (result.base_url_adjusted && result.base_url) $('#modelBaseUrl').value = result.base_url;
      $('#modelStatus').textContent = result.base_url_adjusted
        ? '已自动补全 /v1，读取 ' + result.models.length + ' 个模型。'
        : '已读取 ' + result.models.length + ' 个模型。';
    } catch (error) { $('#modelStatus').textContent = error.message; }
  };
  actions['close-background-picker'] = function () { closeModal('#mBackgroundPicker'); state.reviewBackgroundRequest = null; if (state.backgroundJob) state.backgroundJob.resolveRequestId = null; };
  actions['show-history'] = showRecentStories;
  actions['close-generation-prompt'] = function () { closeModal('#mGenerationPrompt'); state.generationPrompt = null; state.generationPromptTarget = null; state.generationPromptStoryToken = null; };
  actions['copy-install-aap'] = function () { return copyInstallAapPath(); };
  actions['copy-generation-prompt'] = function () { copyGenerationPrompt(); };
  actions['import-generation-result'] = function (trigger) {
    if (!state.generationPrompt || !window.StoryAssets || !window.StoryAssets.importLocal) {
      $('#generationPromptStatus').textContent = '当前剧情的背景导入功能暂不可用。';
      return;
    }
    return openGeneratedBackgroundPicker(trigger);
  };
  actions['story-picker-refresh'] = function () { if (activeFilePicker) activeFilePicker.load(activeFilePicker.locationToken, false); };
  actions['review-filter'] = function (target) { return setReviewFilter(target.dataset.filter); };
  actions['jump-review-card'] = jumpToReviewCard;
  document.addEventListener('click', function (event) { const sortTarget = event.target.closest('[data-story-sort]'); if (sortTarget && activeFilePicker) { activeFilePicker.sortBy(sortTarget.dataset.storySort); return; } const target = event.target.closest('[data-action]'); if (target && actions[target.dataset.action]) actions[target.dataset.action](target); });
  $('#bgq').addEventListener('input', loadBackgrounds); $('#bgready').addEventListener('change', loadBackgrounds); $('#rvDraftSelect').addEventListener('change', loadReview); $('#installCategory').addEventListener('input', updateInstallProjectPreview); $('#installStoryName').addEventListener('input', updateInstallProjectPreview);
  $('#rvCardJump').addEventListener('keydown', function (event) { if (event.key === 'Enter') jumpToReviewCard(); });
  $('#modelSelectionQuery').addEventListener('input', renderModelSelection); $('#modelSelectionProvider').addEventListener('change', renderModelSelection); $('#modelSelectionStatus').addEventListener('change', renderModelSelection);
  $('#modelProfileSelect').addEventListener('change', function () {
    const nextId = this.value;
    const baseline = state.profileBaseline;
    const changed = baseline && window.ModelSettings && window.ModelSettings.profileChanged(baseline, modelPayload());
    if (changed && !window.confirm('当前模型配置有未保存修改，是否放弃这些修改并切换？')) {
      this.value = baseline.id || '';
      return;
    }
    renderProfile(state.profiles.find(function (profile) { return profile.id === nextId; }));
  });
  $('#modelServicePreset').addEventListener('change', function () {
    const preset = presetByKey(this.value);
    if (preset) applyModelPreset(preset);
    renderReasoningCapability();
  });
  $('#modelMaxTokens').addEventListener('input', function (event) {
    const input = event && (event.currentTarget || event.target) || this;
    const current = currentOutputLimitState();
    current.source = 'manual';
    current.value = input.value;
    renderOutputLimitState(current, $('#modelName').value);
  });
  $('#modelName').addEventListener('change', function (event) {
    const input = event && (event.currentTarget || event.target) || this;
    const modelId = String(input.value || '').trim();
    const previousModel = $('#modelMaxTokens').dataset.model || '';
    if (!modelId) return;
    recommendOutputForModel(modelId, {modelChanged: previousModel !== modelId}).catch(function (error) { $('#modelStatus').textContent = error.message; });
    renderReasoningCapability();
  });
  const castSearchInput = $('#castSearch'); if (castSearchInput) castSearchInput.addEventListener('input', function () { clearTimeout(castSearchTimer); const value = this.value; castSearchTimer = setTimeout(function () { searchCharacters(value); }, 180); }); document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { setDrawer('settings', false); setDrawer('help', false); if ($('#mInstall').classList.contains('on')) closeModal('#mInstall'); else if ($('#mBackgroundPicker').classList.contains('on')) actions['close-background-picker'](); else if ($('#mBgReplace').classList.contains('on')) { closeModal('#mBgReplace'); state.bgReplaceCard = null; } else if ($('#mCast').classList.contains('on')) closeModal('#mCast'); else if ($('#mEdit').classList.contains('on')) closeModal('#mEdit'); else if (activeFilePicker && !$('#mBrowse').hidden) { activeFilePicker.close(); activeFilePicker = storyFilePicker; } else closeModal('#mBrowse'); } });
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
    if (context.background_target) return;
    if (context.origin === 'review') applyWorkbenchBackground(context, detail);
    else refreshAfterAssetWorkbench(context);
  });
  window.addEventListener('assetworkbench:background-applied', function (event) {
    const detail = event && event.detail || {};
    const story = currentStory();
    if (!story || detail.story_token !== story.story_token) return;
    if (detail.preflight_snapshot) restorePreflightSnapshot(detail.preflight_snapshot);
  });
  window.AppRuntime = {analyze: analyze, annotate: annotate, build: build, compile: compile, beginOperation: beginOperation, loadBackgrounds: loadBackgrounds, loadReview: loadReview, refreshDrafts: refreshDrafts, reviewPost: reviewPost, renderBackgroundRequests: renderBackgroundRequests, resolveBackground: resolveBackground, pollBuild: pollBuild, continueBackground: continueBackground, replaceStory: replaceStory, restoreActiveReview: restoreActiveReview, fillBackgroundFromHistory: fillBackgroundFromHistory, openDraftBackgroundPicker: openDraftBackgroundPicker, resolveDraftBackgroundRequest: resolveDraftBackgroundRequest, setReviewFilter: setReviewFilter, jumpToReviewCard: jumpToReviewCard, searchCharacters: searchCharacters, pickCharacter: pickCharacter, castSetKind: castSetKind, openCastPicker: openCastPicker, renderReviewCards: renderReviewCards, renderReviewAssets: renderReviewAssets, renderPreflight: renderPreflight, buildPreflightAssetTasks: buildPreflightAssetTasks, refreshAfterAssetWorkbench: refreshAfterAssetWorkbench, applyWorkbenchBackground: applyWorkbenchBackground, approvePreflight: approvePreflight, rerunPreflight: rerunPreflight, renderBackgroundTimeline: renderBackgroundTimeline, openBgReplace: openBgReplace, applyBgReplace: applyBgReplace, renderAAStatus: renderAAStatus, openInstallDialog: openInstallDialog, confirmInstall: confirmInstall, updateInstallProjectPreview: updateInstallProjectPreview, annotationProgressDetail: annotationProgressDetail, formatAnnotationCompletion: formatAnnotationCompletion};
  window.AppRuntime.buildAAIndex = buildAAIndex;
  window.AppRuntime.pollAAIndex = pollAAIndex;
  window.addEventListener('load', function () {
    if (localStorage.getItem('aa-welcome-dismissed-v1') === '1') $('#welcomePanel').hidden = true;
    loadSetupStatus(); loadState(); loadProfiles().catch(function () {}); loadModelWorkbench(); recentStories.refresh();
    const savedReview = readActiveReview();
    if (savedReview && savedReview.draft_token) restoreActiveReview();
  });
})();
