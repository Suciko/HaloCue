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
    this.sheet = document.getElementById('faceWorkspaceSheet');
    this.labels = document.getElementById('faceWorkspaceLabels');
    this.log = document.getElementById('faceWorkspaceLog');
    this.selected = null;
    this.generation = 0;
    this.timer = null;
    this.pollFailures = 0;
    this.trigger = null;
    this.returnState = null;
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
    this.pollFailures = 0;
    this.root.classList.add('open');
    if (this.backdrop) this.backdrop.classList.add('open');
    this.root.setAttribute('aria-hidden', 'false');
    this.character.textContent = item.name + ' · Identifier ' + item.aa_key;
    this.phase.textContent = '正在读取骨骼';
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

  FaceWorkspace.prototype.close = async function () {
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pollFailures = 0;
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
    }
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
      this.phase.textContent = '另一项骨骼正在处理'; this.progress.textContent = '等待队列'; this.result.textContent = '未开始';
      this.status.textContent = '当前一次只能处理一个骨骼。上一项完成后可在此重新开始。'; this.startButton.disabled = true; return false;
    }
    this.startButton.disabled = false;
    if (!belongsToSelected) {
      this.phase.textContent = '等待开始'; this.progress.textContent = '—'; this.result.textContent = '尚未生成'; this.renderLabels([]); return false;
    }
    this.phase.textContent = job.phase || (job.running ? '处理中' : '等待开始');
    const current = Number(job.current || 0), total = Number(job.total || 0);
    this.progress.textContent = total > 0 ? current + ' / ' + total : (job.running ? '处理中' : '—');
    const result = job.result || {};
    if (job.done && job.ok) {
      const rendered = Number(result.rendered_count || 0), labeled = Number(result.labeled_count || 0);
      this.result.textContent = rendered + ' 个差分' + (labeled ? ' · ' + labeled + ' 个 AI 标注' : '');
    } else if (job.done && !job.ok) this.result.textContent = '处理失败';
    else this.result.textContent = '处理中';
    this.status.textContent = job.message || (job.error ? '表情标注失败，请检查 Spine 配置与骨骼完整性。' : '');
    this.log.textContent = (job.log || []).join('\n');
    this.renderLabels(result.semantic_faces || []);
    if (job.contact_sheet_available && job.done && job.ok) {
      this.sheet.hidden = false;
      this.sheet.src = '/api/assets/faces/contact-sheet?ts=' + Date.now();
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
    if (!this.isOpen() || !this.selected) return;
    try {
      const job = await exports.Api.request('/api/assets/faces/job');
      if (!this.isOpen() || generation !== this.generation) return;
      this.pollFailures = 0;
      const running = this.renderJob(job || {});
      if (running) this.scheduleRefresh(850, generation);
    } catch (error) {
      if (!this.isOpen() || generation !== this.generation) return;
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
