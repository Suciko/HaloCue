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

  function AssetWorkbench(root) {
    this.root = root;
    this.appShell = document.getElementById('appShell');
    this.contextLabel = document.getElementById('assetWorkbenchContext');
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
    this.preview = new exports.StoryUI.AssetPreview(this.detail);
    this.transfer = new exports.StoryUI.TransferController(this);
    this.copies = new exports.StoryUI.CopyManager(this);
    this.bind();
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
      else if (action === 'toggle-tasks') self.toggleTasks();
      else if (action === 'select') self.select(target.dataset.assetKey);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) self.close();
    });
  };

  AssetWorkbench.prototype.isOpen = function () {
    return Boolean(this.root && !this.root.hidden);
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

  AssetWorkbench.prototype.renderCatalog = function () {
    clear(this.list);
    if (!this.list) return;
    if (!this.assets.length) {
      const empty = make('p', 'asset-workbench-empty', '素材完成导入登记后会出现在这里。');
      this.list.appendChild(empty);
      return;
    }
    this.assets.forEach(function (item) {
      const button = make('button', 'asset-workbench-row');
      button.type = 'button';
      button.dataset.workbenchAction = 'select';
      button.dataset.assetKey = item._assetKey;
      button.appendChild(make('b', 'asset-name', item.name || String(item.aa_key || '未命名素材')));
      button.appendChild(make('span', 'asset-kind', kindLabel(item.kind)));
      button.appendChild(make('span', 'asset-state', item.registered_in_current ? '本章已登记' : '未登记'));
      this.list.appendChild(button);
    }, this);
  };

  AssetWorkbench.prototype.restoreSelection = function () {
    if (!this.assets.some(function (item) { return item._assetKey === this.selectedKey; }, this)) {
      this.selectedKey = this.assets.length ? this.assets[0]._assetKey : null;
    }
    this.select(this.selectedKey);
  };

  AssetWorkbench.prototype.select = function (key) {
    this.selectedKey = key || null;
    this.preview.render(this.selected());
  };

  AssetWorkbench.prototype.selected = function () {
    return this.assets.find(function (item) { return item._assetKey === this.selectedKey; }, this) || null;
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

  function FaceWorkspace(root) {
    this.root = root;
    this.backdrop = document.getElementById('faceWorkspaceBackdrop');
    this.character = document.getElementById('faceWorkspaceCharacter');
    this.phase = document.getElementById('faceWorkspacePhase');
    this.progress = document.getElementById('faceWorkspaceProgress');
    this.result = document.getElementById('faceWorkspaceResult');
    this.forceVision = document.getElementById('faceWorkspaceForceVision');
    this.startButton = document.getElementById('faceWorkspaceStart');
    this.status = document.getElementById('faceWorkspaceStatus');
    this.sheet = document.getElementById('faceWorkspaceSheet');
    this.labels = document.getElementById('faceWorkspaceLabels');
    this.log = document.getElementById('faceWorkspaceLog');
    this.selected = null;
    this.generation = 0;
    this.timer = null;
    this.trigger = null;
    this.bind();
  }

  FaceWorkspace.prototype.bind = function () {
    const self = this;
    document.addEventListener('click', function (event) {
      const target = event.target && event.target.closest
        ? event.target.closest('[data-face-action]')
        : null;
      if (!target || target.disabled) return;
      if (target.dataset.faceAction === 'close') self.close();
      else if (target.dataset.faceAction === 'start') self.start();
    });
  };

  FaceWorkspace.prototype.isOpen = function () {
    return Boolean(this.root && this.root.classList.contains('open'));
  };

  FaceWorkspace.prototype.open = function (item, trigger) {
    if (!this.root || !item || item.kind !== 'character') return;
    this.selected = item;
    this.trigger = trigger || document.activeElement || null;
    this.generation += 1;
    this.root.classList.add('open');
    if (this.backdrop) this.backdrop.classList.add('open');
    this.root.setAttribute('aria-hidden', 'false');
    this.character.textContent = item.name + ' · Identifier ' + item.aa_key;
    this.phase.textContent = '正在读取任务状态';
    this.progress.textContent = '—';
    this.result.textContent = '尚未生成';
    this.status.textContent = '表情渲染和 AI 语义标注在这里单独执行，不影响剧本生成。';
    this.log.textContent = '';
    this.sheet.hidden = true;
    this.sheet.removeAttribute('src');
    clear(this.labels);
    if (this.root.focus) this.root.focus();
    this.refresh();
  };

  FaceWorkspace.prototype.close = function () {
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (!this.root) return;
    this.root.classList.remove('open');
    if (this.backdrop) this.backdrop.classList.remove('open');
    this.root.setAttribute('aria-hidden', 'true');
    if (this.trigger && this.trigger.focus) this.trigger.focus();
  };

  FaceWorkspace.prototype.renderLabels = function (faces) {
    clear(this.labels);
    if (!faces || !faces.length) {
      this.labels.appendChild(make('p', 'face-workspace-empty', '等待渲染完成后显示表情语义。'));
      return;
    }
    faces.forEach(function (face) {
      const row = make('article', 'face-workspace-label');
      row.appendChild(make('b', '', face.face_id || '—'));
      const words = [face.primary_emotion].concat(face.semantic_labels || []).filter(Boolean);
      row.appendChild(make('span', '', words.length ? Array.from(new Set(words)).join(' · ') : '未命名'));
      this.labels.appendChild(row);
    }, this);
  };

  FaceWorkspace.prototype.renderJob = function (job) {
    const selected = this.selected;
    const belongsToSelected = selected && String(job.ident || '') === String(selected.aa_key || '');
    if (!belongsToSelected && job.running) {
      this.phase.textContent = '另一项骨骼正在处理';
      this.progress.textContent = '等待队列';
      this.result.textContent = '未开始';
      this.status.textContent = '当前一次只能处理一个骨骼。上一项完成后可在此重新开始。';
      this.startButton.disabled = true;
      return false;
    }
    this.startButton.disabled = false;
    if (!belongsToSelected) {
      this.phase.textContent = '等待开始';
      this.progress.textContent = '—';
      this.result.textContent = '尚未生成';
      this.renderLabels([]);
      return false;
    }
    this.phase.textContent = job.phase || (job.running ? '处理中' : '等待开始');
    const current = Number(job.current || 0), total = Number(job.total || 0);
    this.progress.textContent = total > 0 ? current + ' / ' + total : (job.running ? '处理中' : '—');
    const result = job.result || {};
    if (job.done && job.ok) {
      const rendered = Number(result.rendered_count || 0);
      const labeled = Number(result.labeled_count || 0);
      this.result.textContent = rendered + ' 个差分' + (labeled ? ' · ' + labeled + ' 个 AI 标注' : '');
    } else if (job.done && !job.ok) {
      this.result.textContent = '处理失败';
    } else {
      this.result.textContent = '处理中';
    }
    this.status.textContent = job.message || (job.error ? '表情标注失败，请检查 Spine 配置与骨骼完整性。' : '');
    this.log.textContent = (job.log || []).join('\n');
    this.renderLabels(result.semantic_faces || []);
    if (job.contact_sheet_available && job.done && job.ok) {
      this.sheet.hidden = false;
      this.sheet.src = '/api/assets/faces/contact-sheet?ts=' + Date.now();
    }
    return Boolean(job.running);
  };

  FaceWorkspace.prototype.refresh = async function () {
    const generation = this.generation;
    if (!this.isOpen() || !this.selected) return;
    try {
      const job = await exports.Api.request('/api/assets/faces/job');
      if (!this.isOpen() || generation !== this.generation) return;
      const running = this.renderJob(job || {});
      if (running) this.timer = setTimeout(function () { this.refresh(); }.bind(this), 850);
    } catch (error) {
      if (generation === this.generation) this.status.textContent = '无法读取表情标注进度，请重试。';
    }
  };

  FaceWorkspace.prototype.start = async function () {
    if (!this.selected || (this.startButton && this.startButton.disabled)) return;
    if (this.startButton) this.startButton.disabled = true;
    try {
      const response = await exports.Api.request(
        '/api/assets/library/character/face-analysis',
        exports.Api.json('POST', {
          aa_key: this.selected.aa_key,
          sha256: this.selected.sha256,
          force_vision: Boolean(this.forceVision && this.forceVision.checked)
        })
      );
      if (response.ok) {
        this.status.textContent = response.message || '已加入表情标注队列。';
        this.refresh();
      } else {
        if (this.startButton) this.startButton.disabled = false;
        this.status.textContent = response.message || '暂时无法开始表情标注。';
      }
    } catch (error) {
      if (this.startButton) this.startButton.disabled = false;
      this.status.textContent = '表情标注无法开始，请检查骨骼文件后重试。';
    }
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.AssetWorkbench = AssetWorkbench;
  exports.StoryUI.AssetLibraryWorkbench = AssetWorkbench;
  exports.StoryUI.FaceWorkspace = FaceWorkspace;
  exports.sanitizeWorkbenchContext = sanitizeWorkbenchContext;
  exports.flattenLibraryPayload = flattenLibraryPayload;
  exports.openAssetWorkbench = function (context) {
    return exports.AssetWorkbench ? exports.AssetWorkbench.open(context) : undefined;
  };
  if (document.getElementById) {
    const faceRoot = document.getElementById('faceWorkspace');
    if (faceRoot) exports.FaceWorkspace = new FaceWorkspace(faceRoot);
    const root = document.getElementById('assetWorkbench');
    if (root) {
      exports.AssetWorkbench = new AssetWorkbench(root);
      exports.AssetLibraryWorkbench = exports.AssetWorkbench;
    }
  }
})(window);
