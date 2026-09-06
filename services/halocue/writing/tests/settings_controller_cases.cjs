// Run the real controller in a small DOM harness. API functions are stubs;
// this is a behavior test, not a browser or external-provider acceptance test.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function harness(sourcePath) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('const SettingsController =');
  const end = source.indexOf('\n};', start) + 3;
  assert(start >= 0 && end > start, 'SettingsController boundary not found');
  const nodes = new Map(), calls = [], toasts = [];
  function element(id) {
    if (!nodes.has(id)) {
      const listeners = new Map();
      const classes = new Set();
      nodes.set(id, {
        id, value: '', type: 'password', textContent: '', innerHTML: '', disabled: false,
        className: '', open: false,
        classList: {add(...xs) {xs.forEach(x => classes.add(x));},
          remove(...xs) {xs.forEach(x => classes.delete(x));}, contains(x) {return classes.has(x);},
          toggle(x, value) {if (value) classes.add(x); else classes.delete(x);}},
        addEventListener(type, fn) {listeners.set(type, [...(listeners.get(type) || []), fn]);},
        async fire(type) {for (const fn of listeners.get(type) || []) await fn({target: this, preventDefault(){}});},
        querySelectorAll() {return [];}, querySelector() {return null;}, focus() {},
        showModal() {this.open = true;}, close() {this.open = false;},
      });
    }
    return nodes.get(id);
  }
  const fields = {provider: 'settingsProvider', base_url: 'settingsBaseUrl',
    api_key: 'settingsApiKey', model: 'settingsModelName', max_tokens: 'settingsMaxTokens',
    timeout: 'settingsTimeout', reasoning_mode: 'settingsReasoningMode',
    input_cost_per_million: 'settingsInputCost', output_cost_per_million: 'settingsOutputCost',
    apply_scope: 'settingsApplyScope'};
  const h = {element, calls, toasts, apiResult: async (route, body) => ({model: body?.model || 'model-a', models: ['model-a'], latency_ms: 1}),
    fetchResult: async () => ({ok: true, environment: {workspace: {valid: false, path: null}, issues: []}})};
  const context = {
    console, URL, URLSearchParams, window: {location: {search: ''}},
    document: {getElementById: element, addEventListener() {}},
    FormData: class {get(name) {return fields[name] ? element(fields[name]).value : null;}},
    api: async (route, options) => {
      const body = options?.body ? JSON.parse(options.body) : null;
      calls.push({transport: 'api', route, body});
      return h.apiResult(route, body);
    },
    fetch: async (route, options) => {
      const body = options?.body ? JSON.parse(options.body) : null;
      calls.push({transport: 'fetch', route, body});
      const result = await h.fetchResult(route, body);
      return {ok: result.httpOk !== false, status: result.httpOk === false ? 409 : 200, json: async () => result};
    },
    toast: (message, error) => toasts.push({message, error: Boolean(error)}),
    esc: value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])),
    setTimeout() {}, state: {},
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nglobalThis.controller = SettingsController;', context);
  h.controller = context.controller;
  const c = h.controller;
  c.cachedPresets = [
    {id: 'a', name: 'Synthetic A', provider: 'openai', base_url: 'https://a.invalid/v1', default_model: 'model-a', models: [], api_key_env: 'SYNTHETIC_A_KEY'},
    {id: 'b', name: 'Synthetic B', provider: 'openai', base_url: 'https://b.invalid/v1', default_model: 'model-b', models: [], api_key_env: 'SYNTHETIC_B_KEY'},
  ];
  element('settingsProvider').value = 'openai';
  element('settingsBaseUrl').value = 'https://a.invalid/v1';
  element('settingsModelName').value = 'model-a';
  element('settingsApplyScope').value = 'both';
  c.activePresetId = 'a';
  c.init();
  c.loadAll = async () => {};
  calls.length = 0;
  h.enterKey = async value => {element('settingsApiKey').value = value; await element('settingsApiKey').fire('input');};
  return h;
}

const cases = {
  async preset_switch_clears_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-NOT-A-CREDENTIAL');
    h.controller.selectPreset('b');
    assert.equal(h.element('settingsApiKey').value, '');
    await h.controller.fetchModels();
    assert.equal(h.calls.at(-1).body.base_url, 'https://b.invalid/v1');
    assert.equal(h.calls.at(-1).body.api_key, '');
    assert(h.toasts.some(item => /密钥|Key/.test(item.message)) || /密钥|Key/.test(h.element('apiKeyStatusHint').textContent));
  },
  async manual_endpoint_edit_clears_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    h.element('settingsBaseUrl').value = 'https://custom.invalid/v1';
    await h.element('settingsBaseUrl').fire('input');
    assert.equal(h.element('settingsApiKey').value, '');
    await h.controller.saveModel(h.element('settingsModelForm'));
    const activations = h.calls.filter(call => call.route.endsWith(':activate'));
    assert.equal(activations.length, 2);
    for (const call of activations) {
      assert.equal(call.body.base_url, 'https://custom.invalid/v1');
      assert.equal(call.body.api_key, '');
      assert.equal(call.body.api_key_env, '', 'old preset env must not follow a custom endpoint');
    }
  },
  async protocol_edit_clears_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    h.element('settingsProvider').value = 'anthropic';
    await h.element('settingsProvider').fire('change');
    assert.equal(h.element('settingsApiKey').value, '');
    await h.controller.testConnection();
    const sent = h.calls.at(-1);
    assert.equal(sent.body.provider, 'anthropic');
    assert.equal(sent.body.api_key, '');
  },
  async programmatic_endpoint_change_is_guarded_before_send(source) {
    for (const method of ['fetchModels', 'testConnection', 'saveModel']) {
      const h = harness(source);
      await h.enterKey('SYNTHETIC-A');
      h.element('settingsBaseUrl').value = 'https://changed.invalid/v1';
      await h.controller[method](h.element('settingsModelForm'));
      const requests = h.calls.filter(call => call.body?.base_url);
      assert(requests.length);
      for (const call of requests) {
        assert.equal(call.body.api_key, '');
        assert(!call.body.api_key_env, 'unrelated environment key must not be selected');
      }
    }
  },
  async same_endpoint_model_change_keeps_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    h.element('settingsModelName').value = 'model-new';
    await h.element('settingsModelName').fire('input');
    h.element('settingsBaseUrl').value = 'https://A.invalid:443/v1/chat/completions/';
    await h.element('settingsBaseUrl').fire('input');
    await h.controller.fetchModels();
    assert.equal(h.calls.at(-1).body.api_key, 'SYNTHETIC-A');
  },
  async new_key_after_switch_is_allowed(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    h.controller.selectPreset('b');
    await h.enterKey('SYNTHETIC-B');
    await h.controller.saveModel(h.element('settingsModelForm'));
    const requests = h.calls.filter(call => call.route.endsWith(':activate'));
    assert.equal(requests.length, 2);
    for (const call of requests) {
      assert.equal(call.body.api_key, 'SYNTHETIC-B');
      assert.equal(call.body.api_key_env, 'SYNTHETIC_B_KEY');
    }
  },

  async stale_model_list_does_not_replace_new_endpoint_choices(source) {
    const h = harness(source);
    let resolve;
    h.apiResult = () => new Promise(done => {resolve = done;});
    const pending = h.controller.fetchModels();
    h.controller.selectPreset('b');
    h.element('settingsModelDatalist').innerHTML = 'new-endpoint-options';
    resolve({models: ['old-endpoint-model']});
    await pending;
    assert.equal(h.element('settingsModelDatalist').innerHTML, 'new-endpoint-options');
    assert.equal(h.element('fetchModelsBtn').disabled, false);
  },
  async stale_connection_test_does_not_validate_new_credentials(source) {
    const h = harness(source);
    let resolve;
    h.apiResult = () => new Promise(done => {resolve = done;});
    const pending = h.controller.testConnection();
    h.controller.selectPreset('b');
    resolve({model: 'old-model', latency_ms: 23, diagnostics: []});
    await pending;
    assert(!h.toasts.some(item => item.message.includes('连接成功')));
    assert(!h.element('modelDiagnosticsCard').innerHTML.includes('连通性测试通过'));
    assert.equal(h.element('testConnectionBtn').disabled, false);
  },
  async preset_environment_key_never_follows_manual_path_edit(source) {
    const h = harness(source);
    h.element('settingsBaseUrl').value = 'https://a.invalid/other-path/v1';
    await h.element('settingsBaseUrl').fire('change');
    await h.enterKey('SYNTHETIC-CUSTOM');
    await h.controller.saveModel(h.element('settingsModelForm'));
    for (const call of h.calls.filter(item => item.route.endsWith(':activate'))) {
      assert.equal(call.body.api_key, 'SYNTHETIC-CUSTOM');
      assert.equal(call.body.api_key_env, '');
    }
  },

  async invalid_aa_detection_never_enables_adoption(source) {
    const h = harness(source);
    h.element('aaWorkspaceInput').value = '/synthetic/missing';
    await h.controller.inspectAa();
    assert.equal(h.element('adoptAaBtn').disabled, true);
    assert(!h.toasts.some(item => item.message.includes('检测通过')));
    assert(!h.element('aaEnvironmentCard').className.split(' ').includes('valid'));
  },
  async aa_adoption_requires_current_inspection(source) {
    const h = harness(source);
    h.element('aaWorkspaceInput').value = '/synthetic/uninspected';
    await h.controller.adoptAa();
    assert.equal(h.calls.filter(call => call.route.includes('aa-workspace')).length, 0);
    assert(h.toasts.some(item => item.error));
  },
  async valid_executable_detection_adopts_resolved_workspace(source) {
    const h = harness(source);
    h.element('aaWorkspaceInput').value = '/synthetic/AzureArchive.exe';
    h.fetchResult = async route => route.endsWith('aa-environment')
      ? {ok: true, data: {environment: {workspace: {valid: true, path: '/synthetic/storage/data'}, issues: []}}}
      : {ok: true, data: {aa_workspace: {valid: true, path: '/synthetic/storage/data'}}};
    await h.controller.inspectAa();
    assert.equal(h.element('adoptAaBtn').disabled, false);
    assert(h.element('aaEnvironmentCard').innerHTML.includes('/synthetic/storage/data'));
    await h.controller.adoptAa();
    const sent = h.calls.find(call => call.route.endsWith('aa-workspace'));
    assert.deepEqual(sent.body, {path: '/synthetic/storage/data'});
    assert.equal(h.element('adoptAaBtn').disabled, true);
    assert(h.toasts.some(item => item.message.includes('成功采用')));
  },

  async edited_aa_selection_invalidates_detected_path(source) {
    for (const fireEvent of [true, false]) {
      const h = harness(source);
      h.element('aaWorkspaceInput').value = '/synthetic/A';
      h.fetchResult = async () => ({ok: true, environment: {workspace: {valid: true, path: '/synthetic/A/data'}}});
      await h.controller.inspectAa();
      h.element('aaWorkspaceInput').value = '/synthetic/B';
      if (fireEvent) await h.element('aaWorkspaceInput').fire('input');
      await h.controller.adoptAa();
      assert.equal(h.calls.filter(call => call.route.endsWith('aa-workspace')).length, 0);
      assert.equal(h.element('adoptAaBtn').disabled, true);
    }
  },
  async out_of_order_aa_detection_keeps_latest_result(source) {
    const h = harness(source), pending = [];
    h.fetchResult = (route, body) => new Promise(resolve => pending.push({body, resolve}));
    h.element('aaWorkspaceInput').value = '/synthetic/A';
    const first = h.controller.inspectAa();
    h.element('aaWorkspaceInput').value = '/synthetic/B';
    await h.element('aaWorkspaceInput').fire('input');
    const second = h.controller.inspectAa();
    pending[1].resolve({ok: true, environment: {workspace: {valid: false, path: null}, issues: []}});
    await second;
    pending[0].resolve({ok: true, environment: {workspace: {valid: true, path: '/synthetic/A/data'}, issues: []}});
    await first;
    assert.equal(h.element('adoptAaBtn').disabled, true);
    assert(!h.element('aaEnvironmentCard').innerHTML.includes('/synthetic/A/data'));
    assert.equal(h.element('inspectAaBtn').disabled, false);
  },
  async missing_aa_path_or_truthy_valid_flag_is_rejected(source) {
    for (const workspace of [{valid: true}, {valid: 'true', path: '/synthetic/data'}]) {
      const h = harness(source);
      h.fetchResult = async () => ({ok: true, environment: {workspace}});
      await h.controller.inspectAa();
      assert.equal(h.element('adoptAaBtn').disabled, true);
      assert(h.toasts.some(item => item.error));
    }
  },
  async aa_adoption_rejection_is_not_success(source) {
    for (const failure of [{ok: false, httpOk: false, error: {message: 'Directory disappeared'}},
      {ok: true, aa_workspace: {valid: true, path: '/different/path'}}]) {
      const h = harness(source);
      h.fetchResult = async route => route.endsWith('aa-environment')
        ? {ok: true, environment: {workspace: {valid: true, path: '/synthetic/data'}}} : failure;
      await h.controller.inspectAa();
      await h.controller.adoptAa();
      assert(!h.toasts.some(item => item.message.includes('成功采用')));
      assert.equal(h.element('adoptAaBtn').disabled, true);
      assert.equal(h.element('inspectAaBtn').disabled, false);
      assert.equal(h.element('aaWorkspaceInput').disabled, false);
    }
  },
  async duplicate_aa_adoption_submits_once(source) {
    const h = harness(source);
    let resolve;
    h.fetchResult = async route => route.endsWith('aa-environment')
      ? {ok: true, environment: {workspace: {valid: true, path: '/synthetic/data'}}}
      : new Promise(done => {resolve = done;});
    await h.controller.inspectAa();
    const first = h.controller.adoptAa();
    assert.equal(h.element('aaWorkspaceInput').disabled, true);
    await h.controller.adoptAa();
    await h.controller.inspectAa();
    assert.equal(h.calls.filter(call => call.route.endsWith('aa-workspace')).length, 1);
    assert.equal(h.calls.filter(call => call.route.endsWith('aa-environment')).length, 1);
    resolve({ok: true, aa_workspace: {valid: true, path: '/synthetic/data'}});
    await first;
    assert.equal(h.element('aaWorkspaceInput').disabled, false);
  },
  async aa_display_escapes_backend_path_and_error(source) {
    const h = harness(source);
    h.fetchResult = async () => ({ok: true, environment: {workspace: {valid: true, path: '/synthetic/<img onerror=bad>/data'}}});
    await h.controller.inspectAa();
    assert(!h.element('aaEnvironmentCard').innerHTML.includes('<img'));
    h.fetchResult = async () => ({ok: true, environment: {workspace: {valid: false}, issues: [{message: '<img onerror=bad>'}]}});
    await h.controller.inspectAa();
    assert(!h.element('aaEnvironmentCard').innerHTML.includes('<img'));
  },
  async backend_path_spelling_change_does_not_reuse_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    h.element('settingsBaseUrl').value = 'https://a.invalid/unused/../v1';
    await h.controller.fetchModels();
    assert.equal(h.calls.at(-1).body.api_key, '');
    assert.equal(h.calls.at(-1).body.api_key_env, '');
  },
  async saved_configuration_reload_clears_old_draft_key(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-A');
    const presets = h.controller.cachedPresets;
    h.controller.renderModelSettings({model: {provider: 'openai', base_url: 'https://b.invalid/v1', model: 'model-b'}, presets});
    assert.equal(h.element('settingsApiKey').value, '');
    assert.equal(h.element('settingsApiKey').type, 'password');
  },

};

(async () => {
  const name = process.argv[2], source = process.argv[3];
  assert(cases[name], `Unknown case: ${name}`);
  await cases[name](source);
  console.log(JSON.stringify({case: name, passed: true, external_requests: 0}));
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
