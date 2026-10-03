'use strict';
const fs = require('node:fs/promises');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');

function validateReady(value, pid, version) {
  const url = new URL(value.url);
  if (value.app_id !== 'halocue-local-server-v1' || value.pid !== pid || value.version !== version ||
      value.host !== '127.0.0.1' || url.protocol !== 'http:' || url.hostname !== '127.0.0.1' ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash ||
      !Number.isInteger(value.port) || value.port < 1 || value.port > 65535 ||
      Number(url.port) !== value.port || typeof value.shutdown_token !== 'string' ||
      value.shutdown_token.length < 32 || value.interface !== 'integrated') {
    throw new Error('Invalid local service readiness receipt');
  }
  return {...value, url: url.origin};
}

async function waitForReady(child, readyFile, version, signal, timeoutMs = 120000) {
  const started = Date.now();
  while (!signal.aborted) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error('Local service exited before startup');
    try {
      const value = JSON.parse(await fs.readFile(readyFile, 'utf8'));
      return validateReady(value, child.pid, version);
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    }
    if (Date.now() - started > timeoutMs) throw new Error('Local service startup timed out');
    await delay(50, undefined, {signal});
  }
  throw new Error('Startup cancelled');
}

function requestStop(receipt) {
  return new Promise((resolve, reject) => {
    const request = http.request(`${receipt.url}/integration/runtime/stop`, {
      method: 'POST', timeout: 5000,
      headers: {'Content-Type': 'application/json', 'X-HaloCue-Shutdown': receipt.shutdown_token},
    }, response => {
      response.resume();
      response.on('end', () => response.statusCode === 200 ? resolve() : reject(new Error('Service shutdown rejected')));
    });
    request.on('timeout', () => request.destroy(new Error('Service shutdown timed out')));
    request.on('error', reject);
    request.end('{}');
  });
}

async function stopOwnedService(child, receipt) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  if (receipt) await requestStop(receipt).catch(() => {});
  const end = Date.now() + (receipt ? 15000 : 1000);
  while (child.exitCode === null && child.signalCode === null && Date.now() < end) await delay(50);
  if (child.exitCode === null && child.signalCode === null) {
    // ChildProcess retains the owned process handle; never enumerate/kill other HaloCue instances.
    child.kill();
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), delay(3000)]);
  }
}

function sameOrigin(candidate, origin) {
  try { return new URL(candidate).origin === origin; } catch { return false; }
}

function validBounds(value) {
  return value && ['x', 'y', 'width', 'height'].every(key => Number.isInteger(value[key])) &&
    value.width >= 960 && value.height >= 640 && value.width <= 10000 && value.height <= 10000;
}

function availablePort(preferred) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', error => {
      if (error.code === 'EADDRINUSE' && preferred !== 0) availablePort(0).then(resolve, reject);
      else reject(error);
    });
    server.listen(preferred, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

function resolveUserRoot(env, home) {
  const explicit = (env.HALOCUE_USER_DATA_DIR || '').trim();
  if (explicit) return path.resolve(explicit.replace(/^~(?=$|[/\\])/, home));
  return path.resolve(env.LOCALAPPDATA?.trim() || path.join(home, 'AppData', 'Local'), 'HaloCue');
}

function allowPermission(permission, requestingURL, origin, isMainFrame) {
  return permission === 'clipboard-sanitized-write' && isMainFrame === true &&
    Boolean(origin) && sameOrigin(requestingURL, origin);
}

function startupAppearance(saved, systemDark) {
  const preference = ['light', 'dark', 'system'].includes(saved?.preference) ? saved.preference : 'system';
  const effective = preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
  const colors = effective === 'dark'
    ? {background: '#191e27', color: '#222a35', symbolColor: '#e1e7ee', muted: '#a1adbc', line: '#343e4c', accent: '#85afea'}
    : {background: '#ffffff', color: '#ffffff', symbolColor: '#30343b', muted: '#7b818b', line: '#e7eaf0', accent: '#2361de'};
  if (saved?.effective === effective) {
    // The legacy body can be cream behind the full-size workbench. It is not
    // the startup canvas; both boot phases use the canonical light/dark canvas.
    for (const key of Object.keys(colors)) if (key !== 'background' && /^#[0-9a-f]{6}$/i.test(saved[key])) colors[key] = saved[key];
  }
  const appearance = {palette: ['azure', 'sakura', 'forest', 'amber'].includes(saved?.appearance?.palette) ? saved.appearance.palette : 'azure',
    contrast: saved?.appearance?.contrast === true,
    scale: ['small', 'default', 'large'].includes(saved?.appearance?.scale) ? saved.appearance.scale : 'default'};
  return {preference, effective, ...colors, appearance};
}

module.exports = {validateReady, waitForReady, requestStop, stopOwnedService, sameOrigin, validBounds,
  availablePort, resolveUserRoot, allowPermission, startupAppearance};
