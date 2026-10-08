(() => {
  'use strict';
  const panel = document.getElementById('codexConnection');
  if (!panel) return;
  const status = panel.querySelector('[data-codex-status]');
  const form = panel.querySelector('[data-codex-form]');
  const model = form.elements.model;
  let busy = false;
  let snapshot = null;
  let poll = null;
  let savedModel = '';
  let scopeDirty = false;
  function savedScopeConfig() {
    if (typeof SettingsController === 'undefined') return null;
    const value = form.elements.scope.value === 'direction'
      ? SettingsController.directionModelStatus?.model
      : SettingsController.writingModelStatus?.model;
    return value?.provider === 'codex' && value.configured ? value : null;
  }
  function restoreSavedScope() {
    const config = savedScopeConfig();
    if (scopeDirty || !config) return;
    savedModel = config.model;
    if ([...model.options].some(item => item.value === savedModel)) model.value = savedModel;
    if (config.timeout) form.elements.timeout.value = config.timeout;
  }
  async function request(path, body, production = false) {
    const response = await fetch(`${production ? '/production' : ''}/api/v1/settings/${path}`, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error?.message || 'Codex 连接失败，请检查登录状态。');
    return result;
  }
  function message(text, failed = false) {
    status.textContent = text;
    status.dataset.failed = String(failed);
  }
  function controls() {
    panel.querySelectorAll('button').forEach(button => { button.disabled = busy; });
    panel.querySelector('[data-codex-action=login]').disabled = busy || snapshot?.installed === false;
    const ready = snapshot?.state === 'ready' && model.options.length > 0 && !!model.value;
    form.querySelector('[type=submit]').disabled = busy || !ready || !form.elements.subscription_only_acknowledged.checked;
    form.querySelectorAll('input').forEach(input => {input.disabled = busy;});
    model.disabled = busy || !ready;
  }
  function render(value) {
    snapshot = value;
    const selected = (!scopeDirty && savedScopeConfig()?.model) || model.value || savedModel;
    model.replaceChildren();
    for (const item of value.models || []) {
      const option = document.createElement('option');
      option.value = item.id; option.textContent = item.name;
      option.selected = item.id === selected || (!selected && item.default);
      model.append(option);
    }
    if (!model.options.length) model.add(new Option(value.installed ? '登录后读取模型' : '安装后读取模型', ''));
    restoreSavedScope();
    const labels = {ready:'已登录 ChatGPT · 选择模型后测试真实请求', not_installed:'未找到 Codex 运行程序。请重新完整解压新版 HaloCue；也可安装官方 Codex CLI 后检查连接。', codex_login_required:'Codex 已就绪，请登录自己的 ChatGPT 账号。', codex_subscription_required:'当前认证方式不是 ChatGPT 订阅，无法启用。', quota_exhausted:'订阅额度已用完。等待恢复后再继续，不会转用 API。'};
    message(labels[value.state] || '暂时无法确认 Codex 连接状态。', value.state === 'quota_exhausted');
    panel.querySelector('[data-codex-action=login]').hidden = !!value.logged_in;
    panel.querySelector('[data-codex-action=logout]').hidden = !value.logged_in;
    panel.querySelector('[data-codex-install-link]').hidden = value.installed !== false;
    const quota = panel.querySelector('[data-codex-quota]');
    const windows = Object.values(value.limits?.rate_limits || {}).flatMap(bucket => [bucket.primary, bucket.secondary]).filter(window => window && typeof window.usedPercent === 'number' && Number.isFinite(window.usedPercent));
    quota.hidden = !value.logged_in;
    quota.textContent = windows.length ? windows.map(window => `${window.windowDurationMins ? window.windowDurationMins >= 1440 ? `${Math.round(window.windowDurationMins / 1440)} 天额度` : `${Math.round(window.windowDurationMins / 60)} 小时额度` : '订阅额度'} · 剩余 ${Math.max(0, Math.min(100, 100 - window.usedPercent)).toFixed(0)}%${window.resetsAt ? ` · ${new Date(window.resetsAt * 1000).toLocaleString()} 恢复` : ''}`).join('；') : value.state === 'quota_exhausted' ? '已停止模型调用。' : '服务尚未上报额度；不会猜测剩余次数或费用。';
    if (value.logged_in) {
      panel.querySelector('[data-codex-login-link]').hidden = true;
      if (poll) { clearInterval(poll); poll = null; }
    }
    controls();
  }
  async function run(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); }
    catch (error) { message(error.message, true); }
    finally { busy = false; controls(); }
  }
  async function refresh() { render((await request('codex')).connection); }
  panel.addEventListener('click', event => {
    const action = event.target.closest('[data-codex-action]')?.dataset.codexAction;
    if (!action) return;
    run(async () => {
      if (action === 'refresh') return refresh();
      if (action === 'logout') { render((await request('codex/logout', {})).connection); return; }
      const login = (await request('codex/login', {})).connection;
      const link = panel.querySelector('[data-codex-login-link]');
      const url = new URL(login.auth_url);
      if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com') throw new Error('登录地址不符合官方 OAuth 入口，请检查 Codex 版本。');
      link.href = url.href; link.hidden = false; link.focus();
      message('打开登录页面完成 ChatGPT 授权，随后会自动检查连接。');
      if (poll) clearInterval(poll);
      const stopAt = Date.now() + 5 * 60 * 1000;
      poll = setInterval(() => {
        if (Date.now() > stopAt) { clearInterval(poll); poll = null; return; }
        if (document.getElementById('settingsDialog')?.open && !busy) run(refresh);
      }, 2500);
    });
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    run(async () => {
      message('正在用订阅额度测试请求；AA 演出会校验实际输出格式，成功后才启用…');
      const scope = form.elements.scope.value;
      const config = {provider:'codex', model:model.value, timeout:Number(form.elements.timeout.value), base_url:'', api_key:'', api_key_env:'', subscription_only_acknowledged:true};
      if (scope === 'direction') {
        await request('direction-model:activate', config, true);
        if (typeof SettingsController !== 'undefined') await SettingsController.loadAll();
        message('Codex 已用于 AA 演出。额度用完时停止。'); return;
      }
      const result = await request('writing-model:activate', config);
      window.dispatchEvent(new CustomEvent('halocue:model-activated', {detail:result}));
      if (scope === 'both') {
        try { await request('writing-model:activate-direction', {expected_config_revision:result.model.config_revision}); }
        catch (error) {
          if (typeof SettingsController !== 'undefined') await SettingsController.loadAll();
          message(`写作已启用 Codex；演出未启用：${error.message}`, true); return;
        }
      }
      if (typeof SettingsController !== 'undefined') await SettingsController.loadAll();
      message(scope === 'both' ? 'Codex 已用于写作与 AA 演出。额度用完时停止。' : 'Codex 已用于写作。额度用完时停止。');
    });
  });
  form.addEventListener('input', event => {
    if (['model', 'timeout'].includes(event.target.name)) scopeDirty = true;
  });
  form.addEventListener('change', event => {
    if (event.target.name === 'scope') { scopeDirty = false; restoreSavedScope(); }
    controls();
  });
  panel.querySelector('[data-codex-path-form]').addEventListener('submit', event => {
    event.preventDefault();
    run(async () => render((await request('codex/configure', {cli_path:event.target.elements.cli_path.value.trim()})).connection));
  });
  const dialog = document.getElementById('settingsDialog');
  if (dialog) new MutationObserver(() => {
    if (dialog.open && !busy) { scopeDirty = false; run(refresh); }
    else if (!dialog.open && poll) { clearInterval(poll); poll = null; }
  }).observe(dialog, {attributes:true, attributeFilter:['open']});
  window.addEventListener('pagehide', () => { if (poll) clearInterval(poll); });
  window.addEventListener('halocue:connection-selected', event => {
    if (!scopeDirty && form.elements.scope.value !== 'direction') {
      savedModel = event.detail.model || savedModel;
      if (event.detail.timeout) form.elements.timeout.value = event.detail.timeout;
    }
    restoreSavedScope();
    if (event.detail.provider === 'codex' && !busy) run(refresh);
  });
  window.addEventListener('halocue:model-roles-loaded', restoreSavedScope);
})();
