'use strict';
const {app, BrowserWindow, Menu, ipcMain, dialog, shell, screen, nativeTheme} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {waitForReady, stopOwnedService, sameOrigin, validBounds, availablePort, resolveUserRoot, allowPermission, startupAppearance, captureTestPage} = require('./runtime.cjs');
const {version} = require('./package.json');

const started = performance.now();
const userRoot = resolveUserRoot(process.env, app.getPath('home'));
fs.mkdirSync(path.join(userRoot, 'electron'), {recursive: true});
app.setPath('userData', path.join(userRoot, 'electron'));
app.setAppUserModelId('org.halocue.desktop');
const executableRoot = app.isPackaged ? path.dirname(process.execPath) : path.resolve(__dirname, '../../..');
const backend = app.isPackaged ? path.join(executableRoot, 'HaloCueBackend.exe') : process.env.HALOCUE_BACKEND_EXE;
const rawArgs = process.argv.slice(app.isPackaged ? 1 : 2);
const selfTest = rawArgs.includes('--self-test') && Boolean(process.env.HALOCUE_USER_DATA_DIR);
const args = rawArgs.filter(arg => arg !== '--self-test');
let window, child, receipt, quitting = false, failure = false, origin, ownedReadyFile;
const abort = new AbortController();
const metrics = {version, host: 'electron', electron: process.versions.electron};
const stateDir = app.getPath('userData');
let bootURL, bootEvidence, currentAppearance, restorationCapture;
const appearanceFile = path.join(stateDir, 'appearance.json');

function record(stage, extra = {}) {
  metrics[stage] = Math.round(performance.now() - started);
  Object.assign(metrics, extra);
  fs.mkdirSync(stateDir, {recursive: true});
  const target = path.join(stateDir, 'startup.json');
  fs.writeFileSync(`${target}.tmp`, JSON.stringify(metrics, null, 2));
  fs.renameSync(`${target}.tmp`, target);
}

async function fail(error) {
  if (quitting || failure) return;
  failure = true;
  try {record('failed_ms', {error: error.message});} catch {}
  if (selfTest) {app.quit(); return;}
  if (window && !window.isDestroyed()) {
    await dialog.showMessageBox(window, {type: 'error', title: 'HaloCue 启动失败',
      message: '工作台服务未能启动。', detail: '请保留用户数据并重新启动。启动记录在用户目录的 electron/startup.json。'});
  }
  app.quit();
}

function launchBackend(arguments_) {
  if (!backend || !fs.existsSync(backend)) throw new Error('Bundled backend executable is missing');
  const owned = spawn(backend, arguments_, {cwd: executableRoot, windowsHide: true,
    env: {...process.env, HALOCUE_USER_DATA_DIR: userRoot}, stdio: ['ignore', 'pipe', 'pipe']});
  // Drain pipes without putting paths, manuscript contents or credentials in shell logs.
  owned.stdout.on('data', () => {});
  owned.stderr.on('data', () => {});
  return owned;
}

// Preserve backend diagnostics/headless acceptance flags for the portable entry.
const diagnostic = ['--no-browser', '--legacy-ui', '--check', '--check-update', '--download-update', '--migration-status']
  .some(flag => args.includes(flag));
if (diagnostic) {
  try {
    child = launchBackend(args);
    child.stdout.on('data', data => process.stdout?.write(data));
    child.stderr.on('data', data => process.stderr?.write(data));
    child.on('error', () => app.exit(1));
    child.on('exit', code => app.exit(code ?? 1));
  } catch { app.exit(1); }
} else if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) {if (window.isMinimized()) window.restore(); window.show(); window.focus();}
  });
  app.on('before-quit', event => {
    if (quitting) return;
    event.preventDefault();
    // A renderer with unfinished edits can cancel close through beforeunload.
    if (window && !window.isDestroyed()) window.close();
    else shutdown();
  });
  app.on('window-all-closed', shutdown);
  async function shutdown() {
    if (quitting) return;
    quitting = true; abort.abort();
    await stopOwnedService(child, receipt);
    if (ownedReadyFile) fs.rmSync(ownedReadyFile, {force: true});
    if (receipt) fs.rmSync(path.join(stateDir, `ready-${child.pid}.json`), {force: true});
    if (selfTest && failure) app.exit(1);
    else app.quit();
  }
  app.whenReady().then(async () => {
    record('electron_ready_ms');
    Menu.setApplicationMenu(null);
    let saved = {};
    try {saved = JSON.parse(fs.readFileSync(path.join(stateDir, 'window.json'), 'utf8'));} catch {}
    let savedAppearance;
    try {savedAppearance = JSON.parse(fs.readFileSync(appearanceFile, 'utf8'));} catch {}
    currentAppearance = startupAppearance(savedAppearance, nativeTheme.shouldUseDarkColors);
    const boot = pathToFileURL(path.join(__dirname, 'boot.html'));
    for (const [key, value] of Object.entries(currentAppearance)) if (typeof value === 'string') boot.searchParams.set(key, value);
    bootURL = boot.href;
    let bounds = validBounds(saved.bounds) ? saved.bounds : {width: 1360, height: 860};
    if (bounds.x !== undefined && !screen.getAllDisplays().some(display => {
      const a = display.workArea;
      return bounds.x < a.x+a.width && bounds.y < a.y+a.height && bounds.x+bounds.width > a.x && bounds.y+bounds.height > a.y;
    })) bounds = {width: 1360, height: 860};
    window = new BrowserWindow({...bounds, minWidth: 960, minHeight: 640,
      title: `HaloCue ${version}`, show: false, backgroundColor: currentAppearance.background,
      icon: path.join(executableRoot, 'branding', 'halocue.ico'),
      titleBarStyle: 'hidden', titleBarOverlay: {color: currentAppearance.color, symbolColor: currentAppearance.symbolColor, height: 55},
      webPreferences: {preload: path.join(__dirname, 'preload.cjs'),
        additionalArguments: ['--halocue-appearance='+encodeURIComponent(JSON.stringify(currentAppearance))],
        nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true,
        backgroundThrottling: !selfTest},
    });
    window.on('close', () => {
      if (!window.isDestroyed()) {
        fs.writeFileSync(path.join(stateDir, 'window.json'), JSON.stringify({bounds: window.getNormalBounds(), maximized: window.isMaximized()}));
      }
    });
    window.once('closed', () => {window = undefined; shutdown();});
    window.webContents.on('will-prevent-unload', async event => {
      const result = await dialog.showMessageBox(window, {type: 'question', buttons: ['继续编辑', '关闭'],
        defaultId: 0, cancelId: 0, message: '仍有未完成的编辑，要关闭工作台吗？'});
      // The prevented close has already been cancelled; retry after an explicit choice.
      // Explicit confirmation bypasses beforeunload; the closed handler still owns
      // shutdown and receipt cleanup, exactly as for a normal close.
      if (result.response === 1 && window && !window.isDestroyed()) window.destroy();
    });
    const trusted = url => url === bootURL || Boolean(origin && sameOrigin(url, origin));
    window.webContents.on('will-navigate', (event, url) => {if (!trusted(url)) event.preventDefault();});
    window.webContents.on('will-redirect', (event, url) => {if (!trusted(url)) event.preventDefault();});
    window.webContents.setWindowOpenHandler(({url}) => {
      try {if (new URL(url).protocol === 'https:') shell.openExternal(url).catch(() => {});} catch {}
      return {action: 'deny'};
    });
    window.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
      callback(contents === window?.webContents && allowPermission(permission, details.requestingUrl, origin, details.isMainFrame));
    });
    window.webContents.session.setPermissionCheckHandler((contents, permission, requestingOrigin, details) =>
      contents === window?.webContents && allowPermission(permission, details.requestingUrl || requestingOrigin, origin, details.isMainFrame));
    ipcMain.on('halocue:chrome', (event, theme) => {
      if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || !trusted(event.senderFrame.url)) return;
      if (!theme || !/^#[0-9a-f]{6}$/i.test(theme.color) || !/^#[0-9a-f]{6}$/i.test(theme.symbolColor) ||
          !Number.isInteger(theme.height) || theme.height < 40 || theme.height > 100) return;
      window.setTitleBarOverlay({color: theme.color, symbolColor: theme.symbolColor, height: theme.height});
      if (!origin || !sameOrigin(event.senderFrame.url, origin)) return;
      const normalized = startupAppearance(theme, nativeTheme.shouldUseDarkColors);
      const serialized = JSON.stringify(normalized);
      if (serialized !== JSON.stringify(currentAppearance)) {
        currentAppearance = normalized;
        fs.writeFileSync(appearanceFile+'.tmp', serialized);
        fs.renameSync(appearanceFile+'.tmp', appearanceFile);
      }
    });
    ipcMain.on('halocue:workbench-ready', event => {
      if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || !origin || !sameOrigin(event.senderFrame.url, origin)) return;
      if (!metrics.workbench_ready_ms) {
        record('workbench_ready_ms');
        if (selfTest) runWindowSelfTest().catch(fail);
      }
    });
    ipcMain.on('halocue:workbench-loading', event => {
      if (!selfTest || restorationCapture || !window || event.sender !== window.webContents ||
          event.senderFrame !== window.webContents.mainFrame || !origin || !sameOrigin(event.senderFrame.url, origin)) return;
      restorationCapture = (async () => {
        await new Promise(resolve => setTimeout(resolve, 200));
        const result = await window.webContents.executeJavaScript(`(() => {
          const boot=document.querySelector('#bootScreen'), header=boot.querySelector('.boot-header');
          const icon=boot.querySelector('main > img');
          return {loading:document.body.classList.contains('app-loading'), visible:!boot.hidden,
            theme:document.documentElement.dataset.theme, title:boot.querySelector('h1').textContent,
            icon:icon.getAttribute('src'), iconLoaded:icon.complete && icon.naturalWidth>0,
            iconWidth:icon.getBoundingClientRect().width, titleSize:getComputedStyle(boot.querySelector('h1')).fontSize,
            background:getComputedStyle(boot).backgroundColor,
            header:getComputedStyle(header).backgroundColor, headerHeight:header.getBoundingClientRect().height};
        })()`);
        fs.writeFileSync(path.join(stateDir, 'restoration-self-test.json'), JSON.stringify(result, null, 2));
        fs.writeFileSync(path.join(stateDir, 'restoring.png'), (await captureTestPage(window.webContents)).toPNG());
        if (!result.loading || !result.visible || result.title !== '正在打开工作台' || !result.icon.startsWith('/halocue-icon.svg') ||
            !result.iconLoaded || result.iconWidth !== 72 || result.titleSize !== '21px' || result.headerHeight !== 56 ||
            result.theme !== bootEvidence.theme || result.background !== bootEvidence.background || result.header !== bootEvidence.header) {
          throw new Error('Restoration screen is not the unified startup view');
        }
        return result;
      })();
      restorationCapture.catch(fail);
    });
    window.once('ready-to-show', () => {
      if (window && !quitting) {window.show(); if (saved.maximized) window.maximize(); record('window_shown_ms');}
    });
    const bootLoaded = window.loadURL(bootURL).then(async () => {
      if (selfTest && window) {
        if (!window.isVisible()) await new Promise(resolve => window.once('show', resolve));
        // Capture only after the visible boot page has reached the compositor.
        await new Promise(resolve => setTimeout(resolve, 200));
        bootEvidence = await window.webContents.executeJavaScript("({theme:document.documentElement.dataset.theme, background:getComputedStyle(document.body).backgroundColor, header:getComputedStyle(document.querySelector('header')).backgroundColor})");
        fs.writeFileSync(path.join(stateDir, 'boot.png'), (await captureTestPage(window.webContents)).toPNG());
      }
    });
    const readyFile = path.join(stateDir, `ready-${randomUUID()}.json`);
    ownedReadyFile = readyFile;
    let preferredPort = 8770;
    try {preferredPort = Number(fs.readFileSync(path.join(stateDir, 'port.txt'), 'utf8')) || 8770;} catch {}
    const port = await availablePort(preferredPort >= 1 && preferredPort <= 65535 ? preferredPort : 8770);
    if (quitting) return;
    child = launchBackend(['--no-browser', '--port', String(port), '--ready-file', readyFile, ...args]);
    record('backend_spawned_ms');
    child.on('error', fail);
    child.on('exit', () => {if (!quitting) fail(new Error('Local service stopped unexpectedly'));});
    try {
      receipt = await waitForReady(child, readyFile, version, abort.signal);
      // Use a PID-named owned receipt for predictable cleanup; remove the random startup receipt.
      fs.renameSync(readyFile, path.join(stateDir, `ready-${child.pid}.json`));
      ownedReadyFile = path.join(stateDir, `ready-${child.pid}.json`);
      fs.writeFileSync(path.join(stateDir, 'port.txt'), String(receipt.port));
      origin = receipt.url; record('backend_ready_ms');
      await bootLoaded;
      if (selfTest) {
        // Isolated QA holds works loading so the intermediate UI cannot escape review.
        window.webContents.session.webRequest.onBeforeRequest({urls: [origin+'/api/v1/works']}, (_details, callback) => {
          setTimeout(() => callback({}), 1000);
        });
      }
      if (!quitting && window) {await window.loadURL(origin); record('page_loaded_ms');}
    } finally {fs.rmSync(readyFile, {force: true});}
  }).catch(fail);

  async function runWindowSelfTest() {
    // Optional isolated release acceptance: real native APIs, never user documents.
    if (!restorationCapture) throw new Error('Restoration phase was not captured');
    const result = {boot: bootEvidence, restoration: await restorationCapture, nativeHandle: window.getNativeWindowHandle().length > 0,
      packaged: app.isPackaged, title: window.getTitle(), preferences: window.webContents.getLastWebPreferences()};
    const changed = (name, action) => new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`Window self-test: ${name} timeout`)), 3000);
      window.once(name, () => {clearTimeout(timeout); resolve();}); action();
    });
    if (window.isMinimized()) await changed('restore', () => window.restore());
    window.show();
    window.focus();
    if (window.isMaximized()) await changed('unmaximize', () => window.unmaximize());
    await changed('minimize', () => window.minimize()); result.minimized = window.isMinimized();
    await changed('restore', () => window.restore()); result.restored = !window.isMinimized();
    await changed('maximize', () => window.maximize()); result.maximized = window.isMaximized();
    await changed('unmaximize', () => window.unmaximize()); result.unmaximized = !window.isMaximized();
    result.bounds = window.getBounds();
    result.backendPid = child.pid;
    result.clipboardWritePermission = await window.webContents.executeJavaScript(
      "navigator.permissions.query({name:'clipboard-write'}).then(result=>result.state)");
    if (result.clipboardWritePermission !== 'granted') throw new Error('MCP configuration copy permission is unavailable');
    // Renderer snapshot excludes the operating system's overlay caption controls.
    const snapshot = await captureTestPage(window.webContents);
    fs.writeFileSync(path.join(stateDir, 'workbench.png'), snapshot.toPNG());
    const layout = () => window.webContents.executeJavaScript(`(() => {
      const root=document.documentElement, bar=document.querySelector('.hc-topbar');
      const area=navigator.windowControlsOverlay.getTitlebarAreaRect();
      const buttons=[...bar.querySelectorAll('button')].map(button=>({label:button.getAttribute('aria-label')||button.textContent.trim(), rect:button.getBoundingClientRect().toJSON(), region:getComputedStyle(button).webkitAppRegion})).filter(button=>button.rect.width>0);
      return {theme:root.dataset.theme, preference:root.dataset.themePreference, width:innerWidth, height:innerHeight,
        horizontalOverflow:document.body.scrollWidth>innerWidth, overlay:navigator.windowControlsOverlay.visible,
        titleArea:area.toJSON(), header:bar.getBoundingClientRect().toJSON(), drag:getComputedStyle(bar).webkitAppRegion,
        buttons, background:getComputedStyle(document.body).backgroundColor};
    })()`);
    result.regular = await layout();
    const originalBounds = window.getBounds();
    window.setSize(960, 640);
    await new Promise(resolve => setTimeout(resolve, 150));
    result.narrow = await layout();
    fs.writeFileSync(path.join(stateDir, 'workbench-narrow.png'), (await captureTestPage(window.webContents)).toPNG());
    window.setBounds(originalBounds);
    fs.writeFileSync(path.join(stateDir, 'window-self-test.json'), JSON.stringify(result, null, 2));
    app.quit();
  }
}
