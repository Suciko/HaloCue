/* Shared, story-scoped asset cards and import feedback. */
(function (exports) {
  'use strict';

  const TASK_STATES = new Set([
    'validating', 'validated', 'waiting_for_aa', 'registering',
    'labeling', 'available', 'failed', 'interrupted'
  ]);
  const FILTERS = [
    ['all', '全部'], ['character', '角色'], ['background', '背景'],
    ['sound', '音效'], ['bgm', 'BGM']
  ];
  const COLLECTIONS = {character: 'characters', background: 'backgrounds', sound: 'sounds', bgm: 'bgms'};
  const ACTIVE_STATES = new Set(['validating', 'validated', 'waiting_for_aa', 'registering', 'labeling']);
  const STORAGE_KEY = 'aa-story-asset-tasks-v1';

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }
  function clear(node) { node.textContent = ''; }
  function releaseAudio(node) { const audios = node && node.querySelectorAll ? node.querySelectorAll('audio') : (document.querySelectorAll ? document.querySelectorAll('audio') : []); audios.forEach(function (audio) { if (audio.pause) audio.pause(); if (audio.removeAttribute) audio.removeAttribute('src'); if (audio.load) audio.load(); }); }
  function currentStory() { return exports.StoryStore && exports.StoryStore.get ? exports.StoryStore.get() : null; }
  function hasNativeAssetPicker() {
    return Boolean(exports.HaloCueNative && typeof exports.HaloCueNative.pickAsset === 'function');
  }
  function storage() {
    try { return exports.sessionStorage || (typeof sessionStorage !== 'undefined' ? sessionStorage : null); }
    catch (_) { return null; }
  }
  function taskMessage(task) {
    if (task.state === 'validating') return '正在检查文件';
    if (task.state === 'validated') return '检查通过，准备登记';
    if (task.state === 'waiting_for_aa') return '请关闭 AA 后重试';
    if (task.state === 'registering') return '正在复制并登记';
    if (task.state === 'labeling') return '正在识别背景场景';
    if (task.state === 'available') return task.message || '已可用';
    if (task.state === 'interrupted') return '导入已中断，可重试';
    if (task.code === 'aa_running') return '请关闭 AA 后重试';
    if (task.code === 'validation_failed') return task.message || '文件未通过检查，请重新选择';
    if (task.code === 'same_name_different_content') return '同名素材内容不同，请重命名后重试';
    return task.message || '导入失败，可重试';
  }
  function taskStateLabel(task) {
    const labels = {
      validating: '正在检查', validated: '检查完成', waiting_for_aa: '等待 AA 退出',
      registering: '正在登记', labeling: 'AI 标注中', available: '已可用', failed: '导入失败', interrupted: '已中断'
    };
    return labels[task.state] || '导入状态';
  }
  function retryLabel(task) {
    if (task.code === 'validation_failed') return '重新选择';
    if (task.code === 'aa_running') return '关闭 AA 后重试';
    return '重试';
  }
  function stableFailure(error) {
    const code = error && error.code;
    if (code === 'aa_running') return {state: 'waiting_for_aa', code: code};
    if (code === 'validation_failed') return {state: 'failed', code: code, message: error.e || error.message};
    if (code === 'same_name_different_content') return {state: 'failed', code: code, message: error.e || error.message};
    if (code === 'invalid_file_token' || (error && (error.status === 404 || error.status === 410))) return {state: 'interrupted', code: code || 'job_missing', message: '导入已中断，请重新选择'};
    return {state: 'failed', code: code || 'import_failed', message: (error && (error.e || error.message)) || '导入失败'};
  }
  function assetRows(data) {
    const out = [];
    Object.keys(COLLECTIONS).forEach(function (kind) {
      const values = data && data[COLLECTIONS[kind]];
      (Array.isArray(values) ? values : []).forEach(function (item) { out.push({kind: kind, item: item || {}}); });
    });
    return out;
  }
  function assetMeta(kind, item) {
    const labels = item.labels || {};
    if (kind === 'character') {
      const expressionStatus = item.expression_status === 'known'
        ? '已识别表情编号'
        : item.expression_status === 'unresolved' ? '表情状态待确认' : (item.expression_status || '待检测');
      return [
        '表情 ' + expressionStatus,
        '文件 ' + (item.file_completeness || '待检测'),
        '面部 ' + ((item.faces || []).length || '待检测')
      ].join(' · ');
    }
    if (kind === 'background') return [item.resolution || '待检测', item.aspect_ratio || '待检测', labels.place || labels.tags || '待检测'].join(' · ');
    if (kind === 'sound') return [
      item.duration ? Number(item.duration).toFixed(1) + ' 秒' : '待检测',
      item.codec || '待检测', item.sample_rate ? item.sample_rate + ' Hz' : '待检测',
      item.channels ? item.channels + ' 声道' : '待检测'
    ].join(' · ');
    return '待检测';
  }
  function assetStatusLabel(status) {
    return status === 'registered' ? '已登记'
      : status === 'verified' ? '已验证'
      : status === 'observed' ? '已识别'
      : status === 'missing' ? '待补充'
      : status === 'failed' ? '检查失败'
      : status || '待确认';
  }
  function previewUrl(storyToken, kind, item) {
    return '/api/story/assets/preview?story_token=' + encodeURIComponent(storyToken) + '&kind=' + encodeURIComponent(kind) + '&key=' + encodeURIComponent(item.aa_key);
  }

  function StoryAssetStrip(root, options) {
    this.root = root;
    this.options = options || {};
    this.filter = 'all';
    this.items = {characters: [], backgrounds: [], sounds: [], bgms: [], counts: {}};
    this.tasks = [];
    this.loadGeneration = 0;
    this.recoverGeneration = 0;
    this.restoreTasks();
    this.bindCharacterForm();
    this.clear();
  }

  StoryAssetStrip.prototype.bindCharacterForm = function () {
    if (!document.getElementById) return;
    const dialog = document.getElementById('mAssetCharacter');
    if (!dialog) return;
    const identifier = document.getElementById('assetCharacterIdentifier');
    const displayName = document.getElementById('assetCharacterDisplayName');
    const path = document.getElementById('assetCharacterPath');
    const error = document.getElementById('assetCharacterError');
    if (dialog.dataset.assetCharacterBound) return;
    dialog.dataset.assetCharacterBound = '1';
    const close = function () { [identifier, displayName, path].forEach(function (field) { if (field) { field.value = ''; field.setAttribute('aria-invalid', 'false'); } }); dialog.classList.remove('on'); dialog.setAttribute('aria-hidden', 'true'); if (dialog._assetTrigger && dialog._assetTrigger.focus) dialog._assetTrigger.focus(); };
    const self = this;
    if (!document._assetCharacterEscapeBound && document.addEventListener) { document._assetCharacterEscapeBound = true; document.addEventListener('keydown', function (event) { if (event.key === 'Escape' && dialog.classList.contains('on')) close(); }); }
    ['assetCharacterCancel', 'assetCharacterCancelSecondary'].forEach(function (id) {
      const button = document.getElementById(id); if (button) button.addEventListener('click', close);
    });
    const confirm = document.getElementById('assetCharacterConfirm');
    if (confirm) confirm.addEventListener('click', function () {
      const values = {identifier: (identifier && identifier.value || '').trim(), displayName: (displayName && displayName.value || '').trim(), path: (path && path.value || '').trim()};
      if (!values.identifier || !values.displayName || !values.path) {
        [identifier, displayName, path].forEach(function (field) { if (field) field.setAttribute('aria-invalid', String(!field.value.trim())); });
        if (error) error.textContent = '请填写角色标识、显示名称和角色文件路径。';
        return;
      }
      if (error) error.textContent = '';
      close(); self.importLocal('character', values);
    });
  };

  StoryAssetStrip.prototype.openCharacterForm = function () {
    if (hasNativeAssetPicker() && exports.AssetImportDialog && exports.AssetImportDialog.openForKind) {
      return exports.AssetImportDialog.openForKind('character', document.activeElement);
    }
    if (!document.getElementById) return this.importLocal('character', {});
    const dialog = document.getElementById('mAssetCharacter');
    if (!dialog) return this.importLocal('character', {});
    const error = document.getElementById('assetCharacterError'); if (error) error.textContent = '';
    dialog._assetTrigger = document.activeElement; dialog.classList.add('on'); dialog.setAttribute('aria-hidden', 'false');
    const identifier = document.getElementById('assetCharacterIdentifier'); if (identifier && identifier.focus) identifier.focus();
    return null;
  };

  StoryAssetStrip.prototype.clear = function () {
    this.loadGeneration += 1;
    releaseAudio(this.root);
    clear(this.root);
    const hasDetached = this.tasks.some(function (task) { return ACTIVE_STATES.has(task.state) || task.state === 'interrupted' || task.state === 'failed'; });
    this.root.classList.toggle('is-empty', !hasDetached);
    this.root.classList.remove('is-empty-state');
    this.root.appendChild(make('p', 'dim', '打开剧情后显示当前剧情的自定义素材。'));
    this.renderTasksForDetachedStory();
  };

  StoryAssetStrip.prototype.renderTasksForDetachedStory = function () {
    const visible = this.tasks.filter(function (task) { return ACTIVE_STATES.has(task.state) || task.state === 'interrupted' || task.state === 'failed'; });
    if (!visible.length) return;
    const note = make('p', 'asset-task-detached dim', '导入任务仍绑定原剧情；切回该剧情后可继续查看。');
    this.root.appendChild(note);
  };

  StoryAssetStrip.prototype.restoreTasks = function () {
    const store = storage();
    if (!store) return;
    try {
      const raw = JSON.parse(store.getItem(STORAGE_KEY) || '[]');
      this.tasks = Array.isArray(raw) ? raw.slice(0, 30).filter(function (task) {
        return task && TASK_STATES.has(task.state) && typeof task.id === 'string' && typeof task.storyToken === 'string';
      }) : [];
      this.tasks.forEach(function (task) { if (ACTIVE_STATES.has(task.state) && !task.jobId) task.state = 'interrupted'; });
      this.persistTasks();
    } catch (_) {
      this.tasks = [];
      try { store.removeItem(STORAGE_KEY); } catch (ignored) {}
    }
  };
  StoryAssetStrip.prototype.persistTasks = function () {
    const store = storage();
    if (!store) return;
    const kept = this.tasks.slice(-30).map(function (task) {
      return {id: task.id, kind: task.kind, name: task.name, storyToken: task.storyToken, state: task.state, code: task.code || '', message: task.message || '', jobId: task.jobId || '', fileToken: task.fileToken || '', displayName: task.displayName || '', identifier: task.identifier || '', labels: task.labels || {}};
    });
    try { store.setItem(STORAGE_KEY, JSON.stringify(kept)); } catch (_) {}
  };
  StoryAssetStrip.prototype.beginTask = function (input) {
    if (this.tasks.filter(function (task) { return ACTIVE_STATES.has(task.state); }).length >= 30) { const error = new Error('too_many_active_tasks'); error.code = 'too_many_active_tasks'; throw error; }
    input = input || {};
    const story = currentStory();
    const task = {
      id: 'asset-task-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8),
      kind: input.kind, name: input.name || input.displayName || '未命名素材',
      storyToken: input.storyToken || (story && story.story_token) || '',
      source: input.source || '', displayName: input.displayName || '', identifier: input.identifier || '', labels: input.labels || {},
      state: 'validating', code: '', message: '', jobId: input.jobId || ''
    };
    this.tasks.push(task); this.pruneTasks(); this.persistTasks(); this.render();
    return task;
  };
  StoryAssetStrip.prototype.pruneTasks = function () {
    if (this.tasks.length <= 30) return;
    const terminal = this.tasks.filter(function (task) { return !ACTIVE_STATES.has(task.state); });
    while (this.tasks.length > 30 && terminal.length) {
      const drop = terminal.shift(); this.tasks.splice(this.tasks.indexOf(drop), 1);
    }
  };
  StoryAssetStrip.prototype.updateTask = function (id, patch) {
    const task = this.tasks.find(function (item) { return item.id === id; });
    if (!task) return null;
    if (patch && patch.state && !TASK_STATES.has(patch.state)) throw new Error('invalid_asset_task_state');
    Object.assign(task, patch || {});
    if (!ACTIVE_STATES.has(task.state)) { task.source = ''; task.fileToken = ''; task.jobId = ''; }
    this.pruneTasks(); this.persistTasks(); this.render();
    return task;
  };
  StoryAssetStrip.prototype.load = async function (storyToken) {
    const story = currentStory();
    if (!story || story.story_token !== storyToken) return;
    const generation = ++this.loadGeneration;
    this.root.classList.remove('is-empty'); this.render(true);
    try {
      const data = await exports.Api.request('/api/story/assets?story_token=' + encodeURIComponent(storyToken));
      if (generation !== this.loadGeneration || !currentStory() || currentStory().story_token !== storyToken) return;
      this.items = Object.assign({characters: [], backgrounds: [], sounds: [], bgms: [], counts: {}}, data || {});
      this.render();
      this.recoverTasks(storyToken);
    } catch (error) {
      if (generation !== this.loadGeneration || !currentStory() || currentStory().story_token !== storyToken) return;
      this.render(false, '素材列表暂时无法读取：' + error.message);
      throw error;
    }
  };
  StoryAssetStrip.prototype.refresh = function (story) { return story ? this.load(story.story_token) : Promise.resolve(this.clear()); };
  StoryAssetStrip.prototype.recoverTasks = function (storyToken) {
    const self = this; const generation = ++this.recoverGeneration;
    this.tasks.filter(function (task) { return task.storyToken === storyToken && ACTIVE_STATES.has(task.state); }).forEach(function (task) {
      if (!task.jobId) { self.updateTask(task.id, {state: 'interrupted'}); return; }
      exports.Api.poll('/api/jobs/' + encodeURIComponent(task.jobId), function (job) {
        return ['succeeded', 'failed', 'cancelled'].includes(job.state);
      }, {isCurrent: function () { return generation === self.recoverGeneration && currentStory() && currentStory().story_token === storyToken; }}).then(function (job) {
        if (!job || generation !== self.recoverGeneration || task.storyToken !== storyToken) return;
        const wasBackgroundLabel = task.kind === 'background' && task.state === 'labeling';
        if (job.state === 'succeeded') { self.updateTask(task.id, {state: 'available'}); self.load(storyToken).catch(function () { self.updateTask(task.id, {state: 'available', code: 'refresh_failed', message: '已登记，列表刷新失败。'}); }); }
        else if (wasBackgroundLabel && job.state === 'failed') self.updateTask(task.id, {state: 'available', code: 'background_label_failed', message: '背景已登记，AI 标注失败，可在素材工作台补充'});
        else self.updateTask(task.id, {state: job.state === 'cancelled' ? 'interrupted' : 'failed', message: job.error || ''});
      }).catch(function () { self.updateTask(task.id, {state: 'interrupted'}); });
    });
  };
  StoryAssetStrip.prototype.render = function (loading, error) {
    const story = currentStory();
    releaseAudio(this.root);
    clear(this.root);
    if (!story) { this.root.classList.add('is-empty'); this.root.classList.remove('is-empty-state'); this.root.appendChild(make('p', 'dim', '打开剧情后显示当前剧情的自定义素材。')); return; }
    this.root.classList.remove('is-empty');
    const storyTasks = this.tasks.filter(function (task) { return task.storyToken === story.story_token; });
    const hasAssets = assetRows(this.items).length > 0;
    this.root.classList.toggle('is-empty-state', !loading && !error && !hasAssets && !storyTasks.length);
    const header = make('div', 'asset-strip-heading');
    header.appendChild(make('h2', '', '本剧情自定义素材'));
    const counts = this.items.counts || {};
    header.appendChild(make('p', 'dim', loading ? '正在读取自定义素材…' : '角色 ' + (counts.characters || this.items.characters.length || 0) + ' · 背景 ' + (counts.backgrounds || this.items.backgrounds.length || 0) + ' · 音效 ' + (counts.sounds || this.items.sounds.length || 0) + ' · BGM ' + (counts.bgms || this.items.bgms.length || 0)));
    this.root.appendChild(header);
    const controls = make('div', 'asset-strip-controls'); const self = this;
    FILTERS.forEach(function (pair) { const button = make('button', 'ghost asset-filter' + (self.filter === pair[0] ? ' active' : ''), pair[1]); button.type = 'button'; button.addEventListener('click', function () { self.filter = pair[0]; self.render(); }); controls.appendChild(button); });
    const kindLabels = {character: '角色', background: '背景', sound: '音效'};
    const addImportActions = function (resolveKind) {
      const initialKind = resolveKind();
      if (!initialKind) return;
      const importKindLabel = kindLabels[initialKind] || '素材';
      const historyButton = make('button', 'ghost asset-import-history', '从历史导入' + importKindLabel); historyButton.type = 'button';
      historyButton.addEventListener('click', function () {
        const importKind = resolveKind();
        if (importKind && exports.HistoryDrawer && exports.HistoryDrawer.open) exports.HistoryDrawer.open({kind: importKind, trigger: historyButton});
      });
      controls.appendChild(historyButton);
      const importButton = make('button', 'asset-import-local', '从本地导入' + importKindLabel); importButton.type = 'button';
      importButton.addEventListener('click', function () {
        const importKind = resolveKind();
        if (importKind === 'character') self.openCharacterForm(); else if (importKind) self.importLocal(importKind, {});
      });
      controls.appendChild(importButton);
    };
    if (this.filter !== 'all' && this.filter !== 'bgm') {
      const importKind = this.filter;
      addImportActions(function () { return importKind; });
    }
    if (this.filter !== 'bgm') {
      const inboxButton = make('button', 'ghost asset-import-inbox', '扫描素材目录'); inboxButton.type = 'button'; inboxButton.title = '扫描当前剧情素材目录中的背景、音效和角色';
      inboxButton.addEventListener('click', function () { self.scanInbox(); });
      controls.appendChild(inboxButton);
    }
    this.root.appendChild(controls);
    if (this.filter === 'bgm') this.root.appendChild(make('p', 'asset-bgm-gate dim', '当前默认不使用 BGM／原生验证完成后开放。'));
    // 外壳与列表分离：切换筛选只重建列表，避免整块卡顿。
    this.content = make('div', 'asset-strip-content');
    this.root.appendChild(this.content);
    this.renderContent(loading, error);
  };
  StoryAssetStrip.prototype.renderContent = function (loading, error) {
    const story = currentStory();
    if (!story || !this.content) return;
    releaseAudio(this.content);
    clear(this.content);
    const self = this;
    if (error) this.content.appendChild(make('p', 'asset-strip-error', error));
    const taskList = this.tasks.filter(function (task) { return task.storyToken === story.story_token && (self.filter === 'all' || task.kind === self.filter); });
    if (taskList.length) { const tasks = make('div', 'asset-task-list'); taskList.forEach(function (task) { tasks.appendChild(self.renderTask(task)); }); this.content.appendChild(tasks); }
    const cards = assetRows(this.items).filter(function (row) { return self.filter === 'all' || row.kind === self.filter; });
    const list = make('div', 'asset-card-list');
    if (!loading && !cards.length && !taskList.length) list.appendChild(make('p', 'asset-strip-empty dim', self.filter === 'bgm' ? '当前没有可用 BGM。' : self.filter === 'all' ? '当前剧情还没有自定义素材。' : '当前剧情还没有此类自定义素材。'));
    cards.forEach(function (row) { list.appendChild(self.renderAsset(row.kind, row.item)); }); this.content.appendChild(list);
  };
  StoryAssetStrip.prototype.renderTask = function (task) {
    const card = make('article', 'asset-task-card task-' + task.state); card.dataset.taskId = task.id;
    card.appendChild(make('b', 'asset-task-name', task.name)); card.appendChild(make('p', 'asset-task-message', taskMessage(task)));
    card.appendChild(make('span', 'asset-task-status', taskStateLabel(task)));
    if (task.state === 'failed' || task.state === 'interrupted' || task.state === 'waiting_for_aa') { const self = this; const button = make('button', 'ghost asset-task-retry', retryLabel(task)); button.type = 'button'; button.addEventListener('click', function () { self.retryTask(task.id); }); card.appendChild(button); }
    return card;
  };
  StoryAssetStrip.prototype.renderAsset = function (kind, item) {
    const card = make('article', 'asset-card asset-card-' + kind);
    const preview = make('div', 'asset-preview asset-preview-' + kind);
    const story = currentStory();
    if (story && item.preview_available && kind === 'background') {
      const image = make('img', 'asset-preview-image'); image.loading = 'lazy'; image.src = previewUrl(story.story_token, kind, item); image.alt = item.name || '背景预览'; preview.appendChild(image);
    } else if (story && item.preview_available && kind === 'character') {
      const image = make('img', 'asset-preview-image asset-preview-avatar'); image.loading = 'lazy'; image.src = previewUrl(story.story_token, kind, item); image.alt = item.name || '角色头像预览'; preview.appendChild(image);
    } else if (story && item.preview_available && kind === 'sound') {
      const audio = make('audio', 'asset-preview-audio'); audio.controls = true; audio.preload = 'none'; audio.src = previewUrl(story.story_token, kind, item); preview.appendChild(audio);
    } else preview.textContent = kind === 'character' ? '角色文件待检测' : kind === 'background' ? '背景预览待检测' : kind === 'sound' ? '音效待检测' : 'BGM';
    card.appendChild(preview);
    card.appendChild(make('b', 'asset-card-name', item.name || item.display_name || '未命名素材'));
    card.appendChild(make('span', 'asset-card-type', kind === 'character' ? '角色' : kind === 'background' ? '背景' : kind === 'sound' ? '音效' : 'BGM'));
    card.appendChild(make('p', 'asset-card-meta', assetMeta(kind, item)));
    card.appendChild(make('span', 'asset-card-status status-' + (item.status || 'registered'), assetStatusLabel(item.status || 'registered')));
    card.appendChild(make('small', 'asset-source-project', item.source_project ? '来源 · 历史剧情：' + item.source_project : '来源 · 本地导入'));
    return card;
  };
  StoryAssetStrip.prototype.retryTask = function (id) {
    const task = this.tasks.find(function (item) { return item.id === id; });
    if (!task || task.kind === 'bgm') return;
    if (task.source || task.fileToken) this.runImport(task, {source: task.source, fileToken: task.fileToken, displayName: task.displayName, identifier: task.identifier, labels: task.labels});
    else this.importLocal(task.kind, {});
  };
  StoryAssetStrip.prototype.scanInbox = async function (triggerContext) {
    const story = currentStory();
    if (!story) return null;
    triggerContext = triggerContext || {};
    if (hasNativeAssetPicker() && !triggerContext.nativeSelection) {
      if (exports.AssetImportDialog && exports.AssetImportDialog.open) {
        exports.AssetImportDialog.open(document.activeElement);
        return exports.AssetImportDialog.scanInbox();
      }
      return null;
    }
    const task = this.beginTask({kind: 'background', name: '素材目录扫描', storyToken: story.story_token, source: 'inbox'});
    this.updateTask(task.id, {state: 'registering', message: '正在扫描素材文件夹…'});
    try {
      const scanPayload = {story_token: story.story_token};
      if (triggerContext.fileToken) scanPayload.file_token = triggerContext.fileToken;
      const result = await exports.Api.request('/api/story/assets/scan-inbox', exports.Api.json('POST', scanPayload));
      if (!currentStory() || currentStory().story_token !== task.storyToken) { this.updateTask(task.id, {state: 'interrupted'}); return null; }
      const res = result && result.results ? result.results : {};
      const registered = (res.registered || []).length;
      const skipped = (res.skipped || []).length;
      const errors = (res.errors || []).length;
      const inboxPath = (result && result.inbox && result.inbox[0]) ? result.inbox[0].replace(/\\/g, '/') : '';
      const firstError = (res.errors || [])[0];
      const detail = firstError ? '；如 ' + firstError.message : '';
      this.updateTask(task.id, {
        state: registered || !errors ? 'available' : 'failed',
        message: (inboxPath ? '素材放 ' + inboxPath + '/bgs|sounds|characters；' : '') + '本次：登记 ' + registered + ' · 跳过 ' + skipped + ' · 失败 ' + errors + detail,
        code: errors && !registered ? 'validation_failed' : ''
      });
      try { await this.load(story.story_token); } catch (_) {}
      return result;
    } catch (error) {
      if (!currentStory() || currentStory().story_token !== task.storyToken) { this.updateTask(task.id, {state: 'interrupted'}); return null; }
      this.updateTask(task.id, stableFailure(error));
      return null;
    }
  };
  StoryAssetStrip.prototype.importLocal = async function (kind, triggerContext) {
    if (!['character', 'background', 'sound'].includes(kind)) return null;
    const story = currentStory(); if (!story) return null;
    triggerContext = triggerContext || {};
    if (hasNativeAssetPicker() && !triggerContext.fileToken && !triggerContext.path && !triggerContext.source) {
      if (exports.AssetImportDialog && exports.AssetImportDialog.openForKind) {
        exports.AssetImportDialog.openForKind(kind, document.activeElement);
      }
      return null;
    }
    const fileToken = triggerContext.fileToken || '';
    let path = triggerContext.path || triggerContext.source || '';
    if (!fileToken && !path && typeof exports.prompt === 'function') path = exports.prompt('输入要导入的素材完整路径', '');
    if (!fileToken && !path) return null;
    const displayName = triggerContext.displayName || '';
    const identifier = triggerContext.identifier || '';
    const labels = triggerContext.labels || {};
    const task = this.beginTask({kind: kind, name: triggerContext.name || path.split(/[\\/]/).pop() || '所选素材', storyToken: story.story_token, source: path, fileToken: fileToken, displayName: displayName, identifier: identifier, labels: labels});
    if (this.options.onToast) this.options.onToast('已开始导入素材');
    return this.runImport(task, {source: path, fileToken: fileToken, displayName: displayName, identifier: identifier, labels: labels});
  };
  StoryAssetStrip.prototype.runImport = async function (task, details) {
    const story = currentStory();
    if (!story || story.story_token !== task.storyToken) { this.updateTask(task.id, {state: 'interrupted'}); return null; }
    try {
      this.updateTask(task.id, {state: 'validating', code: '', message: ''});
      const picker = details.fileToken ? {file_token: details.fileToken} : await exports.Api.request('/api/picker', exports.Api.json('POST', {path: details.source}));
      if (!currentStory() || currentStory().story_token !== task.storyToken) return null;
      this.updateTask(task.id, {fileToken: picker.file_token, source: ''});
      const payload = {kind: task.kind, file_token: picker.file_token, story_token: task.storyToken};
      if (task.kind === 'character') { payload.identifier = details.identifier; payload.display_name = details.displayName; }
      if (task.kind === 'background') {
        if (details.displayName) payload.display_name = details.displayName;
        if (details.labels && Object.keys(details.labels).length) payload.labels = details.labels;
      }
      const validation = await exports.Api.request('/api/assets/validate', exports.Api.json('POST', payload));
      if (!currentStory() || currentStory().story_token !== task.storyToken) return null;
      if (!validation.ok) { this.updateTask(task.id, {state: 'failed', code: 'validation_failed', message: ((validation.issues || [])[0] || {}).message || '文件未通过检查'}); return null; }
      this.updateTask(task.id, {state: 'validated'});
      this.updateTask(task.id, {state: 'registering'});
      const result = await exports.Api.request('/api/assets/register', exports.Api.json('POST', Object.assign(payload, {story_token: task.storyToken})));
      if (!currentStory() || currentStory().story_token !== task.storyToken) return null;
      if (!result.ok || result.status === 'rejected') { this.updateTask(task.id, {state: 'failed', code: 'validation_failed', message: (((result.issues || [])[0] || {}).message || '文件未通过检查')}); return null; }
      if (exports.dispatchEvent && typeof CustomEvent === 'function') {
        exports.dispatchEvent(new CustomEvent('storyassets:imported', {detail: {
          identity: {
            kind: String(result.kind || validation.kind || task.kind),
            aa_key: result.aa_key === undefined ? validation.aa_key : result.aa_key,
            sha256: String(result.sha256 || validation.sha256 || '')
          },
          story_token: task.storyToken
        }}));
      }
      if (result.job_id) { this.updateTask(task.id, {state: 'registering', jobId: result.job_id}); this.recoverTasks(task.storyToken); return result; }
      if (result.background_analysis && result.background_analysis.queued && result.background_analysis.job_id) {
        this.updateTask(task.id, {state: 'labeling', jobId: result.background_analysis.job_id});
        this.recoverTasks(task.storyToken);
        return result;
      }
      this.updateTask(task.id, {state: 'available'});
      try { await this.load(task.storyToken); }
      catch (_) { this.updateTask(task.id, {state: 'available', code: 'refresh_failed', message: '已登记，列表刷新失败。'}); }
      return result;
    } catch (error) {
      if (!currentStory() || currentStory().story_token !== task.storyToken) return null;
      this.updateTask(task.id, stableFailure(error)); return null;
    }
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.StoryAssetStrip = StoryAssetStrip;
  exports.StoryUI.TASK_STATES = TASK_STATES;
})(window);
