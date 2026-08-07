(function (exports) {
  'use strict';

  function byId(id) { return document.getElementById(id); }
  function scoped(root, role, fallbackId) {
    const found = root && root.querySelector
      ? root.querySelector('[data-picker-role="' + role + '"]')
      : null;
    return found && found.dataset && found.dataset.pickerRole === role
      ? found
      : byId(fallbackId);
  }
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
    this.host = scoped(root, 'host', 'storyPickerHost'); this.status = scoped(root, 'status', 'storyPickerStatus');
    this.entries = scoped(root, 'entries', 'storyPickerEntries'); this.breadcrumbs = scoped(root, 'breadcrumbs', 'storyPickerBreadcrumbs');
    this.roots = scoped(root, 'roots', 'storyPickerRoots'); this.search = scoped(root, 'search', 'storyPickerSearch');
    this.selectedLabel = scoped(root, 'selected', 'storyPickerSelected'); this.openButton = scoped(root, 'open', 'storyPickerOpen');
    this.backButton = scoped(root, 'back', 'storyPickerBack'); this.forwardButton = scoped(root, 'forward', 'storyPickerForward');
    this.upButton = scoped(root, 'up', 'storyPickerUp'); this.title = scoped(root, 'title', 'browseTitle');
    this.selected = null; this.locationToken = ''; this.parentToken = '';
    this.historyBack = []; this.historyForward = []; this.sort = 'name'; this.direction = 'asc';
    this.hostEndpoint = this.options.hostEndpoint || '/api/story-files/host';
    this.selectEndpoint = this.options.selectEndpoint || '/api/story-files/select';
    this.searchPlaceholder = this.options.searchPlaceholder || '搜索剧情文本';
    this.allowedSuffixes = Array.isArray(this.options.allowedSuffixes)
      ? new Set(this.options.allowedSuffixes.map(function (value) {
        const suffix = String(value || '').trim().toLocaleLowerCase();
        return suffix && suffix.charAt(0) === '.' ? suffix : '.' + suffix;
      }).filter(Boolean))
      : null;
    this.directoryOnly = Boolean(this.options.directoryOnly);
    this.hostOnly = Boolean(this.options.hostOnly);
    this.trigger = null; this._bound = false; this.bind();
  }

  StoryFilePicker.prototype.bind = function () {
    if (this._bound) return; this._bound = true; const self = this;
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
    const title = this.title;
    if (title && this.options.title) title.textContent = this.options.title;
    if (this.search) this.search.placeholder = this.searchPlaceholder;
    if (this.status) this.status.textContent = ''; if (this.selectedLabel) this.selectedLabel.textContent = '尚未选择文件';
    if (this.openButton) this.openButton.disabled = true;
    return this.openHost();
  };

  StoryFilePicker.prototype.close = function () {
    if (this.root) { this.root.hidden = true; this.root.classList.remove('on'); this.root.setAttribute('aria-hidden', 'true'); }
    const trigger = this.trigger; this.trigger = null;
    if (trigger && trigger.focus) trigger.focus();
  };

  StoryFilePicker.prototype.openHostMode = function (trigger, directoryOnly) {
    this.trigger = trigger || document.activeElement;
    this.directoryOnly = Boolean(directoryOnly);
    this.hostOnly = true;
    if (this.root) { this.root.hidden = false; this.root.classList.add('on'); this.root.setAttribute('aria-hidden', 'false'); }
    return this.openHost();
  };

  StoryFilePicker.prototype.openDirectory = function (trigger) {
    return this.openHostMode(trigger, true);
  };

  StoryFilePicker.prototype.openPath = function (trigger) {
    return this.openHostMode(trigger, false);
  };

  StoryFilePicker.prototype.openHost = async function () {
    this.selected = null;
    if (this.openButton) this.openButton.disabled = true;
    const title = this.title;
    if (title && this.options.title) title.textContent = this.options.title;
    if (this.search) this.search.placeholder = this.searchPlaceholder;
    if (this.host) this.host.hidden = false;
    this.historyBack = []; this.historyForward = []; this.locationToken = '';
    return this.load('', false);
  };

  StoryFilePicker.prototype.queryPath = function (token) {
    const query = new URLSearchParams();
    if (token) query.set('entry_token', token);
    if (this.search && this.search.value) query.set('query', this.search.value);
    query.set('sort', this.sort); query.set('direction', this.direction);
    return this.hostEndpoint + '?' + query.toString();
  };

  StoryFilePicker.prototype.load = async function (token, pushHistory) {
    if (this.status) this.status.textContent = '正在读取文件夹…';
    try {
      const result = await exports.Api.request(this.queryPath(token));
      if (pushHistory && this.locationToken && result.location_token !== this.locationToken) this.historyBack.push(this.locationToken);
      this.locationToken = result.location_token || token || ''; this.parentToken = result.parent_token || '';
      if (pushHistory) this.historyForward = [];
      this.selected = null; this.render(result);
      if (this.status) this.status.textContent = (result.entries || []).length ? '' : (this.options.emptyStatus || '这个文件夹中没有可选择的 .txt 或 .md 剧情文本');
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
    (result.entries || []).filter(function (item) {
      if (!item || item.kind === 'directory' || !self.allowedSuffixes) return Boolean(item);
      const name = String(item.name || '').toLocaleLowerCase();
      const index = name.lastIndexOf('.');
      return index >= 0 && self.allowedSuffixes.has(name.slice(index));
    }).forEach(function (item) {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'story-picker-entry'; row.dataset.kind = item.kind;
      const icon = document.createElement('span'); icon.className = 'story-picker-entry-icon'; icon.setAttribute('aria-hidden', 'true'); icon.textContent = item.kind === 'directory' ? '▰' : '▤';
      const name = document.createElement('span'); name.className = 'story-picker-entry-name'; name.textContent = item.name;
      const type = document.createElement('span'); type.className = 'story-picker-entry-type'; type.textContent = item.type || '';
      const modified = document.createElement('span'); modified.className = 'story-picker-entry-modified'; modified.textContent = formatDate(item.modified);
      const size = document.createElement('span'); size.className = 'story-picker-entry-size'; size.textContent = item.kind === 'directory' ? '' : formatSize(item.size);
      row.append(icon, name, type, modified, size);
      row.addEventListener('click', function () { self.selectEntry(item, row); });
      row.addEventListener('dblclick', function () {
        if (item.kind === 'directory' && !self.directoryOnly) self.navigate(item.entry_token);
        else { self.selectEntry(item, row); self.confirm(); }
      });
      self.entries.appendChild(row);
    });
    if (this.backButton) this.backButton.disabled = !this.historyBack.length;
    if (this.forwardButton) this.forwardButton.disabled = !this.historyForward.length;
    if (this.upButton) this.upButton.disabled = !this.parentToken;
  };

  StoryFilePicker.prototype.selectEntry = function (item, row) {
    if (!item) return;
    if (item.kind === 'directory' && !this.directoryOnly) { this.navigate(item.entry_token); return; }
    this.selected = item;
    if (this.entries && this.entries.children) Array.prototype.forEach.call(this.entries.children, function (node) { node.classList && node.classList.toggle('is-selected', node === row); });
    if (this.selectedLabel) this.selectedLabel.textContent = item.name + ' · ' + formatSize(item.size);
    if (this.openButton) this.openButton.disabled = false;
  };

  StoryFilePicker.prototype.confirm = async function () {
    if (!this.selected) return null; if (this.status) this.status.textContent = this.options.openingStatus || '正在打开剧情文本…';
    try {
      const result = await exports.Api.request(this.selectEndpoint, exports.Api.json ? exports.Api.json('POST', {entry_token: this.selected.entry_token}) : {method: 'POST', body: JSON.stringify({entry_token: this.selected.entry_token})});
      this.close();
      if (this.options.onChoose) {
        const selection = this.selectEndpoint === '/api/story-files/select'
          ? {file_token: result.file_token, name: result.name, size: result.size}
          : result;
        await this.options.onChoose(selection);
      }
      return result;
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
