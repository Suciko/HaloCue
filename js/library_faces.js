/* 骨骼表情标注独立工作区：保持后端任务轮询契约，不参与剧本生成。 */
(function (exports) {
  'use strict';

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }
  function clear(node) { if (node) node.textContent = ''; }

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
    this.labels = document.getElementById('faceWorkspaceLabels');
    this.log = document.getElementById('faceWorkspaceLog');
    this.selected = null;
    this.generation = 0;
    this.timer = null;
    this.pollFailures = 0;
    this.pollSequence = 0;
    this.trigger = null;
    this.returnState = null;
    this.faces = [];
    this.labelsLoadedKey = '';
    this.labelRequest = null;
    this.labelRequestKey = '';
    this.labelRequestSequence = 0;
    this.saveRequests = Object.create(null);
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
      else if (target.dataset.faceAction === 'edit') self.toggleEditor(target.dataset.faceId);
      else if (target.dataset.faceAction === 'save') self.saveFace(target.dataset.faceId);
      else if (target.dataset.faceAction === 'restore-ai') self.restoreAi(target.dataset.faceId);
    });
  };

  FaceWorkspace.prototype.isOpen = function () {
    return Boolean(this.root && this.root.classList.contains('open'));
  };

  FaceWorkspace.prototype.open = function (item, trigger) {
    if (!this.root || !item || item.kind !== 'character') return;
    const workbench = exports.AssetWorkbench;
    this.selected = item;
    this.trigger = trigger || document.activeElement || null;
    this.returnState = workbench ? {
      workbench: workbench,
      selectedKey: workbench.selectedKey,
      scrollTop: workbench.list ? workbench.list.scrollTop : 0
    } : null;
    if (workbench && workbench.root) {
      workbench.root.hidden = true;
      workbench.root.setAttribute('aria-hidden', 'true');
    }
    this.generation += 1;
    this.labelRequestSequence += 1;
    this.saveRequests = Object.create(null);
    this.pollFailures = 0;
    this.pollSequence = 0;
    this.root.classList.add('open');
    if (this.backdrop) this.backdrop.classList.add('open');
    this.root.setAttribute('aria-hidden', 'false');
    this.character.textContent = item.name + ' · Identifier ' + item.aa_key;
    this.phase.textContent = '正在读取骨骼';
    this.progress.textContent = '—';
    this.result.textContent = '尚未生成';
    this.status.textContent = '表情渲染和 AI 语义标注在这里单独执行，不影响剧本生成。';
    this.log.textContent = '';
    this.faces = [];
    this.labelsLoadedKey = '';
    clear(this.labels);
    if (this.startButton) this.startButton.disabled = true;
    if (this.root.focus) this.root.focus();
    this.loadLabels();
    this.refresh();
  };

  FaceWorkspace.prototype.close = async function () {
    this.generation += 1;
    this.labelRequestSequence += 1;
    this.saveRequests = Object.create(null);
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pollFailures = 0;
    this.pollSequence = 0;
    if (!this.root) return;
    this.root.classList.remove('open');
    if (this.backdrop) this.backdrop.classList.remove('open');
    this.root.setAttribute('aria-hidden', 'true');
    const state = this.returnState;
    if (state && state.workbench && state.workbench.root) {
      const workbench = state.workbench;
      workbench.root.hidden = false;
      workbench.root.setAttribute('aria-hidden', 'false');
      workbench.selectedKey = state.selectedKey;
      await workbench.refresh();
      workbench.selectedKey = state.selectedKey;
      workbench.restoreSelection();
      if (workbench.list) workbench.list.scrollTop = state.scrollTop;
      if (workbench.refreshTasks) workbench.refreshTasks();
    }
    if (this.trigger && this.trigger.focus) this.trigger.focus();
  };

  FaceWorkspace.prototype.renderLabels = function (faces) {
    clear(this.labels);
    if (!faces || !faces.length) {
      this.labels.appendChild(make('p', 'face-workspace-empty', '尚无已保存的表情标注。'));
      return;
    }
    faces.forEach(function (face) {
      const value = face.effective || face;
      const card = make('article', 'face-workspace-card');
      card.dataset.faceId = face.face_id || '';
      if (face.preview_url) {
        const image = document.createElement('img'); image.src = face.preview_url;
        image.alt = '表情 ' + face.face_id; image.loading = 'lazy'; card.appendChild(image);
      }
      const body = make('div', 'face-workspace-card-body');
      const heading = make('header', '');
      heading.appendChild(make('b', '', '表情 ' + (face.face_id || '—')));
      if (Number(value.confidence || 0) < 0.6) {
        heading.appendChild(make('span', 'face-review-mark', '需复核'));
      }
      body.appendChild(heading);
      body.appendChild(make('h4', '', value.primary_emotion || '未命名'));
      body.appendChild(make('p', 'face-usage', value.usage_hint_cn || value.description_cn || '暂无使用语境'));
      const actions = make('div', 'face-card-actions');
      const edit = make('button', 'ghost', '修改标注'); edit.type = 'button'; edit.dataset.faceAction = 'edit'; edit.dataset.faceId = face.face_id; actions.appendChild(edit);
      if (face.reviewed) actions.appendChild(make('span', 'face-manual-mark', '人工修改'));
      body.appendChild(actions);
      const editor = make('div', 'face-card-editor'); editor.hidden = true;
      [['primary_emotion', '情绪名称'], ['usage_hint_cn', '使用语境']].forEach(function (entry) {
        const label = make('label', '', entry[1]);
        const input = document.createElement(entry[0] === 'usage_hint_cn' ? 'textarea' : 'input');
        input.dataset.faceField = entry[0];
        input.value = entry[0] === 'usage_hint_cn'
          ? (value.usage_hint_cn || value.description_cn || '')
          : (value[entry[0]] || '');
        label.appendChild(input); editor.appendChild(label);
      });
      const save = make('button', '', '保存'); save.type = 'button'; save.dataset.faceAction = 'save'; save.dataset.faceId = face.face_id; editor.appendChild(save);
      if (face.reviewed) { const restore = make('button', 'ghost', '恢复 AI 原值'); restore.type = 'button'; restore.dataset.faceAction = 'restore-ai'; restore.dataset.faceId = face.face_id; editor.appendChild(restore); }
      editor.appendChild(make('span', 'face-save-state', ''));
      body.appendChild(editor); card.appendChild(body); this.labels.appendChild(card);
    }, this);
  };

  FaceWorkspace.prototype.loadLabels = async function (force) {
    if (!this.selected) return;
    const generation = this.generation;
    const requestKey = String(this.selected.aa_key || '') + ':' + String(this.selected.sha256 || '');
    if (!force && this.labelRequest && this.labelRequestKey === requestKey) return this.labelRequest;
    const sequence = ++this.labelRequestSequence;
    const query = '?aa_key=' + encodeURIComponent(this.selected.aa_key) + '&sha256=' + encodeURIComponent(this.selected.sha256 || '');
    const request = exports.Api.request('/api/assets/faces/labels' + query);
    this.labelRequest = request;
    this.labelRequestKey = requestKey;
    try {
      const payload = await request;
      const currentKey = this.selected
        ? String(this.selected.aa_key || '') + ':' + String(this.selected.sha256 || '')
        : '';
      if (!this.isOpen() || generation !== this.generation || currentKey !== requestKey || sequence !== this.labelRequestSequence) return;
      this.faces = payload.faces || [];
      this.renderLabels(this.faces);
      if (payload.saved_count) this.status.textContent = '已保存到数据库：' + payload.saved_count + ' 个表情。';
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation || sequence !== this.labelRequestSequence) return;
      this.status.textContent = '标注结果读取失败，请刷新后重试。';
    } finally {
      if (this.labelRequest === request) {
        this.labelRequest = null;
        this.labelRequestKey = '';
      }
    }
  };

  FaceWorkspace.prototype.card = function (faceId) {
    return this.labels && this.labels.querySelector ? this.labels.querySelector('[data-face-id="' + String(faceId).replace(/"/g, '\\"') + '"]') : null;
  };

  FaceWorkspace.prototype.toggleEditor = function (faceId) {
    const card = this.card(faceId), editor = card && card.querySelector('.face-card-editor');
    if (editor) editor.hidden = !editor.hidden;
  };

  FaceWorkspace.prototype.saveFace = function (faceId, restore) {
    const saveKey = String(faceId);
    const card = this.card(faceId), face = this.faces.find(function (item) { return String(item.face_id) === String(faceId); });
    if (!card || !face) return;
    const patch = {};
    if (!restore) {
      const effective = face.effective || face;
      Array.from(card.querySelectorAll('[data-face-field]')).forEach(function (input) {
        const field = input.dataset.faceField;
        const next = input.type === 'checkbox' ? Boolean(input.checked) : input.value.trim();
        const current = field === 'usage_hint_cn'
          ? (Object.prototype.hasOwnProperty.call(effective, field) ? effective[field] : effective.description_cn)
          : effective[field];
        if (next !== (input.type === 'checkbox' ? Boolean(current) : String(current || '').trim())) patch[field] = next;
      });
    }
    const state = card.querySelector('.face-save-state'); if (state) state.textContent = '保存中…';
    const generation = this.generation;
    const aaKey = String(this.selected.aa_key || '');
    const sha256 = String(this.selected.sha256 || '');
    const previous = this.saveRequests[saveKey];
    let operation;
    const executeSave = (async function () {
      const selected = this.selected || {};
      if (!this.isOpen() || generation !== this.generation || aaKey !== String(selected.aa_key || '') || sha256 !== String(selected.sha256 || '')) return;
      const currentFace = this.faces.find(function (item) { return String(item.face_id) === String(faceId); });
      if (!currentFace) return;
      const requestPatch = restore ? {} : patch;
      if (restore) Object.keys(currentFace.manual || {}).forEach(function (key) { requestPatch[key] = null; });
      try {
        const result = await exports.Api.request('/api/assets/faces/labels/' + encodeURIComponent(faceId), exports.Api.json('PATCH', {aa_key:aaKey,sha256:sha256,version:currentFace.version,patch:requestPatch}));
        const current = this.selected || {};
        if (!this.isOpen() || generation !== this.generation || aaKey !== String(current.aa_key || '') || sha256 !== String(current.sha256 || '')) return;
        this.faces = this.faces.map(function (item) { return String(item.face_id) === String(faceId) ? result.face : item; });
        this.renderLabels(this.faces); this.status.textContent = '已保存到数据库：表情 ' + faceId + '，' + (result.saved_at || '刚刚') + '。';
      } catch (error) {
        const current = this.selected || {};
        if (generation === this.generation && aaKey === String(current.aa_key || '') && sha256 === String(current.sha256 || '') && state) state.textContent = '保存失败，请刷新后重试。';
      } finally {
        if (this.saveRequests[saveKey] === operation) delete this.saveRequests[saveKey];
      }
    }).bind(this);
    operation = previous
      ? previous.catch(function () {}).then(executeSave)
      : executeSave();
    this.saveRequests[saveKey] = operation;
    return operation;
  };

  FaceWorkspace.prototype.restoreAi = function (faceId) { return this.saveFace(faceId, true); };

  FaceWorkspace.prototype.renderJob = function (job) {
    const selected = this.selected;
    const belongsToSelected = selected && String(job.ident || '') === String(selected.aa_key || '');
    if (!belongsToSelected && job.running) {
      this.phase.textContent = '另一项骨骼正在处理'; this.progress.textContent = '等待队列'; this.result.textContent = '未开始';
      this.status.textContent = '当前一次只能处理一个骨骼。上一项完成后可在此重新开始。'; this.startButton.disabled = true; return true;
    }
    if (!belongsToSelected) {
      this.startButton.disabled = false;
      this.phase.textContent = '等待开始'; this.progress.textContent = '—'; this.result.textContent = '尚未生成'; return false;
    }
    this.startButton.disabled = Boolean(job.running);
    this.phase.textContent = job.phase || (job.running ? '处理中' : '等待开始');
    const current = Number(job.current || 0), total = Number(job.total || 0);
    this.progress.textContent = total > 0 ? current + ' / ' + total : (job.running ? '处理中' : '—');
    const result = job.result || {};
    if (job.done && job.ok) {
      const rendered = Number(result.rendered_count || 0), labeled = Number(result.labeled_count || 0), saved = Number(result.saved_count || 0);
      this.result.textContent = rendered + ' 个差分' + (labeled ? ' · ' + labeled + ' 个 AI 标注' : '') + (saved ? ' · ' + saved + ' 个已保存' : '');
    } else if (job.done && !job.ok) this.result.textContent = '处理失败';
    else this.result.textContent = '处理中';
    this.status.textContent = job.message || (job.error ? '表情标注失败，请检查 Spine 配置与骨骼完整性。' : '');
    this.log.textContent = (job.log || []).join('\n');
    if (!this.faces.length) this.renderLabels(result.semantic_faces || []);
    if (job.done && job.ok && Number(result.saved_count || result.labeled_count || 0)) {
      const key = [job.ident, result.completed_at || result.saved_count || result.labeled_count].join(':');
      if (this.labelsLoadedKey !== key) { this.labelsLoadedKey = key; this.loadLabels(true); }
    }
    return Boolean(job.running);
  };

  FaceWorkspace.prototype.scheduleRefresh = function (delay, generation) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(function () {
      this.timer = null;
      if (!this.isOpen() || generation !== this.generation) return;
      this.refresh();
    }.bind(this), delay);
  };

  FaceWorkspace.prototype.refresh = async function () {
    const generation = this.generation;
    const sequence = ++this.pollSequence;
    if (!this.isOpen() || !this.selected) return;
    try {
      const job = await exports.Api.request('/api/assets/faces/job');
      if (!this.isOpen() || generation !== this.generation || sequence !== this.pollSequence) return;
      this.pollFailures = 0;
      const running = this.renderJob(job || {});
      if (running) this.scheduleRefresh(850, generation);
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation || sequence !== this.pollSequence) return;
      this.pollFailures += 1;
      if (this.startButton) this.startButton.disabled = true;
      this.status.textContent = '进度连接暂时中断，正在自动重试（第 ' + this.pollFailures + ' 次）。';
      const delay = Math.min(8000, 850 * Math.pow(2, this.pollFailures));
      this.scheduleRefresh(delay, generation);
    }
  };

  FaceWorkspace.prototype.start = async function () {
    if (!this.selected || (this.startButton && this.startButton.disabled)) return;
    if (this.startButton) this.startButton.disabled = true;
    this.phase.textContent = '正在生成联系表';
    try {
      const response = await exports.Api.request('/api/assets/library/character/face-analysis', exports.Api.json('POST', {
        aa_key: this.selected.aa_key, sha256: this.selected.sha256,
        force_vision: Boolean(this.forceVision && this.forceVision.checked)
      }));
      if (response.ok) {
        this.phase.textContent = 'AI 正在识别表情';
        this.status.textContent = response.message || '已加入表情标注队列。'; this.refresh();
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
  exports.StoryUI.FaceWorkspace = FaceWorkspace;
  if (document.getElementById) {
    const root = document.getElementById('faceWorkspace');
    if (root) exports.FaceWorkspace = new FaceWorkspace(root);
  }
})(window);
