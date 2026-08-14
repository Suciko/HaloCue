const fs = require('fs');
const path = require('path');
const vm = require('vm');

function createHarness(config) {
  config = config || {};
  const nodes = Object.create(null);
  const storage = Object.assign(Object.create(null), config.storage || {});
  const documentListeners = Object.create(null);
  const windowListeners = Object.create(null);
  let activeElement = null;

  function makeClassList() {
    const values = new Set();
    return {
      add: value => values.add(value),
      remove: value => values.delete(value),
      contains: value => values.has(value),
      toggle(value, force) {
        const next = force === undefined ? !values.has(value) : Boolean(force);
        if (next) values.add(value); else values.delete(value);
        return next;
      },
    };
  }

  function node(selector) {
    const listeners = Object.create(null);
    const attrs = Object.create(null);
    let ownText = '';
    const result = {
      selector: selector || '', value: '', checked: false, disabled: false, hidden: false,
      dataset: {}, children: [], classList: makeClassList(),
      appendChild(child) { this.children.push(child); return child; },
      append() { Array.from(arguments).forEach(child => this.appendChild(child)); },
      removeChild() { return this.children.shift(); },
      get firstChild() { return this.children[0]; },
      addEventListener(type, handler) { (listeners[type] || (listeners[type] = [])).push(handler); },
      dispatch(type, event) {
        let value;
        (listeners[type] || []).forEach(handler => { value = handler(event || {target: this}); });
        return value;
      },
      click() { return this.dispatch('click', {target: this}); },
      closest(query) { return query === '[data-action]' && this.dataset.action ? this : null; },
      focus() { activeElement = this; },
      setAttribute(name, value) { attrs[name] = String(value); },
      getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
      querySelector() {
        if (this.selector === '#mBrowse') return get('#closeBrowse');
        if (this.selector === '#mEdit') return get('#closeEdit');
        if (this.selector === '#mApproveAll') return get('#approveAllConfirm');
        return node();
      },
      insertRow() { return node(); },
      insertCell() { return node(); },
    };
    Object.defineProperty(result, 'textContent', {
      get() { return ownText + this.children.map(child => child && child.textContent || '').join(''); },
      set(value) {
        ownText = String(value || ''); this.children.length = 0;
        if (config.onText) config.onText(this.selector, ownText);
      },
    });
    return result;
  }

  function get(selector) { return nodes[selector] || (nodes[selector] = node(selector)); }
  [
    '#path', '#proj', '#s1info', '#s2', '#s3', '#s4', '#cast', '#s2sum', '#bgq', '#bgready',
    '#bggrid', '#backgroundBrowserStatus', '#backgroundLoadMore', '#go', '#hint', '#backgroundRequestsPanel', '#backgroundRequestList',
    '#continueBackgroundBuild', '#backgroundContinueHint', '#rvDraftSelect', '#rvStatus',
    '#rvInstall', '#rvCompile', '#rvApproveAll', '#rvValidate', '#rvCards', '#storyPlayer',
    '#rvReviewFilters', '#rvFilterAll', '#rvFilterPending', '#rvFilterBlocking', '#rvFilterDirection',
    '#rvCardJump', '#rvJump', '#rvFilterStatus', '#rvSelectionLabel', '#rvCardToolbar', '#reviewPhase',
    '#log', '#goAnnotate', '#generationFailure', '#generationFailureTitle', '#generationFailureMessage',
    '#generationFailureAction', '#generationFailureTechnical', '#generationFailureRetry', '#generationFailureDraft',
    '#bgsel', '#modelProfileSelect', '#modelProfileId', '#modelProfileName',
    '#modelProvider', '#modelBaseUrl', '#modelName', '#modelMaxTokens', '#modelMaxTokensHint', '#modelRestoreMaxTokens', '#modelVision',
    '#modelApiKey', '#modelSaveKey', '#modelStatus', '#modelOptions', '#modelDiscoveryList', '#welcomePanel', '#recentStories',
    '#storyContextBar', '#storyContextName', '#storyContextMeta', '#storyContextAction', '#storyHistoryAction', '#storyContextStatus',
    '#storyDraftStatus', '#storySaveStatus', '#storyReviewStatus', '#storyCompileStatus', '#storyInstallStatus',
    '#storyLoadRetry', '#storyAssetStrip', '#stat',
    '#aaSetupGate', '#aaSetupGateMessage', '#chooseStoryButton', '#analyzeStoryButton',
    '#readyAA', '#readyDatabase', '#readyModel', '#mBrowse', '#mEdit', '#mApproveAll', '#closeBrowse', '#closeEdit',
    '#approveAllConfirm', '#approveAllCancel', '#approveAllStatus',
    '#browseTitle', '#bdir', '#chooseCurrentDir', '#blist', '#editTitle', '#editWho', '#editText',
    '#editFace', '#editEmo', '#editAct', '#editFx', '#install', '#settingsDrawer', '#settingsBackdrop',
    '#helpDrawer', '#helpBackdrop', '#view-create', '#modelSettings'
  ].forEach(get);
  get('input[name=anno]:checked').value = 'no';

  const document = {
    querySelector: get,
    querySelectorAll: () => [],
    getElementById: id => get('#' + id),
    createElement: () => node(),
    createDocumentFragment: () => node(),
    addEventListener(type, handler) { (documentListeners[type] || (documentListeners[type] = [])).push(handler); },
    dispatch(type, event) {
      let value;
      (documentListeners[type] || []).forEach(handler => { value = handler(event); });
      return value;
    },
    get activeElement() { return activeElement; },
  };

  const defaultRequest = async function (requestPath) {
    if (requestPath === '/api/stories/recent') return config.recent || [];
    if (requestPath === '/api/setup/status') return {aa: {connected: true, path: ''}, database: {ready: true}, model: {configured: false}};
    if (requestPath === '/api/state') return {stats: {}};
    if (requestPath === '/api/llm/profiles') return {profiles: []};
    if (requestPath === '/api/drafts') return [];
    if (requestPath.startsWith('/api/story/assets')) return {characters: [], backgrounds: [], sounds: [], bgms: []};
    if (requestPath.startsWith('/api/backgrounds')) return [];
    if (requestPath.startsWith('/api/browse')) return {dir: '', dirs: [], files: []};
    return {};
  };
  const api = {
    json: (method, payload) => ({method: method, payload: payload}),
    request: config.request || defaultRequest,
    poll: config.poll || (async () => ({state: 'succeeded'})),
  };
  const window = {
    Api: api,
    StoryAssets: config.storyAssets,
    ReviewWorkspace: config.reviewWorkspace,
    Preview: config.preview,
    StoryJobs: config.storyJobs,
    ModelSettings: config.modelSettings,
    CardList: config.cardList || {renderCardList() {}},
    Player: config.Player || function () { this.pause = function () {}; this.loadCards = function () {}; this.jumpToCard = function () {}; },
    addEventListener(type, handler) { (windowListeners[type] || (windowListeners[type] = [])).push(handler); },
    dispatchEvent(event) {
      (windowListeners[event.type] || []).forEach(handler => handler(event));
      return true;
    },
  };
  function CustomEvent(type, options) { this.type = type; this.detail = options && options.detail; }
  const sandbox = {
    window: window, document: document,
    localStorage: {
      getItem(key) { return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null; },
      setItem(key, value) { storage[key] = String(value); },
      removeItem(key) { delete storage[key]; },
    },
    setTimeout: config.setTimeout || (() => {}),
    console: console, URLSearchParams: URLSearchParams, Promise: Promise, Error: Error,
    CustomEvent: CustomEvent,
  };
  const root = path.resolve(__dirname, '..', 'js');
  vm.runInNewContext(fs.readFileSync(path.join(root, 'story.js'), 'utf8'), sandbox);
  if (!window.ModelSettings) vm.runInNewContext(fs.readFileSync(path.join(root, 'model.js'), 'utf8'), sandbox);
  if (config.storyPicker) vm.runInNewContext(fs.readFileSync(path.join(root, 'story_picker.js'), 'utf8'), sandbox);
  vm.runInNewContext(fs.readFileSync(path.join(root, 'app.js'), 'utf8'), sandbox);
  if (config.aaReady !== false && window.AppRuntime && window.AppRuntime.applyAAReadiness) {
    window.AppRuntime.applyAAReadiness({connected: true, program: {status: 'recognized'}});
  }

  return {
    window: window, document: document, nodes: nodes, storage: storage, get: get,
    getActiveElement() { return activeElement; },
    clickAction(action, trigger) {
      const target = trigger || node(); target.dataset.action = action;
      return document.dispatch('click', {target: target});
    },
    async load() {
      (windowListeners.load || []).forEach(handler => handler());
      await this.drain();
    },
    async drain() { for (let index = 0; index < 8; index += 1) await Promise.resolve(); },
  };
}

module.exports = {createHarness};
