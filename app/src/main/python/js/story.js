(function (exports) {
  'use strict';

  const listeners = new Set();
  let current = null;
  const store = {
    get: function () { return current; },
    set: function (value) { current = value || null; listeners.forEach(function (fn) { fn(current); }); },
    subscribe: function (fn) { listeners.add(fn); return function () { listeners.delete(fn); }; }
  };
  exports.StoryStore = store;

  function text(element, value) { if (element) element.textContent = value || ''; }
  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value) node.textContent = value;
    return node;
  }
  function formatRecentTime(value) {
    if (!value) return '未知';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '未知';
    try {
      return new Intl.DateTimeFormat('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(date);
    } catch (_) { return value; }
  }

  function storySourceName(story) {
    if (!story) return '';
    if (story.source_name) return story.source_name;
    const display = String(story.source_display || '').replace(/\\/g, '/');
    const filename = display.split('/').filter(Boolean).pop();
    return filename || story.project || '';
  }
  function formatSourceSize(value) {
    const size = Number(value);
    if (!Number.isFinite(size)) return '';
    if (size < 1024) return size + ' B';
    if (size < 1024 * 1024) return (size / 1024).toFixed(size < 10 * 1024 ? 1 : 0) + ' KB';
    return (size / (1024 * 1024)).toFixed(1) + ' MB';
  }
  function formatSourceTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    try { return date.toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}); }
    catch (_) { return value; }
  }

  function StoryContextBar(root) {
    this.root = root;
    this.name = document.getElementById('storyContextName');
    this.meta = document.getElementById('storyContextMeta');
    this.action = document.getElementById('storyContextAction');
    this.status = document.getElementById('storyContextStatus');
    store.subscribe(this.render.bind(this));
    this.render(store.get());
  }
  StoryContextBar.prototype.render = function (story) {
    this.root.classList.toggle('is-empty', !story);
    if (this.status) this.status.hidden = !story;
    text(this.name, story ? storySourceName(story) : '尚未打开剧情');
    if (story) {
      const details = [
        'AA 工程：' + story.project,
        story.source_type ? '文件类型：' + story.source_type : '',
        formatSourceSize(story.source_size) ? '大小：' + formatSourceSize(story.source_size) : '',
        formatSourceTime(story.source_modified) ? '修改：' + formatSourceTime(story.source_modified) : '',
      ].filter(Boolean);
      text(this.meta, details.join(' · '));
    } else text(this.meta, '打开一份剧本，就会建立只属于它的工作区');
    text(this.action, story ? '更换剧情' : '打开剧情文件');
  };

  function RecentStories(root, onOpen) { this.root = root; this.onOpen = onOpen; this.refreshGeneration = 0; this.expanded = false; }
  RecentStories.prototype.refresh = async function () {
    const generation = ++this.refreshGeneration;
    try {
    const stories = await exports.Api.request('/api/stories/recent');
    if (generation !== this.refreshGeneration) return;
    this.root.textContent = '';
    if (!stories.length) return;
    const title = element('h2', '', '最近使用的剧情');
    const list = element('div', 'recent-story-list');
    const onOpen = this.onOpen;
    const visibleStories = this.expanded ? stories : stories.slice(0, 3);
    visibleStories.forEach(function (story) {
      const entry = element('button', 'ghost recent-story');
      entry.type = 'button';
      const detail = element('span', 'recent-story-detail');
      const metadata = [
        story.source_type ? '文件类型：' + story.source_type : '',
        formatSourceSize(story.source_size) ? '大小：' + formatSourceSize(story.source_size) : '',
        formatSourceTime(story.source_modified) ? '修改：' + formatSourceTime(story.source_modified) : '',
      ].filter(Boolean).join(' · ');
      const detailChildren = [
        element('b', '', storySourceName(story)),
        element('span', 'dim', 'AA 工程：' + story.project),
      ];
      if (metadata) detailChildren.push(element('span', 'dim', metadata));
      detailChildren.push(element('span', 'dim', '最近打开：' + formatRecentTime(story.last_opened_at)));
      detail.append.apply(detail, detailChildren);
      const button = element('span', 'recent-story-button', '继续');
      entry.addEventListener('click', function () { return onOpen(story); });
      entry.append(detail, button);
      list.appendChild(entry);
    });
    if (stories.length > 3) {
      const toggle = element('button', 'ghost recent-story-more', this.expanded ? '收起' : '打开查看更多');
      toggle.type = 'button';
      const self = this;
      toggle.addEventListener('click', function () { self.expanded = !self.expanded; self.refresh(); });
      list.appendChild(toggle);
    }
    this.root.append(title, list);
    } catch (error) {
      if (generation !== this.refreshGeneration) return;
      this.root.textContent = '';
      this.root.appendChild(element('p', 'dim', '最近剧情暂时无法读取：' + error.message));
    }
  };

  function StoryAssetStrip(root) { this.root = root; this.clear(); }
  StoryAssetStrip.prototype.clear = function () {
    this.root.textContent = '';
    this.root.classList.add('is-empty');
    this.root.appendChild(element('p', 'dim', '打开剧情后显示当前剧情的自定义素材。'));
  };
  StoryAssetStrip.prototype.load = async function (storyToken) {
    const story = store.get();
    if (!story || story.story_token !== storyToken) return;
    this.root.textContent = '';
    this.root.classList.remove('is-empty');
    const heading = element('h2', '', '本剧情自定义素材');
    const summary = element('p', 'dim', '正在读取自定义素材…');
    this.root.append(heading, summary);
    try {
      const data = await exports.Api.request('/api/story/assets?story_token=' + encodeURIComponent(storyToken));
      if (store.get() !== story) return;
      const groups = ['characters', 'backgrounds', 'sounds', 'bgms'];
      const parts = groups.map(function (key) {
        const value = data[key];
        return key + ' ' + (Array.isArray(value) ? value.length : Object.keys(value || {}).length);
      });
      summary.textContent = parts.join(' · ');
    } catch (error) {
      if (store.get() === story) summary.textContent = '素材列表暂时无法读取：' + error.message;
      throw error;
    }
  };
  StoryAssetStrip.prototype.refresh = async function (story) {
    if (!story) { this.clear(); return; }
    return this.load(story.story_token);
  };

  function StoryContextStatus() { this.reset(); }
  StoryContextStatus.prototype.reset = function () {
    this.update({draft: '草稿：未载入', save: '保存：未载入', review: '审查：未审查', compile: '编译：未编译', install: '安装：未安装'});
  };
  StoryContextStatus.prototype.update = function (values) {
    const ids = {draft: 'storyDraftStatus', save: 'storySaveStatus', review: 'storyReviewStatus', compile: 'storyCompileStatus', install: 'storyInstallStatus'};
    Object.keys(values || {}).forEach(function (key) { const target = document.getElementById(ids[key]); if (target) target.textContent = values[key]; });
  };

  exports.StoryUI = {StoryContextBar: StoryContextBar, RecentStories: RecentStories, StoryAssetStrip: StoryAssetStrip, StoryContextStatus: StoryContextStatus};
})(window);
