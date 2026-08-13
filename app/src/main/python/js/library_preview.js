/* 素材工作台的类型化预览，只接受服务端签发的不透明预览令牌。 */
(function (exports) {
  'use strict';

  function clear(node) { if (node) node.textContent = ''; }
  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = value;
    return node;
  }
  function previewUrl(item) {
    return '/api/assets/library/preview?preview_token=' + encodeURIComponent(item.preview_token || '');
  }
  function labelSummary(labels) {
    if (!labels || typeof labels !== 'object') return '';
    return Object.keys(labels).map(function (key) {
      const value = Array.isArray(labels[key]) ? labels[key].join('、') : labels[key];
      return String(value || '');
    }).filter(Boolean).join(' · ');
  }

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
    const details = item.details || {};
    const heading = make('header', 'asset-detail-heading');
    heading.appendChild(make('span', 'asset-detail-kind', {
      background: '背景', character: '骨骼角色', sound: '音效'
    }[item.kind] || '素材'));
    heading.appendChild(make('h3', '', item.name || String(item.aa_key || '未命名素材')));
    heading.appendChild(make(
      'p', 'asset-detail-state', item.registered_in_current ? '本章已登记' : '尚未复制到当前剧情'
    ));
    this.root.appendChild(heading);
    if (!item.preview_available || !item.preview_token) {
      this.root.appendChild(make('p', 'asset-preview-unavailable', '预览不可用，副本记录仍可管理。'));
    } else if (item.kind === 'background') {
      const image = document.createElement('img');
      image.className = 'asset-preview-image';
      image.src = previewUrl(item);
      image.alt = item.name || '背景预览';
      this.root.appendChild(image);
    } else if (item.kind === 'character') {
      const avatar = document.createElement('img');
      avatar.className = 'asset-preview-avatar';
      avatar.src = previewUrl(item);
      avatar.alt = item.name || '角色头像';
      this.root.appendChild(avatar);
    } else if (item.kind === 'sound') {
      const audio = document.createElement('audio');
      audio.className = 'asset-preview-audio';
      audio.controls = true;
      audio.preload = 'metadata';
      audio.src = previewUrl(item);
      this.audio = audio;
      this.root.appendChild(audio);
    }
    const facts = make('div', 'asset-detail-facts');
    if (item.kind === 'background') {
      facts.appendChild(make('span', '', details.resolution || '分辨率待检测'));
      const labels = labelSummary(details.labels);
      if (labels) facts.appendChild(make('span', '', labels));
    } else if (item.kind === 'character') {
      facts.appendChild(make('span', '', details.file_count === null || details.file_count === undefined ? '骨骼文件统计中' : Number(details.file_count) + ' 个骨骼文件'));
      facts.appendChild(make('span', '', details.face_count === null || details.face_count === undefined ? '表情统计中' : Number(details.face_count) + ' 个表情'));
      if (Number(details.labeled_count || 0)) facts.appendChild(make('span', '', Number(details.labeled_count) + ' 个标注已保存'));
    } else if (item.kind === 'sound') {
      const duration = Number(details.duration || 0);
      facts.appendChild(make('span', '', duration > 0 ? duration.toFixed(2) + ' 秒' : '时长待检测'));
      if (details.codec) facts.appendChild(make('span', '', String(details.codec)));
    }
    this.root.appendChild(facts);
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.AssetPreview = AssetPreview;
})(window);
