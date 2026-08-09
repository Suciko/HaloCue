/* Read-only historical asset browser for the current story workspace. */
(function (exports) {
  'use strict';

  const COPYABLE_KINDS = new Set(['character', 'background', 'sound']);

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }
  function clear(node) { node.textContent = ''; }
  function story() { return exports.StoryStore && exports.StoryStore.get ? exports.StoryStore.get() : null; }
  function historyError(error) {
    const code = error && error.code;
    if (code === 'history_source_missing') return '历史素材已不在原项目中。请从本地重新选择。';
    if (code === 'history_asset_stale') return '历史素材已经变更，请刷新后重新选择。';
    if (code === 'same_name_different_content') return '当前剧情已有同名但内容不同的素材，请重命名后再试。';
    if (code === 'aa_running') return '请先关闭 AA，再重试复制。';
    if (code === 'invalid_history_token' || code === 'invalid_history_asset_token' || (error && error.status === 410)) return '历史项目列表已过期，请刷新后重新选择。';
    if (code === 'validation_failed') return '历史素材未通过当前检查，无法复制。';
    return '复制素材失败，请重试。';
  }

  function HistoryDrawer(root, options) {
    this.root = root;
    this.options = options || {};
    this.embedded = Boolean(this.options.embedded);
    this.generation = 0;
    this.context = null;
    this.projects = [];
    this.assets = [];
    this.selectedProject = '';
    this.message = '';
    this.busy = false;
    this.trigger = null;
    this.searchQuery = '';
    this.bind();
  }

  HistoryDrawer.prototype.bind = function () {
    const self = this;
    if (this.root && this.root.addEventListener) {
      this.root.addEventListener('click', function (event) {
        const target = event.target && event.target.closest ? event.target.closest('[data-history-action]') : null;
        if (!target || target.disabled) return;
        const action = target.dataset.historyAction;
        if (action === 'close') self.close();
        else if (action === 'refresh') self.open(self.context || {});
        else if (action === 'project') self.selectProject(target.dataset.historyToken || '');
        else if (action === 'copy') self.copy(target.dataset.historyAssetToken || '');
        else if (action === 'replace-local') self.replaceLocal();
      });
    }
    if (!this.embedded && !document._historyDrawerEscapeBound && document.addEventListener) {
      document._historyDrawerEscapeBound = true;
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && self.isOpen()) self.close();
      });
    }
    if (exports.StoryStore && exports.StoryStore.subscribe) {
      exports.StoryStore.subscribe(function (next) {
        if (self.context && (!next || next.story_token !== self.context.storyToken)) self.abortForStoryChange();
      });
    }
  };

  HistoryDrawer.prototype.isOpen = function () {
    return Boolean(this.root && this.root.classList && this.root.classList.contains('on'));
  };
  HistoryDrawer.prototype.isCurrent = function (generation) {
    const active = story();
    return this.isOpen() && generation === this.generation && this.context && active && active.story_token === this.context.storyToken;
  };
  HistoryDrawer.prototype.abortForStoryChange = function () {
    this.generation += 1;
    this.busy = false;
    this.context = null;
    this.close({restore: false});
  };
  HistoryDrawer.prototype.open = async function (context) {
    context = context || {};
    const active = story();
    if (!active || !COPYABLE_KINDS.has(context.kind)) return null;
    const generation = ++this.generation;
    this.context = {
      kind: context.kind,
      storyToken: active.story_token,
      triggerCardId: context.triggerCardId || '',
      draftToken: context.draftToken || '',
      draftVersion: context.draftVersion,
      requestId: context.requestId || '',
      replaceCardId: context.replaceCardId || '',
      onApplied: (typeof context.onApplied === 'function') ? context.onApplied : null,
      onCopied: (typeof context.onCopied === 'function') ? context.onCopied : null,
      onReplaceLocal: (typeof context.onReplaceLocal === 'function') ? context.onReplaceLocal : null
    };
    this.trigger = context.trigger || document.activeElement || null;
    this.projects = [];
    this.assets = [];
    this.selectedProject = '';
    this.message = '正在读取历史项目…';
    this.busy = true;
    if (this.root) {
      this.root.hidden = false;
      this.root.classList.add('on');
      this.root.setAttribute('aria-hidden', 'false');
      this.root.setAttribute('aria-busy', 'true');
      if (this.root.focus) this.root.focus();
    }
    this.render();
    try {
      const projects = await exports.Api.request('/api/history/projects');
      if (!this.isCurrent(generation)) return null;
      this.projects = Array.isArray(projects) ? projects.slice() : [];
      this.busy = false;
      this.message = this.projects.length ? '' : '没有可复用的历史素材。';
      this.render();
      if (this.projects.length) return this.selectProject(this.projects[0].history_token, generation);
    } catch (error) {
      if (!this.isCurrent(generation)) return null;
      this.busy = false;
      this.message = historyError(error);
      this.render();
    }
    return null;
  };
  HistoryDrawer.prototype.selectProject = async function (historyToken, expectedGeneration) {
    const generation = expectedGeneration || this.generation;
    if (!this.isCurrent(generation) || !historyToken) return null;
    this.selectedProject = historyToken;
    this.assets = [];
    this.message = '正在读取素材…';
    this.busy = true;
    this.render();
    try {
      const rows = await exports.Api.request('/api/history/assets?history_token=' + encodeURIComponent(historyToken));
      if (!this.isCurrent(generation) || this.selectedProject !== historyToken) return null;
      this.assets = (Array.isArray(rows) ? rows : []).filter(function (asset) {
        return asset && asset.kind === this.context.kind && COPYABLE_KINDS.has(asset.kind);
      }, this);
      this.busy = false;
      this.message = this.assets.length ? '' : '这个历史项目没有可复制的此类素材。';
      this.render();
    } catch (error) {
      if (!this.isCurrent(generation)) return null;
      this.busy = false;
      this.message = historyError(error);
      this.render();
    }
    return null;
  };
  HistoryDrawer.prototype.copy = async function (historyAssetToken) {
    const context = this.context;
    const generation = this.generation;
    if (!this.isCurrent(generation) || this.busy || !historyAssetToken) return null;
    const asset = this.assets.find(function (item) { return item.history_asset_token === historyAssetToken; });
    if (!asset || asset.status === 'source_missing' || !COPYABLE_KINDS.has(asset.kind)) return null;
    const assetStrip = exports.StoryAssets;
    if (!assetStrip || !assetStrip.beginTask || !assetStrip.updateTask) return null;
    let task;
    try {
      task = assetStrip.beginTask({kind: asset.kind, name: asset.name, storyToken: context.storyToken});
      assetStrip.updateTask(task.id, {state: 'registering', code: '', message: ''});
    } catch (_) {
      this.message = '当前有太多导入任务，请稍后再试。';
      this.render();
      return null;
    }
    this.busy = true;
    this.message = '正在复制到当前剧情…';
    this.render();
    try {
      const result = await exports.Api.request('/api/story/assets/copy', exports.Api.json('POST', {
        story_token: context.storyToken,
        history_asset_token: historyAssetToken
      }));
      if (!this.isCurrent(generation) || this.context !== context) {
        assetStrip.updateTask(task.id, {state: 'interrupted', code: 'story_changed'});
        return null;
      }
      assetStrip.updateTask(task.id, {state: 'available'});
      if (exports.dispatchEvent && typeof CustomEvent === 'function') {
        exports.dispatchEvent(new CustomEvent('storyassets:imported', {detail: {
          identity: {
            kind: String(result.kind || asset.kind),
            aa_key: result.aa_key === undefined ? asset.aa_key : result.aa_key,
            sha256: String(result.sha256 || asset.sha256 || '')
          },
          story_token: context.storyToken
        }}));
      }
      try { await assetStrip.load(context.storyToken); }
      catch (_) { assetStrip.updateTask(task.id, {state: 'available', code: 'refresh_failed', message: '已复制，素材列表刷新失败。'}); }
      if (!this.isCurrent(generation) || this.context !== context) return null;
      const applied = await this.applyDraftContext(context, result);
      if (!this.isCurrent(generation) || this.context !== context) return null;
      if (context.onApplied) { try { await context.onApplied(result); } catch (_) {} }
      if (context.onCopied) { try { await context.onCopied(result); } catch (_) {} }
      if (!this.isCurrent(generation) || this.context !== context) return null;
      this.busy = false;
      this.message = applied === false
        ? '已复制到当前剧情。背景卡应用失败，草稿可能已更新，请刷新后重试。'
        : '已复制到当前剧情。';
      this.render();
      this.close();
      return result;
    } catch (error) {
      if (!this.isCurrent(generation) || this.context !== context) {
        assetStrip.updateTask(task.id, {state: 'interrupted', code: 'story_changed'});
        return null;
      }
      const code = error && error.code || 'history_copy_failed';
      const state = code === 'aa_running' ? 'waiting_for_aa' : (code === 'history_source_missing' ? 'failed' : 'failed');
      assetStrip.updateTask(task.id, {state: state, code: code, message: historyError(error)});
      this.busy = false;
      this.message = historyError(error);
      this.render();
      return null;
    }
  };
  HistoryDrawer.prototype.applyDraftContext = async function (context, result) {
    if (!context.draftToken || context.kind !== 'background' || !Number.isFinite(Number(context.draftVersion))) return null;
    if (!this.isCurrent(this.generation)) return null;
    const endpoint = context.replaceCardId
      ? '/api/cards/update'
      : '/api/drafts/' + encodeURIComponent(context.draftToken) + '/backgrounds/' + encodeURIComponent(context.requestId) + '/resolve';
    try {
      const payload = context.replaceCardId
        ? {token: context.draftToken, card_id: context.replaceCardId, patch: {cmd: 'bg', arg: result.aa_key || result.name}, expected_draft_version: Number(context.draftVersion)}
        : {bg_name: result.aa_key || result.name, expected_draft_version: Number(context.draftVersion)};
      await exports.Api.request(endpoint, exports.Api.json('POST', payload));
      return true;
    } catch (_) {
      // Registration remains valid; the caller can refresh its draft and apply again.
      return false;
    }
  };
  HistoryDrawer.prototype.replaceLocal = function () {
    const context = this.context;
    if (!context || !this.isCurrent(this.generation)) return null;
    this.close({restore: false});
    if (context.onReplaceLocal) return context.onReplaceLocal(context.kind);
    if (!exports.StoryAssets || !exports.StoryAssets.importLocal) return null;
    return exports.StoryAssets.importLocal(context.kind, {triggerCardId: context.triggerCardId});
  };
  HistoryDrawer.prototype.setSearchQuery = function (value) {
    this.searchQuery = String(value || '').trim().toLocaleLowerCase();
    this.render();
  };
  HistoryDrawer.prototype.filteredAssets = function () {
    const query = this.searchQuery;
    return this.assets.filter(function (asset) {
      const searchable = [asset.name, asset.aa_key, asset.project]
        .map(function (value) { return String(value || ''); })
        .join(' ').toLocaleLowerCase();
      return !query || searchable.includes(query);
    }).sort(function (left, right) {
      const leftTime = Date.parse(String(left.imported_at || ''));
      const rightTime = Date.parse(String(right.imported_at || ''));
      const leftKnown = Number.isFinite(leftTime), rightKnown = Number.isFinite(rightTime);
      if (leftKnown && !rightKnown) return -1;
      if (!leftKnown && rightKnown) return 1;
      if (leftKnown && rightKnown && leftTime !== rightTime) return rightTime - leftTime;
      return String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN', {
        numeric: true, sensitivity: 'base'
      }) || String(left.aa_key || '').localeCompare(String(right.aa_key || ''));
    });
  };
  HistoryDrawer.prototype.close = function (options) {
    options = options || {};
    if (!this.root) return;
    this.root.classList.remove('on');
    this.root.setAttribute('aria-hidden', 'true');
    this.root.setAttribute('aria-busy', 'false');
    this.root.hidden = true;
    if (options.restore !== false && this.trigger && this.trigger.focus) this.trigger.focus();
  };
  HistoryDrawer.prototype.render = function () {
    if (!this.root) return;
    clear(this.root);
    const panel = make('div', 'history-drawer-panel' + (this.embedded ? ' is-embedded' : ''));
    const header = make('div', 'history-drawer-heading');
    header.appendChild(make('h2', '', '从历史项目导入'));
    if (!this.embedded) {
      const close = make('button', 'ghost history-drawer-close', '关闭');
      close.type = 'button'; close.dataset.historyAction = 'close'; header.appendChild(close);
    }
    panel.appendChild(header);
    panel.appendChild(make('p', 'dim history-drawer-intro', '素材会复制并登记到当前剧情，不会链接到原项目。'));
    const kind = this.context && this.context.kind;
    panel.appendChild(make('p', 'history-drawer-kind', kind === 'character' ? '角色' : kind === 'sound' ? '音效' : '背景'));
    const projectList = make('div', 'history-project-list');
    this.projects.forEach(function (project) {
      const button = make('button', 'ghost history-project' + (project.history_token === this.selectedProject ? ' active' : ''), project.project || '未命名剧情');
      button.type = 'button'; button.dataset.historyAction = 'project'; button.dataset.historyToken = project.history_token; button.disabled = this.busy;
      projectList.appendChild(button);
    }, this);
    panel.appendChild(projectList);
    const assetList = make('div', 'history-asset-list');
    this.filteredAssets().forEach(function (asset) {
      const card = make('article', 'history-asset-card' + (asset.status === 'source_missing' ? ' is-missing' : ''));
      card.appendChild(make('b', 'history-asset-name', asset.name || asset.aa_key || '未命名素材'));
      card.appendChild(make('span', 'history-asset-type', asset.kind === 'character' ? '角色' : asset.kind === 'sound' ? '音效' : '背景'));
      if (asset.status === 'source_missing') {
        card.appendChild(make('p', 'history-asset-message', '原素材已缺失，不能复制。'));
        const replace = make('button', 'ghost', '从本地替换'); replace.type = 'button'; replace.dataset.historyAction = 'replace-local'; replace.disabled = this.busy; card.appendChild(replace);
      } else {
        const copy = make('button', 'history-copy', '复制到当前剧情'); copy.type = 'button'; copy.dataset.historyAction = 'copy'; copy.dataset.historyAssetToken = asset.history_asset_token; copy.disabled = this.busy; card.appendChild(copy);
      }
      assetList.appendChild(card);
    }, this);
    panel.appendChild(assetList);
    if (this.message) panel.appendChild(make('p', 'history-drawer-message', this.message));
    const refresh = make('button', 'ghost history-refresh', '刷新历史项目'); refresh.type = 'button'; refresh.dataset.historyAction = 'refresh'; refresh.disabled = this.busy; panel.appendChild(refresh);
    this.root.appendChild(panel);
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.HistoryDrawer = HistoryDrawer;
  if (document.getElementById) {
    const root = document.getElementById('historyAssetDrawer');
    if (root) exports.HistoryDrawer = new HistoryDrawer(root);
  }
})(window);
