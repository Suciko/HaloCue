/* 跨章节自定义素材履历。它只管理分类，不替代当前剧情的独立素材登记。 */
(function (exports) {
  'use strict';

  const KINDS = [
    {kind: 'character', bucket: 'characters', label: '骨骼角色'},
    {kind: 'background', bucket: 'backgrounds', label: '背景'},
    {kind: 'sound', bucket: 'sounds', label: '音效'},
    {kind: 'bgm', bucket: 'bgms', label: 'BGM'}
  ];

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }
  function clear(node) { node.textContent = ''; }
  function kindInfo(kind) {
    return KINDS.find(function (item) { return item.kind === kind; }) || KINDS[0];
  }
  function flatten(data) {
    const rows = [];
    KINDS.forEach(function (info) {
      (Array.isArray(data && data[info.bucket]) ? data[info.bucket] : []).forEach(function (item) {
        if (!item || item.kind !== info.kind) return;
        item._libraryIndex = rows.length;
        rows.push(item);
      });
    });
    return rows;
  }
  function currentStory() {
    return exports.StoryStore && exports.StoryStore.get ? exports.StoryStore.get() : null;
  }
  function searchable(item) {
    return [item.name, item.aa_key, item.series_name].concat(item.chapters || []).join(' ').toLocaleLowerCase();
  }
  function labelSummary(labels) {
    if (!labels || typeof labels !== 'object') return '';
    return Object.keys(labels).map(function (key) {
      const value = Array.isArray(labels[key]) ? labels[key].join('、') : labels[key];
      return String(value || '');
    }).filter(Boolean).join(' · ');
  }
  function detailSummary(item) {
    const details = item.details || {};
    if (item.kind === 'character') {
      const faces = Number(details.face_count || 0);
      return faces > 0 ? '已识别 ' + faces + ' 个表情候选' : '表情标注待检测';
    }
    if (item.kind === 'background') {
      return [details.resolution, labelSummary(details.labels)].filter(Boolean).join(' · ') || '背景信息待检测';
    }
    if (item.kind === 'sound') {
      const seconds = Number(details.duration || 0);
      return [seconds > 0 ? seconds.toFixed(2) + ' 秒' : '', details.codec || '', labelSummary(details.labels)].filter(Boolean).join(' · ') || '音频信息待检测';
    }
    return '';
  }

  function AssetLibraryWorkbench(root) {
    this.root = root;
    this.backdrop = document.getElementById('assetLibraryBackdrop');
    this.list = document.getElementById('assetLibraryList');
    this.summary = document.getElementById('assetLibrarySummary');
    this.status = document.getElementById('assetLibraryStatus');
    this.search = document.getElementById('assetLibrarySearch');
    this.kind = document.getElementById('assetLibraryKind');
    this.role = document.getElementById('assetLibraryRole');
    this.currentButton = document.getElementById('assetLibraryUseCurrent');
    this.items = [];
    this.loading = false;
    this.trigger = null;
    this.generation = 0;
    this.bind();
  }

  AssetLibraryWorkbench.prototype.bind = function () {
    const self = this;
    document.addEventListener('click', function (event) {
      const target = event.target && event.target.closest ? event.target.closest('[data-library-action]') : null;
      if (!target || target.disabled) return;
      const action = target.dataset.libraryAction;
      if (action === 'open') self.open(target);
      else if (action === 'close') self.close();
      else if (action === 'save') self.save(target);
      else if (action === 'retry') self.load();
      else if (action === 'focus-current') self.focusCurrentStoryAssets();
      else if (action === 'faces') {
        const item = self.items[Number(target.dataset.libraryIndex)];
        if (item && exports.FaceWorkspace && exports.FaceWorkspace.open) exports.FaceWorkspace.open(item, target);
      }
    });
    if (this.root) {
      this.root.addEventListener('change', function (event) {
        const target = event.target;
        if (target === self.kind || target === self.role) self.render();
        if (target && target.dataset && target.dataset.libraryField === 'asset-role') {
          const card = target.closest('.asset-library-card');
          const series = card && card.querySelector('[data-library-field="series-name"]');
          if (series) {
            series.disabled = target.value !== 'series_shared';
            if (series.disabled) series.value = '';
          }
        }
      });
    }
    if (this.search) this.search.addEventListener('input', function () { self.render(); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) self.close();
    });
  };

  AssetLibraryWorkbench.prototype.isOpen = function () {
    return Boolean(this.root && this.root.classList.contains('open'));
  };
  AssetLibraryWorkbench.prototype.open = function (trigger) {
    if (!this.root) return;
    this.trigger = trigger || document.activeElement || null;
    this.root.classList.add('open');
    this.backdrop.classList.add('open');
    this.root.setAttribute('aria-hidden', 'false');
    if (this.root.focus) this.root.focus();
    this.load();
  };
  AssetLibraryWorkbench.prototype.close = function (options) {
    options = options || {};
    if (!this.root) return;
    this.generation += 1;
    this.root.classList.remove('open');
    this.backdrop.classList.remove('open');
    this.root.setAttribute('aria-hidden', 'true');
    if (options.restore !== false && this.trigger && this.trigger.focus) this.trigger.focus();
  };
  AssetLibraryWorkbench.prototype.focusCurrentStoryAssets = function () {
    const strip = document.getElementById('storyAssetStrip');
    if (!currentStory() || !strip) return;
    this.close({restore: false});
    if (strip.scrollIntoView) strip.scrollIntoView({behavior: 'smooth', block: 'start'});
    strip.classList.add('asset-strip-attention');
    setTimeout(function () { strip.classList.remove('asset-strip-attention'); }, 1400);
  };
  AssetLibraryWorkbench.prototype.load = async function () {
    const generation = ++this.generation;
    this.loading = true;
    this.items = [];
    this.status.textContent = '正在读取自定义素材履历…';
    this.render();
    try {
      const result = await exports.Api.request('/api/assets/library');
      if (!this.isOpen() || generation !== this.generation) return;
      this.items = flatten(result);
      this.loading = false;
      this.status.textContent = this.items.length ? '已读取，只显示自定义登记素材。' : '';
      this.render();
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation) return;
      this.loading = false;
      this.status.textContent = '素材履历读取失败：' + error.message;
      this.render(true);
    }
  };
  AssetLibraryWorkbench.prototype.filteredItems = function () {
    const query = String(this.search.value || '').trim().toLocaleLowerCase();
    const kind = this.kind.value || 'all';
    const role = this.role.value || 'all';
    return this.items.filter(function (item) {
      return (kind === 'all' || item.kind === kind) &&
        (role === 'all' || item.asset_role === role) &&
        (!query || searchable(item).includes(query));
    });
  };
  AssetLibraryWorkbench.prototype.renderSummary = function () {
    clear(this.summary);
    const totalCopies = this.items.reduce(function (sum, item) { return sum + Number(item.copy_count || 0); }, 0);
    const values = [
      ['自定义素材', this.items.length],
      ['章节副本', totalCopies],
      ['系列共用', this.items.filter(function (item) { return item.asset_role === 'series_shared'; }).length],
      ['章节专用', this.items.filter(function (item) { return item.asset_role !== 'series_shared'; }).length]
    ];
    values.forEach(function (entry) {
      const block = make('div', 'asset-library-stat');
      block.appendChild(make('b', '', String(entry[1])));
      block.appendChild(make('span', '', entry[0]));
      this.summary.appendChild(block);
    }, this);
  };
  AssetLibraryWorkbench.prototype.renderEmpty = function (failed) {
    const empty = make('section', 'asset-library-empty');
    empty.appendChild(make('h3', '', failed ? '暂时无法读取素材履历' : '没有符合条件的自定义素材'));
    empty.appendChild(make('p', '', failed ? '检查本地服务后重试。' : '素材在某一章完成导入登记后，会出现在这里。'));
    if (failed) {
      const retry = make('button', 'ghost', '重新读取');
      retry.type = 'button'; retry.dataset.libraryAction = 'retry'; empty.appendChild(retry);
    }
    this.list.appendChild(empty);
  };
  AssetLibraryWorkbench.prototype.renderBgmGate = function () {
    const gate = make('section', 'asset-library-empty asset-library-bgm');
    gate.appendChild(make('h3', '', 'BGM 登记暂未开放'));
    gate.appendChild(make('p', '', 'AA 的 BgmOverrides 原生登记与回滚规则尚未验证，因此不会把音乐误标成可复制素材。'));
    this.list.appendChild(gate);
  };
  AssetLibraryWorkbench.prototype.renderCard = function (item) {
    const card = make('article', 'asset-library-card');
    const heading = make('div', 'asset-library-card-heading');
    const title = make('div', 'asset-library-card-title');
    title.appendChild(make('span', 'asset-library-kind', kindInfo(item.kind).label));
    title.appendChild(make('h3', '', item.name || String(item.aa_key || '未命名素材')));
    heading.appendChild(title);
    heading.appendChild(make('span', 'asset-library-role ' + (item.asset_role === 'series_shared' ? 'is-shared' : ''), item.asset_role === 'series_shared' ? '系列共用' : '章节专用'));
    card.appendChild(heading);
    const detail = detailSummary(item);
    if (detail) card.appendChild(make('p', 'asset-library-detail', detail));
    const chapters = make('div', 'asset-library-chapters');
    chapters.appendChild(make('b', '', '已登记章节 ' + Number(item.copy_count || 0)));
    (item.chapters || []).forEach(function (chapter) { chapters.appendChild(make('span', '', chapter)); });
    card.appendChild(chapters);
    const form = make('div', 'asset-library-profile');
    const roleLabel = make('label', ''); roleLabel.appendChild(make('span', '', '素材归属'));
    const role = make('select'); role.dataset.libraryField = 'asset-role';
    [['chapter_only', '章节专用'], ['series_shared', '系列共用']].forEach(function (entry) {
      const option = make('option', '', entry[1]); option.value = entry[0]; role.appendChild(option);
    });
    role.value = item.asset_role || 'chapter_only'; roleLabel.appendChild(role); form.appendChild(roleLabel);
    const seriesLabel = make('label', ''); seriesLabel.appendChild(make('span', '', '系列名称'));
    const series = make('input'); series.type = 'text'; series.maxLength = 80; series.placeholder = '例如：凯伊约会篇'; series.value = item.series_name || ''; series.disabled = role.value !== 'series_shared'; series.dataset.libraryField = 'series-name'; seriesLabel.appendChild(series); form.appendChild(seriesLabel);
    const save = make('button', '', '保存分类'); save.type = 'button'; save.dataset.libraryAction = 'save'; save.dataset.libraryIndex = String(item._libraryIndex); form.appendChild(save);
    card.appendChild(form);
    if (item.kind === 'character') {
      const faces = make('button', 'ghost asset-library-faces', '表情标注');
      faces.type = 'button'; faces.dataset.libraryAction = 'faces'; faces.dataset.libraryIndex = String(item._libraryIndex);
      card.appendChild(faces);
    }
    return card;
  };
  AssetLibraryWorkbench.prototype.render = function (failed) {
    if (!this.list) return;
    this.currentButton.disabled = !currentStory();
    this.renderSummary();
    clear(this.list);
    if (this.loading) {
      const loading = make('section', 'asset-library-empty');
      loading.appendChild(make('div', 'asset-library-loader'));
      loading.appendChild(make('p', '', '正在汇总各章节的自定义素材副本…'));
      this.list.appendChild(loading);
      return;
    }
    if (failed) { this.renderEmpty(true); return; }
    if (this.kind.value === 'bgm') { this.renderBgmGate(); return; }
    const items = this.filteredItems();
    if (!items.length) { this.renderEmpty(false); return; }
    items.forEach(function (item) { this.list.appendChild(this.renderCard(item)); }, this);
  };
  AssetLibraryWorkbench.prototype.save = async function (button) {
    const item = this.items[Number(button.dataset.libraryIndex)];
    const card = button.closest('.asset-library-card');
    if (!item || !card) return;
    const role = card.querySelector('[data-library-field="asset-role"]').value;
    const series = card.querySelector('[data-library-field="series-name"]').value.trim();
    if (role === 'series_shared' && !series) {
      this.status.textContent = '请先填写系列名称，再保存系列共用分类。';
      card.querySelector('[data-library-field="series-name"]').focus();
      return;
    }
    button.disabled = true;
    button.textContent = '保存中…';
    this.status.textContent = '正在保存“' + item.name + '”的分类…';
    try {
      const result = await exports.Api.request('/api/assets/library/profile', exports.Api.json('POST', {
        kind: item.kind, aa_key: item.aa_key, sha256: item.sha256,
        asset_role: role, series_name: series
      }));
      item.asset_role = result.asset_role;
      item.series_name = result.series_name;
      this.status.textContent = '已保存“' + item.name + '”的素材分类。';
      this.render();
    } catch (error) {
      button.disabled = false;
      button.textContent = '重新保存';
      this.status.textContent = '分类保存失败：' + error.message;
    }
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
      const target = event.target && event.target.closest ? event.target.closest('[data-face-action]') : null;
      if (!target || target.disabled) return;
      if (target.dataset.faceAction === 'close') self.close();
      else if (target.dataset.faceAction === 'start') self.start();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) self.close();
    });
  };
  FaceWorkspace.prototype.isOpen = function () {
    return Boolean(this.root && this.root.classList.contains('open'));
  };
  FaceWorkspace.prototype.open = function (item, trigger) {
    if (!this.root || !item || item.kind !== 'character') return;
    this.generation += 1;
    this.selected = item;
    this.trigger = trigger || document.activeElement || null;
    this.root.classList.add('open');
    this.backdrop.classList.add('open');
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
  FaceWorkspace.prototype.close = function (options) {
    options = options || {};
    this.generation += 1;
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    if (!this.root) return;
    this.root.classList.remove('open');
    this.backdrop.classList.remove('open');
    this.root.setAttribute('aria-hidden', 'true');
    if (options.restore !== false && this.trigger && this.trigger.focus) this.trigger.focus();
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
      if (running) {
        this.timer = setTimeout(function () { this.refresh(); }.bind(this), 850);
      }
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation) return;
      this.status.textContent = '无法读取表情标注进度：' + error.message;
    }
  };
  FaceWorkspace.prototype.start = async function () {
    if (!this.selected || this.startButton.disabled) return;
    this.startButton.disabled = true;
    this.status.textContent = '正在加入表情标注队列…';
    try {
      const response = await exports.Api.request(
        '/api/assets/library/character/face-analysis',
        exports.Api.json('POST', {
          aa_key: this.selected.aa_key,
          sha256: this.selected.sha256,
          force_vision: Boolean(this.forceVision.checked)
        })
      );
      if (response.ok) {
        this.status.textContent = response.message || '已加入表情标注队列。';
        this.refresh();
      } else {
        this.startButton.disabled = false;
        this.status.textContent = response.message || '暂时无法开始表情标注。';
      }
    } catch (error) {
      this.startButton.disabled = false;
      this.status.textContent = '表情标注无法开始：' + error.message;
    }
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.AssetLibraryWorkbench = AssetLibraryWorkbench;
  exports.StoryUI.FaceWorkspace = FaceWorkspace;
  if (document.getElementById) {
    const faceRoot = document.getElementById('faceWorkspace');
    if (faceRoot) exports.FaceWorkspace = new FaceWorkspace(faceRoot);
    const root = document.getElementById('assetLibraryDrawer');
    if (root) exports.AssetLibraryWorkbench = new AssetLibraryWorkbench(root);
  }
})(window);
