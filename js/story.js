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
    text(this.name, story ? story.source_name || story.project : '尚未打开剧情');
    text(this.meta, story ? ('AA 工程：' + story.project) : '打开一份剧本，就会建立只属于它的工作区');
    text(this.action, story ? '更换剧情' : '打开剧情文件');
  };

  function RecentStories(root, onOpen) { this.root = root; this.onOpen = onOpen; this.refreshGeneration = 0; }
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
    stories.forEach(function (story) {
      const entry = element('button', 'ghost recent-story');
      entry.type = 'button';
      const detail = element('span', 'recent-story-detail');
      detail.append(
        element('b', '', story.source_name || story.project),
        element('span', 'dim', 'AA 工程：' + story.project),
        element('span', 'dim', '最近打开：' + formatRecentTime(story.last_opened_at))
      );
      const button = element('span', 'recent-story-button', '继续');
      entry.addEventListener('click', function () { onOpen(story); });
      entry.append(detail, button);
      list.appendChild(entry);
    });
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
    this.root.appendChild(element('p', 'dim', '打开剧情后显示共享素材。'));
  };
  StoryAssetStrip.prototype.load = async function (storyToken) {
    const story = store.get();
    if (!story || story.story_token !== storyToken) return;
    this.root.textContent = '';
    this.root.classList.remove('is-empty');
    const heading = element('h2', '', '本剧情素材');
    const summary = element('p', 'dim', '正在读取共享素材…');
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
