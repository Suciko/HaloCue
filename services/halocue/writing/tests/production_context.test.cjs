const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const production=fs.readFileSync(path.join(__dirname,'../../production/ui/app.js'),'utf8');
const writing=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const embed=fs.readFileSync(path.join(__dirname,'../web/production-embed.js'),'utf8');
function slice(source,start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));}
function harness(){
 const calls=[],adopted=[],shown=[],errors=[];
 const context={state:{currentRun:null},api:url=>new Promise((resolve,reject)=>calls.push({url,resolve,reject})),
 adoptRunResult:r=>{adopted.push(r.run.run_id);context.state.currentRun=r.run;},loadTaskPreflight:async()=>{},updateShell:()=>{},
 showStage:s=>shown.push(s),currentRunOpeningStage:()=> 'review',trackActiveRunJob:()=>{},handleError:e=>errors.push(e)};
 vm.createContext(context);
 vm.runInContext(slice(production,'  let runOpeningEpoch = 0;','\n  async function createRun'),context);
 return {...context,context,calls,adopted,shown,errors};
}
test('rapid task selection discards the older response',async()=>{
 const h=harness();const a=h.openRun('a'),b=h.openRun('b');
 h.calls[1].resolve({run:{run_id:'b'}});assert.equal(await b,true);
 h.calls[0].resolve({run:{run_id:'a'}});assert.equal(await a,false);
 assert.deepEqual(h.adopted,['b']);assert.deepEqual(h.shown,['review']);
});
test('older failed request cannot replace the current success with an error',async()=>{
 const h=harness();const a=h.openRun('a'),b=h.openRun('b');
 h.calls[1].resolve({run:{run_id:'b'}});await b;
 h.calls[0].reject(new Error('old failure'));assert.equal(await a,false);
 assert.deepEqual(h.errors,[]);
});
test('current failure propagates to the embedded error boundary',async()=>{
 const h=harness();const a=h.openRun('missing');h.calls[0].reject(new Error('not found'));
 await assert.rejects(a,/not found/);assert.deepEqual(h.adopted,[]);
});
test('embedded boot does not restore the last standalone task',async()=>{
 for(const embedded of [true,false]){
  let restored=0;const shell={classList:{contains:()=>embedded}};
  const c={setupProfilePickers(){},setupSourceTabs(){},syncSourceReadAction(){},setupModernDropzone(){},refreshCapabilities:async()=>{},loadModelSettings:async()=>{},loadRuns:async()=>{},loadWritingWorksAndReleases:async()=>{},restoreSavedRun:async()=>restored++,$:()=>shell,openRun:async()=>{},handleError:e=>{throw e;}};
  vm.createContext(c);
  const boot=production.slice(production.indexOf('  const productionShell = $(".app-shell");'),production.lastIndexOf('\n})();'));
  vm.runInContext(boot,c);await shell.haloCueReady;assert.equal(restored,embedded?0:1);
 }
});
test('stable-ID deep links do not depend on the eight recent task buttons',async()=>{
 let requested='';const c={};vm.createContext(c);vm.runInContext(slice(embed,'  async function selectRun(','\n  async function open('),c);
 const shell={haloCueReady:Promise.resolve(),haloCueOpenRun:async id=>{requested=id;return true;}};
 assert.equal(await c.selectRun({querySelector:()=>shell},'old-task'),true);assert.equal(requested,'old-task');
 shell.haloCueOpenRun=async()=>{throw Object.assign(new Error('missing'),{status:404});};
 assert.equal(await c.selectRun({querySelector:()=>shell},'missing'),false);
});
test('production URL never inherits the active writing work',()=>{
 const c={URLSearchParams,state:{work:{id:'unrelated-work'}},location:{pathname:'/',search:'?section=production&run_id=run-a'},hcRoute:{section:'production',runId:'run-a',productionWorkId:''}};
 vm.createContext(c);vm.runInContext(slice(writing,'function routeUrl(){','\nfunction syncAppRoute'),c);
 assert.equal(c.routeUrl(),'/?section=production&run_id=run-a');
 c.hcRoute.productionWorkId='linked-work';assert.match(c.routeUrl(),/work_id=linked-work/);
 c.hcRoute.section='writing';assert.match(c.routeUrl(),/work_id=unrelated-work/);
});
test('explicit production URL wins over a stale release link elsewhere in the DOM',()=>{
 const stale={dataset:{openProduction:'wrong',workId:'wrong-work'}};
 const c={URLSearchParams,location:{search:'?section=production&run_id=right'},document:{querySelector:()=>stale}};
 vm.createContext(c);vm.runInContext(slice(embed,'  function linkedContext(','\n  function syncChrome'),c);
 assert.equal(c.linkedContext().runId,'right');assert.equal(c.linkedContext().workId,'');
 assert.equal(c.linkedContext({...stale,matches:()=>true}).runId,'wrong');
});
test('late preflight response cannot repaint another task',async()=>{
 let resolve;const c={state:{currentRun:{run_id:'a'}},api:()=>new Promise(r=>resolve=r),renderTaskPreflight:()=>assert.fail('stale repaint'),renderAiPreflight(){},loadAiPreflights:async()=>{},loadCharacterCatalog:async()=>{},toast(){}};
 vm.createContext(c);vm.runInContext(slice(production,'  async function loadTaskPreflight()','\n  async function loadCharacterCatalog'),c);
 const pending=c.loadTaskPreflight();c.state.currentRun={run_id:'b'};resolve({task:'a'});await pending;
 assert.equal(c.state.taskPreflight,undefined);
});

test('review command title follows the loaded run after in-page switching',()=>{
 const c={runTitle:{textContent:'Current task B'},commandTitle:{},taskButton:{},overviewButton:{disabled:false},compileProxy:{},compileButton:{disabled:true,textContent:'Compile'}};
 vm.createContext(c);
 vm.runInContext(slice(embed,'    const syncCommandbar = () => {','\n    const observer = new MutationObserver(syncCommandbar);')+';syncCommandbar();',c);
 assert.equal(c.commandTitle.textContent,'Current task B');
 c.runTitle.textContent='Current task C';vm.runInContext('syncCommandbar()',c);
 assert.equal(c.commandTitle.textContent,'Current task C');
});
test('writing and production scrolling respect reduced-motion preferences',()=>{
 for(const source of [production,fs.readFileSync(path.join(__dirname,'../web/writing-workbench.js'),'utf8')]){
  const line=source.split('\n').find(s=>s.includes('const scrollBehavior ='));
  for(const reduced of [true,false]){
   const c={window:{matchMedia:()=>({matches:reduced})}};vm.createContext(c);
   assert.equal(vm.runInContext(line+';scrollBehavior()',c),reduced?'instant':'smooth');
  }
  assert.doesNotMatch(source,/behavior:\s*['"]smooth['"]/);
 }
});

test('label sanitizer never overwrites the loaded run title',()=>{
 assert.match(embed,/sideHeader\.querySelector\("p:not\(#runTitle\)"\)/);
 assert.doesNotMatch(embed,/sideHeader\.querySelector\("p"\)/);
});

test('embedded source boundary carries the current-task/new-task split',()=>{
 assert.match(embed,/当前制作任务 · 来源已冻结/);
 assert.match(embed,/新建另一项制作/);
 assert.match(embed,/frozen_source_text/);
 assert.match(embed,/haloCueShowNewProduction/);
});
