'use strict';
// Parser-blocking local script sets the saved appearance before the first paint.
const parameters = new URLSearchParams(location.search);
const theme = parameters.get('effective');
if (theme === 'dark' || theme === 'light') {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}
for (const key of ['background', 'color', 'symbolColor', 'muted', 'line', 'accent']) {
  const value = parameters.get(key);
  if (/^#[0-9a-f]{6}$/i.test(value)) document.documentElement.style.setProperty('--'+key, value);
}
