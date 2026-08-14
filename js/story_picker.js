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
  function optionalScoped(root, role, fallbackId) {
    if (root && root.querySelector) {
      const found = root.querySelector('[data-picker-role="' + role + '"]');
      if (found && found.dataset && found.dataset.pickerRole === role) return found;
      const fallback = byId(fallbackId);
      return !root.contains || (fallback && root.contains(fallback)) ? fallback : null;
    }
    return byId(fallbackId);
  }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function button(label, className) {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = className || '';
    node.textContent = label;
    return node;
  }
  function formatSize(value) {
    const size = Number(value || 0);
    if (size < 1024) return size + ' B';
    if (size < 1024 * 1024) return (size / 1024).toFixed(size < 10 * 1024 ? 1 : 0) + ' KB';
    return (size / (1024 * 1024)).toFixed(1) + ' MB';
  }
  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false
    });
  }
  function suffixAllowed(item, suffixes) {
    if (!item || item.kind === 'directory' || !suffixes) return Boolean(item);
    const name = String(item.name || '').toLocaleLowerCase();
    const index = name.lastIndexOf('.');
    return index >= 0 && suffixes.has(name.slice(index));
  }

  function StoryFilePicker(root, options) {
    this.root = root;
    this.options = options || {};
    this.host = scoped(root, 'host', 'storyPickerHost');
    this.status = scoped(root, 'status', 'storyPickerStatus');
    this.entries = scoped(root, 'entries', 'storyPickerEntries');
    this.breadcrumbs = scoped(root, 'breadcrumbs', 'storyPickerBreadcrumbs');
    this.roots = scoped(root, 'roots', 'storyPickerRoots');
    this.search = scoped(root, 'search', 'storyPickerSearch');
    this.selectedLabel = scoped(root, 'selected', 'storyPickerSelected');
    this.selectedMeta = optionalScoped(root, 'selected-meta', 'storyPickerSelectedMeta');
    this.openButton = scoped(root, 'open', 'storyPickerOpen');
    this.backButton = scoped(root, 'back', 'storyPickerBack');
    this.forwardButton = scoped(root, 'forward', 'storyPickerForward');
    this.upButton = scoped(root, 'up', 'storyPickerUp');
    this.deviceButton = optionalScoped(root, 'device', 'storyPickerDeviceAction');
    this.input = optionalScoped(root, 'device-input', 'storyPickerDeviceInput');
    this.title = optionalScoped(root, 'title', 'browseTitle');
    this.hostEndpoint = this.options.hostEndpoint || '/api/story-files/host';
    this.selectEndpoint = this.options.selectEndpoint || '/api/story-files/select';
    this.allowDeviceUpload = this.options.allowDeviceUpload !== undefined
      ? Boolean(this.options.allowDeviceUpload)
      : this.selectEndpoint === '/api/story-files/select';
    this.searchPlaceholder = this.options.searchPlaceholder || '搜索当前文件夹';
    this.allowedSuffixes = Array.isArray(this.options.allowedSuffixes)
      ? new Set(this.options.allowedSuffixes.map(function (value) {
        const suffix = String(value || '').trim().toLocaleLowerCase();
        return suffix && suffix.charAt(0) === '.' ? suffix : '.' + suffix;
      }).filter(Boolean))
      : null;
    this.directoryOnly = Boolean(this.options.directoryOnly);
    this.hostOnly = Boolean(this.options.hostOnly);
    this.filesOnly = Boolean(this.options.filesOnly);
    this.selected = null;
    this.locationToken = '';
    this.parentToken = '';
    this.historyBack = [];
    this.historyForward = [];
    this.sort = 'name';
    this.direction = 'asc';
    this.visibleEntries = [];
    this.entryRows = [];
    this.activeIndex = -1;
    this.trigger = null;
    this._bound = false;
    this._loadSerial = 0;
    this._searchTimer = null;
    this.bind();
  }

  StoryFilePicker.prototype.isActive = function () {
    return Boolean(this.root && !this.root.hidden &&
      (!this.root._storyPickerOwner || this.root._storyPickerOwner === this));
  };

  StoryFilePicker.prototype.bind = function () {
    if (this._bound) return;
    this._bound = true;
    const self = this;
    if (this.input && this.allowDeviceUpload) {
      this.input.addEventListener('change', function (event) {
        return self.upload(event.target.files && event.target.files[0]);
      });
    }
    if (this.search) {
      this.search.addEventListener('input', function () {
        const run = function () { return self.load(self.locationToken, false); };
        if (typeof clearTimeout === 'function') clearTimeout(self._searchTimer);
        if (typeof setTimeout === 'function') self._searchTimer = setTimeout(run, 180);
        else return run();
      });
    }
    if (this.openButton) this.openButton.addEventListener('click', function () { return self.confirm(); });
    if (this.backButton) this.backButton.addEventListener('click', function () { return self.back(); });
    if (this.forwardButton) this.forwardButton.addEventListener('click', function () { return self.forward(); });
    if (this.upButton) this.upButton.addEventListener('click', function () { return self.parent(); });
    if (this.root) this.root.addEventListener('keydown', function (event) { return self.handleKey(event); });
  };

  StoryFilePicker.prototype.prepare = function (trigger) {
    this.trigger = trigger || document.activeElement;
    this.selected = null;
    this.activeIndex = -1;
    if (this.root) {
      this.root._storyPickerOwner = this;
      this.root.hidden = false;
      this.root.classList.add('on');
      this.root.setAttribute('aria-hidden', 'false');
    }
    if (this.title && this.options.title) this.title.textContent = this.options.title;
    if (this.search) {
      this.search.placeholder = this.searchPlaceholder;
      this.search.value = '';
    }
    if (this.deviceButton) this.deviceButton.hidden = !this.allowDeviceUpload;
    if (this.host) this.host.hidden = false;
    this.updateSelection();
  };

  StoryFilePicker.prototype.open = function (trigger) {
    this.directoryOnly = Boolean(this.options.directoryOnly);
    this.hostOnly = false;
    this.prepare(trigger);
    return this.openHost(true);
  };

  StoryFilePicker.prototype.close = function () {
    if (this.root && this.root._storyPickerOwner && this.root._storyPickerOwner !== this) return;
    if (this.root) {
      this.root.hidden = true;
      this.root.classList.remove('on');
      this.root.setAttribute('aria-hidden', 'true');
      this.root._storyPickerOwner = null;
    }
    if (this.input) this.input.value = '';
    const trigger = this.trigger;
    this.trigger = null;
    if (trigger && trigger.focus) trigger.focus();
  };

  StoryFilePicker.prototype.openHostMode = function (trigger, directoryOnly) {
    this.directoryOnly = Boolean(directoryOnly);
    this.hostOnly = true;
    this.prepare(trigger);
    return this.openHost(true);
  };

  StoryFilePicker.prototype.openDirectory = function (trigger) {
    return this.openHostMode(trigger, true);
  };

  StoryFilePicker.prototype.openPath = function (trigger) {
    return this.openHostMode(trigger, false);
  };

  StoryFilePicker.prototype.chooseDevice = function () {
    if (this.allowDeviceUpload && this.input && this.input.click) this.input.click();
  };

  StoryFilePicker.prototype.upload = async function (file) {
    if (!file || !this.allowDeviceUpload) return null;
    if (this.status) this.status.textContent = '正在读取 ' + (file.name || '所选文件') + '…';
    if (this.deviceButton) this.deviceButton.disabled = true;
    try {
      const result = await exports.Api.request('/api/story-files/upload', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-AA-Filename': encodeURIComponent(file.name || '')
        },
        body: file
      });
      this.close();
      if (this.options.onChoose) {
        await this.options.onChoose({
          file_token: result.file_token,
          name: result.name,
          size: result.size
        });
      }
      return result;
    } catch (error) {
      if (this.status) this.status.textContent = error.message || '文件读取失败';
      return null;
    } finally {
      if (this.deviceButton) this.deviceButton.disabled = false;
      if (this.input) this.input.value = '';
    }
  };

  StoryFilePicker.prototype.openHost = function (resetSession) {
    if (this.root && this.root._storyPickerOwner !== this) {
      this.root._storyPickerOwner = this;
      this.root.hidden = false;
      this.root.classList.add('on');
      this.root.setAttribute('aria-hidden', 'false');
    }
    this.selected = null;
    this.activeIndex = -1;
    if (this.openButton) this.openButton.disabled = true;
    if (this.host) this.host.hidden = false;
    if (resetSession !== false) {
      this.historyBack = [];
      this.historyForward = [];
      this.locationToken = '';
    }
    return this.load(this.locationToken, false);
  };

  StoryFilePicker.prototype.queryPath = function (token) {
    const query = new URLSearchParams();
    if (token) query.set('entry_token', token);
    if (this.search && this.search.value.trim()) query.set('query', this.search.value.trim());
    query.set('sort', this.sort);
    query.set('direction', this.direction);
    return this.hostEndpoint + '?' + query.toString();
  };

  StoryFilePicker.prototype.setLoading = function (loading) {
    if (this.host) this.host.setAttribute('aria-busy', loading ? 'true' : 'false');
    if (this.entries) this.entries.classList.toggle('is-loading', loading);
    if (loading && this.status) this.status.textContent = '正在读取文件夹…';
  };

  StoryFilePicker.prototype.load = async function (token, pushHistory) {
    const serial = ++this._loadSerial;
    this.setLoading(true);
    try {
      const result = await exports.Api.request(this.queryPath(token));
      if (serial !== this._loadSerial) return null;
      if (pushHistory && this.locationToken && result.location_token !== this.locationToken) {
        this.historyBack.push(this.locationToken);
      }
      this.locationToken = result.location_token || token || '';
      this.parentToken = result.parent_token || '';
      if (pushHistory) this.historyForward = [];
      this.selected = null;
      this.activeIndex = -1;
      this.render(result);
      return result;
    } catch (error) {
      if (serial === this._loadSerial && this.status) {
        this.status.textContent = (error.message || '无法读取文件夹') + '，请刷新后重试';
      }
      return null;
    } finally {
      if (serial === this._loadSerial) this.setLoading(false);
    }
  };

  StoryFilePicker.prototype.navigate = function (token) {
    if (!token) return null;
    if (this.search) this.search.value = '';
    return this.load(token, true);
  };

  StoryFilePicker.prototype.parent = function () {
    return this.parentToken ? this.navigate(this.parentToken) : null;
  };

  StoryFilePicker.prototype.back = function () {
    if (!this.historyBack.length) return null;
    const token = this.historyBack.pop();
    if (this.locationToken) this.historyForward.push(this.locationToken);
    if (this.search) this.search.value = '';
    return this.load(token, false);
  };

  StoryFilePicker.prototype.forward = function () {
    if (!this.historyForward.length) return null;
    const token = this.historyForward.pop();
    if (this.locationToken) this.historyBack.push(this.locationToken);
    if (this.search) this.search.value = '';
    return this.load(token, false);
  };

  StoryFilePicker.prototype.sortBy = function (field) {
    if (this.sort === field) this.direction = this.direction === 'asc' ? 'desc' : 'asc';
    else {
      this.sort = field;
      this.direction = 'asc';
    }
    return this.load(this.locationToken, false);
  };

  StoryFilePicker.prototype.updateSortControls = function () {
    if (!this.root || !this.root.querySelectorAll) return;
    const self = this;
    Array.prototype.forEach.call(this.root.querySelectorAll('[data-story-sort]'), function (node) {
      const active = node.dataset.storySort === self.sort;
      node.classList.toggle('is-active', active);
      node.dataset.direction = active ? self.direction : '';
      node.setAttribute('aria-sort', active ? (self.direction === 'asc' ? 'ascending' : 'descending') : 'none');
    });
  };

  StoryFilePicker.prototype.renderRoot = function (item, currentRootName) {
    const self = this;
    const node = button('', 'story-picker-root');
    const icon = document.createElement('span');
    icon.className = 'story-picker-root-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = /^[a-z]:\\?$/i.test(String(item.name || '')) ? '▣' : '◆';
    const label = document.createElement('span');
    label.textContent = item.name;
    node.append(icon, label);
    node.classList.toggle('is-current', item.name === currentRootName);
    if (item.name === currentRootName) node.setAttribute('aria-current', 'location');
    node.addEventListener('click', function () { self.navigate(item.entry_token); });
    return node;
  };

  StoryFilePicker.prototype.renderEmpty = function () {
    const self = this;
    const empty = document.createElement('div');
    empty.className = 'story-picker-empty';
    const icon = document.createElement('span');
    icon.className = 'story-picker-empty-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '□';
    const title = document.createElement('b');
    const hasQuery = Boolean(this.search && this.search.value.trim());
    title.textContent = hasQuery ? '没有匹配的文件' : '这里没有可打开的文件';
    empty.append(icon, title);
    if (hasQuery) {
      const reset = button('清除搜索', 'ghost');
      reset.addEventListener('click', function () {
        self.search.value = '';
        self.load(self.locationToken, false);
      });
      empty.appendChild(reset);
    }
    this.entries.appendChild(empty);
  };

  StoryFilePicker.prototype.render = function (result) {
    const self = this;
    clear(this.entries);
    clear(this.breadcrumbs);
    clear(this.roots);
    const breadcrumbs = result.breadcrumbs || [];
    const currentRootName = breadcrumbs.length ? breadcrumbs[0].name : '';
    (result.roots || []).forEach(function (item) {
      self.roots.appendChild(self.renderRoot(item, currentRootName));
    });
    breadcrumbs.forEach(function (item, index) {
      const node = button(item.name, 'story-picker-crumb');
      if (index === breadcrumbs.length - 1) node.setAttribute('aria-current', 'location');
      node.addEventListener('click', function () { self.navigate(item.entry_token); });
      self.breadcrumbs.appendChild(node);
      if (index < breadcrumbs.length - 1) {
        const sep = document.createElement('span');
        sep.textContent = '›';
        sep.setAttribute('aria-hidden', 'true');
        self.breadcrumbs.appendChild(sep);
      }
    });
    this.visibleEntries = (result.entries || []).filter(function (item) {
      return suffixAllowed(item, self.allowedSuffixes);
    });
    this.entryRows = [];
    this.visibleEntries.forEach(function (item, index) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'story-picker-entry';
      row.dataset.kind = item.kind;
      row.dataset.index = String(index);
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', 'false');
      row.tabIndex = -1;
      const icon = document.createElement('span');
      icon.className = 'story-picker-entry-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = item.kind === 'directory' ? '▰' : '▤';
      const name = document.createElement('span');
      name.className = 'story-picker-entry-name';
      name.textContent = item.name;
      const type = document.createElement('span');
      type.className = 'story-picker-entry-type';
      type.textContent = item.type || '';
      const modified = document.createElement('span');
      modified.className = 'story-picker-entry-modified';
      modified.textContent = formatDate(item.modified);
      const size = document.createElement('span');
      size.className = 'story-picker-entry-size';
      size.textContent = item.kind === 'directory' ? '' : formatSize(item.size);
      row.append(icon, name, type, modified, size);
      row.addEventListener('click', function () { self.selectEntry(item, row, index); });
      row.addEventListener('dblclick', function () {
        if (item.kind === 'directory') return self.navigate(item.entry_token);
        self.selectEntry(item, row, index);
        return self.confirm();
      });
      self.entryRows.push(row);
      self.entries.appendChild(row);
    });
    if (!this.visibleEntries.length) this.renderEmpty();
    const folders = this.visibleEntries.filter(function (item) { return item.kind === 'directory'; }).length;
    const files = this.visibleEntries.length - folders;
    if (this.status) {
      if (!this.visibleEntries.length) {
        this.status.textContent = this.search && this.search.value.trim()
          ? '当前文件夹没有匹配项'
          : (this.options.emptyStatus || '当前文件夹没有可选择的文件');
      } else {
        this.status.textContent = folders + ' 个文件夹 · ' + files + ' 个可用文件';
      }
    }
    if (this.entries) {
      this.entries.tabIndex = 0;
      this.entries.setAttribute('aria-activedescendant', '');
    }
    if (this.backButton) this.backButton.disabled = !this.historyBack.length;
    if (this.forwardButton) this.forwardButton.disabled = !this.historyForward.length;
    if (this.upButton) this.upButton.disabled = !this.parentToken;
    this.updateSortControls();
    this.updateSelection();
  };

  StoryFilePicker.prototype.updateSelection = function () {
    const item = this.selected;
    if (this.selectedLabel) this.selectedLabel.textContent = item ? item.name : '尚未选择文件';
    if (this.selectedMeta) {
      this.selectedMeta.textContent = item
        ? (item.kind === 'directory' ? '文件夹' : ((item.type || '文件') + ' · ' + formatSize(item.size)))
        : '选择文件后可打开';
    }
    if (!this.openButton) return;
    if (!item) {
      this.openButton.disabled = true;
      this.openButton.textContent = this.directoryOnly ? '选择文件夹' : '打开';
      return;
    }
    if (this.directoryOnly && item.kind !== 'directory') {
      this.openButton.disabled = true;
      this.openButton.textContent = '选择文件夹';
      return;
    }
    this.openButton.disabled = false;
    if (item.kind === 'directory') {
      this.openButton.textContent = (this.selectEndpoint === '/api/story-files/select' || this.filesOnly)
        ? '进入文件夹'
        : '选择此文件夹';
    } else {
      this.openButton.textContent = this.options.openLabel || (
        this.selectEndpoint === '/api/story-files/select' ? '打开剧情' : '选择'
      );
    }
  };

  StoryFilePicker.prototype.selectEntry = function (item, row, index) {
    if (!item) return;
    this.selected = item;
    this.activeIndex = Number.isInteger(index)
      ? index
      : this.visibleEntries.findIndex(function (candidate) {
        return candidate.entry_token === item.entry_token;
      });
    const selectedRow = row || this.entryRows[this.activeIndex];
    this.entryRows.forEach(function (node) {
      const selected = node === selectedRow;
      node.classList.toggle('is-selected', selected);
      node.setAttribute('aria-selected', selected ? 'true' : 'false');
      node.tabIndex = selected ? 0 : -1;
    });
    this.updateSelection();
  };

  StoryFilePicker.prototype.moveSelection = function (nextIndex) {
    if (!this.visibleEntries.length) return null;
    const index = Math.max(0, Math.min(this.visibleEntries.length - 1, nextIndex));
    const row = this.entryRows[index];
    this.selectEntry(this.visibleEntries[index], row, index);
    if (row && row.focus) row.focus();
    if (row && row.scrollIntoView) row.scrollIntoView({block: 'nearest'});
    return this.visibleEntries[index];
  };

  StoryFilePicker.prototype.confirm = async function () {
    if (!this.selected) return null;
    if (this.selected.kind === 'directory' && (this.selectEndpoint === '/api/story-files/select' || this.filesOnly)) {
      return this.navigate(this.selected.entry_token);
    }
    if (this.directoryOnly && this.selected.kind !== 'directory') return null;
    if (this.status) this.status.textContent = this.options.openingStatus || '正在打开所选内容…';
    if (this.openButton) this.openButton.disabled = true;
    try {
      const result = await exports.Api.request(
        this.selectEndpoint,
        exports.Api.json
          ? exports.Api.json('POST', {entry_token: this.selected.entry_token})
          : {method: 'POST', body: JSON.stringify({entry_token: this.selected.entry_token})}
      );
      this.close();
      if (this.options.onChoose) {
        const selection = this.selectEndpoint === '/api/story-files/select'
          ? {file_token: result.file_token, name: result.name, size: result.size}
          : result;
        await this.options.onChoose(selection);
      }
      return result;
    } catch (error) {
      if (this.status) this.status.textContent = error.message || '无法打开所选内容';
      if (this.openButton) this.openButton.disabled = false;
      return null;
    }
  };

  StoryFilePicker.prototype.handleKey = function (event) {
    if (!event || !this.isActive()) return null;
    if (event.key === 'Escape') {
      if (event.preventDefault) event.preventDefault();
      this.close();
      return null;
    }
    if (event.altKey && event.key === 'ArrowLeft') {
      if (event.preventDefault) event.preventDefault();
      return this.back();
    }
    if (event.altKey && event.key === 'ArrowRight') {
      if (event.preventDefault) event.preventDefault();
      return this.forward();
    }
    if (event.key === 'Backspace' && event.target !== this.search) {
      if (event.preventDefault) event.preventDefault();
      return this.parent();
    }
    if (event.target === this.search) return null;
    if (event.key === 'ArrowDown') {
      if (event.preventDefault) event.preventDefault();
      return this.moveSelection(this.activeIndex < 0 ? 0 : this.activeIndex + 1);
    }
    if (event.key === 'ArrowUp') {
      if (event.preventDefault) event.preventDefault();
      return this.moveSelection(this.activeIndex < 0 ? this.visibleEntries.length - 1 : this.activeIndex - 1);
    }
    if (event.key === 'Home') {
      if (event.preventDefault) event.preventDefault();
      return this.moveSelection(0);
    }
    if (event.key === 'End') {
      if (event.preventDefault) event.preventDefault();
      return this.moveSelection(this.visibleEntries.length - 1);
    }
    if (event.key === 'Enter' && this.selected) {
      if (event.preventDefault) event.preventDefault();
      if (this.selected.kind === 'directory') return this.navigate(this.selected.entry_token);
      return this.confirm();
    }
    return null;
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.StoryFilePicker = StoryFilePicker;
})(window);
