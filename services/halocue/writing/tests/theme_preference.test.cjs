const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/theme.js'), 'utf8');

function element(dataset = {}) {
  return {
    dataset,
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
  };
}

function boot({ savedTheme = null, savedAppearance = null, dark = false, blocked = false } = {}) {
  const documentEvents = {}, windowEvents = {}, mediaEvents = {};
  const controls = {
    themes: ['system', 'light', 'dark'].map(themeChoice => element({ themeChoice })),
    palettes: ['azure', 'sakura', 'forest', 'amber'].map(appearancePalette => element({ appearancePalette })),
    scales: ['small', 'default', 'large'].map(appearanceScale => element({ appearanceScale })),
    contrast: element({ appearanceContrast: '' }),
  };
  const root = { dataset: {}, style: {} };
  const media = { matches: dark, addEventListener: (name, fn) => { mediaEvents[name] = fn; } };
  const storage = {
    values: { 'halocue.ui.theme': savedTheme, 'halocue.ui.appearance': savedAppearance },
    getItem(key) { if (blocked) throw Error('blocked'); return this.values[key] ?? null; },
    setItem(key, value) { if (blocked) throw Error('blocked'); this.values[key] = value; },
  };
  const document = {
    documentElement: root,
    querySelectorAll(selector) {
      if (selector === 'button[data-theme-choice]') return controls.themes;
      if (selector === 'button[data-appearance-palette]') return controls.palettes;
      if (selector === 'button[data-appearance-scale]') return controls.scales;
      return [];
    },
    querySelector(selector) { return selector === 'button[data-appearance-contrast]' ? controls.contrast : null; },
    addEventListener(name, fn) { documentEvents[name] = fn; },
  };
  vm.runInNewContext(source, {
    window: { matchMedia: () => media, addEventListener: (name, fn) => { windowEvents[name] = fn; } },
    localStorage: storage,
    document,
  });
  const targetFor = (selector, item) => ({ closest: query => query === selector ? item : null });
  return {
    root, controls, storage,
    ready: () => documentEvents.DOMContentLoaded(),
    chooseTheme: value => documentEvents.click({ target: targetFor('button[data-theme-choice]', controls.themes.find(item => item.dataset.themeChoice === value)) }),
    choosePalette: value => documentEvents.click({ target: targetFor('button[data-appearance-palette]', controls.palettes.find(item => item.dataset.appearancePalette === value)) }),
    chooseScale: value => documentEvents.click({ target: targetFor('button[data-appearance-scale]', controls.scales.find(item => item.dataset.appearanceScale === value)) }),
    toggleContrast: () => documentEvents.click({ target: targetFor('button[data-appearance-contrast]', controls.contrast) }),
    system: value => { media.matches = value; mediaEvents.change(); },
    sync: (key, value) => { storage.values[key] = value; windowEvents.storage({ key, newValue: value }); },
  };
}

test('first paint follows system and marks the active appearance controls', () => {
  const page = boot({ dark: true });
  assert.equal(page.root.dataset.theme, 'dark');
  assert.equal(page.root.dataset.themePreference, 'system');
  assert.equal(page.controls.themes[0].attributes['aria-pressed'], 'true');
  assert.equal(page.controls.palettes[0].attributes['aria-pressed'], 'true');
  assert.equal(page.controls.scales[1].attributes['aria-pressed'], 'true');
  page.system(false);
  assert.equal(page.root.dataset.theme, 'light');
});

test('explicit mode, palette, contrast, and scale persist locally', () => {
  const page = boot();
  page.chooseTheme('dark');
  page.choosePalette('forest');
  page.toggleContrast();
  page.chooseScale('large');
  assert.equal(page.root.dataset.theme, 'dark');
  assert.equal(page.root.dataset.appearancePalette, 'forest');
  assert.equal(page.root.dataset.appearanceContrast, 'high');
  assert.equal(page.root.dataset.appearanceScale, 'large');
  assert.equal(page.controls.contrast.attributes['aria-pressed'], 'true');
  assert.deepEqual(JSON.parse(page.storage.values['halocue.ui.appearance']), { palette: 'forest', contrast: true, scale: 'large' });
  const reloaded = boot({ savedTheme: page.storage.values['halocue.ui.theme'], savedAppearance: page.storage.values['halocue.ui.appearance'] });
  assert.equal(reloaded.root.dataset.theme, 'dark');
  assert.equal(reloaded.root.dataset.appearancePalette, 'forest');
  assert.equal(reloaded.root.dataset.appearanceContrast, 'high');
  assert.equal(reloaded.root.dataset.appearanceScale, 'large');
});

test('invalid persisted values and blocked storage safely use defaults', () => {
  const invalid = boot({ savedTheme: 'midnight', savedAppearance: '{"palette":"unknown","contrast":"yes","scale":"giant"}', dark: true });
  assert.equal(invalid.root.dataset.theme, 'dark');
  assert.equal(invalid.root.dataset.appearancePalette, 'azure');
  assert.equal(invalid.root.dataset.appearanceContrast, 'normal');
  assert.equal(invalid.root.dataset.appearanceScale, 'default');
  const blocked = boot({ blocked: true });
  blocked.chooseTheme('dark');
  blocked.choosePalette('amber');
  assert.equal(blocked.root.dataset.theme, 'dark');
  assert.equal(blocked.root.dataset.appearancePalette, 'amber');
});

test('storage synchronization updates the existing window', () => {
  const page = boot({ dark: false });
  page.sync('halocue.ui.theme', 'dark');
  page.sync('halocue.ui.appearance', JSON.stringify({ palette: 'sakura', contrast: true, scale: 'small' }));
  assert.equal(page.root.dataset.theme, 'dark');
  assert.equal(page.root.dataset.appearancePalette, 'sakura');
  assert.equal(page.root.dataset.appearanceContrast, 'high');
  assert.equal(page.root.dataset.appearanceScale, 'small');
  page.sync('halocue.ui.theme', null);
  assert.equal(page.root.dataset.theme, 'light');
  assert.equal(page.root.dataset.themePreference, 'system');
});


test('provider hover uses the same theme surface token as its dialog', () => {
  const styles = fs.readFileSync(path.join(__dirname, '../web/settings-center.css'), 'utf8');
  const hover = styles.match(/#settingsDialog \.vendor-card:hover\s*\{([^}]+)\}/)?.[1];
  assert(hover, 'provider hover rule must exist');
  assert.match(hover, /background:\s*var\(--hc-surface\)/);
  assert.doesNotMatch(hover, /background:\s*(?:#fff(?:fff)?|white)\b/i);
});
