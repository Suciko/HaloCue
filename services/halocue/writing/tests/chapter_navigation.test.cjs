const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const route=source.slice(source.indexOf('function handleAppRouteClick(event){'),source.indexOf('\ndocument.addEventListener',source.indexOf('function handleAppRouteClick(event){')+10));
function setup(stage='draft',dirty=false){
 const chapters=[{id:'a',scenes:[{id:'a1',chapter_id:'a'},{id:'a2',chapter_id:'a'}]},{id:'b',scenes:[{id:'b1',chapter_id:'b'}]},{id:'empty',scenes:[]}];
 const state={route:{section:'writing'},surface:'writing',stage,writingChapterId:'a',sceneId:'a2',work:{id:'w',chapters},manuscriptDirty:dirty,context:{scene_id:'a2'}};
 const calls=[],saves=[];let pending;
 const ctx={state,HC_WRITING_STAGES:new Set(['draft','structure','release']),document:{getElementById:()=>null},claimAppEvent(){},requestManuscriptNavigation:fn=>{pending=fn},navigateRoute:patch=>{calls.push(patch);state.stage=patch.stage;state.sceneId=patch.sceneId;state.writingChapterId=patch.chapterId},persistWritingTarget:(...args)=>{saves.push(args);return Promise.resolve()},toast(){}};
 vm.createContext(ctx);vm.runInContext(route,ctx);
 const click=id=>{const b={dataset:{writingChapter:id},getAttribute(){return null},closest(){return null}};ctx.handleAppRouteClick({target:{closest:()=>b},preventDefault(){}})};
 return {state,calls,saves,click,accept:()=>pending?.()};
}
for(const stage of ['draft','structure','release'])test(`chapter switch preserves ${stage}`,()=>{
 const f=setup(stage);f.click('b');assert.equal(f.calls[0].stage,stage);assert.equal(f.state.sceneId,'b1');assert.equal(f.state.context,null);assert.equal(f.saves.length,1);
});
test('same chapter is a no-op, retaining active scene and dirty editor',()=>{
 const f=setup('draft',true);f.click('a');f.accept();assert.equal(f.calls.length,0);assert.equal(f.state.sceneId,'a2');assert.equal(f.state.manuscriptDirty,true);
});
test('dirty navigation does not mutate scope until the user decides',()=>{
 const f=setup('draft',true);f.click('b');assert.equal(f.calls.length,0);assert.equal(f.state.context.scene_id,'a2');assert.equal(f.state.sceneId,'a2');f.accept();assert.equal(f.calls[0].stage,'draft');
});
test('empty chapter stays in draft and has no unrelated selected scene',()=>{
 const f=setup();f.click('empty');assert.equal(f.calls[0].stage,'draft');assert.equal(f.state.sceneId,null);
 const ctx={state:f.state,scenes:()=>f.state.work.chapters.flatMap(c=>c.scenes)};vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function selectedScene(){'),source.indexOf('\nfunction ',source.indexOf('function selectedScene(){')+10)),ctx);
 assert.equal(ctx.selectedScene(),undefined);
});