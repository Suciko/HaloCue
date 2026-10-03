'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const vm = require('node:vm');
const {validateReady, waitForReady, stopOwnedService, sameOrigin, availablePort, resolveUserRoot, allowPermission, startupAppearance} = require('../runtime.cjs');
const receipt = {app_id: 'halocue-local-server-v1', version: '1.0.0-test', pid: 123,
  host: '127.0.0.1', port: 12345, url: 'http://127.0.0.1:12345', shutdown_token: 'test-'.repeat(8), interface: 'integrated'};

test('readiness rejects stale PID/version, foreign URL and missing shutdown authority', () => {
  assert.equal(validateReady(receipt, 123, receipt.version).url, receipt.url);
  for (const patch of [{pid: 124}, {version: 'stale'}, {url: 'http://example.com:12345'},
    {url: 'http://127.0.0.1:12345/path'}, {port: 12346}, {shutdown_token: ''}]) {
    assert.throws(() => validateReady({...receipt, ...patch}, 123, receipt.version));
  }
  assert.ok(sameOrigin(receipt.url+'/production/', receipt.url));
  assert.ok(!sameOrigin('http://127.0.0.1:12346', receipt.url));
});

test('user data follows the backend custom and redirected local directory rules', () => {
  const local = path.join(os.tmpdir(), 'halocue-redirected');
  assert.equal(resolveUserRoot({LOCALAPPDATA: local}, os.homedir()), path.join(local, 'HaloCue'));
  assert.equal(resolveUserRoot({HALOCUE_USER_DATA_DIR: '~/fixture'}, os.homedir()), path.join(os.homedir(), 'fixture'));
  assert.equal(resolveUserRoot({HALOCUE_USER_DATA_DIR: local, LOCALAPPDATA: 'unused'}, os.homedir()), local);
});

test('startup restores manual theme and follows current system instead of stale effective theme', () => {
  assert.equal(startupAppearance({preference: 'dark'}, false).effective, 'dark');
  assert.equal(startupAppearance({preference: 'light'}, true).effective, 'light');
  assert.equal(startupAppearance({preference: 'system', effective: 'dark', background: '#112233'}, false).background, '#ffffff');
  assert.equal(startupAppearance({preference: 'system'}, true).effective, 'dark');
  assert.equal(startupAppearance({preference: 'light', effective: 'light', background: '#fbfaf6'}, false).background, '#ffffff');
  const saved = {preference: 'dark', effective: 'dark', color: '#123456', background: 'url(file:private)', appearance: {palette: 'sakura', contrast: true, scale: 'large'}};
  const restored = startupAppearance(saved, false);
  assert.equal(restored.color, '#123456'); assert.equal(restored.background, '#191e27');
  assert.deepEqual(restored.appearance, saved.appearance);
  assert.equal(startupAppearance(null, false).preference, 'system');
});

test('only trusted main-frame text copy is permitted; read and unrelated permissions stay denied', () => {
  assert.ok(allowPermission('clipboard-sanitized-write', receipt.url+'/settings', receipt.url, true));
  for (const permission of ['clipboard-read', 'fileSystem', 'media', 'notifications']) {
    assert.ok(!allowPermission(permission, receipt.url, receipt.url, true));
  }
  assert.ok(!allowPermission('clipboard-sanitized-write', receipt.url, receipt.url, false));
  assert.ok(!allowPermission('clipboard-sanitized-write', 'https://example.com', receipt.url, true));
});

test('startup abort and timeout leave no unbounded polling', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'halocue-host-test-'));
  try {
    const child = {pid: 123, exitCode: null, signalCode: null};
    await assert.rejects(waitForReady(child, path.join(directory, 'absent'), receipt.version, new AbortController().signal, 10), /timed out/);
    const abort = new AbortController(); abort.abort();
    await assert.rejects(waitForReady(child, path.join(directory, 'absent'), receipt.version, abort.signal), /cancelled/);
    await fs.writeFile(path.join(directory, 'ready'), JSON.stringify({...receipt, pid: 999}));
    await assert.rejects(waitForReady(child, path.join(directory, 'ready'), receipt.version, new AbortController().signal), /Invalid/);
  } finally {await fs.rm(directory, {recursive: true});}
});

test('shutdown authenticates the owned endpoint and leaves an unrelated child alive', async () => {
  const child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)']);
  const unrelated = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)']);
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/integration/runtime/stop');
    assert.equal(request.headers['x-halocue-shutdown'], receipt.shutdown_token);
    response.end('{}'); child.kill();
  });
  try {
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    await stopOwnedService(child, {...receipt, url: `http://127.0.0.1:${server.address().port}`});
    assert.ok(child.exitCode !== null || child.signalCode !== null);
    assert.equal(unrelated.exitCode, null); assert.equal(unrelated.signalCode, null);
    assert.notEqual(await availablePort(server.address().port), server.address().port);
  } finally {child.kill(); unrelated.kill(); server.close();}
});

test('offline feedback does not prevent the editor from opening', async () => {
  const source = await fs.readFile(path.resolve(__dirname, '../../../../services/halocue/writing/web/app.js'), 'utf8');
  const code = source.slice(source.indexOf('async function boot(){'), source.indexOf('function isCompactViewport(){'));
  const calls = []; let opened = false;
  const sandbox = {state: {}, hcArray: value => value, hcInitialParams: new URLSearchParams(),
    hcHistoryReady: false, hcHistoryIndex: 0, history: {state: {}, replaceState(){}}, location: {href: 'http://local/'},
    parseAppRoute: () => ({}), navigateRoute: () => {opened = true;}, render(){}, toast(){}, loadWork: async () => {},
    document: {body: {classList: {remove(){}}}, getElementById: () => ({setAttribute(){}})},
    api: route => {calls.push(route); return route.includes('feedback') ? new Promise(()=>{}) : Promise.resolve(route === '/works' ? [] : {});},
  };
  vm.createContext(sandbox); vm.runInContext(code, sandbox);
  await Promise.race([sandbox.boot(), new Promise((_, reject) => setTimeout(()=>reject(new Error('Editor blocked on feedback')), 500))]);
  assert.ok(opened); assert.deepEqual(calls, ['/capabilities', '/works', '/settings/feedback/sync']);
});
