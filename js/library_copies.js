/* 单章节副本描述、引用阻止、确认和移除控制器。 */
(function (exports) {
  'use strict';

  function clear(node) { if (node) node.textContent = ''; }
  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }

  function CopyManager(workbench) {
    this.workbench = workbench;
    this.item = null;
    this.copies = [];
    this.pending = null;
  }

  CopyManager.prototype.open = async function (item) {
    this.item = item || null;
    this.pending = null;
    if (!item || !item.preview_token) {
      this.workbench.setCopyState('副本记录不可用，请刷新素材工作台。');
      return null;
    }
    this.workbench.setCopyState('正在读取副本记录…');
    try {
      const payload = await exports.Api.request(
        '/api/assets/library/copies?preview_token=' + encodeURIComponent(item.preview_token)
      );
      this.copies = Array.isArray(payload.copies) ? payload.copies : [];
      this.render();
      this.workbench.setCopyState('已读取 ' + this.copies.length + ' 个章节副本。');
      return payload;
    } catch (error) {
      this.copies = [];
      this.workbench.setCopyState(String(error.action || '副本读取失败，请刷新后重试。'));
      this.render();
      throw error;
    }
  };

  CopyManager.prototype.render = function () {
    const root = this.workbench.detail;
    if (!root) return;
    clear(root);
    const section = make('section', 'asset-copy-panel');
    section.appendChild(make('h3', '', '副本记录'));
    if (!this.copies.length) section.appendChild(make('p', 'asset-workbench-empty', '没有可管理的章节副本。'));
    this.copies.forEach(function (copy) {
      const row = make('div', 'asset-copy-row');
      row.appendChild(make('b', '', copy.chapter || '未命名章节'));
      const references = Array.isArray(copy.references) ? copy.references : [];
      if (references.length) {
        row.appendChild(make('span', 'asset-copy-blocked', '仍被草稿引用 ' + references.length + ' 处'));
        const jump = make('button', 'ghost', '跳转引用');
        jump.type = 'button';
        jump.addEventListener('click', function () {
          if (this.workbench.focusReference) this.workbench.focusReference(references[0]);
        }.bind(this));
        row.appendChild(jump);
      } else {
        const remove = make('button', 'ghost', '移除该章节副本');
        remove.type = 'button';
        remove.addEventListener('click', function () { this.requestRemoval(copy); }.bind(this));
        row.appendChild(remove);
      }
      section.appendChild(row);
    }, this);
    root.appendChild(section);
  };

  CopyManager.prototype.remove = async function (copy) {
    const references = copy && Array.isArray(copy.references) ? copy.references : [];
    if (references.length) {
      this.workbench.setCopyState('该副本仍被草稿引用，请先更换引用素材。');
      if (this.workbench.focusReference) this.workbench.focusReference(references[0]);
      return false;
    }
    this.requestRemoval(copy);
    return true;
  };

  CopyManager.prototype.requestRemoval = function (copy) {
    this.pending = copy;
    const root = this.workbench.detail;
    if (!root || !copy) return;
    clear(root);
    const confirm = make('section', 'asset-copy-confirm');
    confirm.appendChild(make(
      'h3', '', '从“' + copy.chapter + '”移除“' + (this.item.name || this.item.aa_key) + '”？'
    ));
    confirm.appendChild(make('p', '', '这只移除该章节的独立副本，不影响其他章节。'));
    const action = make('button', 'danger', '移除该章节副本');
    action.type = 'button';
    action.addEventListener('click', function () { this.confirmRemoval(); }.bind(this));
    confirm.appendChild(action);
    root.appendChild(confirm);
  };

  CopyManager.prototype.confirmRemoval = async function () {
    const copy = this.pending;
    if (!copy) return null;
    this.workbench.setCopyState('正在安全移除该章节副本…');
    try {
      const result = await exports.Api.request(
        '/api/assets/library/remove-copy',
        exports.Api.json('POST', {
          copy_token: copy.copy_token,
          confirm_chapter: copy.chapter
        })
      );
      if (exports.dispatchEvent && typeof CustomEvent === 'function') {
        exports.dispatchEvent(new CustomEvent('assetworkbench:removed', {detail: {
          kind: result.kind, aa_key: result.aa_key, chapter: result.chapter
        }}));
      }
      this.workbench.setCopyState('已移除“' + copy.chapter + '”的独立副本。');
      this.pending = null;
      if (this.workbench.refresh) await this.workbench.refresh();
      return result;
    } catch (error) {
      this.workbench.setCopyState(String(error.action || '移除未完成，请刷新副本记录后重试。'));
      throw error;
    }
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.CopyManager = CopyManager;
})(window);
