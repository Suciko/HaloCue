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
  const nodes = new Map(), calls = [], toasts = [], timers = [];
  function element(id) {
    if (!nodes.has(id)) {
      const listeners = new Map();
      const classes = new Set();
      nodes.set(id, {
        id, dataset: {}, value: '', type: 'password', textContent: '', innerHTML: '', disabled: false, checked: false, readOnly: false,
        className: '', open: false,
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = String(value); },
        removeAttribute(name) { delete this.attributes[name]; },
        getAttribute(name) { return this.attributes[name] ?? null; },
        classList: {add(...xs) {xs.forEach(x => classes.add(x));},
          remove(...xs) {xs.forEach(x => classes.delete(x));}, contains(x) {return classes.has(x);},
          toggle(x, value) {if (value) classes.add(x); else classes.delete(x);}},
        addEventListener(type, fn) {listeners.set(type, [...(listeners.get(type) || []), fn]);},
        async fire(type) {for (const fn of listeners.get(type) || []) await fn({target: this, preventDefault(){}});},
        querySelectorAll() {return [];}, querySelector() {return null;}, replaceChildren() {this.innerHTML='';}, reportValidity() {return true;}, focus() {},
        showModal() {this.open = true;}, close() {this.open = false;},
      });
    }
    return nodes.get(id);
  }
  const fields = {provider: 'settingsProvider', base_url: 'settingsBaseUrl',
    api_key: 'settingsApiKey', model: 'settingsModelName', max_tokens: 'settingsMaxTokens',
    context_window: 'settingsContextWindow', max_input_tokens: 'settingsMaxInputTokens',
    max_output_tokens: 'settingsMaxOutputTokens', token_limit_parameter: 'settingsTokenLimitParameter',
    timeout: 'settingsTimeout', reasoning_mode: 'settingsReasoningMode',
    input_cost_per_million: 'settingsInputCost', output_cost_per_million: 'settingsOutputCost',
    apply_scope: 'settingsApplyScope'};
  const h = {element, calls, toasts, timers, apiResult: async (route, body) => ({model: body?.model || 'model-a', models: ['model-a'], latency_ms: 1}),
    fetchResult: async () => ({ok: true, environment: {workspace: {valid: false, path: null}, issues: []}})};
  const context = {
    console, URL, URLSearchParams, AbortController, CustomEvent: class { constructor(type, options) {this.type=type; this.detail=options.detail;} }, Option: class { constructor(text, value) {this.text = text; this.value = value;} }, clearTimeout() {}, window: {location: {search: ''}, dispatchEvent() {}},
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
    setTimeout(fn, ms) {timers.push({fn, ms}); return timers.length;}, state: {},
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
  h.loadAll = c.loadAll.bind(c);
  c.loadAll = async () => {};
  calls.length = 0;
  h.enterKey = async value => {element('settingsApiKey').value = value; await element('settingsApiKey').fire('input');};
  return h;
}

const cases = {
  codex_connection_shares_provider_workspace_without_api_fields(source) {
    const h = harness(source), c = h.controller;
    c.cachedPresets.unshift({id:'codex', name:'Codex', provider:'codex', base_url:'', models:[]});
    c.selectPreset('codex');
    assert.equal(h.element('codexConnection').hidden, false);
    assert.equal(h.element('settingsModelForm').hidden, true);
    assert.equal(h.element('settingsModelForm').inert, true);
    assert.equal(h.calls.length, 0);
    c.selectPreset('a');
    assert.equal(h.element('codexConnection').hidden, true);
    assert.equal(h.element('settingsModelForm').hidden, false);
    c.subscriptionOnly = true;
    c.activePresetId = 'codex';
    c.renderProviderPresets();
    assert(h.element('vendorPresetGrid').innerHTML.includes('Codex'));
    assert(!h.element('vendorPresetGrid').innerHTML.includes('Synthetic A'));
    c.selectPreset('a');
    assert.equal(c.activePresetId, 'codex');
  },
  async provider_free_access_badges_are_visible_searchable_and_escaped(source) {
    const h = harness(source);
    const preset = h.controller.cachedPresets[0];
    Object.assign(preset, {access_badge:'免费试用', access_note:'试用受速率限制，不代表永久无限量。'});
    h.controller.providerSearchQuery = '免费';
    h.controller.renderProviderPresets();
    assert.match(h.element('vendorPresetGrid').innerHTML, /vendor-access-badge/);
    assert.match(h.element('vendorPresetGrid').innerHTML, /免费试用/);
    assert(!h.element('vendorPresetGrid').innerHTML.includes('Synthetic B'));
    h.controller.updateSelectedProviderSummary(preset);
    assert.equal(h.element('selectedProviderAccessBadge').textContent, '免费试用');
    assert.equal(h.element('selectedProviderAccessBadge').hidden, false);
    assert.match(h.element('selectedProviderAccessNote').textContent, /速率限制/);
    preset.access_badge = '<img src=x onerror=alert(1)>';
    h.controller.providerSearchQuery = '';
    h.controller.renderProviderPresets();
    assert(!h.element('vendorPresetGrid').innerHTML.includes('<img'));
    assert(h.element('vendorPresetGrid').innerHTML.includes('&lt;img'));
  },
  async paid_or_custom_providers_do_not_keep_free_access_labels(source) {
    const h = harness(source);
    const preset = h.controller.cachedPresets[0];
    Object.assign(preset, {access_badge:'限额免费', access_note:'有配额限制'});
    h.controller.updateSelectedProviderSummary(preset);
    h.controller.selectPreset('b');
    assert.equal(h.element('selectedProviderAccessBadge').hidden, true);
    assert.equal(h.element('selectedProviderAccessBadge').textContent, '');
    assert.equal(h.element('selectedProviderAccessNote').hidden, true);
    h.element('settingsBaseUrl').value = 'https://custom.invalid/v1';
    h.controller.updateSelectedProviderSummary(preset);
    assert.equal(h.element('selectedProviderAccessNote').textContent, '');
  },
  async known_model_auto_fills_limits_and_maximum_output(source) {
    const h = harness(source);
    h.controller.capabilityCatalog = new Map([['model-new', {model:'model-new', known:true, source:'official_preset', context_window:1050000, max_output_tokens:128000, token_limit_parameter:'max_completion_tokens'}]]);
    h.element('settingsModelName').value = 'model-new';
    await h.element('settingsModelName').fire('input');
    assert.equal(h.element('settingsContextWindow').value, '1050000');
    assert.equal(h.element('settingsMaxOutputTokens').value, '128000');
    assert.equal(h.element('settingsMaxTokens').value, '128000');
    assert.equal(h.element('settingsTokenLimitParameter').value, 'max_completion_tokens');
    assert.equal(h.element('settingsMaxTokens').readOnly, true);
    assert.equal(h.calls.length, 0, 'known catalog must not make a paid inference request');
  },
  async switching_unknown_model_drops_previous_limits(source) {
    const h = harness(source);
    h.element('settingsContextWindow').value='1050000';
    h.element('settingsMaxTokens').value='128000';
    h.element('settingsMaxOutputTokens').value='128000';
    h.element('settingsModelName').value='unknown-fixture';
    await h.element('settingsModelName').fire('input');
    assert.equal(h.element('settingsContextWindow').value,'');
    assert.equal(h.element('settingsMaxOutputTokens').value,'');
    assert.equal(h.element('settingsMaxTokens').value,'8192');
    h.apiResult=async()=>({known:false, model:'unknown-fixture'});
    await h.controller.lookupModelCapabilities();
    assert.match(h.element('modelCapabilitySummary').textContent,/未知|未公布/);
    assert(!h.element('modelCapabilitySummary').textContent.includes('自动填入 128'));
  },
  async fetched_provider_limits_override_catalog_automatically(source) {
    const h=harness(source);
    h.controller.capabilityCatalog=new Map([['model-a',{model:'model-a',known:true,source:'official_preset',context_window:128000,max_output_tokens:64000}]]);
    h.apiResult=async()=>({models:['model-a'],model_details:[{model:'model-a',known:true,source:'provider_metadata',context_window:32768,max_output_tokens:16384,provider_fields:['context_window','max_output_tokens']} ]});
    await h.controller.fetchModels();
    assert.equal(h.element('settingsContextWindow').value,'32768');
    assert.equal(h.element('settingsMaxTokens').value,'16384');
    assert.match(h.element('modelCapabilitySummary').textContent,/接口返回/);
  },
  async id_only_provider_does_not_mislabel_catalog_parameters(source) {
    const h=harness(source);
    h.apiResult=async()=>({models:['model-a'],model_details:[{model:'model-a',known:true,source:'official_preset',context_window:128000,max_output_tokens:32000,provider_fields:[]} ]});
    await h.controller.fetchModels();
    assert.equal(h.element('settingsMaxTokens').value,'32000');
    assert.match(h.element('modelCapabilitySummary').textContent,/内置/);
    assert(!h.element('modelCapabilitySummary').textContent.includes('接口返回'));
  },
  async stale_capability_response_never_fills_new_model(source) {
    const h=harness(source);
    let finish;
    h.apiResult=()=>new Promise(resolve=>{finish=resolve});
    const pending=h.controller.lookupModelCapabilities();
    h.element('settingsModelName').value='another-model';
    await h.element('settingsModelName').fire('input');
    finish({model:'model-a',known:true,source:'models_dev',context_window:128000,max_output_tokens:64000});
    await pending;
    assert.equal(h.element('settingsMaxOutputTokens').value,'');
    assert.equal(h.element('settingsMaxTokens').value,'8192');
  },
  async manual_override_is_not_replaced_by_inflight_detection(source) {
    const h=harness(source);
    let finish;
    h.apiResult=()=>new Promise(resolve=>{finish=resolve});
    const pending=h.controller.lookupModelCapabilities();
    h.element('manualModelParams').checked=true;
    await h.element('manualModelParams').fire('change');
    h.element('settingsMaxTokens').value='2048';
    finish({model:'model-a',known:true,source:'models_dev',context_window:128000,max_output_tokens:64000});
    await pending;
    assert.equal(h.element('settingsMaxTokens').value,'2048');
    assert.equal(h.element('settingsMaxTokens').readOnly,false);
  },
  async automatic_limits_finish_before_activation_payload(source) {
    const h=harness(source);
    h.element('settingsApplyScope').value='writing';
    h.element('settingsModelName').value='private-new';
    await h.element('settingsModelName').fire('input');
    h.apiResult=async(route,body)=>route.includes('model-capabilities')
      ? {known:true,model:'private-new',source:'models_dev',context_window:65536,max_output_tokens:16384}
      : {model:body?.model};
    await h.controller.saveModel(h.element('settingsModelForm'));
    const sent=h.calls.find(call=>call.route.endsWith(':activate'));
    assert.equal(sent.body.max_tokens,16384);
    assert.equal(sent.body.max_output_tokens,16384);
  },
  async preset_connections_are_automatic_custom_stays_editable(source) {
    const h=harness(source);
    const preset=h.controller.cachedPresets[1];
    Object.assign(preset,{website_url:'https://b.invalid/',api_key_url:'https://b.invalid/keys',docs_url:'https://b.invalid/docs'});
    h.controller.selectPreset('b');
    assert.equal(h.element('modelEndpointDetails').hidden,true);
    assert.equal(h.element('providerWebsiteLink').getAttribute('href'),'https://b.invalid/');
    assert.equal(h.element('providerApiKeyLink').getAttribute('href'),'https://b.invalid/keys');
    assert.equal(h.element('providerWebsiteLink').getAttribute('rel'),'noopener noreferrer');
    h.element('settingsBaseUrl').value='https://relay.invalid/v1';
    await h.element('settingsBaseUrl').fire('input');
    assert.equal(h.element('modelEndpointDetails').hidden,false);
    assert.equal(h.element('providerWebsiteLink').hidden,true);
    assert.equal(h.controller.activePresetId,'custom');
  },
  async provider_links_reject_non_https_and_embedded_credentials(source) {
    const h=harness(source),p=h.controller.cachedPresets[0];
    Object.assign(p,{website_url:'javascript:alert(1)',api_key_url:'https://secret@site.invalid/'});
    h.controller.updateSelectedProviderSummary(p);
    assert.equal(h.element('providerWebsiteLink').hidden,true);
    assert.equal(h.element('providerApiKeyLink').hidden,true);
  },
  async activation_replaces_old_test_with_current_result(source) {
    const h = harness(source);
    h.element('settingsApplyScope').value = 'writing';
    const card = h.element('modelDiagnosticsCard');
    card.className = 'diagnostics-card';
    card.innerHTML = 'Previous connection test';
    await h.controller.saveModel(h.element('settingsModelForm'));
    assert.equal(card.className, 'diagnostics-card hidden');
    assert.equal(card.innerHTML, '');
    assert.match(h.element('modelApplyStatus').innerHTML, /model-a/);
    assert.match(h.element('modelApplyStatus').innerHTML, /已通过测试并启用/);
  },
  async expanding_saved_writing_model_to_aa_uses_server_side_credential_relay(source) {
    const h = harness(source);
    let activation = 0;
    h.apiResult = async route => route === '/settings/writing-model:activate'
      ? {model: {model: 'model-a', config_revision: `model-config-${++activation}`}}
      : {model: {model: 'model-a'}};
    h.element('settingsApplyScope').value = 'writing';
    await h.enterKey('SYNTHETIC-KEY');
    await h.controller.saveModel(h.element('settingsModelForm'));
    assert.equal(h.element('settingsApiKey').value, '', 'successful save clears only the form draft');

    h.element('settingsApplyScope').value = 'both';
    await h.controller.saveModel(h.element('settingsModelForm'));

    const relay = h.calls.find(call => call.route === '/settings/writing-model:activate-direction');
    assert(relay, `AA activation should relay the already-saved credential inside the local backend; calls=${JSON.stringify(h.calls)}`);
    assert.deepEqual(relay.body, {expected_config_revision: 'model-config-2'});
    assert(!h.calls.some(call => call.route === '/production/api/v1/settings/direction-model:activate'),
      'the browser must not need to resend or receive the saved secret');
    assert(!JSON.stringify(relay.body).includes('SYNTHETIC-KEY'));
    assert.match(h.element('modelApplyStatus').innerHTML, /AA 演出助手/);
    assert.match(h.element('modelApplyStatus').innerHTML, /已通过测试并启用/);
  },
  async activation_failure_focuses_visible_result_after_refresh(source) {
    const h = harness(source);
    h.element('settingsApplyScope').value = 'writing';
    await h.enterKey('SYNTHETIC-SECRET');
    h.apiResult = async () => { throw new Error('HTTP 403 SYNTHETIC-SECRET'); };
    const focused = [];
    h.controller.focusModelResult = id => focused.push(id);
    await h.controller.saveModel(h.element('settingsModelForm'));
    assert.deepEqual(focused, ['modelApplyStatus']);
    const result = h.element('modelApplyStatus');
    assert.equal(result.hidden, false);
    assert.match(result.innerHTML, /HTTP 403/);
    assert(!result.innerHTML.includes('SYNTHETIC-SECRET'));
    assert.equal(h.element('settingsApiKey').value, 'SYNTHETIC-SECRET');
    assert.equal(h.element('modelConfigFields').disabled, false);
  },
  async activation_result_scrolls_inside_settings_above_footer(source) {
    const h = harness(source);
    const dialog = h.element('settingsDialog'), card = h.element('modelApplyStatus');
    const content = {scrollTop: 0, getBoundingClientRect: () => ({top: 100, bottom: 720})};
    dialog.open = true;
    dialog.querySelector = selector => selector === '.settings-content' ? content : null;
    card.focus = () => {card.focused = true;};
    card.getBoundingClientRect = () => ({top: 800, bottom: 900, height: 100});
    h.element('testConnectionBtn').closest = () => ({getBoundingClientRect: () => ({top: 650})});
    h.controller.focusModelResult('modelApplyStatus');
    assert.equal(card.focused, true);
    assert.equal(content.scrollTop, 262);
    dialog.open = false;
    card.focused = false;
    h.controller.focusModelResult('modelApplyStatus');
    assert.equal(card.focused, false);
  },
  async advanced_limits_are_identical_in_test_and_activation(source) {
    const h = harness(source);
    h.element('settingsContextWindow').value = '65536';
    h.element('settingsMaxInputTokens').value = '48000';
    h.element('settingsMaxOutputTokens').value = '8192';
    h.element('settingsMaxTokens').value = '4096';
    h.element('settingsTokenLimitParameter').value = 'max_tokens';
    h.element('settingsApplyScope').value = 'writing';
    await h.controller.testConnection();
    await h.controller.saveModel(h.element('settingsModelForm'));
    const sent = h.calls.filter(call => ['/settings/writing-model/test','/settings/writing-model:activate'].includes(call.route));
    assert.equal(sent.length, 2);
    for (const call of sent) {
      assert.equal(call.body.context_window, 65536);
      assert.equal(call.body.max_input_tokens, 48000);
      assert.equal(call.body.max_output_tokens, 8192);
      assert.equal(call.body.max_tokens, 4096);
      assert.equal(call.body.token_limit_parameter, 'max_tokens');
    }
  },
  async empty_model_stays_in_settings_without_request(source) {
    const h = harness(source);
    h.element('settingsModelName').value = '   ';
    await h.controller.testConnection();
    assert.equal(h.calls.length, 0);
    assert.match(h.element('settingsModelError').textContent, /模型名称/);
    assert.equal(h.element('settingsModelName').getAttribute('aria-invalid'), 'true');
    assert.match(h.element('modelDiagnosticsCard').innerHTML, /连接测试未通过/);
  },
  async failed_model_fetch_is_persistent_and_redacted(source) {
    const h = harness(source);
    await h.enterKey('SYNTHETIC-SECRET');
    h.apiResult = async () => { const error = new Error('HTTP 401 SYNTHETIC-SECRET'); error.status = 401; throw error; };
    await h.controller.fetchModels();
    const card = h.element('modelDiagnosticsCard');
    assert.match(card.innerHTML, /身份验证失败/);
    assert(!card.innerHTML.includes('SYNTHETIC-SECRET'));
    assert.equal(h.element('settingsApiKey').value, 'SYNTHETIC-SECRET');
    assert.match(card.innerHTML, /data-model-retry="fetch"/);
  },
  async connection_failures_distinguish_causes(source) {
    for (const [message, status, expected] of [
      ['Unauthorized', 401, /身份验证失败/],
      ['unsupported parameter: temperature', 400, /不支持当前请求参数/],
      ['request timed out', 504, /连接超时/],
    ]) {
      const h = harness(source);
      h.apiResult = async () => { const error = new Error(message); error.status = status; throw error; };
      await h.controller.testConnection();
      assert.match(h.element('modelDiagnosticsCard').innerHTML, expected);
      assert.match(h.element('modelDiagnosticsCard').innerHTML, /data-model-retry="test"/);
    }
  },
  async backend_passed_steps_render_as_normal_after_stale_retry(source) {
    const h = harness(source);
    h.controller.invalidateModelResult();
    h.apiResult = async () => ({
      model: 'test-writer-a', latency_ms: 23,
      diagnostics: [
        {step: 'network', status: 'passed', label: '接口网络可达'},
        {step: 'auth', status: 'passed', label: '鉴权有效'},
        {step: 'response', status: 'passed', label: '响应正常 (23ms)'},
      ],
    });
    await h.controller.testConnection();
    const card = h.element('modelDiagnosticsCard');
    assert.equal(card.className, 'diagnostics-card');
    assert.match(card.innerHTML, /连通性测试通过/);
    assert.equal((card.innerHTML.match(/需要检查/g) || []).length, 0);
    assert.equal((card.innerHTML.match(/正常<\/span>/g) || []).length, 3);
  },
  async model_result_scrolls_inside_settings_above_sticky_actions(source) {
    const h = harness(source);
    const dialog = h.element('settingsDialog'), card = h.element('modelDiagnosticsCard');
    const content = {scrollTop: 0, getBoundingClientRect: () => ({top: 100, bottom: 990})};
    dialog.open = true;
    dialog.querySelector = selector => selector === '.settings-content' ? content : null;
    card.focus = () => {card.focused = true;};
    card.getBoundingClientRect = () => ({top: 1023, bottom: 1208});
    h.element('testConnectionBtn').closest = () => ({getBoundingClientRect: () => ({top: 930})});
    h.controller.focusModelResult();
    assert.equal(card.focused, true);
    assert.equal(content.scrollTop, 290);
    dialog.open = false;
    content.scrollTop = 0;
    card.focused = false;
    h.controller.focusModelResult();
    assert.equal(content.scrollTop, 0);
    assert.equal(card.focused, false);
  },
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
    h.element('settingsApplyScope').value = 'writing';
    await h.enterKey('SYNTHETIC-A');
    h.element('settingsBaseUrl').value = 'https://custom.invalid/v1';
    await h.element('settingsBaseUrl').fire('input');
    assert.equal(h.element('settingsApiKey').value, '');
    await h.controller.saveModel(h.element('settingsModelForm'));
    const activations = h.calls.filter(call => call.route.endsWith(':activate'));
    assert.equal(activations.length, 1);
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

  async distinct_model_roles_are_shown_independently(source) {
    const h = harness(source);
    h.apiResult = async route => route === '/settings/writing-model'
      ? {ok: true, model: {configured: true, model: 'writer-A', provider: 'openai', base_url: 'https://writer.invalid/v1', activation_status: 'active', last_tested_at: 'synthetic'}, presets: []} : {};
    h.fetchResult = async () => ({ok: true, model: {configured: true, model: 'director-B', provider: 'openai', base_url: 'http://localhost:11434/v1', activation_status: 'saved_unverified'}});
    await h.loadAll();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.element('writingModelRoleName').textContent, 'writer-A');
    assert.equal(h.element('directionModelRoleName').textContent, 'director-B');
    assert(h.element('writingModelRoleState').textContent.includes('已测试'));
    assert(h.element('directionModelRoleState').textContent.includes('未测试'));
    assert(h.element('modelScopeNotice').textContent.includes('分别'));
  },
  async unavailable_direction_model_is_not_claimed_connected(source) {
    const h = harness(source);
    h.apiResult = async () => ({model: {configured: true, model: 'writer-only', provider: 'openai'}, presets: []});
    h.fetchResult = async () => {throw new Error('offline');};
    await h.loadAll();
    await new Promise(resolve => setImmediate(resolve));
    assert(h.element('directionModelRoleState').textContent.includes('不可用'));
    assert(!h.element('directionModelRoleState').textContent.includes('已连接'));
  },

  async hanging_production_does_not_block_writing_settings(source) {
    const h = harness(source);
    h.apiResult = async route => route === '/settings/writing-model'
      ? {model: {configured:true, model:'writer', provider:'openai', base_url:'https://writer.invalid/v1'}, presets: []} : {};
    h.fetchResult = () => new Promise(() => {});
    await Promise.race([h.loadAll(), new Promise((_, reject) => setTimeout(() => reject(new Error('writing settings waited for production')), 150))]);
    assert.equal(h.element('writingModelRoleName').textContent, 'writer');
    h.controller.loadAll = h.loadAll;
    h.element('settingsApplyScope').value = 'writing';
    await Promise.race([h.controller.saveModel(h.element('settingsModelForm')), new Promise((_, reject) => setTimeout(() => reject(new Error('writing save waited for production')), 150))]);
    assert.equal(h.element('saveAndApplyModelBtn').disabled, false);
  },

  async direction_status_timeout_changes_pending_to_unavailable(source) {
    const h = harness(source);
    h.fetchResult = () => new Promise(() => {});
    await h.loadAll();
    assert(h.element('directionModelRoleState').textContent.includes('读取中'));
    const timeout = h.timers.find(timer => timer.ms === 5000);
    assert(timeout, 'direction status must have a bounded timeout');
    timeout.fn();
    await new Promise(resolve => setImmediate(resolve));
    assert(h.element('directionModelRoleState').textContent.includes('不可用'));
  },

};

(async () => {
  const name = process.argv[2], source = process.argv[3];
  assert(cases[name], `Unknown case: ${name}`);
  await cases[name](source);
  console.log(JSON.stringify({case: name, passed: true, external_requests: 0}));
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
