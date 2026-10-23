import {build} from 'esbuild';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

process.chdir(fileURLToPath(new URL('.', import.meta.url)));
await build({entryPoints:['src/manuscript-document.js'], outfile:'../web/manuscript-document.js', bundle:true, minify:true, format:'iife', target:'es2022', legalComments:'eof'});
const packages=['prosemirror-model','prosemirror-state','prosemirror-view','prosemirror-commands','prosemirror-keymap','prosemirror-history','prosemirror-transform','orderedmap','rope-sequence','w3c-keyname'];
const notices=[];
for(const name of packages){
  const metadata=JSON.parse(await readFile(`node_modules/${name}/package.json`,'utf8'));
  const license=await readFile(`node_modules/${name}/LICENSE`,'utf8');
  notices.push(`${name} ${metadata.version}\n${metadata.repository?.url || metadata.repository || ''}\n\n${license}`);
}
await mkdir('../web/vendor/manuscript-document',{recursive:true});
await writeFile('../web/vendor/manuscript-document/LICENSES.txt',notices.join('\n\n---\n\n'));
