/* Apply local appearance preferences before first paint. No project data is changed. */
(() => {
  'use strict';

  const THEME_KEY = 'halocue.ui.theme';
  const APPEARANCE_KEY = 'halocue.ui.appearance';
  const themes = new Set(['system', 'light', 'dark']);
  const palettes = new Set(['azure', 'sakura', 'forest', 'amber']);
  const scales = new Set(['small', 'default', 'large']);
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const defaults = Object.freeze({ palette: 'azure', contrast: false, scale: 'default' });
  let theme = 'system';
  let appearance = { ...defaults };

  const safeRead = (key) => {
    try { return localStorage.getItem(key); } catch (_) { return null; }
  };
  const safeWrite = (key, value) => {
    try { localStorage.setItem(key, value); } catch (_) { /* Session-only when storage is unavailable. */ }
  };
  const normalizeAppearance = (value) => {
    if (!value || typeof value !== 'object') return { ...defaults };
    return {
      palette: palettes.has(value.palette) ? value.palette : defaults.palette,
      contrast: value.contrast === true,
      scale: scales.has(value.scale) ? value.scale : defaults.scale,
    };
  };
  const readAppearance = () => {
    try { return normalizeAppearance(JSON.parse(safeRead(APPEARANCE_KEY) || 'null')); }
    catch (_) { return { ...defaults }; }
  };
  const currentTheme = () => theme === 'system' ? (media.matches ? 'dark' : 'light') : theme;

  function updateControls() {
    document.querySelectorAll('button[data-theme-choice]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
    });
    document.querySelectorAll('button[data-appearance-palette]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.appearancePalette === appearance.palette));
    });
    document.querySelectorAll('button[data-appearance-scale]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.appearanceScale === appearance.scale));
    });
    const contrast = document.querySelector('button[data-appearance-contrast]');
    if (contrast) contrast.setAttribute('aria-pressed', String(appearance.contrast));
  }

  function apply() {
    const root = document.documentElement;
    root.dataset.theme = currentTheme();
    root.dataset.themePreference = theme;
    root.dataset.appearancePalette = appearance.palette;
    root.dataset.appearanceContrast = appearance.contrast ? 'high' : 'normal';
    root.dataset.appearanceScale = appearance.scale;
    root.style.colorScheme = currentTheme();
    updateControls();
  }

  function setTheme(value) {
    if (!themes.has(value)) return;
    theme = value;
    safeWrite(THEME_KEY, theme);
    apply();
  }
  function setAppearance(next) {
    appearance = normalizeAppearance({ ...appearance, ...next });
    safeWrite(APPEARANCE_KEY, JSON.stringify(appearance));
    apply();
  }

  const savedTheme = safeRead(THEME_KEY);
  if (themes.has(savedTheme)) theme = savedTheme;
  appearance = readAppearance();
  apply();

  document.addEventListener('DOMContentLoaded', apply, { once: true });
  document.addEventListener('click', (event) => {
    const themeChoice = event.target.closest?.('button[data-theme-choice]');
    if (themeChoice) { setTheme(themeChoice.dataset.themeChoice); return; }
    const paletteChoice = event.target.closest?.('button[data-appearance-palette]');
    if (paletteChoice) { setAppearance({ palette: paletteChoice.dataset.appearancePalette }); return; }
    const scaleChoice = event.target.closest?.('button[data-appearance-scale]');
    if (scaleChoice) { setAppearance({ scale: scaleChoice.dataset.appearanceScale }); return; }
    const contrast = event.target.closest?.('button[data-appearance-contrast]');
    if (contrast) setAppearance({ contrast: !appearance.contrast });
  });
  media.addEventListener('change', () => { if (theme === 'system') apply(); });
  window.addEventListener('storage', (event) => {
    if (event.key === THEME_KEY || event.key === null) theme = themes.has(event.newValue) ? event.newValue : 'system';
    if (event.key === APPEARANCE_KEY || event.key === null) appearance = readAppearance();
    if (event.key === THEME_KEY || event.key === APPEARANCE_KEY || event.key === null) apply();
  });
})();
