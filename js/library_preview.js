/* 素材工作台的类型化预览生命周期；具体渲染由详情模块调用。 */
(function (exports) {
  'use strict';

  function clear(node) { if (node) node.textContent = ''; }

  function AssetPreview(root) {
    this.root = root;
    this.audio = null;
  }

  AssetPreview.prototype.stop = function () {
    if (!this.audio) return;
    this.audio.pause();
    this.audio.removeAttribute('src');
    this.audio.load();
    this.audio = null;
  };

  AssetPreview.prototype.render = function (item) {
    this.stop();
    clear(this.root);
    if (!this.root || !item) return;
    const title = document.createElement('h3');
    title.textContent = item.name || String(item.aa_key || '未命名素材');
    this.root.appendChild(title);
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.AssetPreview = AssetPreview;
})(window);
