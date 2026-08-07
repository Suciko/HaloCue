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
    'asset_kind', 'request_id', 'tasks', 'background_target'
  ];
  const TASK_FIELDS = [
    'task_id', 'kind', 'requested_name', 'source_location',
    'reason', 'candidate_keys'
  ];
  const SORT_MODES = new Set(['recent', 'oldest', 'name-asc', 'name-desc']);

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }

  function clear(node) { if (node) node.textContent = ''; }

  function storedSortMode() {
    try {
      const value = exports.localStorage && exports.localStorage.getItem
        ? exports.localStorage.getItem('aa-asset-workbench-sort-v1')
        : '';
      return SORT_MODES.has(value) ? value : 'recent';
    } catch (_) { return 'recent'; }
  }

  function saveSortMode(value) {
    try {
      if (exports.localStorage && exports.localStorage.setItem) {
        exports.localStorage.setItem('aa-asset-workbench-sort-v1', value);
      }
    } catch (_) {}
  }

  function parsedTime(value) {
    const time = Date.parse(String(value || ''));
    return Number.isFinite(time) ? time : null;
  }

  function formatLibraryTime(value) {
    const time = parsedTime(value);
    return time === null ? '' : new Date(time).toLocaleString('zh-CN', {hour12: false});
  }

  function nameCompare(left, right) {
    return String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN', {
      numeric: true, sensitivity: 'base'
    }) || String(left._assetKey || '').localeCompare(String(right._assetKey || ''));
  }

  function assetCompare(mode) {
    return function (left, right) {
      if (mode === 'name-asc') return nameCompare(left, right);
      if (mode === 'name-desc') return -nameCompare(left, right);
      const leftTime = parsedTime(left.imported_at);
      const rightTime = parsedTime(right.imported_at);
      if (leftTime === null && rightTime !== null) return 1;
      if (rightTime === null && leftTime !== null) return -1;
      if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
        return mode === 'oldest' ? leftTime - rightTime : rightTime - leftTime;
      }
      return nameCompare(left, right);
    };
  }

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

  function safeBackgroundTarget(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    const rawSelector = value.selector;
    if (!rawSelector || typeof rawSelector !== 'object' || Array.isArray(rawSelector)) return undefined;
    const selector = {};
    ['segment', 'location', 'requested_name'].forEach(function (key) {
      const text = String(rawSelector[key] || '').trim();
      if (text && text.length <= 160) selector[key] = text;
    });
    if (!selector.segment || !selector.location || !selector.requested_name) return undefined;
    return {selector: selector, place: String(value.place || '').trim().slice(0, 160)};
  }

  function sanitizeWorkbenchContext(value) {
    const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const context = {};
    CONTEXT_FIELDS.forEach(function (key) {
      if (!(key in source)) return;
      if (key === 'tasks') context.tasks = Array.isArray(source.tasks)
        ? source.tasks.map(safeTask).filter(Boolean)
        : [];
      else if (key === 'background_target') context.background_target = safeBackgroundTarget(source[key]);
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
    this.importButton = document.getElementById('assetWorkbenchImport');
    this.context = sanitizeWorkbenchContext({});
    this.assets = [];
    this.selectedKey = null;
    this.returnFocus = null;
    this.generation = 0;
    this.faceJob = null;
    this.faceJobError = '';
    this.taskTimer = null;
    this.taskPollSequence = 0;
    this.taskRequest = null;
    this.searchQuery = '';
    this.kindFilter = 'all';
    this.sortMode = storedSortMode();
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
      else if (action === 'import' && exports.AssetImportDialog) exports.AssetImportDialog.open(target);
      else if (action === 'back-catalog') self.showCatalog();
      else if (action === 'toggle-tasks') self.toggleTasks();
      else if (action === 'view-face-job') self.viewFaceJob(target);
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
    if (this.filters) this.filters.addEventListener('change', function (event) {
      if (event.target && event.target.dataset.workbenchFilter === 'sort') {
        const value = String(event.target.value || '');
        self.sortMode = SORT_MODES.has(value) ? value : 'recent';
        saveSortMode(self.sortMode);
        self.renderCatalog();
        self.restoreSelection();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) self.close();
    });
    if (exports.addEventListener) exports.addEventListener('storyassets:imported', function (event) {
      const detail = event && event.detail || {};
      if (!self.isOpen() || detail.story_token !== self.context.story_token) return;
      self.refresh().then(function () { self.locateAsset(detail.identity || {}); });
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
    this.faceJob = null;
    this.faceJobError = '';
    this.taskPollSequence += 1;
    if (this.appShell) this.appShell.hidden = true;
    this.root.hidden = false;
    this.root.setAttribute('aria-hidden', 'false');
    if (this.importButton) {
      this.importButton.disabled = !this.context.story_token;
      this.importButton.title = this.context.story_token ? '导入到当前剧情' : '请先打开剧情文件';
    }
    if (this.contextLabel) {
      const story = currentStory();
      this.contextLabel.textContent = story && story.project
        ? story.project + ' · 每章保留独立素材副本'
        : '浏览跨章节素材；打开剧情后可复制登记';
    }
    this.renderTasks();
    if (this.root.focus) this.root.focus();
    await Promise.all([this.refresh(), this.refreshTasks()]);
  };

  AssetWorkbench.prototype.close = async function () {
    if (!this.root) return;
    this.generation += 1;
    this.taskPollSequence += 1;
    if (this.taskTimer) clearTimeout(this.taskTimer);
    this.taskTimer = null;
    this.preview.stop();
    if (this.tasks) this.tasks.classList.remove('is-open');
    if (this.taskToggle) this.taskToggle.setAttribute('aria-expanded', 'false');
    this.root.hidden = true;
    this.root.setAttribute('aria-hidden', 'true');
    if (this.appShell) this.appShell.hidden = false;
    if (!this.context.background_target && typeof exports.refreshAfterAssetWorkbench === 'function') {
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
      this.renderTasks();
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
    const sort = document.createElement('select');
    sort.className = 'asset-sort-select';
    sort.dataset.workbenchFilter = 'sort';
    sort.setAttribute('aria-label', '素材排序');
    [
      ['recent', '最近导入'], ['oldest', '最早导入'],
      ['name-asc', '名称 A-Z'], ['name-desc', '名称 Z-A']
    ].forEach(function (entry) {
      const option = document.createElement('option');
      option.value = entry[0]; option.textContent = entry[1];
      sort.appendChild(option);
    });
    sort.value = SORT_MODES.has(this.sortMode) ? this.sortMode : 'recent';
    this.filters.appendChild(sort);
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
    }).sort(assetCompare(this.sortMode));
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
      const imported = formatLibraryTime(item.imported_at);
      const chapter = String(item.last_used_chapter || '').trim();
      button.appendChild(make(
        'span', 'asset-workbench-recency',
        (imported || '导入时间未知') + ' · ' +
          (chapter ? '最近使用：' + chapter : '最近使用章节未知')
      ));
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
    const heading = this.detail.querySelector ? this.detail.querySelector('.asset-detail-heading') : null;
    if (heading) heading.appendChild(back);
    else if (this.detail.insertBefore) this.detail.insertBefore(back, this.detail.firstChild);
    else this.detail.appendChild(back);
    const actions = make('section', 'asset-detail-actions');
    const applyMode = Boolean(
      this.context.background_target && item.kind === 'background'
    );
    const primary = make(
      'button', '', applyMode
        ? (item.registered_in_current ? '应用到当前场景' : '复制并应用到当前场景')
        : (item.registered_in_current ? '本章已登记' : '复制到当前剧情')
    );
    primary.type = 'button';
    primary.disabled = Boolean(item.registered_in_current && !applyMode);
    const actionStatus = make('p', 'asset-action-status');
    actionStatus.setAttribute('aria-live', 'polite');
    primary.addEventListener('click', async function () {
      if (!applyMode) return this.transfer.copy(item);
      const idleLabel = item.registered_in_current
        ? '应用到当前场景'
        : '复制并应用到当前场景';
      primary.disabled = true;
      primary.textContent = '正在应用…';
      actionStatus.textContent = '正在把这个背景应用到当前场景。';
      actionStatus.classList.remove('is-error');
      try {
        await this.applyBackground(item);
      } catch (error) {
        const raw = String(error && (error.e || error.message) || '背景未能应用到当前场景，请重试。');
        const message = error && error.status === 404 || raw === 'not found'
          ? '本地服务版本较旧，请重启程序后再试。'
          : raw;
        primary.disabled = false;
        primary.textContent = '重新' + idleLabel;
        actionStatus.textContent = '应用失败：' + message;
        actionStatus.classList.add('is-error');
      }
    }.bind(this));
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
    if (applyMode) this.detail.appendChild(actionStatus);
    this.renderProfileEditor(item);
    if (item.kind === 'background') this.renderBackgroundLabelEditor(item);
  };

  AssetWorkbench.prototype.locateAsset = function (identity) {
    identity = identity || {};
    const kind = String(identity.kind || '');
    const aaKey = String(identity.aa_key === undefined ? '' : identity.aa_key);
    const sha256 = String(identity.sha256 || '');
    const item = this.assets.find(function (candidate) {
      return candidate.kind === kind && String(candidate.aa_key) === aaKey &&
        (!sha256 || String(candidate.sha256 || '') === sha256);
    });
    if (!item) return null;
    this.selectedKey = item._assetKey;
    this.renderCatalog();
    this.select(item._assetKey);
    const row = this.list && this.list.querySelector
      ? this.list.querySelector('[data-asset-key="' + String(item._assetKey).replace(/"/g, '\\"') + '"]')
      : null;
    if (row && row.scrollIntoView) row.scrollIntoView({block: 'nearest'});
    if (row && row.focus) row.focus();
    return item;
  };

  AssetWorkbench.prototype.applyBackground = async function (item) {
    const target = this.context.background_target;
    if (!target || !item || item.kind !== 'background') return null;
    this.setCopyState(item.registered_in_current
      ? '正在应用背景到当前场景…'
      : '正在复制背景并应用到当前场景…');
    try {
      if (!item.registered_in_current) await this.transfer.copy(item);
      const labels = item.details && item.details.labels || {};
      const selectedLabel = String(labels.label || item.name || item.aa_key || '');
      const result = await exports.Api.request(
        '/api/preflight/background-binding',
        exports.Api.json('POST', {
          story_token: this.context.story_token,
          selector: target.selector,
          binding: {aa_key: String(item.aa_key), selected_label: selectedLabel}
        })
      );
      const detail = {
        story_token: this.context.story_token,
        kind: 'background',
        aa_key: String(item.aa_key),
        preflight_snapshot: result.preflight_snapshot,
        context: Object.assign({}, this.context)
      };
      await this.close();
      if (exports.dispatchEvent && typeof CustomEvent === 'function') {
        exports.dispatchEvent(new CustomEvent('assetworkbench:background-applied', {
          detail: detail
        }));
      }
      return result;
    } catch (error) {
      this.setCopyState(String(error.e || error.message || '背景未能应用到当前场景，请重试。'));
      throw error;
    }
  };

  AssetWorkbench.prototype.renderBackgroundLabelEditor = function (item) {
    const details = item.details || (item.details = {});
    const labels = details.labels || {};
    const statusLabels = {
      labeling: 'AI 标注中', ready: '已标注', failed: '标注失败', not_labeled: '待标注'
    };
    const form = make('section', 'background-label-editor');
    const heading = make('div', 'background-label-heading');
    heading.appendChild(make('h4', '', '场景语义'));
    heading.appendChild(make(
      'span', 'background-label-status status-' + String(details.label_status || 'not_labeled'),
      statusLabels[details.label_status] || '待标注'
    ));
    form.appendChild(heading);
    if (details.label_error) form.appendChild(make('p', 'background-label-error', details.label_error));
    const fields = [
      ['label', '场景名称'], ['description', '画面描述'], ['place', '地点'],
      ['indoor_outdoor', '室内外'], ['time', '时间'], ['weather', '天气'],
      ['season', '季节'], ['mood', '氛围'], ['tags', '匹配标签']
    ];
    const controls = {};
    const grid = make('div', 'background-label-fields');
    fields.forEach(function (entry) {
      const wrapper = make('label', entry[0] === 'description' ? 'is-wide' : '');
      wrapper.appendChild(make('span', '', entry[1]));
      const control = document.createElement(entry[0] === 'description' ? 'textarea' : 'input');
      if (entry[0] !== 'description') control.type = 'text';
      control.value = String(labels[entry[0]] || '');
      control.maxLength = entry[0] === 'description' ? 500 : entry[0] === 'tags' ? 960 : 160;
      control.dataset.backgroundLabelField = entry[0];
      controls[entry[0]] = control;
      wrapper.appendChild(control);
      grid.appendChild(wrapper);
    });
    form.appendChild(grid);
    const actions = make('div', 'background-label-actions');
    const recognize = make('button', 'ghost', 'AI 识别场景');
    recognize.type = 'button';
    recognize.disabled = details.label_status === 'labeling';
    recognize.addEventListener('click', function () {
      this.retryBackgroundLabels(item, recognize);
    }.bind(this));
    const save = make('button', '', '保存标注');
    save.type = 'button';
    save.addEventListener('click', async function () {
      save.disabled = true;
      const nextLabels = {};
      Object.keys(controls).forEach(function (key) {
        nextLabels[key] = controls[key].value.trim();
      });
      try {
        const result = await exports.Api.request('/api/assets/library/background-labels', exports.Api.json('POST', {
          aa_key: item.aa_key, sha256: item.sha256, labels: nextLabels
        }));
        details.labels = result.labels || {};
        details.label_status = result.label_status || 'ready';
        details.label_error = result.label_error || '';
        this.setCopyState('背景标注已保存。');
        this.select(item._assetKey);
      } catch (error) {
        this.setCopyState(String(error.e || error.message || '背景标注保存失败，请重试。'));
      } finally {
        save.disabled = false;
      }
    }.bind(this));
    actions.appendChild(recognize);
    actions.appendChild(save);
    form.appendChild(actions);
    this.detail.appendChild(form);
  };

  AssetWorkbench.prototype.retryBackgroundLabels = async function (item, trigger) {
    if (trigger) trigger.disabled = true;
    this.setCopyState('正在启动背景场景识别…');
    try {
      const queued = await exports.Api.request('/api/assets/library/background-label', exports.Api.json('POST', {
        aa_key: item.aa_key, sha256: item.sha256
      }));
      item.details = item.details || {};
      item.details.label_status = queued.status || 'labeling';
      item.details.label_error = '';
      this.select(item._assetKey);
      if (!queued.job_id) return;
      const job = await exports.Api.poll('/api/jobs/' + encodeURIComponent(queued.job_id), function (value) {
        return ['succeeded', 'failed', 'cancelled'].includes(value.state);
      }, {isCurrent: function () { return this.isOpen(); }.bind(this)});
      await this.refresh();
      this.setCopyState(job && job.state === 'succeeded'
        ? '背景场景识别完成。'
        : '背景已登记，AI 标注失败，可手动补充。');
    } catch (error) {
      this.setCopyState(String(error.e || error.message || '背景场景识别启动失败，请重试。'));
      await this.refresh();
    }
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
    const queue = this.context.tasks || [];
    const job = this.faceJob || {};
    const hasFaceJob = Boolean(job.running || job.done || job.ident || job.error);
    if (!queue.length && !hasFaceJob && !this.faceJobError) {
      this.tasks.appendChild(make('p', 'asset-workbench-empty', '当前没有待处理的素材任务。'));
      return;
    }
    if (queue.length) {
      this.tasks.appendChild(make('h3', 'asset-task-section-heading', '剧情待处理 · ' + queue.length + ' 项'));
      queue.forEach(function (task) {
        const row = make('section', 'asset-workbench-task');
        row.appendChild(make('b', '', task.requested_name || '待补素材'));
        row.appendChild(make('span', '', task.reason || '需要在当前剧情登记'));
        this.tasks.appendChild(row);
      }, this);
    }
    if (hasFaceJob) this.renderFaceJob(job);
    else if (this.faceJobError) {
      const error = make('section', 'asset-workbench-task asset-face-task is-error');
      error.appendChild(make('b', '', '骨骼表情标注'));
      error.appendChild(make('span', '', this.faceJobError));
      this.tasks.appendChild(error);
    }
  };

  AssetWorkbench.prototype.faceJobAsset = function (job) {
    const ident = String(job && job.ident || '');
    return this.assets.find(function (item) {
      return item.kind === 'character' && String(item.aa_key || '') === ident;
    }) || null;
  };

  AssetWorkbench.prototype.renderFaceJob = function (job) {
    const result = job.result || {};
    const asset = this.faceJobAsset(job);
    const card = make('section', 'asset-workbench-task asset-face-task');
    if (job.running) card.classList.add('is-running');
    else if (job.done && !job.ok) card.classList.add('is-error');
    card.appendChild(make('h3', 'asset-task-section-heading', '骨骼表情标注'));
    card.appendChild(make('b', 'asset-face-task-name', asset ? asset.name : ('角色标识 ' + (job.ident || '未知'))));
    card.appendChild(make('span', 'asset-face-task-phase', job.phase || (job.running ? '处理中' : '已结束')));
    const current = Number(job.current || 0), total = Number(job.total || 0);
    if (total > 0) card.appendChild(make('strong', 'asset-face-task-progress', current + ' / ' + total));
    const stats = make('div', 'asset-face-task-stats');
    [
      ['已渲染', result.rendered_count],
      ['AI 标注', result.labeled_count],
      ['数据库', result.saved_count],
      ['失败', result.failed_count]
    ].forEach(function (entry) {
      if (entry[1] === undefined || entry[1] === null) return;
      stats.appendChild(make('span', '', entry[0] + ' ' + Number(entry[1] || 0)));
    });
    if (stats.children.length) card.appendChild(stats);
    const failures = Array.isArray(result.failures) ? result.failures : [];
    if (failures.length) {
      const failureList = make('div', 'asset-face-task-log asset-face-task-failures');
      failures.slice(0, 10).forEach(function (failure) {
        const faceId = String(failure && failure.face_id || '未知');
        const reason = String(failure && failure.error || 'vision_label_failed');
        failureList.appendChild(make('span', '', '表情 ' + faceId + '：' + reason));
      });
      card.appendChild(failureList);
    }
    if (result.completed_at) {
      card.appendChild(make('span', 'asset-face-task-completed', '完成时间 ' + result.completed_at));
    }
    const message = job.error || job.message;
    if (message) card.appendChild(make('p', 'asset-face-task-message', message));
    const lines = Array.isArray(job.log) ? job.log.slice(-5) : [];
    if (lines.length) {
      const recent = make('div', 'asset-face-task-log');
      lines.forEach(function (line) { recent.appendChild(make('span', '', line)); });
      card.appendChild(recent);
    }
    if (job.done && job.ok && asset) {
      const view = make('button', 'ghost', '查看标注');
      view.type = 'button';
      view.dataset.workbenchAction = 'view-face-job';
      view.dataset.assetKey = asset._assetKey;
      card.appendChild(view);
    }
    this.tasks.appendChild(card);
  };

  AssetWorkbench.prototype.scheduleTaskRefresh = function (delay, generation) {
    if (this.taskTimer) clearTimeout(this.taskTimer);
    this.taskTimer = setTimeout(function () {
      this.taskTimer = null;
      if (!this.isOpen() || generation !== this.generation) return;
      this.refreshTasks();
    }.bind(this), delay);
  };

  AssetWorkbench.prototype.refreshTasks = function () {
    if (!this.isOpen()) return;
    const generation = this.generation;
    if (this.taskRequest && this.taskRequest.generation === generation) {
      return this.taskRequest.promise;
    }
    const sequence = ++this.taskPollSequence;
    if (this.taskTimer) clearTimeout(this.taskTimer);
    this.taskTimer = null;
    const request = {generation: generation, promise: null};
    request.promise = (async function () {
      try {
        const job = await exports.Api.request('/api/assets/faces/job');
        if (!this.isOpen() || generation !== this.generation || sequence !== this.taskPollSequence) return;
        this.faceJob = job || {};
        this.faceJobError = '';
        this.renderTasks();
        if (this.faceJob.running) this.scheduleTaskRefresh(1000, generation);
      } catch (error) {
        if (!this.isOpen() || generation !== this.generation || sequence !== this.taskPollSequence) return;
        this.faceJobError = '任务状态暂时无法读取，正在自动重试。';
        this.renderTasks();
        this.scheduleTaskRefresh(3000, generation);
      }
    }.bind(this))().finally(function () {
      if (this.taskRequest === request) this.taskRequest = null;
    }.bind(this));
    this.taskRequest = request;
    return request.promise;
  };

  AssetWorkbench.prototype.viewFaceJob = function (trigger) {
    const asset = this.assets.find(function (item) {
      return item._assetKey === String(trigger && trigger.dataset.assetKey || '');
    });
    if (!asset || !exports.FaceWorkspace) return;
    this.selectedKey = asset._assetKey;
    this.select(asset._assetKey);
    exports.FaceWorkspace.open(asset, trigger);
  };

  AssetWorkbench.prototype.toggleTasks = function () {
    if (!this.tasks || !this.taskToggle) return;
    const expanded = this.tasks.classList.contains('is-open');
    this.tasks.classList.toggle('is-open', !expanded);
    this.taskToggle.setAttribute('aria-expanded', String(!expanded));
    if (expanded) return;
    this.refreshTasks();
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
