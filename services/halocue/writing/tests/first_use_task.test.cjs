const {test}=require('node:test');
const assert=require('node:assert/strict');
const {lesson}=require('../web/first-use-task.js');
test('teaching requires opting into the first task, never a new-work reminder',()=>{
  for(const status of ['offered','complete','dismissed','paused','legacy'])assert.equal(lesson({}, {status}),null);
  assert.equal(lesson({}, {status:'active'}).action,'create');
});
test('each step follows actual work state rather than pressing next',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'w'},record).step,2);
  assert.equal(lesson({workId:'w',hasIdea:true},record).action,'structure');
  assert.equal(lesson({workId:'w',planPending:true,hasIdea:true},record).action,'plan');
  assert.equal(lesson({workId:'w',sceneId:'s'},record).action,'draft');
});
test('manual authors need no model and dirty prose teaches saving',()=>{
  const record={status:'active',workId:'w',manual:true};
  assert.equal(lesson({workId:'w'},record).step,3);
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true},record).action,'manual');
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,dirty:true},record).action,'save');
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,dirty:true,emptyField:true},record).action,'write');
  assert.equal(lesson({workId:'w',atStructure:true},record).action,'add-scene');
  assert.match(lesson({workId:'w',compactNav:true},record).detail,/视图菜单/);
  assert.match(lesson({workId:'w',atStructure:true,addSceneVisible:false},record).detail,/展开场景栏/);
});
test('a candidate is not lesson completion; only a new saved revision completes it',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'w',sceneId:'s',atDraft:true,proposalId:'p'},record).action,'review');
  assert.notEqual(lesson({workId:'w',sceneId:'s',atDraft:true,revisionId:'old'},record).step,5);
  assert.equal(lesson({workId:'w',sceneId:'s',saved:true},record).step,5);
});

test('a confirmed direction continues scene planning unless the author chooses manual structure',()=>{
  const record={status:'active',workId:'w'};
  const input={workId:'w',hasIdea:true,hasDirection:true,atDiscussion:true};
  assert.equal(lesson(input,record).action,'arrange');
  assert.equal(lesson({...input,atDiscussion:false},record).action,'arrange');
  assert.equal(lesson({...input,hasNextAction:true},record).action,'next');
  assert.equal(lesson({...input,planPending:true,planKind:'story_structure'},record).action,'plan');
  assert.equal(lesson({...input,atStructure:true},record).action,'add-scene');
  assert.equal(lesson(input,{...record,manual:true}).action,'structure');
});
test('reading mode directs typing to the real edit switch while candidate review stays available',()=>{
  const input={workId:'w',sceneId:'s',atDraft:true,reading:true};
  const record={status:'active',workId:'w'};
  assert.equal(lesson(input,record).action,'edit');
  assert.equal(lesson({...input,canPrepare:true},record).action,'prepare');
  assert.equal(lesson({...input,canPrepare:true},{...record,manual:true}).action,'edit');
  assert.equal(lesson({...input,proposalId:'p'},record).action,'review');
  assert.equal(lesson({...input,proposalId:'p',dirty:true},record).action,'edit');
});
test('switching works or deleting the teaching scene cannot silently complete/rebind it',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workId:'other',saved:true},record).action,'return');
  assert.equal(lesson({workId:'w',targetMissing:true},record).action,'structure');
});
test('recovery, invalidated candidates and deleted works point to usable operations',()=>{
  const record={status:'active',workId:'w'};
  assert.equal(lesson({workMissing:true},record).action,'restart');
  assert.match(lesson({workMissing:true,canRestoreTeaching:true},record).title,/恢复/);
  assert.equal(lesson({workId:'w',atProjects:true},record).action,'open-work');
  assert.equal(lesson({workId:'w',atProjects:true,inTrash:true},record).action,'projects');
  assert.equal(lesson({workId:'w',recovery:true,hasIdea:true},record).action,'recover');
  assert.equal(lesson({workId:'w',recovery:true},{...record,manual:true}).action,'structure');
  const scene={workId:'w',sceneId:'s',atDraft:true};
  assert.equal(lesson({...scene,preparationRequired:true},record).action,'setup');
  assert.equal(lesson({...scene,contextEditing:true},record).action,'context');
  assert.equal(lesson({...scene,preparingScene:true},record).action,'wait');
  assert.equal(lesson({...scene,sceneBusy:true},record).action,'wait');
  assert.equal(lesson({...scene,sceneBusy:true,dirty:true},record).action,'save');
  assert.match(lesson({...scene,proposalSuperseded:true,canPrepare:true},record).title,/不能再用/);
  assert.equal(lesson({...scene,proposalSuperseded:true,canPrepare:true},{...record,manual:true}).action,'manual');
});
