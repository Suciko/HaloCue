/* 应用内素材工作台路由：只持有安全上下文、目录筛选和选中状态。 */
(function (exports) {
  'use strict';

  const KINDS = [
    {kind: 'character', bucket: 'characters', label: '骨骼'},
    {kind: 'background', bucket: 'backgrounds', label: '背景'},
    {kind: 'sound', bucket: 'sounds', label: '音效'}
  ];
  const CONTEXT_FIELDS = [
    'origin', 'story_token', 'draft_token', 'card_id',
    'asset_kind', 'request_id', 'tasks'
  ];
  const TASK_FIELDS = [
    'task_id', 'kind', 'requested_name', 'source_location',
    'reason', 'candidate_keys'
  ];

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }

  function clear(node) { if (node) node.textContent = ''; }

  function currentStory() {
    return exports.StoryStore && exports.StoryStore.get
      ? exports.StoryStore.get()
      : null;
  }

  function safeLocation(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    const location = {};
    ['label', 'line', 'card_id'].forEach(function (key) {
      if (value[key] !== undefined && value[key] !== null) location[key] = value[key];
    });
    return location;
  }

  function safeTask(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const task = {};
    TASK_FIELDS.forEach(function (key) {
      if (!(key in value)) return;
      if (key === 'source_location') task[key] = safeLocation(value[key]);
      else if (key === 'candidate_keys') {
        task[key] = Array.isArray(value[key]) ? value[key].map(String) : [];
      } else task[key] = value[key];
    });
    return task;
  }

  function sanitizeWorkbenchContext(value) {
    const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const context = {};
    CONTEXT_FIELDS.forEach(function (key) {
      if (!(key in source)) return;
      if (key === 'tasks') context.tasks = Array.isArray(source.tasks)
        ? source.tasks.map(safeTask).filter(Boolean)
        : [];
      else context[key] = source[key];
    });
    context.origin = String(context.origin || 'topbar');
    context.story_token = String(context.story_token || '');
    if (!context.tasks) context.tasks = [];
    return context;
  }

  function flattenLibraryPayload(payload) {
    const rows = [];
    KINDS.forEach(function (info) {
      const values = Array.isArray(payload && payload[info.bucket])
        ? payload[info.bucket]
        : [];
      values.forEach(function (item) {
        if (!item || item.kind !== info.kind) return;
        const row = Object.assign({}, item);
        row._assetKey = [row.kind, row.aa_key, row.sha256].join(':');
        rows.push(row);
      });
    });
    return rows;
  }

  function kindLabel(kind) {
    const found = KINDS.find(function (item) { return item.kind === kind; });
    return found ? found.label : '素材';
  }

  function labelSummary(labels) {
    if (!labels || typeof labels !== 'object') return '';
    return Object.keys(labels).map(function (key) {
      const value = Array.isArray(labels[key]) ? labels[key].join('、') : labels[key];
      return String(value || '');
    }).filter(Boolean).join(' · ');
  }

  function auxiliary(item) {
    const details = item.details || {};
    if (item.kind === 'background') {
      return [details.resolution, labelSummary(details.labels)].filter(Boolean).join(' · ') || '背景信息待检测';
    }
    if (item.kind === 'character') {
      const files = details.file_count, faces = details.face_count;
      return (files === null || files === undefined ? '文件统计中' : Number(files) + ' 个文件') +
        ' · ' + (faces === null || faces === undefined ? '表情统计中' : Number(faces) + ' 个表情');
    }
    if (item.kind === 'sound') {
      const duration = Number(details.duration || 0);
      return [duration > 0 ? duration.toFixed(2) + ' 秒' : '', details.codec].filter(Boolean).join(' · ') || '音频信息待检测';
    }
    return '';
  }

  function AssetWorkbench(root) {
    this.root = root;
    this.appShell = document.getElementById('appShell');
    this.contextLabel = document.getElementById('assetWorkbenchContext');
    this.filters = document.getElementById('assetWorkbenchFilters');
    this.list = document.getElementById('assetWorkbenchList');
    this.detail = document.getElementById('assetWorkbenchDetail');
    this.tasks = document.getElementById('assetWorkbenchTasks');
    this.status = document.getElementById('assetWorkbenchStatus');
    this.taskToggle = document.getElementById('assetWorkbenchTaskToggle');
    this.context = sanitizeWorkbenchContext({});
    this.assets = [];
    this.selectedKey = null;
    this.returnFocus = null;
    this.generation = 0;
    this.searchQuery = '';
    this.kindFilter = 'all';
    this.roleFilter = 'all';
    this.visibleColumns = 3;
    this.preview = new exports.StoryUI.AssetPreview(this.detail);
    this.transfer = new exports.StoryUI.TransferController(this);
    this.copies = new exports.StoryUI.CopyManager(this);
    this.renderFilters();
    this.bind();
    this.observeLayout();
  }

  AssetWorkbench.prototype.bind = function () {
    const self = this;
    document.addEventListener('click', function (event) {
      const target = event.target && event.target.closest
        ? event.target.closest('[data-workbench-action],[data-library-action]')
        : null;
      if (!target || target.disabled) return;
      const action = target.dataset.workbenchAction || target.dataset.libraryAction;
      if (action === 'open') {
        const story = currentStory() || {};
        self.open({origin: 'topbar', story_token: story.story_token || ''});
      } else if (action === 'close') self.close();
      else if (action === 'back-catalog') self.showCatalog();
      else if (action === 'toggle-tasks') self.toggleTasks();
      else if (action === 'select') self.select(target.dataset.assetKey, {navigate: true});
      else if (action === 'filter-kind') {
        self.kindFilter = target.dataset.kind || 'all';
        self.renderFilters();
        self.renderCatalog();
        self.restoreSelection();
      }
    });
    if (this.filters) this.filters.addEventListener('input', function (event) {
      if (event.target && event.target.dataset.workbenchFilter === 'search') {
        self.searchQuery = String(event.target.value || '').trim().toLocaleLowerCase();
        self.renderCatalog();
        self.restoreSelection();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) self.close();
    });
  };

  AssetWorkbench.prototype.isOpen = function () {
    return Boolean(this.root && !this.root.hidden);
  };

  AssetWorkbench.prototype.observeLayout = function () {
    const self = this;
    const update = function (width) {
      const columns = width <= 680 ? 1 : width <= 900 ? 2 : 3;
      self.visibleColumns = columns;
      if (self.root) self.root.dataset.visibleColumns = String(columns);
      if (self.body) self.body.dataset.visibleColumns = String(columns);
      if (columns > 1 && self.body) self.body.classList.remove('is-detail');
    };
    this.body = document.getElementById('assetWorkbenchBody');
    if (typeof ResizeObserver === 'function' && this.root) {
      this.layoutObserver = new ResizeObserver(function (entries) {
        const entry = entries && entries[0];
        update(entry && entry.contentRect ? entry.contentRect.width : self.root.clientWidth);
      });
      this.layoutObserver.observe(this.root);
    } else if (this.root) update(Number(this.root.clientWidth || 1200));
  };

  AssetWorkbench.prototype.showCatalog = function () {
    if (this.body) this.body.classList.remove('is-detail');
    const selected = this.list && this.list.querySelector
      ? this.list.querySelector('[data-asset-key="' + String(this.selectedKey || '').replace(/"/g, '\\"') + '"]')
      : null;
    if (selected && selected.focus) selected.focus();
  };

  AssetWorkbench.prototype.open = async function (context) {
    if (!this.root) return;
    this.context = sanitizeWorkbenchContext(context);
    this.returnFocus = document.activeElement || null;
    this.generation += 1;
    if (this.appShell) this.appShell.hidden = true;
    this.root.hidden = false;
    this.root.setAttribute('aria-hidden', 'false');
    if (this.contextLabel) {
      const story = currentStory();
      this.contextLabel.textContent = story && story.project
        ? story.project + ' · 每章保留独立素材副本'
        : '浏览跨章节素材；打开剧情后可复制登记';
    }
    this.renderTasks();
    if (this.root.focus) this.root.focus();
    await this.refresh();
  };

  AssetWorkbench.prototype.close = async function () {
    if (!this.root) return;
    this.generation += 1;
    this.preview.stop();
    this.root.hidden = true;
    this.root.setAttribute('aria-hidden', 'true');
    if (this.appShell) this.appShell.hidden = false;
    if (typeof exports.refreshAfterAssetWorkbench === 'function') {
      await exports.refreshAfterAssetWorkbench(this.context);
    }
    if (this.returnFocus && this.returnFocus.focus) this.returnFocus.focus();
  };

  AssetWorkbench.prototype.refresh = async function () {
    const generation = this.generation;
    if (this.status) this.status.textContent = '正在读取自定义素材履历…';
    try {
      const query = '?story_token=' + encodeURIComponent(this.context.story_token || '');
      const payload = await exports.Api.request('/api/assets/library' + query);
      if (!this.isOpen() || generation !== this.generation) return;
      this.assets = flattenLibraryPayload(payload);
      if (this.status) this.status.textContent = this.assets.length
        ? '已读取，只显示已登记的自定义素材。'
        : '尚无可复用的自定义素材。';
      this.renderCatalog();
      this.restoreSelection();
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation) return;
      this.assets = [];
      if (this.status) this.status.textContent = '素材读取失败，请检查本地服务后重试。';
      this.renderCatalog();
    }
  };

  AssetWorkbench.prototype.renderFilters = function () {
    clear(this.filters);
    if (!this.filters) return;
    const search = document.createElement('input');
    search.type = 'search';
    search.value = this.searchQuery;
    search.placeholder = '搜索素材名、系列或章节';
    search.setAttribute('aria-label', '搜索素材');
    search.dataset.workbenchFilter = 'search';
    this.filters.appendChild(search);
    const segments = make('div', 'asset-kind-segments');
    [['all', '全部'], ['character', '骨骼'], ['background', '背景'], ['sound', '音效']].forEach(function (entry) {
      const button = make('button', this.kindFilter === entry[0] ? 'is-active' : '', entry[1]);
      button.type = 'button';
      button.dataset.workbenchAction = 'filter-kind';
      button.dataset.kind = entry[0];
      button.setAttribute('aria-pressed', String(this.kindFilter === entry[0]));
      segments.appendChild(button);
    }, this);
    this.filters.appendChild(segments);
  };

  AssetWorkbench.prototype.filteredAssets = function () {
    const query = this.searchQuery;
    const kind = this.kindFilter;
    return this.assets.filter(function (item) {
      const searchable = [item.name, item.aa_key, item.series_name]
        .concat((item.copies || []).map(function (copy) { return copy.chapter; }))
        .concat(item.chapters || []).join(' ').toLocaleLowerCase();
      return (kind === 'all' || item.kind === kind) && (!query || searchable.includes(query));
    });
  };

  AssetWorkbench.prototype.renderCatalog = function () {
    clear(this.list);
    if (!this.list) return;
    const visible = this.filteredAssets();
    if (!visible.length) {
      const empty = make('p', 'asset-workbench-empty', '素材完成导入登记后会出现在这里。');
      this.list.appendChild(empty);
      return;
    }
    visible.forEach(function (item) {
      const button = make('button', 'asset-workbench-row');
      button.type = 'button';
      button.dataset.workbenchAction = 'select';
      button.dataset.assetKey = item._assetKey;
      button.appendChild(make('b', 'asset-name', item.name || String(item.aa_key || '未命名素材')));
      button.appendChild(make('span', 'asset-kind', kindLabel(item.kind)));
      button.appendChild(make('span', 'asset-state', item.registered_in_current ? '本章已登记' : '未登记'));
      button.appendChild(make('span', 'asset-auxiliary', auxiliary(item)));
      this.list.appendChild(button);
    }, this);
  };

  AssetWorkbench.prototype.restoreSelection = function () {
    const visible = this.filteredAssets();
    if (!visible.some(function (item) { return item._assetKey === this.selectedKey; }, this)) {
      this.selectedKey = visible.length ? visible[0]._assetKey : null;
    }
    this.select(this.selectedKey);
  };

  AssetWorkbench.prototype.select = function (key, options) {
    this.selectedKey = key || null;
    const item = this.selected();
    this.preview.render(item);
    this.renderDetailActions(item);
    if (item && options && options.navigate && this.visibleColumns === 1 && this.body) this.body.classList.add('is-detail');
  };

  AssetWorkbench.prototype.selected = function () {
    return this.assets.find(function (item) { return item._assetKey === this.selectedKey; }, this) || null;
  };

  AssetWorkbench.prototype.renderDetailActions = function (item) {
    if (!this.detail || !item) return;
    const back = make('button', 'ghost asset-detail-back', '返回目录');
    back.type = 'button';
    back.dataset.workbenchAction = 'back-catalog';
    if (this.detail.insertBefore) this.detail.insertBefore(back, this.detail.firstChild);
    else this.detail.appendChild(back);
    const actions = make('section', 'asset-detail-actions');
    const primary = make(
      'button', '', item.registered_in_current ? '本章已登记' : '复制到当前剧情'
    );
    primary.type = 'button';
    primary.disabled = Boolean(item.registered_in_current);
    primary.addEventListener('click', function () { this.transfer.copy(item); }.bind(this));
    actions.appendChild(primary);
    const manage = make('button', 'ghost', '管理副本');
    manage.type = 'button';
    manage.disabled = !item.preview_token;
    manage.addEventListener('click', function () { this.copies.open(item); }.bind(this));
    actions.appendChild(manage);
    if (item.kind === 'character') {
      const faces = make('button', 'ghost', '打开表情标注');
      faces.type = 'button';
      faces.dataset.assetAction = 'annotate-faces';
      faces.addEventListener('click', function () {
        if (exports.FaceWorkspace) exports.FaceWorkspace.open(item, faces);
      });
      actions.appendChild(faces);
    }
    this.detail.appendChild(actions);
    this.renderProfileEditor(item);
  };

  AssetWorkbench.prototype.renderProfileEditor = function (item) {
    const form = make('section', 'asset-profile-editor');
    form.appendChild(make('h4', '', '素材归属'));
    const role = document.createElement('select');
    [['chapter_only', '章节专用'], ['series_shared', '系列共用']].forEach(function (entry) {
      const option = make('option', '', entry[1]); option.value = entry[0]; role.appendChild(option);
    });
    role.value = item.asset_role || 'chapter_only';
    const series = document.createElement('input');
    series.type = 'text';
    series.maxLength = 80;
    series.placeholder = '系列名称';
    series.value = item.series_name || '';
    series.disabled = role.value !== 'series_shared';
    role.addEventListener('change', function () { series.disabled = role.value !== 'series_shared'; });
    const save = make('button', 'ghost', '保存分类');
    save.type = 'button';
    save.addEventListener('click', async function () {
      if (role.value === 'series_shared' && !series.value.trim()) {
        this.setCopyState('请先填写系列名称。');
        series.focus();
        return;
      }
      save.disabled = true;
      try {
        const result = await exports.Api.request('/api/assets/library/profile', exports.Api.json('POST', {
          kind: item.kind, aa_key: item.aa_key, sha256: item.sha256,
          asset_role: role.value, series_name: series.value.trim()
        }));
        item.asset_role = result.asset_role;
        item.series_name = result.series_name;
        this.setCopyState('素材分类已保存。');
      } catch (error) {
        this.setCopyState(String(error.action || '分类保存失败，请重试。'));
      } finally {
        save.disabled = false;
      }
    }.bind(this));
    form.appendChild(role); form.appendChild(series); form.appendChild(save);
    this.detail.appendChild(form);
  };

  AssetWorkbench.prototype.setTransferState = function (state, options) {
    const suffix = options && options.message ? ' ' + options.message : '';
    if (this.status) this.status.textContent = state + suffix;
    this.renderCatalog();
  };

  AssetWorkbench.prototype.setCopyState = function (message) {
    if (this.status) this.status.textContent = message;
  };

  AssetWorkbench.prototype.focusReference = function (reference) {
    if (exports.dispatchEvent && typeof CustomEvent === 'function') {
      exports.dispatchEvent(new CustomEvent('assetworkbench:focus-reference', {detail: reference}));
    }
  };

  AssetWorkbench.prototype.renderTasks = function () {
    clear(this.tasks);
    if (!this.tasks) return;
    if (!this.context.tasks.length) {
      this.tasks.appendChild(make('p', 'asset-workbench-empty', '当前没有待处理的素材任务。'));
      return;
    }
    this.context.tasks.forEach(function (task) {
      const row = make('section', 'asset-workbench-task');
      row.appendChild(make('b', '', task.requested_name || '待补素材'));
      row.appendChild(make('span', '', task.reason || '需要在当前剧情登记'));
      this.tasks.appendChild(row);
    }, this);
  };

  AssetWorkbench.prototype.toggleTasks = function () {
    if (!this.tasks || !this.taskToggle) return;
    const expanded = this.tasks.classList.contains('is-open');
    this.tasks.classList.toggle('is-open', !expanded);
    this.taskToggle.setAttribute('aria-expanded', String(!expanded));
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.AssetWorkbench = AssetWorkbench;
  exports.StoryUI.AssetLibraryWorkbench = AssetWorkbench;
  exports.sanitizeWorkbenchContext = sanitizeWorkbenchContext;
  exports.flattenLibraryPayload = flattenLibraryPayload;
  exports.openAssetWorkbench = function (context) {
    return exports.AssetWorkbench ? exports.AssetWorkbench.open(context) : undefined;
  };
  if (document.getElementById) {
    const root = document.getElementById('assetWorkbench');
    if (root) {
      exports.AssetWorkbench = new AssetWorkbench(root);
      exports.AssetLibraryWorkbench = exports.AssetWorkbench;
    }
  }
})(window);
