// Real preference load/render methods; synthetic DOM and API only, no network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const readonlyHint = '这些字段不会改变生成结果；为避免误导，暂不可编辑。';
const prefs = {writing_tone: 'long_comedy', char_warning_threshold: 51,
  aa_pacing_wait_ms: 1001, max_stage_characters: 3};
const fieldIds = ['prefWritingTone', 'prefCharWarning', 'prefAaPacing', 'prefMaxStageCharacters'];

function harness(sourcePath) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('const SettingsController =');
  const end = source.indexOf('\n};', start) + 3;
  assert(start >= 0 && end > start);
  const nodes = new Map();
  for (const id of [...fieldIds, 'savePreferencesBtn', 'prefSaveHint']) {
    const node = {value: 'stale-value', textContent: id === 'prefSaveHint' ? readonlyHint : '',
      disabled: true};
    Object.defineProperty(node, 'innerHTML', {set() {assert.fail('Preference UI must use textContent');}});
    nodes.set(id, node);
  }
  const calls = [], renderedModels = [], renderedDiagnostics = [], roles = [];
  const h = {nodes, calls, renderedModels, renderedDiagnostics, roles,
    preferenceResult: async () => ({preferences: prefs})};
  const context = {console, AbortController: class {abort() {}}, setTimeout: (fn) => 1, clearTimeout: () => {}, document: {getElementById: id => nodes.get(id)},
    api: async (route, options) => {
      calls.push(route);
      if (route === '/settings/preferences') return await h.preferenceResult();
      if (route === '/settings/writing-model') return {model: {configured: true}};
      if (route === '/settings/diagnostics') return {writing_service: {status: 'online'}};
      if (route === '/settings/conversations') return [];
      assert.fail(`Unexpected route: ${route}`);
    }};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nglobalThis.controller = SettingsController;', context);
  const c = h.controller = context.controller;
  c.dialog = {showModal() {h.opened = true;}};
  c.readDirectionModelStatus = async () => ({model: {configured: false}});
  c.renderModelSettings = result => renderedModels.push(result);
  c.renderModelRoles = (...args) => roles.push(args);
  c.renderDiagnostics = result => renderedDiagnostics.push(result);
  c.renderArchivedConversations = () => {};
  return h;
}

function assertWarning(h) {
  const text = h.nodes.get('prefSaveHint').textContent;
  assert.match(text, /偏好.*读取失败/);
  assert(text.includes(readonlyHint), 'Keep truthful read-only metadata');
  assert(!text.includes('SYNTHETIC-SECRET') && !text.includes('<img'), 'Never echo backend errors');
  for (const id of fieldIds) assert.equal(h.nodes.get(id).value, '', 'Do not display stale/default values as saved');
  for (const id of [...fieldIds, 'savePreferencesBtn']) assert.equal(h.nodes.get(id).disabled, true);
}

const cases = {
  async preference_load_failure_is_visible_and_nonblocking(source) {
    const h = harness(source);
    h.preferenceResult = async () => {throw new Error('<img src=x> SYNTHETIC-SECRET C:/private');};
    await h.controller.open();
    assert.equal(h.opened, true);
    assertWarning(h);
    assert.equal(h.renderedModels.length, 1);
    assert.equal(h.renderedDiagnostics.length, 1);
    assert.equal(h.controller.writingModelStatus.model.configured, true);
    assert.equal(h.controller.directionModelStatus.model.configured, false);
    assert(h.calls.every(route => route.startsWith('/settings/')));
  },
  async preference_success_clears_warning_but_keeps_readonly(source) {
    const h = harness(source);
    h.preferenceResult = async () => {throw new Error('unavailable');};
    await h.controller.loadAll();
    assertWarning(h);
    h.preferenceResult = async () => ({preferences: prefs});
    await h.controller.loadAll();
    assert.equal(h.nodes.get('prefSaveHint').textContent, readonlyHint);
    assert.deepEqual(fieldIds.map(id => h.nodes.get(id).value), Object.values(prefs));
    for (const id of [...fieldIds, 'savePreferencesBtn']) assert.equal(h.nodes.get(id).disabled, true);
  },
  async preference_missing_payload_is_not_silent_success(source) {
    const h = harness(source);
    for (const response of [{}, null, {preferences: null}, {preferences: []}, {preferences: 'bad'}]) {
      h.preferenceResult = async () => response;
      await h.controller.loadAll();
      assertWarning(h);
    }
  },
  async preference_stale_load_does_not_replace_latest_warning(source) {
    const h = harness(source);
    let resolveOld;
    h.preferenceResult = () => new Promise(resolve => {resolveOld = resolve;});
    const old = h.controller.loadAll();
    h.preferenceResult = async () => {throw new Error('latest failure');};
    await h.controller.loadAll();
    assertWarning(h);
    resolveOld({preferences: prefs});
    await old;
    assertWarning(h);
  },
};

(async () => {
  const [name, source] = process.argv.slice(2);
  assert(cases[name], `Unknown case: ${name}`);
  await cases[name](source);
  process.stdout.write(JSON.stringify({case: name, passed: true, external_requests: 0}));
})().catch(error => {console.error(error); process.exitCode = 1;});
