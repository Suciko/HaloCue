(function (exports) {
  'use strict';

  function byId(id) { return document.getElementById(id); }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function button(label, className) {
    const node = document.createElement('button'); node.type = 'button';
    node.className = className || ''; node.textContent = label; return node;
  }
  function formatSize(value) {
    const size = Number(value || 0);
    if (size < 1024) return size + ' B';
    if (size < 1024 * 1024) return (size / 1024).toFixed(size < 10 * 1024 ? 1 : 0) + ' KB';
    return (size / (1024 * 1024)).toFixed(1) + ' MB';
  }
  function formatDate(value) {
    const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', {hour12: false});
  }

  function StoryFilePicker(root, options) {
    this.root = root; this.options = options || {};
    this.source = byId('storyPickerSource'); this.host = byId('storyPickerHost');
    this.input = byId('storyPickerDeviceInput'); this.status = byId('storyPickerStatus');
    this.entries = byId('storyPickerEntries'); this.breadcrumbs = byId('storyPickerBreadcrumbs');
    this.roots = byId('storyPickerRoots'); this.search = byId('storyPickerSearch');
    this.selectedLabel = byId('storyPickerSelected'); this.openButton = byId('storyPickerOpen');
    this.backButton = byId('storyPickerBack'); this.forwardButton = byId('storyPickerForward');
    this.upButton = byId('storyPickerUp');
    this.selected = null; this.locationToken = ''; this.parentToken = '';
    this.historyBack = []; this.historyForward = []; this.sort = 'name'; this.direction = 'asc';
    this.trigger = null; this._bound = false; this.bind();
  }

  StoryFilePicker.prototype.bind = function () {
    if (this._bound) return; this._bound = true; const self = this;
    if (this.input) this.input.addEventListener('change', function (event) { return self.upload(event.target.files && event.target.files[0]); });
    if (this.search) this.search.addEventListener('input', function () { return self.load(self.locationToken, false); });
    if (this.openButton) this.openButton.addEventListener('click', function () { return self.confirm(); });
    if (this.backButton) this.backButton.addEventListener('click', function () { return self.back(); });
    if (this.forwardButton) this.forwardButton.addEventListener('click', function () { return self.forward(); });
    if (this.upButton) this.upButton.addEventListener('click', function () { return self.parentToken && self.navigate(self.parentToken); });
    if (this.root) this.root.addEventListener('keydown', function (event) { return self.handleKey(event); });
  };

  StoryFilePicker.prototype.open = function (trigger) {
    this.trigger = trigger || document.activeElement; this.selected = null;
    if (this.root) { this.root.hidden = false; this.root.classList.add('on'); this.root.setAttribute('aria-hidden', 'false'); }
    if (this.source) this.source.hidden = false; if (this.host) this.host.hidden = true;
    if (this.status) this.status.textContent = ''; if (this.selectedLabel) this.selectedLabel.textContent = '尚未选择文件';
    if (this.openButton) this.openButton.disabled = true;
    const first = byId('storyPickerDeviceAction'); if (first && first.focus) first.focus();
  };

  StoryFilePicker.prototype.close = function () {
    if (this.root) { this.root.hidden = true; this.root.classList.remove('on'); this.root.setAttribute('aria-hidden', 'true'); }
    if (this.input) this.input.value = ''; const trigger = this.trigger; this.trigger = null;
    if (trigger && trigger.focus) trigger.focus();
  };

  StoryFilePicker.prototype.chooseDevice = function () { if (this.input && this.input.click) this.input.click(); };

  StoryFilePicker.prototype.upload = async function (file) {
    if (!file) return null;
    if (this.status) this.status.textContent = '正在读取此设备上的文件…';
    try {
      const result = await exports.Api.request('/api/story-files/upload', {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream', 'X-AA-Filename': encodeURIComponent(file.name || '')},
        body: file,
      });
      if (this.options.onChoose) await this.options.onChoose({file_token: result.file_token, name: result.name, size: result.size});
      this.close(); return result;
    } catch (error) { if (this.status) this.status.textContent = error.message || '文件上传失败'; return null; }
  };

  StoryFilePicker.prototype.openHost = async function () {
    if (this.source) this.source.hidden = true; if (this.host) this.host.hidden = false;
    this.historyBack = []; this.historyForward = []; this.locationToken = '';
    return this.load('', false);
  };

  StoryFilePicker.prototype.queryPath = function (token) {
    const query = new URLSearchParams();
    if (token) query.set('entry_token', token);
    if (this.search && this.search.value) query.set('query', this.search.value);
    query.set('sort', this.sort); query.set('direction', this.direction);
    return '/api/story-files/host?' + query.toString();
  };

  StoryFilePicker.prototype.load = async function (token, pushHistory) {
    if (this.status) this.status.textContent = '正在读取文件夹…';
    try {
      const result = await exports.Api.request(this.queryPath(token));
      if (pushHistory && this.locationToken && result.location_token !== this.locationToken) this.historyBack.push(this.locationToken);
      this.locationToken = result.location_token || token || ''; this.parentToken = result.parent_token || '';
      if (pushHistory) this.historyForward = [];
      this.selected = null; this.render(result);
      if (this.status) this.status.textContent = (result.entries || []).length ? '' : '这个文件夹中没有可选择的 .txt 或 .md 剧情文本';
      return result;
    } catch (error) { if (this.status) this.status.textContent = error.message || '无法读取文件夹'; return null; }
  };

  StoryFilePicker.prototype.navigate = function (token) { return this.load(token, true); };
  StoryFilePicker.prototype.back = function () {
    if (!this.historyBack.length) return null; const token = this.historyBack.pop();
    if (this.locationToken) this.historyForward.push(this.locationToken); return this.load(token, false);
  };
  StoryFilePicker.prototype.forward = function () {
    if (!this.historyForward.length) return null; const token = this.historyForward.pop();
    if (this.locationToken) this.historyBack.push(this.locationToken); return this.load(token, false);
  };
  StoryFilePicker.prototype.sortBy = function (field) {
    if (this.sort === field) this.direction = this.direction === 'asc' ? 'desc' : 'asc';
    else { this.sort = field; this.direction = 'asc'; }
    return this.load(this.locationToken, false);
  };

  StoryFilePicker.prototype.render = function (result) {
    const self = this; clear(this.entries); clear(this.breadcrumbs); clear(this.roots);
    (result.roots || []).forEach(function (item) { const node = button(item.name, 'story-picker-root'); node.addEventListener('click', function () { self.navigate(item.entry_token); }); self.roots.appendChild(node); });
    (result.breadcrumbs || []).forEach(function (item, index) { const node = button(item.name, 'story-picker-crumb'); node.addEventListener('click', function () { self.navigate(item.entry_token); }); self.breadcrumbs.appendChild(node); if (index < result.breadcrumbs.length - 1) { const sep = document.createElement('span'); sep.textContent = '›'; self.breadcrumbs.appendChild(sep); } });
    (result.entries || []).forEach(function (item) {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'story-picker-entry'; row.dataset.kind = item.kind;
      const icon = document.createElement('span'); icon.className = 'story-picker-entry-icon'; icon.setAttribute('aria-hidden', 'true'); icon.textContent = item.kind === 'directory' ? '▰' : '▤';
      const name = document.createElement('span'); name.className = 'story-picker-entry-name'; name.textContent = item.name;
      const type = document.createElement('span'); type.className = 'story-picker-entry-type'; type.textContent = item.type || '';
      const modified = document.createElement('span'); modified.className = 'story-picker-entry-modified'; modified.textContent = formatDate(item.modified);
      const size = document.createElement('span'); size.className = 'story-picker-entry-size'; size.textContent = item.kind === 'directory' ? '' : formatSize(item.size);
      row.append(icon, name, type, modified, size);
      row.addEventListener('click', function () { self.selectEntry(item, row); });
      row.addEventListener('dblclick', function () { if (item.kind === 'directory') self.navigate(item.entry_token); else { self.selectEntry(item, row); self.confirm(); } });
      self.entries.appendChild(row);
    });
    if (this.backButton) this.backButton.disabled = !this.historyBack.length;
    if (this.forwardButton) this.forwardButton.disabled = !this.historyForward.length;
    if (this.upButton) this.upButton.disabled = !this.parentToken;
  };

  StoryFilePicker.prototype.selectEntry = function (item, row) {
    if (!item) return; if (item.kind === 'directory') { this.navigate(item.entry_token); return; }
    this.selected = item;
    if (this.entries && this.entries.children) Array.prototype.forEach.call(this.entries.children, function (node) { node.classList && node.classList.toggle('is-selected', node === row); });
    if (this.selectedLabel) this.selectedLabel.textContent = item.name + ' · ' + formatSize(item.size);
    if (this.openButton) this.openButton.disabled = false;
  };

  StoryFilePicker.prototype.confirm = async function () {
    if (!this.selected) return null; if (this.status) this.status.textContent = '正在打开剧情文本…';
    try {
      const result = await exports.Api.request('/api/story-files/select', exports.Api.json ? exports.Api.json('POST', {entry_token: this.selected.entry_token}) : {method: 'POST', body: JSON.stringify({entry_token: this.selected.entry_token})});
      if (this.options.onChoose) await this.options.onChoose({file_token: result.file_token, name: result.name, size: result.size});
      this.close(); return result;
    } catch (error) { if (this.status) this.status.textContent = error.message || '无法打开剧情文本'; return null; }
  };

  StoryFilePicker.prototype.handleKey = function (event) {
    if (!event) return null;
    if (event.key === 'Escape') { event.preventDefault && event.preventDefault(); this.close(); return null; }
    if (event.key === 'Enter' && this.selected) { event.preventDefault && event.preventDefault(); return this.confirm(); }
    return null;
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.StoryFilePicker = StoryFilePicker;
})(window);
