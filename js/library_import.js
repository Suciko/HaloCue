(function (exports) {
  'use strict';

  const SUFFIXES = {
    character: ['.skel'],
    background: ['.png', '.jpg', '.jpeg'],
    sound: ['.wav', '.ogg', '.mp3']
  };

  function byId(id) { return document.getElementById(id); }
  function story() {
    return exports.StoryStore && exports.StoryStore.get
      ? exports.StoryStore.get()
      : null;
  }

  function LibraryImportDialog(root) {
    this.root = root;
    this.localPanel = byId('assetImportLocal');
    this.historyPanel = byId('assetImportHistory');
    this.characterFields = byId('assetImportCharacterFields');
    this.identifier = byId('assetImportIdentifier');
    this.displayName = byId('assetImportDisplayName');
    this.selectedFile = byId('assetImportSelectedFile');
    this.status = byId('assetImportStatus');
    this.submitButton = byId('assetImportSubmit');
    this.historyRoot = byId('assetImportHistoryRoot');
    this.historySearch = byId('assetImportHistorySearch');
    this.filePickerRoot = byId('assetImportFilePicker');
    this.mode = 'local';
    this.kind = 'character';
    this.selection = null;
    this.trigger = null;
    this.busy = false;
    this.picker = null;
    this.history = null;
    if (this.filePickerRoot && exports.StoryUI && exports.StoryUI.StoryFilePicker) {
      this.picker = new exports.StoryUI.StoryFilePicker(this.filePickerRoot, {
        hostEndpoint: '/api/assets/host', selectEndpoint: '/api/assets/select',
        hostOnly: true, allowedSuffixes: SUFFIXES.character,
        title: '选择素材文件', searchPlaceholder: '搜索素材文件',
        emptyStatus: '这个文件夹中没有可选择的素材文件',
        openingStatus: '正在读取所选素材…',
        onChoose: this.selectFile.bind(this)
      });
    }
    if (this.historyRoot && exports.StoryUI && exports.StoryUI.HistoryDrawer) {
      this.history = new exports.StoryUI.HistoryDrawer(this.historyRoot, {embedded: true});
    }
    this.bind();
  }

  LibraryImportDialog.prototype.bind = function () {
    if (!this.root || !this.root.addEventListener) return;
    const self = this;
    this.root.addEventListener('click', function (event) {
      const target = event.target && event.target.closest
        ? event.target.closest('[data-asset-import-action],[data-asset-import-mode],[data-asset-import-kind]')
        : null;
      if (!target || target.disabled) return;
      if (target.dataset.assetImportMode) self.setMode(target.dataset.assetImportMode);
      else if (target.dataset.assetImportKind) self.setKind(target.dataset.assetImportKind);
      else if (target.dataset.assetImportAction === 'close') self.close();
      else if (target.dataset.assetImportAction === 'choose-file') self.openPicker(target);
      else if (target.dataset.assetImportAction === 'submit') self.submitLocal();
      else if (target.dataset.assetImportAction === 'scan') self.scanInbox();
    });
    if (this.historySearch && this.historySearch.addEventListener) {
      this.historySearch.addEventListener('input', function () {
        if (self.history) self.history.setSearchQuery(self.historySearch.value);
      });
    }
    if (document.addEventListener) document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.isOpen()) {
        event.preventDefault && event.preventDefault();
        event.stopPropagation && event.stopPropagation();
        self.close();
      }
    });
  };

  LibraryImportDialog.prototype.isOpen = function () {
    return Boolean(this.root && !this.root.hidden);
  };

  LibraryImportDialog.prototype.open = function (trigger) {
    const active = story();
    if (!this.root || !active || !active.story_token) return false;
    this.trigger = trigger || document.activeElement || null;
    this.root.hidden = false;
    this.root.classList && this.root.classList.add('is-open');
    this.root.setAttribute && this.root.setAttribute('aria-hidden', 'false');
    this.selection = null;
    if (this.selectedFile) this.selectedFile.textContent = '尚未选择文件';
    if (this.status) this.status.textContent = '';
    this.setMode('local');
    this.setKind(this.kind || 'character');
    if (this.root.focus) this.root.focus();
    return true;
  };

  LibraryImportDialog.prototype.close = function () {
    if (!this.root) return;
    if (this.history && this.history.isOpen && this.history.isOpen()) {
      this.history.close({restore: false});
    }
    if (this.picker && this.filePickerRoot && !this.filePickerRoot.hidden) this.picker.close();
    this.root.hidden = true;
    this.root.classList && this.root.classList.remove('is-open');
    this.root.setAttribute && this.root.setAttribute('aria-hidden', 'true');
    const trigger = this.trigger;
    this.trigger = null;
    if (trigger && trigger.focus) trigger.focus();
  };

  LibraryImportDialog.prototype.setMode = function (mode) {
    this.mode = mode === 'history' ? 'history' : 'local';
    if (this.localPanel) this.localPanel.hidden = this.mode !== 'local';
    if (this.historyPanel) this.historyPanel.hidden = this.mode !== 'history';
    if (this.root && this.root.querySelectorAll) {
      Array.prototype.forEach.call(this.root.querySelectorAll('[data-asset-import-mode]'), function (button) {
        const active = button.dataset.assetImportMode === this.mode;
        button.setAttribute('aria-pressed', String(active));
        button.classList.toggle('ghost', !active);
      }, this);
    }
    if (this.mode === 'history') this.openHistory();
  };

  LibraryImportDialog.prototype.setKind = function (kind) {
    this.kind = Object.prototype.hasOwnProperty.call(SUFFIXES, kind) ? kind : 'character';
    this.selection = null;
    if (this.selectedFile) this.selectedFile.textContent = '尚未选择文件';
    if (this.characterFields) this.characterFields.hidden = this.kind !== 'character';
    if (this.root && this.root.querySelectorAll) {
      Array.prototype.forEach.call(this.root.querySelectorAll('[data-asset-import-kind]'), function (button) {
        const active = button.dataset.assetImportKind === this.kind;
        button.setAttribute('aria-pressed', String(active));
        button.classList.toggle('ghost', !active);
      }, this);
    }
    if (this.mode === 'history') this.openHistory();
  };

  LibraryImportDialog.prototype.selectFile = function (selection) {
    this.selection = selection && selection.file_token ? {
      file_token: selection.file_token,
      name: String(selection.name || '所选素材'),
      size: Number(selection.size || 0)
    } : null;
    if (this.selectedFile) {
      this.selectedFile.textContent = this.selection ? this.selection.name : '尚未选择文件';
    }
  };

  LibraryImportDialog.prototype.openPicker = function (trigger) {
    if (!this.picker) return null;
    this.picker.allowedSuffixes = new Set(SUFFIXES[this.kind]);
    this.picker.options.title = this.kind === 'character'
      ? '选择角色 .skel 文件'
      : this.kind === 'sound' ? '选择音效文件' : '选择背景图片';
    return this.picker.open(trigger);
  };

  LibraryImportDialog.prototype.submitLocal = async function () {
    if (this.busy || !this.selection || !exports.StoryAssets) {
      if (this.status) this.status.textContent = '请先选择要导入的素材文件。';
      return null;
    }
    const displayName = String(this.displayName && this.displayName.value || '').trim();
    const identifier = String(this.identifier && this.identifier.value || '').trim();
    if (this.kind === 'character' && (!identifier || !displayName)) {
      if (this.status) this.status.textContent = '导入角色需要填写角色标识和显示名称。';
      return null;
    }
    const context = {
      fileToken: this.selection.file_token,
      name: this.selection.name,
      displayName: displayName
    };
    if (this.kind === 'character') context.identifier = identifier;
    this.busy = true;
    if (this.submitButton) this.submitButton.disabled = true;
    if (this.status) this.status.textContent = '正在校验并登记素材…';
    try {
      const result = await exports.StoryAssets.importLocal(this.kind, context);
      if (this.status) this.status.textContent = result && result.ok
        ? '素材已登记到当前剧情。'
        : '素材未能完成登记，请查看当前任务。';
      return result;
    } finally {
      this.busy = false;
      if (this.submitButton) this.submitButton.disabled = false;
    }
  };

  LibraryImportDialog.prototype.scanInbox = async function () {
    if (this.busy || !exports.StoryAssets || !exports.StoryAssets.scanInbox) return null;
    this.busy = true;
    if (this.status) this.status.textContent = '正在扫描当前剧情素材目录…';
    try {
      const result = await exports.StoryAssets.scanInbox();
      const rows = result && result.results || {};
      if (this.status) this.status.textContent = result
        ? '扫描完成：登记 ' + (rows.registered || []).length + ' · 跳过 ' +
          (rows.skipped || []).length + ' · 失败 ' + (rows.errors || []).length
        : '扫描未完成，请查看当前任务。';
      return result;
    } finally { this.busy = false; }
  };

  LibraryImportDialog.prototype.openHistory = function () {
    if (!this.history) return null;
    return this.history.open({
      kind: this.kind,
      trigger: this.historySearch || this.root,
      onCopied: function () { this.close(); }.bind(this),
      onReplaceLocal: function (kind) { this.setMode('local'); this.setKind(kind); }.bind(this)
    });
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.LibraryImportDialog = LibraryImportDialog;
  if (document.getElementById) {
    const root = byId('assetImportDialog');
    if (root && exports.StoryUI.StoryFilePicker && exports.StoryUI.HistoryDrawer) {
      exports.AssetImportDialog = new LibraryImportDialog(root);
    }
  }
})(window);
