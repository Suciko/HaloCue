const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const css=fs.readFileSync(path.join(__dirname,'../web/agent-workspace.css'),'utf8').split('/* The ideation workspace')[1].split('*/').slice(1).join('*/');
const rules=[...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([,selector,body])=>({selector,values:Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{6})\s*;/gi)].map(([,key,value])=>[key,value]))}));
function l(hex){const a=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*a[0]+.7152*a[1]+.0722*a[2];}
function ratio(a,b){a=l(a);b=l(b);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);}
for(const theme of ['light','dark'])test(`${theme} default text and action tokens stay legible`,()=>{
 const base=rules.find(r=>r.selector.trim()==='#app#app.hc-redesign[data-surface="works"]');
 const dark=rules.find(r=>r.selector.trim()==='html[data-theme="dark"] #app#app.hc-redesign[data-surface="works"]');
 const accent=rules.find(r=>r.selector.includes('data-appearance-palette="azure"')&&(theme==='dark'?!r.selector.includes(':not([data-theme'):r.selector.includes(':not([data-theme')));
 const v={...base.values,...(theme==='dark'?dark.values:{}),...accent.values};
 for(const [a,b] of [['--hc-text','--hc-panel'],['--hc-muted','--hc-panel'],['--hc-muted','--hc-rail'],['--hc-on-accent','--hc-accent'],['--hc-nav-ink','--hc-nav-selected']])assert.ok(ratio(v[a],v[b])>=4.5,`${a}/${b}`);
});
test('shared theme rules remain scoped to ideation and preserve high-contrast overrides',()=>{
 assert.ok(rules.every(r=>r.selector.includes('[data-surface="works"]')));
 assert.ok(rules.some(r=>r.selector.includes('data-appearance-contrast="high"')));
 assert.match(css,/--hc-accent: var\(--appearance-accent\)/);
});

test('functional rail follows the checked theme tokens instead of a fixed navy palette',()=>{
 assert.match(css,/--hc-nav-base: var\(--hc-rail\)/);
 assert.match(css,/--hc-nav-label: var\(--hc-muted\)/);
 assert.match(css,/--hc-nav-current: var\(--hc-nav-selected\)/);
 assert.match(css,/--hc-nav-current-ink: var\(--hc-nav-ink\)/);
 assert.match(css,/background: var\(--hc-nav-base\) !important/);
 assert.doesNotMatch(css,/border-right: 2px/);
 assert.doesNotMatch(css,/margin: 10px 6px/);
});
