'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const {packager} = require('@electron/packager');
const {version} = require('./package.json');

async function pack(source, backend, output) {
  source = path.resolve(source); backend = path.resolve(backend); output = path.resolve(output);
  await fs.mkdir(output, {recursive: true});
  const stage = path.join(output, 'electron-source');
  await fs.mkdir(stage, {recursive: false});
  const host = path.join(source, 'apps/desktop-client/electron');
  for (const name of ['main.cjs', 'preload.cjs', 'runtime.cjs', 'boot.html', 'boot.js', 'icon.svg']) {
    await fs.copyFile(path.join(host, name), path.join(stage, name));
  }
  // Runtime asar has no build/test dependencies or machine-local metadata.
  await fs.writeFile(path.join(stage, 'package.json'), JSON.stringify({name: 'halocue-desktop', version,
    main: 'main.cjs', description: 'HaloCue', license: 'MIT', author: 'HaloCue contributors'}, null, 2)+'\n');
  const [built] = await packager({dir: stage, out: output, name: 'HaloCue', platform: 'win32', arch: 'x64',
    electronVersion: '44.5.1', appVersion: version, buildVersion: version,
    icon: path.join(source, 'branding/halocue.ico'), asar: true, prune: true, overwrite: false,
    win32metadata: {CompanyName: 'HaloCue contributors', ProductName: 'HaloCue',
      FileDescription: 'HaloCue Electron desktop', OriginalFilename: 'HaloCue.exe'},
  });
  const target = path.join(output, 'HaloCue');
  await fs.rename(built, target);
  await fs.rename(path.join(target, 'LICENSE'), path.join(target, 'LICENSE.electron.txt'));
  await fs.cp(backend, target, {recursive: true, filter: file => path.basename(file) !== 'HaloCue.exe'});
  await fs.copyFile(path.join(backend, 'HaloCue.exe'), path.join(target, 'HaloCueBackend.exe'));
  // Compare staged app source with asar entries before the final public-tree audit.
  const asar = require('@electron/asar');
  const archive = path.join(target, 'resources/app.asar');
  const expected = (await fs.readdir(stage)).sort();
  const actual = asar.listPackage(archive).map(name => name.replace(/\\/g, '/').replace(/^\//, '')).sort();
  if (JSON.stringify(expected) !== JSON.stringify(actual)) throw new Error('Unexpected desktop asar contents');
  for (const name of expected) {
    if (!asar.extractFile(archive, name).equals(await fs.readFile(path.join(stage, name)))) throw new Error('Desktop asar source mismatch');
  }
  console.log(JSON.stringify({bundle: target, version, electron: '44.5.1', verifiedAsarFiles: expected}));
}
if (require.main === module) pack(...process.argv.slice(2)).catch(error => {console.error(error.message); process.exitCode = 1;});
module.exports = {pack};
