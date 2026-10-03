'use strict';
const {ipcRenderer} = require('electron');
// Restore only appearance keys on our own loopback page, before its theme script runs.
// Existing origin preferences win; the cache also survives a busy-port fallback.
if (process.isMainFrame && location.protocol === 'http:' && location.hostname === '127.0.0.1') {
  try {
    const encoded = process.argv.find(arg => arg.startsWith('--halocue-appearance='));
    const saved = JSON.parse(decodeURIComponent(encoded.slice('--halocue-appearance='.length)));
    if (!localStorage.getItem('halocue.ui.theme') && ['system', 'light', 'dark'].includes(saved.preference)) {
      localStorage.setItem('halocue.ui.theme', saved.preference);
    }
    if (!localStorage.getItem('halocue.ui.appearance')) localStorage.setItem('halocue.ui.appearance', JSON.stringify(saved.appearance));
  } catch {}
}
// No general IPC, filesystem, shell, credentials or backend shutdown token is exposed to the page.
window.addEventListener('DOMContentLoaded', () => {
  if (!process.isMainFrame) return;
  document.documentElement.dataset.windowChrome = 'overlay';
  const topbar = document.querySelector('.hc-topbar');
  if (!topbar) return;
  if (document.body.classList.contains('app-loading')) ipcRenderer.send('halocue:workbench-loading');
  function hex(value, fallback) {
    if (/^#[0-9a-f]{6}$/i.test(value.trim())) return value.trim();
    const values = value.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return values ? '#'+values.slice(1, 4).map(v => Number(v).toString(16).padStart(2, '0')).join('') : fallback;
  }
  function refresh() {
    const style = getComputedStyle(topbar);
    const root = document.documentElement, palette = getComputedStyle(root);
    ipcRenderer.send('halocue:chrome', {color: hex(style.backgroundColor, '#ffffff'),
      symbolColor: hex(style.color, '#30343b'), height: Math.max(40, Math.min(100, Math.round(topbar.getBoundingClientRect().height)-1)),
      preference: root.dataset.themePreference, effective: root.dataset.theme,
      background: hex(getComputedStyle(document.getElementById('bootScreen') || document.body).backgroundColor, '#ffffff'),
      muted: hex(palette.getPropertyValue('--hc-muted'), '#7b818b'),
      line: hex(palette.getPropertyValue('--hc-line'), '#e7eaf0'),
      accent: hex(palette.getPropertyValue('--hc-accent'), '#2361de'),
      appearance: {palette: root.dataset.appearancePalette, contrast: root.dataset.appearanceContrast === 'high', scale: root.dataset.appearanceScale}});
    if (!document.body.classList.contains('app-loading')) ipcRenderer.send('halocue:workbench-ready');
  }
  const observer = new MutationObserver(refresh);
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-theme-preference', 'data-appearance-palette', 'data-appearance-contrast', 'data-appearance-scale', 'class', 'style']});
  observer.observe(document.body, {attributes: true, attributeFilter: ['class']});
  new ResizeObserver(refresh).observe(topbar);
  refresh();
});
